import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def run_forecasting():
    st.title("🏛️ 총지배인(GM) 전략 의사결정 대시보드 v16.3")
    st.caption("핀셋 동기화 완료: 월별 데이터 자동 매칭 + 잔여 판매일수 자동 계산")

    # ----------------------------------------------------------------------
    # 1. 월 선택 및 날짜 기반 자동 설정 (핀셋 조정 핵심)
    # ----------------------------------------------------------------------
    selected_month = st.sidebar.selectbox("🎯 분석 대상 월", range(1, 13), index=datetime.now().month-1)
    
    # [자동 남은 기간 계산 로직]
    today = datetime.now()
    target_month_first_day = datetime(today.year, selected_month, 1)
    
    # 선택한 월이 현재 월보다 미래라면: (이번 달 남은 일수 + 미래 월의 전체 일수)
    # 선택한 월이 현재 월이라면: (이번 달 남은 일수)
    if selected_month > today.month:
        last_day_of_target = (datetime(today.year, selected_month + 1, 1) - timedelta(days=1)).day if selected_month < 12 else 31
        days_to_target_start = (target_month_first_day - today).days
        auto_rem_days = days_to_target_start + last_day_of_target
    else:
        last_day_of_month = (datetime(today.year, today.month + 1, 1) - timedelta(days=1)).day if today.month < 12 else 31
        auto_rem_days = max(1, last_day_of_month - today.day)

    # 2. 데이터 호출 및 인벤토리 설정
    target_sob = st.session_state.get(f"sob_{selected_month}")
    actual_pace = float(st.session_state.get(f"pace_{selected_month}", 0)) 
    dow_indices = st.session_state.get("historical_dow", {})
    
    # [데이터 관리 구역 - 3개년 동기화]
    BUDGET_DATA = { 1: 514992575, 2: 786570856, 3: 529599040, 4: 695351004, 5: 903705440, 6: 808203820, 7: 1231949142, 8: 1388376999, 9: 952171506, 10: 897171539, 11: 667146771, 12: 804030110 }
    LY_DATA = { 1: 485000000, 2: 710000000, 3: 490000000, 4: 650000000, 5: 850000000, 6: 760000000, 7: 1150000000, 8: 1310000000, 9: 900000000, 10: 840000000, 11: 620000000, 12: 750000000 }
    PY_DATA = { 1: 420000000, 2: 650000000, 3: 430000000, 4: 580000000, 5: 790000000, 6: 710000000, 7: 1050000000, 8: 1220000000, 9: 830000000, 10: 780000000, 11: 570000000, 12: 690000000 }

    if not target_sob:
        st.warning(f"메인 리포트에서 {selected_month}월 탭을 클릭하여 실적 데이터를 먼저 로드해 주세요.")
        return

    TOTAL_ROOMS = 131
    days_in_month = (datetime(today.year, selected_month + 1, 1) - timedelta(days=1)).day if selected_month < 12 else 31
    
    fit_otb = float(target_sob.get('FIT_RMS', 0))
    grp_otb = float(target_sob.get('GRP_RMS', 0))
    current_otb = fit_otb + grp_otb
    auto_dow_index = float(dow_indices.get(today.weekday(), 1.0))

    # 3. 벤치마크 및 목표 설정 (Key값 동적 할당으로 새로고침 에러 방지)
    st.write(f"### 📈 {selected_month}월 목표 및 실적 대조")
    cur_budget_man = int(BUDGET_DATA.get(selected_month, 500000000) / 10000)
    cur_ly_man = int(LY_DATA.get(selected_month, 450000000) / 10000)
    cur_py_man = int(PY_DATA.get(selected_month, 400000000) / 10000)

    with st.container(border=True):
        col_tgt, col_ly, col_py = st.columns(3)
        with col_tgt:
            budget_rev = st.number_input("목표 매출 (만원)", value=cur_budget_man, key=f"b_rev_{selected_month}")
            budget_occ = st.slider("목표 점유율 (%)", 0, 100, 85, key=f"b_occ_{selected_month}")
        with col_ly:
            ly_rev = st.number_input("전년 매출 (만원)", value=cur_ly_man, key=f"ly_rev_{selected_month}")
            ly_occ = st.slider("전년 점유율 (%)", 0, 100, 80, key=f"ly_occ_{selected_month}")
        with col_py:
            py_rev = st.number_input("전전년 매출 (만원)", value=cur_py_man, key=f"py_rev_{selected_month}")

    st.write("---")
    
    # 4. 수익 및 재고 전략 설정 (남은 기간 자동 반영)
    st.write("### 🛠️ 시뮬레이션 컨트롤러")
    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            st.write("**📦 재고 최적화**")
            ooo_rooms = st.number_input("일평균 고장(OOO)", 0, 10, 2, key=f"ooo_{selected_month}")
            net_total_cap = (TOTAL_ROOMS - ooo_rooms) * days_in_month
        with c2:
            st.write("**🔥 시장 모멘텀**")
            accel = st.slider("예약 가속도(Accel)", 0.5, 2.5, 1.1, key=f"accel_{selected_month}")
            rem_days = st.number_input("남은 기간(Days)", 1, 365, int(auto_rem_days), key=f"rem_{selected_month}")
        with c3:
            st.write("**💰 수익 극대화**")
            current_adr = int(target_sob.get('FIT_REV', 0)/max(1, fit_otb)) if fit_otb > 0 else 240000
            target_adr = st.number_input("설정 ADR", 100000, 1000000, current_adr, step=5000, key=f"adr_{selected_month}")

    # 5. [정밀 엔진] 시뮬레이션 로직
    lt_factor = (1.0 + (1.0 / np.log1p(rem_days)))
    future_pickup = actual_pace * auto_dow_index * accel * lt_factor * rem_days
    washout_rate = 0.03
    
    final_rms = min(net_total_cap, (current_otb * (1 - washout_rate)) + future_pickup)
    final_rev_man = (final_rms * target_adr) / 10000 
    occ_pct = (final_rms / net_total_cap) * 100
    revpar = (final_rev_man * 10000) / net_total_cap

    # 6. 시각화 대시보드 (기존 완벽한 로직 유지)
    st.divider()
    tab1, tab2, tab3 = st.tabs(["📊 성과 비교 (3개년)", "🔮 예약 곡선 (누적)", "💰 ADR 민감도 분석"])
    
    with tab1:
        st.subheader("🏁 매출 및 예측 비교")
        chart_df = pd.DataFrame({
            "구분": ["2024 실적", "2025 실적", "2026 목표", "2026 예측"],
            "매출액(만원)": [py_rev, ly_rev, budget_rev, final_rev_man]
        })
        st.bar_chart(chart_df.set_index("구분"))

    with tab2:
        st.subheader("🔮 예약 누적 시뮬레이션")
        daily_pickup_avg = future_pickup / rem_days
        curve_data = [{"Day": i, "예상 누적 예약(Rms)": min(net_total_cap, (current_otb * 0.97) + (daily_pickup_avg * i))} for i in range(rem_days + 1)]
        st.line_chart(pd.DataFrame(curve_data).set_index("Day"))

    with tab3:
        st.subheader("💰 ADR 조정 시나리오 분석")
        elasticity = 1.5
        adr_scenarios = []
        for rate in [0.8, 0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15, 1.2]:
            test_adr = target_adr * rate
            p_diff = rate - 1
            demand_impact = max(0, 1 - (p_diff * elasticity))
            test_pickup = future_pickup * demand_impact
            test_rms = min(net_total_cap, (current_otb * 0.97) + test_pickup)
            test_rev = (test_rms * test_adr) / 10000
            adr_scenarios.append({"ADR변화": f"{int(rate*100)}%", "RMS": int(test_rms), "REV": int(test_rev)})
        sc_df = pd.DataFrame(adr_scenarios).set_index("ADR변화")
        cs1, cs2 = st.columns(2)
        with cs1: st.line_chart(sc_df["RMS"])
        with cs2: st.line_chart(sc_df["REV"])

    # 7. KPI 및 운영 지표
    st.divider()
    k1, k2, k3, k4 = st.columns(4)
    rev_gap = final_rev_man - budget_rev
    k1.metric("예상 매출액", f"{int(final_rev_man):,}만", f"{rev_gap:+,.0f}")
    growth_ly = ((final_rev_man / ly_rev) - 1) * 100 if ly_rev > 0 else 0
    k2.metric("vs 2025 성장률", f"{growth_ly:+.1f}%", f"{int(final_rev_man - ly_rev):+}만")
    k3.metric("예상 RevPAR", f"₩{int(revpar):,}")
    k4.metric("예상 점유율", f"{occ_pct:.1f}%", f"{occ_pct - budget_occ:+.1f}%p")

    st.write("---")
    cv1, cv2 = st.columns(2)
    with cv1:
        v_cost = st.slider("객실당 변동비", 10000, 50000, 25000, step=5000, key=f"vc_{selected_month}")
        net_margin = (final_rev_man * 10000) - (final_rms * v_cost)
        st.caption(f"예상 공헌이익: ₩{int(net_margin/10000):,}만")
    with cv2:
        needed_staff = np.ceil(final_rms / (days_in_month * 15))
        st.write(f"🧑‍🤝‍🧑 필요 메이드: 일평균 **{needed_staff:.0f}명**")

if __name__ == "__main__":
    run_forecasting()
