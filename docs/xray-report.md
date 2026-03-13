# ETF X-Ray Tool: Comprehensive Analysis & Application Report

**Date**: March 12, 2026
**Purpose**: Evaluate the feasibility and scope of building a portfolio X-Ray tool using SEC filing data already captured in the etf_tools database.

---

## Table of Contents

1. [What Morningstar X-Ray Does](#1-what-morningstar-x-ray-does)
2. [Your Data: What You Already Have](#2-your-data-what-you-already-have)
3. [Single-ETF X-Ray: Core Features](#3-single-etf-x-ray-core-features)
4. [Multi-ETF Portfolio X-Ray: The Real Power](#4-multi-etf-portfolio-x-ray-the-real-power)
5. [What You Can Do That Morningstar Cannot](#5-what-you-can-do-that-morningstar-cannot)
6. [Historical Analysis: The Backfill Advantage](#6-historical-analysis-the-backfill-advantage)
7. [Risk Analytics Deep Dive](#7-risk-analytics-deep-dive)
8. [Fee and Cost Transparency](#8-fee-and-cost-transparency)
9. [Fund Health and Flow Analysis](#9-fund-health-and-flow-analysis)
10. [Bond and Fixed-Income Intelligence](#10-bond-and-fixed-income-intelligence)
11. [Derivatives and Hidden Leverage](#11-derivatives-and-hidden-leverage)
12. [Data Gaps and External Enrichment](#12-data-gaps-and-external-enrichment)
13. [Application Ideas: From MVP to Full Product](#13-application-ideas-from-mvp-to-full-product)
14. [Implementation Roadmap](#14-implementation-roadmap)

---

## 1. What Morningstar X-Ray Does

Morningstar X-Ray is a portfolio analysis tool that looks through a fund's wrapper to examine the actual underlying holdings. It was recently retired from Morningstar's consumer platform (April 2025), though the API and advisor-workstation versions persist.

### Single Fund View

For an individual ETF, X-Ray shows:

- **Asset allocation**: Cash, US stocks, non-US stocks, bonds, other
- **Stock sectors**: 12 sectors grouped into cyclical, sensitive, and defensive super-sectors
- **World regions**: Americas, Greater Europe, Greater Asia with sub-regions
- **Equity style box**: A 9-cell grid combining market cap (large/mid/small) with value/blend/growth
- **Fixed-income style box**: Interest rate sensitivity crossed with credit quality
- **Stock valuation stats**: Price-to-book, price-to-earnings
- **Bond metrics**: Average effective maturity, duration, credit quality distribution
- **Fees**: Expense ratio

### Portfolio View (Multiple Funds)

When analyzing a portfolio of ETFs, X-Ray aggregates all holdings across all funds and provides:

- **Consolidated holdings**: A single view of every security owned across all funds
- **Overlap detection**: The "Stock Intersection" feature shows the top 50 stocks that appear in multiple funds
- **Benchmark comparison**: Five preset target allocations ranging from aggressive to conservative
- **Holdings breakdown**: Which individual securities are driving overweight or underweight positions relative to a benchmark

### Known Limitations

- **No sector data from SEC filings**: Morningstar relies on its own proprietary sector classification
- **Stale data**: Holdings are often 45+ days old by the time filings hit EDGAR
- **No derivatives exposure**: The consumer tool does not surface derivative positions
- **No securities lending data**: Hidden revenue is invisible
- **No liquidity classification**: Users cannot see how liquid the fund's holdings really are
- **No historical tracking**: X-Ray is a point-in-time snapshot with no drift or evolution analysis
- **No fund flow data**: No visibility into whether money is flowing in or out of the fund

---

## 2. Your Data: What You Already Have

Your database contains 13 core tables plus 4 derivative detail tables, sourced from four SEC filing types. This is a significantly richer dataset than what Morningstar exposes to retail investors.

### Data Sources

| Filing Type | What It Contains | Frequency | Historical Depth |
|-------------|-----------------|-----------|-----------------|
| **N-PORT** (quarterly) | Holdings, derivatives, risk metrics, liquidity, monthly returns/flows | Quarterly | Q1 2020 onward (backfillable) |
| **N-CSR** (annual) | Performance returns, benchmarks, turnover, per-share data | Annual | FY 2021+ (backfillable to 2015) |
| **485BPOS** (prospectus) | Fees, waivers, investment objectives, strategy narratives, risk disclosures | Ad-hoc | Aug 2024+ (backfillable to ~2010) |
| **24F-2NT** (annual) | Fund sales, redemptions, net flows at issuer level | Annual | FY 2021+ (backfillable to 2015) |

### Key Data Assets

**Portfolio composition** (from N-PORT): Every holding with name, CUSIP, ISIN, ticker, value in USD, percent of net assets, asset category, issuer category, country, currency, liquidity classification, and fair value hierarchy level.

**Risk metrics** (from N-PORT): Interest rate sensitivity (DV01) across five maturity buckets and multiple currencies. Credit spread sensitivity (CS01) for investment-grade and high-yield bonds. These are professional-grade risk measures that retail tools never show.

**Derivative positions** (from N-PORT): Full details on swaps (with individual leg data), options (strike, expiry, put/call), forwards (currencies, settlement dates), and futures. Includes notional values, counterparties, unrealized gains/losses, and option delta.

**Performance and benchmarks** (from N-CSR): Annual returns at 1-year, 5-year, 10-year, and since-inception intervals. Benchmark returns for comparison. Portfolio turnover rate and actual expense ratio.

**Fee structure** (from 485BPOS): Management fee, 12b-1 fee, other expenses, acquired fund fees. Both gross and net expense ratios. Fee waiver amounts and expiration dates. Investment objective, strategy narrative, and principal risk disclosures.

**Fund flows** (from 24F-2NT): Annual aggregate sales, redemptions, and net activity at the issuer level. Monthly rolling 3-month flows from N-PORT.

**Fund balance sheet** (from N-PORT fund_snapshot): Total assets, total liabilities, net assets, cash, borrowings, and calculated leverage ratios.

### Data Quality

- Holdings, fund snapshots: 90%+ completeness across all ETFs
- Performance, fees, flows: 70-90% completeness
- Derivatives, interest rate risk, credit spread risk: 40-60% (only relevant for funds that hold these instruments)
- Debt security details, securities lending: 20-40% (bond-focused and lending-active funds only)

---

## 3. Single-ETF X-Ray: Core Features

These features can be built today using data already in your database. No external sources required.

### 3.1 Holdings Composition

Display the top 10 holdings ranked by portfolio weight, with a rolled-up "everything else" row. Show each holding's name, ticker (if available), value in USD, and percent of net assets.

This is the foundational view. Every other analysis builds on top of it.

### 3.2 Asset Allocation Breakdown

Group holdings by `asset_category` (equity, debt, fixed income, cash, etc.) and show a percentage breakdown. This answers the basic question: what does this fund actually own?

N-PORT uses standardized codes: EC (equity common), EP (equity preferred), DBT (debt), FI (fixed income), STIV (short-term investment vehicle, i.e., cash equivalent), and others.

### 3.3 Geographic Diversification

Group holdings by `country` (ISO 3-letter codes) and show top countries by allocation. This surfaces geographic concentration that fund names often obscure. A "Global Equity" fund might be 60% US.

### 3.4 Liquidity Profile

N-PORT requires funds to classify every holding into one of four liquidity buckets:

- **Highly Liquid (HLI)**: Can be converted to cash in 3 business days or fewer without significantly changing the market value
- **Moderately Liquid (MLI)**: Can be converted in 3 business days or fewer, but conversion may affect market value
- **Less Liquid (LLI)**: Cannot be sold or disposed of within 7 calendar days without significant impact
- **Illiquid (ILI)**: Cannot be sold or disposed of within 7 calendar days without significant impact AND there is no reliable market price

This is data that Morningstar does not surface. A fund with 15% in less-liquid or illiquid assets behaves very differently in a market sell-off than one with 98% highly liquid holdings.

### 3.5 Fee Structure Card

Show management fee, 12b-1 fee, other expenses, and acquired fund fees. Display both gross and net expense ratios. Highlight fee waivers with their expiration dates — a waiver expiring in 3 months means the fund's effective cost is about to increase.

### 3.6 Performance vs. Benchmark

Display 1-year, 5-year, 10-year, and since-inception returns alongside benchmark returns. Calculate alpha (fund return minus benchmark return) at each interval. Show portfolio turnover rate and actual expense ratio from the shareholder report.

### 3.7 Fund Health Dashboard

Combine several data points into a single health assessment:

- **AUM trend**: Is the fund's asset base growing or shrinking?
- **Net flows**: Are investors buying in or redeeming out?
- **Leverage ratio**: Total borrowings relative to total assets (from fund_snapshot)
- **Cash position**: How much cash is the fund holding? High cash can indicate defensive positioning or inflows waiting to be deployed.

### 3.8 Concentration Analysis

Calculate the percentage of portfolio value held in the top 5, top 10, and top 20 positions. Compute a Herfindahl-Hirschman Index (HHI) for a single number summarizing concentration. A fully diversified 500-stock index fund will have an HHI near 20; a concentrated 30-stock fund might have an HHI of 500+.

---

## 4. Multi-ETF Portfolio X-Ray: The Real Power

The multi-ETF view is where your tool can genuinely surpass what Morningstar offered. When an investor holds 5-10 ETFs, they need to understand the portfolio as a whole, not each fund in isolation.

### 4.1 Aggregate Holdings View

Combine all holdings across all ETFs in the portfolio, weighted by each ETF's allocation. If SPY is 40% of the portfolio and QQQ is 30%, Apple's weight in the combined view reflects its weight in SPY times 0.40 plus its weight in QQQ times 0.30.

This produces a single, consolidated list of every security the investor effectively owns, with accurate portfolio-level weights.

### 4.2 Overlap Detection

Identify securities that appear in multiple ETFs within the portfolio. For each overlapping security, show:

- Which funds hold it
- The weight in each fund
- The combined portfolio-level weight
- Whether the overlap is intentional diversification or unintentional redundancy

**Simple overlap percentage** (how many holdings appear in both funds) is misleading. Two funds might share 200 holdings by count but only 5% by weight. Weight-adjusted overlap is the meaningful metric.

### 4.3 Redundancy Scoring

Score each ETF in the portfolio on a 0-100 scale for how much unique exposure it provides. An ETF that overlaps 90% by weight with the rest of the portfolio scores low — the investor is paying an extra expense ratio for almost no incremental diversification.

This directly answers: "Should I keep this ETF, or is it redundant?"

### 4.4 Exposure Gap Analysis

Compare the portfolio's aggregate holdings against a target benchmark (e.g., a global all-cap index). Identify sectors, countries, or asset types that the portfolio underweights or overweights. This tells the investor what they are missing, not just what they own.

### 4.5 Portfolio-Level Concentration

Apply the same concentration metrics from the single-ETF view (HHI, top-10 weight) to the aggregate portfolio. An investor might own 5 "diversified" ETFs and still have 15% of their total portfolio in Apple because Apple is a top holding in all of them.

### 4.6 Asset-Weighted Fee Analysis

Calculate the blended expense ratio across the entire portfolio, weighted by each ETF's allocation. Show which ETFs are the most expensive per unit of unique exposure they provide. A high-fee ETF that is also highly redundant with cheaper alternatives is an obvious candidate for replacement.

---

## 5. What You Can Do That Morningstar Cannot

These features are possible because you have direct access to SEC filing data that commercial tools either do not ingest or do not surface.

### 5.1 Derivatives Exposure Transparency

Most retail investors have no idea how much derivative exposure sits inside their ETFs. Your database captures every derivative position from N-PORT: swaps, options, forwards, and futures with full details.

**Application**: Show the total notional value of derivatives as a percentage of fund net assets. A fund with $1 billion in net assets and $3 billion in notional derivative exposure is effectively 3x leveraged through derivatives, even though its "leverage ratio" from the balance sheet looks normal.

Break out derivative exposure by type (interest rate swaps, equity options, FX forwards, credit default swaps) so investors can understand what kind of risk the derivatives create.

### 5.2 Counterparty Risk Map

Every derivative position in N-PORT includes the counterparty name and LEI. Aggregate counterparty exposure across a portfolio of ETFs. If three of your five ETFs all have large swap positions with Goldman Sachs, that is a concentration of counterparty risk that no consumer tool surfaces.

### 5.3 Securities Lending Revenue

Some funds participate in securities lending programs, lending out their holdings to short sellers in exchange for fees. This revenue can partially offset the fund's expense ratio. Your database captures lending data where it exists.

**Application**: Calculate the "effective expense ratio" — the advertised expense ratio minus securities lending revenue. Show investors which ETFs are earning money on the side and which are not.

### 5.4 Liquidity Stress Testing

Using the liquidity classification data (HLI/MLI/LLI/ILI), model what happens to the portfolio if it needs to liquidate quickly. Highly liquid assets can be sold immediately; less liquid and illiquid assets may need to be sold at a discount or cannot be sold at all.

**Application**: Show a "liquidity under stress" metric — what percentage of the portfolio could be liquidated in 3 days, 7 days, and 30 days?

### 5.5 Fee Waiver Expiration Alerts

Your prospectus data includes fee waiver expiration dates. Many new ETFs launch with fee waivers to attract assets, then quietly let the waivers expire.

**Application**: Alert investors when a fee waiver in their portfolio is expiring within the next 6 months. Show the projected cost increase.

### 5.6 Fair Value Hierarchy Breakdown

N-PORT classifies every holding by GAAP fair value level:

- **Level 1**: Quoted prices in active markets (most transparent)
- **Level 2**: Observable inputs other than Level 1 prices (less transparent)
- **Level 3**: Unobservable inputs — essentially management's best guess (least transparent)

A fund with significant Level 3 holdings has valuation risk that most investors are unaware of. This data is in your database and no consumer tool surfaces it.

---

## 6. Historical Analysis: The Backfill Advantage

With the backfill command, you can retrieve N-PORT data back to Q1 2020 (6+ years of quarterly holdings) and N-CSR data back to FY 2015 (10+ years of annual performance). This historical depth enables analyses that point-in-time tools cannot perform.

### 6.1 Style Drift Detection

Track how a fund's characteristics change over time. A "large-cap value" fund that gradually increases its allocation to mid-cap growth stocks is drifting from its stated mandate. Measure drift by tracking changes in:

- Country allocation percentages quarter over quarter
- Asset category mix over time
- Concentration (HHI) trend
- Top-10 holdings turnover

Flag funds where the composition today looks substantially different from the composition 2 years ago. This can reveal that the fund the investor originally bought is no longer the fund they own.

### 6.2 Holdings Turnover Analysis

Compare quarter-to-quarter holdings to calculate what percentage of positions are new, removed, or changed in weight. High turnover suggests active management (or index reconstitution). Correlate turnover with performance to see whether the trading is adding value.

### 6.3 Concentration Trend

Plot HHI or top-10 weight over time. A rising trend means the fund is becoming more concentrated. In the S&P 500, for example, concentration has increased dramatically over the past 5 years as mega-cap tech stocks have grown. An investor who bought "broad market diversification" in 2020 now holds something much more concentrated.

### 6.4 Geographic Shift Tracking

Plot country allocation over time. If an "international" fund's US allocation has crept from 5% to 20% over three years, that changes the portfolio's role.

### 6.5 Fee Evolution

Track expense ratios over time to see if a fund is getting cheaper or more expensive. Many ETFs have reduced fees over the years due to competition. Others have seen fee waivers expire, increasing costs. Historical prospectus data lets you show this trend.

### 6.6 Flow Momentum

Plot fund flows over time. Sustained outflows can indicate declining investor confidence. In extreme cases, persistent outflows can lead to fund liquidation. Conversely, rapid inflows can cause tracking error as the manager deploys new cash.

---

## 7. Risk Analytics Deep Dive

### 7.1 Interest Rate Sensitivity

Your database stores DV01 (dollar value of a 01 — the change in portfolio value for a 1 basis point change in interest rates) across five maturity buckets: 3-month, 1-year, 5-year, 10-year, and 30-year. It also stores DV100 for a full 100 basis point (1%) move.

**Application**: Show bond ETF investors exactly how much money they stand to gain or lose for a given interest rate move. "If the 10-year Treasury yield rises by 1%, this fund's value would decline by approximately $X per $10,000 invested."

Break this out across the yield curve to show whether the fund is more sensitive to short-term or long-term rate changes.

### 7.2 Credit Spread Sensitivity

CS01 data shows how the portfolio responds to a 1 basis point widening in credit spreads, broken out by investment-grade and high-yield. This tells investors how exposed they are to a credit market sell-off (when spreads widen, bond prices fall).

**Application**: "If investment-grade credit spreads widen by 50 basis points, this fund would lose approximately $X per $10,000 invested."

### 7.3 Multi-ETF Risk Aggregation

When analyzing a portfolio of ETFs, aggregate DV01 and CS01 across all holdings. An investor might hold a Treasury ETF, a corporate bond ETF, and a high-yield ETF. The combined interest rate and credit sensitivity of the portfolio may be larger than they realize.

### 7.4 Concentration Risk Indices

Calculate multiple concentration metrics for the aggregate portfolio:

- **Herfindahl-Hirschman Index (HHI)**: Sum of squared weights. Low values mean broad diversification; high values mean concentration.
- **Top-N concentration**: Percentage of portfolio in the top 5, 10, and 20 holdings.
- **Single-name maximum**: The largest single-security exposure across the entire portfolio.
- **Country concentration**: HHI applied to country allocations.

---

## 8. Fee and Cost Transparency

### 8.1 Complete Fee Decomposition

For each ETF, show:

| Fee Component | Source | Notes |
|--------------|--------|-------|
| Management fee | 485BPOS | Base advisory fee |
| 12b-1 fee | 485BPOS | Distribution/marketing fee |
| Other expenses | 485BPOS | Administrative, legal, custody, etc. |
| Acquired fund fees | 485BPOS | Fees of underlying funds (fund-of-funds) |
| Gross expense ratio | 485BPOS | Total before waivers |
| Fee waiver | 485BPOS | Contractual reduction |
| Net expense ratio | 485BPOS | What the investor actually pays |
| Waiver expiration | 485BPOS | When the discount ends |
| Actual expense ratio | N-CSR | What was actually charged last year |

### 8.2 Portfolio-Level Cost Analysis

For a portfolio of ETFs, calculate:

- **Blended expense ratio**: Weighted average of each ETF's net expense ratio
- **Total annual cost**: Blended ER multiplied by total portfolio value
- **Cost per ETF**: How much each position costs annually
- **Cost vs. contribution**: Compare each ETF's cost to its unique diversification contribution

### 8.3 Fee Waiver Risk

Identify ETFs in the portfolio where fee waivers are expiring. Calculate the projected cost increase if all waivers expire. Show when each waiver expires and what the gross expense ratio would become.

---

## 9. Fund Health and Flow Analysis

### 9.1 AUM and Flow Trends

Combine fund_snapshot (quarterly net assets) with flow_data (annual sales/redemptions) and nport_monthly_flow (3-month rolling) to build a picture of fund health over time.

**Red flags to surface**:
- Net assets declining for 3+ consecutive quarters
- Persistent net redemptions (more money leaving than entering)
- AUM below $50M (potential liquidation risk)
- Accelerating outflows (outflows increasing quarter over quarter)

### 9.2 Leverage Monitoring

The fund_snapshot table captures total borrowings and total assets. Calculate leverage ratio (borrowings / net assets). Most vanilla ETFs have zero leverage. Leveraged ETFs, alternative strategy funds, and some bond funds use borrowing. Surface this clearly.

### 9.3 Cash Position Analysis

Show the fund's cash position as a percentage of net assets. Unusually high cash (above 5% for a fully invested fund) can mean:

- Recent large inflows not yet deployed
- Defensive positioning by the manager
- Preparation for anticipated redemptions

---

## 10. Bond and Fixed-Income Intelligence

For bond ETFs, your database has a dedicated `debt_security_detail` table with granular data.

### 10.1 Maturity Profile

Group bond holdings by maturity date to build a "bond ladder" view. Show what percentage of the portfolio matures in each time bucket (0-1 year, 1-3 years, 3-5 years, 5-10 years, 10+ years). This tells the investor about reinvestment risk and interest rate sensitivity from a different angle than DV01.

### 10.2 Coupon Analysis

Break down bond holdings by coupon type: fixed rate, floating rate, variable rate, zero coupon, and others. Show the weighted average coupon rate. This matters for income-focused investors.

### 10.3 Credit Quality Indicators

The `debt_security_detail` table includes flags for whether a bond is in default or has missed interest payments (`is_default`, `are_interest_payments_in_arrears`). While these are binary flags rather than full credit ratings, a fund with any holdings in default is worth flagging.

### 10.4 Annualized Rate Distribution

Show the distribution of coupon rates across the portfolio. Are the bonds yielding 2%, 5%, 8%? A wide distribution might indicate a barbell strategy.

---

## 11. Derivatives and Hidden Leverage

### 11.1 Derivative Type Breakdown

Show the composition of derivative positions by type:

- **Swaps** (interest rate, total return, credit default): Often used for duration management or synthetic exposure
- **Options** (calls and puts): Used for hedging or income generation (covered calls)
- **Forwards** (mostly FX): Used for currency hedging in international funds
- **Futures** (equity index, bond, commodity): Used for cash equitization or tactical allocation

### 11.2 Effective Leverage Calculation

Sum total notional value of all derivative positions and divide by fund net assets. This "gross notional leverage" number reveals the true economic exposure of the fund. A fund with $1B in net assets and $2B in derivatives notional has 3x effective exposure.

### 11.3 Derivative Profit/Loss

Aggregate `unrealized_appreciation` across all derivative positions. Show total mark-to-market gains and losses from the derivatives book. A large unrealized loss on derivatives is a risk indicator.

### 11.4 Multi-Fund Counterparty Aggregation

Across a portfolio of ETFs, aggregate counterparty exposure. If Goldman Sachs is the counterparty on $500M of swaps across three different funds in the portfolio, that represents a meaningful concentration of counterparty risk that is invisible when looking at each fund individually.

---

## 12. Data Gaps and External Enrichment

Some analyses require data that is not available in SEC filings. These are opportunities for future enrichment.

### What You Do Not Have

| Data Point | Why It Matters | Potential Source |
|-----------|---------------|-----------------|
| **Sector classification (GICS/ICB)** | Sector allocation is a core X-Ray feature | OpenFIGI API, or CUSIP-to-sector mapping file |
| **Real-time prices and NAV** | Portfolio valuation, intraday tracking | Yahoo Finance API, IEX Cloud |
| **Historical volatility** | Risk metrics, Sharpe ratio | Calculate from monthly return data in your database |
| **Correlation matrix** | Diversification measurement | Calculate from monthly returns |
| **Credit ratings (Moody's/S&P)** | Bond quality assessment | Partially inferable from N-PORT categories |
| **ESG scores** | ESG-aware portfolio analysis | MSCI, Sustainalytics |
| **Dividend history** | Income analysis | SEC filings contain some, or Yahoo Finance |

### What You Can Derive Without External Data

- **Volatility**: Use `nport_monthly_return` (3-month rolling) to compute annualized volatility
- **Sharpe-like ratio**: Return from N-CSR performance / volatility from monthly returns (use T-bill rate as risk-free proxy)
- **Correlation**: Calculate pairwise correlations between ETFs using monthly return data
- **Tracking error**: Compare fund returns to benchmark returns from N-CSR performance data

---

## 13. Application Ideas: From MVP to Full Product

### Tier 1: Single-ETF X-Ray (Build First)

A command-line or web interface that takes one ticker and produces a comprehensive report:

1. **Holdings card**: Top 10 + "other" with weights
2. **Asset allocation**: Pie chart by asset category
3. **Geographic map**: Top countries by allocation
4. **Liquidity profile**: Bar chart of HLI/MLI/LLI/ILI distribution
5. **Fee card**: Expense ratio breakdown with waiver status
6. **Performance card**: Returns vs. benchmark with alpha
7. **Risk card**: DV01 and CS01 sensitivity (for bond funds)
8. **Fund health**: AUM, flows, leverage, cash position
9. **Concentration**: HHI and top-10 weight

This is achievable with nothing but the data in your database today.

### Tier 2: Multi-ETF Portfolio X-Ray

Accept a list of tickers with allocations and produce:

1. **Aggregate holdings**: Consolidated view across all ETFs
2. **Overlap matrix**: Pairwise overlap between each pair of ETFs (by weight)
3. **Redundancy scores**: Per-ETF score for unique contribution
4. **Portfolio-level concentration**: HHI and top-10 across the aggregate
5. **Blended fees**: Asset-weighted expense ratio and total annual cost
6. **Combined risk metrics**: Aggregate DV01 and CS01 (for fixed-income portfolios)
7. **Counterparty aggregation**: Combined derivative counterparty exposure

### Tier 3: Historical and Temporal Analysis

Using backfilled data:

1. **Style drift monitor**: Quarter-over-quarter changes in asset mix, country allocation, concentration
2. **Concentration trend**: HHI plotted over time for each ETF and the aggregate portfolio
3. **Fee evolution**: Expense ratio history with waiver expirations marked
4. **Flow momentum**: Fund flow trends over time with red-flag alerts
5. **Holdings turnover**: New/removed positions each quarter
6. **Geographic shift**: Country allocation changes over time

### Tier 4: Advanced Analytics and Alerts

1. **Derivative leverage dashboard**: Gross notional as percent of NAV, by derivative type
2. **Liquidity stress test**: "What percentage of the portfolio can be liquidated in N days?"
3. **Fee waiver expiration calendar**: Upcoming cost increases across the portfolio
4. **Portfolio optimizer**: Given the overlap analysis, suggest which ETFs to keep and which to replace
5. **Rebalancing signals**: When drift from target allocation exceeds a threshold
6. **AI-generated commentary**: Natural language summary of portfolio characteristics, risks, and notable changes

### Creative Application Ideas

**"What Changed" Report**: After each quarterly N-PORT filing, automatically generate a report showing what changed in each ETF's holdings since the last quarter. New positions, exited positions, significant weight changes. This is a quarterly monitoring tool that runs on autopilot.

**Fund Comparison Tool**: Side-by-side comparison of two ETFs across all dimensions — holdings overlap, fee comparison, performance comparison, risk profile differences. Directly answers: "Should I own ETF A or ETF B?"

**Portfolio Construction Assistant**: Given a target allocation (e.g., 60/40 stocks/bonds, 70% US / 30% international), suggest which ETFs from the database would best achieve that target with minimal overlap and lowest total cost.

**Liquidation Risk Score**: Combine liquidity classification, AUM size, flow trends, and leverage into a single score that estimates how likely a fund is to face liquidation pressure. Small funds with persistent outflows and illiquid holdings are at highest risk.

**Hidden Cost Calculator**: For each ETF, compute a "true cost" that includes the stated expense ratio, the cost impact of portfolio turnover, and any fee waivers that are about to expire. Express this as a single annual dollar amount for a given investment size.

**Counterparty Network Graph**: Visualize which counterparties connect which funds through derivative positions. A network diagram where nodes are funds and counterparties, and edges are derivative exposures. This reveals systemic concentration that per-fund analysis misses.

---

## 14. Implementation Roadmap

### Phase 1: Data Access Layer

Build query functions that retrieve and aggregate data for X-Ray views. This is the foundation everything else depends on.

- Holdings query (with optional multi-ETF aggregation)
- Fee query (latest fee structure per ETF)
- Performance query (latest returns and benchmarks)
- Risk query (DV01, CS01)
- Fund health query (snapshot, flows)
- Overlap calculator (pairwise and portfolio-level)

### Phase 2: Single-ETF X-Ray

Build the core report for one ticker at a time. Start with a CLI command that outputs formatted text or JSON. This validates the data and the queries before adding complexity.

### Phase 3: Multi-ETF Portfolio X-Ray

Add portfolio-level aggregation. Accept a portfolio definition (tickers + weights) and produce the aggregate analysis with overlap detection and redundancy scoring.

### Phase 4: Historical Analysis

Run the backfill command to populate historical data. Build temporal queries and drift detection. This phase depends on having historical data in the database.

### Phase 5: External Enrichment (Optional)

Add sector classification, real-time prices, or other external data sources to fill the gaps identified in Section 12. This is optional — the core tool is valuable without it.

### Phase 6: Visualization (Optional)

Add a web frontend or interactive dashboard. The underlying analytics are more important than the presentation layer, but visualization makes the tool more accessible.

---

## Summary

Your SEC filing data gives you a foundation that is, in several dimensions, richer than what Morningstar X-Ray exposed to retail investors. Morningstar had better sector classification and real-time pricing, but you have derivatives exposure, liquidity classifications, fee waiver details, securities lending data, interest rate and credit spread sensitivity, fund flow data, and the ability to track all of these over time with historical backfill.

The most differentiated features — the ones no consumer tool currently provides — are derivatives leverage transparency, liquidity stress analysis, counterparty aggregation, fee waiver monitoring, and historical drift detection. These are institutional-grade analytics built from publicly available SEC data.
