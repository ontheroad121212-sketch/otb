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
        'Lead_Time', 'OTB_Rev', 'Budget_Rev', 'Budget_Achiev', 'OTB_RN', 
        'OTB_ADR', 'Actual_Rev', 'Actual_RN', 'Rooms', 'Nights'
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

def save_to_firestore_split_by_date(df):
    try:
        if df.empty: return False
        
        # [핵심] 통데이터 날짜별 분리 저장 로직
        # 데이터 내의 'Snapshot_Date'별로 그룹화하여 날짜별로 각각 별도의 문서로 저장합니다.
        unique_dates = df['Snapshot_Date'].unique()
        
        for s_date in unique_dates:
            date_df = df[df['Snapshot_Date'] == s_date].copy()
            records = date_df.fillna(0).astype(str).to_dict(orient='records')
            
            # 파이어베이스에 날짜별로 문서 생성
            db.collection(COLLECTION_NAME).add({
                'data': records,
                'uploaded_at': datetime.now(),
                'snapshot_date': s_date
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
                snap_date = doc_dict.get('snapshot_date', '')
                rows = doc_dict['data']
                for row in rows:
                    if 'Snapshot_Date' not in row or not row['Snapshot_Date']:
                        row['Snapshot_Date'] = snap_date
                    all_data.append(row)
        return all_data
    except Exception as e:
        st.error(f"❌ 데이터 로드 오류: {e}")
        return []

def delete_all_data():
    try:
        docs = db.collection(COLLECTION_NAME).stream()
        cnt = 0
        for doc in docs:
            doc.reference.delete()
            cnt += 1
        return cnt
    except Exception as e:
        st.error(f"초기화 오류: {e}")
        return 0

# ==============================================================================
# 4. 파일 처리 로직 (날짜 강제 형변환 + 리드타임 자동 계산)
# ==============================================================================

def normalize_and_map_columns(df):
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
        'Account': ['거래처', '에이전시', 'source', 'account'],
        'Room_Type': ['객실타입', '룸타입', 'type']
    }
    for col in df.columns:
        clean = str(col).lower().replace(" ", "").replace("_", "")
        for target, kws in rules.items():
            if any(kw in clean for kw in kws):
                if target not in col_map.values():
                    col_map[col] = target; break
    return df.rename(columns=col_map)

def process_data(uploaded_file, status):
    try:
        # CSV 인코딩 cp949 적용 및 헤더 3행(Index 2) 고정
        if uploaded_file.name.endswith('.csv'):
            try: df_raw = pd.read_csv(uploaded_file, header=2, encoding='cp949')
            except: df_raw = pd.read_csv(uploaded_file, header=2)
        else:
            df_raw = pd.read_excel(uploaded_file, header=2)

        # 1. 조식 전수조사 (BF 스캔)
        def scan_bf(row):
            return 'Included (조식포함)' if 'BF' in "".join(row.astype(str).values).upper() else 'Not Included (불포함)'
        breakfast_col = df_raw.apply(scan_bf, axis=1)

        # 2. 컬럼 매핑
        df = normalize_and_map_columns(df_raw).copy()
        df['Breakfast'] = breakfast_col
        df['Status'] = status

        # 3. [핵심] 날짜 타입 강제 변환 (리드타임 계산 에러 방지)
        # 엑셀의 . 형식을 - 형식으로 바꾸어 계산 가능하게 만듭니다.
        for c in ['CheckIn', 'Booking_Date', 'Cancel_Date']:
            if c in df.columns:
                df[c] = pd.to_datetime(df[c].astype(str).str.replace('.', '-'), errors='coerce')

        # 4. [핵심] 리드타임(LT) 파이썬 직접 계산 (입실일 - 예약일)
        if 'CheckIn' in df.columns and 'Booking_Date' in df.columns:
            df['Lead_Time'] = (df['CheckIn'] - df['Booking_Date']).dt.days.fillna(0)
        else:
            df['Lead_Time'] = 0

        # 5. [핵심] 통데이터 날짜 분류 (Snapshot_Date 생성)
        # 예약 데이터는 '예약일' 기준, 취소 데이터는 '취소일' 기준으로 조회되게 만듭니다.
        if status == "Booked":
            df['Snapshot_Date'] = df['Booking_Date'].dt.strftime('%Y-%m-%d')
        else:
            df['Snapshot_Date'] = df['Cancel_Date'].dt.strftime('%Y-%m-%d')
        
        # 날짜 누락 데이터 방어
        df['Snapshot_Date'] = df['Snapshot_Date'].fillna(datetime.now().strftime('%Y-%m-%d'))

        # 6. 나머지 데이터 정리
        df['RN'] = pd.to_numeric(df.get('Rooms', 0), errors='coerce').fillna(0) * pd.to_numeric(df.get('Nights', 1).replace(0,1), errors='coerce').fillna(1)
        df['Stay_Month'] = df['CheckIn'].dt.strftime('%Y-%m')
        df['Booking_Month'] = df['Booking_Date'].dt.strftime('%Y-%m')
        df['Day_Type'] = df['CheckIn'].dt.weekday.apply(lambda x: 'Weekend' if x >= 4 else 'Weekday')
        
        def classify_nat(row):
            if re.search('[가-힣]', str(row.get('Guest_Name',''))): return 'KOR'
            return 'OTH'
        df['Nat_Group'] = df.apply(classify_nat, axis=1)

        return clean_numeric_columns(df)
            
    except Exception as e:
        st.error(f"⚠️ 파일 처리 오류: {e}")
        return pd.DataFrame()

def process_otb(uploaded_file):
    try:
        df_raw = pd.read_excel(uploaded_file, header=None) if not uploaded_file.name.endswith('.csv') else pd.read_csv(uploaded_file, header=None, encoding='cp949')
        rev = int(str(df_raw.dropna(how='all').dropna(axis=1, how='all').iloc[-1, -1]).replace(',', '').split('.')[0])
        return pd.DataFrame([{'CheckIn': datetime.now().strftime('%Y-%m-01'), 'Room_Revenue': rev, 'Total_Revenue': rev, 'RN': 0, 'Guest_Name': 'OTB', 'Segment': 'OTB', 'Snapshot_Date': datetime.now().strftime('%Y-%m-%d'), 'Status': 'Booked'}])
    except: return pd.DataFrame()

# ==============================================================================
# 5. UI 렌더링 헬퍼 함수들
# ==============================================================================

def add_total_row(df, group_col_name="구분"):
    if df.empty: return df
    numeric_df = df.select_dtypes(include=[np.number]).fillna(0)
    totals = numeric_df.sum().to_dict()
    total_row = {col: "" for col in df.columns}
    total_row.update(totals)
    total_row[group_col_name if group_col_name in df.columns else df.columns[0]] = "TOTAL"
    if 'RN' in total_row and total_row['RN'] > 0:
        if 'Room_Revenue' in total_row: total_row['ADR_Room'] = total_row['Room_Revenue'] / total_row['RN']
        if 'Total_Revenue' in total_row: total_row['ADR_Total'] = total_row['Total_Revenue'] / total_row['RN']
    return pd.concat([df, pd.DataFrame([total_row])], ignore_index=True)

def show_df_styled(df):
    if df.empty: st.write("데이터 없음"); return
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    styler = df.style.format({col: "{:,.0f}" for col in numeric_cols})
    st.dataframe(styler.apply(lambda r: ['background-color: #fff9c4; font-weight: 900; color: black; border-top: 2px solid black'] * len(r) if any(str(v) == "TOTAL" for v in r) else [''] * len(r), axis=1), hide_index=True, use_container_width=True)

def render_analysis_tabs(df, key_prefix):
    if df.empty: st.warning("데이터가 없습니다."); return
    t1, t2, t3, t4, t5, t6, t7, t8 = st.tabs(["📊 세그먼트", "📅 Pacing", "🏢 거래처", "⏳ 리드타임", "🛏️ 객실타입", "🗓️ 요일", "🌐 국적", "🍳 조식"])
    
    with t1:
        s = df.groupby('Segment').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.pie(s, values='Room_Revenue', names='Segment', title="매출 비중"), use_container_width=True, key=f"{key_prefix}_pie")
        c2.plotly_chart(px.bar(s, x='Segment', y='Room_Revenue', title="매출 규모"), use_container_width=True, key=f"{key_prefix}_bar")
        show_df_styled(add_total_row(s, 'Segment'))
    with t2:
        piv = df.pivot_table(index='Booking_Month', columns='Stay_Month', values='RN', aggfunc='sum').fillna(0)
        st.plotly_chart(px.imshow(piv, text_auto="d", aspect="auto", color_continuous_scale="Blues"), use_container_width=True, key=f"{key_prefix}_pace")
    with t3:
        a = df.groupby('Account').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index().sort_values('RN', ascending=False).head(50)
        show_df_styled(add_total_row(a, 'Account'))
    with t4:
        st.subheader("⏳ 리드타임 (파이썬 직접 계산)")
        bins = [-1, 0, 3, 7, 14, 30, 60, 90, 999]; labels = ['0일', '1-3일', '4-7일', '8-14일', '15-30일', '31-60일', '61-90일', '90일+']
        df['LT_G'] = pd.cut(df['Lead_Time'], bins=bins, labels=labels)
        l = df.groupby('LT_G', observed=True).agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
        st.plotly_chart(px.bar(l, x='LT_G', y='RN', title="리드타임별 박수"), use_container_width=True, key=f"{key_prefix}_lt")
        show_df_styled(add_total_row(l, 'LT_G'))
    with t5: show_df_styled(add_total_row(df.groupby('Room_Type').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index(), 'Room_Type'))
    with t6:
        w = df.groupby('Day_Type').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index()
        st.plotly_chart(px.bar(w, x='Day_Type', y='Room_Revenue'), use_container_width=True, key=f"{key_prefix}_wd")
    with t7: show_df_styled(add_total_row(df.groupby('Nat_Group').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index(), 'Nat_Group'))
    with t8:
        if 'Breakfast' in df.columns:
            b = df.groupby('Breakfast').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index()
            c1, c2 = st.columns(2)
            c1.plotly_chart(px.pie(b, values='RN', names='Breakfast', title="조식 비중"), use_container_width=True, key=f"{key_prefix}_bf_p")
            c2.plotly_chart(px.bar(b, x='Breakfast', y='Room_Revenue', title="조식 매출"), use_container_width=True, key=f"{key_prefix}_bf_b")
            show_df_styled(add_total_row(b, 'Breakfast'))

# ==============================================================================
# 6. 메인 실행부
# ==============================================================================
try:
    st.title("🏛️ 앰버 호텔 경영 리포트 (Final Integrity)")
    raw_data = load_data_from_firestore(); df_all = pd.DataFrame(raw_data) if raw_data else pd.DataFrame()
    available_dates = sorted(df_all['Snapshot_Date'].unique(), reverse=True) if not df_all.empty else []

    with st.sidebar:
        st.header("⚙️ 시스템 설정")
        if st.button("🚨 모든 실적 데이터 초기화"):
            cnt = delete_all_data(); st.warning(f"{cnt}개 데이터 삭제됨"); time.sleep(1); st.cache_data.clear(); st.rerun()
            
        selected_date = st.selectbox("조회 기준일 (실제 데이터 발생일)", available_dates, index=0) if available_dates else None
        st.markdown("---")
        st.header("📤 데이터 업로드")
        f1 = st.file_uploader("예약 리스트 (통데이터 가능)", type=['xlsx','csv'], key="f1")
        if f1 and st.button("예약 데이터 저장"):
            if save_to_firestore_split_by_date(process_data(f1, "Booked")): st.cache_data.clear(); st.rerun()
            
        f2 = st.file_uploader("취소 리스트 (통데이터 가능)", type=['xlsx','csv'], key="f2")
        if f2 and st.button("취소 데이터 저장"):
            if save_to_firestore_split_by_date(process_data(f2, "Cancelled")): st.cache_data.clear(); st.rerun()
            
        f3_list = st.file_uploader("OTB 통합 업로드", type=['xlsx','csv'], key="f3", accept_multiple_files=True)
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
            st.header(f"👑 총지배인 요약 ({selected_date} 실적)")
            b_rn, b_rev = df_bk['RN'].sum(), df_bk['Room_Revenue'].sum()
            c_rn, c_rev = df_cn['RN'].sum(), df_cn['Room_Revenue'].sum()
            b_los = b_rn / len(df_bk) if not df_bk.empty else 0
            c_los = c_rn / len(df_cn) if not df_cn.empty else 0
            
            st.markdown("#### ✅ 예약")
            c = st.columns(5)
            c[0].metric("RN", f"{b_rn:,.0f}"); c[1].metric("매출", f"{b_rev:,.0f}")
            c[2].metric("ADR", f"{b_rev/b_rn if b_rn>0 else 0:,.0f}")
            c[3].metric("LOS", f"{b_los:.1f}박"); c[4].metric("건수", f"{len(df_bk):,.0f}")
            
            st.markdown("#### ❌ 취소")
            cc = st.columns(5)
            cc[0].metric("RN", f"{c_rn:,.0f}"); cc[1].metric("매출", f"{c_rev:,.0f}")
            cc[2].metric("ADR", f"{c_rev/c_rn if c_rn>0 else 0:,.0f}")
            cc[3].metric("LOS", f"{c_los:.1f}박"); cc[4].metric("건수", f"{len(df_cn):,.0f}")
            st.divider()
            if not df_bk.empty: show_df_styled(add_total_row(df_bk.groupby('Segment').agg({'RN': 'sum','Room_Revenue': 'sum'}).reset_index(), 'Segment')) 

        with tabs[1]: render_analysis_tabs(df_bk, "booked")
        with tabs[2]: render_analysis_tabs(df_cn, "cancelled")
        with tabs[3]: render_analysis_tabs(pd.concat([df_bk, df_cn]), "total")
        with tabs[4]:
            if not df_otb.empty:
                df_otb['M'] = pd.to_datetime(df_otb['CheckIn']).dt.month
                otb_res = df_otb.groupby('M').agg({'Room_Revenue':'sum'}).reset_index()
                fin = pd.merge(pd.DataFrame({'M': range(1, 13)}), otb_res, on='M', how='left').fillna(0)
                fin['Budget'] = fin['M'].map(BUDGET_DATA).fillna(0)
                fig = go.Figure()
                fig.add_trace(go.Bar(x=fin['M'], y=fin['Room_Revenue'], name='OTB', text=(fin['Room_Revenue']/fin['Budget']*100).apply(lambda x: f"{x:.1f}%" if x>0 else ""), textposition='outside'))
                fig.add_trace(go.Scatter(x=fin['M'], y=fin['Budget'], name='Budget', line=dict(color='red', dash='dot')))
                st.plotly_chart(fig, use_container_width=True)
    else: st.info("👈 파일을 업로드하고 '저장' 버튼을 누르십시오.")
except Exception as e:
    st.error(f"🚨 시스템 오류: {e}")
