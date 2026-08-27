"""Streamlit Dashboard Application for Stock Momentum Screener & Point-in-Time Backtests.

Provides zero-write-access visualization for:
- View A: Live Top-10 Recommendations (T0)
- View B: 1-Week Backtest (T-5)
- View C: 1-Month Backtest (T-22)
"""

from __future__ import annotations

from datetime import datetime, timedelta
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

        /* Portfolio Benchmark Section & Card Styling */
        .benchmark-section-title {
            font-size: 1.1rem;
            font-weight: 700;
            margin: 20px 0 10px 0;
            padding: 8px 12px;
            border-radius: 6px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .title-non-pharma {
            background-color: #ddf4ff;
            color: #0969da;
            border-left: 5px solid #0969da;
        }
        .title-pharma {
            background-color: #dafbe1;
            color: #1a7f37;
            border-left: 5px solid #1a7f37;
        }
        .title-tase {
            background-color: #eef5fc;
            color: #0b4f8a;
            border-left: 5px solid #0b4f8a;
        }
        .portfolio-card {
            border: 1px solid #d0d7de;
            border-radius: 10px;
            padding: 16px 20px;
            background-color: #ffffff;
            box-shadow: 0 4px 12px rgba(0,0,0,0.04);
            margin-bottom: 16px;
        }
        .portfolio-card-tase {
            border: 1px solid #b6d4fe;
            border-left: 4px solid #0b4f8a;
            border-radius: 10px;
            padding: 16px 20px;
            background-color: #f7faff;
            box-shadow: 0 4px 12px rgba(11, 79, 138, 0.06);
            margin-bottom: 16px;
        }
        .portfolio-card-title {
            font-size: 0.82rem;
            font-weight: 600;
            color: #57606a;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 6px;
        }
        .portfolio-card-val {
            font-size: 1.45rem;
            font-weight: 700;
            color: #1f2328;
            font-family: 'JetBrains Mono', monospace;
        }
        .portfolio-card-sub {
            font-size: 0.85rem;
            font-weight: 600;
            margin-top: 4px;
        }
        .pos-gain { color: #1a7f37 !important; }
        .neg-loss { color: #cf222e !important; }
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


def format_company_name(name: Any, ticker: str) -> str:
    """Safely format company name with fallback to ticker symbol if missing or NaN."""
    if pd.notna(name):
        s = str(name).strip()
        if s and s.lower() != "nan":
            return s
    return str(ticker).strip()


def is_tase_ticker(ticker: str) -> bool:
    """Check if ticker belongs to Tel Aviv Stock Exchange."""
    t = ticker.strip().upper()
    return t.endswith(".TA") or t == "^TA125.TA" or t == "^TA125"


def build_html_table(
    df_subset: pd.DataFrame,
    is_backtest: bool = False,
    is_tase: bool = False,
) -> str:
    """Generate HTML table string for a dataframe subset."""
    if df_subset.empty:
        return "<div class='custom-table-container' style='padding: 16px; color: #57606a;'>No tickers in this category.</div>"

    html_rows = []
    for row_idx, row in df_subset.iterrows():
        comp_name = format_company_name(row.get("name"), row["ticker"])
        ticker = str(row["ticker"])
        yahoo_url = f"https://finance.yahoo.com/quote/{ticker}"
        mcap = str(row.get("market_cap_str", "N/A"))

        if is_backtest:
            if is_tase:
                entry_p = f"{row['entry_price']:,.2f} Ag." if pd.notna(row.get("entry_price")) else "N/A"
                exit_p = f"{row['exit_price']:,.2f} Ag." if pd.notna(row.get("exit_price")) else "N/A"
                bench_ret_val = row.get("ta125_return_pct", row.get("benchmark_return_pct", row.get("spy_return_pct", None)))
            else:
                entry_p = f"${row['entry_price']:.2f}" if pd.notna(row.get("entry_price")) else "N/A"
                exit_p = f"${row['exit_price']:.2f}" if pd.notna(row.get("exit_price")) else "N/A"
                bench_ret_val = row.get("spy_return_pct", None)

            ret = f"{row['return_pct']:+.2f}%" if pd.notna(row.get("return_pct")) else "N/A"
            bench_ret = f"{bench_ret_val:+.2f}%" if pd.notna(bench_ret_val) else "N/A"
            alpha_p = f"{row['alpha_pct']:+.2f}%" if pd.notna(row.get("alpha_pct")) else "N/A"
            mdd = f"{row['max_drawdown_pct']:.2f}%" if pd.notna(row.get("max_drawdown_pct")) else "N/A"
            status = str(row.get("win_status", "🟢 WIN" if row.get("is_win", False) else "🔴 LOSS"))

            html_rows.append(
                f'<tr><td class="text-left"><a class="company-link" href="{yahoo_url}" target="_blank">{comp_name}</a></td><td class="text-right">{mcap}</td><td class="text-right">{entry_p}</td><td class="text-right">{exit_p}</td><td class="text-right">{ret}</td><td class="text-right">{bench_ret}</td><td class="text-right">{alpha_p}</td><td class="text-right">{mdd}</td><td class="text-left">{status}</td></tr>'
            )
        else:
            if is_tase:
                price = f"{row['close']:,.2f} Ag." if pd.notna(row.get("close")) else "N/A"
            else:
                price = f"${row['close']:.2f}" if pd.notna(row.get("close")) else "N/A"
            adv = str(row.get("ADV20", "N/A"))
            rs = f"{row['rs_score']:.2f}" if pd.notna(row.get("rs_score")) else "N/A"
            tightness = f"{row['tightness_ratio']:.2f}" if pd.notna(row.get("tightness_ratio")) else "N/A"
            pct_high = f"{row['pct_off_52w_high']:+.2f}%" if pd.notna(row.get("pct_off_52w_high")) else "N/A"
            comp_score = f"{row['composite_score']:.2f}" if pd.notna(row.get("composite_score")) else "N/A"

            html_rows.append(
                f'<tr><td class="text-left"><a class="company-link" href="{yahoo_url}" target="_blank">{comp_name}</a></td><td class="text-right">{mcap}</td><td class="text-right">{price}</td><td class="text-right">{adv}</td><td class="text-right">{rs}</td><td class="text-right">{tightness}</td><td class="text-right">{pct_high}</td><td class="text-right">{comp_score}</td></tr>'
            )

    if is_backtest:
        bench_col = "TA-125 Return (%)" if is_tase else "SPY Return (%)"
        price_col_entry = "Entry Price (Ag.)" if is_tase else "Entry Price ($)"
        price_col_exit = "Exit Price (Ag.)" if is_tase else "Exit Price ($)"
        headers = ["Company Name", "Market Cap", price_col_entry, price_col_exit, "Return (%)", bench_col, "Alpha (%)", "Max Drawdown (%)", "Status"]
    else:
        price_col = "Price (Ag.)" if is_tase else "Price ($)"
        adv_col = "ADV20 (Ag.)" if is_tase else "ADV20"
        headers = ["Company Name", "Market Cap", price_col, adv_col, "RS Score", "Tightness Ratio", "% Off 52W High", "Composite Score"]

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


def render_live_recommendations(
    db_manager: DatabaseManager,
    latest_date: str,
    max_tightness: float = 3.5,
    pct_off_low: float = 30.0,
    pct_within_high: float = 25.0,
    min_price: float | None = None,
    min_adv20: float | None = None,
) -> None:
    """Render View A: Live Top-10 Recommendations (T0)."""
    st.header(f"View A: Live Top-10 Recommendations (Cutoff Date: {latest_date})")
    st.markdown(
        "Quantitative Stage-2 Momentum recommendations clearing liquidity, "
        "VCP tightness, and Mansfield Relative Strength filters."
    )

    with st.spinner("Executing Stage-2 Screener..."):
        try:
            df = run_screener(
                db_manager,
                cutoff_date=latest_date,
                max_tightness=max_tightness,
                pct_off_low=pct_off_low,
                pct_within_high=pct_within_high,
                min_price=min_price,
                min_adv20=min_adv20,
            )
        except Exception as e:
            st.error(f"Database error executing screener: {e}")
            df = pd.DataFrame()

    if isinstance(df, pd.DataFrame) and not df.empty:
        # Calculate % Off 52W High & Market Cap formatting helper
        df["pct_off_52w_high"] = ((df["close"] / df["high_52w"]) - 1.0) * 100.0
        df["yahoo_url"] = df["ticker"].apply(lambda t: f"https://finance.yahoo.com/quote/{t}")
        df["Company Name"] = df.apply(lambda r: format_company_name(r.get("name"), r["ticker"]), axis=1)
        df["market_cap_str"] = df["market_cap"].apply(
            lambda m: f"${m / 1e9:.2f}B" if pd.notna(m) and m >= 1e9 else (f"${m / 1e6:.1f}M" if pd.notna(m) and m >= 1e6 else "N/A")
        )

        display_df = df.copy()
        # Format Company Name as interactive Markdown link directly: [Company Full Name](Yahoo_URL)
        display_df["Company Name"] = display_df.apply(
            lambda r: f"[{format_company_name(r.get('name'), r['ticker'])}](https://finance.yahoo.com/quote/{r['ticker']})",
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
            lambda r: is_medical_pharma(format_company_name(r.get("name"), ""), str(r["ticker"])), axis=1
        )

        df_other_top10 = sorted_df[~sorted_df["is_med_pharma"]].head(10)
        df_med_top10 = sorted_df[sorted_df["is_med_pharma"]].head(10)

        st.subheader("🌐 Top 10: All Other Sectors (Non-Pharma/Bio)")
        st.markdown(build_html_table(df_other_top10, is_backtest=False), unsafe_allow_html=True)

        st.subheader("🏥 Top 10: Medical, Pharma & Bio Category")
        st.markdown(build_html_table(df_med_top10, is_backtest=False), unsafe_allow_html=True)
    else:
        st.warning("No stocks passed all screening filters for the latest trade date.")

    # Section 3: Dedicated Top 5 TASE Recommendations
    st.markdown("---")
    st.markdown(
        '<div class="benchmark-section-title title-tase">'
        '<span>🇮🇱 Category 3: Tel Aviv Stock Exchange (TA-125) — Top 5 Recommendations</span>'
        '<span style="font-size: 0.8rem; text-transform: uppercase;">TASE Dedicated Pool</span>'
        '</div>',
        unsafe_allow_html=True,
    )

    with st.spinner("Executing TASE Stage-2 Screener..."):
        try:
            df_tase = run_screener(
                db_manager,
                cutoff_date=latest_date,
                universe="TASE",
                max_tightness=max_tightness,
                pct_off_low=pct_off_low,
                pct_within_high=pct_within_high,
                min_price=min_price,
                min_adv20=min_adv20,
            )
        except Exception as e:
            st.warning(f"Note: TASE screener execution notice: {e}")
            df_tase = pd.DataFrame()

    if isinstance(df_tase, pd.DataFrame) and not df_tase.empty:
        df_tase["pct_off_52w_high"] = ((df_tase["close"] / df_tase["high_52w"]) - 1.0) * 100.0
        df_tase["yahoo_url"] = df_tase["ticker"].apply(lambda t: f"https://finance.yahoo.com/quote/{t}")
        df_tase["Company Name"] = df_tase.apply(
            lambda r: f"[{format_company_name(r.get('name'), r['ticker'])}](https://finance.yahoo.com/quote/{r['ticker']})",
            axis=1,
        )
        df_tase["ADV20"] = df_tase["adv_20"].apply(
            lambda v: f"{v / 1e6:,.1f}M Ag." if pd.notna(v) and v >= 1e6 else (f"{v:,.0f} Ag." if pd.notna(v) else "N/A")
        )
        df_tase["market_cap_str"] = df_tase["market_cap"].apply(
            lambda m: f"{m / 1e9:.2f}B Ag." if pd.notna(m) and m >= 1e9 else (f"{m / 1e6:.1f}M Ag." if pd.notna(m) and m >= 1e6 else "N/A")
        )

        tcol1, tcol2 = st.columns([4, 1])
        with tcol1:
            st.caption("🇮🇱 Top 5 Quantitative Momentum Recommendations (TA-125 Universe)")
        with tcol2:
            csv_tase = df_tase.head(5).to_csv(index=False).encode("utf-8")
            st.download_button(
                label="📥 Export TASE CSV",
                data=csv_tase,
                file_name=f"tase_recommendations_{latest_date}.csv",
                mime="text/csv",
                key=f"dl_tase_csv_view_a_{latest_date}",
            )

        df_tase_top5 = df_tase.sort_values(by="composite_score", ascending=False).head(5)
        st.markdown(build_html_table(df_tase_top5, is_backtest=False, is_tase=True), unsafe_allow_html=True)
    else:
        st.info("No TASE stocks passed screening filters or TASE universe data not yet loaded.")

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
    db_manager: DatabaseManager,
    cutoff_days_ago: int = 5,
    view_label: str = "Backtest",
    custom_cutoff_date: str | None = None,
    max_tightness: float = 3.5,
    pct_off_low: float = 30.0,
    pct_within_high: float = 25.0,
    min_price: float | None = None,
    min_adv20: float | None = None,
) -> None:
    """Render Point-in-Time Backtest results for T-5, T-22, or Custom Selected Date."""
    if custom_cutoff_date:
        st.header(f"{view_label} (Cutoff Date: {custom_cutoff_date})")
    else:
        st.header(f"{view_label} (T-{cutoff_days_ago} Days Ago)")

    st.markdown("### 💰 $10,000 Portfolio Benchmark Performance Comparisons")

    with st.spinner("Running US Point-in-Time Backtest..."):
        try:
            results = run_point_in_time_backtest(
                db_manager,
                cutoff_days_ago=cutoff_days_ago,
                custom_cutoff_date=custom_cutoff_date,
                max_tightness=max_tightness,
                pct_off_low=pct_off_low,
                pct_within_high=pct_within_high,
                universe="US",
            )
        except Exception as e:
            logger.warning("Error running US backtest: %s", e)
            results = None

    cutoff_date = str(results.get("cutoff_date", custom_cutoff_date or "N/A")) if results else (str(custom_cutoff_date) if custom_cutoff_date else "N/A")
    eval_date = str(results.get("evaluation_date", "N/A")) if results else "N/A"

    if results and isinstance(results.get("positions_df"), pd.DataFrame) and not results["positions_df"].empty:
        mean_ret = float(results["mean_basket_return"]) * 100.0
        spy_ret = float(results["spy_return"]) * 100.0
        alpha = float(results["basket_alpha"]) * 100.0
        win_rate = float(results["win_rate"])
        max_dd = float(results["avg_max_drawdown"])
        pos_df = results["positions_df"]

        # Calculate $10,000 SPY Benchmark value
        spy_val = 10000.0 * (1.0 + (spy_ret / 100.0))
        spy_gain = spy_val - 10000.0

        disp_pos = pos_df.copy()
        disp_pos["company_url"] = disp_pos["ticker"].apply(lambda t: f"https://finance.yahoo.com/quote/{t}")
        disp_pos["company_name"] = disp_pos.apply(lambda r: format_company_name(r.get("name"), r["ticker"]), axis=1)
        disp_pos["market_cap_str"] = disp_pos["market_cap"].apply(
            lambda m: f"${m / 1e9:.2f}B" if pd.notna(m) and m >= 1e9 else (f"${m / 1e6:.1f}M" if pd.notna(m) and m >= 1e6 else "N/A")
        )
        disp_pos["win_status"] = disp_pos["is_win"].apply(lambda w: "🟢 WIN" if w else "🔴 LOSS")
        disp_pos["Company Name"] = disp_pos.apply(
            lambda r: f"[{format_company_name(r.get('name'), r['ticker'])}](https://finance.yahoo.com/quote/{r['ticker']})",
            axis=1,
        )
        disp_pos["is_med_pharma"] = disp_pos.apply(
            lambda r: is_medical_pharma(format_company_name(r.get("name"), ""), str(r["ticker"])), axis=1,
        )

        df_b_other_top10 = disp_pos[~disp_pos["is_med_pharma"]].head(10)
        df_b_med_top10 = disp_pos[disp_pos["is_med_pharma"]].head(10)

        # 1. Non-Pharma / General Sectors Benchmark Calculation
        n_other = len(df_b_other_top10)
        alloc_other = 10000.0 / n_other if n_other > 0 else 1000.0
        other_val = sum([alloc_other * (1.0 + (row["return_pct"] / 100.0)) for _, row in df_b_other_top10.iterrows()]) if n_other > 0 else 10000.0
        other_gain = other_val - 10000.0
        other_alpha = other_val - spy_val

        # 2. Medical & Pharma / Biotech Benchmark Calculation
        n_med = len(df_b_med_top10)
        alloc_med = 10000.0 / n_med if n_med > 0 else 1000.0
        med_val = sum([alloc_med * (1.0 + (row["return_pct"] / 100.0)) for _, row in df_b_med_top10.iterrows()]) if n_med > 0 else 10000.0
        med_gain = med_val - 10000.0
        med_alpha = med_val - spy_val

        # --- Section 1: Non-Pharma Benchmark Cards ---
        st.markdown(
            '<div class="benchmark-section-title title-non-pharma">'
            '<span>🌐 Category 1: All Other Sectors (Non-Pharma/Bio) — $10k Benchmark</span>'
            '<span style="font-size: 0.8rem; text-transform: uppercase;">Top 10 Picks Allocation</span>'
            '</div>',
            unsafe_allow_html=True,
        )
        ocol1, ocol2, ocol3 = st.columns(3)
        with ocol1:
            st.markdown(
                f"""
                <div class="portfolio-card">
                    <div class="portfolio-card-title">💵 SPY S&P 500 ($10k Buy & Hold)</div>
                    <div class="portfolio-card-val">${spy_val:,.2f}</div>
                    <div class="portfolio-card-sub {'pos-gain' if spy_gain >= 0 else 'neg-loss'}">
                        {'▲' if spy_gain >= 0 else '▼'} ${abs(spy_gain):,.2f} ({spy_ret:+.2f}%)
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with ocol2:
            st.markdown(
                f"""
                <div class="portfolio-card">
                    <div class="portfolio-card-title">🌐 10x $1,000 Non-Pharma Stock Picks</div>
                    <div class="portfolio-card-val">${other_val:,.2f}</div>
                    <div class="portfolio-card-sub {'pos-gain' if other_gain >= 0 else 'neg-loss'}">
                        {'▲' if other_gain >= 0 else '▼'} ${abs(other_gain):,.2f} ({(other_gain/10000.0)*100.0:+.2f}%)
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with ocol3:
            st.markdown(
                f"""
                <div class="portfolio-card">
                    <div class="portfolio-card-title">⚡ Net Non-Pharma Alpha vs SPY</div>
                    <div class="portfolio-card-val {'pos-gain' if other_alpha >= 0 else 'neg-loss'}">
                        {'+' if other_alpha >= 0 else '-'}${abs(other_alpha):,.2f}
                    </div>
                    <div class="portfolio-card-sub {'pos-gain' if other_alpha >= 0 else 'neg-loss'}">
                        {'▲ Alpha Outperformance' if other_alpha >= 0 else '▼ Underperformance'} vs S&P 500
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        # --- Section 2: Medical & Pharma Benchmark Cards ---
        st.markdown(
            '<div class="benchmark-section-title title-pharma">'
            '<span>🏥 Category 2: Medical, Pharma & Bio — $10k Benchmark</span>'
            '<span style="font-size: 0.8rem; text-transform: uppercase;">Top 10 Picks Allocation</span>'
            '</div>',
            unsafe_allow_html=True,
        )
        mcol1, mcol2, mcol3 = st.columns(3)
        with mcol1:
            st.markdown(
                f"""
                <div class="portfolio-card">
                    <div class="portfolio-card-title">💵 SPY S&P 500 ($10k Buy & Hold)</div>
                    <div class="portfolio-card-val">${spy_val:,.2f}</div>
                    <div class="portfolio-card-sub {'pos-gain' if spy_gain >= 0 else 'neg-loss'}">
                        {'▲' if spy_gain >= 0 else '▼'} ${abs(spy_gain):,.2f} ({spy_ret:+.2f}%)
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with mcol2:
            st.markdown(
                f"""
                <div class="portfolio-card">
                    <div class="portfolio-card-title">🏥 10x $1,000 Pharma/Bio Stock Picks</div>
                    <div class="portfolio-card-val">${med_val:,.2f}</div>
                    <div class="portfolio-card-sub {'pos-gain' if med_gain >= 0 else 'neg-loss'}">
                        {'▲' if med_gain >= 0 else '▼'} ${abs(med_gain):,.2f} ({(med_gain/10000.0)*100.0:+.2f}%)
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with mcol3:
            st.markdown(
                f"""
                <div class="portfolio-card">
                    <div class="portfolio-card-title">⚡ Net Pharma/Bio Alpha vs SPY</div>
                    <div class="portfolio-card-val {'pos-gain' if med_alpha >= 0 else 'neg-loss'}">
                        {'+' if med_alpha >= 0 else '-'}${abs(med_alpha):,.2f}
                    </div>
                    <div class="portfolio-card-sub {'pos-gain' if med_alpha >= 0 else 'neg-loss'}">
                        {'▲ Alpha Outperformance' if med_alpha >= 0 else '▼ Underperformance'} vs S&P 500
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.markdown("---")
        bcol1, bcol2 = st.columns([4, 1])
        with bcol1:
            st.subheader("Historical Position Performance Tables")
            st.caption(f"📅 Recommended on **{cutoff_date}** ($T_{{-{cutoff_days_ago}}}$) — Performance tracked through **{eval_date}** ($T_0$)")
        with bcol2:
            csv_backtest = pos_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="📥 Export CSV",
                data=csv_backtest,
                file_name=f"backtest_{cutoff_days_ago}d_{cutoff_date}.csv",
                mime="text/csv",
                key=f"dl_us_bt_csv_{cutoff_days_ago}_{custom_cutoff_date}_{cutoff_date}",
            )

        st.subheader("🌐 Top 10: All Other Sectors (Non-Pharma/Bio)")
        st.markdown(build_html_table(df_b_other_top10, is_backtest=True), unsafe_allow_html=True)

        st.subheader("🏥 Top 10: Medical, Pharma & Bio Category")
        st.markdown(build_html_table(df_b_med_top10, is_backtest=True), unsafe_allow_html=True)
    else:
        st.info("No US position data available for this historical backtest date.")

    # --- Section 3: TASE Benchmark Cards & Positions ---
    st.markdown("---")
    st.markdown(
        '<div class="benchmark-section-title title-tase">'
        '<span>🇮🇱 Category 3: Tel Aviv Stock Exchange (TA-125) — $10k Benchmark</span>'
        '<span style="font-size: 0.8rem; text-transform: uppercase;">Top 5 Picks Allocation ($2,000 / position)</span>'
        '</div>',
        unsafe_allow_html=True,
    )

    with st.spinner("Running TASE Point-in-Time Backtest..."):
        try:
            results_tase = run_point_in_time_backtest(
                db_manager,
                cutoff_days_ago=cutoff_days_ago,
                custom_cutoff_date=custom_cutoff_date,
                universe="TASE",
                max_tightness=max_tightness,
                pct_off_low=pct_off_low,
                pct_within_high=pct_within_high,
            )
        except Exception as e:
            logger.warning("Note: TASE backtest execution notice: %s", e)
            results_tase = None

    if results_tase and isinstance(results_tase.get("positions_df"), pd.DataFrame) and not results_tase["positions_df"].empty:
        tase_cutoff = str(results_tase["cutoff_date"])
        tase_eval = str(results_tase["evaluation_date"])
        ta125_ret = float(results_tase.get("ta125_return", results_tase.get("benchmark_return", 0.0))) * 100.0
        pos_df_tase = results_tase["positions_df"].copy()

        pos_df_tase["company_url"] = pos_df_tase["ticker"].apply(lambda t: f"https://finance.yahoo.com/quote/{t}")
        pos_df_tase["company_name"] = pos_df_tase.apply(lambda r: format_company_name(r.get("name"), r["ticker"]), axis=1)
        pos_df_tase["market_cap_str"] = pos_df_tase["market_cap"].apply(
            lambda m: f"{m / 1e9:.2f}B Ag." if pd.notna(m) and m >= 1e9 else (f"{m / 1e6:.1f}M Ag." if pd.notna(m) and m >= 1e6 else "N/A")
        )
        pos_df_tase["win_status"] = pos_df_tase["is_win"].apply(lambda w: "🟢 WIN" if w else "🔴 LOSS")
        pos_df_tase["Company Name"] = pos_df_tase.apply(
            lambda r: f"[{format_company_name(r.get('name'), r['ticker'])}](https://finance.yahoo.com/quote/{r['ticker']})",
            axis=1,
        )

        df_b_tase_top5 = pos_df_tase.head(5)
        n_tase = len(df_b_tase_top5)
        alloc_tase = 10000.0 / n_tase if n_tase > 0 else 2000.0
        tase_val = sum([alloc_tase * (1.0 + (row["return_pct"] / 100.0)) for _, row in df_b_tase_top5.iterrows()]) if n_tase > 0 else 10000.0
        tase_gain = tase_val - 10000.0
        ta125_val = 10000.0 * (1.0 + (ta125_ret / 100.0))
        ta125_gain = ta125_val - 10000.0
        tase_alpha = tase_val - ta125_val

        tcol1, tcol2, tcol3 = st.columns(3)
        with tcol1:
            st.markdown(
                f"""
                <div class="portfolio-card-tase">
                    <div class="portfolio-card-title">🏛️ ^TA125.TA Index ($10k Buy & Hold)</div>
                    <div class="portfolio-card-val">${ta125_val:,.2f}</div>
                    <div class="portfolio-card-sub {'pos-gain' if ta125_gain >= 0 else 'neg-loss'}">
                        {'▲' if ta125_gain >= 0 else '▼'} ${abs(ta125_gain):,.2f} ({ta125_ret:+.2f}%)
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with tcol2:
            st.markdown(
                f"""
                <div class="portfolio-card-tase">
                    <div class="portfolio-card-title">🇮🇱 5x $2,000 TASE Stock Picks</div>
                    <div class="portfolio-card-val">${tase_val:,.2f}</div>
                    <div class="portfolio-card-sub {'pos-gain' if tase_gain >= 0 else 'neg-loss'}">
                        {'▲' if tase_gain >= 0 else '▼'} ${abs(tase_gain):,.2f} ({(tase_gain/10000.0)*100.0:+.2f}%)
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with tcol3:
            st.markdown(
                f"""
                <div class="portfolio-card-tase">
                    <div class="portfolio-card-title">⚡ Net TASE Alpha vs ^TA125.TA</div>
                    <div class="portfolio-card-val {'pos-gain' if tase_alpha >= 0 else 'neg-loss'}">
                        {'+' if tase_alpha >= 0 else '-'}${abs(tase_alpha):,.2f}
                    </div>
                    <div class="portfolio-card-sub {'pos-gain' if tase_alpha >= 0 else 'neg-loss'}">
                        {'▲ Alpha Outperformance' if tase_alpha >= 0 else '▼ Underperformance'} vs TA-125
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.markdown("---")
        tbcol1, tbcol2 = st.columns([4, 1])
        with tbcol1:
            st.subheader("🇮🇱 Top 5: Tel Aviv Stock Exchange (TA-125)")
            st.caption(f"📅 Recommended on **{tase_cutoff}** — Performance tracked through **{tase_eval}** ($T_0$)")
        with tbcol2:
            csv_b_tase = df_b_tase_top5.to_csv(index=False).encode("utf-8")
            date_key = tase_cutoff.replace("-", "")
            st.download_button(
                label="📥 Export TASE CSV",
                data=csv_b_tase,
                file_name=f"tase_backtest_{cutoff_days_ago}d_{date_key}.csv" if not custom_cutoff_date else f"tase_backtest_{date_key}.csv",
                mime="text/csv",
                key=f"dl_tase_bt_csv_{cutoff_days_ago}_{custom_cutoff_date}_{date_key}",
            )

        st.markdown(build_html_table(df_b_tase_top5, is_backtest=True, is_tase=True), unsafe_allow_html=True)
    else:
        st.info("No TASE position data available for this historical backtest date.")

    # Backtest Output Rationale Callout
    st.markdown("### 💡 Backtest Output Guide")
    with st.expander("📊 **What the Backtest Output Tells You**", expanded=True):
        st.markdown(
            f"""
- **$10,000 Investment Benchmark Comparison**
  - *Meaning:* Compares a single **$10,000 buy-and-hold investment in the S&P 500 (`SPY`)** against allocating **$1,000 into each of the model's top 10 recommended stocks** (ignoring share rounding) over the exact same period ($T_{{-{cutoff_days_ago}}} \rightarrow T_0$).
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

    # Initialize session_state defaults for strategy parameters
    if "min_adv20_input" not in st.session_state:
        st.session_state["min_adv20_input"] = 20.0
    if "max_tightness_input" not in st.session_state:
        st.session_state["max_tightness_input"] = 3.5
    if "pct_off_low_input" not in st.session_state:
        st.session_state["pct_off_low_input"] = 30.0
    if "pct_within_high_input" not in st.session_state:
        st.session_state["pct_within_high_input"] = 25.0

    def reset_parameters_callback() -> None:
        st.session_state["min_adv20_input"] = 20.0
        st.session_state["max_tightness_input"] = 3.5
        st.session_state["pct_off_low_input"] = 30.0
        st.session_state["pct_within_high_input"] = 25.0

    st.sidebar.button("🔄 Reset Parameters to Defaults", on_click=reset_parameters_callback)

    min_adv20 = st.sidebar.slider(
        "Min ADV20 Liquidity ($M) ($20M default)",
        min_value=1.0,
        max_value=100.0,
        step=1.0,
        key="min_adv20_input",
        help="Minimum 20-day average daily dollar volume in millions",
    )
    max_tightness = st.sidebar.slider(
        "VCP Tightness Ceiling",
        min_value=1.0,
        max_value=5.0,
        step=0.1,
        key="max_tightness_input",
        help="Maximum allowable 10-day high-low tightness ratio",
    )
    pct_off_low = st.sidebar.slider(
        "Min % Off 52W Low (+30% default)",
        min_value=10.0,
        max_value=60.0,
        step=1.0,
        key="pct_off_low_input",
        help="Stock close price must be at least this % above its 52-week low",
    )
    pct_within_high = st.sidebar.slider(
        "Max % Distance Below 52W High (25% default)",
        min_value=10.0,
        max_value=40.0,
        step=1.0,
        key="pct_within_high_input",
        help="Stock close price must be within this % distance below its 52-week high",
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
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📈 View A: Live Top-10 Recommendations",
        "⏪ View B: 1-Week PIT Backtest",
        "🗓️ View C: 1-Month PIT Backtest",
        "🔬 View D: Custom Diagnostic Lab",
        "🗓️ View E: Custom Date Backtest",
    ])

    with tab1:
        render_live_recommendations(
            db_manager,
            latest_date,
            max_tightness=max_tightness,
            pct_off_low=pct_off_low,
            pct_within_high=pct_within_high,
        )

    with tab2:
        render_backtest_view(
            db_manager,
            cutoff_days_ago=5,
            view_label="View B: 1-Week Backtest",
            max_tightness=max_tightness,
            pct_off_low=pct_off_low,
            pct_within_high=pct_within_high,
        )

    with tab3:
        render_backtest_view(
            db_manager,
            cutoff_days_ago=22,
            view_label="View C: 1-Month Backtest",
            max_tightness=max_tightness,
            pct_off_low=pct_off_low,
            pct_within_high=pct_within_high,
        )

    with tab4:
        if not manual_tickers:
            st.info("👈 Enter one or more stock tickers in the sidebar field **'Ticker(s) to Analyze'** (e.g. `NVDA, AAPL, TSLA`) to launch custom diagnostics.")
        else:
            st.header(f"View D: Custom Analysis for {', '.join(manual_tickers)}")

            # Date Selector for View D Diagnostic Evaluation
            r_rows = db_manager.execute_read("SELECT MIN(trade_date), MAX(trade_date) FROM daily_bars;")
            min_d_val = datetime.strptime(str(r_rows[0][0]), "%Y-%m-%d").date() if r_rows and r_rows[0][0] else datetime.now().date()
            max_d_val = datetime.strptime(str(r_rows[0][1]), "%Y-%m-%d").date() if r_rows and r_rows[0][1] else datetime.now().date()

            v4_col1, v4_col2 = st.columns([1, 2])
            with v4_col1:
                v4_chosen_date = st.date_input(
                    "Evaluation Cutoff Date",
                    value=max_d_val,
                    min_value=min_d_val,
                    max_value=max_d_val,
                    key="view_d_date_picker",
                    help="Choose the historical trading date on which to diagnose custom stock tickers",
                )
            v4_date_str = v4_chosen_date.strftime("%Y-%m-%d")

            with st.expander("⏱️ **Evaluation Date & Technical Lookback Windows Guide**", expanded=False):
                st.markdown(
                    f"""
### 📊 Evaluation Date: `{v4_date_str}`

When diagnosing stocks on `{v4_date_str}`, each checklist criterion measures historical price action over specific lookback timeframes:

1. **Price Floor (>= $10.00)**: Single-day close price on `{v4_date_str}`.
2. **ADV20 Liquidity (>= $20M)**: **20 Trading Days** (~1 month) average daily volume x close price prior to `{v4_date_str}`.
3. **Moving Averages (50/150/200)**: **50, 150, and 200 Trading Days** Simple Moving Averages prior to `{v4_date_str}`. Must satisfy Close > SMA50 > SMA150 > SMA200.
4. **200D SMA Slope Trajectory**: Compares SMA200 on `{v4_date_str}` vs SMA200 **20 Trading Days Ago**. Must be strictly rising.
5. **52-Week Low Bound (>= +30%)**: Minimum low price over **252 Trading Days** (~1 year). Close must be >= +30% above 52W low.
6. **52-Week High Bound (<= 25%)**: Maximum high price over **252 Trading Days** (~1 year). Close must be within 25% distance below 52W high.
7. **VCP Tightness Compression (<= 3.5)**: **10 Trading Days** High-Low consolidation range divided by 14-day Average True Range (ATR14).
8. **Mansfield Relative Strength vs SPY**: Outperformance vs S&P 500 (`SPY`) over **63 Trading Days (3M)** and **252 Trading Days (12M)**.
"""
                )

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
                if st.button(f"📥 Download Data for {', '.join(missing_tickers)}"):
                    with st.spinner(f"Ingesting daily bar data for {', '.join(missing_tickers)}..."):
                        from src.ingestion.data_ingestor import DataIngestor
                        ingestor = DataIngestor(db_manager=db_manager)
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
                df_manual = run_screener(
                    db_manager,
                    cutoff_date=v4_date_str,
                    manual_tickers=found_tickers,
                    max_tightness=max_tightness,
                    pct_off_low=pct_off_low,
                    pct_within_high=pct_within_high,
                )
                df_manual = df_manual[df_manual["ticker"].isin(found_tickers)].copy()

                if not df_manual.empty:
                    st.markdown(f"### 📋 Stage-2 Diagnostic Evaluation & PM Feedback (Cutoff Date: `{v4_date_str}`)")

                    df_top10 = run_screener(
                        db_manager,
                        cutoff_date=v4_date_str,
                        universe="US",
                        max_tightness=max_tightness,
                        pct_off_low=pct_off_low,
                        pct_within_high=pct_within_high,
                    )
                    top10_set = set(df_top10["ticker"].tolist()) if isinstance(df_top10, pd.DataFrame) and not df_top10.empty else set()

                    try:
                        df_tase_top = run_screener(
                            db_manager,
                            cutoff_date=v4_date_str,
                            universe="TASE",
                            max_tightness=max_tightness,
                            pct_off_low=pct_off_low,
                            pct_within_high=pct_within_high,
                        )
                        top5_tase_set = set(df_tase_top.head(5)["ticker"].tolist()) if isinstance(df_tase_top, pd.DataFrame) and not df_tase_top.empty else set()
                    except Exception:
                        top5_tase_set = set()

                    for _, row in df_manual.iterrows():
                        tick = row["ticker"]
                        name_str = format_company_name(row.get("name"), tick)
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

                        is_tase_item = is_tase_ticker(str(tick))

                        # 8-Point Stage-2 Health Diagnostics (Universe-Aware)
                        p_price = pd.notna(close_val) and (close_val >= 100.0 if is_tase_item else close_val >= 10.0)
                        p_adv = pd.notna(adv_val) and adv_val >= 20000000.0
                        p_ma = pd.notna(close_val) and pd.notna(sma50_val) and pd.notna(sma150_val) and pd.notna(sma200_val) and (close_val > sma50_val > sma150_val > sma200_val)
                        p_slope = pd.notna(sma200_val) and pd.notna(sma200_20d_val) and sma200_val > sma200_20d_val
                        p_low52 = pd.notna(close_val) and pd.notna(low52_val) and close_val >= 1.30 * low52_val
                        p_high52 = pd.notna(close_val) and pd.notna(high52_val) and close_val >= 0.75 * high52_val
                        p_tight = pd.notna(tight_val) and tight_val <= 3.5
                        p_rs = pd.notna(rs_val) and rs_val > 0.0

                        passed_count = sum([p_price, p_adv, p_ma, p_slope, p_low52, p_high52, p_tight, p_rs])
                        was_in_top = (tick in top5_tase_set) if is_tase_item else (tick in top10_set)
                        is_passing_all = passed_count == 8

                        reasons = []
                        if not p_price:
                            reasons.append(f"Price ({close_val:.2f} Ag.) is below 100.0 Ag. floor" if is_tase_item else f"Price (${close_val:.2f}) is below $10.00 floor")
                        if not p_adv:
                            reasons.append(f"ADV20 ({adv_val/1e6:.2f}M Ag.) is below 20M Ag. liquidity floor" if is_tase_item else f"ADV20 (${adv_val/1e6:.2f}M) is below $20M liquidity floor")
                        if not p_ma: reasons.append("Moving averages break Close > SMA50 > SMA150 > SMA200 alignment")
                        if not p_slope: reasons.append("200D SMA is not trending upward vs 20 days ago")
                        if not p_low52:
                            reasons.append(f"Price ({close_val:,.2f} Ag.) is < +30% above 52W Low ({low52_val:,.2f} Ag.)" if is_tase_item else f"Price (${close_val:.2f}) is < +30% above 52W Low (${low52_val:.2f})")
                        if not p_high52:
                            reasons.append(f"Price ({close_val:,.2f} Ag.) exceeds 25% distance from 52W High ({high52_val:,.2f} Ag.)" if is_tase_item else f"Price (${close_val:.2f}) exceeds 25% distance from 52W High (${high52_val:.2f})")
                        if not p_tight: reasons.append(f"Tightness Ratio ({tight_val:.2f}) exceeds 3.5 ceiling")
                        if not p_rs:
                            reasons.append(f"Mansfield RS ({rs_val:.4f}) shows underperformance vs ^TA125.TA" if is_tase_item else f"Mansfield RS ({rs_val:.4f}) shows underperformance vs SPY")

                        with st.expander(f"📌 **{tick}** — {name_str} (Diagnostic Score: {passed_count}/8 Passed)", expanded=True):
                            # Visual Health Meter Progress Bar
                            st.progress(passed_count / 8.0, text=f"Stage-2 Health Score: **{passed_count} / 8 Checklist Criteria Passed**")

                            # 8-Point Grid Display
                            gcol1, gcol2, gcol3, gcol4 = st.columns(4)
                            with gcol1:
                                st.markdown(f"**{'Price Floor (100 Ag.)' if is_tase_item else 'Price Floor ($10)'}:** {'🟢 PASS' if p_price else '🔴 FAIL'}")
                                st.markdown(f"**{'Liquidity (20M Ag.)' if is_tase_item else 'Liquidity ($20M)'}:** {'🟢 PASS' if p_adv else '🔴 FAIL'}")
                            with gcol2:
                                st.markdown(f"**MA Alignment:** {'🟢 PASS' if p_ma else '🔴 FAIL'}")
                                st.markdown(f"**200D Slope:** {'🟢 PASS' if p_slope else '🔴 FAIL'}")
                            with gcol3:
                                st.markdown(f"**52W Low (+30%):** {'🟢 PASS' if p_low52 else '🔴 FAIL'}")
                                st.markdown(f"**52W High (-25%):** {'🟢 PASS' if p_high52 else '🔴 FAIL'}")
                            with gcol4:
                                st.markdown(f"**VCP Tightness:** {'🟢 PASS' if p_tight else '🔴 FAIL'}")
                                st.markdown(f"**{'RS vs ^TA125.TA' if is_tase_item else 'Relative Strength'}:** {'🟢 PASS' if p_rs else '🔴 FAIL'}")

                            st.markdown("---")
                            dcol1, dcol2 = st.columns(2)
                            with dcol1:
                                st.markdown(f"**Percentile Composite Rating:** `{comp_val:.2f} / 100`")
                            with dcol2:
                                qual_label = "View A Top 5 (TASE) Qualification" if is_tase_item else "View A Top 10 Qualification"
                                qual_text = ("⭐ Qualified in Top 5 (TASE)" if is_tase_item else "⭐ Qualified in Top 10") if was_in_top else ("Outside Top Ranking" if is_passing_all else "❌ Disqualified (Failed Criteria)")
                                st.markdown(f"**{qual_label}:** {qual_text}")

                            if is_passing_all:
                                st.success(f"**PM Verdict:** {tick} passes all Stage-2 trend template, liquidity, 52W bounds, SMA slope trajectory, and VCP tightness filters!")
                            else:
                                st.warning(f"**PM Feedback — Why {tick} did not qualify:**\n" + "\n".join([f"- {r}" for r in reasons]))

                    df_manual["pct_off_52w_high"] = ((df_manual["close"] / df_manual["high_52w"]) - 1.0) * 100.0
                    df_manual["company_url"] = df_manual["ticker"].apply(lambda t: f"https://finance.yahoo.com/quote/{t}")
                    df_manual["company_name"] = df_manual.apply(lambda r: format_company_name(r.get("name"), r["ticker"]), axis=1)
                    df_manual["ADV20"] = df_manual.apply(
                        lambda r: (f"{r['adv_20'] / 1e6:,.1f}M Ag." if is_tase_ticker(str(r['ticker'])) else (f"${r['adv_20'] / 1e9:.2f}B" if pd.notna(r['adv_20']) and r['adv_20'] >= 1e9 else f"${r['adv_20'] / 1e6:.1f}M")),
                        axis=1
                    )
                    df_manual["market_cap_str"] = df_manual.apply(
                        lambda r: (f"{r['market_cap'] / 1e9:.2f}B Ag." if is_tase_ticker(str(r['ticker'])) and pd.notna(r['market_cap']) else (f"${r['market_cap'] / 1e9:.2f}B" if pd.notna(r['market_cap']) and r['market_cap'] >= 1e9 else "N/A")),
                        axis=1
                    )

                    df_manual["Company Name"] = df_manual.apply(
                        lambda r: f"[{format_company_name(r.get('name'), r['ticker'])}](https://finance.yahoo.com/quote/{r['ticker']})",
                        axis=1
                    )

                    sorted_d_df = df_manual.sort_values(by="composite_score", ascending=False)
                    sorted_d_df["is_tase"] = sorted_d_df["ticker"].apply(is_tase_ticker)
                    sorted_d_df["is_med_pharma"] = sorted_d_df.apply(
                        lambda r: is_medical_pharma(format_company_name(r.get("name"), ""), str(r["ticker"])), axis=1
                    )

                    df_d_other_top10 = sorted_d_df[(~sorted_d_df["is_med_pharma"]) & (~sorted_d_df["is_tase"])].head(10)
                    df_d_med_top10 = sorted_d_df[(sorted_d_df["is_med_pharma"]) & (~sorted_d_df["is_tase"])].head(10)
                    df_d_tase_top5 = sorted_d_df[sorted_d_df["is_tase"]].head(5)

                    if not df_d_other_top10.empty:
                        st.subheader("🌐 Top 10: All Other Sectors (Non-Pharma/Bio)")
                        st.markdown(build_html_table(df_d_other_top10, is_backtest=False, is_tase=False), unsafe_allow_html=True)

                    if not df_d_med_top10.empty:
                        st.subheader("🏥 Top 10: Medical, Pharma & Bio Category")
                        st.markdown(build_html_table(df_d_med_top10, is_backtest=False, is_tase=False), unsafe_allow_html=True)

                    if not df_d_tase_top5.empty:
                        st.subheader("🇮🇱 Top 5: Tel Aviv Stock Exchange (TA-125)")
                        st.markdown(build_html_table(df_d_tase_top5, is_backtest=False, is_tase=True), unsafe_allow_html=True)

    with tab5:
        st.subheader("🗓️ Custom Historical Date Point-in-Time Backtest")
        st.markdown("Select any historical date to evaluate model picks and track their forward performance through today.")
        
        # Get date range from daily_bars
        range_rows = db_manager.execute_read("SELECT MIN(trade_date), MAX(trade_date) FROM daily_bars;")
        min_date_val = datetime.strptime(str(range_rows[0][0]), "%Y-%m-%d").date() if range_rows and range_rows[0][0] else datetime.now().date()
        max_date_val = datetime.strptime(str(range_rows[0][1]), "%Y-%m-%d").date() if range_rows and range_rows[0][1] else datetime.now().date()
        
        # Default custom date to 10 trading days ago
        default_custom_date = max_date_val - timedelta(days=14)

        chosen_date = st.date_input(
            "Select Backtest Cutoff Date",
            value=default_custom_date,
            min_value=min_date_val,
            max_value=max_date_val,
            help="Choose a historical trading date between available dataset range",
        )

        chosen_date_str = chosen_date.strftime("%Y-%m-%d")

        render_backtest_view(
            db_manager,
            custom_cutoff_date=chosen_date_str,
            view_label=f"View E: Custom Date ({chosen_date_str}) Backtest",
            max_tightness=max_tightness,
            pct_off_low=pct_off_low,
            pct_within_high=pct_within_high,
        )


if __name__ == "__main__":
    main()
