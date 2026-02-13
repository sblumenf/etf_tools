# Specification Draft: ncsr parser

*Interview in progress - Started: 2026-02-13*

## Overview
Parse N-CSR/N-CSRS filings to populate the Performance table with per-ETF returns, expense ratio, and portfolio turnover.

## Data Source Analysis

### Company Facts API — Available Fields
The SEC EDGAR XBRL company facts API (`/api/xbrl/companyfacts/CIK{cik}.json`) provides per-series data via `dei:LegalEntityAxis` context dimensions.

| Performance Field | XBRL Element | In API? | Notes |
|---|---|---|---|
| return_1yr | `oef:AvgAnnlRtrPct` | YES | Single element, period encoded in XBRL context |
| return_5yr | `oef:AvgAnnlRtrPct` | YES | Same element, different context period |
| return_10yr | `oef:AvgAnnlRtrPct` | YES | Same element, different context period |
| return_since_inception | `oef:AvgAnnlRtrPct` + `oef:PerfInceptionDate` | YES | Needs inception date for identification |
| portfolio_turnover | `oef:PortfolioTurnoverRate` or `us-gaap:InvestmentCompanyPortfolioTurnover` | YES | pureItemType (decimal) |
| expense_ratio_actual | `oef:ExpenseRatioPct` | YES | Percent |

### NOT in Company Facts API
| Performance Field | Why Not | Alternative |
|---|---|---|
| benchmark_name | Encoded as `BroadBasedIndexAxis` dimension members, not a text field | Parse context dimensions |
| benchmark_return_1yr/5yr/10yr | Uses same `AvgAnnlRtrPct` with `BroadBasedIndexAxis` dimension | Parse context dimensions |
| distribution_total | Not in OEF taxonomy (only narrative `DistOfCapitalTextBlock`) | iXBRL HTML parsing |
| dist_ordinary_income | Not in OEF taxonomy | iXBRL HTML parsing |
| dist_qualified_dividend | Not in OEF taxonomy | iXBRL HTML parsing |
| dist_ltcg | Not in OEF taxonomy | iXBRL HTML parsing |
| dist_stcg | Not in OEF taxonomy | iXBRL HTML parsing |
| dist_return_of_capital | Not in OEF taxonomy | iXBRL HTML parsing |

### Key Technical Detail
Returns use ONE element (`AvgAnnlRtrPct`) with different XBRL contexts encoding the time period (1yr, 5yr, 10yr, inception). Benchmark returns use the SAME element but with a `BroadBasedIndexAxis` dimension. Must parse context dimensions to distinguish.

## Scope Decision
- **User chose:** TBD (awaiting answer on MVP scope given actual data availability)

## Technical Approach
- **User chose:** TBD (company facts API confirmed to have per-series data via LegalEntityAxis)

## Implementation Pattern
Follow existing parser patterns (flows.py, nport.py):
- Entry point: `parse_ncsr(cik=None, limit=None, clear_cache=True)`
- Per-ETF processing (not per-CIK like flows — Performance has etf_id FK)
- Upsert logic: unique on (etf_id, fiscal_year_end)
- CLI: `etf-pipeline ncsr [--cik CIK] [--limit N] [--keep-cache]`

## Open Questions
- MVP scope: which fields to include?
- Should benchmark data (via context dimensions) be in scope?
- Distribution fields: defer entirely or attempt?

---
*Interview notes will be accumulated below as the interview progresses*
---

