# Plan: Fix Data Pipeline Completeness Issues

## Steps
- [x] Step 1: Fix NPORT parser — add early exit to `_get_latest_filings_per_series` (nport.py)
- [x] Step 2: Fix NCSR parser — raise MAX_FILINGS from 10 to 50 (ncsr.py)
- [x] Step 3: Fix CLI timeout — make proportional to ETF count (cli.py)
- [x] Step 4: Run all tests — 321 passed, 1 skipped, 0 failed
- [x] Step 5: Final review — PASS
