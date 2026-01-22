import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from firebase_admin import firestore
import datetime

# Firestore 클라이언트 (이미 설정되어 있다고 가정)
db = firestore.client()

def main():
    st.set_page_config(page_title="엠버 프로모션 분석 엔진", layout="wide")
    st.title("🏨 엠버 프로모션 성과 분석 시스템")

    tab1, tab2 = st.tabs(["📊 성과 분석 대시보드", "📤 데이터 업로드"])

    # --- TAB 2: 데이터 업로드 (Q3, R3 기준 자동 인식) ---
    with tab2:
        st.header("엑셀 데이터 업로드")
        uploaded_file = st.file_uploader("거래처 엑셀 파일을 올려주세요", type=['xlsx'])
        
        if uploaded_file:
            # 1. 데이터 읽기: 3행(index 2)을 제목줄로 지정
            df = pd.read_excel(uploaded_file, header=2) 
            df.columns = [str(c).strip() for c in df.columns] # 컬럼명 공백 제거
            
            # 2. 거래처(Q열) 및 요금타입(R열) 값 가져오기 (첫 번째 데이터 행에서 추출)
            try:
                # 사용자 지정 위치: N(객실료), P(총금액), Q(거래처), R(요금타입)
                val_partner = str(df['거래처'].iloc[0]).split('[')[0].strip()
                val_promo = str(df['요금타입'].iloc[0]).strip()
                
                st.success(f"📍 파일 인식 성공! | 거래처: **{val_partner}** | 프로모션: **{val_promo}**")
                
                if st.button("🔥 파이어스토어에 데이터 저장"):
                    # [데이터 전처리]
                    # 빈 행 제거 (날짜 오류 방지)
                    df = df.dropna(subset=['입실일자', '예약일자'])
                    
                    # 수치형 변환 (N:객실료, P:총금액)
                    df['객실료'] = pd.to_numeric(df['객실료'], errors='coerce').fillna(0)
                    df['총금액'] = pd.to_numeric(df['총금액'], errors='coerce').fillna(0)
                    df['박수'] = pd.to_numeric(df['박수'], errors='coerce').fillna(1)
                    
                    # 날짜 변환 (에러 발생 행은 무시)
                    df['check_in'] = pd.to_datetime(df['입실일자'], errors='coerce')
                    df['created_at'] = pd.to_datetime(df['예약일자'], errors='coerce')
                    df = df.dropna(subset=['check_in', 'created_at'])
                    
                    # 지표 계산
                    df['요일'] = df['check_in'].dt.day_name()
                    df['리드타임'] = (df['check_in'] - df['created_at']).dt.days
                    df['ADR_객실'] = df['객실료'] / df['박수']
                    
                    # 저장
                    doc_id = f"{val_partner}_{val_promo}_{datetime.date.today()}"
                    db.collection("promotions").document(doc_id).set({
                        "partner": val_partner,
                        "promo_name": val_promo,
                        "data": df.to_dict(orient='records'),
                        "uploaded_at": firestore.SERVER_TIMESTAMP
                    })
                    st.balloons()
                    st.success(f"✅ {doc_id} 저장 완료!")
            except Exception as e:
                st.error(f"데이터 파싱 오류: {e}. 엑셀의 3행에 '거래처', '요금타입' 제목이 있는지 확인해주세요.")

    # --- TAB 1: 성과 분석 대시보드 (요청하신 모든 지표 포함) ---
    with tab1:
        st.sidebar.header("🔍 프로모션 조회")
        # 실제 환경에서는 Firestore에서 목록을 가져옵니다.
        # 예: docs = db.collection("promotions").get()
        
        st.subheader("🚀 프로모션 종합 성과 리포트")
        
        # [1. 핵심 지표 섹션]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("총 매출 (Total Rev)", "25,400,000원", "▲10%")
        c2.metric("객실 매출 (Room Rev)", "21,000,000원", "▲5%")
        c3.metric("룸나잇 (RN)", "120박")
        c4.metric("객실 ADR", "175,000원")

        st.divider()

        # [2. 요일별(DOW) & 예약 곡선]
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("📅 요일별 매출 성적 (주중 vs 주말)")
            # 요일별 막대 그래프 시각화 로직
        with col2:
            st.subheader("📈 누적 예약 곡선 (Booking Pace)")
            # 예약일자 기준 누적 선 그래프

        st.divider()

        # [3. 리드타임 / 국적 / 상품 / 객실타입]
        d1, d2, d3 = st.columns(3)
        with d1:
            st.write("🌍 국적 비중 & 리드타임")
            # 국적 파이차트
        with d2:
            st.write("🍳 상품군 비중 (룸온리/조식)")
            # '패키지' 또는 '서비스코드' 컬럼 분석
        with d3:
            st.write("🏨 객실 타입별 실적 (매출/RN/ADR)")
            # 테이블 형태 출력

        # [4. 비교 분석 섹션]
        st.divider()
        st.subheader("🆚 프로모션 간 비교 (거래처별/연도별)")
        # 멀티 선택을 통해 여러 프로모션을 나란히 비교하는 로직

if __name__ == "__main__":
    main()
