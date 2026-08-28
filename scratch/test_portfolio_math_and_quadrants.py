"""Empirical Stress Test Harness for Portfolio Math, 4-Quadrant Alpha, and Multi-Universe Separation."""

import datetime
from pathlib import Path
import tempfile
import numpy as np
import pandas as pd
import pytest

from src.db.db_manager import DatabaseManager
from src.engine.backtest_engine import run_point_in_time_backtest
from src.engine.screener_queries import run_screener
from src.ui.app import (
    build_html_table,
    format_company_name,
    is_tase_ticker,
    render_backtest_view,
    render_live_recommendations,
)


def create_quadrant_scenario_db(
    tase_returns: list[float],
    ta125_return: float,
    us_returns: list[float],
    spy_return: float,
) -> DatabaseManager:
    """Creates a temporary database populated with specific forward price returns."""
    tmpdir = tempfile.mkdtemp()
    db_path = Path(tmpdir) / "scenario.duckdb"
    db_mgr = DatabaseManager(db_path=db_path, read_only=False)

    num_days = 270
    start_date = datetime.date(2025, 1, 1)
    dates = [start_date + datetime.timedelta(days=i) for i in range(num_days)]
    cutoff_idx = num_days - 6  # T-5 trading days
    cutoff_date = str(dates[cutoff_idx])
    eval_date = str(dates[-1])

    # Symbols
    metadata = [
        ("SPY", "SPDR S&P 500 ETF", "NYSE", "ETF", True),
        ("^TA125.TA", "TA-125 Index Benchmark", "TASE", "Index", True),
    ]
    for i in range(len(us_returns)):
        metadata.append((f"US_{i+1}", f"US Stock {i+1}", "NASDAQ", "Common Stock", True))
    for i in range(len(tase_returns)):
        metadata.append((f"TASE_{i+1}.TA", f"TASE Stock {i+1}", "TASE", "Common Stock", True))

    with db_mgr.write_cursor() as conn:
        conn.executemany(
            "INSERT INTO symbol_metadata (ticker, name, exchange, asset_class, is_active) VALUES (?, ?, ?, ?, ?);",
            metadata,
        )

        bars = []

        # SPY bars
        for idx, d in enumerate(dates):
            d_str = str(d)
            if idx <= cutoff_idx:
                p = 500.0 + (idx * 0.1)
            else:
                p_cutoff = 500.0 + (cutoff_idx * 0.1)
                frac = (idx - cutoff_idx) / (num_days - 1 - cutoff_idx)
                p = p_cutoff * (1.0 + frac * spy_return)
            bars.append(("SPY", d_str, p, p + 1, p - 1, p, p, 10000000))

        # TA-125 bars
        for idx, d in enumerate(dates):
            d_str = str(d)
            if idx <= cutoff_idx:
                p = 2000.0 + (idx * 0.5)
            else:
                p_cutoff = 2000.0 + (cutoff_idx * 0.5)
                frac = (idx - cutoff_idx) / (num_days - 1 - cutoff_idx)
                p = p_cutoff * (1.0 + frac * ta125_return)
            bars.append(("^TA125.TA", d_str, p, p + 5, p - 5, p, p, 5000000))

        # US stocks
        for i, ret in enumerate(us_returns):
            ticker = f"US_{i+1}"
            base_p = 100.0 + (i * 10.0)
            for idx, d in enumerate(dates):
                d_str = str(d)
                if idx < cutoff_idx - 30:
                    p = base_p + (idx * 0.5)
                    h, l = p + 1.0, p - 1.0
                elif idx <= cutoff_idx:
                    p = base_p + ((cutoff_idx - 31) * 0.5)
                    h, l = p + 0.2, p - 0.2
                else:
                    p_cutoff = base_p + ((cutoff_idx - 31) * 0.5)
                    frac = (idx - cutoff_idx) / (num_days - 1 - cutoff_idx)
                    p = p_cutoff * (1.0 + frac * ret)
                    h, l = p + 0.2, p - 0.2
                bars.append((ticker, d_str, p, h, l, p, p, 2000000))

        # TASE stocks
        for i, ret in enumerate(tase_returns):
            ticker = f"TASE_{i+1}.TA"
            base_p = 2000.0 + (i * 200.0)
            for idx, d in enumerate(dates):
                d_str = str(d)
                if idx < cutoff_idx - 30:
                    p = base_p + (idx * 5.0)
                    h, l = p + 5.0, p - 5.0
                elif idx <= cutoff_idx:
                    p = base_p + ((cutoff_idx - 31) * 5.0)
                    h, l = p + 1.0, p - 1.0
                else:
                    p_cutoff = base_p + ((cutoff_idx - 31) * 5.0)
                    frac = (idx - cutoff_idx) / (num_days - 1 - cutoff_idx)
                    p = p_cutoff * (1.0 + frac * ret)
                    h, l = p + 1.0, p - 1.0
                bars.append((ticker, d_str, p, h, l, p, p, 1000000))

        conn.executemany(
            "INSERT INTO daily_bars (ticker, trade_date, open, high, low, close, adj_close, volume) VALUES (?, ?, ?, ?, ?, ?, ?, ?);",
            bars,
        )

    return db_mgr


def test_quadrant_1_bull_outperformance():
    """Quadrant 1: Bull Outperformance (Picks +15%, Benchmark +5% -> Alpha +10%)."""
    tase_returns = [0.12, 0.14, 0.15, 0.16, 0.18]  # Mean: +15.0%
    ta125_ret = 0.05  # +5.0%
    db_mgr = create_quadrant_scenario_db(tase_returns, ta125_ret, [0.08]*10, 0.05)

    res = run_point_in_time_backtest(db_mgr, cutoff_days_ago=5, universe="TASE")
    assert abs(res["mean_basket_return"] - 0.15) < 1e-4
    assert abs(res["ta125_return"] - 0.05) < 1e-4
    assert abs(res["basket_alpha"] - 0.10) < 1e-4
    assert res["win_rate"] == 100.0

    pos_df = res["positions_df"]
    assert len(pos_df) == 5
    assert all(abs(usd - 2000.0) < 1e-4 for usd in pos_df["allocation_usd"])
    assert all(abs(pct - 20.0) < 1e-4 for pct in pos_df["allocation_pct"])

    # Verify portfolio dollar values
    tase_val = sum([2000.0 * (1.0 + (r / 100.0)) for r in pos_df["return_pct"]])
    ta125_val = 10000.0 * (1.0 + 0.05)
    tase_alpha_usd = tase_val - ta125_val
    assert abs(tase_val - 11500.0) < 1e-2
    assert abs(ta125_val - 10500.0) < 1e-2
    assert abs(tase_alpha_usd - 1000.0) < 1e-2


def test_quadrant_2_bull_underperformance():
    """Quadrant 2: Bull Underperformance (Picks +4%, Benchmark +10% -> Alpha -6%)."""
    tase_returns = [0.02, 0.03, 0.04, 0.05, 0.06]  # Mean: +4.0%
    ta125_ret = 0.10  # +10.0%
    db_mgr = create_quadrant_scenario_db(tase_returns, ta125_ret, [0.05]*10, 0.10)

    res = run_point_in_time_backtest(db_mgr, cutoff_days_ago=5, universe="TASE")
    assert abs(res["mean_basket_return"] - 0.04) < 1e-4
    assert abs(res["ta125_return"] - 0.10) < 1e-4
    assert abs(res["basket_alpha"] - (-0.06)) < 1e-4
    assert res["win_rate"] == 100.0

    pos_df = res["positions_df"]
    tase_val = sum([2000.0 * (1.0 + (r / 100.0)) for r in pos_df["return_pct"]])
    ta125_val = 10000.0 * (1.0 + 0.10)
    tase_alpha_usd = tase_val - ta125_val
    assert abs(tase_val - 10400.0) < 1e-2
    assert abs(ta125_val - 11000.0) < 1e-2
    assert abs(tase_alpha_usd - (-600.0)) < 1e-2


def test_quadrant_3_bear_outperformance_capital_preservation():
    """Quadrant 3: Bear Outperformance / Capital Preservation (Picks -2%, Benchmark -12% -> Alpha +10%)."""
    tase_returns = [-0.01, -0.02, -0.02, -0.02, -0.03]  # Mean: -2.0%
    ta125_ret = -0.12  # -12.0%
    db_mgr = create_quadrant_scenario_db(tase_returns, ta125_ret, [-0.05]*10, -0.12)

    res = run_point_in_time_backtest(db_mgr, cutoff_days_ago=5, universe="TASE")
    assert abs(res["mean_basket_return"] - (-0.02)) < 1e-4
    assert abs(res["ta125_return"] - (-0.12)) < 1e-4
    assert abs(res["basket_alpha"] - 0.10) < 1e-4
    assert res["win_rate"] == 0.0  # All lost money nominally, but beat index!

    pos_df = res["positions_df"]
    tase_val = sum([2000.0 * (1.0 + (r / 100.0)) for r in pos_df["return_pct"]])
    ta125_val = 10000.0 * (1.0 - 0.12)
    tase_alpha_usd = tase_val - ta125_val
    assert abs(tase_val - 9800.0) < 1e-2
    assert abs(ta125_val - 8800.0) < 1e-2
    assert abs(tase_alpha_usd - 1000.0) < 1e-2  # Capital preservation alpha is +$1,000


def test_quadrant_4_bear_underperformance():
    """Quadrant 4: Bear Underperformance (Picks -18%, Benchmark -6% -> Alpha -12%)."""
    tase_returns = [-0.15, -0.16, -0.18, -0.20, -0.21]  # Mean: -18.0%
    ta125_ret = -0.06  # -6.0%
    db_mgr = create_quadrant_scenario_db(tase_returns, ta125_ret, [-0.10]*10, -0.06)

    res = run_point_in_time_backtest(db_mgr, cutoff_days_ago=5, universe="TASE")
    assert abs(res["mean_basket_return"] - (-0.18)) < 1e-4
    assert abs(res["ta125_return"] - (-0.06)) < 1e-4
    assert abs(res["basket_alpha"] - (-0.12)) < 1e-4
    assert res["win_rate"] == 0.0

    pos_df = res["positions_df"]
    tase_val = sum([2000.0 * (1.0 + (r / 100.0)) for r in pos_df["return_pct"]])
    ta125_val = 10000.0 * (1.0 - 0.06)
    tase_alpha_usd = tase_val - ta125_val
    assert abs(tase_val - 8200.0) < 1e-2
    assert abs(ta125_val - 9400.0) < 1e-2
    assert abs(tase_alpha_usd - (-1200.0)) < 1e-2


def test_multi_universe_isolation_and_benchmarks():
    """Verify US vs TASE decoupling, benchmarks, and sizing."""
    tase_returns = [0.10, 0.10, 0.10, 0.10, 0.10]
    us_returns = [0.05] * 10
    db_mgr = create_quadrant_scenario_db(tase_returns, 0.02, us_returns, 0.01)

    # 1. Run US backtest
    res_us = run_point_in_time_backtest(db_mgr, cutoff_days_ago=5, universe="US")
    assert res_us["universe"] == "US"
    assert res_us["benchmark_ticker"] == "SPY"
    assert abs(res_us["spy_return"] - 0.01) < 1e-4
    assert len(res_us["positions_df"]) == 10
    assert all(not t.endswith(".TA") for t in res_us["positions_df"]["ticker"])
    assert all(abs(usd - 1000.0) < 1e-4 for usd in res_us["positions_df"]["allocation_usd"])
    assert all(abs(pct - 10.0) < 1e-4 for pct in res_us["positions_df"]["allocation_pct"])

    # 2. Run TASE backtest
    res_tase = run_point_in_time_backtest(db_mgr, cutoff_days_ago=5, universe="TASE")
    assert res_tase["universe"] == "TASE"
    assert res_tase["benchmark_ticker"] == "^TA125.TA"
    assert abs(res_tase["ta125_return"] - 0.02) < 1e-4
    assert len(res_tase["positions_df"]) == 5
    assert all(t.endswith(".TA") for t in res_tase["positions_df"]["ticker"])
    assert all(abs(usd - 2000.0) < 1e-4 for usd in res_tase["positions_df"]["allocation_usd"])
    assert all(abs(pct - 20.0) < 1e-4 for pct in res_tase["positions_df"]["allocation_pct"])


if __name__ == "__main__":
    test_quadrant_1_bull_outperformance()
    test_quadrant_2_bull_underperformance()
    test_quadrant_3_bear_outperformance_capital_preservation()
    test_quadrant_4_bear_underperformance()
    test_multi_universe_isolation_and_benchmarks()
    print("ALL EMPIRICAL PORTFOLIO MATH & QUADRANT TESTS PASSED!")
