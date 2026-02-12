# NPORT-P Parser Specification — DRAFT

## Overview
Build an NPORT-P parser that extracts the latest holdings and derivatives for all ETFs under a given CIK, using edgartools `FundReport.from_filing()`. Includes a prerequisite `load-etfs` CLI command.

## Decisions Made
- **Processing model**: One CIK at a time. Each CIK may contain multiple series (ETFs).
- **Scope**: Latest NPORT-P filing per series only. No historical backfill.
- **CLI input**: Both `load-etfs` and `nport` commands accept optional `--cik` (single CIK) and `--limit` (number of CIKs) parameters. If neither provided, process all.
- **CIK ordering**: Alphabetical by CIK for deterministic runs.
- **Re-run behavior**: Skip if holdings already exist for that ETF + report_date.
- **Error handling**: Log warning, skip CIK, continue to next. Summary at end.
- **Field mapping**: Best-effort — map what fits the schema from edgartools objects, don't over-engineer.
- **Derivatives**: Best-effort extraction from DerivativeInfo sub-objects.
- **Logging**: Python logging module (INFO for progress, WARNING for skips, DEBUG for details).
- **ETF.last_fetched**: Updated after successful extraction for each ETF.
- **ETF loading**: New `load-etfs` CLI command (separate from discover).
- **Issuer name**: Looked up via `Company(cik).name` from edgartools.
- **File layout**: `src/etf_pipeline/parsers/nport.py` (parsers subpackage).

## Open Questions
- Test strategy details
- Exact field mapping from InvestmentOrSecurity / DerivativeInfo to models
