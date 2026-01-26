import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def run_forecasting():
    st.title("🏛️ 총지배인(GM) 전략 의사결정 대시보드 v18.0")
    st.caption("최종 고도화: 목표 달성 역산(Daily Target) + 현 추세 도착지 시나리오 예측")

    # 1. 월 선택 및 동적 날짜 설정
    selected_month = st.sidebar.selectbox("🎯 분석 대상 월", range(1, 13), index=datetime.now().month-1)
    today = datetime.now()
    
    target_month_first_day = datetime(today.year, selected_month, 1)
    if selected_month == 12:
        next_month_date = datetime(today.year + 1, 1, 1)
    else:
        next_month_date = datetime(today.year, selected_month + 1, 1)
    
    last_day_of_target = (next_month_date - timedelta(days=1)).day
    
    if selected_month > today.month:
        auto_rem_days = (target_month_first_day - today).days + last_day_of_target
    else:
        auto_rem_days = max(1, last_day_of_target - today.day)

    # 2. [데이터 연동] 메인 탭 실시간 온북(OTB) 실적 불러오기
    target_sob = st.session_state.get(f"sob_{selected_month}")
    if not target_sob or not isinstance(target_sob, dict):
        st.warning(f"⚠️ 메인 리포트에서 {selected_month}월 탭을 먼저 클릭하여 데이터를 로드해 주세요.")
        return

    # [실시간 온북 지표]
    current_actual_rms = float(target_sob.get('FIT_RMS', 0) + target_sob.get('GRP_RMS', 0))
    current_actual_rev = float(target_sob.get('FIT_REV', 0) + target_sob.get('GRP_REV', 0))
    
    raw_pace = float(st.session_state.get(f"pace_{selected_month}", 0))
    actual_pace = raw_pace if raw_pace > 0 else 5.5 
    dow_indices = st.session_state.get("historical_dow", {i: 1.0 for i in range(7)})
    TOTAL_ROOMS = 131

    # 3. 목표 설정
    st.write(f"### 📈 {selected_month}월 전략적 목표 설정")
    BUDGET_DATA = { 1: 514992575, 2: 786570856, 3: 529599040, 4: 695351004, 5: 903705440, 6: 808203820, 7: 1231949142, 8: 1388376999, 9: 952171506, 10: 897171539, 11: 667146771, 12: 804030110 }
    cur_budget_man = int(BUDGET_DATA.get(selected_month, 500000000) / 10000)
    
    with st.container(border=True):
        col_tgt, col_ly, col_py = st.columns(3)
        with col_tgt:
            budget_rev = st.number_input("달성 목표 매출 (만원)", value=cur_budget_man, key=f"b_rev_{selected_month}")
            budget_occ = st.slider("목표 점유율 (%)", 0, 100, 85)
        with col_ly:
            ly_rev = st.number_input("전년 매출 (만원)", value=int(budget_rev * 0.92))
        with col_py:
            py_rev = st.number_input("전전년 매출 (만원)", value=int(budget_rev * 0.85))

    # 4. 시뮬레이션 컨트롤러
    st.write("---")
    st.write("### 🛠️ 초정밀 시뮬레이터")
    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            ooo_rooms = st.number_input("일평균 고장(OOO)", 0, 10, 2)
            net_total_cap = (TOTAL_ROOMS - ooo_rooms) * last_day_of_target
        with c2:
            accel = st.slider("픽업 가속도(Accel)", 0.5, 5.0, 1.5)
            rem_days = st.number_input("남은 판매일수", 1, 365, int(auto_rem_days))
        with c3:
            avg_adr_actual = int(current_actual_rev / max(1, current_actual_rms)) if current_actual_rms > 0 else 240000
            target_adr = st.number_input("설정 ADR", 100000, 1000000, avg_adr_actual if avg_adr_actual > 100000 else 240000, step=5000)

    # 5. [엔진] 픽업 및 시나리오 계산
    lt_factor_base = (1.0 + (1.0 / np.log1p(rem_days)))
    decay_curve = []
    total_pickup = 0
    for d in range(1, rem_days + 1):
        decay_val = np.log1p(rem_days - d + 1) / np.log1p(rem_days)
        daily_p = actual_pace * accel * lt_factor_base * decay_val
        total_pickup += daily_p
        decay_curve.append(daily_p)

    final_rms = min(net_total_cap, current_actual_rms + total_pickup)
    final_rev_total = current_actual_rev + (max(0, final_rms - current_actual_rms) * target_adr)
    
    # [지배인님 요청 추가 1: 목표 달성 역산]
    gap_rev = (budget_rev * 10000) - current_actual_rev
    req_pickup_rms = gap_rev / max(1, target_adr)
    req_daily_rms = req_pickup_rms / rem_days

    # ----------------------------------------------------------------------
    # 6. [신규 섹션] GM 목표 달성 커맨드 센터 (추가 요청 반영)
    # ----------------------------------------------------------------------
    st.divider()
    st.subheader("🎯 GM 목표 달성 전략 요건 (Strategic Command)")
    
    # 현재 온북 상태와 필요한 공격력 시각화
    col_otb, col_gap, col_req = st.columns(3)
    with col_otb:
        st.metric("현재 온북 매출액", f"₩{int(current_actual_rev/10000):,}만")
        st.caption(f"확정 객실: {int(current_actual_rms)} Rms")
    with col_gap:
        st.metric("추가 필요 매출액", f"₩{int(max(0, gap_rev)/10000):,}만")
        st.caption(f"필요 추가 객실: {int(req_pickup_rms)} Rms")
    with col_req:
        # 핵심 지표: 하루에 몇 박을 더 팔아야 하는가
        st.metric("🎯 일일 요구 픽업", f"{req_daily_rms:.1f} 박 / Day", f"at ₩{int(target_adr/1000)}k")
        st.caption(f"남은 {rem_days}일간 매일 달성해야 하는 수치")

    # [지배인님 요청 추가 2: 현 추세 도착지 시나리오 예측]
    st.write("#### 🔮 현재 온북 속도 기반 도착지 시나리오")
    s_col1, s_col2 = st.columns(2)
    with s_col1:
        # 현 추세 달성 예상
        prob = (final_rev_total / (budget_rev * 10000)) * 100
        delta_rev = (final_rev_total / 10000) - budget_rev
        st.metric("현 추세 최종 예상 매출", f"₩{int(final_rev_total/10000):,}만", f"{delta_rev:+,.0f}만")
    with s_col2:
        # 달성 가능성 판단
        status = "목표 달성 가시권" if prob >= 100 else "전략 수정 필요(부족)"
        st.metric("목표 달성 가망성", f"{prob:.1f}%", status)

    # 7. 초정밀 전략 가이드 (기존 기능 유지)
    st.divider()
    with st.expander("🔍 구간별 정밀 전략 가이드 (Breakdown)", expanded=True):
        step = max(1, rem_days // 3)
        breakdown = []
        for i in range(0, rem_days, step):
            end_idx = min(i + step, rem_days)
            seg_rms = sum(decay_curve[i:end_idx])
            seg_adv_adr = target_adr * (1.1 if i < rem_days/3 else 1.0 if i < 2*rem_days/3 else 0.9)
            breakdown.append({
                "리드타임 구간": f"{rem_days - i}일 ~ {rem_days - end_idx + 1}일 전",
                "예상 픽업": f"{seg_rms:.1f} 박",
                "권장 ADR": f"₩{int(seg_adv_adr/1000)}k",
                "액션": "공격적 인상" if i < rem_days/3 else "시장가 유지" if i < 2*rem_days/3 else "공격적 픽업"
            })
        st.table(pd.DataFrame(breakdown))

    # 8. 시각화 (무삭제)
    t1, t2, t3 = st.tabs(["📊 Actual vs Forecast", "🔮 예약 곡선", "💰 수익 민감도"])
    with t1:
        mix_df = pd.DataFrame({
            "구분": ["현재 확정(Actual)", "추가 예측(Forecast)", "전체 목표(Budget)"],
            "매출액(만원)": [int(current_actual_rev/10000), int((final_rev_total - current_actual_rev)/10000), budget_rev]
        })
        st.bar_chart(mix_df.set_index("구분"))
        [Image of a waterfall chart showing actual hotel revenue versus forecasted revenue for the month]

    with t2:
        accum_rms = []
        curr = current_actual_rms
        for p in decay_curve:
            curr += p
            accum_rms.append(min(net_total_cap, curr))
        comp_df = pd.DataFrame({"단순 선형": [current_actual_rms + (actual_pace * accel * i) for i in range(rem_days + 1)], "감쇄 적용": [current_actual_rms] + accum_rms})
        st.line_chart(comp_df)

    with t3:
        sens_data = []
        for r in [0.8, 0.9, 1.0, 1.1, 1.2]:
            t_rms_s = min(net_total_cap, current_actual_rms + (total_pickup * (1 - (r-1)*1.5)))
            sens_data.append({"ADR계수": f"{int(r*100)}%", "최종매출(만)": int((current_actual_rev + (t_rms_s - current_actual_rms)*(target_adr*r))/10000)})
        st.line_chart(pd.DataFrame(sens_data).set_index("ADR계수"))

    # 9. 운영 지표
    st.write("---")
    cola, colb = st.columns(2)
    with cola:
        v_cost = st.slider("객실당 변동비", 10000, 50000, 25000)
        net_margin = (final_rev_total) - (final_rms * v_cost)
        st.write(f"💰 **예상 최종 공헌이익:** ₩{int(net_margin/10000):,}만")
    with colb:
        needed_staff = np.ceil(final_rms / (last_day_of_target * 15))
        st.write(f"🧑‍🤝‍🧑 **필요 메이드 인력:** {needed_staff:.0f}명")

if __name__ == "__main__":
    run_forecasting()
