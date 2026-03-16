## PM Plan: Remove all liquidity-related code — COMPLETE

### Current State
Liquidity classification is an SEC requirement for mutual funds only. ETFs are exempt under Rule 22e-4.
All 1.2M holdings across 3,997 ETFs have NULL liquidity_classification. The column, parser, API logic,
and frontend card are dead code. User has confirmed mutual fund support will never be added.

### Steps

- [x] Step 1: Delete liquidity-only files (implementer)
  - Deleted `frontend/src/components/cards/LiquidityCard.tsx`
  - Deleted `src/etf_pipeline/parsers/nport_xml.py`

- [x] Step 2: Clean up frontend references (implementer)
  - Edited `frontend/src/pages/XRay.tsx` — removed LiquidityCard import and usage
  - Edited `frontend/src/lib/api.ts` — removed LiquidityItem, LiquidityData interfaces and liquidity fields

- [x] Step 3: Clean up API layer (implementer)
  - Edited `src/etf_pipeline/api/routes/xray.py` — removed liquidity imports, aggregation block, and response fields
  - Edited `src/etf_pipeline/api/schemas/xray.py` — removed LiquidityItem, LiquidityData classes and liquidity fields
  - Edited `src/etf_pipeline/xray/service.py` — removed LIQUIDITY_MAP constant

- [x] Step 4: Clean up data model and parser (implementer)
  - Edited `src/etf_pipeline/models.py` — removed liquidity_classification from Holding, liquidity_pref from FundSnapshot
  - Edited `src/etf_pipeline/parsers/nport.py` — removed nport_xml import, xml_custom_fields parameter, liquidity lookup code

- [x] Step 5: Create database migration (implementer)
  - Created `alembic/versions/a09ef8f45a40_remove_liquidity_columns.py`

- [x] Step 6: Fix tests (tester)
  - Deleted `tests/test_nport_xml.py`
  - Edited `tests/test_nport.py` — removed liquidity mocks, assertions, renamed helper
  - Edited `tests/conftest.py` — removed liquidity_pref from mock setup
  - Edited `tests/test_parsers/test_nport_fund_snapshot.py` — removed liquidity_pref

- [x] Step 7: Update documentation (implementer)
  - Edited `docs/xray-report.md` — removed liquidity sections, renumbered
  - Edited `docs/reference/SCHEMA.md` — removed liquidity column descriptions

- [x] Step 8: Run full test suite (tester) — 440 passed, 0 failed

- [x] Step 9: Final review (reviewer) — PASS, no issues found
