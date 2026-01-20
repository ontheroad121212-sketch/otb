import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
import datetime

# 1. 페이지 설정
st.set_page_config(page_title="객실 데이터 관리", layout="wide")
st.title("📅 객실 데이터 업로드 및 분석 대시보드")

# 2. 파이어베이스 연결
if not firebase_admin._apps:
    cred = credentials.Certificate(dict(st.secrets["firebase"]))
    firebase_admin.initialize_app(cred)
db = firestore.client()

# --- 공통 함수: 인덱스 중복 해결 ---
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
tab1, tab2 = st.tabs(["📤 데이터 업로드 (오늘자)", "📊 대시보드 (OCC & 변화량)"])

# =========================================================
# [TAB 1] 데이터 업로드 (기존과 동일, 저장 기능)
# =========================================================
with tab1:
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("1. 룸 스냅샷 (오늘 판매량)")
        st.caption("4개월치 파일 4개를 드래그해서 올리세요.")
        snapshot_files = st.file_uploader("스냅샷 파일 업로드", accept_multiple_files=True, type=['xlsx', 'xls'], key="snap")
        
        if st.button("스냅샷 저장하기"):
            if snapshot_files:
                try:
                    df_list = []
                    for file in snapshot_files:
                        df = pd.read_excel(file)
                        if not df.empty:
                            df.set_index(df.columns[0], inplace=True)
                            df = make_index_unique(df)
                            df_list.append(df)
                    
                    merged_df = pd.concat(df_list, axis=1)
                    merged_df = merged_df.loc[:, ~merged_df.columns.duplicated()] # 날짜 중복 제거
                    merged_df.columns = merged_df.columns.astype(str)
                    merged_df = merged_df.fillna(0)
                    
                    today_str = datetime.date.today().strftime("%Y-%m-%d")
                    db.collection("daily_room_snapshots").document(today_str).set({
                        "data": merged_df.to_dict(),
                        "created_at": datetime.datetime.now()
                    })
                    st.success(f"✅ {today_str} 데이터 저장 완료!")
                except Exception as e:
                    st.error(f"에러 발생: {e}")

    with col2:
        st.subheader("2. 객실 총 수량 (Capacity)")
        st.caption("OCC 계산을 위한 분모 데이터입니다. (한 번만 올리면 됨)")
        avail_files = st.file_uploader("가용 객실 파일 업로드", accept_multiple_files=True, type=['xlsx', 'xls'], key="avail")
        
        if st.button("객실 세팅 업데이트"):
            if avail_files:
                try:
                    df_list = []
                    for file in avail_files:
                        df = pd.read_excel(file)
                        if not df.empty:
                            df.set_index(df.columns[0], inplace=True)
                            df = make_index_unique(df)
                            df_list.append(df)
                    
                    merged_avail = pd.concat(df_list, axis=1)
                    merged_avail = merged_avail.loc[:, ~merged_avail.columns.duplicated()]
                    merged_avail.columns = merged_avail.columns.astype(str)
                    merged_avail = merged_avail.fillna(0)
                    
                    db.collection("hotel_settings").document("latest_availability").set({
                        "data": merged_avail.to_dict(),
                        "updated_at": datetime.datetime.now()
                    })
                    st.success("✅ 객실 총 수량(Capacity) 설정 완료!")
                except Exception as e:
                    st.error(f"에러 발생: {e}")

# =========================================================
# [TAB 2] 대시보드 (여기가 핵심입니다!)
# =========================================================
with tab2:
    st.header("🏨 객실 현황 대시보드")
    
    # 1. 날짜 선택
    search_date = st.date_input("조회 기준일 (오늘)", datetime.date.today())
    search_date_str = search_date.strftime("%Y-%m-%d")
    yesterday_date = search_date - datetime.timedelta(days=1)
    yesterday_str = yesterday_date.strftime("%Y-%m-%d")

    # 2. 데이터 불러오기 (오늘, 어제, 캐파)
    if st.button("데이터 불러오기 및 계산"):
        with st.spinner("데이터를 계산 중입니다..."):
            try:
                # (A) 오늘 판매량 로드
                doc_today = db.collection("daily_room_snapshots").document(search_date_str).get()
                df_today = pd.DataFrame()
                if doc_today.exists:
                    df_today = pd.DataFrame.from_dict(doc_today.to_dict()['data'])
                
                # (B) 어제 판매량 로드 (변화량 계산용)
                doc_yesterday = db.collection("daily_room_snapshots").document(yesterday_str).get()
                df_yesterday = pd.DataFrame()
                if doc_yesterday.exists:
                    df_yesterday = pd.DataFrame.from_dict(doc_yesterday.to_dict()['data'])

                # (C) 총 객실 수(Capacity) 로드 (OCC 계산용)
                doc_capa = db.collection("hotel_settings").document("latest_availability").get()
                df_capacity = pd.DataFrame()
                if doc_capa.exists:
                    df_capacity = pd.DataFrame.from_dict(doc_capa.to_dict()['data'])

                # 데이터가 없으면 중단
                if df_today.empty:
                    st.error(f"❌ {search_date_str} (오늘) 데이터가 없습니다. 먼저 업로드해주세요.")
                else:
                    # 데이터 전처리: 계산을 위해 숫자로 변환 (문자열 제거)
                    df_today = df_today.apply(pd.to_numeric, errors='coerce').fillna(0)
                    
                    if not df_yesterday.empty:
                        df_yesterday = df_yesterday.apply(pd.to_numeric, errors='coerce').fillna(0)
                    
                    if not df_capacity.empty:
                        df_capacity = df_capacity.apply(pd.to_numeric, errors='coerce').fillna(0)

                    # ------------------------------------------------
                    # 1. 판매 수량 (Availability / Sales)
                    # ------------------------------------------------
                    st.subheader(f"1. 판매 객실 수 ({search_date_str})")
                    st.dataframe(df_today, height=300)

                    # ------------------------------------------------
                    # 2. OCC 자동 계산 (판매량 / 총객실수 * 100)
                    # ------------------------------------------------
                    st.subheader("2. 객실 점유율 (OCC %)")
                    
                    if df_capacity.empty:
                        st.warning("⚠️ '객실 총 수량(Capacity)' 데이터가 없어서 OCC를 계산할 수 없습니다. 업로드 탭에서 올려주세요.")
                    else:
                        # 인덱스(룸타입)와 컬럼(날짜)을 맞춰서 나누기
                        # 공통된 룸타입과 날짜만 남겨서 계산
                        common_index = df_today.index.intersection(df_capacity.index)
                        common_cols = df_today.columns.intersection(df_capacity.columns)
                        
                        # 계산 실행
                        df_occ = (df_today.loc[common_index, common_cols] / df_capacity.loc[common_index, common_cols] * 100).round(1)
                        df_occ = df_occ.fillna(0) # 0으로 나누거나 빈 값 처리

                        # 히트맵 스타일링 (빨강색)
                        st.dataframe(
                            df_occ.style.background_gradient(cmap='Reds', vmin=0, vmax=100).format("{:.1f}%"), 
                            height=300
                        )

                    # ------------------------------------------------
                    # 3. 변화량 계산 (오늘 - 어제)
                    # ------------------------------------------------
                    st.subheader(f"3. 전일 대비 변화량 (Pickup)")
                    st.caption(f"비교 대상: {yesterday_str} vs {search_date_str}")

                    if df_yesterday.empty:
                        st.warning(f"⚠️ {yesterday_str} (어제) 데이터가 없어서 변화량을 계산할 수 없습니다.")
                    else:
                        # 날짜 컬럼 맞추기 (오늘 데이터에는 있는데 어제는 없는 날짜가 있을 수 있음)
                        # sub 함수는 인덱스와 컬럼을 자동으로 맞춰서 빼줍니다.
                        df_pickup = df_today.sub(df_yesterday, fill_value=0)
                        
                        # 보기 좋게 0인 값은 흐리게 처리하거나 그대로 표시
                        # 색상: 양수는 파랑, 음수는 빨강
                        def color_pickup(val):
                            if val > 0: return 'color: blue; font-weight: bold'
                            elif val < 0: return 'color: red; font-weight: bold'
                            else: return 'color: lightgrey'

                        st.dataframe(
                            df_pickup.style.applymap(color_pickup).format("{:+.0f}"),
                            height=300
                        )

            except Exception as e:
                st.error(f"계산 중 오류 발생: {e}")
                st.write("힌트: 엑셀 파일의 룸타입 이름(행)과 날짜(열) 형식이 오늘과 어제 파일 간에 똑같은지 확인해보세요.")
