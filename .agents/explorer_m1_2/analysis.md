# Milestone 1: Data Ingestion & Benchmark Gating Investigation Report
**Module Focus:** `src/ingestion/data_ingestor.py`  
**Specialist:** Explorer M1_2 (Data Ingestor & Benchmark Gating Specialist)  
**Date:** 2026-08-27  
**Project:** Tel Aviv Stock Exchange (TA-125) Integration  

---

## 1. Executive Summary

This report delivers the comprehensive architectural analysis and exact implementation specification for upgrading `src/ingestion/data_ingestor.py` to support the **Tel Aviv Stock Exchange (TASE / TA-125)** market data pipeline.

### Core Objectives Delivered:
1. **Benchmark Ingestion & Hard-Gating:** Formulated hard-gating logic for the TA-125 benchmark index (`^TA125.TA`). If `^TA125.TA` download fails or returns empty data during TASE synchronization, `DataIngestor` raises an explicit `RuntimeError` and aborts ingestion immediately.
2. **Multi-Exchange Universe Seeding & Bar Synchronization:** Parameterized `sync_universe()`, `seed_universe()`, and `sync_daily_bars()` with `exchange="ALL" | "US" | "TASE"`, enabling selective or unified ingestion of US equities, TASE equities, or both.
3. **Single Ticker Exchange Inference:** Fixed `sync_single_ticker()` so that tickers ending in `.TA` are stored with `exchange = 'TASE'` and asset class `'Common Stock'` (or `'Index'` for `^TA125.TA`), eliminating the legacy hardcoded `'NASDAQ'` default.
4. **DuckDB Schema Integrity & Zero US Regressions:** Validated that all additions strictly adhere to the existing `symbol_metadata` and `daily_bars` schemas without requiring schema alterations or breaking backward compatibility with existing US ingestion flows.

---

## 2. Analysis of Existing `DataIngestor` Architecture

### 2.1 Component Flow & Method Inventory

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                   DataIngestor Flow                                    │
└────────────────────────────────────────────────────────────────────────────────────────┘
                                           │
                                ┌──────────┴──────────┐
                                │                     │
                        [ US Pipeline ]       [ TASE Pipeline (NEW) ]
                                │                     │
                        download_spy()        download_ta125_benchmark()
                         (Hard-Gated)               (Hard-Gated)
                                │                     │
                                └──────────┬──────────┘
                                           │
                                  sync_universe()
                       (exchange = "ALL" | "US" | "TASE")
                                           │
                     ┌─────────────────────┴─────────────────────┐
                     ▼                                           ▼
             [ US Symbols ]                              [ TASE Symbols ]
          fetch_symbol_directory()                    fetch_tase_symbols()
                     │                                           │
                     └─────────────────────┬─────────────────────┘
                                           ▼
                               sync_symbol_metadata()
                                           ▼
                               get_existing_max_dates()
                                           ▼
                                fetch_ticker_chunk()
                                  (chunk_size=100)
                                           ▼
                               parse_and_store_bars()
                                           ▼
                            INSERT INTO daily_bars (DuckDB)
```

### 2.2 Detailed Method Inspection

| Method | Current Implementation | Observed Limitations / TASE Requirements |
|:---|:---|:---|
| `__init__` (lines 26–45) | Initializes `db_manager`, `chunk_size=100`, `delay_seconds=0.1`, `lookback_years=2`. | Clean and extensible. No changes needed. |
| `get_existing_max_dates` (lines 46–63) | Executes `SELECT ticker, MAX(trade_date) FROM daily_bars GROUP BY ticker`. Returns mapping `{ticker: max_date}`. | Fully ticker-agnostic. Correctly tracks `.TA` and benchmark tickers. |
| `download_spy` (lines 65–105) | Downloads `SPY` bars via `yf.download("SPY", ...)`. Hard-gates by raising `RuntimeError` if empty. Inserts into `daily_bars`. | Exclusively handles `SPY`. Need generalized `download_benchmark()` and dedicated `download_ta125_benchmark()`. Must also register benchmark metadata in `symbol_metadata`. |
| `fetch_ticker_chunk` (lines 107–145) | Fetches chunk of tickers via `yf.download(tickers=..., start=..., end=...)`. | Fully supports `.TA` tickers and chunked batch requests. |
| `parse_and_store_bars` (lines 146–281) | Handles MultiIndex and single-level DataFrames. Drops rows where `trade_date <= max_date`. Inserts into `daily_bars`. Optional `update_metadata` fetches `fast_info`. | Compatible with TASE OHLCV bars. Agorot pricing and share volume parse cleanly into `DOUBLE` and `HUGEINT`. |
| `sync_universe` (lines 283–393) | Calls `self.download_spy()`. If `symbols is None`, calls `fetch_symbol_directory()` (US only). Calculates delta start dates per ticker, chunks, and inserts. | Hardcoded to US: always calls `download_spy()`, only fetches US directory when `symbols is None`. Must accept `exchange: str = "ALL"` parameter. |
| `sync_single_ticker` (lines 394–442) | Fetches `fast_info` / `info` for single ticker, inserts into `symbol_metadata` with hardcoded `exchange = 'NASDAQ'` (line 428), then downloads bars. | **Critical Defect:** TASE tickers (`.TA`) are misclassified as `exchange = 'NASDAQ'`. Must auto-infer `exchange = 'TASE'` for `.TA` tickers and handle index asset classes. |
| `export_daily_delta_parquet` / `sync_local_db_from_parquet` (lines 443–553) | Exports latest trade date to Parquet and merges incoming Parquet files. | Schema-agnostic and fully compatible. |

---

## 3. TASE Ingestion Specifications

### 3.1 TA-125 Benchmark Downloader & Hard-Gating
* **Benchmark Symbol:** `^TA125.TA`
* **Benchmark Metadata:**
  - `name = "TA-125 Index"`
  - `exchange = "TASE"`
  - `asset_class = "Index"`
  - `is_active = True`
* **Hard-Gating Rule:**
  - Attempt download via `yf.download("^TA125.TA", start=calc_start.isoformat(), progress=False, auto_adjust=False)`.
  - If `df is None` or `df.empty`: Raise `RuntimeError("TA-125 (^TA125.TA) benchmark download failed (empty response). Aborting sync.")`.
  - If network or API exception occurs: Raise `RuntimeError(f"TA-125 (^TA125.TA) benchmark download failed. Aborting sync: {err}") from err`.
  - If `bars_inserted == 0` and `^TA125.TA` is not present in `daily_bars`: Raise `RuntimeError("TA-125 (^TA125.TA) benchmark download failed (0 bars stored for new benchmark). Aborting sync.")`.

### 3.2 Multi-Exchange Parameterization
The `sync_universe` method (as well as convenience wrappers `seed_universe` and `sync_daily_bars`) must support:
- `exchange = "ALL"` (default):
  1. Downloads and hard-gates `SPY` benchmark.
  2. Downloads and hard-gates `^TA125.TA` benchmark.
  3. If `symbols` is None: Discovers US symbols via `fetch_symbol_directory()` AND TASE symbols via `fetch_tase_symbols()`. Synchronizes metadata for both sets.
  4. Merges, deduplicates, and synchronizes daily bars for all constituent equities.
- `exchange = "US"`:
  1. Downloads and hard-gates `SPY` benchmark.
  2. If `symbols` is None: Discovers US symbols via `fetch_symbol_directory()`.
  3. Synchronizes daily bars for US equities only.
- `exchange = "TASE"`:
  1. Downloads and hard-gates `^TA125.TA` benchmark.
  2. If `symbols` is None: Discovers TASE symbols via `fetch_tase_symbols()`.
  3. Synchronizes daily bars for TASE equities only.

### 3.3 Exchange Inference for Single Tickers
In `sync_single_ticker(self, ticker: str)`:
```python
ticker_clean = ticker.strip().upper()
is_tase = ticker_clean.endswith(".TA")
exchange = "TASE" if is_tase else "NASDAQ"
asset_class = "Index" if ticker_clean in {"^TA125.TA", "SPY", "^GSPC", "^IXIC"} else "Common Stock"
```
The SQL query must dynamically pass `exchange` and `asset_class`:
```sql
INSERT INTO symbol_metadata (ticker, name, exchange, asset_class, market_cap, is_active, first_added_date, last_updated_date)
VALUES (?, ?, ?, ?, ?, true, CURRENT_DATE(), CURRENT_DATE())
ON CONFLICT (ticker) DO UPDATE SET
    market_cap = COALESCE(EXCLUDED.market_cap, symbol_metadata.market_cap),
    name = COALESCE(EXCLUDED.name, symbol_metadata.name),
    exchange = COALESCE(EXCLUDED.exchange, symbol_metadata.exchange),
    asset_class = COALESCE(EXCLUDED.asset_class, symbol_metadata.asset_class),
    last_updated_date = CURRENT_DATE();
```

---

## 4. Exact Implementation Specification for `src/ingestion/data_ingestor.py`

### 4.1 Imports and Constants
At top of `src/ingestion/data_ingestor.py`:
```python
from __future__ import annotations

import datetime
import logging
import time
from typing import Any, Sequence

import pandas as pd
import yfinance as yf

from src.db.db_manager import DatabaseManager
from src.ingestion.symbol_directory import fetch_symbol_directory, sync_symbol_metadata
from src.ingestion.tase_directory import fetch_tase_symbols

logger = logging.getLogger(__name__)

US_BENCHMARK_TICKER = "SPY"
TASE_BENCHMARK_TICKER = "^TA125.TA"
```

### 4.2 Benchmark Downloader Methods

```python
    def download_benchmark(
        self,
        ticker: str,
        start_date: str | datetime.date | None = None,
        name: str | None = None,
        exchange: str = "US",
    ) -> int:
        """Download benchmark index/ETF data FIRST as a hard-gating step.

        If benchmark download fails or returns empty data, aborts synchronization.

        Args:
            ticker: Benchmark ticker symbol (e.g. 'SPY' or '^TA125.TA').
            start_date: Start date for benchmark download. If None, uses lookback_years.
            name: Official index/ETF name.
            exchange: Exchange code ('US', 'NYSE', 'TASE').

        Returns:
            int: Number of benchmark daily bars stored in DuckDB.

        Raises:
            RuntimeError: If benchmark download fails or returns no data.
        """
        bench_clean = ticker.strip().upper()
        logger.info("Hard-gating check: Downloading benchmark %s...", bench_clean)

        if start_date is None:
            calc_start = datetime.date.today() - datetime.timedelta(days=365 * self.lookback_years)
        elif isinstance(start_date, str):
            calc_start = datetime.date.fromisoformat(start_date)
        else:
            calc_start = start_date

        bench_name = name or ("SPDR S&P 500 ETF Trust" if bench_clean == "SPY" else ("TA-125 Index" if bench_clean == "^TA125.TA" else bench_clean))
        bench_exchange = "TASE" if bench_clean.endswith(".TA") else ("NYSE" if bench_clean == "SPY" else exchange)
        bench_asset_class = "ETF" if bench_clean == "SPY" else "Index"

        # Register/update symbol metadata for benchmark
        try:
            self.db_manager.execute_write(
                """
                INSERT INTO symbol_metadata (ticker, name, exchange, asset_class, market_cap, is_active, first_added_date, last_updated_date)
                VALUES (?, ?, ?, ?, NULL, true, CURRENT_DATE(), CURRENT_DATE())
                ON CONFLICT (ticker) DO UPDATE SET
                    name = COALESCE(EXCLUDED.name, symbol_metadata.name),
                    exchange = COALESCE(EXCLUDED.exchange, symbol_metadata.exchange),
                    asset_class = COALESCE(EXCLUDED.asset_class, symbol_metadata.asset_class),
                    is_active = true,
                    last_updated_date = CURRENT_DATE();
                """,
                [bench_clean, bench_name, bench_exchange, bench_asset_class],
            )
        except Exception as e:
            logger.warning("Could not register metadata for benchmark %s: %s", bench_clean, e)

        try:
            df = yf.download(bench_clean, start=calc_start.isoformat(), progress=False, auto_adjust=False)
        except Exception as e:
            logger.error("Failed to download %s benchmark data: %s", bench_clean, e)
            raise RuntimeError(f"{bench_clean} benchmark download failed. Aborting sync: {e}") from e

        if df is None or df.empty:
            logger.error("%s benchmark returned empty dataset.", bench_clean)
            raise RuntimeError(f"{bench_clean} benchmark download failed (empty response). Aborting sync.")

        bars_inserted = self.parse_and_store_bars(df, [bench_clean])
        if bars_inserted == 0:
            # Check if benchmark is already up-to-date in DB
            max_dates = self.get_existing_max_dates()
            if bench_clean not in max_dates:
                raise RuntimeError(f"{bench_clean} benchmark download failed (0 bars stored for new benchmark). Aborting sync.")

        logger.info("Hard-gating passed: %s benchmark sync complete (%d bars stored/verified).", bench_clean, bars_inserted)
        return bars_inserted

    def download_spy(self, start_date: str | datetime.date | None = None) -> int:
        """Download SPY benchmark data FIRST as a hard-gating step for US equities.

        Args:
            start_date: Start date for benchmark download. If None, uses lookback_years.

        Returns:
            int: Number of SPY daily bars stored in DuckDB.

        Raises:
            RuntimeError: If SPY benchmark download fails or returns no data.
        """
        return self.download_benchmark("SPY", start_date=start_date, name="SPDR S&P 500 ETF Trust", exchange="NYSE")

    def download_ta125_benchmark(self, start_date: str | datetime.date | None = None) -> int:
        """Download TA-125 benchmark data FIRST as a hard-gating step for TASE equities.

        Args:
            start_date: Start date for benchmark download. If None, uses lookback_years.

        Returns:
            int: Number of TA-125 daily bars stored in DuckDB.

        Raises:
            RuntimeError: If TA-125 benchmark download fails or returns no data.
        """
        return self.download_benchmark("^TA125.TA", start_date=start_date, name="TA-125 Index", exchange="TASE")
```

### 4.3 `sync_universe`, `seed_universe`, and `sync_daily_bars` Implementations

```python
    def sync_universe(
        self,
        symbols: Sequence[str] | Sequence[dict[str, Any]] | None = None,
        exchange: str = "ALL",
    ) -> dict[str, Any]:
        """Synchronize historical daily bar data for target equities.

        Workflow:
        1. Hard-gate benchmark downloads based on target exchange:
           - "ALL": Downloads both SPY and ^TA125.TA.
           - "US": Downloads SPY only.
           - "TASE": Downloads ^TA125.TA only.
        2. Resolve ticker universe (US via FTP/HTTP, TASE via curated constituent directory).
        3. Determine existing max dates for delta sync.
        4. Chunk ticker universe and fetch missing date ranges with rate-limiting delays.
        5. Store fetched bars in DuckDB daily_bars.

        Args:
            symbols: Optional list of ticker strings or symbol metadata dictionaries.
            exchange: Target exchange filter: 'ALL', 'US', or 'TASE'. Defaults to 'ALL'.

        Returns:
            dict[str, Any]: Sync results summary containing statistics.
        """
        target_exchange = exchange.strip().upper()

        # Step 1: Hard-gate benchmarks
        if target_exchange in {"US", "ALL"}:
            self.download_spy()
        if target_exchange in {"TASE", "ALL"}:
            self.download_ta125_benchmark()

        # Step 2: Resolve symbol list
        symbol_dicts: list[dict[str, Any]] = []
        ticker_list: list[str] = []

        if symbols is None:
            if target_exchange in {"US", "ALL"}:
                try:
                    us_symbols = fetch_symbol_directory()
                    symbol_dicts.extend(us_symbols)
                except Exception as err:
                    logger.warning("Failed to fetch NASDAQ symbol directory (%s).", err)

            if target_exchange in {"TASE", "ALL"}:
                try:
                    tase_symbols = fetch_tase_symbols()
                    symbol_dicts.extend(tase_symbols)
                except Exception as err:
                    logger.warning("Failed to fetch TASE symbol directory (%s).", err)

            if symbol_dicts:
                sync_symbol_metadata(self.db_manager, symbol_dicts)
                ticker_list = [s["ticker"] for s in symbol_dicts]
            else:
                logger.warning("Falling back to existing database metadata tickers.")
                if target_exchange == "TASE":
                    db_symbols = self.db_manager.execute_read(
                        "SELECT DISTINCT ticker FROM symbol_metadata WHERE is_active = true AND exchange = 'TASE';"
                    )
                elif target_exchange == "US":
                    db_symbols = self.db_manager.execute_read(
                        "SELECT DISTINCT ticker FROM symbol_metadata WHERE is_active = true AND (exchange != 'TASE' OR exchange IS NULL);"
                    )
                else:
                    db_symbols = self.db_manager.execute_read(
                        "SELECT DISTINCT ticker FROM symbol_metadata WHERE is_active = true;"
                    )

                if not db_symbols:
                    db_symbols = self.db_manager.execute_read("SELECT DISTINCT ticker FROM daily_bars;")
                ticker_list = [str(r[0]).upper() for r in db_symbols]

        elif symbols and isinstance(symbols[0], dict):
            symbol_dicts = list(symbols)  # type: ignore[arg-type]
            sync_symbol_metadata(self.db_manager, symbol_dicts)
            ticker_list = [s["ticker"] for s in symbol_dicts]
        else:
            ticker_list = [str(s).upper() for s in symbols]

        # Deduplicate and remove benchmark tickers (they are already synced)
        ticker_list = list(dict.fromkeys(ticker_list))
        for bench in ["SPY", "^TA125.TA"]:
            if bench in ticker_list:
                ticker_list.remove(bench)

        today = datetime.date.today()
        default_start = today - datetime.timedelta(days=365 * self.lookback_years)

        # Step 3: Query max dates in DB
        max_dates = self.get_existing_max_dates()

        # Determine tickers needing update and their required start dates
        ticker_start_dates: dict[str, datetime.date] = {}
        for ticker in ticker_list:
            if ticker in max_dates:
                last_date = max_dates[ticker]
                needed_start = last_date + datetime.timedelta(days=1)
                if needed_start < today:
                    ticker_start_dates[ticker] = needed_start
            else:
                ticker_start_dates[ticker] = default_start

        tickers_to_sync = list(ticker_start_dates.keys())
        total_tickers = len(tickers_to_sync)
        logger.info("Found %d tickers requiring data sync (exchange=%s).", total_tickers, target_exchange)

        if total_tickers == 0:
            logger.info("Universe is up-to-date. No bars to fetch.")
            return {
                "total_tickers": len(ticker_list),
                "synced_tickers": 0,
                "total_bars_inserted": 0,
                "status": "up_to_date",
                "exchange": target_exchange,
            }

        total_bars_inserted = 0
        chunks = [
            tickers_to_sync[i : i + self.chunk_size]
            for i in range(0, total_tickers, self.chunk_size)
        ]

        for i, chunk in enumerate(chunks, 1):
            chunk_min_start = min(ticker_start_dates[t] for t in chunk)
            logger.info(
                "Syncing chunk %d/%d (%d tickers, start=%s)...",
                i,
                len(chunks),
                len(chunk),
                chunk_min_start,
            )

            df = self.fetch_ticker_chunk(chunk, start_date=chunk_min_start)
            bars_count = self.parse_and_store_bars(df, chunk, max_dates=max_dates)
            total_bars_inserted += bars_count

            if i < len(chunks) and self.delay_seconds > 0:
                time.sleep(self.delay_seconds)

        summary = {
            "total_tickers": len(ticker_list),
            "synced_tickers": total_tickers,
            "total_bars_inserted": total_bars_inserted,
            "status": "success",
            "exchange": target_exchange,
        }
        logger.info("Sync complete summary: %s", summary)
        return summary

    def seed_universe(
        self,
        exchange: str = "ALL",
        symbols: Sequence[str] | Sequence[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Seed universe metadata and historical daily bars. Alias/convenience method for sync_universe."""
        return self.sync_universe(symbols=symbols, exchange=exchange)

    def sync_daily_bars(
        self,
        exchange: str = "ALL",
        symbols: Sequence[str] | Sequence[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Synchronize daily bars for universe equities. Alias/convenience method for sync_universe."""
        return self.sync_universe(symbols=symbols, exchange=exchange)
```

### 4.4 `sync_single_ticker` Implementation

```python
    def sync_single_ticker(self, ticker: str) -> bool:
        """Fetch and store 2 years of daily bar data for a single ticker on-demand.

        Correctly tags '.TA' tickers with exchange = 'TASE'.

        Args:
            ticker: Ticker symbol string.

        Returns:
            bool: True if data was successfully downloaded and stored, False otherwise.
        """
        ticker_clean = ticker.strip().upper()
        today = datetime.date.today()
        start_date = today - datetime.timedelta(days=365 * self.lookback_years)

        # Infer exchange and asset class
        is_tase = ticker_clean.endswith(".TA")
        exchange = "TASE" if is_tase else "NASDAQ"
        asset_class = "Index" if ticker_clean in {"^TA125.TA", "SPY", "^GSPC", "^IXIC"} else "Common Stock"

        # Fetch market cap & metadata via yfinance Ticker info
        market_cap = None
        comp_name = ticker_clean
        try:
            t = yf.Ticker(ticker_clean)
            fi = t.fast_info
            market_cap = getattr(fi, "market_cap", None)
            comp_name = getattr(fi, "long_name", None) or getattr(fi, "short_name", None)
            if market_cap is None or pd.isna(market_cap) or not comp_name:
                info = t.info
                if market_cap is None or pd.isna(market_cap):
                    market_cap = info.get("marketCap")
                if not comp_name:
                    comp_name = info.get("shortName") or info.get("longName") or ticker_clean
        except Exception:
            pass

        # Register metadata entry with inferred exchange and asset class
        self.db_manager.execute_write(
            """
            INSERT INTO symbol_metadata (ticker, name, exchange, asset_class, market_cap, is_active, first_added_date, last_updated_date)
            VALUES (?, ?, ?, ?, ?, true, CURRENT_DATE(), CURRENT_DATE())
            ON CONFLICT (ticker) DO UPDATE SET
                market_cap = COALESCE(EXCLUDED.market_cap, symbol_metadata.market_cap),
                name = COALESCE(EXCLUDED.name, symbol_metadata.name),
                exchange = COALESCE(EXCLUDED.exchange, symbol_metadata.exchange),
                asset_class = COALESCE(EXCLUDED.asset_class, symbol_metadata.asset_class),
                last_updated_date = CURRENT_DATE();
            """,
            [ticker_clean, comp_name, exchange, asset_class, market_cap],
        )

        df = self.fetch_ticker_chunk([ticker_clean], start_date=start_date)
        if df.empty:
            return False

        bars_count = self.parse_and_store_bars(df, [ticker_clean])
        return bars_count > 0
```

---

## 5. Cross-Module Interactions & Schema Contracts

### 5.1 Ingestion $\leftrightarrow$ Screener Engine Contract
- **DuckDB `symbol_metadata`**:
  - TASE constituents have `exchange = 'TASE'` and `asset_class = 'Common Stock'`.
  - Benchmark index `^TA125.TA` has `exchange = 'TASE'` and `asset_class = 'Index'`.
  - US equities have `exchange IN ('NASDAQ', 'NYSE', 'AMEX', 'ARCA', 'BATS')`.
  - Benchmark ETF `SPY` has `exchange = 'NYSE'` and `asset_class = 'ETF'`.
- **DuckDB `daily_bars`**:
  - `(ticker, trade_date)` composite primary key.
  - TASE Sunday–Thursday dates and US Monday–Friday dates coexist in the same table without collisions.
  - Price values in Agorot for TASE and USD for US store as standard `DOUBLE` precision.

### 5.2 CLI Integration
- `src/cli.py` can invoke:
  ```python
  ingestor.sync_universe(exchange=exchange)
  ```
  where `exchange` is passed from click option `--exchange` (`US`, `TASE`, `ALL`).

---

## 6. Unit Test Blueprint

The following unit tests should be added to `src/ingestion/test_ingestion.py`:

```python
def test_download_ta125_benchmark_success(tmp_db: DatabaseManager):
    """Test successful download and metadata registration for TA-125 benchmark."""
    ingestor = DataIngestor(db_manager=tmp_db)
    dates = pd.date_range("2026-08-01", periods=3)
    df_mock = pd.DataFrame({
        "Close": [2000.0, 2010.0, 2020.0],
        "Open": [1990.0, 2000.0, 2010.0],
        "High": [2010.0, 2020.0, 2030.0],
        "Low": [1985.0, 1995.0, 2005.0],
        "Volume": [5000000, 6000000, 5500000],
    }, index=dates)

    with patch("yfinance.download", return_value=df_mock):
        bars_count = ingestor.download_ta125_benchmark()
        assert bars_count == 3

    meta = tmp_db.execute_read("SELECT ticker, name, exchange, asset_class FROM symbol_metadata WHERE ticker = '^TA125.TA'")
    assert len(meta) == 1
    assert meta[0] == ("^TA125.TA", "TA-125 Index", "TASE", "Index")


def test_download_ta125_benchmark_hard_gate_failure(tmp_db: DatabaseManager):
    """Test that download_ta125_benchmark raises RuntimeError when yfinance returns empty data."""
    ingestor = DataIngestor(db_manager=tmp_db)
    with patch("yfinance.download", return_value=pd.DataFrame()):
        with pytest.raises(RuntimeError, match=r"\^TA125\.TA benchmark download failed"):
            ingestor.download_ta125_benchmark()


def test_sync_single_ticker_tase(tmp_db: DatabaseManager):
    """Test syncing a single .TA ticker sets exchange = 'TASE' in symbol_metadata."""
    ingestor = DataIngestor(db_manager=tmp_db)
    dates = pd.date_range("2026-08-01", periods=2)
    df_mock = pd.DataFrame({
        "Close": [7500.0, 7600.0],
        "Open": [7400.0, 7500.0],
        "High": [7550.0, 7650.0],
        "Low": [7350.0, 7450.0],
        "Volume": [100000, 120000],
    }, index=dates)

    with patch("yfinance.download", return_value=df_mock), \
         patch("yfinance.Ticker") as mock_ticker:
        mock_fast_info = MagicMock()
        mock_fast_info.market_cap = 50000000000
        mock_fast_info.long_name = "Bank Leumi"
        mock_ticker.return_value.fast_info = mock_fast_info

        success = ingestor.sync_single_ticker("LUMI.TA")
        assert success is True

    rows = tmp_db.execute_read("SELECT ticker, exchange, asset_class FROM symbol_metadata WHERE ticker = 'LUMI.TA'")
    assert len(rows) == 1
    assert rows[0] == ("LUMI.TA", "TASE", "Common Stock")
```
