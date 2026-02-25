# PM Plan: Implement Simplifier Findings — COMPLETE

## Steps

- [x] Step 1: Fix reflection in `run_parser_for_cik()` [cli.py]
- [x] Step 2: Delete unused `PARSER_FORM_MAP` + update test [cli.py, tests/test_run_all.py]
- [x] Step 3: Consolidate `parse_decimal` / `parse_date` [parser_utils.py, finhigh.py, tests/test_finhigh.py]
- [x] Step 4: Simplify `extract_borrower_name()` stub [nport_xml.py]
- [x] Step 5: Refactor `get_stale_parsers()` redundant query [cli.py]
- [x] Step 6: Fix mixed logging in `load_etfs.py` [load_etfs.py, tests/test_load_etfs.py]
- [x] Step 7: Run tests + final review

## Result: 292/292 tests passing
