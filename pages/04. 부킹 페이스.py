import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore
import time

# -----------------------------------------------------------------------------
# 1. Firebase 접속 (가장 안정적인 방식)
# -----------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Hotel Strategy Dashboard", page_icon="🏨")

# 캐시 없이 우선 접속 시도 (진단을 위해)
def init_firebase_direct():
    if not firebase_admin._apps:
        try:
            # 1순위: Streamlit Secrets
            key_dict = dict(st.secrets["firebase"])
            cred = credentials.Certificate(key_dict)
            firebase_admin.initialize_app(cred)
        except Exception as e:
            try:
                # 2순위: 로컬 파일
                cred = credentials.Certificate("serviceAccountKey.json")
                firebase_admin.initialize_app(cred)
            except:
                return None, str(e)
    return firestore.client(), "연결됨 ✅"

db, db_status = init_firebase_direct()

# -----------------------------------------------------------------------------
# 2. 데이터 업로드/삭제 함수
# -----------------------------------------------------------------------------
def upload_to_firestore(df_new):
    if db is None: return
    df_new = df_new.copy()
    
    # 필수 전처리
    df_new['입실일자'] = pd.to_datetime(df_new['입실일자'], errors='coerce')
    df_new['예약일자'] = pd.to_datetime(df_new['예약일자'], errors='coerce')
    df_new['예약번호'] = df_new['예약번호'].astype(str)
    
    # NaN/NaT 제거 (None으로 변환)
    df_upload = df_new.where(pd.notnull(df_new), None)
    
    total = len(df_upload)
    batch = db.batch()
    count = 0
    
    bar = st.progress(0)
    msg = st.empty()
    
    for _, row in df_upload.iterrows():
        doc_id = row['예약번호']
        if not doc_id or doc_id == 'None': continue
        
        doc_ref = db.collection('hotel_bookings').document(doc_id)
        # 딕셔너리 내부의 모든 불필요한 객체 정제
        payload = {k: (None if pd.isna(v) else v) for k, v in row.to_dict().items()}
        
        batch.set(doc_ref, payload, merge=True)
        count += 1
        
        if count % 200 == 0:
            batch.commit()
            batch = db.batch()
            bar.progress(count / total)
            msg.text(f"⏳ 업로드 중... ({count}/{total})")
            time.sleep(0.1)
            
    batch.commit()
    bar.empty()
    msg.success(f"✅ {total}건 업데이트 완료!")
    st.cache_data.clear() # 조회 캐시 삭제

def delete_all_data():
    if db is None: return
    coll_ref = db.collection('hotel_bookings')
    batch_size = 200
    total_del = 0
    
    while True:
        docs = list(coll_ref.limit(batch_size).stream())
        if not docs: break
        
        batch = db.batch()
        for doc in docs:
            batch.delete(doc.reference)
        batch.commit()
        total_del += len(docs)
        st.toast(f"🗑️ {total_del}건 삭제 중...")
        time.sleep(0.2)
    return total_del

# -----------------------------------------------------------------------------
# 3. 데이터 조회 (에러 방어막 강화)
# -----------------------------------------------------------------------------
@st.cache_data(ttl=300) # 5분 캐시
def load_from_firestore():
    if db is None: return pd.DataFrame()
    try:
        docs = db.collection('hotel_bookings').limit(50000).stream() # 일단 5만건 제한
        data = [doc.to_dict() for doc in docs]
        if not data: return pd.DataFrame()
        
        df = pd.DataFrame(data)
        df['입실일자'] = pd.to_datetime(df['입실일자'], errors='coerce')
        df['예약일자'] = pd.to_datetime(df['예약일자'], errors='coerce')
        df = df.dropna(subset=['입실일자', '예약일자'])
        
        if df.empty: return pd.DataFrame()
        
        df['입실일자'] = df['입실일자'].dt.tz_localize(None)
        df['예약일자'] = df['예약일자'].dt.tz_localize(None)
        df['LeadTime'] = (df['입실일자'] - df['예약일자']).dt.days
        df['Year'] = df['입실일자'].dt.isocalendar().year.fillna(0).astype(int)
        df['Month'] = df['입실일자'].dt.month.fillna(0).astype(int)
        df['Week'] = df['입실일자'].dt.isocalendar().week.fillna(0).astype(int)
        df['DayOfWeek'] = df['입실일자'].dt.day_name()
        return df
    except:
        return pd.DataFrame()

# -----------------------------------------------------------------------------
# 4. 사이드바 (Admin & Diagnosis)
# -----------------------------------------------------------------------------
with st.sidebar:
    st.title("⚙️ 시스템 관리")
    st.write(f"**DB 상태:** {db_status}")
    
    if db is None:
        st.error("❌ Firebase 연결 실패! Secrets 설정을 확인하세요.")
        st.stop()

    # 업로드 버튼
    with st.expander("📤 데이터 업로드", expanded=True):
        up_files = st.file_uploader("엑셀/CSV 파일", accept_multiple_files=True)
        if up_files:
            if st.button("🚀 DB 업데이트 시작", key="btn_upload"):
                all_df = []
                for f in up_files:
                    try:
                        tmp = pd.read_csv(f, header=2) if f.name.endswith('.csv') else pd.read_excel(f, header=2)
                        all_df.append(tmp)
                    except: pass
                if all_df:
                    upload_to_firestore(pd.concat(all_df))
                    st.rerun()

    # 초기화 버튼
    st.divider()
    with st.expander("⚠️ 데이터 초기화"):
        pw = st.text_input("확인 메시지 ('초기화' 입력)")
        if st.button("🗑️ 전체 데이터 삭제", key="btn_delete"):
            if pw == "초기화":
                with st.spinner("삭제 중..."):
                    num = delete_all_data()
                    st.cache_data.clear()
                    st.success(f"{num}건 삭제 완료!")
                    st.rerun()
            else:
                st.error("입력값이 틀렸습니다.")

# -----------------------------------------------------------------------------
# 5. 메인 화면
# -----------------------------------------------------------------------------
df = load_from_firestore()

if df.empty:
    st.title("🏨 Hotel Dashboard")
    st.info("표시할 데이터가 없습니다. 사이드바에서 데이터를 업로드해주세요.")
else:
    # (기존 그래프 및 분석 탭 코드... 이하 생략)
    st.title("🏨 Hotel Strategy Dashboard")
    st.write(f"현재 로드된 데이터: {len(df):,}건")

# 상태 필터
with st.sidebar:
    st.divider()
    st.markdown("**🚫 필터 설정**")
    all_sts = df['상태'].unique().astype(str)
    cancel_k = ['취소', 'CXL', 'CANCEL', 'NO', 'NOSHOW', 'RC', 'RX']
    def_exc = [s for s in all_sts if any(x in s.upper() for x in cancel_k)]
    exc_sts = st.multiselect("제외할 상태 (취소 등)", options=all_sts, default=def_exc)

df_clean = df[~df['상태'].isin(exc_sts)]

# 상단 정보
st.title("🏨 Hotel Strategy Dashboard")
st.markdown(f"**Data:** {df_clean['입실일자'].min().date()} ~ {df_clean['입실일자'].max().date()} | **Total:** {len(df_clean):,} Bookings")

# 메인 필터
c1, c2 = st.columns([1, 2])
with c1:
    view_mode = st.radio("기간 단위", ["월별", "분기별", "주별", "연간"], horizontal=True)
with c2:
    all_acc = sorted(df_clean['거래처'].unique())
    sel_acc = st.multiselect("거래처 필터", all_acc, placeholder="전체 (All Channels)")

df_view = df_clean[df_clean['거래처'].isin(sel_acc)] if sel_acc else df_clean
st.divider()

# 기간 선택
years = sorted(df_view['Year'].unique(), reverse=True)
if not years: st.stop()

col1, col2 = st.columns(2)
target_df, ref_df = pd.DataFrame(), pd.DataFrame()
chart_sub = ""
q_map = {"1분기": [1,2,3], "2분기": [4,5,6], "3분기": [7,8,9], "4분기": [10,11,12]}

if view_mode == "월별":
    with col1:
        ty = st.selectbox("Target 연도", years); tm = st.selectbox("Target 월", range(1,13))
    with col2:
        ry = st.selectbox("Ref 연도", years, index=(1 if len(years)>1 else 0))
        rm = st.selectbox("Ref 월", range(1,13), index=tm-1)
    target_df = df_view[(df_view['Year']==ty) & (df_view['Month']==tm)]
    ref_df = df_view[(df_view['Year']==ry) & (df_view['Month']==rm)]
    chart_sub = f"{ty}.{tm} vs {ry}.{rm}"

elif view_mode == "분기별":
    qs = list(q_map.keys())
    with col1:
        ty = st.selectbox("Target 연도", years); tq = st.selectbox("Target 분기", qs)
    with col2:
        ry = st.selectbox("Ref 연도", years, index=(1 if len(years)>1 else 0))
        rq = st.selectbox("Ref 분기", qs, index=qs.index(tq))
    target_df = df_view[(df_view['Year']==ty) & (df_view['Month'].isin(q_map[tq]))]
    ref_df = df_view[(df_view['Year']==ry) & (df_view['Month'].isin(q_map[rq]))]
    chart_sub = f"{ty} {tq} vs {ry} {rq}"

elif view_mode == "주별":
    with col1:
        ty = st.selectbox("Target 연도", years)
        tw = st.selectbox("Target 주차", sorted(df_view[df_view['Year']==ty]['Week'].unique()))
    with col2:
        ry = st.selectbox("Ref 연도", years, index=(1 if len(years)>1 else 0))
        rw = st.selectbox("Ref 주차", range(1,54), index=int(min(tw-1, 52)))
    target_df = df_view[(df_view['Year']==ty) & (df_view['Week']==tw)]
    ref_df = df_view[(df_view['Year']==ry) & (df_view['Week']==rw)]
    chart_sub = f"{ty} {tw}주 vs {ry} {rw}주"
    
else: # 연간
    with col1: ty = st.selectbox("Target 연도", years)
    with col2: ry = st.selectbox("Ref 연도", years, index=(1 if len(years)>1 else 0))
    target_df = df_view[df_view['Year']==ty]
    ref_df = df_view[df_view['Year']==ry]
    chart_sub = f"{ty} 전체 vs {ry} 전체"

if target_df.empty:
    st.warning("해당 기간에 데이터가 없습니다.")
    st.stop()

# 시각화 (5개 탭)
tabs = st.tabs(["💰 매출", "💳 ADR", "⏳ 리드타임", "📅 요일", "🌏 국적/객실", "🔁 고객 로열티 & 재방문 분석"])

with tabs[0]: # Revenue
    st.subheader(f"매출 페이스: {chart_sub}")
    def get_pace(d):
        if d.empty: return pd.Series(dtype=float)
        return d.groupby('LeadTime')['총금액'].sum().sort_index(ascending=False).cumsum().sort_index()
    pt, pr = get_pace(target_df), get_pace(ref_df)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=pt.index, y=pt.values, name='Target', line=dict(color='#0052cc', width=3)))
    if not pr.empty: fig.add_trace(go.Scatter(x=pr.index, y=pr.values, name='Ref', line=dict(color='gray', dash='dot')))
    if not pt.empty:
        lp = pt.index.min()
        fig.add_trace(go.Scatter(x=[lp], y=[pt[lp]], mode='markers+text', text=[f"{pt[lp]/10000:,.0f}만"], textposition="top left", marker=dict(color='red', size=8), showlegend=False))
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
    st.subheader("예약 시점 분포")
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
        fig5 = px.pie(nd.head(7), values='총금액', names='국적', hole=0.4, title="Target 국적")
        st.plotly_chart(fig5, use_container_width=True)
    with c2:
        rt_t = target_df.groupby('객실타입')['총금액'].sum().reset_index().assign(Type='Target')
        rt_r = ref_df.groupby('객실타입')['총금액'].sum().reset_index().assign(Type='Ref')
        top = rt_t.sort_values('총금액', ascending=False).head(10)['객실타입']
        fig6 = px.bar(pd.concat([rt_t, rt_r])[pd.concat([rt_t, rt_r])['객실타입'].isin(top)], x='객실타입', y='총금액', color='Type', barmode='group')
        st.plotly_chart(fig6, use_container_width=True)

# --- TAB 6: Guest Loyalty (재방문 분석) ---
with tabs[4]: # 기존 탭 뒤에 추가하거나 순서를 조정하세요
    st.subheader("🔁 고객 로열티 & 재방문 분석")
    
    # 1. 고객 식별키 생성 (성함 + 휴대폰 뒷자리 조합)
    # 데이터에 '고객명'과 '휴대폰' 컬럼이 있는 경우 사용
    df_loyalty = target_df.copy()
    df_loyalty['GuestKey'] = df_loyalty['고객명'].astype(str) + "_" + df_loyalty['휴대폰'].astype(str).str[-4:]
    
    # 전체 기간(df_clean) 기준으로 이 고객들이 몇 번이나 왔는지 계산
    guest_counts = df_clean.groupby(['고객명', df_clean['휴대폰'].astype(str).str[-4:]]).size().reset_index(name='TotalVisits')
    guest_counts['GuestKey'] = guest_counts['고객명'].astype(str) + "_" + guest_counts['휴대폰'].astype(str)
    
    # 현재 선택된 기간(target_df)의 고객들에게 '과거 방문 횟수' 매핑
    target_loyalty = pd.merge(df_loyalty, guest_counts[['GuestKey', 'TotalVisits']], on='GuestKey', how='left')
    target_loyalty['GuestType'] = target_loyalty['TotalVisits'].apply(lambda x: '첫 방문 (New)' if x == 1 else '재방문 (Return)')

    col_l1, col_l2 = st.columns(2)
    
    with col_l1:
        st.markdown("**재방문 고객 비중**")
        loyalty_pie = px.pie(target_loyalty, names='GuestType', hole=0.4, 
                             color='GuestType', color_discrete_map={'첫 방문 (New)':'#E5ECF6', '재방문 (Return)':'#0052cc'})
        st.plotly_chart(loyalty_pie, use_container_width=True)

    with col_l2:
        st.markdown("**재방문객은 어디서 예약하는가?**")
        return_guests = target_loyalty[target_loyalty['GuestType'] == '재방문 (Return)']
        if not return_guests.empty:
            chan_loyalty = return_guests.groupby('거래처').size().reset_index(name='Count').sort_values('Count', ascending=False)
            fig_chan = px.bar(chan_loyalty.head(10), x='거래처', y='Count', color='Count', color_continuous_scale='Blues')
            st.plotly_chart(fig_chan, use_container_width=True)
        else:
            st.info("해당 기간에 재방문 고객이 없습니다.")

    st.divider()
    
    col_l3, col_l4 = st.columns(2)
    with col_l3:
        st.markdown("**고객 등급별 매출 기여도**")
        # 방문 횟수별 그룹화 (1회, 2회, 3~5회, 6회 이상)
        def guest_grade(n):
            if n == 1: return "1. 신규고객"
            elif n == 2: return "2. 리피터(2회)"
            elif n >= 3 and n <= 5: return "3. 단골(3-5회)"
            else: return "4. VIP(6회+)"
        
        target_loyalty['Grade'] = target_loyalty['TotalVisits'].apply(guest_grade)
        grade_rev = target_loyalty.groupby('Grade')['총금액'].sum().reset_index()
        fig_grade = px.bar(grade_rev, x='Grade', y='총금액', text_auto='.2s', color='Grade')
        st.plotly_chart(fig_grade, use_container_width=True)

    with col_l4:
        st.markdown("**재방문객 vs 신규객 객단가(ADR) 비교**")
        # 신규객과 재방문객 중 누가 더 비싼 방을 예약하는가?
        adr_comp = target_loyalty.groupby('GuestType').apply(lambda x: x['총금액'].sum() / x['객실수'].sum()).reset_index(name='ADR')
        fig_adr_comp = px.bar(adr_comp, x='GuestType', y='ADR', color='GuestType', text_auto=',.0f')
        st.plotly_chart(fig_adr_comp, use_container_width=True)

# 검증기
st.divider()
with st.expander("🕵️‍♂️ 데이터 검증 (Raw Data)"):
    st.dataframe(target_df.head(100))
