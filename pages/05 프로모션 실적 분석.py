import streamlit as st
import pandas as pd
import plotly.express as px
from firebase_admin import firestore
import datetime

db = firestore.client()

def main():
    st.set_page_config(page_title="엠버 프로모션 엔진", layout="wide")
    st.title("🏨 엠버 프로모션 성과 분석 시스템")

    tab1, tab2 = st.tabs(["📊 성과 분석 대시보드", "📤 데이터 업로드"])

    # --- TAB 2: 데이터 업로드 (Q3, R3 추출 로직 포함) ---
    with tab2:
        st.header("엑셀 데이터 업로드")
        uploaded_file = st.file_uploader("거래처 엑셀 파일을 올려주세요", type=['xlsx'])
        
        if uploaded_file:
            # 1. 특정 셀(Q3, R3) 값 추출을 위해 별도로 읽기
            # header=None으로 읽어서 좌표로 접근 (Q=16번 열, R=17번 열 / 3행=index 2)
            df_coord = pd.read_excel(uploaded_file, header=None)
            
            try:
                # 엑셀의 Q3는 [2, 16], R3는 [2, 17] 위치입니다.
                auto_partner = str(df_coord.iloc[2, 16]) 
                auto_promo = str(df_coord.iloc[2, 17])
                
                st.success(f"📍 파일 인식 성공! | 거래처: **{auto_partner}** | 요금타입: **{auto_promo}**")
                
                # 2. 실제 데이터 영역 읽기 (보통 데이터는 4~5행부터 시작하므로 필요시 skiprows 조정)
                # 여기서는 4행부터 데이터라고 가정 (skiprows=3)
                df_main = pd.read_excel(uploaded_file, skiprows=3) 
                
                if st.button("이 데이터로 파이어스토어 저장"):
                    # 전처리: ADR 계산 (총매출/박수, 객실매출/박수)
                    df_main['ADR_총액'] = df_main['총매출'] / df_main['박수']
                    df_main['ADR_객실'] = df_main['객실매출'] / df_main['박수']
                    
                    # 날짜 및 요일 처리
                    df_main['입실일'] = pd.to_datetime(df_main['입실일'])
                    df_main['예약일'] = pd.to_datetime(df_main['예약일'])
                    df_main['요일'] = df_main['입실일'].dt.day_name()
                    df_main['리드타임'] = (df_main['입실일'] - df_main['예약일']).dt.days

                    data_dict = df_main.to_dict(orient='records')
                    doc_id = f"{auto_partner}_{auto_promo}_{datetime.date.today()}"
                    
                    db.collection("promotions").document(doc_id).set({
                        "partner": auto_partner,
                        "promo_name": auto_promo,
                        "data": data_dict,
                        "uploaded_at": firestore.SERVER_TIMESTAMP
                    })
                    st.balloons()
                    st.success(f"✅ {doc_id} 저장 완료!")
            except Exception as e:
                st.error(f"파일 구조가 다릅니다: {e}")

    # --- TAB 1: 분석 대시보드 ---
    with tab1:
        st.sidebar.header("🔍 분석 필터")
        # Firestore에서 파트너/프로모션 목록을 가져오는 로직 (생략)
        sel_partner = st.sidebar.selectbox("거래처", ["호텔타임", "데일리호텔", "야놀자"])
        
        # 지표 출력 (총매출, 객실매출, RN, ADR)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("총 매출", "0원") # 실제 데이터 연결 필요
        c2.metric("객실 매출", "0원")
        c3.metric("총 룸나잇", "0박")
        c4.metric("객실 ADR", "0원")

        st.divider()

        # 요일별 성적 및 예약 곡선
        col_left, col_right = st.columns(2)
        with col_left:
            st.subheader("📅 요일별 매출 & ADR")
            # 
        with col_right:
            st.subheader("📈 누적 예약 곡선 (Pace)")
            # 

        st.divider()
        
        # 비중 분석 (국적, 상품, 객실타입)
        b1, b2, b3 = st.columns(3)
        with b1:
            st.subheader("🌍 국적")
            # 
        with b2:
            st.subheader("🍱 상품 비중 (Room/BF)")
        with b3:
            st.subheader("🛏️ 객실 타입별 실적")

if __name__ == "__main__":
    main()
