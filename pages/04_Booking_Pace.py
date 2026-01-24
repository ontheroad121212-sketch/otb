import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore
import time
import os

# -----------------------------------------------------------------------------
# 1. Firebase 접속 및 초기 설정
# -----------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Amber Pure Hill Strategy Dashboard", page_icon="🏨")

def init_firebase_direct():
    if not firebase_admin._apps:
        try:
            key_dict = dict(st.secrets["firebase"])
            cred = credentials.Certificate(key_dict)
            firebase_admin.initialize_app(cred)
        except Exception as e:
            try:
                cred = credentials.Certificate("serviceAccountKey.json")
                firebase_admin.initialize_app(cred)
            except: return None, str(e)
    return firestore.client(), "연결됨 ✅"

db, db_status = init_firebase_direct()

# -----------------------------------------------------------------------------
# 2. 데이터 고속 로딩(Parquet) 및 관리 로직
# -----------------------------------------------------------------------------
CACHE_FILE = "local_booking_cache.parquet"

def upload_to_firestore(df_new):
    if db is None: return
    df_new = df_new.copy()
    upload_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    df_new['Snapshot'] = upload_time
    df_new['입실일자'] = pd.to_datetime(df_new['입실일자'], errors='coerce')
    df_new['예약일자'] = pd.to_datetime(df_new['예약일자'], errors='coerce')
    df_new['예약번호'] = df_new['예약번호'].astype(str)
    df_upload = df_new.where(pd.notnull(df_new), None)
    
    total = len(df_upload)
    batch = db.batch()
    count = 0
    bar = st.progress(0); msg = st.empty()
    
    for _, row in df_upload.iterrows():
        doc_id = row['예약번호']
        if not doc_id or doc_id == 'None': continue
        doc_ref = db.collection('hotel_bookings').document(doc_id)
        payload = {k: (None if pd.isna(v) else v) for k, v in row.to_dict().items()}
        batch.set(doc_ref, payload, merge=True)
        count += 1
        if count % 200 == 0:
            batch.commit(); batch = db.batch()
            bar.progress(count / total); msg.text(f"⏳ 업로드 중... ({count}/{total})")
    batch.commit()
    bar.empty(); msg.success(f"✅ {total}건 업데이트 완료! (버전: {upload_time})")
    if os.path.exists(CACHE_FILE): os.remove(CACHE_FILE)
    st.cache_data.clear()

def delete_all_data():
    if db is None: return
    coll_ref = db.collection('hotel_bookings')
    batch_size = 200
    total_del = 0
    while True:
        docs = list(coll_ref.limit(batch_size).stream())
        if not docs: break
        batch = db.batch()
        for doc in docs: batch.delete(doc.reference)
        batch.commit()
        total_del += len(docs)
        st.toast(f"🗑️ {total_del}건 삭제 중...")
    if os.path.exists(CACHE_FILE): os.remove(CACHE_FILE)
    st.cache_data.clear()
    return total_del

@st.cache_data(ttl=3600)
def load_data_with_snapshot_cache():
    if os.path.exists(CACHE_FILE):
        try: return pd.read_parquet(CACHE_FILE), "로컬 캐시 (고속)"
        except: pass
    if db is None: return pd.DataFrame(), "연결 안됨"
    try:
        docs = db.collection('hotel_bookings').limit(100000).stream() 
        data = [doc.to_dict() for doc in docs]
        if not data: return pd.DataFrame(), "데이터 없음"
        df = pd.DataFrame(data)
        for col in ['입실일자', '예약일자']:
            df[col] = pd.to_datetime(df[col], errors='coerce').dt.tz_localize(None)
        df = df.dropna(subset=['입실일자', '예약일자'])
        df['LeadTime'] = (df['입실일자'] - df['예약일자']).dt.days
        df['Year'] = df['입실일자'].dt.year
        df['Month'] = df['입실일자'].dt.month
        df['Week'] = df['입실일자'].dt.isocalendar().week
        df['DayOfWeek'] = df['입실일자'].dt.day_name()
        if 'Snapshot' not in df.columns: df['Snapshot'] = "이전 데이터"
        df.to_parquet(CACHE_FILE)
        return df, "Firestore (실시간)"
    except: return pd.DataFrame(), "조회 에러"

# -----------------------------------------------------------------------------
# 3. 사이드바 관리
# -----------------------------------------------------------------------------
df_raw, load_source = load_data_with_snapshot_cache()

with st.sidebar:
    st.title("⚙️ 시스템 관리")
    st.write(f"**DB 상태:** {db_status}")
    st.caption(f"로드 소스: {load_source}")
    
    with st.expander("📤 데이터 업로드", expanded=True):
        up_files = st.file_uploader("파일 선택", accept_multiple_files=True)
        if up_files and st.button("🚀 DB 업데이트 시작"):
            all_dfs = [pd.read_csv(f, header=2) if f.name.endswith('.csv') else pd.read_excel(f, header=2) for f in up_files]
            if all_dfs:
                upload_to_firestore(pd.concat(all_dfs, ignore_index=True))
                st.rerun()

    with st.expander("⚠️ 데이터 초기화"):
        if st.button("🗑️ 전체 삭제") and st.text_input("확인 ('초기화')") == "초기화":
            delete_all_data(); st.rerun()

    st.divider()
    snapshot_options = sorted(df_raw['Snapshot'].unique(), reverse=True) if not df_raw.empty else []
    selected_snapshot = st.selectbox("조회할 데이터 버전", snapshot_options)
    df = df_raw[df_raw['Snapshot'] == selected_snapshot] if selected_snapshot else df_raw

    st.markdown("**🚫 필터 설정**")
    cancel_k = ['취소', 'CXL', 'CANCEL', 'NO', 'NOSHOW', 'RC', 'RX']
    all_sts = df['상태'].unique().astype(str) if '상태' in df.columns else []
    def_exc = [s for s in all_sts if any(x in s.upper() for x in cancel_k)]
    exc_sts = st.multiselect("분석 제외 상태", options=all_sts, default=def_exc)
    df_clean = df[~df['상태'].isin(exc_sts)] if '상태' in df.columns else df

# -----------------------------------------------------------------------------
# 4. 메인 화면 및 기간 선택 (원본 유지)
# -----------------------------------------------------------------------------
if df_clean.empty:
    st.title("🏨 Hotel Strategy Dashboard")
    st.info("데이터를 업로드해주세요."); st.stop()

st.title("🏨 Hotel Strategy Dashboard")
col_kpi1, col_kpi2, col_kpi3 = st.columns(3)
with col_kpi1: st.metric("분석 대상 예약", f"{len(df_clean):,} 건")
with col_kpi2: st.metric("데이터 시작일", str(df_clean['입실일자'].min().date()))
with col_kpi3: st.metric("데이터 종료일", str(df_clean['입실일자'].max().date()))

c1, c2 = st.columns([1, 2])
with c1: view_mode = st.radio("📊 분석 단위", ["월별", "분기별", "주별", "연간"], horizontal=True)
with c2:
    all_acc = sorted(df_clean['거래처'].unique())
    sel_acc = st.multiselect("🏦 거래처 필터", all_acc)
df_view = df_clean[df_clean['거래처'].isin(sel_acc)] if sel_acc else df_clean

years_list = sorted(df_view['Year'].unique(), reverse=True)
year_options = ["전체"] + [str(y) for y in years_list]
col_p1, col_p2 = st.columns(2)
target_df, ref_df = pd.DataFrame(), pd.DataFrame()
q_map = {"1분기": [1,2,3], "2분기": [4,5,6], "3분기": [7,8,9], "4분기": [10,11,12]}

if view_mode == "월별":
    with col_p1: ty = st.selectbox("Target 연도", year_options, index=1); tm = st.selectbox("Target 월", range(1,13))
    with col_p2: ry = st.selectbox("Ref 연도", year_options, index=1); rm = st.selectbox("Ref 월", range(1,13), index=tm-1)
    target_df = df_view[df_view['Month']==tm] if ty=="전체" else df_view[(df_view['Year']==int(ty)) & (df_view['Month']==tm)]
    ref_df = df_view[df_view['Month']==rm] if ry=="전체" else df_view[(df_view['Year']==int(ry)) & (df_view['Month']==rm)]
elif view_mode == "분기별":
    qs = list(q_map.keys())
    with col_p1: ty = st.selectbox("Target 연도", year_options, index=1); tq = st.selectbox("Target 분기", qs)
    with col_p2: ry = st.selectbox("Ref 연도", year_options, index=1); rq = st.selectbox("Ref 분기", qs, index=qs.index(tq))
    target_df = df_view[df_view['Month'].isin(q_map[tq])] if ty=="전체" else df_view[(df_view['Year']==int(ty)) & (df_view['Month'].isin(q_map[tq]))]
    ref_df = df_view[df_view['Month'].isin(q_map[rq])] if ry=="전체" else df_view[(df_view['Year']==int(ry)) & (df_view['Month'].isin(q_map[rq]))]
elif view_mode == "주별":
    with col_p1: 
        ty = st.selectbox("Target 연도", year_options, index=1)
        avail_w = sorted(df_view['Week'].unique()) if ty=="전체" else sorted(df_view[df_view['Year']==int(ty)]['Week'].unique())
        tw = st.selectbox("Target 주차", avail_w if avail_w else [1])
    with col_p2: ry = st.selectbox("Ref 연도", year_options, index=1); rw = st.selectbox("Ref 주차", range(1,54), index=int(min(tw-1, 52)))
    target_df = df_view[df_view['Week']==tw] if ty=="전체" else df_view[(df_view['Year']==int(ty)) & (df_view['Week']==tw)]
    ref_df = df_view[df_view['Week']==rw] if ry=="전체" else df_view[(df_view['Year']==int(ry)) & (df_view['Week']==rw)]
else: # 연간
    with col_p1: ty = st.selectbox("Target 연도", year_options, index=0)
    with col_p2: ry = st.selectbox("Ref 연도", year_options, index=1 if len(year_options)>1 else 0)
    target_df = df_view if ty=="전체" else df_view[df_view['Year']==int(ty)]
    ref_df = df_view if ry=="전체" else df_view[df_view['Year']==int(ry)]

if target_df.empty: st.warning("데이터가 없습니다."); st.stop()

# -----------------------------------------------------------------------------
# 5. 시각화 탭 (무삭제 통합)
# -----------------------------------------------------------------------------
tabs = st.tabs(["💰 매출", "💳 ADR", "⏳ 리드타임", "📅 요일", "🌏 국적/객실", "🔁 로열티", "🚀 RM 분석", "🎯 수익 전략"])

with tabs[0]: # Revenue
    st.subheader(f"매출 페이스")
    def get_pace(d):
        if d.empty: return pd.Series(dtype=float)
        return d.groupby('LeadTime')['총금액'].sum().sort_index(ascending=False).cumsum().sort_index()
    pt, pr = get_pace(target_df), get_pace(ref_df)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=pt.index, y=pt.values, name='Target', line=dict(color='#0052cc', width=3)))
    if not pr.empty: fig.add_trace(go.Scatter(x=pr.index, y=pr.values, name='Ref', line=dict(color='gray', dash='dot')))
    fig.update_layout(xaxis={'autorange': 'reversed'}, xaxis_title="D-Day", yaxis_title="누적 매출", height=500)
    st.plotly_chart(fig, use_container_width=True)

with tabs[1]: # ADR
    st.subheader(f"ADR 추이")
    def get_adr(d):
        if d.empty: return pd.Series(dtype=float)
        rev = d.groupby('LeadTime')['총금액'].sum().sort_index(ascending=False).cumsum().sort_index()
        rms = d.groupby('LeadTime')['객실수'].sum().sort_index(ascending=False).cumsum().sort_index()
        return (rev/rms).fillna(0)
    at, ar = get_adr(target_df), get_adr(ref_df)
    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(x=at.index, y=at.values, name='Target ADR', line=dict(color='#ff6b6b', width=3)))
    if not ar.empty: fig2.add_trace(go.Scatter(x=ar.index, y=ar.values, name='Ref ADR', line=dict(color='gray', dash='dot')))
    fig2.update_layout(xaxis={'autorange': 'reversed'}, height=500)
    st.plotly_chart(fig2, use_container_width=True)

with tabs[2]: # Lead Time
    st.subheader("예약 리드타임 분포")
    bins = [-1, 0, 3, 7, 14, 30, 60, 90, 999]
    labels = ['당일', '1-3일', '4-7일', '8-14일', '15-30일', '31-60일', '61-90일', '90일+']
    t_c, r_c = target_df.copy(), ref_df.copy()
    t_c['Group'] = pd.cut(t_c['LeadTime'], bins=bins, labels=labels)
    r_c['Group'] = pd.cut(r_c['LeadTime'], bins=bins, labels=labels)
    tg = t_c.groupby('Group')['총금액'].sum().reset_index().assign(Type='Target')
    rg = r_c.groupby('Group')['총금액'].sum().reset_index().assign(Type='Ref')
    fig3 = px.bar(pd.concat([tg, rg]), x='Group', y='총금액', color='Type', barmode='group', color_discrete_map={'Target':'#0052cc','Ref':'#bababa'})
    st.plotly_chart(fig3, use_container_width=True)

with tabs[3]: # Day of Week
    st.subheader("요일별 매출")
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    td = target_df.groupby('DayOfWeek')['총금액'].mean().reindex(days).reset_index()
    rd = ref_df.groupby('DayOfWeek')['총금액'].mean().reindex(days).reset_index()
    fig4 = go.Figure()
    fig4.add_trace(go.Scatter(x=td['DayOfWeek'], y=td['총금액'], name='Target', line=dict(color='green', width=3)))
    fig4.add_trace(go.Scatter(x=rd['DayOfWeek'], y=rd['총금액'], name='Ref', line=dict(color='gray', dash='dot')))
    st.plotly_chart(fig4, use_container_width=True)

with tabs[4]: # Demographics
    st.subheader("국적 및 객실 분석")
    c1, c2 = st.columns(2)
    with c1:
        nd = target_df.groupby('국적')['총금액'].sum().reset_index().sort_values('총금액', ascending=False)
        st.plotly_chart(px.pie(nd.head(7), values='총금액', names='국적', hole=0.4, title="Target 국적"), use_container_width=True)
    with c2:
        rt_t = target_df.groupby('객실타입')['총금액'].sum().reset_index().assign(Type='Target')
        rt_r = ref_df.groupby('객실타입')['총금액'].sum().reset_index().assign(Type='Ref')
        top = rt_t.sort_values('총금액', ascending=False).head(10)['객실타입']
        st.plotly_chart(px.bar(pd.concat([rt_t, rt_r])[pd.concat([rt_t, rt_r])['객실타입'].isin(top)], x='객실타입', y='총금액', color='Type', barmode='group'), use_container_width=True)

with tabs[5]: # Loyalty (사장님 원본 그대로)
    st.header("🔁 고객 로열티 & N차 방문 분석")
    name_cols = ['고객명', '예약자', '성함', '고객성함', 'Guest Name', 'Name', '예약자명', '한글성명', '고객']
    f_n = next((c for c in name_cols if c in df_clean.columns), None)
    if not f_n: st.warning("고객명 컬럼 없음")
    else:
        exclude_n = ['허성문', '이민우', 'WANG ZHANJUN']
        df_l = df_clean.copy()
        df_l = df_l[~df_l[f_n].astype(str).str.contains('|'.join(exclude_n), na=False)]
        df_l['GuestKey'] = df_l[f_n].astype(str)
        g_stats = df_l.groupby('GuestKey').agg({'예약번호':'count','총금액':'sum','객실수':'sum'}).reset_index()
        g_stats.columns = ['GuestKey','TotalVisits','TotalRev','TotalRooms']
        def segment(n):
            if n==1: return "1회 (신규)"
            elif n==2: return "2회 (리피터)"
            elif n>=3: return "3회 이상 (VIP)"
            else: return "N/A"
        g_stats['Grade'] = g_stats['TotalVisits'].apply(segment)
        t_f = target_df[~target_df[f_n].astype(str).str.contains('|'.join(exclude_n), na=False)]
        t_l = pd.merge(df_l[df_l['예약번호'].isin(t_f['예약번호'])], g_stats[['GuestKey','TotalVisits','Grade']], on='GuestKey', how='left')
        m1, m2, m3 = st.columns(3)
        u_g = t_l['GuestKey'].nunique(); r_g = t_l[t_l['TotalVisits']>1]['GuestKey'].nunique()
        m1.metric("분석 고객", f"{u_g:,}명"); m2.metric("재방문 고객", f"{r_g:,}명"); m3.metric("재방문율", f"{(r_g/u_g*100) if u_g>0 else 0:.1f}%")
        st.plotly_chart(px.bar(t_l['Grade'].value_counts().reset_index(), x='index', y='Grade', title="고객 등급 분포"), use_container_width=True)

with tabs[6]: # RM 정밀 분석 (핀셋 필터 포함)
    st.header("🚀 수익 관리(RM) 기간별 정밀 분석")
    rm_mode = st.radio("분석 기준", ["입실일자 기준 (Occupancy)", "예약일자 기준 (Production)"], horizontal=True)
    date_col = '입실일자' if "입실일자" in rm_mode else '예약일자'
    rm_c1, rm_c2 = st.columns(2)
    with rm_c1: d_a = st.date_input("기준 기간 (Period A)", [datetime(2025,1,1), datetime(2025,1,31)], key="da_rm")
    with rm_c2: d_b = st.date_input("비교 기간 (Period B)", [datetime(2026,1,1), datetime(2026,1,24)], key="db_rm")
    df_a = df_raw[(df_raw[date_col].dt.date >= d_a[0]) & (df_raw[date_col].dt.date <= d_a[1])].copy()
    df_b = df_raw[(df_raw[date_col].dt.date >= d_b[0]) & (df_raw[date_col].dt.date <= d_b[1])].copy()
    if not df_a.empty and not df_b.empty:
        rm_sub = st.tabs(["📊 KPI", "📈 Pace", "📉 Wash-out", "⏳ 패턴"])
        with rm_sub[0]: # KPI 요약
            rev_a, rms_a = df_a['총금액'].sum(), df_a['객실수'].sum()
            rev_b, rms_b = df_b['총금액'].sum(), df_b['객실수'].sum()
            k1, k2, k3 = st.columns(3)
            k1.metric("매출", f"{rev_b/10000:,.0f}만", f"{(rev_b-rev_a)/10000:,.0f}만")
            k2.metric("객실수", f"{rms_b:,}실", f"{rms_b-rms_a:,}실")
            k3.metric("ADR", f"{rev_b/rms_b:,.0f}원", f"{(rev_b/rms_b)-(rev_a/rms_a):,.0f}원")
        with rm_sub[1]: # Pace
            pace_a = df_a.groupby(date_col)['객실수'].sum().sort_index().cumsum()
            pace_b = df_b.groupby(date_col)['객실수'].sum().sort_index().cumsum()
            st.plotly_chart(go.Figure(data=[go.Scatter(y=pace_a.values, name="A"), go.Scatter(y=pace_b.values, name="B")]), use_container_width=True)
        with rm_sub[2]: # Wash-out
            df_b['is_cancel'] = df_b['상태'].isin(def_exc)
            cxl = df_b.groupby('거래처')['is_cancel'].mean() * 100
            st.plotly_chart(px.bar(cxl.reset_index(), x='거래처', y='is_cancel', title="취소율(%)"), use_container_width=True)

with tabs[7]: # 수익 전략 (Golden ADR, 국적 프로파일, 취소 방어막)
    st.header("🎯 수익 극대화 전략")
    st_tabs = st.tabs(["💰 황금 ADR", "🌍 국적 분석", "🛡️ 취소 예측"])
    with st_tabs[0]:
        df_day = df_clean.groupby('입실일자').agg({'총금액':'sum','객실수':'sum'}).reset_index()
        df_day['ADR'] = df_day['총금액']/df_day['객실수']
        st.plotly_chart(px.scatter(df_day, x='ADR', y='총금액', size='객실수', title="ADR 대비 매출 상관성"), use_container_width=True)
    with st_tabs[1]:
        nat_p = df_clean.groupby('국적').agg({'총금액':'mean','LeadTime':'mean','객실수':'sum'}).reset_index()
        st.plotly_chart(px.scatter(nat_p, x='LeadTime', y='총금액', size='객실수', text='국적', title="국적별 우량도"), use_container_width=True)
    with st_tabs[2]:
        df_raw['is_cxl'] = df_raw['상태'].isin(def_exc)
        cxl_rate = df_raw['is_cxl'].mean()
        st.metric("현재 OTB 실제 투숙 예측", f"{int(target_df['객실수'].sum()*(1-cxl_rate))}실", f"취소예측: {int(target_df['객실수'].sum()*cxl_rate)}실")

# -----------------------------------------------------------------------------
# 6. 포캐스팅 시스템 연동 (세션 동기화)
# -----------------------------------------------------------------------------
try:
    df_raw['dow'] = df_raw['예약일자'].dt.dayofweek
    st.session_state["historical_dow"] = (df_raw['dow'].value_counts(normalize=True)*7).to_dict()
    st.session_state["repeat_rate"] = (df_raw[f_n].value_counts()>1).mean()*100 if f_n else 0
    save_m = df_clean['입실일자'].iloc[0].month if not df_clean.empty else datetime.now().month
    st.session_state[f"sob_{save_m}"] = len(df_clean)
    st.toast("✅ 포캐스팅 데이터 동기화 완료")
except: pass

st.divider()
with st.expander("🕵️ Raw Data 확인"): st.dataframe(df_view.head(50))
