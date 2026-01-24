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
# 1. 기본 설정 및 CSS
# ==============================================================================
st.set_page_config(page_title="ARI Final Integrity", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
    .block-container { padding-top: 1rem; padding-bottom: 5rem; }
    div[data-testid="stMetricValue"] { font-size: 24px !important; font-weight: 900; color: #0f172a; }
    div[data-testid="stMetricLabel"] { font-size: 14px !important; font-weight: 700; color: #64748b; }
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
# 3. 데이터 유틸리티
# ==============================================================================

def clean_num(val):
    """개별 값 숫자 변환"""
    try:
        if pd.isna(val) or val == '': return 0
        s = str(val).replace(',', '').replace('₩', '').replace(' ', '').strip()
        return float(s)
    except: return 0

def save_to_db(df, data_type='Reservation'):
    """데이터를 날짜별로 쪼개서 저장"""
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
            
            # 문서 ID 생성 (날짜_타입_시간)
            did = f"{d}_{data_type}_{int(time.time()*1000)}"
            
            db.collection(COLLECTION_NAME).document(did).set({
                'data': recs, 'uploaded_at': datetime.now(), 'snapshot_date': d, 'data_type': data_type
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
            
            # 구버전 데이터 호환
            if dtype == 'Reservation' and len(dd['data']) > 0 and 'OTB' in str(dd['data'][0].get('Segment', '')):
                dtype = 'OTB'

            for r in dd['data']:
                if 'Snapshot_Date' not in r: r['Snapshot_Date'] = snap
                r['Data_Type'] = dtype
                res.append(r)
        return res
    except: return []

def delete_all():
    try:
        docs = db.collection(COLLECTION_NAME).stream(); c=0
        for d in docs: d.reference.delete(); c+=1
        return c
    except: return 0

def delete_otb():
    try:
        docs = db.collection(COLLECTION_NAME).stream(); c=0
        for d in docs:
            dd = d.to_dict()
            if dd.get('data_type') == 'OTB': d.reference.delete(); c+=1
            elif 'data' in dd and any('OTB' in str(x.get('Segment','')) for x in dd['data']): d.reference.delete(); c+=1
        return c
    except: return 0

# ==============================================================================
# 4. 파일 처리 로직 (컬럼 위치 정밀 타격 & RN 직접 계산)
# ==============================================================================

def process_res_file(file):
    """예약 리스트: AE(30)=예약일, L(11)=객실수, I(8)=박수"""
    try:
        if file.name.endswith('.csv'):
            try: df_raw = pd.read_csv(file, header=2, encoding='cp949')
            except: df_raw = pd.read_csv(file, header=2)
        else: df_raw = pd.read_excel(file, header=2)
            
        if len(df_raw.columns) <= 30:
            st.error("🚨 예약 파일 컬럼 부족. AE열(30번)까지 필요합니다."); return pd.DataFrame()

        df = pd.DataFrame()
        # [위치 기반 매핑]
        df['Status'] = df_raw.iloc[:, 1] # B
        df['Res_No'] = df_raw.iloc[:, 2] # C
        df['Guest_Name'] = df_raw.iloc[:, 5] # F
        df['CheckIn'] = pd.to_datetime(df_raw.iloc[:, 6], errors='coerce') # G
        df['CheckOut'] = pd.to_datetime(df_raw.iloc[:, 7], errors='coerce') # H
        df['Nights'] = df_raw.iloc[:, 8].apply(clean_num) # I (박수)
        df['Room_Type'] = df_raw.iloc[:, 9] # J
        df['Service_Code'] = df_raw.iloc[:, 10] # K
        df['Rooms'] = df_raw.iloc[:, 11].apply(clean_num) # L (객실수)
        df['Room_Revenue'] = df_raw.iloc[:, 13].apply(clean_num) # N
        df['Total_Revenue'] = df_raw.iloc[:, 15].apply(clean_num) # P
        df['Account'] = df_raw.iloc[:, 16] # Q
        df['Segment'] = df_raw.iloc[:, 17] # R
        df['Nat_Orig'] = df_raw.iloc[:, 23] # X
        df['Booking_Date'] = pd.to_datetime(df_raw.iloc[:, 30], errors='coerce') # AE (예약일)

        # AI(휴대폰), AJ(이메일)
        if len(df_raw.columns) > 34: df['Phone'] = df_raw.iloc[:, 34]
        if len(df_raw.columns) > 35: df['Email'] = df_raw.iloc[:, 35]

        # RN & LeadTime (파이썬 계산)
        df['Rooms'] = np.where(df['Rooms']<=0, 1, df['Rooms'])
        df['Nights'] = np.where(df['Nights']<=0, 1, df['Nights'])
        df['RN'] = df['Rooms'] * df['Nights']
        df['Lead_Time'] = (df['CheckIn'] - df['Booking_Date']).dt.days.fillna(0)
        
        # 매출 보정
        df['Total_Revenue'] = np.where(df['Total_Revenue']==0, df['Room_Revenue'], df['Total_Revenue'])
        
        # Snapshot (예약일 기준)
        df['Snapshot_Date'] = df['Booking_Date'].dt.strftime('%Y-%m-%d').fillna(datetime.now().strftime('%Y-%m-%d'))
        
        # 파생 변수
        df['Stay_Month'] = df['CheckIn'].dt.strftime('%Y-%m')
        df['Booking_Month'] = df['Booking_Date'].dt.strftime('%Y-%m')
        df['Day_Type'] = df['CheckIn'].dt.weekday.apply(lambda x: 'Weekend' if x>=4 else 'Weekday')
        
        def classify_nat(val):
            val = str(val).upper()
            if 'KOR' in val: return 'KOR'
            if any(x in val for x in ['CHN','HKG','TWN']): return 'CHN'
            if 'JPN' in val: return 'JPN'
            return 'OTH'
        df['Nat_Group'] = df['Nat_Orig'].apply(classify_nat)
        
        raw_str = df_raw.astype(str).agg(''.join, axis=1).str.upper()
        df['Breakfast'] = np.where(raw_str.str.contains('BF'), 'Included', 'Not Included')

        return df
    except Exception as e: st.error(f"예약 오류: {e}"); return pd.DataFrame()

def process_cancel_file(file):
    """취소 리스트: AA(26)=예약일, AB(27)=취소일"""
    try:
        if file.name.endswith('.csv'):
            try: df_raw = pd.read_csv(file, header=2, encoding='cp949')
            except: df_raw = pd.read_csv(file, header=2)
        else: df_raw = pd.read_excel(file, header=2)
            
        if len(df_raw.columns) <= 27:
            st.error("🚨 취소 파일 컬럼 부족"); return pd.DataFrame()

        df = pd.DataFrame()
        df['Status'] = df_raw.iloc[:, 1] # B
        df['Res_No'] = df_raw.iloc[:, 2] # C
        df['Guest_Name'] = df_raw.iloc[:, 5] # F
        df['CheckIn'] = pd.to_datetime(df_raw.iloc[:, 6], errors='coerce') # G
        df['CheckOut'] = pd.to_datetime(df_raw.iloc[:, 7], errors='coerce') # H
        df['Nights'] = df_raw.iloc[:, 8].apply(clean_num) # I
        df['Room_Type'] = df_raw.iloc[:, 9] # J
        df['Service_Code'] = df_raw.iloc[:, 10] # K
        df['Rooms'] = df_raw.iloc[:, 11].apply(clean_num) # L
        df['Room_Revenue'] = df_raw.iloc[:, 13].apply(clean_num) # N
        df['Total_Revenue'] = df_raw.iloc[:, 15].apply(clean_num) # P
        df['Account'] = df_raw.iloc[:, 16] # Q
        df['Segment'] = df_raw.iloc[:, 17] # R
        df['Nat_Orig'] = df_raw.iloc[:, 23] # X
        df['Booking_Date'] = pd.to_datetime(df_raw.iloc[:, 26], errors='coerce') # AA
        df['Cancel_Date'] = pd.to_datetime(df_raw.iloc[:, 27], errors='coerce') # AB

        df['Rooms'] = np.where(df['Rooms']<=0, 1, df['Rooms'])
        df['Nights'] = np.where(df['Nights']<=0, 1, df['Nights'])
        df['RN'] = df['Rooms'] * df['Nights']
        df['Lead_Time'] = (df['CheckIn'] - df['Booking_Date']).dt.days.fillna(0)
        df['Total_Revenue'] = np.where(df['Total_Revenue']==0, df['Room_Revenue'], df['Total_Revenue'])
        
        # Snapshot (취소일 기준)
        df['Snapshot_Date'] = df['Cancel_Date'].dt.strftime('%Y-%m-%d').fillna(datetime.now().strftime('%Y-%m-%d'))
        
        df['Stay_Month'] = df['CheckIn'].dt.strftime('%Y-%m')
        df['Booking_Month'] = df['Booking_Date'].dt.strftime('%Y-%m')
        df['Day_Type'] = df['CheckIn'].dt.weekday.apply(lambda x: 'Weekend' if x>=4 else 'Weekday')
        
        def classify_nat(val):
            val = str(val).upper()
            if 'KOR' in val: return 'KOR'
            return 'OTH'
        df['Nat_Group'] = df['Nat_Orig'].apply(classify_nat)
        
        raw_str = df_raw.astype(str).agg(''.join, axis=1).str.upper()
        df['Breakfast'] = np.where(raw_str.str.contains('BF'), 'Included', 'Not Included')

        return df
    except Exception as e: st.error(f"취소 오류: {e}"); return pd.DataFrame()

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
# 5. UI 헬퍼
# ==============================================================================

def add_total_with_adr(df, group_col_name="구분"):
    if df.empty: return df
    num = df.select_dtypes(include=[np.number]).fillna(0)
    row = {c: "" for c in df.columns}; row.update(num.sum().to_dict())
    row[group_col_name if group_col_name in df.columns else df.columns[0]] = "TOTAL"
    
    # ADR 재계산
    if row.get('RN', 0) > 0:
        if 'Room_Revenue' in row: row['ADR_Room'] = row['Room_Revenue'] / row['RN']
        if 'Total_Revenue' in row: row['ADR_Total'] = row['Total_Revenue'] / row['RN']
    
    return pd.concat([df, pd.DataFrame([row])], ignore_index=True)

def show_styled(df):
    if df.empty: st.info("데이터 없음"); return
    cols = df.select_dtypes(include=[np.number]).columns
    st.dataframe(df.style.format({c: "{:,.0f}" for c in cols}).apply(lambda r: ['background-color: #fff9c4; font-weight: bold; border-top: 2px solid black']*len(r) if str(r[0])=="TOTAL" else ['']*len(r), axis=1), hide_index=True, use_container_width=True)

def group_and_show(df, group_col):
    """그룹핑 + ADR 계산 + 차트/표 출력"""
    if df.empty: return pd.DataFrame()
    agg = df.groupby(group_col).agg({'RN': 'sum', 'Room_Revenue': 'sum', 'Total_Revenue': 'sum'}).reset_index()
    agg['ADR_Room'] = np.where(agg['RN']>0, agg['Room_Revenue']/agg['RN'], 0)
    agg['ADR_Total'] = np.where(agg['RN']>0, agg['Total_Revenue']/agg['RN'], 0)
    show_styled(add_total_with_adr(agg, group_col))
    return agg

def render_tab(df, k):
    if df.empty:
        st.info("데이터 없음")
        return
    
    t1, t2, t3, t4, t5, t6, t7, t8 = st.tabs(["📊 세그먼트", "📅 Pacing", "🏢 거래처", "⏳ 리드타임", "🛏️ 객실타입", "🗓️ 요일", "🌐 국적", "🍳 조식"])
    
    with t1:
        s = group_and_show(df, 'Segment')
        if not s.empty:
            c1, c2 = st.columns(2)
            c1.plotly_chart(px.pie(s, values='Room_Revenue', names='Segment', title="매출 비중"), use_container_width=True, key=f"{k}_p")
            c2.plotly_chart(px.bar(s, x='Segment', y='Room_Revenue', title="세그먼트별 매출"), use_container_width=True, key=f"{k}_b")
    
    with t2:
        # [핀셋 수정] 페이싱 데이터 집계 정밀화
        # 투숙월(Stay_Month)과 예약월(Booking_Month)이 누락되지 않도록 강제 재설정 후 피벗
        pacing_df = df.copy()
        # 데이터가 문자열일 경우를 대비해 정렬을 위한 전처리
        pacing_df = pacing_df.sort_values(['Booking_Month', 'Stay_Month'])
        
        p = pacing_df.pivot_table(
            index='Booking_Month', 
            columns='Stay_Month', 
            values='RN', 
            aggfunc='sum'
        ).fillna(0)
        
        st.subheader("📅 Booking Pacing Matrix (예약월 vs 투숙월)")
        st.plotly_chart(px.imshow(
            p, 
            text_auto=True, 
            aspect="auto", 
            color_continuous_scale="Blues",
            labels=dict(x="투숙월 (Stay Month)", y="예약 생성월 (Booking Month)", color="RN")
        ), use_container_width=True, key=f"{k}_pace")
        
        # 월별 예약 생성 추이 (Bar Chart) 고도화
        trend = pacing_df.groupby('Booking_Month')['RN'].sum().reset_index()
        st.plotly_chart(px.bar(
            trend, 
            x='Booking_Month', 
            y='RN', 
            title="월별 신규 예약 생성 추이 (RN 기준)",
            text_auto='.0f'
        ), use_container_width=True, key=f"{k}_tr")
    
    with t3:
        agg = df.groupby('Account').agg({'RN': 'sum', 'Room_Revenue': 'sum', 'Total_Revenue': 'sum'}).reset_index()
        agg['ADR_Room'] = np.where(agg['RN']>0, agg['Room_Revenue']/agg['RN'], 0)
        agg['ADR_Total'] = np.where(agg['RN']>0, agg['Total_Revenue']/agg['RN'], 0)
        show_styled(add_total_with_adr(agg.sort_values('RN', ascending=False).head(50), 'Account'))
    
    with t4:
        df['LT_G'] = pd.cut(df['Lead_Time'], bins=[-999,0,3,7,14,30,60,90,999], labels=['0','1-3','4-7','8-14','15-30','31-60','61-90','90+'])
        l = group_and_show(df, 'LT_G')
        if not l.empty:
            st.plotly_chart(px.bar(l, x='LT_G', y='RN', title="리드타임별 RN 실적"), use_container_width=True, key=f"{k}_lt")
    
    with t5:
        group_and_show(df, 'Room_Type')
        
    with t6:
        w = group_and_show(df, 'Day_Type')
        if not w.empty:
            c1, c2 = st.columns(2)
            c1.plotly_chart(px.bar(w, x='Day_Type', y='Room_Revenue', title="요일별 매출"), use_container_width=True, key=f"{k}_w_b")
            c2.plotly_chart(px.pie(w, values='RN', names='Day_Type', title="요일별 RN 비중"), use_container_width=True, key=f"{k}_w_p")
            
    with t7:
        n = group_and_show(df, 'Nat_Group')
        if not n.empty:
            c1, c2 = st.columns(2)
            c1.plotly_chart(px.pie(n, values='RN', names='Nat_Group', title="국적별 RN 비중"), use_container_width=True, key=f"{k}_n_p")
            c2.plotly_chart(px.bar(n, x='Nat_Group', y='Room_Revenue', title="국적별 매출 실적"), use_container_width=True, key=f"{k}_n_b")
            
    with t8:
        b = group_and_show(df, 'Breakfast')
        if not b.empty:
            st.plotly_chart(px.pie(b, values='RN', names='Breakfast', title="조식 포함 여부 비중(RN)"), use_container_width=True, key=f"{k}_bf")

# ==============================================================================
# MAIN
# ==============================================================================
try:
    st.title("🏛️ 앰버 호텔 경영 리포트 (Final Integrity)")
    raw = load_db()
    if raw: df_all = pd.DataFrame(raw)
    else: df_all = pd.DataFrame(columns=['Snapshot_Date','Data_Type'])
    
    # 숫자형 변환
    for c in ['RN','Room_Revenue','Total_Revenue','Rooms','Nights','Lead_Time']:
        if c in df_all.columns: df_all[c] = pd.to_numeric(df_all[c], errors='coerce').fillna(0)

    # 날짜 분리
    res_dates_all = sorted(df_all[df_all['Data_Type']=='Reservation']['Snapshot_Date'].unique(), reverse=True)
    today = datetime.now().strftime('%Y-%m-%d')
    res_dates = [d for d in res_dates_all if d != today] # 오늘 제외
    
    otb_dates = sorted(df_all[df_all['Data_Type']=='OTB']['Snapshot_Date'].unique(), reverse=True)

    with st.sidebar:
        st.header("설정")
        if st.button("🗑️ OTB 초기화"): d=delete_otb(); st.warning(f"{d}건 삭제"); time.sleep(1); st.rerun()
        if st.button("🚨 전체 초기화"): d=delete_all(); st.warning(f"{d}건 삭제"); time.sleep(1); st.rerun()
        
        st.divider()
        sel_res = st.selectbox("📌 예약/취소 조회", res_dates) if res_dates else None
        sel_otb = st.selectbox("📈 OTB 조회", otb_dates) if otb_dates else None
        
        st.divider()
        st.write("※ 파일명 날짜 / 컬럼 위치 기준")
        f1 = st.file_uploader("예약 리스트 (AE=예약일)", type=['xlsx','csv'])
        if f1 and st.button("예약 저장"):
            # 예약 리스트는 'Reservation' 타입으로 저장
            if save_to_db(process_res_file(f1), 'Reservation'): st.rerun()
        f2 = st.file_uploader("취소 리스트 (AB=취소일)", type=['xlsx','csv'])
        if f2 and st.button("취소 저장"):
            # 취소 리스트는 'Cancellation' 타입으로 저장하여 구분
            if save_to_db(process_cancel_file(f2), 'Cancellation'): st.rerun()
        f3 = st.file_uploader("OTB 파일 (파일명 날짜)", type=['xlsx','csv'], accept_multiple_files=True)
        if f3 and st.button("OTB 저장"):
            for f in f3: save_to_db(process_otb(f), 'OTB')
            st.rerun()

    # 데이터 로드
    if sel_res and not df_all.empty:
        # 예약리스트 출처 (Reservation 타입)
        df_bk_raw = df_all[(df_all['Snapshot_Date']==sel_res) & (df_all['Data_Type']=='Reservation')].copy()
        
        # 예약: Total_Revenue > 0 (상태 무관, 예약리스트에 있으면 예약)
        df_bk = df_bk_raw[df_bk_raw['Total_Revenue'] > 0]
        # 0원 예약
        df_zero = df_bk_raw[df_bk_raw['Total_Revenue'] <= 0]
        
        # 취소 데이터 (Cancellation 타입)
        df_cn = df_all[(df_all['Snapshot_Date']==sel_res) & (df_all['Data_Type']=='Cancellation')].copy()
        
        # Fallback: Cancellation 타입이 없으면(구버전), Reservation 내의 RC를 취소로
        if df_cn.empty and not df_bk_raw.empty:
             df_cn = df_bk_raw[df_bk_raw['Status'] == 'RC']
        
        df_tot = pd.concat([df_bk, df_cn])
    else:
        df_bk, df_zero, df_cn, df_tot = pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    if sel_otb and not df_all.empty:
        df_o = df_all[(df_all['Snapshot_Date']==sel_otb) & (df_all['Data_Type']=='OTB')].copy()
    else: df_o = pd.DataFrame()

    # 탭
    tabs = st.tabs(["👑 GM 요약", "✅ 예약 상세", "❌ 취소 상세", "📈 종합 합계", "🆓 0원 예약", "🎯 OTB 현황"])
    
    with tabs[0]:
        st.header(f"👑 GM 요약 ({sel_res})")
        if df_bk.empty and df_cn.empty: st.info("데이터 없음")
        else:
            b_rn, b_rev, b_tot = df_bk['RN'].sum(), df_bk['Room_Revenue'].sum(), df_bk['Total_Revenue'].sum()
            c_rn, c_rev, c_tot = df_cn['RN'].sum(), df_cn['Room_Revenue'].sum(), df_cn['Total_Revenue'].sum()
            
            b_los = b_rn/len(df_bk) if len(df_bk)>0 else 0
            c_los = c_rn/len(df_cn) if len(df_cn)>0 else 0
            
            rc_in_bk = len(df_bk[df_bk['Status']=='RC'])
            
            st.markdown("#### ✅ 예약 (Reservation List)")
            c = st.columns(6)
            c[0].metric("RN", f"{b_rn:,.0f}")
            c[1].metric("객실료", f"{b_rev:,.0f}")
            c[2].metric("총매출", f"{b_tot:,.0f}")
            c[3].metric("ADR(Room)", f"{b_rev/b_rn if b_rn>0 else 0:,.0f}")
            c[4].metric("ADR(Total)", f"{b_tot/b_rn if b_rn>0 else 0:,.0f}")
            c[5].metric("건수", f"{len(df_bk):,.0f}", delta=f"이중 RC: {rc_in_bk}")
            
            st.markdown("#### ❌ 취소 (Cancellation List)")
            c = st.columns(6)
            c[0].metric("RN", f"{c_rn:,.0f}")
            c[1].metric("객실료", f"{c_rev:,.0f}")
            c[2].metric("총매출", f"{c_tot:,.0f}")
            c[3].metric("ADR(Room)", f"{c_rev/c_rn if c_rn>0 else 0:,.0f}")
            c[4].metric("ADR(Total)", f"{c_tot/c_rn if c_rn>0 else 0:,.0f}")
            c[5].metric("건수", f"{len(df_cn):,.0f}")
            
            st.divider()
            if not df_bk.empty: group_and_show(df_bk, 'Segment')
            
            c1, c2 = st.columns(2)
            with c1:
                if not df_bk.empty: st.plotly_chart(px.pie(df_bk.groupby('Nat_Group')['RN'].sum().reset_index(), values='RN', names='Nat_Group', hole=0.4, title="국적 비중"), use_container_width=True)
            with c2:
                comb = pd.concat([df_bk.assign(Type='Book'), df_cn.assign(Type='Cancel')])
                if not comb.empty: st.plotly_chart(px.bar(comb.groupby(['Stay_Month','Type'])['RN'].sum().reset_index(), x='Stay_Month', y='RN', color='Type', barmode='group', title="월별 추이"), use_container_width=True)

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
