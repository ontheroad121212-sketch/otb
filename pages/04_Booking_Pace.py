import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore
import time
import os

# -----------------------------------------------------------------------------
# 1. Firebase 접속 및 초기 설정 (가장 안정적인 방식 유지)
# -----------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Hotel Strategy Dashboard", page_icon="🏨")

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
# 2. 데이터 고속 로딩(Parquet) 및 스냅샷 관리 (신규 추가 로직)
# -----------------------------------------------------------------------------
CACHE_FILE = "local_booking_cache.parquet"

def upload_to_firestore(df_new):
    if db is None: return
    df_new = df_new.copy()
    
    # [스냅샷 추가] 업로드 시점 자동 기록
    upload_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    df_new['Snapshot'] = upload_time
    
    # 필수 전처리
    df_new['입실일자'] = pd.to_datetime(df_new['입실일자'], errors='coerce')
    df_new['예약일자'] = pd.to_datetime(df_new['예약일자'], errors='coerce')
    df_new['예약번호'] = df_new['예약번호'].astype(str)
    
    # NaN/NaT 제거
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
        payload = {k: (None if pd.isna(v) else v) for k, v in row.to_dict().items()}
        
        batch.set(doc_ref, payload, merge=True)
        count += 1
        
        if count % 200 == 0:
            batch.commit()
            batch = db.batch()
            bar.progress(count / total)
            msg.text(f"⏳ 업로드 중... ({count}/{total})")
            time.sleep(0.05)
            
    batch.commit()
    bar.empty()
    msg.success(f"✅ {total}건 업데이트 완료! (버전: {upload_time})")
    
    # 업로드 성공 시 로컬 캐시 삭제하여 새로고침 유도
    if os.path.exists(CACHE_FILE):
        os.remove(CACHE_FILE)
    st.cache_data.clear()

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
        
    if os.path.exists(CACHE_FILE):
        os.remove(CACHE_FILE)
    st.cache_data.clear()
    return total_del

@st.cache_data(ttl=3600)
def load_data_with_snapshot_cache():
    # 1. 로컬 캐시 파일이 있으면 즉시 로드 (광속 로딩)
    if os.path.exists(CACHE_FILE):
        try:
            df = pd.read_parquet(CACHE_FILE)
            return df, "로컬 캐시 (고속)"
        except:
            pass

    # 2. 파일 없으면 Firestore에서 불러오기
    if db is None: return pd.DataFrame(), "연결 안됨"
    try:
        docs = db.collection('hotel_bookings').limit(100000).stream() 
        data = [doc.to_dict() for doc in docs]
        if not data: return pd.DataFrame(), "데이터 없음"
        
        df = pd.DataFrame(data)
        df['입실일자'] = pd.to_datetime(df['입실일자'], errors='coerce')
        df['예약일자'] = pd.to_datetime(df['예약일자'], errors='coerce')
        df = df.dropna(subset=['입실일자', '예약일자'])
        
        if df.empty: return pd.DataFrame(), "데이터 비었음"
        
        df['입실일자'] = df['입실일자'].dt.tz_localize(None)
        df['예약일자'] = df['예약일자'].dt.tz_localize(None)
        df['LeadTime'] = (df['입실일자'] - df['예약일자']).dt.days
        df['Year'] = df['입실일자'].dt.isocalendar().year.fillna(0).astype(int)
        df['Month'] = df['입실일자'].dt.month.fillna(0).astype(int)
        df['Week'] = df['입실일자'].dt.isocalendar().week.fillna(0).astype(int)
        df['DayOfWeek'] = df['입실일자'].dt.day_name()
        
        # Snapshot 컬럼 보정
        if 'Snapshot' not in df.columns:
            df['Snapshot'] = "이전 데이터"
            
        # 3. 로컬 파일로 저장 (다음 로딩부터 빨라짐)
        df.to_parquet(CACHE_FILE)
        return df, "Firestore (실시간)"
    except:
        return pd.DataFrame(), "조회 에러"

def load_historical_patterns():
    db = firestore.client()
    # 4만 건의 예약 데이터를 가져옴
    docs = db.collection("reservations").stream() 
    
    data = []
    for doc in docs:
        data.append(doc.to_dict())
    
    if not data:
        return {}, 0, pd.DataFrame()
        
    df = pd.DataFrame(data)
    
    # [수정 포인트 1] 실제 존재하는 컬럼명 찾기 (대소문자/언더바 대응)
    cols = df.columns.tolist()
    
    # 체크인 날짜 필드 찾기
    ci_col = next((c for c in cols if c.lower() in ['check_in', 'checkin', 'arrivaldate']), None)
    # 예약 생성 날짜 필드 찾기
    bd_col = next((c for c in cols if c.lower() in ['booking_date', 'bookingdate', 'created_at']), None)
    # 고객 식별 필드 찾기
    cust_col = next((c for c in cols if c.lower() in ['customer_id', 'phone', 'email', 'guestname']), None)

    # 필드가 하나라도 없으면 에러 대신 기본값 반환
    if not ci_col or not bd_col:
        st.error(f"⚠️ 필수 필드를 찾을 수 없습니다. (현재 필드: {cols})")
        return {}, 0, df

    # [수정 포인트 2] 찾은 컬럼명으로 데이터 타입 변환
    df['check_in'] = pd.to_datetime(df[ci_col], errors='coerce')
    df['booking_date'] = pd.to_datetime(df[bd_col], errors='coerce')
    
    # 결측치 제거
    df = df.dropna(subset=['check_in', 'booking_date'])

    # [3] 요일별 예약 발생 패턴 (요일 지수)
    df['dow'] = df['booking_date'].dt.dayofweek
    dow_counts = df['dow'].value_counts(normalize=True) * 7
    
    # [4] 재방문율 통계
    repeat_rate = 0
    if cust_col:
        repeat_rate = (df[cust_col].value_counts() > 1).mean() * 100
    
    return dow_counts.to_dict(), repeat_rate, df

# -----------------------------------------------------------------------------
# 3. 사이드바 (시스템 관리 및 필터)
# -----------------------------------------------------------------------------
# 데이터를 먼저 불러옵니다.
df_raw, load_source = load_data_with_snapshot_cache()

with st.sidebar:
    st.title("⚙️ 시스템 관리")
    st.write(f"**DB 상태:** {db_status}")
    st.caption(f"로드 소스: {load_source}")
    
    if db is None:
        st.error("❌ Firebase 연결 실패! Secrets 설정을 확인하세요.")
        st.stop()

    with st.expander("📤 데이터 업로드", expanded=True):
        st.info("💡 4만 건 이상 대용량은 1만 건씩 나눠 올리기를 권장합니다.")
        up_files = st.file_uploader("엑셀/CSV 파일 (여러 개 선택 가능)", accept_multiple_files=True)
        
        if up_files:
            if st.button("🚀 DB 업데이트 시작", key="btn_upload"):
                all_df = []
                for f in up_files:
                    try:
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
                        st.rerun()

    st.divider()
    with st.expander("⚠️ 데이터 초기화"):
        st.warning("경고: 모든 데이터가 파이어베이스에서 영구 삭제됩니다.")
        pw = st.text_input("확인 메시지 ('초기화' 입력)")
        
        if st.button("🗑️ 전체 데이터 삭제", key="btn_delete"):
            if pw == "초기화":
                with st.spinner("🚀 고속 삭제 모드 가동 중..."):
                    try:
                        num = delete_all_data()
                        st.success(f"총 {num}건 삭제 완료!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"삭제 중 오류 발생: {e}")
            else:
                st.error("입력값이 틀렸습니다.")

    st.divider()
    # [스냅샷 선택 필터]
    st.markdown("**🔍 데이터 버전(Snapshot) 선택**")
    if not df_raw.empty:
        snapshot_options = sorted(df_raw['Snapshot'].unique(), reverse=True)
        selected_snapshot = st.selectbox("조회할 업로드 시점 선택", snapshot_options)
        df = df_raw[df_raw['Snapshot'] == selected_snapshot]
    else:
        df = df_raw

    st.markdown("**🚫 필터 설정**")
    df_clean = df.copy()

    if not df.empty:
        if '상태' in df.columns:
            all_sts = df['상태'].unique().astype(str)
            cancel_k = ['취소', 'CXL', 'CANCEL', 'NO', 'NOSHOW', 'RC', 'RX']
            def_exc = [s for s in all_sts if any(x in s.upper() for x in cancel_k)]
            
            exc_sts = st.multiselect(
                "제외할 상태 (취소 등)", 
                options=all_sts, 
                default=def_exc,
                help="체크된 상태는 매출 분석에서 제외됩니다."
            )
            df_clean = df[~df['상태'].isin(exc_sts)]
        else:
            st.warning("⚠️ 데이터에 '상태' 컬럼이 없습니다.")
            df_clean = df
    else:
        df_clean = df

# -----------------------------------------------------------------------------
# 4. 메인 화면 출력 (기존 모든 분석 기능 100% 무삭제 유지)
# -----------------------------------------------------------------------------

if df_clean.empty:
    st.title("🏨 Hotel Strategy Dashboard")
    st.info("👋 환영합니다! 아직 데이터가 로드되지 않았습니다. 사이드바에서 업로드해주세요.")
    st.stop()

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

st.caption(f"※ 데이터 버전: {selected_snapshot if not df_raw.empty else 'N/A'} | 예약번호 기준 중복 제거됨")

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
years_list = sorted(df_view['Year'].unique(), reverse=True)
year_options = ["전체"] + [str(y) for y in years_list]

col1, col2 = st.columns(2)
target_df, ref_df = pd.DataFrame(), pd.DataFrame()
chart_sub = ""
q_map = {"1분기": [1,2,3], "2분기": [4,5,6], "3분기": [7,8,9], "4분기": [10,11,12]}

if view_mode == "월별":
    with col1:
        ty_sel = st.selectbox("Target 연도", year_options, index=1 if len(year_options)>1 else 0)
        tm = st.selectbox("Target 월", range(1,13))
    with col2:
        ry_sel = st.selectbox("Ref 연도", year_options, index=1 if len(year_options)>1 else 0)
        rm = st.selectbox("Ref 월", range(1,13), index=tm-1)
    
    if ty_sel == "전체":
        target_df = df_view[df_view['Month'] == tm]
        t_label = f"전체 연도 {tm}월"
    else:
        target_df = df_view[(df_view['Year'] == int(ty_sel)) & (df_view['Month'] == tm)]
        t_label = f"{ty_sel}.{tm}"
    
    if ry_sel == "전체":
        ref_df = df_view[df_view['Month'] == rm]
        r_label = f"전체 연도 {rm}월"
    else:
        ref_df = df_view[(df_view['Year'] == int(ry_sel)) & (df_view['Month'] == rm)]
        r_label = f"{ry_sel}.{rm}"
    chart_sub = f"{t_label} vs {r_label}"

elif view_mode == "분기별":
    qs = list(q_map.keys())
    with col1:
        ty_sel = st.selectbox("Target 연도", year_options, index=1 if len(year_options)>1 else 0)
        tq = st.selectbox("Target 분기", qs)
    with col2:
        ry_sel = st.selectbox("Ref 연도", year_options, index=1 if len(year_options)>1 else 0)
        rq = st.selectbox("Ref 분기", qs, index=qs.index(tq))
    
    if ty_sel == "전체":
        target_df = df_view[df_view['Month'].isin(q_map[tq])]
        t_label = f"전체 연도 {tq}"
    else:
        target_df = df_view[(df_view['Year'] == int(ty_sel)) & (df_view['Month'].isin(q_map[tq]))]
        t_label = f"{ty_sel} {tq}"

    if ry_sel == "전체":
        ref_df = df_view[df_view['Month'].isin(q_map[rq])]
        r_label = f"전체 연도 {rq}"
    else:
        ref_df = df_view[(df_view['Year'] == int(ry_sel)) & (df_view['Month'].isin(q_map[rq]))]
        r_label = f"{ry_sel} {rq}"
    chart_sub = f"{t_label} vs {r_label}"

elif view_mode == "주별":
    with col1:
        ty_sel = st.selectbox("Target 연도", year_options, index=1 if len(year_options)>1 else 0)
        avail_weeks = sorted(df_view['Week'].unique()) if ty_sel == "전체" else sorted(df_view[df_view['Year']==int(ty_sel)]['Week'].unique())
        tw = st.selectbox("Target 주차", avail_weeks if avail_weeks else [1])
    with col2:
        ry_sel = st.selectbox("Ref 연도", year_options, index=1 if len(year_options)>1 else 0)
        rw = st.selectbox("Ref 주차", range(1,54), index=int(min(tw-1, 52)))
    
    if ty_sel == "전체":
        target_df = df_view[df_view['Week'] == tw]
        t_label = f"전체 연도 {tw}주"
    else:
        target_df = df_view[(df_view['Year'] == int(ty_sel)) & (df_view['Week'] == tw)]
        t_label = f"{ty_sel} {tw}주"

    if ry_sel == "전체":
        ref_df = df_view[df_view['Week'] == rw]
        r_label = f"전체 연도 {rw}주"
    else:
        ref_df = df_view[(df_view['Year'] == int(ry_sel)) & (df_view['Week'] == rw)]
        r_label = f"{ry_sel} {rw}주"
    chart_sub = f"{t_label} vs {r_label}"
    
else: # 연간
    with col1:
        ty_sel = st.selectbox("Target 연도", year_options, index=0)
    with col2:
        ry_sel = st.selectbox("Ref 연도", year_options, index=1 if len(year_options)>1 else 0)
    
    if ty_sel == "전체":
        target_df = df_view
        t_label = "전체 기간"
    else:
        target_df = df_view[df_view['Year'] == int(ty_sel)]
        t_label = f"{ty_sel}년"

    if ry_sel == "전체":
        ref_df = df_view
        r_label = "전체 기간"
    else:
        ref_df = df_view[df_view['Year'] == int(ry_sel)]
        r_label = f"{ry_sel}년"
    chart_sub = f"{t_label} vs {r_label}"

if target_df.empty:
    st.warning(f"⚠️ 선택하신 기간({chart_sub})에 해당하는 데이터가 없습니다.")
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
    c_demo1, c_demo2 = st.columns(2)
    with c_demo1:
        nd = target_df.groupby('국적')['총금액'].sum().reset_index().sort_values('총금액', ascending=False)
        fig5 = px.pie(nd.head(7), values='총금액', names='국적', hole=0.4, title="Target 국적 TOP 7")
        st.plotly_chart(fig5, use_container_width=True)
    with c_demo2:
        rt_t = target_df.groupby('객실타입')['총금액'].sum().reset_index().assign(Type='Target')
        rt_r = ref_df.groupby('객실타입')['총금액'].sum().reset_index().assign(Type='Ref')
        top = rt_t.sort_values('총금액', ascending=False).head(10)['객실타입']
        fig6 = px.bar(pd.concat([rt_t, rt_r])[pd.concat([rt_t, rt_r])['객실타입'].isin(top)], x='객실타입', y='총금액', color='Type', barmode='group')
        st.plotly_chart(fig6, use_container_width=True)

# [TAB 6] Guest Loyalty (Smart Logic & N차 분석 통합)
with tabs[5]:
    st.header("🔁 고객 로열티 심층 리포트 (VIP & N차 분석)")
    
    # [1] 컬럼 자동 감지
    name_cols = ['고객명', '예약자', '성함', '고객성함', 'Guest Name', 'Name', '예약자명', '한글성명', '고객']
    phone_cols = ['휴대폰', '전화번호', '연락처', 'Mobile', 'Phone', '핸드폰', '휴대전화']
    
    f_name = next((c for c in name_cols if c in df_clean.columns), None)
    f_phone = next((c for c in phone_cols if c in df_clean.columns), None)

    if not f_name:
        st.warning(f"⚠️ '고객명' 컬럼을 찾을 수 없어 분석을 시작할 수 없습니다.")
    else:
        # --- [2] 데이터 전처리 (직원 제외 로직 포함) ---
        exclude_names = ['허성문', '이민우', 'WANG ZHANJUN']
        df_loyalty_all = df_clean.copy()
        df_loyalty_all = df_loyalty_all[~df_loyalty_all[f_name].astype(str).str.contains('|'.join(exclude_names), na=False)]
        df_loyalty_all = df_loyalty_all.sort_values([f_name, '입실일자'])
        
        # 식별키 생성
        if f_phone:
            df_loyalty_all['GuestKey'] = df_loyalty_all[f_name].astype(str) + "_" + df_loyalty_all[f_phone].astype(str).str[-4:]
        else:
            df_loyalty_all['GuestKey'] = df_loyalty_all[f_name].astype(str)

        # 전체 기간 기준 통계
        guest_stats = df_loyalty_all.groupby('GuestKey').agg({'예약번호': 'count', '총금액': 'sum', '객실수': 'sum'}).reset_index()
        guest_stats.columns = ['GuestKey', 'TotalVisits', 'TotalRev', 'TotalRooms']

        def segment_visit(n):
            if n == 1: return "1회 (신규)"
            elif n == 2: return "2회 (리피터)"
            elif n == 3: return "3회 (단골)"
            elif n == 4: return "4회 (충성)"
            else: return "5회 이상 (VVIP)"
        guest_stats['CustomerGrade'] = guest_stats['TotalVisits'].apply(segment_visit)

        # 타겟 기간 병합
        target_f_filtered = target_df[~target_df[f_name].astype(str).str.contains('|'.join(exclude_names), na=False)]
        df_target_loyalty = df_loyalty_all[df_loyalty_all['예약번호'].isin(target_f_filtered['예약번호'])].copy()
        df_target_loyalty = pd.merge(df_target_loyalty, guest_stats[['GuestKey', 'TotalVisits', 'CustomerGrade']], on='GuestKey', how='left')

        # --- [3] 시각화: 요약 비교 ---
        st.subheader("📊 기간별 재방문율 비교 (타겟 vs 전체)")
        total_unique = guest_stats['GuestKey'].nunique()
        total_repeater = guest_stats[guest_stats['TotalVisits'] > 1]['GuestKey'].nunique()
        t_unique = df_target_loyalty['GuestKey'].nunique()
        t_repeater = df_target_loyalty[df_target_loyalty['TotalVisits'] > 1]['GuestKey'].nunique()
        
        c_sum1, c_sum2 = st.columns(2)
        c_sum1.info(f"📅 **선택한 기간**\n\n- 재방문율: **{(t_repeater/t_unique*100) if t_unique>0 else 0:.1f}%**")
        c_sum2.success(f"🌎 **전체 누적 기간**\n\n- 누적 재방문율: **{(total_repeater/total_unique*100) if total_unique>0 else 0:.1f}%**")

        st.divider()
        st.subheader("1️⃣ 고객 등급별 분포")
        c_l1, c_l2 = st.columns(2)
        grade_order = ["1회 (신규)", "2회 (리피터)", "3회 (단골)", "4회 (충성)", "5회 이상 (VVIP)"]
        grade_counts = df_target_loyalty.groupby('CustomerGrade').size().reindex(grade_order).fillna(0).reset_index(name='Count')
        with c_l1: st.plotly_chart(px.pie(grade_counts, names='CustomerGrade', values='Count', hole=0.4, title="고객 구성비"), use_container_width=True)
        with c_l2: st.plotly_chart(px.bar(grade_counts, x='CustomerGrade', y='Count', text_auto=True, title="등급별 예약 건수", color='CustomerGrade'), use_container_width=True)

        st.divider()
        st.subheader("2️⃣ 심층 인사이트: 방문 주기 및 채널 전환")
        c_in1, c_in2 = st.columns(2)
        with c_in1:
            df_loyalty_all['Prev'] = df_loyalty_all.groupby('GuestKey')['입실일자'].shift(1)
            df_loyalty_all['Interval'] = (df_loyalty_all['입실일자'] - df_loyalty_all['Prev']).dt.days
            re_data = df_loyalty_all[df_loyalty_all['Interval'] > 0]['Interval']
            if not re_data.empty:
                st.plotly_chart(px.histogram(re_data, x='Interval', nbins=50, title=f"평균 재방문 주기: {re_data.mean():.1f}일"), use_container_width=True)
        with c_in2:
            f_c = df_loyalty_all.groupby('GuestKey').first()['거래처'].reset_index().rename(columns={'거래처':'First'})
            l_c = df_loyalty_all.groupby('GuestKey').last()['거래처'].reset_index().rename(columns={'거래처':'Last'})
            drift = pd.merge(f_c, l_c, on='GuestKey')
            drift = drift[drift['GuestKey'].isin(guest_stats[guest_stats['TotalVisits'] > 1]['GuestKey'])]
            if not drift.empty:
                d_p = drift.groupby(['First', 'Last']).size().reset_index(name='Count').pivot(index='First', columns='Last', values='Count').fillna(0)
                st.write("**채널 전이 매트릭스**")
                st.dataframe(d_p.style.background_gradient(cmap='Blues'), height=250)

        st.divider()
        st.subheader("3️⃣ 수익 기여도 분석")
        c_rv1, c_rv2 = st.columns(2)
        with c_rv1:
            g_perf = df_target_loyalty.groupby('CustomerGrade').apply(lambda x: x['총금액'].sum() / x['객실수'].sum() if x['객실수'].sum() > 0 else 0).reindex(grade_order).fillna(0).reset_index(name='ADR')
            st.plotly_chart(px.line(g_perf, x='CustomerGrade', y='ADR', markers=True, title="등급별 ADR 추이"), use_container_width=True)
        with c_rv2:
            g_rev_t = df_target_loyalty.groupby('CustomerGrade')['총금액'].sum().reindex(grade_order).fillna(0).reset_index()
            st.plotly_chart(px.pie(g_rev_t, names='CustomerGrade', values='총금액', title="매출 기여도 비중"), use_container_width=True)

        st.divider()
        st.subheader("4️⃣ 마케팅 타겟 고객 리스트")
        l_tab1, l_tab2 = st.tabs(["💎 VVIP (5회 이상)", "⭐ 단골 (2회~4회)"])
        with l_tab1:
            vvip = guest_stats[guest_stats['TotalVisits'] >= 5].sort_values('TotalVisits', ascending=False)
            st.dataframe(vvip, use_container_width=True)
            st.download_button("📥 VVIP 리스트 다운로드", data=vvip.to_csv(index=False).encode('utf-8-sig'), file_name="VVIP_List.csv")
        with l_tab2:
            reg = guest_stats[(guest_stats['TotalVisits'] >= 2) & (guest_stats['TotalVisits'] < 5)].sort_values('TotalVisits', ascending=False)
            st.dataframe(reg, use_container_width=True)
            st.download_button("📥 단골 리스트 다운로드", data=reg.to_csv(index=False).encode('utf-8-sig'), file_name="Regular_Guest_List.csv")

# -----------------------------------------------------------------------------
# 5. 하단 검증기
# -----------------------------------------------------------------------------
st.divider()
with st.expander("🕵️‍♂️ 데이터 검증 (Raw Data)"):
    st.dataframe(df_view.head(100))


# --- 02_Room OTB Status.py 하단 수정 ---

# 1. 월(Month) 정보 가져오기 (가장 안전한 방법)
# 위쪽 코드에서 'current_month'나 'month'를 정의했다면 그것을 쓰고, 
# 없으면 데이터프레임(df_curr)에서 직접 추출합니다.
try:
    if 'current_month' in locals():
        save_month = current_month
    elif 'month' in locals():
        save_month = month
    elif 'df_curr' in locals() and df_curr is not None:
        # 데이터프레임의 첫 번째 행 날짜에서 월 추출
        save_month = df_curr['Date'].iloc[0].month
    else:
        # 이도 저도 안 되면 오늘 날짜 기준
        import datetime
        save_month = datetime.datetime.now().month
except Exception:
    import datetime
    save_month = datetime.datetime.now().month

# 2. 공용 게시판(session_state)에 데이터 전송
if 'sob_curr' in locals() and sob_curr is not None:
    st.session_state[f"sob_{save_month}"] = sob_curr
    
    if 'df_curr' in locals() and 'df_prev' in locals():
        # 페이스 데이터(변화량) 저장
        st.session_state[f"pace_{save_month}"] = len(df_curr) - len(df_prev)

    st.success(f"✅ {save_month}월 데이터가 포캐스팅 시스템으로 전송되었습니다.")
