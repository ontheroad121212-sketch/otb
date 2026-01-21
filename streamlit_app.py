import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timedelta
import io
import numpy as np
import textwrap

# ==============================================================================
# 1. 페이지 기본 설정 및 디자인 (CSS) - 하단 표만 컴팩트하게 수정
# ==============================================================================
st.set_page_config(layout="wide", page_title="Daily Pace Report")

st.markdown(textwrap.dedent("""
<style>
    /* 전체 여백 조정 */
    .block-container {
        padding-top: 0.5rem;
        padding-bottom: 2rem;
        padding-left: 0.5rem;
        padding-right: 0.5rem;
    }
    
    /* [상단] S.O.B 카드 컨테이너 (여백 넉넉하게 유지) */
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
    
    /* [상단] 모던 테이블 스타일 (큼직하게 유지) */
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
    
    /* [상단] 강조 행 */
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

    /* [상단] KPI 카드 */
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
    .kpi-title {
        font-size: 12px;
        color: #64748b;
        font-weight: 700;
        margin-bottom: 5px;
    }
    .kpi-value {
        font-size: 28px;
        color: #0f172a;
        font-weight: 900;
    }
    .kpi-accent {
        background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
    }
    .kpi-accent .kpi-title { color: rgba(255,255,255,0.8); }
    .kpi-accent .kpi-value { color: white; }
    
    /* [하단] DataFrame 스타일 강제 적용 (여기가 핵심: 컴팩트하게!) */
    iframe[title="streamlit.dataframe"] { width: 100% !important; }
    
    /* [하단] 헤더 줄바꿈 허용 및 간격 최소화 */
    th {
        white-space: pre-wrap !important;
        text-align: center !important;
        vertical-align: bottom !important;
        line-height: 1.1 !important; /* 줄간격 축소 */
        font-size: 11px !important; /* 폰트 축소 */
        padding: 4px 2px !important; /* 패딩 최소화 */
    }
    
    /* [하단] 데이터 셀 간격 최소화 */
    td {
        vertical-align: middle !important;
        font-size: 11px !important; /* 데이터 폰트 축소 */
        padding: 2px 2px !important; /* 데이터 패딩 최소화 */
    }
    
    /* 텍스트 색상 유틸리티 */
    .text-red { color: #dc2626; font-weight: 700; }
    .text-green { color: #059669; font-weight: 700; }
</style>
"""), unsafe_allow_html=True)

# ==============================================================================
# 2. Firebase 데이터베이스 연결
# ==============================================================================
if not firebase_admin._apps:
    try:
        key_dict = dict(st.secrets["firebase"])
        cred = credentials.Certificate(key_dict)
        firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"Firebase 연결 오류: {e}")
        st.stop()

db = firestore.client()

# ==============================================================================
# 3. 데이터 처리 로직 (12개월 지원 + 예산)
# ==============================================================================

# 월별 예산 데이터
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
    """
    엑셀 파일을 읽어서 헤더 위치를 찾고, 
    FIT(개인), GROUP(단체), TOTAL(합계) 데이터를 추출하는 함수입니다.
    """
    try:
        file.seek(0)
        # 헤더를 찾기 위해 파일의 앞부분 10줄을 먼저 읽어봅니다.
        df_preview = pd.read_excel(file, header=None, nrows=10)
        
        header_row_idx = None
        rms_indices = []
        rev_indices = []
        
        # '객실수'와 '매출' 텍스트가 모두 포함된 행을 찾습니다.
        for idx, row in df_preview.iterrows():
            row_str = row.astype(str).values
            if np.any(['객실수' in s for s in row_str]) and np.any(['매출' in s for s in row_str]):
                header_row_idx = idx
                # 해당 행에서 각 항목의 인덱스(위치)를 찾습니다.
                rms_indices = [i for i, val in enumerate(row_str) if '객실수' in str(val)]
                rev_indices = [i for i, val in enumerate(row_str) if '매출' in str(val)]
                break
        
        if header_row_idx is None:
            return None, None, None

        # 실제 데이터 로드 (찾은 헤더 다음 행부터)
        df_raw = pd.read_excel(file, header=None)
        start_row = header_row_idx + 1 
        df_data = df_raw.iloc[start_row:].copy()
        
        # 날짜 컬럼 파싱 (보통 첫 번째 열)
        df_data['Date'] = pd.to_datetime(df_data.iloc[:, 0], errors='coerce')
        df_data = df_data.dropna(subset=['Date']) 

        # 안전하게 숫자로 변환하는 내부 함수
        def safe_num(col_idx):
            if col_idx >= df_data.shape[1]: return 0
            return pd.to_numeric(df_data.iloc[:, col_idx], errors='coerce').fillna(0)

        # [좌표 매핑 로직]
        # 보통 순서는 [FIT -> GROUP -> TOTAL] 순으로 배치됩니다.
        if len(rms_indices) >= 3 and len(rev_indices) >= 3:
            fit_rms_idx = rms_indices[0]
            fit_rev_idx = rev_indices[0]
            
            grp_rms_idx = rms_indices[1]
            grp_rev_idx = rev_indices[1]
            
            total_rms_idx = rms_indices[-1]
            total_rev_idx = rev_indices[-1]
        else:
            # 자동 감지에 실패할 경우, 사용자가 제공한 기본 이미지 좌표를 사용
            fit_rms_idx, grp_rms_idx, total_rms_idx = 1, 6, 13
            fit_rev_idx, grp_rev_idx, total_rev_idx = 4, 9, 17
            
        # 1. 하단 상세 리포트용 데이터프레임 생성
        df_clean = pd.DataFrame()
        df_clean['Date'] = df_data['Date']
        df_clean['DateStr'] = df_clean['Date'].dt.strftime('%Y-%m-%d')
        df_clean['WeekDay'] = df_clean['Date'].dt.strftime('%a')
        
        # Total 섹션 기준 데이터 추출
        base_idx = total_rms_idx 
        
        df_clean['RMS'] = safe_num(base_idx)
        df_clean['OCC'] = safe_num(base_idx + 1)
        df_clean['ADR'] = safe_num(base_idx + 2)
        df_clean['RevPAR'] = safe_num(base_idx + 3)
        df_clean['REV'] = safe_num(base_idx + 4)
        
        # HU(하우스유즈), Comp(무료)는 Total RMS 바로 앞에 위치한다고 가정
        df_clean['HU'] = safe_num(base_idx - 2)
        df_clean['Comp'] = safe_num(base_idx - 1)

        # 2. 상단 S.O.B 요약용 합계 데이터 계산
        # [중요] 저장 오류 방지를 위해 int/float로 명시적 변환
        fit_rms_sum = int(safe_num(fit_rms_idx).sum())
        fit_rev_sum = int(safe_num(fit_rev_idx).sum())
        
        grp_rms_sum = int(safe_num(grp_rms_idx).sum())
        grp_rev_sum = int(safe_num(grp_rev_idx).sum())
        
        # Total OCC 재계산 (가중평균)
        # 공식: RMS / (OCC/100) = 가동가능객실수(Avail)
        avail_daily = df_clean['RMS'] / (df_clean['OCC'].replace(0, np.nan) / 100)
        total_avail = avail_daily.fillna(0).sum()
        total_rms = int(df_clean['RMS'].sum())
        
        total_occ_pct = 0.0
        if total_avail > 0:
            total_occ_pct = float((total_rms / total_avail * 100))

        sob_data = {
            'FIT_RMS': fit_rms_sum, 'FIT_REV': fit_rev_sum,
            'GRP_RMS': grp_rms_sum, 'GRP_REV': grp_rev_sum,
            'TOTAL_OCC': total_occ_pct
        }
        
        # 해당 파일이 몇 월 데이터인지 리턴 (탭 분류용)
        month_num = df_data['Date'].iloc[0].month
        
        return df_clean, month_num, sob_data

    except Exception as e:
        # 에러 발생 시 로그를 찍거나 None 반환
        return None, None, None

def get_data_by_date(target_date_str, month_num):
    """DB에서 특정 날짜의 데이터를 가져옵니다 (비교 데이터용)."""
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
    """DB에서 데이터프레임과 S.O.B 정보를 모두 가져옵니다 (조회 모드용)."""
    try:
        doc_ref = db.collection('daily_snapshots').document(target_date_str)\
                    .collection('months').document(str(month_num))
        doc = doc_ref.get()
        if doc.exists:
            data = doc.to_dict()
            df = pd.read_json(io.StringIO(data['json_data']), orient='records')
            sob = data.get('sob_data', None)
            
            # S.O.B 데이터가 없는 옛날 데이터 호환성 처리
            if sob is None and not df.empty:
                sob = {'FIT_RMS':0, 'FIT_REV':0, 'GRP_RMS':0, 'GRP_REV':0, 'TOTAL_OCC': df['OCC'].mean()}
            return df, sob
    except Exception:
        return None, None
    return None, None

def save_data_with_sob(target_date_str, month_num, df, sob_data):
    """데이터프레임과 S.O.B 정보를 Firestore에 저장합니다."""
    try:
        json_str = df.to_json(orient='records', date_format='iso')
        
        # 메인 문서 업데이트 (생성 시간 기록)
        db.collection('daily_snapshots').document(target_date_str).set({
            'created_at': firestore.SERVER_TIMESTAMP
        }, merge=True)
        
        # 월별 서브 컬렉션에 데이터 저장
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
    """
    상단 KPI 대시보드를 그리는 함수입니다. 
    textwrap.dedent를 사용하여 코드 블록으로 잘못 렌더링되는 것을 방지함.
    """
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
# 4. 메인 실행 로직 (Sidebar & Tabs)
# ==============================================================================
st.sidebar.header("⚙️ Report Settings")
report_date = st.sidebar.date_input("기준 일자 (오늘)", datetime.now())
report_date_str = report_date.strftime("%Y-%m-%d")

compare_date = st.sidebar.date_input("비교 일자 (어제)", report_date - timedelta(days=1))
compare_date_str = compare_date.strftime("%Y-%m-%d")

st.title(f"🏨 Daily Pace Report")
st.caption("어제와 오늘 파일을 모두 업로드하면, 자동으로 날짜를 비교하여 변화량을 계산합니다.")

# 파일 업로드 (여러 개 가능)
uploaded_files = st.file_uploader("엑셀 파일 업로드", accept_multiple_files=True, type=['xlsx'])

# [수정] 월별 탭 생성 (1~12월)
tabs = st.tabs([f"{i}월" for i in range(1, 13)])
month_files_map = {i: [] for i in range(1, 13)}

# 업로드된 파일 처리 및 분류
if uploaded_files:
    for file in uploaded_files:
        df, month, sob = find_header_and_process(file)
        if df is not None and month in month_files_map:
            # 파일 이름도 함께 저장 (이름순 정렬을 위해)
            month_files_map[month].append({'name': file.name, 'data': df, 'sob': sob})

# 각 탭별로 반복하며 데이터 렌더링
for i, tab in enumerate(tabs):
    current_month = i + 1
    with tab:
        files = month_files_map.get(current_month, [])
        
        df_curr = None
        df_prev = None
        sob_curr = None
        
        # ----------------------------------------------------
        # [데이터 로드 로직]
        # 파일이 있으면 파일을 우선, 없으면 DB를 조회
        # ----------------------------------------------------
        if files:
            # 파일이 2개 이상일 경우: 파일 이름순으로 정렬하여 비교
            # (이름이 뒤인 것이 최신 날짜라고 가정 - 2026-01-21이 2026-01-20보다 뒤)
            if len(files) >= 2:
                files.sort(key=lambda x: x['name'])
                
                f_prev = files[-2] # 뒤에서 두 번째 (어제)
                f_curr = files[-1] # 맨 마지막 (오늘)
                
                df_curr = f_curr['data']
                sob_curr = f_curr['sob']
                df_prev = f_prev['data']
                
                st.caption(f"🔥 파일 비교 모드: {f_prev['name']} (Pre) vs {f_curr['name']} (Today)")
            
            # 파일이 1개일 경우: 해당 파일 vs DB의 비교일자 데이터
            else:
                df_curr = files[0]['data']
                sob_curr = files[0]['sob']
                df_prev = get_data_by_date(compare_date_str, current_month)
                st.caption(f"📂 파일 vs DB 비교 모드 ({files[0]['name']} vs {compare_date_str})")
        
        else:
            # 파일 없음: DB에서 기준일자 vs 비교일자 데이터 조회
            df_curr, sob_curr = get_full_data_by_date(report_date_str, current_month)
            if df_curr is not None:
                df_prev, _ = get_full_data_by_date(compare_date_str, current_month)
                st.caption(f"☁️ DB 조회 모드 ({report_date_str} vs {compare_date_str})")
            else:
                st.info(f"📂 {current_month}월 데이터가 없습니다.")
                continue

        # 예산 가져오기
        budget = BUDGET_DATA.get(current_month, 0)
        
        # S.O.B 데이터가 비어있을 경우 안전장치
        if sob_curr is None and df_curr is not None:
             sob_curr = {'FIT_RMS': 0, 'FIT_REV': 0, 'GRP_RMS': 0, 'GRP_REV': 0, 'TOTAL_OCC': 0}

        # ----------------------------------------------------
        # [A] 상단 대시보드 렌더링
        # ----------------------------------------------------
        # 필요한 값들 미리 계산
        total_rev_val = sob_curr['FIT_REV'] + sob_curr['GRP_REV']
        vs_budget_val = total_rev_val - budget
        achv_rate_val = (total_rev_val / budget * 100) if budget > 0 else 0
        
        total_rms_val = sob_curr['FIT_RMS'] + sob_curr['GRP_RMS']
        total_adr_val = (total_rev_val / total_rms_val) if total_rms_val > 0 else 0
        
        fit_adr_val = (sob_curr['FIT_REV'] / sob_curr['FIT_RMS']) if sob_curr['FIT_RMS'] > 0 else 0
        grp_adr_val = (sob_curr['GRP_REV'] / sob_curr['GRP_RMS']) if sob_curr['GRP_RMS'] > 0 else 0

        render_sob_dashboard(
            current_month=current_month,
            budget=budget,
            total_rev=total_rev_val,
            vs_budget=vs_budget_val,
            achv_rate=achv_rate_val,
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

        # ----------------------------------------------------
        # [B] 하단 상세 리포트 데이터 병합 및 계산
        # ----------------------------------------------------
        # 1. 컬럼 정의
        cols_base = ['DateStr', 'WeekDay', 'HU', 'Comp', 'RMS', 'OCC', 'ADR', 'RevPAR', 'REV']
        cols_curr = ['Date', 'Day', 'Curr_HU', 'Curr_Comp', 'Curr_RMS', 'Curr_OCC', 'Curr_ADR', 'Curr_RevPAR', 'Curr_REV']
        
        display_df = df_curr[cols_base].copy()
        display_df.columns = cols_curr

        # 2. 비교 데이터(Pre) 병합
        if df_prev is not None:
            # 날짜 형식 통일 (문자열로 변환하여 매핑)
            if 'DateStr' not in df_prev.columns:
                df_prev['Date'] = pd.to_datetime(df_prev['Date'])
                df_prev['DateStr'] = df_prev['Date'].dt.strftime('%Y-%m-%d')
            
            prev_subset = df_prev[cols_base].copy()
            prev_subset.columns = ['DateStr', 'Day_p', 'HU_prev', 'Comp_prev', 'RMS_prev', 'OCC_prev', 'ADR_prev', 'RevPAR_prev', 'REV_prev']
            prev_subset = prev_subset.drop(columns=['Day_p'])
            
            # Key 타입 맞추기
            display_df['DateStr_Key'] = display_df['Date'].astype(str)
            prev_subset['DateStr_Key'] = prev_subset['DateStr'].astype(str)
            
            merged = pd.merge(display_df, prev_subset, left_on='DateStr_Key', right_on='DateStr_Key', how='left')
            
            # 결측치 채우기 (비교 데이터가 없으면 0이나 현재값으로 대체)
            for col in ['HU', 'Comp', 'RMS', 'OCC', 'ADR', 'RevPAR', 'REV']:
                merged[f'{col}_prev'] = merged[f'{col}_prev'].fillna(merged[f'Curr_{col}'])
        else:
            # 비교 데이터가 아예 없으면 현재 데이터와 동일하게 처리
            merged = display_df.copy()
            for col in ['HU', 'Comp', 'RMS', 'OCC', 'ADR', 'RevPAR', 'REV']:
                merged[f'{col}_prev'] = merged[f'Curr_{col}']

        # 3. 변화량(PickUp) 계산
        for col in ['HU', 'Comp', 'RMS', 'OCC', 'ADR', 'RevPAR', 'REV']:
            merged[f'Pick_{col}'] = merged[f'Curr_{col}'] - merged[f'{col}_prev']

        # 4. 합계(Total) 행 계산
        sum_cols = []
        for prefix in ['Curr', 'prev', 'Pick']:
            for item in ['HU', 'Comp', 'RMS', 'REV']:
                if prefix == 'prev': item_col = f'{item}_prev'
                elif prefix == 'Pick': item_col = f'Pick_{item}'
                else: item_col = f'{prefix}_{item}'
                sum_cols.append(item_col)
        
        totals = merged[sum_cols].sum()

        # ADR, OCC, RevPAR 가중평균 재계산 함수
        def calc_rates(prefix):
            s_rms = totals[f'{prefix}RMS'] if prefix == 'Curr_' else totals[f'RMS{prefix}']
            s_rev = totals[f'{prefix}REV'] if prefix == 'Curr_' else totals[f'REV{prefix}']
            
            if prefix == 'Curr_':
                avail = merged['Curr_RMS'] / (merged['Curr_OCC'].replace(0, np.nan) / 100)
            else:
                avail = merged['RMS_prev'] / (merged['OCC_prev'].replace(0, np.nan) / 100)
            
            total_avail = avail.fillna(0).sum()
            
            t_adr = (s_rev / s_rms) if s_rms else 0
            t_occ = (s_rms / total_avail * 100) if total_avail else 0
            t_par = (s_rev / total_avail) if total_avail else 0
            return t_adr, t_occ, t_par

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

        # ----------------------------------------------------
        # [C] 컬럼 재배치 (요청하신 순서: 어제 | 오늘 | 변화)
        # ----------------------------------------------------
        final_cols = ['Date', 'Day']
        items = ['HU', 'Comp', 'RMS', 'OCC', 'ADR', 'RevPAR', 'REV']
        
        # 1. 어제 그룹
        for item in items: final_cols.append(f'{item}_prev')
        # 2. 오늘 그룹
        for item in items: final_cols.append(f'Curr_{item}')
        # 3. 변화 그룹
        for item in items: final_cols.append(f'Pick_{item}')
        
        final_df = merged[final_cols].copy()
        
        # 헤더 이름 깔끔하게 정리 (줄바꿈 포함)
        col_map = {'Date':'Date', 'Day':'Day'}
        for item in items:
            col_map[f'{item}_prev'] = f'Pre\n{item}'
            col_map[f'Curr_{item}'] = f'Today\n{item}'
            col_map[f'Pick_{item}'] = f'Var\n{item}'
        final_df.columns = [col_map.get(c, c) for c in final_df.columns]

        # ----------------------------------------------------
        # [D] 스타일링 적용 (Styler) - 컴팩트 사이즈
        # ----------------------------------------------------
        # 숫자 포맷 설정
        fmt = {}
        for col in final_df.columns:
            if 'OCC' in col: fmt[col] = '{:.1f}%'
            elif 'Date' in col or 'Day' in col: continue
            elif 'Var' in col: fmt[col] = '{:+,.0f}'
            else: fmt[col] = '{:,.0f}'
        if 'Var\nOCC' in final_df.columns: fmt['Var\nOCC'] = '{:+.1f}%'

        styler = final_df.style.format(fmt)
        
        # 1. Pre(어제) 그룹: 회색 배경
        pre_cols = [c for c in final_df.columns if 'Pre' in c]
        styler = styler.set_properties(subset=pre_cols, **{
            'background-color': '#f8f9fa', 
            'color': '#9ca3af', 
            'font-size': '11px'
        })
        
        # 2. Today(오늘) 그룹: 파스텔 블루 배경 + 히트맵 적용
        curr_cols = [c for c in final_df.columns if 'Today' in c]
        subset_idx = final_df.index[:-1] # Total행 제외하고 히트맵 적용
        
        # 히트맵 (값: 파랑, 비율: 오렌지)
        styler = styler.background_gradient(cmap='Blues', subset=pd.IndexSlice[subset_idx, [c for c in curr_cols if 'OCC' not in c]], low=0.2, high=0.6)
        styler = styler.background_gradient(cmap='Oranges', subset=pd.IndexSlice[subset_idx, [c for c in curr_cols if 'OCC' in c]], low=0.4, high=0.7)
        
        # Today 컬럼 테두리 강조 + 폰트 설정
        styler = styler.set_properties(subset=curr_cols, **{
            'font-weight': '700', 
            'font-size': '12px', 
            'border-left': '1px solid #cbd5e1', 
            'border-right': '1px solid #cbd5e1'
        })
        
        # 3. Var(변화) 그룹: 파스텔 노랑 배경 + 텍스트 색상
        var_cols = [c for c in final_df.columns if 'Var' in c]
        
        def color_variant(val):
            # 마이너스면 빨강, 플러스면 초록, 0이면 기본색
            color = '#dc2626' if val < 0 else '#166534' if val > 0 else '#374151'
            return f'color: {color}; font-weight: bold;'
            
        styler = styler.map(color_variant, subset=var_cols)
        styler = styler.set_properties(subset=var_cols, **{
            'background-color': '#fffbeb', 
            'font-size': '11px'
        })

        # 4. Total 행 강조 (특히 오늘 데이터 부분 진하게)
        def highlight_total_row(row):
            styles = []
            for col in row.index:
                # 기본 스타일
                base_style = 'background-color: #eff6ff; font-weight: 800; border-top: 2px solid #1d4ed8; font-size: 13px;'
                
                # 오늘 데이터 컬럼은 더 진하게
                if 'Today' in col:
                    base_style += 'background-color: #dbeafe; color: #1e3a8a; font-size: 14px; border-left: 2px solid #1d4ed8; border-right: 2px solid #1d4ed8;'
                
                styles.append(base_style)
            return styles

        styler = styler.apply(lambda x: highlight_total_row(x) if x.name == final_df.index[-1] else ['' for _ in x], axis=1)

        # 화면 출력
        st.dataframe(styler, height=800, use_container_width=True, hide_index=True)

        # ----------------------------------------------------
        # [E] 저장 버튼 (파일이 있을 때만 활성화)
        # ----------------------------------------------------
        if uploaded_files:
            if st.button(f"💾 {report_date.strftime('%Y-%m-%d')}일자 저장", key=f"save_{current_month}"):
                success = save_data_with_sob(report_date.strftime("%Y-%m-%d"), current_month, df_curr, sob_curr)
                if success:
                    st.toast(f"✅ {current_month}월 데이터 저장 완료!", icon="💾")
