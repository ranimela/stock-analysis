# Milestone 3 Challenger Adversarial Verification Report

**Verdict**: **APPROVE**

## 1. Observation
- **Files Audited & Verified**:
  - `src/ui/app.py`
  - `src/engine/screener_queries.py`
  - `src/engine/backtest_engine.py`
  - `src/test_cli_ui.py`
  - `tests/test_adversarial_engine_tase.py`
  - `scratch/run_all_challenger_tests.py`
- **Empirical Test Runs & Direct Results**:
  1. `python scratch/run_all_challenger_tests.py`
     - **Suite 1 (Hard-Gating & Fault Injection)**: 6/6 tests PASSED
     - **Suite 2 (Ticker Normalization & Catalog)**: 5/5 tests PASSED
     - **Suite 3 (Single-Ticker Sync & Exchange Integrity)**: 7/7 tests PASSED
     - **Suite 4 (Malformed Bar Ingestion & Parquet Delta)**: 4/4 tests PASSED
     - **Suite 5 (Milestone 3 Math & Multi-Universe Integrity)**: 8/8 tests PASSED
     - Total runtime: 35.20s (100% pass rate).
  2. `python -m pytest tests/test_adversarial_engine_tase.py src/test_cli_ui.py -v`
     - 37/37 passed in 335.01s (100% pass rate).

## 2. Logic Chain
1. **Model Portfolio Math ($10,000 Capital & 5x $2,000 Positions for TASE)**:
   - In `src/engine/backtest_engine.py` (lines 161-163, 184-186), `top_n` defaults to `5` for `universe == "TASE"` (and `10` for US). Each position is assigned `allocation_pct = 100.0 / 5 = 20.0%` and `allocation_usd = $10,000 / 5 = $2,000.00`.
   - In `src/ui/app.py` (lines 779-786), `render_backtest_view` executes `alloc_tase = 10000.0 / n_tase` (defaulting to $2,000.00 for 5 picks) and computes:
     - `tase_val = sum([alloc_tase * (1.0 + (row["return_pct"] / 100.0)) for _, row in df_b_tase_top5.iterrows()])`
     - `tase_gain = tase_val - 10000.0`
     - `ta125_val = 10000.0 * (1.0 + (ta125_ret / 100.0))`
     - `ta125_gain = ta125_val - 10000.0`
     - `tase_alpha = tase_val - ta125_val`
   - Empirically stress-tested for 5 positions, partial portfolios (1, 2, 3, 4 positions), and empty positions without encountering `ZeroDivisionError`, rounding drift, or NaN leakage.

2. **Net TASE Alpha Strictly Calculated Against `^TA125.TA` Benchmark**:
   - In `src/engine/backtest_engine.py` (lines 53-58, 172-180), `universe == "TASE"` queries daily bars for `^TA125.TA` over `[cutoff_date, eval_date]`.
   - In `src/ui/app.py` (lines 765, 784-786), `ta125_ret` is retrieved from `results_tase["ta125_return"]`, and Net TASE Alpha is calculated as `tase_alpha = tase_val - ta125_val`.
   - Stress-tested across all four return quadrants:
     - **Quadrant 1 (Bull outperformance)**: Basket +10%, TA125 +5% -> Net Alpha = +$500.00.
     - **Quadrant 2 (Bull underperformance)**: Basket +5%, TA125 +10% -> Net Alpha = -$500.00.
     - **Quadrant 3 (Bear outperformance / capital preservation)**: Basket -5%, TA125 -15% -> Net Alpha = +$1,000.00.
     - **Quadrant 4 (Bear underperformance)**: Basket -15%, TA125 -5% -> Net Alpha = -$1,000.00.
     - **Mixed Quadrants**: Basket +10%, TA125 -5% -> Net Alpha = +$1,500.00; Basket -10%, TA125 +5% -> Net Alpha = -$1,500.00.
   - Benchmark isolation verified: TASE never queries or displays `SPY`, and US never queries or displays `^TA125.TA`.

3. **Stage-2 Checklist Scoring Separation**:
   - In `src/ui/app.py` under View D (Custom Diagnostics Lab, lines 1144-1207):
     - **Price Floor**: Enforces `Close >= 100.0 Ag.` for TASE tickers (`.TA`) vs `Close >= $10.00` for US tickers.
     - **ADV20 Liquidity**: Enforces `ADV20 >= 20,000,000 Ag.` for TASE vs `ADV20 >= $20,000,000` for US.
     - **Moving Average Stack**: `Close > SMA50 > SMA150 > SMA200`.
     - **200D SMA Trend Slope**: `SMA200 > SMA200_20d_ago`.
     - **52W Low Bound**: `Close >= 1.30 * Low_52w` (+30% gain off low).
     - **52W High Bound**: `Close >= 0.75 * High_52w` (within 25% of high).
     - **VCP Tightness Ratio**: `Tightness <= 3.5`.
     - **Relative Strength**: Mansfield RS evaluated strictly against `^TA125.TA` for TASE equities and `SPY` for US equities.
     - **Universe Qualification Gating**: TASE tickers qualify against the top 5 TASE ranking (`top5_tase_set`), while US tickers qualify against the top 10 US ranking (`top10_set`).
     - **Currency and HTML Output**: Rendered tables use `Ag.`, `M Ag.`, and `B Ag.` for TASE with column header `TA-125 Return (%)`, and `$`, `$M`, `$B` for US with column header `SPY Return (%)`.

4. **Streamlit UI Views Headless Execution**:
   - Views A, B, C, D, and E were executed in headless mode with simulated Streamlit contexts across multi-universe datasets. All cards, tables, download buttons, and diagnostic expanders rendered without exceptions.

## 3. Caveats
- Tests were performed using isolated temporary DuckDB fixtures without live network requests to ensure deterministic evaluation.
- Streamlit views were verified in headless execution via mocked Streamlit document containers.

## 4. Conclusion
Milestone 3 passes all mathematical, structural, and multi-universe adversarial checks with zero defects or regressions. The $10,000 portfolio allocation for TASE (5x $2,000 / 20%), the Net TASE Alpha against `^TA125.TA`, and the 8-point Stage-2 diagnostic separation operate with 100% precision.

**Verdict: APPROVE**

## 5. Verification Method
To independently reproduce and verify these findings:
1. Run the comprehensive adversarial stress test suite:
   ```powershell
   python scratch/run_all_challenger_tests.py
   ```
2. Run the full repository pytest suite:
   ```powershell
   python -m pytest tests/test_adversarial_engine_tase.py src/test_cli_ui.py -v
   ```
