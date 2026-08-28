# Explorer M3_1 Handoff Report: Streamlit Views A, B, C, E Architecture

**Agent**: Explorer M3_1 (UI Views Architecture Explorer)  
**Date**: 2026-08-27  
**Artifact Path**: `c:\Users\rmelamed\Projects\stock-analysis\.agents\explorer_m3_1\handoff.md`  

---

## 1. Observation

1. **`render_live_recommendations()` (View A)**:
   - Queries `run_screener(db_manager, cutoff_date=latest_date, universe="US")`.
   - Divides US results into Non-Pharma Top 10 and Medical/Pharma Top 10.
   - Needs to execute `run_screener(db_manager, cutoff_date=latest_date, universe="TASE")`, extract `df_tase.head(5)`, and render a dedicated Top 5 TASE section with `.title-tase` banner and dedicated CSV download button.

2. **`render_backtest_view()` (Views B, C, and E)**:
   - Executes `run_point_in_time_backtest(db_manager, cutoff_days_ago=..., custom_cutoff_date=..., universe="US")`.
   - Displays 2 sets of benchmark comparison cards (Non-Pharma and Medical/Pharma vs SPY) and 2 position tables.
   - Needs to execute `run_point_in_time_backtest(..., universe="TASE")` and display:
     - 3 dedicated high-contrast TASE benchmark cards (`.portfolio-card-tase`):
       1. `^TA125.TA` Index ($10k Buy & Hold).
       2. 5x $2,000 Top 5 TASE stock picks ($10k total allocation).
       3. Net TASE Alpha vs `^TA125.TA`.
     - Top 5 TASE Historical Position Performance table with `build_html_table(..., is_backtest=True, is_tase=True)`.

3. **View E (Custom Date Backtest)**:
   - Reuses `render_backtest_view(..., custom_cutoff_date=chosen_date_str)`.
   - Adding TASE support to `render_backtest_view()` automatically enables full dedicated TASE section in View E without code duplication.

---

## 2. Logic Chain

1. Reusing `render_backtest_view()` for Views B ($T_{-5}$), C ($T_{-22}$), and E ($T_{\text{custom}}$) ensures consistent calculation of $10,000 model portfolios across all backtesting tabs.
2. TASE positions in backtests are allocated 20% each ($2,000) across the 5 top picks, accurately matching the 5-stock model portfolio design.

---

## 3. Caveats

- Empty database or missing TASE bars should display graceful info notices rather than raising unhandled exceptions.

---

## 4. Conclusion

The architecture for Views A, B, C, and E is mapped and ready for Worker M3 implementation.
