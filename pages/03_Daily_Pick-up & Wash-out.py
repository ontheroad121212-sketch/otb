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
import textwrap

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
        if pd.isna(val) or str(val).strip() == '': return 0
        s = str(val).replace(',', '').replace('₩', '').replace(' ', '').strip()
        return float(s)
    except: return 0

def safe_date_parse(series):
    """날짜 변환 강화"""
    s1 = pd.to_datetime(series, errors='coerce')
    mask = s1.isna()
    if mask.any():
        s2 = series[mask].astype(str).str.replace(' ', '').str.replace('.', '-').str.replace('/', '-')
        s1[mask] = pd.to_datetime(s2, errors='coerce')
    return s1

def save_to_db(df, data_type='Reservation'):
    """데이터 저장 함수 (덮어쓰기 적용)"""
    if df is None or df.empty:
        st.error("❌ 저장할 데이터가 0건입니다. (파일 처리 실패)")
        return False
    try:
        if 'Snapshot_Date' not in df.columns or df['Snapshot_Date'].isna().all():
             df['Snapshot_Date'] = datetime.now().strftime('%Y-%m-%d')
        else:
             df['Snapshot_Date'] = df['Snapshot_Date'].fillna(datetime.now().strftime('%Y-%m-%d'))

        try:
            df['Snapshot_Date'] = pd.to_datetime(df['Snapshot_Date']).dt.strftime('%Y-%m-%d')
        except:
            df['Snapshot_Date'] = df['Snapshot_Date'].astype(str).str.slice(0, 10)

        dates = df['Snapshot_Date'].unique()
        save_count = 0
        
        for d in dates:
            if pd.isna(d) or str(d).lower() in ['nat', 'nan', 'none', '']: continue 

            sub = df[df['Snapshot_Date'] == d].copy()
            if sub.empty: continue
            
            # 날짜 객체 문자열 변환
            for c in sub.select_dtypes(include=['datetime64[ns]']).columns:
                sub[c] = sub[c].astype(str)
            
            sub = sub.where(pd.notnull(sub), None)
            recs = sub.to_dict(orient='records')
            
            # Sanitization
            sanitized_recs = []
            for r in recs:
                new_r = {}
                for k, v in r.items():
                    clean_k = str(k).replace('.', '_').strip()
                    if isinstance(v, (np.integer, np.int64, np.int32)): new_r[clean_k] = int(v)
                    elif isinstance(v, (np.floating, np.float64, np.float32)): new_r[clean_k] = float(v)
                    elif isinstance(v, (np.bool_, bool)): new_r[clean_k] = bool(v)
                    else: new_r[clean_k] = v
                sanitized_recs.append(new_r)
            
            # 문서 ID (Overwrite)
            did = f"{d}_{data_type}"
            
            db.collection(COLLECTION_NAME).document(did).set({
                'data': sanitized_recs, 'uploaded_at': datetime.now(), 'snapshot_date': d, 'data_type': data_type
            })
            save_count += len(sanitized_recs)
            
        if save_count > 0:
            st.toast(f"✅ 데이터 {save_count}건 저장 완료!")
            return True
        else:
            st.error("⚠️ 날짜 문제로 저장된 데이터가 없습니다.")
            return False
            
    except Exception as e: 
        st.error(f"저장 중 오류 발생: {e}")
        return False

@st.cache_data(ttl=0)
def load_db():
    try:
        docs = db.collection(COLLECTION_NAME).stream(); res = []
        for d in docs:
            dd = d.to_dict()
            snap = dd.get('snapshot_date', '')
            dtype = dd.get('data_type', 'Reservation')
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
# 4. 파일 처리 로직 (핀셋 수정: 정확한 헤더 찾기 및 한글 컬럼 매핑)
# ==============================================================================

def load_and_fix_header(file):
    """
    파일의 진짜 헤더(예약번호, 객실료 등이 있는 줄)를 찾아 DataFrame으로 반환
    """
    try:
        if file.name.endswith('.csv'):
            try: df_raw = pd.read_csv(file, header=None, encoding='cp949')
            except: df_raw = pd.read_csv(file, header=None)
        else:
            df_raw = pd.read_excel(file, header=None)
    except:
        return None

    # 진짜 헤더 행 찾기 (상위 30줄 검색)
    header_idx = -1
    for r in range(min(30, len(df_raw))):
        row_str = df_raw.iloc[r].astype(str).str.cat()
        # "예약번호"와 "객실료"가 동시에 있는 줄을 헤더로 인정
        if "예약번호" in row_str and ("객실료" in row_str or "총금액" in row_str):
            header_idx = r
            break
            
    if header_idx == -1: return None

    # 헤더 적용하여 다시 로드 (또는 슬라이싱)
    df_raw.columns = df_raw.iloc[header_idx]
    df = df_raw.iloc[header_idx+1:].copy()
    
    # 컬럼명 공백 제거
    df.columns = df.columns.astype(str).str.strip()
    return df

def process_res_file(file):
    """예약 리스트 처리"""
    try:
        df = load_and_fix_header(file)
        if df is None:
            st.error("🚨 '예약번호'와 '객실료'가 포함된 헤더 행을 찾을 수 없습니다.")
            return pd.DataFrame()

        # [핵심] 한글 컬럼 -> 영어 컬럼 매핑
        col_map = {
            '상태': 'Status',
            '예약번호': 'Res_No',
            '고객명': 'Guest_Name',
            '입실일자': 'CheckIn', '도착일': 'CheckIn',
            '퇴실일자': 'CheckOut', '출발일': 'CheckOut',
            '박수': 'Nights',
            '객실타입': 'Room_Type',
            '객실수': 'Rooms',
            '객실료': 'Room_Revenue',
            '총금액': 'Total_Revenue', '총매출': 'Total_Revenue',
            '거래처': 'Account',
            '세그먼트': 'Segment',
            '국적': 'Nat_Orig',
            '예약일자': 'Booking_Date', '예약일': 'Booking_Date'
        }
        
        # 컬럼 이름 변경
        df = df.rename(columns=col_map)
        
        # 필수 컬럼이 없으면 생성 (에러 방지)
        required = ['Res_No', 'Room_Revenue', 'Booking_Date', 'CheckIn', 'CheckOut']
        for c in required:
            if c not in df.columns: df[c] = np.nan

        # [필터링 1] 합계행 제거 ('총합계' 등)
        # Res_No가 없거나 '합계' 글자가 있으면 삭제
        df = df[df['Res_No'].notna()]
        df = df[~df['Res_No'].astype(str).str.contains('합계|총계|Total', case=False, na=False)]

        # [필터링 2] 날짜 변환
        df['CheckIn'] = safe_date_parse(df['CheckIn'])
        df['CheckOut'] = safe_date_parse(df['CheckOut'])
        df['Booking_Date'] = safe_date_parse(df['Booking_Date'])
        
        # 날짜 없는 행 제거 (합계행일 확률 높음)
        df = df.dropna(subset=['Booking_Date']) 
        df = df.dropna(subset=['CheckIn'])

        # 숫자 변환
        for c in ['Nights', 'Rooms', 'Room_Revenue', 'Total_Revenue']:
            if c in df.columns: df[c] = df[c].apply(clean_num)
            else: df[c] = 0

        # MICE 단체 허용 (매출 100억 이상만 제거)
        df = df[df['Room_Revenue'] < 10000000000]

        df['RN'] = df['Rooms'] * df['Nights']
        
        try: df['Lead_Time'] = (df['CheckIn'] - df['Booking_Date']).dt.days.fillna(0)
        except: df['Lead_Time'] = 0

        if 'Total_Revenue' in df.columns:
            df['Total_Revenue'] = np.where(df['Total_Revenue']==0, df['Room_Revenue'], df['Total_Revenue'])
        
        df['Snapshot_Date'] = df['Booking_Date'].dt.strftime('%Y-%m-%d')
        
        df['Stay_Month'] = df['CheckIn'].dt.strftime('%Y-%m')
        df['Booking_Month'] = df['Booking_Date'].dt.strftime('%Y-%m')
        df['Day_Type'] = df['CheckIn'].dt.weekday.apply(lambda x: 'Weekend' if x>=4 else 'Weekday')
        
        def classify_nat(val):
            val = str(val).upper()
            if 'KOR' in val: return 'KOR'
            if any(x in val for x in ['CHN','HKG','TWN']): return 'CHN'
            if 'JPN' in val: return 'JPN'
            return 'OTH'
        
        if 'Nat_Orig' in df.columns:
            df['Nat_Group'] = df['Nat_Orig'].apply(classify_nat)
        else:
            df['Nat_Group'] = 'OTH'
        
        if 'Segment' in df.columns:
            df['Segment'] = df['Segment'].astype(str).str.strip()
        else:
            df['Segment'] = 'Unknown'
            
        # 조식 여부 (비고란 같은 곳이 없으므로 일단 전체 raw string에서 찾음)
        # (임시: 원본 df에서 찾아야 함. 편의상 'Included'로 둠)
        df['Breakfast'] = 'Included'

        with st.sidebar:
            st.caption(f"📊 예약 처리: {len(df)}건 (정상 로드)")

        return df
    except Exception as e: st.error(f"예약 오류 상세: {e}"); return pd.DataFrame()

def process_cancel_file(file):
    """취소 리스트 처리"""
    try:
        df = load_and_fix_header(file)
        if df is None:
            st.error("🚨 '예약번호'와 '객실료'가 포함된 헤더 행을 찾을 수 없습니다.")
            return pd.DataFrame()

        col_map = {
            '상태': 'Status',
            '예약번호': 'Res_No',
            '고객명': 'Guest_Name',
            '입실일자': 'CheckIn', '도착일': 'CheckIn',
            '퇴실일자': 'CheckOut', '출발일': 'CheckOut',
            '박수': 'Nights',
            '객실타입': 'Room_Type',
            '객실수': 'Rooms',
            '객실료': 'Room_Revenue',
            '총금액': 'Total_Revenue', '총매출': 'Total_Revenue',
            '거래처': 'Account',
            '세그먼트': 'Segment',
            '국적': 'Nat_Orig',
            '예약일자': 'Booking_Date', '예약일': 'Booking_Date',
            '취소일자': 'Cancel_Date', '취소일': 'Cancel_Date'
        }
        df = df.rename(columns=col_map)
        
        # 합계 제거
        df = df[df['Res_No'].notna()]
        df = df[~df['Res_No'].astype(str).str.contains('합계|총계|Total', case=False, na=False)]

        # 날짜 변환
        df['Cancel_Date'] = safe_date_parse(df.get('Cancel_Date'))
        df['CheckIn'] = safe_date_parse(df.get('CheckIn'))
        df['Booking_Date'] = safe_date_parse(df.get('Booking_Date'))
        
        df = df.dropna(subset=['Cancel_Date'])
        df = df.dropna(subset=['CheckIn'])

        for c in ['Nights', 'Rooms', 'Room_Revenue', 'Total_Revenue']:
            if c in df.columns: df[c] = df[c].apply(clean_num)
            else: df[c] = 0

        df = df[df['Room_Revenue'] < 10000000000]

        df['RN'] = df['Rooms'] * df['Nights']
        
        try: df['Lead_Time'] = (df['CheckIn'] - df['Booking_Date']).dt.days.fillna(0)
        except: df['Lead_Time'] = 0

        df['Snapshot_Date'] = df['Cancel_Date'].dt.strftime('%Y-%m-%d')
        df['Stay_Month'] = df['CheckIn'].dt.strftime('%Y-%m')
        df['Booking_Month'] = df['Booking_Date'].dt.strftime('%Y-%m')
        df['Day_Type'] = df['CheckIn'].dt.weekday.apply(lambda x: 'Weekend' if x>=4 else 'Weekday')
        
        def classify_nat(val):
            val = str(val).upper()
            if 'KOR' in val: return 'KOR'
            return 'OTH'
        
        if 'Nat_Orig' in df.columns:
            df['Nat_Group'] = df['Nat_Orig'].apply(classify_nat)
        else:
            df['Nat_Group'] = 'OTH'
            
        if 'Segment' in df.columns:
            df['Segment'] = df['Segment'].astype(str).str.strip()
        else:
            df['Segment'] = 'Unknown'
            
        df['Breakfast'] = 'Included'

        with st.sidebar: st.caption(f"📊 취소 처리: {len(df)}건")
        return df
    except Exception as e: st.error(f"취소 오류 상세: {e}"); return pd.DataFrame()

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
        return pd.DataFrame([{'CheckIn': target_month_str, 'Room_Revenue': total_rev, 'Total_Revenue': total_rev, 'RN': 0, 'Guest_Name': 'OTB', 'Segment': 'OTB', 'Snapshot_Date': snap, 'Status': 'Booked'}])
    except: return pd.DataFrame()

# ==============================================================================
# 5. UI 헬퍼
# ==============================================================================

def add_total_with_adr(df, group_col_name="구분"):
    if df.empty: return df
    num = df.select_dtypes(include=[np.number]).fillna(0)
    row = {c: "" for c in df.columns}; row.update(num.sum().to_dict())
    row[group_col_name if group_col_name in df.columns else df.columns[0]] = "TOTAL"
    if row.get('RN', 0) > 0:
        if 'Room_Revenue' in row: row['ADR_Room'] = row['Room_Revenue'] / row['RN']
        if 'Total_Revenue' in row: row['ADR_Total'] = row['Total_Revenue'] / row['RN']
    return pd.concat([df, pd.DataFrame([row])], ignore_index=True)

def show_styled(df):
    if df.empty: st.info("데이터 없음"); return
    cols = df.select_dtypes(include=[np.number]).columns
    st.dataframe(df.style.format({c: "{:,.0f}" for c in cols}).apply(lambda r: ['background-color: #fff9c4; font-weight: bold; border-top: 2px solid black']*len(r) if str(r[0])=="TOTAL" else ['']*len(r), axis=1), hide_index=True, use_container_width=True)

def group_and_show(df, group_col):
    if df.empty: return pd.DataFrame()
    if group_col not in df.columns: return pd.DataFrame()
    agg = df.groupby(group_col).agg({'RN': 'sum', 'Room_Revenue': 'sum', 'Total_Revenue': 'sum'}).reset_index()
    agg['ADR_Room'] = np.where(agg['RN']>0, agg['Room_Revenue']/agg['RN'], 0)
    agg['ADR_Total'] = np.where(agg['RN']>0, agg['Total_Revenue']/agg['RN'], 0)
    show_styled(add_total_with_adr(agg, group_col))
    return agg

def render_tab(df, k):
    if df.empty: st.info("데이터 없음"); return
    t1, t2, t3, t4, t5, t6, t7, t8 = st.tabs(["📊 세그먼트", "📅 Pacing", "🏢 거래처", "⏳ 리드타임", "🛏️ 객실타입", "🗓️ 요일", "🌐 국적", "🍳 조식"])
    with t1:
        s = group_and_show(df, 'Segment')
        if not s.empty:
            c1, c2 = st.columns(2)
            c1.plotly_chart(px.pie(s, values='Room_Revenue', names='Segment', title="매출 비중"), use_container_width=True, key=f"{k}_p")
            c2.plotly_chart(px.bar(s, x='Segment', y='Room_Revenue', title="세그먼트별 매출"), use_container_width=True, key=f"{k}_b")
    with t2:
        st.subheader("📅 Booking Pacing Matrix (Booking vs Stay)")
        p_df = df.copy()
        p_df = p_df.sort_values(['Booking_Month', 'Stay_Month'])
        p = p_df.pivot_table(index='Booking_Month', columns='Stay_Month', values='RN', aggfunc='sum').fillna(0)
        if not p.empty:
            fig_hm = go.Figure(data=go.Heatmap(z=p.values, x=p.columns, y=p.index, colorscale='Blues', text=p.values, texttemplate="%{text:.0f}", hoverinfo='z'))
            fig_hm.update_layout(xaxis={'type':'category', 'title':'투숙월 (Stay)'}, yaxis={'type':'category', 'title':'예약생성월 (Booking)'}, height=500)
            st.plotly_chart(fig_hm, use_container_width=True, key=f"{k}_hm")
            st.markdown("---")
            st.subheader("📊 투숙월별 예약 분포")
            stay_dist = p_df.groupby('Stay_Month')['RN'].sum().reset_index()
            st.plotly_chart(px.bar(stay_dist, x='Stay_Month', y='RN', text_auto='.0f'), use_container_width=True, key=f"{k}_stay_b")
        else: st.warning("페이싱 데이터 없음")
    with t3:
        agg = df.groupby('Account').agg({'RN': 'sum', 'Room_Revenue': 'sum', 'Total_Revenue': 'sum'}).reset_index()
        agg['ADR_Room'] = np.where(agg['RN']>0, agg['Room_Revenue']/agg['RN'], 0)
        agg['ADR_Total'] = np.where(agg['RN']>0, agg['Total_Revenue']/agg['RN'], 0)
        show_styled(add_total_with_adr(agg.sort_values('RN', ascending=False).head(50), 'Account'))
    with t4:
        df['LT_G'] = pd.cut(df['Lead_Time'], bins=[-999,0,3,7,14,30,60,90,999], labels=['0','1-3','4-7','8-14','15-30','31-60','61-90','90+'])
        l = group_and_show(df, 'LT_G')
        if not l.empty: st.plotly_chart(px.bar(l, x='LT_G', y='RN', title="리드타임별 RN 실적"), use_container_width=True, key=f"{k}_lt")
    with t5: group_and_show(df, 'Room_Type')
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
        if not b.empty: st.plotly_chart(px.pie(b, values='RN', names='Breakfast', title="조식 포함 여부"), use_container_width=True, key=f"{k}_bf")

# ==============================================================================
# MAIN
# ==============================================================================
try:
    st.title("🏛️ 앰버 호텔 경영 리포트 (Final Integrity)")
    raw = load_db()
    if raw: df_all = pd.DataFrame(raw)
    else: df_all = pd.DataFrame(columns=['Snapshot_Date','Data_Type'])
    
    for c in ['RN','Room_Revenue','Total_Revenue','Rooms','Nights','Lead_Time']:
        if c in df_all.columns: df_all[c] = pd.to_numeric(df_all[c], errors='coerce').fillna(0)

    res_dates_all = sorted(df_all[df_all['Data_Type']=='Reservation']['Snapshot_Date'].unique(), reverse=True)
    today = datetime.now().strftime('%Y-%m-%d')
    otb_dates = sorted(df_all[df_all['Data_Type']=='OTB']['Snapshot_Date'].unique(), reverse=True)

    with st.sidebar:
        st.header("설정")
        if st.button("🗑️ OTB 초기화"): d=delete_otb(); st.warning(f"{d}건 삭제"); time.sleep(1); st.rerun()
        if st.button("🚨 전체 초기화"): d=delete_all(); st.warning(f"{d}건 삭제"); time.sleep(1); st.rerun()
        
        st.divider()
        st.subheader("📌 예약/취소 조회 (기준 vs 비교)")
        
        yesterday_date = datetime.now().date() - timedelta(days=1)
        min_date = datetime.now().date() - timedelta(days=365)
        
        default_val = (yesterday_date, yesterday_date)
        if res_dates_all:
            try:
                latest_db = datetime.strptime(res_dates_all[0], "%Y-%m-%d").date()
                if latest_db > yesterday_date: latest_db = yesterday_date
                default_val = (latest_db, latest_db)
            except: pass

        dates_selected = st.date_input("기준 기간 (어제까지)", value=default_val, min_value=min_date, max_value=yesterday_date, format="YYYY-MM-DD")
        sel_res_start, sel_res_end = None, None
        if isinstance(dates_selected, tuple):
            if len(dates_selected) > 0: sel_res_start = dates_selected[0].strftime('%Y-%m-%d')
            if len(dates_selected) > 1: sel_res_end = dates_selected[1].strftime('%Y-%m-%d')
            if sel_res_start and not sel_res_end: sel_res_end = sel_res_start
            
        comp_dates_selected = st.date_input("비교 기간 (선택사항)", value=(), min_value=min_date, max_value=yesterday_date, format="YYYY-MM-DD")
        comp_start, comp_end = None, None
        if isinstance(comp_dates_selected, tuple):
            if len(comp_dates_selected) > 0: comp_start = comp_dates_selected[0].strftime('%Y-%m-%d')
            if len(comp_dates_selected) > 1: comp_end = comp_dates_selected[1].strftime('%Y-%m-%d')
            if comp_start and not comp_end: comp_end = comp_start
        
        st.divider()
        sel_otb = st.selectbox("📈 OTB 조회", otb_dates) if otb_dates else None
        
        st.divider()
        st.write("※ 파일명 날짜 / 컬럼 자동 인식")
        f1 = st.file_uploader("예약 리스트", type=['xlsx','csv'])
        if f1 and st.button("예약 저장"):
            if save_to_db(process_res_file(f1), 'Reservation'): st.rerun()
        f2 = st.file_uploader("취소 리스트", type=['xlsx','csv'])
        if f2 and st.button("취소 저장"):
            if save_to_db(process_cancel_file(f2), 'Cancellation'): st.rerun()
        f3 = st.file_uploader("OTB 파일", type=['xlsx','csv'], accept_multiple_files=True)
        if f3 and st.button("OTB 저장"):
            for f in f3: save_to_db(process_otb(f), 'OTB')
            st.rerun()

    if sel_res_start and sel_res_end and not df_all.empty:
        mask_bk = (df_all['Data_Type']=='Reservation') & (df_all['Snapshot_Date'] >= sel_res_start) & (df_all['Snapshot_Date'] <= sel_res_end)
        df_bk_raw = df_all[mask_bk].copy()
        df_bk = df_bk_raw[df_bk_raw['Total_Revenue'] > 0]
        df_zero = df_bk_raw[df_bk_raw['Total_Revenue'] <= 0]
        mask_cn = (df_all['Data_Type']=='Cancellation') & (df_all['Snapshot_Date'] >= sel_res_start) & (df_all['Snapshot_Date'] <= sel_res_end)
        df_cn = df_all[mask_cn].copy()
        if df_cn.empty and not df_bk_raw.empty: df_cn = df_bk_raw[df_bk_raw['Status'] == 'RC']
        df_tot = pd.concat([df_bk, df_cn])
        
        df_bk_comp = pd.DataFrame(); df_cn_comp = pd.DataFrame()
        if comp_start and comp_end:
            mask_bk_c = (df_all['Data_Type']=='Reservation') & (df_all['Snapshot_Date'] >= comp_start) & (df_all['Snapshot_Date'] <= comp_end)
            df_bk_comp = df_all[mask_bk_c & (df_all['Total_Revenue']>0)].copy()
            mask_cn_c = (df_all['Data_Type']=='Cancellation') & (df_all['Snapshot_Date'] >= comp_start) & (df_all['Snapshot_Date'] <= comp_end)
            df_cn_comp = df_all[mask_cn_c].copy()
            if df_cn_comp.empty and not df_all[mask_bk_c].empty: df_cn_comp = df_all[mask_bk_c & (df_all['Status']=='RC')]
    else:
        df_bk, df_zero, df_cn, df_tot = pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        df_bk_comp, df_cn_comp = pd.DataFrame(), pd.DataFrame()

    if sel_otb and not df_all.empty:
        df_o = df_all[(df_all['Snapshot_Date']==sel_otb) & (df_all['Data_Type']=='OTB')].copy()
    else: df_o = pd.DataFrame()

    tabs = st.tabs(["👑 GM 요약", "✅ 예약 상세", "❌ 취소 상세", "📈 종합 합계", "🆓 0원 예약", "🎯 OTB 현황"])
    with tabs[0]:
        disp = f"{sel_res_start}~{sel_res_end}" if sel_res_start else "기간 미선택"
        st.header(f"👑 GM 요약 ({disp})")
        if df_bk.empty and df_cn.empty: st.info("데이터 없음")
        else:
            b_rn = df_bk['RN'].sum()
            b_rev = df_bk['Room_Revenue'].sum()
            b_tot = df_bk['Total_Revenue'].sum()
            c_rn = df_cn['RN'].sum()
            c_rev = df_cn['Room_Revenue'].sum()
            c_tot = df_cn['Total_Revenue'].sum()
            
            b_rn_c = df_bk_comp['RN'].sum() if not df_bk_comp.empty else 0
            b_rev_c = df_bk_comp['Room_Revenue'].sum() if not df_bk_comp.empty else 0
            b_tot_c = df_bk_comp['Total_Revenue'].sum() if not df_bk_comp.empty else 0
            c_rn_c = df_cn_comp['RN'].sum() if not df_cn_comp.empty else 0
            c_rev_c = df_cn_comp['Room_Revenue'].sum() if not df_cn_comp.empty else 0
            c_tot_c = df_cn_comp['Total_Revenue'].sum() if not df_cn_comp.empty else 0
            rc_in_bk = len(df_bk[df_bk['Status']=='RC'])

            st.markdown("#### ✅ 예약 (Reservation List)")
            c = st.columns(6)
            c[0].metric("RN", f"{b_rn:,.0f}", delta=f"{b_rn - b_rn_c:,.0f}" if comp_start else None)
            c[1].metric("객실료", f"{b_rev:,.0f}", delta=f"{b_rev - b_rev_c:,.0f}" if comp_start else None)
            c[2].metric("총매출", f"{b_tot:,.0f}", delta=f"{b_tot - b_tot_c:,.0f}" if comp_start else None)
            c[3].metric("ADR(Room)", f"{b_rev/b_rn if b_rn>0 else 0:,.0f}")
            c[4].metric("ADR(Total)", f"{b_tot/b_rn if b_rn>0 else 0:,.0f}")
            c[5].metric("건수", f"{len(df_bk):,.0f}", delta=f"이중 RC: {rc_in_bk}")
            
            st.markdown("#### ❌ 취소 (Cancellation List)")
            c = st.columns(6)
            c[0].metric("RN", f"{c_rn:,.0f}", delta=f"{c_rn - c_rn_c:,.0f}" if comp_start else None, delta_color="inverse")
            c[1].metric("객실료", f"{c_rev:,.0f}", delta=f"{c_rev - c_rev_c:,.0f}" if comp_start else None, delta_color="inverse")
            c[2].metric("총매출", f"{c_tot:,.0f}", delta=f"{c_tot - c_tot_c:,.0f}" if comp_start else None, delta_color="inverse")
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
    with tabs[4]: st.dataframe(df_zero[['Guest_Name','CheckIn','Account','Room_Type']], use_container_width=True)
    with tabs[5]:
        if not df_o.empty:
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
