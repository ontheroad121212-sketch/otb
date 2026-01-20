import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
import datetime
import re

# 1. 페이지 설정
st.set_page_config(page_title="객실 데이터 관리", layout="wide")
st.title("📅 객실 데이터 업로드 및 분석 대시보드")

# 2. 파이어베이스 연결
if not firebase_admin._apps:
    cred = credentials.Certificate(dict(st.secrets["firebase"]))
    firebase_admin.initialize_app(cred)
db = firestore.client()

# --- 데이터 전처리 함수 (헤더 정리, 불필요한 행 삭제) ---
def process_uploaded_df(file):
    # 1. 엑셀 읽기 (header=0: 첫 번째 줄을 컬럼으로 인식)
    # 인덱스는 지정하지 않고 읽은 뒤에 처리합니다.
    df = pd.read_excel(file, header=0)
    
    # 2. 첫 번째 컬럼(룸타입)을 찾아서 인덱스로 설정
    # 보통 첫 번째 열('Unnamed: 0' 또는 '객실' 등)이 룸타입입니다.
    first_col = df.columns[0]
    df.set_index(first_col, inplace=True)
    
    # 3. [헤더 정리] '요일'이 들어있는 줄(월, 화, 수...) 제거
    # 보통 날짜 바로 밑에 요일이 있어서, 데이터의 첫 번째 줄이 요일인 경우가 많습니다.
    # 인덱스나 첫 번째 열 값을 확인해서 '월', 'Tue' 등이 있으면 그 줄 삭제
    # (안전하게 첫 5줄 중에서 '월'이나 'Mon'이 포함된 행을 찾아서 지웁니다)
    rows_to_drop = []
    for idx in df.index[:5]:
        s_idx = str(idx)
        # 인덱스 자체가 '객실수'이거나 값이 '월','화'.. 인 행 제거
        if s_idx in ['객실수', '월', '화', '수', '목', '금', '토', '일']:
            rows_to_drop.append(idx)
    
    if rows_to_drop:
        df = df.drop(rows_to_drop)

    # 4. [불필요한 룸타입 제거] Property, Amber, Pure Hill 등
    # 제거할 키워드 리스트
    exclude_keywords = ['Property', 'Amber', 'Pure', 'Hill', '프로퍼티', '엠버', '퓨어', '힐']
    
    # 인덱스(룸타입 이름)를 문자열로 바꿔서 검색
    # keep=False로 설정하여 해당 키워드가 포함된 행을 찾음
    mask = df.index.to_series().astype(str).apply(
        lambda x: any(k.lower() in x.lower() for k in exclude_keywords)
    )
    # 해당 키워드가 '없는' 행만 남김 (~)
    df = df[~mask]

    return df

# --- 인덱스 중복 해결 (합계 등이 겹칠 때) ---
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

# --- 탭 구성 ---
tab1, tab2 = st.tabs(["📤 데이터 업로드 (오늘/어제)", "📊 대시보드"])

# =========================================================
# [TAB 1] 업로드 섹션 (오늘, 어제, 캐파)
# =========================================================
with tab1:
    col_today, col_yest = st.columns(2)

    # --- 1. 오늘 데이터 업로드 ---
    with col_today:
        st.subheader("1. 오늘자 스냅샷 (Today)")
        st.caption("오늘 날짜로 저장됩니다.")
        files_today = st.file_uploader("오늘 파일 4개", accept_multiple_files=True, type=['xlsx', 'xls'], key="today")
        
        if st.button("오늘 데이터 저장"):
            if files_today:
                try:
                    df_list = []
                    for file in files_today:
                        df = process_uploaded_df(file) # 전처리 적용
                        df = make_index_unique(df)
                        df_list.append(df)
                    
                    merged = pd.concat(df_list, axis=1)
                    merged = merged.loc[:, ~merged.columns.duplicated()] # 날짜 중복 제거
                    merged = merged.fillna(0)
                    merged.columns = merged.columns.astype(str) # 컬럼명 문자열로

                    today_str = datetime.date.today().strftime("%Y-%m-%d")
                    db.collection("daily_room_snapshots").document(today_str).set({
                        "data": merged.to_dict(),
                        "created_at": datetime.datetime.now()
                    })
                    st.success(f"✅ {today_str} 저장 완료! (불필요한 행 제거됨)")
                    st.dataframe(merged.head())
                except Exception as e:
                    st.error(f"에러: {e}")

    # --- 2. 어제 데이터 업로드 (초기 세팅용) ---
    with col_yest:
        st.subheader("2. 어제자 스냅샷 (Yesterday)")
        st.caption("비교를 위해 어제 날짜로 강제 저장합니다.")
        
        # 어제 날짜 자동 계산
        default_yest = datetime.date.today() - datetime.timedelta(days=1)
        target_date = st.date_input("저장할 날짜 선택", default_yest)
        target_date_str = target_date.strftime("%Y-%m-%d")

        files_yest = st.file_uploader("어제 파일 4개", accept_multiple_files=True, type=['xlsx', 'xls'], key="yest")
        
        if st.button(f"{target_date_str} 날짜로 저장"):
            if files_yest:
                try:
                    df_list = []
                    for file in files_yest:
                        df = process_uploaded_df(file) # 전처리 적용
                        df = make_index_unique(df)
                        df_list.append(df)
                    
                    merged = pd.concat(df_list, axis=1)
                    merged = merged.loc[:, ~merged.columns.duplicated()]
                    merged = merged.fillna(0)
                    merged.columns = merged.columns.astype(str)

                    db.collection("daily_room_snapshots").document(target_date_str).set({
                        "data": merged.to_dict(),
                        "created_at": datetime.datetime.now()
                    })
                    st.success(f"✅ {target_date_str} 저장 완료!")
                    st.dataframe(merged.head())
                except Exception as e:
                    st.error(f"에러: {e}")

    st.markdown("---")
    
    # --- 3. 객실 정원 (Capacity) ---
    st.subheader("3. 객실 총 수량 (Capacity)")
    st.caption("OCC 계산용 분모 데이터")
    files_capa = st.file_uploader("가용 객실 파일 업로드", accept_multiple_files=True, type=['xlsx', 'xls'], key="capa")
    
    if st.button("Capacity 설정 업데이트"):
        if files_capa:
            try:
                df_list = []
                for file in files_capa:
                    df = process_uploaded_df(file)
                    df = make_index_unique(df)
                    df_list.append(df)
                
                merged = pd.concat(df_list, axis=1)
                merged = merged.loc[:, ~merged.columns.duplicated()]
                merged = merged.fillna(0)
                merged.columns = merged.columns.astype(str)

                db.collection("hotel_settings").document("latest_availability").set({
                    "data": merged.to_dict(),
                    "updated_at": datetime.datetime.now()
                })
                st.success("✅ Capacity 설정 완료!")
            except Exception as e:
                st.error(f"에러: {e}")

# =========================================================
# [TAB 2] 대시보드
# =========================================================
with tab2:
    st.header("📊 객실 현황 대시보드")
    
    search_date = st.date_input("조회 기준일", datetime.date.today())
    search_date_str = search_date.strftime("%Y-%m-%d")
    yesterday_date = search_date - datetime.timedelta(days=1)
    yesterday_str = yesterday_date.strftime("%Y-%m-%d")

    if st.button("데이터 불러오기"):
        with st.spinner("데이터 로딩 중..."):
            try:
                # 1. 데이터 로드
                doc_today = db.collection("daily_room_snapshots").document(search_date_str).get()
                doc_yest = db.collection("daily_room_snapshots").document(yesterday_str).get()
                doc_capa = db.collection("hotel_settings").document("latest_availability").get()

                if not doc_today.exists:
                    st.error(f"❌ {search_date_str} 데이터가 없습니다. 업로드 탭에서 올려주세요.")
                else:
                    df_today = pd.DataFrame.from_dict(doc_today.to_dict()['data'])
                    df_today = df_today.apply(pd.to_numeric, errors='coerce').fillna(0)

                    df_yest = pd.DataFrame()
                    if doc_yest.exists:
                        df_yest = pd.DataFrame.from_dict(doc_yest.to_dict()['data'])
                        df_yest = df_yest.apply(pd.to_numeric, errors='coerce').fillna(0)
                    
                    df_capa = pd.DataFrame()
                    if doc_capa.exists:
                        df_capa = pd.DataFrame.from_dict(doc_capa.to_dict()['data'])
                        df_capa = df_capa.apply(pd.to_numeric, errors='coerce').fillna(0)

                    # 2. 화면 표시
                    st.markdown(f"### 1. 판매 현황 ({search_date_str})")
                    st.dataframe(df_today.style.format("{:.0f}"), height=400)

                    st.markdown("### 2. 점유율 (OCC %)")
                    if not df_capa.empty:
                        # 교집합 인덱스/컬럼만 계산
                        idx = df_today.index.intersection(df_capa.index)
                        cols = df_today.columns.intersection(df_capa.columns)
                        
                        df_occ = (df_today.loc[idx, cols] / df_capa.loc[idx, cols] * 100).fillna(0).round(1)
                        
                        st.dataframe(
                            df_occ.style.background_gradient(cmap='Reds', vmin=0, vmax=100).format("{:.1f}%"),
                            height=400
                        )
                    else:
                        st.warning("Capacity 데이터가 없습니다.")

                    st.markdown(f"### 3. 변화량 (Pickup) vs {yesterday_str}")
                    if not df_yest.empty:
                        # 날짜 매칭해서 빼기
                        df_pickup = df_today.sub(df_yest, fill_value=0)
                        
                        # 오늘 날짜에 해당하는 컬럼만 보기 (너무 옛날 데이터는 제외하고 싶으면 여기서 필터링)
                        # 여기선 전체 다 보여줍니다.
                        
                        def color_pickup(val):
                            if val > 0: return 'color: blue; font-weight: bold'
                            elif val < 0: return 'color: red; font-weight: bold'
                            else: return 'color: lightgrey'

                        st.dataframe(
                            df_pickup.style.applymap(color_pickup).format("{:+.0f}"),
                            height=400
                        )
                    else:
                        st.warning(f"{yesterday_str} 데이터가 없어서 변화량을 계산할 수 없습니다.")

            except Exception as e:
                st.error(f"오류 발생: {e}")
