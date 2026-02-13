# Specification: N-CSR Parser

## Overview

Parse N-CSR/N-CSRS performance data from iXBRL-tagged filings and populate the `Performance` table. Uses edgartools `filing.xbrl().facts.to_dataframe()` to extract structured XBRL facts from inline XBRL filings. Facts are filtered by OEF taxonomy concepts and dimensional contexts (`ClassAxis`, `BroadBasedIndexAxis`) to extract per-ETF performance metrics.

## Problem Statement

The `Performance` table exists in the schema but has no parser to populate it. N-CSR filings contain annual/semi-annual performance data (returns, expense ratios, portfolio turnover, benchmark comparisons) tagged with iXBRL using the OEF (Open-End Fund) taxonomy. edgartools can parse these iXBRL filings via `filing.xbrl()`, returning a structured `XBRL` object with a `FactsView` that converts to a pandas DataFrame.

## Data Source — Verified

**Confirmed working** (tested on iShares Trust CIK 0001100663, filing date 2026-01-06):

```python
from edgar import Company
c = Company('0001100663')
f = c.get_filings(form='N-CSR')[0]  # latest N-CSR filing
x = f.xbrl()                         # returns XBRL object (3,229 facts, 1,801 contexts)
df = x.facts.to_dataframe()          # DataFrame with 37 columns
```

**DataFrame columns include:**
- `concept` — e.g., `oef:AvgAnnlRtrPct`, `oef:ExpenseRatioPct`, `us-gaap:InvestmentCompanyPortfolioTurnover`
- `numeric_value` — the actual value
- `period_start`, `period_end` — XBRL context period dates
- `dim_oef_ClassAxis` — class ID dimension (e.g., `ist:C000131291Member`)
- `dim_oef_BroadBasedIndexAxis` — benchmark dimension (e.g., `ist:BloombergUSUniversalIndexMember`)

**Key finding:** The XBRL data identifies funds by **class ID** (C000...) via `ClassAxis`, not by series ID. The ETF table currently stores `series_id` but not `class_id`. Since class_id has a strict 1:1 mapping to ticker/ETF (verified: 28,113 unique class IDs = 28,113 unique symbols in SEC data), we need to add `class_id` to the ETF table.

**NOT working:** The Company Facts API (`/api/xbrl/companyfacts/`) does NOT contain OEF taxonomy data — only `dei` and `us-gaap`. The XBRL Frames API also returns 404 for OEF concepts. The correct approach is per-filing `filing.xbrl()`.

## Scope

### In Scope
- Add `class_id` column to ETF model, discover.py, and load_etfs.py
- Parse 6 core fields: `return_1yr`, `return_5yr`, `return_10yr`, `return_since_inception`, `portfolio_turnover`, `expense_ratio_actual`
- Parse 4 benchmark fields: `benchmark_name`, `benchmark_return_1yr`, `benchmark_return_5yr`, `benchmark_return_10yr`
- Per-ETF data via `ClassAxis` dimension filtering (maps class_id to ETF records)
- Latest N-CSR filing only per CIK
- Upsert logic on `(etf_id, fiscal_year_end)` unique constraint
- CLI command: `etf-pipeline ncsr [--cik CIK] [--limit N] [--keep-cache]`
- Entry point: `parse_ncsr(cik=None, ciks=None, limit=None, clear_cache=True)`
- Add `ciks` param to `parse_nport()` for interface consistency (ALREADY DONE)

### Out of Scope
- Distribution fields (`distribution_total`, `dist_ordinary_income`, etc.) — not in OEF XBRL taxonomy
- Historical backfill (multiple fiscal years per ETF)
- `run-all` pipeline orchestration
- Prospectus (485BPOS) parser

## User Stories

### US-1: Add `ciks` parameter to `parse_nport()` for interface consistency
**Status: COMPLETE** (committed in Phase 1 of previous Ralph run)

### US-2: Add `class_id` to ETF table and discovery pipeline
**Description:** As a pipeline developer, I want the ETF table to store `class_id` so that N-CSR XBRL data (which identifies funds by ClassAxis/class_id) can be mapped to ETF records.

**Acceptance Criteria:**
- [ ] `class_id` column added to ETF model (String(20), nullable, indexed)
- [ ] `discover.py` includes `class_id` in the output JSON (from SEC's `classId` field)
- [ ] `load_etfs.py` passes `class_id` through to the ETF upsert
- [ ] SCHEMA.md updated with new column
- [ ] All existing tests pass
- [ ] New test verifying class_id is stored correctly

### US-3: Core N-CSR parser — returns, expense ratio, portfolio turnover
**Description:** As a pipeline operator, I want to extract per-ETF performance returns, expense ratio, and portfolio turnover from N-CSR iXBRL filings so that the Performance table is populated.

**Acceptance Criteria:**
- [ ] `parse_ncsr()` accepts `(cik=None, ciks=None, limit=None, clear_cache=True)`
- [ ] For each CIK, fetches latest N-CSR filing via `Company(cik).get_filings(form="N-CSR")[0]`
- [ ] Calls `filing.xbrl().facts.to_dataframe()` to get structured facts
- [ ] Filters for concepts: `oef:AvgAnnlRtrPct`, `oef:ExpenseRatioPct`, `us-gaap:InvestmentCompanyPortfolioTurnover`
- [ ] Filters by `dim_oef_ClassAxis` to extract per-ETF data
- [ ] Maps class_id from `ClassAxis` dimension (strip prefix and `Member` suffix) to ETF records via `ETF.class_id`
- [ ] Determines return period (1yr/5yr/10yr/inception) from period_start/period_end using year-difference with +/- 30 day tolerance
- [ ] Upserts into Performance table on `(etf_id, fiscal_year_end)` unique constraint
- [ ] Warns and skips class_ids that don't match any ETF in database
- [ ] Prints summary: "X ETFs succeeded, Y ETFs failed"
- [ ] Clears edgartools cache after processing (unless `clear_cache=False`)
- [ ] Test uses saved fixture data in `tests/fixtures/`

### US-4: Benchmark data extraction
**Description:** As a pipeline operator, I want benchmark names and returns extracted alongside fund returns.

**Acceptance Criteria:**
- [ ] Extracts `benchmark_name` from `dim_oef_BroadBasedIndexAxis` member name (stored as raw member name)
- [ ] Extracts benchmark returns (1yr/5yr/10yr) from `oef:AvgAnnlRtrPct` facts that have non-NaN `dim_oef_BroadBasedIndexAxis`
- [ ] Distinguishes fund returns (NaN BroadBasedIndexAxis) from benchmark returns (non-NaN BroadBasedIndexAxis)
- [ ] If multiple benchmarks exist, uses the first one
- [ ] If no benchmark data exists, leaves fields NULL
- [ ] Test verifies benchmark extraction from fixture data

### US-5: CLI integration
**Description:** As a pipeline operator, I want to run the N-CSR parser from the command line.

**Acceptance Criteria:**
- [ ] `etf-pipeline ncsr` command calls `parse_ncsr()` with no args
- [ ] `--cik CIK` flag filters to single CIK
- [ ] `--limit N` flag limits to first N CIKs
- [ ] `--keep-cache` flag prevents cache clearing
- [ ] Logging configured at INFO level
- [ ] Replaces the current stub

## Technical Design

### Data Source
- **Method:** `filing.xbrl().facts.to_dataframe()` on individual N-CSR filings
- **One filing per CIK** (latest N-CSR), which covers all ETF series in that trust
- **Requirement:** Filing must have `is_inline_xbrl=True` (post-2024 filings)

### XBRL Concepts to Extract

| Concept | Taxonomy | Maps to |
|---------|----------|---------|
| `oef:AvgAnnlRtrPct` | oef-2025 | `return_1yr`, `return_5yr`, `return_10yr`, `return_since_inception`, `benchmark_return_*` |
| `oef:ExpenseRatioPct` | oef-2025 | `expense_ratio_actual` |
| `us-gaap:InvestmentCompanyPortfolioTurnover` | us-gaap | `portfolio_turnover` |

### Dimension Mapping

**ETF identification via ClassAxis:**
- DataFrame column: `dim_oef_ClassAxis`
- Values look like: `ist:C000131291Member`
- Extract class_id: strip namespace prefix and `Member` suffix → `C000131291`
- Look up ETF by `ETF.class_id == 'C000131291'`

**Return period mapping from context dates:**
- `period_start` and `period_end` columns encode the return period
- Calculate year difference: `(period_end - period_start).days / 365.25`
- ~1 year (+/- 30 days) → `return_1yr`
- ~5 years (+/- 30 days) → `return_5yr`
- ~10 years (+/- 30 days) → `return_10yr`
- Anything else → `return_since_inception`

**Benchmark identification via BroadBasedIndexAxis:**
- DataFrame column: `dim_oef_BroadBasedIndexAxis`
- NaN = fund return, non-NaN = benchmark return
- Store raw member name as `benchmark_name`

### Processing Flow

```
1. Get CIK list (from ETF table or --cik/--limit args)
2. For each CIK:
   a. Fetch latest N-CSR filing: Company(cik).get_filings(form="N-CSR")[0]
   b. Skip if not is_inline_xbrl
   c. Get DataFrame: filing.xbrl().facts.to_dataframe()
   d. Filter for target concepts
   e. Build class_id -> ETF lookup from database
   f. For each unique class_id in dim_oef_ClassAxis:
      - Look up ETF by class_id
      - If not found, warn and skip
      - fiscal_year_end = period_end from the facts
      - Extract fund returns by period mapping (where BroadBasedIndexAxis is NaN)
      - Extract benchmark returns (where BroadBasedIndexAxis is not NaN)
      - Extract expense ratio and portfolio turnover
      - Upsert Performance row
   g. Commit
3. Print summary
4. Clear cache (if enabled)
```

### File Layout
- `src/etf_pipeline/parsers/ncsr.py` — main parser module
- `tests/test_ncsr.py` — tests
- `tests/fixtures/` — test fixture directory (trimmed XBRL DataFrames)

### Entry Point Signature
```python
def parse_ncsr(
    cik: Optional[str] = None,
    ciks: Optional[list[str]] = None,
    limit: Optional[int] = None,
    clear_cache: bool = True,
) -> None:
```

## Edge Cases

1. **CIK has no N-CSR filings:** `get_filings()` returns empty — log warning, skip CIK
2. **Filing is not iXBRL:** Old filings (pre-2024) lack inline XBRL — skip with warning
3. **`filing.xbrl()` returns None:** Some filings may fail to parse — skip with warning
4. **No OEF concepts in DataFrame:** Filing may not have performance data — skip CIK
5. **Class_id in XBRL not in ETF table:** Expected for mutual fund classes — warn and skip
6. **Missing return periods:** Fund too young for 10yr returns — leave NULL
7. **No benchmark data:** Leave benchmark_* fields NULL
8. **Multiple N-CSR filings on same date:** Use the first one returned

## Implementation Phases

### Phase 1: NPORT consistency fix — COMPLETE
- [x] Add `ciks` parameter to `parse_nport()` signature
- [x] Tests pass
- **Status:** Already committed

### Phase 2: Add `class_id` to ETF table
- [ ] Add `class_id` column to ETF model in `models.py` (String(20), nullable, indexed)
- [ ] Update `discover.py` to include `class_id` from SEC's `classId` field
- [ ] Update `load_etfs.py` `_upsert_etf()` to store `class_id`
- [ ] Update `SCHEMA.md` with new column
- [ ] Update existing tests if needed
- [ ] Add test for class_id storage
- **Verification:** `python -m pytest tests/ -v`

### Phase 3: Core N-CSR parser (returns + expense + turnover)
- [ ] Create `src/etf_pipeline/parsers/ncsr.py`
- [ ] Implement `parse_ncsr()` with CIK iteration, filing fetch, xbrl() parsing
- [ ] Implement DataFrame filtering for OEF concepts
- [ ] Implement `ClassAxis` dimension parsing for per-ETF extraction
- [ ] Implement period-based return mapping (1yr/5yr/10yr/inception)
- [ ] Implement upsert logic
- [ ] Create test fixtures in `tests/fixtures/`
- [ ] Create `tests/test_ncsr.py` with fixture-based tests
- **Verification:** `python -m pytest tests/test_ncsr.py -v`

### Phase 4: Benchmark extraction
- [ ] Add `BroadBasedIndexAxis` filtering to distinguish fund vs benchmark returns
- [ ] Extract benchmark_name from axis member value
- [ ] Map benchmark returns to benchmark_return_1yr/5yr/10yr
- [ ] Add benchmark-specific tests
- **Verification:** `python -m pytest tests/test_ncsr.py -v`

### Phase 5: CLI integration
- [ ] Wire `parse_ncsr()` into `cli.py` ncsr command (replace stub)
- [ ] Add `--cik`, `--limit`, `--keep-cache` flags
- [ ] Configure logging at INFO level
- **Verification:** `python -m pytest tests/ -v`

## Definition of Done

This feature is complete when:
- [ ] All acceptance criteria in user stories pass
- [ ] All implementation phases verified
- [ ] Tests pass: `python -m pytest tests/ -v`
- [ ] `class_id` stored in ETF table
- [ ] `parse_ncsr()` has consistent interface with `parse_flows()`
- [ ] No distribution fields populated (explicitly out of scope)

## Ralph Loop Command

```bash
/ralph "Implement N-CSR parser per spec at docs/specs/ncsr-parser.md

PHASES (Phase 1 already complete — start from Phase 2):
2. class_id: Add class_id column to ETF model, discover.py, load_etfs.py, SCHEMA.md - verify with pytest tests/ -v
3. Core parser: Create ncsr.py using filing.xbrl().facts.to_dataframe(), ClassAxis dimension parsing, period mapping, upsert - verify with pytest tests/test_ncsr.py -v
4. Benchmarks: Add BroadBasedIndexAxis parsing for benchmark data - verify with pytest tests/test_ncsr.py -v
5. CLI: Wire ncsr command in cli.py replacing stub - verify with pytest tests/ -v

DO NOT use Company.get_facts() or the Company Facts API — it does not contain OEF data.
USE filing.xbrl().facts.to_dataframe() on individual N-CSR filings instead.

REFERENCE DOCS: Read docs/reference/PARSER_REFERENCE_MAP.md for N-CSR section.

VERIFICATION (run after each phase):
- python -m pytest tests/ -v

ESCAPE HATCH: After 20 iterations without progress:
- Document what is blocking in the spec file under Implementation Notes
- List approaches attempted
- Stop and ask for human guidance

Output RALPH_COMPLETE when all phases pass verification."
```

## Open Questions
*None — all decisions made during interview and subsequent research.*

## Implementation Notes

### Data Source Correction (2026-02-13)
The original spec assumed the Company Facts API contained OEF taxonomy data. Testing confirmed it does NOT — only `dei` and `us-gaap` taxonomies. The correct approach is `filing.xbrl().facts.to_dataframe()` on individual N-CSR filings, which successfully returns OEF-tagged performance data with dimensional contexts. Verified on iShares Trust (CIK 0001100663) returning 459 OEF performance facts.
