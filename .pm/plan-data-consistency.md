## PM Plan: Fix ETF Data Consistency Issues — COMPLETE

- [x] Step 1: Add `series_id` column to `FundSnapshot` model, update unique constraint
- [x] Step 2: Generate Alembic migration
- [x] Step 3: Update `_extract_fund_snapshot()` to accept and store `series_id`
- [x] Step 4: Update `_process_etf()` to pass `series_id`
- [x] Step 5: Update `get_fund_snapshot()` to filter by `series_id`
- [x] Step 6: Add 9 missing codes to `ASSET_CATEGORY_MAP`
- [x] Step 7: Update xray route to pass `etf.series_id`
- [x] Step 8: Run Alembic migration
- [x] Step 9: Write/update tests (22 new + 2 updated, all 343 pass)
- [x] Step 10: Final review — PASS
