## 2026-08-27T13:51:05Z
You are Explorer M1_3 (CLI & Ingestion Test Specialist) for Milestone 1.
Working directory: c:\Users\rmelamed\Projects\stock-analysis\.agents\explorer_m1_3
Project root: c:\Users\rmelamed\Projects\stock-analysis
Original request file: c:\Users\rmelamed\Projects\stock-analysis\.agents\ORIGINAL_REQUEST.md
Project plan file: c:\Users\rmelamed\Projects\stock-analysis\.agents\PROJECT.md

Task:
Read ORIGINAL_REQUEST.md and PROJECT.md, and investigate `src/cli.py` and `src/ingestion/test_ingestion.py`:
1. Check how `src/cli.py` parses arguments for `seed`, `update`, `screen`, `backtest`, and `diagnose`.
2. Formulate CLI extensions for `--exchange` (supporting `US`, `TASE`, `ALL`) on `seed` and `update` commands.
3. Formulate comprehensive unit and integration tests to add to `src/ingestion/test_ingestion.py`:
   - Test TASE directory retrieval and metadata format (`exchange == 'TASE'`).
   - Test `^TA125.TA` benchmark download and hard-gating on failure.
   - Test single ticker sync for `.TA` tickers storing `exchange = 'TASE'`.
   - Test batch bar ingestion for TASE equities.
   - Test CLI command invocations with `--exchange TASE`.
4. Ensure all tests run with proper mocks (yfinance mock fixtures) and zero host contamination.

Write your report to:
c:\Users\rmelamed\Projects\stock-analysis\.agents\explorer_m1_3\analysis.md
and write a self-contained handoff report to:
c:\Users\rmelamed\Projects\stock-analysis\.agents\explorer_m1_3\handoff.md
Send a completion message back with summary and artifact path when finished.
