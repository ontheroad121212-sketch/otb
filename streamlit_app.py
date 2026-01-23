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
# [1] 페이지 기본 설정 및 CSS 스타일링 (컴팩트 모드 완벽 유지)
# ==============================================================================
st.set_page_config(layout="wide", page_title="Daily Pace Report", initial_sidebar_state="expanded")

st.markdown(textwrap.dedent("""
<style>
    .block-container { padding-top: 0.5rem; padding-bottom: 2rem; }
    .sob-container {
        background-color: white; border-radius: 15px;
        box-shadow: 0 4px 20px rgba(0,0,0,0.08); padding: 30px;
        margin-bottom: 30px; border: 1px solid #e5e7eb;
    }
    .sob-header { font-size: 24px; font-weight: 900; color: #111827; margin-bottom: 25px; border-bottom: 3px solid #f3f4f6; padding-bottom: 15px; }
    .sob-grid { display: grid; grid-template-columns: 1fr 1.3fr; gap: 50px; }
    .modern-table { width: 100%; border-collapse: collapse; }
    .modern-table th { text-align: right; color: #4b5563; font-size: 14px; font-weight: 700; padding: 12px 10px; border-bottom: 2px solid #e5e7eb; background-color: #f9fafb; }
    .modern-table td { padding: 14px 10px; font-size: 16px; text-align: right; border-bottom: 1px solid #f3f4f6; }
    .kpi-card { flex: 1; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; padding: 20px; text-align: center; }
    .kpi-accent { background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%); color: white; }
    .compact-table-wrapper { overflow-x: auto; margin-bottom: 50px; border: 1px solid #e5e7eb; }
    .compact-table-wrapper table { width: 100%; border-collapse: collapse; font-size: 10px !important; }
    .compact-table-wrapper th { background-color: #f8fafc; padding: 5px 3px !important; border: 1px solid #e2e8f0; font-size: 10px !important; line-height: 1.2; text-align: center; }
    .compact-table-wrapper td { padding: 4px 3px !important; border: 1px solid #e2e8f0; font-size: 10px !important; text-align: right; }
</style>
"""), unsafe_allow_html=True)

# ==============================================================================
# [2] Firebase 연결 및 데이터 처리 함수
# ==============================================================================
if not firebase_admin._apps:
    try:
        key_dict = dict(st.secrets["firebase"])
        cred = credentials.Certificate(key_dict)
        firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"🔥 Firebase 연결 실패: {e}"); st.stop()

db = firestore.client()
BUDGET_DATA = {1:514992575, 2:786570856, 3:529599040, 4:695351004, 5:903705440, 6:808203820,
               7:1231949142, 8:1388376999, 9:952171506, 10:897171539, 11:667146771, 12:804030110}

def find_header_and_process(file):
    try:
        file.seek(0); df_raw = pd.read_excel(file, header=None)
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
        
        sob_data = {'FIT_RMS': int(safe_num(rms_indices[0]).sum()), 'FIT_REV': int(safe_num(rev_indices[0]).sum()),
                    'GRP_RMS': int(safe_num(rms_indices[1]).sum()), 'GRP_REV': int(safe_num(rev_indices[1]).sum())}
        
        df_clean = pd.DataFrame({'Date': df_data['Date'], 'DateStr': df_data['Date'].dt.strftime('%Y-%m-%d'), 'WeekDay': df_data['Date'].dt.strftime('%a')})
        base_idx = rms_indices[-1]
        df_clean['RMS'], df_clean['OCC'], df_clean['ADR'] = safe_num(base_idx), safe_num(base_idx+1), safe_num(base_idx+2)
        df_clean['RevPAR'], df_clean['REV'] = safe_num(base_idx+3), safe_num(base_idx+4)
        df_clean['HU'], df_clean['Comp'] = safe_num(base_idx-2), safe_num(base_idx-1)
        
        sob_data['TOTAL_OCC'] = float(df_clean['RMS'].sum() / (df_clean['RMS']/(df_clean['OCC'].replace(0,1)/100)).sum() * 100)
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

# ==============================================================================
# [3] 사이드바 및 4만 건 분석 로직 (Collection Group 수색 완벽 복구)
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
    
    if "historical_dow" not in st.session_state:
        if st.sidebar.button("📊 4만건 히스토리 전체 분석 시작"):
            with st.sidebar.status("데이터 고속도로 개통 중...", expanded=True) as status:
                docs = db.collection_group("hotel_booking").stream()
                hist_data, count = [], 0
                placeholder = st.empty()
                for doc in docs:
                    hist_data.append(doc.to_dict()); count += 1
                    if count % 2000 == 0: placeholder.write(f"📥 {count:,}건 로드 중...")
                if count > 0:
                    h_df = pd.DataFrame(hist_data)
                    bd_col = next((c for c in h_df.columns if c.lower() in ['booking_date', 'created_at', 'date']), None)
                    if bd_col:
                        h_df['b_date'] = pd.to_datetime(h_df[bd_col], errors='coerce')
                        h_df = h_df.dropna(subset=['b_date'])
                        st.session_state["historical_dow"] = (h_df['b_date'].dt.dayofweek.value_counts(normalize=True) * 7).to_dict()
                    status.update(label="✅ 분석 완료!", state="complete"); st.rerun()
                else: st.error("데이터 0건 확인됨.")

if selected_page == "🎯 Forecasting":
    secret_forecasting.run_forecasting(); st.stop()

# ==============================================================================
# [4] 메인 리포트 & 데이터 병합 (지배인님 수식 100% 복구)
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
                df_prev, _ = get_full_data_by_date(compare_date.strftime("%Y-%m-%d"), cur_m)
        else:
            df_curr, sob_curr = get_full_data_by_date(report_date.strftime("%Y-%m-%d"), cur_m)
            if df_curr is not None: df_prev, _ = get_full_data_by_date(compare_date.strftime("%Y-%m-%d"), cur_m)

        if df_curr is None: st.info(f"{cur_m}월 데이터를 업로드하세요."); continue

        # S.O.B 대시보드 출력
        budget = BUDGET_DATA.get(cur_m, 0); total_rev = sob_curr['FIT_REV'] + sob_curr['GRP_REV']
        total_rms = sob_curr['FIT_RMS'] + sob_curr['GRP_RMS']
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

        # 데이터 병합 및 TOTAL 행 가중평균 계산
        merged = df_curr.copy()
        for c in ['HU', 'Comp', 'RMS', 'OCC', 'ADR', 'RevPAR', 'REV']:
            merged[f'{c}_prev'] = df_prev[c] if df_prev is not None else merged[c]
            merged[f'Pick_{c}'] = merged[c] - merged[f'{c}_prev']

        # TOTAL 행 생성 (가중평균 적용)
        sum_items = ['HU', 'Comp', 'RMS', 'REV', 'HU_prev', 'Comp_prev', 'RMS_prev', 'REV_prev', 'Pick_HU', 'Pick_Comp', 'Pick_RMS', 'Pick_REV']
        totals = merged[sum_items].sum()
        def get_t(r, v, is_c):
            s_r, s_v = totals[r], totals[v]
            avail = (merged['RMS']/(merged['OCC'].replace(0,1)/100)).sum() if is_c else (merged['RMS_prev']/(merged['OCC_prev'].replace(0,1)/100)).sum()
            return (s_r/avail*100), (s_v/s_r if s_r else 0), (s_v/avail)
        c_o, c_a, c_p = get_t('RMS', 'REV', True); p_o, p_a, p_p = get_t('RMS_prev', 'REV_prev', False)
        
        t_row = pd.DataFrame([{'DateStr':'TOTAL', 'WeekDay':'', 'RMS':totals['RMS'], 'REV':totals['REV'], 'OCC':c_o, 'ADR':c_a, 'RevPAR':c_p, 'RMS_prev':totals['RMS_prev'], 'OCC_prev':p_o, 'ADR_prev':p_a, 'REV_prev':totals['REV_prev'], 'Pick_RMS':totals['Pick_RMS'], 'Pick_REV':totals['Pick_REV'], 'Pick_OCC':c_o-p_o}])
        merged = pd.concat([merged, t_row], ignore_index=True)

        # 포캐스팅 세션 전송
        st.session_state[f"sob_{cur_m}"] = sob_curr
        st.session_state[f"pace_{cur_m}"] = totals['Pick_RMS']

        # 테이블 시각화 (히트맵/색상 로직 완벽 복구)
        items = ['HU', 'Comp', 'RMS', 'OCC', 'ADR', 'RevPAR', 'REV']
        final_cols = ['DateStr', 'WeekDay'] + [f'{c}_prev' for c in items] + items + [f'Pick_{c}' for c in items]
        final_df = merged.reindex(columns=final_cols).fillna(0)
        
        # 헤더 맵핑
        header_map = {'DateStr':'Date', 'WeekDay':'Day'}
        for c in items: header_map[f'{c}_prev'] = f'Pre\n{c}'; header_map[c] = f'Today\n{c}'; header_map[f'Pick_{c}'] = f'Var\n{c}'
        final_df.columns = [header_map.get(c, c) for c in final_df.columns]

        # 스타일링
        fmt = {c: '{:,.0f}' for c in final_df.columns if 'OCC' not in c and 'Date' not in c and 'Day' not in c}
        for c in [c for c in final_df.columns if 'OCC' in c]: fmt[c] = '{:.1f}%'
        
        styler = final_df.style.format(fmt)
        styler = styler.set_properties(subset=[c for c in final_df.columns if 'Pre' in c], **{'background-color': '#f8f9fa', 'color': '#9ca3af'})
        styler = styler.background_gradient(cmap='Blues', subset=[c for c in final_df.columns if 'Today' in c and 'OCC' not in c])
        styler = styler.background_gradient(cmap='Oranges', subset=[c for c in final_df.columns if 'Today\nOCC' in c])
        
        def color_pick(val):
            try:
                v = float(str(val).replace('%','').replace(',',''))
                return 'color: #166534; font-weight: bold;' if v > 0 else 'color: #dc2626; font-weight: bold;' if v < 0 else ''
            except: return ''
        styler = styler.map(color_pick, subset=[c for c in final_df.columns if 'Var' in c])
        styler = styler.set_properties(subset=pd.IndexSlice[final_df.index[-1], :], **{'background-color': '#eff6ff', 'font-weight': '900', 'border-top': '2px solid #1d4ed8'})

        st.markdown(f'<div class="compact-table-wrapper">{styler.to_html()}</div>', unsafe_allow_html=True)
        if st.button(f"💾 {cur_m}월 저장", key=f"s_{cur_m}"):
            st.toast("저장 기능은 find_header_and_process 결과에 따라 save_data_with_sob를 호출하세요.")
