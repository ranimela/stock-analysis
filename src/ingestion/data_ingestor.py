"""Data ingestor module.

Fetches daily OHLCV bars using yfinance with batch chunking, hard-gated SPY benchmark validation,
delta sync based on existing DuckDB trade dates, and thread-safe database insertion.
"""

from __future__ import annotations

import datetime
import logging
import time
from typing import Any, Sequence

import pandas as pd
import yfinance as yf

from src.db.db_manager import DatabaseManager
from src.ingestion.symbol_directory import fetch_symbol_directory, sync_symbol_metadata

logger = logging.getLogger(__name__)


class DataIngestor:
    """Ingests market daily bars for common stocks into DuckDB."""

    def __init__(
        self,
        db_manager: DatabaseManager | None = None,
        chunk_size: int = 100,
        delay_seconds: float = 1.0,
        lookback_years: int = 2,
    ) -> None:
        """Initialize DataIngestor.

        Args:
            db_manager: DatabaseManager instance. If None, initializes a default instance.
            chunk_size: Number of tickers per batch request. Defaults to 100.
            delay_seconds: Sleep delay between batch requests in seconds. Defaults to 1.0.
            lookback_years: Historical lookback in years for new tickers. Defaults to 2.
        """
        self.db_manager = db_manager if db_manager is not None else DatabaseManager()
        self.chunk_size = chunk_size
        self.delay_seconds = delay_seconds
        self.lookback_years = lookback_years

    def get_existing_max_dates(self) -> dict[str, datetime.date]:
        """Fetch the maximum trade_date for all tickers currently stored in DuckDB.

        Returns:
            dict[str, datetime.date]: Mapping of uppercase ticker to latest trade date.
        """
        rows = self.db_manager.execute_read(
            "SELECT ticker, MAX(trade_date) FROM daily_bars GROUP BY ticker"
        )
        max_dates: dict[str, datetime.date] = {}
        for ticker, max_date in rows:
            if ticker and max_date:
                if isinstance(max_date, str):
                    max_date = datetime.date.fromisoformat(max_date)
                elif isinstance(max_date, datetime.datetime):
                    max_date = max_date.date()
                max_dates[ticker.upper()] = max_date
        return max_dates

    def download_spy(self, start_date: str | datetime.date | None = None) -> int:
        """Download SPY benchmark data FIRST as a hard-gating step.

        If SPY download fails or returns empty data, aborts synchronization.

        Args:
            start_date: Start date for benchmark download. If None, uses lookback_years.

        Returns:
            int: Number of SPY daily bars stored in DuckDB.

        Raises:
            RuntimeError: If SPY benchmark download fails or returns no data.
        """
        logger.info("Hard-gating check: Downloading SPY benchmark data...")
        if start_date is None:
            calc_start = datetime.date.today() - datetime.timedelta(days=365 * self.lookback_years)
        elif isinstance(start_date, str):
            calc_start = datetime.date.fromisoformat(start_date)
        else:
            calc_start = start_date

        try:
            df = yf.download("SPY", start=calc_start.isoformat(), progress=False, auto_adjust=False)
        except Exception as e:
            logger.error("Failed to download SPY benchmark data: %s", e)
            raise RuntimeError(f"SPY benchmark download failed. Aborting sync: {e}") from e

        if df is None or df.empty:
            logger.error("SPY benchmark returned empty dataset.")
            raise RuntimeError("SPY benchmark download failed (empty response). Aborting sync.")

        bars_inserted = self.parse_and_store_bars(df, ["SPY"])
        if bars_inserted == 0:
            # Check if SPY is already up-to-date in DB
            max_dates = self.get_existing_max_dates()
            if "SPY" not in max_dates:
                raise RuntimeError("SPY benchmark download failed (0 bars stored for new benchmark). Aborting sync.")

        logger.info("Hard-gating passed: SPY benchmark sync complete (%d bars stored/verified).", bars_inserted)
        return bars_inserted

    def fetch_ticker_chunk(
        self,
        tickers: Sequence[str],
        start_date: datetime.date | str,
        end_date: datetime.date | str | None = None,
    ) -> pd.DataFrame:
        """Fetch daily bars for a chunk of tickers using yfinance.

        Args:
            tickers: Sequence of ticker symbols.
            start_date: Start date.
            end_date: Optional end date.

        Returns:
            pd.DataFrame: Downloaded market data.
        """
        start_str = start_date.isoformat() if isinstance(start_date, datetime.date) else start_date
        end_str = end_date.isoformat() if isinstance(end_date, datetime.date) else end_date

        ticker_list = [t.strip().upper() for t in tickers if t.strip()]
        if not ticker_list:
            return pd.DataFrame()

        try:
            kwargs: dict[str, Any] = {
                "tickers": ticker_list,
                "start": start_str,
                "progress": False,
                "auto_adjust": False,
            }
            if end_str:
                kwargs["end"] = end_str

            df = yf.download(**kwargs)
            return df if df is not None else pd.DataFrame()
        except Exception as e:
            logger.warning("Error fetching chunk %s: %s", ticker_list[:5], e)
            return pd.DataFrame()

    def parse_and_store_bars(
        self,
        df: pd.DataFrame,
        tickers: Sequence[str],
        max_dates: dict[str, datetime.date] | None = None,
    ) -> int:
        """Parse yfinance DataFrame and store valid bars into DuckDB daily_bars.

        Args:
            df: Raw yfinance DataFrame output.
            tickers: Sequence of ticker symbols expected in the DataFrame.
            max_dates: Optional dictionary mapping ticker to latest stored date for delta sync filtering.

        Returns:
            int: Total number of bars inserted into DuckDB.
        """
        if df.empty:
            return 0

        if max_dates is None:
            max_dates = {}

        records: list[tuple[str, datetime.date, float, float, float, float, float, int]] = []
        is_multi = isinstance(df.columns, pd.MultiIndex)

        for ticker in tickers:
            ticker_upper = ticker.strip().upper()
            ticker_max_date = max_dates.get(ticker_upper)

            try:
                if is_multi:
                    if ticker_upper in df.columns.get_level_values(1):
                        sub_df = df.xs(ticker_upper, axis=1, level=1)
                    elif ticker_upper in df.columns.get_level_values(0):
                        sub_df = df.xs(ticker_upper, axis=1, level=0)
                    else:
                        continue
                else:
                    sub_df = df.copy()

                if "Close" not in sub_df.columns:
                    continue

                sub_df = sub_df.dropna(subset=["Close"])

                for idx, row in sub_df.iterrows():
                    trade_date = idx.date() if isinstance(idx, (pd.Timestamp, datetime.datetime)) else idx
                    if not isinstance(trade_date, datetime.date):
                        continue

                    # Delta sync check per ticker
                    if ticker_max_date is not None and trade_date <= ticker_max_date:
                        continue

                    try:
                        close_p = float(row["Close"])
                        if pd.isna(close_p):
                            continue

                        open_p = float(row["Open"]) if "Open" in row and not pd.isna(row["Open"]) else close_p
                        high_p = float(row["High"]) if "High" in row and not pd.isna(row["High"]) else close_p
                        low_p = float(row["Low"]) if "Low" in row and not pd.isna(row["Low"]) else close_p

                        adj_col = "Adj Close" if "Adj Close" in row else ("AdjClose" if "AdjClose" in row else None)
                        adj_close_p = float(row[adj_col]) if adj_col and not pd.isna(row[adj_col]) else close_p

                        vol = int(row["Volume"]) if "Volume" in row and not pd.isna(row["Volume"]) else 0

                        records.append((
                            ticker_upper,
                            trade_date,
                            open_p,
                            high_p,
                            low_p,
                            close_p,
                            adj_close_p,
                            vol,
                        ))
                    except (ValueError, TypeError):
                        continue

            except Exception as e:
                logger.warning("Error parsing rows for %s: %s", ticker_upper, e)

        if not records:
            return 0

        with self.db_manager.write_cursor() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO daily_bars
                (ticker, trade_date, open, high, low, close, adj_close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                records,
            )

        return len(records)

    def sync_universe(
        self,
        symbols: Sequence[str] | Sequence[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Synchronize historical daily bar data for all target equities.

        Workflow:
        1. Hard-gate SPY benchmark download.
        2. Resolve ticker universe (downloads FTP list if symbols is None).
        3. Determine existing max dates for delta sync.
        4. Chunk ticker universe and fetch missing date ranges with rate-limiting delays.
        5. Store fetched bars in DuckDB daily_bars.

        Args:
            symbols: Optional list of ticker strings or symbol metadata dictionaries.

        Returns:
            dict[str, Any]: Sync results summary containing statistics.
        """
        # Step 1: Hard-gate SPY benchmark FIRST
        self.download_spy()

        # Step 2: Resolve symbol list
        symbol_dicts: list[dict[str, Any]] = []
        ticker_list: list[str] = []

        if symbols is None:
            symbol_dicts = fetch_symbol_directory()
            sync_symbol_metadata(self.db_manager, symbol_dicts)
            ticker_list = [s["ticker"] for s in symbol_dicts]
        elif symbols and isinstance(symbols[0], dict):
            symbol_dicts = list(symbols)  # type: ignore[arg-type]
            sync_symbol_metadata(self.db_manager, symbol_dicts)
            ticker_list = [s["ticker"] for s in symbol_dicts]
        else:
            ticker_list = [str(s).upper() for s in symbols]

        # Deduplicate
        ticker_list = list(dict.fromkeys(ticker_list))
        if "SPY" in ticker_list:
            ticker_list.remove("SPY")

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
        logger.info("Found %d tickers requiring data sync.", total_tickers)

        if total_tickers == 0:
            return {
                "total_tickers": len(ticker_list),
                "synced_tickers": 0,
                "total_bars_inserted": 0,
                "status": "up_to_date",
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
        }
        logger.info("Sync complete summary: %s", summary)
        return summary

    def sync_single_ticker(self, ticker: str) -> bool:
        """Fetch and store 2 years of daily bar data for a single ticker on-demand.

        Args:
            ticker: Ticker symbol string.

        Returns:
            bool: True if data was successfully downloaded and stored, False otherwise.
        """
        ticker_clean = ticker.strip().upper()
        today = datetime.date.today()
        start_date = today - datetime.timedelta(days=365 * self.lookback_years)

        # Fetch market cap & metadata via yfinance Ticker info
        market_cap = None
        comp_name = ticker_clean
        try:
            info = yf.Ticker(ticker_clean).info
            market_cap = info.get("marketCap")
            comp_name = info.get("shortName") or info.get("longName") or ticker_clean
        except Exception:
            pass

        # Register metadata entry if missing
        self.db_manager.execute_write(
            """
            INSERT INTO symbol_metadata (ticker, name, exchange, asset_class, market_cap, is_active, first_added_date, last_updated_date)
            VALUES (?, ?, 'NASDAQ', 'Common Stock', ?, true, CURRENT_DATE, CURRENT_DATE)
            ON CONFLICT (ticker) DO UPDATE SET
                market_cap = COALESCE(EXCLUDED.market_cap, symbol_metadata.market_cap),
                name = COALESCE(EXCLUDED.name, symbol_metadata.name);
            """,
            [ticker_clean, comp_name, market_cap],
        )

        df = self.fetch_ticker_chunk([ticker_clean], start_date=start_date)
        if df.empty:
            return False

        bars_count = self.parse_and_store_bars(df, [ticker_clean])
        return bars_count > 0
