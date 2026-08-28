"""Additional adversarial stress-tests for CLI arguments and edge cases."""

from __future__ import annotations

import datetime
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner
import pandas as pd
import pytest

from src.cli import main
from src.db.db_manager import DatabaseManager
from src.ingestion.data_ingestor import DataIngestor


class TestCLIEdgeCases:
    """Stress testing CLI arguments, chunk sizing, and error handling."""

    def test_cli_seed_chunk_size_option(self, tmp_path: Path):
        """Test CLI seed with custom --chunk-size parameter."""
        db_file = tmp_path / "chunk_test.duckdb"
        runner = CliRunner()

        with patch("src.cli.get_tase_symbol_directory") as mock_tase, \
             patch("src.ingestion.data_ingestor.DataIngestor.download_tase_benchmark", return_value=1), \
             patch("src.ingestion.data_ingestor.DataIngestor.fetch_ticker_chunk", return_value=pd.DataFrame()):

            mock_tase.return_value = [
                {"ticker": f"SYM{i}.TA", "name": f"Sym {i}", "exchange": "TASE", "asset_class": "Common Stock", "is_active": True}
                for i in range(25)
            ]

            res = runner.invoke(main, ["seed", "--db-path", str(db_file), "--exchange", "TASE", "--chunk-size", "5"])
            assert res.exit_code == 0
            assert "Total Tickers: 25" in res.output

    def test_cli_update_nonexistent_db_handling(self, tmp_path: Path):
        """Test CLI update on a fresh/nonexistent database file initializes schema gracefully."""
        db_file = tmp_path / "fresh_db.duckdb"
        runner = CliRunner()

        with patch("src.ingestion.data_ingestor.DataIngestor.download_tase_benchmark", return_value=1), \
             patch("src.ingestion.data_ingestor.DataIngestor.fetch_ticker_chunk", return_value=pd.DataFrame()):

            res = runner.invoke(main, ["update", "--db-path", str(db_file), "--exchange", "TASE"])
            assert res.exit_code == 0
            assert "Update Complete" in res.output
            assert db_file.exists()

    def test_sync_universe_with_duplicate_symbols_in_input(self, tmp_path: Path):
        """Test sync_universe deduplicates ticker lists cleanly."""
        db_file = tmp_path / "dedup.duckdb"
        db_mgr = DatabaseManager(db_path=db_file, read_only=False)
        ingestor = DataIngestor(db_manager=db_mgr)

        duplicates = ["TEVA.TA", "TEVA.TA", "teva.ta", "LUMI.TA", "lumi.ta", "LUMI.TA"]

        with patch.object(ingestor, "download_tase_benchmark", return_value=1), \
             patch.object(ingestor, "fetch_ticker_chunk", return_value=pd.DataFrame()) as mock_chunk:

            summary = ingestor.sync_universe(symbols=duplicates, exchange="TASE")
            # Should deduplicate to 2 unique tickers: TEVA.TA, LUMI.TA
            assert summary["total_tickers"] == 2
            assert summary["synced_tickers"] == 2

    def test_sync_universe_removes_benchmark_from_ticker_chunk_list(self, tmp_path: Path):
        """Test sync_universe strips benchmark tickers (^TA125.TA, SPY) from the general ticker list to prevent duplicate fetch."""
        db_file = tmp_path / "bench_strip.duckdb"
        db_mgr = DatabaseManager(db_path=db_file, read_only=False)
        ingestor = DataIngestor(db_manager=db_mgr)

        symbols_with_bench = ["TEVA.TA", "^TA125.TA", "^TA125", "SPY", "LUMI.TA"]

        with patch.object(ingestor, "download_tase_benchmark", return_value=1), \
             patch.object(ingestor, "download_spy", return_value=1), \
             patch.object(ingestor, "fetch_ticker_chunk", return_value=pd.DataFrame()) as mock_chunk:

            summary = ingestor.sync_universe(symbols=symbols_with_bench, exchange="ALL")
            assert summary["total_tickers"] == 2  # Only TEVA.TA and LUMI.TA
            # Verify fetched chunks do not include benchmark tickers
            for call in mock_chunk.call_args_list:
                chunk = call[0][0]
                assert "^TA125.TA" not in chunk
                assert "^TA125" not in chunk
                assert "SPY" not in chunk
