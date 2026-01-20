import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timedelta
import io
import numpy as np
import textwrap

# ------------------------------------------------------------------
# 1. 페이지 설정 및 CSS (들여쓰기 이슈 완벽 해결)
# ------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Daily Pace Report")

# CSS 스타일 정의 (변수로 분리하여 공백 문제 해결)
custom_css = """
<style>
    /* 전체 여백 조정 */
    .block-container {
        padding-top: 1rem;
        padding-bottom: 3rem;
        padding-left: 1rem;
        padding-right: 1rem;
    }
    
    /* S.O.B 카드 컨테이너 */
    .sob-container {
        background-color: white;
        border-radius: 12px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.05);
        padding: 25px;
        margin-bottom: 25px;
        border: 1px solid #e0e0e0;
    }
    .sob-header {
        font-size: 20px;
        font-weight: 800;
        color: #111827;
        margin-bottom: 20px;
        border-bottom: 2px solid #f3f4f6;
        padding-bottom: 10px;
    }
    .sob-grid {
        display: grid;
        grid-template-columns: 1fr 1.3fr;
        gap: 40px;
    }
    
    /* 테이블 스타일 */
    .modern-table {
        width: 100%;
        border-collapse: collapse;
        font-family: 'Segoe UI', sans-serif;
    }
    .modern-table th {
        text-align: right;
        color: #6b7280;
        font-size: 13px;
        font-weight: 600;
        padding: 10px 8px;
        border-bottom: 2px solid #e5e7eb;
        background-color: #f9fafb;
    }
    .modern-table th:first-child { text-align: left; }
    
    .modern-table td {
        padding: 12px 8px;
        font-size: 15px;
        color: #1f2937;
        text-align: right;
        border-bottom: 1px solid #f3f4f6;
    }
    .modern-table td.label {
        text-align: left;
        font-weight: 600;
        color: #374151;
    }
    
    /* 강조 행 */
    .highlight-row td {
        background-color: #f0fdf4;
        font-weight: 700;
        color: #166534;
    }
    .highlight-row td.negative {
        background-color: #fef2f2;
        color: #991b1b;
    }
    .total-row td {
        background-color: #eff6ff;
        font-weight: 800;
        color: #1e40af;
        border-top: 2px solid #bfdbfe;
    }

    /* KPI 카드 */
    .kpi-wrapper {
        display: flex;
        gap: 15px;
        margin-top: 20px;
    }
    .kpi-card {
        flex: 1;
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 20px;
        text-align: center;
    }
    .kpi-title { font-size: 12px; color: #64748b; font-weight: 700; margin-bottom: 5px; }
    .kpi-value { font-size: 28px; color: #0f172a; font-weight: 900; }
    
    .kpi-accent { background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%); }
    .kpi-accent .kpi-title { color: rgba(255,255,255,0.8); }
    .kpi-accent .kpi-value { color: white; }
    
    /* DataFrame 스타일 */
    iframe[title="streamlit.dataframe"] { width: 100% !important; }
</style>
"""
st.markdown(custom_css, unsafe_allow_html=True)

# Firebase 연결
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
# 2. 데이터 처리
# ------------------------------------------------------------------

BUDGET_DATA = { 1: 514992575, 2: 480000000, 3: 520000000, 4: 600000000 }

def find_header_and_process(file):
    try:
        file.seek(0)
        df_preview = pd.read_excel(file, header=None, nrows=10)
        
        header_row_idx = None
        rms_indices = []
        rev_indices = []
        
        for idx, row in df_preview.iterrows():
            row_str = row.astype(str).values
            if np.any(['객실수' in s for s in row_str]) and np.any(['매출' in s for s in row_str]):
                header_row_idx = idx
                rms_indices = [i for i, val in enumerate(row_str) if '객실수' in str(val)]
                rev_indices = [i for i, val in enumerate(row_str) if '매출' in str(val)]
                break
        
        if header_row_idx is None:
            return None, None, None

        df_raw = pd.read_excel(file, header=None)
        start_row = header_row_idx + 1 
        df_data = df_raw.iloc[start_row:].copy()
        
        df_data['Date'] = pd.to_datetime(df_data.iloc[:, 0], errors='coerce')
        df_data = df_data.dropna(subset=['Date']) 

        def safe_num(col_idx):
            if col_idx >= df_data.shape[1]: return 0
            return pd.to_numeric(df_data.iloc[:, col_idx], errors='coerce').fillna(0)

        # [좌표 매핑]
        if len(rms_indices) >= 3 and len(rev_indices) >= 3:
            fit_rms_idx, grp_rms_idx, total_rms_idx = rms_indices[0], rms_indices[1], rms_indices[-1]
            fit_rev_idx, grp_rev_idx, total_rev_idx = rev_indices[0], rev_indices[1], rev_indices[-1]
        else:
            fit_rms_idx, grp_rms_idx = 1, 6
            fit_rev_idx, grp_rev_idx = 4, 9
            total_rms_idx, total_rev_idx = 13, 17
            
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

    except Exception as e:
        return None, None, None

def get_data_by_date(target_date_str, month_num):
    try:
        doc_ref = db.collection('daily_snapshots').document(target_date_str)\
                    .collection('months').document(str(month_num))
        doc = doc_ref.get()
        if doc.exists:
            data = doc.to_dict()
            return pd.read_json(io.StringIO(data['json_data']), orient='records')
    except Exception:
        return None
    return None

def save_data_by_date(target_date_str, month_num, df):
    json_str = df.to_json(orient='records', date_format='iso')
    db.collection('daily_snapshots').document(target_date_str).set({'created_at': firestore.SERVER_TIMESTAMP}, merge=True)
    doc_ref = db.collection('daily_snapshots').document(target_date_str)\
                .collection('months').document(str(month_num))
    doc_ref.set({
        'json_data': json_str,
        'updated_at': firestore.SERVER_TIMESTAMP
    })

def color_negative_red(val):
    if isinstance(val, (int, float)) and val < 0:
        return 'color: #dc2626; font-weight: bold;'
    if isinstance(val, (int, float)) and val > 0:
        return 'color: #166534; font-weight: bold;'
    return 'color: #374151;'

# ------------------------------------------------------------------
# 3. 사이드바
# ------------------------------------------------------------------
st.sidebar.header("⚙️ Report Settings")
report_date = st.sidebar.date_input("기준 일자", datetime.now())
report_date_str = report_date.strftime("%Y-%m-%d")

compare_date_default = report_date - timedelta(days=1)
compare_date = st.sidebar.date_input("비교 일자", compare_date_default)
compare_date_str = compare_date.strftime("%Y-%m-%d")

# ------------------------------------------------------------------
# 4. 메인 UI
# ------------------------------------------------------------------
st.title(f"🏨 Daily Pace Report")
st.caption(f"기준일: **{report_date_str}** | 비교일: **{compare_date_str}**")

uploaded_files = st.file_uploader("오늘자 엑셀 파일 업로드", accept_multiple_files=True, type=['xlsx'])

if uploaded_files:
    tabs = st.tabs(["1월", "2월", "3월", "4월"])
    month_files_map = {1: [], 2: [], 3: [], 4: []}
    
    for file in uploaded_files:
        df, month, sob = find_header_and_process(file)
        if df is not None and month in month_files_map:
            month_files_map[month].append({'file_name': file.name, 'data': df, 'sob': sob})

    for i, tab in enumerate(tabs):
        current_month = i + 1
        with tab:
            files = month_files_map.get(current_month, [])
            
            df_curr = None
            df_prev = None
            sob_curr = None
            
            if files:
                if len(files) >= 2:
                    f1, f2 = files[0], files[1]
                    if f1['data']['REV'].sum() >= f2['data']['REV'].sum():
                        df_curr, df_prev = f1['data'], f2['data']
                        sob_curr = f1['sob']
                    else:
                        df_curr, df_prev = f2['data'], f1['data']
                        sob_curr = f2['sob']
                else:
                    df_curr = files[0]['data']
                    sob_curr = files[0]['sob']
                    df_prev = get_data_by_date(compare_date_str, current_month)
            else:
                st.info(f"📂 {current_month}월 데이터가 없습니다.")
                continue

            # ----------------------
            # [상단] 모던 S.O.B 카드
            # ----------------------
            budget = BUDGET_DATA.get(current_month, 0)
            
            fit_rms = sob_curr['FIT_RMS']
            fit_rev = sob_curr['FIT_REV']
            fit_adr = (fit_rev / fit_rms) if fit_rms else 0

            grp_rms = sob_curr['GRP_RMS']
            grp_rev = sob_curr['GRP_REV']
            grp_adr = (grp_rev / grp_rms) if grp_rms else 0

            total_rms = fit_rms + grp_rms
            total_rev = fit_rev + grp_rev
            total_adr = (total_rev / total_rms) if total_rms else 0
            total_occ = sob_curr['TOTAL_OCC']

            vs_budget = total_rev - budget
            achv_rate = (total_rev / budget * 100) if budget > 0 else 0
            
            vs_row_class = "highlight-row"
            vs_cell_class = "negative" if vs_budget < 0 else ""

            # HTML 생성 (변수 분리하여 들여쓰기 문제 해결)
            html_content = f"""
            <div class="sob-container">
                <div class="sob-header">📊 {current_month}월 Performance Summary</div>
                
                <div class="sob-grid">
                    <div>
                        <table class="modern-table">
                            <thead>
                                <tr><th>Category</th><th>Amount</th><th>Status</th></tr>
                            </thead>
                            <tbody>
                                <tr>
                                    <td class="label">Budget</td>
                                    <td>{budget:,.0f}</td>
                                    <td>-</td>
                                </tr>
                                <tr>
                                    <td class="label">Actual</td>
                                    <td style="font-weight:bold;">{total_rev:,.0f}</td>
                                    <td>-</td>
                                </tr>
                                <tr class="{vs_row_class}">
                                    <td class="label">Variance</td>
                                    <td class="{vs_cell_class}">{vs_budget:+,.0f}</td>
                                    <td class="{vs_cell_class}">Achv: {achv_rate:.1f}%</td>
                                </tr>
                            </tbody>
                        </table>
                        <div class="kpi-wrapper">
                            <div class="kpi-card">
                                <div class="kpi-title">TOTAL OCC</div>
                                <div class="kpi-value">{total_occ:.1f}%</div>
                            </div>
                            <div class="kpi-card kpi-accent">
                                <div class="kpi-title">ACHIEVEMENT</div>
                                <div class="kpi-value">{achv_rate:.1f}%</div>
                            </div>
                        </div>
                    </div>
                    <div>
                        <table class="modern-table">
                            <thead>
                                <tr>
                                    <th>Segment</th><th>RMS</th><th>ADR</th><th>REV</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr>
                                    <td class="label">FIT (개인)</td>
                                    <td>{fit_rms:,.0f}</td>
                                    <td>{fit_adr:,.0f}</td>
                                    <td>{fit_rev:,.0f}</td>
                                </tr>
                                <tr>
                                    <td class="label">GROUP (단체)</td>
                                    <td>{grp_rms:,.0f}</td>
                                    <td>{grp_adr:,.0f}</td>
                                    <td>{grp_rev:,.0f}</td>
                                </tr>
                                <tr class="total-row">
                                    <td class="label">TOTAL</td>
                                    <td>{total_rms:,.0f}</td>
                                    <td>{total_adr:,.0f}</td>
                                    <td>{total_rev:,.0f}</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
            """
            st.markdown(html_content, unsafe_allow_html=True)

            # ----------------------
            # [하단] 상세 리포트
            # ----------------------
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
            
            # 합계 행
            sum_cols = []
            for prefix in ['Curr', 'prev', 'Pick']:
                for item in ['HU', 'Comp', 'RMS', 'REV']:
                    if prefix == 'prev': item_col = f'{item}_prev'
                    elif prefix == 'Pick': item_col = f'Pick_{item}'
                    else: item_col = f'{prefix}_{item}'
                    sum_cols.append(item_col)
            totals = merged[sum_cols].sum()
            
            def calc_weighted_rates(row_source, prefix):
                s_rms = totals[f'{prefix}RMS'] if prefix == 'Curr_' else totals[f'RMS{prefix}']
                s_rev = totals[f'{prefix}REV'] if prefix == 'Curr_' else totals[f'REV{prefix}']
                if prefix == 'Curr_':
                    avail_series = merged['Curr_RMS'] / (merged['Curr_OCC'].replace(0, np.nan) / 100)
                else:
                    avail_series = merged['RMS_prev'] / (merged['OCC_prev'].replace(0, np.nan) / 100)
                total_avail = avail_series.fillna(0).sum()
                t_adr = (s_rev / s_rms) if s_rms else 0
                t_occ = (s_rms / total_avail * 100) if total_avail else 0
                t_revpar = (s_rev / total_avail) if total_avail else 0
                return t_adr, t_occ, t_revpar

            curr_adr, curr_occ, curr_revpar = calc_weighted_rates(totals, 'Curr_')
            prev_adr, prev_occ, prev_revpar = calc_weighted_rates(totals, '_prev')

            total_row_data = {
                'Date': 'TOTAL', 'Day': '',
                'HU_prev': totals['HU_prev'], 'Comp_prev': totals['Comp_prev'], 'RMS_prev': totals['RMS_prev'],
                'OCC_prev': prev_occ, 'ADR_prev': prev_adr, 'RevPAR_prev': prev_revpar, 'REV_prev': totals['REV_prev'],
                'Curr_HU': totals['Curr_HU'], 'Curr_Comp': totals['Curr_Comp'], 'Curr_RMS': totals['Curr_RMS'],
                'Curr_OCC': curr_occ, 'Curr_ADR': curr_adr, 'Curr_RevPAR': curr_revpar, 'Curr_REV': totals['Curr_REV'],
                'Pick_HU': totals['Pick_HU'], 'Pick_Comp': totals['Pick_Comp'], 'Pick_RMS': totals['Pick_RMS'],
                'Pick_OCC': curr_occ - prev_occ, 'Pick_ADR': curr_adr - prev_adr, 'Pick_RevPAR': curr_revpar - prev_revpar, 'Pick_REV': totals['Pick_REV']
            }
            merged = pd.concat([merged, pd.DataFrame([total_row_data])], ignore_index=True)

            final_cols = ['Date', 'Day']
            items = ['HU', 'Comp', 'RMS', 'OCC', 'ADR', 'RevPAR', 'REV']
            for item in items: final_cols.append(f'{item}_prev')
            for item in items: final_cols.append(f'Curr_{item}')
            for item in items: final_cols.append(f'Pick_{item}')

            final_df = merged[final_cols].copy()

            col_map = {'Date': 'Date', 'Day': 'Day'}
            for item in items:
                col_map[f'{item}_prev'] = f'Pre\n{item}'  
                col_map[f'Curr_{item}'] = f'{item}'  
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
            
            # [스타일링]
            # 1. Pre(어제) - 회색조, 작게
            pre_cols = [c for c in final_df.columns if 'Pre' in c]
            styler = styler.set_properties(subset=pre_cols, **{'background-color': '#f9fafb', 'color': '#9ca3af', 'font-size': '11px'})
            
            # 2. Curr(오늘) - 중앙, 히트맵 적용
            curr_cols = [c for c in final_df.columns if c not in pre_cols and 'Var' not in c and c not in ['Date', 'Day']]
            
            # 히트맵 (은은한 파랑: RMS, ADR, RevPAR, REV / 은은한 오렌지: OCC)
            # Total 행 제외하고 적용
            subset_idx = final_df.index[:-1]
            styler = styler.background_gradient(cmap='Blues', subset=pd.IndexSlice[subset_idx, [c for c in curr_cols if 'OCC' not in c]], low=0.3, high=0.3)
            styler = styler.background_gradient(cmap='Oranges', subset=pd.IndexSlice[subset_idx, [c for c in curr_cols if 'OCC' in c]], low=0.5, high=0.5)
            
            # 폰트 스타일
            styler = styler.set_properties(subset=curr_cols, **{'font-weight': '700', 'font-size': '12px', 'border-left': '1px solid #e5e7eb', 'border-right': '1px solid #e5e7eb'})
            
            # 3. Var(변화량) - 빨강/초록 텍스트
            var_cols = [c for c in final_df.columns if 'Var' in c]
            styler = styler.map(color_negative_red, subset=var_cols)
            styler = styler.set_properties(subset=var_cols, **{'background-color': '#fffbeb', 'font-size': '11px'})
            
            # 4. Total 행
            styler = styler.apply(lambda x: ['font-weight: 800; font-size: 13px; background-color: #eff6ff; border-top: 2px solid #1d4ed8'] * len(x) if x.name == final_df.index[-1] else [''] * len(x), axis=1)

            st.dataframe(styler, height=800, use_container_width=True, hide_index=True)
            
            if st.button(f"💾 {report_date_str}일자 저장", key=f"save_{current_month}"):
                data_to_save = df_curr.copy()
                save_data_by_date(report_date_str, current_month, data_to_save)
                st.toast(f"✅ 데이터 저장 완료!", icon="💾")
