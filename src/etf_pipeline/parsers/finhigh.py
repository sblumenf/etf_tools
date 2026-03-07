"""Parse Financial Highlights tables from N-CSR filings.

Financial Highlights section in N-CSR filings contains per-share operating data,
distribution data, and fund ratios that are NOT available in XBRL. This parser
extracts that data using positional HTML table parsing.
"""

import gc
import logging
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from bs4 import BeautifulSoup
from edgar import Company
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from etf_pipeline.db import get_engine
from etf_pipeline.models import (
    ETF,
    PerShareDistribution,
    PerShareOperating,
    PerShareRatios,
)
from etf_pipeline.parser_utils import (
    build_filing_date_filter,
    clear_and_log_cache,
    ensure_date,
    parse_date,
    parse_decimal,
    resolve_cik_list,
    run_parser_loop,
    update_processing_log,
    upsert_record,
)
from etf_pipeline.sgml import parse_series_class_info

logger = logging.getLogger(__name__)


def _find_table_context(table) -> tuple[Optional[str], Optional[str]]:
    """Extract fund name and share class name from HTML context around table.

    In real N-CSR filings, the structure is:
      <div>Fund Name</div>
      <div>Financial Highlights</div>
      <table> first row has share class label like "Investor Shares"

    Args:
        table: BeautifulSoup table element

    Returns:
        Tuple of (fund_name, class_name) or (None, None) if not found
    """
    # Extract share class from table's first row (first cell text)
    class_name = None
    first_row = table.find('tr')
    if first_row:
        first_cell = first_row.find(['td', 'th'])
        if first_cell:
            cell_text = first_cell.get_text().strip()
            if cell_text and 'shares' in cell_text.lower() and len(cell_text) < 100:
                class_name = cell_text

    # Walk backward from table to find fund name
    fund_name = None
    prev_element = table.find_previous(['h1', 'h2', 'h3', 'h4', 'h5', 'p', 'div'])
    for _ in range(30):
        if not prev_element:
            break
        text = prev_element.get_text().strip()

        # Skip empty, very long, or "Financial Highlights" headings
        if text and len(text) < 200 and 'financial highlights' not in text.lower():
            text_lower = text.lower()
            if any(kw in text_lower for kw in ['fund', 'index', 'portfolio', 'trust']):
                fund_name = text
                break

        prev_element = prev_element.find_previous(['h1', 'h2', 'h3', 'h4', 'h5', 'p', 'div'])

    return (fund_name, class_name)


def parse_financial_highlights_table(html_table_str: str) -> dict:
    """Parse a Financial Highlights HTML table using positional extraction.

    The Financial Highlights table follows a regulated structure (Form N-1A Item 13).
    Regardless of label variations, the ROW ORDER is fixed:
    1. NAV, Beginning of Period
    2. Investment Operations (NII, Gains, Total)
    3. Equalization (optional, some issuers only)
    4. Distributions (from NII, Cap Gains, ROC, Total)
    5. NAV, End of Period
    6. Total Return
    7. Ratios/Supplemental Data (expense ratio, turnover, net assets)

    Args:
        html_table_str: HTML string containing a single Financial Highlights table

    Returns:
        dict with keys:
        - operating: dict with nav_beginning, net_investment_income, etc.
        - distribution: dict with dist_net_investment_income, etc.
        - ratios: dict with expense_ratio, portfolio_turnover, net_assets_end
        - fiscal_year_end: date object
        - math_validated: bool
    """
    soup = BeautifulSoup(html_table_str, "lxml")
    table = soup.find("table")

    if not table:
        raise ValueError("No table found in HTML")

    # Extract all rows
    rows = table.find_all("tr")

    if len(rows) < 10:
        raise ValueError(f"Too few rows ({len(rows)}) for a Financial Highlights table")

    # Result structure
    result = {
        "operating": {},
        "distribution": {},
        "ratios": {},
        "fiscal_year_end": None,
        "math_validated": False,
    }

    # Helper to extract first data value from a row (typically column 1, most recent year)
    def get_value(row_idx: Optional[int], col_idx: int = 1) -> Optional[str]:
        """Get cell value from row at specified column index."""
        if row_idx is None or row_idx >= len(rows):
            return None
        row = rows[row_idx]
        cells = row.find_all(['td', 'th'])
        if col_idx >= len(cells):
            return None
        return cells[col_idx].get_text().strip()

    def get_row_label(row_idx: int) -> str:
        """Get the label (first cell) of a row."""
        if row_idx >= len(rows):
            return ""
        row = rows[row_idx]
        cells = row.find_all(['td', 'th'])
        if not cells:
            return ""
        return cells[0].get_text().strip().lower()

    # Extract fiscal_year_end from column headers
    # Patterns: "Year Ended August 31," with years in next row, or "12/31/2024" inline
    fiscal_year_end = None
    month_day_str = None  # e.g. "August 31" extracted from "Year Ended August 31,"

    for i in range(min(5, len(rows))):
        row_text = rows[i].get_text()

        # Direct date pattern: "12/31/2024"
        date_match = re.search(r'(\d{1,2}/\d{1,2}/\d{4})', row_text)
        if date_match:
            fiscal_year_end = parse_date(date_match.group(1))
            break

        # "Year Ended <Month> <Day>," pattern — extract month/day, find year in next row
        if 'year ended' in row_text.lower():
            md_match = re.search(
                r'year ended\s+(\w+ \d{1,2})', row_text, re.IGNORECASE
            )
            if md_match:
                month_day_str = md_match.group(1)  # e.g. "August 31"

                # Look for year in next row
                if i + 1 < len(rows):
                    next_cells = rows[i + 1].find_all(['td', 'th'])
                    for cell in next_cells:
                        year_match = re.search(r'\d{4}', cell.get_text().strip())
                        if year_match:
                            fiscal_year_end = parse_date(
                                f"{month_day_str}, {year_match.group(0)}"
                            )
                            break
                if fiscal_year_end:
                    break

    # Find key rows by looking for distinctive text patterns
    # Strategy: scan through rows and identify sections
    row_map = {}
    for i, row in enumerate(rows):
        label = get_row_label(i)

        # NAV rows (must check 'end' before general NAV to avoid overwriting)
        if 'net asset value' in label and 'end' in label:
            row_map['nav_end'] = i
        elif 'net asset value' in label and 'beginning' in label:
            row_map['nav_beginning'] = i

        # Investment operations (exclude ratio rows)
        elif 'net investment income' in label and 'ratio' not in label and 'average' not in label and 'dividend' not in label:
            row_map['net_investment_income'] = i
        elif 'realized' in label and 'unrealized' in label and 'gain' in label:
            row_map['net_realized_unrealized_gain'] = i
        elif 'total from investment' in label or ('total' in label and 'investment operations' in label):
            row_map['total_from_operations'] = i

        # Equalization (optional)
        elif 'equalization' in label and 'net' not in label:
            row_map['equalization'] = i

        # Distributions (must check specific patterns first)
        elif ('dividend' in label or 'distribution' in label) and 'net investment income' in label:
            row_map['dist_net_investment_income'] = i
        elif 'distribution' in label and 'realized' in label and ('capital gain' in label or 'capital gains' in label):
            row_map['dist_realized_gains'] = i
        elif 'return of capital' in label:
            row_map['dist_return_of_capital'] = i
        elif 'total distribution' in label:
            row_map['dist_total'] = i

        # Total return (but not if it's in a ratio row)
        elif 'total return' in label and 'ratio' not in label:
            row_map['total_return'] = i

        # Ratios (be specific to avoid matching other rows)
        elif 'net assets' in label and 'end' in label and 'million' in label:
            row_map['net_assets_end'] = i
        elif 'ratio' in label and 'expense' in label:
            row_map['expense_ratio'] = i
        elif 'portfolio turnover' in label:
            row_map['portfolio_turnover'] = i

    # Extract values using mapped rows
    result['operating']['nav_beginning'] = parse_decimal(get_value(row_map.get('nav_beginning')))
    result['operating']['net_investment_income'] = parse_decimal(get_value(row_map.get('net_investment_income')))
    result['operating']['net_realized_unrealized_gain'] = parse_decimal(get_value(row_map.get('net_realized_unrealized_gain')))
    result['operating']['total_from_operations'] = parse_decimal(get_value(row_map.get('total_from_operations')))
    result['operating']['equalization'] = parse_decimal(get_value(row_map.get('equalization')))
    result['operating']['nav_end'] = parse_decimal(get_value(row_map.get('nav_end')))
    result['operating']['total_return'] = parse_decimal(get_value(row_map.get('total_return')), pct=True)

    result['distribution']['dist_net_investment_income'] = parse_decimal(get_value(row_map.get('dist_net_investment_income')))
    result['distribution']['dist_realized_gains'] = parse_decimal(get_value(row_map.get('dist_realized_gains')))
    result['distribution']['dist_return_of_capital'] = parse_decimal(get_value(row_map.get('dist_return_of_capital')))
    result['distribution']['dist_total'] = parse_decimal(get_value(row_map.get('dist_total')))

    result['ratios']['expense_ratio'] = parse_decimal(get_value(row_map.get('expense_ratio')), pct=True)
    result['ratios']['portfolio_turnover'] = parse_decimal(get_value(row_map.get('portfolio_turnover')), pct=True)

    # Net assets may be in millions, need to convert
    net_assets_text = get_value(row_map.get('net_assets_end'))
    if net_assets_text:
        net_assets_value = parse_decimal(net_assets_text)
        if net_assets_value and 'million' in get_row_label(row_map.get('net_assets_end', 0)).lower():
            net_assets_value = net_assets_value * 1_000_000
        result['ratios']['net_assets_end'] = net_assets_value
    else:
        result['ratios']['net_assets_end'] = None

    result['fiscal_year_end'] = fiscal_year_end

    # Math validation
    # Formula: NAV_end = NAV_beginning + total_from_operations - abs(dist_total) + equalization
    nav_beg = result['operating']['nav_beginning']
    total_ops = result['operating']['total_from_operations']
    dist_total = result['distribution']['dist_total']
    nav_end = result['operating']['nav_end']
    equalization = result['operating']['equalization'] or Decimal('0')

    if all(v is not None for v in [nav_beg, total_ops, dist_total, nav_end]):
        # Distribution total is typically reported as negative, so we use it directly
        expected_nav_end = nav_beg + total_ops + dist_total + equalization
        discrepancy = abs(expected_nav_end - nav_end)
        result['math_validated'] = discrepancy <= Decimal('0.01')

        if not result['math_validated']:
            logger.warning(
                f"Math validation failed: expected NAV end {expected_nav_end}, "
                f"got {nav_end}, discrepancy {discrepancy}"
            )
    else:
        result['math_validated'] = False
        logger.debug("Math validation skipped: missing required values")

    return result


def _make_process_cik_finhigh(from_date: Optional[str] = None, to_date: Optional[str] = None):
    """Return a per-CIK processor for the parser loop."""
    date_filter = build_filing_date_filter(from_date, to_date)
    backfill_mode = date_filter is not None

    def _process_cik_finhigh(session: Session, cik: str) -> bool:
        MAX_FILINGS = 10  # Limit scan to 10 most recent filings per CIK

        try:
            # Build class_id -> ETF mapping from database first
            stmt = select(ETF).where(ETF.cik == cik)
            etfs = session.execute(stmt).scalars().all()

            class_id_to_etf = {}
            for etf in etfs:
                if etf.class_id:
                    class_id_to_etf[etf.class_id] = etf

            if not class_id_to_etf:
                logger.warning(f"CIK {cik}: No ETFs with class_id found in database")
                return True

            needed_class_ids = set(class_id_to_etf.keys())
            # Track (class_id, fiscal_year_end) pairs already processed
            satisfied = set()
            latest_filing_date = None

            company = Company(cik)
            kwargs = {"form": "N-CSR"}
            if date_filter is not None:
                kwargs["filing_date"] = date_filter
            filings = company.get_filings(**kwargs)

            if not filings or (hasattr(filings, "empty") and filings.empty):
                logger.info(f"CIK {cik}: No N-CSR filings found")
                return True

            processed_etfs = 0
            skipped_etfs = 0

            num_filings = len(filings) if backfill_mode else min(len(filings), MAX_FILINGS)
            consecutive_misses = 0
            for filing_idx in range(num_filings):
                # In normal mode, stop early if all class_ids have been satisfied
                if not backfill_mode and not (needed_class_ids - {cid for cid, _ in satisfied}):
                    logger.debug(
                        f"CIK {cik}: All class_ids satisfied after {filing_idx} filing(s)"
                    )
                    break

                filing = filings[filing_idx]
                filing_date = ensure_date(filing.filing_date)
                satisfied_before_this_filing = len(satisfied)

                # Track the latest filing date
                if latest_filing_date is None or filing_date > latest_filing_date:
                    latest_filing_date = filing_date

                # Get HTML from filing
                try:
                    html = filing.html()
                    if not html:
                        logger.warning(
                            f"CIK {cik}: Filing {filing_idx} has no HTML, skipping"
                        )
                        continue
                except Exception as e:
                    logger.warning(
                        f"CIK {cik}: Filing {filing_idx} HTML fetch failed: {e}"
                    )
                    continue

                # Parse SGML header to build series/class mapping
                try:
                    header_text = filing.header.text if hasattr(filing, 'header') and hasattr(filing.header, 'text') else ""
                    series_class_mapping = parse_series_class_info(header_text)
                except Exception as e:
                    logger.warning(f"CIK {cik}: Failed to parse SGML header: {e}")
                    series_class_mapping = {'classes': {}, 'tickers': {}}

                if not re.search(r'financial\s+highlights', html, re.IGNORECASE):
                    logger.debug(f"CIK {cik}: Filing {filing_idx} has no Financial Highlights content, skipping")
                    # In normal mode only, use consecutive_misses early exit
                    if not backfill_mode:
                        consecutive_misses += 1
                        if consecutive_misses >= 2:
                            logger.debug(f"CIK {cik}: No new matches in 2 consecutive filings, stopping early")
                            del html
                            gc.collect()
                            break
                    continue

                # Parse HTML to find Financial Highlights tables
                soup = BeautifulSoup(html, 'lxml')

                # Strategy: Find tables that contain Financial Highlights data
                # by looking for characteristic row patterns (Net Asset Value, etc.)
                tables = soup.find_all('table')
                fh_tables = []

                for table in tables:
                    table_text = table.get_text().lower()
                    if 'net asset value' in table_text and 'investment operations' in table_text:
                        fh_tables.append(table)

                logger.info(f"CIK {cik}: Found {len(fh_tables)} Financial Highlights tables in filing {filing_idx}")

                # Collect context and serialized HTML for each table while soup is alive,
                # then release the large DOM tree before entering the inner parsing loop.
                table_tuples = []
                for table in fh_tables:
                    fund_name, class_name = _find_table_context(table)
                    table_tuples.append((fund_name, class_name, str(table)))

                del soup
                del html
                del fh_tables
                gc.collect()

                for fund_name, class_name, table_html_str in table_tuples:
                    try:
                        if not fund_name or not class_name:
                            logger.debug(
                                f"CIK {cik}: Could not extract context from table (fund={fund_name}, class={class_name})"
                            )
                            continue

                        # Match to class_id using SGML mapping
                        matched_class_id = None

                        # Normalize for matching
                        fund_name_norm = fund_name.lower()
                        class_name_norm = class_name.lower()

                        # Try substring match (bidirectional: HTML may truncate or SGML may prefix)
                        for (series_norm, class_norm), class_id in series_class_mapping['classes'].items():
                            series_match = series_norm in fund_name_norm or fund_name_norm in series_norm
                            class_match = class_norm in class_name_norm or class_name_norm in class_norm
                            if series_match and class_match:
                                matched_class_id = class_id
                                break

                        # If no match by name, try ticker fallback (extract from context)
                        if not matched_class_id:
                            for ticker, class_id in series_class_mapping['tickers'].items():
                                if ticker.lower() in fund_name_norm or ticker.lower() in class_name_norm:
                                    matched_class_id = class_id
                                    break

                        if not matched_class_id:
                            logger.debug(
                                f"CIK {cik}: Could not match table to class_id (fund='{fund_name}', class='{class_name}')"
                            )
                            continue

                        # Look up ETF by class_id
                        matched_etf = class_id_to_etf.get(matched_class_id)
                        if not matched_etf:
                            logger.debug(
                                f"CIK {cik}: class_id {matched_class_id} not found in database"
                            )
                            continue

                        logger.info(
                            f"CIK {cik}: Matched table to {matched_etf.ticker} (fund='{fund_name}', class='{class_name}', class_id={matched_class_id})"
                        )

                        # Parse the table
                        table_data = parse_financial_highlights_table(table_html_str)

                        if not table_data.get('fiscal_year_end'):
                            logger.warning(
                                f"CIK {cik}: Could not extract fiscal_year_end from table for {matched_etf.ticker}"
                            )
                            skipped_etfs += 1
                            continue

                        # Ensure fiscal_year_end is a date object
                        if isinstance(table_data['fiscal_year_end'], datetime):
                            table_data['fiscal_year_end'] = table_data['fiscal_year_end'].date()

                        # Check if already processed
                        if (matched_etf.class_id, table_data['fiscal_year_end']) in satisfied:
                            logger.debug(
                                f"CIK {cik}: Already processed {matched_etf.ticker} FY {table_data['fiscal_year_end']}"
                            )
                            continue

                        # Upsert PerShareOperating
                        filter_keys = {
                            'etf_id': matched_etf.id,
                            'fiscal_year_end': table_data['fiscal_year_end'],
                            'filing_date': filing_date,
                        }
                        upsert_record(
                            session, PerShareOperating, filter_keys,
                            {**table_data['operating'], 'math_validated': table_data.get('math_validated', False)},
                        )

                        # Upsert PerShareDistribution
                        upsert_record(session, PerShareDistribution, filter_keys, table_data['distribution'])

                        # Upsert PerShareRatios
                        upsert_record(session, PerShareRatios, filter_keys, table_data['ratios'])

                        session.flush()

                        # Track as satisfied
                        satisfied.add((matched_etf.class_id, table_data['fiscal_year_end']))
                        processed_etfs += 1

                        logger.info(
                            f"CIK {cik}: Processed {matched_etf.ticker} FY {table_data['fiscal_year_end']}, "
                            f"math_validated={table_data['math_validated']}"
                        )

                    except Exception as e:
                        logger.warning(f"CIK {cik}: Failed to parse table: {e}")
                        skipped_etfs += 1
                        continue

                # In normal mode, track consecutive misses for early exit
                if not backfill_mode:
                    if len(satisfied) > satisfied_before_this_filing:
                        consecutive_misses = 0
                    else:
                        consecutive_misses += 1
                        if consecutive_misses >= 2:
                            logger.debug(f"CIK {cik}: No new matches in 2 consecutive filings, stopping early")
                            del table_tuples
                            gc.collect()
                            break

                del table_tuples
                gc.collect()
                session.commit()
                session.expunge_all()
                class_id_to_etf = {
                    cid: session.merge(etf_obj)
                    for cid, etf_obj in class_id_to_etf.items()
                }

                if backfill_mode:
                    update_processing_log(session, cik, "finhigh", filing_date)
                    session.commit()
                    logger.info(f"CIK {cik}: Processed filing {filing_idx + 1}/{num_filings} (filing_date={filing_date})")
                else:
                    logger.debug(f"CIK {cik}: Committed data for filing {filing_idx}")

            # Update processing log after successful processing (normal mode)
            if not backfill_mode and latest_filing_date is not None:
                latest_filing_date = ensure_date(latest_filing_date)
                update_processing_log(session, cik, "finhigh", latest_filing_date)

            session.commit()
            logger.info(f"CIK {cik}: Processed {processed_etfs} ETF(s), skipped {skipped_etfs}")
            return True

        except Exception as e:
            logger.error(f"CIK {cik}: Error processing Financial Highlights: {e}")
            session.rollback()
            return False

    return _process_cik_finhigh


# Module-level alias for backward compatibility (used by tests)
_process_cik_finhigh = _make_process_cik_finhigh()


def parse_finhigh(
    cik: Optional[str] = None,
    ciks: Optional[list[str]] = None,
    limit: Optional[int] = None,
    clear_cache: bool = True,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> None:
    """Parse Financial Highlights from N-CSR filings.

    Args:
        cik: Optional CIK to process (all others will be skipped)
        ciks: Optional list of CIKs to process (overrides cik param)
        limit: Optional limit on number of CIKs to process
        clear_cache: Whether to clear edgartools HTTP cache after processing
        from_date: Optional start date for backfill (YYYY-MM-DD). Requires to_date.
        to_date: Optional end date for backfill (YYYY-MM-DD). Requires from_date.
    """
    engine = get_engine()
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        cik_list = resolve_cik_list(session, cik, ciks, limit)

    if not cik_list:
        return

    process_fn = _make_process_cik_finhigh(from_date, to_date)
    run_parser_loop(cik_list, session_factory, process_fn, "finhigh")

    if clear_cache:
        clear_and_log_cache()
