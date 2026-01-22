import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta
import os

# -----------------------------------------------------------------------------
# 1. 기본 설정 및 데이터 로드
# -----------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Hotel Strategy Dashboard", page_icon="🏨")

# 공유 시 핵심: 이 파일이 GitHub 같은 서버에 같이 올라가 있어야 남들도 봅니다.
DATA_FILE_PATH = 'saved_history_data.csv'

@st.cache_data
def load_and_merge_data(base_file_path, new_files):
    # 1. 서버/로컬에 저장된 과거 데이터 로드
    df_base = pd.DataFrame()
    if os.path.exists(base_file_path):
        try:
            df_base = pd.read_csv(base_file_path)
        except:
            pass
            
    # 2. 사용자가 방금 올린 신규 데이터 로드
    all_new_data = []
    if new_files:
        for file in new_files:
            try:
                if file.name.endswith('.csv'):
                    df = pd.read_csv(file, header=2)
                else:
                    df = pd.read_excel(file, header=2)
                
                # [업데이트] 분석에 필요한 필수 컬럼 확장
                required = ['입실일자', '예약일자', '총금액', '상태', '예약번호', '거래처', '객실수', '국적', '객실타입']
                # 일부 컬럼이 없어도 돌아가게 처리 (유연성 확보)
                if set(['입실일자', '예약일자', '총금액']).issubset(df.columns):
                    all_new_data.append(df)
            except Exception as e:
                st.error(f"파일 로드 오류 ({file.name}): {e}")

    df_new = pd.concat(all_new_data, ignore_index=True) if all_new_data else pd.DataFrame()

    if df_base.empty and df_new.empty:
        return pd.DataFrame()
    
    # --- 전처리 함수 ---
    def safe_to_datetime(series):
        return pd.to_datetime(series, errors='coerce')

    def preprocess(d):
        if d.empty: return d
        d['입실일자'] = safe_to_datetime(d['입실일자'])
        d['예약일자'] = safe_to_datetime(d['예약일자'])
        
        # 숫자 변환 (금액, 객실수)
        for col in ['총금액', '객실수']:
            if col in d.columns and d[col].dtype == object:
                d[col] = d[col].astype(str).str.replace(',', '').astype(float)
        
        # 없는 컬럼 채우기 (에러 방지)
        if '객실수' not in d.columns: d['객실수'] = 1
        if '국적' not in d.columns: d['국적'] = 'Unknown'
        if '객실타입' not in d.columns: d['객실타입'] = 'Unknown'
        
        return d

    if not df_base.empty: df_base = preprocess(df_base)
    if not df_new.empty: df_new = preprocess(df_new)
        
    # 병합
    df_master = pd.concat([df_base, df_new], ignore_index=True)
    df_master = df_master.dropna(subset=['입실일자', '예약일자'])
    df_master = df_master.drop_duplicates(subset=['예약번호'], keep='last')
    
    # 파생 변수 생성
    df_master['LeadTime'] = (df_master['입실일자'] - df_master['예약일자']).dt.days
    df_master['Year'] = df_master['입실일자'].dt.isocalendar().year.astype(int)
    df_master['Week'] = df_master['입실일자'].dt.isocalendar().week.astype(int)
    df_master['Month'] = df_master['입실일자'].dt.month.astype(int)
    df_master['DayOfWeek'] = df_master['입실일자'].dt.day_name()
    df_master['거래처'] = df_master['거래처'].fillna('Direct').astype(str).str.strip()
    
    return df_master

# -----------------------------------------------------------------------------
# 2. 사이드바 (데이터 관리 & 필터)
# -----------------------------------------------------------------------------
with st.sidebar:
    st.title("🏨 Dashboard Menu")
    
    with st.expander("📂 데이터 파일 관리", expanded=True):
        st.caption("팀원들과 공유하려면 '과거 데이터'를 미리 저장해두세요.")
        
        # 과거 데이터 저장 로직
        new_history = st.file_uploader("과거 데이터 업로드 (Admin용)", accept_multiple_files=True, key='history')
        if new_history and st.button("💾 이 데이터를 서버에 저장"):
            temp_df = pd.DataFrame()
            for f in new_history:
                try:
                    d = pd.read_csv(f, header=2) if f.name.endswith('.csv') else pd.read_excel(f, header=2)
                    temp_df = pd.concat([temp_df, d])
                except: pass
            if not temp_df.empty:
                temp_df.to_csv(DATA_FILE_PATH, index=False)
                st.success("저장 완료! 이제 새로고침해도 데이터가 유지됩니다.")
                st.rerun()

        daily_files = st.file_uploader("오늘 데이터 추가 (Update)", accept_multiple_files=True, key='daily')

# 데이터 로딩
df = load_and_merge_data(DATA_FILE_PATH, daily_files)

if df.empty:
    st.info("👋 환영합니다! 왼쪽 사이드바에서 데이터 파일을 업로드해주세요.")
    st.stop()

# 상태 필터 (자동 감지)
with st.sidebar:
    st.divider()
    st.markdown("**🚫 필터 설정**")
    all_statuses = df['상태'].unique().astype(str)
    cancel_keywords = ['취소', 'CXL', 'CANCEL', 'NO', 'NOSHOW', 'RC', 'RX']
    default_excludes = [s for s in all_statuses if any(x in s.upper() for x in cancel_keywords)]
    
    exclude_statuses = st.multiselect("제외할 상태값 (취소 등)", options=all_statuses, default=default_excludes)

df_clean = df[~df['상태'].isin(exclude_statuses)]

# -----------------------------------------------------------------------------
# 3. 메인 분석 화면
# -----------------------------------------------------------------------------
st.title("🏨 Hotel Strategy Dashboard")
st.markdown(f"**Data Range:** {df_clean['입실일자'].min().date()} ~ {df_clean['입실일자'].max().date()} | **Total Bookings:** {len(df_clean):,} 건")

# 상단 필터
c_f1, c_f2 = st.columns([1, 2])
with c_f1:
    view_mode = st.radio("분석 기간", ["월별", "분기별", "주별", "연간"], horizontal=True)
with c_f2:
    all_acc = sorted(df_clean['거래처'].unique())
    selected_acc = st.multiselect("거래처 필터", all_acc, placeholder="전체 보기 (All Channels)")

df_filtered = df_clean[df_clean['거래처'].isin(selected_acc)] if selected_acc else df_clean
filter_label = ", ".join(selected_acc) if selected_acc else "전체"

st.divider()

# 기간 선택 컨트롤러
available_years = sorted(df_filtered['Year'].unique(), reverse=True)
if not available_years:
    st.error("선택한 조건에 맞는 데이터가 없습니다.")
    st.stop()

col_ctrl1, col_ctrl2 = st.columns(2)
target_df = pd.DataFrame()
ref_df = pd.DataFrame()
chart_title = ""
quarters_map = {"1분기": [1,2,3], "2분기": [4,5,6], "3분기": [7,8,9], "4분기": [10,11,12]}

if view_mode == "월별":
    with col_ctrl1:
        t_year = st.selectbox("Target 연도", available_years, index=0)
        t_month = st.selectbox("Target 월", range(1, 13))
    with col_ctrl2:
        ref_idx = available_years.index(t_year-1) if (t_year-1) in available_years else 0
        r_year = st.selectbox("Ref 연도", available_years, index=ref_idx)
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
        ref_idx = available_years.index(t_year-1) if (t_year-1) in available_years else 0
        r_year = st.selectbox("Ref 연도", available_years, index=ref_idx)
        r_q = st.selectbox("Ref 분기", q_keys, index=q_keys.index(t_q))
    target_df = df_filtered[(df_filtered['Year'] == t_year) & (df_filtered['Month'].isin(quarters_map[t_q]))]
    ref_df = df_filtered[(df_filtered['Year'] == r_year) & (df_filtered['Month'].isin(quarters_map[r_q]))]
    chart_title = f"{t_year} {t_q} vs {r_year} {r_q}"

elif view_mode == "주별":
    with col_ctrl1:
        t_year = st.selectbox("Target 연도", available_years)
        t_week = st.selectbox("Target 주차", sorted(df_filtered[df_filtered['Year']==t_year]['Week'].unique()))
    with col_ctrl2:
        ref_idx = available_years.index(t_year-1) if (t_year-1) in available_years else 0
        r_year = st.selectbox("Ref 연도", available_years, index=ref_idx)
        r_week = st.selectbox("Ref 주차", range(1, 54), index=int(min(t_week-1, 52)))
    target_df = df_filtered[(df_filtered['Year'] == t_year) & (df_filtered['Week'] == t_week)]
    ref_df = df_filtered[(df_filtered['Year'] == r_year) & (df_filtered['Week'] == r_week)]
    chart_title = f"{t_year} {t_week}주 vs {r_year} {r_week}주"

else: # 연간
    with col_ctrl1: t_year = st.selectbox("Target 연도", available_years)
    with col_ctrl2: r_year = st.selectbox("Ref 연도", available_years, index=available_years.index(t_year-1) if (t_year-1) in available_years else 0)
    target_df = df_filtered[df_filtered['Year'] == t_year]
    ref_df = df_filtered[df_filtered['Year'] == r_year]
    chart_title = f"{t_year} 전체 vs {r_year} 전체"


if target_df.empty:
    st.warning("선택한 기간에 데이터가 없습니다.")
    st.stop()

# ==============================================================================
# 🌟 5개의 탭: 매출 / 객단가 / 리드타임 / 요일 / 고객분석(New)
# ==============================================================================
tabs = st.tabs([
    "💰 매출 (Revenue)", 
    "💳 객단가 (ADR)", 
    "⏳ 리드타임 (Lead Time)",
    "📅 요일 분석 (Day)",
    "🌏 국적/객실 (Demographics)" 
])

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
    st.subheader(f"ADR(평균단가) 추이: {chart_title}")
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
    fig2.update_layout(xaxis_title="D-Day", yaxis_title="ADR (원)", xaxis={'autorange': 'reversed'}, height=500)
    st.plotly_chart(fig2, use_container_width=True)

# --- TAB 3: Lead Time ---
with tabs[2]:
    st.subheader("예약 리드타임 분포")
    bins = [-1, 0, 3, 7, 14, 30, 60, 90, 999]
    labels = ['당일(0)', '1-3일전', '4-7일전', '8-14일전', '15-30일전', '31-60일전', '61-90일전', '90일+']
    
    # SettingWithCopyWarning 방지를 위해 copy() 사용
    t_df_c = target_df.copy()
    r_df_c = ref_df.copy()
    
    t_df_c['LeadGroup'] = pd.cut(t_df_c['LeadTime'], bins=bins, labels=labels)
    r_df_c['LeadGroup'] = pd.cut(r_df_c['LeadTime'], bins=bins, labels=labels)
    
    t_g = t_df_c.groupby('LeadGroup')['총금액'].sum().reset_index().assign(Type='Target')
    r_g = r_df_c.groupby('LeadGroup')['총금액'].sum().reset_index().assign(Type='Ref')
    
    fig3 = px.bar(pd.concat([t_g, r_g]), x='LeadGroup', y='총금액', color='Type', barmode='group', 
                  color_discrete_map={'Target': '#0052cc', 'Ref': '#bababa'})
    st.plotly_chart(fig3, use_container_width=True)

# --- TAB 4: Day of Week ---
with tabs[3]:
    st.subheader("요일별 매출 퍼포먼스")
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    t_d = target_df.groupby('DayOfWeek')['총금액'].mean().reindex(days).reset_index()
    r_d = ref_df.groupby('DayOfWeek')['총금액'].mean().reindex(days).reset_index()
    
    fig4 = go.Figure()
    fig4.add_trace(go.Scatter(x=t_d['DayOfWeek'], y=t_d['총금액'], name='Target', line=dict(color='green', width=3)))
    fig4.add_trace(go.Scatter(x=r_d['DayOfWeek'], y=r_d['총금액'], name='Ref', line=dict(color='gray', dash='dot')))
    fig4.update_layout(yaxis_title="일평균 매출")
    st.plotly_chart(fig4, use_container_width=True)

# --- TAB 5: Demographics (New) ---
with tabs[4]:
    st.subheader("🌏 누가(국적), 무엇을(객실) 예약했나?")
    col_demo1, col_demo2 = st.columns(2)
    
    with col_demo1:
        st.markdown("**국적별 비중 (Target)**")
        nat_data = target_df.groupby('국적')['총금액'].sum().reset_index()
        # 매출 상위 7개만 보여주고 나머지는 기타 처리
        if len(nat_data) > 7:
            nat_data = nat_data.sort_values('총금액', ascending=False)
            top7 = nat_data.head(7)
            others = pd.DataFrame([['Others', nat_data.iloc[7:]['총금액'].sum()]], columns=['국적', '총금액'])
            nat_data = pd.concat([top7, others])
            
        fig5 = px.pie(nat_data, values='총금액', names='국적', hole=0.4)
        st.plotly_chart(fig5, use_container_width=True)

    with col_demo2:
        st.markdown("**객실 타입별 판매액 (Target vs Ref)**")
        rt_t = target_df.groupby('객실타입')['총금액'].sum().reset_index().assign(Type='Target')
        rt_r = ref_df.groupby('객실타입')['총금액'].sum().reset_index().assign(Type='Ref')
        
        # 상위 10개 타입만
        top_types = rt_t.sort_values('총금액', ascending=False).head(10)['객실타입'].tolist()
        combined_rt = pd.concat([rt_t, rt_r])
        combined_rt = combined_rt[combined_rt['객실타입'].isin(top_types)]
        
        fig6 = px.bar(combined_rt, x='객실타입', y='총금액', color='Type', barmode='group',
                      color_discrete_map={'Target': '#0052cc', 'Ref': '#bababa'})
        st.plotly_chart(fig6, use_container_width=True)

# 검증기
st.divider()
with st.expander("데이터 검증 (Raw Data Inspector)"):
    st.dataframe(target_df.head(100))
