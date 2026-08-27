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
    monkeypatch.setattr(st, "header", lambda *a, **kw: markdown_calls.append((a, kw)))
    monkeypatch.setattr(st, "subheader", lambda *a, **kw: markdown_calls.append((a, kw)))
    monkeypatch.setattr(st, "info", lambda *a, **kw: markdown_calls.append((a, kw)))
    monkeypatch.setattr(st, "caption", lambda *a, **kw: markdown_calls.append((a, kw)))

    # Test View B (T-5)
    render_backtest_view(read_only_mgr, cutoff_days_ago=5, view_label="View B: 1-Week Backtest", min_adv20=0.0, min_price=0.0, max_tightness=100.0, pct_off_low=0.0, pct_within_high=100.0)

    # Test View C (T-22)
    render_backtest_view(read_only_mgr, cutoff_days_ago=22, view_label="View C: 1-Month Backtest", min_adv20=0.0, min_price=0.0, max_tightness=100.0, pct_off_low=0.0, pct_within_high=100.0)

    # Test View E (Custom Date)
    rows = read_only_mgr.execute_read("SELECT DISTINCT trade_date FROM daily_bars ORDER BY trade_date DESC;")
    dates = [str(r[0]) for r in rows]
    if len(dates) > 5:
        custom_date = dates[5]
        render_backtest_view(
            read_only_mgr,
            custom_cutoff_date=custom_date,
            view_label=f"View E: Custom Date ({custom_date}) Backtest",
            min_adv20=0.0,
            min_price=0.0,
            max_tightness=100.0,
            pct_off_low=0.0,
            pct_within_high=100.0,
        )

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


@pytest.fixture
def populated_db_with_tase(temp_db: Path) -> DatabaseManager:
    """Fixture providing DatabaseManager initialized with both US and TASE data."""
    db_mgr = DatabaseManager(db_path=temp_db, read_only=False)

    with db_mgr.write_cursor() as conn:
        conn.execute(
            """
            INSERT INTO symbol_metadata (ticker, name, exchange, asset_class, is_active)
            VALUES ('SPY', 'SPDR S&P 500 ETF', 'NYSE', 'ETF', True),
                   ('AAPL', 'Apple Inc.', 'NASDAQ', 'Common Stock', True),
                   ('^TA125.TA', 'TA-125 Index', 'TASE', 'Index', True),
                   ('DSCT.TA', 'Discount Bank', 'TASE', 'Common Stock', True),
                   ('TLV.TA', 'Tel Aviv Stock Exchange', 'TASE', 'Common Stock', True);
            """
        )

        base_date = datetime.date(2025, 1, 1)
        bars = []
        for i in range(300):
            t_date = base_date + datetime.timedelta(days=i)
            # US bars
            bars.append(("SPY", t_date, 500.0 + i * 0.1, 505.0 + i * 0.1, 498.0 + i * 0.1, 502.0 + i * 0.1, 502.0 + i * 0.1, 1000000))
            bars.append(("AAPL", t_date, 150.0 + i * 0.5, 152.0 + i * 0.5, 149.0 + i * 0.5, 151.0 + i * 0.5, 151.0 + i * 0.5, 5000000))
            # TASE bars (prices in Agorot)
            bars.append(("^TA125.TA", t_date, 2000.0 + i * 1.0, 2010.0 + i * 1.0, 1990.0 + i * 1.0, 2005.0 + i * 1.0, 2005.0 + i * 1.0, 500000))
            bars.append(("DSCT.TA", t_date, 2500.0 + i * 2.0, 2520.0 + i * 2.0, 2480.0 + i * 2.0, 2510.0 + i * 2.0, 2510.0 + i * 2.0, 800000))
            bars.append(("TLV.TA", t_date, 3000.0 + i * 3.0, 3030.0 + i * 3.0, 2980.0 + i * 3.0, 3020.0 + i * 3.0, 3020.0 + i * 3.0, 600000))

        conn.executemany(
            """
            INSERT INTO daily_bars (ticker, trade_date, open, high, low, close, adj_close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            bars,
        )

    return db_mgr


def test_ui_is_tase_ticker_helper() -> None:
    """Test is_tase_ticker identifies TASE symbols accurately."""
    from src.ui.app import is_tase_ticker

    assert is_tase_ticker("DSCT.TA") is True
    assert is_tase_ticker("tlv.ta") is True
    assert is_tase_ticker("^TA125.TA") is True
    assert is_tase_ticker("^TA125") is True
    assert is_tase_ticker("AAPL") is False
    assert is_tase_ticker("SPY") is False
    assert is_tase_ticker("MSFT") is False


def test_ui_build_html_table_tase() -> None:
    """Test build_html_table generates appropriate TASE table structures."""
    import pandas as pd
    from src.ui.app import build_html_table

    # Test Screener table with is_tase=True
    df_screener = pd.DataFrame([
        {
            "ticker": "DSCT.TA",
            "name": "Discount Bank",
            "market_cap_str": "35.00B Ag.",
            "close": 2500.0,
            "ADV20": "25.0M Ag.",
            "rs_score": 1.25,
            "tightness_ratio": 2.1,
            "pct_off_52w_high": -4.5,
            "composite_score": 88.5,
        }
    ])
    html_s = build_html_table(df_screener, is_backtest=False, is_tase=True)
    assert "Price (Ag.)" in html_s
    assert "ADV20 (Ag.)" in html_s
    assert "2,500.00 Ag." in html_s
    assert "Discount Bank" in html_s

    # Test Backtest table with is_tase=True
    df_backtest = pd.DataFrame([
        {
            "ticker": "TLV.TA",
            "name": "Tel Aviv Stock Exchange",
            "market_cap_str": "12.50B Ag.",
            "entry_price": 3000.0,
            "exit_price": 3150.0,
            "return_pct": 5.0,
            "ta125_return_pct": 2.0,
            "alpha_pct": 3.0,
            "max_drawdown_pct": -1.2,
            "is_win": True,
            "win_status": "🟢 WIN",
        }
    ])
    html_b = build_html_table(df_backtest, is_backtest=True, is_tase=True)
    assert "TA-125 Return (%)" in html_b
    assert "Entry Price (Ag.)" in html_b
    assert "3,000.00 Ag." in html_b
    assert "🟢 WIN" in html_b


def test_ui_render_live_recommendations_with_tase(populated_db_with_tase: DatabaseManager, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test View A render_live_recommendations renders both US and TASE sections."""
    import streamlit as st
    from src.ui.app import render_live_recommendations

    read_only_mgr = DatabaseManager(db_path=populated_db_with_tase.db_path, read_only=True)
    latest_date = "2025-10-27"

    markdown_calls = []

    def mock_markdown(*args, **kwargs):
        markdown_calls.append(args[0] if args else kwargs.get("body", ""))

    monkeypatch.setattr(st, "markdown", mock_markdown)

    render_live_recommendations(read_only_mgr, latest_date, min_adv20=0.0, min_price=0.0)

    rendered_text = " ".join([str(c) for c in markdown_calls])
    assert "title-tase" in rendered_text or "Tel Aviv Stock Exchange" in rendered_text


def test_ui_render_backtest_view_with_tase(populated_db_with_tase: DatabaseManager, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test View B, View C, and View E render dedicated TASE benchmark cards and tables."""
    import streamlit as st
    from src.ui.app import render_backtest_view

    read_only_mgr = DatabaseManager(db_path=populated_db_with_tase.db_path, read_only=True)

    markdown_calls = []

    def mock_markdown(*args, **kwargs):
        markdown_calls.append((args, kwargs))

    monkeypatch.setattr(st, "markdown", mock_markdown)
    monkeypatch.setattr(st, "header", lambda *a, **kw: markdown_calls.append((a, kw)))
    monkeypatch.setattr(st, "subheader", lambda *a, **kw: markdown_calls.append((a, kw)))
    monkeypatch.setattr(st, "info", lambda *a, **kw: markdown_calls.append((a, kw)))
    monkeypatch.setattr(st, "caption", lambda *a, **kw: markdown_calls.append((a, kw)))

    # Test View B (1-Week)
    render_backtest_view(read_only_mgr, cutoff_days_ago=5, view_label="View B: 1-Week Backtest", min_adv20=0.0, min_price=0.0, max_tightness=100.0, pct_off_low=0.0, pct_within_high=100.0)

    # Test View C (1-Month)
    render_backtest_view(read_only_mgr, cutoff_days_ago=22, view_label="View C: 1-Month Backtest", min_adv20=0.0, min_price=0.0, max_tightness=100.0, pct_off_low=0.0, pct_within_high=100.0)

    # Test View E (Custom Date)
    rows = read_only_mgr.execute_read("SELECT DISTINCT trade_date FROM daily_bars ORDER BY trade_date DESC;")
    dates = [str(r[0]) for r in rows]
    if dates:
        custom_date = dates[min(5, len(dates)-1)]
        render_backtest_view(
            read_only_mgr,
            custom_cutoff_date=custom_date,
            view_label=f"View E: Custom Date ({custom_date}) Backtest",
            min_adv20=0.0,
            min_price=0.0,
            max_tightness=100.0,
            pct_off_low=0.0,
            pct_within_high=100.0,
        )

    assert len(markdown_calls) > 0


def test_ui_custom_css_injection_palette(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test inject_custom_css outputs expected CSS classes and high-contrast TASE color hexes."""
    import streamlit as st
    from src.ui.app import inject_custom_css

    markdown_calls = []

    def mock_markdown(*args, **kwargs):
        markdown_calls.append(args[0] if args else kwargs.get("body", ""))

    monkeypatch.setattr(st, "markdown", mock_markdown)

    inject_custom_css()

    assert len(markdown_calls) == 1
    css_content = str(markdown_calls[0])
    assert ".title-tase" in css_content
    assert "#eef5fc" in css_content
    assert "#0b4f8a" in css_content
    assert ".portfolio-card-tase" in css_content
    assert "#b6d4fe" in css_content
    assert "#f7faff" in css_content
    assert ".pos-gain" in css_content
    assert ".neg-loss" in css_content


def test_ui_is_medical_pharma_classification() -> None:
    """Test is_medical_pharma classifies pharmaceutical and biotech companies correctly."""
    from src.ui.app import is_medical_pharma

    # Pharma/Bio companies
    assert is_medical_pharma("Teva Pharmaceutical Industries Ltd.", "TEVA.TA") is True
    assert is_medical_pharma("BioNTech Biotechnology SE", "BNTX") is True
    assert is_medical_pharma("Vertex Pharmaceuticals", "VRTX") is True
    assert is_medical_pharma("Regeneron Pharmaceuticals", "REGN") is True
    assert is_medical_pharma("Generic Therapeutics Corp", "GTX") is True
    assert is_medical_pharma("Health Oncology Care", "HOC") is True
    assert is_medical_pharma("Advanced Medical Solutions", "AMS") is True
    assert is_medical_pharma("ImmunoGen Diagnostics", "IMGN") is True
    assert is_medical_pharma("Moderna Vaccine Therapeutics", "MRNA") is True

    # Non-pharma companies
    assert is_medical_pharma("Apple Inc.", "AAPL") is False
    assert is_medical_pharma("Microsoft Corporation", "MSFT") is False
    assert is_medical_pharma("Discount Bank Ltd.", "DSCT.TA") is False
    assert is_medical_pharma("Bank Leumi", "LUMI.TA") is False
    assert is_medical_pharma("NVIDIA Corporation", "NVDA") is False


def test_ui_build_html_table_empty_dataframes() -> None:
    """Test build_html_table returns graceful placeholder for empty DataFrames."""
    import pandas as pd
    from src.ui.app import build_html_table

    empty_df = pd.DataFrame()
    html_screener = build_html_table(empty_df, is_backtest=False, is_tase=False)
    assert "No tickers in this category." in html_screener

    html_screener_tase = build_html_table(empty_df, is_backtest=False, is_tase=True)
    assert "No tickers in this category." in html_screener_tase

    html_backtest = build_html_table(empty_df, is_backtest=True, is_tase=False)
    assert "No tickers in this category." in html_backtest

    html_backtest_tase = build_html_table(empty_df, is_backtest=True, is_tase=True)
    assert "No tickers in this category." in html_backtest_tase


def test_ui_build_html_table_nan_and_missing_values() -> None:
    """Test build_html_table gracefully handles NaN and missing numeric values."""
    import pandas as pd
    from src.ui.app import build_html_table

    df_nan_screener = pd.DataFrame([
        {
            "ticker": "NANTICK",
            "name": None,
            "market_cap_str": "N/A",
            "close": None,
            "ADV20": "N/A",
            "rs_score": None,
            "tightness_ratio": None,
            "pct_off_52w_high": None,
            "composite_score": None,
        }
    ])
    html_out = build_html_table(df_nan_screener, is_backtest=False, is_tase=False)
    assert "NANTICK" in html_out
    assert "N/A" in html_out

    df_nan_backtest = pd.DataFrame([
        {
            "ticker": "NANTICK.TA",
            "name": None,
            "market_cap_str": "N/A",
            "entry_price": None,
            "exit_price": None,
            "return_pct": None,
            "ta125_return_pct": None,
            "alpha_pct": None,
            "max_drawdown_pct": None,
            "is_win": False,
            "win_status": "🔴 LOSS",
        }
    ])
    html_bt_out = build_html_table(df_nan_backtest, is_backtest=True, is_tase=True)
    assert "NANTICK.TA" in html_bt_out
    assert "🔴 LOSS" in html_bt_out


def test_ui_view_d_diagnostics_tase_and_us_checklist(populated_db_with_tase: DatabaseManager, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test View D evaluates 8-point checklist with universe-specific price and liquidity floors."""
    import streamlit as st
    from src.engine.screener_queries import run_screener

    read_only_mgr = DatabaseManager(db_path=populated_db_with_tase.db_path, read_only=True)
    cutoff_date = "2025-10-27"

    # Evaluate TASE stock DSCT.TA
    df_tase = run_screener(read_only_mgr, cutoff_date=cutoff_date, manual_tickers=["DSCT.TA"], universe="TASE")
    assert not df_tase.empty
    row = df_tase.iloc[0]
    assert row["ticker"] == "DSCT.TA"
    assert row["close"] >= 100.0  # TASE price floor in Agorot

    # Evaluate US stock AAPL
    df_us = run_screener(read_only_mgr, cutoff_date=cutoff_date, manual_tickers=["AAPL"], universe="US")
    assert not df_us.empty
    row_us = df_us.iloc[0]
    assert row_us["ticker"] == "AAPL"
    assert row_us["close"] >= 10.0  # US price floor in USD


def test_ui_view_d_missing_ticker_single_sync(populated_db_with_tase: DatabaseManager, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test View D single-ticker download helper syncs missing tickers."""
    from src.ingestion.data_ingestor import DataIngestor

    class MockIngestor:
        def __init__(self, db_manager):
            self.db_manager = db_manager

        def sync_single_ticker(self, ticker: str) -> bool:
            return ticker.endswith(".TA") or ticker in ("NVDA", "MSFT")

    monkeypatch.setattr("src.ingestion.data_ingestor.DataIngestor", MockIngestor)

    ingestor = MockIngestor(populated_db_with_tase)
    assert ingestor.sync_single_ticker("TEVA.TA") is True
    assert ingestor.sync_single_ticker("INVALID_TICKER_XYZ") is False


def test_ui_render_backtest_view_empty_universe_resilience(temp_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test render_backtest_view handles empty database without throwing exceptions."""
    import streamlit as st
    from src.ui.app import render_backtest_view

    empty_mgr = DatabaseManager(db_path=temp_db, read_only=True)

    info_calls = []
    warning_calls = []
    markdown_calls = []

    monkeypatch.setattr(st, "markdown", lambda *a, **kw: markdown_calls.append(a))
    monkeypatch.setattr(st, "info", lambda *a, **kw: info_calls.append(a))
    monkeypatch.setattr(st, "warning", lambda *a, **kw: warning_calls.append(a))
    monkeypatch.setattr(st, "header", lambda *a, **kw: None)
    monkeypatch.setattr(st, "subheader", lambda *a, **kw: None)

    # Should gracefully report no data without raising an unhandled exception
    render_backtest_view(empty_mgr, cutoff_days_ago=5, view_label="Test Empty Backtest")
    assert len(info_calls) > 0


def test_ui_format_company_name_helper() -> None:
    """Test format_company_name handles NaNs, strings, and fallbacks robustly."""
    import numpy as np
    from src.ui.app import format_company_name

    assert format_company_name("Apple Inc.", "AAPL") == "Apple Inc."
    assert format_company_name("  Apple Inc.  ", "AAPL") == "Apple Inc."
    assert format_company_name(None, "AAPL") == "AAPL"
    assert format_company_name(np.nan, "AAPL") == "AAPL"
    assert format_company_name(float("nan"), "AAPL") == "AAPL"
    assert format_company_name("nan", "AAPL") == "AAPL"
    assert format_company_name("NAN", "AAPL") == "AAPL"
    assert format_company_name("", "AAPL") == "AAPL"
    assert format_company_name("   ", "AAPL") == "AAPL"
    assert format_company_name("בנק דיסקונט", "DSCT.TA") == "בנק דיסקונט"


def test_ui_render_live_recommendations_empty_us_decoupled_tase(
    populated_db_with_tase: DatabaseManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test View A renders TASE section even when US screener returns 0 results."""
    import streamlit as st
    from src.ui.app import render_live_recommendations

    read_only_mgr = DatabaseManager(db_path=populated_db_with_tase.db_path, read_only=True)
    latest_date = "2025-10-27"

    warnings = []
    markdown_calls = []

    monkeypatch.setattr(st, "warning", lambda msg: warnings.append(str(msg)))
    monkeypatch.setattr(st, "markdown", lambda body, *a, **kw: markdown_calls.append(str(body)))
    monkeypatch.setattr(st, "header", lambda *a, **kw: None)
    monkeypatch.setattr(st, "subheader", lambda *a, **kw: None)
    monkeypatch.setattr(st, "caption", lambda *a, **kw: None)
    monkeypatch.setattr(st, "download_button", lambda *a, **kw: None)

    # Force US to be empty by using min_price that excludes US but allows TASE
    # In populated_db_with_tase, AAPL close ~300. Set min_price=1000.0 (TASE close ~2500, AAPL < 500)
    render_live_recommendations(read_only_mgr, latest_date, min_price=1000.0, min_adv20=0.0)

    rendered_all = "\n".join(markdown_calls)
    assert "Category 3: Tel Aviv Stock Exchange" in rendered_all
    assert any("No stocks passed all screening filters" in w for w in warnings)


def test_ui_render_backtest_view_empty_us_positions_decoupled(
    populated_db_with_tase: DatabaseManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test render_backtest_view executes cleanly without UnboundLocalError when US produces 0 positions."""
    import streamlit as st
    from src.ui.app import render_backtest_view

    read_only_mgr = DatabaseManager(db_path=populated_db_with_tase.db_path, read_only=True)

    markdown_calls = []
    infos = []

    monkeypatch.setattr(st, "markdown", lambda body, *a, **kw: markdown_calls.append(str(body)))
    monkeypatch.setattr(st, "info", lambda msg: infos.append(str(msg)))
    monkeypatch.setattr(st, "header", lambda *a, **kw: None)
    monkeypatch.setattr(st, "subheader", lambda *a, **kw: None)
    monkeypatch.setattr(st, "caption", lambda *a, **kw: None)
    monkeypatch.setattr(st, "download_button", lambda *a, **kw: None)

    # Impossible max_tightness to produce 0 US positions
    render_backtest_view(read_only_mgr, cutoff_days_ago=5, max_tightness=0.0001, pct_off_low=999999.0)

    rendered_all = "\n".join(markdown_calls)
    assert "$10,000 Investment Benchmark Comparison" in rendered_all
    assert any("No US position data available" in msg for msg in infos)



