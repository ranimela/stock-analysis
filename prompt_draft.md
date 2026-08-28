# Teamwork Project Prompt — Draft

> Status: Launched
> Goal: Craft prompt → get user approval → delegate to teamwork_preview
> Requested team: Full Team

Integrate Tel Aviv Stock Exchange (TA-125 index universe) equities into the quantitative stock analysis engine and Streamlit web application, displaying the Top 5 TASE recommendations in a dedicated section separate from US stocks.

Working directory: c:/Users/rmelamed/Projects/stock-analysis
Integrity mode: development

## Requirements

### R1. TASE Universe & Benchmark Ingestion
- Seed and maintain TA-125 constituent tickers (`.TA` suffix via Yahoo Finance, benchmarked against `^TA125.TA`).
- Store TASE symbol metadata in DuckDB with `exchange = 'TASE'` and currency/pricing attributes.

### R2. Quantitative Screener Engine Adaptation for TASE
- Execute VCP, 52W High/Low distance, and ADV20 liquidity screening for TASE equities.
- Separate TASE stock recommendations from US equities into a dedicated Top 5 TASE recommendation list.

### R3. Streamlit UI Dedicated TASE Section
- Display the Top 5 TASE recommendations as a dedicated visual section/card below the US Top 10 across Views A, B, C, D, and E.

## Acceptance Criteria

### TASE Data & UI Integrity
- [ ] TASE tickers (`.TA`) are ingested into DuckDB without schema conflicts or rate-limiting errors.
- [ ] Top 5 TASE recommendations render in a dedicated, high-contrast UI card across Views A, B, C, D, and E.
- [ ] Pytest suite achieves 100% pass rate across all engine and UI unit tests.
