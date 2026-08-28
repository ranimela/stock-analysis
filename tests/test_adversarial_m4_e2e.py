"""Tier 5 Adversarial Coverage Hardening Test Suite (Milestone 4 E2E).

Comprehensive white-box adversarial stress tests covering:
1. Cross-Market Trading Calendar Differences (TASE Sun-Thu vs US Mon-Fri) & Alignment.
2. Trading Holiday Gaps & Boundary Calendar Conditions.
3. Benchmark Hard-Gating & Degradation Handling (^TA125.TA and SPY).
4. Ingestion Data Normalization, MultiIndex parsing, and Delta Sync edge cases.
5. Extreme / Illiquid / Zero-Volume / Flat-Price Data Anomalies.
6. Screener Boundary Thresholds & Single-Stock Qualifying Pools.
7. Currency Formatting (Agorot 'Ag.' vs USD '$') and High-Contrast CSS Styling.
8. UI Component Formatting, Sector Classification, and Edge String Sanitization.
9. Multi-Exchange CLI Flag Combinations and Subcommands (--exchange TASE/US/ALL).
10. CLI Error Handling and Edge Subcommand Permutations.
11. End-to-End Streamlit Application Rendering across Views A, B, C, D, and E.
12. Concurrency, Database Safety, and Idempotency.

Author: Challenger M4.1
Project: Tel Aviv Stock Exchange (TA-125) Integration
"""

from __future__ import annotations

import datetime
from pathlib import Path
import tempfile
from typing import Any
from unittest.mock import MagicMock, patch

from click.testing import CliRunner
import pandas as pd
import pytest

from src.cli import export_delta, main, scan, seed, sync_delta, update
from src.db.db_manager import DatabaseManager
from src.engine.backtest_engine import run_point_in_time_backtest
from src.engine.screener_queries import run_screener
from src.ingestion.data_ingestor import DataIngestor
from src.ingestion.symbol_directory import (
    clean_company_name,
    is_common_stock,
    parse_nasdaqlisted,
    parse_otherlisted,
    sync_symbol_metadata,
)
from src.ingestion.tase_directory import (
    TASE_BENCHMARK,
    fetch_tase_symbols,
    get_tase_symbol_directory,
    get_tase_symbols,
    is_tase_ticker,
    normalize_tase_ticker,
)
from src.ui.app import (
    build_html_table,
    check_db_availability,
    format_company_name,
    inject_custom_css,
    is_medical_pharma,
    render_backtest_view,
    render_live_recommendations,
)


# ============================================================================
# Shared Pytest Fixtures
# ============================================================================

@pytest.fixture
def temp_db_mgr(tmp_path: Path) -> DatabaseManager:
    """Provides a fresh isolated DatabaseManager instance in a temporary folder."""
    db_file = tmp_path / "test_adversarial_m4.duckdb"
    return DatabaseManager(db_path=db_file, read_only=False)


@pytest.fixture
def dual_calendar_db(temp_db_mgr: DatabaseManager) -> DatabaseManager:
    """Populates database with authentic calendar-divergent US (Mon-Fri) and TASE (Sun-Thu) data.

    Spans 320 calendar days (approx 210 trading days per market).
    TASE trades Sunday-Thursday. US trades Monday-Friday.
    """
    db_mgr = temp_db_mgr

    with db_mgr.write_cursor() as conn:
        conn.execute(
            """
            INSERT INTO symbol_metadata (ticker, name, exchange, asset_class, is_active, market_cap)
            VALUES
                ('SPY', 'SPDR S&P 500 ETF Trust', 'NYSE', 'ETF', True, 500000000000.0),
                ('AAPL', 'Apple Inc.', 'NASDAQ', 'Common Stock', True, 3000000000000.0),
                ('NVDA', 'NVIDIA Corporation', 'NASDAQ', 'Common Stock', True, 2800000000000.0),
                ('PFE', 'Pfizer Inc.', 'NYSE', 'Common Stock', True, 160000000000.0),
                ('MRNA', 'Moderna Therapeutics', 'NASDAQ', 'Common Stock', True, 45000000000.0),
                ('^TA125.TA', 'TA-125 Index Benchmark', 'TASE', 'Index', True, 0.0),
                ('DSCT.TA', 'Israel Discount Bank Ltd', 'TASE', 'Common Stock', True, 35000000000.0),
                ('LUMI.TA', 'Bank Leumi Le-Israel B.M.', 'TASE', 'Common Stock', True, 40000000000.0),
                ('POLI.TA', 'Bank Hapoalim B.M.', 'TASE', 'Common Stock', True, 42000000000.0),
                ('TEVA.TA', 'Teva Pharmaceutical Industries Ltd.', 'TASE', 'Common Stock', True, 55000000000.0),
                ('ICL.TA', 'ICL Group Ltd.', 'TASE', 'Common Stock', True, 25000000000.0),
                ('NICE.TA', 'NICE Ltd.', 'TASE', 'Common Stock', True, 30000000000.0);
            """
        )

        base_date = datetime.date(2025, 1, 1)
        bars: list[tuple[str, datetime.date, float, float, float, float, float, int]] = []

        for day_offset in range(320):
            cur_date = base_date + datetime.timedelta(days=day_offset)
            weekday = cur_date.weekday()  # Monday is 0, Sunday is 6

            # US Market: Monday (0) through Friday (4)
            if weekday in (0, 1, 2, 3, 4):
                growth_factor = 1.0 + (day_offset * 0.0015)
                bars.append(("SPY", cur_date, 500.0 * growth_factor, 503.0 * growth_factor, 497.0 * growth_factor, 501.0 * growth_factor, 501.0 * growth_factor, 80000000))
                bars.append(("AAPL", cur_date, 150.0 * (growth_factor**1.2), 152.0 * (growth_factor**1.2), 149.0 * (growth_factor**1.2), 151.0 * (growth_factor**1.2), 151.0 * (growth_factor**1.2), 50000000))
                bars.append(("NVDA", cur_date, 100.0 * (growth_factor**1.4), 103.0 * (growth_factor**1.4), 99.0 * (growth_factor**1.4), 102.0 * (growth_factor**1.4), 102.0 * (growth_factor**1.4), 60000000))
                bars.append(("PFE", cur_date, 30.0 * growth_factor, 30.5 * growth_factor, 29.5 * growth_factor, 30.0 * growth_factor, 30.0 * growth_factor, 20000000))
                bars.append(("MRNA", cur_date, 80.0 * (growth_factor**1.3), 82.0 * (growth_factor**1.3), 79.0 * (growth_factor**1.3), 81.0 * (growth_factor**1.3), 81.0 * (growth_factor**1.3), 15000000))

            # TASE Market: Sunday (6) through Thursday (3)
            if weekday in (6, 0, 1, 2, 3):
                tase_growth = 1.0 + (day_offset * 0.0018)
                bars.append(("^TA125.TA", cur_date, 2000.0 * tase_growth, 2015.0 * tase_growth, 1990.0 * tase_growth, 2005.0 * tase_growth, 2005.0 * tase_growth, 25000000))
                bars.append(("DSCT.TA", cur_date, 2500.0 * (tase_growth**1.25), 2530.0 * (tase_growth**1.25), 2480.0 * (tase_growth**1.25), 2510.0 * (tase_growth**1.25), 2510.0 * (tase_growth**1.25), 18000000))
                bars.append(("LUMI.TA", cur_date, 3200.0 * (tase_growth**1.3), 3240.0 * (tase_growth**1.3), 3180.0 * (tase_growth**1.3), 3220.0 * (tase_growth**1.3), 3220.0 * (tase_growth**1.3), 22000000))
                bars.append(("POLI.TA", cur_date, 3500.0 * (tase_growth**1.2), 3540.0 * (tase_growth**1.2), 3480.0 * (tase_growth**1.2), 3520.0 * (tase_growth**1.2), 3520.0 * (tase_growth**1.2), 24000000))
                bars.append(("TEVA.TA", cur_date, 6000.0 * (tase_growth**1.35), 6080.0 * (tase_growth**1.35), 5950.0 * (tase_growth**1.35), 6040.0 * (tase_growth**1.35), 6040.0 * (tase_growth**1.35), 30000000))
                bars.append(("ICL.TA", cur_date, 1800.0 * (tase_growth**1.15), 1825.0 * (tase_growth**1.15), 1780.0 * (tase_growth**1.15), 1810.0 * (tase_growth**1.15), 1810.0 * (tase_growth**1.15), 15000000))
                bars.append(("NICE.TA", cur_date, 7000.0 * (tase_growth**1.4), 7100.0 * (tase_growth**1.4), 6950.0 * (tase_growth**1.4), 7050.0 * (tase_growth**1.4), 7050.0 * (tase_growth**1.4), 16000000))

        conn.executemany(
            """
            INSERT INTO daily_bars (ticker, trade_date, open, high, low, close, adj_close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            bars,
        )

    return db_mgr


# ============================================================================
# Test Class 1: Cross-Market Calendar & Alignment
# ============================================================================

class TestCalendarDifferencesAndCrossMarketAlignment:
    """Stress tests calendar divergence: TASE (Sun-Thu) vs US (Mon-Fri)."""

    def test_tase_sunday_bar_and_us_friday_bar_coexistence(self, dual_calendar_db: DatabaseManager) -> None:
        """Verify that Sunday bars exist for TASE equities and Friday bars exist for US equities without collision."""
        rows_sun = dual_calendar_db.execute_read(
            "SELECT DISTINCT ticker FROM daily_bars WHERE EXTRACT(dow FROM trade_date) = 0;"
        )
        sun_tickers = {r[0] for r in rows_sun}
        assert "^TA125.TA" in sun_tickers
        assert "DSCT.TA" in sun_tickers
        assert "SPY" not in sun_tickers
        assert "AAPL" not in sun_tickers

        rows_fri = dual_calendar_db.execute_read(
            "SELECT DISTINCT ticker FROM daily_bars WHERE EXTRACT(dow FROM trade_date) = 5;"
        )
        fri_tickers = {r[0] for r in rows_fri}
        assert "SPY" in fri_tickers
        assert "AAPL" in fri_tickers
        assert "^TA125.TA" not in fri_tickers
        assert "DSCT.TA" not in fri_tickers

    def test_pit_backtest_aligns_strictly_to_exchange_trading_calendar(self, dual_calendar_db: DatabaseManager) -> None:
        """Verify run_point_in_time_backtest uses the benchmark's calendar for T-5 / T-22 calculations."""
        us_bt = run_point_in_time_backtest(dual_calendar_db, cutoff_days_ago=5, universe="US")
        assert us_bt["universe"] == "US"
        assert us_bt["benchmark_ticker"] == "SPY"
        us_eval_date = datetime.date.fromisoformat(str(us_bt["evaluation_date"]))
        assert us_eval_date.weekday() != 6

        tase_bt = run_point_in_time_backtest(dual_calendar_db, cutoff_days_ago=5, universe="TASE")
        assert tase_bt["universe"] == "TASE"
        assert tase_bt["benchmark_ticker"] == "^TA125.TA"
        tase_eval_date = datetime.date.fromisoformat(str(tase_bt["evaluation_date"]))
        assert tase_eval_date.weekday() != 4

    def test_custom_cutoff_date_snapping_per_calendar(self, dual_calendar_db: DatabaseManager) -> None:
        """Verify custom dates on market holidays/weekends snap to the latest prior trading date for that market."""
        sun_row = dual_calendar_db.execute_read(
            "SELECT MAX(trade_date) FROM daily_bars WHERE EXTRACT(dow FROM trade_date) = 0;"
        )
        assert sun_row and sun_row[0][0]
        sunday_str = str(sun_row[0][0])

        tase_bt = run_point_in_time_backtest(dual_calendar_db, custom_cutoff_date=sunday_str, universe="TASE")
        assert tase_bt["cutoff_date"] == sunday_str

        us_bt = run_point_in_time_backtest(dual_calendar_db, custom_cutoff_date=sunday_str, universe="US")
        snapped_us_date = datetime.date.fromisoformat(str(us_bt["cutoff_date"]))
        assert snapped_us_date < datetime.date.fromisoformat(sunday_str)
        assert snapped_us_date.weekday() == 4

    def test_simultaneous_screener_execution_at_market_divergence(self, dual_calendar_db: DatabaseManager) -> None:
        """Verify run_screener for US and TASE independently execute on latest dates without cross-contamination."""
        df_us = run_screener(dual_calendar_db, universe="US")
        df_tase = run_screener(dual_calendar_db, universe="TASE")

        assert not df_us.empty
        assert not df_tase.empty

        assert all(not str(t).endswith(".TA") for t in df_us["ticker"])
        assert all(str(t).endswith(".TA") for t in df_tase["ticker"])


# ============================================================================
# Test Class 2: Trading Holiday Gaps & Boundary Calendar Conditions
# ============================================================================

class TestTradingHolidayGapsAndCalendarAnomalies:
    """Stress tests holiday gaps, boundary dates, and missing trading bars."""

    def test_backtest_with_date_prior_to_dataset_raises_informative_error(self, dual_calendar_db: DatabaseManager) -> None:
        """Verify requesting backtest cutoff date earlier than dataset range raises ValueError with date bounds."""
        with pytest.raises(ValueError, match="prior to available"):
            run_point_in_time_backtest(dual_calendar_db, custom_cutoff_date="2020-01-01", universe="TASE")

    def test_backtest_with_insufficient_history_raises_error(self, temp_db_mgr: DatabaseManager) -> None:
        """Verify backtest on a database with fewer trading dates than cutoff_days_ago raises ValueError."""
        with temp_db_mgr.write_cursor() as conn:
            conn.execute("INSERT INTO symbol_metadata (ticker, name, exchange) VALUES ('^TA125.TA', 'TA125', 'TASE');")
            conn.execute("INSERT INTO daily_bars (ticker, trade_date, close, open, high, low, adj_close, volume) VALUES ('^TA125.TA', '2025-01-02', 2000.0, 2000.0, 2000.0, 2000.0, 2000.0, 1000);")
            conn.execute("INSERT INTO daily_bars (ticker, trade_date, close, open, high, low, adj_close, volume) VALUES ('^TA125.TA', '2025-01-05', 2010.0, 2010.0, 2010.0, 2010.0, 2010.0, 1000);")

        with pytest.raises(ValueError, match="Insufficient historical dates"):
            run_point_in_time_backtest(temp_db_mgr, cutoff_days_ago=5, universe="TASE")


# ============================================================================
# Test Class 3: Benchmark Hard-Gating & Ingestion Degradation
# ============================================================================

class TestBenchmarkGatingAndDegradation:
    """Stress tests benchmark hard-gating, failure modes, and metadata enforcement."""

    def test_download_benchmark_hard_gate_failure_aborts(self, temp_db_mgr: DatabaseManager) -> None:
        """Verify download_benchmark raises RuntimeError when yfinance returns empty DataFrame."""
        ingestor = DataIngestor(db_manager=temp_db_mgr)

        with patch("yfinance.download", return_value=pd.DataFrame()):
            with pytest.raises(RuntimeError, match="benchmark download failed"):
                ingestor.download_benchmark("SPY")

            with pytest.raises(RuntimeError, match="benchmark download failed"):
                ingestor.download_benchmark("^TA125.TA")

    def test_sync_universe_stops_immediately_if_tase_benchmark_fails(self, temp_db_mgr: DatabaseManager) -> None:
        """Verify sync_universe(exchange='TASE') aborts without inserting constituent tickers if benchmark fails."""
        ingestor = DataIngestor(db_manager=temp_db_mgr)

        with patch("yfinance.download", side_effect=RuntimeError("Yahoo Rate Limited")):
            with pytest.raises(RuntimeError, match="Yahoo Rate Limited"):
                ingestor.sync_universe(exchange="TASE")

        count = temp_db_mgr.execute_read("SELECT COUNT(*) FROM daily_bars;")[0][0]
        assert count == 0

    def test_benchmark_metadata_registration(self, temp_db_mgr: DatabaseManager) -> None:
        """Verify benchmark metadata is accurately stored in symbol_metadata for SPY and ^TA125.TA."""
        ingestor = DataIngestor(db_manager=temp_db_mgr)
        fake_df = pd.DataFrame(
            {"Close": [500.0], "Open": [499.0], "High": [502.0], "Low": [498.0], "Volume": [1000000]},
            index=[pd.Timestamp("2025-01-02")],
        )

        with patch("yfinance.download", return_value=fake_df):
            ingestor.download_spy()
            ingestor.download_tase_benchmark()

        meta_spy = temp_db_mgr.execute_read("SELECT name, exchange, asset_class FROM symbol_metadata WHERE ticker = 'SPY';")
        assert meta_spy[0] == ("SPDR S&P 500 ETF Trust", "NYSE", "ETF")

        meta_ta = temp_db_mgr.execute_read("SELECT name, exchange, asset_class FROM symbol_metadata WHERE ticker = '^TA125.TA';")
        assert meta_ta[0] == ("TA-125 Index", "TASE", "Index")

    def test_single_ticker_sync_infers_tase_exchange(self, temp_db_mgr: DatabaseManager) -> None:
        """Verify sync_single_ticker tags .TA symbols with exchange='TASE'."""
        ingestor = DataIngestor(db_manager=temp_db_mgr)
        fake_df = pd.DataFrame(
            {"Close": [2500.0], "Open": [2490.0], "High": [2520.0], "Low": [2480.0], "Volume": [5000000]},
            index=[pd.Timestamp("2025-01-02")],
        )

        with patch.object(ingestor, "fetch_ticker_chunk", return_value=fake_df):
            ok = ingestor.sync_single_ticker("LUMI.TA")
            assert ok is True

        meta = temp_db_mgr.execute_read("SELECT exchange, asset_class FROM symbol_metadata WHERE ticker = 'LUMI.TA';")
        assert meta[0] == ("TASE", "Common Stock")


# ============================================================================
# Test Class 4: Ingestion Normalization & Edge Data Parsing
# ============================================================================

class TestIngestionNormalizationAndParsing:
    """Stress tests ticker normalization, common stock classification, and directory parsing."""

    def test_normalize_tase_ticker_variations(self) -> None:
        """Verify normalize_tase_ticker handles lower/mixed case and benchmark symbols."""
        assert normalize_tase_ticker("teva") == "TEVA.TA"
        assert normalize_tase_ticker("teva.ta") == "TEVA.TA"
        assert normalize_tase_ticker("TEVA.TA") == "TEVA.TA"
        assert normalize_tase_ticker("^TA125.TA") == "^TA125.TA"
        assert normalize_tase_ticker("^TA125") == "^TA125.TA"
        assert normalize_tase_ticker("lumi") == "LUMI.TA"

    def test_is_tase_ticker_edge_cases(self) -> None:
        """Verify is_tase_ticker handles empty, None, and varied symbol formats."""
        assert is_tase_ticker("LUMI.TA") is True
        assert is_tase_ticker("lumi.ta") is True
        assert is_tase_ticker("^TA125.TA") is True
        assert is_tase_ticker("AAPL") is False
        assert is_tase_ticker("") is False
        assert is_tase_ticker("SPY") is False

    def test_common_stock_filtering_exclusions(self) -> None:
        """Verify is_common_stock filters out warrants, ETFs, units, and preferred shares."""
        assert is_common_stock("AAPL", "Apple Inc.") is True
        assert is_common_stock("SPY", "SPDR S&P 500 ETF Trust") is False
        assert is_common_stock("TEST-W", "Acquisition Corp Warrants") is False
        assert is_common_stock("TEST-U", "Acquisition Corp Units") is False
        assert is_common_stock("TEST-P", "Preferred Series A") is False
        assert is_common_stock("ZVV", "Test Ticker ZVV") is False

    def test_clean_company_name_sanitization(self) -> None:
        """Verify clean_company_name strips exchange suffixes."""
        assert clean_company_name("Apple Inc. - Common Stock") == "Apple Inc."
        assert clean_company_name("Tesla Inc. Common Stock Par Value $0.001") == "Tesla Inc."
        assert clean_company_name("BioLineRx Ltd. - American Depositary Shares") == "BioLineRx Ltd."


# ============================================================================
# Test Class 5: Extreme Market Data & Illiquid / Flat-Price Bars
# ============================================================================

class TestExtremeMarketDataAndIlliquidBars:
    """Stress tests edge conditions: zero volume, completely flat price, penny stocks, extreme volatility."""

    def test_zero_volume_bars_do_not_cause_division_by_zero(self, temp_db_mgr: DatabaseManager) -> None:
        """Verify stocks with 0 volume across all bars calculate indicators without SQL zero-division error."""
        with temp_db_mgr.write_cursor() as conn:
            conn.execute("INSERT INTO symbol_metadata (ticker, name, exchange, asset_class, is_active) VALUES ('ZERO.TA', 'Zero Vol Corp', 'TASE', 'Common Stock', True);")
            conn.execute("INSERT INTO symbol_metadata (ticker, name, exchange, asset_class, is_active) VALUES ('^TA125.TA', 'TA125', 'TASE', 'Index', True);")

            base_d = datetime.date(2025, 1, 1)
            bars = []
            for i in range(270):
                d = base_d + datetime.timedelta(days=i)
                bars.append(("^TA125.TA", d, 2000.0 + i, 2010.0 + i, 1990.0 + i, 2005.0 + i, 2005.0 + i, 1000000))
                bars.append(("ZERO.TA", d, 100.0 + i * 2, 102.0 + i * 2, 99.0 + i * 2, 101.0 + i * 2, 101.0 + i * 2, 0))

            conn.executemany("INSERT INTO daily_bars (ticker, trade_date, open, high, low, close, adj_close, volume) VALUES (?, ?, ?, ?, ?, ?, ?, ?);", bars)

        df = run_screener(temp_db_mgr, universe="TASE")
        assert df.empty or "ZERO.TA" not in df["ticker"].values

    def test_completely_flat_price_bars_filtered_by_atr(self, temp_db_mgr: DatabaseManager) -> None:
        """Verify completely flat stock (High == Low == Close, ATR = 0) is excluded by atr14 > 0 filter."""
        with temp_db_mgr.write_cursor() as conn:
            conn.execute("INSERT INTO symbol_metadata (ticker, name, exchange, asset_class, is_active) VALUES ('FLAT.TA', 'Flat Corp', 'TASE', 'Common Stock', True);")
            conn.execute("INSERT INTO symbol_metadata (ticker, name, exchange, asset_class, is_active) VALUES ('^TA125.TA', 'TA125', 'TASE', 'Index', True);")

            base_d = datetime.date(2025, 1, 1)
            bars = []
            for i in range(270):
                d = base_d + datetime.timedelta(days=i)
                bars.append(("^TA125.TA", d, 2000.0 + i, 2010.0 + i, 1990.0 + i, 2005.0 + i, 2005.0 + i, 1000000))
                bars.append(("FLAT.TA", d, 1000.0, 1000.0, 1000.0, 1000.0, 1000.0, 50000000))

            conn.executemany("INSERT INTO daily_bars (ticker, trade_date, open, high, low, close, adj_close, volume) VALUES (?, ?, ?, ?, ?, ?, ?, ?);", bars)

        df = run_screener(temp_db_mgr, universe="TASE")
        assert "FLAT.TA" not in df.get("ticker", pd.Series()).values

    def test_tase_price_and_adv20_floors_enforced(self, temp_db_mgr: DatabaseManager) -> None:
        """Verify TASE minimum price floor (100 Agorot) and ADV20 floor (20,000,000 Agorot) filter penny/illiquid stocks."""
        with temp_db_mgr.write_cursor() as conn:
            conn.execute("INSERT INTO symbol_metadata (ticker, name, exchange, asset_class, is_active) VALUES ('PENNY.TA', 'Penny Stock', 'TASE', 'Common Stock', True);")
            conn.execute("INSERT INTO symbol_metadata (ticker, name, exchange, asset_class, is_active) VALUES ('ILLIQ.TA', 'Illiquid Stock', 'TASE', 'Common Stock', True);")
            conn.execute("INSERT INTO symbol_metadata (ticker, name, exchange, asset_class, is_active) VALUES ('^TA125.TA', 'TA125', 'TASE', 'Index', True);")

            base_d = datetime.date(2025, 1, 1)
            bars = []
            for i in range(270):
                d = base_d + datetime.timedelta(days=i)
                factor = 1.0 + (i * 0.002)
                bars.append(("^TA125.TA", d, 2000.0 * factor, 2010.0 * factor, 1990.0 * factor, 2005.0 * factor, 2005.0 * factor, 10000000))
                bars.append(("PENNY.TA", d, 40.0 * factor, 42.0 * factor, 39.0 * factor, 41.0 * factor, 41.0 * factor, 50000000))
                bars.append(("ILLIQ.TA", d, 500.0 * factor, 510.0 * factor, 490.0 * factor, 505.0 * factor, 505.0 * factor, 100))

            conn.executemany("INSERT INTO daily_bars (ticker, trade_date, open, high, low, close, adj_close, volume) VALUES (?, ?, ?, ?, ?, ?, ?, ?);", bars)

        df = run_screener(temp_db_mgr, universe="TASE")
        assert "PENNY.TA" not in df.get("ticker", pd.Series()).values
        assert "ILLIQ.TA" not in df.get("ticker", pd.Series()).values

    def test_extreme_strategy_parameters_handled_gracefully(self, dual_calendar_db: DatabaseManager) -> None:
        """Verify extreme strategy filter values return empty DataFrame safely."""
        df_tight = run_screener(dual_calendar_db, max_tightness=0.001, universe="TASE")
        assert df_tight.empty

        df_price = run_screener(dual_calendar_db, min_price=1000000.0, universe="TASE")
        assert df_price.empty

        res = run_point_in_time_backtest(dual_calendar_db, max_tightness=0.001, universe="TASE")
        assert res["mean_basket_return"] == 0.0
        assert res["positions_df"].empty


# ============================================================================
# Test Class 6: Screener Boundary Thresholds & Single Stock Pool
# ============================================================================

class TestScreenerBoundaryThresholds:
    """Stress tests exact boundary values and single-qualifying stock ranking."""

    def test_manual_tickers_auto_routes_to_tase(self, dual_calendar_db: DatabaseManager) -> None:
        """Verify passing all .TA manual tickers to run_screener automatically routes to TASE benchmark."""
        dates = dual_calendar_db.execute_read("SELECT MAX(trade_date) FROM daily_bars;")
        latest_date = str(dates[0][0])

        df_manual = run_screener(
            dual_calendar_db,
            cutoff_date=latest_date,
            manual_tickers=["LUMI.TA", "POLI.TA"],
            universe="US",  # Provided as US, should auto-route to TASE
        )
        assert not df_manual.empty
        assert all(t.endswith(".TA") for t in df_manual["ticker"])


# ============================================================================
# Test Class 7: Currency Formatting & CSS Rendering
# ============================================================================

class TestCurrencyFormattingAndCSSRendering:
    """Stress tests HTML tables, Agorot currency notation ('Ag.'), USD ('$'), and CSS classes."""

    def test_tase_vs_us_price_formatting_in_html_tables(self) -> None:
        """Verify TASE stocks display 'Ag.' suffix and US stocks display '$' prefix."""
        df_live_tase = pd.DataFrame([{
            "ticker": "DSCT.TA",
            "name": "Israel Discount Bank",
            "market_cap_str": "35.00B Ag.",
            "close": 2510.0,
            "ADV20": "18.0M Ag.",
            "rs_score": 0.45,
            "tightness_ratio": 1.8,
            "pct_off_52w_high": -2.5,
            "composite_score": 92.5,
        }])
        html_tase = build_html_table(df_live_tase, is_backtest=False, is_tase=True)
        assert "2,510.00 Ag." in html_tase
        assert "Price (Ag.)" in html_tase
        assert "ADV20 (Ag.)" in html_tase
        assert "$" not in html_tase

        df_live_us = pd.DataFrame([{
            "ticker": "AAPL",
            "name": "Apple Inc.",
            "market_cap_str": "$3.00T",
            "close": 150.50,
            "ADV20": "$50.0M",
            "rs_score": 0.55,
            "tightness_ratio": 2.1,
            "pct_off_52w_high": -1.2,
            "composite_score": 95.0,
        }])
        html_us = build_html_table(df_live_us, is_backtest=False, is_tase=False)
        assert "$150.50" in html_us
        assert "Price ($)" in html_us
        assert "Ag." not in html_us

    def test_tase_vs_us_backtest_table_columns_and_currency(self) -> None:
        """Verify backtest HTML tables render TA-125 Return (%) vs SPY Return (%)."""
        df_bt_tase = pd.DataFrame([{
            "ticker": "LUMI.TA",
            "name": "Bank Leumi",
            "market_cap_str": "40.00B Ag.",
            "entry_price": 3000.0,
            "exit_price": 3300.0,
            "return_pct": 10.0,
            "ta125_return_pct": 4.5,
            "alpha_pct": 5.5,
            "max_drawdown_pct": -1.2,
            "win_status": "🟢 WIN",
        }])
        html_bt_tase = build_html_table(df_bt_tase, is_backtest=True, is_tase=True)
        assert "Entry Price (Ag.)" in html_bt_tase
        assert "Exit Price (Ag.)" in html_bt_tase
        assert "TA-125 Return (%)" in html_bt_tase
        assert "3,000.00 Ag." in html_bt_tase
        assert "3,300.00 Ag." in html_bt_tase

        df_bt_us = pd.DataFrame([{
            "ticker": "NVDA",
            "name": "NVIDIA",
            "market_cap_str": "$2.80T",
            "entry_price": 100.0,
            "exit_price": 115.0,
            "return_pct": 15.0,
            "spy_return_pct": 5.0,
            "alpha_pct": 10.0,
            "max_drawdown_pct": -2.0,
            "win_status": "🟢 WIN",
        }])
        html_bt_us = build_html_table(df_bt_us, is_backtest=True, is_tase=False)
        assert "Entry Price ($)" in html_bt_us
        assert "Exit Price ($)" in html_bt_us
        assert "SPY Return (%)" in html_bt_us
        assert "$100.00" in html_bt_us

    def test_css_contains_high_contrast_tase_classes(self) -> None:
        """Verify inject_custom_css markdown string contains dedicated TASE styling rules."""
        with patch("streamlit.markdown") as mock_st_md:
            inject_custom_css()
            assert mock_st_md.called
            css_arg = mock_st_md.call_args[0][0]
            assert ".title-tase" in css_arg
            assert ".portfolio-card-tase" in css_arg
            assert "#0b4f8a" in css_arg

    def test_format_company_name_robustness(self) -> None:
        """Verify format_company_name handles None, NaN, whitespace, and empty strings gracefully."""
        assert format_company_name("Bank Leumi", "LUMI.TA") == "Bank Leumi"
        assert format_company_name(None, "LUMI.TA") == "LUMI.TA"
        assert format_company_name(float("nan"), "LUMI.TA") == "LUMI.TA"
        assert format_company_name("nan", "LUMI.TA") == "LUMI.TA"
        assert format_company_name("   ", "LUMI.TA") == "LUMI.TA"


# ============================================================================
# Test Class 8: Sector Classification & UI Formatting
# ============================================================================

class TestSectorClassificationAndUIFormatting:
    """Stress tests sector matching keywords and empty HTML table rendering."""

    def test_is_medical_pharma_classification(self) -> None:
        """Verify medical/pharma keyword matching accuracy."""
        assert is_medical_pharma("Teva Pharmaceutical Industries Ltd.", "TEVA.TA") is True
        assert is_medical_pharma("Moderna Therapeutics", "MRNA") is True
        assert is_medical_pharma("BioNTech SE", "BNTX") is True
        assert is_medical_pharma("UnitedHealth Group", "UNH") is True
        assert is_medical_pharma("Pfizer Inc.", "PFE") is False
        assert is_medical_pharma("Bank Leumi", "LUMI.TA") is False
        assert is_medical_pharma("NICE Ltd.", "NICE.TA") is False
        assert is_medical_pharma("Apple Inc.", "AAPL") is False

    def test_build_html_table_empty_dataframe(self) -> None:
        """Verify build_html_table with empty DataFrame outputs empty message container."""
        empty_html = build_html_table(pd.DataFrame(), is_backtest=False)
        assert "No tickers in this category" in empty_html


# ============================================================================
# Test Class 9: Multi-Exchange CLI Flags & Subcommands
# ============================================================================

class TestCLIFlagCombinationsAndSubcommands:
    """Stress tests CLI subcommands: seed, update, scan, export-delta, sync-delta across all exchange flags."""

    def test_cli_scan_all_permutations(self, dual_calendar_db: DatabaseManager) -> None:
        """Verify scan output sections for all permutations of --exchange."""
        runner = CliRunner()
        db_path = str(dual_calendar_db.db_path)

        res_tase = runner.invoke(scan, ["--db-path", db_path, "--exchange", "TASE"])
        assert res_tase.exit_code == 0
        assert "TASE (TEL AVIV)" in res_tase.output
        assert "US EQUITIES" not in res_tase.output
        assert "^TA125.TA" in res_tase.output

        res_us = runner.invoke(scan, ["--db-path", db_path, "--exchange", "US"])
        assert res_us.exit_code == 0
        assert "US EQUITIES" in res_us.output
        assert "TASE (TEL AVIV)" not in res_us.output
        assert "SPY" in res_us.output

        res_all = runner.invoke(scan, ["--db-path", db_path, "--exchange", "ALL"])
        assert res_all.exit_code == 0
        assert "US EQUITIES" in res_all.output
        assert "TASE (TEL AVIV)" in res_all.output

    def test_cli_seed_and_update_with_mock_ingestion(self, temp_db_mgr: DatabaseManager) -> None:
        """Verify seed and update subcommands execute properly with mock ingestion."""
        runner = CliRunner()
        db_path = str(temp_db_mgr.db_path)

        mock_summary = {
            "total_tickers": 10,
            "synced_tickers": 10,
            "total_bars_inserted": 2500,
            "status": "success",
            "exchange": "TASE",
        }

        with patch("src.ingestion.data_ingestor.DataIngestor.sync_universe", return_value=mock_summary):
            with patch("src.cli.get_tase_symbol_directory", return_value=[{"ticker": "LUMI.TA", "name": "Leumi", "exchange": "TASE", "asset_class": "Common Stock", "is_active": True}]):
                res_seed = runner.invoke(seed, ["--db-path", db_path, "--exchange", "TASE"])
                assert res_seed.exit_code == 0
                assert "Seed Complete" in res_seed.output

                res_update = runner.invoke(update, ["--db-path", db_path, "--exchange", "TASE"])
                assert res_update.exit_code == 0
                assert "Update Complete" in res_update.output

    def test_cli_export_delta_and_sync_delta(self, dual_calendar_db: DatabaseManager, tmp_path: Path) -> None:
        """Verify export-delta generates Parquet file and sync-delta merges it into another DB."""
        runner = CliRunner()
        db_path = str(dual_calendar_db.db_path)
        delta_dir = tmp_path / "deltas"

        res_exp = runner.invoke(export_delta, ["--db-path", db_path, "--output-dir", str(delta_dir)])
        assert res_exp.exit_code == 0
        assert "Export successful" in res_exp.output

        parquet_files = list(delta_dir.glob("*.parquet"))
        assert len(parquet_files) == 1

        new_db_file = tmp_path / "synced_target.duckdb"
        new_db = DatabaseManager(db_path=new_db_file, read_only=False)

        res_sync = runner.invoke(sync_delta, ["--db-path", str(new_db_file), "--deltas-dir", str(delta_dir)])
        assert res_sync.exit_code == 0
        assert "Merged 1 daily delta file(s)" in res_sync.output

        cnt = new_db.execute_read("SELECT COUNT(*) FROM daily_bars;")[0][0]
        assert cnt > 0

    def test_cli_scan_on_empty_database_errors_cleanly(self, temp_db_mgr: DatabaseManager) -> None:
        """Verify scan on empty database halts with exit code 1 and informative error."""
        runner = CliRunner()
        res = runner.invoke(scan, ["--db-path", str(temp_db_mgr.db_path)])
        assert res.exit_code != 0
        assert "Database is empty" in res.output


# ============================================================================
# Test Class 10: CLI Subcommand Permutations & Error Validation
# ============================================================================

class TestCLISubcommandPermutations:
    """Stress tests CLI invalid flag values and error messages."""

    def test_cli_seed_invalid_exchange_choice_fails(self, temp_db_mgr: DatabaseManager) -> None:
        """Verify seed with invalid exchange name fails with click exit code 2."""
        runner = CliRunner()
        res = runner.invoke(seed, ["--db-path", str(temp_db_mgr.db_path), "--exchange", "INVALID"])
        assert res.exit_code != 0
        assert "Invalid value" in res.output

    def test_cli_scan_invalid_exchange_choice_fails(self, temp_db_mgr: DatabaseManager) -> None:
        """Verify scan with invalid exchange name fails with click exit code 2."""
        runner = CliRunner()
        res = runner.invoke(scan, ["--db-path", str(temp_db_mgr.db_path), "--exchange", "INVALID"])
        assert res.exit_code != 0
        assert "Invalid value" in res.output


# ============================================================================
# Test Class 11: Streamlit Views E2E Integration
# ============================================================================

class TestStreamlitAllViewsIntegration:
    """Stress tests full Streamlit rendering across Views A, B, C, D, and E."""

    def test_view_a_live_recommendations_render_both_markets(self, dual_calendar_db: DatabaseManager) -> None:
        """Verify View A renders US Top 10 categories AND Dedicated Top 5 TASE section."""
        max_d_row = dual_calendar_db.execute_read("SELECT MAX(trade_date) FROM daily_bars;")
        latest_date = str(max_d_row[0][0])

        with patch("streamlit.markdown") as mock_md, \
             patch("streamlit.header") as mock_hdr, \
             patch("streamlit.subheader") as mock_subhdr, \
             patch("streamlit.caption"), \
             patch("streamlit.info"), \
             patch("streamlit.warning"), \
             patch("streamlit.spinner"), \
             patch("streamlit.download_button"), \
             patch("streamlit.expander", return_value=MagicMock(__enter__=MagicMock(), __exit__=MagicMock())):

            render_live_recommendations(dual_calendar_db, latest_date)

            md_calls = [str(call[0][0]) for call in mock_md.call_args_list]
            has_tase_header = any("Category 3: Tel Aviv Stock Exchange (TA-125) — Top 5 Recommendations" in c for c in md_calls)
            assert has_tase_header

    def test_view_b_and_c_backtest_render_tase_and_us_benchmark_cards(self, dual_calendar_db: DatabaseManager) -> None:
        """Verify View B (T-5) and View C (T-22) render $10k portfolio cards for SPY and TA-125."""
        with patch("streamlit.markdown") as mock_md, \
             patch("streamlit.header"), \
             patch("streamlit.subheader"), \
             patch("streamlit.caption"), \
             patch("streamlit.info"), \
             patch("streamlit.warning"), \
             patch("streamlit.spinner"), \
             patch("streamlit.download_button"), \
             patch("streamlit.expander", return_value=MagicMock(__enter__=MagicMock(), __exit__=MagicMock())):

            render_backtest_view(dual_calendar_db, cutoff_days_ago=5, view_label="View B: 1-Week Backtest")
            md_calls_b = [str(call[0][0]) for call in mock_md.call_args_list]
            assert any("^TA125.TA Index ($10k Buy & Hold)" in c for c in md_calls_b)
            assert any("5x $2,000 TASE Stock Picks" in c for c in md_calls_b)
            assert any("Net TASE Alpha vs ^TA125.TA" in c for c in md_calls_b)

    def test_view_e_custom_date_backtest_render(self, dual_calendar_db: DatabaseManager) -> None:
        """Verify View E renders custom date backtest for both markets."""
        dates_row = dual_calendar_db.execute_read("SELECT DISTINCT trade_date FROM daily_bars ORDER BY trade_date DESC;")
        custom_date = str(dates_row[10][0])

        with patch("streamlit.markdown") as mock_md, \
             patch("streamlit.header"), \
             patch("streamlit.subheader"), \
             patch("streamlit.caption"), \
             patch("streamlit.info"), \
             patch("streamlit.warning"), \
             patch("streamlit.spinner"), \
             patch("streamlit.download_button"), \
             patch("streamlit.expander", return_value=MagicMock(__enter__=MagicMock(), __exit__=MagicMock())):

            render_backtest_view(
                dual_calendar_db,
                custom_cutoff_date=custom_date,
                view_label=f"View E: Custom Date ({custom_date}) Backtest",
            )
            md_calls_e = [str(call[0][0]) for call in mock_md.call_args_list]
            assert any("Category 3: Tel Aviv Stock Exchange (TA-125)" in c for c in md_calls_e)


# ============================================================================
# Test Class 12: Concurrency & Database Safety
# ============================================================================

class TestConcurrencyAndDatabaseSafety:
    """Stress tests multithreaded read/write concurrency and idempotency."""

    def test_read_only_database_manager_blocks_writes(self, temp_db_mgr: DatabaseManager) -> None:
        """Verify read-only DatabaseManager raises exception on write attempts."""
        ro_mgr = DatabaseManager(db_path=temp_db_mgr.db_path, read_only=True)
        with pytest.raises(Exception):
            ro_mgr.execute_write("INSERT INTO symbol_metadata (ticker) VALUES ('FAIL');")

    def test_idempotent_duplicate_daily_bars_insertion(self, temp_db_mgr: DatabaseManager) -> None:
        """Verify re-inserting identical daily bars replaces without primary key conflict."""
        ingestor = DataIngestor(db_manager=temp_db_mgr)
        fake_df = pd.DataFrame(
            {"Close": [2500.0], "Open": [2490.0], "High": [2520.0], "Low": [2480.0], "Volume": [5000000]},
            index=[pd.Timestamp("2025-01-02")],
        )

        inserted_1 = ingestor.parse_and_store_bars(fake_df, ["LUMI.TA"])
        assert inserted_1 == 1

        inserted_2 = ingestor.parse_and_store_bars(fake_df, ["LUMI.TA"])
        assert inserted_2 == 1

        total_rows = temp_db_mgr.execute_read("SELECT COUNT(*) FROM daily_bars WHERE ticker = 'LUMI.TA';")[0][0]
        assert total_rows == 1
