import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
import re
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
import time

# ==============================================================================
# 0. 사용자 정의 버짓 데이터 (1월~12월 목표 매출)
# ==============================================================================
BUDGET_DATA = { 
    1: 514992575, 2: 786570856, 3: 529599040, 4: 695351004,
    5: 903705440, 6: 808203820, 7: 1231949142, 8: 1388376999,
    9: 952171506, 10: 897171539, 11: 667146771, 12: 804030110 
}

# ==============================================================================
# 1. 페이지 설정 및 CSS
# ==============================================================================
st.set_page_config(page_title="ARI Final Integrity", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
    .block-container { padding-top: 1rem; padding-bottom: 5rem; }
    div[data-testid="stMetricValue"] { font-size: 26px !important; font-weight: 900; color: #0f172a; }
    div[data-testid="stMetricLabel"] { font-size: 15px !important; font-weight: 700; color: #64748b; }
    button[data-baseweb="tab"] { font-size: 16px !important; font-weight: 700; }
    [data-testid="stDataFrame"] table tr:last-child td {
        font-weight: 900 !important; background-color: #fff9c4 !important; color: #000000 !important; border-top: 2px solid #000000 !important;
    }
    div.stButton > button:first-child { border-color: #ff4b4b; color: #ff4b4b; }
    div.stButton > button:first-child:hover { background-color: #ff4b4b; color: white; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 2. 파이어베이스 연결
# ==============================================================================
if not firebase_admin._apps:
    try:
        cred = credentials.Certificate(dict(st.secrets["firebase"]))
        firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"🔥 DB 연결 실패: {e}"); st.stop()

db = firestore.client()
COLLECTION_NAME = "revenue_integrity_history"

# ==============================================================================
# 3. 데이터 전처리 유틸리티
# ==============================================================================

def clean_numeric(val):
    """문자열을 숫자로 변환 (쉼표, 원화기호 등 제거)"""
    try:
        if pd.isna(val): return 0
        s = str(val).replace(',', '').replace('₩', '').replace(' ', '').strip()
        return float(s) if s else 0
    except: return 0

def save_to_firestore_split_by_date(df, is_otb=False):
    """
    통데이터를 날짜별로 쪼개서 저장하는 핵심 함수
    """
    try:
        if df.empty: return False
        
        # Snapshot_Date가 없으면 오늘 날짜
        if 'Snapshot_Date' not in df.columns:
            df['Snapshot_Date'] = datetime.now().strftime('%Y-%m-%d')
            
        unique_dates = df['Snapshot_Date'].unique()
        
        for s_date in unique_dates:
            date_df = df[df['Snapshot_Date'] == s_date].copy()
            if date_df.empty: continue
            
            # 날짜 객체는 문자열로 변환해야 JSON 직렬화 가능
            for col in date_df.select_dtypes(include=['datetime64[ns]']).columns:
                date_df[col] = date_df[col].astype(str)

            records = date_df.to_dict(orient='records')
            
            # 타입 지정
            data_type = 'OTB' if is_otb else 'Reservation'
            
            # 문서 ID: 날짜_타입_타임스탬프
            doc_id = f"{s_date}_{data_type}_{int(time.time()*1000)}"
            
            db.collection(COLLECTION_NAME).document(doc_id).set({
                'data': records,
                'uploaded_at': datetime.now(),
                'snapshot_date': s_date,
                'data_type': data_type
            })
        return True
    except Exception as e:
        st.error(f"❌ 저장 오류: {e}"); return False

@st.cache_data(ttl=0)
def load_data_from_firestore():
    try:
        docs = db.collection(COLLECTION_NAME).stream()
        all_data = []
        for doc in docs:
            d = doc.to_dict()
            if 'data' in d:
                snap = d.get('snapshot_date', '')
                dtype = d.get('data_type', 'Reservation')
                
                # 구버전 데이터 호환
                if dtype == 'Reservation' and len(d['data']) > 0 and 'OTB' in str(d['data'][0].get('Segment', '')):
                    dtype = 'OTB'

                rows = d['data']
                for row in rows:
                    if 'Snapshot_Date' not in row: row['Snapshot_Date'] = snap
                    row['Data_Type'] = dtype
                    all_data.append(row)
        return all_data
    except Exception as e: st.error(f"❌ 로드 오류: {e}"); return []

def delete_all_records():
    try:
        docs = db.collection(COLLECTION_NAME).stream(); cnt = 0
        for doc in docs: doc.reference.delete(); cnt += 1
        return cnt
    except: return 0

def delete_otb_data_only():
    try:
        docs = db.collection(COLLECTION_NAME).stream(); cnt = 0
        for doc in docs:
            d = doc.to_dict()
            if d.get('data_type') == 'OTB': doc.reference.delete(); cnt += 1
            elif 'data' in d and any('OTB' in str(r.get('Segment', '')) for r in d['data']): doc.reference.delete(); cnt += 1
        return cnt
    except: return 0

# ==============================================================================
# 4. 파일 처리 로직 (사용자 지정 컬럼 매핑)
# ==============================================================================

def process_reservation_file(file):
    """
    예약 리스트 처리 (AE열 예약일자, L열 객실수, I열 박수 등)
    """
    try:
        # 헤더가 3행(index 2)에 있다고 가정
        if file.name.endswith('.csv'):
            try: df_raw = pd.read_csv(file, header=2, encoding='cp949')
            except: df_raw = pd.read_csv(file, header=2)
        else:
            df_raw = pd.read_excel(file, header=2)
            
        # 컬럼 인덱스로 접근하여 강제 매핑 (사용자 요청 사항)
        # B:1, C:2, F:5, G:6, H:7, I:8, J:9, K:10, L:11, N:13, P:15, Q:16, R:17, X:23, AE:30
        # 주의: 0-based index
        
        # 데이터프레임 컬럼 수가 충분한지 확인
        if len(df_raw.columns) <= 30:
            st.error("🚨 파일 컬럼 수가 부족합니다. 예약 리스트 형식이 맞는지 확인해주세요.")
            return pd.DataFrame()

        df = pd.DataFrame()
        
        # 주요 컬럼 매핑 (위치 기반)
        df['Status'] = df_raw.iloc[:, 1] # B
        df['Res_No'] = df_raw.iloc[:, 2] # C
        df['Guest_Name'] = df_raw.iloc[:, 5] # F
        df['CheckIn'] = pd.to_datetime(df_raw.iloc[:, 6], errors='coerce') # G
        df['CheckOut'] = pd.to_datetime(df_raw.iloc[:, 7], errors='coerce') # H
        df['Nights'] = df_raw.iloc[:, 8].apply(clean_numeric) # I (박수)
        df['Room_Type'] = df_raw.iloc[:, 9] # J
        df['Service_Code'] = df_raw.iloc[:, 10] # K
        df['Rooms'] = df_raw.iloc[:, 11].apply(clean_numeric) # L (객실수)
        df['Room_Revenue'] = df_raw.iloc[:, 13].apply(clean_numeric) # N
        df['Total_Revenue'] = df_raw.iloc[:, 15].apply(clean_numeric) # P
        df['Account'] = df_raw.iloc[:, 16] # Q
        df['Segment'] = df_raw.iloc[:, 17] # R
        df['Nat_Orig'] = df_raw.iloc[:, 23] # X
        df['Booking_Date'] = pd.to_datetime(df_raw.iloc[:, 30], errors='coerce') # AE (예약일자)
        
        # 추가 정보
        df['Phone'] = df_raw.iloc[:, 34] if len(df_raw.columns) > 34 else "" # AI (34)
        df['Email'] = df_raw.iloc[:, 35] if len(df_raw.columns) > 35 else "" # AJ (35)

        # 리드타임 & RN 계산 (강제)
        df['Lead_Time'] = (df['CheckIn'] - df['Booking_Date']).dt.days.fillna(0)
        df['RN'] = df['Rooms'] * df['Nights']
        
        # 0원 예약 보정
        df['Total_Revenue'] = np.where(df['Total_Revenue'] == 0, df['Room_Revenue'], df['Total_Revenue'])
        
        # Snapshot Date (예약일 기준 분할)
        df['Snapshot_Date'] = df['Booking_Date'].dt.strftime('%Y-%m-%d').fillna(datetime.now().strftime('%Y-%m-%d'))
        
        # 기타 파생 변수
        df['Stay_Month'] = df['CheckIn'].dt.strftime('%Y-%m')
        df['Booking_Month'] = df['Booking_Date'].dt.strftime('%Y-%m')
        df['Day_Type'] = df['CheckIn'].dt.weekday.apply(lambda x: 'Weekend' if x >= 4 else 'Weekday')
        
        # 국적 분류
        def classify_nat(val):
            val = str(val).upper()
            if val == 'KOR': return 'KOR'
            if val in ['CHN', 'HKG', 'TWN', 'MAC']: return 'CHN'
            if val == 'JPN': return 'JPN'
            if val in ['USA', 'CAN']: return 'AME'
            return 'OTH'
        df['Nat_Group'] = df['Nat_Orig'].apply(classify_nat)
        
        # 조식 스캔 (원본 데이터 전체 문자열에서 검색)
        raw_str_series = df_raw.astype(str).agg(''.join, axis=1).str.upper()
        df['Breakfast'] = np.where(raw_str_series.str.contains('BF'), 'Included (조식포함)', 'Not Included (불포함)')

        return df

    except Exception as e:
        st.error(f"예약 파일 처리 중 오류: {e}")
        return pd.DataFrame()

def process_cancellation_file(file):
    """
    취소 리스트 처리 (AA열 예약일자, AB열 취소일자, L열 객실수, I열 박수 등)
    """
    try:
        if file.name.endswith('.csv'):
            try: df_raw = pd.read_csv(file, header=2, encoding='cp949')
            except: df_raw = pd.read_csv(file, header=2)
        else:
            df_raw = pd.read_excel(file, header=2)
            
        if len(df_raw.columns) <= 27:
            st.error("🚨 파일 컬럼 수가 부족합니다. 취소 리스트 형식이 맞는지 확인해주세요.")
            return pd.DataFrame()

        df = pd.DataFrame()
        
        # 주요 컬럼 매핑 (위치 기반)
        df['Status'] = df_raw.iloc[:, 1] # B
        df['Res_No'] = df_raw.iloc[:, 2] # C
        df['Guest_Name'] = df_raw.iloc[:, 5] # F
        df['CheckIn'] = pd.to_datetime(df_raw.iloc[:, 6], errors='coerce') # G
        df['CheckOut'] = pd.to_datetime(df_raw.iloc[:, 7], errors='coerce') # H
        df['Nights'] = df_raw.iloc[:, 8].apply(clean_numeric) # I
        df['Room_Type'] = df_raw.iloc[:, 9] # J
        df['Service_Code'] = df_raw.iloc[:, 10] # K
        df['Rooms'] = df_raw.iloc[:, 11].apply(clean_numeric) # L
        df['Room_Revenue'] = df_raw.iloc[:, 13].apply(clean_numeric) # N
        df['Total_Revenue'] = df_raw.iloc[:, 15].apply(clean_numeric) # P
        df['Account'] = df_raw.iloc[:, 16] # Q
        df['Segment'] = df_raw.iloc[:, 17] # R
        df['Nat_Orig'] = df_raw.iloc[:, 23] # X
        df['Booking_Date'] = pd.to_datetime(df_raw.iloc[:, 26], errors='coerce') # AA (예약일자)
        df['Cancel_Date'] = pd.to_datetime(df_raw.iloc[:, 27], errors='coerce') # AB (취소일자)

        # 리드타임 & RN 계산 (강제)
        # 취소 리드타임은 보통 입실일 - 취소일 or 입실일 - 예약일. 
        # 여기선 예약일 기준 리드타임 유지
        df['Lead_Time'] = (df['CheckIn'] - df['Booking_Date']).dt.days.fillna(0)
        df['RN'] = df['Rooms'] * df['Nights']
        
        # 매출 0원 보정
        df['Total_Revenue'] = np.where(df['Total_Revenue'] == 0, df['Room_Revenue'], df['Total_Revenue'])
        
        # Snapshot Date (취소일 기준 분할)
        df['Snapshot_Date'] = df['Cancel_Date'].dt.strftime('%Y-%m-%d').fillna(datetime.now().strftime('%Y-%m-%d'))
        
        # 파생 변수
        df['Stay_Month'] = df['CheckIn'].dt.strftime('%Y-%m')
        df['Booking_Month'] = df['Booking_Date'].dt.strftime('%Y-%m')
        df['Day_Type'] = df['CheckIn'].dt.weekday.apply(lambda x: 'Weekend' if x >= 4 else 'Weekday')
        
        def classify_nat(val):
            val = str(val).upper()
            if val == 'KOR': return 'KOR'
            if val in ['CHN', 'HKG', 'TWN', 'MAC']: return 'CHN'
            return 'OTH'
        df['Nat_Group'] = df['Nat_Orig'].apply(classify_nat)
        
        # 조식 스캔
        raw_str_series = df_raw.astype(str).agg(''.join, axis=1).str.upper()
        df['Breakfast'] = np.where(raw_str_series.str.contains('BF'), 'Included (조식포함)', 'Not Included (불포함)')

        return df

    except Exception as e:
        st.error(f"취소 파일 처리 중 오류: {e}")
        return pd.DataFrame()

def process_otb(uploaded_file):
    try:
        # 파일명 날짜 추출
        filename_date = None
        match = re.search(r'(\d{8})', uploaded_file.name)
        if match:
            d = match.group(1)
            filename_date = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        
        if uploaded_file.name.endswith('.csv'):
            df_raw = pd.read_csv(uploaded_file, header=None, encoding='cp949')
        else:
            df_raw = pd.read_excel(uploaded_file, header=None)
            
        target_month_str = datetime.now().strftime('%Y-%m-%d')
        date_pattern = re.compile(r'20\d{2}-(\d{2})')
        for r in range(min(15, len(df_raw))):
            row_str = " ".join(df_raw.iloc[r].astype(str).values)
            match = date_pattern.search(row_str)
            if match:
                target_month_str = f"2026-{match.group(1)}-01"; break
        
        df_clean = df_raw.dropna(how='all').dropna(axis=1, how='all')
        try:
            raw_val = str(df_clean.iloc[-1, -1])
            total_rev = int(raw_val.replace(',', '').split('.')[0])
        except: total_rev = 0
        
        final_snap = filename_date if filename_date else datetime.now().strftime('%Y-%m-%d')

        return pd.DataFrame([{
            'CheckIn': target_month_str,
            'Room_Revenue': total_rev, 'Total_Revenue': total_rev, 'RN': 0,
            'Guest_Name': 'OTB', 'Segment': 'OTB', 'Snapshot_Date': final_snap, 'Status': 'Booked'
        }])
    except Exception as e:
        st.error(f"OTB 오류: {e}"); return pd.DataFrame()

# ==============================================================================
# 5. UI 헬퍼
# ==============================================================================

def add_total_row(df, group_col_name="구분"):
    if df.empty: return df
    numeric_df = df.select_dtypes(include=[np.number]).fillna(0)
    totals = numeric_df.sum().to_dict()
    total_row = {col: "" for col in df.columns}
    total_row.update(totals)
    total_row[group_col_name if group_col_name in df.columns else df.columns[0]] = "TOTAL"
    # 재계산 (합계 행의 ADR 등)
    if 'RN' in total_row and total_row['RN'] > 0:
        if 'Room_Revenue' in total_row: total_row['ADR_Room'] = total_row['Room_Revenue'] / total_row['RN']
    return pd.concat([df, pd.DataFrame([total_row])], ignore_index=True)

def show_df_styled(df):
    if df.empty: st.info("데이터 없음"); return
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    styler = df.style.format({col: "{:,.0f}" for col in numeric_cols})
    if 'Budget_Achiev' in df.columns: styler = styler.format({'Budget_Achiev': "{:.1f}%"})
    st.dataframe(styler.apply(lambda r: ['background-color: #fff9c4; font-weight: 900; border-top: 2px solid black'] * len(r) if any(str(v)=="TOTAL" for v in r) else ['']*len(r), axis=1), hide_index=True, use_container_width=True)

def render_tabs(df, key):
    if df.empty: st.info("데이터 없음"); return
    t1, t2, t3, t4, t5, t6, t7, t8 = st.tabs(["📊 세그먼트", "📅 Pacing", "🏢 거래처", "⏳ 리드타임", "🛏️ 객실타입", "🗓️ 요일", "🌐 국적", "🍳 조식"])
    with t1:
        s = df.groupby('Segment').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.pie(s, values='Room_Revenue', names='Segment'), use_container_width=True, key=f"{key}_pie")
        c2.plotly_chart(px.bar(s, x='Segment', y='Room_Revenue'), use_container_width=True, key=f"{key}_bar")
        show_df_styled(add_total_row(s, 'Segment'))
    with t2:
        piv = df.pivot_table(index='Booking_Month', columns='Stay_Month', values='RN', aggfunc='sum').fillna(0)
        st.plotly_chart(px.imshow(piv, text_auto="d", aspect="auto", color_continuous_scale="Blues"), use_container_width=True, key=f"{key}_pace")
    with t3:
        a = df.groupby('Account').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index().sort_values('RN', ascending=False).head(50)
        show_df_styled(add_total_row(a, 'Account'))
    with t4:
        bins = [-1, 0, 3, 7, 14, 30, 60, 90, 999]; labels = ['0일', '1-3일', '4-7일', '8-14일', '15-30일', '31-60일', '61-90일', '90일+']
        df['LT_G'] = pd.cut(df['Lead_Time'], bins=bins, labels=labels)
        l = df.groupby('LT_G', observed=True).agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
        st.plotly_chart(px.bar(l, x='LT_G', y='RN'), use_container_width=True, key=f"{key}_lt")
        show_df_styled(add_total_row(l, 'LT_G'))
    with t5: show_df_styled(add_total_row(df.groupby('Room_Type').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index(), 'Room_Type'))
    with t6:
        w = df.groupby('Day_Type').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index()
        st.plotly_chart(px.bar(w, x='Day_Type', y='Room_Revenue'), use_container_width=True, key=f"{key}_wd")
    with t7: show_df_styled(add_total_row(df.groupby('Nat_Group').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index(), 'Nat_Group'))
    with t8:
        if 'Breakfast' in df.columns:
            b = df.groupby('Breakfast').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index()
            c1, c2 = st.columns(2)
            c1.plotly_chart(px.pie(b, values='RN', names='Breakfast'), use_container_width=True, key=f"{key}_bf")
            show_df_styled(add_total_row(b, 'Breakfast'))

# ==============================================================================
# 6. 메인 실행부
# ==============================================================================
try:
    st.title("🏛️ 앰버 호텔 경영 리포트 (Final Integrity)")
    raw_data = load_data_from_firestore()
    
    # 데이터 로드
    all_rows = []
    if raw_data:
        for row in raw_data:
            # 숫자 데이터 정리
            for col in ['RN', 'Room_Revenue', 'Total_Revenue', 'Rooms', 'Nights', 'Lead_Time']:
                if col in row: row[col] = clean_numeric(row[col])
            all_rows.append(row)
        df_all = pd.DataFrame(all_rows)
    else: 
        df_all = pd.DataFrame(columns=['Snapshot_Date', 'Data_Type'])

    # [핵심] 예약 날짜와 OTB 날짜 분리
    res_dates_all = sorted(df_all[df_all.get('Data_Type') == 'Reservation']['Snapshot_Date'].unique(), reverse=True)
    
    # [사용자 요청] 오늘 날짜(실행일)는 예약 조회 목록에서 무조건 제외
    today_str = datetime.now().strftime('%Y-%m-%d')
    res_dates = [d for d in res_dates_all if d != today_str]
    
    otb_dates = sorted(df_all[df_all.get('Data_Type') == 'OTB']['Snapshot_Date'].unique(), reverse=True)

    with st.sidebar:
        st.header("📅 조회 설정")
        if st.button("🗑️ OTB 초기화"):
            c = delete_otb_data_only(); st.warning(f"{c}건 삭제"); time.sleep(1); st.cache_data.clear(); st.rerun()
        if st.button("🚨 전체 초기화"):
            c = delete_all_records(); st.warning(f"{c}건 삭제"); time.sleep(1); st.cache_data.clear(); st.rerun()
            
        st.markdown("---")
        sel_res_date = st.selectbox("📌 예약/취소 조회 (오늘 제외)", res_dates, index=0) if res_dates else None
        sel_otb_date = st.selectbox("📈 OTB 조회 (파일명 기준)", otb_dates, index=0) if otb_dates else None
        
        st.markdown("---")
        st.header("📤 업로드")
        f1 = st.file_uploader("예약 리스트 (AE=예약일)", type=['xlsx','csv'], key="f1")
        if f1 and st.button("예약 저장"):
            if save_to_firestore_split_by_date(process_reservation_file(f1), is_otb=False): st.cache_data.clear(); st.rerun()
            
        f2 = st.file_uploader("취소 리스트 (AA=예약일)", type=['xlsx','csv'], key="f2")
        if f2 and st.button("취소 저장"):
            if save_to_firestore_split_by_date(process_cancellation_file(f2), is_otb=False): st.cache_data.clear(); st.rerun()
            
        f3_list = st.file_uploader("OTB 파일 (파일명 날짜)", type=['xlsx','csv'], key="f3", accept_multiple_files=True)
        if f3_list and st.button("OTB 저장"):
            all_otb = [process_otb(f) for f in f3_list]
            if all_otb and save_to_firestore_split_by_date(pd.concat(all_otb, ignore_index=True), is_otb=True): st.cache_data.clear(); st.rerun()

    # 1. 예약 데이터 (오늘 날짜 제외된 선택값 사용)
    if sel_res_date and not df_all.empty:
        df_res = df_all[(df_all['Snapshot_Date'] == sel_res_date) & (df_all['Data_Type'] == 'Reservation')].copy()
        
        df_paid_bk = df_res[(df_res['Status'] == 'Booked') & (df_res['Total_Revenue'] > 0)]
        df_zero_bk = df_res[(df_res['Status'] == 'Booked') & (df_res['Total_Revenue'] <= 0)]
        df_cn = df_res[df_res['Status'] == 'Cancelled']
        df_tot = pd.concat([df_paid_bk, df_cn])
    else:
        df_paid_bk, df_zero_bk, df_cn, df_tot = pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    # 2. OTB 데이터
    if sel_otb_date and not df_all.empty:
        df_otb = df_all[(df_all['Snapshot_Date'] == sel_otb_date) & (df_all['Data_Type'] == 'OTB')].copy()
    else:
        df_otb = pd.DataFrame()

    # 3. 메인 화면
    tabs = st.tabs(["👑 GM 요약", "✅ 예약 상세", "❌ 취소 상세", "📈 종합 합계", "🆓 0원 예약", "🎯 OTB 현황"])

    with tabs[0]:
        st.header(f"👑 총지배인 요약 ({sel_res_date})")
        if df_paid_bk.empty and df_cn.empty:
            st.info("데이터 없음")
        else:
            b_rn, b_rev = df_paid_bk['RN'].sum(), df_paid_bk['Room_Revenue'].sum()
            c_rn, c_rev = df_cn['RN'].sum(), df_cn['Room_Revenue'].sum()
            b_los = b_rn / len(df_paid_bk) if not df_paid_bk.empty else 0
            c_los = c_rn / len(df_cn) if not df_cn.empty else 0
            
            st.markdown("#### ✅ 예약")
            c = st.columns(5); c[0].metric("RN", f"{b_rn:,.0f}"); c[1].metric("매출", f"{b_rev:,.0f}"); c[2].metric("ADR", f"{b_rev/b_rn if b_rn>0 else 0:,.0f}"); c[3].metric("LOS", f"{b_los:.1f}박"); c[4].metric("건수", f"{len(df_paid_bk):,.0f}")
            st.markdown("#### ❌ 취소")
            cc = st.columns(5); cc[0].metric("RN", f"{c_rn:,.0f}"); cc[1].metric("매출", f"{c_rev:,.0f}"); cc[2].metric("ADR", f"{c_rev/c_rn if c_rn>0 else 0:,.0f}"); cc[3].metric("LOS", f"{c_los:.1f}박"); cc[4].metric("건수", f"{len(df_cn):,.0f}")
            st.divider(); 
            if not df_paid_bk.empty: show_df_styled(add_total_row(df_paid_bk.groupby('Segment').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index(), 'Segment'))
            
            c1, c2 = st.columns(2)
            with c1:
                if not df_paid_bk.empty: st.plotly_chart(px.pie(df_paid_bk.groupby('Nat_Group')['RN'].sum().reset_index(), values='RN', names='Nat_Group', hole=0.4, title="국적 비중"), use_container_width=True)
            with c2:
                comb = pd.concat([df_paid_bk.assign(Type='Book'), df_cn.assign(Type='Cancel')])
                if not comb.empty: st.plotly_chart(px.bar(comb.groupby(['Stay_Month','Type'])['RN'].sum().reset_index(), x='Stay_Month', y='RN', color='Type', barmode='group'), use_container_width=True)

    with tabs[1]: render_tabs(df_paid_bk, "bk")
    with tabs[2]: render_tabs(df_cn, "cn")
    with tabs[3]: render_tabs(df_tot, "tot")
    with tabs[4]: 
        st.subheader(f"🆓 0원 예약 ({len(df_zero_bk)}건)")
        if not df_zero_bk.empty: st.dataframe(df_zero_bk[['Guest_Name', 'CheckIn', 'Account', 'Room_Type']], use_container_width=True)
        else: st.write("없음")

    with tabs[5]:
        st.header(f"🎯 OTB ({sel_otb_date})")
        if df_otb.empty: st.warning("데이터 없음")
        else:
            df_otb['M'] = pd.to_datetime(df_otb['CheckIn']).dt.month
            # [수정] Name 컬럼 에러 방지
            agg_otb = df_otb.groupby('M').agg({'Room_Revenue':'sum'}).reset_index()
            fin = pd.merge(pd.DataFrame({'M': range(1, 13)}), agg_otb, on='M', how='left').fillna(0)
            fin['Budget'] = fin['M'].map(BUDGET_DATA).fillna(0)
            fin['OTB'] = fin['Room_Revenue']
            fin['Rate'] = np.where(fin['Budget'] > 0, (fin['OTB'] / fin['Budget']) * 100, 0)
            fin['Name'] = fin['M'].astype(str) + "월"
            
            fig = go.Figure()
            fig.add_trace(go.Bar(x=fin['Name'], y=fin['OTB'], name='OTB', text=fin['Rate'].apply(lambda x: f"{x:.1f}%"), textposition='outside'))
            fig.add_trace(go.Scatter(x=fin['Name'], y=fin['Budget'], name='Budget', line=dict(color='red', dash='dot')))
            st.plotly_chart(fig, use_container_width=True)
            
            res_dict = {}
            tb, to = fin['Budget'].sum(), fin['OTB'].sum()
            for _, r in fin.iterrows(): res_dict[r['Name']] = [f"{r['Budget']:,.0f}", f"{r['OTB']:,.0f}", f"{r['Rate']:.1f}%"]
            res_dict['Total'] = [f"{tb:,.0f}", f"{to:,.0f}", f"{(to/tb*100 if tb>0 else 0):.1f}%"]
            st.dataframe(pd.DataFrame(res_dict, index=['Budget', 'OTB', 'Achiev%']).T)

except Exception as e: st.error(f"🚨 오류: {e}")

try:
    save_month = datetime.now().month
    if 'sob_curr' in locals() and sob_curr is not None:
        st.session_state[f"sob_{save_month}"] = sob_curr
except: pass
