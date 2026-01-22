import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore

# -----------------------------------------------------------------------------
# 1. Firebase 접속 설정
# -----------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Hotel Strategy Dashboard", page_icon="🏨")

@st.cache_resource
def init_firebase():
    if not firebase_admin._apps:
        try:
            # Streamlit Cloud 배포용 (Secrets 사용)
            key_dict = st.secrets["firebase"]
            cred = credentials.Certificate(key_dict)
            firebase_admin.initialize_app(cred)
        except:
            # 로컬 테스트용 (파일 사용)
            try:
                cred = credentials.Certificate("serviceAccountKey.json")
                firebase_admin.initialize_app(cred)
            except:
                st.warning("⚠️ DB 연결 정보를 찾을 수 없습니다. (배포 시 Secrets 설정 필요)")
                return None
    return firestore.client()

db = init_firebase()

# -----------------------------------------------------------------------------
# 2. 데이터 업로드 함수 (Admin용 - 덮어쓰기 로직 포함)
# -----------------------------------------------------------------------------
def upload_to_firestore(df_new):
    if df_new.empty or db is None: return
    
    # 전처리
    df_new = df_new.copy()
    df_new['입실일자'] = pd.to_datetime(df_new['입실일자'], errors='coerce')
    df_new['예약일자'] = pd.to_datetime(df_new['예약일자'], errors='coerce')
    df_new['예약번호'] = df_new['예약번호'].astype(str) # ID로 쓸거라 문자열 변환
    
    # NaN값 채우기 (DB 에러 방지)
    df_new = df_new.fillna({
        '거래처': 'Direct', '국적': 'Unknown', '객실타입': 'Unknown', 
        '상태': 'Unknown', '총금액': 0, '객실수': 1
    })
    
    # 배치 업로드 (속도 향상)
    batch = db.batch()
    count = 0
    total = len(df_new)
    
    status_bar = st.progress(0)
    status_text = st.empty()
    
    for idx, row in df_new.iterrows():
        # [핵심] 예약번호를 문서 ID로 사용 -> 자동으로 덮어쓰기(Update) 됨!
        doc_ref = db.collection('hotel_bookings').document(row['예약번호'])
        row_dict = row.to_dict()
        
        # 날짜 객체 처리 (Firestore 호환)
        if pd.notnull(row_dict['입실일자']): row_dict['입실일자'] = row_dict['입실일자']
        if pd.notnull(row_dict['예약일자']): row_dict['예약일자'] = row_dict['예약일자']
        
        batch.set(doc_ref, row_dict, merge=True)
        count += 1
        
        if count % 400 == 0:
            batch.commit()
            batch = db.batch()
            status_bar.progress(count / total)
            status_text.text(f"🚀 {count}/{total} 건 처리 중...")
            
    batch.commit()
    status_bar.empty()
    status_text.success(f"✅ {total}건 업데이트 완료! (중복은 덮어썼습니다)")

# -----------------------------------------------------------------------------
# 3. 데이터 조회 함수 (Viewer용)
# -----------------------------------------------------------------------------
@st.cache_data(ttl=600) # 10분 캐시
def load_from_firestore():
    if db is None: return pd.DataFrame()
    
    docs = db.collection('hotel_bookings').stream()
    data = [doc.to_dict() for doc in docs]
    
    if not data: return pd.DataFrame()
    
    df = pd.DataFrame(data)
    
    # 형변환 복구
    df['입실일자'] = pd.to_datetime(df['입실일자']).dt.tz_localize(None)
    df['예약일자'] = pd.to_datetime(df['예약일자']).dt.tz_localize(None)
    
    # 숫자 처리
    for col in ['총금액', '객실수']:
        if col in df.columns and df[col].dtype == object:
            df[col] = df[col].astype(str).str.replace(',', '').astype(float)
            
    # 파생 변수
    df['LeadTime'] = (df['입실일자'] - df['예약일자']).dt.days
    df['Year'] = df['입실일자'].dt.isocalendar().year.astype(int)
    df['Month'] = df['입실일자'].dt.month.astype(int)
    df['Week'] = df['입실일자'].dt.isocalendar().week.astype(int)
    df['DayOfWeek'] = df['입실일자'].dt.day_name()
    
    return df

# -----------------------------------------------------------------------------
# 4. 사이드바 (Admin 업로드 & 필터)
# -----------------------------------------------------------------------------
with st.sidebar:
    st.title("Admin & Filter")
    
    # [Admin] 데이터 업로드 구역
    with st.expander("📤 데이터 DB 업데이트 (Admin)", expanded=False):
        st.info("여기 파일을 올리면 DB가 최신화됩니다. (직원들은 안 해도 됨)")
        up_files = st.file_uploader("엑셀 파일 업로드", accept_multiple_files=True)
        
        if up_files and st.button("🔥 DB 업데이트 실행"):
            all_df = []
            for f in up_files:
                try:
                    tmp = pd.read_csv(f, header=2) if f.name.endswith('.csv') else pd.read_excel(f, header=2)
                    if {'입실일자', '예약번호'}.issubset(tmp.columns):
                        all_df.append(tmp)
                except: pass
            
            if all_df:
                final_df = pd.concat(all_df, ignore_index=True)
                upload_to_firestore(final_df)
                st.cache_data.clear() # 캐시 초기화해서 바로 반영되게
                st.rerun()

# -----------------------------------------------------------------------------
# 5. 메인 대시보드 로직
# -----------------------------------------------------------------------------
df = load_from_firestore()

if df.empty:
    st.title("🏨 Hotel Dashboard")
    st.warning("데이터가 없습니다. 사이드바에서 파일을 업로드해주세요.")
    st.stop()

# 상태 필터 (자동 감지)
with st.sidebar:
    st.divider()
    all_sts = df['상태'].unique().astype(str)
    # RC, RX 등 취소 키워드 자동 선택
    cancel_k = ['취소', 'CXL', 'CANCEL', 'NO', 'NOSHOW', 'RC', 'RX']
    def_exc = [s for s in all_sts if any(x in s.upper() for x in cancel_k)]
    
    exc_sts = st.multiselect("제외할 상태 (취소 등)", options=all_sts, default=def_exc)

df_clean = df[~df['상태'].isin(exc_sts)]

# 상단 헤더
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

# 기간 선택 (Target vs Ref)
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

# -----------------------------------------------------------------------------
# 6. 시각화 (5개 탭)
# -----------------------------------------------------------------------------
tabs = st.tabs(["💰 매출", "💳 ADR", "⏳ 리드타임", "📅 요일", "🌏 국적/객실"])

# 1. Revenue
with tabs[0]:
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

# 2. ADR
with tabs[1]:
    st.subheader("객단가(ADR) 추이")
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

# 3. Lead Time
with tabs[2]:
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

# 4. Day of Week
with tabs[3]:
    st.subheader("요일별 매출")
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    td = target_df.groupby('DayOfWeek')['총금액'].mean().reindex(days).reset_index()
    rd = ref_df.groupby('DayOfWeek')['총금액'].mean().reindex(days).reset_index()
    fig4 = go.Figure()
    fig4.add_trace(go.Scatter(x=td['DayOfWeek'], y=td['총금액'], name='Target', line=dict(color='green', width=3)))
    fig4.add_trace(go.Scatter(x=rd['DayOfWeek'], y=rd['총금액'], name='Ref', line=dict(color='gray', dash='dot')))
    st.plotly_chart(fig4, use_container_width=True)

# 5. Demographics
with tabs[4]:
    st.subheader("국적 및 객실 분석")
    col_d1, col_d2 = st.columns(2)
    with col_d1:
        nd = target_df.groupby('국적')['총금액'].sum().reset_index().sort_values('총금액', ascending=False)
        fig5 = px.pie(nd.head(7), values='총금액', names='국적', hole=0.4, title="Target 국적")
        st.plotly_chart(fig5, use_container_width=True)
    with col_d2:
        rt_t = target_df.groupby('객실타입')['총금액'].sum().reset_index().assign(Type='Target')
        rt_r = ref_df.groupby('객실타입')['총금액'].sum().reset_index().assign(Type='Ref')
        top = rt_t.sort_values('총금액', ascending=False).head(10)['객실타입']
        fig6 = px.bar(pd.concat([rt_t, rt_r])[pd.concat([rt_t, rt_r])['객실타입'].isin(top)], x='객실타입', y='총금액', color='Type', barmode='group')
        st.plotly_chart(fig6, use_container_width=True)

# 검증기
st.divider()
with st.expander("데이터 검증 (Raw Data)"):
    st.dataframe(target_df.head(100))
