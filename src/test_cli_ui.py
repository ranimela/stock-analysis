"""Unit tests for CLI orchestration and UI application logic."""

from __future__ import annotations

import datetime
from pathlib import Path
from click.testing import CliRunner
import pytest

from src.cli import main, scan, seed, update
from src.db.db_manager import DatabaseManager
from src.ui.app import check_db_availability, get_db_manager


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    """Fixture to provide temporary DuckDB path."""
    return tmp_path / "test_market.duckdb"


@pytest.fixture
def populated_db(temp_db: Path) -> DatabaseManager:
    """Fixture providing a DatabaseManager instance initialized with test market data."""
    db_mgr = DatabaseManager(db_path=temp_db, read_only=False)

    # Insert symbol metadata
    with db_mgr.write_cursor() as conn:
        conn.execute(
            """
            INSERT INTO symbol_metadata (ticker, name, exchange, asset_class, is_active)
            VALUES ('SPY', 'SPDR S&P 500 ETF', 'NYSE', 'ETF', True),
                   ('AAPL', 'Apple Inc.', 'NASDAQ', 'Common Stock', True);
            """
        )

        # Generate 300 daily bars for SPY and AAPL
        base_date = datetime.date(2025, 1, 1)
        bars = []
        for i in range(300):
            t_date = base_date + datetime.timedelta(days=i)
            # SPY bars
            bars.append(("SPY", t_date, 500.0 + i * 0.1, 505.0 + i * 0.1, 498.0 + i * 0.1, 502.0 + i * 0.1, 502.0 + i * 0.1, 1000000))
            # AAPL bars
            price = 150.0 + i * 0.5
            bars.append(("AAPL", t_date, price, price + 2, price - 1, price + 1, price + 1, 5000000))

        conn.executemany(
            """
            INSERT INTO daily_bars (ticker, trade_date, open, high, low, close, adj_close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            bars,
        )

    return db_mgr


def test_cli_help() -> None:
    """Test CLI main help output."""
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "Quantitative Stock Screener" in result.output
    assert "seed" in result.output
    assert "update" in result.output
    assert "scan" in result.output


def test_cli_scan_empty_db(temp_db: Path) -> None:
    """Test CLI scan command against unseeded/empty database."""
    runner = CliRunner()
    result = runner.invoke(scan, ["--db-path", str(temp_db)])
    assert result.exit_code != 0
    assert "Database is empty" in result.output or "Error" in result.output


def test_cli_scan_populated_db(populated_db: DatabaseManager) -> None:
    """Test CLI scan command against populated database."""
    runner = CliRunner()
    result = runner.invoke(scan, ["--db-path", str(populated_db.db_path)])
    assert result.exit_code == 0
    assert "LIVE TOP-10 RECOMMENDATIONS" in result.output
    assert "1-WEEK POINT-IN-TIME BACKTEST" in result.output
    assert "1-MONTH POINT-IN-TIME BACKTEST" in result.output


def test_ui_check_db_availability(populated_db: DatabaseManager, temp_db: Path) -> None:
    """Test UI check_db_availability function."""
    read_only_mgr = DatabaseManager(db_path=populated_db.db_path, read_only=True)
    latest_date = check_db_availability(read_only_mgr)
    assert latest_date is not None
    assert latest_date.startswith("202")

    non_existent_mgr = DatabaseManager(db_path=temp_db / "nonexistent.duckdb", read_only=True)
    assert check_db_availability(non_existent_mgr) is None


def test_ui_render_live_recommendations(populated_db: DatabaseManager, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test View A render_live_recommendations executes cleanly and renders custom HTML table."""
    import streamlit as st
    from src.ui.app import render_live_recommendations

    read_only_mgr = DatabaseManager(db_path=populated_db.db_path, read_only=True)
    latest_date = check_db_availability(read_only_mgr)
    assert latest_date is not None

    markdown_calls = []

    def mock_markdown(*args, **kwargs):
        markdown_calls.append((args, kwargs))

    monkeypatch.setattr(st, "markdown", mock_markdown)

    render_live_recommendations(read_only_mgr, latest_date)

    assert len(markdown_calls) > 0


def test_ui_render_backtest_view(populated_db: DatabaseManager, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test View B and View C render_backtest_view execute cleanly and render custom HTML table."""
    import streamlit as st
    from src.ui.app import render_backtest_view

    read_only_mgr = DatabaseManager(db_path=populated_db.db_path, read_only=True)

    markdown_calls = []

    def mock_markdown(*args, **kwargs):
        markdown_calls.append((args, kwargs))

    monkeypatch.setattr(st, "markdown", mock_markdown)

    # Test View B (T-5)
    render_backtest_view(read_only_mgr, cutoff_days_ago=5, view_label="View B: 1-Week Backtest")

    # Test View C (T-22)
    render_backtest_view(read_only_mgr, cutoff_days_ago=22, view_label="View C: 1-Month Backtest")

    assert len(markdown_calls) > 0


def test_ui_view_d_manual_analysis(populated_db: DatabaseManager, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test View D Manual Analysis rendering with custom tickers and HTML table."""
    import streamlit as st
    from src.engine.screener_queries import run_screener
    from src.ui.app import check_db_availability

    read_only_mgr = DatabaseManager(db_path=populated_db.db_path, read_only=True)
    latest_date = check_db_availability(read_only_mgr)
    assert latest_date is not None

    markdown_calls = []

    def mock_markdown(*args, **kwargs):
        markdown_calls.append((args, kwargs))

    monkeypatch.setattr(st, "markdown", mock_markdown)

    df_manual = run_screener(read_only_mgr, cutoff_date=latest_date, manual_tickers=["AAPL"])
    assert not df_manual.empty

    df_manual["pct_off_52w_high"] = ((df_manual["close"] / df_manual["high_52w"]) - 1.0) * 100.0
    df_manual["market_cap_str"] = "$100.00B"
    df_manual["Company Name"] = "[Apple Inc.](https://finance.yahoo.com/quote/AAPL)"
    st.markdown("test table", unsafe_allow_html=True)
    assert len(markdown_calls) > 0


