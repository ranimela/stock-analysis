-- DuckDB Schema Definition for Stock Scanner Engine

CREATE TABLE IF NOT EXISTS symbol_metadata (
    ticker VARCHAR PRIMARY KEY,
    name VARCHAR,
    exchange VARCHAR,
    asset_class VARCHAR,
    market_cap DOUBLE,
    is_active BOOLEAN,
    first_added_date DATE,
    last_updated_date DATE
);

CREATE TABLE IF NOT EXISTS daily_bars (
    ticker VARCHAR,
    trade_date DATE,
    open DOUBLE,
    high DOUBLE,
    low DOUBLE,
    close DOUBLE,
    adj_close DOUBLE,
    volume HUGEINT,
    PRIMARY KEY (ticker, trade_date)
);

CREATE TABLE IF NOT EXISTS point_in_time_runs (
    run_id VARCHAR PRIMARY KEY,
    run_date TIMESTAMP,
    cutoff_date DATE,
    scan_type VARCHAR,
    top_tickers VARCHAR
);
