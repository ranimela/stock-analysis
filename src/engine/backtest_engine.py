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

    Raises:
        ValueError: If there are insufficient trading dates or date is out of range.
    """
    univ = universe.strip().upper() if universe else "US"
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
        exchange_val = meta[0][2] if meta and meta[0][2] else ("TASE" if is_tase_ticker(ticker) else "NASDAQ")

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
        if univ == "US":
            run_id = f"pit_T-{cutoff_days_ago}_{cutoff_date.replace('-', '')}"
            scan_type = f"T-{cutoff_days_ago}"
        else:
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

