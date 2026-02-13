# Specification Draft: Financial Highlights Parser

*Interview in progress - Started: 2026-02-13*

## Overview
Parse the Financial Highlights HTML tables from N-CSR filings to extract per-share operating data and per-share distribution data for ETFs.

## Problem Statement
N-CSR filings contain Financial Highlights tables with per-share distribution data (dividends from net investment income, distributions from capital gains, return of capital) that is NOT available in XBRL. The SEC explicitly excluded Financial Highlights from iXBRL tagging requirements. The data must be extracted via HTML table parsing using a positional approach, validated with the mathematical identity: NAV_begin + operations - distributions = NAV_end.

## Key Decisions Made
- **Scope**: Extract ALL Financial Highlights per-share fields (not just distributions)
- **Data model**: Two new tables (`per_share_operating` + `per_share_distribution`)
- **History depth**: Most recent year only per filing
- **Validation**: Insert data but flag when math doesn't balance (`math_validated` boolean)
- **Filing discovery**: Reuse the multi-filing-per-CIK approach from N-CSR XBRL parser
- **Fund matching**: Document structure (series_id/class_id from SGML/iXBRL) with fallback to fuzzy string matching

## Data Model

### Table: `per_share_operating`
FK to ETF, UK on (etf_id, fiscal_year_end)

| Column | Type | Description |
|--------|------|-------------|
| id | int PK | Auto-increment |
| etf_id | int FK | References ETF |
| fiscal_year_end | date | End of reporting period |
| nav_beginning | Numeric(10,4) | Net asset value per share, beginning of period |
| net_investment_income | Numeric(10,4) | Per-share net investment income/loss |
| net_realized_unrealized_gain | Numeric(10,4) | Per-share net realized and unrealized gains/losses |
| total_from_operations | Numeric(10,4) | Sum of investment income + gains |
| nav_end | Numeric(10,4) | Net asset value per share, end of period |
| total_return | Numeric(8,5) | Total return for the period as decimal |
| math_validated | bool | True if NAV_begin + operations - distributions = NAV_end |

### Table: `per_share_distribution`
FK to ETF, UK on (etf_id, fiscal_year_end)

| Column | Type | Description |
|--------|------|-------------|
| id | int PK | Auto-increment |
| etf_id | int FK | References ETF |
| fiscal_year_end | date | End of reporting period |
| dist_net_investment_income | Numeric(10,4) | Dividends from net investment income (negative = distribution paid) |
| dist_realized_gains | Numeric(10,4) | Distributions from realized capital gains |
| dist_return_of_capital | Numeric(10,4) nullable | Return of capital distributions |
| dist_total | Numeric(10,4) | Total distributions |

## Parsing Strategy
1. Find "Financial Highlights" headings in N-CSR HTML
2. Parse the next `<table>` after each heading
3. Use POSITIONAL extraction (not label matching):
   - Row 1: NAV beginning
   - Rows 2-N: Investment operations section
   - Row after "total from operations": start of distributions
   - Rows until next NAV row: distribution items
   - NAV end row
4. Validate: NAV_begin + total_operations - total_distributions = NAV_end (within tolerance)
5. Match each Financial Highlights section to ETF via series_id/class_id from document structure, fallback to fuzzy fund name matching

## Open Questions
- How to handle the ratios/supplemental section (expense ratio, turnover, net assets) — duplicate of XBRL data?
- Tolerance for math validation (rounding differences)?
- CLI command name?

---
*Interview notes accumulated during session*
---
