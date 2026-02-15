# Spec: Enhance Parsers — Capture All Available Filing Data

## Overview

The NPORT-P parser currently extracts only holding-level identifiers and valuations (name, CUSIP, value, asset category) and basic derivative positions. NPORT-P filings contain significantly more data that is being discarded: fund-level balance sheet snapshots, monthly returns and flows, interest rate and credit spread risk metrics, debt security details, and securities lending information.

The 485BPOS (prospectus) parser captures investment objective and strategy text plus fee data, but omits principal risk disclosure narratives and fee waiver expiration dates.

This enhancement captures all available NPORT-P data through edgartools, adds custom XML parsing for fields edgartools does not support (borrower details, liquidity classification), and expands the prospectus parser to include risk narratives and fee waiver metadata.

## Problem Statement

Running `etf-pipeline run-all --limit 3` against CIKs 36405, 52848, 105544 produces holdings and derivatives but discards:
- Fund-level financials (total assets, net assets, cash, borrowings)
- Monthly total returns and flows (3 months per filing)
- Interest rate risk (DV01, DV100) and credit spread risk by time bucket
- Debt security characteristics (maturity, coupon, default status)
- Securities lending activity
- Holding-level fields (title, payoff profile, exchange rate)

The prospectus parser also discards:
- Principal risk disclosure narratives (RiskTextBlock, RiskNarrativeTextBlock, etc.)
- Fee waiver expiration date (FeeWaiverOrReimbursementOverAssetsDateOfTermination)

## Scope

### In Scope
- 7 new database tables (fund_snapshot, nport_monthly_return, nport_monthly_flow, interest_rate_risk, credit_spread_risk, debt_security_detail, security_lending)
- 2 modified tables (holding: add columns + fix unique constraint; derivative: add columns)
- 1 modified table (etf: add risk_text column)
- 1 modified table (fee_expense: add fee_waiver_termination_date column)
- New `nport_xml.py` helper module for custom XML extraction
- Prospectus parser enhancement for risk narrative and fee waiver expiration date
- Updated `docs/SCHEMA.md` per phase
- Tests for all new extraction logic
- Database must be deleted and recreated after upgrade (no migrations)

### Out of Scope
- Changes to N-CSR or 24F-2NT parsers
- Merging NPORT data into existing flow_data or performance tables
- Alembic migration support
- Any UI or reporting layer
- Prospectus shareholder fees and expense examples (intentionally excluded — not relevant for ETFs)

## Reference Documents

Per `docs/reference/PARSER_REFERENCE_MAP.md`:

### NPORT-P References
- `nport-xsd/EDGAR Form N-PORT XML Technical Specification.pdf` — field definitions
- `nport-xsd/EDGAR Form N-PORT XML schema files/eis_NPORT_Filer.xsd` — XML schema
- `nport-xsd/EDGAR Form N-PORT XML schema files/eis_NPORT_common.xsd` — shared types
- `nport-xsd/EDGAR Form N-PORT XML Sample files/N-PORT Sample 1.xml` — sample filing

### 485BPOS References (for US-11, US-12)
- `xbrl-rr-2023/rr-2023.xsd` — RR taxonomy defining RiskTextBlock, RiskNarrativeTextBlock, FeeWaiverOrReimbursementOverAssetsDateOfTermination
- `xbrl-rr-2023/rr-preparers-guide-2022-11-04.pdf` — human-readable guide for RR taxonomy tags
- `xbrl-rr-2023/rr-2023_lab.xsd` — label linkbase for element names
- `xbrl-oef-2025/oef-rr-2025.xsd` — OEF+RR combined taxonomy (may have updated tags)

## User Stories

### US-1: Fund-Level Balance Sheet Snapshot

**Description:** As a data analyst, I want fund-level financial data (total assets, net assets, liabilities, cash, borrowings) stored per NPORT-P filing so I can track fund size and leverage over time.

**Acceptance Criteria:**
- [ ] New `FundSnapshot` model in `models.py` with columns: cik, report_date, filing_date, total_assets, net_assets, total_liabilities, cash_not_reported, assets_invested, assets_misc_sec, 8 borrowing columns (amt_pay_one_yr_banks_borr, amt_pay_one_yr_ctrld_comp, amt_pay_one_yr_oth_affil, amt_pay_one_yr_other, amt_pay_aft_one_yr_banks_borr, amt_pay_aft_one_yr_ctrld_comp, amt_pay_aft_one_yr_oth_affil, amt_pay_aft_one_yr_other), delay_deliv, stand_by_commit, liquidity_pref, is_non_cash_collateral
- [ ] Unique constraint: `(cik, report_date, filing_date)`
- [ ] NPORT parser extracts fund_info fields from FundReport and inserts FundSnapshot rows
- [ ] Running `run-all --limit 3` populates fund_snapshot with non-NULL total_assets and net_assets for all 3 CIKs
- [ ] `docs/SCHEMA.md` updated with fund_snapshot table
- [ ] All existing tests pass; new tests cover fund_snapshot extraction with mock FundReport data

### US-2: Debt Security Detail Table

**Description:** As a fixed-income analyst, I want bond-specific data (maturity date, coupon rate, coupon type, default status) stored for each debt holding so I can analyze bond portfolio characteristics.

**Acceptance Criteria:**
- [ ] New `DebtSecurityDetail` model with FK to holding.id: maturity_date (Date), coupon_kind (String), annualized_rate (Numeric), is_default (Boolean), is_in_arrears (Boolean), is_paid_kind (Boolean), is_mandatory_convertible (Boolean), is_contingent_convertible (Boolean)
- [ ] Unique constraint: `(holding_id)` (one-to-one with holding)
- [ ] Parser checks `investment.debt_security` and creates DebtSecurityDetail rows when present
- [ ] Bond holdings from CIKs 36405/52848/105544 have populated maturity_date and coupon fields
- [ ] `docs/SCHEMA.md` updated
- [ ] Tests cover: debt holding with all fields, equity holding (no debt detail row), NULL coupon rate

### US-3: Securities Lending Table

**Description:** As a risk analyst, I want to know which holdings are involved in securities lending programs.

**Acceptance Criteria:**
- [ ] New `SecurityLending` model with FK to holding.id: is_cash_collateral (Boolean), is_non_cash_collateral (Boolean), is_loan_by_fund (Boolean)
- [ ] Unique constraint: `(holding_id)`
- [ ] Parser checks `investment.security_lending` and creates rows when present
- [ ] `docs/SCHEMA.md` updated
- [ ] Tests cover: holding with lending data, holding without lending data

### US-4: Enhanced Holding Columns

**Description:** As a portfolio analyst, I want additional holding-level fields (title, payoff profile, exchange rate) and a robust unique constraint that handles holdings without CUSIPs.

**Acceptance Criteria:**
- [ ] `Holding` model gains: title (String(500)), payoff_profile (String(10)), exchange_rate (Numeric(12,6))
- [ ] Unique constraint changed from `(etf_id, report_date, cusip, filing_date)` to use a computed holding_key: `COALESCE(cusip, isin, name)` — implemented as a new `holding_key` column populated at insert time
- [ ] Parser populates title, payoff_profile, exchange_rate from InvestmentOrSecurity
- [ ] Foreign holdings without CUSIP no longer collide on NULL
- [ ] `docs/SCHEMA.md` updated
- [ ] Tests cover: holding with CUSIP, holding with only ISIN, holding with only name

### US-5: Enhanced Derivative Columns

**Description:** As a derivatives analyst, I want payoff profile and unrealized appreciation stored for derivative positions.

**Acceptance Criteria:**
- [ ] `Derivative` model gains: payoff_profile (String(10)), unrealized_appreciation (Numeric(20,2))
- [ ] Parser populates both fields from InvestmentOrSecurity/DerivativeInfo
- [ ] `docs/SCHEMA.md` updated
- [ ] Tests cover: derivative with both fields, derivative with NULL unrealized_appreciation

### US-6: Monthly Total Returns

**Description:** As a performance analyst, I want monthly total returns (3 months per filing, per share class) stored so I can track month-over-month fund performance.

**Acceptance Criteria:**
- [ ] New `NportMonthlyReturn` model: cik, report_date, filing_date, class_id (String(20)), month_number (Integer 1-3, where 1=most recent), total_return (Numeric(10,6)), net_realized_gain (Numeric(20,2)), net_unrealized_appreciation (Numeric(20,2))
- [ ] Unique constraint: `(cik, report_date, filing_date, class_id, month_number)`
- [ ] Parser extracts from FundReport.return_info.monthly_total_returns
- [ ] Running pipeline produces 3 rows per class per filing
- [ ] `docs/SCHEMA.md` updated
- [ ] Tests cover: filing with multiple classes, filing with NULL gains

### US-7: Monthly Fund Flows

**Description:** As a flow analyst, I want monthly sales, redemptions, and reinvestments (3 months per filing) stored for granular flow tracking.

**Acceptance Criteria:**
- [ ] New `NportMonthlyFlow` model: cik, report_date, filing_date, month_number (Integer 1-3), sales (Numeric(20,2)), reinvestment (Numeric(20,2)), redemption (Numeric(20,2))
- [ ] Unique constraint: `(cik, report_date, filing_date, month_number)`
- [ ] Parser extracts from FundReport.monthly_flow1/2/3
- [ ] Running pipeline produces 3 rows per filing
- [ ] `docs/SCHEMA.md` updated
- [ ] Tests cover: filing with all 3 months, filing with partial flow data

### US-8: Interest Rate Risk Metrics

**Description:** As a risk analyst, I want DV01 and DV100 sensitivity metrics by currency and time bucket stored for interest rate risk analysis.

**Acceptance Criteria:**
- [ ] New `InterestRateRisk` model: fund_snapshot_id (FK to fund_snapshot.id), currency (String(3)), metric_type (String(10) — 'DV01' or 'DV100'), period (String(10) — '3MO', '1YR', '5YR', '10YR', '30YR'), value (Numeric(20,4))
- [ ] Unique constraint: `(fund_snapshot_id, currency, metric_type, period)`
- [ ] Parser extracts from FundReport.interest_rate_risk / current_metrics
- [ ] `docs/SCHEMA.md` updated
- [ ] Tests cover: multiple currencies, all period buckets, NULL metrics

### US-9: Credit Spread Risk Metrics

**Description:** As a credit analyst, I want credit spread risk by investment grade and time bucket stored for credit risk analysis.

**Acceptance Criteria:**
- [ ] New `CreditSpreadRisk` model: fund_snapshot_id (FK to fund_snapshot.id), grade (String(20) — 'INVESTMENT_GRADE' or 'NON_INVESTMENT_GRADE'), period (String(10) — '3MO', '1YR', '5YR', '10YR', '30YR'), value (Numeric(20,4))
- [ ] Unique constraint: `(fund_snapshot_id, grade, period)`
- [ ] Parser extracts from FundReport.credit_spread_risk
- [ ] `docs/SCHEMA.md` updated
- [ ] Tests cover: both grades, all periods

### US-10: Custom XML Extraction — Borrower Details and Liquidity Classification

**Description:** As a data completeness advocate, I want borrower details (securities lending counterparties) and per-holding liquidity classification captured via custom XML parsing, since edgartools v5.14.1 does not parse these fields.

**Acceptance Criteria:**
- [ ] New `src/etf_pipeline/parsers/nport_xml.py` module
- [ ] Validate against NPORT XSD that borrower details and liquidity classification exist in the filing XML
- [ ] If present in XSD: extract borrower details (name, LEI, aggregate value) and liquidity classification per holding
- [ ] If NOT present or not reliably populated: document finding and skip (no empty tables)
- [ ] Add `liquidity_classification` column (String(20)) to Holding model if data is available
- [ ] Add `Borrower` table if data is available: cik, report_date, filing_date, borrower_name, borrower_lei, aggregate_value
- [ ] Tests use real (trimmed) SEC XML fixtures from CIKs 36405/52848/105544
- [ ] `docs/SCHEMA.md` updated if new tables/columns added

### US-11: Principal Risk Disclosure Narrative

**Description:** As an investor analyst, I want the principal risk disclosure text from 485BPOS prospectus filings stored so I can analyze and compare risk factors across funds.

**Acceptance Criteria:**
- [ ] `ETF` model gains: risk_text (Text, nullable) — stores the principal risk narrative
- [ ] Prospectus parser extracts from `rr:RiskTextBlock` or `oef:RiskTextBlock` iXBRL tag (same dual-prefix pattern as objective/strategy)
- [ ] If RiskTextBlock is not found, fall back to `rr:RiskNarrativeTextBlock` / `oef:RiskNarrativeTextBlock`
- [ ] Running `run-all --limit 3` populates risk_text for ETFs that have 485BPOS filings with tagged risk content
- [ ] `docs/SCHEMA.md` updated with risk_text column on etf table
- [ ] Tests cover: filing with RiskTextBlock, filing with RiskNarrativeTextBlock only, filing with neither (NULL)

### US-12: Fee Waiver Expiration Date

**Description:** As a cost analyst, I want the fee waiver termination date stored alongside fee data so I can identify when net expense ratios may increase.

**Acceptance Criteria:**
- [ ] `FeeExpense` model gains: fee_waiver_termination_date (Date, nullable)
- [ ] Prospectus parser extracts from `rr:FeeWaiverOrReimbursementOverAssetsDateOfTermination` or `oef:FeeWaiverOrReimbursementOverAssetsDateOfTermination` iXBRL tag
- [ ] Parser handles date format variations (YYYY-MM-DD, MM/DD/YYYY, textual dates)
- [ ] Running `run-all --limit 3` populates fee_waiver_termination_date when the tag exists in the filing
- [ ] `docs/SCHEMA.md` updated with fee_waiver_termination_date column on fee_expense table
- [ ] Tests cover: filing with termination date, filing without (NULL), date format edge cases

## Technical Design

### Data Model — New Tables

```
ETF (1) ──< Holding ──< DebtSecurityDetail (0..1)
                   ──< SecurityLending (0..1)
FundSnapshot (keyed by CIK) ──< InterestRateRisk
                             ──< CreditSpreadRisk
NportMonthlyReturn (keyed by CIK + class_id)
NportMonthlyFlow (keyed by CIK)
Borrower (keyed by CIK, if data available)
```

### Parser Architecture

```
nport.py (main parser)
  ├── Existing: holding/derivative extraction via edgartools FundReport
  ├── New: fund_snapshot extraction from FundReport.fund_info
  ├── New: monthly return/flow extraction from FundReport.return_info / monthly_flow
  ├── New: risk metric extraction from FundReport.interest_rate_risk / credit_spread_risk
  ├── New: debt_security_detail extraction from investment.debt_security
  ├── New: security_lending extraction from investment.security_lending
  └── Calls nport_xml.py for borrower/liquidity fields

nport_xml.py (new helper)
  ├── extract_borrowers(filing_xml) -> list[dict]
  └── extract_liquidity_classification(filing_xml, holding_name) -> str | None
```

### Holding Unique Constraint Fix

Replace `(etf_id, report_date, cusip, filing_date)` with `(etf_id, report_date, holding_key, filing_date)` where `holding_key` is a computed column: `COALESCE(cusip, isin, name)`. The parser computes this value at insert time.

## Implementation Phases

### Phase 1: Schema Foundation + Fund Snapshot
- [ ] Add FundSnapshot model to models.py
- [ ] Add fund_snapshot extraction logic to nport.py
- [ ] Add FundSnapshot tests (mock FundReport with fund_info)
- [ ] Update docs/SCHEMA.md
- **Verification:** `python -m pytest tests/ -v` — all pass, fund_snapshot rows populated in test

### Phase 2: Holding/Derivative Enhancements + Debt/Lending Tables
- [ ] Add DebtSecurityDetail and SecurityLending models
- [ ] Add title, payoff_profile, exchange_rate, holding_key columns to Holding model
- [ ] Fix Holding unique constraint to use holding_key
- [ ] Add payoff_profile, unrealized_appreciation to Derivative model
- [ ] Update nport.py to populate all new fields
- [ ] Add tests for debt detail, security lending, enhanced holding, enhanced derivative, constraint fix
- [ ] Update docs/SCHEMA.md
- **Verification:** `python -m pytest tests/ -v` — all pass, debt details populated for bond holdings

### Phase 3: Monthly Returns + Flows
- [ ] Add NportMonthlyReturn and NportMonthlyFlow models
- [ ] Add extraction logic to nport.py for return_info and monthly_flow
- [ ] Add tests (mock FundReport with return_info and monthly_flow data)
- [ ] Update docs/SCHEMA.md
- **Verification:** `python -m pytest tests/ -v` — all pass, 3 monthly return rows and 3 monthly flow rows per filing

### Phase 4: Risk Metrics + Custom XML
- [ ] Add InterestRateRisk and CreditSpreadRisk models
- [ ] Add risk metric extraction to nport.py
- [ ] Create nport_xml.py module
- [ ] Validate borrower/liquidity fields against NPORT XSD
- [ ] Implement custom XML extraction if fields exist in real filings
- [ ] Add Borrower model and liquidity_classification column if applicable
- [ ] Download and trim real SEC XML fixtures for test data
- [ ] Add tests for risk metrics and custom XML parsing
- [ ] Update docs/SCHEMA.md
- **Verification:** `python -m pytest tests/ -v` — all pass, risk metric rows populated, XML extraction verified

### Phase 5: Prospectus Enhancements — Risk Narrative + Fee Waiver Date
- [ ] Add risk_text column to ETF model
- [ ] Add fee_waiver_termination_date column to FeeExpense model
- [ ] Update prospectus.py to extract RiskTextBlock / RiskNarrativeTextBlock
- [ ] Update prospectus.py to extract FeeWaiverOrReimbursementOverAssetsDateOfTermination
- [ ] Add tests for both new extractions (extend existing prospectus test fixtures)
- [ ] Update docs/SCHEMA.md
- **Verification:** `python -m pytest tests/ -v` — all pass, risk_text and fee_waiver_termination_date populated in tests

## Non-Functional Requirements

- NFR-1: No new external dependencies beyond edgartools and stdlib xml.etree
- NFR-2: Existing tests must not break at any phase
- NFR-3: Database must be deleted and recreated after schema changes (no migration tooling)
- NFR-4: Parser should gracefully handle missing data (NULL fields, not errors) for any optional NPORT-P section

## Definition of Done

This feature is complete when:
- [ ] All 12 user stories pass acceptance criteria
- [ ] All 5 implementation phases verified
- [ ] Tests pass: `source .venv/bin/activate && python -m pytest tests/ -v`
- [ ] docs/SCHEMA.md reflects all new tables and modified columns
- [ ] `run-all --limit 3` populates new tables with real SEC data

## Ralph Loop Command

```bash
/ralph "Implement NPORT parser enhancement per spec at docs/specs/enhance-the-nport-parser-to-include-the-items-mentioned-here.md

PHASES:
1. Schema Foundation + Fund Snapshot: FundSnapshot model, extraction, tests, SCHEMA.md - verify with python -m pytest tests/ -v
2. Holding/Derivative Enhancements: DebtSecurityDetail, SecurityLending, holding columns, constraint fix, derivative columns, tests, SCHEMA.md - verify with python -m pytest tests/ -v
3. Monthly Returns + Flows: NportMonthlyReturn, NportMonthlyFlow, extraction, tests, SCHEMA.md - verify with python -m pytest tests/ -v
4. Risk Metrics + Custom XML: InterestRateRisk, CreditSpreadRisk, nport_xml.py, borrower/liquidity validation, tests, SCHEMA.md - verify with python -m pytest tests/ -v
5. Prospectus Enhancements: risk_text on ETF, fee_waiver_termination_date on FeeExpense, prospectus.py extraction, tests, SCHEMA.md - verify with python -m pytest tests/ -v

VERIFICATION (run after each phase):
- source .venv/bin/activate && python -m pytest tests/ -v

ESCAPE HATCH: After 20 iterations without progress:
- Document what's blocking in the spec file under 'Implementation Notes'
- List approaches attempted
- Stop and ask for human guidance

Output <promise>COMPLETE</promise> when all phases pass verification." --max-iterations 30 --completion-promise "COMPLETE"
```

## Implementation Notes

- edgartools `FundReport` class: query Context7 `/dgunning/edgartools` for exact attribute names before coding
- The `fund_info` attribute on FundReport contains most fund-level fields as a `FundInfo` dataclass
- `return_info` contains `MonthlyTotalReturn` objects and `RealizedChange` objects
- `monthly_flow1/2/3` are `MonthlyFlow` dataclass instances
- `interest_rate_risk` and `credit_spread_risk` may be nested dicts — inspect actual data structure
- For Phase 4 custom XML: access raw XML via `filing.document.content` or similar edgartools accessor
- COALESCE holding_key: implement in Python at insert time (SQLite computed columns have limitations)
