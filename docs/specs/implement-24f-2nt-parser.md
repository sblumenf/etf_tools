# Specification: Implement 24F-2NT Parser

## Overview

Parse 24F-2NT filings from SEC EDGAR to extract trust-level fund flow data (sales, redemptions, net sales) and store it in the `FlowData` table keyed by CIK.

## Key Discovery: Trust-Level Data

**24F-2NT filings report aggregate flow data at the trust (CIK) level, NOT per-fund/series.**

Evidence from real filings (iShares, SPDR, ProShares, Schwab):
- Every issuer files ONE `annualFilingInfo` block per filing
- `item2` lists all series covered (e.g., 131 series for ProShares) but item5 has ONE set of aggregate values
- The `seriesOrClassId` field in `item5` exists in the XSD schema but is **never populated** in real filings
- Filings with `rptIncludeAllSeriesFlag=true` are the norm

### Schema Implication

The `FlowData` table must be changed from per-ETF (`etf_id` FK) to per-CIK (`cik` string column). This accurately represents the data granularity.

---

## Scope

### In Scope
- Parse 24F-2NT XML filings via edgartools
- Extract sales_value, redemptions_value, net_sales from `item5`
- Extract fiscal_year_end from `item4`
- Store trust-level flow data keyed by (cik, fiscal_year_end)
- Modify FlowData model: replace `etf_id` FK with `cik` VARCHAR
- Update SCHEMA.md to reflect the schema change
- CLI command `flows` with --cik, --limit, --keep-cache flags
- Upsert on conflict (update existing rows if re-run)
- Handle accounting-notation negatives: `(20.00)` -> `-20.00`

### Out of Scope
- Historical backfill (only parse latest filing per CIK)
- Per-fund flow attribution or proportional splitting
- Pipeline orchestration (`run-all` command) -- separate task
- 24F-2NT/A (amendment) handling beyond normal upsert

---

## User Stories

### US-1: Modify FlowData Model

Change the FlowData SQLAlchemy model from per-ETF to per-CIK.

**Changes:**
- Remove `etf_id` FK column and `etf` relationship
- Add `cik` VARCHAR(10) NOT NULL column
- Change unique constraint to `(cik, fiscal_year_end)`
- Update index to `flow_data_fy_idx` on `fiscal_year_end`
- Remove `flow_data` back_populates from ETF model

**Acceptance Criteria:**
- FlowData model has `cik` string column, no `etf_id`
- UniqueConstraint on `(cik, fiscal_year_end)` enforced
- All existing tests pass (update any that reference FlowData.etf_id)
- SCHEMA.md updated to reflect the change

### US-2: Implement XML Parser Core

Create `src/etf_pipeline/parsers/flows.py` with XML parsing logic.

**Function signature:**
```python
def parse_flows(
    cik: Optional[str] = None,
    ciks: Optional[list[str]] = None,
    limit: Optional[int] = None,
    clear_cache: bool = True,
) -> None
```

**XML Extraction Logic:**
1. Fetch filing via `Company(cik).get_filings(form="24F-2NT")`
2. Get raw XML via `filing.xml()`
3. Parse XML with `xml.etree.ElementTree`
4. Namespace: `http://www.sec.gov/edgar/twentyfourf2filer`
5. Navigate: `formData/annualFilings/annualFilingInfo/item5`
6. Extract fields:
   - `aggregateSalePriceOfSecuritiesSold` -> `sales_value`
   - `aggregatePriceOfSecuritiesRedeemedOrRepurchasedInFiscalYear` -> `redemptions_value`
   - `netSales` -> `net_sales`
7. Navigate: `formData/annualFilings/annualFilingInfo/item4`
   - `lastDayOfFiscalYear` -> `fiscal_year_end` (format: MM/DD/YYYY)

**Money Parsing:**
- Strip commas: `1,234.56` -> `1234.56`
- Handle accounting negatives: `(20.00)` -> `-20.00`
- Convert to `Decimal`

**CIK Discovery:**
- If `ciks` param provided, use those CIKs
- If `cik` param provided, use `[cik]` (zero-padded to 10 digits)
- If neither, query `SELECT DISTINCT cik FROM etf ORDER BY cik`
- If `limit` provided, take first N CIKs

**Duplicate Handling:**
- Upsert: if FlowData exists for (cik, fiscal_year_end), update the values
- Use SQLAlchemy `session.merge()` or explicit query + update

**Acceptance Criteria:**
- Given a 24F-2NT XML string, correctly extracts sales_value, redemptions_value, net_sales, fiscal_year_end
- Handles missing item5 fields gracefully (log warning, skip)
- Handles accounting-notation negative values `(X.XX)`
- Handles filings with no XML content (log warning, skip)
- Upserts correctly: running twice produces same result
- Clears edgartools cache after processing (unless --keep-cache)

### US-3: Wire Up CLI Command

Update the `flows` stub in `cli.py` to call `parse_flows()`.

**CLI flags:**
- `--cik`: Process only this CIK
- `--limit`: Process only the first N CIKs
- `--keep-cache`: Keep edgartools HTTP cache after processing

**Acceptance Criteria:**
- `etf-pipeline flows` runs the parser
- `etf-pipeline flows --cik 1100663` processes only iShares Trust
- `etf-pipeline flows --limit 5` processes first 5 CIKs
- Logging configured at INFO level (same as nport command)

### US-4: Comprehensive Tests

Create `tests/test_flows.py` with tests mocking `filing.xml()`.

**Test Cases:**
1. **Happy path**: Valid XML -> correct FlowData row inserted
2. **Money parsing**: Values with commas, parenthesized negatives
3. **Upsert**: Running parser twice with same data -> one row, updated values
4. **No filings**: CIK with no 24F-2NT filings -> warning logged, no crash
5. **No XML content**: Filing returns None from xml() -> warning, skip
6. **Missing item5 fields**: Partial XML -> handles gracefully
7. **Date parsing**: MM/DD/YYYY fiscal year end -> correct date object
8. **CIK filtering**: --cik flag processes only specified CIK
9. **Limit**: --limit flag restricts number of CIKs processed
10. **CIKs param**: Passing ciks list uses those CIKs directly

**Test Pattern:**
- Mock `Company` and `get_filings` to return mock Filing objects
- Mock `filing.xml()` to return inline XML strings
- Use in-memory SQLite with FK enforcement (from conftest.py)
- Pre-populate ETF table with test data for CIK lookups

**Acceptance Criteria:**
- All tests pass
- No network calls in tests (all mocked)
- Tests cover happy path, edge cases, and error conditions

---

## Technical Details

### XML Namespace
```
http://www.sec.gov/edgar/twentyfourf2filer
```

### XML Path to Flow Data
```
edgarSubmission/formData/annualFilings/annualFilingInfo[0]/item5
```

### Field Mapping

| XML Element | FlowData Column | Type | Notes |
|------------|----------------|------|-------|
| `item5/aggregateSalePriceOfSecuritiesSold` | `sales_value` | Decimal(20,4) | Item 5(i) |
| `item5/aggregatePriceOfSecuritiesRedeemedOrRepurchasedInFiscalYear` | `redemptions_value` | Decimal(20,4) | Item 5(ii) |
| `item5/netSales` | `net_sales` | Decimal(20,4) | Item 5(v) |
| `item4/lastDayOfFiscalYear` | `fiscal_year_end` | Date | MM/DD/YYYY format |
| `headerData/filerInfo/filer/issuerCredentials/cik` | `cik` | VARCHAR(10) | Zero-padded |

### FlowData Model (Updated)

```python
class FlowData(Base):
    __tablename__ = "flow_data"
    __table_args__ = (
        UniqueConstraint("cik", "fiscal_year_end", name="flow_data_cik_fy_uniq"),
        Index("flow_data_fy_idx", "fiscal_year_end"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cik: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    fiscal_year_end: Mapped[date] = mapped_column(Date, nullable=False)
    sales_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 4))
    redemptions_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 4))
    net_sales: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 4))
```

### Sample Real XML Structure (iShares Trust)
```xml
<edgarSubmission xmlns="http://www.sec.gov/edgar/twentyfourf2filer">
  <headerData>
    <filerInfo>
      <filer><issuerCredentials><cik>0001100663</cik></issuerCredentials></filer>
      <investmentCompanyType>N-1A</investmentCompanyType>
    </filerInfo>
  </headerData>
  <formData>
    <annualFilings>
      <annualFilingInfo>
        <item4>
          <lastDayOfFiscalYear>10/28/2024</lastDayOfFiscalYear>
        </item4>
        <item5>
          <aggregateSalePriceOfSecuritiesSold>86116742248.00</aggregateSalePriceOfSecuritiesSold>
          <aggregatePriceOfSecuritiesRedeemedOrRepurchasedInFiscalYear>60338350561.00</aggregatePriceOfSecuritiesRedeemedOrRepurchasedInFiscalYear>
          <netSales>25778391687.00</netSales>
        </item5>
      </annualFilingInfo>
    </annualFilings>
  </formData>
</edgarSubmission>
```

---

## Verification

### Commands to verify
```bash
# Run tests
pytest tests/test_flows.py -v

# Run all tests to check for regressions
pytest tests/ -v

# Type check (if configured)
# mypy src/etf_pipeline/parsers/flows.py

# Test CLI
etf-pipeline flows --help
```

### Success Criteria
- All new tests pass
- All existing tests pass (no regressions from FlowData model change)
- `etf-pipeline flows --help` shows correct flags
- Parser correctly extracts data from real 24F-2NT XML structure

---

## Implementation Phases

### Phase 1: Schema Change (US-1)
Modify FlowData model, update SCHEMA.md, fix any existing tests that reference FlowData.etf_id.

### Phase 2: Parser + CLI (US-2, US-3)
Implement the parser module and wire up the CLI command.

### Phase 3: Tests (US-4)
Write comprehensive test suite.

### Phase 4: Integration Verification
Run full test suite, verify no regressions.
