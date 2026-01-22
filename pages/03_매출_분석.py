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
# 0. 스타일 & 유틸리티
# ==============================================================================
st.set_page_config(page_title="ARI Final Integrity", layout="wide")
st.markdown("""
<style>
    /* 메트릭(숫자) 스타일 크게 */
    div[data-testid="stMetricValue"] { 
        font-size: 26px !important; 
        font-weight: 800; 
        color: #0f172a; 
    }
    div[data-testid="stMetricLabel"] { 
        font-size: 15px !important; 
        font-weight: 600; 
        color: #64748b; 
    }
    /* 합계 행 노란색 강조 */
    tr:last-child {
        font-weight: bold;
        background-color: #fff9c4 !important;
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

def save_to_firestore(df):
    """데이터프레임을 파이어베이스에 저장 (문자열 변환 후 저장)"""
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
    """파이어베이스 데이터 로드"""
    try:
        docs = db.collection(COLLECTION_NAME).stream()
        all_data = []
        for doc in docs:
            doc_dict = doc.to_dict()
            if 'data' in doc_dict:
                rows = doc_dict['data']
                doc_date = doc_dict.get('snapshot_date', '')
                for row in rows:
                    if 'Snapshot_Date' not in row or not row['Snapshot_Date']:
                        row['Snapshot_Date'] = doc_date
                    all_data.append(row)
        return all_data
    except Exception as e:
        st.error(f"❌ 로드 오류: {e}")
        return []

# ==============================================================================
# 2. 데이터 처리 엔진
# ==============================================================================
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

# ==============================================================================
# 3. 헬퍼 함수: 합계 행 추가 & 포맷팅
# ==============================================================================
def add_total_row(df, group_col_name="구분"):
    """합계 행 추가 함수 (ADR 재계산 포함)"""
    if df.empty: return df
    
    # 1. 숫자형 컬럼 합계 계산
    numeric_df = df.select_dtypes(include=[np.number])
    totals = numeric_df.sum().to_dict()
    
    # 2. 합계 행 생성
    total_row = {col: "" for col in df.columns}
    total_row.update(totals)
    
    # 3. 그룹 컬럼 이름 설정
    if group_col_name in df.columns:
        total_row[group_col_name] = "TOTAL"
    else:
        total_row[df.columns[0]] = "TOTAL"
        
    # 4. ADR 재계산 (매출 / RN)
    if 'Room_Revenue' in total_row and 'RN' in total_row:
        total_row['ADR'] = total_row['Room_Revenue'] / total_row['RN'] if total_row['RN'] > 0 else 0
        
    # 5. 합치기
    df_total = pd.DataFrame([total_row])
    return pd.concat([df, df_total], ignore_index=True)

def get_fmt_config():
    """천단위 콤마, 소수점 제거 설정"""
    return {
        "RN": st.column_config.NumberColumn("객실수(RN)", format="%d"),
        "Room_Revenue": st.column_config.NumberColumn("객실매출", format="%d"),
        "Total_Revenue": st.column_config.NumberColumn("총매출", format="%d"),
        "ADR": st.column_config.NumberColumn("객실단가(ADR)", format="%d"),
        "Lead_Time": st.column_config.NumberColumn("리드타임", format="%d")
    }

def render_analysis_tab(target_df, title_prefix, color_scale="Blues"):
    if target_df.empty:
        st.warning(f"⚠️ {title_prefix} 데이터가 없습니다.")
        return

    # 공통 포맷 가져오기
    fmt_config = get_fmt_config()

    t1, t2, t3, t4, t5, t6, t7 = st.tabs([
        "📊 세그먼트", "📅 예약패턴", "🏢 거래처", 
        "⏳ 리드타임", "🛏️ 객실타입", "🗓️ 요일별", "🌐 국적별"
    ])
    
    with t1:
        st.subheader(f"📊 {title_prefix} 세그먼트 분석")
        seg_stats = target_df.groupby('Segment').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
        seg_final = add_total_row(seg_stats, 'Segment')
        
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.pie(seg_stats, values='Room_Revenue', names='Segment'), use_container_width=True)
        c2.plotly_chart(px.bar(seg_stats, x='Segment', y='Room_Revenue', text_auto='.2s'), use_container_width=True)
        st.dataframe(seg_final, hide_index=True, use_container_width=True, column_config=fmt_config)

    with t2:
        st.subheader(f"📅 Pacing")
        pivot_metric = st.radio(f"{title_prefix} 기준", ["RN", "Revenue", "ADR"], horizontal=True, key=f"{title_prefix}_rad")
        
        if pivot_metric == "ADR":
            pacing = target_df.pivot_table(index='Booking_Month', columns='Stay_Month', values='Room_Revenue', aggfunc='sum') / \
                     target_df.pivot_table(index='Booking_Month', columns='Stay_Month', values='RN', aggfunc='sum')
            fmt = ".0f"
        elif pivot_metric == "RN":
            pacing = target_df.pivot_table(index='Booking_Month', columns='Stay_Month', values='RN', aggfunc='sum')
            fmt = "d"
        else:
            pacing = target_df.pivot_table(index='Booking_Month', columns='Stay_Month', values='Room_Revenue', aggfunc='sum')
            fmt = ".0f"
            
        pacing = pacing.fillna(0)
        st.plotly_chart(px.imshow(pacing, text_auto=fmt, aspect="auto", color_continuous_scale=color_scale), use_container_width=True)

    with t3:
        st.subheader("🏢 거래처 분석")
        acc_stats = target_df.groupby('Account').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
        acc_stats = acc_stats.sort_values('RN', ascending=False).head(100) # 상위 100개
        acc_final = add_total_row(acc_stats, 'Account')
        
        st.dataframe(acc_final, hide_index=True, use_container_width=True, column_config=fmt_config)

    with t4:
        st.subheader("⏳ 리드타임")
        bins = [-1, 0, 3, 7, 14, 30, 60, 90, 999]
        labels = ['0일', '1-3일', '4-7일', '8-14일', '15-30일', '31-60일', '61-90일', '90일+']
        temp_df = target_df.copy()
        temp_df['Lead_Group'] = pd.cut(temp_df['Lead_Time'], bins=bins, labels=labels)
        lead_stats = temp_df.groupby('Lead_Group').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
        lead_final = add_total_row(lead_stats, 'Lead_Group')
        
        st.dataframe(lead_final, hide_index=True, use_container_width=True, column_config=fmt_config)

    with t5:
        st.subheader("🛏️ 객실타입")
        rt_stats = target_df.groupby('Room_Type').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
        rt_final = add_total_row(rt_stats, 'Room_Type')
        st.dataframe(rt_final, hide_index=True, use_container_width=True, column_config=fmt_config)

    with t6:
        st.subheader("🗓️ 요일별")
        wd_stats = target_df.groupby('Day_Type').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
        wd_final = add_total_row(wd_stats, 'Day_Type')
        st.dataframe(wd_final, hide_index=True, use_container_width=True, column_config=fmt_config)

    with t7:
        st.subheader("🌐 국적별")
        if 'Nat_Group' in target_df.columns:
            nat_stats = target_df.groupby('Nat_Group').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
            nat_final = add_total_row(nat_stats, 'Nat_Group')
            st.dataframe(nat_final, hide_index=True, use_container_width=True, column_config=fmt_config)
        else:
            st.info("국적 데이터 없음")

# ==============================================================================
# UI 메인
# ==============================================================================
try:
    st.title("🏛️ 앰버 호텔 경영 리포트 (Final Integrity)")

    raw_data = load_data_from_firestore()
    df_all = pd.DataFrame()
    available_dates = []
    
    if raw_data:
        df_all = pd.DataFrame(raw_data)
        if 'Snapshot_Date' in df_all.columns:
            available_dates = sorted(df_all['Snapshot_Date'].unique(), reverse=True)

    with st.sidebar:
        st.header("📅 조회 설정")
        selected_date = None
        if available_dates:
            selected_date = st.selectbox("조회 기준일", available_dates, index=0)
        
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
            f3_list = st.file_uploader("당월 OTB", type=['xlsx','csv'], key="f3", accept_multiple_files=True)
            if f3_list and st.button("당월 OTB 저장"):
                for f in f3_list:
                    df = process_data(f, "Booked", "Month")
                    if not df.empty: save_to_firestore(df)
                st.cache_data.clear()
                st.rerun()
            
            f4_list = st.file_uploader("전체 OTB", type=['xlsx','csv'], key="f4", accept_multiple_files=True)
            if f4_list and st.button("전체 OTB 저장"):
                for f in f4_list:
                    df = process_data(f, "Booked", "Total")
                    if not df.empty: save_to_firestore(df)
                st.cache_data.clear()
                st.rerun()

    if selected_date and not df_all.empty:
        df_filtered = df_all[df_all['Snapshot_Date'] == selected_date].copy()
        
        if df_filtered.empty:
            st.warning("데이터가 없습니다.")
        else:
            # -------------------------------------------------------------
            # [핵심 수정] 숫자 컬럼 강제 형변환 (포맷팅 필수 조건)
            # -------------------------------------------------------------
            df = df_filtered.copy()
            numeric_cols = ['RN', 'Room_Revenue', 'Total_Revenue', 'ADR', 'Lead_Time']
            for col in numeric_cols:
                if col in df.columns:
                    # 문자열 등 섞여있을 수 있으므로 강제 변환
                    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

            if 'Booking_Date' not in df.columns: df['Booking_Date'] = df['CheckIn']
            df['Booking_dt'] = pd.to_datetime(df['Booking_Date'], errors='coerce')
            df['CheckIn_dt'] = pd.to_datetime(df['CheckIn'], errors='coerce')
            df = df.dropna(subset=['CheckIn_dt'])
            
            df['Is_Zero_Rate'] = df['Total_Revenue'] <= 0
            df['Booking_Month'] = df['Booking_dt'].dt.strftime('%Y-%m')
            df['Stay_Month'] = df['CheckIn_dt'].dt.strftime('%Y-%m')
            
            df_otb_m = df[df['Segment'] == 'OTB_Month']
            df_otb_t = df[df['Segment'] == 'OTB_Total']
            
            df_list = df[~df['Segment'].str.contains('OTB')]
            df_paid_bk = df_list[(df_list['Status'] == 'Booked') & (df_list['Is_Zero_Rate'] == False)]
            df_zero_bk = df_list[(df_list['Status'] == 'Booked') & (df_list['Is_Zero_Rate'] == True)]
            df_list_cn = df_list[df_list['Status'] == 'Cancelled']
            df_total_paid = pd.concat([df_paid_bk, df_list_cn])

            # 탭 구성
            main_tab0, main_tab1, main_tab2, main_tab3, main_tab4, main_tab5 = st.tabs([
                "👑 총지배인(GM) 요약", "✅ 예약 상세", "❌ 취소 상세", "📈 종합 합계", "🆓 0원 예약", "🎯 OTB 현황"
            ])

            # 공통 포맷 설정 (천단위 콤마, 소수점 X)
            fmt_cfg = get_fmt_config()

            # ------------------------------------------------------------------
            # 1. GM 요약 탭 (요청사항 완벽 반영)
            # ------------------------------------------------------------------
            with main_tab0:
                st.header(f"👑 총지배인(GM) 요약 ({selected_date} 기준)")
                
                # A. 예약 vs 취소 KPI
                st.subheader("1. 금일 예약 vs 취소 현황")
                
                bk_cnt = len(df_paid_bk)
                bk_rn = df_paid_bk['RN'].sum()
                bk_rev = df_paid_bk['Room_Revenue'].sum()
                bk_adr = bk_rev / bk_rn if bk_rn > 0 else 0
                
                cn_cnt = len(df_list_cn)
                cn_rn = df_list_cn['RN'].sum()
                cn_rev = df_list_cn['Room_Revenue'].sum()
                cn_adr = cn_rev / cn_rn if cn_rn > 0 else 0
                
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("✅ 신규 예약", f"{bk_cnt:,.0f} 건")
                c2.metric("✅ 예약 RN", f"{bk_rn:,.0f} 박")
                c3.metric("✅ 예약 매출", f"{bk_rev:,.0f} 원")
                c4.metric("✅ 예약 ADR", f"{bk_adr:,.0f} 원")
                
                c5, c6, c7, c8 = st.columns(4)
                c5.metric("❌ 취소 건수", f"{cn_cnt:,.0f} 건")
                c6.metric("❌ 취소 RN", f"{cn_rn:,.0f} 박")
                c7.metric("❌ 취소 매출", f"{cn_rev:,.0f} 원")
                c8.metric("❌ 취소 ADR", f"{cn_adr:,.0f} 원")
                
                st.divider()
                
                # B. 세그먼트별 픽업 (합계 행 추가)
                st.subheader("2. 세그먼트별 픽업 현황 (예약)")
                if not df_paid_bk.empty:
                    seg_gm = df_paid_bk.groupby('Segment').agg({'RN':'sum', 'Room_Revenue':'sum'}).reset_index()
                    seg_gm_final = add_total_row(seg_gm, 'Segment')
                    st.dataframe(seg_gm_final, hide_index=True, use_container_width=True, column_config=fmt_cfg)
                else:
                    st.info("예약 데이터 없음")
                
                st.divider()

                # C. 국적별 / 월별 비중
                c_left, c_right = st.columns(2)
                with c_left:
                    st.subheader("3. 국적별 비중")
                    if 'Nat_Group' in df_paid_bk.columns and not df_paid_bk.empty:
                        nat_gm = df_paid_bk.groupby('Nat_Group')['RN'].sum().reset_index()
                        fig_nat = px.pie(nat_gm, values='RN', names='Nat_Group', hole=0.4)
                        st.plotly_chart(fig_nat, use_container_width=True)
                    else:
                        st.info("데이터 없음")
                
                with c_right:
                    st.subheader("4. 월별 예약/취소 집중도")
                    # 예약 월별
                    bk_m = df_paid_bk.groupby('Stay_Month')['RN'].sum().reset_index()
                    bk_m['Type'] = '예약'
                    # 취소 월별
                    cn_m = df_list_cn.groupby('Stay_Month')['RN'].sum().reset_index()
                    cn_m['Type'] = '취소'
                    
                    comb_m = pd.concat([bk_m, cn_m])
                    if not comb_m.empty:
                        fig_m = px.bar(comb_m, x='Stay_Month', y='RN', color='Type', barmode='group', text_auto='.0f')
                        st.plotly_chart(fig_m, use_container_width=True)
                    else:
                        st.info("데이터 없음")

            # ------------------------------------------------------------------
            # 나머지 탭 (합계 행 및 포맷팅 모두 적용)
            # ------------------------------------------------------------------
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
                df_otb_all = pd.concat([df_otb_m, df_otb_t])
                
                if df_otb_all.empty:
                    st.warning("OTB 데이터 없음")
                else:
                    otb_monthly = df_otb_all.groupby('CheckIn').agg({'Room_Revenue': 'sum', 'RN': 'sum'}).reset_index()
                    otb_monthly.rename(columns={'CheckIn': 'Stay_Month', 'Room_Revenue': 'OTB_Rev', 'RN': 'OTB_RN'}, inplace=True)
                    otb_monthly['Stay_Month'] = pd.to_datetime(otb_monthly['Stay_Month']).dt.strftime('%Y-%m')
                    otb_agg = otb_monthly.groupby('Stay_Month')[['OTB_Rev', 'OTB_RN']].sum().reset_index()
                    
                    if not df_paid_bk.empty:
                        act_monthly = df_paid_bk.groupby('Stay_Month').agg({'Room_Revenue': 'sum', 'RN': 'sum'}).reset_index()
                        act_monthly.rename(columns={'Room_Revenue': 'Actual_Rev', 'RN': 'Actual_RN'}, inplace=True)
                        merged = pd.merge(otb_agg, act_monthly, on='Stay_Month', how='outer').fillna(0)
                    else:
                        merged = otb_agg
                        merged['Actual_Rev'] = 0; merged['Actual_RN'] = 0
                    
                    merged = merged.sort_values('Stay_Month')
                    
                    # OTB 합계 행 추가
                    merged_final = add_total_row(merged, 'Stay_Month')

                    st.subheader("📊 OTB vs Actual 매출 비교")
                    fig_otb = go.Figure()
                    fig_otb.add_trace(go.Bar(x=merged['Stay_Month'], y=merged['Actual_Rev'], name='Actual', marker_color='#2E86C1'))
                    fig_otb.add_trace(go.Scatter(x=merged['Stay_Month'], y=merged['OTB_Rev'], name='OTB Goal', line=dict(color='#E74C3C', width=3, dash='dot')))
                    st.plotly_chart(fig_otb, use_container_width=True)
                    
                    st.dataframe(merged_final, hide_index=True, use_container_width=True,
                                 column_config={
                                     "OTB_Rev": st.column_config.NumberColumn("OTB 매출", format="%d"),
                                     "Actual_Rev": st.column_config.NumberColumn("실제 매출", format="%d"),
                                     "OTB_RN": st.column_config.NumberColumn("OTB RN", format="%d"),
                                     "Actual_RN": st.column_config.NumberColumn("실제 RN", format="%d")
                                 })

    else:
        st.info("👈 파일 업로드가 필요합니다.")

except Exception as e:
    st.error(f"🚨 시스템 오류: {e}")
