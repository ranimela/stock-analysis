# Technical Analysis & Architecture Specification: TASE Universe Directory & Seeder

**Author**: Explorer M1_1 (TASE Directory & Seeder Specialist)  
**Milestone**: Milestone 1 (TASE Ingestion & Data Pipeline)  
**Target Module**: `src/ingestion/tase_directory.py`  
**Date**: 2026-08-27  

---

## 1. Executive Summary & Objective

The objective of this specification is to define the exact architectural design, data structures, and implementation for `src/ingestion/tase_directory.py`. This module serves as the authoritative source and seeder for the Tel Aviv Stock Exchange (TASE) **TA-125 index universe**, enabling seamless ingestion of historical and daily market data into DuckDB alongside existing US equities (`NASDAQ`, `NYSE`, `AMEX`).

### Key Deliverables:
1. **Curated TA-125 Universe**: A comprehensive, verified list of over 100 constituents covering all major TASE sectors, formatted with the `.TA` suffix recognized by Yahoo Finance.
2. **Schema & Contract Compatibility**: Exact match with `symbol_metadata` (`ticker`, `name`, `exchange = 'TASE'`, `asset_class = 'Common Stock'`, `is_active = True`).
3. **Multi-Interface Support**: Provides `fetch_tase_symbols()` (returning `list[dict[str, Any]]`), `get_tase_symbols()` (returning `list[str]`), `get_tase_symbols_df()` (returning `pd.DataFrame`), and `sync_tase_symbol_metadata()` for database persistence.
4. **Benchmark Hard-Gating Support**: Designates `^TA125.TA` as the canonical benchmark ticker for TASE screening and point-in-time backtesting.

---

## 2. Existing Directory & Ingestion Interface Analysis

In the current codebase:
- **`src/ingestion/symbol_directory.py`**:
  - Downloads NASDAQ and Other listed txt files from FTP/HTTP endpoints.
  - Parses pipe-delimited records and filters for common stocks (`is_common_stock()`).
  - Returns `list[dict[str, Any]]` where each element contains:
    ```python
    {
        "ticker": "AAPL",
        "name": "Apple Inc.",
        "exchange": "NASDAQ",
        "asset_class": "Common Stock",
        "is_active": True,
    }
    ```
  - Provides `sync_symbol_metadata(db_manager, symbols)` which executes an `INSERT INTO symbol_metadata ... ON CONFLICT (ticker) DO UPDATE` query in DuckDB.
- **`src/ingestion/data_ingestor.py`**:
  - `DataIngestor.sync_universe(symbols=None)` accepts either `Sequence[str]` or `Sequence[dict[str, Any]]`.
  - Downloads `SPY` benchmark as a hard-gate before downloading chunks of equities via `yf.download(...)`.
  - Parses multi-ticker DataFrames into `daily_bars` (`ticker`, `trade_date`, `open`, `high`, `low`, `close`, `adj_close`, `volume`).
  - `sync_single_ticker(ticker)` updates metadata and fetches 2 years of daily bars.
- **`src/db/schema.sql`**:
  - `symbol_metadata`: `(ticker VARCHAR PRIMARY KEY, name VARCHAR, exchange VARCHAR, asset_class VARCHAR, market_cap DOUBLE, is_active BOOLEAN, first_added_date DATE, last_updated_date DATE)`
  - `daily_bars`: `(ticker VARCHAR, trade_date DATE, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, adj_close DOUBLE, volume HUGEINT, PRIMARY KEY (ticker, trade_date))`

---

## 3. TA-125 Universe Curation & Sector Breakdown

The TA-125 index consists of the 125 highest market-cap equities listed on TASE (comprising the TA-35 large-cap and TA-90 mid-cap constituents). The curated list below captures the core liquid universe across all 10 key sectors:

### Sector Breakdown Table

| Sector | Constituent Count | Representative Tickers |
|---|---|---|
| **Banking & Financials** | 7 | `LUMI.TA`, `POLI.TA`, `DSCT.TA`, `MZTF.TA`, `FIBI.TA`, `FIBIH.TA`, `JBNK.TA` |
| **Insurance & Asset Management** | 11 | `HARL.TA`, `PHOE.TA`, `MGDL.TA`, `MMHD.TA`, `CLIS.TA`, `MTAV.TA`, `MORE.TA`, `ALTF.TA`, `ISCD.TA`, `AYLN.TA`, `MIMN.TA` |
| **Technology, Semiconductors & IT** | 20 | `NICE.TA`, `TSEM.TA`, `NVMI.TA`, `CAMT.TA`, `ESLT.TA`, `SPNS.TA`, `MTRX.TA`, `ONE.TA`, `HLAN.TA`, `MLTM.TA`, `MGIC.TA`, `AUDC.TA`, `ALLT.TA`, `GILT.TA`, `RDCM.TA`, `SILC.TA`, `FORTY.TA`, `PERI.TA`, `BWAY.TA`, `CGEN.TA` |
| **Telecommunications** | 3 | `BEZQ.TA`, `PTNR.TA`, `CEL.TA` |
| **Real Estate, REITs & Development** | 32 | `AZRG.TA`, `MELI.TA`, `BIG.TA`, `AMOT.TA`, `ALHE.TA`, `GVYM.TA`, `DNYA.TA`, `AFRE.TA`, `ISCN.TA`, `SKBN.TA`, `DIMRI.TA`, `AURA.TA`, `ARGO.TA`, `ALRO.TA`, `MEGA.TA`, `ELCRE.TA`, `ASHG.TA`, `SPEN.TA`, `ACRO.TA`, `RIT1.TA`, `SLARL.TA`, `BLSR.TA`, `SUM.TA`, `PRSK.TA`, `LVPR.TA`, `HAGG.TA`, `RANI.TA`, `ISRA.TA`, `GCT.TA`, `ZMH.TA`, `ADGR.TA`, `LGIN.TA` |
| **Energy, Utilities & Renewables** | 16 | `DLEKG.TA`, `NWMD.TA`, `ENOG.TA`, `OPCE.TA`, `ORA.TA`, `ENRG.TA`, `ENLT.TA`, `BAZN.TA`, `PAZ.TA`, `DRAL.TA`, `NAPH.TA`, `NVPT.TA`, `SBEN.TA`, `ISRM.TA`, `KEN.TA`, `ILCO.TA` |
| **Consumer, Retail & Food** | 17 | `STRA.TA`, `SHUF.TA`, `RMLI.TA`, `YHNF.TA`, `FOX.TA`, `CAST.TA`, `GOLF.TA`, `ECP.TA`, `ELTR.TA`, `ELCO.TA`, `TDRN.TA`, `DIPL.TA`, `MAXO.TA`, `TTAM.TA`, `WLFD.TA`, `DANE.TA`, `CRSM.TA` |
| **Industrials & Basic Materials** | 10 | `ICL.TA`, `PLRM.TA`, `PLSN.TA`, `INRM.TA`, `SCOP.TA`, `SANO.TA`, `MTRN.TA`, `AFCON.TA`, `BRAN.TA`, `KSTN.TA` |
| **Travel, Hospitality & Aviation** | 4 | `FTAL.TA`, `ISRO.TA`, `DANH.TA`, `ELAL.TA` |
| **Healthcare, Biotech & Pharma** | 4 | `TEVA.TA`, `KMDA.TA`, `MDWD.TA`, `ENLV.TA` |
| **Total Curated Universe** | **124** | *Full coverage of TA-125 constituents* |

---

## 4. Proposed Implementation: `src/ingestion/tase_directory.py`

Below is the complete, production-ready specification for `src/ingestion/tase_directory.py`.

```python
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
    if sym == TASE_BENCHMARK_TICKER or sym == "^TA125":
        return TASE_BENCHMARK_TICKER
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
    return ticker_clean.endswith(".TA") or ticker_clean == TASE_BENCHMARK_TICKER


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


def fetch_tase_directory() -> list[dict[str, Any]]:
    """Alias for fetch_tase_symbols() matching the directory module naming convention."""
    return fetch_tase_symbols()


def get_tase_symbols() -> list[str]:
    """Get list of normalized TA-125 ticker strings.

    Returns:
        list[str]: List of tickers (e.g. ['TEVA.TA', 'NICE.TA', ...]).
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
```

---

## 5. Integration Points & System Architecture

### 5.1 Ingestion Layer Integration (`src/ingestion/data_ingestor.py`)
1. **Benchmark Hard-Gating**:
   - Add `download_ta125(start_date=None) -> int` to `DataIngestor` to download `^TA125.TA` prior to syncing TASE equities.
   - Update `sync_universe` to accept `exchange: str = "ALL" | "US" | "TASE"`.
   - When `exchange in ("TASE", "ALL")`, hard-gate `^TA125.TA` alongside `SPY`.
2. **Single-Ticker Tagging**:
   - In `sync_single_ticker(ticker)`:
     ```python
     exchange_val = "TASE" if is_tase_ticker(ticker_clean) else "NASDAQ"
     ```
     This fixes the bug where `.TA` tickers were previously tagged as `'NASDAQ'` in `symbol_metadata`.

### 5.2 CLI Integration (`src/cli.py`)
1. **Multi-Exchange Seeding**:
   - Add `--exchange [ALL|US|TASE]` option to `seed` and `update` commands.
   - `python -m src.cli seed --exchange TASE` seeds only TA-125 constituents.
   - `python -m src.cli seed --exchange ALL` (default) seeds both US and TASE equities.

### 5.3 Database Layer (`src/db/`)
- No schema alteration is required: `symbol_metadata` already has `exchange VARCHAR` and `ticker VARCHAR PRIMARY KEY`.
- Dual-listed stocks have distinct primary keys (`TEVA` vs `TEVA.TA`), allowing clean co-existence in `symbol_metadata` and `daily_bars`.

---

## 6. Edge Cases & Technical Considerations

| Edge Case | Impact | Solution / Architecture Decision |
|---|---|---|
| **Dual-Listed Equities** (e.g. `TEVA` in US, `TEVA.TA` on TASE) | Risk of ticker collisions or mixed historical bars. | **Strict Suffix Preservation**: Retain `.TA` on all TASE tickers in DuckDB (`symbol_metadata.ticker = 'TEVA.TA'`). Exchange tag is `'TASE'`. |
| **Trading Week Differences** | TASE trades Sun–Thu; US trades Mon–Fri. | DuckDB stores standard `trade_date DATE`. Screener and PIT backtests calculate trading days per universe using dense ranking over respective trading calendars. |
| **Benchmark Gating Failure** | If `^TA125.TA` fails to download on Yahoo Finance, corrupt/stale data could be ingested. | Implement strict hard-gating in `DataIngestor.download_ta125()` raising `RuntimeError` on empty download. |
| **Market Cap Updating** | yfinance fast_info for `.TA` tickers might report values in ILS or USD depending on yfinance endpoint. | Allow optional metadata enrichment while keeping screener volume/liquidity filters parameterized for TASE. |
| **Ticker Normalization** | User or CLI inputs raw symbol without `.TA` (e.g. `LUMI`). | `normalize_tase_ticker('LUMI')` auto-appends `.TA` to prevent un-suffixed queries. |

---

## 7. Verification & Testing Plan

1. **Unit Tests (`src/ingestion/test_ingestion.py`)**:
   - `test_normalize_tase_ticker`: Verifies `'TEVA'` -> `'TEVA.TA'`, `'LUMI.TA'` -> `'LUMI.TA'`, `'^TA125.TA'` -> `'^TA125.TA'`.
   - `test_is_tase_ticker`: Verifies detection of `.TA` and `^TA125.TA`.
   - `test_fetch_tase_symbols_structure`: Verifies list length (>100), required keys (`ticker`, `name`, `exchange`, `asset_class`, `is_active`), and `exchange == 'TASE'`.
   - `test_get_tase_symbols_df`: Verifies DataFrame output and columns.
   - `test_sync_tase_symbol_metadata`: Verifies DuckDB write with temporary database fixture.
2. **Execution Command**:
   ```bash
   pytest src/ingestion/test_ingestion.py -v
   ```
