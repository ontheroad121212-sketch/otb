import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from firebase_admin import firestore
import datetime

# 1. Firestore 클라이언트 초기화
# 이미 초기화된 경우를 대비해 예외 처리
try:
    db = firestore.client()
except Exception as e:
    st.error(f"Firestore 연결 상태를 확인해주세요: {e}")

# --- [1. 데이터 가공 및 모든 지표 생성 함수] ---
def prepare_df(raw_data):
    """Firestore 원본 데이터를 분석용 풀스펙 데이터로 가공합니다."""
    if not raw_data:
        return pd.DataFrame()
        
    df = pd.DataFrame(raw_data)
    
    # 날짜 데이터 변환 (오류 방지용 coerce)
    df['입실일자'] = pd.to_datetime(df['입실일자'], errors='coerce')
    df['예약일자'] = pd.to_datetime(df['예약일자'], errors='coerce')
    df['퇴실일자'] = pd.to_datetime(df['퇴실일자'], errors='coerce')
    
    # 수치 데이터 변환 및 결측치 처리
    for col in ['객실료', '총금액', '박수', '서비스료']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    
    # 1-1. 요일 및 주말 분석 (DOW)
    dow_map = {
        'Monday': '01.월', 'Tuesday': '02.화', 'Wednesday': '03.수', 
        'Thursday': '04.목', 'Friday': '05.금', 'Saturday': '06.토', 'Sunday': '07.일'
    }
    df['요일'] = df['입실일자'].dt.day_name().map(dow_map)
    df['주말여부'] = df['입실일자'].dt.dayofweek >= 4 # 금, 토, 일 기준
    
    # 1-2. 리드타임 및 구간 분석 (Lead Time Buckets)
    df['리드타임'] = (df['입실일자'] - df['예약일자']).dt.days
    lt_bins = [-999, 0, 3, 7, 14, 30, 999]
    lt_labels = ['당일', '1-3일전', '4-7일전', '8-14일전', '15-30일전', '30일+']
    df['LT구간'] = pd.cut(df['리드타임'], bins=lt_bins, labels=lt_labels)
    
    # 1-3. 상품 구분 (조식 포함 여부) - 서비스코드 기준
    df['상품구분'] = df['서비스코드'].apply(lambda x: '🍳 조식포함' if 'BF' in str(x) else '🏨 룸온리')
    
    # 1-4. ADR 및 히트맵 주차 계산
    df['ADR_객실'] = df.apply(lambda x: x['객실료'] / x['박수'] if x['박수'] > 0 else 0, axis=1)
    df['입실주차'] = df['입실일자'].dt.isocalendar().week
    
    # 1-5. 부대시설 서비스 분석용 리스트화
    df['서비스목록'] = df['서비스코드'].fillna('').str.split(',')
    
    return df.dropna(subset=['입실일자'])

def get_all_promotions():
    """Firestore에서 저장된 모든 프로모션 목록을 불러옵니다."""
    try:
        # 업로드 날짜 기준 최신순 정렬
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
        st.sidebar.error(f"목록 로드 실패: {e}")
        return []

# --- [2. 메인 대시보드 화면 구성] ---
def main():
    st.set_page_config(page_title="엠버 프로모션 분석 엔진", layout="wide")
    st.title("📊 엠버 프로모션 성과 분석 및 전략 대시보드")

    # 탭 구성 - 분석 탭과 업로드 탭 분리
    tab1, tab2 = st.tabs(["📈 성과 분석 대시보드", "📤 데이터 업로드 및 저장"])

    # --- TAB 1: 성과 분석 화면 ---
    with tab1:
        all_promos = get_all_promotions()
        
        if not all_promos:
            st.info("데이터가 없습니다. 업로드 탭에서 엑셀 파일을 먼저 등록해주세요.")
        else:
            # 사이드바 설정 영역
            st.sidebar.header("🔍 분석 대상 설정")
            target_promo = st.sidebar.selectbox("기준 프로모션 선택", all_promos, format_func=lambda x: x['display'], key="main_select")
            
            compare_on = st.sidebar.checkbox("비교 프로모션 활성화 (YoY)")
            compare_promo = None
            if compare_on:
                compare_promo = st.sidebar.selectbox("비교 대상 선택", all_promos, format_func=lambda x: x['display'], key="comp_select")

            # 데이터 가공 실행
            df_main = prepare_df(target_promo['data'])
            
            # KPI 계산 함수
            def get_metrics(df):
                trev = df['총금액'].sum()
                rrev = df['객실료'].sum()
                rn = df['박수'].sum()
                adr = rrev / rn if rn > 0 else 0
                los = df['박수'].mean() if not df.empty else 0
                return trev, rrev, rn, adr, los

            m_trev, m_rrev, m_rn, m_adr, m_los = get_metrics(df_main)
            
            st.subheader(f"📍 [{target_promo['partner']}] {target_promo['promo_name']} 리포트")
            
            # KPI 메트릭 상단 배치
            k1, k2, k3, k4, k5 = st.columns(5)
            
            if compare_on and compare_promo:
                df_comp = prepare_df(compare_promo['data'])
                c_trev, c_rrev, c_rn, c_adr, c_los = get_metrics(df_comp)
                k1.metric("총 매출", f"{m_trev:,.0f}원", f"{m_trev-c_trev:,.0f}원")
                k2.metric("객실 매출", f"{m_rrev:,.0f}원", f"{m_rrev-c_rrev:,.0f}원")
                k3.metric("룸나잇(RN)", f"{m_rn:,.0f}박", f"{m_rn-c_rn:,.0f}박")
                k4.metric("객실 ADR", f"{m_adr:,.0f}원", f"{m_adr-c_adr:,.0f}원")
                k5.metric("평균 LOS", f"{m_los:.1f}박", f"{m_los-c_los:.1f}박")
            else:
                k1.metric("총 매출", f"{m_trev:,.0f}원")
                k2.metric("객실 매출", f"{m_rrev:,.0f}원")
                k3.metric("룸나잇(RN)", f"{m_rn:,.0f}박")
                k4.metric("객실 ADR", f"{m_adr:,.0f}원")
                k5.metric("평균 LOS", f"{m_los:.1f}박")

            st.divider()

            # 그래프 섹션 1: 요일별 성적(DOW) & 예약 곡선
            col1, col2 = st.columns(2)
            with col1:
                st.subheader("📅 요일별 실적 (주중 vs 주말 성과)")
                
                dow_df = df_main.groupby('요일').agg({'총금액':'sum', 'ADR_객실':'mean'}).reset_index()
                fig_dow = px.bar(dow_df, x='요일', y='총금액', color='ADR_객실', 
                                 title="요일별 매출 (색상: ADR)", color_continuous_scale='Portland')
                st.plotly_chart(fig_dow, use_container_width=True)
            
            with col2:
                st.subheader("📈 누적 예약 생산 곡선 (Booking Pace)")
                
                pace_df = df_main.sort_values('예약일자')
                pace_df['누적_RN'] = pace_df['박수'].cumsum()
                fig_pace = px.line(pace_df, x='예약일자', y='누적_RN', title="프로모션 누적 예약 추이")
                st.plotly_chart(fig_pace, use_container_width=True)

            st.divider()

            # 그래프 섹션 2: 집중도 히트맵 & 리드타임 구간
            col3, col4 = st.columns(2)
            with col3:
                st.subheader("🔥 투숙일 집중도 히트맵")
                
                heat_data = df_main.groupby(['입실주차', '요일']).size().unstack(fill_value=0)
                valid_dow = [c for c in ['01.월', '02.화', '03.수', '04.목', '05.금', '06.토', '07.일'] if c in heat_data.columns]
                heat_data = heat_data.reindex(columns=valid_dow)
                fig_heat = px.imshow(heat_data, text_auto=True, color_continuous_scale="YlOrRd", title="투숙 분포 히트맵")
                st.plotly_chart(fig_heat, use_container_width=True)
                
            with col4:
                st.subheader("⏱️ 예약 리드타임 분포")
                
                lt_order = ['당일', '1-3일전', '4-7일전', '8-14일전', '15-30일전', '30일+']
                lt_sum = df_main['LT구간'].value_counts().reindex(lt_order).reset_index()
                fig_lt = px.bar(lt_sum, x='LT구간', y='count', color='count', title="예약 시점 비중")
                st.plotly_chart(fig_lt, use_container_width=True)

            st.divider()

            # 그래프 섹션 3: 국적 / 상품비중 / 객실타입별 실적
            d1, d2, d3 = st.columns(3)
            with d1:
                st.subheader("🌍 국적 비중")
                
                fig_nat = px.pie(df_main, names='국적', hole=0.5, title="예약 국적 분포")
                st.plotly_chart(fig_nat, use_container_width=True)
            with d2:
                st.subheader("🍳 상품군 비중 (조식여부)")
                
                fig_prod = px.pie(df_main, names='상품구분', title="조식 포함 vs 룸온리", 
                                  color_discrete_sequence=px.colors.qualitative.Bold)
                st.plotly_chart(fig_prod, use_container_width=True)
            with d3:
                st.subheader("🏨 객실 타입별 실적")
                room_perf = df_main.groupby('객실타입').agg({'총금액':'sum', '박수':'sum', 'ADR_객실':'mean'}).reset_index()
                room_perf.columns = ['타입', '매출액', 'RN', 'ADR']
                st.dataframe(room_perf.style.format({'매출액': '{:,.0f}', 'ADR': '{:,.0f}'}))

            # 그래프 섹션 4: 부대수익 분석
            st.divider()
            st.subheader("🍱 부대시설 서비스 분석 (Ancillary Revenue)")
            all_svcs = []
            for s_list in df_main['서비스목록']:
                all_svcs.extend([x.strip() for x in s_list if x.strip() != ''])
            if all_svcs:
                svc_df = pd.Series(all_svcs).value_counts().reset_index()
                svc_df.columns = ['서비스명', '건수']
                fig_svc = px.bar(svc_df, x='서비스명', y='건수', color='건수', title="가장 많이 포함된 추가 서비스")
                st.plotly_chart(fig_svc, use_container_width=True)

    # --- TAB 2: 데이터 업로드 화면 ---
    with tab2:
        st.header("📤 새로운 프로모션 데이터 저장")
        st.markdown("엑셀의 **Q3(거래처), R3(요금타입)** 정보를 읽어 자동으로 Firestore에 저장합니다.")
        
        uploaded_file = st.file_uploader("PMS 엑셀 파일을 업로드하세요", type=['xlsx'])
        
        if uploaded_file:
            # 제목줄 위치 확인 (샘플 기반 index 2가 제목줄)
            df_check = pd.read_excel(uploaded_file, header=2)
            df_check.columns = [str(c).strip() for c in df_check.columns]
            
            try:
                # 첫 데이터 행에서 거래처와 요금타입 추출
                val_partner = str(df_check['거래처'].iloc[0]).split('[')[0].strip()
                val_promo = str(df_check['요금타입'].iloc[0]).strip()
                
                st.info(f"📂 인식된 정보: **{val_partner}** / **{val_promo}**")
                
                if st.button("🔥 파이어스토어에 데이터 저장하기"):
                    # 유효한 행만 필터링
                    df_final = df_check.dropna(subset=['입실일자', '객실료'])
                    
                    doc_id = f"{val_partner}_{val_promo}_{datetime.date.today()}"
                    db.collection("promotions").document(doc_id).set({
                        "partner": val_partner,
                        "promo_name": val_promo,
                        "upload_date": str(datetime.date.today()),
                        "data": df_final.to_dict(orient='records')
                    })
                    st.balloons()
                    st.success(f"✅ {val_partner} 데이터가 저장되었습니다!")
                    
            except Exception as e:
                st.error(f"데이터 파싱 오류: {e}")

if __name__ == "__main__":
    main()
