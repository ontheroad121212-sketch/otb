import streamlit as st
import pandas as pd
from datetime import datetime

def run_forecasting():
    # 1. 헤더 영역
    st.title("🎯 AI Smart Forecasting Lab")
    st.caption("메인 리포트의 데이터를 기반으로 미래 시나리오를 예측합니다.")
    st.markdown("---")

    # 2. 데이터 연동 확인
    selected_month = st.sidebar.selectbox("예측 대상 월 선택", range(1, 13), index=datetime.now().month - 1)
    
    # 세션 스테이트에서 다른 탭의 데이터 가져오기
    target_sob = st.session_state.get(f"sob_{selected_month}")
    target_pace = st.session_state.get(f"pace_{selected_month}", 0)

    if not target_sob:
        st.warning(f"📂 {selected_month}월의 분석 데이터가 캐시에 없습니다.")
        st.info("메인 리포트에서 해당 월의 탭을 먼저 클릭(데이터 로드)한 뒤 다시 오세요!")
        return

    # 3. 현재 현황 요약 (S.O.B 기반)
    current_occ_pct = target_sob.get('TOTAL_OCC', 0)
    fit_rms = target_sob.get('FIT_RMS', 0)
    grp_rms = target_sob.get('GRP_RMS', 0)
    total_otb_rms = fit_rms + grp_rms

    st.subheader(f"📊 {selected_month}월 실시간 OTB 현황")
    c1, c2, c3 = st.columns(3)
    c1.metric("현재 점유율", f"{current_occ_pct:.1f}%")
    c2.metric("확정 예약실 (OTB)", f"{total_otb_rms:,.0f} Rms")
    c3.metric("계산된 일일 Pace", f"{target_pace:+,.0f} Rms")

    # 4. 시나리오 시뮬레이션
    st.markdown("### 🔮 Scenario Simulation")
    with st.expander("🛠️ 예측 변수 조절", expanded=True):
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            input_pace = st.number_input("향후 예상 Pace (Rms/일)", value=float(target_pace))
        with col_b:
            rem_days = st.number_input("분석 기간 (남은 일수)", value=15, min_value=1)
        with col_c:
            washout = st.slider("예상 취소율(Wash-out) %", 0, 30, 5)

    # 5. 예측 계산 로직
    # 예상 추가 예약 = 일일 페이스 * 남은 기간
    projected_add = input_pace * rem_days
    # 최종 예상 = (현재 OTB + 추가 예약) * (1 - 취소율)
    final_occ_rms = (total_otb_rms + projected_add) * (1 - washout/100)

    st.divider()
    
    # 6. 결과 시각화
    st.subheader("🚀 Forecasting 결과")
    res_col1, res_col2 = st.columns([1, 1])
    
    with res_col1:
        st.metric(
            label="최종 예상 점유 객실",
            value=f"{int(final_occ_rms)} Rms",
            delta=f"{int(final_occ_rms - total_otb_rms)} Rms 추가 예상"
        )
        # 100조 기업을 향한 게이지 (예시로 150실 기준 점유율 표시)
        occ_target = min(1.0, final_occ_rms / 150) 
        st.progress(occ_target, text=f"예상 점유율: {int(occ_target*100)}%")

    with res_col2:
        st.write("**Scenario Comparison**")
        comparison_data = {
            "Scenario": ["Worst (-50% Pace)", "Base (Maintain)", "Best (+50% Pace)"],
            "Projected RMS": [
                int((total_otb_rms + (projected_add * 0.5)) * 0.9), # 취소율 가중치 포함
                int(final_occ_rms),
                int((total_otb_rms + (projected_add * 1.5)) * 0.98)
            ]
        }
        st.table(pd.DataFrame(comparison_data))

    st.caption("※ 본 페이지는 실전형 천재를 위한 관리자 전용 대시보드입니다. 😎")

if __name__ == "__main__":
    run_forecasting()
else:
    run_forecasting()
