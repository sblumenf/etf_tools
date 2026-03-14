## PM Plan: Fix All 7 Data Consistency Issues — COMPLETE

- [x] Step 1: Add "N/A" to PLACEHOLDER_CUSIPS
- [x] Step 2: Add value_usd tiebreaker to dedup key
- [x] Step 3: Add hardcoded UIT allowlist for SPY/DIA/MDY
- [x] Step 4: Add series_id=None fallback path in NPORT parser (+ fix unreachable guard)
- [x] Step 5: Fix ASSET_CATEGORY_MAP (add XSD codes, remove dead entries)
- [x] Step 6: Align in-memory dedup key with DB constraint (filing_date added)
- [x] Step 7: Add currency validation warning
- [x] Step 8: Update/add tests (28 new, 372 total passing)
- [x] Step 9: Final review — PASS (1 bug found and fixed)
