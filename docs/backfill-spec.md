# Backfill Feature Specification

## Overview

Add a one-time backfill capability to the existing ETF pipeline. The pipeline currently only processes recent SEC filings (forward-looking). Backfill allows populating the database with historical filings that were released before the pipeline was first run on 2026-02-25.

This is a **new command** on the existing CLI tool — not a separate application. It writes to the same database, uses the same parsers, and the same deduplication logic prevents duplicates. It is designed to be run once (or a few times during testing), not on a recurring schedule.

## Constraints

### Files to Modify
- `src/etf_pipeline/parser_utils.py` — processing log fix, date-filter helper
- `src/etf_pipeline/parsers/nport.py` — add date-range support, bypass 1-per-series limit
- `src/etf_pipeline/parsers/ncsr.py` — add date-range support, bypass `MAX_FILINGS = 10`
- `src/etf_pipeline/parsers/finhigh.py` — add date-range support, bypass `MAX_FILINGS = 10`
- `src/etf_pipeline/parsers/prospectus.py` — add date-range support, bypass `LOOKBACK_DAYS = 547`
- `src/etf_pipeline/parsers/flows.py` — add date-range support, bypass `filings[0]` limit
- `src/etf_pipeline/cli.py` — add `backfill` command and `--backfill` flags on existing commands

### Files NOT to Modify
- `src/etf_pipeline/models.py` — the database schema already supports unlimited historical data
- Alembic migrations — no schema changes needed
- `run_all` command logic — backfill is a separate manual operation

### New Files Allowed
- Test files in `tests/` for backfill functionality

### New Dependencies Allowed
- No. `edgartools` already supports date-range filtering on `get_filings()` natively.

### Existing Code to Reuse
- All parser logic — the same code that parses a 2026 filing parses a 2020 filing
- `upsert_record()` in `parser_utils.py` — handles deduplication via unique constraints
- Skip-if-exists check in NPORT parser — prevents duplicate holdings
- `edgartools` `get_filings(form=..., filing_date=(...))` — accepts a date tuple for range queries

### Out of Scope
- Changing `run_all` behavior — the automated pipeline is untouched
- Schema migrations — tables already have `filing_date`/`report_date` columns
- Building a scheduler or cron job for backfill — this is a manual one-time operation

---

## Problem Statement

The pipeline was first run on 2026-02-25. Due to hardcoded limits in each parser, only a shallow slice of recent data was captured:

| Parser | Hardcoded Limit | What Was Captured | What's Missing |
|--------|----------------|-------------------|----------------|
| **NPORT** (holdings) | 1 filing per series (`_get_latest_filings_per_series`) | ~Jan 2026 snapshot only | Every prior quarterly report |
| **NCSR** (performance) | `MAX_FILINGS = 10` | ~5 years back to ~2021 | Everything before 2021 |
| **Finhigh** (per-share data) | `MAX_FILINGS = 10` | ~5 years back to ~2021 | Everything before 2021 |
| **Prospectus** (fees/strategy) | `LOOKBACK_DAYS = 547` | Aug 2024 – Feb 2026 | Everything before Aug 2024 |
| **Flows** (sales/redemptions) | `filings[0]` (latest only) | Last fiscal year only | All prior fiscal years |

The database schema supports unlimited historical data. The bottleneck is purely in the parsers.

---

## Desired Behavior

### New CLI Command

```bash
# Full backfill — all CIKs, all parsers, full date range
etf-pipeline backfill --from-date 2020-01-01 --to-date 2025-12-31

# Single ETF (for testing)
etf-pipeline backfill --from-date 2023-01-01 --to-date 2024-12-31 --cik 0001234567

# First N ETFs (for testing)
etf-pipeline backfill --from-date 2024-01-01 --to-date 2024-12-31 --limit 5

# Specific parser(s) only
etf-pipeline backfill --from-date 2023-01-01 --to-date 2024-12-31 --parser flows
etf-pipeline backfill --from-date 2023-01-01 --to-date 2024-12-31 --parser ncsr --parser finhigh
```

### Backfill Flag on Existing Commands

```bash
# Run a single parser in backfill mode
etf-pipeline flows --backfill --from-date 2023-01-01 --to-date 2024-12-31 --cik 0001234567
```

### Scope Controls

| Flag | Purpose |
|------|---------|
| `--from-date` | Start of date range (YYYY-MM-DD) |
| `--to-date` | End of date range (YYYY-MM-DD) |
| `--cik` | Process only one CIK |
| `--limit` | Process only the first N CIKs |
| `--parser` | Run only specific parser(s) — on the `backfill` command only |

These controls exist so the user can start small during testing and scale up to a full backfill.

### Behavior Rules

1. **Backfill never runs automatically.** The `run_all` command does not trigger backfill. It is always a manual operation.
2. **Backfill ignores the staleness check.** It does not consult `get_stale_parsers` or `check_sec_filing_dates`.
3. **Backfill does not corrupt the processing log.** If the log says `latest_filing_date_seen = 2025-12-31` and a backfill processes a 2022 filing, the log keeps the 2025 date. The log should only ever move forward, never backward.
4. **Deduplication is automatic.** Re-running the same backfill parameters is safe — existing data is skipped (holdings) or upserted (everything else).
5. **Normal pipeline behavior is unchanged.** When `--backfill` / `from_date` / `to_date` are not set, every parser behaves identically to today.

---

## Implementation Plan

### Step 1: Protect the Processing Log

**File:** `src/etf_pipeline/parser_utils.py`

In `update_processing_log`, change the update logic so `latest_filing_date_seen` only moves forward:

```python
# Before (current)
existing.latest_filing_date_seen = filing_date

# After
existing.latest_filing_date_seen = max(existing.latest_filing_date_seen, filing_date)
```

This is a standalone safety fix with no dependencies. It is correct for both normal and backfill runs.

### Step 2: Add a Date-Filter Helper

**File:** `src/etf_pipeline/parser_utils.py`

Add a utility that converts `from_date`/`to_date` into the tuple format `edgartools` expects for its `filing_date` parameter:

```python
def build_filing_date_filter(from_date, to_date):
    # Returns None (no filter) or ("YYYY-MM-DD", "YYYY-MM-DD") tuple
```

### Step 3: Make Each Parser Backfill-Aware

Add optional `from_date` and `to_date` parameters to each parser's entry function and its per-CIK processor. When set, the parser:
- Passes the date range to `company.get_filings(filing_date=...)`
- Bypasses its hardcoded limit
- Processes all filings in the range

When not set, behavior is identical to today.

#### 3a. Flows (simplest — start here)
- **Current:** `filings[0]` — only the latest filing
- **Backfill:** Loop over all filings in the date range

#### 3b. NCSR
- **Current:** `MAX_FILINGS = 10`, early-exit when all class_ids satisfied
- **Backfill:** Remove the cap, remove early-exit, process all filings in range

#### 3c. Finhigh
- **Current:** Same as NCSR — `MAX_FILINGS = 10` with early-exit
- **Backfill:** Same changes as NCSR

#### 3d. Prospectus
- **Current:** `LOOKBACK_DAYS = 547` cutoff, early-exit when all class_ids satisfied
- **Backfill:** Ignore the cutoff, remove early-exit
- **Special case:** Skip narrative text updates (`objective_text`, `strategy_text`, `principal_risks`) during backfill so old text doesn't overwrite current values on the ETF record

#### 3e. NPORT (most complex — do last)
- **Current:** `_get_latest_filings_per_series()` returns 1 filing per series
- **Backfill:** Return all filings per series, iterate them all
- **Deduplication:** The existing skip-if-exists check on Holdings handles this, but needs adjustment to check per `(etf_id, report_date, filing_date)` not just `etf_id`

### Step 4: Wire Up the CLI

**File:** `src/etf_pipeline/cli.py`

- Add `--backfill`, `--from-date`, `--to-date` to each existing parser command
- Add a standalone `backfill` command that accepts `--from-date`, `--to-date`, `--cik`, `--limit`, `--parser`
- Validation: `--from-date`/`--to-date` require `--backfill` on individual commands; the `backfill` command requires `--from-date` and `--to-date`

---

## Implementation Order

1. Processing log fix (Step 1) — standalone, no dependencies
2. Date-filter helper (Step 2) — standalone, no dependencies
3. Flows parser (Step 3a) — simplest parser, good proof of concept
4. NCSR + Finhigh parsers (Steps 3b, 3c) — same pattern, do together
5. Prospectus parser (Step 3d) — medium complexity
6. NPORT parser (Step 3e) — most complex, do last
7. CLI wiring (Step 4) — connect everything

Each step can be implemented and tested independently.

---

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| **SEC API rate limiting** during large backfills | Use `--cik` and `--limit` to control scope. Start small. |
| **Memory pressure** from many large NPORT filings | Commit and clear the session after each filing |
| **Old prospectus text overwrites current text** | Skip narrative text updates in backfill mode |
| **Processing log corruption** | Step 1 ensures log only moves forward |
| **Re-running backfill creates duplicates** | Existing upsert and skip-if-exists logic prevents this |
| **Breaking normal pipeline behavior** | All changes gated on `from_date`/`to_date` being set; `None` = today's behavior |

---

## Testing Workflow

Recommended approach for the user:

1. One CIK, one parser, one quarter — minutes
2. One CIK, all parsers, one year — still fast
3. 10 CIKs, all parsers, full history — maybe an hour
4. All CIKs, all parsers, full history — run once overnight

Re-running any of these is safe due to deduplication.
