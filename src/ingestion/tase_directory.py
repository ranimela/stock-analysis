"""TASE (Tel Aviv Stock Exchange) TA-125 Directory and Seeder Module.

Provides the curated directory of TA-125 constituent equities, standard symbol normalization (.TA suffix),
benchmark identification (^TA125.TA), and database synchronization.
"""

from __future__ import annotations

import logging
from typing import Any, Sequence

import pandas as pd

from src.db.db_manager import DatabaseManager
from src.ingestion.symbol_directory import sync_symbol_metadata

logger = logging.getLogger(__name__)

# Constants
TASE_EXCHANGE_CODE = "TASE"
TASE_BENCHMARK = "^TA125.TA"
TASE_BENCHMARK_TICKER = "^TA125.TA"
DEFAULT_ASSET_CLASS = "Common Stock"

# Curated TA-125 Constituents Universe
# Format: (symbol_without_suffix, company_name, sector)
TA125_CONSTITUENTS_CATALOG: list[tuple[str, str, str]] = [
    # Banking & Financial Institutions
    ("LUMI", "Bank Leumi Le-Israel B.M.", "Financials"),
    ("POLI", "Bank Hapoalim B.M.", "Financials"),
    ("DSCT", "Israel Discount Bank Ltd.", "Financials"),
    ("MZTF", "Mizrahi Tefahot Bank Ltd.", "Financials"),
    ("FIBI", "The First International Bank of Israel Ltd.", "Financials"),
    ("FIBIH", "F.I.B.I. Holdings Ltd.", "Financials"),
    ("JBNK", "Bank of Jerusalem Ltd.", "Financials"),

    # Insurance & Financial Services
    ("HARL", "Harel Insurance Investments & Financial Services Ltd.", "Financials"),
    ("PHOE", "The Phoenix Holdings Ltd.", "Financials"),
    ("MGDL", "Migdal Insurance & Financial Holdings Ltd.", "Financials"),
    ("MMHD", "Menora Mivtachim Holdings Ltd.", "Financials"),
    ("CLIS", "Clal Insurance Enterprises Holdings Ltd.", "Financials"),
    ("MTAV", "Meitav Investment House Ltd.", "Financials"),
    ("MORE", "More Investment House Ltd.", "Financials"),
    ("ALTF", "Altshuler Shaham Finance Ltd.", "Financials"),
    ("ISCD", "Isracard Ltd.", "Financials"),
    ("AYLN", "Ayalon Holdings Ltd.", "Financials"),
    ("MIMN", "Direct Finance Ltd.", "Financials"),

    # Technology, Software & Semiconductors
    ("NICE", "NICE Ltd.", "Technology"),
    ("TSEM", "Tower Semiconductor Ltd.", "Technology"),
    ("NVMI", "Nova Ltd.", "Technology"),
    ("CAMT", "Camtek Ltd.", "Technology"),
    ("ESLT", "Elbit Systems Ltd.", "Technology"),
    ("SPNS", "Sapiens International Corporation N.V.", "Technology"),
    ("MTRX", "Matrix IT Ltd.", "Technology"),
    ("ONE", "One Software Technologies Ltd.", "Technology"),
    ("HLAN", "Hilan Ltd.", "Technology"),
    ("MLTM", "Malam Team Ltd.", "Technology"),
    ("MGIC", "Magic Software Enterprises Ltd.", "Technology"),
    ("AUDC", "AudioCodes Ltd.", "Technology"),
    ("ALLT", "Allot Ltd.", "Technology"),
    ("GILT", "Gilat Satellite Networks Ltd.", "Technology"),
    ("RDCM", "Radcom Ltd.", "Technology"),
    ("SILC", "Silicom Ltd.", "Technology"),
    ("FORTY", "Formula Systems (1985) Ltd.", "Technology"),
    ("PERI", "Perion Network Ltd.", "Technology"),
    ("BWAY", "BrainsWay Ltd.", "Technology"),
    ("CGEN", "Compugen Ltd.", "Technology"),

    # Telecommunications
    ("BEZQ", "Bezeq The Israeli Telecommunication Corp. Ltd.", "Telecommunications"),
    ("PTNR", "Partner Communications Company Ltd.", "Telecommunications"),
    ("CEL", "Cellcom Israel Ltd.", "Telecommunications"),

    # Real Estate & Construction
    ("AZRG", "Azrieli Group Ltd.", "Real Estate"),
    ("MELI", "Melisron Ltd.", "Real Estate"),
    ("BIG", "BIG Shopping Centers Ltd.", "Real Estate"),
    ("AMOT", "Amot Investments Ltd.", "Real Estate"),
    ("ALHE", "Alony Hetz Properties & Investments Ltd.", "Real Estate"),
    ("GVYM", "Gav-Yam Lands Corp. Ltd.", "Real Estate"),
    ("DNYA", "Danya Cebus Ltd.", "Real Estate"),
    ("AFRE", "Africa Israel Residences Ltd.", "Real Estate"),
    ("ISCN", "Israel Canada Ltd.", "Real Estate"),
    ("SKBN", "Shikun & Binui Ltd.", "Real Estate"),
    ("DIMRI", "Y.H. Dimri Construction & Development Ltd.", "Real Estate"),
    ("AURA", "Aura Investments Ltd.", "Real Estate"),
    ("ARGO", "Argo Properties N.V.", "Real Estate"),
    ("ALRO", "Alrov Properties and Lodgings Ltd.", "Real Estate"),
    ("MEGA", "Mega Or Holdings Ltd.", "Real Estate"),
    ("ELCRE", "Electra Real Estate Ltd.", "Real Estate"),
    ("ASHG", "Ashtrom Group Ltd.", "Real Estate"),
    ("SPEN", "Shapir Engineering and Industry Ltd.", "Real Estate"),
    ("ACRO", "Kvutzat Acro Ltd.", "Real Estate"),
    ("RIT1", "REIT 1 Ltd.", "Real Estate"),
    ("SLARL", "Sela Capital Real Estate Ltd.", "Real Estate"),
    ("BLSR", "Blue Square Real Estate Ltd.", "Real Estate"),
    ("SUM", "Summit Real Estate Holdings Ltd.", "Real Estate"),
    ("PRSK", "Prashkovsky Investments and Construction Ltd.", "Real Estate"),
    ("LVPR", "Levinstein Properties Ltd.", "Real Estate"),
    ("HAGG", "Hagag Group Real Estate Entrepreneurship Ltd.", "Real Estate"),
    ("RANI", "Rani Zim Shopping Centers Ltd.", "Real Estate"),
    ("ISRA", "Isras Investment Company Ltd.", "Real Estate"),
    ("GCT", "G City Ltd.", "Real Estate"),
    ("ZMH", "Z.M.H. Hammerman Ltd.", "Real Estate"),
    ("ADGR", "Adgar Investment & Development Ltd.", "Real Estate"),
    ("LGIN", "Logisticim Ltd.", "Real Estate"),

    # Energy, Utilities & Renewable Power
    ("DLEKG", "Delek Group Ltd.", "Energy"),
    ("NWMD", "NewMed Energy LP", "Energy"),
    ("ENOG", "Energean PLC", "Energy"),
    ("OPCE", "OPC Energy Ltd.", "Energy"),
    ("ORA", "Ormat Technologies Inc.", "Energy"),
    ("ENRG", "Energix - Renewable Energies Ltd.", "Energy"),
    ("ENLT", "Enlight Renewable Energy Ltd.", "Energy"),
    ("BAZN", "Bazan Group (Oil Refineries) Ltd.", "Energy"),
    ("PAZ", "Paz Oil Company Ltd.", "Energy"),
    ("DRAL", "Dor Alon Energy in Israel (1988) Ltd.", "Energy"),
    ("NAPH", "Naphta Israel Petroleum Corp. Ltd.", "Energy"),
    ("NVPT", "Navitas Petroleum LP", "Energy"),
    ("SBEN", "Shikun & Binui Energy Ltd.", "Energy"),
    ("ISRM", "Isramco Negev 2 LP", "Energy"),
    ("KEN", "Kenon Holdings Ltd.", "Energy"),
    ("ILCO", "Israel Corp Ltd.", "Energy"),

    # Consumer, Retail & Food
    ("STRA", "Strauss Group Ltd.", "Consumer"),
    ("SHUF", "Shufersal Ltd.", "Consumer"),
    ("RMLI", "Rami Levi Chain Stores Hashikma Marketing 2006 Ltd.", "Consumer"),
    ("YHNF", "M. Yochananof and Sons Ltd.", "Consumer"),
    ("FOX", "Fox-Wizel Ltd.", "Consumer"),
    ("CAST", "Castro Model Ltd.", "Consumer"),
    ("GOLF", "Golf & Co Ltd.", "Consumer"),
    ("ECP", "Electra Consumer Products Ltd.", "Consumer"),
    ("ELTR", "Electra Ltd.", "Consumer"),
    ("ELCO", "Elco Ltd.", "Consumer"),
    ("TDRN", "Tadiran Group Ltd.", "Consumer"),
    ("DIPL", "Diplomat Holdings Ltd.", "Consumer"),
    ("MAXO", "Max Stock Ltd.", "Consumer"),
    ("TTAM", "Tiv Taam Holdings 1 Ltd.", "Consumer"),
    ("WLFD", "G. Willi-Food International Ltd.", "Consumer"),
    ("DANE", "Danel (Adir Yeoshua) Ltd.", "Consumer"),
    ("CRSM", "Carasso Motors Ltd.", "Consumer"),

    # Industrials & Basic Materials
    ("ICL", "ICL Group Ltd.", "Industrials"),
    ("PLRM", "Palram Industries (1990) Ltd.", "Industrials"),
    ("PLSN", "Plasson Industries Ltd.", "Industrials"),
    ("INRM", "Inrom Construction Industries Ltd.", "Industrials"),
    ("SCOP", "Scope Metals Group Ltd.", "Industrials"),
    ("SANO", "Sano-Bruno's Enterprises Ltd.", "Industrials"),
    ("MTRN", "Maytronics Ltd.", "Industrials"),
    ("AFCON", "Afcon Holdings Ltd.", "Industrials"),
    ("BRAN", "Baran Group Ltd.", "Industrials"),
    ("KSTN", "Kardan Real Estate / Enterprises Ltd.", "Industrials"),

    # Travel, Leisure & Hospitality
    ("FTAL", "Fattal 1998 Holdings Ltd.", "Consumer"),
    ("ISRO", "Isrotel Ltd.", "Consumer"),
    ("DANH", "Dan Hotels Ltd.", "Consumer"),
    ("ELAL", "El Al Israel Airlines Ltd.", "Consumer"),

    # Healthcare, Biotech & Pharmaceuticals
    ("TEVA", "Teva Pharmaceutical Industries Ltd.", "Healthcare"),
    ("KMDA", "Kamada Ltd.", "Healthcare"),
    ("MDWD", "MediWound Ltd.", "Healthcare"),
    ("ENLV", "Enlivex Therapeutics Ltd.", "Healthcare"),
]


def normalize_tase_ticker(symbol: str) -> str:
    """Normalize a symbol string to the standard TASE Yahoo Finance format (.TA suffix).

    Args:
        symbol: Raw ticker string (e.g. 'TEVA', 'teva.ta', 'LUMI').

    Returns:
        str: Normalized uppercase ticker with .TA suffix (e.g. 'TEVA.TA').
    """
    sym = symbol.strip().upper()
    if sym in {TASE_BENCHMARK, "^TA125"}:
        return TASE_BENCHMARK
    if not sym.endswith(".TA"):
        sym = f"{sym}.TA"
    return sym


def is_tase_ticker(ticker: str) -> bool:
    """Check if a ticker belongs to the TASE universe.

    Args:
        ticker: Ticker symbol string.

    Returns:
        bool: True if ticker is a TASE ticker, False otherwise.
    """
    if not ticker:
        return False
    ticker_clean = ticker.strip().upper()
    return ticker_clean.endswith(".TA") or ticker_clean == TASE_BENCHMARK


def fetch_tase_symbols() -> list[dict[str, Any]]:
    """Fetch the curated list of TA-125 constituent metadata dictionaries.

    Returns:
        list[dict[str, Any]]: List of ticker metadata records formatted for symbol_metadata.
    """
    records: list[dict[str, Any]] = []
    seen: set[str] = set()

    for base_sym, name, sector in TA125_CONSTITUENTS_CATALOG:
        ticker = normalize_tase_ticker(base_sym)
        if ticker in seen:
            continue
        seen.add(ticker)

        records.append({
            "ticker": ticker,
            "name": name,
            "exchange": TASE_EXCHANGE_CODE,
            "asset_class": DEFAULT_ASSET_CLASS,
            "is_active": True,
            "sector": sector,
        })

    logger.info("Loaded %d curated TA-125 constituent records.", len(records))
    return records


def get_tase_symbol_directory() -> list[dict[str, Any]]:
    """Return the curated list of TA-125 constituent metadata dictionaries.

    Alias matching the get_tase_symbol_directory naming convention.

    Returns:
        list[dict[str, Any]]: List of ticker metadata records.
    """
    return fetch_tase_symbols()


def fetch_tase_directory() -> list[dict[str, Any]]:
    """Alias for fetch_tase_symbols() matching the directory module naming convention."""
    return fetch_tase_symbols()


def get_tase_symbols() -> list[str]:
    """Get list of normalized TA-125 ticker strings.

    Returns:
        list[str]: List of tickers (e.g. ['LUMI.TA', 'POLI.TA', ...]).
    """
    return [normalize_tase_ticker(sym) for sym, _, _ in TA125_CONSTITUENTS_CATALOG]


def get_tase_symbols_df() -> pd.DataFrame:
    """Return the TA-125 universe as a pandas DataFrame.

    Returns:
        pd.DataFrame: DataFrame containing columns ['ticker', 'name', 'exchange', 'asset_class', 'is_active', 'sector'].
    """
    data = fetch_tase_symbols()
    return pd.DataFrame(data)


def sync_tase_symbol_metadata(
    db_manager: DatabaseManager,
    symbols: Sequence[dict[str, Any]] | None = None,
) -> int:
    """Insert or update TASE symbol metadata in DuckDB.

    Args:
        db_manager: DatabaseManager instance.
        symbols: Optional custom list of symbol metadata dictionaries. If None, uses fetch_tase_symbols().

    Returns:
        int: Number of symbol records synchronized.
    """
    if symbols is None:
        symbols = fetch_tase_symbols()

    return sync_symbol_metadata(db_manager, symbols)
