# Database Schema

SQLite database managed by SQLAlchemy 2.0. All models defined in `src/etf_pipeline/models.py`.

---

## Entity-Relationship Overview

```
ETF (1) ──< Holding (1) ──< DebtSecurityDetail (0..1)
ETF (1) ──< Derivative
ETF (1) ──< Performance
ETF (1) ──< FeeExpense
ETF (1) ──< PerShareOperating
ETF (1) ──< PerShareDistribution
ETF (1) ──< PerShareRatios
ETF (1) ──< NPORTMonthlyReturn
ETF (1) ──< NPORTMonthlyFlow
ETF (1) ──< InterestRateRisk

FlowData (standalone, keyed by CIK)
FundSnapshot (standalone, keyed by CIK)
```

---

## Tables

### `etf`

Central table identifying each ETF share class.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | Integer | PK | Auto-increment ID |
| `ticker` | String(10) | UNIQUE, NOT NULL | ETF ticker symbol |
| `cik` | String(10) | NOT NULL, INDEXED | SEC Central Index Key |
| `series_id` | String(20) | | SEC series identifier |
| `class_id` | String(20) | INDEXED | SEC class/contract identifier |
| `fund_name` | String(500) | | Full fund name |
| `issuer_name` | String(500) | NOT NULL | Issuer/registrant name |
| `objective_text` | Text | | Investment objective narrative |
| `strategy_text` | Text | | Principal strategy narrative |
| `filing_url` | String(1000) | | Source filing URL |
| `category` | String(100) | | Fund category |
| `is_active` | Boolean | NOT NULL, default=True | Whether the ETF is active |
| `incomplete_data` | Boolean | NOT NULL, default=False | Flag for partial data loads |
| `created_at` | DateTime | NOT NULL, server default | Row creation timestamp |
| `updated_at` | DateTime | NOT NULL, auto-update | Last modification timestamp |

---

### `holding`

Individual portfolio holdings from NPORT-P filings.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | Integer | PK | |
| `etf_id` | Integer | FK -> etf.id, NOT NULL | Parent ETF |
| `report_date` | Date | NOT NULL | Filing report date |
| `filing_date` | Date | NOT NULL | SEC filing date (enables over-time tracking) |
| `name` | String(500) | NOT NULL | Security name |
| `cusip` | String(9) | INDEXED | CUSIP identifier |
| `isin` | String(12) | | ISIN identifier |
| `ticker` | String(20) | | Security ticker |
| `lei` | String(20) | | Legal Entity Identifier |
| `balance` | Numeric(20,4) | | Quantity held |
| `units` | String(20) | | Unit type (NS, PA, etc.) |
| `value_usd` | Numeric(20,2) | | Market value in USD |
| `pct_val` | Numeric(8,5) | | Percentage of net assets |
| `asset_category` | String(20) | | Asset category code |
| `issuer_category` | String(50) | | Issuer type category |
| `country` | String(3) | | ISO country code |
| `currency` | String(3) | | ISO currency code |
| `fair_value_level` | Integer | | Fair value hierarchy (1/2/3) |
| `is_restricted` | Boolean | NOT NULL, default=False | Restricted security flag |
| `title` | String(500) | | Security title/description |
| `payoff_profile` | String(10) | | Payoff profile (Long/Short) |
| `exchange_rate` | Numeric(12,6) | | FX rate used for USD valuation |
| `holding_key` | String(500) | NOT NULL | Unique identifier: COALESCE(cusip, isin, name) |

**Unique:** `(etf_id, report_date, holding_key, filing_date)`
**Indexes:** `(etf_id, report_date)`, `(cusip)`, `(report_date)`

> Note: `holding_key` is computed as the first non-null value among cusip, isin, and name. This ensures foreign holdings without CUSIP identifiers can be uniquely identified without constraint violations on NULL cusip values.

---

### `derivative`

Derivative positions from NPORT-P filings.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | Integer | PK | |
| `etf_id` | Integer | FK -> etf.id, NOT NULL | Parent ETF |
| `report_date` | Date | NOT NULL | Filing report date |
| `filing_date` | Date | NOT NULL | SEC filing date (enables over-time tracking) |
| `derivative_type` | String(20) | NOT NULL | Type (FWD, SWP, FUT, OPT, etc.) |
| `underlying_name` | String(500) | | Underlying instrument name |
| `underlying_cusip` | String(9) | | Underlying CUSIP |
| `notional_value` | Numeric(20,2) | | Notional amount in USD |
| `counterparty` | String(500) | | Counterparty name |
| `counterparty_lei` | String(20) | | Counterparty LEI |
| `delta` | Numeric(10,6) | | Option delta |
| `expiration_date` | Date | | Contract expiration |
| `currency_sold` | String(3) | | Currency sold (for forward currency derivatives) |
| `currency_amt_sold` | Numeric(18,2) | | Amount of currency sold (for forward currency derivatives) |
| `settlement_date` | Date | | Settlement date (for forward derivatives) |
| `written_notional_amt` | Numeric(18,2) | | Notional amount for written options/swaptions |
| `other_amt` | Numeric(18,2) | | Catch-all for other derivative amounts |

**Unique:** `(etf_id, report_date, derivative_type, underlying_name, filing_date)`
**Indexes:** `(etf_id, report_date)`, `(report_date)`

---

### `debt_security_detail`

Debt-specific details for bond holdings from NPORT-P filings (one-to-one with holding).

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | Integer | PK | |
| `holding_id` | Integer | FK -> holding.id CASCADE, NOT NULL | Parent holding (one-to-one) |
| `maturity_date` | Date | | Bond maturity date |
| `coupon_kind` | String(50) | | Coupon type (Fixed, Floating, Zero, etc.) |
| `annualized_rate` | Numeric(8,6) | | Annualized coupon rate (e.g., 0.0375 for 3.75%) |
| `is_default` | Boolean | NOT NULL, default=False | Whether the bond is in default |
| `is_in_arrears` | Boolean | NOT NULL, default=False | Whether payments are in arrears |
| `is_paid_kind` | Boolean | NOT NULL, default=False | Whether paid in kind |
| `is_mandatory_convertible` | Boolean | NOT NULL, default=False | Whether mandatory convertible |
| `is_contingent_convertible` | Boolean | NOT NULL, default=False | Whether contingent convertible (CoCo) |

**Unique:** `(holding_id)`

> Note: Only holdings with `debt_security` data in NPORT-P filings will have a corresponding row in this table. Equity holdings will not.

---

### `security_lending`

Securities lending program details for holdings from NPORT-P filings (one-to-one with holding).

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | Integer | PK | |
| `holding_id` | Integer | FK -> holding.id CASCADE, NOT NULL | Parent holding (one-to-one) |
| `is_cash_collateral` | Boolean | NOT NULL, default=False | Whether the holding is cash collateral for securities loaned |
| `is_non_cash_collateral` | Boolean | NOT NULL, default=False | Whether the holding is non-cash collateral for securities loaned |
| `is_loan_by_fund` | Boolean | NOT NULL, default=False | Whether the holding represents a security loaned by the fund |

**Unique:** `(holding_id)`

> Note: Only holdings with `security_lending` data in NPORT-P filings will have a corresponding row in this table.

---

### `performance`

Annual return and benchmark data from N-CSR filings.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | Integer | PK | |
| `etf_id` | Integer | FK -> etf.id, NOT NULL | Parent ETF |
| `fiscal_year_end` | Date | NOT NULL | Fiscal year end date |
| `filing_date` | Date | NOT NULL | SEC filing date (enables over-time tracking) |
| `return_1yr` | Numeric(8,5) | | 1-year return |
| `return_5yr` | Numeric(8,5) | | 5-year annualized return |
| `return_10yr` | Numeric(8,5) | | 10-year annualized return |
| `return_since_inception` | Numeric(8,5) | | Since-inception return |
| `benchmark_name` | String(500) | | Benchmark index name |
| `benchmark_return_1yr` | Numeric(8,5) | | Benchmark 1-year return |
| `benchmark_return_5yr` | Numeric(8,5) | | Benchmark 5-year return |
| `benchmark_return_10yr` | Numeric(8,5) | | Benchmark 10-year return |
| `portfolio_turnover` | Numeric(8,5) | | Portfolio turnover rate |
| `expense_ratio_actual` | Numeric(6,5) | | Actual expense ratio |

**Unique:** `(etf_id, fiscal_year_end, filing_date)`

---

### `fee_expense`

Annual fee table data from 485BPOS prospectus filings.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | Integer | PK | |
| `etf_id` | Integer | FK -> etf.id, NOT NULL | Parent ETF |
| `effective_date` | Date | NOT NULL | Prospectus effective date |
| `filing_date` | Date | NOT NULL | SEC filing date (enables over-time tracking) |
| `management_fee` | Numeric(6,5) | | Management fee rate |
| `distribution_12b1` | Numeric(6,5) | | 12b-1 distribution fee |
| `other_expenses` | Numeric(6,5) | | Other expenses rate |
| `total_expense_gross` | Numeric(6,5) | | Gross total expense ratio |
| `fee_waiver` | Numeric(6,5) | | Fee waiver/reimbursement |
| `total_expense_net` | Numeric(6,5) | | Net total expense ratio |
| `acquired_fund_fees` | Numeric(6,5) | | Acquired fund fees and expenses |

**Unique:** `(etf_id, effective_date, filing_date)`

---

### `flow_data`

Fund-level sales and redemption flows from 24F-2NT filings.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | Integer | PK | |
| `cik` | String(10) | NOT NULL | SEC CIK (issuer-level, not per-ETF) |
| `fiscal_year_end` | Date | NOT NULL, INDEXED | Fiscal year end date |
| `filing_date` | Date | NOT NULL | SEC filing date (enables over-time tracking) |
| `sales_value` | Numeric(20,4) | | Aggregate sales |
| `redemptions_value` | Numeric(20,4) | | Aggregate redemptions |
| `net_sales` | Numeric(20,4) | | Net sales (sales - redemptions) |

**Unique:** `(cik, fiscal_year_end, filing_date)`

> Note: `flow_data` is keyed by CIK, not `etf_id`. 24F-2NT filings report at the issuer level, not per share class.

---

### `fund_snapshot`

Fund-level balance sheet snapshot from NPORT-P filings.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | Integer | PK | |
| `cik` | String(10) | NOT NULL, INDEXED | SEC CIK (issuer-level, not per-ETF) |
| `report_date` | Date | NOT NULL, INDEXED | NPORT filing report date |
| `filing_date` | Date | NOT NULL | SEC filing date (enables over-time tracking) |
| `total_assets` | Numeric(20,2) | | Fund's total asset value |
| `total_liabilities` | Numeric(20,2) | | Fund's total liabilities |
| `net_assets` | Numeric(20,2) | | NAV (total_assets - total_liabilities) |
| `cash_not_reported` | Numeric(20,2) | | Cash not reported in Part D |
| `assets_invested` | Numeric(20,2) | | Assets invested in securities |
| `assets_misc_sec` | Numeric(20,2) | | Assets attributable to miscellaneous securities |
| `amt_pay_one_yr_banks_borr` | Numeric(20,2) | | Amounts payable within one year to banks for borrowings |
| `amt_pay_one_yr_ctrld_comp` | Numeric(20,2) | | Amounts payable within one year to controlled companies |
| `amt_pay_one_yr_oth_affil` | Numeric(20,2) | | Amounts payable within one year to other affiliates |
| `amt_pay_one_yr_other` | Numeric(20,2) | | Amounts payable within one year to other parties |
| `amt_pay_aft_one_yr_banks_borr` | Numeric(20,2) | | Amounts payable after one year to banks for borrowings |
| `amt_pay_aft_one_yr_ctrld_comp` | Numeric(20,2) | | Amounts payable after one year to controlled companies |
| `amt_pay_aft_one_yr_oth_affil` | Numeric(20,2) | | Amounts payable after one year to other affiliates |
| `amt_pay_aft_one_yr_other` | Numeric(20,2) | | Amounts payable after one year to other parties |
| `delay_deliv` | Numeric(20,2) | | Delayed delivery commitments |
| `stand_by_commit` | Numeric(20,2) | | Standby commitments |
| `liquidity_pref` | Numeric(20,2) | | Liquidity preference of outstanding preferred stock |
| `is_non_cash_collateral` | Boolean | NOT NULL, default=False | Whether fund holds non-cash collateral |

**Unique:** `(cik, report_date, filing_date)`

> Note: `fund_snapshot` is keyed by CIK, not `etf_id`. NPORT-P filings report fund-level balance sheet data at the series level, which maps to CIK in our data model. This table captures the balance sheet state as of each quarterly filing.

---

### `nport_monthly_return`

Monthly total return data from NPORT-P filings.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | Integer | PK | |
| `etf_id` | Integer | FK -> etf.id, NOT NULL | Parent ETF |
| `report_date` | Date | NOT NULL | NPORT filing report date |
| `filing_date` | Date | NOT NULL | SEC filing date (enables over-time tracking) |
| `class_id` | String(10) | | SEC class identifier (NULL = fund-level returns) |
| `month_1_return` | Numeric(24,2) | | Most recent month's return (NULL if N/A in filing) |
| `month_2_return` | Numeric(24,2) | | Second most recent month's return (NULL if N/A in filing) |
| `month_3_return` | Numeric(24,2) | | Third most recent month's return (NULL if N/A in filing) |

**Unique:** `(etf_id, report_date, class_id, filing_date)`

> Note: Monthly returns are extracted from the XML at `/edgarSubmission/formData/fundinfo/returnInfo/monthlyTotReturns`. The `class_id` field is NULL for fund-level returns or contains the class identifier when returns are reported separately by share class. Return values of "N/A" in the XML are stored as NULL.

---

### `nport_monthly_flow`

Monthly fund flow data from NPORT-P filings.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | Integer | PK | |
| `etf_id` | Integer | FK -> etf.id, NOT NULL | Parent ETF |
| `report_date` | Date | NOT NULL | NPORT filing report date |
| `filing_date` | Date | NOT NULL | SEC filing date (enables over-time tracking) |
| `class_id` | String(50) | | SEC class identifier (NULL = fund-level flows) |
| `month_1_sales` | Numeric(18,2) | | Most recent month's sales (NULL if N/A in filing) |
| `month_1_redemptions` | Numeric(18,2) | | Most recent month's redemptions (NULL if N/A in filing) |
| `month_1_reinvestments` | Numeric(18,2) | | Most recent month's reinvestments (NULL if N/A in filing) |
| `month_2_sales` | Numeric(18,2) | | Second most recent month's sales (NULL if N/A in filing) |
| `month_2_redemptions` | Numeric(18,2) | | Second most recent month's redemptions (NULL if N/A in filing) |
| `month_2_reinvestments` | Numeric(18,2) | | Second most recent month's reinvestments (NULL if N/A in filing) |
| `month_3_sales` | Numeric(18,2) | | Third most recent month's sales (NULL if N/A in filing) |
| `month_3_redemptions` | Numeric(18,2) | | Third most recent month's redemptions (NULL if N/A in filing) |
| `month_3_reinvestments` | Numeric(18,2) | | Third most recent month's reinvestments (NULL if N/A in filing) |

**Unique:** `(etf_id, report_date, class_id, filing_date)`

> Note: Monthly flows are extracted from the XML at `/edgarSubmission/formData/fundinfo/returnInfo/monthlyTotReturns` (same location as returns data). The `class_id` field is NULL for fund-level flows or contains the class identifier when flows are reported separately by share class. Flow values of "N/A" in the XML are stored as NULL.

---

### `interest_rate_risk`

Interest rate risk metrics (DV01 and DV100) by currency from NPORT-P filings.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | Integer | PK | |
| `etf_id` | Integer | FK -> etf.id, NOT NULL | Parent ETF |
| `report_date` | Date | NOT NULL | NPORT filing report date |
| `filing_date` | Date | NOT NULL | SEC filing date (enables over-time tracking) |
| `currency_code` | String(3) | NOT NULL | ISO currency code (e.g., USD, EUR) |
| `dv01_3m` | Numeric(24,2) | | DV01 sensitivity for 3-month period |
| `dv01_1y` | Numeric(24,2) | | DV01 sensitivity for 1-year period |
| `dv01_5y` | Numeric(24,2) | | DV01 sensitivity for 5-year period |
| `dv01_10y` | Numeric(24,2) | | DV01 sensitivity for 10-year period |
| `dv01_30y` | Numeric(24,2) | | DV01 sensitivity for 30-year period |
| `dv100_3m` | Numeric(24,2) | | DV100 sensitivity for 3-month period |
| `dv100_1y` | Numeric(24,2) | | DV100 sensitivity for 1-year period |
| `dv100_5y` | Numeric(24,2) | | DV100 sensitivity for 5-year period |
| `dv100_10y` | Numeric(24,2) | | DV100 sensitivity for 10-year period |
| `dv100_30y` | Numeric(24,2) | | DV100 sensitivity for 30-year period |

**Unique:** `(etf_id, report_date, currency_code, filing_date)`

> Note: Interest rate risk metrics are extracted from the XML at `/edgarSubmission/formData/fundinfo/curMetrics`. DV01 measures the dollar value change for a 1 basis point (0.01%) move in interest rates. DV100 measures the dollar value change for a 100 basis point (1%) move. Each metric has five period buckets: 3-month, 1-year, 5-year, 10-year, and 30-year. Multiple currencies may be reported per filing.

---

### `per_share_operating`

Per-share operating performance from N-CSR financial highlights.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | Integer | PK | |
| `etf_id` | Integer | FK -> etf.id, NOT NULL | Parent ETF |
| `fiscal_year_end` | Date | NOT NULL | Fiscal year end date |
| `filing_date` | Date | NOT NULL | SEC filing date (enables over-time tracking) |
| `nav_beginning` | Numeric(10,4) | | NAV at start of period |
| `net_investment_income` | Numeric(10,4) | | Per-share net investment income |
| `net_realized_unrealized_gain` | Numeric(10,4) | | Per-share realized + unrealized gains |
| `total_from_operations` | Numeric(10,4) | | Total income from operations |
| `equalization` | Numeric(10,4) | | Equalization adjustment |
| `nav_end` | Numeric(10,4) | | NAV at end of period |
| `total_return` | Numeric(8,5) | | Total return for the period |
| `math_validated` | Boolean | NOT NULL | Whether NAV math checks out |

**Unique:** `(etf_id, fiscal_year_end, filing_date)`

---

### `per_share_distribution`

Per-share distributions from N-CSR financial highlights.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | Integer | PK | |
| `etf_id` | Integer | FK -> etf.id, NOT NULL | Parent ETF |
| `fiscal_year_end` | Date | NOT NULL | Fiscal year end date |
| `filing_date` | Date | NOT NULL | SEC filing date (enables over-time tracking) |
| `dist_net_investment_income` | Numeric(10,4) | | Distributions from net investment income |
| `dist_realized_gains` | Numeric(10,4) | | Distributions from realized gains |
| `dist_return_of_capital` | Numeric(10,4) | | Return of capital distributions |
| `dist_total` | Numeric(10,4) | | Total distributions |

**Unique:** `(etf_id, fiscal_year_end, filing_date)`

---

### `per_share_ratios`

Per-share supplemental ratios from N-CSR financial highlights.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | Integer | PK | |
| `etf_id` | Integer | FK -> etf.id, NOT NULL | Parent ETF |
| `fiscal_year_end` | Date | NOT NULL | Fiscal year end date |
| `filing_date` | Date | NOT NULL | SEC filing date (enables over-time tracking) |
| `expense_ratio` | Numeric(6,5) | | Expense ratio |
| `portfolio_turnover` | Numeric(8,5) | | Portfolio turnover rate |
| `net_assets_end` | Numeric(20,2) | | Net assets at period end |

**Unique:** `(etf_id, fiscal_year_end, filing_date)`

---

### `processing_log`

Tracks when each parser was last run for each CIK, enabling incremental pipeline processing.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | Integer | PK | |
| `cik` | String(10) | NOT NULL | SEC CIK |
| `parser_type` | String(20) | NOT NULL | Parser identifier (nport, ncsr, prospectus, finhigh, flows) |
| `last_run_at` | DateTime | NOT NULL | Timestamp of last successful parser run |
| `latest_filing_date_seen` | Date | NOT NULL | Most recent filing date processed |

**Unique:** `(cik, parser_type)`

> Note: Used by the `run-all` command to detect when new SEC filings are available and skip CIKs with no updates.

---

## Indexes and Constraints Summary

| Table | Name | Type | Columns |
|---|---|---|---|
| etf | — | UNIQUE | `ticker` |
| etf | — | INDEX | `cik` |
| etf | — | INDEX | `class_id` |
| holding | `holding_uniq` | UNIQUE | `etf_id, report_date, holding_key, filing_date` |
| holding | `holding_etf_report_idx` | INDEX | `etf_id, report_date` |
| holding | `holding_cusip_idx` | INDEX | `cusip` |
| holding | `holding_report_date_idx` | INDEX | `report_date` |
| derivative | `derivative_etf_report_type_name_filing_uniq` | UNIQUE | `etf_id, report_date, derivative_type, underlying_name, filing_date` |
| derivative | `derivative_etf_report_idx` | INDEX | `etf_id, report_date` |
| derivative | `derivative_report_date_idx` | INDEX | `report_date` |
| performance | `performance_etf_fy_filing_uniq` | UNIQUE | `etf_id, fiscal_year_end, filing_date` |
| fee_expense | `fee_expense_etf_date_filing_uniq` | UNIQUE | `etf_id, effective_date, filing_date` |
| flow_data | `flow_data_cik_fy_filing_uniq` | UNIQUE | `cik, fiscal_year_end, filing_date` |
| flow_data | `flow_data_fy_idx` | INDEX | `fiscal_year_end` |
| fund_snapshot | `fund_snapshot_cik_date_uniq` | UNIQUE | `cik, report_date, filing_date` |
| fund_snapshot | `fund_snapshot_cik_idx` | INDEX | `cik` |
| fund_snapshot | `fund_snapshot_report_date_idx` | INDEX | `report_date` |
| per_share_operating | `per_share_operating_etf_fy_filing_uniq` | UNIQUE | `etf_id, fiscal_year_end, filing_date` |
| per_share_distribution | `per_share_distribution_etf_fy_filing_uniq` | UNIQUE | `etf_id, fiscal_year_end, filing_date` |
| per_share_ratios | `per_share_ratios_etf_fy_filing_uniq` | UNIQUE | `etf_id, fiscal_year_end, filing_date` |
| nport_monthly_return | `nport_monthly_return_uniq` | UNIQUE | `etf_id, report_date, class_id, filing_date` |
| nport_monthly_flow | `nport_monthly_flow_uniq` | UNIQUE | `etf_id, report_date, class_id, filing_date` |
| interest_rate_risk | `interest_rate_risk_uniq` | UNIQUE | `etf_id, report_date, currency_code, filing_date` |
| processing_log | `processing_log_cik_parser_uniq` | UNIQUE | `cik, parser_type` |

---

## Data Sources by Filing Type

| Filing Type | Tables Populated |
|---|---|
| NPORT-P | `holding`, `debt_security_detail`, `security_lending`, `derivative`, `fund_snapshot`, `nport_monthly_return`, `nport_monthly_flow`, `interest_rate_risk` |
| N-CSR | `performance`, `per_share_operating`, `per_share_distribution`, `per_share_ratios` |
| 485BPOS | `etf` (objective/strategy), `fee_expense` |
| 24F-2NT | `flow_data` |
