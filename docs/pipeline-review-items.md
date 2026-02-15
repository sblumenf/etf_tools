# Pipeline Review Items

Issues identified from `run-all --limit 3` on 2026-02-14.

**STATUS: All items reviewed and resolved** (2026-02-14)

- Items 1–2: Technical debt removed
- Items 3–7: Working as designed, no action needed

## 1. expense_example table — technical debt candidate

The prospectus parser populates this table (hypothetical costs on $10k over 1/3/5/10 years), but nothing in the codebase ever reads it back. Write-only. Decide whether to keep or remove.

**Resolution:** RESOLVED — Table removed. It was write-only (never read by any consumer). Model, parser code, tests, and schema docs all cleaned up.

## 2. last_fetched field — misleading and incomplete

Only set by the NPORT parser (`nport.py:242`) when holdings are inserted. Two problems found:

- **CIK 0000052848**: NPORT parser never ran at all (no processing_log entry). Other parsers ran fine. Investigate why `run_all` skipped NPORT for this CIK.
- **CIK 0000105544**: NPORT parser ran but returned early (no filings or empty series map). `last_fetched` stayed NULL.
- **Field name is misleading**: Implies "last time any data was fetched" but only tracks NPORT. Either rename to `nport_last_fetched`, have all parsers set it, or remove it in favor of `processing_log`.

**Resolution:** RESOLVED — Field removed from ETF model. Orchestration already uses `ProcessingLog` table exclusively (since commit 14b1bd1). The write in nport.py, its test, and schema docs all cleaned up.

## 3. distribution_12b1 field — informational only

No action needed. This is the SEC Rule 12b-1 annual distribution/marketing fee (up to 1% of assets). Stored as a decimal (e.g., 0.0025 = 0.25%). Varies by share class.

**Resolution:** NO ACTION — Working as designed. SEC Rule 12b-1 fee, varies by share class.

## 4. net_sales = 0 for CIK 0000105544 — verify against raw filing

The parser extracts `<netSales>` directly from 24F-2NT XML (not computed). SEC formula floors to 0 when redemptions exceed sales. Likely legitimate, but verify by checking the raw filing XML for this CIK.

**Resolution:** NO ACTION — Correct per SEC formula. Net sales floors to 0 when redemptions exceed sales.

## 5. per_share_operating table — informational only

No action needed. Positive/negative values represent income vs. losses per share during the fiscal year. The `equalization` field is always NULL because ETFs don't use this mutual-fund accounting adjustment.

**Resolution:** NO ACTION — Working as designed. Equalization is always NULL for ETFs.

## 6. performance table — benchmark fields all NULL

Parser is fully implemented and tested. The benchmark extraction looks for `BroadBasedIndexAxis` dimension in N-CSR XBRL data. All NULLs means the specific filings for these 3 CIKs either lack benchmark XBRL data or present it in an unmatched format. Investigate by checking a raw N-CSR filing.

**Resolution:** RESOLVED — Parser bug fixed. Benchmark XBRL facts have NULL ClassAxis, so the per-class filter was excluding them. Benchmark extraction now runs before the per-class loop.

## 7. shareholder_fee table — empty, zero records

Parser is implemented and tested. Table is empty because ETFs rarely charge shareholder fees (front loads, back loads, redemption fees). These are mutual fund concepts. Expected behavior for an ETF-only dataset.

**Resolution:** RESOLVED — Table removed. ETFs don't charge shareholder fees (mutual fund concept). This is an ETF-only pipeline, so the table, parser code, tests, and schema docs were all removed.
