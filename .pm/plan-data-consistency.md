## PM Plan: Fix ETF Data Consistency Issues

- [ ] Step 1: Add `series_id` column to `FundSnapshot` model, update unique constraint
- [ ] Step 2: Generate Alembic migration
- [ ] Step 3: Update `_extract_fund_snapshot()` to accept and store `series_id`
- [ ] Step 4: Update `_process_etf()` to pass `series_id`
- [ ] Step 5: Update `get_fund_snapshot()` to filter by `series_id`
- [ ] Step 6: Add 9 missing codes to `ASSET_CATEGORY_MAP`
- [ ] Step 7: Update xray route to pass `etf.series_id`
- [ ] Step 8: Run Alembic migration
- [ ] Step 9: Write/update tests
- [ ] Step 10: Final review
