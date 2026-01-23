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
        st.error(f"🔥 DB 연결 실패: {e}")
        st.stop()

db = firestore.client()
COLLECTION_NAME = "revenue_integrity_history_v2"

# ==============================================================================
# 3. 데이터 관리 함수
# ==============================================================================

def clean_numeric_columns(df):
    target_cols = ['RN', 'Room_Revenue', 'Total_Revenue', 'ADR_Room', 'ADR_Total', 'Lead_Time', 'Rooms', 'Nights']
    for col in target_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', '').str.replace('₩', '').str.replace('nan', '0'), errors='coerce').fillna(0)
    return df

def save_to_firestore(df):
    try:
        if df.empty: return False
        # 저장할 때 무조건 오늘 날짜로 Snapshot_Date 강제 고정 (조회 누락 방지)
        today_str = datetime.now().strftime('%Y-%m-%d')
        df['Snapshot_Date'] = today_str
        records = df.fillna(0).astype(str).to_dict(orient='records')
        db.collection(COLLECTION_NAME).add({
            'data': records,
            'uploaded_at': datetime.now(),
            'snapshot_date': today_str
        })
        return True
    except Exception as e:
        st.error(f"❌ 저장 오류: {e}")
        return False

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
                    r['Snapshot_Date'] = snap
                    all_data.append(r)
        return all_data
    except Exception as e:
        st.error(f"❌ 로드 오류: {e}")
        return []

def delete_otb_data_only():
    try:
        docs = db.collection(COLLECTION_NAME).stream()
        cnt = 0
        for doc in docs:
            d = doc.to_dict()
            if 'data' in d and len(d['data']) > 0:
                # OTB가 포함된 문서 전체 삭제
                if any('OTB' in str(row.get('Segment', '')) for row in d['data']):
                    doc.reference.delete()
                    cnt += 1
        return cnt
    except: return 0

# ==============================================================================
# 4. 엑셀/CSV 처리 (OTB 마지막 셀 & 조식 전수조사)
# ==============================================================================

def normalize_columns(df):
    col_map = {}
    rules = {
        'CheckIn': ['checkin', 'arrival', '입실', '일자', 'date'],
        'Guest_Name': ['guest', 'name', 'customer', '고객', '성명'],
        'Booking_Date': ['booking', 'create', 'res', '예약', '생성'],
        'Rooms': ['room', 'qty', '객실수'],
        'Nights': ['night', 'los', '박수'],
        'Room_Revenue': ['room_rev', 'revenue', '객실료', '매출'],
        'Total_Revenue': ['total', 'amount', '총금액', '합계'],
        'Segment': ['segment', '세그먼트'],
        'Account': ['account', 'source', '거래처'],
        'Room_Type': ['type', 'cat', '객실타입'],
        'Lead_Time': ['lead', 'lt']
    }
    for col in df.columns:
        clean = str(col).lower().replace(" ", "").replace("_", "")
        for target, kws in rules.items():
            if any(kw in clean for kw in kws):
                if target not in col_map.values():
                    col_map[col] = target; break
    return df.rename(columns=col_map)

def process_data(file, status, force_otb=False):
    try:
        is_otb = force_otb or "Sales on the Book" in file.name
        if file.name.endswith('.csv'):
            try: df_raw = pd.read_csv(file, header=None)
            except: df_raw = pd.read_csv(file, header=None, encoding='cp949')
        else:
            df_raw = pd.read_excel(file, header=None)

        # [A] OTB 처리: 마지막 유효 셀 추출
        if is_otb:
            found_month = datetime.now().month
            for r in range(min(15, len(df_raw))):
                row_str = " ".join(df_raw.iloc[r].astype(str).values)
                match = re.search(r'20\d{2}-(\d{2})', row_str)
                if match:
                    found_month = int(match.group(1)); break
            
            # 빈 행/열 쳐내고 마지막 값 찾기
            df_clean = df_raw.dropna(how='all').dropna(axis=1, how='all')
            try:
                total_rev = float(str(df_clean.iloc[-1, -1]).replace(',', '').replace('nan', '0').split('.')[0])
                total_rn = float(str(df_clean.iloc[-1, -5]).replace(',', '').replace('nan', '0').split('.')[0])
            except:
                total_rev = 0; total_rn = 0

            return pd.DataFrame([{
                'CheckIn': f"2026-{found_month:02d}-01",
                'Room_Revenue': total_rev, 'Total_Revenue': total_rev, 'RN': total_rn,
                'Guest_Name': 'OTB_DATA', 'Segment': 'OTB', 'Account': 'OTB', 'Room_Type': 'ROH',
                'Nat_Orig': 'KR', 'Booking_Date': datetime.now().strftime('%Y-%m-%d'),
                'Lead_Time': 0, 'Breakfast': 'Unknown', 'Status': 'Booked'
            }])

        # [B] 예약/취소: 조식(BF) 행 전체 전수조사
        header_idx = -1
        for i, row in df_raw.head(20).iterrows():
            if sum(1 for k in ['예약번호', '고객명', '입실일자'] if k in str(row.values)) >= 2:
                header_idx = i; break
        
        if header_idx != -1:
            df_data = df_raw.iloc[header_idx+1:].reset_index(drop=True)
            
            # 조식 식별 로직 (K열 인덱스 10 포함, 행 전체 문자열 검사)
            def find_bf(row):
                row_text = "".join(row.astype(str).values).upper()
                if 'BF' in row_text: return 'Included (조식포함)'
                return 'Not Included (불포함)'
            
            bf_series = df_data.apply(find_bf, axis=1)
            
            df_data.columns = df_raw.iloc[header_idx].values
            df = normalize_columns(df_data).copy()
            df['Breakfast'] = bf_series
            
            for col in ['Room_Revenue', 'Total_Revenue', 'Rooms', 'Nights', 'Lead_Time']:
                if col in df.columns: df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
            
            df['Total_Revenue'] = np.where(df['Total_Revenue'] == 0, df['Room_Revenue'], df['Total_Revenue'])
            df['RN'] = df.get('Rooms', 0) * df.get('Nights', 1).replace(0, 1)
            df['Status'] = status
            df['CheckIn_dt'] = pd.to_datetime(df['CheckIn'], errors='coerce')
            df = df.dropna(subset=['CheckIn_dt'])
            df['Stay_Month'] = df['CheckIn_dt'].dt.strftime('%Y-%m')
            df['Booking_Month'] = pd.to_datetime(df.get('Booking_Date', df['CheckIn']), errors='coerce').dt.strftime('%Y-%m')
            df['Day_Type'] = df['CheckIn_dt'].dt.weekday.apply(lambda x: 'Weekend' if x >= 4 else 'Weekday')
            
            def cls_nat(row):
                if re.search('[가-힣]', str(row.get('Guest_Name',''))): return 'KOR'
                return 'OTH'
            df['Nat_Group'] = df.apply(cls_nat, axis=1)
            return clean_numeric_columns(df)
            
    except Exception as e:
        st.error(f"파일 처리 에러: {e}")
        return pd.DataFrame()

# ==============================================================================
# 5. UI 헬퍼 함수
# ==============================================================================

def add_total(df, group_col="구분"):
    if df.empty: return df
    num_df = df.select_dtypes(include=[np.number]).fillna(0)
    totals = num_df.sum().to_dict()
    row = {col: "" for col in df.columns}
    row.update(totals)
    if group_col in df.columns: row[group_col] = "TOTAL"
    else: row[df.columns[0]] = "TOTAL"
    if 'RN' in row and row['RN'] > 0:
        if 'Room_Revenue' in row: row['ADR_Room'] = row['Room_Revenue'] / row['RN']
        if 'Total_Revenue' in row: row['ADR_Total'] = total_rev = row['Total_Revenue'] / row['RN']
    return pd.concat([df, pd.DataFrame([row])], ignore_index=True)

def style_df(df):
    if df.empty: st.write("데이터가 없습니다."); return
    styler = df.style.format({c: "{:,.0f}" for c in df.select_dtypes(include=[np.number]).columns})
    def highlight(row):
        is_total = any(str(v) == "TOTAL" for v in row)
        return ['background-color: #fff9c4; font-weight: 900; color: black; border-top: 2px solid black'] * len(row) if is_total else [''] * len(row)
    st.dataframe(styler.apply(highlight, axis=1), hide_index=True, use_container_width=True)

def render_tab(df, unique_key):
    if df.empty: st.warning("데이터가 없습니다."); return
    t1, t2, t3, t4, t5 = st.tabs(["세그먼트", "Pacing", "거래처", "요일", "조식"])
    with t1:
        s = df.groupby('Segment').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.pie(s, values='Room_Revenue', names='Segment'), use_container_width=True, key=f"{unique_key}_pie")
        c2.plotly_chart(px.bar(s, x='Segment', y='Room_Revenue'), use_container_width=True, key=f"{unique_key}_bar")
        style_df(add_total(s, 'Segment'))
    with t2:
        piv = df.pivot_table(index='Booking_Month', columns='Stay_Month', values='RN', aggfunc='sum').fillna(0)
        st.plotly_chart(px.imshow(piv, text_auto="d", aspect="auto"), use_container_width=True, key=f"{unique_key}_pacing")
    with t3:
        a = df.groupby('Account').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index().sort_values('RN', ascending=False).head(50)
        style_df(add_total(a, 'Account'))
    with t4:
        w = df.groupby('Day_Type').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
        st.plotly_chart(px.bar(w, x='Day_Type', y='Room_Revenue'), use_container_width=True, key=f"{unique_key}_day")
    with t5:
        if 'Breakfast' in df.columns:
            b = df.groupby('Breakfast').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
            c1, c2 = st.columns(2)
            c1.plotly_chart(px.pie(b, values='RN', names='Breakfast', title="조식 비중"), use_container_width=True, key=f"{unique_key}_bf_pie")
            c2.plotly_chart(px.bar(b, x='Breakfast', y='Room_Revenue'), use_container_width=True, key=f"{unique_key}_bf_bar")
            style_df(add_total(b, 'Breakfast'))

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
        if st.button("🗑️ 데이터 초기화 (전체)"):
            deleted = delete_otb_data_only()
            st.warning("데이터 초기화 완료!"); time.sleep(1); st.cache_data.clear(); st.rerun()
            
        selected_date = st.selectbox("Snapshot 날짜", dates, index=0) if dates else None
        st.markdown("---")
        with st.expander("파일 업로드", expanded=True):
            f1 = st.file_uploader("예약 리스트", type=['xlsx','csv'], key="f1")
            if f1 and st.button("예약 저장"):
                if save_to_firestore(process_data(f1, "Booked")): st.cache_data.clear(); st.rerun()
            f2 = st.file_uploader("취소 리스트", type=['xlsx','csv'], key="f2")
            if f2 and st.button("취소 저장"):
                if save_to_firestore(process_data(f2, "Cancelled")): st.cache_data.clear(); st.rerun()
            f3_list = st.file_uploader("OTB (12개 파일)", type=['xlsx','csv'], key="f3", accept_multiple_files=True)
            if f3_list and st.button("OTB 저장"):
                otb_list = [process_data(f, "Booked", force_otb=True) for f in f3_list]
                if save_to_firestore(pd.concat(otb_list, ignore_index=True)): st.cache_data.clear(); st.rerun()

    if selected_date and not df_all.empty:
        df = clean_numeric_columns(df_all[df_all['Snapshot_Date'] == selected_date].copy())
        df_otb = df[df['Segment'] == 'OTB']
        df_act = df[df['Segment'] != 'OTB']
        df_paid_bk = df_act[(df_act['Status'] == 'Booked') & (df_act['Total_Revenue'] > 0)]
        df_list_cn = df_act[df_act['Status'] == 'Cancelled']
        df_total_paid = pd.concat([df_paid_bk, df_list_cn])

        main_tabs = st.tabs(["👑 GM 요약", "✅ 예약 상세", "❌ 취소 상세", "📈 종합 합계", "🎯 OTB 현황"])

        with main_tabs[0]:
            st.header(f"👑 총지배인(GM) 요약 ({selected_date})")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("예약 RN", f"{df_paid_bk['RN'].sum():,.0f}")
            c2.metric("예약 매출", f"{df_paid_bk['Room_Revenue'].sum():,.0f}")
            c3.metric("취소 RN", f"{df_list_cn['RN'].sum():,.0f}")
            c4.metric("취소 매출", f"{df_list_cn['Room_Revenue'].sum():,.0f}")
            st.divider()
            if not df_paid_bk.empty:
                style_df(add_total(df_paid_bk.groupby('Segment').agg({'RN': 'sum','Room_Revenue': 'sum'}).reset_index(), 'Segment')) 

        with main_tabs[1]: render_tab(df_paid_bk, "bk_u")
        with main_tabs[2]: render_tab(df_list_cn, "cn_u")
        with main_tabs[3]: render_tab(df_total_paid, "tot_u")
        with main_tabs[4]:
            st.header("🎯 OTB 현황 (Budget vs OTB)")
            if df_otb.empty: st.warning("OTB 데이터 없음")
            else:
                base = df_otb.copy(); base['M'] = pd.to_datetime(base['CheckIn']).dt.month
                grp = base.groupby('M').agg({'Room_Revenue':'sum'}).reset_index()
                fin = pd.merge(pd.DataFrame({'M': range(1, 13)}), grp, on='M', how='left').fillna(0)
                fin['Budget'] = fin['M'].map(BUDGET_DATA).fillna(0)
                fin['Rate'] = np.where(fin['Budget'] > 0, (fin['Room_Revenue'] / fin['Budget']) * 100, 0)
                fig = go.Figure()
                fig.add_trace(go.Bar(x=fin['M'], y=fin['Room_Revenue'], name='OTB', text=fin['Rate'].apply(lambda x: f"{x:.1f}%"), textposition='outside'))
                fig.add_trace(go.Scatter(x=fin['M'], y=fin['Budget'], name='Budget', line=dict(color='red', dash='dot')))
                st.plotly_chart(fig, use_container_width=True, key="otb_chart_integrity")
                res = {}
                for _, r in fin.iterrows(): res[f"{int(r['M'])}월"] = [f"{r['Budget']:,.0f}", f"{r['Room_Revenue']:,.0f}", f"{r['Rate']:.1f}%"]
                st.table(pd.DataFrame(res, index=['Budget','OTB','달성률']))
    else:
        st.info("👈 사이드바에서 파일을 업로드하고 '저장' 버튼을 눌러주세요.")
except Exception as e:
    st.error(f"🚨 시스템 오류: {e}")
