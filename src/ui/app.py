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


def inject_custom_css() -> None:
    """Inject custom institutional terminal styling CSS into Streamlit document."""
    st.markdown(
        """
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');
        
        /* Font and Tabular Numerals */
        html, body, [class*="css"] {
            font-family: 'Inter', -apple-system, sans-serif;
            font-variant-numeric: tabular-nums;
        }

        /* Metric Card Containers */
        div[data-testid="stMetric"] {
            background-color: #161b22;
            border: 1px solid #30363d;
            border-left: 4px solid #2f81f7;
            padding: 14px 18px;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        }

        div[data-testid="stMetricLabel"] {
            color: #8b949e !important;
            font-size: 0.85rem !important;
            font-weight: 600 !important;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        div[data-testid="stMetricValue"] {
            color: #f0f6fc !important;
            font-family: 'JetBrains Mono', monospace !important;
            font-weight: 700 !important;
        }

        /* Dataframe Modernization */
        div[data-testid="stDataFrame"] {
            border: 1px solid #30363d;
            border-radius: 10px;
            overflow: hidden;
            box-shadow: 0 4px 16px rgba(0,0,0,0.2);
        }

        /* Tab Bar Styling */
        div[data-baseweb="tab-list"] {
            gap: 8px;
            background-color: #0d1117;
            padding: 6px;
            border-radius: 8px;
            border: 1px solid #30363d;
        }

        button[data-baseweb="tab"] {
            border-radius: 6px !important;
            padding: 8px 16px !important;
            font-weight: 600 !important;
        }

        button[aria-selected="true"] {
            background-color: #1f242d !important;
            color: #58a6ff !important;
            border-bottom: 2px solid #58a6ff !important;
        }
    </style>
    """,
        unsafe_allow_html=True,
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
    display_df["pct_off_52w_high"] = ((display_df["close"] / display_df["high_52w"]) - 1.0) * 100.0
    display_df["ADV20_str"] = display_df["adv_20"].apply(
        lambda v: f"${v / 1e9:.2f}B" if pd.notna(v) and v >= 1e9 else (f"${v / 1e6:.1f}M" if pd.notna(v) and v >= 1e6 else "N/A")
    )
    display_df["market_cap_str"] = display_df["market_cap"].apply(
        lambda m: f"${m / 1e9:.2f}B" if pd.notna(m) and m >= 1e9 else (f"${m / 1e6:.1f}M" if pd.notna(m) and m >= 1e6 else "N/A")
    )
    display_df = display_df.sort_values(by="composite_score", ascending=False)

    tcol1, tcol2 = st.columns([4, 1])
    with tcol1:
        st.caption("📈 Top 10 Quantitative Momentum Recommendations")
    with tcol2:
        csv_data = display_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📥 Export CSV",
            data=csv_data,
            file_name=f"recommendations_{latest_date}.csv",
            mime="text/csv",
        )

    # Render HTML Table Enforcing Left-Aligned Text & Right-Aligned Numbers with Hyperlinked Full Company Name
    html_rows = []
    for idx, r in enumerate(display_df.itertuples(), 1):
        comp_name = getattr(r, "name", None) or getattr(r, "ticker")
        ticker = getattr(r, "ticker")
        mcap = getattr(r, "market_cap_str")
        exch = getattr(r, "exchange", "NASDAQ")
        price = f"${getattr(r, 'close'):.2f}"
        adv = getattr(r, "ADV20_str")
        rs = f"{getattr(r, 'rs_score'):.4f}"
        tight = f"{getattr(r, 'tightness_ratio'):.2f}"
        pct_off = f"{getattr(r, 'pct_off_52w_high'):+.2f}%"
        comp_score = f"{getattr(r, 'composite_score'):.2f}"
        url = f"https://finance.yahoo.com/quote/{ticker}"

        html_rows.append(f"""
        <tr>
            <td style="text-align: left;"><a href="{url}" target="_blank" style="color: #58a6ff; text-decoration: none; font-weight: 600;">{comp_name}</a></td>
            <td style="text-align: right;">{mcap}</td>
            <td style="text-align: left;">{exch}</td>
            <td style="text-align: right; font-family: monospace;">{price}</td>
            <td style="text-align: right;">{adv}</td>
            <td style="text-align: right; font-family: monospace;">{rs}</td>
            <td style="text-align: right; font-family: monospace;">{tight}</td>
            <td style="text-align: right; font-family: monospace;">{pct_off}</td>
            <td style="text-align: right; font-family: monospace; font-weight: bold; color: #58a6ff;">{comp_score}</td>
        </tr>
        """)

    html_table = f"""
    <div style="overflow-x: auto; border: 1px solid #30363d; border-radius: 8px; margin-bottom: 20px;">
        <table style="width: 100%; border-collapse: collapse; font-family: Inter, sans-serif; font-size: 0.9rem;">
            <thead>
                <tr style="background-color: #161b22; border-bottom: 1px solid #30363d; color: #8b949e; font-size: 0.8rem; text-transform: uppercase;">
                    <th style="text-align: left; padding: 10px 12px;">Company Name</th>
                    <th style="text-align: right; padding: 10px 12px;">Market Cap</th>
                    <th style="text-align: left; padding: 10px 12px;">Exchange</th>
                    <th style="text-align: right; padding: 10px 12px;">Price ($)</th>
                    <th style="text-align: right; padding: 10px 12px;">ADV20</th>
                    <th style="text-align: right; padding: 10px 12px;">RS Score</th>
                    <th style="text-align: right; padding: 10px 12px;">Tightness Ratio</th>
                    <th style="text-align: right; padding: 10px 12px;">% Off 52W High</th>
                    <th style="text-align: right; padding: 10px 12px;">Composite Score</th>
                </tr>
            </thead>
            <tbody style="background-color: #0d1117; color: #c9d1d9;">
                {''.join(html_rows)}
            </tbody>
        </table>
    </div>
    """
    st.markdown(html_table, unsafe_allow_html=True)

    # Strategy Rationale & Output Guide (from app rationale.txt)
    st.markdown("### 💡 Strategy Rationale & Screener Output Guide")
    st.info(
        "**Core Strategy:** Find the market's star athletes right as they bend their knees to jump, "
        "rather than trying to rescue injured players or chase someone already sprinting at full speed."
    )

    with st.expander("📖 **The Filters & What They Mean**", expanded=True):
        st.markdown(
            """
- **Price & Trade Volume ($10+ & $20M+ per day)**
  - *Meaning:* Keeps out cheap penny stocks and illiquid ghost towns.
  - *Why:* You want to shop in a crowded, safe supermarket where you can buy and sell instantly without getting ripped off on price.

- **Moving Averages Stacked (Price > 50-day > 150-day > 200-day)**
  - *Meaning:* The stock's current price is higher than its recent average, which is higher than its yearly average.
  - *Why:* Confirms big institutional players (like mutual funds and banks) are actively buying and driving the price upward across all timeframes.

- **Near 52-Week Highs (Up 30%+ from lows, within 25% of highs)**
  - *Meaning:* The stock is trading near its record high for the year, not near the bottom.
  - *Why:* In the stock market, winners usually keep winning; cheap, battered stocks usually stay broken.

- **Volatility Contraction (Tight Price Squeeze)**
  - *Meaning:* The stock stops swinging wildly and trades in a very narrow, quiet price range for two weeks.
  - *Why:* Think of a compressed spring. When the wild swings stop, a big move is about to happen, and you can buy with very low downside risk.

- **Volume Dry-Up (Low Trading Activity)**
  - *Meaning:* Daily trading volume drops way below normal.
  - *Why:* It means sellers have run out of shares to dump. With no sellers left, even a tiny bit of fresh buying will push the price straight up.

- **Relative Strength vs. S&P 500**
  - *Meaning:* Measures if the stock is beating the overall market average.
  - *Why:* You only want the top-performing market leaders, not the average laggards.
"""
        )

    with st.expander("📊 **What the App Output Tells You**", expanded=True):
        st.markdown(
            """
- **Today's Top 10 List ($T_0$)**
  - *Meaning:* The 10 healthiest stocks in the entire market today that are tightly coiled and ready to pop.

- **1-Week & 1-Month "Time Machine" Backtests ($T_{-5}$ and $T_{-22}$)**
  - *Meaning:* A simulated report card showing what would have happened if you bought the scanner's top picks 1 week ago or 1 month ago.
  - *Forward Return & Alpha:* Shows the exact percentage gained and how much better the picks performed compared to the standard S&P 500 index.
  - *Win Rate:* Tells you the batting average (e.g., "7 out of 10 picks went up").
""",
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

    bcol1, bcol2 = st.columns([4, 1])
    with bcol1:
        st.subheader("Historical Position Performance Table")
    with bcol2:
        if isinstance(pos_df, pd.DataFrame) and not pos_df.empty:
            csv_backtest = pos_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="📥 Export CSV",
                data=csv_backtest,
                file_name=f"backtest_{cutoff_days_ago}d_{cutoff_date}.csv",
                mime="text/csv",
            )

    if isinstance(pos_df, pd.DataFrame) and not pos_df.empty:
        disp_pos = pos_df.copy()
        disp_pos["market_cap_str"] = disp_pos["market_cap"].apply(
            lambda m: f"${m / 1e9:.2f}B" if pd.notna(m) and m >= 1e9 else (f"${m / 1e6:.1f}M" if pd.notna(m) and m >= 1e6 else "N/A")
        )

        html_b_rows = []
        for idx, r in enumerate(disp_pos.itertuples(), 1):
            comp_name = getattr(r, "name", None) or getattr(r, "ticker")
            ticker = getattr(r, "ticker")
            mcap = getattr(r, "market_cap_str")
            entry_p = f"${getattr(r, 'entry_price'):.2f}"
            exit_p = f"${getattr(r, 'exit_price'):.2f}"
            ret_pct = f"{getattr(r, 'return_pct'):+.2f}%"
            spy_pct = f"{getattr(r, 'spy_return_pct'):+.2f}%"
            alpha_pct = f"{getattr(r, 'alpha_pct'):+.2f}%"
            mdd = f"{getattr(r, 'max_drawdown_pct'):.2f}%"
            is_win = getattr(r, "is_win")
            status_str = "🟢 WIN" if is_win else "🔴 LOSS"
            url = f"https://finance.yahoo.com/quote/{ticker}"

            ret_color = "#3fb950" if getattr(r, "return_pct") >= 0 else "#f85149"
            alpha_color = "#3fb950" if getattr(r, "alpha_pct") >= 0 else "#f85149"

            html_b_rows.append(f"""
            <tr>
                <td style="text-align: left;"><a href="{url}" target="_blank" style="color: #58a6ff; text-decoration: none; font-weight: 600;">{comp_name}</a></td>
                <td style="text-align: right;">{mcap}</td>
                <td style="text-align: right; font-family: monospace;">{entry_p}</td>
                <td style="text-align: right; font-family: monospace;">{exit_p}</td>
                <td style="text-align: right; font-family: monospace; color: {ret_color}; font-weight: 600;">{ret_pct}</td>
                <td style="text-align: right; font-family: monospace;">{spy_pct}</td>
                <td style="text-align: right; font-family: monospace; color: {alpha_color}; font-weight: 600;">{alpha_pct}</td>
                <td style="text-align: right; font-family: monospace;">{mdd}</td>
                <td style="text-align: left;">{status_str}</td>
            </tr>
            """)

        html_b_table = f"""
        <div style="overflow-x: auto; border: 1px solid #30363d; border-radius: 8px; margin-bottom: 20px;">
            <table style="width: 100%; border-collapse: collapse; font-family: Inter, sans-serif; font-size: 0.9rem;">
                <thead>
                    <tr style="background-color: #161b22; border-bottom: 1px solid #30363d; color: #8b949e; font-size: 0.8rem; text-transform: uppercase;">
                        <th style="text-align: left; padding: 10px 12px;">Company Name</th>
                        <th style="text-align: right; padding: 10px 12px;">Market Cap</th>
                        <th style="text-align: right; padding: 10px 12px;">Entry Price ($)</th>
                        <th style="text-align: right; padding: 10px 12px;">Exit Price ($)</th>
                        <th style="text-align: right; padding: 10px 12px;">Return (%)</th>
                        <th style="text-align: right; padding: 10px 12px;">SPY Return (%)</th>
                        <th style="text-align: right; padding: 10px 12px;">Alpha (%)</th>
                        <th style="text-align: right; padding: 10px 12px;">Max Drawdown (%)</th>
                        <th style="text-align: left; padding: 10px 12px;">Status</th>
                    </tr>
                </thead>
                <tbody style="background-color: #0d1117; color: #c9d1d9;">
                    {''.join(html_b_rows)}
                </tbody>
            </table>
        </div>
        """
        st.markdown(html_b_table, unsafe_allow_html=True)
    else:
        st.info("No position data available for this historical backtest date.")

    # Backtest Output Rationale Callout
    st.markdown("### 💡 Backtest Output Guide")
    with st.expander("📊 **What the Backtest Output Tells You**", expanded=True):
        st.markdown(
            """
- **1-Week & 1-Month "Time Machine" Backtests ($T_{-5}$ and $T_{-22}$)**
  - *Meaning:* A simulated report card showing what would have happened if you bought the scanner's top picks 1 week ago ($T_{-5}$) or 1 month ago ($T_{-22}$).
- **Forward Return & Alpha**
  - *Meaning:* Shows the exact percentage gained and how much better the picks performed compared to the standard S&P 500 benchmark.
- **Win Rate**
  - *Meaning:* Tells you the batting average (e.g., "7 out of 10 picks went up").
- **Max Drawdown**
  - *Meaning:* Tracks the deepest intraday dip experienced during the holding window to quantify downside risk.
"""
        )


def main() -> None:
    """Main entry point for Streamlit dashboard application."""
    inject_custom_css()

    db_manager = get_db_manager()
    latest_date = check_db_availability(db_manager)

    # Sidebar Controls & Parameter Customization Panel
    st.sidebar.title("🎛️ Screener Controls")

    if not latest_date:
        st.sidebar.error("Database: Offline / Missing")
        st.warning(
            "⚠️ Database file missing or contains no trade data.\n\n"
            "Please initialize the database using the CLI command:\n"
            "`python -m src.cli seed`"
        )
        return

    st.sidebar.markdown("### Strategy Parameters")
    min_adv20 = st.sidebar.number_input(
        "Min ADV20 Liquidity ($M)",
        min_value=1.0,
        max_value=100.0,
        value=20.0,
        step=5.0,
        help="Minimum 20-day average daily dollar volume in millions",
    )
    max_tightness = st.sidebar.slider(
        "VCP Tightness Ceiling",
        min_value=1.0,
        max_value=5.0,
        value=3.5,
        step=0.1,
        help="Maximum allowable 10-day high-low tightness ratio",
    )

    st.sidebar.markdown("---")
    st.sidebar.subheader("🔬 Custom Stock Analysis")
    manual_input = st.sidebar.text_input(
        "Ticker(s) to Analyze",
        placeholder="e.g. NVDA, AAPL, TSLA",
        help="Comma-separated ticker symbols to evaluate in Tab 4 (Diagnostic Lab)",
    )
    manual_tickers = [t.strip().upper() for t in manual_input.split(",") if t.strip()] if manual_input else None

    st.sidebar.markdown("---")
    st.sidebar.caption("Mode: **Read-Only (Zero Write Access)**")
    st.sidebar.caption(f"Latest EOD Date: **{latest_date}**")

    # Header Status Banner
    st.title("📈 Quantitative Stock Screener & PIT Backtest")
    col_b1, col_b2, col_b3 = st.columns(3)
    with col_b1:
        st.caption("🟢 **DuckDB Read-Only Active**")
    with col_b2:
        st.caption(f"📅 **Latest EOD Trade Date:** `{latest_date}`")
    with col_b3:
        st.caption("⚡ **Stage-2 Momentum Model**")

    st.markdown("---")

    # Top-Level Horizontal Tabbed Navigation Architecture
    tab1, tab2, tab3, tab4 = st.tabs([
        "📈 View A: Live Top-10 Recommendations",
        "⏪ View B: 1-Week PIT Backtest",
        "🗓️ View C: 1-Month PIT Backtest",
        "🔬 View D: Custom Diagnostic Lab",
    ])

    with tab1:
        render_live_recommendations(db_manager, latest_date)

    with tab2:
        render_backtest_view(db_manager, cutoff_days_ago=5, view_label="View B: 1-Week Backtest")

    with tab3:
        render_backtest_view(db_manager, cutoff_days_ago=22, view_label="View C: 1-Month Backtest")

    with tab4:
        if not manual_tickers:
            st.info("👈 Enter one or more stock tickers in the sidebar field **'Ticker(s) to Analyze'** (e.g. `NVDA, AAPL, TSLA`) to launch custom diagnostics.")
        else:
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

            if found_tickers:
                df_manual = run_screener(db_manager, cutoff_date=latest_date, manual_tickers=found_tickers)
                df_manual = df_manual[df_manual["ticker"].isin(found_tickers)].copy()

                if not df_manual.empty:
                    st.markdown("### 📋 Stage-2 Diagnostic Evaluation & PM Feedback")

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

                        # 8-Point Stage-2 Health Diagnostics
                        p_price = pd.notna(close_val) and close_val >= 10.0
                        p_adv = pd.notna(adv_val) and adv_val >= 20000000.0
                        p_ma = pd.notna(close_val) and pd.notna(sma50_val) and pd.notna(sma150_val) and pd.notna(sma200_val) and (close_val > sma50_val > sma150_val > sma200_val)
                        p_slope = pd.notna(sma200_val) and pd.notna(sma200_20d_val) and sma200_val > sma200_20d_val
                        p_low52 = pd.notna(close_val) and pd.notna(low52_val) and close_val >= 1.30 * low52_val
                        p_high52 = pd.notna(close_val) and pd.notna(high52_val) and close_val >= 0.75 * high52_val
                        p_tight = pd.notna(tight_val) and tight_val <= 3.5
                        p_rs = pd.notna(rs_val) and rs_val > 0.0

                        passed_count = sum([p_price, p_adv, p_ma, p_slope, p_low52, p_high52, p_tight, p_rs])
                        was_in_top10 = tick in top10_set
                        is_passing_all = passed_count == 8

                        reasons = []
                        if not p_price: reasons.append(f"Price (${close_val:.2f}) is below $10.00 floor")
                        if not p_adv: reasons.append(f"ADV20 (${adv_val/1e6:.2f}M) is below $20M liquidity floor")
                        if not p_ma: reasons.append("Moving averages break Close > SMA50 > SMA150 > SMA200 alignment")
                        if not p_slope: reasons.append("200D SMA is not trending upward vs 20 days ago")
                        if not p_low52: reasons.append(f"Price (${close_val:.2f}) is < +30% above 52W Low (${low52_val:.2f})")
                        if not p_high52: reasons.append(f"Price (${close_val:.2f}) exceeds 25% distance from 52W High (${high52_val:.2f})")
                        if not p_tight: reasons.append(f"Tightness Ratio ({tight_val:.2f}) exceeds 3.5 ceiling")
                        if not p_rs: reasons.append(f"Mansfield RS ({rs_val:.4f}) shows underperformance vs SPY")

                        with st.expander(f"📌 **{tick}** — {name_str} (Diagnostic Score: {passed_count}/8 Passed)", expanded=True):
                            # Visual Health Meter Progress Bar
                            st.progress(passed_count / 8.0, text=f"Stage-2 Health Score: **{passed_count} / 8 Checklist Criteria Passed**")

                            # 8-Point Grid Display
                            gcol1, gcol2, gcol3, gcol4 = st.columns(4)
                            with gcol1:
                                st.markdown(f"**Price Floor ($10):** {'🟢 PASS' if p_price else '🔴 FAIL'}")
                                st.markdown(f"**Liquidity ($20M):** {'🟢 PASS' if p_adv else '🔴 FAIL'}")
                            with gcol2:
                                st.markdown(f"**MA Alignment:** {'🟢 PASS' if p_ma else '🔴 FAIL'}")
                                st.markdown(f"**200D Slope:** {'🟢 PASS' if p_slope else '🔴 FAIL'}")
                            with gcol3:
                                st.markdown(f"**52W Low (+30%):** {'🟢 PASS' if p_low52 else '🔴 FAIL'}")
                                st.markdown(f"**52W High (-25%):** {'🟢 PASS' if p_high52 else '🔴 FAIL'}")
                            with gcol4:
                                st.markdown(f"**VCP Tightness:** {'🟢 PASS' if p_tight else '🔴 FAIL'}")
                                st.markdown(f"**Relative Strength:** {'🟢 PASS' if p_rs else '🔴 FAIL'}")

                            st.markdown("---")
                            dcol1, dcol2 = st.columns(2)
                            with dcol1:
                                st.markdown(f"**Percentile Composite Rating:** `{comp_val:.2f} / 100`")
                            with dcol2:
                                st.markdown(f"**View A Top 10 Qualification:** {'⭐ Qualified in Top 10' if was_in_top10 else ('Outside Top 10' if is_passing_all else '❌ Disqualified (Failed Criteria)')}")

                            if is_passing_all:
                                st.success(f"**PM Verdict:** {tick} passes all Stage-2 trend template, liquidity, 52W bounds, SMA slope trajectory, and VCP tightness filters!")
                            else:
                                st.warning(f"**PM Feedback — Why {tick} did not qualify for Top 10:**\n" + "\n".join([f"- {r}" for r in reasons]))

                    df_manual["pct_off_52w_high"] = ((df_manual["close"] / df_manual["high_52w"]) - 1.0) * 100.0
                    df_manual["ADV20_str"] = df_manual["adv_20"].apply(
                        lambda v: f"${v / 1e9:.2f}B" if pd.notna(v) and v >= 1e9 else (f"${v / 1e6:.1f}M" if pd.notna(v) and v >= 1e6 else "N/A")
                    )
                    df_manual["market_cap_str"] = df_manual["market_cap"].apply(
                        lambda m: f"${m / 1e9:.2f}B" if pd.notna(m) and m >= 1e9 else (f"${m / 1e6:.1f}M" if pd.notna(m) and m >= 1e6 else "N/A")
                    )
                    df_manual = df_manual.sort_values(by="composite_score", ascending=False)

                    html_d_rows = []
                    for idx, r in enumerate(df_manual.itertuples(), 1):
                        comp_name = getattr(r, "name", None) or getattr(r, "ticker")
                        ticker = getattr(r, "ticker")
                        mcap = getattr(r, "market_cap_str")
                        exch = getattr(r, "exchange", "NASDAQ")
                        price = f"${getattr(r, 'close'):.2f}"
                        adv = getattr(r, "ADV20_str")
                        rs = f"{getattr(r, 'rs_score'):.4f}"
                        tight = f"{getattr(r, 'tightness_ratio'):.2f}"
                        pct_off = f"{getattr(r, 'pct_off_52w_high'):+.2f}%"
                        comp_score = f"{getattr(r, 'composite_score'):.2f}"
                        url = f"https://finance.yahoo.com/quote/{ticker}"

                        html_d_rows.append(f"""
                        <tr>
                            <td style="text-align: left;"><a href="{url}" target="_blank" style="color: #58a6ff; text-decoration: none; font-weight: 600;">{comp_name}</a></td>
                            <td style="text-align: right;">{mcap}</td>
                            <td style="text-align: left;">{exch}</td>
                            <td style="text-align: right; font-family: monospace;">{price}</td>
                            <td style="text-align: right;">{adv}</td>
                            <td style="text-align: right; font-family: monospace;">{rs}</td>
                            <td style="text-align: right; font-family: monospace;">{tight}</td>
                            <td style="text-align: right; font-family: monospace;">{pct_off}</td>
                            <td style="text-align: right; font-family: monospace; font-weight: bold; color: #58a6ff;">{comp_score}</td>
                        </tr>
                        """)

                    html_d_table = f"""
                    <div style="overflow-x: auto; border: 1px solid #30363d; border-radius: 8px; margin-bottom: 20px;">
                        <table style="width: 100%; border-collapse: collapse; font-family: Inter, sans-serif; font-size: 0.9rem;">
                            <thead>
                                <tr style="background-color: #161b22; border-bottom: 1px solid #30363d; color: #8b949e; font-size: 0.8rem; text-transform: uppercase;">
                                    <th style="text-align: left; padding: 10px 12px;">Company Name</th>
                                    <th style="text-align: right; padding: 10px 12px;">Market Cap</th>
                                    <th style="text-align: left; padding: 10px 12px;">Exchange</th>
                                    <th style="text-align: right; padding: 10px 12px;">Price ($)</th>
                                    <th style="text-align: right; padding: 10px 12px;">ADV20</th>
                                    <th style="text-align: right; padding: 10px 12px;">RS Score</th>
                                    <th style="text-align: right; padding: 10px 12px;">Tightness Ratio</th>
                                    <th style="text-align: right; padding: 10px 12px;">% Off 52W High</th>
                                    <th style="text-align: right; padding: 10px 12px;">Composite Score</th>
                                </tr>
                            </thead>
                            <tbody style="background-color: #0d1117; color: #c9d1d9;">
                                {''.join(html_d_rows)}
                            </tbody>
                        </table>
                    </div>
                    """
                    st.markdown(html_d_table, unsafe_allow_html=True)


if __name__ == "__main__":
    main()
