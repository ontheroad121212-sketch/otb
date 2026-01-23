import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime

def run_forecasting():
    st.title("🎯 데이터 기반 정밀 포캐스팅 (v7.0)")
    st.caption("현재 실적(OTB)을 보존하며 과거 4만 건의 예약 패턴을 반영합니다.")
    
    # 1. 사이드바 및 기본 데이터 로드
    selected_month = st.sidebar.selectbox("대상 월 선택", range(1, 13), index=datetime.now().month-1)
    
    # [데이터 호출] 메인 리포트와 4만 건 분석 결과 가져오기
    target_sob = st.session_state.get(f"sob_{selected_month}")
    # pace_{selected_month}가 없으면 0으로 처리하여 NameError 방지
    actual_pace = float(st.session_state.get(f"pace_{selected_month}", 0)) 
    dow_indices = st.session_state.get("historical_dow", {})
    
    if not target_sob:
        st.warning("먼저 메인 리포트에서 해당 월의 탭을 클릭해 데이터를 로드하세요.")
        return

    # 2. 현재 실적 및 요일 지수 설정
    current_otb = float(target_sob.get('FIT_RMS', 0) + target_sob.get('GRP_RMS', 0))
    current_dow = datetime.now().weekday()
    # 요일 지수가 없으면 기본값 1.0 사용
    auto_dow_index = float(dow_indices.get(current_dow, 1.0))

    # 3. 시뮬레이션 변수 설정 (중복 제거 및 통합)
    st.subheader(f"🔮 {selected_month}월 Forecasting Simulation")
    with st.container(border=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            # 실시간 픽업량(actual_pace)이 0이더라도 최소 0.5실의 잠재수요는 있다고 가정
            base_pace = st.number_input("일평균 예상 픽업 (Rms)", value=max(0.5, actual_pace))
            accel = st.slider("📈 예약 가속도 (Accel)", 0.5, 3.0, 1.2)
        with col2:
            rem_days = st.number_input("남은 기간 (Days)", value=7, min_value=1)
        with col3:
            # 현재 들어온 2400박 중 취소될 가능성 설정
            washout_pct = st.slider("확정 예약 취소 예상 (Wash-out %)", 0, 10, 0)

    # 4. [핵심 수식] 상식적인 산수 모델 적용
    # 예상 취소분 계산
    expected_washout = current_otb * (washout_pct / 100)
    # 미래 추가 픽업 계산 (일평균 픽업 * 요일지수 * 가속도 * 남은날짜)
    future_pickup = base_pace * auto_dow_index * accel * rem_days
    
    # 최종 예측 = 현재실적 - 취소분 + 미래픽업
    final_forecast = (current_otb - expected_washout) + future_pickup

    # 5. 결과 리포트 출력
    [Image of a professional hotel revenue forecasting chart showing OTB as a solid foundation with a rising projected pickup curve]

    st.divider()
    res_c1, res_c2 = st.columns(2)
    
    with res_c1:
        st.write(f"### 🚀 {selected_month}월 최종 예상")
        # 현재 OTB 대비 증감폭 시각화
        st.metric("최종 예상 점유 객실", f"{int(final_forecast)} Rms", 
                  delta=f"{int(final_forecast - current_otb):+d} Rms (현재 대비)")
        
        # 점유율 계산 (기준: 150실 * 30일 = 4500실)
        occ_pct = (final_forecast / 4500) * 100
        st.write(f"**예상 점유율: {occ_pct:.1f}%**")
        st.progress(min(1.0, occ_pct/100))

    with res_c2:
        st.write("### 📊 분석 디테일")
        st.write(f"✅ **현재 확정(OTB):** {int(current_otb)} Rms")
        st.write(f"📉 **예상 취소분:** -{int(expected_washout)} Rms")
        st.write(f"📈 **추가 예약(Pickup):** +{int(future_pickup)} Rms")
        st.caption(f"※ 요일 지수({auto_dow_index:.2f}x)와 가속도({accel:.1f}x)가 적용된 수치입니다.")

    # 6. 전략 가이드
    st.divider()
    if final_forecast > current_otb:
        st.success(f"💡 현재 추세라면 투숙 전까지 약 **{int(future_pickup)}실**의 추가 예약이 기대됩니다. 요일별 강도({auto_dow_index:.2f})가 긍정적입니다.")
    else:
        st.warning("💡 취소 예상치가 픽업 속도보다 높을 수 있습니다. 현재 확정된 예약의 No-show 방지 및 취소 방어 전략이 필요합니다.")

if __name__ == "__main__":
    run_forecasting()
