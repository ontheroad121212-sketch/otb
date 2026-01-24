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
# 1. 페이지 설정 및 CSS 스타일링
# ==============================================================================
st.set_page_config(
    page_title="ARI Final Integrity", 
    layout="wide",
    initial_sidebar_state="expanded"
)

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
# 2. 파이어베이스 데이터베이스 연결
# ==============================================================================
if not firebase_admin._apps:
    try:
        cred = credentials.Certificate(dict(st.secrets["firebase"]))
        firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"🔥 DB 연결 실패: {e}")
        st.stop()

db = firestore.client()
COLLECTION_NAME = "revenue_integrity_history"

# ==============================================================================
# 3. 데이터 전처리 및 유틸리티 함수
# ==============================================================================

def clean_numeric_columns(df):
    target_cols = [
        'RN', 'Room_Revenue', 'Total_Revenue', 'ADR_Room', 'ADR_Total', 
        'Lead_Time', 'OTB_Rev', 'Budget_Rev', 'Budget_Achiev', 'OTB_RN', 
        'OTB_ADR', 'Actual_Rev', 'Actual_RN', 'Rooms', 'Nights'
    ]
    for col in target_cols:
        if col in df.columns:
            # 쉼표, 원화기호, 공백 제거 후 숫자로 강제 변환
            df[col] = pd.to_numeric(
                df[col].astype(str).str.replace(',', '').str.replace('nan', '0').str.replace('₩', '').str.strip(), 
                errors='coerce'
            ).fillna(0)
    
    if 'RN' in df.columns:
        if 'Room_Revenue' in df.columns:
            df['ADR_Room'] = np.where(df['RN'] > 0, df['Room_Revenue'] / df['RN'], 0)
        if 'Total_Revenue' in df.columns:
            df['ADR_Total'] = np.where(df['RN'] > 0, df['Total_Revenue'] / df['RN'], 0)
    return df

def save_to_firestore_split_by_date(df, is_otb=False):
    """
    [핵심] 데이터를 날짜별로 쪼개서 저장 & OTB/Reservation 타입 구분 저장
    """
    try:
        if df.empty: return False
        
        # Snapshot_Date가 없으면 오늘 날짜(fallback)
        if 'Snapshot_Date' not in df.columns:
            df['Snapshot_Date'] = datetime.now().strftime('%Y-%m-%d')
            
        unique_dates = df['Snapshot_Date'].unique()
        
        for s_date in unique_dates:
            date_df = df[df['Snapshot_Date'] == s_date].copy()
            if date_df.empty: continue
            
            records = date_df.fillna(0).astype(str).to_dict(orient='records')
            
            # 타입 지정 (OTB vs Reservation)
            data_type = 'OTB' if is_otb else 'Reservation'
            
            # 문서 ID: 날짜_타입_타임스탬프 (중복 방지)
            doc_id = f"{s_date}_{data_type}_{int(time.time()*1000)}"
            
            db.collection(COLLECTION_NAME).document(doc_id).set({
                'data': records,
                'uploaded_at': datetime.now(),
                'snapshot_date': s_date,
                'data_type': data_type  # 필터링을 위한 핵심 필드
            })
        return True
    except Exception as e:
        st.error(f"❌ 데이터 저장 오류: {e}")
        return False

@st.cache_data(ttl=0)
def load_data_from_firestore():
    try:
        docs = db.collection(COLLECTION_NAME).stream()
        all_data = []
        for doc in docs:
            doc_dict = doc.to_dict()
            if 'data' in doc_dict:
                doc_snap_date = doc_dict.get('snapshot_date', '')
                doc_data_type = doc_dict.get('data_type', 'Reservation') # 기본값 예약
                rows = doc_dict['data']
                for row in rows:
                    if 'Snapshot_Date' not in row or not row['Snapshot_Date']:
                        row['Snapshot_Date'] = doc_snap_date
                    row['Data_Type'] = doc_data_type # 데이터 타입 강제 주입
                    all_data.append(row)
        return all_data
    except Exception as e:
        st.error(f"❌ 데이터 로드 오류: {e}")
        return []

def delete_all_records():
    try:
        docs = db.collection(COLLECTION_NAME).stream()
        cnt = 0
        for doc in docs:
            doc.reference.delete()
            cnt += 1
        return cnt
    except Exception as e:
        st.error(f"삭제 오류: {e}")
        return 0

def delete_otb_data_only():
    try:
        docs = db.collection(COLLECTION_NAME).stream()
        cnt = 0
        for doc in docs:
            d = doc.to_dict()
            # data_type이 OTB이거나, 내용물에 OTB가 있는 경우 삭제
            if d.get('data_type') == 'OTB':
                doc.reference.delete(); cnt += 1
                continue
            if 'data' in d and any('OTB' in str(r.get('Segment', '')) for r in d['data']):
                doc.reference.delete(); cnt += 1
        return cnt
    except: return 0

# ==============================================================================
# 4. 파일 처리 로직 (매핑 강화 + 리드타임 + 날짜분할)
# ==============================================================================

def normalize_and_map_columns(df):
    col_map = {}
    rules = {
        'CheckIn': ['checkin', 'arrival', '입실', '일자', 'date'],
        'Guest_Name': ['guest', 'name', 'customer', '투숙객', '성명'],
        'Booking_Date': ['booking', 'create', 'res', '예약', '생성'],
        'Cancel_Date': ['cancel', '취소일', '취소'],
        'Rooms': ['room', 'qty', 'rmws', '객실수', '수량'],
        'Nights': ['night', 'los', '박수', '박'],
        'Room_Revenue': ['room_rev', 'revenue', 'roomrate', '객실료', '매출', '금액', '요금'],
        'Total_Revenue': ['total', 'amount', '총금액', '합계'],
        'Segment': ['segment', '세그먼트'],
        'Account': ['account', 'source', 'agent', '거래처', '에이전시'],
        'Room_Type': ['type', 'cat', '객실타입', '룸타입'],
        'Rate_Plan': ['rate', 'plan', '상품', '패키지', '프로모션'], 
        'Nat_Orig': ['nation', 'country', 'nat', '국적']
    }
    
    # [핵심] 제외 단어 설정 (오인 사격 방지)
    exclusions = {
        'Rooms': ['revenue', 'rate', 'type', '금액', '료', '번호', 'id', 'pax'],
        'Nights': ['date', '일자', 'time', '시각']
    }

    for col in df.columns:
        clean = str(col).lower().replace(" ", "").replace("_", "")
        for target, kws in rules.items():
            if target in exclusions:
                if any(exc in clean for exc in exclusions[target]):
                    continue
            
            if any(kw in clean for kw in kws):
                if target not in col_map.values():
                    col_map[col] = target; break
    return df.rename(columns=col_map)

def process_data(uploaded_file, status):
    try:
        if uploaded_file.name.endswith('.csv'):
            try: df_raw = pd.read_csv(uploaded_file, header=2, encoding='cp949')
            except: df_raw = pd.read_csv(uploaded_file, header=2)
        else:
            df_raw = pd.read_excel(uploaded_file, header=2)

        # 1. 조식 전수조사
        def scan_bf(row):
            return 'Included (조식포함)' if 'BF' in "".join(row.astype(str).values).upper() else 'Not Included (불포함)'
        breakfast_col = df_raw.apply(scan_bf, axis=1)

        # 2. 컬럼 매핑
        df = normalize_and_map_columns(df_raw).copy()
        df['Breakfast'] = breakfast_col
        df['Status'] = status

        # 3. 날짜 타입 강제 변환
        for d_col in ['CheckIn', 'Booking_Date', 'Cancel_Date']:
            if d_col in df.columns:
                df[d_col] = pd.to_datetime(df[d_col].astype(str).str.replace('.', '-'), errors='coerce')

        # 4. [핵심] 리드타임 파이썬 직접 계산
        if 'CheckIn' in df.columns and 'Booking_Date' in df.columns:
            df['Lead_Time'] = (df['CheckIn'] - df['Booking_Date']).dt.days.fillna(0)
        else:
            df['Lead_Time'] = 0

        # 5. [핵심] Snapshot_Date 생성 (통데이터 분할의 기준)
        # 예약일/취소일을 기준으로 날짜를 쪼갭니다.
        target_date_col = 'Booking_Date' if status == 'Booked' else 'Cancel_Date'
        if target_date_col in df.columns:
            df['Snapshot_Date'] = df[target_date_col].dt.strftime('%Y-%m-%d')
            # 날짜 없는 데이터는 방어적으로 오늘 날짜 처리 (거의 없음)
            df['Snapshot_Date'] = df['Snapshot_Date'].fillna(datetime.now().strftime('%Y-%m-%d'))
        else:
            df['Snapshot_Date'] = datetime.now().strftime('%Y-%m-%d')

        # 6. 숫자 정리
        df['Rooms_Clean'] = pd.to_numeric(df.get('Rooms', 0), errors='coerce').fillna(0)
        df['Nights_Clean'] = pd.to_numeric(df.get('Nights', 1), errors='coerce').fillna(1)
        df['RN'] = df['Rooms_Clean'] * df['Nights_Clean']
        
        # 매출 정리 (0원 데이터 살리기 위해)
        df['Total_Revenue'] = np.where(pd.to_numeric(df.get('Total_Revenue', 0), errors='coerce').fillna(0) == 0, 
                                     pd.to_numeric(df.get('Room_Revenue', 0), errors='coerce').fillna(0), 
                                     pd.to_numeric(df.get('Total_Revenue', 0), errors='coerce').fillna(0))
        
        # 파생 변수
        if 'CheckIn' in df.columns:
            df['Stay_Month'] = df['CheckIn'].dt.strftime('%Y-%m')
            df['Day_Type'] = df['CheckIn'].dt.weekday.apply(lambda x: 'Weekend' if x >= 4 else 'Weekday')
        
        if 'Booking_Date' in df.columns:
            df['Booking_Month'] = df['Booking_Date'].dt.strftime('%Y-%m')
        else:
            df['Booking_Month'] = df.get('Stay_Month', '')

        # 7. 국적 상세 분류
        def classify_nat(row):
            name = str(row.get('Guest_Name',''))
            orig = str(row.get('Nat_Orig', '')).upper()
            if re.search('[가-힣]', name): return 'KOR'
            if any(x in orig for x in ['CHN', 'HKG', 'TWN', 'MAC']): return 'CHN'
            if any(x in orig for x in ['JPN']): return 'JPN'
            if any(x in orig for x in ['USA', 'CAN']): return 'AME'
            return 'OTH'
        df['Nat_Group'] = df.apply(classify_nat, axis=1)

        return clean_numeric_columns(df)
            
    except Exception as e:
        st.error(f"⚠️ 파일 처리 오류: {e}")
        return pd.DataFrame()

def process_otb(uploaded_file):
    try:
        if uploaded_file.name.endswith('.csv'):
            df_raw = pd.read_csv(uploaded_file, header=None, encoding='cp949')
        else:
            df_raw = pd.read_excel(uploaded_file, header=None)
            
        # OTB 날짜 찾기 (2026-01 등)
        target_month_str = datetime.now().strftime('%Y-%m-%d')
        date_pattern = re.compile(r'20\d{2}-(\d{2})')
        
        for r in range(min(15, len(df_raw))):
            row_str = " ".join(df_raw.iloc[r].astype(str).values)
            match = date_pattern.search(row_str)
            if match:
                target_month_str = f"2026-{match.group(1)}-01"
                break
        
        # OTB 데이터의 기준일은 보통 '해당 데이터의 생성일'이 없으므로
        # 업로드한 날짜 또는 특정 월의 1일로 지정해야 함.
        # 여기서는 파일 내 월의 1일로 지정하여 월별 관리가 되도록 함.
        snapshot_date = target_month_str 

        # 총 매출 추출
        df_clean = df_raw.dropna(how='all').dropna(axis=1, how='all')
        try:
            raw_val = str(df_clean.iloc[-1, -1])
            total_rev = int(raw_val.replace(',', '').split('.')[0])
        except: total_rev = 0
        
        return pd.DataFrame([{
            'CheckIn': target_month_str,
            'Room_Revenue': total_rev, 'Total_Revenue': total_rev, 'RN': 0,
            'Guest_Name': 'OTB', 'Segment': 'OTB', 'Account': 'OTB_Summary',
            'Room_Type': 'ROH', 'Nat_Orig': 'KR',
            'Snapshot_Date': snapshot_date, 
            'Status': 'Booked'
        }])
    except Exception as e:
        st.error(f"OTB 처리 오류: {e}")
        return pd.DataFrame()

# ==============================================================================
# 5. UI 렌더링 헬퍼 함수들
# ==============================================================================

def add_total_row(df, group_col_name="구분"):
    if df.empty: return df
    numeric_df = df.select_dtypes(include=[np.number]).fillna(0)
    totals = numeric_df.sum().to_dict()
    total_row = {col: "" for col in df.columns}
    total_row.update(totals)
    total_row[group_col_name if group_col_name in df.columns else df.columns[0]] = "TOTAL"
    if 'RN' in total_row and total_row['RN'] > 0:
        if 'Room_Revenue' in total_row: total_row['ADR_Room'] = total_row['Room_Revenue'] / total_row['RN']
        if 'Total_Revenue' in total_row: total_row['ADR_Total'] = total_row['Total_Revenue'] / total_row['RN']
    return pd.concat([df, pd.DataFrame([total_row])], ignore_index=True)

def show_dataframe_with_style(df):
    if df.empty:
        st.info("데이터가 없습니다."); return
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    styler = df.style.format({col: "{:,.0f}" for col in numeric_cols})
    if 'Budget_Achiev' in df.columns: styler = styler.format({'Budget_Achiev': "{:.1f}%"})
    def highlight_total(row):
        is_total = any(str(val) == "TOTAL" for val in row)
        return ['background-color: #fff9c4; font-weight: bold; color: black; border-top: 2px solid black'] * len(row) if is_total else [''] * len(row)
    st.dataframe(styler.apply(highlight_total, axis=1), hide_index=True, use_container_width=True)

def render_analysis_tab(target_df, title_prefix, unique_key, color_scale="Blues"):
    if target_df.empty:
        st.info(f"⚠️ {title_prefix} 데이터가 없습니다."); return
    
    t1, t2, t3, t4, t5, t6, t7, t8 = st.tabs([
        "📊 세그먼트", "📅 Pacing", "🏢 거래처", "⏳ 리드타임", "🛏️ 객실타입", "🗓️ 요일", "🌐 국적", "🍳 조식"
    ])
    
    with t1:
        st.subheader("📊 세그먼트 분석")
        seg_stats = target_df.groupby('Segment').agg({'RN': 'sum', 'Room_Revenue': 'sum', 'Total_Revenue': 'sum'}).reset_index()
        seg_stats['ADR_Room'] = np.where(seg_stats['RN']>0, seg_stats['Room_Revenue']/seg_stats['RN'], 0)
        seg_stats['ADR_Total'] = np.where(seg_stats['RN']>0, seg_stats['Total_Revenue']/seg_stats['RN'], 0)
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.pie(seg_stats, values='Room_Revenue', names='Segment', title="매출 비중"), use_container_width=True, key=f"{unique_key}_seg_pie")
        c2.plotly_chart(px.bar(seg_stats, x='Segment', y='Room_Revenue', title="세그먼트별 매출"), use_container_width=True, key=f"{unique_key}_seg_bar")
        show_dataframe_with_style(add_total_row(seg_stats, 'Segment'))
    
    with t2:
        st.subheader("📅 예약월 vs 투숙월 Pacing")
        piv = target_df.pivot_table(index='Booking_Month', columns='Stay_Month', values='RN', aggfunc='sum').fillna(0)
        st.plotly_chart(px.imshow(piv, text_auto="d", aspect="auto", color_continuous_scale=color_scale), use_container_width=True, key=f"{unique_key}_pacing")
    
    with t3:
        st.subheader("🏢 거래처별 실적 (Top 50)")
        acc_stats = target_df.groupby('Account').agg({'RN': 'sum', 'Room_Revenue': 'sum', 'Total_Revenue': 'sum'}).reset_index()
        acc_stats['ADR_Room'] = np.where(acc_stats['RN']>0, acc_stats['Room_Revenue']/acc_stats['RN'], 0)
        acc_stats['ADR_Total'] = np.where(acc_stats['RN']>0, acc_stats['Total_Revenue']/acc_stats['RN'], 0)
        show_dataframe_with_style(add_total_row(acc_stats.sort_values('RN', ascending=False).head(50), 'Account'))
    
    with t4:
        st.subheader("⏳ 리드타임 (자동 계산: 입실-예약)")
        bins = [-1, 0, 3, 7, 14, 30, 60, 90, 999]; labels = ['0일', '1-3일', '4-7일', '8-14일', '15-30일', '31-60일', '61-90일', '90일+']
        target_df['Lead_Group'] = pd.cut(target_df['Lead_Time'], bins=bins, labels=labels)
        lead_stats = target_df.groupby('Lead_Group', observed=True).agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
        st.plotly_chart(px.bar(lead_stats, x='Lead_Group', y='RN', title="리드타임 구간별 박수"), use_container_width=True, key=f"{unique_key}_lead")
        show_dataframe_with_style(add_total_row(lead_stats, 'Lead_Group'))
    
    with t5:
        st.subheader("🛏️ 객실타입 선호도")
        rt_stats = target_df.groupby('Room_Type').agg({'RN': 'sum', 'Room_Revenue': 'sum', 'Total_Revenue': 'sum'}).reset_index()
        show_dataframe_with_style(add_total_row(rt_stats.sort_values('RN', ascending=False), 'Room_Type'))
    
    with t6:
        st.subheader("🗓️ 요일별 패턴")
        wd_stats = target_df.groupby('Day_Type').agg({'RN': 'sum', 'Room_Revenue': 'sum', 'Total_Revenue': 'sum'}).reset_index()
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.bar(wd_stats, x='Day_Type', y='Room_Revenue'), use_container_width=True, key=f"{unique_key}_wd_bar")
        c2.plotly_chart(px.pie(wd_stats, values='RN', names='Day_Type'), use_container_width=True, key=f"{unique_key}_wd_pie")
    
    with t7:
        st.subheader("🌐 국적별 분포")
        if 'Nat_Group' in target_df.columns:
            nat_stats = target_df.groupby('Nat_Group').agg({'RN': 'sum', 'Room_Revenue': 'sum', 'Total_Revenue': 'sum'}).reset_index()
            c1, c2 = st.columns(2)
            c1.plotly_chart(px.pie(nat_stats, values='RN', names='Nat_Group', title="국적 비중"), use_container_width=True, key=f"{unique_key}_nat_pie")
            c2.plotly_chart(px.bar(nat_stats, x='Nat_Group', y='Room_Revenue'), use_container_width=True, key=f"{unique_key}_nat_bar")
            show_dataframe_with_style(add_total_row(nat_stats, 'Nat_Group'))
            
    with t8:
        st.subheader("🍳 조식 포함 여부 분석")
        if 'Breakfast' in target_df.columns:
            bf_stats = target_df.groupby('Breakfast').agg({'RN': 'sum', 'Room_Revenue': 'sum', 'Total_Revenue': 'sum'}).reset_index()
            c1, c2 = st.columns(2)
            c1.plotly_chart(px.pie(bf_stats, values='RN', names='Breakfast', title="조식 포함 비율 (RN)"), use_container_width=True, key=f"{unique_key}_bf_pie")
            c2.plotly_chart(px.bar(bf_stats, x='Breakfast', y='Room_Revenue', title="조식 여부별 매출"), use_container_width=True, key=f"{unique_key}_bf_bar")
            show_dataframe_with_style(add_total_row(bf_stats, 'Breakfast'))

# ==============================================================================
# 6. 메인 실행부
# ==============================================================================
try:
    st.title("🏛️ 앰버 호텔 경영 리포트 (Final Integrity)")
    raw_data = load_data_from_firestore()
    df_all = pd.DataFrame(raw_data) if raw_data else pd.DataFrame()
    
    # [핵심] 예약 날짜와 OTB 날짜 분리
    res_dates = sorted(df_all[df_all['Data_Type'] == 'Reservation']['Snapshot_Date'].unique(), reverse=True)
    otb_dates = sorted(df_all[df_all['Data_Type'] == 'OTB']['Snapshot_Date'].unique(), reverse=True)

    with st.sidebar:
        st.header("📅 조회 설정")
        if st.button("🗑️ OTB 데이터만 초기화"):
            deleted_cnt = delete_otb_data_only()
            st.warning(f"OTB 데이터 {deleted_cnt}건 삭제 완료!"); time.sleep(1); st.cache_data.clear(); st.rerun()
        
        if st.button("🚨 모든 데이터 초기화 (신중히)"):
            cnt = delete_all_records(); st.warning(f"{cnt}개 데이터 삭제됨"); time.sleep(1); st.cache_data.clear(); st.rerun()
            
        st.markdown("---")
        # 날짜 선택기 분리
        selected_res_date = st.selectbox("📌 예약/취소 조회 기준일", res_dates, index=0) if res_dates else None
        selected_otb_date = st.selectbox("📈 OTB 조회 기준일", otb_dates, index=0) if otb_dates else None
        
        st.markdown("---")
        st.header("📤 데이터 업로드")
        f1 = st.file_uploader("예약 리스트 (통데이터 가능)", type=['xlsx','csv'], key="f1")
        if f1 and st.button("예약 저장"):
            # is_otb=False
            if save_to_firestore_split_by_date(process_data(f1, "Booked"), is_otb=False): st.cache_data.clear(); st.rerun()
            
        f2 = st.file_uploader("취소 리스트 (통데이터 가능)", type=['xlsx','csv'], key="f2")
        if f2 and st.button("취소 저장"):
            if save_to_firestore_split_by_date(process_data(f2, "Cancelled"), is_otb=False): st.cache_data.clear(); st.rerun()
            
        f3_list = st.file_uploader("OTB 파일", type=['xlsx','csv'], key="f3", accept_multiple_files=True)
        if f3_list and st.button("OTB 저장"):
            # OTB는 is_otb=True로 저장
            all_otb = [process_otb(f) for f in f3_list]
            if all_otb and save_to_firestore_split_by_date(pd.concat(all_otb, ignore_index=True), is_otb=True): st.cache_data.clear(); st.rerun()

    # 1. 예약 데이터 로드 (선택된 예약 날짜 기준)
    if selected_res_date and not df_all.empty:
        df_res = clean_numeric_columns(df_all[(df_all['Snapshot_Date'] == selected_res_date) & (df_all['Data_Type'] == 'Reservation')].copy())
        
        df_paid_bk = df_res[(df_res['Status'] == 'Booked') & (df_res['Total_Revenue'] > 0)]
        df_zero_bk = df_res[(df_res['Status'] == 'Booked') & (df_res['Total_Revenue'] <= 0)]
        df_list_cn = df_res[df_res['Status'] == 'Cancelled']
        df_total_paid = pd.concat([df_paid_bk, df_list_cn])
    else:
        df_paid_bk, df_zero_bk, df_list_cn, df_total_paid = pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    # 2. OTB 데이터 로드 (선택된 OTB 날짜 기준)
    if selected_otb_date and not df_all.empty:
        df_otb = clean_numeric_columns(df_all[(df_all['Snapshot_Date'] == selected_otb_date) & (df_all['Data_Type'] == 'OTB')].copy())
    else:
        df_otb = pd.DataFrame()

    # 3. 메인 탭
    tabs = st.tabs(["👑 GM 요약", "✅ 예약 상세", "❌ 취소 상세", "📈 종합 합계", "🆓 0원 예약", "🎯 OTB 현황"])

    with tabs[0]:
        st.header(f"👑 총지배인(GM) 요약 리포트 ({selected_res_date})")
        if df_paid_bk.empty and df_list_cn.empty:
            st.info("선택한 날짜에 예약/취소 데이터가 없습니다.")
        else:
            bk_rn, bk_rev = df_paid_bk['RN'].sum(), df_paid_bk['Room_Revenue'].sum()
            cn_rn, cn_rev = df_list_cn['RN'].sum(), df_list_cn['Room_Revenue'].sum()
            bk_los = bk_rn / len(df_paid_bk) if not df_paid_bk.empty else 0
            cn_los = cn_rn / len(df_list_cn) if not df_list_cn.empty else 0
            
            st.markdown("#### ✅ 금일 신규 예약")
            c1,c2,c3,c4,c5 = st.columns(5)
            c1.metric("예약 RN", f"{bk_rn:,.0f}"); c2.metric("예약 매출", f"{bk_rev:,.0f}")
            c3.metric("예약 ADR", f"{bk_rev/bk_rn if bk_rn > 0 else 0:,.0f}")
            c4.metric("LOS (평균투숙)", f"{bk_los:.1f}박")
            c5.metric("예약 건수", f"{len(df_paid_bk):,.0f}")
            
            st.markdown("#### ❌ 금일 취소")
            c1,c2,c3,c4,c5 = st.columns(5)
            c1.metric("취소 RN", f"{cn_rn:,.0f}"); c2.metric("취소 매출", f"{cn_rev:,.0f}")
            c3.metric("취소 ADR", f"{cn_rev/cn_rn if cn_rn > 0 else 0:,.0f}")
            c4.metric("LOS (평균투숙)", f"{cn_los:.1f}박")
            c5.metric("취소 건수", f"{len(df_list_cn):,.0f}")
            st.divider()
            
            if not df_paid_bk.empty:
                seg_gm = df_paid_bk.groupby('Segment').agg({'RN': 'sum','Room_Revenue': 'sum','Total_Revenue': 'sum'}).reset_index()
                show_dataframe_with_style(add_total_row(seg_gm, 'Segment')) 
            c_left, c_right = st.columns(2)
            with c_left:
                if not df_paid_bk.empty: 
                    fig_gm_pie = px.pie(df_paid_bk.groupby('Nat_Group')['RN'].sum().reset_index(), values='RN', names='Nat_Group', hole=0.4, title="국적별 비중")
                    st.plotly_chart(fig_gm_pie, use_container_width=True, key="gm_pie")
            with c_right:
                comb_m = pd.concat([df_paid_bk.assign(Type='예약'), df_list_cn.assign(Type='취소')]).groupby(['Stay_Month','Type'])['RN'].sum().reset_index()
                if not comb_m.empty: 
                    fig_gm_bar = px.bar(comb_m, x='Stay_Month', y='RN', color='Type', barmode='group', title="월별 예약/취소 추이")
                    st.plotly_chart(fig_gm_bar, use_container_width=True, key="gm_bar")

    with tabs[1]: render_analysis_tab(df_paid_bk, "유료 예약", "bk_u", "Blues")
    with tabs[2]: render_analysis_tab(df_list_cn, "취소 데이터", "cn_u", "Reds")
    with tabs[3]: render_analysis_tab(df_total_paid, "종합 합계", "tot_u", "Greens")
    with tabs[4]: 
        st.subheader(f"🆓 0원 예약 (총 {len(df_zero_bk)}건)")
        if not df_zero_bk.empty:
            st.dataframe(df_zero_bk[['Guest_Name', 'CheckIn', 'Account', 'Room_Type']], use_container_width=True)
        else:
            st.write("0원 예약 데이터가 없습니다.")

    with tabs[5]:
        st.header(f"🎯 OTB 현황 ({selected_otb_date})")
        if df_otb.empty: 
            st.warning("⚠️ 선택한 날짜의 OTB 데이터가 없습니다.")
        else:
            base = df_otb.copy(); base['M'] = pd.to_datetime(base['CheckIn']).dt.month
            grp_otb = base.groupby('M').agg({'Room_Revenue':'sum'}).reset_index()
            fin = pd.merge(pd.DataFrame({'M': range(1, 13)}), grp_otb, on='M', how='left').fillna(0)
            fin['Budget'] = fin['M'].map(BUDGET_DATA).fillna(0)
            fin['OTB'] = fin['Room_Revenue']
            fin['Rate'] = np.where(fin['Budget'] > 0, (fin['OTB'] / fin['Budget']) * 100, 0)
            fin['Name'] = fin['M'].astype(str) + "월"
            
            fig_otb = go.Figure()
            fig_otb.add_trace(go.Bar(x=fin['Name'], y=fin['OTB'], name='OTB (현재)', marker_color='#2E86C1', text=fin['Rate'].apply(lambda x: f"{x:.1f}%"), textposition='outside'))
            fig_otb.add_trace(go.Scatter(x=fin['Name'], y=fin['Budget'], name='Budget (목표)', line=dict(color='red', dash='dot', width=3)))
            fig_otb.update_layout(height=550, yaxis_title="매출 (KRW)", margin=dict(t=50))
            st.plotly_chart(fig_otb, use_container_width=True, key="otb_main_chart")
            
            res_dict = {}
            tb, to = fin['Budget'].sum(), fin['OTB'].sum()
            for _, r in fin.iterrows(): res_dict[r['Name']] = [f"{r['Budget']:,.0f}", f"{r['OTB']:,.0f}", f"{r['Rate']:.1f}%"]
            res_dict['합계 (Total)'] = [f"{tb:,.0f}", f"{to:,.0f}", f"{(to/tb*100 if tb>0 else 0):.1f}%"]
            st.dataframe(pd.DataFrame(res_dict, index=['Budget (목표)', 'OTB (현재)', '달성률 (%)']).style.apply(lambda s: ['background-color: #fff9c4; font-weight: bold; border-left: 2px solid black; color: black'] * len(s) if s.name == '합계 (Total)' else [''] * len(s), axis=0), use_container_width=True)

except Exception as e:
    st.error(f"🚨 시스템 오류: {e}")

# ==============================================================================
# Forecasting 시스템 연동
# ==============================================================================
try:
    save_month = datetime.now().month
    if 'sob_curr' in locals() and sob_curr is not None:
        st.session_state[f"sob_{save_month}"] = sob_curr
        if 'df_curr' in locals() and 'df_prev' in locals():
            st.session_state[f"pace_{save_month}"] = len(df_curr) - len(df_prev)
        st.success(f"✅ {save_month}월 데이터가 포캐스팅 시스템으로 전송되었습니다.")
except: pass
