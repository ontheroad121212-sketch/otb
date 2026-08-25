import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timedelta
import io
import re  # [추가] 파일명 날짜 추출용
import numpy as np
import textwrap
import secret_forecasting  # 포캐스팅 모듈 임포트
import plotly.express as px
import plotly.graph_objects as go
import os
import traceback  # [추가] 에러 상세 추적용

def _get_firestore_client():
    """firebase-admin 버전 호환 Firestore 클라이언트"""
    _fs = firestore.client
    try:
        return _fs(database="(default)")
    except TypeError:
        return _fs()



# ==============================================================================
# [1] 페이지 기본 설정 및 다국어(중국어) 세션 고정 로직
# ==============================================================================

# [1] 설정
st.set_page_config(layout="wide", page_title="ARI Management")

# [2] 에러 방지용 언어 로직
if 'lang' not in st.session_state:
    st.session_state['lang'] = 'ko'

# URL 파라미터 강제 추출
try:
    u_params = st.query_params
    if u_params.get("lang") == "zh":
        st.session_state['lang'] = 'zh'
    elif u_params.get("lang") == "ko":
        st.session_state['lang'] = 'ko'
except Exception:
    pass

# 최종 결정
is_chairman_mode = (st.session_state.get('lang') == 'zh')

# [강제 출력 테스트]
if is_chairman_mode:
    st.error("현재 모드: 중국어 (ZH)")
else:
    st.info("현재 모드: 한국어 (KO)")

# [번역 사전]
LANG_DICT = {
    "⚙️ Settings": "⚙️ 设置 (Settings)",
    "기준 일자": "基准日期 (Report Date)",
    "비교 일자": "对比日期 (Compare Date)",
    "Admin Key": "管理员密钥 (Admin Key)",
    "✅ Admin Mode On": "✅ 管理员模式已开启 (Admin Mode On)",
    "Navigation": "导航 (Navigation)",
    "Main Report": "主要报告 (Main Report)",
    "🎯 Forecasting": "🎯 预测 (Forecasting)",
    "⏳ 과거 패턴 분석이 필요합니다.": "⏳ 需要分析历史模式。",
    "📊 4만건 히스토리 전체 분석 시작": "📊 开始全量历史数据分析",
    "데이터 고속 도로 개통 중...": "正在建立数据通道...",
    "파이어베이스 서버에 접속 중...": "正在连接 Firebase 服务器...",
    "'hotel_bookings' 데이터를 수색합니다...": "正在搜索 'hotel_bookings' 데이터...",
    "데이터를 업로드하거나 조회하세요.": "请上传或查询数据。",
    "필드를 찾지 못했습니다.": "未找到字段。",
    "실제 데이터 필드명:": "实际数据字段名:",
    "연결 실패 원인": "连接失败原因",
    "과거 패턴 분석 완료": "历史模式分析完成",
    "요일별 가중치 적용 중": "正在应用星期权重",
    "데이터 다시 분석": "重新分析数据",
    "필드 분석 중...": "正在分析字段...",
    "건 분석 완료!": "条数据分析完成!",
    "건의 패턴이 반영되었습니다.": "条数据的模式已反映。",
    "메인 리포트": "主要报告 (Main)",
    "데일리 픽업": "每日数据 (Daily Pick-up)",
    "🏨 Daily Pace Report": "🏨 每日进度报告 (Daily Pace Report)",
    "엑셀 업로드": "上传 Excel (Upload)",
    "월": "月",
    "월 데이터를 업로드하거나 조회하세요.": "月 请上传 or 查询数据。",
    "Performance Summary": "绩效摘要 (Performance Summary)",
    "Budget": "预算 (Budget)",
    "Actual": "实际 (Actual)",
    "Variance": "差异 (Variance)",
    "OCC": "出租率 (OCC)",
    "ACHIEVEMENT": "达成率 (ACHIEVEMENT)",
    "Segment": "细分 (Segment)",
    "RMS": "房晚 (RMS)",
    "ADR": "房价 (ADR)",
    "REV": "收入 (REV)",
    "FIT": "散객 (FIT)",
    "GROUP": "团队 (GROUP)",
    "TOTAL": "총계 (TOTAL)",
    "Date": "날짜",
    "Day": "요일",
    "Pre": "전일",
    "Today": "금일",
    "Var": "증감",
    "월 데이터 DB 저장": "월 데이터 DB 저장",
    "월 데이터가 안전하게 저장되었습니다.": "월 데이터가 안전하게 저장되었습니다.",
    "데이터 없음": "데이터 없음",
    "현재": "현재",
    "건 로드 중...": "건 로드 중...",
    "총": "총",
    "건 수신 완료! 지표 계산 시작...": "건 수신 완료! 지표 계산 시작...",
    "저장할 기준 일자 선택": "저장할 기준 일자 선택",
    "📊 리포트": "📊 리포트 (Report)",
    "📈 시각화": "📈 시각화 (Visual)",
    "일자별 매출 구성 (개인 vs 단체)": "일자별 매출 구성 (개인 vs 단체)",
    "요일별 픽업 히트맵": "요일별 픽업 히트맵",
    "시각화할 데이터가 없습니다.": "시각화할 데이터가 없습니다.",
    "요일별": "요일별"
}

def T(text):
    if is_chairman_mode:
        if text in LANG_DICT:
            return LANG_DICT[text]
        for k, v in LANG_DICT.items():
            if k in str(text):
                return str(text).replace(k, v)
    return text

# CSS 스타일링
st.markdown(textwrap.dedent("""
<style>
    .block-container { padding-top: 0.5rem; padding-bottom: 2rem; }
    .sob-container {
        background-color: white; border-radius: 15px;
        box-shadow: 0 4px 20px rgba(0,0,0,0.08); padding: 30px;
        margin-bottom: 30px; border: 1px solid #e5e7eb;
    }
    .sob-header {
        font-size: 24px; font-weight: 900; color: #111827;
        margin-bottom: 25px; border-bottom: 3px solid #f3f4f6; padding-bottom: 15px;
    }
    .sob-grid { display: grid; grid-template-columns: 1fr 1.3fr; gap: 50px; }
    .modern-table { width: 100%; border-collapse: collapse; }
    .modern-table th { 
        text-align: right; color: #4b5563; font-size: 14px; font-weight: 700;
        padding: 12px 10px; border-bottom: 2px solid #e5e7eb; background-color: #f9fafb;
    }
    .modern-table td { padding: 14px 10px; font-size: 16px; text-align: right; border-bottom: 1px solid #f3f4f6; }
    .modern-table td.label { text-align: left; font-weight: 700; }
    .kpi-wrapper { display: flex; gap: 20px; margin-top: 25px; }
    .kpi-card { flex: 1; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; padding: 20px; text-align: center; }
    .kpi-title { font-size: 14px; color: #64748b; font-weight: 800; }
    .kpi-value { font-size: 32px; color: #0f172a; font-weight: 900; }
    .kpi-accent { background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%); color: white; }
    .kpi-accent .kpi-title, .kpi-accent .kpi-value { color: white; }
    .compact-table-wrapper { overflow-x: auto; margin-bottom: 50px; border: 1px solid #e5e7eb; }
    .compact-table-wrapper table { width: 100%; border-collapse: collapse; font-size: 10px !important; }
    .compact-table-wrapper th { 
        background-color: #f8fafc; padding: 5px 3px !important; border: 1px solid #e2e8f0;
        font-size: 10px !important; line-height: 1.2; text-align: center;
    }
    .compact-table-wrapper td { padding: 4px 3px !important; border: 1px solid #e2e8f0; text-align: right; }
</style>
"""), unsafe_allow_html=True)

# ==============================================================================
# [2] Firebase 연결 및 데이터 함수
# ==============================================================================
if not firebase_admin._apps:
    try:
        key_dict = dict(st.secrets["firebase"])
        cred = credentials.Certificate(key_dict)
        firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"🔥 Firebase 연결 실패: {e}")
        st.stop()

db = _get_firestore_client()

# [타겟 데이터]
TARGET_DATA = {
    1:  {"rn": 2270, "adr": 226869, "occ": 56.3, "rev": 514992575},
    2:  {"rn": 2577, "adr": 305227, "occ": 70.8, "rev": 786570856},
    3:  {"rn": 2248, "adr": 235587, "occ": 55.8, "rev": 529599040},
    4:  {"rn": 2414, "adr": 288049, "occ": 61.9, "rev": 695351004},
    5:  {"rn": 3082, "adr": 293220, "occ": 76.5, "rev": 903705440},
    6:  {"rn": 2776, "adr": 291140, "occ": 71.2, "rev": 808203820},
    7:  {"rn": 3671, "adr": 335590, "occ": 91.1, "rev": 1231949142},
    8:  {"rn": 3873, "adr": 358476, "occ": 96.1, "rev": 1388376999},
    9:  {"rn": 2932, "adr": 324752, "occ": 75.2, "rev": 952171506},
    10: {"rn": 3009, "adr": 298163, "occ": 74.7, "rev": 897171539},
    11: {"rn": 2402, "adr": 277746, "occ": 61.6, "rev": 667146771},
    12: {"rn": 2765, "adr": 290788, "occ": 68.6, "rev": 804030110}
}


# ==============================================================================
# [신규 함수 1] 파일명에서 날짜 추출
# ==============================================================================
def extract_date_from_filename(filename):
    """
    파일명에서 날짜를 추출하여 'YYYY-MM-DD' 문자열로 반환.
    지원 패턴:
      - 20251210, 2025-12-10, 2025.12.10, 2025_12_10 (8자리)
      - 251210, 25-12-10, 25.12.10 (6자리, 20xx로 변환)
    실패 시 None 반환.
    """
    name = filename.lower()
    # 확장자 제거
    name = re.sub(r'\.(xlsx|xls|csv)$', '', name)
    
    # 패턴 1: YYYYMMDD (8자리 연속) 또는 YYYY-MM-DD 등
    m = re.search(r'(20\d{2})[-_./]?(\d{2})[-_./]?(\d{2})', name)
    if m:
        try:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 1 <= mo <= 12 and 1 <= d <= 31:
                return f"{y:04d}-{mo:02d}-{d:02d}"
        except (ValueError, TypeError):
            pass
    
    # 패턴 2: YYMMDD (6자리, 25 → 2025)
    m = re.search(r'(?<!\d)(\d{2})[-_./]?(\d{2})[-_./]?(\d{2})(?!\d)', name)
    if m:
        try:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 0 <= y <= 99 and 1 <= mo <= 12 and 1 <= d <= 31:
                full_year = 2000 + y
                return f"{full_year:04d}-{mo:02d}-{d:02d}"
        except (ValueError, TypeError):
            pass
    
    return None


def load_all_historical_data():
    db = _get_firestore_client()
    st.write(T("파이어베이스 서버에 접속 중..."))
    docs = db.collection("hotel_bookings").stream()
    data = []
    count = 0
    status_text = st.empty()
    for doc in docs:
        data.append(doc.to_dict())
        count += 1
        if count % 2000 == 0:
            status_text.write(T("현재 {count:,}건 로드 중...").format(count=count))
    if not data: return {}, 0
    df = pd.DataFrame(data)
    st.write(T("총 {count:,}건 수신 완료! 지표 계산 시작...").format(count=len(df)))
    bd_col = next((c for c in df.columns if c.lower() in ['booking_date', 'created_at', 'reservation_date', 'date']), None)
    if bd_col:
        df['b_date'] = pd.to_datetime(df[bd_col], errors='coerce')
        df = df.dropna(subset=['b_date'])
        df['dow'] = df['b_date'].dt.dayofweek
        dow_indices = (df['dow'].value_counts(normalize=True) * 7).to_dict()
    else:
        st.error(T("필드를 찾지 못했습니다."))
        dow_indices = {i: 1.0 for i in range(7)}
    cust_col = next((c for c in df.columns if c.lower() in ['customer_id', 'phone', 'guest_name']), None)
    repeat_rate = (df[cust_col].value_counts() > 1).mean() * 100 if cust_col else 0
    return dow_indices, repeat_rate


# [강력한 숫자 변환 함수]
def clean_num(val):
    try:
        if pd.isna(val) or str(val).strip() == '': return 0
        s = str(val).replace(',', '').replace('₩', '').replace(' ', '').replace('%', '').strip()
        return float(s)
    except (ValueError, TypeError):
        return 0


def find_header_and_process(file):
    """
    [지배인님 확정 좌표 강제 추출]
    - 파일 형식 자동 감지
    - 5행(Index 4)부터 데이터 시작
    - C열(2), F열(5), H열(7), K열(10) 고정
    """
    try:
        file.seek(0)
        df_raw = None
        
        try:
            df_raw = pd.read_excel(file, header=None)
        except Exception:
            try:
                file.seek(0)
                df_raw = pd.read_csv(file, header=None)
            except Exception:
                file.seek(0)
                df_raw = pd.read_csv(file, header=None, encoding='cp949')
        
        if df_raw is None or len(df_raw) < 5:
            return None, None, None

        df_data = df_raw.iloc[4:].copy()
        
        df_data['Date'] = pd.to_datetime(df_data.iloc[:, 0], errors='coerce')
        df_data = df_data.dropna(subset=['Date'])
        
        if df_data.empty: return None, None, None

        def safe_col(idx):
            if idx >= len(df_data.columns): return pd.Series(0, index=df_data.index)
            return df_data.iloc[:, idx].apply(clean_num)

        df_clean = pd.DataFrame()
        df_clean['Date'] = df_data['Date']
        df_clean['DateStr'] = df_data['Date'].dt.strftime('%Y-%m-%d')
        df_clean['WeekDay'] = df_data.iloc[:, 1].astype(str)
        
        df_clean['FIT_RMS'] = safe_col(2)   # C
        df_clean['FIT_REV'] = safe_col(5)   # F
        df_clean['GRP_RMS'] = safe_col(7)   # H
        df_clean['GRP_REV'] = safe_col(10)  # K
        df_clean['RMS']     = safe_col(14)  # O
        df_clean['REV']     = safe_col(18)  # S
        
        df_clean['HU']     = safe_col(12)
        df_clean['Comp']   = safe_col(13)
        df_clean['OCC']    = safe_col(15)
        df_clean['ADR']    = safe_col(16)
        df_clean['RevPAR'] = safe_col(17)

        sob_data = {
            'FIT_RMS': int(df_clean['FIT_RMS'].sum()),
            'FIT_REV': int(df_clean['FIT_REV'].sum()),
            'GRP_RMS': int(df_clean['GRP_RMS'].sum()),
            'GRP_REV': int(df_clean['GRP_REV'].sum()),
            'TOTAL_OCC': float(df_clean['OCC'].mean()) if not df_clean['OCC'].empty else 0
        }
        
        return df_clean, int(df_data['Date'].iloc[0].month), sob_data
        
    except Exception as e:
        st.session_state['last_upload_error'] = f"{type(e).__name__}: {e}"
        return None, None, None


def get_full_data_by_date(date_str, month_num):
    """date_str의 month_num 스냅샷 로드"""
    try:
        doc = db.collection('daily_snapshots').document(date_str).collection('months').document(str(month_num)).get()
        if doc.exists:
            d = doc.to_dict()
            df = pd.read_json(io.StringIO(d['json_data']), orient='records')
            required_cols = ['FIT_RMS', 'FIT_REV', 'GRP_RMS', 'GRP_REV', 'RMS', 'REV', 'HU', 'Comp', 'OCC', 'ADR', 'RevPAR']
            for c in required_cols:
                if c not in df.columns: df[c] = 0
            return df, d.get('sob_data')
    except Exception as e:
        st.session_state[f'db_load_err_{month_num}'] = f"{type(e).__name__}: {e}"
    return None, None


def get_latest_snapshot_before(target_date_str, month_num, exclude_date=None):
    """target_date 이전의 가장 최근 스냅샷"""
    try:
        docs = db.collection_group('months').stream()
        candidate_dates = []
        for doc in docs:
            if doc.id != str(month_num): continue
            date_str = doc.reference.parent.parent.id
            if exclude_date and date_str == exclude_date: continue
            if date_str < target_date_str:
                candidate_dates.append(date_str)
        
        if not candidate_dates: return None, None, None
        
        latest = max(candidate_dates)
        df, sob = get_full_data_by_date(latest, month_num)
        return df, sob, latest
    except Exception:
        return None, None, None


# ==============================================================================
# [신규 함수 2] 특정 월의 모든 스냅샷 날짜 리스트
# ==============================================================================
@st.cache_data(ttl=60)
def get_all_snapshot_dates_for_month(month_num):
    """해당 월(month_num)에 대해 저장된 모든 스냅샷 날짜를 정렬해 반환"""
    try:
        db_local = _get_firestore_client()
        docs = db_local.collection_group('months').stream()
        dates = []
        for doc in docs:
            if doc.id == str(month_num):
                dates.append(doc.reference.parent.parent.id)
        return sorted(dates)
    except Exception:
        return []


def get_latest_snapshot_for_month(month_num):
    """
    [신규] 해당 월의 가장 마지막에 저장된 스냅샷을 반환.
    과거 월(예: 5월 시점의 1~4월) 자동 로드용.
    """
    dates = get_all_snapshot_dates_for_month(month_num)
    if not dates: return None, None, None
    latest = dates[-1]
    df, sob = get_full_data_by_date(latest, month_num)
    if df is None: return None, None, None
    return df, sob, latest


def get_second_latest_snapshot_for_month(month_num, exclude_date=None):
    """[신규] 마지막에서 두 번째 스냅샷 (과거 월의 비교용)"""
    dates = get_all_snapshot_dates_for_month(month_num)
    if exclude_date:
        dates = [d for d in dates if d != exclude_date]
    if len(dates) == 0: 
        return None, None, None
    if len(dates) == 1:
        # 한 개밖에 없으면 그것이라도 반환
        df, sob = get_full_data_by_date(dates[0], month_num)
        return df, sob, dates[0]
    second_latest = dates[-2]
    df, sob = get_full_data_by_date(second_latest, month_num)
    return df, sob, second_latest


def save_data_with_sob(date_str, month, df, sob):
    """저장. (success, err_msg) 반환"""
    try:
        db.collection('daily_snapshots').document(date_str).set(
            {'created_at': firestore.SERVER_TIMESTAMP}, merge=True
        )
        db.collection('daily_snapshots').document(date_str).collection('months').document(str(month)).set({
            'json_data': df.to_json(orient='records'),
            'sob_data': sob,
            'updated_at': firestore.SERVER_TIMESTAMP
        })
        return True, None
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


@st.cache_data(ttl=300)
def load_daily_summary_matrix():
    try:
        db = _get_firestore_client()
        docs = db.collection_group('months').stream()
        data = []
        for doc in docs:
            try:
                month_num = int(doc.id)
            except (ValueError, TypeError):
                continue
            date_str = doc.reference.parent.parent.id
            d = doc.to_dict()
            sob = d.get('sob_data', {})
            if sob:
                rev = sob.get('FIT_REV', 0) + sob.get('GRP_REV', 0)
                rn = sob.get('FIT_RMS', 0) + sob.get('GRP_RMS', 0)
                data.append({'Date': date_str, 'Month': f"{month_num}월", 'Rev': rev, 'RN': rn})
                
        if not data: return None, None
        
        df = pd.DataFrame(data)
        
        df_rev = df.pivot_table(index='Date', columns='Month', values='Rev', aggfunc='sum').fillna(0)
        df_rn = df.pivot_table(index='Date', columns='Month', values='RN', aggfunc='sum').fillna(0)
        
        month_cols = [f"{m}월" for m in range(1, 13)]
        for c in month_cols:
            if c not in df_rev.columns: df_rev[c] = 0
            if c not in df_rn.columns: df_rn[c] = 0
            
        return df_rev[month_cols].sort_index(), df_rn[month_cols].sort_index()
    except Exception:
        return None, None

# ==============================================================================
# [3] 메인 화면 UI 및 사이드바
# ==============================================================================
if is_chairman_mode:
    st.markdown('<style>[data-testid="stSidebarNav"] {display: none;}</style>', unsafe_allow_html=True)
    with st.sidebar:
        st.title("Navigation")
        st.page_link("streamlit_app.py", label=T("메인 리포트"), icon="🏠")
        st.page_link("pages/03_Daily_Pick-up & Wash-out.py", label=T("데일리 픽업"), icon="📅")
        st.divider()

st.sidebar.header(T("⚙️ Settings"))

now_kst = datetime.now() + timedelta(hours=9)
today_kst = now_kst.date()

report_date = st.sidebar.date_input(T("기준 일자"), value=today_kst, max_value=today_kst)
compare_date = st.sidebar.date_input(T("비교 일자"), value=today_kst - timedelta(days=1), max_value=today_kst)

# [신규] 자동화 옵션들
st.sidebar.divider()
st.sidebar.markdown("**🤖 자동화 옵션**")

auto_save_on_upload = st.sidebar.checkbox(
    "📤 업로드 시 파일명 일자로 자동 저장",
    value=True,
    help="파일명에서 날짜(예: 12월_20251210.xlsx → 2025-12-10)를 추출해 자동으로 DB에 저장합니다."
)

auto_load_past_months = st.sidebar.checkbox(
    "📅 과거 월 자동 로드 (최신 스냅샷)",
    value=True,
    help="현재 월 이전의 월들은 파일을 올리지 않아도 가장 마지막 저장 스냅샷을 자동으로 표시합니다."
)

auto_fallback = st.sidebar.checkbox(
    "🔄 비교일자 데이터 없으면 가장 가까운 이전 스냅샷 사용",
    value=True,
    help="비교 일자에 저장된 스냅샷이 없을 때, 그 이전의 가장 최근 스냅샷을 자동으로 찾아 비교합니다."
)
st.sidebar.divider()

admin_key = st.sidebar.text_input(T("Admin Key"), type="password")
if admin_key == "master136":
    st.session_state["authenticated"] = True

selected_page = T("Main Report")
if st.session_state.get("authenticated"):
    st.sidebar.success(T("✅ Admin Mode On"))
    selected_page = st.sidebar.radio(T("Navigation"), [T("Main Report"), T("📈 Daily Tracking"), T("🎯 Forecasting")])
    if "historical_dow" not in st.session_state:
        if st.sidebar.button(T("📊 4만건 히스토리 전체 분석 시작")):
            with st.sidebar.status(T("데이터 수색 중..."), expanded=True) as status:
                try:
                    cache_file = "hotel_bookings_cache.pkl"
                    h_df = None

                    if os.path.exists(cache_file):
                        st.sidebar.write(T("✅ 캐시 파일에서 로드! (비용 0원)"))
                        h_df = pd.read_pickle(cache_file)
                    else:
                        db = _get_firestore_client()
                        docs = db.collection_group("hotel_bookings").stream()
                        hist_data = []
                        count = 0
                        status_text = st.sidebar.empty()
                        for doc in docs:
                            hist_data.append(doc.to_dict())
                            count += 1
                            if count % 2000 == 0:
                                status_text.write(T("현재 {count:,}건 로드 중...").format(count=count))
                        
                        if count > 0:
                            h_df = pd.DataFrame(hist_data)
                            h_df.to_pickle(cache_file)
                    
                    if h_df is not None and not h_df.empty:
                        h_df['b_date'] = pd.to_datetime(h_df['예약일자'], errors='coerce')
                        h_df = h_df.dropna(subset=['b_date'])
                        h_df['dow'] = h_df['b_date'].dt.dayofweek
                        st.session_state["historical_dow"] = (h_df['dow'].value_counts(normalize=True) * 7).to_dict()
                        status.update(label=T("✅ 분석 완료!"), state="complete")
                        st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")

if selected_page == "🎯 Forecasting" or selected_page == T("🎯 Forecasting"):
    secret_forecasting.run_forecasting()
    st.stop()

# ----------------------------------------------------------------------
# 🌟 [Daily Tracking 페이지]
# ----------------------------------------------------------------------
elif selected_page == "📈 Daily Tracking" or selected_page == T("📈 Daily Tracking"):
    st.title(T("📈 Daily Tracking & Pace Analysis"))
    
    df_rev, df_rn = load_daily_summary_matrix()
    if df_rev is None or df_rev.empty:
        st.info(T("저장된 일자별 요약 데이터가 없습니다. Main Report에서 데이터를 먼저 저장해 주세요."))
        st.stop()
    
    dt_tab1, dt_tab2 = st.tabs(["📅 데일리 매트릭스 (Daily Matrix)", "🎯 페이스 & 분기 분석 (Pace & Quarterly)"])
    
    with dt_tab1:
        view_type = st.radio("보기 옵션 (View Type)", ["💰 총 매출 (Revenue)", "🛏️ 총 객실수 (Room Nights)"], horizontal=True)
        target_df = df_rev if "매출" in view_type else df_rn
        
        st.markdown("### 1️⃣ 누적 총합 (Cumulative OTB)")
        st.dataframe(target_df.style.format("{:,.0f}").background_gradient(cmap="Blues", axis=0), use_container_width=True)
        
        st.markdown("### 2️⃣ 전일 대비 픽업 및 증감률 (Pick-up & %)")
        combined_df = pd.DataFrame(index=target_df.index, columns=target_df.columns)
        shifted_df = target_df.shift(1)
        
        for col in target_df.columns:
            for idx in target_df.index:
                curr = target_df.at[idx, col]
                prev = shifted_df.at[idx, col]
                if pd.isna(prev):
                    combined_df.at[idx, col] = "-"
                    continue
                diff = curr - prev
                if diff == 0:
                    combined_df.at[idx, col] = "-"
                else:
                    pct = (diff / prev * 100) if prev != 0 else 100.0
                    sign = "+" if diff > 0 else ""
                    combined_df.at[idx, col] = f"{sign}{diff:,.0f} ({sign}{pct:,.1f}%)"
                    
        def color_combined(val):
            if isinstance(val, str):
                if val.startswith("+"): return 'color: #166534; font-weight: bold; background-color: #f0fdf4;'
                elif val.startswith("-") and val != "-": return 'color: #dc2626; font-weight: bold; background-color: #fef2f2;'
            return 'color: #9ca3af;'
            
        st.dataframe(combined_df.style.map(color_combined), use_container_width=True)

    with dt_tab2:
        st.subheader("📊 분기별 타겟 달성 현황 (Quarterly Target)")
        st.caption("※ 4,5월이 오버버짓하면 6월의 부족분을 상쇄할 수 있는지 확인하는 통합 뷰입니다.")
        
        current_year = datetime.now().year
        q_data = []
        for q in range(1, 5):
            months = [q*3-2, q*3-1, q*3]
            q_target_rn = sum([TARGET_DATA[m]['rn'] for m in months])
            q_target_rev = sum([TARGET_DATA[m]['rev'] for m in months])
            
            q_curr_rn = 0
            q_curr_rev = 0
            for m in months:
                col = f"{m}월"
                if col in df_rn.columns and not df_rn[col].empty:
                    q_curr_rn += df_rn[col].iloc[-1]
                if col in df_rev.columns and not df_rev[col].empty:
                    q_curr_rev += df_rev[col].iloc[-1]
            
            rn_achieve = (q_curr_rn / q_target_rn * 100) if q_target_rn > 0 else 0
            
            q_data.append({
                "Quarter": f"Q{q}", "Target RN": q_target_rn, "OTB RN": q_curr_rn, "Achievement": rn_achieve,
                "Diff RN": q_curr_rn - q_target_rn, "Months": f"{months[0]}월~{months[2]}월"
            })
            
        q_df = pd.DataFrame(q_data)
        
        cols = st.columns(4)
        for idx, row in q_df.iterrows():
            with cols[idx]:
                st.info(f"**{row['Quarter']} ({row['Months']})**")
                st.metric("OTB RN", f"{row['OTB RN']:,.0f}", f"{row['Diff RN']:+,.0f} vs Target")
                st.progress(min(row['Achievement']/100, 1.0))
                st.caption(f"🎯 Target RN: {row['Target RN']:,.0f} ({row['Achievement']:.1f}%)")

        st.divider()

        st.subheader("🚀 현재 속도 기반 마감 예측 (Run-Rate Projection)")
        st.caption("※ 최근 7일간의 예약 속도(Velocity)를 바탕으로 월말 최종 객실수(RN)를 예측합니다.")
        
        proj_data = []
        today = datetime.now()
        
        for m in range(today.month, 13):
            m_str = f"{m}월"
            if m_str not in df_rn.columns: continue
            if df_rn[m_str].empty: continue
            
            target_rn = TARGET_DATA[m]['rn']
            curr_rn = df_rn[m_str].iloc[-1]
            
            if len(df_rn) >= 7:
                pickup_7d = df_rn[m_str].iloc[-1] - df_rn[m_str].iloc[-7]
                run_rate = pickup_7d / 7
            elif len(df_rn) > 1:
                pickup_all = df_rn[m_str].iloc[-1] - df_rn[m_str].iloc[0]
                run_rate = pickup_all / (len(df_rn) - 1)
            else:
                run_rate = 0
                
            if m == 12:
                last_day = datetime(current_year + 1, 1, 1) - timedelta(days=1)
            else:
                last_day = datetime(current_year, m + 1, 1) - timedelta(days=1)
                
            days_remaining = (last_day.date() - today.date()).days
            if days_remaining < 0: days_remaining = 0
            
            projected_rn = curr_rn + (run_rate * days_remaining)
            diff_to_target = projected_rn - target_rn
            
            if diff_to_target >= target_rn * 0.05: status = "🔥 매우 빠름 (단가 인상 고려)"
            elif diff_to_target >= 0: status = "✅ 정상 궤도 (On-Pace)"
            elif diff_to_target >= -target_rn * 0.1: status = "⚠️ 주의 (Slightly Slow)"
            else: status = "🚨 심각한 지연 (프로모션 필요)"
            
            proj_data.append({
                "월 (Month)": m_str,
                "목표 (Target RN)": target_rn,
                "현재 (Current OTB)": curr_rn,
                "최근 7일 속도 (RN/Day)": run_rate,
                "예측 마감 (Projected)": projected_rn,
                "예측-목표 차이": diff_to_target,
                "상태 (Status)": status
            })
            
        if proj_data:
            proj_df = pd.DataFrame(proj_data)
            st.dataframe(
                proj_df.style.format({
                    "목표 (Target RN)": "{:,.0f}", "현재 (Current OTB)": "{:,.0f}",
                    "최근 7일 속도 (RN/Day)": "{:,.1f}", "예측 마감 (Projected)": "{:,.0f}",
                    "예측-목표 차이": "{:+,.0f}"
                }).map(lambda v: 'color: #166534; font-weight:bold' if v>0 else 'color: #dc2626; font-weight:bold' if v<0 else '', subset=["예측-목표 차이"]),
                use_container_width=True
            )
        else:
            st.info("예측할 수 있는 진행 중인 월 데이터가 없습니다.")
            
    st.stop()

# ==============================================================================
# Main Report
# ==============================================================================    
st.title(T("🏨 Daily Pace Report"))
uploaded_files = st.file_uploader(T("엑셀 업로드"), accept_multiple_files=True, type=['xlsx', 'csv'])

# [개선] 업로드 에러가 있었으면 표시
if 'last_upload_error' in st.session_state and uploaded_files:
    with st.expander("⚠️ 업로드 처리 중 일부 파일에서 에러 발생 (클릭하여 상세 확인)"):
        st.code(st.session_state['last_upload_error'])

tabs = st.tabs([f"{i}{T('월')}" for i in range(1, 13)])

# ==============================================================================
# [개선] 파일 처리 + 파일명에서 일자 추출 + 자동 저장
# ==============================================================================
month_files_map = {i: [] for i in range(1, 13)}

if uploaded_files:
    auto_save_results = {'success': [], 'failed': [], 'no_date': []}
    
    # 중복 저장 방지 시그니처
    upload_signature = tuple(sorted(f.name for f in uploaded_files))
    already_saved = st.session_state.get('auto_saved_signature') == upload_signature
    
    for f in uploaded_files:
        df, m, sob = find_header_and_process(f)
        if not m: 
            continue
        
        # 파일명에서 일자 추출
        snapshot_date = extract_date_from_filename(f.name)
        date_from_filename = snapshot_date is not None
        if not snapshot_date:
            snapshot_date = today_kst.strftime("%Y-%m-%d")
        
        month_files_map[m].append({
            'name': f.name, 
            'data': df, 
            'sob': sob,
            'snapshot_date': snapshot_date,
            'date_from_filename': date_from_filename
        })
        
        # [핵심] 자동 저장
        if auto_save_on_upload and not already_saved:
            ok, err = save_data_with_sob(snapshot_date, m, df, sob)
            if ok:
                auto_save_results['success'].append({
                    'file': f.name, 'date': snapshot_date, 'month': m,
                    'from_filename': date_from_filename
                })
            else:
                auto_save_results['failed'].append({
                    'file': f.name, 'date': snapshot_date, 'month': m, 'err': err
                })
            if not date_from_filename:
                auto_save_results['no_date'].append(f.name)
    
    # 자동 저장 결과 표시 + 중복 방지 시그니처 기록
    if auto_save_on_upload and not already_saved and (auto_save_results['success'] or auto_save_results['failed']):
        st.session_state['auto_saved_signature'] = upload_signature
        load_daily_summary_matrix.clear()
        get_all_snapshot_dates_for_month.clear()
        
        with st.expander(f"📦 자동 저장 결과 ({len(auto_save_results['success'])}건 성공, {len(auto_save_results['failed'])}건 실패)", expanded=True):
            if auto_save_results['success']:
                st.success(f"✅ {len(auto_save_results['success'])}개 파일이 DB에 자동 저장되었습니다.")
                df_result = pd.DataFrame([
                    {
                        '파일명': s['file'], 
                        '월': f"{s['month']}월", 
                        '저장 일자': s['date'],
                        '인식 방법': '✅ 파일명 자동추출' if s['from_filename'] else '⚠️ 오늘 날짜(파일명 인식 실패)'
                    }
                    for s in auto_save_results['success']
                ])
                st.dataframe(df_result, use_container_width=True, hide_index=True)
            
            if auto_save_results['failed']:
                st.error(f"❌ {len(auto_save_results['failed'])}개 파일 저장 실패")
                for fail in auto_save_results['failed']:
                    st.code(f"{fail['file']} → {fail['err']}")
            
            if auto_save_results['no_date']:
                st.warning(f"⚠️ 파일명에서 일자를 인식하지 못해 **오늘 날짜({today_kst})**로 저장한 파일: {', '.join(auto_save_results['no_date'])}")
                st.caption("📌 파일명 예시: `12월_20251210.xlsx`, `12월 2025-12-10.xlsx`, `251210_12월.xlsx`")


# ==============================================================================
# [4] 탭별 데이터 렌더링
# ==============================================================================
for i, tab in enumerate(tabs):
    cur_m = i + 1
    with tab:
        try:
            files = month_files_map.get(cur_m, [])
            df_curr, sob_curr, df_prev = None, None, None
            prev_source_info = None
            curr_source_info = None
            
            if files:
                # snapshot_date 기준으로 정렬 (가장 최근이 현재, 그 직전이 비교)
                files.sort(key=lambda x: x['snapshot_date'])
                
                if len(files) >= 2:
                    df_curr, sob_curr = files[-1]['data'], files[-1]['sob']
                    df_prev = files[-2]['data']
                    curr_source_info = f"📁 업로드 파일: `{files[-1]['name']}` ({files[-1]['snapshot_date']})"
                    prev_source_info = f"📁 파일 비교: `{files[-2]['name']}` ({files[-2]['snapshot_date']})"
                else:
                    df_curr, sob_curr = files[0]['data'], files[0]['sob']
                    curr_source_info = f"📁 업로드 파일: `{files[0]['name']}` ({files[0]['snapshot_date']})"
                    
                    # 파일의 snapshot_date 기준으로 그 이전 스냅샷을 DB에서 찾기
                    file_snap_date = files[0]['snapshot_date']
                    df_prev, _, found_date = get_latest_snapshot_before(file_snap_date, cur_m, exclude_date=file_snap_date)
                    
                    if df_prev is not None:
                        prev_source_info = f"💾 DB 비교: `{found_date}` 스냅샷 (자동 매칭)"
                    else:
                        compare_date_str = compare_date.strftime("%Y-%m-%d")
                        df_prev, _ = get_full_data_by_date(compare_date_str, cur_m)
                        if df_prev is not None:
                            prev_source_info = f"💾 DB 비교: `{compare_date_str}` 스냅샷"
                        elif auto_fallback:
                            df_prev, _, found_date = get_latest_snapshot_before(compare_date_str, cur_m)
                            if df_prev is not None:
                                prev_source_info = f"🔄 자동 폴백: 가장 가까운 `{found_date}` 사용"
            else:
                # [핵심] 파일 없을 때
                report_date_str = report_date.strftime("%Y-%m-%d")
                is_past_month = cur_m < today_kst.month
                
                if auto_load_past_months and is_past_month:
                    # [신규] 과거 월 자동 로드: 가장 마지막 스냅샷 + 그 직전 스냅샷으로 비교
                    df_curr, sob_curr, latest_date = get_latest_snapshot_for_month(cur_m)
                    if df_curr is not None:
                        curr_source_info = f"📅 과거 월 자동 로드: 최신 스냅샷 `{latest_date}`"
                        df_prev, _, second_date = get_second_latest_snapshot_for_month(cur_m, exclude_date=latest_date)
                        if df_prev is not None and second_date != latest_date:
                            prev_source_info = f"💾 직전 스냅샷 비교: `{second_date}`"
                else:
                    # 기존 로직: report_date 기준
                    df_curr, sob_curr = get_full_data_by_date(report_date_str, cur_m)
                    if df_curr is not None:
                        curr_source_info = f"💾 DB 로드: `{report_date_str}` 스냅샷"
                    
                if df_curr is not None and df_prev is None:
                    compare_date_str = compare_date.strftime("%Y-%m-%d")
                    df_prev, _ = get_full_data_by_date(compare_date_str, cur_m)
                    if df_prev is not None:
                        prev_source_info = f"💾 DB 비교: `{compare_date_str}` 스냅샷"
                    elif auto_fallback:
                        df_prev, _, found_date = get_latest_snapshot_before(compare_date_str, cur_m, exclude_date=report_date_str)
                        if df_prev is not None:
                            prev_source_info = f"🔄 자동 폴백: 가장 가까운 `{found_date}` 사용"

            if df_curr is None:
                st.info(f"{cur_m}{T('월')} {T('데이터를 업로드하거나 조회하세요.')}")
                err_key = f'db_load_err_{cur_m}'
                if err_key in st.session_state:
                    with st.expander(f"⚠️ {cur_m}월 DB 조회 에러 상세"):
                        st.code(st.session_state[err_key])
                continue

            # [신규] 데이터 출처 안내
            col_info1, col_info2 = st.columns(2)
            with col_info1:
                if curr_source_info: st.caption(f"**현재:** {curr_source_info}")
            with col_info2:
                if prev_source_info: 
                    st.caption(f"**비교:** {prev_source_info}")
                else:
                    st.caption("**비교:** ⚠️ 이전 스냅샷 없음 (증감 = 현재값)")

            budget = TARGET_DATA.get(cur_m, {}).get('rev', 0)
            total_rev = sob_curr.get('FIT_REV', 0) + sob_curr.get('GRP_REV', 0)
            total_rms = sob_curr.get('FIT_RMS', 0) + sob_curr.get('GRP_RMS', 0)
            
            st.markdown(f"""
            <div class="sob-container">
                <div class="sob-header">📊 {cur_m}{T('월')} {T('Performance Summary')}</div>
                <div class="sob-grid">
                    <div>
                        <table class="modern-table">
                            <tr><td class="label">{T('Budget')}</td><td>{budget:,.0f}</td></tr>
                            <tr><td class="label">{T('Actual')}</td><td style="font-weight:bold;">{total_rev:,.0f}</td></tr>
                            <tr><td class="label">{T('Variance')}</td><td style="color:{'green' if total_rev>=budget else 'red'}">{total_rev-budget:+,.0f}</td></tr>
                        </table>
                        <div class="kpi-wrapper">
                            <div class="kpi-card"><div class="kpi-title">{T('OCC')}</div><div class="kpi-value">{sob_curr.get('TOTAL_OCC',0):.1f}%</div></div>
                            <div class="kpi-card kpi-accent"><div class="kpi-title">{T('ACHIEVEMENT')}</div><div class="kpi-value">{(total_rev/budget*100) if budget>0 else 0:.1f}%</div></div>
                        </div>
                    </div>
                    <div>
                        <table class="modern-table">
                            <thead><tr><th>{T('Segment')}</th><th>{T('RMS')}</th><th>{T('ADR')}</th><th>{T('REV')}</th></tr></thead>
                            <tr><td class="label">{T('FIT')}</td><td>{sob_curr.get('FIT_RMS',0):,.0f}</td><td>{(sob_curr.get('FIT_REV',0)/max(1,sob_curr.get('FIT_RMS',1))):,.0f}</td><td>{sob_curr.get('FIT_REV',0):,.0f}</td></tr>
                            <tr><td class="label">{T('GROUP')}</td><td>{sob_curr.get('GRP_RMS',0):,.0f}</td><td>{(sob_curr.get('GRP_REV',0)/max(1,sob_curr.get('GRP_RMS',1))):,.0f}</td><td>{sob_curr.get('GRP_REV',0):,.0f}</td></tr>
                            <tr style="background:#eff6ff; font-weight:bold;"><td>{T('TOTAL')}</td><td>{total_rms:,.0f}</td><td>{(total_rev/max(1,total_rms)):,.0f}</td><td>{total_rev:,.0f}</td></tr>
                        </table>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            merged = df_curr.copy()
            if df_prev is not None:
                cols_to_use = ['DateStr', 'HU', 'Comp', 'RMS', 'OCC', 'ADR', 'RevPAR', 'REV']
                for c in ['FIT_RMS', 'FIT_REV', 'GRP_RMS', 'GRP_REV']:
                    if c in df_prev.columns: cols_to_use.append(c)
                
                if 'DateStr' not in df_prev.columns and 'Date' in df_prev.columns:
                    df_prev['DateStr'] = pd.to_datetime(df_prev['Date']).dt.strftime('%Y-%m-%d')
                
                p_sub = df_prev[[c for c in cols_to_use if c in df_prev.columns]].copy()
                for c in ['FIT_RMS', 'FIT_REV', 'GRP_RMS', 'GRP_REV']:
                    if c not in p_sub.columns: p_sub[c] = 0
                
                merged = pd.merge(merged, p_sub, on='DateStr', how='left', suffixes=('', '_prev'))
            else:
                for c in ['HU', 'Comp', 'RMS', 'OCC', 'ADR', 'RevPAR', 'REV', 'FIT_RMS', 'FIT_REV', 'GRP_RMS', 'GRP_REV']: 
                    merged[f'{c}_prev'] = 0

            all_cols = ['FIT_RMS', 'FIT_REV', 'GRP_RMS', 'GRP_REV', 'RMS', 'REV', 'HU', 'Comp', 'OCC', 'ADR', 'RevPAR']
            for c in all_cols:
                if c not in merged.columns: merged[c] = 0
                if f'{c}_prev' not in merged.columns: merged[f'{c}_prev'] = 0
                merged[c] = merged[c].fillna(0)
                merged[f'{c}_prev'] = merged[f'{c}_prev'].fillna(0)
                merged[f'Pick_{c}'] = merged[c] - merged[f'{c}_prev']

            sum_items = ['HU', 'Comp', 'RMS', 'REV', 'HU_prev', 'Comp_prev', 'RMS_prev', 'REV_prev', 'Pick_HU', 'Pick_Comp', 'Pick_RMS', 'Pick_REV']
            valid_sum_items = [x for x in sum_items if x in merged.columns]
            totals = merged[valid_sum_items].sum()
            
            def get_total_rates(prefix_rms, prefix_rev, is_curr=True):
                s_rms = totals.get(prefix_rms, 0)
                s_rev = totals.get(prefix_rev, 0)
                if is_curr: t_occ = merged['OCC'].mean()
                else: t_occ = merged['OCC_prev'].mean()
                t_adr = s_rev / s_rms if s_rms > 0 else 0
                t_par = t_adr * t_occ / 100
                return t_occ, t_adr, t_par

            c_occ, c_adr, c_par = get_total_rates('RMS', 'REV', True)
            p_occ, p_adr, p_par = get_total_rates('RMS_prev', 'REV_prev', False)

            total_row = pd.DataFrame([{
                'DateStr': 'TOTAL', 'WeekDay': '',
                'HU_prev': totals.get('HU_prev', 0), 'Comp_prev': totals.get('Comp_prev', 0), 'RMS_prev': totals.get('RMS_prev', 0), 'REV_prev': totals.get('REV_prev', 0),
                'OCC_prev': p_occ, 'ADR_prev': p_adr, 'RevPAR_prev': p_par,
                'HU': totals.get('HU', 0), 'Comp': totals.get('Comp', 0), 'RMS': totals.get('RMS', 0), 'REV': totals.get('REV', 0),
                'OCC': c_occ, 'ADR': c_adr, 'RevPAR': c_par,
                'Pick_HU': totals.get('Pick_HU', 0), 'Pick_Comp': totals.get('Pick_Comp', 0), 'Pick_RMS': totals.get('Pick_RMS', 0), 'Pick_REV': totals.get('Pick_REV', 0),
                'Pick_OCC': c_occ - p_occ, 'Pick_ADR': c_adr - p_adr, 'Pick_RevPAR': c_par - p_par
            }])
            
            merged_with_total = pd.concat([merged, total_row], ignore_index=True)

            st.session_state[f"sob_{cur_m}"] = sob_curr
            st.session_state[f"pace_{cur_m}"] = totals.get('Pick_RMS', 0)

            sub_t1, sub_t2 = st.tabs([T("📊 리포트"), T("📈 시각화")])
            
            with sub_t1:
                final_df = merged_with_total[['DateStr', 'WeekDay', 
                                              'HU_prev', 'Comp_prev', 'RMS_prev', 'OCC_prev', 'ADR_prev', 'RevPAR_prev', 'REV_prev',
                                              'HU', 'Comp', 'RMS', 'OCC', 'ADR', 'RevPAR', 'REV',
                                              'Pick_HU', 'Pick_Comp', 'Pick_RMS', 'Pick_OCC', 'Pick_ADR', 'Pick_RevPAR', 'Pick_REV']]

                col_map = {'DateStr': T('Date'), 'WeekDay': T('Day')}
                items = ['HU', 'Comp', 'RMS', 'OCC', 'ADR', 'RevPAR', 'REV']
                for it in items:
                    col_map[f'{it}_prev'] = f'{T("Pre")}\n{T(it)}'
                    col_map[it] = f'{T("Today")}\n{T(it)}'
                    col_map[f'Pick_{it}'] = f'{T("Var")}\n{T(it)}'
                final_df.columns = [col_map.get(c, c) for c in final_df.columns]

                fmt = {c: '{:,.0f}' for c in final_df.columns if 'OCC' not in c and T('Date') not in c and T('Day') not in c}
                for c in [c for c in final_df.columns if 'OCC' in c]: fmt[c] = '{:.1f}%'

                styler = final_df.style.format(fmt)
                pre_cols = [c for c in final_df.columns if T('Pre') in c]
                styler = styler.set_properties(subset=pre_cols, **{'background-color': '#f8f9fa', 'color': '#9ca3af'})
                curr_cols = [c for c in final_df.columns if T('Today') in c]
                data_idx = final_df.index[:-1] 
                styler = styler.background_gradient(cmap='Blues', subset=pd.IndexSlice[data_idx, [c for c in curr_cols if 'OCC' not in c]], low=0.2, high=0.6)
                styler = styler.background_gradient(cmap='Oranges', subset=pd.IndexSlice[data_idx, [c for c in curr_cols if 'OCC' in c]], low=0.4, high=0.7)
                var_cols = [c for c in final_df.columns if T('Var') in c]
                def color_pick(val):
                    try:
                        v = float(str(val).replace('%','').replace(',',''))
                        return 'color: #166534; font-weight: bold;' if v > 0 else 'color: #dc2626; font-weight: bold;' if v < 0 else 'color: #374151;'
                    except (ValueError, TypeError):
                        return ''
                styler = styler.map(color_pick, subset=var_cols)
                styler = styler.set_properties(subset=var_cols, **{'background-color': '#fffbeb'})
                styler = styler.set_properties(subset=pd.IndexSlice[final_df.index[-1], :], 
                                               **{'background-color': '#eff6ff', 'font-weight': '900', 'border-top': '2px solid #1d4ed8'})
                st.markdown(f'<div class="compact-table-wrapper">{styler.to_html()}</div>', unsafe_allow_html=True)

            with sub_t2:
                vis_df = merged.copy()
                if not vis_df.empty:
                    st.subheader(T("일자별 매출 구성 (개인 vs 단체)"))
                    m_rev = vis_df.melt(id_vars=['DateStr', 'FIT_RMS', 'GRP_RMS'], 
                                        value_vars=['FIT_REV', 'GRP_REV'],
                                        var_name='Segment', value_name='Revenue')
                    
                    m_rev['Segment'] = m_rev['Segment'].map({'FIT_REV': T('FIT'), 'GRP_REV': T('GROUP')})
                    m_rev['RoomNights'] = np.where(m_rev['Segment'] == T('FIT'), m_rev['FIT_RMS'], m_rev['GRP_RMS'])
                    
                    fig_bar = px.bar(m_rev, x='DateStr', y='Revenue', color='Segment', 
                                     hover_data={'DateStr': False, 'Revenue': ':,.0f', 'RoomNights': ':,.0f'},
                                     color_discrete_map={T('FIT'): '#3b82f6', T('GROUP'): '#ef4444'})
                    fig_bar.update_layout(xaxis_title="", yaxis_title=T("REV"), legend_title="", height=450)
                    st.plotly_chart(fig_bar, use_container_width=True, key=f"bar_{cur_m}")
                    
                    st.divider()
                    
                    st.subheader(T("요일별 픽업 히트맵"))
                    vis_df['Date'] = pd.to_datetime(vis_df['DateStr'])
                    vis_df['DayNum'] = vis_df['Date'].dt.day
                    vis_df['MonthWeek'] = (vis_df['DayNum'] - 1) // 7 + 1
                    
                    days_order = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
                    vis_df['WeekDay'] = pd.Categorical(vis_df['WeekDay'], categories=days_order, ordered=True)
                    
                    heatmap_z = vis_df.pivot_table(index='MonthWeek', columns='WeekDay', values='Pick_RMS', aggfunc='sum').fillna(0)
                    heatmap_d = vis_df.pivot_table(index='MonthWeek', columns='WeekDay', values='DayNum', aggfunc='first').fillna(0).astype(int)
                    
                    final_text = []
                    for r_idx in range(len(heatmap_z)):
                        row_cells = []
                        for c_idx in range(len(heatmap_z.columns)):
                            try:
                                d_val = heatmap_d.iloc[r_idx, c_idx]
                                v_val = int(heatmap_z.iloc[r_idx, c_idx])
                                if d_val == 0: row_cells.append("")
                                else:
                                    sign = "+" if v_val > 0 else ""
                                    row_cells.append(f"{d_val}일<br><b>{sign}{v_val}</b>")
                            except (IndexError, ValueError, TypeError):
                                row_cells.append("")
                        final_text.append(row_cells)

                    heatmap_z.index = heatmap_z.index.astype(str)
                    
                    fig_hm = go.Figure(data=go.Heatmap(
                        z=heatmap_z.values, x=days_order, y=heatmap_z.index.astype(str),
                        text=final_text, texttemplate="%{text}", textfont={"size": 11},
                        colorscale='RdBu', zmid=0, reversescale=True, xgap=2, ygap=2
                    ))
                    fig_hm.update_layout(yaxis=dict(title='Week', autorange="reversed", showgrid=False),
                                         xaxis=dict(side="top", showgrid=False), height=400)
                    st.plotly_chart(fig_hm, use_container_width=True, key=f"hm_{cur_m}")
                else:
                    st.info(T("시각화할 데이터가 없습니다."))

            # [수정] 자동 저장이 켜져있을 때는 수동 저장 버튼을 옵션으로
            if uploaded_files and not auto_save_on_upload:
                st.divider()
                save_date = st.date_input(T("저장할 기준 일자 선택"), value=today_kst, key=f"save_date_{cur_m}")
                if st.button(f"💾 {save_date} / {cur_m}{T('월 데이터 DB 저장')}", key=f"btn_{cur_m}"):
                    ok, err = save_data_with_sob(save_date.strftime("%Y-%m-%d"), cur_m, df_curr, sob_curr)
                    if ok:
                        st.success(f"✅ {save_date} : {cur_m}{T('월 데이터가 안전하게 저장되었습니다.')}")
                        st.toast(f"✅ {save_date} : {cur_m}{T('월 데이터가 안전하게 저장되었습니다.')}")
                        load_daily_summary_matrix.clear()
                        get_all_snapshot_dates_for_month.clear()
                    else:
                        st.error(f"❌ 저장 실패: {err}")
            elif uploaded_files and auto_save_on_upload and files:
                st.caption(f"💡 자동 저장 모드: 업로드 시점에 이미 DB에 저장되었습니다. 수동 저장을 원하면 사이드바에서 자동 저장을 꺼주세요.")
        except Exception as e:
            st.error(f"Error in {cur_m}월 Tab: {e}")
            with st.expander("🔍 상세 에러 (개발자용)"):
                st.code(traceback.format_exc())
