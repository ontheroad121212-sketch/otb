import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime

def run_forecasting():
    st.title("🎯 실전형 천재의 지능형 포캐스팅")
    st.caption("단순 계산을 넘어, 예약 가속도와 리드 타임을 반영한 정밀 예측 모델입니다.")
    st.markdown("---")

    selected_month = st.sidebar.selectbox("분석 대상 월", range(1, 13), index=datetime.now().month - 1)
    target_sob = st.session_state.get(f"sob_{selected_month}")
    target_pace = st.session_state.get(f"pace_{selected_month}", 0)

    if not target_sob:
        st.warning(f"📂 {selected_month}월 리포트 데이터가 없습니다. 먼저 메인 탭을 조회해 주세요.")
        return

    # [데이터 로드]
    current_occ = target_sob.get('TOTAL_OCC', 0)
    fit_rms = target_sob.get('FIT_RMS', 0)
    grp_rms = target_sob.get('GRP_RMS', 0)
    total_otb = fit_rms + grp_rms

    # --- 실전형 시뮬레이터 ---
    st.subheader("🔮 고도화 시나리오 설정")
    with st.expander("🛠️ 예측 파라미터 미세 조정", expanded=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            # 단순 Pace가 아닌 가속도(Acceleration) 개념 도입
            accel_factor = st.slider("예약 가속도 (1.0 = 현재 유지)", 0.5, 2.0, 1.2)
            adj_pace = target_pace * accel_factor
        with col2:
            rem_days = st.number_input("투숙까지 남은 평균 리드타임", value=14, min_value=1)
        with col3:
            # 세그먼트별 취소율 차등 적용
            fit_wash = st.slider("FIT 예상 취소율 (%)", 0, 20, 3)
            grp_wash = st.slider("Group 예상 취소율 (%)", 0, 50, 15)

    # --- 정밀 계산 로직 ---
    # 1. FIT 예상: (현재 FIT + (보정 페이스 * 남은날)) * (1 - FIT 취소율)
    # 2. Group 예상: 현재 Group OTB * (1 - Group 취소율) -> 단체는 보통 추가 픽업이 적으므로
    projected_fit = (fit_rms + (adj_pace * rem_days)) * (1 - fit_wash/100)
    projected_grp = grp_rms * (1 - grp_wash/100)
    final_forecast = projected_fit + projected_grp

    # --- 시각화 보고서 ---
    st.divider()
    res_c1, res_c2 = st.columns([1, 1])
    
    with res_c1:
        st.write("### 🚀 최종 예측 점유 (Forecast)")
        st.metric("예상 점유 객실", f"{int(final_forecast)} Rms", 
                  delta=f"{int(final_forecast - total_otb)} Rms (vs OTB)")
        
        # 목표 대비 달성률 시각화 (예: 월 목표 2500실 가정)
        goal = 2500 # 이 부분은 BUDGET_DATA 등을 활용해 자동화 가능
        st.progress(min(1.0, final_forecast / goal), text=f"월 목표 대비 예상 달성률: {int(final_forecast/goal*100)}%")

    with res_c2:
        st.write("### 📈 세그먼트별 비중")
        segment_df = pd.DataFrame({
            "Segment": ["FIT (개인)", "Group (단체)"],
            "Forecast Rms": [int(projected_fit), int(projected_grp)]
        })
        st.bar_chart(segment_df.set_index("Segment"))

    # --- 실질적 도움 메시지 ---
    st.info("💡 **천재 개발자의 인사이트:**\n"
            f"현재 페이스와 가속도를 고려할 때, {selected_month}월은 {'공격적인 가격 인상' if final_forecast > goal * 0.9 else '특가 프로모션'}이 필요한 시점입니다.")

if __name__ == "__main__":
    run_forecasting()
