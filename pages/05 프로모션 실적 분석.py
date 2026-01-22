import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from firebase_admin import firestore
import datetime

# Firestore 클라이언트 초기화 (기존 설정이 되어 있다고 가정)
try:
    db = firestore.client()
except Exception as e:
    st.error(f"Firestore 연결 오류: {e}")

# --- 1. 데이터 처리 및 심화 지표 생성 함수 ---
def prepare_df(raw_data):
    """Firestore에서 가져온 원본 데이터를 모든 분석 지표가 포함된 상태로 가공합니다."""
    if not raw_data:
        return pd.DataFrame()
        
    df = pd.DataFrame(raw_data)
    
    # 날짜 데이터 변환
    df['입실일자'] = pd.to_datetime(df['입실일자'], errors='coerce')
    df['예약일자'] = pd.to_datetime(df['예약일자'], errors='coerce')
    df['퇴실일자'] = pd.to_datetime(df['퇴실일자'], errors='coerce')
    
    # 수치 데이터 변환 및 결측치 처리
    for col in ['객실료', '총금액', '박수', '서비스료']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
    
    # 요일 데이터 생성 (DOW 분석용)
    dow_map = {
        'Monday': '01.월', 'Tuesday': '02.화', 'Wednesday': '03.수', 
        'Thursday': '04.목', 'Friday': '05.금', 'Saturday': '06.토', 'Sunday': '07.일'
    }
    df['요일'] = df['입실일자'].dt.day_name().map(dow_map)
    df['주말여부'] = df['입실일자'].dt.dayofweek >= 4 # 금, 토, 일
    
    # 리드타임 및 구간 분석
    df['리드타임'] = (df['입실일자'] - df['예약일자']).dt.days
    lt_bins = [-999, 0, 3, 7, 14, 30, 999]
    lt_labels = ['당일', '1-3일전', '4-7일전', '8-14일전', '15-30일전', '30일+']
    df['LT구간'] = pd.cut(df['리드타임'], bins=lt_bins, labels=lt_labels)
    
    # 상품 구분 (조식 포함 여부) - 서비스코드 기준
    df['상품구분'] = df['서비스코드'].apply(lambda x: '🍳 조식포함' if 'BF' in str(x) else '🏨 룸온리')
    
    # 서비스코드 리스트화 (부대수익 분석용)
    df['서비스목록'] = df['서비스코드'].fillna('').str.split(',')
    
    # 지표 계산 (ADR, LOS 등)
    df['ADR_객실'] = df.apply(lambda x: x['객실료'] / x['박수'] if x['박수'] > 0 else 0, axis=1)
    df['입실주차'] = df['입실일자'].dt.isocalendar().week
    
    return df.dropna(subset=['입실일자'])

def get_all_promotions():
    """Firestore에서 저장된 프로모션 리스트를 가져옵니다."""
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

# --- 2. 메인 앱 화면 ---
def main():
    st.set_page_config(page_title="엠버 프로모션 분석 엔진", layout="wide")
    st.title("🚀 엠버 프로모션 성과 분석 & 전략 대시보드")

    tab1, tab2 = st.tabs(["📊 성과 분석 대시보드", "📤 데이터 업로드 및 저장"])

    # --- TAB 1: 분석 대시보드 ---
    with tab1:
        all_promos = get_all_promotions()
        
        if not all_promos:
            st.warning("데이터가 없습니다. 업로드 탭에서 엑셀 파일을 먼저 등록해주세요.")
        else:
            # [사이드바 필터 구성]
            st.sidebar.header("🔍 분석 대상 설정")
            target_promo = st.sidebar.selectbox("기준 프로모션", all_promos, format_func=lambda x: x['display'], key="main_sel")
            
            compare_on = st.sidebar.checkbox("과거/타 프로모션 비교 활성화")
            compare_promo = None
            if compare_on:
                compare_promo = st.sidebar.selectbox("비교 대상 선택", all_promos, format_func=lambda x: x['display'], key="comp_sel")

            # 데이터 가공
            df_main = prepare_df(target_promo['data'])
            
            # [KPI 지표 계산 및 출력]
            def calc_kpis(df):
                trev = df['총금액'].sum()
                rrev = df['객실료'].sum()
                rn = df['박수'].sum()
                adr = rrev / rn if rn > 0 else 0
                los = df['박수'].mean() if not df.empty else 0
                return trev, rrev, rn, adr, los

            m_trev, m_rrev, m_rn, m_adr, m_los = calc_kpis(df_main)
            
            st.subheader(f"📍 [{target_promo['partner']}] {target_promo['promo_name']} 실적 요약")
            k1, k2, k3, k4, k5 = st.columns(5)
            
            if compare_on and compare_promo:
                df_comp = prepare_df(compare_promo['data'])
                c_trev, c_rrev, c_rn, c_adr, c_los = calc_kpis(df_comp)
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

            # [그래프 섹션 1: 요일별 성적 & 예약 곡선]
            col1, col2 = st.columns(2)
            with col1:
                st.subheader("📅 요일별 매출 및 ADR (DOW)")
                dow_df = df_main.groupby('요일').agg({'총금액':'sum', 'ADR_객실':'mean'}).reset_index()
                fig_dow = px.bar(dow_df, x='요일', y='총금액', color='ADR_객실', 
                                 title="요일별 매출 (색상: ADR)", color_continuous_scale='RdYlGn')
                st.plotly_chart(fig_dow, use_container_width=True)
            
            with col2:
                st.subheader("📈 누적 예약 생산 곡선 (Booking Pace)")
                pace_df = df_main.sort_values('예약일자')
                pace_df['누적_RN'] = pace_df['박수'].cumsum()
                fig_pace = px.line(pace_df, x='예약일자', y='누적_RN', title="프로모션 오픈 후 예약 집계 추이")
                st.plotly_chart(fig_pace, use_container_width=True)

            st.divider()

            # [그래프 섹션 2: 히트맵 & 리드타임]
            col3, col4 = st.columns(2)
            with col3:
                st.subheader("🔥 투숙일 집중도 히트맵")
                heat_data = df_main.groupby(['입실주차', '요일']).size().unstack(fill_value=0)
                # 요일 컬럼 정렬 (존재하는 요일만)
                valid_dow = [c for c in ['01.월', '02.화', '03.수', '04.목', '05.금', '06.토', '07.일'] if c in heat_data.columns]
                heat_data = heat_data.reindex(columns=valid_dow)
                fig_heat = px.imshow(heat_data, text_auto=True, color_continuous_scale="YlOrRd", title="주차별/요일별 투숙 분포")
                st.plotly_chart(fig_heat, use_container_width=True)
                
            with col4:
                st.subheader("⏱️ 예약 리드타임 분포")
                lt_order = ['당일', '1-3일전', '4-7일전', '8-14일전', '15-30일전', '30일+']
                lt_sum = df_main['LT구간'].value_counts().reindex(lt_order).reset_index()
                fig_lt = px.bar(lt_sum, x='LT구간', y='count', color='count', title="예약 시점 비중")
                st.plotly_chart(fig_lt, use_container_width=True)

            st.divider()

            # [그래프 섹션 3: 국적 / 상품 / 객실타입]
            d1, d2, d3 = st.columns(3)
            with d1:
                st.subheader("🌍 국적 비중")
                st.plotly_chart(px.pie(df_main, names='국적', hole=0.5), use_container_width=True)
            with d2:
                st.subheader("🍳 상품군 판매 비중 (조식여부)")
                st.plotly_chart(px.pie(df_main, names='상품구분', color_discrete_sequence=px.colors.qualitative.Bold), use_container_width=True)
            with d3:
                st.subheader("🏨 객실 타입별 실적")
                room_perf = df_main.groupby('객실타입').agg({'총금액':'sum', '박수':'sum', 'ADR_객실':'mean'}).reset_index()
                room_perf.columns = ['객실타입', '매출액', '룸나잇', 'ADR']
                st.dataframe(room_perf.style.format({'매출액': '{:,.0f}', 'ADR': '{:,.0f}'}))

            # [그래프 섹션 4: 부대시설 분석]
            st.divider()
            st.subheader("🍱 부대시설 서비스 코드 분석 (Ancillary Revenue)")
            all_svcs = []
            for s_list in df_main['서비스목록']:
                all_svcs.extend([x.strip() for x in s_list if x.strip() != ''])
            if all_svcs:
                svc_df = pd.Series(all_svcs).value_counts().reset_index()
                svc_df.columns = ['서비스명', '건수']
                fig_svc = px.bar(svc_df, x='서비스명', y='건수', color='건수', title="가장 많이 포함된 추가 서비스")
                st.plotly_chart(fig_svc, use_container_width=True)

    # --- TAB 2: 데이터 업로드 및 저장 ---
    with tab2:
        st.header("📤 새로운 프로모션 데이터 등록")
        st.write("엑셀의 **Q3(거래처), R3(요금타입)** 셀 정보를 읽어 자동으로 저장합니다.")
        
        uploaded_file = st.file_uploader("PMS 엑셀 파일을 업로드하세요", type=['xlsx'])
        
        if uploaded_file:
            # Q3, R3 추출 (Excel 3행은 index 2, Q열은 index 16, R열은 index 17)
            df_info = pd.read_excel(uploaded_file, header=None, nrows=3)
            
            try:
                # 3행(index 2)에서 Q, R열 정보 추출
                val_partner = str(df_info.iloc[2, 16]).split('[')[0].strip()
                val_promo = str(df_info.iloc[2, 17]).strip()
                
                st.info(f"📂 파일 감지 - 거래처: **{val_partner}** / 프로모션: **{val_promo}**")
                
                # 데이터 테이블 로드 (3행부터 제목줄)
                df_load = pd.read_excel(uploaded_file, header=2)
                df_load.columns = [str(c).strip() for c in df_load.columns]
                
                if st.button("🔥 이 프로모션 데이터를 Firestore에 저장하기"):
                    # 빈 데이터 제외
                    df_final = df_load.dropna(subset=['입실일자', '객실료'])
                    
                    doc_id = f"{val_partner}_{val_promo}_{datetime.date.today()}"
                    db.collection("promotions").document(doc_id).set({
                        "partner": val_partner,
                        "promo_name": val_promo,
                        "upload_date": str(datetime.date.today()),
                        "data": df_final.to_dict(orient='records')
                    })
                    st.balloons()
                    st.success(f"✅ [{val_partner}] {val_promo} 데이터가 저장되었습니다!")
                    
            except Exception as e:
                st.error(f"데이터 파싱 중 오류가 발생했습니다: {e}")

if __name__ == "__main__":
    main()
