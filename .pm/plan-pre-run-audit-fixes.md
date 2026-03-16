# PM Plan: Fix Critical, High, and Medium Pipeline Issues (Pre-Run Audit)

## Current State
The pipeline has 17 issues across critical/high/medium severity that could cause failures, data loss, or silent corruption during a full multi-hour run over 2500+ ETFs.

## Steps

### Step 1: Fix db.py — WAL mode, connection timeout, SQLite-only PRAGMA
- **Status:** [x] DONE

### Step 2: Fix cli.py — Queue cleanup, proc.join timeout, staleness fallback
- **Status:** [x] DONE (+ review fix: utcnow -> now)

### Step 3: Fix nport.py — elif for swaption
- **Status:** [x] DONE

### Step 4: Fix prospectus.py — Replace SIGALRM, fix backfill_mode logic
- **Status:** [x] DONE (+ review fix: simplified except clause)

### Step 5: Fix finhigh.py — Elevate log level
- **Status:** [x] DONE

### Step 6: Fix ncsr.py — UIT satisfied key consistency
- **Status:** [x] DONE

### Step 7: Fix flows.py — Broaden exception catch
- **Status:** [x] DONE

### Step 8: Fix discover.py — Add retry logic and error handling
- **Status:** [x] DONE

### Step 9: Fix load_etfs.py — Warn on empty series mapping
- **Status:** [x] DONE

### Step 10: Fix benchmark_labels.py — Add logging on flush failure
- **Status:** [x] DONE (cache reverted per review)

### Step 11: Run tests — 489 pass, 0 new failures
- **Status:** [x] DONE

### Step 12: Review + fix review findings
- **Status:** [x] DONE — 3 review findings fixed

## Execution Strategy
- **Parallel batch 1:** Steps 1, 3, 4, 5, 6, 7, 9, 10 (independent files)
- **Sequential after batch 1:** Steps 2 and 8 (larger, more complex changes)
- **Sequential final:** Step 11 (tests), then Step 12 (review)

## Risks
- SIGALRM replacement changes timeout behavior
- SQLite WAL mode may affect test fixtures
- Staleness fallback logic needs care to avoid re-processing everything

## Estimated Scope
- Files affected: 10
- Subagents needed: implementer, tester, reviewer
