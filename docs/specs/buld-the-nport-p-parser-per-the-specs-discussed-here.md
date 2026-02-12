# Spec: NPORT-P Parser

## Summary

Build two new features:
1. A `load-etfs` CLI command that loads ETF rows from `etf_tickers.json` into the database
2. An `nport` CLI command that extracts the latest holdings and derivatives from NPORT-P filings

Both commands process data one CIK at a time.

## Out of Scope

- Historical backfill (only latest filing per series)
- Alembic migrations (handled separately)
- Modifications to existing models
- Any parser other than NPORT-P
- run-all orchestration

---

## User Stories

### US-1: Load ETFs to Database

**As a** pipeline operator
**I want to** load ETF records from etf_tickers.json into the ETF table
**So that** the NPORT parser has FK targets to write against

**Implementation:**
- New file: `src/etf_pipeline/load_etfs.py`
- New CLI command: `etf-pipeline load-etfs [--cik CIK] [--limit N]`
- Reads `data/etf_tickers.json` (output of `discover` command)
- Groups entries by CIK, processes CIKs alphabetically
- For each unique CIK: calls `Company(cik).name` via edgartools to get `issuer_name`
- For each ETF entry under that CIK: upserts into ETF table
  - Match on `ticker` (unique column)
  - Insert if new; update `fund_name`, `issuer_name`, `series_id` if existing
  - `fund_name`: looked up from edgartools (Company or series-level, whatever is available)
- `--cik`: optional, process only this CIK
- `--limit N`: optional, process only the first N CIKs (alphabetical order)
- If neither flag provided, process all CIKs
- Uses Python logging: INFO for progress, WARNING for failures

**Acceptance Criteria:**
- Running `load-etfs` with a fresh DB creates ETF rows with ticker, cik, series_id, issuer_name populated
- Running `load-etfs` again does not duplicate rows; updates changed fields
- `--cik 12345` processes only ETFs for CIK 12345
- `--limit 5` processes only the first 5 CIKs alphabetically
- CIK-level errors are logged and skipped; command continues

### US-2: NPORT-P Holdings Parser

**As a** pipeline operator
**I want to** extract holdings from the latest NPORT-P filing for each ETF
**So that** the Holding table contains current portfolio data

**Implementation:**
- New file: `src/etf_pipeline/parsers/__init__.py` (empty)
- New file: `src/etf_pipeline/parsers/nport.py`
- Update CLI: wire `nport` command to call the parser
- CLI signature: `etf-pipeline nport [--cik CIK] [--limit N]`

**Processing flow per CIK:**
1. Query ETF table for all ETFs with this CIK
2. For each ETF (series), fetch its latest NPORT-P filing via edgartools
3. Check if holdings already exist for this ETF + report_date — if yes, skip
4. Call `FundReport.from_filing(filing)` to get parsed data
5. Map each holding (InvestmentOrSecurity) to a Holding model instance
6. Insert holdings into DB
7. Update `ETF.last_fetched` to current timestamp

**Field mapping (Holding):**
- Map fields from `InvestmentOrSecurity` to `Holding` model as directly as possible
- Fields: name, lei, cusip, title, balance, units, value_usd, pct_value, asset_category, issuer_category, investment_country, is_restricted_security, fair_value_level
- For isin, ticker, currency: extract from `identifiers` dict if present, otherwise NULL
- `report_date`: from the FundReport/filing object

**Acceptance Criteria:**
- Running `nport` for a CIK with 3 ETFs creates Holding rows for each ETF that has an NPORT-P filing
- Holdings have correct FK to etf.id
- Re-running for the same CIK + report_date does NOT create duplicate holdings
- ETF.last_fetched is updated after successful extraction
- CIKs with no NPORT-P filings are logged as warnings and skipped
- `--cik` and `--limit` flags work as described

### US-3: NPORT-P Derivatives Parser

**As a** pipeline operator
**I want to** extract derivatives from the latest NPORT-P filing for each ETF
**So that** the Derivative table contains current derivative positions

**Implementation:**
- Same file as US-2: `src/etf_pipeline/parsers/nport.py`
- Extracted alongside holdings in the same processing pass

**Field mapping (Derivative):**
- Map from `DerivativeInfo` sub-objects (forward_derivative, swap_derivative, future_derivative, option_derivative, swaption_derivative)
- `derivative_type`: from `derivative_category` field
- Other fields (underlying_name, underlying_cusip, notional_value, counterparty, counterparty_lei, delta, expiration_date): best-effort from whichever sub-object is populated
- `report_date`: same as holdings

**Acceptance Criteria:**
- Running `nport` for a CIK where filings contain derivatives creates Derivative rows
- Derivatives have correct FK to etf.id
- Re-running skips (same skip logic as holdings — tied to same report_date check)
- ETFs with no derivatives: no error, just zero Derivative rows

### US-4: Tests

**As a** developer
**I want** tests for load-etfs and the NPORT parser
**So that** I can verify correctness without hitting the SEC API

**Implementation:**
- `tests/test_load_etfs.py`: tests for the load-etfs module
- `tests/test_nport.py`: tests for the NPORT parser
- All tests use in-memory SQLite (existing conftest.py pattern)
- Mock `Company()` calls (for issuer_name/fund_name lookup)
- Mock edgartools filing fetches and `FundReport.from_filing()`
- Create FundReport-like mock objects that return known holdings/derivatives

**Acceptance Criteria for load-etfs tests:**
- Test: fresh load creates ETF rows with correct fields
- Test: re-running upserts (updates changed issuer_name, does not duplicate)
- Test: --cik filters to one CIK
- Test: CIK lookup failure is skipped with warning

**Acceptance Criteria for NPORT tests:**
- Test: parser creates Holding rows from mocked FundReport
- Test: parser creates Derivative rows from mocked FundReport
- Test: parser skips ETF when holdings already exist for report_date
- Test: parser updates ETF.last_fetched
- Test: parser handles CIK with no NPORT-P filing (warning, no error)
- Test: parser handles ETF with zero derivatives (no error)
- All tests pass: `pytest tests/`

---

## File Changes

| File | Action | Purpose |
|------|--------|---------|
| `src/etf_pipeline/load_etfs.py` | Create | Load ETFs from JSON to DB |
| `src/etf_pipeline/parsers/__init__.py` | Create | Empty package init |
| `src/etf_pipeline/parsers/nport.py` | Create | NPORT-P parser |
| `src/etf_pipeline/cli.py` | Modify | Wire load-etfs and nport commands |
| `tests/test_load_etfs.py` | Create | Tests for load-etfs |
| `tests/test_nport.py` | Create | Tests for NPORT parser |

---

## Technical Notes

- **edgartools API**: `Company(cik).get_filings(form="NPORT-P")` to fetch filings. `FundReport.from_filing(filing)` to parse.
- **Series matching**: Each NPORT-P filing is for one series. Match to ETF row via series_id from the filing.
- **CIK ordering**: All CIK lists sorted alphabetically for deterministic behavior.
- **Skip logic**: Before parsing a filing, check if any Holding rows exist for that `etf_id + report_date`. If yes, skip.
- **Error handling**: try/except at CIK level. Log warning, continue. Print summary count at end (X succeeded, Y skipped, Z failed).
- **Logging**: `logging.getLogger(__name__)` in each module. INFO for CIK progress, WARNING for skips/errors, DEBUG for per-holding detail.
- **Reference docs**: Before implementing field mappings, consult `docs/reference/PARSER_REFERENCE_MAP.md` and the NPORT XSD/spec files listed there.

---

## Implementation Phases

### Phase 1: load-etfs command + tests
- Create `load_etfs.py`
- Add `load-etfs` CLI command
- Write `test_load_etfs.py`
- Verify: `pytest tests/test_load_etfs.py` passes

### Phase 2: NPORT parser (holdings) + tests
- Create `parsers/nport.py` with holdings extraction
- Wire `nport` CLI command
- Write `test_nport.py` (holdings tests)
- Verify: `pytest tests/test_nport.py` passes

### Phase 3: NPORT parser (derivatives) + tests
- Add derivative extraction to `parsers/nport.py`
- Add derivative tests to `test_nport.py`
- Verify: `pytest tests/` all pass

---

## Verification

After each phase:
```
pytest tests/ -v
```

Final check — all tests pass, no regressions:
```
pytest tests/ -v --tb=short
```
