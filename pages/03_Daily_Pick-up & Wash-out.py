import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
import re
from datetime import datetime
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
import time

# ==============================================================================
# 0. 사용자 정의 버짓 데이터 (2026년 목표 매출)
# ==============================================================================
# 2026년도 월별 목표 매출 데이터입니다.
BUDGET_DATA = { 
    1: 514992575, 
    2: 786570856, 
    3: 529599040, 
    4: 695351004,
    5: 903705440,
    6: 808203820,
    7: 1231949142,
    8: 1388376999,
    9: 952171506,
    10: 897171539,
    11: 667146771,
    12: 804030110 
}

# ==============================================================================
# 1. 페이지 설정 및 CSS 스타일링
# ==============================================================================
st.set_page_config(
    page_title="ARI Final Integrity", 
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    /* 전체 레이아웃 여백 조정 */
    .block-container {
        padding-top: 1rem;
        padding-bottom: 5rem;
    }
    
    /* 주요 지표(Metric) 숫자 스타일 크게 */
    div[data-testid="stMetricValue"] {
        font-size: 26px !important;
        font-weight: 900;
        color: #0f172a;
    }
    
    /* 주요 지표 라벨 스타일 */
    div[data-testid="stMetricLabel"] {
        font-size: 15px !important;
        font-weight: 700;
        color: #64748b;
    }
    
    /* 탭 버튼 스타일 */
    button[data-baseweb="tab"] {
        font-size: 16px !important;
        font-weight: 700;
    }
    
    /* 데이터프레임 합계(Total) 행 노란색 강조 */
    [data-testid="stDataFrame"] table tr:last-child td {
        font-weight: 900 !important;
        background-color: #fff9c4 !important;
        color: #000000 !important;
        border-top: 2px solid #000000 !important;
    }

    /* 사이드바 삭제 버튼 빨간색 스타일 */
    div.stButton > button:first-child {
        border-color: #ff4b4b;
        color: #ff4b4b;
    }
    div.stButton > button:first-child:hover {
        background-color: #ff4b4b;
        color: white;
    }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 2. 파이어베이스 데이터베이스 연결
# ==============================================================================
if not firebase_admin._apps:
    try:
        cred = credentials.Certificate(dict(st.secrets["firebase"]))
        firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"🔥 데이터베이스 연결 실패: {e}")
        st.stop()

db = firestore.client()
COLLECTION_NAME = "revenue_integrity_history"

# ==============================================================================
# 3. 데이터 전처리 및 유틸리티 함수
# ==============================================================================

def clean_numeric_columns(df):
    """
    데이터프레임 내의 숫자 컬럼들을 강제로 숫자형(Float/Int)으로 변환합니다.
    천단위 콤마(,)나 원화 기호 등을 정밀 제거합니다.
    """
    target_cols = [
        'RN', 'Room_Revenue', 'Total_Revenue', 'ADR_Room', 'ADR_Total', 
        'Lead_Time', 'OTB_Rev', 'Budget_Rev', 'Budget_Achiev', 'OTB_RN', 
        'OTB_ADR', 'Actual_Rev', 'Actual_RN', 'Rooms', 'Nights'
    ]
    
    for col in target_cols:
        if col in df.columns:
            # 모든 숫자가 아닌 문자를 제거하는 강력한 클렌징 로직
            df[col] = pd.to_numeric(
                df[col].astype(str).str.replace(r'[^0-9.-]', '', regex=True), 
                errors='coerce'
            ).fillna(0)
            
    # ADR(객실단가) 재계산 로직 (ZeroDivision 방지)
    if 'RN' in df.columns:
        if 'Room_Revenue' in df.columns:
            df['ADR_Room'] = np.where(df['RN'] != 0, df['Room_Revenue'] / df['RN'], 0)
        if 'Total_Revenue' in df.columns:
            df['ADR_Total'] = np.where(df['RN'] != 0, df['Total_Revenue'] / df['RN'], 0)
            
    return df

def save_to_firestore(df):
    """Firestore 저장 로직"""
    try:
        if df.empty:
            return False
        # Firestore 전송용 JSON 직렬화 가능 객체로 변환
        records = df.fillna(0).astype(str).to_dict(orient='records')
        db.collection(COLLECTION_NAME).add({
            'data': records,
            'uploaded_at': datetime.now(),
            'snapshot_date': datetime.now().strftime('%Y-%m-%d')
        })
        return True
    except Exception as e:
        st.error(f"❌ 데이터 저장 중 오류 발생: {e}")
        return False

@st.cache_data(ttl=0)
def load_data_from_firestore():
    """Firestore 데이터 로드"""
    try:
        docs = db.collection(COLLECTION_NAME).stream()
        all_data = []
        for doc in docs:
            doc_dict = doc.to_dict()
            if 'data' in doc_dict:
                doc_date = doc_dict.get('snapshot_date', '')
                rows = doc_dict['data']
                for row in rows:
                    if 'Snapshot_Date' not in row or not row['Snapshot_Date']:
                        row['Snapshot_Date'] = doc_date
                    all_data.append(row)
        return all_data
    except Exception as e:
        st.error(f"❌ 데이터 로드 중 오류 발생: {e}")
        return []

def delete_otb_data_only():
    """OTB 데이터만 초기화"""
    try:
        docs = db.collection(COLLECTION_NAME).stream()
        deleted_count = 0
        for doc in docs:
            doc_data = doc.to_dict()
            if 'data' in doc_data and len(doc_data['data']) > 0:
                first_row = doc_data['data'][0]
                segment = str(first_row.get('Segment', ''))
                g_name = str(first_row.get('Guest_Name', ''))
                if 'OTB' in segment or 'OTB' in g_name:
                    doc.reference.delete()
                    deleted_count += 1
        return deleted_count
    except Exception as e:
        st.error(f"OTB 삭제 중 오류 발생: {e}")
        return 0

# ==============================================================================
# 4. 파일 처리 및 매핑 로직 (무생략/정밀 수정)
# ==============================================================================

def normalize_and_map_columns(df):
    """컬럼명 표준화 매핑"""
    col_map = {}
    rules = {
        'CheckIn': ['checkin', 'arrival', '입실', '일자', 'date'],
        'Guest_Name': ['guest', 'name', 'customer', '고객', '성명'],
        'Booking_Date': ['booking', 'create', 'res', '예약', '생성'],
        'Rooms': ['room', 'qty', 'rmws', '객실수', '수량'],
        'Nights': ['night', 'los', '박수', '박'],
        'Room_Revenue': ['room_rev', 'revenue', 'roomrate', '객실료', '매출'],
        'Total_Revenue': ['total', 'amount', '총금액', '합계'],
        'Segment': ['segment', '세그먼트'],
        'Account': ['account', 'source', 'agent', '거래처'],
        'Room_Type': ['type', 'cat', '객실타입'],
        'Rate_Plan': ['rate', 'plan', '상품', '패키지'], 
        'Service_Code': ['service', '서비스', 'code'], 
        'Nat_Orig': ['nation', 'country', 'nat', '국적'],
        'Lead_Time': ['lead', '리드', 'lt']
    }
    for col in df.columns:
        clean = str(col).lower().replace(" ", "").replace("_", "")
        for key, kw_list in rules.items():
            if any(k in clean for k in kw_list):
                if key == 'Room_Revenue' and 'total' in clean: continue
                if key == 'Total_Revenue' and 'room' in clean: continue
                if key == 'CheckIn' and ('book' in clean or 'res' in clean): continue
                if key not in col_map.values():
                    col_map[col] = key
                    break
    return df.rename(columns=col_map)

def process_data(uploaded_file, status, force_otb=False):
    """
    [핵심 수정 로직 반영]
    - OTB: 물리적 위치(맨 오른쪽 끝 열)를 매출로 자동 인식.
    - 조식: 서비스코드에 'BF'가 포함되면 무조건 포함으로 분류.
    """
    try:
        is_filename_otb = "Sales on the Book" in uploaded_file.name or "영업 현황" in uploaded_file.name
        is_otb = force_otb or is_filename_otb
        
        uploaded_file.seek(0)
        if uploaded_file.name.endswith('.csv'):
            try: df_raw = pd.read_csv(uploaded_file, header=None)
            except: df_raw = pd.read_csv(uploaded_file, header=None, encoding='cp949')
        else:
            df_raw = pd.read_excel(uploaded_file, header=None)

        # 1. 제목 줄 자동 탐색
        best_row = 0; max_hit = 0
        keywords = ['guest', 'name', 'check', 'date', 'room', '고객', '입실', '객실', '서비스', '매출', '일자']
        for i, row in df_raw.head(20).iterrows():
            hit = sum(1 for k in keywords if k in str(row.values).lower())
            if hit > max_hit: max_hit = hit; best_row = i
        
        headers = df_raw.iloc[best_row].values
        df_final = df_raw.iloc[best_row+1:].reset_index(drop=True)
        df_final.columns = [str(c).strip() for c in headers]

        if is_otb:
            # ------------------------------------
            # CASE A: OTB 데이터 (Sales on the Book)
            # ------------------------------------
            # 합계/소계 행은 집계에서 제외
            if '일자' in df_final.columns:
                df_final = df_final[~df_final['일자'].astype(str).str.contains('합계|Total|소계', na=False)]
            
            df = pd.DataFrame()
            # 일자: 첫 번째 열
            df['CheckIn'] = pd.to_datetime(df_final.iloc[:, 0], errors='coerce')
            
            # [수정] OTB 매출 추출: 무조건 가장 마지막 열(-1)
            df['Room_Revenue'] = pd.to_numeric(
                df_final.iloc[:, -1].astype(str).str.replace(r'[^0-9.-]', '', regex=True), 
                errors='coerce'
            ).fillna(0)
            
            # [수정] OTB RN 추출: 뒤에서 5번째 열(-5)
            df['RN'] = pd.to_numeric(
                df_final.iloc[:, -5].astype(str).str.replace(r'[^0-9.-]', '', regex=True), 
                errors='coerce'
            ).fillna(0)
            
            df['Total_Revenue'] = df['Room_Revenue']
            df['Guest_Name'] = 'OTB_DATA'; df['Segment'] = 'OTB'; df['Account'] = 'OTB_Summary'
            df['Room_Type'] = 'ROH'; df['Nat_Orig'] = 'KR'; df['Booking_Date'] = df['CheckIn']
            df['Lead_Time'] = 0; df['Breakfast'] = 'Unknown'
            
        else:
            # ------------------------------------
            # CASE B: 일반 고객 목록 (예약/취소)
            # ------------------------------------
            df_final = df_final[~df_final.iloc[:, 0].astype(str).str.contains('합계|Total|소계', na=False)]
            df = normalize_and_map_columns(df_final).copy()
            
            req_cols = ['Rooms', 'Nights', 'Room_Revenue', 'Total_Revenue', 'Guest_Name', 'Segment', 'Account', 'Room_Type', 'Nat_Orig', 'Lead_Time', 'Rate_Plan', 'Service_Code']
            for c in req_cols:
                if c not in df.columns: 
                    df[c] = 0 if c in ['Rooms', 'Nights', 'Room_Revenue', 'Total_Revenue', 'Lead_Time'] else 'Unknown'

            # [수정] 조식 정밀 식별: 서비스코드에 'BF'가 들어있으면 무조건 조식 포함
            def check_breakfast_logic(row):
                svc = str(row.get('Service_Code', '')).upper()
                plan = str(row.get('Rate_Plan', '')).upper()
                if 'BF' in svc or '조식' in svc or 'BF' in plan or '조식' in plan:
                    return 'Included (조식포함)'
                return 'Not Included (불포함)'
            
            df['Breakfast'] = df.apply(check_breakfast_logic, axis=1)

            # 숫자 필드 변환
            for col in ['Room_Revenue', 'Total_Revenue', 'Rooms', 'Nights', 'Lead_Time']:
                df[col] = pd.to_numeric(df[col].astype(str).str.replace(r'[^0-9.-]', '', regex=True), errors='coerce').fillna(0)
            
            df['Total_Revenue'] = np.where(df['Total_Revenue'] == 0, df['Room_Revenue'], df['Total_Revenue'])
            df['RN'] = df['Rooms'] * df['Nights'].replace(0, 1)

        # 공통 마무리 처리
        df['Status'] = status
        df['Snapshot_Date'] = datetime.now().strftime('%Y-%m-%d')
        df['CheckIn_dt'] = pd.to_datetime(df['CheckIn'], errors='coerce')
        df['Booking_dt'] = pd.to_datetime(df.get('Booking_Date', df['CheckIn']), errors='coerce')
        
        df = df.dropna(subset=['CheckIn_dt'])
        df['Stay_Month'] = df['CheckIn_dt'].dt.strftime('%Y-%m')
        df['Booking_Month'] = df['Booking_dt'].dt.strftime('%Y-%m')
        df['Day_Type'] = df['CheckIn_dt'].dt.weekday.apply(lambda x: 'Weekend' if x >= 4 else 'Weekday')
        
        # 국적 분류 로직
        def classify_nationality(row):
            name = str(row.get('Guest_Name', ''))
            orig = str(row.get('Nat_Orig', '')).upper()
            if re.search('[가-힣]', name): return 'KOR'
            if any(x in orig for x in ['CHN', 'HKG', 'TWN', 'MAC']): return 'CHN'
            return 'OTH'
        df['Nat_Group'] = df.apply(classify_nationality, axis=1)
        
        return clean_numeric_columns(df)

    except Exception as e:
        st.error(f"파일 처리 에러: {e}")
        return pd.DataFrame()

# ==============================================================================
# 5. UI 렌더링 헬퍼 함수들 (무생략)
# ==============================================================================

def add_total_row(df, group_col_name="구분"):
    if df.empty: return df
    numeric_df = df.select_dtypes(include=[np.number]).fillna(0)
    totals = numeric_df.sum().to_dict()
    total_row = {col: "" for col in df.columns}
    total_row.update(totals)
    total_row[group_col_name] = "TOTAL"
    if 'RN' in total_row and total_row['RN'] > 0:
        if 'Room_Revenue' in total_row: total_row['ADR_Room'] = total_row['Room_Revenue'] / total_row['RN']
        if 'Total_Revenue' in total_row: total_row['ADR_Total'] = total_row['Total_Revenue'] / total_row['RN']
    return pd.concat([df, pd.DataFrame([total_row])], ignore_index=True)

def show_dataframe_with_style(df):
    """데이터프레임 스타일링 출력"""
    if df.empty:
        st.write("데이터가 없습니다.")
        return
    num_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    styler = df.style.format({col: "{:,.0f}" for col in num_cols})
    if 'Budget_Achiev' in df.columns: styler = styler.format({'Budget_Achiev': "{:.1f}%"})
    
    def highlight_total(row):
        is_total = any(str(val) == "TOTAL" for val in row)
        return ['background-color: #fff9c4; font-weight: 900; color: black; border-top: 2px solid black'] * len(row) if is_total else [''] * len(row)
    
    st.dataframe(styler.apply(highlight_total, axis=1), hide_index=True, use_container_width=True)

# ==============================================================================
# UI 메인 실행부 (여기가 본체입니다)
# ==============================================================================
try:
    st.title("🏛️ 앰버 호텔 경영 리포트 (Final Integrity)")

    raw_data = load_data_from_firestore()
    df_all = pd.DataFrame(raw_data) if raw_data else pd.DataFrame()
    available_dates = sorted(df_all['Snapshot_Date'].unique(), reverse=True) if not df_all.empty else []

    # ----------------------------------------------------------------------
    # SIDEBAR
    # ----------------------------------------------------------------------
    with st.sidebar:
        st.header("📅 조회 및 관리")
        if st.button("🗑️ OTB 데이터 초기화"):
            deleted_cnt = delete_otb_data_only()
            st.warning(f"OTB 데이터 {deleted_cnt}건 삭제 완료!")
            time.sleep(1); st.cache_data.clear(); st.rerun()
            
        selected_date = st.selectbox("조회 기준일 (Snapshot)", available_dates, index=0) if available_dates else None

        st.markdown("---")
        st.header("📤 데이터 업로드")
        
        with st.expander("1. 예약 리스트", expanded=True):
            f1 = st.file_uploader("예약 파일 (Excel/CSV)", type=['xlsx','csv'], key="f1")
            if f1 and st.button("예약 데이터 저장"):
                df = process_data(f1, "Booked")
                if not df.empty and save_to_firestore(df):
                    st.success("예약 리스트 저장 성공!"); time.sleep(1); st.cache_data.clear(); st.rerun()
            
        with st.expander("2. 취소 리스트", expanded=True):
            f2 = st.file_uploader("취소 파일 (Excel/CSV)", type=['xlsx','csv'], key="f2")
            if f2 and st.button("취소 데이터 저장"):
                df = process_data(f2, "Cancelled")
                if not df.empty and save_to_firestore(df):
                    st.success("취소 리스트 저장 성공!"); time.sleep(1); st.cache_data.clear(); st.rerun()

        with st.expander("3. OTB (영업현황)", expanded=True):
            f3_list = st.file_uploader("OTB 파일들", type=['xlsx','csv'], key="f3", accept_multiple_files=True)
            if f3_list and st.button("OTB 데이터 저장"):
                all_otb = []
                for f in f3_list:
                    processed = process_data(f, "Booked", force_otb=True)
                    if not processed.empty: all_otb.append(processed)
                if all_otb:
                    combined_otb = pd.concat(all_otb, ignore_index=True)
                    if save_to_firestore(combined_otb):
                        st.success("OTB 통합 저장 성공!"); time.sleep(1); st.cache_data.clear(); st.rerun()

    # ----------------------------------------------------------------------
    # MAIN DASHBOARD
    # ----------------------------------------------------------------------
    if selected_date and not df_all.empty:
        df = clean_numeric_columns(df_all[df_all['Snapshot_Date'] == selected_date].copy())
        
        # 데이터 분리
        df_otb = df[df['Segment'] == 'OTB']
        df_list = df[df['Segment'] != 'OTB']
        df_paid_bk = df_list[(df_list['Status'] == 'Booked') & (df_list['Total_Revenue'] > 0)]
        df_list_cn = df_list[df_list['Status'] == 'Cancelled']
        df_total_paid = pd.concat([df_paid_bk, df_list_cn])

        main_tab0, main_tab1, main_tab2, main_tab3, main_tab4, main_tab5 = st.tabs([
            "👑 GM 요약", "✅ 예약 상세", "❌ 취소 상세", "📈 종합 합계", "🆓 0원 예약", "🎯 OTB 현황"
        ])

        # -----------------------------------------------------------
        # [GM 요약]
        # -----------------------------------------------------------
        with main_tab0:
            st.header(f"👑 총지배인 요약 ({selected_date})")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("신규 예약 RN", f"{df_paid_bk['RN'].sum():,.0f} RN")
            c2.metric("신규 예약 매출", f"{df_paid_bk['Room_Revenue'].sum():,.0f} 원")
            c3.metric("금일 취소 RN", f"{df_list_cn['RN'].sum():,.0f} RN")
            c4.metric("금일 취소 매출", f"{df_list_cn['Room_Revenue'].sum():,.0f} 원")
            
            st.subheader("📊 세그먼트별 픽업 실적")
            seg_sum = df_paid_bk.groupby('Segment').agg({'RN':'sum', 'Room_Revenue':'sum'}).reset_index()
            show_dataframe_with_style(add_total_row(seg_sum, 'Segment'))
            
            st.divider()
            c_left, c_right = st.columns(2)
            with c_left:
                st.subheader("국적별 비중")
                nat_pie = df_paid_bk.groupby('Nat_Group')['RN'].sum().reset_index()
                st.plotly_chart(px.pie(nat_pie, values='RN', names='Nat_Group', hole=0.4), use_container_width=True)
            with c_right:
                st.subheader("월별 추이")
                trend = df_paid_bk.groupby('Stay_Month')['RN'].sum().reset_index()
                st.plotly_chart(px.bar(trend, x='Stay_Month', y='RN'), use_container_width=True)

        # -----------------------------------------------------------
        # [예약 상세] - 무생략 전개
        # -----------------------------------------------------------
        with main_tab1:
            if df_paid_bk.empty: st.warning("데이터가 없습니다.")
            else:
                t1, t2, t3, t4, t5, t6, t7, t8 = st.tabs(["📊 세그먼트", "📅 Pacing", "🏢 거래처", "⏳ 리드타임", "🛏️ 객실타입", "🗓️ 요일", "🌐 국적", "🍳 조식"])
                with t1:
                    s_data = df_paid_bk.groupby('Segment').agg({'RN':'sum', 'Room_Revenue':'sum'}).reset_index()
                    st.plotly_chart(px.bar(s_data, x='Segment', y='Room_Revenue', title="세그먼트별 매출"), use_container_width=True)
                    show_dataframe_with_style(add_total_row(s_data, 'Segment'))
                with t2:
                    p_data = df_paid_bk.pivot_table(index='Booking_Month', columns='Stay_Month', values='RN', aggfunc='sum').fillna(0)
                    st.plotly_chart(px.imshow(p_data, text_auto=True), use_container_width=True)
                with t3:
                    a_data = df_paid_bk.groupby('Account').agg({'RN':'sum', 'Room_Revenue':'sum'}).reset_index().sort_values('RN', ascending=False).head(50)
                    show_dataframe_with_style(add_total_row(a_data, 'Account'))
                with t4:
                    df_paid_bk['LT_G'] = pd.cut(df_paid_bk['Lead_Time'], bins=[-1,0,3,7,14,30,60,90,999], labels=['0일','1-3일','4-7일','8-14일','15-30일','31-60일','61-90일','90일+'])
                    l_data = df_paid_bk.groupby('LT_G').agg({'RN':'sum'}).reset_index()
                    st.plotly_chart(px.bar(l_data, x='LT_G', y='RN'), use_container_width=True)
                with t5:
                    r_data = df_paid_bk.groupby('Room_Type').agg({'RN':'sum', 'Room_Revenue':'sum'}).reset_index()
                    show_dataframe_with_style(add_total_row(r_data, 'Room_Type'))
                with t6:
                    d_data = df_paid_bk.groupby('Day_Type').agg({'RN':'sum', 'Room_Revenue':'sum'}).reset_index()
                    st.plotly_chart(px.pie(d_data, values='RN', names='Day_Type'), use_container_width=True)
                with t7:
                    n_data = df_paid_bk.groupby('Nat_Group').agg({'RN':'sum', 'Room_Revenue':'sum'}).reset_index()
                    st.plotly_chart(px.bar(n_data, x='Nat_Group', y='RN'), use_container_width=True)
                with t8:
                    st.subheader("🍳 조식 판매 분석")
                    b_data = df_paid_bk.groupby('Breakfast').agg({'RN':'sum', 'Room_Revenue':'sum'}).reset_index()
                    st.plotly_chart(px.pie(b_data, values='RN', names='Breakfast', title="조식 비중"), use_container_width=True)
                    show_dataframe_with_style(add_total_row(b_data, 'Breakfast'))

        # -----------------------------------------------------------
        # [취소 상세] - 무생략 전개
        # -----------------------------------------------------------
        with main_tab2:
            if df_list_cn.empty: st.warning("데이터가 없습니다.")
            else:
                t1, t2, t3, t4, t5, t6, t7, t8 = st.tabs(["📊 세그먼트", "📅 Pacing", "🏢 거래처", "⏳ 리드타임", "🛏️ 객실타입", "🗓️ 요일", "🌐 국적", "🍳 조식"])
                with t1:
                    sc_data = df_list_cn.groupby('Segment').agg({'RN':'sum', 'Room_Revenue':'sum'}).reset_index()
                    show_dataframe_with_style(add_total_row(sc_data, 'Segment'))
                with t3:
                    ac_data = df_list_cn.groupby('Account').agg({'RN':'sum'}).reset_index().sort_values('RN', ascending=False).head(50)
                    show_dataframe_with_style(add_total_row(ac_data, 'Account'))
                with t8:
                    bc_data = df_list_cn.groupby('Breakfast').agg({'RN':'sum', 'Room_Revenue':'sum'}).reset_index()
                    show_dataframe_with_style(add_total_row(bc_data, 'Breakfast'))

        # -----------------------------------------------------------
        # [종합 합계]
        # -----------------------------------------------------------
        with main_tab3:
            st.header("📈 예약 및 취소 종합 실적")
            st.subheader("세그먼트 종합")
            tot_seg = df_total_paid.groupby('Segment').agg({'RN':'sum', 'Room_Revenue':'sum'}).reset_index()
            show_dataframe_with_style(add_total_row(tot_seg, 'Segment'))
            st.subheader("거래처 종합 (Top 50)")
            tot_acc = df_total_paid.groupby('Account').agg({'RN':'sum', 'Room_Revenue':'sum'}).reset_index().sort_values('RN', ascending=False).head(50)
            show_dataframe_with_style(add_total_row(tot_acc, 'Account'))

        # -----------------------------------------------------------
        # [0원 예약]
        # -----------------------------------------------------------
        with main_tab4:
            df_zero = df_list[(df_list['Status'] == 'Booked') & (df_list['Total_Revenue'] <= 0)]
            st.subheader(f"🆓 0원 예약 건수: {len(df_zero)}건")
            st.dataframe(df_zero[['Guest_Name', 'CheckIn', 'Account', 'Room_Type', 'Service_Code']], use_container_width=True)

        # -----------------------------------------------------------
        # [OTB 현황] - 물리적 열 위치 로직 적용
        # -----------------------------------------------------------
        with main_tab5:
            st.header("🎯 OTB 현황 (Budget vs OTB)")
            if df_otb.empty: st.warning("OTB 데이터가 업로드되지 않았습니다.")
            else:
                base = df_otb.copy()
                base['M'] = pd.to_datetime(base['CheckIn']).dt.month
                otb_m = base.groupby('M').agg({'Room_Revenue':'sum'}).reset_index()
                otb_m['Budget'] = otb_m['M'].map(BUDGET_DATA).fillna(0)
                otb_m['Rate'] = (otb_m['Room_Revenue'] / otb_m['Budget'] * 100).fillna(0)
                
                # 차트 시각화
                fig = go.Figure()
                fig.add_trace(go.Bar(x=otb_m['M'].astype(str)+"월", y=otb_m['Room_Revenue'], name='현재 OTB', text=otb_m['Rate'].apply(lambda x: f"{x:.1f}%"), textposition='outside'))
                fig.add_trace(go.Scatter(x=otb_m['M'].astype(str)+"월", y=otb_m['Budget'], name='목표 Budget', line=dict(color='red', dash='dot')))
                st.plotly_chart(fig, use_container_width=True)
                
                # 표 구성
                res_tbl = []
                for _, r in otb_m.iterrows():
                    res_tbl.append({"월": f"{int(r['M'])}월", "목표 버짓": f"{r['Budget']:,.0f}", "현재 OTB": f"{r['Room_Revenue']:,.0f}", "달성률": f"{r['Rate']:.1f}%"})
                st.table(pd.DataFrame(res_tbl))

    else:
        st.info("👈 사이드바에서 파일을 업로드하고 조회 기준일을 선택해 주세요.")

except Exception as e:
    st.error(f"🚨 시스템 오류: {e}")
