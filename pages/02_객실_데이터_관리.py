import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
import datetime
import re

# --------------------------------------------------------------------------
# 1. 기본 설정 및 DB 연결
# --------------------------------------------------------------------------
st.set_page_config(page_title="객실 현황 대시보드", layout="wide")
st.title("🏨 객실 현황 통합 대시보드 (Reference & Sales)")

if not firebase_admin._apps:
    cred = credentials.Certificate(dict(st.secrets["firebase"]))
    firebase_admin.initialize_app(cred)
db = firestore.client()

# --------------------------------------------------------------------------
# 2. 데이터 처리 함수들 (헤더 찾기, 날짜 통일, 숫자 추출)
# --------------------------------------------------------------------------

def extract_total_rooms(index_name):
    """
    'GDB (7)' 같은 문자열에서 괄호 안의 숫자 '7'을 추출 (OCC 계산용 분모)
    """
    if pd.isna(index_name): return 0
    match = re.search(r'\((\d+)\)', str(index_name))
    if match:
        return int(match.group(1))
    return 0

def normalize_date_columns(df):
    """날짜 컬럼을 YYYY-MM-DD 형식으로 통일"""
    new_cols = []
    current_year = str(datetime.date.today().year)
    
    for col in df.columns:
        if isinstance(col, (pd.Timestamp, datetime.date, datetime.datetime)):
            new_cols.append(col.strftime("%Y-%m-%d"))
            continue
            
        col_str = str(col).strip().replace(" 00:00:00", "")
        # 2026-01-20 패턴
        if re.match(r'^\d{4}-\d{1,2}-\d{1,2}$', col_str):
            new_cols.append(col_str)
        # 01-20 패턴 -> 2026-01-20 변환
        elif re.match(r'^\d{1,2}-\d{1,2}$', col_str):
            parts = col_str.split('-')
            new_cols.append(f"{current_year}-{parts[0].zfill(2)}-{parts[1].zfill(2)}")
        else:
            new_cols.append(col_str)
            
    df.columns = new_cols
    return df

def find_header_row(df_raw):
    """헤더 행 자동 찾기"""
    for i, row in df_raw.head(20).iterrows():
        # 날짜 패턴이나 GDB 키워드가 있으면 헤더로 간주
        date_count = row.astype(str).apply(lambda x: '-' in x or '/' in x).sum()
        has_gdb = row.astype(str).str.contains('GDB').any()
        if date_count > 3 or has_gdb:
            return i
    return 0 

def process_uploaded_df(file):
    # 헤더 찾아서 읽기
    df_raw = pd.read_excel(file, header=None)
    header_idx = find_header_row(df_raw)
    df = pd.read_excel(file, header=header_idx)
    
    # 첫 컬럼 인덱스 처리
    if str(df.columns[0]).startswith('Unnamed'):
        df.rename(columns={df.columns[0]: '구분'}, inplace=True)
    df.set_index(df.columns[0], inplace=True)
    
    # 날짜 통일
    df = normalize_date_columns(df)
    
    # 불필요한 행(요일 등) 삭제
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
    
    # 날짜순 정렬
    date_cols = [c for c in merged.columns if re.match(r'^\d{4}-\d{1,2}-\d{1,2}$', str(c))]
    date_cols.sort()
    other_cols = [c for c in merged.columns if c not in date_cols]
    
    return merged[other_cols + date_cols]

# --------------------------------------------------------------------------
# 3. UI 구성
# --------------------------------------------------------------------------
tab_upload, tab_dashboard = st.tabs(["📤 데이터 업로드 (3종류)", "📊 통합 리포트 (GM/Sales)"])

# ==========================================================================
# [TAB 1] 업로드
# ==========================================================================
with tab_upload:
    st.info("💡 순서: 1. 오늘 판매량(스냅샷) -> 2. 어제 판매량 -> 3. 남은 객실(참고용)")
    
    c1, c2, c3 = st.columns(3)
    
    # 1. 오늘 판매량 (Sales Snapshot)
    with c1:
        st.subheader("1. 오늘 판매량 (Snapshot)")
        st.caption("실제 판매된 데이터")
        files_today = st.file_uploader("오늘 판매 파일들", accept_multiple_files=True, key="today")
        if st.button("오늘 판매량 저장"):
            if files_today:
                df = merge_files(files_today)
                if df is not None:
                    df_save = df.fillna(0)
                    today_str = datetime.date.today().strftime("%Y-%m-%d")
                    db.collection("daily_sales_snapshot").document(today_str).set({
                        "data": df_save.to_dict(), "created_at": datetime.datetime.now()
                    })
                    st.success(f"✅ 오늘 판매량 저장 완료! ({df.shape[1]}일치)")

    # 2. 어제 판매량 (Yesterday Sales)
    with c2:
        st.subheader("2. 어제 판매량 (비교용)")
        st.caption("Pickup 계산을 위한 어제 데이터")
        yest_date = st.date_input("어제 날짜", datetime.date.today() - datetime.timedelta(days=1))
        yest_str = yest_date.strftime("%Y-%m-%d")
        files_yest = st.file_uploader("어제 판매 파일들", accept_multiple_files=True, key="yest")
        if st.button("어제 판매량 저장"):
            if files_yest:
                df = merge_files(files_yest)
                if df is not None:
                    df_save = df.fillna(0)
                    db.collection("daily_sales_snapshot").document(yest_str).set({
                        "data": df_save.to_dict(), "created_at": datetime.datetime.now()
                    })
                    st.success(f"✅ 어제 판매량 저장 완료!")

    # 3. 남은 객실 (Availability / Capacity)
    with c3:
        st.subheader("3. 남은 객실 (Availability)")
        st.caption("총지배인 참고용 (Available)")
        files_avail = st.file_uploader("남은 객실 파일들", accept_multiple_files=True, key="avail")
        if st.button("남은 객실 저장"):
            if files_avail:
                df = merge_files(files_avail)
                if df is not None:
                    df_save = df.fillna(0)
                    # Availability는 날짜별 스냅샷보다는 '최신 상태'를 보는 것이므로 latest로 저장
                    db.collection("hotel_settings").document("latest_availability_view").set({
                        "data": df_save.to_dict(), "updated_at": datetime.datetime.now()
                    })
                    st.success("✅ 남은 객실 데이터 저장 완료!")

# ==========================================================================
# [TAB 2] 리포트 (GM View)
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
            
            # DB 로드 (3개 다 부름)
            doc_sales_today = db.collection("daily_sales_snapshot").document(search_str).get()
            doc_sales_yest = db.collection("daily_sales_snapshot").document(yest_str).get()
            doc_avail = db.collection("hotel_settings").document("latest_availability_view").get()

            # ----------------------------------------------------------
            # SECTION 1: 상단 - 남은 객실 (Availability)
            # ----------------------------------------------------------
            st.markdown("### 1️⃣ 남은 객실 수 (Available Rooms) - GM 참고용")
            if doc_avail.exists:
                df_avail = pd.DataFrame.from_dict(doc_avail.to_dict()['data']).apply(pd.to_numeric, errors='coerce')
                # 날짜 컬럼 정렬
                date_cols = [c for c in df_avail.columns if re.match(r'^\d{4}-\d{1,2}-\d{1,2}$', str(c))]
                date_cols.sort()
                # 정렬된 순서로 보여주기 (옵션: 펼쳐보기)
                with st.expander("🔻 남은 객실 데이터 펼쳐보기", expanded=True):
                    st.dataframe(df_avail[date_cols], use_container_width=True)
            else:
                st.warning("⚠️ 남은 객실(Availability) 데이터가 없습니다. 업로드해주세요.")

            st.divider()

            # ----------------------------------------------------------
            # SECTION 2: 중단 - 실제 판매 & OCC (Sales Snapshot)
            # ----------------------------------------------------------
            st.markdown(f"### 2️⃣ {search_str} 판매 현황 및 점유율 (Sales & OCC)")
            
            if not doc_sales_today.exists:
                st.error("❌ 오늘 판매량(Snapshot) 데이터가 없습니다.")
            else:
                df_sales = pd.DataFrame.from_dict(doc_sales_today.to_dict()['data']).apply(pd.to_numeric, errors='coerce')
                
                # 날짜 정렬
                sales_dates = [c for c in df_sales.columns if re.match(r'^\d{4}-\d{1,2}-\d{1,2}$', str(c))]
                sales_dates.sort()

                # [OCC 자동 계산 로직]
                # 판매량 / (행 이름에 있는 숫자)
                frames = {}
                for date in sales_dates:
                    qty_col = df_sales[date].copy()
                    occ_col = pd.Series(index=df_sales.index, dtype=float)
                    
                    for idx in df_sales.index:
                        total = extract_total_rooms(idx) # GDB (7) -> 7 추출
                        sold = qty_col.loc[idx]
                        
                        if total > 0 and pd.notna(sold):
                            occ_col.loc[idx] = (sold / total) * 100
                        else:
                            occ_col.loc[idx] = None # 합계 등은 빈칸
                    
                    frame = pd.DataFrame({
                        '판매': qty_col,
                        'OCC': occ_col
                    })
                    frames[date] = frame
                
                df_combined = pd.concat(frames, axis=1)
                
                # 스타일링
                idx = pd.IndexSlice
                st.dataframe(
                    df_combined.style
                    .format("{:.0f}", subset=idx[:, (slice(None), '판매')], na_rep="") 
                    .format("{:.1f}%", subset=idx[:, (slice(None), 'OCC')], na_rep="")
                    .background_gradient(cmap='Reds', vmin=0, vmax=100, subset=idx[:, (slice(None), 'OCC')]),
                    height=600,
                    use_container_width=True
                )

            st.divider()

            # ----------------------------------------------------------
            # SECTION 3: 하단 - 변화값 (Pickup)
            # ----------------------------------------------------------
            st.markdown("### 3️⃣ 전일 대비 변동 (Pickup)")
            
            if not doc_sales_yest.exists:
                st.warning("⚠️ 어제 판매량 데이터가 없어서 변동을 계산할 수 없습니다.")
            elif doc_sales_today.exists:
                df_yest = pd.DataFrame.from_dict(doc_sales_yest.to_dict()['data']).apply(pd.to_numeric, errors='coerce')
                
                # 오늘과 어제의 교집합 날짜 찾기
                common_dates = sorted(list(set(sales_dates).intersection(df_yest.columns)))
                
                if common_dates:
                    # 계산: 오늘 판매량 - 어제 판매량
                    df_pickup = df_sales[common_dates].sub(df_yest[common_dates], fill_value=0)
                    
                    def color_pickup(val):
                        if val > 0: return 'color: blue; font-weight: bold; background-color: #f0f8ff'
                        elif val < 0: return 'color: red; font-weight: bold; background-color: #fff0f0'
                        else: return 'color: lightgrey'

                    st.dataframe(
                        df_pickup.style.applymap(color_pickup).format("{:+.0f}", na_rep=""),
                        use_container_width=True
                    )
                else:
                    st.warning("오늘 데이터와 어제 데이터 간에 날짜가 겹치지 않습니다.")
