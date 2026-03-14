## PM Plan: Fix All 14 Pre-Pipeline-Run Issues — COMPLETE

### Current State
- 11 Alembic migrations exist; head is b1c2d3e4f5a6, c2d3e4f5a6b7 is pending
- Pipeline uses SQLite with edgartools for NPORT-P parsing
- 378 tests passing
- Database will be wiped before next pipeline run (fresh start)

### Steps

#### Group A — Derivative NULL Constraint Fix (HIGH)
- [x] Step 1: Add sentinel values for derivative nullable constraint columns
  - File: `src/etf_pipeline/parsers/nport.py`
  - Change `_map_investment_to_derivative` to use `""` (empty string) for underlying_name when None, `""` for counterparty when None
  - Change `expiration_date` to sentinel `9999-12-31` when None
  - Update in-memory `deriv_key` to match (already uses these fields)
  - Subagent: implementer

- [x] Step 2: Update derivative model — make constraint columns non-nullable with defaults
  - File: `src/etf_pipeline/models.py`
  - `underlying_name`: change from Optional[str] to str, server_default=""
  - `counterparty`: change from Optional[str] to str, server_default=""
  - `expiration_date`: keep Optional but use sentinel in parser
  - Subagent: implementer

#### Group B — Migration Safety (HIGH)
- [x] Step 3: Add dedup guard to migration c2d3e4f5a6b7
  - File: `alembic/versions/c2d3e4f5a6b7_remove_null_columns_from_unique_constraints.py`
  - Before creating tighter constraints, run DELETE to remove duplicate rows
  - For holdings: keep row with max(id) per (etf_id, report_date, holding_key, filing_date)
  - For monthly_flow: keep row with max(id) per (etf_id, report_date, filing_date)
  - Subagent: implementer

#### Group C — Amendment Handling (HIGH)
- [x] Step 4: Allow amendments to overwrite original holdings
  - File: `src/etf_pipeline/parsers/nport.py`
  - In the existing-holdings check, when a newer filing_date exists for the same report_date, delete old holdings and re-process
  - Modify the `existing_etf_ids` check to compare filing_dates, not just existence
  - Subagent: implementer

#### Group D — Cash Double-Counting (MEDIUM)
- [x] Step 5: Fix cash double-counting in asset allocation
  - File: `src/etf_pipeline/api/routes/xray.py`
  - Only add CASH row from snapshot if no STIV holdings exist in the allocation
  - OR: merge STIV and CASH into a single "Cash & Equivalents" bucket
  - Decision: merge approach is cleaner — rename STIV display to "Cash & Equivalents" and add snapshot cash to that bucket
  - Subagent: implementer

#### Group E — Holding Key Collision (MEDIUM)
- [x] Step 6: Improve fallback holding_key to include more differentiators
  - File: `src/etf_pipeline/parsers/nport.py`
  - Add name (even partial), asset_category, and country to the hash input
  - Include a counter for same-hash collisions within the same ETF
  - Subagent: implementer

#### Group F — Fund Snapshot UIT Dedup (MEDIUM)
- [x] Step 7: Use empty string sentinel for fund_snapshot.series_id instead of NULL
  - File: `src/etf_pipeline/parsers/nport.py` — change `series_id=None` to `series_id=""` for UITs
  - File: `src/etf_pipeline/models.py` — make series_id non-nullable with default ""
  - File: `src/etf_pipeline/xray/service.py` — update get_fund_snapshot query to handle ""
  - File: `src/etf_pipeline/api/routes/xray.py` — pass "" instead of None for UITs
  - Subagent: implementer

#### Group G — FK Enforcement in Production (MEDIUM)
- [x] Step 8: Enable PRAGMA foreign_keys in production get_engine()
  - File: `src/etf_pipeline/db.py`
  - Call enable_sqlite_fks on the engine returned by get_engine()
  - Subagent: implementer

#### Group H — Processing Log Partial-Success (MEDIUM)
- [x] Step 9: Track latest_filing_date only for successfully processed ETFs
  - File: `src/etf_pipeline/parsers/nport.py`
  - In normal mode, only include filing_dates from ETFs that were actually committed
  - Track a per-ETF success list and derive latest_filing_date from successes only
  - Subagent: implementer

#### Group I — Geographic Unknown Bucket (LOW)
- [x] Step 10: Add "Unknown" bucket for holdings with no country
  - File: `src/etf_pipeline/api/routes/xray.py`
  - When h.country is None, group under "XX" (standard unknown code)
  - Subagent: implementer

#### Group J — Asset Allocation Normalization (LOW)
- [x] Step 11: Add "Unallocated" row when pct_val sum < 95%
  - File: `src/etf_pipeline/api/routes/xray.py`
  - After building allocation_items, compute total. If < 95%, add an "Unallocated" item
  - Subagent: implementer

#### Group K — Orphaned Derivative Rows (LOW)
- [x] Step 12: Add savepoint around derivative child-build
  - File: `src/etf_pipeline/parsers/nport.py`
  - Use session.begin_nested() before flush, rollback to savepoint on child failure
  - Subagent: implementer

#### Group L — Misc Cleanup (LOW)
- [x] Step 13: Fix NPORTMonthlyReturn precision + mark is_active dead code
  - File: `src/etf_pipeline/models.py` — change Numeric(24,2) to Numeric(10,6) for return columns
  - Note: is_active wiring is out of scope (requires load_etfs changes beyond scope lock)
  - Subagent: implementer

#### Group M — Alembic Migration + Tests + Review
- [x] Step 14: Create Alembic migration for all model changes (Steps 1-2, 7, 13)
  - File: `alembic/versions/d3e4f5a6b7c8_fix_nullable_constraints_and_precision.py`
  - Derivative: make underlying_name/counterparty non-nullable, backfill NULLs to ""
  - FundSnapshot: make series_id non-nullable, backfill NULLs to ""
  - NPORTMonthlyReturn: change return column precision
  - Must use SQLite batch mode
  - Subagent: implementer

- [x] Step 15: Write/update tests for all changes (389 total, all passing)
  - Files: `tests/test_nport.py`, `tests/test_xray/*.py`, `tests/test_api/*.py`
  - Subagent: tester

- [x] Step 16: Final review — PASS (3 issues found and fixed)
  - Subagent: reviewer

### Execution Strategy
- **Parallel Group 1** (Steps 1-2): Derivative sentinel + model changes
- **Parallel Group 2** (Steps 3-4): Migration safety + amendment handling
- **Parallel Group 3** (Steps 5-6): Cash fix + holding key fix
- **Sequential**: Step 7 depends on model understanding from Step 2
- **Parallel Group 4** (Steps 8-9): FK enforcement + processing log
- **Parallel Group 5** (Steps 10-12): Geographic + allocation + savepoint
- **Sequential**: Step 13 after model changes settle
- **Sequential**: Step 14 (migration) after ALL model changes
- **Sequential**: Step 15 (tests) after all code changes
- **Sequential**: Step 16 (review) last

### Risks
- Derivative sentinel values change query semantics (must update any code that checks `is None`)
- Amendment overwrite deletes existing data — must be careful with cascades
- series_id="" vs None changes service layer queries
- Migration on populated DB needs careful ordering (dedup before constraint tightening)
- Since DB will be wiped, migration data guards are safety nets only

### Estimated Scope
- Files affected: ~8 source files + 1-2 migration files + 3-4 test files
- Subagents needed: implementer (x8-10), tester (x1), reviewer (x1)
