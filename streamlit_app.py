import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timedelta
import io
import numpy as np

# ------------------------------------------------------------------
# 1. 기본 설정 및 Firebase 연결
# ------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Daily Pace Report")

# 스타일 커스텀: KPI 카드 디자인 + 테이블 폰트 미세 조정
st.markdown("""
<style>
    /* 전체 여백 최소화 */
    .block-container {
        padding-top: 1rem; 
        padding-bottom: 2rem; 
        padding-left: 0.5rem; 
        padding-right: 0.5rem;
    }
    
    /* [테이블 스타일] */
    iframe[title="streamlit.dataframe"] {width: 100% !important;}
    
    /* 헤더: 중앙 정렬, 줄바꿈, 폰트 적당히 */
    th {
        text-align: center !important;
        vertical-align: bottom !important;
        white-space: pre-wrap !important;
        padding: 2px !important;
        font-size: 11px !important;
        line-height: 1.1 !important;
    }
    
    /* 데이터 셀 기본: 패딩 축소 */
    td {
        padding: 2px !important;
    }

    /* [상단 요약 KPI 카드 스타일] */
    .kpi-container {
        display: flex;
        justify_content: space-between;
        background-color: #f8f9fa;
        padding: 15px;
        border-radius: 10px;
        margin-bottom: 10px;
        border: 1px solid #e0e0e0;
    }
    .kpi-box {
        text-align: center;
        flex: 1;
        border-right: 1px solid #ddd;
    }
    .kpi-box:last-child { border-right: none; }
    .kpi-label {
        font-size: 14px;
        color: #666;
        margin-bottom: 5px;
        font-weight: bold;
    }
    .kpi-value {
        font-size: 24px; /* 숫자 크게! */
        font-weight: 800;
        color: #333;
    }
    .kpi-sub {
        font-size: 16px;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

if not firebase_admin._apps:
    try:
        key_dict = dict(st.secrets["firebase"])
        cred = credentials.Certificate(key_dict)
        firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"Firebase 연결 오류: Secrets 설정을 확인해주세요. ({e})")
        st.stop()

db = firestore.client()

# ------------------------------------------------------------------
# 2. 예산(Budget) 설정
# ------------------------------------------------------------------
BUDGET_DATA = {
    1: 514992575,  
    2: 480000000,
    3: 520000000,
    4: 600000000
}

# ------------------------------------------------------------------
# 3. 함수 정의
# ------------------------------------------------------------------

def find_first_date(df):
    first_col = df.iloc[:, 0]
    dates = pd.to_datetime(first_col, errors='coerce')
    valid_dates = dates.dropna()
    if not valid_dates.empty:
        return valid_dates.iloc[0], valid_dates.index[0]
    return None, None

def process_excel_file(file):
    try:
        file.seek(0)
        temp_df = pd.read_excel(file, header=None)
        first_date, start_row = find_first_date(temp_df)
        
        if first_date is None:
            return None, None

        df_raw = pd.read_excel(file, header=None)
        df_data = df_raw.iloc[start_row:].copy()
        
        df_clean = pd.DataFrame()
        
        df_clean['Date'] = pd.to_datetime(df_data.iloc[:, 0], errors='coerce')
        df_clean = df_clean.dropna(subset=['Date'])

        def safe_num(col_idx):
            return pd.to_numeric(df_data.iloc[:, col_idx], errors='coerce').fillna(0)

        df_clean['HU'] = safe_num(-7)
        df_clean['Comp'] = safe_num(-6)
        df_clean['RMS'] = safe_num(-5)
        df_clean['OCC'] = safe_num(-4)
        df_clean['ADR'] = safe_num(-3)
        df_clean['RevPAR'] = safe_num(-2)
        df_clean['REV'] = safe_num(-1)
        
        df_clean['DateStr'] = df_clean['Date'].dt.strftime('%Y-%m-%d')
        df_clean['WeekDay'] = df_clean['Date'].dt.strftime('%a')
        
        return df_clean, first_date.month
    except Exception as e:
        return None, None

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
        return 'color: red; font-weight: bold;'
    return 'color: black;'

# ------------------------------------------------------------------
# 4. 사이드바
# ------------------------------------------------------------------
st.sidebar.title("📅 Settings")
report_date = st.sidebar.date_input("기준 일자", datetime.now())
report_date_str = report_date.strftime("%Y-%m-%d")

compare_date_default = report_date - timedelta(days=1)
compare_date = st.sidebar.date_input("비교 일자", compare_date_default)
compare_date_str = compare_date.strftime("%Y-%m-%d")

# ------------------------------------------------------------------
# 5. 메인 UI
# ------------------------------------------------------------------
st.title(f"🏨 Daily Pace Report ({report_date_str})")

uploaded_files = st.file_uploader(
    "오늘자 엑셀 파일 업로드", 
    accept_multiple_files=True,
    type=['xlsx']
)

if uploaded_files:
    tabs = st.tabs(["1월", "2월", "3월", "4월"])
    
    month_files_map = {1: [], 2: [], 3: [], 4: []}
    
    for file in uploaded_files:
        df, month = process_excel_file(file)
        if df is not None and month in month_files_map:
            month_files_map[month].append({'file_name': file.name, 'data': df})

    for i, tab in enumerate(tabs):
        current_month = i + 1
        with tab:
            files = month_files_map.get(current_month, [])
            
            df_curr = None
            df_prev = None
            mode_msg = ""

            if files:
                if len(files) >= 2:
                    f1, f2 = files[0], files[1]
                    if f1['data']['REV'].sum() >= f2['data']['REV'].sum():
                        df_curr, df_prev = f1['data'], f2['data']
                    else:
                        df_curr, df_prev = f2['data'], f1['data']
                    mode_msg = "File Comparison"
                else:
                    df_curr = files[0]['data']
                    df_prev = get_data_by_date(compare_date_str, current_month)
                    mode_msg = f"vs {compare_date_str}" if df_prev is not None else "No Prev Data"
            else:
                st.info(f"📂 {current_month}월 데이터 없음")
                continue

            # ----------------------
            # 1. 상단 요약 (HTML/CSS로 크게!)
            # ----------------------
            total_rev = df_curr['REV'].sum()
            budget = BUDGET_DATA.get(current_month, 0)
            achv_rate = (total_rev / budget * 100) if budget > 0 else 0
            diff_val = total_rev - budget
            diff_color = "#d9534f" if diff_val < 0 else "#0275d8" # 빨강 / 파랑
            diff_sign = "-" if diff_val < 0 else "+"
            
            # HTML 코드로 KPI 카드 직접 그리기
            st.markdown(f"""
            <div class="kpi-container">
                <div class="kpi-box">
                    <div class="kpi-label">BUDGET</div>
                    <div class="kpi-value">{budget:,.0f}</div>
                </div>
                <div class="kpi-box">
                    <div class="kpi-label">ACTUAL (Total)</div>
                    <div class="kpi-value" style="color: #0275d8;">{total_rev:,.0f}</div>
                </div>
                <div class="kpi-box">
                    <div class="kpi-label">VAR</div>
                    <div class="kpi-value" style="color: {diff_color};">
                        <span class="kpi-sub">{diff_sign} {abs(diff_val):,.0f}</span>
                    </div>
                </div>
                <div class="kpi-box">
                    <div class="kpi-label">ACHIEVEMENT</div>
                    <div class="kpi-value">{achv_rate:.1f}%</div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            # ----------------------
            # 2. 데이터 처리
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
            
            # ----------------------
            # 3. 합계
            # ----------------------
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

            # ----------------------
            # 4. 컬럼 정리 (Pre는 작게 보이게)
            # ----------------------
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

            # ----------------------
            # 5. 스타일링 (폰트 크기 차별화)
            # ----------------------
            fmt = {}
            for col in final_df.columns:
                if 'OCC' in col: fmt[col] = '{:.1f}%'
                elif 'Date' in col or 'Day' in col: continue
                elif 'Var' in col: fmt[col] = '{:+,.0f}'
                else: fmt[col] = '{:,.0f}'
            if 'Var\nOCC' in final_df.columns: fmt['Var\nOCC'] = '{:+.1f}%'

            styler = final_df.style.format(fmt)
            
            # [폰트 사이즈 전략]
            # Pre(어제) 컬럼 -> 폰트 10px로 작게
            pre_cols = [c for c in final_df.columns if 'Pre' in c]
            styler = styler.set_properties(subset=pre_cols, **{
                'background-color': '#f8f9fa', 
                'color': '#888888',
                'font-size': '10px' 
            })

            # Curr(오늘) 컬럼 -> 폰트 12px + Bold (강조)
            curr_cols = [c for c in final_df.columns if c not in pre_cols and 'Var' not in c and c not in ['Date', 'Day']]
            styler = styler.set_properties(subset=curr_cols, **{
                'background-color': '#ffffff', 
                'font-weight': 'bold',
                'font-size': '12px',
                'border-left': '1px solid #ddd',
                'border-right': '1px solid #ddd'
            })

            # Var(변화) 컬럼 -> 폰트 11px
            var_cols = [c for c in final_df.columns if 'Var' in c]
            styler = styler.set_properties(subset=var_cols, **{
                'background-color': '#fffdeb',
                'font-size': '11px'
            })

            # 마이너스 빨간색
            styler = styler.map(color_negative_red, subset=var_cols)
            
            # Total 행
            styler = styler.apply(lambda x: ['font-weight: bold; font-size: 13px; background-color: #e6f3ff; border-top: 2px solid #333'] * len(x) if x.name == final_df.index[-1] else [''] * len(x), axis=1)

            st.dataframe(styler, height=800, use_container_width=True, hide_index=True)
            
            if st.button(f"💾 {report_date_str}일자 저장", key=f"save_{current_month}"):
                data_to_save = df_curr.copy()
                save_data_by_date(report_date_str, current_month, data_to_save)
                st.toast(f"✅ 저장 완료!", icon="💾")
