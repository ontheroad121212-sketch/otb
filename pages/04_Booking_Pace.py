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
# 1. Firebase 접속 및 초기 설정
# -----------------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Amber Pure Hill Dashboard", page_icon="🏨")

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
# 2. 데이터 고속 로딩(Parquet) 및 스냅샷 관리
# -----------------------------------------------------------------------------
CACHE_FILE = "local_booking_cache.parquet"

def upload_to_firestore(df_new):
    if db is None: return
    df_new = df_new.copy()
    
    # 업로드 시점 자동 기록
    upload_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    df_new['Snapshot'] = upload_time
    
    # 필수 전처리
    df_new['입실일자'] = pd.to_datetime(df_new['입실일자'], errors='coerce')
    df_new['예약일자'] = pd.to_datetime(df_new['예약일자'], errors='coerce')
    df_new['예약번호'] = df_new['예약번호'].astype(str)
    
    # 숫자 데이터 강제 변환 (오류 방지)
    cols_to_numeric = ['총금액', '객실수', '박수', '객실금액', '객실료', '상품금액']
    for col in cols_to_numeric:
        if col in df_new.columns:
            df_new[col] = pd.to_numeric(df_new[col], errors='coerce').fillna(0)
            
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
    msg.success(f"✅ {total}건 업데이트 완료!")
    
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
    if os.path.exists(CACHE_FILE):
        try:
            df = pd.read_parquet(CACHE_FILE)
            return df, "로컬 캐시 (고속)"
        except:
            pass

    if db is None: return pd.DataFrame(), "연결 안됨"
    try:
        docs = db.collection('hotel_bookings').limit(100000).stream() 
        data = [doc.to_dict() for doc in docs]
        if not data: return pd.DataFrame(), "데이터 없음"
        
        df = pd.DataFrame(data)
        df['입실일자'] = pd.to_datetime(df['입실일자'], errors='coerce')
        df['예약일자'] = pd.to_datetime(df['예약일자'], errors='coerce')
        df = df.dropna(subset=['입실일자', '예약일자'])
        
        df['입실일자'] = df['입실일자'].dt.tz_localize(None)
        df['예약일자'] = df['예약일자'].dt.tz_localize(None)
        df['LeadTime'] = (df['입실일자'] - df['예약일자']).dt.days
        df['Year'] = df['입실일자'].dt.isocalendar().year.fillna(0).astype(int)
        df['Month'] = df['입실일자'].dt.month.fillna(0).astype(int)
        df['Week'] = df['입실일자'].dt.isocalendar().week.fillna(0).astype(int)
        df['DayOfWeek'] = df['입실일자'].dt.day_name()
        
        # [핵심 로직 수정] 룸나잇 및 객실매출 계산
        if '박수' in df.columns:
            df['박수'] = pd.to_numeric(df['박수'], errors='coerce').fillna(1)
        else:
            df['박수'] = 1
            
        if '객실수' in df.columns:
            df['객실수'] = pd.to_numeric(df['객실수'], errors='coerce').fillna(1)
        else:
            df['객실수'] = 1
            
        # 룸나잇 = 객실수 * 박수
        df['RoomNights'] = df['객실수'] * df['박수']
        
        # 객실 매출 분리 (컬럼이 없으면 총금액을 사용하되 분리 변수 지정)
        rev_cols = ['객실금액', '객실료', '상품금액']
        found_rev = next((c for c in rev_cols if c in df.columns), None)
        
        df['총금액'] = pd.to_numeric(df['총금액'], errors='coerce').fillna(0)
        
        if found_rev:
            df['RoomRevenue'] = pd.to_numeric(df[found_rev], errors='coerce').fillna(0)
        else:
            df['RoomRevenue'] = df['총금액']

        if 'Snapshot' not in df.columns:
            df['Snapshot'] = "이전 데이터"
            
        df.to_parquet(CACHE_FILE)
        return df, "Firestore (실시간)"
    except:
        return pd.DataFrame(), "조회 에러"

# -----------------------------------------------------------------------------
# 3. 사이드바 및 필터 (취소 정밀 필터 적용)
# -----------------------------------------------------------------------------
df_raw, load_source = load_data_with_snapshot_cache()

with st.sidebar:
    st.title("⚙️ 시스템 관리")
    st.write(f"**DB 상태:** {db_status}")
    st.caption(f"로드 소스: {load_source}")
    
    with st.expander("📤 데이터 업로드", expanded=True):
        st.info("💡 4만 건 이상 대용량은 1만 건씩 나눠 올리기를 권장합니다.")
        up_files = st.file_uploader("엑셀/CSV 파일", accept_multiple_files=True)
        
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
    st.markdown("**🔍 데이터 버전(Snapshot) 선택**")
    if not df_raw.empty:
        snapshot_options = sorted(df_raw['Snapshot'].unique(), reverse=True)
        selected_snapshot = st.selectbox("조회할 데이터 버전", snapshot_options)
        df = df_raw[df_raw['Snapshot'] == selected_snapshot]
    else:
        df = df_raw

    st.markdown("**🚫 필터 설정**")
    cancel_k = ['취소', 'CXL', 'CANCEL', 'NO', 'NOSHOW', 'RC', 'RX']
    all_sts = df['상태'].unique().astype(str) if '상태' in df.columns else []
    
    def_exc = [s for s in all_sts if any(x in s.upper() for x in cancel_k)]
    
    exc_sts = st.multiselect(
        "분석 제외 상태 (취소/RC/RX 등)", 
        options=all_sts, 
        default=def_exc,
        help="체크된 상태는 매출 및 ADR 분석에서 제외됩니다."
    )
    
    df_clean = df[~df['상태'].isin(exc_sts)] if '상태' in df.columns else df

# -----------------------------------------------------------------------------
# 4. 메인 화면 출력
# -----------------------------------------------------------------------------

if df_clean.empty:
    st.title("🏨 Hotel Strategy Dashboard")
    st.info("👋 환영합니다! 데이터가 없습니다. 사이드바에서 업로드해주세요.")
    st.stop()

st.title("🏨 Hotel Strategy Dashboard")

col_kpi1, col_kpi2, col_kpi3 = st.columns(3)
with col_kpi1:
    st.metric("분석 대상 예약건수", f"{len(df_clean):,} 건")
with col_kpi2:
    min_date = df_clean['입실일자'].min().date() if not df_clean.empty else "-"
    st.metric("데이터 시작일", str(min_date))
with col_kpi3:
    max_date = df_clean['입실일자'].max().date() if not df_clean.empty else "-"
    st.metric("데이터 종료일", str(max_date))

st.caption(f"※ 데이터 버전: {selected_snapshot if not df_raw.empty else 'N/A'}")

# --- 메인 필터 ---
c1, c2 = st.columns([1, 2])
with c1:
    view_mode = st.radio("📊 분석 단위", ["월별", "분기별", "주별", "연간"], horizontal=True)
with c2:
    all_acc = sorted(df_clean['거래처'].unique())
    sel_acc = st.multiselect("🏦 거래처 필터", all_acc, placeholder="전체 거래처(All Channels) 보기")

# 필터링 적용
df_view = df_clean[df_clean['거래처'].isin(sel_acc)] if sel_acc else df_clean
st.divider()

# --- 비교 기간 선택 ---
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
    st.warning(f"⚠️ 선택하신 기간({chart_sub})에 해당하는 데이터가 없습니다. 필터를 확인해주세요.")
    st.stop()

# -----------------------------------------------------------------------------
# 5. 시각화 탭
# -----------------------------------------------------------------------------
tabs = st.tabs(["💰 매출", "💳 ADR", "⏳ 리드타임", "📅 요일", "🌏 국적/객실", "🔁 로열티(재방문)", "🚀 RM 분석", "🎯 수익 전략"])

# [TAB 0] Revenue (총매출, 객실매출, 룸나잇 분리)
with tabs[0]:
    st.subheader(f"매출 페이스: {chart_sub}")
    
    # 핵심 지표 분리 표시
    tot_rev = target_df['총금액'].sum()
    room_rev = target_df['RoomRevenue'].sum()
    rn_sum = target_df['RoomNights'].sum()
    
    k1, k2, k3 = st.columns(3)
    k1.metric("총 매출 (Total)", f"{tot_rev/10000:,.0f}만")
    k2.metric("객실 매출 (Room)", f"{room_rev/10000:,.0f}만")
    k3.metric("총 룸나잇 (RN)", f"{rn_sum:,.0f}박")
    
    def get_pace(d):
        if d.empty: return pd.Series(dtype=float)
        return d.groupby('LeadTime')['총금액'].sum().sort_index(ascending=False).cumsum().sort_index()
    pt, pr = get_pace(target_df), get_pace(ref_df)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=pt.index, y=pt.values, name='Target (Total)', line=dict(color='#0052cc', width=3)))
    if not pr.empty: fig.add_trace(go.Scatter(x=pr.index, y=pr.values, name='Ref (Total)', line=dict(color='gray', dash='dot')))
    if not pt.empty:
        lp = pt.index.min()
        fig.add_trace(go.Scatter(x=[lp], y=[pt[lp]], mode='markers+text', text=[f"{pt[lp]/10000:,.0f}만"], textposition="top left", marker=dict(color='red', size=8), showlegend=False))
    fig.update_layout(xaxis={'autorange': 'reversed'}, xaxis_title="D-Day", yaxis_title="누적 매출", height=500)
    st.plotly_chart(fig, use_container_width=True)

# [TAB 1] ADR (정밀 계산 적용: Room Revenue / Room Nights)
with tabs[1]:
    st.subheader(f"ADR(객단가) 정밀 분석")
    st.info("💡 ADR = 객실매출 / 룸나잇 (객실수 × 박수)")
    
    def get_adr_precise(d):
        if d.empty: return pd.Series(dtype=float)
        # 누적 객실매출
        cum_rev = d.groupby('LeadTime')['RoomRevenue'].sum().sort_index(ascending=False).cumsum().sort_index()
        # 누적 룸나잇
        cum_rn = d.groupby('LeadTime')['RoomNights'].sum().sort_index(ascending=False).cumsum().sort_index()
        return (cum_rev / cum_rn).fillna(0)
        
    at, ar = get_adr_precise(target_df), get_adr_precise(ref_df)
    
    # 현재 평균 ADR 계산
    curr_adr = target_df['RoomRevenue'].sum() / target_df['RoomNights'].sum() if target_df['RoomNights'].sum() > 0 else 0
    st.metric("기간 평균 ADR", f"{curr_adr:,.0f}원")
    
    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(x=at.index, y=at.values, name='Target ADR', line=dict(color='#ff6b6b', width=3)))
    if not ar.empty: fig2.add_trace(go.Scatter(x=ar.index, y=ar.values, name='Ref ADR', line=dict(color='gray', dash='dot')))
    fig2.update_layout(xaxis={'autorange': 'reversed'}, height=500)
    st.plotly_chart(fig2, use_container_width=True)

# [TAB 2] Lead Time
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

# [TAB 3] Day of Week
with tabs[3]:
    st.subheader("요일별 매출 퍼포먼스")
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    td = target_df.groupby('DayOfWeek')['총금액'].mean().reindex(days).reset_index()
    rd = ref_df.groupby('DayOfWeek')['총금액'].mean().reindex(days).reset_index()
    fig4 = go.Figure()
    fig4.add_trace(go.Scatter(x=td['DayOfWeek'], y=td['총금액'], name='Target', line=dict(color='green', width=3)))
    fig4.add_trace(go.Scatter(x=rd['DayOfWeek'], y=rd['총금액'], name='Ref', line=dict(color='gray', dash='dot')))
    st.plotly_chart(fig4, use_container_width=True)

# [TAB 4] Demographics
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

# [TAB 5] Guest Loyalty
with tabs[5]:
    st.header("🔁 고객 로열티 심층 리포트 (VIP & N차 분석)")
    
    name_cols = ['고객명', '예약자', '성함', '고객성함', 'Guest Name', 'Name', '예약자명', '한글성명', '고객']
    phone_cols = ['휴대폰', '전화번호', '연락처', 'Mobile', 'Phone', '핸드폰', '휴대전화']
    
    f_name = next((c for c in name_cols if c in df_clean.columns), None)
    f_phone = next((c for c in phone_cols if c in df_clean.columns), None)

    if not f_name:
        st.warning(f"⚠️ '고객명' 컬럼을 찾을 수 없어 분석을 시작할 수 없습니다.")
    else:
        exclude_names = ['허성문', '이민우', 'WANG ZHANJUN']
        df_l = df_clean.copy()
        df_l = df_l[~df_l[f_name].astype(str).str.contains('|'.join(exclude_names), na=False)]
        df_l = df_l.sort_values([f_name, '입실일자'])
        
        if f_phone:
            df_l['GuestKey'] = df_l[f_name].astype(str) + "_" + df_l[f_phone].astype(str).str[-4:]
        else:
            df_l['GuestKey'] = df_l[f_name].astype(str)

        df_l['PrevVisit'] = df_l.groupby('GuestKey')['입실일자'].shift(1)
        df_l['DaysSinceLastVisit'] = (df_l['입실일자'] - df_l['PrevVisit']).dt.days

        guest_stats = df_l.groupby('GuestKey').agg({
            '예약번호': 'count',
            '총금액': 'sum',
            '객실수': 'sum'
        }).reset_index()
        guest_stats.columns = ['GuestKey', 'TotalVisits', 'TotalRev', 'TotalRooms']

        def segment_visit(n):
            if n == 1: return "1회 (신규)"
            elif n == 2: return "2회 (리피터)"
            elif n == 3: return "3회 (단골)"
            elif n == 4: return "4회 (충성)"
            else: return "5회 이상 (VVIP)"
        guest_stats['CustomerGrade'] = guest_stats['TotalVisits'].apply(segment_visit)

        target_filtered = target_df[~target_df[f_name].astype(str).str.contains('|'.join(exclude_names), na=False)]
        df_target_loyalty = df_l[df_l['예약번호'].isin(target_filtered['예약번호'])].copy()
        df_target_loyalty = pd.merge(df_target_loyalty, guest_stats[['GuestKey', 'TotalVisits', 'CustomerGrade']], on='GuestKey', how='left')
        df_target_loyalty['GuestType'] = df_target_loyalty['TotalVisits'].apply(lambda x: '첫 방문 (New)' if x <= 1 else '재방문 (Return)')

        st.subheader("📊 기간별 재방문율 비교 (타겟 vs 전체)")
        total_u = guest_stats['GuestKey'].nunique()
        total_r = guest_stats[guest_stats['TotalVisits'] > 1]['GuestKey'].nunique()
        total_rate = (total_r / total_u * 100) if total_u > 0 else 0
        
        target_u = df_target_loyalty['GuestKey'].nunique()
        target_r = df_target_loyalty[df_target_loyalty['TotalVisits'] > 1]['GuestKey'].nunique()
        target_rate = (target_r / target_u * 100) if target_u > 0 else 0

        col_sum1, col_sum2 = st.columns(2)
        with col_sum1:
            st.info(f"📅 **선택한 기간**\n\n- 고객: {target_u:,}명 / 재방문: {target_r:,}명\n- 재방문율: **{target_rate:.1f}%**")
        with col_sum2:
            st.success(f"🌎 **전체 누적 기간**\n\n- 총 고객: {total_u:,}명 / 총 재방문: {total_r:,}명\n- 누적 재방문율: **{total_rate:.1f}%**")
        
        st.divider()

        st.subheader("1️⃣ 고객 구성 및 등급별 분포")
        c1, c2 = st.columns(2)
        grade_order = ["1회 (신규)", "2회 (리피터)", "3회 (단골)", "4회 (충성)", "5회 이상 (VVIP)"]
        
        grade_counts = df_target_loyalty.groupby('CustomerGrade').size().reindex(grade_order).fillna(0).reset_index()
        grade_counts.columns = ['등급', 'count']
        
        with c1:
            st.plotly_chart(px.pie(grade_counts, names='등급', values='count', hole=0.4, title="고객 등급 구성비"), use_container_width=True)
        with c2:
            st.plotly_chart(px.bar(grade_counts, x='등급', y='count', text_auto=True, title="등급별 예약 건수", color='등급'), use_container_width=True)

        st.divider()

        st.subheader("2️⃣ 심층 인사이트: 방문 주기 및 채널 전환")
        col_in1, col_in2 = st.columns(2)
        with col_in1:
            revisit_data = df_l[df_l['DaysSinceLastVisit'] > 0]['DaysSinceLastVisit']
            if not revisit_data.empty:
                avg_days = revisit_data.mean()
                fig_inv = px.histogram(revisit_data, x='DaysSinceLastVisit', nbins=50, 
                                       title=f"평균 재방문 주기: 약 {avg_days:.1f}일", color_discrete_sequence=['#0052cc'])
                st.plotly_chart(fig_inv, use_container_width=True)
        with col_in2:
            first_c = df_l.groupby('GuestKey').first()['거래처'].reset_index().rename(columns={'거래처':'First'})
            last_c = df_l.groupby('GuestKey').last()['거래처'].reset_index().rename(columns={'거래처':'Last'})
            drift = pd.merge(first_c, last_c, on='GuestKey')
            drift = drift[drift['GuestKey'].isin(guest_stats[guest_stats['TotalVisits'] > 1]['GuestKey'])]
            if not drift.empty:
                drift_p = drift.groupby(['First', 'Last']).size().reset_index(name='Count').pivot(index='First', columns='Last', values='Count').fillna(0)
                st.write("**채널 전이 매트릭스**")
                st.dataframe(drift_p.style.background_gradient(cmap='Blues'), height=250)

        st.divider()

        st.subheader("3️⃣ 수익 기여도 분석")
        col_rev1, col_rev2 = st.columns(2)
        with col_rev1:
            grade_perf = df_target_loyalty.groupby('CustomerGrade').apply(
                lambda x: x['총금액'].sum() / x['객실수'].sum() if x['객실수'].sum() > 0 else 0
            ).reindex(grade_order).fillna(0).reset_index(name='ADR')
            st.plotly_chart(px.line(grade_perf, x='CustomerGrade', y='ADR', markers=True, title="등급별 ADR 추이"), use_container_width=True)
        with col_rev2:
            grade_rev_total = df_target_loyalty.groupby('CustomerGrade')['총금액'].sum().reindex(grade_order).fillna(0).reset_index()
            st.plotly_chart(px.pie(grade_rev_total, names='CustomerGrade', values='총금액', title="등급별 매출 기여도 비중"), use_container_width=True)

        st.divider()

        st.subheader("4️⃣ 마케팅 타겟 고객 리스트")
        list_tab1, list_tab2 = st.tabs(["💎 VVIP (5회 이상)", "⭐ 단골 (2회~4회)"])
        with list_tab1:
            vvip_list = guest_stats[guest_stats['TotalVisits'] >= 5].sort_values('TotalVisits', ascending=False)
            if not vvip_list.empty:
                st.dataframe(vvip_list, use_container_width=True)
                st.download_button("📥 VVIP 리스트 다운로드", data=vvip_list.to_csv(index=False).encode('utf-8-sig'), file_name="VVIP_List.csv")
        with list_tab2:
            regular_list = guest_stats[(guest_stats['TotalVisits'] >= 2) & (guest_stats['TotalVisits'] < 5)].sort_values('TotalVisits', ascending=False)
            if not regular_list.empty:
                st.dataframe(regular_list, use_container_width=True)
                st.download_button("📥 단골 리스트 다운로드", data=regular_list.to_csv(index=False).encode('utf-8-sig'), file_name="Regular_Guest_List.csv")

# [TAB 6] 🚀 수익 관리 (RM 정밀 분석 & 핀셋 필터)
with tabs[6]:
    st.header("🚀 수익 관리(RM) 기간별 정밀 분석")
    st.info("💡 RC, RX 등 취소 건을 철저히 제외한 **순수 투숙(Net)** 기준 분석입니다.")
    
    rm_mode = st.radio("분석 기준 선택", ["📅 입실일자 기준", "📝 예약일자 기준"], horizontal=True, key="rm_filter_main")
    d_col = '입실일자' if "입실일자" in rm_mode else '예약일자'
    
    rm_c1, rm_c2 = st.columns(2)
    with rm_c1: d_a = st.date_input("기준 기간 (Period A)", [datetime(2025,1,1), datetime(2025,1,31)], key="da_rm_f")
    with rm_c2: d_b = st.date_input("비교 기간 (Period B)", [datetime(2026,1,1), datetime(2026,1,24)], key="db_rm_f")
    
    # 1. 날짜 필터
    df_a_raw = df_raw[(df_raw[d_col].dt.date >= d_a[0]) & (df_raw[d_col].dt.date <= d_a[1])].copy()
    df_b_raw = df_raw[(df_raw[d_col].dt.date >= d_b[0]) & (df_raw[d_col].dt.date <= d_b[1])].copy()
    
    # 2. 유효 데이터 (취소 제외)
    df_a_valid = df_a_raw[~df_a_raw['상태'].isin(def_exc)]
    df_b_valid = df_b_raw[~df_b_raw['상태'].isin(def_exc)]
    
    if not df_a_valid.empty and not df_b_valid.empty:
        sub_rm = st.tabs(["📊 KPI (Net)", "📈 Pace", "📉 Wash-out", "⏳ 패턴", "🌏 국적/채널", "🚀 픽업"])
        
        with sub_rm[0]: # KPI (정밀 ADR 적용)
            # A기간
            rev_a_tot = df_a_valid['총금액'].sum()
            rev_a_room = df_a_valid['RoomRevenue'].sum()
            rn_a = df_a_valid['RoomNights'].sum()
            adr_a = rev_a_room / rn_a if rn_a > 0 else 0
            
            # B기간
            rev_b_tot = df_b_valid['총금액'].sum()
            rev_b_room = df_b_valid['RoomRevenue'].sum()
            rn_b = df_b_valid['RoomNights'].sum()
            adr_b = rev_b_room / rn_b if rn_b > 0 else 0
            
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("총 매출", f"{rev_b_tot/10000:,.0f}만", f"{(rev_b_tot-rev_a_tot)/10000:,.0f}만")
            k2.metric("객실 매출", f"{rev_b_room/10000:,.0f}만", f"{(rev_b_room-rev_a_room)/10000:,.0f}만")
            k3.metric("룸나잇 (RN)", f"{rn_b:,.0f}박", f"{rn_b-rn_a:,.0f}박")
            k4.metric("ADR (객실/RN)", f"{adr_b:,.0f}원", f"{adr_b-adr_a:,.0f}원")
            
        with sub_rm[1]: # Pace
            p_a = df_a_valid.groupby(d_col)['객실수'].sum().sort_index().cumsum()
            p_b = df_b_valid.groupby(d_col)['객실수'].sum().sort_index().cumsum()
            st.plotly_chart(go.Figure(data=[go.Scatter(y=p_a.values, name="A (Net)"), go.Scatter(y=p_b.values, name="B (Net)")]), use_container_width=True)
            
        with sub_rm[2]: # Wash-out
            df_b_raw['is_cxl'] = df_b_raw['상태'].isin(def_exc)
            cxl = df_b_raw.groupby('거래처')['is_cxl'].mean() * 100
            st.plotly_chart(px.bar(cxl.reset_index(), x='거래처', y='is_cxl', title="거래처별 취소율(%)"), use_container_width=True)
            
        with sub_rm[3]: 
            lt_c = pd.concat([df_a_valid.assign(P='A'), df_b_valid.assign(P='B')])
            st.plotly_chart(px.box(lt_c, x='P', y='LeadTime', color='P', title="Lead Time 변동"), use_container_width=True)

        with sub_rm[4]: # 국적/채널 (에러 수정)
            c1, c2 = st.columns(2)
            c1.plotly_chart(px.pie(df_b_valid.groupby('국적')['총금액'].sum().reset_index().head(7), values='총금액', names='국적', title="현재 국적 비중"), use_container_width=True)
            
            acc_a = df_a_valid['거래처'].value_counts(normalize=True).head(7).reset_index()
            acc_a.columns = ['거래처', '점유율']
            acc_a['P'] = 'A'
            acc_b = df_b_valid['거래처'].value_counts(normalize=True).head(7).reset_index()
            acc_b.columns = ['거래처', '점유율']
            acc_b['P'] = 'B'
            
            c2.plotly_chart(px.line(pd.concat([acc_a, acc_b]), x='거래처', y='점유율', color='P', markers=True, title="Channel Share"), use_container_width=True)

        with sub_rm[5]: # 픽업
            pickup_a = df_a_valid.groupby(d_col)['객실수'].sum()
            pickup_b = df_b_valid.groupby(d_col)['객실수'].sum()
            diff = (pickup_b - pickup_a).fillna(pickup_b).reset_index(name='Pickup')
            st.plotly_chart(px.bar(diff, x=d_col, y='Pickup', color='Pickup', title="예약 증감 (Net)"), use_container_width=True)

# [TAB 7] 🎯 수익 전략 (Golden ADR 등 - 룸나잇 반영)
with tabs[7]:
    st.header("🎯 수익 극대화 전략 (Strategy)")
    s_tabs = st.tabs(["💰 황금 ADR", "🌍 국적 분석", "🛡️ 취소 예측"])
    
    with s_tabs[0]:
        df_g = df_clean.groupby('입실일자').agg({'RoomRevenue':'sum', 'RoomNights':'sum'}).reset_index()
        df_g = df_g[df_g['RoomNights'] > 0]
        df_g['ADR'] = df_g['RoomRevenue'] / df_g['RoomNights']
        
        st.plotly_chart(px.scatter(df_g, x='ADR', y='RoomRevenue', size='RoomNights', title="ADR vs 객실매출 상관관계 (룸나잇 기준)"), use_container_width=True)
        
    with s_tabs[1]:
        nat_p = df_clean.groupby('국적').agg({'RoomRevenue':'mean','LeadTime':'mean','RoomNights':'sum','예약번호':'count'}).reset_index()
        st.plotly_chart(px.scatter(nat_p[nat_p['예약번호']>5], x='LeadTime', y='RoomRevenue', size='RoomNights', text='국적', title="국적별 수익성 (객실매출)"), use_container_width=True)
        
    with s_tabs[2]:
        df_raw['is_cxl_hist'] = df_raw['상태'].isin(def_exc)
        cxl_rate_hist = df_raw['is_cxl_hist'].mean()
        current_otb = target_df['객실수'].sum()
        net_predict = int(current_otb * (1 - cxl_rate_hist))
        st.metric("현재 OTB 기준 실투숙 예측", f"{net_predict}실", f"예상 취소: {int(current_otb * cxl_rate_hist)}실")

# -----------------------------------------------------------------------------
# 6. 포캐스팅 시스템 연동
# -----------------------------------------------------------------------------
try:
    df_raw['dow_idx'] = df_raw['예약일자'].dt.dayofweek
    st.session_state["historical_dow"] = (df_raw['dow_idx'].value_counts(normalize=True)*7).to_dict()
    if f_name:
        st.session_state["repeat_rate"] = (df_raw[f_name].value_counts()>1).mean()*100
    s_m = df_clean['입실일자'].iloc[0].month if not df_clean.empty else datetime.now().month
    st.session_state[f"sob_{s_m}"] = len(df_clean)
    st.toast("✅ 포캐스팅 데이터 동기화 완료")
except: pass

st.divider()
with st.expander("🕵️‍♂️ 데이터 검증 (Raw Data)"):
    st.write("▼ 현재 필터링된 데이터 (취소 제외됨)")
    st.dataframe(df_view.head(50))
