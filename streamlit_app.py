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

# 스타일 커스텀: 헤더 고정, 폰트 크기, 여백 최적화
st.markdown("""
<style>
    .block-container {
        padding-top: 1rem; 
        padding-bottom: 2rem; 
        padding-left: 0.5rem; 
        padding-right: 0.5rem;
    }
    iframe[title="streamlit.dataframe"] {width: 100% !important;}
    th { text-align: center !important; font-size: 13px !important; }
    td { font-size: 13px !important; }
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
# 3. 함수 정의 (DB 로직 변경됨)
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
        
        # 데이터 파싱
        df_clean['Date'] = pd.to_datetime(df_data.iloc[:, 0], errors='coerce')
        df_clean = df_clean.dropna(subset=['Date'])

        def safe_num(col_idx):
            return pd.to_numeric(df_data.iloc[:, col_idx], errors='coerce').fillna(0)

        # 컬럼 매핑 (이미지2 기준)
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
    """
    특정 날짜(YYYY-MM-DD)에 저장된 해당 월(month_num)의 데이터를 가져옵니다.
    구조: Collection('daily_snapshots') -> Doc('2026-01-20') -> SubCollection('months') -> Doc('1')
    """
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
    """
    특정 날짜(YYYY-MM-DD)를 키값으로 데이터를 저장합니다. (히스토리 보존)
    """
    json_str = df.to_json(orient='records', date_format='iso')
    # 메인 문서 생성 (없으면 생성)
    db.collection('daily_snapshots').document(target_date_str).set({'created_at': firestore.SERVER_TIMESTAMP}, merge=True)
    # 서브 컬렉션에 월별 데이터 저장
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
# 4. 사이드바 (날짜 선택)
# ------------------------------------------------------------------
st.sidebar.title("📅 Report Settings")

# 1. 기준일 (Report Date) - 보통 오늘
report_date = st.sidebar.date_input("기준 일자 (Report Date)", datetime.now())
report_date_str = report_date.strftime("%Y-%m-%d")

# 2. 비교일 (Comparison Date) - 보통 어제
# 기본값은 기준일 하루 전
compare_date_default = report_date - timedelta(days=1)
compare_date = st.sidebar.date_input("비교 일자 (Comparison Date)", compare_date_default)
compare_date_str = compare_date.strftime("%Y-%m-%d")

st.sidebar.markdown("---")
st.sidebar.info(
    f"""
    **조회 모드:**
    - **오늘 데이터:** 파일 업로드 필요
    - **{compare_date_str} 데이터:** DB에서 자동 조회
    
    *저장 시 '{report_date_str}' 날짜로 기록됩니다.*
    """
)

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
            
            df_curr = None
            df_prev = None
            mode_msg = ""

            # [로직 A] 업로드 된 파일 사용 (Current)
            if files:
                # 파일이 여러개면 매출 큰걸 Current로 (혹은 최신걸로)
                # 여기서는 파일 1개만 써도, 비교 대상은 DB(사이드바 날짜)에서 가져옴
                # 만약 파일 2개를 올려서 비교하고 싶다면? -> 파일 2개 로직 유지
                if len(files) >= 2:
                    f1, f2 = files[0], files[1]
                    if f1['data']['REV'].sum() >= f2['data']['REV'].sum():
                        df_curr, df_prev = f1['data'], f2['data']
                    else:
                        df_curr, df_prev = f2['data'], f1['data']
                    mode_msg = "🔥 **업로드된 파일끼리 비교**"
                else:
                    df_curr = files[0]['data']
                    # DB에서 비교일자 데이터 가져오기
                    df_prev = get_data_by_date(compare_date_str, current_month)
                    if df_prev is not None:
                        mode_msg = f"🗓️ **{compare_date_str}일자 DB 데이터와 비교**"
                    else:
                        mode_msg = f"⚠️ **{compare_date_str}일자 DB 데이터가 없습니다.**"
            else:
                # 파일 업로드가 없으면? -> 그냥 DB에서 기준일 vs 비교일 조회 기능도 가능하지만
                # 지금은 업로드 기반이므로 패스
                st.info(f"📂 {current_month}월 데이터가 없습니다.")
                continue

            # ----------------------
            # 1. 상단 요약
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
            # 2. 데이터 병합
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
                
                # 결측치 채우기
                for col in ['HU', 'Comp', 'RMS', 'OCC', 'ADR', 'RevPAR', 'REV']:
                    merged[f'{col}_prev'] = merged[f'{col}_prev'].fillna(merged[f'Curr_{col}'])
            else:
                merged = display_df.copy()
                for col in ['HU', 'Comp', 'RMS', 'OCC', 'ADR', 'RevPAR', 'REV']:
                    merged[f'{col}_prev'] = merged[f'Curr_{col}']

            # 변화량 계산
            for col in ['HU', 'Comp', 'RMS', 'OCC', 'ADR', 'RevPAR', 'REV']:
                merged[f'Pick_{col}'] = merged[f'Curr_{col}'] - merged[f'{col}_prev']
            
            # ----------------------
            # 3. 합계(TOTAL) 계산
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
            # 4. 컬럼 배치 및 이름 정리
            # ----------------------
            final_cols = ['Date', 'Day']
            items = ['HU', 'Comp', 'RMS', 'OCC', 'ADR', 'RevPAR', 'REV']
            
            for item in items: final_cols.append(f'{item}_prev')
            for item in items: final_cols.append(f'Curr_{item}')
            for item in items: final_cols.append(f'Pick_{item}')

            final_df = merged[final_cols].copy()

            col_map = {'Date': 'Date', 'Day': 'Day'}
            for item in items:
                col_map[f'{item}_prev'] = f'Pre {item}'
                col_map[f'Curr_{item}'] = f'{item}' 
                col_map[f'Pick_{item}'] = f'Var {item}'

            final_df.columns = [col_map.get(c, c) for c in final_df.columns]

            # ----------------------
            # 5. 스타일링 (배경색 구분!)
            # ----------------------
            fmt = {}
            for col in final_df.columns:
                if 'OCC' in col: fmt[col] = '{:.1f}%'
                elif 'Date' in col or 'Day' in col: continue
                elif 'Var' in col: fmt[col] = '{:+,.0f}'
                else: fmt[col] = '{:,.0f}'
            if 'Var OCC' in final_df.columns: fmt['Var OCC'] = '{:+.1f}%'

            styler = final_df.style.format(fmt)
            
            # [색상 로직]
            # 1. 어제 데이터(Pre) -> 회색 배경
            pre_cols = [c for c in final_df.columns if 'Pre' in c]
            styler = styler.set_properties(subset=pre_cols, **{'background-color': '#f8f9fa', 'color': '#666666'})

            # 2. 오늘 데이터(Curr) -> 흰색/강조 배경 (기본값)
            curr_cols = [c for c in final_df.columns if c not in pre_cols and 'Var' not in c and c not in ['Date', 'Day']]
            styler = styler.set_properties(subset=curr_cols, **{'background-color': '#ffffff', 'font-weight': 'bold'})

            # 3. 변화량(Var) -> 옅은 노란색 배경 (주목!)
            var_cols = [c for c in final_df.columns if 'Var' in c]
            styler = styler.set_properties(subset=var_cols, **{'background-color': '#fffdeb'})

            # 4. 마이너스 빨간색
            styler = styler.map(color_negative_red, subset=var_cols)
            
            # 5. Total 행 강조
            styler = styler.apply(lambda x: ['font-weight: bold; background-color: #e6f3ff; border-top: 2px solid black'] * len(x) if x.name == final_df.index[-1] else [''] * len(x), axis=1)

            st.dataframe(styler, height=800, use_container_width=True, hide_index=True)
            
            # ----------------------
            # 6. 저장 버튼 (날짜 기준 저장)
            # ----------------------
            if st.button(f"💾 {report_date_str}일자 데이터로 확정 및 저장", key=f"save_{current_month}"):
                data_to_save = df_curr.copy()
                save_data_by_date(report_date_str, current_month, data_to_save)
                st.toast(f"✅ {report_date_str} 날짜로 {current_month}월 데이터가 저장되었습니다!", icon="💾")
