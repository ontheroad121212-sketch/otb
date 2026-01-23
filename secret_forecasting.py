import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime

def run_forecasting():
    st.title("🎯 데이터 기반 정밀 포캐스팅 (v7.0)")
    
    selected_month = st.sidebar.selectbox("대상 월", range(1, 13), index=datetime.now().month-1)
    target_sob = st.session_state.get(f"sob_{selected_month}")
    
    # 1. 메인 리포트의 17박(Pace)과 4만 건의 요일 지수 가져오기
    real_pace = float(st.session_state.get(f"pace_{selected_month}", 0))
    dow_indices = st.session_state.get("historical_dow", {})
    
    if not target_sob:
        st.warning("먼저 메인 리포트에서 해당 월의 탭을 클릭해 데이터를 로드하세요.")
        return

    # 2. 기초 지표 설정 (2400박 보존)
    current_otb = float(target_sob.get('FIT_RMS', 0) + target_sob.get('GRP_RMS', 0))
    current_dow = datetime.now().weekday()
    dow_weight = float(dow_indices.get(current_dow, 1.0))

    # 3. 정밀 시뮬레이션 (산수: 2400 + (17 * 요일지수 * 가속도 * 7일))
    st.subheader(f"📊 현재 실적: {int(current_otb)} Rms 기준")
    col1, col2 = st.columns(2)
    with col1:
        rem_days = st.number_input("남은 기간 (Days)", value=7)
        accel = st.slider("예약 가속도 (Market Accel)", 0.5, 3.0, 1.2)
    
    future_pickup = real_pace * dow_weight * accel * rem_days
    final_forecast = current_otb + future_pickup # 마이너스 방지

    # 4. 결과 출력
    st.divider()
    st.metric("최종 예상 실적", f"{int(final_forecast)} Rms", 
              delta=f"+{int(future_pickup)} Rms (현재 OTB 대비)")
    
    st.info(f"💡 근거: 일평균 {real_pace}박 픽업 + 4만건 기반 요일지수({dow_weight:.2f}x) 적용")

    # --- 실전형 변수 설정 ---
    st.subheader("🔮 Forecasting Simulation")
    with st.container(border=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            # 최근 페이스가 마이너스여도 최소 0.5실 이상은 들어온다고 가정 (Base Pickup)
            base_pace = max(0.5, float(target_pace)) 
            accel = st.slider("📈 예약 가속도 (Accel)", 0.5, 3.0, 1.2)
        with col2:
            rem_days = st.number_input("남은 기간 (Days)", value=7, min_value=1)
        with col3:
            # 취소율은 전체가 아니라 '추가로 들어올 예약'에만 적용하거나 아주 미세하게 적용
            washout_pct = st.slider("확정 예약 취소 예상 (Wash-out %)", 0, 10, 2)

    # 4. [핵심] 마이너스 방지 예측 수식
    # 수식 설명: 현재 OTB에서 취소될 것 같은 양을 빼고, 앞으로 들어올 양(Pickup)을 더함
    # 절대 (현재 OTB - 취소분)이 마이너스가 되지 않도록 설계
    
    expected_washout = current_otb * (washout_pct / 100)
    # 픽업 계산 시 요일 지수와 가속도를 반영하여 '미래에 추가될 양'만 산출
    future_pickup = base_pace * auto_dow_index * accel * rem_days
    
    # 최종 예측 = 현재 실적 - 예상 취소 + 미래 추가 예약
    final_forecast = (current_otb - expected_washout) + future_pickup

    # 5. 결과 리포트
    
    
    st.divider()
    res_c1, res_c2 = st.columns(2)
    with res_c1:
        st.write(f"### 🚀 {selected_month}월 최종 예상")
        # 현재 OTB보다 낮은 숫자가 나오지 않도록 시각적 강조
        st.metric("최종 예상 점유 객실", f"{int(final_forecast)} Rms", 
                  delta=f"{int(final_forecast - current_otb)} Rms (현재 대비 증감)")
        
        # 4500실(150실*30일) 기준 점유율
        occ_pct = (final_forecast / 4500) * 100
        st.write(f"**예상 점유율: {occ_pct:.1f}%**")
        st.progress(min(1.0, occ_pct/100))

    with res_c2:
        st.write("### 📊 분석 디테일")
        st.write(f"✅ **현재 확정(OTB):** {int(current_otb)} Rms")
        st.write(f"📉 **예상 취소분:** -{int(expected_washout)} Rms")
        st.write(f"📈 **추가 예약(Pickup):** +{int(future_pickup)} Rms")
        st.caption(f"※ 요일 지수({auto_dow_index:.2f}x)와 가속도({accel}x)가 적용된 수치입니다.")

    # 6. 전략 가이드
    if final_forecast > current_otb:
        st.success(f"💡 현재 속도를 유지할 경우, 투숙 전까지 약 **{int(future_pickup)}실**의 추가 예약이 기대됩니다.")
    else:
        st.warning("💡 취소 발생량이 픽업 속도보다 빠를 수 있습니다. 예약 유지를 위한 CRM이 필요합니다.")

if __name__ == "__main__":
    run_forecasting()
