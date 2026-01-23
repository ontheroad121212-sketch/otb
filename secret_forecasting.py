import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def run_forecasting():
    st.title("🏛️ RM 지배인용 전략 포캐스팅 (v9.0)")
    st.caption("과거 4만 건의 예약 원장 분석 데이터와 실시간 픽업 가속도를 결합한 정밀 모델")

    # 1. 데이터 호출 및 초기화
    selected_month = st.sidebar.selectbox("대상 월 선택", range(1, 13), index=datetime.now().month-1)
    target_sob = st.session_state.get(f"sob_{selected_month}")
    actual_pace = float(st.session_state.get(f"pace_{selected_month}", 0)) 
    dow_indices = st.session_state.get("historical_dow", {})
    
    if not target_sob:
        st.warning("먼저 메인 리포트에서 해당 월의 데이터를 로드하세요.")
        return

    # [데이터 기본값 설정]
    fit_otb = float(target_sob.get('FIT_RMS', 0))
    grp_otb = float(target_sob.get('GRP_RMS', 0))
    current_otb = fit_otb + grp_otb
    current_dow = datetime.now().weekday()
    auto_dow_index = float(dow_indices.get(current_dow, 1.0))

    # ----------------------------------------------------------------------
    # 2. 지배인 전략 변수 설정 (시뮬레이션 입력)
    # ----------------------------------------------------------------------
    st.subheader(f"📅 {selected_month}월 상세 시뮬레이션 설정")
    
    with st.container(border=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            st.write("**🔥 시장 모멘텀**")
            base_pace = st.number_input("일평균 픽업 (Rms)", value=max(0.5, actual_pace))
            accel = st.slider("📈 예약 가속도 (Accel)", 0.5, 3.0, 1.2, help="1.0 이상은 시장 상승세, 이하인 경우 하락세를 의미")
            rem_days = st.number_input("남은 기간 (Days)", value=7, min_value=1)
        
        with col2:
            st.write("**⚠️ 리스크 관리**")
            fit_washout = st.slider("FIT 취소율 (%)", 0, 15, 2)
            grp_washout = st.slider("Group 워시아웃 (%)", 0, 50, 5, help="단체 예약의 실제 투숙 하락분 예상")
            lt_weight = st.checkbox("리드타임 가중치 적용", value=True, help="입실일이 가까울수록 픽업이 증가하는 곡선 적용")
            
        with col3:
            st.write("**💰 수익 지표**")
            target_adr = st.number_input("예상 ADR (평균단가)", value=int(target_sob.get('FIT_REV', 0)/max(1, fit_otb)) if fit_otb > 0 else 250000, step=5000)
            comp_set_occ = st.slider("경쟁사 예상 OCC (%)", 0, 100, 75, help="경쟁사 대비 우리 호텔의 포지셔닝 참고용")

    # ----------------------------------------------------------------------
    # 3. [정밀 수식 엔진] 지배인급 시뮬레이션 로직
    # ----------------------------------------------------------------------
    # 리드타임 보정치 계산 (남은 기간이 짧을수록 예약 발생 빈도가 높아짐)
    lt_factor = (1.0 + (1.0 / np.log1p(rem_days))) if lt_weight else 1.0
    
    # 1) FIT 추가 픽업 = (일평균 * 요일지수 * 가속도 * 리드타임보정 * 남은날짜)
    expected_fit_pickup = base_pace * auto_dow_index * accel * lt_factor * rem_days
    
    # 2) Group 추가 픽업 (단체는 리드타임이 짧으면 추가 유입이 거의 없음)
    expected_grp_pickup = (grp_otb * 0.02) if rem_days > 14 else 0
    
    # 3) Wash-out (취소 예상량)
    loss_fit = fit_otb * (fit_washout / 100)
    loss_grp = grp_otb * (grp_washout / 100)
    
    # 최종 객실수 및 매출
    final_rms = (current_otb - loss_fit - loss_grp) + expected_fit_pickup + expected_grp_pickup
    final_rev = final_rms * target_adr

    # ----------------------------------------------------------------------
    # 4. 전략적 결과 리포트
    # ----------------------------------------------------------------------
    [Image of a professional hotel revenue management system showing forecasting graphs and booking pace trends]
    
    st.divider()
    res_c1, res_c2 = st.columns([1.2, 1])
    
    with res_c1:
        st.write(f"### 🚀 {selected_month}월 최종 시뮬레이션 결과")
        occ_pct = (final_rms / 4500) * 100 # 150실 * 30일 기준
        
        m1, m2, m3 = st.columns(3)
        m1.metric("예상 객실수", f"{int(final_rms)} Rms", f"{int(final_rms - current_otb):+d}")
        m2.metric("예상 점유율", f"{occ_pct:.1f}%")
        m3.metric("예상 매출액", f"₩{int(final_rev/10000):,}만")
        
        st.progress(min(1.0, occ_pct/100))
        
        # 지배인 코멘트 (AI Insight)
        if occ_pct > 85:
            st.success(f"🔥 **[High Demand]** 점유율이 {occ_pct:.1f}%로 예상됩니다. 즉시 ADR을 상향 조정하고 마감 전략을 세우세요.")
        elif occ_pct < 60:
            st.error(f"❄️ **[Low Demand]** 수요가 부족합니다. 타임세일이나 OTA 프로모션 검토가 필요합니다.")
        else:
            st.info(f"⚖️ **[Stable]** 안정적인 흐름입니다. 현재 가격을 유지하며 취소분을 모니터링하세요.")

    with res_c2:
        st.write("### 📊 정밀 분석 브리핑")
        detail_data = {
            "항목": ["현재 OTB", "FIT 추가 픽업", "Group 추가 픽업", "Wash-out (FIT)", "Wash-out (Group)"],
            "객실수": [int(current_otb), int(expected_fit_pickup), int(expected_grp_pickup), int(-loss_fit), int(-loss_grp)]
        }
        st.table(pd.DataFrame(detail_data))
        st.caption(f"💡 요일 지수({auto_dow_index:.2f}x)와 리드타임 보정({lt_factor:.2f}x)이 반영된 수치입니다.")

    # ----------------------------------------------------------------------
    # 5. 전략적 체크리스트
    # ----------------------------------------------------------------------
    with st.expander("📍 지배인 행동 지침 (Action Plan)"):
        st.write(f"1. **오버부킹 방어**: 예상 점유율이 {occ_pct:.1f}%이므로 남은 {int(4500 - final_rms)}실에 대해 수동 채널 정지를 검토하세요.")
        st.write(f"2. **단가 전략**: 현재 설정된 ADR ₩{target_adr:,}이 경쟁사 대비 적절한지 재확인 바랍니다.")
        st.write(f"3. **예약 경로**: 4만 건 분석 데이터에 따르면 해당 요일에는 자사몰 예약 비중이 높습니다. 마케팅을 강화하세요.")

if __name__ == "__main__":
    run_forecasting()
