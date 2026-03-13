# Portfolio X-Ray Tool: Data Inventory & Analysis

This directory contains comprehensive research on all available data for developing a portfolio X-Ray tool (inspired by Morningstar's X-Ray).

## Documents

### 1. XRAY_KEY_FINDINGS.txt (Quick Start)
**Size**: 13 KB  
**Read Time**: 10-15 minutes  
**Purpose**: Executive summary of key findings, recommendations, and implementation plan

**Contents**:
- Database schema overview (13 core + 4 derivative tables)
- Filing sources and data freshness
- Critical X-Ray data fields
- Data quality & coverage assessment
- MVP feature recommendations (10 core features)
- Key file locations
- Implementation roadmap

**Start here** if you want a fast overview.

---

### 2. xray_data_inventory.md (Detailed Reference)
**Size**: 46 KB  
**Read Time**: 30-45 minutes  
**Purpose**: Comprehensive field-by-field documentation of all available data

**Contents** (24 sections):
1. Executive Summary
2. Database Schema Inventory
3-17. Individual table documentation (all 13 core + 4 derivative tables)
   - Each table section includes:
     - Field definitions with types
     - Data sources (which SEC filing)
     - X-Ray utility (how it's used)
     - Example data structures
18. Derivable & Computed Fields (SQL examples)
19. External Data Sources (what's missing)
20. Data Availability Timeline & Backfill
21. Data Quality & Maturity Assessment
22. X-Ray Feature Recommendations
23. Implementation Roadmap (3 phases)
24. Reference Documentation Locations

**Use this** when you need to understand a specific field or construct queries.

---

## Data Summary

### What's Available

**Stored in Database**:
- Holdings data: 6+ years of quarterly snapshots (NPORT-P)
- Performance: Annual returns + benchmarks (N-CSR)
- Fees: Management, 12b-1, expense ratios, waivers (485BPOS)
- Flows: Annual sales/redemptions (24F-2NT)
- Risk metrics: Interest rate sensitivity, credit spread risk (NPORT)
- Bond details: Maturity, coupon, credit status
- Derivatives: Swaps, options, forwards with full details
- Fund balance sheet: AUM, leverage, liquidity data

**Can Be Computed**:
- Asset allocation (by category, country, sector)
- Portfolio concentration (Herfindahl index)
- Fee impact on returns
- Liquidity assessment
- Alpha calculation (vs benchmark)
- Risk scenario analysis
- Fund growth trends

**NOT Available** (would require external integration):
- Real-time prices / NAV
- Sector codes (GICS)
- ESG scores
- Credit ratings
- Historical volatility

---

## Quick Reference: Top 10 X-Ray Features

All data available in database, no external APIs required:

1. **Holdings Composition**: Top 10 holdings + "Other" aggregation
2. **Asset Allocation**: Pie chart by category (EC/DBT/FI/Cash)
3. **Geographic Diversification**: Country allocation breakdown
4. **Fee Structure**: Management fee, 12b-1, expense ratio (gross/net), waiver expiration
5. **Performance vs Benchmark**: Returns (1yr/5yr/10yr) with alpha calculation
6. **Interest Rate Risk**: DV01 sensitivities by maturity bucket
7. **Credit Spread Risk**: Investment grade vs high yield exposure
8. **Fund Health**: AUM trend, net flows, investor demand
9. **Liquidity Assessment**: HLI/MLI/LLI/ILI breakdown
10. **Concentration Analysis**: Top holdings concentration %, Herfindahl index

---

## Data Flow

```
SEC EDGAR Filing → Parser → Database Table → X-Ray Query
   (NPORT-P)        nport.py    holding,         SELECT *
                                derivative       FROM holding
   (N-CSR)          ncsr.py     performance      WHERE etf_id=?
                                per_share_*
   (485BPOS)        prospectus.py  fee_expense   SELECT *
                                etf (text)       FROM fee_expense
   (24F-2NT)        flows.py    flow_data        WHERE etf_id=?
```

---

## Key Tables for X-Ray

| Table | Records | Source | Freshness | X-Ray Priority |
|-------|---------|--------|-----------|-----------------|
| `holding` | Millions | NPORT-P | +45 days | HIGH |
| `fee_expense` | 50K | 485BPOS | Ad-hoc | HIGH |
| `performance` | 25K | N-CSR | Annual | HIGH |
| `derivative` | 100K+ | NPORT-P | +45 days | MEDIUM |
| `interest_rate_risk` | 10K+ | NPORT-P | +45 days | MEDIUM |
| `credit_spread_risk` | 5K+ | NPORT-P | +45 days | MEDIUM |
| `flow_data` | 5K | 24F-2NT | Annual | MEDIUM |
| `debt_security_detail` | 10K | NPORT-P | +45 days | LOW |
| `fund_snapshot` | Quarterly | NPORT-P | +45 days | LOW |

---

## Implementation Status

### Available Today
- All database tables populated with 1-2 quarters of recent data
- All parsers working (nport, ncsr, prospectus, finhigh, flows)
- Backfill commands available (--from-date, --to-date)
- Historical data retrievable via backfill (6+ years)

### Ready to Build
- Holdings view (top 10 + other)
- Asset allocation breakdown
- Fee analysis
- Performance comparison
- Risk metrics display
- Fund health indicators

### Requires External Data
- Real-time pricing
- Sector classification
- ESG scores
- Volatility calculations

---

## Key Locations

**Schema Documentation**:
- `/docs/reference/SCHEMA.md` — Full schema with all fields
- `/src/etf_pipeline/models.py` — SQLAlchemy ORM definitions

**Parser Reference**:
- `/docs/reference/PARSER_REFERENCE_MAP.md` — Which filing type for each parser
- `/docs/reference/README.md` — SEC filing specs location

**Code**:
- `/src/etf_pipeline/parsers/` — All 5 parsers
- `/src/etf_pipeline/cli.py` — Available commands

**Backfill**:
- `/docs/backfill-spec.md` — Full backfill implementation plan

---

## Recommended Reading Order

For X-Ray implementation:

1. **XRAY_KEY_FINDINGS.txt** (this directory) — Quick overview
2. **SCHEMA.md** (reference/) — Understand database structure
3. **xray_data_inventory.md** (this directory) — Deep dive on each field
4. **PARSER_REFERENCE_MAP.md** (reference/) — Understand data sources
5. **Test files** (tests/) — See example data structures

---

## SQL Query Examples

### Holdings
```sql
SELECT name, value_usd, pct_val, asset_category
FROM holding
WHERE etf_id = ? AND report_date = ?
ORDER BY value_usd DESC
LIMIT 20
```

### Asset Allocation
```sql
SELECT asset_category, SUM(pct_val) as allocation
FROM holding
WHERE etf_id = ? AND report_date = ?
GROUP BY asset_category
```

### Fees
```sql
SELECT 
  management_fee,
  distribution_12b1,
  total_expense_gross,
  fee_waiver,
  total_expense_net,
  fee_waiver_expiration_date
FROM fee_expense
WHERE etf_id = ?
ORDER BY filing_date DESC
LIMIT 1
```

### Performance vs Benchmark
```sql
SELECT 
  return_1yr, 
  return_5yr,
  return_10yr,
  benchmark_name,
  benchmark_return_1yr,
  benchmark_return_5yr,
  portfolio_turnover,
  expense_ratio_actual
FROM performance
WHERE etf_id = ?
ORDER BY fiscal_year_end DESC
LIMIT 1
```

### Risk Metrics
```sql
SELECT 
  currency_code,
  dv01_5y,
  dv100_5y
FROM interest_rate_risk
WHERE etf_id = ? AND currency_code = 'USD'
ORDER BY report_date DESC
LIMIT 1
```

---

## Questions?

Refer to the detailed sections in `xray_data_inventory.md`:
- **Holdings data**: Section 3
- **Fees**: Section 8
- **Performance**: Section 7
- **Risk metrics**: Sections 13-14
- **Fund health**: Section 10
- **Data quality**: Section 21

---

**Report Generated**: March 12, 2026  
**Codebase Version**: etf_tools master branch  
**Session**: Research complete
