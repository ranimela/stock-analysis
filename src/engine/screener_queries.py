"""Screener Queries Module.

Provides DuckDB SQL window functions to execute the Stage-2 Momentum
screener template (liquidity, moving averages, 52W range, VCP tightness,
and Mansfield Relative Strength vs SPY) returning top recommendations.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

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
spy_bars AS (
    SELECT
        trade_date,
        close AS spy_close,
        LAG(close, 63) OVER (ORDER BY trade_date) AS spy_close_63,
        LAG(close, 252) OVER (ORDER BY trade_date) AS spy_close_252
    FROM daily_bars
    WHERE ticker = 'SPY' AND trade_date <= (SELECT target_date FROM date_anchor)
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
        sb.spy_close,
        sb.spy_close_63,
        sb.spy_close_252,
        CASE WHEN ls.vol_sma50 > 0 THEN CAST(ls.volume AS DOUBLE) / ls.vol_sma50 ELSE NULL END AS vdu_ratio,
        CASE WHEN ls.atr14 > 0 THEN (ls.high_10d - ls.low_10d) / ls.atr14 ELSE 0.0 END AS tightness_ratio,
        CASE
            WHEN ls.close_63 > 0 AND sb.spy_close IS NOT NULL AND sb.spy_close_63 > 0
                THEN ((ls.close / ls.close_63) / (sb.spy_close / sb.spy_close_63)) - 1.0
            WHEN ls.close_63 > 0
                THEN (ls.close / ls.close_63) - 1.0
            ELSE 0.0
        END AS rs_63,
        CASE
            WHEN ls.close_252 > 0 AND sb.spy_close IS NOT NULL AND sb.spy_close_252 > 0
                THEN ((ls.close / ls.close_252) / (sb.spy_close / sb.spy_close_252)) - 1.0
            WHEN ls.close_252 > 0
                THEN (ls.close / ls.close_252) - 1.0
            ELSE 0.0
        END AS rs_252
    FROM latest_snapshot ls
    LEFT JOIN spy_bars sb ON ls.trade_date = sb.trade_date
    WHERE
        (ls.asset_class IS NULL OR ls.asset_class = 'Common Stock')
        AND ls.ticker != 'SPY'
        AND ls.close >= 10.0
        AND ls.adv_20 >= 20000000.0
        AND ls.close > ls.sma50
        AND ls.sma50 > ls.sma150
        AND ls.sma150 > ls.sma200
        AND ls.sma200_20d_ago IS NOT NULL
        AND ls.sma200 > ls.sma200_20d_ago
        AND ls.close >= 1.30 * ls.low_52w
        AND ls.close >= 0.75 * ls.high_52w
        AND ls.atr14 IS NOT NULL AND ls.atr14 > 0
),
composite_scoring AS (
    SELECT
        sf.*,
        (0.70 * sf.rs_63 + 0.30 * sf.rs_252) AS rs_score,
        ((0.70 * sf.rs_63 + 0.30 * sf.rs_252) * 100.0) AS composite_score
    FROM stage_filters sf
    WHERE sf.tightness_ratio <= {max_tightness}  -- Hard VCP Coiling Gating Filter
),
final_ranked AS (
    SELECT
        cs.*,
        ROW_NUMBER() OVER (ORDER BY cs.rs_score DESC) AS rank
    FROM composite_scoring cs
)
SELECT
    CAST(rank AS INT) AS rank,
    ticker,
    COALESCE(name, ticker) AS name,
    exchange,
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
ORDER BY rank ASC
LIMIT 10;
"""


def run_screener(
    db_manager: DatabaseManager,
    cutoff_date: str,
    max_tightness: float = 2.0,
    manual_tickers: list[str] | None = None,
) -> pd.DataFrame:
    """Executes the quantitative momentum screener query for a cutoff date.

    Args:
        db_manager: DatabaseManager instance.
        cutoff_date: YYYY-MM-DD cutoff date string.
        max_tightness: Tightness ratio threshold ceiling. Defaults to 2.0.
        manual_tickers: Optional list of manual ticker symbols to force-include or evaluate.

    Returns:
        pd.DataFrame: Top recommended stocks clearing filter stages,
            ranked by pure Mansfield Relative Strength score.
    """
    if manual_tickers:
        placeholders = ", ".join(["?"] * len(manual_tickers))
        manual_sql = f"""
        WITH date_anchor AS (
            SELECT MAX(trade_date) AS target_date
            FROM daily_bars
            WHERE trade_date <= CAST(? AS DATE)
        ),
        spy_bars AS (
            SELECT
                trade_date,
                close AS spy_close,
                LAG(close, 63) OVER (ORDER BY trade_date) AS spy_close_63,
                LAG(close, 252) OVER (ORDER BY trade_date) AS spy_close_252
            FROM daily_bars
            WHERE ticker = 'SPY' AND trade_date <= (SELECT target_date FROM date_anchor)
        ),
        ticker_dates AS (
            SELECT ticker, MAX(trade_date) AS max_ticker_date
            FROM daily_bars
            WHERE trade_date <= CAST(? AS DATE)
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
                sb.spy_close,
                sb.spy_close_63,
                sb.spy_close_252,
                CASE WHEN ls.vol_sma50 > 0 THEN CAST(ls.volume AS DOUBLE) / ls.vol_sma50 ELSE NULL END AS vdu_ratio,
                CASE WHEN ls.atr14 > 0 THEN (ls.high_10d - ls.low_10d) / ls.atr14 ELSE 0.0 END AS tightness_ratio,
                CASE
                    WHEN ls.close_63 > 0 AND sb.spy_close IS NOT NULL AND sb.spy_close_63 > 0
                        THEN ((ls.close / ls.close_63) / (sb.spy_close / sb.spy_close_63)) - 1.0
                    WHEN ls.close_63 > 0
                        THEN (ls.close / ls.close_63) - 1.0
                    ELSE 0.0
                END AS rs_63,
                CASE
                    WHEN ls.close_252 > 0 AND sb.spy_close IS NOT NULL AND sb.spy_close_252 > 0
                        THEN ((ls.close / ls.close_252) / (sb.spy_close / sb.spy_close_252)) - 1.0
                    WHEN ls.close_252 > 0
                        THEN (ls.close / ls.close_252) - 1.0
                    ELSE 0.0
                END AS rs_252
            FROM latest_snapshot ls
            LEFT JOIN spy_bars sb ON ls.trade_date = sb.trade_date
            WHERE
                ls.ticker IN ({placeholders})
                OR (
                    (ls.asset_class IS NULL OR ls.asset_class = 'Common Stock')
                    AND ls.ticker != 'SPY'
                    AND ls.close >= 10.0
                    AND ls.adv_20 >= 20000000.0
                    AND ls.close > ls.sma50
                    AND ls.sma50 > ls.sma150
                    AND ls.sma150 > ls.sma200
                    AND ls.sma200_20d_ago IS NOT NULL
                    AND ls.sma200 > ls.sma200_20d_ago
                    AND ls.close >= 1.30 * ls.low_52w
                    AND ls.close >= 0.75 * ls.high_52w
                    AND ls.atr14 IS NOT NULL AND ls.atr14 > 0
                )
        ),
        composite_scoring AS (
            SELECT
                sf.*,
                (0.70 * sf.rs_63 + 0.30 * sf.rs_252) AS rs_score,
                ((0.70 * sf.rs_63 + 0.30 * sf.rs_252) * 100.0) AS composite_score
            FROM stage_filters sf
            WHERE sf.tightness_ratio <= 3.5 OR sf.ticker IN ({placeholders})
        ),
        final_ranked AS (
            SELECT
                cs.*,
                ROW_NUMBER() OVER (ORDER BY cs.rs_score DESC) AS rank
            FROM composite_scoring cs
        )
        SELECT
            CAST(rank AS INT) AS rank,
            sm.ticker,
            COALESCE(sm.name, sm.ticker) AS name,
            COALESCE(sm.exchange, 'NASDAQ') AS exchange,
            sm.market_cap,
            sm.trade_date,
            sm.close,
            sm.adv_20,
            sm.sma50,
            sm.sma150,
            sm.sma200,
            sm.sma200_20d_ago,
            sm.high_52w,
            sm.low_52w,
            sm.tightness_ratio,
            sm.vdu_ratio,
            sm.rs_score,
            sm.composite_score
        FROM final_ranked sm
        ORDER BY sm.rs_score DESC;
        """
        with db_manager.read_cursor() as conn:
            manual_df = conn.execute(manual_sql, [cutoff_date] + [cutoff_date] + manual_tickers + manual_tickers).df()
        if not manual_df.empty:
            return manual_df

    query = SCREENER_SQL.format(max_tightness=max_tightness)
    with db_manager.read_cursor() as conn:
        df = conn.execute(query, [cutoff_date]).df()

    if df.empty and max_tightness == 2.0:
        fallback_query = SCREENER_SQL.format(max_tightness=3.0)
        with db_manager.read_cursor() as conn:
            df = conn.execute(fallback_query, [cutoff_date]).df()

    if df.empty:
        logger.info("No candidates passed screener for cutoff date %s.", cutoff_date)

    return df
