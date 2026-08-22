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

        # Batch update Market Cap & Name for synced tickers via fast_info / Ticker info
        for ticker in tickers:
            ticker_clean = ticker.strip().upper()
            try:
                t = yf.Ticker(ticker_clean)
                fi = t.fast_info
                mc = getattr(fi, "market_cap", None)
                name = getattr(fi, "long_name", None) or getattr(fi, "short_name", None)
                if mc is None or pd.isna(mc) or not name:
                    inf = t.info
                    if mc is None or pd.isna(mc):
                        mc = inf.get("marketCap")
                    if not name:
                        name = inf.get("longName") or inf.get("shortName")

                if (mc and not pd.isna(mc)) or name:
                    with self.db_manager.write_cursor() as conn:
                        if mc and not pd.isna(mc) and name:
                            conn.execute(
                                "UPDATE symbol_metadata SET market_cap = ?, name = ? WHERE ticker = ?;",
                                [float(mc), str(name), ticker_clean],
                            )
                        elif mc and not pd.isna(mc):
                            conn.execute(
                                "UPDATE symbol_metadata SET market_cap = ? WHERE ticker = ?;",
                                [float(mc), ticker_clean],
                            )
                        elif name:
                            conn.execute(
                                "UPDATE symbol_metadata SET name = ? WHERE ticker = ?;",
                                [str(name), ticker_clean],
                            )
            except Exception:
                pass

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
            logger.info("Universe is up-to-date. No bars to fetch.")
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

        # Register metadata entry if missing
        self.db_manager.execute_write(
            """
            INSERT INTO symbol_metadata (ticker, name, exchange, asset_class, market_cap, is_active, first_added_date, last_updated_date)
            VALUES (?, ?, 'NASDAQ', 'Common Stock', ?, true, CURRENT_DATE(), CURRENT_DATE())
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

    def export_daily_delta_parquet(self, output_dir: str = "data/daily_deltas", retention_days: int = 7) -> str | None:
        """Export latest EOD daily bar delta into a single parquet file and prune old parquet files > retention_days.

        Args:
            output_dir: Target directory path for parquet files.
            retention_days: Number of days to retain parquet files on disk before cleanup. Defaults to 7.

        Returns:
            str | None: Absolute filepath of exported parquet file if successful, otherwise None.
        """
        import pathlib
        out_path = pathlib.Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        today_str = datetime.date.today().isoformat()
        target_file = out_path / f"{today_str}.parquet"

        # Fetch latest EOD bars from daily_bars table for latest trade date
        max_date_row = self.db_manager.execute_read("SELECT MAX(trade_date) FROM daily_bars;")
        if not max_date_row or not max_date_row[0][0]:
            logger.warning("No trade dates found in database. Cannot export parquet delta.")
            return None

        latest_date = str(max_date_row[0][0])
        logger.info("Exporting daily parquet delta for trade date %s...", latest_date)

        query = f"SELECT ticker, trade_date, open, high, low, close, adj_close, volume FROM daily_bars WHERE trade_date = '{latest_date}';"
        rows = self.db_manager.execute_read(query)

        if not rows:
            logger.warning("No rows found for trade date %s.", latest_date)
            return None

        cols = ["ticker", "trade_date", "open", "high", "low", "close", "adj_close", "volume"]
        df = pd.DataFrame(rows, columns=cols)

        df.to_parquet(target_file, index=False)
        logger.info("Successfully exported %d rows to %s", len(df), target_file)

        # Prune parquet files older than retention_days
        cutoff_time = time.time() - (retention_days * 86400)
        for pfile in out_path.glob("*.parquet"):
            if pfile.stat().st_mtime < cutoff_time:
                try:
                    pfile.unlink()
                    logger.info("Pruned old delta parquet file: %s", pfile.name)
                except Exception as err:
                    logger.warning("Failed to delete old file %s: %s", pfile.name, err)

        return str(target_file)

    def sync_local_db_from_parquet(self, deltas_dir: str = "data/daily_deltas") -> int:
        """Scan deltas_dir for parquet files and merge un-synced trade dates into local DuckDB.

        Args:
            deltas_dir: Directory containing daily delta parquet files.

        Returns:
            int: Number of newly synced trade dates merged into DuckDB.
        """
        import pathlib
        d_path = pathlib.Path(deltas_dir)
        if not d_path.exists():
            return 0

        parquet_files = sorted(list(d_path.glob("*.parquet")))
        if not parquet_files:
            return 0

        max_date_row = self.db_manager.execute_read("SELECT MAX(trade_date) FROM daily_bars;")
        local_max_date = str(max_date_row[0][0]) if (max_date_row and max_date_row[0][0]) else "1970-01-01"

        inserted_dates = 0
        for pfile in parquet_files:
            file_date_str = pfile.stem  # YYYY-MM-DD
            if file_date_str > local_max_date:
                logger.info("Merging remote delta parquet file %s into local DuckDB...", pfile.name)
                try:
                    p_df = pd.read_parquet(pfile)
                    if p_df.empty:
                        continue

                    records = [
                        (
                            str(r["ticker"]).upper(),
                            datetime.date.fromisoformat(str(r["trade_date"])),
                            float(r["open"]),
                            float(r["high"]),
                            float(r["low"]),
                            float(r["close"]),
                            float(r["adj_close"]),
                            int(r["volume"]),
                        )
                        for _, r in p_df.iterrows()
                    ]

                    with self.db_manager.write_cursor() as conn:
                        conn.executemany(
                            """
                            INSERT OR REPLACE INTO daily_bars
                            (ticker, trade_date, open, high, low, close, adj_close, volume)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            records,
                        )
                    inserted_dates += 1
                    logger.info("Successfully merged %d rows from %s", len(records), pfile.name)
                except Exception as e:
                    logger.error("Error merging parquet file %s: %s", pfile.name, e)

        return inserted_dates
