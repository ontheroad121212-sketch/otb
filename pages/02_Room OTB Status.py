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
st.title("🏨 객실 현황 통합 대시보드")

if not firebase_admin._apps:
    cred = credentials.Certificate(dict(st.secrets["firebase"]))
    firebase_admin.initialize_app(cred)
db = firestore.client()

# --------------------------------------------------------------------------
# 2. 데이터 처리 엔진 (로직 100% 유지)
# --------------------------------------------------------------------------

def sort_rows_custom(df):
    """
    사용자가 지정한 순서대로 행(Index)을 강제로 정렬합니다.
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
# 3. UI 구성
# --------------------------------------------------------------------------
tab_upload, tab_dashboard = st.tabs(["📤 데이터 업로드 (관리자)", "📊 통합 리포트"])

# ==========================================================================
# [TAB 1] 업로드 (날짜 지정 기능 추가됨!)
# ==========================================================================
with tab_upload:
    st.info("💡 과거 데이터 수정이 필요하면 '저장할 날짜'를 변경해서 업로드하세요.")
    
    admin_pw = st.text_input("🔑 관리자 암호", type="password")
    
    st.divider()
    
    c1, c2 = st.columns(2)
    
    # 1. 판매량 스냅샷 (날짜 선택 가능)
    with c1:
        st.subheader("1. 판매량 스냅샷 저장")
        
        # [수정] 업로드할 날짜를 직접 선택 (기본값: 오늘)
        upload_date = st.date_input("📅 저장할 날짜 선택", datetime.date.today(), key="upload_date")
        
        files_today = st.file_uploader("판매 파일 업로드", accept_multiple_files=True, key="sales_files")
        
        if st.button("판매량 저장하기", type="primary"):
            if admin_pw == "9999": 
                if files_today:
                    df = merge_files(files_today)
                    if df is not None:
                        df_save = df.fillna(0)
                        # [핵심] 선택한 날짜 문자열로 저장
                        save_str = upload_date.strftime("%Y-%m-%d")
                        
                        db.collection("daily_sales_snapshot").document(save_str).set({
                            "data": df_save.to_dict(), "created_at": datetime.datetime.now()
                        })
                        st.success(f"✅ {save_str} 날짜로 저장 완료!")
                else:
                    st.warning("파일을 먼저 선택해주세요.")
            else:
                st.error("⛔ 암호가 틀렸습니다!")

    # 2. 남은 객실 (Availability)
    with c2:
        st.subheader("2. 남은 객실 (Availability)")
        st.caption("최신 현황으로 덮어씌워집니다.")
        files_avail = st.file_uploader("남은 객실 파일들", accept_multiple_files=True, key="avail")
        
        if st.button("남은 객실 저장"):
            if admin_pw == "9999":
                if files_avail:
                    df = merge_files(files_avail)
                    if df is not None:
                        df_save = df.fillna(0)
                        db.collection("hotel_settings").document("latest_availability_view").set({
                            "data": df_save.to_dict(), "updated_at": datetime.datetime.now()
                        })
                        st.success("✅ 남은 객실 데이터 업데이트 완료!")
                else:
                    st.warning("파일을 먼저 선택해주세요.")
            else:
                st.error("⛔ 암호가 틀렸습니다!")

# ==========================================================================
# [TAB 2] 리포트 (조회 기능 유지)
# ==========================================================================
with tab_dashboard:
    st.header("📊 객실 통합 리포트")
    
    col_sel, col_btn = st.columns([1, 4])
    with col_sel:
        # 기본값: 오늘
        search_date = st.date_input("조회 기준일 선택", datetime.date.today(), key="search_date")
        
        search_str = search_date.strftime("%Y-%m-%d")
        yest_str = (search_date - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    
    with col_btn:
        st.write("")
        st.write("")
        if st.button("🚀 리포트 불러오기", type="primary"):
            
            # DB 로드
            doc_sales_today = db.collection("daily_sales_snapshot").document(search_str).get()
            doc_sales_yest = db.collection("daily_sales_snapshot").document(yest_str).get()
            doc_avail = db.collection("hotel_settings").document("latest_availability_view").get()

            # ----------------------------------------------------------
            # SECTION 1: 상단 - 남은 객실
            # ----------------------------------------------------------
            st.markdown("### 1️⃣ 남은 객실 수 (Available Rooms) - GM 참고용")
            if doc_avail.exists:
                df_avail = pd.DataFrame.from_dict(doc_avail.to_dict()['data']).apply(pd.to_numeric, errors='coerce')
                df_avail = sort_rows_custom(df_avail)
                
                date_cols = [c for c in df_avail.columns if re.match(r'^\d{4}-\d{1,2}-\d{1,2}$', str(c))]
                date_cols.sort()
                
                with st.expander("🔻 남은 객실 데이터 펼쳐보기", expanded=True):
                    st.dataframe(df_avail[date_cols], use_container_width=True)
            else:
                st.warning("⚠️ 남은 객실 데이터가 없습니다.")

            st.divider()

            # ----------------------------------------------------------
            # SECTION 2: 중단 - 판매 & OCC
            # ----------------------------------------------------------
            st.markdown(f"### 2️⃣ {search_str} 판매 현황 및 점유율")
            
            if not doc_sales_today.exists:
                st.error(f"❌ '{search_str}' 날짜의 데이터가 없습니다.")
                st.info("💡 업로드 탭에서 날짜를 지정하여 데이터를 올려주세요.")
            else:
                df_sales = pd.DataFrame.from_dict(doc_sales_today.to_dict()['data']).apply(pd.to_numeric, errors='coerce')
                df_sales = sort_rows_custom(df_sales)

                sales_dates = [c for c in df_sales.columns if re.match(r'^\d{4}-\d{1,2}-\d{1,2}$', str(c))]
                sales_dates.sort()

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
                
                idx = pd.IndexSlice
                st.dataframe(
                    df_combined.style
                    .format("{:.0f}", subset=idx[:, (slice(None), '판매')], na_rep="") 
                    .format("{:.1f}%", subset=idx[:, (slice(None), 'OCC')], na_rep="")
                    .background_gradient(
                        cmap='Reds', 
                        vmin=0, 
                        vmax=200, 
                        subset=idx[:, (slice(None), 'OCC')]
                    ),
                    height=600,
                    use_container_width=True
                )

            st.divider()

            # ----------------------------------------------------------
            # SECTION 3: 하단 - Pickup
            # ----------------------------------------------------------
            st.markdown(f"### 3️⃣ 전일({yest_str}) 대비 변동 (Pickup)")
            
            if doc_sales_today.exists:
                if doc_sales_yest.exists:
                    df_yest = pd.DataFrame.from_dict(doc_sales_yest.to_dict()['data']).apply(pd.to_numeric, errors='coerce')
                    
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
                        st.warning("⚠️ 겹치는 날짜가 없어 비교 불가")
                else:
                    st.warning(f"⚠️ {yest_str} (어제) 데이터가 없어 비교할 수 없습니다.")
            else:
                pass


# --- 02_Room OTB Status.py 하단 수정 ---

# 1. 월(Month) 정보 가져오기 (가장 안전한 방법)
# 위쪽 코드에서 'current_month'나 'month'를 정의했다면 그것을 쓰고, 
# 없으면 데이터프레임(df_curr)에서 직접 추출합니다.
try:
    if 'current_month' in locals():
        save_month = current_month
    elif 'month' in locals():
        save_month = month
    elif 'df_curr' in locals() and df_curr is not None:
        # 데이터프레임의 첫 번째 행 날짜에서 월 추출
        save_month = df_curr['Date'].iloc[0].month
    else:
        # 이도 저도 안 되면 오늘 날짜 기준
        import datetime
        save_month = datetime.datetime.now().month
except Exception:
    import datetime
    save_month = datetime.datetime.now().month

# 2. 공용 게시판(session_state)에 데이터 전송
if 'sob_curr' in locals() and sob_curr is not None:
    st.session_state[f"sob_{save_month}"] = sob_curr
    
    if 'df_curr' in locals() and 'df_prev' in locals():
        # 페이스 데이터(변화량) 저장
        st.session_state[f"pace_{save_month}"] = len(df_curr) - len(df_prev)

    st.success(f"✅ {save_month}월 데이터가 포캐스팅 시스템으로 전송되었습니다.")
