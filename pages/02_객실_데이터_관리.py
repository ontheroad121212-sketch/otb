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

# --- 탭 구성 ---
tab1, tab2 = st.tabs(["📤 데이터 업로드", "💾 저장된 데이터 확인"])

with tab1:
    # ==========================================
    # 1. 룸 스냅샷 (예약 현황) 업로드 섹션
    # ==========================================
    st.subheader("1. 룸 스냅샷 업로드 (예약 현황)")
    st.info("4개월치 엑셀 파일 4개를 한꺼번에 선택해서 드래그하세요.")
    
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
                    # 1. 일단 인덱스 지정 없이 읽어옵니다.
                    df = pd.read_excel(file)
                    
                    # 2. 첫 번째 컬럼(룸타입)을 기준으로 중복 제거
                    # (예: 'Total'이 여러 개 있거나 빈 줄이 있으면 제거)
                    first_col = df.columns[0]
                    df = df.drop_duplicates(subset=[first_col], keep='first')
                    
                    # 3. 빈 값(NaN)이 있는 행 제거 (빈 줄 방지)
                    df = df.dropna(subset=[first_col])

                    # 4. 이제 첫 번째 컬럼을 인덱스로 설정
                    df.set_index(first_col, inplace=True)
                    
                    df_list.append(df)
                
                # 옆으로 합치기 (axis=1)
                # join='outer'는 혹시 룸타입 순서가 달라도 알아서 맞춰줍니다.
                merged_df = pd.concat(df_list, axis=1, join='outer')
                
                # 날짜(컬럼) 중복 제거
                merged_df = merged_df.loc[:, ~merged_df.columns.duplicated()]

                # 파이어베이스 저장
                today_str = datetime.date.today().strftime("%Y-%m-%d")
                merged_df.columns = merged_df.columns.astype(str)
                
                # NaN(빈값)은 0으로 채우기 (데이터 안정성 확보)
                merged_df = merged_df.fillna(0)
                
                doc_ref = db.collection("daily_room_snapshots").document(today_str)
                doc_ref.set({
                    "data": merged_df.to_dict(), 
                    "created_at": datetime.datetime.now()
                })
                
                st.success(f"✅ {today_str} 스냅샷 저장 완료! (중복/빈행 자동 제거됨)")
                st.dataframe(merged_df.head())
                
            except Exception as e:
                st.error(f"오류가 발생했습니다: {e}")
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
                    # 여기도 동일하게 중복 방지 로직 적용
                    df = pd.read_excel(file)
                    first_col = df.columns[0]
                    df = df.drop_duplicates(subset=[first_col], keep='first')
                    df = df.dropna(subset=[first_col])
                    df.set_index(first_col, inplace=True)
                    df_list.append(df)
                
                merged_avail_df = pd.concat(df_list, axis=1, join='outer')
                merged_avail_df = merged_avail_df.loc[:, ~merged_avail_df.columns.duplicated()]
                merged_avail_df.columns = merged_avail_df.columns.astype(str)
                merged_avail_df = merged_avail_df.fillna(0)
                
                db.collection("hotel_settings").document("latest_availability").set({
                    "data": merged_avail_df.to_dict(),
                    "updated_at": datetime.datetime.now()
                })
                
                st.success("✅ 가용 객실 설정 업데이트 완료!")
                st.dataframe(merged_avail_df.head())
                
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
                st.dataframe(pd.DataFrame.from_dict(doc.to_dict()['data']).head())
            else:
                st.warning("데이터 없음")

    with col2:
        if st.button("최신 가용 객실 확인"):
            doc = db.collection("hotel_settings").document("latest_availability").get()
            if doc.exists:
                st.success("Load Success")
                st.dataframe(pd.DataFrame.from_dict(doc.to_dict()['data']).head())
            else:
                st.warning("데이터 없음")
