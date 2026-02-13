#!/usr/bin/env python3
"""
Exploratory script to understand the EDGAR company facts API schema for N-CSR parsing.
Makes a single API call to inspect DataFrame structure.
"""

import os
import json
from edgartools import Company

# Set EDGAR identity
os.environ["EDGAR_IDENTITY"] = "Serge Blumenfeld test@example.com"

# Use SPY trust (State Street S&P 500 SPDR) - CIK 0000884394
# This is a small single-fund trust, perfect for exploration
cik = "0000884394"

print(f"Fetching company facts for CIK {cik}...")
company = Company(cik)
facts = company.get_facts()

if facts is None:
    print("No XBRL facts found for this CIK")
    exit(1)

# Convert to pandas DataFrame
df = facts.to_pandas()

print(f"\n=== DataFrame Shape ===")
print(f"Rows: {len(df)}, Columns: {len(df.columns)}")

print(f"\n=== Column Names ===")
print(df.columns.tolist())

print(f"\n=== First 5 Rows ===")
print(df.head())

# Filter for OEF taxonomy concepts
oef_concepts = ["AvgAnnlRtrPct", "PortfolioTurnoverRate", "ExpenseRatioPct"]
df_oef = df[df['name'].isin(oef_concepts)]

print(f"\n=== OEF Concepts Found ===")
print(f"Total OEF rows: {len(df_oef)}")
print(f"Concepts: {df_oef['name'].unique()}")

if len(df_oef) > 0:
    print(f"\n=== Sample OEF Facts (first 10) ===")
    print(df_oef.head(10))

    # Check for dimension columns
    print(f"\n=== Checking for Dimension Columns ===")
    potential_dims = [col for col in df_oef.columns if 'axis' in col.lower() or 'member' in col.lower() or 'dimension' in col.lower() or 'entity' in col.lower()]
    print(f"Potential dimension columns: {potential_dims}")

    # Show unique values for dimension-like columns
    for col in potential_dims:
        unique_vals = df_oef[col].dropna().unique()
        if len(unique_vals) > 0:
            print(f"\n{col}: {unique_vals[:10]}")  # Show first 10 unique values

    # Check for date columns (for period mapping)
    date_cols = [col for col in df_oef.columns if 'date' in col.lower() or 'start' in col.lower() or 'end' in col.lower() or 'period' in col.lower()]
    print(f"\n=== Date/Period Columns ===")
    print(f"Date-related columns: {date_cols}")

    # Save sample to JSON for tests
    sample_data = df_oef.head(20).to_dict(orient='records')
    output_path = '/home/sergeblumenfeld/etf_tools/tests/fixtures/company_facts_sample.json'
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Also save the full column schema
    schema_info = {
        'columns': df.columns.tolist(),
        'dtypes': {col: str(dtype) for col, dtype in df.dtypes.items()},
        'sample_oef_facts': sample_data
    }

    with open(output_path, 'w') as f:
        json.dump(schema_info, f, indent=2, default=str)

    print(f"\n=== Saved schema and sample data to {output_path} ===")
else:
    print("\nNo OEF concepts found. Trying alternative taxonomy...")
    # Try other potential names
    df_sample = df[df['taxonomy'].str.contains('oef', case=False, na=False)]
    print(f"Facts with 'oef' in taxonomy: {len(df_sample)}")
    if len(df_sample) > 0:
        print(df_sample.head(10))

print("\n=== Exploration Complete ===")
