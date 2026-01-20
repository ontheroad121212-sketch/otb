import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
import json

# 페이지 기본 설정
st.set_page_config(layout="wide")
st.title("🏨 Daily Pace Report System")

# 1. Firebase 접속 (Secrets 활용)
# 주의: 이 코드는 파일이 아니라 Streamlit Secrets에서 키를 가져옵니다.
# 이렇게 바꿔주세요
if not firebase_admin._apps:
    # secrets에서 [firebase] 섹션을 바로 딕셔너리로 가져옵니다
    key_dict = dict(st.secrets["firebase"])
    cred = credentials.Certificate(key_dict)
    firebase_admin.initialize_app(cred)

st.success("✅ Firebase 연결 성공!")
db = firestore.client()

# 2. 테스트: 파일 업로더 보여주기
st.write("---")
st.subheader("데이터 업로드")
uploaded_files = st.file_uploader("월별 데이터를 업로드하세요", accept_multiple_files=True, type=['xlsx'])

if uploaded_files:
    st.write(f"{len(uploaded_files)}개의 파일이 업로드 되었습니다.")
