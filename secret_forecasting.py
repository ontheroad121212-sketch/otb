import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def run_forecasting():
    st.title("🏛️ 총지배인(GM) 전략 의사결정 대시보드 v15.0")
    st.caption("무삭제 통합판: 3개년 비교 + 인벤토리 최적화 + 미래 예측 곡선 시뮬레이션")

    # 1. 데이터 호출 및 인벤토리 설정
    selected_month = st.sidebar.selectbox("🎯 분석 대상 월", range(1, 13), index=datetime.now().month-1)
    target_sob = st.session_state.get(f"sob_{selected_month}")
    actual_pace = float(st.session_state.get(f"pace_{selected_month}", 0)) 
    dow_indices = st.session_state.get("historical_dow", {})
    
    # [데이터 관리 구역] - 지배인님이 나중에 이 숫자만 바꾸시면 됩니다.
    BUDGET_DATA = {
        1: 514992575, 2: 786570856, 3: 529599040, 4: 695351004, 5: 903705440, 6: 808203820,
        7: 1231949142, 8: 1388376999, 9: 952171506, 10: 897171539, 11: 667146771, 12: 804030110
    }
    LY_DATA = { 1: 485000000, 2: 710000000, 3: 490000000, 4: 650000000, 5: 850000000, 6: 760000000, 7: 1150000000, 8: 1310000000, 9: 900000000, 10: 840000000, 11: 620000000, 12: 750000000 }
    PY_DATA = { 1: 420000000, 2: 650000000, 3: 430000000, 4: 580000000, 5: 790000000, 6: 710000000, 7: 1050000000, 8: 1220000000, 9: 830000000, 10: 780000000, 11: 570000000, 12: 690000000 }

    if not target_sob:
        st.warning(f"메인 리포트에서 {selected_month}월 실적 데이터를 먼저 로드해 주세요.")
        return

    # [131실 특화 물리량 계산]
    TOTAL_ROOMS = 131
    days_in_month = 31 if selected_month in [1,3,5,7,8,10,12] else 30
    if selected_month == 2: days_in_month = 28
    
    fit_otb = float(target_sob.get('FIT_RMS', 0))
    grp_otb = float(target_sob.get('GRP_RMS', 0))
    current_otb = fit_otb + grp_otb
    auto_dow_index = float(dow_indices.get(datetime.now().weekday(), 1.0))

    # 2. 벤치마크 및 목표 설정 (3개년 자동 매칭)
    st.write("### 📈 벤치마크 및 목표 설정")
    cur_budget_man = int(BUDGET_DATA.get(selected_month, 500000000) / 10000)
    cur_ly_man = int(LY_DATA.get(selected_month, 450000000) / 10000)
    cur_py_man = int(PY_DATA.get(selected_month, 400000000) / 10000)

    with st.container(border=True):
        col_tgt, col_ly, col_py = st.columns(3)
        with col_tgt:
            st.write(f"**🎯 2026 목표 (Budget)**")
            budget_rev = st.number_input("목표 매출 (만원)", value=cur_budget_man, step=500, key="b_rev")
            budget_occ = st.slider("목표 점유율 (%)", 0, 100, 85, key="b_occ")
        with col_ly:
            st.write(f"**📅 2025 실적 (LY)**")
            ly_rev = st.number_input("전년 매출 (만원)", value=cur_ly_man, step=500, key="ly_rev")
            ly_occ = st.slider("전년 점유율 (%)", 0, 100, 80, key="ly_occ")
        with col_py:
            st.write(f"**📜 2024 실적 (PY)**")
            py_rev = st.number_input("전전년 매출 (만원)", value=cur_py_man, step=500, key="py_rev")

    st.write("---")
    
    # 3. 수익 및 재고 전략 설정
    st.write("### 🛠️ 수익 및 재고 전략 설정")
    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            st.write("**📦 재고 최적화**")
            ooo_rooms = st.number_input("일평균 고장 객실(OOO)", 0, 10, 2)
            net_total_cap = (TOTAL_ROOMS - ooo_rooms) * days_in_month
        with c2:
            st.write("**🔥 시장 모멘텀**")
            accel = st.slider("예약 가속도(Accel)", 0.5, 2.5, 1.1)
            rem_days = st.number_input("남은 기간(Days)", 1, 31, 7)
        with c3:
            st.write("**💰 수익 극대화**")
            current_adr = int(target_sob.get('FIT_REV', 0)/max(1, fit_otb)) if fit_otb > 0 else 240000
            target_adr = st.number_input("목표 ADR(단가)", 100000, 1000000, current_adr, step=5000)

    # 4. [정밀 엔진] 시뮬레이션 및 곡선 데이터 생성
    lt_factor = (1.0 + (1.0 / np.log1p(rem_days)))
    future_pickup = actual_pace * auto_dow_index * accel * lt_factor * rem_days
    washout_rate = 0.03
    
    final_rms = min(net_total_cap, (current_otb * (1 - washout_rate)) + future_pickup)
    final_rev_man = (final_rms * target_adr) / 10000 
    occ_pct = (final_rms / net_total_cap) * 100
    revpar = (final_rev_man * 10000) / net_total_cap

    # --- [보강] 미래 예측 예약 곡선 데이터 생성 ---
    daily_pickup_avg = future_pickup / rem_days
    curve_data = []
    for i in range(rem_days + 1):
        # 오늘부터 입실일까지 누적 예약이 쌓여가는 흐름 계산
        sim_rms = min(net_total_cap, (current_otb * (1 - washout_rate)) + (daily_pickup_avg * i))
        curve_data.append({"남은날짜": i, "예상 누적 예약(Rms)": sim_rms})
    curve_df = pd.DataFrame(curve_data).set_index("남은날짜")

    # 5. [신규 시각화] 예측 곡선 대시보드
    st.divider()
    st.subheader("🔮 미래 예측 예약 곡선 (Booking Forecast Curve)")
    
    chart_col, stat_col = st.columns([2, 1])
    with chart_col:
        # 예약이 쌓이는 흐름을 차트로 표시
        st.line_chart(curve_df)
        st.caption(f"💡 현재 {int(current_otb)}실에서 시작하여 일평균 {daily_pickup_avg:.1f}실씩 예약이 추가될 것으로 예측됩니다.")
    
    with stat_col:
        st.write("#### 🎯 마감 분석")
        rem_inv = net_total_cap - final_rms
        st.metric("최종 예상 OCC", f"{occ_pct:.1f}%")
        st.metric("잔여 가용 객실", f"{int(max(0, rem_inv))}실")
        if occ_pct > 95: st.error("🚨 만실 임박: 즉시 단가 상향")
        elif occ_pct > 80: st.success("✅ 안정적인 픽업 페이스")

    # 6. 종합 KPI 대시보드 (성장률 및 비교 분석)
    st.divider()
    st.subheader("🏁 종합 성과 분석 (2024-2026)")
    k1, k2, k3, k4 = st.columns(4)
    
    rev_gap = final_rev_man - budget_rev
    k1.metric("예상 매출", f"{int(final_rev_man):,}만", f"{rev_gap:+,.0f} (Target)")
    
    growth_ly = ((final_rev_man / ly_rev) - 1) * 100 if ly_rev > 0 else 0
    k2.metric("vs 2025 (YoY)", f"{growth_ly:+.1f}%", f"{int(final_rev_man - ly_rev):+}만")
    
    k3.metric("예상 RevPAR", f"₩{int(revpar):,}")
    
    growth_py = ((final_rev_man / py_rev) - 1) * 100 if py_rev > 0 else 0
    k4.metric("vs 2024 (YoY)", f"{growth_py:+.1f}%", f"{int(final_rev_man - py_rev):+}만")

    # 7. 세부 분석 및 전략 가이드
    st.write("---")
    col_left, col_right = st.columns([1.5, 1])
    
    with col_left:
        st.write("#### 📑 세부 시뮬레이션 내역")
        report_df = pd.DataFrame({
            "구분": ["실질 가용 재고", "현재 확정(OTB)", "예상 추가 픽업", "취소 이탈 예상"],
            "객실수": [int(net_total_cap), int(current_otb), int(future_pickup), int(-(current_otb * washout_rate))]
        })
        st.table(report_df)

    with col_right:
        st.write("#### 🎯 총지배인 전략 권고")
        achieve_rate = (final_rev_man / budget_rev) * 100
        if achieve_rate >= 100:
            st.success(f"🎊 **목표 달성 가시권 ({achieve_rate:.1f}%)**")
            st.write(f"목표 대비 {int(final_rev_man - budget_rev)}만원 초과 달성이 예상됩니다. 저가 OTA 비중을 줄이세요.")
        else:
            st.error(f"⚠️ **목표 미달 비상 ({achieve_rate:.1f}%)**")
            st.write(f"목표까지 {int(budget_rev - final_rev_man)}만원 부족합니다. 예약 가속도를 높일 특가 상품이 필요합니다.")

    # 8. 수익성 및 운영 효율성
    st.write("---")
    col_v1, col_v2 = st.columns(2)
    with col_v1:
        st.write("#### 💰 수익성 가이드라인")
        v_cost = st.slider("객실당 변동비", 10000, 50000, 25000, step=5000)
        net_margin = (final_rev_man * 10000) - (final_rms * v_cost)
        st.caption(f"예상 객실 공헌이익: ₩{int(net_margin/10000):,}만")
    
    with col_v2:
        st.write("#### 🧑‍🤝‍🧑 운영 효율성 (Staffing)")
        needed_staff = np.ceil(final_rms / (days_in_month * 15))
        st.write(f"예상 점유율 기준, 일평균 **{needed_staff:.0f}명**의 메이드 인력이 필요합니다.")

if __name__ == "__main__":
    run_forecasting()
