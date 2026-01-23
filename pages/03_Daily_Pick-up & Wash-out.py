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
# 0. 설정 및 예산 데이터
# ==============================================================================
st.set_page_config(page_title="ARI Final Integrity", layout="wide")

BUDGET_DATA = { 
    1: 514992575, 2: 786570856, 3: 529599040, 4: 695351004,
    5: 903705440, 6: 808203820, 7: 1231949142, 8: 1388376999,
    9: 952171506, 10: 897171539, 11: 667146771, 12: 804030110 
}

st.markdown("""
<style>
    .block-container { padding-top: 1rem; padding-bottom: 5rem; }
    div[data-testid="stMetricValue"] { font-size: 26px !important; font-weight: 900; color: #0f172a; }
    div[data-testid="stMetricLabel"] { font-size: 15px !important; font-weight: 700; color: #64748b; }
    [data-testid="stDataFrame"] table tr:last-child td {
        font-weight: 900 !important; background-color: #fff9c4 !important; color: black; border-top: 2px solid black;
    }
    div.stButton > button:first-child { border-color: #ff4b4b; color: #ff4b4b; }
    div.stButton > button:first-child:hover { background-color: #ff4b4b; color: white; }
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
        st.error(f"DB 연결 실패: {e}")
        st.stop()

db = firestore.client()
COLLECTION_NAME = "revenue_integrity_history"

# ==============================================================================
# 2. 데이터 관리 함수
# ==============================================================================

def clean_numeric_columns(df):
    target_cols = ['RN', 'Room_Revenue', 'Total_Revenue', 'ADR_Room', 'ADR_Total', 'Lead_Time', 'OTB_Rev', 'Budget_Rev', 'OTB_RN']
    for col in target_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', '').str.replace('nan', '0'), errors='coerce').fillna(0)
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
            'data': records, 'uploaded_at': datetime.now(), 'snapshot_date': datetime.now().strftime('%Y-%m-%d')
        })
        return True
    except: return False

@st.cache_data(ttl=0)
def load_data_from_firestore():
    try:
        docs = db.collection(COLLECTION_NAME).stream()
        all_data = []
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
        docs = db.collection(COLLECTION_NAME).stream()
        cnt = 0
        for doc in docs:
            d = doc.to_dict()
            if 'data' in d and len(d['data']) > 0:
                first = d['data'][0]
                if 'OTB' in str(first.get('Segment','')) or 'OTB' in str(first.get('Guest_Name','')):
                    doc.reference.delete()
                    cnt += 1
        return cnt
    except: return 0

# ==============================================================================
# 3. 엑셀 파일 처리 로직 (OTB 마지막 열 추출, K열 조식 확인)
# ==============================================================================

def normalize_and_map_columns(df):
    col_map = {}
    rules = {
        'CheckIn': ['checkin', 'arrival', '입실', '일자', 'date'],
        'Guest_Name': ['guest', 'name', '고객', '성명'],
        'Booking_Date': ['booking', 'create', '예약', '생성'],
        'Rooms': ['room', 'qty', '객실수', '수량'],
        'Nights': ['night', 'los', '박수', '박'],
        'Room_Revenue': ['room_rev', 'revenue', '객실료', '매출'],
        'Total_Revenue': ['total', 'amount', '총금액', '합계'],
        'Segment': ['segment', '세그먼트'],
        'Account': ['account', 'agent', '거래처'],
        'Room_Type': ['type', 'cat', '객실타입'],
        'Rate_Plan': ['rate', 'plan', '상품', '패키지'], 
        'Service_Code': ['service', '서비스', 'code'], 
        'Nat_Orig': ['nation', 'country', '국적'],
        'Lead_Time': ['lead', '리드', 'lt']
    }
    for col in df.columns:
        clean = str(col).lower().replace(" ", "").replace("_", "")
        for key, kws in rules.items():
            if any(k in clean for k in kws):
                if key == 'Room_Revenue' and 'total' in clean: continue
                if key == 'Total_Revenue' and 'room' in clean: continue
                if key == 'CheckIn' and ('book' in clean or 'res' in clean): continue
                if key not in col_map.values():
                    col_map[col] = key; break
    return df.rename(columns=col_map)

def process_data(file, status, force_otb=False):
    try:
        is_otb = force_otb or "Sales on the Book" in file.name
        if file.name.endswith('.csv'):
            try: df_raw = pd.read_csv(file, header=None)
            except: df_raw = pd.read_csv(file, header=None, encoding='cp949')
        else: df_raw = pd.read_excel(file, header=None)

        # [A] OTB 처리: 마지막 행/열 값 가져오기
        if is_otb:
            target_month_date = datetime.now()
            # 월 파악
            for r in range(10):
                row_vals = df_raw.iloc[r].astype(str).values
                for v in row_vals:
                    match = re.search(r'20\d{2}-(\d{2})', v)
                    if match:
                        try: target_month_date = pd.to_datetime(match.group() + "-01"); break
                        except: pass
                if target_month_date.month != datetime.now().month: break
            
            # 마지막 값 추출
            df_clean = df_raw.dropna(how='all').dropna(axis=1, how='all')
            try:
                # 맨 마지막 열이 총매출
                total_rev = float(str(df_clean.iloc[-1, -1]).replace(',', '').replace('nan', '0'))
                # 뒤에서 5번째 열이 RN
                total_rn = float(str(df_clean.iloc[-1, -5]).replace(',', '').replace('nan', '0'))
            except: total_rev = 0; total_rn = 0

            return pd.DataFrame([{
                'CheckIn': target_month_date.strftime('%Y-%m-%d'),
                'Room_Revenue': total_rev, 'Total_Revenue': total_rev, 'RN': total_rn,
                'Guest_Name': 'OTB', 'Segment': 'OTB', 'Account': 'OTB', 'Room_Type': 'ROH',
                'Nat_Orig': 'KR', 'Booking_Date': target_month_date.strftime('%Y-%m-%d'),
                'Lead_Time': 0, 'Breakfast': 'Unknown', 'Status': 'Booked', 'Snapshot_Date': datetime.now().strftime('%Y-%m-%d')
            }])

        # [B] 일반 예약 처리
        header_idx = -1
        for i, row in df_raw.head(20).iterrows():
            if sum(1 for k in ['예약번호', '고객명', '입실일자'] if k in str(row.values)) >= 2:
                header_idx = i; break
        
        if header_idx != -1:
            headers = df_raw.iloc[header_idx].values
            df = df_raw.iloc[header_idx+1:].reset_index(drop=True)
            df.columns = headers
            
            # K열(10번 인덱스)을 서비스코드로 강제 지정
            svc_col_name = df.columns[10] if len(df.columns) > 10 else "Service_Code"
            df['Service_Code_Raw'] = df[svc_col_name]
            
            df = normalize_and_map_columns(df).copy()
            
            # 조식 식별 (K열 'BF' 포함 여부)
            def check_bf(row):
                # 매핑된 Service_Code 혹은 원본 K열 참조
                val1 = str(row.get('Service_Code', '')).upper()
                val2 = str(row.get('Service_Code_Raw', '')).upper()
                if 'BF' in val1 or 'BF' in val2: return 'Included'
                return 'Room Only'
            df['Breakfast'] = df.apply(check_bf, axis=1)
            
            for c in ['Room_Revenue', 'Total_Revenue', 'Rooms', 'Nights']:
                if c in df.columns: df[c] = pd.to_numeric(df[c].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
                else: df[c] = 0
            
            df['Total_Revenue'] = np.where(df['Total_Revenue']==0, df['Room_Revenue'], df['Total_Revenue'])
            df['RN'] = df['Rooms'] * df['Nights'].replace(0, 1)
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
    except: return pd.DataFrame()

# ==============================================================================
# 4. UI 헬퍼 함수
# ==============================================================================

def add_total(df, grp):
    if df.empty: return df
    total = df.select_dtypes(include=[np.number]).sum().to_dict()
    row = {c: "" for c in df.columns}; row.update(total); row[grp]="TOTAL"
    if 'RN' in row and row['RN'] > 0:
        if 'Room_Revenue' in row: row['ADR_Room'] = row['Room_Revenue'] / row['RN']
        if 'Total_Revenue' in row: row['ADR_Total'] = row['Total_Revenue'] / row['RN']
    return pd.concat([df, pd.DataFrame([row])], ignore_index=True)

def style_df(df):
    """(이전 show_dataframe_with_style 대체)"""
    if df.empty: st.write("데이터 없음"); return
    fmt = {c: "{:,.0f}" for c in df.select_dtypes(include=[np.number]).columns}
    def highlight(row):
        is_total = any(str(v) == "TOTAL" for v in row)
        return ['background-color: #fff9c4; font-weight: 900; color: black'] * len(row) if is_total else [''] * len(row)
    st.dataframe(df.style.format(fmt).apply(highlight, axis=1), hide_index=True, use_container_width=True)

def render_tab(df, key_prefix):
    if df.empty: st.warning("데이터 없음"); return
    t = st.tabs(["세그먼트", "Pacing", "거래처", "요일", "조식"])
    
    with t[0]:
        s = df.groupby('Segment').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index()
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.pie(s, values='Room_Revenue', names='Segment'), use_container_width=True, key=f"{key_prefix}_pie")
        c2.plotly_chart(px.bar(s, x='Segment', y='Room_Revenue'), use_container_width=True, key=f"{key_prefix}_bar")
        style_df(add_total(s, 'Segment'))
    
    with t[1]:
        piv = df.pivot_table(index='Snapshot_Date', columns='Stay_Month', values='RN', aggfunc='sum').fillna(0)
        st.plotly_chart(px.imshow(piv, text_auto=True), use_container_width=True, key=f"{key_prefix}_pacing")
        
    with t[2]:
        a = df.groupby('Account').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index().sort_values('RN', ascending=False).head(30)
        style_df(add_total(a, 'Account'))
        
    with t[3]:
        df['Day'] = pd.to_datetime(df['CheckIn']).dt.day_name()
        w = df.groupby('Day').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index()
        st.plotly_chart(px.bar(w, x='Day', y='Room_Revenue'), use_container_width=True, key=f"{key_prefix}_day")
        
    with t[4]:
        if 'Breakfast' in df.columns:
            b = df.groupby('Breakfast').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index()
            c1, c2 = st.columns(2)
            c1.plotly_chart(px.pie(b, values='RN', names='Breakfast', title="조식 비중"), use_container_width=True, key=f"{key_prefix}_bf_pie")
            c2.plotly_chart(px.bar(b, x='Breakfast', y='Room_Revenue'), use_container_width=True, key=f"{key_prefix}_bf_bar")
            style_df(add_total(b, 'Breakfast'))

# ==============================================================================
# 5. 메인 실행부
# ==============================================================================
try:
    st.title("🏛️ 앰버 호텔 경영 리포트 (Final Integrity)")
    raw = load_data_from_firestore(); df_all = pd.DataFrame(raw) if raw else pd.DataFrame()
    dates = sorted(df_all['Snapshot_Date'].unique(), reverse=True) if not df_all.empty else []

    with st.sidebar:
        st.header("📅 설정")
        if st.button("🗑️ OTB 데이터만 초기화"):
            cnt = delete_otb_data_only(); st.warning(f"{cnt}건 삭제."); time.sleep(1); st.cache_data.clear(); st.rerun()
        sel_date = st.selectbox("기준일", dates, index=0) if dates else None
        st.markdown("---")
        with st.expander("파일 업로드", expanded=True):
            f1=st.file_uploader("예약", type=['csv','xlsx'])
            if f1 and st.button("예약 저장"):
                if save_to_firestore(process_data(f1, "Booked")): st.cache_data.clear(); st.rerun()
            f2=st.file_uploader("취소", type=['csv','xlsx'])
            if f2 and st.button("취소 저장"):
                if save_to_firestore(process_data(f2, "Cancelled")): st.cache_data.clear(); st.rerun()
            f3=st.file_uploader("OTB (12개월)", type=['csv','xlsx'], accept_multiple_files=True)
            if f3 and st.button("OTB 저장"):
                otb_list = [process_data(f, "Booked", force_otb=True) for f in f3]
                if save_to_firestore(pd.concat(otb_list, ignore_index=True)): st.cache_data.clear(); st.rerun()

    if sel_date and not df_all.empty:
        df = clean_numeric_columns(df_all[df_all['Snapshot_Date'] == sel_date].copy())
        if not df.empty:
            df['CheckIn_dt'] = pd.to_datetime(df['CheckIn'], errors='coerce')
            df['Stay_Month'] = df['CheckIn_dt'].dt.strftime('%Y-%m')
            df_otb = df[df['Segment'] == 'OTB']; df_act = df[df['Segment'] != 'OTB']
            df_bk = df_act[(df_act['Status']=='Booked') & (df_act['Total_Revenue']>0)]
            df_cn = df_act[df_act['Status']=='Cancelled']; df_tot = pd.concat([df_bk, df_cn])

            tabs = st.tabs(["👑 GM 요약", "✅ 예약 상세", "❌ 취소 상세", "📈 종합 합계", "🆓 0원 예약", "🎯 OTB 현황"])
            with tabs[0]:
                st.header(f"👑 GM 요약 ({sel_date})")
                bk_r, bk_rn = df_bk['Room_Revenue'].sum(), df_bk['RN'].sum()
                cn_r, cn_rn = df_cn['Room_Revenue'].sum(), df_cn['RN'].sum()
                c=st.columns(6); c[0].metric("예약건", len(df_bk)); c[1].metric("RN", bk_rn); c[2].metric("매출", f"{bk_r:,.0f}")
                c[3].metric("ADR", f"{bk_r/bk_rn if bk_rn>0 else 0:,.0f}"); c[4].metric("취소RN", cn_rn); c[5].metric("취소매출", f"{cn_r:,.0f}")
                st.divider(); style_df(add_total(df_bk.groupby('Segment').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index(), 'Segment'))
            with tabs[1]: render_tab(df_bk, "bk")
            with tabs[2]: render_tab(df_cn, "cn")
            with tabs[3]: render_tab(df_tot, "tot")
            with tabs[4]: style_df(df_act[(df_act['Status']=='Booked')&(df_act['Total_Revenue']<=0)][['Guest_Name','CheckIn','Account']])
            with tabs[5]:
                st.header("🎯 OTB 현황")
                if df_otb.empty: st.warning("OTB 데이터 없음")
                else:
                    base = df_otb.copy(); base['M'] = base['CheckIn_dt'].dt.month
                    grp = base.groupby('M').agg({'Room_Revenue':'sum'}).reset_index()
                    fin = pd.merge(pd.DataFrame({'M': range(1,13)}), grp, on='M', how='left').fillna(0)
                    fin['Budget'] = fin['M'].map(BUDGET_DATA).fillna(0)
                    fin['Rate'] = np.where(fin['Budget']>0, (fin['Room_Revenue']/fin['Budget'])*100, 0)
                    fig = go.Figure(); fig.add_trace(go.Bar(x=fin['M'], y=fin['Room_Revenue'], text=fin['Rate'].apply(lambda x:f"{x:.1f}%"), textposition='outside'))
                    fig.add_trace(go.Scatter(x=fin['M'], y=fin['Budget'], line=dict(color='red', dash='dot')))
                    st.plotly_chart(fig, use_container_width=True, key="otb_chart")
                    res = {}; tb, to = fin['Budget'].sum(), fin['Room_Revenue'].sum()
                    for _,r in fin.iterrows(): res[f"{int(r['M'])}월"] = [f"{r['Budget']:,.0f}", f"{r['Room_Revenue']:,.0f}", f"{r['Rate']:.1f}%"]
                    res['Total'] = [f"{tb:,.0f}", f"{to:,.0f}", f"{to/tb*100 if tb>0 else 0:.1f}%"]
                    st.dataframe(pd.DataFrame(res, index=['Budget','OTB','달성률']), use_container_width=True)
    else: st.info("👈 파일 업로드 필요")
except Exception as e: st.error(f"오류: {e}")
