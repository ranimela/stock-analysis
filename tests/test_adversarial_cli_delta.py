"""Adversarial stress-test suite for CLI multi-exchange commands and TASE delta sync.

Challenger M1_2 Test Suite.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any, Sequence
from unittest.mock import MagicMock, patch

from click.testing import CliRunner
import pandas as pd
import pytest

from src.cli import main, seed, update
from src.db.db_manager import DatabaseManager
from src.ingestion.data_ingestor import DataIngestor
from src.ingestion.symbol_directory import sync_symbol_metadata
from src.ingestion.tase_directory import TASE_BENCHMARK_TICKER, fetch_tase_symbols


# ============================================================================
# TEST HELPERS
# ============================================================================


def make_mock_yf_multi_df(
    tickers: Sequence[str],
    dates: Sequence[str | datetime.date],
    start_price: float = 100.0,
) -> pd.DataFrame:
    """Create synthetic MultiIndex yfinance DataFrame."""
    idx = pd.to_datetime(list(dates))
    ticker_list = [t.strip().upper() for t in tickers]
    data = {}
    for i, t in enumerate(ticker_list):
        base = start_price + (i * 50.0)
        data[("Open", t)] = [base + j for j in range(len(idx))]
        data[("High", t)] = [base + j + 5.0 for j in range(len(idx))]
        data[("Low", t)] = [base + j - 5.0 for j in range(len(idx))]
        data[("Close", t)] = [base + j + 2.0 for j in range(len(idx))]
        data[("Adj Close", t)] = [base + j + 2.0 for j in range(len(idx))]
        data[("Volume", t)] = [50000 + (j * 1000) for j in range(len(idx))]

    df = pd.DataFrame(data, index=idx)
    df.columns = pd.MultiIndex.from_tuples(df.columns)
    return df


def make_mock_yf_single_df(
    ticker: str,
    dates: Sequence[str | datetime.date],
    start_price: float = 100.0,
) -> pd.DataFrame:
    """Create synthetic SingleIndex yfinance DataFrame (1 ticker download shape)."""
    idx = pd.to_datetime(list(dates))
    data = {
        "Open": [start_price + j for j in range(len(idx))],
        "High": [start_price + j + 5.0 for j in range(len(idx))],
        "Low": [start_price + j - 5.0 for j in range(len(idx))],
        "Close": [start_price + j + 2.0 for j in range(len(idx))],
        "Adj Close": [start_price + j + 2.0 for j in range(len(idx))],
        "Volume": [50000 + (j * 1000) for j in range(len(idx))],
    }
    return pd.DataFrame(data, index=idx)


@pytest.fixture
def clean_db(tmp_path: Path) -> DatabaseManager:
    """Fixture to provide an isolated DatabaseManager instance."""
    db_file = tmp_path / "test_stress.duckdb"
    return DatabaseManager(db_path=db_file, read_only=False)


# ============================================================================
# 1. CLI MULTI-EXCHANGE COMMANDS STRESS TESTS
# ============================================================================


class TestCLIMultiExchangeCommands:
    """Adversarial stress-testing of CLI seed and update commands."""

    def test_seed_exchange_us_isolation(self, tmp_path: Path):
        """Verify CLI seed with --exchange US strictly isolates to US symbols and SPY benchmark."""
        db_file = tmp_path / "seed_us.duckdb"
        runner = CliRunner()

        mock_us = [
            {"ticker": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ", "asset_class": "Common Stock", "is_active": True},
            {"ticker": "MSFT", "name": "Microsoft Corp.", "exchange": "NASDAQ", "asset_class": "Common Stock", "is_active": True},
        ]

        with patch("src.cli.fetch_symbol_directory", return_value=mock_us) as mock_fetch_us, \
             patch("src.cli.get_tase_symbol_directory") as mock_fetch_tase, \
             patch("src.ingestion.data_ingestor.DataIngestor.download_spy", return_value=10) as mock_dl_spy, \
             patch("src.ingestion.data_ingestor.DataIngestor.download_tase_benchmark") as mock_dl_tase, \
             patch("src.ingestion.data_ingestor.DataIngestor.fetch_ticker_chunk", return_value=pd.DataFrame()):

            result = runner.invoke(main, ["seed", "--db-path", str(db_file), "--exchange", "US"])

            assert result.exit_code == 0
            assert mock_fetch_us.called
            assert not mock_fetch_tase.called, "TASE directory must NOT be fetched when --exchange US"
            assert mock_dl_spy.called, "SPY benchmark must be downloaded for US universe"
            assert not mock_dl_tase.called, "TASE benchmark must NOT be downloaded when --exchange US"

            db = DatabaseManager(db_path=db_file, read_only=True)
            tase_meta = db.execute_read("SELECT count(*) FROM symbol_metadata WHERE exchange = 'TASE'")
            assert tase_meta[0][0] == 0, "No TASE symbols should exist in symbol_metadata when seeded with --exchange US"

    def test_seed_exchange_tase_isolation(self, tmp_path: Path):
        """Verify CLI seed with --exchange TASE strictly isolates to TASE symbols and TA125 benchmark."""
        db_file = tmp_path / "seed_tase.duckdb"
        runner = CliRunner()

        with patch("src.cli.fetch_symbol_directory") as mock_fetch_us, \
             patch("src.ingestion.data_ingestor.DataIngestor.download_spy") as mock_dl_spy, \
             patch("src.ingestion.data_ingestor.DataIngestor.download_tase_benchmark", return_value=10) as mock_dl_tase, \
             patch("src.ingestion.data_ingestor.DataIngestor.fetch_ticker_chunk", return_value=pd.DataFrame()):

            result = runner.invoke(main, ["seed", "--db-path", str(db_file), "--exchange", "TASE"])

            assert result.exit_code == 0
            assert not mock_fetch_us.called, "US directory must NOT be fetched when --exchange TASE"
            assert not mock_dl_spy.called, "SPY benchmark must NOT be downloaded when --exchange TASE"
            assert mock_dl_tase.called, "TASE benchmark must be downloaded for TASE universe"

            db = DatabaseManager(db_path=db_file, read_only=True)
            us_meta = db.execute_read("SELECT count(*) FROM symbol_metadata WHERE exchange != 'TASE' AND ticker != '^TA125.TA'")
            assert us_meta[0][0] == 0, "No non-TASE symbols should exist in symbol_metadata when seeded with --exchange TASE"

            tase_count = db.execute_read("SELECT count(*) FROM symbol_metadata WHERE exchange = 'TASE'")
            assert tase_count[0][0] >= 100, "TASE symbols must be seeded in symbol_metadata"

    def test_seed_exchange_all_dual_universe(self, tmp_path: Path):
        """Verify CLI seed with --exchange ALL seeds both US and TASE universes and benchmarks."""
        db_file = tmp_path / "seed_all.duckdb"
        runner = CliRunner()

        mock_us = [
            {"ticker": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ", "asset_class": "Common Stock", "is_active": True},
        ]

        with patch("src.cli.fetch_symbol_directory", return_value=mock_us) as mock_fetch_us, \
             patch("src.cli.get_tase_symbol_directory", wraps=fetch_tase_symbols) as mock_fetch_tase, \
             patch("src.ingestion.data_ingestor.DataIngestor.download_spy", return_value=10) as mock_dl_spy, \
             patch("src.ingestion.data_ingestor.DataIngestor.download_tase_benchmark", return_value=10) as mock_dl_tase, \
             patch("src.ingestion.data_ingestor.DataIngestor.fetch_ticker_chunk", return_value=pd.DataFrame()):

            result = runner.invoke(main, ["seed", "--db-path", str(db_file), "--exchange", "ALL"])

            assert result.exit_code == 0
            assert mock_fetch_us.called
            assert mock_fetch_tase.called
            assert mock_dl_spy.called
            assert mock_dl_tase.called

            db = DatabaseManager(db_path=db_file, read_only=True)
            us_count = db.execute_read("SELECT count(*) FROM symbol_metadata WHERE exchange = 'NASDAQ'")
            tase_count = db.execute_read("SELECT count(*) FROM symbol_metadata WHERE exchange = 'TASE'")
            assert us_count[0][0] == 1
            assert tase_count[0][0] >= 100

    @pytest.mark.parametrize("cmd,flag,val", [
        ("seed", "--exchange", "us"),
        ("seed", "--exchange", "tase"),
        ("seed", "--exchange", "all"),
        ("seed", "-e", "Us"),
        ("seed", "-e", "Tase"),
        ("seed", "-e", "ALL"),
        ("update", "--exchange", "us"),
        ("update", "--exchange", "tase"),
        ("update", "--exchange", "all"),
        ("update", "-e", "Us"),
        ("update", "-e", "Tase"),
        ("update", "-e", "ALL"),
    ])
    def test_cli_case_insensitive_flags(self, tmp_path: Path, cmd: str, flag: str, val: str):
        """Verify CLI accepts case-insensitive exchange values (us, tase, all, mixed case)."""
        db_file = tmp_path / f"{cmd}_{val}.duckdb"
        runner = CliRunner()

        mock_us = [{"ticker": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ", "asset_class": "Common Stock", "is_active": True}]
        mock_tase = [{"ticker": "TEVA.TA", "name": "Teva", "exchange": "TASE", "asset_class": "Common Stock", "is_active": True}]

        with patch("src.cli.fetch_symbol_directory", return_value=mock_us), \
             patch("src.cli.get_tase_symbol_directory", return_value=mock_tase), \
             patch("src.ingestion.data_ingestor.DataIngestor.download_spy", return_value=1), \
             patch("src.ingestion.data_ingestor.DataIngestor.download_tase_benchmark", return_value=1), \
             patch("src.ingestion.data_ingestor.DataIngestor.sync_universe", return_value={
                 "total_tickers": 10, "synced_tickers": 0, "total_bars_inserted": 0, "status": "up_to_date"
             }):

            result = runner.invoke(main, [cmd, "--db-path", str(db_file), flag, val])
            assert result.exit_code == 0, f"Failed for command '{cmd}' with flag '{flag} {val}': {result.output}"

    @pytest.mark.parametrize("cmd,invalid_val", [
        ("seed", "INVALID"),
        ("seed", "LSE"),
        ("seed", "NYSE"),
        ("seed", "123"),
        ("seed", ""),
        ("update", "INVALID"),
        ("update", "LSE"),
        ("update", "NYSE"),
        ("update", "123"),
        ("update", ""),
    ])
    def test_cli_invalid_exchange_rejection(self, tmp_path: Path, cmd: str, invalid_val: str):
        """Verify CLI rejects invalid exchange values with non-zero exit code and error message."""
        db_file = tmp_path / "invalid_ex.duckdb"
        runner = CliRunner()

        result = runner.invoke(main, [cmd, "--db-path", str(db_file), "--exchange", invalid_val])
        assert result.exit_code != 0
        assert "Invalid value for" in result.output or "invalid choice" in result.output.lower() or "Error" in result.output

    def test_cli_update_exchange_routing(self, tmp_path: Path):
        """Verify CLI update routes correctly to DataIngestor.sync_universe with target exchange."""
        db_file = tmp_path / "update_routing.duckdb"
        runner = CliRunner()

        with patch("src.ingestion.data_ingestor.DataIngestor.sync_universe") as mock_sync:
            mock_sync.return_value = {
                "total_tickers": 50,
                "synced_tickers": 5,
                "total_bars_inserted": 25,
                "status": "success",
            }

            # Update TASE
            res_tase = runner.invoke(main, ["update", "--db-path", str(db_file), "--exchange", "TASE"])
            assert res_tase.exit_code == 0
            mock_sync.assert_called_with(exchange="TASE")

            # Update US
            res_us = runner.invoke(main, ["update", "--db-path", str(db_file), "--exchange", "US"])
            assert res_us.exit_code == 0
            mock_sync.assert_called_with(exchange="US")

            # Update ALL
            res_all = runner.invoke(main, ["update", "--db-path", str(db_file), "--exchange", "ALL"])
            assert res_all.exit_code == 0
            mock_sync.assert_called_with(exchange="ALL")

    def test_cli_seed_empty_universe_graceful_exit(self, tmp_path: Path):
        """Verify CLI seed exits with code 1 when all symbol sources return empty."""
        db_file = tmp_path / "seed_empty.duckdb"
        runner = CliRunner()

        with patch("src.cli.fetch_symbol_directory", return_value=[]), \
             patch("src.cli.get_tase_symbol_directory", return_value=[]):
            result = runner.invoke(main, ["seed", "--db-path", str(db_file), "--exchange", "ALL"])
            assert result.exit_code == 1
            assert "Error: No symbols discovered" in result.output


# ============================================================================
# 2. TASE DELTA SYNC & DATE BOUNDARY STRESS TESTS
# ============================================================================


class TestTASEDeltaSyncAndDateBoundaries:
    """Adversarial stress-testing of TASE delta sync, date boundary handling, and deduplication."""

    def test_delta_sync_skips_existing_dates_and_inserts_only_new(self, clean_db: DatabaseManager):
        """Test delta sync strictly inserts new dates and does not re-insert existing bars."""
        ingestor = DataIngestor(db_manager=clean_db)

        # Pre-populate DB with 3 historical bars for TEVA.TA
        initial_records = [
            ("TEVA.TA", datetime.date(2026, 8, 10), 6000.0, 6100.0, 5900.0, 6050.0, 6050.0, 100000),
            ("TEVA.TA", datetime.date(2026, 8, 11), 6050.0, 6150.0, 6000.0, 6100.0, 6100.0, 110000),
            ("TEVA.TA", datetime.date(2026, 8, 12), 6100.0, 6200.0, 6050.0, 6150.0, 6150.0, 120000),
        ]
        with clean_db.write_cursor() as conn:
            conn.executemany(
                "INSERT INTO daily_bars (ticker, trade_date, open, high, low, close, adj_close, volume) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                initial_records,
            )

        max_dates = ingestor.get_existing_max_dates()
        assert max_dates.get("TEVA.TA") == datetime.date(2026, 8, 12)

        # Incoming batch has 5 bars: 3 overlapping (8/10, 8/11, 8/12) + 2 new (8/13, 8/14)
        all_dates = ["2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13", "2026-08-14"]
        mock_df = make_mock_yf_multi_df(["TEVA.TA"], all_dates, start_price=6000.0)

        bars_inserted = ingestor.parse_and_store_bars(mock_df, ["TEVA.TA"], max_dates=max_dates)
        assert bars_inserted == 2, f"Expected 2 new bars inserted, got {bars_inserted}"

        # Verify DB contents
        stored_bars = clean_db.execute_read("SELECT trade_date, close FROM daily_bars WHERE ticker = 'TEVA.TA' ORDER BY trade_date")
        assert len(stored_bars) == 5
        # Verify original bars were NOT modified
        assert stored_bars[0][0] == datetime.date(2026, 8, 10)
        assert stored_bars[0][1] == 6050.0  # Original close price

    def test_delta_sync_up_to_date_short_circuit(self, clean_db: DatabaseManager):
        """Test delta sync short-circuits with 0 downloads when all tickers are up to date."""
        ingestor = DataIngestor(db_manager=clean_db)
        today = datetime.date.today()

        # Seed metadata and bars for TASE stock up to today
        with clean_db.write_cursor() as conn:
            conn.execute(
                "INSERT INTO symbol_metadata (ticker, name, exchange, asset_class, is_active) VALUES ('LUMI.TA', 'Bank Leumi', 'TASE', 'Common Stock', true)"
            )
            conn.execute(
                "INSERT INTO daily_bars (ticker, trade_date, open, high, low, close, adj_close, volume) VALUES ('LUMI.TA', ?, 3000.0, 3100.0, 2900.0, 3050.0, 3050.0, 500000)",
                [today],
            )

        with patch.object(ingestor, "download_tase_benchmark", return_value=1), \
             patch.object(ingestor, "fetch_ticker_chunk") as mock_chunk:

            summary = ingestor.sync_universe(symbols=["LUMI.TA"], exchange="TASE")
            assert summary["status"] == "up_to_date"
            assert summary["synced_tickers"] == 0
            assert summary["total_bars_inserted"] == 0
            assert not mock_chunk.called, "fetch_ticker_chunk should NOT be called when universe is up to date"

    def test_tase_sunday_thursday_schedule_delta(self, clean_db: DatabaseManager):
        """Test TASE Sunday-Thursday trading schedule delta ingestion."""
        ingestor = DataIngestor(db_manager=clean_db)

        # Simulate last synced trade date was Thursday (e.g. 2026-08-20)
        thursday = datetime.date(2026, 8, 20)
        with clean_db.write_cursor() as conn:
            conn.execute(
                "INSERT INTO daily_bars (ticker, trade_date, open, high, low, close, adj_close, volume) VALUES ('NICE.TA', ?, 7000.0, 7100.0, 6900.0, 7050.0, 7050.0, 50000)",
                [thursday],
            )

        # Sunday 2026-08-23 and Monday 2026-08-24 bars arrive
        trading_dates = ["2026-08-20", "2026-08-23", "2026-08-24"]
        mock_df = make_mock_yf_multi_df(["NICE.TA"], trading_dates, start_price=7000.0)

        max_dates = ingestor.get_existing_max_dates()
        bars_inserted = ingestor.parse_and_store_bars(mock_df, ["NICE.TA"], max_dates=max_dates)

        # Friday and Saturday had no trading; Sunday (8/23) and Monday (8/24) should be inserted
        assert bars_inserted == 2
        dates_in_db = clean_db.execute_read("SELECT trade_date FROM daily_bars WHERE ticker = 'NICE.TA' ORDER BY trade_date")
        dates_list = [r[0] for r in dates_in_db]
        assert dates_list == [datetime.date(2026, 8, 20), datetime.date(2026, 8, 23), datetime.date(2026, 8, 24)]

    def test_delta_sync_single_ticker_df_format(self, clean_db: DatabaseManager):
        """Test delta sync handles single-index DataFrame format (returned when 1 ticker is fetched)."""
        ingestor = DataIngestor(db_manager=clean_db)

        # Existing date
        with clean_db.write_cursor() as conn:
            conn.execute(
                "INSERT INTO daily_bars (ticker, trade_date, open, high, low, close, adj_close, volume) VALUES ('ICL.TA', '2026-08-01', 2000.0, 2050.0, 1950.0, 2020.0, 2020.0, 100000)"
            )

        max_dates = ingestor.get_existing_max_dates()
        single_df = make_mock_yf_single_df("ICL.TA", ["2026-08-01", "2026-08-02", "2026-08-03"], start_price=2020.0)

        bars_inserted = ingestor.parse_and_store_bars(single_df, ["ICL.TA"], max_dates=max_dates)
        assert bars_inserted == 2
        rows = clean_db.execute_read("SELECT trade_date FROM daily_bars WHERE ticker = 'ICL.TA' ORDER BY trade_date")
        assert len(rows) == 3

    def test_delta_sync_with_corrupted_nan_data(self, clean_db: DatabaseManager):
        """Test delta sync skips rows with NaN Close prices without corrupting existing records."""
        ingestor = DataIngestor(db_manager=clean_db)

        # Pre-existing bar
        with clean_db.write_cursor() as conn:
            conn.execute(
                "INSERT INTO daily_bars (ticker, trade_date, open, high, low, close, adj_close, volume) VALUES ('POLI.TA', '2026-08-01', 3000.0, 3050.0, 2950.0, 3020.0, 3020.0, 100000)"
            )

        max_dates = ingestor.get_existing_max_dates()

        dates = pd.date_range("2026-08-01", periods=4)
        data = {
            ("Open", "POLI.TA"): [3000.0, 3020.0, float("nan"), 3040.0],
            ("High", "POLI.TA"): [3050.0, 3060.0, float("nan"), 3080.0],
            ("Low", "POLI.TA"): [2950.0, 3000.0, float("nan"), 3010.0],
            ("Close", "POLI.TA"): [3020.0, 3040.0, float("nan"), 3060.0],  # 3rd row is NaN Close
            ("Adj Close", "POLI.TA"): [3020.0, 3040.0, float("nan"), 3060.0],
            ("Volume", "POLI.TA"): [100000, 120000, float("nan"), 150000],
        }
        nan_df = pd.DataFrame(data, index=dates)
        nan_df.columns = pd.MultiIndex.from_tuples(nan_df.columns)

        bars_inserted = ingestor.parse_and_store_bars(nan_df, ["POLI.TA"], max_dates=max_dates)
        # 8/1 skipped because <= max_date. 8/2 inserted. 8/3 skipped due to NaN. 8/4 inserted.
        assert bars_inserted == 2

        rows = clean_db.execute_read("SELECT trade_date, close FROM daily_bars WHERE ticker = 'POLI.TA' ORDER BY trade_date")
        assert len(rows) == 3
        assert rows[1][1] == 3040.0
        assert rows[2][1] == 3060.0

    def test_parquet_export_and_sync_delta_integration(self, clean_db: DatabaseManager, tmp_path: Path):
        """Test exporting daily delta to parquet and merging into a separate local database."""
        ingestor_src = DataIngestor(db_manager=clean_db)
        deltas_dir = tmp_path / "deltas"

        # Populate source DB with trade date
        with clean_db.write_cursor() as conn:
            conn.execute(
                "INSERT INTO daily_bars (ticker, trade_date, open, high, low, close, adj_close, volume) VALUES ('TEVA.TA', '2026-08-27', 6000.0, 6100.0, 5950.0, 6050.0, 6050.0, 200000)"
            )
            conn.execute(
                "INSERT INTO daily_bars (ticker, trade_date, open, high, low, close, adj_close, volume) VALUES ('SPY', '2026-08-27', 550.0, 555.0, 548.0, 553.0, 553.0, 50000000)"
            )

        # Export delta
        exported_path = ingestor_src.export_daily_delta_parquet(output_dir=str(deltas_dir))
        assert exported_path is not None
        assert Path(exported_path).exists()

        # Destination DB (empty / older)
        dest_db_file = tmp_path / "dest.duckdb"
        dest_db = DatabaseManager(db_path=dest_db_file, read_only=False)
        ingestor_dest = DataIngestor(db_manager=dest_db)

        # Sync from parquet
        merged_count = ingestor_dest.sync_local_db_from_parquet(deltas_dir=str(deltas_dir))
        assert merged_count == 1

        dest_rows = dest_db.execute_read("SELECT ticker, trade_date, close FROM daily_bars ORDER BY ticker")
        assert len(dest_rows) == 2
        assert dest_rows[0][0] == "SPY"
        assert dest_rows[1][0] == "TEVA.TA"

    def test_dual_listed_ticker_delta_isolation(self, clean_db: DatabaseManager):
        """Test delta sync keeps distinct max_dates for US 'TEVA' and TASE 'TEVA.TA'."""
        ingestor = DataIngestor(db_manager=clean_db)

        with clean_db.write_cursor() as conn:
            # TEVA (US) max date is 2026-08-15
            conn.execute(
                "INSERT INTO daily_bars (ticker, trade_date, open, high, low, close, adj_close, volume) VALUES ('TEVA', '2026-08-15', 18.0, 18.5, 17.8, 18.2, 18.2, 5000000)"
            )
            # TEVA.TA (TASE) max date is 2026-08-10 (older)
            conn.execute(
                "INSERT INTO daily_bars (ticker, trade_date, open, high, low, close, adj_close, volume) VALUES ('TEVA.TA', '2026-08-10', 6500.0, 6600.0, 6400.0, 6550.0, 6550.0, 150000)"
            )

        max_dates = ingestor.get_existing_max_dates()
        assert max_dates["TEVA"] == datetime.date(2026, 8, 15)
        assert max_dates["TEVA.TA"] == datetime.date(2026, 8, 10)

        # Incoming batch for TEVA.TA with dates 2026-08-11 through 2026-08-15
        tase_dates = ["2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13", "2026-08-14", "2026-08-15"]
        mock_tase_df = make_mock_yf_multi_df(["TEVA.TA"], tase_dates, start_price=6550.0)

        # Ingest TEVA.TA batch
        inserted = ingestor.parse_and_store_bars(mock_tase_df, ["TEVA.TA"], max_dates=max_dates)
        # Should insert 5 new bars for TEVA.TA (8/11 to 8/15) without affecting US TEVA
        assert inserted == 5

        us_rows = clean_db.execute_read("SELECT count(*) FROM daily_bars WHERE ticker = 'TEVA'")
        tase_rows = clean_db.execute_read("SELECT count(*) FROM daily_bars WHERE ticker = 'TEVA.TA'")
        assert us_rows[0][0] == 1, "US TEVA count must remain 1"
        assert tase_rows[0][0] == 6, "TASE TEVA.TA count must be 6"

    def test_get_existing_max_dates_type_handling(self, clean_db: DatabaseManager):
        """Test get_existing_max_dates handles empty DB, str, datetime, and date objects robustly."""
        ingestor = DataIngestor(db_manager=clean_db)

        # 1. Empty DB
        assert ingestor.get_existing_max_dates() == {}

        # 2. Insert mix of dates
        with clean_db.write_cursor() as conn:
            conn.execute("INSERT INTO daily_bars (ticker, trade_date, close) VALUES ('LUMI.TA', '2026-08-01', 3000.0)")
            conn.execute("INSERT INTO daily_bars (ticker, trade_date, close) VALUES ('LUMI.TA', '2026-08-05', 3050.0)")

        max_dates = ingestor.get_existing_max_dates()
        assert "LUMI.TA" in max_dates
        assert max_dates["LUMI.TA"] == datetime.date(2026, 8, 5)
        assert isinstance(max_dates["LUMI.TA"], datetime.date)
