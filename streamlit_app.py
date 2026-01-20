import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timedelta
import io
import numpy as np

# ------------------------------------------------------------------
# 1. 페이지 설정 및 CSS 디자인
# ------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Daily Pace Report")

st.markdown("""
<style>
    /* 전체 레이아웃 최적화 */
    .block-container {
        padding-top: 1rem;
        padding-bottom: 3rem;
        padding-left: 1rem;
        padding-right: 1rem;
    }
    
    /* [카드 스타일 S.O.B 테이블] */
    .sob-container {
        background-color: white;
        border-radius: 12px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        padding: 20px;
        margin-bottom: 20px;
        border: 1px solid #e0e0e0;
    }
    .sob-header {
        font-size: 16px;
        font-weight: 700;
        color: #1f2937;
        margin-bottom: 15px;
        border-bottom: 2px solid #f3f4f6;
        padding-bottom: 10px;
    }
    .sob-grid {
        display: grid;
        grid-template-columns: 1fr 1fr; /* 2분할 (Budget vs SOB) */
        gap: 30px;
    }
    
    /* 내부 테이블 스타일 */
    .modern-table {
        width: 100%;
        border-collapse: collapse;
        font-family: 'Segoe UI', sans-serif;
    }
    .modern-table th {
        text-align: left;
        color: #6b7280;
        font-size: 12px;
        font-weight: 600;
        padding: 8px 4px;
        border-bottom: 1px solid #e5e7eb;
    }
    .modern-table td {
        padding: 8px 4px;
        font-size: 14px;
        color: #111827;
        font-weight: 500;
        text-align: right;
    }
    .modern-table td.label {
        text-align: left;
        font-weight: 600;
        color: #374151;
    }
    .highlight-row td {
        background-color: #f9fafb;
        font-weight: 700;
        color: #2563eb; /* 강조색 파랑 */
    }
    
    /* KPI 박스 (점유율 등) */
    .kpi-card {
        background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
        color: white;
        border-radius: 10px;
        padding: 15px;
        text-align: center;
        display: flex;
        flex-direction: column;
        justify-content: center;
        height: 100%;
    }
    .kpi-title { font-size: 12px; opacity: 0.9; margin-bottom: 5px; }
    .kpi-value { font-size: 28px; font-weight: 800; }

    /* [하단 상세 리포트 테이블 스타일] */
    iframe[title="streamlit.dataframe"] { width: 100% !important; }
    
</style>
""", unsafe_allow_html=True)

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
# 2. 데이터 처리 함수 (좌표 수정됨)
# ------------------------------------------------------------------

BUDGET_DATA = { 1: 514992575, 2: 480000000, 3: 520000000, 4: 600000000 }

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
            return None, None, None

        df_raw = pd.read_excel(file, header=None)
        df_data = df_raw.iloc[start_row:].copy()
        
        df_clean = pd.DataFrame()
        df_clean['Date'] = pd.to_datetime(df_data.iloc[:, 0], errors='coerce')
        df_clean = df_clean.dropna(subset=['Date'])

        # [좌표 매핑] - 보내주신 이미지 기반 (0부터 시작)
        # A=0: 날짜
        # B=1: FIT RMS, D=3: FIT ADR, E=4: FIT REV
        # G=6: GRP RMS, I=8: GRP ADR, J=9: GRP REV
        # L=11: HU, M=12: Comp
        # N=13: Total RMS, O=14: OCC, P=15: Total ADR, Q=16: RevPAR, R=17: Total REV
        
        def safe_num(col_idx):
            return pd.to_numeric(df_data.iloc[:, col_idx], errors='coerce').fillna(0)

        # 1. 상세 리포트용 (Total 섹션 데이터)
        df_clean['HU'] = safe_num(11)      # L열
        df_clean['Comp'] = safe_num(12)    # M열
        df_clean['RMS'] = safe_num(13)     # N열 (Total RMS)
        df_clean['OCC'] = safe_num(14)     # O열 (OCC)
        df_clean['ADR'] = safe_num(15)     # P열 (Total ADR)
        df_clean['RevPAR'] = safe_num(16)  # Q열
        df_clean['REV'] = safe_num(17)     # R열 (Total REV)
        
        df_clean['DateStr'] = df_clean['Date'].dt.strftime('%Y-%m-%d')
        df_clean['WeekDay'] = df_clean['Date'].dt.strftime('%a')

        # 2. S.O.B 요약용 (FIT / GROUP 합계 계산)
        fit_rms = safe_num(1).sum()  # B열
        fit_rev = safe_num(4).sum()  # E열
        
        grp_rms = safe_num(6).sum()  # G열
        grp_rev = safe_num(9).sum()  # J열
        
        # Total OCC 계산 (가중평균)
        # 역산: Daily RMS / (Daily OCC / 100) = Daily Avail
        avail_daily = df_clean['RMS'] / (df_clean['OCC'].replace(0, np.nan) / 100)
        total_avail = avail_daily.fillna(0).sum()
        total_rms = df_clean['RMS'].sum()
        total_occ_pct = (total_rms / total_avail * 100) if total_avail > 0 else 0

        sob_data = {
            'FIT_RMS': fit_rms, 'FIT_REV': fit_rev,
            'GRP_RMS': grp_rms, 'GRP_REV': grp_rev,
            'TOTAL_OCC': total_occ_pct
        }
        
        return df_clean, first_date.month, sob_data

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
        return 'color: red; font-weight: bold;'
    return 'color: black;'

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
        df, month, sob = process_excel_file(file)
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
            
            # FIT/GROUP/TOTAL 계산
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
            
            vs_budget_color = "#ef4444" if vs_budget < 0 else "#10b981" # red/green

            html_card = f"""
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
                                <tr class="highlight-row">
                                    <td class="label">Variance</td>
                                    <td style="color:{vs_budget_color}">{vs_budget:+,.0f}</td>
                                    <td>Achv: {achv_rate:.1f}%</td>
                                </tr>
                            </tbody>
                        </table>
                        <div style="margin-top:15px; display:flex; gap:10px;">
                            <div class="kpi-card" style="flex:1;">
                                <div class="kpi-title">TOTAL OCC</div>
                                <div class="kpi-value">{total_occ:.1f}%</div>
                            </div>
                            <div class="kpi-card" style="flex:1; background: linear-gradient(135deg, #10b981 0%, #059669 100%);">
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
                                <tr class="highlight-row" style="border-top:2px solid #e5e7eb;">
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
            st.markdown(html_card, unsafe_allow_html=True)

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
            
            # 스타일링: Pre(회색), Curr(강조), Var(노랑)
            pre_cols = [c for c in final_df.columns if 'Pre' in c]
            styler = styler.set_properties(subset=pre_cols, **{'background-color': '#f9fafb', 'color': '#9ca3af', 'font-size': '10px'})
            
            curr_cols = [c for c in final_df.columns if c not in pre_cols and 'Var' not in c and c not in ['Date', 'Day']]
            styler = styler.set_properties(subset=curr_cols, **{'background-color': '#ffffff', 'font-weight': '700', 'font-size': '12px', 'border-left': '1px solid #e5e7eb', 'border-right': '1px solid #e5e7eb'})
            
            var_cols = [c for c in final_df.columns if 'Var' in c]
            styler = styler.set_properties(subset=var_cols, **{'background-color': '#fffbeb', 'font-size': '11px'})
            styler = styler.map(color_negative_red, subset=var_cols)
            
            # Total 행
            styler = styler.apply(lambda x: ['font-weight: 800; font-size: 13px; background-color: #eff6ff; border-top: 2px solid #1e40af'] * len(x) if x.name == final_df.index[-1] else [''] * len(x), axis=1)

            st.dataframe(styler, height=800, use_container_width=True, hide_index=True)
            
            if st.button(f"💾 {report_date_str}일자 저장", key=f"save_{current_month}"):
                data_to_save = df_curr.copy()
                save_data_by_date(report_date_str, current_month, data_to_save)
                st.toast(f"✅ 데이터 저장 완료!", icon="💾")
