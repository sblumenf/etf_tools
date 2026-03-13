# Specification Draft: ETF X-Ray (Single-ETF)

*Interview in progress - Started: 2026-03-12*

## Overview
Build a single-ETF X-Ray webapp that displays comprehensive fund analysis across 8 feature cards. Uses the existing SEC filing data already in the etf_tools database. This is Phase 1 of a larger product that will grow to include multi-ETF portfolio analysis, historical tracking, and advanced analytics.

## Architecture Decisions
- **Backend**: FastAPI with a service layer (`xray/service.py`) for query logic, thin API route handlers
- **Frontend**: React SPA with Tailwind CSS + shadcn/ui + Recharts for data visualization
- **Database**: SQLite (etf_data.db) now, designed for easy Postgres migration via SQLAlchemy
- **Repo structure**: Monorepo — `src/etf_pipeline/api/` for FastAPI, `frontend/` at project root for React
- **Scope**: Tier 1 only — single-ETF analysis. Multi-ETF is future work but architecture should accommodate it.

## Design Principles
- **Future-proof but KISS**: Design for growth without over-engineering. Service layer enables reuse by future multi-ETF and CLI consumers.
- **Graceful data gaps**: Show available data, gray out missing metrics. Never hide cards entirely.
- **Consistent patterns**: Same approach for missing data across all cards.

## Constraints

### Files to Modify
- `src/etf_pipeline/models.py` — may add computed properties or relationships
- `src/etf_pipeline/db.py` — may extend for async/FastAPI session management

### Files NOT to Modify
- `src/etf_pipeline/parsers/*` — all parsers off-limits
- `src/etf_pipeline/cli.py` — CLI unchanged
- `src/etf_pipeline/config.py` — config unchanged

### New Files Allowed
- `src/etf_pipeline/api/` — FastAPI app, routes, schemas
- `src/etf_pipeline/xray/` — service layer (query functions)
- `frontend/` — React application
- `tests/test_api/` or `tests/test_xray/` — new tests

### New Dependencies Allowed
- Backend: fastapi, uvicorn, pydantic (for response schemas)
- Frontend: react, tailwindcss, @shadcn/ui, recharts, and standard React tooling (vite, etc.)

### Existing Code to Reuse
- SQLAlchemy models from `models.py`
- Database engine setup from `db.py`
- All existing table relationships and data

### Out of Scope
- Multi-ETF portfolio analysis
- Historical/temporal analysis
- Derivatives dashboard, stress testing
- External data enrichment (sectors, prices, ESG)
- User authentication / authorization
- Deployment / hosting / CI/CD
- CLI integration for xray

## Feature Cards (All 8)
1. **Holdings Composition** — Top 10 holdings by weight + "other" rollup
2. **Asset Allocation** — Breakdown by asset_category (EC, EP, DBT, FI, STIV, etc.)
3. **Geographic Diversification** — Top countries by allocation (ISO 3-letter codes)
4. **Liquidity Profile** — HLI/MLI/LLI/ILI distribution
5. **Fee Structure** — Management fee, 12b-1, other, gross/net ER, waiver status
6. **Performance vs. Benchmark** — 1yr/5yr/10yr/inception returns + alpha
7. **Fund Health Dashboard** — AUM trend, net flows, leverage, cash position
8. **Concentration Analysis** — HHI, top-5/10/20 weight percentages

## Technical Design

### Backend
- FastAPI app in `src/etf_pipeline/api/`
- Service layer in `src/etf_pipeline/xray/` with per-card query functions
- Pydantic response models for type-safe API responses
- Separate endpoints per card for independent loading (future multi-ETF will add aggregate endpoints)

### Frontend
- React + Vite
- Tailwind CSS + shadcn/ui
- Recharts for charts
- ETF selection: ticker in URL (/xray/:ticker) + search bar with autocomplete
- Dashboard layout with responsive card grid

### ETF Selection UX
- URL-driven: `/xray/SPY`
- Search bar with ticker/name autocomplete (queries `/api/etfs/search?q=...`)
- Future-proofed for multi-ETF (URL could become `/xray?tickers=SPY,QQQ&weights=60,40`)

## Open Questions
- [TBD — continuing interview]

---
*Interview notes accumulated during session*
---

