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
</style>
""", unsafe_allow_html=True)

# ------------------------------------------------------------------------------
# 1. 파이어베이스 연결 & 데이터 로딩 함수 (구글 시트 대체)
# ------------------------------------------------------------------------------
# 파이어베이스 초기화
if not firebase_admin._apps:
    cred = credentials.Certificate(dict(st.secrets["firebase"]))
    firebase_admin.initialize_app(cred)
db = firestore.client()

COLLECTION_NAME = "revenue_integrity_data"  # 데이터가 저장될 컬렉션 이름

def load_data_from_firestore():
    """파이어베이스에 저장된 모든 업로드 데이터를 가져와 하나로 합칩니다."""
    try:
        docs = db.collection(COLLECTION_NAME).stream()
        all_data = []
        
        for doc in docs:
            doc_dict = doc.to_dict()
            if 'data' in doc_dict:
                # 저장할 때 'data' 필드에 리스트 형태로 저장했다고 가정
                all_data.extend(doc_dict['data'])
        
        if not all_data:
            return pd.DataFrame()
            
        return pd.DataFrame(all_data)
        
    except Exception as e:
        st.error(f"❌ 데이터 로딩 오류: {e}")
        return pd.DataFrame()

def save_to_firestore(df, file_name, upload_type):
    """업로드된 데이터를 파이어베이스에 저장합니다."""
    try:
        # 데이터프레임을 딕셔너리 리스트로 변환
        data_records = df.fillna('').to_dict(orient='records')
        
        # 문서 ID 생성 (날짜_파일명)
        doc_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{upload_type}"
        
        # 파이어베이스에 저장
        db.collection(COLLECTION_NAME).document(doc_id).set({
            "data": data_records,
            "file_name": file_name,
            "upload_type": upload_type,
            "uploaded_at": datetime.now()
        })
        return True
    except Exception as e:
        st.error(f"❌ 저장 오류: {e}")
        return False

def clear_firestore_collection():
    """컬렉션의 모든 데이터를 삭제합니다 (초기화)"""
    docs = db.collection(COLLECTION_NAME).stream()
    for doc in docs:
        doc.reference.delete()

# ------------------------------------------------------------------------------
# 2. 데이터 처리 엔진 (기존 로직 유지)
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
        # 파일명 기반 OTB 판단 (파일명에 'OTB' 또는 '영업'이 있으면)
        is_otb = "OTB" in uploaded_file.name or "영업" in uploaded_file.name
        
        if uploaded_file.name.endswith('.csv'):
            df_raw = pd.read_csv(uploaded_file, header=None)
        else:
            df_raw = pd.read_excel(uploaded_file, header=None)

        if is_otb:
            # [OTB]
            df_raw = find_valid_header_row(df_raw)
            # 날짜 컬럼 찾기
            date_col = next((c for c in df_raw.columns if '일자' in str(c) or 'Date' in str(c)), None)
            
            if date_col:
                df_raw = df_raw[~df_raw[date_col].astype(str).str.contains('소계|Subtotal|합계|Total', na=False)]
            elif df_raw.shape[1] > 0:
                df_raw = df_raw[~df_raw.iloc[:, 0].astype(str).str.contains('소계|Subtotal|합계|Total', na=False)]

            df = pd.DataFrame()
            df['Guest_Name'] = f'OTB_{sub_segment}_DATA'
            
            if date_col:
                df['CheckIn'] = pd.to_datetime(df_raw[date_col], errors='coerce')
            else:
                # 날짜 컬럼을 못 찾으면 첫번째 컬럼 사용
                df['CheckIn'] = pd.to_datetime(df_raw.iloc[:, 0], errors='coerce')
            
            # OTB 포맷 추정 (뒤에서부터 컬럼 추적)
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
            # [리스트]
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

        # 공통 처리
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
        
        # 저장할 컬럼만 추리기
        cols = ['Guest_Name', 'CheckIn', 'RN', 'Room_Revenue', 'Total_Revenue', 'ADR', 'Segment', 'Account', 'Room_Type', 'Snapshot_Date', 'Status', 'Stay_Month', 'Booking_Month', 'Stay_YearWeek', 'Lead_Time', 'Day_Type', 'Day_of_Week', 'Nat_Group', 'Month_Label', 'Is_Zero_Rate']
        
        final_df = pd.DataFrame()
        for c in cols:
            final_df[c] = df[c] if c in df.columns else ''
            
        # 데이터프레임 값들을 문자열/숫자로 확실하게 변환 (JSON 직렬화 위해)
        final_df = final_df.fillna(0)
        
        return final_df

    except Exception as e:
        st.error(f"처리 중 오류 발생: {e}")
        return pd.DataFrame()

# ------------------------------------------------------------------------------
# 3. 공통 분석 모듈 (기존 로직 유지)
# ------------------------------------------------------------------------------
def render_rich_analysis(target_df, title_prefix, color_scale="Blues"):
    if target_df.empty:
        st.warning(f"⚠️ {title_prefix} 데이터가 없습니다.")
        return

    # 탭 구성
    t1, t2, t3, t4, t5, t6 = st.tabs([
        "📊 세그먼트 분석", "📅 예약패턴(Pacing)", "🏢 거래처", 
        "⏳ 리드타임", "🛏️ 객실타입", "🗓️ 요일별"
    ])
    
    # 1. 세그먼트
    with t1:
        st.subheader(f"📊 {title_prefix} 세그먼트 상세")
        seg_stats = target_df.groupby('Segment').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
        seg_stats['ADR'] = (seg_stats['Room_Revenue'] / seg_stats['RN']).fillna(0)
        
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.pie(seg_stats, values='Room_Revenue', names='Segment', title="매출 비중"), use_container_width=True, key=f"{title_prefix}_seg_pie")
        c2.plotly_chart(px.bar(seg_stats, x='Segment', y='ADR', title="세그먼트별 ADR", text_auto=',.0f', color='Segment'), use_container_width=True, key=f"{title_prefix}_seg_bar")
        
        st.divider()
        st.markdown("##### 📅 세그먼트 x 월별 상세 실적")
        seg_monthly = target_df.groupby(['Segment', 'Stay_Month']).agg({
            'RN': 'sum', 
            'Room_Revenue': 'sum'
        }).reset_index()
        seg_monthly['ADR'] = (seg_monthly['Room_Revenue'] / seg_monthly['RN']).fillna(0)
        seg_monthly = seg_monthly.sort_values(['Stay_Month', 'Segment'])
        
        st.dataframe(seg_monthly, 
                     column_config={
                         "Stay_Month": st.column_config.TextColumn("월"),
                         "Segment": st.column_config.TextColumn("세그먼트"),
                         "Room_Revenue": st.column_config.NumberColumn("매출액", format="%d원"),
                         "ADR": st.column_config.NumberColumn("ADR", format="%d원"),
                         "RN": st.column_config.NumberColumn("RN", format="%d")
                     }, hide_index=True, use_container_width=True)

    # 2. Pacing
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

        fig = px.imshow(pacing, text_auto=fmt, aspect="auto", color_continuous_scale=color_scale, title=f"Booking Pattern ({pivot_metric})")
        st.plotly_chart(fig, use_container_width=True, key=f"{title_prefix}_pacing")

    # 3. 거래처
    with t3:
        st.subheader(f"🏢 {title_prefix} 거래처 분석")
        acc_stats = target_df.groupby('Account').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
        acc_stats['ADR'] = (acc_stats['Room_Revenue'] / acc_stats['RN']).fillna(0)
        
        fig_acc = px.scatter(acc_stats, x="RN", y="ADR", size="Room_Revenue", color="Account", hover_name="Account", size_max=60)
        st.plotly_chart(fig_acc, use_container_width=True, key=f"{title_prefix}_acc")
        st.dataframe(acc_stats.sort_values('RN', ascending=False), 
                     column_config={"Room_Revenue": st.column_config.NumberColumn(format="%d원"), "ADR": st.column_config.NumberColumn(format="%d원")}, 
                     hide_index=True, use_container_width=True)

    # 4. 리드타임
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
        fig_lead.update_layout(yaxis2=dict(overlaying='y', side='right', title='ADR'), title="리드타임별 물량 vs 단가")
        st.plotly_chart(fig_lead, use_container_width=True, key=f"{title_prefix}_lead")

    # 5. 객실타입
    with t5:
        st.subheader(f"🛏️ {title_prefix} 객실타입 분석")
        rt_stats = target_df.groupby('Room_Type').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
        rt_stats['ADR'] = (rt_stats['Room_Revenue'] / rt_stats['RN']).fillna(0)
        st.dataframe(rt_stats.sort_values('RN', ascending=False), 
                     column_config={"Room_Revenue": st.column_config.NumberColumn(format="%d원"), "ADR": st.column_config.NumberColumn(format="%d원")}, 
                     hide_index=True, use_container_width=True)

    # 6. 요일별
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
    st.title("🏛️ 앰버 호텔 경영 리포트 (Firebase Version)")

    # 초기화 및 관리 사이드바
    with st.sidebar.expander("🛠️ 데이터 관리", expanded=True):
        if st.button("🗑️ 전체 데이터 삭제 (초기화)"):
            clear_firestore_collection()
            st.cache_data.clear()
            st.success("데이터베이스 초기화 완료!")
            time.sleep(1)
            st.rerun()

    st.sidebar.header("📤 데이터 업로드 (to Firestore)")
    
    with st.sidebar.expander("📝 상세 리스트", expanded=False):
        f1 = st.file_uploader("신규 예약 리스트", type=['xlsx','csv'], key="f1")
        if f1 and st.button("신규 예약 저장"):
            df = process_data(f1, "Booked")
            if not df.empty:
                save_to_firestore(df, f1.name, "Booked")
                st.success("저장 완료!")
                time.sleep(1)
                st.rerun()
        
        f2 = st.file_uploader("취소 리스트", type=['xlsx','csv'], key="f2")
        if f2 and st.button("취소 저장"):
            df = process_data(f2, "Cancelled")
            if not df.empty:
                save_to_firestore(df, f2.name, "Cancelled")
                st.success("저장 완료!")
                time.sleep(1)
                st.rerun()

    with st.sidebar.expander("🎯 세일즈 온더북", expanded=True):
        f3 = st.file_uploader("당월 OTB", type=['xlsx','csv'], key="f3")
        if f3 and st.button("당월 OTB 저장"):
            df = process_data(f3, "Booked", "Month")
            if not df.empty:
                save_to_firestore(df, f3.name, "OTB_Month")
                st.success("저장 완료!")
                time.sleep(1)
                st.rerun()
        
        f4 = st.file_uploader("전체 OTB", type=['xlsx','csv'], key="f4")
        if f4 and st.button("전체 OTB 저장"):
            df = process_data(f4, "Booked", "Total")
            if not df.empty:
                save_to_firestore(df, f4.name, "OTB_Total")
                st.success("저장 완료!")
                time.sleep(1)
                st.rerun()

    # 데이터 로드 (Firebase에서)
    with st.spinner("데이터를 불러오는 중입니다..."):
        df = load_data_from_firestore()

    if df.empty:
        st.warning("⚠️ 저장된 데이터가 없습니다. 사이드바에서 파일을 업로드해주세요.")
    else:
        # 데이터가 있으면 기존 로직 수행
        
        # 수치 변환 (문자열로 저장되었을 수 있으므로 다시 변환)
        for col in ['RN', 'Room_Revenue', 'Total_Revenue', 'ADR', 'Lead_Time']:
            if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        
        df['Is_Zero_Rate'] = df['Total_Revenue'] <= 0
        
        # 데이터 분리
        df_otb_m = df[df['Segment'] == 'OTB_Month']
        df_otb_t = df[df['Segment'] == 'OTB_Total']
        
        df_list = df[~df['Segment'].str.contains('OTB')]
        df_paid_bk = df_list[(df_list['Status'] == 'Booked') & (df_list['Is_Zero_Rate'] == False)]
        df_zero_bk = df_list[(df_list['Status'] == 'Booked') & (df_list['Is_Zero_Rate'] == True)]
        df_list_cn = df_list[df_list['Status'] == 'Cancelled']
        df_total_paid = pd.concat([df_paid_bk, df_list_cn])

        # 탭 구성
        main_tab0, main_tab1, main_tab2, main_tab3, main_tab4 = st.tabs([
            "👑 총지배인(GM) 요약", "✅ 예약 상세", "❌ 취소 상세", "📈 종합 합계", "🆓 0원 예약"
        ])

        with main_tab0:
            st.header("👑 Executive Summary")
            
            # 1. 예약 유입 속도
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
            
            # 2. Top 5 거래처
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

except Exception as e:
    st.error(f"🚨 시스템 오류: {e}")
