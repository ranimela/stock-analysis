# Handoff Report: CLI Multi-Exchange & Ingestion Test Suite (Milestone 1)

**Agent**: Explorer M1_3 (CLI & Ingestion Test Specialist)  
**Target Path**: `c:\Users\rmelamed\Projects\stock-analysis\.agents\explorer_m1_3\handoff.md`  
**Date**: 2026-08-27  

---

## 1. Observation

1. **CLI Subcommand Structure in `src/cli.py`**:
   - `src/cli.py` lines 35-70 define `seed(db_path: str, chunk_size: int)`. It currently hardcodes US symbol discovery via `fetch_symbol_directory()` without an `--exchange` filter option.
   - `src/cli.py` lines 71-92 define `update(db_path: str)`. It currently invokes `ingestor.sync_universe()` with default parameters without an `--exchange` filter option.
   - `src/cli.py` lines 140-210 define `scan(db_path: str)` which orchestrates live screener and backtest runs across US equities.
2. **Ingestion Test Suite in `src/ingestion/test_ingestion.py`**:
   - Lines 1-171 contain 7 unit tests covering `is_common_stock_filtering`, `parse_nasdaqlisted`, `parse_otherlisted`, `sync_symbol_metadata`, `download_spy_hard_gate_failure`, `parse_and_store_bars`, and `delta_sync_filtering`.
   - Zero tests currently exist for TASE directory ingestion, `^TA125.TA` benchmark hard-gating, single-ticker `.TA` exchange tagging, or CLI `--exchange` option parsing.
3. **Data Ingestor Behavior in `src/ingestion/data_ingestor.py`**:
   - Lines 427-434 in `sync_single_ticker`: Metadata insertion hardcodes `exchange = 'NASDAQ'` for single ticker syncs:
     ```python
     INSERT INTO symbol_metadata (ticker, name, exchange, asset_class, market_cap, is_active, first_added_date, last_updated_date)
     VALUES (?, ?, 'NASDAQ', 'Common Stock', ?, true, CURRENT_DATE(), CURRENT_DATE())
     ```
     This corrupts `.TA` tickers unless updated to infer `'TASE'`.
   - Lines 65-106 in `download_spy`: Only downloads `SPY`. TASE requires `download_tase_benchmark()` for `^TA125.TA`.
4. **Current Test Suite Baseline**:
   - Executing `python -m pytest` outputs: `21 passed in 8.43s` across `src/db/`, `src/engine/`, `src/ingestion/`, and `src/test_cli_ui.py`.

---

## 2. Logic Chain

1. **CLI Extension Logic**:
   - Adding `@click.option("--exchange", "-e", type=click.Choice(["US", "TASE", "ALL"], case_sensitive=False), default="ALL")` to `seed` and `update` allows the user to specify whether to ingest/update US equities, TASE equities, or both.
   - For `seed`: When `exchange in ("US", "ALL")`, it fetches US symbols from `fetch_symbol_directory()`; when `exchange in ("TASE", "ALL")`, it fetches TASE symbols from `get_tase_symbol_directory()`. Both sets are merged and stored in `symbol_metadata`.
   - For `update`: It passes `exchange` to `ingestor.sync_universe(exchange=exchange)` to target delta updates for the specified exchange universe.

2. **Ingestion Test Suite Design Logic**:
   - To verify TASE directory integrity without network dependence, `test_get_tase_symbol_directory_structure` and `test_tase_directory_key_constituents` validate the static/curated directory structure and blue chips (`TEVA.TA`, `LUMI.TA`, `NICE.TA`, `ICL.TA`, `POLI.TA`, `ESLT.TA`).
   - To verify benchmark reliability and defensive gating, `test_download_tase_benchmark_success`, `test_download_tase_benchmark_empty_failure`, and `test_sync_universe_tase_hard_gate` mock `yfinance.download` and verify that any failure of `^TA125.TA` immediately halts the pipeline.
   - To verify single-ticker exchange tagging, `test_sync_single_ticker_tase` asserts that `.TA` symbols are recorded with `exchange = 'TASE'` and not `'NASDAQ'`.
   - To verify CLI argument parsing and error handling, `test_cli_seed_exchange_tase`, `test_cli_seed_exchange_us`, `test_cli_seed_exchange_all`, `test_cli_update_exchange_tase`, and `test_cli_invalid_exchange_option` run `CliRunner` with mock fixtures and assert proper exit codes and stdout logs.

3. **Hermetic Mocking & Contamination Prevention**:
   - All tests use `tmp_path` fixture for temporary DuckDB instances and patch `yfinance.download` / `DataIngestor` methods to prevent any real HTTP/FTP calls or host system modifications.

---

## 3. Caveats

- **Scope Boundary**: This specification applies to Milestone 1 (Ingestion & CLI). Parameterizing `run_screener` and `run_point_in_time_backtest` for TASE is scoped for Milestone 2 (`src/engine/`), and UI rendering is scoped for Milestone 3 (`src/ui/`).
- **Dependencies**: CLI `seed` importing `get_tase_symbol_directory` depends on `src/ingestion/tase_directory.py` (being designed by Explorer M1_1). `DataIngestor.sync_universe(exchange=...)` depends on `src/ingestion/data_ingestor.py` updates (being designed by Explorer M1_2).

---

## 4. Conclusion

1. **`src/cli.py` Modifications**:
   - Import `get_tase_symbol_directory` from `src.ingestion.tase_directory`.
   - Add `@click.option("--exchange", "-e", type=click.Choice(["US", "TASE", "ALL"], case_sensitive=False), default="ALL")` to `seed` and `update`.
   - Branch symbol fetching in `seed` based on `exchange`.
   - Pass `exchange` to `ingestor.sync_universe(exchange=exchange_upper)`.

2. **`src/ingestion/test_ingestion.py` Modifications**:
   - Add `make_mock_yf_df` helper fixture.
   - Add 15 new test cases covering TASE directory parsing, benchmark download & hard-gating, single-ticker sync exchange tagging, batch OHLCV parsing, delta sync filtering, and CLI `--exchange` option invocations.

---

## 5. Verification Method

To verify the implementation independently once built:

1. **Run Full Test Suite**:
   ```powershell
   python -m pytest -v
   ```
   *Expected outcome*: All tests in `src/ingestion/test_ingestion.py` (and existing tests in `src/db/`, `src/engine/`, `src/test_cli_ui.py`) pass with 100% success rate (36+ passed tests).

2. **CLI Help Output Verification**:
   ```powershell
   python -m src.cli seed --help
   python -m src.cli update --help
   ```
   *Expected outcome*: `--exchange` option appears in the help menu with choices `[US|TASE|ALL]` and default `ALL`.

3. **Invalid Parameter Gating**:
   ```powershell
   python -m src.cli seed --exchange INVALID
   ```
   *Expected outcome*: Click aborts immediately with exit code 2 and usage error message without modifying any database.
