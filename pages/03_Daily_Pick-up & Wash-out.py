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
    통화 기호(₩, $), 콤마(,), 문자열, 공백 등을 제거하고 순수 숫자로 만듭니다.
    """
    target_cols = [
        'RN', 'Room_Revenue', 'Total_Revenue', 'ADR_Room', 'ADR_Total', 
        'Lead_Time', 'Rooms', 'Nights'
    ]
    
    for col in target_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(
                df[col].astype(str).str.replace(',', '')
                                   .str.replace('₩', '')
                                   .str.replace('$', '')
                                   .str.replace(' ', '')
                                   .str.replace('nan', '0')
                                   .str.extract(r'(\d+)', expand=False), # 숫자만 추출
                errors='coerce'
            ).fillna(0)
            
    # ADR 재계산 (Zero Division 방지)
    if 'RN' in df.columns:
        if 'Room_Revenue' in df.columns:
            df['ADR_Room'] = np.where(df['RN'] > 0, df['Room_Revenue'] / df['RN'], 0)
        if 'Total_Revenue' in df.columns:
            df['ADR_Total'] = np.where(df['RN'] > 0, df['Total_Revenue'] / df['RN'], 0)
            
    return df

def save_to_firestore(df):
    """전처리된 데이터프레임을 파이어베이스 DB에 저장합니다."""
    try:
        if df.empty:
            return False
            
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
    """파이어베이스 DB에서 모든 데이터를 불러옵니다."""
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
    """기존 DB에서 OTB 데이터만 골라서 삭제합니다."""
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
# 4. 파일 처리 및 데이터 매핑 (핵심 로직 수정됨)
# ==============================================================================

def normalize_and_map_columns(df):
    """
    컬럼명을 표준화합니다.
    (서비스코드, 매출, 객실수 등 핵심 컬럼 매핑)
    """
    col_map = {}
    rules = {
        'CheckIn': ['checkin', 'arrival', '입실', '일자', 'date'],
        'Guest_Name': ['guest', 'name', 'customer', '고객', '성명', '투숙객'],
        'Booking_Date': ['booking', 'create', 'res', '예약', '생성'],
        'Rooms': ['room', 'qty', 'rmws', '객실수', '수량'],
        'Nights': ['night', 'los', '박수', '박'],
        'Room_Revenue': ['room_rev', 'revenue', 'roomrate', '객실료', '매출'],
        'Total_Revenue': ['total', 'amount', '총금액', '합계'],
        'Segment': ['segment', '세그먼트'],
        'Account': ['account', 'agent', '거래처'],
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
                # 중복 매핑 방지 조건
                if key == 'Room_Revenue' and 'total' in clean: continue
                if key == 'Total_Revenue' and 'room' in clean: continue
                if key == 'CheckIn' and ('book' in clean or 'res' in clean): continue
                
                if key not in col_map.values():
                    col_map[col] = key
                    break
    return df.rename(columns=col_map)

def process_data(file, status, force_otb=False):
    """
    [핵심 수정 사항 반영]
    1. Guest List: 'Service_Code'에 'BF'가 포함되면 조식 포함으로 자동 분류.
    2. OTB: 일자별로 데이터를 읽어 해당 월을 파악하고, '가장 마지막 열'을 매출로 인식하여 합산.
    """
    try:
        is_filename_otb = "Sales on the Book" in file.name or "영업 현황" in file.name
        is_otb = force_otb or is_filename_otb
        
        # 파일 포인터 초기화
        file.seek(0)
        
        # 파일 읽기
        if file.name.endswith('.csv'): 
            try: df_raw = pd.read_csv(file, header=None)
            except: df_raw = pd.read_csv(file, header=None, encoding='cp949')
        else: 
            df_raw = pd.read_excel(file, header=None)

        # 헤더 자동 찾기 (키워드 기반)
        keywords = ['guest', 'name', 'check', 'date', 'room', '고객', '입실', '객실', '서비스', '매출', '일자', 'RevPAR']
        best_row = 0; max_hit = 0
        for i, row in df_raw.head(20).iterrows():
            hit = sum(1 for k in keywords if k in str(row.values).lower())
            if hit > max_hit: max_hit = hit; best_row = i
        
        # 헤더 적용
        df_raw.columns = df_raw.iloc[best_row]
        df_raw = df_raw.iloc[best_row+1:].reset_index(drop=True)
        
        # 빈 컬럼 이름 정리
        df_raw.columns = [str(c).strip() for c in df_raw.columns]

        # ---------------------------------------------------------
        # Case A: OTB (Sales on the Book) 처리 로직
        # ---------------------------------------------------------
        if is_otb:
            # 1. 합계/소계 행 제거 (순수 일별 데이터만 남김)
            if '일자' in df_raw.columns:
                df_raw = df_raw[~df_raw['일자'].astype(str).str.contains('합계|Total|소계', na=False)]
            
            # 2. 날짜 컬럼 식별
            d_col = next((c for c in df_raw.columns if any(k in str(c) for k in ['일자', 'Date', 'CheckIn'])), df_raw.columns[0])
            
            # 3. 데이터프레임 생성
            df = pd.DataFrame()
            df['CheckIn'] = pd.to_datetime(df_raw[d_col], errors='coerce')
            
            # 유효한 날짜가 있는 행만 남김
            df = df.dropna(subset=['CheckIn'])
            
            # [중요] 매출 컬럼 추출: "가장 오른쪽 끝 열" 사용
            # 빈 열이 있을 수 있으므로, 데이터가 있는 가장 마지막 열을 찾음
            try:
                # 모든 열 중 Unnamed가 아닌 실제 데이터가 있는 마지막 열 인덱스 찾기
                valid_cols = [c for c in df_raw.columns if 'Unnamed' not in str(c)]
                if valid_cols:
                    last_col = valid_cols[-1] # 진짜 마지막 컬럼
                    df['Room_Revenue'] = df_raw[last_col] 
                else:
                    df['Room_Revenue'] = df_raw.iloc[:, -1] # Fallback
                
                df['Total_Revenue'] = df['Room_Revenue']
                
                # 객실수(RN) 추출
                rn_candidates = [c for c in df_raw.columns if any(k in str(c).upper() for k in ['RN', '객실수', 'QTY', 'ROOMS'])]
                if rn_candidates:
                    # 보통 객실수 컬럼이 여러 개면 첫번째 것이 전체 합계인 경우가 많음 (또는 마지막)
                    # 파일 구조상 왼쪽편에 있는 객실수를 쓰는게 안전할 수 있으나, 일단 명시된 컬럼 사용
                    df['RN'] = df_raw[rn_candidates[0]]
                else:
                    df['RN'] = 0
                    
            except Exception as e:
                df['Room_Revenue'] = 0
                df['Total_Revenue'] = 0
                df['RN'] = 0

            # 필수 식별자 주입
            df['Guest_Name'] = 'OTB_DATA'
            df['Segment'] = 'OTB'
            df['Account'] = 'OTB_Summary'
            df['Room_Type'] = 'ROH'
            df['Nat_Orig'] = 'KR'
            df['Booking_Date'] = df['CheckIn']
            df['Lead_Time'] = 0
            df['Breakfast'] = 'Unknown'

        # ---------------------------------------------------------
        # Case B: 예약/취소 리스트 (Guest List) 처리 로직
        # ---------------------------------------------------------
        else:
            # 합계 행 제거
            df_raw = df_raw[~df_raw.iloc[:, 0].astype(str).str.contains('합계|Total|소계', case=False, na=False)]
            
            # 컬럼 매핑
            df = normalize_and_map_columns(df_raw).copy()
            
            # [핵심] 조식(Breakfast) 분류 로직
            # "서비스코드"에 BF가 들어가는지 확인
            def classify_breakfast(row):
                svc_code = str(row.get('Service_Code', '')).upper()
                
                # 사용자가 지정한 조식 코드 패턴 (BF, BF2P, BF4P 등 'BF'가 들어가면 다 포함)
                if 'BF' in svc_code:
                    return 'Breakfast Included'
                else:
                    return 'Room Only'
            
            df['Breakfast'] = df.apply(classify_breakfast, axis=1)

            # 필수 컬럼 채우기
            req_cols = ['Rooms', 'Nights', 'Room_Revenue', 'Total_Revenue', 'Guest_Name', 'Segment', 'Account', 'Room_Type', 'Nat_Orig', 'Lead_Time']
            for c in req_cols: 
                if c not in df.columns: 
                    df[c] = 0 if c in ['Rooms', 'Nights', 'Room_Revenue', 'Total_Revenue'] else 'Unknown'

            # 숫자 변환 (clean_numeric_columns에서 더 강력하게 처리됨)
            df['Total_Revenue'] = np.where(df['Total_Revenue'] == 0, df['Room_Revenue'], df['Total_Revenue'])
            
            # RN 계산 (객실수 * 박수)
            df['RN'] = pd.to_numeric(df['Rooms'], errors='coerce').fillna(0) * pd.to_numeric(df['Nights'], errors='coerce').replace(0, 1).fillna(1)

        # 공통 후처리
        df['Status'] = status
        df['Snapshot_Date'] = datetime.now().strftime('%Y-%m-%d')
        
        # 날짜 포맷 통일
        df['CheckIn_dt'] = pd.to_datetime(df['CheckIn'], errors='coerce')
        df['Booking_dt'] = pd.to_datetime(df['Booking_Date'], errors='coerce')
        df.loc[df['Booking_dt'].isna(), 'Booking_dt'] = df.loc[df['Booking_dt'].isna(), 'CheckIn_dt']
        
        # 유효하지 않은 날짜 제거
        df = df.dropna(subset=['CheckIn_dt'])
        
        # 분석용 날짜 파생변수
        df['Stay_Month'] = df['CheckIn_dt'].dt.strftime('%Y-%m')
        df['Booking_Month'] = df['Booking_dt'].dt.strftime('%Y-%m')
        df['Day_Type'] = df['CheckIn_dt'].dt.weekday.apply(lambda x: 'Weekend' if x >= 4 else 'Weekday')
        
        # 국적 분류
        def classify_nat(row):
            name = str(row.get('Guest_Name', ''))
            orig = str(row.get('Nat_Orig', '')).upper()
            if re.search('[가-힣]', name): return 'KOR'
            if any(x in orig for x in ['CHN', 'HKG', 'TWN', 'CN']): return 'CHN'
            return 'OTH'
        df['Nat_Group'] = df.apply(classify_nat, axis=1)
        
        # 최종 숫자 클렌징
        return clean_numeric_columns(df)

    except Exception as e:
        st.error(f"파일 처리 중 오류 ({file.name}): {e}")
        return pd.DataFrame()

# ==============================================================================
# 5. UI 렌더링 헬퍼 함수들 (조식 대시보드 강화)
# ==============================================================================

def add_total_row(df, group_col):
    """데이터프레임 하단에 Total 행 추가"""
    if df.empty: return df
    num = df.select_dtypes(include=[np.number]).fillna(0)
    total = num.sum().to_dict()
    row = {c: "" for c in df.columns}; row.update(total); row[group_col]="TOTAL"
    
    # ADR 재계산
    if 'RN' in row and row['RN'] > 0:
        if 'Room_Revenue' in row: row['ADR_Room'] = row['Room_Revenue'] / row['RN']
        if 'Total_Revenue' in row: row['ADR_Total'] = row['Total_Revenue'] / row['RN']
    return pd.concat([df, pd.DataFrame([row])], ignore_index=True)

def style_df(df):
    """데이터프레임 스타일링 (천단위 콤마, 합계행 강조)"""
    if df.empty: st.write("데이터 없음"); return
    
    # 숫자 컬럼 포맷
    num_cols = df.select_dtypes(include=[np.number]).columns
    fmt = {c: "{:,.0f}" for c in num_cols}
    
    st.dataframe(
        df.style.format(fmt)
        .apply(lambda x: ['background-color: #fff9c4; font-weight: bold; color: black; border-top: 2px solid black'] * len(x) 
               if str(x.iloc[0]) == 'TOTAL' else [''] * len(x), axis=1),
        hide_index=True, 
        use_container_width=True
    )

def render_tab(df, key_prefix):
    """각 분석 탭 렌더링"""
    t1, t2, t3, t4, t5, t6, t7, t8 = st.tabs(["📊 세그먼트", "📅 Pacing", "🏢 거래처", "⏳ 리드타임", "🛏️ 객실타입", "🗓️ 요일", "🌐 국적", "🍳 조식"])
    
    with t1:
        s = df.groupby('Segment').agg({'RN':'sum','Room_Revenue':'sum','Total_Revenue':'sum'}).reset_index()
        s['ADR_Room'] = np.where(s['RN']>0, s['Room_Revenue']/s['RN'], 0)
        c1,c2=st.columns(2)
        c1.plotly_chart(px.pie(s, values='Room_Revenue', names='Segment', title="세그먼트 비중"), use_container_width=True, key=f"{key_prefix}_seg_pie")
        c2.plotly_chart(px.bar(s, x='Segment', y='Room_Revenue', title="세그먼트 매출"), use_container_width=True, key=f"{key_prefix}_seg_bar")
        style_df(add_total_row(s, 'Segment'))
    with t2:
        p = df.pivot_table(index='Booking_Month', columns='Stay_Month', values='RN', aggfunc='sum').fillna(0)
        st.plotly_chart(px.imshow(p, text_auto="d", aspect="auto", title="Booking Pacing"), use_container_width=True, key=f"{key_prefix}_pacing")
    with t3:
        a = df.groupby('Account').agg({'RN':'sum','Room_Revenue':'sum','Total_Revenue':'sum'}).reset_index().sort_values('RN', ascending=False).head(50)
        style_df(add_total_row(a, 'Account'))
    with t4:
        df['LG'] = pd.cut(df['Lead_Time'], [-1,0,3,7,14,30,60,90,999], labels=['0','1-3','4-7','8-14','15-30','31-60','61-90','90+'])
        l = df.groupby('LG').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index()
        st.plotly_chart(px.bar(l, x='LG', y='RN', title="리드타임별 건수"), use_container_width=True, key=f"{key_prefix}_lead")
        style_df(add_total_row(l, 'LG'))
    with t5:
        r = df.groupby('Room_Type').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index()
        style_df(add_total_row(r, 'Room_Type'))
    with t6:
        w = df.groupby('Day_Type').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index()
        c1,c2=st.columns(2)
        c1.plotly_chart(px.bar(w, x='Day_Type', y='Room_Revenue', title="평일/주말 매출"), use_container_width=True, key=f"{key_prefix}_day_bar")
        c2.plotly_chart(px.pie(w, values='RN', names='Day_Type', title="평일/주말 비중"), use_container_width=True, key=f"{key_prefix}_day_pie")
        style_df(add_total_row(w, 'Day_Type'))
    with t7: 
        if 'Nat_Group' in df.columns:
            n = df.groupby('Nat_Group').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index()
            c1,c2=st.columns(2)
            c1.plotly_chart(px.pie(n, values='RN', names='Nat_Group', title="국적 비중"), use_container_width=True, key=f"{key_prefix}_nat_pie")
            c2.plotly_chart(px.bar(n, x='Nat_Group', y='Room_Revenue', title="국적 매출"), use_container_width=True, key=f"{key_prefix}_nat_bar")
            style_df(add_total_row(n, 'Nat_Group'))
            
    # [핵심] 조식 분석 탭 (Room Only vs Breakfast Included)
    with t8:
        if 'Breakfast' in df.columns:
            st.subheader("🍳 조식 포함 여부 분석 (Room Only vs Breakfast Included)")
            
            # 그룹핑
            bf_stats = df.groupby('Breakfast').agg({
                'RN': 'sum', 
                'Room_Revenue': 'sum', 
                'Total_Revenue': 'sum'
            }).reset_index()
            
            # ADR 계산
            bf_stats['ADR_Room'] = np.where(bf_stats['RN'] > 0, bf_stats['Room_Revenue'] / bf_stats['RN'], 0)
            
            # 시각화
            c1, c2 = st.columns(2)
            c1.plotly_chart(px.pie(bf_stats, values='RN', names='Breakfast', title='객실 수(RN) 비중', hole=0.4), use_container_width=True, key=f"{key_prefix}_bf_pie")
            c2.plotly_chart(px.bar(bf_stats, x='Breakfast', y='Room_Revenue', title='매출 비교', text_auto='.2s', color='Breakfast'), use_container_width=True, key=f"{key_prefix}_bf_bar")
            
            # 데이터 테이블 출력
            st.caption("※ 서비스코드에 'BF'가 포함된 경우 조식 포함으로 자동 분류됩니다.")
            style_df(add_total_row(bf_stats, 'Breakfast'))
            
        else: st.info("조식 데이터(Service_Code)가 식별되지 않았습니다.")

# ==============================================================================
# UI 메인 실행부
# ==============================================================================
try:
    st.title("🏛️ 앰버 호텔 경영 리포트 (Final Integrity)")

    # DB 로드
    raw_data = load_data_from_firestore()
    df_all = pd.DataFrame()
    available_dates = []
    
    if raw_data:
        df_all = pd.DataFrame(raw_data)
        if 'Snapshot_Date' in df_all.columns:
            available_dates = sorted(df_all['Snapshot_Date'].unique(), reverse=True)

    # ----------------------------------------------------------------------
    # 사이드바
    # ----------------------------------------------------------------------
    with st.sidebar:
        st.header("📅 조회 설정")
        
        if st.button("🗑️ OTB 데이터만 초기화"):
            deleted_cnt = delete_otb_data_only()
            st.warning(f"OTB 데이터 {deleted_cnt}건 삭제 완료! 파일을 다시 업로드해주세요.")
            time.sleep(1)
            st.cache_data.clear()
            st.rerun()
            
        selected_date = None
        if available_dates:
            selected_date = st.selectbox("조회 기준일 (Snapshot)", available_dates, index=0)
            st.info(f"선택된 데이터 기준일: {selected_date}")
        else:
            st.warning("저장된 데이터가 없습니다.")

        st.markdown("---")
        st.header("📤 데이터 업로드")
        
        # 1. 예약 리스트
        with st.expander("예약 리스트 (Service Code 필수)", expanded=True):
            f1 = st.file_uploader("예약 리스트 (Excel/CSV)", type=['xlsx','csv'], key="f1")
            if f1 and st.button("예약 저장"):
                df = process_data(f1, "Booked")
                if not df.empty and save_to_firestore(df):
                    st.success("예약 리스트 저장 성공! (조식 자동 분류됨)")
                    time.sleep(1)
                    st.cache_data.clear()
                    st.rerun()
            
        # 2. 취소 리스트
        with st.expander("취소 리스트", expanded=True):
            f2 = st.file_uploader("취소 리스트 (Excel/CSV)", type=['xlsx','csv'], key="f2")
            if f2 and st.button("취소 저장"):
                df = process_data(f2, "Cancelled")
                if not df.empty and save_to_firestore(df):
                    st.success("취소 리스트 저장 성공!")
                    time.sleep(1)
                    st.cache_data.clear()
                    st.rerun()

        # 3. OTB (월별)
        with st.expander("OTB (Sales on the Book)", expanded=True):
            st.caption("※ 여러 달의 파일을 한번에 올려도 됩니다.")
            f3_list = st.file_uploader("OTB 파일 (Excel/CSV)", type=['xlsx','csv'], key="f3", accept_multiple_files=True)
            if f3_list and st.button("OTB 저장"):
                all_otb_data = []
                for f in f3_list:
                    # force_otb=True로 강제 인식
                    processed = process_data(f, "Booked", force_otb=True)
                    if not processed.empty:
                        all_otb_data.append(processed)
                
                if all_otb_data:
                    combined_otb = pd.concat(all_otb_data, ignore_index=True)
                    if save_to_firestore(combined_otb):
                        st.success(f"OTB 데이터 통합 저장 완료! (총 {len(combined_otb)}행)")
                        time.sleep(1)
                        st.cache_data.clear()
                        st.rerun()
                else:
                    st.error("처리 가능한 OTB 데이터가 없습니다.")

    # ----------------------------------------------------------------------
    # 메인 대시보드
    # ----------------------------------------------------------------------
    if selected_date and not df_all.empty:
        df_filtered = df_all[df_all['Snapshot_Date'] == selected_date].copy()
        
        # 숫자 컬럼 클렌징
        df = clean_numeric_columns(df_filtered)
        
        if df.empty:
            st.warning("해당 날짜에 데이터가 없습니다.")
        else:
            # 날짜형 변환
            if 'Booking_Date' not in df.columns: df['Booking_Date'] = df['CheckIn']
            df['Booking_dt'] = pd.to_datetime(df['Booking_Date'], errors='coerce')
            df['CheckIn_dt'] = pd.to_datetime(df['CheckIn'], errors='coerce')
            
            df = df.dropna(subset=['CheckIn_dt'])
            df.loc[df['Booking_dt'].isna(), 'Booking_dt'] = df.loc[df['Booking_dt'].isna(), 'CheckIn_dt']
            
            df['Is_Zero_Rate'] = df['Total_Revenue'] <= 0
            df['Booking_Month'] = df['Booking_dt'].dt.strftime('%Y-%m')
            df['Stay_Month'] = df['CheckIn_dt'].dt.strftime('%Y-%m')
            
            # OTB 데이터 vs 실적 데이터 분리
            df_otb = df[df['Segment'].astype(str).str.contains('OTB')]
            
            df_list = df[~df['Segment'].astype(str).str.contains('OTB')]
            df_paid_bk = df_list[(df_list['Status'] == 'Booked') & (df_list['Is_Zero_Rate'] == False)]
            df_zero_bk = df_list[(df_list['Status'] == 'Booked') & (df_list['Is_Zero_Rate'] == True)]
            df_list_cn = df_list[df_list['Status'] == 'Cancelled']
            
            df_total_paid = pd.concat([df_paid_bk, df_list_cn])

            # 탭 메뉴
            main_tab0, main_tab1, main_tab2, main_tab3, main_tab4, main_tab5 = st.tabs([
                "👑 총지배인(GM) 요약", "✅ 예약 상세", "❌ 취소 상세", "📈 종합 합계", "🆓 0원 예약", "🎯 OTB 현황"
            ])

            # 1. GM 요약
            with main_tab0:
                st.header(f"👑 총지배인(GM) 요약 리포트 ({selected_date})")
                
                # 요약 지표 계산
                bk_cnt = len(df_paid_bk); bk_rn = df_paid_bk['RN'].sum()
                bk_room_rev = df_paid_bk['Room_Revenue'].sum(); bk_total_rev = df_paid_bk['Total_Revenue'].sum()
                bk_adr_room = bk_room_rev / bk_rn if bk_rn > 0 else 0
                
                cn_cnt = len(df_list_cn); cn_rn = df_list_cn['RN'].sum()
                cn_room_rev = df_list_cn['Room_Revenue'].sum()
                
                c1,c2,c3,c4 = st.columns(4)
                c1.metric("확정 예약 건수", f"{bk_cnt:,.0f}건")
                c2.metric("확정 객실수(RN)", f"{bk_rn:,.0f}RN")
                c3.metric("확정 객실매출", f"{bk_room_rev:,.0f}원")
                c4.metric("객실 ADR", f"{bk_adr_room:,.0f}원")
                
                st.divider()
                st.subheader("2. 세그먼트별 현황")
                if not df_paid_bk.empty:
                    seg_gm = df_paid_bk.groupby('Segment').agg({'RN': 'sum','Room_Revenue': 'sum'}).reset_index()
                    seg_gm['ADR'] = np.where(seg_gm['RN']>0, seg_gm['Room_Revenue']/seg_gm['RN'], 0)
                    style_df(add_total_row(seg_gm, 'Segment')) 
                else: st.info("데이터 없음")
                
                st.divider()
                st.subheader("3. 조식 포함 비율 (Service Code 기준)")
                if 'Breakfast' in df_paid_bk.columns and not df_paid_bk.empty:
                    bf_gm = df_paid_bk.groupby('Breakfast').agg({'RN':'sum', 'Room_Revenue':'sum'}).reset_index()
                    c1, c2 = st.columns(2)
                    c1.plotly_chart(px.pie(bf_gm, values='RN', names='Breakfast', title='RN 비중'), use_container_width=True, key="gm_bf_pie")
                    c2.plotly_chart(px.bar(bf_gm, x='Breakfast', y='Room_Revenue', title='매출 비교'), use_container_width=True, key="gm_bf_bar")
                else: st.info("조식 데이터 없음")

            # 상세 탭들
            with main_tab1: render_tab(df_paid_bk, "bk")
            with main_tab2: render_tab(df_list_cn, "cn")
            with main_tab3: render_tab(df_total_paid, "tot")
            
            with main_tab4:
                st.subheader(f"🆓 0원 예약 (총 {len(df_zero_bk)}건)")
                st.dataframe(df_zero_bk[['Guest_Name', 'CheckIn', 'Account', 'Room_Type']], use_container_width=True)

            # 6. OTB 현황 (Budget vs OTB) - 핵심 로직 적용
            with main_tab5:
                st.header("🎯 OTB 현황 (Budget vs OTB)")
                
                if df_otb.empty:
                    st.warning("⚠️ OTB 데이터가 없습니다. 사이드바에서 파일을 업로드해 주세요.")
                else:
                    # 1. 기본 월별 틀 생성
                    all_months = pd.DataFrame({'M': range(1, 13)})
                    
                    # 2. OTB 데이터 월별 집계
                    # (일별 데이터를 날짜 기준으로 GroupBy 하여 월 합계를 구함 -> 합계행 오류 방지)
                    base = df_otb.copy()
                    if 'CheckIn_dt' not in base.columns or base['CheckIn_dt'].isnull().all():
                        base['CheckIn_dt'] = pd.to_datetime(base['CheckIn'], errors='coerce')
                    
                    base['M'] = base['CheckIn_dt'].dt.month
                    
                    # [중요] 일별 매출 합산
                    otb_grp = base.groupby('M').agg({'Room_Revenue':'sum'}).reset_index()
                    
                    # 3. 데이터 병합
                    fin = pd.merge(all_months, otb_grp, on='M', how='left').fillna(0)
                    
                    # 4. Budget 매핑 및 달성률 계산
                    fin['Budget'] = fin['M'].map(BUDGET_DATA).fillna(0)
                    fin['OTB'] = fin['Room_Revenue']
                    fin['Rate'] = np.where(fin['Budget'] > 0, (fin['OTB'] / fin['Budget']) * 100, 0)
                    fin['Name'] = fin['M'].astype(str) + "월"
                    
                    # 5. 합계 계산
                    tb = fin['Budget'].sum(); to = fin['OTB'].sum(); tr = (to / tb * 100) if tb > 0 else 0
                    
                    # 6. 시각화
                    st.subheader("📊 월별 버짓 달성률 현황")
                    fig = go.Figure()
                    fig.add_trace(go.Bar(
                        x=fin['Name'], y=fin['OTB'], name='OTB (현재)', marker_color='#2E86C1',
                        text=fin['Rate'].apply(lambda x: f"{x:.1f}%"), textposition='outside', textfont=dict(size=14, weight='bold', color='black')
                    ))
                    fig.add_trace(go.Scatter(
                        x=fin['Name'], y=fin['Budget'], name='Budget (목표)', line=dict(color='red', dash='dot', width=3)
                    ))
                    fig.update_layout(height=550, yaxis_title="매출 (KRW)", margin=dict(t=50))
                    st.plotly_chart(fig, use_container_width=True, key="otb_chart")
                    
                    # 7. 표 출력
                    st.subheader("📋 실적 요약 (Budget vs OTB)")
                    res_dict = {}
                    for _, r in fin.iterrows():
                        res_dict[r['Name']] = [f"{r['Budget']:,.0f}", f"{r['OTB']:,.0f}", f"{r['Rate']:.1f}%"]
                    res_dict['합계 (Total)'] = [f"{tb:,.0f}", f"{to:,.0f}", f"{tr:.1f}%"]
                    
                    tbl_df = pd.DataFrame(res_dict, index=['Budget (목표)', 'OTB (현재)', '달성률 (%)'])
                    def style_total_col(s):
                        if s.name == '합계 (Total)': return ['background-color: #fff9c4; font-weight: bold; border-left: 2px solid black; color: black'] * len(s)
                        return [''] * len(s)
                    st.dataframe(tbl_df.style.apply(style_total_col, axis=0), use_container_width=True)

    else:
        st.info("👈 왼쪽 사이드바에서 파일을 업로드해주세요.")

except Exception as e:
    st.error(f"🚨 시스템 오류: {e}")
