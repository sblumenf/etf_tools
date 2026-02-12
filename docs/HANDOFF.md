# Project Handoff: SEC EDGAR ETF Data Pipeline

## Goal
Build a Python pipeline that uses the `edgartools` library to extract SEC EDGAR filing data and populate a PostgreSQL database described in `SCHEMA.md`.

**Database**: Neon (serverless PostgreSQL). Connection string via environment variable.

**Scope**: Data ingestion pipeline only. No web application layer.

## Database Schema
See `SCHEMA.md` for complete table definitions, relationships, and constraints. The schema has 6 tables:

| Table | Fed by SEC Filing | Granularity |
|-------|-------------------|-------------|
| ETF | company_tickers_mf.json + 485BPOS | One row per ticker |
| Holding | NPORT-P | Per security per quarter |
| Derivative | NPORT-P | Per derivative per quarter |
| Performance | N-CSR / N-CSRS | Per ETF per fiscal year |
| FeeExpense | 485BPOS | Per ETF per effective date |
| FlowData | 24F-2NT | Per ETF per fiscal year |

## edgartools Library

**Install**: `pip install edgartools` (requires Python >= 3.10)

**API reference**: Use Context7 with library ID `/dgunning/edgartools` (4,838 indexed snippets). Query on demand during implementation — do not paste API examples into prompts.

**Gotchas**:
- SEC identity must be set before any API call (name + email)
- Rate limit: 10 requests/second max (SEC enforced, library handles it)
- NPORT-P has built-in parsing support; N-CSR, 485BPOS, 24F-2NT support is unclear — may need raw HTML/XML fallback
- Unsupported form types raise `UnsupportedFilingTypeError`
- Max 1000 filings per company in local data mode

## Setup

Before starting, verify all system-wide MCP servers have a connection to this project. If the project has no `.mcp.json`, create one to ensure MCP servers (Context7, Playwright, etc.) are available.

## Feature Breakdown

Plan and implement these features in order:

1. **Project scaffolding** — Python project, PostgreSQL config, ORM/models matching SCHEMA.md
2. **ETF discovery** — Fetch `company_tickers_mf.json`, filter ETFs (3-4 char tickers), populate ETF table
3. **NPORT-P parser** — Extract holdings and derivatives from quarterly filings
4. **N-CSR parser** — Extract performance returns, distributions, turnover from annual filings
5. **485BPOS parser** — Extract fee schedules and strategy text from prospectus filings
6. **24F-2NT parser** — Extract fund flow data (sales, redemptions, net flows)
7. **Pipeline orchestration** — CLI command to run all parsers for all ETFs
