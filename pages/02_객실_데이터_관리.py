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
# 2. 강력한 엑셀 로더 (헤더 찾기 & 노란색 데이터 모두 살리기)
# --------------------------------------------------------------------------
def find_header_row(df_raw):
    """데이터프레임에서 실제 날짜가 있는 헤더 행의 인덱스를 찾습니다."""
    for i, row in df_raw.head(20).iterrows():
        row_str = row.astype(str).str.cat(sep=' ')
        # 1. '-'가 포함된 날짜 형태가 3개 이상 있거나
        # 2. 'GDB' 같은 룸타입 키워드가 포함된 경우 헤더로 간주
        date_count = row.astype(str).apply(lambda x: '-' in x or x.replace('.','').isdigit()).sum()
        if date_count > 5:  # 날짜가 5개 이상이면 확실함
            return i
    return 0 # 못 찾으면 첫 줄

def process_uploaded_df(file):
    # 1. 일단 헤더 없이 읽기
    df_raw = pd.read_excel(file, header=None)
    
    # 2. 진짜 헤더 위치 찾기
    header_idx = find_header_row(df_raw)
    
    # 3. 진짜 헤더로 다시 읽기
    df = pd.read_excel(file, header=header_idx)
    
    # 4. 첫 번째 컬럼(룸타입) 인덱스 설정
    # 컬럼명이 Unnamed라면 '구분'으로 변경
    if df.columns[0].startswith('Unnamed'):
        df.rename(columns={df.columns[0]: '구분'}, inplace=True)
    df.set_index(df.columns[0], inplace=True)
    
    # 5. [중요] '요일' 행(월, 화, 수...)만 콕 집어서 삭제
    # 노란색 데이터(합계, 고장객실 등)는 살려야 하므로 조건 조심!
    rows_to_drop = []
    for idx in df.index[:20]: # 상위 20줄 검사
        s_idx = str(idx)
        # 인덱스 자체가 '객실수', '요일', 'nan' 인 경우 삭제
        if s_idx in ['객실수', 'Room Qty', 'nan', 'NaT', 'None']:
            rows_to_drop.append(idx)
            continue
            
        # 행 데이터에 '월', '화', 'Mon'이 포함되어 있으면 요일 줄로 간주하고 삭제
        row_values = df.loc[idx].astype(str).values.flatten()
        row_str = "".join(row_values)
        if any(day in row_str for day in ['월', '화', '수', '목', '금', '토', '일', 'Mon', 'Tue']):
             rows_to_drop.append(idx)

    if rows_to_drop:
        df = df.drop(rows_to_drop)

    # 6. 빈 행 제거
    df = df.dropna(how='all')
    
    return df

def make_index_unique(df):
    """인덱스 중복 방지 (합계가 여러 개일 경우 등)"""
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
    """4개 파일 병합"""
    if not files: return None
    df_list = []
    for f in files:
        try:
            df = process_uploaded_df(f)
            df = make_index_unique(df)
            # 날짜 컬럼만 문자열로 변환 (시분초 제거)
            new_cols = []
            for col in df.columns:
                s_col = str(col).replace(" 00:00:00", "")
                new_cols.append(s_col)
            df.columns = new_cols
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
tab_upload, tab_dashboard = st.tabs(["📤 데이터 업로드", "📊 통합 리포트 (VIEW)"])

# ==========================================================================
# [TAB 1] 업로드
# ==========================================================================
with tab_upload:
    st.info("💡 4개월치 파일을 한꺼번에 드래그해서 올리세요.")
    
    c1, c2, c3 = st.columns(3)
    
    # 1. 오늘 스냅샷
    with c1:
        st.subheader("1. 오늘 스냅샷 (필수)")
        files_today = st.file_uploader("오늘 파일 4개", accept_multiple_files=True, key="today")
        if st.button("오늘 데이터 저장"):
            if files_today:
                df = merge_files(files_today)
                if df is not None:
                    # NaN을 0으로 채우지 않음! (합계 계산 등을 위해 원본 유지)
                    # 단, 저장을 위해 문자열로 변환하거나 0 처리 필요할 수 있음. 
                    # 여기선 일단 0으로 채워서 저장 (계산 편의성)
                    df_save = df.fillna(0)
                    
                    today_str = datetime.date.today().strftime("%Y-%m-%d")
                    db.collection("daily_room_snapshots").document(today_str).set({
                        "data": df_save.to_dict(), "created_at": datetime.datetime.now()
                    })
                    st.success(f"✅ {today_str} 저장 완료!")
                    st.dataframe(df.head())

    # 2. 어제 스냅샷
    with c2:
        st.subheader("2. 어제 스냅샷 (비교용)")
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
        st.subheader("3. Capacity (기준값)")
        st.caption("OCC 계산을 위한 분모 데이터")
        files_capa = st.file_uploader("Capacity 파일 4개", accept_multiple_files=True, key="capa")
        if st.button("Capacity 저장"):
            if files_capa:
                df = merge_files(files_capa)
                if df is not None:
                    df_save = df.fillna(0)
                    db.collection("hotel_settings").document("latest_availability").set({
                        "data": df_save.to_dict(), "updated_at": datetime.datetime.now()
                    })
                    st.success("✅ Capacity 저장 완료!")

# ==========================================================================
# [TAB 2] 리포트 (핵심 로직 구현)
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
            
            # 1. DB 로드
            doc_today = db.collection("daily_room_snapshots").document(search_str).get()
            doc_capa = db.collection("hotel_settings").document("latest_availability").get()
            doc_yest = db.collection("daily_room_snapshots").document(yest_str).get()

            if not doc_today.exists:
                st.error(f"❌ '{search_str}' 데이터가 없습니다. 먼저 업로드해주세요.")
            elif not doc_capa.exists:
                st.error("❌ 'Capacity' 데이터가 없습니다. 먼저 업로드해주세요.")
            else:
                # 2. DataFrame 변환 (숫자형 변환)
                df_today = pd.DataFrame.from_dict(doc_today.to_dict()['data']).apply(pd.to_numeric, errors='coerce')
                df_capa = pd.DataFrame.from_dict(doc_capa.to_dict()['data']).apply(pd.to_numeric, errors='coerce').fillna(0)
                
                df_yest = pd.DataFrame()
                if doc_yest.exists:
                    df_yest = pd.DataFrame.from_dict(doc_yest.to_dict()['data']).apply(pd.to_numeric, errors='coerce').fillna(0)

                # 3. 공통 날짜 컬럼 추출 및 정렬
                # (4개월치 파일이므로 날짜가 아주 많습니다)
                valid_dates = sorted([c for c in df_today.columns if '-' in str(c)])
                
                # Capacity와 날짜가 겹치는 부분만 계산 가능
                common_dates = sorted(list(set(valid_dates).intersection(df_capa.columns)))

                if not common_dates:
                    st.error("스냅샷과 Capacity 파일 간에 겹치는 날짜가 하나도 없습니다. 날짜 형식을 확인해주세요.")
                else:
                    # ----------------------------------------------------------
                    # [핵심] 뷰 생성 로직: [날짜] -> [Qty | OCC]
                    # ----------------------------------------------------------
                    
                    # 1) OCC 계산 (룸타입 매칭되는 행만 계산)
                    # Capacity에는 '합계'나 '고장객실' 행이 없을 수 있으므로,
                    # 교집합 인덱스(룸타입)에 대해서만 나눗셈을 수행합니다.
                    
                    common_idx = df_today.index.intersection(df_capa.index)
                    
                    # 부분 계산: Sales / Capacity
                    df_occ_calc = df_today.loc[common_idx, common_dates].div(df_capa.loc[common_idx, common_dates]).fillna(0) * 100

                    # 2) 최종 표시용 DataFrame 만들기
                    # 날짜별로 (Qty, OCC) 두 개의 컬럼을 만듭니다.
                    frames = {}
                    
                    for date in common_dates:
                        # 해당 날짜의 판매량 (모든 행 포함 - 합계, 고장객실 등)
                        qty_col = df_today[date].copy()
                        
                        # 해당 날짜의 OCC (계산된 룸타입 + 나머지는 NaN or 빈값)
                        # 먼저 빈 시리즈 생성
                        occ_col = pd.Series(index=df_today.index, dtype=float)
                        # 계산된 값 채워넣기 (룸타입 부분)
                        occ_col.update(df_occ_calc[date])
                        
                        # 합계, 고장객실 등은 OCC 계산이 안되므로 NaN 상태 (나중에 빈칸 처리)
                        
                        # 두 컬럼 합치기
                        frame = pd.DataFrame({
                            '객실수': qty_col,
                            '비율(%)': occ_col
                        })
                        frames[date] = frame
                    
                    # Multi-Column DataFrame 생성 (상위: 날짜, 하위: 객실수, 비율)
                    df_combined = pd.concat(frames, axis=1)

                    # ----------------------------------------------------------
                    # 화면 출력
                    # ----------------------------------------------------------
                    st.success(f"데이터 로드 성공! ({len(common_dates)}일치)")

                    # 1. Capacity 확인 (접기)
                    with st.expander("🔻 전체 객실 수 (Capacity) 확인"):
                        st.dataframe(df_capa, use_container_width=True)

                    # 2. 메인 리포트
                    st.markdown("### 2️⃣ 일자별 판매 현황 및 OCC")
                    st.caption("노란색 영역(하단 합계 등)도 모두 표시됩니다.")

                    # 스타일링: 비율(%) 컬럼만 빨간색 히트맵 + 소수점 1자리
                    # 객실수는 소수점 없이 정수로 (NaN이 있으면 float이 되므로 포맷팅 주의)
                    
                    idx = pd.IndexSlice
                    
                    st.dataframe(
                        df_combined.style
                        .format("{:.0f}", subset=idx[:, (slice(None), '객실수')], na_rep="") 
                        .format("{:.1f}%", subset=idx[:, (slice(None), '비율(%)')], na_rep="")
                        .background_gradient(cmap='Reds', vmin=0, vmax=100, subset=idx[:, (slice(None), '비율(%)')]),
                        height=600,
                        use_container_width=True
                    )

                    # 3. Pickup (변동량)
                    st.markdown("### 3️⃣ 전일 대비 변동 (Pickup)")
                    if df_yest.empty:
                        st.warning("어제 데이터가 없습니다.")
                    else:
                        # 겹치는 날짜와 인덱스만 계산
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
                            st.warning("오늘과 어제 데이터 간에 날짜가 매칭되지 않습니다.")
