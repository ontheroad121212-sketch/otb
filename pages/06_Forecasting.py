import streamlit as st
# 세션 상태에 인증 정보가 없으면 화면을 비우고 경고 메시지만 출력
if st.session_state.get("authenticated") != True:
    st.warning("접근 권한이 없습니다. 메인 페이지에서 관리자 인증을 완료해주세요.")
    st.stop()  # 이후의 코드는 실행되지 않음

# --- 여기서부터는 암호가 맞을 때만 실행되는 포캐스팅 로직 ---
st.title("🎯 Secret Forecasting")

# [보안] 세션 스테이트에 인증 정보가 없으면 아예 접근 불가 처리
if "authenticated" not in st.session_state or not st.session_state["authenticated"]:
    st.error("이 페이지에 접근할 권한이 없습니다.")
    st.stop()

st.title("🎯 AI 지능형 포캐스팅 시나리오")

# [데이터 연동] 다른 탭에서 계산되어 저장된 데이터 가져오기 (예시)
current_otb = st.session_state.get("otb_total", 0)
current_pace = st.session_state.get("pace_average", 0)

# [시나리오 분석] 슬라이더로 가중치 조절
st.subheader("📊 시나리오 설정")
pace_weight = st.slider("페이스 가중치 (Best/Worst)", 0.5, 1.5, 1.0)
washout_rate = st.slider("예상 취소율(%)", 0, 30, 5)

# [예측 수식]
projected_rooms = current_otb + (current_pace * pace_weight * 30) * (1 - washout_rate/100)

col1, col2, col3 = st.columns(3)
col1.metric("현재 OTB", f"{current_otb} Rms")
col2.metric("예상 추가 예약", f"{int(current_pace * pace_weight * 30)} Rms")
col3.metric("최종 예상 점유율", f"{int(projected_rooms)} Rms")
