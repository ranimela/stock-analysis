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

        /* HTML Custom Data Table Styling (Light Background) */
        .custom-table-container {
            border: 1px solid #d0d7de;
            border-radius: 10px;
            overflow-x: auto;
            box-shadow: 0 4px 16px rgba(0,0,0,0.08);
            margin: 12px 0 24px 0;
            background-color: #ffffff;
        }

        .custom-data-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.9rem;
            color: #1f2328;
            text-align: left;
        }

        .custom-data-table th {
            background-color: #f6f8fa;
            color: #57606a;
            font-weight: 600;
            padding: 12px 16px;
            border-bottom: 1px solid #d0d7de;
            text-transform: uppercase;
            font-size: 0.8rem;
            letter-spacing: 0.5px;
        }

        .custom-data-table td {
            padding: 12px 16px;
            border-bottom: 1px solid #e1e4e8;
            vertical-align: middle;
            font-variant-numeric: tabular-nums;
            color: #1f2328;
        }

        .custom-data-table tr:hover {
            background-color: #f3f4f6;
        }

        .custom-data-table a.company-link {
            color: #0969da;
            text-decoration: none;
            font-weight: 600;
        }

        .custom-data-table a.company-link:hover {
            text-decoration: underline;
            color: #0550ae;
        }

        .text-left { text-align: left !important; }
        .text-right { text-align: right !important; font-family: 'JetBrains Mono', monospace; color: #1f2328 !important; }
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


def is_medical_pharma(name: str, ticker: str) -> bool:
    """Categorize stock as Medical & Pharma based on corporate name and ticker keywords."""
    text = f"{name} {ticker}".lower()
    keywords = [
        "pharma", "therapeutics", "bio", "health", "medical", "medicine",
        "oncology", "genomics", "care", "diagnostic", "surgical", "clinical",
        "life science", "vaccine", "immunology", "biotech", "hospital", "pharma"
    ]
    return any(kw in text for kw in keywords)


def build_html_table(df_subset: pd.DataFrame, is_backtest: bool = False) -> str:
    """Generate HTML table string for a dataframe subset."""
    if df_subset.empty:
        return "<div class='custom-table-container' style='padding: 16px; color: #57606a;'>No tickers in this category.</div>"

    html_rows = []
    for row_idx, row in df_subset.iterrows():
        comp_name = str(row.get("name") or row["ticker"])
        ticker = row["ticker"]
        yahoo_url = f"https://finance.yahoo.com/quote/{ticker}"
        mcap = row["market_cap_str"]

        if is_backtest:
            entry_p = f"${row['entry_price']:.2f}"
            exit_p = f"${row['exit_price']:.2f}"
            ret = f"{row['return_pct']:+.2f}%"
            spy_ret = f"{row['spy_return_pct']:+.2f}%"
            alpha_p = f"{row['alpha_pct']:+.2f}%"
            mdd = f"{row['max_drawdown_pct']:.2f}%"
            status = row["win_status"]

            html_rows.append(
                f'<tr><td class="text-left"><a class="company-link" href="{yahoo_url}" target="_blank">{comp_name}</a></td><td class="text-right">{mcap}</td><td class="text-right">{entry_p}</td><td class="text-right">{exit_p}</td><td class="text-right">{ret}</td><td class="text-right">{spy_ret}</td><td class="text-right">{alpha_p}</td><td class="text-right">{mdd}</td><td class="text-left">{status}</td></tr>'
            )
        else:
            price = f"${row['close']:.2f}"
            adv = row["ADV20"]
            rs = f"{row['rs_score']:.2f}"
            tightness = f"{row['tightness_ratio']:.2f}"
            pct_high = f"{row['pct_off_52w_high']:+.2f}%"
            comp_score = f"{row['composite_score']:.2f}"

            html_rows.append(
                f'<tr><td class="text-left"><a class="company-link" href="{yahoo_url}" target="_blank">{comp_name}</a></td><td class="text-right">{mcap}</td><td class="text-right">{price}</td><td class="text-right">{adv}</td><td class="text-right">{rs}</td><td class="text-right">{tightness}</td><td class="text-right">{pct_high}</td><td class="text-right">{comp_score}</td></tr>'
            )

    if is_backtest:
        headers = ["Company Name", "Market Cap", "Entry Price ($)", "Exit Price ($)", "Return (%)", "SPY Return (%)", "Alpha (%)", "Max Drawdown (%)", "Status"]
    else:
        headers = ["Company Name", "Market Cap", "Price ($)", "ADV20", "RS Score", "Tightness Ratio", "% Off 52W High", "Composite Score"]

    th_html = "".join([f'<th class="text-left">{h}</th>' for h in headers])

    return f"""
    <div class="custom-table-container">
        <table class="custom-data-table">
            <thead>
                <tr>{th_html}</tr>
            </thead>
            <tbody>
                {''.join(html_rows)}
            </tbody>
        </table>
    </div>
    """


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

    display_df = df.copy()
    # Format Company Name as interactive Markdown link directly: [Company Full Name](Yahoo_URL)
    display_df["Company Name"] = display_df.apply(
        lambda r: f"[{str(r.get('name') or r['ticker'])}](https://finance.yahoo.com/quote/{r['ticker']})",
        axis=1
    )
    display_df["ADV20"] = display_df["adv_20"].apply(
        lambda v: f"${v / 1e9:.2f}B" if pd.notna(v) and v >= 1e9 else (f"${v / 1e6:.1f}M" if pd.notna(v) and v >= 1e6 else "N/A")
    )

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

    sorted_df = display_df.sort_values(by="composite_score", ascending=False)
    sorted_df["is_med_pharma"] = sorted_df.apply(
        lambda r: is_medical_pharma(str(r.get("name") or ""), str(r["ticker"])), axis=1
    )

    df_other_top10 = sorted_df[~sorted_df["is_med_pharma"]].head(10)
    df_med_top10 = sorted_df[sorted_df["is_med_pharma"]].head(10)

    st.subheader("🌐 Top 10: All Other Sectors (Non-Pharma/Bio)")
    st.markdown(build_html_table(df_other_top10, is_backtest=False), unsafe_allow_html=True)

    st.subheader("🏥 Top 10: Medical, Pharma & Bio Category")
    st.markdown(build_html_table(df_med_top10, is_backtest=False), unsafe_allow_html=True)

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

- **Composite Score Calculation (0 – 100 Percentile Rank)**
  - *How it is calculated:* The composite score combines two key factors into a single percentile rank score from `0` to `100`:
    1. **Mansfield Relative Strength Weight (60%):** Weighted combination of 3-month outperformance (70%) and 12-month outperformance (30%) versus the SPY benchmark.
    2. **VCP Tightness Compression Weight (40%):** Measures how tightly squeezed the stock's 10-day price range is relative to its 14-day Average True Range ($\text{ATR}_{14}$). Tighter consolidations receive higher percentile ranks.
  - *Final Formula:* $\text{Composite Score} = 0.60 \times (\text{RS Percentile}) + 0.40 \times (\text{Tightness Percentile})$.
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

    bcol1, bcol2 = st.columns([4, 1])
    with bcol1:
        st.subheader("Historical Position Performance Table")
        st.caption(f"📅 Recommended on **{cutoff_date}** ($T_{{-{cutoff_days_ago}}}$) — Performance tracked through **{eval_date}** ($T_0$)")
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
        disp_pos["company_url"] = disp_pos["ticker"].apply(lambda t: f"https://finance.yahoo.com/quote/{t}")
        disp_pos["company_name"] = disp_pos.apply(lambda r: str(r.get("name") or r["ticker"]), axis=1)
        disp_pos["market_cap_str"] = disp_pos["market_cap"].apply(
            lambda m: f"${m / 1e9:.2f}B" if pd.notna(m) and m >= 1e9 else (f"${m / 1e6:.1f}M" if pd.notna(m) and m >= 1e6 else "N/A")
        )
        disp_pos["win_status"] = disp_pos["is_win"].apply(lambda w: "🟢 WIN" if w else "🔴 LOSS")

        disp_pos["Company Name"] = disp_pos.apply(
            lambda r: f"[{str(r.get('name') or r['ticker'])}](https://finance.yahoo.com/quote/{r['ticker']})",
            axis=1
        )

        disp_pos["is_med_pharma"] = disp_pos.apply(
            lambda r: is_medical_pharma(str(r.get("name") or ""), str(r["ticker"])), axis=1
        )

        df_b_other_top10 = disp_pos[~disp_pos["is_med_pharma"]].head(10)
        df_b_med_top10 = disp_pos[disp_pos["is_med_pharma"]].head(10)

        st.subheader("🌐 Top 10: All Other Sectors (Non-Pharma/Bio)")
        st.markdown(build_html_table(df_b_other_top10, is_backtest=True), unsafe_allow_html=True)

        st.subheader("🏥 Top 10: Medical, Pharma & Bio Category")
        st.markdown(build_html_table(df_b_med_top10, is_backtest=True), unsafe_allow_html=True)
    else:
        st.info("No position data available for this historical backtest date.")

    # Backtest Output Rationale Callout
    st.markdown("### 💡 Backtest Output Guide")
    with st.expander("📊 **What the Backtest Output Tells You**", expanded=True):
        st.markdown(
            f"""
- **Point-in-Time Recommendation ($T_{{-{cutoff_days_ago}}}$)**
  - *Meaning:* Shows the exact list of stocks that the model recommended **{cutoff_days_ago} trading days ago** on **{cutoff_date}**, using strictly the market data available on that day.
- **Forward Performance Tracking ($T_{{-{cutoff_days_ago}}} \rightarrow T_0$)**
  - *Meaning:* Tracks the performance of those recommendations from their entry price on **{cutoff_date}** up to **today ({eval_date})**.
- **Return (%) & Benchmark Alpha (%)**
  - *Meaning:* Measures your exact stock percentage return and how much better (or worse) each pick performed compared to the S&P 500 (`SPY`) over the exact same period.
- **Max Drawdown (%)**
  - *Meaning:* Tracks the deepest intraday price drop from entry peak during the holding period to quantify risk.
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

    # Auto-sync unmerged parquet deltas if available
    try:
        from src.ingestion.data_ingestor import DataIngestor
        ingestor = DataIngestor(db_manager=db_manager)
        ingestor.sync_local_db_from_parquet(deltas_dir="data/daily_deltas")
        latest_date = check_db_availability(db_manager)
    except Exception as e:
        logger.warning("Auto parquet sync warning: %s", e)

    st.sidebar.markdown("---")
    if st.sidebar.button("🔄 Sync Cloud Delta"):
        try:
            from src.ingestion.data_ingestor import DataIngestor
            ingestor = DataIngestor(db_manager=db_manager)
            count = ingestor.sync_local_db_from_parquet(deltas_dir="data/daily_deltas")
            st.sidebar.success(f"Synced {count} delta file(s)!")
            st.rerun()
        except Exception as err:
            st.sidebar.error(f"Sync error: {err}")

    st.sidebar.caption("Mode: **Read-Only (Zero Write Access)**")
    st.sidebar.caption(f"Latest EOD Date: **{latest_date}**")
    st.sidebar.caption("⏰ EOD Update: **Daily at 16:30 EST / 23:30 IST** (After US Market Close)")

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
                    df_manual["company_url"] = df_manual["ticker"].apply(lambda t: f"https://finance.yahoo.com/quote/{t}")
                    df_manual["company_name"] = df_manual.apply(lambda r: str(r.get("name") or r["ticker"]), axis=1)
                    df_manual["ADV20"] = df_manual["adv_20"].apply(
                        lambda v: f"${v / 1e9:.2f}B" if pd.notna(v) and v >= 1e9 else (f"${v / 1e6:.1f}M" if pd.notna(v) and v >= 1e6 else "N/A")
                    )
                    df_manual["market_cap_str"] = df_manual["market_cap"].apply(
                        lambda m: f"${m / 1e9:.2f}B" if pd.notna(m) and m >= 1e9 else (f"${m / 1e6:.1f}M" if pd.notna(m) and m >= 1e6 else "N/A")
                    )

                    df_manual["Company Name"] = df_manual.apply(
                        lambda r: f"[{str(r.get('name') or r['ticker'])}](https://finance.yahoo.com/quote/{r['ticker']})",
                        axis=1
                    )

                    sorted_d_df = df_manual.sort_values(by="composite_score", ascending=False)
                    sorted_d_df["is_med_pharma"] = sorted_d_df.apply(
                        lambda r: is_medical_pharma(str(r.get("name") or ""), str(r["ticker"])), axis=1
                    )

                    df_d_other_top10 = sorted_d_df[~sorted_d_df["is_med_pharma"]].head(10)
                    df_d_med_top10 = sorted_d_df[sorted_d_df["is_med_pharma"]].head(10)

                    st.subheader("🌐 Top 10: All Other Sectors (Non-Pharma/Bio)")
                    st.markdown(build_html_table(df_d_other_top10, is_backtest=False), unsafe_allow_html=True)

                    st.subheader("🏥 Top 10: Medical, Pharma & Bio Category")
                    st.markdown(build_html_table(df_d_med_top10, is_backtest=False), unsafe_allow_html=True)


if __name__ == "__main__":
    main()
