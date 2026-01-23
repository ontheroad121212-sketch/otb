import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime

def run_forecasting():
    st.title("🎯 AI Smart Forecasting Lab v3.0")
    st.caption("Exponential Pickup 모델과 리드타임 보정 로직이 적용되었습니다.")
    st.markdown("---")

    # 1. 데이터 로드 및 검증
    selected_month = st.sidebar.selectbox("분석 대상 월 선택", range(1, 13), index=datetime.now().month - 1)
    target_sob = st.session_state.get(f"sob_{selected_month}")
    target_pace = st.session_state.get(f"pace_{selected_month}", 0)

    if target_sob is None:
        st.warning(f"📂 {selected_month}월 리포트 데이터가 캐시에 없습니다.")
        st.info("메인 리포트 탭에서 해당 월의 데이터를 먼저 분석해주세요.")
        return

    # 2. 핵심 지표 파싱
    fit_rms = float(target_sob.get('FIT_RMS', 0))
    grp_rms = float(target_sob.get('GRP_RMS', 0))
    total_otb = fit_rms + grp_rms
    base_pace = max(0.1, float(target_pace)) # 마이너스 방지

    # 3. 지능형 시뮬레이션 설정
    st.subheader("🔮 Forecasting Parameters")
    with st.container(border=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            # 단순 Pace가 아닌 예약 가속도(Exponential Factor)
            exp_factor = st.slider("📈 예약 가속도 (1.0~3.0)", 1.0, 3.0, 1.5, 
                                   help="임박 시점일수록 높은 값을 설정하세요.")
        with col2:
            rem_days = st.number_input("남은 리드타임 (Days)", value=14, min_value=1)
        with col3:
            total_rooms = 150 # 전체 객실 수
            market_trend = st.select_slider("시장 트렌드", options=["침체", "보통", "호재"], value="보통")

    # 4. [핵심] 지수 성장형 예측 수식 (Exponential Pickup Model)
    # 단순히 (Pace * Days)가 아니라, 남은 기간 동안 예약이 가속화되는 곡선을 시뮬레이션합니다.
    # 수식: Forecast = OTB + (Pace * Days * 가속도_보정값)
    trend_weight = {"침체": 0.7, "보통": 1.0, "호재": 1.4}[market_trend]
    
    # 가속도 로직: 남은 날짜가 적을수록 pickup 효율이 기하급수적으로 증가하는 모델링
    projected_pickup = base_pace * rem_days * (exp_factor ** (rem_days / 30)) * trend_weight
    final_forecast = total_otb + projected_pickup
    
    # 5. 시각적 리포트
    
    
    res_c1, res_c2 = st.columns(2)
    with res_c1:
        st.write("### 🚀 실시간 예측 결과")
        st.metric("최종 예상 점유실", f"{int(final_forecast)} Rms", 
                  delta=f"+{int(projected_pickup)} Rms 추가 확보 예상")
        
        occ_pct = (final_forecast / (total_rooms * 30)) * 100
        st.write(f"**예상 점유율: {occ_pct:.1f}%**")
        st.progress(min(1.0, occ_pct/100))

    with res_c2:
        st.write("### 📉 시나리오 비교")
        comparison = pd.DataFrame({
            "시나리오": ["Worst (가속도 1.0)", "Base (가속도 1.5)", "Best (가속도 2.5)"],
            "예상 객실": [
                int(total_otb + (base_pace * rem_days * 1.0)),
                int(final_forecast),
                int(total_otb + (base_pace * rem_days * 2.5 * 1.2))
            ]
        })
        st.table(comparison)

    # 6. 전략적 인사이트
    st.divider()
    if occ_pct > 85:
        st.success(f"💡 **전략 제안:** 예상 점유율이 매우 높습니다. **BAR 요금을 10~15% 인상**하고 고단가 채널 비중을 높이세요.")
    elif occ_pct < 60:
        st.error(f"💡 **전략 제안:** 공급 과잉이 우려됩니다. **Flash Sale** 또는 연박 패키지 출시를 검토하세요.")
    else:
        st.info(f"💡 **전략 제안:** 현재 페이스가 안정적입니다. 얼리버드 예약을 유지하며 주말 요금 최적화에 집중하세요.")

if __name__ == "__main__":
    run_forecasting()
