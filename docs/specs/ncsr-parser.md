# Specification: N-CSR Parser

## Overview

Parse N-CSR/N-CSRS performance data from the SEC EDGAR XBRL company facts API and populate the `Performance` table. Uses `edgartools` `Company.get_facts().to_pandas()` to retrieve structured XBRL facts, filtered by OEF taxonomy concepts and dimensional contexts to extract per-ETF (per-series) performance metrics.

## Problem Statement

The `Performance` table exists in the schema but has no parser to populate it. N-CSR filings contain annual/semi-annual performance data (returns, expense ratios, portfolio turnover, benchmark comparisons) that is tagged with iXBRL using the OEF (Open-End Fund) taxonomy. The EDGAR XBRL company facts API pre-extracts these tagged values into structured JSON.

## Scope

### In Scope
- Parse 6 core fields: `return_1yr`, `return_5yr`, `return_10yr`, `return_since_inception`, `portfolio_turnover`, `expense_ratio_actual`
- Parse 4 benchmark fields: `benchmark_name`, `benchmark_return_1yr`, `benchmark_return_5yr`, `benchmark_return_10yr`
- Per-ETF data via `LegalEntityAxis` dimension filtering (maps series_id to ETF records)
- Latest fiscal year only per ETF
- Upsert logic on `(etf_id, fiscal_year_end)` unique constraint
- CLI command: `etf-pipeline ncsr [--cik CIK] [--limit N] [--keep-cache]`
- Entry point: `parse_ncsr(cik=None, ciks=None, limit=None, clear_cache=True)`
- Add `ciks` param to `parse_nport()` for interface consistency
- Test fixtures from saved JSON snapshot in `tests/fixtures/`

### Out of Scope
- Distribution fields (`distribution_total`, `dist_ordinary_income`, `dist_qualified_dividend`, `dist_ltcg`, `dist_stcg`, `dist_return_of_capital`) — not in OEF XBRL taxonomy, would require iXBRL HTML parsing
- Historical backfill (multiple fiscal years per ETF)
- `run-all` pipeline orchestration
- Prospectus (485BPOS) parser

## User Stories

### US-1: Add `ciks` parameter to `parse_nport()` for interface consistency
**Description:** As a pipeline developer, I want all parsers to have the same function signature so that `run-all` can call them uniformly.

**Acceptance Criteria:**
- [ ] `parse_nport()` accepts `ciks: Optional[list[str]] = None` parameter
- [ ] When `ciks` is provided, only those CIKs are processed (overrides `cik` param)
- [ ] Existing behavior unchanged when `ciks` is not provided
- [ ] All existing NPORT tests pass
- [ ] New test verifying `ciks` param works

### US-2: Core N-CSR parser — returns, expense ratio, portfolio turnover
**Description:** As a pipeline operator, I want to extract per-ETF performance returns, expense ratio, and portfolio turnover from the EDGAR company facts API so that the Performance table is populated with core metrics.

**Acceptance Criteria:**
- [ ] `parse_ncsr()` accepts `(cik=None, ciks=None, limit=None, clear_cache=True)`
- [ ] Calls `Company(cik).get_facts().to_pandas()` for each CIK
- [ ] Filters DataFrame for OEF taxonomy concepts: `AvgAnnlRtrPct`, `PortfolioTurnoverRate` (or `InvestmentCompanyPortfolioTurnover`), `ExpenseRatioPct`
- [ ] Filters by `LegalEntityAxis` dimension to extract per-series data
- [ ] Maps series_id from XBRL dimensions to ETF records in database
- [ ] Determines return period (1yr/5yr/10yr/inception) from XBRL context period dates using year-difference with +/- 30 day tolerance
- [ ] Only stores the latest fiscal year per ETF
- [ ] Upserts into Performance table on `(etf_id, fiscal_year_end)` unique constraint
- [ ] Warns and skips series_ids that don't match any ETF in database (expected for mutual fund series)
- [ ] Prints summary: "X ETFs succeeded, Y ETFs failed"
- [ ] Clears edgartools cache after processing (unless `clear_cache=False`)
- [ ] Test uses saved JSON snapshot fixture from `tests/fixtures/`

### US-3: Benchmark data extraction
**Description:** As a pipeline operator, I want benchmark names and returns extracted alongside fund returns so that Performance rows include comparison data.

**Acceptance Criteria:**
- [ ] Extracts `benchmark_name` from `BroadBasedIndexAxis` dimension member name (stored as raw member name, e.g., `StandardPoors500IndexMember`)
- [ ] Extracts benchmark returns (1yr/5yr/10yr) from `AvgAnnlRtrPct` facts that have `BroadBasedIndexAxis` dimension
- [ ] Distinguishes fund returns (no `BroadBasedIndexAxis`) from benchmark returns (with `BroadBasedIndexAxis`)
- [ ] If multiple benchmarks exist, uses the first `BroadBasedIndexAxis` member
- [ ] If no benchmark data exists, leaves fields NULL
- [ ] Test verifies benchmark extraction from fixture data

### US-4: CLI integration
**Description:** As a pipeline operator, I want to run the N-CSR parser from the command line with the same flags as other parsers.

**Acceptance Criteria:**
- [ ] `etf-pipeline ncsr` command calls `parse_ncsr()` with no args
- [ ] `--cik CIK` flag filters to single CIK
- [ ] `--limit N` flag limits to first N CIKs
- [ ] `--keep-cache` flag prevents cache clearing
- [ ] Logging configured at INFO level (same as nport/flows)
- [ ] Replaces the current stub with working implementation

## Technical Design

### Data Source
- **API:** `https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json`
- **edgartools wrapper:** `Company(cik).get_facts().to_pandas()` returns a DataFrame
- **One call per CIK** — covers all series (ETFs) in that trust

### XBRL Concepts to Extract

| Concept | Taxonomy | Maps to |
|---------|----------|---------|
| `AvgAnnlRtrPct` | oef-2025 | `return_1yr`, `return_5yr`, `return_10yr`, `return_since_inception`, `benchmark_return_1yr/5yr/10yr` |
| `PortfolioTurnoverRate` | oef-2025 | `portfolio_turnover` |
| `ExpenseRatioPct` | oef-2025 | `expense_ratio_actual` |
| `PerfInceptionDate` | oef-2025 | Used to identify since-inception returns |

### Dimension Parsing

**Series identification:** Facts include `LegalEntityAxis` dimension with member values like `S000047440Member`. Strip the `Member` suffix to get the series_id, then look up ETF by `series_id` in the database.

**Return period mapping:** `AvgAnnlRtrPct` facts have XBRL context periods (start_date, end_date). Calculate year difference:
- ~1 year (+/- 30 days) → `return_1yr`
- ~5 years (+/- 30 days) → `return_5yr`
- ~10 years (+/- 30 days) → `return_10yr`
- Anything else → `return_since_inception`

**Benchmark vs. fund returns:** `AvgAnnlRtrPct` facts with `BroadBasedIndexAxis` dimension are benchmark returns. Those without are fund returns.

**Benchmark name:** The `BroadBasedIndexAxis` member value (e.g., `StandardPoors500IndexMember`) is stored as-is in `benchmark_name`.

### Processing Flow

```
1. Get CIK list (from ETF table or --cik/--limit args)
2. For each CIK:
   a. Call Company(cik).get_facts().to_pandas()
   b. Filter DataFrame for OEF concepts (AvgAnnlRtrPct, PortfolioTurnoverRate, ExpenseRatioPct)
   c. Group facts by LegalEntityAxis member (series_id)
   d. For each series_id:
      - Look up ETF by series_id in database
      - If not found, warn and skip
      - Find the latest fiscal_year_end from the facts
      - Extract return values by period mapping
      - Extract benchmark values via BroadBasedIndexAxis
      - Extract expense ratio and portfolio turnover
      - Upsert Performance row
   e. Commit
3. Print summary
4. Clear cache (if enabled)
```

### File Layout
- `src/etf_pipeline/parsers/ncsr.py` — main parser module
- `tests/test_ncsr.py` — tests
- `tests/fixtures/company_facts_sample.json` — trimmed API response fixture

### Entry Point Signature
```python
def parse_ncsr(
    cik: Optional[str] = None,
    ciks: Optional[list[str]] = None,
    limit: Optional[int] = None,
    clear_cache: bool = True,
) -> None:
```

### Database Interaction
- Read: `SELECT etf.id, etf.series_id, etf.cik FROM etf WHERE cik = :cik`
- Upsert: Check for existing `Performance` row by `(etf_id, fiscal_year_end)`, update if exists, insert if new
- Same session/commit pattern as flows parser

## Edge Cases

1. **CIK has no XBRL facts:** `get_facts()` returns None — log warning, skip CIK
2. **No OEF taxonomy concepts in facts:** DataFrame filter returns empty — log warning, skip CIK
3. **Series in XBRL not in ETF table:** Expected for mutual fund series — warn and skip
4. **ETF in database has no matching XBRL series:** The CIK may not have N-CSR filings — warn and skip
5. **Multiple fiscal year ends in data:** Only use the latest one per ETF
6. **Missing return periods:** Some ETFs won't have 10yr returns (fund too young) — leave NULL
7. **No benchmark data:** Leave benchmark_* fields NULL

## Implementation Phases

### Phase 1: NPORT consistency fix
- [ ] Add `ciks` parameter to `parse_nport()` signature
- [ ] Add test for `ciks` param
- **Verification:** `python -m pytest tests/test_nport.py -v`

### Phase 2: Core N-CSR parser (returns + expense + turnover)
- [ ] Create `src/etf_pipeline/parsers/ncsr.py`
- [ ] Implement `parse_ncsr()` with CIK iteration and company facts API
- [ ] Implement DataFrame filtering for OEF concepts
- [ ] Implement `LegalEntityAxis` dimension parsing for per-series extraction
- [ ] Implement period-based return mapping (1yr/5yr/10yr/inception)
- [ ] Implement upsert logic
- [ ] Make one live exploratory API call to verify DataFrame schema (column names, dimension encoding)
- [ ] Create `tests/fixtures/company_facts_sample.json` from trimmed real API response
- [ ] Create `tests/test_ncsr.py` with fixture-based tests
- **Verification:** `python -m pytest tests/test_ncsr.py -v`

### Phase 3: Benchmark extraction
- [ ] Add `BroadBasedIndexAxis` dimension parsing
- [ ] Distinguish fund returns from benchmark returns
- [ ] Extract benchmark_name from axis member value
- [ ] Add benchmark-specific tests to `tests/test_ncsr.py`
- **Verification:** `python -m pytest tests/test_ncsr.py -v`

### Phase 4: CLI integration
- [ ] Wire `parse_ncsr()` into `cli.py` ncsr command (replace stub)
- [ ] Add `--cik`, `--limit`, `--keep-cache` flags
- [ ] Configure logging at INFO level
- **Verification:** `python -m pytest tests/ -v` (all tests pass)

## Definition of Done

This feature is complete when:
- [ ] All acceptance criteria in user stories pass
- [ ] All implementation phases verified
- [ ] Tests pass: `python -m pytest tests/ -v`
- [ ] `parse_nport()` has consistent `ciks` param
- [ ] `parse_ncsr()` has consistent interface with `parse_flows()`
- [ ] No distribution fields populated (explicitly out of scope)

## Ralph Loop Command

```bash
/ralph "Implement N-CSR parser per spec at docs/specs/ncsr-parser.md

PHASES:
1. NPORT consistency: Add ciks param to parse_nport() - verify with pytest tests/test_nport.py -v
2. Core parser: Create ncsr.py with company facts API, dimension parsing, period mapping, upsert - verify with pytest tests/test_ncsr.py -v
3. Benchmarks: Add BroadBasedIndexAxis parsing for benchmark data - verify with pytest tests/test_ncsr.py -v
4. CLI: Wire ncsr command in cli.py replacing stub - verify with pytest tests/ -v

EXPLORATION ALLOWED: Make ONE live API call to Company(cik).get_facts().to_pandas() for a small single-fund trust to inspect DataFrame schema (column names, dimension encoding). Document findings before writing parser logic.

REFERENCE DOCS: Read docs/reference/PARSER_REFERENCE_MAP.md for N-CSR section. Read docs/reference/xbrl-oef-2025/oef-2025.xsd for element definitions.

VERIFICATION (run after each phase):
- python -m pytest tests/ -v

ESCAPE HATCH: After 20 iterations without progress:
- Document what's blocking in the spec file under 'Implementation Notes'
- List approaches attempted
- Stop and ask for human guidance

Output <promise>COMPLETE</promise> when all phases pass verification." --max-iterations 30 --completion-promise "COMPLETE"
```

## Open Questions
*None — all decisions made during interview.*

## Implementation Notes

### ❌ CRITICAL: Data Source Assumption is Invalid (2026-02-13)

**Discovery**: The specification's core assumption is incorrect. The SEC Company Facts API does **NOT** contain OEF taxonomy data needed for N-CSR parsing.

**Evidence**:
- Tested multiple ETF trusts (SPY/CIK 0000884394, IVV/CIK 0001100663, VTI/CIK 0000102909, AGG/CIK 0001393818)
- API endpoint tested: `https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json`
- Result: All responses contain ONLY `dei` (Document & Entity Information) and `us-gaap` (US GAAP) taxonomies
- **Missing**: All OEF taxonomy concepts including `AvgAnnlRtrPct`, `PortfolioTurnoverRate`, `ExpenseRatioPct`

**Root Cause**:
- The Company Facts API aggregates XBRL facts from **financial statement filings** (10-K, 10-Q, 8-K) which use US-GAAP taxonomy
- N-CSR filings use the **OEF (Open-End Fund) taxonomy** for performance data
- OEF XBRL data is embedded as **iXBRL tags within HTML documents**, not extracted to the structured Company Facts JSON API
- The SEC does not pre-extract OEF taxonomy facts into a structured API endpoint

**Specification Error**: Line 9 states "The EDGAR XBRL company facts API pre-extracts these tagged values into structured JSON" — this statement is factually incorrect.

### Alternative Implementation Approaches

Implementation is **BLOCKED** pending decision on alternative approach:

#### Option 1: iXBRL HTML Parsing (Recommended)
**Approach**:
1. Fetch N-CSR filings: `Company(cik).get_filings(form="N-CSR").latest()`
2. Extract HTML content: `filing.html()`
3. Parse iXBRL tags from HTML to extract OEF concepts with dimensional contexts
4. Extract `LegalEntityAxis` and `BroadBasedIndexAxis` dimensions from inline XBRL context attributes
5. Map period durations to return types (1yr/5yr/10yr/inception)

**Pros**:
- Matches actual data structure
- All OEF data is available in iXBRL HTML
- Dimensional contexts are preserved

**Cons**:
- Requires HTML/XML parsing (BeautifulSoup or lxml)
- More complex than DataFrame API
- Need to handle iXBRL namespace resolution

**Reference**: `docs/reference/edgar-xbrl-guide.pdf` for iXBRL structure

#### Option 2: XBRL Instance Document Parsing
**Approach**:
1. Check if N-CSR filing has separate XBRL instance XML file
2. Parse XML directly for OEF concepts and contexts
3. Extract dimensional data from XBRL context definitions

**Pros**:
- Cleaner XML structure than HTML parsing
- Standard XBRL parsing libraries available

**Cons**:
- Not all N-CSR filings have separate instance documents (many use inline XBRL only)
- Would need fallback to Option 1

#### Option 3: Research Alternative Data Sources
**Approach**:
- Research if SEC provides fund-specific structured data API
- Check if edgartools has higher-level N-CSR parsing capabilities not yet discovered
- Investigate if other vendors provide structured N-CSR data

**Pros**:
- Might find easier data source

**Cons**:
- No evidence such API exists
- Time investment with uncertain outcome

### Recommendation

**Human decision required** before proceeding:
1. Choose implementation approach (Option 1 recommended)
2. Update specification with correct data source and parsing methodology
3. Adjust implementation phases to reflect HTML/XML parsing requirements

### Next Steps (After Decision)
1. Update spec Overview and Technical Design sections
2. Revise Phase 2 implementation checklist
3. Proceed with chosen approach
