import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta
import os

# -----------------------------------------------------------------------------
# 1. 환경 설정 및 데이터 로드 함수
# -----------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Booking Pace Manager Pro")
DATA_FILE_PATH = 'saved_history_data.csv'

@st.cache_data
def load_and_merge_data(base_file_path, new_files):
    # 1. 저장된 과거 데이터 로드
    df_base = pd.DataFrame()
    if os.path.exists(base_file_path):
        try:
            df_base = pd.read_csv(base_file_path)
        except:
            pass
            
    # 2. 신규 업로드 데이터 로드
    all_new_data = []
    if new_files:
        for file in new_files:
            try:
                if file.name.endswith('.csv'):
                    df = pd.read_csv(file, header=2)
                else:
                    df = pd.read_excel(file, header=2)
                
                # 필수 컬럼 체크
                required = ['입실일자', '예약일자', '총금액', '상태', '예약번호', '거래처', '객실수']
                if set(required).issubset(df.columns):
                    all_new_data.append(df)
            except Exception as e:
                st.error(f"파일 로드 오류 ({file.name}): {e}")

    df_new = pd.concat(all_new_data, ignore_index=True) if all_new_data else pd.DataFrame()

    if df_base.empty and df_new.empty:
        return pd.DataFrame()
    
    # 병합 전 전처리
    def safe_to_datetime(series):
        return pd.to_datetime(series, errors='coerce')

    def preprocess(d):
        if d.empty: return d
        d['입실일자'] = safe_to_datetime(d['입실일자'])
        d['예약일자'] = safe_to_datetime(d['예약일자'])
        if d['총금액'].dtype == object:
            d['총금액'] = d['총금액'].astype(str).str.replace(',', '').astype(float)
        # 객실수 처리 (ADR 계산용)
        if '객실수' in d.columns:
             if d['객실수'].dtype == object:
                d['객실수'] = d['객실수'].astype(str).str.replace(',', '').astype(float)
        else:
            d['객실수'] = 1 # 없으면 1로 가정
        return d

    if not df_base.empty: df_base = preprocess(df_base)
    if not df_new.empty: df_new = preprocess(df_new)
        
    df_master = pd.concat([df_base, df_new], ignore_index=True)
    df_master = df_master.dropna(subset=['입실일자', '예약일자'])
    df_master = df_master.drop_duplicates(subset=['예약번호'], keep='last')
    
    # 파생 변수
    df_master['LeadTime'] = (df_master['입실일자'] - df_master['예약일자']).dt.days
    df_master['Year'] = df_master['입실일자'].dt.isocalendar().year.astype(int)
    df_master['Week'] = df_master['입실일자'].dt.isocalendar().week.astype(int)
    df_master['Month'] = df_master['입실일자'].dt.month.astype(int)
    df_master['DayOfWeek'] = df_master['입실일자'].dt.day_name() # 요일
    df_master['거래처'] = df_master['거래처'].fillna('Direct/Unknown').astype(str).str.strip()
    
    return df_master

# -----------------------------------------------------------------------------
# 2. 사이드바 (데이터 & 필터)
# -----------------------------------------------------------------------------
with st.sidebar:
    st.header("📂 Data Center")
    with st.expander("데이터 업로드/저장", expanded=True):
        new_history = st.file_uploader("과거 데이터(저장용)", accept_multiple_files=True, key='history')
        if new_history and st.button("과거 데이터 저장하기"):
            temp_df = pd.DataFrame()
            for f in new_history:
                try:
                    d = pd.read_csv(f, header=2) if f.name.endswith('.csv') else pd.read_excel(f, header=2)
                    temp_df = pd.concat([temp_df, d])
                except: pass
            if not temp_df.empty:
                temp_df.to_csv(DATA_FILE_PATH, index=False)
                st.success("저장 완료!")
                st.rerun()

        daily_files = st.file_uploader("오늘 데이터(분석용)", accept_multiple_files=True, key='daily')

df = load_and_merge_data(DATA_FILE_PATH, daily_files)
if df.empty:
    st.info("👈 데이터를 업로드해주세요.")
    st.stop()

# 상태 필터
with st.sidebar:
    st.divider()
    st.header("🚫 상태 필터")
    all_statuses = df['상태'].unique().astype(str)
    cancel_keywords = ['취소', 'CXL', 'CANCEL', 'NO', 'NOSHOW', 'RC', 'RX']
    default_excludes = [s for s in all_statuses if any(x in s.upper() for x in cancel_keywords)]
    exclude_statuses = st.multiselect("제외할 상태값", options=all_statuses, default=default_excludes)
    
df_clean = df[~df['상태'].isin(exclude_statuses)]

# -----------------------------------------------------------------------------
# 3. 메인 대시보드
# -----------------------------------------------------------------------------
st.title("🏨 Hotel Pace Analytics Pro")

# 필터 영역
col_f1, col_f2 = st.columns([1, 2])
with col_f1:
    view_mode = st.radio("분석 기간", ["월별", "분기별", "주별", "연간"], horizontal=True)
with col_f2:
    all_accounts = sorted(df_clean['거래처'].unique())
    selected_acc = st.multiselect("거래처 필터", options=all_accounts, placeholder="전체 보기")

df_filtered = df_clean[df_clean['거래처'].isin(selected_acc)] if selected_acc else df_clean
filter_label = ", ".join(selected_acc) if selected_acc else "전체"

st.divider()

# 기간 선택 로직
available_years = sorted(df_filtered['Year'].unique(), reverse=True)
if not available_years:
    st.error("데이터 없음")
    st.stop()

c1, c2 = st.columns(2)
target_df = pd.DataFrame()
ref_df = pd.DataFrame()
chart_title = ""
quarters_map = {"1분기": [1,2,3], "2분기": [4,5,6], "3분기": [7,8,9], "4분기": [10,11,12]}

if view_mode == "월별":
    with c1:
        t_year = st.selectbox("Target 연도", available_years, index=0)
        t_month = st.selectbox("Target 월", range(1, 13))
    with c2:
        ref_idx = available_years.index(t_year-1) if (t_year-1) in available_years else 0
        r_year = st.selectbox("Ref 연도", available_years, index=ref_idx)
        r_month = st.selectbox("Ref 월", range(1, 13), index=t_month-1)
    target_df = df_filtered[(df_filtered['Year'] == t_year) & (df_filtered['Month'] == t_month)]
    ref_df = df_filtered[(df_filtered['Year'] == r_year) & (df_filtered['Month'] == r_month)]
    chart_title = f"{t_year}.{t_month} vs {r_year}.{r_month}"

elif view_mode == "분기별":
    q_list = list(quarters_map.keys())
    with c1:
        t_year = st.selectbox("Target 연도", available_years, index=0)
        t_q = st.selectbox("Target 분기", q_list)
    with c2:
        ref_idx = available_years.index(t_year-1) if (t_year-1) in available_years else 0
        r_year = st.selectbox("Ref 연도", available_years, index=ref_idx)
        r_q = st.selectbox("Ref 분기", q_list, index=q_list.index(t_q))
    target_df = df_filtered[(df_filtered['Year'] == t_year) & (df_filtered['Month'].isin(quarters_map[t_q]))]
    ref_df = df_filtered[(df_filtered['Year'] == r_year) & (df_filtered['Month'].isin(quarters_map[r_q]))]
    chart_title = f"{t_year} {t_q} vs {r_year} {r_q}"

# ... (주별, 연간은 로직 동일, 생략하고 기존대로 처리) ...
elif view_mode == "주별":
    with c1:
        t_year = st.selectbox("Target 연도", available_years)
        t_week = st.selectbox("Target 주차", sorted(df_filtered[df_filtered['Year']==t_year]['Week'].unique()))
    with c2:
        ref_idx = available_years.index(t_year-1) if (t_year-1) in available_years else 0
        r_year = st.selectbox("Ref 연도", available_years, index=ref_idx)
        r_week = st.selectbox("Ref 주차", range(1, 54), index=int(min(t_week-1, 52)))
    target_df = df_filtered[(df_filtered['Year'] == t_year) & (df_filtered['Week'] == t_week)]
    ref_df = df_filtered[(df_filtered['Year'] == r_year) & (df_filtered['Week'] == r_week)]
    chart_title = f"{t_year} {t_week}주 vs {r_year} {r_week}주"

else: # 연간
    with c1: t_year = st.selectbox("Target 연도", available_years)
    with c2: r_year = st.selectbox("Ref 연도", available_years, index=available_years.index(t_year-1) if (t_year-1) in available_years else 0)
    target_df = df_filtered[df_filtered['Year'] == t_year]
    ref_df = df_filtered[df_filtered['Year'] == r_year]
    chart_title = f"{t_year} 전체 vs {r_year} 전체"


# ==============================================================================
# 🌟 [New] 4개의 탭으로 구성된 분석 대시보드
# ==============================================================================
if target_df.empty:
    st.warning("선택한 기간에 데이터가 없습니다.")
    st.stop()

tab1, tab2, tab3, tab4 = st.tabs([
    "💰 매출 페이스 (Revenue)", 
    "💳 객단가 페이스 (ADR)", 
    "⏳ 리드타임 분포 (Lead Time)",
    "📅 요일별 분석 (Day of Week)"
])

# --- TAB 1: Revenue Pace (기존 기능) ---
with tab1:
    st.subheader(f"매출 속도 비교: {chart_title}")
    
    def get_pace(d, col='총금액'):
        if d.empty: return pd.Series(dtype=float)
        return d.groupby('LeadTime')[col].sum().sort_index(ascending=False).cumsum().sort_index()

    rev_t = get_pace(target_df)
    rev_r = get_pace(ref_df)

    fig1 = go.Figure()
    fig1.add_trace(go.Scatter(x=rev_t.index, y=rev_t.values, mode='lines', name=f'Target', line=dict(color='#0052cc', width=3)))
    if not rev_r.empty:
        fig1.add_trace(go.Scatter(x=rev_r.index, y=rev_r.values, mode='lines', name=f'Ref', line=dict(color='gray', dash='dot')))
    
    # 마커
    if not rev_t.empty:
        last_pt = rev_t.index.min()
        fig1.add_trace(go.Scatter(x=[last_pt], y=[rev_t[last_pt]], mode='markers+text', 
                                  text=[f"{rev_t[last_pt]/10000:,.0f}만"], textposition="top left", marker=dict(color='red', size=8), showlegend=False))

    fig1.update_layout(xaxis_title="D-Day (Lead Time)", yaxis_title="누적 매출", xaxis={'autorange': 'reversed'}, height=500)
    st.plotly_chart(fig1, use_container_width=True)

# --- TAB 2: ADR Pace (신규 기능) ---
with tab2:
    st.subheader(f"평균 객단가(ADR) 비교: {chart_title}")
    st.caption("누적 매출 / 누적 객실수 = 현재 시점의 평균 단가")

    # ADR 계산 로직: (누적 매출) / (누적 객실수)
    def get_adr_pace(d):
        if d.empty: return pd.Series(dtype=float)
        cum_rev = d.groupby('LeadTime')['총금액'].sum().sort_index(ascending=False).cumsum().sort_index()
        cum_rms = d.groupby('LeadTime')['객실수'].sum().sort_index(ascending=False).cumsum().sort_index()
        return (cum_rev / cum_rms).fillna(0)

    adr_t = get_adr_pace(target_df)
    adr_r = get_adr_pace(ref_df)

    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(x=adr_t.index, y=adr_t.values, mode='lines', name='Target ADR', line=dict(color='#ff6b6b', width=3)))
    if not adr_r.empty:
        fig2.add_trace(go.Scatter(x=adr_r.index, y=adr_r.values, mode='lines', name='Ref ADR', line=dict(color='gray', dash='dot')))

    fig2.update_layout(xaxis_title="D-Day", yaxis_title="평균 객단가 (ADR)", xaxis={'autorange': 'reversed'}, height=500)
    st.plotly_chart(fig2, use_container_width=True)

# --- TAB 3: Lead Time Distribution (신규 기능) ---
with tab3:
    st.subheader("예약 시점 분포 (언제 예약했는가?)")
    
    # 리드타임 구간 설정
    bins = [-1, 0, 3, 7, 14, 30, 60, 90, 999]
    labels = ['당일(0)', '1-3일전', '4-7일전', '8-14일전', '15-30일전', '31-60일전', '61-90일전', '90일이상']
    
    target_df['LeadGroup'] = pd.cut(target_df['LeadTime'], bins=bins, labels=labels)
    ref_df['LeadGroup'] = pd.cut(ref_df['LeadTime'], bins=bins, labels=labels)
    
    # 집계
    t_grp = target_df.groupby('LeadGroup')['총금액'].sum().reset_index()
    t_grp['Type'] = 'Target'
    r_grp = ref_df.groupby('LeadGroup')['총금액'].sum().reset_index()
    r_grp['Type'] = 'Ref'
    
    combined_grp = pd.concat([t_grp, r_grp])
    
    fig3 = px.bar(combined_grp, x='LeadGroup', y='총금액', color='Type', barmode='group',
                  color_discrete_map={'Target': '#0052cc', 'Ref': '#bababa'},
                  title="구간별 매출 발생량 비교")
    st.plotly_chart(fig3, use_container_width=True)

# --- TAB 4: Day of Week (신규 기능) ---
with tab4:
    st.subheader("요일별 매출 퍼포먼스")
    
    # 요일 순서 정렬
    days_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    
    # 집계
    t_dow = target_df.groupby('DayOfWeek')['총금액'].mean().reindex(days_order).reset_index() # 평균 매출
    r_dow = ref_df.groupby('DayOfWeek')['총금액'].mean().reindex(days_order).reset_index()
    
    fig4 = go.Figure()
    fig4.add_trace(go.Scatter(x=t_dow['DayOfWeek'], y=t_dow['총금액'], mode='lines+markers', name='Target (평균)', line=dict(color='green', width=3)))
    fig4.add_trace(go.Scatter(x=r_dow['DayOfWeek'], y=r_dow['총금액'], mode='lines+markers', name='Ref (평균)', line=dict(color='gray', dash='dot')))
    
    fig4.update_layout(title="요일별 일평균 매출 비교", yaxis_title="일평균 매출")
    st.plotly_chart(fig4, use_container_width=True)
    st.caption("* 해당 기간 동안 각 요일별로 평균 얼마를 벌었는지 보여줍니다.")

# -----------------------------------------------------------------------------
# 검증기 (맨 아래)
# -----------------------------------------------------------------------------
st.divider()
with st.expander("🕵️‍♂️ 데이터 검증용 상세 리스트 보기"):
    st.dataframe(target_df[['입실일자','예약일자','거래처','상태','객실수','총금액']].head(100))
