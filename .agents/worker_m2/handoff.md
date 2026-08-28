# Milestone 2 Handoff Report: Quantitative Engine Adaptation

**Agent**: Worker M2 (Implementation Specialist for Milestone 2: Quantitative Engine Adaptation)  
**Date**: 2026-08-27  
**Artifact Directory**: `c:\Users\rmelamed\Projects\stock-analysis\.agents\worker_m2\`  

---

## 1. Observation

1. **Target Files Implemented**:
   - `src/engine/screener_queries.py`:
     - Parameterized `run_screener(db_manager, cutoff_date=None, universe="US", benchmark_ticker=None, max_tightness=3.5, manual_tickers=None, pct_off_low=30.0, pct_within_high=25.0, min_price=None, min_adv20=None) -> pd.DataFrame`.
     - Parameterized `benchmark_bars` CTE querying `WHERE ticker = '{benchmark_ticker}'` (`SPY` for US, `^TA125.TA` for TASE).
     - Parameterized `stage_filters` with dynamic `{exchange_filter}` isolating `(ls.exchange = 'TASE' OR ls.ticker LIKE '%.TA')` for TASE and US exchanges for US.
     - Calibrated price floor (`min_price=100.0` Agorot for TASE, `10.0` USD for US) and ADV20 turnover floor (`min_adv20=20,000,000.0` Agorot / USD).
     - Isolated percentile scoring (`PERCENT_RANK()`) executed strictly over the active universe candidate set to eliminate cross-universe score distortion.
     - Automatic auto-routing for `manual_tickers` containing `.TA` tickers.
     - Polymorphic execution supporting `DatabaseManager` instances and raw DuckDB connections.
   - `src/engine/backtest_engine.py`:
     - Parameterized `run_point_in_time_backtest(db_manager, cutoff_days_ago=5, custom_cutoff_date=None, max_tightness=3.5, pct_off_low=30.0, pct_within_high=25.0, universe="US", benchmark_ticker=None, top_n=None) -> dict`.
     - Dynamic benchmark calendar resolution: trade dates are queried directly from the target universe's benchmark (`^TA125.TA` for TASE, `SPY` for US) with fallback to general daily bars.
     - Forward return and alpha tracking against `^TA125.TA` (`ta125_return_pct`, `alpha_pct = return_pct - benchmark_return_pct`).
     - Portfolio allocation for TASE Top 5: $2,000 / 20.0% per position (vs $1,000 / 10.0% for US Top 10).
     - Isolated database persistence to `point_in_time_runs` with distinct run IDs (`pit_T-5_TASE_20250818`).
   - `src/cli.py`:
     - Added `@click.option("--exchange", "-e", type=click.Choice(["US", "TASE", "ALL"], case_sensitive=False), default="ALL")` to `scan` command.
     - Added `_run_market_scans(db_manager, latest_date, universe)` producing dedicated output reports:
       - US Equities: Live Top-10 recommendations, 1-Week PIT Backtest (T-5, SPY), 1-Month PIT Backtest (T-22, SPY).
       - TASE Equities: Live Top-5 recommendations, 1-Week PIT Backtest (T-5, ^TA125.TA), 1-Month PIT Backtest (T-22, ^TA125.TA).
   - `src/engine/test_engine.py`:
     - Comprehensive unit and integration test suite with 20 tests organized across 6 modules (TASE screener execution, dedicated Top 5 extraction, universe isolation without cross-contamination, VCP/52W/Minervini/Mansfield math, price/liquidity floors, and PIT backtests against `^TA125.TA`).
   - `tests/test_adversarial_engine_tase.py`:
     - Added 19 adversarial tests for CLI scan flag permutations, case insensitivity, invalid exchange rejection, top_n allocations, read-only DB safety, and boundary parameters.
   - `tests/test_same_day_sync.py`:
     - Fixed return statement to cleanly assert and eliminate PytestReturnNotNoneWarning.

2. **Test Execution Results**:
   - `python -m pytest src/engine/test_engine.py -v`: 20 passed in 115.93s (100% pass rate).
   - `python -m pytest tests/test_adversarial_engine_tase.py -v`: 19 passed in 99.45s (100% pass rate).
   - `python -m pytest -v`: 119 passed, 0 warnings in 193.71s across the entire project test suite (100% pass rate).

---

## 2. Logic Chain

1. **Dynamic Benchmark Routing & Calendar Alignment**:
   - Israeli equities on the TASE trade on a Sunday through Thursday schedule, whereas US equities trade Monday through Friday.
   - By resolving historical trade dates using `WHERE ticker = '^TA125.TA'` when `universe == "TASE"`, the backtest accurately identifies historical $T_{-5}$ (1-week lookback) and $T_{-22}$ (1-month lookback) trading days on the Israeli calendar rather than skipping or shifting days.
   - Forward returns for TASE stocks are evaluated against the true forward return of `^TA125.TA`, accurately computing basket alpha (`basket_alpha = mean_basket_return - ta125_return`).

2. **Liquidity & Price Floor Calibration**:
   - TASE stocks in Yahoo Finance trade in Agorot (100 Agorot = 1 NIS).
   - `min_price = 100.0` prevents sub-NIS penny stocks while allowing all legitimate TA-125 constituents.
   - `min_adv20 = 20,000,000.0` Agorot (~200,000 NIS turnover) screens out illiquid tail stocks.

3. **Isolated Percentile Ranking (`PERCENT_RANK()`)**:
   - In DuckDB, `PERCENT_RANK() OVER (...)` is evaluated over the rows surviving `stage_filters`.
   - Because `stage_filters` filters by `{exchange_filter}`, the window function calculates percentiles strictly across the target universe pool. TASE composite scores are calculated solely across the TASE pool and not distorted or compressed by US stocks.

4. **Dedicated Top 5 TASE Separation**:
   - `df_tase.head(5)` extracts the Top 5 highest composite score TASE recommendations.
   - In PIT backtests, the top 5 positions each receive an equal $2,000 allocation (20.0% weight) in a $10,000 model portfolio.

5. **Full Backwards Compatibility**:
   - Default arguments `universe = "US"`, `benchmark_ticker = None`, `min_price = None`, `min_adv20 = None` ensure that existing callers (e.g. Streamlit UI and CLI commands) operate without regression.

---

## 3. Caveats

1. **Currency Units**: TASE equity prices and volume figures in Yahoo Finance data are in Agorot (or ILS). Returns, alpha, and drawdowns are dimensionless percentages and remain invariant to currency units.
2. **Streamlit UI Views (Milestone 3 Scope)**: The underlying engine functions are fully prepared and tested with `universe="US"` and `universe="TASE"`. In Milestone 3, Worker M3 will update the Streamlit UI (`src/ui/app.py`) to render the dedicated Top 5 TASE cards below the US Top 10 across Views A, B, C, D, and E.

---

## 4. Conclusion

All requirements for Milestone 2 (Quantitative Engine Adaptation) are 100% complete, fully implemented with genuine quantitative logic, and verified with 119 passing tests:
- `src/engine/screener_queries.py` supports dynamic benchmark routing, universe isolation, price/ADV20 floors, and isolated percentile ranking.
- `src/engine/backtest_engine.py` supports TASE calendar resolution, alpha vs `^TA125.TA`, and Top 5 portfolio allocations.
- `src/cli.py` supports `--exchange [US|TASE|ALL]` with dedicated US Top-10 and TASE Top-5 output reports.
- Comprehensive test coverage in `src/engine/test_engine.py` and `tests/test_adversarial_engine_tase.py` achieves 100% pass rate with zero warnings.

---

## 5. Verification Method

To independently reproduce and verify all results:

1. **Run Engine Unit & Integration Tests**:
   ```bash
   python -m pytest src/engine/test_engine.py -v
   ```
   *Expected*: 20 passed.

2. **Run Adversarial Engine Tests**:
   ```bash
   python -m pytest tests/test_adversarial_engine_tase.py -v
   ```
   *Expected*: 19 passed.

3. **Run Full Test Suite**:
   ```bash
   python -m pytest -v
   ```
   *Expected*: 119 passed, 0 warnings.

4. **Test CLI Multi-Exchange Scan**:
   ```bash
   python -m src.cli scan --help
   ```

5. **Invalidation Conditions**:
   - Any test failure in `pytest`.
   - Any inclusion of `.TA` tickers in `run_screener(universe="US")`.
   - Any inclusion of US tickers in `run_screener(universe="TASE")`.
   - Discrepancy in TASE alpha calculation vs `^TA125.TA`.
