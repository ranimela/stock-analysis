# Milestone 2: Backtest Engine Specialist Analysis (`src/engine/backtest_engine.py` & `src/cli.py`)

## Executive Summary
This document provides the exhaustive technical analysis and architectural formulation for adapting `src/engine/backtest_engine.py` and `src/cli.py` to support Tel Aviv Stock Exchange (TA-125) point-in-time (PIT) backtesting, exchange-specific trading calendar handling, `^TA125.TA` benchmark performance and alpha calculations, Top 5 TASE portfolio allocations, and multi-exchange CLI scan orchestration for Milestone 2.

---

## 1. Current State Assessment of `src/engine/backtest_engine.py`

### 1.1 Architecture & Mechanism
Currently, `run_point_in_time_backtest()` (lines 21–248 of `src/engine/backtest_engine.py`) performs the following operations:
1. **Trade Dates Resolution (Lines 47–79)**:
   - Queries distinct trade dates across the entire `daily_bars` table (`SELECT DISTINCT trade_date FROM daily_bars ORDER BY trade_date DESC;`).
   - Sets `eval_date = trade_dates[0]` (T0) and `cutoff_date = trade_dates[cutoff_days_ago]` (or snaps `custom_cutoff_date` to `trade_date <= custom_str`).
2. **Screener Execution (Lines 87–93)**:
   - Calls `run_screener(db_manager, cutoff_date=cutoff_date, ...)` without any universe/exchange parameter.
3. **Hardcoded Benchmark Forward Performance (Lines 126–142)**:
   - Queries `SPY` daily bars from `cutoff_date` to `eval_date` (`WHERE ticker = 'SPY'`).
   - Computes `spy_return = (spy_exit - spy_entry) / spy_entry`.
4. **Position Forward Return & Drawdown (Lines 145–201)**:
   - Queries each recommended stock's daily bars from `cutoff_date` to `eval_date`.
   - Computes stock return `ret = (exit_price - entry_price) / entry_price`.
   - Calculates rolling peak-to-trough maximum drawdown `mdd`.
   - Computes alpha strictly against SPY: `alpha = ret - spy_return`.
5. **Basket Aggregation & Metrics (Lines 205–215)**:
   - Aggregates `mean_basket_return`, `basket_alpha`, `win_rate`, `avg_max_drawdown`.
6. **DB Persistence (Lines 217–236)**:
   - Writes run record to `point_in_time_runs` with `run_id = f"pit_T-{cutoff_days_ago}_{cutoff_date.replace('-', '')}"`.

### 1.2 Identified Limitations & Friction Points for TASE Integration
1. **Calendar Asymmetry (Sundays vs. Fridays)**:
   - TASE trades **Sunday through Thursday**; US exchanges trade **Monday through Friday**.
   - Querying `SELECT DISTINCT trade_date FROM daily_bars` without exchange filtering on a combined database produces a 6-day trading week (Sun–Fri). Stepping back 5 dates in a combined dataset skips only ~3.5 trading days per individual market rather than 1 full trading week.
   - `eval_date` (index 0) could be Sunday (TASE) or Friday (US), causing missing bar errors for the opposite exchange.
2. **Hardcoded SPY Benchmark**:
   - `WHERE ticker = 'SPY'` ignores `^TA125.TA`, making TASE alpha computation incorrect.
3. **Portfolio Size & Allocation**:
   - TASE universe requires a dedicated **Top 5** portfolio allocation ($2,000 / 20% each in a standard $10,000 model) rather than the default US Top 10 ($1,000 / 10% each).
4. **Missing CLI Scan Exchange Parameter**:
   - `src/cli.py` `scan` command only accepts `--db-path` and does not accept `--exchange` / `-e` (unlike `seed` and `update` commands which support `US`, `TASE`, `ALL`).

---

## 2. Proposed Architecture & Parameterization for `src/engine/backtest_engine.py`

### 2.1 Function Signature
```python
def run_point_in_time_backtest(
    db_manager: DatabaseManager,
    cutoff_days_ago: int = 5,
    custom_cutoff_date: str | None = None,
    max_tightness: float = 3.5,
    pct_off_low: float = 30.0,
    pct_within_high: float = 25.0,
    universe: str = "US",
    benchmark_ticker: str | None = None,
    top_n: int | None = None,
) -> dict[str, float | str | int | pd.DataFrame]:
```

### 2.2 Exchange-Aware Trading Calendar Resolution
To guarantee zero calendar distortion and preserve market holidays accurately:
```python
univ = universe.strip().upper()
if benchmark_ticker is None:
    bench_ticker = "^TA125.TA" if univ == "TASE" else "SPY"
else:
    bench_ticker = benchmark_ticker.strip().upper()

# Query trade dates directly for the target benchmark ticker
dates_query = """
    SELECT DISTINCT trade_date
    FROM daily_bars
    WHERE ticker = ?
    ORDER BY trade_date DESC;
"""
rows = db_manager.execute_read(dates_query, [bench_ticker])

# Fallback for synthetic / mock test databases lacking benchmark tickers
if not rows:
    fallback_query = "SELECT DISTINCT trade_date FROM daily_bars ORDER BY trade_date DESC;"
    rows = db_manager.execute_read(fallback_query)

trade_dates = [str(r[0]) for r in rows]
if not trade_dates:
    raise ValueError(f"Database is empty or contains no historical daily bars for {univ} (benchmark: {bench_ticker}).")

eval_date = trade_dates[0]  # T0 for specific exchange
```

### 2.3 Forward Benchmark Performance Calculation
```python
bench_rows = db_manager.execute_read(
    """
    SELECT trade_date, close
    FROM daily_bars
    WHERE ticker = ? AND trade_date >= CAST(? AS DATE) AND trade_date <= CAST(? AS DATE)
    ORDER BY trade_date ASC;
    """,
    [bench_ticker, cutoff_date, eval_date],
)

if bench_rows and len(bench_rows) >= 1:
    bench_entry = float(bench_rows[0][1])
    bench_exit = float(bench_rows[-1][1])
    bench_return = (bench_exit - bench_entry) / bench_entry if bench_entry > 0 else 0.0
else:
    bench_return = 0.0
```

### 2.4 Top Tickers & Portfolio Allocation Formulation
```python
# Screener execution with universe routing
screener_df = run_screener(
    db_manager,
    cutoff_date=cutoff_date,
    max_tightness=max_tightness,
    pct_off_low=pct_off_low,
    pct_within_high=pct_within_high,
    universe=univ,
    benchmark_ticker=bench_ticker,
)

effective_top_n = top_n if top_n is not None else (5 if univ == "TASE" else 10)
if not screener_df.empty:
    top_df = screener_df.head(effective_top_n)
    top_tickers = top_df["ticker"].tolist()
else:
    top_tickers = []

num_positions = len(top_tickers)
alloc_pct = (100.0 / num_positions) if num_positions > 0 else 0.0
alloc_usd = (10000.0 / num_positions) if num_positions > 0 else 0.0
```

### 2.5 Positions DataFrame Schema
For each position in `top_tickers`, compute:
- `ticker`: Symbol (`LUMI.TA`, `NVDA`, etc.)
- `name`: Full company name
- `exchange`: `TASE` or `NASDAQ`/`NYSE`
- `market_cap`: Market capitalization
- `entry_price`: Entry price on `cutoff_date`
- `exit_price`: Exit price on `eval_date`
- `return_pct`: Stock forward return `((exit - entry) / entry) * 100.0`
- `benchmark_ticker`: `^TA125.TA` or `SPY`
- `benchmark_return_pct`: Benchmark return `* 100.0`
- `spy_return_pct`: Backward-compatible alias for benchmark return `* 100.0`
- `ta125_return_pct`: Explicit TASE benchmark return `* 100.0` (or `None` for US)
- `alpha_pct`: `return_pct - benchmark_return_pct`
- `max_drawdown_pct`: Intraday peak-to-trough drawdown `* 100.0`
- `allocation_pct`: Portfolio weight percentage (e.g. 20.0% for Top 5)
- `allocation_usd`: Position dollar allocation in $10,000 portfolio (e.g. $2,000 for Top 5)
- `is_win`: Boolean `return_pct > 0.0`

### 2.6 Return Dictionary Contract
```python
return {
    "universe": univ,
    "benchmark_ticker": bench_ticker,
    "cutoff_date": cutoff_date,
    "evaluation_date": eval_date,
    "cutoff_days_ago": cutoff_days_ago,
    "mean_basket_return": mean_basket_return,
    "benchmark_return": bench_return,
    "spy_return": bench_return,  # Backward compatibility for existing UI/tests
    "ta125_return": bench_return if univ == "TASE" else 0.0,
    "basket_alpha": basket_alpha,
    "win_rate": win_rate,
    "avg_max_drawdown": avg_mdd,
    "positions_df": positions_df,
}
```

### 2.7 Database Persistence Integrity
To avoid primary key conflicts between US and TASE runs for the same cutoff date:
```python
run_id = f"pit_T-{cutoff_days_ago}_{univ}_{cutoff_date.replace('-', '')}"
scan_type = f"T-{cutoff_days_ago}_{univ}"
```

---

## 3. Analysis & Design for `src/cli.py` `scan` Command

### 3.1 Option Parameterization
Add `--exchange` / `-e` parameter to `@main.command() def scan`:
```python
@main.command()
@click.option(
    "--db-path",
    default="market_data.duckdb",
    help="Path to DuckDB database file.",
    show_default=True,
)
@click.option(
    "--exchange",
    "-e",
    type=click.Choice(["US", "TASE", "ALL"], case_sensitive=False),
    default="ALL",
    help="Target exchange universe to scan (US, TASE, or ALL).",
    show_default=True,
)
def scan(db_path: str, exchange: str = "ALL") -> None:
    ...
```

### 3.2 Output Formatting Structure
When `exchange == "ALL"`:
1. **US Market Sections**:
   - `1A. US LIVE TOP-10 RECOMMENDATIONS (T0 Cutoff: ...)`
   - `2A. US 1-WEEK POINT-IN-TIME BACKTEST (T-5, SPY Benchmark)`
   - `3A. US 1-MONTH POINT-IN-TIME BACKTEST (T-22, SPY Benchmark)`
2. **TASE Market Sections**:
   - `1B. TASE LIVE TOP-5 RECOMMENDATIONS (T0 Cutoff: ...)`
   - `2B. TASE 1-WEEK POINT-IN-TIME BACKTEST (T-5, TA-125 Benchmark)`
   - `3B. TASE 1-MONTH POINT-IN-TIME BACKTEST (T-22, TA-125 Benchmark)`

When `exchange == "US"` or `exchange == "TASE"`, only the requested market sections are executed and rendered.

---

## 4. Verification and Risk Analysis

### 4.1 Backward Compatibility
- Default parameter values (`universe="US"`, `top_n=None`) ensure existing test suites (`src/engine/test_engine.py`, `src/test_cli_ui.py`, `tests/`) execute with zero modifications or regressions.
- Retaining `spy_return` and `spy_return_pct` aliases in dictionary and DataFrame outputs prevents breaking changes in UI rendering modules prior to Milestone 3.

### 4.2 Edge Cases Addressed
1. **Calendar Offsets**: US and TASE trading date separation avoids weekend/holiday contamination.
2. **Empty Screener Candidates**: Returns empty DataFrame with full column structure and 0.0 metrics.
3. **Database Read-Only Safeguard**: Prevents write attempts on read-only DuckDB connections.
4. **Primary Key Collision**: Segmented `run_id` (`pit_T-5_TASE_20260820` vs `pit_T-5_US_20260820`).
