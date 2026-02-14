# Draft: End-to-End Run Pipeline Command

## Core Concept
Intelligent, incremental pipeline that builds an over-time record of ETF data.

## CLI Interface
```
etf-pipeline run-all           # process all CIKs (new + stale)
etf-pipeline run-all --limit 5 # process 5 CIKs (new + stale)
```
No other flags. Simple.

## Execution Flow

### Step 0: Ensure DB + tables exist
- `Base.metadata.create_all(engine)` (idempotent)

### Step 1: Discover
- Always re-run `fetch()` to get latest ETF universe from SEC
- Produces `etf_tickers.json`

### Step 2: Load ETFs
- Run `load_etfs()` to populate/update ETF table with fund_name, issuer_name
- Pass `limit` if provided

### Step 3: Per-CIK Processing
For each CIK (alphabetical order, limited by --limit if set):
1. Check SEC for latest filing dates per form type (NPORT-P, N-CSR, 485BPOS, 24F-2NT)
2. Compare against processing_log table
3. Run ONLY parsers that have new filings since last run
4. For never-processed CIKs: run ALL parsers
5. Update processing_log with (cik, parser_type, last_run_at, latest_filing_date_seen)
6. Clear edgartools cache after each CIK

### Error Handling
- Continue on per-CIK failure, log error
- Report summary at end: N succeeded, N failed, N skipped (no new data)

## Tracking: processing_log Table
```
processing_log:
  id: Integer (PK)
  cik: String(10), NOT NULL
  parser_type: String(20), NOT NULL  (nport, ncsr, prospectus, finhigh, flows)
  last_run_at: DateTime, NOT NULL
  latest_filing_date_seen: Date, NOT NULL
  UNIQUE(cik, parser_type)
```

## Data History: filing_date Column
- Add `filing_date` (Date) column to ALL data tables
- Include `filing_date` in unique constraints
- New filings = new rows (different report_date)
- Amended filings = also new rows (same report_date, different filing_date)
- Never overwrite — always insert

### Tables needing filing_date:
- Holding (currently unique on etf_id, cusip, report_date)
- Derivative (currently unique on etf_id, name, report_date)
- Performance (currently unique on etf_id, class_id, fiscal_year_end)
- FeeExpense (currently unique on etf_id, effective_date)
- ShareholderFee (currently unique on etf_id, effective_date)
- ExpenseExample (currently unique on etf_id, effective_date)
- FlowData (currently unique on cik, fiscal_year_end)
- PerShareOperating (currently unique on etf_id, fiscal_year_end)
- PerShareDistribution (currently unique on etf_id, fiscal_year_end)
- PerShareRatio (currently unique on etf_id, fiscal_year_end)

## Orchestration: Per-CIK (not bulk)
- Iterate CIK by CIK
- For each CIK, run only needed parsers
- Clear cache after each CIK completes
- DB is source of truth; cached filings are disposable

## Phasing (3 phases, separation of concerns)
### Phase 1: Schema changes
- Add processing_log table
- Add filing_date column to all data tables
- Update unique constraints to include filing_date
- Update SCHEMA.md
- All existing tests must still pass

### Phase 2: Parser changes
- Each parser: INSERT instead of upsert
- Each parser: set filing_date on every row
- Each parser: log to processing_log after success
- Extract per-CIK processing functions for reuse by run-all

### Phase 3: run-all intelligence
- Per-CIK orchestration with freshness detection
- Cache cleanup per CIK
- Summary reporting
