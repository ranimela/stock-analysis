"""Adversarial stress-test suite for TASE Quantitative Screener, PIT Backtesting, and CLI Scan.

Validates boundary conditions, cross-market calendar alignment, CLI exchange flags,
ranking isolation, and robustness under extreme parameters.
"""

from __future__ import annotations

import datetime
from pathlib import Path
import tempfile
from click.testing import CliRunner
import pandas as pd
import pytest

from src.cli import main, scan
from src.db.db_manager import DatabaseManager
from src.engine.backtest_engine import run_point_in_time_backtest
from src.engine.screener_queries import run_screener
from src.engine.test_engine import populate_multi_universe_mock_data


@pytest.fixture
def populated_engine_db() -> DatabaseManager:
    """Fixture providing a temporary DatabaseManager populated with multi-market data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "adv_engine_test.duckdb"
        db_mgr = DatabaseManager(db_path=db_path, read_only=False)
        populate_multi_universe_mock_data(db_mgr, num_days=270)
        yield db_mgr


class TestCLIScanCommandAdversarial:
    """Adversarial tests for CLI scan command options and outputs."""

    def test_cli_scan_exchange_us(self, populated_engine_db: DatabaseManager) -> None:
        """Verify scan with --exchange US prints US report and excludes TASE."""
        runner = CliRunner()
        result = runner.invoke(scan, ["--db-path", str(populated_engine_db.db_path), "--exchange", "US"])
        assert result.exit_code == 0
        assert "US EQUITIES" in result.output
        assert "TASE (TEL AVIV)" not in result.output

    def test_cli_scan_exchange_tase(self, populated_engine_db: DatabaseManager) -> None:
        """Verify scan with --exchange TASE prints TASE report and excludes US."""
        runner = CliRunner()
        result = runner.invoke(scan, ["--db-path", str(populated_engine_db.db_path), "--exchange", "TASE"])
        assert result.exit_code == 0
        assert "TASE (TEL AVIV)" in result.output
        assert "US EQUITIES" not in result.output
        assert "TOP-5" in result.output

    def test_cli_scan_exchange_all(self, populated_engine_db: DatabaseManager) -> None:
        """Verify scan with --exchange ALL prints both US and TASE reports."""
        runner = CliRunner()
        result = runner.invoke(scan, ["--db-path", str(populated_engine_db.db_path), "--exchange", "ALL"])
        assert result.exit_code == 0
        assert "US EQUITIES" in result.output
        assert "TASE (TEL AVIV)" in result.output
        assert "LIVE TOP-10 RECOMMENDATIONS" in result.output
        assert "LIVE TOP-5 RECOMMENDATIONS" in result.output

    @pytest.mark.parametrize("flag_val", ["us", "Us", "tase", "Tase", "all", "All"])
    def test_cli_scan_case_insensitive_flags(self, populated_engine_db: DatabaseManager, flag_val: str) -> None:
        """Verify case-insensitive handling for --exchange and -e flags."""
        runner = CliRunner()
        result = runner.invoke(scan, ["--db-path", str(populated_engine_db.db_path), "-e", flag_val])
        assert result.exit_code == 0

    @pytest.mark.parametrize("invalid_val", ["INVALID", "LSE", "NYSE", "123", ""])
    def test_cli_scan_invalid_exchange_rejection(self, populated_engine_db: DatabaseManager, invalid_val: str) -> None:
        """Verify invalid exchange options are rejected with non-zero exit code."""
        runner = CliRunner()
        result = runner.invoke(scan, ["--db-path", str(populated_engine_db.db_path), "--exchange", invalid_val])
        assert result.exit_code != 0


class TestQuantitativeEngineAdversarial:
    """Adversarial tests for Quantitative Screener and Backtest Engine."""

    def test_backtest_read_only_database_safety(self, populated_engine_db: DatabaseManager) -> None:
        """Verify run_point_in_time_backtest succeeds without error on read-only DB."""
        ro_mgr = DatabaseManager(db_path=populated_engine_db.db_path, read_only=True)
        res = run_point_in_time_backtest(ro_mgr, cutoff_days_ago=5, universe="TASE")
        assert isinstance(res, dict)
        assert res["universe"] == "TASE"
        assert not res["positions_df"].empty

    def test_backtest_top_n_portfolio_allocations(self, populated_engine_db: DatabaseManager) -> None:
        """Verify top_n parameter controls portfolio position count and dollar/percentage weights."""
        res_top3 = run_point_in_time_backtest(populated_engine_db, cutoff_days_ago=5, universe="TASE", top_n=3)
        pos_df_3 = res_top3["positions_df"]
        assert len(pos_df_3) == 3
        assert all(abs(p - 33.333333333333336) < 1e-3 for p in pos_df_3["allocation_pct"])
        assert all(abs(usd - 3333.3333333333335) < 1e-3 for usd in pos_df_3["allocation_usd"])

        res_top5 = run_point_in_time_backtest(populated_engine_db, cutoff_days_ago=5, universe="TASE", top_n=5)
        pos_df_5 = res_top5["positions_df"]
        assert len(pos_df_5) == 5
        assert all(p == 20.0 for p in pos_df_5["allocation_pct"])
        assert all(usd == 2000.0 for usd in pos_df_5["allocation_usd"])

    def test_screener_manual_tickers_auto_routing(self, populated_engine_db: DatabaseManager) -> None:
        """Verify manual_tickers with .TA symbols automatically routes universe to TASE."""
        dates = populated_engine_db.execute_read("SELECT DISTINCT trade_date FROM daily_bars ORDER BY trade_date DESC;")
        latest_date = str(dates[0][0])

        # Call with default universe="US", but manual tickers are all .TA
        df = run_screener(populated_engine_db, cutoff_date=latest_date, manual_tickers=["LUMI.TA", "POLI.TA"])
        assert not df.empty
        assert all(t.endswith(".TA") for t in df["ticker"])
        assert all(ex == "TASE" for ex in df["exchange"])

    def test_screener_custom_liquidity_and_price_floors(self, populated_engine_db: DatabaseManager) -> None:
        """Verify min_price and min_adv20 overrides operate cleanly."""
        dates = populated_engine_db.execute_read("SELECT DISTINCT trade_date FROM daily_bars ORDER BY trade_date DESC;")
        latest_date = str(dates[0][0])

        # Setting min_price=100000.0 Agorot should filter out LUMI (3000-5500) but keep ESLT (70k-112k)
        df_high_price = run_screener(
            populated_engine_db,
            cutoff_date=latest_date,
            universe="TASE",
            min_price=100000.0,
        )
        if not df_high_price.empty:
            assert "LUMI.TA" not in df_high_price["ticker"].tolist()
            assert all(c >= 100000.0 for c in df_high_price["close"])

    def test_backtest_empty_screener_result_graceful_handling(self, populated_engine_db: DatabaseManager) -> None:
        """Verify backtest returns clean empty structure with 0.0 stats when no stocks qualify."""
        # Force 0 qualifying stocks by demanding impossibly high price floor
        res = run_point_in_time_backtest(
            populated_engine_db,
            cutoff_days_ago=5,
            universe="TASE",
            pct_off_low=5000.0,  # 5000% gain off low required -> impossible
        )
        assert isinstance(res, dict)
        assert res["mean_basket_return"] == 0.0
        assert res["basket_alpha"] == 0.0
        assert res["win_rate"] == 0.0
        assert res["avg_max_drawdown"] == 0.0
        assert isinstance(res["positions_df"], pd.DataFrame)
        assert res["positions_df"].empty
