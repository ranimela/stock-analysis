"""Streamlit Dashboard Application for Stock Momentum Screener & Point-in-Time Backtests.

Provides zero-write-access visualization for:
- View A: Live Top-10 Recommendations (T0)
- View B: 1-Week Backtest (T-5)
- View C: 1-Month Backtest (T-22)
"""

from __future__ import annotations

import logging
from pathlib import Path
import sys

import pandas as pd
import streamlit as st

# Ensure project root is in sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.db.db_manager import DatabaseManager
from src.engine.backtest_engine import run_point_in_time_backtest
from src.engine.screener_queries import run_screener

logger = logging.getLogger(__name__)

# Page Configuration
st.set_page_config(
    page_title="Quantitative Stock Screener & PIT Backtest",
    page_icon="📈",
    layout="wide",
)


@st.cache_resource
def get_db_manager() -> DatabaseManager:
    """Initialize DatabaseManager in strictly read-only mode."""
    db_path = ROOT_DIR / "market_data.duckdb"
    return DatabaseManager(db_path=db_path, read_only=True)


def check_db_availability(db_manager: DatabaseManager) -> str | None:
    """Check if database file exists and contains trade dates.

    Returns:
        str | None: Latest trade date string if available, otherwise None.
    """
    if not db_manager.db_path.exists():
        return None
    try:
        rows = db_manager.execute_read("SELECT MAX(trade_date) FROM daily_bars;")
        if rows and rows[0][0]:
            return str(rows[0][0])
    except Exception as e:
        logger.warning("Error reading max trade_date: %s", e)
        return None
    return None


def render_live_recommendations(db_manager: DatabaseManager, latest_date: str) -> None:
    """Render View A: Live Top-10 Recommendations (T0)."""
    st.header(f"View A: Live Top-10 Recommendations (Cutoff Date: {latest_date})")
    st.markdown(
        "Quantitative Stage-2 Momentum recommendations clearing liquidity, "
        "VCP tightness, and Mansfield Relative Strength filters."
    )

    with st.spinner("Executing Stage-2 Screener..."):
        df = run_screener(db_manager, cutoff_date=latest_date)

    if df.empty:
        st.warning("No stocks passed all screening filters for the latest trade date.")
        return

    # Calculate % Off 52W High
    df["pct_off_52w_high"] = ((df["close"] / df["high_52w"]) - 1.0) * 100.0

    # Key metrics for top recommendation
    top_row = df.iloc[0]
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Top Pick Ticker", str(top_row["ticker"]))
    with col2:
        st.metric("Price ($)", f"${top_row['close']:.2f}")
    with col3:
        st.metric("ADV20 ($M)", f"${top_row['adv_20'] / 1e6:.2f}M")
    with col4:
        st.metric("RS Score", f"{top_row['rs_score']:.4f}")
    with col5:
        st.metric("Tightness Ratio", f"{top_row['tightness_ratio']:.2f}")

    st.subheader("Ranked Top-10 Recommendations Table")

    display_df = df.copy()
    display_df = display_df[
        [
            "rank",
            "ticker",
            "name",
            "exchange",
            "close",
            "adv_20",
            "rs_score",
            "tightness_ratio",
            "pct_off_52w_high",
            "composite_score",
        ]
    ].rename(
        columns={
            "rank": "Rank",
            "ticker": "Ticker",
            "name": "Company Name",
            "exchange": "Exchange",
            "close": "Price ($)",
            "adv_20": "ADV20 ($)",
            "rs_score": "RS Score",
            "tightness_ratio": "Tightness Ratio",
            "pct_off_52w_high": "% Off 52W High",
            "composite_score": "Composite Score",
        }
    )

    st.dataframe(
        display_df.style.format(
            {
                "Price ($)": "${:.2f}",
                "ADV20 ($)": "${:,.0f}",
                "RS Score": "{:.4f}",
                "Tightness Ratio": "{:.2f}",
                "% Off 52W High": "{:+.2f}%",
                "Composite Score": "{:.2f}",
            }
        ),
        use_container_width=True,
    )

    # CSV Download Button
    csv_data = display_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="📥 Download Recommendations CSV",
        data=csv_data,
        file_name=f"recommendations_{latest_date}.csv",
        mime="text/csv",
    )


def render_backtest_view(
    db_manager: DatabaseManager, cutoff_days_ago: int, view_label: str
) -> None:
    """Render View B / View C Point-in-Time Backtest results."""
    st.header(f"{view_label} (T-{cutoff_days_ago} Days Ago)")

    with st.spinner(f"Running T-{cutoff_days_ago} Point-in-Time Backtest..."):
        try:
            results = run_point_in_time_backtest(db_manager, cutoff_days_ago=cutoff_days_ago)
        except Exception as e:
            st.error(f"Error running backtest: {e}")
            return

    cutoff_date = str(results["cutoff_date"])
    eval_date = str(results["evaluation_date"])
    mean_ret = float(results["mean_basket_return"]) * 100.0
    spy_ret = float(results["spy_return"]) * 100.0
    alpha = float(results["basket_alpha"]) * 100.0
    win_rate = float(results["win_rate"])
    max_dd = float(results["avg_max_drawdown"])
    pos_df = results["positions_df"]

    st.info(f"Cutoff Date: **{cutoff_date}** | Evaluation Date: **{eval_date}**")

    # Metrics Summary Row
    mcol1, mcol2, mcol3, mcol4, mcol5 = st.columns(5)
    with mcol1:
        st.metric("Basket Alpha vs SPY", f"{alpha:+.2f}%")
    with mcol2:
        st.metric("Win Rate", f"{win_rate:.1f}%")
    with mcol3:
        st.metric("Avg Max Drawdown", f"{max_dd:.2f}%")
    with mcol4:
        st.metric("Basket Return", f"{mean_ret:+.2f}%")
    with mcol5:
        st.metric("SPY Return", f"{spy_ret:+.2f}%")

    st.subheader("Historical Position Performance Table")
    if isinstance(pos_df, pd.DataFrame) and not pos_df.empty:
        disp_pos = pos_df.copy().rename(
            columns={
                "ticker": "Ticker",
                "entry_price": "Entry Price ($)",
                "exit_price": "Exit Price ($)",
                "return_pct": "Return (%)",
                "spy_return_pct": "SPY Return (%)",
                "alpha_pct": "Alpha (%)",
                "max_drawdown_pct": "Max Drawdown (%)",
                "is_win": "Win?",
            }
        )

        st.dataframe(
            disp_pos.style.format(
                {
                    "Entry Price ($)": "${:.2f}",
                    "Exit Price ($)": "${:.2f}",
                    "Return (%)": "{:+.2f}%",
                    "SPY Return (%)": "{:+.2f}%",
                    "Alpha (%)": "{:+.2f}%",
                    "Max Drawdown (%)": "{:.2f}%",
                }
            ),
            use_container_width=True,
        )
    else:
        st.info("No position data available for this backtest period.")


def main() -> None:
    """Main Streamlit application entry point."""
    st.title("📊 Quantitative Momentum Screener & PIT Backtest")

    db_manager = get_db_manager()
    latest_date = check_db_availability(db_manager)

    if not latest_date:
        st.warning(
            "⚠️ Database file missing or contains no trade data.\n\n"
            "Please initialize the database using the CLI command:\n"
            "`python -m src.cli seed`"
        )
        return

    # Sidebar Navigation
    st.sidebar.title("Navigation")
    view_option = st.sidebar.radio(
        "Select View:",
        [
            "View A: Live Top-10 Recommendations (T0)",
            "View B: 1-Week Backtest (T-5)",
            "View C: 1-Month Backtest (T-22)",
        ],
    )

    st.sidebar.markdown("---")
    st.sidebar.caption("Mode: **Read-Only (Zero Write Access)**")
    st.sidebar.caption(f"Latest EOD Date: **{latest_date}**")

    if view_option.startswith("View A"):
        render_live_recommendations(db_manager, latest_date)
    elif view_option.startswith("View B"):
        render_backtest_view(
            db_manager, cutoff_days_ago=5, view_label="View B: 1-Week Backtest"
        )
    elif view_option.startswith("View C"):
        render_backtest_view(
            db_manager, cutoff_days_ago=22, view_label="View C: 1-Month Backtest"
        )


if __name__ == "__main__":
    main()
