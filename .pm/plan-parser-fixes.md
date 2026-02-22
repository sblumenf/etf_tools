# PM Plan: Fix 5 Parser Bugs (Prospectus + Finhigh) — COMPLETE

## Steps

- [x] Step 1: Fix `RiskNarrativeTextBlock` substring match (prospectus.py:581)
- [x] Step 2: Refactor narrative loop to iterate series IDs (prospectus.py:548-611)
- [x] Step 3: Add 120s signal.alarm() timeout around filing.html() (prospectus.py:419-431)
- [x] Step 4: Per-filing commit in prospectus parser (prospectus.py:623-624)
- [x] Step 5: Per-filing commit + cleanup in finhigh parser (finhigh.py:641-648)
- [x] Step 6: Tests — 288 passed, 0 failed
- [x] Step 7: Review — 2 bugs found and fixed (signal handler leak, early-break cleanup)

## Status: COMPLETE
