"""Command Line Interface (CLI) Orchestration Module.

Provides subcommands for database seeding, daily EOD delta update, and screening scans:
- `python -m src.cli seed`: Initializes database schema, downloads master ticker list, and ingests historical bars.
- `python -m src.cli update`: Synchronizes newest daily EOD bars for all existing equities (delta sync).
- `python -m src.cli scan`: Runs T0 live screener, T-5 (1-Week), and T-22 (1-Month) PIT backtests and prints summary report.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import click

from src.db.db_manager import DatabaseManager
from src.engine.backtest_engine import run_point_in_time_backtest
from src.engine.screener_queries import run_screener
from src.ingestion.data_ingestor import DataIngestor
from src.ingestion.symbol_directory import fetch_symbol_directory, sync_symbol_metadata
from src.ingestion.tase_directory import get_tase_symbol_directory

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
@click.option(
    "--exchange",
    "-e",
    type=click.Choice(["US", "TASE", "ALL"], case_sensitive=False),
    default="ALL",
    help="Target exchange universe to seed (US, TASE, or ALL).",
    show_default=True,
)
def seed(db_path: str, chunk_size: int, exchange: str) -> None:
    """Initial database seed (downloads master ticker list and runs chunked ingestion)."""
    exchange_upper = exchange.upper()
    click.echo(f"Initializing database seed at '{db_path}' for exchange universe: {exchange_upper}...")
    db_manager = DatabaseManager(db_path=db_path, read_only=False)

    symbols: list[dict[str, Any]] = []
    if exchange_upper in ("US", "ALL"):
        click.echo("Fetching master symbol directory from NASDAQ/Other exchange lists...")
        try:
            us_symbols = fetch_symbol_directory()
            click.echo(f"Discovered {len(us_symbols)} US common stock symbols.")
            symbols.extend(us_symbols)
        except Exception as err:
            click.echo(f"Warning: Could not fetch US symbol directory: {err}", err=True)

    if exchange_upper in ("TASE", "ALL"):
        click.echo("Fetching TASE TA-125 symbol directory...")
        try:
            tase_symbols = get_tase_symbol_directory()
            click.echo(f"Discovered {len(tase_symbols)} TASE constituent symbols.")
            symbols.extend(tase_symbols)
        except Exception as err:
            click.echo(f"Warning: Could not fetch TASE symbol directory: {err}", err=True)

    if not symbols:
        click.echo("Error: No symbols discovered for requested exchange universe.", err=True)
        sys.exit(1)

    sync_symbol_metadata(db_manager, symbols)
    click.echo("Symbol metadata synchronized to database.")

    ingestor = DataIngestor(db_manager=db_manager, chunk_size=chunk_size)
    click.echo("Starting historical bar ingestion...")
    summary = ingestor.sync_universe(symbols, exchange=exchange_upper)

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
@click.option(
    "--exchange",
    "-e",
    type=click.Choice(["US", "TASE", "ALL"], case_sensitive=False),
    default="ALL",
    help="Target exchange universe to update (US, TASE, or ALL).",
    show_default=True,
)
def update(db_path: str, exchange: str) -> None:
    """Daily delta sync (fetches newest EOD bar)."""
    exchange_upper = exchange.upper()
    click.echo(f"Starting daily delta update for database '{db_path}' (exchange: {exchange_upper})...")
    db_manager = DatabaseManager(db_path=db_path, read_only=False)

    ingestor = DataIngestor(db_manager=db_manager)
    summary = ingestor.sync_universe(exchange=exchange_upper)

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
@click.option(
    "--exchange",
    "-e",
    type=click.Choice(["US", "TASE", "ALL"], case_sensitive=False),
    default="ALL",
    help="Target exchange universe to scan (US, TASE, or ALL).",
    show_default=True,
)
def scan(db_path: str, exchange: str = "ALL") -> None:
    """Runs T0, T-5, and T-22 scans for US and/or TASE and outputs summary report."""
    exchange_upper = exchange.upper()
    click.echo(f"Executing scans against database '{db_path}' (exchange universe: {exchange_upper})...")
    db_manager = DatabaseManager(db_path=db_path, read_only=False)

    rows = db_manager.execute_read("SELECT MAX(trade_date) FROM daily_bars;")
    if not rows or not rows[0][0]:
        click.echo("Error: Database is empty. Please run 'python -m src.cli seed' first.", err=True)
        sys.exit(1)

    latest_date = str(rows[0][0])
    click.echo(f"Latest Market Trade Date (T0): {latest_date}\n")

    if exchange_upper in ("US", "ALL"):
        _run_market_scans(db_manager, latest_date, universe="US")

    if exchange_upper in ("TASE", "ALL"):
        _run_market_scans(db_manager, latest_date, universe="TASE")


def _run_market_scans(db_manager: DatabaseManager, latest_date: str, universe: str = "US") -> None:
    """Helper to run and display screener and backtest scans for a specific market universe."""
    is_tase = universe == "TASE"
    top_label = "TOP-5" if is_tase else "TOP-10"
    bench_label = "^TA125.TA" if is_tase else "SPY"
    market_header = "TASE (TEL AVIV)" if is_tase else "US EQUITIES"

    click.echo("=========================================================================")
    click.echo(f" [{market_header}] 1. LIVE {top_label} RECOMMENDATIONS (T0 Cutoff: {latest_date})")
    click.echo("=========================================================================")
    t0_df = run_screener(db_manager, cutoff_date=latest_date, universe=universe)

    if t0_df.empty:
        click.echo(f"No {universe} candidates passed screener filters for T0.")
    else:
        disp_df = t0_df.head(5 if is_tase else 10).copy()
        disp_df["pct_off_52w"] = ((disp_df["close"] / disp_df["high_52w"]) - 1.0) * 100.0
        click.echo(
            f"{'Rank':<5} {'Ticker':<10} {'Price':<10} {'ADV20':<14} {'RS Score':<10} {'Tightness':<10} {'%Off 52W High':<14}"
        )
        click.echo("-" * 75)
        for _, row in disp_df.iterrows():
            click.echo(
                f"{int(row['rank']):<5} {row['ticker']:<10} {row['close']:<10.2f} "
                f"{row['adv_20']/1e6:<13.2f}M {row['rs_score']:<10.4f} "
                f"{row['tightness_ratio']:<10.2f} {row['pct_off_52w']:<+13.2f}%"
            )

    click.echo("\n=========================================================================")
    click.echo(f" [{market_header}] 2. 1-WEEK POINT-IN-TIME BACKTEST (T-5, {bench_label})")
    click.echo("=========================================================================")
    try:
        res_t5 = run_point_in_time_backtest(db_manager, cutoff_days_ago=5, universe=universe)
        click.echo(f"Cutoff Date: {res_t5['cutoff_date']}  -->  Evaluation Date: {res_t5['evaluation_date']}")
        click.echo(f"Basket Mean Return: {res_t5['mean_basket_return']*100:+.2f}%")
        click.echo(f"{bench_label} Benchmark Return: {res_t5['benchmark_return']*100:+.2f}%")
        click.echo(f"Basket Alpha vs {bench_label}: {res_t5['basket_alpha']*100:+.2f}%")
        click.echo(f"Win Rate: {res_t5['win_rate']:.1f}%")
        click.echo(f"Average Max Drawdown: {res_t5['avg_max_drawdown']:.2f}%")
    except Exception as e:
        click.echo(f"T-5 Backtest error ({universe}): {e}")

    click.echo("\n=========================================================================")
    click.echo(f" [{market_header}] 3. 1-MONTH POINT-IN-TIME BACKTEST (T-22, {bench_label})")
    click.echo("=========================================================================")
    try:
        res_t22 = run_point_in_time_backtest(db_manager, cutoff_days_ago=22, universe=universe)
        click.echo(f"Cutoff Date: {res_t22['cutoff_date']}  -->  Evaluation Date: {res_t22['evaluation_date']}")
        click.echo(f"Basket Mean Return: {res_t22['mean_basket_return']*100:+.2f}%")
        click.echo(f"{bench_label} Benchmark Return: {res_t22['benchmark_return']*100:+.2f}%")
        click.echo(f"Basket Alpha vs {bench_label}: {res_t22['basket_alpha']*100:+.2f}%")
        click.echo(f"Win Rate: {res_t22['win_rate']:.1f}%")
        click.echo(f"Average Max Drawdown: {res_t22['avg_max_drawdown']:.2f}%")
    except Exception as e:
        click.echo(f"T-22 Backtest error ({universe}): {e}")


if __name__ == "__main__":
    main()

