"""Weekly Database Update & ntfy Notification Script.

Executes a full EOD market data delta update across US and TASE universes,
verifies that the update brought database records up to date,
and dispatches a detailed notification via ntfy.sh.
"""

from __future__ import annotations

import datetime
import logging
import os
import sys
from pathlib import Path

import duckdb
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("db_updater")

NTFY_TOPIC = os.getenv("NTFY_TOPIC", "stock_analysis_ranimela_alerts")
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"
DB_PATH = Path("market_data.duckdb")

# Allowable staleness threshold (in calendar days)
MAX_ALLOWED_STALENESS_DAYS = 4


def send_ntfy_notification(
    title: str,
    message: str,
    priority: str = "default",
    tags: list[str] | None = None,
) -> bool:
    """Send a notification via ntfy.sh HTTP POST request."""
    # Clean non-ASCII out of Title header for requests library compatibility
    title_clean = title.encode("ascii", "ignore").decode("ascii").strip()
    headers = {
        "Title": title_clean or "Stock Analysis Alert",
        "Priority": priority,
    }
    if tags:
        headers["Tags"] = ",".join(tags)

    try:
        response = requests.post(NTFY_URL, data=message.encode("utf-8"), headers=headers, timeout=15)
        if response.status_code == 200:
            logger.info("Successfully sent ntfy notification to %s", NTFY_URL)
            return True
        else:
            logger.error("Failed to send ntfy notification. Status: %s, Response: %s", response.status_code, response.text)
            return False
    except Exception as e:
        logger.error("Exception occurred while sending ntfy notification: %s", e)
        return False


def run_database_update() -> tuple[bool, str]:
    """Perform CLI market data update across US and TASE universes."""
    try:
        logger.info("Importing DataIngestor & DatabaseManager...")
        from src.db.db_manager import DatabaseManager
        from src.ingestion.data_ingestor import DataIngestor

        db_mgr = DatabaseManager(db_path=DB_PATH, read_only=False)
        ingestor = DataIngestor(db_manager=db_mgr)

        logger.info("Executing multi-exchange EOD delta sync (US + TASE)...")
        stats = ingestor.sync_universe(exchange="ALL")
        logger.info("Sync completed: %s", stats)

        # Read updated stats directly from DuckDB
        conn = duckdb.connect(str(DB_PATH), read_only=True)
        total_bars = conn.execute("SELECT COUNT(*) FROM daily_bars;").fetchone()[0]
        latest_date_raw = conn.execute("SELECT MAX(trade_date) FROM daily_bars;").fetchone()[0]
        latest_date = pd_date_to_date(latest_date_raw)

        spy_date_raw = conn.execute("SELECT MAX(trade_date) FROM daily_bars WHERE ticker = 'SPY';").fetchone()[0]
        spy_date = pd_date_to_date(spy_date_raw) if spy_date_raw else None

        tase_date_raw = conn.execute("SELECT MAX(trade_date) FROM daily_bars WHERE ticker = '^TA125.TA';").fetchone()[0]
        tase_date = pd_date_to_date(tase_date_raw) if tase_date_raw else None

        today = datetime.date.today()
        days_since_latest = (today - latest_date).days

        summary = (
            f"DB Update Summary (Executed on {today}):\n"
            f"- Sync Result Status: {stats.get('status', 'complete')}\n"
            f"- Synced Tickers: {stats.get('synced_tickers', 0)} / {stats.get('total_tickers', 0)}\n"
            f"- New Bars Inserted: {stats.get('total_bars_inserted', 0):,}\n"
            f"- Total Database Bars: {total_bars:,}\n"
            f"- Latest Overall Date: {latest_date} ({days_since_latest} day(s) ago)\n"
            f"- Latest SPY (US): {spy_date or 'N/A'}\n"
            f"- Latest ^TA125.TA (TASE): {tase_date or 'N/A'}"
        )

        if days_since_latest > MAX_ALLOWED_STALENESS_DAYS:
            return False, f"UPDATE INCOMPLETE / STALE!\n\n{summary}"
        else:
            return True, f"DATABASE UPDATED SUCCESSFULLY!\n\n{summary}"

    except Exception as err:
        err_msg = f"EXCEPTION DURING UPDATE: {err}"
        logger.error(err_msg, exc_info=True)
        return False, err_msg


def pd_date_to_date(val: any) -> datetime.date:
    """Helper to convert DuckDB date object or string to datetime.date."""
    if isinstance(val, datetime.date):
        return val
    return datetime.datetime.strptime(str(val)[:10], "%Y-%m-%d").date()


def main() -> None:
    """Run database update and send ntfy notification."""
    logger.info("Starting scheduled weekly database update process...")
    is_success, msg = run_database_update()

    if is_success:
        send_ntfy_notification(
            title="Stock Analysis DB Update: SUCCESS",
            message=msg,
            priority="default",
            tags=["white_check_mark", "database", "arrow_up"],
        )
        sys.exit(0)
    else:
        send_ntfy_notification(
            title="Stock Analysis DB Update: FAILED / OUTDATED",
            message=msg,
            priority="high",
            tags=["warning", "database", "x"],
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
