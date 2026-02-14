# Specification: Implement the 485BPOS Parser

## Overview

Parse 485BPOS (post-effective amendment / prospectus) filings from SEC EDGAR to extract fee schedules, shareholder fees, expense projections, and investment strategy text. Data is iXBRL-tagged using the Risk/Return Summary (RR) XBRL taxonomy (`rr-2023.xsd`). The parser populates data at the ETF level, matching share classes via `class_id`.

## Reference Documents

Before implementing, read:
- `docs/reference/xbrl-rr-2023/rr-preparers-guide-2022-11-04.pdf` — RR taxonomy usage guide
- `docs/reference/xbrl-rr-2023/rr-2023.xsd` — Tag definitions and types
- `docs/reference/xbrl-rr-2023/rr-samples/rr-samples-2023/rr01/rr01-20221103.htm` — Sample iXBRL filing
- `docs/reference/PARSER_REFERENCE_MAP.md` — Section 3 (485BPOS)

## Scope

### In Scope
- Parse iXBRL fee tables from 485BPOS filings (management fee, 12b-1, other expenses, gross/net totals, waivers, acquired fund fees)
- Parse shareholder fees (front-load, deferred, reinvestment, redemption, exchange)
- Parse expense example projections (1yr, 3yr, 5yr, 10yr with-redemption dollar costs)
- Extract investment objective and strategy narrative text (plain text, HTML stripped)
- Update ETF.objective_text, ETF.strategy_text, ETF.filing_url
- New tables: ShareholderFee, ExpenseExample
- New column: FeeExpense.acquired_fund_fees
- New column: ETF.objective_text
- CLI command: `etf-pipeline prospectus --cik --limit --keep-cache`

### Out of Scope
- Expense example "no redemption" variant
- Bar chart / performance data from prospectus (already handled by N-CSR parser)
- Processing classes not already in ETF table
- Historical fee timeline (multiple filings per CIK)

## Data Model

### ETF Table Changes
| Field | Type | Notes |
|-------|------|-------|
| `objective_text` | Text, nullable | NEW. Investment objective from `rr:ObjectivePrimaryTextBlock`, HTML stripped to plain text |

`strategy_text` already exists — will be populated from `rr:StrategyNarrativeTextBlock`, HTML stripped to plain text.
`filing_url` already exists — will be set to the 485BPOS filing URL on successful extraction.

### FeeExpense Table Changes
| Field | Type | Notes |
|-------|------|-------|
| `acquired_fund_fees` | Numeric(6,5), nullable | NEW. From `rr:AcquiredFundFeesAndExpensesOverAssets` |

Existing fields populated by this parser:
| Field | RR Tag | Notes |
|-------|--------|-------|
| `management_fee` | `rr:ManagementFeesOverAssets` | Per share class |
| `distribution_12b1` | `rr:DistributionAndService12b1FeesOverAssets` | Per share class |
| `other_expenses` | `rr:OtherExpensesOverAssets` | Per share class |
| `total_expense_gross` | `rr:ExpensesOverAssets` | Per share class |
| `fee_waiver` | `rr:FeeWaiverOrReimbursementOverAssets` | Per share class, store as positive (negate from source) |
| `total_expense_net` | `rr:NetExpensesOverAssets` | Per share class, NULL if tag absent |

### ShareholderFee Table (NEW)
| Field | Type | RR Tag | Notes |
|-------|------|--------|-------|
| `id` | Integer, PK | — | Auto-increment |
| `etf_id` | FK -> ETF | — | |
| `effective_date` | Date | `dei:DocumentPeriodEndDate` | |
| `front_load` | Numeric(6,5), nullable | `rr:MaximumSalesChargeImposedOnPurchasesOverOfferingPrice` | Decimal form |
| `deferred_load` | Numeric(6,5), nullable | `rr:MaximumDeferredSalesChargeOverOther` | Decimal form |
| `reinvestment_charge` | Numeric(6,5), nullable | `rr:MaximumSalesChargeOnReinvestedDividendsAndDistributionsOverOther` | Decimal form |
| `redemption_fee` | Numeric(6,5), nullable | `rr:RedemptionFeeOverRedemption` | Store as positive (negate from source, it's NonPositive type) |
| `exchange_fee` | Numeric(6,5), nullable | `rr:ExchangeFeeOverRedemption` | Decimal form |

**Unique constraint**: `(etf_id, effective_date)`
**Relationship**: `ETF.shareholder_fees` (back_populates)

### ExpenseExample Table (NEW)
| Field | Type | RR Tag | Notes |
|-------|------|--------|-------|
| `id` | Integer, PK | — | Auto-increment |
| `etf_id` | FK -> ETF | — | |
| `effective_date` | Date | `dei:DocumentPeriodEndDate` | |
| `year_01` | Integer, nullable | `rr:ExpenseExampleYear01` | Dollar cost on $10K, with redemption |
| `year_03` | Integer, nullable | `rr:ExpenseExampleYear03` | Dollar cost on $10K, with redemption |
| `year_05` | Integer, nullable | `rr:ExpenseExampleYear05` | Dollar cost on $10K, with redemption |
| `year_10` | Integer, nullable | `rr:ExpenseExampleYear10` | Dollar cost on $10K, with redemption |

**Unique constraint**: `(etf_id, effective_date)`
**Relationship**: `ETF.expense_examples` (back_populates)

## RR Tag Mapping — Value Conversion Rules

### Numeric fees (NonNegativePure4Type)
- iXBRL `scale="-2"` means displayed value / 100 = actual decimal
- Example: displayed `0.70` with scale -2 → store as `Decimal('0.0070')`
- Format `ixt:numdotdecimal` → parse as float, apply scale
- Format `ixt-sec:numwordsen` with value `None` → store as NULL (not zero)
- Format `ixt:zerodash` with value `—` → store as `Decimal('0')` (zero, after scale)

### Negative fees (NonPositivePure4Type — fee_waiver, redemption_fee)
- Source values are zero or negative
- Store as positive (negate the extracted value)
- Example: waiver displayed as `-0.10` → store as `Decimal('0.0010')`

### Expense example (NonNegativeMonetaryType)
- Dollar amounts, no scale factor (decimals="0")
- Store as integer
- Example: displayed `695` → store as `695`

### Text blocks (textBlockItemType)
- Contains raw HTML (paragraphs, bold, lists)
- Strip to plain text using BeautifulSoup `.get_text(separator=' ', strip=True)`

## XBRL Context Structure

iXBRL contexts use dimensional axes to identify series and share classes:

```
CIK: xbrli:identifier → "0001234567"
Series: dei:LegalEntityAxis → "rr01:S000012345Member"
Class: rr:ProspectusShareClassAxis → "rr01:C000012345Member"
```

- **Fee data** (FeeExpense, ShareholderFee, ExpenseExample): context has both series AND class dimensions
- **Narrative text** (objective, strategy): context has series dimension only
- **Filing metadata** (CIK, document type, period): base context, no dimensions

### Matching Logic
1. Parse all contexts from `ix:resources` section
2. For each context, extract S-number from `dei:LegalEntityAxis` member and C-number from `rr:ProspectusShareClassAxis` member
3. Match C-number to `ETF.class_id` in database
4. Skip data for unmatched class_ids (log at DEBUG level)
5. For narrative text (series-only contexts), match S-number to `ETF.series_id`

## Parser Architecture

### File: `src/etf_pipeline/parsers/prospectus.py`

Follow the same structural pattern as `ncsr.py` and `finhigh.py`:

```
parse_prospectus(cik=None, limit=None, clear_cache=True)
    → iterates CIKs from ETF table
    → calls _process_cik_prospectus(cik, session)

_process_cik_prospectus(cik, session)
    → fetches most recent 485BPOS filing via edgartools
    → gets HTML via filing.html()
    → parses iXBRL with BeautifulSoup
    → extracts fee data, shareholder fees, expense examples, narrative text
    → upserts to database
```

### Key Implementation Details

1. **Filing retrieval**: `Company(cik).get_filings(form='485BPOS').latest(1)` — most recent only
2. **HTML parsing**: `BeautifulSoup(html, 'html.parser')` — parse `ix:nonFraction` and `ix:nonNumeric` tags
3. **Context parsing**: Extract all `xbrli:context` elements, build a map of context_id → {cik, series_id, class_id}
4. **effective_date**: Extract from `dei:DocumentPeriodEndDate` `ix:nonNumeric` tag
5. **Upsert**: Use `INSERT ... ON CONFLICT (etf_id, effective_date) DO UPDATE` for all three target tables (FeeExpense, ShareholderFee, ExpenseExample)
6. **ETF update**: Set objective_text, strategy_text, filing_url on the ETF row after successful extraction
7. **Cache**: Clear edgartools cache after processing unless `--keep-cache`

### Error Handling
- No 485BPOS filing found for CIK → log WARNING, skip
- Filing has no RR iXBRL tags → log WARNING, skip
- Individual value parse failure → log WARNING, set field to NULL, continue with other fields
- Database error → log ERROR, rollback session for this CIK, continue to next

## CLI Command

### File: `src/etf_pipeline/cli.py`

Replace the existing stub:

```python
@main.command()
@click.option("--cik", type=str, help="Process only this CIK")
@click.option("--limit", type=int, help="Process only the first N CIKs")
@click.option("--keep-cache", is_flag=True, default=False,
              help="Keep edgartools HTTP cache after processing (default: clear)")
def prospectus(cik, limit, keep_cache):
    """Parse 485BPOS filings for fee schedules, shareholder fees, and strategy."""
    import logging
    from etf_pipeline.parsers.prospectus import parse_prospectus
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    parse_prospectus(cik=cik, limit=limit, clear_cache=not keep_cache)
```

## Testing

### File: `tests/test_prospectus.py`

Follow the same testing pattern as `test_ncsr.py` and `test_finhigh.py`:

1. **Fixture**: Create `tests/fixtures/prospectus/sample_485bpos.html` based on the RR sample at `docs/reference/xbrl-rr-2023/rr-samples/rr-samples-2023/rr01/rr01-20221103.htm` but trimmed to include only the tags we extract (fee table, shareholder fees, expense example, objective, strategy)
2. **Mock**: Mock `edgartools` Company and Filing objects, return fixture HTML from `filing.html()`
3. **In-memory SQLite**: Use the existing `conftest.py` pattern with FK enforcement

### Test Cases

**Fee extraction tests:**
- Extract all 7 fee fields (management, 12b1, other, gross, net, waiver, acquired_fund_fees) from a share class context
- Verify decimal conversion: displayed `0.70` with scale -2 → stored as `Decimal('0.0070')`
- Verify waiver negation: source negative → stored positive
- Verify `ixt-sec:numwordsen` "None" → stored as NULL
- Verify `ixt:zerodash` "—" → stored as `Decimal('0')` after scale

**Shareholder fee tests:**
- Extract all 5 shareholder fee types
- Verify "None" word values → NULL
- Verify redemption_fee negation (NonPositive → positive)

**Expense example tests:**
- Extract 4 year projections as integers
- Verify dollar amounts stored correctly (no scale)

**Narrative text tests:**
- Extract objective and strategy text
- Verify HTML stripped to plain text
- Verify text assigned to correct ETF (matched by series_id)

**ETF update tests:**
- Verify objective_text, strategy_text, filing_url updated on ETF row
- Verify filing_url only set on successful extraction

**Edge case tests:**
- Filing with no RR tags → logs warning, no rows created
- Unmatched class_id → skipped with debug log
- Multiple series in one filing → each matched to correct ETF
- Upsert: second run with same effective_date overwrites existing row

**Integration test:**
- Full flow: create ETF rows → mock filing → run `_process_cik_prospectus` → verify all 3 tables + ETF updates

## User Stories

### US-1: Data Model Updates
**Description:** Add new columns and tables to support prospectus data extraction.

**Acceptance Criteria:**
- [ ] `ETF.objective_text` column added (Text, nullable)
- [ ] `FeeExpense.acquired_fund_fees` column added (Numeric(6,5), nullable)
- [ ] `ShareholderFee` model created with 5 fee columns + unique constraint
- [ ] `ExpenseExample` model created with 4 year columns + unique constraint
- [ ] `ETF` relationships added for new tables
- [ ] `docs/SCHEMA.md` updated to reflect all changes
- [ ] All existing tests still pass: `pytest tests/`

### US-2: iXBRL Parsing Engine
**Description:** Implement the core iXBRL extraction logic — context parsing, tag extraction, value conversion.

**Acceptance Criteria:**
- [ ] Context parser extracts CIK, series_id, class_id from all `xbrli:context` elements
- [ ] `ix:nonFraction` tags extracted and matched to correct context
- [ ] `ix:nonNumeric` tags extracted for text blocks and dates
- [ ] Scale factor `-2` applied correctly (displayed 0.70 → Decimal 0.0070)
- [ ] `ixt-sec:numwordsen` "None" → NULL
- [ ] `ixt:zerodash` "—" → Decimal 0
- [ ] Negative values (waiver, redemption_fee) negated to positive
- [ ] Text blocks stripped to plain text
- [ ] Tests verify all conversion rules against sample fixture

### US-3: Database Upsert and ETF Updates
**Description:** Implement the CIK processing function that fetches filings, runs extraction, and upserts results.

**Acceptance Criteria:**
- [ ] `_process_cik_prospectus()` fetches most recent 485BPOS via edgartools
- [ ] Fee data upserted to FeeExpense with ON CONFLICT UPDATE
- [ ] Shareholder fees upserted to ShareholderFee
- [ ] Expense examples upserted to ExpenseExample
- [ ] ETF.objective_text, strategy_text, filing_url updated
- [ ] filing_url only set when at least one FeeExpense row created
- [ ] Unmatched class_ids skipped with debug log
- [ ] Missing RR tags → warning log, no rows created
- [ ] Tests verify full extraction flow with mocked filing

### US-4: CLI Command and Entry Point
**Description:** Wire up the CLI command and `parse_prospectus()` entry point.

**Acceptance Criteria:**
- [ ] `parse_prospectus(cik, limit, clear_cache)` iterates CIKs from ETF table
- [ ] CLI command `etf-pipeline prospectus` accepts `--cik`, `--limit`, `--keep-cache`
- [ ] Logging configured at INFO level
- [ ] edgartools cache cleared after processing (unless --keep-cache)
- [ ] All tests pass: `pytest tests/`

## Implementation Phases

### Phase 1: Data Model Updates (US-1)
- Add `objective_text` to ETF model
- Add `acquired_fund_fees` to FeeExpense model
- Create `ShareholderFee` model
- Create `ExpenseExample` model
- Add relationships to ETF
- Update `docs/SCHEMA.md`
- Run existing tests to verify no regressions
- **Verification:** `pytest tests/`

### Phase 2: iXBRL Parsing Engine (US-2)
- Create `src/etf_pipeline/parsers/prospectus.py`
- Implement context parsing functions
- Implement tag extraction and value conversion
- Create test fixture from RR sample
- Write unit tests for all conversion rules
- **Verification:** `pytest tests/test_prospectus.py`

### Phase 3: Database Upsert and CIK Processing (US-3)
- Implement `_process_cik_prospectus()`
- Implement upsert logic for all 3 tables
- Implement ETF field updates
- Write integration tests with mocked filing
- **Verification:** `pytest tests/test_prospectus.py`

### Phase 4: CLI Command and Entry Point (US-4)
- Implement `parse_prospectus()` entry point
- Wire up CLI command (replace stub)
- Write CLI integration test
- Run full test suite
- **Verification:** `pytest tests/`

## Definition of Done

This feature is complete when:
- [ ] All acceptance criteria in US-1 through US-4 pass
- [ ] All implementation phases verified
- [ ] Full test suite passes: `pytest tests/`
- [ ] No regressions in existing tests (124+ tests)
- [ ] `docs/SCHEMA.md` reflects all model changes

## Ralph Loop Command

```bash
/ralph "Implement the 485BPOS parser per spec at docs/specs/implement-the-485bpos-parser.md

PHASES:
1. Data Model Updates: Add objective_text to ETF, acquired_fund_fees to FeeExpense, create ShareholderFee and ExpenseExample models, update SCHEMA.md - verify with pytest tests/
2. iXBRL Parsing Engine: Create prospectus.py with context parsing, tag extraction, value conversion. Create test fixture and unit tests - verify with pytest tests/test_prospectus.py
3. Database Upsert: Implement _process_cik_prospectus with upsert logic for FeeExpense/ShareholderFee/ExpenseExample and ETF updates - verify with pytest tests/test_prospectus.py
4. CLI Command: Wire up parse_prospectus() entry point and CLI command, run full suite - verify with pytest tests/

VERIFICATION (run after each phase):
- pytest tests/

ESCAPE HATCH: After 20 iterations without progress:
- Document what's blocking in the spec file under 'Implementation Notes'
- List approaches attempted
- Stop and ask for human guidance

Output <promise>COMPLETE</promise> when all phases pass verification." --max-iterations 30 --completion-promise "COMPLETE"
```
