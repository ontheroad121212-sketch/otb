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
# 0. 사용자 정의 버짓 데이터
# ==============================================================================
BUDGET_DATA = { 
    1: 514992575, 2: 786570856, 3: 529599040, 4: 695351004,
    5: 903705440, 6: 808203820, 7: 1231949142, 8: 1388376999,
    9: 952171506, 10: 897171539, 11: 667146771, 12: 804030110 
}

# ==============================================================================
# 1. 페이지 설정 및 CSS
# ==============================================================================
st.set_page_config(page_title="ARI Final Integrity", layout="wide", initial_sidebar_state="expanded")

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
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 2. 파이어베이스 연결
# ==============================================================================
if not firebase_admin._apps:
    try:
        cred = credentials.Certificate(dict(st.secrets["firebase"]))
        firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"🔥 DB 연결 실패: {e}"); st.stop()

db = firestore.client()
COLLECTION_NAME = "revenue_integrity_history"

# ==============================================================================
# 3. 데이터 관리 유틸리티
# ==============================================================================

def clean_numeric_columns(df):
    target_cols = ['RN', 'Room_Revenue', 'Total_Revenue', 'ADR_Room', 'ADR_Total', 'Lead_Time', 'Rooms', 'Nights']
    for col in target_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', '').str.replace('nan', '0').str.replace('₩', ''), errors='coerce').fillna(0)
    if 'RN' in df.columns:
        if 'Room_Revenue' in df.columns: df['ADR_Room'] = np.where(df['RN'] > 0, df['Room_Revenue'] / df['RN'], 0)
        if 'Total_Revenue' in df.columns: df['ADR_Total'] = np.where(df['RN'] > 0, df['Total_Revenue'] / df['RN'], 0)
    return df

def save_to_firestore(df):
    try:
        if df.empty: return False
        records = df.fillna(0).astype(str).to_dict(orient='records')
        db.collection(COLLECTION_NAME).add({'data': records, 'uploaded_at': datetime.now(), 'snapshot_date': datetime.now().strftime('%Y-%m-%d')})
        return True
    except: return False

@st.cache_data(ttl=0)
def load_data_from_firestore():
    try:
        docs = db.collection(COLLECTION_NAME).stream(); all_data = []
        for doc in docs:
            d = doc.to_dict()
            if 'data' in d:
                snap = d.get('snapshot_date', '')
                for r in d['data']:
                    if 'Snapshot_Date' not in r: r['Snapshot_Date'] = snap
                    all_data.append(r)
        return all_data
    except: return []

def delete_otb_data_only():
    try:
        docs = db.collection(COLLECTION_NAME).stream(); cnt = 0
        for doc in docs:
            d = doc.to_dict()
            if 'data' in d and any('OTB' in str(row.get('Segment', '')) for row in d['data']):
                doc.reference.delete(); cnt += 1
        return cnt
    except: return 0

# ==============================================================================
# 4. 파일 처리 (CSV cp949 인코딩 & 리드타임 좌표 추출)
# ==============================================================================

def normalize_columns(df):
    col_map = {}
    rules = {
        'CheckIn': ['checkin', 'arrival', '입실', '일자'],
        'Guest_Name': ['guest', 'name', '고객', '성명'],
        'Booking_Date': ['booking', 'create', '예약일', '생성'],
        'Rooms': ['room', 'qty', '객실수', '수량'],
        'Nights': ['night', 'los', '박수'],
        'Room_Revenue': ['room_rev', 'revenue', '객실료', '매출'],
        'Total_Revenue': ['total', 'amount', '총금액', '합계'],
        'Segment': ['segment', '세그먼트'],
        'Account': ['account', 'source', '거래처'],
        'Room_Type': ['type', 'cat', '객실타입'],
        'Nat_Orig': ['nation', 'country', '국적']
    }
    for col in df.columns:
        clean = str(col).lower().replace(" ", "")
        for target, kws in rules.items():
            if any(kw in clean for kw in kws):
                if target not in col_map.values(): col_map[col] = target; break
    return df.rename(columns=col_map)

def process_data(file, status, force_otb=False):
    try:
        is_otb = force_otb or "Sales on the Book" in file.name
        
        # 1. 파일 읽기 (CSV 한글 깨짐 방지 cp949)
        if file.name.endswith('.csv'):
            try: df_raw = pd.read_csv(file, header=None, encoding='cp949')
            except: df_raw = pd.read_csv(file, header=None) # utf-8 fallback
        else:
            df_raw = pd.read_excel(file, header=None)

        # [A] OTB 처리
        if is_otb:
            target_date = datetime.now()
            for r in range(min(15, len(df_raw))):
                row_str = " ".join(df_raw.iloc[r].astype(str).values)
                match = re.search(r'20\d{2}-(\d{2})', row_str)
                if match:
                    target_date = pd.to_datetime(f"2026-{match.group(1)}-01"); break
            
            df_clean = df_raw.dropna(how='all').dropna(axis=1, how='all')
            try: rev = int(str(df_clean.iloc[-1, -1]).replace(',', '').replace('nan', '0').split('.')[0])
            except: rev = 0
            
            return pd.DataFrame([{
                'CheckIn': target_date.strftime('%Y-%m-%d'),
                'Room_Revenue': rev, 'Total_Revenue': rev, 'RN': 0, 
                'Guest_Name': 'OTB_DATA', 'Segment': 'OTB', 'Status': 'Booked'
            }])
        
        # [B] 예약/취소 리스트 처리 (리드타임 해결)
        else:
            # 1. 헤더 행 찾기 ('리드타임' 글자가 있는 줄)
            header_idx = -1
            lt_col_idx = -1
            
            # 상위 10줄을 뒤져서 '리드타임'이 있는 행을 찾음
            for i, row in df_raw.head(10).iterrows():
                row_vals = row.astype(str).tolist()
                for j, val in enumerate(row_vals):
                    if '리드타임' in val or 'Lead' in val or 'LT' in val:
                        header_idx = i
                        lt_col_idx = j
                        break
                if header_idx != -1: break
            
            # 못 찾았으면 기본값 3행(Index 2)
            if header_idx == -1: header_idx = 2
            
            # 2. 데이터프레임 재구성
            df_data = df_raw.iloc[header_idx+1:].reset_index(drop=True)
            df_data.columns = df_raw.iloc[header_idx].astype(str).values
            
            # 3. [핵심] 리드타임 데이터 별도 추출 (인덱스로 바로 접근)
            if lt_col_idx != -1:
                # df_raw에서 직접 데이터를 가져옴 (헤더 다음 행부터)
                lead_time_raw = df_raw.iloc[header_idx+1:, lt_col_idx]
                lead_time_vals = pd.to_numeric(lead_time_raw.astype(str).str.replace(',', ''), errors='coerce').fillna(0)
            else:
                lead_time_vals = 0
            
            # 4. 조식 전수조사
            bf_series = df_data.apply(lambda r: 'Included (조식포함)' if 'BF' in "".join(r.astype(str).values).upper() else 'Not Included (불포함)', axis=1)
            
            # 5. 컬럼 매핑
            df = normalize_columns(df_data).copy()
            
            # 6. [핵심] 데이터 강제 주입
            df['Lead_Time'] = lead_time_vals.values if hasattr(lead_time_vals, 'values') else lead_time_vals
            df['Breakfast'] = bf_series
            df['Status'] = status
            
            # 7. 나머지 정리
            for c in ['Room_Revenue', 'Total_Revenue', 'Rooms', 'Nights']:
                if c in df.columns: df[c] = pd.to_numeric(df[c].astype(str).str.replace(',', '').str.replace('nan', '0'), errors='coerce').fillna(0)
            
            df['Total_Revenue'] = np.where(df.get('Total_Revenue', 0) == 0, df.get('Room_Revenue', 0), df.get('Total_Revenue', 0))
            df['RN'] = df.get('Rooms', 0) * df.get('Nights', 1).replace(0, 1)
            df['CheckIn_dt'] = pd.to_datetime(df['CheckIn'], errors='coerce')
            df = df.dropna(subset=['CheckIn_dt'])
            df['Stay_Month'] = df['CheckIn_dt'].dt.strftime('%Y-%m')
            df['Booking_Month'] = pd.to_datetime(df.get('Booking_Date', df['CheckIn']), errors='coerce').dt.strftime('%Y-%m')
            df['Day_Type'] = df['CheckIn_dt'].dt.weekday.apply(lambda x: 'Weekend' if x >= 4 else 'Weekday')
            df['Nat_Group'] = df.apply(lambda r: 'KOR' if re.search('[가-힣]', str(r.get('Guest_Name',''))) else 'OTH', axis=1)
            
            return clean_numeric_columns(df)

    except Exception as e:
        st.error(f"파일 처리 오류: {e}"); return pd.DataFrame()

# ==============================================================================
# 5. UI 렌더링
# ==============================================================================

def add_total(df, group_col="구분"):
    if df.empty: return df
    num_df = df.select_dtypes(include=[np.number]).fillna(0)
    totals = num_df.sum().to_dict(); row = {c: "" for c in df.columns}; row.update(totals)
    row[group_col if group_col in df.columns else df.columns[0]] = "TOTAL"
    if 'RN' in row and row['RN'] > 0:
        if 'Room_Revenue' in row: row['ADR_Room'] = row['Room_Revenue'] / row['RN']
        if 'Total_Revenue' in row: row['ADR_Total'] = row['Total_Revenue'] / row['RN']
    return pd.concat([df, pd.DataFrame([row])], ignore_index=True)

def style_df(df):
    if df.empty: st.write("데이터 없음"); return
    styler = df.style.format({c: "{:,.0f}" for c in df.select_dtypes(include=[np.number]).columns})
    st.dataframe(styler.apply(lambda r: ['background-color: #fff9c4; font-weight: 900; color: black; border-top: 2px solid black'] * len(r) if any(str(v) == "TOTAL" for v in r) else [''] * len(r), axis=1), hide_index=True, use_container_width=True)

def render_tabs(df, key):
    if df.empty: st.warning("데이터가 없습니다."); return
    t1, t2, t3, t4, t5, t6, t7, t8 = st.tabs(["📊 세그먼트", "📅 Pacing", "🏢 거래처", "⏳ 리드타임", "🛏️ 객실타입", "🗓️ 요일", "🌐 국적", "🍳 조식"])
    with t1:
        s = df.groupby('Segment').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.pie(s, values='Room_Revenue', names='Segment'), use_container_width=True, key=f"{key}_pie")
        c2.plotly_chart(px.bar(s, x='Segment', y='Room_Revenue'), use_container_width=True, key=f"{key}_bar")
        style_df(add_total(s, 'Segment'))
    with t2:
        piv = df.pivot_table(index='Booking_Month', columns='Stay_Month', values='RN', aggfunc='sum').fillna(0)
        st.plotly_chart(px.imshow(piv, text_auto="d", aspect="auto", color_continuous_scale="Blues"), use_container_width=True, key=f"{key}_pace")
    with t3:
        a = df.groupby('Account').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index().sort_values('RN', ascending=False).head(50)
        style_df(add_total(a, 'Account'))
    with t4:
        # 리드타임 차트
        bins = [-1, 0, 3, 7, 14, 30, 60, 90, 999]; labels = ['0일', '1-3일', '4-7일', '8-14일', '15-30일', '31-60일', '61-90일', '90일+']
        df['LT_G'] = pd.cut(df['Lead_Time'], bins=bins, labels=labels)
        l = df.groupby('LT_G', observed=True).agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
        st.plotly_chart(px.bar(l, x='LT_G', y='RN', title="리드타임별 건수"), use_container_width=True, key=f"{key}_lt")
        style_df(add_total(l, 'LT_G'))
    with t5: style_df(add_total(df.groupby('Room_Type').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index(), 'Room_Type'))
    with t6:
        w = df.groupby('Day_Type').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
        st.plotly_chart(px.bar(w, x='Day_Type', y='Room_Revenue'), use_container_width=True, key=f"{key}_wd")
    with t7: 
        if 'Nat_Group' in df.columns: style_df(add_total(df.groupby('Nat_Group').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index(), 'Nat_Group'))
    with t8:
        if 'Breakfast' in df.columns:
            b = df.groupby('Breakfast').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
            st.plotly_chart(px.pie(b, values='RN', names='Breakfast'), use_container_width=True, key=f"{key}_bf")
            style_df(add_total(b, 'Breakfast'))

# ==============================================================================
# 6. 메인 실행
# ==============================================================================
try:
    st.title("🏛️ 앰버 호텔 경영 리포트 (Final Integrity)")
    raw_data = load_data_from_firestore(); df_db = pd.DataFrame(raw_data) if raw_data else pd.DataFrame()
    dates = sorted(df_db['Snapshot_Date'].unique(), reverse=True) if not df_db.empty else []

    with st.sidebar:
        st.header("⚙️ 시스템 설정")
        if st.button("🗑️ OTB 데이터만 초기화"):
            c = delete_otb_data_only(); st.warning(f"OTB {c}건 삭제 완료"); time.sleep(1); st.cache_data.clear(); st.rerun()
        sel_date = st.selectbox("기준일", dates, index=0) if dates else None
        st.markdown("---")
        st.header("📤 데이터 업로드")
        f1 = st.file_uploader("예약 리스트", type=['xlsx','csv'], key="uf1")
        if f1 and st.button("예약 저장"):
            if save_to_firestore(process_data(f1, "Booked")): st.cache_data.clear(); st.rerun()
        f2 = st.file_uploader("취소 리스트", type=['xlsx','csv'], key="uf2")
        if f2 and st.button("취소 저장"):
            if save_to_firestore(process_data(f2, "Cancelled")): st.cache_data.clear(); st.rerun()
        f3_list = st.file_uploader("OTB 통합 업로드", type=['xlsx','csv'], key="uf3", accept_multiple_files=True)
        if f3_list and st.button("OTB 저장"):
            otb_all = [process_data(f, "Booked", force_otb=True) for f in f3_list]
            if otb_all and save_to_firestore(pd.concat(otb_all, ignore_index=True)): st.cache_data.clear(); st.rerun()

    if sel_date and not df_db.empty:
        df = clean_numeric_columns(df_db[df_db['Snapshot_Date'] == sel_date].copy())
        df_otb = df[df['Segment'].astype(str).str.contains('OTB')]
        df_bk = df[(~df['Segment'].astype(str).str.contains('OTB')) & (df['Status'] == 'Booked') & (df['Total_Revenue'] > 0)]
        df_cn = df[df['Status'] == 'Cancelled']

        tabs = st.tabs(["👑 GM 요약", "✅ 예약 상세", "❌ 취소 상세", "📈 종합 합계", "🎯 OTB 현황"])
        
        with tabs[0]:
            st.header(f"👑 GM 요약 ({sel_date})")
            b_rn, b_rev = df_bk['RN'].sum(), df_bk['Room_Revenue'].sum()
            c_rn, c_rev = df_cn['RN'].sum(), df_cn['Room_Revenue'].sum()
            # LOS 계산 (취소 포함)
            b_los = (b_rn / len(df_bk)) if len(df_bk) > 0 else 0
            c_los = (c_rn / len(df_cn)) if len(df_cn) > 0 else 0
            
            st.markdown("#### ✅ 신규 예약")
            c = st.columns(5); c[0].metric("RN", f"{b_rn:,.0f}"); c[1].metric("매출", f"{b_rev:,.0f}"); c[2].metric("ADR", f"{b_rev/b_rn if b_rn>0 else 0:,.0f}"); c[3].metric("LOS", f"{b_los:.1f}박"); c[4].metric("건수", f"{len(df_bk):,.0f}")
            
            st.markdown("#### ❌ 금일 취소")
            cc = st.columns(5); cc[0].metric("RN", f"{c_rn:,.0f}"); cc[1].metric("매출", f"{c_rev:,.0f}"); cc[2].metric("ADR", f"{c_rev/c_rn if c_rn>0 else 0:,.0f}"); cc[3].metric("LOS", f"{c_los:.1f}박"); cc[4].metric("건수", f"{len(df_cn):,.0f}")
            st.divider(); style_df(add_total(df_bk.groupby('Segment').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index(), 'Segment'))
            
        with tabs[1]: render_tabs(df_bk, "bk")
        with tabs[2]: render_tabs(df_cn, "cn")
        with tabs[3]: render_tabs(pd.concat([df_bk, df_cn]), "tot")
        with tabs[4]:
            if df_otb.empty: st.warning("OTB 없음")
            else:
                df_otb['M'] = pd.to_datetime(df_otb['CheckIn']).dt.month
                fin = pd.merge(pd.DataFrame({'M':range(1,13)}), df_otb.groupby('M').agg({'Room_Revenue':'sum'}).reset_index(), on='M', how='left').fillna(0)
                fin['Budget'] = fin['M'].map(BUDGET_DATA).fillna(0)
                fig = go.Figure()
                fig.add_trace(go.Bar(x=fin['M'], y=fin['Room_Revenue'], name='OTB', text=(fin['Room_Revenue']/fin['Budget']*100).apply(lambda x: f"{x:.1f}%"), textposition='outside'))
                fig.add_trace(go.Scatter(x=fin['M'], y=fin['Budget'], name='Budget', line=dict(color='red', dash='dot')))
                st.plotly_chart(fig, use_container_width=True)
                
    else: st.info("👈 파일을 업로드하세요.")
    
except Exception as e: st.error(f"🚨 시스템 오류: {e}")
