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
# 0. 스타일 & 유틸리티 설정
# ==============================================================================
st.set_page_config(page_title="ARI Final Integrity", layout="wide")

st.markdown("""
<style>
    /* 1. 전체 메인 컨테이너 여백 조정 */
    .block-container {
        padding-top: 1rem;
        padding-bottom: 5rem;
        padding-left: 1rem;
        padding-right: 1rem;
    }
    
    /* 2. 메트릭(숫자) 스타일 - 크고 진하게 */
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
    
    /* 3. 탭 스타일 */
    button[data-baseweb="tab"] { 
        font-size: 16px !important; 
        font-weight: 700; 
    }
    
    /* 4. 데이터프레임 합계 행 강조 (마지막 행 노란색 배경) */
    [data-testid="stDataFrame"] table tr:last-child td {
        font-weight: 900 !important;
        background-color: #fff9c4 !important; /* 연한 노란색 */
        color: #000000 !important;
        border-top: 2px solid #000000 !important;
    }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 1. 파이어베이스 연결 & 데이터 저장/로드 함수
# ==============================================================================
if not firebase_admin._apps:
    try:
        # Streamlit Cloud의 Secrets에서 키를 가져옴
        cred = credentials.Certificate(dict(st.secrets["firebase"]))
        firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"🔥 파이어베이스 연결 실패: {e}")
        st.stop()

db = firestore.client()
COLLECTION_NAME = "revenue_integrity_history"

def save_to_firestore(df):
    """
    데이터프레임을 파이어베이스에 저장하는 함수
    - JSON 직렬화 오류를 막기 위해 문자열로 변환하여 저장
    - 업로드 날짜와 스냅샷 날짜를 기록
    """
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
    """
    파이어베이스에서 저장된 모든 데이터를 불러오는 함수
    - 캐시를 사용하지 않아(ttl=0) 항상 최신 데이터를 가져옴
    """
    try:
        docs = db.collection(COLLECTION_NAME).stream()
        all_data = []
        
        for doc in docs:
            doc_dict = doc.to_dict()
            if 'data' in doc_dict:
                # 문서 자체의 스냅샷 날짜
                doc_date = doc_dict.get('snapshot_date', '')
                rows = doc_dict['data']
                
                for row in rows:
                    # 개별 행에 날짜 정보가 없으면 문서 날짜로 채움
                    if 'Snapshot_Date' not in row or not row['Snapshot_Date']:
                        row['Snapshot_Date'] = doc_date
                    all_data.append(row)
        
        return all_data if all_data else []
    except Exception as e:
        st.error(f"❌ 데이터 로드 오류: {e}")
        return []

# ==============================================================================
# 2. 데이터 전처리 엔진 (컬럼 매핑 및 정제)
# ==============================================================================
def normalize_and_map_columns(df):
    """다양한 엑셀 컬럼명을 표준화된 영어 컬럼명으로 매핑"""
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
                    # 예외 처리: Room Revenue와 Total Revenue 구분
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
    """데이터가 시작되는 실제 헤더 행을 찾아 DataFrame을 재설정"""
    for i, row in df.iterrows():
        row_str = " ".join(row.astype(str).values).lower()
        # 헤더로 추정되는 키워드가 2개 이상 포함된 행을 찾음
        keywords = ['guest', 'name', 'check', 'date', 'room', '고객', '입실', '객실']
        if sum(1 for k in keywords if k in row_str) >= 2:
            df.columns = df.iloc[i]
            return df.iloc[i+1:].reset_index(drop=True)
    return df

def process_data(uploaded_file, status, sub_segment="General"):
    """업로드된 엑셀/CSV 파일을 읽어서 표준 포맷으로 변환"""
    try:
        # 파일명으로 OTB 파일 여부 확인
        is_otb = "Sales on the Book" in uploaded_file.name or "영업 현황" in uploaded_file.name
        
        if uploaded_file.name.endswith('.csv'):
            df_raw = pd.read_csv(uploaded_file, header=None)
        else:
            df_raw = pd.read_excel(uploaded_file, header=None)

        # -----------------------------------------------------------
        # Case A: OTB (세일즈 온더북) 파일 처리
        # -----------------------------------------------------------
        if is_otb:
            df_raw = find_valid_header_row(df_raw)
            # 합계 행 제거
            if '일자' in df_raw.columns: 
                df_raw = df_raw[~df_raw['일자'].astype(str).str.contains('소계|Subtotal|합계|Total', na=False)]
            elif df_raw.shape[1] > 0:
                df_raw = df_raw[~df_raw.iloc[:, 0].astype(str).str.contains('소계|Subtotal|합계|Total', na=False)]

            df = pd.DataFrame()
            df['Guest_Name'] = f'OTB_{sub_segment}_DATA'
            
            # 날짜 컬럼 찾기
            date_col = next((c for c in df_raw.columns if '일자' in str(c) or 'Date' in str(c)), df_raw.columns[0])
            df['CheckIn'] = pd.to_datetime(df_raw[date_col], errors='coerce')
            
            # OTB 파일의 특정 위치에 있는 값 추출 (보통 우측에 위치)
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
            
        # -----------------------------------------------------------
        # Case B: 일반 예약/취소 리스트 처리
        # -----------------------------------------------------------
        else:
            df_raw = find_valid_header_row(df_raw)
            # 합계 행 제거
            df_raw = df_raw[~df_raw.iloc[:, 0].astype(str).str.contains('합계|Total|소계|Subtotal', case=False, na=False)]
            
            df = normalize_and_map_columns(df_raw).copy()
            if 'Guest_Name' in df.columns:
                df = df[~df['Guest_Name'].astype(str).str.contains('합계|Total|소계|Subtotal', case=False, na=False)]
            
            # 필수 컬럼 확인
            if 'CheckIn' not in df.columns: return pd.DataFrame()
            if 'Booking_Date' not in df.columns: df['Booking_Date'] = df['CheckIn']
            
            # 없는 컬럼 기본값 채우기
            req_cols = ['Rooms', 'Nights', 'Room_Revenue', 'Total_Revenue', 'Guest_Name', 'Segment', 'Account', 'Room_Type', 'Nat_Orig', 'Lead_Time']
            for c in req_cols:
                if c not in df.columns: 
                    if c in ['Rooms', 'Nights', 'Room_Revenue', 'Total_Revenue', 'Lead_Time']: df[c] = 0 
                    else: df[c] = 'Unknown'

            # 숫자 형변환
            for col in ['Room_Revenue', 'Total_Revenue', 'Rooms', 'Nights', 'Lead_Time']:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            
            # 파생 변수 계산
            df['Total_Revenue'] = np.where(df['Total_Revenue'] == 0, df['Room_Revenue'], df['Total_Revenue'])
            df['RN'] = df['Rooms'] * df['Nights'].replace(0, 1)
            df['Is_Zero_Rate'] = df['Room_Revenue'] <= 0
            df['ADR'] = df.apply(lambda x: x['Room_Revenue'] / x['RN'] if x['RN'] > 0 else 0, axis=1)

        # -----------------------------------------------------------
        # 공통 전처리 (날짜, 국적, 요일 등)
        # -----------------------------------------------------------
        df['Snapshot_Date'] = datetime.now().strftime('%Y-%m-%d') 
        df['Status'] = status
        
        df['CheckIn_dt'] = pd.to_datetime(df['CheckIn'], errors='coerce')
        df['Booking_dt'] = pd.to_datetime(df['Booking_Date'], errors='coerce')
        # 예약일 없으면 체크인일로 대체
        df.loc[df['Booking_dt'].isna(), 'Booking_dt'] = df.loc[df['Booking_dt'].isna(), 'CheckIn_dt']
        
        df = df.dropna(subset=['CheckIn_dt'])

        df['Stay_Month'] = df['CheckIn_dt'].dt.strftime('%Y-%m')
        df['Booking_Month'] = df['Booking_dt'].dt.strftime('%Y-%m')
        df['Stay_YearWeek'] = df['CheckIn_dt'].dt.strftime('%Y-%U주')
        df['Day_of_Week'] = df['CheckIn_dt'].dt.day_name()
        
        df['Weekday_Num'] = df['CheckIn_dt'].dt.weekday
        df['Day_Type'] = df['Weekday_Num'].apply(lambda x: 'Weekend' if x >= 4 else 'Weekday')
        
        df['Lead_Time'] = df['Lead_Time'].fillna(0).astype(int)
        
        # 국적 그룹핑
        def classify_nat(row):
            name = str(row.get('Guest_Name', ''))
            orig = str(row.get('Nat_Orig', '')).upper()
            if re.search('[가-힣]', name): return 'KOR'
            if any(x in orig for x in ['CHN', 'HKG', 'TWN', 'MAC']): return 'CHN'
            return 'OTH'
        df['Nat_Group'] = df.apply(classify_nat, axis=1)

        # 월별 라벨링 (M, M+1...)
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
        
        # 최종 컬럼 정리
        cols = ['Guest_Name', 'CheckIn', 'RN', 'Room_Revenue', 'Total_Revenue', 'ADR', 'Segment', 'Account', 'Room_Type', 'Snapshot_Date', 'Status', 'Stay_Month', 'Booking_Month', 'Stay_YearWeek', 'Lead_Time', 'Day_Type', 'Day_of_Week', 'Nat_Group', 'Month_Label', 'Is_Zero_Rate']
        
        final_df = pd.DataFrame()
        for c in cols:
            final_df[c] = df[c] if c in df.columns else ''
        return final_df

    except Exception as e:
        return pd.DataFrame()

# ==============================================================================
# 3. 헬퍼 함수: 합계 행 추가 & 포맷 설정
# ==============================================================================

def add_total_row(df, group_col_name="구분"):
    """
    데이터프레임 하단에 '합계(TOTAL)' 행을 추가합니다.
    - ADR은 단순 합계가 아니라 (총매출 / 총객실수)로 재계산하여 정확도 보장
    """
    if df.empty:
        return df
    
    # 1. 숫자형 컬럼만 골라서 합계 계산
    numeric_df = df.select_dtypes(include=[np.number]).fillna(0)
    totals = numeric_df.sum().to_dict()
    
    # 2. 합계 행 딕셔너리 생성
    total_row = {col: "" for col in df.columns}
    total_row.update(totals)
    
    # 3. 그룹 컬럼 이름에 'TOTAL' 명시
    if group_col_name in df.columns:
        total_row[group_col_name] = "TOTAL"
    else:
        total_row[df.columns[0]] = "TOTAL"

    # 4. ADR 재계산 (Weighted Average)
    if 'Room_Revenue' in total_row and 'RN' in total_row:
        if total_row['RN'] > 0:
            total_row['ADR'] = total_row['Room_Revenue'] / total_row['RN']
        else:
            total_row['ADR'] = 0
            
    # 5. 합계 행 추가 (concat 사용)
    df_total = pd.DataFrame([total_row])
    df_final = pd.concat([df, df_total], ignore_index=True)
    
    return df_final

def get_fmt_config():
    """
    모든 테이블에 적용될 공통 컬럼 설정
    - format="%d": 소수점 제거
    - 천 단위 콤마는 Streamlit NumberColumn이 자동으로 처리함 (설정값에 따라 다를 수 있으나 %d가 정수형)
    """
    return {
        "RN": st.column_config.NumberColumn("객실수 (RN)", format="%d"),
        "Room_Revenue": st.column_config.NumberColumn("객실매출", format="%d"),
        "Total_Revenue": st.column_config.NumberColumn("총매출", format="%d"),
        "ADR": st.column_config.NumberColumn("객실단가 (ADR)", format="%d"),
        "Lead_Time": st.column_config.NumberColumn("리드타임", format="%d")
    }

def render_analysis_tab(target_df, title_prefix, color_scale="Blues"):
    """각 분석 탭(예약, 취소 등)의 내용을 렌더링하는 함수"""
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
        seg_stats['ADR'] = (seg_stats['Room_Revenue'] / seg_stats['RN']).fillna(0)
        
        # 합계 행 추가
        seg_final = add_total_row(seg_stats, 'Segment')
        
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.pie(seg_stats, values='Room_Revenue', names='Segment', title="매출 비중"), use_container_width=True)
        c2.plotly_chart(px.bar(seg_stats, x='Segment', y='ADR', title="세그먼트별 ADR", text_auto=',.0f', color='Segment'), use_container_width=True)
        
        st.dataframe(seg_final, hide_index=True, use_container_width=True, column_config=fmt_config)

    with t2:
        st.subheader(f"📅 Pacing Analysis")
        pivot_metric = st.radio(f"{title_prefix} 기준", ["RN", "Revenue", "ADR"], horizontal=True, key=f"{title_prefix}_rad")
        
        if pivot_metric == "ADR":
            rev_piv = target_df.pivot_table(index='Booking_Month', columns='Stay_Month', values='Room_Revenue', aggfunc='sum', fill_value=0)
            rn_piv = target_df.pivot_table(index='Booking_Month', columns='Stay_Month', values='RN', aggfunc='sum', fill_value=0)
            pacing = rev_piv.div(rn_piv).fillna(0)
            fmt = ".0f"
        elif pivot_metric == "RN":
            pacing = target_df.pivot_table(index='Booking_Month', columns='Stay_Month', values='RN', aggfunc='sum', fill_value=0)
            fmt = "d"
        else:
            pacing = target_df.pivot_table(index='Booking_Month', columns='Stay_Month', values='Room_Revenue', aggfunc='sum', fill_value=0)
            fmt = ".0f"
            
        pacing = pacing.fillna(0)
        st.plotly_chart(px.imshow(pacing, text_auto=fmt, aspect="auto", color_continuous_scale=color_scale), use_container_width=True)

    with t3:
        st.subheader("🏢 거래처 분석")
        acc_stats = target_df.groupby('Account').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
        acc_stats['ADR'] = (acc_stats['Room_Revenue'] / acc_stats['RN']).fillna(0)
        
        # 상위 100개만 + 합계
        acc_stats = acc_stats.sort_values('RN', ascending=False).head(100)
        acc_final = add_total_row(acc_stats, 'Account')

        fig_acc = px.scatter(acc_stats, x="RN", y="ADR", size="Room_Revenue", color="Account", hover_name="Account", size_max=60)
        st.plotly_chart(fig_acc, use_container_width=True)
        st.dataframe(acc_final, hide_index=True, use_container_width=True, column_config=fmt_config)

    with t4:
        st.subheader("⏳ 리드타임")
        bins = [-1, 0, 3, 7, 14, 30, 60, 90, 999]
        labels = ['0일', '1-3일', '4-7일', '8-14일', '15-30일', '31-60일', '61-90일', '90일+']
        temp_df = target_df.copy()
        temp_df['Lead_Group'] = pd.cut(temp_df['Lead_Time'], bins=bins, labels=labels)
        lead_stats = temp_df.groupby('Lead_Group').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
        lead_stats['ADR'] = (lead_stats['Room_Revenue'] / lead_stats['RN']).fillna(0)
        
        lead_final = add_total_row(lead_stats, 'Lead_Group')

        fig_lead = go.Figure()
        fig_lead.add_trace(go.Bar(x=lead_stats['Lead_Group'], y=lead_stats['RN'], name='RN', marker_color='blue', text=lead_stats['RN'], texttemplate='%{text:,.0f}'))
        fig_lead.add_trace(go.Scatter(x=lead_stats['Lead_Group'], y=lead_stats['ADR'], name='ADR', yaxis='y2', line=dict(color='red', width=2)))
        st.plotly_chart(fig_lead, use_container_width=True)
        st.dataframe(lead_final, hide_index=True, use_container_width=True, column_config=fmt_config)

    with t5:
        st.subheader("🛏️ 객실타입")
        rt_stats = target_df.groupby('Room_Type').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
        rt_stats['ADR'] = (rt_stats['Room_Revenue'] / rt_stats['RN']).fillna(0)
        
        rt_final = add_total_row(rt_stats.sort_values('RN', ascending=False), 'Room_Type')
        st.dataframe(rt_final, hide_index=True, use_container_width=True, column_config=fmt_config)

    with t6:
        st.subheader("🗓️ 요일별")
        wd_stats = target_df.groupby('Day_Type').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
        wd_stats['ADR'] = (wd_stats['Room_Revenue'] / wd_stats['RN']).fillna(0)
        
        wd_final = add_total_row(wd_stats, 'Day_Type')
        
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.bar(wd_stats, x='Day_Type', y='ADR', title="요일별 ADR", text_auto=',.0f'), use_container_width=True)
        c2.plotly_chart(px.pie(wd_stats, values='RN', names='Day_Type', title="요일별 비중"), use_container_width=True)
        st.dataframe(wd_final, hide_index=True, use_container_width=True, column_config=fmt_config)

    with t7:
        st.subheader("🌐 국적별")
        if 'Nat_Group' in target_df.columns:
            nat_stats = target_df.groupby('Nat_Group').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
            nat_stats['ADR'] = (nat_stats['Room_Revenue'] / nat_stats['RN']).fillna(0)
            
            nat_final = add_total_row(nat_stats, 'Nat_Group')
            
            c1, c2 = st.columns(2)
            c1.plotly_chart(px.pie(nat_stats, values='RN', names='Nat_Group', title="국적 비중"), use_container_width=True)
            c2.plotly_chart(px.bar(nat_stats, x='Nat_Group', y='ADR', title="국적별 ADR", text_auto=',.0f', color='Nat_Group'), use_container_width=True)
            
            st.dataframe(nat_final, hide_index=True, use_container_width=True, column_config=fmt_config)
        else:
            st.info("국적 데이터 없음")

# ==============================================================================
# UI 메인
# ==============================================================================
try:
    st.title("🏛️ 앰버 호텔 경영 리포트 (Final Integrity)")

    # 1. 데이터 로드
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
            st.success(f"선택됨: {selected_date}")
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

    # 3. 메인 대시보드
    if selected_date and not df_all.empty:
        df_filtered = df_all[df_all['Snapshot_Date'] == selected_date].copy()
        
        if df_filtered.empty:
            st.warning("선택한 날짜의 데이터가 없습니다.")
        else:
            # -------------------------------------------------------------
            # [핵심 수정] 숫자 데이터 강제 형변환 (포맷팅 필수 조건)
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
            # 날짜 없는 행 제거 및 보정
            df = df.dropna(subset=['CheckIn_dt'])
            df.loc[df['Booking_dt'].isna(), 'Booking_dt'] = df.loc[df['Booking_dt'].isna(), 'CheckIn_dt']
            
            # 파생 변수
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

            # 공통 설정
            fmt_cfg = get_fmt_config()

            # 탭 구성
            main_tab0, main_tab1, main_tab2, main_tab3, main_tab4, main_tab5 = st.tabs([
                "👑 총지배인(GM) 요약", "✅ 예약 상세", "❌ 취소 상세", "📈 종합 합계", "🆓 0원 예약", "🎯 OTB 현황"
            ])

            # ------------------------------------------------------------------
            # 1. GM 요약 탭 (요청사항 100% 반영)
            # ------------------------------------------------------------------
            with main_tab0:
                st.header(f"👑 총지배인(GM) 요약 리포트 ({selected_date} 기준)")
                
                # A. 예약 vs 취소 KPI
                st.subheader("1. 금일(Today) 예약 vs 취소 현황")
                
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
                    seg_gm['ADR'] = (seg_gm['Room_Revenue'] / seg_gm['RN']).fillna(0)
                    seg_gm_final = add_total_row(seg_gm, 'Segment')
                    st.dataframe(seg_gm_final, hide_index=True, use_container_width=True, column_config=fmt_cfg)
                else:
                    st.info("예약 데이터 없음")
                
                st.divider()

                # C. 국적별 비중 & 월별 집중도
                c_left, c_right = st.columns(2)
                with c_left:
                    st.subheader("3. 국적별 예약 비중")
                    if 'Nat_Group' in df_paid_bk.columns and not df_paid_bk.empty:
                        nat_gm = df_paid_bk.groupby('Nat_Group')['RN'].sum().reset_index()
                        fig_nat = px.pie(nat_gm, values='RN', names='Nat_Group', hole=0.4)
                        st.plotly_chart(fig_nat, use_container_width=True)
                    else:
                        st.info("데이터 없음")
                
                with c_right:
                    st.subheader("4. 월별 예약/취소 집중도 (비중)")
                    # 예약 월별
                    bk_m = df_paid_bk.groupby('Stay_Month')['RN'].sum().reset_index()
                    bk_m['Type'] = '예약'
                    # 취소 월별
                    cn_m = df_list_cn.groupby('Stay_Month')['RN'].sum().reset_index()
                    cn_m['Type'] = '취소'
                    
                    comb_m = pd.concat([bk_m, cn_m])
                    if not comb_m.empty:
                        fig_m = px.bar(comb_m, x='Stay_Month', y='RN', color='Type', barmode='group', text_auto='.0f', title="월별 발생량 (RN)")
                        st.plotly_chart(fig_m, use_container_width=True)
                    else:
                        st.info("데이터 없음")

            # ------------------------------------------------------------------
            # 나머지 탭들 (합계 행 + 포맷팅 적용)
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
                    st.warning("업로드된 OTB 데이터가 없습니다.")
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
        st.info("👈 왼쪽 사이드바에서 파일을 업로드하여 데이터를 추가해주세요.")

except Exception as e:
    st.error(f"🚨 시스템 오류: {e}")
