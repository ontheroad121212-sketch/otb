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
    
    # [1] 파일 분류 (월별로 리스트에 담기)
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

            # Case A: 파일이 2개다? (오늘 vs 어제 파일 직접 비교)
            if len(files) >= 2:
                # 매출(REV) 합계가 더 큰 쪽을 '오늘(Current)'로 간주 (보통 누적되므로)
                # 만약 같다면 파일 이름 등 다른 로직이 필요하지만, 일단 매출 기준
                f1 = files[0]
                f2 = files[1]
                
                rev1 = f1['data']['REV'].sum()
                rev2 = f2['data']['REV'].sum()
                
                if rev1 >= rev2:
                    df_curr = f1['data']
                    df_prev = f2['data']
                    mode_msg = f"🔥 **업로드된 파일끼리 비교 중** ({f1['file_name']} vs {f2['file_name']})"
                else:
                    df_curr = f2['data']
                    df_prev = f1['data']
                    mode_msg = f"🔥 **업로드된 파일끼리 비교 중** ({f2['file_name']} vs {f1['file_name']})"

            # Case B: 파일이 1개다? (DB와 비교)
            elif len(files) == 1:
                df_curr = files[0]['data']
                df_prev = get_yesterday_data(current_month)
                if df_prev is not None:
                    mode_msg = "☁️ **DB 저장된 과거 데이터와 비교 중**"
                else:
                    mode_msg = "⚠️ **비교할 과거 데이터가 없습니다.** (오늘 저장하면 내일부터 나옵니다)"

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
            # 2. 상세 리포트 (Comparison)
            # ----------------------
            if df_prev is not None:
                # 날짜 포맷 통일 및 병합
                if 'DateStr' not in df_prev.columns:
                    df_prev['Date'] = pd.to_datetime(df_prev['Date'])
                    df_prev['DateStr'] = df_prev['Date'].dt.strftime('%Y-%m-%d')

                merged = pd.merge(
                    df_curr, 
                    df_prev[['DateStr', 'REV', 'RMS']], 
                    on='DateStr', 
                    how='left', 
                    suffixes=('', '_prev')
                )
                
                # 없는 값 처리
                merged['REV_prev'] = merged['REV_prev'].fillna(merged['REV'])
                merged['RMS_prev'] = merged['RMS_prev'].fillna(merged['RMS'])
                
                # 변화량 계산
                merged['Var_REV'] = merged['REV'] - merged['REV_prev']
                merged['Var_RMS'] = merged['RMS'] - merged['RMS_prev']
                
                final_show = merged[['DateStr', 'RMS', 'RMS_prev', 'Var_RMS', 'REV', 'REV_prev', 'Var_REV']].copy()
            else:
                # 비교 대상 없을 때
                final_show = df_curr[['DateStr', 'RMS', 'RMS', 'REV', 'REV']].copy()
                final_show.columns = ['DateStr', 'RMS', 'RMS_prev', 'REV', 'REV_prev']
                final_show['Var_RMS'] = 0
                final_show['Var_REV'] = 0

            # 컬럼명 정리
            final_show.columns = ['Date', 'Rms(Act)', 'Rms(Pre)', 'Rms(Pick)', 'Rev(Act)', 'Rev(Pre)', 'Rev(Pick)']

            st.dataframe(
                final_show,
                column_config={
                    "Rev(Act)": st.column_config.NumberColumn(format="%d"),
                    "Rev(Pre)": st.column_config.NumberColumn(format="%d"),
                    "Rev(Pick)": st.column_config.NumberColumn(format="%d"),
                },
                height=600,
                use_container_width=True
            )
            
            # ----------------------
            # 3. 저장 버튼
            # ----------------------
            # 파일이 2개일 땐 'Current'로 선정된 놈을 저장해야 내일 또 비교가 됨
            if st.button(f"💾 {current_month}월 데이터 확정 및 저장", key=f"save_{current_month}"):
                save_today_data(current_month, df_curr)
                st.toast(f"✅ {current_month}월 데이터가 안전하게 저장되었습니다!", icon="💾")
