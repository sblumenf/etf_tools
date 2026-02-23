# PM Plan: Simplify Codebase

## Current State
The etf_tools codebase is a SEC EDGAR ETF data pipeline with 5 parsers (nport, ncsr, prospectus, finhigh, flows). A simplification audit found 3 HIGH, 15 MEDIUM, and 7 LOW severity issues across dead code, over-abstraction, reimplemented functionality, duplicate logic, and repo bloat.

## Steps

### Phase A: Foundation — Shared Utilities (sequential, enables later phases)

- [x] **Step 1: Consolidate shared functions into parser_utils.py** (DONE)
  - Files: `src/etf_pipeline/parser_utils.py`, `src/etf_pipeline/parsers/nport.py`, `src/etf_pipeline/parsers/nport_xml.py`, `src/etf_pipeline/parsers/ncsr.py`, `src/etf_pipeline/parsers/finhigh.py`, `src/etf_pipeline/parsers/flows.py`
  - Add to parser_utils.py:
    - `clean_str(val)` — canonical version (no Mock detection)
    - `safe_numeric(val)` — canonical version (no Mock detection)
    - `get_clean(obj, attr)` — helper: `clean_str(getattr(obj, attr, None))`
    - `get_numeric(obj, attr)` — helper: `safe_numeric(getattr(obj, attr, None))`
    - `parse_decimal(val)` — superset from finhigh.py (handles $, %, parens, commas, N/A, Decimal passthrough)
    - `parse_date(val)` — tries YYYY-MM-DD, MM/DD/YYYY, and other known formats
  - Update imports in nport.py, nport_xml.py, ncsr.py, finhigh.py, flows.py to use shared versions
  - Remove local `_clean_str`, `_safe_numeric`, `_parse_decimal`, `_parse_date` from each parser
  - Remove Mock detection from production code
  - Subagent: **implementer**

### Phase B: nport.py Simplification (sequential, largest file)

- [x] **Step 2: Cache filing.xml() in _process_etf()** (DONE)
  - File: `src/etf_pipeline/parsers/nport.py`
  - Call `xml_text = filing.xml()` once at top of `_process_etf()`
  - Pass `xml_text` to `_extract_monthly_returns`, `_extract_monthly_flows`, `_extract_interest_rate_risk`, `_extract_credit_spread_risk`
  - Update those 4 functions to accept xml_text instead of filing
  - Pass `xml_text` directly to `parse_nport_investments_xml()` (already accepts string)
  - Subagent: **implementer**

- [x] **Step 3: Collapse _extract_fund_snapshot() with getattr()** (DONE)
  - File: `src/etf_pipeline/parsers/nport.py`
  - Replace 19 try/except blocks with getattr() calls (~160 lines -> ~25 lines)
  - Subagent: **implementer**

- [x] **Step 4: Replace hasattr ternary patterns with get_clean/get_numeric helpers** (DONE)
  - File: `src/etf_pipeline/parsers/nport.py`
  - Replace ~80 instances of `_clean_str(obj.attr) if hasattr(obj, 'attr') else None` with `get_clean(obj, 'attr')`
  - Replace ~20 instances of `_safe_numeric(obj.attr) if hasattr(obj, 'attr') else None` with `get_numeric(obj, 'attr')`
  - Subagent: **implementer**

- [x] **Step 5: Remove double-guarding in _map_debt_security_detail() and _map_security_lending()** (DONE)
  - File: `src/etf_pipeline/parsers/nport.py`
  - Replace hasattr + try/except blocks with getattr() or get_clean/get_numeric helpers
  - Subagent: **implementer**

### Phase C: Dead Code Removal (parallel-safe)

- [x] **Step 6: Remove dead code** (PARTIAL — extract_borrower_name kept due to test dependency)
  - Files: `src/etf_pipeline/parsers/nport_xml.py`, `src/etf_pipeline/parsers/nport.py`, `src/etf_pipeline/parsers/ncsr.py`, `src/etf_pipeline/models.py`
  - Delete `extract_borrower_name()` from nport_xml.py
  - Remove `borrower_name` from result dict in `parse_nport_investments_xml()`
  - Remove `borrower_name` lookup in nport.py line ~1146
  - Remove `other_amt` initialization and passing in nport.py (keep column on model for future use)
  - Remove unused `import pandas as pd` from ncsr.py
  - Subagent: **implementer**

### Phase D: Config & Dependency Fixes (parallel-safe)

- [x] **Step 7: Fix config issues** (DONE)
  - Files: `src/etf_pipeline/discover.py`, `src/etf_pipeline/config.py`, `src/etf_pipeline/parser_utils.py`, `pyproject.toml`
  - In discover.py: import EDGAR_IDENTITY from config.py, remove load_dotenv() call
  - In parser_utils.py: fix sqlite dialect — use dialect-agnostic upsert (select-then-update-or-insert)
  - In pyproject.toml: add `python-dateutil` as explicit dependency (used in prospectus.py)
  - Do NOT add pandas — the import is being removed in Step 6
  - Subagent: **implementer**

### Phase E: Repo Cleanup (parallel-safe)

- [x] **Step 8: Clean up repo bloat** (DONE)
  - Files: `.gitignore`, `docs/failed-ciks.txt`, `docs/reference/nport-xsd/.../Thumbs.db`, `.pm/` old plans, `README.md`, `src/etf_pipeline/py.typed`
  - Add to .gitignore: `Thumbs.db`, `docs/failed-ciks.txt`
  - Delete: `docs/failed-ciks.txt`, Thumbs.db, `src/etf_pipeline/py.typed`
  - Delete duplicate: `docs/reference/xbrl-rr-2023/rr-samples/rr-samples-2023/` (keep `docs/reference/rr-samples-2023/`)
  - Delete: `docs/reference/xbrl-rr-2023/rr-samples-2023.zip`
  - Note: Keep docs/reference/ in repo (required by project rules for parser work)
  - Note: Keep .pm/ plans (will be used to track this work)
  - Subagent: **implementer**

### Phase F: Test Fixes (sequential, after all code changes)

- [x] **Step 9: Fix test fixtures** (DONE)
  - Files: `tests/conftest.py`, `tests/test_nport.py`, `tests/test_nport_credit_spread.py`
  - Move `_add_mock_fund_info()` to conftest.py as a shared fixture
  - Update both test files to import from conftest
  - Remove Mock detection workarounds if tests were relying on them
  - Subagent: **implementer**

- [x] **Step 10: Run tests and fix any breakage** (DONE — 279 pass, 9 pre-existing failures)
  - Run full test suite
  - Fix any import errors or regressions from the changes
  - Subagent: **tester**

### Phase G: Final Review

- [x] **Step 11: Code review all changes** (DONE — PASS with minor caveats fixed)
  - Review all modified files for correctness, consistency, and no regressions
  - Subagent: **reviewer**

## Execution Strategy

```
Phase A (Step 1)          -- SEQUENTIAL (foundation for B)
    |
Phase B (Steps 2→3→4→5)  -- SEQUENTIAL within phase (all modify nport.py)
    |
Phase C+D+E (Steps 6,7,8) -- PARALLEL (independent files)
    |
Phase F (Steps 9→10)     -- SEQUENTIAL (tests after all code changes)
    |
Phase G (Step 11)         -- SEQUENTIAL (final review)
```

## Risks

1. **Import chain breakage** — Moving functions to parser_utils.py may cause circular imports if parser_utils imports from parsers. Mitigated by: parser_utils should only import from models/config, never from parsers.
2. **filing.xml() signature changes** — The 4 extraction functions need their signatures changed to accept xml_text instead of filing. Any other callers of these functions will break. Mitigated by: these are private functions, only called from _process_etf().
3. **Decimal parsing behavior change** — Consolidating to finhigh.py's superset parse_decimal means nport.py and ncsr.py will now accept formats they previously rejected. Mitigated by: SEC filings use consistent formats; extra format support is harmless.
4. **SQLite upsert change** — Changing from sqlite.insert to dialect-agnostic may subtly change upsert behavior. Mitigated by: test the upsert logic explicitly.

## Estimated Scope
- Files affected: ~15
- Subagents needed: implementer (×8), tester (×1), reviewer (×1)
