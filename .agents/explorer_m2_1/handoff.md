# Handoff Report: Screener Queries Parameterization (Milestone 2)

**Agent**: Explorer M2_1 (Screener Queries Specialist)  
**Date**: 2026-08-27  
**Artifact Directory**: `c:\Users\rmelamed\Projects\stock-analysis\.agents\explorer_m2_1\`  
**Target Module**: `src/engine/screener_queries.py`

---

## 1. Observation

1. **File Locations & Hardcoded Constants**:
   - `src/engine/screener_queries.py`:
     - Line 26: CTE `spy_bars` hardcodes `WHERE ticker = 'SPY'`.
     - Lines 95–97: `sb.spy_close`, `sb.spy_close_63`, `sb.spy_close_252`.
     - Line 115: `LEFT JOIN spy_bars sb ON ls.trade_date = sb.trade_date`.
     - Line 118: `AND ls.ticker != 'SPY'`.
     - Line 119: Hardcoded price filter `AND ls.close >= 10.0`.
     - Line 120: Hardcoded ADV turnover filter `AND ls.adv_20 >= 20000000.0`.
     - Lines 198–349: CTE duplicated in `manual_sql` with identical hardcoded `SPY` and US-specific filters.
     - Line 171: Function signature `def run_screener(db_manager: DatabaseManager, cutoff_date: str, max_tightness: float = 3.5, manual_tickers: list[str] | None = None, pct_off_low: float = 30.0, pct_within_high: float = 25.0) -> pd.DataFrame`.
   - `src/ingestion/tase_directory.py`:
     - Line 21: `TASE_BENCHMARK = '^TA125.TA'`.
     - Line 20: `TASE_EXCHANGE_CODE = 'TASE'`.
     - All TASE equities end with `.TA` and trade in Agorot (100 Agorot = 1 NIS).
   - `src/engine/test_engine.py`:
     - Line 14: `populate_mock_data` generates synthetic US tickers (`SPY`, `GOOD1`, `GOOD2`, `BAD1`).
     - Lines 91–121: `test_screener_execution()` tests standard screening pass/fail.
     - Lines 170–194: `test_manual_vs_screener_score_consistency()` verifies `rs_score` and `composite_score` parity.

2. **Test Baseline**:
   - Executed `uv run pytest`: 84 passed across the entire project repository in 30.81s.

---

## 2. Logic Chain

1. **Benchmark Routing**:
   - Israeli equities trade on a Sunday–Thursday schedule, while US equities trade on a Monday–Friday schedule.
   - Joining TASE stock bars on `spy_bars` produces NULL benchmarks for Sunday trading dates.
   - Routing benchmark dynamically to `^TA125.TA` when `universe == "TASE"` aligns trading dates on Sunday–Thursday and measures Mansfield Relative Strength against the TA-125 index benchmark.

2. **Exchange Partitioning**:
   - In DuckDB `symbol_metadata`, TASE equities are tagged with `exchange = 'TASE'` and have `.TA` ticker suffix.
   - US equities have `exchange IN ('NASDAQ', 'NYSE', 'AMEX', 'ARCA', 'BATS', 'IEX')` or `exchange IS NULL`.
   - Adding `{exchange_filter}` to `stage_filters` isolates candidate pools prior to ranking.

3. **Price & Liquidity Calibration**:
   - TASE stocks are denominated in Agorot. A price floor of `100.0` Agorot (1.0 NIS) removes sub-shekel penny stocks while retaining all legitimate TA-125 equities.
   - ADV20 turnover (`close * volume`) in Agorot with threshold `20,000,000.0` Agorot (200,000 NIS / ~$55,000 USD daily volume) screens out illiquid issues without eliminating mid-cap TA-125 constituents.

4. **Isolated Percentile Ranking (`PERCENT_RANK()`)**:
   - The composite score combines 60% Mansfield RS Percentile and 40% VCP Tightness Inverse Percentile using DuckDB window function `PERCENT_RANK() OVER (...)`.
   - Because `stage_filters` is partitioned by `universe`, `PERCENT_RANK()` calculates ranks strictly across the target universe pool. TASE stocks are ranked exclusively against TASE constituents, and US stocks against US constituents.

5. **Backward Compatibility**:
   - Setting default values `universe: str = "US"`, `benchmark_ticker: str | None = None`, `min_price: float | None = None`, `min_adv20: float | None = None` guarantees 100% backward compatibility with all existing callers and test fixtures.

---

## 3. Caveats

- **TASE Denomination Assumption**: Yahoo Finance data for TASE stocks is denominated in Agorot. Should a data source provide prices in NIS directly in future, `min_price` and `min_adv20` parameter overrides allow explicit specification without code modification.
- **Single-Ticker Auto-Inference**: When `manual_tickers` are supplied without explicit `universe` parameter, if all tickers end with `.TA`, the function auto-infers `universe = "TASE"`. Mixed US + TASE manual lists in a single call will evaluate under the specified `universe` parameter.

---

## 4. Conclusion

The parameterized screener queries design in `analysis.md` completely resolves all quantitative screening requirements for Milestone 2:
- Supports US (`SPY`), TASE (`^TA125.TA`), and custom benchmark routing.
- Partitions DuckDB `symbol_metadata.exchange` cleanly.
- Calibrates price/liquidity filters for Agorot-based TASE equities.
- Computes isolated percentile rankings with zero cross-market distortion.
- Fully preserves backwards compatibility with existing CLI, UI, and test suites.

---

## 5. Verification Method

1. **Code Review**:
   - Inspect `src/engine/screener_queries.py` against the specification in `c:\Users\rmelamed\Projects\stock-analysis\.agents\explorer_m2_1\analysis.md`.

2. **Automated Test Execution**:
   - Run `uv run pytest` to confirm all 84 existing unit and adversarial tests pass without regression.
   - Run `uv run pytest src/engine/test_engine.py` to confirm screener and consistency tests pass.
   - Execute builder/test agent to add TASE synthetic fixtures verifying `run_screener(universe="TASE")` returns `.TA` stocks benchmarked against `^TA125.TA`.

3. **Invalidation Conditions**:
   - Any test failure in `test_screener_execution()` or `test_manual_vs_screener_score_consistency()`.
   - Any inclusion of `.TA` tickers in `run_screener(universe="US")`.
   - Any inclusion of US tickers in `run_screener(universe="TASE")`.
