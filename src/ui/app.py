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
        try:
            df = run_screener(db_manager, cutoff_date=latest_date)
        except Exception as e:
            st.error(f"Database error executing screener: {e}")
            return

    if df.empty:
        st.warning("No stocks passed all screening filters for the latest trade date.")
        return

    # Calculate % Off 52W High & Market Cap formatting helper
    df["pct_off_52w_high"] = ((df["close"] / df["high_52w"]) - 1.0) * 100.0
    df["ticker_url"] = df["ticker"].apply(lambda t: f"https://finance.yahoo.com/quote/{t}")
    df["market_cap_str"] = df["market_cap"].apply(
        lambda m: f"${m / 1e9:.2f}B" if pd.notna(m) and m >= 1e9 else (f"${m / 1e6:.1f}M" if pd.notna(m) and m >= 1e6 else "N/A")
    )

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
            "ticker_url",
            "name",
            "exchange",
            "market_cap_str",
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
            "ticker_url": "Ticker",
            "name": "Company Name",
            "exchange": "Exchange",
            "market_cap_str": "Market Cap",
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
        column_config={
            "Ticker": st.column_config.LinkColumn(
                "Ticker",
                help="Click to view live chart and fundamentals on Yahoo Finance",
                validate="^https://finance\\.yahoo\\.com/quote/",
                display_text=r"https://finance\\.yahoo\\.com/quote/(.*)",
            ),
        },
        width="stretch",
    )

    # Parameter Explanations Callout
    st.markdown("### ℹ️ Parameter Definitions")
    st.markdown(
        r"""
- **Rank**: Priority order (#1–10) determined by the composite momentum score across passing candidates.
- **Ticker**: Hyperlinked stock symbol trading on NYSE, NASDAQ, or AMEX (opens Yahoo Finance chart page).
- **Company Name**: Registered corporate title of the asset.
- **Exchange**: Primary US listing market (NASDAQ, NYSE, or AMEX).
- **Market Cap**: Total dollar market capitalization of the company (in Millions/Billions).
- **Price ($)**: End-of-Day (EOD) closing price on the cutoff evaluation date.
- **ADV20 ($)**: 20-Day Average Daily Dollar Volume ($\text{Close} \times \text{Volume}$), enforced to be $\ge \$20,000,000$ for institutional liquidity.
- **RS Score**: Mansfield Relative Strength measuring multi-timeframe price outperformance vs the SPY benchmark (70% 63-day weight + 30% 252-day weight).
- **Tightness Ratio**: Volatility Contraction Ratio measuring 10-day price range relative to 14-day ATR ($\le 3.5$ ceiling).
- **% Off 52W High**: Percentage distance from the stock's 252-day rolling peak.
- **Composite Score**: Weighted percentile score combining Relative Strength (60% weight) and Consolidation Tightness (40% weight).
"""
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
        disp_pos = pos_df.copy()
        disp_pos["ticker_url"] = disp_pos["ticker"].apply(lambda t: f"https://finance.yahoo.com/quote/{t}")
        disp_pos = disp_pos[
            [
                "ticker_url",
                "entry_price",
                "exit_price",
                "return_pct",
                "spy_return_pct",
                "alpha_pct",
                "max_drawdown_pct",
                "is_win",
            ]
        ].rename(
            columns={
                "ticker_url": "Ticker",
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
            column_config={
                "Ticker": st.column_config.LinkColumn(
                    "Ticker",
                    help="Click to view live chart and fundamentals on Yahoo Finance",
                    validate="^https://finance\\.yahoo\\.com/quote/",
                    display_text=r"https://finance\\.yahoo\\.com/quote/(.*)",
                ),
            },
            width="stretch",
        )
    else:
        st.info("No position data available for this historical backtest date.")

    # Backtest Parameter Explanations Callout
    st.markdown("### ℹ️ Backtest Parameter Definitions")
    st.markdown(
        r"""
- **Cutoff Date**: Historical date ($T_{-5}$ or $T_{-22}$) when screener recommendations were computed without lookahead bias.
- **Evaluation Date**: Target date ($T_0$) up to which forward performance is tracked.
- **Ticker**: Hyperlinked stock symbol trading on NYSE, NASDAQ, or AMEX (opens Yahoo Finance chart page).
- **Entry Price ($)**: Closing price of recommended stock on the historical Cutoff Date.
- **Exit Price ($)**: Closing price of stock on Evaluation Date ($T_0$).
- **Return (%)**: Total percentage price change from Entry Price to Exit Price.
- **SPY Return (%)**: Benchmark S&P 500 ETF percentage return over the identical time window.
- **Alpha (%)**: Excess return achieved by the stock or basket relative to SPY ($\text{Stock Return} - \text{SPY Return}$).
- **Max Drawdown (%)**: Maximum percentage price dip from Entry Price to the lowest intraday low during holding period.
- **Win Rate (%)**: Percentage of recommended stocks in the basket yielding positive forward return ($\text{Return} > 0$).
"""
    )


def main() -> None:
    """Main Streamlit application entry point."""
    st.title("📊 Quantitative Momentum Screener & PIT Backtest")

    # Render Sidebar FIRST to guarantee it never disappears on sub-view errors
    st.sidebar.title("Navigation")

    db_manager = get_db_manager()
    latest_date = check_db_availability(db_manager)

    if not latest_date:
        st.sidebar.error("Database: Offline / Missing")
        st.warning(
            "⚠️ Database file missing or contains no trade data.\n\n"
            "Please initialize the database using the CLI command:\n"
            "`python -m src.cli seed`"
        )
        return

    # Manual Stock Input Controls
    st.sidebar.markdown("---")
    st.sidebar.subheader("➕ Manual Stock Analysis")
    manual_input = st.sidebar.text_input(
        "Add Ticker(s) to Analysis",
        placeholder="e.g. NVDA, AAPL, TSLA",
        help="Comma-separated ticker symbols to force-analyze in the screener/backtest",
    )
    manual_tickers = [t.strip().upper() for t in manual_input.split(",") if t.strip()] if manual_input else None

    view_option = st.sidebar.radio(
        "Select View:",
        [
            "View A: Live Top-10 Recommendations (T0)",
            "View B: 1-Week Backtest (T-5)",
            "View C: 1-Month Backtest (T-22)",
            "View D: Manual Stock Analysis",
        ],
    )

    st.sidebar.markdown("---")
    st.sidebar.caption("Mode: **Read-Only (Zero Write Access)**")
    st.sidebar.caption(f"Latest EOD Date: **{latest_date}**")

    if view_option.startswith("View D") or manual_tickers:
        if not manual_tickers:
            st.warning("Please enter one or more stock tickers in the sidebar field (e.g. `NVDA, AAPL`).")
            return

        st.header(f"View D: Custom Analysis for {', '.join(manual_tickers)}")

        # Check ticker presence in DuckDB
        db_tickers_query = f"SELECT DISTINCT ticker FROM daily_bars WHERE ticker IN ({', '.join(['?']*len(manual_tickers))});"
        existing_rows = db_manager.execute_read(db_tickers_query, manual_tickers)
        existing_set = {r[0] for r in existing_rows}

        missing_tickers = [t for t in manual_tickers if t not in existing_set]
        found_tickers = [t for t in manual_tickers if t in existing_set]

        # Display Ticker Status Badges
        bcol1, bcol2 = st.columns(2)
        with bcol1:
            if found_tickers:
                st.success(f"✅ Found in Database: **{', '.join(found_tickers)}**")
        with bcol2:
            if missing_tickers:
                st.error(f"❌ Missing / Not Ingested: **{', '.join(missing_tickers)}**")

        # Handle missing tickers: Offer 1-click fetch button
        if missing_tickers:
            st.warning(
                f"The following ticker(s) do not currently have historical bars in the local database: **{', '.join(missing_tickers)}**"
            )
            if st.button("📥 Download Historical Data for Missing Tickers"):
                from src.ingestion.data_ingestor import DataIngestor

                with st.spinner("Downloading price history from Yahoo Finance..."):
                    write_db = DatabaseManager(db_path=db_manager.db_path, read_only=False)
                    ingestor = DataIngestor(db_manager=write_db)
                    synced_any = False
                    for m_tick in missing_tickers:
                        ok = ingestor.sync_single_ticker(m_tick)
                        if ok:
                            st.success(f"Downloaded and stored price history for **{m_tick}**!")
                            synced_any = True
                        else:
                            st.error(f"Failed to fetch data for **{m_tick}**. Please verify ticker symbol on Yahoo Finance.")
                    if synced_any:
                        st.rerun()

        if not found_tickers:
            st.info("Enter a valid ticker symbol above and click download to analyze.")
            return

        df_manual = run_screener(db_manager, cutoff_date=latest_date, manual_tickers=found_tickers)
        if not df_manual.empty:
            df_manual["pct_off_52w_high"] = ((df_manual["close"] / df_manual["high_52w"]) - 1.0) * 100.0
            df_manual["ticker_url"] = df_manual["ticker"].apply(lambda t: f"https://finance.yahoo.com/quote/{t}")
            df_manual["market_cap_str"] = df_manual["market_cap"].apply(
                lambda m: f"${m / 1e9:.2f}B" if pd.notna(m) and m >= 1e9 else (f"${m / 1e6:.1f}M" if pd.notna(m) and m >= 1e6 else "N/A")
            )
            st.dataframe(
                df_manual[
                    [
                        "rank",
                        "ticker_url",
                        "name",
                        "exchange",
                        "market_cap_str",
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
                        "ticker_url": "Ticker",
                        "name": "Company Name",
                        "exchange": "Exchange",
                        "market_cap_str": "Market Cap",
                        "close": "Price ($)",
                        "adv_20": "ADV20 ($)",
                        "rs_score": "RS Score",
                        "tightness_ratio": "Tightness Ratio",
                        "pct_off_52w_high": "% Off 52W High",
                        "composite_score": "Composite Score",
                    }
                ).style.format(
                    {
                        "Price ($)": "${:.2f}",
                        "ADV20 ($)": "${:,.0f}",
                        "RS Score": "{:.4f}",
                        "Tightness Ratio": "{:.2f}",
                        "% Off 52W High": "{:+.2f}%",
                        "Composite Score": "{:.2f}",
                    }
                ),
                column_config={
                    "Ticker": st.column_config.LinkColumn(
                        "Ticker",
                        help="Click to view live chart and fundamentals on Yahoo Finance",
                        validate="^https://finance\\.yahoo\\.com/quote/",
                        display_text=r"https://finance\\.yahoo\\.com/quote/(.*)",
                    ),
                },
                width="stretch",
            )
    elif view_option.startswith("View A"):
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
