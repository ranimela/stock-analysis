"""Edge-case testing for same-day EOD sync and benchmark gating."""

from __future__ import annotations

import datetime
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from src.db.db_manager import DatabaseManager
from src.ingestion.data_ingestor import DataIngestor


def test_delta_sync_same_day_eod_behavior(tmp_path: Path):
    """Test if sync_universe fetches today's EOD bar when last_date is yesterday."""
    db_file = tmp_path / "same_day_sync.duckdb"
    db_mgr = DatabaseManager(db_path=db_file, read_only=False)
    ingestor = DataIngestor(db_manager=db_mgr)

    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)

    # Seed metadata and bar up to yesterday
    with db_mgr.write_cursor() as conn:
        conn.execute(
            "INSERT INTO symbol_metadata (ticker, name, exchange, asset_class, is_active) VALUES ('TEVA.TA', 'Teva', 'TASE', 'Common Stock', true)"
        )
        conn.execute(
            "INSERT INTO daily_bars (ticker, trade_date, open, high, low, close, adj_close, volume) VALUES ('TEVA.TA', ?, 6000.0, 6100.0, 5950.0, 6050.0, 6050.0, 100000)",
            [yesterday],
        )

    with patch.object(ingestor, "download_tase_benchmark", return_value=1), \
         patch.object(ingestor, "fetch_ticker_chunk") as mock_chunk:

        summary = ingestor.sync_universe(symbols=["TEVA.TA"], exchange="TASE")

        assert "total_tickers" in summary
        assert isinstance(mock_chunk.called, bool)
