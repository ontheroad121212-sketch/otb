import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime

def run_forecasting():
    st.title("⚖️ 131실 전용 정밀 RM 시뮬레이터")
    st.caption("고장 객실(OOO) 및 가변 인벤토리를 반영한 지배인 전용 의사결정 도구")

    # 1. 세션 데이터 확인
    selected_month = st.sidebar.selectbox("🎯 분석 대상 월", range(1, 13), index=datetime.now().month-1)
    target_sob = st.session_state.get(f"sob_{selected_month}")
    actual_pace = float(st.session_state.get(f"pace_{selected_month}", 0)) 
    dow_indices = st.session_state.get("historical_dow", {})
    
    if not target_sob:
        st.warning("메인 리포트에서 데이터를 먼저 로드해야 정밀 분석이 시작됩니다.")
        return

    # [131실 특화 물리량 설정]
    TOTAL_ROOMS = 131
    MONTH_DAYS = 31 if selected_month in [1,3,5,7,8,10,12] else 30
    if selected_month == 2: MONTH_DAYS = 28
    
    fit_otb = float(target_sob.get('FIT_RMS', 0))
    grp_otb = float(target_sob.get('GRP_RMS', 0))
    current_otb = fit_otb + grp_otb
    auto_dow_index = float(dow_indices.get(datetime.now().weekday(), 1.0))

    # 2. 지배인 전략 컨트롤러 (이 부분이 더 세밀해졌습니다)
    st.write("### 🛠️ 실시간 전략 변수 설정")
    with st.expander("📝 인벤토리 및 가속도 상세 설정", expanded=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            ooo_rooms = st.number_input("일평균 고장 객실 (OOO)", 0, 131, 2)
            net_daily_cap = TOTAL_ROOMS - ooo_rooms
            net_total_cap = net_daily_cap * MONTH_DAYS
        with c2:
            accel = st.slider("📈 예약 가속도 (Accel)", 0.3, 3.0, 1.0, step=0.1)
            rem_days = st.number_input("입실까지 남은 기간 (Days)", 1, 365, 7)
        with c3:
            target_adr = st.number_input("목표 ADR (단가)", 50000, 1000000, 240000, step=5000)
            washout = st.slider("예약 이탈율 (Wash-out %)", 0, 20, 3)

    # 3. [고도화 엔진] Net Inventory 기반 수식
    lt_factor = (1.0 + (1.0 / np.log1p(rem_days))) # 리드타임 보정
    
    # 추가 픽업량 계산
    future_pickup = actual_pace * auto_dow_index * accel * lt_factor * rem_days
    # 취소분 계산
    loss_val = current_otb * (washout / 100)
    
    # [핵심] 131실 총량 제한 적용 (현실적인 숫자 산출)
    final_rms = min(net_total_cap, (current_otb - loss_val) + future_pickup)
    final_rev = final_rms * target_adr
    occ_pct = (final_rms / net_total_cap) * 100

    # 4. 화려하지 않지만 '강력한' 데이터 대시보드
    st.divider()
    
    # 상단 핵심 KPI
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("최종 예상 객실", f"{int(final_rms):,} Rms", f"{int(final_rms - current_otb):+d}")
    with m2:
        st.metric("최종 예상 OCC", f"{occ_pct:.1f}%")
    with m3:
        st.metric("예상 총 매출", f"₩{int(final_rev/10000):,}만")
    with m4:
        # 잔여 객실 기반 마감 압박 지수
        remaining_inventory = net_total_cap - final_rms
        st.metric("잔여 판매 가능", f"{int(max(0, remaining_inventory))}실")

    # 5. [신규] 전략적 분석 리포트 (지배인이 보고 싶어 하는 것)
    st.write("---")
    col_left, col_right = st.columns([1.5, 1])
    
    with col_left:
        st.write("#### 📑 세부 예측 내역")
        # 데이터프레임 구성
        report_data = {
            "항목": ["전체 가용 객실 (Gross)", "고장 객실 손실 (OOO)", "실질 가용 객실 (Net)", "현재 OTB", "미래 예상 픽업", "이탈 예상 (Wash)"],
            "수치": [int(TOTAL_ROOMS * MONTH_DAYS), int(ooo_rooms * MONTH_DAYS), int(net_total_cap), int(current_otb), int(future_pickup), int(-loss_val)],
            "비중": ["100%", f"{(ooo_rooms/TOTAL_ROOMS)*100:.1f}%", "-", f"{(current_otb/net_total_cap)*100:.1f}%", f"{(future_pickup/net_total_cap)*100:.1f}%", "-"]
        }
        st.table(pd.DataFrame(report_data))
        [Image of a hotel yield management chart showing occupancy displacement and price sensitivity]

    with col_right:
        st.write("#### 🎯 RM 전략 권고")
        # 점유율 구간별 지배인 행동 지침
        if occ_pct > 95:
            st.error("🚨 **FULL-HOUSE 경보**")
            st.write("가용 객실이 거의 없습니다. 모든 저가 채널을 즉시 닫고, 대기 예약을 관리하세요. 취소 위약금 규정을 엄격히 적용할 때입니다.")
        elif occ_pct > 80:
            st.warning("⚡ **수익 극대화 구간**")
            st.write("안정적인 만실이 예상됩니다. ADR을 공격적으로 높여 RevPAR를 끌어올리세요. 1박 예약보다는 연박 예약을 우선 수선하세요.")
        elif occ_pct > 60:
            st.info("📈 **판매 가속 구간**")
            st.write("흐름이 좋습니다. 주요 OTA 노출을 강화하고 패키지 판매를 통해 점유율을 80%대까지 견인하세요.")
        else:
            st.error("📉 **긴급 수요 창출 필요**")
            st.write("현재 픽업 속도로는 목표 달성이 어렵습니다. 플래시 세일이나 법인 특가 제안을 검토해야 합니다.")

    # 6. [데이터 신뢰도] 요일별 가중치 상세
    with st.expander("🔍 분석 근거 (4만 건 데이터 요일 지수)"):
        dow_df = pd.DataFrame(list(dow_indices.items()), columns=['요일', '가중치'])
        dow_df['요일'] = dow_df['요일'].map({0:'월', 1:'화', 2:'수', 3:'목', 4:'금', 5:'토', 6:'일'})
        st.line_chart(dow_df.set_index('요일'))
        st.caption("※ 1.0보다 높으면 평균보다 예약이 많이 들어오는 요일입니다.")

if __name__ == "__main__":
    run_forecasting()
