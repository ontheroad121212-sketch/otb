import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore
import time

# -----------------------------------------------------------------------------
# 1. Firebase 접속 (가장 안정적인 방식)
# -----------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Hotel Strategy Dashboard", page_icon="🏨")

# 캐시 없이 우선 접속 시도 (진단을 위해)
def init_firebase_direct():
    if not firebase_admin._apps:
        try:
            # 1순위: Streamlit Secrets
            key_dict = dict(st.secrets["firebase"])
            cred = credentials.Certificate(key_dict)
            firebase_admin.initialize_app(cred)
        except Exception as e:
            try:
                # 2순위: 로컬 파일
                cred = credentials.Certificate("serviceAccountKey.json")
                firebase_admin.initialize_app(cred)
            except:
                return None, str(e)
    return firestore.client(), "연결됨 ✅"

db, db_status = init_firebase_direct()

# -----------------------------------------------------------------------------
# 2. 데이터 업로드/삭제 함수
# -----------------------------------------------------------------------------
def upload_to_firestore(df_new):
    if db is None: return
    df_new = df_new.copy()
    
    # 필수 전처리
    df_new['입실일자'] = pd.to_datetime(df_new['입실일자'], errors='coerce')
    df_new['예약일자'] = pd.to_datetime(df_new['예약일자'], errors='coerce')
    df_new['예약번호'] = df_new['예약번호'].astype(str)
    
    # NaN/NaT 제거 (None으로 변환)
    df_upload = df_new.where(pd.notnull(df_new), None)
    
    total = len(df_upload)
    batch = db.batch()
    count = 0
    
    bar = st.progress(0)
    msg = st.empty()
    
    for _, row in df_upload.iterrows():
        doc_id = row['예약번호']
        if not doc_id or doc_id == 'None': continue
        
        doc_ref = db.collection('hotel_bookings').document(doc_id)
        # 딕셔너리 내부의 모든 불필요한 객체 정제
        payload = {k: (None if pd.isna(v) else v) for k, v in row.to_dict().items()}
        
        batch.set(doc_ref, payload, merge=True)
        count += 1
        
        if count % 200 == 0:
            batch.commit()
            batch = db.batch()
            bar.progress(count / total)
            msg.text(f"⏳ 업로드 중... ({count}/{total})")
            time.sleep(0.1)
            
    batch.commit()
    bar.empty()
    msg.success(f"✅ {total}건 업데이트 완료!")
    st.cache_data.clear() # 조회 캐시 삭제

def delete_all_data():
    if db is None: return
    coll_ref = db.collection('hotel_bookings')
    batch_size = 200
    total_del = 0
    
    while True:
        docs = list(coll_ref.limit(batch_size).stream())
        if not docs: break
        
        batch = db.batch()
        for doc in docs:
            batch.delete(doc.reference)
        batch.commit()
        total_del += len(docs)
        st.toast(f"🗑️ {total_del}건 삭제 중...")
        time.sleep(0.2)
    return total_del

# -----------------------------------------------------------------------------
# 3. 데이터 조회 (에러 방어막 강화)
# -----------------------------------------------------------------------------
@st.cache_data(ttl=300) # 5분 캐시
def load_from_firestore():
    if db is None: return pd.DataFrame()
    try:
        docs = db.collection('hotel_bookings').limit(50000).stream() # 일단 5만건 제한
        data = [doc.to_dict() for doc in docs]
        if not data: return pd.DataFrame()
        
        df = pd.DataFrame(data)
        df['입실일자'] = pd.to_datetime(df['입실일자'], errors='coerce')
        df['예약일자'] = pd.to_datetime(df['예약일자'], errors='coerce')
        df = df.dropna(subset=['입실일자', '예약일자'])
        
        if df.empty: return pd.DataFrame()
        
        df['입실일자'] = df['입실일자'].dt.tz_localize(None)
        df['예약일자'] = df['예약일자'].dt.tz_localize(None)
        df['LeadTime'] = (df['입실일자'] - df['예약일자']).dt.days
        df['Year'] = df['입실일자'].dt.isocalendar().year.fillna(0).astype(int)
        df['Month'] = df['입실일자'].dt.month.fillna(0).astype(int)
        df['Week'] = df['입실일자'].dt.isocalendar().week.fillna(0).astype(int)
        df['DayOfWeek'] = df['입실일자'].dt.day_name()
        return df
    except:
        return pd.DataFrame()

# -----------------------------------------------------------------------------
# 4. 사이드바 (시스템 관리 및 필터)
# -----------------------------------------------------------------------------
# [1] 데이터를 먼저 불러와서 'df'라는 변수를 만듭니다.
df = load_from_firestore()

with st.sidebar:
    st.title("⚙️ 시스템 관리")
    st.write(f"**DB 상태:** {db_status}")
    
    # DB 연결 실패 시 중단
    if db is None:
        st.error("❌ Firebase 연결 실패! Secrets 설정을 확인하세요.")
        st.stop()

    # --- [A] 데이터 업로드 섹션 ---
    with st.expander("📤 데이터 업로드", expanded=True):
        st.info("💡 4만 건 이상 대용량은 1만 건씩 나눠 올리기를 권장합니다.")
        up_files = st.file_uploader("엑셀/CSV 파일 (여러 개 선택 가능)", accept_multiple_files=True)
        
        if up_files:
            if st.button("🚀 DB 업데이트 시작", key="btn_upload"):
                all_df = []
                for f in up_files:
                    try:
                        # 파일 형식에 따른 읽기 (헤더 2번줄 스킵)
                        if f.name.endswith('.csv'):
                            tmp = pd.read_csv(f, header=2)
                        else:
                            tmp = pd.read_excel(f, header=2)
                        all_df.append(tmp)
                    except Exception as e:
                        st.error(f"파일 읽기 실패 ({f.name}): {e}")
                
                if all_df:
                    with st.spinner("데이터 분석 및 클라우드 전송 중..."):
                        combined_upload_df = pd.concat(all_df, ignore_index=True)
                        upload_to_firestore(combined_upload_df)
                        # 업로드 완료 후 캐시 삭제 및 새로고침
                        st.cache_data.clear()
                        st.rerun()

    # --- [B] 데이터 초기화 섹션 ---
    st.divider()
    with st.expander("⚠️ 데이터 초기화"):
        st.warning("경고: 모든 데이터가 파이어베이스에서 영구 삭제됩니다.")
        pw = st.text_input("확인 메시지 ('초기화' 입력)")
        
        if st.button("🗑️ 전체 데이터 삭제", key="btn_delete"):
            if pw == "초기화":
                with st.spinner("🚀 고속 삭제 모드 가동 중..."):
                    try:
                        num = delete_all_data()
                        st.cache_data.clear()
                        st.success(f"총 {num}건 삭제 완료! 이제 다시 업로드 가능합니다.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"삭제 중 오류 발생: {e}")
            else:
                st.error("입력값이 틀렸습니다.")

    # --- [C] 필터 설정 섹션 ---
    st.divider()
    st.markdown("**🚫 필터 설정**")
    
    # df_clean 초기값 설정 (에러 방지)
    df_clean = df.copy()

    # 데이터가 로드되었을 때만 필터 활성화
    if not df.empty:
        # '상태' 컬럼 존재 여부 체크 (KeyError 방지)
        if '상태' in df.columns:
            all_sts = df['상태'].unique().astype(str)
            # 취소 관련 키워드 자동 감지
            cancel_k = ['취소', 'CXL', 'CANCEL', 'NO', 'NOSHOW', 'RC', 'RX']
            def_exc = [s for s in all_sts if any(x in s.upper() for x in cancel_k)]
            
            exc_sts = st.multiselect(
                "제외할 상태 (취소 등)", 
                options=all_sts, 
                default=def_exc,
                help="체크된 상태는 매출 분석에서 제외됩니다."
            )
            # 메인 화면에서 쓸 필터링된 데이터
            df_clean = df[~df['상태'].isin(exc_sts)]
        else:
            st.warning("⚠️ 데이터에 '상태' 컬럼이 없습니다.")
            df_clean = df
    else:
        df_clean = df


# -----------------------------------------------------------------------------
# 5. 메인 화면 출력
# -----------------------------------------------------------------------------

# [A] 데이터가 없을 경우 안내 화면
if df_clean.empty:
    st.title("🏨 Hotel Strategy Dashboard")
    st.info("👋 환영합니다! 아직 데이터가 로드되지 않았습니다.")
    st.markdown("""
    **시작하는 방법:**
    1. 왼쪽 사이드바의 **[📤 데이터 업로드]** 를 클릭하세요.
    2. 호텔 PMS에서 다운받은 엑셀 파일을 선택하세요.
    3. **[🚀 DB 업데이트 시작]** 버튼을 누르면 분석이 시작됩니다.
    """)
    st.stop() # 이후 코드 실행 중단

# [B] 대시보드 메인 화면
st.title("🏨 Hotel Strategy Dashboard")

# 상단 핵심 지표 (KPI)
col_kpi1, col_kpi2, col_kpi3 = st.columns(3)
with col_kpi1:
    st.metric("분석 대상 예약건수", f"{len(df_clean):,} 건")
with col_kpi2:
    min_date = df_clean['입실일자'].min().date() if not df_clean.empty else "-"
    st.metric("데이터 시작일", str(min_date))
with col_kpi3:
    max_date = df_clean['입실일자'].max().date() if not df_clean.empty else "-"
    st.metric("데이터 종료일", str(max_date))

st.caption("※ 모든 분석은 '예약번호' 기준으로 중복이 제거된 최신 데이터를 기반으로 합니다.")

# --- 메인 필터 (기간 및 거래처) ---
c1, c2 = st.columns([1, 2])
with c1:
    view_mode = st.radio("📊 분석 단위", ["월별", "분기별", "주별", "연간"], horizontal=True)
with c2:
    all_acc = sorted(df_clean['거래처'].unique())
    sel_acc = st.multiselect("🏦 거래처 필터", all_acc, placeholder="전체 거래처(All Channels) 보기")

# 필터링 적용
df_view = df_clean[df_clean['거래처'].isin(sel_acc)] if sel_acc else df_clean
st.divider()

# --- 비교 기간 선택 (Target vs Reference) ---
years = sorted(df_view['Year'].unique(), reverse=True)
if not years:
    st.warning("선택한 필터 조건에 맞는 데이터가 없습니다.")
    st.stop()

col1, col2 = st.columns(2)
target_df, ref_df = pd.DataFrame(), pd.DataFrame()
chart_sub = ""
q_map = {"1분기": [1,2,3], "2분기": [4,5,6], "3분기": [7,8,9], "4분기": [10,11,12]}

if view_mode == "월별":
    with col1:
        ty = st.selectbox("Target 연도", years); tm = st.selectbox("Target 월", range(1,13))
    with col2:
        ry = st.selectbox("Ref 연도", years, index=(1 if len(years)>1 else 0))
        rm = st.selectbox("Ref 월", range(1,13), index=tm-1)
    target_df = df_view[(df_view['Year']==ty) & (df_view['Month']==tm)]
    ref_df = df_view[(df_view['Year']==ry) & (df_view['Month']==rm)]
    chart_sub = f"{ty}.{tm} vs {ry}.{rm}"

elif view_mode == "분기별":
    qs = list(q_map.keys())
    with col1:
        ty = st.selectbox("Target 연도", years); tq = st.selectbox("Target 분기", qs)
    with col2:
        ry = st.selectbox("Ref 연도", years, index=(1 if len(years)>1 else 0))
        rq = st.selectbox("Ref 분기", qs, index=qs.index(tq))
    target_df = df_view[(df_view['Year']==ty) & (df_view['Month'].isin(q_map[tq]))]
    ref_df = df_view[(df_view['Year']==ry) & (df_view['Month'].isin(q_map[rq]))]
    chart_sub = f"{ty} {tq} vs {ry} {rq}"

elif view_mode == "주별":
    with col1:
        ty = st.selectbox("Target 연도", years)
        tw = st.selectbox("Target 주차", sorted(df_view[df_view['Year']==ty]['Week'].unique()))
    with col2:
        ry = st.selectbox("Ref 연도", years, index=(1 if len(years)>1 else 0))
        rw = st.selectbox("Ref 주차", range(1,54), index=int(min(tw-1, 52)))
    target_df = df_view[(df_view['Year']==ty) & (df_view['Week']==tw)]
    ref_df = df_view[(df_view['Year']==ry) & (df_view['Week']==rw)]
    chart_sub = f"{ty} {tw}주 vs {ry} {rw}주"
    
else: # 연간
    with col1: ty = st.selectbox("Target 연도", years)
    with col2: ry = st.selectbox("Ref 연도", years, index=(1 if len(years)>1 else 0))
    target_df = df_view[df_view['Year']==ty]
    ref_df = df_view[df_view['Year']==ry]
    chart_sub = f"{ty} 전체 vs {ry} 전체"

if target_df.empty:
    st.warning(f"선택하신 기간({chart_sub})에 해당하는 데이터가 없습니다.")
    st.stop()

# --- 시각화 탭 생성 ---
tabs = st.tabs(["💰 매출", "💳 ADR", "⏳ 리드타임", "📅 요일", "🌏 국적/객실", "🔁 로열티(재방문)"])

# [TAB 1] Revenue
with tabs[0]:
    st.subheader(f"매출 페이스: {chart_sub}")
    def get_pace(d):
        if d.empty: return pd.Series(dtype=float)
        return d.groupby('LeadTime')['총금액'].sum().sort_index(ascending=False).cumsum().sort_index()
    pt, pr = get_pace(target_df), get_pace(ref_df)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=pt.index, y=pt.values, name='Target', line=dict(color='#0052cc', width=3)))
    if not pr.empty: fig.add_trace(go.Scatter(x=pr.index, y=pr.values, name='Ref', line=dict(color='gray', dash='dot')))
    if not pt.empty:
        lp = pt.index.min()
        fig.add_trace(go.Scatter(x=[lp], y=[pt[lp]], mode='markers+text', text=[f"{pt[lp]/10000:,.0f}만"], textposition="top left", marker=dict(color='red', size=8), showlegend=False))
    fig.update_layout(xaxis={'autorange': 'reversed'}, xaxis_title="D-Day", yaxis_title="누적 매출", height=500)
    st.plotly_chart(fig, use_container_width=True)

# [TAB 2] ADR
with tabs[1]:
    st.subheader(f"ADR(객단가) 추이")
    def get_adr(d):
        if d.empty: return pd.Series(dtype=float)
        rev = d.groupby('LeadTime')['총금액'].sum().sort_index(ascending=False).cumsum().sort_index()
        rms = d.groupby('LeadTime')['객실수'].sum().sort_index(ascending=False).cumsum().sort_index()
        return (rev/rms).fillna(0)
    at, ar = get_adr(target_df), get_adr(ref_df)
    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(x=at.index, y=at.values, name='Target ADR', line=dict(color='#ff6b6b', width=3)))
    if not ar.empty: fig2.add_trace(go.Scatter(x=ar.index, y=ar.values, name='Ref ADR', line=dict(color='gray', dash='dot')))
    fig2.update_layout(xaxis={'autorange': 'reversed'}, height=500)
    st.plotly_chart(fig2, use_container_width=True)

# [TAB 3] Lead Time
with tabs[2]:
    st.subheader("예약 리드타임 분포")
    bins = [-1, 0, 3, 7, 14, 30, 60, 90, 999]
    labels = ['당일', '1-3일', '4-7일', '8-14일', '15-30일', '31-60일', '61-90일', '90일+']
    t_c, r_c = target_df.copy(), ref_df.copy()
    t_c['Group'] = pd.cut(t_c['LeadTime'], bins=bins, labels=labels)
    r_c['Group'] = pd.cut(r_c['LeadTime'], bins=bins, labels=labels)
    tg = t_c.groupby('Group')['총금액'].sum().reset_index().assign(Type='Target')
    rg = r_c.groupby('Group')['총금액'].sum().reset_index().assign(Type='Ref')
    fig3 = px.bar(pd.concat([tg, rg]), x='Group', y='총금액', color='Type', barmode='group', color_discrete_map={'Target':'#0052cc','Ref':'#bababa'})
    st.plotly_chart(fig3, use_container_width=True)

# [TAB 4] Day of Week
with tabs[3]:
    st.subheader("요일별 매출 퍼포먼스")
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    td = target_df.groupby('DayOfWeek')['총금액'].mean().reindex(days).reset_index()
    rd = ref_df.groupby('DayOfWeek')['총금액'].mean().reindex(days).reset_index()
    fig4 = go.Figure()
    fig4.add_trace(go.Scatter(x=td['DayOfWeek'], y=td['총금액'], name='Target', line=dict(color='green', width=3)))
    fig4.add_trace(go.Scatter(x=rd['DayOfWeek'], y=rd['총금액'], name='Ref', line=dict(color='gray', dash='dot')))
    st.plotly_chart(fig4, use_container_width=True)

# [TAB 5] Demographics
with tabs[4]:
    st.subheader("국적 및 객실 타입 분석")
    c1, c2 = st.columns(2)
    with c1:
        nd = target_df.groupby('국적')['총금액'].sum().reset_index().sort_values('총금액', ascending=False)
        fig5 = px.pie(nd.head(7), values='총금액', names='국적', hole=0.4, title="Target 국적 TOP 7")
        st.plotly_chart(fig5, use_container_width=True)
    with c2:
        rt_t = target_df.groupby('객실타입')['총금액'].sum().reset_index().assign(Type='Target')
        rt_r = ref_df.groupby('객실타입')['총금액'].sum().reset_index().assign(Type='Ref')
        top = rt_t.sort_values('총금액', ascending=False).head(10)['객실타입']
        fig6 = px.bar(pd.concat([rt_t, rt_r])[pd.concat([rt_t, rt_r])['객실타입'].isin(top)], x='객실타입', y='총금액', color='Type', barmode='group')
        st.plotly_chart(fig6, use_container_width=True)

# [TAB 6] Guest Loyalty (Smart Logic)
with tabs[5]:
    st.header("🔁 재방문 고객 심층 리포트")
    
    # 1. 컬럼명 자동 감지
    name_cols = ['고객명', '예약자', '성함', '고객성함', 'Guest Name', 'Name', '예약자명', '한글성명']
    phone_cols = ['휴대폰', '전화번호', '연락처', 'Mobile', 'Phone', '핸드폰', '휴대전화']
    
    found_name = next((c for c in name_cols if c in df_clean.columns), None)
    found_phone = next((c for c in phone_cols if c in df_clean.columns), None)

    if not found_name:
        st.warning(f"⚠️ '고객명' 컬럼을 찾을 수 없어 심층 분석이 불가능합니다.")
    else:
        # --- [A] 기본 데이터 준비 ---
        df_l = df_clean.copy().sort_values([found_name, '입실일자'])
        
        # 식별키 생성
        if found_phone:
            df_l['GuestKey'] = df_l[found_name].astype(str) + "_" + df_l[found_phone].astype(str).str[-4:]
        else:
            df_l['GuestKey'] = df_l[found_name].astype(str)

        # 재방문 주기(Interval) 계산: 이전 방문일과의 차이
        df_l['PrevVisit'] = df_l.groupby('GuestKey')['입실일자'].shift(1)
        df_l['DaysSinceLastVisit'] = (df_l['입실일자'] - df_l['PrevVisit']).dt.days

        # 현재 선택된 타겟 기간 데이터 추출
        target_keys = target_df[found_name].astype(str) + "_" + target_df[found_phone].astype(str).str[-4:] if found_phone else target_df[found_name].astype(str)
        df_target_loyalty = df_l[df_l['GuestKey'].isin(target_keys)].copy()
        
        # 총 방문횟수 매핑
        guest_counts = df_l.groupby('GuestKey').size().reset_index(name='TotalVisits')
        df_target_loyalty = pd.merge(df_target_loyalty, guest_counts, on='GuestKey', how='left')
        df_target_loyalty['GuestType'] = df_target_loyalty['TotalVisits'].apply(lambda x: '첫 방문' if x <= 1 else '재방문')

        # --- [B] 시각화 시작 ---
        
        # 지표 요약
        m1, m2, m3 = st.columns(3)
        unique_g = df_target_loyalty['GuestKey'].nunique()
        return_g = df_target_loyalty[df_target_loyalty['GuestType'] == '재방문']['GuestKey'].nunique()
        m1.metric("선택 기간 내 총 고객수", f"{unique_g:,}명")
        m2.metric("재방문 고객수", f"{return_g:,}명")
        m3.metric("재방문율", f"{(return_g/unique_g*100) if unique_g > 0 else 0:.1f}%")

        st.divider()

        # INSIGHT 1: 재방문 주기 분석 (얼마 만에 다시 오나?)
        st.subheader("1️⃣ 단골들은 보통 얼마 만에 다시 올까? (방문 주기)")
        revisit_intervals = df_l[df_l['DaysSinceLastVisit'] > 0]['DaysSinceLastVisit']
        if not revisit_intervals.empty:
            avg_interval = revisit_intervals.mean()
            fig_interval = px.histogram(revisit_intervals, x='DaysSinceLastVisit', 
                                         nbins=50, title=f"평균 재방문 주기: {avg_interval:.1f}일",
                                         color_discrete_sequence=['#0052cc'], labels={'x':'방문 간격(일)', 'y':'건수'})
            st.plotly_chart(fig_interval, use_container_width=True)
            st.info(f"💡 단골 손님들은 평균적으로 **약 {avg_interval/30:.1f}개월** 마다 호텔을 다시 찾고 계십니다.")
        else:
            st.info("재방문 주기를 계산할 데이터가 충분하지 않습니다.")

        st.divider()

        # INSIGHT 2: 신규 vs 재방문 수익 기여도 비교
        st.subheader("2️⃣ 재방문객이 돈을 더 많이 쓸까? (수익 기여도)")
        col_rev1, col_rev2 = st.columns(2)
        
        with col_rev1:
            # ADR 비교
            adr_comp = df_target_loyalty.groupby('GuestType').apply(lambda x: x['총금액'].sum() / x['객실수'].sum()).reset_index(name='ADR')
            fig_adr = px.bar(adr_comp, x='GuestType', y='ADR', color='GuestType', text_auto=',.0f', title="객단가(ADR) 비교")
            st.plotly_chart(fig_adr, use_container_width=True)
        
        with col_rev2:
            # 총 매출 비중
            rev_share = df_target_loyalty.groupby('GuestType')['총금액'].sum().reset_index()
            fig_share = px.pie(rev_share, names='GuestType', values='총금액', hole=0.4, title="매출 기여도 비중")
            st.plotly_chart(fig_share, use_container_width=True)

        st.divider()

        # INSIGHT 3: 채널 전이 분석 (OTA에서 직예약으로 전환되나?)
        st.subheader("3️⃣ OTA 손님이 '직예약'으로 전환되고 있나? (채널 전이)")
        
        # 첫 방문 채널 vs 마지막 방문 채널 비교 로직
        first_visit = df_l.groupby('GuestKey').first()['거래처'].reset_index().rename(columns={'거래처':'FirstChannel'})
        last_visit = df_l.groupby('GuestKey').last()['거래처'].reset_index().rename(columns={'거래처':'LastChannel'})
        channel_drift = pd.merge(first_visit, last_visit, on='GuestKey')
        
        # 재방문자만 필터링
        repeater_keys = guest_counts[guest_counts['TotalVisits'] > 1]['GuestKey']
        drift_repeaters = channel_drift[channel_drift['GuestKey'].isin(repeater_keys)]
        
        if not drift_repeaters.empty:
            drift_summary = drift_repeaters.groupby(['FirstChannel', 'LastChannel']).size().reset_index(name='Count')
            # Sankey 차트 또는 Heatmap으로 표현 (여기서는 깔끔한 테이블과 설명)
            success_direct = drift_repeaters[(drift_repeaters['FirstChannel'] != '홈페이지') & (drift_repeaters['LastChannel'] == '홈페이지')].shape[0]
            
            c_drift1, c_drift2 = st.columns([1, 2])
            with c_drift1:
                st.metric("OTA → 직예약 전환 성공", f"{success_direct}건")
                st.write("첫 방문은 타 채널이었으나 마지막은 홈페이지/직예약으로 오신 손님 수입니다.")
            with c_drift2:
                # 간단한 히트맵형 표
                pivot_drift = drift_summary.pivot(index='FirstChannel', columns='LastChannel', values='Count').fillna(0)
                st.write("**채널 전이 매트릭스 (어디서 와서 어디로 가나)**")
                st.dataframe(pivot_drift.style.background_gradient(cmap='Blues'))
        else:
            st.info("채널 전이를 분석할 재방문 데이터가 없습니다.")
# 검증기 (항상 맨 아래)
st.divider()
with st.expander("🕵️‍♂️ 데이터 검증 (Raw Data)"):
    st.dataframe(df_view.head(100))
