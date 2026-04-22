import html
import json
import os
import sys
import time
import textwrap
from pathlib import Path
import textwrap

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

DATABASE_URL = os.getenv("DATABASE_URL", "http://database:8000")
CONTROL_FILE = Path(os.getenv("CONTROL_FILE", "/control/sim_control.json"))
MARKET_REPO_ROOT = Path(os.getenv("MARKET_REPO_ROOT", "/repos/market_operator"))

SIM_SEASON_ENV = os.getenv("SIM_SEASON", "").strip().lower() or None
TARIFF_TARGET_YEAR = int(os.getenv("TARIFF_TARGET_YEAR", "2025"))
TARIFF_AGG = os.getenv("TARIFF_AGG", "median").strip().lower()

sys.path.insert(0, str(MARKET_REPO_ROOT))
from tariff import load_tou_profile, load_fit_profile, normalize_season  # noqa: E402


st.set_page_config(
    page_title="Microgrid Final Dashboard",
    page_icon="⚡",
    layout="wide",
)

st.set_option("client.toolbarMode", "minimal")

st.markdown(
    """
    <style>
    .stApp {
        background-color: #E7EBF0;
    }

    section[data-testid="stSidebar"] {
        background: #DCE3EA;
        border-right: 1px solid #C7D0DA;
    }

    .block-container {
        max-width: 1450px;
        padding-top: 1.2rem;
        padding-bottom: 2rem;
    }

    .metric-card {
        background: #F2F5F8;
        border: 1px solid #D6DCE3;
        border-radius: 16px;
        padding: 16px 18px 14px 18px;
        min-height: 132px;
        overflow: visible;
        margin-bottom: 0.55rem;
        display: flex;
        flex-direction: column;
        justify-content: center;
    }

    .metric-header {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 10px;
    }

    .metric-label-wrap {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 7px;
        min-width: 0;
        flex: 1;
        text-align: center;
    }

    .metric-label {
        color: #5B6675;
        font-size: 1.02rem;
        font-weight: 600;
        line-height: 1.35;
        text-align: center;
    }

    .metric-value {
        color: #1F2937;
        font-size: 2.25rem;
        font-weight: 700;
        line-height: 1.12;
        margin-top: 0.9rem;
        word-break: normal;
        overflow-wrap: normal;
        text-align: center;
    }

    details.metric-info {
        position: relative;
        flex-shrink: 0;
        overflow: visible;
    }

    details.metric-info > summary {
        list-style: none;
        width: 18px;
        height: 18px;
        border-radius: 50%;
        background: #D5DAE0;
        color: #6B7280;
        font-size: 11px;
        font-weight: 700;
        display: flex;
        align-items: center;
        justify-content: center;
        cursor: pointer;
        line-height: 1;
        user-select: none;
    }

    details.metric-info > summary::-webkit-details-marker {
        display: none;
    }

    details.metric-info > summary::marker {
        content: "";
    }

    .metric-help-box {
        position: absolute;
        right: 0;
        top: 24px;
        width: 245px;
        background: #FFFFFF;
        border: 1px solid #D6DCE3;
        border-radius: 10px;
        padding: 9px 11px;
        box-shadow: 0 10px 22px rgba(0, 0, 0, 0.12);
        color: #4B5563;
        font-size: 0.88rem;
        line-height: 1.35;
        z-index: 9999;
        text-align: left;
    }

    .subheading-text {
        color: #243142;
        font-size: 1.22rem;
        font-weight: 700;
        margin-top: 0.45rem;
        margin-bottom: 0.15rem;
    }

    .household-note {
        color: #6B7280;
        font-size: 0.95rem;
        margin-top: 0.25rem;
        margin-bottom: 0.8rem;
    }

    .financial-linked-row {
        display: flex;
        gap: 0;
        width: 100%;
        background: #F2F5F8;
        border: 1px solid #D6DCE3;
        border-radius: 20px;
        overflow: hidden;
        margin-bottom: 1rem;
    }

    .financial-linked-side {
        width: 220px;
        min-width: 220px;
        max-width: 220px;
        border-right: 1px solid #D6DCE3;
        display: flex;
        flex-direction: column;
        background: #F2F5F8;
    }

    .financial-linked-subcard {
        flex: 1;
        min-height: 148px;
        display: flex;
        flex-direction: column;
        justify-content: center;
        padding: 18px 16px;
        background: #F2F5F8;
    }

    .financial-linked-subcard + .financial-linked-subcard {
        border-top: 1px solid #D6DCE3;
    }

    .financial-linked-main {
        flex: 1;
        min-height: 296px;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        padding: 24px 24px;
        background: #F2F5F8;
        text-align: center;
    }

    .financial-linked-label-wrap {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 7px;
    }

    .financial-linked-label {
        color: #5B6675;
        font-size: 1.04rem;
        font-weight: 600;
        line-height: 1.35;
        text-align: center;
    }

    .financial-linked-subvalue {
        color: #1F2937;
        font-size: 2.05rem;
        font-weight: 700;
        line-height: 1.15;
        margin-top: 0.75rem;
        text-align: center;
    }

    .financial-linked-main-label {
        color: #5B6675;
        font-size: 1.22rem;
        font-weight: 600;
        line-height: 1.35;
        text-align: center;
    }

    .financial-linked-main-value {
    color: #1F2937;
    font-size: 3.6rem;
    font-weight: 700;
    line-height: 1.08;
    margin-top: 1rem;
    text-align: center;
}


    </style>
    """,
    unsafe_allow_html=True,
)


def read_control() -> dict:
    default = {
        "pause_simulation": False,
        "tick_seconds": 1.0,
    }

    if not CONTROL_FILE.exists():
        return default

    try:
        with open(CONTROL_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        default.update(data)
    except Exception:
        pass

    return default


def write_control(data: dict):
    CONTROL_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(data)
    payload["updated_at"] = time.time()
    tmp_file = CONTROL_FILE.with_suffix(CONTROL_FILE.suffix + ".tmp")
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_file, CONTROL_FILE)


def make_info_html(help_text: str) -> str:
    if not help_text:
        return ""
    help_text_html = html.escape(help_text)
    return (
        f'<details class="metric-info">'
        f'<summary>!</summary>'
        f'<div class="metric-help-box">{help_text_html}</div>'
        f'</details>'
    )


def render_metric_card(label: str, value: str, help_text: str = ""):
    label_html = html.escape(label)
    value_html = html.escape(value)
    help_html = make_info_html(help_text)

    card_html = textwrap.dedent(f"""
    <div class="metric-card">
        <div class="metric-header">
            <div class="metric-label-wrap">
                <div class="metric-label">{label_html}</div>
                {help_html}
            </div>
        </div>
        <div class="metric-value">{value_html}</div>
    </div>
    """).strip()
    st.markdown(card_html, unsafe_allow_html=True)


def render_financial_linked_row(
    title: str,
    value: str,
    help_text: str,
    side_columns: list[dict],
    side_column_width_px: int = 220,
):
    title_html = html.escape(title)
    value_html = html.escape(value)

    parts = []
    for col in side_columns:
        top_label_html = html.escape(col["top_label"])
        top_value_html = html.escape(col["top_value"])
        bottom_label_html = html.escape(col["bottom_label"])
        bottom_value_html = html.escape(col["bottom_value"])

        parts.append(
            f"""
<div class="financial-linked-side" style="width:{side_column_width_px}px; min-width:{side_column_width_px}px; max-width:{side_column_width_px}px;">
    <div class="financial-linked-subcard">
        <div class="financial-linked-label-wrap">
            <div class="financial-linked-label">{top_label_html}</div>
            {make_info_html(col.get("top_help", ""))}
        </div>
        <div class="financial-linked-subvalue">{top_value_html}</div>
    </div>
    <div class="financial-linked-subcard">
        <div class="financial-linked-label-wrap">
            <div class="financial-linked-label">{bottom_label_html}</div>
            {make_info_html(col.get("bottom_help", ""))}
        </div>
        <div class="financial-linked-subvalue">{bottom_value_html}</div>
    </div>
</div>
""".strip()
        )

    side_columns_html = "".join(parts)

    html_block = f"""
<div class="financial-linked-row">
    {side_columns_html}
    <div class="financial-linked-main">
        <div class="financial-linked-label-wrap">
            <div class="financial-linked-main-label">{title_html}</div>
            {make_info_html(help_text)}
        </div>
        <div class="financial-linked-main-value">{value_html}</div>
    </div>
</div>
""".strip()

    st.markdown(html_block, unsafe_allow_html=True)

def section_header(title: str):
    st.markdown(f"## {title}")


def subsection_title(title: str):
    st.markdown(
        f"<div class='subheading-text'>{html.escape(title)}</div>",
        unsafe_allow_html=True,
    )


def base_figure(y_title: str, height: int = 350):
    fig = go.Figure()
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#F5F7FA",
        margin=dict(l=20, r=20, t=20, b=70),
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.20,
            xanchor="left",
            x=0.0,
            title="",
            bgcolor="rgba(0,0,0,0)",
            font=dict(size=13),
        ),
        font=dict(color="#243142", size=14),
        hovermode="x unified",
        height=height,
    )
    fig.update_xaxes(
        title="Simulation Slot",
        showgrid=True,
        gridcolor="#D7DEE7",
        zeroline=False,
        linecolor="#AAB5C3",
        tickfont=dict(size=12),
        title_font=dict(size=15),
    )
    fig.update_yaxes(
        title=y_title,
        showgrid=True,
        gridcolor="#D7DEE7",
        zeroline=False,
        linecolor="#AAB5C3",
        tickfont=dict(size=12),
        title_font=dict(size=15),
    )
    return fig


def add_line(fig, x, y, name, color, width=1.6):
    fig.add_trace(
        go.Scatter(
            x=x,
            y=y,
            mode="lines",
            name=name,
            line=dict(width=width, color=color),
        )
    )


@st.cache_data(ttl=0.2, show_spinner=False)
def load_state():
    r = requests.get(f"{DATABASE_URL}/state", timeout=5)
    r.raise_for_status()
    return r.json()


@st.cache_data(ttl=0.2, show_spinner=False)
def load_summary() -> pd.DataFrame:
    r = requests.get(f"{DATABASE_URL}/summary", timeout=5)
    r.raise_for_status()
    data = r.json()
    return pd.DataFrame(data) if data else pd.DataFrame()


@st.cache_data(ttl=1, show_spinner=False)
def load_household_ids():
    r = requests.get(f"{DATABASE_URL}/households", timeout=5)
    r.raise_for_status()
    return r.json()


@st.cache_data(ttl=1, show_spinner=False)
def load_household_history(h_id: str) -> pd.DataFrame:
    r = requests.get(f"{DATABASE_URL}/households/{h_id}", timeout=5)
    r.raise_for_status()
    data = r.json()
    return pd.DataFrame(data) if data else pd.DataFrame()


@st.cache_data(ttl=1, show_spinner=False)
def load_all_household_history() -> pd.DataFrame:
    ids = load_household_ids()
    frames = []

    for h_id in ids:
        df = load_household_history(h_id)
        if not df.empty:
            frames.append(df)

    if not frames:
        return pd.DataFrame()

    return pd.concat(frames, ignore_index=True)


@st.cache_data(ttl=3600, show_spinner=False)
def load_shared_tariff_profiles(season: str | None, target_year: int, agg: str):
    season = normalize_season(season)

    tou_profile = load_tou_profile(
        target_year=target_year,
        season=season,
        agg=agg,
    )
    fit_profile = load_fit_profile(
        target_year=target_year,
        season=season,
        agg=agg,
    )

    return tou_profile, fit_profile, season


def compute_without_p2p_breakdown(
    summary_df: pd.DataFrame,
    tou_profile,
    fit_profile,
):
    if summary_df.empty:
        return {
            "without_grid_buy_cost_gbp": 0.0,
            "without_grid_sell_revenue_gbp": 0.0,
            "without_net_cost_gbp": 0.0,
            "total_avoided_external_spread_gbp": 0.0,
        }

    df = summary_df.copy()
    df["simulated_datetime"] = pd.to_datetime(df["simulated_datetime"], errors="coerce")
    df = df.dropna(subset=["simulated_datetime"]).copy()

    df["hour"] = df["simulated_datetime"].dt.hour
    df["shared_grid_buy_price_gbp_per_kwh"] = df["hour"].apply(
        lambda h: float(tou_profile.get_price(int(h)))
    )
    df["shared_grid_sell_price_gbp_per_kwh"] = df["hour"].apply(
        lambda h: float(fit_profile.get_price(int(h)))
    )

    df["extra_grid_buy_cost_without_p2p_gbp"] = (
        df["p2p_trade_kwh"].astype(float) * df["shared_grid_buy_price_gbp_per_kwh"].astype(float)
    )
    df["extra_grid_sell_revenue_without_p2p_gbp"] = (
        df["p2p_trade_kwh"].astype(float) * df["shared_grid_sell_price_gbp_per_kwh"].astype(float)
    )
    df["avoided_external_spread_gbp"] = (
        df["extra_grid_buy_cost_without_p2p_gbp"] - df["extra_grid_sell_revenue_without_p2p_gbp"]
    )

    actual_grid_buy_cost = float(df["grid_import_cost_gbp"].sum())
    actual_grid_sell_revenue = float(df["grid_export_revenue_gbp"].sum())
    total_penalties = float(df["balancing_penalties_gbp"].sum())

    without_grid_buy_cost = actual_grid_buy_cost + float(df["extra_grid_buy_cost_without_p2p_gbp"].sum())
    without_grid_sell_revenue = actual_grid_sell_revenue + float(df["extra_grid_sell_revenue_without_p2p_gbp"].sum())
    without_net_cost = without_grid_buy_cost - without_grid_sell_revenue + total_penalties

    return {
        "without_grid_buy_cost_gbp": without_grid_buy_cost,
        "without_grid_sell_revenue_gbp": without_grid_sell_revenue,
        "without_net_cost_gbp": without_net_cost,
        "total_avoided_external_spread_gbp": float(df["avoided_external_spread_gbp"].sum()),
    }


def estimate_household_settlement(
    h_df: pd.DataFrame,
    summary_df: pd.DataFrame,
    tou_profile,
    fit_profile,
):
    if h_df.empty:
        return h_df.copy(), {}

    merge_cols = [
        "slot",
        "p2p_trade_kwh",
        "grid_bought_kwh",
        "grid_export_kwh",
        "avg_total_p2p_price_gbp_per_kwh",
    ]
    slot_df = summary_df[merge_cols].copy()

    df = h_df.merge(slot_df, on="slot", how="left")
    df["simulated_datetime"] = pd.to_datetime(df["simulated_datetime"], errors="coerce")
    df = df.dropna(subset=["simulated_datetime"]).copy()

    df["hour"] = df["simulated_datetime"].dt.hour
    df["shared_grid_buy_price_gbp_per_kwh"] = df["hour"].apply(
        lambda h: float(tou_profile.get_price(int(h)))
    )
    df["shared_grid_sell_price_gbp_per_kwh"] = df["hour"].apply(
        lambda h: float(fit_profile.get_price(int(h)))
    )

    df["p2p_trade_kwh"] = pd.to_numeric(df["p2p_trade_kwh"], errors="coerce").fillna(0.0)
    df["grid_bought_kwh"] = pd.to_numeric(df["grid_bought_kwh"], errors="coerce").fillna(0.0)
    df["grid_export_kwh"] = pd.to_numeric(df["grid_export_kwh"], errors="coerce").fillna(0.0)
    df["avg_total_p2p_price_gbp_per_kwh"] = pd.to_numeric(
        df["avg_total_p2p_price_gbp_per_kwh"], errors="coerce"
    ).fillna(0.0)

    df["actual_buy_kwh"] = pd.to_numeric(df["actual_buy_kwh"], errors="coerce").fillna(0.0)
    df["actual_sell_kwh"] = pd.to_numeric(df["actual_sell_kwh"], errors="coerce").fillna(0.0)

    buyer_den = df["p2p_trade_kwh"] + df["grid_bought_kwh"]
    seller_den = df["p2p_trade_kwh"] + df["grid_export_kwh"]

    df["p2p_buy_share"] = 0.0
    df["p2p_sell_share"] = 0.0

    buy_mask = buyer_den > 0
    sell_mask = seller_den > 0

    df.loc[buy_mask, "p2p_buy_share"] = (
        df.loc[buy_mask, "p2p_trade_kwh"] / buyer_den[buy_mask]
    ).clip(lower=0.0, upper=1.0)

    df.loc[sell_mask, "p2p_sell_share"] = (
        df.loc[sell_mask, "p2p_trade_kwh"] / seller_den[sell_mask]
    ).clip(lower=0.0, upper=1.0)

    df["p2p_buy_kwh"] = df["actual_buy_kwh"] * df["p2p_buy_share"]
    df["grid_buy_kwh"] = df["actual_buy_kwh"] - df["p2p_buy_kwh"]

    df["p2p_sell_kwh"] = df["actual_sell_kwh"] * df["p2p_sell_share"]
    df["grid_sell_kwh"] = df["actual_sell_kwh"] - df["p2p_sell_kwh"]

    df["grid_buy_cost_gbp"] = df["grid_buy_kwh"] * df["shared_grid_buy_price_gbp_per_kwh"]
    df["grid_sell_revenue_gbp"] = df["grid_sell_kwh"] * df["shared_grid_sell_price_gbp_per_kwh"]
    df["p2p_buy_cost_gbp"] = df["p2p_buy_kwh"] * df["avg_total_p2p_price_gbp_per_kwh"]
    df["p2p_sell_revenue_gbp"] = df["p2p_sell_kwh"] * df["avg_total_p2p_price_gbp_per_kwh"]

    totals = {
        "grid_buy_kwh": float(df["grid_buy_kwh"].sum()),
        "grid_buy_cost_gbp": float(df["grid_buy_cost_gbp"].sum()),
        "grid_sell_kwh": float(df["grid_sell_kwh"].sum()),
        "grid_sell_revenue_gbp": float(df["grid_sell_revenue_gbp"].sum()),
        "p2p_buy_kwh": float(df["p2p_buy_kwh"].sum()),
        "p2p_buy_cost_gbp": float(df["p2p_buy_cost_gbp"].sum()),
        "p2p_sell_kwh": float(df["p2p_sell_kwh"].sum()),
        "p2p_sell_revenue_gbp": float(df["p2p_sell_revenue_gbp"].sum()),
    }

    return df, totals


if "pause_dashboard_updates" not in st.session_state:
    st.session_state.pause_dashboard_updates = False

if "dashboard_refresh_seconds" not in st.session_state:
    st.session_state.dashboard_refresh_seconds = 1.0

current_control = read_control()
current_slots_per_second = 1.0 / max(float(current_control.get("tick_seconds", 1.0)), 0.001)
active_tick_seconds = max(float(current_control.get("tick_seconds", 1.0)), 0.001)
active_slots_per_second = 1.0 / active_tick_seconds

with st.sidebar:
    st.markdown("## Dashboard Controls")

    st.session_state.pause_dashboard_updates = st.checkbox(
        "Pause dashboard updates",
        value=st.session_state.pause_dashboard_updates,
    )

    st.session_state.dashboard_refresh_seconds = st.slider(
        "Dashboard refresh interval (seconds)",
        min_value=0.2,
        max_value=10.0,
        value=float(st.session_state.dashboard_refresh_seconds),
        step=0.1,
    )

    if st.button("Refresh now", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.markdown("---")
    st.markdown("## Simulation Controls")
    st.caption(
        f"Current active control: {'paused' if bool(current_control.get('pause_simulation', False)) else 'running'} · "
        f"{active_slots_per_second:.2f} slots/s"
    )

    with st.form("simulation_controls_form", clear_on_submit=False):
        pause_simulation = st.checkbox(
            "Pause simulation",
            value=bool(current_control.get("pause_simulation", False)),
        )

        slots_per_second = st.slider(
            "Simulation speed (slots per second)",
            min_value=0.1,
            max_value=6.0,
            value=min(float(current_slots_per_second), 6.0),
            step=0.1,
        )

        apply_controls = st.form_submit_button(
            "Apply simulation controls",
            use_container_width=True,
        )

    if apply_controls:
        tick_seconds = 1.0 / max(slots_per_second, 0.1)
        write_control(
            {
                "pause_simulation": pause_simulation,
                "tick_seconds": tick_seconds,
            }
        )
        time.sleep(0.05)
        st.cache_data.clear()
        st.success(
            f"Applied: pause_simulation={pause_simulation}, "
            f"tick_seconds={tick_seconds:.3f} ({slots_per_second:.2f} slots/s)"
        )
        st.rerun()

if not st.session_state.pause_dashboard_updates:
    st_autorefresh(
        interval=int(st.session_state.dashboard_refresh_seconds * 1000),
        key=f"dashboard_refresh_{st.session_state.dashboard_refresh_seconds}",
    )

st.title("Microgrid Final Dashboard")

summary_df = load_summary()
if summary_df.empty:
    st.warning("No summary data in the database yet.")
    st.stop()

state = load_state()
summary_df = summary_df.sort_values(by=["slot", "id"]).reset_index(drop=True)

needed_cols = [
    "predicted_demand_kwh",
    "actual_demand_kwh",
    "grid_bought_kwh",
    "p2p_trade_kwh",
    "trade_pct",
    "planned_market_p2p_kwh",
    "planned_market_p2p_value_gbp",
    "avg_market_p2p_price_gbp_per_kwh",
    "balancing_internal_p2p_kwh",
    "balancing_internal_p2p_value_gbp",
    "total_internal_p2p_kwh",
    "total_internal_p2p_value_gbp",
    "avg_total_p2p_price_gbp_per_kwh",
    "grid_import_kwh",
    "grid_export_kwh",
    "grid_import_cost_gbp",
    "grid_export_revenue_gbp",
    "avg_grid_import_price_gbp_per_kwh",
    "avg_grid_export_price_gbp_per_kwh",
    "balancing_penalties_gbp",
    "net_external_cost_gbp",
]

for col in needed_cols:
    if col not in summary_df.columns:
        summary_df[col] = 0.0

latest = summary_df.iloc[-1]
household_ids = load_household_ids()

tou_profile, fit_profile, shared_season = load_shared_tariff_profiles(
    season=SIM_SEASON_ENV,
    target_year=TARIFF_TARGET_YEAR,
    agg=TARIFF_AGG,
)

without_breakdown = compute_without_p2p_breakdown(
    summary_df,
    tou_profile,
    fit_profile,
)

total_grid_import_cost_gbp = float(summary_df["grid_import_cost_gbp"].sum())
total_grid_export_revenue_gbp = float(summary_df["grid_export_revenue_gbp"].sum())
total_grid_import_kwh = float(summary_df["grid_import_kwh"].sum())
total_grid_export_kwh = float(summary_df["grid_export_kwh"].sum())
total_internal_p2p_value_gbp = float(summary_df["total_internal_p2p_value_gbp"].sum())
total_internal_p2p_kwh = float(summary_df["p2p_trade_kwh"].sum())

total_p2p_buy_cost_gbp = total_internal_p2p_value_gbp
total_p2p_sell_revenue_gbp = total_internal_p2p_value_gbp

household_cost_with_p2p = float(summary_df["net_external_cost_gbp"].sum())
household_cost_without_p2p = float(without_breakdown["without_net_cost_gbp"])
total_savings_from_p2p = float(without_breakdown["total_avoided_external_spread_gbp"])
avg_saving_per_household = (
    total_savings_from_p2p / len(household_ids)
    if household_ids else 0.0
)

avg_grid_buy_price_whole_run = (
    total_grid_import_cost_gbp / total_grid_import_kwh
    if total_grid_import_kwh > 0 else 0.0
)
avg_grid_sell_price_whole_run = (
    total_grid_export_revenue_gbp / total_grid_export_kwh
    if total_grid_export_kwh > 0 else 0.0
)
avg_total_p2p_price_whole_run = (
    total_internal_p2p_value_gbp / total_internal_p2p_kwh
    if total_internal_p2p_kwh > 0 else 0.0
)

section_header("Simulation Status")
c1, c2, c3 = st.columns(3)
with c1:
    render_metric_card("Simulation Slot", f"{int(state['slot'])}", "Current slot number in the replayed simulation.")
with c2:
    render_metric_card("Simulated Datetime", str(state["simulated_datetime"]), "Historical datetime represented by the current slot.")
with c3:
    render_metric_card("Run Status", str(state["status"]).capitalize(), "Shows whether the simulation is running or completed.")

section_header("Latest Slot Energy Metrics")
e1, e2, e3 = st.columns(3)
e4, e5, e6 = st.columns(3)

with e1:
    render_metric_card(
        "Forecast Demand",
        f"{latest['predicted_demand_kwh']:.2f} kWh",
        "Predicted community electricity demand for the latest slot."
    )

with e2:
    render_metric_card(
        "Actual Demand",
        f"{latest['actual_demand_kwh']:.2f} kWh",
        "Measured community electricity demand for the latest slot."
    )

with e3:
    render_metric_card(
        "Energy Bought from Grid",
        f"{float(latest['grid_import_kwh']):.2f} kWh",
        "Total electricity bought from the grid in the latest slot."
    )

with e4:
    render_metric_card(
        "Energy Sold to Grid",
        f"{float(latest['grid_export_kwh']):.2f} kWh",
        "Total electricity sold to the grid in the latest slot."
    )

with e5:
    render_metric_card(
        "P2P Energy Traded",
        f"{latest['p2p_trade_kwh']:.2f} kWh",
        "Total internal matched electricity in the latest slot across both market and balancing."
    )

with e6:
    render_metric_card(
        "P2P Share of Supply",
        f"{latest['trade_pct']:.1f}%",
        "The share of supplied electricity in the latest slot that came through internal matching rather than grid buying."
    )

section_header("Latest Slot Money Snapshot")
m1, m2, m3 = st.columns(3)

latest_total_p2p_value_gbp = float(latest.get("total_internal_p2p_value_gbp", 0.0))

with m1:
    render_metric_card(
        "Cost of Buying from Grid",
        f"£{latest['grid_import_cost_gbp']:.2f}",
        "How much the community paid the grid in the latest slot."
    )

with m2:
    render_metric_card(
        "Revenue from Selling to Grid",
        f"£{latest['grid_export_revenue_gbp']:.2f}",
        "How much the community earned by exporting surplus electricity to the grid in the latest slot."
    )

with m3:
    render_metric_card(
        "P2P Money Exchanged",
        f"£{latest_total_p2p_value_gbp:.2f}",
        "Money exchanged in total internal household-to-household matching in the latest slot, including both market-cleared P2P and balancing-stage internal matching."
    )

section_header("Whole-Run Energy Summary")
wr1, wr2, wr3, wr4 = st.columns(4)

overall_share = 0.0
if (total_grid_import_kwh + total_internal_p2p_kwh) > 0:
    overall_share = 100.0 * total_internal_p2p_kwh / (total_grid_import_kwh + total_internal_p2p_kwh)

with wr1:
    render_metric_card(
        "Grid Energy Bought",
        f"{total_grid_import_kwh:.2f} kWh",
        "Total electricity the community bought from the grid across the whole run."
    )

with wr2:
    render_metric_card(
        "Energy Sold to Grid",
        f"{total_grid_export_kwh:.2f} kWh",
        "Total surplus electricity exported to the grid across the whole run."
    )

with wr3:
    render_metric_card(
        "Total P2P Energy Traded",
        f"{total_internal_p2p_kwh:.2f} kWh",
        "Total electricity matched household-to-household across the whole run after market clearing and balancing."
    )

with wr4:
    render_metric_card(
        "P2P Share of Supply",
        f"{overall_share:.1f}%",
        "Internal matched energy divided by internal matched energy plus grid-bought energy across the whole run."
    )

section_header("Whole-Run Average Prices")
p1, p2, p3 = st.columns(3)

with p1:
    render_metric_card(
        "Average Grid Buy Price",
        f"£{avg_grid_buy_price_whole_run:.3f}/kWh",
        "Whole-run weighted average price paid for electricity bought from the grid."
    )

with p2:
    render_metric_card(
        "Average Grid Sell Price",
        f"£{avg_grid_sell_price_whole_run:.3f}/kWh",
        "Whole-run weighted average price earned for electricity sold to the grid."
    )

with p3:
    render_metric_card(
        "Average P2P Price",
        f"£{avg_total_p2p_price_whole_run:.3f}/kWh",
        "Whole-run average price of all internal P2P matching, including both market-cleared trades and balancing-stage internal matching."
    )

section_header("Whole-Run Financial Summary")

render_financial_linked_row(
    title="Household net cost without P2P trading",
    value=f"£{household_cost_without_p2p:,.2f}",
    help_text="This is the benchmark total household net energy cost if no internal matching had happened. It is built from the benchmark grid-bought cost and benchmark grid-sold revenue using the same tariff assumptions.",
    side_columns=[
        {
            "top_label": "Grid Bought",
            "top_value": f"£{without_breakdown['without_grid_buy_cost_gbp']:,.2f}",
            "top_help": "This is how much the community would have paid to buy electricity from the grid without internal matching (P2P).",
            "bottom_label": "Grid Sold",
            "bottom_value": f"£{without_breakdown['without_grid_sell_revenue_gbp']:,.2f}",
            "bottom_help": "This is how much the community would have earned by selling electricity to the grid without internal matching (P2P).",
        }
    ],
    side_column_width_px=440,
)

render_financial_linked_row(
    title="Household net cost with P2P trading",
    value=f"£{household_cost_with_p2p:,.2f}",
    help_text="This is the actual total household net energy cost with internal matching active. It equals actual grid-bought cost minus actual grid-sold revenue plus settlement penalties.",
    side_columns=[
        {
            "top_label": "Grid Buy",
            "top_value": f"£{total_grid_import_cost_gbp:,.2f}",
            "top_help": "Money paid to the grid for external electricity imports across the whole run.",
            "bottom_label": "Grid Sell",
            "bottom_value": f"£{total_grid_export_revenue_gbp:,.2f}",
            "bottom_help": "Revenue earned from exporting electricity to the grid across the whole run.",
        },
        {
            "top_label": "P2P Buy",
            "top_value": f"£{total_p2p_buy_cost_gbp:,.2f}",
            "top_help": "Money paid internally for P2P electricity purchases across the whole run.",
            "bottom_label": "P2P Sell",
            "bottom_value": f"£{total_p2p_sell_revenue_gbp:,.2f}",
            "bottom_help": "Revenue earned internally from P2P electricity sales across the whole run.",
        },
    ],
    side_column_width_px=220,
)

g1, g2 = st.columns(2)

with g1:
    render_metric_card(
        "Total savings from P2P system",
        f"£{total_savings_from_p2p:,.2f}",
        "This is the avoided external grid spread created by all internal matching across both market and balancing, using the same shared tariff settings."
    )

with g2:
    render_metric_card(
        "Average saving per household",
        f"£{avg_saving_per_household:,.2f}",
        "This is the total savings from the P2P system divided by the number of households in the run."
    )

section_header("Core Energy Performance")

subsection_title("Grid Energy Bought vs P2P Energy Traded")
st.caption("Compares external grid dependence against total internal trading.")
fig1 = base_figure("Energy (kWh)")
add_line(fig1, summary_df["slot"], summary_df["grid_import_kwh"], "Grid Energy Bought (kWh)", "#1565C0")
add_line(fig1, summary_df["slot"], summary_df["p2p_trade_kwh"], "P2P Energy Traded (kWh)", "#FF8F00")
st.plotly_chart(fig1, use_container_width=True, config={"displayModeBar": False})

subsection_title("Forecast Demand vs Actual Demand")
st.caption("Compares predicted community demand with measured demand.")
fig2 = base_figure("Demand (kWh)")
add_line(fig2, summary_df["slot"], summary_df["predicted_demand_kwh"], "Forecast Demand (kWh)", "#4FC3F7", 1.4)
add_line(fig2, summary_df["slot"], summary_df["actual_demand_kwh"], "Actual Demand (kWh)", "#C62828", 1.7)
st.plotly_chart(fig2, use_container_width=True, config={"displayModeBar": False})

section_header("Financial Performance")

subsection_title("Cost of Buying from Grid vs Revenue from Selling to Grid")
st.caption("Shows the external money paid to the grid and earned from the grid.")
fig3 = base_figure("GBP (£)")
add_line(fig3, summary_df["slot"], summary_df["grid_import_cost_gbp"], "Cost of Buying from Grid (£)", "#D32F2F")
add_line(fig3, summary_df["slot"], summary_df["grid_export_revenue_gbp"], "Revenue from Selling to Grid (£)", "#2E7D32")
st.plotly_chart(fig3, use_container_width=True, config={"displayModeBar": False})

subsection_title("Net External Cost Over Time")
st.caption("Shows net external cost over time.")
fig4 = base_figure("GBP (£)")
add_line(fig4, summary_df["slot"], summary_df["net_external_cost_gbp"], "Net External Cost (£)", "#3949AB")
st.plotly_chart(fig4, use_container_width=True, config={"displayModeBar": False})

subsection_title("Grid Energy Bought vs Energy Sold to Grid")
st.caption("Shows external energy import and export over time.")
fig5 = base_figure("Energy (kWh)")
add_line(fig5, summary_df["slot"], summary_df["grid_import_kwh"], "Grid Energy Bought (kWh)", "#00838F")
add_line(fig5, summary_df["slot"], summary_df["grid_export_kwh"], "Energy Sold to Grid (kWh)", "#66BB6A")
st.plotly_chart(fig5, use_container_width=True, config={"displayModeBar": False})

section_header("Individual household breakdown")
st.markdown(
    "<div class='household-note'>The 8 settlement cards and the slot history ledger below are derived from each slot’s community settlement mix, because exact per-household P2P settlement fields are not currently stored in the database.</div>",
    unsafe_allow_html=True,
)

if household_ids:
    selected_h = st.selectbox("Choose household", household_ids)
    h_df = load_household_history(selected_h)

    if not h_df.empty:
        h_df = h_df.sort_values(by=["slot", "id"]).reset_index(drop=True)
        h_df_hist, h_totals = estimate_household_settlement(
            h_df,
            summary_df,
            tou_profile,
            fit_profile,
        )

        hh1, hh2, hh3, hh4 = st.columns(4)
        with hh1:
            render_metric_card(
                "Grid Buy",
                f"{h_totals['grid_buy_kwh']:.2f} kWh",
                "Household electricity bought from the grid across the whole run."
            )
        with hh2:
            render_metric_card(
                "Grid Buy Cost",
                f"£{h_totals['grid_buy_cost_gbp']:.2f}",
                "Household money paid for grid imports across the whole run."
            )
        with hh3:
            render_metric_card(
                "Grid Sell",
                f"{h_totals['grid_sell_kwh']:.2f} kWh",
                "Household electricity sold to the grid across the whole run."
            )
        with hh4:
            render_metric_card(
                "Grid Sell Revenue",
                f"£{h_totals['grid_sell_revenue_gbp']:.2f}",
                "Household money earned from grid exports across the whole run."
            )

        hh5, hh6, hh7, hh8 = st.columns(4)
        with hh5:
            render_metric_card(
                "P2P Buy",
                f"{h_totals['p2p_buy_kwh']:.2f} kWh",
                "Household electricity received through P2P trading across the whole run."
            )
        with hh6:
            render_metric_card(
                "P2P Buy Cost",
                f"£{h_totals['p2p_buy_cost_gbp']:.2f}",
                "Household money paid for P2P electricity across the whole run."
            )
        with hh7:
            render_metric_card(
                "P2P Sell",
                f"{h_totals['p2p_sell_kwh']:.2f} kWh",
                "Household electricity sold through P2P trading across the whole run."
            )
        with hh8:
            render_metric_card(
                "P2P Sell Revenue",
                f"£{h_totals['p2p_sell_revenue_gbp']:.2f}",
                "Household money earned from P2P electricity sales across the whole run."
            )

        subsection_title(f"Household {selected_h}: Settlement History Ledger")
        st.caption("Click open and inspect any slot. The table stores the 8 household settlement metrics by slot.")

        ledger_df = h_df_hist.copy()
        ledger_df["simulated_datetime"] = pd.to_datetime(ledger_df["simulated_datetime"], errors="coerce")

        ledger_display = ledger_df[
            [
                "slot",
                "simulated_datetime",
                "grid_buy_kwh",
                "grid_buy_cost_gbp",
                "grid_sell_kwh",
                "grid_sell_revenue_gbp",
                "p2p_buy_kwh",
                "p2p_buy_cost_gbp",
                "p2p_sell_kwh",
                "p2p_sell_revenue_gbp",
            ]
        ].copy()

        ledger_display = ledger_display.rename(
            columns={
                "slot": "Slot",
                "simulated_datetime": "Simulated Datetime",
                "grid_buy_kwh": "Grid Buy (kWh)",
                "grid_buy_cost_gbp": "Grid Buy Cost (£)",
                "grid_sell_kwh": "Grid Sell (kWh)",
                "grid_sell_revenue_gbp": "Grid Sell Revenue (£)",
                "p2p_buy_kwh": "P2P Buy (kWh)",
                "p2p_buy_cost_gbp": "P2P Buy Cost (£)",
                "p2p_sell_kwh": "P2P Sell (kWh)",
                "p2p_sell_revenue_gbp": "P2P Sell Revenue (£)",
            }
        )

        for col in [
            "Grid Buy (kWh)",
            "Grid Buy Cost (£)",
            "Grid Sell (kWh)",
            "Grid Sell Revenue (£)",
            "P2P Buy (kWh)",
            "P2P Buy Cost (£)",
            "P2P Sell (kWh)",
            "P2P Sell Revenue (£)",
        ]:
            ledger_display[col] = ledger_display[col].astype(float).round(4)

        ledger_display = ledger_display.sort_values("Slot", ascending=False).reset_index(drop=True)

        with st.expander("Open household settlement history ledger", expanded=False):
            slot_options = ledger_display["Slot"].tolist()
            selected_slot = st.selectbox(
                "Choose slot to inspect",
                slot_options,
                key=f"ledger_slot_{selected_h}",
            )

            slot_row = ledger_display[ledger_display["Slot"] == selected_slot].iloc[0]

            st.caption(
                f"Simulated Datetime: {slot_row['Simulated Datetime']}"
            )

            sr1, sr2, sr3, sr4 = st.columns(4)
            with sr1:
                st.metric(
                    "Grid Buy",
                    f"{float(slot_row['Grid Buy (kWh)']):.2f} kWh"
                )
            with sr2:
                st.metric(
                    "Grid Buy Cost",
                    f"£{float(slot_row['Grid Buy Cost (£)']):.2f}"
                )
            with sr3:
                st.metric(
                    "Grid Sell",
                    f"{float(slot_row['Grid Sell (kWh)']):.2f} kWh"
                )
            with sr4:
                st.metric(
                    "Grid Sell Revenue",
                    f"£{float(slot_row['Grid Sell Revenue (£)']):.2f}"
                )

            sr5, sr6, sr7, sr8 = st.columns(4)
            with sr5:
                st.metric(
                    "P2P Buy",
                    f"{float(slot_row['P2P Buy (kWh)']):.2f} kWh"
                )
            with sr6:
                st.metric(
                    "P2P Buy Cost",
                    f"£{float(slot_row['P2P Buy Cost (£)']):.2f}"
                )
            with sr7:
                st.metric(
                    "P2P Sell",
                    f"{float(slot_row['P2P Sell (kWh)']):.2f} kWh"
                )
            with sr8:
                st.metric(
                    "P2P Sell Revenue",
                    f"£{float(slot_row['P2P Sell Revenue (£)']):.2f}"
                )

            st.dataframe(
                ledger_display,
                use_container_width=True,
                hide_index=True,
            )

        subsection_title(f"Household {selected_h}: Forecast Demand vs Actual Demand")
        st.caption("Compares household-level predicted demand with measured demand.")
        fig8 = base_figure("Demand (kWh)")
        add_line(fig8, h_df_hist["slot"], h_df_hist["predicted_demand_kwh"], "Forecast Demand (kWh)", "#4FC3F7", 1.4)
        add_line(fig8, h_df_hist["slot"], h_df_hist["actual_demand_kwh"], "Actual Demand (kWh)", "#C62828", 1.7)
        st.plotly_chart(fig8, use_container_width=True, config={"displayModeBar": False})

        subsection_title(f"Household {selected_h}: PV Output")
        st.caption("Shows household photovoltaic generation over time.")
        fig9 = base_figure("PV Output (kWh)")
        add_line(fig9, h_df_hist["slot"], h_df_hist["pv_kwh"], "PV Output (kWh)", "#FB8C00")
        st.plotly_chart(fig9, use_container_width=True, config={"displayModeBar": False})

        subsection_title(f"Household {selected_h}: Battery State of Charge")
        st.caption("Shows battery state of charge over time.")
        fig10 = base_figure("State of Charge")
        add_line(fig10, h_df_hist["slot"], h_df_hist["soc"], "State of Charge", "#3949AB")
        st.plotly_chart(fig10, use_container_width=True, config={"displayModeBar": False})