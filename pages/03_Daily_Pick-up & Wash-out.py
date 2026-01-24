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
        font-weight: 900 !important; background-color: #fff9c4 !important; color: #000000 !important; border-top: 2px solid #000000 !important;
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
        st.error(f"🔥 데이터베이스 연결 실패: {e}")
        st.stop()

db = firestore.client()
COLLECTION_NAME = "revenue_integrity_history"

# ==============================================================================
# 3. 데이터 전처리 및 유틸리티 함수
# ==============================================================================

def clean_numeric_columns(df):
    target_cols = [
        'RN', 'Room_Revenue', 'Total_Revenue', 'ADR_Room', 'ADR_Total', 
        'Lead_Time', 'OTB_Rev', 'Budget_Rev', 'Budget_Achiev', 'OTB_RN', 
        'Actual_Rev', 'Actual_RN', 'Rooms', 'Nights'
    ]
    for col in target_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(
                df[col].astype(str).str.replace(',', '').str.replace('nan', '0').str.replace('₩', ''), 
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
    except Exception as e:
        st.error(f"❌ 데이터 저장 오류: {e}")
        return False

@st.cache_data(ttl=0)
def load_data_from_firestore():
    try:
        docs = db.collection(COLLECTION_NAME).stream()
        all_data = []
        for doc in docs:
            doc_dict = doc.to_dict()
            if 'data' in doc_dict:
                doc_date = doc_dict.get('snapshot_date', '')
                for row in doc_dict['data']:
                    if 'Snapshot_Date' not in row or not row['Snapshot_Date']:
                        row['Snapshot_Date'] = doc_date
                    all_data.append(row)
        return all_data
    except Exception as e:
        st.error(f"❌ 데이터 로드 오류: {e}")
        return []

def delete_otb_data_only():
    try:
        docs = db.collection(COLLECTION_NAME).stream()
        deleted_count = 0
        for doc in docs:
            doc_data = doc.to_dict()
            if 'data' in doc_data and len(doc_data['data']) > 0:
                first_row = doc_data['data'][0]
                if 'OTB' in str(first_row.get('Segment', '')):
                    doc.reference.delete()
                    deleted_count += 1
        return deleted_count
    except Exception as e:
        st.error(f"OTB 삭제 중 오류: {e}")
        return 0

# ==============================================================================
# 4. 파일 처리 로직 (리드타임 0 문제 근본 해결)
# ==============================================================================

def normalize_and_map_columns(df):
    col_map = {}
    rules = {
        'CheckIn': ['checkin', 'arrival', '입실', '일자', 'date'],
        'Guest_Name': ['guest', 'name', 'customer', '투숙객', '성명'],
        'Booking_Date': ['booking', 'create', 'res', '예약', '생성'],
        'Rooms': ['room', 'qty', '객실수', '수량'],
        'Nights': ['night', 'los', '박수', '박'],
        'Room_Revenue': ['room_rev', 'revenue', 'roomrate', '객실료', '매출'],
        'Total_Revenue': ['total', 'amount', '총금액', '합계'],
        'Segment': ['segment', '세그먼트'],
        'Account': ['account', 'source', 'agent', '거래처'],
        'Room_Type': ['type', 'cat', '객실타입', '룸타입'],
        'Rate_Plan': ['rate', 'plan', '상품', '패키지'], 
        'Nat_Orig': ['nation', 'country', 'nat', '국적'],
        'Lead_Time': ['lead', '리드', 'lt', 'l/t']
    }
    for col in df.columns:
        clean = str(col).lower().replace(" ", "").replace("_", "").replace("-", "")
        for target, kws in rules.items():
            if any(kw in clean for kw in kws):
                if target not in col_map.values():
                    col_map[col] = target; break
    return df.rename(columns=col_map)

def process_data(uploaded_file, status, force_otb=False):
    try:
        is_filename_otb = "Sales on the Book" in uploaded_file.name or "영업 현황" in uploaded_file.name
        is_otb = force_otb or is_filename_otb
        
        if uploaded_file.name.endswith('.csv'):
            try: df_raw = pd.read_csv(uploaded_file, header=None)
            except: df_raw = pd.read_csv(uploaded_file, header=None, encoding='cp949')
        else:
            df_raw = pd.read_excel(uploaded_file, header=None)

        # ---------------------------------------------------------
        # Case A: OTB (마지막 셀 추출)
        # ---------------------------------------------------------
        if is_otb:
            target_month_date = None
            date_pattern = re.compile(r'20\d{2}-(\d{2})')
            for r in range(min(15, len(df_raw))):
                row_str = " ".join(df_raw.iloc[r].astype(str).values)
                match = date_pattern.search(row_str)
                if match:
                    target_month_date = pd.to_datetime(f"2026-{match.group(1)}-01"); break
            if not target_month_date: target_month_date = datetime.now()

            df_clean = df_raw.dropna(how='all').dropna(axis=1, how='all')
            try:
                total_rev = float(str(df_clean.iloc[-1, -1]).replace(',', '').replace('nan', '0').split('.')[0])
                total_rn = float(str(df_clean.iloc[-1, -5]).replace(',', '').replace('nan', '0').split('.')[0])
            except: total_rev = 0; total_rn = 0

            return pd.DataFrame([{
                'CheckIn': target_month_date.strftime('%Y-%m-%d'),
                'Room_Revenue': total_rev, 'Total_Revenue': total_rev, 'RN': total_rn,
                'Guest_Name': 'OTB_DATA', 'Segment': 'OTB', 'Account': 'OTB_Summary',
                'Room_Type': 'ROH', 'Nat_Orig': 'KR', 'Booking_Date': target_month_date.strftime('%Y-%m-%d'),
                'Lead_Time': 0, 'Breakfast': 'Unknown', 'Status': 'Booked'
            }])
            
        # ---------------------------------------------------------
        # Case B: 예약/취소 (리드타임 행 전수조사)
        # ---------------------------------------------------------
        else:
            # 3행(Index 2) 근처에서 헤더행 찾기
            header_idx = -1
            for i, row in df_raw.head(15).iterrows():
                row_text = "".join(row.astype(str).values).lower()
                if any(k in row_text for k in ['리드', 'lead', 'lt', 'l/t']):
                    header_idx = i; break
            
            if header_idx == -1: header_idx = 2 # 기본값
            
            df_header = df_raw.iloc[header_idx]
            df_data = df_raw.iloc[header_idx+1:].reset_index(drop=True)
            df_data.columns = df_header.values
            
            # 조식 전수조사
            def scan_bf(row):
                return 'Included (조식포함)' if 'BF' in "".join(row.astype(str).values).upper() else 'Not Included (불포함)'
            breakfast_col = df_data.apply(scan_bf, axis=1)
            
            # 매핑 및 보정
            df = normalize_and_map_columns(df_data).copy()
            df['Breakfast'] = breakfast_col
            
            for col in ['Room_Revenue', 'Total_Revenue', 'Rooms', 'Nights', 'Lead_Time']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', '').str.replace('nan', '0').str.replace('₩', ''), errors='coerce').fillna(0)
                else:
                    df[col] = 0
            
            df['Total_Revenue'] = np.where(df['Total_Revenue'] == 0, df['Room_Revenue'], df['Total_Revenue'])
            df['RN'] = df.get('Rooms', 0) * df.get('Nights', 1).replace(0, 1)
            df['Status'] = status
            df['Snapshot_Date'] = datetime.now().strftime('%Y-%m-%d')
            df['CheckIn_dt'] = pd.to_datetime(df['CheckIn'], errors='coerce')
            df['Booking_dt'] = pd.to_datetime(df.get('Booking_Date', df['CheckIn']), errors='coerce')
            df = df.dropna(subset=['CheckIn_dt'])
            df['Stay_Month'] = df['CheckIn_dt'].dt.strftime('%Y-%m')
            df['Booking_Month'] = df['Booking_dt'].dt.strftime('%Y-%m')
            df['Day_Type'] = df['CheckIn_dt'].dt.weekday.apply(lambda x: 'Weekend' if x >= 4 else 'Weekday')
            
            def classify_nat(row):
                name = str(row.get('Guest_Name',''))
                if re.search('[가-힣]', name): return 'KOR'
                return 'OTH'
            df['Nat_Group'] = df.apply(classify_nat, axis=1)
            return clean_numeric_columns(df)
            
    except Exception as e:
        st.error(f"⚠️ 파일 처리 오류: {e}")
        return pd.DataFrame()

# ==============================================================================
# 5. UI 렌더링 헬퍼 함수들 (원본 기능 100% 복구)
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
    if df.empty:
        st.write("표시할 데이터가 없습니다."); return
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    styler = df.style.format({col: "{:,.0f}" for col in numeric_cols})
    def highlight_total(row):
        return ['background-color: #fff9c4; font-weight: 900; color: black; border-top: 2px solid black'] * len(row) if any(str(val) == "TOTAL" for val in row) else [''] * len(row)
    st.dataframe(styler.apply(highlight_total, axis=1), hide_index=True, use_container_width=True)

def render_analysis_tab(target_df, title_prefix, unique_key, color_scale="Blues"):
    if target_df.empty:
        st.warning(f"⚠️ {title_prefix} 데이터가 없습니다."); return
    
    t1, t2, t3, t4, t5, t6, t7, t8 = st.tabs(["📊 세그먼트", "📅 Pacing", "🏢 거래처", "⏳ 리드타임", "🛏️ 객실타입", "🗓️ 요일", "🌐 국적", "🍳 조식"])
    
    with t1:
        st.subheader(f"📊 {title_prefix} 세그먼트 분석")
        s_stats = target_df.groupby('Segment').agg({'RN': 'sum', 'Room_Revenue': 'sum', 'Total_Revenue': 'sum'}).reset_index()
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.pie(s_stats, values='Room_Revenue', names='Segment', title="매출 비중"), use_container_width=True, key=f"{unique_key}_pie")
        c2.plotly_chart(px.bar(s_stats, x='Segment', y='Room_Revenue', title="매출 규모"), use_container_width=True, key=f"{unique_key}_bar")
        show_dataframe_with_style(add_total_row(s_stats, 'Segment'))
    
    with t2:
        st.subheader(f"📅 Booking Pacing")
        piv = target_df.pivot_table(index='Booking_Month', columns='Stay_Month', values='RN', aggfunc='sum').fillna(0)
        st.plotly_chart(px.imshow(piv, text_auto="d", aspect="auto", color_continuous_scale=color_scale), use_container_width=True, key=f"{unique_key}_pacing")
    
    with t3:
        st.subheader("🏢 상위 거래처")
        acc_stats = target_df.groupby('Account').agg({'RN': 'sum', 'Room_Revenue': 'sum', 'Total_Revenue': 'sum'}).reset_index().sort_values('RN', ascending=False).head(50)
        show_dataframe_with_style(add_total_row(acc_stats, 'Account'))
    
    with t4:
        st.subheader("⏳ 리드타임 (엑셀 계산값)")
        bins = [-1, 0, 3, 7, 14, 30, 60, 90, 999]; labels = ['0일', '1-3일', '4-7일', '8-14일', '15-30일', '31-60일', '61-90일', '90일+']
        tdf = target_df.copy(); tdf['LT_G'] = pd.cut(tdf['Lead_Time'], bins=bins, labels=labels)
        l_stats = tdf.groupby('LT_G', observed=True).agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
        st.plotly_chart(px.bar(l_stats, x='LT_G', y='RN', title="리드타임별 박수"), use_container_width=True, key=f"{unique_key}_lead")
        show_dataframe_with_style(add_total_row(l_stats, 'LT_G'))
    
    with t5:
        rt_stats = target_df.groupby('Room_Type').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
        show_dataframe_with_style(add_total_row(rt_stats, 'Room_Type'))
    
    with t6:
        wd_stats = target_df.groupby('Day_Type').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.bar(wd_stats, x='Day_Type', y='Room_Revenue'), use_container_width=True, key=f"{unique_key}_wd_bar")
        c2.plotly_chart(px.pie(wd_stats, values='RN', names='Day_Type'), use_container_width=True, key=f"{unique_key}_wd_pie")
    
    with t7:
        if 'Nat_Group' in target_df.columns:
            nat_stats = target_df.groupby('Nat_Group').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
            show_dataframe_with_style(add_total_row(nat_stats, 'Nat_Group'))
            
    with t8:
        st.subheader("🍳 조식 분석")
        if 'Breakfast' in target_df.columns:
            bf_stats = target_df.groupby('Breakfast').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
            c1, c2 = st.columns(2)
            c1.plotly_chart(px.pie(bf_stats, values='RN', names='Breakfast', title="조식 비중"), use_container_width=True, key=f"{unique_key}_bf_p")
            c2.plotly_chart(px.bar(bf_stats, x='Breakfast', y='Room_Revenue', title="조식 매출"), use_container_width=True, key=f"{unique_key}_bf_b")
            show_dataframe_with_style(add_total_row(bf_stats, 'Breakfast'))

# ==============================================================================
# 6. 메인 실행부 (무삭제 무편집)
# ==============================================================================
try:
    st.title("🏛️ 앰버 호텔 경영 리포트 (Final Integrity)")
    raw_data = load_data_from_firestore()
    df_all = pd.DataFrame(raw_data) if raw_data else pd.DataFrame()
    available_dates = sorted(df_all['Snapshot_Date'].unique(), reverse=True) if not df_all.empty else []

    with st.sidebar:
        st.header("📅 조회 설정")
        if st.button("🗑️ OTB 데이터만 초기화"):
            deleted_cnt = delete_otb_data_only()
            st.warning(f"OTB {deleted_cnt}건 삭제 완료!"); time.sleep(1); st.cache_data.clear(); st.rerun()
            
        selected_date = st.selectbox("조회 기준일 (Snapshot)", available_dates, index=0) if available_dates else None
        st.markdown("---")
        st.header("📤 데이터 업로드")
        f1 = st.file_uploader("예약 리스트", type=['xlsx','csv'], key="f1")
        if f1 and st.button("예약 저장"):
            if save_to_firestore(process_data(f1, "Booked")): st.cache_data.clear(); st.rerun()
        f2 = st.file_uploader("취소 리스트", type=['xlsx','csv'], key="f2")
        if f2 and st.button("취소 저장"):
            if save_to_firestore(process_data(f2, "Cancelled")): st.cache_data.clear(); st.rerun()
        f3_list = st.file_uploader("OTB (12개월 통합)", type=['xlsx','csv'], key="f3", accept_multiple_files=True)
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

        tabs = st.tabs(["👑 GM 요약", "✅ 예약 상세", "❌ 취소 상세", "📈 종합 합계", "🆓 0원 예약", "🎯 OTB 현황"])

        with tabs[0]:
            st.header(f"👑 총지배인(GM) 요약 ({selected_date})")
            bk_rn, bk_rev = df_paid_bk['RN'].sum(), df_paid_bk['Room_Revenue'].sum()
            cn_rn, cn_rev = df_list_cn['RN'].sum(), df_list_cn['Room_Revenue'].sum()
            c = st.columns(4)
            c[0].metric("예약 RN", f"{bk_rn:,.0f}"); c[1].metric("예약 매출", f"{bk_rev:,.0f}")
            c[2].metric("취소 RN", f"{cn_rn:,.0f}"); c[3].metric("취소 매출", f"{cn_rev:,.0f}")
            st.divider()
            if not df_paid_bk.empty:
                seg_gm = df_paid_bk.groupby('Segment').agg({'RN': 'sum','Room_Revenue': 'sum','Total_Revenue': 'sum'}).reset_index()
                show_dataframe_with_style(add_total_row(seg_gm, 'Segment')) 
            c_left, c_right = st.columns(2)
            with c_left:
                if not df_paid_bk.empty: st.plotly_chart(px.pie(df_paid_bk.groupby('Nat_Group')['RN'].sum().reset_index(), values='RN', names='Nat_Group', hole=0.4, title="국적 비중"), use_container_width=True, key="gm_pie")
            with c_right:
                comb_m = pd.concat([df_paid_bk.assign(Type='예약'), df_list_cn.assign(Type='취소')]).groupby(['Stay_Month','Type'])['RN'].sum().reset_index()
                if not comb_m.empty: st.plotly_chart(px.bar(comb_m, x='Stay_Month', y='RN', color='Type', barmode='group', title="월별 추이"), use_container_width=True, key="gm_bar")

        with tabs[1]: render_analysis_tab(df_paid_bk, "유료 예약", "bk_u")
        with tabs[2]: render_analysis_tab(df_list_cn, "취소 데이터", "cn_u")
        with tabs[3]: render_analysis_tab(df_total_paid, "종합 합계", "tot_u")
        with tabs[4]: st.dataframe(df_list[(df_list['Status'] == 'Booked') & (df_list['Total_Revenue'] <= 0)][['Guest_Name', 'CheckIn', 'Account', 'Room_Type']], use_container_width=True)

        with tabs[5]:
            st.header("🎯 OTB 현황 (Budget vs OTB)")
            if df_otb.empty: st.warning("⚠️ OTB 데이터가 없습니다.")
            else:
                base = df_otb.copy(); base['M'] = pd.to_datetime(base['CheckIn']).dt.month
                grp_otb = base.groupby('M').agg({'Room_Revenue':'sum'}).reset_index()
                fin = pd.merge(pd.DataFrame({'M': range(1, 13)}), grp_otb, on='M', how='left').fillna(0)
                fin['Budget'] = fin['M'].map(BUDGET_DATA).fillna(0)
                fin['OTB'] = fin['Room_Revenue']
                fin['Rate'] = np.where(fin['Budget'] > 0, (fin['OTB'] / fin['Budget']) * 100, 0)
                fin['Name'] = fin['M'].astype(str) + "월"
                fig_otb = go.Figure()
                fig_otb.add_trace(go.Bar(x=fin['Name'], y=fin['OTB'], name='OTB', marker_color='#2E86C1', text=fin['Rate'].apply(lambda x: f"{x:.1f}%"), textposition='outside'))
                fig_otb.add_trace(go.Scatter(x=fin['Name'], y=fin['Budget'], name='Budget', line=dict(color='red', dash='dot', width=3)))
                fig_otb.update_layout(height=550, yaxis_title="매출", margin=dict(t=50))
                st.plotly_chart(fig_otb, use_container_width=True, key="otb_final_chart")
                res_dict = {}
                tb, to = fin['Budget'].sum(), fin['OTB'].sum()
                for _, r in fin.iterrows(): res_dict[r['Name']] = [f"{r['Budget']:,.0f}", f"{r['OTB']:,.0f}", f"{r['Rate']:.1f}%"]
                res_dict['합계 (Total)'] = [f"{tb:,.0f}", f"{to:,.0f}", f"{(to/tb*100 if tb>0 else 0):.1f}%"]
                st.dataframe(pd.DataFrame(res_dict, index=['Budget', 'OTB', '달성률']).style.apply(lambda s: ['background-color: #fff9c4; font-weight: bold; border-left: 2px solid black; color: black'] * len(s) if s.name == '합계 (Total)' else [''] * len(s), axis=0), use_container_width=True)

except Exception as e:
    st.error(f"🚨 시스템 오류: {e}")
