# Plan: Add UIT ETF Discovery to Pipeline

## Steps
- [ ] Step 1: Modify `discover.py` to add UIT discovery via SEC EDGAR full-text search for Form S-6 filers (implementer)
- [ ] Step 2: Update `tests/test_discover.py` with UIT test coverage (implementer)
- [ ] Step 3: Review all changes (reviewer)
- [ ] Step 4: Run tests (tester)
- [ ] Step 5: Regenerate `data/etf_tickers.json` by running discover command
