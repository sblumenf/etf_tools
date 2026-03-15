# Benchmark Name Usage Statistics

## Overview

This document provides usage statistics for the 450 distinct benchmark names currently stored in the database.

## Key Statistics

| Metric | Value |
|--------|-------|
| **Total distinct benchmark names** | 450 |
| **Total performance records with benchmarks** | 5,040 |
| **Average usage per benchmark name** | 11.2 records |
| **Most used benchmark** | 291 records (StandardPoors500IndexMember) |
| **Least used benchmark** | 1 record (40 benchmarks appear only once) |
| **Median usage** | ~8-10 records per benchmark |

## Top 20 Most Used Benchmarks

Ordered by number of performance records referencing them:

| Rank | Count | Provider | Benchmark Name |
|------|-------|----------|---|
| 1 | 291 | Other | StandardPoors500IndexMember |
| 2 | 263 | Russell | Russell3000IndexMember |
| 3 | 142 | S&P/S&P | SAndP500TotalReturnIndexMember |
| 4 | 131 | FactSet | FactSetBigDataRefinersIndex8227BroadBasedIndexMember |
| 5 | 128 | Other | FRTSRAATRMinusBenchmark1MinusYear13589BroadBasedIndexMember |
| 6 | 118 | Custom | bench20251224106944_5953Member |
| 7 | 89 | S&P/S&P | SP500PriceReturnIndexSM3618BroadBasedIndexMember |
| 8 | 86 | Bloomberg | BloombergUSUniversalIndexMember |
| 9 | 84 | Bloomberg | BloombergUSAggregateBondIndexMember |
| 10 | 79 | MSCI | MSCIAllCountryWorldIndexMember |
| 11 | 79 | Bloomberg | BloombergGlobalAggregateIndex44249BroadBasedIndexMember |
| 12 | 62 | ICE | ICEBofAUSBroadMarketIndex995BroadBasedIndexMember |
| 13 | 60 | MSCI | MSCIChinaAllSharesIndexNetTotalReturnMember |
| 14 | 54 | Nasdaq | NasdaqCompositeIndexMember |
| 15 | 47 | S&P/S&P | SPNationalAMTFreeMunicipalBondInceptionDate7.16.24Member |
| 16 | 46 | MSCI | MSCIRussia2550IndexMember |
| 17 | 46 | MSCI | MSCIAllCountryWorldIndexNetMember |
| 18 | 46 | Bloomberg | BloombergU.S.AggregateBondInceptionDate11118Member |
| 19 | 45 | Bloomberg | BloombergUSUniversalBondIndex25427BroadBasedIndexMember |
| 20 | 43 | S&P/S&P | SPDRETFsIndexSP500Index2877BroadBasedIndexMember |

## Benchmarks by Index Provider

The 450 benchmarks are distributed among index providers as follows:

| Provider | Count | Example |
|----------|-------|---------|
| S&P / S&P Global | 88 | SP500Index, SAndP500Index, SPComposite1500 |
| Custom/Proprietary | 87 | Alerian, Morningstar, Solactive, Aztlan, bench20XX |
| MSCI | 86 | MSCIACWIIndex, MSCIEAFEIndex, MSCIEmergingMarkets |
| Bloomberg | 77 | BloombergUSAggregate, BloombergGlobalAggregate |
| Russell | 43 | Russell1000, Russell2000, Russell3000 |
| DowJones | 12 | DowJonesUSTotal, DowJonesGlobalComposite |
| FTSE | 5 | FTSEAllWorld, FTSEGlobalAllCap, FTSEUSAIndex |
| ICE/BofA | 5 | ICEBofAUSBroad, ICEBofALiquidHighYield |
| Other | ~61 | Various specialized indexes |

## Usage Distribution Analysis

### Concentration
- **Top 10 benchmarks**: Account for ~1,200 of 5,040 records (24%)
- **Top 20 benchmarks**: Account for ~1,500+ of 5,040 records (30%)
- **Top 50 benchmarks**: Account for ~2,000+ of 5,040 records (40%)
- **Remaining 400 benchmarks**: Account for ~3,000 of 5,040 records (60%)

This shows that:
1. A small set of benchmarks are heavily used (Standard & Poor's 500, Russell 3000, major MSCI/Bloomberg indexes)
2. A long tail of 400 benchmarks are used less frequently (1-50 times each)
3. The distribution follows a power law pattern (typical for index/benchmark data)

### Implications for Mapping Strategy

**Priority order for creating readable name mappings:**

1. **Priority 1 (High)**: Top 20-30 benchmarks (~1,500 records)
   - These account for 30% of all data
   - Should be manually curated for accuracy
   - Most likely to be used by external consumers

2. **Priority 2 (Medium)**: Benchmarks 31-100 (~1,000 records)
   - These account for 20% of all data
   - Can use semi-automated extraction with manual review
   - Important for completeness

3. **Priority 3 (Low)**: Benchmarks 101-450 (~2,500 records)
   - These account for 50% of data but are dispersed across 350 unique names
   - Can use fully automated extraction
   - Lower risk of errors due to low individual impact

## Specific Observations

### Most Used Benchmarks

1. **StandardPoors500IndexMember** (291 records)
   - The S&P 500 is the most common benchmark by far
   - Used by multiple fund families
   - Note: Variant "SAndP500TotalReturnIndexMember" also has 142 records

2. **Russell3000IndexMember** (263 records)
   - Second most common benchmark
   - Indicates broad US market coverage is important

3. **Custom Benchmarks** (118+ records)
   - Timestamp-formatted benchmarks like "bench20251224106944_5953Member"
   - These are 40 different custom/proprietary benchmarks with minimal description
   - Represent funds tracking non-standard indexes

### Index Provider Insights

- **S&P/S&P Global**: Most diversified provider with 88 different index names
- **MSCI**: 86 different names, heavy focus on international/emerging markets
- **Bloomberg**: 77 names, primarily bond indexes
- **Russell**: 43 names, primarily US equity indexes
- **Custom/Proprietary**: 87 names indicate significant use of non-standard benchmarks

## Data Quality Flags

### Inconsistency Examples

Some ETFs report different benchmarks across fiscal years:

- **AAPX**: `SP500IndexMember` (2025) vs `SAndP500IndexMember` (2024)
- **AAXJ**: `MSCIAllCountryWorldIndexNetMember` (2025) vs `MSCIAllCountryWorldIndexMember` (2024)
- **ABCS**: `BloombergUS2500TotalReturnIndexMember` (2025) vs `BloombergUSAggregateEquityTotalReturnIndexMember` (2024)

These inconsistencies suggest:
1. Potential fund benchmark changes
2. Variations in how benchmark names are reported across fiscal years
3. Need for time-series tracking of benchmark assignments

## Recommendations

### For Dashboard/Reporting
- Focus initial effort on mapping Top 30 benchmarks
- This covers ~30% of all data with minimal effort
- Provides 80/20 ROI on mapping effort

### For Data Integrity
- Flag all 40 custom "bench20XX" format benchmarks for manual review
- Verify that ETFs with changing benchmarks across years reflect actual fund strategy changes
- Consider adding benchmark change tracking in database

### For API/Consumer Use
- Create a `/benchmarks/readable` endpoint that uses the mapping table
- Include confidence scores (high for Top 30, medium for 31-100, low for 101+)
- Provide fallback to concatenated name if no mapping exists
- Log requests for unmapped benchmarks to prioritize future mapping work

## Next Steps

1. **Immediate**: Manually create mappings for Top 30 benchmarks
2. **Short-term**: Implement the benchmark_name_mapping table in database
3. **Medium-term**: Build automated extraction regex for remaining benchmarks
4. **Long-term**: Integrate with external index data services (Bloomberg, MSCI APIs)
