import streamlit as st
import pandas as pd
from datetime import datetime

def run_forecasting():
    st.title("🎯 AI Smart Forecasting Lab v2.0")
    st.caption("가속도 보정 및 역산 타겟팅 로직이 적용된 실전형 모델입니다.")
    st.markdown("---")

    # 1. 데이터 호출 및 안전장치
    selected_month = st.sidebar.selectbox("분석 대상 월 선택", range(1, 13), index=datetime.now().month - 1)
    target_sob = st.session_state.get(f"sob_{selected_month}")
    target_pace = st.session_state.get(f"pace_{selected_month}", 0)

    if target_sob is None:
        st.warning(f"📂 {selected_month}월 분석 데이터가 없습니다.")
        st.info("메인 리포트에서 해당 월의 탭을 먼저 클릭하여 데이터를 로드해주세요.")
        return

    # 2. 기본 지표 파싱
    current_occ = float(target_sob.get('TOTAL_OCC', 0))
    fit_rms = float(target_sob.get('FIT_RMS', 0))
    grp_rms = float(target_sob.get('GRP_RMS', 0))
    total_otb = fit_rms + grp_rms
    base_pace = float(target_pace)

    # 3. 전략적 변수 설정 (가속도 및 목표 설정)
    st.subheader("🔮 시뮬레이션 및 목표 역산")
    with st.container(border=True):
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            accel_factor = st.slider("🚀 예약 가속도 (Accel Factor)", 0.5, 3.0, 1.2, help="리드타임이 짧을수록 가중치를 높이세요.")
            calc_pace = base_pace * accel_factor
        with col_b:
            rem_days = st.number_input("남은 분석 기간 (Days)", value=7, min_value=1)
            total_inventory = 150 # 호텔 전체 객실수 (사용자 환경에 맞게 수정)
        with col_c:
            monthly_goal_rev = st.number_input("월 매출 목표 (₩)", value=500000000, step=10000000)

    # 4. 정밀 예측 로직 (마이너스 방지 및 가중치 적용)
    # 
    projected_pickup = max(0, calc_pace * rem_days) # 마이너스 픽업 방지 로직
    expected_final_rms = total_otb + projected_pickup
    
    # 5. 결과 리포트 (시각적 피드백 강화)
    st.divider()
    res_c1, res_c2 = st.columns(2)
    
    with res_c1:
        st.write("### 🚀 실시간 예측 결과")
        st.metric("최종 예상 점유실", f"{int(expected_final_rms)} Rms", 
                  delta=f"{int(expected_final_rms - total_otb)} Rms (추가 확보 예상)")
        
        occ_rate = (expected_final_rms / (total_inventory * 30)) * 100 # 월간 점유율 환산
        st.write(f"**예상 월간 점유율: {occ_rate:.1f}%**")
        st.progress(min(1.0, occ_rate/100))

    with res_c2:
        st.write("### 🎯 전략 가이드 (Targeting)")
        # 목표 달성을 위해 남은 기간 동안 하루에 팔아야 할 객실 수 역산
        current_rev = float(target_sob.get('FIT_REV', 0) + target_sob.get('GRP_REV', 0))
        rem_rev_goal = max(0, monthly_goal_rev - current_rev)
        
        if rem_rev_goal > 0:
            required_daily_rms = (rem_rev_goal / 150000) / rem_days # 평균단가 15만원 가정 시
            st.error(f"목표까지 부족분: ₩{rem_rev_goal:,.0f}")
            st.info(f"💡 앞으로 매일 **{int(required_daily_rms)}실** 이상 판매해야 목표 달성 가능합니다.")
        else:
            st.success("🎉 축하합니다! 이미 이번 달 매출 목표를 달성했습니다.")

    # 6. 세그먼트별 시나리오
    st.divider()
    st.write("**Scenario Comparison**")
    comparison_data = {
        "구분": ["최악 (가속도 0.5)", "현재 유지 (가속도 1.0)", "최상 (가속도 2.0)"],
        "예상 점유 객실": [
            int(total_otb + (base_pace * 0.5 * rem_days)),
            int(total_otb + (base_pace * 1.0 * rem_days)),
            int(total_otb + (base_pace * 2.0 * rem_days))
        ]
    }
    st.table(pd.DataFrame(comparison_data))

if __name__ == "__main__":
    run_forecasting()
