import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timedelta
import io
import numpy as np
import textwrap

# ------------------------------------------------------------------
# 1. 페이지 설정 및 CSS
# ------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Daily Pace Report")

st.markdown(textwrap.dedent("""
<style>
    .block-container { padding-top: 1rem; padding-bottom: 3rem; padding-left: 1rem; padding-right: 1rem; }
    
    /* S.O.B 카드 */
    .sob-container {
        background-color: white; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.05);
        padding: 25px; margin-bottom: 25px; border: 1px solid #e0e0e0;
    }
    .sob-header {
        font-size: 20px; font-weight: 800; color: #111827; margin-bottom: 20px;
        border-bottom: 2px solid #f3f4f6; padding-bottom: 10px;
    }
    .sob-grid { display: grid; grid-template-columns: 1fr 1.3fr; gap: 40px; }
    
    /* 테이블 */
    .modern-table { width: 100%; border-collapse: collapse; font-family: 'Segoe UI', sans-serif; }
    .modern-table th {
        text-align: right; color: #6b7280; font-size: 13px; font-weight: 600;
        padding: 10px 8px; border-bottom: 2px solid #e5e7eb; background-color: #f9fafb;
    }
    .modern-table th:first-child { text-align: left; }
    .modern-table td {
        padding: 12px 8px; font-size: 15px; color: #1f2937; text-align: right;
        border-bottom: 1px solid #f3f4f6;
    }
    .modern-table td.label { text-align: left; font-weight: 600; color: #374151; }
    
    /* 강조 */
    .highlight-row td { background-color: #f0fdf4; font-weight: 700; color: #166534; }
    .highlight-row td.negative { background-color: #fef2f2; color: #991b1b; }
    .total-row td { background-color: #eff6ff; font-weight: 800; color: #1e40af; border-top: 2px solid #bfdbfe; }

    /* KPI */
    .kpi-wrapper { display: flex; gap: 15px; margin-top: 20px; }
    .kpi-card {
        flex: 1; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px;
        padding: 20px; text-align: center;
    }
    .kpi-title { font-size: 12px; color: #64748b; font-weight: 700; margin-bottom: 5px; }
    .kpi-value { font-size: 28px; color: #0f172a; font-weight: 900; }
    .kpi-accent { background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%); }
    .kpi-accent .kpi-title { color: rgba(255,255,255,0.8); }
    .kpi-accent .kpi-value { color: white; }
    
    .text-red { color: #dc2626; font-weight: 700; }
    .text-green { color: #059669; font-weight: 700; }

    iframe[title="streamlit.dataframe"] { width: 100% !important; }
</style>
"""), unsafe_allow_html=True)

# ------------------------------------------------------------------
# 2. Firebase 연결
# ------------------------------------------------------------------
if not firebase_admin._apps:
    try:
        key_dict = dict(st.secrets["firebase"])
        cred = credentials.Certificate(key_dict)
        firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"Firebase 연결 오류: {e}")
        st.stop()

db = firestore.client()

# ------------------------------------------------------------------
# 3. 데이터 로직
# ------------------------------------------------------------------
BUDGET_DATA = { 1: 514992575, 2: 480000000, 3: 520000000, 4: 600000000 }

def find_header_and_process(file):
    try:
        file.seek(0)
        df_preview = pd.read_excel(file, header=None, nrows=10)
        header_row_idx = None
        rms_indices, rev_indices = [], []
        
        for idx, row in df_preview.iterrows():
            row_str = row.astype(str).values
            if np.any(['객실수' in s for s in row_str]) and np.any(['매출' in s for s in row_str]):
                header_row_idx = idx
                rms_indices = [i for i, val in enumerate(row_str) if '객실수' in str(val)]
                rev_indices = [i for i, val in enumerate(row_str) if '매출' in str(val)]
                break
        
        if header_row_idx is None: return None, None, None

        df_raw = pd.read_excel(file, header=None)
        start_row = header_row_idx + 1 
        df_data = df_raw.iloc[start_row:].copy()
        df_data['Date'] = pd.to_datetime(df_data.iloc[:, 0], errors='coerce')
        df_data = df_data.dropna(subset=['Date']) 

        def safe_num(col_idx):
            if col_idx >= df_data.shape[1]: return 0
            return pd.to_numeric(df_data.iloc[:, col_idx], errors='coerce').fillna(0)

        if len(rms_indices) >= 3 and len(rev_indices) >= 3:
            fit_rms_idx, grp_rms_idx, total_rms_idx = rms_indices[0], rms_indices[1], rms_indices[-1]
            fit_rev_idx, grp_rev_idx, total_rev_idx = rev_indices[0], rev_indices[1], rev_indices[-1]
        else:
            fit_rms_idx, grp_rms_idx, total_rms_idx = 1, 6, 13
            fit_rev_idx, grp_rev_idx, total_rev_idx = 4, 9, 17
            
        df_clean = pd.DataFrame()
        df_clean['Date'] = df_data['Date']
        df_clean['DateStr'] = df_clean['Date'].dt.strftime('%Y-%m-%d')
        df_clean['WeekDay'] = df_clean['Date'].dt.strftime('%a')
        
        base_idx = total_rms_idx 
        df_clean['RMS'] = safe_num(base_idx)
        df_clean['OCC'] = safe_num(base_idx + 1)
        df_clean['ADR'] = safe_num(base_idx + 2)
        df_clean['RevPAR'] = safe_num(base_idx + 3)
        df_clean['REV'] = safe_num(base_idx + 4)
        df_clean['HU'] = safe_num(base_idx - 2)
        df_clean['Comp'] = safe_num(base_idx - 1)

        fit_rms_sum = safe_num(fit_rms_idx).sum()
        fit_rev_sum = safe_num(fit_rev_idx).sum()
        grp_rms_sum = safe_num(grp_rms_idx).sum()
        grp_rev_sum = safe_num(grp_rev_idx).sum()
        
        avail_daily = df_clean['RMS'] / (df_clean['OCC'].replace(0, np.nan) / 100)
        total_avail = avail_daily.fillna(0).sum()
        total_rms = df_clean['RMS'].sum()
        total_occ_pct = (total_rms / total_avail * 100) if total_avail > 0 else 0

        sob_data = {
            'FIT_RMS': fit_rms_sum, 'FIT_REV': fit_rev_sum,
            'GRP_RMS': grp_rms_sum, 'GRP_REV': grp_rev_sum,
            'TOTAL_OCC': total_occ_pct
        }
        
        return df_clean, df_data['Date'].iloc[0].month, sob_data
    except Exception: return None, None, None

def get_data_by_date(target_date_str, month_num):
    try:
        doc_ref = db.collection('daily_snapshots').document(target_date_str)\
                    .collection('months').document(str(month_num))
        doc = doc_ref.get()
        if doc.exists:
            data = doc.to_dict()
            return pd.read_json(io.StringIO(data['json_data']), orient='records')
    except Exception: return None
    return None

# [중요] S.O.B 데이터도 DB에 같이 저장해야 함 (구조 변경)
def save_data_with_sob(target_date_str, month_num, df, sob_data):
    json_str = df.to_json(orient='records', date_format='iso')
    db.collection('daily_snapshots').document(target_date_str).set({'created_at': firestore.SERVER_TIMESTAMP}, merge=True)
    db.collection('daily_snapshots').document(target_date_str)\
      .collection('months').document(str(month_num))\
      .set({
          'json_data': json_str, 
          'sob_data': sob_data, # S.O.B 정보도 함께 저장
          'updated_at': firestore.SERVER_TIMESTAMP
      })

# DB에서 S.O.B 데이터까지 가져오는 함수
def get_full_data_by_date(target_date_str, month_num):
    try:
        doc_ref = db.collection('daily_snapshots').document(target_date_str)\
                    .collection('months').document(str(month_num))
        doc = doc_ref.get()
        if doc.exists:
            data = doc.to_dict()
            df = pd.read_json(io.StringIO(data['json_data']), orient='records')
            sob = data.get('sob_data', None)
            
            # 만약 예전 데이터라 sob_data가 없다면 df에서 역산
            if sob is None and not df.empty:
                # 임시 계산 (정확하진 않음, 가급적 새로 저장 권장)
                sob = {
                    'FIT_RMS': 0, 'FIT_REV': 0, 'GRP_RMS': 0, 'GRP_REV': 0, 
                    'TOTAL_OCC': df['OCC'].mean() 
                }
            return df, sob
    except Exception: return None, None
    return None, None

def render_sob_dashboard(current_month, budget, total_rev, vs_budget, achv_rate, total_occ, fit_rms, fit_adr, fit_rev, grp_rms, grp_adr, grp_rev, total_rms, total_adr):
    vs_class = "text-green" if vs_budget >= 0 else "text-red"
    achv_class = "text-green" if achv_rate >= 100 else "text-red"
    
    html = textwrap.dedent(f"""
    <div class="sob-container">
        <div class="sob-header">📊 {current_month}월 Performance Summary</div>
        <div class="sob-grid">
            <div>
                <table class="modern-table">
                    <thead><tr><th>Category</th><th>Amount</th><th>Status</th></tr></thead>
                    <tbody>
                        <tr><td class="label">Budget</td><td>{budget:,.0f}</td><td>-</td></tr>
                        <tr><td class="label">Actual</td><td style="font-weight:bold;">{total_rev:,.0f}</td><td>-</td></tr>
                        <tr><td class="label">Variance</td><td class="{vs_class}">{vs_budget:+,.0f}</td><td class="{achv_class}">Achv: {achv_rate:.1f}%</td></tr>
                    </tbody>
                </table>
                <div class="kpi-wrapper">
                    <div class="kpi-card"><div class="kpi-title">TOTAL OCC</div><div class="kpi-value">{total_occ:.1f}%</div></div>
                    <div class="kpi-card kpi-accent"><div class="kpi-title">ACHIEVEMENT</div><div class="kpi-value">{achv_rate:.1f}%</div></div>
                </div>
            </div>
            <div>
                <table class="modern-table">
                    <thead><tr><th>Segment</th><th>RMS</th><th>ADR</th><th>REV</th></tr></thead>
                    <tbody>
                        <tr><td class="label">FIT (개인)</td><td>{fit_rms:,.0f}</td><td>{fit_adr:,.0f}</td><td>{fit_rev:,.0f}</td></tr>
                        <tr><td class="label">GROUP (단체)</td><td>{grp_rms:,.0f}</td><td>{grp_adr:,.0f}</td><td>{grp_rev:,.0f}</td></tr>
                        <tr class="total-row"><td class="label">TOTAL</td><td>{total_rms:,.0f}</td><td>{total_adr:,.0f}</td><td>{total_rev:,.0f}</td></tr>
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    """)
    st.markdown(html, unsafe_allow_html=True)

# ------------------------------------------------------------------
# 4. 메인 UI
# ------------------------------------------------------------------
st.sidebar.header("⚙️ Report Settings")
report_date = st.sidebar.date_input("기준 일자 (오늘/조회일)", datetime.now())
report_date_str = report_date.strftime("%Y-%m-%d")

compare_date = st.sidebar.date_input("비교 일자 (어제/과거)", report_date - timedelta(days=1))
compare_date_str = compare_date.strftime("%Y-%m-%d")

st.title(f"🏨 Daily Pace Report")
st.caption(f"📅 **{report_date_str}** 데이터 조회 중 (비교: {compare_date_str})")

uploaded_files = st.file_uploader("오늘자 엑셀 파일 업로드 (파일이 없으면 저장된 데이터 조회)", accept_multiple_files=True, type=['xlsx'])

tabs = st.tabs(["1월", "2월", "3월", "4월"])
month_files_map = {1: [], 2: [], 3: [], 4: []}

# 1. 파일이 있으면 파일 처리
if uploaded_files:
    for file in uploaded_files:
        df, month, sob = find_header_and_process(file)
        if df is not None and month in month_files_map:
            month_files_map[month].append({'data': df, 'sob': sob})

for i, tab in enumerate(tabs):
    current_month = i + 1
    with tab:
        files = month_files_map.get(current_month, [])
        df_curr, df_prev, sob_curr = None, None, None
        data_source = "" # 데이터 출처 표시용

        # [로직 A] 파일이 업로드된 경우 -> 파일을 최우선으로 보여줌
        if files:
            if len(files) >= 2:
                # 파일 2개 비교
                f1, f2 = files[0], files[1]
                if f1['data']['REV'].sum() >= f2['data']['REV'].sum():
                    df_curr, df_prev, sob_curr = f1['data'], f2['data'], f1['sob']
                else:
                    df_curr, df_prev, sob_curr = f2['data'], f1['data'], f2['sob']
                data_source = "🔥 파일 간 비교"
            else:
                # 파일 1개 + DB(어제) 비교
                df_curr, sob_curr = files[0]['data'], files[0]['sob']
                # 비교 데이터는 DB에서 가져옴
                df_prev, _ = get_full_data_by_date(compare_date_str, current_month)
                data_source = f"📂 파일 업로드 (비교: {compare_date_str})"
        
        # [로직 B] 파일이 없는 경우 -> DB에서 '기준 일자' 데이터를 가져옴 (조회 모드)
        else:
            df_curr, sob_curr = get_full_data_by_date(report_date_str, current_month)
            if df_curr is not None:
                # 비교 데이터도 DB에서 가져옴
                df_prev, _ = get_full_data_by_date(compare_date_str, current_month)
                data_source = f"☁️ DB 조회 모드 ({report_date_str} vs {compare_date_str})"
            else:
                st.info(f"📂 {current_month}월 데이터가 없습니다. (파일을 업로드하거나 날짜를 확인하세요)")
                continue

        # --------------------------------------
        # 여기서부터 화면 렌더링 (파일이든 DB든 df_curr만 있으면 OK)
        # --------------------------------------
        st.caption(f"ℹ️ {data_source}")

        # S.O.B 대시보드
        budget = BUDGET_DATA.get(current_month, 0)
        
        # sob_curr가 없으면(옛날 DB 데이터라) df_curr에서 대충 계산
        if sob_curr is None and df_curr is not None:
             sob_curr = {
                'FIT_RMS': 0, 'FIT_REV': 0, 'GRP_RMS': 0, 'GRP_REV': 0,
                'TOTAL_OCC': df_curr['OCC'].mean() if not df_curr.empty else 0
             }

        render_sob_dashboard(
            current_month=current_month,
            budget=budget,
            total_rev=sob_curr['FIT_REV'] + sob_curr['GRP_REV'],
            vs_budget=(sob_curr['FIT_REV'] + sob_curr['GRP_REV']) - budget,
            achv_rate=((sob_curr['FIT_REV'] + sob_curr['GRP_REV']) / budget * 100) if budget > 0 else 0,
            total_occ=sob_curr['TOTAL_OCC'],
            fit_rms=sob_curr['FIT_RMS'],
            fit_adr=(sob_curr['FIT_REV'] / sob_curr['FIT_RMS']) if sob_curr['FIT_RMS'] else 0,
            fit_rev=sob_curr['FIT_REV'],
            grp_rms=sob_curr['GRP_RMS'],
            grp_adr=(sob_curr['GRP_REV'] / sob_curr['GRP_RMS']) if sob_curr['GRP_RMS'] else 0,
            grp_rev=sob_curr['GRP_REV'],
            total_rms=sob_curr['FIT_RMS'] + sob_curr['GRP_RMS'],
            total_adr=((sob_curr['FIT_REV'] + sob_curr['GRP_REV']) / (sob_curr['FIT_RMS'] + sob_curr['GRP_RMS'])) if (sob_curr['FIT_RMS'] + sob_curr['GRP_RMS']) else 0
        )

        # 상세 리포트
        cols_base = ['DateStr', 'WeekDay', 'HU', 'Comp', 'RMS', 'OCC', 'ADR', 'RevPAR', 'REV']
        cols_curr = ['Date', 'Day', 'Curr_HU', 'Curr_Comp', 'Curr_RMS', 'Curr_OCC', 'Curr_ADR', 'Curr_RevPAR', 'Curr_REV']
        
        display_df = df_curr[cols_base].copy()
        display_df.columns = cols_curr

        if df_prev is not None:
            if 'DateStr' not in df_prev.columns:
                df_prev['Date'] = pd.to_datetime(df_prev['Date'])
                df_prev['DateStr'] = df_prev['Date'].dt.strftime('%Y-%m-%d')
            prev_subset = df_prev[cols_base].copy()
            prev_subset.columns = ['DateStr', 'Day_p', 'HU_prev', 'Comp_prev', 'RMS_prev', 'OCC_prev', 'ADR_prev', 'RevPAR_prev', 'REV_prev']
            prev_subset = prev_subset.drop(columns=['Day_p'])
            merged = pd.merge(display_df, prev_subset, left_on='Date', right_on='DateStr', how='left')
            for col in ['HU', 'Comp', 'RMS', 'OCC', 'ADR', 'RevPAR', 'REV']:
                merged[f'{col}_prev'] = merged[f'{col}_prev'].fillna(merged[f'Curr_{col}'])
        else:
            merged = display_df.copy()
            for col in ['HU', 'Comp', 'RMS', 'OCC', 'ADR', 'RevPAR', 'REV']:
                merged[f'{col}_prev'] = merged[f'Curr_{col}']

        for col in ['HU', 'Comp', 'RMS', 'OCC', 'ADR', 'RevPAR', 'REV']:
            merged[f'Pick_{col}'] = merged[f'Curr_{col}'] - merged[f'{col}_prev']

        sum_cols = []
        for prefix in ['Curr', 'prev', 'Pick']:
            for item in ['HU', 'Comp', 'RMS', 'REV']:
                if prefix == 'prev': item_col = f'{item}_prev'
                elif prefix == 'Pick': item_col = f'Pick_{item}'
                else: item_col = f'{prefix}_{item}'
                sum_cols.append(item_col)
        totals = merged[sum_cols].sum()

        def calc_rates(prefix):
            s_rms = totals[f'{prefix}RMS'] if prefix == 'Curr_' else totals[f'RMS{prefix}']
            s_rev = totals[f'{prefix}REV'] if prefix == 'Curr_' else totals[f'REV{prefix}']
            if prefix == 'Curr_':
                avail = merged['Curr_RMS'] / (merged['Curr_OCC'].replace(0, np.nan) / 100)
            else:
                avail = merged['RMS_prev'] / (merged['OCC_prev'].replace(0, np.nan) / 100)
            total_avail = avail.fillna(0).sum()
            return (s_rev/s_rms if s_rms else 0), (s_rms/total_avail*100 if total_avail else 0), (s_rev/total_avail if total_avail else 0)

        c_adr, c_occ, c_par = calc_rates('Curr_')
        p_adr, p_occ, p_par = calc_rates('_prev')

        total_row = {
            'Date': 'TOTAL', 'Day': '',
            'HU_prev': totals['HU_prev'], 'Comp_prev': totals['Comp_prev'], 'RMS_prev': totals['RMS_prev'], 'OCC_prev': p_occ, 'ADR_prev': p_adr, 'RevPAR_prev': p_par, 'REV_prev': totals['REV_prev'],
            'Curr_HU': totals['Curr_HU'], 'Curr_Comp': totals['Curr_Comp'], 'Curr_RMS': totals['Curr_RMS'], 'Curr_OCC': c_occ, 'Curr_ADR': c_adr, 'Curr_RevPAR': c_par, 'Curr_REV': totals['Curr_REV'],
            'Pick_HU': totals['Pick_HU'], 'Pick_Comp': totals['Pick_Comp'], 'Pick_RMS': totals['Pick_RMS'], 'Pick_OCC': c_occ-p_occ, 'Pick_ADR': c_adr-p_adr, 'Pick_RevPAR': c_par-p_par, 'Pick_REV': totals['Pick_REV']
        }
        merged = pd.concat([merged, pd.DataFrame([total_row])], ignore_index=True)

        final_cols = ['Date', 'Day']
        items = ['HU', 'Comp', 'RMS', 'OCC', 'ADR', 'RevPAR', 'REV']
        for item in items: final_cols.append(f'{item}_prev')
        for item in items: final_cols.append(f'Curr_{item}')
        for item in items: final_cols.append(f'Pick_{item}')
        
        final_df = merged[final_cols].copy()
        col_map = {'Date':'Date', 'Day':'Day'}
        for item in items:
            col_map[f'{item}_prev'] = f'Pre\n{item}'
            col_map[f'Curr_{item}'] = f'Today\n{item}'
            col_map[f'Pick_{item}'] = f'Var\n{item}'
        final_df.columns = [col_map.get(c, c) for c in final_df.columns]

        fmt = {}
        for col in final_df.columns:
            if 'OCC' in col: fmt[col] = '{:.1f}%'
            elif 'Date' in col or 'Day' in col: continue
            elif 'Var' in col: fmt[col] = '{:+,.0f}'
            else: fmt[col] = '{:,.0f}'
        if 'Var\nOCC' in final_df.columns: fmt['Var\nOCC'] = '{:+.1f}%'

        styler = final_df.style.format(fmt)
        
        pre_cols = [c for c in final_df.columns if 'Pre' in c]
        styler = styler.set_properties(subset=pre_cols, **{'background-color': '#f8f9fa', 'color': '#9ca3af', 'font-size': '11px'})
        
        curr_cols = [c for c in final_df.columns if 'Today' in c]
        subset_idx = final_df.index[:-1]
        styler = styler.background_gradient(cmap='Blues', subset=pd.IndexSlice[subset_idx, [c for c in curr_cols if 'OCC' not in c]], low=0.2, high=0.5)
        styler = styler.background_gradient(cmap='Oranges', subset=pd.IndexSlice[subset_idx, [c for c in curr_cols if 'OCC' in c]], low=0.4, high=0.6)
        styler = styler.set_properties(subset=curr_cols, **{'background-color': '#f0f9ff', 'font-weight': '700', 'font-size': '12px', 'border-left': '1px solid #cbd5e1', 'border-right': '1px solid #cbd5e1'})
        
        var_cols = [c for c in final_df.columns if 'Var' in c]
        def color_variant(val):
            color = '#dc2626' if val < 0 else '#166534' if val > 0 else '#374151'
            return f'color: {color}; font-weight: bold;'
        styler = styler.map(color_variant, subset=var_cols)
        styler = styler.set_properties(subset=var_cols, **{'background-color': '#fffbeb', 'font-size': '11px'})

        def highlight_total_curr(row):
            styles = []
            for idx, col in enumerate(row.index):
                base_style = 'background-color: #eff6ff; font-weight: 800; border-top: 2px solid #1d4ed8; font-size: 13px;'
                if 'Today' in col:
                    base_style += 'background-color: #dbeafe; color: #1e3a8a; font-size: 14px; border-left: 2px solid #1d4ed8; border-right: 2px solid #1d4ed8;'
                styles.append(base_style)
            return styles

        styler = styler.apply(lambda x: highlight_total_curr(x) if x.name == final_df.index[-1] else ['' for _ in x], axis=1)

        st.dataframe(styler, height=800, use_container_width=True, hide_index=True)

        if uploaded_files: # 파일 업로드 시에만 저장 버튼 활성화
            if st.button(f"💾 {report_date.strftime('%Y-%m-%d')}일자 저장", key=f"save_{current_month}"):
                save_data_with_sob(report_date.strftime("%Y-%m-%d"), current_month, df_curr, sob_curr)
                st.toast(f"✅ 저장 완료!", icon="💾")
