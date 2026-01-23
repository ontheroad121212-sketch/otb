import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime

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

    # 2. 지배인 전략 변수 설정
    st.subheader(f"📅 {selected_month}월 상세 시뮬레이션 설정")
    
    with st.container(border=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            st.write("**🔥 시장 모멘텀**")
            base_pace = st.number_input("일평균 픽업 (Rms)", value=max(0.5, actual_pace))
            accel = st.slider("📈 예약 가속도 (Accel)", 0.5, 3.0, 1.2)
            rem_days = st.number_input("남은 기간 (Days)", value=7, min_value=1)
        
        with col2:
            st.write("**⚠️ 리스크 관리**")
            fit_washout = st.slider("FIT 취소율 (%)", 0, 15, 2)
            grp_washout = st.slider("Group 워시아웃 (%)", 0, 50, 5)
            lt_weight = st.checkbox("리드타임 가중치 적용", value=True)
            
        with col3:
            st.write("**💰 수익 지표**")
            # 예상 ADR 자동 산출 (실적 기반)
            current_adr = int(target_sob.get('FIT_REV', 0)/max(1, fit_otb)) if fit_otb > 0 else 250000
            target_adr = st.number_input("예상 ADR (평균단가)", value=current_adr, step=5000)
            st.caption(f"현재 실적 ADR: ₩{current_adr:,}")

    # 3. [정밀 수식 엔진]
    # 리드타임 보정: 임박할수록 예약 밀도가 높아지는 로그 곡선 적용
    lt_factor = (1.0 + (1.0 / np.log1p(rem_days))) if lt_weight else 1.0
    
    # FIT 픽업 = 일평균 * 요일가중치 * 가속도 * 리드타임보정 * 남은날짜
    expected_fit_pickup = base_pace * auto_dow_index * accel * lt_factor * rem_days
    # Group은 임박 시 추가유입 보수적 산정
    expected_grp_pickup = (grp_otb * 0.02) if rem_days > 14 else 0
    # Wash-out 계산
    loss_fit = fit_otb * (fit_washout / 100)
    loss_grp = grp_otb * (grp_washout / 100)
    
    # 최종 결과 산출
    final_rms = (current_otb - loss_fit - loss_grp) + expected_fit_pickup + expected_grp_pickup
    final_rev = final_rms * target_adr

    # 4. 전략적 결과 리포트
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
        
        if occ_pct > 85:
            st.success(f"🔥 **[High Demand]** 예상 점유율 {occ_pct:.1f}%! ADR 상향 및 마감 전략이 필요합니다.")
        elif occ_pct < 60:
            st.error(f"❄️ **[Low Demand]** 수요 창출이 필요합니다. 프로모션 검토 권장.")
        else:
            st.info(f"⚖️ **[Stable]** 안정적 흐름입니다. 현재 단가 유지 및 취소분 모니터링.")

    with res_c2:
        st.write("### 📊 정밀 분석 브리핑")
        detail_data = {
            "항목": ["현재 확정(OTB)", "FIT 추가 픽업", "Group 추가 픽업", "Wash-out(FIT)", "Wash-out(Group)"],
            "객실수": [int(current_otb), int(expected_fit_pickup), int(expected_grp_pickup), int(-loss_fit), int(-loss_grp)]
        }
        st.table(pd.DataFrame(detail_data))
        st.caption(f"💡 요일지수({auto_dow_index:.2f}x)와 리드타임 보정({lt_factor:.2f}x) 반영됨")

    with st.expander("📍 지배인 행동 지침 (Action Plan)"):
        st.write(f"1. **오버부킹 방어**: 예상 점유율 {occ_pct:.1f}%이므로 남은 {int(max(0, 4500 - final_rms))}실에 대한 채널 통제 검토.")
        st.write(f"2. **수익 최적화**: 설정된 ADR ₩{target_adr:,}이 경쟁사 대비 우위인지 확인.")
        st.write(f"3. **과거 패턴**: 4만 건 데이터 기준, 현재 요일 패턴은 {'강세' if auto_dow_index > 1 else '약세'} 구간입니다.")

if __name__ == "__main__":
    run_forecasting()
