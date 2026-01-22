import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from firebase_admin import firestore
import datetime

# 1. Firestore 클라이언트 초기화
try:
    db = firestore.client()
except Exception as e:
    st.error(f"Firestore 연결 오류: {e}")

# --- [1. 데이터 가공 및 모든 지표 생성 함수] ---
def prepare_df(raw_data):
    """Firestore 원본 데이터를 분석용 풀스펙 데이터로 가공합니다."""
    if not raw_data:
        return pd.DataFrame()
    df = pd.DataFrame(raw_data)
    
    # 컬럼명 공백 제거
    df.columns = [str(c).strip() for c in df.columns]
    
    # 날짜 데이터 변환 (오류 방지용 coerce)
    df['입실일자'] = pd.to_datetime(df['입실일자'], errors='coerce')
    df['예약일자'] = pd.to_datetime(df['예약일자'], errors='coerce')
    df['퇴실일자'] = pd.to_datetime(df['퇴실일자'], errors='coerce')
    
    # 수치 데이터 변환 및 결측치 처리
    for col in ['객실료', '총금액', '박수', '서비스료']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    
    # 1. 요일 및 주말 분석 (DOW)
    dow_map = {
        'Monday': '01.월', 'Tuesday': '02.화', 'Wednesday': '03.수', 
        'Thursday': '04.목', 'Friday': '05.금', 'Saturday': '06.토', 'Sunday': '07.일'
    }
    df['요일'] = df['입실일자'].dt.day_name().map(dow_map)
    df['주말여부'] = df['입실일자'].dt.dayofweek >= 4 # 금, 토, 일 기준
    
    # 2. 리드타임 및 구간 분석 (Lead Time Buckets)
    df['리드타임'] = (df['입실일자'] - df['예약일자']).dt.days
    lt_bins = [-999, 0, 3, 7, 14, 30, 999]
    lt_labels = ['당일', '1-3일전', '4-7일전', '8-14일전', '15-30일전', '30일+']
    df['LT구간'] = pd.cut(df['리드타임'], bins=lt_bins, labels=lt_labels)
    
    # 3. 상품 구분 (조식 포함 여부) - 서비스코드 기준
    if '서비스코드' in df.columns:
        df['상품구분'] = df['서비스코드'].apply(lambda x: '🍳 조식포함' if 'BF' in str(x) else '🏨 룸온리')
    else:
        df['상품구분'] = '정보없음'
    
    # 4. ADR 및 히트맵 주차 계산
    df['ADR_객실'] = df.apply(lambda x: x['객실료'] / x['박수'] if x['박수'] > 0 else 0, axis=1)
    df['입실주차'] = df['입실일자'].dt.isocalendar().week
    
    # 5. 부대시설 서비스 분석용 리스트화
    if '서비스코드' in df.columns:
        df['서비스목록'] = df['서비스코드'].fillna('').str.split(',')
    else:
        df['서비스목록'] = [[] for _ in range(len(df))]
    
    return df.dropna(subset=['입실일자'])

def get_all_promotions():
    """Firestore에서 저장된 모든 프로모션 데이터를 가져옵니다."""
    try:
        docs = db.collection("promotions").stream()
        promo_list = []
        for doc in docs:
            d = doc.to_dict()
            # 데이터 로드 시 None 방지
            d['start_date'] = str(d.get('start_date', '미상'))
            d['end_date'] = str(d.get('end_date', '미상'))
            promo_list.append(d)
        return promo_list
    except Exception as e:
        return []

# --- [2. 메인 대시보드 화면 구성] ---
def main():
    st.set_page_config(page_title="엠버 프로모션 분석 엔진", layout="wide")
    st.title("📊 엠버 프로모션 성과 분석 및 전략 대시보드")

    tab1, tab2 = st.tabs(["📈 성과 분석 대시보드", "📤 데이터 업로드 및 저장"])

    # --- TAB 1: 분석 및 비교 모드 ---
    with tab1:
        all_data = get_all_promotions()
        
        if not all_data:
            st.info("데이터가 없습니다. 업로드 탭에서 엑셀 파일을 먼저 등록해주세요.")
        else:
            # 사이드바 필터: 거래처 선택 -> 해당 거래처의 기간 선택
            st.sidebar.header("🔍 분석 대상 설정")
            
            # 1. 거래처 리스트 추출 및 선택
            partners = sorted(list(set([d.get('partner', '알수없음') for d in all_data])))
            selected_partner = st.sidebar.selectbox("거래처 선택", partners, key="main_partner")
            
            # 2. 해당 거래처의 기간 리스트 구성
            partner_promos = [d for d in all_data if d.get('partner') == selected_partner]
            partner_promos.sort(key=lambda x: str(x.get('start_date')), reverse=True)
            
            def format_period(d):
                s = d.get('start_date', '미상')
                e = d.get('end_date', '미상')
                return f"📅 {s} ~ {e}"

            target_promo = st.sidebar.selectbox("분석 기간 선택", partner_promos, format_func=format_period, key="main_period")
            
            # 비교 모드 (거래처와 기간을 별도로 선택)
            compare_on = st.sidebar.checkbox("비교 프로모션 활성화 (YoY)")
            compare_promo = None
            if compare_on:
                c_partner = st.sidebar.selectbox("비교 거래처 선택", partners, key="comp_partner")
                c_partner_promos = [d for d in all_data if d.get('partner') == c_partner]
                c_partner_promos.sort(key=lambda x: str(x.get('start_date')), reverse=True)
                compare_promo = st.sidebar.selectbox("비교 기간 선택", c_partner_promos, format_func=format_period, key="comp_period")

            # 데이터 가공 실행
            df_main = prepare_df(target_promo['data'])
            
            # KPI 계산 로직
            def get_metrics(df):
                trev = df['총금액'].sum()
                rrev = df['객실료'].sum()
                rn = df['박수'].sum()
                adr = rrev / rn if rn > 0 else 0
                los = df['박수'].mean() if not df.empty else 0
                return trev, rrev, rn, adr, los

            m_trev, m_rrev, m_rn, m_adr, m_los = get_metrics(df_main)
            
            st.subheader(f"📍 [{selected_partner}] {format_period(target_promo)} 분석 리포트")
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

            # --- 시각화 섹션 1: 요일별 성적 & 예약 곡선 ---
            col1, col2 = st.columns(2)
            with col1:
                st.subheader("📅 요일별 실적 (DOW)")
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

            # --- 시각화 섹션 2: 히트맵 및 리드타임 ---
            col3, col4 = st.columns(2)
            with col3:
                st.subheader("🔥 투숙 집중도 히트맵")
                heat_data = df_main.groupby(['입실주차', '요일']).size().unstack(fill_value=0)
                valid_dow = [c for c in ['01.월', '02.화', '03.수', '04.목', '05.금', '06.토', '07.일'] if c in heat_data.columns]
                heat_data = heat_data.reindex(columns=valid_dow)
                fig_heat = px.imshow(heat_data, text_auto=True, color_continuous_scale="YlOrRd")
                st.plotly_chart(fig_heat, use_container_width=True)
                
            with col4:
                st.subheader("⏱️ 예약 리드타임 분포")
                lt_order = ['당일', '1-3일전', '4-7일전', '8-14일전', '15-30일전', '30일+']
                lt_sum = df_main['LT구간'].value_counts().reindex(lt_order).reset_index()
                fig_lt = px.bar(lt_sum, x='LT구간', y='count', color='count', title="예약 시점 비중")
                st.plotly_chart(fig_lt, use_container_width=True)

            st.divider()

            # --- 시각화 섹션 3: 국적 / 상품비중 / 객실타입 실적 ---
            d1, d2, d3 = st.columns(3)
            with d1:
                st.subheader("🌍 국적 비중")
                fig_nat = px.pie(df_main, names='국적', hole=0.5, title="국적 분포")
                st.plotly_chart(fig_nat, use_container_width=True)
            with d2:
                st.subheader("🍳 상품군 판매 비중 (조식여부)")
                fig_prod = px.pie(df_main, names='상품구분', title="조식 포함 여부",
                                  color_discrete_sequence=px.colors.qualitative.Pastel)
                st.plotly_chart(fig_prod, use_container_width=True)
            with d3:
                st.subheader("🏨 객실 타입별 실적")
                room_perf = df_main.groupby('객실타입').agg({'총금액':'sum', '박수':'sum', 'ADR_객실':'mean'}).reset_index()
                room_perf.columns = ['타입', '매출액', 'RN', 'ADR']
                st.dataframe(room_perf.style.format({'매출액': '{:,.0f}', 'ADR': '{:,.0f}'}))

            # --- 부대시설 서비스 분석 ---
            st.divider()
            st.subheader("🍱 부대시설 서비스 분석 (Ancillary Revenue)")
            all_svcs = [x.strip() for s in df_main['서비스목록'] for x in s if x.strip() != '']
            if all_svcs:
                svc_df = pd.Series(all_svcs).value_counts().reset_index()
                svc_df.columns = ['서비스명', '건수']
                fig_svc = px.bar(svc_df, x='서비스명', y='건수', color='건수', title="추가 서비스 판매 현황")
                st.plotly_chart(fig_svc, use_container_width=True)

            # --- [하단 원본 데이터 조회 기능] ---
            st.divider()
            with st.expander("📄 전체 예약 목록 및 원본 데이터 (Raw Data)", expanded=False):
                st.write(f"조회된 프로모션의 전체 예약 데이터입니다. (총 {len(df_main)}건)")
                st.dataframe(df_main, use_container_width=True)

    # --- TAB 2: 데이터 업로드 (AE열 3행 고정 조준) ---
    with tab2:
        st.header("📤 새로운 프로모션 데이터 등록")
        st.markdown("**AE열(예약일자)** 정보를 읽어 기간을 자동 생성하여 저장합니다.")
        
        uploaded_file = st.file_uploader("PMS 엑셀 파일을 업로드하세요", type=['xlsx'])
        if uploaded_file:
            # AE열(31번째 열)이 있는 3행(index 2)을 헤더로 읽기
            df_load = pd.read_excel(uploaded_file, header=2)
            df_load.columns = [str(c).strip() for c in df_load.columns]
            
            try:
                # 1. 거래처 추출
                val_partner = str(df_load['거래처'].iloc[0]).split('[')[0].strip()
                
                # 2. 예약일자 기준 기간 자동 계산
                res_dates = pd.to_datetime(df_load['예약일자'], errors='coerce').dropna()
                if not res_dates.empty:
                    start_date = str(res_dates.min().strftime('%Y-%m-%d'))
                    end_date = str(res_dates.max().strftime('%Y-%m-%d'))
                else:
                    start_date = end_date = "날짜파싱불가"
                
                st.info(f"📁 탐지 거래처: **{val_partner}**")
                st.success(f"🗓️ 예약일자 기준 기간: **{start_date}** ~ **{end_date}**")
                
                if st.button("🔥 이 데이터와 기간으로 Firestore 저장"):
                    df_final = df_load.dropna(subset=['입실일자', '객실료'])
                    doc_id = f"{val_partner}_{start_date}_{end_date}_{datetime.datetime.now().strftime('%H%M%S')}"
                    db.collection("promotions").document(doc_id).set({
                        "partner": val_partner,
                        "start_date": start_date,
                        "end_date": end_date,
                        "upload_date": str(datetime.date.today()),
                        "data": df_final.to_dict(orient='records')
                    })
                    st.balloons(); st.success("성공적으로 저장되었습니다!")
            except Exception as e:
                st.error(f"데이터 파싱 오류: {e}")

if __name__ == "__main__":
    main()
