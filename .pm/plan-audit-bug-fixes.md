# PM Plan: Fix All Database Audit Bugs

## Current State
- 8 bugs identified in db-audit-report.md
- Primary file: `src/etf_pipeline/parsers/nport.py` (5 bugs)
- Secondary files: `src/etf_pipeline/models.py`, `src/etf_pipeline/parsers/nport_xml.py`, `src/etf_pipeline/parsers/ncsr.py`
- 124 existing tests in `tests/test_nport.py`
- No DB migration needed — user will delete .db file and recreate
- edgartools returns strings 'Y'/'N' for some fields, bools for others

## Steps

### Step 1: Fix security_lending boolean conversion (HIGH)
- **File**: `src/etf_pipeline/parsers/nport.py:1587-1603`
- **Agent**: implementer
- **Change**: Replace `bool(sec_lending.is_cash_collateral)` with `sec_lending.is_cash_collateral == "Y"` for all three fields (is_cash_collateral, is_non_cash_collateral, is_loan_by_fund)
- **Tests**: Update `tests/test_nport.py` security_lending tests to use string 'Y'/'N' values in mocks
- [x] Done

### Step 2: Fix derivative futures field access (HIGH)
- **File**: `src/etf_pipeline/parsers/nport.py:1312`
- **Agent**: implementer
- **Change**: `fut.currency_code` -> `fut.currency`. Remove hasattr checks for non-existent fields on lines 1320-1327 (reference_entity_balance, reference_entity_units, etc.)
- **Tests**: Update futures derivative tests to verify currency and underlying fields are populated
- [x] Done

### Step 3: Fix holding.currency extraction (HIGH)
- **File**: `src/etf_pipeline/parsers/nport.py:1128-1145`
- **Agent**: implementer
- **Change**: Prioritize `investment.currency_code` (the primary field) over `identifiers.other` dict lookup. The current order checks identifiers.other first, which is unreliable. Swap the order so `currency_code` is checked first, with identifiers.other as fallback.
- **Tests**: Add test case for holding with currency_code populated but no identifiers.other currency
- [x] Done

### Step 4: Fix debt_security_detail maturity_date extraction (HIGH)
- **File**: `src/etf_pipeline/parsers/nport.py` (debt security section ~1487-1568)
- **Agent**: implementer
- **Change**: edgartools DebtSecurity.maturity_date already populated (returns datetime from `maturityDt` XML). Verify parser correctly reads `debt_sec.maturity_date` and converts to date. If it's reading it as a string, parse it properly.
- **Tests**: Verify existing debt security tests include maturity_date assertions
- [x] Done

### Step 5: Fix debt_security_detail field name typos in model (HIGH)
- **File**: `src/etf_pipeline/models.py:294-317`
- **Agent**: implementer
- **Changes**:
  - Model field `is_contingent_convertible` is already correct in the model (line ~313)
  - Parser accesses `debt_sec.is_continuing_convertible` (edgartools field name) but should map it to model field `is_contingent_convertible` — verify this mapping is correct
  - Model field for arrears: verify name matches between model and edgartools (`are_instrument_payents_in_arrears` has typo "payents" in edgartools too — check if model uses the same typo or the corrected spelling)
  - Fix the model column name `are_instrument_payents_in_arrears` -> `are_instrument_payments_in_arrears` (no migration needed, user deletes DB)
  - Update parser to map from edgartools `are_instrument_payents_in_arrears` to model `are_instrument_payments_in_arrears`
- **Tests**: Update test mocks to use correct field names
- [x] Done

### Step 6: Fix borrower_name and liquidity_classification (MEDIUM)
- **File**: `src/etf_pipeline/parsers/nport_xml.py` and `src/etf_pipeline/parsers/nport.py:1182-1213`
- **Agent**: implementer
- **Change**: First investigate `nport_xml.py` to see if `parse_nport_investments_xml()` actually extracts these fields. If it does, fix the key matching. If not, implement extraction from the raw NPORT XML (these fields are in `<securityLending>` and `<liquidityClassification>` XML elements). Reference NPORT XSD for field locations.
- **Tests**: Add tests for borrower_name and liquidity_classification extraction
- [x] Done

### Step 7: Investigate and fix performance benchmark/expense fields (MEDIUM)
- **File**: `src/etf_pipeline/parsers/ncsr.py:237-416`
- **Agent**: diagnostician first, then implementer if fixable
- **Change**: The parser code for benchmark/expense exists but produces NULL for all 44 rows. Need to diagnose why:
  - Are the XBRL concept names correct? (oef:ExpenseRatioPct, us-gaap:InvestmentCompanyPortfolioTurnover)
  - Is the BroadBasedIndexAxis filter working?
  - Is the DataFrame empty at the point of extraction?
  - This may be a data availability issue (Vanguard N-CSR filings may not contain these XBRL facts)
- **Tests**: If fix found, add tests
- [x] Done

### Step 8: Run all tests and review
- **Agent**: tester, then reviewer
- **Change**: Run full test suite, fix any failures
- [x] Done

## Execution Strategy
- **Parallel batch 1**: Steps 1, 2, 3, 4, 5 (all independent NPORT parser fixes in nport.py — but since they touch the same file, run sequentially to avoid conflicts)
- **Parallel batch 2**: Steps 6 and 7 (independent parsers: nport_xml.py and ncsr.py)
- **Sequential**: Step 8 after all fixes

Actually, since all of steps 1-5 touch nport.py, they must be done sequentially by a single implementer agent to avoid edit conflicts. Steps 6 and 7 can run in parallel with each other but after steps 1-5 (step 6 also touches nport.py).

**Revised execution order**:
1. Single implementer agent for Steps 1-5 (all nport.py + models.py changes)
2. After Step 5: Steps 6 and 7 in parallel
3. Step 8: Test and review

## Risks
- Steps 1-5 all touch nport.py — must be done by one agent to avoid conflicts
- edgartools DebtSecurity.maturity_date may return datetime or string "N/A" — need to handle both
- borrower_name/liquidity_classification may not be in edgartools FundReport at all — may need raw XML parsing
- N-CSR benchmark fields may genuinely not exist in Vanguard filings — may need to mark as EXPECTED, not BUG

## Estimated Scope
- Files affected: 4 (nport.py, models.py, nport_xml.py, ncsr.py) + test files
- Subagents needed: implementer (x2-3), diagnostician (x1), tester (x1), reviewer (x1)
