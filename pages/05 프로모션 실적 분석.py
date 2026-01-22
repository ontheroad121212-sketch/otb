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
    st.title("🔥 엠버 프로모션 실적 분석 & 통합 관리")

    tab1, tab2 = st.tabs(["📊 성과 분석 대시보드", "📤 데이터 업로드 (Firestore)"])

    # --- TAB 2: 데이터 업로드 (샘플 파일 구조 완벽 반영) ---
    with tab2:
        st.header("프로모션 엑셀 파일 업로드")
        uploaded_file = st.file_uploader("거래처에서 내려받은 프리즘/OTA 엑셀을 올려주세요", type=['xlsx', 'csv'])
        
        if uploaded_file:
            # 1. 고정 좌표(Q3, R3)에서 정보 추출
            # Pandas는 0부터 시작: 3행(index 2), Q열(index 16), R열(index 17)
            df_info = pd.read_excel(uploaded_file, header=None, nrows=3)
            val_partner = str(df_info.iloc[1, 16]).split('[')[0].strip() # 'PRIZM[41]' -> 'PRIZM'
            val_promo = str(df_info.iloc[1, 17]).strip()
            
            st.success(f"📍 파일 인식 완료: **거래처 - {val_partner}** | **요금타입 - {val_promo}**")
            
            # 2. 실제 데이터 영역 로드 (4행부터 데이터 시작)
            df = pd.read_excel(uploaded_file, skiprows=2)
            df.columns = [str(c).strip() for c in df.columns] # 컬럼명 공백 제거

            if st.button("🚀 이 데이터를 분석 엔진에 저장"):
                try:
                    # 데이터 전처리 (ADR 계산 및 날짜 처리)
                    df['객실료'] = pd.to_numeric(df['객실료'], errors='coerce').fillna(0)
                    df['총금액'] = pd.to_numeric(df['총금액'], errors='coerce').fillna(0)
                    df['박수'] = pd.to_numeric(df['박수'], errors='coerce').fillna(0)
                    
                    df['입실일자'] = pd.to_datetime(df['입실일자'])
                    df['예약일자'] = pd.to_datetime(df['예약일자'])
                    df['요일'] = df['입실일자'].dt.day_name()
                    df['리드타임'] = (df['입실일자'] - df['예약일자']).dt.days
                    
                    # 저장용 딕셔너리 생성
                    data_to_save = {
                        "partner": val_partner,
                        "promo_name": val_promo,
                        "uploaded_at": firestore.SERVER_TIMESTAMP,
                        "data": df.to_dict(orient='records')
                    }
                    
                    doc_id = f"{val_partner}_{val_promo}_{datetime.date.today()}"
                    db.collection("promotions").document(doc_id).set(data_to_save)
                    st.balloons()
                    st.success(f"✅ {doc_id} 문서가 Firestore에 안전하게 저장되었습니다.")
                except Exception as e:
                    st.error(f"데이터 처리 중 오류 발생: {e}")

    # --- TAB 1: 성과 분석 대시보드 (원하시는 기능 집약) ---
    with tab1:
        st.sidebar.header("🔍 분석 필터")
        # 실제로는 Firestore에서 목록을 가져오지만, 여기서는 로직만 구성
        sel_partner = st.sidebar.selectbox("거래처 선택", ["PRIZM", "호텔타임", "데일리호텔", "야놀자"])
        sel_promo = st.sidebar.text_input("프로모션명 검색", "11TO11")
        
        # [데이터가 로드되었다고 가정하고 시각화 진행]
        # (실제 환경에서는 db.collection().where().get()으로 df_main 생성)
        
        st.subheader(f"📅 [{sel_partner}] {sel_promo} 분석 리포트")
        
        # 1. 상단 핵심 지표 (Comparison 포함)
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("총 매출 (Total Rev)", "25,400,000원", "▲12%")
        m2.metric("객실 매출 (Room Rev)", "21,000,000원", "▲8%")
        m3.metric("총 룸나잇 (RN)", "120박", "▲5박")
        m4.metric("객실 ADR", "175,000원", "▼2,000원")

        st.divider()

        # 2. 요일별(DOW) 성적 & 예약 곡선
        col_left, col_right = st.columns(2)
        with col_left:
            st.subheader("📅 요일별 매출 & ADR (주중/주말 잠식 분석)")
            # 
            st.info("금/토/일에 매출이 쏠리는지, 주중 ADR이 방어되는지 확인합니다.")
            
        with col_right:
            st.subheader("📈 누적 예약 곡선 (Booking Curve)")
            # 
            st.info("프로모션 시작 후 며칠 만에 예약이 몰렸는지 Pace를 분석합니다.")

        st.divider()

        # 3. 상세 분포 (국적, LOS, 상품비중, 객실타입)
        c1, c2, c3 = st.columns(3)
        with c1:
            st.subheader("🌍 국적 및 리드타임")
            # 도넛 차트로 국적 비중 시각화
        with c2:
            st.subheader("🍱 상품별 비중 (Room Only vs BF)")
            # 샘플 파일의 '패키지' 또는 '요금타입' 기반 비중 분석
        with c3:
            st.subheader("🏨 객실 타입별 실적")
            # 매출 / 룸나잇 / ADR 표 출력

        # 4. 비교 분석 섹션 (과거 데이터와 매칭)
        st.divider()
        st.subheader("🆚 과거 프로모션 비교 분석 (YoY)")
        # 멀티 셀렉트로 과거 데이터를 불러와 사이드 바이 사이드로 차트 비교하는 영역

if __name__ == "__main__":
    main()
