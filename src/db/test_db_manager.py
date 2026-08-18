"""Unit tests for DatabaseManager and DuckDB schema."""

import os
from pathlib import Path
import tempfile
import pytest

from src.db.db_manager import DatabaseManager


def test_schema_initialization():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_market_data.duckdb"
        db_mgr = DatabaseManager(db_path=db_path)

        # Verify tables created
        tables = db_mgr.execute_read("SHOW TABLES;")
        table_names = [t[0] for t in tables]
        assert "symbol_metadata" in table_names
        assert "daily_bars" in table_names
        assert "point_in_time_runs" in table_names

        # Verify symbol_metadata schema
        cols = db_mgr.execute_read("DESCRIBE symbol_metadata;")
        col_dict = {col[0]: col[1] for col in cols}
        assert "ticker" in col_dict
        assert "name" in col_dict
        assert "exchange" in col_dict
        assert "asset_class" in col_dict
        assert "is_active" in col_dict
        assert "first_added_date" in col_dict
        assert "last_updated_date" in col_dict

        # Verify daily_bars schema
        cols = db_mgr.execute_read("DESCRIBE daily_bars;")
        col_dict = {col[0]: col[1] for col in cols}
        assert "ticker" in col_dict
        assert "trade_date" in col_dict
        assert "open" in col_dict
        assert "high" in col_dict
        assert "low" in col_dict
        assert "close" in col_dict
        assert "adj_close" in col_dict
        assert "volume" in col_dict

        # Verify point_in_time_runs schema
        cols = db_mgr.execute_read("DESCRIBE point_in_time_runs;")
        col_dict = {col[0]: col[1] for col in cols}
        assert "run_id" in col_dict
        assert "run_date" in col_dict
        assert "cutoff_date" in col_dict
        assert "scan_type" in col_dict
        assert "top_tickers" in col_dict


def test_read_write_operations():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_rw.duckdb"
        db_mgr = DatabaseManager(db_path=db_path)

        # Write symbol metadata
        db_mgr.execute_write(
            """
            INSERT INTO symbol_metadata (ticker, name, exchange, asset_class, is_active, first_added_date, last_updated_date)
            VALUES ('AAPL', 'Apple Inc.', 'NASDAQ', 'Common Stock', true, '2026-01-01', '2026-08-18')
            """
        )

        # Read back
        res = db_mgr.execute_read("SELECT ticker, name, is_active FROM symbol_metadata WHERE ticker = 'AAPL';")
        assert len(res) == 1
        assert res[0] == ("AAPL", "Apple Inc.", True)


def test_context_managers():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_cm.duckdb"
        db_mgr = DatabaseManager(db_path=db_path)

        with db_mgr.write_cursor() as conn:
            conn.execute("INSERT INTO daily_bars VALUES ('AAPL', '2026-08-18', 150.0, 155.0, 149.0, 154.0, 154.0, 1000000);")

        with db_mgr.read_cursor() as conn:
            row = conn.execute("SELECT ticker, close, volume FROM daily_bars WHERE ticker = 'AAPL';").fetchone()
            assert row == ("AAPL", 154.0, 1000000)
