import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from firebase_admin import firestore
import datetime

# Firestore 클라이언트 설정 (이미 초기화되었다고 가정)
db = firestore.client()

# --- 데이터 처리 함수 ---
def process_excel_data(df):
    """업로드된 데이터의 ADR 및 필요 지표 자동 계산"""
    # 컬럼 표준화 (공백 제거 등)
    df.columns = [c.strip() for c in df.columns]
    
    # 1. ADR 계산: 총매출 기준 ADR / 객실매출 기준 ADR 구분
    # '총매출', '객실매출', '박수' 컬럼이 있다고 가정
    df['ADR_총액'] = df['총매출'] / df['박수']
    df['ADR_객실'] = df['객실매출'] / df['박수']
    
    # 2. 날짜 데이터 변환
    df['입실일'] = pd.to_datetime(df['입실일'])
    df['예약일'] = pd.to_datetime(df['예약일'])
    df['요일'] = df['입실일'].dt.day_name()
    df['주말여부'] = df['입실일'].dt.dayofweek >= 4 # 금, 토, 일
    df['리드타임'] = (df['입실일'] - df['예약일']).dt.days
    
    return df

# --- 메인 앱 구성 ---
def main():
    st.set_page_config(page_title="엠버 프로모션 엔진", layout="wide")
    
    tabs = st.tabs(["📊 성과 분석 대시보드", "📤 데이터 업로드 및 저장"])

    # --- TAB 1: 데이터 업로드 ---
    with tabs[1]:
        st.header("엑셀 데이터 업로드")
        uploaded_file = st.file_uploader("거래처에서 내려받은 엑셀 파일을 올려주세요", type=['xlsx', 'csv'])
        
        if uploaded_file:
            df_raw = pd.read_excel(uploaded_file) if uploaded_file.name.endswith('.xlsx') else pd.read_csv(uploaded_file)
            
            # 파일에서 정보 자동 추출
            try:
                auto_partner = df_raw['거래처'].iloc[0]
                auto_promo = df_raw['요금타입'].iloc[0]
                
                st.info(f"📍 탐지된 정보: **거래처 - {auto_partner}** | **프로모션 - {auto_promo}**")
                
                if st.button("파이어스토어에 이 정보로 저장"):
                    processed_df = process_excel_data(df_raw)
                    data_dict = processed_df.to_dict(orient='records')
                    
                    doc_id = f"{auto_partner}_{auto_promo}_{datetime.date.today()}"
                    db.collection("promotions").document(doc_id).set({
                        "partner": auto_partner,
                        "promo_name": auto_promo,
                        "upload_date": str(datetime.date.today()),
                        "data": data_dict
                    })
                    st.success(f"✅ {doc_id} 저장 완료!")
            except KeyError:
                st.error("파일에 '거래처' 또는 '요금타입' 컬럼이 없습니다. 확인해 주세요.")

    # --- TAB 2: 성과 분석 대시보드 ---
    with tabs[0]:
        st.header("프로모션 성과 분석")
        
        # 필터 영역
        with st.sidebar:
            st.header("🔍 조회 설정")
            # Firestore에서 목록 불러오기 (실제 운영시에는 실시간 쿼리)
            target_partner = st.selectbox("거래처 선택", ["호텔타임", "데일리호텔", "야놀자", "기타"])
            target_promo = st.text_input("프로모션명 검색 (직접 입력)")
            compare_mode = st.checkbox("전년/타 프로모션 비교")

        # 예시 데이터 로드 및 시각화 (실제 로직은 db.collection().get() 사용)
        # 여기서는 df_main이 로드되었다고 가정하고 분석 진행
        st.subheader("📌 Key Performance Indicators")
        col1, col2, col3, col4 = st.columns(4)
        
        # 지표 예시 (df_main 데이터 기반)
        col1.metric("총 매출", "25,400,000원", "15%")
        col2.metric("객실 매출", "21,000,000원", "10%")
        col3.metric("총 룸나잇", "120박")
        col4.metric("객실 ADR", "175,000원")

        st.divider()

        # 요일별 및 예약 곡선
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("📅 요일별 점유 및 ADR")
            # 
            st.info("여기에 요일별 막대 그래프(매출)와 꺾은선(ADR)이 표시됩니다.")
            
        with c2:
            st.subheader("📈 예약 생산 곡선 (Booking Curve)")
            # 
            st.info("프로모션 시작 후 예약이 쌓이는 속도를 분석합니다.")

        st.divider()
        
        # 상세 비중 분석
        c3, c4, c5 = st.columns(3)
        with c3:
            st.subheader("🌍 국적 비중")
            # 
        with c4:
            st.subheader("🍳 상품별 판매 비중")
            # 룸온리 vs 조식 포함 등 3개 상품 비교
        with c5:
            st.subheader("🏢 객실 타입별 실적")
            # 매출 / 룸나잇 / ADR 표

if __name__ == "__main__":
    main()
