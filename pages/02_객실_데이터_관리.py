import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
import datetime

# 1. 페이지 기본 설정
st.set_page_config(page_title="객실 데이터 관리", layout="wide")
st.title("📅 객실 데이터 업로드 및 관리")

# 2. 파이어베이스 연결 (기존 설정 활용)
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
                # 파일 읽기 및 병합 로직
                df_list = []
                for file in snapshot_files:
                    # 엑셀을 읽을 때 첫 번째 컬럼(룸타입)을 인덱스로 설정
                    df = pd.read_excel(file, index_col=0)
                    df_list.append(df)
                
                # 옆으로 합치기 (날짜 컬럼이 늘어남)
                merged_df = pd.concat(df_list, axis=1)
                
                # 혹시 중복된 날짜 컬럼이 있으면 제거 (안전장치)
                merged_df = merged_df.loc[:, ~merged_df.columns.duplicated()]

                # 파이어베이스 저장 (문서 ID: 오늘 날짜)
                today_str = datetime.date.today().strftime("%Y-%m-%d")
                
                # 컬럼(날짜)이 문자열이어야 에러가 안 납니다.
                merged_df.columns = merged_df.columns.astype(str)
                
                doc_ref = db.collection("daily_room_snapshots").document(today_str)
                doc_ref.set({
                    "data": merged_df.to_dict(), 
                    "created_at": datetime.datetime.now()
                })
                
                st.success(f"✅ {today_str} 날짜로 스냅샷 저장 완료! (총 {len(merged_df.columns)}일치 데이터 병합됨)")
                st.write("▼ 저장된 데이터 미리보기")
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
    st.info("4개월치 가용 객실 파일 4개를 한꺼번에 선택해서 드래그하세요.")
    
    # [수정됨] 4개 파일 허용
    avail_files = st.file_uploader(
        "가용 객실 파일 4개 선택", 
        accept_multiple_files=True, 
        type=['xlsx', 'xls'], 
        key="avail_uploader"
    )
    
    if st.button("가용 객실 설정 업데이트"):
        if avail_files:
            try:
                # 파일 읽기 및 병합 로직
                df_list = []
                for file in avail_files:
                    df = pd.read_excel(file, index_col=0)
                    df_list.append(df)
                
                # 옆으로 합치기
                merged_avail_df = pd.concat(df_list, axis=1)
                
                # 중복 컬럼 제거
                merged_avail_df = merged_avail_df.loc[:, ~merged_avail_df.columns.duplicated()]
                
                # 컬럼 문자열 변환
                merged_avail_df.columns = merged_avail_df.columns.astype(str)
                
                # 파이어베이스 덮어쓰기 (문서 ID: latest_availability 고정)
                db.collection("hotel_settings").document("latest_availability").set({
                    "data": merged_avail_df.to_dict(),
                    "updated_at": datetime.datetime.now()
                })
                
                st.success(f"✅ 가용 객실 설정 업데이트 완료! (총 {len(merged_avail_df.columns)}일치 데이터 병합됨)")
                st.write("▼ 업데이트된 설정 데이터 미리보기")
                st.dataframe(merged_avail_df.head())
                
            except Exception as e:
                st.error(f"오류가 발생했습니다: {e}")
        else:
            st.warning("파일을 먼저 업로드해주세요.")

with tab2:
    st.write("### 🔍 데이터 저장 확인")
    st.write("파이어베이스에 데이터가 잘 들어갔는지 불러와서 확인해보세요.")
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("오늘자 스냅샷 불러오기"):
            today_str = datetime.date.today().strftime("%Y-%m-%d")
            doc = db.collection("daily_room_snapshots").document(today_str).get()
            if doc.exists:
                data = doc.to_dict()['data']
                df_check = pd.DataFrame.from_dict(data)
                st.success(f"📂 {today_str} 데이터 로드 성공!")
                st.dataframe(df_check.head())
            else:
                st.error(f"❌ {today_str} 날짜의 데이터가 없습니다.")

    with col2:
        if st.button("최신 가용 객실 설정 불러오기"):
            doc = db.collection("hotel_settings").document("latest_availability").get()
            if doc.exists:
                data = doc.to_dict()['data']
                df_avail_check = pd.DataFrame.from_dict(data)
                st.success("📂 최신 가용 객실 데이터 로드 성공!")
                st.dataframe(df_avail_check.head())
            else:
                st.error("❌ 설정된 가용 객실 데이터가 없습니다.")
