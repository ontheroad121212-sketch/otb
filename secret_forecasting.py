import streamlit as st
import pandas as pd
from datetime import datetime

def run_forecasting():
    st.title("🎯 AI 실전형 정밀 포캐스팅 (v4.5)")
    st.caption("4만 건의 과거 데이터 패턴과 실시간 가속도 로직이 통합되었습니다.")
    st.markdown("---")

    # [1] 데이터 호출 및 변수 초기화 (에러 방지 핵심)
    selected_month = st.sidebar.selectbox("분석 대상 월 선택", range(1, 13), index=datetime.now().month - 1)
    
    # 세션 데이터 로드
    target_sob = st.session_state.get(f"sob_{selected_month}")
    target_pace = st.session_state.get(f"pace_{selected_month}", 0)
    dow_indices = st.session_state.get("historical_dow", {})
    repeat_rate = st.session_state.get("repeat_rate", 0)

    # 변수 기본값 선언 (UnboundLocalError 방지)
    base_pace = float(target_pace) if target_pace else 0.0
    auto_dow_index = 1.0
    total_otb = 0.0
    current_occ = 0.0

    # [2] 데이터 검증 및 파싱
    if target_sob is None:
        st.warning(f"📂 {selected_month}월 분석 데이터가 없습니다.")
        st.info("메인 리포트 탭에서 해당 월의 데이터를 먼저 로드해주세요.")
        return

    try:
        current_occ = float(target_sob.get('TOTAL_OCC', 0))
        total_otb = float(target_sob.get('FIT_RMS', 0) + target_sob.get('GRP_RMS', 0))
        
        # 오늘 요일에 해당하는 과거 데이터 기반 가중치 추출
        current_dow = datetime.now().weekday()
        auto_dow_index = float(dow_indices.get(current_dow, 1.1))
    except Exception as e:
        st.error(f"데이터 파싱 중 오류 발생: {e}")
        return

    # [3] 실전형 시뮬레이션 설정
    st.subheader("🔮 지능형 시나리오 설정")
    with st.container(border=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            # 엑셀 펙터(가속도)와 요일 지수 결합
            accel_factor = st.slider("🚀 예약 가속도 (Accel Factor)", 0.5, 3.0, 1.2)
            # 최종 계산용 페이스 = 최근 페이스 * 과거 요일 가중치 * 수동 가속도
            calc_pace = base_pace * auto_dow_index * accel_factor
        with col2:
            rem_days = st.number_input("남은 분석 기간 (Days)", value=7, min_value=1)
        with col3:
            washout = st.slider("예상 취소율 (%)", 0, 30, 5)

    # [4] 정밀 예측 계산
    projected_pickup = max(0, calc_pace * rem_days) # 마이너스 발생 방지
    final_forecast = (total_otb + projected_pickup) * (1 - washout/100)

    # [5] 결과 리포트 시각화
    
    
    st.divider()
    res_c1, res_c2 = st.columns(2)
    
    with res_c1:
        st.write("### 🚀 실시간 예측 결과")
        st.metric("최종 예상 점유실", f"{int(final_forecast)} Rms", 
                  delta=f"{int(final_forecast - total_otb)} Rms 증감 예상")
        
        # 150실 기준 점유율 시각화
        occ_rate = (final_forecast / (150 * 30)) * 100
        st.write(f"**예상 월간 점유율: {occ_rate:.1f}%**")
        st.progress(min(1.0, occ_rate/100))

    with res_c2:
        st.write("### 🎯 데이터 기반 인사이트")
        st.write(f"**과거 데이터 분석 재방문율:** {repeat_rate:.1f}%")
        st.write(f"**오늘의 예약 강도 지수:** {auto_dow_index:.2f}x")
        
        if occ_rate > 85:
            st.success("💡 점유율이 높습니다. 고단가 위주로 판매를 최적화하세요.")
        else:
            st.info("💡 추가 픽업이 필요합니다. 타겟 마케팅을 검토하세요.")

if __name__ == "__main__":
    run_forecasting()
