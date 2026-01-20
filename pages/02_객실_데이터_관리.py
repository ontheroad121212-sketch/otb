import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
import datetime

# 1. 페이지 기본 설정
st.set_page_config(page_title="객실 데이터 관리", layout="wide")
st.title("📅 객실 데이터 업로드 및 관리")

# 2. 파이어베이스 연결 (기존 설정 활용)
# 이미 메인 앱에서 초기화되었을 수 있으므로 확인 후 연결합니다.
if not firebase_admin._apps:
    cred = credentials.Certificate(dict(st.secrets["firebase"]))
    firebase_admin.initialize_app(cred)
db = firestore.client()

# --- 탭 구성 ---
tab1, tab2 = st.tabs(["📤 데이터 업로드", "💾 저장된 데이터 확인"])

with tab1:
    st.subheader("1. 룸 스냅샷 업로드 (예약 현황)")
    st.info("4개월치 엑셀 파일 4개를 한꺼번에 선택해서 드래그하세요.")
    
    snapshot_files = st.file_uploader(
        "스냅샷 파일 4개 선택", 
        accept_multiple_files=True,
        type=['xlsx', 'xls']
    )

    if st.button("스냅샷 파이어베이스에 저장하기"):
        if snapshot_files:
            try:
                # 파일 읽기 및 병합 로직
                df_list = []
                for file in snapshot_files:
                    # 엑셀을 읽을 때 첫 번째 컬럼(룸타입)을 인덱스로 설정해야 합치기 좋습니다.
                    # index_col=0은 A열(룸타입)을 기준열로 잡겠다는 뜻입니다.
                    df = pd.read_excel(file, index_col=0)
                    df_list.append(df)
                
                # 옆으로 합치기 (날짜 컬럼이 늘어남)
                merged_df = pd.concat(df_list, axis=1)
                
                # 혹시 중복된 날짜 컬럼이 있으면 제거 (선택사항)
                merged_df = merged_df.loc[:, ~merged_df.columns.duplicated()]

                # 파이어베이스 저장
                today_str = datetime.date.today().strftime("%Y-%m-%d")
                
                # 데이터프레임의 컬럼(날짜)이 문자열이어야 파이어베이스 오류가 안 납니다.
                merged_df.columns = merged_df.columns.astype(str)
                
                doc_ref = db.collection("daily_room_snapshots").document(today_str)
                doc_ref.set({
                    "data": merged_df.to_dict(), # 딕셔너리로 변환하여 저장
                    "created_at": datetime.datetime.now()
                })
                
                st.success(f"✅ {today_str} 날짜로 스냅샷 저장 완료! (총 {len(merged_df.columns)}일치 데이터)")
                st.dataframe(merged_df.head()) # 데이터 미리보기
                
            except Exception as e:
                st.error(f"오류가 발생했습니다: {e}")
        else:
            st.warning("파일을 먼저 업로드해주세요.")

    st.markdown("---")

    st.subheader("2. 사용가능 객실(Availability) 업로드")
    st.info("월별/일별 가용 객실수 파일을 업로드하면 최신 설정으로 덮어씁니다.")
    
    avail_file = st.file_uploader("가용 객실 파일 1개 선택", type=['xlsx', 'xls'], key="avail")
    
    if st.button("가용 객실 설정 업데이트"):
        if avail_file:
            try:
                # 데이터 읽기
                df_avail = pd.read_excel(avail_file, index_col=0)
                df_avail.columns = df_avail.columns.astype(str) # 컬럼을 문자열로
                
                # 파이어베이스 덮어쓰기
                db.collection("hotel_settings").document("latest_availability").set({
                    "data": df_avail.to_dict(),
                    "updated_at": datetime.datetime.now()
                })
                
                st.success("✅ 가용 객실 설정(latest_availability) 업데이트 완료!")
                st.dataframe(df_avail.head())
                
            except Exception as e:
                st.error(f"오류가 발생했습니다: {e}")
        else:
            st.warning("파일을 먼저 업로드해주세요.")

with tab2:
    st.write("파이어베이스에 잘 저장되었는지 테스트하는 공간입니다.")
    if st.button("최신 데이터 불러오기 테스트"):
        today_str = datetime.date.today().strftime("%Y-%m-%d")
        
        # 스냅샷 불러오기
        doc = db.collection("daily_room_snapshots").document(today_str).get()
        if doc.exists:
            data = doc.to_dict()['data']
            df_check = pd.DataFrame.from_dict(data)
            st.write(f"📂 **{today_str} 스냅샷 데이터:**")
            st.dataframe(df_check.head())
        else:
            st.error(f"{today_str} 날짜의 데이터가 아직 없습니다.")
