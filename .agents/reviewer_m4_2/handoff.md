# Milestone 4 Quantitative Parity & Architecture Review Report

**Agent**: `reviewer_m4_2` (Quantitative Parity & Architecture Reviewer)
**Roles**: Reviewer, Critic
**Working Directory**: `c:\Users\rmelamed\Projects\stock-analysis\.agents\reviewer_m4_2\`
**Target Milestone**: Milestone 4 (Final E2E Verification & Hardening)
**Verdict**: **APPROVE**

---

## 1. Observation

### 1.1 Source Code and Architecture Audit
- **Screener Mathematical Formulas** (`src/engine/screener_queries.py`):
  - **Mansfield RS Calculation** (Lines 101-114, 135):
    - `rs_63`: `((ls.close / ls.close_63) / (bb.bench_close / bb.bench_close_63)) - 1.0`
    - `rs_252`: `((ls.close / ls.close_252) / (bb.bench_close / bb.bench_close_252)) - 1.0`
    - `rs_score`: `(0.70 * sf.rs_63 + 0.30 * sf.rs_252)`
    - Dynamic benchmark routing (Lines 377-384): `active_benchmark = "^TA125.TA"` for `universe="TASE"` and `active_benchmark = "SPY"` for `universe="US"`.
  - **VCP Tightness Ratio** (Lines 58-59, 75-87, 100):
    - `tr = GREATEST(bb.high - bb.low, ABS(bb.high - COALESCE(bb.prev_close, bb.close)), ABS(bb.low - COALESCE(bb.prev_close, bb.close)))`
    - `atr14 = AVG(bi.tr) OVER (PARTITION BY bi.ticker ORDER BY bi.trade_date ROWS BETWEEN 13 PRECEDING AND CURRENT ROW)`
    - `tightness_ratio = CASE WHEN ls.atr14 > 0 THEN (ls.high_10d - ls.low_10d) / ls.atr14 ELSE 0.0 END`
  - **Percentile Composite Score Calculation** (Lines 132-142):
    - `composite_score = 0.60 * (PERCENT_RANK() OVER (ORDER BY (0.70 * sf.rs_63 + 0.30 * sf.rs_252) ASC) * 100.0) + 0.40 * (PERCENT_RANK() OVER (ORDER BY (CASE WHEN sf.tightness_ratio > 0 THEN 1.0 / sf.tightness_ratio ELSE 0 END) ASC) * 100.0)`
    - Evaluated over `stage_filters`, ensuring percentile ranks are partition-isolated within the target universe.
  - **Exchange Filtering & Universe Partitioning** (Lines 386-401):
    - TASE: `(ls.exchange = 'TASE' OR ls.ticker LIKE '%.TA')`, default exchange `'TASE'`, price floor `100.0` Ag., ADV20 floor `20,000,000.0`.
    - US: `((ls.exchange IN ('NASDAQ', 'NYSE', 'AMEX', 'ARCA', 'BATS', 'IEX') OR ls.exchange IS NULL) AND ls.ticker NOT LIKE '%.TA')`, default exchange `'NASDAQ'`, price floor `10.0` USD, ADV20 floor `20,000,000.0`.

- **Point-in-Time Backtest Engine** (`src/engine/backtest_engine.py`):
  - **Benchmark Isolation & Calendar Alignment** (Lines 53-78):
    - Queries `trade_date` from `daily_bars` filtered by benchmark ticker (`^TA125.TA` vs `SPY`), automatically adapting to local exchange trading calendars (Sunday-Thursday vs Monday-Friday).
  - **Portfolio Sizing Math** (Lines 161-163, 184-186):
    - `effective_top_n = top_n if top_n is not None else (5 if univ == "TASE" else 10)`
    - `alloc_pct = (100.0 / num_positions)` (20.0% for 5 TASE picks; 10.0% for 10 US picks)
    - `alloc_usd = (10000.0 / num_positions)` ($2,000.00 for 5 TASE picks; $1,000.00 for 10 US picks)
  - **Net Alpha & Max Drawdown** (Lines 215-230, 256-264):
    - `ret = (exit_price - entry_price) / entry_price`
    - `alpha = ret - bench_return`
    - `basket_alpha = float(mean_basket_return - bench_return)`
    - Rolling peak-to-trough max drawdown calculation per position.

- **Streamlit Web Application** (`src/ui/app.py`):
  - **Dedicated TASE Visual Section** (Lines 426-483, 747-858, 1252-1255):
    - Dedicated Category 3 visual cards and headers across Views A, B, C, D, and E using CSS classes `.title-tase` and `.portfolio-card-tase`.
  - **$10,000 Benchmark Comparison Cards Math** (Lines 788-796, 801-838):
    - `alloc_tase = 10000.0 / n_tase if n_tase > 0 else 2000.0`
    - `tase_val = sum([alloc_tase * (1.0 + (row["return_pct"] / 100.0)) for _, row in df_b_tase_top5.iterrows()])`
    - `ta125_val = 10000.0 * (1.0 + (ta125_ret / 100.0))`
    - `tase_gain = tase_val - 10000.0`
    - `ta125_gain = ta125_val - 10000.0`
    - `tase_alpha = tase_val - ta125_val`
  - **View D Stage-2 Checklist Scoring Separation** (Lines 1153-1216):
    - Dynamic evaluation: 100 Ag. price floor for TASE vs $10.00 for US, 20M Ag. ADV20 for TASE vs $20M for US, Mansfield RS benchmarked against `^TA125.TA` for TASE vs `SPY` for US, Top 5 qualification for TASE vs Top 10 for US.

### 1.2 Test Execution Results
1. **Full Pytest Test Suite (`python -m pytest -v`)**:
   - Total Collected Items: 164
   - Result: **164 PASSED, 0 FAILED (100% Pass Rate)**
2. **Empirical Adversarial Stress Suite (`python scratch/run_all_challenger_tests.py`)**:
   - **Suite 1 (Hard-Gating & Fault Injection)**: 6/6 tests PASSED
   - **Suite 2 (Ticker Normalization & Symbol Directory Parsing)**: 5/5 tests PASSED
   - **Suite 3 (Single Ticker Sync & DuckDB Exchange Integrity)**: 7/7 tests PASSED
   - **Suite 4 (Malformed Bar Ingestion & Parquet Delta Integrity)**: 4/4 tests PASSED
   - **Suite 5 (Milestone 3 Mathematical & Multi-Universe Integrity)**: 8/8 tests PASSED
   - Total runtime: 15.35s (**100% Pass Rate**)

---

## 2. Logic Chain

1. **Mathematical Invariant Verification**:
   - **Mansfield Relative Strength**: In `screener_queries.py`, the Mansfield RS is computed as ((P_t / P_{t-k}) / (B_t / B_{t-k})) - 1.0 for k=63 (3 months) and k=252 (12 months) and blended as 0.70 * RS_63 + 0.30 * RS_252. When `universe="TASE"`, benchmark B is strictly `^TA125.TA`; when `universe="US"`, benchmark B is strictly `SPY`. Verified via unit and adversarial tests.
   - **VCP Tightness Ratio**: The 10-day price range (High_10d - Low_10d) normalized by ATR_14 accurately measures price volatility contraction. Inverting the ratio (1 / tightness) in the SQL window function `PERCENT_RANK()` strictly rewards tighter consolidations with higher percentile scores.
   - **Percentile Composite Score**: Combines 0.60 * Percentile(RS) + 0.40 * Percentile(Tightness^-1), evaluated strictly within the filtered universe candidate partition. TASE percentiles are never skewed by US equities and vice versa.
   - **Portfolio Sizing Invariants**: Both the backtest engine and UI allocate a fixed $10,000 nominal capital. For TASE, 5 positions receive $2,000 (20.0%) each; for US, 10 positions receive $1,000 (10.0%) each. Partial portfolios (N < 5 or N < 10) dynamically scale to $10,000 / N without loss of capital.
   - **4-Quadrant Net Alpha Formulation**: Net Alpha is algebraically defined as Portfolio Value - Benchmark Value. Verified across all 4 market regimes:
     - *Quadrant 1 (Bull Outperformance)*: Picks +15%, Benchmark +5% -> Net Alpha = +$1,000 (+10.0%).
     - *Quadrant 2 (Bull Underperformance)*: Picks +4%, Benchmark +10% -> Net Alpha = -$600 (-6.0%).
     - *Quadrant 3 (Bear Outperformance / Capital Preservation)*: Picks -2%, Benchmark -12% -> Net Alpha = +$1,000 (+10.0%).
     - *Quadrant 4 (Bear Underperformance)*: Picks -18%, Benchmark -6% -> Net Alpha = -$1,200 (-12.0%).

2. **Multi-Universe Isolation & Database Contracts**:
   - **Database Schema**: `symbol_metadata` and `daily_bars` tables support dual-universe storage with strict schema constraints. TASE tickers are identified with `.TA` suffix and `exchange = 'TASE'`.
   - **Query Separation**: Screener queries explicitly partition universes by exchange and ticker pattern, excluding `SPY` and `^TA125.TA` from recommendation rankings.
   - **Backtest State Isolation**: Historical simulation and trade date resolution query the respective benchmark ticker, ensuring zero calendar drift between US and Israeli markets.
   - **UI Decoupling**: Streamlit UI renders TASE recommendations in a dedicated Category 3 container with distinct visual styling (`.title-tase`, `.portfolio-card-tase`), distinct currency formatting (Agorot vs USD), and separate export options.

3. **Integrity & Adversarial Review**:
   - **No Integrity Violations Detected**: Source code contains zero hardcoded test outputs, facade methods, or bypassed logic. All calculations (ATR, RS, percentile rank, drawdown) execute full algebraic/vectorized operations directly in DuckDB and Python.
   - **Boundary Robustness**: Handled all edge cases including zero/negative ATR, infinite values, NaN close prices, empty screener results, read-only database connections, and duplicate ticker inputs.

---

## 3. Caveats

- **Test Fixture Isolation**: Tests rely on synthetic in-memory/temp DuckDB fixtures and mocked yfinance network calls to guarantee deterministic offline execution without hitting API rate limits.
- **UI Headless Verification**: Streamlit UI visual components and DOM structures were validated through headless monkeypatched document container inspections.
- No other caveats.

---

## 4. Conclusion

The quantitative momentum screener engine, point-in-time backtester, DuckDB database layer, and Streamlit user interface satisfy all mathematical invariants, schema contracts, and multi-universe isolation requirements. All 164 pytest tests and 5 challenger adversarial test suites pass with a 100% success rate.

**Final Review Verdict: APPROVE**

---

## 5. Verification Method

To independently reproduce and verify this review:

1. **Run full repository pytest test suite**:
   ```powershell
   python -m pytest -v
   ```
   *Expected Output*: 164 passed, 0 failed.

2. **Run empirical challenger adversarial stress test suite**:
   ```powershell
   python scratch/run_all_challenger_tests.py
   ```
   *Expected Output*: All 5 suites passed (Hard-Gating, Ticker Normalization, Single Ticker Sync, Malformed Bar Ingestion, Milestone 3 Math Integrity).

3. **Run 4-quadrant mathematical deep audit tests**:
   ```powershell
   python -m pytest scratch/test_portfolio_math_and_quadrants.py scratch/test_portfolio_math_deep_audit.py -v
   ```
   *Expected Output*: 8 passed, 0 failed.
