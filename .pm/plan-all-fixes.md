## PM Plan: Fix All Remaining Pipeline Issues — COMPLETE

### Group A — Parser Data Loss Fixes
- [x] Step 1: Multi-class dedup (track processed series_ids)
- [x] Step 2: Per-holding error isolation (try/except in loop)
- [x] Step 3: Per-ETF commit in normal mode
- [x] Step 4: Empty holding_key guard (positional fallback)
- [x] Step 5: Guard non_derivatives/derivatives against None

### Group B — Discovery Fixes
- [x] Step 6: Allow 2-char tickers
- [x] Step 7: Move UIT allowlist to fetch()
- [x] Step 8: Add rate limiting to EDGAR requests

### Group C — X-Ray Card Consistency Fixes
- [x] Step 9: Normalize NULL pct_val handling across cards
- [x] Step 10: Fix HHI scale (confirmed correct, no change needed)
- [x] Step 11: Add cash to asset allocation
- [x] Step 12: Match report_dates between snapshot and holdings
- [x] Step 13: Return leverage_ratio=None when data missing

### Group D — Database Constraint Fixes
- [x] Step 14: Remove liquidity_classification from holding_uniq
- [x] Step 15: Remove class_id from nport_monthly_flow_uniq
- [x] Step 16: Fix derivative_uniq NULLs (sentinel value)

### Group E — Pipeline Resilience
- [x] Step 17: Verify zero-holdings ETFs handled correctly (confirmed safe)

### Group F — Tests + Migration + Review
- [x] Step 18: Alembic migration for constraint changes
- [x] Step 19: Write/update tests (378 total, all passing)
- [x] Step 20: Final review — PASS (1 bug found and fixed: UIT processing log)
