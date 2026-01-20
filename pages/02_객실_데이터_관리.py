import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
import datetime

# 1. 페이지 기본 설정
st.set_page_config(page_title="객실 데이터 관리", layout="wide")
st.title("📅 객실 데이터 업로드 및 관리")

# 2. 파이어베이스 연결
if not firebase_admin._apps:
    cred = credentials.Certificate(dict(st.secrets["firebase"]))
    firebase_admin.initialize_app(cred)
db = firestore.client()

# --- 중복된 행 이름(Index)을 강제로 살려내는 함수 ---
def make_index_unique(df):
    # 인덱스가 없는 경우(0, 1, 2...)는 처리 안 함
    if df.index.name is None and df.index.dtype == 'int64':
        return df
        
    new_index = []
    seen = {} # 등장한 이름 횟수 체크
    
    for idx in df.index:
        # 빈 값(NaN)은 'Unknown'으로 변경
        if pd.isna(idx) or str(idx).strip() == "":
            name = "Unknown"
        else:
            name = str(idx).strip()
            
        if name in seen:
            seen[name] += 1
            new_name = f"{name}_{seen[name]}" # 중복되면 이름_1, 이름_2 ...
        else:
            seen[name] = 0
            new_name = name
            
        new_index.append(new_name)
    
    df.index = new_index
    return df

# --- 탭 구성 ---
tab1, tab2 = st.tabs(["📤 데이터 업로드", "💾 저장된 데이터 확인"])

with tab1:
    # ==========================================
    # 1. 룸 스냅샷 (예약 현황) 업로드 섹션
    # ==========================================
    st.subheader("1. 룸 스냅샷 업로드 (예약 현황)")
    st.info("4개월치 엑셀 파일 4개를 한꺼번에 선택해서 드래그하세요. (모든 행 포함)")
    
    snapshot_files = st.file_uploader(
        "스냅샷 파일 4개 선택", 
        accept_multiple_files=True,
        type=['xlsx', 'xls'],
        key="snapshot_uploader"
    )

    if st.button("스냅샷 파이어베이스에 저장하기"):
        if snapshot_files:
            try:
                df_list = []
                for file in snapshot_files:
                    # 1. 엑셀 읽기 (헤더는 첫 줄로 가정)
                    df = pd.read_excel(file)
                    
                    # 2. 첫 번째 컬럼을 기준으로 삼음 (여기에 GDB, 합계 등이 있다고 가정)
                    # 데이터가 비어있지 않은 첫 번째 열을 찾아서 인덱스로 만듦
                    first_col_name = df.columns[0]
                    df.set_index(first_col_name, inplace=True)
                    
                    # 3. [핵심] 중복된 행 이름 강제 변경 (삭제하지 않음!)
                    df = make_index_unique(df)
                    
                    # 4. 쓸모없는 행(요일 등) 제거 로직은 뺍니다. 일단 다 가져옵니다.
                    # 다만, 데이터가 전부 비어있는 행 정도는 제거
                    df = df.dropna(how='all')
                    
                    df_list.append(df)
                
                # 5. 옆으로 합치기 (axis=1)
                # 이제 인덱스가 유니크해졌으므로 에러가 나지 않습니다.
                merged_df = pd.concat(df_list, axis=1)
                
                # 6. 날짜(컬럼) 중복 제거 (혹시 파일 간 겹치는 날짜가 있으면 하나만 유지)
                merged_df = merged_df.loc[:, ~merged_df.columns.duplicated()]

                # 7. 파이어베이스 저장 준비
                today_str = datetime.date.today().strftime("%Y-%m-%d")
                merged_df.columns = merged_df.columns.astype(str) # 컬럼 이름 문자열로
                merged_df = merged_df.fillna(0) # 빈칸 0으로 채우기
                
                # 저장
                doc_ref = db.collection("daily_room_snapshots").document(today_str)
                doc_ref.set({
                    "data": merged_df.to_dict(), 
                    "created_at": datetime.datetime.now()
                })
                
                st.success(f"✅ {today_str} 스냅샷 저장 완료! (총 {len(merged_df)}개 행 저장됨)")
                st.write("▼ 저장된 데이터 확인 (합계, 점유율 등 포함)")
                st.dataframe(merged_df) # head() 대신 전체 다 보여줌
                
            except Exception as e:
                st.error(f"오류가 발생했습니다: {e}")
                st.write("힌트: 엑셀 파일의 첫 번째 열이 '객실타입'이나 'GDB' 같은 이름이어야 합니다.")
        else:
            st.warning("파일을 먼저 업로드해주세요.")

    st.markdown("---")

    # ==========================================
    # 2. 사용가능 객실 (Availability) 업로드 섹션
    # ==========================================
    st.subheader("2. 사용가능 객실(Availability) 업로드")
    
    avail_files = st.file_uploader(
        "가용 객실 파일 4개 선택", 
        accept_multiple_files=True, 
        type=['xlsx', 'xls'], 
        key="avail_uploader"
    )
    
    if st.button("가용 객실 설정 업데이트"):
        if avail_files:
            try:
                df_list = []
                for file in avail_files:
                    df = pd.read_excel(file)
                    # 첫 번째 열 인덱스 설정
                    df.set_index(df.columns[0], inplace=True)
                    # 중복 인덱스 처리
                    df = make_index_unique(df)
                    df_list.append(df)
                
                merged_avail_df = pd.concat(df_list, axis=1)
                merged_avail_df = merged_avail_df.loc[:, ~merged_avail_df.columns.duplicated()]
                merged_avail_df.columns = merged_avail_df.columns.astype(str)
                merged_avail_df = merged_avail_df.fillna(0)
                
                db.collection("hotel_settings").document("latest_availability").set({
                    "data": merged_avail_df.to_dict(),
                    "updated_at": datetime.datetime.now()
                })
                
                st.success("✅ 가용 객실 설정 업데이트 완료!")
                st.dataframe(merged_avail_df)
                
            except Exception as e:
                st.error(f"오류가 발생했습니다: {e}")
        else:
            st.warning("파일을 먼저 업로드해주세요.")

with tab2:
    st.write("### 🔍 데이터 저장 확인")
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("오늘자 스냅샷 확인"):
            today_str = datetime.date.today().strftime("%Y-%m-%d")
            doc = db.collection("daily_room_snapshots").document(today_str).get()
            if doc.exists:
                st.success(f"Load Success: {today_str}")
                st.dataframe(pd.DataFrame.from_dict(doc.to_dict()['data']))
            else:
                st.warning("데이터 없음")

    with col2:
        if st.button("최신 가용 객실 확인"):
            doc = db.collection("hotel_settings").document("latest_availability").get()
            if doc.exists:
                st.success("Load Success")
                st.dataframe(pd.DataFrame.from_dict(doc.to_dict()['data']))
            else:
                st.warning("데이터 없음")
