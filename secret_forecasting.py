import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime

def run_forecasting():
    st.title("🏛️ 총지배인(GM) 전략 의사결정 대시보드 v14.0")
    st.caption("3개년 지표 통합: 2024-2025 실적 기반 2026년 목표 달성 시뮬레이션")

    # 1. 데이터 호출 및 인벤토리 설정
    selected_month = st.sidebar.selectbox("🎯 분석 대상 월", range(1, 13), index=datetime.now().month-1)
    target_sob = st.session_state.get(f"sob_{selected_month}")
    actual_pace = float(st.session_state.get(f"pace_{selected_month}", 0)) 
    dow_indices = st.session_state.get("historical_dow", {})
    
    # ----------------------------------------------------------------------
    # [데이터 관리 구역] - 지배인님이 나중에 이 숫자만 바꾸시면 됩니다.
    # ----------------------------------------------------------------------
    # 2026년 사업계획 (Budget) - 지배인님이 주신 데이터
    BUDGET_DATA = {
        1: 514992575, 2: 786570856, 3: 529599040, 4: 695351004, 5: 903705440, 6: 808203820,
        7: 1231949142, 8: 1388376999, 9: 952171506, 10: 897171539, 11: 667146771, 12: 804030110
    }

    # 2025년 실제 실적 (LY - Last Year)
    LY_DATA = {
        1: 485000000, 2: 710000000, 3: 490000000, 4: 650000000, 5: 850000000, 6: 760000000,
        7: 1150000000, 8: 1310000000, 9: 900000000, 10: 840000000, 11: 620000000, 12: 750000000
    }

    # 2024년 실제 실적 (PY - Prev Year)
    PY_DATA = {
        1: 420000000, 2: 650000000, 3: 430000000, 4: 580000000, 5: 790000000, 6: 710000000,
        7: 1050000000, 8: 1220000000, 9: 830000000, 10: 780000000, 11: 570000000, 12: 690000000
    }
    # ----------------------------------------------------------------------

    if not target_sob:
        st.warning(f"먼저 메인 리포트에서 {selected_month}월 실적 데이터를 로드해 주세요.")
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
            py_occ = st.slider("전전년 점유율 (%)", 0, 100, 75, key="py_occ")

    st.write("---")
    
    # 3. 수익 및 재고 전략 설정
    st.write("### 🛠️ 수익 및 재고 전략 설정")
    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            st.write("**📦 재고 최적화**")
            ooo_rooms = st.number_input("일평균 고장 객실(OOO)", 0, 10, 2)
            net_daily_cap = TOTAL_ROOMS - ooo_rooms
            net_total_cap = net_daily_cap * days_in_month
        with c2:
            st.write("**🔥 시장 모멘텀**")
            accel = st.slider("예약 가속도(Accel)", 0.5, 2.5, 1.1)
            rem_days = st.number_input("남은 기간(Days)", 1, 31, 7)
        with c3:
            st.write("**💰 수익 극대화**")
            current_adr = int(target_sob.get('FIT_REV', 0)/max(1, fit_otb)) if fit_otb > 0 else 240000
            target_adr = st.number_input("목표 ADR(단가)", 100000, 1000000, current_adr, step=5000)

    # 4. [정밀 엔진] 시뮬레이션 수식
    lt_factor = (1.0 + (1.0 / np.log1p(rem_days)))
    future_pickup = actual_pace * auto_dow_index * accel * lt_factor * rem_days
    washout_rate = 0.03
    
    final_rms = min(net_total_cap, (current_otb * (1 - washout_rate)) + future_pickup)
    final_rev_man = (final_rms * target_adr) / 10000 
    occ_pct = (final_rms / net_total_cap) * 100
    revpar = (final_rev_man * 10000) / net_total_cap

    # 5. KPI 대시보드 (성장률 분석 강화)
    st.divider()
    st.subheader("🏁 시뮬레이션 결과 및 성장률 분석")
    k1, k2, k3, k4 = st.columns(4)
    
    rev_gap = final_rev_man - budget_rev
    k1.metric("예상 매출", f"{int(final_rev_man):,}만", f"{rev_gap:+,.0f} (Target 대비)")
    
    growth_ly = ((final_rev_man / ly_rev) - 1) * 100 if ly_rev > 0 else 0
    k2.metric("vs 2025 (YoY)", f"{growth_ly:+.1f}%", f"{int(final_rev_man - ly_rev):+}만")
    
    growth_py = ((final_rev_man / py_rev) - 1) * 100 if py_rev > 0 else 0
    k3.metric("vs 2024 (YoY)", f"{growth_py:+.1f}%", f"{int(final_rev_man - py_rev):+}만")
    
    k4.metric("예상 점유율", f"{occ_pct:.1f}%", f"{occ_pct - budget_occ:+.1f}%p")

    # 6. 세부 분석 및 차트
    st.write("---")
    col_left, col_right = st.columns([1.5, 1])
    
    with col_left:
        st.write("#### 📊 3개년 매출 추이 비교 (2024 - 2026)")
        chart_df = pd.DataFrame({
            "연도": ["2024 실적", "2025 실적", "2026 목표", "2026 예측"],
            "매출액(만원)": [py_rev, ly_rev, budget_rev, final_rev_man]
        })
        st.bar_chart(chart_df.set_index("연도"))
        
        st.write("#### 📑 세부 시뮬레이션 데이터")
        report_df = pd.DataFrame({
            "구분": ["실질 가용 재고", "현재 OTB", "예상 추가 픽업", "최종 예상 객실"],
            "수치": [int(net_total_cap), int(current_otb), int(future_pickup), int(final_rms)]
        })
        st.table(report_df)

    with col_right:
        st.write("#### 🎯 총지배인 전략 권고")
        achieve_rate = (final_rev_man / budget_rev) * 100
        if achieve_rate >= 100:
            st.success(f"🎊 **목표 달성 가시권 (달성률 {achieve_rate:.1f}%)**")
            st.write(f"현재 추세라면 {int(final_rev_man - budget_rev)}만원 초과 달성이 예상됩니다. 이제부터는 저가 채널을 통제하세요.")
        else:
            st.error(f"⚠️ **목표 미달 경보 (달성률 {achieve_rate:.1f}%)**")
            st.write(f"목표 대비 {int(budget_rev - final_rev_man)}만원 부족합니다. 남은 {rem_days}일 동안 공격적인 세일즈가 필요합니다.")
        
        st.info(f"💡 **분석 근거:** 요일 지수({auto_dow_index:.2f}x) 및 리드타임 보정({lt_factor:.2f}x) 반영됨")

    # 7. 수익성 및 인건비 효율 가이드
    st.write("---")
    col_v1, col_v2 = st.columns(2)
    with col_v1:
        st.write("#### 💰 수익성 가이드라인")
        v_cost = st.slider("객실당 변동비(세탁/어메니티 등)", 10000, 50000, 25000, step=5000)
        net_margin = (final_rev_man * 10000) - (final_rms * v_cost)
        st.caption(f"예상 객실 공헌이익: ₩{int(net_margin/10000):,}만 (고정비 제외)")
    
    with col_v2:
        st.write("#### 🧑‍🤝‍🧑 운영 효율성 (Staffing)")
        needed_staff = np.ceil(final_rms / (days_in_month * 15))
        st.write(f"예상 점유율 기준, 일평균 **{needed_staff:.0f}명**의 룸 메이드 인력이 필요합니다.")

if __name__ == "__main__":
    run_forecasting()
