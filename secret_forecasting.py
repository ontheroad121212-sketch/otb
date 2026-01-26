import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def run_forecasting():
    st.title("🏛️ 총지배인(GM) 전략 의사결정 대시보드 v17.0")
    st.caption("초정밀 분석: 리드타임 감쇄 곡선 시각화 + 구간별 요구 픽업 세분화")

    # 1. 월 선택 및 날짜 기반 동적 설정 (기존 로직 보존)
    selected_month = st.sidebar.selectbox("🎯 분석 대상 월", range(1, 13), index=datetime.now().month-1)
    
    today = datetime.now()
    target_month_first_day = datetime(today.year, selected_month, 1)
    
    # [날짜 및 잔여일 자동 계산]
    if selected_month > today.month:
        next_month = datetime(today.year + (1 if selected_month == 12 else 0), (selected_month % 12) + 1, 1)
        last_day_of_target = (next_month - timedelta(days=1)).day
        days_to_target_start = (target_month_first_day - today).days
        auto_rem_days = days_to_target_start + last_day_of_target
    else:
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
            st.write("**📦 재고 최적화**")
            ooo_rooms = st.number_input("일평균 고장(OOO)", 0, 10, 2, key=f"ooo_{selected_month}")
            net_total_cap = (TOTAL_ROOMS - ooo_rooms) * days_in_month
        with c2:
            st.write("**🔥 시장 모멘텀 (가속도)**")
            accel = st.slider("픽업 강도 설정", 0.5, 5.0, 1.1, key=f"accel_{selected_month}")
            rem_days = st.number_input("남은 판매일수", 1, 365, int(auto_rem_days), key=f"rem_{selected_month}")
        with c3:
            st.write("**💰 수익 극대화**")
            current_adr_actual = int(current_actual_rev / max(1, current_actual_rms))
            target_adr = st.number_input("미래 예상 ADR", 100000, 1000000, current_adr_actual if current_adr_actual > 100000 else 240000, step=5000, key=f"adr_{selected_month}")

    # 5. [정밀 엔진 고도화] 리드타임 감쇄 정밀 시뮬레이션
    lt_factor_base = (1.0 + (1.0 / np.log1p(rem_days)))
    
    # 입실일에 가까워질수록 픽업 속도가 줄어드는 시계열 감쇄 데이터 생성
    decay_curve = []
    total_expected_pickup = 0
    for d in range(1, rem_days + 1):
        # 당일 픽업 감쇄 계수 (d가 1에 가까울수록 입실 임박, d가 rem_days일수록 오늘)
        # 역순으로 계산하여 오늘부터 입실일까지의 감쇄를 표현
        current_decay = np.log1p(d) / np.log1p(rem_days)
        daily_pickup = actual_pace * auto_dow_index * accel * lt_factor_base * current_decay
        total_expected_pickup += daily_pickup
        decay_curve.append(daily_pickup)

    final_rms = min(net_total_cap, current_actual_rms + total_expected_pickup)
    final_rev_total = current_actual_rev + (max(0, final_rms - current_actual_rms) * target_adr)
    final_rev_man = final_rev_total / 10000

    # 목표 달성 역산 (Required Pace)
    required_rev = (budget_rev * 10000) - current_actual_rev
    required_rms = required_rev / max(1, target_adr)
    required_daily_rms = required_rms / rem_days

    # 6. [세분화 보강] 전략적 요건 정밀 분석 섹션
    st.divider()
    st.subheader("🎯 목표 달성 정밀 전략 요건 (Strategic Granularity)")
    
    s1, s2, s3 = st.columns(3)
    with s1:
        st.write("**📊 달성 시나리오 분석**")
        achievement_rate = (final_rev_man / budget_rev) * 100
        st.metric("예상 달성률", f"{achievement_rate:.1f}%", f"{final_rev_man - budget_rev:+,.0f}만")
        gap_to_target = max(0, (budget_rev * 10000) - final_rev_total)
        st.caption(f"부족분(Gap): ₩{int(gap_to_target/10000):,}만")
        
    with s2:
        st.write("**🏃 요구 픽업 페이스**")
        avg_decay_factor = np.mean([np.log1p(d) / np.log1p(rem_days) for d in range(1, rem_days + 1)])
        effective_pace = actual_pace * avg_decay_factor
        color = "normal" if effective_pace >= required_daily_rms else "inverse"
        st.metric("필요 일평균 예약", f"{required_daily_rms:.1f} 박", f"{effective_pace - required_daily_rms:+.1f} (현재 추세)", delta_color=color)
        st.caption(f"평균 감쇄 보정치: {avg_decay_factor:.2f}")
        
    with s3:
        st.write("**🛡️ 재고 및 수익 방어선**")
        needed_occ = (required_rms + current_actual_rms) / net_total_cap * 100
        needed_adr = (budget_rev * 10000 - current_actual_rev) / max(1, (final_rms - current_actual_rms))
        st.metric("Target ADR", f"₩{int(needed_adr/1000)}k", f"필요 OCC: {needed_occ:.1f}%")
        st.caption("※ 현재 OCC 예측 하에서 목표 달성에 필요한 단가")

    # [세분화 추가] 구간별 리드타임 감쇄 상세 테이블
    with st.expander("🔍 구간별 예약 픽업 감쇄 상세 분석 (Decay Breakdown)"):
        # 3단계 구간으로 나누어 분석
        step = max(1, rem_days // 3)
        breakdown = []
        for i in range(0, rem_days, step):
            end_idx = min(i + step, rem_days)
            segment_pickup = sum(decay_curve[i:end_idx])
            breakdown.append({
                "구간 (남은일수)": f"{rem_days - i}일 ~ {rem_days - end_idx + 1}일 전",
                "예상 구간 픽업량": f"{segment_pickup:.1f} 박",
                "구간 평균 픽업 강도": f"{(segment_pickup/(end_idx-i)):.2f}"
            })
        st.table(pd.DataFrame(breakdown))

    # 7. 시각화 (무삭제 및 고도화)
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
        # 비교를 위해 단순 선형 곡선도 생성
        linear_curve = []
        decay_adjusted_curve = []
        curr_lin = current_actual_rms
        curr_dec = current_actual_rms
        
        # 오늘부터 입실일까지 (Day 0 = 오늘)
        for i in range(rem_days + 1):
            # 선형 (단순 합산)
            lin_rms = min(net_total_cap, current_actual_rms + (actual_pace * accel * i))
            linear_curve.append(lin_rms)
            
            # 감쇄 반영 (누적)
            if i == 0:
                decay_adjusted_curve.append(current_actual_rms)
            else:
                # decay_curve는 역순(입실일 임박이 앞)이므로 슬라이싱 주의
                # 오늘부터의 누적을 위해 뒤에서부터 합산
                adj_pickup = sum(decay_curve[-(i):]) 
                decay_adjusted_curve.append(min(net_total_cap, current_actual_rms + adj_pickup))
        
        curve_comparison = pd.DataFrame({
            "단순 선형 예측": linear_curve,
            "리드타임 감쇄 적용": decay_adjusted_curve
        })
        st.line_chart(curve_comparison)
        st.caption("💡 노란색(감쇄 적용) 곡선이 입실일이 다가올수록 완만해지는 실제 예약 패턴에 가깝습니다.")

    with tab3:
        st.subheader("💰 ADR 조정 시나리오")
        elasticity = 1.5
        adr_scenarios = []
        for rate in [0.8, 0.9, 1.0, 1.1, 1.2]:
            t_adr = target_adr * rate
            d_impact = max(0, 1 - ((rate-1)*elasticity))
            t_rms = min(net_total_cap, current_actual_rms + (total_expected_pickup * d_impact))
            t_rev = (current_actual_rev + (max(0, t_rms - current_actual_rms)) * t_adr) / 10000
            adr_scenarios.append({"ADR": f"{int(rate*100)}%", "REV": int(t_rev)})
        st.line_chart(pd.DataFrame(adr_scenarios).set_index("ADR"))

    # 8. 운영 지표 (무삭제)
    st.write("---")
    cv1, cv2 = st.columns(2)
    with cv1:
        v_cost = st.slider("객실당 변동비", 10000, 50000, 25000, step=5000, key=f"vc_{selected_month}")
        margin = (final_rev_man * 10000) - (final_rms * v_cost)
        st.caption(f"💰 예상 최종 공헌이익: ₩{int(margin/10000):,}만")
    with cv2:
        staff = np.ceil(final_rms / (days_in_month * 15))
        st.write(f"🧑‍🤝‍🧑 필요 메이드: 일평균 **{staff:.0f}명**")

if __name__ == "__main__":
    run_forecasting()
