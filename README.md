# Quantitative Stock Screener & Point-in-Time Backtest Engine

Local quantitative momentum screener (Stage-2 trend template, Volatility Contraction Pattern, and Mansfield Relative Strength) and point-in-time (PIT) backtesting engine supporting **US (NYSE/NASDAQ/AMEX vs. `SPY`)** and **Tel Aviv Stock Exchange (`TA-125` vs. `^TA125.TA`)** universes.

## Stack & Conventions
- **Runtime:** Python 3.10+
- **Data Store:** DuckDB (`market_data.duckdb`) + Parquet daily deltas (`data/daily_deltas/*.parquet`)
- **UI & CLI:** Streamlit (`src/ui/app.py`) and Click CLI (`src/cli.py`)
- **Package Manager:** `pip` with `requirements.txt`

## Setup
1. Install dependencies:
   ```powershell
   python -m pip install -r requirements.txt
   ```
2. (Optional) Configure environment variables by copying `.env.example` to `.env`:
   ```powershell
   Copy-Item .env.example .env
   ```
   - `NTFY_TOPIC`: Topic name on `https://ntfy.sh` for weekly database update notifications (`update_db_weekly.py` / `verify_db_weekly.py`).

## CLI Usage
Run commands from the repository root:

- **Seed historical data (2-year lookback):**
  ```powershell
  python -m src.cli seed --exchange [US|TASE|ALL] --db-path market_data.duckdb
  ```
- **Daily EOD delta update:**
  ```powershell
  python -m src.cli update --exchange [US|TASE|ALL] --db-path market_data.duckdb
  ```
- **Export latest trade-date delta to Parquet:**
  ```powershell
  python -m src.cli export-delta --output-dir data/daily_deltas --db-path market_data.duckdb
  ```
- **Sync local DuckDB from Parquet delta files:**
  ```powershell
  python -m src.cli sync-local --deltas-dir data/daily_deltas --db-path market_data.duckdb
  ```
- **Run Stage-2 momentum screener:**
  ```powershell
  python -m src.cli scan --universe [US|TASE|ALL] --cutoff-date YYYY-MM-DD --max-tightness 3.5
  ```
- **Run point-in-time historical backtest ($T_{-5}$ and $T_{-22}$):**
  ```powershell
  python -m src.cli backtest --universe [US|TASE|ALL]
  ```

## Launch Web UI
```powershell
python -m streamlit run src/ui/app.py --server.port 8501
```
The Streamlit app connects to `market_data.duckdb` in strict `read_only=True` mode (`Views A–E`).

## Testing & Quality Gates
```powershell
python -m ruff check src/ tests/
python -m pip_audit -r requirements.txt
python -m pytest
```
