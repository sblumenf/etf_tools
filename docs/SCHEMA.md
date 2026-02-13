## Database Schema Reference

### ETF
The central table. One row per exchange-traded fund, discovered from SEC's `company_tickers_mf.json` and enriched from 485BPOS prospectus filings.

| Field | Description |
|-------|-------------|
| **ticker** | Trading symbol (e.g., SPY, QQQ). Unique identifier for deduplication |
| **cik** | SEC Central Index Key — identifies the issuer/trust. Multiple ETFs can share one CIK |
| **series_id** | SEC Series ID — distinguishes individual funds within a trust |
| **class_id** | SEC Class ID — identifies the share class within a fund. Used by N-CSR XBRL data for fund identification |
| **fund_name** | Full name (e.g., "SPDR S&P 500 ETF Trust"). Backfilled from Yahoo Finance |
| **issuer_name** | Trust or issuer name (e.g., "State Street Global Advisors"). From SEC submissions |
| **strategy_text** | Investment strategy/objective extracted from the 485BPOS prospectus narrative |
| **filing_url** | URL to the source 485BPOS filing on EDGAR |
| **category** | ETF classification — reserved for future use, not yet populated |
| **is_active** | Soft delete flag. Set to False if the ticker disappears from SEC data |
| **last_fetched** | When the pipeline last processed this ETF |
| **incomplete_data** | True if any parser failed during the last pipeline run |

---

### Holding
Individual security positions from quarterly N-PORT filings. One row per security per report date.

| Field | Description |
|-------|-------------|
| **etf** | FK to ETF |
| **report_date** | Quarter-end reporting date of the N-PORT filing |
| **name** | Security name (e.g., "Apple Inc") |
| **cusip** | 9-character CUSIP identifier |
| **isin** | 12-character ISIN identifier |
| **ticker** | Ticker of the held security (not the ETF) |
| **lei** | Legal Entity Identifier of the issuer |
| **balance** | Number of shares, par value, or contracts held |
| **units** | What balance measures: "shares", "principal", "contracts" |
| **value_usd** | Market value in USD |
| **pct_val** | Percentage of the ETF's net asset value (0.05000 = 5%) |
| **asset_category** | SEC asset class code: EC (equity), DBT (debt), etc. |
| **issuer_category** | Issuer type: corporate, government, municipal, etc. |
| **country** | 3-letter country code of the issuer |
| **currency** | 3-letter currency code of the holding |
| **fair_value_level** | GAAP fair value hierarchy: 1 (quoted prices), 2 (observable inputs), 3 (unobservable) |
| **is_restricted** | Whether the security has resale restrictions |

---

### Derivative
Derivative positions (futures, options, swaps, forwards) from N-PORT filings.

| Field | Description |
|-------|-------------|
| **etf** | FK to ETF |
| **report_date** | Quarter-end reporting date |
| **derivative_type** | Instrument type: "future", "option", "swap", "forward" |
| **underlying_name** | Name of the underlying asset or index |
| **underlying_cusip** | CUSIP of the underlying security, if applicable |
| **notional_value** | Notional/face value of the position in USD |
| **counterparty** | Name of the counterparty (for OTC derivatives) |
| **counterparty_lei** | LEI of the counterparty |
| **delta** | Option delta — sensitivity of price to underlying (0 to 1 for calls, -1 to 0 for puts) |
| **expiration_date** | When the contract expires |

---

### Performance
Returns, distributions, and operating metrics from annual/semi-annual N-CSR filings. One row per ETF per fiscal year.

| Field | Description |
|-------|-------------|
| **etf** | FK to ETF |
| **fiscal_year_end** | End date of the reporting period |
| **return_1yr** | 1-year total return as decimal (0.1234 = 12.34%) |
| **return_5yr** | Annualized 5-year return |
| **return_10yr** | Annualized 10-year return |
| **return_since_inception** | Annualized return since fund inception |
| **benchmark_name** | Name of the benchmark index |
| **benchmark_return_1yr/5yr/10yr** | Corresponding benchmark returns |
| **portfolio_turnover** | Portfolio turnover rate as decimal (0.50000 = 50%) |
| **expense_ratio_actual** | Actual expense ratio from operations |

---

### FeeExpense
Fee schedules from 485BPOS prospectus filings. One row per ETF per effective date.

| Field | Description |
|-------|-------------|
| **etf** | FK to ETF |
| **effective_date** | When this fee schedule became effective |
| **management_fee** | Advisory/management fee (0.00450 = 0.45%) |
| **distribution_12b1** | 12b-1 marketing/distribution fee |
| **other_expenses** | Other annual operating expenses |
| **total_expense_gross** | Total expense ratio before any waivers |
| **fee_waiver** | Amount waived by the adviser |
| **total_expense_net** | Net expense ratio the investor actually pays |

---

### FlowData
Dollar-value fund flows from 24F-2NT filings. One row per CIK per fiscal year.

**Important**: 24F-2NT filings report aggregate flow data at the trust (CIK) level, NOT per individual fund/series.

| Field | Description |
|-------|-------------|
| **cik** | SEC Central Index Key — identifies the issuer/trust. Indexed for lookups |
| **fiscal_year_end** | End of the fiscal year covered by the filing |
| **sales_value** | Total dollar value of shares sold (creations) during the year across all series in the trust |
| **redemptions_value** | Total dollar value of shares redeemed during the year across all series in the trust |
| **net_sales** | Net flows: sales minus redemptions. Positive = net inflows |

---

## Entity Relationship Diagram

```mermaid
erDiagram
    ETF ||--o{ Holding : "has many"
    ETF ||--o{ Derivative : "has many"
    ETF ||--o{ Performance : "has many"
    ETF ||--o{ FeeExpense : "has many"

    ETF {
        int id PK
        varchar ticker UK "e.g. SPY"
        varchar cik IX "SEC Central Index Key"
        varchar series_id "nullable"
        varchar class_id IX "nullable, SEC Class ID"
        varchar fund_name "nullable"
        varchar issuer_name
        text strategy_text "nullable"
        url filing_url "nullable"
        varchar category "nullable"
        bool is_active "default true"
        datetime last_fetched "nullable"
        bool incomplete_data "default false"
        datetime created_at
        datetime updated_at
    }

    Holding {
        int id PK
        int etf_id FK
        date report_date IX
        varchar name
        varchar cusip IX "nullable, 9 chars"
        varchar isin "nullable, 12 chars"
        varchar ticker "nullable"
        varchar lei "nullable"
        decimal balance "20,4"
        varchar units "shares|principal|contracts"
        decimal value_usd "20,2"
        decimal pct_val "8,5 (0.05000 = 5%)"
        varchar asset_category "EC|DBT|etc"
        varchar issuer_category "nullable"
        varchar country "nullable, 3 chars"
        varchar currency "3 chars"
        int fair_value_level "nullable, 1|2|3"
        bool is_restricted "default false"
    }

    Derivative {
        int id PK
        int etf_id FK
        date report_date IX
        varchar derivative_type "future|option|swap|forward"
        varchar underlying_name "nullable"
        varchar underlying_cusip "nullable"
        decimal notional_value "20,2"
        varchar counterparty "nullable"
        varchar counterparty_lei "nullable"
        decimal delta "10,6 nullable"
        date expiration_date "nullable"
    }

    Performance {
        int id PK
        int etf_id FK
        date fiscal_year_end "UK(etf,fiscal_year_end)"
        decimal return_1yr "8,5 nullable"
        decimal return_5yr "8,5 nullable"
        decimal return_10yr "8,5 nullable"
        decimal return_since_inception "8,5 nullable"
        varchar benchmark_name "nullable"
        decimal benchmark_return_1yr "8,5 nullable"
        decimal benchmark_return_5yr "8,5 nullable"
        decimal benchmark_return_10yr "8,5 nullable"
        decimal portfolio_turnover "8,5 nullable"
        decimal expense_ratio_actual "6,5 nullable"
    }

    FeeExpense {
        int id PK
        int etf_id FK
        date effective_date "UK(etf,effective_date)"
        decimal management_fee "6,5 nullable"
        decimal distribution_12b1 "6,5 nullable"
        decimal other_expenses "6,5 nullable"
        decimal total_expense_gross "6,5 nullable"
        decimal fee_waiver "6,5 nullable"
        decimal total_expense_net "6,5 nullable"
    }

    FlowData {
        int id PK
        varchar cik IX "10 chars"
        date fiscal_year_end "UK(cik,fiscal_year_end)"
        decimal sales_value "20,4 nullable"
        decimal redemptions_value "20,4 nullable"
        decimal net_sales "20,4 nullable"
    }
```

---

## Data Source Mapping

```
SEC EDGAR Filing Types ──────────────────────── Database Tables

  company_tickers_mf.json ──────────────────┐
  485BPOS (prospectus)  ────────────────────┤── ETF
                                            │
  NPORT-P (quarterly holdings) ─────────────┤── Holding
                                            │── Derivative
                                            │
  N-CSR / N-CSRS (annual/semi-annual) ─────┤── Performance
                                            │
  485BPOS (prospectus fee tables) ──────────┤── FeeExpense
                                            │
  24F-2NT (annual flow notice) ─────────────┘── FlowData
```

---

## Table Relationships (ASCII)

```
                              +-------------+
                              |     ETF     |
                              |-------------|
                              | PK id       |
                              | UK ticker   |
                              | IX cik      |
                              +------+------+
                                     |
              +----------+-----------+-----------+----------+
              |          |           |           |          |
              v          v           v           v          v
        +---------+ +-----------+ +-----------+ +-------+ +--------+
        | Holding | | Derivative| |Performance| |FeExp. | |FlowData|
        |---------| |-----------| |-----------| |-------| |--------|
        | FK etf  | | FK etf    | | FK etf    | |FK etf | |   cik  |
        | IX date | | IX date   | | UK etf+fy | |UK etf | |UK cik  |
        | IX cusip| |           | |           | | +date | | +fy    |
        +---------+ +-----------+ +-----------+ +-------+ +--------+
         1 ETF:N     1 ETF:N       1 ETF:N      1 ETF:N    Per CIK
       (per qtr)   (per qtr)    (per fiscal yr)  (per eff  (per fis
                                                   date)    cal yr)
```

---

## Indexes and Constraints Summary

| Table | Constraint | Type | Columns |
|-------|-----------|------|---------|
| ETF | `etf_ticker_key` | UNIQUE | `ticker` |
| ETF | `etf_cik_idx` | INDEX | `cik` |
| Holding | `holding_etf_report_idx` | INDEX | `etf_id, report_date` |
| Holding | `holding_cusip_idx` | INDEX | `cusip` |
| Holding | `holding_report_date_idx` | INDEX | `report_date` |
| Derivative | `derivative_etf_report_idx` | INDEX | `etf_id, report_date` |
| Derivative | `derivative_report_date_idx` | INDEX | `report_date` |
| Performance | `performance_etf_fy_uniq` | UNIQUE | `etf_id, fiscal_year_end` |
| FeeExpense | `fee_expense_etf_date_uniq` | UNIQUE | `etf_id, effective_date` |
| FlowData | `flow_data_cik_fy_uniq` | UNIQUE | `cik, fiscal_year_end` |
| FlowData | `flow_data_fy_idx` | INDEX | `fiscal_year_end` |

---

## SEC Upstream Source: `company_tickers_mf.json`

The ETF table is seeded from a single SEC file that maps every registered mutual fund and ETF share class to its identifiers. This is the entry point for the entire pipeline.

**URL**: `https://www.sec.gov/files/company_tickers_mf.json`

### JSON Structure

The file uses a compact array-of-arrays format (not objects) with a separate `fields` header:

```json
{
  "fields": ["cik", "seriesId", "classId", "symbol"],
  "data": [
    [2110,    "S000009184", "C000024954", "LACAX"],
    [2110,    "S000009184", "C000024956", "LIACX"],
    [1592900, "S000047440", "C000148278", "IJAN"],
    [1174610, "S000021823", "C000060674", "SSO"]
  ]
}
```

### Field Definitions

| Field | Type | Description |
|-------|------|-------------|
| `cik` | integer | SEC Central Index Key. Identifies the issuer/trust. Multiple funds share one CIK |
| `seriesId` | string | SEC Series ID (e.g., `S000047440`). Identifies a specific fund within a trust |
| `classId` | string | SEC Class ID (e.g., `C000148278`). Identifies a share class within a fund. Maps to `class_id` in ETF table |
| `symbol` | string | Trading ticker symbol. Used as the unique key in the ETF table |

### ETF vs Mutual Fund Filtering

The file contains both ETFs and mutual funds (~50,000+ rows). The pipeline filters using a ticker-length heuristic:

```
 Symbol        Length   Ends in X?   Classification
 ───────────── ──────── ──────────── ──────────────
 SPY           3        no           ETF
 QQQ           3        no           ETF
 TQQQ          4        no           ETF
 QYLD          4        no           ETF
 LACAX         5        yes          Mutual fund (excluded)
 VFINX         5        yes          Mutual fund (excluded)
 AB            2        no           Rejected (too short)
 ABCDEF        6        no           Rejected (too long)
```

**Rules**:
- 3-4 characters long --> ETF (included)
- 5 characters ending in `X` --> mutual fund (excluded)
- Everything else --> rejected

### Data Flow: JSON to ETF Table

```
company_tickers_mf.json
        |
        |  fetch_company_tickers()
        v
  { fields: [...], data: [[...], ...] }
        |
        |  fetch_and_filter_etf_tickers()
        |  - parse array-of-arrays using field indices
        |  - apply is_etf_ticker() filter
        v
  [ {cik, series_id, ticker}, ... ]     ~5,000 ETF records
        |
        |  group by CIK
        v
  { cik: [tickers...], ... }                      ~2,000 unique CIKs
        |
        |  for each CIK:
        |    fetch submissions -> find 485BPOS filing
        |    parse prospectus -> extract fund_name, strategy, issuer
        |    match back to tickers via series_id
        v
  upsert_etf() per ticker
        |
        |  - INSERT if new ticker
        |  - UPDATE strategy, filing_url, issuer_name if exists
        |  - set is_active=True, last_fetched=now()
        v
  ETF table
        |
        |  mark_stale_etfs()
        |  - set is_active=False for any ETF
        |    with last_fetched < run_start
        v
  Final ETF table (active + inactive)
```

### Mapping to ETF Table Columns

| JSON field | ETF column | Notes |
|------------|------------|-------|
| `cik` | `cik` | Cast from int to string, zero-padded to 10 digits for API calls |
| `seriesId` | `series_id` | Used to match tickers to prospectus sections |
| `classId` | `class_id` | Stored in ETF table for N-CSR XBRL data mapping (identifies fund in iXBRL via ClassAxis dimension) |
| `symbol` | `ticker` | Unique key for deduplication |
| — | `fund_name` | Parsed from 485BPOS prospectus, or backfilled from Yahoo Finance |
| — | `issuer_name` | Parsed from SEC submissions JSON |
| — | `strategy_text` | Parsed from 485BPOS prospectus narrative |
| — | `filing_url` | Constructed from CIK + accession number + document name |
