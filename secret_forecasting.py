import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime

def run_forecasting():
    st.title("🏛️ 총지배인(GM) 전략 의사결정 대시보드 v13.0")
    st.caption("무삭제 정밀판: 131실 가변 재고 기반 실시간 예측 vs 전년(LY) vs 목표(Budget)")

    # 1. 데이터 호출 및 인벤토리 설정
    selected_month = st.sidebar.selectbox("🎯 분석 대상 월", range(1, 13), index=datetime.now().month-1)
    target_sob = st.session_state.get(f"sob_{selected_month}")
    actual_pace = float(st.session_state.get(f"pace_{selected_month}", 0)) 
    dow_indices = st.session_state.get("historical_dow", {})
    
    # [중요] 메인 앱의 BUDGET_DATA 연동 (없을 경우 기본값 4.5억 설정)
    try:
        from __main__ import BUDGET_DATA
        raw_budget = BUDGET_DATA.get(selected_month, 450000000)
    except:
        raw_budget = 450000000
    
    auto_budget_man = int(raw_budget / 10000)

    if not target_sob:
        st.warning("메인 리포트에서 데이터를 로드해야 RM 전략 수립이 가능합니다.")
        return

    # [131실 특화 물리량 계산]
    TOTAL_ROOMS = 131
    days_in_month = 31 if selected_month in [1,3,5,7,8,10,12] else 30
    if selected_month == 2: days_in_month = 28
    
    fit_otb = float(target_sob.get('FIT_RMS', 0))
    grp_otb = float(target_sob.get('GRP_RMS', 0))
    current_otb = fit_otb + grp_otb
    auto_dow_index = float(dow_indices.get(datetime.now().weekday(), 1.0))

    # ----------------------------------------------------------------------
    # 2. 벤치마크 및 목표 설정 (Budget 자동 연동)
    # ----------------------------------------------------------------------
    st.write("### 📈 벤치마크 및 목표 설정")
    with st.container(border=True):
        col_tgt, col_ly = st.columns(2)
        with col_tgt:
            st.write("**🎯 당월 사업계획 (Budget)**")
            budget_rev = st.number_input("목표 매출 (만원)", value=auto_budget_man, step=500)
            budget_occ = st.slider("목표 점유율 (%)", 0, 100, 80)
        with col_ly:
            st.write("**📅 전년 동월 실적 (Last Year)**")
            # 기본적으로 예산의 95% 수준으로 제안
            ly_rev = st.number_input("전년 매출 (만원)", value=int(budget_rev * 0.95), step=500)
            ly_occ = st.slider("전년 점유율 (%)", 0, 100, 75)

    st.write("---")
    
    # ----------------------------------------------------------------------
    # 3. 수익 및 재고 전략 설정
    # ----------------------------------------------------------------------
    st.write("### 🛠️ 수익 및 재고 전략 설정")
    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            st.write("**📦 재고 최적화**")
            ooo_rooms = st.number_input("일평균 고장 객실(OOO)", 0, 10, 2)
            net_daily_cap = TOTAL_ROOMS - ooo_rooms
            net_total_cap = net_daily_cap * days_in_month
        with c2:
            st.write("**🔥 시장 모멘텀**")
            accel = st.slider("예약 가속도(Accel)", 0.5, 2.5, 1.1)
            rem_days = st.number_input("남은 기간(Days)", 1, 31, 7)
        with c3:
            st.write("**💰 수익 극대화**")
            current_adr = int(target_sob.get('FIT_REV', 0)/max(1, fit_otb)) if fit_otb > 0 else 240000
            target_adr = st.number_input("목표 ADR(단가)", 100000, 1000000, current_adr, step=5000)

    # ----------------------------------------------------------------------
    # 4. [정밀 엔진] 시뮬레이션 수식
    # ----------------------------------------------------------------------
    # 리드타임 보정: 임박할수록 예약 밀도 증가
    lt_factor = (1.0 + (1.0 / np.log1p(rem_days)))
    
    # 미래 예상 픽업량 계산
    future_pickup = actual_pace * auto_dow_index * accel * lt_factor * rem_days
    washout_rate = 0.03 # 3% 예약 이탈 가정
    
    # 가용 재고(131실-OOO) 내 최종 예상치
    final_rms = min(net_total_cap, (current_otb * (1 - washout_rate)) + future_pickup)
    final_rev_man = (final_rms * target_adr) / 10000 
    occ_pct = (final_rms / net_total_cap) * 100
    revpar = (final_rev_man * 10000) / net_total_cap

    # ----------------------------------------------------------------------
    # 5. KPI 대시보드
    # ----------------------------------------------------------------------
    st.divider()
    st.subheader("🏁 시뮬레이션 vs 벤치마크 결과")
    k1, k2, k3, k4 = st.columns(4)
    
    # 매출 달성률
    rev_gap = final_rev_man - budget_rev
    k1.metric("예상 매출액", f"{int(final_rev_man):,}만", f"{rev_gap:+,.0f} (Target 대비)")
    
    # 점유율 비교
    occ_gap = occ_pct - budget_occ
    k2.metric("예상 점유율(OCC)", f"{occ_pct:.1f}%", f"{occ_gap:+.1f}%p")
    
    # RevPAR 비교
    k3.metric("목표 RevPAR", f"₩{int(revpar):,}")
    
    # 전년 대비 성장률
    growth = ((final_rev_man / ly_rev) - 1) * 100 if ly_rev > 0 else 0
    k4.metric("전년 대비 성장", f"{growth:+.1f}%", f"{int(final_rev_man - ly_rev):+}만")

    # ----------------------------------------------------------------------
    # 6. 세부 분석 및 차트
    # ----------------------------------------------------------------------
    st.write("---")
    col_left, col_right = st.columns([1.5, 1])
    
    with col_left:
        st.write("#### 📊 목표 대비 Pace 시각화")
        chart_data = pd.DataFrame({
            "항목": ["전년 실적", "사업 계획", "현재 예측"],
            "매출액(만원)": [ly_rev, budget_rev, final_rev_man],
            "점유율(%)": [ly_occ, budget_occ, occ_pct]
        })
        st.bar_chart(chart_data.set_index("항목")["매출액(만원)"])
        
        # 상세 데이터 테이블
        st.write("#### 📑 세부 시뮬레이션 데이터")
        report_df = pd.DataFrame({
            "구분": ["총 가용 재고", "고장객실 손실", "실질 판매 가능(Net)", "현재 확정(OTB)", "미래 예상 픽업"],
            "객실수": [TOTAL_ROOMS * days_in_month, -(ooo_rooms * days_in_month), int(net_total_cap), int(current_otb), int(future_pickup)]
        })
        st.table(report_df)

    with col_right:
        st.write("#### 🎯 총지배인 전략 권고")
        if final_rev_man < budget_rev:
            st.error(f"⚠️ **Target 미달 비상**")
            st.write(f"현재 추세로는 목표 대비 {int(budget_rev - final_rev_man)}만원이 부족합니다. 즉시 OTA 프로모션 및 로컬 패키지 강화를 지시하세요.")
        elif final_rev_man >= budget_rev:
            st.success(f"🎊 **목표 달성 가시권**")
            st.write(f"사업 계획을 {int(final_rev_man - budget_rev)}만원 초과 달성할 것으로 보입니다. 이제부터는 저가 예약을 막고 단가를 높이는 Yield 전략으로 전환하세요.")
        
        st.info(f"💡 **요일 가중치:** 현재 요일 패턴은 {auto_dow_index:.2f}배 강도로 반영되었습니다.")

    # ----------------------------------------------------------------------
    # 7. 수익성 및 인건비 효율 가이드
    # ----------------------------------------------------------------------
    st.write("---")
    col_v1, col_v2 = st.columns(2)
    with col_v1:
        st.write("#### 💰 수익성 가이드라인")
        v_cost = st.slider("객실당 변동비(세탁/어메니티 등)", 10000, 50000, 25000, step=5000)
        net_margin = (final_rev_man * 10000) - (final_rms * v_cost)
        st.caption(f"예상 객실 공헌이익: ₩{int(net_margin/10000):,}만 (고정비 제외)")
    
    with col_v2:
        st.write("#### 🧑‍🤝‍🧑 운영 효율성 (Staffing)")
        # OCC에 따른 적정 청소 인력 가이드 (1인당 15객실 기준)
        needed_staff = np.ceil(final_rms / (days_in_month * 15))
        st.write(f"예상 점유율 기준, 일평균 **{needed_staff:.0f}명**의 룸 메이드 인력이 필요합니다.")
        st.caption("※ 외주 인력 배치 및 근무 스케줄 조정 근거로 활용하세요.")

if __name__ == "__main__":
    run_forecasting()
