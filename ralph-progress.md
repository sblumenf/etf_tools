# Ralph Progress: ETF X-Ray Webapp

## Spec: docs/specs/etf-xray-docsxray-reportmd.md

## Status: Phase 1 complete — backend foundation done

---

## Completed

### Phase 1: Foundation + Backend API ✅

- [x] Created `src/etf_pipeline/api/` package with FastAPI app, CORS, lifespan (`main.py`)
- [x] Created `src/etf_pipeline/api/deps.py` with DB session dependency injection
- [x] Created `src/etf_pipeline/xray/service.py` with query functions for all 8 cards
- [x] Created `src/etf_pipeline/xray/calculations.py` with HHI and concentration calculations
- [x] Created `src/etf_pipeline/api/schemas/xray.py` with Pydantic response models for all cards
- [x] Created `src/etf_pipeline/api/schemas/etf.py` with ETF search response models
- [x] Created `src/etf_pipeline/api/routes/etf.py` with search endpoint
- [x] Created `src/etf_pipeline/api/routes/xray.py` with full xray endpoint (all 8 cards)
- [x] Tests pass: `python -m pytest tests/test_xray/ tests/test_api/ -v` → 9 passed, 1 skipped

### Key field-name corrections discovered (models.py vs spec assumptions)
- `FeeExpense.total_expense_gross` (not `gross_expense_ratio`)
- `FeeExpense.total_expense_net` (not `net_expense_ratio`)
- `FeeExpense.fee_waiver_expiration_date` (not `waiver_expiration_date`)
- `Performance.return_1yr/5yr/10yr` (not `one_year_return`, etc.)
- `Performance.portfolio_turnover` (not `portfolio_turnover_rate`)
- `FundSnapshot.cik` join (no etf_id FK — joined via ETF.cik)
- `FundSnapshot.report_date` (not `period_date`)
- `NPORTMonthlyFlow` net_sales computed from sales - redemptions
- `FlowData.cik` join (not etf_id)

---

## Remaining

### Phase 1 final item
- [ ] Scaffold React frontend with Vite + Tailwind + shadcn/ui (no card implementations yet)

### Phase 2: Frontend Cards + Search
- [ ] SearchBar component with autocomplete
- [ ] Home page with search bar
- [ ] XRay page layout with responsive card grid
- [ ] HoldingsCard with configurable N dropdown
- [ ] AssetAllocationCard with donut chart (Recharts)
- [ ] GeographicCard with bar chart + choropleth
- [ ] LiquidityCard with stacked bar chart
- [ ] FeeCard with fee breakdown + waiver highlight
- [ ] PerformanceCard with returns comparison
- [ ] FundHealthCard with AUM, leverage, cash metrics
- [ ] ConcentrationCard with HHI + treemap
- [ ] "No data available" gray states
- [ ] data_completeness-driven card states

### Phase 3: E2E Tests + Error Handling + Polish
- [ ] Playwright setup and all E2E tests
- [ ] Loading skeleton states
- [ ] Error boundary / error state
- [ ] Filing date display

---

## Next task
Scaffold React frontend (Vite + Tailwind + shadcn/ui) — last item of Phase 1.
