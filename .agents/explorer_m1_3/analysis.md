# Technical Analysis & Test Specification: CLI Multi-Exchange & Ingestion Test Suite

**Author**: Explorer M1_3 (CLI & Ingestion Test Specialist)  
**Date**: 2026-08-27  
**Scope**: `src/cli.py`, `src/ingestion/test_ingestion.py`, and CLI Ingestion Integration  
**Status**: COMPLETE  

---

## 1. Executive Summary

This report establishes the complete specification for:
1. Extending `src/cli.py` with the `--exchange` option (`US`, `TASE`, `ALL`) across `seed` and `update` commands.
2. Analyzing argument parsing for current and future CLI commands (`seed`, `update`, `scan` / `screen`, `backtest`, `diagnose`).
3. Designing a 20-test comprehensive unit and integration test suite for `src/ingestion/test_ingestion.py` to validate TASE directory parsing, `^TA125.TA` benchmark ingestion with hard-gating, single-ticker `.TA` exchange tagging, batch OHLCV ingestion, and CLI multi-exchange invocations.
4. Implementing a hermetic mock architecture (`yfinance` mock fixtures + temporary DuckDB instances) guaranteeing zero host contamination and 100% deterministic test execution.

---

## 2. CLI Architecture & Argument Parsing Investigation (`src/cli.py`)

### 2.1 Current Subcommand Inventory in `src/cli.py`

| Subcommand | Current Arguments & Options | Implementation Function | Description |
| :--- | :--- | :--- | :--- |
| `seed` | `--db-path` (default `market_data.duckdb`), `--chunk-size` (default `100`) | `seed(db_path, chunk_size)` | Downloads US symbol directory, writes metadata, and ingests historical bars. |
| `update` | `--db-path` (default `market_data.duckdb`) | `update(db_path)` | Executes daily delta sync for existing database equities. |
| `export-delta` | `--db-path`, `--output-dir` (default `data/daily_deltas`) | `export_delta(db_path, output_dir)` | Exports latest trade date bars to a single Parquet file and prunes files older than 7 days. |
| `sync-delta` | `--db-path`, `--deltas-dir` (default `data/daily_deltas`) | `sync_delta(db_path, deltas_dir)` | Merges un-synced Parquet delta files into local DuckDB. |
| `scan` | `--db-path` (default `market_data.duckdb`) | `scan(db_path)` | Orchestrates T0 Live Screener, T-5 (1-Week), and T-22 (1-Month) PIT backtests and outputs formatted terminal summary. |

### 2.2 Alignment of `screen`, `backtest`, and `diagnose` Commands

The system currently exposes the combined `scan` command to execute the full pipeline (T0 live screener + T-5 backtest + T-22 backtest). In Milestone 2 and Milestone 3:
- `scan` / `screen`: Can accept `--universe [US|TASE|ALL]` to restrict or segment the screener output.
- `backtest`: Parameterized by `--cutoff-days-ago [5|22]` and `--universe [US|TASE|ALL]`.
- `diagnose`: Supports on-demand single ticker diagnostic runs (e.g. `python -m src.cli diagnose --ticker TEVA.TA`).

---

## 3. CLI Extension Specification for `--exchange`

### 3.1 Click Option Definition
For both `seed` and `update`, add the `--exchange` option:

```python
@click.option(
    "--exchange",
    "-e",
    type=click.Choice(["US", "TASE", "ALL"], case_sensitive=False),
    default="ALL",
    help="Target exchange universe to seed/update (US, TASE, or ALL).",
    show_default=True,
)
```

### 3.2 Detailed Logic for `seed`

When `seed` is invoked with `--exchange`:
1. Parse `exchange_upper = exchange.upper()`.
2. Symbol Discovery:
   - If `exchange_upper in ("US", "ALL")`: Invoke `fetch_symbol_directory()` to retrieve US common stock symbols.
   - If `exchange_upper in ("TASE", "ALL")`: Invoke `get_tase_symbol_directory()` (from `src.ingestion.tase_directory`) to retrieve TA-125 constituent symbols.
   - Combine symbols into a single list and deduplicate by ticker.
3. Metadata Synchronization:
   - Call `sync_symbol_metadata(db_manager, symbols)` to store ticker, name, exchange (`'NASDAQ'`, `'NYSE'`, or `'TASE'`), and asset class.
4. Historical Bar Ingestion:
   - Instantiate `ingestor = DataIngestor(db_manager=db_manager, chunk_size=chunk_size)`.
   - Execute `summary = ingestor.sync_universe(symbols=symbols, exchange=exchange_upper)`.
   - Log structured summary.

### 3.3 Detailed Logic for `update`

When `update` is invoked with `--exchange`:
1. Parse `exchange_upper = exchange.upper()`.
2. Ingestion Execution:
   - Instantiate `ingestor = DataIngestor(db_manager=db_manager)`.
   - Execute `summary = ingestor.sync_universe(exchange=exchange_upper)`.
   - Ingestor synchronizes benchmark(s) (`SPY` for US/ALL, `^TA125.TA` for TASE/ALL), identifies equities requiring delta updates for the specified exchange filter, and ingests missing bars.

### 3.4 Proposed Code for `src/cli.py`

```python
# Proposed modifications in src/cli.py

from src.ingestion.tase_directory import get_tase_symbol_directory

@main.command()
@click.option(
    "--db-path",
    default="market_data.duckdb",
    help="Path to DuckDB database file.",
    show_default=True,
)
@click.option(
    "--chunk-size",
    default=100,
    help="Batch chunk size for ticker data fetching.",
    show_default=True,
)
@click.option(
    "--exchange",
    "-e",
    type=click.Choice(["US", "TASE", "ALL"], case_sensitive=False),
    default="ALL",
    help="Target exchange universe to seed (US, TASE, or ALL).",
    show_default=True,
)
def seed(db_path: str, chunk_size: int, exchange: str) -> None:
    """Initial database seed (downloads master ticker list and runs chunked ingestion)."""
    exchange_upper = exchange.upper()
    click.echo(f"Initializing database seed at '{db_path}' for exchange universe: {exchange_upper}...")
    db_manager = DatabaseManager(db_path=db_path, read_only=False)

    symbols: list[dict[str, Any]] = []
    if exchange_upper in ("US", "ALL"):
        click.echo("Fetching master symbol directory from NASDAQ/Other exchange lists...")
        try:
            us_symbols = fetch_symbol_directory()
            click.echo(f"Discovered {len(us_symbols)} US common stock symbols.")
            symbols.extend(us_symbols)
        except Exception as err:
            click.echo(f"Warning: Could not fetch US symbol directory: {err}", err=True)

    if exchange_upper in ("TASE", "ALL"):
        click.echo("Fetching TASE TA-125 symbol directory...")
        try:
            tase_symbols = get_tase_symbol_directory()
            click.echo(f"Discovered {len(tase_symbols)} TASE constituent symbols.")
            symbols.extend(tase_symbols)
        except Exception as err:
            click.echo(f"Warning: Could not fetch TASE symbol directory: {err}", err=True)

    if not symbols:
        click.echo("Error: No symbols discovered for requested exchange universe.", err=True)
        sys.exit(1)

    sync_symbol_metadata(db_manager, symbols)
    click.echo("Symbol metadata synchronized to database.")

    ingestor = DataIngestor(db_manager=db_manager, chunk_size=chunk_size)
    click.echo("Starting historical bar ingestion...")
    summary = ingestor.sync_universe(symbols=symbols, exchange=exchange_upper)

    click.echo("\n--- Seed Complete ---")
    click.echo(f"Total Tickers: {summary['total_tickers']}")
    click.echo(f"Synced Tickers: {summary['synced_tickers']}")
    click.echo(f"Total Bars Inserted: {summary['total_bars_inserted']}")
    click.echo(f"Status: {summary['status']}")


@main.command()
@click.option(
    "--db-path",
    default="market_data.duckdb",
    help="Path to DuckDB database file.",
    show_default=True,
)
@click.option(
    "--exchange",
    "-e",
    type=click.Choice(["US", "TASE", "ALL"], case_sensitive=False),
    default="ALL",
    help="Target exchange universe to update (US, TASE, or ALL).",
    show_default=True,
)
def update(db_path: str, exchange: str) -> None:
    """Daily delta sync (fetches newest EOD bar)."""
    exchange_upper = exchange.upper()
    click.echo(f"Starting daily delta update for database '{db_path}' (exchange: {exchange_upper})...")
    db_manager = DatabaseManager(db_path=db_path, read_only=False)

    ingestor = DataIngestor(db_manager=db_manager)
    summary = ingestor.sync_universe(exchange=exchange_upper)

    click.echo("\n--- Update Complete ---")
    click.echo(f"Total Tickers: {summary['total_tickers']}")
    click.echo(f"Synced Tickers: {summary['synced_tickers']}")
    click.echo(f"Total Bars Inserted: {summary['total_bars_inserted']}")
    click.echo(f"Status: {summary['status']}")
```

---

## 4. Ingestion Test Suite Specification (`src/ingestion/test_ingestion.py`)

A comprehensive 20-test specification covering all TASE ingestion and CLI functionality.

### 4.1 Mock Fixture Architecture

```python
import datetime
from pathlib import Path
from typing import Sequence
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest
from click.testing import CliRunner

from src.db.db_manager import DatabaseManager
from src.ingestion.data_ingestor import DataIngestor
from src.ingestion.tase_directory import TASE_BENCHMARK, get_tase_symbol_directory
from src.ingestion.symbol_directory import sync_symbol_metadata


def make_mock_yf_df(
    tickers: Sequence[str],
    dates: Sequence[str] | pd.DatetimeIndex,
    start_price: float = 1000.0,
) -> pd.DataFrame:
    """Generates synthetic multi-index or single-index yfinance DataFrame."""
    if isinstance(dates, list):
        idx = pd.to_datetime(dates)
    else:
        idx = dates

    ticker_list = [t.strip().upper() for t in tickers]
    data = {}
    for i, t in enumerate(ticker_list):
        base = start_price + (i * 100.0)
        data[("Open", t)] = [base + j for j in range(len(idx))]
        data[("High", t)] = [base + j + 5.0 for j in range(len(idx))]
        data[("Low", t)] = [base + j - 5.0 for j in range(len(idx))]
        data[("Close", t)] = [base + j + 2.0 for j in range(len(idx))]
        data[("Adj Close", t)] = [base + j + 2.0 for j in range(len(idx))]
        data[("Volume", t)] = [50000 + (j * 1000) for j in range(len(idx))]

    df = pd.DataFrame(data, index=idx)
    df.columns = pd.MultiIndex.from_tuples(df.columns)
    return df
```

### 4.2 Test Inventory & Detailed Specifications

#### Tier 1: TASE Directory & Metadata Tests
1. **`test_get_tase_symbol_directory_structure()`**:
   - Verifies `get_tase_symbol_directory()` returns $\ge 100$ items.
   - Asserts each dictionary schema: `ticker` (ends with `.TA`), `name` (non-empty string), `exchange == 'TASE'`, `asset_class == 'Common Stock'`, `is_active is True`.
2. **`test_tase_directory_key_constituents()`**:
   - Confirms inclusion of anchor equities: `TEVA.TA`, `LUMI.TA`, `NICE.TA`, `ICL.TA`, `POLI.TA`, `ESLT.TA`, `DSCT.TA`, `AZRG.TA`, `BEZQ.TA`.
3. **`test_sync_tase_symbol_metadata(tmp_db)`**:
   - Calls `sync_symbol_metadata(tmp_db, tase_symbols)`.
   - Queries `symbol_metadata` in DuckDB.
   - Verifies count matches and `exchange = 'TASE'` for all records.
4. **`test_tase_benchmark_constant()`**:
   - Asserts `TASE_BENCHMARK == "^TA125.TA"`.

#### Tier 2: Benchmark Ingestion & Hard-Gating Tests
5. **`test_download_tase_benchmark_success(tmp_db)`**:
   - Patches `yfinance.download` with 5 synthetic daily bars for `^TA125.TA`.
   - Calls `ingestor.download_tase_benchmark()`.
   - Asserts return value == 5.
   - Verifies rows in `daily_bars` for `ticker = '^TA125.TA'`.
   - Verifies row in `symbol_metadata` for `^TA125.TA` with `exchange = 'TASE'` and `asset_class = 'Index'`.
6. **`test_download_tase_benchmark_empty_failure(tmp_db)`**:
   - Patches `yfinance.download` returning `pd.DataFrame()`.
   - Expects `pytest.raises(RuntimeError, match="TA-125 benchmark download failed")`.
7. **`test_download_tase_benchmark_exception_failure(tmp_db)`**:
   - Patches `yfinance.download` raising `Exception("HTTP 500 Network Timeout")`.
   - Expects `pytest.raises(RuntimeError, match="TA-125 benchmark download failed")`.
8. **`test_sync_universe_tase_hard_gate(tmp_db)`**:
   - Patches `download_tase_benchmark` to raise `RuntimeError`.
   - Invokes `ingestor.sync_universe(exchange="TASE")`.
   - Verifies execution aborts before any stock tickers are requested.
9. **`test_sync_universe_all_hard_gate_on_tase_failure(tmp_db)`**:
   - Patches `download_spy` to succeed and `download_tase_benchmark` to fail.
   - Invokes `ingestor.sync_universe(exchange="ALL")`.
   - Verifies execution halts with `RuntimeError`.

#### Tier 3: Single-Ticker Sync & Auto-Detection Tests
10. **`test_sync_single_ticker_tase(tmp_db)`**:
    - Calls `ingestor.sync_single_ticker("TEVA.TA")` with mocked yfinance download.
    - Asserts return is `True`.
    - Queries DuckDB `symbol_metadata` where `ticker = 'TEVA.TA'`.
    - Verifies `exchange == 'TASE'` (proves `.TA` is not hardcoded to `'NASDAQ'`).
    - Verifies `daily_bars` has rows for `'TEVA.TA'`.
11. **`test_sync_single_ticker_us(tmp_db)`**:
    - Calls `ingestor.sync_single_ticker("AAPL")` with mocked yfinance download.
    - Verifies `exchange == 'NASDAQ'`.
12. **`test_sync_single_ticker_lowercase_normalization(tmp_db)`**:
    - Calls `ingestor.sync_single_ticker("lumi.ta")`.
    - Verifies stored ticker is `"LUMI.TA"` with `exchange == 'TASE'`.

#### Tier 4: Batch Bar Ingestion & Delta Sync Tests
13. **`test_parse_and_store_bars_tase_multi_ticker(tmp_db)`**:
    - Creates synthetic MultiIndex DataFrame for `["TEVA.TA", "LUMI.TA", "NICE.TA"]` with 3 dates.
    - Calls `ingestor.parse_and_store_bars(df, ["TEVA.TA", "LUMI.TA", "NICE.TA"])`.
    - Asserts 9 bars inserted.
    - Verifies all 3 tickers exist in DuckDB `daily_bars`.
14. **`test_tase_delta_sync_filtering(tmp_db)`**:
    - Inserts existing bar for `TEVA.TA` on `2026-08-20`.
    - Provides DataFrame containing dates `2026-08-20` and `2026-08-21`.
    - Asserts only `2026-08-21` is inserted (1 new bar, 2 total in table).
15. **`test_sync_universe_tase_batching(tmp_db)`**:
    - Ingestor configured with `chunk_size = 2`.
    - Synchronizes 5 TASE tickers with mocked downloads.
    - Verifies multiple chunk calls and final status `"success"`.

#### Tier 5: CLI Invocation Tests
16. **`test_cli_seed_tase(tmp_path)`**:
    - Uses `CliRunner().invoke(main, ["seed", "--db-path", str(db_file), "--exchange", "TASE"])`.
    - Verifies exit code 0 and output strings: `"exchange universe: TASE"`, `"TASE constituent symbols"`, `"Seed Complete"`.
17. **`test_cli_seed_us(tmp_path)`**:
    - Uses `CliRunner().invoke(main, ["seed", "--db-path", str(db_file), "--exchange", "US"])`.
    - Verifies exit code 0 and output strings: `"exchange universe: US"`, `"US common stock symbols"`.
18. **`test_cli_seed_all(tmp_path)`**:
    - Uses `CliRunner().invoke(main, ["seed", "--db-path", str(db_file), "--exchange", "ALL"])`.
    - Verifies exit code 0 and both US and TASE discovery logs.
19. **`test_cli_update_tase(tmp_path)`**:
    - Uses `CliRunner().invoke(main, ["update", "--db-path", str(db_file), "--exchange", "TASE"])`.
    - Verifies exit code 0 and output string `"exchange: TASE"`.
20. **`test_cli_invalid_exchange(tmp_path)`**:
    - Uses `CliRunner().invoke(main, ["seed", "--db-path", str(db_file), "--exchange", "INVALID"])`.
    - Verifies exit code == 2 (Click usage error) and error message indicating invalid choice.

---

## 5. Hermetic Test Code Implementation for `src/ingestion/test_ingestion.py`

Below is the concrete implementation to append to / integrate into `src/ingestion/test_ingestion.py`:

```python
# ============================================================================
# TASE INGESTION & MULTI-EXCHANGE CLI TEST SUITE (Milestone 1)
# ============================================================================

def make_mock_yf_df(
    tickers: Sequence[str],
    dates: Sequence[str] | pd.DatetimeIndex,
    start_price: float = 1000.0,
) -> pd.DataFrame:
    """Helper to generate multi-index or single-index yfinance DataFrame."""
    if isinstance(dates, list):
        idx = pd.to_datetime(dates)
    else:
        idx = dates

    ticker_list = [t.strip().upper() for t in tickers]
    data = {}
    for i, t in enumerate(ticker_list):
        base = start_price + (i * 100.0)
        data[("Open", t)] = [base + j for j in range(len(idx))]
        data[("High", t)] = [base + j + 5.0 for j in range(len(idx))]
        data[("Low", t)] = [base + j - 5.0 for j in range(len(idx))]
        data[("Close", t)] = [base + j + 2.0 for j in range(len(idx))]
        data[("Adj Close", t)] = [base + j + 2.0 for j in range(len(idx))]
        data[("Volume", t)] = [50000 + (j * 1000) for j in range(len(idx))]

    df = pd.DataFrame(data, index=idx)
    df.columns = pd.MultiIndex.from_tuples(df.columns)
    return df


def test_get_tase_symbol_directory_structure():
    """Test TASE directory returns valid constituent metadata list."""
    from src.ingestion.tase_directory import get_tase_symbol_directory
    symbols = get_tase_symbol_directory()
    assert len(symbols) >= 100
    for s in symbols:
        assert s["ticker"].endswith(".TA")
        assert len(s["name"]) > 0
        assert s["exchange"] == "TASE"
        assert s["asset_class"] == "Common Stock"
        assert s["is_active"] is True


def test_tase_directory_key_constituents():
    """Test presence of core blue-chip constituents in TA-125 directory."""
    from src.ingestion.tase_directory import get_tase_symbol_directory
    symbols = get_tase_symbol_directory()
    tickers = {s["ticker"] for s in symbols}
    required = ["TEVA.TA", "LUMI.TA", "NICE.TA", "ICL.TA", "POLI.TA", "ESLT.TA", "DSCT.TA", "AZRG.TA", "BEZQ.TA"]
    for req in required:
        assert req in tickers


def test_sync_tase_symbol_metadata(tmp_db: DatabaseManager):
    """Test inserting TASE symbol metadata into DuckDB."""
    from src.ingestion.tase_directory import get_tase_symbol_directory
    symbols = get_tase_symbol_directory()[:10]
    inserted = sync_symbol_metadata(tmp_db, symbols)
    assert inserted == 10

    rows = tmp_db.execute_read("SELECT ticker, exchange, asset_class FROM symbol_metadata WHERE exchange = 'TASE'")
    assert len(rows) == 10
    assert all(r[1] == "TASE" for r in rows)


def test_download_tase_benchmark_success(tmp_db: DatabaseManager):
    """Test downloading and storing ^TA125.TA benchmark data."""
    ingestor = DataIngestor(db_manager=tmp_db)
    dates = ["2026-08-01", "2026-08-02", "2026-08-03"]
    mock_df = make_mock_yf_df(["^TA125.TA"], dates, start_price=2000.0)

    with patch("yfinance.download", return_value=mock_df):
        inserted = ingestor.download_tase_benchmark()
        assert inserted == 3

    rows = tmp_db.execute_read("SELECT ticker, trade_date, close FROM daily_bars WHERE ticker = '^TA125.TA' ORDER BY trade_date")
    assert len(rows) == 3
    assert rows[0][0] == "^TA125.TA"

    meta_rows = tmp_db.execute_read("SELECT ticker, exchange, asset_class FROM symbol_metadata WHERE ticker = '^TA125.TA'")
    assert len(meta_rows) == 1
    assert meta_rows[0] == ("^TA125.TA", "TASE", "Index")


def test_download_tase_benchmark_empty_failure(tmp_db: DatabaseManager):
    """Test download_tase_benchmark raises RuntimeError when empty data is returned."""
    ingestor = DataIngestor(db_manager=tmp_db)
    with patch("yfinance.download", return_value=pd.DataFrame()):
        with pytest.raises(RuntimeError, match="TA-125 benchmark download failed"):
            ingestor.download_tase_benchmark()


def test_download_tase_benchmark_network_exception_failure(tmp_db: DatabaseManager):
    """Test download_tase_benchmark raises RuntimeError on network exception."""
    ingestor = DataIngestor(db_manager=tmp_db)
    with patch("yfinance.download", side_effect=Exception("Connection timed out")):
        with pytest.raises(RuntimeError, match="TA-125 benchmark download failed"):
            ingestor.download_tase_benchmark()


def test_sync_universe_tase_hard_gate(tmp_db: DatabaseManager):
    """Test sync_universe hard-gates on TASE benchmark failure."""
    ingestor = DataIngestor(db_manager=tmp_db)
    with patch.object(ingestor, "download_tase_benchmark", side_effect=RuntimeError("Benchmark fail")):
        with pytest.raises(RuntimeError, match="Benchmark fail"):
            ingestor.sync_universe(exchange="TASE")


def test_sync_single_ticker_tase(tmp_db: DatabaseManager):
    """Test sync_single_ticker sets exchange = 'TASE' for .TA tickers."""
    ingestor = DataIngestor(db_manager=tmp_db)
    dates = ["2026-08-01", "2026-08-02"]
    mock_df = make_mock_yf_df(["TEVA.TA"], dates, start_price=6500.0)

    with patch.object(ingestor, "fetch_ticker_chunk", return_value=mock_df):
        success = ingestor.sync_single_ticker("TEVA.TA")
        assert success is True

    rows = tmp_db.execute_read("SELECT ticker, exchange FROM symbol_metadata WHERE ticker = 'TEVA.TA'")
    assert len(rows) == 1
    assert rows[0] == ("TEVA.TA", "TASE")

    bar_rows = tmp_db.execute_read("SELECT count(*) FROM daily_bars WHERE ticker = 'TEVA.TA'")
    assert bar_rows[0][0] == 2


def test_sync_single_ticker_us_exchange(tmp_db: DatabaseManager):
    """Test sync_single_ticker maintains NASDAQ exchange for US tickers."""
    ingestor = DataIngestor(db_manager=tmp_db)
    dates = ["2026-08-01", "2026-08-02"]
    mock_df = make_mock_yf_df(["AAPL"], dates, start_price=220.0)

    with patch.object(ingestor, "fetch_ticker_chunk", return_value=mock_df):
        success = ingestor.sync_single_ticker("AAPL")
        assert success is True

    rows = tmp_db.execute_read("SELECT ticker, exchange FROM symbol_metadata WHERE ticker = 'AAPL'")
    assert len(rows) == 1
    assert rows[0] == ("AAPL", "NASDAQ")


def test_parse_and_store_bars_tase_multi_ticker(tmp_db: DatabaseManager):
    """Test parsing multi-ticker TASE DataFrame and storing in DuckDB."""
    ingestor = DataIngestor(db_manager=tmp_db)
    tickers = ["TEVA.TA", "LUMI.TA", "NICE.TA"]
    dates = ["2026-08-01", "2026-08-02", "2026-08-03"]
    df = make_mock_yf_df(tickers, dates, start_price=5000.0)

    inserted = ingestor.parse_and_store_bars(df, tickers)
    assert inserted == 9

    rows = tmp_db.execute_read("SELECT DISTINCT ticker FROM daily_bars ORDER BY ticker")
    assert [r[0] for r in rows] == ["LUMI.TA", "NICE.TA", "TEVA.TA"]


def test_tase_delta_sync_filtering(tmp_db: DatabaseManager):
    """Test delta sync prevents inserting existing dates for TASE stocks."""
    ingestor = DataIngestor(db_manager=tmp_db)

    # Insert existing bar on 2026-08-01
    with tmp_db.write_cursor() as conn:
        conn.execute(
            """
            INSERT INTO daily_bars (ticker, trade_date, open, high, low, close, adj_close, volume)
            VALUES ('TEVA.TA', '2026-08-01', 5000.0, 5100.0, 4950.0, 5050.0, 5050.0, 100000);
            """
        )

    max_dates = ingestor.get_existing_max_dates()
    assert max_dates.get("TEVA.TA") == datetime.date(2026, 8, 1)

    df = make_mock_yf_df(["TEVA.TA"], ["2026-08-01", "2026-08-02"], start_price=5050.0)
    inserted = ingestor.parse_and_store_bars(df, ["TEVA.TA"], max_dates=max_dates)
    assert inserted == 1

    rows = tmp_db.execute_read("SELECT trade_date FROM daily_bars WHERE ticker = 'TEVA.TA' ORDER BY trade_date")
    assert len(rows) == 2


def test_cli_seed_exchange_tase(tmp_path: Path):
    """Test CLI seed command with --exchange TASE."""
    from src.cli import main
    db_file = tmp_path / "cli_tase_seed.duckdb"
    runner = CliRunner()

    with patch("src.ingestion.data_ingestor.DataIngestor.download_tase_benchmark", return_value=10):
        with patch("src.ingestion.data_ingestor.DataIngestor.fetch_ticker_chunk", return_value=pd.DataFrame()):
            res = runner.invoke(main, ["seed", "--db-path", str(db_file), "--exchange", "TASE"])
            assert res.exit_code == 0
            assert "exchange universe: TASE" in res.output
            assert "TASE constituent symbols" in res.output
            assert "Seed Complete" in res.output


def test_cli_seed_exchange_us(tmp_path: Path):
    """Test CLI seed command with --exchange US."""
    from src.cli import main
    db_file = tmp_path / "cli_us_seed.duckdb"
    runner = CliRunner()

    mock_us_symbols = [{"ticker": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ", "asset_class": "Common Stock", "is_active": True}]
    with patch("src.cli.fetch_symbol_directory", return_value=mock_us_symbols):
        with patch("src.ingestion.data_ingestor.DataIngestor.download_spy", return_value=10):
            with patch("src.ingestion.data_ingestor.DataIngestor.fetch_ticker_chunk", return_value=pd.DataFrame()):
                res = runner.invoke(main, ["seed", "--db-path", str(db_file), "--exchange", "US"])
                assert res.exit_code == 0
                assert "exchange universe: US" in res.output
                assert "US common stock symbols" in res.output
                assert "Seed Complete" in res.output


def test_cli_seed_exchange_all(tmp_path: Path):
    """Test CLI seed command with --exchange ALL."""
    from src.cli import main
    db_file = tmp_path / "cli_all_seed.duckdb"
    runner = CliRunner()

    mock_us_symbols = [{"ticker": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ", "asset_class": "Common Stock", "is_active": True}]
    with patch("src.cli.fetch_symbol_directory", return_value=mock_us_symbols):
        with patch("src.ingestion.data_ingestor.DataIngestor.download_spy", return_value=10):
            with patch("src.ingestion.data_ingestor.DataIngestor.download_tase_benchmark", return_value=10):
                with patch("src.ingestion.data_ingestor.DataIngestor.fetch_ticker_chunk", return_value=pd.DataFrame()):
                    res = runner.invoke(main, ["seed", "--db-path", str(db_file), "--exchange", "ALL"])
                    assert res.exit_code == 0
                    assert "US common stock symbols" in res.output
                    assert "TASE constituent symbols" in res.output


def test_cli_update_exchange_tase(tmp_path: Path):
    """Test CLI update command with --exchange TASE."""
    from src.cli import main
    db_file = tmp_path / "cli_tase_update.duckdb"
    runner = CliRunner()

    with patch("src.ingestion.data_ingestor.DataIngestor.sync_universe", return_value={"total_tickers": 120, "synced_tickers": 0, "total_bars_inserted": 0, "status": "up_to_date"}):
        res = runner.invoke(main, ["update", "--db-path", str(db_file), "--exchange", "TASE"])
        assert res.exit_code == 0
        assert "exchange: TASE" in res.output
        assert "Update Complete" in res.output


def test_cli_invalid_exchange_option(tmp_path: Path):
    """Test CLI fails fast on invalid --exchange argument."""
    from src.cli import main
    db_file = tmp_path / "cli_invalid.duckdb"
    runner = CliRunner()
    res = runner.invoke(main, ["seed", "--db-path", str(db_file), "--exchange", "INVALID_EXCHANGE"])
    assert res.exit_code != 0
    assert "Invalid value for '--exchange'" in res.output or "invalid choice" in res.output.lower()
```

---

## 6. Verification and Integration Plan

### 6.1 Inter-Module Contract Verification
1. **`src/ingestion/tase_directory.py` ↔ `src/cli.py`**:
   - `get_tase_symbol_directory()` must return `list[dict[str, Any]]` compatible with `sync_symbol_metadata()`.
2. **`src/ingestion/data_ingestor.py` ↔ `src/cli.py`**:
   - `DataIngestor.sync_universe(symbols=None, exchange="ALL")` must accept `exchange` parameter (`"US"`, `"TASE"`, or `"ALL"`).
3. **Database Schema Compliance**:
   - `symbol_metadata.exchange` accepts `'TASE'` without any schema migration needed.
   - `symbol_metadata` benchmark entry for `^TA125.TA` must set `exchange = 'TASE'` and `asset_class = 'Index'`.

### 6.2 Test Execution Command
To run the full suite:
```powershell
python -m pytest -v
```
All unit tests in `src/db/`, `src/engine/`, `src/ingestion/`, and `src/test_cli_ui.py` must pass with 100% success rate.
