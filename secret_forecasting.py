import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime

def run_forecasting():
    # 1. 헤더 영역
    st.title("🎯 AI Smart Forecasting Lab")
    st.markdown("---")

    # 2. 데이터 연동 확인 (세션 스테이트에서 가져오기)
    selected_month = st.sidebar.selectbox("예측 대상 월 선택", range(1, 13), index=datetime.now().month - 1)
    
    # 메인/개별 페이지에서 저장한 데이터 불러오기
    target_sob = st.session_state.get(f"sob_{selected_month}")
    target_pace = st.session_state.get(f"pace_{selected_month}", 0)

    # 데이터가 없을 경우 흰 화면 대신 경고 메시지 출력
    if not target_sob:
        st.warning(f"📂 {selected_month}월의 분석 데이터가 캐시에 없습니다.")
        st.info("메인 리포트나 OTB/Pace 탭에서 데이터를 먼저 조회한 뒤 다시 오세요!")
        return  # 함수 종료 (st.stop() 대신 return 사용)

    # 3. 데이터 파싱 (안전하게 get 사용)
    try:
        current_occ_pct = float(target_sob.get('TOTAL_OCC', 0))
        fit_rms = float(target_sob.get('FIT_RMS', 0))
        grp_rms = float(target_sob.get('GRP_RMS', 0))
        total_otb_rms = fit_rms + grp_rms
        
        # 페이스 데이터가 숫자가 아닐 경우를 대비
        current_pace = float(target_pace) if target_pace else 0.0
    except (ValueError, TypeError):
        st.error("데이터 형식이 올바르지 않습니다. 리포트를 다시 로드해주세요.")
        return

    # 4. 현황 대시보드
    st.subheader(f"📊 {selected_month}월 실시간 OTB 현황")
    c1, c2, c3 = st.columns(3)
    c1.metric("현재 점유율", f"{current_occ_pct:.1f}%")
    c2.metric("확정 예약실 (OTB)", f"{total_otb_rms:,.0f} Rms")
    c3.metric("최근 일일 Pace", f"{current_pace:+,.1f} Rms")

    # 5. [핵심] 가속도 및 시나리오 설정
    st.markdown("### 🔮 Advanced Simulation (Accel Factor)")
    
    with st.container(border=True):
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            # 가속도 인자: 1.0보다 크면 예약 속도가 빨라짐을 의미
            accel_factor = st.slider("🚀 예약 가속도 (Accel Factor)", 0.5, 2.0, 1.2, help="1.0은 현재 속도 유지, 1.2는 20% 가속을 의미합니다.")
            input_pace = current_pace * accel_factor
        with col_b:
            rem_days = st.number_input("투숙까지 남은 평균 기간 (Days)", value=15, min_value=1)
        with col_c:
            washout = st.slider("예상 취소율 (Wash-out %)", 0, 30, 5)

    # 6. 예측 계산 로직 (실전 수식)
    # 예상 추가 예약 = (현재 페이스 * 가속도) * 남은 기간
    projected_add = input_pace * rem_days
    # 최종 Forecast = (현재 OTB + 예상 추가분) * (1 - 취소율)
    final_forecast_rms = (total_otb_rms + projected_add) * (1 - washout/100)

    st.divider()
    
    # 7. 결과 시각화
    st.subheader("🚀 최종 기대 실적 (Forecast Result)")
    
    res_col1, res_col2 = st.columns([1, 1])
    
    with res_col1:
        st.metric(
            label="최종 예상 점유 객실",
            value=f"{int(final_forecast_rms)} Rms",
            delta=f"{int(final_forecast_rms - total_otb_rms)} Rms 추가 확보 예상"
        )
        # 프로그래스 바 (150실 기준 예시, 실제 총객실수가 있다면 분모에 넣으세요)
        total_capacity = 150 
        progress_val = min(1.0, final_forecast_rms / total_capacity)
        st.progress(progress_val, text=f"예상 최종 점유율: {int(progress_val * 100)}%")

    with res_col2:
        st.write("**Scenario Comparison**")
        comparison_data = {
            "Scenario": ["Worst (Low Accel)", "Base (Current)", "Best (High Accel)"],
            "Projected RMS": [
                int((total_otb_rms + (projected_add * 0.7)) * 0.92),
                int(final_forecast_rms),
                int((total_otb_rms + (projected_add * 1.5)) * 0.98)
            ]
        }
        st.table(pd.DataFrame(comparison_data))

    st.info(f"💡 **Insight:** 현재 가속도({accel_factor}x)를 적용했을 때, {selected_month}월 최종 목표 달성을 위해 일평균 {input_pace:.1f}실의 추가 픽업이 필요합니다.")
    st.caption("※ 이 리포트는 사용자 전용 비밀 페이지입니다. 보안에 유의하세요. 😉")

# 실행부
if __name__ == "__main__":
    run_forecasting()
