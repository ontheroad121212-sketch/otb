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
# 이미 앱이 실행 중이면 기존 연결을 사용하고, 없으면 새로 연결합니다.
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
    천단위 콤마(,)나 통화기호(₩), 공백 등을 제거합니다.
    """
    target_cols = [
        'RN', 'Room_Revenue', 'Total_Revenue', 'ADR_Room', 'ADR_Total', 
        'Lead_Time', 'OTB_Rev', 'Budget_Rev', 'Budget_Achiev', 'OTB_RN', 
        'OTB_ADR', 'Actual_Rev', 'Actual_RN', 'Rooms', 'Nights'
    ]
    
    for col in target_cols:
        if col in df.columns:
            # 문자열로 변환 -> 콤마, 통화기호, 공백 제거 -> 숫자 변환
            df[col] = pd.to_numeric(
                df[col].astype(str)
                .str.replace(',', '')
                .str.replace('₩', '')
                .str.replace('$', '')
                .str.replace(' ', '')
                .str.replace('nan', '0'), 
                errors='coerce'
            ).fillna(0)
            
    # ADR(객실단가) 재계산 로직 (매출 / 박수)
    if 'RN' in df.columns:
        if 'Room_Revenue' in df.columns:
            df['ADR_Room'] = np.where(df['RN'] > 0, df['Room_Revenue'] / df['RN'], 0)
        if 'Total_Revenue' in df.columns:
            df['ADR_Total'] = np.where(df['RN'] > 0, df['Total_Revenue'] / df['RN'], 0)
            
    return df

def save_to_firestore(df):
    """
    전처리된 데이터프레임을 파이어베이스 DB에 저장합니다.
    리스트 형태(records)로 변환하여 하나의 문서에 저장합니다.
    """
    try:
        if df.empty:
            return False
            
        # 데이터프레임을 딕셔너리 리스트로 변환
        records = df.fillna(0).astype(str).to_dict(orient='records')
        
        # Firestore 컬렉션에 추가
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
    """
    파이어베이스 DB에서 모든 데이터를 불러옵니다.
    캐싱(cache)을 사용하여 속도를 높이되, ttl=0으로 최신 상태를 유지합니다.
    """
    try:
        docs = db.collection(COLLECTION_NAME).stream()
        all_data = []
        
        for doc in docs:
            doc_dict = doc.to_dict()
            if 'data' in doc_dict:
                # 문서의 스냅샷 날짜 가져오기
                doc_date = doc_dict.get('snapshot_date', '')
                rows = doc_dict['data']
                
                for row in rows:
                    # 개별 행에 스냅샷 날짜가 없으면 문서 날짜를 할당
                    if 'Snapshot_Date' not in row or not row['Snapshot_Date']:
                        row['Snapshot_Date'] = doc_date
                    all_data.append(row)
                    
        return all_data
    except Exception as e:
        st.error(f"❌ 데이터 로드 중 오류 발생: {e}")
        return []

def delete_otb_data_only():
    """
    기존 DB에서 OTB(On The Books) 데이터만 골라서 삭제합니다.
    초기화 버튼 클릭 시 실행됩니다.
    """
    try:
        docs = db.collection(COLLECTION_NAME).stream()
        deleted_count = 0
        
        for doc in docs:
            doc_data = doc.to_dict()
            if 'data' in doc_data and len(doc_data['data']) > 0:
                first_row = doc_data['data'][0]
                
                # 데이터의 세그먼트나 이름에 'OTB'가 포함되어 있는지 확인
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
# 4. 엑셀/CSV 파일 처리 및 매핑 로직 (OTB 및 조식 정밀 좌표 로직)
# ==============================================================================

def normalize_and_map_columns(df):
    """
    다양한 이름의 컬럼들을 표준화된 이름으로 매핑합니다.
    """
    col_map = {}
    rules = {
        'CheckIn': ['checkin', 'arrival', '입실', '일자', 'date'],
        'Guest_Name': ['guest', 'name', 'customer', '고객', '투숙객', '성명'],
        'Booking_Date': ['booking', 'create', 'res', '예약', '생성'],
        'Rooms': ['room', 'qty', 'rmws', '객실수', '수량'],
        'Nights': ['night', 'los', '박수', '박'],
        'Room_Revenue': ['room_rev', 'revenue', 'roomrate', '객실료', '매출'],
        'Total_Revenue': ['total', 'amount', '총금액', '합계'],
        'Segment': ['segment', '세그먼트'],
        'Account': ['account', 'source', 'agent', '거래처', '에이전시'],
        'Room_Type': ['type', 'cat', '객실타입', '룸타입'],
        'Rate_Plan': ['rate', 'plan', '상품', '패키지', '프로모션'], 
        'Service_Code': ['service', '서비스', 'code'], 
        'Nat_Orig': ['nation', 'country', 'nat', '국적'],
        'Lead_Time': ['lead', '리드', 'lt', 'l/t']
    }

    for original_col in df.columns:
        clean_col = str(original_col).lower().replace(" ", "").replace("_", "").replace("-", "")
        mapped = False
        
        for target_col, keywords in rules.items():
            for kw in keywords:
                if kw in clean_col:
                    if target_col == 'Room_Revenue' and 'total' in clean_col: continue
                    if target_col == 'Total_Revenue' and 'room' in clean_col and 'total' not in clean_col: continue
                    if target_col == 'CheckIn' and ('book' in clean_col or 'res' in clean_col): continue
                    
                    if target_col not in col_map.values():
                        col_map[original_col] = target_col
                        mapped = True
                        break
            if mapped: break
            
    return df.rename(columns=col_map)

def find_valid_header_row(df):
    """
    엑셀 파일의 실제 헤더(제목 줄) 위치를 찾아 데이터프레임을 정리합니다.
    """
    for i, row in df.iterrows():
        row_str = " ".join(row.astype(str).values).lower()
        keywords = ['guest', 'name', 'check', 'date', 'room', '고객', '입실', '객실']
        if sum(1 for k in keywords if k in row_str) >= 2:
            df.columns = df.iloc[i]
            return df.iloc[i+1:].reset_index(drop=True)
    return df

def process_data(uploaded_file, status, force_otb=False):
    """
    [사용자 요청 반영 정밀 로직]
    1. 조식 (예약/취소 리스트):
       - 3행(index 2)이 '서비스코드' 등이 있는 헤더. 4행(index 3)부터 데이터 시작.
       - K열(index 10)의 서비스코드를 강제로 읽어 'BF' 포함 시 조식 포함 분류.
    2. OTB (Sales on the Book):
       - S열(index 18)의 데이터 중 가장 마지막 행(합계/소계)의 값을 월 매출로 추출.
       - '통화' 형식 기호 완벽 제거.
    """
    try:
        is_filename_otb = "Sales on the Book" in uploaded_file.name or "영업 현황" in uploaded_file.name
        is_otb = force_otb or is_filename_otb
        
        uploaded_file.seek(0)
        # 데이터 구조 파악을 위해 header 없이 읽기
        df_raw = pd.read_excel(uploaded_file, header=None)

        if is_otb:
            # ---------------------------------------------------------
            # CASE A: Sales on the Book (OTB) 처리
            # ---------------------------------------------------------
            # 월 식별: A열(0)의 5행(index 4) 날짜 데이터 활용
            first_date_raw = df_raw.iloc[4, 0]
            month_dt = pd.to_datetime(first_date_raw, errors='coerce')
            
            # [수정] S열(index 18)의 가장 마지막 행(합계) 찾기
            # 유효한 행 중 가장 마지막 행 탐색
            s_col_series = df_raw.iloc[4:, 18]
            last_idx = s_col_series.last_valid_index()
            
            # 매출 데이터 추출 및 통화 기호 제거
            revenue_raw = str(df_raw.iloc[last_idx, 18])
            revenue_clean = pd.to_numeric(revenue_raw.replace(',', '').replace('₩', '').replace('$', '').replace(' ', ''), errors='coerce')
            
            # RN 식별: 보통 뒤에서 5번째(index 14 부근) 합계 객실수 위치
            rn_raw = str(df_raw.iloc[last_idx, 14]) 
            rn_clean = pd.to_numeric(rn_raw.replace(',', ''), errors='coerce')

            df = pd.DataFrame([{
                'CheckIn': month_dt,
                'Room_Revenue': revenue_clean,
                'RN': rn_clean,
                'Total_Revenue': revenue_clean,
                'Guest_Name': 'OTB_MONTHLY_TOTAL',
                'Segment': 'OTB',
                'Account': 'OTB_Summary',
                'Room_Type': 'ROH',
                'Nat_Orig': 'KR',
                'Booking_Date': month_dt,
                'Lead_Time': 0,
                'Breakfast': 'Unknown',
                'Status': status,
                'Snapshot_Date': datetime.now().strftime('%Y-%m-%d')
            }])
        else:
            # ---------------------------------------------------------
            # CASE B: 예약/취소 리스트 (조식 집계) 처리
            # ---------------------------------------------------------
            # 사용자 지정: 3행(index 2) 헤더, 4행(index 3) 데이터 시작
            df_headers = df_raw.iloc[2]
            df = df_raw.iloc[3:].reset_index(drop=True)
            df.columns = df_headers
            
            # 표준 매핑 실행
            df = normalize_and_map_columns(df).copy()

            # [핵심] 조식 식별 로직: K열(index 10) 직접 접근하여 'BF' 확인
            def check_breakfast_bf(row):
                # row.iloc[10]은 K열
                svc_val = str(row.iloc[10]).upper()
                if svc_val == 'NAN' or not svc_val.strip():
                    return 'Room Only (불포함)'
                if 'BF' in svc_val:
                    return 'Included (조식포함)'
                return 'Room Only (불포함)'
            
            df['Breakfast'] = df.apply(check_breakfast_bf, axis=1)

            # 필수 컬럼 보정 및 RN 계산
            req_cols = ['Rooms', 'Nights', 'Room_Revenue', 'Total_Revenue', 'Guest_Name', 'Segment', 'Account', 'Room_Type', 'Nat_Orig', 'Lead_Time']
            for c in req_cols:
                if c not in df.columns: 
                    df[c] = 0 if c in ['Rooms', 'Nights', 'Room_Revenue', 'Total_Revenue', 'Lead_Time'] else 'Unknown'

            # 숫자 변환
            for col in ['Room_Revenue', 'Total_Revenue', 'Rooms', 'Nights', 'Lead_Time']:
                df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', '').str.replace('nan', '0'), errors='coerce').fillna(0)
            
            df['Total_Revenue'] = np.where(df['Total_Revenue'] == 0, df['Room_Revenue'], df['Total_Revenue'])
            df['RN'] = df['Rooms'] * df['Nights'].replace(0, 1)

        # 공통 후처리
        df['Status'] = status
        df['Snapshot_Date'] = datetime.now().strftime('%Y-%m-%d')
        df['CheckIn_dt'] = pd.to_datetime(df['CheckIn'], errors='coerce')
        df['Booking_dt'] = pd.to_datetime(df.get('Booking_Date', df['CheckIn']), errors='coerce')
        
        df = df.dropna(subset=['CheckIn_dt'])
        df['Stay_Month'] = df['CheckIn_dt'].dt.strftime('%Y-%m')
        df['Booking_Month'] = df['Booking_dt'].dt.strftime('%Y-%m')
        df['Day_Type'] = df['CheckIn_dt'].dt.weekday.apply(lambda x: 'Weekend' if x >= 4 else 'Weekday')
        
        def cls_nat(row):
            name = str(row.get('Guest_Name', ''))
            orig = str(row.get('Nat_Orig', '')).upper()
            if re.search('[가-힣]', name): return 'KOR'
            if any(x in orig for x in ['CHN', 'HKG', 'TWN']): return 'CHN'
            return 'OTH'
        df['Nat_Group'] = df.apply(cls_nat, axis=1)
        
        return clean_numeric_columns(df)

    except Exception as e:
        st.error(f"파일 처리 에러: {e}")
        return pd.DataFrame()

# ==============================================================================
# 5. UI 렌더링 헬퍼 함수들 (무생략)
# ==============================================================================

def add_total_row(df, group_col_name="구분"):
    """데이터프레임 하단에 'TOTAL' 합계 행 추가"""
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
    """데이터프레임을 스타일링하여 출력합니다."""
    if df.empty:
        st.write("표시할 데이터가 없습니다.")
        return
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    styler = df.style.format({col: "{:,.0f}" for col in numeric_cols})
    if 'Budget_Achiev' in df.columns: styler = styler.format({'Budget_Achiev': "{:.1f}%"})
    def highlight_total(row):
        is_total = any(str(val) == "TOTAL" for val in row)
        return ['background-color: #fff9c4; font-weight: 900; color: black; border-top: 2px solid black'] * len(row) if is_total else [''] * len(row)
    st.dataframe(styler.apply(highlight_total, axis=1), hide_index=True, use_container_width=True)

# ==============================================================================
# UI 메인 실행부
# ==============================================================================
try:
    st.title("🏛️ 앰버 호텔 경영 리포트 (Final Integrity)")
    raw_data = load_data_from_firestore()
    df_all = pd.DataFrame(raw_data) if raw_data else pd.DataFrame()
    available_dates = sorted(df_all['Snapshot_Date'].unique(), reverse=True) if not df_all.empty else []

    with st.sidebar:
        st.header("📅 조회 및 관리")
        if st.button("🗑️ OTB 데이터 초기화"):
            cnt = delete_otb_data_only()
            st.warning(f"OTB 데이터 {cnt}건 삭제 완료!"); time.sleep(1); st.cache_data.clear(); st.rerun()
            
        selected_date = st.selectbox("조회 기준일 (Snapshot)", available_dates, index=0) if available_dates else None

        st.markdown("---")
        st.header("📤 데이터 업로드")
        with st.expander("1. 예약 리스트", expanded=True):
            f1 = st.file_uploader("예약 파일 (Excel)", type=['xlsx','csv'], key="f1")
            if f1 and st.button("예약 저장"):
                df = process_data(f1, "Booked")
                if not df.empty and save_to_firestore(df): st.success("저장 성공!"); time.sleep(1); st.cache_data.clear(); st.rerun()
        with st.expander("2. 취소 리스트", expanded=True):
            f2 = st.file_uploader("취소 파일 (Excel)", type=['xlsx','csv'], key="f2")
            if f2 and st.button("취소 저장"):
                df = process_data(f2, "Cancelled")
                if not df.empty and save_to_firestore(df): st.success("저장 성공!"); time.sleep(1); st.cache_data.clear(); st.rerun()
        with st.expander("3. OTB (영업현황)", expanded=True):
            f3_list = st.file_uploader("OTB 파일들 (12개월)", type=['xlsx','csv'], key="f3", accept_multiple_files=True)
            if f3_list and st.button("OTB 통합 저장"):
                all_otb = []
                for f in f3_list:
                    processed = process_data(f, "Booked", force_otb=True)
                    if not processed.empty: all_otb.append(processed)
                if all_otb:
                    combined_otb = pd.concat(all_otb, ignore_index=True)
                    if save_to_firestore(combined_otb):
                        st.success(f"OTB {len(all_otb)}개 월 통합 저장 완료!"); time.sleep(1); st.cache_data.clear(); st.rerun()

    if selected_date and not df_all.empty:
        df = clean_numeric_columns(df_all[df_all['Snapshot_Date'] == selected_date].copy())
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
            c1.metric("신규 예약 건수", f"{len(df_paid_bk):,.0f}")
            c2.metric("신규 예약 RN", f"{df_paid_bk['RN'].sum():,.0f}")
            c3.metric("신규 예약 매출", f"{df_paid_bk['Room_Revenue'].sum():,.0f}")
            c4.metric("금일 취소 RN", f"{df_list_cn['RN'].sum():,.0f}")
            
            st.subheader("📊 세그먼트별 실적 요약")
            seg_gm = df_paid_bk.groupby('Segment').agg({'RN': 'sum','Room_Revenue': 'sum'}).reset_index()
            show_dataframe_with_style(add_total_row(seg_gm, 'Segment')) 

        # -----------------------------------------------------------
        # [예약 상세] - 무생략 서브 탭
        # -----------------------------------------------------------
        with main_tab1:
            t1, t2, t3, t4, t5, t6, t7, t8 = st.tabs(["📊 세그먼트", "📅 Pacing", "🏢 거래처", "⏳ 리드타임", "🛏️ 객실타입", "🗓️ 요일", "🌐 국적", "🍳 조식"])
            with t1:
                s = df_paid_bk.groupby('Segment').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index()
                c1,c2=st.columns(2)
                c1.plotly_chart(px.pie(s, values='Room_Revenue', names='Segment'), use_container_width=True)
                c2.plotly_chart(px.bar(s, x='Segment', y='Room_Revenue'), use_container_width=True)
                show_dataframe_with_style(add_total_row(s, 'Segment'))
            with t2:
                p = df_paid_bk.pivot_table(index='Booking_Month', columns='Stay_Month', values='RN', aggfunc='sum').fillna(0)
                st.plotly_chart(px.imshow(p, text_auto="d"), use_container_width=True)
            with t3:
                a = df_paid_bk.groupby('Account').agg({'RN':'sum', 'Room_Revenue':'sum'}).reset_index().sort_values('RN', ascending=False).head(50)
                show_dataframe_with_style(add_total_row(a, 'Account'))
            with t4:
                df_paid_bk['LG'] = pd.cut(df_paid_bk['Lead_Time'], bins=[-1,0,3,7,14,30,60,90,999], labels=['0일','1-3일','4-7일','8-14일','15-30일','31-60일','61-90일','90일+'])
                l = df_paid_bk.groupby('LG').agg({'RN':'sum'}).reset_index()
                st.plotly_chart(px.bar(l, x='LG', y='RN'), use_container_width=True)
                show_dataframe_with_style(add_total_row(l, 'LG'))
            with t5:
                r = df_paid_bk.groupby('Room_Type').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index()
                show_dataframe_with_style(add_total_row(r, 'Room_Type'))
            with t6:
                w = df_paid_bk.groupby('Day_Type').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index()
                st.plotly_chart(px.bar(w, x='Day_Type', y='Room_Revenue'), use_container_width=True)
                show_dataframe_with_style(add_total_row(w, 'Day_Type'))
            with t7:
                n = df_paid_bk.groupby('Nat_Group').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index()
                st.plotly_chart(px.pie(n, values='RN', names='Nat_Group'), use_container_width=True)
                show_dataframe_with_style(add_total_row(n, 'Nat_Group'))
            with t8:
                st.subheader("🍳 조식 판매 비중 분석")
                b = df_paid_bk.groupby('Breakfast').agg({'RN':'sum', 'Room_Revenue':'sum'}).reset_index()
                c1, c2 = st.columns(2)
                c1.plotly_chart(px.pie(b, values='RN', names='Breakfast', hole=0.4), use_container_width=True)
                c2.plotly_chart(px.bar(b, x='Breakfast', y='Room_Revenue'), use_container_width=True)
                show_dataframe_with_style(add_total_row(b, 'Breakfast'))

        # -----------------------------------------------------------
        # [취소 상세] - 무생략 서브 탭
        # -----------------------------------------------------------
        with main_tab2:
            t1, t2, t3, t8 = st.tabs(["📊 세그먼트", "📅 Pacing", "🏢 거래처", "🍳 조식"])
            with t1:
                s = df_list_cn.groupby('Segment').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index()
                show_dataframe_with_style(add_total_row(s, 'Segment'))
            with t3:
                a = df_list_cn.groupby('Account').agg({'RN':'sum'}).reset_index().sort_values('RN', ascending=False).head(50)
                show_dataframe_with_style(add_total_row(a, 'Account'))
            with t8:
                b = df_list_cn.groupby('Breakfast').agg({'RN':'sum', 'Room_Revenue':'sum'}).reset_index()
                show_dataframe_with_style(add_total_row(b, 'Breakfast'))

        # -----------------------------------------------------------
        # [종합 합계]
        # -----------------------------------------------------------
        with main_tab3:
            st.subheader("📈 전체 예약 및 취소 종합")
            s = df_total_paid.groupby('Segment').agg({'RN':'sum', 'Room_Revenue':'sum'}).reset_index()
            show_dataframe_with_style(add_total_row(s, 'Segment'))

        # -----------------------------------------------------------
        # [0원 예약]
        # -----------------------------------------------------------
        with main_tab4:
            df_zero = df_list[(df_list['Status'] == 'Booked') & (df_list['Total_Revenue'] <= 0)]
            st.subheader(f"🆓 0원 예약 건수: {len(df_zero)}건")
            st.dataframe(df_zero[['Guest_Name', 'CheckIn', 'Account', 'Room_Type', 'Service_Code']], use_container_width=True)

        # -----------------------------------------------------------
        # [OTB 현황] - S열 마지막 행 추출 로직 적용
        # -----------------------------------------------------------
        with main_tab5:
            st.header("🎯 OTB 현황 (Budget vs OTB)")
            if df_otb.empty: st.warning("OTB 데이터가 없습니다.")
            else:
                base = df_otb.copy()
                base['M'] = pd.to_datetime(base['CheckIn']).dt.month
                otb_m = base.groupby('M').agg({'Room_Revenue':'sum'}).reset_index()
                otb_m['Budget'] = otb_m['M'].map(BUDGET_DATA).fillna(0)
                otb_m['Rate'] = (otb_m['Room_Revenue'] / otb_m['Budget'] * 100).fillna(0)
                
                fig = go.Figure()
                fig.add_trace(go.Bar(x=otb_m['M'].astype(str)+"월", y=otb_m['Room_Revenue'], name='OTB', text=otb_m['Rate'].apply(lambda x: f"{x:.1f}%"), textposition='outside'))
                fig.add_trace(go.Scatter(x=otb_m['M'].astype(str)+"월", y=otb_m['Budget'], name='Budget', line=dict(color='red', dash='dot')))
                st.plotly_chart(fig, use_container_width=True)
                
                res_tbl = []
                for _, r in otb_m.iterrows():
                    res_tbl.append({"월": f"{int(r['M'])}월", "목표": f"{r['Budget']:,.0f}", "실적": f"{r['Room_Revenue']:,.0f}", "달성률": f"{r['Rate']:.1f}%"})
                st.table(pd.DataFrame(res_tbl))
    else:
        st.info("👈 사이드바에서 데이터를 업로드해주세요.")
except Exception as e:
    st.error(f"🚨 시스템 오류: {e}")
