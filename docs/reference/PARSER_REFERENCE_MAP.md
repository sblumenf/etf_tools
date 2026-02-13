# Parser-to-Reference Document Map

Which local reference files to read before building each parser.
All paths are relative to `docs/reference/`.

---

## Parser 1: NPORT-P (Holding + Derivative tables)

**Filing type**: NPORT-P (quarterly portfolio holdings)
**Target tables**: `Holding`, `Derivative`
**edgartools support**: Full — `FundReport.from_filing()` parses holdings and derivatives natively.

### Primary References (read these)
| File | Why |
|------|-----|
| `nport-xsd/EDGAR Form N-PORT XML Technical Specification.pdf` | Definitive field definitions, valid values, required vs optional elements |
| `nport-xsd/EDGAR Form N-PORT XML schema files/eis_NPORT_Filer.xsd` | Top-level XML schema — shows the complete element tree |
| `nport-xsd/EDGAR Form N-PORT XML schema files/eis_NPORT_common.xsd` | Shared types: asset categories, issuer categories, country codes, currency codes |
| `nport-xsd/EDGAR Form N-PORT XML Sample files/N-PORT Sample 1.xml` | Real example filing to validate parser output against |

### Secondary References (consult if needed)
| File | Why |
|------|-----|
| `nport-xsd/EDGAR Form N-PORT XML schema files/eis_Common.xsd` | Common EDGAR types shared across all filing types |
| `nport-xsd/EDGAR Form N-PORT XML Sample files/N-PORT Sample 2.xml` | Additional sample with different derivative types |
| `nport-xsd/EDGAR Form N-PORT XML Sample files/N-PORT Sample 3.xml` | Additional sample for edge cases |

### Context7
Query `/dgunning/edgartools` for: `FundReport`, `securities_data()`, `derivatives_data()`, `InvestmentOrSecurity`, `DerivativeInfo`

### Field Mapping Notes
- `asset_category` valid values defined in `eis_NPORT_common.xsd` (EC, DBT, etc.)
- `issuer_category` valid values defined in `eis_NPORT_common.xsd`
- `fair_value_level` is 1, 2, or 3 per GAAP hierarchy
- `derivative_type` maps from edgartools `derivative_category` field

---

## Parser 2: N-CSR (Performance table)

**Filing type**: N-CSR / N-CSRS (annual/semi-annual certified shareholder reports)
**Target table**: `Performance`
**edgartools support**: Partial — no high-level N-CSR parser. Must use raw HTML/iXBRL extraction or XBRL company facts API.

### Primary References (read these)
| File | Why |
|------|-----|
| `xbrl-oef-2025/oef-sr-2025.xsd` | **Open-End Fund Shareholder Report taxonomy** — defines iXBRL tags for performance returns, expense ratios, distributions |
| `xbrl-oef-2025/oef-2025.xsd` | Main OEF taxonomy — broader set of fund-level tags including portfolio turnover |
| `xbrl-oef-2025/oeftaxonomyguide-2025-03-17.pdf` | Human-readable guide explaining OEF taxonomy tags and their usage |
| `xbrl-oef-2025/oef-2025_lab.xsd` | Label linkbase — maps element IDs to human-readable names (useful for identifying the right tags) |

### Secondary References (consult if needed)
| File | Why |
|------|-----|
| `edgar-xbrl-guide.pdf` | General XBRL/iXBRL filing rules — how tagged data is structured in HTML |
| `edgar-filer-manual-vol2.pdf` | Chapter 6 covers interactive data / XBRL requirements |

### Context7
Query `/dgunning/edgartools` for: `Filing`, `html()`, `xbrl()`, XBRL data extraction patterns

### Field Mapping Notes
- `return_1yr`, `return_5yr`, `return_10yr`, `return_since_inception` — look for OEF taxonomy tags related to average annual returns
- `benchmark_name`, `benchmark_return_*` — look for index/benchmark-related tags in OEF taxonomy
- `portfolio_turnover` — tagged in OEF taxonomy
- `expense_ratio_actual` — tagged in OEF taxonomy

---

## Parser 3: 485BPOS (ETF enrichment + FeeExpense table)

**Filing type**: 485BPOS (post-effective amendment / prospectus)
**Target tables**: `ETF` (strategy_text, fund_name, filing_url), `FeeExpense`
**edgartools support**: Partial — can retrieve filing, but fee table extraction requires iXBRL/HTML parsing.

### Primary References (read these)
| File | Why |
|------|-----|
| `xbrl-rr-2023/rr-2023.xsd` | **Risk/Return Summary taxonomy** — defines iXBRL tags for fee tables (management fee, 12b-1, expense ratios, waivers) |
| `xbrl-rr-2023/rr-preparers-guide-2022-11-04.pdf` | Human-readable guide explaining RR taxonomy tags — shows exactly how fee tables and strategy text are tagged |
| `xbrl-rr-2023/rr-2023_lab.xsd` | Label linkbase — maps element IDs to human-readable fee/expense names |
| `xbrl-rr-2023/rr-2023_doc.xsd` | Documentation linkbase — contains detailed descriptions of each element |
| `xbrl-oef-2025/oef-rr-2025.xsd` | Combined OEF + RR schema — may contain updated fee-related tags |

### Secondary References (consult if needed)
| File | Why |
|------|-----|
| `xbrl-rr-2023/rr-samples/rr-samples-2023/rr01/` | Sample iXBRL Risk/Return filing — test against real tagged data |
| `xbrl-rr-2023/rr-2023_pre.xsd` | Presentation linkbase — shows how fee table elements are ordered/grouped |
| `edgar-xbrl-guide.pdf` | General iXBRL extraction patterns |

### Context7
Query `/dgunning/edgartools` for: `Filing`, `html()`, prospectus/485BPOS access patterns

### Field Mapping Notes
- `management_fee` — RR taxonomy tag for advisory fee percentage
- `distribution_12b1` — RR taxonomy tag for distribution/service fee
- `total_expense_gross` / `total_expense_net` — RR taxonomy has specific tags for gross and net expense ratios
- `fee_waiver` — RR taxonomy tag for contractual fee waiver amount
- `strategy_text` — narrative text, likely tagged with RR `StrategyNarrativeTextBlock` or similar
- `effective_date` — derived from filing effective date

---

## Parser 4: 24F-2NT (FlowData table)

**Filing type**: 24F-2NT (notice of intent to register additional shares / fee calculation)
**Target table**: `FlowData`
**edgartools support**: Minimal — requires raw XML parsing. All post-Feb-2022 filings are pure XML at `primary_doc.xml`.

### Primary References (read these)
| File | Why |
|------|-----|
| `24f2-xsd/EDGAR Form 24F-2 XML Technical Specification/EDGAR Form 24F-2 XML Technical Specification.pdf` | Definitive spec — field definitions, valid values, XML structure |
| `24f2-xsd/EDGAR Form 24F-2 XML Technical Specification/EDGAR Form 24F-2 Schema Files/eis_24F_2NT_Filer.xsd` | Top-level XML schema — the `<item5>` element contains all flow data |
| `24f2-xsd/EDGAR Form 24F-2 XML Technical Specification/EDGAR Form 24F-2 XML Samples/24F-2NT Form N-1A.xml` | Sample filing for N-1A filers (most ETFs are N-1A) |

### Secondary References (consult if needed)
| File | Why |
|------|-----|
| `24f2-xsd/EDGAR Form 24F-2 XML Technical Specification/EDGAR Form 24F-2 XML Samples/24F-2NT S-6 Filer.xml` | Sample for S-6 filers (unit investment trusts like SPY) |
| `24f2-xsd/EDGAR Form 24F-2 XML Technical Specification/EDGAR Form 24F-2 Schema Files/eis_Common.xsd` | Common EDGAR types shared across filing types |
| `edgar-filer-manual-vol2.pdf` | Section 8.2.31 (p.247-258 of chapter 8) covers 24F-2 field-by-field instructions |

### Context7
Query `/dgunning/edgartools` for: `Filing`, form type `24F-2NT`, raw document access patterns

### Field Mapping Notes
- `sales_value` maps to `<aggregateSalePriceOfSecuritiesSold>` (Item 5(i))
- `redemptions_value` maps to `<aggregatePriceOfSecuritiesRedeemedOrRepurchasedInFiscalYear>` (Item 5(ii))
- `net_sales` maps to `<netSales>` (Item 5(v)) — calculated as max(0, 5(i) - totalRedemptionCredits)
- `fiscal_year_end` maps to `<lastDayOfFiscalYear>` (Item 4(a)), format MM/DD/YYYY
- Schema versions: X0101 (pre-2024) and X0102 (current) — Item 5 fields are identical between both
- Multiple `<annualFilingInfo>` elements can appear per filing (series-by-series fee calculation)
- No XBRL — uses proprietary SEC XML schema, namespace `http://www.sec.gov/edgar/twentyfourf2filer`

---

## Cross-Parser References

These documents are useful across all parsers:

| File | Use Case |
|------|----------|
| `edgar-filer-manual-vol2.pdf` | Master reference for any filing type questions — form requirements, document formats, submission rules |
| `edgar-api-overview.pdf` | Understanding EDGAR API endpoints for fetching filings |
| `edgar-xbrl-guide.pdf` | How iXBRL tagging works — needed for N-CSR, 485BPOS, and potentially 24F-2NT parsers |
