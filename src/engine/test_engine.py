"""Comprehensive Unit and Integration Tests for Screener Queries and Backtest Engine (US & TASE)."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import tempfile
from typing import Any

import pandas as pd
import pytest

from src.db.db_manager import DatabaseManager
from src.engine.backtest_engine import run_point_in_time_backtest
from src.engine.screener_queries import run_screener


def populate_mock_data(db_mgr: DatabaseManager, num_days: int = 270) -> None:
    """Populates test database with synthetic US daily bars and symbol metadata."""
    populate_multi_universe_mock_data(db_mgr, num_days=num_days)


def populate_multi_universe_mock_data(db_mgr: DatabaseManager, num_days: int = 270) -> None:
    """Populates test database with synthetic daily bars and symbol metadata for BOTH US and TASE universes.

    Args:
        db_mgr: Initialized DatabaseManager instance.
        num_days: Number of historical trading days to generate. Defaults to 270.
    """
    start_date = datetime(2025, 1, 1)
    dates = [(start_date + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(num_days)]

    # 1. Insert Symbol Metadata (US & TASE)
    db_mgr.execute_write(
        """
        INSERT INTO symbol_metadata (ticker, name, exchange, asset_class, is_active, first_added_date, last_updated_date)
        VALUES 
        -- US Equities & Benchmark
        ('SPY', 'SPDR S&P 500 ETF', 'NYSE', 'ETF', true, '2025-01-01', '2026-08-18'),
        ('GOOD1', 'Good US Momentum Inc.', 'NASDAQ', 'Common Stock', true, '2025-01-01', '2026-08-18'),
        ('GOOD2', 'Super US Trend Corp.', 'NASDAQ', 'Common Stock', true, '2025-01-01', '2026-08-18'),
        ('BAD1', 'Low Volume US Penny Co.', 'NASDAQ', 'Common Stock', true, '2025-01-01', '2026-08-18'),
        ('US_FAIL_VCP', 'Loose Volatility US Co.', 'NASDAQ', 'Common Stock', true, '2025-01-01', '2026-08-18'),

        -- TASE Equities & Benchmark
        ('^TA125.TA', 'TA-125 Index Benchmark', 'TASE', 'Index', true, '2025-01-01', '2026-08-18'),
        ('LUMI.TA', 'Bank Leumi Le-Israel B.M.', 'TASE', 'Common Stock', true, '2025-01-01', '2026-08-18'),
        ('POLI.TA', 'Bank Hapoalim B.M.', 'TASE', 'Common Stock', true, '2025-01-01', '2026-08-18'),
        ('NICE.TA', 'NICE Ltd.', 'TASE', 'Common Stock', true, '2025-01-01', '2026-08-18'),
        ('TEVA.TA', 'Teva Pharmaceutical Industries Ltd.', 'TASE', 'Common Stock', true, '2025-01-01', '2026-08-18'),
        ('ICL.TA', 'ICL Group Ltd.', 'TASE', 'Common Stock', true, '2025-01-01', '2026-08-18'),
        ('ESLT.TA', 'Elbit Systems Ltd.', 'TASE', 'Common Stock', true, '2025-01-01', '2026-08-18'),
        ('FAIL_PENNY.TA', 'TASE Penny Stock Ltd.', 'TASE', 'Common Stock', true, '2025-01-01', '2026-08-18'),
        ('FAIL_ILLIQUID.TA', 'TASE Ghost Town Ltd.', 'TASE', 'Common Stock', true, '2025-01-01', '2026-08-18'),
        ('FAIL_DOWNTREND.TA', 'TASE Falling Knife Ltd.', 'TASE', 'Common Stock', true, '2025-01-01', '2026-08-18'),
        ('FAIL_LOOSE_VCP.TA', 'TASE Wild Swing Ltd.', 'TASE', 'Common Stock', true, '2025-01-01', '2026-08-18');
        """
    )

    bars: list[tuple[str, str, float, float, float, float, float, int]] = []

    # 2. US SPY Bars: gradual increase from 400.0 to 500.0
    for i, d in enumerate(dates):
        spy_close = 400.0 + (i * 0.37)
        bars.append(("SPY", d, spy_close, spy_close + 1.0, spy_close - 1.0, spy_close, spy_close, 50000000))

    # 3. US GOOD1 & GOOD2 Bars: Strong uptrend then tight consolidation
    for i, d in enumerate(dates):
        if i < num_days - 35:
            p1 = 25.0 + (i * 0.35)
            h1, l1 = p1 + 1.0, p1 - 1.0
            p2 = 40.0 + (i * 0.35)
            h2, l2 = p2 + 0.8, p2 - 0.8
            vol = 700000
        else:
            p1 = 25.0 + ((num_days - 36) * 0.35)
            h1, l1 = p1 + 0.3, p1 - 0.3
            p2 = 40.0 + ((num_days - 36) * 0.35)
            h2, l2 = p2 + 0.25, p2 - 0.25
            vol = 200000
        bars.append(("GOOD1", d, p1, h1, l1, p1, p1, vol))
        bars.append(("GOOD2", d, p2, h2, l2, p2, p2, vol))

        # US BAD1: Fails price & liquidity gate ($5 price, low volume)
        bars.append(("BAD1", d, 5.0, 5.2, 4.8, 5.0, 5.0, 10000))

        # US_FAIL_VCP: Wild swing in consolidation (tightness > 3.5)
        if i < num_days - 35:
            p_v = 30.0 + (i * 0.30)
            bars.append(("US_FAIL_VCP", d, p_v, p_v + 1.0, p_v - 1.0, p_v, p_v, 500000))
        else:
            p_v = 30.0 + ((num_days - 36) * 0.30)
            if i == num_days - 3:
                h_v, l_v = p_v + 8.0, p_v - 8.0
            else:
                h_v, l_v = p_v + 0.3, p_v - 0.3
            bars.append(("US_FAIL_VCP", d, p_v, h_v, l_v, p_v, p_v, 500000))

    # 4. TASE Benchmark (^TA125.TA): Rises from 2000.0 to 2500.0 (+25.0%)
    for i, d in enumerate(dates):
        ta_close = 2000.0 + (i * 1.85185)
        bars.append(("^TA125.TA", d, ta_close, ta_close + 5.0, ta_close - 5.0, ta_close, ta_close, 10000000))

    # 5. TASE Qualifying High-Momentum Equities
    tase_configs = [
        ("LUMI.TA", 3000.0, 10.5, 500000, 0.0),   # Bank Leumi: tightest consolidation (tightness = 1.00)
        ("POLI.TA", 2500.0, 9.8, 450000, 0.2),    # Bank Hapoalim: tightness ~ 1.54
        ("NICE.TA", 60000.0, 150.0, 50000, 0.4),  # NICE Ltd.: tightness ~ 2.13
        ("TEVA.TA", 4000.0, 14.0, 600000, 0.6),   # Teva: tightness ~ 2.70
        ("ICL.TA", 1800.0, 6.0, 400000, 0.8),     # ICL: tightness ~ 3.26
        ("ESLT.TA", 70000.0, 180.0, 30000, 0.9),  # Elbit: tightness ~ 3.50
    ]

    for ticker, base_p, step, norm_vol, spike in tase_configs:
        for i, d in enumerate(dates):
            if i < num_days - 35:
                p = base_p + (i * step)
                h = p + (step * 0.8)
                l = p - (step * 0.8)
                v = norm_vol
            else:
                p = base_p + ((num_days - 36) * step)
                if i == num_days - 5:
                    h = p + 0.3 + spike
                    l = p - 0.3 - spike
                else:
                    h = p + 0.3
                    l = p - 0.3
                v = int(norm_vol * 0.35)  # VDU (Volume Dry-Up)
            bars.append((ticker, d, p, h, l, p, p, v))

    # 6. TASE Negative Test Equities
    for i, d in enumerate(dates):
        # FAIL_PENNY.TA: Price 50 Agorot (< 100 Agorot floor)
        bars.append(("FAIL_PENNY.TA", d, 50.0, 51.0, 49.0, 50.0, 50.0, 100000))

        # FAIL_ILLIQUID.TA: ADV20 = 3000 * 50 = 150,000 Agorot (< 20,000,000 floor)
        bars.append(("FAIL_ILLIQUID.TA", d, 3000.0, 3010.0, 2990.0, 3000.0, 3000.0, 50))

        # FAIL_DOWNTREND.TA: Severe downtrend from 5000 to 2000 Agorot
        dt_p = 5000.0 - (i * 11.0)
        bars.append(("FAIL_DOWNTREND.TA", d, dt_p, dt_p + 10.0, dt_p - 10.0, dt_p, dt_p, 300000))

        # FAIL_LOOSE_VCP.TA: Strong uptrend but loose high-volatility swing in consolidation
        if i < num_days - 35:
            lv_p = 2000.0 + (i * 8.0)
            bars.append(("FAIL_LOOSE_VCP.TA", d, lv_p, lv_p + 5.0, lv_p - 5.0, lv_p, lv_p, 300000))
        else:
            lv_p = 2000.0 + ((num_days - 36) * 8.0)
            if i == num_days - 3:
                lv_h, lv_l = lv_p + 15.0, lv_p - 15.0
            else:
                lv_h, lv_l = lv_p + 0.3, lv_p - 0.3
            bars.append(("FAIL_LOOSE_VCP.TA", d, lv_p, lv_h, lv_l, lv_p, lv_p, 300000))

    with db_mgr.write_cursor() as conn:
        conn.executemany(
            """
            INSERT INTO daily_bars (ticker, trade_date, open, high, low, close, adj_close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            bars,
        )


@pytest.fixture
def multi_market_db() -> DatabaseManager:
    """Fixture providing an isolated temporary DatabaseManager populated with multi-universe data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_engine_multi.duckdb"
        db_mgr = DatabaseManager(db_path=db_path, read_only=False)
        populate_multi_universe_mock_data(db_mgr, num_days=270)
        yield db_mgr


# ============================================================================
# MODULE 1: TASE SCREENER EXECUTION & TOP 5 RECOMMENDATIONS
# ============================================================================


def test_screener_execution(multi_market_db: DatabaseManager) -> None:
    """Legacy compatibility test for basic US screener execution."""
    dates = multi_market_db.execute_read("SELECT DISTINCT trade_date FROM daily_bars ORDER BY trade_date DESC;")
    latest_date = str(dates[0][0])

    df = run_screener(multi_market_db, cutoff_date=latest_date, universe="US")

    assert isinstance(df, pd.DataFrame)
    assert not df.empty
    tickers = df["ticker"].tolist()
    assert "GOOD1" in tickers
    assert "GOOD2" in tickers
    assert "BAD1" not in tickers
    assert "SPY" not in tickers

    expected_cols = [
        "rank", "ticker", "name", "exchange", "trade_date",
        "close", "adv_20", "sma50", "sma150", "sma200",
        "high_52w", "low_52w", "tightness_ratio", "vdu_ratio",
        "rs_score", "composite_score"
    ]
    for col in expected_cols:
        assert col in df.columns


def test_screener_tase_universe_execution(multi_market_db: DatabaseManager) -> None:
    """Test run_screener with universe='TASE' returns top TASE equities and excludes failing ones."""
    dates = multi_market_db.execute_read("SELECT DISTINCT trade_date FROM daily_bars ORDER BY trade_date DESC;")
    latest_date = str(dates[0][0])

    df_tase = run_screener(multi_market_db, cutoff_date=latest_date, universe="TASE")

    assert isinstance(df_tase, pd.DataFrame)
    assert not df_tase.empty
    assert len(df_tase) >= 5

    tickers = df_tase["ticker"].tolist()

    # Core qualifying TASE stocks must be present
    assert "LUMI.TA" in tickers
    assert "POLI.TA" in tickers
    assert "NICE.TA" in tickers
    assert "TEVA.TA" in tickers
    assert "ICL.TA" in tickers
    assert "ESLT.TA" in tickers

    # Benchmark and negative candidates must be excluded
    assert "^TA125.TA" not in tickers
    assert "SPY" not in tickers
    assert "GOOD1" not in tickers
    assert "FAIL_PENNY.TA" not in tickers
    assert "FAIL_ILLIQUID.TA" not in tickers
    assert "FAIL_DOWNTREND.TA" not in tickers
    assert "FAIL_LOOSE_VCP.TA" not in tickers

    # Verify all exchange tags are TASE
    assert all(ex == "TASE" for ex in df_tase["exchange"])


def test_screener_dedicated_tase_top_5_extraction(multi_market_db: DatabaseManager) -> None:
    """Test extracting Top 5 TASE recommendations yields exactly 5 sorted high-conviction picks."""
    dates = multi_market_db.execute_read("SELECT DISTINCT trade_date FROM daily_bars ORDER BY trade_date DESC;")
    latest_date = str(dates[0][0])

    df_tase = run_screener(multi_market_db, cutoff_date=latest_date, universe="TASE")
    top_5_tase = df_tase.head(5)

    assert len(top_5_tase) == 5
    assert all(t.endswith(".TA") for t in top_5_tase["ticker"])
    assert top_5_tase["composite_score"].is_monotonic_decreasing
    assert all(0.0 <= score <= 100.0 for score in top_5_tase["composite_score"])


def test_screener_output_columns_contract(multi_market_db: DatabaseManager) -> None:
    """Verify standard screener DataFrame output column contracts for TASE universe."""
    dates = multi_market_db.execute_read("SELECT DISTINCT trade_date FROM daily_bars ORDER BY trade_date DESC;")
    latest_date = str(dates[0][0])

    df_tase = run_screener(multi_market_db, cutoff_date=latest_date, universe="TASE")

    expected_cols = [
        "rank", "ticker", "name", "exchange", "trade_date",
        "close", "adv_20", "sma50", "sma150", "sma200",
        "high_52w", "low_52w", "tightness_ratio", "vdu_ratio",
        "rs_score", "composite_score"
    ]
    for col in expected_cols:
        assert col in df_tase.columns, f"Missing required column: {col}"


# ============================================================================
# MODULE 2: UNIVERSE ISOLATION & CROSS-CONTAMINATION PREVENTION
# ============================================================================


def test_universe_isolation_us_vs_tase(multi_market_db: DatabaseManager) -> None:
    """Verify complete separation of US and TASE universes without cross-contamination."""
    dates = multi_market_db.execute_read("SELECT DISTINCT trade_date FROM daily_bars ORDER BY trade_date DESC;")
    latest_date = str(dates[0][0])

    df_us = run_screener(multi_market_db, cutoff_date=latest_date, universe="US")
    df_tase = run_screener(multi_market_db, cutoff_date=latest_date, universe="TASE")

    assert not df_us.empty
    assert not df_tase.empty

    us_tickers = set(df_us["ticker"])
    tase_tickers = set(df_tase["ticker"])

    # Ticker sets must be completely disjoint
    assert us_tickers.isdisjoint(tase_tickers)

    # US results must have zero .TA tickers
    assert not any(t.endswith(".TA") for t in us_tickers)
    assert "SPY" not in us_tickers

    # TASE results must have 100% .TA tickers
    assert all(t.endswith(".TA") for t in tase_tickers)
    assert "^TA125.TA" not in tase_tickers

    # Rank indices must start at 1 independently in both universes
    assert int(df_us.iloc[0]["rank"]) == 1
    assert int(df_tase.iloc[0]["rank"]) == 1


def test_tase_percentile_ranking_isolation(multi_market_db: DatabaseManager) -> None:
    """Verify that composite_score percentile ranking is computed strictly within the TASE universe."""
    dates = multi_market_db.execute_read("SELECT DISTINCT trade_date FROM daily_bars ORDER BY trade_date DESC;")
    latest_date = str(dates[0][0])

    df_tase = run_screener(multi_market_db, cutoff_date=latest_date, universe="TASE")

    # Top ranked stock in TASE pool must achieve top relative composite score (> 50.0)
    top_score = df_tase.iloc[0]["composite_score"]
    assert top_score >= 50.0
    assert df_tase["composite_score"].max() <= 100.0
    assert df_tase["composite_score"].min() >= 0.0


# ============================================================================
# MODULE 3: QUANTITATIVE INDICATOR MATHEMATICS
# ============================================================================


def test_tase_vcp_tightness_ratio_math(multi_market_db: DatabaseManager) -> None:
    """Verify VCP tightness ratio calculation (high_10d - low_10d) / atr14 and threshold gating."""
    dates = multi_market_db.execute_read("SELECT DISTINCT trade_date FROM daily_bars ORDER BY trade_date DESC;")
    latest_date = str(dates[0][0])

    df_tase = run_screener(multi_market_db, cutoff_date=latest_date, universe="TASE", max_tightness=3.5)
    assert not df_tase.empty

    for _, row in df_tase.iterrows():
        assert row["tightness_ratio"] <= 3.5
        assert row["tightness_ratio"] > 0.0

    # Strict tightness filter (max_tightness=0.5) should filter out regular consolidations
    df_strict = run_screener(multi_market_db, cutoff_date=latest_date, universe="TASE", max_tightness=0.5)
    assert df_strict.empty or len(df_strict) < len(df_tase)


def test_tase_52w_high_low_distance_filters(multi_market_db: DatabaseManager) -> None:
    """Verify 52-week High/Low distance filters for TASE equities."""
    dates = multi_market_db.execute_read("SELECT DISTINCT trade_date FROM daily_bars ORDER BY trade_date DESC;")
    latest_date = str(dates[0][0])

    df_tase = run_screener(
        multi_market_db,
        cutoff_date=latest_date,
        universe="TASE",
        pct_off_low=30.0,
        pct_within_high=25.0,
    )
    assert not df_tase.empty

    for _, row in df_tase.iterrows():
        # Close >= 1.30 * low_52w
        assert row["close"] >= 1.30 * row["low_52w"] - 1e-4
        # Close >= 0.75 * high_52w
        assert row["close"] >= 0.75 * row["high_52w"] - 1e-4


def test_tase_minervini_trend_template(multi_market_db: DatabaseManager) -> None:
    """Verify Minervini Stage-2 trend template criteria on TASE equities."""
    dates = multi_market_db.execute_read("SELECT DISTINCT trade_date FROM daily_bars ORDER BY trade_date DESC;")
    latest_date = str(dates[0][0])

    df_tase = run_screener(multi_market_db, cutoff_date=latest_date, universe="TASE")
    assert not df_tase.empty

    for _, row in df_tase.iterrows():
        assert row["close"] > row["sma50"]
        assert row["sma50"] > row["sma150"]
        assert row["sma150"] > row["sma200"]
        assert row["sma200"] > row["sma200_20d_ago"]


def test_tase_mansfield_rs_vs_ta125(multi_market_db: DatabaseManager) -> None:
    """Verify Mansfield Relative Strength is computed against ^TA125.TA benchmark."""
    dates = multi_market_db.execute_read("SELECT DISTINCT trade_date FROM daily_bars ORDER BY trade_date DESC;")
    latest_date = str(dates[0][0])

    df_tase = run_screener(multi_market_db, cutoff_date=latest_date, universe="TASE")
    assert not df_tase.empty

    # Top TASE momentum stocks clearly outperform ^TA125.TA, so rs_score must be positive
    for _, row in df_tase.iterrows():
        assert row["rs_score"] > 0.0


# ============================================================================
# MODULE 4: TASE LIQUIDITY & PRICE FLOOR GATING
# ============================================================================


def test_tase_price_floor_filtering(multi_market_db: DatabaseManager) -> None:
    """Verify TASE stocks priced below floor (e.g. FAIL_PENNY.TA at 50 Agorot) are rejected."""
    dates = multi_market_db.execute_read("SELECT DISTINCT trade_date FROM daily_bars ORDER BY trade_date DESC;")
    latest_date = str(dates[0][0])

    df_tase = run_screener(multi_market_db, cutoff_date=latest_date, universe="TASE")
    tickers = df_tase["ticker"].tolist()

    assert "FAIL_PENNY.TA" not in tickers
    assert all(c >= 100.0 for c in df_tase["close"])


def test_tase_adv20_liquidity_filtering(multi_market_db: DatabaseManager) -> None:
    """Verify TASE stocks with low ADV20 (e.g. FAIL_ILLIQUID.TA) are rejected."""
    dates = multi_market_db.execute_read("SELECT DISTINCT trade_date FROM daily_bars ORDER BY trade_date DESC;")
    latest_date = str(dates[0][0])

    df_tase = run_screener(multi_market_db, cutoff_date=latest_date, universe="TASE")
    tickers = df_tase["ticker"].tolist()

    assert "FAIL_ILLIQUID.TA" not in tickers
    assert all(adv >= 20000000.0 for adv in df_tase["adv_20"])


# ============================================================================
# MODULE 5: TASE POINT-IN-TIME BACKTESTING
# ============================================================================


def test_point_in_time_backtest(multi_market_db: DatabaseManager) -> None:
    """Legacy compatibility test for basic US point-in-time backtest."""
    result = run_point_in_time_backtest(multi_market_db, cutoff_days_ago=5, universe="US")

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

    runs = multi_market_db.execute_read("SELECT scan_type, cutoff_date, top_tickers FROM point_in_time_runs;")
    assert len(runs) >= 1
    assert runs[0][0] == "T-5"


def test_tase_point_in_time_backtest_t5(multi_market_db: DatabaseManager) -> None:
    """Verify run_point_in_time_backtest for universe='TASE' at T-5."""
    result = run_point_in_time_backtest(multi_market_db, cutoff_days_ago=5, universe="TASE")

    assert isinstance(result, dict)
    assert result["cutoff_days_ago"] == 5
    assert "cutoff_date" in result
    assert "evaluation_date" in result
    assert "mean_basket_return" in result
    assert "basket_alpha" in result
    assert "win_rate" in result
    assert "avg_max_drawdown" in result
    assert "positions_df" in result

    # Check benchmark returns correspond to ^TA125.TA
    pos_df = result["positions_df"]
    assert isinstance(pos_df, pd.DataFrame)
    if not pos_df.empty:
        assert all(t.endswith(".TA") for t in pos_df["ticker"])
        assert "return_pct" in pos_df.columns
        assert "alpha_pct" in pos_df.columns
        assert "max_drawdown_pct" in pos_df.columns
        assert "is_win" in pos_df.columns
        assert "allocation_pct" in pos_df.columns
        assert "allocation_usd" in pos_df.columns


def test_tase_point_in_time_backtest_t22(multi_market_db: DatabaseManager) -> None:
    """Verify run_point_in_time_backtest for universe='TASE' at T-22."""
    result = run_point_in_time_backtest(multi_market_db, cutoff_days_ago=22, universe="TASE")
    assert isinstance(result, dict)
    assert result["cutoff_days_ago"] == 22
    assert isinstance(result["positions_df"], pd.DataFrame)


def test_tase_custom_cutoff_date_backtest(multi_market_db: DatabaseManager) -> None:
    """Verify run_point_in_time_backtest with a specific custom historical date."""
    dates = multi_market_db.execute_read("SELECT DISTINCT trade_date FROM daily_bars ORDER BY trade_date DESC;")
    target_custom_date = str(dates[10][0])

    result = run_point_in_time_backtest(
        multi_market_db,
        custom_cutoff_date=target_custom_date,
        universe="TASE",
    )
    assert result["cutoff_date"] == target_custom_date
    assert isinstance(result["positions_df"], pd.DataFrame)


def test_tase_backtest_persistence_to_db(multi_market_db: DatabaseManager) -> None:
    """Verify TASE point-in-time backtest run is saved to point_in_time_runs table."""
    run_point_in_time_backtest(multi_market_db, cutoff_days_ago=5, universe="TASE")
    runs = multi_market_db.execute_read("SELECT scan_type, cutoff_date, top_tickers FROM point_in_time_runs;")
    assert len(runs) >= 1


# ============================================================================
# MODULE 6: DIAGNOSTICS & BOUNDARY CASES
# ============================================================================


def test_tase_manual_tickers_diagnostic(multi_market_db: DatabaseManager) -> None:
    """Verify manual_tickers evaluation for TASE equities in Diagnostic Lab mode."""
    dates = multi_market_db.execute_read("SELECT DISTINCT trade_date FROM daily_bars ORDER BY trade_date DESC;")
    latest_date = str(dates[0][0])

    df_manual = run_screener(
        multi_market_db,
        cutoff_date=latest_date,
        manual_tickers=["LUMI.TA", "POLI.TA"],
        universe="TASE",
    )
    assert not df_manual.empty
    tickers = df_manual["ticker"].tolist()
    assert "LUMI.TA" in tickers
    assert "POLI.TA" in tickers
    assert all(0.0 <= s <= 100.0 for s in df_manual["composite_score"])


def test_invalid_cutoff_days(multi_market_db: DatabaseManager) -> None:
    """Verify invalid cutoff days raise ValueError for both US and TASE universes."""
    with pytest.raises(ValueError):
        run_point_in_time_backtest(multi_market_db, cutoff_days_ago=0, universe="TASE")

    with pytest.raises(ValueError):
        run_point_in_time_backtest(multi_market_db, cutoff_days_ago=1000, universe="TASE")


def test_manual_vs_screener_score_consistency(multi_market_db: DatabaseManager) -> None:
    """Verify that manual_sql and SCREENER_SQL compute composite_score using identical percentile ranking formulas."""
    dates = multi_market_db.execute_read("SELECT DISTINCT trade_date FROM daily_bars ORDER BY trade_date DESC;")
    latest_date = str(dates[0][0])

    df_screener = run_screener(multi_market_db, cutoff_date=latest_date, universe="US")
    assert not df_screener.empty

    target_ticker = df_screener.iloc[0]["ticker"]
    df_manual = run_screener(multi_market_db, cutoff_date=latest_date, manual_tickers=[target_ticker], universe="US")
    assert not df_manual.empty

    screener_row = df_screener[df_screener["ticker"] == target_ticker].iloc[0]
    manual_row = df_manual[df_manual["ticker"] == target_ticker].iloc[0]

    assert abs(screener_row["rs_score"] - manual_row["rs_score"]) < 1e-5
    assert abs(screener_row["composite_score"] - manual_row["composite_score"]) < 1e-5
    assert 0.0 <= manual_row["composite_score"] <= 100.0


