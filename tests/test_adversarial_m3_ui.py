"""Empirical Adversarial Stress Test Suite for Milestone 3 (Streamlit UI Dedicated TASE Section).

Author: Challenger M3_1
Target Modules:
- src/ui/app.py
- src/test_cli_ui.py
"""

from __future__ import annotations

import datetime
import html
from pathlib import Path
from typing import Any
import concurrent.futures
import numpy as np
import pandas as pd
import pytest
import streamlit as st

from src.db.db_manager import DatabaseManager
from src.ui.app import (
    build_html_table,
    check_db_availability,
    format_company_name,
    get_db_manager,
    inject_custom_css,
    is_medical_pharma,
    is_tase_ticker,
    render_backtest_view,
    render_live_recommendations,
)


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    """Fixture to provide temporary DuckDB path."""
    return tmp_path / "test_market_ui_stress.duckdb"


@pytest.fixture
def populated_dual_universe_db(temp_db: Path) -> DatabaseManager:
    """Fixture providing DatabaseManager with comprehensive US & TASE test data."""
    db_mgr = DatabaseManager(db_path=temp_db, read_only=False)

    with db_mgr.write_cursor() as conn:
        # Insert symbol metadata
        conn.execute(
            """
            INSERT INTO symbol_metadata (ticker, name, exchange, asset_class, is_active, market_cap)
            VALUES 
                ('SPY', 'SPDR S&P 500 ETF Trust', 'NYSE', 'ETF', True, 500000000000.0),
                ('AAPL', 'Apple Inc.', 'NASDAQ', 'Common Stock', True, 3000000000000.0),
                ('MRNA', 'Moderna Therapeutics Inc.', 'NASDAQ', 'Common Stock', True, 45000000000.0),
                ('^TA125.TA', 'TA-125 Index Benchmark', 'TASE', 'Index', True, 0.0),
                ('DSCT.TA', 'Israel Discount Bank Ltd', 'TASE', 'Common Stock', True, 35000000000.0),
                ('TEVA.TA', 'Teva Pharmaceutical Industries', 'TASE', 'Common Stock', True, 55000000000.0),
                ('TLV.TA', 'Tel Aviv Stock Exchange Ltd', 'TASE', 'Common Stock', True, 12000000000.0);
            """
        )

        base_date = datetime.date(2025, 1, 1)
        bars = []
        for i in range(300):
            t_date = base_date + datetime.timedelta(days=i)
            # US stocks
            bars.append(("SPY", t_date, 500.0 + i * 0.2, 505.0 + i * 0.2, 498.0 + i * 0.2, 502.0 + i * 0.2, 502.0 + i * 0.2, 5000000))
            bars.append(("AAPL", t_date, 150.0 + i * 0.5, 152.0 + i * 0.5, 149.0 + i * 0.5, 151.0 + i * 0.5, 151.0 + i * 0.5, 10000000))
            bars.append(("MRNA", t_date, 100.0 + i * 0.4, 103.0 + i * 0.4, 98.0 + i * 0.4, 102.0 + i * 0.4, 102.0 + i * 0.4, 8000000))
            
            # TASE stocks (Prices in Agorot)
            bars.append(("^TA125.TA", t_date, 2000.0 + i * 1.5, 2015.0 + i * 1.5, 1990.0 + i * 1.5, 2005.0 + i * 1.5, 2005.0 + i * 1.5, 2000000))
            bars.append(("DSCT.TA", t_date, 2500.0 + i * 3.0, 2530.0 + i * 3.0, 2480.0 + i * 3.0, 2510.0 + i * 3.0, 2510.0 + i * 3.0, 15000000))
            bars.append(("TEVA.TA", t_date, 6000.0 + i * 5.0, 6080.0 + i * 5.0, 5950.0 + i * 5.0, 6040.0 + i * 5.0, 6040.0 + i * 5.0, 25000000))
            bars.append(("TLV.TA", t_date, 3000.0 + i * 2.5, 3040.0 + i * 2.5, 2970.0 + i * 2.5, 3020.0 + i * 2.5, 3020.0 + i * 2.5, 5000000))

        conn.executemany(
            """
            INSERT INTO daily_bars (ticker, trade_date, open, high, low, close, adj_close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            bars,
        )

    return db_mgr


class TestHTMLTableAdversarialEdgeCases:
    """Stress test build_html_table under corrupt, NaN, extreme, and malicious inputs."""

    def test_completely_empty_dataframe(self) -> None:
        """Verify empty DataFrame returns benign placeholder without raising."""
        df = pd.DataFrame()
        for is_bt in (True, False):
            for is_tase in (True, False):
                res = build_html_table(df, is_backtest=is_bt, is_tase=is_tase)
                assert "<div class='custom-table-container'" in res
                assert "No tickers in this category." in res

    def test_missing_optional_and_required_columns(self) -> None:
        """Verify handling of missing non-ticker columns without crashing."""
        df = pd.DataFrame([{"ticker": "BARE_TICKER"}])
        res_screener = build_html_table(df, is_backtest=False, is_tase=False)
        assert "BARE_TICKER" in res_screener
        assert "N/A" in res_screener

        res_bt = build_html_table(df, is_backtest=True, is_tase=True)
        assert "BARE_TICKER" in res_bt
        assert "TA-125 Return (%)" in res_bt

    def test_all_nan_and_none_values(self) -> None:
        """Verify all-NaN/None row does not raise TypeError or string formatting errors."""
        df = pd.DataFrame([{
            "ticker": "NANDATA",
            "name": None,
            "market_cap_str": None,
            "close": np.nan,
            "ADV20": None,
            "rs_score": np.nan,
            "tightness_ratio": np.nan,
            "pct_off_52w_high": np.nan,
            "composite_score": np.nan,
            "entry_price": np.nan,
            "exit_price": np.nan,
            "return_pct": np.nan,
            "ta125_return_pct": np.nan,
            "spy_return_pct": np.nan,
            "alpha_pct": np.nan,
            "max_drawdown_pct": np.nan,
            "win_status": None,
            "is_win": None,
        }])
        
        res_s = build_html_table(df, is_backtest=False, is_tase=False)
        assert "NANDATA" in res_s
        assert "N/A" in res_s

        res_bt = build_html_table(df, is_backtest=True, is_tase=True)
        assert "NANDATA" in res_bt
        assert "N/A" in res_bt

    def test_nan_name_string_coercion_flaw(self) -> None:
        """Demonstrate that np.nan in 'name' column evaluates to ticker symbol rather than 'nan' string."""
        df = pd.DataFrame([{
            "ticker": "AAPL",
            "name": np.nan,
            "market_cap_str": "N/A",
            "close": 150.0,
            "ADV20": "N/A",
            "rs_score": 1.0,
            "tightness_ratio": 1.0,
            "pct_off_52w_high": -1.0,
            "composite_score": 50.0,
        }])
        res = build_html_table(df, is_backtest=False, is_tase=False)
        assert ">nan</a>" not in res
        assert ">AAPL</a>" in res

    def test_extreme_numeric_values_inf_overflow(self) -> None:
        """Verify infinite and extreme values format cleanly without unhandled exceptions."""
        df = pd.DataFrame([{
            "ticker": "EXTREME",
            "name": "Extreme Corp",
            "market_cap_str": "$999.99B",
            "close": float("inf"),
            "ADV20": "9999.9M Ag.",
            "rs_score": float("-inf"),
            "tightness_ratio": 1e12,
            "pct_off_52w_high": -1e-8,
            "composite_score": 100.0,
            "entry_price": float("inf"),
            "exit_price": 0.00001,
            "return_pct": float("-inf"),
            "ta125_return_pct": 1e6,
            "alpha_pct": float("inf"),
            "max_drawdown_pct": -99.999,
            "win_status": "🟢 WIN",
            "is_win": True,
        }])

        res_s = build_html_table(df, is_backtest=False, is_tase=True)
        assert "EXTREME" in res_s
        assert "inf Ag." in res_s

        res_bt = build_html_table(df, is_backtest=True, is_tase=False)
        assert "EXTREME" in res_bt
        assert "Extreme Corp" in res_bt

    def test_unicode_and_hebrew_company_names(self) -> None:
        """Verify non-ASCII / Hebrew names and characters render properly in HTML."""
        df = pd.DataFrame([{
            "ticker": "DSCT.TA",
            "name": "בנק דיסקונט לישראל בע\"מ",
            "market_cap_str": "35.00B Ag.",
            "close": 2500.0,
            "ADV20": "25.0M Ag.",
            "rs_score": 1.5,
            "tightness_ratio": 2.0,
            "pct_off_52w_high": -3.5,
            "composite_score": 92.5,
        }])
        res = build_html_table(df, is_backtest=False, is_tase=True)
        assert "בנק דיסקונט לישראל" in res
        assert "2,500.00 Ag." in res


class TestViewALiveRecommendationsAdversarial:
    """Stress test View A Live recommendations with varied database states."""

    def test_view_a_with_populated_dual_universe(
        self, populated_dual_universe_db: DatabaseManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify View A executes both US and TASE screeners and produces both sections."""
        markdown_outputs = []
        download_buttons = []

        monkeypatch.setattr(st, "markdown", lambda body, *a, **kw: markdown_outputs.append(str(body)))
        monkeypatch.setattr(st, "header", lambda *a, **kw: None)
        monkeypatch.setattr(st, "subheader", lambda *a, **kw: None)
        monkeypatch.setattr(st, "caption", lambda *a, **kw: None)
        monkeypatch.setattr(st, "warning", lambda *a, **kw: None)
        monkeypatch.setattr(st, "info", lambda *a, **kw: None)
        monkeypatch.setattr(st, "error", lambda msg, *a, **kw: pytest.fail(f"Unexpected st.error: {msg}"))
        monkeypatch.setattr(
            st,
            "download_button",
            lambda label, data, file_name, *a, **kw: download_buttons.append((label, file_name, data)),
        )

        read_only_mgr = DatabaseManager(db_path=populated_dual_universe_db.db_path, read_only=True)
        latest_date = check_db_availability(read_only_mgr)
        assert latest_date is not None

        render_live_recommendations(
            read_only_mgr,
            latest_date=latest_date,
            min_price=0.0,
            min_adv20=0.0,
            max_tightness=100.0,
            pct_off_low=0.0,
            pct_within_high=100.0,
        )

        rendered_all = "\n".join(markdown_outputs)
        assert "title-tase" in rendered_all
        assert "Category 3: Tel Aviv Stock Exchange" in rendered_all
        assert len(download_buttons) >= 2  # US CSV and TASE CSV export buttons

    def test_view_a_zero_us_qualifying_skips_tase_bug(
        self, populated_dual_universe_db: DatabaseManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify that 0 US qualifying stocks does NOT skip TASE section in View A."""
        warnings = []
        markdown_outputs = []

        monkeypatch.setattr(st, "warning", lambda msg: warnings.append(str(msg)))
        monkeypatch.setattr(st, "markdown", lambda body, *a, **kw: markdown_outputs.append(str(body)))
        monkeypatch.setattr(st, "header", lambda *a, **kw: None)
        monkeypatch.setattr(st, "subheader", lambda *a, **kw: None)
        monkeypatch.setattr(st, "caption", lambda *a, **kw: None)
        monkeypatch.setattr(st, "download_button", lambda *a, **kw: None)

        read_only_mgr = DatabaseManager(db_path=populated_dual_universe_db.db_path, read_only=True)

        # Force US screener to return 0 stocks using impossible min_price
        render_live_recommendations(read_only_mgr, latest_date="2025-10-27", min_price=1000000.0)

        # Verify that TASE is rendered and warning was displayed for US
        rendered_all = "\n".join(markdown_outputs)
        assert "Category 3: Tel Aviv Stock Exchange" in rendered_all
        assert any("No stocks passed all screening filters" in w for w in warnings)


class TestBacktestViewAdversarial:
    """Stress test render_backtest_view under missing data, partial data, and zero allocations."""

    def test_backtest_view_unbound_local_error_proof(
        self, populated_dual_universe_db: DatabaseManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify render_backtest_view executes cleanly without UnboundLocalError when US backtest produces 0 positions."""
        markdown_outputs = []
        infos = []

        monkeypatch.setattr(st, "markdown", lambda body, *a, **kw: markdown_outputs.append(str(body)))
        monkeypatch.setattr(st, "header", lambda *a, **kw: None)
        monkeypatch.setattr(st, "subheader", lambda *a, **kw: None)
        monkeypatch.setattr(st, "caption", lambda *a, **kw: None)
        monkeypatch.setattr(st, "info", lambda msg: infos.append(str(msg)))
        monkeypatch.setattr(st, "download_button", lambda *a, **kw: None)

        read_only_mgr = DatabaseManager(db_path=populated_dual_universe_db.db_path, read_only=True)

        # When pct_off_low=999999.0 is passed, US backtest produces 0 positions
        render_backtest_view(
            read_only_mgr,
            cutoff_days_ago=5,
            max_tightness=0.0001,
            pct_off_low=999999.0,
        )

        rendered_all = "\n".join(markdown_outputs)
        assert "$10,000 Investment Benchmark Comparison" in rendered_all
        assert any("No US position data available" in msg for msg in infos)

    def test_backtest_view_all_three_views_b_c_e_success_path(
        self, populated_dual_universe_db: DatabaseManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify View B, C, and E execute and generate benchmark cards when positions exist."""
        markdown_outputs = []
        download_buttons = []

        monkeypatch.setattr(st, "markdown", lambda body, *a, **kw: markdown_outputs.append(str(body)))
        monkeypatch.setattr(st, "header", lambda *a, **kw: None)
        monkeypatch.setattr(st, "subheader", lambda *a, **kw: None)
        monkeypatch.setattr(st, "caption", lambda *a, **kw: None)
        monkeypatch.setattr(st, "info", lambda *a, **kw: None)
        monkeypatch.setattr(
            st,
            "download_button",
            lambda label, data, file_name, key, *a, **kw: download_buttons.append((label, file_name, key)),
        )

        read_only_mgr = DatabaseManager(db_path=populated_dual_universe_db.db_path, read_only=True)

        # 1. View B (1-Week)
        render_backtest_view(
            read_only_mgr,
            cutoff_days_ago=5,
            view_label="View B: 1-Week Backtest",
            min_price=0.0,
            min_adv20=0.0,
            max_tightness=100.0,
            pct_off_low=0.0,
            pct_within_high=100.0,
        )

        # 2. View C (1-Month)
        render_backtest_view(
            read_only_mgr,
            cutoff_days_ago=22,
            view_label="View C: 1-Month Backtest",
            min_price=0.0,
            min_adv20=0.0,
            max_tightness=100.0,
            pct_off_low=0.0,
            pct_within_high=100.0,
        )

        # 3. View E (Custom Date)
        render_backtest_view(
            read_only_mgr,
            custom_cutoff_date="2025-08-01",
            view_label="View E: Custom Date Backtest",
            min_price=0.0,
            min_adv20=0.0,
            max_tightness=100.0,
            pct_off_low=0.0,
            pct_within_high=100.0,
        )

        rendered_str = "\n".join(markdown_outputs)
        assert "portfolio-card-tase" in rendered_str
        assert "^TA125.TA Index" in rendered_str
        assert "5x $2,000 TASE Stock Picks" in rendered_str
        assert "Net TASE Alpha vs ^TA125.TA" in rendered_str

        # Check unique download button keys
        keys = [k[2] for k in download_buttons]
        assert len(keys) == len(set(keys)), "Download button keys must be globally unique across views"


class TestViewDDiagnosticsAdversarial:
    """Stress test View D manual analysis with mixed universes, invalid tickers, and edge cases."""

    def test_mixed_us_and_tase_manual_tickers_diagnostics(
        self, populated_dual_universe_db: DatabaseManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify mixed input (US + TASE + Bio) correctly routes 8-point checklist and sub-tables."""
        from src.engine.screener_queries import run_screener

        read_only_mgr = DatabaseManager(db_path=populated_dual_universe_db.db_path, read_only=True)
        cutoff_date = "2025-10-27"
        manual_tickers = ["AAPL", "MRNA", "DSCT.TA", "TEVA.TA"]

        df_manual = run_screener(
            read_only_mgr,
            cutoff_date=cutoff_date,
            manual_tickers=manual_tickers,
            min_price=0.0,
            min_adv20=0.0,
            max_tightness=100.0,
            pct_off_low=0.0,
            pct_within_high=100.0,
        )

        assert not df_manual.empty
        tickers_found = set(df_manual["ticker"].tolist())
        assert "AAPL" in tickers_found
        assert "DSCT.TA" in tickers_found
        assert "TEVA.TA" in tickers_found

        # Evaluate TASE vs US separation logic as in View D
        df_manual["is_tase"] = df_manual["ticker"].apply(is_tase_ticker)
        df_manual["is_med_pharma"] = df_manual.apply(
            lambda r: is_medical_pharma(str(r.get("name") or ""), str(r["ticker"])), axis=1
        )

        df_other = df_manual[(~df_manual["is_med_pharma"]) & (~df_manual["is_tase"])]
        df_med = df_manual[(df_manual["is_med_pharma"]) & (~df_manual["is_tase"])]
        df_tase = df_manual[df_manual["is_tase"]]

        assert "AAPL" in df_other["ticker"].values
        assert "MRNA" in df_med["ticker"].values
        assert "DSCT.TA" in df_tase["ticker"].values
        assert "TEVA.TA" in df_tase["ticker"].values

    def test_8_point_checklist_boundary_evaluations(self) -> None:
        """Verify 8-point checklist exact boundary thresholds for both US and TASE."""
        # TASE Stock DSCT.TA on boundary
        is_tase_item = True
        close_val = 100.0  # Exactly 100 Ag.
        adv_val = 20000000.0  # Exactly 20M Ag.
        sma50_val = 99.0
        sma150_val = 98.0
        sma200_val = 97.0
        sma200_20d_val = 96.0
        low52_val = 76.923  # close >= 1.30 * low52
        high52_val = 133.333  # close >= 0.75 * high52
        tight_val = 3.5  # Exactly 3.5 ceiling
        rs_val = 0.0001  # > 0.0

        p_price = pd.notna(close_val) and (close_val >= 100.0 if is_tase_item else close_val >= 10.0)
        p_adv = pd.notna(adv_val) and adv_val >= 20000000.0
        p_ma = pd.notna(close_val) and pd.notna(sma50_val) and pd.notna(sma150_val) and pd.notna(sma200_val) and (close_val > sma50_val > sma150_val > sma200_val)
        p_slope = pd.notna(sma200_val) and pd.notna(sma200_20d_val) and sma200_val > sma200_20d_val
        p_low52 = pd.notna(close_val) and pd.notna(low52_val) and close_val >= 1.30 * low52_val
        p_high52 = pd.notna(close_val) and pd.notna(high52_val) and close_val >= 0.75 * high52_val
        p_tight = pd.notna(tight_val) and tight_val <= 3.5
        p_rs = pd.notna(rs_val) and rs_val > 0.0

        assert p_price is True
        assert p_adv is True
        assert p_ma is True
        assert p_slope is True
        assert p_low52 is True
        assert p_high52 is True
        assert p_tight is True
        assert p_rs is True
        assert sum([p_price, p_adv, p_ma, p_slope, p_low52, p_high52, p_tight, p_rs]) == 8

        # Fails price floor
        assert (99.99 >= 100.0 if is_tase_item else 99.99 >= 10.0) is False
        # Fails tightness ceiling
        assert (3.51 <= 3.5) is False
        # Fails RS
        assert (-0.001 > 0.0) is False


class TestCSSAndLayoutDesignStandards:
    """Stress test styling, palette consistency, and visual token conformance."""

    def test_css_classes_and_color_palette(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify CSS injection contains all required high-contrast TASE design tokens."""
        css_blocks = []
        monkeypatch.setattr(st, "markdown", lambda body, *a, **kw: css_blocks.append(str(body)))

        inject_custom_css()
        assert len(css_blocks) == 1
        css = css_blocks[0]

        # Verify TASE title bar styling
        assert ".title-tase" in css
        assert "background-color: #eef5fc;" in css
        assert "color: #0b4f8a;" in css
        assert "border-left: 5px solid #0b4f8a;" in css

        # Verify TASE portfolio card styling
        assert ".portfolio-card-tase" in css
        assert "border: 1px solid #b6d4fe;" in css
        assert "border-left: 4px solid #0b4f8a;" in css
        assert "background-color: #f7faff;" in css

        # Verify Typography & Numerals
        assert "font-variant-numeric: tabular-nums;" in css
        assert "'JetBrains Mono', monospace" in css


class TestEmptyDatabaseAndSchemaAnomalies:
    """Stress test UI views against empty, partially unseeded, and corrupt databases."""

    def test_view_a_with_empty_database(self, temp_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify render_live_recommendations gracefully handles an empty database."""
        db_mgr = DatabaseManager(db_path=temp_db, read_only=False)
        read_only_mgr = DatabaseManager(db_path=temp_db, read_only=True)
        warnings = []
        infos = []
        errors = []

        monkeypatch.setattr(st, "markdown", lambda *a, **kw: None)
        monkeypatch.setattr(st, "header", lambda *a, **kw: None)
        monkeypatch.setattr(st, "subheader", lambda *a, **kw: None)
        monkeypatch.setattr(st, "caption", lambda *a, **kw: None)
        monkeypatch.setattr(st, "warning", lambda msg: warnings.append(str(msg)))
        monkeypatch.setattr(st, "info", lambda msg: infos.append(str(msg)))
        monkeypatch.setattr(st, "error", lambda msg: errors.append(str(msg)))
        monkeypatch.setattr(st, "download_button", lambda *a, **kw: None)

        # Execute View A with nonexistent trade date on empty DB
        render_live_recommendations(read_only_mgr, latest_date="2025-01-01")

        assert len(warnings) >= 1 or len(infos) >= 1

    def test_backtest_view_with_empty_database(self, temp_db: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify render_backtest_view gracefully handles an empty database without unhandled exceptions."""
        db_mgr = DatabaseManager(db_path=temp_db, read_only=False)
        read_only_mgr = DatabaseManager(db_path=temp_db, read_only=True)
        infos = []

        monkeypatch.setattr(st, "markdown", lambda *a, **kw: None)
        monkeypatch.setattr(st, "header", lambda *a, **kw: None)
        monkeypatch.setattr(st, "subheader", lambda *a, **kw: None)
        monkeypatch.setattr(st, "caption", lambda *a, **kw: None)
        monkeypatch.setattr(st, "info", lambda msg: infos.append(str(msg)))
        monkeypatch.setattr(st, "download_button", lambda *a, **kw: None)

        render_backtest_view(read_only_mgr, cutoff_days_ago=5, view_label="View B: 1-Week Backtest")
        assert any("No US position data available" in m for m in infos)
        assert any("No TASE position data available" in m for m in infos)


class TestSingleElementAndFewElementAllocations:
    """Stress test allocation math, table rendering, and metrics for 1 to 4 positions."""

    @pytest.mark.parametrize("num_positions", [1, 2, 3, 4])
    def test_backtest_us_and_tase_single_and_few_element_baskets(
        self, num_positions: int, populated_dual_universe_db: DatabaseManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify that small portfolios (1-4 picks) compute exact equal-weight allocations without zero-division."""
        markdown_outputs = []
        monkeypatch.setattr(st, "markdown", lambda body, *a, **kw: markdown_outputs.append(str(body)))
        monkeypatch.setattr(st, "header", lambda *a, **kw: None)
        monkeypatch.setattr(st, "subheader", lambda *a, **kw: None)
        monkeypatch.setattr(st, "caption", lambda *a, **kw: None)
        monkeypatch.setattr(st, "info", lambda *a, **kw: None)
        monkeypatch.setattr(st, "download_button", lambda *a, **kw: None)

        read_only_mgr = DatabaseManager(db_path=populated_dual_universe_db.db_path, read_only=True)

        from src.ui import app

        def mock_backtest(db, cutoff_days_ago=5, universe="US", **kw):
            tickers = ["AAPL", "MRNA", "NVDA", "AMZN"][:num_positions] if universe == "US" else ["DSCT.TA", "TEVA.TA", "TLV.TA", "NICE.TA"][:num_positions]
            rows = []
            for t in tickers:
                rows.append({
                    "ticker": t,
                    "name": f"Company {t}",
                    "market_cap": 1000000000.0,
                    "entry_price": 100.0,
                    "exit_price": 110.0,
                    "return_pct": 10.0,
                    "spy_return_pct": 2.0,
                    "ta125_return_pct": 3.0,
                    "alpha_pct": 8.0,
                    "max_drawdown_pct": -2.0,
                    "is_win": True,
                })
            df_pos = pd.DataFrame(rows)
            return {
                "cutoff_date": "2025-06-01",
                "evaluation_date": "2025-06-08",
                "positions_df": df_pos,
                "mean_basket_return": 0.10,
                "spy_return": 0.02,
                "ta125_return": 0.03,
                "benchmark_return": 0.03,
                "basket_alpha": 0.08,
                "win_rate": 1.0,
                "avg_max_drawdown": -2.0,
            }

        monkeypatch.setattr(app, "run_point_in_time_backtest", mock_backtest)

        render_backtest_view(read_only_mgr, cutoff_days_ago=5)
        rendered = "\n".join(markdown_outputs)

        # For 10% return on $10k, total value should be $11,000.00
        assert "$11,000.00" in rendered
        assert "portfolio-card-tase" in rendered


class TestCorruptedDataFramesAndEdgeValues:
    """Stress test build_html_table and format_company_name with corrupted and adversarial data types."""

    def test_format_company_name_exhaustive_matrix(self) -> None:
        """Verify format_company_name handles all variants of empty, None, NaN, and whitespace."""
        assert format_company_name(None, "TICK") == "TICK"
        assert format_company_name(np.nan, "TICK") == "TICK"
        assert format_company_name(float("nan"), "TICK") == "TICK"
        assert format_company_name("nan", "TICK") == "TICK"
        assert format_company_name("NAN", "TICK") == "TICK"
        assert format_company_name(" NaN ", "TICK") == "TICK"
        assert format_company_name("", "TICK") == "TICK"
        assert format_company_name("   ", "TICK") == "TICK"
        assert format_company_name("Apple Inc.", "AAPL") == "Apple Inc."
        assert format_company_name(" בנק דיסקונט ", "DSCT.TA") == "בנק דיסקונט"
        assert format_company_name(12345, "TICK") == "12345"

    def test_build_html_table_extreme_bounds_and_corrupt_types(self) -> None:
        """Verify build_html_table survives extreme numbers, negative prices, and unexpected types."""
        df_corrupt = pd.DataFrame([
            {
                "ticker": "CORRUPT1",
                "name": "Corrupt Corp",
                "market_cap_str": "$0.00M",
                "close": -50.0,
                "ADV20": "0.0 Ag.",
                "rs_score": -99999.0,
                "tightness_ratio": -1.0,
                "pct_off_52w_high": -100.0,
                "composite_score": 0.0,
                "entry_price": 0.0,
                "exit_price": 0.0,
                "return_pct": -100.0,
                "ta125_return_pct": 0.0,
                "spy_return_pct": 0.0,
                "alpha_pct": -100.0,
                "max_drawdown_pct": -100.0,
                "win_status": "🔴 LOSS",
                "is_win": False,
            },
            {
                "ticker": "HUGE1",
                "name": "Mega Corp",
                "market_cap_str": "$99999.99B",
                "close": 1000000.0,
                "ADV20": "99999.0M Ag.",
                "rs_score": 99999.0,
                "tightness_ratio": 0.01,
                "pct_off_52w_high": 0.0,
                "composite_score": 100.0,
                "entry_price": 1000000.0,
                "exit_price": 2000000.0,
                "return_pct": 100000.0,
                "ta125_return_pct": 50000.0,
                "spy_return_pct": 50000.0,
                "alpha_pct": 50000.0,
                "max_drawdown_pct": 0.0,
                "win_status": "🟢 WIN",
                "is_win": True,
            },
        ])

        html_s = build_html_table(df_corrupt, is_backtest=False, is_tase=True)
        assert "CORRUPT1" in html_s
        assert "HUGE1" in html_s

        html_bt = build_html_table(df_corrupt, is_backtest=True, is_tase=True)
        assert "-100.00%" in html_bt
        assert "+100000.00%" in html_bt


class TestConcurrentMultiThreadedUIRendering:
    """Stress test UI components under concurrent / multi-threaded execution."""

    def test_concurrent_html_table_generation(self) -> None:
        """Verify thread-safety of build_html_table and format_company_name under concurrent workers."""
        df_sample = pd.DataFrame([
            {"ticker": f"TICK{i}", "name": f"Name {i}", "close": 100.0 + i, "market_cap_str": "$1.0B", "ADV20": "25M", "rs_score": 1.0, "tightness_ratio": 2.0, "pct_off_52w_high": -5.0, "composite_score": 80.0}
            for i in range(10)
        ])

        def worker_task(idx: int) -> str:
            return build_html_table(df_sample, is_backtest=(idx % 2 == 0), is_tase=(idx % 3 == 0))

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(worker_task, i) for i in range(50)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        assert len(results) == 50
        assert all("custom-table-container" in r for r in results)

