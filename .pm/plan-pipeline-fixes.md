# PM Plan: Fix 5 Pipeline & Display Bugs

## Current State

The investigation identified 5 bugs (excluding `category` which is intentionally a placeholder). All root causes are confirmed with database evidence and code tracing.

## Steps

### Step 1: Fix fee display — multiply fee values by 100 in API layer (implementer)
- **File:** `src/etf_pipeline/api/routes/xray.py` (fee section ~lines 176-186)
- **Problem:** Fee values stored as pure ratios (0.0003 = 0.03%) but `formatPct` just does `.toFixed(2) + "%"`.
- **Critical context:** `formatPct` is also called by HoldingsCard, AssetAllocationCard, FundHealthCard with 0-100 scale values. So we CANNOT just multiply by 100 inside `formatPct` — that would break everything else.
- **Solution:** Multiply fee values by 100 in the API layer before sending to frontend. In `xray.py` lines 177-183, multiply each fee float by 100. This keeps `formatPct` unchanged and fixes fees without breaking holdings/allocations.
- **Verify:** All other `formatPct` callers receive 0-100 scale data already (holdings pct_val, cash_position_pct, asset allocation pct).

### Step 2: Fix benchmark name corruption — blocklist tax-treatment members (implementer)
- **File:** `src/etf_pipeline/parsers/prospectus.py` (~line 916-924)
- **Problem:** `PerformanceMeasureAxis` dimension contains both real benchmarks and tax-treatment labels. Parser grabs whichever comes first.
- **Solution:** Add a blocklist set of 6 known non-benchmark member IDs: `AfterTaxesOnDistributionsMember`, `AfterTaxesOnDistributionsAndSalesMember`, `AftertaxondistributionsMember`, `ReturnBeforeTaxesMember`, `ReturnAfterTaxesonDistributionsMember`, `BasedonNAVMember`. Skip these when selecting `benchmark_name`.
- **Data cleanup:** After fixing parser, run SQL to NULL out the ~3,054 corrupted benchmark_name values in the performance table.

### Step 3: Fix SPY/DIA/MDY HTML performance parsing — 3 sub-bugs (implementer)
- **File:** `src/etf_pipeline/parsers/prospectus.py` (~lines 698-853)
- **Bug 3a — Column offset:** Header maps `<th>` positions but SPDR COLSPAN="2" layout puts data one column right. Fix: when building `col_to_field`, account for colspan by tracking actual column positions rather than element indices.
- **Bug 3b — Empty parent row:** `horizontal_fund_row_seen` set on empty grouping row. Fix: only set flag when at least one value was parsed from the row.
- **Bug 3c — Cumulative vs Annual:** Same `<table>` has both sections; parser locks onto cumulative. Fix: if a row contains "average annual" text, reset `header_parsed` and `horizontal_fund_row_seen` to re-parse from that section.
- **Also:** Change logger.debug to logger.warning at line 851-852 for visibility.

### Step 4: Fix first-time CIK skip logic (implementer)
- **File:** `src/etf_pipeline/cli.py` (~lines 599-609)
- **Problem:** When `has_any_log=False` and `stale_parsers` is empty, CIK is skipped. Should treat never-processed CIKs as all-parsers-stale.
- **Solution:** Change the condition: if `not has_any_log`, set `stale_parsers` to all parser names instead of skipping.

### Step 5: Fix N-PORT UIT date type error (implementer)
- **File:** `src/etf_pipeline/parsers/nport.py` (~line 366)
- **Problem:** `FundReport.reporting_period` returns `str` for UIT NPORT-P filings, causing `ensure_date` to raise TypeError.
- **Solution:** Wrap with a string-to-date parse fallback at the call site (not in `ensure_date` globally, to avoid masking type errors elsewhere).

### Step 6: Data cleanup migration (implementer)
- **Run SQL:** NULL out `performance.benchmark_name` where value is in the blocklist set (6 values, ~3,054 rows)
- **Verify:** Query database to confirm cleanup

### Step 7: Run tests (tester)
- Run full test suite to verify no regressions
- Specifically run: `test_benchmark_mapping.py`, `test_resolve_benchmarks.py`
- Run any prospectus parser tests
- Run frontend tests if they exist

### Step 8: Final review (reviewer)
- Review all changes for correctness, side effects, and code quality

## Execution Strategy

- **Parallel batch 1:** Steps 1, 2, 4, 5 (independent files)
- **Sequential after batch 1:** Step 3 (same file as Step 2), then Step 6
- **Final:** Step 7, then Step 8

## Risks

1. **Step 1 (fee scale):** If any API endpoint sends fee values that are already multiplied by 100 somewhere upstream, we'd double-multiply. Need to verify the raw DB values flow through unchanged before the multiply.
2. **Step 3 (HTML parsing):** The SPDR table layout fix could break parsing for other issuers with different HTML layouts.
3. **Step 2+3 (same file):** Both modify `prospectus.py` — must be sequenced to avoid merge conflicts.
4. **Step 5 (nport date):** The `ensure_date` function is used broadly — changing it globally would be risky. Fix at call site only.

## Estimated Scope
- Files affected: 4 (`xray.py`, `prospectus.py`, `cli.py`, `nport.py`)
- Subagents needed: implementer (x5-6), tester (x1), reviewer (x1)
