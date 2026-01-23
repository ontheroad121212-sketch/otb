import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
import re
from datetime import datetime
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
import time

# ==============================================================================
# 0. 사용자 정의 버짓 데이터 (1월~12월 목표 매출)
# ==============================================================================
BUDGET_DATA = { 
    1: 514992575, 2: 786570856, 3: 529599040, 4: 695351004,
    5: 903705440, 6: 808203820, 7: 1231949142, 8: 1388376999,
    9: 952171506, 10: 897171539, 11: 667146771, 12: 804030110 
}

# ==============================================================================
# 1. 페이지 설정 및 CSS 스타일링
# ==============================================================================
st.set_page_config(page_title="ARI Final Integrity", layout="wide")

st.markdown("""
<style>
    .block-container { padding-top: 1rem; padding-bottom: 5rem; }
    div[data-testid="stMetricValue"] { font-size: 26px !important; font-weight: 900; color: #0f172a; }
    div[data-testid="stMetricLabel"] { font-size: 15px !important; font-weight: 700; color: #64748b; }
    button[data-baseweb="tab"] { font-size: 16px !important; font-weight: 700; }
    [data-testid="stDataFrame"] table tr:last-child td {
        font-weight: 900 !important; background-color: #fff9c4 !important; color: black; border-top: 2px solid black;
    }
    div.stButton > button:first-child { border-color: #ff4b4b; color: #ff4b4b; }
    div.stButton > button:first-child:hover { background-color: #ff4b4b; color: white; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 2. 파이어베이스 데이터베이스 연결
# ==============================================================================
if not firebase_admin._apps:
    try:
        cred = credentials.Certificate(dict(st.secrets["firebase"]))
        firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"🔥 DB 연결 실패: {e}")
        st.stop()

db = firestore.client()
COLLECTION_NAME = "revenue_integrity_history"

# ==============================================================================
# 3. 데이터 전처리 및 유틸리티 함수
# ==============================================================================

def clean_numeric_columns(df):
    target_cols = [
        'RN', 'Room_Revenue', 'Total_Revenue', 'ADR_Room', 'ADR_Total', 
        'Lead_Time', 'OTB_Rev', 'Budget_Rev', 'Budget_Achiev', 'OTB_RN', 
        'Actual_Rev', 'Actual_RN', 'Rooms', 'Nights'
    ]
    for col in target_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(
                df[col].astype(str).str.replace(',', '').str.replace('₩', '').str.replace('nan', '0'), 
                errors='coerce'
            ).fillna(0)
    if 'RN' in df.columns:
        if 'Room_Revenue' in df.columns:
            df['ADR_Room'] = np.where(df['RN'] > 0, df['Room_Revenue'] / df['RN'], 0)
        if 'Total_Revenue' in df.columns:
            df['ADR_Total'] = np.where(df['RN'] > 0, df['Total_Revenue'] / df['RN'], 0)
    return df

def save_to_firestore(df):
    try:
        if df.empty: return False
        records = df.fillna(0).astype(str).to_dict(orient='records')
        db.collection(COLLECTION_NAME).add({
            'data': records,
            'uploaded_at': datetime.now(),
            'snapshot_date': datetime.now().strftime('%Y-%m-%d')
        })
        return True
    except Exception as e:
        st.error(f"❌ 데이터 저장 오류: {e}")
        return False

@st.cache_data(ttl=0)
def load_data_from_firestore():
    try:
        docs = db.collection(COLLECTION_NAME).stream()
        all_data = []
        for doc in docs:
            doc_dict = doc.to_dict()
            if 'data' in doc_dict:
                doc_date = doc_dict.get('snapshot_date', '')
                rows = doc_dict['data']
                for row in rows:
                    if 'Snapshot_Date' not in row or not row['Snapshot_Date']:
                        row['Snapshot_Date'] = doc_date
                    all_data.append(row)
        return all_data
    except Exception as e:
        st.error(f"❌ 데이터 로드 오류: {e}")
        return []

def delete_otb_data_only():
    try:
        docs = db.collection(COLLECTION_NAME).stream()
        deleted_count = 0
        for doc in docs:
            doc_data = doc.to_dict()
            if 'data' in doc_data and len(doc_data['data']) > 0:
                first_row = doc_data['data'][0]
                segment = str(first_row.get('Segment', ''))
                if 'OTB' in segment:
                    doc.reference.delete()
                    deleted_count += 1
        return deleted_count
    except Exception as e:
        st.error(f"OTB 삭제 중 오류: {e}")
        return 0

# ==============================================================================
# 4. 엑셀/CSV 파일 처리 로직 (OTB 마지막 열 추출, K열 조식 확인)
# ==============================================================================

def normalize_and_map_columns(df):
    col_map = {}
    rules = {
        'CheckIn': ['checkin', 'arrival', '입실', '일자', 'date'],
        'Guest_Name': ['guest', 'name', 'customer', '고객', '투숙객', '성명'],
        'Booking_Date': ['booking', 'create', 'res', '예약', '생성'],
        'Rooms': ['room', 'qty', 'rmws', '객실수', '수량'],
        'Nights': ['night', 'los', '박수', '박'],
        'Room_Revenue': ['room_rev', 'revenue', 'roomrate', '객실료', '매출'],
        'Total_Revenue': ['total', 'amount', '총금액', '합계'],
        'Segment': ['segment', '세그먼트'],
        'Account': ['account', 'source', 'agent', '거래처', '에이전시'],
        'Room_Type': ['type', 'cat', '객실타입', '룸타입'],
        'Rate_Plan': ['rate', 'plan', '상품', '패키지', '프로모션'], 
        'Nat_Orig': ['nation', 'country', 'nat', '국적'],
        'Lead_Time': ['lead', '리드', 'lt', 'l/t']
    }
    for col in df.columns:
        clean = str(col).lower().replace(" ", "").replace("_", "")
        for target_col, keywords in rules.items():
            for kw in keywords:
                if kw in clean:
                    if target_col not in col_map.values():
                        col_map[col] = target_col; break
            if col in col_map: break
    return df.rename(columns=col_map)

def process_data(file, status, force_otb=False):
    try:
        is_otb = force_otb or "Sales on the Book" in file.name
        if file.name.endswith('.csv'):
            try: df_raw = pd.read_csv(file, header=None)
            except: df_raw = pd.read_csv(file, header=None, encoding='cp949')
        else:
            df_raw = pd.read_excel(file, header=None)

        # ---------------------------------------------------------
        # [A] OTB 데이터 처리 (가장 마지막 행과 행의 셀 값 가져오기)
        # ---------------------------------------------------------
        if is_otb:
            found_month_date = datetime.now()
            # 파일 상단 15줄 이내에서 월 정보 탐색
            for r in range(min(15, len(df_raw))):
                row_str = " ".join(df_raw.iloc[r].astype(str).values)
                match = re.search(r'20\d{2}-(\d{2})', row_str)
                if match:
                    found_month_date = pd.to_datetime(f"2026-{match.group(1)}-01")
                    break
            
            # 마지막 행/열 값 추출 (매출 합계)
            df_clean = df_raw.dropna(how='all').dropna(axis=1, how='all')
            try:
                # 엑셀 물리적 맨 우측 하단 셀
                total_rev = float(str(df_clean.iloc[-1, -1]).replace(',', '').replace('nan', '0').split('.')[0])
                # 엑셀 물리적 맨 우측 하단에서 왼쪽으로 4칸 (보통 객실수 합계)
                total_rn = float(str(df_clean.iloc[-1, -5]).replace(',', '').replace('nan', '0').split('.')[0])
            except:
                total_rev = 0; total_rn = 0

            return pd.DataFrame([{
                'CheckIn': found_month_date.strftime('%Y-%m-%d'),
                'Room_Revenue': total_rev, 'Total_Revenue': total_rev, 'RN': total_rn,
                'Guest_Name': 'OTB_DATA', 'Segment': 'OTB', 'Account': 'OTB_Summary',
                'Room_Type': 'ROH', 'Nat_Orig': 'KR', 'Booking_Date': found_month_date.strftime('%Y-%m-%d'),
                'Lead_Time': 0, 'Breakfast': 'Unknown', 'Status': 'Booked', 'Snapshot_Date': datetime.now().strftime('%Y-%m-%d')
            }])

        # ---------------------------------------------------------
        # [B] 일반 예약/취소 처리 (K열 BF 확인)
        # ---------------------------------------------------------
        header_idx = -1
        # 헤더 키워드 탐색
        for i, row in df_raw.head(20).iterrows():
            if sum(1 for k in ['예약번호', '고객명', '입실일자'] if k in str(row.values)) >= 2:
                header_idx = i; break
        
        if header_idx != -1:
            # 엑셀 원본 컬럼명 확보
            original_headers = df_raw.iloc[header_idx].values
            df = df_raw.iloc[header_idx+1:].reset_index(drop=True)
            df.columns = original_headers
            
            # [수정] 조식 식별 로직: 서비스코드는 엑셀의 K열(11번째)에 위치함
            # 데이터프레임 인덱스로는 10 (0부터 시작)
            svc_col_idx = 10 
            
            # 컬럼 매핑
            df = normalize_and_map_columns(df).copy()
            
            # 조식 분류 (K열 데이터를 서비스코드로 보고 'BF' 포함 여부 확인)
            def check_breakfast(row):
                # 인덱스로 접근하거나, '서비스코드'라는 이름으로 접근 시도
                svc_val = ""
                if len(row) > svc_col_idx:
                    svc_val = str(row.iloc[svc_col_idx]).upper()
                
                # 만약 매핑 과정에서 이름이 바뀌었다면 이름으로도 확인
                if not svc_val or svc_val == 'NAN':
                    svc_val = str(row.get('서비스코드', '')).upper()
                
                if 'BF' in svc_val:
                    return 'Included (조식포함)'
                return 'Not Included (불포함)'
            
            df['Breakfast'] = df.apply(check_breakfast, axis=1)
            
            # 숫자 처리
            for col in ['Room_Revenue', 'Total_Revenue', 'Rooms', 'Nights', 'Lead_Time']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
            
            df['Total_Revenue'] = np.where(df['Total_Revenue'] == 0, df['Room_Revenue'], df['Total_Revenue'])
            df['RN'] = df.get('Rooms', 0) * df.get('Nights', 1).replace(0, 1)
            df['Status'] = status
            df['Snapshot_Date'] = datetime.now().strftime('%Y-%m-%d')
            df['CheckIn_dt'] = pd.to_datetime(df['CheckIn'], errors='coerce')
            df = df.dropna(subset=['CheckIn_dt'])
            df['Stay_Month'] = df['CheckIn_dt'].dt.strftime('%Y-%m')
            
            def cls_nat(row):
                if re.search('[가-힣]', str(row.get('Guest_Name',''))): return 'KOR'
                return 'OTH'
            df['Nat_Group'] = df.apply(cls_nat, axis=1)
            
            return clean_numeric_columns(df)
            
    except Exception as e:
        return pd.DataFrame()

# ==============================================================================
# 5. UI 렌더링 헬퍼 함수
# ==============================================================================

def add_total_row(df, group_col_name="구분"):
    if df.empty: return df
    numeric_df = df.select_dtypes(include=[np.number]).fillna(0)
    totals = numeric_df.sum().to_dict()
    total_row = {col: "" for col in df.columns}
    total_row.update(totals)
    
    if group_col_name in df.columns:
        total_row[group_col_name] = "TOTAL"
    else:
        total_row[df.columns[0]] = "TOTAL"

    if 'RN' in total_row and total_row['RN'] > 0:
        if 'Room_Revenue' in total_row: total_row['ADR_Room'] = total_row['Room_Revenue'] / total_row['RN']
        if 'Total_Revenue' in total_row: total_row['ADR_Total'] = total_row['Total_Revenue'] / total_row['RN']
            
    return pd.concat([df, pd.DataFrame([total_row])], ignore_index=True)

def show_dataframe_with_style(df):
    if df.empty:
        st.write("표시할 데이터가 없습니다.")
        return
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    styler = df.style.format({col: "{:,.0f}" for col in numeric_cols})
    
    def highlight_total(row):
        is_total = any(str(val) == "TOTAL" for val in row)
        return ['background-color: #fff9c4; font-weight: 900; color: black; border-top: 2px solid black'] * len(row) if is_total else [''] * len(row)
    
    st.dataframe(styler.apply(highlight_total, axis=1), hide_index=True, use_container_width=True)

def render_analysis_tab(target_df, title_prefix, unique_key, color_scale="Blues"):
    if target_df.empty:
        st.warning(f"⚠️ {title_prefix} 데이터가 없습니다.")
        return

    t1, t2, t3, t4, t5, t6, t7, t8 = st.tabs([
        "📊 세그먼트", "📅 Pacing", "🏢 거래처", "⏳ 리드타임", "🛏️ 객실타입", "🗓️ 요일", "🌐 국적", "🍳 조식"
    ])
    
    with t1:
        st.subheader(f"📊 {title_prefix} 세그먼트 분석")
        seg_stats = target_df.groupby('Segment').agg({'RN': 'sum', 'Room_Revenue': 'sum', 'Total_Revenue': 'sum'}).reset_index()
        seg_stats['ADR_Room'] = np.where(seg_stats['RN']>0, seg_stats['Room_Revenue']/seg_stats['RN'], 0)
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.pie(seg_stats, values='Room_Revenue', names='Segment', title="매출 비중"), use_container_width=True, key=f"{unique_key}_seg_pie")
        c2.plotly_chart(px.bar(seg_stats, x='Segment', y='Room_Revenue', title="세그먼트별 매출"), use_container_width=True, key=f"{unique_key}_seg_bar")
        show_dataframe_with_style(add_total_row(seg_stats, 'Segment'))

    with t2:
        st.subheader(f"📅 Booking Pacing")
        piv = target_df.pivot_table(index='Booking_Month', columns='Stay_Month', values='RN', aggfunc='sum').fillna(0)
        st.plotly_chart(px.imshow(piv, text_auto="d", aspect="auto", color_continuous_scale=color_scale), use_container_width=True, key=f"{unique_key}_pacing")

    with t3:
        st.subheader("🏢 상위 거래처")
        acc_stats = target_df.groupby('Account').agg({'RN': 'sum', 'Room_Revenue': 'sum', 'Total_Revenue': 'sum'}).reset_index()
        show_dataframe_with_style(add_total_row(acc_stats.sort_values('RN', ascending=False).head(50), 'Account'))

    with t4:
        st.subheader("⏳ 리드타임")
        bins = [-1, 0, 3, 7, 14, 30, 60, 90, 999]; labels = ['0일', '1-3일', '4-7일', '8-14일', '15-30일', '31-60일', '61-90일', '90일+']
        target_df['Lead_Group'] = pd.cut(target_df['Lead_Time'], bins=bins, labels=labels)
        lead_stats = target_df.groupby('Lead_Group').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
        st.plotly_chart(px.bar(lead_stats, x='Lead_Group', y='RN'), use_container_width=True, key=f"{unique_key}_lead")
        show_dataframe_with_style(add_total_row(lead_stats, 'Lead_Group'))

    with t5:
        st.subheader("🛏️ 객실타입")
        rt_stats = target_df.groupby('Room_Type').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
        show_dataframe_with_style(add_total_row(rt_stats, 'Room_Type'))

    with t6:
        st.subheader("🗓️ 요일별 패턴")
        wd_stats = target_df.groupby('Day_Type').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.bar(wd_stats, x='Day_Type', y='Room_Revenue'), use_container_width=True, key=f"{unique_key}_day_bar")
        c2.plotly_chart(px.pie(wd_stats, values='RN', names='Day_Type'), use_container_width=True, key=f"{unique_key}_day_pie")
        show_dataframe_with_style(add_total_row(wd_stats, 'Day_Type'))

    with t7:
        st.subheader("🌐 국적별 분포")
        if 'Nat_Group' in target_df.columns:
            nat_stats = target_df.groupby('Nat_Group').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
            show_dataframe_with_style(add_total_row(nat_stats, 'Nat_Group'))

    with t8:
        # [핵심] 조식 비중 탭 렌더링
        st.subheader("🍳 조식 포함 여부 (서비스코드 BF 기준)")
        if 'Breakfast' in target_df.columns:
            bf_stats = target_df.groupby('Breakfast').agg({'RN': 'sum', 'Room_Revenue': 'sum'}).reset_index()
            c1, c2 = st.columns(2)
            c1.plotly_chart(px.pie(bf_stats, values='RN', names='Breakfast', title="조식 비중"), use_container_width=True, key=f"{unique_key}_bf_pie")
            c2.plotly_chart(px.bar(bf_stats, x='Breakfast', y='Room_Revenue'), use_container_width=True, key=f"{unique_key}_bf_bar")
            show_dataframe_with_style(add_total_row(bf_stats, 'Breakfast'))

# ==============================================================================
# 6. 메인 실행부
# ==============================================================================
try:
    st.title("🏛️ 앰버 호텔 경영 리포트 (Final Integrity)")
    raw_data = load_data_from_firestore()
    df_all = pd.DataFrame(raw_data) if raw_data else pd.DataFrame()
    available_dates = sorted(df_all['Snapshot_Date'].unique(), reverse=True) if not df_all.empty else []

    with st.sidebar:
        st.header("📅 조회 설정")
        if st.button("🗑️ OTB 데이터만 초기화"):
            cnt = delete_otb_data_only()
            st.warning(f"OTB 데이터 {cnt}건 삭제 완료!"); time.sleep(1); st.cache_data.clear(); st.rerun()
            
        selected_date = st.selectbox("조회 기준일 (Snapshot)", available_dates, index=0) if available_dates else None

        st.markdown("---")
        st.header("📤 데이터 업로드")
        with st.expander("예약/취소 리스트", expanded=True):
            f1 = st.file_uploader("예약 리스트", type=['xlsx','csv'], key="f1")
            if f1 and st.button("예약 저장"):
                df = process_data(f1, "Booked")
                if not df.empty and save_to_firestore(df):
                    st.success("예약 리스트 저장 성공!"); time.sleep(1); st.cache_data.clear(); st.rerun()
            f2 = st.file_uploader("취소 리스트", type=['xlsx','csv'], key="f2")
            if f2 and st.button("취소 저장"):
                df = process_data(f2, "Cancelled")
                if not df.empty and save_to_firestore(df):
                    st.success("취소 리스트 저장 성공!"); time.sleep(1); st.cache_data.clear(); st.rerun()

        with st.expander("OTB (Sales on the Book)", expanded=True):
            f3_list = st.file_uploader("당월 OTB (12개월 통합)", type=['xlsx','csv'], key="f3", accept_multiple_files=True)
            if f3_list and st.button("OTB 저장"):
                otb_list = [process_data(f, "Booked", force_otb=True) for f in f3_list]
                if otb_list:
                    if save_to_firestore(pd.concat(otb_list, ignore_index=True)):
                        st.success("OTB 통합 저장 완료!"); time.sleep(1); st.cache_data.clear(); st.rerun()

    if selected_date and not df_all.empty:
        df_filtered = df_all[df_all['Snapshot_Date'] == selected_date].copy()
        df = clean_numeric_columns(df_filtered)
        
        df_otb = df[df['Segment'].astype(str).str.contains('OTB')]
        df_list = df[~df['Segment'].astype(str).str.contains('OTB')]
        df_paid_bk = df_list[(df_list['Status'] == 'Booked') & (df_list['Total_Revenue'] > 0)]
        df_list_cn = df_list[df_list['Status'] == 'Cancelled']
        df_total_paid = pd.concat([df_paid_bk, df_list_cn])

        main_tab0, main_tab1, main_tab2, main_tab3, main_tab4, main_tab5 = st.tabs([
            "👑 GM 요약", "✅ 예약 상세", "❌ 취소 상세", "📈 종합 합계", "🆓 0원 예약", "🎯 OTB 현황"
        ])

        with main_tab0:
            st.header(f"👑 총지배인(GM) 요약 ({selected_date})")
            bk_rn = df_paid_bk['RN'].sum(); bk_rev = df_paid_bk['Room_Revenue'].sum()
            cn_rn = df_list_cn['RN'].sum(); cn_rev = df_list_cn['Room_Revenue'].sum()
            c = st.columns(4)
            c[0].metric("예약 RN", f"{bk_rn:,.0f}"); c[1].metric("예약 매출", f"{bk_rev:,.0f}")
            c[2].metric("취소 RN", f"{cn_rn:,.0f}"); c[3].metric("취소 매출", f"{cn_rev:,.0f}")
            st.divider()
            if not df_paid_bk.empty:
                seg_gm = df_paid_bk.groupby('Segment').agg({'RN': 'sum','Room_Revenue': 'sum'}).reset_index()
                show_dataframe_with_style(add_total_row(seg_gm, 'Segment')) 

        with main_tab1: render_analysis_tab(df_paid_bk, "유료 예약", "bk_u")
        with main_tab2: render_analysis_tab(df_list_cn, "취소 데이터", "cn_u")
        with main_tab3: render_analysis_tab(df_total_paid, "종합 합계", "tot_u")
        with main_tab4: 
            df_zero = df_list[(df_list['Status'] == 'Booked') & (df_list['Total_Revenue'] <= 0)]
            st.dataframe(df_zero[['Guest_Name', 'CheckIn', 'Account', 'Room_Type']], use_container_width=True)

        with main_tab5:
            st.header("🎯 OTB 현황 (Budget vs OTB)")
            if df_otb.empty: st.warning("⚠️ OTB 데이터가 없습니다.")
            else:
                base = df_otb.copy()
                base['M'] = pd.to_datetime(base['CheckIn']).dt.month
                grp_otb = base.groupby('M').agg({'Room_Revenue':'sum'}).reset_index()
                fin = pd.merge(pd.DataFrame({'M': range(1, 13)}), grp_otb, on='M', how='left').fillna(0)
                fin['Budget'] = fin['M'].map(BUDGET_DATA).fillna(0)
                fin['Rate'] = np.where(fin['Budget'] > 0, (fin['Room_Revenue'] / fin['Budget']) * 100, 0)
                fin['Month_Label'] = fin['M'].astype(str) + "월"
                
                fig = go.Figure()
                fig.add_trace(go.Bar(x=fin['Month_Label'], y=fin['Room_Revenue'], name='OTB', text=fin['Rate'].apply(lambda x: f"{x:.1f}%"), textposition='outside', marker_color='#2E86C1'))
                fig.add_trace(go.Scatter(x=fin['Month_Label'], y=fin['Budget'], name='Budget', line=dict(color='red', dash='dot', width=3)))
                fig.update_layout(height=550, yaxis_title="매출 (KRW)", margin=dict(t=50))
                st.plotly_chart(fig, use_container_width=True, key="otb_final_integrity_chart")
                
                res_dict = {}
                for _, r in fin.iterrows(): res_dict[f"{int(r['M'])}월"] = [f"{r['Budget']:,.0f}", f"{r['Room_Revenue']:,.0f}", f"{r['Rate']:.1f}%"]
                st.table(pd.DataFrame(res_dict, index=['Budget (목표)', 'OTB (현재)', '달성률 (%)']))

except Exception as e:
    st.error(f"🚨 시스템 오류: {e}")
