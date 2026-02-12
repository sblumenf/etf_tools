# Ralph Progress: NPORT-P Parser Implementation

## Status: IN PROGRESS

## Completed Tasks
- [x] Read reference documentation (PARSER_REFERENCE_MAP.md, NPORT XSD schemas)
- [x] Reviewed existing codebase (models.py, cli.py, config.py)
- [x] Checked etf_tickers.json structure
- [x] **Phase 1: load-etfs command + tests** ✅
  - Created `src/etf_pipeline/load_etfs.py`
  - Added `load-etfs` CLI command with --cik and --limit flags
  - Created `tests/test_load_etfs.py` (7 tests, all passing)
  - All 21 tests pass

## Current Task
- [ ] **Phase 2: NPORT parser (holdings) + tests**
  - Creating `src/etf_pipeline/parsers/nport.py`
  - Wiring `nport` CLI command
  - Writing holding extraction tests

## Remaining Tasks
- [ ] Phase 3: NPORT parser (derivatives) + tests

## Notes
- CIK in etf_tickers.json is an integer, not zero-padded string
- Need to use edgartools Company(cik).name for issuer_name
- Series-level fund_name lookup also needed
