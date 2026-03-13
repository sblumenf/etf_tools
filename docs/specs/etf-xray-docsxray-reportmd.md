# ETF X-Ray: Single-ETF Analysis Webapp

**Date**: 2026-03-12
**Status**: SPEC COMPLETE
**Phase**: 1 of N (future phases: multi-ETF portfolio, historical analysis, advanced analytics)

---

## Overview

Build a single-ETF X-Ray webapp that displays comprehensive fund analysis across 8 feature cards. The app queries the existing etf_tools database (populated by the SEC filing parser pipeline) and presents data through a React frontend backed by a FastAPI API. This is Phase 1 of a consumer-facing product intended for public deployment and eventual monetization.

## Constraints

### Files to Modify
- `src/etf_pipeline/models.py` -- may add computed properties or relationships
- `src/etf_pipeline/db.py` -- may extend for FastAPI session management

### Files NOT to Modify
- `src/etf_pipeline/parsers/*` -- all parsers off-limits
- `src/etf_pipeline/cli.py` -- CLI unchanged
- `src/etf_pipeline/config.py` -- config unchanged

### New Files Allowed
- `src/etf_pipeline/api/` -- FastAPI application, routes, Pydantic schemas
- `src/etf_pipeline/xray/` -- service layer (query functions for each card)
- `frontend/` -- React application (Vite + Tailwind + shadcn/ui + Recharts)
- `tests/test_api/` -- backend API integration tests
- `tests/test_xray/` -- service layer integration tests
- `tests/e2e/` -- Playwright end-to-end tests

### New Dependencies Allowed
- **Backend**: fastapi, uvicorn, pydantic (response schemas)
- **Frontend**: react, vite, tailwindcss, @shadcn/ui, recharts, react-simple-maps (choropleth), playwright (E2E)
- **No new ORM or DB dependencies** -- reuse existing SQLAlchemy + SQLite

### Existing Code to Reuse
- SQLAlchemy ORM models from `models.py` (ETF, Holding, FeeExpense, Performance, FundSnapshot, FlowData, NportMonthlyFlow, InterestRateRisk, CreditSpreadRisk, etc.)
- Database engine setup from `db.py`
- All existing table relationships and foreign keys

### Out of Scope
- Multi-ETF portfolio analysis (Tier 2 -- future spec)
- Historical/temporal analysis (Tier 3 -- future spec)
- Derivatives dashboard, liquidity stress testing (Tier 4 -- future spec)
- External data enrichment (sector classification, real-time prices, ESG)
- User authentication / authorization
- Deployment / hosting / CI/CD / Docker
- CLI integration for xray
- UI/UX polish beyond functional layout (will be refined later with design skill)

---

## Architecture

### Design Principles
- **Future-proof but KISS**: Service layer enables reuse by future multi-ETF, CLI, and advanced analytics consumers. No over-engineering.
- **Graceful data gaps**: Show available data, gray out missing metrics. Never hide cards entirely.
- **Scalable deployment**: Frontend and backend are separate deployable units. React served via CDN/static hosting, FastAPI as API-only service.
- **Latest data only**: All cards show the most recent available data. Historical views are future work.

### System Architecture

```
[React SPA]  <--HTTP/JSON-->  [FastAPI API]  <--SQLAlchemy-->  [SQLite DB]
  (CDN)                        (/api/*)                        (etf_data.db)
```

### Backend Structure

```
src/etf_pipeline/
  api/
    __init__.py
    main.py          # FastAPI app, CORS, lifespan
    routes/
      __init__.py
      etf.py         # ETF search/list endpoints
      xray.py        # X-Ray card endpoints
    schemas/
      __init__.py
      etf.py         # ETF search response models
      xray.py        # Per-card Pydantic response models
    deps.py          # Dependency injection (DB session)
  xray/
    __init__.py
    service.py       # Query functions: get_holdings(), get_fees(), etc.
    calculations.py  # HHI, concentration metrics, aggregations
```

### Frontend Structure

```
frontend/
  src/
    App.tsx
    pages/
      Home.tsx       # Search landing page
      XRay.tsx       # Single-ETF dashboard
    components/
      SearchBar.tsx  # Ticker autocomplete
      cards/
        HoldingsCard.tsx
        AssetAllocationCard.tsx
        GeographicCard.tsx
        LiquidityCard.tsx
        FeeCard.tsx
        PerformanceCard.tsx
        FundHealthCard.tsx
        ConcentrationCard.tsx
    hooks/
      useXRayData.ts # API data fetching
    lib/
      api.ts         # API client
```

### API Design

All endpoints under `/api/v1/`. Versioned from the start for future compatibility.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/etfs/search?q={query}` | GET | Search ETFs by ticker or name. Returns `[{ticker, name, cik}]` |
| `/api/v1/xray/{ticker}` | GET | Full X-Ray data for one ETF. Returns all 8 cards' data in a single response |

The single-endpoint approach for xray data is appropriate because:
1. All 8 cards' data is small (< 50KB total)
2. A single DB session can efficiently gather all data
3. Frontend loads all cards simultaneously
4. Future multi-ETF endpoint will follow the same pattern: `/api/v1/xray/portfolio`

### Response Schema (abbreviated)

```json
{
  "ticker": "SPY",
  "name": "SPDR S&P 500 ETF Trust",
  "filing_date": "2025-12-31",
  "data_completeness": {
    "holdings": true,
    "fees": true,
    "performance": true,
    "fund_health": true,
    "liquidity": true
  },
  "holdings": { ... },
  "asset_allocation": { ... },
  "geographic": { ... },
  "liquidity": { ... },
  "fees": { ... },
  "performance": { ... },
  "fund_health": { ... },
  "concentration": { ... }
}
```

The `data_completeness` object tells the frontend which cards have data and which should show "No data available" states.

---

## User Stories

### US-1: ETF Search

**Description**: As a user, I want to search for an ETF by ticker or name so that I can view its X-Ray analysis.

**Acceptance Criteria:**
- [ ] `GET /api/v1/etfs/search?q=spy` returns results containing `{ticker: "SPY", name: "SPDR S&P 500 ETF Trust"}`
- [ ] Search matches partial ticker (e.g., "sp" matches "SPY") and partial name
- [ ] Search returns max 20 results, ordered by relevance (exact ticker match first)
- [ ] Empty query returns empty list (no full ETF dump)
- [ ] Frontend search bar shows dropdown with ticker + fund name as user types
- [ ] Selecting a result navigates to `/xray/{ticker}`
- [ ] Typing a ticker directly in the URL bar (`/xray/SPY`) loads the dashboard

### US-2: Holdings Composition Card

**Description**: As a user, I want to see a fund's top holdings ranked by portfolio weight so I know what securities I actually own.

**Acceptance Criteria:**
- [ ] Card shows top N holdings (default N=10, configurable via dropdown: 10, 25, 50, All)
- [ ] Each holding row shows: name, ticker (if available), value in USD, percent of net assets
- [ ] An "Other" row shows the aggregated remainder when N < total holdings
- [ ] Holdings are sorted by `pct_val` descending
- [ ] For SPY, the top holding is a recognizable mega-cap stock (Apple, Microsoft, etc.)
- [ ] If no holdings data exists, card shows "No data available" in gray

### US-3: Asset Allocation Card

**Description**: As a user, I want to see the breakdown of asset types (equity, debt, cash, etc.) so I understand what the fund actually holds.

**Acceptance Criteria:**
- [ ] Card shows a pie/donut chart with segments for each `asset_category`
- [ ] Categories are labeled with human-readable names (not raw codes): "Equity - Common" not "EC"
- [ ] Percentages sum to ~100% (within rounding)
- [ ] A table below the chart lists each category with percentage and USD value
- [ ] For SPY, asset allocation is ~99%+ Equity - Common
- [ ] If no holdings data exists, card shows "No data available" in gray

### US-4: Geographic Diversification Card

**Description**: As a user, I want to see which countries my fund is invested in so I understand geographic concentration.

**Acceptance Criteria:**
- [ ] Card shows a horizontal bar chart of top 10 countries by allocation weight
- [ ] Countries display full names (United States, not USA)
- [ ] Card also shows a choropleth world map colored by allocation weight
- [ ] Hovering over a country on the map shows the allocation percentage
- [ ] For SPY, United States is ~100%
- [ ] For a global ETF (e.g., VT if in DB), multiple countries appear
- [ ] If no holdings have country data, card shows "No data available" in gray

### US-5: Liquidity Profile Card

**Description**: As a user, I want to see how liquid the fund's holdings are so I understand redemption risk.

**Acceptance Criteria:**
- [ ] Card shows a stacked bar chart with 4 segments: Highly Liquid, Moderately Liquid, Less Liquid, Illiquid
- [ ] Each segment shows percentage of portfolio
- [ ] Labels use human-readable names (not HLI/MLI/LLI/ILI codes)
- [ ] Color coding: green (highly liquid) to red (illiquid)
- [ ] For SPY, nearly 100% should be Highly Liquid
- [ ] For AGG, there may be a mix of liquidity levels
- [ ] If no liquidity data exists, card shows "No data available" in gray

### US-6: Fee Structure Card

**Description**: As a user, I want to see the complete fee breakdown so I know exactly what I'm paying.

**Acceptance Criteria:**
- [ ] Card shows: management fee, 12b-1 fee, other expenses, acquired fund fees (if applicable)
- [ ] Gross and net expense ratios prominently displayed
- [ ] If a fee waiver exists, show waiver amount and expiration date
- [ ] If waiver expires within 6 months, highlight it (e.g., amber/warning color)
- [ ] For SPY, expense ratio should be ~0.09%
- [ ] Fees displayed as percentages with 2 decimal places (e.g., 0.09%)
- [ ] If no fee data exists, card shows "No data available" in gray

### US-7: Performance vs. Benchmark Card

**Description**: As a user, I want to see fund returns alongside benchmark returns so I can evaluate performance.

**Acceptance Criteria:**
- [ ] Card shows returns at available intervals: 1-year, 5-year, 10-year, since inception
- [ ] Benchmark returns shown alongside fund returns
- [ ] Alpha (fund return - benchmark return) calculated and displayed for each interval
- [ ] Positive alpha shown in green, negative in red
- [ ] Benchmark name displayed
- [ ] If turnover rate is available, show it
- [ ] If no performance data exists, card shows "No data available" in gray

### US-8: Fund Health Dashboard Card

**Description**: As a user, I want a quick health assessment of the fund so I can identify potential risks.

**Acceptance Criteria:**
- [ ] Card shows latest: total net assets (AUM), total borrowings, leverage ratio (borrowings / net assets), cash position (% of net assets)
- [ ] If flow data available (from nport_monthly_flow or flow_data), show latest net flow direction (inflows vs outflows)
- [ ] AUM displayed in human-readable format ($5.2B, $340M, etc.)
- [ ] Leverage ratio of 0 displayed as "None" or "0%"
- [ ] If no fund_snapshot data exists, card shows "No data available" in gray

### US-9: Concentration Analysis Card

**Description**: As a user, I want to see how concentrated the fund is so I understand single-name and top-holding risk.

**Acceptance Criteria:**
- [ ] Card shows: HHI (Herfindahl-Hirschman Index), top-5 weight %, top-10 weight %, top-20 weight %
- [ ] A treemap visualization shows holdings proportional to weight (top 20 holdings, remaining as "Other")
- [ ] HHI calculated as sum of squared weights (each weight as percentage, e.g., 7% = 49)
- [ ] For SPY (~500 holdings), HHI should be low (< 200)
- [ ] For a concentrated fund (< 50 holdings), HHI should be visibly higher
- [ ] If no holdings data exists, card shows "No data available" in gray

---

## Technical Requirements

### Functional Requirements

- **FR-1**: API returns valid JSON for all endpoints with appropriate HTTP status codes (200, 404, 422, 500)
- **FR-2**: `GET /api/v1/xray/{ticker}` returns 404 with `{"detail": "ETF not found"}` for unknown tickers
- **FR-3**: All monetary values returned in USD
- **FR-4**: All percentage values returned as floats (0.0 to 100.0), not decimals (0.0 to 1.0)
- **FR-5**: Filing date of the source N-PORT data included in response so users know data freshness
- **FR-6**: `data_completeness` object in response indicates which cards have data available
- **FR-7**: Search endpoint returns results within 200ms for any query
- **FR-8**: HHI calculation uses all holdings, not just top N

### Non-Functional Requirements

- **NFR-1**: API response time < 500ms for `/api/v1/xray/{ticker}` (p95)
- **NFR-2**: Frontend initial load (search page) < 2 seconds on broadband
- **NFR-3**: Frontend renders all cards within 1 second of receiving API response
- **NFR-4**: CORS configured to allow frontend origin
- **NFR-5**: SQLAlchemy queries use read-only sessions (no writes from the webapp)
- **NFR-6**: Database connection string configurable via environment variable (for future Postgres migration)
- **NFR-7**: No hardcoded file paths -- database location via config/env var

---

## Implementation Phases

### Phase 1: Foundation + Backend API

Set up project scaffolding for both backend and frontend. Implement the full FastAPI backend with service layer and all API endpoints.

- [ ] Create `src/etf_pipeline/api/` package with FastAPI app, CORS, lifespan
- [ ] Create `src/etf_pipeline/api/deps.py` with DB session dependency injection
- [ ] Create `src/etf_pipeline/xray/service.py` with query functions for all 8 cards
- [ ] Create `src/etf_pipeline/xray/calculations.py` with HHI and concentration calculations
- [ ] Create `src/etf_pipeline/api/schemas/xray.py` with Pydantic response models for all cards
- [ ] Create `src/etf_pipeline/api/routes/etf.py` with search endpoint
- [ ] Create `src/etf_pipeline/api/routes/xray.py` with xray endpoint
- [ ] Write integration tests for all service layer functions (tests against real DB)
- [ ] Write integration tests for all API endpoints
- [ ] Scaffold React frontend with Vite + Tailwind + shadcn/ui (no card implementations yet)
- **Verification:** `cd /Users/sergeblumenfeld/etf_tools && python -m pytest tests/test_api/ tests/test_xray/ -v` passes. `curl http://localhost:8000/api/v1/xray/SPY` returns valid JSON with all 8 card sections.

### Phase 2: Frontend Cards + Search

Implement the React frontend with search, navigation, and all 8 card components.

- [ ] Implement SearchBar component with autocomplete (hitting `/api/v1/etfs/search`)
- [ ] Implement Home page with search bar
- [ ] Implement XRay page layout with responsive card grid
- [ ] Implement HoldingsCard with configurable N dropdown and table
- [ ] Implement AssetAllocationCard with donut chart (Recharts)
- [ ] Implement GeographicCard with bar chart (Recharts) + choropleth map (react-simple-maps)
- [ ] Implement LiquidityCard with stacked bar chart (Recharts)
- [ ] Implement FeeCard with fee breakdown table and waiver highlight
- [ ] Implement PerformanceCard with returns comparison table
- [ ] Implement FundHealthCard with AUM, leverage, cash metrics
- [ ] Implement ConcentrationCard with HHI metrics + treemap (Recharts)
- [ ] Implement "No data available" gray state for all cards
- [ ] Implement `data_completeness`-driven card state (active vs. grayed out)
- **Verification:** `cd /Users/sergeblumenfeld/etf_tools/frontend && npm run build` succeeds. Manual verification: navigate to `/xray/SPY`, `/xray/AGG`, `/xray/QQQ` and confirm all 8 cards render with real data.

### Phase 3: E2E Tests + Error Handling + Polish

Add Playwright E2E tests, error states, loading states, and overall robustness.

- [ ] Set up Playwright config for E2E tests
- [ ] E2E test: search for "SPY", click result, verify dashboard loads with 8 cards
- [ ] E2E test: navigate directly to `/xray/SPY`, verify all cards render
- [ ] E2E test: navigate to `/xray/INVALIDTICKER`, verify 404/error state
- [ ] E2E test: verify `/xray/AGG` shows different data profile than `/xray/SPY`
- [ ] Add loading skeleton states for all cards while API call is in flight
- [ ] Add error boundary / error state if API call fails
- [ ] Add filing date display on the dashboard ("Data as of: 2025-12-31")
- [ ] Verify all "No data available" states render correctly for ETFs with partial data
- **Verification:** `cd /Users/sergeblumenfeld/etf_tools && npx playwright test` passes all E2E tests. `python -m pytest tests/ -v` passes all backend tests.

---

## Definition of Done

This feature is complete when:
- [ ] All acceptance criteria in US-1 through US-9 pass
- [ ] All implementation phases verified
- [ ] Backend tests pass: `python -m pytest tests/test_api/ tests/test_xray/ -v`
- [ ] Frontend builds: `cd frontend && npm run build`
- [ ] E2E tests pass: `npx playwright test`
- [ ] `/xray/SPY`, `/xray/AGG`, and `/xray/QQQ` all render correctly with real data
- [ ] Cards with missing data show gray "No data available" state

---

## Asset Category Code Mapping

For US-3 (Asset Allocation Card), map these N-PORT codes to display names:

| Code | Display Name |
|------|-------------|
| EC | Equity - Common |
| EP | Equity - Preferred |
| DBT | Debt |
| FI | Fixed Income |
| STIV | Cash Equivalent |
| ABS | Asset-Backed Security |
| MBS | Mortgage-Backed Security |
| UST | US Treasury |
| OTHER | Other |

## Liquidity Code Mapping

For US-5 (Liquidity Profile Card):

| Code | Display Name | Color |
|------|-------------|-------|
| HLI | Highly Liquid | Green |
| MLI | Moderately Liquid | Yellow |
| LLI | Less Liquid | Orange |
| ILI | Illiquid | Red |

---

## Ralph Loop Command

```bash
/ralph-loop "Implement ETF X-Ray single-ETF webapp per spec at docs/specs/etf-xray-docsxray-reportmd.md

PHASES:
1. Foundation + Backend API: FastAPI app, service layer, all endpoints, backend integration tests, React scaffold - verify with pytest tests/test_api/ tests/test_xray/ -v
2. Frontend Cards + Search: All 8 card components, search bar, routing, data fetching - verify with cd frontend && npm run build
3. E2E Tests + Polish: Playwright tests, loading states, error handling, filing date display - verify with npx playwright test

VERIFICATION (run after each phase):
- python -m pytest tests/ -v
- cd frontend && npm run build
- npx playwright test (Phase 3 only)

ESCAPE HATCH: After 20 iterations without progress:
- Document what's blocking in the spec file under 'Implementation Notes'
- List approaches attempted
- Stop and ask for human guidance

Output <promise>COMPLETE</promise> when all phases pass verification." --max-iterations 30 --completion-promise "COMPLETE"
```

## Implementation Notes

*To be filled during implementation*
