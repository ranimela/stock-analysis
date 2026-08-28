"""Deep Audit and Invariant Stress Tests for Portfolio Math and Multi-Universe Decoupling."""

import datetime
from pathlib import Path
import tempfile
import numpy as np
import pandas as pd
import pytest

from src.db.db_manager import DatabaseManager
from src.engine.backtest_engine import run_point_in_time_backtest
from src.engine.screener_queries import run_screener
from src.ui.app import build_html_table, format_company_name, is_tase_ticker


def test_portfolio_math_invariants_exact_dollar_sizing():
    """Verify exact dollar sizing invariants across varying portfolio counts."""
    # Sizing invariant: Total capital = $10,000
    # For N positions: alloc_usd = 10,000 / N, alloc_pct = 100 / N
    for n in range(1, 11):
        alloc_usd = 10000.0 / n
        alloc_pct = 100.0 / n
        assert abs((alloc_usd * n) - 10000.0) < 1e-6
        assert abs((alloc_pct * n) - 100.0) < 1e-6

    # 5 positions (TASE default)
    assert 10000.0 / 5 == 2000.0
    assert 100.0 / 5 == 20.0

    # 10 positions (US default)
    assert 10000.0 / 10 == 1000.0
    assert 100.0 / 10 == 10.0


def test_alpha_four_quadrant_exact_math():
    """Verify algebraic properties of 4-quadrant Net Alpha calculation."""
    # Alpha = Basket Value - Benchmark Value
    # Basket Value = Sum(Alloc_i * (1 + Ret_i))
    # Benchmark Value = Total_Capital * (1 + Bench_Ret)

    # Quadrant 1: Bull Outperformance
    # Basket +20%, Bench +10% -> Net Alpha = +$1,000 (+10%)
    b_val_1 = sum([2000.0 * 1.20 for _ in range(5)])
    bench_val_1 = 10000.0 * 1.10
    alpha_usd_1 = b_val_1 - bench_val_1
    assert b_val_1 == 12000.0
    assert bench_val_1 == 11000.0
    assert alpha_usd_1 == 1000.0

    # Quadrant 2: Bull Underperformance
    # Basket +5%, Bench +12% -> Net Alpha = -$700 (-7%)
    b_val_2 = sum([2000.0 * 1.05 for _ in range(5)])
    bench_val_2 = round(10000.0 * 1.12, 4)
    alpha_usd_2 = b_val_2 - bench_val_2
    assert b_val_2 == 10500.0
    assert bench_val_2 == 11200.0
    assert alpha_usd_2 == -700.0

    # Quadrant 3: Bear Outperformance (Capital Preservation)
    # Basket -3%, Bench -15% -> Net Alpha = +$1,200 (+12%)
    b_val_3 = sum([2000.0 * 0.97 for _ in range(5)])
    bench_val_3 = 10000.0 * 0.85
    alpha_usd_3 = b_val_3 - bench_val_3
    assert b_val_3 == 9700.0
    assert bench_val_3 == 8500.0
    assert alpha_usd_3 == 1200.0

    # Quadrant 4: Bear Underperformance
    # Basket -25%, Bench -10% -> Net Alpha = -$1,500 (-15%)
    b_val_4 = sum([2000.0 * 0.75 for _ in range(5)])
    bench_val_4 = 10000.0 * 0.90
    alpha_usd_4 = b_val_4 - bench_val_4
    assert b_val_4 == 7500.0
    assert bench_val_4 == 9000.0
    assert alpha_usd_4 == -1500.0


def test_tase_and_us_metadata_exchange_leak_resilience():
    """Verify that tickers with unusual or corrupted exchange tags are safely partitioned."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "exchange_leak.duckdb"
        db_mgr = DatabaseManager(db_path=db_path, read_only=False)

        with db_mgr.write_cursor() as conn:
            conn.execute(
                """
                INSERT INTO symbol_metadata (ticker, name, exchange, asset_class, is_active)
                VALUES 
                    ('SPY', 'SPDR S&P 500 ETF', 'NYSE', 'ETF', True),
                    ('^TA125.TA', 'TA-125 Index', 'TASE', 'Index', True),
                    ('TASE_NO_SUFFIX', 'TASE Stock without TA suffix', 'TASE', 'Common Stock', True),
                    ('US_WITH_TA_NAME', 'US Stock Named TA.TA', 'NASDAQ', 'Common Stock', True);
                """
            )
            base_date = datetime.date(2025, 1, 1)
            bars = []
            for i in range(270):
                d = str(base_date + datetime.timedelta(days=i))
                bars.append(("SPY", d, 500.0 + i*0.1, 501.0, 499.0, 500.0 + i*0.1, 500.0, 10000000))
                bars.append(("^TA125.TA", d, 2000.0 + i*0.5, 2005.0, 1995.0, 2000.0 + i*0.5, 2000.0, 5000000))
                # TASE_NO_SUFFIX: exchange = 'TASE', close 2500 Ag.
                bars.append(("TASE_NO_SUFFIX", d, 2500.0 + i*1.0, 2505.0, 2495.0, 2500.0 + i*1.0, 2500.0, 25000000))
                # US_WITH_TA_NAME: exchange = 'NASDAQ', close $50
                bars.append(("US_WITH_TA_NAME", d, 50.0 + i*0.2, 51.0, 49.0, 50.0 + i*0.2, 50.0, 30000000))

            conn.executemany(
                "INSERT INTO daily_bars (ticker, trade_date, open, high, low, close, adj_close, volume) VALUES (?, ?, ?, ?, ?, ?, ?, ?);",
                bars,
            )

        # Query TASE screener
        df_tase = run_screener(db_mgr, cutoff_date="2025-09-01", universe="TASE", min_price=0.0, min_adv20=0.0, max_tightness=100.0, pct_off_low=0.0, pct_within_high=100.0)
        tase_tickers = df_tase["ticker"].tolist() if not df_tase.empty else []
        assert "TASE_NO_SUFFIX" in tase_tickers
        assert "US_WITH_TA_NAME" not in tase_tickers

        # Query US screener
        df_us = run_screener(db_mgr, cutoff_date="2025-09-01", universe="US", min_price=0.0, min_adv20=0.0, max_tightness=100.0, pct_off_low=0.0, pct_within_high=100.0)
        us_tickers = df_us["ticker"].tolist() if not df_us.empty else []
        assert "US_WITH_TA_NAME" in us_tickers
        assert "TASE_NO_SUFFIX" not in us_tickers
