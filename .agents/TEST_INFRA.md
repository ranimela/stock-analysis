# E2E Test Infra: Tel Aviv Stock Exchange (TA-125) Integration

## Test Philosophy
- Opaque-box, requirement-driven testing.
- Methodology: Category-Partition + Boundary Value Analysis + Pairwise Combinatorial Testing + Real-World Workload Testing.
- Hard requirement: 100% pass rate on all unit, integration, and UI tests without schema conflicts or host contamination.

## Feature Inventory
| # | Feature | Source (requirement) | Tier 1 (Feature) | Tier 2 (Boundary) | Tier 3 (Cross-Feature) | Tier 4 (Workload) |
|---|---------|---------------------|:----------------:|:-----------------:|:----------------------:|:-----------------:|
| 1 | TA-125 Universe Seeding | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ | ✓ |
| 2 | Benchmark Ingestion & Gating | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ | ✓ |
| 3 | Single-Ticker TASE Tagging | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ | ✓ |
| 4 | CLI Multi-Exchange Ingestion | ORIGINAL_REQUEST §R1 | 5 | 5 | ✓ | ✓ |
| 5 | TASE Quantitative Screener | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ | ✓ |
| 6 | TASE Backtest Engine | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ | ✓ |
| 7 | Dedicated Top 5 TASE Separation | ORIGINAL_REQUEST §R2 | 5 | 5 | ✓ | ✓ |
| 8 | High-Contrast TASE CSS Styling | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ | ✓ |
| 9 | Streamlit View A (Live Top 5) | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ | ✓ |
| 10 | Streamlit View B (1-Wk Backtest) | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ | ✓ |
| 11 | Streamlit View C (1-Mo Backtest) | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ | ✓ |
| 12 | Streamlit View D (Diagnostics) | ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ | ✓ |
| 13 | Streamlit View E (Custom Backtest)| ORIGINAL_REQUEST §R3 | 5 | 5 | ✓ | ✓ |

## Test Architecture
- Framework: `pytest`
- Execution: `python -m pytest -v`
- Mocking & Isolation:
  - Synthetic DuckDB in-memory or temporary SQLite/DuckDB fixtures for isolation.
  - Mocked yfinance returns to prevent rate-limiting during test runs.
  - Streamlit headless render mocks via `monkeypatch` to verify DOM output strings and CSS classes.

## Real-World Application Scenarios (Tier 4)
| # | Scenario | Features Exercised | Complexity |
|---|----------|--------------------|------------|
| 1 | Full TASE Seed, Sync, and Benchmark Gating Pipeline | F1, F2, F3, F4 | High |
| 2 | End-to-End Screener Execution on TASE Universe producing Top 5 | F5, F6, F7 | High |
| 3 | Streamlit Full Multi-View Render with Live US + TASE Sections | F8, F9, F10, F11, F12, F13 | High |
| 4 | End-to-End Dual-Market Backtest Alignment (SPY vs TA125) | F2, F6, F10, F11, F13 | High |
| 5 | CLI Single-Ticker Sync for .TA Stock and Diagnostic Lab Inspection | F3, F4, F12 | Medium |

## Coverage Thresholds
- Tier 1: >=5 per feature (65+ tests)
- Tier 2: >=5 per feature boundary (65+ tests)
- Tier 3: Pairwise combinations of exchange, universe, benchmark, and views
- Tier 4: >=5 realistic workload scenarios
