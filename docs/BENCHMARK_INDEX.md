# Benchmark Name Research Index

This directory contains comprehensive research on the benchmark/index names currently stored in the etf_tools database.

## Quick Start

1. **Start here**: Read [BENCHMARK_RESEARCH_SUMMARY.txt](BENCHMARK_RESEARCH_SUMMARY.txt) (5 min read)
2. **For details**: Read [BENCHMARK_RESEARCH.md](BENCHMARK_RESEARCH.md) (15-20 min read)
3. **For stats**: Read [BENCHMARK_USAGE_STATS.md](BENCHMARK_USAGE_STATS.md) (10 min read)
4. **For complete list**: See [ALL_BENCHMARK_NAMES.txt](ALL_BENCHMARK_NAMES.txt) (reference only)

## Documents Overview

### BENCHMARK_RESEARCH_SUMMARY.txt
**Purpose**: Executive summary for quick understanding  
**Audience**: Project managers, developers starting the project  
**Contents**:
- Key findings (6 sections)
- What was created (3 documents)
- Recommended next actions
- Implementation notes for developers
- Research methodology

**Key Sections**:
- Database statistics
- Name format and examples
- Data source and extraction logic
- Index provider distribution
- Usage concentration analysis
- Data quality issues

### BENCHMARK_RESEARCH.md
**Purpose**: Comprehensive technical documentation  
**Audience**: Developers implementing solutions, data analysts  
**Contents**:
- Complete database schema
- Pattern analysis with detailed examples
- Distribution by index provider (8 providers)
- Data quality issues with specific examples
- Code location reference
- Extraction logic and recommended mapping strategy
- Python code samples for regex-based extraction
- Long-form recommendations

**Key Sections**:
- 450 benchmark names explained
- Format structure and examples
- Why this concatenation happens (XBRL explanation)
- Recommended mapping table schema (SQL)
- Extraction regex patterns with code
- File locations in the codebase

### BENCHMARK_USAGE_STATS.md
**Purpose**: Statistical analysis and usage patterns  
**Audience**: Data analysts, architects deciding priority  
**Contents**:
- Key statistics table
- Top 20 most used benchmarks
- Provider distribution
- Usage distribution analysis
- Concentration analysis (80/20 breakdown)
- Data quality flags
- Specific observations
- Recommendations by priority

**Key Sections**:
- Usage distribution (power law analysis)
- Concentration (which benchmarks matter most)
- Priority matrix for mapping (High/Medium/Low)
- Data quality inconsistencies
- Recommendations for different audiences

### ALL_BENCHMARK_NAMES.txt
**Purpose**: Complete reference list  
**Audience**: Anyone who needs to see all 450 names  
**Contents**: Alphabetically sorted list of all 450 distinct benchmark names

## Key Findings at a Glance

| Metric | Value |
|--------|-------|
| Total distinct benchmark names | 450 |
| Total performance records | 5,040 |
| Most used benchmark | StandardPoors500IndexMember (291 uses) |
| Top 10 benchmarks cover | 24% of all data |
| Top 30 benchmarks cover | ~30% of all data |
| Least used benchmarks | 1-10 uses (40 benchmarks appear only once) |

## Database Details

- **Table**: `performance` 
- **Column**: `benchmark_name`
- **Type**: VARCHAR(500)
- **File**: `src/etf_pipeline/models.py` line 352
- **Extract Function**: `src/etf_pipeline/parsers/ncsr.py` lines 58-79, 242-244

## Name Format

```
[ManagerPrefix]Index[IndexName][NumericID]MemberSuffix
```

**Examples**:
- `BloombergUSAggregateBondIndex10436BroadBasedIndexMember` → Bloomberg US Aggregate Bond Index
- `NACC2IndexFTSEUSAIndex17335BroadBasedIndexMember` → FTSE USA Index
- `SP500IndexMember` → S&P 500 Index

## Implementation Roadmap

### Phase 1: Foundation (Immediate)
1. Create `benchmark_name_mapping` lookup table
2. Manually curate mappings for Top 30 benchmarks (covers 30% of data)

### Phase 2: Expansion (Short-term)
1. Implement automated extraction regex
2. Add database migration
3. Create API endpoint for readable names

### Phase 3: Enhancement (Medium-term)
1. Benchmark reconciliation against external services
2. Benchmark change tracking over time
3. Standardized benchmark identifiers

## Related Code Locations

### Parser Implementation
- **File**: `src/etf_pipeline/parsers/ncsr.py`
- **Function**: `_extract_benchmark_name()` (line 58-79)
- **Extraction**: lines 242-244 (from XBRL dimension)
- **Storage**: line 376 (writes to Performance record)

### Database Model
- **File**: `src/etf_pipeline/models.py`
- **Class**: `Performance` (lines 335-360)
- **Column**: `benchmark_name` (line 352)

### XBRL References
- **Path**: `docs/reference/xbrl-oef-2025/`
- **Files**: 
  - `oef-2025.xsd` (taxonomy definition)
  - `oef-sr-2025.xsd` (shareholder report schema)
  - `oeftaxonomyguide-2025-03-17.pdf` (guide)

## Why This Research Matters

The benchmark names are currently stored in a **non-human-readable concatenated format** that:
- ✗ Cannot be displayed to users
- ✗ Makes data analysis difficult
- ✗ Prevents index comparison across ETFs
- ✗ Cannot be used in reports or dashboards

A mapping layer would:
- ✓ Enable readable names in APIs and UIs
- ✓ Support benchmark performance analysis
- ✓ Allow index-based fund comparison
- ✓ Make reports user-friendly
- ✓ Preserve XBRL identifiers for audit trail

## Statistics by Provider

| Provider | Count | Coverage |
|----------|-------|----------|
| S&P/S&P Global | 88 | Most diversified (88 variations) |
| Custom/Proprietary | 87 | Non-standard indexes |
| MSCI | 86 | International/emerging focus |
| Bloomberg | 77 | Bond index focus |
| Russell | 43 | US equity focus |
| Others | 69 | Specialized indexes |

## Data Quality Alerts

1. **Inconsistent naming across fiscal years**: Some ETFs report different benchmark names in different years
2. **Custom benchmarks**: 40 names use timestamp format (bench20XX series) with unknown origin
3. **Manager-branded names**: Some benchmarks include fund manager prefix, unclear if proprietary

## Questions & Answers

**Q: Why are the names concatenated?**  
A: They come directly from XBRL taxonomy member element names. The parser extracts them raw without conversion.

**Q: Can we change the format?**  
A: Yes, by creating a mapping table. This preserves audit trail while enabling readable names.

**Q: How many names need mapping?**  
A: Top 30 names cover ~30% of data (easy win). Full coverage requires mapping all 450.

**Q: What's the timeline?**  
A: Top 30 can be done in 1-2 hours. Full coverage with automation takes 1-2 days.

**Q: Is this a bug?**  
A: No, it's by design. The parser correctly extracts XBRL dimension members. A mapping layer is the solution.

## Contact & Support

For questions about this research:
- Review the appropriate document above
- Check the source code references
- See `BENCHMARK_RESEARCH.md` section on "Code Locations"

---

**Research Date**: 2026-03-15  
**Database Version**: Current (SQLite etf_data.db)  
**Status**: Complete & Documented
