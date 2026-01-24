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
# 3. 데이터 처리 유틸리티
# ==============================================================================

def clean_numeric_columns(df):
    target_cols = ['RN', 'Room_Revenue', 'Total_Revenue', 'ADR_Room', 'ADR_Total', 'Lead_Time', 'Rooms', 'Nights']
    for col in target_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', '').str.replace('nan', '0').str.replace('₩', ''), errors='coerce').fillna(0)
    return df

def save_to_firestore_split_by_date(df):
    try:
        if df.empty: return False
        # [핵심] 통데이터 날짜별 분리 저장 로직
        unique_dates = df['Snapshot_Date'].unique()
        for s_date in unique_dates:
            date_df = df[df['Snapshot_Date'] == s_date].copy()
            records = date_df.fillna(0).astype(str).to_dict(orient='records')
            db.collection(COLLECTION_NAME).add({
                'data': records,
                'uploaded_at': datetime.now(),
                'snapshot_date': s_date
            })
        return True
    except Exception as e:
        st.error(f"❌ 저장 오류: {e}"); return False

@st.cache_data(ttl=0)
def load_data_from_firestore():
    try:
        docs = db.collection(COLLECTION_NAME).stream(); all_data = []
        for doc in docs:
            d = doc.to_dict()
            if 'data' in d:
                snap = d.get('snapshot_date', '')
                for row in d['data']:
                    if 'Snapshot_Date' not in row: row['Snapshot_Date'] = snap
                    all_data.append(row)
        return all_data
    except: return []

# ==============================================================================
# 4. 파일 처리 (날짜 타입 강제 변환 + 리드타임 자동 계산)
# ==============================================================================

def normalize_columns(df):
    col_map = {}
    rules = {
        'CheckIn': ['입실', '일자', 'checkin', 'arrival'],
        'Guest_Name': ['고객', '성명', 'guest', 'name'],
        'Booking_Date': ['예약일', '생성', 'booking'],
        'Cancel_Date': ['취소일', '취소'],
        'Rooms': ['객실수', '수량', 'room'],
        'Nights': ['박수', 'night', 'los'],
        'Room_Revenue': ['객실료', '매출', 'room_rev'],
        'Total_Revenue': ['총금액', '합계', 'total'],
        'Segment': ['세그먼트', 'segment'],
        'Account': ['거래처', '에이전시', 'source'],
        'Room_Type': ['객실타입', '룸타입', 'type']
    }
    for col in df.columns:
        clean = str(col).lower().replace(" ", "")
        for target, kws in rules.items():
            if any(kw in clean for kw in kws):
                if target not in col_map.values(): col_map[col] = target; break
    return df.rename(columns=col_map)

def process_data(file, status):
    try:
        if file.name.endswith('.csv'):
            try: df_raw = pd.read_csv(file, header=2, encoding='cp949')
            except: df_raw = pd.read_csv(file, header=2)
        else:
            df_raw = pd.read_excel(file, header=2)

        # 1. 조식 전수조사
        bf_col = df_raw.apply(lambda r: 'Included (조식포함)' if 'BF' in "".join(r.astype(str).values).upper() else 'Not Included (불포함)', axis=1)

        # 2. 컬럼 매핑
        df = normalize_columns(df_raw).copy()
        df['Breakfast'] = bf_col
        df['Status'] = status

        # 3. [핵심] 날짜 타입 강제 변환 (글자 -> 계산 가능한 날짜)
        for c in ['CheckIn', 'Booking_Date', 'Cancel_Date']:
            if c in df.columns:
                df[c] = pd.to_datetime(df[c].astype(str).str.replace('.', '-'), errors='coerce')

        # 4. [핵심] 리드타임(LT) 파이썬 직접 계산 (입실일 - 예약일)
        # 둘 다 날짜 타입이므로 이제 뺄셈이 가능합니다.
        if 'CheckIn' in df.columns and 'Booking_Date' in df.columns:
            df['Lead_Time'] = (df['CheckIn'] - df['Booking_Date']).dt.days.fillna(0)
        else:
            df['Lead_Time'] = 0

        # 5. [핵심] 통데이터 날짜 분류 (Snapshot_Date 생성)
        if status == "Booked":
            df['Snapshot_Date'] = df['Booking_Date'].dt.strftime('%Y-%m-%d')
        else:
            df['Snapshot_Date'] = df['Cancel_Date'].dt.strftime('%Y-%m-%d')
        
        df['Snapshot_Date'] = df['Snapshot_Date'].fillna(datetime.now().strftime('%Y-%m-%d'))

        # 6. 나머지 정리
        df['RN'] = pd.to_numeric(df.get('Rooms', 0), errors='coerce').fillna(0) * pd.to_numeric(df.get('Nights', 1).replace(0,1), errors='coerce').fillna(1)
        df['Stay_Month'] = df['CheckIn'].dt.strftime('%Y-%m')
        df['Booking_Month'] = df['Booking_Date'].dt.strftime('%Y-%m')
        df['Day_Type'] = df['CheckIn'].dt.weekday.apply(lambda x: 'Weekend' if x >= 4 else 'Weekday')
        df['Nat_Group'] = df.apply(lambda r: 'KOR' if re.search('[가-힣]', str(r.get('Guest_Name',''))) else 'OTH', axis=1)

        return clean_numeric_columns(df)
    except Exception as e:
        st.error(f"⚠️ 파일 처리 오류: {e}"); return pd.DataFrame()

def process_otb(file):
    try:
        df_raw = pd.read_excel(file, header=None) if not file.name.endswith('.csv') else pd.read_csv(file, header=None, encoding='cp949')
        rev = int(str(df_raw.dropna(how='all').dropna(axis=1, how='all').iloc[-1, -1]).replace(',', '').split('.')[0])
        return pd.DataFrame([{'CheckIn': datetime.now().strftime('%Y-%m-01'), 'Room_Revenue': rev, 'Total_Revenue': rev, 'RN': 0, 'Guest_Name': 'OTB', 'Segment': 'OTB', 'Snapshot_Date': datetime.now().strftime('%Y-%m-%d'), 'Status': 'Booked'}])
    except: return pd.DataFrame()

# ==============================================================================
# 5. UI 헬퍼
# ==============================================================================

def add_total(df, col_name="구분"):
    if df.empty: return df
    num_df = df.select_dtypes(include=[np.number]).fillna(0)
    totals = num_df.sum().to_dict(); row = {c: "" for c in df.columns}; row.update(totals)
    row[col_name if col_name in df.columns else df.columns[0]] = "TOTAL"
    if 'RN' in row and row['RN'] > 0:
        if 'Room_Revenue' in row: row['ADR_Room'] = row['Room_Revenue'] / row['RN']
    return pd.concat([df, pd.DataFrame([row])], ignore_index=True)

def style_df_styled(df):
    if df.empty: return
    styler = df.style.format({c: "{:,.0f}" for c in df.select_dtypes(include=[np.number]).columns})
    st.dataframe(styler.apply(lambda r: ['background-color: #fff9c4; font-weight: 900; border-top: 2px solid black'] * len(r) if any(str(v)=="TOTAL" for v in r) else ['']*len(r), axis=1), hide_index=True, use_container_width=True)

def render_tabs(df, key):
    if df.empty: st.warning("데이터 없음"); return
    t1, t2, t3, t4, t5, t6, t7, t8 = st.tabs(["📊 세그먼트", "📅 Pacing", "🏢 거래처", "⏳ 리드타임", "🛏️ 객실타입", "🗓️ 요일", "🌐 국적", "🍳 조식"])
    with t1:
        s = df.groupby('Segment').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.pie(s, values='Room_Revenue', names='Segment'), use_container_width=True, key=f"{key}_pie")
        c2.plotly_chart(px.bar(s, x='Segment', y='Room_Revenue'), use_container_width=True, key=f"{key}_bar")
        style_df_styled(add_total(s, 'Segment'))
    with t2:
        piv = df.pivot_table(index='Booking_Month', columns='Stay_Month', values='RN', aggfunc='sum').fillna(0)
        st.plotly_chart(px.imshow(piv, text_auto="d", aspect="auto", color_continuous_scale="Blues"), use_container_width=True, key=f"{key}_pace")
    with t3:
        a = df.groupby('Account').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index().sort_values('RN', ascending=False).head(50)
        style_df_styled(add_total(a, 'Account'))
    with t4:
        bins = [-1, 0, 3, 7, 14, 30, 60, 90, 999]; labels = ['0일', '1-3일', '4-7일', '8-14일', '15-30일', '31-60일', '61-90일', '90일+']
        df['LT_G'] = pd.cut(df['Lead_Time'], bins=bins, labels=labels)
        l = df.groupby('LT_G', observed=True).agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
        st.plotly_chart(px.bar(l, x='LT_G', y='RN', title="리드타임별 건수"), use_container_width=True, key=f"{key}_lt")
        style_df_styled(add_total(l, 'LT_G'))
    with t5: style_df_styled(add_total(df.groupby('Room_Type').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index(), 'Room_Type'))
    with t6:
        w = df.groupby('Day_Type').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index()
        st.plotly_chart(px.bar(w, x='Day_Type', y='Room_Revenue'), use_container_width=True, key=f"{key}_wd")
    with t7: style_df_styled(add_total(df.groupby('Nat_Group').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index(), 'Nat_Group'))
    with t8:
        if 'Breakfast' in df.columns:
            b = df.groupby('Breakfast').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index()
            st.plotly_chart(px.pie(b, values='RN', names='Breakfast'), use_container_width=True, key=f"{key}_bf")
            style_df_styled(add_total(b, 'Breakfast'))

# ==============================================================================
# 6. 메인 실행부
# ==============================================================================
try:
    st.title("🏛️ 앰버 호텔 경영 리포트 (Final Integrity)")
    raw_db = load_data_from_firestore(); df_all = pd.DataFrame(raw_db) if raw_db else pd.DataFrame()
    available_dates = sorted(df_all['Snapshot_Date'].unique(), reverse=True) if not df_all.empty else []

    with st.sidebar:
        st.header("⚙️ 시스템 설정")
        if st.button("🗑️ 모든 데이터 초기화"):
            docs = db.collection(COLLECTION_NAME).stream()
            for doc in docs: doc.reference.delete()
            st.warning("데이터 초기화됨"); time.sleep(1); st.cache_data.clear(); st.rerun()
            
        selected_date = st.selectbox("조회일 (실제 데이터 날짜)", available_dates, index=0) if available_dates else None
        st.markdown("---")
        st.header("📤 데이터 업로드")
        f1 = st.file_uploader("예약 리스트 (통데이터 가능)", type=['xlsx','csv'], key="f1")
        if f1 and st.button("예약 저장"):
            if save_to_firestore_split_by_date(process_data(f1, "Booked")): st.cache_data.clear(); st.rerun()
        f2 = st.file_uploader("취소 리스트 (통데이터 가능)", type=['xlsx','csv'], key="f2")
        if f2 and st.button("취소 저장"):
            if save_to_firestore_split_by_date(process_data(f2, "Cancelled")): st.cache_data.clear(); st.rerun()
        f3_list = st.file_uploader("OTB 파일", type=['xlsx','csv'], key="f3", accept_multiple_files=True)
        if f3_list and st.button("OTB 저장"):
            all_otb = [process_otb(f) for f in f3_list]
            if all_otb and save_to_firestore_split_by_date(pd.concat(all_otb, ignore_index=True)): st.cache_data.clear(); st.rerun()

    if selected_date and not df_all.empty:
        df = clean_numeric_columns(df_all[df_all['Snapshot_Date'] == selected_date].copy())
        df_otb = df[df['Segment'].astype(str).str.contains('OTB')]
        df_list = df[~df['Segment'].astype(str).str.contains('OTB')]
        df_bk = df_list[(df_list['Status'] == 'Booked') & (df_list['Total_Revenue'] > 0)]
        df_cn = df_list[df_list['Status'] == 'Cancelled']

        tabs = st.tabs(["👑 GM 요약", "✅ 예약 상세", "❌ 취소 상세", "📈 종합 합계", "🎯 OTB 현황"])
        with tabs[0]:
            st.header(f"👑 GM 요약 ({selected_date})")
            b_rn, b_rev = df_bk['RN'].sum(), df_bk['Room_Revenue'].sum()
            c_rn, c_rev = df_cn['RN'].sum(), df_cn['Room_Revenue'].sum()
            b_los = b_rn / len(df_bk) if not df_bk.empty else 0
            c_los = c_rn / len(df_cn) if not df_cn.empty else 0
            
            st.markdown("#### ✅ 예약 실적")
            c = st.columns(5); c[0].metric("RN", f"{b_rn:,.0f}"); c[1].metric("매출", f"{b_rev:,.0f}"); c[2].metric("ADR", f"{b_rev/b_rn if b_rn>0 else 0:,.0f}"); c[3].metric("LOS", f"{b_los:.1f}박"); c[4].metric("건수", f"{len(df_bk):,.0f}")
            st.markdown("#### ❌ 취소 실적")
            cc = st.columns(5); cc[0].metric("RN", f"{c_rn:,.0f}"); cc[1].metric("매출", f"{c_rev:,.0f}"); cc[2].metric("ADR", f"{c_rev/c_rn if c_rn>0 else 0:,.0f}"); cc[3].metric("LOS", f"{c_los:.1f}박"); cc[4].metric("건수", f"{len(df_cn):,.0f}")
            st.divider(); style_df_styled(add_total(df_bk.groupby('Segment').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index(), 'Segment'))
            
        with tabs[1]: render_tabs(df_bk, "bk")
        with tabs[2]: render_tabs(df_cn, "cn")
        with tabs[3]: render_tabs(pd.concat([df_bk, df_cn]), "tot")
        with tabs[4]:
            if not df_otb.empty:
                df_otb['M'] = pd.to_datetime(df_otb['CheckIn']).dt.month
                fin = pd.merge(pd.DataFrame({'M': range(1, 13)}), df_otb.groupby('M').agg({'Room_Revenue':'sum'}).reset_index(), on='M', how='left').fillna(0)
                fin['Budget'] = fin['M'].map(BUDGET_DATA).fillna(0)
                fig = go.Figure()
                fig.add_trace(go.Bar(x=fin['M'], y=fin['Room_Revenue'], name='OTB', text=(fin['Room_Revenue']/fin['Budget']*100).apply(lambda x: f"{x:.1f}%" if x>0 else ""), textposition='outside'))
                fig.add_trace(go.Scatter(x=fin['M'], y=fin['Budget'], name='Budget', line=dict(color='red', dash='dot')))
                st.plotly_chart(fig, use_container_width=True)
    else: st.info("👈 파일을 업로드하세요.")
except Exception as e: st.error(f"🚨 오류: {e}")
