"""Unit and integration tests for Data Ingestion module and CLI commands."""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Sequence
from unittest.mock import MagicMock, patch

from click.testing import CliRunner
import pandas as pd
import pytest

from src.db.db_manager import DatabaseManager
from src.ingestion.data_ingestor import DataIngestor
from src.ingestion.symbol_directory import (
    is_common_stock,
    parse_nasdaqlisted,
    parse_otherlisted,
    sync_symbol_metadata,
)
from src.ingestion.tase_directory import (
    TASE_BENCHMARK,
    TASE_BENCHMARK_TICKER,
    fetch_tase_symbols,
    get_tase_symbol_directory,
    get_tase_symbols,
    get_tase_symbols_df,
    is_tase_ticker,
    normalize_tase_ticker,
    sync_tase_symbol_metadata,
)


@pytest.fixture
def tmp_db(tmp_path: Path) -> DatabaseManager:
    """Fixture providing a temporary DatabaseManager instance."""
    db_file = tmp_path / "test_market_data.duckdb"
    return DatabaseManager(db_file)


def make_mock_yf_df(
    tickers: Sequence[str],
    dates: Sequence[str] | pd.DatetimeIndex,
    start_price: float = 1000.0,
) -> pd.DataFrame:
    """Helper to generate multi-index or single-index synthetic yfinance DataFrame."""
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


# ============================================================================
# US SYMBOL DIRECTORY TESTS
# ============================================================================


def test_is_common_stock_filtering():
    """Test common stock filtering logic against various security types."""
    # Valid common stocks
    assert is_common_stock("AAPL", "Apple Inc. - Common Stock") is True
    assert is_common_stock("MSFT", "Microsoft Corporation Common Stock") is True
    assert is_common_stock("BRK-B", "Berkshire Hathaway Inc. Class B Common Stock") is True

    # Exclude ETFs
    assert is_common_stock("SPY", "SPDR S&P 500 ETF Trust") is False
    assert is_common_stock("QQQ", "Invesco QQQ Trust Series 1 ETF") is False

    # Exclude Warrants
    assert is_common_stock("ABCWS", "Acme Corp Warrants") is False
    assert is_common_stock("XYZ-W", "XYZ Corp Wt") is False

    # Exclude Preferreds
    assert is_common_stock("BAC-PB", "Bank of America Preferred Stock Series B") is False
    assert is_common_stock("F-PR-A", "Ford Motor Co 6% Preferred Stock") is False

    # Exclude Test Tickers
    assert is_common_stock("ZVV", "Test Ticker ZVV") is False
    assert is_common_stock("ATEST", "ATEST Stock") is False

    # Exclude SPACs / Blank Check
    assert is_common_stock("SPACU", "Blank Check Acquisition Corp Units") is False


def test_parse_nasdaqlisted():
    """Test parsing nasdaqlisted.txt raw content."""
    sample_content = (
        "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\n"
        "AAPL|Apple Inc. Common Stock|Q|N|N|100|N|N\n"
        "QQQ|Invesco QQQ Trust|Q|N|N|100|Y|N\n"
        "ZVV|Test Ticker|Q|Y|N|100|N|N\n"
        "File Creation Time: 0818202612:00|||||||\n"
    )
    result = parse_nasdaqlisted(sample_content)
    assert len(result) == 1
    assert result[0]["ticker"] == "AAPL"
    assert result[0]["exchange"] == "NASDAQ"
    assert result[0]["asset_class"] == "Common Stock"


def test_parse_otherlisted():
    """Test parsing otherlisted.txt raw content."""
    sample_content = (
        "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\n"
        "IBM|International Business Machines Common Stock|N|IBM|N|100|N|IBM\n"
        "SPY|SPDR S&P 500 ETF Trust|P|SPY|Y|100|N|SPY\n"
        "File Creation Time: 0818202612:00|||||||\n"
    )
    result = parse_otherlisted(sample_content)
    assert len(result) == 1
    assert result[0]["ticker"] == "IBM"
    assert result[0]["exchange"] == "NYSE"


def test_sync_symbol_metadata(tmp_db: DatabaseManager):
    """Test inserting symbol metadata into DuckDB."""
    symbols = [
        {"ticker": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ", "asset_class": "Common Stock", "is_active": True},
        {"ticker": "MSFT", "name": "Microsoft Corp.", "exchange": "NASDAQ", "asset_class": "Common Stock", "is_active": True},
    ]
    inserted = sync_symbol_metadata(tmp_db, symbols)
    assert inserted == 2

    rows = tmp_db.execute_read("SELECT ticker, name, exchange FROM symbol_metadata ORDER BY ticker")
    assert len(rows) == 2
    assert rows[0] == ("AAPL", "Apple Inc.", "NASDAQ")
    assert rows[1] == ("MSFT", "Microsoft Corp.", "NASDAQ")


def test_download_spy_hard_gate_failure(tmp_db: DatabaseManager):
    """Test that download_spy raises RuntimeError when yfinance returns empty data."""
    ingestor = DataIngestor(db_manager=tmp_db)

    with patch("yfinance.download", return_value=pd.DataFrame()):
        with pytest.raises(RuntimeError, match="SPY benchmark download failed"):
            ingestor.download_spy()


def test_parse_and_store_bars(tmp_db: DatabaseManager):
    """Test parsing yfinance DataFrame and inserting into daily_bars."""
    ingestor = DataIngestor(db_manager=tmp_db)

    dates = pd.date_range("2026-08-01", periods=3)
    data = {
        ("Close", "AAPL"): [150.0, 152.0, 151.0],
        ("Open", "AAPL"): [149.0, 150.5, 151.5],
        ("High", "AAPL"): [151.0, 153.0, 152.5],
        ("Low", "AAPL"): [148.5, 150.0, 150.0],
        ("Volume", "AAPL"): [10000, 12000, 11000],
    }
    df = pd.DataFrame(data, index=dates)
    df.columns = pd.MultiIndex.from_tuples(df.columns)

    inserted = ingestor.parse_and_store_bars(df, ["AAPL"])
    assert inserted == 3

    rows = tmp_db.execute_read("SELECT ticker, trade_date, close, volume FROM daily_bars WHERE ticker = 'AAPL' ORDER BY trade_date")
    assert len(rows) == 3
    assert rows[0][0] == "AAPL"
    assert rows[0][2] == 150.0
    assert rows[0][3] == 10000


def test_delta_sync_filtering(tmp_db: DatabaseManager):
    """Test delta sync filtering logic prevents inserting older duplicate dates."""
    ingestor = DataIngestor(db_manager=tmp_db)

    # Insert existing bar for AAPL on 2026-08-01
    records = [
        ("AAPL", datetime.date(2026, 8, 1), 150.0, 155.0, 149.0, 154.0, 154.0, 1000000)
    ]
    with tmp_db.write_cursor() as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO daily_bars
            (ticker, trade_date, open, high, low, close, adj_close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            records,
        )

    max_dates = ingestor.get_existing_max_dates()
    assert max_dates.get("AAPL") == datetime.date(2026, 8, 1)

    dates = [pd.Timestamp("2026-08-01"), pd.Timestamp("2026-08-02")]
    data = {
        ("Close", "AAPL"): [154.0, 156.0],
        ("Open", "AAPL"): [150.0, 155.0],
        ("High", "AAPL"): [155.0, 157.0],
        ("Low", "AAPL"): [149.0, 154.0],
        ("Volume", "AAPL"): [1000000, 1100000],
    }
    df = pd.DataFrame(data, index=dates)
    df.columns = pd.MultiIndex.from_tuples(df.columns)

    inserted = ingestor.parse_and_store_bars(df, ["AAPL"], max_dates=max_dates)
    assert inserted == 1  # Only 2026-08-02 should be inserted

    rows = tmp_db.execute_read("SELECT trade_date FROM daily_bars WHERE ticker = 'AAPL' ORDER BY trade_date")
    assert len(rows) == 2


# ============================================================================
# TASE DIRECTORY & BENCHMARK TESTS
# ============================================================================


def test_get_tase_symbol_directory_structure():
    """Test TASE directory returns valid constituent metadata list."""
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
    symbols = get_tase_symbol_directory()
    tickers = {s["ticker"] for s in symbols}
    required = ["TEVA.TA", "LUMI.TA", "NICE.TA", "ICL.TA", "POLI.TA", "ESLT.TA", "DSCT.TA", "AZRG.TA", "BEZQ.TA"]
    for req in required:
        assert req in tickers


def test_normalize_tase_ticker():
    """Test symbol normalization to .TA suffix and benchmark handling."""
    assert normalize_tase_ticker("TEVA") == "TEVA.TA"
    assert normalize_tase_ticker("teva.ta") == "TEVA.TA"
    assert normalize_tase_ticker("LUMI.TA") == "LUMI.TA"
    assert normalize_tase_ticker("^TA125.TA") == "^TA125.TA"
    assert normalize_tase_ticker("^TA125") == "^TA125.TA"


def test_is_tase_ticker():
    """Test checking whether symbol belongs to TASE universe."""
    assert is_tase_ticker("TEVA.TA") is True
    assert is_tase_ticker("teva.ta") is True
    assert is_tase_ticker("^TA125.TA") is True
    assert is_tase_ticker("AAPL") is False
    assert is_tase_ticker("") is False


def test_get_tase_symbols_and_df():
    """Test get_tase_symbols and get_tase_symbols_df return types and columns."""
    symbols = get_tase_symbols()
    assert len(symbols) >= 100
    assert all(s.endswith(".TA") for s in symbols)

    df = get_tase_symbols_df()
    assert isinstance(df, pd.DataFrame)
    assert not df.empty
    assert "ticker" in df.columns
    assert "exchange" in df.columns
    assert "sector" in df.columns
    assert all(df["exchange"] == "TASE")


def test_sync_tase_symbol_metadata(tmp_db: DatabaseManager):
    """Test inserting TASE symbol metadata into DuckDB."""
    symbols = get_tase_symbol_directory()[:10]
    inserted = sync_tase_symbol_metadata(tmp_db, symbols)
    assert inserted == 10

    rows = tmp_db.execute_read("SELECT ticker, exchange, asset_class FROM symbol_metadata WHERE exchange = 'TASE'")
    assert len(rows) == 10
    assert all(r[1] == "TASE" for r in rows)


def test_tase_benchmark_constant():
    """Test benchmark constant consistency."""
    assert TASE_BENCHMARK == "^TA125.TA"
    assert TASE_BENCHMARK_TICKER == "^TA125.TA"


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
        with pytest.raises(RuntimeError, match=r"\^TA125\.TA benchmark download failed"):
            ingestor.download_tase_benchmark()


def test_download_tase_benchmark_network_exception_failure(tmp_db: DatabaseManager):
    """Test download_tase_benchmark raises RuntimeError on network exception."""
    ingestor = DataIngestor(db_manager=tmp_db)
    with patch("yfinance.download", side_effect=Exception("Connection timed out")):
        with pytest.raises(RuntimeError, match=r"\^TA125\.TA benchmark download failed"):
            ingestor.download_tase_benchmark()


def test_sync_universe_tase_hard_gate(tmp_db: DatabaseManager):
    """Test sync_universe hard-gates on TASE benchmark failure."""
    ingestor = DataIngestor(db_manager=tmp_db)
    with patch.object(ingestor, "download_tase_benchmark", side_effect=RuntimeError("Benchmark fail")):
        with pytest.raises(RuntimeError, match="Benchmark fail"):
            ingestor.sync_universe(exchange="TASE")


def test_sync_universe_all_hard_gate_on_tase_failure(tmp_db: DatabaseManager):
    """Test sync_universe(exchange='ALL') halts if TASE benchmark download fails."""
    ingestor = DataIngestor(db_manager=tmp_db)
    with patch.object(ingestor, "download_spy", return_value=5):
        with patch.object(ingestor, "download_tase_benchmark", side_effect=RuntimeError("TA125 fail")):
            with pytest.raises(RuntimeError, match="TA125 fail"):
                ingestor.sync_universe(exchange="ALL")


# ============================================================================
# SINGLE TICKER SYNC & AUTO-DETECTION TESTS
# ============================================================================


def test_sync_single_ticker_tase(tmp_db: DatabaseManager):
    """Test sync_single_ticker sets exchange = 'TASE' for .TA tickers."""
    ingestor = DataIngestor(db_manager=tmp_db)
    dates = ["2026-08-01", "2026-08-02"]
    mock_df = make_mock_yf_df(["TEVA.TA"], dates, start_price=6500.0)

    with patch.object(ingestor, "fetch_ticker_chunk", return_value=mock_df):
        success = ingestor.sync_single_ticker("TEVA.TA")
        assert success is True

    rows = tmp_db.execute_read("SELECT ticker, exchange, asset_class FROM symbol_metadata WHERE ticker = 'TEVA.TA'")
    assert len(rows) == 1
    assert rows[0] == ("TEVA.TA", "TASE", "Common Stock")

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


def test_sync_single_ticker_lowercase_normalization(tmp_db: DatabaseManager):
    """Test sync_single_ticker normalizes lowercase ticker name and sets exchange = TASE."""
    ingestor = DataIngestor(db_manager=tmp_db)
    dates = ["2026-08-01", "2026-08-02"]
    mock_df = make_mock_yf_df(["LUMI.TA"], dates, start_price=3000.0)

    with patch.object(ingestor, "fetch_ticker_chunk", return_value=mock_df):
        success = ingestor.sync_single_ticker("lumi.ta")
        assert success is True

    rows = tmp_db.execute_read("SELECT ticker, exchange FROM symbol_metadata WHERE ticker = 'LUMI.TA'")
    assert len(rows) == 1
    assert rows[0] == ("LUMI.TA", "TASE")


# ============================================================================
# BATCH BAR INGESTION & DELTA SYNC TESTS
# ============================================================================


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


def test_sync_universe_tase_batching(tmp_db: DatabaseManager):
    """Test sync_universe chunks TASE symbols and runs batch download."""
    ingestor = DataIngestor(db_manager=tmp_db, chunk_size=2)
    sample_symbols = [
        {"ticker": "LUMI.TA", "name": "Bank Leumi", "exchange": "TASE", "asset_class": "Common Stock", "is_active": True},
        {"ticker": "POLI.TA", "name": "Bank Hapoalim", "exchange": "TASE", "asset_class": "Common Stock", "is_active": True},
        {"ticker": "NICE.TA", "name": "NICE Systems", "exchange": "TASE", "asset_class": "Common Stock", "is_active": True},
    ]

    dates = ["2026-08-01", "2026-08-02"]
    mock_df = make_mock_yf_df(["LUMI.TA", "POLI.TA"], dates)

    with patch.object(ingestor, "download_tase_benchmark", return_value=2):
        with patch.object(ingestor, "fetch_ticker_chunk", return_value=mock_df):
            summary = ingestor.sync_universe(symbols=sample_symbols, exchange="TASE")
            assert summary["status"] == "success"
            assert summary["exchange"] == "TASE"
            assert summary["total_tickers"] == 3


# ============================================================================
# CLI MULTI-EXCHANGE COMMAND TESTS
# ============================================================================


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
