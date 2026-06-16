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
# [2] 구간 설정 (이전 대화 내용 기반)
# ==============================================================================
PERIODS = [
    {
        "id": "pre_peak",
        "label": "📅 Pre-Peak",
        "desc": "7/1~7/18",
        "start": "2026-07-01",
        "end": "2026-07-18",
        "target_adr": 355_000,
        "color": "#64748b",
        "bg": "#f8fafc",
    },
    {
        "id": "shoulder1",
        "label": "🟡 숄더 전반",
        "desc": "7/19~7/23",
        "start": "2026-07-19",
        "end": "2026-07-23",
        "target_adr": 340_000,
        "color": "#d97706",
        "bg": "#fffbeb",
    },
    {
        "id": "peak",
        "label": "🔴 극성수기",
        "desc": "7/24~8/8",
        "start": "2026-07-24",
        "end": "2026-08-08",
        "target_adr": 510_000,
        "color": "#dc2626",
        "bg": "#fef2f2",
    },
    {
        "id": "post_peak",
        "label": "🟠 성수기 후반",
        "desc": "8/9~8/16",
        "start": "2026-08-09",
        "end": "2026-08-16",
        "target_adr": 470_000,
        "color": "#ea580c",
        "bg": "#fff7ed",
    },
    {
        "id": "shoulder2",
        "label": "🟢 숄더 후반",
        "desc": "8/17~8/31",
        "start": "2026-08-17",
        "end": "2026-08-31",
        "target_adr": 310_000,
        "color": "#16a34a",
        "bg": "#f0fdf4",
    },
]

# 월별 예산 목표 (이전 대화 수치)
MONTH_TARGETS = {
    7: {"rn": 3_720, "rev": 1_231_949_142},
    8: {"rn": 3_873, "rev": 1_388_376_999},
}

# 총 객실수 (OCC 계산용 — 기존 코드에서 40실 기준 확인 필요, 일단 40)
TOTAL_ROOMS = 40

# ==============================================================================
# [3] Firebase 연결
# ==============================================================================
if not firebase_admin._apps:
    try:
        key_dict = dict(st.secrets["firebase"])
        cred = credentials.Certificate(key_dict)
        firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"🔥 Firebase 연결 실패: {e}")
        st.stop()

db = firestore.client()


# ==============================================================================
# [4] 데이터 로드 함수
# ==============================================================================

@st.cache_data(ttl=60)
def get_snapshot_dates_for_month(month_num: int) -> list:
    """해당 월에 저장된 스냅샷 날짜 목록 반환"""
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
    """7월·8월 스냅샷 날짜 합집합 (최신순)"""
    d7 = set(get_snapshot_dates_for_month(7))
    d8 = set(get_snapshot_dates_for_month(8))
    return sorted(d7 | d8, reverse=True)


def load_snapshot(date_str: str, month_num: int) -> pd.DataFrame | None:
    """특정 날짜·월의 스냅샷 로드"""
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
            # 필수 컬럼 보정
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
    """7월·8월 데이터프레임 합치기"""
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
    st.markdown("## ⚙️ Summer Tracker 설정")

    if not all_dates:
        st.warning("저장된 스냅샷 없음.\n메인 리포트에서 7·8월 데이터를 먼저 저장해 주세요.")
        st.stop()

    curr_date = st.selectbox("📅 기준 스냅샷 (오늘)", all_dates, index=0)

    prev_options = [d for d in all_dates if d < curr_date]
    prev_date = (
        st.selectbox("📅 비교 스냅샷 (전일/전주)", prev_options, index=0)
        if prev_options
        else None
    )
    if not prev_date:
        st.caption("비교할 이전 스냅샷이 없습니다.")

    st.divider()
    st.markdown("**🎯 구간별 ADR 목표**")
    for p in PERIODS:
        st.markdown(
            f"<span style='color:{p['color']};font-size:16px;'>■</span> "
            f"**{p['desc']}** {p['target_adr']:,}원",
            unsafe_allow_html=True,
        )
    st.divider()
    if st.button("🔄 캐시 새로고침"):
        get_all_snapshot_dates.clear()
        get_snapshot_dates_for_month.clear()
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

# ==============================================================================
# [7] 메인 화면
# ==============================================================================
st.title("🌊 Summer 2026 Revenue Tracker")
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


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────
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
st.markdown("### 📊 구간별 OTB 현황 요약")
period_results = []

summary_cols = st.columns(5)
for i, p in enumerate(PERIODS):
    c_df = period_df(curr_df, p)
    p_df = period_df(prev_df, p)
    cs = calc_summary(c_df)
    ps = calc_summary(p_df)

    pickup_rn = cs["rn"] - ps["rn"]
    pickup_rev = cs["rev"] - ps["rev"]
    # 픽업 ADR: 신규 유입 예약의 단가 (픽업 RN > 0 일 때만 의미 있음)
    pickup_adr = pickup_rev / pickup_rn if pickup_rn > 0 else None
    adr_vs_tgt = cs["adr"] - p["target_adr"]
    adr_color = "#16a34a" if adr_vs_tgt >= 0 else "#dc2626"
    # 픽업 ADR vs 목표
    pickup_adr_color = "#16a34a" if (pickup_adr or 0) >= p["target_adr"] else "#dc2626"

    period_results.append(
        {
            "period": p,
            "curr": cs,
            "prev": ps,
            "pickup_rn": pickup_rn,
            "pickup_rev": pickup_rev,
            "pickup_adr": pickup_adr,
            "adr_vs_tgt": adr_vs_tgt,
            "curr_df": c_df,
            "prev_df": p_df,
        }
    )

    with summary_cols[i]:
        pickup_sign = "+" if pickup_rn >= 0 else ""
        pickup_adr_str = f"{pickup_adr:,.0f}원" if pickup_adr is not None else "—"
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
                <div><b>📌 픽업 ADR</b> &nbsp;<span style="color:{pickup_adr_color};font-weight:900;">{pickup_adr_str}</span>
                    <span style="font-size:10px;color:#9ca3af;"> ← 신규유입 단가</span>
                </div>
                <div style="font-size:11px;color:#6b7280;">목표 {p['target_adr']:,}원</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

# ==============================================================================
# [9] 월별 OTB 총계 (7월·8월)
# ==============================================================================
st.markdown("---")
st.markdown("### 📈 월별 OTB vs 목표")
mcol7, mcol8 = st.columns(2)

for m_num, mcol, df_m in [(7, mcol7, curr_df7), (8, mcol8, curr_df8)]:
    tgt = MONTH_TARGETS[m_num]
    with mcol:
        st.markdown(f"#### {m_num}월")
        if df_m is not None and not df_m.empty:
            rn = df_m["RMS"].sum()
            rev = df_m["REV"].sum()
            adr = rev / rn if rn > 0 else 0

            # 필요 추가 픽업 계산
            need_rn = max(tgt["rn"] - rn, 0)
            today = datetime.now()
            # 7월은 7/31, 8월은 8/31까지 잔여 판매일
            end_day = datetime(2026, m_num, 31)
            days_left = max((end_day.date() - today.date()).days, 1)
            daily_need = need_rn / days_left

            rc1, rc2, rc3 = st.columns(3)
            rc1.metric("OTB RN", f"{rn:,.0f}", f"{rn - tgt['rn']:+,.0f} vs 목표")
            rc2.metric("OTB Rev", f"{rev/1e8:.2f}억", f"{(rev - tgt['rev'])/1e8:+.2f}억 vs 목표")
            rc3.metric("ADR", f"{adr:,.0f}원")

            rn_pct = min(rn / tgt["rn"], 1.0) if tgt["rn"] > 0 else 0
            rev_pct = min(rev / tgt["rev"], 1.0) if tgt["rev"] > 0 else 0
            st.progress(rn_pct, text=f"RN {rn_pct*100:.1f}% | 필요 추가 {need_rn:,.0f} RN (일평균 {daily_need:.1f} RN × {days_left}일)")
            st.progress(rev_pct, text=f"Revenue {rev_pct*100:.1f}%")
        else:
            st.info(f"{m_num}월 데이터 없음")

# ==============================================================================
# [10] 구간별 상세 탭
# ==============================================================================
st.markdown("---")
st.markdown("### 🗓️ 구간별 데일리 픽업 상세")

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

        # ── 픽업 테이블 조합 ──────────────────────────────────────────────
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
        # 픽업 ADR: 신규 유입 예약 단가 (Pick_RN > 0 인 날짜만)
        merged["Pick_ADR"] = np.where(
            merged["Pick_RN"] > 0,
            merged["Pick_REV"] / merged["Pick_RN"],
            np.nan
        )
        merged["ADR_vs_Tgt"] = merged["ADR"] - p["target_adr"]
        merged["Date"] = pd.to_datetime(merged["DateStr"])
        merged = merged.sort_values("Date")

        # ── 상단 메트릭 ───────────────────────────────────────────────────
        cs = pr["curr"]
        ps = pr["prev"]
        # 구간 전체 픽업 ADR
        period_pickup_adr = pr.get("pickup_adr")
        pickup_adr_delta = f"{period_pickup_adr - p['target_adr']:+,.0f} vs 목표" if period_pickup_adr else "신규유입 없음"

        m1, m2, m3, m4, m5, m6 = st.columns(6)
        m1.metric("OTB RN",      f"{cs['rn']:,.0f}",    f"{pr['pickup_rn']:+,.0f} 픽업")
        m2.metric("OTB Revenue",  f"{cs['rev']/1e8:.2f}억", f"{pr['pickup_rev']/1e6:+.1f}M 픽업")
        m3.metric("OTB ADR (종합)", f"{cs['adr']:,.0f}원", f"{pr['adr_vs_tgt']:+,.0f} vs 목표")
        m4.metric("📌 픽업 ADR (신규)", f"{period_pickup_adr:,.0f}원" if period_pickup_adr else "—", pickup_adr_delta)
        m5.metric("FIT ADR",
                  f"{(merged['FIT_REV'].sum() / merged['FIT_RMS'].sum()):,.0f}원" if merged['FIT_RMS'].sum() > 0 else "—")
        m6.metric("GRP ADR",
                  f"{(merged['GRP_REV'].sum() / merged['GRP_RMS'].sum()):,.0f}원" if merged['GRP_RMS'].sum() > 0 else "—")

        # ── ADR Alert ─────────────────────────────────────────────────────
        adr_diff = cs["adr"] - p["target_adr"]
        if cs["rn"] == 0:
            pass
        elif adr_diff >= 0:
            st.markdown(f'<div class="alert-green">✅ ADR <b>{cs["adr"]:,.0f}원</b> — 목표 대비 <b>+{adr_diff:,.0f}원</b> 상회</div>', unsafe_allow_html=True)
        elif adr_diff >= -20_000:
            st.markdown(f'<div class="alert-yellow">⚠️ ADR <b>{cs["adr"]:,.0f}원</b> — 목표 대비 <b>{adr_diff:,.0f}원</b> 미달 (BAR 점검 권고)</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="alert-red">🚨 ADR <b>{cs["adr"]:,.0f}원</b> — 목표 대비 <b>{adr_diff:,.0f}원</b> 미달 (즉시 가격 검토 필요)</div>', unsafe_allow_html=True)

        st.markdown("")

        # ── 데일리 픽업 테이블 ────────────────────────────────────────────
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
            "Pick_ADR": "📌 픽업 ADR (신규)",
            "ADR_vs_Tgt": f"OTB ADR vs 목표({p['target_adr']:,})",
        }
        display.rename(columns=col_names, inplace=True)

        # TOTAL 행 추가 — 빈 문자열 대신 np.nan 사용 (Styler 포맷 에러 방지)
        num_cols = [c for c in display.columns if c not in ["날짜", "요일", "OCC%"]]
        total_row = {c: np.nan for c in display.columns}
        total_row["날짜"] = "TOTAL"
        total_row["요일"] = ""
        for c in num_cols:
            try:
                total_row[c] = pd.to_numeric(display[c], errors="coerce").sum()
            except Exception:
                total_row[c] = np.nan
        # ADR total 재계산 (단순 합산은 의미 없으므로 가중평균으로 덮어씀)
        total_row["OTB ADR (종합)"] = cs["adr"]
        total_row[f"OTB ADR vs 목표({p['target_adr']:,})"] = adr_diff
        if "전일 ADR" in display.columns and ps["rn"] > 0:
            total_row["전일 ADR"] = ps["adr"]
        # 픽업 ADR total: 전체 픽업 REV / 전체 픽업 RN
        if pr.get("pickup_adr") is not None:
            total_row["📌 픽업 ADR (신규)"] = pr["pickup_adr"]
        else:
            total_row["📌 픽업 ADR (신규)"] = np.nan
        display = pd.concat([display, pd.DataFrame([total_row])], ignore_index=True)

        # 포맷 함수 — np.nan/비숫자 값에 안전하게 대응하는 callable 사용
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
                if val > 0:  return "color:#16a34a;font-weight:bold;"
                elif val < 0: return "color:#dc2626;font-weight:bold;"
            except Exception:
                pass
            return ""

        def color_adr(v):
            try:
                val = float(str(v).replace(",", ""))
                if val >= 0:  return "background:#f0fdf4;color:#16a34a;font-weight:bold;"
                elif val >= -20_000: return "background:#fffbeb;color:#d97706;font-weight:bold;"
                else:          return "background:#fef2f2;color:#dc2626;font-weight:bold;"
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

        def color_pickup_adr(v):
            """픽업 ADR: 목표 대비 색상"""
            try:
                if pd.isna(v): return ""
                val = float(str(v).replace(",", ""))
                if val >= p["target_adr"]: return "color:#16a34a;font-weight:bold;background:#f0fdf4;"
                elif val >= p["target_adr"] * 0.95: return "color:#d97706;font-weight:bold;background:#fffbeb;"
                else: return "color:#dc2626;font-weight:bold;background:#fef2f2;"
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

        # ── 차트 ─────────────────────────────────────────────────────────
        chart1, chart2 = st.columns(2)

        with chart1:
            fig_rn = go.Figure()
            if not p_df_period.empty:
                fig_rn.add_trace(
                    go.Scatter(
                        x=merged["DateStr"], y=merged["RMS_prev"],
                        name=f"전일 OTB ({prev_date})",
                        line=dict(color="#9ca3af", dash="dot", width=1.5),
                        mode="lines",
                    )
                )
            fig_rn.add_trace(
                go.Bar(
                    x=merged["DateStr"], y=merged["RMS"],
                    name="OTB RN",
                    marker_color=p["color"],
                    opacity=0.85,
                )
            )
            fig_rn.add_trace(
                go.Scatter(
                    x=merged["DateStr"], y=merged["Pick_RN"],
                    name="픽업 RN (증감)",
                    line=dict(color="#2563eb", width=2),
                    mode="lines+markers",
                    yaxis="y2",
                )
            )
            fig_rn.update_layout(
                title=f"일자별 OTB RN & 픽업 — {p['desc']}",
                height=320,
                xaxis=dict(tickangle=-45, tickfont=dict(size=10)),
                yaxis=dict(title="OTB RN"),
                yaxis2=dict(title="픽업 RN", overlaying="y", side="right", zeroline=True, zerolinecolor="#e5e7eb"),
                legend=dict(orientation="h", y=-0.25),
                bargap=0.3,
            )
            st.plotly_chart(fig_rn, use_container_width=True, key=f"rn_{p['id']}")

        with chart2:
            fig_adr = go.Figure()
            if not p_df_period.empty:
                fig_adr.add_trace(
                    go.Scatter(
                        x=merged["DateStr"], y=merged["ADR_prev"],
                        name=f"전일 ADR ({prev_date})",
                        line=dict(color="#9ca3af", dash="dot", width=1.5),
                        mode="lines",
                    )
                )
            fig_adr.add_trace(
                go.Scatter(
                    x=merged["DateStr"], y=merged["ADR"],
                    name="금일 ADR",
                    line=dict(color=p["color"], width=3),
                    mode="lines+markers",
                    marker=dict(size=7),
                )
            )
            fig_adr.add_hline(
                y=p["target_adr"],
                line_dash="dash",
                line_color="red",
                line_width=1.5,
                annotation_text=f"목표 ADR {p['target_adr']:,}",
                annotation_position="top left",
                annotation_font_color="red",
            )
            fig_adr.update_layout(
                title=f"일자별 ADR vs 목표 — {p['desc']}",
                height=320,
                xaxis=dict(tickangle=-45, tickfont=dict(size=10)),
                yaxis=dict(title="ADR (원)"),
                legend=dict(orientation="h", y=-0.25),
            )
            st.plotly_chart(fig_adr, use_container_width=True, key=f"adr_{p['id']}")

        # ── Revenue 흐름 ──────────────────────────────────────────────────
        fig_rev = go.Figure()
        if not p_df_period.empty:
            fig_rev.add_trace(
                go.Bar(
                    x=merged["DateStr"], y=merged["REV_prev"],
                    name="전일 Revenue",
                    marker_color="#d1d5db",
                    opacity=0.6,
                )
            )
        fig_rev.add_trace(
            go.Bar(
                x=merged["DateStr"], y=merged["REV"],
                name="금일 OTB Revenue",
                marker_color=p["color"],
                opacity=0.85,
            )
        )
        fig_rev.add_trace(
            go.Scatter(
                x=merged["DateStr"], y=merged["Pick_REV"],
                name="픽업 Revenue",
                line=dict(color="#7c3aed", width=2),
                mode="lines+markers",
                yaxis="y2",
            )
        )
        fig_rev.update_layout(
            title=f"일자별 OTB Revenue & 픽업 — {p['desc']}",
            height=300,
            barmode="overlay",
            xaxis=dict(tickangle=-45, tickfont=dict(size=10)),
            yaxis=dict(title="Revenue (원)"),
            yaxis2=dict(title="픽업 Revenue", overlaying="y", side="right"),
            legend=dict(orientation="h", y=-0.28),
            bargap=0.3,
        )
        st.plotly_chart(fig_rev, use_container_width=True, key=f"rev_{p['id']}")


# ==============================================================================
# [11] 전체 구간 통합 비교 차트
# ==============================================================================
st.markdown("---")
st.markdown("### 🔭 전체 구간 통합 뷰")

col_a, col_b = st.columns(2)

summary_df = pd.DataFrame(
    [
        {
            "구간": f"{pr['period']['label']}\n{pr['period']['desc']}",
            "desc_short": pr["period"]["desc"],
            "OTB RN": pr["curr"]["rn"],
            "픽업 RN": pr["pickup_rn"],
            "ADR": pr["curr"]["adr"],
            "목표 ADR": pr["period"]["target_adr"],
            "ADR Gap": pr["adr_vs_tgt"],
            "color": pr["period"]["color"],
        }
        for pr in period_results
    ]
)

with col_a:
    fig_s1 = go.Figure()
    fig_s1.add_trace(
        go.Bar(
            x=summary_df["desc_short"],
            y=summary_df["OTB RN"],
            name="OTB RN",
            marker_color=summary_df["color"].tolist(),
            text=summary_df["OTB RN"].apply(lambda v: f"{v:,.0f}"),
            textposition="outside",
        )
    )
    fig_s1.update_layout(title="구간별 OTB RN", height=350, showlegend=False)
    st.plotly_chart(fig_s1, use_container_width=True, key="s_rn")

with col_b:
    fig_s2 = go.Figure()
    fig_s2.add_trace(
        go.Bar(
            x=summary_df["desc_short"],
            y=summary_df["ADR"],
            name="실제 ADR",
            marker_color=summary_df["color"].tolist(),
            text=summary_df["ADR"].apply(lambda v: f"{v:,.0f}"),
            textposition="outside",
        )
    )
    fig_s2.add_trace(
        go.Scatter(
            x=summary_df["desc_short"],
            y=summary_df["목표 ADR"],
            name="목표 ADR",
            mode="markers+text",
            marker=dict(color="red", size=14, symbol="line-ew-open", line=dict(width=3)),
            text=summary_df["목표 ADR"].apply(lambda v: f"{v:,.0f}"),
            textposition="top center",
            textfont=dict(color="red", size=10),
        )
    )
    fig_s2.update_layout(
        title="구간별 ADR vs 목표 ADR",
        height=350,
        legend=dict(orientation="h", y=-0.15),
    )
    st.plotly_chart(fig_s2, use_container_width=True, key="s_adr")

# ── ADR Gap 게이지 ─────────────────────────────────────────────────────────
st.markdown("#### ADR 달성 상태 (목표 대비)")
gap_cols = st.columns(5)
for i, (pr, gc) in enumerate(zip(period_results, gap_cols)):
    gap = pr["adr_vs_tgt"]
    adr = pr["curr"]["adr"]
    tgt = pr["period"]["target_adr"]
    color = "#16a34a" if gap >= 0 else ("#d97706" if gap >= -20_000 else "#dc2626")
    label = "✅ 달성" if gap >= 0 else ("⚠️ 주의" if gap >= -20_000 else "🚨 미달")
    with gc:
        st.markdown(
            f"""
            <div style="text-align:center;padding:10px;border-radius:8px;
                        background:{pr['period']['bg']};border:1px solid {pr['period']['color']}20;">
                <div style="font-size:11px;color:#6b7280;">{pr['period']['desc']}</div>
                <div style="font-size:20px;font-weight:900;color:{color};">{'+' if gap>=0 else ''}{gap:,.0f}</div>
                <div style="font-size:11px;color:{color};">{label}</div>
                <div style="font-size:10px;color:#9ca3af;">{adr:,.0f} / 목표 {tgt:,}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

# ==============================================================================
# [12] 빠른 의사결정 체크리스트
# ==============================================================================
st.markdown("---")
with st.expander("⚡ 빠른 의사결정 가이드 (Trigger Point 기반)", expanded=False):
    st.markdown("""
    | 구간 | 체크 지표 | 액션 |
    |------|-----------|------|
    | 극성수기 7/24~8/8 | ADR < 430,000원 | OTA 재고 축소, BAR 상향 검토 |
    | 극성수기 7/24~8/8 | OCC 85% 이상 날짜 | 홈페이지 우선, 라이브/공구 제외 |
    | 성수기 후반 8/9~8/16 | ADR < 560,000원 | BAR 동결, OTA 노출 조정 |
    | 숄더 8/17~8/31 | OCC < 65% (7/15 기준) | 조식 포함 패키지, 해외 OTA 확대 |
    | 전체 | 잔여 10실 이하 날짜 | 홈페이지 우선 전환 |

    **6/30 Trigger**: 7월 OCC < 70% → 라이브 1회 추가 / OTA 광고 증액 / BAR 동결 / F&B Credit 확대
    **7/15 Trigger**: 7월 OCC < 85% → 숄더 조식 포함 / 해외 OTA Visibility 확대 / 프로모션 추가
    """)

st.caption(f"Last updated: {curr_date}  |  Amber Pure Hill Revenue Management")
