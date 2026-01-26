import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def run_forecasting():
    st.title("🏛️ 총지배인(GM) 전략 의사결정 대시보드 v16.9")
    st.caption("고도화: 리드타임 감쇄 로직 + 목표 달성 역산(Required Pace) 엔진")

    # 1. 월 선택 및 날짜 기반 동적 설정
    selected_month = st.sidebar.selectbox("🎯 분석 대상 월", range(1, 13), index=datetime.now().month-1)
    
    today = datetime.now()
    target_month_first_day = datetime(today.year, selected_month, 1)
    
    # [날짜 및 잔여일 자동 계산]
    if selected_month > today.month:
        # 미래 월: 오늘부터 그 달 말일까지 (예: 1/26에 2월 선택 시 30일+잔여일)
        next_month = datetime(today.year + (1 if selected_month == 12 else 0), (selected_month % 12) + 1, 1)
        last_day_of_target = (next_month - timedelta(days=1)).day
        days_to_target_start = (target_month_first_day - today).days
        auto_rem_days = days_to_target_start + last_day_of_target
    else:
        # 당월: 오늘부터 말일까지
        last_day_of_month = (datetime(today.year + (1 if today.month == 12 else 0), (today.month % 12) + 1, 1) - timedelta(days=1)).day
        auto_rem_days = max(1, last_day_of_month - today.day)

    # 2. 데이터 호출 (메인 탭 실적 연동)
    target_sob = st.session_state.get(f"sob_{selected_month}")
    actual_pace = float(st.session_state.get(f"pace_{selected_month}", 0)) 
    dow_indices = st.session_state.get("historical_dow", {})
    
    BUDGET_DATA = { 1: 514992575, 2: 786570856, 3: 529599040, 4: 695351004, 5: 903705440, 6: 808203820, 7: 1231949142, 8: 1388376999, 9: 952171506, 10: 897171539, 11: 667146771, 12: 804030110 }
    
    if not target_sob:
        st.warning(f"메인 리포트에서 {selected_month}월 실적 데이터를 먼저 로드해 주세요.")
        return

    # [실시간 확정 실적]
    current_actual_rms = float(target_sob.get('FIT_RMS', 0) + target_sob.get('GRP_RMS', 0))
    current_actual_rev = float(target_sob.get('FIT_REV', 0) + target_sob.get('GRP_REV', 0))
    
    TOTAL_ROOMS = 131
    days_in_month = (datetime(today.year + (1 if selected_month == 12 else 0), (selected_month % 12) + 1, 1) - timedelta(days=1)).day
    auto_dow_index = float(dow_indices.get(today.weekday(), 1.0))

    # 3. 벤치마크 및 목표 설정
    st.write(f"### 📈 {selected_month}월 전략적 목표 설정")
    cur_budget_man = int(BUDGET_DATA.get(selected_month, 500000000) / 10000)

    with st.container(border=True):
        col_tgt, col_ly, col_py = st.columns(3)
        with col_tgt:
            budget_rev = st.number_input("달성 목표 매출 (만원)", value=cur_budget_man, key=f"b_rev_{selected_month}")
            budget_occ = st.slider("목표 점유율 (%)", 0, 100, 85, key=f"b_occ_{selected_month}")
        with col_ly:
            ly_rev = st.number_input("전년 매출 (만원)", value=int(budget_rev * 0.92), key=f"ly_rev_{selected_month}")
        with col_py:
            cur_py_man = int(budget_rev * 0.85)
            py_rev = st.number_input("전전년 매출 (만원)", value=cur_py_man, key=f"py_rev_{selected_month}")

    st.write("---")
    
    # 4. 시뮬레이션 컨트롤러
    st.write("### 🛠️ 시뮬레이션 및 리드타임 분석")
    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            ooo_rooms = st.number_input("일평균 고장(OOO)", 0, 10, 2, key=f"ooo_{selected_month}")
            net_total_cap = (TOTAL_ROOMS - ooo_rooms) * days_in_month
        with c2:
            accel = st.slider("픽업 가속도 설정", 0.5, 5.0, 1.1, key=f"accel_{selected_month}")
            rem_days = st.number_input("잔여 판매일수", 1, 365, int(auto_rem_days), key=f"rem_{selected_month}")
        with c3:
            current_adr_actual = int(current_actual_rev / max(1, current_actual_rms))
            target_adr = st.number_input("미래 예상 ADR", 100000, 1000000, current_adr_actual if current_adr_actual > 100000 else 240000, step=5000, key=f"adr_{selected_month}")

    # 5. [정밀 엔진] 리드타임 감쇄 및 역산 로직
    # [A] 리드타임 감쇄(Time-decay): 입실 임박 시 픽업 속도가 둔화되는 물리적 현상 반영
    time_decay = np.log1p(rem_days) / np.log1p(auto_rem_days) if auto_rem_days > 0 else 1.0
    adjusted_pickup_rms = actual_pace * auto_dow_index * accel * time_decay * rem_days
    
    final_rms = min(net_total_cap, current_actual_rms + adjusted_pickup_rms)
    final_rev_total = current_actual_rev + (max(0, final_rms - current_actual_rms) * target_adr)
    final_rev_man = final_rev_total / 10000

    # [B] 목표 달성 역산 (Required Pace)
    required_total_rev = (budget_rev * 10000)
    required_pickup_rev = max(0, required_total_rev - current_actual_rev)
    required_pickup_rms = required_pickup_rev / max(1, target_adr)
    required_daily_rms = required_pickup_rms / rem_days

    # 6. 전략 요건 및 추세 분석 (신규 보강)
    st.divider()
    st.subheader("🎯 목표 달성 전략 요건 (Strategic Insight)")
    
    s1, s2, s3 = st.columns(3)
    with s1:
        st.write("**현재 추세 기반 예상**")
        prob = (final_rev_man / budget_rev) * 100
        st.metric("Expected Achievement", f"{prob:.1f}%", f"{final_rev_man - budget_rev:+,.0f}만")
    with s2:
        st.write("**일평균 필요 예약량**")
        current_effective_pace = actual_pace * time_decay
        color = "normal" if current_effective_pace >= required_daily_rms else "inverse"
        st.metric("Required Pickup", f"{required_daily_rms:.1f} 박", f"{current_effective_pace - required_daily_rms:+.1f} (Pace)", delta_color=color)
    with s3:
        st.write("**재고 가용성 분석**")
        needed_occ = (required_pickup_rms + current_actual_rms) / net_total_cap * 100
        feasibility = "가능" if needed_occ <= 100 else "불가능(재고부족)"
        st.metric("Target Feasibility", feasibility, f"필요 OCC: {needed_occ:.1f}%")

    # 7. 시각화 (무삭제 탭 구성)
    st.divider()
    tab1, tab2, tab3 = st.tabs(["📊 성과 비교 (3개년)", "🔮 예약 곡선 (누적)", "💰 ADR 민감도 분석"])
    
    with tab1:
        st.subheader("🏁 매출 및 예측 대조")
        chart_df = pd.DataFrame({
            "구분": ["2024 실적", "2025 실적", "2026 목표", "2026 예측"],
            "매출액(만원)": [py_rev, ly_rev, budget_rev, final_rev_man]
        })
        st.bar_chart(chart_df.set_index("구분"))

    with tab2:
        st.subheader("🔮 리드타임 감쇄 반영 예약 곡선")
        daily_pace = adjusted_pickup_rms / max(1, rem_days)
        curve_data = [{"Day": i, "예상 누적 Rms": min(net_total_cap, current_actual_rms + (daily_pace * i))} for i in range(rem_days + 1)]
        st.line_chart(pd.DataFrame(curve_data).set_index("Day"))
        st.caption("💡 입실일이 가까울수록 물리적 한계로 인해 픽업 강도가 완만해지는 곡선입니다.")

    with tab3:
        st.subheader("💰 ADR 조정 시나리오")
        elasticity = 1.5
        adr_scenarios = []
        for rate in [0.8, 0.9, 1.0, 1.1, 1.2]:
            t_adr = target_adr * rate
            d_impact = max(0, 1 - ((rate-1)*elasticity))
            t_rms = min(net_total_cap, current_actual_rms + (adjusted_pickup_rms * d_impact))
            t_rev = (current_actual_rev + (max(0, t_rms - current_actual_rms)) * t_adr) / 10000
            adr_scenarios.append({"ADR": f"{int(rate*100)}%", "REV": int(t_rev)})
        st.line_chart(pd.DataFrame(adr_scenarios).set_index("ADR"))

    # 8. 운영 및 수익성 지표 (무삭제)
    st.write("---")
    cv1, cv2 = st.columns(2)
    with cv1:
        v_cost = st.slider("객실당 변동비", 10000, 50000, 25000, step=5000, key=f"vc_{selected_month}")
        net_margin = (final_rev_man * 10000) - (final_rms * v_cost)
        st.caption(f"💰 예상 최종 공헌이익: ₩{int(net_margin/10000):,}만")
    with cv2:
        staff = np.ceil(final_rms / (days_in_month * 15))
        st.write(f"🧑‍🤝‍🧑 필요 메이드 인력: 일평균 **{staff:.0f}명**")

if __name__ == "__main__":
    run_forecasting()
