import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
import datetime

# --------------------------------------------------------------------------
# 1. 기본 설정 및 DB 연결
# --------------------------------------------------------------------------
st.set_page_config(page_title="객실 현황 대시보드", layout="wide")
st.title("🏨 객실 판매 현황 및 변동 분석")

if not firebase_admin._apps:
    cred = credentials.Certificate(dict(st.secrets["firebase"]))
    firebase_admin.initialize_app(cred)
db = firestore.client()

# --------------------------------------------------------------------------
# 2. 핵심 로직 함수 (전처리, 인덱스 정리)
# --------------------------------------------------------------------------
def process_uploaded_df(file):
    """
    엑셀 파일을 읽어서 요일 행 삭제, 불필요한 룸타입 제거 등 전처리를 수행합니다.
    """
    # 1. 엑셀 읽기 (첫 줄을 헤더로)
    df = pd.read_excel(file, header=0)
    
    # 2. 첫 번째 컬럼(룸타입)을 인덱스로 설정
    # (보통 첫 컬럼이 비어있거나 '객실'이라고 되어 있음)
    df.set_index(df.columns[0], inplace=True)
    
    # 3. [중요] '요일' 행(월, 화, 수...) 제거 로직
    # 데이터 첫 3줄 안에 '월'이나 'Mon' 같은 글자가 있으면 그 줄은 데이터가 아니므로 삭제
    rows_to_drop = []
    for idx in df.index[:5]:
        # 인덱스 이름이나 해당 행의 값들을 문자열로 합쳐서 검사
        row_values = df.loc[idx].astype(str).values.flatten()
        row_str = " ".join(row_values)
        
        if any(day in row_str for day in ['월', '화', '수', '목', '금', '토', '일', 'Mon', 'Tue']):
             rows_to_drop.append(idx)
        
        # 인덱스 이름 자체가 '객실수' 등으로 되어 있는 헤더성 행도 제거
        if str(idx) in ['객실수', 'Room Qty']:
            rows_to_drop.append(idx)

    if rows_to_drop:
        df = df.drop(rows_to_drop)

    # 4. [필터링] 제외할 키워드 (Property, Amber 등)
    exclude_keywords = ['Property', 'Amber', 'Pure', 'Hill', '프로퍼티', '엠버', '퓨어', '힐']
    mask = df.index.to_series().astype(str).apply(
        lambda x: any(k.lower() in x.lower() for k in exclude_keywords)
    )
    df = df[~mask]
    
    # 5. 빈 행 제거 (모든 값이 NaN인 경우)
    df = df.dropna(how='all')
    
    return df

def make_index_unique(df):
    """
    인덱스(룸타입) 이름이 같을 경우(예: 합계가 2개) 뒤에 숫자를 붙여 살려냅니다.
    """
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
    """여러 파일을 읽어 하나로 합치고 정리하는 함수"""
    if not files: return None
    df_list = []
    for f in files:
        df = process_uploaded_df(f)
        df = make_index_unique(df)
        df_list.append(df)
    
    # 옆으로 합치기
    merged = pd.concat(df_list, axis=1)
    # 날짜 중복 제거
    merged = merged.loc[:, ~merged.columns.duplicated()]
    # 결측치 0 처리 및 컬럼 문자열 변환
    merged = merged.fillna(0)
    merged.columns = merged.columns.astype(str)
    return merged

# --------------------------------------------------------------------------
# 3. UI 구성 (탭 2개: 업로드 / 대시보드)
# --------------------------------------------------------------------------
tab_upload, tab_dashboard = st.tabs(["📤 데이터 파일 업로드", "📊 분석 리포트 (VIEW)"])

# ==========================================================================
# [TAB 1] 데이터 업로드 (어제 / 오늘 / Capacity)
# ==========================================================================
with tab_upload:
    col_today, col_yest, col_capa = st.columns(3)

    # 1. 오늘 데이터 (Today)
    with col_today:
        st.subheader("1. 오늘 스냅샷 (Today)")
        files_today = st.file_uploader("오늘 파일 4개", accept_multiple_files=True, key="today")
        if st.button("오늘 데이터 저장"):
            if files_today:
                df = merge_files(files_today)
                today_str = datetime.date.today().strftime("%Y-%m-%d")
                db.collection("daily_room_snapshots").document(today_str).set({
                    "data": df.to_dict(), "created_at": datetime.datetime.now()
                })
                st.success(f"✅ {today_str} 저장 완료!")

    # 2. 어제 데이터 (Yesterday) - 초기 세팅용
    with col_yest:
        st.subheader("2. 어제 스냅샷 (Yesterday)")
        yest_date = st.date_input("어제 날짜 선택", datetime.date.today() - datetime.timedelta(days=1))
        yest_str = yest_date.strftime("%Y-%m-%d")
        files_yest = st.file_uploader("어제 파일 4개", accept_multiple_files=True, key="yest")
        if st.button(f"어제({yest_str}) 데이터 저장"):
            if files_yest:
                df = merge_files(files_yest)
                db.collection("daily_room_snapshots").document(yest_str).set({
                    "data": df.to_dict(), "created_at": datetime.datetime.now()
                })
                st.success(f"✅ {yest_str} 저장 완료!")

    # 3. Capacity (Availability)
    with col_capa:
        st.subheader("3. 판매 가능 객실 (Capacity)")
        files_capa = st.file_uploader("Capacity 파일 4개", accept_multiple_files=True, key="capa")
        if st.button("Capacity 업데이트"):
            if files_capa:
                df = merge_files(files_capa)
                db.collection("hotel_settings").document("latest_availability").set({
                    "data": df.to_dict(), "updated_at": datetime.datetime.now()
                })
                st.success("✅ Capacity 설정 완료!")

# ==========================================================================
# [TAB 2] 분석 리포트 (사용자님이 원하는 그 로직!)
# ==========================================================================
with tab_dashboard:
    # 조회 컨트롤
    c1, c2 = st.columns([1, 4])
    with c1:
        search_date = st.date_input("조회 기준일", datetime.date.today())
        search_str = search_date.strftime("%Y-%m-%d")
        yest_str = (search_date - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        
        btn_load = st.button("🚀 리포트 생성", use_container_width=True)

    if btn_load:
        with st.spinner("데이터를 분석하고 있습니다..."):
            # 1. DB에서 데이터 가져오기
            doc_today = db.collection("daily_room_snapshots").document(search_str).get()
            doc_yest = db.collection("daily_room_snapshots").document(yest_str).get()
            doc_capa = db.collection("hotel_settings").document("latest_availability").get()

            # 데이터 존재 여부 확인
            if not doc_today.exists:
                st.error(f"❌ {search_str} (오늘) 데이터가 없습니다. 업로드 탭에서 올려주세요.")
            elif not doc_capa.exists:
                st.error("❌ Capacity(판매가능객실) 데이터가 없습니다. 업로드 탭에서 올려주세요.")
            else:
                # DataFrame 변환
                df_today = pd.DataFrame.from_dict(doc_today.to_dict()['data']).apply(pd.to_numeric, errors='coerce').fillna(0)
                df_capa = pd.DataFrame.from_dict(doc_capa.to_dict()['data']).apply(pd.to_numeric, errors='coerce').fillna(0)
                
                df_yest = pd.DataFrame()
                if doc_yest.exists:
                    df_yest = pd.DataFrame.from_dict(doc_yest.to_dict()['data']).apply(pd.to_numeric, errors='coerce').fillna(0)

                # 공통 인덱스/컬럼 추출 (계산을 위해 교집합 사용)
                common_idx = df_today.index.intersection(df_capa.index)
                common_col = df_today.columns.intersection(df_capa.columns)

                # ----------------------------------------------------------
                # SECTION 1: 상단 - 판매 가능 객실 (Reference)
                # ----------------------------------------------------------
                st.markdown("### 1️⃣ 판매 가능 객실 (Total Capacity)")
                st.info("💡 참고용 데이터입니다. (전체 객실 수)")
                with st.expander("펼쳐보기 / 접기", expanded=False):
                    st.dataframe(df_capa.style.format("{:.0f}"), use_container_width=True)

                st.divider()

                # ----------------------------------------------------------
                # SECTION 2: 중단 - 판매 현황 & OCC (Status)
                # ----------------------------------------------------------
                st.markdown(f"### 2️⃣ {search_str} 판매 현황 (Sales & OCC)")
                
                # (A) 판매 수량 (Sales Quantity)
                st.markdown("**A. 판매 객실 수 (Room Sold)**")
                st.dataframe(df_today.style.format("{:.0f}"), use_container_width=True)

                # (B) 점유율 (OCC %) - 계산 로직: Today / Capacity
                st.markdown("**B. 객실 점유율 (Occupancy %)**")
                
                # 계산: 0으로 나누기 방지
                df_occ = df_today.loc[common_idx, common_col].div(df_capa.loc[common_idx, common_col]).fillna(0) * 100
                
                # 히트맵 스타일링 (빨강색)
                st.dataframe(
                    df_occ.style.background_gradient(cmap='Reds', vmin=0, vmax=100).format("{:.1f}%"),
                    use_container_width=True
                )

                st.divider()

                # ----------------------------------------------------------
                # SECTION 3: 하단 - 변동 내역 (Changes)
                # ----------------------------------------------------------
                st.markdown(f"### 3️⃣ 전일 대비 변동 (Pickup)")
                st.caption(f"비교: {search_str} (오늘) - {yest_str} (어제)")
                
                if df_yest.empty:
                    st.warning(f"⚠️ {yest_str} 데이터가 없어서 변동량을 계산할 수 없습니다. 어제 데이터를 업로드해주세요.")
                else:
                    # 계산 로직: Today - Yesterday (날짜 매칭)
                    df_pickup = df_today.sub(df_yest, fill_value=0)
                    
                    # 스타일: 양수(파랑), 음수(빨강), 0(회색)
                    def color_pickup(val):
                        if val > 0: return 'color: blue; font-weight: bold; background-color: #e6f3ff'
                        elif val < 0: return 'color: red; font-weight: bold; background-color: #ffe6e6'
                        else: return 'color: lightgrey'

                    st.dataframe(
                        df_pickup.style.applymap(color_pickup).format("{:+.0f}"),
                        use_container_width=True
                    )
