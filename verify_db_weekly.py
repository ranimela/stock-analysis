"""Weekly Database Verification & ntfy Notification Script.

Checks market_data.duckdb to verify that US and TASE market data is up-to-date
(within expected trading day thresholds) and sends a notification via ntfy.sh.
"""

from __future__ import annotations

import datetime
import logging
import os
import sys
from pathlib import Path
from urllib.parse import quote

import duckdb
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("db_verifier")

# Default ntfy topic name. Can be overridden via NTFY_TOPIC environment variable.
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "stock_analysis_ranimela_alerts")
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"
DB_PATH = Path("market_data.duckdb")

# Allowable staleness thresholds (in calendar days)
# E.g., over a weekend, a 4-day age is normal (Friday -> Monday).
MAX_ALLOWED_STALENESS_DAYS = 4


def send_ntfy_notification(
    title: str,
    message: str,
    priority: str = "default",
    tags: list[str] | None = None,
) -> bool:
    """Send a notification via ntfy.sh HTTP POST request using safe RFC-2047 / URL-safe title encoding."""
    headers = {
        "Title": f"=?utf-8?B?{quote(title)}?=" if any(ord(c) > 127 for c in title) else title,
        "Priority": priority,
    }
    # Clean non-ASCII out of Title header for requests library compatibility
    title_clean = title.encode("ascii", "ignore").decode("ascii").strip()
    headers["Title"] = title_clean or "Stock Analysis Alert"

    if tags:
        headers["Tags"] = ",".join(tags)

    try:
        response = requests.post(NTFY_URL, data=message.encode("utf-8"), headers=headers, timeout=10)
        if response.status_code == 200:
            logger.info("Successfully sent ntfy notification to %s", NTFY_URL)
            return True
        else:
            logger.error("Failed to send ntfy notification. Status: %s, Response: %s", response.status_code, response.text)
            return False
    except Exception as e:
        logger.error("Exception occurred while sending ntfy notification: %s", e)
        return False


def verify_database() -> tuple[bool, str]:
    """Verify DuckDB market database staleness and return status tuple (is_valid, summary_message)."""
    if not DB_PATH.exists():
        msg = f"[CRITICAL] Database file '{DB_PATH.resolve()}' does not exist!"
        return False, msg

    try:
        conn = duckdb.connect(str(DB_PATH), read_only=True)

        # 1. Overall row count
        total_bars = conn.execute("SELECT COUNT(*) FROM daily_bars;").fetchone()[0]

        # 2. Latest overall date
        latest_date_raw = conn.execute("SELECT MAX(trade_date) FROM daily_bars;").fetchone()[0]
        if not latest_date_raw:
            msg = "[CRITICAL] Database table 'daily_bars' is empty!"
            return False, msg

        latest_date = pd_date_to_date(latest_date_raw)

        # 3. SPY (US Benchmark) latest date
        spy_date_raw = conn.execute("SELECT MAX(trade_date) FROM daily_bars WHERE ticker = 'SPY';").fetchone()[0]
        spy_date = pd_date_to_date(spy_date_raw) if spy_date_raw else None

        # 4. ^TA125.TA (TASE Benchmark) latest date
        tase_date_raw = conn.execute("SELECT MAX(trade_date) FROM daily_bars WHERE ticker = '^TA125.TA';").fetchone()[0]
        tase_date = pd_date_to_date(tase_date_raw) if tase_date_raw else None

        today = datetime.date.today()
        days_since_latest = (today - latest_date).days

        summary = (
            f"DB Status Summary (Checked on {today}):\n"
            f"- Total Price Bars: {total_bars:,}\n"
            f"- Latest Overall Date: {latest_date} ({days_since_latest} day(s) ago)\n"
            f"- Latest SPY (US): {spy_date or 'N/A'}\n"
            f"- Latest ^TA125.TA (TASE): {tase_date or 'N/A'}"
        )
        logger.info("\n%s", summary)

        if days_since_latest > MAX_ALLOWED_STALENESS_DAYS:
            failure_msg = (
                f"DATABASE OUTDATED!\n\n"
                f"The database has not been updated for {days_since_latest} days (Threshold: {MAX_ALLOWED_STALENESS_DAYS} days).\n\n"
                f"{summary}"
            )
            return False, failure_msg
        else:
            success_msg = f"DATABASE IS UP TO DATE!\n\n{summary}"
            return True, success_msg

    except Exception as err:
        error_msg = f"[ERROR] Exception during database verification: {err}"
        logger.error(error_msg)
        return False, error_msg


def pd_date_to_date(val: any) -> datetime.date:
    """Helper to convert DuckDB date object or string to datetime.date."""
    if isinstance(val, datetime.date):
        return val
    return datetime.datetime.strptime(str(val)[:10], "%Y-%m-%d").date()


def main() -> None:
    """Run verification check and dispatch ntfy alert."""
    logger.info("Starting weekly database verification process...")
    is_success, msg = verify_database()

    if is_success:
        send_ntfy_notification(
            title="Stock Analysis DB Check: UP TO DATE",
            message=msg,
            priority="default",
            tags=["white_check_mark", "database"],
        )
        sys.exit(0)
    else:
        send_ntfy_notification(
            title="Stock Analysis DB Check: OUTDATED / ERROR",
            message=msg,
            priority="high",
            tags=["warning", "database"],
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
