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
    WHERE b.trade_date <= (SELECT target_date FROM date_anchor)
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
    WHERE ba.trade_date = (SELECT target_date FROM date_anchor)
),
stage_filters AS (
    SELECT
        ls.*,
        sb.spy_close,
        sb.spy_close_63,
        sb.spy_close_252,
        CASE WHEN ls.vol_sma50 > 0 THEN CAST(ls.volume AS DOUBLE) / ls.vol_sma50 ELSE NULL END AS vdu_ratio,
        CASE WHEN ls.atr14 > 0 THEN (ls.high_10d - ls.low_10d) / ls.atr14 ELSE NULL END AS tightness_ratio,
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
        -- Asset Class Gate
        (ls.asset_class IS NULL OR ls.asset_class = 'Common Stock')
        AND ls.ticker != 'SPY'
        -- Stage 1: Liquidity & Price Floor
        AND ls.close >= 10.0
        AND ls.adv_20 >= 20000000.0
        -- Stage 2: Structural Trend Template
        AND ls.close > ls.sma50
        AND ls.sma50 > ls.sma150
        AND ls.sma150 > ls.sma200
        AND ls.sma200_20d_ago IS NOT NULL
        AND ls.sma200 > ls.sma200_20d_ago
        AND ls.close >= 1.30 * ls.low_52w
        AND ls.close >= 0.75 * ls.high_52w
        -- Stage 3: Volatility & Volume Contraction
        AND ls.atr14 IS NOT NULL AND ls.atr14 > 0
        AND (ls.high_10d - ls.low_10d) / ls.atr14 <= 2.0
        AND ls.vol_sma50 > 0
        AND ls.volume <= 0.60 * ls.vol_sma50
),
composite_scoring AS (
    SELECT
        sf.*,
        (0.70 * sf.rs_63 + 0.30 * sf.rs_252) AS rs_score,
        PERCENT_RANK() OVER (ORDER BY (0.70 * sf.rs_63 + 0.30 * sf.rs_252) ASC) * 100.0 AS rs_rank,
        PERCENT_RANK() OVER (ORDER BY (CASE WHEN sf.tightness_ratio > 0 THEN 1.0 / sf.tightness_ratio ELSE 0 END) ASC) * 100.0 AS tightness_rank
    FROM stage_filters sf
),
final_ranked AS (
    SELECT
        cs.*,
        (0.60 * cs.rs_rank + 0.40 * cs.tightness_rank) AS composite_score,
        ROW_NUMBER() OVER (ORDER BY (0.60 * cs.rs_rank + 0.40 * cs.tightness_rank) DESC, cs.rs_score DESC) AS rank
    FROM composite_scoring cs
)
SELECT
    CAST(rank AS INT) AS rank,
    ticker,
    COALESCE(name, ticker) AS name,
    exchange,
    trade_date,
    close,
    adv_20,
    sma50,
    sma150,
    sma200,
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


def run_screener(db_manager: DatabaseManager, cutoff_date: str) -> pd.DataFrame:
    """Executes the quantitative momentum screener query for a cutoff date.

    Args:
        db_manager: Initialized DatabaseManager instance.
        cutoff_date: Cutoff date string in 'YYYY-MM-DD' format.

    Returns:
        pd.DataFrame: Top 10 recommended stocks clearing all filter stages,
            ranked by composite score (60% Relative Strength rank +
            40% Tightness rank).
    """
    with db_manager.read_cursor() as conn:
        df = conn.execute(SCREENER_SQL, [cutoff_date]).df()

    if df.empty:
        logger.info("No candidates passed screener for cutoff date %s.", cutoff_date)

    return df
