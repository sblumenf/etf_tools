# Spec: End-to-End Run Pipeline Command

## Overview

Redesign the `run-all` CLI command to be an intelligent, incremental pipeline that:
- Tracks which CIKs have been processed and when
- Detects new filings on SEC EDGAR and only processes what changed
- Builds an over-time record (new filings = new rows, amendments = new rows)
- Processes per-CIK with cache cleanup after each CIK
- Works with SQLite (PostgreSQL support deferred)

## CLI Interface

```
etf-pipeline run-all           # process all CIKs (new + stale)
etf-pipeline run-all --limit 5 # process 5 CIKs (new + stale)
```

No other flags.

## Execution Flow

```
Step 0: Ensure DB + tables exist (Base.metadata.create_all)
Step 1: Discover ETF universe (always re-run fetch())
Step 2: Load ETFs into DB (load_etfs, with limit if set)
Step 3: Per-CIK processing loop:
  For each CIK (alphabetical, limited by --limit):
    a. Check SEC for latest filing dates per form type
    b. Compare against processing_log
    c. Run only parsers with new filings (or all parsers if never processed)
    d. Update processing_log
    e. Clear edgartools cache
Step 4: Print summary (N processed, N skipped, N failed)
```

### Per-CIK Parser Order
Within each CIK, parsers run in this order:
1. nport (NPORT-P filings)
2. ncsr (N-CSR filings)
3. prospectus (485BPOS filings)
4. finhigh (N-CSR Financial Highlights)
5. flows (24F-2NT filings)

### Error Handling
- Continue on per-CIK failure, log error
- Report summary at end

---

## Phase 1: Schema Changes

### US-1: Add `processing_log` table

New model:

```python
class ProcessingLog(Base):
    __tablename__ = "processing_log"
    __table_args__ = (
        UniqueConstraint("cik", "parser_type", name="processing_log_cik_parser_uniq"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cik: Mapped[str] = mapped_column(String(10), nullable=False)
    parser_type: Mapped[str] = mapped_column(String(20), nullable=False)
    last_run_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    latest_filing_date_seen: Mapped[date] = mapped_column(Date, nullable=False)
```

`parser_type` values: `"nport"`, `"ncsr"`, `"prospectus"`, `"finhigh"`, `"flows"`

**Acceptance criteria:**
- Table created by `Base.metadata.create_all()`
- Existing tests still pass
- New test: insert a ProcessingLog row, verify unique constraint on (cik, parser_type)

### US-2: Add `filing_date` column to all data tables

Add a `filing_date: Mapped[date] = mapped_column(Date, nullable=False)` column to these 10 tables:

| Table | Current Unique Constraint | New Unique Constraint |
|-------|--------------------------|----------------------|
| Holding | (none, has indexes only) | Add UniqueConstraint("etf_id", "report_date", "cusip", "filing_date") |
| Derivative | (none, has indexes only) | Add UniqueConstraint("etf_id", "report_date", "derivative_type", "underlying_name", "filing_date") |
| Performance | (etf_id, fiscal_year_end) | (etf_id, fiscal_year_end, filing_date) |
| FeeExpense | (etf_id, effective_date) | (etf_id, effective_date, filing_date) |
| ShareholderFee | (etf_id, effective_date) | (etf_id, effective_date, filing_date) |
| ExpenseExample | (etf_id, effective_date) | (etf_id, effective_date, filing_date) |
| FlowData | (cik, fiscal_year_end) | (cik, fiscal_year_end, filing_date) |
| PerShareOperating | (etf_id, fiscal_year_end) | (etf_id, fiscal_year_end, filing_date) |
| PerShareDistribution | (etf_id, fiscal_year_end) | (etf_id, fiscal_year_end, filing_date) |
| PerShareRatios | (etf_id, fiscal_year_end) | (etf_id, fiscal_year_end, filing_date) |

**Acceptance criteria:**
- All 10 tables have `filing_date` column (Date, NOT NULL)
- Unique constraints updated to include `filing_date`
- `docs/SCHEMA.md` updated
- All existing tests updated to supply `filing_date` values
- All tests pass

---

## Phase 2: Parser Changes

### US-3: Update each parser to set `filing_date` and log to `processing_log`

For each parser (`nport`, `ncsr`, `prospectus`, `finhigh`, `flows`):

1. **Set `filing_date`** on every row inserted. The filing date comes from the edgartools filing object (`filing.filing_date` or `filing.date`).

2. **Upsert behavior preserved** — the unique constraint now includes `filing_date`, so:
   - Same filing processed twice = same filing_date = upsert (idempotent, no duplicate)
   - New filing (different date) = new row
   - Amendment (same report period, different filing_date) = new row

3. **Update `processing_log`** after successfully processing a CIK:
   ```python
   stmt = insert(ProcessingLog).values(
       cik=cik,
       parser_type="nport",  # or ncsr, prospectus, etc.
       last_run_at=datetime.now(),
       latest_filing_date_seen=latest_filing_date,
   ).on_conflict_do_update(
       index_elements=["cik", "parser_type"],
       set_={"last_run_at": datetime.now(), "latest_filing_date_seen": latest_filing_date},
   )
   ```

4. **Extract per-CIK processing functions** so `run-all` can call them directly:
   - Each parser should expose `_process_cik_<parser>(cik, session, ...)` (most already do)
   - The `parse_<parser>()` entry point continues to work for standalone CLI use

**Parser-to-form mapping** (for SEC API queries):

| Parser | SEC Form Type |
|--------|--------------|
| nport | NPORT-P |
| ncsr | N-CSR |
| prospectus | 485BPOS |
| finhigh | N-CSR |
| flows | 24F-2NT |

Note: `ncsr` and `finhigh` both use N-CSR filings. The freshness check should use one SEC API call for both.

**Acceptance criteria per parser:**
- Every inserted row has `filing_date` set
- `processing_log` updated after each CIK
- Running a parser twice for the same CIK produces no duplicate rows
- Running a parser after a new filing is available produces a new row
- All existing tests updated and passing
- New test: verify `processing_log` is written after successful processing
- New test: verify `filing_date` is set on inserted rows

---

## Phase 3: Intelligent `run-all` Command

### US-4: Per-CIK orchestration with freshness detection

Replace the current `run-all` (which calls each parser in bulk) with per-CIK processing:

```python
def run_all(limit):
    # Step 0: Ensure tables
    engine = get_engine()
    Base.metadata.create_all(engine)

    # Step 1: Discover
    fetch()

    # Step 2: Load ETFs
    load_etfs(limit=limit)

    # Step 3: Get CIK list from DB
    ciks = get_all_ciks(limit=limit)  # SELECT DISTINCT cik FROM etf ORDER BY cik

    processed = 0
    skipped = 0
    failed = 0

    for cik in ciks:
        try:
            # Check SEC for latest filing dates
            latest_filings = check_sec_filing_dates(cik)
            # Compare against processing_log
            needed_parsers = get_stale_parsers(cik, latest_filings)

            if not needed_parsers:
                skipped += 1
                continue

            # Run only needed parsers
            for parser_type in needed_parsers:
                run_parser_for_cik(cik, parser_type)

            processed += 1
        except Exception:
            failed += 1
            logger.exception(f"Failed to process CIK {cik}")
        finally:
            clear_edgartools_cache()

    click.echo(f"Done: {processed} processed, {skipped} skipped, {failed} failed")
```

### Freshness Detection Logic

```python
def get_stale_parsers(cik, latest_sec_filings):
    """Return list of parser_types that need to run for this CIK."""
    needed = []
    for parser_type, form_type in PARSER_FORM_MAP.items():
        sec_latest_date = latest_sec_filings.get(form_type)
        if sec_latest_date is None:
            continue  # No filings of this type for this CIK

        log_entry = get_processing_log(cik, parser_type)
        if log_entry is None:
            needed.append(parser_type)  # Never processed
        elif sec_latest_date > log_entry.latest_filing_date_seen:
            needed.append(parser_type)  # New filing available
    return needed
```

### SEC Filing Date Check

For each CIK, make one call per form type to get the latest filing date:
```python
company = Company(cik)
filings = company.get_filings(form="NPORT-P")
latest_date = filings[0].filing_date if len(filings) > 0 else None
```

Since `ncsr` and `finhigh` both use N-CSR, make one SEC call and share the result.

**Acceptance criteria:**
- `run-all` processes CIK by CIK, not parser by parser
- CIKs with no new filings are skipped
- Never-processed CIKs run all parsers
- Cache cleared after each CIK
- Summary printed at end
- `--limit N` limits total CIKs processed
- Running `run-all` twice with no new SEC filings = all CIKs skipped
- New test: mock SEC API, verify only stale parsers are invoked
- New test: verify skip count when no new filings
- New test: verify cache cleanup called per CIK

---

## Out of Scope
- PostgreSQL support (deferred)
- Parallel processing
- Backward compatibility shims
- `--offset`, `--fresh-only`, `--new-only` flags
- Individual parser CLI commands already work; no changes to their CLI interface needed

## Verification

After each phase:
```
python -m pytest tests/ -q
```

After Phase 3, full integration test:
```
rm -f etf_pipeline.db
export DATABASE_URL="sqlite:///etf_pipeline.db"
etf-pipeline run-all --limit 2
# Verify: 2 CIKs processed, 0 skipped
etf-pipeline run-all --limit 2
# Verify: 0 processed, 2 skipped (no new filings)
```
