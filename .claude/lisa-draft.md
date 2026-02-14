# Specification Draft: implement the 485BPOS parser

*Interview in progress - Started: 2026-02-13*

## Overview
Parse 485BPOS (post-effective amendment / prospectus) filings from SEC EDGAR to extract fee schedules and investment strategy text. Data is iXBRL-tagged using the Risk/Return Summary (RR) XBRL taxonomy.

## Decisions Made

### D1: Class scope — Only known classes
Only extract fee data for class_ids already in the ETF table. Skip unknown classes. Consistent with ncsr/finhigh parsers.

### D2: Net vs Gross — Leave NULL
If no `NetExpensesOverAssets` tag exists, leave `total_expense_net` as NULL. Don't infer.

### D3: Strategy field — Two separate fields
Add two fields to ETF table:
- `objective_text` — from `rr:ObjectivePrimaryTextBlock` (investment objective, 1-2 sentences)
- `strategy_text` — from `rr:StrategyNarrativeTextBlock` (principal strategies, detailed)

### D4: AFFE column — Add it
Add `acquired_fund_fees` Numeric(6,5) to FeeExpense model.

## Data Model Changes

### ETF table additions
- `objective_text` (Text, nullable) — Investment objective from RR ObjectivePrimaryTextBlock

### FeeExpense table additions
- `acquired_fund_fees` (Numeric(6,5), nullable) — Acquired fund fees and expenses

## RR Taxonomy Tag Mapping

| DB Field | RR Tag | Notes |
|----------|--------|-------|
| management_fee | `rr:ManagementFeesOverAssets` | Per share class |
| distribution_12b1 | `rr:DistributionAndService12b1FeesOverAssets` | Per share class |
| other_expenses | `rr:OtherExpensesOverAssets` | Per share class |
| total_expense_gross | `rr:ExpensesOverAssets` | Per share class |
| fee_waiver | `rr:FeeWaiverOrReimbursementOverAssets` | Per share class, negative value |
| total_expense_net | `rr:NetExpensesOverAssets` | Per share class, NULL if absent |
| acquired_fund_fees | `rr:AcquiredFundFeesAndExpensesOverAssets` | Per share class |
| objective_text | `rr:ObjectivePrimaryTextBlock` | Per series (LegalEntityAxis) |
| strategy_text | `rr:StrategyNarrativeTextBlock` | Per series (LegalEntityAxis) |
| filing_url | Filing metadata | URL to source 485BPOS filing |
| effective_date | `dei:DocumentPeriodEndDate` or filing date | TBD |

## XBRL Context Structure
- CIK in `xbrli:identifier`
- Series via `dei:LegalEntityAxis` → `S{number}Member`
- Share class via `rr:ProspectusShareClassAxis` → `C{number}Member`
- Fee tags are per share class (series + class context)
- Strategy/objective tags are per series (series-only context)

## Open Questions
- Effective date: use `dei:DocumentPeriodEndDate` from filing, or filing date from EDGAR index?
- HTML stripping: should strategy_text/objective_text be stored as plain text or raw HTML?
- How to handle multiple 485BPOS filings per CIK — most recent only, or iterate?

---
*Interview notes will be accumulated below as the interview progresses*
---

