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
# [1] 설정 및 언어 세션 고정
# ==============================================================================
st.set_page_config(page_title="Daily Pick-up & Wash-out", layout="wide")

if 'lang' not in st.session_state:
    st.session_state.lang = 'ko'

# URL 파라미터 감지 및 세션 업데이트
try:
    url_params = st.query_params
    if url_params.get("lang") == "zh":
        st.session_state.lang = "zh"
    elif url_params.get("lang") == "ko":
        st.session_state.lang = "ko"
except:
    pass

is_chairman_mode = (st.session_state.lang == "zh")

if is_chairman_mode:
    st.sidebar.success("Chairman Mode Active (ZH)")

# ==============================================================================
# [번역 사전]
# ==============================================================================
LANG_DICT = {
    "ARI Final Integrity": "ARI 最终数据完整性报告",
    "🏛️ 앰버 호텔 경영 리포트 (Final Integrity)": "🏛️ 琥珀酒店经营报告 (Amber Hotel Management Report)",
    "설정": "设置 (Settings)",
    "🗑️ OTB 초기화": "🗑️ 重置 OTB 数据",
    "🚨 전체 초기화": "🚨 重置所有数据",
    "📌 예약/취소 조회 (기준 vs 비교)": "📌 预订/取消查询 (Target vs Comparison)",
    "기준 기간 (어제까지 선택 가능)": "基准期间 (Target Period)",
    "비교 기간 (선택사항)": "对比期间 (Comparison Period)",
    "📈 OTB 조회": "📈 OTB 查询 (On The Books)",
    "※ 파일명 날짜 / 컬럼 자동 인식": "※ 自动识别文件名日期及列名",
    "예약 리스트": "预订列表 (Reservation List)",
    "예약 저장": "保存预订数据",
    "취소 리스트": "取消列表 (Cancellation List)",
    "취소 저장": "保存取消数据",
    "OTB 파일": "OTB 文件",
    "OTB 저장": "保存 OTB 数据",
    "👑 GM 요약": "👑 总经理摘要 (GM Summary)",
    "✅ 예약 상세": "✅ 预订详情 (Res Detail)",
    "❌ 취소 상세": "❌ 取消详情 (Cncl Detail)",
    "📈 종합 합계": "📈 综合合计 (Total)",
    "🆓 0원 예약": "🆓 免费/零元预订 (Zero Rate)",
    "🎯 OTB 현황": "🎯 OTB 现状 (Pacing)",
    "✅ 예약 (Reservation List)": "✅ 预订 (Reservation List)",
    "❌ 취소 (Cancellation List)": "❌ 取消 (Cancellation List)",
    "RN": "间夜量 (RN)",
    "객실료": "客房收入 (Room Rev)",
    "총매출": "总收入 (Total Rev)",
    "ADR(Room)": "平均房价 (ADR-Room)",
    "ADR(Total)": "总平均房价 (ADR-Total)",
    "건수": "数量 (Trx)",
    "이중 RC": "其中 RC (Re-Book)",
    "매출 비중": "收入占比",
    "세그먼트별 매출": "分市场收入 (Rev by Segment)",
    "📅 Booking Pacing Matrix (Booking vs Stay)": "📅 预订进度矩阵 (Booking vs Stay)",
    "투숙월 (Stay)": "入住月份 (Stay Month)",
    "예약생성월 (Booking)": "预订创建月份 (Booking Month)",
    "📊 투숙월별 예약 분포 (Stay Month Distribution)": "📊 入住月份分布 (Stay Month Dist.)",
    "투숙월별 총 RN": "各月总间夜量 (Total RN)",
    "리드타임별 RN 실적": "提前预订期表现 (Lead Time RN)",
    "요일별 매출": "分星期收入 (Rev by Day)",
    "요일별 RN 비중": "分星期间夜占比 (RN by Day)",
    "국적별 RN 비중": "分国籍间夜占比 (RN by Nation)",
    "국적별 매출 실적": "分国籍收入表现 (Rev by Nation)",
    "조식 포함 여부 비중(RN)": "含早/不含早占比 (Breakfast Ratio)",
    "조식 상세 코드 비중": "含早代码明细 (Breakfast Code Detail)",
    "📊 세그먼트": "📊 市场细分 (Segment)",
    "📅 Pacing": "📅 预订进度 (Pacing)",
    "🏢 거래처": "🏢 代理商/客户 (Account)",
    "⏳ 리드타임": "⏳ 提前预订期 (Lead Time)",
    "🛏️ 객실타입": "🛏️ 房型 (Room Type)",
    "🗓️ 요일": "🗓️ 星期 (Day of Week)",
    "🌐 국적": "🌐 国籍 (Nationality)",
    "🍳 조식": "🍳 早餐 (Breakfast)",
    "네이버": "Naver",
    "아고다": "Agoda",
    "부킹닷컴": "Booking.com",
    "야놀자": "Yanolja",
    "여기어때": "Yeogi-Eottae",
    "익스피디아": "Expedia",
    "트립닷컴": "Trip.com",
    "마이리얼트립": "MyRealTrip",
    "가고파여행사": "Gagopa Travel",
    "산하정보기술": "Sanha IT",
    "마이스팀": "MICE Team",
    "에어비앤비": "Airbnb",
    "도매": "Wholesale",
    "기업": "Corporate",
    "여행사": "Travel Agency",
    "OTA": "OTA",
    "🏢 거래처 필터": "🏢 代理商筛选 (Filter)",
    "전체 거래처": "全部代理商 (All Accounts)",
    "거래처 선택": "选择代理商 (Select)",
    "거래처 필터 적용 중": "当前筛选 (Filtering by)",
    "데이터 없음": "无数据",
    "기간 미선택": "未选择期间",
    "⚠️ 저장할 데이터가 없습니다.": "⚠️ 没有可保存的数据。",
    "❌ 저장할 데이터가 0건입니다.": "❌ 保存的数据为 0 笔 (被过滤)",
    "✅ 데이터 {save_count}건 저장 완료!": "✅ 已成功保存 {save_count} 笔数据!",
    "⚠️ 날짜 문제로 저장된 데이터가 없습니다.": "⚠️ 因日期格式问题，未保存任何数据。",
    "📊 예약 처리": "📊 预订处理",
    "📊 취소 처리": "📊 取消处理",
    "건": "笔",
    "조식 포함 내역이 없습니다.": "无含早记录",
    "📋 데이터 검증 (Raw Data)": "📋 数据验证 (Raw Data)"
}

def T(text):
    if is_chairman_mode:
        if text in LANG_DICT: return LANG_DICT[text]
        for k, v in LANG_DICT.items():
            if k in str(text): return str(text).replace(k, v)
    return text

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
    try:
        if pd.isna(val) or str(val).strip() == '': return 0
        s = str(val).replace(',', '').replace('₩', '').replace(' ', '').strip()
        return float(s)
    except: return 0

def safe_date_parse(series):
    s1 = pd.to_datetime(series, errors='coerce')
    mask = s1.isna()
    if mask.any():
        s2 = series[mask].astype(str).str.replace(' ', '').str.replace('.', '-').str.replace('/', '-')
        s1[mask] = pd.to_datetime(s2, errors='coerce')
    return s1

def save_to_db(df, data_type='Reservation'):
    if df is None or df.empty:
        st.error(T("❌ 저장할 데이터가 0건입니다."))
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
            
            for c in sub.select_dtypes(include=['datetime64[ns]']).columns:
                sub[c] = sub[c].astype(str)
            
            sub = sub.where(pd.notnull(sub), None)
            recs = sub.to_dict(orient='records')
            
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
            
            # [핀셋 수정] OTB일 경우에만 타임스탬프를 붙여서 개별 파일로 저장 (덮어쓰기 방지)
            if data_type == 'OTB':
                did = f"{d}_{data_type}_{int(time.time()*1000)}"
            else:
                did = f"{d}_{data_type}"
            
            db.collection(COLLECTION_NAME).document(did).set({
                'data': sanitized_recs, 'uploaded_at': datetime.now(), 'snapshot_date': d, 'data_type': data_type
            })
            save_count += len(sanitized_recs)
            
        if save_count > 0:
            st.toast(T("✅ 데이터 {save_count}건 저장 완료!").format(save_count=save_count))
            return True
        return False
    except Exception as e: 
        st.error(f"Save Error: {e}")
        return False

@st.cache_data(ttl=0)
def load_db():
    try:
        docs = db.collection(COLLECTION_NAME).stream(); res = []
        for d in docs:
            dd = d.to_dict()
            snap = dd.get('snapshot_date', '')
            dtype = dd.get('data_type', 'Reservation')
            # OTB 데이터 타입 감지 강화
            if dtype == 'Reservation' and len(dd['data']) > 0 and 'OTB' in str(dd['data'][0].get('Segment', '')):
                dtype = 'OTB'
            for r in dd['data']:
                if 'Snapshot_Date' not in r: r['Snapshot_Date'] = snap
                r['Data_Type'] = dtype
                res.append(r)
        return res
    except: return []

def delete_all():
    docs = db.collection(COLLECTION_NAME).stream(); c=0
    for d in docs: d.reference.delete(); c+=1
    return c

def delete_otb():
    docs = db.collection(COLLECTION_NAME).stream(); c=0
    for d in docs:
        dd = d.to_dict()
        if dd.get('data_type') == 'OTB': d.reference.delete(); c+=1
    return c

# ==============================================================================
# 4. 파일 처리 로직
# ==============================================================================

def load_and_fix_header(file):
    try:
        if file.name.endswith('.csv'):
            try: df_raw = pd.read_csv(file, header=None, encoding='cp949')
            except: df_raw = pd.read_csv(file, header=None)
        else:
            df_raw = pd.read_excel(file, header=None)
    except: return None

    header_idx = -1
    for r in range(min(30, len(df_raw))):
        row_str = df_raw.iloc[r].astype(str).str.cat()
        if "예약번호" in row_str and ("객실료" in row_str or "총금액" in row_str):
            header_idx = r
            break
            
    if header_idx == -1: return None

    df_raw.columns = df_raw.iloc[header_idx]
    df = df_raw.iloc[header_idx+1:].copy()
    df.columns = df.columns.astype(str).str.strip()
    return df

def process_res_file(file):
    try:
        df = load_and_fix_header(file)
        if df is None:
            st.error("🚨 Header Error")
            return pd.DataFrame()

        for col in df.columns:
            if "서비스" in str(col) and "코드" in str(col):
                df.rename(columns={col: 'Service_Code'}, inplace=True)
                break

        col_map = {
            '상태': 'Status', '예약번호': 'Res_No', '고객명': 'Guest_Name',
            '입실일자': 'CheckIn', '도착일': 'CheckIn', '퇴실일자': 'CheckOut', '출발일': 'CheckOut',
            '박수': 'Nights', '객실타입': 'Room_Type', '객실수': 'Rooms',
            '객실료': 'Room_Revenue', '총금액': 'Total_Revenue', '총매출': 'Total_Revenue',
            '거래처': 'Account', '세그먼트': 'Segment', '국적': 'Nat_Orig',
            '예약일자': 'Booking_Date', '예약일': 'Booking_Date',
        }
        df = df.rename(columns=col_map)
        
        required = ['Res_No', 'Room_Revenue', 'Booking_Date', 'CheckIn', 'CheckOut']
        for c in required:
            if c not in df.columns: df[c] = np.nan

        df = df[df['Res_No'].notna()]
        df = df[~df['Res_No'].astype(str).str.contains('합계|총계|Total', case=False, na=False)]

        df['CheckIn'] = safe_date_parse(df['CheckIn'])
        df['CheckOut'] = safe_date_parse(df['CheckOut'])
        df['Booking_Date'] = safe_date_parse(df['Booking_Date'])
        
        df = df.dropna(subset=['Booking_Date']) 
        df = df.dropna(subset=['CheckIn'])

        for c in ['Nights', 'Rooms', 'Room_Revenue', 'Total_Revenue']:
            if c in df.columns: df[c] = df[c].apply(clean_num)
            else: df[c] = 0

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
        
        if 'Nat_Orig' in df.columns: df['Nat_Group'] = df['Nat_Orig'].apply(classify_nat)
        else: df['Nat_Group'] = 'OTH'
        
        if 'Segment' in df.columns: df['Segment'] = df['Segment'].astype(str).str.strip()
        else: df['Segment'] = 'Unknown'
            
        if 'Service_Code' in df.columns:
            df['Breakfast'] = df['Service_Code'].fillna('').astype(str).str.upper().apply(
                lambda x: 'Included' if 'BF' in x else 'Room Only'
            )
        else:
            df['Breakfast'] = 'Room Only'

        with st.sidebar:
            st.caption(f"{T('📊 예약 처리')}: {len(df)}{T('건')}")

        return df
    except Exception as e: st.error(f"Res Error: {e}"); return pd.DataFrame()

def process_cancel_file(file):
    try:
        df = load_and_fix_header(file)
        if df is None:
            st.error("🚨 Header Error")
            return pd.DataFrame()

        for col in df.columns:
            if "서비스" in str(col) and "코드" in str(col):
                df.rename(columns={col: 'Service_Code'}, inplace=True)
                break

        col_map = {
            '상태': 'Status', '예약번호': 'Res_No', '고객명': 'Guest_Name',
            '입실일자': 'CheckIn', '도착일': 'CheckIn', '퇴실일자': 'CheckOut', '출발일': 'CheckOut',
            '박수': 'Nights', '객실타입': 'Room_Type', '객실수': 'Rooms',
            '객실료': 'Room_Revenue', '총금액': 'Total_Revenue', '총매출': 'Total_Revenue',
            '거래처': 'Account', '세그먼트': 'Segment', '국적': 'Nat_Orig',
            '예약일자': 'Booking_Date', '예약일': 'Booking_Date',
            '취소일자': 'Cancel_Date', '취소일': 'Cancel_Date',
        }
        df = df.rename(columns=col_map)
        
        df = df[df['Res_No'].notna()]
        df = df[~df['Res_No'].astype(str).str.contains('합계|총계|Total', case=False, na=False)]

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
        
        if 'Nat_Orig' in df.columns: df['Nat_Group'] = df['Nat_Orig'].apply(classify_nat)
        else: df['Nat_Group'] = 'OTH'
            
        if 'Segment' in df.columns: df['Segment'] = df['Segment'].astype(str).str.strip()
        else: df['Segment'] = 'Unknown'
            
        if 'Service_Code' in df.columns:
            df['Breakfast'] = df['Service_Code'].fillna('').astype(str).str.upper().apply(
                lambda x: 'Included' if 'BF' in x else 'Room Only'
            )
        else:
            df['Breakfast'] = 'Room Only'

        with st.sidebar: st.caption(f"{T('📊 취소 처리')}: {len(df)}{T('건')}")
        return df
    except Exception as e: st.error(f"Cancel Error: {e}"); return pd.DataFrame()

def process_otb(file):
    try:
        if file.name.endswith('.csv'): df_raw = pd.read_csv(file, header=None, encoding='cp949')
        else: df_raw = pd.read_excel(file, header=None)
        
        snap = datetime.now().strftime('%Y-%m-%d')
        match = re.search(r'(\d{8})', file.name)
        if match: snap = f"{match.group(1)[:4]}-{match.group(1)[4:6]}-{match.group(1)[6:]}"
        
        data_list = []
        for i, row in df_raw.iterrows():
            try:
                date_val = row[0]
                ts = pd.to_datetime(date_val, errors='coerce')
                
                if pd.notnull(ts):
                    rev_val = clean_num(row.iloc[-1])
                    if rev_val > 0:
                        data_list.append({
                            'CheckIn': ts.strftime('%Y-%m-%d'),
                            'Room_Revenue': rev_val,
                            'Total_Revenue': rev_val,
                            'RN': 0, 
                            'Guest_Name': 'OTB', 
                            'Segment': 'OTB', 
                            'Snapshot_Date': snap,
                            'Status': 'Booked'
                        })
            except: continue
            
        if not data_list:
            val = int(str(df_raw.dropna(how='all').dropna(axis=1, how='all').iloc[-1, -1]).replace(',', '').split('.')[0])
            return pd.DataFrame([{'CheckIn': snap, 'Room_Revenue': val, 'Total_Revenue': val, 'RN': 0, 'Guest_Name': 'OTB', 'Segment': 'OTB', 'Snapshot_Date': snap, 'Status': 'Booked'}])
            
        return pd.DataFrame(data_list)
    except: return pd.DataFrame()

# ==============================================================================
# 5. UI 및 번역 적용
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
    if df.empty: st.info(T("데이터 없음")); return
    df = df.reset_index(drop=True)
    cols = df.select_dtypes(include=[np.number]).columns
    st.dataframe(df.style.format({c: "{:,.0f}" for c in cols}).apply(lambda r: ['background-color: #fff9c4; font-weight: bold; border-top: 2px solid black']*len(r) if str(r[0])=="TOTAL" else ['']*len(r), axis=1), hide_index=True, use_container_width=True)

def group_and_show(df, group_col):
    if df.empty: return pd.DataFrame()
    agg = df.groupby(group_col).agg({'RN': 'sum', 'Room_Revenue': 'sum', 'Total_Revenue': 'sum'}).reset_index()
    agg['ADR_Room'] = np.where(agg['RN']>0, agg['Room_Revenue']/agg['RN'], 0)
    agg['ADR_Total'] = np.where(agg['RN']>0, agg['Total_Revenue']/agg['RN'], 0)
    final_df = add_total_with_adr(agg, group_col)
    
    if is_chairman_mode:
        final_df[group_col] = final_df[group_col].apply(lambda x: LANG_DICT.get(str(x), str(x)))
        
    show_styled(final_df)
    return final_df

def render_tab(df, k):
    if df.empty: st.info(T("데이터 없음")); return
    
    t1, t2, t3, t4, t5, t6, t7, t8 = st.tabs([
        T("📊 세그먼트"), T("📅 Pacing"), T("🏢 거래처"), 
        T("⏳ 리드타임"), T("🛏️ 객실타입"), T("🗓️ 요일"), 
        T("🌐 국적"), T("🍳 조식")
    ])
    
    with t1:
        s = group_and_show(df, 'Segment')
        if not s.empty:
            c1, c2 = st.columns(2)
            c1.plotly_chart(px.pie(s, values='Room_Revenue', names='Segment', title=T("매출 비중")), use_container_width=True, key=f"{k}_p")
            c2.plotly_chart(px.bar(s, x='Segment', y='Room_Revenue', title=T("세그먼트별 매출")), use_container_width=True, key=f"{k}_b")
    
    with t2:
        st.subheader(T("📅 Booking Pacing Matrix (Booking vs Stay)"))
        p_df = df.copy()
        p_df['Booking_Month'] = p_df['Booking_Month'].astype(str).str.strip()
        p_df['Stay_Month'] = p_df['Stay_Month'].astype(str).str.strip()
        p_df = p_df.sort_values(['Booking_Month', 'Stay_Month'])
        p = p_df.pivot_table(index='Booking_Month', columns='Stay_Month', values='RN', aggfunc='sum').fillna(0)
        if not p.empty:
            fig_hm = go.Figure(data=go.Heatmap(z=p.values, x=p.columns, y=p.index, colorscale='Blues', text=p.values, texttemplate="%{text:.0f}", hoverinfo='z'))
            fig_hm.update_layout(xaxis={'type':'category', 'title':T("투숙월 (Stay)")}, yaxis={'type':'category', 'title':T("예약생성월 (Booking)")}, height=500)
            st.plotly_chart(fig_hm, use_container_width=True, key=f"{k}_hm")
            st.markdown("---")
            st.subheader(T("📊 투숙월별 예약 분포 (Stay Month Distribution)"))
            stay_dist = p_df.groupby('Stay_Month')['RN'].sum().reset_index()
            st.plotly_chart(px.bar(stay_dist, x='Stay_Month', y='RN', text_auto='.0f', title=T("투숙월별 총 RN")), use_container_width=True, key=f"{k}_stay_b")
        else: st.warning(T("페이싱 데이터 없음"))
    
    with t3: group_and_show(df, 'Account')
    
    with t4:
        df['LT_G'] = pd.cut(df['Lead_Time'], bins=[-999,0,3,7,14,30,60,90,999], labels=['0','1-3','4-7','8-14','15-30','31-60','61-90','90+'])
        l = group_and_show(df, 'LT_G')
        if not l.empty: st.plotly_chart(px.bar(l, x='LT_G', y='RN', title=T("리드타임별 RN 실적")), use_container_width=True, key=f"{k}_lt")
    
    with t5: group_and_show(df, 'Room_Type')
    
    with t6:
        w = group_and_show(df, 'Day_Type')
        if not w.empty:
            c1, c2 = st.columns(2)
            c1.plotly_chart(px.bar(w, x='Day_Type', y='Room_Revenue', title=T("요일별 매출")), use_container_width=True, key=f"{k}_w_b")
            c2.plotly_chart(px.pie(w, values='RN', names='Day_Type', title=T("요일별 RN 비중")), use_container_width=True, key=f"{k}_w_p")
    
    with t7:
        n = group_and_show(df, 'Nat_Group')
        if not n.empty:
            c1, c2 = st.columns(2)
            c1.plotly_chart(px.pie(n, values='RN', names='Nat_Group', title=T("국적별 RN 비중")), use_container_width=True, key=f"{k}_n_p")
            c2.plotly_chart(px.bar(n, x='Nat_Group', y='Room_Revenue', title=T("국적별 매출 실적")), use_container_width=True, key=f"{k}_n_b")
    
    with t8:
        b_raw = df.groupby('Breakfast').agg({'RN': 'sum'}).reset_index()
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.pie(b_raw, values='RN', names='Breakfast', title=T("조식 포함 여부 비중(RN)")), use_container_width=True, key=f"{k}_bf_pie")
        
        bf_included = df[df['Breakfast'] == 'Included']
        if not bf_included.empty and 'Service_Code' in bf_included.columns:
            detail = bf_included.groupby('Service_Code')['RN'].sum().reset_index().sort_values('RN', ascending=False)
            c2.plotly_chart(px.bar(detail, x='Service_Code', y='RN', text_auto='.0f', title=T("조식 상세 코드 비중")), use_container_width=True, key=f"{k}_bf_bar")
        else:
            c2.info(T("조식 포함 내역이 없습니다."))
            
        group_and_show(df, 'Breakfast')

    # [요청 반영] 탭 하단에 검증 데이터 (Raw Data) 표시
    st.markdown("---")
    with st.expander(T("📋 데이터 검증 (Raw Data)")):
        st.dataframe(df, use_container_width=True)

# ==============================================================================
# MAIN
# ==============================================================================
try:
    st.title(T("🏛️ 앰버 호텔 경영 리포트 (Final Integrity)"))
    raw = load_db()
    df_all = pd.DataFrame(raw) if raw else pd.DataFrame(columns=['Snapshot_Date','Data_Type'])
    
    for c in ['RN','Room_Revenue','Total_Revenue','Rooms','Nights','Lead_Time']:
        if c in df_all.columns: df_all[c] = pd.to_numeric(df_all[c], errors='coerce').fillna(0)

    otb_dates = sorted(df_all[df_all['Data_Type']=='OTB']['Snapshot_Date'].unique(), reverse=True)

    with st.sidebar:
        st.header(T("설정"))
        if st.button(T("🗑️ OTB 초기화")): delete_otb(); st.rerun()
        if st.button(T("🚨 전체 초기화")): delete_all(); st.rerun()
        st.divider()
        st.subheader(T("📌 예약/취소 조회 (기준 vs 비교)"))
        
        now_kst = datetime.now() + timedelta(hours=9)
        yesterday = now_kst.date() - timedelta(days=1)
        
        default_val = (yesterday, yesterday)
        dates_selected = st.date_input(T("기준 기간 (어제까지 선택 가능)"), value=default_val, max_value=yesterday, format="YYYY-MM-DD")
        
        sel_start = dates_selected[0].strftime('%Y-%m-%d') if isinstance(dates_selected, tuple) and len(dates_selected)>0 else yesterday.strftime('%Y-%m-%d')
        sel_end = dates_selected[1].strftime('%Y-%m-%d') if isinstance(dates_selected, tuple) and len(dates_selected)>1 else sel_start
        
        comp_selected = st.date_input(T("비교 기간 (선택사항)"), value=(), max_value=yesterday, format="YYYY-MM-DD")
        c_start = comp_selected[0].strftime('%Y-%m-%d') if isinstance(comp_selected, tuple) and len(comp_selected)>0 else None
        c_end = comp_selected[1].strftime('%Y-%m-%d') if isinstance(comp_selected, tuple) and len(comp_selected)>1 else c_start

        # ==============================================================================
        # [UI 추가] 🏢 거래처 필터 (데이터 연동)
        # ==============================================================================
        st.divider()
        st.subheader(T("🏢 거래처 필터"))
        all_accounts = ["전체 거래처"]
        if not df_all.empty and 'Account' in df_all.columns:
            raw_accs = sorted(df_all['Account'].dropna().astype(str).unique().tolist())
            all_accounts.extend(raw_accs)
        
        acc_idx = st.selectbox(
            T("거래처 선택"), 
            range(len(all_accounts)), 
            format_func=lambda x: T(all_accounts[x])
        )
        selected_acc = all_accounts[acc_idx]

        st.divider()
        sel_otb = st.selectbox(T("📈 OTB 조회"), otb_dates) if otb_dates else None
        st.divider()
        f1 = st.file_uploader(T("예약 리스트"), type=['xlsx','csv'])
        if f1 and st.button(T("예약 저장")):
            if save_to_db(process_res_file(f1), 'Reservation'): st.rerun()
        f2 = st.file_uploader(T("취소 리스트"), type=['xlsx','csv'])
        if f2 and st.button(T("취소 저장")):
            if save_to_db(process_cancel_file(f2), 'Cancellation'): st.rerun()
        f3 = st.file_uploader(T("OTB 파일"), type=['xlsx','csv'], accept_multiple_files=True)
        # [핀셋 수정] OTB 저장 시 개별 저장으로 복구 (타임스탬프 ID 생성으로 덮어쓰기 방지)
        if f3 and st.button(T("OTB 저장")):
            for f in f3: save_to_db(process_otb(f), 'OTB')
            st.rerun()

    # 데이터 필터링
    if sel_start and sel_end and not df_all.empty:
        mask_bk = (df_all['Data_Type']=='Reservation') & (df_all['Snapshot_Date'] >= sel_start) & (df_all['Snapshot_Date'] <= sel_end)
        
        if selected_acc != "전체 거래처":
            mask_bk = mask_bk & (df_all['Account'] == selected_acc)
            
        df_bk = df_all[mask_bk & (df_all['Total_Revenue']>0)].copy()
        df_zero = df_all[mask_bk & (df_all['Total_Revenue']<=0)].copy()
        
        mask_cn = (df_all['Data_Type']=='Cancellation') & (df_all['Snapshot_Date'] >= sel_start) & (df_all['Snapshot_Date'] <= sel_end)
        
        if selected_acc != "전체 거래처":
            mask_cn = mask_cn & (df_all['Account'] == selected_acc)
            
        df_cn = df_all[mask_cn].copy()
        if df_cn.empty and not df_bk.empty: 
            df_cn = df_all[mask_bk & (df_all['Status']=='RC')].copy()
        
        df_tot = pd.concat([df_bk, df_cn])
        
        df_bk_comp = pd.DataFrame(); df_cn_comp = pd.DataFrame()
        if c_start and c_end:
            mask_bk_c = (df_all['Data_Type']=='Reservation') & (df_all['Snapshot_Date'] >= c_start) & (df_all['Snapshot_Date'] <= c_end)
            mask_cn_c = (df_all['Data_Type']=='Cancellation') & (df_all['Snapshot_Date'] >= c_start) & (df_all['Snapshot_Date'] <= c_end)
            
            if selected_acc != "전체 거래처":
                mask_bk_c = mask_bk_c & (df_all['Account'] == selected_acc)
                mask_cn_c = mask_cn_c & (df_all['Account'] == selected_acc)
                
            df_bk_comp = df_all[mask_bk_c & (df_all['Total_Revenue']>0)].copy()
            df_cn_comp = df_all[mask_cn_c].copy()
            if df_cn_comp.empty and not df_all[mask_bk_c].empty: df_cn_comp = df_all[mask_bk_c & (df_all['Status']=='RC')]
    else:
        df_bk, df_zero, df_cn, df_tot = pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        df_bk_comp, df_cn_comp = pd.DataFrame(), pd.DataFrame()

    if sel_otb and not df_all.empty:
        df_o = df_all[(df_all['Snapshot_Date']==sel_otb) & (df_all['Data_Type']=='OTB')].copy()
    else:
        df_o = pd.DataFrame()

    tabs = st.tabs([T("👑 GM 요약"), T("✅ 예약 상세"), T("❌ 취소 상세"), T("📈 종합 합계"), T("🆓 0원 예약"), T("🎯 OTB 현황")])
    with tabs[0]:
        disp = f"{sel_start}~{sel_end}" if sel_start else T("기간 미선택")
        st.header(f"{T('👑 GM 요약')} ({disp})")
        
        if selected_acc != "전체 거래처":
            st.caption(f"🎯 {T('거래처 필터 적용 중')}: {T(selected_acc)}")
            
        if df_bk.empty and df_cn.empty: st.info(T("데이터 없음"))
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

            st.markdown(f"#### {T('✅ 예약 (Reservation List)')}")
            col = st.columns(6)
            col[0].metric(T("RN"), f"{b_rn:,.0f}", delta=f"{b_rn - b_rn_c:,.0f}" if c_start else None)
            col[1].metric(T("객실료"), f"{b_rev:,.0f}", delta=f"{b_rev - b_rev_c:,.0f}" if c_start else None)
            col[2].metric(T("총매출"), f"{b_tot:,.0f}", delta=f"{b_tot - b_tot_c:,.0f}" if c_start else None)
            col[3].metric(T("ADR(Room)"), f"{b_rev/b_rn if b_rn>0 else 0:,.0f}")
            col[4].metric(T("ADR(Total)"), f"{b_tot/b_rn if b_rn>0 else 0:,.0f}")
            col[5].metric(T("건수"), f"{len(df_bk):,.0f}", delta=f"{T('이중 RC')}: {rc_in_bk}")
            
            st.markdown(f"#### {T('❌ 취소 (Cancellation List)')}")
            col = st.columns(6)
            col[0].metric(T("RN"), f"{c_rn:,.0f}", delta=f"{c_rn - c_rn_c:,.0f}" if c_start else None, delta_color="inverse")
            col[1].metric(T("객실료"), f"{c_rev:,.0f}", delta=f"{c_rev - c_rev_c:,.0f}" if c_start else None, delta_color="inverse")
            col[2].metric(T("총매출"), f"{c_tot:,.0f}", delta=f"{c_tot - c_tot_c:,.0f}" if c_start else None, delta_color="inverse")
            col[3].metric(T("ADR(Room)"), f"{c_rev/c_rn if c_rn>0 else 0:,.0f}")
            col[4].metric(T("ADR(Total)"), f"{c_tot/c_rn if c_rn>0 else 0:,.0f}")
            col[5].metric(T("건수"), f"{len(df_cn):,.0f}")
            
            st.divider()
            if not df_bk.empty: group_and_show(df_bk, 'Segment')
            
            c1, c2 = st.columns(2)
            with c1:
                if not df_bk.empty: st.plotly_chart(px.pie(df_bk.groupby('Nat_Group')['RN'].sum().reset_index(), values='RN', names='Nat_Group', hole=0.4, title=T("국적별 RN 비중")), use_container_width=True)
            with c2:
                comb = pd.concat([df_bk.assign(Type='Book'), df_cn.assign(Type='Cancel')])
                if not comb.empty: st.plotly_chart(px.bar(comb.groupby(['Stay_Month','Type'])['RN'].sum().reset_index(), x='Stay_Month', y='RN', color='Type', barmode='group', title=T("📊 투숙월별 예약 분포 (Stay Month Distribution)")), use_container_width=True)

    with tabs[1]: render_tab(df_bk, "bk")
    with tabs[2]: render_tab(df_cn, "cn")
    with tabs[3]: render_tab(df_tot, "tot")
    with tabs[4]: 
        st.subheader(f"{T('🆓 0원 예약')} ({len(df_zero)}{T('건')})")
        if not df_zero.empty: st.dataframe(df_zero[['Guest_Name','CheckIn','Account','Room_Type']], use_container_width=True)
    with tabs[5]:
        st.header(f"{T('🎯 OTB 현황')} ({sel_otb})")
        if df_o.empty: st.warning(T("데이터 없음"))
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

except Exception as e: st.error(f"Error: {e}")
