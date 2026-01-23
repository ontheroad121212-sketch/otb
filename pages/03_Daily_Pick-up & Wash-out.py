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
# 0. 사용자 정의 버짓 데이터 (1월~12월 목표 매출)
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
    천단위 콤마(,)나 문자열이 섞여 있어도 처리합니다.
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
    [정밀 분석 로직 반영]
    1. 조식 (예약/취소 리스트):
       - 3행(index 2)이 헤더, 4행(index 3)부터 데이터 시작.
       - K열(index 10)의 서비스코드 확인. 공란=룸온리, 'BF' 포함=조식포함.
    2. OTB (영업현황):
       - 12개월 월별 파일. S열(index 18)의 가장 마지막 행 값이 월별 매출(통화 형식).
       - A열(index 0)의 5행(index 4) 날짜 데이터로 월 구분.
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
            # 날짜 식별: A열(0)의 5행(4) 날짜 활용
            date_val = pd.to_datetime(df_raw.iloc[4, 0], errors='coerce')
            
            # 매출 식별: S열(18)에서 유효한 마지막 데이터 행(합계) 찾기
            # (엑셀 하단에 빈 줄이 있을 수 있으므로 실제 데이터가 있는 마지막 index 탐색)
            s_col_series = df_raw.iloc[4:, 18]
            last_idx = s_col_series.last_valid_index()
            
            # 통화 형식 기호 제거 후 숫자로 변환
            revenue_val = pd.to_numeric(
                str(df_raw.iloc[last_idx, 18]).replace(',', '').replace('₩', '').replace('$', '').replace(' ', ''),
                errors='coerce'
            )
            
            # RN 식별: 보통 O열(index 14) 부근에 합계 객실수가 위치함 (Snippet 기반 위치 추정)
            rn_val = pd.to_numeric(str(df_raw.iloc[last_idx, 14]).replace(',', ''), errors='coerce')

            df = pd.DataFrame([{
                'CheckIn': date_val,
                'Room_Revenue': revenue_val,
                'RN': rn_val,
                'Total_Revenue': revenue_val,
                'Guest_Name': 'OTB_MONTHLY_TOTAL',
                'Segment': 'OTB',
                'Account': 'OTB_Summary',
                'Room_Type': 'ROH',
                'Nat_Orig': 'KR',
                'Booking_Date': date_val,
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
            df_header = df_raw.iloc[2]
            df = df_raw.iloc[3:].reset_index(drop=True)
            df.columns = df_header
            
            # 컬럼 매핑 실행
            df = normalize_and_map_columns(df).copy()

            # [핵심] 조식 식별 로직: K열(index 10) 직접 접근
            # (매핑 결과와 관계없이 위치 기반으로 보정)
            def check_breakfast_k_col(row):
                # K열은 index 10
                svc_val = str(row.iloc[10]).upper()
                if 'BF' in svc_val:
                    return 'Included (조식포함)'
                return 'Room Only (불포함)'
            
            df['Breakfast'] = df.apply(check_breakfast_k_col, axis=1)

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
        
        def classify_nat(row):
            name = str(row.get('Guest_Name', ''))
            orig = str(row.get('Nat_Orig', '')).upper()
            if re.search('[가-힣]', name): return 'KOR'
            if any(x in orig for x in ['CHN', 'HKG', 'TWN', 'MAC']): return 'CHN'
            return 'OTH'
        df['Nat_Group'] = df.apply(classify_nat, axis=1)
        
        return clean_numeric_columns(df)

    except Exception as e:
        return pd.DataFrame()

# ==============================================================================
# 5. UI 렌더링 헬퍼 함수들 (무생략)
# ==============================================================================

def add_total_row(df, group_col_name="구분"):
    """
    데이터프레임 하단에 'TOTAL' 합계 행을 추가합니다.
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

    # ADR 재계산
    if 'RN' in total_row and total_row['RN'] > 0:
        if 'Room_Revenue' in total_row:
            total_row['ADR_Room'] = total_row['Room_Revenue'] / total_row['RN']
        if 'Total_Revenue' in total_row:
            total_row['ADR_Total'] = total_row['Total_Revenue'] / total_row['RN']
    else:
        total_row['ADR_Room'] = 0
        total_row['ADR_Total'] = 0
            
    return pd.concat([df, pd.DataFrame([total_row])], ignore_index=True)

def show_dataframe_with_style(df):
    """
    데이터프레임을 보기 좋게 스타일링하여 출력합니다.
    """
    if df.empty:
        st.write("표시할 데이터가 없습니다.")
        return

    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    styler = df.style.format({col: "{:,.0f}" for col in numeric_cols})
    
    if 'Budget_Achiev' in df.columns:
        styler = styler.format({'Budget_Achiev': "{:.1f}%"})
    
    # 합계 행 강조 스타일
    def highlight_total(row):
        is_total = False
        for val in row:
            if str(val) == "TOTAL": is_total = True; break
        return ['background-color: #fff9c4; font-weight: bold; color: black; border-top: 2px solid black'] * len(row) if is_total else [''] * len(row)
    
    styler = styler.apply(highlight_total, axis=1)
    st.dataframe(styler, hide_index=True, use_container_width=True)

def render_analysis_tab(target_df, title_prefix, unique_key, color_scale="Blues"):
    """
    상세 분석 탭들을 렌더링합니다.
    """
    if target_df.empty:
        st.warning(f"⚠️ {title_prefix} 데이터가 없습니다.")
        return

    # 탭 구성
    t1, t2, t3, t4, t5, t6, t7, t8 = st.tabs([
        "📊 세그먼트", "📅 Pacing", "🏢 거래처", 
        "⏳ 리드타임", "🛏️ 객실타입", "🗓️ 요일", "🌐 국적", "🍳 조식"
    ])
    
    with t1:
        st.subheader(f"📊 {title_prefix} 세그먼트 분석")
        seg_stats = target_df.groupby('Segment').agg({'RN': 'sum', 'Room_Revenue': 'sum', 'Total_Revenue': 'sum'}).reset_index()
        seg_stats['ADR_Room'] = np.where(seg_stats['RN']>0, seg_stats['Room_Revenue']/seg_stats['RN'], 0)
        seg_stats['ADR_Total'] = np.where(seg_stats['RN']>0, seg_stats['Total_Revenue']/seg_stats['RN'], 0)
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.pie(seg_stats, values='Room_Revenue', names='Segment', title="매출 비중"), use_container_width=True, key=f"{unique_key}_seg_pie")
        c2.plotly_chart(px.bar(seg_stats, x='Segment', y='Room_Revenue', title="세그먼트별 매출"), use_container_width=True, key=f"{unique_key}_seg_bar")
        show_dataframe_with_style(add_total_row(seg_stats, 'Segment'))

    with t2:
        st.subheader(f"📅 Booking Pacing (예약 시점)")
        piv = target_df.pivot_table(index='Booking_Month', columns='Stay_Month', values='RN', aggfunc='sum').fillna(0)
        st.plotly_chart(px.imshow(piv, text_auto="d", aspect="auto", color_continuous_scale=color_scale), use_container_width=True, key=f"{unique_key}_pacing")

    with t3:
        st.subheader("🏢 상위 거래처 (Top 50)")
        acc_stats = target_df.groupby('Account').agg({'RN': 'sum', 'Room_Revenue': 'sum', 'Total_Revenue': 'sum'}).reset_index()
        acc_stats['ADR_Room'] = np.where(acc_stats['RN']>0, acc_stats['Room_Revenue']/acc_stats['RN'], 0)
        acc_stats['ADR_Total'] = np.where(acc_stats['RN']>0, acc_stats['Total_Revenue']/acc_stats['RN'], 0)
        show_dataframe_with_style(add_total_row(acc_stats.sort_values('RN', ascending=False).head(50), 'Account'))

    with t4:
        st.subheader("⏳ 리드타임 (예약일~체크인)")
        temp_df = target_df.copy()
        temp_df['Lead_Group'] = pd.cut(temp_df['Lead_Time'], bins=[-1, 0, 3, 7, 14, 30, 60, 90, 999], labels=['0일', '1-3일', '4-7일', '8-14일', '15-30일', '31-60일', '61-90일', '90일+'])
        lead_stats = temp_df.groupby('Lead_Group').agg({'RN': 'sum', 'Room_Revenue': 'sum', 'Total_Revenue': 'sum'}).reset_index()
        st.plotly_chart(px.bar(lead_stats, x='Lead_Group', y='RN', title="리드타임별 건수"), use_container_width=True, key=f"{unique_key}_lead")
        show_dataframe_with_style(add_total_row(lead_stats, 'Lead_Group'))

    with t5:
        st.subheader("🛏️ 객실타입 선호도")
        rt_stats = target_df.groupby('Room_Type').agg({'RN': 'sum', 'Room_Revenue': 'sum', 'Total_Revenue': 'sum'}).reset_index()
        show_dataframe_with_style(add_total_row(rt_stats.sort_values('RN', ascending=False), 'Room_Type'))

    with t6:
        st.subheader("🗓️ 요일별 패턴")
        wd_stats = target_df.groupby('Day_Type').agg({'RN': 'sum', 'Room_Revenue': 'sum', 'Total_Revenue': 'sum'}).reset_index()
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.bar(wd_stats, x='Day_Type', y='Room_Revenue'), use_container_width=True, key=f"{unique_key}_day_bar")
        c2.plotly_chart(px.pie(wd_stats, values='RN', names='Day_Type'), use_container_width=True, key=f"{unique_key}_day_pie")
        show_dataframe_with_style(add_total_row(wd_stats, 'Day_Type'))

    with t7:
        st.subheader("🌐 국적별 분포")
        if 'Nat_Group' in target_df.columns:
            nat_stats = target_df.groupby('Nat_Group').agg({'RN': 'sum', 'Room_Revenue': 'sum', 'Total_Revenue': 'sum'}).reset_index()
            c1, c2 = st.columns(2)
            c1.plotly_chart(px.pie(nat_stats, values='RN', names='Nat_Group', title="국적 비중"), use_container_width=True, key=f"{unique_key}_nat_pie")
            c2.plotly_chart(px.bar(nat_stats, x='Nat_Group', y='Room_Revenue'), use_container_width=True, key=f"{unique_key}_nat_bar")
            show_dataframe_with_style(add_total_row(nat_stats, 'Nat_Group'))
        else:
            st.info("국적 데이터 없음")

    with t8:
        st.subheader("🍳 조식 포함 여부 분석 (Position Based)")
        if 'Breakfast' in target_df.columns:
            bf_stats = target_df.groupby('Breakfast').agg({'RN': 'sum', 'Room_Revenue': 'sum', 'Total_Revenue': 'sum'}).reset_index()
            bf_stats['ADR_Room'] = np.where(bf_stats['RN']>0, bf_stats['Room_Revenue']/bf_stats['RN'], 0)
            c1, c2 = st.columns(2)
            c1.plotly_chart(px.pie(bf_stats, values='RN', names='Breakfast', title="조식 포함 비율 (RN)"), use_container_width=True, key=f"{unique_key}_bf_pie")
            c2.plotly_chart(px.bar(bf_stats, x='Breakfast', y='Room_Revenue', title="매출 비교"), use_container_width=True, key=f"{unique_key}_bf_bar")
            show_dataframe_with_style(add_total_row(bf_stats, 'Breakfast'))
        else:
            st.info("조식 데이터가 없습니다.")

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
    # SIDEBAR
    # ----------------------------------------------------------------------
    with st.sidebar:
        st.header("📅 조회 설정")
        if st.button("🗑️ OTB 데이터만 초기화"):
            deleted_cnt = delete_otb_data_only()
            st.warning(f"OTB 데이터 {deleted_cnt}건 삭제 완료! 파일을 다시 업로드해주세요.")
            time.sleep(1); st.cache_data.clear(); st.rerun()
            
        selected_date = st.selectbox("조회 기준일 (Snapshot)", available_dates, index=0) if available_dates else None

        st.markdown("---")
        st.header("📤 데이터 업로드")
        
        with st.expander("1. 예약 리스트", expanded=True):
            f1 = st.file_uploader("예약 리스트 (Excel)", type=['xlsx','csv'], key="f1")
            if f1 and st.button("예약 저장"):
                df = process_data(f1, "Booked")
                if not df.empty and save_to_firestore(df):
                    st.success("예약 리스트 저장 성공!"); time.sleep(1); st.cache_data.clear(); st.rerun()
            
        with st.expander("2. 취소 리스트", expanded=True):
            f2 = st.file_uploader("취소 리스트 (Excel)", type=['xlsx','csv'], key="f2")
            if f2 and st.button("취소 저장"):
                df = process_data(f2, "Cancelled")
                if not df.empty and save_to_firestore(df):
                    st.success("취소 리스트 저장 성공!"); time.sleep(1); st.cache_data.clear(); st.rerun()

        with st.expander("3. OTB (영업현황)", expanded=True):
            f3_list = st.file_uploader("OTB 파일들 (12개월)", type=['xlsx','csv'], key="f3", accept_multiple_files=True)
            if f3_list and st.button("OTB 저장"):
                all_otb = []
                for f in f3_list:
                    processed = process_data(f, "Booked", force_otb=True)
                    if not processed.empty: all_otb.append(processed)
                if all_otb:
                    combined_otb = pd.concat(all_otb, ignore_index=True)
                    if save_to_firestore(combined_otb):
                        st.success(f"OTB {len(all_otb)}개 월 데이터 저장 완료!"); time.sleep(1); st.cache_data.clear(); st.rerun()

    # ----------------------------------------------------------------------
    # DASHBOARD MAIN
    # ----------------------------------------------------------------------
    if selected_date and not df_all.empty:
        df_filtered = df_all[df_all['Snapshot_Date'] == selected_date].copy()
        df = clean_numeric_columns(df_filtered)
        
        if not df.empty:
            # 날짜형 데이터 변환
            df['Booking_dt'] = pd.to_datetime(df.get('Booking_Date', df['CheckIn']), errors='coerce')
            df['CheckIn_dt'] = pd.to_datetime(df['CheckIn'], errors='coerce')
            df = df.dropna(subset=['CheckIn_dt'])
            
            # 파생 변수
            df['Is_Zero_Rate'] = df['Total_Revenue'] <= 0
            df['Booking_Month'] = df['Booking_dt'].dt.strftime('%Y-%m')
            df['Stay_Month'] = df['CheckIn_dt'].dt.strftime('%Y-%m')
            
            # 데이터 분리
            df_otb = df[df['Segment'].astype(str).str.contains('OTB')]
            df_list = df[~df['Segment'].astype(str).str.contains('OTB')]
            df_paid_bk = df_list[(df_list['Status'] == 'Booked') & (df_list['Is_Zero_Rate'] == False)]
            df_list_cn = df_list[df_list['Status'] == 'Cancelled']
            df_total_paid = pd.concat([df_paid_bk, df_list_cn])

            main_tab0, main_tab1, main_tab2, main_tab3, main_tab4, main_tab5 = st.tabs([
                "👑 총지배인(GM) 요약", "✅ 예약 상세", "❌ 취소 상세", "📈 종합 합계", "🆓 0원 예약", "🎯 OTB 현황"
            ])

            with main_tab0:
                st.header(f"👑 총지배인(GM) 요약 리포트 ({selected_date})")
                c1,c2,c3,c4 = st.columns(4)
                c1.metric("확정 예약 건수", f"{len(df_paid_bk):,.0f}건")
                c2.metric("확정 예약 RN", f"{df_paid_bk['RN'].sum():,.0f}RN")
                c3.metric("확정 예약 매출", f"{df_paid_bk['Room_Revenue'].sum():,.0f}원")
                c4.metric("금일 취소 RN", f"{df_list_cn['RN'].sum():,.0f}RN")
                
                st.subheader("📊 세그먼트별 픽업 요약")
                seg_gm = df_paid_bk.groupby('Segment').agg({'RN': 'sum','Room_Revenue': 'sum'}).reset_index()
                show_dataframe_with_style(add_total_row(seg_gm, 'Segment')) 

            with main_tab1: render_analysis_tab(df_paid_bk, "유료 예약", "bk")
            with main_tab2: render_analysis_tab(df_list_cn, "취소 데이터", "cn")
            with main_tab3: render_analysis_tab(df_total_paid, "종합(예약+취소)", "tot")
            with main_tab4:
                df_zero = df_list[(df_list['Status'] == 'Booked') & (df_list['Is_Zero_Rate'] == True)]
                st.subheader(f"🆓 0원 예약 (총 {len(df_zero)}건)")
                st.dataframe(df_zero[['Guest_Name', 'CheckIn', 'Account', 'Room_Type', 'Service_Code']], use_container_width=True)

            with main_tab5:
                st.header("🎯 OTB 현황 (Budget vs OTB)")
                if df_otb.empty: st.warning("OTB 데이터가 없습니다.")
                else:
                    all_months = pd.DataFrame({'M': range(1, 13)})
                    base = df_otb.copy()
                    base['M'] = pd.to_datetime(base['CheckIn']).dt.month
                    otb_m = base.groupby('M').agg({'Room_Revenue':'sum'}).reset_index()
                    fin = pd.merge(all_months, otb_m, on='M', how='left').fillna(0)
                    fin['Budget'] = fin['M'].map(BUDGET_DATA).fillna(0)
                    fin['OTB'] = fin['Room_Revenue']
                    fin['Rate'] = np.where(fin['Budget'] > 0, (fin['OTB'] / fin['Budget']) * 100, 0)
                    fin['Name'] = fin['M'].astype(str) + "월"
                    
                    fig = go.Figure()
                    fig.add_trace(go.Bar(x=fin['Name'], y=fin['OTB'], name='OTB (현재)', marker_color='#2E86C1', text=fin['Rate'].apply(lambda x: f"{x:.1f}%"), textposition='outside'))
                    fig.add_trace(go.Scatter(x=fin['Name'], y=fin['Budget'], name='Budget (목표)', line=dict(color='red', dash='dot')))
                    st.plotly_chart(fig, use_container_width=True)
                    
                    res_dict = {row['Name']: [f"{row['Budget']:,.0f}", f"{row['OTB']:,.0f}", f"{row['Rate']:.1f}%"] for _, row in fin.iterrows()}
                    st.table(pd.DataFrame(res_dict, index=['Budget (목표)', 'OTB (현재)', '달성률 (%)']))
    else:
        st.info("👈 사이드바에서 파일을 업로드하고 조회 기준일을 선택해 주세요.")

except Exception as e:
    st.error(f"🚨 시스템 오류: {e}")
