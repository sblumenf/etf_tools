# PM Plan: Benchmark Name Mapping Pipeline

## Current State

- 450 distinct benchmark names stored as raw XBRL member IDs in `performance.benchmark_name`
- The OEF taxonomy does NOT contain the actual index member elements — ALL index members are filer-created extensions
- This means every filing's extension taxonomy is the authoritative source for label mappings
- The NCSR parser (`src/etf_pipeline/parsers/ncsr.py`) stores raw member IDs without any label resolution
- No mapping table exists

## Key Discovery

The standard OEF taxonomy only defines `BroadBasedIndexAxis` and `BroadBasedIndexDomain` (the dimension structure). The actual members like `StandardPoors500IndexMember` are defined in each filer's **extension taxonomy** submitted with their filing. The human-readable labels live in the filing's extension label linkbase.

This means:
1. There is no single master label file to parse
2. Labels must be extracted from individual filings' XBRL extension taxonomies
3. The edgartools library's `filing.xbrl()` object may already have access to these labels
4. Once extracted, labels should be cached in a DB mapping table to avoid re-fetching

## Status: COMPLETE

## Steps

1. [x] **Add `BenchmarkMapping` model to `models.py`**
   - New table: `benchmark_mapping`
   - Columns: `id`, `member_id` (unique), `readable_name`, `source` (enum: taxonomy_label, filing_html, manual), `first_seen_cik`, `first_seen_date`, `created_at`, `updated_at`
   - File: `src/etf_pipeline/models.py`
   - Agent: implementer

2. **Create Alembic migration**
   - Add `benchmark_mapping` table
   - File: `alembic/versions/e4f5a6b7c8d9_add_benchmark_mapping_table.py`
   - Agent: implementer

3. **Research edgartools XBRL label access**
   - Investigate whether `filing.xbrl()` exposes extension taxonomy labels
   - If not, determine how to fetch the filing's extension schema from EDGAR
   - Test with a real filing that has a known custom member
   - Agent: researcher

4. **Build label extraction module**
   - New file: `src/etf_pipeline/benchmark_labels.py`
   - Function: `resolve_benchmark_label(member_id, filing) -> Optional[str]`
     - Check DB mapping table first (cache hit)
     - If miss, extract label from filing's XBRL extension taxonomy
     - If still no label, attempt HTML narrative extraction as fallback
     - Upsert resolved label into mapping table
   - Function: `load_taxonomy_labels(session)` — pre-populate from taxonomy if possible
   - Agent: implementer

5. **Integrate into NCSR parser**
   - After extracting `benchmark_name` in `parse_ncsr()`, call `resolve_benchmark_label()`
   - Store both raw `member_id` and resolved `readable_name`
   - Minimal change: add a call after line 244 and line 303 of `ncsr.py`
   - File: `src/etf_pipeline/parsers/ncsr.py`
   - Agent: implementer

6. **Backfill existing data**
   - CLI command or script to iterate all distinct `benchmark_name` values
   - For each, attempt to resolve via taxonomy label extraction
   - File: add command to `src/etf_pipeline/cli.py`
   - Agent: implementer

7. **Update API layer**
   - Join `Performance` with `BenchmarkMapping` to return `readable_name`
   - File: `src/etf_pipeline/xray/service.py` and/or `src/etf_pipeline/api/routes/xray.py`
   - Agent: implementer

8. **Write tests**
   - Test `BenchmarkMapping` model CRUD
   - Test label extraction logic
   - Test NCSR parser integration with mapping
   - Files: `tests/test_benchmark_mapping.py`
   - Agent: tester

9. **Review all changes**
   - Agent: reviewer

## Execution Strategy

- **Sequential dependencies**: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9
- Step 3 (research edgartools labels) is critical — it determines the implementation approach for Step 4
- Steps 6 and 7 can run in parallel after Step 5

## Risks

- **edgartools may not expose extension taxonomy labels** — if so, we need to fetch and parse extension schema files directly from EDGAR (HTTP requests + XML parsing)
- **Filing extension schemas may not always contain labels** — some filers may define members without labels, requiring HTML fallback
- **The ~40 opaque `bench20XX...` names** may not have labels in any source — may need manual mapping or flagging as "unresolved"
- **Rate limiting on EDGAR** — backfilling 450 names may require throttled requests

## Estimated Scope

- Files affected: 6-7
- New files: 2 (benchmark_labels.py, test_benchmark_mapping.py, migration)
- Subagents needed: researcher, implementer, tester, reviewer
