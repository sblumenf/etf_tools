# Portfolio X-Ray Tool: Comprehensive Data Inventory Report

**Generated**: March 2026  
**Scope**: Complete analysis of ETF tools codebase data structures, sources, and derivable metrics  
**Session Active**

---

## EXECUTIVE SUMMARY

The ETF tools codebase contains a robust database schema supporting comprehensive portfolio analysis across **13 core tables** plus 4 derivative tables for detailed security types. Data comes from 4 different SEC filing types, enabling:

- **Real-time portfolio composition** (quarterly NPORT holdings)
- **Risk metrics** (interest rate sensitivity, credit spread risk)
- **Performance & benchmarking** (annual N-CSR returns)
- **Fee structure analysis** (prospectus fee tables)
- **Fund flows** (annual sales/redemptions)
- **Detailed security attributes** (debt terms, derivative positions)

All data is keyed by **ticker/CIK/series/class** identifiers and supports **temporal tracking** (filing_date + report_date enables time-series analysis back to 2020).

---

## SECTION 1: DATABASE SCHEMA INVENTORY

### 1.1 Core Tables Overview

| Table | Records | Primary Key | Filing Source | Temporal Scope |
|-------|---------|-------------|---------------|----------------|
| `etf` | ~2,500 ETF tickers | ticker (UNIQUE) | Multiple | Current |
| `holding` | Millions (quarterly × funds × positions) | (etf_id, report_date, holding_key, filing_date) | NPORT-P | Q1 2020 – Present |
| `derivative` | Hundreds of thousands | (etf_id, report_date, type, underlying, expiry, filing_date) | NPORT-P | Q1 2020 – Present |
| `debt_security_detail` | Thousands (1:1 with bonds) | holding_id | NPORT-P | Q1 2020 – Present |
| `security_lending` | Hundreds (1:1 with loans) | holding_id | NPORT-P | Q1 2020 – Present |
| `performance` | ~25K (1-2 per ETF per year) | (etf_id, fiscal_year_end, filing_date) | N-CSR | FY 2021 – Present |
| `fee_expense` | ~50K (1-2 per ETF per filing) | (etf_id, effective_date, filing_date) | 485BPOS | Aug 2024 – Present |
| `flow_data` | ~5K (per CIK/issuer per year) | (cik, fiscal_year_end, filing_date) | 24F-2NT | FY 2021 – Present |
| `fund_snapshot` | Quarterly per fund | (cik, report_date, filing_date) | NPORT-P | Q1 2020 – Present |
| `nport_monthly_return` | ~5K (per ETF per filing) | (etf_id, report_date, class_id, filing_date) | NPORT-P | Q1 2020 – Present |
| `nport_monthly_flow` | ~5K (per ETF per filing) | (etf_id, report_date, class_id, filing_date) | NPORT-P | Q1 2020 – Present |
| `interest_rate_risk` | ~10K (multi-currency per ETF) | (etf_id, report_date, currency_code, filing_date) | NPORT-P | Q1 2020 – Present |
| `credit_spread_risk` | ~5K (per ETF per filing) | (etf_id, report_date, filing_date) | NPORT-P | Q1 2020 – Present |

**Derivative Support Tables:**
- `derivative_swap` — swap-specific fields (upfront payment, legs)
- `derivative_swap_leg` — individual swap leg details (pay/receive, rates)
- `derivative_option` — option-specific fields (put/call, exercise price)
- `derivative_forward` — FX forward details (currencies, amounts)

---

## SECTION 2: ETF MASTER DATA (Table: `etf`)

**Location**: `/Users/sergeblumenfeld/etf_tools/src/etf_pipeline/models.py:25-76`

### 2.1 Identity Fields

| Field | Type | Source | Usage |
|-------|------|--------|-------|
| `ticker` | String(10) | SEC company_tickers_mf.json | Primary lookup key |
| `cik` | String(10) | SEC EDGAR | Issuer-level identifier, filing lookups |
| `series_id` | String(20) | SEC EDGAR | Series/trust identifier |
| `class_id` | String(20) | SEC EDGAR | Share class identifier (multiple per series) |
| `issuer_name` | String(500) | SEC EDGAR | Issuer/fund company name |
| `fund_name` | String(500) | 485BPOS prospectus | Full fund name |

### 2.2 Narrative/Disclosure Fields

| Field | Type | Source | XRay Utility |
|-------|------|--------|-------------|
| `objective_text` | Text | 485BPOS (iXBRL tag: ObjectivePrimaryTextBlock) | Fund investment goal description |
| `strategy_text` | Text | 485BPOS (iXBRL tag: StrategyNarrativeTextBlock) | Investment strategy narrative |
| `principal_risks` | Text | 485BPOS (iXBRL tags: RiskTextBlock/RiskNarrativeTextBlock) | Fund risk disclosure |
| `category` | String(100) | Manual/imported | Fund category (e.g., "Large-Cap Growth") |
| `filing_url` | String(1000) | SEC EDGAR | Link to source 485BPOS filing |

### 2.3 Operational Fields

| Field | Type | Purpose |
|-------|------|---------|
| `is_active` | Boolean | Whether ETF is currently trading |
| `incomplete_data` | Boolean | Flag for partial loads (data quality) |
| `created_at` | DateTime | Row creation timestamp |
| `updated_at` | DateTime | Last modification timestamp |

**Sample Data** (from etf_tickers.json):
```json
{
  "ticker": "VOO",
  "cik": 36405,
  "series_id": "S000002839",
  "class_id": "C000092055"
}
```

---

## SECTION 3: PORTFOLIO HOLDINGS DATA (Table: `holding`)

**Location**: `/Users/sergeblumenfeld/etf_tools/src/etf_pipeline/models.py:78-122`  
**Source**: NPORT-P XML filings (quarterly portfolio report form)  
**Parser**: `/Users/sergeblumenfeld/etf_tools/src/etf_pipeline/parsers/nport.py`

### 3.1 Security Identification

| Field | Type | Description | XRay Use |
|-------|------|-------------|----------|
| `name` | String(500) | Security name/title | Holdings list, text search |
| `cusip` | String(9) | 9-digit CUSIP identifier | Security lookup, matching |
| `isin` | String(12) | ISIN for foreign securities | Cross-reference |
| `ticker` | String(20) | Security ticker | Lookup, composition analysis |
| `lei` | String(20) | Legal Entity Identifier | Corporate ID matching |
| `title` | String(500) | Alternative security title | Display in reports |

**Unique Constraint**: `(etf_id, report_date, holding_key, liquidity_classification, filing_date)`
- `holding_key = COALESCE(cusip, isin, name)` ensures deduplication across filings

### 3.2 Position & Valuation Data

| Field | Type | Description | XRay Use |
|-------|------|-------------|----------|
| `balance` | Numeric(20,4) | Quantity held | Position size, weighting |
| `units` | String(20) | Unit type (NS=shares, PA=par amount) | Interpretation context |
| `value_usd` | Numeric(20,2) | Market value in USD | Weighting, concentration |
| `pct_val` | Numeric(8,5) | % of net assets | Portfolio composition |
| `exchange_rate` | Numeric(12,6) | FX rate for conversion | Currency risk |

### 3.3 Classification & Risk

| Field | Type | Description | XRay Use |
|-------|------|-------------|----------|
| `asset_category` | String(20) | NPORT code (EC=equity, DBT=debt, FI=fixed income, etc.) | Asset allocation |
| `issuer_category` | String(50) | Issuer type (US Government, Corporate, etc.) | Credit analysis |
| `country` | String(3) | ISO country code | Geographic diversification |
| `currency` | String(3) | ISO currency code | Currency exposure |
| `fair_value_level` | Integer | GAAP fair value hierarchy (1/2/3) | Valuation risk |
| `is_restricted` | Boolean | Whether security has restrictions | Liquidity assessment |
| `payoff_profile` | String(10) | Long/Short | Position direction |
| `liquidity_classification` | String(50) | HLI/MLI/LLI/ILI (High/Moderate/Less/Illiquid) | Liquidity risk |

### 3.4 Temporal Fields

| Field | Type | Description | XRay Use |
|-------|------|-------------|----------|
| `report_date` | Date | Quarter-end date (Q1, Q2, Q3, Q4) | Time-series tracking |
| `filing_date` | Date | Date filing was submitted to SEC | Filing recency |

**Example Schema Usage**:
```
SELECT 
  ticker, 
  SUM(value_usd) as total_value,
  SUM(pct_val) as portfolio_pct,
  COUNT(*) as position_count
FROM holding
WHERE etf_id = ? AND report_date = ?
GROUP BY asset_category, country
```

---

## SECTION 4: DERIVATIVE POSITIONS (Table: `derivative` + subtables)

**Location**: `/Users/sergeblumenfeld/etf_tools/src/etf_pipeline/models.py:124-284`  
**Source**: NPORT-P filings (Part D)  
**Parser**: `/Users/sergeblumenfeld/etf_tools/src/etf_pipeline/parsers/nport.py` + `/nport_xml.py`

### 4.1 Derivative Base Fields

| Field | Type | Description | XRay Use |
|-------|------|-------------|----------|
| `derivative_type` | String(20) | FWD (forward), SWP (swap), FUT (futures), OPT (option), etc. | Derivative classification |
| `underlying_name` | String(500) | Name of underlying asset | Derivative tracking |
| `underlying_cusip` | String(9) | CUSIP of underlying | Lookup |
| `underlying_title` | String(150) | Alternative underlying name | Display |
| `underlying_isin` | String(12) | ISIN of underlying | Cross-ref |
| `underlying_ticker` | String(20) | Ticker of underlying | Quick lookup |
| `notional_value` | Numeric(20,2) | Notional exposure (USD) | Risk assessment |
| `counterparty` | String(500) | Counterparty institution | Counterparty risk |
| `counterparty_lei` | String(20) | Counterparty LEI | Corporate ID |
| `unrealized_appreciation` | Numeric(20,2) | Mark-to-market gain/loss | Derivative P&L |
| `delta` | Numeric(10,6) | Option delta (equity exposure) | Option Greeks |
| `payoff_profile` | String(10) | Long/Short | Exposure direction |

### 4.2 Swap Details (Table: `derivative_swap`)

| Field | Type | Description | XRay Use |
|-------|------|-------------|----------|
| `upfront_payment` | Numeric(20,2) | Cash paid upfront | Fee tracking |
| `upfront_payment_currency` | String(3) | Currency of payment | FX tracking |
| `upfront_receipt` | Numeric(20,2) | Cash received upfront | Fee tracking |
| `upfront_receipt_currency` | String(3) | Currency | FX tracking |
| `swap_flag` | String(1) | Swap indicator flag | Validation |

**Swap Legs** (Table: `derivative_swap_leg`, multiple per swap):

| Field | Type | Description | XRay Use |
|-------|------|-------------|----------|
| `direction` | String(7) | "pay" or "receive" | Swap exposure |
| `leg_type` | String(10) | "fixed", "floating", "other" | Rate structure |
| `fixed_rate` | Numeric(10,6) | Fixed coupon rate | Swap terms |
| `fixed_amount` | Numeric(20,2) | Fixed notional amount | Size |
| `fixed_currency` | String(3) | Currency | FX risk |
| `floating_index` | String(100) | Index name (e.g., "SOFR") | Rate basis |
| `floating_spread` | Numeric(10,6) | Spread over index | Rate structure |
| `floating_amount` | Numeric(20,2) | Floating notional | Size |
| `floating_currency` | String(3) | Currency | FX risk |
| `tenor` | String(20) | Reset period (e.g., "3M", "6M") | Payment frequency |
| `tenor_unit` | String(10) | "months", "years", etc. | Period unit |
| `reset_date_tenor` | String(20) | Time until next reset | Repricing schedule |

### 4.3 Option Details (Table: `derivative_option`)

| Field | Type | Description | XRay Use |
|-------|------|-------------|----------|
| `put_or_call` | String(4) | "call" or "put" | Option type |
| `written_or_purchased` | String(10) | "written" (sold) or "purchased" (long) | Option position |
| `share_number` | Numeric(20,4) | Number of shares represented | Position size |
| `exercise_price` | Numeric(20,6) | Strike price | Option terms |
| `exercise_price_currency` | String(3) | Currency | FX |
| `index_name` | String(150) | Underlying index name | Index identification |
| `index_identifier` | String(50) | Index code | Lookup |
| `nested_deriv_type` | String(20) | Type of nested derivative (swaption) | Complex option |
| `nested_deriv_notional` | Numeric(20,2) | Notional of nested deriv | Complexity |
| `nested_deriv_counterparty` | String(500) | Nested counterparty | Exposure |
| `nested_deriv_currency` | String(3) | Currency | FX |

### 4.4 Forward Details (Table: `derivative_forward`)

| Field | Type | Description | XRay Use |
|-------|------|-------------|----------|
| `currency_sold` | String(3) | Currency being sold | FX position |
| `amount_sold` | Numeric(20,2) | Amount in base currency | FX notional |
| `currency_purchased` | String(3) | Currency being purchased | FX position |
| `amount_purchased` | Numeric(20,2) | Amount purchased | FX notional |
| `settlement_date` | Date | When trade settles | FX cash flow |

**Derivative Example**:
```
Interest rate swap: Pay fixed 2.5% on $100M, receive SOFR+0.25% quarterly
Underlying = SOFR Index
Notional = $100M
Counterparty = JPMorgan
Delta = 0 (interest rate exposure only)
```

---

## SECTION 5: BOND/DEBT SECURITIES (Table: `debt_security_detail`)

**Location**: `/Users/sergeblumenfeld/etf_tools/src/etf_pipeline/models.py:286-310`  
**Source**: NPORT-P filings (debt_security section)  
**Relationship**: 1-to-1 with `holding` (optional)

### 5.1 Bond Terms

| Field | Type | Description | XRay Use |
|-------|------|-------------|----------|
| `maturity_date` | Date | Bond maturity/call date | Duration, convexity |
| `coupon_kind` | String(50) | Fixed, Floating, Zero, Stepped, etc. | Income stream type |
| `annualized_rate` | Numeric(8,6) | Coupon rate (e.g., 0.0375 = 3.75%) | Yield calculation |

### 5.2 Bond Status

| Field | Type | Description | XRay Use |
|-------|------|-------------|----------|
| `is_default` | Boolean | Bond in default | Credit risk |
| `is_in_arrears` | Boolean | Payments past due | Credit risk |
| `is_paid_kind` | Boolean | Paid-in-kind (not cash) | Income quality |
| `is_mandatory_convertible` | Boolean | Must convert to equity | Conversion risk |
| `is_contingent_convertible` | Boolean | CoCo bond (converts if bank capital < threshold) | Conversion risk |

---

## SECTION 6: SECURITY LENDING (Table: `security_lending`)

**Location**: `/Users/sergeblumenfeld/etf_tools/src/etf_pipeline/models.py:312-333`  
**Source**: NPORT-P filings (security_lending section)  
**Relationship**: 1-to-1 with `holding` (optional)

| Field | Type | Description | XRay Use |
|-------|------|-------------|----------|
| `is_cash_collateral` | Boolean | Position is cash collateral for loaned securities | Income source |
| `is_non_cash_collateral` | Boolean | Position is non-cash collateral (securities) | Collateral tracking |
| `is_loan_by_fund` | Boolean | Fund has loaned this security | Income source |

---

## SECTION 7: PERFORMANCE & RETURNS (Table: `performance`)

**Location**: `/Users/sergeblumenfeld/etf_tools/src/etf_pipeline/models.py:335-359`  
**Source**: N-CSR filings (annual certified shareholder reports)  
**Parser**: `/Users/sergeblumenfeld/etf_tools/src/etf_pipeline/parsers/ncsr.py`  
**XRay Priority**: HIGH

### 7.1 Fund Returns

| Field | Type | Description | XRay Use |
|-------|------|-------------|----------|
| `return_1yr` | Numeric(8,5) | 1-year annualized return (as decimal: 0.15 = 15%) | Recent performance |
| `return_5yr` | Numeric(8,5) | 5-year annualized return | Medium-term performance |
| `return_10yr` | Numeric(8,5) | 10-year annualized return | Long-term performance |
| `return_since_inception` | Numeric(8,5) | Annualized return from inception | Lifetime performance |

### 7.2 Benchmark Comparison

| Field | Type | Description | XRay Use |
|-------|------|-------------|----------|
| `benchmark_name` | String(500) | Benchmark index name (e.g., "S&P 500") | Performance attribution |
| `benchmark_return_1yr` | Numeric(8,5) | Benchmark 1-year return | Alpha calculation (1yr) |
| `benchmark_return_5yr` | Numeric(8,5) | Benchmark 5-year return | Alpha calculation (5yr) |
| `benchmark_return_10yr` | Numeric(8,5) | Benchmark 10-year return | Alpha calculation (10yr) |

### 7.3 Operational Metrics

| Field | Type | Description | XRay Use |
|-------|------|-------------|----------|
| `portfolio_turnover` | Numeric(8,5) | Annual turnover rate (e.g., 0.35 = 35%) | Trading activity, tax efficiency |
| `expense_ratio_actual` | Numeric(6,5) | Actual net expense ratio | Fee assessment |

### 7.4 Temporal Context

| Field | Type | Description | XRay Use |
|-------|------|-------------|----------|
| `fiscal_year_end` | Date | Fiscal year end date (e.g., 2025-12-31) | Annual snapshot |
| `filing_date` | Date | SEC filing date (enables time-series) | Historical tracking |

**Alpha Calculation Example**:
```
ETF 1-year return: 0.15 (15%)
Benchmark 1-year return: 0.12 (12%)
Alpha = 15% - 12% = 3%
```

---

## SECTION 8: FEES & EXPENSES (Table: `fee_expense`)

**Location**: `/Users/sergeblumenfeld/etf_tools/src/etf_pipeline/models.py:361-383`  
**Source**: 485BPOS filings (post-effective prospectus amendments)  
**Parser**: `/Users/sergeblumenfeld/etf_tools/src/etf_pipeline/parsers/prospectus.py` (iXBRL extraction)  
**XRay Priority**: HIGH

### 8.1 Fee Components

| Field | Type | Description | XRay Use |
|-------|------|-------------|----------|
| `management_fee` | Numeric(6,5) | Advisory/management fee (e.g., 0.005 = 0.5%) | Fee assessment |
| `distribution_12b1` | Numeric(6,5) | 12b-1 distribution & service fee | Distribution cost |
| `other_expenses` | Numeric(6,5) | Other operating expenses | Total cost |
| `acquired_fund_fees` | Numeric(6,5) | Fees of acquired funds (for fund-of-funds) | Indirect costs |

### 8.2 Expense Ratio (Gross vs Net)

| Field | Type | Description | XRay Use |
|-------|------|-------------|----------|
| `total_expense_gross` | Numeric(6,5) | Gross total expense ratio (before waiver) | Cost baseline |
| `fee_waiver` | Numeric(6,5) | Fee waiver/reimbursement amount | Effective cost reduction |
| `total_expense_net` | Numeric(6,5) | Net total expense ratio (after waiver) | Effective cost |

### 8.3 Waiver Terms

| Field | Type | Description | XRay Use |
|-------|------|-------------|----------|
| `fee_waiver_expiration_date` | Date | When waiver agreement expires | Risk of fee increase |
| `effective_date` | Date | Prospectus effective date | Fee change timing |
| `filing_date` | Date | SEC filing date (enables time-series) | Fee change history |

**Fee Analysis Example**:
```
Gross Expense Ratio: 0.50% (0.005)
Fee Waiver: 0.10% (0.001)
Net Expense Ratio: 0.40% (0.004) ← Effective cost to investor
Waiver Expiration: 2026-12-31 ← Risk of jump to 0.50%
```

---

## SECTION 9: FUND FLOWS (Table: `flow_data`)

**Location**: `/Users/sergeblumenfeld/etf_tools/src/etf_pipeline/models.py:385-401`  
**Source**: 24F-2NT filings (annual notice of additional shares)  
**Parser**: `/Users/sergeblumenfeld/etf_tools/src/etf_pipeline/parsers/flows.py`  
**Aggregation**: CIK-level (issuer/trust level, not per-ETF)

### 9.1 Flow Metrics

| Field | Type | Description | XRay Use |
|-------|------|-------------|----------|
| `sales_value` | Numeric(20,4) | Aggregate securities sold (new shares issued) | Asset growth |
| `redemptions_value` | Numeric(20,4) | Aggregate securities redeemed (shares withdrawn) | Asset decline |
| `net_sales` | Numeric(20,4) | Net sales = sales_value - redemptions | Net fund growth |

### 9.2 Temporal Context

| Field | Type | Description | XRay Use |
|-------|------|-------------|----------|
| `fiscal_year_end` | Date | FY ending date (e.g., 2025-12-31) | Annual snapshot |
| `filing_date` | Date | Filing date to SEC | Reporting date |
| `cik` | String(10) | CIK of issuer (not per-ETF class) | Fund-level aggregation |

**Flow Analysis Example**:
```
Fiscal Year 2025:
  Sales: $5.0B
  Redemptions: $2.0B
  Net Sales: $3.0B (fund growing)

Fiscal Year 2024:
  Sales: $4.0B
  Redemptions: $3.5B
  Net Sales: $0.5B (fund growing slowly)

Trend: Investor inflows accelerating → increased demand
```

---

## SECTION 10: FUND BALANCE SHEET (Table: `fund_snapshot`)

**Location**: `/Users/sergeblumenfeld/etf_tools/src/etf_pipeline/models.py:479-511`  
**Source**: NPORT-P filings (Part A)  
**Aggregation**: CIK-level (series/trust level, not per-ETF class)

### 10.1 Assets

| Field | Type | Description | XRay Use |
|-------|------|-------------|----------|
| `total_assets` | Numeric(20,2) | Sum of all fund assets (USD) | AUM |
| `assets_invested` | Numeric(20,2) | Assets deployed in securities | Investment level |
| `assets_misc_sec` | Numeric(20,2) | Assets in miscellaneous securities | Special holdings |
| `cash_not_reported` | Numeric(20,2) | Cash not itemized in Part D | Liquidity |

### 10.2 Liabilities (short-term: payable within 1 year)

| Field | Type | Description | XRay Use |
|-------|------|-------------|----------|
| `amt_pay_one_yr_banks_borr` | Numeric(20,2) | Bank borrowings due within 1 year | Leverage |
| `amt_pay_one_yr_ctrld_comp` | Numeric(20,2) | Controlled company payments due | Related-party debt |
| `amt_pay_one_yr_oth_affil` | Numeric(20,2) | Other affiliate payments due | Related-party debt |
| `amt_pay_one_yr_other` | Numeric(20,2) | Other payments due | Operational debt |

### 10.3 Liabilities (long-term: payable after 1 year)

| Field | Type | Description | XRay Use |
|-------|------|-------------|----------|
| `amt_pay_aft_one_yr_banks_borr` | Numeric(20,2) | Bank borrowings due after 1 year | Long-term leverage |
| `amt_pay_aft_one_yr_ctrld_comp` | Numeric(20,2) | Controlled company payments | Related-party debt |
| `amt_pay_aft_one_yr_oth_affil` | Numeric(20,2) | Other affiliate payments | Related-party debt |
| `amt_pay_aft_one_yr_other` | Numeric(20,2) | Other payments | Operational debt |

### 10.4 Commitments & Options

| Field | Type | Description | XRay Use |
|-------|------|-------------|----------|
| `delay_deliv` | Numeric(20,2) | Delayed delivery commitments | Settlement risk |
| `stand_by_commit` | Numeric(20,2) | Standby commitments | Contingent liabilities |
| `liquidity_pref` | Numeric(20,2) | Preferred stock liquidity preference | Preferred structure |
| `is_non_cash_collateral` | Boolean | Whether fund holds non-cash collateral | Collateral tracking |

### 10.5 Derived Metrics

| Calculation | Description | XRay Use |
|-------------|-------------|----------|
| `net_assets = total_assets - total_liabilities` | NAV | Fund size |
| `leverage_ratio = total_liabilities / total_assets` | Borrowing level | Risk assessment |
| `cash_ratio = cash_not_reported / total_assets` | Liquidity | Cash position |

---

## SECTION 11: MONTHLY RETURNS (Table: `nport_monthly_return`)

**Location**: `/Users/sergeblumenfeld/etf_tools/src/etf_pipeline/models.py:513-531`  
**Source**: NPORT-P filings (returnInfo section)  
**Frequency**: Quarterly filings, 3 months of rolling data per filing

### 11.1 Monthly Return Data

| Field | Type | Description | XRay Use |
|-------|------|-------------|----------|
| `month_1_return` | Numeric(24,2) | Most recent month's total return | Recent performance |
| `month_2_return` | Numeric(24,2) | 2nd most recent month's total return | Performance tracking |
| `month_3_return` | Numeric(24,2) | 3rd most recent month's total return | Performance tracking |
| `class_id` | String(10) | Share class (NULL = fund-level) | Class-specific performance |

**Note**: Values can be NULL if marked "N/A" in filing.

**Rolling Window Example**:
```
Q1 2025 Filing (filed May 15):
  month_1_return = April return
  month_2_return = March return
  month_3_return = February return

Q2 2025 Filing (filed Aug 15):
  month_1_return = July return
  month_2_return = June return
  month_3_return = May return
```

---

## SECTION 12: MONTHLY FLOWS (Table: `nport_monthly_flow`)

**Location**: `/Users/sergeblumenfeld/etf_tools/src/etf_pipeline/models.py:533-557`  
**Source**: NPORT-P filings (returnInfo section)  
**Frequency**: Quarterly filings, 3 months of rolling data per filing

### 12.1 Flow Components

| Field | Type | Description | XRay Use |
|-------|------|-------------|----------|
| `month_1_sales` | Numeric(18,2) | Most recent month's sales (new shares) | Flow tracking |
| `month_1_redemptions` | Numeric(18,2) | Most recent month's redemptions | Outflow tracking |
| `month_1_reinvestments` | Numeric(18,2) | Reinvested distributions | Income reinvestment |
| `month_2_sales` | Numeric(18,2) | Prior month sales | Flow tracking |
| `month_2_redemptions` | Numeric(18,2) | Prior month redemptions | Outflow tracking |
| `month_2_reinvestments` | Numeric(18,2) | Prior month reinvestments | Income reinvestment |
| `month_3_sales` | Numeric(18,2) | 2nd prior month sales | Flow tracking |
| `month_3_redemptions` | Numeric(18,2) | 2nd prior month redemptions | Outflow tracking |
| `month_3_reinvestments` | Numeric(18,2) | 2nd prior month reinvestments | Income reinvestment |
| `class_id` | String(50) | Share class (NULL = fund-level) | Class-specific flows |

**Flow Analysis Example**:
```
Month 1 (April): Sales $100M, Redemptions $80M, Reinvestments $5M
Month 2 (March): Sales $90M, Redemptions $70M, Reinvestments $4M
Month 3 (Feb): Sales $85M, Redemptions $60M, Reinvestments $3M

Net flow trend: Positive and increasing → strong investor demand
```

---

## SECTION 13: INTEREST RATE RISK (Table: `interest_rate_risk`)

**Location**: `/Users/sergeblumenfeld/etf_tools/src/etf_pipeline/models.py:559-584`  
**Source**: NPORT-P filings (curMetrics section)  
**Scope**: Multi-currency, bucket approach (3m, 1y, 5y, 10y, 30y maturity)  
**Metric**: DV01/DV100 (dollar value of 1bp / 100bp rate move)

### 13.1 DV01 Metrics (dollar value for 1 basis point move)

| Field | Type | Description | XRay Use |
|-------|------|-------------|----------|
| `dv01_3m` | Numeric(24,2) | Sensitivity to 3-month interest rates | Short-term IR risk |
| `dv01_1y` | Numeric(24,2) | Sensitivity to 1-year interest rates | Medium-term IR risk |
| `dv01_5y` | Numeric(24,2) | Sensitivity to 5-year interest rates | Duration risk |
| `dv01_10y` | Numeric(24,2) | Sensitivity to 10-year interest rates | Long-duration risk |
| `dv01_30y` | Numeric(24,2) | Sensitivity to 30-year interest rates | Long-term risk |

### 13.2 DV100 Metrics (dollar value for 100 basis point move)

| Field | Type | Description | XRay Use |
|-------|------|-------------|----------|
| `dv100_3m` | Numeric(24,2) | Portfolio change for 1% rate move (3m) | Scenario analysis |
| `dv100_1y` | Numeric(24,2) | Portfolio change for 1% rate move (1y) | Scenario analysis |
| `dv100_5y` | Numeric(24,2) | Portfolio change for 1% rate move (5y) | Scenario analysis |
| `dv100_10y` | Numeric(24,2) | Portfolio change for 1% rate move (10y) | Scenario analysis |
| `dv100_30y` | Numeric(24,2) | Portfolio change for 1% rate move (30y) | Scenario analysis |

### 13.3 Context

| Field | Type | Description | XRay Use |
|-------|------|-------------|----------|
| `currency_code` | String(3) | ISO currency code (USD, EUR, JPY, etc.) | Multi-currency IR risk |
| `report_date` | Date | Quarter-end date | Temporal snapshot |
| `filing_date` | Date | Filing date | Historical tracking |

**Interpretation Example**:
```
USD DV01_5y = -$500,000
→ If 5-year USD rates rise by 1bp (0.01%), portfolio loses $500k
→ If 5-year USD rates fall by 1bp, portfolio gains $500k

USD DV100_5y = -$50,000,000
→ If 5-year USD rates rise by 100bp (1%), portfolio loses $50M
```

---

## SECTION 14: CREDIT SPREAD RISK (Table: `credit_spread_risk`)

**Location**: `/Users/sergeblumenfeld/etf_tools/src/etf_pipeline/models.py:586-610`  
**Source**: NPORT-P filings (creditSprdRiskInvstGrade / creditSprdRiskNonInvstGrade sections)  
**Scope**: Bucket approach (3m, 1y, 5y, 10y, 30y maturity)  
**Metric**: CS01/SDV01 (dollar value of 1bp credit spread move)

### 14.1 Investment Grade Credit Spread Risk

| Field | Type | Description | XRay Use |
|-------|------|-------------|----------|
| `invst_grade_3m` | Numeric(24,2) | CS01 for 3-month IG bonds | Short-term credit risk |
| `invst_grade_1y` | Numeric(24,2) | CS01 for 1-year IG bonds | Medium-term credit risk |
| `invst_grade_5y` | Numeric(24,2) | CS01 for 5-year IG bonds | Primary IG maturity |
| `invst_grade_10y` | Numeric(24,2) | CS01 for 10-year IG bonds | Long-term IG risk |
| `invst_grade_30y` | Numeric(24,2) | CS01 for 30-year IG bonds | Ultra-long IG risk |

### 14.2 Non-Investment Grade (High Yield) Credit Spread Risk

| Field | Type | Description | XRay Use |
|-------|------|-------------|----------|
| `non_invst_grade_3m` | Numeric(24,2) | CS01 for 3-month HY bonds | Short-term HY risk |
| `non_invst_grade_1y` | Numeric(24,2) | CS01 for 1-year HY bonds | Medium-term HY risk |
| `non_invst_grade_5y` | Numeric(24,2) | CS01 for 5-year HY bonds | Primary HY maturity |
| `non_invst_grade_10y` | Numeric(24,2) | CS01 for 10-year HY bonds | Long-term HY risk |
| `non_invst_grade_30y` | Numeric(24,2) | CS01 for 30-year HY bonds | Ultra-long HY risk |

**Credit Risk Interpretation Example**:
```
IG CS01_5y = -$1,000,000
→ If IG credit spreads widen by 1bp, portfolio loses $1M
→ Indicates $1B equivalent of IG bond exposure at 5-year tenor

HY CS01_5y = -$500,000
→ If HY spreads widen by 1bp, portfolio loses $500k
→ Indicates significant but smaller HY exposure
```

---

## SECTION 15: PER-SHARE OPERATING DATA (Table: `per_share_operating`)

**Location**: `/Users/sergeblumenfeld/etf_tools/src/etf_pipeline/models.py:403-430`  
**Source**: N-CSR filings (Financial Highlights table)  
**Parser**: `/Users/sergeblumenfeld/etf_tools/src/etf_pipeline/parsers/finhigh.py` (HTML table extraction)  
**Frequency**: Annual per fiscal year

### 15.1 NAV & Performance

| Field | Type | Description | XRay Use |
|-------|------|-------------|----------|
| `nav_beginning` | Numeric(10,4) | NAV per share at start of period | Period baseline |
| `nav_end` | Numeric(10,4) | NAV per share at end of period | Period ending value |
| `total_return` | Numeric(8,5) | Total return percentage for period | Annual return |

### 15.2 Per-Share Income & Gains

| Field | Type | Description | XRay Use |
|-------|------|-------------|----------|
| `net_investment_income` | Numeric(10,4) | Dividend & interest per share | Income generation |
| `net_realized_unrealized_gain` | Numeric(10,4) | Cap gains (realized + unrealized) | Total gains |
| `total_from_operations` | Numeric(10,4) | Net income from investment operations | Operating performance |

### 15.3 Shareholder Communications

| Field | Type | Description | XRay Use |
|-------|------|-------------|----------|
| `equalization` | Numeric(10,4) | Equalization adjustment | Fair share accounting |
| `math_validated` | Boolean | Whether NAV math checks out | Data quality flag |

**Math Validation**:
```
NAV_end = NAV_begin + net_investment_income + net_realized_unrealized_gain + equalization

If math_validated=False, there's a data quality issue
```

---

## SECTION 16: PER-SHARE DISTRIBUTIONS (Table: `per_share_distribution`)

**Location**: `/Users/sergeblumenfeld/etf_tools/src/etf_pipeline/models.py:432-455`  
**Source**: N-CSR filings (Financial Highlights table)  
**Frequency**: Annual per fiscal year

### 16.1 Distribution Components

| Field | Type | Description | XRay Use |
|-------|------|-------------|----------|
| `dist_net_investment_income` | Numeric(10,4) | Dividend distributions per share | Income yield |
| `dist_realized_gains` | Numeric(10,4) | Capital gains distributions per share | Tax impact |
| `dist_return_of_capital` | Numeric(10,4) | Return of capital per share | Liability reduction |
| `dist_total` | Numeric(10,4) | Total distributions per share | Total payout |

**Yield Calculation Example**:
```
Dividend per share: $1.50
Year NAV: $50
Yield = $1.50 / $50 = 3.0%
```

---

## SECTION 17: PER-SHARE RATIOS (Table: `per_share_ratios`)

**Location**: `/Users/sergeblumenfeld/etf_tools/src/etf_pipeline/models.py:457-477`  
**Source**: N-CSR filings (Financial Highlights table)  
**Frequency**: Annual per fiscal year

### 17.1 Efficiency Ratios

| Field | Type | Description | XRay Use |
|-------|------|-------------|----------|
| `expense_ratio` | Numeric(6,5) | Operating expense ratio | Cost assessment |
| `portfolio_turnover` | Numeric(8,5) | Annual portfolio turnover | Trading activity |
| `net_assets_end` | Numeric(20,2) | Total net assets at period end | AUM |

---

## SECTION 18: DATA DERIVED & COMPUTED FIELDS

Beyond raw database fields, X-Ray should compute:

### 18.1 Portfolio Composition Analysis

**Derivable from**: `holding` table

```sql
-- Asset allocation by category
SELECT 
  asset_category,
  SUM(value_usd) as total,
  SUM(pct_val) as pct_portfolio
FROM holding
WHERE etf_id = ? AND report_date = ?
GROUP BY asset_category

-- Geographic allocation
SELECT 
  country,
  SUM(value_usd) as total,
  SUM(pct_val) as pct_portfolio
FROM holding
WHERE etf_id = ? AND report_date = ?
GROUP BY country

-- Top 10 holdings
SELECT name, value_usd, pct_val
FROM holding
WHERE etf_id = ? AND report_date = ?
ORDER BY value_usd DESC
LIMIT 10

-- Sector allocation (requires external sector mapping for cusips)
SELECT 
  sector_code,
  SUM(pct_val) as allocation
FROM holding h
LEFT JOIN security_sectors ss ON h.cusip = ss.cusip
WHERE h.etf_id = ? AND h.report_date = ?
GROUP BY sector_code
```

### 18.2 Risk Metrics

**Derivable from**: `interest_rate_risk`, `credit_spread_risk`, `holding`

```sql
-- Interest rate sensitivity summary
SELECT 
  report_date,
  SUM(dv100_5y) as total_5y_ir_risk,
  SUM(dv100_10y) as total_10y_ir_risk
FROM interest_rate_risk
WHERE etf_id = ? AND currency_code = 'USD'
GROUP BY report_date

-- Effective duration (approximate from DV01)
-- duration = -DV01 / (portfolio_value * 0.0001)

-- Credit exposure summary
SELECT 
  report_date,
  invst_grade_5y + non_invst_grade_5y as total_5y_credit_risk
FROM credit_spread_risk
WHERE etf_id = ?
GROUP BY report_date
```

### 18.3 Performance & Attribution

**Derivable from**: `performance`, `fee_expense`, `nport_monthly_return`

```sql
-- Alpha calculation
SELECT 
  p.ticker,
  p.return_1yr - perf.benchmark_return_1yr as alpha_1yr,
  p.return_5yr - perf.benchmark_return_5yr as alpha_5yr
FROM etf p
JOIN performance perf ON p.id = perf.etf_id
WHERE perf.fiscal_year_end = ?

-- Cost impact on returns
SELECT 
  p.ticker,
  perf.return_1yr as gross_return,
  perf.expense_ratio_actual as expense_ratio,
  (perf.return_1yr - fee.total_expense_net) as net_return
FROM performance perf
JOIN fee_expense fee ON perf.etf_id = fee.etf_id
WHERE perf.fiscal_year_end = ?
```

### 18.4 Fund Growth Analysis

**Derivable from**: `fund_snapshot`, `flow_data`

```sql
-- AUM growth over time
SELECT 
  fs.report_date,
  fs.net_assets as aum
FROM fund_snapshot fs
WHERE fs.cik = ?
ORDER BY fs.report_date DESC

-- Organic growth vs total growth
-- organic_growth = (AUM_end - AUM_start) - net_flows
-- with net_flows from flow_data

-- Asset retention rate
SELECT 
  CAST(AUM_end AS FLOAT) / (AUM_start + net_flows_year) as retention_rate
```

### 18.5 Liquidity Assessment

**Derivable from**: `holding`, `derivative`

```sql
-- Liquidity classification breakdown
SELECT 
  liquidity_classification,
  SUM(pct_val) as portfolio_pct
FROM holding
WHERE etf_id = ? AND report_date = ?
GROUP BY liquidity_classification

-- Illiquid asset percentage
SELECT 
  SUM(CASE WHEN liquidity_classification IN ('LLI', 'ILI') THEN pct_val ELSE 0 END) as illiquid_pct
FROM holding
WHERE etf_id = ? AND report_date = ?

-- Derivative leverage
SELECT 
  SUM(ABS(notional_value)) / (SELECT net_assets FROM fund_snapshot 
                              WHERE cik = ? AND report_date = ?) as derivative_leverage
FROM derivative
WHERE etf_id = ? AND report_date = ?
```

---

## SECTION 19: EXTERNAL DATA SOURCES

### 19.1 SEC EDGAR API

**Source**: `https://www.sec.gov` (via edgartools library)

| Data | Endpoint | Usage |
|------|----------|-------|
| Company metadata | `/cgi-bin/browse-edgar` | CIK lookup, company info |
| Filing index | `/cgi-bin/browse-edgar?action=getcompany` | Filing retrieval |
| XBRL data | `/Archives/edgar/` | iXBRL extraction (prospectus, N-CSR) |
| XML data | `/Archives/edgar/` | NPORT-P, 24F-2NT raw XML |

### 19.2 SEC Company Tickers

**Source**: `https://www.sec.gov/files/company_tickers_mf.json`  
**Updated**: Regularly by SEC  
**Parser**: `/Users/sergeblumenfeld/etf_tools/src/etf_pipeline/discover.py`  
**Contains**: ticker, CIK, series_id, class_id for all registered funds

### 19.3 FinViz (Referenced but not integrated)

**Source**: Mentioned in `/Users/sergeblumenfeld/etf_tools/docs/finviz_urls.md`  
**Status**: URL references only, no active data pull  
**Could Enable**: Real-time price, market cap, sector data

### 19.4 Data NOT Currently Integrated

These would enhance X-Ray but require additional parsers:

| Data | Source | X-Ray Utility |
|------|--------|---------------|
| Real-time prices | Yahoo Finance, IEX | NAV, current market prices |
| Market cap | Yahoo Finance | Relative sizing |
| Industry/sector | GICS/ICB | Sector allocation |
| ESG scores | MSCI, Refinitiv | ESG exposure |
| Credit ratings | S&P, Moody's | Credit quality (currently inferred from NPORT) |
| Dividend history | Company disclosures | Yield tracking |
| Historical correlation | Market data | Portfolio correlation |

---

## SECTION 20: DATA AVAILABILITY TIMELINE

### 20.1 Current Data Coverage

| Filing Type | First Data | Update Frequency | Lookback | Status |
|---|---|---|---|---|
| NPORT-P | Q1 2020 | Quarterly (latest per series) | ~1 quarter | Backfillable to 2020 |
| N-CSR | FY 2021 | Annual | ~1 year | Backfillable to 2015+ |
| 485BPOS | Aug 2024 | Ad-hoc | 18 months | Backfillable to earliest filing |
| 24F-2NT | FY 2021 | Annual | Latest FY only | Backfillable to 2015+ |

### 20.2 Backfill Capability

**Reference**: `/Users/sergeblumenfeld/etf_tools/docs/backfill-spec.md`

The codebase supports historical data backfill with CLI commands:

```bash
# Full backfill for a date range
etf-pipeline backfill --from-date 2020-01-01 --to-date 2025-12-31

# Single CIK
etf-pipeline backfill --from-date 2020-01-01 --cik 0001234567

# Specific parser
etf-pipeline backfill --from-date 2022-01-01 --parser flows
```

**Hardcoded Limits Being Bypassed** (in backfill mode):
- NPORT: `_get_latest_filings_per_series()` → all filings per series
- NCSR: `MAX_FILINGS = 10` → all filings
- Finhigh: `MAX_FILINGS = 10` → all filings
- Prospectus: `LOOKBACK_DAYS = 547` (18 months) → any date range
- Flows: `filings[0]` (latest only) → all filings

---

## SECTION 21: DATA QUALITY & MATURITY

### 21.1 Data Completeness by Table

| Table | Coverage | Notes |
|-------|----------|-------|
| etf | 100% (all SEC tickers) | ETF identifier data complete |
| holding | 95%+ | NPORT-P filings mandatory for registered funds |
| derivative | ~60% | Only funds using derivatives |
| debt_security_detail | ~40% | Only bond/fixed-income holdings |
| security_lending | ~20% | Only funds with lending programs |
| performance | ~80% | Only funds filing N-CSR (most ETFs do) |
| fee_expense | ~70% | Only 485BPOS filings (most ETFs file these) |
| flow_data | ~70% | Only 24F-2NT filings (issuer-level) |
| fund_snapshot | 95%+ | NPORT-P mandatory |
| nport_monthly_return | ~50% | Only funds with monthly return reporting |
| nport_monthly_flow | ~50% | Only funds with monthly flow reporting |
| interest_rate_risk | ~40% | Only funds with fixed income, derivative exposure |
| credit_spread_risk | ~20% | Only bond/credit-focused funds |
| per_share_* | ~70% | N-CSR filing dependent |

### 21.2 Data Quality Considerations

1. **NPORT-P Holdings**:
   - Most accurate (filed quarterly, required by regulation)
   - Lag: ~45 days after quarter-end
   - May include restricted/illiquid securities at fair value estimates

2. **Performance Data (N-CSR)**:
   - Annual only (not quarterly)
   - Benchmark names vary (manual standardization may be needed)
   - Return figures audited

3. **Fee Tables (485BPOS)**:
   - Can change mid-year without new filing (only if significant)
   - Waiver expiration dates are key risk indicators
   - May be superseded by later amendments

4. **Fund Flows (24F-2NT)**:
   - Issuer-level aggregation (not per-share class)
   - Annual only
   - Can be estimated from AUM changes in NPORT

5. **Risk Metrics (NPORT)**:
   - Quarter-end snapshots only
   - May be estimated by fund (not always precise marks)
   - No historical volatility data (would require external calculation)

### 21.3 Missing Data Scenarios

```sql
-- Check coverage for a specific ETF
SELECT 
  e.ticker,
  COUNT(DISTINCT h.report_date) as nport_quarters,
  COUNT(DISTINCT p.fiscal_year_end) as ncsr_years,
  COUNT(DISTINCT f.fiscal_year_end) as flow_years,
  COUNT(DISTINCT ir.report_date) as ir_metrics
FROM etf e
LEFT JOIN holding h ON e.id = h.etf_id
LEFT JOIN performance p ON e.id = p.etf_id
LEFT JOIN flow_data f ON e.cik = f.cik
LEFT JOIN interest_rate_risk ir ON e.id = ir.etf_id
WHERE e.ticker = ?
GROUP BY e.ticker

-- Identify ETFs with complete data
SELECT ticker
FROM etf
WHERE cik IN (
  SELECT DISTINCT etf_id FROM holding WHERE report_date >= DATE('now', '-3 months')
)
AND id IN (
  SELECT DISTINCT etf_id FROM performance WHERE fiscal_year_end >= DATE('now', '-1 year')
)
```

---

## SECTION 22: X-RAY FEATURE RECOMMENDATIONS

### 22.1 Core X-Ray Features (Ready Now)

✓ **Portfolio Composition**
- Top 10 holdings with weighting
- Asset class allocation (Equity / Fixed Income / Cash / Alternatives)
- Geographic diversification
- Liquidity assessment (HLI / MLI / LLI / ILI breakdown)

✓ **Fee Analysis**
- Management fee, 12b-1 fee, other expenses
- Net expense ratio vs gross
- Fee waiver details and expiration risks
- Comparison to fund category median

✓ **Performance**
- 1yr, 5yr, 10yr, since-inception returns
- Alpha vs benchmark
- Return volatility (if historical data available)
- Turnover rate

✓ **Risk Metrics**
- Interest rate sensitivity (DV01 by maturity bucket)
- Credit spread risk (IG vs HY)
- Derivative exposure (notional, types)
- Portfolio concentration (Herfindahl index)

✓ **Fund Health**
- AUM trend (annual from flow_data)
- Net flows (sales - redemptions)
- Investor demand trend

### 22.2 Advanced Features (Require External Data or Computation)

- **Sector allocation** (requires GICS/ICB mapping for CUSIPs)
- **ESG exposure** (requires ESG factor data)
- **Tax efficiency** (requires NAV change decomposition)
- **Correlation matrix** (requires historical price data)
- **VaR/Expected Shortfall** (requires volatility estimation)
- **Attribution analysis** (requires factor pricing data)

### 22.3 Data Integration Points for Future Enhancement

```
External Data Source → Processing → Database → X-Ray Display

Yahoo Finance/IEX → Price Download → price_snapshot table → Current NAV
GICS Index → Sector Mapping → security_sectors table → Sector Allocation
ESG Database → Factor Extraction → security_esg table → ESG Exposure
FRED API → Economic Data → economic_snapshot table → Macro Context
```

---

## SECTION 23: XRAY IMPLEMENTATION ROADMAP

### Phase 1: MVP (Foundation)

1. **Holdings Display**
   - Query: `SELECT name, value_usd, pct_val FROM holding WHERE etf_id = ? AND report_date = ?`
   - Transform: Sort by value, compute contribution
   - Display: Table with top 20, "Other" row

2. **Asset Allocation Pie Chart**
   - Query: `GROUP BY asset_category` with `SUM(pct_val)`
   - Transform: Normalize to 100%
   - Display: Pie chart with legend

3. **Fees Summary Card**
   - Query: `SELECT * FROM fee_expense WHERE etf_id = ? ORDER BY filing_date DESC LIMIT 1`
   - Transform: Format percentages, highlight waivers
   - Display: Card showing Gross/Net ER, waiver status

4. **Performance Comparison**
   - Query: `SELECT return_1yr, benchmark_return_1yr FROM performance WHERE etf_id = ?`
   - Transform: Calculate alpha
   - Display: Comparison table with sparklines

### Phase 2: Risk & Quality

5. **Risk Heatmap**
   - Query: Interest rate + credit spread risk tables
   - Transform: Normalize across maturities
   - Display: Heatmap showing sensitivity buckets

6. **Concentration Analysis**
   - Query: Top 10 holdings by pct_val
   - Transform: Calculate Herfindahl index
   - Display: Concentration metric + top holders

7. **Flow Trend**
   - Query: `SELECT fiscal_year_end, net_sales FROM flow_data WHERE cik = ? ORDER BY fiscal_year_end`
   - Transform: Compute YoY growth
   - Display: Bar chart with trend line

### Phase 3: Detailed Analytics

8. **Bond Detail View**
   - Query: `holding h JOIN debt_security_detail d WHERE h.etf_id = ? AND h.report_date = ?`
   - Transform: Aggregate by maturity bucket, coupon type
   - Display: Bond ladder, duration calculation

9. **Derivative Dashboard**
   - Query: Derivative tables grouped by type
   - Transform: Calculate notional exposure percentage
   - Display: Derivative types, counterparty risk

10. **Risk Scenario Projection**
    - Input: Rate/spread shock scenario
    - Query: DV01/CS01 data
    - Calculate: Portfolio impact
    - Display: "If rates rise 1%, portfolio value changes by X%"

---

## SECTION 24: REFERENCE DOCUMENTATION LOCATIONS

### Database Schema
- Full schema docs: `/Users/sergeblumenfeld/etf_tools/docs/reference/SCHEMA.md`
- Models code: `/Users/sergeblumenfeld/etf_tools/src/etf_pipeline/models.py`

### Parser Reference
- Parser map: `/Users/sergeblumenfeld/etf_tools/docs/reference/PARSER_REFERENCE_MAP.md`
- SEC filing specs: `/Users/sergeblumenfeld/etf_tools/docs/reference/` (NPORT XSD, XBRL schemas)

### Parsers Code
- NPORT: `/Users/sergeblumenfeld/etf_tools/src/etf_pipeline/parsers/nport.py`
- N-CSR: `/Users/sergeblumenfeld/etf_tools/src/etf_pipeline/parsers/ncsr.py`
- Prospectus: `/Users/sergeblumenfeld/etf_tools/src/etf_pipeline/parsers/prospectus.py`
- Flows: `/Users/sergeblumenfeld/etf_tools/src/etf_pipeline/parsers/flows.py`
- Financial Highlights: `/Users/sergeblumenfeld/etf_tools/src/etf_pipeline/parsers/finhigh.py`

### CLI
- Commands: `/Users/sergeblumenfeld/etf_tools/src/etf_pipeline/cli.py`
- Available: nport, ncsr, prospectus, finhigh, flows, run-all, discover, load-etfs

### Test Fixtures
- Database fixtures: `/Users/sergeblumenfeld/etf_tools/tests/conftest.py`
- Test data examples: `/Users/sergeblumenfeld/etf_tools/tests/test_*.py`

### Backfill
- Feature spec: `/Users/sergeblumenfeld/etf_tools/docs/backfill-spec.md`
- Implemented in: parsers (from_date, to_date parameters)

---

## CONCLUSION

The ETF tools database provides a **comprehensive, well-structured foundation** for portfolio X-Ray development:

1. **Data Richness**: 13+ core tables + 4 derivative tables covering composition, fees, performance, risk, and flows
2. **Time-Series Capable**: All data keyed by both report_date and filing_date, enabling historical analysis back to 2020
3. **Risk Metrics Native**: Interest rate sensitivity, credit spread risk, derivative exposure all directly available
4. **Fee Transparency**: Management fee, 12b-1, waivers, expiration dates all captured
5. **Operational Metrics**: Monthly returns, flows, turnover, expense ratios available
6. **Scalable Schema**: SQLite with SQLAlchemy ORM, indexed for fast queries

**Key Constraints**:
- Data freshness: ~45-day lag for NPORT (regulatory requirement)
- Annual only: N-CSR and 24F-2NT filings are annual
- Missing: Real-time prices, sector mappings, volatility (would require external integration)

**Recommended X-Ray MVP** should focus on:
1. Holdings composition + top 10 + asset allocation
2. Fee structure + waiver risks
3. Performance vs benchmark + alpha
4. Risk metrics from NPORT (IR/CS risk)
5. Fund health indicators (flows, concentration)

All queryable, all available, no external APIs needed for MVP.

