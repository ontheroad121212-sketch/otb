import streamlit as st
import pandas as pd

# [보안] 인증되지 않은 사용자는 즉시 차단
if st.session_state.get("authenticated") != True:
    st.warning("이 페이지는 관리자 전용입니다. 메인 페이지에서 인증을 완료해주세요.")
    st.stop()

st.set_page_config(page_title="Secret Forecasting Lab", layout="wide")

st.title("🎯 AI 지능형 포캐스팅 (비공개 모드)")
st.caption("총지배인님 몰래 진행하는 데이터 기반 미래 예측 시나리오입니다. 😎")

# --- 데이터 로드 ---
selected_month = st.selectbox("분석 대상 월 선택", [f"{i}월" for i in range(1, 13)])
month_idx = int(selected_month.replace("월", ""))

# 세션에 저장된 데이터 가져오기 (메인 앱이나 다른 탭에서 저장한 값)
sob_data = st.session_state.get(f"sob_{month_idx}")
pace_data = st.session_state.get(f"pace_{month_idx}", 0) # 기본값 0

if sob_data:
    current_occ = sob_data.get('TOTAL_OCC', 0)
    
    st.divider()
    
    # --- 시나리오 컨트롤러 ---
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.subheader("📊 시나리오 설정")
        # 최근 페이스를 기본값으로 주되, 사용자님이 직접 조절 가능
        input_pace = st.number_input("일일 예상 추가 픽업 (Rms)", value=float(pace_data), step=0.5)
        remaining_days = st.number_input("예측 기간 (남은 투숙일 수)", value=15, step=1)
        washout_rate = st.slider("예상 취소율 (%)", 0, 30, 5)
    
    # --- 계산 로직 ---
    # 공식: 현재 OTB + (예상 페이스 * 남은 기간) - 취소 예상분
    projected_add = input_pace * remaining_days
    final_projection = current_occ + projected_add
    washout_amount = final_projection * (washout_rate / 100)
    adjusted_final = final_projection - washout_amount

    with col2:
        st.subheader("🚀 예측 결과 (Simulation)")
        c1, c2 = st.columns(2)
        c1.metric("현재 OTB", f"{current_occ} Rms")
        c2.metric("예상 추가 픽업", f"+{int(projected_add)} Rms")
        
        # 강조 표시
        st.metric("최종 예상 점유실 (Adjusted)", f"{int(adjusted_final)} Rms", 
                  delta=f"{int(adjusted_final - current_occ)} Rms 증감 예상")
        
        # 진행률 바 (예: 100실 기준 점유율 시각화)
        progress = min(100, int((adjusted_final / 100) * 100)) # 분모는 실제 총 객실수로 수정 필요
        st.progress(progress / 100, text=f"예상 점유율: {progress}%")

    # --- Best/Worst Case 자동 계산 ---
    st.divider()
    st.subheader("📉 Case Study")
    case_cols = st.columns(3)
    
    with case_cols[0]:
        st.error("Worst Case (페이스 -50%)")
        worst = current_occ + (projected_add * 0.5)
        st.write(f"**{int(worst)} Rms**")
        
    with case_cols[1]:
        st.info("Base Case (현재 페이스 유지)")
        st.write(f"**{int(final_projection)} Rms**")
        
    with case_cols[2]:
        st.success("Best Case (페이스 +50%)")
        best = current_occ + (projected_add * 1.5)
        st.write(f"**{int(best)} Rms**")

else:
    st.info(f"📂 {month_idx}월의 분석 데이터가 메모리에 없습니다. 먼저 해당 월의 리포트 탭을 조회해주세요.")
