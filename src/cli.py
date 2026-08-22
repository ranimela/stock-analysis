"""Command Line Interface (CLI) Orchestration Module.

Provides subcommands for database seeding, daily EOD delta update, and screening scans:
- `python -m src.cli seed`: Initializes database schema, downloads master ticker list, and ingests historical bars.
- `python -m src.cli update`: Synchronizes newest daily EOD bars for all existing equities (delta sync).
- `python -m src.cli scan`: Runs T0 live screener, T-5 (1-Week), and T-22 (1-Month) PIT backtests and prints summary report.
"""

from __future__ import annotations

import logging
import sys

import click

from src.db.db_manager import DatabaseManager
from src.engine.backtest_engine import run_point_in_time_backtest
from src.engine.screener_queries import run_screener
from src.ingestion.data_ingestor import DataIngestor
from src.ingestion.symbol_directory import fetch_symbol_directory, sync_symbol_metadata

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@click.group()
def main() -> None:
    """Quantitative Stock Screener & PIT Backtest Orchestration CLI."""
    pass


@main.command()
@click.option(
    "--db-path",
    default="market_data.duckdb",
    help="Path to DuckDB database file.",
    show_default=True,
)
@click.option(
    "--chunk-size",
    default=100,
    help="Batch chunk size for ticker data fetching.",
    show_default=True,
)
def seed(db_path: str, chunk_size: int) -> None:
    """Initial database seed (downloads master ticker list and runs chunked ingestion)."""
    click.echo(f"Initializing database seed at '{db_path}'...")
    db_manager = DatabaseManager(db_path=db_path, read_only=False)

    click.echo("Fetching master symbol directory from NASDAQ/Other exchange lists...")
    symbols = fetch_symbol_directory()
    click.echo(f"Discovered {len(symbols)} common stock symbols.")

    sync_symbol_metadata(db_manager, symbols)
    click.echo("Symbol metadata synchronized to database.")

    ingestor = DataIngestor(db_manager=db_manager, chunk_size=chunk_size)
    click.echo("Starting historical bar ingestion...")
    summary = ingestor.sync_universe(symbols)

    click.echo("\n--- Seed Complete ---")
    click.echo(f"Total Tickers: {summary['total_tickers']}")
    click.echo(f"Synced Tickers: {summary['synced_tickers']}")
    click.echo(f"Total Bars Inserted: {summary['total_bars_inserted']}")
    click.echo(f"Status: {summary['status']}")


@main.command()
@click.option(
    "--db-path",
    default="market_data.duckdb",
    help="Path to DuckDB database file.",
    show_default=True,
)
def update(db_path: str) -> None:
    """Daily delta sync (fetches newest EOD bar)."""
    click.echo(f"Starting daily delta update for database '{db_path}'...")
    db_manager = DatabaseManager(db_path=db_path, read_only=False)

    ingestor = DataIngestor(db_manager=db_manager)
    summary = ingestor.sync_universe()

    click.echo("\n--- Update Complete ---")
    click.echo(f"Total Tickers: {summary['total_tickers']}")
    click.echo(f"Synced Tickers: {summary['synced_tickers']}")
    click.echo(f"Total Bars Inserted: {summary['total_bars_inserted']}")
    click.echo(f"Status: {summary['status']}")


@main.command(name="export-delta")
@click.option(
    "--db-path",
    default="market_data.duckdb",
    help="Path to DuckDB database file.",
    show_default=True,
)
@click.option(
    "--output-dir",
    default="data/daily_deltas",
    help="Output directory for parquet file.",
    show_default=True,
)
def export_delta(db_path: str, output_dir: str) -> None:
    """Exports latest EOD trade date bars to a single Parquet file and prunes files older than 7 days."""
    click.echo(f"Exporting latest EOD delta from '{db_path}' to '{output_dir}'...")
    db_manager = DatabaseManager(db_path=db_path, read_only=False)
    ingestor = DataIngestor(db_manager=db_manager)
    res_path = ingestor.export_daily_delta_parquet(output_dir=output_dir, retention_days=7)
    if res_path:
        click.echo(f"Export successful: {res_path}")
    else:
        click.echo("Export skipped or failed.")


@main.command(name="sync-delta")
@click.option(
    "--db-path",
    default="market_data.duckdb",
    help="Path to DuckDB database file.",
    show_default=True,
)
@click.option(
    "--deltas-dir",
    default="data/daily_deltas",
    help="Directory containing parquet delta files.",
    show_default=True,
)
def sync_delta(db_path: str, deltas_dir: str) -> None:
    """Syncs unmerged parquet delta files into local DuckDB database."""
    click.echo(f"Syncing local DuckDB '{db_path}' from parquet deltas in '{deltas_dir}'...")
    db_manager = DatabaseManager(db_path=db_path, read_only=False)
    ingestor = DataIngestor(db_manager=db_manager)
    synced_count = ingestor.sync_local_db_from_parquet(deltas_dir=deltas_dir)
    click.echo(f"Merged {synced_count} daily delta file(s) into local DuckDB.")


@main.command()
@click.option(
    "--db-path",
    default="market_data.duckdb",
    help="Path to DuckDB database file.",
    show_default=True,
)
def scan(db_path: str) -> None:
    """Runs T0, T-5, and T-22 scans and outputs summary report."""
    click.echo(f"Executing scans against database '{db_path}'...")
    db_manager = DatabaseManager(db_path=db_path, read_only=False)

    rows = db_manager.execute_read("SELECT MAX(trade_date) FROM daily_bars;")
    if not rows or not rows[0][0]:
        click.echo("Error: Database is empty. Please run 'python -m src.cli seed' first.", err=True)
        sys.exit(1)

    latest_date = str(rows[0][0])
    click.echo(f"Latest Market Trade Date (T0): {latest_date}\n")

    # 1. View A: Live T0 Screener Recommendations
    click.echo("=========================================================================")
    click.echo(f" 1. LIVE TOP-10 RECOMMENDATIONS (T0 Cutoff: {latest_date})")
    click.echo("=========================================================================")
    t0_df = run_screener(db_manager, cutoff_date=latest_date)

    if t0_df.empty:
        click.echo("No candidates passed screener filters for T0.")
    else:
        t0_df["pct_off_52w"] = ((t0_df["close"] / t0_df["high_52w"]) - 1.0) * 100.0
        click.echo(
            f"{'Rank':<5} {'Ticker':<8} {'Price':<10} {'ADV20($M)':<12} {'RS Score':<10} {'Tightness':<10} {'%Off 52W High':<14}"
        )
        click.echo("-" * 75)
        for _, row in t0_df.iterrows():
            click.echo(
                f"{int(row['rank']):<5} {row['ticker']:<8} ${row['close']:<9.2f} "
                f"${row['adv_20']/1e6:<11.2f} {row['rs_score']:<10.4f} "
                f"{row['tightness_ratio']:<10.2f} {row['pct_off_52w']:<+13.2f}%"
            )

    # 2. View B: T-5 (1-Week) PIT Backtest
    click.echo("\n=========================================================================")
    click.echo(" 2. 1-WEEK POINT-IN-TIME BACKTEST (T-5)")
    click.echo("=========================================================================")
    try:
        res_t5 = run_point_in_time_backtest(db_manager, cutoff_days_ago=5)
        click.echo(f"Cutoff Date: {res_t5['cutoff_date']}  -->  Evaluation Date: {res_t5['evaluation_date']}")
        click.echo(f"Basket Mean Return: {res_t5['mean_basket_return']*100:+.2f}%")
        click.echo(f"SPY Benchmark Return: {res_t5['spy_return']*100:+.2f}%")
        click.echo(f"Basket Alpha vs SPY: {res_t5['basket_alpha']*100:+.2f}%")
        click.echo(f"Win Rate: {res_t5['win_rate']:.1f}%")
        click.echo(f"Average Max Drawdown: {res_t5['avg_max_drawdown']:.2f}%")
    except Exception as e:
        click.echo(f"T-5 Backtest error: {e}")

    # 3. View C: T-22 (1-Month) PIT Backtest
    click.echo("\n=========================================================================")
    click.echo(" 3. 1-MONTH POINT-IN-TIME BACKTEST (T-22)")
    click.echo("=========================================================================")
    try:
        res_t22 = run_point_in_time_backtest(db_manager, cutoff_days_ago=22)
        click.echo(f"Cutoff Date: {res_t22['cutoff_date']}  -->  Evaluation Date: {res_t22['evaluation_date']}")
        click.echo(f"Basket Mean Return: {res_t22['mean_basket_return']*100:+.2f}%")
        click.echo(f"SPY Benchmark Return: {res_t22['spy_return']*100:+.2f}%")
        click.echo(f"Basket Alpha vs SPY: {res_t22['basket_alpha']*100:+.2f}%")
        click.echo(f"Win Rate: {res_t22['win_rate']:.1f}%")
        click.echo(f"Average Max Drawdown: {res_t22['avg_max_drawdown']:.2f}%")
    except Exception as e:
        click.echo(f"T-22 Backtest error: {e}")


if __name__ == "__main__":
    main()
