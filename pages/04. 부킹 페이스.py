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
    
    # [수정됨] 병합 전 날짜 처리 (에러 방지 핵심!)
    # 날짜 변환 함수 (에러나면 NaT 처리)
    def safe_to_datetime(series):
        return pd.to_datetime(series, errors='coerce')

    if not df_base.empty:
        df_base['입실일자'] = safe_to_datetime(df_base['입실일자'])
        df_base['예약일자'] = safe_to_datetime(df_base['예약일자'])
    if not df_new.empty:
        df_new['입실일자'] = safe_to_datetime(df_new['입실일자'])
        df_new['예약일자'] = safe_to_datetime(df_new['예약일자'])
        
        # 신규 데이터 금액 전처리
        if df_new['총금액'].dtype == object:
            df_new['총금액'] = df_new['총금액'].astype(str).str.replace(',', '').astype(float)
        
        # 취소 필터링
        cancel_keywords = ['취소', 'CXL', 'CANCEL', 'NO SHOW']
        df_new = df_new[~df_new['상태'].astype(str).str.upper().apply(lambda x: any(k in x for k in cancel_keywords))]

    # 합치기
    df_master = pd.concat([df_base, df_new], ignore_index=True)
    
    # [중요] 날짜가 없는 행(오류 데이터)은 과감히 삭제 (에러 원인 제거)
    df_master = df_master.dropna(subset=['입실일자', '예약일자'])

    # 중복 제거 (최신 데이터 우선)
    df_master = df_master.drop_duplicates(subset=['예약번호'], keep='last')
    
    # 파생 변수 생성
    df_master['LeadTime'] = (df_master['입실일자'] - df_master['예약일자']).dt.days
    
    # Year/Week/Month 계산 (이제 날짜가 확실하므로 에러 안 남)
    df_master['Year'] = df_master['입실일자'].dt.isocalendar().year.astype(int)
    df_master['Week'] = df_master['입실일자'].dt.isocalendar().week.astype(int)
    df_master['Month'] = df_master['입실일자'].dt.month.astype(int)
    
    df_master['거래처'] = df_master['거래처'].fillna('Direct/Unknown')
    
    return df_master

# -----------------------------------------------------------------------------
# 2. 사이드바 (데이터 & 필터)
# -----------------------------------------------------------------------------
with st.sidebar:
    st.header("📂 Data Center")
    
    # A. 데이터 관리
    with st.expander("데이터 업로드/저장", expanded=True):
        # 과거 데이터 저장 로직
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
                # 전처리 후 저장
                temp_df['입실일자'] = pd.to_datetime(temp_df['입실일자'], errors='coerce')
                temp_df['예약일자'] = pd.to_datetime(temp_df['예약일자'], errors='coerce')
                # 날짜 없는 행 제거 후 저장
                temp_df = temp_df.dropna(subset=['입실일자'])
                
                if temp_df['총금액'].dtype == object:
                    temp_df['총금액'] = temp_df['총금액'].astype(str).str.replace(',', '').astype(float)
                
                cancel_k = ['취소', 'CXL', 'CANCEL']
                temp_df = temp_df[~temp_df['상태'].astype(str).str.upper().apply(lambda x: any(k in x for k in cancel_k))]
                
                temp_df.to_csv(DATA_FILE_PATH, index=False)
                st.success(f"저장 완료! (총 {len(temp_df)}건)")
                st.rerun()

        # 현재 데이터 업로드
        daily_files = st.file_uploader("오늘 데이터(분석용)", accept_multiple_files=True, key='daily')

# 데이터 로드 실행
df = load_and_merge_data(DATA_FILE_PATH, daily_files)

if df.empty:
    st.info("👈 왼쪽 사이드바에서 데이터를 업로드해주세요.")
    st.stop()

# -----------------------------------------------------------------------------
# 3. 메인 대시보드 (필터링 & 차트)
# -----------------------------------------------------------------------------
st.title("📈 Booking Pace Analysis")

# [핵심] 어카운트 필터링 UI (상단 배치)
st.markdown("### 🔍 Filter Condition")
col_filter1, col_filter2 = st.columns([1, 2])

with col_filter1:
    view_mode = st.radio("분석 기간 단위", ["월별 (Monthly)", "주별 (Weekly)", "연간 (Yearly)"], horizontal=True)

with col_filter2:
    # 거래처 리스트 추출
    all_accounts = sorted(df['거래처'].unique().astype(str))
    
    selected_acc = st.multiselect(
        "분석할 거래처 선택 (비워두면 '전체 매출'로 분석합니다)", 
        options=all_accounts,
        default=[],
        placeholder="여기를 클릭하여 부킹닷컴, 아고다 등을 선택하세요..."
    )

if selected_acc:
    df_filtered = df[df['거래처'].isin(selected_acc)]
    filter_label = ", ".join(selected_acc)
    if len(filter_label) > 30: filter_label = f"{len(selected_acc)}개 거래처"
else:
    df_filtered = df
    filter_label = "전체 (Total)"

st.divider()

# -----------------------------------------------------------------------------
# 4. 차트 그리기 (Target vs Reference)
# -----------------------------------------------------------------------------
# 연도 추출 (NaN 제거하고 int로 변환)
available_years = sorted(df_filtered['Year'].unique(), reverse=True)

# 데이터가 너무 없어서 연도가 안 잡히는 경우 방지
if not available_years:
    st.error("유효한 날짜 데이터가 없습니다. 파일을 확인해주세요.")
    st.stop()

c1, c2 = st.columns(2)

target_df = pd.DataFrame()
ref_df = pd.DataFrame()
chart_sub_title = ""

# 뷰 모드에 따른 데이터 슬라이싱
if view_mode == "월별 (Monthly)":
    with c1:
        t_year = st.selectbox("Target 연도", available_years, index=0)
        t_month = st.selectbox("Target 월", range(1, 13))
    with c2:
        # Ref 연도 자동 선택 로직 강화
        ref_idx = available_years.index(t_year-1) if (t_year-1) in available_years else (1 if len(available_years)>1 else 0)
        r_year = st.selectbox("Reference 연도", available_years, index=ref_idx)
        r_month = st.selectbox("Reference 월", range(1, 13), index=t_month-1)
    
    target_df = df_filtered[(df_filtered['Year'] == t_year) & (df_filtered['Month'] == t_month)]
    ref_df = df_filtered[(df_filtered['Year'] == r_year) & (df_filtered['Month'] == r_month)]
    chart_sub_title = f"{t_year}.{t_month} vs {r_year}.{r_month}"

elif view_mode == "주별 (Weekly)":
    with c1:
        t_year = st.selectbox("Target 연도", available_years, index=0)
        # 해당 연도에 데이터가 있는 주차만 표시
        weeks_in_year = sorted(df_filtered[df_filtered['Year']==t_year]['Week'].unique())
        if not weeks_in_year: weeks_in_year = range(1, 53)
        
        t_week = st.selectbox("Target 주차 (Week)", weeks_in_year)
    with c2:
        ref_idx = available_years.index(t_year-1) if (t_year-1) in available_years else (1 if len(available_years)>1 else 0)
        r_year = st.selectbox("Ref 연도", available_years, index=ref_idx)
        
        # Ref 주차도 데이터가 있는 것 위주로 하되, 없으면 Target과 같은 주차
        r_week = st.selectbox("Ref 주차 (Week)", range(1, 54), index=min(t_week-1, 52))

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
    
    # 페이스 계산 함수 (누적 합계)
    def calculate_pace(d):
        if d.empty: return pd.Series(dtype=float)
        # 리드타임 내림차순 정렬 -> 누적합 -> 다시 원래대로
        return d.groupby('LeadTime')['총금액'].sum().sort_index(ascending=False).cumsum().sort_index()

    pace_t = calculate_pace(target_df)
    pace_r = calculate_pace(ref_df)

    fig = go.Figure()
    
    # 1. Target Line (올해/선택한 기간)
    fig.add_trace(go.Scatter(
        x=pace_t.index, y=pace_t.values, 
        mode='lines', 
        name=f'Target ({t_year})', 
        line=dict(color='#0052cc', width=3)
    ))
    
    # 2. Reference Line (작년/비교 기간)
    if not pace_r.empty:
        fig.add_trace(go.Scatter(
            x=pace_r.index, y=pace_r.values, 
            mode='lines', 
            name=f'Ref ({r_year})', 
            line=dict(color='gray', dash='dot')
        ))

    # 3. 현재 시점 마커 (Target의 끝점)
    if not pace_t.empty:
        last_pt = pace_t.index.min()
        last_val = pace_t[last_pt]
        fig.add_trace(go.Scatter(
            x=[last_pt], y=[last_val],
            mode='markers+text',
            text=[f"{last_val/10000:,.0f}만"],
            textposition="top left",
            marker=dict(color='red', size=8),
            showlegend=False
        ))

    fig.update_layout(
        xaxis_title="리드타임 (D-Day, 오른쪽이 투숙일)",
        yaxis_title="누적 매출 (KRW)",
        xaxis=dict(autorange="reversed"), # D-90 -> D-0 순서
        hovermode="x unified",
        height=550
    )
    st.plotly_chart(fig, use_container_width=True)
    
    # [추가 정보] 수치 요약
    st.markdown("#### 🔢 Summary")
    
    final_t_val = pace_t.values[-1] # 누적의 끝값(실제 총합)
    final_r_val = pace_r.values[-1] if not pace_r.empty else 0
    
    gap = final_t_val - final_r_val
    gap_pct = (gap / final_r_val * 100) if final_r_val != 0 else 0
    
    col_sum1, col_sum2, col_sum3 = st.columns(3)
    col_sum1.metric("Target 최종 예약고", f"{final_t_val:,.0f} 원")
    col_sum2.metric("Ref 최종 예약고", f"{final_r_val:,.0f} 원")
    col_sum3.metric("차이 (Gap)", f"{gap:,.0f} 원", f"{gap_pct:.1f}%")

else:
    st.warning("선택하신 조건에 해당하는 예약 데이터가 없습니다.")
