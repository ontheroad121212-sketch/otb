import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta
import os

# 파일 저장 경로
DATA_FILE_PATH = 'saved_history_data.csv'

# ==========================================
# 1. 데이터 로드 및 전처리
# ==========================================
def process_files(files):
    all_data = []
    for file in files:
        try:
            if file.name.endswith('.csv'):
                df = pd.read_csv(file, header=2)
            else:
                df = pd.read_excel(file, header=2)
            
            # 필수 컬럼 체크
            required = ['입실일자', '예약일자', '총금액', '상태', '예약번호', '거래처']
            if set(required).issubset(df.columns):
                all_data.append(df)
        except Exception as e:
            st.error(f"❌ 파일 로드 실패: {file.name} - {e}")

    if not all_data:
        return pd.DataFrame()

    return pd.concat(all_data, ignore_index=True)

def preprocess_data(df):
    if df.empty: return df
    df = df.copy()

    # 날짜 변환
    df['입실일자'] = pd.to_datetime(df['입실일자'], errors='coerce')
    df['예약일자'] = pd.to_datetime(df['예약일자'], errors='coerce')
    
    # 금액 처리
    if df['총금액'].dtype == object:
        df['총금액'] = df['총금액'].astype(str).str.replace(',', '').astype(float)

    # 리드타임
    df['LeadTime'] = (df['입실일자'] - df['예약일자']).dt.days
    
    # 취소 제외
    cancel_keywords = ['취소', 'CXL', 'CANCEL', 'NO SHOW']
    df = df[~df['상태'].astype(str).str.upper().apply(lambda x: any(k in x for k in cancel_keywords))]
    
    # 주차(Week) 정보 추가 (ISO 기준)
    df['Year'] = df['입실일자'].dt.isocalendar().year
    df['Week'] = df['입실일자'].dt.isocalendar().week
    df['Month'] = df['입실일자'].dt.month
    
    # 거래처(Account) 빈 값 채우기
    df['거래처'] = df['거래처'].fillna('Direct/Unknown')

    return df

# ==========================================
# 2. 메인 화면
# ==========================================
st.set_page_config(layout="wide") # 넓은 화면 모드
st.title("🏨 Pro Booking Pace Analytics")
st.markdown("주별/월별/년별 분석 및 주요 채널 필터링 기능 탑재")

# --- [A] 데이터 업로드 섹션 ---
with st.sidebar:
    st.header("📂 데이터 관리")
    
    # 1. 과거 데이터 (저장소)
    if os.path.exists(DATA_FILE_PATH):
        st.success("✅ 과거 데이터 연동됨")
        if st.button("데이터 초기화"):
            os.remove(DATA_FILE_PATH)
            st.rerun()
    else:
        st.info("과거 데이터(24~25년)가 없습니다.")
        h_files = st.file_uploader("과거 데이터 업로드 (저장용)", accept_multiple_files=True)
        if h_files and st.button("저장하기"):
            raw = process_files(h_files)
            if not raw.empty:
                prep = preprocess_data(raw)
                prep.to_csv(DATA_FILE_PATH, index=False)
                st.rerun()

    # 2. 현재 데이터 (매일 업데이트)
    c_files = st.file_uploader("오늘 데이터 업로드 (2026년~)", accept_multiple_files=True)

# 데이터 병합 로직
df_base = pd.read_csv(DATA_FILE_PATH) if os.path.exists(DATA_FILE_PATH) else pd.DataFrame()
if not df_base.empty:
    df_base['입실일자'] = pd.to_datetime(df_base['입실일자'])
    df_base['예약일자'] = pd.to_datetime(df_base['예약일자'])

df_new = pd.DataFrame()
if c_files:
    raw_new = process_files(c_files)
    df_new = preprocess_data(raw_new)

if df_base.empty and df_new.empty:
    st.warning("데이터를 업로드해주세요.")
    st.stop()

df_master = pd.concat([df_base, df_new], ignore_index=True)
df_master = df_master.drop_duplicates(subset=['예약번호'], keep='last')

# --- [B] 필터링 섹션 (상단) ---
st.divider()
col_f1, col_f2, col_f3 = st.columns([1, 2, 1])

with col_f1:
    st.subheader("1. 분석 단위 (View)")
    view_mode = st.radio("기간 기준", ["월별 (Monthly)", "주별 (Weekly)", "연간 (Yearly)"], horizontal=True)

with col_f2:
    st.subheader("2. 어카운트 필터 (Account)")
    
    # 데이터에 있는 실제 거래처 리스트
    all_accounts = sorted(df_master['거래처'].unique().astype(str))
    
    # 주요 채널 키워드 (사용자가 요청한 것들)
    major_keywords = ['홈페이지', '부킹닷컴', '아고다', '익스피디아', '야놀자', '여기어때', '트립닷컴', '네이버']
    
    # 실제 데이터에서 키워드와 매칭되는 거래처 이름 찾기
    default_selections = []
    for acc in all_accounts:
        for kw in major_keywords:
            if kw in acc: # 예: '객실형광고-야놀자' 안에 '야놀자'가 포함됨
                default_selections.append(acc)
                break
    
    # 멀티 셀렉트 박스
    selected_accounts = st.multiselect(
        "포함할 거래처 선택 (기본: 주요 8대 채널)", 
        options=all_accounts,
        default=default_selections, # 기본적으로 주요 채널이 선택된 상태로 시작
        help="원하는 거래처를 추가하거나 뺄 수 있습니다."
    )

# 필터링 적용
if selected_accounts:
    df_filtered = df_master[df_master['거래처'].isin(selected_accounts)]
else:
    df_filtered = df_master # 아무것도 선택 안하면 전체

# --- [C] 타겟 설정 및 차트 ---
available_years = sorted(df_filtered['Year'].unique(), reverse=True)

st.divider()

# 뷰 모드에 따른 UI 분기
target_df = pd.DataFrame()
ref_df = pd.DataFrame()
chart_title = ""

# 컨트롤러 UI
c1, c2 = st.columns(2)

if view_mode == "월별 (Monthly)":
    with c1:
        t_year = st.selectbox("Target 연도", available_years, index=0)
        t_month = st.selectbox("Target 월", range(1, 13))
    with c2:
        r_year = st.selectbox("Ref 연도", available_years, index=1 if len(available_years)>1 else 0)
        r_month = st.selectbox("Ref 월", range(1, 13), index=t_month-1) # 동일 월 기본
        
    target_df = df_filtered[(df_filtered['Year'] == t_year) & (df_filtered['Month'] == t_month)]
    ref_df = df_filtered[(df_filtered['Year'] == r_year) & (df_filtered['Month'] == r_month)]
    chart_title = f"{t_year}년 {t_month}월 vs {r_year}년 {r_month}월"

elif view_mode == "주별 (Weekly)":
    with c1:
        t_year = st.selectbox("Target 연도", available_years, index=0)
        # 해당 연도에 존재하는 주차만 표시
        weeks_in_year = sorted(df_filtered[df_filtered['Year']==t_year]['Week'].unique())
        if not weeks_in_year: weeks_in_year = range(1, 53)
        t_week = st.selectbox("Target 주차 (Week)", weeks_in_year)
    with c2:
        r_year = st.selectbox("Ref 연도", available_years, index=1 if len(available_years)>1 else 0)
        r_week = st.selectbox("Ref 주차 (Week)", range(1, 54), index=t_week-1)
        
    target_df = df_filtered[(df_filtered['Year'] == t_year) & (df_filtered['Week'] == t_week)]
    ref_df = df_filtered[(df_filtered['Year'] == r_year) & (df_filtered['Week'] == r_week)]
    chart_title = f"{t_year}년 {t_week}주차 vs {r_year}년 {r_week}주차"

elif view_mode == "연간 (Yearly)":
    with c1:
        t_year = st.selectbox("Target 연도 (전체)", available_years, index=0)
    with c2:
        r_year = st.selectbox("Ref 연도 (전체)", available_years, index=1 if len(available_years)>1 else 0)
        
    target_df = df_filtered[df_filtered['Year'] == t_year]
    ref_df = df_filtered[df_filtered['Year'] == r_year]
    chart_title = f"{t_year}년 전체 vs {r_year}년 전체"

# --- 차트 그리기 ---
if not target_df.empty:
    
    # 1. 부킹 페이스 커브
    st.subheader(f"📉 Booking Pace: {chart_title}")
    
    def get_pace(df):
        if df.empty: return pd.Series(dtype=float)
        return df.groupby('LeadTime')['총금액'].sum().sort_index(ascending=False).cumsum().sort_index()

    pace_t = get_pace(target_df)
    pace_r = get_pace(ref_df)

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=pace_t.index, y=pace_t.values, mode='lines', name='Target', line=dict(color='#0052cc', width=3)))
    if not pace_r.empty:
        fig.add_trace(go.Scatter(x=pace_r.index, y=pace_r.values, mode='lines', name='Reference', line=dict(color='gray', dash='dot')))
    
    # 마커 (현재 달성액)
    if not pace_t.empty:
        last_pt = pace_t.index.min()
        current_rev = pace_t[last_pt]
        fig.add_trace(go.Scatter(x=[last_pt], y=[current_rev], mode='markers+text',
                                 text=[f"{current_rev/10000:,.0f}만"], textposition="top center",
                                 marker=dict(color='red', size=8), showlegend=False))

    fig.update_layout(xaxis_title="Lead Time (D-Day)", yaxis_title="누적 매출", 
                      xaxis={'autorange': 'reversed'}, height=500, hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True)

    # 2. 채널별 비중 (파이 차트) - 선택된 어카운트 내에서의 비중
    st.subheader("📊 선택된 채널 비중 (Target 기간)")
    channel_sum = target_df.groupby('거래처')['총금액'].sum().reset_index()
    if not channel_sum.empty:
        fig_pie = px.pie(channel_sum, values='총금액', names='거래처', hole=0.4)
        st.plotly_chart(fig_pie, use_container_width=True)

else:
    st.warning("선택하신 조건에 해당하는 데이터가 없습니다.")
