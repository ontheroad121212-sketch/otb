import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def run_forecasting():
    st.title("🏛️ 총지배인(GM) 전략 의사결정 대시보드 v17.6")
    st.caption("데이터 직결: 메인 탭 실적(Actual) 실시간 바인딩 및 목표 가시화")

    # 1. 월 선택 및 동적 설정
    selected_month = st.sidebar.selectbox("🎯 분석 대상 월", range(1, 13), index=datetime.now().month-1)
    today = datetime.now()
    
    # [날짜 계산 로직]
    next_month_date = datetime(today.year + (1 if selected_month == 12 else 0), (selected_month % 12) + 1, 1)
    last_day_of_target = (next_month_date - timedelta(days=1)).day
    
    if selected_month > today.month:
        target_month_first_day = datetime(today.year, selected_month, 1)
        auto_rem_days = (target_month_first_day - today).days + last_day_of_target
    else:
        auto_rem_days = max(1, last_day_of_target - today.day)

    # ----------------------------------------------------------------------
    # 2. [데이터 핀셋 수정] 메인 탭 실적 데이터 실시간 바인딩
    # ----------------------------------------------------------------------
    target_sob = st.session_state.get(f"sob_{selected_month}")
    
    # 데이터가 없을 경우 가이드 출력
    if not target_sob or not isinstance(target_sob, dict):
        st.warning(f"⚠️ 메인 리포트에서 {selected_month}월 탭을 먼저 클릭하여 원장 데이터를 로드해 주세요.")
        return

    # 메인 탭 세션 데이터에서 실적 직접 추출 (Key값 정밀 매칭)
    current_actual_rms = float(target_sob.get('FIT_RMS', 0) + target_sob.get('GRP_RMS', 0))
    current_actual_rev = float(target_sob.get('FIT_REV', 0) + target_sob.get('GRP_REV', 0))
    
    raw_pace = float(st.session_state.get(f"pace_{selected_month}", 0))
    actual_pace = raw_pace if raw_pace > 0 else 5.5 # 시뮬레이션 기본값
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
            # 실적 기반 ADR 자동 계산
            avg_adr_actual = int(current_actual_rev / max(1, current_actual_rms))
            target_adr = st.number_input("설정 ADR", 100000, 1000000, avg_adr_actual if avg_adr_actual > 100000 else 240000, step=5000)

    # 5. [엔진] 리드타임 감쇄 계산
    lt_factor_base = (1.0 + (1.0 / np.log1p(rem_days)))
    decay_curve = []
    total_pickup = 0
    for d in range(1, rem_days + 1):
        decay_val = np.log1p(rem_days - d + 1) / np.log1p(rem_days)
        daily_p = actual_pace * accel * lt_factor_base * decay_val
        total_pickup += daily_p
        decay_curve.append(daily_p)

    final_rms = min(net_total_cap, current_actual_rms + total_pickup)
    additional_rev = (final_rms - current_actual_rms) * target_adr
    final_rev_total = current_actual_rev + additional_pickup_rev if 'additional_pickup_rev' in locals() else current_actual_rev + additional_rev
    final_rev_man = final_rev_total / 10000

    # 6. [시각화 보강] 실적 vs 예측 브리핑
    st.divider()
    st.subheader("📊 실시간 실적 분석 및 전략 브리핑")
    
    # 지배인님, 여기 지표가 실시간으로 변해야 합니다.
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.write("**현재 확정 매출 (Actual)**")
        st.metric("Confirmed REV", f"₩{int(current_actual_rev/10000):,}만", "On-the-Books")
    with col_b:
        st.write("**미래 예상 매출 (Forecast)**")
        st.metric("Forecasted REV", f"₩{int(additional_rev/10000):,}만", f"+{int(total_pickup)} Rms")
    with col_c:
        st.write("**최종 달성 예상 (Total)**")
        prob = (final_rev_man / budget_rev) * 100
        st.metric("Expected Total", f"₩{int(final_rev_man):,}만", f"{prob:.1f}% 달성")

    # 7. 시각화 탭 (무삭제)
    st.divider()
    t1, t2, t3 = st.tabs(["📈 실적/예측 혼합 차트", "🔮 리드타임 감쇄 곡선", "💰 수익 민감도"])
    
    with t1:
        st.subheader("🏁 누적 매출 구성 분석 (Actual vs Forecast)")
        # 실적과 예측을 쌓아서 보여주는 시각화
        mix_df = pd.DataFrame({
            "구분": ["현재 확정 실적", "추가 예상 매출", "전체 목표"],
            "매출액(만원)": [int(current_actual_rev/10000), int(additional_rev/10000), budget_rev]
        })
        st.bar_chart(mix_df.set_index("구분"))
        

    with t2:
        st.subheader("🔮 리드타임 감쇄 기반 예약 흐름")
        accum_rms = []
        curr = current_actual_rms
        for p in decay_curve:
            curr += p
            accum_rms.append(min(net_total_cap, curr))
        
        comp_df = pd.DataFrame({
            "현재 실적 바닥": [current_actual_rms] * (rem_days + 1),
            "감쇄 적용 곡선": [current_actual_rms] + accum_rms
        })
        st.line_chart(comp_df)

    with t3:
        # ADR 민감도 로직 보존
        sens_data = []
        for r in [0.8, 0.9, 1.0, 1.1, 1.2]:
            t_rms_sens = min(net_total_cap, current_actual_rms + (total_pickup * (1 - (r-1)*1.5)))
            sens_data.append({"ADR계수": f"{int(r*100)}%", "최종매출(만)": int((current_actual_rev + (t_rms_sens - current_actual_rms)*(target_adr*r))/10000)})
        st.line_chart(pd.DataFrame(sens_data).set_index("ADR계수"))

    # 8. 운영 지표 (무삭제)
    st.write("---")
    cola, colb = st.columns(2)
    with cola:
        v_cost = st.slider("객실당 변동비", 10000, 50000, 25000, step=5000)
        margin = final_rev_total - (final_rms * v_cost)
        st.write(f"💰 **최종 예상 공헌이익:** ₩{int(margin/10000):,}만")
    with colb:
        staff = np.ceil(final_rms / (last_day_of_target * 15))
        st.write(f"🧑‍🤝‍🧑 **필요 메이드 인력:** {staff:.0f}명")

if __name__ == "__main__":
    run_forecasting()
