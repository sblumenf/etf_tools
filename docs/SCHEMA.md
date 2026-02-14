# Database Schema

SQLite database managed by SQLAlchemy 2.0. All models defined in `src/etf_pipeline/models.py`.

---

## Entity-Relationship Overview

```
ETF (1) ──< Holding
ETF (1) ──< Derivative
ETF (1) ──< Performance
ETF (1) ──< FeeExpense
ETF (1) ──< ShareholderFee
ETF (1) ──< ExpenseExample
ETF (1) ──< PerShareOperating
ETF (1) ──< PerShareDistribution
ETF (1) ──< PerShareRatios

FlowData (standalone, keyed by CIK)
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
| `last_fetched` | DateTime | | Last pipeline run timestamp |
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

**Unique:** `(etf_id, report_date, cusip, filing_date)`
**Indexes:** `(etf_id, report_date)`, `(cusip)`, `(report_date)`

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

**Unique:** `(etf_id, report_date, derivative_type, underlying_name, filing_date)`
**Indexes:** `(etf_id, report_date)`, `(report_date)`

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

### `shareholder_fee`

Shareholder-level fees from 485BPOS prospectus filings.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | Integer | PK | |
| `etf_id` | Integer | FK -> etf.id, NOT NULL | Parent ETF |
| `effective_date` | Date | NOT NULL | Prospectus effective date |
| `filing_date` | Date | NOT NULL | SEC filing date (enables over-time tracking) |
| `front_load` | Numeric(6,5) | | Front-end sales load |
| `deferred_load` | Numeric(6,5) | | Deferred sales load |
| `reinvestment_charge` | Numeric(6,5) | | Dividend reinvestment charge |
| `redemption_fee` | Numeric(6,5) | | Redemption fee |
| `exchange_fee` | Numeric(6,5) | | Exchange fee |

**Unique:** `(etf_id, effective_date, filing_date)`

---

### `expense_example`

Dollar-cost examples from 485BPOS prospectus filings ($10,000 investment).

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | Integer | PK | |
| `etf_id` | Integer | FK -> etf.id, NOT NULL | Parent ETF |
| `effective_date` | Date | NOT NULL | Prospectus effective date |
| `filing_date` | Date | NOT NULL | SEC filing date (enables over-time tracking) |
| `year_01` | Integer | | Cost after 1 year ($) |
| `year_03` | Integer | | Cost after 3 years ($) |
| `year_05` | Integer | | Cost after 5 years ($) |
| `year_10` | Integer | | Cost after 10 years ($) |

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
| holding | `holding_etf_report_cusip_filing_uniq` | UNIQUE | `etf_id, report_date, cusip, filing_date` |
| holding | `holding_etf_report_idx` | INDEX | `etf_id, report_date` |
| holding | `holding_cusip_idx` | INDEX | `cusip` |
| holding | `holding_report_date_idx` | INDEX | `report_date` |
| derivative | `derivative_etf_report_type_name_filing_uniq` | UNIQUE | `etf_id, report_date, derivative_type, underlying_name, filing_date` |
| derivative | `derivative_etf_report_idx` | INDEX | `etf_id, report_date` |
| derivative | `derivative_report_date_idx` | INDEX | `report_date` |
| performance | `performance_etf_fy_filing_uniq` | UNIQUE | `etf_id, fiscal_year_end, filing_date` |
| fee_expense | `fee_expense_etf_date_filing_uniq` | UNIQUE | `etf_id, effective_date, filing_date` |
| shareholder_fee | `shareholder_fee_etf_date_filing_uniq` | UNIQUE | `etf_id, effective_date, filing_date` |
| expense_example | `expense_example_etf_date_filing_uniq` | UNIQUE | `etf_id, effective_date, filing_date` |
| flow_data | `flow_data_cik_fy_filing_uniq` | UNIQUE | `cik, fiscal_year_end, filing_date` |
| flow_data | `flow_data_fy_idx` | INDEX | `fiscal_year_end` |
| per_share_operating | `per_share_operating_etf_fy_filing_uniq` | UNIQUE | `etf_id, fiscal_year_end, filing_date` |
| per_share_distribution | `per_share_distribution_etf_fy_filing_uniq` | UNIQUE | `etf_id, fiscal_year_end, filing_date` |
| per_share_ratios | `per_share_ratios_etf_fy_filing_uniq` | UNIQUE | `etf_id, fiscal_year_end, filing_date` |
| processing_log | `processing_log_cik_parser_uniq` | UNIQUE | `cik, parser_type` |

---

## Data Sources by Filing Type

| Filing Type | Tables Populated |
|---|---|
| NPORT-P | `holding`, `derivative` |
| N-CSR | `performance`, `per_share_operating`, `per_share_distribution`, `per_share_ratios` |
| 485BPOS | `etf` (objective/strategy), `fee_expense`, `shareholder_fee`, `expense_example` |
| 24F-2NT | `flow_data` |
