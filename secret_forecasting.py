import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime

def run_forecasting():
    st.title("🏛️ 총지배인(GM) 전략 의사결정 대시보드")
    st.caption("131실 가변 재고 기반 RevPAR 및 마진 최적화 엔진")

    # 1. 데이터 호출 및 인벤토리 설정
    selected_month = st.sidebar.selectbox("🎯 분석 대상 월", range(1, 13), index=datetime.now().month-1)
    target_sob = st.session_state.get(f"sob_{selected_month}")
    actual_pace = float(st.session_state.get(f"pace_{selected_month}", 0)) 
    dow_indices = st.session_state.get("historical_dow", {})
    
    if not target_sob:
        st.warning("메인 리포트에서 데이터를 로드해야 RM 전략 수립이 가능합니다.")
        return

    # [131실 특화 물리량 계산]
    TOTAL_ROOMS = 131
    days_in_month = 31 if selected_month in [1,3,5,7,8,10,12] else 30
    if selected_month == 2: days_in_month = 28
    
    fit_otb = float(target_sob.get('FIT_RMS', 0))
    grp_otb = float(target_sob.get('GRP_RMS', 0))
    current_otb = fit_otb + grp_otb
    auto_dow_index = float(dow_indices.get(datetime.now().weekday(), 1.0))

    # 2. 총지배인 관점의 핵심 변수 (인벤토리 + 손익)
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

    # 3. [GM 전용 수식] 정밀 포캐스팅 엔진
    # 리드타임 보정 (투숙일 임박 시 예약 밀도 증가 반영)
    lt_factor = (1.0 + (1.0 / np.log1p(rem_days)))
    
    # 최종 예상 픽업 및 Wash-out(이탈)
    future_pickup = actual_pace * auto_dow_index * accel * lt_factor * rem_days
    washout_rate = 0.03 # 3% 예약 이탈 가정
    
    # 최종 예상치 (131실 한계 적용)
    final_rms = min(net_total_cap, (current_otb * (1 - washout_rate)) + future_pickup)
    final_rev = final_rms * target_adr
    occ_pct = (final_rms / net_total_cap) * 100
    revpar = final_rev / net_total_cap

    # 4. 총지배인 보고용 KPI 대시보드
    st.divider()
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("최종 예상 객실", f"{int(final_rms):,} Rms", f"{int(final_rms - current_otb):+d}")
    k2.metric("예상 점유율(OCC)", f"{occ_pct:.1f}%")
    k3.metric("목표 RevPAR", f"₩{int(revpar):,}")
    k4.metric("예상 총매출", f"₩{int(final_rev/10000):,}만")

    # 5. 전략적 분석 리포트
    st.write("---")
    col_left, col_right = st.columns([1.5, 1])
    
    with col_left:
        st.write("#### 📑 세부 시뮬레이션 데이터")
        report_df = pd.DataFrame({
            "항목": ["총 가용 재고", "고장객실 손실", "실질 판매 가능(Net)", "현재 확정(OTB)", "미래 예상 픽업"],
            "객실수": [TOTAL_ROOMS * days_in_month, -(ooo_rooms * days_in_month), net_total_cap, int(current_otb), int(future_pickup)],
            "비고": ["Gross Capacity", "Maintenance", "Total Marketable", "Confirmed", "Forecasted"]
        })
        st.table(report_df)

    with col_right:
        st.write("#### 🎯 총지배인 전략 권고")
        if occ_pct > 92:
            st.error("🚨 **Yield Management: 단가 인상**")
            st.write(f"예상 점유율이 {occ_pct:.1f}%로 만실에 가깝습니다. 저가 패키지를 중단하고 ADR을 ₩{int(target_adr*1.1):,}까지 상향하여 수익을 극대화하세요.")
        elif occ_pct > 75:
            st.warning("⚡ **Efficiency: 선택적 판매**")
            st.write("안정적 수요입니다. 단기 투숙보다 연박(2박 이상) 고객 위주로 채널을 열어 객실 정비 효율을 높이세요.")
        else:
            st.info("📉 **Demand Gen: 수요 창출**")
            st.write("점유율 확보가 시급합니다. 로컬 프로모션 및 OTA 타임세일을 통해 베이스 물량을 확보하세요.")

    # 6. [신규 기능] 수익성 분석 섹션
    st.write("---")
    st.write("#### 💰 수익성 가이드라인")
    v_cost = st.slider("객실당 변동비(세탁/어메니티 등)", 10000, 50000, 25000, step=5000)
    net_margin = final_rev - (final_rms * v_cost)
    st.caption(f"예상 객실 공헌이익: ₩{int(net_margin/10000):,}만 (고정비 제외)")

if __name__ == "__main__":
    run_forecasting()
