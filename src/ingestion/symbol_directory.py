"""Symbol directory downloader and parser module.

Downloads stock symbols from NASDAQ FTP / HTTP endpoints and filters for common stocks,
excluding ETFs, preferred stock, warrants, rights, units, test tickers, and SPACs.
"""

from __future__ import annotations

import logging
from typing import Any, Sequence
import urllib.request

from src.db.db_manager import DatabaseManager

logger = logging.getLogger(__name__)

NASDAQ_LISTED_HTTP_URL = "https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt"
OTHER_LISTED_HTTP_URL = "https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt"

NASDAQ_LISTED_FTP_URL = "ftp://ftp.nasdaqtrader.com/SymbolDirectory/nasdaqlisted.txt"
OTHER_LISTED_FTP_URL = "ftp://ftp.nasdaqtrader.com/SymbolDirectory/otherlisted.txt"

EXCHANGE_MAP = {
    "A": "AMEX",
    "N": "NYSE",
    "P": "ARCA",
    "Z": "BATS",
    "V": "IEX",
    "Q": "NASDAQ",
    "G": "NASDAQ",
    "S": "NASDAQ",
}


def download_file_content(primary_url: str, fallback_url: str, timeout: int = 30) -> str:
    """Download text content from a primary URL, falling back to an alternative URL.

    Args:
        primary_url: Main URL (e.g. HTTP/HTTPS).
        fallback_url: Backup URL (e.g. FTP).
        timeout: Network timeout in seconds. Defaults to 30.

    Returns:
        str: Decoded UTF-8 string content.

    Raises:
        RuntimeError: If downloading from both URLs fails.
    """
    for url in [primary_url, fallback_url]:
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as response:
                content = response.read().decode("utf-8", errors="ignore")
                if content and len(content.strip()) > 0:
                    return content
        except Exception as e:
            logger.warning("Failed to download from %s: %s", url, e)

    raise RuntimeError(
        f"Failed to download symbol directory from both {primary_url} and {fallback_url}"
    )


def is_common_stock(symbol: str, security_name: str) -> bool:
    """Determine whether a symbol and security name represent a common stock.

    Filters out ETFs, warrants, preferred shares, rights, units, test tickers,
    closed-end funds, ADRs, notes, and SPACs.

    Args:
        symbol: Ticker symbol.
        security_name: Name of the security.

    Returns:
        bool: True if identified as a common stock, False otherwise.
    """
    if not symbol or not security_name:
        return False

    sym_upper = symbol.strip().upper()
    name_lower = security_name.strip().lower()

    # 1. Test tickers
    test_tickers = {"ZVV", "ZBZX", "ATEST", "BTEST", "CTEST"}
    if sym_upper in test_tickers or sym_upper.startswith(("ATEST", "BTEST", "CTEST")):
        return False

    # 2. Exclude special symbol indicators ($ + = /)
    if any(ch in sym_upper for ch in ["$", "+", "=", "/"]):
        return False

    # Standardize symbol (e.g. BRK.B or BRK B -> BRK-B)
    norm_sym = sym_upper.replace(".", "-").replace(" ", "-")

    # Non-common suffixes after hyphens or dots
    # e.g., -W, -WS (warrants), -U, -UT (units), -P, -PR (preferred), -R, -RT (rights)
    parts = norm_sym.split("-")
    if len(parts) > 1:
        suffix = parts[-1]
        if suffix in {
            "W", "WS", "WT", "WARR", "U", "UT", "UNT", "P", "PR", "R", "RT", "RTS", "PFD", "PREFERRED"
        }:
            return False
        if any(parts[i] in {"P", "PR", "WS", "W", "U", "UT", "RT"} for i in range(1, len(parts))):
            return False

    # 3. Security Name checks
    # Exclude ETFs / Funds / ETNs / ADRs
    if any(k in name_lower for k in [
        " etf", "etf ", "etn", "fund", "closed-end", "american depositary",
        "depositary receipt", "depositary share", "dep share", "dep. share",
        "structured note", "notes", "debenture", " index"
    ]):
        return False

    # Exclude Preferreds
    if any(k in name_lower for k in ["preferred", "pref ", "pref.", "pfd", " % ", "% series", "series %"]):
        return False

    # Exclude Warrants
    if any(k in name_lower for k in ["warrant", "warrants", " wt", " wrt", " cw "]):
        return False

    # Exclude Rights
    if any(k in name_lower for k in ["rights", " rts", " rt "]):
        return False

    # Exclude Units
    if any(k in name_lower for k in [" unit", " units", " ut "]):
        return False

    # Exclude SPACs / Blank Check / Acquisition vehicles
    if any(k in name_lower for k in [
        "blank check", "spac ", "spac-", "(spac)", "special purpose acquisition",
        "acquisition corp", "acquisition corporation", "acquisition inc",
        "capital acquisition", "acquisition co"
    ]):
        return False

    # Exclude Test issues in name
    if "test ticker" in name_lower or "test stock" in name_lower or "test issue" in name_lower:
        return False

    return True


def parse_nasdaqlisted(content: str) -> list[dict[str, Any]]:
    """Parse nasdaqlisted.txt content into ticker metadata dictionaries.

    Header format: Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares

    Args:
        content: Raw pipe-delimited text from nasdaqlisted.txt.

    Returns:
        list[dict[str, Any]]: List of metadata dictionaries for valid common stocks.
    """
    results: list[dict[str, Any]] = []
    lines = content.splitlines()

    for line in lines:
        line = line.strip()
        if not line or line.startswith("File Creation Time") or line.startswith("Symbol|"):
            continue

        parts = line.split("|")
        if len(parts) < 8:
            continue

        raw_symbol, security_name, market_cat, test_issue, financial_status, round_lot, etf, _ = parts[:8]

        if test_issue.strip().upper() == "Y" or etf.strip().upper() == "Y":
            continue

        symbol = raw_symbol.strip().replace(".", "-").replace(" ", "-")

        if not is_common_stock(symbol, security_name):
            continue

        results.append({
            "ticker": symbol,
            "name": security_name.strip(),
            "exchange": "NASDAQ",
            "asset_class": "Common Stock",
            "is_active": True,
        })

    return results


def parse_otherlisted(content: str) -> list[dict[str, Any]]:
    """Parse otherlisted.txt content into ticker metadata dictionaries.

    Header format: ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol

    Args:
        content: Raw pipe-delimited text from otherlisted.txt.

    Returns:
        list[dict[str, Any]]: List of metadata dictionaries for valid common stocks.
    """
    results: list[dict[str, Any]] = []
    lines = content.splitlines()

    for line in lines:
        line = line.strip()
        if not line or line.startswith("File Creation Time") or line.startswith("ACT Symbol|"):
            continue

        parts = line.split("|")
        if len(parts) < 8:
            continue

        act_symbol, security_name, exchange_code, cqs_symbol, etf, round_lot, test_issue, _ = parts[:8]

        if test_issue.strip().upper() == "Y" or etf.strip().upper() == "Y":
            continue

        symbol = act_symbol.strip().replace(".", "-").replace(" ", "-")

        if not is_common_stock(symbol, security_name):
            continue

        exchange_name = EXCHANGE_MAP.get(exchange_code.strip().upper(), exchange_code.strip().upper())

        results.append({
            "ticker": symbol,
            "name": security_name.strip(),
            "exchange": exchange_name,
            "asset_class": "Common Stock",
            "is_active": True,
        })

    return results


def fetch_symbol_directory() -> list[dict[str, Any]]:
    """Download and parse NASDAQ FTP/HTTP symbol lists for common stocks.

    Returns:
        list[dict[str, Any]]: Combined list of common stock ticker metadata dictionaries.
    """
    logger.info("Fetching NASDAQ listed symbol directory...")
    nasdaq_content = download_file_content(NASDAQ_LISTED_HTTP_URL, NASDAQ_LISTED_FTP_URL)
    nasdaq_symbols = parse_nasdaqlisted(nasdaq_content)

    logger.info("Fetching Other listed symbol directory...")
    other_content = download_file_content(OTHER_LISTED_HTTP_URL, OTHER_LISTED_FTP_URL)
    other_symbols = parse_otherlisted(other_content)

    # Deduplicate by ticker
    seen_tickers: set[str] = set()
    combined: list[dict[str, Any]] = []

    for item in nasdaq_symbols + other_symbols:
        ticker = item["ticker"]
        if ticker not in seen_tickers:
            seen_tickers.add(ticker)
            combined.append(item)

    logger.info("Discovered %d common stock symbols.", len(combined))
    return combined


def sync_symbol_metadata(db_manager: DatabaseManager, symbols: Sequence[dict[str, Any]]) -> int:
    """Insert or update symbol metadata records in DuckDB.

    Args:
        db_manager: DatabaseManager connection instance.
        symbols: List of ticker metadata dictionaries.

    Returns:
        int: Number of symbol records written.
    """
    if not symbols:
        return 0

    records = [
        (
            s["ticker"],
            s["name"],
            s.get("exchange", "UNKNOWN"),
            s.get("asset_class", "Common Stock"),
            s.get("is_active", True),
        )
        for s in symbols
    ]

    with db_manager.write_cursor() as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO symbol_metadata
            (ticker, name, exchange, asset_class, is_active, last_updated_date)
            VALUES (?, ?, ?, ?, ?, CURRENT_DATE)
            """,
            records,
        )

    logger.info("Synced %d symbol metadata records to database.", len(records))
    return len(records)
