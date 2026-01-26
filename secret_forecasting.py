import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def run_forecasting():
    st.title("🏛️ 총지배인(GM) 전략 의사결정 대시보드 v16.4")
    st.caption("핀셋 조정: 메인 탭 온북 실적 실시간 연동 + 잔여 판매일수 자동 동기화")

    # ----------------------------------------------------------------------
    # 1. 월 선택 및 날짜 기반 동적 설정
    # ----------------------------------------------------------------------
    selected_month = st.sidebar.selectbox("🎯 분석 대상 월", range(1, 13), index=datetime.now().month-1)
    
    # [자동 남은 기간 계산] 오늘 날짜 기준으로 해당 월 말일까지의 잔여 일수
    today = datetime.now()
    target_month_first_day = datetime(today.year, selected_month, 1)
    
    if selected_month > today.month:
        # 미래 월 분석 시: 오늘부터 해당 월 말일까지의 전체 기간
        next_month = datetime(today.year + (1 if selected_month == 12 else 0), (selected_month % 12) + 1, 1)
        last_day_of_target = (next_month - timedelta(days=1)).day
        days_to_target_start = (target_month_first_day - today).days
        auto_rem_days = days_to_target_start + last_day_of_target
    else:
        # 당월 분석 시: 오늘부터 말일까지 남은 일수
        if today.month == 12:
            last_day_of_month = 31
        else:
            last_day_of_month = (datetime(today.year, today.month + 1, 1) - timedelta(days=1)).day
        auto_rem_days = max(1, last_day_of_month - today.day)

    # ----------------------------------------------------------------------
    # 2. 데이터 호출 (메인 탭 실적 데이터 실시간 바인딩)
    # ----------------------------------------------------------------------
    target_sob = st.session_state.get(f"sob_{selected_month}")
    actual_pace = float(st.session_state.get(f"pace_{selected_month}", 0)) 
    dow_indices = st.session_state.get("historical_dow", {})
    
    # [3개년 벤치마크 데이터 구역]
    BUDGET_DATA = { 1: 514992575, 2: 786570856, 3: 529599040, 4: 695351004, 5: 903705440, 6: 808203820, 7: 1231949142, 8: 1388376999, 9: 952171506, 10: 897171539, 11: 667146771, 12: 804030110 }
    LY_DATA = { 1: 485000000, 2: 710000000, 3: 490000000, 4: 650000000, 5: 850000000, 6: 760000000, 7: 1150000000, 8: 1310000000, 9: 900000000, 10: 840000000, 11: 620000000, 12: 750000000 }
    PY_DATA = { 1: 420000000, 2: 650000000, 3: 430000000, 4: 580000000, 5: 790000000, 6: 710000000, 7: 1050000000, 8: 1220000000, 9: 830000000, 10: 780000000, 11: 570000000, 12: 690000000 }

    if not target_sob:
        st.warning(f"메인 리포트에서 {selected_month}월 실적 데이터를 먼저 로드해 주세요.")
        return

    # [중요] 실시간 실적(Actual OTB) 추출
    # 메인 탭에서 업로드한 데이터에서 현재 확정된 객실수와 매출액을 직접 가져옵니다.
    current_actual_rms = float(target_sob.get('FIT_RMS', 0) + target_sob.get('GRP_RMS', 0))
    current_actual_rev = float(target_sob.get('FIT_REV', 0) + target_sob.get('GRP_REV', 0))
    
    TOTAL_ROOMS = 131
    # 해당 월의 전체 일수 계산
    if selected_month == 12:
        days_in_month = 31
    else:
        days_in_month = (datetime(today.year, selected_month + 1, 1) - timedelta(days=1)).day
    
    auto_dow_index = float(dow_indices.get(today.weekday(), 1.0))

    # 3. 벤치마크 및 목표 설정
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
        with col_py:
            py_rev = st.number_input("전전년 매출 (만원)", value=cur_py_man, key=f"py_rev_{selected_month}")

    st.write("---")
    
    # 4. 시뮬레이션 컨트롤러 (가속도 및 ADR 설정)
    st.write("### 🛠️ 시뮬레이션 컨트롤러")
    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            ooo_rooms = st.number_input("일평균 고장(OOO)", 0, 10, 2, key=f"ooo_{selected_month}")
            net_total_cap = (TOTAL_ROOMS - ooo_rooms) * days_in_month
        with c2:
            st.write("**🔥 시장 가속도 (Event Mode)**")
            accel = st.slider("픽업 강도", 0.5, 5.0, 1.1, help="특수기(연휴 등)에는 2.0 이상 설정 권장", key=f"accel_{selected_month}")
            rem_days = st.number_input("남은 기간(Days)", 1, 365, int(auto_rem_days), key=f"rem_{selected_month}")
        with c3:
            # 현재까지의 실적 기반 평균 ADR 계산 (낚시 방지용 가이드)
            current_adr_actual = int(current_actual_rev / max(1, current_actual_rms))
            target_adr = st.number_input("미래 예상 ADR", 100000, 1000000, current_adr_actual if current_adr_actual > 100000 else 240000, step=5000, key=f"adr_{selected_month}")
            st.caption(f"💡 현재 실적 ADR: ₩{current_adr_actual:,}")

    # 5. [정밀 엔진] 수식 (실적 보존형)
    lt_factor = (1.0 + (1.0 / np.log1p(rem_days)))
    future_pickup_rms = actual_pace * auto_dow_index * accel * lt_factor * rem_days
    
    # 최종 예상 = (현재 실적 - 3% 취소 보정) + 미래 픽업
    final_rms = min(net_total_cap, (current_actual_rms * 0.97) + future_pickup_rms)
    
    # 최종 예상 매출 = 현재 실적 매출 + (추가 예상 객실 * 미래 예상 ADR)
    additional_rev = (final_rms - current_actual_rms) * target_adr
    final_rev_total = current_actual_rev + additional_rev
    final_rev_man = final_rev_total / 10000

    occ_pct = (final_rms / net_total_cap) * 100
    revpar = final_rev_total / net_total_cap

    # 6. 시각화 대시보드 (무삭제 탭 구성)
    st.divider()
    tab1, tab2, tab3 = st.tabs(["📊 성과 비교 (3개년)", "🔮 예약 곡선 (누적)", "💰 ADR 민감도 분석"])
    
    with tab1:
        st.subheader("🏁 3개년 매출 및 예측 비교")
        chart_df = pd.DataFrame({
            "구분": ["2024 실적", "2025 실적", "2026 목표", "2026 예측"],
            "매출액(만원)": [py_rev, ly_rev, budget_rev, final_rev_man]
        })
        st.bar_chart(chart_df.set_index("구분"))

    with tab2:
        st.subheader("🔮 예약 누적 시뮬레이션")
        daily_pickup = future_pickup_rms / max(1, rem_days)
        curve_data = [{"Day": i, "예상 누적 Rms": min(net_total_cap, (current_actual_rms*0.97) + (daily_pickup * i))} for i in range(rem_days + 1)]
        st.line_chart(pd.DataFrame(curve_data).set_index("Day"))

    with tab3:
        st.subheader("💰 ADR 조정 시나리오 분석")
        elasticity = 1.5
        adr_scenarios = []
        for rate in [0.8, 0.9, 1.0, 1.1, 1.2]:
            test_adr = target_adr * rate
            d_change = 1 - ((rate - 1) * elasticity)
            t_rms = min(net_total_cap, (current_actual_rms*0.97) + (future_pickup_rms * max(0, d_change)))
            t_rev = (current_actual_rev + (t_rms - current_actual_rms) * test_adr) / 10000
            adr_scenarios.append({"ADR": f"{int(rate*100)}%", "REV": int(test_rev), "RMS": int(t_rms)})
        st.line_chart(pd.DataFrame(adr_scenarios).set_index("ADR")[["REV", "RMS"]])

    # 7. KPI 대시보드
    st.divider()
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("최종 예상 매출", f"{int(final_rev_man):,}만", f"{final_rev_man - budget_rev:+,.0f}")
    k2.metric("현재 확정 실적(Actual)", f"₩{int(current_actual_rev/10000):,}만")
    k3.metric("추가 예상(Pickup)", f"+₩{int(additional_rev/10000):,}만")
    k4.metric("최종 예상 OCC", f"{occ_pct:.1f}%")

    # 8. 운영 및 수익성 지표 (무삭제)
    st.write("---")
    cv1, cv2 = st.columns(2)
    with cv1:
        v_cost = st.slider("객실당 변동비", 10000, 50000, 25000, step=5000, key=f"vc_{selected_month}")
        net_margin = final_rev_total - (final_rms * v_cost)
        st.write(f"💰 **예상 최종 공헌이익:** ₩{int(net_margin/10000):,}만")
    with cv2:
        needed_staff = np.ceil(final_rms / (days_in_month * 15))
        st.write(f"🧑‍🤝‍🧑 **필요 메이드 인력:** 일평균 {needed_staff:.0f}명")

if __name__ == "__main__":
    run_forecasting()
