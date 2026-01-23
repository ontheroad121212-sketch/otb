import streamlit as st
import pandas as pd
from datetime import datetime

def run_forecasting():
    # 1. 헤더 영역
    st.title("🎯 AI Smart Forecasting Lab")
    st.markdown("---")

    # 2. 데이터 연동 확인
    # 메인 앱에서 st.session_state[f"sob_{month}"]로 저장한 데이터를 불러옵니다.
    selected_month = st.sidebar.selectbox("예측 대상 월 선택", range(1, 13), index=datetime.now().month - 1)
    target_sob = st.session_state.get(f"sob_{selected_month}")
    target_pace = st.session_state.get(f"pace_{selected_month}", 0)

    if not target_sob:
        st.warning(f"📂 {selected_month}월의 분석 데이터가 캐시에 없습니다.")
        st.info("메인 리포트 탭에서 해당 월의 데이터를 먼저 조회(업로드)한 뒤 다시 오세요!")
        st.stop()

    # 3. 현재 현황 요약 (S.O.B 기반)
    current_occ_pct = target_sob.get('TOTAL_OCC', 0)
    fit_rms = target_sob.get('FIT_RMS', 0)
    grp_rms = target_sob.get('GRP_RMS', 0)
    total_otb_rms = fit_rms + grp_rms

    st.subheader(f"📊 {selected_month}월 현재 OTB 현황")
    c1, c2, c3 = st.columns(3)
    c1.metric("현재 확정 점유율", f"{current_occ_pct:.1f}%")
    c2.metric("확정 예약실 (OTB)", f"{total_otb_rms:,.0f} Rms")
    c3.metric("최근 일일 Pace", f"{target_pace:+,.0f} Rms")

    # 4. 시나리오 시뮬레이션
    st.markdown("### 🔮 Scenario Simulation")
    with st.expander("🛠️ 예측 변수 설정", expanded=True):
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            input_pace = st.number_input("향후 일일 예상 픽업 (Rms)", value=float(target_pace))
        with col_b:
            rem_days = st.number_input("투숙까지 남은 기간 (Days)", value=15, min_value=1)
        with col_c:
            washout = st.slider("예상 취소율 (%)", 0, 30, 5)

    # 5. 예측 계산 로직
    # 공식: OTB + (예상 페이스 * 남은 기간) - 취소분
    projected_add = input_pace * rem_days
    final_occ_rms = (total_otb_rms + projected_add) * (1 - washout/100)

    st.divider()
    
    # 결과 시각화
    st.subheader("🚀 최종 기대 실적 (Forecast)")
    
    res_col1, res_col2 = st.columns([1, 1])
    
    with res_col1:
        # 베이스 시나리오 메트릭
        st.metric(
            label="최종 예상 점유 객실",
            value=f"{int(final_occ_rms)} Rms",
            delta=f"{int(final_occ_rms - total_otb_rms)} Rms 증가 예상"
        )
        st.progress(min(1.0, final_occ_rms / 100), text=f"목표 달성 가시권") # 분모 100은 실제 총객실수로 수정 권장

    with res_col2:
        # Best/Worst Case 간이 표
        st.write("**Scenario Comparison**")
        comparison_data = {
            "Scenario": ["Worst (-50%)", "Base (Maintain)", "Best (+50%)"],
            "Projected RMS": [
                int((total_otb_rms + (projected_add * 0.5)) * 0.9),
                int(final_occ_rms),
                int((total_otb_rms + (projected_add * 1.5)) * 0.98)
            ]
        }
        st.table(pd.DataFrame(comparison_data))

    st.caption("※ 이 리포트는 사용자 전용 비밀 페이지입니다. 보안에 유의하세요. 😉")

# 파일이 실행될 때 함수 호출
if __name__ == "__main__":
    run_forecasting()
else:
    run_forecasting()
