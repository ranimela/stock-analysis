# Quantitative Screener & Analysis Engine Investigation Report
**Project:** Tel Aviv Stock Exchange (TASE / TA-125) Integration  
**Investigator:** Explorer 2 (Quantitative Engine Investigator)  
**Date:** 2026-08-27  
**Scope:** Quantitative screening, indicator mathematics, relative strength benchmarking, universe separation, and point-in-time backtesting.

---

## 1. Executive Summary

This report documents the architectural and quantitative analysis of the Stock Scanner Engine for integrating equities listed on the **Tel Aviv Stock Exchange (TASE)**, specifically the **TA-125 constituent universe**, alongside the existing US equity universe (NYSE / NASDAQ / AMEX).

### Core Findings & Conclusions:
1. **Mathematical Scale Invariance:** Price-ratio indicators—including the **Minervini Trend Template** ($Close > SMA_{50} > SMA_{150} > SMA_{200}$), **52-Week High/Low Proximity** ($Close \ge 1.30 \times Low_{52W}$ and $Close \ge 0.75 \times High_{52W}$), **VCP Tightness Ratio** ($TR_{10D} / ATR_{14}$), and **Mansfield Relative Strength** ($RS_{63}, RS_{252}$)—are dimensionless ratios and are **100% scale-invariant**, functioning identically on Israeli Agorot (ILA) and US Dollars (USD).
2. **Dedicated Benchmark Engine (`^TA125.TA`):** TASE equities must be evaluated against the **TA-125 index benchmark (`^TA125.TA`)**, while US equities evaluate against `SPY`. Benchmarking Israeli equities against `SPY` introduces severe currency distortion and calendar mismatch.
3. **Calendar Independence:** TASE operates on a **Sunday–Thursday** trading schedule, while US markets operate **Monday–Friday**. Because DuckDB daily bars are indexed by `(ticker, trade_date)` and Relative Strength joins against the respective benchmark (`^TA125.TA` vs `SPY`), the trading schedules are completely decoupled with zero calendar collision.
4. **Universe-Isolated Ranking:** Percentile ranking (`PERCENT_RANK()`) for composite scoring must be partitioned by universe (`exchange = 'TASE'` vs US equities) so that the TASE Top 5 recommendations are generated from an internal peer ranking of TA-125 constituents rather than competing across US market distributions.
5. **Liquidity Calibration:** Yahoo Finance quotes TASE equity prices in Israeli Agorot ($1 \text{ ILS} = 100 \text{ Agorot}$). In raw terms, daily volume turnover is in Agorot. A dedicated TASE liquidity threshold (e.g. $1,000,000 \text{ ILS} = 100,000,000 \text{ Agorot}$) or flexible threshold handling must be specified.

---

## 2. Quantitative Screening & Scoring Architecture

### 2.1 Component & Module Map

| Module Path | Primary Classes / Functions | Responsibility |
|:---|:---|:---|
| `src/db/db_manager.py` | `DatabaseManager` | Thread-safe DuckDB connection pooling, read/write cursor context managers, schema initialization. |
| `src/db/schema.sql` | DDL Statements | Tables: `symbol_metadata`, `daily_bars`, `point_in_time_runs`. |
| `src/engine/screener_queries.py` | `run_screener()`, `SCREENER_SQL` | Parameterized DuckDB window functions executing Stages 1–4 screening and composite ranking. |
| `src/engine/backtest_engine.py` | `run_point_in_time_backtest()` | Simulates historical point-in-time scans ($T_{-5}, T_{-22}$, custom dates) and calculates forward returns, benchmark returns, alpha, win rates, and peak-to-trough max drawdown. |
| `src/ingestion/symbol_directory.py` | `fetch_symbol_directory()`, `sync_symbol_metadata()` | Discovers and normalizes equity metadata, applying common stock filtering rules. |
| `src/ingestion/data_ingestor.py` | `DataIngestor` (`sync_universe()`, `download_spy()`, `parse_and_store_bars()`) | Batch downloads 2-year OHLCV bars via `yfinance` into DuckDB with delta sync logic. |
| `src/cli.py` | `main()`, `seed()`, `update()`, `scan()` | Command-line orchestration for seeding, updating, delta sync, and terminal reporting. |
| `src/ui/app.py` | `main()`, `render_live_recommendations()`, `render_backtest_view()` | Zero-write Streamlit frontend displaying Views A, B, C, D, and E. |

---

## 3. Mathematical Indicator Implementations & TASE Behavior

### 3.1 Stage 1: Liquidity & Asset Class Gate
* **Asset Class Filter:** Excludes ETFs, CEFs, ADRs, warrants, preferreds, units, and SPACs (`asset_class = 'Common Stock'`).
* **Price Floor:**
  $$\text{Close}_t \ge \text{Price Floor}$$
  * *US Equities:* $\text{Close}_t \ge \$10.00$.
  * *TASE Equities:* Yahoo Finance quotes in Agorot (ILA). $\text{Close}_t \ge 100.0 \text{ Agorot}$ ($1.00 \text{ ILS}$).
* **20-Day Average Daily Volume Turnover ($ADV_{20}$):**
  $$ADV_{20}(t) = \frac{1}{20} \sum_{i=0}^{19} (\text{Close}_{t-i} \times \text{Volume}_{t-i})$$
  * *US Equities:* $ADV_{20} \ge \$20,000,000 \text{ USD}$.
  * *TASE Equities:* On Yahoo Finance, $\text{Close}$ is in Agorot, $\text{Volume}$ is shares. Turnover in Agorot $= \text{Close} \times \text{Volume}$. Turnover in $\text{ILS} = \frac{\text{Close} \times \text{Volume}}{100}$. For TA-125 constituents, average daily turnover ranges from $1\text{M ILS}$ to $200\text{M ILS}$ ($100\text{M}$ to $20\text{B Agorot}$). A default liquidity floor of $1,000,000 \text{ ILS}$ ($100,000,000 \text{ Agorot}$) or $20,000,000 \text{ Agorot}$ ($200,000 \text{ ILS}$) passes liquid TA-125 equities.

### 3.2 Stage 2: Minervini Trend Template
All Stage 2 criteria are ratio-based and dimensionless:
1. **Moving Average Alignment:**
   $$\text{Close}_t > \text{SMA}_{50}(t) > \text{SMA}_{150}(t) > \text{SMA}_{200}(t)$$
2. **200-Day SMA Trajectory (Structural Slope):**
   $$\text{SMA}_{200}(t) > \text{SMA}_{200}(t-20)$$
3. **52-Week Range Proximity:**
   $$\text{Close}_t \ge \left(1.0 + \frac{\text{pct\_off\_low}}{100}\right) \times \min_{i \in [0, 251]}(\text{Low}_{t-i}) \quad (\text{default: } \ge 1.30 \times \text{Low}_{52W})$$
   $$\text{Close}_t \ge \left(1.0 - \frac{\text{pct\_within\_high}}{100}\right) \times \max_{i \in [0, 251]}(\text{High}_{t-i}) \quad (\text{default: } \ge 0.75 \times \text{High}_{52W})$$

### 3.3 Stage 3: Volatility Contraction Pattern (VCP) & Volume Dry-Up (VDU)
* **True Range ($TR_t$) & Average True Range ($ATR_{14}$):**
  $$TR_t = \max(\text{High}_t - \text{Low}_t, \, |\text{High}_t - \text{Close}_{t-1}|, \, |\text{Low}_t - \text{Close}_{t-1}|)$$
  $$ATR_{14}(t) = \frac{1}{14} \sum_{i=0}^{13} TR_{t-i}$$
* **10-Day Consolidation Tightness Ratio ($TR_{10D}$):**
  $$TR_{10D}(t) = \frac{\max_{i \in [0,9]}(\text{High}_{t-i}) - \min_{i \in [0,9]}(\text{Low}_{t-i})}{ATR_{14}(t)} \le \text{max\_tightness} \quad (\text{default: } \le 3.5)$$
  *Note:* Because numerator ($\text{High}_{10D} - \text{Low}_{10D}$) and denominator ($ATR_{14}$) share the same currency/unit scale (whether USD or Agorot), $TR_{10D}$ is purely dimensionless.
* **Volume Dry-Up (VDU Ratio):**
  $$\text{VDU Ratio} = \frac{\text{Volume}_t}{\text{SMA}_{\text{Vol}, 50}(t)} \le 0.60$$

### 3.4 Stage 4: Relative Strength & Composite Scoring
* **Mansfield Relative Strength ($RS$):**
  $$RS_{63, i} = \frac{\text{Stock}_{i, t} / \text{Stock}_{i, t-63}}{\text{Benchmark}_t / \text{Benchmark}_{t-63}} - 1.0 \quad \text{(3-Month Relative Return)}$$
  $$RS_{252, i} = \frac{\text{Stock}_{i, t} / \text{Stock}_{i, t-252}}{\text{Benchmark}_t / \text{Benchmark}_{t-252}} - 1.0 \quad \text{(12-Month Relative Return)}$$
  $$RS_{\text{Score}, i} = 0.70 \times RS_{63, i} + 0.30 \times RS_{252, i}$$
* **Benchmark Association:**
  * **US Equities:** $\text{Benchmark} = \text{SPY}$ (S&P 500 ETF)
  * **TASE Equities:** $\text{Benchmark} = \text{^TA125.TA}$ (TA-125 Index)
* **Percentile Composite Score ($S_i \in [0, 100]$):**
  $$S_i = 0.60 \times \mathcal{P}(RS_{\text{Score}, i}) + 0.40 \times \mathcal{P}\left(\frac{1}{TR_{10D, i}}\right)$$
  Where $\mathcal{P}(X)$ is the empirical percentile rank (`PERCENT_RANK() * 100.0`) evaluated across the passing universe.

---

## 4. Stock Universe Separation & Point-in-Time Backtesting

### 4.1 Schema Integration Points

```
========================================================================================
                                    DUCKDB TABLES
========================================================================================

 ┌──────────────────────────────────────┐     ┌──────────────────────────────────────┐
 │           symbol_metadata            │     │              daily_bars              │
 ├──────────────────────────────────────┤     ├──────────────────────────────────────┤
 │ ticker           VARCHAR (PK)        │     │ ticker           VARCHAR (PK)        │
 │ name             VARCHAR             │     │ trade_date       DATE    (PK)        │
 │ exchange         VARCHAR             │────<│ open             DOUBLE              │
 │ asset_class      VARCHAR             │     │ high             DOUBLE              │
 │ market_cap       DOUBLE              │     │ low              DOUBLE              │
 │ is_active        BOOLEAN             │     │ close            DOUBLE              │
 │ first_added_date DATE                │     │ adj_close        DOUBLE              │
 │ last_updated_date DATE               │     │ volume           HUGEINT             │
 └──────────────────────────────────────┘     └──────────────────────────────────────┘
      │ exchange = 'TASE' (Israel)                 │ TASE tickers: '<SYM>.TA', '^TA125.TA'
      │ exchange = 'NASDAQ'/'NYSE' (US)            │ US tickers: 'AAPL', 'SPY', etc.
```

### 4.2 Screener Query Architecture (`run_screener`)

To support universe separation cleanly without duplicate code paths, `run_screener` should support a `universe` parameter (`"US"` | `"TASE"` | `"ALL"`):

```python
def run_screener(
    db_manager: DatabaseManager,
    cutoff_date: str,
    max_tightness: float = 3.5,
    manual_tickers: list[str] | None = None,
    pct_off_low: float = 30.0,
    pct_within_high: float = 25.0,
    universe: str = "US",  # "US" or "TASE"
) -> pd.DataFrame:
    ...
```

#### Key Parameterizations per Universe:
1. **Benchmark Ticker:**
   * If `universe == "US"`: `benchmark_ticker = 'SPY'`
   * If `universe == "TASE"`: `benchmark_ticker = '^TA125.TA'`
2. **Exchange Filter:**
   * If `universe == "US"`: `ls.exchange != 'TASE'` (or `ls.exchange IN ('NASDAQ', 'NYSE', 'AMEX', 'ARCA', 'BATS')`)
   * If `universe == "TASE"`: `ls.exchange = 'TASE'`
3. **Exclusion Clause:**
   * US: `ls.ticker != 'SPY' AND ls.ticker NOT LIKE '^%'`
   * TASE: `ls.ticker != '^TA125.TA' AND ls.ticker NOT LIKE '^%'`
4. **Liquidity Filter ($ADV_{20}$):**
   * US: `ls.adv_20 >= 20000000.0` ($20M USD)
   * TASE: `ls.adv_20 >= 20000000.0` (20M Agorot = 200k ILS) or customizable threshold.
5. **Price Floor:**
   * US: `ls.close >= 10.0` ($10.00 USD)
   * TASE: `ls.close >= 100.0` (100 Agorot = 1.00 ILS)

### 4.3 Backtest Engine Architecture (`run_point_in_time_backtest`)

```python
def run_point_in_time_backtest(
    db_manager: DatabaseManager,
    cutoff_days_ago: int = 5,
    custom_cutoff_date: str | None = None,
    max_tightness: float = 3.5,
    pct_off_low: float = 30.0,
    pct_within_high: float = 25.0,
    universe: str = "US",  # "US" or "TASE"
) -> dict[str, float | str | int | pd.DataFrame]:
    ...
```

* **Benchmark Returns:**
  * For `universe == "US"`: Fetches `SPY` bars between `cutoff_date` and `eval_date`.
    $$R_{\text{SPY}} = \frac{\text{Close}_{\text{SPY}}(T_0) - \text{Close}_{\text{SPY}}(T_{\text{cut}})}{\text{Close}_{\text{SPY}}(T_{\text{cut}})}$$
  * For `universe == "TASE"`: Fetches `^TA125.TA` bars between `cutoff_date` and `eval_date`.
    $$R_{\text{TA125}} = \frac{\text{Close}_{\text{TA125}}(T_0) - \text{Close}_{\text{TA125}}(T_{\text{cut}})}{\text{Close}_{\text{TA125}}(T_{\text{cut}})}$$
* **Basket Alpha:**
  $$\text{Alpha}_{\text{TASE}} = \bar{R}_{\text{TASE Basket}} - R_{\text{TA125}}$$

---

## 5. UI Layout Specification for Dedicated TASE Section (R3)

In accordance with requirement R3 across Views A, B, C, D, and E:

### 5.1 View A: Live Top 10 US + Top 5 TASE
* **Primary Container 1 (Top):**
  * Section 1: Non-Pharma Top 10 (US Equities)
  * Section 2: Medical & Pharma Top 10 (US Equities)
* **Dedicated High-Contrast Container 2 (Bottom):**
  * Title: `🇮🇱 Top 5 Tel Aviv Stock Exchange (TA-125) Stage-2 Recommendations`
  * High-contrast card/table with TASE-specific styling.
  * Columns: `Company Name`, `Market Cap (ILS / USD)`, `Price (Agorot / ILS)`, `ADV20 (ILS)`, `RS Score (vs TA-125)`, `Tightness Ratio`, `% Off 52W High`, `Composite Score`.
  * Company links point to `https://finance.yahoo.com/quote/<TICKER>.TA`.

### 5.2 Views B, C, and E: Backtest Views (T-5, T-22, Custom Date)
* **Section 1 (Top):** US $10,000 Portfolio Benchmark vs `SPY` ($10k SPY vs 10x $1,000 US Picks).
* **Section 2 (Bottom):** Dedicated TASE ₪10,000 (or $10,000) Portfolio Benchmark vs `^TA125.TA`:
  * Card 1: `^TA125.TA` Index Buy & Hold Return.
  * Card 2: 5x Equal-Weighted TASE Stock Picks Return.
  * Card 3: Net TASE Alpha vs TA-125 Index.
  * Detailed Position Performance Table: Entry Price, Exit Price, Stock Return (%), TA-125 Return (%), Alpha (%), Max Drawdown (%), Win/Loss Status.

### 5.3 View D: Custom Diagnostic Lab
* Entering `.TA` tickers (e.g. `TEVA.TA, NICE.TA, LUMI.TA`) evaluates them against TASE-specific parameters and the `^TA125.TA` benchmark, displaying the 8-point checklist and Stage-2 health diagnostics.

---

## 6. Edge Cases & Technical Nuances

| Edge Case | Nuance / Risk | Architectural Solution |
|:---|:---|:---|
| **Trading Calendars** | TASE trades Sun–Thu; US trades Mon–Fri. Sundays have TASE data but no US data; Fridays have US data but no TASE data. | Decoupled queries. Screener query for TASE anchors on `MAX(trade_date)` for `^TA125.TA` / TASE; US anchors on `SPY` / US. Joins on `trade_date` are intra-market. |
| **Price Units (Agorot vs ILS)** | Yahoo quotes prices in Agorot ($100 \text{ Agorot} = 1 \text{ ILS}$). | Ratios (SMAs, ATR, % Returns, High/Low range) are scale-invariant. Price floor set to $\ge 100 \text{ Agorot}$ ($\ge 1 \text{ ILS}$). In UI, prices and turnover are formatted with clear labels (`Ag / ₪`). |
| **ADV20 Volume Units** | In raw database, $\text{Close} \times \text{Volume}$ is in Agorot. | $20,000,000 \text{ Agorot} = 200,000 \text{ ILS} \approx \$55\text{k USD}$. Filter threshold calibrated to TASE market size (e.g. $20\text{M Agorot}$ or $100\text{M Agorot}$). In UI, displayed as $\text{ADV}_{20} / 100$ in $\text{₪M}$. |
| **History Requirement** | 252 trading days needed for SMA200 slope, 52W High/Low, and RS252. | Data ingestor fetches 2 full years of historical bars for `^TA125.TA` and all TA-125 tickers during initial seeding/sync. |
| **Small Universe Size** | TA-125 universe is 125 stocks vs 5,000+ US stocks. | Fallback query mechanism or returning `df.head(5)` of passing candidates gracefully handles periods where fewer than 5 stocks meet strict VCP tightness. |
| **Benchmark Ingestion Gate** | Ingestion pipeline requires hard-gated benchmark sync before universe sync. | Ingestor hard-gates `^TA125.TA` benchmark download during TASE sync, mirroring `download_spy()` for US sync. |

---

## 7. Implementation Recommendations for Planner & Builder

1. **Update `src/engine/screener_queries.py`:**
   - Add parameter `universe: str = "US"` to `run_screener`.
   - Parametrize the SQL benchmark join (`SPY` vs `^TA125.TA`), exchange filter (`exchange = 'TASE'` vs `exchange != 'TASE'`), and exclusion clauses.
2. **Update `src/engine/backtest_engine.py`:**
   - Add parameter `universe: str = "US"` to `run_point_in_time_backtest`.
   - Query forward prices for `^TA125.TA` when `universe == "TASE"` and compute alpha against `^TA125.TA`.
3. **Update `src/ui/app.py`:**
   - In `render_live_recommendations`: Call `run_screener(..., universe="TASE")` and render the dedicated **Top 5 TASE Recommendations** card and table below the US Top 10.
   - In `render_backtest_view`: Call `run_point_in_time_backtest(..., universe="TASE")` and render the dedicated TASE benchmark cards and position table.
   - In View D: Auto-detect `.TA` tickers or exchange to evaluate against `^TA125.TA`.
4. **Update `src/cli.py`:**
   - In `scan` command: Execute both US screener (Top 10) and TASE screener (Top 5) and output both summary sections.
5. **Unit Tests:**
   - Add unit tests in `src/engine/test_engine.py` verifying TASE screening, scoring, and point-in-time backtesting with synthetic TASE and `^TA125.TA` data.
