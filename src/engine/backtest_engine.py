"""Point-in-Time Backtest Engine Module.

Executes point-in-time simulation at historical cutoff dates (e.g. T-5, T-22 days ago)
and tracks forward stock returns, benchmark SPY returns, basket alpha, win rate,
and maximum drawdown without lookahead bias.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging

import pandas as pd

from src.db.db_manager import DatabaseManager
from src.engine.screener_queries import run_screener

logger = logging.getLogger(__name__)


def run_point_in_time_backtest(
    db_manager: DatabaseManager, cutoff_days_ago: int
) -> dict[str, float | str | int | pd.DataFrame]:
    """Executes a point-in-time backtest for top recommendations at T - cutoff_days_ago.

    Args:
        db_manager: Initialized DatabaseManager instance.
        cutoff_days_ago: Number of trading days prior to latest available date (e.g. 5 or 22).

    Returns:
        dict[str, float | str | int | pd.DataFrame]: Dictionary containing summary statistics
        and a detailed DataFrame of position forward performance.

    Raises:
        ValueError: If there are insufficient trading dates in the database for cutoff_days_ago.
    """
    if cutoff_days_ago < 1:
        raise ValueError("cutoff_days_ago must be a positive integer >= 1.")

    # Get distinct trade dates in descending order
    dates_query = "SELECT DISTINCT trade_date FROM daily_bars ORDER BY trade_date DESC;"
    rows = db_manager.execute_read(dates_query)
    trade_dates = [str(r[0]) for r in rows]

    if len(trade_dates) <= cutoff_days_ago:
        raise ValueError(
            f"Insufficient historical dates ({len(trade_dates)}) for cutoff_days_ago={cutoff_days_ago}."
        )

    eval_date = trade_dates[0]  # T0 (Today / latest available date)
    cutoff_date = trade_dates[cutoff_days_ago]  # T_cut

    logger.info(
        "Running point-in-time backtest for T-%d: cutoff_date=%s, eval_date=%s.",
        cutoff_days_ago,
        cutoff_date,
        eval_date,
    )

    # Execute screener at cutoff date
    screener_df = run_screener(db_manager, cutoff_date=cutoff_date)

    if screener_df.empty:
        logger.warning("No candidates returned by screener for cutoff date %s.", cutoff_date)
        empty_positions = pd.DataFrame(
            columns=[
                "ticker",
                "entry_price",
                "exit_price",
                "return_pct",
                "spy_return_pct",
                "alpha_pct",
                "max_drawdown_pct",
                "is_win",
            ]
        )
        return {
            "cutoff_date": cutoff_date,
            "evaluation_date": eval_date,
            "cutoff_days_ago": cutoff_days_ago,
            "mean_basket_return": 0.0,
            "spy_return": 0.0,
            "basket_alpha": 0.0,
            "win_rate": 0.0,
            "avg_max_drawdown": 0.0,
            "positions_df": empty_positions,
        }

    top_tickers = screener_df["ticker"].tolist()

    # Query forward prices for SPY from cutoff_date to eval_date
    spy_rows = db_manager.execute_read(
        """
        SELECT trade_date, close
        FROM daily_bars
        WHERE ticker = 'SPY' AND trade_date >= CAST(? AS DATE) AND trade_date <= CAST(? AS DATE)
        ORDER BY trade_date ASC;
        """,
        [cutoff_date, eval_date],
    )

    if spy_rows and len(spy_rows) >= 1:
        spy_entry = float(spy_rows[0][1])
        spy_exit = float(spy_rows[-1][1])
        spy_return = (spy_exit - spy_entry) / spy_entry if spy_entry > 0 else 0.0
    else:
        spy_return = 0.0

    position_results: list[dict[str, float | str | bool]] = []

    for ticker in top_tickers:
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

        # Calculate Max Drawdown (MDD) during period
        lows = [float(b[2]) for b in bars]
        min_low = min(lows) if lows else entry_price
        mdd = (min_low - entry_price) / entry_price if entry_price > 0 else 0.0

        alpha = ret - spy_return
        is_win = ret > 0.0

        position_results.append(
            {
                "ticker": ticker,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "return_pct": ret * 100.0,
                "spy_return_pct": spy_return * 100.0,
                "alpha_pct": alpha * 100.0,
                "max_drawdown_pct": mdd * 100.0,
                "is_win": is_win,
            }
        )

    positions_df = pd.DataFrame(position_results)

    if not positions_df.empty:
        mean_basket_return = float(positions_df["return_pct"].mean() / 100.0)
        basket_alpha = float(mean_basket_return - spy_return)
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
        run_id = f"pit_T-{cutoff_days_ago}_{cutoff_date.replace('-', '')}"
        scan_type = f"T-{cutoff_days_ago}"
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
        "cutoff_date": cutoff_date,
        "evaluation_date": eval_date,
        "cutoff_days_ago": cutoff_days_ago,
        "mean_basket_return": mean_basket_return,
        "spy_return": spy_return,
        "basket_alpha": basket_alpha,
        "win_rate": win_rate,
        "avg_max_drawdown": avg_mdd,
        "positions_df": positions_df,
    }
