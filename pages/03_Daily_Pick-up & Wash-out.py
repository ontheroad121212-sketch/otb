import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
import re
from datetime import datetime, timedelta
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
    """
    통데이터(여러 날짜)를 받아서 날짜별로 쪼개어 파이어베이스에 저장하는 핵심 함수
    """
    try:
        if df.empty: return False
        
        # 데이터프레임 내의 Snapshot_Date(예약일/취소일) 별로 그룹화하여 저장
        if 'Snapshot_Date' in df.columns:
            unique_dates = df['Snapshot_Date'].unique()
            for s_date in unique_dates:
                # 해당 날짜 데이터만 필터링
                subset = df[df['Snapshot_Date'] == s_date].copy()
                if subset.empty: continue
                
                records = subset.fillna(0).astype(str).to_dict(orient='records')
                
                # 문서 ID를 (날짜_타입_시간)으로 생성하여 덮어쓰기 방지
                doc_type = subset['Status'].iloc[0] if 'Status' in subset.columns else 'Unknown'
                doc_id = f"{s_date}_{doc_type}_{int(time.time()*1000)}"
                
                db.collection(COLLECTION_NAME).document(doc_id).set({
                    'data': records,
                    'uploaded_at': datetime.now(),
                    'snapshot_date': s_date  # 실제 데이터 발생일
                })
        else:
            # 날짜 컬럼이 없으면(OTB 등) 오늘 날짜로 저장
            records = df.fillna(0).astype(str).to_dict(orient='records')
            today_str = datetime.now().strftime('%Y-%m-%d')
            doc_id = f"{today_str}_OTB_{int(time.time()*1000)}"
            db.collection(COLLECTION_NAME).document(doc_id).set({
                'data': records,
                'uploaded_at': datetime.now(),
                'snapshot_date': today_str
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
                doc_snap_date = doc_dict.get('snapshot_date', '')
                rows = doc_dict['data']
                for row in rows:
                    if 'Snapshot_Date' not in row or not row['Snapshot_Date']:
                        row['Snapshot_Date'] = doc_snap_date
                    all_data.append(row)
        return all_data
    except Exception as e:
        st.error(f"❌ 데이터 로드 중 오류 발생: {e}")
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
        st.error(f"삭제 중 오류 발생: {e}")
        return 0

# ==============================================================================
# 4. 파일 처리 로직 (리드타임 강제 계산 & OTB/국적 이식)
# ==============================================================================

def normalize_and_map_columns(df):
    col_map = {}
    rules = {
        'CheckIn': ['checkin', 'arrival', '입실', '일자', 'date'],
        'Guest_Name': ['guest', 'name', 'customer', '투숙객', '성명'],
        'Booking_Date': ['booking', 'create', 'res', '예약', '생성'],
        'Cancel_Date': ['cancel', '취소일', '취소'],
        'Rooms': ['room', 'qty', 'rmws', '객실수', '수량'],
        'Nights': ['night', 'los', '박수', '박'],
        'Room_Revenue': ['room_rev', 'revenue', 'roomrate', '객실료', '매출'],
        'Total_Revenue': ['total', 'amount', '총금액', '합계'],
        'Segment': ['segment', '세그먼트'],
        'Account': ['account', 'source', 'agent', '거래처', '에이전시'],
        'Room_Type': ['type', 'cat', '객실타입', '룸타입'],
        'Rate_Plan': ['rate', 'plan', '상품', '패키지', '프로모션'], 
        'Nat_Orig': ['nation', 'country', 'nat', '국적']
    }
    for col in df.columns:
        clean = str(col).lower().replace(" ", "").replace("_", "")
        for target, kws in rules.items():
            if any(kw in clean for kw in kws):
                if target not in col_map.values():
                    col_map[col] = target; break
    return df.rename(columns=col_map)

def process_data(uploaded_file, status, force_otb=False):
    try:
        is_otb = force_otb or "Sales on the Book" in uploaded_file.name
        
        # [1] 파일 읽기 (CSV cp949, 헤더 3행 고정)
        if uploaded_file.name.endswith('.csv'):
            try: df_raw = pd.read_csv(uploaded_file, header=2, encoding='cp949')
            except: df_raw = pd.read_csv(uploaded_file, header=2)
        else:
            df_raw = pd.read_excel(uploaded_file, header=2)

        # ---------------------------------------------------------
        # Case A: OTB (별도 함수로 처리하지 않고 여기서 통합 관리 가능하지만, 분리된 process_otb 사용 권장)
        # ---------------------------------------------------------
        if is_otb:
            return process_otb(uploaded_file) # 아래 정의된 OTB 함수 호출

        # ---------------------------------------------------------
        # Case B: 예약/취소 리스트
        # ---------------------------------------------------------
        
        # 1. 조식 전수조사
        def scan_bf(row):
            return 'Included (조식포함)' if 'BF' in "".join(row.astype(str).values).upper() else 'Not Included (불포함)'
        breakfast_col = df_raw.apply(scan_bf, axis=1)

        # 2. 컬럼 매핑
        df = normalize_and_map_columns(df_raw).copy()
        df['Breakfast'] = breakfast_col
        df['Status'] = status

        # 3. 날짜 타입 강제 변환 (리드타임 계산 및 분류용)
        for c in ['CheckIn', 'Booking_Date', 'Cancel_Date']:
            if c in df.columns:
                df[c] = pd.to_datetime(df[c].astype(str).str.replace('.', '-'), errors='coerce')

        # 4. [핵심] 리드타임 파이썬 직접 계산
        if 'CheckIn' in df.columns and 'Booking_Date' in df.columns:
            df['Lead_Time'] = (df['CheckIn'] - df['Booking_Date']).dt.days.fillna(0)
        else:
            df['Lead_Time'] = 0

        # 5. [핵심] 통데이터 날짜 분류 (Snapshot_Date 생성)
        target_date_col = 'Booking_Date' if status == "Booked" else 'Cancel_Date'
        
        if target_date_col in df.columns:
            # 해당 날짜를 문자열로 변환하여 Snapshot_Date로 사용 (이걸로 저장시 쪼개짐)
            df['Snapshot_Date'] = df[target_date_col].dt.strftime('%Y-%m-%d')
            df['Snapshot_Date'] = df['Snapshot_Date'].fillna(datetime.now().strftime('%Y-%m-%d'))
        else:
            df['Snapshot_Date'] = datetime.now().strftime('%Y-%m-%d')

        # 6. 데이터 정리 및 파생 변수
        df['RN'] = pd.to_numeric(df.get('Rooms', 0), errors='coerce').fillna(0) * pd.to_numeric(df.get('Nights', 1).replace(0,1), errors='coerce').fillna(1)
        df['Total_Revenue'] = np.where(df.get('Total_Revenue', 0) == 0, df.get('Room_Revenue', 0), df.get('Total_Revenue', 0))
        
        if 'CheckIn' in df.columns:
            df['Stay_Month'] = df['CheckIn'].dt.strftime('%Y-%m')
            df['Day_Type'] = df['CheckIn'].dt.weekday.apply(lambda x: 'Weekend' if x >= 4 else 'Weekday')
        
        if 'Booking_Date' in df.columns:
            df['Booking_Month'] = df['Booking_Date'].dt.strftime('%Y-%m')
        else:
            df['Booking_Month'] = df.get('Stay_Month', '')

        # 7. [국적 로직 강화]
        def classify_nat(row):
            name = str(row.get('Guest_Name',''))
            orig = str(row.get('Nat_Orig', '')).upper()
            if re.search('[가-힣]', name): return 'KOR'
            if any(x in orig for x in ['CHN', 'HKG', 'TWN', 'MAC']): return 'CHN'
            if any(x in orig for x in ['JPN']): return 'JPN'
            if any(x in orig for x in ['USA', 'CAN']): return 'AME'
            return 'OTH'
        df['Nat_Group'] = df.apply(classify_nat, axis=1)

        return clean_numeric_columns(df)
            
    except Exception as e:
        st.error(f"⚠️ 파일 처리 오류: {e}")
        return pd.DataFrame()

def process_otb(uploaded_file):
    try:
        # OTB 읽기 (헤더 없음 가정)
        if uploaded_file.name.endswith('.csv'):
            df_raw = pd.read_csv(uploaded_file, header=None, encoding='cp949')
        else:
            df_raw = pd.read_excel(uploaded_file, header=None)
            
        # OTB 날짜 찾기
        target_month_str = datetime.now().strftime('%Y-%m-%d')
        date_pattern = re.compile(r'20\d{2}-(\d{2})')
        
        # 파일 상단에서 날짜 스캔
        for r in range(min(15, len(df_raw))):
            row_str = " ".join(df_raw.iloc[r].astype(str).values)
            match = date_pattern.search(row_str)
            if match:
                # OTB는 보통 월단위이므로 해당월 1일로 설정하거나 오늘 날짜로 설정
                # 여기서는 "오늘 날짜"를 Snapshot Date로 사용하여 오늘자 OTB로 저장
                break
        
        # 총 매출 추출 (우하단 셀)
        df_clean = df_raw.dropna(how='all').dropna(axis=1, how='all')
        try:
            raw_val = str(df_clean.iloc[-1, -1])
            total_rev = int(raw_val.replace(',', '').split('.')[0])
        except: total_rev = 0
        
        return pd.DataFrame([{
            'CheckIn': datetime.now().strftime('%Y-%m-01'), # 더미 데이터
            'Room_Revenue': total_rev, 'Total_Revenue': total_rev, 'RN': 0,
            'Guest_Name': 'OTB_DATA', 'Segment': 'OTB', 'Account': 'OTB_Summary',
            'Room_Type': 'ROH', 'Nat_Orig': 'KR',
            'Snapshot_Date': datetime.now().strftime('%Y-%m-%d'), # 오늘 날짜 기준
            'Status': 'Booked'
        }])
    except Exception as e:
        st.error(f"OTB 처리 오류: {e}")
        return pd.DataFrame()

# ==============================================================================
# 5. UI 렌더링 헬퍼 함수들 (전체 기능 포함)
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
    if 'Budget_Achiev' in df.columns: styler = styler.format({'Budget_Achiev': "{:.1f}%"})
    
    def highlight_total(row):
        is_total = any(str(val) == "TOTAL" for val in row)
        return ['background-color: #fff9c4; font-weight: bold; color: black; border-top: 2px solid black'] * len(row) if is_total else [''] * len(row)
    st.dataframe(styler.apply(highlight_total, axis=1), hide_index=True, use_container_width=True)

def render_analysis_tab(target_df, title_prefix, unique_key, color_scale="Blues"):
    if target_df.empty: st.warning("데이터가 없습니다."); return
    
    t1, t2, t3, t4, t5, t6, t7, t8 = st.tabs(["📊 세그먼트", "📅 Pacing", "🏢 거래처", "⏳ 리드타임", "🛏️ 객실타입", "🗓️ 요일", "🌐 국적", "🍳 조식"])
    
    with t1:
        st.subheader("📊 세그먼트 분석")
        s = target_df.groupby('Segment').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.pie(s, values='Room_Revenue', names='Segment', title="매출 비중"), use_container_width=True, key=f"{unique_key}_pie")
        c2.plotly_chart(px.bar(s, x='Segment', y='Room_Revenue', title="매출 규모"), use_container_width=True, key=f"{unique_key}_bar")
        show_df_styled(add_total_row(s, 'Segment'))
    with t2:
        st.subheader("📅 Pacing Matrix")
        piv = target_df.pivot_table(index='Booking_Month', columns='Stay_Month', values='RN', aggfunc='sum').fillna(0)
        st.plotly_chart(px.imshow(piv, text_auto="d", aspect="auto", color_continuous_scale=color_scale), use_container_width=True, key=f"{unique_key}_pace")
    with t3:
        st.subheader("🏢 거래처 실적 (Top 50)")
        a = target_df.groupby('Account').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index().sort_values('RN', ascending=False).head(50)
        show_df_styled(add_total_row(a, 'Account'))
    with t4:
        st.subheader("⏳ 리드타임 (자동 계산)")
        bins = [-1, 0, 3, 7, 14, 30, 60, 90, 999]; labels = ['0일', '1-3일', '4-7일', '8-14일', '15-30일', '31-60일', '61-90일', '90일+']
        target_df['LT_G'] = pd.cut(target_df['Lead_Time'], bins=bins, labels=labels)
        l = target_df.groupby('LT_G', observed=True).agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
        st.plotly_chart(px.bar(l, x='LT_G', y='RN'), use_container_width=True, key=f"{unique_key}_lt")
        show_df_styled(add_total_row(l, 'LT_G'))
    with t5:
        st.subheader("🛏️ 객실 타입 선호도")
        show_df_styled(add_total_row(target_df.groupby('Room_Type').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index(), 'Room_Type'))
    with t6:
        st.subheader("🗓️ 요일별 패턴")
        w = target_df.groupby('Day_Type').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index()
        st.plotly_chart(px.bar(w, x='Day_Type', y='Room_Revenue'), use_container_width=True, key=f"{unique_key}_wd")
    with t7:
        st.subheader("🌐 국적 비중 (상세)")
        show_df_styled(add_total_row(target_df.groupby('Nat_Group').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index(), 'Nat_Group'))
    with t8:
        st.subheader("🍳 조식 분석")
        if 'Breakfast' in target_df.columns:
            b = target_df.groupby('Breakfast').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index()
            c1, c2 = st.columns(2)
            c1.plotly_chart(px.pie(b, values='RN', names='Breakfast'), use_container_width=True, key=f"{unique_key}_bf_p")
            show_df_styled(add_total_row(b, 'Breakfast'))

# ==============================================================================
# 6. 메인 실행부
# ==============================================================================
try:
    st.title("🏛️ 앰버 호텔 경영 리포트 (Final Integrity)")
    raw_data = load_data_from_firestore()
    df_all = pd.DataFrame(raw_data) if raw_data else pd.DataFrame()
    available_dates = sorted(df_all['Snapshot_Date'].unique(), reverse=True) if not df_all.empty else []

    with st.sidebar:
        st.header("⚙️ 시스템 설정")
        if st.button("🚨 모든 데이터 초기화"):
            cnt = delete_all_data(); st.warning(f"{cnt}개 문서 삭제됨"); time.sleep(1); st.cache_data.clear(); st.rerun()
            
        selected_date = st.selectbox("조회 기준일 (데이터 발생일)", available_dates, index=0) if available_dates else None
        st.markdown("---")
        st.header("📤 데이터 업로드")
        f1 = st.file_uploader("예약 리스트 (통데이터 가능)", type=['xlsx','csv'], key="f1")
        if f1 and st.button("예약 저장"):
            # 예약일 기준으로 쪼개서 저장
            if save_to_firestore_split_by_date(process_data(f1, "Booked")): st.cache_data.clear(); st.rerun()
            
        f2 = st.file_uploader("취소 리스트 (통데이터 가능)", type=['xlsx','csv'], key="f2")
        if f2 and st.button("취소 저장"):
            # 취소일 기준으로 쪼개서 저장
            if save_to_firestore_split_by_date(process_data(f2, "Cancelled")): st.cache_data.clear(); st.rerun()
            
        f3_list = st.file_uploader("OTB 파일", type=['xlsx','csv'], key="f3", accept_multiple_files=True)
        if f3_list and st.button("OTB 저장"):
            # OTB는 각각 처리 후 오늘 날짜 등으로 저장
            all_otb = [process_otb(f) for f in f3_list]
            if all_otb and save_to_firestore_split_by_date(pd.concat(all_otb, ignore_index=True)): st.cache_data.clear(); st.rerun()

    if selected_date and not df_all.empty:
        # 선택한 날짜의 데이터만 필터링
        df = clean_numeric_columns(df_all[df_all['Snapshot_Date'] == selected_date].copy())
        
        df_otb = df[df['Segment'].astype(str).str.contains('OTB')]
        df_list = df[~df['Segment'].astype(str).str.contains('OTB')]
        df_bk = df_list[(df_list['Status'] == 'Booked') & (df_list['Total_Revenue'] > 0)]
        df_cn = df_list[df_list['Status'] == 'Cancelled']
        df_zero = df_list[(df_list['Status'] == 'Booked') & (df_list['Total_Revenue'] <= 0)]

        tabs = st.tabs(["👑 GM 요약", "✅ 예약 상세", "❌ 취소 상세", "📈 종합 합계", "🆓 0원 예약", "🎯 OTB 현황"])

        with tabs[0]:
            st.header(f"👑 총지배인 요약 ({selected_date} 실적)")
            b_rn, b_rev = df_bk['RN'].sum(), df_bk['Room_Revenue'].sum()
            c_rn, c_rev = df_cn['RN'].sum(), df_cn['Room_Revenue'].sum()
            b_los = b_rn / len(df_bk) if not df_bk.empty else 0
            c_los = c_rn / len(df_cn) if not df_cn.empty else 0
            
            st.markdown("#### ✅ 예약 실적")
            c = st.columns(5)
            c[0].metric("RN", f"{b_rn:,.0f}"); c[1].metric("매출", f"{b_rev:,.0f}")
            c[2].metric("ADR", f"{b_rev/b_rn if b_rn>0 else 0:,.0f}")
            c[3].metric("LOS", f"{b_los:.1f}박"); c[4].metric("건수", f"{len(df_bk):,.0f}")
            
            st.markdown("#### ❌ 취소 실적")
            cc = st.columns(5)
            cc[0].metric("RN", f"{c_rn:,.0f}"); cc[1].metric("매출", f"{c_rev:,.0f}")
            cc[2].metric("ADR", f"{c_rev/c_rn if c_rn>0 else 0:,.0f}")
            cc[3].metric("LOS", f"{c_los:.1f}박"); cc[4].metric("건수", f"{len(df_cn):,.0f}")
            st.divider(); 
            if not df_bk.empty: show_df_styled(add_total_row(df_bk.groupby('Segment').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index(), 'Segment')) 

        with tabs[1]: render_analysis_tab(df_bk, "bk_u", "blue")
        with tabs[2]: render_analysis_tab(df_cn, "cn_u", "red")
        with tabs[3]: render_analysis_tab(pd.concat([df_bk, df_cn]), "tot_u", "green")
        with tabs[4]: 
            st.subheader(f"🆓 0원 예약 (총 {len(df_zero)}건)")
            st.dataframe(df_zero[['Guest_Name', 'CheckIn', 'Account', 'Room_Type']], use_container_width=True)
        with tabs[5]:
            if not df_otb.empty:
                df_otb['M'] = pd.to_datetime(df_otb['CheckIn']).dt.month
                res = df_otb.groupby('M').agg({'Room_Revenue':'sum'}).reset_index()
                fin = pd.merge(pd.DataFrame({'M': range(1, 13)}), res, on='M', how='left').fillna(0)
                fin['Budget'] = fin['M'].map(BUDGET_DATA).fillna(0)
                fig = go.Figure()
                fig.add_trace(go.Bar(x=fin['M'], y=fin['Room_Revenue'], name='OTB', text=(fin['Room_Revenue']/fin['Budget']*100).apply(lambda x: f"{x:.1f}%" if x>0 else ""), textposition='outside'))
                fig.add_trace(go.Scatter(x=fin['M'], y=fin['Budget'], name='Budget', line=dict(color='red', dash='dot')))
                st.plotly_chart(fig, use_container_width=True)
                
                # OTB 테이블
                res_dict = {}
                tb, to = fin['Budget'].sum(), fin['Room_Revenue'].sum()
                for _, r in fin.iterrows(): res_dict[f"{r['M']}월"] = [f"{r['Budget']:,.0f}", f"{r['Room_Revenue']:,.0f}", f"{(r['Room_Revenue']/r['Budget']*100 if r['Budget']>0 else 0):.1f}%"]
                res_dict['Total'] = [f"{tb:,.0f}", f"{to:,.0f}", f"{(to/tb*100 if tb>0 else 0):.1f}%"]
                st.dataframe(pd.DataFrame(res_dict, index=['Budget', 'OTB', 'Achiev%']).T)
            else: st.warning("OTB 데이터 없음")

    else: st.info("👈 왼쪽 사이드바에서 파일을 업로드하고 '저장' 버튼을 눌러주세요.")
except Exception as e:
    st.error(f"🚨 시스템 오류: {e}")
