import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timedelta
import plotly.graph_objects as go
import plotly.express as px
import io
import numpy as np
import textwrap
import math
import calendar

# ==============================================================================
# [1] 페이지 설정
# ==============================================================================
st.set_page_config(page_title="Summer 2026 Revenue Tracker", layout="wide")

st.markdown(textwrap.dedent("""
<style>
    .block-container { padding-top: 0.8rem; padding-bottom: 3rem; }
    .period-card {
        border-radius: 10px; padding: 14px 16px; margin-bottom: 6px;
        font-size: 13px; line-height: 1.7;
    }
    .metric-big { font-size: 26px; font-weight: 900; }
    .metric-label { font-size: 12px; color: #6b7280; font-weight: 700; text-transform: uppercase; }
    .alert-green { background: #f0fdf4; border: 1px solid #86efac; border-radius: 8px; padding: 8px 12px; }
    .alert-red   { background: #fef2f2; border: 1px solid #fca5a5; border-radius: 8px; padding: 8px 12px; }
    .alert-yellow { background: #fffbeb; border: 1px solid #fcd34d; border-radius: 8px; padding: 8px 12px; }
    div[data-testid="stMetricValue"] { font-size: 22px !important; font-weight: 900; }
</style>
"""), unsafe_allow_html=True)

# ==============================================================================
# [2] 구간 설정
# ==============================================================================
PERIODS = [
    {
        "id": "pre_peak",
        "label": "Pre-Peak",
        "desc": "7/1~7/18",
        "start": "2026-07-01",
        "end": "2026-07-18",
        "target_adr": 355_000,
        "new_bk_adr_lo": 355_000,
        "new_bk_adr_hi": 355_000,
        "target_occ": 0.85,
        "booking_buffer": 3,
        "wash_rate": 0.08,
        "color": "#64748b",
        "bg": "#f8fafc",
    },
    {
        "id": "shoulder1",
        "label": "Shoulder A",
        "desc": "7/19~7/23",
        "start": "2026-07-19",
        "end": "2026-07-23",
        "target_adr": 340_000,
        "new_bk_adr_lo": 340_000,
        "new_bk_adr_hi": 340_000,
        "target_occ": 0.90,
        "booking_buffer": 3,
        "wash_rate": 0.08,
        "color": "#d97706",
        "bg": "#fffbeb",
    },
    {
        "id": "peak",
        "label": "Peak",
        "desc": "7/24~8/8",
        "start": "2026-07-24",
        "end": "2026-08-08",
        "target_adr": 510_000,
        "new_bk_adr_lo": 510_000,
        "new_bk_adr_hi": 530_000,
        "target_occ": 0.97,
        "booking_buffer": 5,
        "wash_rate": 0.12,
        "color": "#dc2626",
        "bg": "#fef2f2",
    },
    {
        "id": "post_peak",
        "label": "Post-Peak",
        "desc": "8/9~8/16",
        "start": "2026-08-09",
        "end": "2026-08-16",
        "target_adr": 470_000,
        "new_bk_adr_lo": 470_000,
        "new_bk_adr_hi": 470_000,
        "target_occ": 0.96,
        "booking_buffer": 3,
        "wash_rate": 0.10,
        "color": "#ea580c",
        "bg": "#fff7ed",
    },
    {
        "id": "shoulder2",
        "label": "Shoulder B",
        "desc": "8/17~8/31",
        "start": "2026-08-17",
        "end": "2026-08-31",
        "target_adr": 310_000,
        "new_bk_adr_lo": 310_000,
        "new_bk_adr_hi": 310_000,
        "target_occ": 0.80,
        "booking_buffer": 3,
        "wash_rate": 0.08,
        "color": "#16a34a",
        "bg": "#f0fdf4",
    },
    {
        "id": "september",
        "label": "September",
        "desc": "9/1~9/30",
        "start": "2026-09-01",
        "end": "2026-09-30",
        "target_adr": 330_000,
        "new_bk_adr_lo": 330_000,
        "new_bk_adr_hi": 345_000,
        "target_occ": 0.83,
        "booking_buffer": 3,
        "wash_rate": 0.08,
        "color": "#0891b2",
        "bg": "#ecfeff",
    },
]

# 월별 공식 목표 (rn=객실박, rev=매출목표)
MONTH_TARGETS = {
    7: {"rn": 3_720, "rev": 1_231_949_142},
    8: {"rn": 3_873, "rev": 1_388_376_999},
    9: {"rn": 3_120, "rev": 952_171_506},   # 9월 추가 (RN은 추정)
}

# ── 3분기(7~9월) 통합목표 필달 계획 (보고서 승인안, 2026-07-22) ──────────────
Q3_TARGET_REV = 3_572_497_647            # 3분기 통합 매출목표
PLAN_LANDING = {                          # 월별 권장 착지 (역할 재조정)
    7: 1_117_926_536,   # 잠금
    8: 1_310_585_855,   # 현실선 (하한 사수)
    9: 1_154_000_000,   # 승부처 (목표 +2.02억 초과)
}
AUG_FLOOR = 1_300_000_000                 # 8월 하한 사수선
AUG_OTB_CHECKPOINTS = [                    # 8월 누적 OTB 관리선 (단조 증가)
    ("2026-07-31",   960_000_000),
    ("2026-08-07", 1_060_000_000),
    ("2026-08-14", 1_140_000_000),
    ("2026-08-21", 1_215_000_000),
    ("2026-08-28", 1_280_000_000),
    ("2026-08-31", 1_311_000_000),
]
SEP_STRATEGY = {                          # 9월 승부처 관리 지표
    "adr_target": 330_000,
    "peak_dates": ["09-05", "09-10", "09-11", "09-17", "09-18", "09-19"],
    "peak_adr": 345_000,
    "indiv_sell_through": 0.92,
    "group_target_rev": 230_000_000,
    "group_current_rev": 192_569_161,
    "hardblock_confirmed_rn": 180,
}

DATE_PLAN = {  # 일자별 권장 착지(플랜): rn=권장객실, rev=권장매출, adr=ADR하한
    "2026-08-01": {"rn": 126, "rev": 50581499, "adr": 425000},
    "2026-08-02": {"rn": 124, "rev": 48516553, "adr": 425000},
    "2026-08-03": {"rn": 127, "rev": 52214615, "adr": 425000},
    "2026-08-04": {"rn": 123, "rev": 50464175, "adr": 390000},
    "2026-08-05": {"rn": 122, "rev": 47348661, "adr": 390000},
    "2026-08-06": {"rn": 118, "rev": 45084799, "adr": 390000},
    "2026-08-07": {"rn": 123, "rev": 50002179, "adr": 390000},
    "2026-08-08": {"rn": 123, "rev": 46395515, "adr": 390000},
    "2026-08-09": {"rn": 117, "rev": 42816682, "adr": 390000},
    "2026-08-10": {"rn": 118, "rev": 43583752, "adr": 390000},
    "2026-08-11": {"rn": 118, "rev": 43824735, "adr": 390000},
    "2026-08-12": {"rn": 120, "rev": 44816255, "adr": 390000},
    "2026-08-13": {"rn": 120, "rev": 44520019, "adr": 390000},
    "2026-08-14": {"rn": 121, "rev": 46714343, "adr": 390000},
    "2026-08-15": {"rn": 126, "rev": 48288650, "adr": 425000},
    "2026-08-16": {"rn": 124, "rev": 45757118, "adr": 425000},
    "2026-08-17": {"rn": 115, "rev": 37321965, "adr": 350000},
    "2026-08-18": {"rn": 113, "rev": 37152438, "adr": 350000},
    "2026-08-19": {"rn": 113, "rev": 36410208, "adr": 350000},
    "2026-08-20": {"rn": 113, "rev": 36152350, "adr": 350000},
    "2026-08-21": {"rn": 110, "rev": 36666619, "adr": 350000},
    "2026-08-22": {"rn": 128, "rev": 45378974, "adr": 425000},
    "2026-08-23": {"rn": 111, "rev": 36166415, "adr": 355000},
    "2026-08-24": {"rn": 111, "rev": 36345670, "adr": 355000},
    "2026-08-25": {"rn": 111, "rev": 35558142, "adr": 355000},
    "2026-08-26": {"rn": 111, "rev": 35937552, "adr": 355000},
    "2026-08-27": {"rn": 85, "rev": 27945658, "adr": 355000},
    "2026-08-28": {"rn": 111, "rev": 38297767, "adr": 355000},
    "2026-08-29": {"rn": 127, "rev": 45140792, "adr": 425000},
    "2026-08-30": {"rn": 117, "rev": 38525146, "adr": 355000},
    "2026-08-31": {"rn": 114, "rev": 36656609, "adr": 355000},
    "2026-09-01": {"rn": 120, "rev": 36683073, "adr": 330000},
    "2026-09-02": {"rn": 117, "rev": 37331517, "adr": 330000},
    "2026-09-03": {"rn": 122, "rev": 37219761, "adr": 330000},
    "2026-09-04": {"rn": 121, "rev": 37872924, "adr": 330000},
    "2026-09-05": {"rn": 128, "rev": 40890657, "adr": 345000},
    "2026-09-06": {"rn": 121, "rev": 35660089, "adr": 330000},
    "2026-09-07": {"rn": 119, "rev": 36972200, "adr": 330000},
    "2026-09-08": {"rn": 118, "rev": 37180039, "adr": 330000},
    "2026-09-09": {"rn": 118, "rev": 37849389, "adr": 330000},
    "2026-09-10": {"rn": 128, "rev": 40142665, "adr": 345000},
    "2026-09-11": {"rn": 128, "rev": 40465469, "adr": 345000},
    "2026-09-12": {"rn": 120, "rev": 39136511, "adr": 330000},
    "2026-09-13": {"rn": 118, "rev": 36344300, "adr": 330000},
    "2026-09-14": {"rn": 118, "rev": 37478968, "adr": 330000},
    "2026-09-15": {"rn": 117, "rev": 37245032, "adr": 330000},
    "2026-09-16": {"rn": 118, "rev": 37081328, "adr": 330000},
    "2026-09-17": {"rn": 37, "rev": 9030189, "adr": 345000},
    "2026-09-18": {"rn": 42, "rev": 11755101, "adr": 345000},
    "2026-09-19": {"rn": 127, "rev": 43750243, "adr": 345000},
    "2026-09-20": {"rn": 118, "rev": 36738608, "adr": 330000},
    "2026-09-21": {"rn": 119, "rev": 37263165, "adr": 330000},
    "2026-09-22": {"rn": 119, "rev": 37677771, "adr": 330000},
    "2026-09-23": {"rn": 119, "rev": 38727630, "adr": 330000},
    "2026-09-24": {"rn": 121, "rev": 44022976, "adr": 330000},
    "2026-09-25": {"rn": 119, "rev": 43593588, "adr": 330000},
    "2026-09-26": {"rn": 119, "rev": 43004426, "adr": 330000},
    "2026-09-27": {"rn": 115, "rev": 38413786, "adr": 330000},
    "2026-09-28": {"rn": 116, "rev": 38572923, "adr": 330000},
    "2026-09-29": {"rn": 117, "rev": 36406781, "adr": 330000},
    "2026-09-30": {"rn": 115, "rev": 35529494, "adr": 330000},
}

TOTAL_ROOMS = 129

# ==============================================================================
# [3] Firebase 연결
# ==============================================================================
if not firebase_admin._apps:
    try:
        key_dict = dict(st.secrets["firebase"])
        cred = credentials.Certificate(key_dict)
        firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"Firebase 연결 실패: {e}")
        st.stop()

db = firestore.client()


# ==============================================================================
# [4] 데이터 로드 함수
# ==============================================================================

@st.cache_data(ttl=60)
def get_snapshot_dates_for_month(month_num: int) -> list:
    try:
        db_local = firestore.client()
        docs = db_local.collection_group("months").stream()
        dates = []
        for doc in docs:
            if doc.id == str(month_num):
                dates.append(doc.reference.parent.parent.id)
        return sorted(dates)
    except Exception:
        return []


@st.cache_data(ttl=60)
def get_all_snapshot_dates() -> list:
    d7 = set(get_snapshot_dates_for_month(7))
    d8 = set(get_snapshot_dates_for_month(8))
    d9 = set(get_snapshot_dates_for_month(9))
    return sorted(d7 | d8 | d9, reverse=True)


@st.cache_data(ttl=60)
def load_reservation_pickups(snapshot_date: str) -> pd.DataFrame:
    try:
        db_local = firestore.client()
        doc_id = f"{snapshot_date}_Reservation"
        doc = db_local.collection("revenue_integrity_history").document(doc_id).get()
        if doc.exists:
            data = doc.to_dict().get("data", [])
            if data:
                df = pd.DataFrame(data)
                if "CheckIn" in df.columns:
                    df["CheckIn"] = pd.to_datetime(df["CheckIn"], errors="coerce")
                for col in ["Room_Revenue", "Total_Revenue", "RN", "Rooms", "Nights", "F_B_Revenue"]:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
                if "RN" not in df.columns and "Rooms" in df.columns and "Nights" in df.columns:
                    df["RN"] = df["Rooms"] * df["Nights"]
                if "Room_Revenue" in df.columns:
                    df = df[df["Room_Revenue"] > 0].copy()
                return df
    except Exception as e:
        st.session_state["_res_pickup_err"] = str(e)
    return pd.DataFrame()


@st.cache_data(ttl=300)
def load_cancellation_pickups(snapshot_date: str) -> pd.DataFrame:
    try:
        db_local = firestore.client()
        doc_id = f"{snapshot_date}_Cancellation"
        doc = db_local.collection("revenue_integrity_history").document(doc_id).get()
        if doc.exists:
            data = doc.to_dict().get("data", [])
            if data:
                df = pd.DataFrame(data)
                if "CheckIn" in df.columns:
                    df["CheckIn"] = pd.to_datetime(df["CheckIn"], errors="coerce")
                for col in ["Room_Revenue", "Total_Revenue", "RN", "Rooms", "Nights", "F_B_Revenue"]:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
                if "RN" not in df.columns and "Rooms" in df.columns and "Nights" in df.columns:
                    df["RN"] = df["Rooms"] * df["Nights"]
                if "Room_Revenue" in df.columns:
                    df = df[df["Room_Revenue"] > 0].copy()
                return df
    except Exception as e:
        st.session_state["_cancel_pickup_err"] = str(e)
    return pd.DataFrame()


def calc_res_period_stats(res_df: pd.DataFrame, cancel_df: pd.DataFrame = None) -> dict:
    stats = {}
    for p in PERIODS:
        if res_df.empty or "CheckIn" not in res_df.columns:
            stats[p["id"]] = None
            continue
        mask = (
            (res_df["CheckIn"] >= pd.Timestamp(p["start"]))
            & (res_df["CheckIn"] <= pd.Timestamp(p["end"]))
        )
        sub = res_df[mask]
        rn_sum = sub["RN"].sum() if not sub.empty else 0

        # 취소 RN 계산
        cancel_rn = 0
        if cancel_df is not None and not cancel_df.empty and "CheckIn" in cancel_df.columns:
            c_mask = (
                (cancel_df["CheckIn"] >= pd.Timestamp(p["start"]))
                & (cancel_df["CheckIn"] <= pd.Timestamp(p["end"]))
            )
            c_sub = cancel_df[c_mask]
            cancel_rn = int(c_sub["RN"].sum()) if not c_sub.empty else 0

        if sub.empty or rn_sum == 0:
            # 취소만 있는 경우에도 None 반환하지 않고 cancel 정보 포함
            if cancel_rn > 0:
                stats[p["id"]] = {
                    "rn": 0,
                    "room_rev": 0,
                    "total_rev": 0,
                    "room_adr": 0,
                    "total_adr": 0,
                    "count": 0,
                    "cancel_rn": cancel_rn,
                    "net_rn": -cancel_rn,
                }
            else:
                stats[p["id"]] = None
        else:
            room_rev = sub["Room_Revenue"].sum()
            total_rev = sub["Total_Revenue"].sum() if "Total_Revenue" in sub.columns else room_rev
            net_rn = int(rn_sum) - cancel_rn
            stats[p["id"]] = {
                "rn": int(rn_sum),
                "room_rev": room_rev,
                "total_rev": total_rev,
                "room_adr": room_rev / rn_sum,
                "total_adr": total_rev / rn_sum,
                "count": len(sub),
                "cancel_rn": cancel_rn,
                "net_rn": net_rn,
            }
    return stats


@st.cache_data(ttl=300)
def load_7day_pickups(curr_date_str: str) -> dict:
    base = datetime.strptime(curr_date_str, "%Y-%m-%d").date()
    period_daily = {p["id"]: [] for p in PERIODS}

    for i in range(1, 8):
        d = (base - timedelta(days=i)).strftime("%Y-%m-%d")
        r_df = load_reservation_pickups(d)
        c_df = load_cancellation_pickups(d)
        stats = calc_res_period_stats(r_df, c_df)
        for p in PERIODS:
            s = stats.get(p["id"])
            net = s["net_rn"] if s else 0
            period_daily[p["id"]].append(net)

    result = {}
    for pid, vals in period_daily.items():
        loaded = [v for v in vals if v > 0]
        result[pid] = {
            "avg_net_rn": sum(vals) / 7,
            "days_with_data": len(loaded),
        }
    return result


def load_snapshot(date_str: str, month_num: int) -> pd.DataFrame | None:
    try:
        doc = (
            db.collection("daily_snapshots")
            .document(date_str)
            .collection("months")
            .document(str(month_num))
            .get()
        )
        if doc.exists:
            d = doc.to_dict()
            df = pd.read_json(io.StringIO(d["json_data"]), orient="records")
            for c in ["FIT_RMS", "FIT_REV", "GRP_RMS", "GRP_REV", "RMS", "REV", "OCC", "ADR", "RevPAR", "HU", "Comp"]:
                if c not in df.columns:
                    df[c] = 0
            if "Date" not in df.columns and "DateStr" in df.columns:
                df["Date"] = pd.to_datetime(df["DateStr"])
            elif "Date" in df.columns:
                df["Date"] = pd.to_datetime(df["Date"])
            if "DateStr" not in df.columns and "Date" in df.columns:
                df["DateStr"] = df["Date"].dt.strftime("%Y-%m-%d")
            return df
    except Exception as e:
        st.session_state[f"_err_{date_str}_{month_num}"] = str(e)
    return None


def combine_months(df7, df8, df9=None) -> pd.DataFrame | None:
    parts = [df for df in [df7, df8, df9] if df is not None and not df.empty]
    if not parts:
        return None
    df = pd.concat(parts, ignore_index=True)
    if "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"])
    return df


# ==============================================================================
# [5] 사이드바 설정
# ==============================================================================
all_dates = get_all_snapshot_dates()

with st.sidebar:
    st.markdown("## 설정")

    if not all_dates:
        st.warning("저장된 스냅샷 없음. 메인 리포트에서 7·8월 데이터를 먼저 저장해 주세요.")
        st.stop()

    curr_date = st.selectbox("기준 스냅샷 (오늘)", all_dates, index=0)

    prev_options = [d for d in all_dates if d < curr_date]
    prev_date = (
        st.selectbox("비교 스냅샷 (전일/전주)", prev_options, index=0)
        if prev_options
        else None
    )
    if not prev_date:
        st.caption("비교할 이전 스냅샷이 없습니다.")

    st.divider()
    st.markdown("**구간별 ADR 목표**")
    for p in PERIODS:
        st.markdown(
            f"<span style='color:{p['color']};font-size:16px;'>■</span> "
            f"**{p['desc']}** {p['target_adr']:,}원",
            unsafe_allow_html=True,
        )

    st.divider()
    st.markdown("**ADR Scenario**")
    scenario_adj = st.slider(
        "신규 단가 조정 (%)", -20, 20, 0, step=5,
        help="신규 예약 목표 단가를 % 조정하여 예상 최종 ADR 재계산"
    )

    st.divider()
    if st.button("캐시 새로고침"):
        get_all_snapshot_dates.clear()
        get_snapshot_dates_for_month.clear()
        load_reservation_pickups.clear()
        load_cancellation_pickups.clear()
        load_7day_pickups.clear()
        st.rerun()

# ==============================================================================
# [6] 데이터 로드
# ==============================================================================
curr_df7 = load_snapshot(curr_date, 7)
curr_df8 = load_snapshot(curr_date, 8)
curr_df9 = load_snapshot(curr_date, 9)
prev_df7 = load_snapshot(prev_date, 7) if prev_date else None
prev_df8 = load_snapshot(prev_date, 8) if prev_date else None
prev_df9 = load_snapshot(prev_date, 9) if prev_date else None

curr_df = combine_months(curr_df7, curr_df8, curr_df9)
prev_df = combine_months(prev_df7, prev_df8, prev_df9)

_pickup_date = (
    datetime.strptime(curr_date, "%Y-%m-%d") - timedelta(days=1)
).strftime("%Y-%m-%d")
res_today = load_reservation_pickups(_pickup_date)
cancel_today = load_cancellation_pickups(_pickup_date)
res_period_stats = calc_res_period_stats(res_today, cancel_today)

pace_7day = load_7day_pickups(curr_date)

if not res_today.empty:
    st.sidebar.success(f"신규 예약 {len(res_today)}건 로드됨\n({_pickup_date} 예약분)")
else:
    st.sidebar.info(f"{_pickup_date} 예약 데이터 없음\n(Daily Pick-up에서 어제 예약 파일 업로드 필요)")

# ==============================================================================
# [7] 메인 화면
# ==============================================================================
st.title("Summer 2026 Revenue Tracker")
st.caption(
    f"기준: **{curr_date}**  |  비교: **{prev_date or '없음'}**  "
    f"|  구간별 데일리 픽업 · ADR · Revenue 모니터링"
)

if curr_df is None:
    st.warning(f"선택한 스냅샷 ({curr_date})에 7·8월 데이터가 없습니다.")
    st.stop()

curr_df["Date"] = pd.to_datetime(curr_df["Date"])
if prev_df is not None:
    prev_df["Date"] = pd.to_datetime(prev_df["Date"])


# ==============================================================================
# [7.3] 3분기(7~9월) 통합목표 현황  ← 보고서 승인 실행안
# ==============================================================================
def _mrev(_df):
    return float(_df["REV"].sum()) if (_df is not None and not _df.empty) else 0.0

_otb_m = {7: _mrev(curr_df7), 8: _mrev(curr_df8), 9: _mrev(curr_df9)}
_q3_otb = sum(_otb_m.values())
_q3_pct = _q3_otb / Q3_TARGET_REV if Q3_TARGET_REV else 0

st.markdown("### 3분기 통합목표 현황 (승인 실행안)")
st.caption("월별 개별 달성이 아니라 9월 초과 달성으로 7·8월 부족분을 흡수하는 구조 · 통합목표 3,572,497,647원 · 계획착지 35.83억(100.3%)")
_names = {7: "7월 (잠금)", 8: "8월 (현실선)", 9: "9월 (승부처)"}
_qc = st.columns(4)
for _m, _col in zip([7, 8, 9], _qc[:3]):
    with _col:
        _o = _otb_m[_m]; _t = MONTH_TARGETS[_m]["rev"]; _pl = PLAN_LANDING[_m]
        st.metric(_names[_m], f"{_o/1e8:.2f}억", f"목표대비 {(_o-_t)/1e8:+.2f}억")
        st.caption(f"권장착지 {_pl/1e8:.2f}억 · 목표 {_t/1e8:.2f}억")
with _qc[3]:
    st.metric("3분기 누적 OTB", f"{_q3_otb/1e8:.2f}억", f"달성률 {_q3_pct*100:.1f}%")
    st.caption(f"목표 {Q3_TARGET_REV/1e8:.2f}억")
st.progress(min(_q3_pct, 1.0),
            text=f"3분기 통합 달성률 {_q3_pct*100:.1f}%  (누적 {_q3_otb/1e8:.2f}억 / 목표 {Q3_TARGET_REV/1e8:.2f}억)")

# 8월 OTB 관리선 판정
_today_d = datetime.strptime(curr_date, "%Y-%m-%d").date()
_pts = [(datetime.strptime(_d, "%Y-%m-%d").date(), _v) for _d, _v in AUG_OTB_CHECKPOINTS]
def _aug_line(_td):
    if _td <= _pts[0][0]:
        return _pts[0][1]
    for (_d0, _v0), (_d1, _v1) in zip(_pts, _pts[1:]):
        if _d0 <= _td <= _d1:
            _fr = (_td - _d0).days / max(1, (_d1 - _d0).days)
            return _v0 + (_v1 - _v0) * _fr
    return _pts[-1][1]
_aug_otb = _otb_m[8]; _line = _aug_line(_today_d); _gap = _aug_otb - _line
if _gap >= 0:                 _lv, _c = "정상", "#16a34a"
elif _gap >= -20_000_000:     _lv, _c = "주의", "#d97706"
elif _gap >= -40_000_000:     _lv, _c = "위험", "#ea580c"
else:                         _lv, _c = "비상", "#dc2626"
_floor_warn = " · ⚠ 8월 하한 13.0억 사수선 근접" if _aug_otb < AUG_FLOOR else ""
st.markdown(
    f"<div style='background:{_c}18;border-left:4px solid {_c};border-radius:6px;"
    f"padding:8px 12px;margin-top:6px;font-size:13px;'>"
    f"<b>8월 OTB 관리선 판정: <span style='color:{_c};'>{_lv}</span></b> &nbsp; "
    f"오늘({curr_date}) 관리선 {_line/1e8:.2f}억 · 현재 {_aug_otb/1e8:.2f}억 · "
    f"갭 <b>{_gap/1e8:+.2f}억</b>{_floor_warn}</div>",
    unsafe_allow_html=True,
)
st.markdown("---")


def period_df(src_df, p):
    if src_df is None:
        return pd.DataFrame()
    mask = (src_df["Date"] >= pd.Timestamp(p["start"])) & (src_df["Date"] <= pd.Timestamp(p["end"]))
    return src_df[mask].copy()


def calc_summary(df):
    if df.empty:
        return {"rn": 0, "rev": 0, "adr": 0, "occ": 0.0}
    rn = df["RMS"].sum()
    rev = df["REV"].sum()
    adr = rev / rn if rn > 0 else 0
    days = df["Date"].nunique()
    occ = (rn / (TOTAL_ROOMS * days) * 100) if days > 0 else 0
    return {"rn": rn, "rev": rev, "adr": adr, "occ": occ}


# ==============================================================================
# [8] 구간 요약 카드 (상단 5개)
# ==============================================================================
st.markdown("### 구간별 OTB 현황 요약")
period_results = []

scenario_factor = 1 + scenario_adj / 100

summary_cols = st.columns(len(PERIODS))
for i, p in enumerate(PERIODS):
    c_df = period_df(curr_df, p)
    p_df = period_df(prev_df, p)
    cs = calc_summary(c_df)
    ps = calc_summary(p_df)

    pickup_rn = cs["rn"] - ps["rn"]
    pickup_rev = cs["rev"] - ps["rev"]
    res_stat = res_period_stats.get(p["id"])
    pickup_room_adr = res_stat["room_adr"] if res_stat else None
    pickup_total_adr = res_stat["total_adr"] if res_stat else None
    adr_vs_tgt = cs["adr"] - p["target_adr"]
    adr_color = "#16a34a" if adr_vs_tgt >= 0 else "#dc2626"
    pickup_adr_color = "#16a34a" if (pickup_room_adr or 0) >= p["target_adr"] else "#dc2626"

    _p_start = datetime.strptime(p["start"], "%Y-%m-%d").date()
    _p_end   = datetime.strptime(p["end"],   "%Y-%m-%d").date()
    _p_days  = (_p_end - _p_start).days + 1
    _target_rn = int(TOTAL_ROOMS * _p_days * p["target_occ"])
    effective_target_rn = math.ceil(_target_rn / (1 - p["wash_rate"]))
    _remaining = max(0, effective_target_rn - cs["rn"])
    _otb_rev   = cs["rev"]
    _is_range  = p["new_bk_adr_lo"] != p["new_bk_adr_hi"]

    adj_lo = p["new_bk_adr_lo"] * scenario_factor
    adj_hi = p["new_bk_adr_hi"] * scenario_factor

    def _blended(new_bk_price, _r=_remaining, _otb=_otb_rev, _trn=_target_rn, _cs_adr=cs["adr"]):
        if _trn <= 0:
            return _cs_adr
        if _r <= 0:
            return _cs_adr
        return (_otb + _r * new_bk_price) / _trn

    _blended_lo = _blended(adj_lo)
    _blended_hi = _blended(adj_hi)

    if _remaining <= 0:
        _blended_str = f"{cs['adr']:,.0f}원 (OCC 목표 달성)"
        _new_bk_str  = (
            f"{p['new_bk_adr_lo']:,}~{p['new_bk_adr_hi']:,}원"
            if _is_range else f"{p['new_bk_adr_lo']:,}원"
        )
    elif _is_range:
        _blended_str = f"{_blended_lo:,.0f}~{_blended_hi:,.0f}원"
        _new_bk_str  = f"{adj_lo:,.0f}~{adj_hi:,.0f}원"
    else:
        _blended_str = f"{_blended_lo:,.0f}원"
        _new_bk_str  = f"{adj_lo:,.0f}원"

    if scenario_adj != 0:
        _new_bk_str += f" (조정 {scenario_adj:+d}%)"

    period_results.append(
        {
            "period": p,
            "curr": cs,
            "prev": ps,
            "pickup_rn": pickup_rn,
            "pickup_rev": pickup_rev,
            "pickup_adr": pickup_room_adr,
            "res_stat": res_stat,
            "adr_vs_tgt": adr_vs_tgt,
            "curr_df": c_df,
            "prev_df": p_df,
            "target_rn": _target_rn,
            "effective_target_rn": effective_target_rn,
            "remaining_rn": _remaining,
            "blended_lo": _blended_lo,
            "blended_hi": _blended_hi,
            "blended_str": _blended_str,
            "new_bk_str": _new_bk_str,
            "is_range": _is_range,
            "adj_lo": adj_lo,
            "adj_hi": adj_hi,
        }
    )

    with summary_cols[i]:
        pickup_sign = "+" if pickup_rn >= 0 else ""
        room_adr_str  = f"{pickup_room_adr:,.0f}원"  if pickup_room_adr  is not None else "—"
        total_adr_str = f"{pickup_total_adr:,.0f}원" if pickup_total_adr is not None else "—"

        if res_stat:
            cancel_rn_val = res_stat.get("cancel_rn", 0)
            net_rn_val = res_stat.get("net_rn", res_stat["rn"])
            res_info = (
                f"<span style='font-size:10px;color:#6b7280;'>"
                f"{res_stat['count']}건 신규 / 취소 -{cancel_rn_val}RN / 순픽업 {net_rn_val}RN</span>"
            )
        else:
            res_info = "<span style='font-size:10px;color:#9ca3af;'>예약 데이터 없음</span>"

        st.markdown(
            f"""
            <div class="period-card" style="background:{p['bg']};border-left:4px solid {p['color']};">
                <div style="font-weight:900;color:{p['color']};font-size:14px;">{p['label']}</div>
                <div style="color:#6b7280;font-size:11px;margin-bottom:6px;">{p['desc']}</div>
                <div><b>OTB RN</b> &nbsp;<span style="font-size:18px;font-weight:900;">{cs['rn']:,.0f}</span>
                    &nbsp;<span style="color:{'#16a34a' if pickup_rn>=0 else '#dc2626'};font-size:12px;">
                    ({pickup_sign}{pickup_rn:,.0f})</span>
                </div>
                <div><b>OTB ADR</b> &nbsp;<span style="color:{adr_color};font-weight:900;">{cs['adr']:,.0f}원</span>
                    &nbsp;<span style="font-size:11px;color:{adr_color};">({'+' if adr_vs_tgt>=0 else ''}{adr_vs_tgt:,.0f})</span>
                </div>
                <div><b>신규 객실 ADR</b> &nbsp;<span style="color:{pickup_adr_color};font-weight:900;">{room_adr_str}</span></div>
                <div><b>신규 총매출 ADR</b> &nbsp;<span style="color:#6366f1;font-weight:900;">{total_adr_str}</span></div>
                <div style="margin-top:2px;">{res_info}</div>
                <hr style="margin:6px 0;border-color:#e5e7eb;">
                <div style="font-size:11px;color:#374151;">
                  <b>신규 목표 단가</b> <span style="color:#7c3aed;font-weight:700;">{_new_bk_str}</span>
                </div>
                <div style="font-size:11px;color:#374151;">
                  <b>예상 최종 ADR</b>
                  <span style="color:#1d4ed8;font-weight:700;">{_blended_str}</span>
                  <span style="font-size:10px;color:#9ca3af;"> (잔여 {_remaining}RN 소화 시)</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

# ==============================================================================
# ==============================================================================
# [8.5] 구간별 Revenue Pacing 분석 (매출 기준)
# ==============================================================================
st.markdown("---")
st.markdown("### Revenue Pacing — 매출 목표 달성 시뮬레이션")
st.caption(
    f"기준 스냅샷: {curr_date}  |  어제 예약 데이터: {_pickup_date}  |  "
    "신규 목표 단가 기준으로 매출 갭을 채우는 데 필요한 일일 픽업을 계산합니다."
)

_today_dt = datetime.strptime(curr_date, "%Y-%m-%d").date()

def _pacing_action(pace_ratio, days_to_start, rev_pct):
    if rev_pct >= 1.0:
        return "REVENUE TARGET MET", "#16a34a", "OTA inventory reduction / BAR increase review"
    if pace_ratio is None:
        color = "#6b7280"
        if days_to_start > 45:
            advice = "D+45 window — check OTA exposure & package deals"
        elif days_to_start > 21:
            advice = "Upload yesterday pickup data to see revenue pace"
        else:
            advice = "URGENT — upload pickup data immediately"
        return "NO DATA", color, advice
    if pace_ratio >= 1.5:
        return "STRONG PACE", "#16a34a", "Revenue on track — consider BAR increase"
    if pace_ratio >= 1.0:
        return "ON PACE", "#16a34a", "Revenue pace healthy — maintain strategy"
    if pace_ratio >= 0.7:
        if days_to_start > 45:
            advice = "Monitor — expand OTA visibility / review package"
        elif days_to_start > 21:
            advice = "Boost OTA ad / re-check channel mix"
        elif days_to_start > 7:
            advice = "WARNING — lower BAR tier / add live-commerce"
        else:
            advice = "CRITICAL D-7 — immediate pricing & channel review"
        return "BELOW PACE", "#d97706", advice
    if days_to_start > 45:
        advice = "Underperforming — launch promotion / review OTA ranking"
    elif days_to_start > 21:
        advice = "ALERT — aggressive OTA ad / flash deal / live session"
    elif days_to_start > 7:
        advice = "URGENT — lower BAR + live session + SNS push"
    else:
        advice = "CRITICAL — all-channel emergency pricing review"
    return "CRITICAL PACE", "#dc2626", advice

pace_cols = st.columns(len(PERIODS))
for i, pr in enumerate(period_results):
    p  = pr["period"]
    cs = pr["curr"]
    rs = pr.get("res_stat")

    start_dt    = datetime.strptime(p["start"], "%Y-%m-%d").date()
    end_dt      = datetime.strptime(p["end"],   "%Y-%m-%d").date()
    period_days = (end_dt - start_dt).days + 1

    # ── 매출 기준 목표 및 갭 ──────────────────────────────────────────────
    target_rn_base = int(TOTAL_ROOMS * period_days * p["target_occ"])
    target_rev     = target_rn_base * p["target_adr"]   # 구간 매출 목표
    otb_rev        = cs["rev"]                           # 현재 OTB 매출
    revenue_gap    = max(0.0, target_rev - otb_rev)      # 채워야 할 매출
    rev_pct        = otb_rev / target_rev if target_rev > 0 else 0

    # ── 판매 마감까지 남은 일수 ───────────────────────────────────────────
    deadline_dt      = end_dt - timedelta(days=p["booking_buffer"])
    days_to_deadline = max(1, (deadline_dt - _today_dt).days)
    days_to_start    = max(0, (start_dt - _today_dt).days)

    # ── 필요 일일 픽업 (매출 갭 → 순객실 → wash 반영 그로스) ─────────────
    net_rooms_needed   = revenue_gap / p["new_bk_adr_lo"] if p["new_bk_adr_lo"] > 0 else 0
    gross_rooms_needed = net_rooms_needed / (1 - p["wash_rate"]) if p["wash_rate"] < 1 else net_rooms_needed
    required_daily     = gross_rooms_needed / days_to_deadline if days_to_deadline > 0 else 0

    # ── 7일 평균 vs 어제 실적 (순픽업 기준) ──────────────────────────────
    p7d            = pace_7day.get(p["id"], {})
    avg7           = p7d.get("avg_net_rn", 0)
    days_with_data = p7d.get("days_with_data", 0)
    yesterday_net  = rs["net_rn"] if rs else None

    pace_actual = avg7 if days_with_data >= 3 else yesterday_net
    pace_ratio  = (pace_actual / required_daily) if (pace_actual is not None and required_daily > 0) else None

    # ── 현 페이스 유지 시 예상 매출 ──────────────────────────────────────
    if pace_actual is not None and pace_actual > 0:
        projected_add_rev   = pace_actual * days_to_deadline * p["new_bk_adr_lo"]
        projected_total_rev = otb_rev + projected_add_rev
        proj_pct            = projected_total_rev / target_rev if target_rev > 0 else 0
        proj_color          = "#16a34a" if proj_pct >= 0.95 else ("#d97706" if proj_pct >= 0.80 else "#dc2626")
        proj_str            = f"{projected_total_rev/1e8:.2f}억 ({proj_pct*100:.0f}%)"
    else:
        proj_color = "#6b7280"
        proj_str   = f"— (목표 {target_rev/1e8:.2f}억)"

    status_label, status_color, advice = _pacing_action(pace_ratio, days_to_start, rev_pct)

    # ── 프로그레스 바 (매출 달성률) ──────────────────────────────────────
    bar_pct   = min(rev_pct, 1.0)
    bar_color = "#16a34a" if rev_pct >= 0.8 else ("#d97706" if rev_pct >= 0.5 else "#dc2626")

    yesterday_str = f"{yesterday_net:.0f} RN" if yesterday_net is not None else "—"
    avg7_str      = f"{avg7:.1f} RN" if days_with_data > 0 else "—"
    required_str  = f"{required_daily:.1f} RN/day" if required_daily > 0 else "Achieved"
    pace_str      = f"{pace_ratio*100:.0f}%" if pace_ratio is not None else "—"

    with pace_cols[i]:
        html_card = (
            '<div style="border:1px solid #e5e7eb;border-radius:10px;padding:12px;'
            'font-size:12px;line-height:1.8;">'
            f'<div style="font-weight:900;color:{p["color"]};margin-bottom:4px;">'
            f'{p["label"]} {p["desc"]}</div>'

            '<div style="font-size:10px;color:#6b7280;margin-bottom:2px;">매출 달성률</div>'
            '<div style="background:#f3f4f6;border-radius:6px;height:8px;margin-bottom:6px;">'
            f'<div style="background:{bar_color};width:{bar_pct*100:.0f}%;height:8px;border-radius:6px;"></div>'
            '</div>'

            f'<div><b>OTB 매출</b>&nbsp;'
            f'<span style="font-weight:700;color:{bar_color};">{otb_rev/1e8:.2f}억</span>'
            f'&nbsp;/ 목표 <b>{target_rev/1e8:.2f}억</b>'
            f'&nbsp;<span style="color:{bar_color};font-size:11px;">({rev_pct*100:.0f}%)</span></div>'

            f'<div><b>매출 갭</b>&nbsp;'
            f'<span style="color:#dc2626;font-weight:700;">{revenue_gap/1e8:.2f}억원</span>'
            f'&nbsp;<span style="font-size:10px;color:#9ca3af;">@ {p["new_bk_adr_lo"]:,}원</span></div>'

            '<hr style="margin:6px 0;border-color:#f3f4f6;">'

            f'<div><b>필요 일일 픽업</b>&nbsp;'
            f'<span style="font-weight:700;color:#1d4ed8;">{required_str}</span>'
            f'&nbsp;<span style="font-size:10px;color:#9ca3af;">(wash {p["wash_rate"]*100:.0f}% 반영)</span></div>'

            f'<div>어제: <b>{yesterday_str}</b>&nbsp;|&nbsp;7일평균: <b>{avg7_str}</b>'
            f'&nbsp;<span style="color:{status_color};font-weight:700;">({pace_str})</span></div>'

            '<hr style="margin:6px 0;border-color:#f3f4f6;">'

            '<div style="font-size:11px;"><b>현 페이스 예상 매출</b><br>'
            f'<span style="color:{proj_color};font-weight:700;">{proj_str}</span>'
            f'&nbsp;<span style="font-size:10px;color:#9ca3af;">/ 목표 {target_rev/1e8:.2f}억</span></div>'

            f'<div style="margin-top:6px;padding:5px 8px;background:{status_color}22;'
            f'border-left:3px solid {status_color};border-radius:4px;'
            f'color:{status_color};font-weight:700;font-size:11px;">'
            f'{status_label}</div>'

            f'<div style="font-size:10px;color:#4b5563;margin-top:4px;">{advice}</div>'

            f'<div style="font-size:10px;color:#9ca3af;margin-top:4px;">'
            f'D-{days_to_start} | 마감까지 {days_to_deadline}일 (기간 종료 {p["booking_buffer"]}일 전)'
            '</div>'
            '</div>'
        )
        st.markdown(html_card, unsafe_allow_html=True)


# ==============================================================================
# [9] 월별 OTB 총계 (7월·8월)
# ==============================================================================
st.markdown("---")
st.markdown("### 월별 OTB vs 목표")
mcol7, mcol8, mcol9 = st.columns(3)

for m_num, mcol, df_m in [(7, mcol7, curr_df7), (8, mcol8, curr_df8), (9, mcol9, curr_df9)]:
    tgt = MONTH_TARGETS[m_num]
    with mcol:
        st.markdown(f"#### {m_num}월")
        if df_m is not None and not df_m.empty:
            rn = df_m["RMS"].sum()
            rev = df_m["REV"].sum()
            adr = rev / rn if rn > 0 else 0

            need_rn = max(tgt["rn"] - rn, 0)
            today = datetime.now()
            _last_day = calendar.monthrange(2026, m_num)[1]
            end_day = datetime(2026, m_num, _last_day)
            days_left = max((end_day.date() - today.date()).days, 1)
            daily_need = need_rn / days_left

            rc1, rc2, rc3 = st.columns(3)
            rc1.metric("OTB RN", f"{rn:,.0f}", f"{rn - tgt['rn']:+,.0f} vs 목표")
            rc2.metric("OTB Rev", f"{rev/1e8:.2f}억", f"{(rev - tgt['rev'])/1e8:+.2f}억 vs 목표")
            rc3.metric("ADR", f"{adr:,.0f}원")

            rn_pct  = min(rn  / tgt["rn"],  1.0) if tgt["rn"]  > 0 else 0
            rev_pct = min(rev / tgt["rev"], 1.0) if tgt["rev"] > 0 else 0
            st.progress(rn_pct,  text=f"RN {rn_pct*100:.1f}% | 필요 추가 {need_rn:,.0f} RN (일평균 {daily_need:.1f} RN × {days_left}일)")
            st.progress(rev_pct, text=f"Revenue {rev_pct*100:.1f}%")
        else:
            st.info(f"{m_num}월 데이터 없음")

# ==============================================================================
# [9.5] 9월 승부처 관리 — 단체 · 하드블럭 · 핵심 레버
# ==============================================================================
st.markdown("---")
st.markdown("### 9월 승부처 관리 (단체 · 하드블럭 · ADR)")
st.caption("9월은 3분기 성패를 가르는 달. 예약창구(40~70일)와 확정 단체를 활용해 목표를 초과 달성하여 7·8월 부족분을 흡수.")
_sep_otb = _mrev(curr_df9); _sep_plan = PLAN_LANDING[9]
_sc1, _sc2, _sc3, _sc4 = st.columns(4)
_sc1.metric("9월 OTB", f"{_sep_otb/1e8:.2f}억", f"권장착지 {_sep_plan/1e8:.2f}억")
_sc2.metric("ADR 목표", f"{SEP_STRATEGY['adr_target']:,}원", "+8% 유지")
_sc3.metric("개인 순판매 목표", f"{SEP_STRATEGY['indiv_sell_through']*100:.0f}%", "잔여 대비")
_sc4.metric("단체 목표", f"{SEP_STRATEGY['group_target_rev']/1e8:.2f}억",
            f"현재 {SEP_STRATEGY['group_current_rev']/1e8:.2f}억")
_grp_gap = SEP_STRATEGY["group_target_rev"] - SEP_STRATEGY["group_current_rev"]
st.progress(min(SEP_STRATEGY["group_current_rev"] / SEP_STRATEGY["group_target_rev"], 1.0),
            text=f"단체 진척 {SEP_STRATEGY['group_current_rev']/1e8:.2f}억 / 목표 "
                 f"{SEP_STRATEGY['group_target_rev']/1e8:.2f}억 (추가 필요 {_grp_gap/1e6:.0f}백만)")
_peak_str = ", ".join("9/" + _d[3:] for _d in SEP_STRATEGY["peak_dates"])
st.markdown(
    f"- **피크 날짜(요금 극대화·할인 금지):** {_peak_str} — ADR 하한 {SEP_STRATEGY['peak_adr']:,}원\n"
    f"- **공략 날짜(저수요 평일):** 날짜한정 상품·2박·폐쇄형 B2B·환불불가 중심, ADR 하한 {SEP_STRATEGY['adr_target']:,}원\n"
    f"- **9/17~18 하드블럭 {SEP_STRATEGY['hardblock_confirmed_rn']}박 확정(OTB 미반영):** 실입금·룸리스트·OTB 반영을 매일 별도 추적 "
    f"(단체 2.30억에 포함, 중복 산정하지 않음)"
)

# ==============================================================================
# [9.7] 일자별 권장목표 대비 추적 (플랜 대비 부족분 / 채울 RN)
# ==============================================================================
st.markdown("---")
st.markdown("### 일자별 권장목표 대비 추적")
st.caption("보고서에서 정한 일자별 권장 착지(플랜) 대비 현재 OTB 부족액과 추가로 채워야 할 객실 수. 부족액 ÷ ADR하한 = 필요 픽업 RN. (빨강=부족, 초록=초과달성)")

def _plan_track(df_month, pfx, mlabel):
    if df_month is None or df_month.empty:
        st.info(f"{mlabel} 데이터 없음 (다른 페이지에서 업로드 필요)")
        return
    g = df_month.groupby("DateStr").agg(RMS=("RMS", "sum"), REV=("REV", "sum")).reset_index()
    otb_map = {r["DateStr"]: (r["RMS"], r["REV"]) for _, r in g.iterrows()}
    rows = []
    for d in sorted([k for k in DATE_PLAN if k.startswith(pfx)]):
        pl = DATE_PLAN[d]
        rn, rev = otb_map.get(d, (0, 0))
        short = pl["rev"] - rev
        need_rn = max(0, round(short / pl["adr"])) if pl["adr"] > 0 else 0
        rows.append({
            "날짜": d[5:], "OTB RN": rn, "권장 RN": pl["rn"],
            "OTB매출": rev, "권장매출": pl["rev"],
            "부족액": short, "필요픽업RN": need_rn,
        })
    tdf = pd.DataFrame(rows)
    tot = {
        "날짜": "합계", "OTB RN": tdf["OTB RN"].sum(), "권장 RN": tdf["권장 RN"].sum(),
        "OTB매출": tdf["OTB매출"].sum(), "권장매출": tdf["권장매출"].sum(),
        "부족액": tdf["부족액"].sum(), "필요픽업RN": tdf["필요픽업RN"].sum(),
    }
    tdf = pd.concat([tdf, pd.DataFrame([tot])], ignore_index=True)

    def _color_short(v):
        try:
            x = float(v)
            if x > 0:   return "color:#dc2626;font-weight:bold;"
            elif x < 0: return "color:#16a34a;font-weight:bold;"
        except Exception:
            pass
        return ""

    def _hl_total(row):
        if str(row.iloc[0]) == "합계":
            return ["background:#eff6ff;font-weight:900;border-top:2px solid #1d4ed8"] * len(row)
        return [""] * len(row)

    num_fmt = {c: "{:,.0f}" for c in ["OTB RN", "권장 RN", "OTB매출", "권장매출", "부족액", "필요픽업RN"]}
    sty = (tdf.style.format(num_fmt)
           .map(_color_short, subset=["부족액", "필요픽업RN"])
           .apply(_hl_total, axis=1))
    st.dataframe(sty, use_container_width=True, hide_index=True, height=340)
    st.caption(f"{mlabel} 총 부족액 {tot['부족액']/1e8:.2f}억 · 총 필요 픽업 {tot['필요픽업RN']:,.0f} RN "
               f"(권장 착지 {tot['권장매출']/1e8:.2f}억 / 현재 OTB {tot['OTB매출']/1e8:.2f}억)")

_pt_tabs = st.tabs(["8월", "9월"])
with _pt_tabs[0]:
    _plan_track(curr_df8, "2026-08", "8월")
with _pt_tabs[1]:
    _plan_track(curr_df9, "2026-09", "9월")


# ==============================================================================
# [10] 구간별 상세 탭
# ==============================================================================
st.markdown("---")
st.markdown("### 구간별 데일리 픽업 상세")

tab_labels = [f"{pr['period']['label']} {pr['period']['desc']}" for pr in period_results]
tabs = st.tabs(tab_labels)

for tab, pr in zip(tabs, period_results):
    p = pr["period"]
    c_df = pr["curr_df"]
    p_df_period = pr["prev_df"]

    with tab:
        if c_df.empty:
            st.info(f"{p['desc']} 구간에 데이터가 없습니다.")
            continue

        merged = c_df.copy()
        if not p_df_period.empty:
            prev_sub = p_df_period[
                ["DateStr", "RMS", "REV", "OCC", "ADR", "FIT_RMS", "FIT_REV", "GRP_RMS", "GRP_REV"]
            ].copy()
            prev_sub.columns = [
                "DateStr", "RMS_prev", "REV_prev", "OCC_prev", "ADR_prev",
                "FIT_RMS_prev", "FIT_REV_prev", "GRP_RMS_prev", "GRP_REV_prev",
            ]
            merged = pd.merge(merged, prev_sub, on="DateStr", how="left").fillna(0)
        else:
            for c in ["RMS_prev", "REV_prev", "OCC_prev", "ADR_prev", "FIT_RMS_prev", "FIT_REV_prev", "GRP_RMS_prev", "GRP_REV_prev"]:
                merged[c] = 0

        merged["Pick_RN"]  = merged["RMS"] - merged["RMS_prev"]
        merged["Pick_REV"] = merged["REV"] - merged["REV_prev"]
        merged["Pick_ADR"] = np.nan
        merged["ADR_vs_Tgt"] = merged["ADR"] - p["target_adr"]
        merged["Date"] = pd.to_datetime(merged["DateStr"])
        merged = merged.sort_values("Date")

        cs = pr["curr"]
        ps = pr["prev"]
        res_stat = pr.get("res_stat")
        pickup_room_adr  = res_stat["room_adr"]  if res_stat else None
        pickup_total_adr = res_stat["total_adr"] if res_stat else None
        res_hint = (f"{_pickup_date} 예약 | {res_stat['count']}건 / {res_stat['rn']}RN" if res_stat
                    else "예약 데이터 없음")

        m1, m2, m3, m4, m5, m6, m7 = st.columns(7)
        m1.metric("OTB RN",        f"{cs['rn']:,.0f}",        f"{pr['pickup_rn']:+,.0f} (OTB)")
        m2.metric("OTB Revenue",    f"{cs['rev']/1e8:.2f}억",  f"{pr['pickup_rev']/1e6:+.1f}M (OTB)")
        m3.metric("OTB ADR (종합)", f"{cs['adr']:,.0f}원",     f"{pr['adr_vs_tgt']:+,.0f} vs 목표")
        m4.metric(
            "신규 객실 ADR",
            f"{pickup_room_adr:,.0f}원" if pickup_room_adr else "—",
            f"{pickup_room_adr - p['target_adr']:+,.0f} vs 목표" if pickup_room_adr else "데이터 없음",
            help=f"객실료 기준 | {res_hint}",
        )
        m5.metric(
            "신규 총매출 ADR",
            f"{pickup_total_adr:,.0f}원" if pickup_total_adr else "—",
            f"{pickup_total_adr - pickup_room_adr:+,.0f} (F&B 포함 차이)" if (pickup_total_adr and pickup_room_adr) else "",
            help=f"총매출(객실+F&B) 기준 | {res_hint}",
        )
        m6.metric("FIT ADR",
                  f"{(merged['FIT_REV'].sum() / merged['FIT_RMS'].sum()):,.0f}원" if merged['FIT_RMS'].sum() > 0 else "—")
        m7.metric("GRP ADR",
                  f"{(merged['GRP_REV'].sum() / merged['GRP_RMS'].sum()):,.0f}원" if merged['GRP_RMS'].sum() > 0 else "—")

        # ADR 시뮬레이션 박스
        _b_lo   = pr["blended_lo"]
        _b_hi   = pr["blended_hi"]
        _b_str  = pr["blended_str"]
        _nb_str = pr["new_bk_str"]
        _rem    = pr["remaining_rn"]
        _tgt_rn = pr["target_rn"]
        _eff_tgt = pr["effective_target_rn"]
        _b_color = "#16a34a" if _b_lo >= p["target_adr"] else ("#d97706" if _b_lo >= p["target_adr"] * 0.95 else "#dc2626")

        scenario_note = ""
        if scenario_adj != 0:
            adj_lo_v = pr["adj_lo"]
            scenario_note = f" &nbsp;<span style='color:#d97706;font-weight:700;'>조정 단가: {adj_lo_v:,.0f}원</span>"

        st.markdown(
            f"""
            <div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;
                        padding:10px 16px;font-size:12px;margin-bottom:8px;line-height:1.8;">
              <span style="font-weight:700;color:#1d4ed8;">ADR 시뮬레이션</span> &nbsp;|&nbsp;
              신규 예약 목표 단가 <b style="color:#7c3aed;">{_nb_str}</b>으로
              잔여 <b>{_rem:,} RN</b> 소화 시 &nbsp;→&nbsp;
              <b>예상 최종 ADR: <span style="color:{_b_color};font-size:14px;">{_b_str}</span></b>
              &nbsp;<span style="color:#6b7280;">(목표 RN {_tgt_rn:,} | 효과적 목표 {_eff_tgt:,})</span>
              {scenario_note}
            </div>
            """,
            unsafe_allow_html=True,
        )

        adr_diff = cs["adr"] - p["target_adr"]
        if cs["rn"] == 0:
            pass
        elif adr_diff >= 0:
            st.markdown(f'<div class="alert-green">ADR <b>{cs["adr"]:,.0f}원</b> — 목표 대비 <b>+{adr_diff:,.0f}원</b> 상회</div>', unsafe_allow_html=True)
        elif adr_diff >= -20_000:
            st.markdown(f'<div class="alert-yellow">ADR <b>{cs["adr"]:,.0f}원</b> — 목표 대비 <b>{adr_diff:,.0f}원</b> 미달 (BAR 점검 권고)</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="alert-red">ADR <b>{cs["adr"]:,.0f}원</b> — 목표 대비 <b>{adr_diff:,.0f}원</b> 미달 (즉시 가격 검토 필요)</div>', unsafe_allow_html=True)

        st.markdown("")

        base_cols = ["DateStr", "RMS_prev", "REV_prev", "ADR_prev",
                     "RMS", "REV", "ADR", "OCC", "Pick_RN", "Pick_REV", "Pick_ADR", "ADR_vs_Tgt"]
        if "WeekDay" in merged.columns:
            base_cols = ["DateStr", "WeekDay"] + base_cols[1:]
        display = merged[[c for c in base_cols if c in merged.columns]].copy()

        col_names = {
            "DateStr": "날짜",
            "WeekDay": "요일",
            "RMS_prev": "전일 RN",
            "REV_prev": "전일 Revenue",
            "ADR_prev": "전일 ADR",
            "RMS": "OTB RN",
            "REV": "OTB Revenue",
            "ADR": "OTB ADR (종합)",
            "OCC": "OCC%",
            "Pick_RN": "픽업 RN",
            "Pick_REV": "픽업 Revenue",
            "Pick_ADR": "픽업 ADR (신규)",
            "ADR_vs_Tgt": f"OTB ADR vs 목표({p['target_adr']:,})",
        }
        display.rename(columns=col_names, inplace=True)

        num_cols = [c for c in display.columns if c not in ["날짜", "요일", "OCC%"]]
        total_row = {c: np.nan for c in display.columns}
        total_row["날짜"] = "TOTAL"
        total_row["요일"] = ""
        for c in num_cols:
            try:
                total_row[c] = pd.to_numeric(display[c], errors="coerce").sum()
            except Exception:
                total_row[c] = np.nan
        total_row["OTB ADR (종합)"] = cs["adr"]
        total_row[f"OTB ADR vs 목표({p['target_adr']:,})"] = adr_diff
        if "전일 ADR" in display.columns and ps["rn"] > 0:
            total_row["전일 ADR"] = ps["adr"]
        total_row["픽업 ADR (신규)"] = res_stat["room_adr"] if res_stat else np.nan
        display = pd.concat([display, pd.DataFrame([total_row])], ignore_index=True)

        def _fmt_num(v):
            try:
                if pd.isna(v): return "—"
                return f"{float(v):,.0f}"
            except Exception:
                return str(v)

        def _fmt_occ(v):
            try:
                if pd.isna(v): return "—"
                return f"{float(v):.1f}%"
            except Exception:
                return str(v)

        fmt = {}
        for c in display.columns:
            if c in ["날짜", "요일"]:
                continue
            elif "OCC" in c:
                fmt[c] = _fmt_occ
            else:
                fmt[c] = _fmt_num

        def color_pickup(v):
            try:
                val = float(str(v).replace(",", ""))
                if val > 0:   return "color:#16a34a;font-weight:bold;"
                elif val < 0: return "color:#dc2626;font-weight:bold;"
            except Exception:
                pass
            return ""

        def color_adr(v):
            try:
                val = float(str(v).replace(",", ""))
                if val >= 0:           return "background:#f0fdf4;color:#16a34a;font-weight:bold;"
                elif val >= -20_000:   return "background:#fffbeb;color:#d97706;font-weight:bold;"
                else:                  return "background:#fef2f2;color:#dc2626;font-weight:bold;"
            except Exception:
                pass
            return ""

        def hl_total(row):
            if str(row.iloc[0]) == "TOTAL":
                return ["background:#eff6ff;font-weight:900;border-top:2px solid #1d4ed8"] * len(row)
            return [""] * len(row)

        pick_rn_rev_cols = [c for c in display.columns if "픽업 RN" in c or "픽업 Revenue" in c]
        pickup_adr_cols  = [c for c in display.columns if "픽업 ADR" in c]
        adr_vs_cols      = [c for c in display.columns if "vs 목표" in c]

        _p_target_adr = p["target_adr"]
        def color_pickup_adr(v):
            try:
                if pd.isna(v): return ""
                val = float(str(v).replace(",", ""))
                if val >= _p_target_adr:
                    return "color:#16a34a;font-weight:bold;background:#f0fdf4;"
                elif val >= _p_target_adr * 0.95:
                    return "color:#d97706;font-weight:bold;background:#fffbeb;"
                else:
                    return "color:#dc2626;font-weight:bold;background:#fef2f2;"
            except Exception:
                return ""

        styler = display.style.format(fmt)
        if pick_rn_rev_cols:
            styler = styler.map(color_pickup, subset=pick_rn_rev_cols)
        if pickup_adr_cols:
            styler = styler.map(color_pickup_adr, subset=pickup_adr_cols)
        if adr_vs_cols:
            styler = styler.map(color_adr, subset=adr_vs_cols)
        styler = styler.apply(hl_total, axis=1)
        st.dataframe(styler, use_container_width=True, hide_index=True)

        # Excel 다운로드
        import io as _io
        _excel_buf = _io.BytesIO()
        display.to_excel(_excel_buf, index=False, engine="openpyxl")
        st.download_button(
            label="Excel",
            data=_excel_buf.getvalue(),
            file_name=f"pickup_{p['id']}_{curr_date}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=f"dl_{p['id']}",
        )

        # 세그먼트 / 채널별 신규 예약
        with st.expander("세그먼트 / 채널별 신규 예약", expanded=False):
            if res_today is not None and not res_today.empty:
                _mask = (res_today["CheckIn"] >= pd.Timestamp(p["start"])) & (res_today["CheckIn"] <= pd.Timestamp(p["end"]))
                _period_res = res_today[_mask]
                if not _period_res.empty:
                    sc1, sc2 = st.columns(2)
                    with sc1:
                        st.markdown("**세그먼트별**")
                        seg_col = "Segment" if "Segment" in _period_res.columns else None
                        if seg_col:
                            seg_grp = _period_res.groupby(seg_col, dropna=False).agg(
                                건수=("RN", "count"), RN=("RN", "sum"), ADR=("Room_Revenue", "sum")
                            ).reset_index()
                            seg_grp["ADR"] = seg_grp["ADR"] / seg_grp["RN"].replace(0, 1)
                            seg_grp = seg_grp.sort_values("RN", ascending=False)
                            st.dataframe(seg_grp.style.format({"RN": "{:,.0f}", "ADR": "{:,.0f}"}), hide_index=True)
                        else:
                            st.info("Segment 컬럼 없음")
                    with sc2:
                        st.markdown("**채널/거래처별 (Top 5)**")
                        acc_col = "Account" if "Account" in _period_res.columns else None
                        if acc_col:
                            acc_grp = _period_res.groupby(acc_col, dropna=False).agg(
                                건수=("RN", "count"), RN=("RN", "sum"), ADR=("Room_Revenue", "sum")
                            ).reset_index()
                            acc_grp["ADR"] = acc_grp["ADR"] / acc_grp["RN"].replace(0, 1)
                            acc_grp = acc_grp.sort_values("RN", ascending=False).head(5)
                            st.dataframe(acc_grp.style.format({"RN": "{:,.0f}", "ADR": "{:,.0f}"}), hide_index=True)
                        else:
                            st.info("Account 컬럼 없음")
                else:
                    st.info("이 구간 신규 예약 데이터 없음")
            else:
                st.info("예약 데이터 없음")

        chart1, chart2 = st.columns(2)
        with chart1:
            fig_rn = go.Figure()
            if not p_df_period.empty:
                fig_rn.add_trace(go.Scatter(
                    x=merged["DateStr"], y=merged["RMS_prev"],
                    name="Prev OTB", line=dict(color="#9ca3af", dash="dot", width=1.5), mode="lines",
                ))
            fig_rn.add_trace(go.Bar(
                x=merged["DateStr"], y=merged["RMS"],
                name="OTB RN", marker_color=p["color"], opacity=0.85,
            ))
            fig_rn.update_layout(title="OTB RN by Date", height=300, margin=dict(l=10,r=10,t=30,b=10))
            st.plotly_chart(fig_rn, use_container_width=True)
        with chart2:
            fig_adr = go.Figure()
            fig_adr.add_hline(y=p["target_adr"], line_dash="dash", line_color="#dc2626", annotation_text="ADR Target")
            if not p_df_period.empty:
                fig_adr.add_trace(go.Scatter(
                    x=merged["DateStr"], y=merged["ADR_prev"],
                    name="Prev ADR", line=dict(color="#9ca3af", dash="dot", width=1.5), mode="lines",
                ))
            fig_adr.add_trace(go.Scatter(
                x=merged["DateStr"], y=merged["ADR"],
                name="OTB ADR", line=dict(color=p["color"], width=2), mode="lines+markers",
            ))
            fig_adr.update_layout(title="OTB ADR by Date", height=300, margin=dict(l=10,r=10,t=30,b=10))
            st.plotly_chart(fig_adr, use_container_width=True)

# ==============================================================================
# [12] Quick decision guide
# ==============================================================================
st.markdown("---")
with st.expander("Quick Decision Guide (Trigger Points)", expanded=False):
    _rows = [
        ("Peak 7/24-8/8",      "ADR < 510,000",        "Reduce OTA inventory / raise BAR"),
        ("Peak 7/24-8/8",      "OCC >= 97%",            "Prioritize direct / exclude deals"),
        ("Post-peak 8/9-8/16", "ADR < 470,000",        "Freeze BAR / adjust OTA exposure"),
        ("Shoulder 8/17-8/31", "OCC < 80% by 7/15",   "Breakfast pkg / expand intl OTA"),
        ("All periods",        "< 10 rooms remaining", "Switch to website priority"),
    ]
    _gdf = pd.DataFrame(_rows, columns=["Period", "Trigger", "Action"])
    st.dataframe(_gdf, use_container_width=True, hide_index=True)
    st.info("6/30: Jul OCC <70% - Add live / Increase OTA ad / Freeze BAR / Expand F&B Credit")
    st.info("7/15: Jul OCC <85% - Shoulder breakfast pkg / Expand intl OTA / Add promo")

# ==============================================================================
# [13] 일일 보고 (오전 / 오후) — 저장 & 조회   ← 총지배인 지시: 1일 2회 보고
# ==============================================================================
st.markdown("---")
st.markdown("### 일일 보고 (오전 / 오후)  ·  저장 & 조회")
st.caption("총지배인 지시: 매일 오전·오후 2회 보고. 순매출/순객실 픽업, 신규 ADR, OTB 관리선 대비 판정, 조치를 저장하고 언제든 일자로 조회.")

def _save_report(date_str, slot, payload):
    try:
        firestore.client().collection("daily_reports").document(date_str).set(
            {slot: payload, "last_updated": datetime.now().isoformat()}, merge=True
        )
        return True, ""
    except Exception as e:
        return False, str(e)

@st.cache_data(ttl=20)
def _load_report(date_str):
    try:
        doc = firestore.client().collection("daily_reports").document(date_str).get()
        return doc.to_dict() if doc.exists else {}
    except Exception:
        return {}

@st.cache_data(ttl=60)
def _list_report_dates():
    try:
        return sorted([d.id for d in firestore.client().collection("daily_reports").stream()], reverse=True)
    except Exception:
        return []

# ── 자동 계산 지표 (보고 항목) ──────────────────────────────────────────────
_now_rev = float(curr_df["REV"].sum()); _now_rn = float(curr_df["RMS"].sum())
_prev_rev = float(prev_df["REV"].sum()) if prev_df is not None else 0.0
_prev_rn  = float(prev_df["RMS"].sum()) if prev_df is not None else 0.0
_net_rev_pk = _now_rev - _prev_rev
_net_rn_pk  = _now_rn - _prev_rn
if res_today is not None and not res_today.empty and "Room_Revenue" in res_today.columns:
    _rn_sum = res_today["RN"].sum() if "RN" in res_today.columns else 0
    _new_adr = (res_today["Room_Revenue"].sum() / _rn_sum) if _rn_sum > 0 else 0
else:
    _new_adr = 0

_rc = st.columns(4)
_rc[0].metric("순매출 픽업(합계)", f"{_net_rev_pk/1e6:+.1f}M")
_rc[1].metric("순객실 픽업(합계)", f"{_net_rn_pk:+,.0f} RN")
_rc[2].metric("신규 예약 ADR", f"{_new_adr:,.0f}원" if _new_adr else "—")
_rc[3].metric("8월 관리선 판정", _lv)

_slot = st.radio("보고 시점", ["오전", "오후"], horizontal=True, key="rep_slot")
_prefill = ""
_existing = _load_report(curr_date)
if isinstance(_existing, dict) and _slot in _existing:
    _prefill = _existing[_slot].get("note", "")
_note = st.text_area(
    "특이사항 / 기준 미달 시 당일 조치 / 채널·상품 운영",
    value=_prefill, key="rep_note",
    placeholder="예: 8/17~21 저수요 구간 OTA 날짜한정 쿠폰 확대, 강한 날짜 할인 중단, 9/17~18 하드블럭 실입금 확인 …",
)
if st.button("이 시점 보고 저장", type="primary"):
    _payload = {
        "net_rev_pickup": _net_rev_pk, "net_rn_pickup": _net_rn_pk, "new_adr": _new_adr,
        "aug_otb": _otb_m[8], "aug_line": _line, "aug_gap": _gap, "aug_verdict": _lv,
        "sep_otb": _otb_m[9], "q3_otb": _q3_otb, "q3_pct": _q3_pct,
        "note": _note, "saved_at": datetime.now().isoformat(),
    }
    _ok, _err = _save_report(curr_date, _slot, _payload)
    if _ok:
        _load_report.clear(); _list_report_dates.clear()
        st.success(f"{curr_date} {_slot} 보고 저장 완료")
    else:
        st.error(f"저장 실패: {_err}")

st.markdown("#### 저장된 보고 조회 (일자별)")
_saved = _list_report_dates()
if _saved:
    _lookup = st.selectbox("조회할 일자", _saved, key="rep_lookup")
    _rep = _load_report(_lookup)
    for _s in ["오전", "오후"]:
        if isinstance(_rep, dict) and _s in _rep:
            _p = _rep[_s]
            st.markdown(
                f"**{_lookup} {_s}** — 순매출 {_p.get('net_rev_pickup',0)/1e6:+.1f}M · "
                f"순객실 {_p.get('net_rn_pickup',0):+,.0f}RN · 신규ADR {_p.get('new_adr',0):,.0f}원 · "
                f"8월판정 {_p.get('aug_verdict','—')} · 3분기 {_p.get('q3_pct',0)*100:.1f}%"
            )
            if _p.get("note"):
                st.caption(f"조치/메모: {_p['note']}")
        else:
            st.caption(f"{_lookup} {_s}: 미저장")
else:
    st.info("저장된 보고가 없습니다. 위에서 첫 보고를 저장하세요.  (Firestore 컬렉션: daily_reports)")

# ==============================================================================
# [14] 총지배인 지시사항 · 실행 원칙 · 보고 기준
# ==============================================================================
with st.expander("총지배인 지시사항 · 월별 실행 원칙 · 보고 기준", expanded=False):
    st.markdown("""
**공식 실행안 (금일부터 세일즈팀 적용)** — 월별 개별목표 추구가 아닌 3분기 통합목표 기준 역할 재조정 (목표 완화 아님).

**7월** — 잔여 재고 제한적. 무리한 할인 없이 **ADR 방어 중심**으로 마감.

**8월** — 7/31까지 **OTB 9.6억(1차 관리선)**, 최종 **13.11억** 목표. 수요 높은 날짜는 할인 없이 ADR 극대화, **8/17 이후 저수요 구간**은 날짜한정·2박·폐쇄형 B2B·환불불가 상품 집중.

**9월** — 3분기 성패 핵심월. 신규 예약 **ADR 33만~34만원 유지**, **개인 잔여 약 92% 순판매**, 주차별 Pick-up 관리. **단체 2.30억** 및 **9/17~18 하드블럭 180박**의 실입금·룸리스트·OTB 반영을 **매일 별도 추적**.

**매일 오전·오후 2회 보고 항목** — 순매출 Pick-up / 순객실 Pick-up / 신규 예약 ADR / 날짜별 잔여 재고 / 8·9월 OTB 관리선 대비 달성 / 기준 미달 시 당일 실행 조치.

**운영 원칙** — 강한 날짜의 불필요한 할인 중단, 약한 날짜에만 채널·상품 집중. 기준 미달 시 주의/위험/비상 단계별 조치 당일 적용, **비상 단계는 즉시 보고**.
""")

# ==============================================================================
# [15] 종합 요약 (하단)
# ==============================================================================
st.markdown("---")
st.markdown("## 종합 요약")

def _month_short(dfm, pfx):
    if dfm is None or dfm.empty:
        return 0.0
    g = dfm.groupby("DateStr").agg(REV=("REV", "sum")).reset_index()
    om = {r["DateStr"]: r["REV"] for _, r in g.iterrows()}
    return sum(max(0, DATE_PLAN[d]["rev"] - om.get(d, 0)) for d in DATE_PLAN if d.startswith(pfx))

_a_short = _month_short(curr_df8, "2026-08")
_s_short = _month_short(curr_df9, "2026-09")
_sum_l, _sum_r = st.columns(2)
with _sum_l:
    st.markdown(f"**3분기 통합 달성률: {_q3_pct*100:.1f}%**  (누적 {_q3_otb/1e8:.2f}억 / 목표 {Q3_TARGET_REV/1e8:.2f}억)")
    st.markdown(
        f"- 7월 {_otb_m[7]/1e8:.2f}억 (권장 {PLAN_LANDING[7]/1e8:.2f}) · "
        f"8월 {_otb_m[8]/1e8:.2f}억 (권장 {PLAN_LANDING[8]/1e8:.2f}) · "
        f"9월 {_otb_m[9]/1e8:.2f}억 (권장 {PLAN_LANDING[9]/1e8:.2f})"
    )
    st.markdown(f"- **8월 관리선 판정: {_lv}**  (오늘 관리선 {_line/1e8:.2f}억 · 갭 {_gap/1e8:+.2f}억){_floor_warn}")
with _sum_r:
    st.markdown("**일자별 권장목표 대비 부족분**")
    st.markdown(f"- 8월 총 부족: **{_a_short/1e8:.2f}억**")
    st.markdown(f"- 9월 총 부족: **{_s_short/1e8:.2f}억**")
    st.markdown(
        f"- 단체 진척: {SEP_STRATEGY['group_current_rev']/1e8:.2f}억 / 목표 "
        f"{SEP_STRATEGY['group_target_rev']/1e8:.2f}억 · 9/17~18 하드블럭 {SEP_STRATEGY['hardblock_confirmed_rn']}박 확정"
    )
    _today_saved = _load_report(curr_date)
    _slots_done = ", ".join([s for s in ["오전", "오후"] if isinstance(_today_saved, dict) and s in _today_saved]) or "미저장"
    st.markdown(f"- 오늘({curr_date}) 보고 상태: **{_slots_done}**")


st.caption(f"Last updated: {curr_date}  |  Amber Pure Hill Revenue Management")
