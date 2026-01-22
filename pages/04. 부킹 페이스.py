import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
import os

# -----------------------------------------------------------------------------
# 1. 환경 설정 및 데이터 로드 함수
# -----------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Booking Pace Manager")
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
                # 파일 읽기
                if file.name.endswith('.csv'):
                    df = pd.read_csv(file, header=2)
                else:
                    df = pd.read_excel(file, header=2)
                
                # 필수 컬럼 체크
                required = ['입실일자', '예약일자', '총금액', '상태', '예약번호', '거래처']
                if set(required).issubset(df.columns):
                    all_new_data.append(df)
            except Exception as e:
                st.error(f"파일 로드 오류 ({file.name}): {e}")

    df_new = pd.concat(all_new_data, ignore_index=True) if all_new_data else pd.DataFrame()

    # 3. 병합 (Base + New)
    if df_base.empty and df_new.empty:
        return pd.DataFrame()
    
    # 병합 전 날짜 처리 (에러 방지)
    def safe_to_datetime(series):
        return pd.to_datetime(series, errors='coerce')

    if not df_base.empty:
        df_base['입실일자'] = safe_to_datetime(df_base['입실일자'])
        df_base['예약일자'] = safe_to_datetime(df_base['예약일자'])
    if not df_new.empty:
        df_new['입실일자'] = safe_to_datetime(df_new['입실일자'])
        df_new['예약일자'] = safe_to_datetime(df_new['예약일자'])
        
        if df_new['총금액'].dtype == object:
            df_new['총금액'] = df_new['총금액'].astype(str).str.replace(',', '').astype(float)
        
    # 합치기
    df_master = pd.concat([df_base, df_new], ignore_index=True)
    
    # 날짜 없는 행 삭제
    df_master = df_master.dropna(subset=['입실일자', '예약일자'])

    # 중복 제거 (최신 데이터 우선)
    df_master = df_master.drop_duplicates(subset=['예약번호'], keep='last')
    
    # 파생 변수 생성
    df_master['LeadTime'] = (df_master['입실일자'] - df_master['예약일자']).dt.days
    df_master['Year'] = df_master['입실일자'].dt.isocalendar().year.astype(int)
    df_master['Week'] = df_master['입실일자'].dt.isocalendar().week.astype(int)
    df_master['Month'] = df_master['입실일자'].dt.month.astype(int)
    
    # 거래처 공백 처리
    df_master['거래처'] = df_master['거래처'].fillna('Direct/Unknown').astype(str).str.strip()
    
    return df_master

# -----------------------------------------------------------------------------
# 2. 사이드바 (데이터 & 필터)
# -----------------------------------------------------------------------------
with st.sidebar:
    st.header("📂 Data Center")
    
    # A. 데이터 관리
    with st.expander("데이터 업로드/저장", expanded=True):
        new_history = st.file_uploader("과거 데이터(저장용)", accept_multiple_files=True, key='history')
        if new_history and st.button("과거 데이터 저장하기"):
            temp_df = pd.DataFrame()
            for f in new_history:
                try:
                    d = pd.read_csv(f, header=2) if f.name.endswith('.csv') else pd.read_excel(f, header=2)
                    temp_df = pd.concat([temp_df, d])
                except Exception as e:
                    st.error(f"저장 중 에러: {e}")
            
            if not temp_df.empty:
                temp_df.to_csv(DATA_FILE_PATH, index=False)
                st.success(f"저장 완료! (총 {len(temp_df)}건)")
                st.rerun()

        daily_files = st.file_uploader("오늘 데이터(분석용)", accept_multiple_files=True, key='daily')

# 데이터 로드
df = load_and_merge_data(DATA_FILE_PATH, daily_files)

if df.empty:
    st.info("👈 왼쪽 사이드바에서 데이터를 업로드해주세요.")
    st.stop()

# -----------------------------------------------------------------------------
# [New] 예약 상태 필터링 (RC, RX 자동 포함)
# -----------------------------------------------------------------------------
with st.sidebar:
    st.divider()
    st.header("🚫 상태 필터 (취소 제외)")
    
    all_statuses = df['상태'].unique().astype(str)
    
    # RC, RX, 취소 등 키워드 포함시 자동 선택
    cancel_keywords = ['취소', 'CXL', 'CANCEL', 'NO', 'NOSHOW', 'RC', 'RX']
    default_excludes = [s for s in all_statuses if any(x in s.upper() for x in cancel_keywords)]
    
    exclude_statuses = st.multiselect(
        "매출에서 제외할 상태값",
        options=all_statuses,
        default=default_excludes
    )
    
# 필터 적용
df_clean = df[~df['상태'].isin(exclude_statuses)]

# -----------------------------------------------------------------------------
# 3. 메인 대시보드
# -----------------------------------------------------------------------------
st.title("📈 Booking Pace Analysis")

st.markdown("### 🔍 Filter Condition")
col_filter1, col_filter2 = st.columns([1, 2])

with col_filter1:
    # [업데이트] 분기별 옵션 추가
    view_mode = st.radio("분석 기간 단위", ["월별 (Monthly)", "분기별 (Quarterly)", "주별 (Weekly)", "연간 (Yearly)"], horizontal=True)

with col_filter2:
    all_accounts = sorted(df_clean['거래처'].unique())
    selected_acc = st.multiselect(
        "분석할 거래처 선택 (이름이 다르면 모두 선택해야 합니다!)", 
        options=all_accounts,
        default=[],
        placeholder="예: Booking.com, 부킹닷컴, Expedia, 익스피디아..."
    )

if selected_acc:
    df_filtered = df_clean[df_clean['거래처'].isin(selected_acc)]
    filter_label = ", ".join(selected_acc)
    if len(filter_label) > 30: filter_label = f"{len(selected_acc)}개 거래처"
else:
    df_filtered = df_clean
    filter_label = "전체 (Total)"

st.divider()

# -----------------------------------------------------------------------------
# 4. 차트 그리기
# -----------------------------------------------------------------------------
available_years = sorted(df_filtered['Year'].unique(), reverse=True)

if not available_years:
    st.error("데이터가 없습니다. 날짜나 필터를 확인해주세요.")
    st.stop()

c1, c2 = st.columns(2)
target_df = pd.DataFrame()
ref_df = pd.DataFrame()
chart_sub_title = ""

# --- [로직 추가] 분기 정의 ---
quarters_map = {
    "1분기 (1~3월)": [1, 2, 3],
    "2분기 (4~6월)": [4, 5, 6],
    "3분기 (7~9월)": [7, 8, 9],
    "4분기 (10~12월)": [10, 11, 12]
}

# 날짜 선택 UI
if view_mode == "월별 (Monthly)":
    with c1:
        t_year = st.selectbox("Target 연도", available_years, index=0)
        t_month = st.selectbox("Target 월", range(1, 13))
    with c2:
        ref_idx = available_years.index(t_year-1) if (t_year-1) in available_years else (1 if len(available_years)>1 else 0)
        r_year = st.selectbox("Reference 연도", available_years, index=ref_idx)
        r_month = st.selectbox("Reference 월", range(1, 13), index=t_month-1)
    
    target_df = df_filtered[(df_filtered['Year'] == t_year) & (df_filtered['Month'] == t_month)]
    ref_df = df_filtered[(df_filtered['Year'] == r_year) & (df_filtered['Month'] == r_month)]
    chart_sub_title = f"{t_year}.{t_month} vs {r_year}.{r_month}"

elif view_mode == "분기별 (Quarterly)":
    quarter_list = list(quarters_map.keys())
    with c1:
        t_year = st.selectbox("Target 연도", available_years, index=0)
        t_q = st.selectbox("Target 분기", quarter_list, index=0)
    with c2:
        ref_idx = available_years.index(t_year-1) if (t_year-1) in available_years else (1 if len(available_years)>1 else 0)
        r_year = st.selectbox("Ref 연도", available_years, index=ref_idx)
        r_q = st.selectbox("Ref 분기", quarter_list, index=quarter_list.index(t_q))
    
    # 해당 분기의 월(Month) 리스트로 필터링
    t_months = quarters_map[t_q]
    r_months = quarters_map[r_q]
    
    target_df = df_filtered[(df_filtered['Year'] == t_year) & (df_filtered['Month'].isin(t_months))]
    ref_df = df_filtered[(df_filtered['Year'] == r_year) & (df_filtered['Month'].isin(r_months))]
    chart_sub_title = f"{t_year}년 {t_q} vs {r_year}년 {r_q}"

elif view_mode == "주별 (Weekly)":
    with c1:
        t_year = st.selectbox("Target 연도", available_years, index=0)
        weeks_in_year = sorted(df_filtered[df_filtered['Year']==t_year]['Week'].unique())
        if not weeks_in_year: weeks_in_year = range(1, 53)
        t_week = st.selectbox("Target 주차 (Week)", weeks_in_year)
        
    with c2:
        ref_idx = available_years.index(t_year-1) if (t_year-1) in available_years else (1 if len(available_years)>1 else 0)
        r_year = st.selectbox("Ref 연도", available_years, index=ref_idx)
        valid_idx = int(min(t_week-1, 52))
        r_week = st.selectbox("Ref 주차 (Week)", range(1, 54), index=valid_idx)

    target_df = df_filtered[(df_filtered['Year'] == t_year) & (df_filtered['Week'] == t_week)]
    ref_df = df_filtered[(df_filtered['Year'] == r_year) & (df_filtered['Week'] == r_week)]
    chart_sub_title = f"{t_year}년 {t_week}주 vs {r_year}년 {r_week}주"

else: # 연간
    with c1:
        t_year = st.selectbox("Target 연도", available_years, index=0)
    with c2:
        ref_idx = available_years.index(t_year-1) if (t_year-1) in available_years else (1 if len(available_years)>1 else 0)
        r_year = st.selectbox("Reference 연도", available_years, index=ref_idx)
    
    target_df = df_filtered[df_filtered['Year'] == t_year]
    ref_df = df_filtered[df_filtered['Year'] == r_year]
    chart_sub_title = f"{t_year}년 전체 vs {r_year}년 전체"

# 그래프 생성
if not target_df.empty:
    st.subheader(f"📉 Booking Pace Curve [{filter_label}]")
    st.caption(f"비교 기간: {chart_sub_title}")
    
    def calculate_pace(d):
        if d.empty: return pd.Series(dtype=float)
        return d.groupby('LeadTime')['총금액'].sum().sort_index(ascending=False).cumsum().sort_index()

    pace_t = calculate_pace(target_df)
    pace_r = calculate_pace(ref_df)

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=pace_t.index, y=pace_t.values, mode='lines', name=f'Target ({t_year})', line=dict(color='#0052cc', width=3)))
    if not pace_r.empty:
        fig.add_trace(go.Scatter(x=pace_r.index, y=pace_r.values, mode='lines', name=f'Ref ({r_year})', line=dict(color='gray', dash='dot')))

    if not pace_t.empty:
        last_pt = pace_t.index.min()
        last_val = pace_t[last_pt]
        fig.add_trace(go.Scatter(x=[last_pt], y=[last_val], mode='markers+text',
            text=[f"{last_val/10000:,.0f}만"], textposition="top left", marker=dict(color='red', size=8), showlegend=False))

    fig.update_layout(xaxis_title="리드타임 (D-Day)", yaxis_title="누적 매출 (KRW)", xaxis=dict(autorange="reversed"), hovermode="x unified", height=500)
    st.plotly_chart(fig, use_container_width=True)
    
    # Summary
    st.markdown("#### 🔢 Summary")
    final_t_val = pace_t.values[-1]
    final_r_val = pace_r.values[-1] if not pace_r.empty else 0
    gap = final_t_val - final_r_val
    gap_pct = (gap / final_r_val * 100) if final_r_val != 0 else 0
    
    s1, s2, s3 = st.columns(3)
    s1.metric("Target 최종", f"{final_t_val:,.0f} 원")
    s2.metric("Ref 최종", f"{final_r_val:,.0f} 원")
    s3.metric("차이", f"{gap:,.0f} 원", f"{gap_pct:.1f}%")

    # ---------------------------------------------------------
    # 데이터 검증기
    # ---------------------------------------------------------
    st.divider()
    st.markdown("### 🕵️‍♂️ 데이터 검증")
    st.info("거래처 필터나 제외할 상태값을 확인할 때 아래 표를 참고하세요.")

    with st.expander("📄 Target 데이터 상세 보기", expanded=False):
        st.dataframe(target_df[['입실일자', '예약일자', '거래처', '상태', '총금액', '고객명']].sort_values('총금액', ascending=False), use_container_width=True)
        st.write(f"포함된 거래처: {target_df['거래처'].unique()}")

    with st.expander("📄 Reference 데이터 상세 보기", expanded=False):
        st.dataframe(ref_df[['입실일자', '예약일자', '거래처', '상태', '총금액', '고객명']].sort_values('총금액', ascending=False), use_container_width=True)
        st.write(f"포함된 거래처: {ref_df['거래처'].unique()}")

else:
    st.warning("선택하신 조건에 해당하는 예약 데이터가 없습니다.")
