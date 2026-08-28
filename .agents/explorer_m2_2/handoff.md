# Handoff Report: Milestone 2 Backtest Engine & CLI Investigation

## 1. Observation
1. **Backtest Engine Implementation**:
   - In `src/engine/backtest_engine.py` (lines 47–49), trade dates are fetched via:
     ```python
     dates_query = "SELECT DISTINCT trade_date FROM daily_bars ORDER BY trade_date DESC;"
     rows = db_manager.execute_read(dates_query)
     ```
   - In `src/engine/backtest_engine.py` (lines 126–134), the benchmark query is hardcoded to `'SPY'`:
     ```python
     spy_rows = db_manager.execute_read(
         """
         SELECT trade_date, close
         FROM daily_bars
         WHERE ticker = 'SPY' AND trade_date >= CAST(? AS DATE) AND trade_date <= CAST(? AS DATE)
         ORDER BY trade_date ASC;
         """,
         [cutoff_date, eval_date],
     )
     ```
   - In `src/engine/backtest_engine.py` (lines 185, 196, 207, 242), alpha and benchmark metrics are strictly computed against SPY:
     ```python
     alpha = ret - spy_return
     "spy_return_pct": spy_return * 100.0,
     "spy_return": spy_return,
     "basket_alpha": basket_alpha,
     ```
   - In `src/engine/backtest_engine.py` (lines 219–220), `run_id` and `scan_type` are generated without market universe differentiation:
     ```python
     run_id = f"pit_T-{cutoff_days_ago}_{cutoff_date.replace('-', '')}"
     scan_type = f"T-{cutoff_days_ago}"
     ```
2. **CLI Scan Command**:
   - In `src/cli.py` (lines 180–187), `@main.command() def scan(db_path: str)` currently lacks an `--exchange` / `-e` option, while `seed` (lines 51–57) and `update` (lines 109–115) already support `--exchange` with `click.Choice(["US", "TASE", "ALL"])`.
3. **Current Test Status**:
   - Running `python -m pytest` executes 84 items with 100% pass rate in 34.76s (`src/db/`, `src/engine/`, `src/ingestion/`, `src/test_cli_ui.py`, `tests/`).

---

## 2. Logic Chain
1. **Observation 1 (Calendar Asymmetry)**: In a database populated with both US and TASE data, `daily_bars` contains trading dates for Sunday (TASE) through Friday (US).
   - *Inference*: Selecting `DISTINCT trade_date` globally creates a 6-day trading week. Stepping back `cutoff_days_ago=5` across a 6-day mixed calendar steps back only 3.5 trading days on an individual market, corrupting the true 1-week ($T_{-5}$) and 1-month ($T_{-22}$) lookback windows.
   - *Resolution*: Query distinct trade dates filtered by the target universe's benchmark ticker (`^TA125.TA` for TASE, `SPY` for US). The benchmark ticker's historical series naturally embodies the exchange's trading days (Sun–Thu for TASE, Mon–Fri for US) and respective market holidays.
2. **Observation 1 (Benchmark & Alpha Routing)**: Forward returns and alpha for TASE equities must be evaluated against the TA-125 benchmark index (`^TA125.TA`).
   - *Inference*: By parameterizing `universe: str = "US"` and dynamically resolving `benchmark_ticker = "^TA125.TA" if universe == "TASE" else "SPY"`, the benchmark forward query becomes parameterized `WHERE ticker = ?`.
   - *Resolution*: Compute `benchmark_return`, calculate `alpha = ret - benchmark_return`, and provide both normalized keys (`benchmark_return`, `benchmark_ticker`, `ta125_return`) and backwards-compatible aliases (`spy_return`, `spy_return_pct`).
3. **Observation 1 (Top 5 TASE Portfolio Allocation)**: The user specification requires Top 5 recommendations for TASE.
   - *Inference*: For TASE, `top_tickers = screener_df["ticker"].head(5).tolist()`. In a standard $10,000 model, each of the 5 positions receives an equal $2,000 allocation (20.0% weight).
   - *Resolution*: Add `effective_top_n = top_n if top_n is not None else (5 if univ == "TASE" else 10)`, and compute position allocations `allocation_pct = 100.0 / num_positions` and `allocation_usd = 10000.0 / num_positions`.
4. **Observation 2 (CLI Multi-Exchange Symmetry)**: The CLI `scan` command must allow scanning US only, TASE only, or ALL.
   - *Resolution*: Add `@click.option("--exchange", "-e", type=click.Choice(["US", "TASE", "ALL"]), default="ALL")` to `scan` and invoke screener/backtest for the selected market universes with dedicated output tables.

---

## 3. Caveats
1. **Mock Data in Tests**: Synthetic test databases in `test_engine.py` might insert test equities without creating `SPY` or `^TA125.TA` bars. A graceful fallback to `SELECT DISTINCT trade_date FROM daily_bars` must be maintained if the benchmark ticker returns 0 trade dates.
2. **Read-Only Connections**: When `db_manager.read_only == True` (e.g. in Streamlit UI), persistence to `point_in_time_runs` must be bypassed safely without raising permission exceptions.
3. **Price Currencies**: US equity prices and ADV are in USD; TASE equity prices and ADV in Yahoo Finance `.TA` feeds are typically in Agorot (or ILS). Ratios, percentage returns, and alpha calculations are dimensionless percentages and remain invariant to currency units.

---

## 4. Conclusion & Proposed Code Modifications

### 4.1 Proposed `src/engine/backtest_engine.py`
```python
"""Point-in-Time Backtest Engine Module.

Executes point-in-time simulation at historical cutoff dates (e.g. T-5, T-22 days ago)
and tracks forward stock returns, benchmark returns (SPY for US, ^TA125.TA for TASE),
basket alpha, win rate, and maximum drawdown without lookahead bias.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging

import pandas as pd

from src.db.db_manager import DatabaseManager
from src.engine.screener_queries import run_screener
from src.ingestion.tase_directory import TASE_BENCHMARK, is_tase_ticker

logger = logging.getLogger(__name__)


def run_point_in_time_backtest(
    db_manager: DatabaseManager,
    cutoff_days_ago: int = 5,
    custom_cutoff_date: str | None = None,
    max_tightness: float = 3.5,
    pct_off_low: float = 30.0,
    pct_within_high: float = 25.0,
    universe: str = "US",
    benchmark_ticker: str | None = None,
    top_n: int | None = None,
) -> dict[str, float | str | int | pd.DataFrame]:
    """Executes a point-in-time backtest for top recommendations at T - cutoff_days_ago or a custom date.

    Args:
        db_manager: Initialized DatabaseManager instance.
        cutoff_days_ago: Number of trading days prior to latest available date. Defaults to 5.
        custom_cutoff_date: Optional specific historical YYYY-MM-DD date.
        max_tightness: Tightness ratio threshold ceiling. Defaults to 3.5.
        pct_off_low: Minimum % gain off 52-week low. Defaults to 30.0.
        pct_within_high: Maximum allowable % distance below 52-week high. Defaults to 25.0.
        universe: Target exchange universe ('US' or 'TASE'). Defaults to 'US'.
        benchmark_ticker: Optional benchmark ticker override (defaults to SPY for US, ^TA125.TA for TASE).
        top_n: Optional portfolio size cutoff (defaults to 5 for TASE, 10 for US).

    Returns:
        dict[str, float | str | int | pd.DataFrame]: Dictionary containing summary statistics
        and a detailed DataFrame of position forward performance.
    """
    univ = universe.strip().upper()
    if benchmark_ticker is None:
        bench_ticker = TASE_BENCHMARK if univ == "TASE" else "SPY"
    else:
        bench_ticker = benchmark_ticker.strip().upper()

    # Query distinct trade dates for the specific benchmark to align with exchange trading calendar
    dates_query = """
        SELECT DISTINCT trade_date
        FROM daily_bars
        WHERE ticker = ?
        ORDER BY trade_date DESC;
    """
    rows = db_manager.execute_read(dates_query, [bench_ticker])

    # Fallback to general daily_bars if benchmark has no bars in DB
    if not rows:
        fallback_query = "SELECT DISTINCT trade_date FROM daily_bars ORDER BY trade_date DESC;"
        rows = db_manager.execute_read(fallback_query)

    trade_dates = [str(r[0]) for r in rows]

    if not trade_dates:
        raise ValueError(f"Database is empty or contains no historical daily bars for {univ} (benchmark: {bench_ticker}).")

    eval_date = trade_dates[0]  # T0 (Latest available date for target exchange)

    if custom_cutoff_date is not None:
        custom_str = str(custom_cutoff_date)
        valid_dates = [d for d in trade_dates if d <= custom_str]
        if not valid_dates:
            min_avail = trade_dates[-1]
            max_avail = trade_dates[0]
            raise ValueError(
                f"Selected date '{custom_str}' is prior to available {univ} market dataset. "
                f"Available database range: {min_avail} to {max_avail}."
            )
        cutoff_date = valid_dates[0]
        if custom_str != cutoff_date:
            logger.info("Custom date %s snapped to nearest prior %s trading date %s.", custom_str, univ, cutoff_date)
    else:
        if cutoff_days_ago < 1:
            raise ValueError("cutoff_days_ago must be a positive integer >= 1.")

        if len(trade_dates) <= cutoff_days_ago:
            raise ValueError(
                f"Insufficient historical dates ({len(trade_dates)}) for cutoff_days_ago={cutoff_days_ago} in {univ} universe."
            )
        cutoff_date = trade_dates[cutoff_days_ago]

    logger.info(
        "Running point-in-time backtest (%s): cutoff_date=%s, eval_date=%s, benchmark=%s.",
        univ,
        cutoff_date,
        eval_date,
        bench_ticker,
    )

    # Execute screener at cutoff date with strategy parameters
    screener_df = run_screener(
        db_manager,
        cutoff_date=cutoff_date,
        max_tightness=max_tightness,
        pct_off_low=pct_off_low,
        pct_within_high=pct_within_high,
        universe=univ,
        benchmark_ticker=bench_ticker,
    )

    empty_positions = pd.DataFrame(
        columns=[
            "ticker",
            "name",
            "exchange",
            "market_cap",
            "entry_price",
            "exit_price",
            "return_pct",
            "benchmark_ticker",
            "benchmark_return_pct",
            "spy_return_pct",
            "ta125_return_pct",
            "alpha_pct",
            "max_drawdown_pct",
            "allocation_pct",
            "allocation_usd",
            "is_win",
        ]
    )

    if screener_df.empty:
        logger.warning("No candidates returned by screener for cutoff date %s (%s).", cutoff_date, univ)
        return {
            "universe": univ,
            "benchmark_ticker": bench_ticker,
            "cutoff_date": cutoff_date,
            "evaluation_date": eval_date,
            "cutoff_days_ago": cutoff_days_ago,
            "mean_basket_return": 0.0,
            "benchmark_return": 0.0,
            "spy_return": 0.0,
            "ta125_return": 0.0,
            "basket_alpha": 0.0,
            "win_rate": 0.0,
            "avg_max_drawdown": 0.0,
            "positions_df": empty_positions,
        }

    effective_top_n = top_n if top_n is not None else (5 if univ == "TASE" else 10)
    top_df = screener_df.head(effective_top_n)
    top_tickers = top_df["ticker"].tolist()

    # Query forward prices for benchmark from cutoff_date to eval_date
    bench_rows = db_manager.execute_read(
        """
        SELECT trade_date, close
        FROM daily_bars
        WHERE ticker = ? AND trade_date >= CAST(? AS DATE) AND trade_date <= CAST(? AS DATE)
        ORDER BY trade_date ASC;
        """,
        [bench_ticker, cutoff_date, eval_date],
    )

    if bench_rows and len(bench_rows) >= 1:
        bench_entry = float(bench_rows[0][1])
        bench_exit = float(bench_rows[-1][1])
        bench_return = (bench_exit - bench_entry) / bench_entry if bench_entry > 0 else 0.0
    else:
        bench_return = 0.0

    position_results: list[dict[str, float | str | bool | None]] = []
    num_positions = len(top_tickers)
    alloc_pct = (100.0 / num_positions) if num_positions > 0 else 0.0
    alloc_usd = (10000.0 / num_positions) if num_positions > 0 else 0.0

    for ticker in top_tickers:
        meta = db_manager.execute_read(
            "SELECT COALESCE(name, ticker), market_cap, exchange FROM symbol_metadata WHERE ticker = ?;",
            [ticker],
        )
        comp_name = meta[0][0] if meta else ticker
        m_cap = meta[0][1] if meta else None
        exchange_val = meta[0][2] if meta and meta[0][2] else ("TASE" if is_tase_ticker(ticker) else "US")

        bars = db_manager.execute_read(
            """
            SELECT trade_date, close, low
            FROM daily_bars
            WHERE ticker = ? AND trade_date >= CAST(? AS DATE) AND trade_date <= CAST(? AS DATE)
            ORDER BY trade_date ASC;
            """,
            [ticker, cutoff_date, eval_date],
        )

        if not bars:
            continue

        entry_price = float(bars[0][1])
        exit_price = float(bars[-1][1])

        ret = (exit_price - entry_price) / entry_price if entry_price > 0 else 0.0

        # Calculate standard rolling peak-to-trough Max Drawdown (MDD) during period
        running_peak = float(bars[0][1])
        max_drawdown = 0.0
        for b in bars:
            bar_close = float(b[1])
            bar_low = float(b[2])
            if bar_close > running_peak:
                running_peak = bar_close
            if running_peak > 0:
                dd = (bar_low - running_peak) / running_peak
                if dd < max_drawdown:
                    max_drawdown = dd
        mdd = max_drawdown

        alpha = ret - bench_return
        is_win = ret > 0.0

        position_results.append(
            {
                "ticker": ticker,
                "name": comp_name,
                "exchange": exchange_val,
                "market_cap": m_cap,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "return_pct": ret * 100.0,
                "benchmark_ticker": bench_ticker,
                "benchmark_return_pct": bench_return * 100.0,
                "spy_return_pct": bench_return * 100.0,
                "ta125_return_pct": bench_return * 100.0 if univ == "TASE" else None,
                "alpha_pct": alpha * 100.0,
                "max_drawdown_pct": mdd * 100.0,
                "allocation_pct": alloc_pct,
                "allocation_usd": alloc_usd,
                "is_win": is_win,
            }
        )

    positions_df = pd.DataFrame(position_results)

    if not positions_df.empty:
        mean_basket_return = float(positions_df["return_pct"].mean() / 100.0)
        basket_alpha = float(mean_basket_return - bench_return)
        win_rate = float((positions_df["is_win"].sum() / len(positions_df)) * 100.0)
        avg_mdd = float(positions_df["max_drawdown_pct"].mean())
    else:
        mean_basket_return = 0.0
        basket_alpha = 0.0
        win_rate = 0.0
        avg_mdd = 0.0

    # Persist run to point_in_time_runs if database is writable
    if not getattr(db_manager, "read_only", False):
        now_iso = datetime.now(timezone.utc).isoformat()
        run_id = f"pit_T-{cutoff_days_ago}_{univ}_{cutoff_date.replace('-', '')}"
        scan_type = f"T-{cutoff_days_ago}_{univ}"
        tickers_str = ",".join(top_tickers)

        try:
            db_manager.execute_write(
                """
                INSERT INTO point_in_time_runs (run_id, run_date, cutoff_date, scan_type, top_tickers)
                VALUES (?, ?, CAST(? AS DATE), ?, ?)
                ON CONFLICT (run_id) DO UPDATE SET
                    run_date = EXCLUDED.run_date,
                    top_tickers = EXCLUDED.top_tickers;
                """,
                [run_id, now_iso, cutoff_date, scan_type, tickers_str],
            )
        except Exception as e:
            logger.warning("Skipped persisting point-in-time run to DB: %s", e)

    return {
        "universe": univ,
        "benchmark_ticker": bench_ticker,
        "cutoff_date": cutoff_date,
        "evaluation_date": eval_date,
        "cutoff_days_ago": cutoff_days_ago,
        "mean_basket_return": mean_basket_return,
        "benchmark_return": bench_return,
        "spy_return": bench_return,
        "ta125_return": bench_return if univ == "TASE" else 0.0,
        "basket_alpha": basket_alpha,
        "win_rate": win_rate,
        "avg_max_drawdown": avg_mdd,
        "positions_df": positions_df,
    }
```

### 4.2 Proposed CLI `scan` Command Modification in `src/cli.py`
```python
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
```

---

## 5. Verification Method
1. **Unit Test Verification**:
   - Run `python -m pytest src/engine/test_engine.py`
   - Run `python -m pytest src/test_cli_ui.py`
   - Run `python -m pytest`
2. **Specific Checks for Implementation Agent (Builder)**:
   - Verify `run_point_in_time_backtest(db_mgr, cutoff_days_ago=5, universe="TASE")` queries trade dates from `^TA125.TA`.
   - Verify `benchmark_return` equals forward price change of `^TA125.TA`.
   - Verify `basket_alpha` equals `mean_basket_return - ta125_return`.
   - Verify `positions_df` returns 5 rows for TASE with `allocation_pct = 20.0` and `allocation_usd = 2000.0`.
   - Verify `python -m src.cli scan --exchange US`, `python -m src.cli scan --exchange TASE`, and `python -m src.cli scan --exchange ALL` execute cleanly.
3. **Invalidation Conditions**:
   - Failure of any existing test in `src/engine/test_engine.py` or `src/test_cli_ui.py`.
   - Cross-market date mixing causing mismatched evaluation dates.
