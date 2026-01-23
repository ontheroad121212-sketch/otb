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
st.set_page_config(page_title="ARI Final Integrity", layout="wide")

st.markdown("""
<style>
    .block-container { padding-top: 1rem; padding-bottom: 5rem; }
    div[data-testid="stMetricValue"] { font-size: 26px !important; font-weight: 900; color: #0f172a; }
    div[data-testid="stMetricLabel"] { font-size: 15px !important; font-weight: 700; color: #64748b; }
    button[data-baseweb="tab"] { font-size: 16px !important; font-weight: 700; }
    [data-testid="stDataFrame"] table tr:last-child td {
        font-weight: 900 !important; background-color: #fff9c4 !important; color: black; border-top: 2px solid black;
    }
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
COLLECTION_NAME = "revenue_integrity_history"

# ==============================================================================
# 3. 데이터 관리 함수
# ==============================================================================

def clean_numeric_columns(df):
    target_cols = ['RN', 'Room_Revenue', 'Total_Revenue', 'ADR_Room', 'ADR_Total', 'Lead_Time', 'OTB_Rev', 'Budget_Rev']
    for col in target_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', '').str.replace('₩', '').str.replace('nan', '0'), errors='coerce').fillna(0)
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
                if 'OTB' in str(d['data'][0].get('Segment','')):
                    doc.reference.delete(); cnt += 1
        return cnt
    except: return 0

# ==============================================================================
# 4. 엑셀 처리 로직 (BF 전수조사 및 OTB 마지막 셀 추출 보강)
# ==============================================================================

def normalize_and_map_columns(df):
    col_map = {}
    rules = {
        'CheckIn': ['checkin', 'arrival', '입실', '일자', 'date'],
        'Guest_Name': ['guest', 'name', 'customer', '고객', '성명'],
        'Booking_Date': ['booking', 'create', 'res', '예약', '생성'],
        'Rooms': ['room', 'qty', '객실수', '수량'],
        'Nights': ['night', 'los', '박수', '박'],
        'Room_Revenue': ['room_rev', 'revenue', '객실료', '매출'],
        'Total_Revenue': ['total', 'amount', '총금액', '합계'],
        'Segment': ['segment', '세그먼트'],
        'Account': ['account', 'source', 'agent', '거래처'],
        'Room_Type': ['type', 'cat', '객실타입'],
        'Nat_Orig': ['nation', 'country', '국적'],
        'Lead_Time': ['lead', '리드', 'lt']
    }
    for col in df.columns:
        clean = str(col).lower().replace(" ", "").replace("_", "")
        for key, kw_list in rules.items():
            if any(k in clean for k in kw_list):
                if key not in col_map.values():
                    col_map[col] = key; break
            if col in col_map: break
    return df.rename(columns=col_map)

def process_data(file, status, force_otb=False):
    try:
        is_otb = force_otb or "Sales on the Book" in file.name
        if file.name.endswith('.csv'):
            try: df_raw = pd.read_csv(file, header=None)
            except: df_raw = pd.read_csv(file, header=None, encoding='cp949')
        else:
            df_raw = pd.read_excel(file, header=None)

        # [A] OTB 처리: 물리적 마지막 셀 추출
        if is_otb:
            found_month = datetime.now().month
            for r in range(min(15, len(df_raw))):
                row_str = " ".join(df_raw.iloc[r].astype(str).values)
                match = re.search(r'20\d{2}-(\d{2})', row_str)
                if match:
                    found_month = int(match.group(1)); break
            
            df_clean = df_raw.dropna(how='all').dropna(axis=1, how='all')
            try:
                # 마지막 유효 행/열 찾기
                last_row_idx = len(df_clean) - 1
                last_col_idx = len(df_clean.columns) - 1
                total_rev = float(str(df_clean.iloc[last_row_idx, last_col_idx]).replace(',', '').replace('nan', '0').split('.')[0])
                total_rn = float(str(df_clean.iloc[last_row_idx, last_col_idx-4]).replace(',', '').replace('nan', '0').split('.')[0])
            except: total_rev = 0; total_rn = 0

            return pd.DataFrame([{
                'CheckIn': f"2026-{found_month:02d}-01",
                'Room_Revenue': total_rev, 'Total_Revenue': total_rev, 'RN': total_rn,
                'Guest_Name': 'OTB_DATA', 'Segment': 'OTB', 'Account': 'OTB', 'Room_Type': 'ROH',
                'Nat_Orig': 'KR', 'Booking_Date': datetime.now().strftime('%Y-%m-%d'),
                'Lead_Time': 0, 'Breakfast': 'Unknown', 'Status': 'Booked', 'Snapshot_Date': datetime.now().strftime('%Y-%m-%d')
            }])

        # [B] 일반 예약: K열 BF 강제 판독 및 전수조사
        header_idx = -1
        for i, row in df_raw.head(20).iterrows():
            if sum(1 for k in ['예약번호', '고객명', '입실일자'] if k in str(row.values)) >= 2:
                header_idx = i; break
        
        if header_idx != -1:
            df_data = df_raw.iloc[header_idx+1:].reset_index(drop=True)
            
            # [최종 조식 로직] 행 전체를 문자열로 합쳐서 'BF'가 있는지 검사 (절대 안 놓침)
            def find_bf_anywhere(row):
                # K열(인덱스 10)을 집중 조사하되, 행 전체도 검사
                row_str = "".join(row.astype(str).values).upper()
                # K열 값만 따로 추출 (인덱스 에러 방지)
                k_val = str(row.iloc[10]).upper() if len(row) > 10 else ""
                if 'BF' in k_val or 'BF' in row_str:
                    return 'Included'
                return 'Room Only'
            
            bf_list = [find_bf_anywhere(row) for _, row in df_data.iterrows()]
            
            df_data.columns = df_raw.iloc[header_idx].values
            df = normalize_and_map_columns(df_data).copy()
            df['Breakfast'] = bf_list
            
            for col in ['Room_Revenue', 'Total_Revenue', 'Rooms', 'Nights', 'Lead_Time']:
                if col in df.columns: df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
            
            df['Total_Revenue'] = np.where(df['Total_Revenue'] == 0, df['Room_Revenue'], df['Total_Revenue'])
            df['RN'] = df.get('Rooms', 0) * df.get('Nights', 1).replace(0, 1)
            df['Status'] = status
            df['Snapshot_Date'] = datetime.now().strftime('%Y-%m-%d')
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
            
    except: return pd.DataFrame()

# ==============================================================================
# 5. UI 및 탭 렌더링
# ==============================================================================

def add_total_row(df, group_col_name="구분"):
    if df.empty: return df
    numeric_df = df.select_dtypes(include=[np.number]).fillna(0)
    totals = numeric_df.sum().to_dict()
    total_row = {col: "" for col in df.columns}
    total_row.update(totals)
    if group_col_name in df.columns: total_row[group_col_name] = "TOTAL"
    else: total_row[df.columns[0]] = "TOTAL"
    if 'RN' in total_row and total_row['RN'] > 0:
        if 'Room_Revenue' in total_row: total_row['ADR_Room'] = total_row['Room_Revenue'] / total_row['RN']
        if 'Total_Revenue' in total_row: total_row['ADR_Total'] = total_row['Total_Revenue'] / total_row['RN']
    return pd.concat([df, pd.DataFrame([total_row])], ignore_index=True)

def show_dataframe_with_style(df):
    if df.empty: st.write("No Data"); return
    num_cols = df.select_dtypes(include=[np.number]).columns
    styler = df.style.format({c: "{:,.0f}" for c in num_cols})
    def highlight(row):
        is_total = any(str(val) == "TOTAL" for val in row)
        return ['background-color: #fff9c4; font-weight: 900; color: black; border-top: 2px solid black'] * len(row) if is_total else [''] * len(row)
    st.dataframe(styler.apply(highlight, axis=1), hide_index=True, use_container_width=True)

def render_analysis_tab(target_df, title_prefix, unique_key):
    if target_df.empty: st.warning(f"⚠️ {title_prefix} 데이터가 없습니다."); return
    t1, t2, t3, t4, t5 = st.tabs(["세그먼트", "Pacing", "거래처", "요일", "조식"])
    
    with t1:
        seg_stats = target_df.groupby('Segment').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.pie(seg_stats, values='Room_Revenue', names='Segment'), use_container_width=True, key=f"{unique_key}_pie")
        c2.plotly_chart(px.bar(seg_stats, x='Segment', y='Room_Revenue'), use_container_width=True, key=f"{unique_key}_bar")
        show_dataframe_with_style(add_total_row(seg_stats, 'Segment'))
    with t2:
        piv = target_df.pivot_table(index='Booking_Month', columns='Stay_Month', values='RN', aggfunc='sum').fillna(0)
        st.plotly_chart(px.imshow(piv, text_auto="d", aspect="auto"), use_container_width=True, key=f"{unique_key}_pacing")
    with t3:
        acc_stats = target_df.groupby('Account').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index().sort_values('RN', ascending=False).head(50)
        show_dataframe_with_style(add_total_row(acc_stats, 'Account'))
    with t4:
        wd_stats = target_df.groupby('Day_Type').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
        st.plotly_chart(px.bar(wd_stats, x='Day_Type', y='Room_Revenue'), use_container_width=True, key=f"{unique_key}_day")
        show_dataframe_with_style(add_total_row(wd_stats, 'Day_Type'))
    with t5:
        st.subheader("🍳 조식 포함 여부 분석 (전수조사)")
        if 'Breakfast' in target_df.columns:
            bf_stats = target_df.groupby('Breakfast').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
            c1, c2 = st.columns(2)
            c1.plotly_chart(px.pie(bf_stats, values='RN', names='Breakfast'), use_container_width=True, key=f"{unique_key}_bf_pie")
            c2.plotly_chart(px.bar(bf_stats, x='Breakfast', y='Room_Revenue'), use_container_width=True, key=f"{unique_key}_bf_bar")
            show_dataframe_with_style(add_total_row(bf_stats, 'Breakfast'))

# ==============================================================================
# 6. 메인 실행부
# ==============================================================================
try:
    st.title("🏛️ 앰버 호텔 경영 리포트 (Final Integrity)")
    raw_data = load_data_from_firestore()
    df_all = pd.DataFrame(raw_data) if raw_data else pd.DataFrame()
    available_dates = sorted(df_all['Snapshot_Date'].unique(), reverse=True) if not df_all.empty else []

    with st.sidebar:
        st.header("📅 설정")
        if st.button("🗑️ OTB 초기화"):
            cnt = delete_otb_data_only()
            st.warning(f"OTB {cnt}건 삭제."); time.sleep(1); st.cache_data.clear(); st.rerun()
        selected_date = st.selectbox("날짜 선택", available_dates, index=0) if available_dates else None
        st.markdown("---")
        with st.expander("파일 업로드", expanded=True):
            f1 = st.file_uploader("예약 리스트", type=['xlsx','csv'], key="f1")
            if f1 and st.button("예약 저장"):
                if save_to_firestore(process_data(f1, "Booked")): st.cache_data.clear(); st.rerun()
            f2 = st.file_uploader("취소 리스트", type=['xlsx','csv'], key="f2")
            if f2 and st.button("취소 저장"):
                if save_to_firestore(process_data(f2, "Cancelled")): st.cache_data.clear(); st.rerun()
            f3 = st.file_uploader("OTB (12개월)", type=['xlsx','csv'], key="f3", accept_multiple_files=True)
            if f3 and st.button("OTB 저장"):
                otb_list = [process_data(f, "Booked", force_otb=True) for f in f3]
                if save_to_firestore(pd.concat(otb_list, ignore_index=True)): st.cache_data.clear(); st.rerun()

    if selected_date and not df_all.empty:
        df = clean_numeric_columns(df_all[df_all['Snapshot_Date'] == selected_date].copy())
        df_otb = df[df['Segment'] == 'OTB']
        df_act = df[df['Segment'] != 'OTB']
        df_paid_bk = df_act[(df_act['Status'] == 'Booked') & (df_act['Total_Revenue'] > 0)]
        df_list_cn = df_act[df_act['Status'] == 'Cancelled']
        df_total_paid = pd.concat([df_paid_bk, df_list_cn])

        tabs = st.tabs(["👑 GM 요약", "✅ 예약 상세", "❌ 취소 상세", "📈 종합 합계", "🎯 OTB 현황"])

        with tabs[0]:
            st.header(f"👑 GM 요약 ({selected_date})")
            c = st.columns(4)
            c[0].metric("예약 RN", f"{df_paid_bk['RN'].sum():,.0f}")
            c[1].metric("예약 매출", f"{df_paid_bk['Room_Revenue'].sum():,.0f}")
            c[2].metric("취소 RN", f"{df_list_cn['RN'].sum():,.0f}")
            c[3].metric("취소 매출", f"{df_list_cn['Room_Revenue'].sum():,.0f}")
            st.divider()
            if not df_paid_bk.empty:
                seg_gm = df_paid_bk.groupby('Segment').agg({'RN': 'sum','Room_Revenue': 'sum'}).reset_index()
                show_dataframe_with_style(add_total_row(seg_gm, 'Segment')) 

        with tabs[1]: render_analysis_tab(df_paid_bk, "예약", "bk_v")
        with tabs[2]: render_analysis_tab(df_list_cn, "취소", "cn_v")
        with tabs[3]: render_analysis_tab(df_total_paid, "종합", "tot_v")
        with tabs[4]:
            st.header("🎯 OTB 현황 (Budget vs OTB)")
            if df_otb.empty: st.warning("OTB 데이터 없음")
            else:
                base = df_otb.copy(); base['M'] = pd.to_datetime(base['CheckIn']).dt.month
                grp = base.groupby('M').agg({'Room_Revenue':'sum'}).reset_index()
                fin = pd.merge(pd.DataFrame({'M': range(1,13)}), grp, on='M', how='left').fillna(0)
                fin['Budget'] = fin['M'].map(BUDGET_DATA).fillna(0)
                fin['Rate'] = np.where(fin['Budget']>0, fin['Room_Revenue']/fin['Budget']*100, 0)
                fig = go.Figure()
                fig.add_trace(go.Bar(x=fin['M'], y=fin['Room_Revenue'], name='OTB', text=fin['Rate'].apply(lambda x:f"{x:.1f}%"), textposition='outside'))
                fig.add_trace(go.Scatter(x=fin['M'], y=fin['Budget'], name='Budget', line=dict(color='red', dash='dot')))
                st.plotly_chart(fig, use_container_width=True, key="otb_final_integrity")
                res = {}
                for _, r in fin.iterrows(): res[f"{int(r['M'])}월"] = [f"{r['Budget']:,.0f}", f"{r['Room_Revenue']:,.0f}", f"{r['Rate']:.1f}%"]
                st.table(pd.DataFrame(res, index=['Budget','OTB','달성률']))
except Exception as e:
    st.error(f"🚨 시스템 오류: {e}")
