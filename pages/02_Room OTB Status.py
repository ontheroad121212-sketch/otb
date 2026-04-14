import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
import datetime
import re
import pytz # 시차 해결을 위해 추가

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
# 2. 데이터 처리 엔진 (정렬 로직 유지)
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
        # [수정된 부분] x가 실수(NaN)일 경우를 대비해 확실하게 str(x)로 감싸줍니다.
        date_count = row.apply(lambda x: '-' in str(x) or '/' in str(x)).sum()
        
        # [수정된 부분] 결측치가 있을 때 에러가 나지 않도록 na=False 옵션을 추가합니다.
        has_gdb = row.astype(str).str.contains('GDB', na=False).any()
        
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
        row_str = "".join(df.loc[idx].astype(str).to_numpy().flatten())
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
# [TAB 1] 업로드 (수정됨: 날짜 선택 기능 + 한국 시간 적용)
# ==========================================================================
with tab_upload:
    st.info("💡 과거 데이터가 누락되었다면, 아래 '저장 날짜'를 변경해서 올리세요.")
    
    # 암호 입력창
    admin_pw = st.text_input("🔑 관리자 암호 (저장하려면 입력하세요)", type="password")
    
    st.divider()
    
    c1, c2 = st.columns(2)
    
    # 한국 시간 설정
    KST = pytz.timezone('Asia/Seoul')
    now_kst = datetime.datetime.now(KST)

    # 1. 오늘 판매량
    with c1:
        st.subheader("1. 오늘 판매량 (Snapshot)")
        
        # [NEW] 저장 날짜 선택 기능 (기본값: 오늘)
        save_date = st.date_input(
            "📅 저장할 날짜 선택 (과거 데이터 복구용)", 
            now_kst.date()
        )

        files_today = st.file_uploader("오늘 판매 파일들 (드래그)", accept_multiple_files=True, key="today")
        
        if st.button("오늘 판매량 저장", type="primary"):
            if admin_pw == "9999": # 암호 확인
                if files_today:
                    df = merge_files(files_today)
                    if df is not None:
                        df_save = df.fillna(0)
                        
                        # [핵심] 선택한 날짜를 문자열로 변환하여 문서 ID로 사용
                        target_date_str = save_date.strftime("%Y-%m-%d")
                        
                        # DB 저장
                        db.collection("daily_sales_snapshot").document(target_date_str).set({
                            "data": df_save.to_dict(), 
                            "created_at": datetime.datetime.now(KST) # 실제 저장 시간은 현재로 기록
                        })
                        st.success(f"✅ {target_date_str} 날짜로 저장 완료! (과거 데이터 복구 성공)")
                        st.cache_data.clear() # 캐시 초기화
                else:
                    st.warning("파일을 먼저 선택해주세요.")
            else:
                st.error("⛔ 암호가 틀렸습니다!")

    # 2. 남은 객실 (Availability)
    with c2:
        st.subheader("2. 남은 객실 (Availability)")
        files_avail = st.file_uploader("남은 객실 파일들 (드래그)", accept_multiple_files=True, key="avail")
        
        if st.button("남은 객실 저장"):
            if admin_pw == "9999": # 암호 확인
                if files_avail:
                    df = merge_files(files_avail)
                    if df is not None:
                        df_save = df.fillna(0)
                        # DB 저장 (최신 상태 덮어쓰기)
                        db.collection("hotel_settings").document("latest_availability_view").set({
                            "data": df_save.to_dict(), "updated_at": datetime.datetime.now(KST)
                        })
                        st.success("✅ 남은 객실 데이터 업데이트 완료!")
                else:
                    st.warning("파일을 먼저 선택해주세요.")
            else:
                st.error("⛔ 암호가 틀렸습니다!")

# ==========================================================================
# [TAB 2] 리포트 (수정됨: 조회 기준일 한국시간 적용)
# ==========================================================================
with tab_dashboard:
    st.header("📊 객실 통합 리포트")
    
    col_sel, col_btn = st.columns([1, 4])
    with col_sel:
        # [핵심] 조회 달력의 기본값을 '한국 시간' 오늘로 변경
        KST = pytz.timezone('Asia/Seoul')
        today_kst_date = datetime.datetime.now(KST).date()
        
        search_date = st.date_input("조회 기준일", today_kst_date)
        search_str = search_date.strftime("%Y-%m-%d")
        yest_str = (search_date - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    
    with col_btn:
        st.write("")
        st.write("")
        if st.button("🚀 리포트 불러오기", type="primary"):
            
            # 1. 오늘/가용 객실 데이터 로드
            doc_sales_today = db.collection("daily_sales_snapshot").document(search_str).get()
            doc_avail = db.collection("hotel_settings").document("latest_availability_view").get()

            # ------------------------------------------------------------------
            # [핀셋 수정] 비교일(어제) 데이터 찾는 로직 강화
            # ------------------------------------------------------------------
            # 일단 어제 날짜로 시도
            doc_sales_yest = db.collection("daily_sales_snapshot").document(yest_str).get()
            compare_date_str = yest_str # 기본값은 어제

            # 만약 어제 데이터가 없다면? (주말 등) -> DB 뒤져서 가장 최신 과거 날짜 찾기
            if not doc_sales_yest.exists:
                # DB에 있는 모든 문서 ID(날짜)를 가져옴
                all_docs = [d.id for d in db.collection("daily_sales_snapshot").list_documents()]
                # 조회 기준일(search_str)보다 작은(과거) 날짜들만 필터링하고, 최신순(내림차순) 정렬
                past_dates = sorted([d for d in all_docs if d < search_str], reverse=True)
                
                if past_dates:
                    compare_date_str = past_dates[0] # 가장 최근의 과거 데이터 날짜 선택
                    doc_sales_yest = db.collection("daily_sales_snapshot").document(compare_date_str).get()
            # ------------------------------------------------------------------

            # SECTION 1: 상단 - 남은 객실 (Availability)
            st.markdown("### 1️⃣ 남은 객실 수 (Available Rooms) - GM 참고용")
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

            # SECTION 2: 중단 - 실제 판매 & OCC
            st.markdown(f"### 2️⃣ {search_str} 판매 현황 및 점유율")
            
            if not doc_sales_today.exists:
                st.error(f"❌ '{search_str}' 날짜의 판매 데이터가 없습니다. 업로드 탭에서 올려주세요.")
            else:
                df_sales = pd.DataFrame.from_dict(doc_sales_today.to_dict()['data']).apply(pd.to_numeric, errors='coerce')
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

            # SECTION 3: 하단 - Pickup (자동 매칭된 비교일 사용)
            # 날짜가 자동으로 바뀌었으면 표시해줌
            pickup_title = f"### 3️⃣ 비교일({compare_date_str}) 대비 변동 (Pickup)"
            if compare_date_str != yest_str:
                pickup_title += f" 🚨어제 데이터가 없어 {compare_date_str} 데이터와 비교합니다."
            
            st.markdown(pickup_title)
            
            # 비교 데이터가 있는지 확인
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
                        st.warning("⚠️ 오늘과 비교 대상 데이터 간에 겹치는 날짜(Future dates)가 하나도 없습니다.")
                else:
                    st.warning(f"⚠️ {yest_str} (어제) 데이터도 없고, 그 이전 과거 데이터도 DB에 하나도 없습니다.")
            else:
                pass
