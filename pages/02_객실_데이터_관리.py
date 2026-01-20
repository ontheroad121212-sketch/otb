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
# 2. 데이터 처리 엔진 (정렬 로직 추가됨)
# --------------------------------------------------------------------------

def sort_rows_custom(df):
    """
    사용자가 지정한 순서대로 행(Index)을 강제로 정렬합니다.
    (GDB -> GDF ... -> 합계 -> 예약객실 ... -> 무료객실)
    """
    # 1. 우리가 원하는 순서 리스트 (우선순위)
    # 텍스트가 포함되어 있으면 해당 순서를 부여함
    target_order = [
        'GDB', 'GDF', 'FDB', 'FDE', 'FPT', 'FFD', 
        'HDP', 'HDT', 'HDF', 'PPV', 
        '합계', 
        '예약객실', '하드블럭제외', '하드블럭', 
        '점유율', '판매가능', '고장', '내부', '무료'
    ]
    
    # 2. 정렬을 위한 보조 컬럼 생성 function
    def get_sort_key(idx_value):
        s_idx = str(idx_value).strip()
        for rank, key in enumerate(target_order):
            # "GDB (7)" 처럼 키워드가 포함되어 있으면 우선순위 부여
            if key in s_idx:
                # '하드블럭제외'와 '하드블럭'이 겹치므로 긴 단어부터 체크되게 해야 함
                # (리스트 순서대로 체크하므로 상위 리스트 배치가 중요)
                return rank
        return 999 # 리스트에 없는 항목은 맨 뒤로

    # 3. 정렬 실행
    # 인덱스를 기준으로 정렬 키를 만들어서 정렬
    sorted_index = sorted(df.index, key=get_sort_key)
    return df.reindex(sorted_index)

def extract_total_rooms(index_name):
    """ 'GDB (7)' -> 7 추출 """
    if pd.isna(index_name): return 0
    match = re.search(r'\((\d+)\)', str(index_name))
    if match:
        return int(match.group(1))
    return 0

def normalize_date_columns(df):
    """ 날짜 형식 통일 """
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
    """ 헤더 자동 찾기 """
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
    
    # 요일 행 삭제 (월, 화, 수...)
    rows_to_drop = []
    for idx in df.index[:20]:
        s_idx = str(idx)
        # 삭제할 특정 헤더들
        if s_idx in ['객실수', 'Room Qty', 'nan', 'NaT', 'None']:
            rows_to_drop.append(idx)
            continue
        # 요일 텍스트 포함 여부
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
tab_upload, tab_dashboard = st.tabs(["📤 데이터 업로드", "📊 통합 리포트"])

# ==========================================================================
# [TAB 1] 업로드
# ==========================================================================
with tab_upload:
    st.info("💡 순서: 1. 오늘 판매량 -> 2. 어제 판매량 -> 3. 남은 객실")
    
    c1, c2, c3 = st.columns(3)
    
    # 1. 오늘 판매량
    with c1:
        st.subheader("1. 오늘 판매량 (Snapshot)")
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
                    st.success(f"✅ 저장 완료!")

    # 2. 어제 판매량
    with c2:
        st.subheader("2. 어제 판매량 (비교용)")
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
                    st.success(f"✅ 저장 완료!")

    # 3. 남은 객실 (Availability)
    with c3:
        st.subheader("3. 남은 객실 (Availability)")
        files_avail = st.file_uploader("남은 객실 파일들", accept_multiple_files=True, key="avail")
        if st.button("남은 객실 저장"):
            if files_avail:
                df = merge_files(files_avail)
                if df is not None:
                    df_save = df.fillna(0)
                    db.collection("hotel_settings").document("latest_availability_view").set({
                        "data": df_save.to_dict(), "updated_at": datetime.datetime.now()
                    })
                    st.success("✅ 저장 완료!")

# ==========================================================================
# [TAB 2] 리포트
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
            
            # DB 로드
            doc_sales_today = db.collection("daily_sales_snapshot").document(search_str).get()
            doc_sales_yest = db.collection("daily_sales_snapshot").document(yest_str).get()
            doc_avail = db.collection("hotel_settings").document("latest_availability_view").get()

            # ----------------------------------------------------------
            # SECTION 1: 상단 - 남은 객실 (Availability)
            # ----------------------------------------------------------
            st.markdown("### 1️⃣ 남은 객실 수 (Available Rooms) - GM 참고용")
            if doc_avail.exists:
                df_avail = pd.DataFrame.from_dict(doc_avail.to_dict()['data']).apply(pd.to_numeric, errors='coerce')
                
                # [수정됨] 사용자 지정 정렬 적용
                df_avail = sort_rows_custom(df_avail)
                
                date_cols = [c for c in df_avail.columns if re.match(r'^\d{4}-\d{1,2}-\d{1,2}$', str(c))]
                date_cols.sort()
                
                with st.expander("🔻 남은 객실 데이터 펼쳐보기", expanded=True):
                    st.dataframe(df_avail[date_cols], use_container_width=True)
            else:
                st.warning("⚠️ 남은 객실 데이터가 없습니다.")

            st.divider()

            # ----------------------------------------------------------
            # SECTION 2: 중단 - 실제 판매 & OCC
            # ----------------------------------------------------------
            st.markdown(f"### 2️⃣ {search_str} 판매 현황 및 점유율")
            
            if not doc_sales_today.exists:
                st.error("❌ 오늘 판매량 데이터가 없습니다.")
            else:
                df_sales = pd.DataFrame.from_dict(doc_sales_today.to_dict()['data']).apply(pd.to_numeric, errors='coerce')
                
                # [수정됨] 사용자 지정 정렬 적용
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
                
                # [수정됨] 색상 피로도 개선 (Soft Red)
                # vmax=200으로 설정하면 100%일 때 너무 진하지 않은 '중간 빨강' 정도가 나옵니다.
                idx = pd.IndexSlice
                st.dataframe(
                    df_combined.style
                    .format("{:.0f}", subset=idx[:, (slice(None), '판매')], na_rep="") 
                    .format("{:.1f}%", subset=idx[:, (slice(None), 'OCC')], na_rep="")
                    .background_gradient(
                        cmap='Reds', 
                        vmin=0, 
                        vmax=200,   # [핵심] 100이 아닌 200으로 잡아서 100%가 연한 빨강이 되게 함
                        subset=idx[:, (slice(None), 'OCC')]
                    ),
                    height=600,
                    use_container_width=True
                )

            st.divider()

            # ----------------------------------------------------------
            # SECTION 3: 하단 - Pickup
            # ----------------------------------------------------------
            st.markdown("### 3️⃣ 전일 대비 변동 (Pickup)")
            
            if doc_sales_yest.exists and doc_sales_today.exists:
                df_yest = pd.DataFrame.from_dict(doc_sales_yest.to_dict()['data']).apply(pd.to_numeric, errors='coerce')
                
                # [수정됨] 사용자 지정 정렬 적용
                df_sales_sorted = sort_rows_custom(df_sales)
                df_yest_sorted = sort_rows_custom(df_yest)
                
                common_dates = sorted(list(set(sales_dates).intersection(df_yest_sorted.columns)))
                
                if common_dates:
                    df_pickup = df_sales_sorted[common_dates].sub(df_yest_sorted[common_dates], fill_value=0)
                    
                    # Pickup 색상은 유지하되 너무 쨍하면 조정 가능 (현재 유지)
                    def color_pickup(val):
                        if val > 0: return 'color: blue; font-weight: bold; background-color: #f0f8ff'
                        elif val < 0: return 'color: red; font-weight: bold; background-color: #fff0f0'
                        else: return 'color: lightgrey'

                    st.dataframe(
                        df_pickup.style.applymap(color_pickup).format("{:+.0f}", na_rep=""),
                        use_container_width=True
                    )
                else:
                    st.warning("날짜 매칭 실패")
            else:
                st.warning("어제 데이터 없음")
