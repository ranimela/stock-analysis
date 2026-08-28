## 2026-08-27T18:40:51Z

You are Worker M3_1 implementing Milestone 3: Streamlit UI Dedicated TASE Section across Views A, B, C, D, and E.

Working directory: c:\Users\rmelamed\Projects\stock-analysis\.agents\worker_m3_1
Project root: c:\Users\rmelamed\Projects\stock-analysis

Inputs to read:
- c:\Users\rmelamed\Projects\stock-analysis\.agents\ORIGINAL_REQUEST.md
- c:\Users\rmelamed\Projects\stock-analysis\.agents\PROJECT.md
- c:\Users\rmelamed\Projects\stock-analysis\.agents\TEST_INFRA.md
- c:\Users\rmelamed\Projects\stock-analysis\.agents\explorer_m3_1\handoff.md
- c:\Users\rmelamed\Projects\stock-analysis\.agents\explorer_m3_2\handoff.md
- c:\Users\rmelamed\Projects\stock-analysis\.agents\explorer_m3_3\handoff.md

Write ownership:
- `src/ui/app.py`
- `src/test_cli_ui.py` (and any new UI test files if needed)

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Core Objectives:
1. CSS & Visual Design:
   - Implement `.title-tase` and `.portfolio-card-tase` styling in `src/ui/app.py` with high-contrast distinct palette (#eef5fc, #0b4f8a accents).
   - Format TASE currency/prices in Agorot ('Ag.') and market caps/volumes with appropriate Agorot indicators.
2. View A (Live Recommendations):
   - Run `run_screener(db_manager, cutoff_date=latest_date, universe="TASE")`.
   - Render dedicated Top 5 TASE recommendations section below US Top 10 with `.title-tase` banner, Agorot table, and dedicated TASE CSV download button.
3. Views B, C, and E (Backtest Portfolios):
   - Run `run_point_in_time_backtest(db_manager, cutoff_days_ago=..., custom_cutoff_date=..., universe="TASE")`.
   - Render 3 dedicated high-contrast TASE benchmark cards (`.portfolio-card-tase`):
     1. `^TA125.TA` Index ($10k Buy & Hold)
     2. 5x $2,000 Top 5 TASE stock picks ($10k total allocation)
     3. Net TASE Alpha vs `^TA125.TA`
   - Render Top 5 TASE Historical Position Performance table (`build_html_table(..., is_backtest=True, is_tase=True)`).
4. View D (Diagnostics Lab):
   - Support user-supplied `.TA` tickers with dynamic detection.
   - Stage-2 Checklist: Price Floor (>= 100.0 Agorot), Liquidity (>= 20M Agorot), Mansfield RS vs `^TA125.TA`, and qualification against Top 5 TASE recommendations.
   - Sync single ticker download support for missing `.TA` tickers.
5. Verification:
   - Write comprehensive tests in `src/test_cli_ui.py` covering Views A, B, C, D, E, HTML tables, CSS classes, cards, and edge cases.
   - Run the full test suite (`pytest`) across the repository and verify 100% pass rate.
   - Write your handoff report to `c:\Users\rmelamed\Projects\stock-analysis\.agents\worker_m3_1\handoff.md` with complete build/test commands and outputs.
