import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import io
import numpy as np

# ------------------------------------------------------------------
# 1. 기본 설정 및 Firebase 연결
# ------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Daily Pace Report")

# 스타일 커스텀: 화면 너비 100% 사용, 여백 최소화 (촘촘하게)
st.markdown("""
<style>
    .block-container {
        padding-top: 1rem; 
        padding-bottom: 0rem; 
        padding-left: 0.5rem; 
        padding-right: 0.5rem;
    }
    iframe[title="streamlit.dataframe"] {width: 100% !important;}
    
    /* 헤더 글씨 크기 조정 */
    th {
        font-size: 12px !important;
        text-align: center !important;
    }
    td {
        font-size: 13px !important;
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
        
        # 날짜
        df_clean['Date'] = pd.to_datetime(df_data.iloc[:, 0], errors='coerce')
        df_clean = df_clean.dropna(subset=['Date'])

        # 컬럼 매핑 (이미지2 기준 역순 매핑)
        # 맨뒤(-1): 매출, -2: RevPAR, -3: ADR, -4: OCC, -5: RMS
        # -6: 무료(Comp), -7: 내부이용(HU)
        
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

def get_yesterday_data(month_num):
    doc_ref = db.collection('daily_reports').document(f"2026-{month_num:02d}")
    doc = doc_ref.get()
    if doc.exists:
        data = doc.to_dict()
        try:
            return pd.read_json(io.StringIO(data['json_data']), orient='records')
        except:
            return None
    return None

def save_today_data(month_num, df):
    json_str = df.to_json(orient='records', date_format='iso')
    doc_ref = db.collection('daily_reports').document(f"2026-{month_num:02d}")
    doc_ref.set({
        'json_data': json_str,
        'updated_at': firestore.SERVER_TIMESTAMP
    })

def color_negative_red(val):
    if isinstance(val, (int, float)) and val < 0:
        return 'color: red; font-weight: bold;'
    return 'color: black;'

# ------------------------------------------------------------------
# 4. 메인 UI 구성
# ------------------------------------------------------------------
st.title("🏨 One-Click Daily Pace Report")
st.caption("💡 Tip: 파일을 드래그하면 자동 비교됩니다. (데이터가 많으니 넓은 화면에서 보세요)")

uploaded_files = st.file_uploader(
    "파일 업로드 (4개월치 동시 가능)", 
    accept_multiple_files=True,
    type=['xlsx']
)

if uploaded_files:
    tabs = st.tabs(["1월 (JAN)", "2월 (FEB)", "3월 (MAR)", "4월 (APR)"])
    
    month_files_map = {1: [], 2: [], 3: [], 4: []}
    
    for file in uploaded_files:
        df, month = process_excel_file(file)
        if df is not None and month in month_files_map:
            month_files_map[month].append({'file_name': file.name, 'data': df})

    for i, tab in enumerate(tabs):
        current_month = i + 1
        with tab:
            files = month_files_map.get(current_month, [])
            
            if not files:
                st.info(f"📂 {current_month}월 데이터가 없습니다.")
                continue

            df_curr = None
            df_prev = None
            mode_msg = ""

            # 비교 로직
            if len(files) >= 2:
                f1, f2 = files[0], files[1]
                if f1['data']['REV'].sum() >= f2['data']['REV'].sum():
                    df_curr, df_prev = f1['data'], f2['data']
                else:
                    df_curr, df_prev = f2['data'], f1['data']
                mode_msg = f"🔥 **파일 간 비교**"
            elif len(files) == 1:
                df_curr = files[0]['data']
                df_prev = get_yesterday_data(current_month)
                if df_prev is not None:
                    mode_msg = "☁️ **DB(어제)와 비교**"
                else:
                    mode_msg = "⚠️ **비교 데이터 없음**"

            # ----------------------
            # 1. 상단 요약 (Budget)
            # ----------------------
            total_rev = df_curr['REV'].sum()
            budget = BUDGET_DATA.get(current_month, 0)
            achv_rate = (total_rev / budget * 100) if budget > 0 else 0
            diff_val = total_rev - budget
            diff_color = "red" if diff_val < 0 else "blue"
            
            st.markdown(f"""
            ### 📊 {current_month}월 Performance
            {mode_msg}
            | Category | Budget | Actual | Vs Budget | Achv % |
            | :--- | :---: | :---: | :---: | :---: |
            | **Total Rev** | {budget:,.0f} | **{total_rev:,.0f}** | <span style='color:{diff_color}'>{diff_val:,.0f}</span> | **{achv_rate:.1f}%** |
            """, unsafe_allow_html=True)
            
            st.divider()

            # ----------------------
            # 2. 데이터 가공 (컬럼 확장: HU, Comp, RevPAR 추가)
            # ----------------------
            cols_base = ['DateStr', 'WeekDay', 'HU', 'Comp', 'RMS', 'OCC', 'ADR', 'RevPAR', 'REV']
            cols_curr = ['Date', 'Day', 'Curr_HU', 'Curr_Comp', 'Curr_RMS', 'Curr_OCC', 'Curr_ADR', 'Curr_RevPAR', 'Curr_REV']
            
            display_df = df_curr[cols_base].copy()
            display_df.columns = cols_curr

            if df_prev is not None:
                if 'DateStr' not in df_prev.columns:
                    df_prev['Date'] = pd.to_datetime(df_prev['Date'])
                    df_prev['DateStr'] = df_prev['Date'].dt.strftime('%Y-%m-%d')
                
                # 어제 데이터 준비
                prev_subset = df_prev[cols_base].copy()
                prev_subset.columns = ['DateStr', 'Day_p', 'HU_prev', 'Comp_prev', 'RMS_prev', 'OCC_prev', 'ADR_prev', 'RevPAR_prev', 'REV_prev']
                prev_subset = prev_subset.drop(columns=['Day_p']) # 요일 중복 제거

                merged = pd.merge(display_df, prev_subset, left_on='Date', right_on='DateStr', how='left')
                
                # 결측치 채우기 (어제 데이터 없으면 오늘 데이터로 채워서 변화량 0 만들기)
                for col in ['HU', 'Comp', 'RMS', 'OCC', 'ADR', 'RevPAR', 'REV']:
                    merged[f'{col}_prev'] = merged[f'{col}_prev'].fillna(merged[f'Curr_{col}'])

            else:
                merged = display_df.copy()
                for col in ['HU', 'Comp', 'RMS', 'OCC', 'ADR', 'RevPAR', 'REV']:
                    merged[f'{col}_prev'] = merged[f'Curr_{col}']

            # 변화량 계산 (Pick Up)
            for col in ['HU', 'Comp', 'RMS', 'OCC', 'ADR', 'RevPAR', 'REV']:
                merged[f'Pick_{col}'] = merged[f'Curr_{col}'] - merged[f'{col}_prev']
            
            # ----------------------
            # 3. 합계(TOTAL) 행 계산
            # ----------------------
            # 단순 합계 항목
            sum_cols = []
            for prefix in ['Curr', 'prev', 'Pick']: # Pick 합계도 계산
                for item in ['HU', 'Comp', 'RMS', 'REV']: # 단순 합산 가능한 것들
                    if prefix == 'prev': item_col = f'{item}_prev'
                    elif prefix == 'Pick': item_col = f'Pick_{item}'
                    else: item_col = f'{prefix}_{item}'
                    sum_cols.append(item_col)

            totals = merged[sum_cols].sum()
            
            # 가중 평균 항목 (ADR, OCC, RevPAR) 재계산 로직
            # 가용 객실수 역산 (Avail = RMS / (OCC%/100))
            def calc_weighted_rates(row_source, prefix):
                # prefix: 'Curr_' or '_prev'
                s_rms = totals[f'{prefix}RMS'] if prefix == 'Curr_' else totals[f'RMS{prefix}']
                s_rev = totals[f'{prefix}REV'] if prefix == 'Curr_' else totals[f'REV{prefix}']
                
                # Avail 합계 구하기 (Row별로 역산 후 합산)
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

            # 합계 행 데이터 생성
            total_row_data = {
                'Date': 'TOTAL', 'Day': '',
                # Prev
                'HU_prev': totals['HU_prev'], 'Comp_prev': totals['Comp_prev'], 'RMS_prev': totals['RMS_prev'],
                'OCC_prev': prev_occ, 'ADR_prev': prev_adr, 'RevPAR_prev': prev_revpar, 'REV_prev': totals['REV_prev'],
                # Curr
                'Curr_HU': totals['Curr_HU'], 'Curr_Comp': totals['Curr_Comp'], 'Curr_RMS': totals['Curr_RMS'],
                'Curr_OCC': curr_occ, 'Curr_ADR': curr_adr, 'Curr_RevPAR': curr_revpar, 'Curr_REV': totals['Curr_REV'],
                # Pick
                'Pick_HU': totals['Pick_HU'], 'Pick_Comp': totals['Pick_Comp'], 'Pick_RMS': totals['Pick_RMS'],
                'Pick_OCC': curr_occ - prev_occ, 'Pick_ADR': curr_adr - prev_adr, 'Pick_RevPAR': curr_revpar - prev_revpar, 'Pick_REV': totals['Pick_REV']
            }

            merged = pd.concat([merged, pd.DataFrame([total_row_data])], ignore_index=True)

            # ----------------------
            # 4. 컬럼 순서 및 이름 정리 (촘촘하게 배치)
            # ----------------------
            # 순서: Prev 그룹 -> Curr 그룹 -> Pick 그룹
            final_cols = ['Date', 'Day']
            
            # 그룹별 컬럼 정의
            items = ['HU', 'Comp', 'RMS', 'OCC', 'ADR', 'RevPAR', 'REV']
            
            for item in items: final_cols.append(f'{item}_prev')
            for item in items: final_cols.append(f'Curr_{item}')
            for item in items: final_cols.append(f'Pick_{item}')

            final_df = merged[final_cols].copy()

            # 헤더 이름 줄이기 (공간 절약)
            col_map = {'Date': 'Date', 'Day': 'Day'}
            for item in items:
                col_map[f'{item}_prev'] = f'Pre {item}'
                col_map[f'Curr_{item}'] = f'{item}' # 현재는 그냥 이름만 (중앙 강조)
                col_map[f'Pick_{item}'] = f'Var {item}' # Var = Variance

            final_df.columns = [col_map.get(c, c) for c in final_df.columns]

            # ----------------------
            # 5. 스타일링 (Styler)
            # ----------------------
            # 포맷 지정
            fmt = {}
            for col in final_df.columns:
                if 'OCC' in col: fmt[col] = '{:.1f}%'
                elif 'Date' in col or 'Day' in col: continue
                elif 'Var' in col: fmt[col] = '{:+,.0f}' # 변화량은 +기호
                else: fmt[col] = '{:,.0f}'
            
            # OCC 변화량은 % 붙이기
            if 'Var OCC' in final_df.columns: fmt['Var OCC'] = '{:+.1f}%'

            styler = final_df.style.format(fmt)
            
            # 마이너스 빨간색 (Var 컬럼들)
            var_cols = [c for c in final_df.columns if 'Var' in c]
            styler = styler.map(color_negative_red, subset=var_cols)
            
            # 중요 데이터 히트맵 (Total 행 제외)
            subset_idx = final_df.index[:-1]
            styler = styler.background_gradient(cmap='Blues', subset=pd.IndexSlice[subset_idx, ['RMS', 'REV', 'RevPAR']])
            styler = styler.background_gradient(cmap='Oranges', subset=pd.IndexSlice[subset_idx, ['OCC']])
            
            # Total 행 강조
            styler = styler.apply(lambda x: ['font-weight: bold; background-color: #f0f2f6'] * len(x) if x.name == final_df.index[-1] else [''] * len(x), axis=1)

            # 출력
            st.dataframe(styler, height=800, use_container_width=True, hide_index=True)
            
            # ----------------------
            # 6. 저장 버튼
            # ----------------------
            if st.button(f"💾 {current_month}월 데이터 확정 및 저장", key=f"save_{current_month}"):
                data_to_save = df_curr.copy()
                save_today_data(current_month, data_to_save)
                st.toast(f"✅ {current_month}월 데이터가 안전하게 저장되었습니다!", icon="💾")
