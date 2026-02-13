# Specification: Financial Highlights Parser

## Overview
Parse Financial Highlights HTML tables from N-CSR filings to extract per-share operating data, per-share distribution data, and fund ratios for ETFs. This data is NOT available in XBRL — it must be extracted from untagged HTML in Item 7(b) of N-CSR filings using positional table parsing validated with arithmetic identity.

## Problem Statement
The OEF XBRL taxonomy has no per-share distribution elements. Per-share distributions (dividends from net investment income, distributions from capital gains, return of capital) are reported in the Financial Highlights section of every N-CSR filing but are not iXBRL-tagged. The SEC explicitly excluded Financial Highlights from tagging requirements (Release 33-11125). A positional HTML parsing approach is needed, with built-in math validation.

## Scope

### In Scope
- Parse Financial Highlights tables from N-CSR filing HTML
- Extract per-share operating data (NAV, investment operations)
- Extract per-share distribution data (income, gains, ROC)
- Extract ratios/supplemental data (expense ratio, turnover, net assets)
- Store in 3 new database tables
- Math validation with flagging
- CLI command: `etf-pipeline finhigh`
- Multi-filing-per-CIK iteration (reuse N-CSR XBRL pattern)
- Fund matching via document structure + fuzzy name fallback
- Unit tests with trimmed real HTML fixtures

### Out of Scope
- Historical data extraction (only most recent year per filing)
- Tax-character distribution breakdown (1099-DIV data)
- Cross-validation against XBRL Performance data
- Mutual fund support (ETFs only via existing ticker filter)

## Data Model

### Table: `per_share_operating`
One row per ETF per fiscal year. Per-share investment operations data.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| id | Integer PK | No | Auto-increment |
| etf_id | Integer FK(etf.id) | No | References ETF |
| fiscal_year_end | Date | No | End of reporting period |
| nav_beginning | Numeric(10,4) | Yes | Net asset value per share, beginning of period |
| net_investment_income | Numeric(10,4) | Yes | Per-share net investment income/loss |
| net_realized_unrealized_gain | Numeric(10,4) | Yes | Per-share net realized and unrealized gains/losses |
| total_from_operations | Numeric(10,4) | Yes | Sum of investment income + gains |
| equalization | Numeric(10,4) | Yes | Net equalization credits/charges (some issuers only) |
| nav_end | Numeric(10,4) | Yes | Net asset value per share, end of period |
| total_return | Numeric(8,5) | Yes | Total return for the period as decimal |
| math_validated | Boolean | No | True if NAV_begin + operations - distributions (+/- equalization) = NAV_end within $0.01 |

**Unique constraint**: `(etf_id, fiscal_year_end)`

### Table: `per_share_distribution`
One row per ETF per fiscal year. Per-share distribution amounts.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| id | Integer PK | No | Auto-increment |
| etf_id | Integer FK(etf.id) | No | References ETF |
| fiscal_year_end | Date | No | End of reporting period |
| dist_net_investment_income | Numeric(10,4) | Yes | Dividends from net investment income (reported as negative) |
| dist_realized_gains | Numeric(10,4) | Yes | Distributions from realized capital gains |
| dist_return_of_capital | Numeric(10,4) | Yes | Return of capital distributions |
| dist_total | Numeric(10,4) | Yes | Total distributions |

**Unique constraint**: `(etf_id, fiscal_year_end)`

### Table: `per_share_ratios`
One row per ETF per fiscal year. Fund-level ratios and supplemental data.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| id | Integer PK | No | Auto-increment |
| etf_id | Integer FK(etf.id) | No | References ETF |
| fiscal_year_end | Date | No | End of reporting period |
| expense_ratio | Numeric(6,5) | Yes | Total expense ratio as decimal |
| portfolio_turnover | Numeric(8,5) | Yes | Portfolio turnover rate as decimal |
| net_assets_end | Numeric(20,2) | Yes | Total net assets at end of period in USD |

**Unique constraint**: `(etf_id, fiscal_year_end)`

## Parsing Strategy

### Positional Extraction (not label matching)
The Financial Highlights table follows a regulated structure (Form N-1A Item 13). Regardless of label text variations across issuers, the ROW ORDER is fixed:

1. **NAV, Beginning of Period** (always first numeric row)
2. **Investment Operations section**:
   - Net Investment Income/Loss
   - Net Realized/Unrealized Gain/Loss
   - Total from Investment Operations
3. **Equalization** (optional — only some issuers like State Street)
4. **Distributions section**:
   - From Net Investment Income
   - From Capital Gains (if any)
   - From Return of Capital (if any)
   - Total Distributions
5. **NAV, End of Period**
6. **Total Return**
7. **Ratios/Supplemental Data** (expense ratio, turnover, net assets)

### Math Validation
```
expected_nav_end = nav_beginning + total_from_operations - abs(dist_total) + equalization
math_validated = abs(expected_nav_end - nav_end) <= 0.01
```

If `math_validated` is False: insert the data anyway but flag it. Log a warning with the ticker and the discrepancy.

### Fund Matching
1. **Primary**: Parse series_id/class_id from SGML headers or iXBRL context near each Financial Highlights section
2. **Fallback**: Fuzzy-match the heading text (e.g., "Vanguard 500 Index Fund - ETF Shares") against ETF.fund_name

### Filing Discovery
Reuse the multi-filing-per-CIK approach from the N-CSR XBRL parser:
- For each CIK, iterate up to 10 recent N-CSR filings
- Track which ETFs (class_ids) have been satisfied
- Stop early when all ETFs for the CIK are matched
- Access filing HTML via `filing.html()` from edgartools

## CLI Command

```
etf-pipeline finhigh [--cik CIK] [--limit N] [--keep-cache]
```

Same flags as other parsers. Wired into `cli.py` with the same pattern.

## Dependencies

Add to project:
- `beautifulsoup4` — HTML table parsing
- `lxml` — parser backend for BeautifulSoup

## User Stories

### US-1: Add 3 new database models
**Description**: Create PerShareOperating, PerShareDistribution, and PerShareRatios SQLAlchemy models with relationships to ETF.

**Acceptance Criteria**:
- [ ] 3 new model classes in models.py with all columns per spec
- [ ] Unique constraints on (etf_id, fiscal_year_end) for each
- [ ] ETF model has relationships to new tables
- [ ] `python3 scripts/init_test_db.py` creates the tables
- [ ] Model unit tests pass

### US-2: Implement Financial Highlights HTML parser
**Description**: Create `src/etf_pipeline/parsers/finhigh.py` with the core HTML parsing logic.

**Acceptance Criteria**:
- [ ] `parse_financial_highlights_table(html_table)` extracts all per-share fields from a single FH table
- [ ] Positional extraction works for Vanguard, iShares, ALPS, and State Street HTML formats
- [ ] Math validation computes correctly within $0.01 tolerance
- [ ] Equalization field captured when present
- [ ] Parser handles missing rows gracefully (nullable fields)
- [ ] Unit tests with trimmed real HTML fixtures from 4 issuers pass

### US-3: Implement filing-level orchestration
**Description**: Add `parse_finhigh()` function that iterates CIKs, discovers N-CSR filings, matches Financial Highlights sections to ETFs, and upserts data.

**Acceptance Criteria**:
- [ ] Multi-filing-per-CIK iteration (up to 10 filings)
- [ ] Fund matching via document structure with fuzzy name fallback
- [ ] Upserts on unique constraint (etf_id, fiscal_year_end)
- [ ] Writes to all 3 tables per matched ETF
- [ ] Logs processed/skipped counts
- [ ] Unit tests with mocked filings pass

### US-4: Wire CLI command and integration test
**Description**: Add `finhigh` command to CLI, run end-to-end against real filings.

**Acceptance Criteria**:
- [ ] `etf-pipeline finhigh` command works with --cik, --limit, --keep-cache flags
- [ ] End-to-end test: load ETFs for CIK 36405, run finhigh, verify per_share_distribution rows exist
- [ ] All existing tests still pass (85+)

## Implementation Phases

### Phase 1: Data Model + Dependencies
- [ ] Add bs4 and lxml to pyproject.toml
- [ ] Add PerShareOperating, PerShareDistribution, PerShareRatios models to models.py
- [ ] Add relationships to ETF model
- [ ] Update docs/SCHEMA.md
- [ ] Write model tests
- **Verification**: `python3 -m pytest tests/test_models.py -v`

### Phase 2: HTML Table Parser
- [ ] Create `src/etf_pipeline/parsers/finhigh.py`
- [ ] Implement `parse_financial_highlights_table()` — core positional extraction
- [ ] Create test fixtures: trimmed real HTML from Vanguard, iShares, ALPS, State Street
- [ ] Write unit tests for table parsing across all 4 formats
- [ ] Implement math validation
- **Verification**: `python3 -m pytest tests/test_finhigh.py -v`

### Phase 3: Filing Orchestration + CLI
- [ ] Implement `parse_finhigh()` — CIK iteration, filing discovery, fund matching, upsert
- [ ] Implement fund matching (document structure + fuzzy fallback)
- [ ] Wire `finhigh` command into cli.py
- [ ] Write orchestration tests with mocked filings
- [ ] Run full test suite
- **Verification**: `python3 -m pytest tests/ -v`

## Definition of Done

This feature is complete when:
- [ ] All acceptance criteria in US-1 through US-4 pass
- [ ] All 3 implementation phases verified
- [ ] Tests pass: `python3 -m pytest tests/ -v`
- [ ] `etf-pipeline finhigh --cik 36405` populates per_share_distribution rows for Vanguard ETFs
- [ ] Math validation flags are accurate (most records should be True)

## Reference: Verified Table Structures

From actual N-CSR filings (4 issuers verified):

**Vanguard** (CIK 36405): NAV begin -> NII + Gains -> Total Ops -> Dist from NII + Cap Gains -> Total Dist -> NAV end -> Total Return -> Ratios

**Invesco** (CIK 1100663): NAV begin -> NII + Gains -> Total Ops -> Dist from NII -> NAV end -> Total Return -> Ratios

**ALPS ETF** (CIK 1414040): NAV begin -> NII + Gains -> Total Ops -> Dist from NII + ROC -> Total Dist -> Net Change -> NAV end -> Total Return -> Ratios

**State Street SPDR** (CIK 1064642): NAV begin -> NII + Gains -> Total Ops -> Equalization -> Dist from NII -> NAV end -> Total Return -> Ratios

## Ralph Loop Command

```bash
/ralph-loop "Implement Financial Highlights parser per spec at docs/specs/implement-financial-highlights-parser.md

PHASES:
1. Data Model + Dependencies: Add 3 new SQLAlchemy models, update schema docs, write model tests - verify with python3 -m pytest tests/test_models.py -v
2. HTML Table Parser: Create finhigh.py with positional extraction, create test fixtures from real HTML, write parser tests - verify with python3 -m pytest tests/test_finhigh.py -v
3. Filing Orchestration + CLI: Implement CIK iteration, fund matching, upsert, wire CLI command, run full suite - verify with python3 -m pytest tests/ -v

VERIFICATION (run after each phase):
- python3 -m pytest tests/ -v

ESCAPE HATCH: After 20 iterations without progress:
- Document what's blocking in the spec file under 'Implementation Notes'
- List approaches attempted
- Stop and ask for human guidance

Output <promise>COMPLETE</promise> when all phases pass verification." --max-iterations 30 --completion-promise "COMPLETE"
```
