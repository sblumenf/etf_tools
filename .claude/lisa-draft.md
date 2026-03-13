# Specification Draft: Backfill Command

*Interview in progress - Started: 2026-03-07*

## Overview
Add a one-time backfill capability to the existing ETF pipeline. The pipeline currently only processes recent SEC filings (forward-looking). Backfill allows populating the database with historical filings released before the pipeline was first run on 2026-02-25.

This is a **new command** on the existing CLI tool — not a separate application. It writes to the same database, uses the same parsers, and the same deduplication logic prevents duplicates.

## Key Decisions (from interview)

### Batching & Commits
- **Per-filing commit for ALL parsers** during backfill (not just NPORT)
- Progress logging to console for all parsers (e.g., "Processed 50/200 filings for CIK X")

### Error Handling
- **Log, skip, and collect**: Log errors with filing accession number and CIK, skip that filing, continue processing. Collect all failures into a summary report at the end.

### Data Safety
- **No special protection needed**: User is not married to existing data and can re-run if modifications happen. The original spec's suggestion to skip narrative text (objective_text, strategy_text, principal_risks) during backfill is NOT needed.
- Parser audit confirmed: Only prospectus writes "current state" fields on the ETF record. Finhigh, NCSR, Flows, NPORT only create historical rows.

### Run Tracking
- Use standard database engineering practices: add created_at/updated_at timestamps to processing_log

### CLI Surface
- **Standalone `backfill` command only** — no `--backfill` flags on existing parser commands
- `--parser` flag on the backfill command to select specific parsers
- Simpler, one code path

## Constraints
[From docs/backfill-spec.md - to be refined]

### Files to Modify
- `src/etf_pipeline/parser_utils.py` — processing log fix, date-filter helper
- `src/etf_pipeline/parsers/nport.py` — add date-range support, bypass 1-per-series limit
- `src/etf_pipeline/parsers/ncsr.py` — add date-range support, bypass MAX_FILINGS = 10
- `src/etf_pipeline/parsers/finhigh.py` — add date-range support, bypass MAX_FILINGS = 10
- `src/etf_pipeline/parsers/prospectus.py` — add date-range support, bypass LOOKBACK_DAYS = 547
- `src/etf_pipeline/parsers/flows.py` — add date-range support, bypass filings[0] limit
- `src/etf_pipeline/cli.py` — add `backfill` command (no --backfill flags on existing commands)

### Files NOT to Modify
- `src/etf_pipeline/models.py` — schema already supports unlimited historical data (except possibly adding timestamps)
- Alembic migrations — no schema changes needed (unless adding timestamps)
- `run_all` command logic — backfill is a separate manual operation

### New Files Allowed
- Test files in `tests/` for backfill functionality

### New Dependencies Allowed
- No

### Out of Scope
- Changing `run_all` behavior
- Building a scheduler or cron job for backfill
- Schema migrations beyond possible timestamp additions

## Problem Statement
[From docs/backfill-spec.md - carried forward]

## User Stories
[To be filled - continuing interview]

## Technical Design
[To be filled - continuing interview]

## Implementation Phases
[To be filled - continuing interview]

---
*Interview notes accumulated above*
