import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from firebase_admin import firestore
import datetime

# Firestore 클라이언트 설정 (기존 설정 유지)
db = firestore.client()

def main():
    st.set_page_config(page_title="엠버 프로모션 분석 엔진", layout="wide")
    st.title("🔥 엠버 프로모션 실적 분석 시스템")

    tab1, tab2 = st.tabs(["📊 성과 분석 대시보드", "📤 데이터 업로드 (Firestore)"])

    # --- TAB 2: 데이터 업로드 (오류 방지 로직 강화) ---
    with tab2:
        st.header("프로모션 엑셀 파일 업로드")
        uploaded_file = st.file_uploader("거래처 엑셀 파일을 올려주세요", type=['xlsx', 'csv'])
        
        if uploaded_file:
            # 1. 고정 좌표(Q3, R3) 추출 (Pandas index 2, 16/17)
            df_info = pd.read_excel(uploaded_file, header=None, nrows=3)
            try:
                val_partner = str(df_info.iloc[1, 16]).split('[')[0].strip()
                val_promo = str(df_info.iloc[1, 17]).strip()
                st.success(f"📍 파일 인식: **{val_partner}** | **{val_promo}**")
            except:
                val_partner, val_promo = "Unknown", "Unknown"

            # 2. 실제 데이터 영역 로드 (3행부터 제목줄)
            df = pd.read_excel(uploaded_file, skiprows=2)
            df.columns = [str(c).strip() for c in df.columns]
            
            # 빈 행 제거 (날짜 오류 방지 핵심)
            df = df.dropna(subset=['입실일자', '객실료']) 

            if st.button("🚀 분석 엔진에 데이터 저장"):
                try:
                    # 날짜 변환 (errors='coerce'로 공백 무시)
                    df['입실일자'] = pd.to_datetime(df['입실일자'], errors='coerce')
                    df['예약일자'] = pd.to_datetime(df['예약일자'], errors='coerce')
                    df = df.dropna(subset=['입실일자', '예약일자']) # 변환 실패 행 제거

                    # 수치 변환
                    for col in ['객실료', '총금액', '박수']:
                        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
                    
                    # 파생 지표 계산
                    df['요일'] = df['입실일자'].dt.day_name()
                    df['주말여부'] = df['입실일자'].dt.dayofweek >= 4 # 금토일
                    df['리드타임'] = (df['입실일자'] - df['예약일자']).dt.days
                    
                    # Firestore 저장
                    doc_id = f"{val_partner}_{val_promo}_{datetime.date.today()}"
                    db.collection("promotions").document(doc_id).set({
                        "partner": val_partner, "promo_name": val_promo,
                        "data": df.to_dict(orient='records'),
                        "uploaded_at": firestore.SERVER_TIMESTAMP
                    })
                    st.success(f"✅ {doc_id} 저장 완료!")
                except Exception as e:
                    st.error(f"데이터 처리 중 오류 발생: {e}")

    # --- TAB 1: 성과 분석 대시보드 (기능 구현) ---
    with tab1:
        # DB에서 목록 가져오기 (예시)
        st.sidebar.header("🔍 프로모션 선택")
        # 실제 운영시: docs = db.collection("promotions").get() 후 리스트화
        # 여기서는 저장된 데이터를 불러왔다고 가정하고 분석 화면 구성
        
        # 1. 상단 요약 지표
        st.subheader("📍 Key Performance Indicators")
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("총 매출 (Total)", "50,760,000원") 
        k2.metric("객실 매출 (Room)", "40,260,000원")
        k3.metric("총 룸나잇 (RN)", "120박")
        k4.metric("객실 ADR", "335,500원")

        st.divider()

        # 2. 요일별 분석 (DOW) & 예약 곡선
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("📅 요일별 실적 (주중 vs 주말)")
            # 
            st.caption("요일별 예약 집중도와 ADR 방어율을 분석합니다.")
            
        with c2:
            st.subheader("📈 누적 예약 곡선 (Booking Curve)")
            # 
            st.caption("프로모션 오픈 후 시간 경과에 따른 예약 생산 속도입니다.")

        st.divider()

        # 3. 비중 분석
        st.subheader("📊 상세 분포 분석")
        d1, d2, d3 = st.columns(3)
        with d1:
            st.write("🌍 국적 비중")
            # 
        with d2:
            st.write("🍳 상품(패키지) 판매 비중")
            # 조식포함 vs 룸온리 비중 계산
        with d3:
            st.write("🏨 객실 타입별 성과")
            # 매출 / RN / ADR 표

        # 4. 비교 분석 (YoY)
        st.divider()
        st.subheader("🆚 프로모션 간 비교 (Target vs Compare)")
        # 여기서 두 개의 프로모션을 선택해 막대 그래프로 나란히 비교

if __name__ == "__main__":
    main()
