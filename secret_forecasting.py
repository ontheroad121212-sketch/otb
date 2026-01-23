import streamlit as st
import pandas as pd

def run_forecasting():
    st.title("🎯 실전형 천재의 비밀 분석실")
    st.caption("과거 데이터와 현재 페이스를 기반으로 미래 점유율을 시뮬레이션합니다.")

    # 1. 월 선택 및 데이터 로드
    selected_month = st.selectbox("분석 대상 월", range(1, 13), index=datetime.now().month - 1)
    target_sob = st.session_state.get(f"sob_{selected_month}")
    target_pace = st.session_state.get(f"pace_{selected_month}", 0)

    if not target_sob:
        st.warning(f"📂 {selected_month}월의 리포트 데이터가 없습니다. 먼저 메인 탭에서 데이터를 로드하세요.")
        return

    # 2. 현재 상태 요약
    current_occ = target_sob.get('TOTAL_OCC', 0)
    st.metric("현재 OTB (확정 예약)", f"{current_occ} Rms")

    # 3. 시나리오 컨트롤러
    st.divider()
    col1, col2, col3 = st.columns(3)
    with col1:
        daily_pace = st.number_input("일일 예상 픽업(Rms)", value=float(target_pace))
    with col2:
        rem_days = st.number_input("남은 기간 (Days)", value=15)
    with col3:
        washout = st.slider("예상 취소율(%)", 0, 30, 5)

    # 4. 시나리오 계산 및 시각화
    # 
    st.subheader("🚀 시나리오별 최종 예측")
    
    # Base Case 계산
    base_proj = (current_occ + (daily_pace * rem_days)) * (1 - washout/100)
    
    c1, c2, c3 = st.columns(3)
    with c1:
        st.error("Worst Case (페이스 -50%)")
        worst = (current_occ + (daily_pace * 0.5 * rem_days)) * (1 - (washout+5)/100)
        st.write(f"**{int(worst)} Rms**")
    with c2:
        st.info("Base Case (현재 유지)")
        st.metric("최종 예상", f"{int(base_proj)} Rms", delta=f"{int(base_proj - current_occ)} Rms")
    with c3:
        st.success("Best Case (페이스 +50%)")
        best = (current_occ + (daily_pace * 1.5 * rem_days)) * (1 - (washout-2)/100)
        st.write(f"**{int(best)} Rms**")

    st.divider()
    st.caption("※ 이 분석 결과는 총지배인님께 보고 전, 전략 수립용으로만 활용하십시오. 😉")

if __name__ == "__main__":
    run_forecasting()
