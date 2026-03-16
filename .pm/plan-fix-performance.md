## PM Plan: Fix performance data coverage across all ETF types — COMPLETE

### Steps

- [x] Step 1: Add performance extraction to prospectus parser (implementer)
  - RR taxonomy: rr:AverageAnnualReturnYear01/05/10/SinceInception
  - OEF taxonomy: oef:AvgAnnlRtrPct with period-based mapping
  - Portfolio turnover extraction
  - Writes to Performance model via upsert_record()

- [x] Step 2: Add benchmark context handling for prospectus (implementer)
  - PerformanceMeasureAxis dimension detection in context parsing
  - Fund vs benchmark return separation
  - Benchmark name extraction and resolve_benchmark_label() integration

- [x] Step 3: Add UIT performance HTML fallback (implementer)
  - _extract_performance_from_html_table() handles vertical and horizontal layouts
  - _write_uit_html_performance() helper (deduplicated)
  - UIT sentinel-based early-exit integration
  - Works for SPY/DIA/MDY pure HTML filings

- [x] Step 4: Fix N-CSR parser UIT handling (implementer)
  - uit_fallback_etf for CIKs with exactly 1 NULL-class_id ETF
  - Synthesizes NULL ClassAxis column when absent
  - UIT fallback block extracts fund returns from filing-level facts

- [x] Step 5: Add benchmark label batch resolution CLI command (implementer)
  - resolve-benchmarks command with --dry-run and --limit flags
  - Pass 1: heuristic label cleanup (suffix stripping, CamelCase, S&P expansion)
  - Pass 2: XBRL-based resolution via N-CSR re-fetch
  - SP regex anchored to prevent false positives

- [x] Step 6: Tests written (tester)
  - 12 prospectus performance tests (RR, OEF, benchmark, HTML fallback, UIT)
  - 4 N-CSR UIT fallback tests
  - 13 benchmark resolution tests (heuristic + CLI integration)

- [x] Step 7: Full test suite — 491 passed, 0 failed

- [x] Step 8: Final review — PASS (3 issues found and fixed)
  - Fixed: SP regex false positives
  - Fixed: return period catch-all → now returns None for 2yr/3yr/etc.
  - Fixed: duplicated UIT HTML block extracted to helper
