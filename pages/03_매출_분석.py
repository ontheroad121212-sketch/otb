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

# ------------------------------------------------------------------------------
# 0. 스타일 & 유틸리티
# ------------------------------------------------------------------------------
st.set_page_config(page_title="ARI Final Integrity", layout="wide")
st.markdown("""
<style>
    div[data-testid="stMetricValue"] { font-size: 24px !important; font-weight: 800; color: #333; }
    div[data-testid="stMetricLabel"] { font-size: 16px !important; font-weight: 600; }
    button[data-baseweb="tab"] { font-size: 16px !important; font-weight: 700; }
    .stSelectbox label { font-size: 1.1rem; font-weight: 700; }
</style>
""", unsafe_allow_html=True)

# ------------------------------------------------------------------------------
# 1. 파이어베이스 연결 & 데이터 함수
# ------------------------------------------------------------------------------
if not firebase_admin._apps:
    cred = credentials.Certificate(dict(st.secrets["firebase"]))
    firebase_admin.initialize_app(cred)
db = firestore.client()

# 컬렉션 이름 (이곳에 히스토리가 쌓입니다)
COLLECTION_NAME = "revenue_integrity_history"

def save_to_firestore(df):
    """데이터프레임을 파이어베이스에 저장 (Append Mode)"""
    try:
        # 날짜 등 객체 타입을 문자열로 변환하여 JSON 오류 방지
        records = df.fillna('').astype(str).to_dict(orient='records')
        
        # 문서 생성 (업로드 시간 기반 ID)
        doc_ref = db.collection(COLLECTION_NAME).document()
        doc_ref.set({
            'data': records,
            'uploaded_at': datetime.now(),
            'snapshot_date': datetime.now().strftime('%Y-%m-%d'), # 조회 기준일(오늘)
            'count': len(records)
        })
        return True
    except Exception as e:
        st.error(f"❌ 저장 오류: {e}")
        return False

@st.cache_data(ttl=600)
def load_data_from_firestore():
    """파이어베이스에서 모든 히스토리 데이터 불러오기"""
    try:
        docs = db.collection(COLLECTION_NAME).stream()
        all_data = []
        
        for doc in docs:
            doc_dict = doc.to_dict()
            if 'data' in doc_dict:
                # 각 행에 스냅샷 날짜(업로드일) 정보 추가
                doc_date = doc_dict.get('snapshot_date', '')
                rows = doc_dict['data']
                
                # 데이터프레임 변환 후 날짜 보정
                for row in rows:
                    if 'Snapshot_Date' not in row or not row['Snapshot_Date']:
                        row['Snapshot_Date'] = doc_date
                    all_data.append(row)
        
        if not all_data:
            return []
            
        return all_data
        
    except Exception as e:
        st.error(f"❌ 데이터 로드 오류: {e}")
        return []

# ------------------------------------------------------------------------------
# 2. 데이터 처리 엔진 (로직 유지)
# ------------------------------------------------------------------------------
def normalize_and_map_columns(df):
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
            elif df_raw.shape[1] > 0:
                df_raw = df_raw[~df_raw.iloc[:, 0].astype(str).str.contains('소계|Subtotal|합계|Total', na=False)]

            df = pd.DataFrame()
            df['Guest_Name'] = f'OTB_{sub_segment}_DATA'
            
            date_col = next((c for c in df_raw.columns if '일자' in str(c) or 'Date' in str(c)), df_raw.columns[0])
            df['CheckIn'] = pd.to_datetime(df_raw[date_col], errors='coerce')
            
            try:
                df['RN'] = pd.to_numeric(df_raw.iloc[:, -5], errors='coerce').fillna(0)
                df['Room_Revenue'] = pd.to_numeric(df_raw.iloc[:, -1], errors='coerce').fillna(0)
                df['ADR'] = pd.to_numeric(df_raw.iloc[:, -3], errors='coerce').fillna(0)
                df['Total_Revenue'] = df['Room_Revenue']
            except:
                df['RN'] = 0; df['Room_Revenue'] = 0; df['ADR'] = 0; df['Total_Revenue'] = 0

            df['Booking_Date'] = df['CheckIn']
            df['Segment'] = f'OTB_{sub_segment}'
            df['Account'] = 'OTB_Summary'
            df['Room_Type'] = 'Run of House'
            df['Nat_Orig'] = 'KOR'
            df['Lead_Time'] = 0
            
        else:
            df_raw = find_valid_header_row(df_raw)
            df_raw = df_raw[~df_raw.iloc[:, 0].astype(str).str.contains('합계|Total|소계|Subtotal', case=False, na=False)]
            
            df = normalize_and_map_columns(df_raw).copy()
            if 'Guest_Name' in df.columns:
                df = df[~df['Guest_Name'].astype(str).str.contains('합계|Total|소계|Subtotal', case=False, na=False)]
            
            if 'CheckIn' not in df.columns: return pd.DataFrame()
            if 'Booking_Date' not in df.columns: df['Booking_Date'] = df['CheckIn']
            
            req_cols = ['Rooms', 'Nights', 'Room_Revenue', 'Total_Revenue', 'Guest_Name', 'Segment', 'Account', 'Room_Type', 'Nat_Orig', 'Lead_Time']
            for c in req_cols:
                if c not in df.columns: 
                    if c in ['Rooms', 'Nights', 'Room_Revenue', 'Total_Revenue', 'Lead_Time']: df[c] = 0 
                    else: df[c] = 'Unknown'

            for col in ['Room_Revenue', 'Total_Revenue', 'Rooms', 'Nights', 'Lead_Time']:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            
            df['Total_Revenue'] = np.where(df['Total_Revenue'] == 0, df['Room_Revenue'], df['Total_Revenue'])
            df['RN'] = df['Rooms'] * df['Nights'].replace(0, 1)
            
            df['Is_Zero_Rate'] = df['Room_Revenue'] <= 0
            df['ADR'] = df.apply(lambda x: x['Room_Revenue'] / x['RN'] if x['RN'] > 0 else 0, axis=1)

        # 공통 필드 추가 (저장 시점 기준이 아닌 파일 자체의 스냅샷 날짜가 중요하지만, 여기선 오늘 날짜로 태깅)
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
        cols = ['Guest_Name', 'CheckIn', 'RN', 'Room_Revenue', 'Total_Revenue', 'ADR', 'Segment', 'Account', 'Room_Type', 'Snapshot_Date', 'Status', 'Stay_Month', 'Booking_Month', 'Stay_YearWeek', 'Lead_Time', 'Day_Type', 'Day_of_Week', 'Nat_Group', 'Month_Label', 'Is_Zero_Rate']
        
        final_df = pd.DataFrame()
        for c in cols:
            final_df[c] = df[c] if c in df.columns else ''
        return final_df

    except Exception as e:
        return pd.DataFrame()

# ------------------------------------------------------------------------------
# 3. 공통 분석 모듈
# ------------------------------------------------------------------------------
def render_rich_analysis(target_df, title_prefix, color_scale="Blues"):
    if target_df.empty:
        st.warning(f"⚠️ {title_prefix} 데이터가 없습니다.")
        return

    t1, t2, t3, t4, t5, t6 = st.tabs([
        "📊 세그먼트 분석", "📅 예약패턴(Pacing)", "🏢 거래처", 
        "⏳ 리드타임", "🛏️ 객실타입", "🗓️ 요일별"
    ])
    
    with t1:
        st.subheader(f"📊 {title_prefix} 세그먼트 상세")
        seg_stats = target_df.groupby('Segment').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
        seg_stats['ADR'] = (seg_stats['Room_Revenue'] / seg_stats['RN']).fillna(0)
        
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.pie(seg_stats, values='Room_Revenue', names='Segment', title="매출 비중"), use_container_width=True, key=f"{title_prefix}_seg_pie")
        c2.plotly_chart(px.bar(seg_stats, x='Segment', y='ADR', title="세그먼트별 ADR", text_auto=',.0f', color='Segment'), use_container_width=True, key=f"{title_prefix}_seg_bar")
        
        st.divider()
        seg_monthly = target_df.groupby(['Segment', 'Stay_Month']).agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
        seg_monthly['ADR'] = (seg_monthly['Room_Revenue'] / seg_monthly['RN']).fillna(0)
        seg_monthly = seg_monthly.sort_values(['Stay_Month', 'Segment'])
        st.dataframe(seg_monthly, hide_index=True, use_container_width=True)

    with t2:
        st.subheader(f"📅 {title_prefix} Pacing (예약월 vs 입실월)")
        pivot_metric = st.radio("분석 기준", ["객실수 (RN)", "객실매출", "객실단가 (ADR)"], horizontal=True, key=f"{title_prefix}_pacing_radio")
        
        if "ADR" in pivot_metric:
            rev_piv = target_df.pivot_table(index='Booking_Month', columns='Stay_Month', values='Room_Revenue', aggfunc='sum', fill_value=0)
            rn_piv = target_df.pivot_table(index='Booking_Month', columns='Stay_Month', values='RN', aggfunc='sum', fill_value=0)
            pacing = rev_piv.div(rn_piv).fillna(0)
            fmt = ".0f"
        elif "RN" in pivot_metric:
            pacing = target_df.pivot_table(index='Booking_Month', columns='Stay_Month', values='RN', aggfunc='sum', fill_value=0)
            fmt = "d"
        else:
            pacing = target_df.pivot_table(index='Booking_Month', columns='Stay_Month', values='Room_Revenue', aggfunc='sum', fill_value=0)
            fmt = ".2s"

        fig = px.imshow(pacing, text_auto=fmt, aspect="auto", color_continuous_scale=color_scale)
        st.plotly_chart(fig, use_container_width=True, key=f"{title_prefix}_pacing")

    with t3:
        st.subheader(f"🏢 {title_prefix} 거래처 분석")
        acc_stats = target_df.groupby('Account').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
        acc_stats['ADR'] = (acc_stats['Room_Revenue'] / acc_stats['RN']).fillna(0)
        fig_acc = px.scatter(acc_stats, x="RN", y="ADR", size="Room_Revenue", color="Account", hover_name="Account", size_max=60)
        st.plotly_chart(fig_acc, use_container_width=True, key=f"{title_prefix}_acc")
        st.dataframe(acc_stats.sort_values('RN', ascending=False), hide_index=True, use_container_width=True)

    with t4:
        st.subheader(f"⏳ {title_prefix} 리드타임 분석")
        bins = [-1, 0, 3, 7, 14, 30, 60, 90, 999]
        labels = ['당일', '1-3일', '4-7일', '8-14일', '15-30일', '31-60일', '61-90일', '90일+']
        temp_df = target_df.copy()
        temp_df['Lead_Group'] = pd.cut(temp_df['Lead_Time'], bins=bins, labels=labels)
        lead_stats = temp_df.groupby('Lead_Group').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
        lead_stats['ADR'] = (lead_stats['Room_Revenue'] / lead_stats['RN']).fillna(0)
        
        fig_lead = go.Figure()
        fig_lead.add_trace(go.Bar(x=lead_stats['Lead_Group'], y=lead_stats['RN'], name='RN', marker_color='red' if "취소" in title_prefix else 'blue'))
        fig_lead.add_trace(go.Scatter(x=lead_stats['Lead_Group'], y=lead_stats['ADR'], name='ADR', yaxis='y2', line=dict(color='black', width=2)))
        st.plotly_chart(fig_lead, use_container_width=True, key=f"{title_prefix}_lead")

    with t5:
        st.subheader(f"🛏️ {title_prefix} 객실타입 분석")
        rt_stats = target_df.groupby('Room_Type').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
        rt_stats['ADR'] = (rt_stats['Room_Revenue'] / rt_stats['RN']).fillna(0)
        st.dataframe(rt_stats.sort_values('RN', ascending=False), hide_index=True, use_container_width=True)

    with t6:
        st.subheader(f"🗓️ {title_prefix} 요일별 분석")
        wd_stats = target_df.groupby('Day_Type').agg({'RN':'sum', 'Room_Revenue':'sum'}).reset_index()
        wd_stats['ADR'] = (wd_stats['Room_Revenue'] / wd_stats['RN']).fillna(0)
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.bar(wd_stats, x='Day_Type', y='ADR', title="요일별 ADR", text_auto=',.0f'), use_container_width=True, key=f"{title_prefix}_wd_bar")
        c2.plotly_chart(px.pie(wd_stats, values='RN', names='Day_Type', title="요일별 비중"), use_container_width=True, key=f"{title_prefix}_wd_pie")

# ------------------------------------------------------------------------------
# UI 메인
# ------------------------------------------------------------------------------
try:
    st.title("🏛️ 앰버 호텔 경영 리포트 (History & Analytics)")

    # 1. 데이터 로드 (항상 로드 시도)
    raw_data = load_data_from_firestore()
    
    # 2. 날짜 필터링을 위한 데이터프레임 준비
    df_all = pd.DataFrame()
    available_dates = []
    
    if raw_data:
        df_all = pd.DataFrame(raw_data)
        if 'Snapshot_Date' in df_all.columns:
            # 날짜 정렬 (최신순)
            available_dates = sorted(df_all['Snapshot_Date'].unique(), reverse=True)

    # =========================================================================
    # [사이드바] 설정 및 업로드 (항상 보임)
    # =========================================================================
    with st.sidebar:
        st.header("📅 조회 설정")
        
        selected_date = None
        if available_dates:
            selected_date = st.selectbox(
                "조회할 데이터 기준일 (Snapshot)", 
                available_dates, 
                index=0
            )
            st.success(f"선택됨: {selected_date}")
        else:
            st.warning("저장된 데이터가 없습니다.")
            st.info("아래에서 파일을 업로드해주세요.")

        st.markdown("---")
        st.header("📤 데이터 추가 (Append)")
        st.caption("파일을 올리면 오늘 날짜로 DB에 저장됩니다.")
        
        with st.expander("📝 상세 리스트 (Booked/Cancel)", expanded=False):
            f1 = st.file_uploader("신규 예약 리스트", type=['xlsx','csv'], key="f1")
            if f1 and st.button("신규 예약 저장"):
                df = process_data(f1, "Booked")
                if not df.empty and save_to_firestore(df):
                    st.cache_data.clear()
                    st.success("저장 완료!")
                    time.sleep(1)
                    st.rerun()
            
            f2 = st.file_uploader("취소 리스트", type=['xlsx','csv'], key="f2")
            if f2 and st.button("취소 저장"):
                df = process_data(f2, "Cancelled")
                if not df.empty and save_to_firestore(df):
                    st.cache_data.clear()
                    st.success("저장 완료!")
                    time.sleep(1)
                    st.rerun()

        with st.expander("🎯 세일즈 온더북 (OTB)", expanded=False):
            # 다중 파일 업로드 지원
            f3_list = st.file_uploader("당월 OTB (여러개 가능)", type=['xlsx','csv'], key="f3", accept_multiple_files=True)
            if f3_list and st.button("당월 OTB 저장"):
                for f in f3_list:
                    df = process_data(f, "Booked", "Month")
                    if not df.empty: save_to_firestore(df)
                st.cache_data.clear()
                st.success("저장 완료!")
                time.sleep(1)
                st.rerun()
            
            f4_list = st.file_uploader("전체 OTB (여러개 가능)", type=['xlsx','csv'], key="f4", accept_multiple_files=True)
            if f4_list and st.button("전체 OTB 저장"):
                for f in f4_list:
                    df = process_data(f, "Booked", "Total")
                    if not df.empty: save_to_firestore(df)
                st.cache_data.clear()
                st.success("저장 완료!")
                time.sleep(1)
                st.rerun()

    # =========================================================================
    # [메인] 대시보드 출력
    # =========================================================================
    
    if selected_date and not df_all.empty:
        # 선택된 날짜의 데이터만 필터링
        df_filtered = df_all[df_all['Snapshot_Date'] == selected_date].copy()
        
        if df_filtered.empty:
            st.warning("선택한 날짜에 해당하는 데이터가 없습니다.")
        else:
            # 데이터 전처리 (문자열 -> 숫자 변환 등)
            df = df_filtered.copy()
            for col in ['RN', 'Room_Revenue', 'Total_Revenue', 'ADR', 'Lead_Time']:
                if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            
            if 'Booking_Date' not in df.columns: df['Booking_Date'] = df['CheckIn']
            df['Booking_dt'] = pd.to_datetime(df['Booking_Date'], errors='coerce')
            df['CheckIn_dt'] = pd.to_datetime(df['CheckIn'], errors='coerce')
            df.loc[df['Booking_dt'].isna(), 'Booking_dt'] = df.loc[df['Booking_dt'].isna(), 'CheckIn_dt']
            
            df['Is_Zero_Rate'] = df['Total_Revenue'] <= 0
            df['Booking_Month'] = df['Booking_dt'].dt.strftime('%Y-%m')
            df['Stay_Month'] = df['CheckIn_dt'].dt.strftime('%Y-%m')
            
            # 데이터 분리
            df_otb_m = df[df['Segment'] == 'OTB_Month']
            df_otb_t = df[df['Segment'] == 'OTB_Total']
            
            df_list = df[~df['Segment'].str.contains('OTB')]
            df_paid_bk = df_list[(df_list['Status'] == 'Booked') & (df_list['Is_Zero_Rate'] == False)]
            df_zero_bk = df_list[(df_list['Status'] == 'Booked') & (df_list['Is_Zero_Rate'] == True)]
            df_list_cn = df_list[df_list['Status'] == 'Cancelled']
            df_total_paid = pd.concat([df_paid_bk, df_list_cn])

            curr_month = datetime.now().strftime('%Y-%m')

            # 탭 구성
            main_tab0, main_tab1, main_tab2, main_tab3, main_tab4 = st.tabs([
                "👑 총지배인(GM) 요약", "✅ 예약 상세", "❌ 취소 상세", "📈 종합 합계", "🆓 0원 예약"
            ])

            with main_tab0:
                st.header(f"👑 Executive Summary ({selected_date})")
                
                st.subheader("🚀 최근 예약 유입 속도 (Booking Velocity)")
                if not df_paid_bk.empty:
                    recent_bk = df_paid_bk.groupby('Booking_Month').agg({'RN':'sum', 'Room_Revenue':'sum'}).reset_index()
                    recent_bk = recent_bk.sort_values('Booking_Month').tail(12)
                    c1, c2 = st.columns(2)
                    c1.plotly_chart(px.line(recent_bk, x='Booking_Month', y='RN', title="월별 예약 생성량 (RN)", markers=True), use_container_width=True)
                    c2.plotly_chart(px.bar(recent_bk, x='Booking_Month', y='Room_Revenue', title="월별 예약 생성액 (매출)", text_auto='.2s'), use_container_width=True)
                else:
                    st.info("예약 데이터가 없습니다.")

                st.divider()
                
                st.subheader("🏆 Top 5 효자 거래처")
                if not df_paid_bk.empty:
                    top_acc = df_paid_bk.groupby('Account').agg({'Room_Revenue':'sum', 'RN':'sum'}).reset_index()
                    top_acc['ADR'] = top_acc['Room_Revenue'] / top_acc['RN']
                    top_acc = top_acc.sort_values('Room_Revenue', ascending=False).head(5)
                    st.dataframe(top_acc, column_config={"Room_Revenue": st.column_config.NumberColumn("매출", format="%d원"), "ADR": st.column_config.NumberColumn(format="%d원")}, use_container_width=True, hide_index=True)

            with main_tab1:
                render_rich_analysis(df_paid_bk, "유료 예약", "Blues")
            
            with main_tab2:
                render_rich_analysis(df_list_cn, "취소 데이터", "Reds")
                
            with main_tab3:
                render_rich_analysis(df_total_paid, "종합(예약+취소)", "Greens")
                
            with main_tab4:
                st.write(f"총 {len(df_zero_bk)}건")
                st.dataframe(df_zero_bk[['Guest_Name', 'CheckIn', 'Account', 'Room_Type']], use_container_width=True)
    else:
        # 데이터가 없을 때 메인 화면 안내
        st.info("👈 왼쪽 사이드바에서 파일을 업로드하여 데이터를 추가해주세요.")
        st.markdown("""
        ### 📋 사용 방법
        1. **데이터 업로드**: 사이드바의 '데이터 추가' 섹션에서 엑셀 파일을 업로드하고 저장하세요.
        2. **자동 저장**: 파일은 업로드한 날짜(오늘) 기준으로 자동 저장됩니다.
        3. **날짜 선택**: 데이터가 쌓이면 사이드바 상단의 '조회할 데이터 기준일'에서 과거 데이터를 선택해 조회할 수 있습니다.
        """)

except Exception as e:
    st.error(f"🚨 시스템 오류: {e}")
