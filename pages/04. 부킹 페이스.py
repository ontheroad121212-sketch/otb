import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore

# -----------------------------------------------------------------------------
# 1. Firebase 접속 및 설정 (Streamlit Secrets 활용)
# -----------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Hotel Strategy Dashboard", page_icon="🏨")

# 캐싱을 통해 DB 연결 속도 최적화
@st.cache_resource
def init_firebase():
    # 이미 앱이 초기화되어 있는지 확인
    if not firebase_admin._apps:
        # Streamlit Cloud 배포 시: st.secrets에 저장된 정보 사용
        # 로컬 테스트 시: serviceAccountKey.json 파일 경로 사용 가능
        try:
            # 1. Streamlit Secrets에서 가져오기 (배포용)
            key_dict = st.secrets["firebase"]
            cred = credentials.Certificate(key_dict)
            firebase_admin.initialize_app(cred)
        except:
            # 2. 로컬 파일에서 가져오기 (테스트용 - 파일명 확인 필요)
            try:
                cred = credentials.Certificate("serviceAccountKey.json")
                firebase_admin.initialize_app(cred)
            except:
                st.error("🔥 Firebase 인증 키를 찾을 수 없습니다. secrets.toml 설정이나 json 파일을 확인하세요.")
                return None
    return firestore.client()

db = init_firebase()

# -----------------------------------------------------------------------------
# 2. 데이터 처리 함수 (업로드 & 다운로드)
# -----------------------------------------------------------------------------

# [Admin] 엑셀 -> 파이어베이스 업로드
def upload_to_firestore(df_new):
    if df_new.empty: return
    
    # 1. 데이터 전처리 (DB에 넣기 좋게 변환)
    df_new = df_new.copy()
    
    # 날짜를 문자열이나 datetime 객체로 통일
    df_new['입실일자'] = pd.to_datetime(df_new['입실일자'], errors='coerce')
    df_new['예약일자'] = pd.to_datetime(df_new['예약일자'], errors='coerce')
    
    # NaN(빈값) 처리 (Firestore는 NaN을 싫어함)
    df_new = df_new.fillna({
        '거래처': 'Direct', '국적': 'Unknown', '객실타입': 'Unknown', 
        '상태': 'Unknown', '총금액': 0, '객실수': 1
    })
    
    # 예약번호를 문자열로 (Document ID로 쓰기 위함)
    df_new['예약번호'] = df_new['예약번호'].astype(str)

    # 2. 배치 업로드 (속도 향상)
    batch = db.batch()
    count = 0
    total = len(df_new)
    
    progress_bar = st.progress(0)
    status_text = st.empty()

    for idx, row in df_new.iterrows():
        # 예약번호를 문서 ID로 사용 -> 덮어쓰기(업데이트) 자동 처리
        doc_ref = db.collection('hotel_bookings').document(row['예약번호'])
        
        # 데이터 딕셔너리 변환
        row_dict = row.to_dict()
        
        # set with merge=True: 기존 데이터 있으면 업데이트, 없으면 생성
        batch.set(doc_ref, row_dict, merge=True)
        count += 1
        
        # Firestore 배치 제한 (500개)
        if count % 400 == 0:
            batch.commit()
            batch = db.batch()
            progress_bar.progress(count / total)
            status_text.text(f"🚀 클라우드에 데이터 전송 중... ({count}/{total})")
            
    batch.commit() # 남은 것 최종 전송
    progress_bar.empty()
    status_text.success(f"✅ {total}건의 데이터가 파이어베이스에 안전하게 저장되었습니다!")

# [Viewer] 파이어베이스 -> 화면 조회
@st.cache_data(ttl=600) # 10분마다 캐시 갱신
def load_from_firestore():
    if db is None: return pd.DataFrame()
    
    # 컬렉션의 모든 데이터 가져오기
    docs = db.collection('hotel_bookings').stream()
    
    data = []
    for doc in docs:
        data.append(doc.to_dict())
        
    if not data: return pd.DataFrame()
    
    df = pd.DataFrame(data)
    
    # 날짜 형변환 복구
    df['입실일자'] = pd.to_datetime(df['입실일자'])
    df['예약일자'] = pd.to_datetime(df['예약일자'])
    
    # 파생 변수 생성 (DB에서 안 가져오고 여기서 계산)
    df['LeadTime'] = (df['입실일자'] - df['예약일자']).dt.days
    df['Year'] = df['입실일자'].dt.isocalendar().year.astype(int)
    df['Month'] = df['입실일자'].dt.month.astype(int)
    df['Week'] = df['입실일자'].dt.isocalendar().week.astype(int)
    df['DayOfWeek'] = df['입실일자'].dt.day_name()
    
    # 금액/객실수 숫자형 보장
    if df['총금액'].dtype == object:
        df['총금액'] = df['총금액'].astype(str).str.replace(',', '').astype(float)
    if '객실수' in df.columns and df['객실수'].dtype == object:
        df['객실수'] = df['객실수'].astype(str).str.replace(',', '').astype(float)
        
    return df

# -----------------------------------------------------------------------------
# 3. 사이드바 (Admin 전용: 데이터 업로드)
# -----------------------------------------------------------------------------
with st.sidebar:
    st.title("Admin Console")
    st.info("비밀번호나 특정 키를 아는 사람만 업로드하게 할 수도 있습니다.")
    
    with st.expander("📤 데이터 업데이트 (Admin Only)", expanded=False):
        uploaded_files = st.file_uploader("PMS 엑셀 파일 업로드", accept_multiple_files=True)
        
        if uploaded_files and st.button("🔥 DB에 저장/업데이트 하기"):
            all_data = []
            for f in uploaded_files:
                try:
                    # 헤더 2번째 줄 스킵 처리
                    temp_df = pd.read_csv(f, header=2) if f.name.endswith('.csv') else pd.read_excel(f, header=2)
                    
                    # 필수 컬럼 있는지만 확인
                    if {'입실일자', '예약일자', '예약번호'}.issubset(temp_df.columns):
                        all_data.append(temp_df)
                except Exception as e:
                    st.error(f"Error: {e}")
            
            if all_data:
                final_df = pd.concat(all_data, ignore_index=True)
                upload_to_firestore(final_df)
                st.rerun() # 새로고침해서 반영

# -----------------------------------------------------------------------------
# 4. 메인 화면 (Viewer 전용: 데이터 조회)
# -----------------------------------------------------------------------------
st.title("🏨 Hotel Strategy Dashboard (Live)")

# DB에서 데이터 로드
df = load_from_firestore()

if df.empty:
    st.warning("📭 데이터베이스가 비어있습니다. 사이드바에서 데이터를 업로드해주세요.")
    st.stop()

# --- 상태 필터 (자동 감지) ---
with st.sidebar:
    st.divider()
    all_statuses = df['상태'].unique().astype(str)
    cancel_keywords = ['취소', 'CXL', 'CANCEL', 'NO', 'NOSHOW', 'RC', 'RX']
    default_excludes = [s for s in all_statuses if any(x in s.upper() for x in cancel_keywords)]
    exclude_statuses = st.multiselect("제외할 상태값", options=all_statuses, default=default_excludes)

df_clean = df[~df['상태'].isin(exclude_statuses)]

st.markdown(f"**Data Range:** {df_clean['입실일자'].min().date()} ~ {df_clean['입실일자'].max().date()} | **Total Bookings:** {len(df_clean):,} 건")

# -----------------------------------------------------------------------------
# 5. 분석 로직 (기존과 동일)
# -----------------------------------------------------------------------------

# 상단 필터
c_f1, c_f2 = st.columns([1, 2])
with c_f1:
    view_mode = st.radio("분석 기간", ["월별", "분기별", "주별", "연간"], horizontal=True)
with c_f2:
    all_acc = sorted(df_clean['거래처'].unique())
    selected_acc = st.multiselect("거래처 필터", all_acc, placeholder="전체 보기")

df_filtered = df_clean[df_clean['거래처'].isin(selected_acc)] if selected_acc else df_clean

st.divider()

# 기간 선택 컨트롤러
available_years = sorted(df_filtered['Year'].unique(), reverse=True)
if not available_years:
    st.stop()

col_ctrl1, col_ctrl2 = st.columns(2)
target_df = pd.DataFrame()
ref_df = pd.DataFrame()
chart_title = ""
quarters_map = {"1분기": [1,2,3], "2분기": [4,5,6], "3분기": [7,8,9], "4분기": [10,11,12]}

# (기간 선택 로직은 코드 길이상 간략화, 기존 로직 그대로 사용됨)
if view_mode == "월별":
    with col_ctrl1:
        t_year = st.selectbox("Target 연도", available_years)
        t_month = st.selectbox("Target 월", range(1, 13))
    with col_ctrl2:
        r_year = st.selectbox("Ref 연도", available_years, index=(1 if len(available_years)>1 else 0))
        r_month = st.selectbox("Ref 월", range(1, 13), index=t_month-1)
    target_df = df_filtered[(df_filtered['Year'] == t_year) & (df_filtered['Month'] == t_month)]
    ref_df = df_filtered[(df_filtered['Year'] == r_year) & (df_filtered['Month'] == r_month)]
    chart_title = f"{t_year}.{t_month} vs {r_year}.{r_month}"

elif view_mode == "분기별":
    q_keys = list(quarters_map.keys())
    with col_ctrl1:
        t_year = st.selectbox("Target 연도", available_years)
        t_q = st.selectbox("Target 분기", q_keys)
    with col_ctrl2:
        r_year = st.selectbox("Ref 연도", available_years, index=(1 if len(available_years)>1 else 0))
        r_q = st.selectbox("Ref 분기", q_keys, index=q_keys.index(t_q))
    target_df = df_filtered[(df_filtered['Year'] == t_year) & (df_filtered['Month'].isin(quarters_map[t_q]))]
    ref_df = df_filtered[(df_filtered['Year'] == r_year) & (df_filtered['Month'].isin(quarters_map[r_q]))]
    chart_title = f"{t_year} {t_q} vs {r_year} {r_q}"

elif view_mode == "주별":
    with col_ctrl1:
        t_year = st.selectbox("Target 연도", available_years)
        t_week = st.selectbox("Target 주차", sorted(df_filtered[df_filtered['Year']==t_year]['Week'].unique()))
    with col_ctrl2:
        r_year = st.selectbox("Ref 연도", available_years, index=(1 if len(available_years)>1 else 0))
        r_week = st.selectbox("Ref 주차", range(1, 54), index=int(min(t_week-1, 52)))
    target_df = df_filtered[(df_filtered['Year'] == t_year) & (df_filtered['Week'] == t_week)]
    ref_df = df_filtered[(df_filtered['Year'] == r_year) & (df_filtered['Week'] == r_week)]
    chart_title = f"{t_year} {t_week}주 vs {r_year} {r_week}주"
    
else: # 연간
    with col_ctrl1: t_year = st.selectbox("Target 연도", available_years)
    with col_ctrl2: r_year = st.selectbox("Ref 연도", available_years, index=(1 if len(available_years)>1 else 0))
    target_df = df_filtered[df_filtered['Year'] == t_year]
    ref_df = df_filtered[df_filtered['Year'] == r_year]
    chart_title = f"{t_year} 전체 vs {r_year} 전체"


if target_df.empty:
    st.warning("데이터가 없습니다.")
    st.stop()

# 탭 구성
tabs = st.tabs(["💰 매출", "💳 ADR", "⏳ 리드타임", "📅 요일", "🌏 국적/객실"])

# (나머지 그래프 그리는 코드는 V5.0 코드와 100% 동일합니다. 여기 붙여넣으시면 됩니다.)
# ... [TAB 1 ~ TAB 5 그래프 코드 생략 없이 사용] ...

# --- TAB 1: Revenue ---
with tabs[0]:
    st.subheader(f"매출 페이스: {chart_title}")
    def get_pace(d, col='총금액'):
        if d.empty: return pd.Series(dtype=float)
        return d.groupby('LeadTime')[col].sum().sort_index(ascending=False).cumsum().sort_index()

    p_t = get_pace(target_df)
    p_r = get_pace(ref_df)

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=p_t.index, y=p_t.values, name='Target', line=dict(color='#0052cc', width=3)))
    if not p_r.empty: fig.add_trace(go.Scatter(x=p_r.index, y=p_r.values, name='Ref', line=dict(color='gray', dash='dot')))
    
    if not p_t.empty:
        lp = p_t.index.min()
        fig.add_trace(go.Scatter(x=[lp], y=[p_t[lp]], mode='markers+text', text=[f"{p_t[lp]/10000:,.0f}만"], textposition="top left", marker=dict(color='red', size=8), showlegend=False))
        
    fig.update_layout(xaxis_title="D-Day", yaxis_title="누적 매출", xaxis={'autorange': 'reversed'}, height=500)
    st.plotly_chart(fig, use_container_width=True)

# --- TAB 2: ADR ---
with tabs[1]:
    st.subheader(f"ADR 추이")
    def get_adr(d):
        if d.empty: return pd.Series(dtype=float)
        rev = d.groupby('LeadTime')['총금액'].sum().sort_index(ascending=False).cumsum().sort_index()
        rms = d.groupby('LeadTime')['객실수'].sum().sort_index(ascending=False).cumsum().sort_index()
        return (rev/rms).fillna(0)
    
    adr_t = get_adr(target_df)
    adr_r = get_adr(ref_df)
    
    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(x=adr_t.index, y=adr_t.values, name='Target ADR', line=dict(color='#ff6b6b', width=3)))
    if not adr_r.empty: fig2.add_trace(go.Scatter(x=adr_r.index, y=adr_r.values, name='Ref ADR', line=dict(color='gray', dash='dot')))
    fig2.update_layout(xaxis={'autorange': 'reversed'}, height=500)
    st.plotly_chart(fig2, use_container_width=True)

# --- TAB 3: Lead Time ---
with tabs[2]:
    st.subheader("예약 시점 분포")
    bins = [-1, 0, 3, 7, 14, 30, 60, 90, 999]
    labels = ['당일', '1-3일', '4-7일', '8-14일', '15-30일', '31-60일', '61-90일', '90일+']
    t_g = target_df.copy(); r_g = ref_df.copy()
    t_g['Group'] = pd.cut(t_g['LeadTime'], bins=bins, labels=labels)
    r_g['Group'] = pd.cut(r_g['LeadTime'], bins=bins, labels=labels)
    
    t_sum = t_g.groupby('Group')['총금액'].sum().reset_index().assign(Type='Target')
    r_sum = r_g.groupby('Group')['총금액'].sum().reset_index().assign(Type='Ref')
    
    fig3 = px.bar(pd.concat([t_sum, r_sum]), x='Group', y='총금액', color='Type', barmode='group')
    st.plotly_chart(fig3, use_container_width=True)

# --- TAB 4: Day of Week ---
with tabs[3]:
    st.subheader("요일별 매출")
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    t_d = target_df.groupby('DayOfWeek')['총금액'].mean().reindex(days).reset_index()
    r_d = ref_df.groupby('DayOfWeek')['총금액'].mean().reindex(days).reset_index()
    
    fig4 = go.Figure()
    fig4.add_trace(go.Scatter(x=t_d['DayOfWeek'], y=t_d['총금액'], name='Target', line=dict(color='green', width=3)))
    fig4.add_trace(go.Scatter(x=r_d['DayOfWeek'], y=r_d['총금액'], name='Ref', line=dict(color='gray', dash='dot')))
    st.plotly_chart(fig4, use_container_width=True)

# --- TAB 5: Demographics ---
with tabs[4]:
    st.subheader("국적 및 객실 분석")
    c1, c2 = st.columns(2)
    with c1:
        nat_data = target_df.groupby('국적')['총금액'].sum().reset_index().sort_values('총금액', ascending=False)
        fig5 = px.pie(nat_data.head(7), values='총금액', names='국적', hole=0.4, title="Target 국적 비중")
        st.plotly_chart(fig5, use_container_width=True)
    with c2:
        rt_t = target_df.groupby('객실타입')['총금액'].sum().reset_index().assign(Type='Target')
        rt_r = ref_df.groupby('객실타입')['총금액'].sum().reset_index().assign(Type='Ref')
        top = rt_t.sort_values('총금액', ascending=False).head(10)['객실타입']
        combined = pd.concat([rt_t, rt_r])
        fig6 = px.bar(combined[combined['객실타입'].isin(top)], x='객실타입', y='총금액', color='Type', barmode='group')
        st.plotly_chart(fig6, use_container_width=True)
