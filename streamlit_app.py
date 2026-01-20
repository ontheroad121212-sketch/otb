import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timedelta
import io

# ------------------------------------------------------------------
# 1. 기본 설정 및 Firebase 연결
# ------------------------------------------------------------------
st.set_page_config(layout="wide", page_title="Daily Pace Report")

# Firebase 연결 (Secrets 활용)
if not firebase_admin._apps:
    key_dict = dict(st.secrets["firebase"])
    cred = credentials.Certificate(key_dict)
    firebase_admin.initialize_app(cred)

db = firestore.client()

# ------------------------------------------------------------------
# 2. 예산(Budget) 설정 (나중에 DB에서 불러오게 고칠 수 있음)
# ------------------------------------------------------------------
# 예시값입니다. 실제 예산으로 수정하세요.
BUDGET_DATA = {
    1: 514992575,  # 1월 예산
    2: 480000000,  # 2월 예산
    3: 520000000,  # 3월 예산
    4: 600000000   # 4월 예산
}

# ------------------------------------------------------------------
# 3. 함수 정의 (엑셀 처리 & DB 통신)
# ------------------------------------------------------------------

def load_and_process_excel(file):
    """
    업로드된 RAW 엑셀(Image 2)을 읽어서 깔끔한 DF로 변환
    """
    # 헤더가 2줄(개인/단체 등)로 복잡하므로 적절히 처리
    # 실제 파일 구조에 따라 header=1 또는 2 조정 필요. 
    # 사진상으로는 2번째 줄(Index 1)부터가 진짜 헤더라고 가정
    try:
        df = pd.read_excel(file, header=1) 
        
        # 컬럼 이름 정리 (특수문자 제거 및 공백 정리)
        df.columns = [str(c).replace('\n', '').strip() for c in df.columns]
        
        # '일자' 컬럼 찾기 (첫번째 컬럼일 확률 높음)
        date_col = df.columns[0]
        
        # 합계 행 제거 (보통 맨 아래 '소계', '총합계' 등이 있음)
        df = df[pd.to_numeric(df[date_col], errors='coerce').notna()]
        
        # 날짜 형식 변환
        df['Date'] = pd.to_datetime(df[date_col])
        df['Month'] = df['Date'].dt.month
        
        # 필요한 컬럼만 추출 및 이름 변경 (RAW 데이터 구조에 맞게 매핑)
        # RAW 데이터 컬럼 위치를 기반으로 가져옵니다 (이름이 중복될 수 있어서 iloc 사용 권장)
        # 가정: 개인(FIT) 매출은 왼쪽에서 5번째쯤, 단체(Group) 매출은 중간, 합계는 오른쪽
        # *주의: 실제 엑셀 컬럼 위치 확인 후 인덱스 수정 필요*
        
        # 여기서는 편의상 컬럼명 검색으로 처리 시도
        # (실제 엑셀을 봐야 정확하지만, 일반적인 구조로 추정)
        # 전체 데이터 프레임 반환
        return df
        
    except Exception as e:
        st.error(f"엑셀 처리 중 오류 발생: {e}")
        return None

def get_yesterday_data(month_num):
    """
    DB에서 해당 월의 '가장 최근 저장된(어제)' 데이터를 가져옴
    """
    # 전략: DB 컬렉션 'daily_reports' -> 문서 'YYYY-MM' -> 필드 'last_updated_data'
    doc_ref = db.collection('daily_reports').document(f"2026-{month_num:02d}")
    doc = doc_ref.get()
    
    if doc.exists:
        data = doc.to_dict()
        # 저장된 JSON 데이터를 다시 DataFrame으로 변환
        return pd.read_json(io.StringIO(data['json_data']), orient='records')
    return None

def save_today_data(month_num, df):
    """
    오늘 데이터를 DB에 저장 (내일의 '어제 데이터'가 됨)
    """
    json_str = df.to_json(orient='records', date_format='iso')
    doc_ref = db.collection('daily_reports').document(f"2026-{month_num:02d}")
    doc_ref.set({
        'json_data': json_str,
        'updated_at': firestore.SERVER_TIMESTAMP
    })

# ------------------------------------------------------------------
# 4. 메인 UI 구성
# ------------------------------------------------------------------
st.title("🏨 One-Click Daily Pace Report")

# 파일 업로더
uploaded_files = st.file_uploader(
    "1월~4월 RAW 데이터 파일을 모두 드래그해서 넣으세요", 
    accept_multiple_files=True,
    type=['xlsx']
)

if uploaded_files:
    # 탭 생성
    tabs = st.tabs(["1월 (JAN)", "2월 (FEB)", "3월 (MAR)", "4월 (APR)"])
    
    # 파일을 월별로 분류
    month_files = {}
    for file in uploaded_files:
        # 파일명이나 내용을 미리 읽어서 월 구분 (여기서는 일단 파일 읽어서 확인)
        temp_df = pd.read_excel(file, header=1) 
        # 첫번째 날짜로 월 확인
        first_date = pd.to_datetime(temp_df.iloc[0, 0])
        month = first_date.month
        month_files[month] = file

    # 각 탭별로 리포트 생성 루프
    for i, tab in enumerate(tabs):
        current_month = i + 1
        with tab:
            if current_month in month_files:
                file = month_files[current_month]
                
                # 1. 데이터 로드 (RAW)
                # Streamlit의 file_uploader는 seek(0) 필요할 수 있음
                file.seek(0) 
                
                # RAW 데이터 읽기 (복잡한 헤더 처리)
                # *중요*: 사용자 엑셀 양식에 맞춰 iloc로 위치 지정
                raw_df = pd.read_excel(file, header=1)
                
                # 데이터 전처리 (필요한 컬럼 추출)
                # 가정: [일자, ..., 개인매출, ..., 단체매출, ..., 전체객실수, 전체점유율, 전체객단가, 전체매출]
                # 사용자 이미지 기준:
                # 합계 부분(맨 오른쪽) -> 객실수(-5), 점유율(-4), 객단가(-3), RevPAR(-2), 매출(-1) 이라고 가정
                
                try:
                    df_clean = pd.DataFrame()
                    df_clean['Date'] = pd.to_datetime(raw_df.iloc[:, 0]) # 날짜
                    df_clean = df_clean[df_clean['Date'].notna()] # 날짜 없는 행 제거

                    # 주요 데이터 추출 (엑셀 구조에 따라 숫자 조정 필수!)
                    # 이미지2 기준 '합계' 섹션의 데이터 가져오기
                    df_clean['RMS'] = raw_df.iloc[:, -5]  # 객실수 (맨 뒤에서 5번째)
                    df_clean['OCC'] = raw_df.iloc[:, -4]  # 점유율
                    df_clean['ADR'] = raw_df.iloc[:, -3]  # 객단가
                    df_clean['REV'] = raw_df.iloc[:, -1]  # 매출 (맨 뒤)
                    
                    # 요약용 FIT/GROUP 매출 (앞쪽 컬럼에서 찾아야 함)
                    # 대략 개인매출(4번째?), 단체매출(9번째?) -> 확인 필요. 임시로 추정값
                    # (정확히 하려면 컬럼명 검색 로직 추가 필요)
                    total_rev = df_clean['REV'].sum()
                    
                    # 2. Summary (Budget vs Actual) 계산
                    budget = BUDGET_DATA.get(current_month, 0)
                    achv_rate = (total_rev / budget * 100) if budget > 0 else 0
                    
                    st.markdown(f"""
                    ### 📊 {current_month}월 Summary
                    | 구분 | Budget | Actual | Vs Budget | 달성률 |
                    | :--- | :---: | :---: | :---: | :---: |
                    | **Total** | {budget:,.0f} | **{total_rev:,.0f}** | {total_rev-budget:,.0f} | **{achv_rate:.1f}%** |
                    """)
                    
                    st.divider()

                    # 3. 어제 데이터 불러오기 및 비교
                    df_prev = get_yesterday_data(current_month)
                    
                    if df_prev is not None:
                        # 날짜 문자열 통일
                        df_clean['DateStr'] = df_clean['Date'].dt.strftime('%Y-%m-%d')
                        df_prev['DateStr'] = pd.to_datetime(df_prev['Date']).dt.strftime('%Y-%m-%d')
                        
                        # 병합 (오늘 vs 어제)
                        merged = pd.merge(df_clean, df_prev[['DateStr', 'REV', 'RMS']], on='DateStr', how='left', suffixes=('', '_prev'))
                        
                        # 변화량(PickUp) 계산
                        merged['PickUp_REV'] = merged['REV'] - merged['REV_prev'].fillna(0)
                        merged['PickUp_RMS'] = merged['RMS'] - merged['RMS_prev'].fillna(0)
                        
                        # 표시할 데이터프레임 정리
                        display_df = merged[['DateStr', 'RMS', 'RMS_prev', 'PickUp_RMS', 'REV', 'REV_prev', 'PickUp_REV']].copy()
                        display_df.columns = ['날짜', '객실(Today)', '객실(Yst)', '객실(Var)', '매출(Today)', '매출(Yst)', '매출(Var)']
                        
                        st.dataframe(display_df, use_container_width=True, height=500)
                        
                    else:
                        st.info("비교할 과거 데이터가 없습니다. (오늘이 첫 저장입니다)")
                        st.dataframe(df_clean, use_container_width=True)

                    # 4. 저장 버튼
                    if st.button(f"{current_month}월 데이터 DB 저장 (확정)", key=f"save_{current_month}"):
                        save_today_data(current_month, df_clean)
                        st.success(f"{current_month}월 데이터가 저장되었습니다! 내일 비교 데이터로 사용됩니다.")
                        
                except Exception as e:
                    st.error(f"데이터 파싱 에러: {e}. 엑셀 컬럼 위치를 확인해주세요.")

            else:
                st.write(f"{current_month}월 데이터 파일이 업로드되지 않았습니다.")

else:
    st.info("👆 위 영역에 엑셀 파일을 업로드해주세요.")
