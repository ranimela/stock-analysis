# Milestone 3 Adversarial Challenge Report

**Verdict**: **REQUEST_CHANGES**

---

## 1. Observation

Adversarial stress-testing was conducted on `src/ui/app.py` and `src/test_cli_ui.py` using a dedicated 13-case test harness (`tests/test_adversarial_m3_ui.py`). The following empirical defects and vulnerabilities were reproduced and verified:

### Defect 1 (CRITICAL): `UnboundLocalError` crash in `render_backtest_view` on empty US recommendations
- **File**: `src/ui/app.py`
- **Lines**: 566–568, 859, 861
- **Verbatim Error**:
  ```
  UnboundLocalError: cannot access local variable 'cutoff_date' where it is not associated with a value
  ```
- **Observed Behavior**:
  In `render_backtest_view`, variables `cutoff_date` and `eval_date` are only assigned inside:
  ```python
  566: if results and isinstance(results.get("positions_df"), pd.DataFrame) and not results["positions_df"].empty:
  567:     cutoff_date = str(results["cutoff_date"])
  568:     eval_date = str(results["evaluation_date"])
  ```
  However, on lines 859 and 861 (inside the `st.expander` output guide), the code evaluates:
  ```python
  859: ... on **{cutoff_date if results and 'cutoff_date' in results else 'N/A'}** ...
  861: ... today ({eval_date if results and 'evaluation_date' in results else 'N/A'}) ...
  ```
  When `results` is non-empty (e.g. contains `cutoff_date` and `evaluation_date`) but `positions_df` is empty, `results and 'cutoff_date' in results` evaluates to `True`, causing Python to access unassigned local variable `cutoff_date`, triggering an immediate unhandled crash that takes down the entire Streamlit page across Views B, C, and E.

### Defect 2 (HIGH): Early `return` in `render_live_recommendations` skips TASE section when US screener is empty
- **File**: `src/ui/app.py`
- **Lines**: 370–372
- **Observed Behavior**:
  ```python
  370: if df.empty:
  371:     st.warning("No stocks passed all screening filters for the latest trade date.")
  372:     return
  ```
  When 0 US stocks pass screening filters, line 372 performs an early `return` before Section 3 (lines 418–474: Category 3 Dedicated Tel Aviv Stock Exchange recommendations) is ever reached. This breaks requirement R3 ("Display the Top 5 TASE recommendations as a dedicated visual section/card below the US Top 10 across Views A, B, C, D, and E") whenever the US market conditions produce 0 qualifying picks.

### Defect 3 (MEDIUM): `np.nan` in `name` column evaluates to literal `"nan"` string instead of ticker fallback
- **File**: `src/ui/app.py`
- **Lines**: 274, 1131
- **Observed Behavior**:
  Line 274: `comp_name = str(row.get("name") or row["ticker"])`
  Line 1131: `name_str = row.get("name", tick)`
  Because `np.nan` is a float and `bool(float('nan'))` is `True` in Python, `row.get("name") or row["ticker"]` evaluates to `np.nan`. Converting to string yields `"nan"` in table anchors (`<a class="company-link" ...>nan</a>`) and expander titles (`📌 **DSCT.TA** — nan`).

---

## 2. Logic Chain

1. **Decoupling Violation in Backtest Guide**:
   - `render_backtest_view` decoupled US and TASE backtest execution pipelines, but left references to `cutoff_date` and `eval_date` in the common bottom expander guide.
   - If `results["positions_df"].empty` is True, `cutoff_date` is not bound, but `results and 'cutoff_date' in results` evaluates to `True`, triggering `UnboundLocalError`.
2. **Decoupling Violation in Live Screener (View A)**:
   - `render_live_recommendations` assumes `df` (US screener) is non-empty before proceeding to TASE screener (`df_tase`).
   - If `df.empty` is True, `return` exits the function immediately, abandoning the TASE screener pipeline entirely.
3. **Data Schema Robustness in Table Formatting**:
   - Equities ingested without full company metadata have `NULL` (`np.nan`) in `symbol_metadata.name`.
   - String interpolation using `or` fails on float NaNs because floats are truthy in Python.

---

## 3. Caveats

- Mixed US and TASE ticker routing in View D (`run_screener` with `manual_tickers`) operates smoothly and segregates tickers into appropriate sub-tables once data is loaded.
- CSS color palettes (`#eef5fc`, `#0b4f8a`, `#b6d4fe`, `#f7faff`) and tabular numeral typography conform to specifications.
- 8-point checklist threshold math evaluates accurately against both US ($10 floor, $20M ADV) and TASE (100 Ag. floor, 20M Ag. ADV) benchmarks.

---

## 4. Conclusion

**Verdict: REQUEST_CHANGES**

The implementation in `src/ui/app.py` contains 1 CRITICAL runtime crash defect and 1 HIGH decoupling defect that must be corrected before Milestone 3 can be approved:

1. **Fix `render_backtest_view` Variable Binding**:
   Assign default values at the top of `render_backtest_view`:
   ```python
   cutoff_date = str(results["cutoff_date"]) if results and "cutoff_date" in results else "N/A"
   eval_date = str(results["evaluation_date"]) if results and "evaluation_date" in results else "N/A"
   ```
2. **Fix `render_live_recommendations` Decoupling**:
   Replace the early `return` with an informative warning and allow execution to continue to Section 3:
   ```python
   if df.empty:
       st.warning("No US stocks passed all screening filters for the latest trade date.")
   else:
       # render US tables ...
   ```
3. **Fix NaN Name Formatting**:
   Use `pd.notna` guards for `name`:
   ```python
   name_val = row.get("name")
   comp_name = str(name_val) if pd.notna(name_val) and str(name_val).strip() else str(row["ticker"])
   ```

---

## 5. Verification Method

To reproduce and verify these findings independently:

1. Run the adversarial stress test suite:
   ```powershell
   python -m pytest tests/test_adversarial_m3_ui.py -v
   ```
2. Inspect test outputs:
   - `test_backtest_view_unbound_local_error_proof` reproduces `UnboundLocalError`.
   - `test_view_a_zero_us_qualifying_skips_tase_bug` reproduces TASE skipping on empty US screener.
   - `test_nan_name_string_coercion_flaw` reproduces `"nan"` company name coercion.
