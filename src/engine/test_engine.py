"""Unit tests for Screener Queries and Point-in-Time Backtest Engine."""

from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import pytest
import pandas as pd

from src.db.db_manager import DatabaseManager
from src.engine.screener_queries import run_screener
from src.engine.backtest_engine import run_point_in_time_backtest


def populate_mock_data(db_mgr: DatabaseManager, num_days: int = 270) -> None:
    """Populates test database with synthetic daily bars and symbol metadata.

    Args:
        db_mgr: DatabaseManager instance.
        num_days: Number of historical trading days to generate.
    """
    start_date = datetime(2025, 1, 1)
    dates = [(start_date + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(num_days)]

    # Insert symbol metadata
    db_mgr.execute_write(
        """
        INSERT INTO symbol_metadata (ticker, name, exchange, asset_class, is_active, first_added_date, last_updated_date)
        VALUES 
        ('SPY', 'SPDR S&P 500 ETF', 'NYSE', 'ETF', true, '2025-01-01', '2026-08-18'),
        ('GOOD1', 'Good Momentum Inc.', 'NASDAQ', 'Common Stock', true, '2025-01-01', '2026-08-18'),
        ('GOOD2', 'Super Trend Corp.', 'NASDAQ', 'Common Stock', true, '2025-01-01', '2026-08-18'),
        ('BAD1', 'Low Volume Penny Co.', 'NASDAQ', 'Common Stock', true, '2025-01-01', '2026-08-18');
        """
    )

    bars = []
    # SPY bars: gradual increase from 400 to 500
    for i, d in enumerate(dates):
        spy_close = 400.0 + (i * 0.37)
        bars.append(("SPY", d, spy_close, spy_close + 1.0, spy_close - 1.0, spy_close, spy_close, 50000000))

    # GOOD1 bars: Meets all Stage 1-3 conditions!
    # Strong uptrend up to day num_days-35, then flat tight consolidation
    base_price = 25.0
    for i, d in enumerate(dates):
        if i < num_days - 35:
            price = base_price + (i * 0.35)
            high = price + 1.0
            low = price - 1.0
            vol = 700000
        else:
            # Consolidation at high price (~107.0)
            price = base_price + ((num_days - 36) * 0.35)
            high = price + 0.3
            low = price - 0.3
            vol = 200000  # VDU (200k <= 0.6 * 350k) and ADV = 107 * 200k = $21.4M >= $20M

        bars.append(("GOOD1", d, price, high, low, price, price, vol))

    # GOOD2 bars: Strong uptrend as well, then tight consolidation
    base_price_2 = 40.0
    for i, d in enumerate(dates):
        if i < num_days - 35:
            price = base_price_2 + (i * 0.35)
            high = price + 0.8
            low = price - 0.8
            vol = 700000
        else:
            price = base_price_2 + ((num_days - 36) * 0.35)
            high = price + 0.25
            low = price - 0.25
            vol = 200000  # VDU: 200k <= 0.6 * SMA50(vol) where SMA50 ~ (15*700k + 35*200k)/50 = 350k => 0.6*350k = 210k. 200k <= 210k.

        bars.append(("GOOD2", d, price, high, low, price, price, vol))

    # BAD1 bars: Fails price & liquidity gate ($5 price, low volume)
    for i, d in enumerate(dates):
        price = 5.0
        bars.append(("BAD1", d, price, price + 0.2, price - 0.2, price, price, 10000))

    with db_mgr.write_cursor() as conn:
        conn.executemany(
            """
            INSERT INTO daily_bars (ticker, trade_date, open, high, low, close, adj_close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            bars,
        )


def test_screener_execution():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_screener.duckdb"
        db_mgr = DatabaseManager(db_path=db_path)
        populate_mock_data(db_mgr, num_days=270)

        dates = db_mgr.execute_read("SELECT DISTINCT trade_date FROM daily_bars ORDER BY trade_date DESC;")
        latest_date = str(dates[0][0])

        df = run_screener(db_mgr, cutoff_date=latest_date)

        assert isinstance(df, pd.DataFrame)
        assert not df.empty
        # GOOD1 and GOOD2 should be in top results, BAD1 and SPY should be filtered out
        tickers = df["ticker"].tolist()
        assert "GOOD1" in tickers
        assert "GOOD2" in tickers
        assert "BAD1" not in tickers
        assert "SPY" not in tickers

        # Verify output columns
        expected_cols = [
            "rank", "ticker", "name", "exchange", "trade_date",
            "close", "adv_20", "sma50", "sma150", "sma200",
            "high_52w", "low_52w", "tightness_ratio", "vdu_ratio",
            "rs_score", "composite_score"
        ]
        for col in expected_cols:
            assert col in df.columns


def test_point_in_time_backtest():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_backtest.duckdb"
        db_mgr = DatabaseManager(db_path=db_path)
        populate_mock_data(db_mgr, num_days=270)

        # Test T-5 backtest
        result = run_point_in_time_backtest(db_mgr, cutoff_days_ago=5)

        assert isinstance(result, dict)
        assert result["cutoff_days_ago"] == 5
        assert "cutoff_date" in result
        assert "evaluation_date" in result
        assert "mean_basket_return" in result
        assert "spy_return" in result
        assert "basket_alpha" in result
        assert "win_rate" in result
        assert "avg_max_drawdown" in result

        pos_df = result["positions_df"]
        assert isinstance(pos_df, pd.DataFrame)
        if not pos_df.empty:
            assert "ticker" in pos_df.columns
            assert "return_pct" in pos_df.columns
            assert "spy_return_pct" in pos_df.columns
            assert "alpha_pct" in pos_df.columns
            assert "max_drawdown_pct" in pos_df.columns
            assert "is_win" in pos_df.columns

        # Verify entry in point_in_time_runs table
        runs = db_mgr.execute_read("SELECT scan_type, cutoff_date, top_tickers FROM point_in_time_runs;")
        assert len(runs) >= 1
        assert runs[0][0] == "T-5"


def test_invalid_cutoff_days():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_invalid.duckdb"
        db_mgr = DatabaseManager(db_path=db_path)

        with pytest.raises(ValueError):
            run_point_in_time_backtest(db_mgr, cutoff_days_ago=0)

        with pytest.raises(ValueError):
            run_point_in_time_backtest(db_mgr, cutoff_days_ago=1000)


def test_manual_vs_screener_score_consistency():
    """Verify that manual_sql and SCREENER_SQL compute composite_score using identical percentile ranking formulas."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_consistency.duckdb"
        db_mgr = DatabaseManager(db_path=db_path)
        populate_mock_data(db_mgr, num_days=270)

        dates = db_mgr.execute_read("SELECT DISTINCT trade_date FROM daily_bars ORDER BY trade_date DESC;")
        latest_date = str(dates[0][0])

        df_screener = run_screener(db_mgr, cutoff_date=latest_date)
        assert not df_screener.empty

        # Evaluate a ticker via manual_tickers
        target_ticker = df_screener.iloc[0]["ticker"]
        df_manual = run_screener(db_mgr, cutoff_date=latest_date, manual_tickers=[target_ticker])
        assert not df_manual.empty

        screener_row = df_screener[df_screener["ticker"] == target_ticker].iloc[0]
        manual_row = df_manual[df_manual["ticker"] == target_ticker].iloc[0]

        # Verify composite_score and rs_score match exactly, and composite_score is bounded in [0, 100]
        assert abs(screener_row["rs_score"] - manual_row["rs_score"]) < 1e-5
        assert abs(screener_row["composite_score"] - manual_row["composite_score"]) < 1e-5
        assert 0.0 <= manual_row["composite_score"] <= 100.0

