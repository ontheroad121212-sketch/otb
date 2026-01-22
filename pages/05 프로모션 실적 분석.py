import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from firebase_admin import firestore
import datetime

# Firestore 클라이언트 초기화 (기존 설정이 되어 있다고 가정)
db = firestore.client()

def get_all_promotions():
    """Firestore에서 저장된 모든 프로모션 목록을 불러옵니다."""
    docs = db.collection("promotions").stream()
    promo_list = []
    for doc in docs:
        d = doc.to_dict()
        display_name = f"[{d.get('partner')}] {d.get('promo_name')} ({d.get('upload_date')})"
        promo_list.append({"id": doc.id, "display": display_name, "data": d.get('data'), "partner": d.get('partner')})
    return promo_list

def prepare_df(raw_data):
    """분석에 필요한 파생 지표들을 계산합니다."""
    df = pd.DataFrame(raw_data)
    df['입실일자'] = pd.to_datetime(df['입실일자'])
    df['예약일자'] = pd.to_datetime(df['예약일자'])
    df['요일'] = df['입실일자'].dt.day_name()
    df['주말여부'] = df['입실일자'].dt.dayofweek >= 4 # 금, 토, 일 기준
    df['리드타임'] = (df['입실일자'] - df['예약일자']).dt.days
    # 조식 포함 여부 (서비스코드에 BF 포함 시 조식상품으로 간주)
    df['상품구분'] = df['서비스코드'].apply(lambda x: '조식포함' if 'BF' in str(x) else '룸온리')
    return df

def main():
    st.set_page_config(page_title="엠버 프로모션 분석 엔진", layout="wide")
    st.title("📊 엠버 프로모션 성과 분석 & 비교 대시보드")

    tab1, tab2 = st.tabs(["📈 성과 분석 및 비교", "📤 데이터 업로드"])

    # --- TAB 2: 데이터 업로드 (파일 자동 인식) ---
    with tab2:
        st.header("엑셀 데이터 업로드")
        uploaded_file = st.file_uploader("거래처 엑셀 파일을 드래그하세요 (Q3, R3 자동인식)", type=['xlsx'])
        
        if uploaded_file:
            # 3행(index 2)을 제목줄로 인식
            df_raw = pd.read_excel(uploaded_file, header=2)
            df_raw.columns = [str(c).strip() for c in df_raw.columns]
            
            try:
                # 첫 행에서 거래처와 요금타입 추출
                val_partner = str(df_raw['거래처'].iloc[0]).split('[')[0].strip()
                val_promo = str(df_raw['요금타입'].iloc[0]).strip()
                st.success(f"📍 파일 인식 성공: **{val_partner}** / **{val_promo}**")
                
                if st.button("🔥 파이어스토어에 데이터 차곡차곡 쌓기"):
                    # 데이터 정제 및 업로드
                    df_clean = df_raw.dropna(subset=['입실일자', '객실료'])
                    doc_id = f"{val_partner}_{val_promo}_{datetime.date.today()}"
                    
                    db.collection("promotions").document(doc_id).set({
                        "partner": val_partner,
                        "promo_name": val_promo,
                        "upload_date": str(datetime.date.today()),
                        "data": df_clean.to_dict(orient='records')
                    })
                    st.balloons()
                    st.success(f"✅ {val_partner} 데이터가 저장되었습니다. 이제 분석 탭에서 확인하세요!")
            except Exception as e:
                st.error(f"데이터 파싱 오류: {e}")

    # --- TAB 1: 분석 및 비교 (핵심 기능) ---
    with tab1:
        all_promos = get_all_promotions()
        if not all_promos:
            st.info("데이터가 없습니다. 먼저 업로드를 진행해 주세요.")
            return

        # [사이드바 필터]
        st.sidebar.header("🔍 분석 대상")
        target_promo = st.sidebar.selectbox("기준 프로모션 선택", all_promos, format_func=lambda x: x['display'])
        
        compare_on = st.sidebar.checkbox("과거/타 프로모션과 비교 (YoY)")
        compare_promo = None
        if compare_on:
            compare_promo = st.sidebar.selectbox("비교 대상 선택", all_promos, format_func=lambda x: x['display'])

        df_main = prepare_df(target_promo['data'])

        # 1. 핵심 지표 (KPI Cards)
        st.subheader(f"📍 [{target_promo['partner']}] {target_promo['display']} 핵심 성과")
        k1, k2, k3, k4 = st.columns(4)
        
        def get_kpis(df):
            return df['총금액'].sum(), df['객실료'].sum(), df['박수'].sum(), df['객실료'].sum()/df['박수'].sum()

        t_rev, r_rev, rn, adr = get_kpis(df_main)
        
        if compare_promo:
            df_comp = prepare_df(compare_promo['data'])
            ct_rev, cr_rev, crn, cadr = get_kpis(df_comp)
            k1.metric("총 매출", f"{t_rev:,.0f}원", f"{t_rev-ct_rev:,.0f}원")
            k2.metric("객실 매출", f"{r_rev:,.0f}원", f"{r_rev-cr_rev:,.0f}원")
            k3.metric("룸나잇(RN)", f"{rn}박", f"{rn-crn}박")
            k4.metric("객실 ADR", f"{adr:,.0f}원", f"{adr-cadr:,.0f}원")
        else:
            k1.metric("총 매출", f"{t_rev:,.0f}원")
            k2.metric("객실 매출", f"{r_rev:,.0f}원")
            k3.metric("룸나잇(RN)", f"{rn}박")
            k4.metric("객실 ADR", f"{adr:,.0f}원")

        st.divider()

        # 2. 요일별 성적 (DOW) & 예약 곡선 (Booking Curve)
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("📅 요일별 매출 성적 (주중 점유 방어율)")
            dow_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
            dow_data = df_main.groupby('요일').agg({'총금액':'sum', '객실료':'mean'}).reindex(dow_order).reset_index()
            fig_dow = px.bar(dow_data, x='요일', y='총금액', color='객실료', title="요일별 매출 (색상은 ADR)")
            st.plotly_chart(fig_dow, use_container_width=True)

        with col2:
            st.subheader("📈 예약 생산 곡선 (Booking Pace)")
            curve_df = df_main.sort_values('예약일자')
            curve_df['cum_rn'] = curve_df['박수'].cumsum()
            fig_curve = px.line(curve_df, x='예약일자', y='cum_rn', title="프로모션 시작 후 예약 누적 추이")
            st.plotly_chart(fig_curve, use_container_width=True)

        st.divider()

        # 3. 상세 분포 (리드타임, 국적, 상품비중, 객실타입)
        d1, d2, d3 = st.columns(3)
        with d1:
            st.write("🌍 국적 비중 & 평균 리드타임")
            st.plotly_chart(px.pie(df_main, names='국적', hole=0.4), use_container_width=True)
            st.info(f"평균 예약 리드타임: **{df_main['리드타임'].mean():.1f}일**")
        with d2:
            st.write("🍳 상품별 비중 (룸온리 vs 조식)")
            st.plotly_chart(px.pie(df_main, names='상품구분'), use_container_width=True)
        with d3:
            st.write("🏨 객실 타입별 실적")
            room_type_perf = df_main.groupby('객실타입').agg({'총금액':'sum', '박수':'sum', '객실료':'mean'}).reset_index()
            st.dataframe(room_type_perf.style.format({'총금액': '{:,.0f}', '객실료': '{:,.0f}'}))

if __name__ == "__main__":
    main()
