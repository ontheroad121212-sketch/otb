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
# 1. 페이지 설정 및 CSS (스타일 100% 유지)
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
    div.stButton > button:first-child:hover { background-color: #ff4b4b; color: white; }
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
# 3. 데이터 전처리 함수
# ==============================================================================

def clean_numeric_columns(df):
    target_cols = ['RN', 'Room_Revenue', 'Total_Revenue', 'ADR_Room', 'ADR_Total', 'Lead_Time', 'OTB_Rev', 'Budget_Rev']
    for col in target_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', '').str.replace('nan', '0'), errors='coerce').fillna(0)
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
                for row in d['data']:
                    if 'Snapshot_Date' not in row: row['Snapshot_Date'] = snap
                    all_data.append(row)
        return all_data
    except: return []

def delete_otb_data_only():
    try:
        docs = db.collection(COLLECTION_NAME).stream(); cnt = 0
        for doc in docs:
            d = doc.to_dict()
            if 'data' in d and 'OTB' in str(d['data'][0].get('Segment','')):
                doc.reference.delete(); cnt += 1
        return cnt
    except: return 0

# ==============================================================================
# 4. 파일 처리 (리드타임 핀셋 추출 및 조식 전수조사)
# ==============================================================================

def normalize_and_map_columns(df):
    col_map = {}
    rules = {
        'CheckIn': ['입실', '일자', 'checkin', 'arrival'],
        'Guest_Name': ['고객', '성명', 'guest', 'name'],
        'Booking_Date': ['예약일', '생성', 'booking', 'create'],
        'Rooms': ['객실수', '수량', 'room', 'qty'],
        'Nights': ['박수', 'los', 'night'],
        'Room_Revenue': ['객실료', '매출', 'room_rev'],
        'Total_Revenue': ['총금액', '합계', 'total'],
        'Segment': ['세그먼트', 'segment'],
        'Account': ['거래처', 'source', 'account'],
        'Room_Type': ['객실타입', 'type', 'cat'],
        'Nat_Orig': ['국적', 'nation', 'country']
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
        if file.name.endswith('.csv'):
            try: df_raw = pd.read_csv(file, header=None)
            except: df_raw = pd.read_csv(file, header=None, encoding='cp949')
        else:
            df_raw = pd.read_excel(file, header=None)

        if is_otb:
            # OTB 로직: 마지막 셀 매출
            df_clean = df_raw.dropna(how='all').dropna(axis=1, how='all')
            try:
                total_rev = int(str(df_clean.iloc[-1, -1]).replace(',', '').replace('nan', '0').split('.')[0])
            except: total_rev = 0
            return pd.DataFrame([{'CheckIn': datetime.now().strftime('%Y-%m-01'), 'Room_Revenue': total_rev, 'Total_Revenue': total_rev, 'RN': 0, 'Guest_Name': 'OTB', 'Segment': 'OTB', 'Status': 'Booked'}])
        
        else:
            # 예약/취소 리스트 로직
            # 1. 제목줄(3행, Index 2)에서 리드타임 열 찾기
            header_row = df_raw.iloc[2].astype(str).tolist()
            lt_col_idx = -1
            for idx, name in enumerate(header_row):
                if any(kw in name.lower() for kw in ['리드', 'lead', 'lt']):
                    lt_col_idx = idx; break
            
            # 2. 4행부터 데이터 추출
            df_data = df_raw.iloc[3:].reset_index(drop=True)
            df_data.columns = header_row
            
            # 3. 조식 전수조사
            def scan_bf(row):
                return 'Included (조식포함)' if 'BF' in "".join(row.astype(str).values).upper() else 'Not Included (불포함)'
            breakfast_col = df_data.apply(scan_bf, axis=1)
            
            # 4. 리드타임 값 강제 추출
            lead_time_col = pd.to_numeric(df_data.iloc[:, lt_col_idx].astype(str).str.replace(',', ''), errors='coerce').fillna(0) if lt_col_idx != -1 else 0
            
            # 5. 매핑 및 병합
            df = normalize_and_map_columns(df_data).copy()
            df['Breakfast'] = breakfast_col
            df['Lead_Time'] = lead_time_col
            
            # 숫자/날짜 마무리
            for col in ['Room_Revenue', 'Total_Revenue', 'Rooms', 'Nights']:
                if col in df.columns: df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
            
            df['Total_Revenue'] = np.where(df.get('Total_Revenue', 0) == 0, df.get('Room_Revenue', 0), df.get('Total_Revenue', 0))
            df['RN'] = df.get('Rooms', 0) * df.get('Nights', 1).replace(0, 1)
            df['Status'] = status
            df['Snapshot_Date'] = datetime.now().strftime('%Y-%m-%d')
            df['CheckIn_dt'] = pd.to_datetime(df['CheckIn'], errors='coerce')
            df = df.dropna(subset=['CheckIn_dt'])
            df['Stay_Month'] = df['CheckIn_dt'].dt.strftime('%Y-%m')
            df['Booking_Month'] = pd.to_datetime(df.get('Booking_Date', df['CheckIn']), errors='coerce').dt.strftime('%Y-%m')
            df['Day_Type'] = df['CheckIn_dt'].dt.weekday.apply(lambda x: 'Weekend' if x >= 4 else 'Weekday')
            
            def cls_nat(row): return 'KOR' if re.search('[가-힣]', str(row.get('Guest_Name',''))) else 'OTH'
            df['Nat_Group'] = df.apply(cls_nat, axis=1)
            return clean_numeric_columns(df)
    except Exception as e:
        st.error(f"⚠️ 파일 처리 오류: {e}"); return pd.DataFrame()

# ==============================================================================
# 5. UI 렌더링 (원본 기능 유지)
# ==============================================================================

def add_total_row(df, group_col_name="구분"):
    if df.empty: return df
    num_df = df.select_dtypes(include=[np.number]).fillna(0)
    totals = num_df.sum().to_dict(); total_row = {col: "" for col in df.columns}; total_row.update(totals)
    if group_col_name in df.columns: total_row[group_col_name] = "TOTAL"
    else: total_row[df.columns[0]] = "TOTAL"
    if 'RN' in total_row and total_row['RN'] > 0:
        if 'Room_Revenue' in total_row: total_row['ADR_Room'] = total_row['Room_Revenue'] / total_row['RN']
        if 'Total_Revenue' in total_row: total_row['ADR_Total'] = total_row['Total_Revenue'] / total_row['RN']
    return pd.concat([df, pd.DataFrame([total_row])], ignore_index=True)

def show_dataframe_with_style(df):
    if df.empty: st.write("표시할 데이터가 없습니다."); return
    num_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    styler = df.style.format({col: "{:,.0f}" for col in num_cols})
    def highlight(row):
        return ['background-color: #fff9c4; font-weight: 900; color: black; border-top: 2px solid black'] * len(row) if any(str(v) == "TOTAL" for v in row) else [''] * len(row)
    st.dataframe(styler.apply(highlight, axis=1), hide_index=True, use_container_width=True)

def render_analysis_tab(target_df, title_prefix, unique_key):
    if target_df.empty: st.warning(f"⚠️ {title_prefix} 데이터가 없습니다."); return
    t1, t2, t3, t4, t5, t6, t7, t8 = st.tabs(["📊 세그먼트", "📅 Pacing", "🏢 거래처", "⏳ 리드타임", "🛏️ 객실타입", "🗓️ 요일", "🌐 국적", "🍳 조식"])
    with t1:
        s = target_df.groupby('Segment').agg({'RN': 'sum', 'Room_Revenue': 'sum', 'Total_Revenue': 'sum'}).reset_index()
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.pie(s, values='Room_Revenue', names='Segment'), use_container_width=True, key=f"{unique_key}_pie")
        c2.plotly_chart(px.bar(s, x='Segment', y='Room_Revenue'), use_container_width=True, key=f"{unique_key}_bar")
        show_dataframe_with_style(add_total_row(s, 'Segment'))
    with t2:
        piv = target_df.pivot_table(index='Booking_Month', columns='Stay_Month', values='RN', aggfunc='sum').fillna(0)
        st.plotly_chart(px.imshow(piv, text_auto="d", aspect="auto", color_continuous_scale="Blues"), use_container_width=True, key=f"{unique_key}_pacing")
    with t3:
        a = target_df.groupby('Account').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index().sort_values('RN', ascending=False).head(50)
        show_dataframe_with_style(add_total_row(a, 'Account'))
    with t4:
        bins = [-1, 0, 3, 7, 14, 30, 60, 90, 999]; labels = ['0일', '1-3일', '4-7일', '8-14일', '15-30일', '31-60일', '61-90일', '90일+']
        target_df['Lead_Group'] = pd.cut(target_df['Lead_Time'], bins=bins, labels=labels)
        l = target_df.groupby('Lead_Group').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
        st.plotly_chart(px.bar(l, x='Lead_Group', y='RN'), use_container_width=True, key=f"{unique_key}_lead")
        show_dataframe_with_style(add_total_row(l, 'Lead_Group'))
    with t5: show_dataframe_with_style(add_total_row(target_df.groupby('Room_Type').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index(), 'Room_Type'))
    with t6:
        w = target_df.groupby('Day_Type').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.bar(w, x='Day_Type', y='Room_Revenue'), use_container_width=True, key=f"{unique_key}_day_bar")
        c2.plotly_chart(px.pie(w, values='RN', names='Day_Type'), use_container_width=True, key=f"{unique_key}_day_pie")
    with t7:
        if 'Nat_Group' in target_df.columns: show_dataframe_with_style(add_total_row(target_df.groupby('Nat_Group').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index(), 'Nat_Group'))
    with t8:
        if 'Breakfast' in target_df.columns:
            b = target_df.groupby('Breakfast').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
            c1, c2 = st.columns(2)
            c1.plotly_chart(px.pie(b, values='RN', names='Breakfast'), use_container_width=True, key=f"{unique_key}_bf_pie")
            c2.plotly_chart(px.bar(b, x='Breakfast', y='Room_Revenue'), use_container_width=True, key=f"{unique_key}_bf_bar")
            show_dataframe_with_style(add_total_row(b, 'Breakfast'))

# ==============================================================================
# 6. 메인 실행부
# ==============================================================================
try:
    st.title("🏛️ 앰버 호텔 경영 리포트 (Final Integrity)")
    raw_data = load_data_from_firestore(); df_all = pd.DataFrame(raw_data) if raw_data else pd.DataFrame()
    available_dates = sorted(df_all['Snapshot_Date'].unique(), reverse=True) if not df_all.empty else []

    with st.sidebar:
        st.header("📅 조회 설정")
        if st.button("🗑️ OTB 데이터만 초기화"):
            cnt = delete_otb_data_only(); st.warning(f"OTB {cnt}건 삭제 완료!"); time.sleep(1); st.cache_data.clear(); st.rerun()
        selected_date = st.selectbox("조회 기준일 (Snapshot)", available_dates, index=0) if available_dates else None
        st.markdown("---")
        st.header("📤 데이터 업로드")
        with st.expander("예약/취소 리스트", expanded=True):
            f1 = st.file_uploader("예약 리스트", type=['xlsx','csv'], key="f1")
            if f1 and st.button("예약 저장"):
                if save_to_firestore(process_data(f1, "Booked")): st.cache_data.clear(); st.rerun()
            f2 = st.file_uploader("취소 리스트", type=['xlsx','csv'], key="f2")
            if f2 and st.button("취소 저장"):
                if save_to_firestore(process_data(f2, "Cancelled")): st.cache_data.clear(); st.rerun()
        with st.expander("OTB (Sales on the Book)", expanded=True):
            f3_list = st.file_uploader("당월 OTB (12개월 통합)", type=['xlsx','csv'], key="f3", accept_multiple_files=True)
            if f3_list and st.button("OTB 저장"):
                all_otb = []
                for f in f3_list:
                    processed = process_data(f, "Booked", force_otb=True)
                    if not processed.empty: all_otb.append(processed)
                if all_otb and save_to_firestore(pd.concat(all_otb, ignore_index=True)): st.cache_data.clear(); st.rerun()

    if selected_date and not df_all.empty:
        df = clean_numeric_columns(df_all[df_all['Snapshot_Date'] == selected_date].copy())
        df_otb = df[df['Segment'].astype(str).str.contains('OTB')]
        df_list = df[~df['Segment'].astype(str).str.contains('OTB')]
        df_paid_bk = df_list[(df_list['Status'] == 'Booked') & (df_list['Total_Revenue'] > 0)]
        df_list_cn = df_list[df_list['Status'] == 'Cancelled']
        df_total_paid = pd.concat([df_paid_bk, df_list_cn])

        main_tab0, main_tab1, main_tab2, main_tab3, main_tab4, main_tab5 = st.tabs(["👑 GM 요약", "✅ 예약 상세", "❌ 취소 상세", "📈 종합 합계", "🆓 0원 예약", "🎯 OTB 현황"])

        with main_tab0:
            st.header(f"👑 총지배인(GM) 요약 ({selected_date})")
            bk_rn, bk_rev = df_paid_bk['RN'].sum(), df_paid_bk['Room_Revenue'].sum()
            cn_rn, cn_rev = df_list_cn['RN'].sum(), df_list_cn['Room_Revenue'].sum()
            c = st.columns(4); c[0].metric("예약 RN", f"{bk_rn:,.0f}"); c[1].metric("예약 매출", f"{bk_rev:,.0f}"); c[2].metric("취소 RN", f"{cn_rn:,.0f}"); c[3].metric("취소 매출", f"{cn_rev:,.0f}")
            st.divider()
            if not df_paid_bk.empty: show_dataframe_with_style(add_total_row(df_paid_bk.groupby('Segment').agg({'RN': 'sum','Room_Revenue': 'sum','Total_Revenue': 'sum'}).reset_index(), 'Segment')) 
            c_left, c_right = st.columns(2)
            with c_left:
                if not df_paid_bk.empty: st.plotly_chart(px.pie(df_paid_bk.groupby('Nat_Group')['RN'].sum().reset_index(), values='RN', names='Nat_Group', hole=0.4, title="국적"), use_container_width=True, key="gm_pie")
            with c_right:
                comb_m = pd.concat([df_paid_bk.assign(Type='예약'), df_list_cn.assign(Type='취소')]).groupby(['Stay_Month','Type'])['RN'].sum().reset_index()
                if not comb_m.empty: st.plotly_chart(px.bar(comb_m, x='Stay_Month', y='RN', color='Type', barmode='group', title="월별 추이"), use_container_width=True, key="gm_bar")

        with main_tab1: render_analysis_tab(df_paid_bk, "예약", "bk_f")
        with main_tab2: render_analysis_tab(df_list_cn, "취소", "cn_f")
        with main_tab3: render_analysis_tab(df_total_paid, "합계", "tot_f")
        with main_tab4: st.dataframe(df_list[(df_list['Status'] == 'Booked') & (df_list['Total_Revenue'] <= 0)][['Guest_Name', 'CheckIn', 'Account', 'Room_Type']], use_container_width=True)

        with main_tab5:
            st.header("🎯 OTB 현황")
            if df_otb.empty: st.warning("⚠️ OTB 데이터 없음")
            else:
                base = df_otb.copy(); base['M'] = pd.to_datetime(base['CheckIn']).dt.month
                grp = base.groupby('M').agg({'Room_Revenue':'sum'}).reset_index()
                fin = pd.merge(pd.DataFrame({'M': range(1, 13)}), grp, on='M', how='left').fillna(0)
                fin['Budget'] = fin['M'].map(BUDGET_DATA).fillna(0)
                fin['Rate'] = np.where(fin['Budget'] > 0, (fin['Room_Revenue'] / fin['Budget']) * 100, 0)
                fig = go.Figure()
                fig.add_trace(go.Bar(x=fin['M'], y=fin['Room_Revenue'], name='OTB', text=fin['Rate'].apply(lambda x: f"{x:.1f}%"), textposition='outside'))
                fig.add_trace(go.Scatter(x=fin['M'], y=fin['Budget'], name='Budget', line=dict(color='red', dash='dot')))
                fig.update_layout(height=550, margin=dict(t=50)); st.plotly_chart(fig, use_container_width=True, key="otb_chart_last")
                res = {}; tb, to = fin['Budget'].sum(), fin['Room_Revenue'].sum()
                for _, r in fin.iterrows(): res[f"{int(r['M'])}월"] = [f"{r['Budget']:,.0f}", f"{r['Room_Revenue']:,.0f}", f"{r['Rate']:.1f}%"]
                res['합계'] = [f"{tb:,.0f}", f"{to:,.0f}", f"{(to/tb*100 if tb>0 else 0):.1f}%"]
                st.dataframe(pd.DataFrame(res, index=['Budget', 'OTB', '달성률']).style.apply(lambda s: ['background-color: #fff9c4; font-weight: bold; border-left: 2px solid black; color: black'] * len(s) if s.name == '합계' else [''] * len(s), axis=0), use_container_width=True)

except Exception as e: st.error(f"🚨 시스템 오류: {e}")
