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
    
    # 5. 부대시설 서비스 분석용 리스트화 (Ancillary Revenue)
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
            d['start_date'] = str(d.get('start_date', '미상'))
            d['end_date'] = str(d.get('end_date', '미상'))
            promo_list.append(d)
        return promo_list
    except Exception as e:
        return []

# --- [2. 메인 대시보드 화면 구성] ---
def main():
    st.set_page_config(page_title="엠버 RM 분석 엔진", layout="wide")
    st.title("📊 엠버 프로모션 성과 분석 및 정밀 비교 AI 리포트")

    tab1, tab2 = st.tabs(["📈 정밀 비교 및 AI 리포트", "📤 데이터 업로드"])

    # --- TAB 1: 분석 및 비교 모드 ---
    with tab1:
        all_data = get_all_promotions()
        
        if not all_data:
            st.info("데이터가 없습니다. 업로드 탭에서 엑셀 파일을 먼저 등록해주세요.")
        else:
            # 사이드바 필터: 기준 데이터 vs 비교 데이터
            st.sidebar.header("🔍 분석 대상 설정")
            partners = sorted(list(set([d.get('partner', '알수없음') for d in all_data])))
            
            # 기준 프로모션 선택
            selected_partner = st.sidebar.selectbox("기준 거래처 선택", partners, key="main_partner")
            partner_promos = [d for d in all_data if d.get('partner') == selected_partner]
            partner_promos.sort(key=lambda x: str(x.get('start_date')), reverse=True)
            
            def format_period(d):
                s = d.get('start_date', '미상')
                e = d.get('end_date', '미상')
                return f"📅 {s} ~ {e}"

            target_promo = st.sidebar.selectbox("기준 기간 선택", partner_promos, format_func=format_period, key="main_period")
            
            # 비교 모드 활성화
            st.sidebar.divider()
            compare_on = st.sidebar.checkbox("🔄 비교 분석 모드 활성화", value=True)
            compare_promo = None
            if compare_on:
                c_partner = st.sidebar.selectbox("비교 거래처 선택", partners, key="comp_partner")
                c_partner_promos = [d for d in all_data if d.get('partner') == c_partner]
                c_partner_promos.sort(key=lambda x: str(x.get('start_date')), reverse=True)
                compare_promo = st.sidebar.selectbox("비교 기간 선택", c_partner_promos, format_func=format_period, key="comp_period")

            # 데이터 가공
            df_main = prepare_df(target_promo['data'])
            
            def get_metrics(df):
                trev = df['총금액'].sum(); rrev = df['객실료'].sum(); rn = df['박수'].sum()
                adr = rrev / rn if rn > 0 else 0; los = df['박수'].mean() if not df.empty else 0
                return trev, rrev, rn, adr, los

            m_tr, m_rr, m_rn, m_adr, m_los = get_metrics(df_main)
            
            st.subheader(f"📌 분석 결과: {target_promo['partner']} ({target_promo['start_date']} ~ {target_promo['end_date']})")
            
            # KPI 카드 (Delta 자동 계산)
            k1, k2, k3, k4, k5 = st.columns(5)
            if compare_on and compare_promo:
                df_comp = prepare_df(compare_promo['data'])
                c_tr, c_rr, c_rn, c_adr, c_los = get_metrics(df_comp)
                k1.metric("총 매출", f"{m_tr:,.0f}원", f"{m_tr-c_tr:,.0f}원")
                k2.metric("객실 매출", f"{m_rr:,.0f}원", f"{m_rr-c_rr:,.0f}원")
                k3.metric("RN (박수)", f"{m_rn:,.0f}박", f"{m_rn-c_rn:,.0f}박")
                k4.metric("평균 ADR", f"{m_adr:,.0f}원", f"{m_adr-c_adr:,.0f}원")
                k5.metric("평균 LOS", f"{m_los:.1f}박", f"{m_los-c_los:.1f}박")
            else:
                k1.metric("총 매출", f"{m_tr:,.0f}원"); k2.metric("객실 매출", f"{m_rr:,.0f}원")
                k3.metric("RN (박수)", f"{m_rn:,.0f}박"); k4.metric("평균 ADR", f"{m_adr:,.0f}원"); k5.metric("평균 LOS", f"{m_los:.1f}박")

            st.divider()

            # --- [정밀 비교 섹션 1: Pace & DOW] ---
            col_a, col_b = st.columns(2)
            with col_a:
                st.subheader("📈 예약 생산 속도 비교 (Pace)")
                df_main_p = df_main.sort_values('예약일자'); df_main_p['누적_RN'] = df_main_p['박수'].cumsum(); df_main_p['구분'] = "기준"
                if compare_on and compare_promo:
                    df_comp_p = df_comp.sort_values('예약일자'); df_comp_p['누적_RN'] = df_comp_p['박수'].cumsum(); df_comp_p['구분'] = "비교"
                    combined_p = pd.concat([df_main_p[['예약일자', '누적_RN', '구분']], df_comp_p[['예약일자', '누적_RN', '구분']]])
                    st.plotly_chart(px.line(combined_p, x='예약일자', y='누적_RN', color='구분'), use_container_width=True)
                else:
                    st.plotly_chart(px.line(df_main_p, x='예약일자', y='누적_RN'), use_container_width=True)
            with col_b:
                st.subheader("📅 요일별 ADR 성적 비교 (DOW)")
                dow_main = df_main.groupby('요일')['ADR_객실'].mean().reset_index(); dow_main['구분'] = "기준"
                if compare_on and compare_promo:
                    dow_comp = df_comp.groupby('요일')['ADR_객실'].mean().reset_index(); dow_comp['구분'] = "비교"
                    combined_dow = pd.concat([dow_main, dow_comp])
                    st.plotly_chart(px.bar(combined_dow, x='요일', y='ADR_객실', color='구분', barmode='group'), use_container_width=True)
                else:
                    st.plotly_chart(px.bar(dow_main, x='요일', y='ADR_객실'), use_container_width=True)

            st.divider()

            # --- [정밀 비교 섹션 2: 국적 & 상품군 비중] ---
            col_c, col_d = st.columns(2)
            with col_c:
                st.subheader("🌍 국적별 점유율 비교 (Nationality Mix)")
                nat_main = df_main['국적'].value_counts(normalize=True).reset_index(); nat_main['구분'] = "기준"
                if compare_on and compare_promo:
                    nat_comp = df_comp['국적'].value_counts(normalize=True).reset_index(); nat_comp['구분'] = "비교"
                    combined_nat = pd.concat([nat_main, nat_comp])
                    st.plotly_chart(px.bar(combined_nat, x='proportion', y='국적', color='구분', barmode='group', orientation='h'), use_container_width=True)
                else:
                    st.plotly_chart(px.pie(df_main, names='국적', hole=0.5), use_container_width=True)
            with col_d:
                st.subheader("🍳 상품군 판매 비중 비교 (Meal Plan Mix)")
                prod_main = df_main['상품구분'].value_counts(normalize=True).reset_index(); prod_main['구분'] = "기준"
                if compare_on and compare_promo:
                    prod_comp = df_comp['상품구분'].value_counts(normalize=True).reset_index(); prod_comp['구분'] = "비교"
                    combined_prod = pd.concat([prod_main, prod_comp])
                    st.plotly_chart(px.bar(combined_prod, x='상품구분', y='proportion', color='구분', barmode='group'), use_container_width=True)
                else:
                    st.plotly_chart(px.pie(df_main, names='상품구분'), use_container_width=True)

            st.divider()

            # --- [정밀 비교 섹션 3: 리드타임 & 객실타입] ---
            col_e, col_f = st.columns(2)
            with col_e:
                st.subheader("⏱️ 예약 리드타임 비중 비교")
                lt_main = df_main['LT구간'].value_counts(normalize=True).reset_index(); lt_main['구분'] = "기준"
                if compare_on and compare_promo:
                    lt_comp = df_comp['LT구간'].value_counts(normalize=True).reset_index(); lt_comp['구분'] = "비교"
                    combined_lt = pd.concat([lt_main, lt_comp])
                    st.plotly_chart(px.bar(combined_lt, x='LT구간', y='proportion', color='구분', barmode='group'), use_container_width=True)
                else:
                    st.plotly_chart(px.bar(lt_main, x='LT구간', y='proportion'), use_container_width=True)
            with col_f:
                st.subheader("🏨 객실 타입별 매출 기여도 비교")
                room_main = df_main.groupby('객실타입')['총금액'].sum().reset_index(); room_main['구분'] = "기준"
                if compare_on and compare_promo:
                    room_comp = df_comp.groupby('객실타입')['총금액'].sum().reset_index(); room_comp['구분'] = "비교"
                    combined_room = pd.concat([room_main, room_comp])
                    st.plotly_chart(px.bar(combined_room, x='객실타입', y='총금액', color='구분', barmode='group'), use_container_width=True)
                else:
                    st.plotly_chart(px.bar(room_main, x='객실타입', y='총금액'), use_container_width=True)

            # --- [신규 섹션: AI 지배인 분석 리포트] ---
            st.divider()
            st.subheader("🤖 AI 지배인의 전략 분석 리포트")
            if compare_on and compare_promo:
                diff_tr = m_tr - c_tr; diff_adr = m_adr - c_adr; diff_rn = m_rn - c_rn
                perf_status = "🟢 성과 향상" if diff_tr > 0 else "🔴 보완 필요"
                with st.expander(f"📢 {target_promo['partner']} vs {compare_promo['partner']} 실적 총평", expanded=True):
                    st.markdown(f"""
                    ### **[분석 총평: {perf_status}]**
                    1. **매출 추이:** 기준 데이터가 비교군 대비 매출은 **{diff_tr:,.0f}원** {'상회' if diff_tr > 0 else '하회'} 중입니다.
                    2. **수익성 효율:** 평균 단가는 **{diff_adr:,.0f}원** 차이가 나며, 이는 {'프리미엄 전략이 주효했음' if diff_adr > 0 else '단가 경쟁력을 통한 물량 확보 전략'}으로 분석됩니다.
                    3. **패턴 인사이트:** - **리드타임:** {lt_main.iloc[0]['LT구간']} 비중이 가장 높으며, 비교군 대비 예약 시점이 {'길어져 안정적' if m_adr > c_adr else '짧아져 직전 수요 의존적'}인 패턴을 보입니다.
                        - **국적 변화:** {'국내 고객' if nat_main.iloc[0]['국적'] == 'KOR' else '외국인 고객'} 비중이 {nat_main.iloc[0]['proportion']*100:.1f}%로 가장 큰 기여를 하고 있습니다.
                    4. **RM 제언:** {'단가를 유지하며 수익을 극대화' if diff_adr > 30000 else '단가 조정을 통해 RN 점유율을 추가 확보'}하는 방향을 추천합니다.
                    """)
            else:
                st.info("비교 분석 모드를 활성화하면 AI 지배인의 분석 리포트가 생성됩니다.")

            # --- 상세 예약 패턴 100% 유지 ---
            st.divider()
            st.subheader("📊 상세 예약 패턴 분석 (기준 데이터 중심)")
            d1, d2, d3 = st.columns(3)
            with d1:
                heat_data = df_main.groupby(['입실주차', '요일']).size().unstack(fill_value=0)
                valid_dow = [c for c in ['01.월', '02.화', '03.수', '04.목', '05.금', '06.토', '07.일'] if c in heat_data.columns]
                heat_data = heat_data.reindex(columns=valid_dow)
                st.plotly_chart(px.imshow(heat_data, text_auto=True, color_continuous_scale="YlOrRd", title="투숙 집중도 히트맵"), use_container_width=True)
            with d2:
                st.plotly_chart(px.pie(df_main, names='국적', hole=0.5, title="국적 분포"), use_container_width=True)
            with d3:
                st.plotly_chart(px.pie(df_main, names='상품구분', title="상품군 비중"), use_container_width=True)

            st.divider()
            st.subheader("🍱 부대수익 및 서비스 분석")
            all_svcs = [x.strip() for s in df_main['서비스목록'] for x in s if x.strip() != '']
            if all_svcs:
                svc_df = pd.Series(all_svcs).value_counts().reset_index()
                svc_df.columns = ['서비스명', '건수']
                st.plotly_chart(px.bar(svc_df, x='서비스명', y='건수', color='건수', title="추가 서비스 판매 현황"), use_container_width=True)

            st.divider()
            with st.expander("📄 전체 예약 목록 및 원본 데이터 (Raw Data)", expanded=False):
                st.dataframe(df_main, use_container_width=True)

    # --- TAB 2: 데이터 업로드 (AE열 3행 고정 조준) ---
    with tab2:
        st.header("📤 새로운 프로모션 데이터 등록")
        uploaded_file = st.file_uploader("PMS 엑셀 파일을 업로드하세요", type=['xlsx'])
        if uploaded_file:
            df_load = pd.read_excel(uploaded_file, header=2)
            df_load.columns = [str(c).strip() for c in df_load.columns]
            try:
                df_load['예약일자'] = df_load.iloc[:, 30] # AE열 고정
                val_partner = str(df_load['거래처'].iloc[0]).split('[')[0].strip()
                res_series = pd.to_datetime(df_load['예약일자'], errors='coerce').dropna()
                start_date = str(res_series.min().date()) if not res_series.empty else "미상"
                end_date = str(res_series.max().date()) if not res_series.empty else "미상"
                st.success(f"탐지 거래처: **{val_partner}** | 기간: **{start_date}** ~ **{end_date}**")
                if st.button("🔥 Firestore 저장"):
                    df_final = df_load.dropna(subset=['입실일자', '객실료'])
                    doc_id = f"{val_partner}_{start_date}_{end_date}_{datetime.datetime.now().strftime('%H%M%S')}"
                    db.collection("promotions").document(doc_id).set({"partner": val_partner, "start_date": start_date, "end_date": end_date, "upload_date": str(datetime.date.today()), "data": df_final.to_dict(orient='records')})
                    st.balloons(); st.success("성공적으로 저장되었습니다!")
            except Exception as e: st.error(f"데이터 파싱 오류: {e}")

if __name__ == "__main__":
    main()
