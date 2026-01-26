import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def run_forecasting():
    st.title("🏛️ 총지배인(GM) 전략 의사결정 대시보드 v17.1")
    st.caption("초정밀 분석: 데이터 바인딩 수정 완료 + 구간별 감쇄 상세 분석")

    # 1. 월 선택
    selected_month = st.sidebar.selectbox("🎯 분석 대상 월", range(1, 13), index=datetime.now().month-1)
    
    today = datetime.now()
    target_month_first_day = datetime(today.year, selected_month, 1)
    
    # [날짜 및 잔여일 자동 계산]
    next_month_val = (selected_month % 12) + 1
    year_val = today.year + (1 if selected_month == 12 else 0)
    last_day_of_target = (datetime(year_val, next_month_val, 1) - timedelta(days=1)).day
    
    if selected_month > today.month:
        days_to_target_start = (target_month_first_day - today).days
        auto_rem_days = days_to_target_start + last_day_of_target
    else:
        auto_rem_days = max(1, last_day_of_target - today.day)

    # 2. 데이터 호출 및 안정화
    target_sob = st.session_state.get(f"sob_{selected_month}")
    # 픽업 데이터가 0일 경우 시뮬레이션을 위해 기본값 1.0 혹은 지배인님이 메인에서 보시는 값 바인딩
    raw_pace = float(st.session_state.get(f"pace_{selected_month}", 0))
    actual_pace = raw_pace if raw_pace > 0 else 5.0 # 데이터 부재 시 시뮬레이션용 기본값
    
    dow_indices = st.session_state.get("historical_dow", {})
    auto_dow_index = float(dow_indices.get(today.weekday(), 1.0))

    if not target_sob:
        st.warning(f"⚠️ 메인 리포트에서 {selected_month}월 실적 데이터를 로드해 주세요.")
        return

    current_actual_rms = float(target_sob.get('FIT_RMS', 0) + target_sob.get('GRP_RMS', 0))
    current_actual_rev = float(target_sob.get('FIT_REV', 0) + target_sob.get('GRP_REV', 0))
    TOTAL_ROOMS = 131

    # 3. 목표 설정 (생략 없음)
    st.write(f"### 📈 {selected_month}월 전략적 목표 설정")
    BUDGET_DATA = { 1: 514992575, 2: 786570856, 3: 529599040, 4: 695351004, 5: 903705440, 6: 808203820, 7: 1231949142, 8: 1388376999, 9: 952171506, 10: 897171539, 11: 667146771, 12: 804030110 }
    cur_budget_man = int(BUDGET_DATA.get(selected_month, 500000000) / 10000)
    
    with st.container(border=True):
        col_tgt, col_ly, col_py = st.columns(3)
        with col_tgt:
            budget_rev = st.number_input("목표 매출 (만원)", value=cur_budget_man, key=f"b_rev_{selected_month}")
            budget_occ = st.slider("목표 점유율 (%)", 0, 100, 85)
        with col_ly:
            ly_rev = st.number_input("전년 매출 (만원)", value=int(budget_rev * 0.92))
        with col_py:
            py_rev = st.number_input("전전년 매출 (만원)", value=int(budget_rev * 0.85))

    # 4. 시뮬레이션 컨트롤러
    st.write("---")
    st.write("### 🛠️ 시뮬레이션 및 리드타임 분석")
    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            ooo_rooms = st.number_input("일평균 고장(OOO)", 0, 10, 2)
            net_total_cap = (TOTAL_ROOMS - ooo_rooms) * last_day_of_target
        with c2:
            accel = st.slider("픽업 가속도 설정", 0.5, 5.0, 1.5, key=f"accel_{selected_month}")
            rem_days = st.number_input("남은 판매일수", 1, 365, int(auto_rem_days))
        with c3:
            current_adr_actual = int(current_actual_rev / max(1, current_actual_rms))
            target_adr = st.number_input("미래 예상 ADR", 100000, 1000000, current_adr_actual if current_adr_actual > 100000 else 240000, step=5000)

    # 5. [정밀 엔진] 리드타임 감쇄 정밀 계산
    lt_factor_base = (1.0 + (1.0 / np.log1p(rem_days)))
    decay_curve = []
    accum_rms = []
    total_pickup = 0
    
    # 지배인님, 여기서 'd'는 입실까지 남은 날짜의 진행도를 의미합니다.
    for d in range(1, rem_days + 1):
        # 감쇄 수식 보강: 오늘로부터 멀어질수록(미래일수록) 픽업 강도가 높고, 가까워질수록 낮아짐
        decay_val = np.log1p(rem_days - d + 1) / np.log1p(rem_days)
        daily_p = actual_pace * auto_dow_index * accel * lt_factor_base * decay_val
        total_pickup += daily_p
        decay_curve.append(daily_p)
        accum_rms.append(min(net_total_cap, current_actual_rms + total_pickup))

    final_rms = min(net_total_cap, current_actual_rms + total_pickup)
    final_rev_total = current_actual_rev + (max(0, final_rms - current_actual_rms) * target_adr)
    final_rev_man = final_rev_total / 10000

    # 6. 전략적 요건 정밀 분석 (이 섹션이 핵심입니다!)
    st.divider()
    st.subheader("🎯 목표 달성 정밀 전략 요건 (Strategic Granularity)")
    
    s1, s2, s3 = st.columns(3)
    with s1:
        st.write("**📊 달성 시나리오**")
        achievement_rate = (final_rev_man / budget_rev) * 100
        st.metric("예상 달성률", f"{achievement_rate:.1f}%", f"{final_rev_man - budget_rev:+,.0f}만")
    with s2:
        st.write("**🏃 요구 페이스**")
        required_daily_rms = ((budget_rev * 10000) - current_actual_rev) / max(1, target_adr) / rem_days
        st.metric("필요 일평균 예약", f"{required_daily_rms:.1f} 박", f"{actual_pace - required_daily_rms:+.1f}")
    with s3:
        st.write("**🛡️ 수익 방어선**")
        needed_adr = (budget_rev * 10000 - current_actual_rev) / max(1, (final_rms - current_actual_rms))
        st.metric("Target ADR", f"₩{int(needed_adr/1000)}k", f"필요 OCC: {((budget_rev*10000-current_actual_rev)/target_adr + current_actual_rms)/net_total_cap*100:.1f}%")

    # [세분화 데이터 테이블]
    with st.expander("🔍 구간별 예약 픽업 감쇄 상세 분석 (Decay Breakdown)", expanded=True):
        step = max(1, rem_days // 3)
        breakdown_data = []
        for i in range(0, rem_days, step):
            end_idx = min(i + step, rem_days)
            seg_p = sum(decay_curve[i:end_idx])
            breakdown_data.append({
                "구간 (순번)": f"{i//step + 1}단계",
                "잔여일수 범위": f"{rem_days - i}일 전 ~ {rem_days - end_idx + 1}일 전",
                "예상 구간 픽업": f"{seg_p:.1f} 박",
                "구간 평균 강도": f"{(seg_p/(end_idx-i)):.2f}"
            })
        st.table(pd.DataFrame(breakdown_data))

    # 7. 시각화 (무삭제)
    st.divider()
    tab1, tab2, tab3 = st.tabs(["📊 성과 비교 (3개년)", "🔮 리드타임 감쇄 곡선 (정밀)", "💰 ADR 민감도 분석"])
    
    with tab1:
        st.bar_chart(pd.DataFrame({"구분": ["25 실적", "26 목표", "26 예측"], "매출액": [ly_rev, budget_rev, final_rev_man]}).set_index("구분"))

    with tab2:
        st.subheader("🔮 리드타임 감쇄 반영 예약 곡선")
        # 선형 예측과 비교
        linear_curve = [min(net_total_cap, current_actual_rms + (actual_pace * accel * i)) for i in range(rem_days + 1)]
        comp_df = pd.DataFrame({"단순 선형": linear_curve, "감쇄 적용": [current_actual_rms] + accum_rms})
        st.line_chart(comp_df)
        

    with tab3:
        st.subheader("💰 ADR 조정 시나리오")
        adr_scenarios = []
        for rate in [0.8, 0.9, 1.0, 1.1, 1.2]:
            t_adr = target_adr * rate
            t_rms = min(net_total_cap, current_actual_rms + (total_pickup * (1 - (rate-1)*1.5)))
            adr_scenarios.append({"ADR": f"{int(rate*100)}%", "REV": int((current_actual_rev + (t_rms - current_actual_rms)*t_adr)/10000)})
        st.line_chart(pd.DataFrame(adr_scenarios).set_index("ADR"))

    # 8. 운영 지표
    st.write("---")
    cv1, cv2 = st.columns(2)
    with cv1:
        v_cost = st.slider("객실당 변동비", 10000, 50000, 25000, step=5000)
        st.write(f"💰 예상 공헌이익: ₩{int((final_rev_man*10000 - final_rms*v_cost)/10000):,}만")
    with cv2:
        staff = np.ceil(final_rms / (last_day_of_target * 15))
        st.write(f"🧑‍🤝‍🧑 필요 메이드 인력: {staff:.0f}명")

if __name__ == "__main__":
    run_forecasting()
