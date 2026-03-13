# PM Plan: Simplify Parser Codebase

## Current State
- 4,855 lines across 10 source files in src/etf_pipeline/
- 5 parsers (nport, ncsr, prospectus, finhigh, flows) each copy-paste ~40 lines of identical boilerplate
- parser_utils.py has some shared helpers but is underused
- nport.py parses the same XML 5 times per filing
- Several dead code paths and redundant wrappers

## Steps

### Commit 1: Extract shared parser utilities (biggest win, ~250 lines)

- [ ] Step 1: Add shared utilities to `parser_utils.py` — implementer
  - `resolve_cik_list(session, cik, ciks, limit)` — CIK resolution logic
  - `run_parser_loop(cik_list, session_factory, process_fn)` — succeeded/failed loop + summary
  - `clear_and_log_cache()` — cache-clear + logging block
  - `upsert_record(session, model_class, filter_kwargs, data_kwargs)` — generic upsert
  - Files: `src/etf_pipeline/parser_utils.py`

- [ ] Step 2: Refactor ncsr.py to use shared utilities — implementer
  - Replace CIK resolution, loop, cache-clear, upsert, date coercion
  - Files: `src/etf_pipeline/parsers/ncsr.py`

- [ ] Step 3: Refactor prospectus.py to use shared utilities — implementer
  - Replace CIK resolution, loop, cache-clear, upsert
  - Fix N+1 session.get (use already-loaded data)
  - Files: `src/etf_pipeline/parsers/prospectus.py`

- [ ] Step 4: Refactor finhigh.py to use shared utilities — implementer
  - Replace CIK resolution, loop, cache-clear, 3x upsert calls
  - Remove redundant `if 'X' in row_map else None` guards
  - Files: `src/etf_pipeline/parsers/finhigh.py`

- [ ] Step 5: Refactor flows.py to use shared utilities — implementer
  - Replace CIK resolution, loop, cache-clear, upsert
  - Files: `src/etf_pipeline/parsers/flows.py`

- [ ] Step 6: Refactor nport.py entry point to use shared utilities — implementer
  - Replace cache-clear block (CIK resolution is different here — keep custom)
  - Files: `src/etf_pipeline/parsers/nport.py`

- [ ] Step 7: Run tests — tester
  - Verify all existing tests pass after refactor

### Commit 2: Fix nport.py efficiency + dead code (~100 lines)

- [ ] Step 8: Parse XML once, pass root element to all extractors — implementer
  - Modify `_process_etf` to parse once
  - Update `_extract_monthly_returns`, `_extract_monthly_flows`, `_extract_interest_rate_risk`, `_extract_credit_spread_risk` to accept root element
  - Extract NPORT_NS to module-level constant
  - Files: `src/etf_pipeline/parsers/nport.py`

- [ ] Step 9: Remove dead code from nport.py and nport_xml.py — implementer
  - Remove `_parse_delta` (use `parse_decimal`)
  - Remove `parse_return` / `parse_flow` identity wrappers
  - Remove `extract_borrower_name` stub + downstream references
  - Consolidate pre-declared None blocks in risk extractors
  - Files: `src/etf_pipeline/parsers/nport.py`, `src/etf_pipeline/parsers/nport_xml.py`

- [ ] Step 10: Run tests — tester

### Commit 3: Minor fixes (~50 lines)

- [ ] Step 11: Fix remaining minor issues — implementer
  - ncsr.py: Replace all inline date coercion with `parse_date()`, remove dead `_parse_decimal` alias
  - cli.py: Batch stale-parser DB queries (1 query per CIK instead of 6), move inline imports to top
  - Files: `src/etf_pipeline/parsers/ncsr.py`, `src/etf_pipeline/cli.py`

- [ ] Step 12: Run tests — tester

- [ ] Step 13: Final review — reviewer

## Execution Strategy
- Steps 1 must complete before steps 2-6 (they depend on the new utilities)
- Steps 2-6 can run in parallel (independent parser files)
- Step 7 must follow steps 2-6
- Steps 8-9 can run in parallel
- Step 10 must follow steps 8-9
- Step 11 after commit 2 is done
- Step 13 reviews all changes at the end

## Risks
- Changing parser entry points could break CLI invocation if signatures change
- The upsert_record generic must handle all existing filter patterns correctly
- nport.py's CIK resolution is different from the other 4 — must not be forced into the shared pattern

## Estimated Scope
- Files affected: 8 (parser_utils.py, nport.py, nport_xml.py, ncsr.py, prospectus.py, finhigh.py, flows.py, cli.py)
- Subagents: implementer, tester, reviewer
- Estimated reduction: ~340-400 lines
