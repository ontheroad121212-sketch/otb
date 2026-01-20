import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timedelta
import io
import numpy as np

# ------------------------------------------------------------------
# 1. 기본 설정 및 스타일링
# ------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Daily Pace Report")

st.markdown("""
<style>
    /* 전체 여백 최소화 (화면 꽉 채우기) */
    .block-container {
        padding-top: 1rem; 
        padding-bottom: 2rem; 
        padding-left: 0.5rem; 
        padding-right: 0.5rem;
    }
    
    /* [테이블 공통 스타일] */
    iframe[title="streamlit.dataframe"] {width: 100% !important;}
    
    /* 메인 리포트 헤더: 중앙 정렬, 줄바꿈 허용, 폰트 작게 */
    th {
        text-align: center !important;
        vertical-align: bottom !important;
        white-space: pre-wrap !important; /* 줄바꿈 강제 적용 */
        padding: 4px !important;
        font-size: 11px !important;
        line-height: 1.2 !important;
        background-color: #f0f2f6;
    }
    
    /* 데이터 셀: 패딩 축소 */
    td {
        padding: 4px 2px !important;
        font-size: 11px !important;
    }

    /* [상단 S.O.B 요약표 스타일 - 이미지 완벽 재현] */
    .sob-table {
        width: 100%;
        border-collapse: collapse;
        font-family: Arial, sans-serif;
        font-size: 13px;
        margin-bottom: 20px;
        background-color: white;
        border: 1px solid #000;
    }
    .sob-table th {
        background-color: #e1f5fe; /* 헤더: 연한 파랑 */
        border: 1px solid #000;
        padding: 6px;
        text-align: center;
        font-weight: bold;
        font-size: 13px !important;
    }
    .sob-table td {
        border: 1px solid #000;
        padding: 6px;
        text-align: right;
    }
    .sob-label {
        background-color: #fff9c4; /* 라벨: 연한 노랑 */
        text-align: center !important;
        font-weight: bold;
    }
    .sob-total-row {
        background-color: #fff9c4; /* 합계행: 연한 노랑 */
        font-weight: bold;
    }
    .sob-occ-cell {
        font-size: 20px;
        font-weight: 800;
        text-align: center !important;
        vertical-align: middle;
        background-color: #ffffff;
    }
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
# 2. 예산(Budget) 설정
# ------------------------------------------------------------------
BUDGET_DATA = {
    1: 514992575,  
    2: 480000000,
    3: 520000000,
    4: 600000000
}

# ------------------------------------------------------------------
# 3. 데이터 처리 함수 (FIT/GROUP 분리 로직 포함)
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
            return None, None, None

        df_raw = pd.read_excel(file, header=None)
        df_data = df_raw.iloc[start_row:].copy()
        
        df_clean = pd.DataFrame()
        df_clean['Date'] = pd.to_datetime(df_data.iloc[:, 0], errors='coerce')
        df_clean = df_clean.dropna(subset=['Date'])

        # 안전하게 숫자 변환하는 헬퍼 함수
        def safe_num(col_idx):
            return pd.to_numeric(df_data.iloc[:, col_idx], errors='coerce').fillna(0)

        # [1] 상세 리포트용 (Total 데이터) - 우측 합계 섹션(역순 인덱스 사용)
        df_clean['HU'] = safe_num(-7)
        df_clean['Comp'] = safe_num(-6)
        df_clean['RMS'] = safe_num(-5)
        df_clean['OCC'] = safe_num(-4)
        df_clean['ADR'] = safe_num(-3)
        df_clean['RevPAR'] = safe_num(-2)
        df_clean['REV'] = safe_num(-1)
        
        df_clean['DateStr'] = df_clean['Date'].dt.strftime('%Y-%m-%d')
        df_clean['WeekDay'] = df_clean['Date'].dt.strftime('%a')

        # [2] S.O.B 요약용 (FIT/GROUP 데이터 추출) - 좌측 섹션(정순 인덱스 사용)
        # 이미지 기준: 
        # FIT(개인): 2번째열(객실수), 5번째열(매출) -> 인덱스 1, 4
        # GROUP(단체): 6번째열(객실수), 9번째열(매출) -> 인덱스 5, 8
        
        fit_rms = safe_num(1).sum()
        fit_rev = safe_num(4).sum()
        
        grp_rms = safe_num(5).sum()
        grp_rev = safe_num(8).sum()
        
        # Total OCC 계산 (전체 RMS / 전체 가동가능객실)
        # 역산법: Total RMS / (Total OCC / 100) = Total Avail
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
        # DB 구조: daily_snapshots/{YYYY-MM-DD}/months/{month_num}
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
    # 메인 문서 업데이트
    db.collection('daily_snapshots').document(target_date_str).set({'created_at': firestore.SERVER_TIMESTAMP}, merge=True)
    # 서브 컬렉션 저장
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
# 4. 사이드바 (날짜 설정)
# ------------------------------------------------------------------
st.sidebar.title("📅 Settings")
report_date = st.sidebar.date_input("기준 일자 (저장일)", datetime.now())
report_date_str = report_date.strftime("%Y-%m-%d")

compare_date_default = report_date - timedelta(days=1)
compare_date = st.sidebar.date_input("비교 일자 (DB조회)", compare_date_default)
compare_date_str = compare_date.strftime("%Y-%m-%d")

# ------------------------------------------------------------------
# 5. 메인 UI
# ------------------------------------------------------------------
st.title(f"🏨 Daily Pace Report ({report_date_str})")

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
            mode_msg = ""
            
            # [데이터 로드 로직]
            if files:
                # 파일 2개 이상이면 파일끼리 비교
                if len(files) >= 2:
                    f1, f2 = files[0], files[1]
                    if f1['data']['REV'].sum() >= f2['data']['REV'].sum():
                        df_curr, df_prev = f1['data'], f2['data']
                        sob_curr = f1['sob']
                    else:
                        df_curr, df_prev = f2['data'], f1['data']
                        sob_curr = f2['sob']
                    mode_msg = "File vs File"
                # 파일 1개면 DB와 비교
                else:
                    df_curr = files[0]['data']
                    sob_curr = files[0]['sob']
                    df_prev = get_data_by_date(compare_date_str, current_month)
                    mode_msg = f"vs DB({compare_date_str})" if df_prev is not None else "No History"
            else:
                st.info(f"📂 {current_month}월 데이터가 없습니다.")
                continue

            # ----------------------
            # [상단 1] S.O.B 요약표 (HTML 구현)
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

            # HTML 생성
            html_table = f"""
            <table class="sob-table">
                <tr class="sob-header-row">
                    <th style="width: 25%;">OTB(On The Book) vs Budget</th>
                    <th style="width: 10%;">S.O.B</th>
                    <th style="width: 15%;">RMS</th>
                    <th style="width: 15%;">ADR</th>
                    <th style="width: 20%;">REV</th>
                    <th style="width: 15%;">OCC</th>
                </tr>
                <tr>
                    <td>
                        <div style="display:flex; justify-content:space-between;">
                            <span>Budget</span> <span>{budget:,.0f}</span>
                        </div>
                    </td>
                    <td class="sob-label">FIT</td>
                    <td>{fit_rms:,.0f}</td>
                    <td>{fit_adr:,.0f}</td>
                    <td>{fit_rev:,.0f}</td>
                    <td rowspan="3" class="sob-occ-cell">{total_occ:.1f}%</td>
                </tr>
                <tr>
                    <td>
                        <div style="display:flex; justify-content:space-between;">
                            <span>VS Budget</span> <span>{vs_budget:,.0f}</span>
                        </div>
                    </td>
                    <td class="sob-label">GROUP</td>
                    <td>{grp_rms:,.0f}</td>
                    <td>{grp_adr:,.0f}</td>
                    <td>{grp_rev:,.0f}</td>
                </tr>
                <tr class="sob-total-row">
                    <td>
                        <div style="display:flex; justify-content:space-between;">
                            <span>Achv.R</span> <span>{achv_rate:.1f}%</span>
                        </div>
                    </td>
                    <td class="sob-label">TOTAL</td>
                    <td>{total_rms:,.0f}</td>
                    <td>{total_adr:,.0f}</td>
                    <td>{total_rev:,.0f}</td>
                </tr>
            </table>
            """
            st.markdown(html_table, unsafe_allow_html=True)

            # ----------------------
            # [하단 2] 상세 리포트 (데이터 병합 및 계산)
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
                # 결측치 처리
                for col in ['HU', 'Comp', 'RMS', 'OCC', 'ADR', 'RevPAR', 'REV']:
                    merged[f'{col}_prev'] = merged[f'{col}_prev'].fillna(merged[f'Curr_{col}'])
            else:
                merged = display_df.copy()
                for col in ['HU', 'Comp', 'RMS', 'OCC', 'ADR', 'RevPAR', 'REV']:
                    merged[f'{col}_prev'] = merged[f'Curr_{col}']

            # 변화량(PickUp) 계산
            for col in ['HU', 'Comp', 'RMS', 'OCC', 'ADR', 'RevPAR', 'REV']:
                merged[f'Pick_{col}'] = merged[f'Curr_{col}'] - merged[f'{col}_prev']
            
            # ----------------------
            # [하단 3] Total 합계 행 계산
            # ----------------------
            sum_cols = []
            for prefix in ['Curr', 'prev', 'Pick']:
                for item in ['HU', 'Comp', 'RMS', 'REV']:
                    if prefix == 'prev': item_col = f'{item}_prev'
                    elif prefix == 'Pick': item_col = f'Pick_{item}'
                    else: item_col = f'{prefix}_{item}'
                    sum_cols.append(item_col)
            totals = merged[sum_cols].sum()
            
            # 가중 평균 재계산 함수
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
            # [하단 4] 컬럼 및 스타일링 (컴팩트 뷰)
            # ----------------------
            final_cols = ['Date', 'Day']
            items = ['HU', 'Comp', 'RMS', 'OCC', 'ADR', 'RevPAR', 'REV']
            for item in items: final_cols.append(f'{item}_prev')
            for item in items: final_cols.append(f'Curr_{item}')
            for item in items: final_cols.append(f'Pick_{item}')

            final_df = merged[final_cols].copy()

            # 줄바꿈으로 폭 좁히기
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
            
            # Pre(어제): 작고 회색
            pre_cols = [c for c in final_df.columns if 'Pre' in c]
            styler = styler.set_properties(subset=pre_cols, **{'background-color': '#f8f9fa', 'color': '#888888', 'font-size': '10px'})
            
            # Curr(오늘): 굵고 흰색 (경계선 추가)
            curr_cols = [c for c in final_df.columns if c not in pre_cols and 'Var' not in c and c not in ['Date', 'Day']]
            styler = styler.set_properties(subset=curr_cols, **{'background-color': '#ffffff', 'font-weight': 'bold', 'font-size': '12px', 'border-left': '1px solid #ddd', 'border-right': '1px solid #ddd'})
            
            # Var(변화): 노란색
            var_cols = [c for c in final_df.columns if 'Var' in c]
            styler = styler.set_properties(subset=var_cols, **{'background-color': '#fffdeb', 'font-size': '11px'})
            styler = styler.map(color_negative_red, subset=var_cols)
            
            # Total 행 강조
            styler = styler.apply(lambda x: ['font-weight: bold; font-size: 13px; background-color: #e6f3ff; border-top: 2px solid #333'] * len(x) if x.name == final_df.index[-1] else [''] * len(x), axis=1)

            st.dataframe(styler, height=800, use_container_width=True, hide_index=True)
            
            if st.button(f"💾 {report_date_str}일자 저장", key=f"save_{current_month}"):
                data_to_save = df_curr.copy()
                save_data_by_date(report_date_str, current_month, data_to_save)
                st.toast(f"✅ 저장 완료!", icon="💾")
