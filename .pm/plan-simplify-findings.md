## PM Plan: Act on Simplifier Findings 1-15

### Current State
The codebase has accumulated dead code, duplicated logic, and over-defensive patterns.
Research confirms 12 actionable findings (3 dropped — see below).

### Dropped Findings
- **#6 (get_clean wrapper)**: 55 callsites in nport.py — inlining makes code worse, not simpler. The wrapper earns its weight.
- **#14 (top-level imports)**: Style nitpick, not a real simplification.
- **#15 (SGML regex)**: SEC SGML headers are not standard HTML/XML. BeautifulSoup may not parse them correctly. Risk exceeds benefit.

### Steps

- [x] **Step 1: Clean up parser_utils.py** (implementer)
  - Delete `safe_numeric()` (lines 19-22)
  - Simplify `get_numeric()` to `return getattr(obj, attr, None)` (removing safe_numeric call)
  - Replace `parse_date()` trial-and-error with `dateutil.parser.parse()` + warning log on failure
  - Files: `src/etf_pipeline/parser_utils.py`

- [x] **Step 2: Merge _parse_money into parse_decimal** (implementer)
  - Ensure `parse_decimal()` handles all `_parse_money()` cases (it already does + more)
  - Add warning log to parse_decimal on failure (matching _parse_money behavior)
  - Replace `_parse_money()` calls in flows.py with `parse_decimal()`
  - Delete `_parse_money()` from flows.py
  - Files: `src/etf_pipeline/parser_utils.py`, `src/etf_pipeline/parsers/flows.py`

- [x] **Step 3: Replace get_numeric() calls in nport.py** (implementer)
  - Replace all 13 `get_numeric(obj, attr)` calls with `getattr(obj, attr, None)`
  - Remove `get_numeric` from imports
  - Delete `get_numeric()` and `safe_numeric()` from parser_utils.py
  - Files: `src/etf_pipeline/parsers/nport.py`, `src/etf_pipeline/parser_utils.py`

- [x] **Step 4: DRY up swap leg extraction** (implementer)
  - Refactor `_build_swap_legs()` to loop over pay/receive directions
  - Use dynamic attribute suffix for `_pay`/`_receive` fields
  - Files: `src/etf_pipeline/parsers/nport.py`

- [x] **Step 5: Unify parser dispatch maps in cli.py** (implementer)
  - Merge `PARSER_FORM_MAP` and `parser_map` into single `PARSERS` registry
  - Remove `del` statements (lines 171-172)
  - Files: `src/etf_pipeline/cli.py`

- [x] **Step 6: Move EDGAR_IDENTITY fallback to config.py** (implementer)
  - Add fallback default in config.py
  - Remove inline fallback from discover.py line 18
  - Files: `src/etf_pipeline/config.py`, `src/etf_pipeline/discover.py`

- [x] **Step 7: SQL-side CIK filtering in load_etfs.py** (implementer)
  - Replace Python-side filtering with SQL WHERE clause
  - Files: `src/etf_pipeline/load_etfs.py`

- [x] **Step 8: Fix test fixture duplication** (implementer)
  - Consolidate mock fund_info setup between conftest.py and test_nport.py
  - Trim mock_fund_report fixture to minimal attributes
  - Files: `tests/conftest.py`, `tests/test_nport.py`

- [x] **Step 9: Run tests** (tester)
  - Run full test suite, verify nothing broke
  - Files: all test files

- [x] **Step 10: Final review** (reviewer)
  - Review all changes for correctness and consistency

### Execution Strategy
- Steps 1-3 are sequential (all touch parser_utils.py)
- Steps 4, 5, 6, 7 can run in parallel after Step 3
- Step 8 after Steps 1-7 (test fixtures may need to reflect changes)
- Step 9 after Step 8
- Step 10 after Step 9

### Risks
- **parse_date change**: dateutil.parser.parse() is more permissive — could accept bad dates that were previously rejected. Mitigate with tests.
- **_parse_money removal**: flows.py tests must pass with parse_decimal. parse_decimal handles a superset so risk is low.
- **Swap leg refactor**: Complex derivative logic — must verify output is identical. Regression tests from commit 49dd99b should catch issues.

### Estimated Scope
- Files affected: 10
- Subagents needed: implementer (x4-5), tester (x1), reviewer (x1)
