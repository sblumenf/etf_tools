# PM Plan: Fix 7 Pipeline Bugs

## Current State

The ETF data pipeline has 7 bugs that primarily affect large multi-fund issuers, UITs, and funds with older filings. The pipeline works correctly for simple single-fund issuers (mostly Vanguard). All bugs have been diagnosed with exact file:line references and database evidence.

## Steps

### Step 1: Fix `map_return_period` dead zone (parser_utils.py)
- **File**: `src/etf_pipeline/parser_utils.py:195`
- **Change**: Replace `years > 10 + tolerance` with a fallback that treats any unrecognized period > 1 year as `return_since_inception`
- **Subagent**: implementer
- **Risk**: Low. Only affects the else branch. Existing 1yr/5yr/10yr matching is untouched.

### Step 2: Fix N-CSR unconditional performance upsert (ncsr.py)
- **File**: `src/etf_pipeline/parsers/ncsr.py:343-362`
- **Change**: Guard the `upsert_record` call — only write a Performance row if `returns_data` is non-empty OR no row with non-null returns already exists for that (etf_id, fiscal_year_end)
- **Subagent**: implementer
- **Risk**: Medium. Must preserve expense_ratio_actual and portfolio_turnover writes when they're the only data.

### Step 3: Fix performance query tiebreaker (service.py)
- **File**: `src/etf_pipeline/xray/service.py:108-114`
- **Change**: Add secondary sort `desc(Performance.filing_date)` and prefer rows where return_1yr is not null
- **Subagent**: implementer
- **Risk**: Low. Read-only query change.

### Step 4: Raise MAX_FILINGS cap (ncsr.py)
- **File**: `src/etf_pipeline/parsers/ncsr.py:91`
- **Change**: Increase `MAX_FILINGS` from 50 to 500
- **Subagent**: implementer
- **Risk**: Low. Increases processing time for large CIKs but correctness is more important.

### Step 5: Widen prospectus lookback window (prospectus.py)
- **File**: `src/etf_pipeline/parsers/prospectus.py:23`
- **Change**: Increase `LOOKBACK_DAYS` from 547 to 1095 (3 years)
- **Subagent**: implementer
- **Risk**: Low. One constant change. More filings processed on next run.

### Step 6: Fix fee sanity check blind spot (prospectus.py)
- **File**: `src/etf_pipeline/parsers/prospectus.py:393-399`
- **Change**: Lower threshold from `Decimal('0.50')` to `Decimal('0.10')` (10%). Any raw fee value > 0.10 is almost certainly mis-scaled.
- **Subagent**: implementer
- **Risk**: Medium. Must not double-correct values that already have correct scale. The function only runs on values that passed through convert_numeric_value, so if scale was applied correctly the value will already be small.

### Step 7: Fix benchmark label guards (benchmark_labels.py)
- **File**: `src/etf_pipeline/benchmark_labels.py:121-148`
- **Change**: In `_get_best_label`, after extracting label, check if `label.replace(' ', '') == member_id` or similar — if so, return None to fall through to heuristic. In `_clean_label`, add normalization: strip "NACC2 Index:" and similar prefixes, fix "U S" -> "U.S.".
- **Subagent**: implementer
- **Risk**: Low. Only affects new resolutions and re-resolutions.

### Step 8: Fix resolve-benchmarks CLI skip logic (cli.py)
- **File**: `src/etf_pipeline/cli.py:380-400`
- **Change**: The filter that skips entries with non-null `readable_name` should also re-process entries where `readable_name` equals `member_id` (the stuck entries).
- **Subagent**: implementer
- **Risk**: Low. Only affects CLI command behavior.

### Step 9: Add N-30D filing type for UITs (ncsr.py)
- **File**: `src/etf_pipeline/parsers/ncsr.py:121`
- **Change**: For CIKs where all ETFs lack series_id (UITs), also fetch `form="N-30D"` filings. N-30D is HTML-only (not iXBRL), so this requires an HTML parsing path for the financial highlights table. **This is the most complex step and may need to be scoped separately.**
- **Subagent**: implementer
- **Risk**: High. New parsing logic for a different filing format. Recommend implementing as a separate follow-up if time is constrained.

### Step 10: Run tests
- **Subagent**: tester
- **Run**: All existing tests to verify no regressions. Add targeted tests for the fixes.

### Step 11: Review all changes
- **Subagent**: reviewer
- **Review**: All modified files for correctness, edge cases, and style consistency.

## Execution Strategy

**Parallel Group A** (independent, low-risk one-liners):
- Step 1 (map_return_period)
- Step 4 (MAX_FILINGS)
- Step 5 (LOOKBACK_DAYS)

**Parallel Group B** (independent, medium complexity):
- Step 6 (fee sanity check)
- Step 7 + Step 8 (benchmark labels + CLI — same logical fix, do together)

**Sequential after Group A**:
- Step 2 (ncsr upsert guard) — depends on understanding Step 1's impact on return data
- Step 3 (service query tiebreaker) — should follow Step 2

**Deferred**:
- Step 9 (N-30D for UITs) — most complex, recommend as separate follow-up

**After all code changes**:
- Step 10 (tests) — sequential
- Step 11 (review) — sequential after tests

## Risks

1. **Step 2 edge case**: If we guard the performance upsert too aggressively, we lose expense_ratio_actual and portfolio_turnover data for ETFs that only have those fields. Need to check if those fields are displayed anywhere.
2. **Step 6 double-correction**: If a filing already had correct `scale="-2"` applied, the value is already small and won't trigger the threshold. Safe.
3. **Step 9 complexity**: N-30D HTML parsing is a new capability. Financial highlights tables vary between issuers. Recommend deferring to a separate task.
4. **Database state**: Code fixes alone won't fix existing bad data. After deploying fixes, a re-run of the parsers is needed to backfill.

## Estimated Scope

- **Files affected**: 6 (parser_utils.py, ncsr.py, service.py, prospectus.py, benchmark_labels.py, cli.py)
- **Subagents needed**: implementer (x2-3 parallel), tester, reviewer
- **Steps 1-8**: Implementable now
- **Step 9**: Recommend deferring (new parsing capability)
