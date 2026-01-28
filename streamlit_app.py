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
    "'hotel_bookings' 데이터를 수색합니다...": "正在搜索 'hotel_bookings' 数据...",
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
    "FIT": "散客 (FIT)",
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
    "📊 리포트": "📊 报表 (Report)",
    "📈 시각화": "📈 可视化 (Visual)",
    "일자별 픽업 현황 (개인 vs 단체)": "每日增量 (FIT vs Group)",
    "요일별 픽업 히트맵": "星期增量热力图 (Day Heatmap)",
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

def find_header_and_process(file):
    try:
        file.seek(0)
        df_raw = pd.read_excel(file, header=None)
        header_row_idx = None
        for idx, row in df_raw.iloc[:15].iterrows():
            row_str = row.astype(str).values
            if any('객실수' in s for s in row_str) and any('매출' in s for s in row_str):
                header_row_idx = idx
                rms_indices = [i for i, val in enumerate(row_str) if '객실수' in str(val)]
                rev_indices = [i for i, val in enumerate(row_str) if '매출' in str(val)]
                break
        if header_row_idx is None: return None, None, None
        df_data = df_raw.iloc[header_row_idx+1:].copy()
        df_data['Date'] = pd.to_datetime(df_data.iloc[:, 0], errors='coerce')
        df_data = df_data.dropna(subset=['Date'])
        def safe_num(idx): return pd.to_numeric(df_data.iloc[:, idx], errors='coerce').fillna(0)
        
        fit_rms_idx, fit_rev_idx = rms_indices[0], rev_indices[0]
        grp_rms_idx, grp_rev_idx = rms_indices[1], rev_indices[1]
        total_rms_idx, total_rev_idx = rms_indices[-1], rev_indices[-1]

        df_clean = pd.DataFrame({'Date': df_data['Date'], 'DateStr': df_data['Date'].dt.strftime('%Y-%m-%d'), 'WeekDay': df_data['Date'].dt.strftime('%a')})
        df_clean['FIT_RMS'] = safe_num(fit_rms_idx)
        df_clean['GRP_RMS'] = safe_num(grp_rms_idx)
        df_clean['RMS'], df_clean['OCC'], df_clean['ADR'] = safe_num(total_rms_idx), safe_num(total_rms_idx+1), safe_num(total_rms_idx+2)
        df_clean['RevPAR'], df_clean['REV'] = safe_num(total_rms_idx+3), safe_num(total_rms_idx+4)
        df_clean['HU'], df_clean['Comp'] = safe_num(total_rms_idx-2), safe_num(total_rms_idx-1)

        sob_data = {'FIT_RMS': int(safe_num(fit_rms_idx).sum()), 'FIT_REV': int(safe_num(fit_rev_idx).sum()),
                    'GRP_RMS': int(safe_num(grp_rms_idx).sum()), 'GRP_REV': int(safe_num(grp_rev_idx).sum()),
                    'TOTAL_OCC': float(df_clean['RMS'].sum() / (df_clean['RMS']/(df_clean['OCC']/100)).sum() * 100)}
        return df_clean, df_data['Date'].iloc[0].month, sob_data
    except: return None, None, None

def get_full_data_by_date(date_str, month_num):
    try:
        doc = db.collection('daily_snapshots').document(date_str).collection('months').document(str(month_num)).get()
        if doc.exists:
            d = doc.to_dict()
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

report_date = st.sidebar.date_input(
    T("기준 일자"), 
    value=today_kst, 
    max_value=today_kst
)

compare_date = st.sidebar.date_input(
    T("비교 일자"), 
    value=today_kst - timedelta(days=1),
    max_value=today_kst
)

admin_key = st.sidebar.text_input(T("Admin Key"), type="password")

if admin_key == "master136":
    st.session_state["authenticated"] = True

selected_page = T("Main Report")
if st.session_state.get("authenticated"):
    st.sidebar.success(T("✅ Admin Mode On"))
    selected_page = st.sidebar.radio(T("Navigation"), [T("Main Report"), T("🎯 Forecasting")])
    st.sidebar.markdown("---")
    
    if "historical_dow" not in st.session_state:
        st.sidebar.warning(T("⏳ 과거 패턴 분석이 필요합니다."))
        if st.sidebar.button(T("📊 4만건 히스토리 전체 분석 시작")):
            with st.sidebar.status(T("데이터 고속 도로 개통 중..."), expanded=True) as status:
                try:
                    st.write(T("파이어베이스 서버에 접속 중..."))
                    db = firestore.client()
                    st.write(T("'hotel_bookings' 데이터를 수색합니다..."))
                    docs = db.collection_group("hotel_bookings").stream()
                    hist_data = []
                    count = 0
                    status_placeholder = st.empty()
                    for doc in docs:
                        hist_data.append(doc.to_dict())
                        count += 1
                        if count % 2000 == 0:
                            status_placeholder.write(T("현재 {count:,}건 로드 중...").format(count=count))
                    if count > 0:
                        st.write(T("총 {count:,}건 수신 완료! 지표 계산 시작...").format(count=count))
                        h_df = pd.DataFrame(hist_data)
                        target_date_col = '예약일자' 
                        if target_date_col in h_df.columns:
                            st.write(f"📈 '{target_date_col}' {T('필드 분석 중...')}")
                            h_df['b_date'] = pd.to_datetime(h_df[target_date_col], errors='coerce')
                            h_df = h_df.dropna(subset=['b_date'])
                            h_df['dow'] = h_df['b_date'].dt.dayofweek
                            st.session_state["historical_dow"] = (h_df['dow'].value_counts(normalize=True) * 7).to_dict()
                            if '휴대폰' in h_df.columns:
                                st.session_state["repeat_rate"] = (h_df['휴대폰'].value_counts() > 1).mean() * 100
                            status.update(label=T("✅ {count:,}건 분석 완료!").format(count=count), state="complete")
                            st.sidebar.success(T("📊 {count:,}건의 패턴이 반영되었습니다.").format(count=count))
                            st.rerun()
                        else:
                            st.error(T("필드를 찾지 못했습니다."))
                            st.write(T("실제 데이터 필드명:"), h_df.columns.tolist())
                    else:
                        st.error(T("데이터를 수집하지 못했습니다. 컬렉션명을 확인해주세요."))
                except Exception as e:
                    st.error(f"❌ {T('연결 실패 원인')}: {str(e)}")
                    st.info("💡 Tip: Check service account permissions.")
    else:
        st.sidebar.success(T("✅ 과거 패턴 분석 완료"))
        if "historical_dow" in st.session_state:
            st.sidebar.info(T("📅 요일별 가중치 적용 중"))
        if st.sidebar.button(T("🔄 데이터 다시 분석")):
            if "historical_dow" in st.session_state: del st.session_state["historical_dow"]
            st.rerun()

if selected_page == "🎯 Forecasting" or selected_page == T("🎯 Forecasting"):
    secret_forecasting.run_forecasting()
    st.stop()

st.title(T("🏨 Daily Pace Report"))
uploaded_files = st.file_uploader(T("엑셀 업로드"), accept_multiple_files=True, type=['xlsx'])

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
            df_prev_sub = df_prev[['DateStr', 'HU', 'Comp', 'RMS', 'OCC', 'ADR', 'RevPAR', 'REV']]
            # [수정] 컬럼 존재 여부 체크 후 할당 (안전장치)
            if 'FIT_RMS' in df_prev.columns: df_prev_sub['FIT_RMS'] = df_prev['FIT_RMS']
            else: df_prev_sub['FIT_RMS'] = 0
            
            if 'GRP_RMS' in df_prev.columns: df_prev_sub['GRP_RMS'] = df_prev['GRP_RMS']
            else: df_prev_sub['GRP_RMS'] = 0
            
            merged = pd.merge(merged, df_prev_sub, on='DateStr', how='left', suffixes=('', '_prev'))
        else:
            for c in ['HU', 'Comp', 'RMS', 'OCC', 'ADR', 'RevPAR', 'REV', 'FIT_RMS', 'GRP_RMS']: 
                if c in merged.columns: merged[f'{c}_prev'] = merged[c]
                else: merged[f'{c}_prev'] = 0

        # [수정] 안전한 컬럼 생성 및 NaN 처리 (AttributeError 원천 차단)
        for col in ['FIT_RMS', 'FIT_RMS_prev', 'GRP_RMS', 'GRP_RMS_prev']:
            if col not in merged.columns: merged[col] = 0
            merged[col] = merged[col].fillna(0)

        for c in ['HU', 'Comp', 'RMS', 'OCC', 'ADR', 'RevPAR', 'REV']: 
            if c not in merged.columns: merged[c] = 0
            if f'{c}_prev' not in merged.columns: merged[f'{c}_prev'] = 0
            merged[f'Pick_{c}'] = merged[c].fillna(0) - merged[f'{c}_prev'].fillna(0)
        
        merged['Pick_FIT_RMS'] = merged['FIT_RMS'] - merged['FIT_RMS_prev']
        merged['Pick_GRP_RMS'] = merged['GRP_RMS'] - merged['GRP_RMS_prev']

        sum_items = ['HU', 'Comp', 'RMS', 'REV', 'HU_prev', 'Comp_prev', 'RMS_prev', 'REV_prev', 'Pick_HU', 'Pick_Comp', 'Pick_RMS', 'Pick_REV']
        totals = merged[sum_items].sum()
        
        def get_total_rates(prefix_rms, prefix_rev, is_curr=True):
            s_rms = totals[prefix_rms]
            s_rev = totals[prefix_rev]
            if is_curr:
                avail = (merged['RMS'] / (merged['OCC'].replace(0, np.nan) / 100)).fillna(0).sum()
            else:
                avail = (merged['RMS_prev'] / (merged['OCC_prev'].replace(0, np.nan) / 100)).fillna(0).sum()
            t_occ = (s_rms / avail * 100) if avail > 0 else 0
            t_adr = (s_rev / s_rms) if s_rms > 0 else 0
            t_par = (s_rev / avail) if avail > 0 else 0
            return t_occ, t_adr, t_par

        c_occ, c_adr, c_par = get_total_rates('RMS', 'REV', True)
        p_occ, p_adr, p_par = get_total_rates('RMS_prev', 'REV_prev', False)

        total_row = pd.DataFrame([{
            'DateStr': 'TOTAL', 'WeekDay': '',
            'HU_prev': totals['HU_prev'], 'Comp_prev': totals['Comp_prev'], 'RMS_prev': totals['RMS_prev'], 
            'OCC_prev': p_occ, 'ADR_prev': p_adr, 'RevPAR_prev': p_par, 'REV_prev': totals['REV_prev'],
            'HU': totals['HU'], 'Comp': totals['Comp'], 'RMS': totals['RMS'], 
            'OCC': c_occ, 'ADR': c_adr, 'RevPAR': c_par, 'REV': totals['REV'],
            'Pick_HU': totals['Pick_HU'], 'Pick_Comp': totals['Pick_Comp'], 'Pick_RMS': totals['Pick_RMS'], 
            'Pick_OCC': c_occ - p_occ, 'Pick_ADR': c_adr - p_adr, 'Pick_RevPAR': c_par - p_par, 'Pick_REV': totals['Pick_REV']
        }])
        
        merged = pd.concat([merged, total_row], ignore_index=True)

        st.session_state[f"sob_{cur_m}"] = sob_curr
        st.session_state[f"pace_{cur_m}"] = totals['Pick_RMS']

        sub_t1, sub_t2 = st.tabs([T("📊 리포트"), T("📈 시각화")])
        
        with sub_t1:
            final_df = merged[['DateStr', 'WeekDay', 
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
            try:
                vis_df = merged.iloc[:-1].copy() # Total 행 제외
                if not vis_df.empty:
                    st.subheader(T("일자별 픽업 현황 (개인 vs 단체)"))
                    # [수정] 안전한 컬럼 초기화
                    if 'Pick_FIT_RMS' not in vis_df.columns: vis_df['Pick_FIT_RMS'] = 0
                    if 'Pick_GRP_RMS' not in vis_df.columns: vis_df['Pick_GRP_RMS'] = 0
                    
                    melted = vis_df.melt(id_vars=['DateStr'], value_vars=['Pick_FIT_RMS', 'Pick_GRP_RMS'], 
                                         var_name='Segment', value_name='Pickup')
                    melted['Segment'] = melted['Segment'].map({'Pick_FIT_RMS': T('FIT'), 'Pick_GRP_RMS': T('GROUP')})
                    
                    fig = px.bar(melted, x='DateStr', y='Pickup', color='Segment', 
                                 title=f"{cur_m}{T('월')} Daily Pickup", 
                                 color_discrete_map={T('FIT'): '#3b82f6', T('GROUP'): '#ef4444'})
                    st.plotly_chart(fig, use_container_width=True)
                    
                    st.divider()
                    st.subheader(T("요일별 픽업 히트맵"))
                    vis_df['Date'] = pd.to_datetime(vis_df['DateStr'])
                    vis_df['Day'] = vis_df['Date'].dt.day
                    vis_df['MonthWeek'] = (vis_df['Day'] - 1) // 7 + 1
                    
                    days_order = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
                    vis_df['WeekDay'] = pd.Categorical(vis_df['WeekDay'], categories=days_order, ordered=True)
                    
                    heatmap_z = vis_df.pivot_table(index='MonthWeek', columns='WeekDay', values='Pick_RMS', aggfunc='sum').fillna(0)
                    
                    # [수정] 달력형 텍스트 생성
                    heatmap_text_d = vis_df.pivot_table(index='MonthWeek', columns='WeekDay', values='Day', aggfunc='first').fillna(0).astype(int).astype(str)
                    heatmap_text_v = vis_df.pivot_table(index='MonthWeek', columns='WeekDay', values='Pick_RMS', aggfunc='sum').fillna(0).astype(int).astype(str)
                    
                    # 0일(빈 날짜)은 빈칸으로 처리
                    heatmap_text_d = heatmap_text_d.replace('0', '')
                    
                    def combine_txt(d, v):
                        if d == '': return ""
                        try:
                            val = int(v)
                            sign = "+" if val > 0 else ""
                            # 0은 표시 안하거나 0으로 표시 (여기선 0 표시)
                            return f"{d}일<br><b>{sign}{val}</b>"
                        except: return ""

                    final_text = heatmap_text_d.combine(heatmap_text_v, combine_txt)
                    
                    heatmap_z.index = heatmap_z.index.astype(str)
                    final_text.index = final_text.index.astype(str)
                    
                    fig_hm = go.Figure(data=go.Heatmap(
                        z=heatmap_z.values,
                        x=days_order,
                        y=heatmap_z.index,
                        text=final_text.values,
                        texttemplate="%{text}",
                        textfont={"size": 11},
                        colorscale='RdBu', 
                        zmid=0,
                        reversescale=True,
                        xgap=1, ygap=1 # 격자 간격 추가
                    ))
                    fig_hm.update_layout(
                        title=f"{cur_m}{T('월')} {T('요일별 픽업 히트맵')}",
                        yaxis=dict(title='Week', autorange="reversed", showgrid=False),
                        xaxis=dict(side="top", showgrid=False),
                        height=400,
                        margin=dict(t=50, l=50, r=50, b=50)
                    )
                    st.plotly_chart(fig_hm, use_container_width=True)
                else:
                    st.info(T("시각화할 데이터가 없습니다."))
            except Exception as e:
                st.error(f"Visualization Error in {cur_m}월: {e}")

        if uploaded_files:
            st.divider()
            save_date = st.date_input(
                T("저장할 기준 일자 선택"), 
                value=today_kst, 
                key=f"save_date_{cur_m}"
            )
            
            if st.button(f"💾 {save_date} / {cur_m}{T('월 데이터 DB 저장')}", key=f"btn_{cur_m}"):
                if save_data_with_sob(save_date.strftime("%Y-%m-%d"), cur_m, df_curr, sob_curr):
                    st.toast(f"✅ {save_date} : {cur_m}{T('월 데이터가 안전하게 저장되었습니다.')}")
