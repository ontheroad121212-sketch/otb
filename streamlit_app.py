import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timedelta
import io
import numpy as np
import textwrap
import secret_forecasting  # 포캐스팅 모듈 임포트
import plotly.express as px
import plotly.graph_objects as go

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
    "TOTAL": "总计 (TOTAL)",
    "Date": "日期",
    "Day": "星期",
    "Pre": "前日",
    "Today": "今日",
    "Var": "变化",
    "월 데이터 DB 저장": "月数据存入数据库",
    "월 데이터가 안전하게 저장되었습니다.": "月数据已安全保存。",
    "데이터 없음": "无数据",
    "현재": "当前",
    "건 로드 중...": "条正在加载...",
    "총": "总计",
    "건 수신 완료! 지표 계산 시작...": "条接收完成！开始计算指标...",
    "저장할 기준 일자 선택": "选择保存日期 (Select Save Date)",
    "📊 리포트": "📊 报표 (Report)",
    "📈 시각화": "📈 可视化 (Visual)",
    "일자별 매출 구성 (개인 vs 단체)": "每日营收构成 (FIT vs Group Revenue)",
    "요일별 픽업 히트맵": "星期增量热力图 (Day Pickup Heatmap)",
    "시각화할 데이터가 없습니다.": "没有可视化数据 (No Data)",
    "요일별": "星期别"
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
        font-size: 10px !important; line-height: 1.2; white-space: pre-wrap; text-align: center;
    }
    .compact-table-wrapper td { padding: 4px 3px !important; border: 1px solid #e2e8f0; font-size: 10px !important; text-align: right; }
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

db = firestore.client()

BUDGET_DATA = {1:514992575, 2:786570856, 3:529599040, 4:695351004, 5:903705440, 6:808203820,
               7:1231949142, 8:1388376999, 9:952171506, 10:897171539, 11:667146771, 12:804030110}

def load_all_historical_data():
    db = firestore.client()
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
        # 값이 없으면 0
        if pd.isna(val) or str(val).strip() == '': return 0
        # 문자열로 변환 후 콤마, 원화, 퍼센트, 공백 제거
        s = str(val).replace(',', '').replace('₩', '').replace(' ', '').replace('%', '').strip()
        return float(s)
    except: 
        return 0

def find_header_and_process(file):
    """
    [최종 해결책] 
    1. 파일 형식을 엑셀/CSV 가리지 않고 강제로 읽기
    2. 5번째 줄(Index 4)부터 무조건 데이터로 인식
    3. C열, F열, H열, K열 좌표 강제 고정
    """
    try:
        file.seek(0)
        df_raw = None
        
        # 1차 시도: 엑셀로 읽기
        try:
            df_raw = pd.read_excel(file, header=None)
        except:
            # 2차 시도: CSV로 읽기 (utf-8)
            try:
                file.seek(0)
                df_raw = pd.read_csv(file, header=None)
            except:
                # 3차 시도: CSV로 읽기 (cp949 - 한글 인코딩)
                file.seek(0)
                df_raw = pd.read_csv(file, header=None, encoding='cp949')
        
        if df_raw is None or len(df_raw) < 5:
            # 데이터가 너무 적으면 실패
            return None, None, None

        # [핵심] 5행(Index 4)부터 데이터 시작
        df_data = df_raw.iloc[4:].copy()
        
        # 첫 번째 컬럼(A열, Index 0)이 날짜라고 가정
        df_data['Date'] = pd.to_datetime(df_data.iloc[:, 0], errors='coerce')
        df_data = df_data.dropna(subset=['Date']) # 날짜가 없는 행은 제거
        
        if df_data.empty:
            return None, None, None

        # [데이터 추출 - 좌표 고정]
        # apply(clean_num)을 사용하여 모든 값을 강제로 숫자로 변환
        
        df_clean = pd.DataFrame()
        df_clean['Date'] = df_data['Date']
        df_clean['DateStr'] = df_data['Date'].dt.strftime('%Y-%m-%d')
        # B열(Index 1)은 요일
        df_clean['WeekDay'] = df_data.iloc[:, 1].astype(str)
        
        # C열(Index 2): 개인 객실수
        df_clean['FIT_RMS'] = df_data.iloc[:, 2].apply(clean_num)
        # F열(Index 5): 개인 매출
        df_clean['FIT_REV'] = df_data.iloc[:, 5].apply(clean_num)
        
        # H열(Index 7): 단체 객실수
        df_clean['GRP_RMS'] = df_data.iloc[:, 7].apply(clean_num)
        # K열(Index 10): 단체 매출
        df_clean['GRP_REV'] = df_data.iloc[:, 10].apply(clean_num)
        
        # O열(Index 14): 합계 객실수
        df_clean['RMS'] = df_data.iloc[:, 14].apply(clean_num)
        # S열(Index 18): 합계 매출
        df_clean['REV'] = df_data.iloc[:, 18].apply(clean_num)
        
        # 보조 지표 (대략적 위치 추정)
        # M열(12): 내부이용, N열(13): 무료
        df_clean['HU'] = df_data.iloc[:, 12].apply(clean_num)
        df_clean['Comp'] = df_data.iloc[:, 13].apply(clean_num)
        
        # P열(15): 점유율, Q열(16): 객단가, R열(17): RevPAR
        df_clean['OCC'] = df_data.iloc[:, 15].apply(clean_num)
        df_clean['ADR'] = df_data.iloc[:, 16].apply(clean_num)
        df_clean['RevPAR'] = df_data.iloc[:, 17].apply(clean_num)

        # SOB 데이터 요약 (상단 KPI용)
        sob_data = {
            'FIT_RMS': int(df_clean['FIT_RMS'].sum()),
            'FIT_REV': int(df_clean['FIT_REV'].sum()),
            'GRP_RMS': int(df_clean['GRP_RMS'].sum()),
            'GRP_REV': int(df_clean['GRP_REV'].sum()),
            'TOTAL_OCC': df_clean['OCC'].mean() if not df_clean['OCC'].empty else 0
        }
        
        # 월 정보 (첫 번째 데이터 기준)
        month_val = df_data['Date'].iloc[0].month
        
        return df_clean, month_val, sob_data
        
    except Exception:
        # 어떤 에러가 나도 일단 None 반환하여 프로그램 다운 방지
        return None, None, None

def get_full_data_by_date(date_str, month_num):
    try:
        doc = db.collection('daily_snapshots').document(date_str).collection('months').document(str(month_num)).get()
        if doc.exists:
            d = doc.to_dict()
            # JSON 읽을 때 에러 방지
            return pd.read_json(io.StringIO(d['json_data']), orient='records'), d.get('sob_data')
    except: pass
    return None, None

def save_data_with_sob(date_str, month, df, sob):
    try:
        db.collection('daily_snapshots').document(date_str).set({'created_at': firestore.SERVER_TIMESTAMP}, merge=True)
        db.collection('daily_snapshots').document(date_str).collection('months').document(str(month)).set({
            'json_data': df.to_json(orient='records'), 'sob_data': sob, 'updated_at': firestore.SERVER_TIMESTAMP
        })
        return True
    except: return False

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

admin_key = st.sidebar.text_input(T("Admin Key"), type="password")
if admin_key == "master136":
    st.session_state["authenticated"] = True

selected_page = T("Main Report")
if st.session_state.get("authenticated"):
    st.sidebar.success(T("✅ Admin Mode On"))
    selected_page = st.sidebar.radio(T("Navigation"), [T("Main Report"), T("🎯 Forecasting")])
    if "historical_dow" not in st.session_state:
        if st.sidebar.button(T("📊 4만건 히스토리 전체 분석 시작")):
            with st.sidebar.status(T("데이터 수색 중..."), expanded=True) as status:
                try:
                    db = firestore.client()
                    docs = db.collection_group("hotel_bookings").stream()
                    hist_data = []
                    count = 0
                    for doc in docs:
                        hist_data.append(doc.to_dict())
                        count += 1
                    if count > 0:
                        h_df = pd.DataFrame(hist_data)
                        h_df['b_date'] = pd.to_datetime(h_df['예약일자'], errors='coerce')
                        h_df = h_df.dropna(subset=['b_date'])
                        h_df['dow'] = h_df['b_date'].dt.dayofweek
                        st.session_state["historical_dow"] = (h_df['dow'].value_counts(normalize=True) * 7).to_dict()
                        status.update(label=T("✅ 분석 완료!"), state="complete")
                        st.rerun()
                except Exception as e: st.error(f"Error: {e}")

if selected_page == "🎯 Forecasting" or selected_page == T("🎯 Forecasting"):
    secret_forecasting.run_forecasting()
    st.stop()

st.title(T("🏨 Daily Pace Report"))
uploaded_files = st.file_uploader(T("엑셀 업로드"), accept_multiple_files=True, type=['xlsx', 'csv'])

tabs = st.tabs([f"{i}{T('월')}" for i in range(1, 13)])
month_files_map = {i: [] for i in range(1, 13)}
if uploaded_files:
    for f in uploaded_files:
        df, m, sob = find_header_and_process(f)
        if m: month_files_map[m].append({'name': f.name, 'data': df, 'sob': sob})

# ==============================================================================
# [4] 탭별 데이터 렌더링 (T 함수 적용 핵심 구간)
# ==============================================================================
for i, tab in enumerate(tabs):
    cur_m = i + 1
    with tab:
        try:
            files = month_files_map.get(cur_m, [])
            df_curr, sob_curr, df_prev = None, None, None
            
            if files:
                files.sort(key=lambda x: x['name'])
                if len(files) >= 2:
                    df_curr, sob_curr, df_prev = files[-1]['data'], files[-1]['sob'], files[-2]['data']
                else:
                    df_curr, sob_curr = files[0]['data'], files[0]['sob']
                    df_prev, _ = get_full_data_by_date(compare_date.strftime("%Y-%m-%d"), cur_m)
            else:
                df_curr, sob_curr = get_full_data_by_date(report_date.strftime("%Y-%m-%d"), cur_m)
                if df_curr is not None: df_prev, _ = get_full_data_by_date(compare_date.strftime("%Y-%m-%d"), cur_m)

            if df_curr is None:
                st.info(f"{cur_m}{T('월')} {T('데이터를 업로드하거나 조회하세요.')}")
                continue

            budget = BUDGET_DATA.get(cur_m, 0)
            total_rev = sob_curr['FIT_REV'] + sob_curr['GRP_REV']
            total_rms = sob_curr['FIT_RMS'] + sob_curr['GRP_RMS']
            
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
                            <div class="kpi-card"><div class="kpi-title">{T('OCC')}</div><div class="kpi-value">{sob_curr['TOTAL_OCC']:.1f}%</div></div>
                            <div class="kpi-card kpi-accent"><div class="kpi-title">{T('ACHIEVEMENT')}</div><div class="kpi-value">{(total_rev/budget*100):.1f}%</div></div>
                        </div>
                    </div>
                    <div>
                        <table class="modern-table">
                            <thead><tr><th>{T('Segment')}</th><th>{T('RMS')}</th><th>{T('ADR')}</th><th>{T('REV')}</th></tr></thead>
                            <tr><td class="label">{T('FIT')}</td><td>{sob_curr['FIT_RMS']:,.0f}</td><td>{(sob_curr['FIT_REV']/max(1,sob_curr['FIT_RMS'])):,.0f}</td><td>{sob_curr['FIT_REV']:,.0f}</td></tr>
                            <tr><td class="label">{T('GROUP')}</td><td>{sob_curr['GRP_RMS']:,.0f}</td><td>{(sob_curr['GRP_REV']/max(1,sob_curr['GRP_RMS'])):,.0f}</td><td>{sob_curr['GRP_REV']:,.0f}</td></tr>
                            <tr style="background:#eff6ff; font-weight:bold;"><td>{T('TOTAL')}</td><td>{total_rms:,.0f}</td><td>{(total_rev/max(1,total_rms)):,.0f}</td><td>{total_rev:,.0f}</td></tr>
                        </table>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            merged = df_curr.copy()
            if df_prev is not None:
                needed_cols = ['DateStr', 'HU', 'Comp', 'RMS', 'OCC', 'ADR', 'RevPAR', 'REV']
                for c in ['FIT_RMS', 'FIT_REV', 'GRP_RMS', 'GRP_REV']:
                    if c in df_prev.columns: needed_cols.append(c)
                
                p_sub = df_prev[needed_cols].copy()
                for c in ['FIT_RMS', 'FIT_REV', 'GRP_RMS', 'GRP_REV']:
                    if c not in p_sub.columns: p_sub[c] = 0
                
                merged = pd.merge(merged, p_sub, on='DateStr', how='left', suffixes=('', '_prev'))
            else:
                for c in ['HU', 'Comp', 'RMS', 'OCC', 'ADR', 'RevPAR', 'REV']: 
                    merged[f'{c}_prev'] = merged[c]
                for c in ['FIT_RMS', 'FIT_REV', 'GRP_RMS', 'GRP_REV']:
                    merged[f'{c}_prev'] = 0

            # 결측치 처리
            num_cols = ['FIT_RMS', 'FIT_REV', 'GRP_RMS', 'GRP_REV', 'RMS', 'REV', 'HU', 'Comp', 'OCC', 'ADR', 'RevPAR']
            for c in num_cols:
                if c not in merged.columns: merged[c] = 0
                if f'{c}_prev' not in merged.columns: merged[f'{c}_prev'] = 0
                merged[c] = merged[c].fillna(0)
                merged[f'{c}_prev'] = merged[f'{c}_prev'].fillna(0)
                merged[f'Pick_{c}'] = merged[c] - merged[f'{c}_prev']

            sum_items = ['HU', 'Comp', 'RMS', 'REV', 'HU_prev', 'Comp_prev', 'RMS_prev', 'REV_prev', 'Pick_HU', 'Pick_Comp', 'Pick_RMS', 'Pick_REV']
            totals = merged[sum_items].sum()
            
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
                    except: return ''
                styler = styler.map(color_pick, subset=var_cols)
                styler = styler.set_properties(subset=var_cols, **{'background-color': '#fffbeb'})
                styler = styler.set_properties(subset=pd.IndexSlice[final_df.index[-1], :], 
                                             **{'background-color': '#eff6ff', 'font-weight': '900', 'border-top': '2px solid #1d4ed8'})
                st.markdown(f'<div class="compact-table-wrapper">{styler.to_html()}</div>', unsafe_allow_html=True)

            with sub_t2:
                vis_df = merged.copy() # merged는 Total 행 제외된 순수 데이터임 (merged_with_total 전)
                
                # 안전장치: 컬럼 없으면 생성
                for c in ['FIT_REV', 'GRP_REV', 'FIT_RMS', 'GRP_RMS']:
                    if c not in vis_df.columns: vis_df[c] = 0
                
                if not vis_df.empty:
                    # 1. 매출 구성 (현재 실적 기준) - 누적 막대
                    st.subheader(T("일자별 매출 구성 (개인 vs 단체)"))
                    
                    # 데이터 Melt
                    m_rev = vis_df.melt(id_vars=['DateStr', 'FIT_RMS', 'GRP_RMS'], 
                                        value_vars=['FIT_REV', 'GRP_REV'],
                                        var_name='Segment', value_name='Revenue')
                    
                    m_rev['Segment'] = m_rev['Segment'].map({'FIT_REV': T('FIT'), 'GRP_REV': T('GROUP')})
                    # 툴팁용 룸나잇 매핑
                    m_rev['RoomNights'] = np.where(m_rev['Segment'] == T('FIT'), m_rev['FIT_RMS'], m_rev['GRP_RMS'])
                    
                    fig_bar = px.bar(m_rev, x='DateStr', y='Revenue', color='Segment', 
                                     hover_data={'DateStr': False, 'Revenue': ':,.0f', 'RoomNights': ':,.0f'},
                                     color_discrete_map={T('FIT'): '#3b82f6', T('GROUP'): '#ef4444'})
                    fig_bar.update_layout(xaxis_title="", yaxis_title=T("REV"), legend_title="", height=450)
                    st.plotly_chart(fig_bar, use_container_width=True)
                    
                    st.divider()
                    
                    # 2. 요일별 픽업 히트맵 (Pickup RMS 기준)
                    st.subheader(T("요일별 픽업 히트맵"))
                    vis_df['Date'] = pd.to_datetime(vis_df['DateStr'])
                    vis_df['DayNum'] = vis_df['Date'].dt.day
                    vis_df['MonthWeek'] = (vis_df['DayNum'] - 1) // 7 + 1
                    
                    days_order = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
                    vis_df['WeekDay'] = pd.Categorical(vis_df['WeekDay'], categories=days_order, ordered=True)
                    
                    heatmap_z = vis_df.pivot_table(index='MonthWeek', columns='WeekDay', values='Pick_RMS', aggfunc='sum').fillna(0)
                    heatmap_d = vis_df.pivot_table(index='MonthWeek', columns='WeekDay', values='DayNum', aggfunc='first').fillna(0).astype(int)
                    
                    # 텍스트 생성 (안전한 이중 반복문)
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
                            except: row_cells.append("")
                        final_text.append(row_cells)

                    # Plotly Heatmap
                    heatmap_z.index = heatmap_z.index.astype(str)
                    
                    fig_hm = go.Figure(data=go.Heatmap(
                        z=heatmap_z.values, x=days_order, y=heatmap_z.index.astype(str),
                        text=final_text, texttemplate="%{text}", textfont={"size": 11},
                        colorscale='RdBu', zmid=0, reversescale=True, xgap=2, ygap=2
                    ))
                    fig_hm.update_layout(yaxis=dict(title='Week', autorange="reversed", showgrid=False),
                                         xaxis=dict(side="top", showgrid=False), height=400)
                    st.plotly_chart(fig_hm, use_container_width=True)
                else:
                    st.info(T("시각화할 데이터가 없습니다."))

            if uploaded_files:
                st.divider()
                save_date = st.date_input(T("저장할 기준 일자 선택"), value=today_kst, key=f"save_date_{cur_m}")
                if st.button(f"💾 {save_date} / {cur_m}{T('월 데이터 DB 저장')}", key=f"btn_{cur_m}"):
                    if save_data_with_sob(save_date.strftime("%Y-%m-%d"), cur_m, df_curr, sob_curr):
                        st.toast(f"✅ {save_date} : {cur_m}{T('월 데이터가 안전하게 저장되었습니다.')}")
        except Exception as e:
            st.error(f"Error in {cur_m}월 Tab: {e}")
