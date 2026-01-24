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
# 1. 기본 설정 및 Firebase 연결
# ==============================================================================
st.set_page_config(page_title="ARI Final Integrity", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
    .block-container { padding-top: 1rem; padding-bottom: 5rem; }
    div[data-testid="stMetricValue"] { font-size: 26px !important; font-weight: 900; color: #0f172a; }
    div[data-testid="stMetricLabel"] { font-size: 15px !important; font-weight: 700; color: #64748b; }
    [data-testid="stDataFrame"] table tr:last-child td {
        font-weight: 900 !important; background-color: #fff9c4 !important; border-top: 2px solid #000000 !important;
    }
</style>
""", unsafe_allow_html=True)

BUDGET_DATA = { 
    1: 514992575, 2: 786570856, 3: 529599040, 4: 695351004,
    5: 903705440, 6: 808203820, 7: 1231949142, 8: 1388376999,
    9: 952171506, 10: 897171539, 11: 667146771, 12: 804030110 
}

if not firebase_admin._apps:
    try:
        cred = credentials.Certificate(dict(st.secrets["firebase"]))
        firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"🔥 DB 연결 실패: {e}"); st.stop()

db = firestore.client()
COLLECTION_NAME = "revenue_integrity_history"

# ==============================================================================
# 2. 데이터 처리 및 유틸리티 함수 (함수 정의 최상단 배치)
# ==============================================================================

def clean_num(val):
    """개별 값 숫자 변환"""
    try:
        if pd.isna(val) or val == '': return 0
        s = str(val).replace(',', '').replace('₩', '').replace(' ', '').strip()
        return float(s)
    except: return 0

def clean_numeric_columns(df):
    """데이터프레임 전체 숫자 컬럼 정리"""
    target_cols = ['RN', 'Room_Revenue', 'Total_Revenue', 'Rooms', 'Nights', 'Lead_Time', 'ADR_Room', 'ADR_Total']
    for col in target_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', '').str.replace('nan', '0').str.replace('₩', ''), errors='coerce').fillna(0)
    return df

def save_to_db(df, is_otb=False):
    if df.empty: return False
    try:
        if 'Snapshot_Date' not in df.columns: df['Snapshot_Date'] = datetime.now().strftime('%Y-%m-%d')
        dates = df['Snapshot_Date'].unique()
        for d in dates:
            sub = df[df['Snapshot_Date'] == d].copy()
            if sub.empty: continue
            
            # 날짜 객체 문자열 변환
            for c in sub.select_dtypes(include=['datetime64[ns]']).columns:
                sub[c] = sub[c].astype(str)
                
            recs = sub.to_dict(orient='records')
            dtype = 'OTB' if is_otb else 'Reservation'
            
            # 예약/취소 상태 구분 ID
            status_tag = ""
            if not is_otb and 'Status' in sub.columns:
                status_tag = f"_{sub['Status'].iloc[0]}"
                
            did = f"{d}_{dtype}{status_tag}_{int(time.time()*1000)}"
            db.collection(COLLECTION_NAME).document(did).set({
                'data': recs, 'uploaded_at': datetime.now(), 'snapshot_date': d, 'data_type': dtype
            })
        return True
    except Exception as e: st.error(f"저장 실패: {e}"); return False

@st.cache_data(ttl=0)
def load_db():
    try:
        docs = db.collection(COLLECTION_NAME).stream(); res = []
        for d in docs:
            dd = d.to_dict()
            snap = dd.get('snapshot_date', '')
            dtype = dd.get('data_type', 'Reservation')
            if dtype == 'Reservation' and len(dd['data'])>0 and 'OTB' in str(dd['data'][0].get('Segment','')): dtype = 'OTB'
            for r in dd['data']:
                if 'Snapshot_Date' not in r: r['Snapshot_Date'] = snap
                r['Data_Type'] = dtype
                res.append(r)
        return res
    except: return []

def delete_otb():
    try:
        docs = db.collection(COLLECTION_NAME).stream(); c=0
        for d in docs:
            dd = d.to_dict()
            if dd.get('data_type') == 'OTB': d.reference.delete(); c+=1
            elif 'data' in dd and any('OTB' in str(x.get('Segment','')) for x in dd['data']): d.reference.delete(); c+=1
        return c
    except: return 0

def delete_all():
    try:
        docs = db.collection(COLLECTION_NAME).stream(); c=0
        for d in docs: d.reference.delete(); c+=1
        return c
    except: return 0

# ==============================================================================
# 3. 파일 처리 로직 (위치 기반 매핑 & RN 직접 계산)
# ==============================================================================

def process_reservation_file(file):
    try:
        if file.name.endswith('.csv'):
            try: df_raw = pd.read_csv(file, header=2, encoding='cp949')
            except: df_raw = pd.read_csv(file, header=2)
        else: df_raw = pd.read_excel(file, header=2)
            
        if len(df_raw.columns) <= 30:
            st.error(f"🚨 예약 파일 컬럼 부족 ({len(df_raw.columns)}개). AE열(30번)까지 필요합니다."); return pd.DataFrame()

        df = pd.DataFrame()
        df['Status'] = df_raw.iloc[:, 1] # B
        df['Res_No'] = df_raw.iloc[:, 2] # C
        df['Guest_Name'] = df_raw.iloc[:, 5] # F
        df['CheckIn'] = pd.to_datetime(df_raw.iloc[:, 6], errors='coerce') # G
        df['Nights'] = df_raw.iloc[:, 8].apply(clean_num) # I
        df['Room_Type'] = df_raw.iloc[:, 9] # J
        df['Rooms'] = df_raw.iloc[:, 11].apply(clean_num) # L
        df['Room_Revenue'] = df_raw.iloc[:, 13].apply(clean_num) # N
        df['Total_Revenue'] = df_raw.iloc[:, 15].apply(clean_num) # P
        df['Account'] = df_raw.iloc[:, 16] # Q
        df['Segment'] = df_raw.iloc[:, 17] # R
        df['Nat_Orig'] = df_raw.iloc[:, 23] # X
        df['Booking_Date'] = pd.to_datetime(df_raw.iloc[:, 30], errors='coerce') # AE

        # RN & 리드타임 직접 계산 (제한 없음)
        df['Rooms'] = np.where(df['Rooms'] <= 0, 1, df['Rooms'])
        df['Nights'] = np.where(df['Nights'] <= 0, 1, df['Nights'])
        df['RN'] = df['Rooms'] * df['Nights']
        df['Lead_Time'] = (df['CheckIn'] - df['Booking_Date']).dt.days.fillna(0)
        
        df['Total_Revenue'] = np.where(df['Total_Revenue'] == 0, df['Room_Revenue'], df['Total_Revenue'])
        df['Snapshot_Date'] = df['Booking_Date'].dt.strftime('%Y-%m-%d').fillna(datetime.now().strftime('%Y-%m-%d'))
        
        df['Stay_Month'] = df['CheckIn'].dt.strftime('%Y-%m')
        df['Booking_Month'] = df['Booking_Date'].dt.strftime('%Y-%m')
        df['Day_Type'] = df['CheckIn'].dt.weekday.apply(lambda x: 'Weekend' if x >= 4 else 'Weekday')
        
        def classify_nat(val):
            val = str(val).upper()
            if 'KOR' in val: return 'KOR'
            if any(x in val for x in ['CHN', 'HKG', 'TWN']): return 'CHN'
            if 'JPN' in val: return 'JPN'
            return 'OTH'
        df['Nat_Group'] = df['Nat_Orig'].apply(classify_nat)
        
        raw_str = df_raw.astype(str).agg(''.join, axis=1).str.upper()
        df['Breakfast'] = np.where(raw_str.str.contains('BF'), 'Included', 'Not Included')

        return df
    except Exception as e: st.error(f"예약 파일 오류: {e}"); return pd.DataFrame()

def process_cancellation_file(file):
    try:
        if file.name.endswith('.csv'):
            try: df_raw = pd.read_csv(file, header=2, encoding='cp949')
            except: df_raw = pd.read_csv(file, header=2)
        else: df_raw = pd.read_excel(file, header=2)
            
        if len(df_raw.columns) <= 27:
            st.error(f"🚨 취소 파일 컬럼 부족 ({len(df_raw.columns)}개). AB열(27번)까지 필요합니다."); return pd.DataFrame()

        df = pd.DataFrame()
        df['Status'] = df_raw.iloc[:, 1] # B
        df['Res_No'] = df_raw.iloc[:, 2] # C
        df['Guest_Name'] = df_raw.iloc[:, 5] # F
        df['CheckIn'] = pd.to_datetime(df_raw.iloc[:, 6], errors='coerce') # G
        df['Nights'] = df_raw.iloc[:, 8].apply(clean_num) # I
        df['Room_Type'] = df_raw.iloc[:, 9] # J
        df['Rooms'] = df_raw.iloc[:, 11].apply(clean_num) # L
        df['Room_Revenue'] = df_raw.iloc[:, 13].apply(clean_num) # N
        df['Total_Revenue'] = df_raw.iloc[:, 15].apply(clean_num) # P
        df['Account'] = df_raw.iloc[:, 16] # Q
        df['Segment'] = df_raw.iloc[:, 17] # R
        df['Nat_Orig'] = df_raw.iloc[:, 23] # X
        df['Booking_Date'] = pd.to_datetime(df_raw.iloc[:, 26], errors='coerce') # AA
        df['Cancel_Date'] = pd.to_datetime(df_raw.iloc[:, 27], errors='coerce') # AB

        df['Rooms'] = np.where(df['Rooms'] <= 0, 1, df['Rooms'])
        df['Nights'] = np.where(df['Nights'] <= 0, 1, df['Nights'])
        df['RN'] = df['Rooms'] * df['Nights']
        df['Lead_Time'] = (df['CheckIn'] - df['Booking_Date']).dt.days.fillna(0)
        
        df['Total_Revenue'] = np.where(df['Total_Revenue'] == 0, df['Room_Revenue'], df['Total_Revenue'])
        df['Snapshot_Date'] = df['Cancel_Date'].dt.strftime('%Y-%m-%d').fillna(datetime.now().strftime('%Y-%m-%d'))
        
        df['Stay_Month'] = df['CheckIn'].dt.strftime('%Y-%m')
        df['Booking_Month'] = df['Booking_Date'].dt.strftime('%Y-%m')
        df['Day_Type'] = df['CheckIn'].dt.weekday.apply(lambda x: 'Weekend' if x >= 4 else 'Weekday')
        
        def classify_nat(val):
            val = str(val).upper()
            if 'KOR' in val: return 'KOR'
            if any(x in val for x in ['CHN', 'HKG']): return 'CHN'
            return 'OTH'
        df['Nat_Group'] = df['Nat_Orig'].apply(classify_nat)
        
        raw_str = df_raw.astype(str).agg(''.join, axis=1).str.upper()
        df['Breakfast'] = np.where(raw_str.str.contains('BF'), 'Included', 'Not Included')

        return df
    except Exception as e: st.error(f"취소 파일 오류: {e}"); return pd.DataFrame()

def process_otb(file):
    try:
        fname_date = None
        match = re.search(r'(\d{8})', file.name)
        if match:
            d = match.group(1)
            fname_date = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        
        if file.name.endswith('.csv'): df_raw = pd.read_csv(file, header=None, encoding='cp949')
        else: df_raw = pd.read_excel(file, header=None)
            
        target_month_str = datetime.now().strftime('%Y-%m-%d')
        date_pattern = re.compile(r'20\d{2}-(\d{2})')
        for r in range(min(15, len(df_raw))):
            row_str = " ".join(df_raw.iloc[r].astype(str).values)
            match = date_pattern.search(row_str)
            if match: target_month_str = f"2026-{match.group(1)}-01"; break
        
        df_clean = df_raw.dropna(how='all').dropna(axis=1, how='all')
        try:
            raw_val = str(df_clean.iloc[-1, -1])
            total_rev = int(raw_val.replace(',', '').split('.')[0])
        except: total_rev = 0
        
        snap = fname_date if fname_date else datetime.now().strftime('%Y-%m-%d')

        return pd.DataFrame([{
            'CheckIn': target_month_str,
            'Room_Revenue': total_rev, 'Total_Revenue': total_rev, 'RN': 0,
            'Guest_Name': 'OTB', 'Segment': 'OTB', 'Snapshot_Date': snap, 'Status': 'Booked'
        }])
    except: return pd.DataFrame()

# ==============================================================================
# 4. UI 헬퍼 함수 (정의 먼저!)
# ==============================================================================

def add_total(df, key):
    if df.empty: return df
    num = df.select_dtypes(include=[np.number]).fillna(0)
    row = {c: "" for c in df.columns}; row.update(num.sum().to_dict())
    row[key] = "TOTAL"
    if row.get('RN', 0) > 0:
        if 'Room_Revenue' in row: row['ADR_Room'] = row['Room_Revenue'] / row['RN']
    return pd.concat([df, pd.DataFrame([row])], ignore_index=True)

def show_styled(df):
    if df.empty: st.info("데이터 없음"); return
    cols = df.select_dtypes(include=[np.number]).columns
    st.dataframe(df.style.format({c: "{:,.0f}" for c in cols}).apply(lambda r: ['background-color: #fff9c4; font-weight: bold; border-top: 2px solid black']*len(r) if str(r[0])=="TOTAL" else ['']*len(r), axis=1), hide_index=True, use_container_width=True)

def render_tab(df, k):
    if df.empty: st.info("데이터 없음"); return
    t1, t2, t3, t4, t5, t6, t7, t8 = st.tabs(["📊 세그먼트", "📅 Pacing", "🏢 거래처", "⏳ 리드타임", "🛏️ 객실타입", "🗓️ 요일", "🌐 국적", "🍳 조식"])
    with t1:
        s = df.groupby('Segment').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index()
        c1,c2 = st.columns(2)
        c1.plotly_chart(px.pie(s, values='Room_Revenue', names='Segment'), use_container_width=True, key=f"{k}_p")
        c2.plotly_chart(px.bar(s, x='Segment', y='Room_Revenue'), use_container_width=True, key=f"{k}_b")
        show_styled(add_total(s, 'Segment'))
    with t2:
        p = df.pivot_table(index='Booking_Month', columns='Stay_Month', values='RN', aggfunc='sum').fillna(0)
        st.plotly_chart(px.imshow(p, text_auto=True), use_container_width=True, key=f"{k}_pace")
    with t3: show_styled(add_total(df.groupby('Account').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index().sort_values('RN', ascending=False).head(50), 'Account'))
    with t4:
        df['LT_G'] = pd.cut(df['Lead_Time'], bins=[-1,0,3,7,14,30,60,90,999], labels=['0','1-3','4-7','8-14','15-30','31-60','61-90','90+'])
        l = df.groupby('LT_G', observed=True).agg({'RN':'sum','Room_Revenue':'sum'}).reset_index()
        st.plotly_chart(px.bar(l, x='LT_G', y='RN'), use_container_width=True, key=f"{k}_lt")
        show_styled(add_total(l, 'LT_G'))
    with t5: show_styled(add_total(df.groupby('Room_Type').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index(), 'Room_Type'))
    with t6:
        w = df.groupby('Day_Type').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index()
        st.plotly_chart(px.bar(w, x='Day_Type', y='Room_Revenue'), use_container_width=True, key=f"{k}_w")
    with t7: show_styled(add_total(df.groupby('Nat_Group').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index(), 'Nat_Group'))
    with t8:
        b = df.groupby('Breakfast').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index()
        st.plotly_chart(px.pie(b, values='RN', names='Breakfast'), use_container_width=True, key=f"{k}_bf")
        show_styled(add_total(b, 'Breakfast'))

# ==============================================================================
# 6. 메인 실행부
# ==============================================================================
try:
    st.title("🏛️ 앰버 호텔 경영 리포트 (Final Integrity)")
    raw = load_db()
    if raw: df_all = pd.DataFrame(raw)
    else: df_all = pd.DataFrame(columns=['Snapshot_Date','Data_Type'])
    
    # [핵심] 날짜 분리 & 오늘 날짜 차단
    today_str = datetime.now().strftime('%Y-%m-%d')
    res_dates_all = sorted(df_all[df_all['Data_Type']=='Reservation']['Snapshot_Date'].unique(), reverse=True)
    res_dates = [d for d in res_dates_all if d != today_str] # 오늘 날짜 강제 제외
    
    otb_dates = sorted(df_all[df_all['Data_Type']=='OTB']['Snapshot_Date'].unique(), reverse=True)

    with st.sidebar:
        st.header("설정")
        if st.button("🗑️ OTB 초기화"): d=delete_otb(); st.warning(f"{d}건 삭제"); time.sleep(1); st.rerun()
        if st.button("🚨 전체 초기화"): d=delete_all(); st.warning(f"{d}건 삭제"); time.sleep(1); st.rerun()
        
        st.divider()
        sel_res = st.selectbox("📌 예약/취소 조회", res_dates) if res_dates else None
        sel_otb = st.selectbox("📈 OTB 조회", otb_dates) if otb_dates else None
        
        st.divider()
        f1 = st.file_uploader("예약 리스트 (AE=예약일)", type=['xlsx','csv'])
        if f1 and st.button("예약 저장"):
            if save_to_db(process_reservation_file(f1)): st.rerun()
        f2 = st.file_uploader("취소 리스트 (AA=예약일)", type=['xlsx','csv'])
        if f2 and st.button("취소 저장"):
            if save_to_db(process_cancellation_file(f2)): st.rerun()
        f3 = st.file_uploader("OTB 파일 (파일명 날짜)", type=['xlsx','csv'], accept_multiple_files=True)
        if f3 and st.button("OTB 저장"):
            for f in f3: save_to_db(process_otb(f), is_otb=True)
            st.rerun()

    # 데이터 로드
    if sel_res and not df_all.empty:
        df_r = df_all[(df_all['Snapshot_Date']==sel_res) & (df_all['Data_Type']=='Reservation')].copy()
        df_r = clean_numeric_columns(df_r) # 숫자 정리
        
        df_bk = df_r[(df_r['Status']=='RR') & (df_r['Total_Revenue']>0)] # 예약(RR) & 유료
        df_zero = df_r[(df_r['Status']=='RR') & (df_r['Total_Revenue']<=0)] # 0원
        df_cn = df_r[df_r['Status']=='RC'] # 취소(RC)
        df_tot = pd.concat([df_bk, df_cn])
    else:
        df_bk, df_zero, df_cn, df_tot = pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    if sel_otb and not df_all.empty:
        df_o = df_all[(df_all['Snapshot_Date']==sel_otb) & (df_all['Data_Type']=='OTB')].copy()
        df_o['Room_Revenue'] = pd.to_numeric(df_o['Room_Revenue'], errors='coerce').fillna(0)
    else: df_o = pd.DataFrame()

    # 탭
    tabs = st.tabs(["👑 GM 요약", "✅ 예약 상세", "❌ 취소 상세", "📈 종합 합계", "🆓 0원 예약", "🎯 OTB 현황"])
    
    with tabs[0]:
        st.header(f"👑 GM 요약 ({sel_res})")
        if df_bk.empty and df_cn.empty: st.info("데이터 없음")
        else:
            b_rn, b_rev = df_bk['RN'].sum(), df_bk['Room_Revenue'].sum()
            c_rn, c_rev = df_cn['RN'].sum(), df_cn['Room_Revenue'].sum()
            b_los = b_rn/len(df_bk) if len(df_bk)>0 else 0
            c_los = c_rn/len(df_cn) if len(df_cn)>0 else 0
            
            st.markdown("#### ✅ 예약")
            c = st.columns(5)
            c[0].metric("RN", f"{b_rn:,.0f}")
            c[1].metric("매출", f"{b_rev:,.0f}")
            c[2].metric("ADR", f"{b_rev/b_rn if b_rn>0 else 0:,.0f}")
            c[3].metric("LOS", f"{b_los:.1f}박")
            c[4].metric("건수", f"{len(df_bk):,.0f}")
            
            st.markdown("#### ❌ 취소")
            c = st.columns(5)
            c[0].metric("RN", f"{c_rn:,.0f}")
            c[1].metric("매출", f"{c_rev:,.0f}")
            c[2].metric("ADR", f"{c_rev/c_rn if c_rn>0 else 0:,.0f}")
            c[3].metric("LOS", f"{c_los:.1f}박")
            c[4].metric("건수", f"{len(df_cn):,.0f}")
            st.divider()
            if not df_bk.empty: show_styled(add_total(df_bk.groupby('Segment').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index(), 'Segment'))

    with tabs[1]: render_tab(df_bk, "bk")
    with tabs[2]: render_tab(df_cn, "cn")
    with tabs[3]: render_tab(df_tot, "tot")
    with tabs[4]: 
        st.subheader(f"🆓 0원 예약 ({len(df_zero)}건)")
        if not df_zero.empty: st.dataframe(df_zero[['Guest_Name','CheckIn','Account','Room_Type']], use_container_width=True)
    with tabs[5]:
        st.header(f"🎯 OTB ({sel_otb})")
        if df_o.empty: st.warning("데이터 없음")
        else:
            df_o['M'] = pd.to_datetime(df_o['CheckIn']).dt.month
            grp = df_o.groupby('M').agg({'Room_Revenue':'sum'}).reset_index()
            fin = pd.merge(pd.DataFrame({'M': range(1,13)}), grp, on='M', how='left').fillna(0)
            fin['Budget'] = fin['M'].map(BUDGET_DATA).fillna(0)
            fin['Name'] = fin['M'].astype(str) + "월"
            fin['Rate'] = np.where(fin['Budget']>0, (fin['Room_Revenue']/fin['Budget'])*100, 0)
            
            fig = go.Figure()
            fig.add_trace(go.Bar(x=fin['Name'], y=fin['Room_Revenue'], name='OTB', text=fin['Rate'].apply(lambda x:f"{x:.1f}%")))
            fig.add_trace(go.Scatter(x=fin['Name'], y=fin['Budget'], name='Budget', line=dict(color='red', dash='dot')))
            st.plotly_chart(fig, use_container_width=True)
            
            res = {}
            for _,r in fin.iterrows(): res[r['Name']] = [f"{r['Budget']:,.0f}", f"{r['Room_Revenue']:,.0f}", f"{r['Rate']:.1f}%"]
            st.dataframe(pd.DataFrame(res, index=['Budget','OTB','Achiev']).T, use_container_width=True)

except Exception as e: st.error(f"오류: {e}")
