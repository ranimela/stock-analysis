"""Unit tests for Data Ingestion module."""

from __future__ import annotations

import datetime
from unittest.mock import MagicMock, patch

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


@pytest.fixture
def tmp_db(tmp_path) -> DatabaseManager:
    """Fixture providing a temporary DatabaseManager instance."""
    db_file = tmp_path / "test_market_data.duckdb"
    return DatabaseManager(db_file)


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
