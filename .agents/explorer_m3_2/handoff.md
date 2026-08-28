# Explorer M3_2 Handoff Report: Streamlit View D Diagnostics & TASE Parameters

**Agent**: Explorer M3_2 (Diagnostics & Multi-Universe Explorer)  
**Date**: 2026-08-27  
**Artifact Path**: `c:\Users\rmelamed\Projects\stock-analysis\.agents\explorer_m3_2\handoff.md`  

---

## 1. Observation

1. **View D Custom Analysis Tab**:
   - Accepts arbitrary user-supplied tickers in sidebar `manual_input` (e.g. `DSCT.TA, TLV.TA, AAPL`).
   - Uses `run_screener(..., manual_tickers=found_tickers)`.
   - In `screener_queries.py`, `manual_tickers` containing `.TA` symbols auto-routes to `^TA125.TA` benchmark and uses TASE price floor (100.0 Agorot).
   - View D's 8-Point Stage-2 Checklist currently hardcodes US thresholds (`>= $10.00` price, `adv >= $20M`, `Mansfield RS vs SPY`, `Top 10 Qualification`).
   - For TASE stocks (`.TA` suffix):
     - Checklist item 1: Price Floor (`>= 100.0` Agorot).
     - Checklist item 2: ADV20 Liquidity (`>= 20,000,000` Agorot).
     - Checklist item 8: Mansfield RS vs `^TA125.TA`.
     - Qualification: Checks against Top 5 TASE recommendations (`run_screener(..., universe="TASE")`).

2. **Downloader for Missing TASE Tickers**:
   - View D includes a 1-click download button for missing tickers.
   - `DataIngestor.sync_single_ticker(ticker)` automatically identifies `.TA` tickers and tags them as `exchange = 'TASE'`.

---

## 2. Logic Chain

1. Dynamic universe detection (`is_tase_ticker(tick)`) in View D ensures each ticker is diagnosed against its appropriate exchange rules and benchmark index.

---

## 3. Caveats

- Mixed lists (e.g. `AAPL, DSCT.TA`) must evaluate each ticker under its respective benchmark and thresholds.

---

## 4. Conclusion

View D diagnostic logic is fully defined and ready for implementation.
