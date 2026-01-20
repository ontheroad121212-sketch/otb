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
    """
    데이터프레임의 첫 번째 열을 훑어서 '진짜 날짜'가 언제인지 찾아냄
    """
    first_col = df.iloc[:, 0]
    # errors='coerce'를 써서 '소계', '구분' 같은 문자는 NaT(시간아님)로 변환
    dates = pd.to_datetime(first_col, errors='coerce')
    valid_dates = dates.dropna()
    
    if not valid_dates.empty:
        return valid_dates.iloc[0], valid_dates.index[0]
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
            temp_df = pd.read_excel(file, header=None)
            first_date, start_row_idx = find_first_date(temp_df)
            
            if first_date:
                month_num = first_date.month
                month_map[month_num] = (file, start_row_idx)
        except Exception as e:
            st.error(f"파일 분류 중 오류 ({file.name}): {e}")

    # [2] 탭별 리포트 생성
    for i, tab in enumerate(tabs):
        current_month = i + 1
        with tab:
            if current_month in month_map:
                file, start_row = month_map[current_month]
                file.seek(0)
                
                try:
                    df_raw = pd.read_excel(file, header=None)
                    df_data = df_raw.iloc[start_row:].copy()
                    
                    df_clean = pd.DataFrame()
                    
                    # [핵심 수정] errors='coerce' 추가 -> '소계' 같은 문자는 NaT로 변환
                    df_clean['Date'] = pd.to_datetime(df_data.iloc[:, 0], errors='coerce')
                    
                    # NaT(날짜가 아닌 행) 제거 -> 즉, '소계', '합계' 행 삭제됨
                    df_clean = df_clean.dropna(subset=['Date'])

                    # 나머지 데이터 숫자 변환
                    df_clean['RMS'] = pd.to_numeric(df_data.iloc[:, -5], errors='coerce').fillna(0)
                    df_clean['OCC'] = pd.to_numeric(df_data.iloc[:, -4], errors='coerce').fillna(0)
                    df_clean['ADR'] = pd.to_numeric(df_data.iloc[:, -3], errors='coerce').fillna(0)
                    df_clean['REV'] = pd.to_numeric(df_data.iloc[:, -1], errors='coerce').fillna(0)
                    
                    df_clean['DateStr'] = df_clean['Date'].dt.strftime('%Y-%m-%d')
                    
                    # ----------------------
                    # 상단 요약 (Budget)
                    # ----------------------
                    total_rev = df_clean['REV'].sum()
                    budget = BUDGET_DATA.get(current_month, 0)
                    achv_rate = (total_rev / budget * 100) if budget > 0 else 0
                    diff_val = total_rev - budget
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
                    
                    if df_prev is not None:
                        if 'Date' in df_prev.columns:
                            df_prev['DateStr'] = pd.to_datetime(df_prev['Date']).dt.strftime('%Y-%m-%d')
                        
                        merged = pd.merge(
                            df_clean, 
                            df_prev[['DateStr', 'REV', 'RMS']], 
                            on='DateStr', 
                            how='left', 
                            suffixes=('', '_prev')
                        )
                        
                        # 비교 데이터가 없으면 오늘 값으로 채우기 (변화량 0)
                        merged['REV_prev'] = merged['REV_prev'].fillna(merged['REV'])
                        merged['RMS_prev'] = merged['RMS_prev'].fillna(merged['RMS'])
                        
                        merged['Var_REV'] = merged['REV'] - merged['REV_prev']
                        merged['Var_RMS'] = merged['RMS'] - merged['RMS_prev']
                        
                        final_show = merged[['DateStr', 'RMS', 'RMS_prev', 'Var_RMS', 'REV', 'REV_prev', 'Var_REV']].copy()
                    else:
                        final_show = df_clean[['DateStr', 'RMS', 'RMS', 'REV', 'REV']].copy()
                        final_show.columns = ['DateStr', 'RMS', 'RMS_prev', 'REV', 'REV_prev']
                        final_show['Var_RMS'] = 0
                        final_show['Var_REV'] = 0

                    final_show.columns = ['Date', 'Rms(Act)', 'Rms(Pre)', 'Rms(Pick)', 'Rev(Act)', 'Rev(Pre)', 'Rev(Pick)']
                    
                    # 데이터프레임 표시
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
                    
                    if st.button(f"💾 {current_month}월 데이터 확정 및 저장", key=f"save_{current_month}"):
                        save_today_data(current_month, df_clean)
                        st.toast(f"✅ {current_month}월 데이터가 안전하게 저장되었습니다!", icon="cloud")
                        
                except Exception as e:
                    st.error(f"데이터 처리 중 에러 발생: {e}")
            else:
                st.info(f"📂 {current_month}월 파일을 아직 업로드하지 않았습니다.")
