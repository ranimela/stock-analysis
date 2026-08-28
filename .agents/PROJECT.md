# Project: Tel Aviv Stock Exchange (TA-125) Integration

## Architecture
- **Ingestion Layer**: `src/ingestion/tase_directory.py`, `src/ingestion/data_ingestor.py`, `src/cli.py`
  - Ingests TA-125 constituents list with `exchange = 'TASE'`.
  - Ingests and hard-gates `^TA125.TA` benchmark ticker alongside `SPY`.
  - Tags `.TA` tickers accurately with `exchange = 'TASE'` in DuckDB `symbol_metadata`.
- **Database Layer**: `src/db/db_manager.py`, `src/db/schema.sql`
  - Stores TASE equities in `symbol_metadata` and `daily_bars`.
- **Quantitative Screener Engine Layer**: `src/engine/screener_queries.py`, `src/engine/backtest_engine.py`
  - Runs VCP, 52W High/Low distance, Minervini trend template, and ADV20 liquidity filters parameterized by `universe = "US" | "TASE"`.
  - Benchmarks US stocks against `SPY` and TASE stocks against `^TA125.TA`.
  - Calculates `PERCENT_RANK()` isolated within the TASE pool to yield a dedicated Top 5 TASE recommendation list.
- **Streamlit Web Application Layer**: `src/ui/app.py`
  - Injects high-contrast CSS styling for TASE (`.title-tase`, `.portfolio-card-tase`).
  - Displays Top 5 TASE recommendations in dedicated visual cards below the US Top 10 across Views A, B, C, D, and E.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | TA-125 Universe Directory | Seed curated TA-125 constituent tickers (`.TA`) with `exchange = 'TASE'` | M1 | R1 (DONE) |
| 2 | Benchmark Ingestion & Gating | Ingest and enforce hard-gating for `^TA125.TA` benchmark | M1 | R1 (DONE) |
| 3 | Single-Ticker TASE Tagging | Auto-infer `exchange = 'TASE'` for `.TA` tickers in `sync_single_ticker` | M1 | R1 (DONE) |
| 4 | CLI Multi-Exchange Support | Allow seeding and updating TASE via CLI (`--exchange TASE` / `--exchange ALL`) | M1 | R1 (DONE) |
| 5 | TASE Quantitative Screener | Parameterize `run_screener(universe="TASE")` with `^TA125.TA` benchmark and TASE liquidity floors | M2 | R2 |
| 6 | TASE Backtest Engine | Parameterize `run_point_in_time_backtest(universe="TASE")` against `^TA125.TA` benchmark | M2 | R2 |
| 7 | Dedicated Top 5 TASE Separation | Extract top 5 TASE equities ranked by composite score independent of US stocks | M2 | R2 |
| 8 | Streamlit Custom Styling for TASE | High-contrast visual styling (`.title-tase`, `.portfolio-card-tase`) | M3 | R3 |
| 9 | Streamlit View A TASE Section | Dedicated Top 5 TASE live recommendations card below US Top 10 | M3 | R3 |
| 10 | Streamlit View B TASE Section | Dedicated Top 5 TASE 1-Week backtest portfolio & card below US Top 10 | M3 | R3 |
| 11 | Streamlit View C TASE Section | Dedicated Top 5 TASE 1-Month backtest portfolio & card below US Top 10 | M3 | R3 |
| 12 | Streamlit View D TASE Diagnostics | Diagnostic lab support for `.TA` tickers benchmarked against `^TA125.TA` | M3 | R3 |
| 13 | Streamlit View E TASE Section | Dedicated Top 5 TASE custom-date backtest portfolio & card below US Top 10 | M3 | R3 |
| 14 | E2E Testing & Hardening | Full 4-tier test suite + Challenger adversarial verification + Forensic Audit | M4 | Acceptance Criteria |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | TASE Ingestion & Data Pipeline | `src/ingestion/tase_directory.py`, `src/ingestion/data_ingestor.py`, `src/cli.py`, `src/ingestion/test_ingestion.py` | none | DONE |
| 2 | Quantitative Engine Adaptation | `src/engine/screener_queries.py`, `src/engine/backtest_engine.py`, `src/engine/test_engine.py` | M1 | DONE |
| 3 | Streamlit UI Dedicated TASE Section | `src/ui/app.py`, `src/test_cli_ui.py` across Views A, B, C, D, E | M2 | DONE |
| 4 | E2E Testing, Adversarial Verification & Audit | Opaque-box E2E test suite, Challenger stress testing, Forensic Audit | M3 | IN_PROGRESS |

## Interface Contracts

### Ingestion ↔ Engine
- DuckDB `symbol_metadata`: `exchange` is set to `'TASE'` for `.TA` tickers.
- DuckDB `daily_bars`: Benchmark ticker is `^TA125.TA` with standard OHLCV bars.
- TASE constituent tickers match `.TA` suffix format recognized by Yahoo Finance.

### Engine ↔ UI
- `run_screener(conn, cutoff_date=None, universe="US"|"TASE") -> pd.DataFrame`
  - For `universe="TASE"`: Returns DataFrame sorted by `composite_score DESC` containing columns: `ticker`, `name`, `close`, `adv_20`, `sma_50`, `sma_200`, `vcp_ratio`, `high_52w_dist`, `low_52w_dist`, `rs_63_ratio`, `rs_252_ratio`, `composite_score`.
- `run_point_in_time_backtest(conn, cutoff_date, universe="US"|"TASE") -> tuple[pd.DataFrame, float]`
  - For `universe="TASE"`: Returns `(df_portfolio, ta125_benchmark_return)`.
- UI extracts `df_tase.head(5)` to render Top 5 TASE recommendations.

## Code Layout
```
src/
├── db/
│   ├── db_manager.py
│   ├── schema.sql
│   └── test_db_manager.py
├── engine/
│   ├── backtest_engine.py
│   ├── screener_queries.py
│   └── test_engine.py
├── ingestion/
│   ├── data_ingestor.py
│   ├── tase_directory.py      # TA-125 constituent seeding (DONE)
│   ├── us_directory.py
│   └── test_ingestion.py     # Ingestion tests (DONE)
├── ui/
│   └── app.py                 # Streamlit UI with Views A, B, C, D, E
├── cli.py                     # Multi-exchange CLI (DONE)
└── test_cli_ui.py
tests/
└── e2e/                       # E2E test suite
```
