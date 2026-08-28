# Milestone 3 Gate Verification: Portfolio Math & Multi-Universe Integrity Challenger Report

**Agent**: `challenger_m3_r2_2`  
**Role**: Empirical Challenger (`[critic, specialist]`)  
**Date**: 2026-08-28T08:08:00Z  
**Verdict**: **APPROVE**

---

## 1. Observation

Direct empirical observations, code citations, and test execution results:

### A. Model Portfolio Math & Sizing Invariants
- **TASE Portfolio Allocation (`src/engine/backtest_engine.py:161-177`)**:
  ```python
  portfolio_size = top_n if top_n is not None else (5 if universe == "TASE" else 10)
  total_capital = 10000.0
  pos_capital = total_capital / portfolio_size if portfolio_size > 0 else 0.0
  ```
  - For TASE (`universe == "TASE"`): Default portfolio size is 5 positions. Each position is allocated exactly $\$10,000.00 / 5 = \$2,000.00$ ($20.0\%$).
- **US Portfolio Allocation (`src/engine/backtest_engine.py:161-177`)**:
  - For US (`universe == "US"`): Default portfolio size is 10 positions. Each position is allocated exactly $\$10,000.00 / 10 = \$1,000.00$ ($10.0\%$).
- **UI Metric Card Sizing & Multi-Basket Rendering (`src/ui/app.py:608-620, 788-796`)**:
  - View B/C/E cards compute:
    - US Non-Pharma: 10 positions $\times \$1,000 = \$10,000$.
    - US Pharma: 10 positions $\times \$1,000 = \$10,000$.
    - TASE (Category 3): 5 positions $\times \$2,000 = \$10,000$.
    - S&P 500 Index Benchmark: $\$10,000$ baseline.
    - TA-125 Index Benchmark: $\$10,000$ baseline.

### B. 4-Quadrant Net TASE Alpha Evaluation Against `^TA125.TA`
We constructed an empirical simulation test harness (`scratch/test_portfolio_math_and_quadrants.py`) and validated all 4 return quadrants:
1. **Quadrant 1 (Bull Outperformance)**:
   - TASE Basket Return: $+15.0\%$ ($+\$1,500.00 \to \$11,500.00$ total value).
   - `^TA125.TA` Benchmark Return: $+5.0\%$ ($+\$500.00 \to \$10,500.00$ total value).
   - Net Alpha: $+10.0\%$ ($+\$1,000.00$ alpha).
   - Observation: `test_quadrant_1_bull_outperformance PASSED`.
2. **Quadrant 2 (Bull Underperformance)**:
   - TASE Basket Return: $+4.0\%$ ($+\$400.00 \to \$10,400.00$ total value).
   - `^TA125.TA` Benchmark Return: $+10.0\%$ ($+\$1,000.00 \to \$11,000.00$ total value).
   - Net Alpha: $-6.0\%$ ($-\$600.00$ alpha).
   - Observation: `test_quadrant_2_bull_underperformance PASSED`.
3. **Quadrant 3 (Bear Outperformance / Capital Preservation)**:
   - TASE Basket Return: $-2.0\%$ ($-\$200.00 \to \$9,800.00$ total value).
   - `^TA125.TA` Benchmark Return: $-12.0\%$ ($-\$1,200.00 \to \$8,800.00$ total value).
   - Net Alpha: $+10.0\%$ ($+\$1,000.00$ alpha).
   - Observation: `test_quadrant_3_bear_outperformance_capital_preservation PASSED`.
4. **Quadrant 4 (Bear Underperformance)**:
   - TASE Basket Return: $-18.0\%$ ($-\$1,800.00 \to \$8,200.00$ total value).
   - `^TA125.TA` Benchmark Return: $-6.0\%$ ($-\$600.00 \to \$9,400.00$ total value).
   - Net Alpha: $-12.0\%$ ($-\$1,200.00$ alpha).
   - Observation: `test_quadrant_4_bear_underperformance PASSED`.

### C. Multi-Universe State Isolation and Screener Decoupling
- **Screener Isolation (`src/engine/screener_queries.py:386-401`)**:
  - TASE universe filters explicitly by `(ls.exchange = 'TASE' OR ls.ticker LIKE '%.TA')`, Mansfield RS benchmark `^TA125.TA`, min price 100 Agorot, ADV20 20,000,000 Agorot.
  - US universe filters explicitly by `((ls.exchange IN ('NASDAQ', 'NYSE', 'AMEX', 'ARCA', 'BATS', 'IEX') OR ls.exchange IS NULL) AND ls.ticker NOT LIKE '%.TA')`, Mansfield RS benchmark `SPY`, min price $10.00, ADV20 $20,000,000.
- **Calendar & Trading Schedule Decoupling (`src/engine/backtest_engine.py:53-74`)**:
  - Benchmark trading dates are queried directly from `daily_bars` for `^TA125.TA` (Sunday-Thursday trading calendar) or `SPY` (Monday-Friday trading calendar), ensuring no calendar cross-talk or misalignment.
- **UI Decoupled Rendering (`src/ui/app.py:426-483, 747-859`)**:
  - View A: Category 3 TASE Top 5 recommendations render independently even when US screener returns zero qualifying picks.
  - View B/C/E: TASE backtest card renders independently even when US positions are empty.
  - Pre-initialization of `cutoff_date` and `eval_date` at top scope prevents `UnboundLocalError`.
  - `format_company_name(name, ticker)` converts null/NaN names to `"—"` and never prints literal `"nan"`.

### D. Test Suite Verification
- Targeted test suite:
  ```
  python -m pytest tests/test_adversarial_engine_tase.py src/test_cli_ui.py tests/test_adversarial_m3_ui.py -v
  ======================= 53 passed in 390.90s (0:06:30) ========================
  ```
- Full repository test suite:
  ```
  python -m pytest -v
  ======================= 161 passed in 792.30s (0:13:12) =======================
  ```
- Deep audit invariant test suite:
  ```
  python -m pytest scratch/test_portfolio_math_deep_audit.py -v
  ======================= 3 passed in 2.54s ======================================
  ```

---

## 2. Logic Chain

1. **Step 1 (Portfolio Math Precision)**: Observation A proves that both the backtest engine and UI layer enforce a strict $\$10,000.00$ model portfolio capital basis, precisely allocating $\$2,000.00$ ($20\%$) across 5 positions for TASE and $\$1,000.00$ ($10\%$) across 10 positions for US.
2. **Step 2 (TASE Alpha Invariant Across All Market Regimes)**: Observation B empirically proves that Net TASE Alpha ($\alpha_{\$} = \text{Basket Value} - \text{Benchmark Value}$, $\alpha_{\%} = \text{Basket Return} - \text{Benchmark Return}$) accurately calculates excess return vs `^TA125.TA` in both bull and bear market regimes. In Quadrant 3 (bear capital preservation), picks falling less than the index produce positive net dollar alpha ($+\$1,000$), preserving capital as required by the specification.
3. **Step 3 (Multi-Universe Separation)**: Observation C proves that DuckDB SQL filtering and Python backtest execution keep TASE and US universes strictly separated. Tickers with `.TA` or exchange `TASE` cannot pollute US screener results, and US tickers cannot pollute TASE screener results. Trading calendar alignment uses the specific benchmark's historical trade dates.
4. **Step 4 (UI Resilience and Quality)**: Observations A and C confirm that empty universes, missing metadata, and NaN names do not crash the application or cause display defects. The UI renders both US and TASE categories cleanly and independently.
5. **Step 5 (Empirical Pass Confirmation)**: Observation D demonstrates that all 161 unit, integration, and adversarial tests across the entire repository pass with zero errors.

---

## 3. Caveats

- **Caveat 1**: Future additions of new international exchanges (e.g. LSE, TSX) will need their own benchmark routing and currency/unit scale configs.
- **Caveat 2**: All empirical stress tests were executed on DuckDB in-memory and local disk backends using real and synthetic multi-year market data.
- **Caveat 3**: No other caveats.

---

## 4. Conclusion

All quantitative calculation requirements, portfolio math invariants ($10,000 capital, 5x $2,000 TASE vs 10x $1,000 US), 4-quadrant Net Alpha vs `^TA125.TA`, and multi-universe state isolation have been empirically verified and pass all stress harnesses.

**Explicit Verdict**: **APPROVE**

---

## 5. Verification Method

To independently verify all findings:

1. **Run targeted adversarial test suites**:
   ```bash
   python -m pytest tests/test_adversarial_engine_tase.py src/test_cli_ui.py tests/test_adversarial_m3_ui.py -v
   ```
2. **Run 4-quadrant math & universe isolation harness**:
   ```bash
   python -m pytest scratch/test_portfolio_math_and_quadrants.py scratch/test_portfolio_math_deep_audit.py -v
   ```
3. **Run full repository regression test suite**:
   ```bash
   python -m pytest -v
   ```
4. **Inspect Source Files**:
   - `src/engine/backtest_engine.py`: Lines 161-186 (portfolio allocation & sizing).
   - `src/engine/screener_queries.py`: Lines 386-401 (universe filtering & benchmark assignment).
   - `src/ui/app.py`: Lines 608-620, 788-796 (metric cards $10k math).
