import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from firebase_admin import firestore
import datetime

# Firestore 클라이언트 (이미 설정되어 있다고 가정)
db = firestore.client()

def get_all_promotions():
    """Firestore에서 저장된 모든 프로모션 목록을 가져옵니다."""
    docs = db.collection("promotions").stream()
    promo_list = []
    for doc in docs:
        d = doc.to_dict()
        # 선택창에 보여줄 이름: [거래처] 프로모션명 (업로드일)
        display_name = f"[{d.get('partner')}] {d.get('promo_name')} ({d.get('upload_date', 'Unknown')})"
        promo_list.append({"id": doc.id, "display": display_name, "data": d.get('data')})
    return promo_list

def main():
    st.set_page_config(page_title="엠버 프로모션 엔진", layout="wide")
    st.title("🔥 엠버 프로모션 실적 분석 시스템")

    tab1, tab2 = st.tabs(["📊 성과 분석 대시보드", "📤 데이터 업로드"])

    # --- TAB 2: 데이터 업로드 (파일에서 정보 자동 추출) ---
    with tab2:
        st.header("엑셀 데이터 업로드")
        uploaded_file = st.file_uploader("거래처 엑셀 파일을 올려주세요", type=['xlsx'])
        
        if uploaded_file:
            # 제목줄(3행) 기준으로 읽기
            df = pd.read_excel(uploaded_file, header=2) 
            df.columns = [str(c).strip() for c in df.columns]
            
            try:
                # 첫 행에서 거래처와 요금타입 추출
                val_partner = str(df['거래처'].iloc[0]).split('[')[0].strip()
                val_promo = str(df['요금타입'].iloc[0]).strip()
                st.success(f"📍 파일 인식: **{val_partner}** | **{val_promo}**")
                
                if st.button("🔥 이 데이터를 파이어스토어에 저장"):
                    # 데이터 정제
                    df = df.dropna(subset=['입실일자', '예약일자'])
                    df['객실료'] = pd.to_numeric(df['객실료'], errors='coerce').fillna(0)
                    df['총금액'] = pd.to_numeric(df['총금액'], errors='coerce').fillna(0)
                    df['박수'] = pd.to_numeric(df['박수'], errors='coerce').fillna(1)
                    df['입실일자'] = pd.to_datetime(df['입실일자'])
                    df['예약일자'] = pd.to_datetime(df['예약일자'])
                    
                    doc_id = f"{val_partner}_{val_promo}_{datetime.date.today()}"
                    db.collection("promotions").document(doc_id).set({
                        "partner": val_partner,
                        "promo_name": val_promo,
                        "upload_date": str(datetime.date.today()),
                        "data": df.to_dict(orient='records')
                    })
                    st.balloons()
                    st.success(f"✅ 저장 완료! '성과 분석' 탭에서 확인하세요.")
            except Exception as e:
                st.error(f"오류: {e}")

    # --- TAB 1: 성과 분석 대시보드 (사이드바 선택 기능 복구) ---
    with tab1:
        promo_options = get_all_promotions()
        
        if not promo_options:
            st.warning("데이터가 없습니다. '데이터 업로드' 탭에서 먼저 파일을 올려주세요.")
            return

        # 사이드바 선택창
        st.sidebar.header("🔍 프로모션 선택")
        selected_promo_dict = st.sidebar.selectbox(
            "분석할 프로모션", 
            promo_options, 
            format_func=lambda x: x['display']
        )
        
        compare_on = st.sidebar.checkbox("비교 대상 선택 (YoY 등)")
        compare_promo_dict = None
        if compare_on:
            compare_promo_dict = st.sidebar.selectbox(
                "비교 대상 프로모션", 
                promo_options, 
                format_func=lambda x: x['display']
            )

        # 데이터 변환 함수
        def prepare_df(raw_data):
            df = pd.DataFrame(raw_data)
            df['입실일자'] = pd.to_datetime(df['입실일자'])
            df['예약일자'] = pd.to_datetime(df['예약일자'])
            df['요일'] = df['입실일자'].dt.day_name()
            df['리드타임'] = (df['입실일자'] - df['예약일자']).dt.days
            df['조식포함'] = df['서비스코드'].str.contains('BF', na=False)
            return df

        df_main = prepare_df(selected_promo_dict['data'])
        
        # 1. 상단 지표 (Metrics)
        st.subheader(f"📍 {selected_promo_dict['display']} 상세 분석")
        m1, m2, m3, m4, m5 = st.columns(5)
        
        total_rev = df_main['총금액'].sum()
        room_rev = df_main['객실료'].sum()
        total_rn = df_main['박수'].sum()
        adr_room = room_rev / total_rn if total_rn > 0 else 0
        avg_los = df_main['박수'].mean()

        m1.metric("총 매출", f"{total_rev:,.0f}원")
        m2.metric("객실 매출", f"{room_rev:,.0f}원")
        m3.metric("룸나잇(RN)", f"{total_rn:,.0f}박")
        m4.metric("객실 ADR", f"{adr_room:,.0f}원")
        m5.metric("평균 LOS", f"{avg_los:.1f}박")

        st.divider()

        # 2. 요일별(DOW) 성적 & 예약 곡선
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("📅 요일별 성적 (DOW)")
            dow_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
            dow_df = df_main.groupby('요일').agg({'총금액':'sum', '객실료':'mean'}).reindex(dow_order).reset_index()
            fig_dow = px.bar(dow_df, x='요일', y='총금액', color='객실료', title="요일별 매출 (색상: ADR)")
            st.plotly_chart(fig_dow, use_container_width=True)

        with c2:
            st.subheader("📈 누적 예약 곡선 (Booking Curve)")
            curve_df = df_main.sort_values('예약일자').copy()
            curve_df['cumulative_rn'] = curve_df['박수'].cumsum()
            fig_curve = px.line(curve_df, x='예약일자', y='cumulative_rn', title="프로모션 누적 예약 생산")
            st.plotly_chart(fig_curve, use_container_width=True)

        # 3. 상세 분포 (국적, 조식비중, 객실타입)
        st.divider()
        d1, d2, d3 = st.columns(3)
        with d1:
            st.write("🌍 국적 비중")
            fig_nat = px.pie(df_main, names='국적', hole=0.4)
            st.plotly_chart(fig_nat, use_container_width=True)
        with d2:
            st.write("🍳 조식 포함 비중")
            fig_bf = px.pie(df_main, names='조식포함', title="True: 조식포함 / False: 룸온리")
            st.plotly_chart(fig_bf, use_container_width=True)
        with d3:
            st.write("🏨 객실 타입별 실적")
            room_perf = df_main.groupby('객실타입').agg({'총금액':'sum', '박수':'sum', '객실료':'mean'}).reset_index()
            st.dataframe(room_perf.style.format({'총금액': '{:,.0f}', '객실료': '{:,.0f}'}))

if __name__ == "__main__":
    main()
