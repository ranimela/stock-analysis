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
    df["yahoo_url"] = df["ticker"].apply(lambda t: f"https://finance.yahoo.com/quote/{t}")
    df["Company Name"] = df.apply(lambda r: str(r.get("name") or r["ticker"]), axis=1)
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

    st.subheader("Top-10 Recommendations Table (Sorted by Composite Score)")

    display_df = df.copy()

    # Select columns without Rank, sorted by Composite Score descending
    display_df = display_df[
        [
            "yahoo_url",
            "Company Name",
            "market_cap_str",
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
            "market_cap_str": "Market Cap",
            "exchange": "Exchange",
            "close": "Price ($)",
            "adv_20": "ADV20 ($)",
            "rs_score": "RS Score",
            "tightness_ratio": "Tightness Ratio",
            "pct_off_52w_high": "% Off 52W High",
            "composite_score": "Composite Score",
        }
    ).sort_values(by="Composite Score", ascending=False)

    display_df["Company Name"] = display_df["yahoo_url"]

    st.dataframe(
        display_df[
            [
                "Company Name",
                "Market Cap",
                "Exchange",
                "Price ($)",
                "ADV20 ($)",
                "RS Score",
                "Tightness Ratio",
                "% Off 52W High",
                "Composite Score",
            ]
        ].style.format(
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
            "Company Name": st.column_config.LinkColumn(
                "Company Name",
                help="Click to view live chart and fundamentals on Yahoo Finance",
                validate=r"^https://finance\.yahoo\.com/quote/",
                display_text=r"https://finance\.yahoo\.com/quote/(.*)",
            ),
        },
        width="stretch",
    )

    # Parameter Explanations Callout
    st.markdown("### ℹ️ Parameter Definitions")
    st.markdown(
        r"""
- **Company Name**: Hyperlinked corporate title of the asset (click to open live chart on Yahoo Finance).
- **Market Cap**: Total dollar market capitalization of the company (placed directly after Company Name).
- **Exchange**: Primary US listing market (NASDAQ, NYSE, or AMEX).
- **Price ($)**: End-of-Day (EOD) closing price on the cutoff evaluation date.
- **ADV20 ($)**: 20-Day Average Daily Dollar Volume ($\text{Close} \times \text{Volume}$), enforced to be $\ge \$20,000,000$ for institutional liquidity.
- **RS Score**: Mansfield Relative Strength measuring multi-timeframe price outperformance vs the SPY benchmark (70% 63-day weight + 30% 252-day weight).
- **Tightness Ratio**: Volatility Contraction Ratio measuring 10-day price range relative to 14-day ATR ($\le 3.5$ ceiling).
- **% Off 52W High**: Percentage distance from the stock's 252-day rolling peak.
- **Composite Score**: Weighted percentile score combining Relative Strength (60% weight) and Consolidation Tightness (40% weight) — stocks sorted by this score.
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
        disp_pos["company_url"] = disp_pos["ticker"].apply(lambda t: f"https://finance.yahoo.com/quote/{t}")
        disp_pos["company_name"] = disp_pos.apply(lambda r: str(r.get("name") or r["ticker"]), axis=1)
        disp_pos["market_cap_str"] = disp_pos["market_cap"].apply(
            lambda m: f"${m / 1e9:.2f}B" if pd.notna(m) and m >= 1e9 else (f"${m / 1e6:.1f}M" if pd.notna(m) and m >= 1e6 else "N/A")
        )

        disp_pos = disp_pos[
            [
                "company_url",
                "market_cap_str",
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
                "company_url": "Company Name",
                "market_cap_str": "Market Cap",
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
                "Company Name": st.column_config.LinkColumn(
                    "Company Name",
                    help="Click to view live chart and fundamentals on Yahoo Finance",
                    validate=r"^https://finance\.yahoo\.com/quote/",
                    display_text=r"https://finance\.yahoo\.com/quote/(.*)",
                ),
            },
            width="stretch",
        )
        # Backtest CSV Export Button
        csv_backtest = disp_pos.to_csv(index=False).encode("utf-8")
        st.download_button(
            label=f"📥 Download {view_label} Results CSV",
            data=csv_backtest,
            file_name=f"backtest_{cutoff_days_ago}d_{cutoff_date}.csv",
            mime="text/csv",
        )
    else:
        st.info("No position data available for this historical backtest date.")

    # Backtest Parameter Explanations Callout
    st.markdown("### ℹ️ Backtest Parameter Definitions")
    st.markdown(
        r"""
- **Cutoff Date**: Historical date ($T_{-5}$ or $T_{-22}$) when screener recommendations were computed without lookahead bias.
- **Evaluation Date**: Target date ($T_0$) up to which forward performance is tracked.
- **Company Name**: Hyperlinked corporate title of recommended stock (click to open live chart on Yahoo Finance).
- **Market Cap**: Total dollar market capitalization of the company (placed directly after Company Name).
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

    view_option = st.sidebar.radio(
        "Select View:",
        [
            "View A: Live Top-10 Recommendations (T0)",
            "View B: 1-Week Backtest (T-5)",
            "View C: 1-Month Backtest (T-22)",
            "View D: Manual Stock Analysis",
        ],
    )

    # Manual Stock Input Controls
    st.sidebar.markdown("---")
    st.sidebar.subheader("➕ Manual Stock Analysis")
    manual_input = st.sidebar.text_input(
        "Add Ticker(s) to Analyze",
        placeholder="e.g. NVDA, AAPL, TSLA",
        help="Comma-separated ticker symbols to force-analyze in View D",
    )
    manual_tickers = [t.strip().upper() for t in manual_input.split(",") if t.strip()] if manual_input else None

    st.sidebar.markdown("---")
    st.sidebar.caption("Mode: **Read-Only (Zero Write Access)**")
    st.sidebar.caption(f"Latest EOD Date: **{latest_date}**")

    if view_option.startswith("View D"):
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
                st.success(f"✅ Found in Original Ingested Database: **{', '.join(found_tickers)}**")
        with bcol2:
            if missing_tickers:
                st.error(f"❌ Missing / Not Ingested in Local Database: **{', '.join(missing_tickers)}**")

        # Handle missing tickers: Offer 1-click fetch button
        if missing_tickers:
            st.warning(
                f"The following ticker(s) were not part of the initial database seed: **{', '.join(missing_tickers)}**"
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
        # Strictly filter df_manual to user-entered found_tickers only
        df_manual = df_manual[df_manual["ticker"].isin(found_tickers)].copy()

        if not df_manual.empty:
            st.markdown("### 📋 Product Manager & Screener Evaluation Feedback")

            # Dynamic fetch of top 10 recommended tickers for cutoff date
            df_top10 = run_screener(db_manager, cutoff_date=latest_date)
            top10_set = set(df_top10["ticker"].tolist()) if not df_top10.empty else set()

            for _, row in df_manual.iterrows():
                tick = row["ticker"]
                name_str = row.get("name", tick)
                close_val = row["close"]
                adv_val = row["adv_20"]
                sma50_val = row["sma50"]
                sma150_val = row["sma150"]
                sma200_val = row["sma200"]
                sma200_20d_val = row.get("sma200_20d_ago", None)
                high52_val = row["high_52w"]
                low52_val = row["low_52w"]
                tight_val = row.get("tightness_ratio", None)
                rs_val = row["rs_score"]
                comp_val = row["composite_score"]

                reasons = []

                # Price floor check (close >= $10.00)
                if pd.isna(close_val) or close_val < 10.0:
                    c_str = f"${close_val:.2f}" if pd.notna(close_val) else "N/A"
                    reasons.append(f"Price ({c_str}) is below $10.00 minimum price floor")

                # Liquidity floor check (ADV20 >= $20,000,000)
                if pd.isna(adv_val) or adv_val < 20000000.0:
                    adv_str = f"${adv_val/1e6:.2f}M" if pd.notna(adv_val) else "N/A"
                    reasons.append(f"ADV20 ({adv_str}) is below $20M liquidity floor")

                # Moving Average Order (close > sma50 > sma150 > sma200)
                if pd.notna(close_val) and pd.notna(sma50_val) and close_val <= sma50_val:
                    reasons.append(f"Price (${close_val:.2f}) is below 50D SMA (${sma50_val:.2f})")
                if pd.notna(sma50_val) and pd.notna(sma150_val) and sma50_val <= sma150_val:
                    reasons.append(f"50D SMA (${sma50_val:.2f}) is below/equal to 150D SMA (${sma150_val:.2f})")
                if pd.notna(sma150_val) and pd.notna(sma200_val) and sma150_val <= sma200_val:
                    reasons.append(f"150D SMA (${sma150_val:.2f}) is below/equal to 200D SMA (${sma200_val:.2f})")

                # 200D SMA Slope Trajectory (20-day uptrend)
                if pd.isna(sma200_20d_val):
                    reasons.append("200D SMA 20-day slope trajectory unavailable (insufficient historical data)")
                elif pd.notna(sma200_val) and sma200_val <= sma200_20d_val:
                    reasons.append(f"200D SMA (${sma200_val:.2f}) is not trending upward vs 20 days ago (${sma200_20d_val:.2f})")

                # 52-Week Low Bound (close >= 1.30 * low_52w)
                if pd.notna(close_val) and pd.notna(low52_val):
                    pct_above_low = ((close_val / low52_val) - 1.0) * 100.0
                    if close_val < 1.30 * low52_val:
                        reasons.append(
                            f"52W Low Bound Failure: Price (${close_val:.2f}) is only {pct_above_low:+.1f}% above 52W Low (${low52_val:.2f}) — requires >= +30.0%"
                        )

                # 52-Week High Bound (close >= 0.75 * high_52w)
                if pd.notna(close_val) and pd.notna(high52_val):
                    pct_off_high = ((close_val / high52_val) - 1.0) * 100.0
                    if close_val < 0.75 * high52_val:
                        reasons.append(
                            f"52W High Bound Failure: Price (${close_val:.2f}) is {pct_off_high:.1f}% off 52W High (${high52_val:.2f}) — exceeds 25.0% max distance ceiling"
                        )

                # VCP Tightness Ratio ceiling (tightness_ratio <= 3.5)
                if pd.isna(tight_val):
                    reasons.append("Tightness Ratio unavailable (ATR14 missing or zero)")
                elif tight_val > 3.5:
                    reasons.append(f"Tightness Ratio ({tight_val:.2f}) exceeds 3.5 VCP coiling ceiling")

                # Mansfield Relative Strength vs SPY
                if pd.notna(rs_val) and rs_val < 0.0:
                    reasons.append(f"Mansfield RS ({rs_val:.4f}) shows relative underperformance vs SPY benchmark")

                was_in_top10 = tick in top10_set
                is_passing_all = len(reasons) == 0

                with st.expander(f"📌 **{tick}** — {name_str}", expanded=True):
                    ecol1, ecol2 = st.columns(2)
                    with ecol1:
                        st.markdown(f"**Database Status:** Part of Original Ingested Database")
                        st.markdown(f"**Stage-2 Trend Template:** {'✅ Passed All Filters' if is_passing_all else '⚠️ Filter Deficiencies Found'}")
                    with ecol2:
                        st.markdown(f"**Composite Score:** `{comp_val:.2f}`")
                        st.markdown(f"**View A Top 10 Selection:** {'⭐ Qualified in Top 10' if was_in_top10 else ('Outside Top 10 (Ranked below top 10)' if is_passing_all else '❌ Outside Top 10 (Failed filters)')}")

                    if is_passing_all:
                        st.success(f"**PM Verdict:** {tick} passes all Stage-2 trend template, liquidity, 52W bounds, SMA slope trajectory, and VCP tightness filters!")
                    else:
                        st.warning(f"**PM Feedback — Why {tick} did not qualify for Top 10:**\n" + "\n".join([f"- {r}" for r in reasons]))

            df_manual["pct_off_52w_high"] = ((df_manual["close"] / df_manual["high_52w"]) - 1.0) * 100.0
            df_manual["company_url"] = df_manual["ticker"].apply(lambda t: f"https://finance.yahoo.com/quote/{t}")
            df_manual["company_name"] = df_manual.apply(lambda r: str(r.get("name") or r["ticker"]), axis=1)
            df_manual["market_cap_str"] = df_manual["market_cap"].apply(
                lambda m: f"${m / 1e9:.2f}B" if pd.notna(m) and m >= 1e9 else (f"${m / 1e6:.1f}M" if pd.notna(m) and m >= 1e6 else "N/A")
            )

            st.dataframe(
                df_manual[
                    [
                        "company_url",
                        "market_cap_str",
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
                        "company_url": "Company Name",
                        "market_cap_str": "Market Cap",
                        "exchange": "Exchange",
                        "close": "Price ($)",
                        "adv_20": "ADV20 ($)",
                        "rs_score": "RS Score",
                        "tightness_ratio": "Tightness Ratio",
                        "pct_off_52w_high": "% Off 52W High",
                        "composite_score": "Composite Score",
                    }
                ).sort_values(by="Composite Score", ascending=False).style.format(
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
                    "Company Name": st.column_config.LinkColumn(
                        "Company Name",
                        help="Click to view live chart and fundamentals on Yahoo Finance",
                        validate=r"^https://finance\.yahoo\.com/quote/",
                        display_text=r"https://finance\.yahoo\.com/quote/(.*)",
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
