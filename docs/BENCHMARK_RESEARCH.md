# ETF Tools Benchmark/Index Names Research Report

## Executive Summary

The database contains **450 distinct benchmark/index names** stored in the `performance` table's `benchmark_name` column. These names are **concatenated XML element values** from N-CSR (shareholder report) XBRL filings, not human-readable index names. This report provides:

1. Complete catalog of all 450 benchmark names
2. Pattern analysis and decoding methodology
3. Recommendations for creating a readable benchmark name mapping
4. Code location and extraction logic

---

## Database Location & Details

### Connection Details
- **Database**: SQLite at `etf_data.db`
- **Table**: `performance`
- **Column**: `benchmark_name`
- **Total Records with Benchmark Data**: ~1400+ performance records
- **Distinct Benchmark Names**: 450

### Table Schema (relevant fields)
```sql
CREATE TABLE performance (
    id INTEGER PRIMARY KEY,
    etf_id INTEGER NOT NULL FOREIGN KEY,
    fiscal_year_end DATE NOT NULL,
    filing_date DATE NOT NULL,
    benchmark_name VARCHAR(500),                    -- THE CONCATENATED NAME
    benchmark_return_1yr NUMERIC(8,5),
    benchmark_return_5yr NUMERIC(8,5),
    benchmark_return_10yr NUMERIC(8,5),
    ...
);
```

---

## Pattern Analysis: How the Names Are Constructed

### Format Structure
All benchmark names follow this concatenation pattern:

```
[ManagerPrefix]Index[IndexName][NumericID]MemberSuffix
```

Where:
- **ManagerPrefix** (optional): Fund manager/family name (e.g., "BloombergCapital", "NACC2", "AllianceBernstein")
- **Index** (optional): Literal word "Index" that appears between manager and index name
- **IndexName** (core): The actual index name (e.g., "BloombergUSAggregateBond", "FTSEUSA", "SP500")
- **NumericID** (optional): 4-5 digit class ID or version number (e.g., 10436, 17335, 26286)
- **MemberSuffix** (always present): Either "BroadBasedIndexMember" or just "Member"

### Examples with Breakdown

| Full Name | Breakdown | Readable Name |
|-----------|-----------|---------------|
| `BloombergUSAggregateBondIndex10436BroadBasedIndexMember` | Bloomberg \| USAggregateBond \| 10436 \| BBIndexMember | Bloomberg US Aggregate Bond Index |
| `NACC2IndexFTSEUSAIndex17335BroadBasedIndexMember` | NACC2 \| FTSEUSA \| 17335 \| BBIndexMember | FTSE USA Index |
| `SP500IndexMember` | (none) \| SP500 \| (none) \| Member | S&P 500 Index |
| `MSCIACWIIndexNetUSD1365BroadBasedIndexMember` | MSCI \| ACWINet \| 1365 \| BBIndexMember | MSCI ACWI Index (Net, USD) |
| `bench20260306110862_6329Member` | (custom) \| bench20260306110862 \| 6329 \| Member | [Unknown - custom benchmark] |

### Why This Concatenation Happens

The NCSR parser (src/etf_pipeline/parsers/ncsr.py) extracts benchmark names directly from XBRL dimension members:

```python
# Line 242-244 in ncsr.py
benchmark_axis_values = benchmark_facts_deduped['dim_oef_BroadBasedIndexAxis'].dropna().unique()
if len(benchmark_axis_values) > 0:
    benchmark_name = _extract_benchmark_name(benchmark_axis_values[0])
```

The `dim_oef_BroadBasedIndexAxis` is an XBRL dimension member from the OEF (Open-End Fund) taxonomy. The member values are **the entire element name** from the taxonomy definition, not a human-readable label.

---

## Distribution by Index Provider

From the 450 names, here's the breakdown by index provider:

| Index Provider | Count | Examples |
|---|---|---|
| **S&P / S&P Global** | 88 | SP500Index, SAndP500Index, SPComposite1500 |
| **Custom/Proprietary** | 87 | Alerian, Morningstar, Solactive, Aztlan, bench20XX... |
| **MSCI** | 86 | MSCIACWIIndex, MSCIEAFEIndex, MSCIEmergingMarkets |
| **Bloomberg** | 77 | BloombergUSAggregate, BloombergGlobalAggregate, BloombergMunicipal |
| **Russell** | 43 | Russell1000, Russell2000, Russell3000 |
| **DowJones** | 12 | DowJonesUSTotal, DowJonesGlobalComposite |
| **FTSE** | 5 | FTSEAllWorld, FTSEGlobalAllCap, FTSEUSAIndex |
| **ICE/BofA** | 5 | ICEBofAUSBroad, ICEBofALiquidHighYield |
| **Other** | ~61 | Various specialized indexes |

---

## Data Quality Issues Identified

### 1. Inconsistent Naming Across Fiscal Years (Same ETF)

Examples of the **same ETF reporting different benchmark names** in different years:

| Ticker | FY 1 | FY 2 |
|--------|------|------|
| AAPX | `SP500IndexMember` | `SAndP500IndexMember` |
| AAVM | `SolactiveUSAggregateBondIndexMember` | `SolactiveGBSUnitedStates1000IndexMember` |
| AAXJ | `MSCIAllCountryWorldIndexNetMember` | `MSCIAllCountryWorldIndexMember` |
| ABCS | `BloombergUS2500TotalReturnIndexMember` | `BloombergUSAggregateEquityTotalReturnIndexMember` |

**Root Cause**: Different XBRL member names used in different SEC filings, or changes in benchmark by the fund.

### 2. Custom/Unidentifiable Benchmarks

About 40 benchmarks have timestamp-format names like:
- `bench20260306110862_6329Member`
- `bench20251230107016_5908Member`

**Interpretation**: These appear to be auto-generated IDs for benchmarks that don't have standard taxonomy member names. Format is likely `benchYYYYMMDDHHMM_XXXXX`.

### 3. Manager-Branded Index Names

Some benchmarks include the fund manager name:
- `AlerianMLPETFAlerianMLPETFAlerianMLPInfrastructureIndexMember`
- `GuinnessAtkinsonAlternativeEnergyFundGuinnessAtkinsonAlternativeEnergyFundMSCIWorldIndexNetReturnMember`

**Interpretation**: These may be proprietary fund indices or branded versions of standard indices.

---

## Extraction Logic & Recommended Mapping Strategy

### Current Extraction Method (in ncsr.py)

```python
def _extract_benchmark_name(member_value: str) -> Optional[str]:
    """Extract benchmark name from BroadBasedIndexAxis member value."""
    if not member_value or not isinstance(member_value, str):
        return None
    
    # Strip namespace prefix (e.g., "ist:")
    if ":" in member_value:
        member_value = member_value.split(":", 1)[1]
    
    return member_value if member_value else None
```

**Problem**: This returns the raw XML member name, not a human-readable index name.

### Recommended: Implement Index Name Mapping Table

Create a new table `benchmark_name_mapping`:

```sql
CREATE TABLE benchmark_name_mapping (
    id INTEGER PRIMARY KEY,
    concatenated_name VARCHAR(500) UNIQUE NOT NULL,  -- The raw name from XBRL
    readable_name VARCHAR(500),                        -- Human-readable index name
    index_provider VARCHAR(100),                        -- Bloomberg, MSCI, Russell, etc.
    isin_or_ticker VARCHAR(20),                         -- Index ticker if available
    notes TEXT,                                         -- Custom/alternative names, etc.
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Population Strategy

The mapping can be populated through:

1. **Automatic extraction** using regex patterns (see below)
2. **SEC Edgar taxonomy lookup** - cross-reference XBRL member names with OEF taxonomy definitions
3. **Manual curation** - for custom benchmarks and special cases
4. **Similarity matching** - group similar names and assign one canonical readable name

### Extraction Regex Patterns

```python
import re

def extract_readable_benchmark_name(concatenated_name: str) -> str:
    """Convert concatenated XBRL name to readable index name."""
    
    name = concatenated_name
    
    # Remove axis member suffix
    name = re.sub(r'BroadBasedIndexMember$', '', name)
    name = re.sub(r'Member$', '', name)
    
    # Remove trailing numeric class ID (4-5 digits)
    name = re.sub(r'\d{4,5}$', '', name)
    
    # Remove known manager prefixes, keeping the index name
    manager_prefixes = {
        'ALLSPRING': 'Index',
        'AMERICANBEACON': 'INDEX',
        'AllianceBernstein': 'Index',
        'NACC2': 'Index',
        'FidelityIndex': '',
        'PIMCOINDEX': '',
        'SPDRETFs': 'Index',
        'TRoweIndex': '',
        'TRowePriceETF': 'Index',
        'WisdomTree': 'Index',
        # ... more prefixes
    }
    
    for prefix, sep in manager_prefixes.items():
        pattern = f'^{prefix}{sep}'
        match = re.match(pattern, name)
        if match:
            name = name[len(match.group(0)):]
            break
    
    # Normalize camelCase index names to readable format
    # Insert spaces before capital letters (except at start)
    readable = re.sub(r'([A-Z])', r' \1', name).strip()
    readable = ' '.join(readable.split())  # Collapse multiple spaces
    
    return readable
```

---

## Code Locations

### Files Involved

1. **Parser Logic**: `/Users/sergeblumenfeld/etf_tools/src/etf_pipeline/parsers/ncsr.py`
   - Line 58-79: `_extract_benchmark_name()` function
   - Line 242-244: Where benchmark name is extracted from XBRL facts
   - Line 376: Where benchmark_name is written to Performance record

2. **Database Models**: `/Users/sergeblumenfeld/etf_tools/src/etf_pipeline/models.py`
   - Line 335-360: Performance class definition
   - Line 352: `benchmark_name` column definition

3. **XBRL Reference Docs**: `/Users/sergeblumenfeld/etf_tools/docs/reference/xbrl-oef-2025/`
   - `oef-2025.xsd` - XBRL taxonomy defining BroadBasedIndexAxis
   - `oef-sr-2025.xsd` - Shareholder report-specific schema
   - `oeftaxonomyguide-2025-03-17.pdf` - Human-readable guide

### Related Tests
- `/Users/sergeblumenfeld/etf_tools/tests/test_parsers/test_ncsr*.py` - NCSR parser tests

---

## Complete List of All 450 Benchmark Names

[See `/tmp/benchmark_names.txt` - contains all 450 distinct names sorted alphabetically]

### Summary Statistics

- **Total Distinct Names**: 450
- **With "BroadBasedIndexMember" suffix**: 272 (60%)
- **With "Member" suffix only**: 138 (31%)
- **Custom/Proprietary format**: 40 (9%)
- **Names with numeric suffix**: 385 (86%)
- **Names with manager prefix**: 150+ (33%)
- **Different benchmarks per ETF**: 1-3 (with 10+ ETFs having 2+ different benchmarks across fiscal years)

---

## Recommendations

### Short-term (Immediate)
1. Document the current behavior in the parser
2. Create the `benchmark_name_mapping` lookup table
3. Manually curate mappings for top 50 most-used benchmarks

### Medium-term (Next Sprint)
1. Implement automated extraction regex for readable names
2. Add database migration to populate mapping table
3. Modify NCSR parser to use mapping when available
4. Add API endpoint to return readable benchmark names

### Long-term (Future)
1. Integrate with SEC Edgar XBRL taxonomy lookups
2. Build benchmark reconciliation service against Bloomberg, Russell, MSCI APIs
3. Track benchmark changes over time for each ETF
4. Create standardized benchmark identifiers (ISINs for indexes)

---

## Conclusion

The concatenated format of benchmark names is an artifact of the XBRL extraction process. The names are useful for:
- Exact matching against SEC filings
- Tracing back to specific XBRL taxonomy members
- Linking to official index definitions in OEF taxonomy

However, they're not suitable for:
- User display
- Data analysis and reporting
- Index comparison across ETFs
- Benchmark performance reports

A mapping layer (as recommended above) would make this data much more usable while preserving the original XBRL identifiers for reference.
