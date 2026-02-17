# Fix Silent Parser Skipping in Pipeline

## Steps
- [x] Step 1: Research — Read exact current code for check_sec_filing_dates, get_stale_parsers, run_all
- [x] Step 2: Implement — Fix check_sec_filing_dates to return (dict, had_error) tuple
- [x] Step 3: Implement — Fix get_stale_parsers to treat failed check as "stale" for unprocessed parsers
- [x] Step 4: Implement — Fix run_all: track failed_parsers, don't re-raise, pass check_failed
- [x] Step 5: Test — 279 tests passing
- [x] Step 6: Test — Added 3 new tests for check_failed scenarios
- [x] Step 7: Review — Passed after test gaps were filled

## Status: COMPLETE
