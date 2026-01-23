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
        font-weight: 900 !important; background-color: #fff9c4 !important; color: black; border-top: 2px solid black;
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
        st.error(f"🔥 DB 연결 실패: {e}")
        st.stop()

db = firestore.client()
COLLECTION_NAME = "revenue_integrity_history"

# ==============================================================================
# 3. 데이터 처리 함수
# ==============================================================================

def clean_numeric_columns(df):
    """숫자 컬럼 강제 변환 및 ADR 재계산"""
    target_cols = ['RN', 'Room_Revenue', 'Total_Revenue', 'ADR_Room', 'ADR_Total', 'Lead_Time', 
                   'OTB_Rev', 'Budget_Rev', 'Budget_Achiev', 'OTB_RN']
    for col in target_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(
                df[col].astype(str).str.replace(',', '').str.replace('nan', '0'), 
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
                first = d['data'][0]
                if 'OTB' in str(first.get('Segment','')) or 'OTB' in str(first.get('Guest_Name','')):
                    doc.reference.delete()
                    cnt += 1
        return cnt
    except: return 0

# ==============================================================================
# 4. 엑셀 처리 로직 (핵심 수정됨)
# ==============================================================================

def normalize_and_map_columns(df):
    col_map = {}
    rules = {
        'CheckIn': ['checkin', 'arrival', '입실', '일자', 'date'],
        'Guest_Name': ['guest', 'name', 'customer', '고객', '성명'],
        'Booking_Date': ['booking', 'create', 'res', '예약', '생성'],
        'Rooms': ['room', 'qty', 'rmws', '객실수', '수량'],
        'Nights': ['night', 'los', '박수', '박'],
        'Room_Revenue': ['room_rev', 'revenue', 'roomrate', '객실료', '매출'],
        'Total_Revenue': ['total', 'amount', '총금액', '합계'],
        'Segment': ['segment', '세그먼트'],
        'Account': ['account', 'agent', '거래처'],
        'Room_Type': ['type', 'cat', '객실타입'],
        'Rate_Plan': ['rate', 'plan', '상품', '패키지'], 
        'Service_Code': ['service', '서비스', 'code'], 
        'Nat_Orig': ['nation', 'country', 'nat', '국적'],
        'Lead_Time': ['lead', '리드', 'lt']
    }
    for col in df.columns:
        clean = str(col).lower().replace(" ", "").replace("_", "")
        for key, kw_list in rules.items():
            if any(k in clean for k in kw_list):
                if key == 'Room_Revenue' and 'total' in clean: continue
                if key == 'Total_Revenue' and 'room' in clean: continue
                if key == 'CheckIn' and ('book' in clean or 'res' in clean): continue
                if key not in col_map.values():
                    col_map[col] = key
                    break
    return df.rename(columns=col_map)

def process_data(file, status, force_otb=False):
    """
    [수정 포인트]
    1. OTB: 무조건 맨 마지막 행(총합계)의 맨 마지막 열(매출) 값을 가져옴.
    2. 조식: 서비스코드(K열 추정)에 'BF'가 있으면 조식으로 간주.
    """
    try:
        is_otb = force_otb or "Sales on the Book" in file.name
        
        if file.name.endswith('.csv'):
            try: df_raw = pd.read_csv(file, header=None)
            except: df_raw = pd.read_csv(file, header=None, encoding='cp949')
        else:
            df_raw = pd.read_excel(file, header=None)

        # ---------------------------------------------------------
        # [A] OTB 데이터 처리
        # ---------------------------------------------------------
        if is_otb:
            # 1. 월(Month) 파악
            target_month_date = datetime.now()
            # 상위 10행에서 날짜 찾기
            for r in range(10):
                row_vals = df_raw.iloc[r].astype(str).values
                for v in row_vals:
                    match = re.search(r'20\d{2}-\d{2}', v)
                    if match:
                        try:
                            target_month_date = pd.to_datetime(match.group() + "-01")
                            break
                        except: pass
                if target_month_date != datetime.now(): break

            # 2. 총 매출 추출 (무조건 마지막 행, 마지막 열)
            try:
                # 빈 행/열 제거
                df_clean = df_raw.dropna(how='all').dropna(axis=1, how='all')
                
                # 맨 마지막 셀 값 가져오기
                last_val = str(df_clean.iloc[-1, -1])
                # 숫자만 남기고 변환
                clean_val = last_val.replace(',', '').replace('nan', '0').replace(' ', '')
                total_rev = float(clean_val)
                
                # RN (보통 뒤에서 5번째 열에 있음)
                rn_val = str(df_clean.iloc[-1, -5])
                clean_rn = rn_val.replace(',', '').replace('nan', '0').replace(' ', '')
                total_rn = float(clean_rn)
            except:
                total_rev = 0
                total_rn = 0

            # 3. 데이터프레임 생성 (월별 1줄 요약)
            df = pd.DataFrame([{
                'CheckIn': target_month_date.strftime('%Y-%m-%d'),
                'Room_Revenue': total_rev,
                'Total_Revenue': total_rev,
                'RN': total_rn,
                'Guest_Name': 'OTB_DATA',
                'Segment': 'OTB',
                'Account': 'OTB_Summary',
                'Room_Type': 'ROH',
                'Nat_Orig': 'KR',
                'Booking_Date': target_month_date.strftime('%Y-%m-%d'),
                'Lead_Time': 0,
                'Breakfast': 'Unknown'
            }])
            
        # ---------------------------------------------------------
        # [B] 일반 예약/취소 리스트 처리
        # ---------------------------------------------------------
        else:
            # 헤더 찾기
            header_idx = -1
            keywords = ['guest', 'name', 'check', 'date', 'room', '고객', '입실']
            for i, row in df_raw.head(20).iterrows():
                if sum(1 for k in keywords if k in str(row.values).lower()) >= 2:
                    header_idx = i; break
            
            if header_idx != -1:
                df_raw.columns = df_raw.iloc[header_idx]
                df_raw = df_raw.iloc[header_idx+1:].reset_index(drop=True)

            # 합계 행 제거
            df_raw = df_raw[~df_raw.iloc[:, 0].astype(str).str.contains('합계|Total', na=False)]
            df = normalize_and_map_columns(df_raw).copy()
            
            # 필수 컬럼 채우기
            req = ['Rooms','Nights','Room_Revenue','Total_Revenue','Guest_Name','Segment','Account','Room_Type','Nat_Orig','Lead_Time','Rate_Plan','Service_Code']
            for c in req:
                if c not in df.columns: df[c] = 0 if c in ['Rooms','Nights','Room_Revenue','Total_Revenue','Lead_Time'] else 'Unknown'
            
            for c in ['Room_Revenue','Total_Revenue','Rooms','Nights']:
                df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
            
            df['Total_Revenue'] = np.where(df['Total_Revenue']==0, df['Room_Revenue'], df['Total_Revenue'])
            df['RN'] = df['Rooms'] * df['Nights'].replace(0, 1)
            
            # [조식 식별 로직] Service_Code에 'BF'가 있으면 조식
            def check_bf(row):
                svc = str(row.get('Service_Code', '')).upper()
                if 'BF' in svc: return 'Included' # 조식 포함
                return 'Not Included' # 룸 온리
            
            df['Breakfast'] = df.apply(check_bf, axis=1)

        # 공통 마무리
        df['Status'] = status
        df['Snapshot_Date'] = datetime.now().strftime('%Y-%m-%d')
        df['CheckIn_dt'] = pd.to_datetime(df['CheckIn'], errors='coerce')
        df['Booking_dt'] = pd.to_datetime(df['Booking_Date'], errors='coerce')
        df.loc[df['Booking_dt'].isna(), 'Booking_dt'] = df.loc[df['Booking_dt'].isna(), 'CheckIn_dt']
        
        df = df.dropna(subset=['CheckIn_dt'])
        df['Stay_Month'] = df['CheckIn_dt'].dt.strftime('%Y-%m')
        df['Booking_Month'] = df['Booking_dt'].dt.strftime('%Y-%m')
        df['Day_Type'] = df['CheckIn_dt'].dt.weekday.apply(lambda x: 'Weekend' if x >= 4 else 'Weekday')
        
        def cls_nat(row):
            if re.search('[가-힣]', str(row.get('Guest_Name',''))): return 'KOR'
            if any(x in str(row.get('Nat_Orig','')).upper() for x in ['CHN','HKG']): return 'CHN'
            return 'OTH'
        df['Nat_Group'] = df.apply(cls_nat, axis=1)
        
        return clean_numeric_columns(df)
    except: return pd.DataFrame()

# ==============================================================================
# 5. UI 렌더링 헬퍼 함수 (이름 통일됨)
# ==============================================================================

def add_total_row(df, group_col_name="구분"):
    if df.empty: return df
    num = df.select_dtypes(include=[np.number]).fillna(0)
    total = num.sum().to_dict()
    row = {c: "" for c in df.columns}; row.update(total); row[grp]="TOTAL"
    if group_col_name in df.columns: row[group_col_name] = "TOTAL"
    else: row[df.columns[0]] = "TOTAL"
    
    if 'RN' in row and row['RN'] > 0:
        if 'Room_Revenue' in row: row['ADR_Room'] = row['Room_Revenue'] / row['RN']
        if 'Total_Revenue' in row: row['ADR_Total'] = row['Total_Revenue'] / row['RN']
    return pd.concat([df, pd.DataFrame([row])], ignore_index=True)

def style_df(df):
    """(구 show_dataframe_with_style)"""
    if df.empty: st.write("No Data"); return
    fmt = {c: "{:,.0f}" for c in df.select_dtypes(include=[np.number]).columns}
    st.dataframe(df.style.format(fmt).apply(lambda x: ['background-color: #fff9c4; font-weight: bold; color: black']*len(x) if str(x.iloc[0])=='TOTAL' else ['']*len(x), axis=1), hide_index=True, use_container_width=True)

def render_tab(df, key_prefix):
    t = st.tabs(["📊 세그먼트", "📅 Pacing", "🏢 거래처", "⏳ 리드타임", "🛏️ 객실타입", "🗓️ 요일", "🌐 국적", "🍳 조식"])
    
    with t[0]:
        s = df.groupby('Segment').agg({'RN':'sum','Room_Revenue':'sum','Total_Revenue':'sum'}).reset_index()
        s['ADR_Room'] = np.where(s['RN']>0, s['Room_Revenue']/s['RN'], 0)
        c1,c2=st.columns(2)
        c1.plotly_chart(px.pie(s, values='Room_Revenue', names='Segment'), use_container_width=True, key=f"{key_prefix}_pie")
        c2.plotly_chart(px.bar(s, x='Segment', y='Room_Revenue'), use_container_width=True, key=f"{key_prefix}_bar")
        style_df(add_total_row(s, 'Segment'))
    with t[1]:
        p = df.pivot_table(index='Booking_Month', columns='Stay_Month', values='RN', aggfunc='sum').fillna(0)
        st.plotly_chart(px.imshow(p, text_auto="d", aspect="auto"), use_container_width=True, key=f"{key_prefix}_pacing")
    with t[2]:
        a = df.groupby('Account').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index().sort_values('RN', ascending=False).head(50)
        style_df(add_total_row(a, 'Account'))
    with t[3]:
        df['LG'] = pd.cut(df['Lead_Time'], [-1,0,3,7,14,30,60,90,999], labels=['0','1-3','4-7','8-14','15-30','31-60','61-90','90+'])
        l = df.groupby('LG').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index()
        st.plotly_chart(px.bar(l, x='LG', y='RN'), use_container_width=True, key=f"{key_prefix}_lead")
        style_df(add_total_row(l, 'LG'))
    with t[4]:
        r = df.groupby('Room_Type').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index()
        style_df(add_total_row(r, 'Room_Type'))
    with t[5]:
        w = df.groupby('Day_Type').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index()
        c1,c2=st.columns(2)
        c1.plotly_chart(px.bar(w, x='Day_Type', y='Room_Revenue'), use_container_width=True, key=f"{key_prefix}_day_bar")
        c2.plotly_chart(px.pie(w, values='RN', names='Day_Type'), use_container_width=True, key=f"{key_prefix}_day_pie")
        style_df(add_total_row(w, 'Day_Type'))
    with t[6]:
        n = df.groupby('Nat_Group').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index()
        c1,c2=st.columns(2)
        c1.plotly_chart(px.pie(n, values='RN', names='Nat_Group'), use_container_width=True, key=f"{key_prefix}_nat_pie")
        c2.plotly_chart(px.bar(n, x='Nat_Group', y='Room_Revenue'), use_container_width=True, key=f"{key_prefix}_nat_bar")
        style_df(add_total_row(n, 'Nat_Group'))
    with t[7]:
        if 'Breakfast' in df.columns:
            b = df.groupby('Breakfast').agg({'RN':'sum', 'Room_Revenue':'sum'}).reset_index()
            c1, c2 = st.columns(2)
            c1.plotly_chart(px.pie(b, values='RN', names='Breakfast', title='객실수 비중'), use_container_width=True, key=f"{key_prefix}_bf_pie")
            c2.plotly_chart(px.bar(b, x='Breakfast', y='Room_Revenue', title='매출 비중'), use_container_width=True, key=f"{key_prefix}_bf_bar")
            style_df(add_total_row(b, 'Breakfast'))
        else: st.info("조식 데이터 없음")

# ==============================================================================
# 6. 메인 실행부
# ==============================================================================
try:
    st.title("🏛️ 앰버 호텔 경영 리포트 (Final Integrity)")
    
    raw = load_data_from_firestore()
    df_all = pd.DataFrame(raw) if raw else pd.DataFrame()
    dates = sorted(df_all['Snapshot_Date'].unique(), reverse=True) if not df_all.empty else []

    with st.sidebar:
        st.header("📅 설정")
        if st.button("🗑️ OTB 데이터만 초기화"):
            cnt = delete_otb_data_only()
            st.warning(f"OTB 데이터 {cnt}건 삭제. 다시 업로드하세요."); time.sleep(1); st.cache_data.clear(); st.rerun()
        
        sel_date = st.selectbox("기준일", dates, index=0) if dates else None
        
        st.markdown("---")
        with st.expander("파일 업로드", expanded=True):
            f1=st.file_uploader("예약 리스트", type=['csv','xlsx'])
            if f1 and st.button("예약 저장"):
                if save_to_firestore(process_data(f1, "Booked")): st.cache_data.clear(); st.rerun()
            f2=st.file_uploader("취소 리스트", type=['csv','xlsx'])
            if f2 and st.button("취소 저장"):
                if save_to_firestore(process_data(f2, "Cancelled")): st.cache_data.clear(); st.rerun()
            
            # [수정] 12개월 OTB 통합 저장
            f3=st.file_uploader("OTB (12개월 통합)", type=['csv','xlsx'], accept_multiple_files=True)
            if f3 and st.button("OTB 저장"):
                otb_list = []
                for f in f3: 
                    # force_otb=True로 강제 지정
                    otb_list.append(process_data(f, "Booked", force_otb=True))
                if otb_list:
                    combined = pd.concat(otb_list, ignore_index=True)
                    if save_to_firestore(combined): 
                        st.success("12개월 통합 저장 완료!"); time.sleep(1); st.cache_data.clear(); st.rerun()

    if sel_date and not df_all.empty:
        df = clean_numeric_columns(df_all[df_all['Snapshot_Date'] == sel_date].copy())
        
        if df.empty: st.warning("데이터 없음")
        else:
            df['CheckIn_dt'] = pd.to_datetime(df['CheckIn'], errors='coerce')
            df['Stay_Month'] = df['CheckIn_dt'].dt.strftime('%Y-%m')
            
            df_otb = df[df['Segment'] == 'OTB']
            df_act = df[df['Segment'] != 'OTB']
            
            df_bk = df_act[(df_act['Status']=='Booked') & (df_act['Total_Revenue']>0)]
            df_cn = df_act[df_act['Status']=='Cancelled']
            df_tot = pd.concat([df_bk, df_cn])

            tabs = st.tabs(["👑 GM 요약", "✅ 예약 상세", "❌ 취소 상세", "📈 종합 합계", "🆓 0원 예약", "🎯 OTB 현황"])

            with tabs[0]:
                st.header(f"👑 GM 요약 ({sel_date})")
                bk_r = df_bk['Room_Revenue'].sum(); bk_t = df_bk['Total_Revenue'].sum(); bk_rn = df_bk['RN'].sum()
                cn_r = df_cn['Room_Revenue'].sum(); cn_t = df_cn['Total_Revenue'].sum(); cn_rn = df_cn['RN'].sum()
                
                st.markdown("#### ✅ 예약")
                c = st.columns(6)
                c[0].metric("건수", f"{len(df_bk):,.0f}"); c[1].metric("RN", f"{bk_rn:,.0f}")
                c[2].metric("객실매출", f"{bk_r:,.0f}"); c[3].metric("총매출", f"{bk_t:,.0f}")
                c[4].metric("객실ADR", f"{bk_r/bk_rn if bk_rn>0 else 0:,.0f}"); c[5].metric("총ADR", f"{bk_t/bk_rn if bk_rn>0 else 0:,.0f}")
                
                st.markdown("#### ❌ 취소")
                c = st.columns(6)
                c[0].metric("건수", f"{len(df_cn):,.0f}"); c[1].metric("RN", f"{cn_rn:,.0f}")
                c[2].metric("객실매출", f"{cn_r:,.0f}"); c[3].metric("총매출", f"{cn_t:,.0f}")
                c[4].metric("객실ADR", f"{cn_r/cn_rn if cn_rn>0 else 0:,.0f}"); c[5].metric("총ADR", f"{cn_t/cn_rn if cn_rn>0 else 0:,.0f}")
                
                st.divider()
                s = df_bk.groupby('Segment').agg({'RN':'sum','Room_Revenue':'sum'}).reset_index()
                style_df(add_total_row(s, 'Segment'))

                c1, c2 = st.columns(2)
                with c1:
                    if 'Nat_Group' in df_bk.columns: st.plotly_chart(px.pie(df_bk.groupby('Nat_Group')['RN'].sum().reset_index(), values='RN', names='Nat_Group', title="국적"), use_container_width=True, key="gm_pie")
                with c2:
                    m = pd.concat([df_bk.assign(Type='예약'), df_cn.assign(Type='취소')]).groupby(['Stay_Month','Type'])['RN'].sum().reset_index()
                    if not m.empty: st.plotly_chart(px.bar(m, x='Stay_Month', y='RN', color='Type', barmode='group', title="월별 추이"), use_container_width=True, key="gm_bar")

            with tabs[1]: render_tab(df_bk, "bk")
            with tabs[2]: render_tab(df_cn, "cn")
            with tabs[3]: render_tab(df_tot, "tot")
            with tabs[4]: 
                z = df_act[(df_act['Status']=='Booked')&(df_act['Total_Revenue']<=0)]
                st.subheader(f"🆓 0원 예약 ({len(z)}건)")
                st.dataframe(z[['Guest_Name','CheckIn','Account','Room_Type']], use_container_width=True)

            with tabs[5]:
                st.header("🎯 OTB 현황 (Budget vs OTB)")
                if df_otb.empty: st.warning("⚠️ OTB 데이터 없음")
                else:
                    base = df_otb.copy()
                    base['M'] = base['CheckIn_dt'].dt.month
                    all_m = pd.DataFrame({'M': range(1, 13)})
                    grp = base.groupby('M').agg({'Room_Revenue':'sum'}).reset_index()
                    fin = pd.merge(all_m, grp, on='M', how='left').fillna(0)
                    
                    fin['Budget'] = fin['M'].map(BUDGET_DATA).fillna(0)
                    fin['OTB'] = fin['Room_Revenue']
                    fin['Rate'] = np.where(fin['Budget'] > 0, (fin['OTB'] / fin['Budget']) * 100, 0)
                    fin['Name'] = fin['M'].astype(str) + "월"
                    
                    tb = fin['Budget'].sum(); to = fin['OTB'].sum(); tr = (to / tb * 100) if tb > 0 else 0
                    
                    fig = go.Figure()
                    fig.add_trace(go.Bar(x=fin['Name'], y=fin['OTB'], name='OTB', marker_color='#2E86C1', 
                                         text=fin['Rate'].apply(lambda x: f"{x:.1f}%"), textposition='outside'))
                    fig.add_trace(go.Scatter(x=fin['Name'], y=fin['Budget'], name='Budget', line=dict(color='red', dash='dot')))
                    fig.update_layout(height=500, margin=dict(t=50))
                    st.plotly_chart(fig, use_container_width=True, key="otb_chart")
                    
                    res_dict = {}
                    for _, r in fin.iterrows(): res_dict[r['Name']] = [f"{r['Budget']:,.0f}", f"{r['OTB']:,.0f}", f"{r['Rate']:.1f}%"]
                    res_dict['합계'] = [f"{tb:,.0f}", f"{to:,.0f}", f"{tr:.1f}%"]
                    tbl = pd.DataFrame(res_dict, index=['Budget','OTB','달성률'])
                    st.dataframe(tbl.style.apply(lambda x: ['background-color:#fff9c4; font-weight:bold; border-left:2px solid black']*len(x) if x.name=='합계' else ['']*len(x), axis=0), use_container_width=True)

    else: st.info("👈 파일 업로드 필요")
except Exception as e: st.error(f"오류: {e}")
