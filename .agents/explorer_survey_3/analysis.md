# Comprehensive Investigation: Streamlit UI & Test Infrastructure for TASE Integration

## Executive Summary

This report delivers the structural analysis of the Streamlit dashboard (`src/ui/app.py`), backend integration surfaces, and test infrastructure for the integration of the **Tel Aviv Stock Exchange (TASE / TA-125 universe)**.

The primary objective for the UI layer is to render a **dedicated, high-contrast visual section for the "Top 5 TASE" momentum recommendations** placed directly below the US Top 10 across all five active views (**Views A, B, C, D, and E**), without disrupting existing US equity screening or mixing US and Israeli market metrics.

---

## 1. Streamlit Application Architecture & View Inventory

The dashboard is housed in `src/ui/app.py` and provides a zero-write-access interactive terminal connected to DuckDB (`market_data.duckdb`).

### View Breakdown

| View | Tab Title | Handler Function | Core Purpose | Current Output Format |
|---|---|---|---|---|
| **View A** | `📈 View A: Live Top-10 Recommendations` | `render_live_recommendations()` | Live Stage-2 momentum recommendations at latest EOD ($T_0$) | 2 sub-tables (Non-Pharma Top 10 & Medical/Pharma Top 10) rendered via custom HTML table, CSV export, filter guide |
| **View B** | `⏪ View B: 1-Week PIT Backtest` | `render_backtest_view(cutoff_days_ago=5)` | Point-in-time backtest at $T_{-5}$ evaluating forward 5-day performance | $10k Benchmark performance cards (SPY vs Picks vs Net Alpha) + historical position performance tables (Non-Pharma & Pharma) |
| **View C** | `🗓️ View C: 1-Month PIT Backtest` | `render_backtest_view(cutoff_days_ago=22)` | Point-in-time backtest at $T_{-22}$ evaluating forward 22-day performance | $10k Benchmark performance cards (SPY vs Picks vs Net Alpha) + historical position performance tables |
| **View D** | `🔬 View D: Custom Diagnostic Lab` | Inline in `main()` | Single/multi-ticker 8-point Stage-2 technical health checklist at selected date | Ticker status badges, on-demand ingest button, health score progress bar ($X/8$), 4-col diagnostic grid, PM verdict & disqualification breakdown, metric table |
| **View E** | `🗓️ View E: Custom Date Backtest` | `render_backtest_view(custom_cutoff_date=...)` | Historical backtest on user-selected date | $10k Benchmark performance cards + historical position performance tables |

### Global Layout & Configuration
- **Page Config**: `st.set_page_config(page_title="Quantitative Stock Screener & PIT Backtest", layout="wide")`
- **Database Access**: `get_db_manager()` cached via `@st.cache_resource` in strictly read-only mode (`read_only=True`).
- **Sidebar Controls**:
  - `min_adv20_input` slider (default $20.0M)
  - `max_tightness_input` slider (default 3.5)
  - `pct_off_low_input` slider (default 30.0%)
  - `pct_within_high_input` slider (default 25.0%)
  - Reset to defaults callback
  - Custom Ticker input (`manual_input`)
  - Cloud Delta Sync trigger button (`DataIngestor.sync_local_db_from_parquet`)

---

## 2. US Top 10 Rendering Mechanism & Component Contracts

### HTML & CSS Component Hierarchy
The UI uses custom institutional styling injected via `inject_custom_css()`:

```
┌─────────────────────────────────────────────────────────────┐
│ Streamlit Page Container (GitHub Dark Theme #0d1117)        │
│                                                             │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Section Header Banner (.benchmark-section-title)        │ │
│ ├─────────────────────────────────────────────────────────┤ │
│ │ 3-Column Metric Cards (.portfolio-card)                 │ │
│ │  - .portfolio-card-title (uppercase label)              │ │
│ │  - .portfolio-card-val (JetBrains Mono tabular value)   │ │
│ │  - .portfolio-card-sub (.pos-gain / .neg-loss)          │ │
│ ├─────────────────────────────────────────────────────────┤ │
│ │ Custom Table Container (.custom-table-container)        │ │
│ │  └─ <table class="custom-data-table">                   │ │
│ │      ├─ <thead> (th: #f6f8fa background, #57606a text)  │ │
│ │      └─ <tbody> (tr hover: #f3f4f6, td: #1f2328 text)   │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### Table Column Contracts
1. **Live Screener Table Contract** (`build_html_table(..., is_backtest=False)`):
   - `Company Name`: Formatted as interactive anchor `<a class="company-link" href="..." target="_blank">`
   - `Market Cap`: Formatted as `$XB` or `$XM`
   - `Price ($)`: Formatted as `$XX.XX`
   - `ADV20`: Formatted as `$XB` or `$XM`
   - `RS Score`: Mansfield Relative Strength float (`.2f`)
   - `Tightness Ratio`: 10-day range / ATR14 (`.2f`)
   - `% Off 52W High`: Signed percentage (`+X.XX%`)
   - `Composite Score`: Percentile score (`0.00` to `100.00`)

2. **Backtest Table Contract** (`build_html_table(..., is_backtest=True)`):
   - `Company Name`, `Market Cap`, `Entry Price ($)`, `Exit Price ($)`, `Return (%)`, `SPY Return (%)`, `Alpha (%)`, `Max Drawdown (%)`, `Status` (`🟢 WIN` / `🔴 LOSS`).

---

## 3. Dedicated High-Contrast "Top 5 TASE" Visual Design & Implementation

To satisfy Requirement **R3** ("Display the Top 5 TASE recommendations as a dedicated visual section/card below the US Top 10 across Views A, B, C, D, and E"), the following UI architecture must be implemented:

### A. High-Contrast CSS Theme for TASE (`title-tase` and `tase-card`)
Add the following dedicated CSS rules to `inject_custom_css()` in `src/ui/app.py`:

```css
/* Dedicated TASE Israeli High-Contrast Theme */
.title-tase {
    background: linear-gradient(135deg, #e8f4fd 0%, #d0e8fc 100%);
    color: #003884;
    border-left: 6px solid #0052cc;
    border-right: 2px solid #0052cc;
    box-shadow: 0 2px 8px rgba(0, 82, 204, 0.12);
}

.title-tase-dark {
    background: linear-gradient(135deg, #0b2545 0%, #133b68 100%);
    color: #70b5ff;
    border-left: 6px solid #2f81f7;
    border: 1px solid #1f497d;
}

.tase-badge {
    background-color: #0052cc;
    color: #ffffff;
    padding: 3px 8px;
    border-radius: 4px;
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: 0.5px;
    text-transform: uppercase;
}

.portfolio-card-tase {
    border: 2px solid #0052cc;
    border-radius: 10px;
    padding: 16px 20px;
    background-color: #fbfdff;
    box-shadow: 0 4px 14px rgba(0, 82, 204, 0.08);
    margin-bottom: 16px;
}
```

### B. Implementation Across All Views

#### 1. View A (Live Recommendations $T_0$)
- **Data Query**: Query TASE momentum universe via `run_screener(db_manager, cutoff_date=latest_date, exchange="TASE")` or partition the screener result where `exchange == 'TASE'` or `ticker LIKE '%.TA'`.
- **Top 5 Selection**: Extract `df_tase_top5 = df_tase.sort_values(by="composite_score", ascending=False).head(5)`.
- **Placement**: Directly below the US Medical/Pharma table.
- **Visual Section**:
  - Banner:
    ```html
    <div class="benchmark-section-title title-tase">
        <span>🇮🇱 Top 5: Tel Aviv Stock Exchange (TA-125 Universe)</span>
        <span class="tase-badge">TASE Top 5</span>
    </div>
    ```
  - Currency Callout: Caption highlighting `Prices in ILS (₪/Agurot) | Benchmarked against ^TA125.TA`.
  - Table: `build_html_table(df_tase_top5, is_backtest=False, currency_symbol="₪")`.

#### 2. Views B & C (1-Week $T_{-5}$ and 1-Month $T_{-22}$ Backtests)
- **Data Query**: `run_point_in_time_backtest(db_manager, cutoff_days_ago=5, exchange="TASE")` executing against `^TA125.TA` benchmark.
- **Placement**: Directly below the US Backtest tables.
- **Visual Section**:
  - Section Header: `🇮🇱 Category 3: Tel Aviv Stock Exchange (TASE) — $10k / ₪10k Benchmark`
  - 3 High-Contrast Metric Cards:
    1. 🇮🇱 TA-125 Benchmark (`^TA125.TA` Buy & Hold)
    2. 🇮🇱 5x $2,000 / ₪2,000 Top 5 TASE Stock Picks
    3. ⚡ Net TASE Alpha vs TA-125 Index
  - Dedicated Top 5 TASE Historical Position Table (`build_html_table(df_b_tase_top5, is_backtest=True)`).

#### 3. View D (Custom Diagnostic Lab)
- **Ticker Identification**: Inspect ticker suffix `.TA` or `exchange == 'TASE'`.
- **Benchmark Routing**:
  - If TASE equity: Calculate Mansfield Relative Strength against `^TA125.TA` (instead of `SPY`).
  - Checklist item #8 displays: `Mansfield Relative Strength vs TA-125 (^TA125.TA)`.
  - Qualification badge: `⭐ Qualified in Top 5 TASE` vs `Outside Top 5 TASE` vs `❌ Disqualified`.
- **Visual Layout**: If diagnosed tickers include TASE stocks, render a distinct dedicated TASE diagnostic section below US diagnostic cards.

#### 4. View E (Custom Date Backtest)
- Mirrors Views B & C for the user-selected historical cutoff date.
- Displays both US Top 10 and dedicated Top 5 TASE benchmark cards and position tables.

---

## 4. Test Infrastructure Survey

### Test Environment & Execution
- **Framework**: `pytest` 9.1.1 running under Python 3.14.4.
- **Execution Command**:
  ```powershell
  python -m pytest -v
  ```
- **Current Test Status**: 21 passed in 18.64s (100% pass rate).

### Existing Test Suite Inventory

| Test Module | Test Name | Target Functionality | Fixture / Mock Approach |
|---|---|---|---|
| `src/db/test_db_manager.py` | `test_schema_initialization` | Validates tables & column definitions | `tempfile.TemporaryDirectory` |
| `src/db/test_db_manager.py` | `test_read_write_operations` | Validates SQL insert/select | `tempfile.TemporaryDirectory` |
| `src/db/test_db_manager.py` | `test_context_managers` | Validates `read_cursor` & `write_cursor` | `tempfile.TemporaryDirectory` |
| `src/engine/test_engine.py` | `test_screener_execution` | Tests Stage 1-3 filters & ranking | `populate_mock_data(num_days=270)` |
| `src/engine/test_engine.py` | `test_point_in_time_backtest` | Tests T-5 backtest and DB persistence | `populate_mock_data(num_days=270)` |
| `src/engine/test_engine.py` | `test_invalid_cutoff_days` | Validates error on invalid lookback | `populate_mock_data(num_days=270)` |
| `src/engine/test_engine.py` | `test_manual_vs_screener_score_consistency` | Tests composite score math alignment | `populate_mock_data(num_days=270)` |
| `src/ingestion/test_ingestion.py` | `test_is_common_stock_filtering` | Validates ETF, warrant, preferred filters | Unit assertions |
| `src/ingestion/test_ingestion.py` | `test_parse_nasdaqlisted` | Validates pipe-delimited parser | Raw sample text string |
| `src/ingestion/test_ingestion.py` | `test_parse_otherlisted` | Validates exchange mapping | Raw sample text string |
| `src/ingestion/test_ingestion.py` | `test_sync_symbol_metadata` | Validates metadata upsert | `tmp_db` fixture |
| `src/ingestion/test_ingestion.py` | `test_download_spy_hard_gate_failure` | Validates hard gating aborts on error | `unittest.mock.patch("yfinance.download")` |
| `src/ingestion/test_ingestion.py` | `test_parse_and_store_bars` | Validates MultiIndex yfinance parsing | Synthetic `pd.DataFrame` |
| `src/ingestion/test_ingestion.py` | `test_delta_sync_filtering` | Validates max date deduplication | `tmp_db` fixture |
| `src/test_cli_ui.py` | `test_cli_help` | Validates CLI subcommands | `click.testing.CliRunner` |
| `src/test_cli_ui.py` | `test_cli_scan_empty_db` | Validates empty DB handling | `CliRunner` |
| `src/test_cli_ui.py` | `test_cli_scan_populated_db` | Validates CLI scan output | `populated_db` fixture (300 bars) |
| `src/test_cli_ui.py` | `test_ui_check_db_availability` | Validates DB trade date probe | `populated_db` fixture |
| `src/test_cli_ui.py` | `test_ui_render_live_recommendations` | Validates View A execution & HTML | `monkeypatch.setattr(st, "markdown")` |
| `src/test_cli_ui.py` | `test_ui_render_backtest_view` | Validates Views B, C, E execution | `monkeypatch.setattr(st, "markdown")` |
| `src/test_cli_ui.py` | `test_ui_view_d_manual_analysis` | Validates View D execution | `monkeypatch.setattr(st, "markdown")` |

---

## 5. Requirements for Comprehensive TASE Test Coverage

To guarantee 100% pass rate and production reliability for the TASE integration, the test suite must be expanded across four tiers:

### Tier 1: Ingestion & Seed Tests (`test_tase_ingestion.py`)
1. **TA-125 Universe Seeding**: Verify TA-125 constituents are correctly identified with `.TA` suffix and `exchange = 'TASE'`.
2. **TA-125 Benchmark Ingestion**: Hard-gated ingestion of `^TA125.TA` daily bars alongside `SPY`.
3. **Delta Sync & Rate-Limiting**: Verify delta sync handles `.TA` tickers without schema corruption or timestamp conversion errors.
4. **Metadata Integrity**: Verify `symbol_metadata` stores `asset_class = 'Common Stock'` and `exchange = 'TASE'`.

### Tier 2: Quantitative Screener Tests (`test_tase_screener.py`)
1. **Benchmark Isolation**: Verify TASE Relative Strength is calculated strictly against `^TA125.TA`, while US Relative Strength is calculated against `SPY`.
2. **Screener Partitioning**: Assert that `run_screener(..., exchange='TASE')` returns only `.TA` tickers, and US screener excludes `.TA` tickers.
3. **Top 5 Ranking**: Verify ranking logic selects exactly the Top 5 highest composite scores among TASE constituents.
4. **Threshold Edge Cases**: Test VCP tightness and ADV20 liquidity filters under synthetic TASE market scenarios.

### Tier 3: Point-in-Time Backtest Tests (`test_tase_backtest.py`)
1. **TA-125 Benchmark Return Tracking**: Verify `^TA125.TA` return calculation matches the exact holding period ($T_{-5} \to T_0$, $T_{-22} \to T_0$).
2. **TASE Alpha Calculation**: Verify `TASE Alpha = TASE Mean Basket Return - TA125 Return`.
3. **Win Rate & Max Drawdown**: Test precision of MDD and win rate metrics on synthetic TASE price action.

### Tier 4: Streamlit UI Component Tests (`test_tase_ui.py` or extended `test_cli_ui.py`)
1. **View A Top 5 TASE Render**: Test `render_live_recommendations` renders the `.title-tase` container and Top 5 TASE HTML table.
2. **Views B, C, E TASE Benchmark Cards**: Test `render_backtest_view` generates the 3 TASE portfolio benchmark cards and position table.
3. **View D TASE Diagnosis**: Test that supplying a `.TA` ticker runs diagnostics against `^TA125.TA` and displays the TASE qualification verdict.
4. **HTML & Visual Tag Validation**: Assert rendered HTML contains no unescaped tags (`&lt;`, `&gt;` inside cells), raw markdown leaks, or broken links.

---

## 6. Implementation Interfaces & Code Proposals

### A. Extended Screener Query Interface (`src/engine/screener_queries.py`)
Add an optional `exchange: str | None = None` parameter or dedicated benchmark anchor:

```python
def run_screener(
    db_manager: DatabaseManager,
    cutoff_date: str,
    max_tightness: float = 3.5,
    manual_tickers: list[str] | None = None,
    pct_off_low: float = 30.0,
    pct_within_high: float = 25.0,
    exchange: str | None = None,
) -> pd.DataFrame:
    """Executes screener query filtered by exchange ('US' vs 'TASE').
    
    If exchange == 'TASE', benchmarks against ^TA125.TA.
    If exchange is None or 'US', benchmarks against SPY.
    """
```

### B. Extended Backtest Engine Interface (`src/engine/backtest_engine.py`)
```python
def run_point_in_time_backtest(
    db_manager: DatabaseManager,
    cutoff_days_ago: int = 5,
    custom_cutoff_date: str | None = None,
    max_tightness: float = 3.5,
    pct_off_low: float = 30.0,
    pct_within_high: float = 25.0,
    exchange: str | None = None,
) -> dict[str, Any]:
    """Returns backtest results partitioned by market (US vs TASE)."""
```

### C. Extended UI Layout (`src/ui/app.py`)
In `render_live_recommendations()`:
```python
# 1. US Recommendations
st.subheader("🌐 Top 10: All Other Sectors (Non-Pharma/Bio)")
st.markdown(build_html_table(df_other_top10, is_backtest=False), unsafe_allow_html=True)

st.subheader("🏥 Top 10: Medical, Pharma & Bio Category")
st.markdown(build_html_table(df_med_top10, is_backtest=False), unsafe_allow_html=True)

# 2. Dedicated High-Contrast TASE Section
st.markdown(
    '<div class="benchmark-section-title title-tase">'
    '<span>🇮🇱 Dedicated Section: Top 5 Tel Aviv Stock Exchange (TA-125) Recommendations</span>'
    '<span class="tase-badge">TASE Top 5</span>'
    '</div>',
    unsafe_allow_html=True
)
st.markdown(build_html_table(df_tase_top5, is_backtest=False), unsafe_allow_html=True)
```

In `render_backtest_view()`:
```python
# TASE Benchmark Cards Section
st.markdown(
    '<div class="benchmark-section-title title-tase">'
    '<span>🇮🇱 Category 3: Tel Aviv Stock Exchange (TA-125) — $10k / ₪10k Benchmark</span>'
    '<span style="font-size: 0.8rem; text-transform: uppercase;">Top 5 Picks Allocation</span>'
    '</div>',
    unsafe_allow_html=True
)
tcol1, tcol2, tcol3 = st.columns(3)
# Render TA-125 Buy & Hold, 5x TASE Picks, Net TASE Alpha
# Followed by Top 5 TASE Backtest Table
```

---

## 7. Actionable Recommendations for Orchestrator & Builder

1. **Schema & Seed Compatibility**:
   - TASE tickers must use standard Yahoo Finance `.TA` suffix (e.g., `TEVA.TA`, `ICL.TA`).
   - Benchmark ticker must be stored as `^TA125.TA` in `daily_bars` with `symbol_metadata.exchange = 'TASE'`.
2. **Benchmark Decoupling**:
   - Do not benchmark TASE stocks against SPY; compute Mansfield RS against `^TA125.TA`.
3. **UI High Contrast Discipline**:
   - Ensure the `.title-tase` banner and `.portfolio-card-tase` styles provide sharp visual distinction from the US green/blue cards.
4. **Test Suite Integrity**:
   - All tests must continue to run synchronously via `python -m pytest -v` with 100% pass rate.
