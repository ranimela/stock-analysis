## 2026-08-27T14:06:01Z

You are Explorer M2_1 (Screener Queries Specialist) for Milestone 2.
Your working directory is: c:\Users\rmelamed\Projects\stock-analysis\.agents\explorer_m2_1
Project root: c:\Users\rmelamed\Projects\stock-analysis
Original request file: c:\Users\rmelamed\Projects\stock-analysis\.agents\ORIGINAL_REQUEST.md
Project plan file: c:\Users\rmelamed\Projects\stock-analysis\.agents\PROJECT.md

Task:
Read ORIGINAL_REQUEST.md and PROJECT.md, and investigate `src/engine/screener_queries.py`:
1. Analyze the SQL CTE chain in `run_screener()`: `date_anchor`, `spy_bars` (benchmark CTE), `ticker_dates`, `base_bars`, `bar_indicators`, `bar_atr`, `latest_snapshot`, `stage_filters`, `composite_scoring`, `final_ranked`.
2. Formulate exact modifications to parameterize `run_screener(conn, cutoff_date=None, universe="US", benchmark_ticker=None)`:
   - Route benchmark ticker dynamically (`SPY` for US, `^TA125.TA` for TASE).
   - Filter `symbol_metadata.exchange` accordingly (`exchange IN ('NASDAQ', 'NYSE', 'AMEX', 'ARCA', 'BATS')` for US, `exchange = 'TASE'` for TASE).
   - Calibrate price & liquidity filters for TASE (e.g. price >= 100.0 Agorot, ADV20 >= 20,000,000 Agorot).
   - Ensure all momentum, VCP, 52W High/Low distance, and Mansfield RS calculations work smoothly and calculate percentile rank `PERCENT_RANK()` isolated within the universe pool.
3. Ensure no regressions on existing US screening functionality.

Write your report to:
c:\Users\rmelamed\Projects\stock-analysis\.agents\explorer_m2_1\analysis.md
and write a self-contained handoff report to:
c:\Users\rmelamed\Projects\stock-analysis\.agents\explorer_m2_1\handoff.md
Send a completion message back when finished.
