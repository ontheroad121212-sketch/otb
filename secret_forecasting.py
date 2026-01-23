import streamlit as st
import pandas as pd
from datetime import datetime

def run_forecasting():
    st.title("🎯 AI Smart Forecasting Lab")
    st.caption("가속도 인자(Accel Factor)를 반영한 지능형 예측 모델입니다.")
    st.markdown("---")

    selected_month = st.sidebar.selectbox("분석 대상 월 선택", range(1, 13), index=datetime.now().month - 1)
    target_sob = st.session_state.get(f"sob_{selected_month}")
    target_pace = st.session_state.get(f"pace_{selected_month}", 0)

    if target_sob is None:
        st.warning(f"📂 {selected_month}월 분석 데이터가 없습니다.")
        st.info("메인 리포트에서 해당 월의 탭을 먼저 클릭하여 데이터를 로드해주세요.")
        return

    try:
        current_occ = float(target_sob.get('TOTAL_OCC', 0))
        total_otb = float(target_sob.get('FIT_RMS', 0) + target_sob.get('GRP_RMS', 0))
        base_pace = float(target_pace)
    except Exception as e:
        st.error(f"데이터 처리 중 오류 발생: {e}")
        return

    st.subheader(f"📊 {selected_month}월 OTB 현황")
    c1, c2, c3 = st.columns(3)
    c1.metric("현재 점유율", f"{current_occ:.1f}%")
    c2.metric("확정 예약실(OTB)", f"{int(total_otb)} Rms")
    c3.metric("최근 일평균 Pace", f"{base_pace:+,.1f} Rms")

    st.markdown("### 🔮 Forecasting Simulation")
    with st.container(border=True):
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            accel_factor = st.slider("🚀 예약 가속도 (Accel Factor)", 0.5, 2.0, 1.2)
            calc_pace = base_pace * accel_factor
        with col_b:
            rem_days = st.number_input("남은 분석 기간 (Days)", value=15, min_value=1)
        with col_c:
            washout = st.slider("예상 취소율(%)", 0, 30, 5)

    projected_add = calc_pace * rem_days
    final_forecast = (total_otb + projected_add) * (1 - washout/100)

    st.divider()
    res_c1, res_c2 = st.columns(2)
    with res_c1:
        st.metric("최종 예상 점유 객실", f"{int(final_forecast)} Rms", 
                  delta=f"{int(final_forecast - total_otb)} Rms 증감 예상")
        progress_val = min(1.0, final_forecast / 150)
        st.progress(progress_val, text=f"예상 점유율: {int(progress_val * 100)}%")
    with res_c2:
        st.write("**Scenario Comparison**")
        comparison_data = {
            "Scenario": ["Worst (-50%)", "Base (Current)", "Best (+50%)"],
            "Projected RMS": [
                int((total_otb + (projected_add * 0.5)) * 0.9),
                int(final_forecast),
                int((total_otb + (projected_add * 1.5)) * 0.98)
            ]
        }
        st.table(pd.DataFrame(comparison_data))
