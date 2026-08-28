"""Screener Queries Module.

Provides DuckDB SQL window functions to execute the Stage-2 Momentum
screener template (liquidity, moving averages, 52W range, VCP tightness,
and Mansfield Relative Strength vs benchmark index) returning top recommendations
parameterized across equity universes (US and TASE).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import pandas as pd

if TYPE_CHECKING:
    from src.db.db_manager import DatabaseManager

logger = logging.getLogger(__name__)

SCREENER_SQL = """
WITH date_anchor AS (
    SELECT MAX(trade_date) AS target_date
    FROM daily_bars
    WHERE trade_date <= CAST(? AS DATE)
),
benchmark_bars AS (
    SELECT
        trade_date,
        close AS bench_close,
        LAG(close, 63) OVER (ORDER BY trade_date) AS bench_close_63,
        LAG(close, 252) OVER (ORDER BY trade_date) AS bench_close_252
    FROM daily_bars
    WHERE ticker = '{benchmark_ticker}' AND trade_date <= (SELECT target_date FROM date_anchor)
),
ticker_dates AS (
    SELECT ticker, MAX(trade_date) AS max_ticker_date
    FROM daily_bars
    WHERE trade_date <= (SELECT target_date FROM date_anchor)
    GROUP BY ticker
),
base_bars AS (
    SELECT
        b.ticker,
        b.trade_date,
        b.open,
        b.high,
        b.low,
        b.close,
        b.volume,
        m.name,
        m.exchange,
        m.asset_class,
        m.market_cap,
        LAG(b.close, 1) OVER (PARTITION BY b.ticker ORDER BY b.trade_date) AS prev_close,
        LAG(b.close, 63) OVER (PARTITION BY b.ticker ORDER BY b.trade_date) AS close_63,
        LAG(b.close, 252) OVER (PARTITION BY b.ticker ORDER BY b.trade_date) AS close_252,
        MAX(b.high) OVER (PARTITION BY b.ticker ORDER BY b.trade_date ROWS BETWEEN 9 PRECEDING AND CURRENT ROW) AS high_10d,
        MIN(b.low) OVER (PARTITION BY b.ticker ORDER BY b.trade_date ROWS BETWEEN 9 PRECEDING AND CURRENT ROW) AS low_10d,
        MAX(b.high) OVER (PARTITION BY b.ticker ORDER BY b.trade_date ROWS BETWEEN 251 PRECEDING AND CURRENT ROW) AS high_52w,
        MIN(b.low) OVER (PARTITION BY b.ticker ORDER BY b.trade_date ROWS BETWEEN 251 PRECEDING AND CURRENT ROW) AS low_52w,
        AVG(b.close * b.volume) OVER (PARTITION BY b.ticker ORDER BY b.trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS adv_20,
        AVG(b.volume) OVER (PARTITION BY b.ticker ORDER BY b.trade_date ROWS BETWEEN 49 PRECEDING AND CURRENT ROW) AS vol_sma50,
        AVG(b.close) OVER (PARTITION BY b.ticker ORDER BY b.trade_date ROWS BETWEEN 49 PRECEDING AND CURRENT ROW) AS sma50,
        AVG(b.close) OVER (PARTITION BY b.ticker ORDER BY b.trade_date ROWS BETWEEN 149 PRECEDING AND CURRENT ROW) AS sma150,
        AVG(b.close) OVER (PARTITION BY b.ticker ORDER BY b.trade_date ROWS BETWEEN 199 PRECEDING AND CURRENT ROW) AS sma200
    FROM daily_bars b
    LEFT JOIN symbol_metadata m ON b.ticker = m.ticker
    INNER JOIN ticker_dates td ON b.ticker = td.ticker AND b.trade_date <= td.max_ticker_date
),
bar_indicators AS (
    SELECT
        bb.*,
        LAG(bb.sma200, 20) OVER (PARTITION BY bb.ticker ORDER BY bb.trade_date) AS sma200_20d_ago,
        GREATEST(
            bb.high - bb.low,
            ABS(bb.high - COALESCE(bb.prev_close, bb.close)),
            ABS(bb.low - COALESCE(bb.prev_close, bb.close))
        ) AS tr
    FROM base_bars bb
),
bar_atr AS (
    SELECT
        bi.*,
        AVG(bi.tr) OVER (PARTITION BY bi.ticker ORDER BY bi.trade_date ROWS BETWEEN 13 PRECEDING AND CURRENT ROW) AS atr14
    FROM bar_indicators bi
),
latest_snapshot AS (
    SELECT ba.*
    FROM bar_atr ba
    INNER JOIN ticker_dates td ON ba.ticker = td.ticker AND ba.trade_date = td.max_ticker_date
),
stage_filters AS (
    SELECT
        ls.*,
        bb.bench_close,
        bb.bench_close_63,
        bb.bench_close_252,
        CASE WHEN ls.vol_sma50 > 0 THEN CAST(ls.volume AS DOUBLE) / ls.vol_sma50 ELSE NULL END AS vdu_ratio,
        CASE WHEN ls.atr14 > 0 THEN (ls.high_10d - ls.low_10d) / ls.atr14 ELSE 0.0 END AS tightness_ratio,
        CASE
            WHEN ls.close_63 > 0 AND bb.bench_close IS NOT NULL AND bb.bench_close_63 > 0
                THEN ((ls.close / ls.close_63) / (bb.bench_close / bb.bench_close_63)) - 1.0
            WHEN ls.close_63 > 0
                THEN (ls.close / ls.close_63) - 1.0
            ELSE 0.0
        END AS rs_63,
        CASE
            WHEN ls.close_252 > 0 AND bb.bench_close IS NOT NULL AND bb.bench_close_252 > 0
                THEN ((ls.close / ls.close_252) / (bb.bench_close / bb.bench_close_252)) - 1.0
            WHEN ls.close_252 > 0
                THEN (ls.close / ls.close_252) - 1.0
            ELSE 0.0
        END AS rs_252
    FROM latest_snapshot ls
    LEFT JOIN benchmark_bars bb ON ls.trade_date = bb.trade_date
    WHERE
        (ls.asset_class IS NULL OR ls.asset_class = 'Common Stock')
        AND ls.ticker != '{benchmark_ticker}'
        AND {exchange_filter}
        AND ls.close >= {min_price:.2f}
        AND ls.adv_20 >= {min_adv20:.2f}
        AND ls.close > ls.sma50
        AND ls.sma50 > ls.sma150
        AND ls.sma150 > ls.sma200
        AND ls.sma200_20d_ago IS NOT NULL
        AND ls.sma200 > ls.sma200_20d_ago
        AND ls.close >= {min_off_low_mult:.2f} * ls.low_52w
        AND ls.close >= {min_of_high_mult:.2f} * ls.high_52w
        AND ls.atr14 IS NOT NULL AND ls.atr14 > 0
),
composite_scoring AS (
    SELECT
        sf.*,
        (0.70 * sf.rs_63 + 0.30 * sf.rs_252) AS rs_score,
        (
            0.60 * (PERCENT_RANK() OVER (ORDER BY (0.70 * sf.rs_63 + 0.30 * sf.rs_252) ASC) * 100.0) +
            0.40 * (PERCENT_RANK() OVER (ORDER BY (CASE WHEN sf.tightness_ratio > 0 THEN 1.0 / sf.tightness_ratio ELSE 0 END) ASC) * 100.0)
        ) AS composite_score
    FROM stage_filters sf
    WHERE sf.tightness_ratio <= {max_tightness}  -- Hard VCP Coiling Gating Filter
),
final_ranked AS (
    SELECT
        cs.*,
        ROW_NUMBER() OVER (ORDER BY cs.composite_score DESC) AS rank
    FROM composite_scoring cs
)
SELECT
    CAST(rank AS INT) AS rank,
    ticker,
    COALESCE(name, ticker) AS name,
    COALESCE(exchange, '{default_exchange}') AS exchange,
    market_cap,
    trade_date,
    close,
    adv_20,
    sma50,
    sma150,
    sma200,
    sma200_20d_ago,
    high_52w,
    low_52w,
    tightness_ratio,
    vdu_ratio,
    rs_score,
    composite_score
FROM final_ranked
ORDER BY rank ASC;
"""

MANUAL_SCREENER_SQL = """
WITH date_anchor AS (
    SELECT MAX(trade_date) AS target_date
    FROM daily_bars
    WHERE trade_date <= CAST(? AS DATE)
),
benchmark_bars AS (
    SELECT
        trade_date,
        close AS bench_close,
        LAG(close, 63) OVER (ORDER BY trade_date) AS bench_close_63,
        LAG(close, 252) OVER (ORDER BY trade_date) AS bench_close_252
    FROM daily_bars
    WHERE ticker = '{benchmark_ticker}' AND trade_date <= (SELECT target_date FROM date_anchor)
),
ticker_dates AS (
    SELECT ticker, MAX(trade_date) AS max_ticker_date
    FROM daily_bars
    WHERE trade_date <= (SELECT target_date FROM date_anchor)
    GROUP BY ticker
),
base_bars AS (
    SELECT
        b.ticker,
        b.trade_date,
        b.open,
        b.high,
        b.low,
        b.close,
        b.volume,
        m.name,
        m.exchange,
        m.asset_class,
        m.market_cap,
        LAG(b.close, 1) OVER (PARTITION BY b.ticker ORDER BY b.trade_date) AS prev_close,
        LAG(b.close, 63) OVER (PARTITION BY b.ticker ORDER BY b.trade_date) AS close_63,
        LAG(b.close, 252) OVER (PARTITION BY b.ticker ORDER BY b.trade_date) AS close_252,
        MAX(b.high) OVER (PARTITION BY b.ticker ORDER BY b.trade_date ROWS BETWEEN 9 PRECEDING AND CURRENT ROW) AS high_10d,
        MIN(b.low) OVER (PARTITION BY b.ticker ORDER BY b.trade_date ROWS BETWEEN 9 PRECEDING AND CURRENT ROW) AS low_10d,
        MAX(b.high) OVER (PARTITION BY b.ticker ORDER BY b.trade_date ROWS BETWEEN 251 PRECEDING AND CURRENT ROW) AS high_52w,
        MIN(b.low) OVER (PARTITION BY b.ticker ORDER BY b.trade_date ROWS BETWEEN 251 PRECEDING AND CURRENT ROW) AS low_52w,
        AVG(b.close * b.volume) OVER (PARTITION BY b.ticker ORDER BY b.trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS adv_20,
        AVG(b.volume) OVER (PARTITION BY b.ticker ORDER BY b.trade_date ROWS BETWEEN 49 PRECEDING AND CURRENT ROW) AS vol_sma50,
        AVG(b.close) OVER (PARTITION BY b.ticker ORDER BY b.trade_date ROWS BETWEEN 49 PRECEDING AND CURRENT ROW) AS sma50,
        AVG(b.close) OVER (PARTITION BY b.ticker ORDER BY b.trade_date ROWS BETWEEN 149 PRECEDING AND CURRENT ROW) AS sma150,
        AVG(b.close) OVER (PARTITION BY b.ticker ORDER BY b.trade_date ROWS BETWEEN 199 PRECEDING AND CURRENT ROW) AS sma200
    FROM daily_bars b
    LEFT JOIN symbol_metadata m ON b.ticker = m.ticker
    INNER JOIN ticker_dates td ON b.ticker = td.ticker AND b.trade_date <= td.max_ticker_date
),
bar_indicators AS (
    SELECT
        bb.*,
        LAG(bb.sma200, 20) OVER (PARTITION BY bb.ticker ORDER BY bb.trade_date) AS sma200_20d_ago,
        GREATEST(
            bb.high - bb.low,
            ABS(bb.high - COALESCE(bb.prev_close, bb.close)),
            ABS(bb.low - COALESCE(bb.prev_close, bb.close))
        ) AS tr
    FROM base_bars bb
),
bar_atr AS (
    SELECT
        bi.*,
        AVG(bi.tr) OVER (PARTITION BY bi.ticker ORDER BY bi.trade_date ROWS BETWEEN 13 PRECEDING AND CURRENT ROW) AS atr14
    FROM bar_indicators bi
),
latest_snapshot AS (
    SELECT ba.*
    FROM bar_atr ba
    INNER JOIN ticker_dates td ON ba.ticker = td.ticker AND ba.trade_date = td.max_ticker_date
),
stage_filters AS (
    SELECT
        ls.*,
        bb.bench_close,
        bb.bench_close_63,
        bb.bench_close_252,
        CASE WHEN ls.vol_sma50 > 0 THEN CAST(ls.volume AS DOUBLE) / ls.vol_sma50 ELSE NULL END AS vdu_ratio,
        CASE WHEN ls.atr14 > 0 THEN (ls.high_10d - ls.low_10d) / ls.atr14 ELSE 0.0 END AS tightness_ratio,
        CASE
            WHEN ls.close_63 > 0 AND bb.bench_close IS NOT NULL AND bb.bench_close_63 > 0
                THEN ((ls.close / ls.close_63) / (bb.bench_close / bb.bench_close_63)) - 1.0
            WHEN ls.close_63 > 0
                THEN (ls.close / ls.close_63) - 1.0
            ELSE 0.0
        END AS rs_63,
        CASE
            WHEN ls.close_252 > 0 AND bb.bench_close IS NOT NULL AND bb.bench_close_252 > 0
                THEN ((ls.close / ls.close_252) / (bb.bench_close / bb.bench_close_252)) - 1.0
            WHEN ls.close_252 > 0
                THEN (ls.close / ls.close_252) - 1.0
            ELSE 0.0
        END AS rs_252
    FROM latest_snapshot ls
    LEFT JOIN benchmark_bars bb ON ls.trade_date = bb.trade_date
    WHERE
        ls.ticker IN ({placeholders})
        OR (
            (ls.asset_class IS NULL OR ls.asset_class = 'Common Stock')
            AND ls.ticker != '{benchmark_ticker}'
            AND {exchange_filter}
            AND ls.close >= {min_price:.2f}
            AND ls.adv_20 >= {min_adv20:.2f}
            AND ls.close > ls.sma50
            AND ls.sma50 > ls.sma150
            AND ls.sma150 > ls.sma200
            AND ls.sma200_20d_ago IS NOT NULL
            AND ls.sma200 > ls.sma200_20d_ago
            AND ls.close >= {min_off_low_mult:.2f} * ls.low_52w
            AND ls.close >= {min_of_high_mult:.2f} * ls.high_52w
            AND ls.atr14 IS NOT NULL AND ls.atr14 > 0
        )
),
composite_scoring AS (
    SELECT
        sf.*,
        (0.70 * sf.rs_63 + 0.30 * sf.rs_252) AS rs_score,
        (
            0.60 * (PERCENT_RANK() OVER (ORDER BY (0.70 * sf.rs_63 + 0.30 * sf.rs_252) ASC) * 100.0) +
            0.40 * (PERCENT_RANK() OVER (ORDER BY (CASE WHEN sf.tightness_ratio > 0 THEN 1.0 / sf.tightness_ratio ELSE 0 END) ASC) * 100.0)
        ) AS composite_score
    FROM stage_filters sf
    WHERE sf.tightness_ratio <= {max_tightness} OR sf.ticker IN ({placeholders})
),
final_ranked AS (
    SELECT
        cs.*,
        ROW_NUMBER() OVER (ORDER BY cs.composite_score DESC) AS rank
    FROM composite_scoring cs
)
SELECT
    CAST(rank AS INT) AS rank,
    ticker,
    COALESCE(name, ticker) AS name,
    COALESCE(exchange, '{default_exchange}') AS exchange,
    market_cap,
    trade_date,
    close,
    adv_20,
    sma50,
    sma150,
    sma200,
    sma200_20d_ago,
    high_52w,
    low_52w,
    tightness_ratio,
    vdu_ratio,
    rs_score,
    composite_score
FROM final_ranked
ORDER BY rank ASC;
"""


def _execute_df(db_manager: DatabaseManager | Any, query: str, params: list[Any]) -> pd.DataFrame:
    """Helper to execute DuckDB query against DatabaseManager or raw connection."""
    if hasattr(db_manager, "read_cursor"):
        with db_manager.read_cursor() as conn:
            return conn.execute(query, params).df()
    elif hasattr(db_manager, "execute"):
        return db_manager.execute(query, params).df()
    else:
        raise TypeError(f"Unsupported db_manager type: {type(db_manager)}")


def run_screener(
    db_manager: DatabaseManager | Any,
    cutoff_date: str | None = None,
    universe: str = "US",
    benchmark_ticker: str | None = None,
    max_tightness: float = 3.5,
    manual_tickers: list[str] | None = None,
    pct_off_low: float = 30.0,
    pct_within_high: float = 25.0,
    min_price: float | None = None,
    min_adv20: float | None = None,
) -> pd.DataFrame:
    """Executes the quantitative momentum screener query for a cutoff date and universe.

    Args:
        db_manager: DatabaseManager instance or DuckDB connection.
        cutoff_date: YYYY-MM-DD cutoff date string. If None, uses maximum available trade_date.
        universe: Target equity universe ('US', 'TASE', or 'ALL'). Defaults to 'US'.
        benchmark_ticker: Optional benchmark ticker override. If None, routes 'SPY' for US
            and '^TA125.TA' for TASE.
        max_tightness: Tightness ratio threshold ceiling. Defaults to 3.5.
        manual_tickers: Optional list of manual ticker symbols to force-include or evaluate.
        pct_off_low: Minimum % gain off 52-week low. Defaults to 30.0 (+30%).
        pct_within_high: Maximum allowable % distance below 52-week high. Defaults to 25.0 (within 25%).
        min_price: Minimum price floor. If None, defaults to 10.0 for US, 100.0 (Agorot) for TASE.
        min_adv20: Minimum 20-day turnover floor. If None, defaults to 20,000,000.0.

    Returns:
        pd.DataFrame: Top recommended stocks clearing filter stages,
            ranked by isolated universe composite score.
    """
    target_universe = universe.strip().upper() if universe else "US"

    # Auto-route universe if all manual tickers are TASE tickers (.TA)
    if manual_tickers and target_universe == "US":
        if all(t.strip().upper().endswith(".TA") for t in manual_tickers):
            target_universe = "TASE"

    # Dynamic benchmark routing
    if benchmark_ticker is None:
        if target_universe == "TASE":
            active_benchmark = "^TA125.TA"
        else:
            active_benchmark = "SPY"
    else:
        active_benchmark = benchmark_ticker.strip().upper()

    # Dynamic exchange filter and default values
    if target_universe == "TASE":
        exchange_filter = "(ls.exchange = 'TASE' OR ls.ticker LIKE '%.TA')"
        default_exchange = "TASE"
        active_min_price = 100.0 if min_price is None else float(min_price)
        active_min_adv20 = 20000000.0 if min_adv20 is None else float(min_adv20)
    elif target_universe == "ALL":
        exchange_filter = "(1=1)"
        default_exchange = "US"
        active_min_price = 10.0 if min_price is None else float(min_price)
        active_min_adv20 = 20000000.0 if min_adv20 is None else float(min_adv20)
    else:  # US
        exchange_filter = "((ls.exchange IN ('NASDAQ', 'NYSE', 'AMEX', 'ARCA', 'BATS', 'IEX') OR ls.exchange IS NULL) AND ls.ticker NOT LIKE '%.TA')"
        default_exchange = "NASDAQ"
        active_min_price = 10.0 if min_price is None else float(min_price)
        active_min_adv20 = 20000000.0 if min_adv20 is None else float(min_adv20)

    # Resolve cutoff_date if None
    if cutoff_date is None:
        if hasattr(db_manager, "execute_read"):
            rows = db_manager.execute_read("SELECT MAX(trade_date) FROM daily_bars;")
            cutoff_date = str(rows[0][0]) if (rows and rows[0][0]) else "9999-12-31"
        elif hasattr(db_manager, "execute"):
            res = db_manager.execute("SELECT MAX(trade_date) FROM daily_bars;").fetchall()
            cutoff_date = str(res[0][0]) if (res and res[0][0]) else "9999-12-31"
        else:
            cutoff_date = "9999-12-31"

    min_off_low_mult = 1.0 + (pct_off_low / 100.0)
    min_of_high_mult = 1.0 - (pct_within_high / 100.0)

    if manual_tickers:
        placeholders = ", ".join(["?"] * len(manual_tickers))
        manual_sql = MANUAL_SCREENER_SQL.format(
            benchmark_ticker=active_benchmark,
            exchange_filter=exchange_filter,
            default_exchange=default_exchange,
            min_price=active_min_price,
            min_adv20=active_min_adv20,
            max_tightness=max_tightness,
            min_off_low_mult=min_off_low_mult,
            min_of_high_mult=min_of_high_mult,
            placeholders=placeholders,
        )
        manual_df = _execute_df(
            db_manager,
            manual_sql,
            [cutoff_date] + manual_tickers + manual_tickers,
        )
        if not manual_df.empty:
            return manual_df

    query = SCREENER_SQL.format(
        benchmark_ticker=active_benchmark,
        exchange_filter=exchange_filter,
        default_exchange=default_exchange,
        min_price=active_min_price,
        min_adv20=active_min_adv20,
        max_tightness=max_tightness,
        min_off_low_mult=min_off_low_mult,
        min_of_high_mult=min_of_high_mult,
    )
    df = _execute_df(db_manager, query, [cutoff_date])

    if df.empty and max_tightness == 2.0:
        fallback_query = SCREENER_SQL.format(
            benchmark_ticker=active_benchmark,
            exchange_filter=exchange_filter,
            default_exchange=default_exchange,
            min_price=active_min_price,
            min_adv20=active_min_adv20,
            max_tightness=3.0,
            min_off_low_mult=min_off_low_mult,
            min_of_high_mult=min_of_high_mult,
        )
        df = _execute_df(db_manager, fallback_query, [cutoff_date])

    if df.empty:
        logger.info("No candidates passed screener for cutoff date %s (%s).", cutoff_date, target_universe)

    return df


