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
# 4. 엑셀/CSV 파일 처리 및 매핑 로직 (OTB 로직 강화)
# ==============================================================================

def normalize_and_map_columns(df):
    """
    다양한 이름의 컬럼들을 표준화된 이름으로 매핑합니다.
    예: '객실료', '매출', 'Room Charge' -> 'Room_Revenue'
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
        'Service_Code': ['service', '서비스', 'code'], # 조식 식별용
        'Nat_Orig': ['nation', 'country', 'nat', '국적'],
        'Lead_Time': ['lead', '리드', 'lt', 'l/t']
    }

    for original_col in df.columns:
        clean_col = str(original_col).lower().replace(" ", "").replace("_", "").replace("-", "")
        mapped = False
        
        for target_col, keywords in rules.items():
            for kw in keywords:
                if kw in clean_col:
                    # 중복 매핑 방지 규칙
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
        # 헤더로 추정되는 키워드들이 포함되어 있는지 확인
        keywords = ['guest', 'name', 'check', 'date', 'room', '고객', '입실', '객실']
        if sum(1 for k in keywords if k in row_str) >= 2:
            df.columns = df.iloc[i]
            return df.iloc[i+1:].reset_index(drop=True)
    return df

def process_data(file, status, force_otb=False):
    try:
        is_filename_otb = "Sales on the Book" in file.name or "영업 현황" in file.name
        is_otb = force_otb or is_filename_otb
        
        # 파일 읽기
        if file.name.endswith('.csv'):
            try: df_raw = pd.read_csv(file, header=None)
            except: df_raw = pd.read_csv(file, header=None, encoding='cp949')
        else: df_raw = pd.read_excel(file, header=None)

        # 헤더 찾기 (키워드 매칭)
        header_idx = -1
        keywords = ['guest', 'name', 'check', 'date', 'room', '고객', '입실', '일자']
        if is_otb: keywords += ['매출', 'rev', 'revenue', '합계']
        
        for i, row in df_raw.head(20).iterrows(): # 상위 20줄 검사
            row_str = " ".join(row.astype(str).values).lower()
            if sum(1 for k in keywords if k in row_str) >= 2:
                header_idx = i
                break
        
        if header_idx != -1:
            df_raw.columns = df_raw.iloc[header_idx]
            df_raw = df_raw.iloc[header_idx+1:].reset_index(drop=True)
        
        # [A] OTB 데이터 처리
        if is_otb:
            # 합계/소계 행 제거
            if '일자' in df_raw.columns:
                df_raw = df_raw[~df_raw['일자'].astype(str).str.contains('합계|Total|소계', na=False)]
            
            df = pd.DataFrame()
            
            # 날짜 (일자)
            date_col = next((c for c in df_raw.columns if any(k in str(c) for k in ['일자', 'Date', 'CheckIn'])), df_raw.columns[0])
            df['CheckIn'] = pd.to_datetime(df_raw[date_col], errors='coerce')
            
            # 매출 및 RN (파일 구조상 맨 오른쪽 끝이 합계)
            try:
                # 맨 마지막 열 = 총 매출
                df['Room_Revenue'] = pd.to_numeric(df_raw.iloc[:, -1], errors='coerce').fillna(0)
                # 뒤에서 5번째 열 = 총 객실수 (OTB 파일 구조 반영)
                df['RN'] = pd.to_numeric(df_raw.iloc[:, -5], errors='coerce').fillna(0)
                df['Total_Revenue'] = df['Room_Revenue']
            except:
                df['RN'] = 0; df['Room_Revenue'] = 0; df['Total_Revenue'] = 0
                
            df['Guest_Name']='OTB_DATA'; df['Segment']='OTB'; df['Account']='OTB'; df['Room_Type']='ROH'; df['Nat_Orig']='KR'
            df['Booking_Date']=df['CheckIn']; df['Lead_Time']=0; df['Breakfast']='Unknown'

        # [B] 일반 예약 데이터 처리
        else:
            df_raw = df_raw[~df_raw.iloc[:, 0].astype(str).str.contains('합계|Total', na=False)]
            df = normalize_and_map_columns(df_raw).copy()
            
            # 필수 컬럼 채우기
            req = ['Rooms','Nights','Room_Revenue','Total_Revenue','Guest_Name','Segment','Account','Room_Type','Nat_Orig','Lead_Time','Rate_Plan','Service_Code']
            for c in req:
                if c not in df.columns: df[c] = 0 if c in ['Rooms','Nights','Room_Revenue','Total_Revenue','Lead_Time'] else 'Unknown'
            
            # 숫자 변환
            for c in ['Room_Revenue','Total_Revenue','Rooms','Nights']:
                df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
                
            df['Total_Revenue'] = np.where(df['Total_Revenue']==0, df['Room_Revenue'], df['Total_Revenue'])
            df['RN'] = df['Rooms'] * df['Nights'].replace(0, 1)
            
            # 조식 식별 (BF, 조식, 패키지)
            def check_bf(row):
                text = (str(row.get('Service_Code','')) + str(row.get('Rate_Plan','')) + str(row.get('Room_Type',''))).upper()
                if any(k in text for k in ['BF', '조식', 'BREAKFAST', 'PKG', '패키지']): return 'Included'
                return 'Not Included'
            df['Breakfast'] = df.apply(check_bf, axis=1)

        # 공통 마무리
        df['Status'] = status
        df['Snapshot_Date'] = datetime.now().strftime('%Y-%m-%d')
        df['CheckIn_dt'] = pd.to_datetime(df['CheckIn'], errors='coerce')
        df['Booking_dt'] = pd.to_datetime(df['Booking_Date'], errors='coerce')
        df.loc[df['Booking_dt'].isna(), 'Booking_dt'] = df.loc[df['Booking_dt'].isna(), 'CheckIn_dt']
        
        df = df.dropna(subset=['CheckIn_dt'])
        df['Stay_Month'] = df['CheckIn_dt'].dt.strftime('%Y-%m')
        df['Booking_Month'] = df['Booking_dt'].dt.strftime('%Y-%m')
        df['Day_Type'] = df['CheckIn_dt'].dt.weekday.apply(lambda x: 'Weekend' if x>=4 else 'Weekday')
        
        def cls_nat(row):
            if re.search('[가-힣]', str(row.get('Guest_Name',''))): return 'KOR'
            if any(x in str(row.get('Nat_Orig','')).upper() for x in ['CHN','HKG']): return 'CHN'
            return 'OTH'
        df['Nat_Group'] = df.apply(cls_nat, axis=1)
        
        return clean_numeric_columns(df)
    except: return pd.DataFrame()
# ==============================================================================
# 5. UI 렌더링 헬퍼 함수들 (오류 수정 및 명칭 통일)
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
    if target_df.empty:
        st.warning(f"⚠️ {title_prefix} 데이터가 없습니다.")
        return

    t1, t2, t3, t4, t5, t6, t7, t8 = st.tabs(["📊 세그먼트", "📅 Pacing", "🏢 거래처", "⏳ 리드타임", "🛏️ 객실타입", "🗓️ 요일", "🌐 국적", "🍳 조식"])
    
    with t1:
        s = target_df.groupby('Segment').agg({'RN':'sum','Room_Revenue':'sum','Total_Revenue':'sum'}).reset_index()
        s['ADR_Room'] = np.where(s['RN']>0, s['Room_Revenue']/s['RN'], 0); s['ADR_Total'] = np.where(s['RN']>0, s['Total_Revenue']/s['RN'], 0)
        c1,c2=st.columns(2)
        c1.plotly_chart(px.pie(s, values='Room_Revenue', names='Segment'), use_container_width=True, key=f"{unique_key}_seg_pie")
        c2.plotly_chart(px.bar(s, x='Segment', y='Room_Revenue'), use_container_width=True, key=f"{unique_key}_seg_bar")
        show_dataframe_with_style(add_total_row(s, 'Segment'))
    with t2:
        p = target_df.pivot_table(index='Booking_Month', columns='Stay_Month', values='RN', aggfunc='sum').fillna(0)
        st.plotly_chart(px.imshow(p, text_auto="d", aspect="auto", color_continuous_scale=color_scale), use_container_width=True, key=f"{unique_key}_pacing")
    with t3:
        a = target_df.groupby('Account').agg({'RN':'sum','Room_Revenue':'sum','Total_Revenue':'sum'}).reset_index().sort_values('RN', ascending=False).head(50)
        a['ADR_Room'] = np.where(a['RN']>0, a['Room_Revenue']/a['RN'], 0); a['ADR_Total'] = np.where(a['RN']>0, a['Total_Revenue']/a['RN'], 0)
        show_dataframe_with_style(add_total_row(a, 'Account'))
    with t4:
        target_df['LG'] = pd.cut(target_df['Lead_Time'], [-1,0,3,7,14,30,60,90,999], labels=['0','1-3','4-7','8-14','15-30','31-60','61-90','90+'])
        l = target_df.groupby('LG').agg({'RN':'sum','Room_Revenue':'sum','Total_Revenue':'sum'}).reset_index()
        l['ADR_Room'] = np.where(l['RN']>0, l['Room_Revenue']/l['RN'], 0); l['ADR_Total'] = np.where(l['RN']>0, l['Total_Revenue']/l['RN'], 0)
        st.plotly_chart(px.bar(l, x='LG', y='RN'), use_container_width=True, key=f"{unique_key}_lead")
        show_dataframe_with_style(add_total_row(l, 'LG'))
    with t5:
        r = target_df.groupby('Room_Type').agg({'RN':'sum','Room_Revenue':'sum','Total_Revenue':'sum'}).reset_index()
        r['ADR_Room'] = np.where(r['RN']>0, r['Room_Revenue']/r['RN'], 0); r['ADR_Total'] = np.where(r['RN']>0, r['Total_Revenue']/r['RN'], 0)
        show_dataframe_with_style(add_total_row(r, 'Room_Type'))
    with t6:
        w = target_df.groupby('Day_Type').agg({'RN':'sum','Room_Revenue':'sum','Total_Revenue':'sum'}).reset_index()
        w['ADR_Room'] = np.where(w['RN']>0, w['Room_Revenue']/w['RN'], 0); w['ADR_Total'] = np.where(w['RN']>0, w['Total_Revenue']/w['RN'], 0)
        c1,c2=st.columns(2)
        c1.plotly_chart(px.bar(w, x='Day_Type', y='Room_Revenue'), use_container_width=True, key=f"{unique_key}_day_bar")
        c2.plotly_chart(px.pie(w, values='RN', names='Day_Type'), use_container_width=True, key=f"{unique_key}_day_pie")
        show_dataframe_with_style(add_total_row(w, 'Day_Type'))
    with t7: 
        if 'Nat_Group' in target_df.columns:
            n = target_df.groupby('Nat_Group').agg({'RN':'sum','Room_Revenue':'sum','Total_Revenue':'sum'}).reset_index()
            n['ADR_Room'] = np.where(n['RN']>0, n['Room_Revenue']/n['RN'], 0); n['ADR_Total'] = np.where(n['RN']>0, n['Total_Revenue']/n['RN'], 0)
            c1,c2=st.columns(2)
            c1.plotly_chart(px.pie(n, values='RN', names='Nat_Group'), use_container_width=True, key=f"{unique_key}_nat_pie")
            c2.plotly_chart(px.bar(n, x='Nat_Group', y='Room_Revenue'), use_container_width=True, key=f"{unique_key}_nat_bar")
            show_dataframe_with_style(add_total_row(n, 'Nat_Group'))
    with t8:
        if 'Breakfast' in target_df.columns:
            b = target_df.groupby('Breakfast').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index()
            b['ADR_Room'] = np.where(b['RN']>0, b['Room_Revenue']/b['RN'], 0)
            c1,c2=st.columns(2)
            c1.plotly_chart(px.pie(b, values='RN', names='Breakfast'), use_container_width=True, key=f"{unique_key}_bf_pie")
            c2.plotly_chart(px.bar(b, x='Breakfast', y='Room_Revenue'), use_container_width=True, key=f"{unique_key}_bf_bar")
            show_dataframe_with_style(add_total_row(b, 'Breakfast'))

# ==============================================================================
# UI 메인 실행부
# ==============================================================================
try:
    st.title("🏛️ 앰버 호텔 경영 리포트 (Final Integrity)")
    
    raw = load_data_from_firestore()
    df_all = pd.DataFrame(raw) if raw else pd.DataFrame()
    dates = sorted(df_all['Snapshot_Date'].unique(), reverse=True) if not df_all.empty else []

    with st.sidebar:
        st.header("📅 설정")
        if st.button("🗑️ OTB 데이터만 초기화"):
            cnt = delete_otb_data_only()
            st.warning(f"{cnt}건 삭제. 다시 업로드하세요."); time.sleep(1); st.cache_data.clear(); st.rerun()
        
        sel_date = st.selectbox("기준일", dates, index=0) if dates else None
        
        st.markdown("---")
        with st.expander("파일 업로드", expanded=True):
            f1=st.file_uploader("예약",type=['csv','xlsx']); 
            if f1 and st.button("예약 저장"):
                if save_to_firestore(process_data(f1,"Booked")): st.cache_data.clear(); st.rerun()
            f2=st.file_uploader("취소",type=['csv','xlsx']); 
            if f2 and st.button("취소 저장"):
                if save_to_firestore(process_data(f2,"Cancelled")): st.cache_data.clear(); st.rerun()
            f3=st.file_uploader("OTB (12개월)",type=['csv','xlsx'],accept_multiple_files=True)
            if f3 and st.button("OTB 저장"):
                dfs = []
                for f in f3: dfs.append(process_data(f,"Booked",force_otb=True))
                if dfs:
                    if save_to_firestore(pd.concat(dfs, ignore_index=True)):
                        st.success("통합 저장 완료!"); st.cache_data.clear(); st.rerun()

    if sel_date and not df_all.empty:
        df = clean_numeric_columns(df_all[df_all['Snapshot_Date']==sel_date].copy())
        if df.empty: st.warning("데이터 없음")
        else:
            df['CheckIn_dt'] = pd.to_datetime(df['CheckIn'], errors='coerce')
            df['Stay_Month'] = df['CheckIn_dt'].dt.strftime('%Y-%m')
            
            df_otb = df[df['Segment']=='OTB']; df_act = df[df['Segment']!='OTB']
            df_bk = df_act[(df_act['Status']=='Booked')&(df_act['Total_Revenue']>0)]
            df_cn = df_act[df_act['Status']=='Cancelled']; df_tot = pd.concat([df_bk, df_cn])

            tabs = st.tabs(["👑 GM 요약", "✅ 예약", "❌ 취소", "📈 종합", "🆓 0원", "🎯 OTB 현황"])

            with tabs[0]:
                st.header(f"👑 GM 요약 ({sel_date})")
                bk_r=df_bk['Room_Revenue'].sum(); bk_t=df_bk['Total_Revenue'].sum(); bk_rn=df_bk['RN'].sum()
                cn_r=df_cn['Room_Revenue'].sum(); cn_t=df_cn['Total_Revenue'].sum(); cn_rn=df_cn['RN'].sum()
                
                st.markdown("#### ✅ 예약"); c=st.columns(6)
                c[0].metric("건수",f"{len(df_bk):,.0f}"); c[1].metric("RN",f"{bk_rn:,.0f}"); c[2].metric("객실",f"{bk_r:,.0f}")
                c[3].metric("총매출",f"{bk_t:,.0f}"); c[4].metric("객실ADR",f"{bk_r/bk_rn if bk_rn>0 else 0:,.0f}"); c[5].metric("총ADR",f"{bk_t/bk_rn if bk_rn>0 else 0:,.0f}")
                
                st.markdown("#### ❌ 취소"); c=st.columns(6)
                c[0].metric("건수",f"{len(df_cn):,.0f}"); c[1].metric("RN",f"{cn_rn:,.0f}"); c[2].metric("객실",f"{cn_r:,.0f}")
                c[3].metric("총매출",f"{cn_t:,.0f}"); c[4].metric("객실ADR",f"{cn_r/cn_rn if cn_rn>0 else 0:,.0f}"); c[5].metric("총ADR",f"{cn_t/cn_rn if cn_rn>0 else 0:,.0f}")
                
                st.divider(); st.subheader("2. 세그먼트 (예약)")
                if not df_bk.empty:
                    s=df_bk.groupby('Segment').agg({'RN':'sum','Room_Revenue':'sum','Total_Revenue':'sum'}).reset_index()
                    s['ADR_Room']=np.where(s['RN']>0,s['Room_Revenue']/s['RN'],0); s['ADR_Total']=np.where(s['RN']>0,s['Total_Revenue']/s['RN'],0)
                    show_dataframe_with_style(add_total_row(s,'Segment'))
                
                c1,c2=st.columns(2)
                with c1: 
                    if 'Nat_Group' in df_bk.columns: st.plotly_chart(px.pie(df_bk.groupby('Nat_Group')['RN'].sum().reset_index(), values='RN', names='Nat_Group', title="국적"), use_container_width=True, key="gm_pie")
                with c2:
                    m = pd.concat([df_bk.assign(Type='예약'), df_cn.assign(Type='취소')]).groupby(['Stay_Month','Type'])['RN'].sum().reset_index()
                    if not m.empty: st.plotly_chart(px.bar(m, x='Stay_Month', y='RN', color='Type', barmode='group'), use_container_width=True, key="gm_bar")

            # Unique Key 추가하여 렌더링
            with tabs[1]: render_tab(df_bk, "bk")
            with tabs[2]: render_tab(df_cn, "cn")
            with tabs[3]: render_tab(df_tot, "tot")
            with tabs[4]: 
                st.subheader(f"🆓 0원 예약 ({len(df_act[(df_act['Status']=='Booked')&(df_act['Total_Revenue']<=0)])}건)")
                st.dataframe(df_act[(df_act['Status']=='Booked')&(df_act['Total_Revenue']<=0)][['Guest_Name','CheckIn','Account']], use_container_width=True)

            with tabs[5]:
                st.header("🎯 OTB 현황")
                if df_otb.empty: st.warning("⚠️ OTB 데이터 없음")
                else:
                    base = df_otb.copy(); base['M'] = base['CheckIn_dt'].dt.month
                    all_m = pd.DataFrame({'M': range(1, 13)})
                    grp = base.groupby('M').agg({'Room_Revenue':'sum'}).reset_index()
                    fin = pd.merge(all_m, grp, on='M', how='left').fillna(0)
                    
                    fin['Budget'] = fin['M'].map(BUDGET_DATA).fillna(0)
                    fin['OTB'] = fin['Room_Revenue']
                    fin['Rate'] = np.where(fin['Budget']>0, (fin['OTB']/fin['Budget'])*100, 0)
                    fin['Name'] = fin['M'].astype(str)+"월"
                    
                    tb = fin['Budget'].sum(); to = fin['OTB'].sum(); tr = (to/tb*100) if tb>0 else 0
                    
                    fig = go.Figure()
                    fig.add_trace(go.Bar(x=fin['Name'], y=fin['OTB'], name='OTB', marker_color='#2E86C1', text=fin['Rate'].apply(lambda x: f"{x:.1f}%"), textposition='outside'))
                    fig.add_trace(go.Scatter(x=fin['Name'], y=fin['Budget'], name='Budget', line=dict(color='red', dash='dot')))
                    fig.update_layout(height=500, margin=dict(t=50))
                    st.plotly_chart(fig, use_container_width=True, key="otb_chart")
                    
                    res = {}; 
                    for _, r in fin.iterrows(): res[r['Name']] = [f"{r['Budget']:,.0f}", f"{r['OTB']:,.0f}", f"{r['Rate']:.1f}%"]
                    res['합계 (Total)'] = [f"{tb:,.0f}", f"{to:,.0f}", f"{tr:.1f}%"]
                    tbl = pd.DataFrame(res, index=['Budget','OTB','달성률'])
                    st.dataframe(tbl.style.apply(lambda x: ['background-color:#fff9c4; font-weight:bold; border-left:2px solid black']*len(x) if x.name=='합계 (Total)' else ['']*len(x), axis=0), use_container_width=True)

    else: st.info("👈 파일 업로드 필요")
except Exception as e: st.error(f"오류: {e}")

    # ----------------------------------------------------------------------
    # 메인 대시보드
    # ----------------------------------------------------------------------
    if selected_date and not df_all.empty:
        # 선택된 날짜의 데이터만 필터링
        df_filtered = df_all[df_all['Snapshot_Date'] == selected_date].copy()
        
        # 숫자 컬럼 정리
        df = clean_numeric_columns(df_filtered)
        
        if df.empty:
            st.warning("해당 날짜에 데이터가 없습니다.")
        else:
            # 날짜형 데이터 변환 (안전장치)
            if 'Booking_Date' not in df.columns: df['Booking_Date'] = df['CheckIn']
            df['Booking_dt'] = pd.to_datetime(df['Booking_Date'], errors='coerce')
            df['CheckIn_dt'] = pd.to_datetime(df['CheckIn'], errors='coerce')
            
            # 유효한 날짜만 남김
            df = df.dropna(subset=['CheckIn_dt'])
            
            # Booking 날짜 없으면 CheckIn 날짜로 채움
            df.loc[df['Booking_dt'].isna(), 'Booking_dt'] = df.loc[df['Booking_dt'].isna(), 'CheckIn_dt']
            
            # 파생 변수 생성
            df['Is_Zero_Rate'] = df['Total_Revenue'] <= 0
            df['Booking_Month'] = df['Booking_dt'].dt.strftime('%Y-%m')
            df['Stay_Month'] = df['CheckIn_dt'].dt.strftime('%Y-%m')
            
            # 데이터 분리 (OTB vs 실적 데이터)
            df_otb = df[df['Segment'].astype(str).str.contains('OTB')]
            
            df_list = df[~df['Segment'].astype(str).str.contains('OTB')]
            df_paid_bk = df_list[(df_list['Status'] == 'Booked') & (df_list['Is_Zero_Rate'] == False)]
            df_list_cn = df_list[df_list['Status'] == 'Cancelled']
            
            # 종합 합계용 (예약+취소)
            df_total_paid = pd.concat([df_paid_bk, df_list_cn])

            # 탭 메뉴 구성
            main_tab0, main_tab1, main_tab2, main_tab3, main_tab4, main_tab5 = st.tabs([
                "👑 총지배인(GM) 요약", "✅ 예약 상세", "❌ 취소 상세", "📈 종합 합계", "🆓 0원 예약", "🎯 OTB 현황"
            ])

            # -----------------------------------------------------------
            # 1. GM 요약 탭
            # -----------------------------------------------------------
            with main_tab0:
                st.header(f"👑 총지배인(GM) 요약 리포트 ({selected_date})")
                st.subheader("1. 금일(Today) 예약 vs 취소")
                
                # 예약 지표 계산
                bk_cnt = len(df_paid_bk); bk_rn = df_paid_bk['RN'].sum()
                bk_room_rev = df_paid_bk['Room_Revenue'].sum(); bk_total_rev = df_paid_bk['Total_Revenue'].sum()
                bk_adr_room = bk_room_rev / bk_rn if bk_rn > 0 else 0
                bk_adr_total = bk_total_rev / bk_rn if bk_rn > 0 else 0
                
                # 취소 지표 계산
                cn_cnt = len(df_list_cn); cn_rn = df_list_cn['RN'].sum()
                cn_room_rev = df_list_cn['Room_Revenue'].sum(); cn_total_rev = df_list_cn['Total_Revenue'].sum()
                cn_adr_room = cn_room_rev / cn_rn if cn_rn > 0 else 0
                cn_adr_total = cn_total_rev / cn_rn if cn_rn > 0 else 0
                
                # 메트릭 표시
                st.markdown("#### ✅ 신규 예약")
                c1,c2,c3,c4,c5,c6=st.columns(6)
                c1.metric("예약건수",f"{bk_cnt:,.0f}"); c2.metric("예약RN",f"{bk_rn:,.0f}")
                c3.metric("객실매출",f"{bk_room_rev:,.0f}"); c4.metric("총매출",f"{bk_total_rev:,.0f}")
                c5.metric("객실ADR",f"{bk_adr_room:,.0f}"); c6.metric("총ADR",f"{bk_adr_total:,.0f}")
                
                st.markdown("#### ❌ 취소")
                c1,c2,c3,c4,c5,c6=st.columns(6)
                c1.metric("취소건수",f"{cn_cnt:,.0f}"); c2.metric("취소RN",f"{cn_rn:,.0f}")
                c3.metric("객실매출",f"{cn_room_rev:,.0f}"); c4.metric("총매출",f"{cn_total_rev:,.0f}")
                c5.metric("객실ADR",f"{cn_adr_room:,.0f}"); c6.metric("총ADR",f"{cn_adr_total:,.0f}")
                
                st.divider()
                st.subheader("2. 세그먼트별 픽업 현황")
                if not df_paid_bk.empty:
                    seg_gm = df_paid_bk.groupby('Segment').agg({'RN': 'sum','Room_Revenue': 'sum','Total_Revenue': 'sum'}).reset_index()
                    seg_gm['ADR_Room'] = np.where(seg_gm['RN']>0, seg_gm['Room_Revenue']/seg_gm['RN'], 0)
                    seg_gm['ADR_Total'] = np.where(seg_gm['RN']>0, seg_gm['Total_Revenue']/seg_gm['RN'], 0)
                    show_dataframe_with_style(add_total_row(seg_gm, 'Segment')) 
                else: st.info("예약 데이터 없음")
                
                st.divider()
                c_left, c_right = st.columns(2)
                with c_left:
                    st.subheader("3. 국적별 비중")
                    if 'Nat_Group' in df_paid_bk.columns and not df_paid_bk.empty:
                        nat_gm = df_paid_bk.groupby('Nat_Group')['RN'].sum().reset_index()
                        st.plotly_chart(px.pie(nat_gm, values='RN', names='Nat_Group', hole=0.4), use_container_width=True, key="gm_pie")
                    else: st.info("데이터 없음")
                with c_right:
                    st.subheader("4. 월별 예약/취소 추이")
                    bk_m = df_paid_bk.groupby('Stay_Month')['RN'].sum().reset_index(); bk_m['Type'] = '예약'
                    cn_m = df_list_cn.groupby('Stay_Month')['RN'].sum().reset_index(); cn_m['Type'] = '취소'
                    comb_m = pd.concat([bk_m, cn_m])
                    if not comb_m.empty: st.plotly_chart(px.bar(comb_m, x='Stay_Month', y='RN', color='Type', barmode='group'), use_container_width=True, key="gm_bar")
                    else: st.info("데이터 없음")

            # -----------------------------------------------------------
            # 상세 분석 탭
            # -----------------------------------------------------------
            with main_tab1: render_analysis_tab(df_paid_bk, "유료 예약", "bk", "Blues")
            with main_tab2: render_analysis_tab(df_list_cn, "취소 데이터", "cn", "Reds")
            with main_tab3: render_analysis_tab(df_total_paid, "종합(예약+취소)", "tot", "Greens")
            
            with main_tab4:
                df_zero_bk = df_list[(df_list['Status'] == 'Booked') & (df_list['Is_Zero_Rate'] == True)]
                st.subheader(f"🆓 0원 예약 (총 {len(df_zero_bk)}건)")
                st.dataframe(df_zero_bk[['Guest_Name', 'CheckIn', 'Account', 'Room_Type']], use_container_width=True)

            # -----------------------------------------------------------
            # 6. OTB 현황 (Budget vs OTB)
            # -----------------------------------------------------------
            with main_tab5:
                st.header("🎯 OTB 현황 (Budget vs OTB)")
                
                if df_otb.empty:
                    st.warning("⚠️ OTB 데이터가 없습니다. 사이드바에서 파일을 업로드해 주세요.")
                else:
                    all_months = pd.DataFrame({'M': range(1, 13)})
                    
                    base = df_otb.copy()
                    if 'CheckIn_dt' not in base.columns or base['CheckIn_dt'].isnull().all():
                        base['CheckIn_dt'] = pd.to_datetime(base['CheckIn'], errors='coerce')
                    
                    base['M'] = base['CheckIn_dt'].dt.month
                    otb_grp = base.groupby('M').agg({'Room_Revenue':'sum'}).reset_index()
                    
                    fin = pd.merge(all_months, otb_grp, on='M', how='left').fillna(0)
                    fin['Budget'] = fin['M'].map(BUDGET_DATA).fillna(0)
                    fin['OTB'] = fin['Room_Revenue']
                    fin['Rate'] = np.where(fin['Budget'] > 0, (fin['OTB'] / fin['Budget']) * 100, 0)
                    fin['Name'] = fin['M'].astype(str) + "월"
                    
                    tb = fin['Budget'].sum()
                    to = fin['OTB'].sum()
                    tr = (to / tb * 100) if tb > 0 else 0
                    
                    st.subheader("📊 월별 버짓 달성률 현황")
                    fig = go.Figure()
                    
                    fig.add_trace(go.Bar(
                        x=fin['Name'], 
                        y=fin['OTB'], 
                        name='OTB (현재)', 
                        marker_color='#2E86C1',
                        text=fin['Rate'].apply(lambda x: f"{x:.1f}%"), 
                        textposition='outside',
                        textfont=dict(size=14, weight='bold', color='black')
                    ))
                    
                    fig.add_trace(go.Scatter(
                        x=fin['Name'], 
                        y=fin['Budget'], 
                        name='Budget (목표)', 
                        line=dict(color='red', dash='dot', width=3)
                    ))
                    
                    fig.update_layout(height=550, yaxis_title="매출 (KRW)", margin=dict(t=50))
                    st.plotly_chart(fig, use_container_width=True, key="otb_chart")
                    
                    st.subheader("📋 실적 요약 (Budget vs OTB)")
                    
                    res_dict = {}
                    for _, r in fin.iterrows():
                        res_dict[r['Name']] = [f"{r['Budget']:,.0f}", f"{r['OTB']:,.0f}", f"{r['Rate']:.1f}%"]
                    
                    res_dict['합계 (Total)'] = [f"{tb:,.0f}", f"{to:,.0f}", f"{tr:.1f}%"]
                    
                    tbl_df = pd.DataFrame(res_dict, index=['Budget (목표)', 'OTB (현재)', '달성률 (%)'])
                    
                    def style_total_col(s):
                        if s.name == '합계 (Total)':
                            return ['background-color: #fff9c4; font-weight: bold; border-left: 2px solid black; color: black'] * len(s)
                        return [''] * len(s)

                    st.dataframe(tbl_df.style.apply(style_total_col, axis=0), use_container_width=True)

    else:
        st.info("👈 왼쪽 사이드바에서 파일을 업로드해주세요.")

except Exception as e:
    st.error(f"🚨 시스템 오류: {e}")
