import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from firebase_admin import firestore
import datetime

# Firestore 연결 (기본 설정이 되어 있다고 가정)
db = firestore.client()

def get_promo_data(promo_id):
    """Firestore에서 프로모션 ID로 데이터 불러오기"""
    doc = db.collection("promotions").document(promo_id).get()
    if doc.exists:
        data = doc.to_dict().get('data', [])
        return pd.DataFrame(data)
    return pd.DataFrame()

def main():
    st.set_page_config(page_title="앰버 프로모션 분석 엔진", layout="wide")
    st.title("📈 프로모션 성과 분석 & 비교 대시보드")

    # --- [사이드바] 필터 및 비교 설정 ---
    st.sidebar.header("🎯 분석 대상 설정")
    
    # 1. 거래처 및 프로모션 선택
    partners = ["호텔타임", "데일리호텔", "야놀자", "네이버", "공홈"]
    selected_partner = st.sidebar.selectbox("거래처 선택", partners)
    
    # 실제 운영 시에는 DB에서 해당 거래처의 promo_id 리스트를 가져오게 구성
    all_promos = ["2026-01_신년특가", "2025-01_신년특가(YoY)", "2025-12_연말특가"]
    target_promo = st.sidebar.selectbox("기준 프로모션", all_promos)
    compare_promo = st.sidebar.selectbox("비교 프로모션 (전년 등)", [None] + all_promos)

    # 데이터 로드
    df_main = get_promo_data(target_promo)
    df_comp = get_promo_data(compare_promo) if compare_promo else pd.DataFrame()

    if df_main.empty:
        st.info("데이터를 선택해주세요. Firestore에 저장된 프로모션 정보가 표시됩니다.")
        return

    # --- [데이터 전처리] ---
    for df in [df_main, df_comp]:
        if not df.empty:
            df['check_in'] = pd.to_datetime(df['check_in'])
            df['created_at'] = pd.to_datetime(df['created_at'])
            df['dow'] = df['check_in'].dt.day_name()
            df['is_weekend'] = df['check_in'].dt.dayofweek >= 4 # 금,토,일 기준(호텔 기준 설정)
            df['lead_time'] = (df['check_in'] - df['created_at']).dt.days

    # --- [섹션 1] 핵심 지표 (Comparison Cards) ---
    st.subheader("📍 핵심 성과 지표 (Key Metrics)")
    m1, m2, m3, m4 = st.columns(4)
    
    def get_metrics(df):
        rev = df['revenue'].sum()
        rn = len(df)
        adr = rev / rn if rn > 0 else 0
        los = df['stay_nights'].mean() if not df.empty else 0
        return rev, rn, adr, los

    m_rev, m_rn, m_adr, m_los = get_metrics(df_main)
    
    if not df_comp.empty:
        c_rev, c_rn, c_adr, c_los = get_metrics(df_comp)
        m1.metric("총 매출", f"{m_rev:,.0f}원", f"{m_rev-c_rev:,.0f}원")
        m2.metric("룸나잇", f"{m_rn}개", f"{m_rn-c_rn}개")
        m3.metric("ADR", f"{m_adr:,.0f}원", f"{m_adr-c_adr:,.0f}원")
        m4.metric("평균 LOS", f"{m_los:.1f}박", f"{m_los-c_los:.1f}박")
    else:
        m1.metric("총 매출", f"{m_rev:,.0f}원")
        m2.metric("룸나잇", f"{m_rn}개")
        m3.metric("ADR", f"{m_adr:,.0f}원")
        m4.metric("평균 LOS", f"{m_los:.1f}박")

    st.divider()

    # --- [섹션 2] 요일별(DOW) & 예약 곡선(Booking Curve) ---
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("📅 요일별 성적 (DOW Analysis)")
        # 
        dow_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        dow_summary = df_main.groupby('dow').agg({'revenue':'sum', 'adr':'mean'}).reindex(dow_order).reset_index()
        
        fig_dow = px.bar(dow_summary, x='dow', y='revenue', color='adr',
                         title="요일별 매출 (색상: ADR)",
                         labels={'revenue':'매출', 'dow':'요일', 'adr':'ADR'})
        st.plotly_chart(fig_dow, use_container_width=True)
        
        # 주중/주말 비중 텍스트 요약
        weekday_ratio = len(df_main[df_main['is_weekend']==False]) / len(df_main) * 100
        st.caption(f"💡 현재 프로모션의 **주중 투숙 비중은 {weekday_ratio:.1f}%** 입니다.")

    with col2:
        st.subheader("📈 누적 예약 곡선 (Booking Curve)")
        # 
        # 예약 생성일 기준 누적 데이터
        df_main = df_main.sort_values('created_at')
        df_main['count'] = 1
        df_main['cumulative_rn'] = df_main['count'].cumsum()
        
        fig_curve = px.line(df_main, x='created_at', y='cumulative_rn', 
                            title="프로모션 진행 기간 예약 생산 속도")
        st.plotly_chart(fig_curve, use_container_width=True)

    st.divider()

    # --- [섹션 3] 상세 분포 (리드타임, 국적, 상품군) ---
    c1, c2, c3 = st.columns(3)
    
    with c1:
        st.subheader("⏱️ 리드타임 분포")
        fig_lt = px.histogram(df_main, x='lead_time', nbins=10, title="예약 시점(D-Day)")
        st.plotly_chart(fig_lt, use_container_width=True)

    with c2:
        st.subheader("🌍 국적 & 상품 비중")
        tab_nat, tab_meal = st.tabs(["국적", "조식포함여부"])
        with tab_nat:
            st.plotly_chart(px.pie(df_main, names='nationality', hole=0.4), use_container_width=True)
        with tab_meal:
            st.plotly_chart(px.pie(df_main, names='meal_plan'), use_container_width=True)

    with c3:
        st.subheader("🏨 객실 타입별 실적")
        room_perf = df_main.groupby('room_type').agg({
            'revenue': 'sum',
            'count': 'sum',
            'adr': 'mean'
        }).rename(columns={'count': '룸나잇'}).reset_index()
        st.dataframe(room_perf.style.format({'revenue': '{:,.0f}', 'adr': '{:,.0f}'}))

if __name__ == "__main__":
    main()
