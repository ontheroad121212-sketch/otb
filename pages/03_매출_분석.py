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
# 0. 페이지 설정 및 CSS
# ==============================================================================
st.set_page_config(page_title="ARI Final Integrity", layout="wide")

st.markdown("""
<style>
    /* 전체 여백 조정 */
    .block-container {
        padding-top: 1rem;
        padding-bottom: 5rem;
    }
    
    /* 숫자(Metric) 스타일: 크고 진하게 */
    div[data-testid="stMetricValue"] { 
        font-size: 26px !important; 
        font-weight: 900; 
        color: #0f172a; 
    }
    div[data-testid="stMetricLabel"] { 
        font-size: 15px !important; 
        font-weight: 700; 
        color: #64748b; 
    }
    
    /* 탭 스타일 */
    button[data-baseweb="tab"] { 
        font-size: 16px !important; 
        font-weight: 700; 
    }
    
    /* 데이터프레임 합계(Total) 행 스타일 강조 */
    [data-testid="stDataFrame"] table tr:last-child td {
        font-weight: 900 !important;
        background-color: #fff9c4 !important; /* 연한 노란색 */
        color: #000000 !important;
        border-top: 2px solid #000000 !important;
    }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 1. 파이어베이스 연결
# ==============================================================================
if not firebase_admin._apps:
    try:
        cred = credentials.Certificate(dict(st.secrets["firebase"]))
        firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"🔥 파이어베이스 연결 실패: {e}")
        st.stop()

db = firestore.client()
COLLECTION_NAME = "revenue_integrity_history"

# ==============================================================================
# 2. 핵심 유틸리티 함수: 데이터 정제 및 저장/로드
# ==============================================================================

def clean_numeric_columns(df):
    """
    [핵심] 데이터프레임의 숫자 컬럼을 강제로 숫자형(Float/Int)으로 변환
    """
    target_cols = ['RN', 'Room_Revenue', 'Total_Revenue', 'ADR_Room', 'ADR_Total', 'Lead_Time', 
                   'OTB_Rev', 'Actual_Rev', 'OTB_RN', 'Actual_RN']
    
    for col in target_cols:
        if col in df.columns:
            # 1. 문자열 변환 -> 2. 콤마 제거 -> 3. 숫자 변환 -> 4. NaN은 0으로
            df[col] = pd.to_numeric(
                df[col].astype(str).str.replace(',', ''), 
                errors='coerce'
            ).fillna(0)
            
    # [ADR 재계산 로직] 숫자가 된 상태에서 다시 계산하여 정확도 보장
    if 'RN' in df.columns:
        if 'Room_Revenue' in df.columns:
            df['ADR_Room'] = np.where(df['RN'] > 0, df['Room_Revenue'] / df['RN'], 0)
        if 'Total_Revenue' in df.columns:
            df['ADR_Total'] = np.where(df['RN'] > 0, df['Total_Revenue'] / df['RN'], 0)
            
    return df

def save_to_firestore(df):
    """데이터 저장"""
    try:
        records = df.fillna(0).astype(str).to_dict(orient='records')
        doc_ref = db.collection(COLLECTION_NAME).document()
        doc_ref.set({
            'data': records,
            'uploaded_at': datetime.now(),
            'snapshot_date': datetime.now().strftime('%Y-%m-%d'), 
            'count': len(records)
        })
        return True
    except Exception as e:
        st.error(f"❌ 저장 오류: {e}")
        return False

@st.cache_data(ttl=0)
def load_data_from_firestore():
    """데이터 로드"""
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
        st.error(f"❌ 데이터 로드 오류: {e}")
        return []

# ==============================================================================
# 3. 엑셀 파일 처리 로직
# ==============================================================================

def normalize_and_map_columns(df):
    """컬럼명 표준화"""
    col_map = {}
    rules = {
        'CheckIn': ['checkin', 'check-in', 'arrival', '입실', '일자', 'date'],
        'Guest_Name': ['guest', 'name', 'customer', '고객', '투숙객', '성명'],
        'Booking_Date': ['booking', 'create', 'res', '예약', '생성'],
        'Rooms': ['room', 'qty', 'rmws', '객실수', '수량'],
        'Nights': ['night', 'los', '박수', '박'],
        'Room_Revenue': ['room_rev', 'revenue', 'roomrate', '객실료', '매출'],
        'Total_Revenue': ['total', 'amount', '총금액', '합계'],
        'Segment': ['segment', '세그먼트'],
        'Account': ['account', 'source', 'agent', '거래처', '에이전시'],
        'Room_Type': ['type', 'cat', '객실타입', '룸타입'],
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
    for i, row in df.iterrows():
        row_str = " ".join(row.astype(str).values).lower()
        keywords = ['guest', 'name', 'check', 'date', 'room', '고객', '입실', '객실']
        if sum(1 for k in keywords if k in row_str) >= 2:
            df.columns = df.iloc[i]
            return df.iloc[i+1:].reset_index(drop=True)
    return df

def process_data(uploaded_file, status, sub_segment="General"):
    """파일 업로드 처리"""
    try:
        is_otb = "Sales on the Book" in uploaded_file.name or "영업 현황" in uploaded_file.name
        
        if uploaded_file.name.endswith('.csv'):
            df_raw = pd.read_csv(uploaded_file, header=None)
        else:
            df_raw = pd.read_excel(uploaded_file, header=None)

        if is_otb:
            df_raw = find_valid_header_row(df_raw)
            if '일자' in df_raw.columns: 
                df_raw = df_raw[~df_raw['일자'].astype(str).str.contains('소계|Subtotal|합계|Total', na=False)]
            
            df = pd.DataFrame()
            df['Guest_Name'] = f'OTB_{sub_segment}_DATA'
            date_col = next((c for c in df_raw.columns if '일자' in str(c) or 'Date' in str(c)), df_raw.columns[0])
            df['CheckIn'] = pd.to_datetime(df_raw[date_col], errors='coerce')
            
            try:
                df['RN'] = pd.to_numeric(df_raw.iloc[:, -5], errors='coerce').fillna(0)
                df['Room_Revenue'] = pd.to_numeric(df_raw.iloc[:, -1], errors='coerce').fillna(0)
                df['ADR_Room'] = pd.to_numeric(df_raw.iloc[:, -3], errors='coerce').fillna(0)
                df['Total_Revenue'] = df['Room_Revenue'] # OTB는 보통 객실매출만 있음
            except:
                df['RN'] = 0; df['Room_Revenue'] = 0; df['ADR_Room'] = 0; df['Total_Revenue'] = 0

            df['ADR_Total'] = df['ADR_Room']
            df['Booking_Date'] = df['CheckIn']
            df['Segment'] = 'OTB' # 통합 OTB
            df['Account'] = 'OTB_Summary'
            df['Room_Type'] = 'Run of House'
            df['Nat_Orig'] = 'KOR'
            df['Lead_Time'] = 0
        else:
            df_raw = find_valid_header_row(df_raw)
            df_raw = df_raw[~df_raw.iloc[:, 0].astype(str).str.contains('합계|Total|소계|Subtotal', case=False, na=False)]
            df = normalize_and_map_columns(df_raw).copy()
            
            if 'CheckIn' not in df.columns: return pd.DataFrame()
            if 'Booking_Date' not in df.columns: df['Booking_Date'] = df['CheckIn']
            
            req_cols = ['Rooms', 'Nights', 'Room_Revenue', 'Total_Revenue', 'Guest_Name', 'Segment', 'Account', 'Room_Type', 'Nat_Orig', 'Lead_Time']
            for c in req_cols:
                if c not in df.columns: 
                    if c in ['Rooms', 'Nights', 'Room_Revenue', 'Total_Revenue', 'Lead_Time']: df[c] = 0 
                    else: df[c] = 'Unknown'

            # 1차 숫자 변환
            for col in ['Room_Revenue', 'Total_Revenue', 'Rooms', 'Nights', 'Lead_Time']:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            
            df['Total_Revenue'] = np.where(df['Total_Revenue'] == 0, df['Room_Revenue'], df['Total_Revenue'])
            df['RN'] = df['Rooms'] * df['Nights'].replace(0, 1)
            df['Is_Zero_Rate'] = df['Room_Revenue'] <= 0
            
            # ADR 2개 계산 (객실 / 전체)
            df['ADR_Room'] = df.apply(lambda x: x['Room_Revenue'] / x['RN'] if x['RN'] > 0 else 0, axis=1)
            df['ADR_Total'] = df.apply(lambda x: x['Total_Revenue'] / x['RN'] if x['RN'] > 0 else 0, axis=1)

        df['Snapshot_Date'] = datetime.now().strftime('%Y-%m-%d') 
        df['Status'] = status
        
        df['CheckIn_dt'] = pd.to_datetime(df['CheckIn'], errors='coerce')
        df['Booking_dt'] = pd.to_datetime(df['Booking_Date'], errors='coerce')
        df.loc[df['Booking_dt'].isna(), 'Booking_dt'] = df.loc[df['Booking_dt'].isna(), 'CheckIn_dt']
        
        df = df.dropna(subset=['CheckIn_dt'])
        df['Stay_Month'] = df['CheckIn_dt'].dt.strftime('%Y-%m')
        df['Booking_Month'] = df['Booking_dt'].dt.strftime('%Y-%m')
        df['Stay_YearWeek'] = df['CheckIn_dt'].dt.strftime('%Y-%U주')
        df['Day_of_Week'] = df['CheckIn_dt'].dt.day_name()
        df['Weekday_Num'] = df['CheckIn_dt'].dt.weekday
        df['Day_Type'] = df['Weekday_Num'].apply(lambda x: 'Weekend' if x >= 4 else 'Weekday')
        df['Lead_Time'] = df['Lead_Time'].fillna(0).astype(int)
        
        def classify_nat(row):
            name = str(row.get('Guest_Name', ''))
            orig = str(row.get('Nat_Orig', '')).upper()
            if re.search('[가-힣]', name): return 'KOR'
            if any(x in orig for x in ['CHN', 'HKG', 'TWN', 'MAC']): return 'CHN'
            return 'OTH'
        df['Nat_Group'] = df.apply(classify_nat, axis=1)

        def get_month_label(row_dt):
            try:
                curr = datetime.now()
                offset = (row_dt.year - curr.year) * 12 + (row_dt.month - curr.month)
                if offset == 0: return "0.당월(M)"
                elif offset == 1: return "1.익월(M+1)"
                elif offset == 2: return "2.익익월(M+2)"
                else: return "3.그외"
            except: return "Unknown"
        df['Month_Label'] = df['CheckIn_dt'].apply(get_month_label)
        
        df['CheckIn'] = df['CheckIn_dt'].dt.strftime('%Y-%m-%d')
        
        cols = ['Guest_Name', 'CheckIn', 'RN', 'Room_Revenue', 'Total_Revenue', 'ADR_Room', 'ADR_Total', 'Segment', 'Account', 'Room_Type', 'Snapshot_Date', 'Status', 'Stay_Month', 'Booking_Month', 'Stay_YearWeek', 'Lead_Time', 'Day_Type', 'Day_of_Week', 'Nat_Group', 'Month_Label', 'Is_Zero_Rate']
        
        final_df = pd.DataFrame()
        for c in cols:
            final_df[c] = df[c] if c in df.columns else ''
        
        # 마지막으로 숫자 정제 함수 통과
        final_df = clean_numeric_columns(final_df)
        
        return final_df

    except Exception as e:
        return pd.DataFrame()

# ==============================================================================
# 3. [핵심] 합계 행 추가 및 스타일링 헬퍼
# ==============================================================================

def add_total_row(df, group_col_name="구분"):
    """
    데이터프레임 하단에 '합계(TOTAL)' 행을 추가합니다.
    - 입력받은 df의 숫자가 반드시 숫자형이어야 합니다.
    - ADR은 (매출 / RN)으로 각각 재계산합니다.
    """
    if df.empty: return df
    
    numeric_df = df.select_dtypes(include=[np.number]).fillna(0)
    totals = numeric_df.sum().to_dict()
    
    total_row = {col: "" for col in df.columns}
    total_row.update(totals)
    
    if group_col_name in df.columns:
        total_row[group_col_name] = "TOTAL"
    else:
        total_row[df.columns[0]] = "TOTAL"

    # [ADR 재계산: Room ADR / Total ADR 각각 계산]
    if 'RN' in total_row and total_row['RN'] > 0:
        if 'Room_Revenue' in total_row:
            total_row['ADR_Room'] = total_row['Room_Revenue'] / total_row['RN']
        if 'Total_Revenue' in total_row:
            total_row['ADR_Total'] = total_row['Total_Revenue'] / total_row['RN']
    else:
        total_row['ADR_Room'] = 0
        total_row['ADR_Total'] = 0
            
    df_total = pd.DataFrame([total_row])
    return pd.concat([df, df_total], ignore_index=True)

def show_dataframe_with_style(df):
    """
    Pandas Styler를 사용하여 무조건 콤마와 소수점 제거를 적용합니다.
    """
    if df.empty:
        st.write("No Data")
        return

    # 숫자 컬럼 식별
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    
    # 1. 스타일러 생성 및 포맷 적용 (천단위 콤마, 소수점 0자리)
    styler = df.style.format({col: "{:,.0f}" for col in numeric_cols})
    
    # 2. 마지막 행(Total) 배경색 강조
    def highlight_total(row):
        is_total = False
        for val in row:
            if str(val) == "TOTAL":
                is_total = True
                break
        if is_total:
            return ['background-color: #fff9c4; font-weight: bold; color: black; border-top: 2px solid black'] * len(row)
        return [''] * len(row)
    
    styler = styler.apply(highlight_total, axis=1)
    st.dataframe(styler, hide_index=True, use_container_width=True)

def get_fmt_config():
    """스트림릿용 포맷 설정 (Styler와 병행 사용)"""
    return {
        "RN": st.column_config.NumberColumn("객실수", format="%d"),
        "Room_Revenue": st.column_config.NumberColumn("객실매출", format="%d"),
        "Total_Revenue": st.column_config.NumberColumn("총매출", format="%d"),
        "ADR_Room": st.column_config.NumberColumn("객실 ADR", format="%d"),
        "ADR_Total": st.column_config.NumberColumn("총 ADR", format="%d"),
        "Lead_Time": st.column_config.NumberColumn("리드타임", format="%d")
    }

def render_analysis_tab(target_df, title_prefix, color_scale="Blues"):
    """분석 탭 렌더링"""
    if target_df.empty:
        st.warning(f"⚠️ {title_prefix} 데이터가 없습니다.")
        return

    t1, t2, t3, t4, t5, t6, t7 = st.tabs([
        "📊 세그먼트", "📅 예약패턴", "🏢 거래처", 
        "⏳ 리드타임", "🛏️ 객실타입", "🗓️ 요일별", "🌐 국적별"
    ])
    
    with t1:
        st.subheader(f"📊 {title_prefix} 세그먼트 분석")
        # 매출 2개 모두 집계
        seg_stats = target_df.groupby('Segment').agg({'RN': 'sum', 'Room_Revenue': 'sum', 'Total_Revenue': 'sum'}).reset_index()
        # ADR 각각 계산
        seg_stats['ADR_Room'] = np.where(seg_stats['RN']>0, seg_stats['Room_Revenue']/seg_stats['RN'], 0)
        seg_stats['ADR_Total'] = np.where(seg_stats['RN']>0, seg_stats['Total_Revenue']/seg_stats['RN'], 0)
        
        seg_stats_final = add_total_row(seg_stats, 'Segment')
        
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.pie(seg_stats, values='Room_Revenue', names='Segment', title="매출 비중"), use_container_width=True)
        c2.plotly_chart(px.bar(seg_stats, x='Segment', y='Room_Revenue', text_auto='.2s', title="매출액"), use_container_width=True)
        
        show_dataframe_with_style(seg_stats_final)

    with t2:
        st.subheader(f"📅 Pacing Analysis")
        piv = target_df.pivot_table(index='Booking_Month', columns='Stay_Month', values='RN', aggfunc='sum').fillna(0)
        st.plotly_chart(px.imshow(piv, text_auto="d", aspect="auto", color_continuous_scale=color_scale), use_container_width=True)

    with t3:
        st.subheader("🏢 거래처 분석")
        acc_stats = target_df.groupby('Account').agg({'RN': 'sum', 'Room_Revenue': 'sum', 'Total_Revenue': 'sum'}).reset_index()
        acc_stats['ADR_Room'] = np.where(acc_stats['RN']>0, acc_stats['Room_Revenue']/acc_stats['RN'], 0)
        acc_stats['ADR_Total'] = np.where(acc_stats['RN']>0, acc_stats['Total_Revenue']/acc_stats['RN'], 0)
        
        acc_stats = acc_stats.sort_values('RN', ascending=False).head(100)
        acc_final = add_total_row(acc_stats, 'Account')
        
        show_dataframe_with_style(acc_final)

    with t4:
        st.subheader("⏳ 리드타임")
        bins = [-1, 0, 3, 7, 14, 30, 60, 90, 999]
        labels = ['0일', '1-3일', '4-7일', '8-14일', '15-30일', '31-60일', '61-90일', '90일+']
        temp_df = target_df.copy()
        temp_df['Lead_Group'] = pd.cut(temp_df['Lead_Time'], bins=bins, labels=labels)
        lead_stats = temp_df.groupby('Lead_Group').agg({'RN': 'sum', 'Room_Revenue': 'sum', 'Total_Revenue': 'sum'}).reset_index()
        lead_stats['ADR_Room'] = np.where(lead_stats['RN']>0, lead_stats['Room_Revenue']/lead_stats['RN'], 0)
        lead_stats['ADR_Total'] = np.where(lead_stats['RN']>0, lead_stats['Total_Revenue']/lead_stats['RN'], 0)
        
        lead_final = add_total_row(lead_stats, 'Lead_Group')
        
        st.plotly_chart(px.bar(lead_stats, x='Lead_Group', y='RN'), use_container_width=True)
        show_dataframe_with_style(lead_final)

    with t5:
        st.subheader("🛏️ 객실타입")
        rt_stats = target_df.groupby('Room_Type').agg({'RN': 'sum', 'Room_Revenue': 'sum', 'Total_Revenue': 'sum'}).reset_index()
        rt_stats['ADR_Room'] = np.where(rt_stats['RN']>0, rt_stats['Room_Revenue']/rt_stats['RN'], 0)
        rt_stats['ADR_Total'] = np.where(rt_stats['RN']>0, rt_stats['Total_Revenue']/rt_stats['RN'], 0)
        
        rt_final = add_total_row(rt_stats.sort_values('RN', ascending=False), 'Room_Type')
        show_dataframe_with_style(rt_final)

    with t6:
        st.subheader("🗓️ 요일별")
        wd_stats = target_df.groupby('Day_Type').agg({'RN': 'sum', 'Room_Revenue': 'sum', 'Total_Revenue': 'sum'}).reset_index()
        wd_stats['ADR_Room'] = np.where(wd_stats['RN']>0, wd_stats['Room_Revenue']/wd_stats['RN'], 0)
        wd_stats['ADR_Total'] = np.where(wd_stats['RN']>0, wd_stats['Total_Revenue']/wd_stats['RN'], 0)
        
        wd_final = add_total_row(wd_stats, 'Day_Type')
        
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.bar(wd_stats, x='Day_Type', y='Room_Revenue'), use_container_width=True)
        c2.plotly_chart(px.pie(wd_stats, values='RN', names='Day_Type'), use_container_width=True)
        show_dataframe_with_style(wd_final)

    with t7:
        st.subheader("🌐 국적별")
        if 'Nat_Group' in target_df.columns:
            nat_stats = target_df.groupby('Nat_Group').agg({'RN': 'sum', 'Room_Revenue': 'sum', 'Total_Revenue': 'sum'}).reset_index()
            nat_stats['ADR_Room'] = np.where(nat_stats['RN']>0, nat_stats['Room_Revenue']/nat_stats['RN'], 0)
            nat_stats['ADR_Total'] = np.where(nat_stats['RN']>0, nat_stats['Total_Revenue']/nat_stats['RN'], 0)
            
            nat_final = add_total_row(nat_stats, 'Nat_Group')
            
            c1, c2 = st.columns(2)
            c1.plotly_chart(px.pie(nat_stats, values='RN', names='Nat_Group', title="국적 비중"), use_container_width=True)
            c2.plotly_chart(px.bar(nat_stats, x='Nat_Group', y='Room_Revenue'), use_container_width=True)
            
            show_dataframe_with_style(nat_final)
        else:
            st.info("국적 데이터 없음")

# ==============================================================================
# UI 메인 실행
# ==============================================================================
try:
    st.title("🏛️ 앰버 호텔 경영 리포트 (Final Integrity)")

    # 1. 데이터 로드 (DB)
    raw_data = load_data_from_firestore()
    df_all = pd.DataFrame()
    available_dates = []
    
    if raw_data:
        df_all = pd.DataFrame(raw_data)
        if 'Snapshot_Date' in df_all.columns:
            available_dates = sorted(df_all['Snapshot_Date'].unique(), reverse=True)

    # 2. 사이드바
    with st.sidebar:
        st.header("📅 조회 설정")
        selected_date = None
        if available_dates:
            selected_date = st.selectbox("조회 기준일 (Snapshot)", available_dates, index=0)
        else:
            st.warning("데이터가 없습니다.")

        st.markdown("---")
        st.header("📤 데이터 업로드")
        
        with st.expander("예약/취소 리스트", expanded=True):
            f1 = st.file_uploader("예약 리스트", type=['xlsx','csv'], key="f1")
            if f1 and st.button("예약 저장"):
                df = process_data(f1, "Booked")
                if not df.empty and save_to_firestore(df):
                    st.cache_data.clear()
                    st.rerun()
            
            f2 = st.file_uploader("취소 리스트", type=['xlsx','csv'], key="f2")
            if f2 and st.button("취소 저장"):
                df = process_data(f2, "Cancelled")
                if not df.empty and save_to_firestore(df):
                    st.cache_data.clear()
                    st.rerun()

        with st.expander("OTB (Sales on the Book)", expanded=True):
            f3_list = st.file_uploader("당월 OTB (12개월 통합)", type=['xlsx','csv'], key="f3", accept_multiple_files=True)
            if f3_list and st.button("OTB 저장"):
                for f in f3_list:
                    df = process_data(f, "Booked", "Month")
                    if not df.empty: save_to_firestore(df)
                st.cache_data.clear()
                st.rerun()
            
    # 3. 메인 콘텐츠
    if selected_date and not df_all.empty:
        df_filtered = df_all[df_all['Snapshot_Date'] == selected_date].copy()
        
        # [데이터 세탁] 숫자 강제 변환 및 ADR 재계산
        df = clean_numeric_columns(df_filtered)
        
        if df.empty:
            st.warning("데이터가 없습니다.")
        else:
            # 날짜형 변환
            if 'Booking_Date' not in df.columns: df['Booking_Date'] = df['CheckIn']
            df['Booking_dt'] = pd.to_datetime(df['Booking_Date'], errors='coerce')
            df['CheckIn_dt'] = pd.to_datetime(df['CheckIn'], errors='coerce')
            df = df.dropna(subset=['CheckIn_dt'])
            df.loc[df['Booking_dt'].isna(), 'Booking_dt'] = df.loc[df['Booking_dt'].isna(), 'CheckIn_dt']
            
            # 파생 변수
            df['Is_Zero_Rate'] = df['Total_Revenue'] <= 0
            df['Booking_Month'] = df['Booking_dt'].dt.strftime('%Y-%m')
            df['Stay_Month'] = df['CheckIn_dt'].dt.strftime('%Y-%m')
            
            # 데이터 분리
            df_otb_m = df[df['Segment'] == 'OTB_Month']
            df_otb_t = df[df['Segment'] == 'OTB_Total']
            # OTB 통합처리 (Segment가 OTB이거나 OTB_Month 등인 경우)
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

            # -----------------------------------------------------------
            # 1. GM 요약 탭 (총매출/객실매출/ADR 분리)
            # -----------------------------------------------------------
            with main_tab0:
                st.header(f"👑 총지배인(GM) 요약 리포트 ({selected_date})")
                
                st.subheader("1. 금일(Today) 예약 vs 취소")
                
                # 예약 지표
                bk_cnt = len(df_paid_bk)
                bk_rn = df_paid_bk['RN'].sum()
                bk_room_rev = df_paid_bk['Room_Revenue'].sum()
                bk_total_rev = df_paid_bk['Total_Revenue'].sum()
                
                bk_adr_room = bk_room_rev / bk_rn if bk_rn > 0 else 0
                bk_adr_total = bk_total_rev / bk_rn if bk_rn > 0 else 0
                
                # 취소 지표
                cn_cnt = len(df_list_cn)
                cn_rn = df_list_cn['RN'].sum()
                cn_room_rev = df_list_cn['Room_Revenue'].sum()
                cn_total_rev = df_list_cn['Total_Revenue'].sum()
                
                cn_adr_room = cn_room_rev / cn_rn if cn_rn > 0 else 0
                cn_adr_total = cn_total_rev / cn_rn if cn_rn > 0 else 0
                
                # 예약 섹션
                st.markdown("#### ✅ 신규 예약")
                c1, c2, c3, c4, c5, c6 = st.columns(6)
                c1.metric("예약 건수", f"{bk_cnt:,.0f} 건")
                c2.metric("예약 RN", f"{bk_rn:,.0f} 박")
                c3.metric("객실 매출", f"{bk_room_rev:,.0f} 원")
                c4.metric("총 매출", f"{bk_total_rev:,.0f} 원")
                c5.metric("객실 ADR", f"{bk_adr_room:,.0f} 원")
                c6.metric("총 ADR", f"{bk_adr_total:,.0f} 원")
                
                # 취소 섹션
                st.markdown("#### ❌ 취소")
                c1, c2, c3, c4, c5, c6 = st.columns(6)
                c1.metric("취소 건수", f"{cn_cnt:,.0f} 건")
                c2.metric("취소 RN", f"{cn_rn:,.0f} 박")
                c3.metric("취소 객실매출", f"{cn_room_rev:,.0f} 원")
                c4.metric("취소 총매출", f"{cn_total_rev:,.0f} 원")
                c5.metric("취소 객실ADR", f"{cn_adr_room:,.0f} 원")
                c6.metric("취소 총ADR", f"{cn_adr_total:,.0f} 원")
                
                st.divider()
                
                # 세그먼트별 픽업 (상세 분리)
                st.subheader("2. 세그먼트별 픽업 현황 (예약)")
                if not df_paid_bk.empty:
                    seg_gm = df_paid_bk.groupby('Segment').agg({
                        'RN': 'sum', 
                        'Room_Revenue': 'sum', 
                        'Total_Revenue': 'sum'
                    }).reset_index()
                    
                    # ADR 각각 계산
                    seg_gm['ADR_Room'] = np.where(seg_gm['RN']>0, seg_gm['Room_Revenue']/seg_gm['RN'], 0)
                    seg_gm['ADR_Total'] = np.where(seg_gm['RN']>0, seg_gm['Total_Revenue']/seg_gm['RN'], 0)
                    
                    seg_gm_final = add_total_row(seg_gm, 'Segment')
                    
                    # 원하는 순서로 컬럼 정렬
                    cols_order = ['Segment', 'RN', 'Room_Revenue', 'Total_Revenue', 'ADR_Room', 'ADR_Total']
                    # 존재하는 컬럼만 선택
                    cols_final = [c for c in cols_order if c in seg_gm_final.columns]
                    seg_gm_final = seg_gm_final[cols_final]
                    
                    show_dataframe_with_style(seg_gm_final) 
                else:
                    st.info("예약 데이터 없음")
                
                st.divider()

                # 국적 / 월별 비중
                c_left, c_right = st.columns(2)
                with c_left:
                    st.subheader("3. 국적별 비중 (예약)")
                    if 'Nat_Group' in df_paid_bk.columns and not df_paid_bk.empty:
                        nat_gm = df_paid_bk.groupby('Nat_Group')['RN'].sum().reset_index()
                        fig_nat = px.pie(nat_gm, values='RN', names='Nat_Group', hole=0.4)
                        st.plotly_chart(fig_nat, use_container_width=True)
                    else:
                        st.info("데이터 없음")
                
                with c_right:
                    st.subheader("4. 월별 예약/취소 집중도")
                    bk_m = df_paid_bk.groupby('Stay_Month')['RN'].sum().reset_index()
                    bk_m['Type'] = '예약'
                    cn_m = df_list_cn.groupby('Stay_Month')['RN'].sum().reset_index()
                    cn_m['Type'] = '취소'
                    comb_m = pd.concat([bk_m, cn_m])
                    if not comb_m.empty:
                        fig_m = px.bar(comb_m, x='Stay_Month', y='RN', color='Type', barmode='group', text_auto='.0f')
                        st.plotly_chart(fig_m, use_container_width=True)
                    else:
                        st.info("데이터 없음")

            # -----------------------------------------------------------
            # 나머지 분석 탭
            # -----------------------------------------------------------
            with main_tab1:
                render_analysis_tab(df_paid_bk, "유료 예약", "Blues")
            
            with main_tab2:
                render_analysis_tab(df_list_cn, "취소 데이터", "Reds")
                
            with main_tab3:
                render_analysis_tab(df_total_paid, "종합(예약+취소)", "Greens")
                
            with main_tab4:
                st.subheader(f"🆓 0원 예약 (총 {len(df_zero_bk)}건)")
                st.dataframe(df_zero_bk[['Guest_Name', 'CheckIn', 'Account', 'Room_Type']], use_container_width=True)

            with main_tab5:
                st.header("🎯 OTB 현황")
                
                if df_otb.empty:
                    st.warning("업로드된 OTB 데이터가 없습니다.")
                else:
                    # OTB 월별 집계
                    otb_monthly = df_otb.groupby('CheckIn').agg({'Room_Revenue': 'sum', 'RN': 'sum'}).reset_index()
                    otb_monthly.rename(columns={'CheckIn': 'Stay_Month', 'Room_Revenue': 'OTB_Rev', 'RN': 'OTB_RN'}, inplace=True)
                    otb_monthly['Stay_Month'] = pd.to_datetime(otb_monthly['Stay_Month']).dt.strftime('%Y-%m')
                    otb_agg = otb_monthly.groupby('Stay_Month')[['OTB_Rev', 'OTB_RN']].sum().reset_index()
                    
                    # 실제 예약 집계
                    if not df_paid_bk.empty:
                        act_monthly = df_paid_bk.groupby('Stay_Month').agg({'Room_Revenue': 'sum', 'RN': 'sum'}).reset_index()
                        act_monthly.rename(columns={'Room_Revenue': 'Actual_Rev', 'RN': 'Actual_RN'}, inplace=True)
                        merged = pd.merge(otb_agg, act_monthly, on='Stay_Month', how='outer').fillna(0)
                    else:
                        merged = otb_agg
                        merged['Actual_Rev'] = 0; merged['Actual_RN'] = 0
                    
                    merged = merged.sort_values('Stay_Month')
                    
                    # 합계 행
                    merged_final = add_total_row(merged, 'Stay_Month')

                    st.subheader("📊 OTB vs Actual 매출 비교")
                    fig_otb = go.Figure()
                    fig_otb.add_trace(go.Bar(x=merged['Stay_Month'], y=merged['Actual_Rev'], name='Actual', marker_color='#2E86C1'))
                    fig_otb.add_trace(go.Scatter(x=merged['Stay_Month'], y=merged['OTB_Rev'], name='OTB Goal', line=dict(color='#E74C3C', width=3, dash='dot')))
                    st.plotly_chart(fig_otb, use_container_width=True)
                    
                    show_dataframe_with_style(merged_final)

    else:
        st.info("👈 왼쪽에서 파일을 업로드해주세요.")

except Exception as e:
    st.error(f"🚨 시스템 오류: {e}")
