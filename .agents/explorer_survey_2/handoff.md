# Quantitative Engine Investigation Handoff Report

## 1. Observation
- **Codebase Baseline:**
  - Running `python -m pytest` executed 21 unit tests across `src\db\test_db_manager.py`, `src\engine\test_engine.py`, `src\ingestion\test_ingestion.py`, and `src\test_cli_ui.py`, achieving 100% pass rate in 18.88s.
- **Quantitative Engine Architecture:**
  - `src/engine/screener_queries.py`: `run_screener()` executes DuckDB SQL with CTEs (`date_anchor`, `spy_bars`, `ticker_dates`, `base_bars`, `bar_indicators`, `bar_atr`, `latest_snapshot`, `stage_filters`, `composite_scoring`, `final_ranked`). Hardcoded references to `SPY` exist in CTE `spy_bars` (lines 33, 118) and `stage_filters` (lines 101, 108). Hardcoded filters: `ls.close >= 10.0` (line 119) and `ls.adv_20 >= 20000000.0` (line 120).
  - `src/engine/backtest_engine.py`: `run_point_in_time_backtest()` queries historical forward prices for `SPY` (line 130) and calculates `spy_return` (line 139) and `alpha = ret - spy_return` (line 185).
  - `src/db/schema.sql`: `symbol_metadata` includes `exchange VARCHAR` and `asset_class VARCHAR`. `daily_bars` is indexed by `PRIMARY KEY (ticker, trade_date)`.
  - `src/ui/app.py`: Displays Views A, B, C, D, and E, currently segmenting US equities by Non-Pharma and Medical/Pharma categories.
- **Market Data Inspection:**
  - TASE tickers on Yahoo Finance (e.g. `NICE.TA`, `TEVA.TA`, `LUMI.TA`, `^TA125.TA`):
    - Equities are quoted in Israeli Agorot (ILA) (e.g. `NICE.TA` close: 31,150 Agorot = 311.50 ILS).
    - `^TA125.TA` is quoted in index points (e.g. 4,092 points).
    - 2-year download of `^TA125.TA` returns 424 trading days.
    - Trading calendar is Sunday–Thursday, while US markets are Monday–Friday.

## 2. Logic Chain
1. **Mathematical Invariance:**
   - Because $Close_t / SMA_n$, $(High_{10D} - Low_{10D}) / ATR_{14}$, $(Close - Low_{52W}) / Low_{52W}$, and $(Close / Close_{63})$ are all homogeneous ratio functions of price, the units (Agorot vs USD) cancel out. Therefore, Minervini trend alignment, 52W range boundaries, VCP tightness compression, and Relative Strength ratios produce identical mathematical values regardless of whether prices are denominated in Agorot or USD.
2. **Benchmark Independence:**
   - Joining TASE equities to `SPY` would create calendar mismatches (e.g. Sunday trading days would have NULL SPY data) and cross-currency distortion.
   - Decoupling the benchmark query to join `^TA125.TA` for TASE equities and `SPY` for US equities ensures 100% calendar alignment and meaningful intra-market Relative Strength ($RS_{63}, RS_{252}$) and alpha metrics.
3. **Universe Separation:**
   - Filtering by `exchange = 'TASE'` vs US exchanges allows the engine to compute `PERCENT_RANK()` composite scores independently within the TASE pool.
   - Extracting `df.head(5)` from the TASE ranked universe produces a dedicated "Top 5 TASE" recommendation list that does not dilute or interfere with the US Top 10 list.

## 3. Caveats
- **Historical Ingestion Prerequisite:** TASE screening requires `^TA125.TA` and TA-125 constituents to be seeded into DuckDB with at least 252 trading days of history.
- **TA-125 Constituent List Maintenance:** TA-125 index composition is periodically rebalanced by the Tel Aviv Stock Exchange (semi-annually). Static seeding should cover current constituents.
- **No caveats regarding indicator mathematical compatibility.**

## 4. Conclusion
The Quantitative Screener and Backtest Engine is fully capable of supporting TASE equities seamlessly by:
1. Parameterizing `run_screener()` and `run_point_in_time_backtest()` with a `universe: str = "US" | "TASE"` argument.
2. Associating `SPY` with `universe="US"` and `^TA125.TA` with `universe="TASE"`.
3. Filtering `exchange = 'TASE'` and applying TASE price/liquidity floors (e.g. price $\ge 100 \text{ Agorot}$, ADV20 $\ge 20\text{M Agorot}$).
4. Rendering a dedicated, high-contrast Top 5 TASE recommendation card across Views A, B, C, D, and E in Streamlit.

## 5. Verification Method
1. **Automated Unit Tests:**
   Run full test suite:
   ```powershell
   python -m pytest
   ```
2. **TASE Screener Verification:**
   Execute parameterized query test on test database with synthetic/live TASE data and verify:
   - TASE stocks pass Stage 1–3 filters.
   - Composite scores are bounded in $[0, 100]$.
   - Relative Strength computes against `^TA125.TA`.
   - Top 5 results return sorted by composite score.
3. **Files to Inspect:**
   - `src/engine/screener_queries.py`
   - `src/engine/backtest_engine.py`
   - `src/engine/test_engine.py`
   - `src/ui/app.py`
