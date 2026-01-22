import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from firebase_admin import firestore
import datetime

# 1. Firestore 클라이언트 초기화 (기존 설정 유지)
# 앱 시작 시 한 번만 초기화되도록 설정되어 있어야 합니다.
try:
    db = firestore.client()
except Exception as e:
    st.error(f"Firestore 연결 확인 필요: {e}")

# --- 데이터 처리 및 변환 함수 (모든 심화 지표 생성) ---
def prepare_df(raw_data):
    """Firestore에서 가져온 원본 데이터를 분석용으로 완벽하게 가공합니다."""
    if not raw_data:
        return pd.DataFrame()
        
    df = pd.DataFrame(raw_data)
    
    # 날짜 데이터 변환 (오류 방지용)
    df['입실일자'] = pd.to_datetime(df['입실일자'], errors='coerce')
    df['예약일자'] = pd.to_datetime(df['예약일자'], errors='coerce')
    df['퇴실일자'] = pd.to_datetime(df['퇴실일자'], errors='coerce')
    
    # 수치 데이터 변환
    for col in ['객실료', '총금액', '박수', '서비스료']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    
    # 1. 요일 및 주말 분석 (DOW)
    dow_map = {
        'Monday': '01.월', 'Tuesday': '02.화', 'Wednesday': '03.수', 
        'Thursday': '04.목', 'Friday': '05.금', 'Saturday': '06.토', 'Sunday': '07.일'
    }
    df['요일'] = df['입실일자'].dt.day_name().map(dow_map)
    df['주말여부'] = df['입실일자'].dt.dayofweek >= 4 # 금, 토, 일 (호텔 기준)
    
    # 2. 리드타임 및 구간화
    df['리드타임'] = (df['입실일자'] - df['예약일자']).dt.days
    lt_bins = [-999, 0, 3, 7, 14, 30, 999]
    lt_labels = ['당일', '1-3일전', '4-7일전', '8-14일전', '15-30일전', '30일+']
    df['LT구간'] = pd.cut(df['리드타임'], bins=lt_bins, labels=lt_labels)
    
    # 3. 상품 구분 (조식 포함 여부)
    # 서비스코드에 'BF'가 있으면 조식포함으로 판단
    df['상품구분'] = df['서비스코드'].apply(lambda x: '🍳 조식포함' if 'BF' in str(x) else '🏨 룸온리')
    
    # 4. ADR 계산
    df['ADR_객실'] = df.apply(lambda x: x['객실료'] / x['박수'] if x['박수'] > 0 else 0, axis=1)
    
    # 5. LOS (Stay Nights)
    df['LOS'] = df['박수'] # 기본적으로 박수와 동일
    
    # 6. 히트맵용 데이터 (주차)
    df['입실주차'] = df['입실일자'].dt.isocalendar().week
    
    return df.dropna(subset=['입실일자'])

def get_all_promotions():
    """Firestore에 저장된 모든 프로모션 목록을 가져옵니다."""
    try:
        docs = db.collection("promotions").order_by("upload_date", direction=firestore.Query.DESCENDING).stream()
        promo_list = []
        for doc in docs:
            d = doc.to_dict()
            display_name = f"[{d.get('partner')}] {d.get('promo_name')} ({d.get('upload_date')})"
            promo_list.append({
                "id": doc.id, 
                "display": display_name, 
                "data": d.get('data'), 
                "partner": d.get('partner'),
                "promo_name": d.get('promo_name')
            })
        return promo_list
    except Exception as e:
        return []

# --- 메인 대시보드 화면 ---
def main():
    st.set_page_config(page_title="엠버 프로모션 분석 엔진 v1.0", layout="wide")
    st.title("🚀 엠버 프로모션 통합 성과 분석 엔진")

    tab1, tab2 = st.tabs(["📊 프로모션 분석 대시보드", "📤 데이터 업로드 및 업데이트"])

    # --- TAB 1: 분석 대시보드 ---
    with tab1:
        all_promos = get_all_promotions()
        
        if not all_promos:
            st.warning("데이터가 없습니다. 업로드 탭에서 엑셀 파일을 먼저 등록해주세요.")
            return

        # [사이드바 필터]
        st.sidebar.header("🔍 분석 대상 설정")
        target_promo_select = st.sidebar.selectbox("대상 프로모션 선택", all_promos, format_func=lambda x: x['display'], key="target")
        
        compare_on = st.sidebar.checkbox("비교 프로모션 활성화 (YoY/채널비교)")
        compare_promo_select = None
        if compare_on:
            compare_promo_select = st.sidebar.selectbox("비교할 프로모션 선택", all_promos, format_func=lambda x: x['display'], key="compare")

        # 데이터 가공
        df_main = prepare_df(target_promo_select['data'])
        
        # 1. 상단 핵심 지표 (KPI Cards)
        st.subheader(f"📌 [{target_promo_select['partner']}] {target_promo_select['promo_name']} 실적")
        
        def calc_metrics(df):
            trev = df['총금액'].sum()
            rrev = df['객실료'].sum()
            rn = df['박수'].sum()
            adr = rrev / rn if rn > 0 else 0
            los = df['박수'].mean() if not df.empty else 0
            return trev, rrev, rn, adr, los

        m_trev, m_rrev, m_rn, m_adr, m_los = calc_metrics(df_main)
        
        k1, k2, k3, k4, k5 = st.columns(5)
        
        if compare_on and compare_promo_select:
            df_comp = prepare_df(compare_promo_select['data'])
            c_trev, c_rrev, c_rn, c_adr, c_los = calc_metrics(df_comp)
            k1.metric("총 매출", f"{m_trev:,.0f}원", f"{m_trev-c_trev:,.0f}원")
            k2.metric("객실 매출", f"{m_rrev:,.0f}원", f"{m_rrev-c_rrev:,.0f}원")
            k3.metric("룸나잇(RN)", f"{m_rn:,.0f}박", f"{m_rn-c_rn:,.0f}박")
            k4.metric("ADR (객실단가)", f"{m_adr:,.0f}원", f"{m_adr-c_adr:,.0f}원")
            k5.metric("평균 LOS", f"{m_los:.1f}박", f"{m_los-c_los:.1f}박")
        else:
            k1.metric("총 매출", f"{m_trev:,.0f}원")
            k2.metric("객실 매출", f"{m_rrev:,.0f}원")
            k3.metric("룸나잇(RN)", f"{m_rn:,.0f}박")
            k4.metric("ADR (객실단가)", f"{m_adr:,.0f}원")
            k5.metric("평균 LOS", f"{m_los:.1f}박")

        st.divider()

        # 2. 요일별 분석 (DOW) & 예약 생산 곡선 (Booking Curve)
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("📅 요일별 실적 (주중 vs 주말 성과)")
            dow_sum = df_main.groupby('요일').agg({'총금액':'sum', 'ADR_객실':'mean'}).reset_index()
            fig_dow = px.bar(dow_sum, x='요일', y='총금액', color='ADR_객실', 
                             title="요일별 매출 (색상: ADR)", color_continuous_scale='Portland')
            st.plotly_chart(fig_dow, use_container_width=True)
            
        with col2:
            st.subheader("📈 누적 예약 생산 곡선 (Booking Pace)")
            pace_df = df_main.sort_values('예약일자')
            pace_df['누적_RN'] = pace_df['박수'].cumsum()
            fig_pace = px.line(pace_df, x='예약일자', y='누적_RN', title="프로모션 오픈 후 예약 집계 추이")
            st.plotly_chart(fig_pace, use_container_width=True)

        st.divider()

        # 3. 투숙 집중도 (Heatmap) & 리드타임 구간 (Lead Time)
        col3, col4 = st.columns(2)
        with col3:
            st.subheader("🔥 투숙일 집중도 히트맵")
            heat_data = df_main.groupby(['입실주차', '요일']).size().unstack(fill_value=0)
            # 요일 정렬
            target_cols = ['01.월', '02.화', '03.수', '04.목', '05.금', '06.토', '07.일']
            heat_data = heat_data.reindex(columns=[c for c in target_cols if c in heat_data.columns])
            fig_heat = px.imshow(heat_data, text_auto=True, aspect="auto", color_continuous_scale="YlOrRd", title="투숙 기간 집중 분포")
            st.plotly_chart(fig_heat, use_container_width=True)
            
        with col4:
            st.subheader("⏱️ 예약 리드타임 분포")
            lt_sum = df_main['LT구간'].value_counts().reindex(['당일', '1-3일전', '4-7일전', '8-14일전', '15-30일전', '30일+']).reset_index()
            fig_lt = px.bar(lt_sum, x='LT구간', y='count', color='count', title="예약 시점 비중")
            st.plotly_chart(fig_lt, use_container_width=True)

        st.divider()

        # 4. 국적 / 상품비중 / 객실타입별 실적
        d1, d2, d3 = st.columns(3)
        with d1:
            st.subheader("🌍 국적 비중")
            fig_nat = px.pie(df_main, names='국적', hole=0.5, title="예약 국적 분포")
            st.plotly_chart(fig_nat, use_container_width=True)
        with d2:
            st.subheader("🍳 상품군 판매 비중")
            fig_prod = px.pie(df_main, names='상품구분', title="조식 포함 vs 룸온리 비중", 
                              color_discrete_sequence=px.colors.qualitative.Pastel)
            st.plotly_chart(fig_prod, use_container_width=True)
        with d3:
            st.subheader("🏨 객실 타입별 실적")
            room_perf = df_main.groupby('객실타입').agg({'총금액':'sum', '박수':'sum', 'ADR_객실':'mean'}).reset_index()
            room_perf.columns = ['객실타입', '매출액', 'RN', 'ADR']
            st.dataframe(room_perf.style.format({'매출액': '{:,.0f}', 'ADR': '{:,.0f}'}))

        # 5. 부대시설(Ancillary) 상세 분석
        st.divider()
        st.subheader("🍱 부대시설 서비스 코드 분석 (Ancillary Revenue)")
        all_svcs = []
        for s in df_main['서비스목록']:
            all_svcs.extend([x.strip() for x in s if x.strip() != ''])
        if all_svcs:
            svc_df = pd.Series(all_svcs).value_counts().reset_index()
            svc_df.columns = ['서비스명', '포함건수']
            fig_svc = px.bar(svc_df, x='서비스명', y='포함건수', color='포함건수', title="가장 많이 판매된 추가 서비스")
            st.plotly_chart(fig_svc, use_container_width=True)

    # --- TAB 2: 데이터 업로드 및 Firestore 저장 ---
    with tab2:
        st.header("📤 새로운 프로모션 데이터 업데이트")
        st.markdown("""
        1. PMS에서 **'전체 고객 목록'** 엑셀을 내려받습니다.
        2. 아래 업로더에 파일을 드래그합니다.
        3. **Q3(거래처), R3(요금타입)** 정보가 맞는지 확인하고 '저장' 버튼을 누르세요.
        """)
        
        uploaded_file = st.file_uploader("엑셀 파일을 선택하세요", type=['xlsx'])
        
        if uploaded_file:
            # 헤더 정보 읽기 (Q3, R3 좌표 추출)
            # Q는 17번째(idx 16), R은 18번째(idx 17), 3행은 idx 2
            df_info = pd.read_excel(uploaded_file, header=None, nrows=3)
            
            try:
                # Q3, R3 위치에서 데이터 추출
                raw_partner = str(df_info.iloc[1, 16]).split('[')[0].strip() # 2행 17열 (Q2/Q3 위치)
                raw_promo = str(df_info.iloc[1, 17]).strip()   # 2행 18열 (R2/R3 위치)
                
                st.info(f"📁 탐지된 정보 - 거래처: **{raw_partner}** / 프로모션: **{raw_promo}**")
                
                # 실제 데이터 로드 (3행부터 제목줄)
                df_load = pd.read_excel(uploaded_file, header=2)
                df_load.columns = [str(c).strip() for c in df_load.columns]
                
                if st.button("🔥 파이어스토어에 이 프로모션 저장하기"):
                    # 데이터 정제
                    df_final = df_load.dropna(subset=['입실일자', '객실료'])
                    
                    doc_id = f"{raw_partner}_{raw_promo}_{datetime.date.today()}"
                    db.collection("promotions").document(doc_id).set({
                        "partner": raw_partner,
                        "promo_name": raw_promo,
                        "upload_date": str(datetime.date.today()),
                        "data": df_final.to_dict(orient='records')
                    })
                    st.balloons()
                    st.success(f"✅ [{raw_partner}] {raw_promo} 데이터가 성공적으로 저장되었습니다!")
                    
            except Exception as e:
                st.error(f"엑셀 인식 오류: {e}. Q3, R3 셀 위치를 확인해주세요.")

if __name__ == "__main__":
    main()
