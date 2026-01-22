import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from firebase_admin import firestore
import datetime

# Firestore 클라이언트 초기화 (기존 설정 유지)
# 초기화 코드가 없다면 여기에 추가: 
# if not firebase_admin._apps:
#     cred = credentials.Certificate('your-key.json')
#     firebase_admin.initialize_app(cred)
db = firestore.client()

def get_all_promotions():
    """Firestore에서 저장된 모든 프로모션 목록을 불러옵니다."""
    try:
        docs = db.collection("promotions").stream()
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
        st.error(f"데이터 로드 중 오류: {e}")
        return []

def prepare_df(raw_data):
    """분석에 필요한 파생 지표 및 심화 지표를 계산합니다."""
    df = pd.DataFrame(raw_data)
    
    # 1. 날짜 데이터 변환
    df['입실일자'] = pd.to_datetime(df['입실일자'])
    df['예약일자'] = pd.to_datetime(df['예약일자'])
    
    # 2. 요일 및 주말 구분 (DOW 분석용)
    dow_map = {'Monday': '월', 'Tuesday': '화', 'Wednesday': '수', 'Thursday': '목', 'Friday': '금', 'Saturday': '토', 'Sunday': '일'}
    df['요일'] = df['입실일자'].dt.day_name().map(dow_map)
    df['주말여부'] = df['입실일자'].dt.dayofweek >= 4 # 금, 토, 일 기준
    
    # 3. 리드타임 및 구간화 (Lead Time Buckets)
    df['리드타임'] = (df['입실일자'] - df['예약일자']).dt.days
    bins = [-999, 0, 3, 7, 14, 30, 999]
    labels = ['당일', '1-3일전', '4-7일전', '8-14일전', '15-30일전', '30일+']
    df['LT구간'] = pd.cut(df['리드타임'], bins=bins, labels=labels)
    
    # 4. 서비스코드(부대시설) 분석
    # 서비스코드가 'BF2P,EXBD' 형태일 때 분리하여 리스트화
    df['서비스목록'] = df['서비스코드'].fillna('').str.split(',')
    df['조식포함'] = df['서비스코드'].apply(lambda x: '조식포함' if 'BF' in str(x) else '룸온리')
    
    # 5. 수치형 데이터 강제 변환
    for col in ['객실료', '총금액', '박수']:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        
    # 6. 히트맵용 주차 계산
    df['입실주차'] = df['입실일자'].dt.isocalendar().week
    
    return df

def main():
    st.set_page_config(page_title="엠버 프로모션 분석 엔진", layout="wide")
    st.title("🔥 엠버 프로모션 실적 분석 & 전략 대시보드")

    tab1, tab2 = st.tabs(["📊 성과 분석 및 심화 비교", "📤 데이터 업로드 (Firestore)"])

    # --- TAB 2: 데이터 업로드 (파일 자동 인식) ---
    with tab2:
        st.header("엑셀 데이터 업로드")
        st.info("파일의 3행(Q, R열)에서 거래처와 프로모션명을 자동으로 추출합니다.")
        uploaded_file = st.file_uploader("거래처 엑셀 파일을 드래그하세요", type=['xlsx'])
        
        if uploaded_file:
            # 3행(index 2)을 제목줄로 인식
            df_raw = pd.read_excel(uploaded_file, header=2)
            df_raw.columns = [str(c).strip() for c in df_raw.columns]
            
            try:
                # 첫 행에서 Q, R열 정보 추출
                val_partner = str(df_raw['거래처'].iloc[0]).split('[')[0].strip()
                val_promo = str(df_raw['요금타입'].iloc[0]).strip()
                st.success(f"📍 파일 인식 성공: **거래처 - {val_partner}** | **프로모션 - {val_promo}**")
                
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
                    st.success(f"✅ 데이터가 저장되었습니다. '성과 분석' 탭에서 확인하세요!")
            except Exception as e:
                st.error(f"데이터 파싱 오류: {e}")

    # --- TAB 1: 분석 및 비교 (핵심 기능) ---
    with tab1:
        all_promos = get_all_promotions()
        if not all_promos:
            st.info("데이터가 없습니다. 먼저 업로드를 진행해 주세요.")
            return

        # [사이드바 필터]
        st.sidebar.header("🔍 분석 설정")
        target_promo = st.sidebar.selectbox("기준 프로모션 선택", all_promos, format_func=lambda x: x['display'])
        
        compare_on = st.sidebar.checkbox("과거/타 프로모션과 비교 (YoY)")
        compare_promo = None
        if compare_on:
            compare_promo = st.sidebar.selectbox("비교 대상 선택", all_promos, format_func=lambda x: x['display'])

        df_main = prepare_df(target_promo['data'])

        # 1. 상단 핵심 지표 (KPI Cards)
        st.subheader(f"📍 [{target_promo['partner']}] {target_promo['promo_name']} 성과 요약")
        k1, k2, k3, k4, k5 = st.columns(5)
        
        def get_kpis(df):
            trev = df['총금액'].sum()
            rrev = df['객실료'].sum()
            rn = df['박수'].sum()
            adr = rrev / rn if rn > 0 else 0
            los = df['박수'].mean()
            return trev, rrev, rn, adr, los

        t_rev, r_rev, rn, adr, los = get_kpis(df_main)
        
        if compare_on and compare_promo:
            df_comp = prepare_df(compare_promo['data'])
            ct_rev, cr_rev, crn, cadr, clos = get_kpis(df_comp)
            k1.metric("총 매출", f"{t_rev:,.0f}원", f"{t_rev-ct_rev:,.0f}원")
            k2.metric("객실 매출", f"{r_rev:,.0f}원", f"{r_rev-cr_rev:,.0f}원")
            k3.metric("룸나잇(RN)", f"{rn:,.0f}박", f"{rn-crn:,.0f}박")
            k4.metric("객실 ADR", f"{adr:,.0f}원", f"{adr-cadr:,.0f}원")
            k5.metric("평균 LOS", f"{los:.1f}박", f"{los-clos:.1f}박")
        else:
            k1.metric("총 매출", f"{t_rev:,.0f}원")
            k2.metric("객실 매출", f"{r_rev:,.0f}원")
            k3.metric("룸나잇(RN)", f"{rn:,.0f}박")
            k4.metric("객실 ADR", f"{adr:,.0f}원")
            k5.metric("평균 LOS", f"{los:.1f}박")

        st.divider()

        # 2. 요일별 성적 (DOW) & 예약 곡선 (Booking Curve)
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("📅 요일별 매출 및 ADR (주중/주말 잠식 분석)")
            dow_order = ['월', '화', '수', '목', '금', '토', '일']
            dow_data = df_main.groupby('요일').agg({'총금액':'sum', '객실료':'mean'}).reindex(dow_order).reset_index()
            fig_dow = px.bar(dow_data, x='요일', y='총금액', color='객실료', 
                             title="요일별 매출 (색상은 ADR)",
                             color_continuous_scale='RdYlGn')
            st.plotly_chart(fig_dow, use_container_width=True)
            st.caption("💡 주말(금-일) 매출 비중이 너무 높고 ADR이 낮다면 잠식(Cannibalization)을 의심해야 합니다.")

        with col2:
            st.subheader("📈 누적 예약 곡선 (Booking Pace)")
            curve_df = df_main.sort_values('예약일자')
            curve_df['cum_rn'] = curve_df['박수'].cumsum()
            fig_curve = px.line(curve_df, x='예약일자', y='cum_rn', title="프로모션 오픈 후 예약 생산 속도")
            st.plotly_chart(fig_curve, use_container_width=True)
            st.caption("💡 곡선이 초반에 가파르다면 짧은 플래시 세일이 효과적이고, 완만하다면 장기 노출이 필요합니다.")

        st.divider()

        # 3. 심화 분석: 히트맵 & 리드타임 구간
        col3, col4 = st.columns(2)
        with col3:
            st.subheader("🔥 입실일 기반 예약 집중도 (Heatmap)")
            heatmap_data = df_main.groupby(['입실주차', '요일']).size().unstack(fill_value=0)
            heatmap_data = heatmap_data.reindex(columns=['월', '화', '수', '목', '금', '토', '일'])
            fig_heat = px.imshow(heatmap_data, text_auto=True, color_continuous_scale='YlOrRd',
                                 title="주차별/요일별 실제 투숙 집중도")
            st.plotly_chart(fig_heat, use_container_width=True)
            
        with col4:
            st.subheader("⏱️ 리드타임 구간별 비중 (Lead Time Buckets)")
            lt_dist = df_main['LT구간'].value_counts().reindex(['당일', '1-3일전', '4-7일전', '8-14일전', '15-30일전', '30일+']).reset_index()
            fig_lt = px.bar(lt_dist, x='LT구간', y='count', color='count', title="예약 시점 분포")
            st.plotly_chart(fig_lt, use_container_width=True)

        st.divider()

        # 4. 상세 분포 (국적, 상품비중, 객실타입)
        d1, d2, d3 = st.columns(3)
        with d1:
            st.write("🌍 국적 비중")
            st.plotly_chart(px.pie(df_main, names='국적', hole=0.4), use_container_width=True)
        with d2:
            st.write("🍳 상품별 비중 (룸온리 vs 조식)")
            st.plotly_chart(px.pie(df_main, names='상품구분', color_discrete_sequence=px.colors.qualitative.Pastel), use_container_width=True)
        with d3:
            st.write("🏨 객실 타입별 실적")
            room_type_perf = df_main.groupby('객실타입').agg({'총금액':'sum', '박수':'sum', '객실료':'mean'}).reset_index()
            room_type_perf.columns = ['객실타입', '매출액', '룸나잇', '평균ADR']
            st.dataframe(room_type_perf.style.format({'매출액': '{:,.0f}', '평균ADR': '{:,.0f}'}))

        # 5. 서비스코드(부대시설) 상세 분석
        st.divider()
        st.subheader("🍱 부대시설 및 추가 서비스 포함 현황 (Ancillary)")
        all_services = [item for sublist in df_main['서비스목록'] for item in sublist if item != '']
        if all_services:
            svc_df = pd.Series(all_services).value_counts().reset_index()
            svc_df.columns = ['서비스', '포함건수']
            fig_svc = px.bar(svc_df, x='서비스', y='포함건수', color='포함건수', title="가장 인기 있는 추가 옵션")
            st.plotly_chart(fig_svc, use_container_width=True)

if __name__ == "__main__":
    main()
