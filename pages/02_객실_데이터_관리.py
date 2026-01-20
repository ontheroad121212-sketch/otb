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
st.title("🏨 객실 판매 현황 및 변동 분석")

if not firebase_admin._apps:
    cred = credentials.Certificate(dict(st.secrets["firebase"]))
    firebase_admin.initialize_app(cred)
db = firestore.client()

# --------------------------------------------------------------------------
# 2. 스마트 엑셀 로더 (헤더 자동 찾기 & 전처리)
# --------------------------------------------------------------------------
def process_uploaded_df(file):
    """
    엑셀을 읽을 때 날짜가 있는 '진짜 헤더' 줄을 찾아내고,
    요일 행을 삭제하며, 불필요한 룸타입을 걸러냅니다.
    """
    # 1. 일단 헤더 없이 읽어서 데이터 구조 파악
    df_raw = pd.read_excel(file, header=None)
    
    # 2. '진짜 헤더' 행 찾기 (날짜 형태의 데이터가 많은 행)
    # 엑셀 첫 줄이 비어있거나 제목이 있을 수 있으므로, 
    # '01-19' 처럼 날짜 패턴이 있거나 'GDB' 같은 룸타입이 있는 줄을 찾습니다.
    header_row_idx = 0
    for i, row in df_raw.head(10).iterrows():
        # 행을 문자열로 바꿔서 '-'나 '/'가 포함된 날짜 패턴이 있는지 검사
        row_str = row.astype(str).str.cat(sep=' ')
        if '-' in row_str or '/' in row_str or 'GDB' in row_str or '객실' in row_str:
            header_row_idx = i
            break
            
    # 3. 진짜 헤더를 적용해서 다시 읽기
    df = pd.read_excel(file, header=header_row_idx)
    
    # 4. 첫 번째 컬럼(룸타입)을 인덱스로 설정
    # (컬럼명이 'Unnamed'로 시작하면 첫번째 열이라고 가정)
    if df.columns[0].startswith('Unnamed') or '객실' in str(df.columns[0]):
        df.set_index(df.columns[0], inplace=True)
    else:
        # 혹시 모르니 첫번째 열을 인덱스로
        df.set_index(df.columns[0], inplace=True)
        
    # 5. [중요] '요일' 행(월, 화, 수...) 삭제
    rows_to_drop = []
    for idx in df.index[:10]: # 상위 10줄 검사
        # 인덱스나 행 값에 요일이 포함되어 있으면 삭제 대상
        row_values = df.loc[idx].astype(str).values.flatten()
        row_str = " ".join(row_values)
        if any(day in row_str for day in ['월', '화', '수', '목', '금', '토', '일', 'Mon', 'Tue']):
             rows_to_drop.append(idx)
        # '객실수' 같은 헤더성 데이터도 삭제
        if str(idx).strip() in ['객실수', 'Room Qty', 'nan', 'NaT']:
             rows_to_drop.append(idx)

    if rows_to_drop:
        df = df.drop(rows_to_drop)

    # 6. [필터링] 제외할 키워드 (Property, Amber 등)
    exclude_keywords = ['Property', 'Amber', 'Pure', 'Hill', '프로퍼티', '엠버', '퓨어', '힐', '합계', 'Total']
    # 합계는 나중에 계산할 수도 있으니 일단 뺄지 말지 결정해야 하는데, 
    # 사용자 요청에 따라 불필요한 룸타입만 제거
    
    mask = df.index.to_series().astype(str).apply(
        lambda x: any(k.lower() in x.lower() for k in exclude_keywords if k not in ['합계', 'Total'])
    )
    # '합계'는 살리고 싶으면 위 리스트에서 빼야 함. 일단 요청하신 Property 등만 제거.
    df = df[~mask]
    
    # 7. 빈 행 제거
    df = df.dropna(how='all')
    
    return df

def make_index_unique(df):
    """중복된 룸타입 이름(합계 등) 처리"""
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
    """여러 파일을 읽어 하나로 합치기"""
    if not files: return None
    df_list = []
    for f in files:
        df = process_uploaded_df(f)
        df = make_index_unique(df)
        df_list.append(df)
    
    merged = pd.concat(df_list, axis=1)
    # 날짜 중복 제거 (같은 날짜 컬럼이 여러 개면 하나만)
    merged = merged.loc[:, ~merged.columns.duplicated()]
    merged = merged.fillna(0)
    
    # 컬럼 이름(날짜) 정리: 시분초 제거하고 날짜만 남기기
    new_cols = []
    for col in merged.columns:
        s_col = str(col).replace(" 00:00:00", "") # 엑셀 날짜 포맷 정리
        new_cols.append(s_col)
    merged.columns = new_cols
    
    return merged

# --------------------------------------------------------------------------
# 3. UI 구성
# --------------------------------------------------------------------------
tab_upload, tab_dashboard = st.tabs(["📤 데이터 파일 업로드", "📊 분석 리포트 (VIEW)"])

# ==========================================================================
# [TAB 1] 데이터 업로드
# ==========================================================================
with tab_upload:
    col1, col2, col3 = st.columns(3)

    # 1. 오늘 데이터
    with col1:
        st.subheader("1. 오늘 스냅샷 (Today)")
        files_today = st.file_uploader("오늘 파일 4개", accept_multiple_files=True, key="today")
        if st.button("오늘 데이터 저장"):
            if files_today:
                try:
                    df = merge_files(files_today)
                    today_str = datetime.date.today().strftime("%Y-%m-%d")
                    db.collection("daily_room_snapshots").document(today_str).set({
                        "data": df.to_dict(), "created_at": datetime.datetime.now()
                    })
                    st.success(f"✅ {today_str} 저장 완료! (컬럼: {list(df.columns)[:3]}...)")
                except Exception as e:
                    st.error(f"저장 중 오류: {e}")

    # 2. 어제 데이터 (초기 세팅용)
    with col2:
        st.subheader("2. 어제 스냅샷 (Yesterday)")
        yest_date = st.date_input("어제 날짜 선택", datetime.date.today() - datetime.timedelta(days=1))
        yest_str = yest_date.strftime("%Y-%m-%d")
        files_yest = st.file_uploader("어제 파일 4개", accept_multiple_files=True, key="yest")
        if st.button(f"{yest_str} 데이터 저장"):
            if files_yest:
                try:
                    df = merge_files(files_yest)
                    db.collection("daily_room_snapshots").document(yest_str).set({
                        "data": df.to_dict(), "created_at": datetime.datetime.now()
                    })
                    st.success(f"✅ {yest_str} 저장 완료!")
                except Exception as e:
                    st.error(f"저장 중 오류: {e}")

    # 3. Capacity
    with col3:
        st.subheader("3. 판매 가능 객실 (Capacity)")
        files_capa = st.file_uploader("Capacity 파일 4개", accept_multiple_files=True, key="capa")
        if st.button("Capacity 업데이트"):
            if files_capa:
                try:
                    df = merge_files(files_capa)
                    db.collection("hotel_settings").document("latest_availability").set({
                        "data": df.to_dict(), "updated_at": datetime.datetime.now()
                    })
                    st.success("✅ Capacity 설정 완료!")
                except Exception as e:
                    st.error(f"저장 중 오류: {e}")

# ==========================================================================
# [TAB 2] 분석 리포트 (사용자 요청 완벽 반영!)
# ==========================================================================
with tab_dashboard:
    # 조회 컨트롤
    c1, c2 = st.columns([1, 5])
    with c1:
        search_date = st.date_input("조회 기준일", datetime.date.today())
        search_str = search_date.strftime("%Y-%m-%d")
        yest_str = (search_date - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        btn_load = st.button("🚀 리포트 생성", use_container_width=True)

    if btn_load:
        with st.spinner("데이터 분석 및 표 생성 중..."):
            # 1. 데이터 로드
            doc_today = db.collection("daily_room_snapshots").document(search_str).get()
            doc_yest = db.collection("daily_room_snapshots").document(yest_str).get()
            doc_capa = db.collection("hotel_settings").document("latest_availability").get()

            if not doc_today.exists or not doc_capa.exists:
                st.error("❌ 필수 데이터(오늘 스냅샷 또는 Capacity)가 없습니다. 업로드 탭을 확인하세요.")
            else:
                # 2. DataFrame 변환 & 숫자형 처리
                df_today = pd.DataFrame.from_dict(doc_today.to_dict()['data']).apply(pd.to_numeric, errors='coerce').fillna(0)
                df_capa = pd.DataFrame.from_dict(doc_capa.to_dict()['data']).apply(pd.to_numeric, errors='coerce').fillna(0)
                
                df_yest = pd.DataFrame()
                if doc_yest.exists:
                    df_yest = pd.DataFrame.from_dict(doc_yest.to_dict()['data']).apply(pd.to_numeric, errors='coerce').fillna(0)

                # 3. 공통 인덱스/컬럼 (날짜순 정렬)
                common_idx = df_today.index.intersection(df_capa.index)
                common_col = sorted(list(df_today.columns.intersection(df_capa.columns))) # 날짜순 정렬

                # 데이터 줄이기 (공통된 것만)
                df_today_clean = df_today.loc[common_idx, common_col]
                df_capa_clean = df_capa.loc[common_idx, common_col]

                # ------------------------------------------------------------------
                # [핵심] 날짜별로 [판매 | OCC] 병합 (Multi-Column) 만들기
                # ------------------------------------------------------------------
                # 1) OCC 계산
                df_occ_calc = df_today_clean.div(df_capa_clean).fillna(0) * 100

                # 2) 딕셔너리로 구조 잡기: {날짜: DataFrame(판매, OCC)}
                frames = {}
                for date in common_col:
                    # 해당 날짜의 판매량과 OCC를 묶음
                    frame = pd.DataFrame({
                        '판매 (Qty)': df_today_clean[date],
                        '점유율 (OCC)': df_occ_calc[date]
                    })
                    frames[date] = frame

                # 3) Pandas concat으로 병합 (Keys가 상위 헤더가 됨)
                df_combined = pd.concat(frames, axis=1)

                # ------------------------------------------------------------------
                # 화면 출력 (Section별)
                # ------------------------------------------------------------------

                # [상단] Capacity (펼치기 옵션)
                st.markdown("### 1️⃣ 판매 가능 객실 (Capacity)")
                with st.expander("🔻 Capacity 데이터 확인하기 (클릭)", expanded=False):
                    st.dataframe(df_capa_clean.style.format("{:.0f}"), use_container_width=True)

                st.divider()

                # [중단] 판매 현황 (Merged Header)
                st.markdown(f"### 2️⃣ {search_str} 판매 현황 (Merged View)")
                st.caption("날짜 아래에 판매량과 점유율이 함께 표시됩니다.")
                
                # 스타일링: OCC 컬럼만 % 표시 및 색상 적용
                # idx[:, (slice(None), '점유율 (OCC)')] -> 모든 행, 모든 날짜의 '점유율' 열 선택
                idx = pd.IndexSlice
                
                st.dataframe(
                    df_combined.style
                    .format("{:.0f}", subset=idx[:, (slice(None), '판매 (Qty)')])  # 판매량: 정수
                    .format("{:.1f}%", subset=idx[:, (slice(None), '점유율 (OCC)')]) # OCC: %
                    .background_gradient(cmap='Reds', vmin=0, vmax=100, subset=idx[:, (slice(None), '점유율 (OCC)')]), # OCC만 빨강 배경
                    use_container_width=True,
                    height=500
                )

                st.divider()

                # [하단] 변동 내역 (Pickup)
                st.markdown(f"### 3️⃣ 전일 대비 변동 (Pickup)")
                if df_yest.empty:
                    st.warning("어제 데이터가 없어 변동량을 계산할 수 없습니다.")
                else:
                    # 어제 데이터도 공통 컬럼만
                    common_col_yest = sorted(list(df_today.columns.intersection(df_yest.columns)))
                    df_pickup = df_today[common_col_yest].sub(df_yest[common_col_yest], fill_value=0)
                    
                    def color_pickup(val):
                        if val > 0: return 'color: blue; font-weight: bold; background-color: #f0f8ff'
                        elif val < 0: return 'color: red; font-weight: bold; background-color: #fff0f0'
                        else: return 'color: lightgrey'

                    st.dataframe(
                        df_pickup.style.applymap(color_pickup).format("{:+.0f}"),
                        use_container_width=True
                    )
