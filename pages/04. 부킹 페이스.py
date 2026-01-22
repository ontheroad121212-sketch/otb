import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore
import time # 시간 지연을 위해 추가

# -----------------------------------------------------------------------------
# 1. Firebase 접속 설정
# -----------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Hotel Strategy Dashboard", page_icon="🏨")

@st.cache_resource
def init_firebase():
    if not firebase_admin._apps:
        try:
            # Streamlit Cloud 배포용
            key_dict = st.secrets["firebase"]
            cred = credentials.Certificate(key_dict)
            firebase_admin.initialize_app(cred)
        except:
            # 로컬 테스트용
            try:
                cred = credentials.Certificate("serviceAccountKey.json")
                firebase_admin.initialize_app(cred)
            except:
                st.warning("⚠️ DB 연결 정보를 찾을 수 없습니다.")
                return None
    return firestore.client()

db = init_firebase()

# -----------------------------------------------------------------------------
# 2. 데이터 업로드 함수 (Admin용 - 배치 쓰기)
# -----------------------------------------------------------------------------
def upload_to_firestore(df_new):
    if df_new.empty or db is None: return
    
    df_new = df_new.copy()
    
    # 1. 날짜 및 데이터 정제 (NaT/NaN 제거)
    date_columns = ['입실일자', '예약일자', '퇴실일자', '취소일자', '확인일자']
    for col in date_columns:
        if col in df_new.columns:
            df_new[col] = pd.to_datetime(df_new[col], errors='coerce')

    # NaT/NaN을 None으로 변환하여 Firestore 에러 방지
    df_upload = df_new.where(pd.notnull(df_new), None)
    df_upload['예약번호'] = df_upload['예약번호'].astype(str)

    total = len(df_upload)
    count = 0
    # [수정] 배치 사이즈를 100으로 줄여서 안정성 강화
    batch_size = 100 
    batch = db.batch()
    
    status_bar = st.progress(0)
    status_text = st.empty()
    
    for _, row in df_upload.iterrows():
        doc_id = row['예약번호']
        if not doc_id or doc_id == 'None': continue
        
        doc_ref = db.collection('hotel_bookings').document(doc_id)
        
        # 딕셔너리 정제
        row_dict = row.to_dict()
        final_payload = {k: (None if pd.isna(v) else v) for k, v in row_dict.items()}
        
        batch.set(doc_ref, final_payload, merge=True)
        count += 1
        
        # 배치 커밋 (100개마다)
        if count % batch_size == 0:
            try:
                batch.commit()
                # [수정] 서버 부하 방지를 위해 0.1초 짧은 휴식
                time.sleep(0.1) 
                batch = db.batch()
                
                status_bar.progress(count / total)
                status_text.text(f"🐢 안전 모드로 업데이트 중... ({count}/{total})")
            except Exception as e:
                st.error(f"⚠️ 전송 중 일시적 오류 발생: {e}. 다시 시도합니다.")
                time.sleep(1) # 에러 시 1초 대기 후 다음 배치 시도
            
    # 남은 데이터 최종 전송
    batch.commit()
    status_bar.empty()
    status_text.success(f"✅ {total}건 업데이트 완료! 이제 안심하고 사용하세요.")
# -----------------------------------------------------------------------------
# [⚡수정됨] 데이터 고속 삭제 함수 (Batch Delete)
# -----------------------------------------------------------------------------
def delete_all_data():
    if db is None: return
    
    coll_ref = db.collection('hotel_bookings')
    # [수정] 한 번에 찾는 양을 200개로 줄여서 서버 부담 최소화
    batch_size = 200 
    
    st.info("데이터 삭제를 시작합니다. 잠시만 기다려주세요...")
    
    total_deleted = 0
    while True:
        try:
            # 1. 문서 목록 가져오기 (시간 초과 방지를 위해 아주 작은 단위로)
            docs = list(coll_ref.limit(batch_size).stream())
            
            if not docs:
                break # 더 이상 지울 게 없으면 탈출
            
            # 2. 배치 삭제 실행
            batch = db.batch()
            for doc in docs:
                batch.delete(doc.reference)
            
            batch.commit()
            
            total_deleted += len(docs)
            st.toast(f"현재 {total_deleted}건 삭제 완료...")
            
            # 3. [중요] 서버 휴식 시간
            # 연속적인 삭제 요청으로 서버가 거부하지 않도록 0.2초 휴식
            time.sleep(0.2)
            
        except Exception as e:
            # 에러 발생 시 잠시 쉬었다가 다시 시도 (자동 복구 로직)
            st.warning(f"일시적 통신 지연 발생. 2초 후 다시 시도합니다...")
            time.sleep(2)
            continue
            
    st.success(f"✨ 총 {total_deleted}건의 데이터를 모두 삭제했습니다!")

# -----------------------------------------------------------------------------
# 3. 데이터 조회 함수 (Viewer용)
# -----------------------------------------------------------------------------
@st.cache_data(ttl=600)
def load_from_firestore():
    if db is None: return pd.DataFrame()
    docs = db.collection('hotel_bookings').stream()
    data = [doc.to_dict() for doc in docs]
    
    if not data: return pd.DataFrame()
    
    df = pd.DataFrame(data)
    df['입실일자'] = pd.to_datetime(df['입실일자']).dt.tz_localize(None)
    df['예약일자'] = pd.to_datetime(df['예약일자']).dt.tz_localize(None)
    
    for col in ['총금액', '객실수']:
        if col in df.columns and df[col].dtype == object:
            df[col] = df[col].astype(str).str.replace(',', '').astype(float)
            
    df['LeadTime'] = (df['입실일자'] - df['예약일자']).dt.days
    df['Year'] = df['입실일자'].dt.isocalendar().year.astype(int)
    df['Month'] = df['입실일자'].dt.month.astype(int)
    df['Week'] = df['입실일자'].dt.isocalendar().week.astype(int)
    df['DayOfWeek'] = df['입실일자'].dt.day_name()
    
    return df

# -----------------------------------------------------------------------------
# 4. 사이드바 (Admin)
# -----------------------------------------------------------------------------
with st.sidebar:
    st.title("Admin Console")
    
    # [1] 업로드 섹션
    with st.expander("📤 데이터 DB 업데이트", expanded=True):
        up_files = st.file_uploader("엑셀 파일 업로드", accept_multiple_files=True)
        if up_files and st.button("🔥 DB 업데이트 실행"):
            all_df = []
            for f in up_files:
                try:
                    tmp = pd.read_csv(f, header=2) if f.name.endswith('.csv') else pd.read_excel(f, header=2)
                    if {'입실일자', '예약번호'}.issubset(tmp.columns):
                        all_df.append(tmp)
                except: pass
            
            if all_df:
                final_df = pd.concat(all_df, ignore_index=True)
                upload_to_firestore(final_df)
                st.cache_data.clear()
                st.rerun()

    # [2] 초기화 섹션
    st.divider()
    with st.expander("⚠️ 데이터 초기화 (Danger Zone)", expanded=False):
        st.warning("경고: 모든 데이터가 영구 삭제됩니다.")
        check_text = st.text_input("확인을 위해 '초기화' 라고 입력하세요.")
        
        if st.button("🗑️ 모든 데이터 삭제"):
            if check_text == "초기화":
                with st.spinner("🚀 고속 삭제 모드 가동... 잠시만 기다려주세요."):
                    delete_all_data()
                    st.cache_data.clear()
                    st.success("초기화 완료! 다시 파일을 업로드해주세요.")
                    st.rerun()
            else:
                st.error("'초기화'라고 정확히 입력해야 합니다.")

# -----------------------------------------------------------------------------
# 5. 메인 대시보드
# -----------------------------------------------------------------------------
df = load_from_firestore()

if df.empty:
    st.title("🏨 Hotel Dashboard")
    st.info("현재 데이터가 없습니다. 사이드바에서 파일을 업로드해주세요.")
    st.stop()

# 상태 필터
with st.sidebar:
    st.divider()
    st.markdown("**🚫 필터 설정**")
    all_sts = df['상태'].unique().astype(str)
    cancel_k = ['취소', 'CXL', 'CANCEL', 'NO', 'NOSHOW', 'RC', 'RX']
    def_exc = [s for s in all_sts if any(x in s.upper() for x in cancel_k)]
    exc_sts = st.multiselect("제외할 상태 (취소 등)", options=all_sts, default=def_exc)

df_clean = df[~df['상태'].isin(exc_sts)]

# 상단 정보
st.title("🏨 Hotel Strategy Dashboard")
st.markdown(f"**Data:** {df_clean['입실일자'].min().date()} ~ {df_clean['입실일자'].max().date()} | **Total:** {len(df_clean):,} Bookings")

# 메인 필터
c1, c2 = st.columns([1, 2])
with c1:
    view_mode = st.radio("기간 단위", ["월별", "분기별", "주별", "연간"], horizontal=True)
with c2:
    all_acc = sorted(df_clean['거래처'].unique())
    sel_acc = st.multiselect("거래처 필터", all_acc, placeholder="전체 (All Channels)")

df_view = df_clean[df_clean['거래처'].isin(sel_acc)] if sel_acc else df_clean
st.divider()

# 기간 선택
years = sorted(df_view['Year'].unique(), reverse=True)
if not years: st.stop()

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
    st.warning("해당 기간에 데이터가 없습니다.")
    st.stop()

# 시각화 (5개 탭)
tabs = st.tabs(["💰 매출", "💳 ADR", "⏳ 리드타임", "📅 요일", "🌏 국적/객실", "🔁 고객 로열티 & 재방문 분석"])

with tabs[0]: # Revenue
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

with tabs[1]: # ADR
    st.subheader(f"ADR 추이")
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

with tabs[2]: # Lead Time
    st.subheader("예약 시점 분포")
    bins = [-1, 0, 3, 7, 14, 30, 60, 90, 999]
    labels = ['당일', '1-3일', '4-7일', '8-14일', '15-30일', '31-60일', '61-90일', '90일+']
    t_c, r_c = target_df.copy(), ref_df.copy()
    t_c['Group'] = pd.cut(t_c['LeadTime'], bins=bins, labels=labels)
    r_c['Group'] = pd.cut(r_c['LeadTime'], bins=bins, labels=labels)
    tg = t_c.groupby('Group')['총금액'].sum().reset_index().assign(Type='Target')
    rg = r_c.groupby('Group')['총금액'].sum().reset_index().assign(Type='Ref')
    fig3 = px.bar(pd.concat([tg, rg]), x='Group', y='총금액', color='Type', barmode='group', color_discrete_map={'Target':'#0052cc','Ref':'#bababa'})
    st.plotly_chart(fig3, use_container_width=True)

with tabs[3]: # Day of Week
    st.subheader("요일별 매출")
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    td = target_df.groupby('DayOfWeek')['총금액'].mean().reindex(days).reset_index()
    rd = ref_df.groupby('DayOfWeek')['총금액'].mean().reindex(days).reset_index()
    fig4 = go.Figure()
    fig4.add_trace(go.Scatter(x=td['DayOfWeek'], y=td['총금액'], name='Target', line=dict(color='green', width=3)))
    fig4.add_trace(go.Scatter(x=rd['DayOfWeek'], y=rd['총금액'], name='Ref', line=dict(color='gray', dash='dot')))
    st.plotly_chart(fig4, use_container_width=True)

with tabs[4]: # Demographics
    st.subheader("국적 및 객실 분석")
    c1, c2 = st.columns(2)
    with c1:
        nd = target_df.groupby('국적')['총금액'].sum().reset_index().sort_values('총금액', ascending=False)
        fig5 = px.pie(nd.head(7), values='총금액', names='국적', hole=0.4, title="Target 국적")
        st.plotly_chart(fig5, use_container_width=True)
    with c2:
        rt_t = target_df.groupby('객실타입')['총금액'].sum().reset_index().assign(Type='Target')
        rt_r = ref_df.groupby('객실타입')['총금액'].sum().reset_index().assign(Type='Ref')
        top = rt_t.sort_values('총금액', ascending=False).head(10)['객실타입']
        fig6 = px.bar(pd.concat([rt_t, rt_r])[pd.concat([rt_t, rt_r])['객실타입'].isin(top)], x='객실타입', y='총금액', color='Type', barmode='group')
        st.plotly_chart(fig6, use_container_width=True)

# --- TAB 6: Guest Loyalty (재방문 분석) ---
with tabs[4]: # 기존 탭 뒤에 추가하거나 순서를 조정하세요
    st.subheader("🔁 고객 로열티 & 재방문 분석")
    
    # 1. 고객 식별키 생성 (성함 + 휴대폰 뒷자리 조합)
    # 데이터에 '고객명'과 '휴대폰' 컬럼이 있는 경우 사용
    df_loyalty = target_df.copy()
    df_loyalty['GuestKey'] = df_loyalty['고객명'].astype(str) + "_" + df_loyalty['휴대폰'].astype(str).str[-4:]
    
    # 전체 기간(df_clean) 기준으로 이 고객들이 몇 번이나 왔는지 계산
    guest_counts = df_clean.groupby(['고객명', df_clean['휴대폰'].astype(str).str[-4:]]).size().reset_index(name='TotalVisits')
    guest_counts['GuestKey'] = guest_counts['고객명'].astype(str) + "_" + guest_counts['휴대폰'].astype(str)
    
    # 현재 선택된 기간(target_df)의 고객들에게 '과거 방문 횟수' 매핑
    target_loyalty = pd.merge(df_loyalty, guest_counts[['GuestKey', 'TotalVisits']], on='GuestKey', how='left')
    target_loyalty['GuestType'] = target_loyalty['TotalVisits'].apply(lambda x: '첫 방문 (New)' if x == 1 else '재방문 (Return)')

    col_l1, col_l2 = st.columns(2)
    
    with col_l1:
        st.markdown("**재방문 고객 비중**")
        loyalty_pie = px.pie(target_loyalty, names='GuestType', hole=0.4, 
                             color='GuestType', color_discrete_map={'첫 방문 (New)':'#E5ECF6', '재방문 (Return)':'#0052cc'})
        st.plotly_chart(loyalty_pie, use_container_width=True)

    with col_l2:
        st.markdown("**재방문객은 어디서 예약하는가?**")
        return_guests = target_loyalty[target_loyalty['GuestType'] == '재방문 (Return)']
        if not return_guests.empty:
            chan_loyalty = return_guests.groupby('거래처').size().reset_index(name='Count').sort_values('Count', ascending=False)
            fig_chan = px.bar(chan_loyalty.head(10), x='거래처', y='Count', color='Count', color_continuous_scale='Blues')
            st.plotly_chart(fig_chan, use_container_width=True)
        else:
            st.info("해당 기간에 재방문 고객이 없습니다.")

    st.divider()
    
    col_l3, col_l4 = st.columns(2)
    with col_l3:
        st.markdown("**고객 등급별 매출 기여도**")
        # 방문 횟수별 그룹화 (1회, 2회, 3~5회, 6회 이상)
        def guest_grade(n):
            if n == 1: return "1. 신규고객"
            elif n == 2: return "2. 리피터(2회)"
            elif n >= 3 and n <= 5: return "3. 단골(3-5회)"
            else: return "4. VIP(6회+)"
        
        target_loyalty['Grade'] = target_loyalty['TotalVisits'].apply(guest_grade)
        grade_rev = target_loyalty.groupby('Grade')['총금액'].sum().reset_index()
        fig_grade = px.bar(grade_rev, x='Grade', y='총금액', text_auto='.2s', color='Grade')
        st.plotly_chart(fig_grade, use_container_width=True)

    with col_l4:
        st.markdown("**재방문객 vs 신규객 객단가(ADR) 비교**")
        # 신규객과 재방문객 중 누가 더 비싼 방을 예약하는가?
        adr_comp = target_loyalty.groupby('GuestType').apply(lambda x: x['총금액'].sum() / x['객실수'].sum()).reset_index(name='ADR')
        fig_adr_comp = px.bar(adr_comp, x='GuestType', y='ADR', color='GuestType', text_auto=',.0f')
        st.plotly_chart(fig_adr_comp, use_container_width=True)

# 검증기
st.divider()
with st.expander("🕵️‍♂️ 데이터 검증 (Raw Data)"):
    st.dataframe(target_df.head(100))
