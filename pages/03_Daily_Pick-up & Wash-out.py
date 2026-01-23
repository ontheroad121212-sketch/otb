import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
import datetime
import re
import numpy as np
import time
import plotly.express as px
import plotly.graph_objects as go

# ==============================================================================
# 0. 사용자 정의 버짓 데이터 (2026년 목표 매출)
# ==============================================================================
BUDGET_DATA = { 
    1: 514992575, 2: 786570856, 3: 529599040, 4: 695351004,
    5: 903705440, 6: 808203820, 7: 1231949142, 8: 1388376999,
    9: 952171506, 10: 897171539, 11: 667146771, 12: 804030110 
}

# --------------------------------------------------------------------------
# 1. 기본 설정 및 DB 연결
# --------------------------------------------------------------------------
st.set_page_config(page_title="객실 현황 통합 대시보드", layout="wide")
st.title("🏨 객실 & 매출 통합 대시보드 (Final)")

if not firebase_admin._apps:
    try:
        cred = credentials.Certificate(dict(st.secrets["firebase"]))
        firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"🔥 DB 연결 실패: {e}")
        st.stop()

db = firestore.client()

# --------------------------------------------------------------------------
# 2. [기존 기능 유지] 데이터 처리 엔진 (Inventory, Pickup, Sorting)
# --------------------------------------------------------------------------

def sort_rows_custom(df):
    """
    사용자가 지정한 순서대로 행(Index)을 강제로 정렬합니다. (기존 로직 유지)
    """
    target_order = [
        'GDB', 'GDF', 'FDB', 'FDE', 'FPT', 'FFD', 
        'HDP', 'HDT', 'HDF', 'PPV', 
        '합계', 
        '예약객실', '하드블럭제외', '하드블럭', 
        '점유율', '판매가능', '고장', '내부', '무료'
    ]
    
    def get_sort_key(idx_value):
        s_idx = str(idx_value).strip()
        for rank, key in enumerate(target_order):
            if key in s_idx:
                return rank
        return 999 

    sorted_index = sorted(df.index, key=get_sort_key)
    return df.reindex(sorted_index)

def extract_total_rooms(index_name):
    if pd.isna(index_name): return 0
    match = re.search(r'\((\d+)\)', str(index_name))
    if match:
        return int(match.group(1))
    return 0

def normalize_date_columns(df):
    new_cols = []
    current_year = str(datetime.date.today().year)
    for col in df.columns:
        if isinstance(col, (pd.Timestamp, datetime.date, datetime.datetime)):
            new_cols.append(col.strftime("%Y-%m-%d"))
            continue
        col_str = str(col).strip().replace(" 00:00:00", "")
        if re.match(r'^\d{4}-\d{1,2}-\d{1,2}$', col_str):
            new_cols.append(col_str)
        elif re.match(r'^\d{1,2}-\d{1,2}$', col_str):
            parts = col_str.split('-')
            new_cols.append(f"{current_year}-{parts[0].zfill(2)}-{parts[1].zfill(2)}")
        else:
            new_cols.append(col_str)
    df.columns = new_cols
    return df

def find_header_row(df_raw):
    for i, row in df_raw.head(20).iterrows():
        date_count = row.astype(str).apply(lambda x: '-' in x or '/' in x).sum()
        has_gdb = row.astype(str).str.contains('GDB').any()
        if date_count > 3 or has_gdb:
            return i
    return 0 

def process_uploaded_df(file):
    """Inventory 파일 처리 (기존 로직)"""
    df_raw = pd.read_excel(file, header=None)
    header_idx = find_header_row(df_raw)
    df = pd.read_excel(file, header=header_idx)
    
    if str(df.columns[0]).startswith('Unnamed'):
        df.rename(columns={df.columns[0]: '구분'}, inplace=True)
    df.set_index(df.columns[0], inplace=True)
    
    df = normalize_date_columns(df)
    
    rows_to_drop = []
    for idx in df.index[:20]:
        s_idx = str(idx)
        if s_idx in ['객실수', 'Room Qty', 'nan', 'NaT', 'None']:
            rows_to_drop.append(idx)
            continue
        row_str = "".join(df.loc[idx].astype(str).values.flatten())
        if any(day in row_str for day in ['월', '화', '수', '목', '금', '토', '일', 'Mon', 'Tue']):
             rows_to_drop.append(idx)
    if rows_to_drop:
        df = df.drop(rows_to_drop)

    df = df.dropna(how='all')
    return df

def make_index_unique(df):
    if df.index.name is None and df.index.dtype == 'int64':
        return df
    new_index = []
    seen = {}
    for idx in df.index:
        name = "Unknown" if pd.isna(idx) or str(idx).strip() == "" else str(idx).strip()
        if name in seen:
            seen[name] += 1
            new_name = f"{name}_{seen[name]}"
        else:
            seen[name] = 0
            new_name = name
        new_index.append(new_name)
    df.index = new_index
    return df

def merge_files(files):
    if not files: return None
    df_list = []
    for f in files:
        try:
            df = process_uploaded_df(f)
            df = make_index_unique(df)
            df_list.append(df)
        except Exception as e:
            st.error(f"파일 {f.name} 오류: {e}")
    if not df_list: return None
    
    merged = pd.concat(df_list, axis=1, sort=False)
    merged = merged.loc[:, ~merged.columns.duplicated()]
    
    date_cols = [c for c in merged.columns if re.match(r'^\d{4}-\d{1,2}-\d{1,2}$', str(c))]
    date_cols.sort()
    other_cols = [c for c in merged.columns if c not in date_cols]
    
    return merged[other_cols + date_cols]

# --------------------------------------------------------------------------
# 3. [추가된 기능] OTB 및 조식 처리 엔진 (여기가 안되던 부분 수정본)
# --------------------------------------------------------------------------

def process_revenue_data(file):
    """
    Sales on the Book (OTB) 및 Guest List (조식) 데이터를 처리합니다.
    - OTB: 맨 오른쪽 열(매출), 뒤에서 5번째(RN) 강제 인식
    - 조식: 서비스코드 'BF' 포함 여부로 식별
    """
    try:
        # 파일 포인터 초기화
        file.seek(0)
        
        if file.name.endswith('.csv'): 
            try: df_raw = pd.read_csv(file, header=None)
            except: df_raw = pd.read_csv(file, header=None, encoding='cp949')
        else: 
            df_raw = pd.read_excel(file, header=None)

        # 1. 헤더 찾기 (공통)
        best_row = 0; max_hit = 0
        keywords = ['guest', '고객', '입실', '객실', '서비스', '매출', '일자', '요일']
        for i, row in df_raw.head(20).iterrows():
            hit = sum(1 for k in keywords if k in str(row.values).lower())
            if hit > max_hit: max_hit = hit; best_row = i
        
        headers = df_raw.iloc[best_row].values
        df = df_raw.iloc[best_row+1:].reset_index(drop=True)
        df.columns = [str(h).strip() for h in headers]

        # ------------------------------------------------
        # CASE A: OTB (Sales on the Book) 판별 및 처리
        # ------------------------------------------------
        if "Sales" in file.name or "영업 현황" in file.name or "일자" in df.columns:
            
            # 합계 행 제거
            if '일자' in df.columns:
                df = df[~df['일자'].astype(str).str.contains('합계|Total|소계', na=False)]
            
            # [수정] 무조건 물리적 위치로 데이터 추출
            # 매출: 맨 마지막 열 (-1)
            rev_raw = df.iloc[:, -1].astype(str).str.replace(',', '').str.replace('₩', '').str.replace('nan', '0')
            # RN: 뒤에서 5번째 열 (-5)
            rn_raw = df.iloc[:, -5].astype(str).str.replace(',', '').str.replace('nan', '0')
            # 날짜: 첫 번째 열
            date_raw = df.iloc[:, 0]

            summary = pd.DataFrame({
                'Date': pd.to_datetime(date_raw, errors='coerce'),
                'Room_Revenue': pd.to_numeric(rev_raw, errors='coerce').fillna(0),
                'RN': pd.to_numeric(rn_raw, errors='coerce').fillna(0),
                'Type': 'OTB',
                'Breakfast': 'Unknown'
            }).dropna(subset=['Date'])
            
            return summary

        # ------------------------------------------------
        # CASE B: Guest List (조식) 판별 및 처리
        # ------------------------------------------------
        else:
            # 컬럼 매핑
            col_map = {
                '입실일자': 'Date', '입실': 'Date', 'CheckIn': 'Date',
                '객실수': 'Rooms', 'Rooms': 'Rooms',
                '박수': 'Nights', 'Nights': 'Nights',
                '총금액': 'Revenue', 'Total_Revenue': 'Revenue',
                '서비스코드': 'Service_Code', 'Service_Code': 'Service_Code'
            }
            df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
            
            # 서비스코드 컬럼 찾기 (없으면 헤더 다시 검색)
            if 'Service_Code' not in df.columns:
                for c in df.columns:
                    if '서비스' in str(c) or 'Service' in str(c):
                        df = df.rename(columns={c: 'Service_Code'})
                        break
            
            # [수정] 조식 식별: Service_Code에 'BF'가 있으면 무조건 조식
            df['Service_Code'] = df['Service_Code'].fillna('').astype(str).str.upper()
            df['Breakfast'] = np.where(df['Service_Code'].str.contains('BF'), 'Included (조식포함)', 'Room Only (불포함)')
            
            # 숫자 변환
            for col in ['Rooms', 'Nights', 'Revenue']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
            
            df['RN'] = df.get('Rooms', 0) * df.get('Nights', 1)
            df['Type'] = 'GuestList'
            df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
            
            return df[['Date', 'Breakfast', 'RN', 'Revenue', 'Type']].dropna(subset=['Date'])

    except Exception as e:
        st.error(f"매출 데이터 처리 중 오류 ({file.name}): {e}")
        return None

# --------------------------------------------------------------------------
# 4. UI 구성 (탭 통합)
# --------------------------------------------------------------------------
tab_upload, tab_dashboard = st.tabs(["📤 데이터 업로드 (관리자)", "📊 통합 리포트"])

# ==========================================================================
# [TAB 1] 업로드 (Inventory + Revenue 통합)
# ==========================================================================
with tab_upload:
    st.info("💡 모든 파일은 원본 그대로 업로드하시면 시스템이 자동으로 분석합니다.")
    
    # 암호 입력창
    admin_pw = st.text_input("🔑 관리자 암호 (저장하려면 입력하세요)", type="password")
    
    st.divider()
    
    c1, c2 = st.columns(2)
    
    # 1. 오늘 판매량 (Inventory) - 기존 기능
    with c1:
        st.subheader("1. [객실팀] 객실 점유율 (Inventory)")
        files_today = st.file_uploader("오늘 판매 현황 파일", accept_multiple_files=True, key="today")
        
        if st.button("점유율 데이터 저장", type="primary"):
            if admin_pw == "9999":
                if files_today:
                    df = merge_files(files_today)
                    if df is not None:
                        today_str = datetime.date.today().strftime("%Y-%m-%d")
                        # NaN 처리 후 저장
                        db.collection("daily_sales_snapshot").document(today_str).set({
                            "data": df.fillna(0).to_dict(), "created_at": datetime.datetime.now()
                        })
                        st.success(f"✅ {today_str} 점유율 데이터 저장 완료!")
                else:
                    st.warning("파일을 먼저 선택해주세요.")
            else:
                st.error("⛔ 암호가 틀렸습니다!")

    # 2. 매출 및 조식 (Revenue/OTB) - 추가된 기능
    with c2:
        st.subheader("2. [예약실] OTB 및 조식 리스트")
        files_rev = st.file_uploader("OTB(영업현황) 또는 예약리스트", accept_multiple_files=True, key="rev")
        
        if st.button("매출/조식 데이터 저장"):
            if admin_pw == "9999":
                if files_rev:
                    all_data = []
                    for f in files_rev:
                        res = process_revenue_data(f)
                        if res is not None: all_data.append(res)
                    
                    if all_data:
                        combined = pd.concat(all_data, ignore_index=True)
                        # 날짜를 문자열로 변환하여 저장 (JSON 호환)
                        combined['Date'] = combined['Date'].dt.strftime("%Y-%m-%d")
                        
                        today_str = datetime.date.today().strftime("%Y-%m-%d")
                        db.collection("daily_revenue_integrity").document(today_str).set({
                            "data": combined.fillna(0).to_dict('records'), "updated_at": datetime.datetime.now()
                        })
                        st.success("✅ 매출 및 조식 분석 데이터 저장 완료!")
                else:
                    st.warning("파일을 먼저 선택해주세요.")
            else:
                st.error("⛔ 암호가 틀렸습니다!")

    st.divider()
    
    # 3. 남은 객실 (Availability) - 기존 기능
    st.subheader("3. 남은 객실 (Availability)")
    files_avail = st.file_uploader("남은 객실 파일들", accept_multiple_files=True, key="avail")
    
    if st.button("남은 객실 저장"):
        if admin_pw == "9999":
            if files_avail:
                df = merge_files(files_avail)
                if df is not None:
                    db.collection("hotel_settings").document("latest_availability_view").set({
                        "data": df.fillna(0).to_dict(), "updated_at": datetime.datetime.now()
                    })
                    st.success("✅ 남은 객실 데이터 업데이트 완료!")
            else:
                st.warning("파일을 먼저 선택해주세요.")
        else:
            st.error("⛔ 암호가 틀렸습니다!")

# ==========================================================================
# [TAB 2] 리포트 (기존 기능 + 신규 기능 통합)
# ==========================================================================
with tab_dashboard:
    st.header("📊 객실 통합 리포트")
    
    col_sel, col_btn = st.columns([1, 4])
    with col_sel:
        search_date = st.date_input("조회 기준일", datetime.date.today())
        search_str = search_date.strftime("%Y-%m-%d")
        yest_str = (search_date - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    
    with col_btn:
        st.write("")
        st.write("")
        if st.button("🚀 리포트 불러오기", type="primary"):
            
            # DB 로드 (기존 + 신규)
            doc_sales_today = db.collection("daily_sales_snapshot").document(search_str).get()
            doc_sales_yest = db.collection("daily_sales_snapshot").document(yest_str).get()
            doc_avail = db.collection("hotel_settings").document("latest_availability_view").get()
            doc_rev = db.collection("daily_revenue_integrity").document(search_str).get()

            # ----------------------------------------------------------
            # [NEW] SECTION 1: 매출 및 조식 분석 (상단 배치)
            # ----------------------------------------------------------
            st.markdown("### 1️⃣ 매출(OTB) 및 조식 현황")
            
            if doc_rev.exists:
                # 데이터 복원
                rev_data = doc_rev.to_dict()['data']
                df_rev_raw = pd.DataFrame(rev_data)
                
                c_bf, c_otb = st.columns(2)
                
                # 1-1. 조식 분석
                with c_bf:
                    st.subheader("🍳 조식 포함 비중 (Guest List)")
                    df_bf = df_rev_raw[df_rev_raw['Type'] == 'GuestList'].copy()
                    
                    if not df_bf.empty:
                        # 숫자형 변환
                        df_bf['RN'] = pd.to_numeric(df_bf['RN'])
                        df_bf['Revenue'] = pd.to_numeric(df_bf['Revenue'])
                        
                        bf_sum = df_bf.groupby('Breakfast').agg({'RN': 'sum', 'Revenue': 'sum'}).reset_index()
                        bf_sum['ADR'] = np.where(bf_sum['RN']>0, bf_sum['Revenue'] / bf_sum['RN'], 0)
                        
                        st.plotly_chart(px.pie(bf_sum, values='RN', names='Breakfast', hole=0.4, title="조식 포함 객실 비중"), use_container_width=True)
                        st.dataframe(bf_sum.style.format({'RN': '{:,.0f}', 'Revenue': '{:,.0f}', 'ADR': '{:,.0f}'}), use_container_width=True)
                    else:
                        st.info("조식 데이터(Guest List)가 없습니다.")

                # 1-2. OTB 분석
                with c_otb:
                    st.subheader("🎯 OTB 실적 vs Budget")
                    df_otb = df_rev_raw[df_rev_raw['Type'] == 'OTB'].copy()
                    
                    if not df_otb.empty:
                        df_otb['Date'] = pd.to_datetime(df_otb['Date'])
                        df_otb['Month'] = df_otb['Date'].dt.month
                        df_otb['Room_Revenue'] = pd.to_numeric(df_otb['Room_Revenue'])
                        
                        monthly_otb = df_otb.groupby('Month')['Room_Revenue'].sum().reset_index()
                        monthly_otb['Budget'] = monthly_otb['Month'].map(BUDGET_DATA).fillna(0)
                        monthly_otb['Achiev'] = (monthly_otb['Room_Revenue'] / monthly_otb['Budget'] * 100).fillna(0)
                        
                        fig = go.Figure()
                        fig.add_trace(go.Bar(x=monthly_otb['Month'].astype(str)+"월", y=monthly_otb['Room_Revenue'], name="실적(OTB)", marker_color='#2E86C1', text_auto='.2s'))
                        fig.add_trace(go.Scatter(x=monthly_otb['Month'].astype(str)+"월", y=monthly_otb['Budget'], name="목표(Budget)", line=dict(color='red', dash='dot')))
                        st.plotly_chart(fig, use_container_width=True)
                        
                        st.dataframe(monthly_otb.style.format({'Room_Revenue': '{:,.0f}', 'Budget': '{:,.0f}', 'Achiev': '{:.1f}%'}), use_container_width=True)
                    else:
                        st.info("OTB 데이터가 없습니다.")
            else:
                st.warning("⚠️ 매출/조식 데이터가 업로드되지 않았습니다. (Tab 1에서 업로드 필요)")

            st.divider()

            # ----------------------------------------------------------
            # [OLD] SECTION 2: 남은 객실 (Inventory) - 기존 기능 유지
            # ----------------------------------------------------------
            st.markdown("### 2️⃣ 남은 객실 수 (Available Rooms)")
            if doc_avail.exists:
                df_avail = pd.DataFrame.from_dict(doc_avail.to_dict()['data']).apply(pd.to_numeric, errors='coerce')
                
                # 정렬 적용
                df_avail = sort_rows_custom(df_avail)
                
                date_cols = [c for c in df_avail.columns if re.match(r'^\d{4}-\d{1,2}-\d{1,2}$', str(c))]
                date_cols.sort()
                
                with st.expander("🔻 남은 객실 데이터 펼쳐보기", expanded=True):
                    st.dataframe(df_avail[date_cols], use_container_width=True)
            else:
                st.warning("⚠️ 남은 객실 데이터가 없습니다.")

            st.divider()

            # ----------------------------------------------------------
            # [OLD] SECTION 3: 실제 판매 & OCC - 기존 기능 유지
            # ----------------------------------------------------------
            st.markdown(f"### 3️⃣ {search_str} 판매 현황 및 점유율")
            
            if not doc_sales_today.exists:
                st.error(f"❌ '{search_str}' 날짜의 판매 데이터가 없습니다. 업로드 탭에서 올려주세요.")
            else:
                df_sales = pd.DataFrame.from_dict(doc_sales_today.to_dict()['data']).apply(pd.to_numeric, errors='coerce')
                
                # 정렬 적용
                df_sales = sort_rows_custom(df_sales)

                sales_dates = [c for c in df_sales.columns if re.match(r'^\d{4}-\d{1,2}-\d{1,2}$', str(c))]
                sales_dates.sort()

                # OCC 자동 계산
                frames = {}
                for date in sales_dates:
                    qty_col = df_sales[date].copy()
                    occ_col = pd.Series(index=df_sales.index, dtype=float)
                    
                    for idx in df_sales.index:
                        total = extract_total_rooms(idx) 
                        sold = qty_col.loc[idx]
                        if total > 0 and pd.notna(sold):
                            occ_col.loc[idx] = (sold / total) * 100
                        else:
                            occ_col.loc[idx] = None 
                    
                    frame = pd.DataFrame({'판매': qty_col, 'OCC': occ_col})
                    frames[date] = frame
                
                df_combined = pd.concat(frames, axis=1)
                
                # 그라데이션 스타일링
                idx_slice = pd.IndexSlice
                st.dataframe(
                    df_combined.style
                    .format("{:.0f}", subset=idx_slice[:, (slice(None), '판매')], na_rep="") 
                    .format("{:.1f}%", subset=idx_slice[:, (slice(None), 'OCC')], na_rep="")
                    .background_gradient(
                        cmap='Reds', 
                        vmin=0, 
                        vmax=200, 
                        subset=idx_slice[:, (slice(None), 'OCC')]
                    ),
                    height=600,
                    use_container_width=True
                )

            st.divider()

            # ----------------------------------------------------------
            # [OLD] SECTION 4: Pickup (어제 데이터 비교) - 기존 기능 유지
            # ----------------------------------------------------------
            st.markdown(f"### 4️⃣ 전일({yest_str}) 대비 변동 (Pickup)")
            
            if doc_sales_today.exists:
                if doc_sales_yest.exists:
                    df_yest = pd.DataFrame.from_dict(doc_sales_yest.to_dict()['data']).apply(pd.to_numeric, errors='coerce')
                    
                    # 정렬 적용
                    df_sales_sorted = sort_rows_custom(df_sales)
                    df_yest_sorted = sort_rows_custom(df_yest)
                    
                    common_dates = sorted(list(set(sales_dates).intersection(df_yest_sorted.columns)))
                    
                    if common_dates:
                        df_pickup = df_sales_sorted[common_dates].sub(df_yest_sorted[common_dates], fill_value=0)
                        
                        def color_pickup(val):
                            if val > 0: return 'color: blue; font-weight: bold; background-color: #f0f8ff'
                            elif val < 0: return 'color: red; font-weight: bold; background-color: #fff0f0'
                            else: return 'color: lightgrey'

                        st.dataframe(
                            df_pickup.style.applymap(color_pickup).format("{:+.0f}", na_rep=""),
                            use_container_width=True
                        )
                    else:
                        st.warning("⚠️ 오늘과 어제 데이터 간에 겹치는 날짜가 하나도 없습니다.")
                else:
                    st.warning(f"⚠️ {yest_str} (어제) 데이터가 DB에 없어 비교할 수 없습니다.")
            else:
                pass
