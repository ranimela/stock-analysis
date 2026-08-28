## 2026-08-27T13:55:13Z

You are Worker M1 (Implementation Specialist for Milestone 1: TASE Ingestion & Data Pipeline).
Your working directory is: c:\Users\rmelamed\Projects\stock-analysis\.agents\worker_m1
Project root: c:\Users\rmelamed\Projects\stock-analysis
Original request file: c:\Users\rmelamed\Projects\stock-analysis\.agents\ORIGINAL_REQUEST.md
Project plan file: c:\Users\rmelamed\Projects\stock-analysis\.agents\PROJECT.md

Explorer handoffs to review:
- c:\Users\rmelamed\Projects\stock-analysis\.agents\explorer_m1_1\handoff.md (and analysis.md)
- c:\Users\rmelamed\Projects\stock-analysis\.agents\explorer_m1_2\handoff.md (and analysis.md)
- c:\Users\rmelamed\Projects\stock-analysis\.agents\explorer_m1_3\handoff.md (and analysis.md)

Files you own and are tasked with implementing:
1. `src/ingestion/tase_directory.py` (New module: curated TA-125 constituents catalog, helper functions, symbol metadata seeder).
2. `src/ingestion/data_ingestor.py` (Update: benchmark gating for `^TA125.TA`, parameterize `sync_universe` with `exchange="ALL"|"US"|"TASE"`, fix `sync_single_ticker` to store `exchange = 'TASE'` for `.TA` tickers).
3. `src/cli.py` (Update: add `--exchange` option to `seed` and `update` subcommands).
4. `src/ingestion/test_ingestion.py` (Update: comprehensive unit & integration tests for all new TASE ingestion functionality).
