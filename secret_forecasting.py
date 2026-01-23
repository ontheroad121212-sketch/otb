import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime

def run_forecasting():
    st.title("🏛️ 전략 RM 지배인 포캐스팅 (v10.0)")
    st.caption("131실 가변 재고 모델 및 4만 건 예약 패턴 동기화 엔진")

    # 1. 데이터 호출 및 세션 체크
    selected_month = st.sidebar.selectbox("🎯 분석 대상 월", range(1, 13), index=datetime.now().month-1)
    target_sob = st.session_state.get(f"sob_{selected_month}")
    actual_pace = float(st.session_state.get(f"pace_{selected_month}", 0)) 
    dow_indices = st.session_state.get("historical_dow", {})
    
    if not target_sob:
        st.warning("먼저 메인 리포트에서 해당 월의 데이터를 로드하세요.")
        return

    # [기본 물리량 설정]
    TOTAL_ROOMS = 131
    MONTH_DAYS = 30 # 대상 월의 일수 (필요시 달력 연동 가능)
    fit_otb = float(target_sob.get('FIT_RMS', 0))
    grp_otb = float(target_sob.get('GRP_RMS', 0))
    current_otb = fit_otb + grp_otb
    auto_dow_index = float(dow_indices.get(datetime.now().weekday(), 1.0))

    # 2. 지배인 전략 변수 (인벤토리 및 리스크 관리)
    st.subheader(f"📊 {selected_month}월 시뮬레이션 환경 설정")
    
    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            st.write("**🏨 인벤토리 관리**")
            ooo_rooms = st.slider("일평균 고장 객실 (OOO)", 0, 10, 2)
            net_capacity = (TOTAL_ROOMS - ooo_rooms) * MONTH_DAYS
            st.caption(f"실 가용 객실: {net_capacity:,} Rms")
        with c2:
            st.write("**🔥 시장 모멘텀**")
            accel = st.slider("예약 가속도 (Accel)", 0.5, 3.0, 1.1)
            rem_days = st.number_input("남은 기간 (Days)", value=7, min_value=1)
        with c3:
            st.write("**💰 수익 지표**")
            current_adr = int(target_sob.get('FIT_REV', 0)/max(1, fit_otb)) if fit_otb > 0 else 230000
            target_adr = st.number_input("목표 ADR (평균단가)", value=current_adr, step=5000)

    # 3. [정밀 수식 엔진]
    # 리드타임 보정: 임박할수록 예약 밀도가 높아짐
    lt_factor = (1.0 + (1.0 / np.log1p(rem_days)))
    
    # 예상 픽업량 계산 (공급량 한계 설정)
    expected_pickup = actual_pace * auto_dow_index * accel * lt_factor * rem_days
    
    # Wash-out (취소 예상)
    washout_rate = 0.03 # 기본 3% 설정
    expected_loss = current_otb * washout_rate
    
    # 최종 예상 객실수 (가용 객실 초과 불가)
    final_rms = min(net_capacity, (current_otb - expected_loss) + expected_pickup)
    final_rev = final_rms * target_adr

    # 4. 고도화된 대시보드 출력
    st.divider()
    
    # KPI 3종 지표
    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    with kpi1:
        st.metric("최종 예상 객실", f"{int(final_rms):,} Rms", f"{int(final_rms - current_otb):+d}")
    with kpi2:
        occ_pct = (final_rms / net_capacity) * 100
        st.metric("예상 점유율(OCC)", f"{occ_pct:.1f}%")
    with kpi3:
        st.metric("예상 매출액", f"₩{int(final_rev/10000):,}만")
    with kpi4:
        # 예상 마감 속도 측정
        days_to_full = (net_capacity - current_otb) / max(0.1, (expected_pickup / rem_days))
        st.metric("만실 예상", f"{int(days_to_full)}일 뒤" if occ_pct < 100 else "SOLD OUT")

    # 시각화 차트 영역
    [Image of hotel room occupancy forecast chart comparing current OTB vs trend line vs total capacity]
    
    st.write("---")
    
    col_a, col_b = st.columns([1.5, 1])
    
    with col_a:
        st.write("### 📈 시뮬레이션 상세 분석")
        # 데이터프레임으로 깔끔하게 정리
        analysis_df = pd.DataFrame({
            "구분": ["현재 확정(OTB)", "예약 취소(Wash-out)", "미래 추가 픽업", "고장객실 손실"],
            "객실수": [int(current_otb), int(-expected_loss), int(expected_pickup), int(-(ooo_rooms * MONTH_DAYS))],
            "영향력": ["기본값", "낮음", "높음", "중간"]
        })
        st.table(analysis_df)

    with col_b:
        st.write("### 💡 RM 지배인 전략 제언")
        if occ_pct > 90:
            st.error("🚨 **OVERBOOKING 위험**")
            st.write("현재 속도라면 만실이 예상됩니다. 즉시 저가 채널(OTA)을 닫고 ADR을 15% 이상 상향하세요.")
        elif occ_pct > 75:
            st.warning("⚡ **ADR 상향 구간**")
            st.write("안정적인 수요가 확인되었습니다. 주말 단가를 높이고 연박(Min Stay) 제한을 검토하세요.")
        else:
            st.info("📉 **수요 촉진 구간**")
            st.write("픽업 속도가 더딥니다. 당일 특가 또는 패키지 노출을 강화하여 OCC를 끌어올려야 합니다.")

    # 5. 과거 4만건 기반 요일별 인사이트 (세밀한 기능 추가)
    with st.expander("🔍 과거 데이터 기반 요일별 ADR 전략 정보"):
        st.write(f"현재 분석된 요일({datetime.now().strftime('%A')})의 예약 강도는 **{auto_dow_index:.2f}배** 입니다.")
        st.write("- **평일(월-목):** 비즈니스 수요 위주, 안정적 단가 유지 필요")
        st.write("- **주말(금-일):** 레저 수요 집중, 높은 ADR 탄력성 확인됨")

if __name__ == "__main__":
    run_forecasting()
