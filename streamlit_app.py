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
# 3. 함수 정의 (스마트한 엑셀 처리)
# ------------------------------------------------------------------

def find_first_date(df):
    """
    데이터프레임의 첫 번째 열을 훑어서 '진짜 날짜'가 언제인지 찾아냄
    """
    # 첫 번째 열을 강제로 날짜로 변환 시도 (에러나면 NaT로 처리)
    first_col = df.iloc[:, 0]
    dates = pd.to_datetime(first_col, errors='coerce')
    
    # 날짜가 유효한 행들만 남김
    valid_dates = dates.dropna()
    
    if not valid_dates.empty:
        return valid_dates.iloc[0], valid_dates.index[0] # 첫 날짜와 그 행 번호 반환
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

uploaded_files = st.file_uploader(
    "1월~4월 RAW 데이터 파일을 모두 드래그해서 넣으세요", 
    accept_multiple_files=True,
    type=['xlsx']
)

if uploaded_files:
    tabs = st.tabs(["1월 (JAN)", "2월 (FEB)", "3월 (MAR)", "4월 (APR)"])
    
    # [1] 파일을 미리 읽어서 몇 월 파일인지 분류
    month_map = {}
    
    for file in uploaded_files:
        try:
            # 헤더 없이 일단 읽음
            temp_df = pd.read_excel(file, header=None)
            
            # 날짜 찾기 함수 실행
            first_date, start_row_idx = find_first_date(temp_df)
            
            if first_date:
                month_num = first_date.month
                month_map[month_num] = (file, start_row_idx) # 파일과 데이터 시작 위치 저장
        except Exception as e:
            st.error(f"파일 분류 중 오류 ({file.name}): {e}")

    # [2] 탭별 리포트 생성
    for i, tab in enumerate(tabs):
        current_month = i + 1
        with tab:
            if current_month in month_map:
                file, start_row = month_map[current_month]
                file.seek(0) # 파일 포인터 초기화
                
                try:
                    # 데이터 시작 위치(start_row)를 알았으니 거기부터 다시 읽음
                    # header=start_row-2 (헤더가 2줄 위에 있다고 가정) 하거나
                    # 그냥 헤더 없이 읽어서 인덱싱으로 처리하는게 가장 안전
                    
                    df_raw = pd.read_excel(file, header=None)
                    
                    # 데이터 영역만 자르기 (날짜가 시작되는 행부터 끝까지)
                    df_data = df_raw.iloc[start_row:].copy()
                    
                    # 컬럼 매핑 (이미지2 기준)
                    # 0: 날짜, 맨뒤(-1): 매출, 맨뒤-1: RevPAR, -3: 객단가, -4: 점유율, -5: 객실수
                    df_clean = pd.DataFrame()
                    df_clean['Date'] = pd.to_datetime(df_data.iloc[:, 0])
                    
                    # 중요: 엑셀 컬럼 위치가 정확해야 합니다.
                    # 만약 숫자가 이상하면 이 인덱스(-1, -3 등)를 조절해야 합니다.
                    df_clean['RMS'] = pd.to_numeric(df_data.iloc[:, -5], errors='coerce').fillna(0)
                    df_clean['OCC'] = pd.to_numeric(df_data.iloc[:, -4], errors='coerce').fillna(0)
                    df_clean['ADR'] = pd.to_numeric(df_data.iloc[:, -3], errors='coerce').fillna(0)
                    df_clean['REV'] = pd.to_numeric(df_data.iloc[:, -1], errors='coerce').fillna(0)
                    
                    # 날짜 문자열 컬럼 추가 (매칭용)
                    df_clean['DateStr'] = df_clean['Date'].dt.strftime('%Y-%m-%d')
                    
                    # ----------------------
                    # 상단 요약 (Budget)
                    # ----------------------
                    total_rev = df_clean['REV'].sum()
                    budget = BUDGET_DATA.get(current_month, 0)
                    achv_rate = (total_rev / budget * 100) if budget > 0 else 0
                    diff_val = total_rev - budget
                    
                    # 색상 서식
                    diff_color = "red" if diff_val < 0 else "blue"
                    
                    st.markdown(f"""
                    ### 📊 {current_month}월 Performance
                    | Category | Budget | Actual | Vs Budget | Achv % |
                    | :--- | :---: | :---: | :---: | :---: |
                    | **Total Rev** | {budget:,.0f} | **{total_rev:,.0f}** | <span style='color:{diff_color}'>{diff_val:,.0f}</span> | **{achv_rate:.1f}%** |
                    """, unsafe_allow_html=True)
                    
                    st.divider()
                    
                    # ----------------------
                    # Daily Report (Comparison)
                    # ----------------------
                    df_prev = get_yesterday_data(current_month)
                    
                    display_df = df_clean.copy()
                    
                    if df_prev is not None:
                         # 저장된 데이터 날짜 포맷 통일
                        if 'Date' in df_prev.columns:
                            df_prev['DateStr'] = pd.to_datetime(df_prev['Date']).dt.strftime('%Y-%m-%d')
                        
                        # 병합
                        merged = pd.merge(
                            df_clean, 
                            df_prev[['DateStr', 'REV', 'RMS']], 
                            on='DateStr', 
                            how='left', 
                            suffixes=('', '_prev')
                        )
                        
                        # 변화량 계산
                        merged['PickUp_REV'] = merged['REV'] - merged['REV_prev'].fillna(merged['REV']) # 없으면 0변화가 아니라 당일값으로? 보통은 0처리
                        # *수정: 전일 데이터가 없으면 변화량은 0이어야 함 (또는 신규발생)
                        # 여기서는 "전일 데이터가 없으면 변화량 0"으로 처리
                        merged['PickUp_REV'] = merged['REV'] - merged['REV_prev'].fillna(merged['REV']) 
                        # 로직 수정: 비교대상이 없으면 변화량 0 (즉, 어제값=오늘값으로 가정) 
                        # 혹은 아예 신규 예약으로 칠거면 fillna(0) -> 이 경우 전체 매출이 픽업으로 잡힘.
                        # 보통 Pace Report는 전일자 파일과 비교이므로 fillna(0)하면 첫날 전체가 픽업이 됨. 
                        # 일단 fillna(0)으로 해서 "전체 증가"로 보이게 하거나, 첫날은 0으로 숨기는게 나음.
                        
                        # 깔끔한 로직: 
                        # DB값이 있으면 차이 계산, 없으면 0
                        merged['REV_prev'] = merged['REV_prev'].fillna(merged['REV']) # 비교값 없으면 변화 없음 처리
                        merged['RMS_prev'] = merged['RMS_prev'].fillna(merged['RMS'])
                        
                        merged['Var_REV'] = merged['REV'] - merged['REV_prev']
                        merged['Var_RMS'] = merged['RMS'] - merged['RMS_prev']
                        
                        # 컬럼 정리
                        final_show = merged[['DateStr', 'RMS', 'RMS_prev', 'Var_RMS', 'REV', 'REV_prev', 'Var_REV']].copy()
                    else:
                        # 비교 데이터 없음
                        final_show = df_clean[['DateStr', 'RMS', 'RMS', 'REV', 'REV']].copy()
                        final_show.columns = ['DateStr', 'RMS', 'RMS_prev', 'REV', 'REV_prev']
                        final_show['Var_RMS'] = 0
                        final_show['Var_REV'] = 0

                    # 컬럼 이름 예쁘게
                    final_show.columns = ['Date', 'Rms(Act)', 'Rms(Pre)', 'Rms(Pick)', 'Rev(Act)', 'Rev(Pre)', 'Rev(Pick)']
                    
                    # 데이터프레임 표시 (하이라이트 기능 사용)
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
                    # 저장 버튼
                    # ----------------------
                    if st.button(f"💾 {current_month}월 데이터 확정 및 저장", key=f"save_{current_month}"):
                        save_today_data(current_month, df_clean)
                        st.toast(f"✅ {current_month}월 데이터가 안전하게 저장되었습니다!", icon="cloud")
                        
                except Exception as e:
                    st.error(f"데이터 처리 중 에러 발생: {e}")
            else:
                st.info(f"📂 {current_month}월 파일을 아직 업로드하지 않았습니다.")
