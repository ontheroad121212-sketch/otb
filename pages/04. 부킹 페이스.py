import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta

# -----------------------------------------------------------------------------
# 1. 데이터 로드 및 전처리 함수 (헤더 2줄 스킵 적용)
# -----------------------------------------------------------------------------
@st.cache_data
def load_booking_data(file):
    # CSV 파일 읽기 (위 2줄은 메타데이터이므로 건너뜀: header=2)
    # 엑셀(.xlsx) 원본이라면 read_excel로, CSV라면 read_csv로 읽습니다.
    try:
        if file.name.endswith('.csv'):
            df = pd.read_csv(file, header=2)
        else:
            df = pd.read_excel(file, header=2)
    except Exception as e:
        st.error(f"파일을 읽는 중 오류가 발생했습니다: {e}")
        return pd.DataFrame()

    # 필수 컬럼 존재 여부 확인
    required_cols = ['입실일자', '예약일자', '총금액', '상태']
    if not set(required_cols).issubset(df.columns):
        st.warning(f"필수 컬럼이 없습니다. 파일 양식을 확인해주세요. (필요 컬럼: {required_cols})")
        return pd.DataFrame()

    # 날짜 변환
    df['입실일자'] = pd.to_datetime(df['입실일자'], errors='coerce')
    df['예약일자'] = pd.to_datetime(df['예약일자'], errors='coerce')
    
    # 금액 숫자 변환 (콤마 제거 등)
    if df['총금액'].dtype == object:
        df['총금액'] = df['총금액'].astype(str).str.replace(',', '').astype(float)

    # 리드타임 계산 (투숙일 - 예약일)
    df['LeadTime'] = (df['입실일자'] - df['예약일자']).dt.days

    # '상태' 컬럼 정제 (취소된 건 제외하기 위함)
    # 실제 데이터에 '취소', 'CXL', 'Cancel' 등의 단어가 포함되면 제외
    cancel_keywords = ['취소', 'CXL', 'CANCEL', 'NO SHOW']
    # 상태 컬럼이 문자열인 경우만 필터링
    df = df[~df['상태'].astype(str).str.upper().apply(lambda x: any(k in x for k in cancel_keywords))]

    return df

# -----------------------------------------------------------------------------
# 2. 부킹 페이스 대시보드 UI
# -----------------------------------------------------------------------------
st.title("📈 Booking Pace & Pickup")
st.markdown("##### 2026년(Current) vs 2025년(Past) 예약 속도 비교")

col1, col2 = st.columns(2)
with col1:
    file_cur = st.file_uploader("📂 올해 데이터 (2026년 투숙 기준)", type=['csv', 'xlsx'], key='f1')
with col2:
    file_past = st.file_uploader("📂 작년 데이터 (2025년 투숙 기준)", type=['csv', 'xlsx'], key='f2')

if file_cur and file_past:
    df_cur = load_booking_data(file_cur)
    df_past = load_booking_data(file_past)

    if not df_cur.empty and not df_past.empty:
        
        # 분석할 월 선택 (데이터에 있는 월만 추출)
        available_months = sorted(df_cur['입실일자'].dt.month.unique())
        if not available_months:
            st.error("데이터에 유효한 날짜가 없습니다.")
            st.stop()
            
        selected_month = st.selectbox("📅 분석할 투숙 월(Month) 선택", available_months, format_func=lambda x: f"{x}월")

        # 선택한 월의 데이터 필터링
        cur_target = df_cur[df_cur['입실일자'].dt.month == selected_month]
        past_target = df_past[df_past['입실일자'].dt.month == selected_month]

        # ---------------------------------------------------------
        # [Chart 1] 부킹 커브 (Booking Curve)
        # ---------------------------------------------------------
        st.subheader(f"📉 {selected_month}월 부킹 커브 (누적 매출 속도)")
        
        # 리드타임별 누적 매출 집계 함수
        def calculate_pace(df):
            pace = df.groupby('LeadTime')['총금액'].sum().sort_index(ascending=False).cumsum()
            return pace.sort_index()

        pace_cur = calculate_pace(cur_target)
        pace_past = calculate_pace(past_target)

        fig_pace = go.Figure()
        fig_pace.add_trace(go.Scatter(x=pace_cur.index, y=pace_cur.values, mode='lines', name='2026 (Current)', line=dict(color='#0052cc', width=3)))
        fig_pace.add_trace(go.Scatter(x=pace_past.index, y=pace_past.values, mode='lines', name='2025 (STLY)', line=dict(color='#808080', dash='dot')))
        
        fig_pace.update_layout(
            xaxis_title="리드타임 (D-Day)",
            yaxis_title="누적 예약 매출 (KRW)",
            xaxis=dict(autorange="reversed"), # D-90 -> D-0 순서
            hovermode="x unified",
            height=500
        )
        st.plotly_chart(fig_pace, use_container_width=True)

        # ---------------------------------------------------------
        # [Chart 2] 픽업 차트 (Pickup - 최근 예약 유입)
        # ---------------------------------------------------------
        st.subheader("📊 최근 7일간 예약 유입 (Pickup)")
        
        # 오늘 날짜 기준 (파일 내 가장 최근 예약일 기준)
        last_booking_date = df_cur['예약일자'].max()
        pickup_start_date = last_booking_date - timedelta(days=7)
        
        # 최근 7일간 '생성된' 예약만 필터링
        pickup_data = df_cur[df_cur['예약일자'] > pickup_start_date]
        
        # 투숙 일자별로 묶어서 시각화
        pickup_summary = pickup_data.groupby('입실일자')['총금액'].sum().reset_index()
        
        fig_pickup = px.bar(pickup_summary, x='입실일자', y='총금액', 
                            title=f"최근 7일({pickup_start_date.date()} ~ {last_booking_date.date()}) 동안 들어온 예약",
                            labels={'총금액': '유입 매출', '입실일자': '투숙일자'},
                            color='총금액', color_continuous_scale='Blues')
        st.plotly_chart(fig_pickup, use_container_width=True)

        # ---------------------------------------------------------
        # [Table] 전년 대비 증감 (Variance Table)
        # ---------------------------------------------------------
        st.subheader("🗓️ 전년 대비 일별 증감표 (Variance)")
        
        # 일(Day)별 합계
        cur_day_sum = cur_target.groupby(cur_target['입실일자'].dt.day)['총금액'].sum()
        past_day_sum = past_target.groupby(past_target['입실일자'].dt.day)['총금액'].sum()
        
        var_df = pd.DataFrame({'2026 매출': cur_day_sum, '2025 매출': past_day_sum}).fillna(0)
        var_df['차액 (Gap)'] = var_df['2026 매출'] - var_df['2025 매출']
        var_df['달성률 (%)'] = (var_df['2026 매출'] / var_df['2025 매출'] * 100).round(1)
        
        # 스타일링 (숫자 포맷)
        st.dataframe(
            var_df.style.format("{:,.0f}", subset=['2026 매출', '2025 매출', '차액 (Gap)'])
                       .format("{:.1f}%", subset=['달성률 (%)'])
                       .background_gradient(subset=['차액 (Gap)'], cmap='RdYlGn', vmin=-1000000, vmax=1000000),
            use_container_width=True,
            height=400
        )

else:
    st.info("👆 위에서 2026년과 2025년 파일을 업로드해주세요.")
