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
    .modern-table { width: 100%; border-collapse: collapse; }
    .modern-table th { 
        text-align: right; color: #4b5563; font-size: 14px; font-weight: 700;
        padding: 12px 10px; border-bottom: 2px solid #e5e7eb; background-color: #f9fafb;
    }
    .modern-table td { padding: 14px 10px; font-size: 16px; text-align: right; border-bottom: 1px solid #f3f4f6; }
    .modern-table td.label { text-align: left; font-weight: 700; }
    .kpi-wrapper { display: flex; gap: 20px; margin-top: 25px; }
    .kpi-card { flex: 1; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; padding: 20px; text-align: center; }
    .kpi-title { font-size: 14px; color: #64748b; font-weight: 800; }
    .kpi-value { font-size: 32px; color: #0f172a; font-weight: 900; }
    .kpi-accent { background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%); color: white; }
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

BUDGET_DATA = {1:514992575, 2:786570856, 3:529599040, 4:695351004, 5:903705440, 6:808203820,
               7:1231949142, 8:1388376999, 9:952171506, 10:897171539, 11:667146771, 12:804030110}

def find_header_and_process(file):
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
# [3] 메인 실행 및 사이드바 로직
# ==============================================================================
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
    
    # 4만건 분석 로직 (Collection Group 활용)
    if "historical_dow" not in st.session_state:
        if st.sidebar.button("📊 4만건 히스토리 전체 분석 시작"):
            with st.sidebar.status("데이터 분석 중...", expanded=True) as status:
                try:
                    docs = db.collection_group("hotel_booking").stream()
                    hist_data, count = [], 0
                    placeholder = st.empty()
                    for doc in docs:
                        hist_data.append(doc.to_dict())
                        count += 1
                        if count % 2000 == 0: placeholder.write(f"📥 {count:,}건 로드 중...")
                    
                    if count > 0:
                        h_df = pd.DataFrame(hist_data)
                        bd_col = next((c for c in h_df.columns if c.lower() in ['booking_date', 'created_at', 'date']), None)
                        if bd_col:
                            h_df['b_date'] = pd.to_datetime(h_df[bd_col], errors='coerce')
                            h_df = h_df.dropna(subset=['b_date'])
                            st.session_state["historical_dow"] = (h_df['b_date'].dt.dayofweek.value_counts(normalize=True) * 7).to_dict()
                        status.update(label="✅ 분석 완료!", state="complete")
                        st.rerun()
                    else:
                        st.error("데이터를 찾을 수 없습니다.")
                except Exception as e: st.error(f"에러: {e}")

if selected_page == "🎯 Forecasting":
    secret_forecasting.run_forecasting()
    st.stop()

# ==============================================================================
# [4] 메인 리포트 렌더링
# ==============================================================================
st.title("🏨 Daily Pace Report")
uploaded_files = st.file_uploader("엑셀 업로드", accept_multiple_files=True, type=['xlsx'])

tabs = st.tabs([f"{i}월" for i in range(1, 13)])
month_files_map = {i: [] for i in range(1, 13)}

if uploaded_files:
    for f in uploaded_files:
        df, m, sob = find_header_and_process(f)
        if m: month_files_map[m].append({'name': f.name, 'data': df, 'sob': sob})

for i, tab in enumerate(tabs):
    cur_m = i + 1
    with tab:
        files = month_files_map.get(cur_m, [])
        df_curr, sob_curr, df_prev = None, None, None
        
        if files:
            files.sort(key=lambda x: x['name'])
            if len(files) >= 2: df_curr, sob_curr, df_prev = files[-1]['data'], files[-1]['sob'], files[-2]['data']
            else:
                df_curr, sob_curr = files[0]['data'], files[0]['sob']
                doc_p, _ = get_full_data_by_date(compare_date.strftime("%Y-%m-%d"), cur_m)
                df_prev = doc_p
        else:
            df_curr, sob_curr = get_full_data_by_date(report_date.strftime("%Y-%m-%d"), cur_m)
            if df_curr is not None: df_prev, _ = get_full_data_by_date(compare_date.strftime("%Y-%m-%d"), cur_m)

        if df_curr is None:
            st.info(f"{cur_m}월 데이터를 업로드하세요.")
            continue

        # S.O.B 대시보드
        budget = BUDGET_DATA.get(cur_m, 0)
        total_rev = sob_curr['FIT_REV'] + sob_curr['GRP_REV']
        total_rms = sob_curr['FIT_RMS'] + sob_curr['GRP_RMS']
        
        st.markdown(textwrap.dedent(f"""
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
        """), unsafe_allow_html=True)

        # 데이터 병합 및 스타일링 (히트맵 포함)
        merged = df_curr.copy()
        for c in ['HU', 'Comp', 'RMS', 'OCC', 'ADR', 'RevPAR', 'REV']:
            merged[f'{c}_prev'] = df_prev[c] if df_prev is not None else merged[c]
            merged[f'Pick_{c}'] = merged[c] - merged[f'{c}_prev']

        # Forecasting 데이터 연동
        st.session_state[f"sob_{cur_m}"] = sob_curr
        st.session_state[f"pace_{cur_m}"] = merged['Pick_RMS'].sum()

        # 테이블 렌더링 (줄바꿈 헤더 및 스타일링)
        final_df = merged[['DateStr', 'WeekDay', 'HU_prev', 'Comp_prev', 'RMS_prev', 'OCC_prev', 'ADR_prev', 'RevPAR_prev', 'REV_prev',
                           'HU', 'Comp', 'RMS', 'OCC', 'ADR', 'RevPAR', 'REV',
                           'Pick_HU', 'Pick_Comp', 'Pick_RMS', 'Pick_OCC', 'Pick_ADR', 'Pick_RevPAR', 'Pick_REV']]
        
        # 컬럼명 맵핑
        new_cols = ['Date', 'Day'] + [f'Pre\n{c}' for c in ['HU', 'Comp', 'RMS', 'OCC', 'ADR', 'RevPAR', 'REV']] + \
                   [f'Today\n{c}' for c in ['HU', 'Comp', 'RMS', 'OCC', 'ADR', 'RevPAR', 'REV']] + \
                   [f'Var\n{c}' for c in ['HU', 'Comp', 'RMS', 'OCC', 'ADR', 'RevPAR', 'REV']]
        final_df.columns = new_cols

        styler = final_df.style.format({c: '{:,.0f}' for c in final_df.columns if 'OCC' not in c and 'Date' not in c and 'Day' not in c})
        for c in [c for c in final_df.columns if 'OCC' in c]: styler = styler.format({c: '{:.1f}%'})
        
        # 히트맵 적용 (오늘 실적 구역)
        curr_cols = [c for c in final_df.columns if 'Today' in c]
        styler = styler.background_gradient(cmap='Blues', subset=curr_cols)
        
        st.markdown(f'<div class="compact-table-wrapper">{styler.to_html()}</div>', unsafe_allow_html=True)

        if uploaded_files and st.button(f"💾 {cur_m}월 저장", key=f"btn_{cur_m}"):
            if save_data_with_sob(report_date.strftime("%Y-%m-%d"), cur_m, df_curr, sob_curr):
                st.toast("저장 완료!")
