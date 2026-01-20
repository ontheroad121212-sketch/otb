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
st.title("🏨 객실 판매 및 OCC 통합 리포트")

if not firebase_admin._apps:
    cred = credentials.Certificate(dict(st.secrets["firebase"]))
    firebase_admin.initialize_app(cred)
db = firestore.client()

# --------------------------------------------------------------------------
# 2. 강력한 엑셀 로더 (헤더 찾기 & 날짜 통일 & 노란색 데이터 살리기)
# --------------------------------------------------------------------------

def normalize_date_columns(df):
    """
    서로 다른 날짜 형식(01-19 vs 2026-01-19)을 'YYYY-MM-DD'로 강제 통일합니다.
    """
    new_cols = []
    # 현재 연도 (만약 파일에 연도가 없으면 붙여줄 용도)
    current_year = "2026" 
    
    for col in df.columns:
        # 1. 만약 이미 datetime 객체라면 -> '2026-01-20' 문자열로 변환
        if isinstance(col, (pd.Timestamp, datetime.date, datetime.datetime)):
            new_cols.append(col.strftime("%Y-%m-%d"))
        
        # 2. 문자열인 경우
        elif isinstance(col, str):
            col_str = col.strip().replace(" 00:00:00", "") # 시간 제거
            
            # 패턴 A: '01-19' 처럼 월-일만 있는 경우 -> '2026-01-19'로 변경
            # 정규표현식: 숫자1~2개 + 하이픈 + 숫자1~2개 (예: 1-19, 01-19)
            if re.match(r'^\d{1,2}-\d{1,2}$', col_str):
                new_cols.append(f"{current_year}-{col_str.zfill(5)}") # 01-19 형태로 맞춤
            
            # 패턴 B: '2026-01-19' 처럼 이미 완벽한 경우 -> 그대로 둠
            elif re.match(r'^\d{4}-\d{1,2}-\d{1,2}$', col_str):
                new_cols.append(col_str)
                
            # 날짜가 아닌 컬럼(객실타입 등) -> 그대로 둠
            else:
                new_cols.append(col_str)
        
        # 기타 숫자형 등
        else:
            new_cols.append(str(col))
            
    df.columns = new_cols
    return df

def find_header_row(df_raw):
    """데이터프레임에서 실제 날짜가 있는 헤더 행의 인덱스를 찾습니다."""
    for i, row in df_raw.head(20).iterrows():
        # '-'나 '/'가 포함된 날짜 형태가 3개 이상 있으면 헤더로 간주
        date_count = row.astype(str).apply(lambda x: '-' in x or '/' in x).sum()
        # 혹은 'GDB' 같은 룸타입이 있어도 헤더로 간주
        has_gdb = row.astype(str).str.contains('GDB').any()
        
        if date_count > 3 or has_gdb:
            return i
    return 0 

def process_uploaded_df(file):
    # 1. 헤더 없이 읽기
    df_raw = pd.read_excel(file, header=None)
    
    # 2. 진짜 헤더 위치 찾아서 다시 읽기
    header_idx = find_header_row(df_raw)
    df = pd.read_excel(file, header=header_idx)
    
    # 3. 첫 번째 컬럼(룸타입) 설정
    if df.columns[0].startswith('Unnamed'):
        df.rename(columns={df.columns[0]: '구분'}, inplace=True)
    df.set_index(df.columns[0], inplace=True)
    
    # 4. [중요] 날짜 컬럼 형식 통일 (YYYY-MM-DD)
    df = normalize_date_columns(df)
    
    # 5. '요일' 행(월, 화...) 삭제
    rows_to_drop = []
    for idx in df.index[:20]:
        s_idx = str(idx)
        if s_idx in ['객실수', 'Room Qty', 'nan', 'NaT', 'None']:
            rows_to_drop.append(idx)
            continue
        
        row_values = df.loc[idx].astype(str).values.flatten()
        row_str = "".join(row_values)
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
            st.error(f"파일 {f.name} 처리 중 오류: {e}")
            
    if not df_list: return None
    
    # 옆으로 합치기
    merged = pd.concat(df_list, axis=1, sort=False)
    # 중복 날짜 제거
    merged = merged.loc[:, ~merged.columns.duplicated()]
    return merged

# --------------------------------------------------------------------------
# 3. UI 구성
# --------------------------------------------------------------------------
tab_upload, tab_dashboard = st.tabs(["📤 데이터 업로드 (다시 올려주세요!)", "📊 통합 리포트 (VIEW)"])

# ==========================================================================
# [TAB 1] 업로드
# ==========================================================================
with tab_upload:
    st.warning("⚠️ 날짜 형식 오류가 있었다면, 파일을 다시 업로드해야 해결됩니다!")
    
    c1, c2, c3 = st.columns(3)
    
    # 1. 오늘 스냅샷
    with c1:
        st.subheader("1. 오늘 스냅샷")
        files_today = st.file_uploader("오늘 파일 4개", accept_multiple_files=True, key="today")
        if st.button("오늘 데이터 저장"):
            if files_today:
                df = merge_files(files_today)
                if df is not None:
                    df_save = df.fillna(0)
                    today_str = datetime.date.today().strftime("%Y-%m-%d")
                    db.collection("daily_room_snapshots").document(today_str).set({
                        "data": df_save.to_dict(), "created_at": datetime.datetime.now()
                    })
                    st.success(f"✅ {today_str} 저장 완료! (날짜 포맷 통일됨)")
                    st.dataframe(df.head())

    # 2. 어제 스냅샷
    with c2:
        st.subheader("2. 어제 스냅샷")
        yest_date = st.date_input("어제 날짜", datetime.date.today() - datetime.timedelta(days=1))
        yest_str = yest_date.strftime("%Y-%m-%d")
        files_yest = st.file_uploader("어제 파일 4개", accept_multiple_files=True, key="yest")
        if st.button("어제 데이터 저장"):
            if files_yest:
                df = merge_files(files_yest)
                if df is not None:
                    df_save = df.fillna(0)
                    db.collection("daily_room_snapshots").document(yest_str).set({
                        "data": df_save.to_dict(), "created_at": datetime.datetime.now()
                    })
                    st.success(f"✅ {yest_str} 저장 완료!")

    # 3. Capacity
    with c3:
        st.subheader("3. Capacity (필수)")
        files_capa = st.file_uploader("Capacity 파일 4개", accept_multiple_files=True, key="capa")
        if st.button("Capacity 저장"):
            if files_capa:
                df = merge_files(files_capa)
                if df is not None:
                    df_save = df.fillna(0)
                    db.collection("hotel_settings").document("latest_availability").set({
                        "data": df_save.to_dict(), "updated_at": datetime.datetime.now()
                    })
                    st.success("✅ Capacity 저장 완료! (날짜 포맷 통일됨)")
                    st.dataframe(df.head())

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
            doc_today = db.collection("daily_room_snapshots").document(search_str).get()
            doc_capa = db.collection("hotel_settings").document("latest_availability").get()
            doc_yest = db.collection("daily_room_snapshots").document(yest_str).get()

            if not doc_today.exists:
                st.error(f"❌ '{search_str}' 데이터가 없습니다. 옆 탭에서 업로드해주세요.")
            elif not doc_capa.exists:
                st.error("❌ 'Capacity' 데이터가 없습니다. 옆 탭에서 업로드해주세요.")
            else:
                # DataFrame 변환
                df_today = pd.DataFrame.from_dict(doc_today.to_dict()['data']).apply(pd.to_numeric, errors='coerce')
                df_capa = pd.DataFrame.from_dict(doc_capa.to_dict()['data']).apply(pd.to_numeric, errors='coerce').fillna(0)
                
                df_yest = pd.DataFrame()
                if doc_yest.exists:
                    df_yest = pd.DataFrame.from_dict(doc_yest.to_dict()['data']).apply(pd.to_numeric, errors='coerce').fillna(0)

                # 날짜 교집합 확인 (여기가 문제였음 -> 해결!)
                common_dates = sorted(list(set(df_today.columns).intersection(df_capa.columns)))

                if not common_dates:
                    st.error(f"⚠️ 날짜 매칭 실패!\n\n오늘 스냅샷 날짜 예시: {list(df_today.columns)[:3]}\nCapacity 날짜 예시: {list(df_capa.columns)[:3]}\n\n두 파일의 날짜 형식이 다릅니다. 업로드 탭에서 둘 다 다시 업로드해주세요.")
                else:
                    # ----------------------------------------------------------
                    # 뷰 생성 (OCC 계산 & 병합)
                    # ----------------------------------------------------------
                    
                    # 1) OCC 계산 (룸타입 부분만)
                    common_idx = df_today.index.intersection(df_capa.index)
                    df_occ_calc = df_today.loc[common_idx, common_dates].div(df_capa.loc[common_idx, common_dates]).fillna(0) * 100

                    # 2) 병합 [객실수 | 비율(%)]
                    frames = {}
                    for date in common_dates:
                        qty_col = df_today[date].copy()
                        
                        occ_col = pd.Series(index=df_today.index, dtype=float)
                        occ_col.update(df_occ_calc[date]) # 룸타입만 채우기
                        
                        # 합계 행의 OCC는 여기서 계산 안 됨 (필요시 별도 로직 필요)
                        
                        frame = pd.DataFrame({
                            '객실수': qty_col,
                            '비율(%)': occ_col
                        })
                        frames[date] = frame
                    
                    df_combined = pd.concat(frames, axis=1)

                    st.success(f"데이터 매칭 성공! ({len(common_dates)}일치)")

                    # 1. Capacity
                    with st.expander("🔻 전체 객실 수 (Capacity) 확인"):
                        st.dataframe(df_capa, use_container_width=True)

                    # 2. 메인 리포트
                    st.markdown("### 2️⃣ 일자별 판매 현황 및 OCC")
                    idx = pd.IndexSlice
                    st.dataframe(
                        df_combined.style
                        .format("{:.0f}", subset=idx[:, (slice(None), '객실수')], na_rep="") 
                        .format("{:.1f}%", subset=idx[:, (slice(None), '비율(%)')], na_rep="")
                        .background_gradient(cmap='Reds', vmin=0, vmax=100, subset=idx[:, (slice(None), '비율(%)')]),
                        height=600,
                        use_container_width=True
                    )

                    # 3. Pickup
                    st.markdown("### 3️⃣ 전일 대비 변동 (Pickup)")
                    if not df_yest.empty:
                        pickup_dates = sorted(list(set(df_today.columns).intersection(df_yest.columns)))
                        pickup_idx = df_today.index.intersection(df_yest.index)
                        
                        if pickup_dates:
                            df_pickup = df_today.loc[pickup_idx, pickup_dates].sub(df_yest.loc[pickup_idx, pickup_dates], fill_value=0)
                            
                            def color_pickup(val):
                                if val > 0: return 'color: blue; font-weight: bold; background-color: #f0f8ff'
                                elif val < 0: return 'color: red; font-weight: bold; background-color: #fff0f0'
                                else: return 'color: lightgrey'

                            st.dataframe(
                                df_pickup.style.applymap(color_pickup).format("{:+.0f}", na_rep=""),
                                use_container_width=True
                            )
                        else:
                            st.warning("어제 데이터와 날짜가 겹치지 않습니다.")
                    else:
                        st.warning("어제 데이터가 없습니다.")
