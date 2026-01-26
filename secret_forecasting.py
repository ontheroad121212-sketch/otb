import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def run_forecasting():
    # 버전명을 v17.0으로 명시하여 반영 여부를 즉시 확인하게 함
    st.title("🏛️ 총지배인(GM) 전략 의사결정 대시보드 v17.0")
    st.caption("초정밀 분석: 리드타임 감쇄 곡선 시각화 + 구간별 요구 픽업 세분화")

    # 1. 월 선택 (기존 로직 유지)
    selected_month = st.sidebar.selectbox("🎯 분석 대상 월", range(1, 13), index=datetime.now().month-1)
    
    today = datetime.now()
    target_month_first_day = datetime(today.year, selected_month, 1)
    
    # [날짜 및 잔여일 자동 계산]
    if selected_month > today.month:
        next_month_val = (selected_month % 12) + 1
        year_val = today.year + (1 if selected_month == 12 else 0)
        last_day_of_target = (datetime(year_val, next_month_val, 1) - timedelta(days=1)).day
        days_to_target_start = (target_month_first_day - today).days
        auto_rem_days = days_to_target_start + last_day_of_target
    else:
        next_month_val = (today.month % 12) + 1
        year_val = today.year + (1 if today.month == 12 else 0)
        last_day_of_month = (datetime(year_val, next_month_val, 1) - timedelta(days=1)).day
        auto_rem_days = max(1, last_day_of_month - today.day)

    # 2. 데이터 호출
    target_sob = st.session_state.get(f"sob_{selected_month}")
    actual_pace = float(st.session_state.get(f"pace_{selected_month}", 0)) 
    dow_indices = st.session_state.get("historical_dow", {})
    BUDGET_DATA = { 1: 514992575, 2: 786570856, 3: 529599040, 4: 695351004, 5: 903705440, 6: 808203820, 7: 1231949142, 8: 1388376999, 9: 952171506, 10: 897171539, 11: 667146771, 12: 804030110 }

    if not target_sob:
        st.warning(f"메인 리포트에서 {selected_month}월 실적 데이터를 로드해 주세요.")
        return

    current_actual_rms = float(target_sob.get('FIT_RMS', 0) + target_sob.get('GRP_RMS', 0))
    current_actual_rev = float(target_sob.get('FIT_REV', 0) + target_sob.get('GRP_REV', 0))
    TOTAL_ROOMS = 131
    auto_dow_index = float(dow_indices.get(today.weekday(), 1.0))

    # 3. 목표 설정
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
            py_rev = st.number_input("전전년 매출 (만원)", value=int(budget_rev * 0.85), key=f"py_rev_{selected_month}")

    # 4. 시뮬레이션 컨트롤러
    st.write("---")
    st.write("### 🛠️ 시뮬레이션 및 리드타임 분석")
    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            ooo_rooms = st.number_input("일평균 고장(OOO)", 0, 10, 2, key=f"ooo_{selected_month}")
            net_total_cap = (TOTAL_ROOMS - ooo_rooms) * (last_day_of_target if selected_month > today.month else last_day_of_month)
        with c2:
            accel = st.slider("픽업 가속도 설정", 0.5, 5.0, 1.1, key=f"accel_{selected_month}")
            rem_days = st.number_input("남은 판매일수", 1, 365, int(auto_rem_days), key=f"rem_{selected_month}")
        with c3:
            current_adr_actual = int(current_actual_rev / max(1, current_actual_rms))
            target_adr = st.number_input("미래 예상 ADR", 100000, 1000000, current_adr_actual if current_adr_actual > 100000 else 240000, step=5000, key=f"adr_{selected_month}")

    # 5. [핵심 엔진] 리드타임 감쇄 정밀 계산
    lt_factor_base = (1.0 + (1.0 / np.log1p(rem_days)))
    decay_curve = []
    total_pickup = 0
    for d in range(1, rem_days + 1):
        # 감쇄 로직: 오늘(rem_days)부터 투숙 당일(1)까지 픽업 강도가 점진적으로 줄어듦
        decay_val = np.log1p(d) / np.log1p(rem_days)
        daily_p = actual_pace * auto_dow_index * accel * lt_factor_base * decay_val
        total_pickup += daily_p
        decay_curve.append(daily_p)

    final_rms = min(net_total_cap, current_actual_rms + total_pickup)
    final_rev_total = current_actual_rev + (max(0, final_rms - current_actual_rms) * target_adr)
    final_rev_man = final_rev_total / 10000

    # 역산 로직
    required_rev = (budget_rev * 10000) - current_actual_rev
    required_rms = required_rev / max(1, target_adr)
    required_daily_rms = required_rms / rem_days

    # 6. [신규 추가] 전략적 요건 정밀 분석 (이 섹션이 보여야 합니다!)
    st.divider()
    st.subheader("🎯 목표 달성 정밀 전략 요건 (Strategic Granularity)")
    
    s1, s2, s3 = st.columns(3)
    with s1:
        st.write("**📊 달성 시나리오**")
        achievement_rate = (final_rev_man / budget_rev) * 100
        st.metric("예상 달성률", f"{achievement_rate:.1f}%", f"{final_rev_man - budget_rev:+,.0f}만")
        st.caption(f"부족분(Gap): ₩{int(max(0, (budget_rev*10000)-final_rev_total)/10000):,}만")
    with s2:
        st.write("**🏃 요구 페이스**")
        avg_decay = np.mean([np.log1p(d)/np.log1p(rem_days) for d in range(1, rem_days+1)])
        st.metric("필요 일평균 예약", f"{required_daily_rms:.1f} 박", f"{(actual_pace * avg_decay) - required_daily_rms:+.1f}")
        st.caption(f"평균 감쇄 보정치: {avg_decay:.2f}")
    with s3:
        st.write("**🛡️ 수익 방어선**")
        needed_adr = (budget_rev * 10000 - current_actual_rev) / max(1, (final_rms - current_actual_rms))
        st.metric("Target ADR", f"₩{int(needed_adr/1000)}k", f"필요 OCC: { (required_rms + current_actual_rms)/net_total_cap*100:.1f}%")

    # [세분화 데이터 테이블]
    with st.expander("🔍 구간별 예약 픽업 감쇄 상세 분석 (Decay Breakdown)"):
        step = max(1, rem_days // 3)
        breakdown = []
        for i in range(0, rem_days, step):
            end_idx = min(i + step, rem_days)
            seg_p = sum(decay_curve[i:end_idx])
            breakdown.append({
                "구간 (남은일수)": f"{rem_days - i}일 ~ {rem_days - end_idx + 1}일 전",
                "예상 구간 픽업": f"{seg_p:.1f} 박",
                "평균 강도": f"{(seg_p/(end_idx-i)):.2f}"
            })
        st.table(pd.DataFrame(breakdown))

    # 7. 시각화 (무삭제)
    st.divider()
    tab1, tab2, tab3 = st.tabs(["📊 성과 비교 (3개년)", "🔮 리드타임 감쇄 곡선 (정밀)", "💰 ADR 민감도 분석"])
    
    with tab1:
        st.subheader("🏁 매출 및 예측 대조")
        chart_df = pd.DataFrame({
            "구분": ["2024 실적", "2025 실적", "2026 목표", "2026 예측"],
            "매출액(만원)": [py_rev, ly_rev, budget_rev, final_rev_man]
        })
        st.bar_chart(chart_df.set_index("구분"))

    with tab2:
        st.subheader("🔮 선형 예측 vs 리드타임 감쇄 반영 비교")
        linear_curve = [min(net_total_cap, current_actual_rms + (actual_pace * accel * i)) for i in range(rem_days + 1)]
        decay_curve_plot = [current_actual_rms]
        for i in range(1, rem_days + 1):
            decay_curve_plot.append(min(net_total_cap, current_actual_rms + sum(decay_curve[-i:])))
        
        comp_df = pd.DataFrame({"단순 선형": linear_curve, "감쇄 적용": decay_curve_plot})
        st.line_chart(comp_df)
        st.info("💡 입실일이 가까울수록 물리적 한계로 픽업이 완만해지는 감쇄 곡선입니다.")
        

    with tab3:
        st.subheader("💰 ADR 조정 시나리오")
        elasticity = 1.5
        adr_scenarios = []
        for rate in [0.8, 0.9, 1.0, 1.1, 1.2]:
            t_adr = target_adr * rate
            d_impact = max(0, 1 - ((rate-1)*elasticity))
            t_rms = min(net_total_cap, current_actual_rms + (total_pickup * d_impact))
            t_rev = (current_actual_rev + (max(0, t_rms - current_actual_rms)) * t_adr) / 10000
            adr_scenarios.append({"ADR": f"{int(rate*100)}%", "REV": int(t_rev)})
        st.line_chart(pd.DataFrame(adr_scenarios).set_index("ADR"))

    # 8. 운영 지표 (무삭제)
    st.write("---")
    cv1, cv2 = st.columns(2)
    with cv1:
        v_cost = st.slider("객실당 변동비", 10000, 50000, 25000, step=5000, key=f"vc_{selected_month}")
        margin = (final_rev_man * 10000) - (final_rms * v_cost)
        st.write(f"💰 **예상 최종 공헌이익:** ₩{int(margin/10000):,}만")
    with cv2:
        staff = np.ceil(final_rms / (30 * 15))
        st.write(f"🧑‍🤝‍🧑 **필요 메이드 인력:** {staff:.0f}명")

if __name__ == "__main__":
    run_forecasting()
