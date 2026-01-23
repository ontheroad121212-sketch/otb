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
    """
    target_cols = [
        'RN', 'Room_Revenue', 'Total_Revenue', 'ADR_Room', 'ADR_Total', 
        'Lead_Time', 'OTB_Rev', 'Budget_Rev', 'Budget_Achiev', 'OTB_RN', 
        'OTB_ADR', 'Actual_Rev', 'Actual_RN', 'Rooms', 'Nights'
    ]
    
    for col in target_cols:
        if col in df.columns:
            # 문자열로 변환 -> 콤마, ₩, $, 공백 제거 -> 숫자 변환
            df[col] = pd.to_numeric(
                df[col].astype(str)
                .str.replace(',', '')
                .str.replace('₩', '')
                .str.replace('$', '')
                .str.replace(' ', '')
                .str.replace('nan', '0'), 
                errors='coerce'
            ).fillna(0)
            
    # ADR(객실단가) 재계산 로직
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
            
        # NaT나 NaN 값을 Firestore가 인식할 수 있는 값으로 치환
        df_save = df.copy()
        for col in df_save.columns:
            if df_save[col].dtype == 'datetime64[ns]':
                df_save[col] = df_save[col].astype(str)
        
        records = df_save.fillna(0).astype(str).to_dict(orient='records')
        
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
    """기존 DB에서 OTB 데이터만 삭제합니다."""
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
# 4. 파일 처리 및 매핑 로직 (핵심 수정 구간)
# ==============================================================================

def normalize_and_map_columns(df):
    """한글 컬럼명을 표준 영문 이름으로 매핑합니다."""
    col_map = {}
    rules = {
        'CheckIn': ['checkin', 'arrival', '입실', '일자', 'date'],
        'Guest_Name': ['guest', 'name', 'customer', '고객', '성명'],
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
                if key == 'Room_Revenue' and 'total' in clean: continue
                if key == 'Total_Revenue' and 'room' in clean: continue
                if key == 'CheckIn' and ('book' in clean or 'res' in clean): continue
                if key not in col_map.values():
                    col_map[col] = key
                    break
    return df.rename(columns=col_map)

def process_data(file, status, force_otb=False):
    """
    [정밀 수정 로직]
    - OTB: 테이블 가장 오른쪽 열(-1)을 매출로, 뒤에서 5번째(-5)를 RN으로 인식.
    - 조식: 서비스코드에 'BF'가 있으면 조식 포함으로 분류.
    """
    try:
        is_filename_otb = "Sales on the Book" in file.name or "영업 현황" in file.name
        is_otb = force_otb or is_filename_otb
        
        file.seek(0)
        if file.name.endswith('.csv'): 
            try: df_raw = pd.read_csv(file, header=None)
            except: df_raw = pd.read_csv(file, header=None, encoding='cp949')
        else: 
            df_raw = pd.read_excel(file, header=None)

        # 1. 헤더 행(제목 줄) 자동 찾기
        best_row = 0; max_hit = 0
        keywords = ['guest', 'name', 'check', 'date', 'room', '고객', '입실', '객실', '서비스', '매출', '일자', '요일']
        for i, row in df_raw.head(15).iterrows():
            hit = sum(1 for k in keywords if k in str(row.values).lower())
            if hit > max_hit: max_hit = hit; best_row = i
        
        headers = df_raw.iloc[best_row].values
        df_final = df_raw.iloc[best_row+1:].reset_index(drop=True)
        df_final.columns = [str(h).strip() for h in headers]

        if is_otb:
            # 합계/소계 행 제거
            if '일자' in df_final.columns:
                df_final = df_final[~df_final['일자'].astype(str).str.contains('합계|Total|소계', na=False)]
            
            df = pd.DataFrame()
            # 날짜: 무조건 첫 번째 열
            df['CheckIn'] = pd.to_datetime(df_final.iloc[:, 0], errors='coerce')
            
            # [핵심] OTB 매출: 테이블 물리적 가장 마지막 열(-1) 사용
            df['Room_Revenue'] = pd.to_numeric(
                df_final.iloc[:, -1].astype(str).str.replace(',', '').str.replace('₩', '').str.replace('nan', '0'), 
                errors='coerce'
            ).fillna(0)
            
            # [핵심] OTB RN: 뒤에서 5번째 열(-5) 사용 (합계 객실수 위치)
            df['RN'] = pd.to_numeric(
                df_final.iloc[:, -5].astype(str).str.replace(',', '').str.replace(' ', '').str.replace('nan', '0'), 
                errors='coerce'
            ).fillna(0)
            
            df['Total_Revenue'] = df['Room_Revenue']
            df['Guest_Name'] = 'OTB_DATA'; df['Segment'] = 'OTB'; df['Account'] = 'OTB_Summary'
            df['Room_Type'] = 'ROH'; df['Nat_Orig'] = 'KR'; df['Lead_Time'] = 0; df['Breakfast'] = 'Unknown'
            
        else:
            # 합계 행 제거
            df_final = df_final[~df_final.iloc[:, 0].astype(str).str.contains('합계|Total', na=False)]
            df = normalize_and_map_columns(df_final).copy()
            
            # 필수 컬럼 채우기
            req_cols = ['Rooms','Nights','Room_Revenue','Total_Revenue','Guest_Name','Segment','Account','Room_Type','Nat_Orig','Lead_Time','Service_Code']
            for c in req_cols:
                if c not in df.columns: df[c] = 0 if c in ['Rooms', 'Nights', 'Room_Revenue', 'Total_Revenue', 'Lead_Time'] else 'Unknown'
            
            # [핵심] 조식 식별 로직 (서비스코드 BF 검색)
            def check_bf(row):
                sc = str(row.get('Service_Code', '')).upper()
                return 'Included (조식포함)' if 'BF' in sc else 'Not Included (불포함)'
            df['Breakfast'] = df.apply(check_bf, axis=1)
            
            # RN 계산 (객실수 * 박수)
            df['RN'] = pd.to_numeric(df['Rooms'], errors='coerce').fillna(0) * pd.to_numeric(df['Nights'], errors='coerce').replace(0,1).fillna(1)

        # 공통 마무리 로직
        df['Status'] = status
        df['Snapshot_Date'] = datetime.now().strftime('%Y-%m-%d')
        df['CheckIn_dt'] = pd.to_datetime(df['CheckIn'], errors='coerce')
        df = df.dropna(subset=['CheckIn_dt'])
        
        df['Stay_Month'] = df['CheckIn_dt'].dt.strftime('%Y-%m')
        df['Booking_Month'] = pd.to_datetime(df.get('Booking_Date', df['CheckIn']), errors='coerce').dt.strftime('%Y-%m')
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
        st.error(f"파일 처리 중 오류: {e}")
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
    if 'Budget_Achiev' in df.columns:
        styler = styler.format({'Budget_Achiev': "{:.1f}%"})
    def highlight_total(row):
        is_total = any(str(val) == "TOTAL" for val in row)
        return ['background-color: #fff9c4; font-weight: bold; color: black; border-top: 2px solid black'] * len(row) if is_total else [''] * len(row)
    st.dataframe(styler.apply(highlight_total, axis=1), hide_index=True, use_container_width=True)

def render_analysis_tab(target_df, title_prefix, unique_key, color_scale="Blues"):
    if target_df.empty:
        st.warning(f"⚠️ {title_prefix} 데이터가 없습니다.")
        return
    
    t1, t2, t3, t4, t5, t6, t7, t8 = st.tabs(["📊 세그먼트", "📅 Pacing", "🏢 거래처", "⏳ 리드타임", "🛏️ 객실타입", "🗓️ 요일", "🌐 국적", "🍳 조식"])
    
    with t1:
        s = target_df.groupby('Segment').agg({'RN': 'sum', 'Room_Revenue': 'sum', 'Total_Revenue': 'sum'}).reset_index()
        s['ADR_Room'] = np.where(s['RN']>0, s['Room_Revenue']/s['RN'], 0)
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.pie(s, values='Room_Revenue', names='Segment', title="매출 비중"), use_container_width=True, key=f"{unique_key}_pie")
        c2.plotly_chart(px.bar(s, x='Segment', y='Room_Revenue', title="세그먼트별 매출"), use_container_width=True, key=f"{unique_key}_bar")
        show_dataframe_with_style(add_total_row(s, 'Segment'))
    with t2:
        piv = target_df.pivot_table(index='Booking_Month', columns='Stay_Month', values='RN', aggfunc='sum').fillna(0)
        st.plotly_chart(px.imshow(piv, text_auto="d", aspect="auto", color_continuous_scale=color_scale), use_container_width=True, key=f"{unique_key}_pacing")
    with t3:
        acc = target_df.groupby('Account').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index().sort_values('RN', ascending=False).head(50)
        show_dataframe_with_style(add_total_row(acc, 'Account'))
    with t4:
        df_lt = target_df.copy()
        df_lt['LT_G'] = pd.cut(df_lt['Lead_Time'], bins=[-1, 0, 3, 7, 14, 30, 60, 90, 999], labels=['0일', '1-3일', '4-7일', '8-14일', '15-30일', '31-60일', '61-90일', '90일+'])
        lt = df_lt.groupby('LT_G').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
        st.plotly_chart(px.bar(lt, x='LT_G', y='RN', title="리드타임별 건수"), use_container_width=True, key=f"{unique_key}_lt")
        show_dataframe_with_style(add_total_row(lt, 'LT_G'))
    with t5:
        rt = target_df.groupby('Room_Type').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
        show_dataframe_with_style(add_total_row(rt, 'Room_Type'))
    with t6:
        wd = target_df.groupby('Day_Type').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.bar(wd, x='Day_Type', y='Room_Revenue'), use_container_width=True, key=f"{unique_key}_wd_bar")
        c2.plotly_chart(px.pie(wd, values='RN', names='Day_Type'), use_container_width=True, key=f"{unique_key}_wd_pie")
        show_dataframe_with_style(add_total_row(wd, 'Day_Type'))
    with t7:
        if 'Nat_Group' in target_df.columns:
            nat = target_df.groupby('Nat_Group').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
            c1, c2 = st.columns(2)
            c1.plotly_chart(px.pie(nat, values='RN', names='Nat_Group'), use_container_width=True, key=f"{unique_key}_nat_pie")
            c2.plotly_chart(px.bar(nat, x='Nat_Group', y='Room_Revenue'), use_container_width=True, key=f"{unique_key}_nat_bar")
            show_dataframe_with_style(add_total_row(nat, 'Nat_Group'))
    with t8:
        if 'Breakfast' in target_df.columns:
            bf = target_df.groupby('Breakfast').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
            bf['ADR'] = np.where(bf['RN']>0, bf['Room_Revenue']/bf['RN'], 0)
            c1, c2 = st.columns(2)
            c1.plotly_chart(px.pie(bf, values='RN', names='Breakfast', title="조식 비중(RN)"), use_container_width=True, key=f"{unique_key}_bf_pie")
            c2.plotly_chart(px.bar(bf, x='Breakfast', y='Room_Revenue', title="조식 여부별 매출"), use_container_width=True, key=f"{unique_key}_bf_bar")
            show_dataframe_with_style(add_total_row(bf, 'Breakfast'))

# ==============================================================================
# UI 메인 실행부
# ==============================================================================
try:
    st.title("🏛️ 앰버 호텔 경영 리포트 (Final Integrity)")
    raw_data = load_data_from_firestore()
    df_all = pd.DataFrame(raw_data) if raw_data else pd.DataFrame()
    available_dates = sorted(df_all['Snapshot_Date'].unique(), reverse=True) if not df_all.empty else []

    with st.sidebar:
        st.header("📅 조회 및 업로드")
        if st.button("🗑️ OTB 데이터 초기화"):
            cnt = delete_otb_data_only()
            st.warning(f"OTB {cnt}건 삭제 완료! 다시 업로드해주세요.")
            time.sleep(1); st.cache_data.clear(); st.rerun()
        selected_date = st.selectbox("조회 기준일", available_dates, index=0) if available_dates else None
        
        st.markdown("---")
        with st.expander("데이터 업로드", expanded=True):
            f1 = st.file_uploader("예약/취소 리스트", type=['xlsx','csv'], key="f1")
            if f1 and st.button("실적 저장"):
                df = process_data(f1, "Booked")
                if not df.empty and save_to_firestore(df): st.success("저장 성공!"); time.sleep(1); st.cache_data.clear(); st.rerun()
            
            f3 = st.file_uploader("OTB 파일 (Sales on the Book)", type=['xlsx','csv'], key="f3", accept_multiple_files=True)
            if f3 and st.button("OTB 저장"):
                all_otb = [process_data(f, "Booked", True) for f in f3]
                combined = pd.concat([d for d in all_otb if not d.empty], ignore_index=True)
                if not combined.empty and save_to_firestore(combined): st.success("OTB 저장 완료!"); time.sleep(1); st.cache_data.clear(); st.rerun()

    if selected_date and not df_all.empty:
        df = clean_numeric_columns(df_all[df_all['Snapshot_Date'] == selected_date].copy())
        df_otb = df[df['Segment'] == 'OTB']
        df_list = df[df['Segment'] != 'OTB']
        df_paid_bk = df_list[(df_list['Status'] == 'Booked') & (df_list['Total_Revenue'] > 0)]
        df_list_cn = df_list[df_list['Status'] == 'Cancelled']
        df_total_paid = pd.concat([df_paid_bk, df_list_cn])

        m0, m1, m2, m3, m4, m5 = st.tabs(["👑 GM 요약", "✅ 예약 상세", "❌ 취소 상세", "📈 종합 합계", "🆓 0원 예약", "🎯 OTB 현황"])
        
        with m0:
            st.header(f"👑 GM 요약 ({selected_date})")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("예약 RN", f"{df_paid_bk['RN'].sum():,.0f}")
            c2.metric("예약 매출", f"{df_paid_bk['Room_Revenue'].sum():,.0f}")
            c3.metric("취소 RN", f"{df_list_cn['RN'].sum():,.0f}")
            c4.metric("취소 매출", f"{df_list_cn['Room_Revenue'].sum():,.0f}")
            st.subheader("세그먼트별 실적 요약")
            seg = df_paid_bk.groupby('Segment').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index()
            show_dataframe_with_style(add_total_row(seg, 'Segment'))
            
        with m1: render_analysis_tab(df_paid_bk, "예약", "bk")
        with m2: render_analysis_tab(df_list_cn, "취소", "cn")
        with m3: render_analysis_tab(df_total_paid, "종합", "tot")
        with m4:
            df_zero = df_list[(df_list['Status'] == 'Booked') & (df_list['Total_Revenue'] <= 0)]
            st.subheader(f"🆓 0원 예약 (총 {len(df_zero)}건)")
            st.dataframe(df_zero[['Guest_Name', 'CheckIn', 'Account', 'Room_Type']], use_container_width=True)
            
        with m5:
            st.header("🎯 OTB 현황 (Budget vs OTB)")
            if df_otb.empty: st.warning("OTB 데이터가 없습니다.")
            else:
                base = df_otb.copy()
                base['M'] = pd.to_datetime(base['CheckIn']).dt.month
                otb_m = base.groupby('M').agg({'Room_Revenue':'sum'}).reset_index()
                otb_m['Budget'] = otb_m['M'].map(BUDGET_DATA).fillna(0)
                otb_m['Rate'] = (otb_m['Room_Revenue'] / otb_m['Budget'] * 100).fillna(0)
                
                fig = go.Figure()
                fig.add_trace(go.Bar(x=otb_m['M'].astype(str)+"월", y=otb_m['Room_Revenue'], name='현재 OTB', text=otb_m['Rate'].apply(lambda x: f"{x:.1f}%"), textposition='outside'))
                fig.add_trace(go.Scatter(x=otb_m['M'].astype(str)+"월", y=otb_m['Budget'], name='목표 Budget', line=dict(color='red', dash='dot')))
                st.plotly_chart(fig, use_container_width=True)
                
                res_table = []
                for _, row in otb_m.iterrows():
                    res_table.append({"월": f"{int(row['M'])}월", "목표": f"{row['Budget']:,.0f}", "실적": f"{row['Room_Revenue']:,.0f}", "달성률": f"{row['Rate']:.1f}%"})
                st.table(pd.DataFrame(res_table))
    else:
        st.info("👈 사이드바에서 데이터를 업로드하고 기준일을 선택해 주세요.")
        
except Exception as e:
    st.error(f"🚨 시스템 오류가 발생했습니다: {e}")
