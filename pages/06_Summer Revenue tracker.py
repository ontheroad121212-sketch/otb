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
]

# 월별 예산 목표
MONTH_TARGETS = {
    7: {"rn": 3_720, "rev": 1_231_949_142},
    8: {"rn": 3_873, "rev": 1_388_376_999},
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
    return sorted(d7 | d8, reverse=True)


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


def combine_months(df7, df8) -> pd.DataFrame | None:
    parts = [df for df in [df7, df8] if df is not None and not df.empty]
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
prev_df7 = load_snapshot(prev_date, 7) if prev_date else None
prev_df8 = load_snapshot(prev_date, 8) if prev_date else None

curr_df = combine_months(curr_df7, curr_df8)
prev_df = combine_months(prev_df7, prev_df8)

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

summary_cols = st.columns(5)
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

pace_cols = st.columns(5)
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
mcol7, mcol8 = st.columns(2)

for m_num, mcol, df_m in [(7, mcol7, curr_df7), (8, mcol8, curr_df8)]:
    tgt = MONTH_TARGETS[m_num]
    with mcol:
        st.markdown(f"#### {m_num}월")
        if df_m is not None and not df_m.empty:
            rn = df_m["RMS"].sum()
            rev = df_m["REV"].sum()
            adr = rev / rn if rn > 0 else 0

            need_rn = max(tgt["rn"] - rn, 0)
            today = datetime.now()
            end_day = datetime(2026, m_num, 31)
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

st.caption(f"Last updated: {curr_date}  |  Amber Pure Hill Revenue Management")
