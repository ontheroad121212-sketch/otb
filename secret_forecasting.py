import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def run_forecasting():
    st.title("🏛️ 총지배인(GM) 전략 의사결정 대시보드 v17.5")
    st.caption("초정밀 고도화: 구간별 권장 ADR + 주중·주말 픽업 믹스 + 인벤토리 경보")

    # 1. 월 선택 및 동적 설정
    selected_month = st.sidebar.selectbox("🎯 분석 대상 월", range(1, 13), index=datetime.now().month-1)
    today = datetime.now()
    target_month_first_day = datetime(today.year, selected_month, 1)
    
    next_month_val = (selected_month % 12) + 1
    year_val = today.year + (1 if selected_month == 12 else 0)
    last_day_of_target = (datetime(year_val, next_month_val, 1) - timedelta(days=1)).day
    
    if selected_month > today.month:
        auto_rem_days = (target_month_first_day - today).days + last_day_of_target
    else:
        auto_rem_days = max(1, last_day_of_target - today.day)

    # 2. 데이터 호출 및 안정화
    target_sob = st.session_state.get(f"sob_{selected_month}")
    raw_pace = float(st.session_state.get(f"pace_{selected_month}", 0))
    actual_pace = raw_pace if raw_pace > 0 else 5.5 # 데이터 부재 시 시뮬레이션 기본값
    dow_indices = st.session_state.get("historical_dow", {0:0.8, 1:0.7, 2:0.7, 3:0.9, 4:1.3, 5:1.5, 6:1.1})
    
    if not target_sob:
        st.warning(f"⚠️ 메인 리포트에서 {selected_month}월 실적 데이터를 먼저 로드해 주세요.")
        return

    current_actual_rms = float(target_sob.get('FIT_RMS', 0) + target_sob.get('GRP_RMS', 0))
    current_actual_rev = float(target_sob.get('FIT_REV', 0) + target_sob.get('GRP_REV', 0))
    TOTAL_ROOMS = 131

    # 3. 목표 설정
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
            avg_adr = int(current_actual_rev / max(1, current_actual_rms))
            target_adr = st.number_input("설정 ADR", 100000, 1000000, avg_adr if avg_adr > 100000 else 240000, step=5000)

    # 5. [초정밀 엔진] 리드타임 감쇄 및 주중/주말 믹스 계산
    lt_factor_base = (1.0 + (1.0 / np.log1p(rem_days)))
    decay_curve = []
    accum_rms = []
    total_pickup = 0
    
    for d in range(1, rem_days + 1):
        # 감쇄 계수 적용
        decay_val = np.log1p(rem_days - d + 1) / np.log1p(rem_days)
        daily_p = actual_pace * accel * lt_factor_base * decay_val
        total_pickup += daily_p
        decay_curve.append(daily_p)
        accum_rms.append(min(net_total_cap, current_actual_rms + total_pickup))

    final_rms = min(net_total_cap, current_actual_rms + total_pickup)
    final_rev_man = (current_actual_rev + (max(0, final_rms - current_actual_rms) * target_adr)) / 10000

    # 6. [세분화 섹션] GM 전용 전략 브리핑 (이것저것 정밀하게 추가!)
    st.divider()
    st.subheader("🎯 총지배인 전용 초정밀 전략 가이드")
    
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.write("**📈 예상 최종 점유율**")
        final_occ = (final_rms / net_total_cap) * 100
        st.metric("Final OCC", f"{final_occ:.1f}%", f"{final_occ - budget_occ:+.1f}%p")
    with m2:
        st.write("**💰 목표 달성 필요 단가**")
        # 남은 목표액을 남은 예상 객실수로 나눈 역산 ADR
        needed_rev = (budget_rev * 10000) - current_actual_rev
        needed_pickup_rms = final_rms - current_actual_rms
        req_adr = needed_rev / max(1, needed_pickup_rms)
        st.metric("Required ADR", f"₩{int(req_adr/1000)}k", f"{int((req_adr/target_adr-1)*100):+d}%")
    with m3:
        st.write("**⚡ 인벤토리 소진 속도**")
        burn_rate = (total_pickup / rem_days) / (TOTAL_ROOMS/7) # 주간 공급량 대비 일평균 판매량 비율
        st.metric("Burn Rate", f"{burn_rate:.2f}x", "High" if burn_rate > 1.2 else "Normal")
    with m4:
        st.write("**📊 주중/주말 픽업 믹스**")
        we_ratio = (dow_indices[4]+dow_indices[5]) / sum(dow_indices.values()) * 100
        st.metric("WE Pickup Ratio", f"{we_ratio:.1f}%", "Weekend Heavy")

    # [초정밀 구간별 권장 전략 테이블]
    with st.expander("🔍 구간별 타겟 ADR 및 권장 액션 (Strategic Breakdown)", expanded=True):
        step = max(1, rem_days // 3)
        breakdown = []
        for i in range(0, rem_days, step):
            end_idx = min(i + step, rem_days)
            seg_rms = sum(decay_curve[i:end_idx])
            # 구간별로 입실일이 가까울수록 ADR을 방어하거나 공격적으로 제안
            seg_adv_adr = target_adr * (1.1 if i < rem_days/3 else 1.0 if i < 2*rem_days/3 else 0.9)
            breakdown.append({
                "리드타임 구간": f"{rem_days - i}일 ~ {rem_days - end_idx + 1}일 전",
                "예상 픽업": f"{seg_rms:.1f} 박",
                "권장 ADR": f"₩{int(seg_adv_adr/1000)}k",
                "전략": "공격적 인상" if i < rem_days/3 else "시장가 유지" if i < 2*rem_days/3 else "Last-minute 방어"
            })
        st.table(pd.DataFrame(breakdown))

    # 7. 시각화 (무삭제 원칙)
    st.divider()
    t1, t2, t3 = st.tabs(["📊 성과 비교", "🔮 정밀 예약 곡선", "💰 수익 민감도"])
    
    with t1:
        st.bar_chart(pd.DataFrame({"구분": ["LY 실적", "26 목표", "26 예측"], "매출액": [ly_rev, budget_rev, final_rev_man]}).set_index("구분"))

    with t2:
        st.subheader("🔮 리드타임 감쇄 기반 예약 흐름 시뮬레이션")
        
        comp_df = pd.DataFrame({
            "단순 선형(현상유지)": [current_actual_rms + (actual_pace * accel * i) for i in range(rem_days + 1)],
            "감쇄 적용(현실반영)": [current_actual_rms] + accum_rms
        })
        st.line_chart(comp_df)
        st.info("💡 입실일이 임박할수록 픽업 강도가 완만해지는 패턴을 반영한 '감쇄 적용' 곡선을 주목하십시오.")

    with t3:
        st.subheader("💰 ADR 변화에 따른 최종 매출 변화")
        sens_data = []
        for r in [0.8, 0.9, 1.0, 1.1, 1.2]:
            t_adr_sens = target_adr * r
            t_rms_sens = min(net_total_cap, current_actual_rms + (total_pickup * (1 - (r-1)*1.5)))
            sens_data.append({"ADR계수": f"{int(r*100)}%", "최종매출(만)": int((current_actual_rev + (t_rms_sens - current_actual_rms)*t_adr_sens)/10000)})
        st.line_chart(pd.DataFrame(sens_data).set_index("ADR계수"))

    # 8. 운영 지표 (무삭제)
    st.write("---")
    cola, colb = st.columns(2)
    with cola:
        v_cost = st.slider("객실당 변동비", 10000, 50000, 25000, step=5000)
        net_margin = (final_rev_man * 10000) - (final_rms * v_cost)
        st.write(f"💰 **예상 최종 공헌이익:** ₩{int(net_margin/10000):,}만")
    with colb:
        needed_staff = np.ceil(final_rms / (last_day_of_target * 15))
        st.write(f"🧑‍🤝‍🧑 **필요 메이드 인력:** {needed_staff:.0f}명")

if __name__ == "__main__":
    run_forecasting()
