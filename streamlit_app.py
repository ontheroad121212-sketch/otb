import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timedelta
import io
import numpy as np
import textwrap

# ==============================================================================
# [1] 페이지 기본 설정
# ==============================================================================
st.set_page_config(
    layout="wide",
    page_title="Daily Pace Report",
    initial_sidebar_state="expanded"
)

# ==============================================================================
# [2] CSS 스타일링 (하단 공백 추가 + 행 높이 조절)
# ==============================================================================
st.markdown(textwrap.dedent("""
<style>
    /* 1. 전체 메인 컨테이너 여백 조정 */
    /* [수정] 아래쪽 padding-bottom을 10rem으로 늘려 'Manage App' 버튼에 가려지지 않게 함 */
    .block-container {
        padding-top: 0.5rem;
        padding-bottom: 10rem !important; 
        padding-left: 1rem;
        padding-right: 1rem;
    }
    
    /* ==========================================================================
       [상단 구역] S.O.B 요약 카드 디자인 (크고 시원하게 유지)
       ========================================================================== */
    
    /* 흰색 카드 박스 컨테이너 */
    .sob-container {
        background-color: white;
        border-radius: 15px;
        box-shadow: 0 4px 20px rgba(0,0,0,0.08);
        padding: 30px;
        margin-bottom: 30px;
        border: 1px solid #e5e7eb;
    }
    
    /* S.O.B 헤더 제목 스타일 */
    .sob-header {
        font-size: 24px;
        font-weight: 900;
        color: #111827;
        margin-bottom: 25px;
        border-bottom: 3px solid #f3f4f6;
        padding-bottom: 15px;
        letter-spacing: -0.5px;
    }
    
    /* 좌우 분할 그리드 레이아웃 */
    .sob-grid {
        display: grid;
        grid-template-columns: 1fr 1.3fr;
        gap: 50px;
    }
    
    /* 상단 테이블 */
    .modern-table {
        width: 100%;
        border-collapse: collapse;
        font-family: 'Segoe UI', sans-serif;
    }
    
    .modern-table th {
        text-align: right;
        color: #4b5563;
        font-size: 14px;
        font-weight: 700;
        padding: 12px 10px;
        border-bottom: 2px solid #e5e7eb;
        background-color: #f9fafb;
    }
    .modern-table th:first-child {
        text-align: left;
    }
    
    .modern-table td {
        padding: 14px 10px;
        font-size: 16px;
        color: #1f2937;
        text-align: right;
        border-bottom: 1px solid #f3f4f6;
    }
    .modern-table td.label {
        text-align: left;
        font-weight: 700;
        color: #374151;
    }
    
    /* 상단 KPI 미니 카드 */
    .kpi-wrapper {
        display: flex;
        gap: 20px;
        margin-top: 25px;
    }
    .kpi-card {
        flex: 1;
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 20px;
        text-align: center;
    }
    .kpi-title {
        font-size: 14px;
        color: #64748b;
        font-weight: 800;
        margin-bottom: 8px;
        text-transform: uppercase;
    }
    .kpi-value {
        font-size: 32px;
        color: #0f172a;
        font-weight: 900;
        letter-spacing: -1px;
    }
    .kpi-accent {
        background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%);
        box-shadow: 0 4px 10px rgba(37, 99, 235, 0.2);
    }
    .kpi-accent .kpi-title { color: rgba(255,255,255,0.9); }
    .kpi-accent .kpi-value { color: #ffffff; }

    /* ==========================================================================
       [중앙/하단 구역] 메인 데이터 테이블 (HTML 강제 스타일링)
       [수정] 행 높이 살짝 증가, 가독성 확보
       ========================================================================== */
    
    /* 테이블 감싸는 div (스크롤 및 여백) */
    .compact-table-wrapper {
        overflow-x: auto;
        margin-top: 10px;
        margin-bottom: 50px; /* 표 아래에도 추가 여백 */
        border: 1px solid #e5e7eb;
        border-radius: 4px;
    }

    .compact-table-wrapper table {
        width: 100%;
        border-collapse: collapse;
        font-family: 'Segoe UI', sans-serif;
        font-size: 10px !important;
    }
    
    /* 헤더 스타일링 */
    .compact-table-wrapper th {
        background-color: #f8fafc;
        color: #475569;
        font-weight: 700;
        text-align: center;
        padding: 5px 3px !important; /* [수정] 헤더 높이도 살짝 여유 있게 */
        border: 1px solid #e2e8f0;
        font-size: 10px !important;
        line-height: 1.2 !important;
        white-space: pre-wrap;
    }
    
    /* 데이터 셀 스타일링 */
    .compact-table-wrapper td {
        /* [수정] 행 높이 조절 핵심: 패딩을 2px -> 5px로 늘림 */
        padding: 5px 3px !important; 
        border: 1px solid #e2e8f0;
        text-align: right;
        font-size: 10px !important;
        /* [수정] 줄 간격을 1.0 -> 1.4로 늘려 숨쉴 공간 확보 */
        line-height: 1.4 !important; 
        white-space: nowrap;
        vertical-align: middle;
    }

    /* 유틸리티 클래스 */
    .text-red { color: #dc2626; font-weight: 800; }
    .text-green { color: #059669; font-weight: 800; }
    
    /* 합계 행 스타일 */
    .total-row td {
        background-color: #eff6ff;
        font-weight: 900;
        color: #1e40af;
        border-top: 3px solid #bfdbfe;
    }
</style>
"""), unsafe_allow_html=True)

# ==============================================================================
# [3] Firebase 데이터베이스 연결 설정
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

# ==============================================================================
# [4] 데이터 처리 로직 및 함수 정의
# ==============================================================================

# 월별 예산 데이터 (1월 ~ 12월 전체)
BUDGET_DATA = { 
    1: 514992575, 
    2: 786570856, 
    3: 529599040, 
    4: 695351004,
    5: 903705440,
    6: 808203820,
    7: 1231949142,
    8: 1388376999,
    9: 952171506,
    10: 897171539,
    11: 667146771,
    12: 804030110 
}

def find_header_and_process(file):
    try:
        file.seek(0)
        df_preview = pd.read_excel(file, header=None, nrows=15)
        
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

        if len(rms_indices) >= 3 and len(rev_indices) >= 3:
            fit_rms_idx = rms_indices[0]
            fit_rev_idx = rev_indices[0]
            
            grp_rms_idx = rms_indices[1]
            grp_rev_idx = rev_indices[1]
            
            total_rms_idx = rms_indices[-1]
            total_rev_idx = rev_indices[-1]
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

        fit_rms_sum = int(safe_num(fit_rms_idx).sum())
        fit_rev_sum = int(safe_num(fit_rev_idx).sum())
        grp_rms_sum = int(safe_num(grp_rms_idx).sum())
        grp_rev_sum = int(safe_num(grp_rev_idx).sum())
        
        avail_daily = df_clean['RMS'] / (df_clean['OCC'].replace(0, np.nan) / 100)
        total_avail = avail_daily.fillna(0).sum()
        total_rms = int(df_clean['RMS'].sum())
        
        total_occ_pct = 0.0
        if total_avail > 0:
            total_occ_pct = float((total_rms / total_avail * 100))

        sob_data = {
            'FIT_RMS': fit_rms_sum, 
            'FIT_REV': fit_rev_sum,
            'GRP_RMS': grp_rms_sum, 
            'GRP_REV': grp_rev_sum,
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

def get_full_data_by_date(target_date_str, month_num):
    try:
        doc_ref = db.collection('daily_snapshots').document(target_date_str)\
                    .collection('months').document(str(month_num))
        doc = doc_ref.get()
        if doc.exists:
            data = doc.to_dict()
            df = pd.read_json(io.StringIO(data['json_data']), orient='records')
            sob = data.get('sob_data', None)
            if sob is None and not df.empty:
                sob = {
                    'FIT_RMS': 0, 'FIT_REV': 0, 
                    'GRP_RMS': 0, 'GRP_REV': 0, 
                    'TOTAL_OCC': df['OCC'].mean()
                }
            return df, sob
    except Exception:
        return None, None
    return None, None

def save_data_with_sob(target_date_str, month_num, df, sob_data):
    try:
        json_str = df.to_json(orient='records', date_format='iso')
        db.collection('daily_snapshots').document(target_date_str).set({
            'created_at': firestore.SERVER_TIMESTAMP
        }, merge=True)
        
        db.collection('daily_snapshots').document(target_date_str)\
          .collection('months').document(str(month_num))\
          .set({
              'json_data': json_str, 
              'sob_data': sob_data,
              'updated_at': firestore.SERVER_TIMESTAMP
          })
        return True
    except Exception as e:
        st.error(f"저장 중 오류 발생: {e}")
        return False

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

# ==============================================================================
# [5] 메인 실행 로직
# ==============================================================================

st.sidebar.header("⚙️ Report Settings")
report_date = st.sidebar.date_input("기준 일자 (오늘)", datetime.now())
report_date_str = report_date.strftime("%Y-%m-%d")

compare_date = st.sidebar.date_input("비교 일자 (어제)", report_date - timedelta(days=1))
compare_date_str = compare_date.strftime("%Y-%m-%d")

st.title(f"🏨 Daily Pace Report")
st.caption("어제와 오늘 파일을 모두 업로드하면, 자동으로 날짜를 분류하여 분석합니다.")

uploaded_files = st.file_uploader("엑셀 파일 업로드 (xlsx)", accept_multiple_files=True, type=['xlsx'])

tabs = st.tabs([f"{i}월" for i in range(1, 13)])
month_files_map = {i: [] for i in range(1, 13)}

if uploaded_files:
    for file in uploaded_files:
        df, month, sob = find_header_and_process(file)
        if df is not None and month in month_files_map:
            month_files_map[month].append({'name': file.name, 'data': df, 'sob': sob})

for i, tab in enumerate(tabs):
    current_month = i + 1
    with tab:
        files = month_files_map.get(current_month, [])
        df_curr, df_prev, sob_curr = None, None, None
        
        if files:
            files.sort(key=lambda x: x['name'])
            
            if len(files) >= 2:
                f_prev = files[-2]
                f_curr = files[-1]
                df_curr = f_curr['data'], f_curr['sob']
                df_prev = f_prev['data']
                st.caption(f"🔥 파일 비교 모드: {f_prev['name']} (Pre) vs {f_curr['name']} (Today)")
            
            else:
                df_curr = files[0]['data'], files[0]['sob']
                df_prev = get_data_by_date(compare_date_str, current_month)
                st.caption(f"📂 파일 vs DB 비교 모드 ({files[0]['name']} vs {compare_date_str})")
        
        else:
            df_curr, sob_curr = get_full_data_by_date(report_date_str, current_month)
            if df_curr is not None:
                df_prev, _ = get_full_data_by_date(compare_date_str, current_month)
                st.caption(f"☁️ DB 조회 모드 ({report_date_str} vs {compare_date_str})")
            else:
                st.info(f"📂 {current_month}월 데이터가 없습니다.")
                continue

        budget = BUDGET_DATA.get(current_month, 0)
        if sob_curr is None and df_curr is not None:
             sob_curr = {'FIT_RMS': 0, 'FIT_REV': 0, 'GRP_RMS': 0, 'GRP_REV': 0, 'TOTAL_OCC': 0}

        render_sob_dashboard(
            current_month=current_month,
            budget=budget,
            total_rev=sob_curr['FIT_REV'] + sob_curr['GRP_REV'],
            vs_budget=(sob_curr['FIT_REV'] + sob_curr['GRP_REV']) - budget,
            achv_rate=((sob_curr['FIT_REV'] + sob_curr['GRP_REV']) / budget * 100) if budget > 0 else 0,
            total_occ=sob_curr['TOTAL_OCC'],
            fit_rms=sob_curr['FIT_RMS'],
            fit_adr=fit_adr_val,
            fit_rev=sob_curr['FIT_REV'],
            grp_rms=sob_curr['GRP_RMS'],
            grp_adr=grp_adr_val,
            grp_rev=sob_curr['GRP_REV'],
            total_rms=total_rms_val,
            total_adr=total_adr_val
        )

        # 상세 데이터 가공
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
            
            display_df['DateStr_Key'] = display_df['Date'].astype(str)
            prev_subset['DateStr_Key'] = prev_subset['DateStr'].astype(str)
            merged = pd.merge(display_df, prev_subset, left_on='DateStr_Key', right_on='DateStr_Key', how='left')
            
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

        total_row_data = {
            'Date': 'TOTAL', 'Day': '',
            'HU_prev': totals['HU_prev'], 'Comp_prev': totals['Comp_prev'], 'RMS_prev': totals['RMS_prev'], 
            'OCC_prev': p_occ, 'ADR_prev': p_adr, 'RevPAR_prev': p_par, 'REV_prev': totals['REV_prev'],
            
            'Curr_HU': totals['Curr_HU'], 'Curr_Comp': totals['Curr_Comp'], 'Curr_RMS': totals['Curr_RMS'], 
            'Curr_OCC': c_occ, 'Curr_ADR': c_adr, 'Curr_RevPAR': c_par, 'Curr_REV': totals['Curr_REV'],
            
            'Pick_HU': totals['Pick_HU'], 'Pick_Comp': totals['Pick_Comp'], 'Pick_RMS': totals['Pick_RMS'], 
            'Pick_OCC': c_occ-p_occ, 'Pick_ADR': c_adr-p_adr, 'Pick_RevPAR': c_par-p_par, 'Pick_REV': totals['Pick_REV']
        }
        merged = pd.concat([merged, pd.DataFrame([total_row_data])], ignore_index=True)

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

        # [스타일링]
        fmt = {}
        for col in final_df.columns:
            if 'OCC' in col: fmt[col] = '{:.1f}%'
            elif 'Date' in col or 'Day' in col: continue
            elif 'Var' in col: fmt[col] = '{:+,.0f}'
            else: fmt[col] = '{:,.0f}'
        if 'Var\nOCC' in final_df.columns: fmt['Var\nOCC'] = '{:+.1f}%'

        styler = final_df.style.format(fmt)
        
        # 1. Pre(어제)
        pre_cols = [c for c in final_df.columns if 'Pre' in c]
        styler = styler.set_properties(subset=pre_cols, **{'background-color': '#f8f9fa', 'color': '#9ca3af'})
        
        # 2. Today(오늘) - 히트맵
        curr_cols = [c for c in final_df.columns if 'Today' in c]
        subset_idx = final_df.index[:-1]
        styler = styler.background_gradient(cmap='Blues', subset=pd.IndexSlice[subset_idx, [c for c in curr_cols if 'OCC' not in c]], low=0.2, high=0.6)
        styler = styler.background_gradient(cmap='Oranges', subset=pd.IndexSlice[subset_idx, [c for c in curr_cols if 'OCC' in c]], low=0.4, high=0.7)
        styler = styler.set_properties(subset=curr_cols, **{'font-weight': '700', 'border-left': '1px solid #cbd5e1', 'border-right': '1px solid #cbd5e1'})
        
        # 3. Var(변화)
        var_cols = [c for c in final_df.columns if 'Var' in c]
        def color_variant(val):
            color = '#dc2626' if val < 0 else '#166534' if val > 0 else '#374151'
            return f'color: {color}; font-weight: bold;'
        styler = styler.map(color_variant, subset=var_cols)
        styler = styler.set_properties(subset=var_cols, **{'background-color': '#fffbeb'})

        # 4. Total 행
        def highlight_total_curr(row):
            styles = []
            for idx, col in enumerate(row.index):
                base_style = 'background-color: #eff6ff; font-weight: 800; border-top: 2px solid #1d4ed8;'
                if 'Today' in col:
                    base_style += 'background-color: #dbeafe; color: #1e3a8a; border-left: 2px solid #1d4ed8; border-right: 2px solid #1d4ed8;'
                styles.append(base_style)
            return styles

        styler = styler.apply(lambda x: highlight_total_curr(x) if x.name == final_df.index[-1] else ['' for _ in x], axis=1)

        # [HTML 변환 및 렌더링] - st.dataframe 대신 HTML로 강제 렌더링
        html_code = styler.to_html(classes='compact-table') # classes에 CSS 클래스 연결
        
        # div 래퍼로 감싸서 출력 (스크롤 및 스타일 적용)
        st.markdown(f'<div class="compact-table-wrapper">{html_code}</div>', unsafe_allow_html=True)

        if uploaded_files:
            if st.button(f"💾 {report_date.strftime('%Y-%m-%d')}일자 저장", key=f"save_{current_month}"):
                success = save_data_with_sob(report_date.strftime("%Y-%m-%d"), current_month, df_curr, sob_curr)
                if success:
                    st.toast(f"✅ 저장 완료!", icon="💾")
