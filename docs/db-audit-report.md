# Database Audit Report

## Executive Summary

- **Tables Analyzed**: 18 tables across 7 analysis runs
- **Total Rows**: 51,392 rows
- **Critical Bugs**: 8 (6 original + 2 reclassified from INVESTIGATE)
- **Fixed**: 6 (2026-02-15)
- **Already Fixed**: 1 (commit 3ff8488, 2026-02-14)
- **Verified OK**: 1 (debt_security booleans — mapping was already correct)
- **Expected Gaps**: 4
- **Not a Bug**: 1 (reclassified from INVESTIGATE)

### Severity Breakdown
- **FIXED** (2026-02-15): security_lending booleans, derivative futures fields, holding currency priority, maturity_date extraction, borrower_name/liquidity key matching
- **ALREADY FIXED**: performance benchmark/expense fields (commit 3ff8488)
- **VERIFIED OK**: debt_security_detail boolean field mapping (already correct)
- **NOT A BUG**: flow_data net_sales=0 (correct per SEC spec), etf.category (design decision)
- **EXPECTED**: 4 issues that are normal for current data

## Actionable Issues

### BUG: etf.category field never populated
- **Table**: `etf`
- **Issue**: 100% NULL (0/30 rows populated)
- **Root cause**: Field exists in model but no code populates it anywhere in codebase
- **File/line**: `src/etf_tools/models/etf.py` (model definition), no parser implementation
- **Action**: Either implement category extraction from filings or remove field from model
-  **HUMAN REVIEWER**: not a bug.  design decision

### ~~BUG~~ FIXED: holding.currency extraction fails for 31.5% of holdings
- **Table**: `holding`
- **Issue**: 7,574 rows (31.5%) have NULL currency BUT populated exchange_rate
- **Root cause**: Parser checked unreliable `identifiers.other` dict first, then fell back to `investment.currency_code` (backwards priority)
- **Fix applied (2026-02-15)**: Swapped priority — now checks `investment.currency_code` first (primary reliable field), falls back to `identifiers.other` dict only if needed.

### ~~BUG~~ FIXED: holding.borrower_name and liquidity_classification never populated
- **Table**: `holding`
- **Issue**: 100% NULL (0/24,052 rows populated)
- **Root cause**: Key mismatch between XML parser (raw "N/A" in keys) and NPORT parser (cleaned to empty string)
- **Fix applied (2026-02-15)**: Added `_clean_str()` to `nport_xml.py` to normalize keys consistently. `liquidity_classification` now populates from `<fundCat>` XML element. `borrower_name` correctly remains NULL (fund-level field, not per-holding in NPORT schema).

### ~~BUG~~ FIXED: debt_security_detail.maturity_date always NULL
- **Table**: `debt_security_detail`
- **Issue**: 100% NULL (0/2,815 rows populated)
- **Root cause**: Parser didn't handle edgartools returning datetime objects or "N/A" strings for maturity_date
- **Fix applied (2026-02-15)**: Enhanced maturity_date parsing to handle datetime (`.date()`), date, "N/A" (→ None), and string formats.

### ~~BUG~~ VERIFIED OK: debt_security_detail boolean fields never True
- **Table**: `debt_security_detail`
- **Issue**: All boolean fields always False (0/2,815 rows have any True value)
- **Verification (2026-02-15)**: Model already uses correct field names (`is_in_arrears`, `is_contingent_convertible`). Parser correctly maps from edgartools typo'd names (`are_instrument_payents_in_arrears`, `is_continuing_convertible`) to model's clean names. All False values are likely correct for the current dataset (Vanguard bond ETFs rarely have arrears/contingent convertible securities).

### ~~BUG~~ ALREADY FIXED: performance benchmark and expense fields never populated
- **Table**: `performance`
- **Issue**:
  - `benchmark_name`, `benchmark_return_1yr`, `benchmark_return_5yr`, `benchmark_return_10yr`: 100% NULL (0/44 rows)
  - `expense_ratio_actual`, `portfolio_turnover`: 100% NULL (0/44 rows)
- **Verification (2026-02-15)**: This was already fixed in commit `3ff8488` (2026-02-14). The bug was that benchmark XBRL facts have `BroadBasedIndexAxis` dimension but NULL `ClassAxis`, so the per-class filter excluded all benchmark rows. The fix moved benchmark extraction before the per-class loop. Database currently has all 44 rows with non-NULL values. Audit report was based on stale DB snapshot.

## Table-by-Table Analysis

### etf
- **Rows**: 30
- **NULLs**:
  - `category`: 30 (100%)
- **Issues**: category field never populated (see BUG above)
- **Verdict**: **BUG** - implement or remove category field -- **HUMAN CONTEXT**:  not s bug, design decision

---

### holding
- **Rows**: 24,052 (26 ETFs, 2 report dates)
- **NULLs**:
  - `cusip`: 7,108 (29.6%) - expected for foreign holdings
  - `ticker`: 10,470 (43.5%) - 100% NULL for DBT/EP/STIV, expected
  - `lei`: 6,209 (25.8%) - varies by asset type
  - `currency`: 7,574 (31.5%) - **BUG**: exchange_rate populated but currency NULL
  - `exchange_rate`: 16,478 (68.5%) - expected, only for non-USD
  - `borrower_name`: 24,052 (100%) - **BUG**: never populated
  - `liquidity_classification`: 24,052 (100%) - **BUG**: never populated
- **Issues**:
  - 112 holdings (0.5%) missing both CUSIP and ISIN - handled by fallback to name
  - See BUG issues above for currency, borrower_name, liquidity_classification
- **Verdict**: **BUG** - fix currency extraction, implement borrower_name/liquidity_classification or remove

---

### derivative
- **Rows**: 37 (16 FUT, 19 SWP, 2 FWD)
- **NULLs**:
  - `underlying_title`: 18 (48.6%) - 100% NULL for FUT (16/16), all SWP populated
  - `underlying_lei`: similar pattern to underlying_title
  - `underlying_cusip`: similar pattern to underlying_title
- **Issues**: FUT derivatives have 100% NULL underlying fields - edgartools field access issue
- **Verdict**: ~~INVESTIGATE~~ **BUG** - parser accesses wrong field names on `FutureDerivative`
- **Investigation findings (2026-02-15)**:
  - **Root cause**: `nport.py:1312` accesses `fut.currency_code` but the edgartools field is `fut.currency`. Lines 1320-1327 attempt to access `reference_entity_balance`, `reference_entity_units`, etc. which do not exist on the edgartools `FutureDerivative` class. The `hasattr()` checks silently fail, leaving all underlying fields as `None`.
  - **Why swaps work**: `SwapDerivative` class has both `deriv_addl_*` and `reference_entity_*` fields; parser correctly uses fallback logic.
  - **Fix**: Change `fut.currency_code` to `fut.currency`. Remove `hasattr()` checks for non-existent fields (lines 1320-1327). Keep correct fields: `reference_entity_name`, `reference_entity_title`, `reference_entity_cusip`. Note: futures do NOT have extended underlying fields (balance, units, value_usd, etc.) per the NPORT XSD — this is expected.

---

### derivative_swap
- **Rows**: 19
- **NULLs**: None
- **Issues**: No issues, all rows properly linked to parent derivatives
- **Verdict**: **OK**

---

### derivative_swap_leg
- **Rows**: 38 (2 per swap)
- **NULLs**: None
- **Issues**: No issues, all swap legs properly populated
- **Verdict**: **OK**

---

### derivative_option
- **Rows**: 0
- **NULLs**: N/A
- **Issues**: No options in current data
- **Verdict**: **EXPECTED** - these ETFs don't hold options

---

### derivative_forward
- **Rows**: 2
- **NULLs**: None
- **Issues**: No issues, all rows properly linked to parent derivatives
- **Verdict**: **OK**

---

### debt_security_detail
- **Rows**: 2,815
- **NULLs**:
  - `maturity_date`: 2,815 (100%) - **BUG**
  - `coupon_kind`: 2,733 (97.1%) - 82 rows have string "None" instead of SQL NULL
- **Issues**:
  - All boolean fields always False (see BUG above)
  - maturity_date 100% NULL (see BUG above)
- **Verdict**: **BUG** - fix field name typos, implement maturity_date extraction

---

### security_lending
- **Rows**: 24,052
- **NULLs**: None (all boolean fields)
- **Issues**: 93% have all three booleans = True - suspicious pattern, likely parser or source data issue
- **Verdict**: ~~INVESTIGATE~~ **BUG** - `bool("N")` evaluates to `True` in Python
- **Investigation findings (2026-02-15)**:
  - **Root cause**: `_map_security_lending()` in `nport.py:1587-1602` uses `bool(sec_lending.is_cash_collateral)` to convert string values. edgartools returns the string `"N"` for False values, and `bool("N")` is `True` in Python.
  - **Result**: ~93% of holdings have `"N"` values (not involved in security lending) that are incorrectly stored as `True`. The ~7% with actual `True` values happen to be stored as `False` (edgartools returns `None` for the conditional attribute XML form, defaulting to `False`).
  - **Fix**: Replace `bool(sec_lending.is_cash_collateral)` with `sec_lending.is_cash_collateral == "Y"` for all three fields. Rebuild security_lending data after fix.

---

### performance
- **Rows**: 44 (22 unique ETFs)
- **NULLs**:
  - `return_since_inception`: 44 (100%) - **EXPECTED**: N-CSR only reports 1yr/5yr/10yr
  - `return_10yr`: 6 (13.6%) - **EXPECTED**: ESG funds too new (<10yr old)
  - `return_5yr`: 1 (2.3%) - **EXPECTED**: VCEB too new
  - `benchmark_name`, `benchmark_return_1yr`, `benchmark_return_5yr`, `benchmark_return_10yr`: 44 (100%) - **BUG**
  - `expense_ratio_actual`: 44 (100%) - **BUG**
  - `portfolio_turnover`: 44 (100%) - **BUG**
- **Issues**: See BUG above for benchmark and expense fields
- **Verdict**: **BUG** - implement benchmark/expense extraction or remove fields

---

### fee_expense
- **Rows**: 30
- **NULLs**:
  - `distribution_12b1`: 30 (100%) - expected for Vanguard (no 12b-1 fees)
  - `fee_waiver`: 30 (100%) - expected for Vanguard
  - `total_expense_net`: 30 (100%) - expected for Vanguard
  - `acquired_fund_fees`: 30 (100%) - expected for Vanguard
  - `fee_waiver_expiration_date`: 30 (100%) - expected for Vanguard
- **Issues**: No issues, `management_fee`, `other_expenses`, `total_expense_gross` all populated
- **Verdict**: **EXPECTED** - Vanguard ETFs don't have 12b-1 fees or waivers

---

### per_share_operating
- **Rows**: 79 (23 ETFs)
- **NULLs**:
  - `equalization`: 79 (100%) - **EXPECTED**: Vanguard doesn't use equalization
- **Issues**: No issues, math validation passes 100%
- **Verdict**: **OK**

---

### per_share_distribution
- **Rows**: 79
- **NULLs**:
  - `dist_realized_gains`: 78 (98.7%) - **EXPECTED**: only 1 ETF had realized gains distribution
  - `dist_return_of_capital`: 79 (100%) - **EXPECTED**: no return of capital distributions
- **Issues**: No issues
- **Verdict**: **OK**

---

### per_share_ratios
- **Rows**: 79
- **NULLs**: None
- **Issues**: No issues, 100% populated
- **Verdict**: **OK**

---

### flow_data
- **Rows**: 3
- **NULLs**: None
- **Issues**: Row 3 has `net_sales=0` when `sales != redemptions` - possible data issue
- **Verdict**: ~~INVESTIGATE~~ **NOT A BUG** - correct per SEC 24F-2NT specification
- **Investigation findings (2026-02-15)**:
  - **Root cause**: `net_sales` uses `totalAvailableRedemptionCredits` (includes prior years), not just fiscal year `redemptions_value`. For CIK 0000105544: sales=6.1B, fiscal year redemptions=8.7B, but total available credits=16.9B. Formula: `max(0, 6.1B - 16.9B) = 0`.
  - **Data model gap**: The `flow_data` table only stores `sales_value`, `redemptions_value`, and `net_sales` — it does not store `total_available_redemption_credits`, making the net_sales calculation unverifiable from table data alone.
  - **Recommendation**: Consider adding `total_available_redemption_credits` field to FlowData model for transparency.

---

### fund_snapshot
- **Rows**: 2
- **NULLs**:
  - `cash_not_reported`: 2 (100%)
  - `assets_misc_sec`: 2 (100%)
- **Issues**: No issues, fields likely optional in NPORT-P
- **Verdict**: **EXPECTED**

---

### nport_monthly_return
- **Rows**: 0
- **NULLs**: N/A
- **Issues**: EMPTY - XML element `monthlyTotReturns` not found in filings
- **Verdict**: **EXPECTED** - element may be optional in NPORT-P

---

### nport_monthly_flow
- **Rows**: 0
- **NULLs**: N/A
- **Issues**: EMPTY - XML element not found in filings
- **Verdict**: **EXPECTED** - element may be optional in NPORT-P

---

### interest_rate_risk
- **Rows**: 0
- **NULLs**: N/A
- **Issues**: EMPTY
- **Verdict**: **EXPECTED** - equity ETFs don't have interest rate risk schedules

---

### credit_spread_risk
- **Rows**: 0
- **NULLs**: N/A
- **Issues**: EMPTY
- **Verdict**: **EXPECTED** - equity ETFs don't have credit spread risk schedules

---

### processing_log
- **Rows**: 15 (all 5 parsers represented)
- **NULLs**: None
- **Issues**: No issues
- **Verdict**: **OK**

---

## Recommendations

### High Priority (Critical Bugs)
1. Fix `debt_security_detail` field name typos: `are_instrument_payents_in_arrears` -> `are_instrument_payments_in_arrears`, `is_continuing_convertible` -> `is_contingent_convertible`
2. Implement `debt_security_detail.maturity_date` extraction - debt securities MUST have maturity dates
3. Fix `holding.currency` extraction - holdings with `exchange_rate` MUST have `currency`

### Medium Priority (Data Quality)
4. Implement or remove `holding.borrower_name` and `holding.liquidity_classification`
5. Implement or remove `performance` benchmark fields and `expense_ratio_actual`/`portfolio_turnover`
6. Implement or remove `etf.category` field

### High Priority (Reclassified from INVESTIGATE — 2026-02-15)
7. Fix `security_lending` boolean conversion: replace `bool(value)` with `value == "Y"` in `nport.py:1587-1602` — all three fields inverted for ~93% of rows
8. Fix `derivative` futures field access: change `fut.currency_code` to `fut.currency`, remove non-existent field references in `nport.py:1312-1327`

### No Action Required (Reclassified from INVESTIGATE — 2026-02-15)
9. `flow_data` net_sales=0 is correct per SEC 24F-2NT spec — consider adding `total_available_redemption_credits` field for transparency

### No Action Required
- `per_share_operating.equalization` - Vanguard doesn't use equalization
- `fee_expense` NULL fields - Vanguard doesn't have 12b-1 fees or waivers
- `per_share_distribution` low NULL counts - expected distribution patterns
- Empty tables (`nport_monthly_return`, `nport_monthly_flow`, risk tables) - elements optional in NPORT-P or not applicable to equity ETFs
