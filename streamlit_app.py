import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import io

# ------------------------------------------------------------------
# 1. 기본 설정 및 Firebase 연결
# ------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Daily Pace Report")

# 스타일 커스텀 (화면 너비 최대한 활용 + 테이블 헤더 고정 등)
st.markdown("""
<style>
    .block-container {padding-top: 1rem; padding-bottom: 0rem; padding-left: 1rem; padding-right: 1rem;}
    iframe[title="streamlit.dataframe"] {width: 100% !important;}
</style>
""", unsafe_allow_html=True)

if not firebase_admin._apps:
    try:
        key_dict = dict(st.secrets["firebase"])
        cred = credentials.Certificate(key_dict)
        firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"Firebase 연결 오류: Secrets 설정을 확인해주세요. ({e})")
        st.stop()

db = firestore.client()

# ------------------------------------------------------------------
# 2. 예산(Budget) 설정
# ------------------------------------------------------------------
BUDGET_DATA = {
    1: 514992575,  
    2: 480000000,
    3: 520000000,
    4: 600000000
}

# ------------------------------------------------------------------
# 3. 함수 정의
# ------------------------------------------------------------------

def find_first_date(df):
    """데이터프레임에서 진짜 날짜가 시작되는 위치 찾기"""
    first_col = df.iloc[:, 0]
    dates = pd.to_datetime(first_col, errors='coerce')
    valid_dates = dates.dropna()
    if not valid_dates.empty:
        return valid_dates.iloc[0], valid_dates.index[0]
    return None, None

def process_excel_file(file):
    """엑셀 파일을 읽어서 깨끗한 DataFrame으로 변환"""
    try:
        file.seek(0)
        temp_df = pd.read_excel(file, header=None)
        first_date, start_row = find_first_date(temp_df)
        
        if first_date is None:
            return None, None

        # 데이터 로드
        df_raw = pd.read_excel(file, header=None)
        df_data = df_raw.iloc[start_row:].copy()
        
        df_clean = pd.DataFrame()
        
        # 날짜 및 데이터 파싱
        df_clean['Date'] = pd.to_datetime(df_data.iloc[:, 0], errors='coerce')
        df_clean = df_clean.dropna(subset=['Date'])

        # 컬럼 매핑 (맨뒤: 매출, -5: 객실수 등)
        df_clean['RMS'] = pd.to_numeric(df_data.iloc[:, -5], errors='coerce').fillna(0)
        df_clean['OCC'] = pd.to_numeric(df_data.iloc[:, -4], errors='coerce').fillna(0)
        df_clean['ADR'] = pd.to_numeric(df_data.iloc[:, -3], errors='coerce').fillna(0)
        df_clean['REV'] = pd.to_numeric(df_data.iloc[:, -1], errors='coerce').fillna(0)
        
        df_clean['DateStr'] = df_clean['Date'].dt.strftime('%Y-%m-%d')
        df_clean['WeekDay'] = df_clean['Date'].dt.strftime('%a') # 요일 추가
        
        return df_clean, first_date.month
    except Exception as e:
        return None, None

def get_yesterday_data(month_num):
    doc_ref = db.collection('daily_reports').document(f"2026-{month_num:02d}")
    doc = doc_ref.get()
    if doc.exists:
        data = doc.to_dict()
        try:
            return pd.read_json(io.StringIO(data['json_data']), orient='records')
        except:
            return None
    return None

def save_today_data(month_num, df):
    json_str = df.to_json(orient='records', date_format='iso')
    doc_ref = db.collection('daily_reports').document(f"2026-{month_num:02d}")
    doc_ref.set({
        'json_data': json_str,
        'updated_at': firestore.SERVER_TIMESTAMP
    })

# 스타일링 함수 (마이너스 빨간색 처리)
def color_negative_red(val):
    if isinstance(val, (int, float)) and val < 0:
        return 'color: red; font-weight: bold;'
    return 'color: black;'

# ------------------------------------------------------------------
# 4. 메인 UI 구성
# ------------------------------------------------------------------
st.title("🏨 One-Click Daily Pace Report")
st.caption("💡 팁: 처음 사용할 땐 '어제 파일'과 '오늘 파일'을 같이 업로드하면 바로 비교됩니다.")

uploaded_files = st.file_uploader(
    "파일을 몽땅 드래그해서 넣으세요 (4개 또는 8개)", 
    accept_multiple_files=True,
    type=['xlsx']
)

if uploaded_files:
    tabs = st.tabs(["1월 (JAN)", "2월 (FEB)", "3월 (MAR)", "4월 (APR)"])
    
    # [1] 파일 분류
    month_files_map = {1: [], 2: [], 3: [], 4: []}
    
    for file in uploaded_files:
        df, month = process_excel_file(file)
        if df is not None and month in month_files_map:
            month_files_map[month].append({'file_name': file.name, 'data': df})

    # [2] 탭별 로직 실행
    for i, tab in enumerate(tabs):
        current_month = i + 1
        with tab:
            files = month_files_map.get(current_month, [])
            
            if not files:
                st.info(f"📂 {current_month}월 데이터가 없습니다.")
                continue

            # 변수 초기화
            df_curr = None
            df_prev = None
            mode_msg = ""

            # 파일 비교 로직 (Case A: 파일 2개, Case B: DB 비교)
            if len(files) >= 2:
                f1, f2 = files[0], files[1]
                if f1['data']['REV'].sum() >= f2['data']['REV'].sum():
                    df_curr, df_prev = f1['data'], f2['data']
                else:
                    df_curr, df_prev = f2['data'], f1['data']
                mode_msg = f"🔥 **업로드된 파일끼리 비교 중**"
            elif len(files) == 1:
                df_curr = files[0]['data']
                df_prev = get_yesterday_data(current_month)
                if df_prev is not None:
                    mode_msg = "☁️ **DB 데이터와 비교 중**"
                else:
                    mode_msg = "⚠️ **비교할 과거 데이터가 없습니다.**"

            # ----------------------
            # 1. 상단 요약 (Budget)
            # ----------------------
            total_rev = df_curr['REV'].sum()
            budget = BUDGET_DATA.get(current_month, 0)
            achv_rate = (total_rev / budget * 100) if budget > 0 else 0
            diff_val = total_rev - budget
            diff_color = "red" if diff_val < 0 else "blue"
            
            st.markdown(f"""
            ### 📊 {current_month}월 Performance
            {mode_msg}
            | Category | Budget | Actual | Vs Budget | Achv % |
            | :--- | :---: | :---: | :---: | :---: |
            | **Total Rev** | {budget:,.0f} | **{total_rev:,.0f}** | <span style='color:{diff_color}'>{diff_val:,.0f}</span> | **{achv_rate:.1f}%** |
            """, unsafe_allow_html=True)
            
            st.divider()

            # ----------------------
            # 2. 상세 리포트 (데이터 가공) - 여기가 수정됨!
            # ----------------------
            # 오늘 데이터 준비
            display_df = df_curr[['DateStr', 'WeekDay', 'RMS', 'OCC', 'ADR', 'REV']].copy()
            display_df.columns = ['Date', 'Day', 'Curr_RMS', 'Curr_OCC', 'Curr_ADR', 'Curr_REV']

            # 어제 데이터 병합
            if df_prev is not None:
                if 'DateStr' not in df_prev.columns:
                    df_prev['Date'] = pd.to_datetime(df_prev['Date'])
                    df_prev['DateStr'] = df_prev['Date'].dt.strftime('%Y-%m-%d')
                
                # [수정] df_prev 컬럼명을 강제로 변경해서 Key Error 방지
                # 필요한 컬럼만 뽑아서 이름 변경
                prev_subset = df_prev[['DateStr', 'RMS', 'OCC', 'ADR', 'REV']].copy()
                prev_subset.columns = ['DateStr', 'RMS_prev', 'OCC_prev', 'ADR_prev', 'REV_prev']

                # 이제 병합 (이름이 다르니 헷갈릴 일 없음)
                merged = pd.merge(display_df, prev_subset, left_on='Date', right_on='DateStr', how='left')
                
                # 결측치 채우기 (비교값이 없으면 오늘 값으로 대체)
                merged['Prev_RMS'] = merged['RMS_prev'].fillna(merged['Curr_RMS'])
                merged['Prev_OCC'] = merged['OCC_prev'].fillna(merged['Curr_OCC'])
                merged['Prev_ADR'] = merged['ADR_prev'].fillna(merged['Curr_ADR'])
                merged['Prev_REV'] = merged['REV_prev'].fillna(merged['Curr_REV'])

                # 변화량 계산 (Growth)
                merged['Var_RMS'] = merged['Curr_RMS'] - merged['Prev_RMS']
                merged['Var_OCC'] = merged['Curr_OCC'] - merged['Prev_OCC']
                merged['Var_ADR'] = merged['Curr_ADR'] - merged['Prev_ADR']
                merged['Var_REV'] = merged['Curr_REV'] - merged['Prev_REV']
                
                # 최종 컬럼 순서 재배치 (어제 | 오늘 | 변화량)
                final_df = merged[[
                    'Date', 'Day',
                    'Prev_RMS', 'Prev_OCC', 'Prev_ADR', 'Prev_REV',
                    'Curr_RMS', 'Curr_OCC', 'Curr_ADR', 'Curr_REV',
                    'Var_RMS', 'Var_OCC', 'Var_ADR', 'Var_REV'
                ]]
            else:
                # 비교 데이터 없을 때
                final_df = display_df.copy()
                # 빈 컬럼 추가
                final_df['Prev_RMS'] = final_df['Curr_RMS']
                final_df['Prev_OCC'] = final_df['Curr_OCC']
                final_df['Prev_ADR'] = final_df['Curr_ADR']
                final_df['Prev_REV'] = final_df['Curr_REV']
                final_df['Var_RMS'] = 0
                final_df['Var_OCC'] = 0
                final_df['Var_ADR'] = 0
                final_df['Var_REV'] = 0
                
                final_df = final_df[[
                    'Date', 'Day',
                    'Prev_RMS', 'Prev_OCC', 'Prev_ADR', 'Prev_REV',
                    'Curr_RMS', 'Curr_OCC', 'Curr_ADR', 'Curr_REV',
                    'Var_RMS', 'Var_OCC', 'Var_ADR', 'Var_REV'
                ]]

            # ----------------------
            # 3. 스타일링 (Pandas Styler)
            # ----------------------
            # 컬럼 이름 깔끔하게 변경
            final_df.columns = [
                'Date', 'Day', 
                'Prev RMS', 'Prev OCC', 'Prev ADR', 'Prev REV', 
                'Curr RMS', 'Curr OCC', 'Curr ADR', 'Curr REV', 
                'Pick RMS', 'Pick OCC', 'Pick ADR', 'Pick REV'
            ]

            # 포맷 설정 (천단위 콤마, 소수점)
            format_dict = {
                'Prev RMS': '{:,.0f}', 'Prev OCC': '{:.1f}%', 'Prev ADR': '{:,.0f}', 'Prev REV': '{:,.0f}',
                'Curr RMS': '{:,.0f}', 'Curr OCC': '{:.1f}%', 'Curr ADR': '{:,.0f}', 'Curr REV': '{:,.0f}',
                'Pick RMS': '{:+,.0f}', 'Pick OCC': '{:+.1f}%', 'Pick ADR': '{:+,.0f}', 'Pick REV': '{:+,.0f}'
            }

            # 스타일 적용
            styler = final_df.style.format(format_dict)
            
            # 1) 마이너스 빨간색
            styler = styler.map(color_negative_red, subset=['Pick RMS', 'Pick OCC', 'Pick ADR', 'Pick REV'])
            
            # 2) 히트맵 (상위/하위 데이터 표시)
            styler = styler.background_gradient(cmap='Blues', subset=['Curr RMS', 'Curr REV'])
            styler = styler.background_gradient(cmap='Oranges', subset=['Curr OCC'])

            # 화면 출력
            st.dataframe(styler, height=800, use_container_width=True, hide_index=True)
            
            # ----------------------
            # 4. 저장 버튼
            # ----------------------
            if st.button(f"💾 {current_month}월 데이터 확정 및 저장", key=f"save_{current_month}"):
                save_today_data(current_month, df_curr)
                st.toast(f"✅ {current_month}월 데이터가 안전하게 저장되었습니다!", icon="💾")
