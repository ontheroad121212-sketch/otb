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
# 0. 사용자 정의 버짓 데이터 (1월~12월)
# ==============================================================================
BUDGET_DATA = { 
    1: 514992575, 2: 786570856, 3: 529599040, 4: 695351004,
    5: 903705440, 6: 808203820, 7: 1231949142, 8: 1388376999,
    9: 952171506, 10: 897171539, 11: 667146771, 12: 804030110 
}

# ==============================================================================
# 1. 페이지 설정
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
# 3. 데이터 전처리 유틸리티
# ==============================================================================

def clean_numeric_columns(df):
    # 숫자 컬럼들만 골라서 쉼표 제거 및 숫자 변환
    target_cols = [
        'RN', 'Room_Revenue', 'Total_Revenue', 'ADR_Room', 'ADR_Total', 
        'Lead_Time', 'OTB_Rev', 'Budget_Rev', 'Rooms', 'Nights'
    ]
    for col in target_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(
                df[col].astype(str).str.replace(',', '').str.replace('nan', '0').str.replace('₩', '').str.strip(), 
                errors='coerce'
            ).fillna(0)
    return df

def save_to_firestore_split_by_date(df, is_otb=False):
    try:
        if df.empty: return False
        
        # 날짜 컬럼 없으면 오늘로
        if 'Snapshot_Date' not in df.columns:
            df['Snapshot_Date'] = datetime.now().strftime('%Y-%m-%d')
            
        unique_dates = df['Snapshot_Date'].unique()
        
        for s_date in unique_dates:
            date_df = df[df['Snapshot_Date'] == s_date].copy()
            if date_df.empty: continue
            
            records = date_df.fillna(0).astype(str).to_dict(orient='records')
            data_type = 'OTB' if is_otb else 'Reservation'
            
            # 예약 상태(Status)가 있으면 ID에 포함
            status_part = ""
            if not is_otb and 'Status' in date_df.columns:
                status_part = f"_{date_df['Status'].iloc[0]}"

            doc_id = f"{s_date}_{data_type}{status_part}_{int(time.time()*1000)}"
            
            db.collection(COLLECTION_NAME).document(doc_id).set({
                'data': records,
                'uploaded_at': datetime.now(),
                'snapshot_date': s_date,
                'data_type': data_type
            })
        return True
    except Exception as e:
        st.error(f"❌ 저장 오류: {e}"); return False

@st.cache_data(ttl=0)
def load_data_from_firestore():
    try:
        docs = db.collection(COLLECTION_NAME).stream()
        all_data = []
        for doc in docs:
            d = doc.to_dict()
            if 'data' in d:
                snap = d.get('snapshot_date', '')
                dtype = d.get('data_type', 'Reservation')
                rows = d['data']
                for row in rows:
                    if 'Snapshot_Date' not in row: row['Snapshot_Date'] = snap
                    row['Data_Type'] = dtype
                    all_data.append(row)
        return all_data
    except: return []

def delete_all_records():
    try:
        docs = db.collection(COLLECTION_NAME).stream(); cnt = 0
        for doc in docs: doc.reference.delete(); cnt += 1
        return cnt
    except: return 0

def delete_otb_data_only():
    try:
        docs = db.collection(COLLECTION_NAME).stream(); cnt = 0
        for doc in docs:
            d = doc.to_dict()
            if d.get('data_type') == 'OTB': doc.reference.delete(); cnt += 1
        return cnt
    except: return 0

# ==============================================================================
# 4. 파일 처리 (매핑 정밀화 + RN 근본 계산)
# ==============================================================================

def normalize_and_map_columns(df):
    col_map = {}
    
    # 1. 컬럼명을 문자열로 변환하고 공백 제거 (전처리)
    df.columns = [str(c).strip() for c in df.columns]
    
    # 2. 우선순위가 높은 "정확한 이름"부터 매핑
    # (주의: '객실료'가 '객실수'로 오인되지 않게 하는 것이 핵심)
    
    # [객실수] - '객실수', 'Rooms', 'Rmws' (절대 '료', '금액' 등이 포함되면 안됨)
    for c in df.columns:
        if c in ['객실수', 'Rooms', 'Rmws', 'Qty']:
            col_map[c] = 'Rooms'
            break # 찾으면 즉시 종료 (우선순위 1)
    
    # [박수] - '박수', 'Nights', 'LOS'
    if 'Nights' not in col_map.values():
        for c in df.columns:
            if c in ['박수', 'Nights', 'LOS']:
                col_map[c] = 'Nights'
                break

    # [객실료] - '객실료', 'Room Revenue'
    if 'Room_Revenue' not in col_map.values():
        for c in df.columns:
            clean_c = c.replace(" ", "").lower()
            if '객실료' in c or 'roomrev' in clean_c or 'roomrate' in clean_c:
                col_map[c] = 'Room_Revenue'
                break

    # 나머지 일반 컬럼 매핑
    rules = {
        'CheckIn': ['입실', 'checkin', 'arrival'],
        'Guest_Name': ['고객명', 'guest', 'name'],
        'Booking_Date': ['예약일', 'booking', 'create'],
        'Cancel_Date': ['취소일', 'cancel'],
        'Total_Revenue': ['총금액', '합계', 'total'],
        'Segment': ['세그먼트', 'segment'],
        'Account': ['거래처', 'account', 'source', 'agent'],
        'Room_Type': ['객실타입', 'type', 'cat'],
        'Nat_Orig': ['국적', 'nation', 'country']
    }
    
    for c in df.columns:
        if c in col_map: continue # 이미 매핑된 건 패스
        clean_c = c.replace(" ", "").lower()
        
        for target, kws in rules.items():
            if any(kw in clean_c for kw in kws):
                # 방어: Rooms나 Nights로 이미 매핑된 컬럼은 덮어쓰지 않음
                if target not in col_map.values():
                    col_map[c] = target
                break
                
    return df.rename(columns=col_map)

def process_data(uploaded_file, status):
    try:
        if uploaded_file.name.endswith('.csv'):
            try: df_raw = pd.read_csv(uploaded_file, header=2, encoding='cp949')
            except: df_raw = pd.read_csv(uploaded_file, header=2)
        else:
            df_raw = pd.read_excel(uploaded_file, header=2)

        def scan_bf(row):
            return 'Included (조식포함)' if 'BF' in "".join(row.astype(str).values).upper() else 'Not Included (불포함)'
        breakfast_col = df_raw.apply(scan_bf, axis=1)

        # 컬럼 매핑 실행
        df = normalize_and_map_columns(df_raw).copy()
        df['Breakfast'] = breakfast_col
        df['Status'] = status

        # 날짜 변환
        for d_col in ['CheckIn', 'Booking_Date', 'Cancel_Date']:
            if d_col in df.columns:
                df[d_col] = pd.to_datetime(df[d_col].astype(str).str.replace('.', '-'), errors='coerce')

        # 리드타임
        if 'CheckIn' in df.columns and 'Booking_Date' in df.columns:
            df['Lead_Time'] = (df['CheckIn'] - df['Booking_Date']).dt.days.fillna(0)
        else:
            df['Lead_Time'] = 0

        # Snapshot_Date 생성 (분할 저장 기준)
        target_date_col = 'Booking_Date' if status == 'Booked' else 'Cancel_Date'
        if target_date_col in df.columns:
            df['Snapshot_Date'] = df[target_date_col].dt.strftime('%Y-%m-%d')
            df['Snapshot_Date'] = df['Snapshot_Date'].fillna(datetime.now().strftime('%Y-%m-%d'))
        else:
            df['Snapshot_Date'] = datetime.now().strftime('%Y-%m-%d')

        # [근본 해결] 숫자 정리 및 RN 계산
        # 1. Rooms와 Nights 컬럼이 제대로 매핑되었는지 확인
        if 'Rooms' not in df.columns: df['Rooms'] = 1 # 없으면 기본 1
        if 'Nights' not in df.columns: df['Nights'] = 1 # 없으면 기본 1
        
        # 2. 숫자로 변환 (오류 발생 시 0)
        df['Rooms_Num'] = pd.to_numeric(df['Rooms'], errors='coerce').fillna(0)
        df['Nights_Num'] = pd.to_numeric(df['Nights'], errors='coerce').fillna(1)
        
        # 3. RN = 객실수 * 박수 (제한 없음, 파일 값 그대로)
        df['RN'] = df['Rooms_Num'] * df['Nights_Num']
        
        # 매출 정리
        df = clean_numeric_columns(df) # 여기서 쉼표 제거 등 수행
        df['Total_Revenue'] = np.where(df['Total_Revenue'] == 0, df['Room_Revenue'], df['Total_Revenue'])
        
        # 파생 변수
        if 'CheckIn' in df.columns:
            df['Stay_Month'] = df['CheckIn'].dt.strftime('%Y-%m')
            df['Day_Type'] = df['CheckIn'].dt.weekday.apply(lambda x: 'Weekend' if x >= 4 else 'Weekday')
        
        if 'Booking_Date' in df.columns:
            df['Booking_Month'] = df['Booking_Date'].dt.strftime('%Y-%m')
        else:
            df['Booking_Month'] = df.get('Stay_Month', '')

        # 국적 분류
        def classify_nat(row):
            name = str(row.get('Guest_Name',''))
            orig = str(row.get('Nat_Orig', '')).upper()
            if re.search('[가-힣]', name): return 'KOR'
            if any(x in orig for x in ['CHN', 'HKG', 'TWN', 'MAC']): return 'CHN'
            if any(x in orig for x in ['JPN']): return 'JPN'
            return 'OTH'
        df['Nat_Group'] = df.apply(classify_nat, axis=1)

        return df
            
    except Exception as e:
        st.error(f"⚠️ 파일 처리 오류: {e}"); return pd.DataFrame()

def process_otb(uploaded_file):
    try:
        # 파일명 날짜 추출 (YYYYMMDD)
        filename_date = None
        match = re.search(r'(\d{8})', uploaded_file.name)
        if match:
            d = match.group(1)
            filename_date = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        
        if uploaded_file.name.endswith('.csv'):
            df_raw = pd.read_csv(uploaded_file, header=None, encoding='cp949')
        else:
            df_raw = pd.read_excel(uploaded_file, header=None)
            
        target_month_str = datetime.now().strftime('%Y-%m-%d')
        date_pattern = re.compile(r'20\d{2}-(\d{2})')
        for r in range(min(15, len(df_raw))):
            row_str = " ".join(df_raw.iloc[r].astype(str).values)
            match = date_pattern.search(row_str)
            if match:
                target_month_str = f"2026-{match.group(1)}-01"; break
        
        df_clean = df_raw.dropna(how='all').dropna(axis=1, how='all')
        try:
            raw_val = str(df_clean.iloc[-1, -1])
            total_rev = int(raw_val.replace(',', '').split('.')[0])
        except: total_rev = 0
        
        final_snap = filename_date if filename_date else datetime.now().strftime('%Y-%m-%d')

        return pd.DataFrame([{
            'CheckIn': target_month_str,
            'Room_Revenue': total_rev, 'Total_Revenue': total_rev, 'RN': 0,
            'Guest_Name': 'OTB', 'Segment': 'OTB', 'Snapshot_Date': final_snap, 'Status': 'Booked'
        }])
    except Exception as e:
        st.error(f"OTB 오류: {e}"); return pd.DataFrame()

# ==============================================================================
# 5. UI 헬퍼
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
    return pd.concat([df, pd.DataFrame([total_row])], ignore_index=True)

def show_df_styled(df):
    if df.empty: st.info("데이터 없음"); return
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    styler = df.style.format({col: "{:,.0f}" for col in numeric_cols})
    st.dataframe(styler.apply(lambda r: ['background-color: #fff9c4; font-weight: 900; border-top: 2px solid black'] * len(r) if any(str(v)=="TOTAL" for v in r) else ['']*len(r), axis=1), hide_index=True, use_container_width=True)

def render_tabs(df, key):
    if df.empty: st.info("데이터 없음"); return
    t1, t2, t3, t4, t5, t6, t7, t8 = st.tabs(["📊 세그먼트", "📅 Pacing", "🏢 거래처", "⏳ 리드타임", "🛏️ 객실타입", "🗓️ 요일", "🌐 국적", "🍳 조식"])
    with t1:
        s = df.groupby('Segment').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.pie(s, values='Room_Revenue', names='Segment'), use_container_width=True, key=f"{key}_pie")
        c2.plotly_chart(px.bar(s, x='Segment', y='Room_Revenue'), use_container_width=True, key=f"{key}_bar")
        show_df_styled(add_total_row(s, 'Segment'))
    with t2:
        piv = df.pivot_table(index='Booking_Month', columns='Stay_Month', values='RN', aggfunc='sum').fillna(0)
        st.plotly_chart(px.imshow(piv, text_auto="d", aspect="auto", color_continuous_scale="Blues"), use_container_width=True, key=f"{key}_pace")
    with t3:
        a = df.groupby('Account').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index().sort_values('RN', ascending=False).head(50)
        show_df_styled(add_total_row(a, 'Account'))
    with t4:
        bins = [-1, 0, 3, 7, 14, 30, 60, 90, 999]; labels = ['0일', '1-3일', '4-7일', '8-14일', '15-30일', '31-60일', '61-90일', '90일+']
        df['LT_G'] = pd.cut(df['Lead_Time'], bins=bins, labels=labels)
        l = df.groupby('LT_G', observed=True).agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
        st.plotly_chart(px.bar(l, x='LT_G', y='RN'), use_container_width=True, key=f"{key}_lt")
        show_df_styled(add_total_row(l, 'LT_G'))
    with t5: show_df_styled(add_total_row(df.groupby('Room_Type').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index(), 'Room_Type'))
    with t6:
        w = df.groupby('Day_Type').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index()
        st.plotly_chart(px.bar(w, x='Day_Type', y='Room_Revenue'), use_container_width=True, key=f"{key}_wd")
    with t7: show_df_styled(add_total_row(df.groupby('Nat_Group').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index(), 'Nat_Group'))
    with t8:
        if 'Breakfast' in df.columns:
            b = df.groupby('Breakfast').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index()
            c1, c2 = st.columns(2)
            c1.plotly_chart(px.pie(b, values='RN', names='Breakfast'), use_container_width=True, key=f"{key}_bf")
            show_df_styled(add_total_row(b, 'Breakfast'))

# ==============================================================================
# 6. 메인 실행부
# ==============================================================================
try:
    st.title("🏛️ 앰버 호텔 경영 리포트 (Final Integrity)")
    raw_data = load_data_from_firestore()
    if raw_data: df_all = pd.DataFrame(raw_data)
    else: df_all = pd.DataFrame(columns=['Snapshot_Date', 'Data_Type'])

    # [핵심] 예약 날짜와 OTB 날짜 분리
    res_dates_all = sorted(df_all[df_all.get('Data_Type') == 'Reservation']['Snapshot_Date'].unique(), reverse=True)
    
    # [사용자 요청] 오늘 날짜(실행일)는 예약 조회 목록에서 무조건 제외
    today_str = datetime.now().strftime('%Y-%m-%d')
    res_dates = [d for d in res_dates_all if d != today_str]
    
    otb_dates = sorted(df_all[df_all.get('Data_Type') == 'OTB']['Snapshot_Date'].unique(), reverse=True)

    with st.sidebar:
        st.header("📅 조회 설정")
        if st.button("🗑️ OTB 초기화"):
            c = delete_otb_data_only(); st.warning(f"{c}건 삭제"); time.sleep(1); st.cache_data.clear(); st.rerun()
        if st.button("🚨 전체 초기화"):
            c = delete_all_records(); st.warning(f"{c}건 삭제"); time.sleep(1); st.cache_data.clear(); st.rerun()
            
        st.markdown("---")
        sel_res_date = st.selectbox("📌 예약/취소 조회 (오늘 제외)", res_dates, index=0) if res_dates else None
        sel_otb_date = st.selectbox("📈 OTB 조회 (파일명 기준)", otb_dates, index=0) if otb_dates else None
        
        st.markdown("---")
        st.header("📤 업로드")
        f1 = st.file_uploader("예약 리스트", type=['xlsx','csv'], key="f1")
        if f1 and st.button("예약 저장"):
            if save_to_firestore_split_by_date(process_data(f1, "Booked"), is_otb=False): st.cache_data.clear(); st.rerun()
        f2 = st.file_uploader("취소 리스트", type=['xlsx','csv'], key="f2")
        if f2 and st.button("취소 저장"):
            if save_to_firestore_split_by_date(process_data(f2, "Cancelled"), is_otb=False): st.cache_data.clear(); st.rerun()
        f3_list = st.file_uploader("OTB 파일", type=['xlsx','csv'], key="f3", accept_multiple_files=True)
        if f3_list and st.button("OTB 저장"):
            all_otb = [process_otb(f) for f in f3_list]
            if all_otb and save_to_firestore_split_by_date(pd.concat(all_otb, ignore_index=True), is_otb=True): st.cache_data.clear(); st.rerun()

    # 1. 예약/취소 데이터 준비
    if sel_res_date and not df_all.empty:
        df_res = clean_numeric_columns(df_all[(df_all['Snapshot_Date'] == sel_res_date) & (df_all['Data_Type'] == 'Reservation')].copy())
        df_paid_bk = df_res[(df_res['Status'] == 'Booked') & (df_res['Total_Revenue'] > 0)]
        df_zero_bk = df_res[(df_res['Status'] == 'Booked') & (df_res['Total_Revenue'] <= 0)]
        df_cn = df_res[df_res['Status'] == 'Cancelled']
        df_tot = pd.concat([df_paid_bk, df_cn])
    else:
        df_paid_bk, df_zero_bk, df_cn, df_tot = pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    # 2. OTB 데이터 준비
    if sel_otb_date and not df_all.empty:
        df_otb = clean_numeric_columns(df_all[(df_all['Snapshot_Date'] == sel_otb_date) & (df_all['Data_Type'] == 'OTB')].copy())
    else:
        df_otb = pd.DataFrame()

    # 3. 메인 화면
    tabs = st.tabs(["👑 GM 요약", "✅ 예약 상세", "❌ 취소 상세", "📈 종합 합계", "🆓 0원 예약", "🎯 OTB 현황"])

    with tabs[0]:
        st.header(f"👑 총지배인 요약 ({sel_res_date})")
        if df_paid_bk.empty and df_cn.empty:
            st.info("데이터 없음 (또는 오늘 날짜는 제외됨)")
        else:
            b_rn, b_rev = df_paid_bk['RN'].sum(), df_paid_bk['Room_Revenue'].sum()
            c_rn, c_rev = df_cn['RN'].sum(), df_cn['Room_Revenue'].sum()
            b_los = b_rn / len(df_paid_bk) if not df_paid_bk.empty else 0
            c_los = c_rn / len(df_cn) if not df_cn.empty else 0
            
            st.markdown("#### ✅ 예약")
            c = st.columns(5); c[0].metric("RN", f"{b_rn:,.0f}"); c[1].metric("매출", f"{b_rev:,.0f}"); c[2].metric("ADR", f"{b_rev/b_rn if b_rn>0 else 0:,.0f}"); c[3].metric("LOS", f"{b_los:.1f}박"); c[4].metric("건수", f"{len(df_paid_bk):,.0f}")
            st.markdown("#### ❌ 취소")
            cc = st.columns(5); cc[0].metric("RN", f"{c_rn:,.0f}"); cc[1].metric("매출", f"{c_rev:,.0f}"); cc[2].metric("ADR", f"{c_rev/c_rn if c_rn>0 else 0:,.0f}"); cc[3].metric("LOS", f"{c_los:.1f}박"); cc[4].metric("건수", f"{len(df_cn):,.0f}")
            st.divider()
            
            if not df_paid_bk.empty: show_df_styled(add_total_row(df_paid_bk.groupby('Segment').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index(), 'Segment'))
            
            c1, c2 = st.columns(2)
            with c1:
                if not df_paid_bk.empty: st.plotly_chart(px.pie(df_paid_bk.groupby('Nat_Group')['RN'].sum().reset_index(), values='RN', names='Nat_Group', hole=0.4, title="국적 비중"), use_container_width=True)
            with c2:
                comb = pd.concat([df_paid_bk.assign(Type='Book'), df_cn.assign(Type='Cancel')])
                if not comb.empty: st.plotly_chart(px.bar(comb.groupby(['Stay_Month','Type'])['RN'].sum().reset_index(), x='Stay_Month', y='RN', color='Type', barmode='group'), use_container_width=True)

    with tabs[1]: render_tabs(df_paid_bk, "bk")
    with tabs[2]: render_tabs(df_cn, "cn")
    with tabs[3]: render_tabs(df_tot, "tot")
    with tabs[4]: 
        st.subheader(f"🆓 0원 예약 ({len(df_zero_bk)}건)")
        if not df_zero_bk.empty: st.dataframe(df_zero_bk[['Guest_Name', 'CheckIn', 'Account', 'Room_Type']], use_container_width=True)
        else: st.write("없음")

    with tabs[5]:
        st.header(f"🎯 OTB ({sel_otb_date})")
        if df_otb.empty: st.warning("데이터 없음")
        else:
            df_otb['M'] = pd.to_datetime(df_otb['CheckIn']).dt.month
            agg_otb = df_otb.groupby('M').agg({'Room_Revenue':'sum'}).reset_index()
            fin = pd.merge(pd.DataFrame({'M': range(1, 13)}), agg_otb, on='M', how='left').fillna(0)
            fin['Budget'] = fin['M'].map(BUDGET_DATA).fillna(0)
            fin['OTB'] = fin['Room_Revenue']
            fin['Rate'] = np.where(fin['Budget'] > 0, (fin['OTB'] / fin['Budget']) * 100, 0)
            fin['Name'] = fin['M'].astype(str) + "월"
            
            fig = go.Figure()
            fig.add_trace(go.Bar(x=fin['Name'], y=fin['OTB'], name='OTB', text=fin['Rate'].apply(lambda x: f"{x:.1f}%"), textposition='outside'))
            fig.add_trace(go.Scatter(x=fin['Name'], y=fin['Budget'], name='Budget', line=dict(color='red', dash='dot')))
            st.plotly_chart(fig, use_container_width=True)
            
            res_dict = {}
            tb, to = fin['Budget'].sum(), fin['OTB'].sum()
            for _, r in fin.iterrows(): res_dict[r['Name']] = [f"{r['Budget']:,.0f}", f"{r['OTB']:,.0f}", f"{r['Rate']:.1f}%"]
            res_dict['Total'] = [f"{tb:,.0f}", f"{to:,.0f}", f"{(to/tb*100 if tb>0 else 0):.1f}%"]
            st.dataframe(pd.DataFrame(res_dict, index=['Budget', 'OTB', 'Achiev%']).T)

except Exception as e: st.error(f"🚨 오류: {e}")

try:
    save_month = datetime.now().month
    if 'sob_curr' in locals() and sob_curr is not None:
        st.session_state[f"sob_{save_month}"] = sob_curr
except: pass
