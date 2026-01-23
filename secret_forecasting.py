import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def run_forecasting():
    st.title("🏛️ 총지배인(GM) 전략 의사결정 대시보드 v15.1")
    st.caption("최종 통합본: 3개년 비교 차트 + 미래 예측 곡선 + 인벤토리 최적화")

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
    # 2025년 실적 (Last Year)
    LY_DATA = { 1: 485000000, 2: 710000000, 3: 490000000, 4: 650000000, 5: 850000000, 6: 760000000, 7: 1150000000, 8: 1310000000, 9: 900000000, 10: 840000000, 11: 620000000, 12: 750000000 }
    # 2024년 실적 (Prev Year)
    PY_DATA = { 1: 420000000, 2: 650000000, 3: 430000000, 4: 580000000, 5: 790000000, 6: 710000000, 7: 1050000000, 8: 1220000000, 9: 830000000, 10: 780000000, 11: 570000000, 12: 690000000 }

    if not target_sob:
        st.warning(f"메인 리포트에서 {selected_month}월 실적 데이터를 먼저 로드해 주세요.")
        return

    # [131실 특화 물리량]
    TOTAL_ROOMS = 131
    days_in_month = 31 if selected_month in [1,3,5,7,8,10,12] else 30
    if selected_month == 2: days_in_month = 28
    
    fit_otb = float(target_sob.get('FIT_RMS', 0))
    grp_otb = float(target_sob.get('GRP_RMS', 0))
    current_otb = fit_otb + grp_otb
    auto_dow_index = float(dow_indices.get(datetime.now().weekday(), 1.0))

    # 2. 벤치마크 및 목표 설정
    st.write("### 📈 벤치마크 및 목표 설정")
    cur_budget_man = int(BUDGET_DATA.get(selected_month, 500000000) / 10000)
    cur_ly_man = int(LY_DATA.get(selected_month, 450000000) / 10000)
    cur_py_man = int(PY_DATA.get(selected_month, 400000000) / 10000)

    with st.container(border=True):
        col_tgt, col_ly, col_py = st.columns(3)
        with col_tgt:
            budget_rev = st.number_input("2026 목표(만원)", value=cur_budget_man, step=500, key="b_rev")
            budget_occ = st.slider("목표 점유율(%)", 0, 100, 85, key="b_occ")
        with col_ly:
            ly_rev = st.number_input("2025 실적(LY, 만원)", value=cur_ly_man, step=500, key="ly_rev")
            ly_occ = st.slider("2025 점유율(%)", 0, 100, 80, key="ly_occ")
        with col_py:
            py_rev = st.number_input("2024 실적(PY, 만원)", value=cur_py_man, step=500, key="py_rev")

    st.write("---")
    
    # 3. 전략 시뮬레이션 설정
    st.write("### 🛠️ 수익 및 재고 전략 설정")
    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            ooo_rooms = st.number_input("일평균 고장(OOO)", 0, 10, 2)
            net_total_cap = (TOTAL_ROOMS - ooo_rooms) * days_in_month
        with c2:
            accel = st.slider("예약 가속도(Accel)", 0.5, 2.5, 1.1)
            rem_days = st.number_input("남은 기간(Days)", 1, 31, 7)
        with c3:
            target_adr = st.number_input("목표 ADR(단가)", 100000, 1000000, 240000, step=5000)

    # 4. [정밀 엔진] 시뮬레이션 계산
    lt_factor = (1.0 + (1.0 / np.log1p(rem_days)))
    future_pickup = actual_pace * auto_dow_index * accel * lt_factor * rem_days
    washout_rate = 0.03
    
    final_rms = min(net_total_cap, (current_otb * (1 - washout_rate)) + future_pickup)
    final_rev_man = (final_rms * target_adr) / 10000 
    occ_pct = (final_rms / net_total_cap) * 100
    revpar = (final_rev_man * 10000) / net_total_cap

    # 5. [신규/보강] 시각화 대시보드 (막대 그래프 + 예측 곡선)
    st.divider()
    
    tab1, tab2 = st.tabs(["📊 성과 비교 (Bar Chart)", "🔮 예약 곡선 (Booking Curve)"])
    
    with tab1:
        st.subheader("🏁 3개년 매출 추이 및 예측 비교")
        # 막대 그래프 데이터 구성
        comp_df = pd.DataFrame({
            "구분": ["2024 실적", "2025 실적", "2026 목표", "2026 예측"],
            "매출액(만원)": [py_rev, ly_rev, budget_rev, final_rev_man]
        })
        st.bar_chart(comp_df.set_index("구분"))
        st.caption("💡 2024년부터 이어지는 매출 흐름과 2026년 최종 예측치를 대조합니다.")

    with tab2:
        st.subheader("🔮 미래 예약 누적 시뮬레이션")
        daily_pickup_avg = future_pickup / rem_days
        curve_data = []
        for i in range(rem_days + 1):
            sim_rms = min(net_total_cap, (current_otb * (1 - washout_rate)) + (daily_pickup_avg * i))
            curve_data.append({"Day": i, "예상 누적 예약(Rms)": sim_rms})
        curve_df = pd.DataFrame(curve_data).set_index("Day")
        
        st.line_chart(curve_df)
        st.info(f"📈 오늘부터 입실일까지 일평균 {daily_pickup_avg:.1f}실씩 예약이 추가될 것으로 보입니다.")

    # 6. 종합 KPI 리포트
    st.divider()
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("예상 매출액", f"{int(final_rev_man):,}만", f"{final_rev_man - budget_rev:+,.0f} (Target)")
    growth_ly = ((final_rev_man / ly_rev) - 1) * 100 if ly_rev > 0 else 0
    k2.metric("vs 2025 성장률", f"{growth_ly:+.1f}%", f"{int(final_rev_man - ly_rev):+}만")
    k3.metric("예상 RevPAR", f"₩{int(revpar):,}")
    k4.metric("예상 점유율", f"{occ_pct:.1f}%", f"{occ_pct - budget_occ:+.1f}%p")

    # 7. 세부 데이터 및 운영 지표
    st.write("---")
    col_a, col_b = st.columns([1.5, 1])
    
    with col_a:
        st.write("#### 📑 세부 시뮬레이션 데이터")
        report_df = pd.DataFrame({
            "항목": ["실질 가용 재고", "현재 확정(OTB)", "예상 추가 픽업", "이탈 예상(Wash)"],
            "수치": [int(net_total_cap), int(current_otb), int(future_pickup), int(-(current_otb * washout_rate))]
        })
        st.table(report_df)

    with col_b:
        st.write("#### 🎯 전략적 권고")
        achieve_rate = (final_rev_man / budget_rev) * 100
        if achieve_rate >= 100:
            st.success(f"🎊 **목표 달성 예상 ({achieve_rate:.1f}%)**")
            st.write("안정적 수익 구간입니다. 고단가 예약을 선별적으로 받으세요.")
        else:
            st.error(f"⚠️ **목표 달성 경보 ({achieve_rate:.1f}%)**")
            st.write(f"목표 대비 {int(budget_rev - final_rev_man)}만원 부족합니다. 판매 속도를 높이세요.")

    # 8. 수익성 및 인력 가이드
    st.write("---")
    cv1, cv2 = st.columns(2)
    with cv1:
        v_cost = st.slider("객실당 변동비", 10000, 50000, 25000, step=5000)
        net_margin = (final_rev_man * 10000) - (final_rms * v_cost)
        st.caption(f"💰 예상 객실 공헌이익: ₩{int(net_margin/10000):,}만")
    with cv2:
        needed_staff = np.ceil(final_rms / (days_in_month * 15))
        st.write(f"🧑‍🤝‍🧑 일평균 필요 메이드: **{needed_staff:.0f}명**")

if __name__ == "__main__":
    run_forecasting()
