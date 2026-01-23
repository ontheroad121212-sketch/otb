import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timedelta
import io
import numpy as np
import textwrap
import secret_forecasting  # 포캐스팅 모듈 임포트

# ==============================================================================
# [1] 페이지 기본 설정 및 CSS 스타일링
# ==============================================================================
st.set_page_config(
    layout="wide",
    page_title="Daily Pace Report & Forecasting",
    initial_sidebar_state="expanded"
)

st.markdown(textwrap.dedent("""
<style>
    .block-container { padding-top: 0.5rem; padding-bottom: 2rem; }
    
    /* S.O.B 요약 카드 디자인 */
    .sob-container {
        background-color: white; border-radius: 15px;
        box-shadow: 0 4px 20px rgba(0,0,0,0.08); padding: 30px;
        margin-bottom: 30px; border: 1px solid #e5e7eb;
    }
    .sob-header {
        font-size: 24px; font-weight: 900; color: #111827;
        margin-bottom: 25px; border-bottom: 3px solid #f3f4f6; padding-bottom: 15px;
    }
    .sob-grid { display: grid; grid-template-columns: 1fr 1.3fr; gap: 50px; }
    
    /* 테이블 공통 스타일 */
    .modern-table { width: 100%; border-collapse: collapse; }
    .modern-table th { 
        text-align: right; color: #4b5563; font-size: 14px; font-weight: 700;
        padding: 12px 10px; border-bottom: 2px solid #e5e7eb; background-color: #f9fafb;
    }
    .modern-table td { padding: 14px 10px; font-size: 16px; text-align: right; border-bottom: 1px solid #f3f4f6; }
    .modern-table td.label { text-align: left; font-weight: 700; }

    /* KPI 카드 */
    .kpi-wrapper { display: flex; gap: 20px; margin-top: 25px; }
    .kpi-card { flex: 1; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; padding: 20px; text-align: center; }
    .kpi-title { font-size: 14px; color: #64748b; font-weight: 800; }
    .kpi-value { font-size: 32px; color: #0f172a; font-weight: 900; }
    .kpi-accent { background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%); color: white; }
    .kpi-accent .kpi-title, .kpi-accent .kpi-value { color: white; }

    /* 하단 상세 데이터 테이블 컴팩트 스타일 */
    .compact-table-wrapper { overflow-x: auto; margin-bottom: 50px; border: 1px solid #e5e7eb; }
    .compact-table-wrapper table { width: 100%; border-collapse: collapse; font-size: 10px !important; }
    .compact-table-wrapper th { 
        background-color: #f8fafc; padding: 5px 3px !important; border: 1px solid #e2e8f0;
        font-size: 10px !important; line-height: 1.2; white-space: pre-wrap; text-align: center;
    }
    .compact-table-wrapper td { padding: 4px 3px !important; border: 1px solid #e2e8f0; font-size: 10px !important; text-align: right; }
</style>
"""), unsafe_allow_html=True)

# ==============================================================================
# [2] Firebase 연결 및 데이터 함수
# ==============================================================================
if not firebase_admin._apps:
    try:
        key_dict = dict(st.secrets["firebase"])
        cred = credentials.Certificate(key_dict)
        firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"🔥 Firebase 연결 실패: {e}")
        st.stop()

db = firestore.client()

# 월별 예산 데이터
BUDGET_DATA = {1:514992575, 2:786570856, 3:529599040, 4:695351004, 5:903705440, 6:808203820,
               7:1231949142, 8:1388376999, 9:952171506, 10:897171539, 11:667146771, 12:804030110}

def load_all_historical_data():
    """hotel_bookings 컬렉션에서 4만 건의 예약 데이터를 직접 분석"""
    db = firestore.client()
    st.write("📡 hotel_bookings 데이터베이스 연결 중...")
    
    # 1. 4만 건을 한꺼번에 가져오기 위한 스트림 설정
    # (주의: 데이터가 너무 많으면 시간이 걸리므로 덩어리로 끊어서 로드하는 것이 안전함)
    docs = db.collection("hotel_bookings").stream()
    
    data = []
    count = 0
    status_text = st.empty()
    
    for doc in docs:
        data.append(doc.to_dict())
        count += 1
        # 2,000건마다 진행 상황 표시 (지배인님이 답답하지 않게!)
        if count % 2000 == 0:
            status_text.write(f"📂 {count:,}건 읽어오는 중... 조금만 기다려주세요!")
            
    if not data:
        return {}, 0
    
    df = pd.DataFrame(data)
    st.write(f"✅ 총 {len(df):,}건 로드 완료! 지표 가공 시작...")

    # 2. 예약 생성일(booking_date 등) 필드 자동 매칭
    # 호텔 시스템마다 필드명이 다를 수 있으니 유연하게 대처합니다.
    bd_col = next((c for c in df.columns if c.lower() in ['booking_date', 'created_at', 'reservation_date', 'date']), None)
    
    if bd_col:
        # 날짜 형식으로 변환
        df['b_date'] = pd.to_datetime(df[bd_col], errors='coerce')
        df = df.dropna(subset=['b_date'])
        
        # 요일 추출 (0:월, 6:일)
        df['dow'] = df['b_date'].dt.dayofweek
        
        # [핵심] 요일별 예약 비중 지수화 (4만 건의 평균을 1.0으로 둠)
        # 예: 일요일 예약이 평소보다 1.2배 많다면 지수는 1.2
        dow_indices = (df['dow'].value_counts(normalize=True) * 7).to_dict()
    else:
        st.error("날짜 필드(booking_date)를 찾을 수 없습니다. 필드명을 확인해주세요.")
        dow_indices = {i: 1.0 for i in range(7)}

    # 3. 추가 통계 (재방문율 등)
    cust_col = next((c for c in df.columns if c.lower() in ['customer_id', 'phone', 'guest_name']), None)
    repeat_rate = (df[cust_col].value_counts() > 1).mean() * 100 if cust_col else 0
    
    return dow_indices, repeat_rate

def find_header_and_process(file):
    """엑셀 파일 헤더 감지 및 S.O.B/상세 데이터 추출"""
    try:
        file.seek(0)
        df_raw = pd.read_excel(file, header=None)
        header_row_idx = None
        for idx, row in df_raw.iloc[:15].iterrows():
            row_str = row.astype(str).values
            if any('객실수' in s for s in row_str) and any('매출' in s for s in row_str):
                header_row_idx = idx
                rms_indices = [i for i, val in enumerate(row_str) if '객실수' in str(val)]
                rev_indices = [i for i, val in enumerate(row_str) if '매출' in str(val)]
                break
        if header_row_idx is None: return None, None, None
        df_data = df_raw.iloc[header_row_idx+1:].copy()
        df_data['Date'] = pd.to_datetime(df_data.iloc[:, 0], errors='coerce')
        df_data = df_data.dropna(subset=['Date'])
        def safe_num(idx): return pd.to_numeric(df_data.iloc[:, idx], errors='coerce').fillna(0)
        
        fit_rms_idx, fit_rev_idx = rms_indices[0], rev_indices[0]
        grp_rms_idx, grp_rev_idx = rms_indices[1], rev_indices[1]
        total_rms_idx, total_rev_idx = rms_indices[-1], rev_indices[-1]

        df_clean = pd.DataFrame({'Date': df_data['Date'], 'DateStr': df_data['Date'].dt.strftime('%Y-%m-%d'), 'WeekDay': df_data['Date'].dt.strftime('%a')})
        df_clean['RMS'], df_clean['OCC'], df_clean['ADR'] = safe_num(total_rms_idx), safe_num(total_rms_idx+1), safe_num(total_rms_idx+2)
        df_clean['RevPAR'], df_clean['REV'] = safe_num(total_rms_idx+3), safe_num(total_rms_idx+4)
        df_clean['HU'], df_clean['Comp'] = safe_num(total_rms_idx-2), safe_num(total_rms_idx-1)

        sob_data = {'FIT_RMS': int(safe_num(fit_rms_idx).sum()), 'FIT_REV': int(safe_num(fit_rev_idx).sum()),
                    'GRP_RMS': int(safe_num(grp_rms_idx).sum()), 'GRP_REV': int(safe_num(grp_rev_idx).sum()),
                    'TOTAL_OCC': float(df_clean['RMS'].sum() / (df_clean['RMS']/(df_clean['OCC']/100)).sum() * 100)}
        return df_clean, df_data['Date'].iloc[0].month, sob_data
    except: return None, None, None

def get_full_data_by_date(date_str, month_num):
    try:
        doc = db.collection('daily_snapshots').document(date_str).collection('months').document(str(month_num)).get()
        if doc.exists:
            d = doc.to_dict()
            return pd.read_json(io.StringIO(d['json_data']), orient='records'), d.get('sob_data')
    except: pass
    return None, None

def save_data_with_sob(date_str, month, df, sob):
    try:
        db.collection('daily_snapshots').document(date_str).set({'created_at': firestore.SERVER_TIMESTAMP}, merge=True)
        db.collection('daily_snapshots').document(date_str).collection('months').document(str(month)).set({
            'json_data': df.to_json(orient='records'), 'sob_data': sob, 'updated_at': firestore.SERVER_TIMESTAMP
        })
        return True
    except: return False

# ==============================================================================
# [3] 메인 화면 UI 및 사이드바 (지배인님 데이터 필드 맞춤형 최종본)
# ==============================================================================
st.sidebar.header("⚙️ Settings")
report_date = st.sidebar.date_input("기준 일자", datetime.now())
compare_date = st.sidebar.date_input("비교 일자", report_date - timedelta(days=1))
admin_key = st.sidebar.text_input("Admin Key", type="password")

if admin_key == "master136":
    st.session_state["authenticated"] = True

selected_page = "Main Report"
if st.session_state.get("authenticated"):
    st.sidebar.success("✅ Admin Mode On")
    selected_page = st.sidebar.radio("Navigation", ["Main Report", "🎯 Forecasting"])
    
    st.sidebar.markdown("---")
    
    # 과거 패턴 데이터가 없을 때만 분석 UI 표시
    if "historical_dow" not in st.session_state:
        st.sidebar.warning("⏳ 과거 패턴 분석이 필요합니다.")
        
        if st.sidebar.button("📊 4만건 히스토리 전체 분석 시작"):
            with st.sidebar.status("데이터 고속 도로 개통 중...", expanded=True) as status:
                try:
                    st.write("📡 파이어베이스 서버에 접속 중...")
                    db = firestore.client()
                    
                    # 1. 데이터 수집 (확인된 컬렉션명: hotel_booking)
                    # 만약 DB 이름이 hotel_bookings라면 아래 문구에서 s만 붙여주세요.
                    st.write("🔎 'hotel_booking' 데이터를 수색합니다...")
                    docs = db.collection_group("hotel_booking").stream()
                    
                    hist_data = []
                    count = 0
                    status_placeholder = st.empty()
                    
                    for doc in docs:
                        hist_data.append(doc.to_dict())
                        count += 1
                        if count % 2000 == 0:
                            status_placeholder.write(f"📥 현재 {count:,}건 로드 중...")
                    
                    # 2. 지배인님 데이터 맞춤형 지표 계산
                    if count > 0:
                        st.write(f"✅ 총 {count:,}건 수신 완료! 지표 계산 시작...")
                        h_df = pd.DataFrame(hist_data)
                        
                        # [핵심] 한글 필드 '예약일자'를 찾아 날짜로 변환
                        target_date_col = '예약일자' 
                        if target_date_col in h_df.columns:
                            st.write(f"📈 '{target_date_col}' 필드 분석 중...")
                            h_df['b_date'] = pd.to_datetime(h_df[target_date_col], errors='coerce')
                            h_df = h_df.dropna(subset=['b_date'])
                            h_df['dow'] = h_df['b_date'].dt.dayofweek
                            
                            # 요일 지수 세션 저장 (미래 예측의 핵심 엔진)
                            st.session_state["historical_dow"] = (h_df['dow'].value_counts(normalize=True) * 7).to_dict()
                            
                            # 재방문율 계산 (확인된 필드: '휴대폰')
                            if '휴대폰' in h_df.columns:
                                st.session_state["repeat_rate"] = (h_df['휴대폰'].value_counts() > 1).mean() * 100
                            
                            status.update(label=f"✅ {count:,}건 분석 완료!", state="complete")
                            st.sidebar.success(f"📊 {count:,}건의 패턴이 반영되었습니다.")
                            
                            # 결과 반영을 위해 즉시 앱 재실행
                            st.rerun()
                        else:
                            # 필드를 못 찾았을 때를 위한 디버깅용 정보 출력
                            st.error(f"❌ '{target_date_col}' 필드를 찾지 못했습니다.")
                            st.write("실제 데이터 필드명:", h_df.columns.tolist())
                    else:
                        st.error("⚠️ 데이터를 수집하지 못했습니다. 컬렉션명을 확인해주세요.")

                except Exception as e:
                    st.error(f"❌ 연결 실패 원인: {str(e)}")
                    st.info("💡 팁: 서비스 계정 권한 또는 네트워크를 확인하세요.")
    else:
        # 분석이 완료된 상태
        st.sidebar.success("✅ 과거 패턴 분석 완료")
        # 요일 지수가 잘 들어갔는지 시각적 피드백 (선택사항)
        if "historical_dow" in st.session_state:
            st.sidebar.info("📅 요일별 가중치 적용 중")
            
        if st.sidebar.button("🔄 데이터 다시 분석"):
            if "historical_dow" in st.session_state:
                del st.session_state["historical_dow"]
            st.rerun()

if selected_page == "🎯 Forecasting":
    secret_forecasting.run_forecasting()
    st.stop()

st.title("🏨 Daily Pace Report")
uploaded_files = st.file_uploader("엑셀 업로드", accept_multiple_files=True, type=['xlsx'])

tabs = st.tabs([f"{i}월" for i in range(1, 13)])
month_files_map = {i: [] for i in range(1, 13)}
if uploaded_files:
    for f in uploaded_files:
        df, m, sob = find_header_and_process(f)
        if m: month_files_map[m].append({'name': f.name, 'data': df, 'sob': sob})

# ==============================================================================
# [4] 탭별 데이터 렌더링 (메인 로직)
# ==============================================================================
for i, tab in enumerate(tabs):
    cur_m = i + 1
    with tab:
        files = month_files_map.get(cur_m, [])
        df_curr, sob_curr, df_prev = None, None, None
        
        if files:
            files.sort(key=lambda x: x['name'])
            if len(files) >= 2:
                df_curr, sob_curr, df_prev = files[-1]['data'], files[-1]['sob'], files[-2]['data']
            else:
                df_curr, sob_curr = files[0]['data'], files[0]['sob']
                df_prev, _ = get_full_data_by_date(compare_date.strftime("%Y-%m-%d"), cur_m)
        else:
            df_curr, sob_curr = get_full_data_by_date(report_date.strftime("%Y-%m-%d"), cur_m)
            if df_curr is not None: df_prev, _ = get_full_data_by_date(compare_date.strftime("%Y-%m-%d"), cur_m)

        if df_curr is None:
            st.info(f"{cur_m}월 데이터를 업로드하거나 조회하세요.")
            continue

        # S.O.B 대시보드 계산 및 출력
        budget = BUDGET_DATA.get(cur_m, 0)
        total_rev = sob_curr['FIT_REV'] + sob_curr['GRP_REV']
        total_rms = sob_curr['FIT_RMS'] + sob_curr['GRP_RMS']
        
        # HTML S.O.B 대시보드 렌더링
        st.markdown(f"""
        <div class="sob-container">
            <div class="sob-header">📊 {cur_m}월 Performance Summary</div>
            <div class="sob-grid">
                <div>
                    <table class="modern-table">
                        <tr><td class="label">Budget</td><td>{budget:,.0f}</td></tr>
                        <tr><td class="label">Actual</td><td style="font-weight:bold;">{total_rev:,.0f}</td></tr>
                        <tr><td class="label">Variance</td><td style="color:{'green' if total_rev>=budget else 'red'}">{total_rev-budget:+,.0f}</td></tr>
                    </table>
                    <div class="kpi-wrapper">
                        <div class="kpi-card"><div class="kpi-title">OCC</div><div class="kpi-value">{sob_curr['TOTAL_OCC']:.1f}%</div></div>
                        <div class="kpi-card kpi-accent"><div class="kpi-title">ACHIEVEMENT</div><div class="kpi-value">{(total_rev/budget*100):.1f}%</div></div>
                    </div>
                </div>
                <div>
                    <table class="modern-table">
                        <thead><tr><th>Segment</th><th>RMS</th><th>ADR</th><th>REV</th></tr></thead>
                        <tr><td class="label">FIT</td><td>{sob_curr['FIT_RMS']:,.0f}</td><td>{(sob_curr['FIT_REV']/max(1,sob_curr['FIT_RMS'])):,.0f}</td><td>{sob_curr['FIT_REV']:,.0f}</td></tr>
                        <tr><td class="label">GROUP</td><td>{sob_curr['GRP_RMS']:,.0f}</td><td>{(sob_curr['GRP_REV']/max(1,sob_curr['GRP_RMS'])):,.0f}</td><td>{sob_curr['GRP_REV']:,.0f}</td></tr>
                        <tr style="background:#eff6ff; font-weight:bold;"><td>TOTAL</td><td>{total_rms:,.0f}</td><td>{(total_rev/max(1,total_rms)):,.0f}</td><td>{total_rev:,.0f}</td></tr>
                    </table>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

# ----------------------------------------------------------------------
        # [B] 상세 리포트 데이터 병합 (어제 vs 오늘)
        # ----------------------------------------------------------------------
        merged = df_curr.copy()
        if df_prev is not None:
            df_prev_sub = df_prev[['DateStr', 'HU', 'Comp', 'RMS', 'OCC', 'ADR', 'RevPAR', 'REV']]
            merged = pd.merge(merged, df_prev_sub, on='DateStr', how='left', suffixes=('', '_prev'))
        else:
            # 비교 데이터가 없을 경우 현재 데이터를 기본값으로 설정
            for c in ['HU', 'Comp', 'RMS', 'OCC', 'ADR', 'RevPAR', 'REV']: 
                merged[f'{c}_prev'] = merged[c]

        # 변화량(PickUp) 계산
        for c in ['HU', 'Comp', 'RMS', 'OCC', 'ADR', 'RevPAR', 'REV']: 
            merged[f'Pick_{c}'] = merged[c] - merged[f'{c}_prev']

        # 합계(TOTAL) 행 추가 계산
        sum_items = ['HU', 'Comp', 'RMS', 'REV', 'HU_prev', 'Comp_prev', 'RMS_prev', 'REV_prev', 'Pick_HU', 'Pick_Comp', 'Pick_RMS', 'Pick_REV']
        totals = merged[sum_items].sum()
        
        # 비율 지표 가중평균 재계산 (TOTAL 행용)
        def get_total_rates(prefix_rms, prefix_rev, is_curr=True):
            s_rms = totals[prefix_rms]
            s_rev = totals[prefix_rev]
            # 전체 가용객실수 역산 (RMS / (OCC/100))
            if is_curr:
                avail = (merged['RMS'] / (merged['OCC'].replace(0, np.nan) / 100)).fillna(0).sum()
            else:
                avail = (merged['RMS_prev'] / (merged['OCC_prev'].replace(0, np.nan) / 100)).fillna(0).sum()
            t_occ = (s_rms / avail * 100) if avail > 0 else 0
            t_adr = (s_rev / s_rms) if s_rms > 0 else 0
            t_par = (s_rev / avail) if avail > 0 else 0
            return t_occ, t_adr, t_par

        c_occ, c_adr, c_par = get_total_rates('RMS', 'REV', True)
        p_occ, p_adr, p_par = get_total_rates('RMS_prev', 'REV_prev', False)

        total_row = pd.DataFrame([{
            'DateStr': 'TOTAL', 'WeekDay': '',
            'HU_prev': totals['HU_prev'], 'Comp_prev': totals['Comp_prev'], 'RMS_prev': totals['RMS_prev'], 
            'OCC_prev': p_occ, 'ADR_prev': p_adr, 'RevPAR_prev': p_par, 'REV_prev': totals['REV_prev'],
            'HU': totals['HU'], 'Comp': totals['Comp'], 'RMS': totals['RMS'], 
            'OCC': c_occ, 'ADR': c_adr, 'RevPAR': c_par, 'REV': totals['REV'],
            'Pick_HU': totals['Pick_HU'], 'Pick_Comp': totals['Pick_Comp'], 'Pick_RMS': totals['Pick_RMS'], 
            'Pick_OCC': c_occ - p_occ, 'Pick_ADR': c_adr - p_adr, 'Pick_RevPAR': c_par - p_par, 'Pick_REV': totals['Pick_REV']
        }])
        
        merged = pd.concat([merged, total_row], ignore_index=True)

        # ----------------------------------------------------------------------
        # [C] Forecasting 연동 데이터 저장
        # ----------------------------------------------------------------------
        st.session_state[f"sob_{cur_m}"] = sob_curr
        # 실시간 픽업량(17박 등)을 세션에 전달
        st.session_state[f"pace_{cur_m}"] = totals['Pick_RMS']

        # ----------------------------------------------------------------------
        # [D] 테이블 스타일링 (히트맵/색상 로직 복구)
        # ----------------------------------------------------------------------
        final_df = merged[['DateStr', 'WeekDay', 
                           'HU_prev', 'Comp_prev', 'RMS_prev', 'OCC_prev', 'ADR_prev', 'RevPAR_prev', 'REV_prev',
                           'HU', 'Comp', 'RMS', 'OCC', 'ADR', 'RevPAR', 'REV',
                           'Pick_HU', 'Pick_Comp', 'Pick_RMS', 'Pick_OCC', 'Pick_ADR', 'Pick_RevPAR', 'Pick_REV']]

        # 헤더 이름 변경 (줄바꿈 포함)
        col_map = {'DateStr':'Date', 'WeekDay':'Day'}
        items = ['HU', 'Comp', 'RMS', 'OCC', 'ADR', 'RevPAR', 'REV']
        for it in items:
            col_map[f'{it}_prev'] = f'Pre\n{it}'
            col_map[it] = f'Today\n{it}'
            col_map[f'Pick_{it}'] = f'Var\n{it}'
        final_df.columns = [col_map.get(c, c) for c in final_df.columns]

        # 숫자 포맷 설정
        fmt = {c: '{:,.0f}' for c in final_df.columns if 'OCC' not in c and 'Date' not in c and 'Day' not in c}
        for c in [c for c in final_df.columns if 'OCC' in c]: fmt[c] = '{:.1f}%'

        styler = final_df.style.format(fmt)

        # 1. Pre(어제) 그룹 - 회색 파스텔 스타일
        pre_cols = [c for c in final_df.columns if 'Pre' in c]
        styler = styler.set_properties(subset=pre_cols, **{'background-color': '#f8f9fa', 'color': '#9ca3af'})

        # 2. Today(오늘) 그룹 - 블루/오렌지 히트맵
        curr_cols = [c for c in final_df.columns if 'Today' in c]
        data_idx = final_df.index[:-1] # TOTAL 제외
        styler = styler.background_gradient(cmap='Blues', subset=pd.IndexSlice[data_idx, [c for c in curr_cols if 'OCC' not in c]], low=0.2, high=0.6)
        styler = styler.background_gradient(cmap='Oranges', subset=pd.IndexSlice[data_idx, [c for c in curr_cols if 'OCC' in c]], low=0.4, high=0.7)

        # 3. Var(변화) 그룹 - 색상 텍스트 (양수 초록 / 음수 빨강)
        var_cols = [c for c in final_df.columns if 'Var' in c]
        def color_pick(val):
            try:
                v = float(str(val).replace('%','').replace(',',''))
                return 'color: #166534; font-weight: bold;' if v > 0 else 'color: #dc2626; font-weight: bold;' if v < 0 else 'color: #374151;'
            except: return ''
        styler = styler.map(color_pick, subset=var_cols)
        styler = styler.set_properties(subset=var_cols, **{'background-color': '#fffbeb'})

        # 4. TOTAL 행 하이라이트
        styler = styler.set_properties(subset=pd.IndexSlice[final_df.index[-1], :], 
                                      **{'background-color': '#eff6ff', 'font-weight': '900', 'border-top': '2px solid #1d4ed8'})

        # 출력
        st.markdown(f'<div class="compact-table-wrapper">{styler.to_html()}</div>', unsafe_allow_html=True)

        # 저장 버튼
        if uploaded_files and st.button(f"💾 {cur_m}월 데이터 DB 저장", key=f"btn_{cur_m}"):
            if save_data_with_sob(report_date.strftime("%Y-%m-%d"), cur_m, df_curr, sob_curr):
                st.toast(f"✅ {cur_m}월 데이터가 안전하게 저장되었습니다.")
