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
        font-weight: 900 !important; background-color: #fff9c4 !important; color: black; border-top: 2px solid black;
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
        'Lead_Time', 'OTB_Rev', 'Budget_Rev', 'OTB_RN'
    ]
    for col in target_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(
                df[col].astype(str).str.replace(',', '').str.replace('nan', '0'), 
                errors='coerce'
            ).fillna(0)
            
    if 'RN' in df.columns:
        if 'Room_Revenue' in df.columns:
            df['ADR_Room'] = np.where(df['RN'] > 0, df['Room_Revenue'] / df['RN'], 0)
        if 'Total_Revenue' in df.columns:
            df['ADR_Total'] = np.where(df['RN'] > 0, df['Total_Revenue'] / df['RN'], 0)
    return df

def save_to_firestore(df):
    try:
        if df.empty: return False
        records = df.fillna(0).astype(str).to_dict(orient='records')
        db.collection(COLLECTION_NAME).add({
            'data': records,
            'uploaded_at': datetime.now(),
            'snapshot_date': datetime.now().strftime('%Y-%m-%d')
        })
        return True
    except: return False

@st.cache_data(ttl=0)
def load_data_from_firestore():
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
    except: return []

def delete_otb_data_only():
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
    except: return 0

# ==============================================================================
# 4. 엑셀/CSV 파일 처리 및 매핑 로직 (OTB 및 조식 BF 로직)
# ==============================================================================

def normalize_and_map_columns(df):
    col_map = {}
    rules = {
        'CheckIn': ['checkin', 'arrival', '입실', '일자', 'date'],
        'Guest_Name': ['guest', 'name', 'customer', '고객', '투숙객', '성명'],
        'Booking_Date': ['booking', 'create', 'res', '예약', '생성'],
        'Rooms': ['room', 'qty', 'rmws', '객실수', '수량'],
        'Nights': ['night', 'los', '박수', '박'],
        'Room_Revenue': ['room_rev', 'revenue', 'roomrate', '객실료', '매출'],
        'Total_Revenue': ['total', 'amount', '총금액', '합계'],
        'Segment': ['segment', '세그먼트'],
        'Account': ['account', 'source', 'agent', '거래처', '에이전시'],
        'Room_Type': ['type', 'cat', '객실타입', '룸타입'],
        'Rate_Plan': ['rate', 'plan', '상품', '패키지'], 
        'Nat_Orig': ['nation', 'country', 'nat', '국적'],
        'Lead_Time': ['lead', '리드', 'lt']
    }

    for original_col in df.columns:
        clean_col = str(original_col).lower().replace(" ", "").replace("_", "")
        mapped = False
        for target_col, keywords in rules.items():
            for kw in keywords:
                if kw in clean_col:
                    if target_col == 'Room_Revenue' and 'total' in clean_col: continue
                    if target_col == 'Total_Revenue' and 'room' in clean_col: continue
                    if target_col not in col_map.values():
                        col_map[original_col] = target_col
                        mapped = True; break
            if mapped: break
    return df.rename(columns=col_map)

def process_data(file, status, force_otb=False):
    try:
        is_otb = force_otb or "Sales on the Book" in file.name
        if file.name.endswith('.csv'):
            try: df_raw = pd.read_csv(file, header=None)
            except: df_raw = pd.read_csv(file, header=None, encoding='cp949')
        else: df_raw = pd.read_excel(file, header=None)

        # ---------------------------------------------------------
        # [A] OTB 데이터 처리 (가장 마지막 열과 행의 셀 값 가져오기)
        # ---------------------------------------------------------
        if is_otb:
            # 1. 파일 내용에서 월(Month) 정보를 찾음
            found_month = datetime.now().month
            for r in range(min(15, len(df_raw))):
                row_str = " ".join(df_raw.iloc[r].astype(str).values)
                match = re.search(r'20\d{2}-(\d{2})', row_str)
                if match:
                    found_month = int(match.group(1))
                    break
            
            # 2. 마지막 행/열 값 추출 (매출)
            df_clean = df_raw.dropna(how='all').dropna(axis=1, how='all')
            try:
                raw_rev = str(df_clean.iloc[-1, -1])
                total_rev = float(raw_rev.replace(',', '').replace('nan', '0'))
                
                # RN은 뒤에서 5번째 열
                raw_rn = str(df_clean.iloc[-1, -5])
                total_rn = float(raw_rn.replace(',', '').replace('nan', '0'))
            except:
                total_rev = 0; total_rn = 0

            # 1개 행으로 구성된 요약 데이터프레임 생성
            return pd.DataFrame([{
                'CheckIn': f"2026-{found_month:02d}-01",
                'Room_Revenue': total_rev,
                'Total_Revenue': total_rev,
                'RN': total_rn,
                'Guest_Name': 'OTB_SUMMARY',
                'Segment': 'OTB',
                'Account': 'OTB_DATA',
                'Room_Type': 'ROH',
                'Nat_Orig': 'KR',
                'Booking_Date': datetime.now().strftime('%Y-%m-%d'),
                'Lead_Time': 0,
                'Breakfast': 'Unknown',
                'Status': 'Booked',
                'Snapshot_Date': datetime.now().strftime('%Y-%m-%d')
            }])

        # ---------------------------------------------------------
        # [B] 일반 데이터 처리 (K열 BF 확인)
        # ---------------------------------------------------------
        header_idx = -1
        for i, row in df_raw.head(20).iterrows():
            if sum(1 for k in ['예약번호', '고객명', '입실일자'] if k in str(row.values)) >= 2:
                header_idx = i; break
        
        if header_idx != -1:
            # K열이 서비스코드이므로, K열(10번 인덱스)의 이름을 확보
            headers = df_raw.iloc[header_idx].values
            df = df_raw.iloc[header_idx+1:].reset_index(drop=True)
            df.columns = headers
            
            # K열(인덱스 10) 강제 지정
            service_col_name = df.columns[10] if len(df.columns) > 10 else "Service_Code"
            
            # 컬럼 매핑
            df = normalize_and_map_columns(df).copy()
            
            # 조식 분류 (K열에 BF가 포함되면 조식)
            def check_bf(row):
                val = str(row.get(service_col_name, '')).upper()
                return 'Included' if 'BF' in val else 'Room Only'
            
            df['Breakfast'] = df.apply(check_bf, axis=1)
            
            # 숫자 처리
            for c in ['Room_Revenue', 'Total_Revenue', 'Rooms', 'Nights', 'Lead_Time']:
                if c in df.columns:
                    df[c] = pd.to_numeric(df[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
                else:
                    df[c] = 0
            
            df['Total_Revenue'] = np.where(df['Total_Revenue']==0, df['Room_Revenue'], df['Total_Revenue'])
            df['RN'] = df.get('Rooms', 0) * df.get('Nights', 1).replace(0, 1)
            df['Status'] = status
            df['Snapshot_Date'] = datetime.now().strftime('%Y-%m-%d')
            df['CheckIn_dt'] = pd.to_datetime(df['CheckIn'], errors='coerce')
            df = df.dropna(subset=['CheckIn_dt'])
            df['Stay_Month'] = df['CheckIn_dt'].dt.strftime('%Y-%m')
            
            def cls_nat(row):
                if re.search('[가-힣]', str(row.get('Guest_Name',''))): return 'KOR'
                return 'OTH'
            df['Nat_Group'] = df.apply(cls_nat, axis=1)
            
            return clean_numeric_columns(df)
            
    except Exception as e:
        return pd.DataFrame()

# ==============================================================================
# 5. UI 렌더링 함수
# ==============================================================================

def add_total_row(df, group_col_name="구분"):
    if df.empty: return df
    numeric_cols = df.select_dtypes(include=[np.number]).columns
    totals = df[numeric_cols].sum().to_dict()
    total_row = {col: "" for col in df.columns}
    total_row.update(totals)
    
    if group_col_name in df.columns:
        total_row[group_col_name] = "TOTAL"
    else:
        total_row[df.columns[0]] = "TOTAL"

    if 'RN' in total_row and total_row['RN'] > 0:
        if 'Room_Revenue' in total_row: total_row['ADR_Room'] = total_row['Room_Revenue'] / total_row['RN']
        if 'Total_Revenue' in total_row: total_row['ADR_Total'] = total_row['Total_Revenue'] / total_row['RN']
            
    return pd.concat([df, pd.DataFrame([total_row])], ignore_index=True)

def show_dataframe_with_style(df):
    if df.empty: st.write("No Data"); return
    num_cols = df.select_dtypes(include=[np.number]).columns
    styler = df.style.format({c: "{:,.0f}" for c in num_cols})
    
    def highlight(row):
        is_total = any(str(v) == "TOTAL" for v in row)
        return ['background-color: #fff9c4; font-weight: 900; color: black'] * len(row) if is_total else [''] * len(row)
    
    st.dataframe(styler.apply(highlight, axis=1), hide_index=True, use_container_width=True)

def render_analysis_tab(df, prefix, key):
    if df.empty: st.warning("데이터가 없습니다."); return
    t = st.tabs(["세그먼트", "Pacing", "거래처", "요일", "조식"])
    
    with t[0]:
        s = df.groupby('Segment').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index()
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.pie(s, values='Room_Revenue', names='Segment'), use_container_width=True, key=f"{key}_pie")
        c2.plotly_chart(px.bar(s, x='Segment', y='Room_Revenue'), use_container_width=True, key=f"{key}_bar")
        show_dataframe_with_style(add_total_row(s, 'Segment'))
    
    with t[1]:
        piv = df.pivot_table(index='Snapshot_Date', columns='Stay_Month', values='RN', aggfunc='sum').fillna(0)
        st.plotly_chart(px.imshow(piv, text_auto=True), use_container_width=True, key=f"{key}_pacing")
        
    with t[2]:
        a = df.groupby('Account').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index().sort_values('RN', ascending=False).head(30)
        show_dataframe_with_style(add_total_row(a, 'Account'))
        
    with t[3]:
        df['Day'] = pd.to_datetime(df['CheckIn']).dt.day_name()
        w = df.groupby('Day').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index()
        st.plotly_chart(px.bar(w, x='Day', y='Room_Revenue'), use_container_width=True, key=f"{key}_day")
        
    with t[4]:
        if 'Breakfast' in df.columns:
            b = df.groupby('Breakfast').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index()
            c1, c2 = st.columns(2)
            c1.plotly_chart(px.pie(b, values='RN', names='Breakfast', title="조식 비중"), use_container_width=True, key=f"{key}_bf_pie")
            c2.plotly_chart(px.bar(b, x='Breakfast', y='Room_Revenue'), use_container_width=True, key=f"{key}_bf_bar")
            show_dataframe_with_style(add_total_row(b, 'Breakfast'))

# ==============================================================================
# 6. 메인 실행부
# ==============================================================================
try:
    st.title("🏛️ 앰버 호텔 경영 리포트 (Final Integrity)")
    raw = load_data_from_firestore()
    df_all = pd.DataFrame(raw) if raw else pd.DataFrame()
    dates = sorted(df_all['Snapshot_Date'].unique(), reverse=True) if not df_all.empty else []

    with st.sidebar:
        st.header("📅 설정")
        if st.button("🗑️ OTB 초기화"):
            cnt = delete_otb_data_only()
            st.warning(f"{cnt}건 삭제됨."); time.sleep(1); st.cache_data.clear(); st.rerun()
        
        selected_date = st.selectbox("조회 기준일", dates, index=0) if dates else None
        st.markdown("---")
        with st.expander("데이터 업로드", expanded=True):
            f1 = st.file_uploader("예약 리스트", type=['xlsx','csv'])
            if f1 and st.button("예약 저장"):
                if save_to_firestore(process_data(f1, "Booked")): st.cache_data.clear(); st.rerun()
            
            f2 = st.file_uploader("취소 리스트", type=['xlsx','csv'])
            if f2 and st.button("취소 저장"):
                if save_to_firestore(process_data(f2, "Cancelled")): st.cache_data.clear(); st.rerun()
            
            f3 = st.file_uploader("OTB (12개월)", type=['xlsx','csv'], accept_multiple_files=True)
            if f3 and st.button("OTB 저장"):
                otb_list = [process_data(f, "Booked", force_otb=True) for f in f3]
                if otb_list:
                    if save_to_firestore(pd.concat(otb_list, ignore_index=True)):
                        st.success("OTB 저장 성공"); st.cache_data.clear(); st.rerun()

    if selected_date and not df_all.empty:
        df = clean_numeric_columns(df_all[df_all['Snapshot_Date'] == selected_date].copy())
        df_otb = df[df['Segment'] == 'OTB']
        df_act = df[df['Segment'] != 'OTB']
        df_bk = df_act[df_act['Status'] == 'Booked']
        df_cn = df_act[df_act['Status'] == 'Cancelled']
        df_tot = pd.concat([df_bk, df_cn])

        main_tabs = st.tabs(["👑 GM 요약", "✅ 예약 상세", "❌ 취소 상세", "📈 종합 합계", "🎯 OTB 현황"])

        with main_tabs[0]:
            st.header(f"👑 GM 요약 ({selected_date})")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("예약 RN", f"{df_bk['RN'].sum():,.0f}")
            c2.metric("예약 매출", f"{df_bk['Room_Revenue'].sum():,.0f}")
            c3.metric("취소 RN", f"{df_cn['RN'].sum():,.0f}")
            c4.metric("취소 매출", f"{df_cn['Room_Revenue'].sum():,.0f}")
            st.divider()
            show_dataframe_with_style(add_total_row(df_bk.groupby('Segment').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index(), 'Segment'))

        with main_tabs[1]: render_analysis_tab(df_bk, "예약", "bk_unique")
        with main_tabs[2]: render_analysis_tab(df_cn, "취소", "cn_unique")
        with main_tabs[3]: render_analysis_tab(df_tot, "종합", "tot_unique")

        with main_tabs[4]:
            st.header("🎯 OTB 현황 (Budget vs OTB)")
            if df_otb.empty: st.info("OTB 데이터가 없습니다.")
            else:
                # 월별 집계
                df_otb['M'] = pd.to_datetime(df_otb['CheckIn']).dt.month
                grp = df_otb.groupby('M').agg({'Room_Revenue':'sum'}).reset_index()
                fin = pd.merge(pd.DataFrame({'M': range(1,13)}), grp, on='M', how='left').fillna(0)
                fin['Budget'] = fin['M'].map(BUDGET_DATA)
                fin['Rate'] = np.where(fin['Budget']>0, fin['Room_Revenue']/fin['Budget']*100, 0)
                
                fig = go.Figure()
                fig.add_trace(go.Bar(x=fin['M'], y=fin['Room_Revenue'], name='OTB', text=fin['Rate'].apply(lambda x: f"{x:.1f}%"), textposition='outside'))
                fig.add_trace(go.Scatter(x=fin['M'], y=fin['Budget'], name='Budget', line=dict(color='red', dash='dot')))
                st.plotly_chart(fig, use_container_width=True, key="otb_chart_final")
                
                res = {}
                for _, r in fin.iterrows():
                    res[f"{int(r['M'])}월"] = [f"{r['Budget']:,.0f}", f"{r['Room_Revenue']:,.0f}", f"{r['Rate']:.1f}%"]
                st.table(pd.DataFrame(res, index=['Budget','OTB','달성률']))

    else: st.info("사이드바에서 데이터를 업로드하세요.")
except Exception as e: st.error(f"🚨 오류 발생: {e}")
