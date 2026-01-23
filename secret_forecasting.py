import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

def run_forecasting():
    st.title("🏛️ 총지배인(GM) 전략 의사결정 대시보드 v15.0")
    st.caption("예측 곡선 엔진: 131실 가변 재고 기반 시계열 픽업 시뮬레이션")

    # 1. 데이터 호출 및 인벤토리 설정
    selected_month = st.sidebar.selectbox("🎯 분석 대상 월", range(1, 13), index=datetime.now().month-1)
    target_sob = st.session_state.get(f"sob_{selected_month}")
    actual_pace = float(st.session_state.get(f"pace_{selected_month}", 0)) 
    dow_indices = st.session_state.get("historical_dow", {})
    
    # [데이터 관리 구역]
    BUDGET_DATA = {
        1: 514992575, 2: 786570856, 3: 529599040, 4: 695351004, 5: 903705440, 6: 808203820,
        7: 1231949142, 8: 1388376999, 9: 952171506, 10: 897171539, 11: 667146771, 12: 804030110
    }
    LY_DATA = { # 2025 실적
        1: 485000000, 2: 710000000, 3: 490000000, 4: 650000000, 5: 850000000, 6: 760000000,
        7: 1150000000, 8: 1310000000, 9: 900000000, 10: 840000000, 11: 620000000, 12: 750000000
    }
    PY_DATA = { # 2024 실적
        1: 420000000, 2: 650000000, 3: 430000000, 4: 580000000, 5: 790000000, 6: 710000000,
        7: 1050000000, 8: 1220000000, 9: 830000000, 10: 780000000, 11: 570000000, 12: 690000000
    }

    if not target_sob:
        st.warning(f"메인 리포트에서 실적 데이터를 먼저 로드해 주세요.")
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

    with st.container(border=True):
        col_tgt, col_ly = st.columns(2)
        with col_tgt:
            budget_rev = st.number_input("2026 목표 (만원)", value=cur_budget_man, step=500)
            budget_occ = st.slider("목표 점유율 (%)", 0, 100, 85)
        with col_ly:
            ly_rev = st.number_input("2025 실적 (만원)", value=cur_ly_man, step=500)
            ly_occ = st.slider("2025 점유율 (%)", 0, 100, 80)

    # 3. 전략 시뮬레이션 설정
    st.write("### 🛠️ 수익 및 재고 전략 설정")
    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            ooo_rooms = st.number_input("일평균 고장(OOO)", 0, 10, 2)
            net_total_cap = (TOTAL_ROOMS - ooo_rooms) * days_in_month
        with c2:
            accel = st.slider("예약 가속도", 0.5, 2.5, 1.1)
            rem_days = st.number_input("남은 기간(Days)", 1, 31, 7)
        with c3:
            target_adr = st.number_input("목표 ADR(단가)", 100000, 1000000, 240000, step=5000)

    # 4. [정밀 엔진] 시뮬레이션 및 곡선 데이터 생성
    lt_factor = (1.0 + (1.0 / np.log1p(rem_days)))
    future_pickup = actual_pace * auto_dow_index * accel * lt_factor * rem_days
    
    # 최종 결과 계산
    final_rms = min(net_total_cap, (current_otb * 0.97) + future_pickup)
    final_rev_man = (final_rms * target_adr) / 10000 
    occ_pct = (final_rms / net_total_cap) * 100

    # --- [신규] 예측 곡선 데이터 생성 ---
    # 오늘(Day 0)부터 남은 기간(rem_days) 동안 매일의 누적 예약량을 계산
    daily_pickup_avg = future_pickup / rem_days
    curve_data = []
    for i in range(rem_days + 1):
        day_rms = min(net_total_cap, (current_otb * 0.97) + (daily_pickup_avg * i))
        curve_data.append({"Day": i, "예상 누적 예약(Rms)": day_rms})
    
    curve_df = pd.DataFrame(curve_data).set_index("Day")

    # 5. [강력한 시각화] 예측 곡선 및 페이스 분석
    st.divider()
    st.subheader("🔮 미래 예측 예약 곡선 (Booking Forecast Curve)")
    
    col_chart, col_stat = st.columns([2, 1])
    
    with col_chart:
        # 픽업이 쌓여가는 흐름을 선 그래프로 표시
        st.line_chart(curve_df)
        st.caption(f"💡 오늘({int(current_otb)}실)부터 입실일까지 일평균 {daily_pickup_avg:.1f}실씩 예약이 쌓이는 흐름입니다.")

    with col_stat:
        st.write("#### 🎯 마감 분석")
        rem_inventory = net_total_cap - final_rms
        st.metric("최종 예상 점유율", f"{occ_pct:.1f}%")
        st.metric("잔여 객실(Inventory)", f"{int(max(0, rem_inventory))}실")
        if occ_pct > 95:
            st.error("🚨 SOLD OUT 임박!")
        elif occ_pct > 80:
            st.success("✅ 안정적인 픽업 흐름")

    # 6. KPI 대시보드
    st.divider()
    st.subheader("🏁 종합 성과 분석")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("예상 매출액", f"{int(final_rev_man):,}만", f"{final_rev_man - budget_rev:+,.0f} (Target)")
    growth_ly = ((final_rev_man / ly_rev) - 1) * 100 if ly_rev > 0 else 0
    k2.metric("vs 2025 성장률", f"{growth_ly:+.1f}%", f"{int(final_rev_man - ly_rev):+}만")
    revpar = (final_rev_man * 10000) / net_total_cap
    k3.metric("예상 RevPAR", f"₩{int(revpar):,}")
    k4.metric("예상 청소 인력", f"{int(np.ceil(final_rms / (days_in_month * 15)))}명", "일평균")

    # 7. 수익성 가이드
    st.write("---")
    v_cost = st.slider("객실당 변동비", 10000, 50000, 25000, step=5000)
    net_margin = (final_rev_man * 10000) - (final_rms * v_cost)
    st.info(f"💰 **최종 예상 공헌이익:** ₩{int(net_margin/10000):,}만 (변동비 {v_cost:,}원 차감 후)")

if __name__ == "__main__":
    run_forecasting()
