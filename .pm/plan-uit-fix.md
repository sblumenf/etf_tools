## PM Plan: Fix UIT ETF Data Pipeline (SPY/DIA/MDY) — COMPLETE

### Root Cause

`fr.general_info.report_date` on line 368 of nport.py doesn't exist — the correct attribute is `fr.reporting_period`. This single typo caused every SPY N-PORT-P filing to fail silently (caught by `except Exception`, logged at DEBUG level).

### Steps

- [x] Step 1: Diagnose actual error — AttributeError on `general_info.report_date` (should be `reporting_period`)
- [x] Steps 2-3: SKIPPED — FundReport.from_filing() works fine for SPY, no XML fallback needed
- [x] Step 4: Raised logging from DEBUG to WARNING (nport.py line 374)
- [x] Step 5: Added 3 tests for UIT fallback path (78/78 pass)
- [x] Step 6: Research — SPY does NOT file N-CSR (1 filing from 2004), 485BPOS is non-iXBRL HTML. Other parsers correctly skip UITs.
- [x] Step 7: Final review — PASS, no regressions, 393 total tests pass

### Changes Made

| File | Change |
|------|--------|
| `src/etf_pipeline/parsers/nport.py:368` | `fr.general_info.report_date` → `fr.reporting_period` |
| `src/etf_pipeline/parsers/nport.py:374` | `logger.debug` → `logger.warning` |
| `tests/test_nport.py` | +3 tests for UIT fallback |

### Research Findings (Other Parsers)

| Parser | SPY Files This? | Action Needed |
|--------|----------------|---------------|
| ncsr | No (1 filing from 2004) | None — correctly skips |
| finhigh | No (depends on N-CSR) | None — correctly skips |
| prospectus | Yes (485BPOS) but non-iXBRL HTML | Future: could optimize to skip download |
| nport | Yes (NPORT-P quarterly) | Fixed in this task |
| flows | Yes (24F-2NT) | Already works |

### Reviewer Notes

- Low-severity: `ensure_date(fr.reporting_period)` at line 368 doesn't guard against string values like lines 154-155 do. Pre-existing, not introduced here.
