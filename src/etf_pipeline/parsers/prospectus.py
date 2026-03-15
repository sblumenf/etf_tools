"""Parse 485BPOS (prospectus) filings for fee/expense data using iXBRL.

This parser extracts data from the Risk/Return Summary section of prospectuses,
which uses the RR (Risk/Return) XBRL taxonomy. Data is embedded in HTML using
inline XBRL (iXBRL) tags.
"""

import gc
import logging
import re
import signal
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from bs4 import BeautifulSoup

from etf_pipeline.models import FeeExpense
from etf_pipeline.parser_utils import upsert_record

logger = logging.getLogger(__name__)

LOOKBACK_DAYS = 547  # 18-month window for prospectus filings


class HtmlFetchTimeout(Exception):
    pass


def _html_timeout_handler(signum, frame):
    raise HtmlFetchTimeout("filing.html() timed out")


def parse_contexts(soup: BeautifulSoup) -> dict[str, dict[str, Optional[str]]]:
    """Extract context map: context_id → {cik, series_id, class_id}.

    Contexts are defined in <xbrli:context> elements within <ix:resources>.
    Each context has a unique id and may contain:
    - CIK (from xbrli:identifier)
    - Series ID (from dei:LegalEntityAxis member, format: S000014796Member)
    - Class ID (from rr:ProspectusShareClassAxis member, format: C000014542Member)

    Args:
        soup: BeautifulSoup object of the iXBRL filing

    Returns:
        Dict mapping context_id to {cik, series_id, class_id}

    Example:
        {
            "AsOf2022-11-03_custom_S000014796Member_custom_C000014542Member": {
                "cik": "0001314612",
                "series_id": "S000014796",
                "class_id": "C000014542"
            }
        }
    """
    context_map = {}

    # Find all context elements (namespace-aware: xbrli:context)
    contexts = soup.find_all('xbrli:context')

    for context in contexts:
        context_id = context.get('id')
        if not context_id:
            continue

        # Extract CIK from xbrli:identifier
        cik = None
        identifier = context.find('xbrli:identifier')
        if identifier:
            cik_text = identifier.get_text().strip()
            # Normalize to 10 digits
            if cik_text:
                try:
                    cik = f"{int(cik_text):010d}"
                except ValueError:
                    logger.warning(f"Invalid CIK format: {cik_text}")

        # Extract series_id and class_id from segment dimensions
        series_id = None
        class_id = None

        segment = context.find('xbrli:segment')
        if segment:
            members = segment.find_all('xbrldi:explicitmember')
            for member in members:
                dimension = member.get('dimension', '')
                member_value = member.get_text().strip()

                # Extract series_id from LegalEntityAxis
                if 'legalentityaxis' in dimension.lower():
                    # Format: "rr01:S000014796Member" or "S000014796Member"
                    match = re.search(r'(S\d+)Member', member_value, re.IGNORECASE)
                    if match:
                        series_id = match.group(1).upper()

                # Extract class_id from ProspectusShareClassAxis (RR) or ClassAxis (OEF)
                elif 'prospectusshare' in dimension.lower() or 'classaxis' in dimension.lower():
                    # Format: "rr01:C000014542Member" or "C000014542Member"
                    match = re.search(r'(C\d+)Member', member_value, re.IGNORECASE)
                    if match:
                        class_id = match.group(1).upper()

        context_map[context_id] = {
            'cik': cik,
            'series_id': series_id,
            'class_id': class_id,
        }

    return context_map


def convert_numeric_value(
    element,
    scale: Optional[str] = None,
    format_attr: Optional[str] = None,
    sign: Optional[str] = None,
    negate_to_positive: bool = False,
) -> Optional[Decimal]:
    """Apply scale, format, and type conversions to numeric iXBRL element.

    Conversion rules:
    1. Scale factor -2: displayed 0.70 → Decimal('0.0070')
       Formula: value * 10^scale = 0.70 * 10^-2 = 0.007
    2. Format "ixt-sec:numwordsen" with text "None" → NULL
    3. Format "ixt:zerodash" with text "—" → Decimal('0')
    4. Sign "-": negate the value
    5. negate_to_positive=True: if value is negative, convert to positive

    Args:
        element: BeautifulSoup element (ix:nonFraction)
        scale: Scale attribute value (e.g., "-2")
        format_attr: Format attribute value (e.g., "ixt:numdotdecimal")
        sign: Sign attribute value (e.g., "-")
        negate_to_positive: If True, negate negative values to positive

    Returns:
        Decimal value or None
    """
    if element is None:
        return None

    text = element.get_text().strip()

    # Handle format transformations
    if format_attr:
        # ixt-sec:numwordsen "None" → NULL
        if 'numwordsen' in format_attr.lower():
            if text.lower() in ('none', 'n/a'):
                return None

        # ixt:zerodash "—" → Decimal('0')
        if 'zerodash' in format_attr.lower():
            if text in ('—', '-', '–', ''):
                return Decimal('0')

    # Parse numeric value
    # Remove common formatting: commas, percent signs, dollar signs
    clean_text = text.replace(',', '').replace('$', '').replace('%', '')

    if not clean_text or clean_text in ('—', '-', '–'):
        return None

    try:
        value = Decimal(clean_text)
    except (ValueError, InvalidOperation):
        logger.warning(f"Failed to parse numeric value: '{text}'")
        return None

    # Apply sign attribute
    if sign == '-':
        value = -value

    # Apply scale factor
    # Scale -2 means: displayed_value * 10^-2 = actual_value
    # Example: 0.70 with scale=-2 → 0.70 * 0.01 = 0.007
    if scale:
        try:
            scale_int = int(scale)
            value = value * (Decimal('10') ** scale_int)
        except ValueError:
            logger.warning(f"Invalid scale value: {scale}")

    # Optionally negate negative values to positive
    # (used for fee waivers and redemption fees which may be reported as negative)
    if negate_to_positive and value < 0:
        value = -value

    return value


def strip_html_to_text(html_fragment: str) -> str:
    """Strip HTML tags and return plain text.

    Args:
        html_fragment: HTML string (may contain <p>, <b>, <i>, etc.)

    Returns:
        Plain text with HTML tags removed
    """
    if not html_fragment:
        return ''

    soup = BeautifulSoup(html_fragment, 'lxml')
    text = soup.get_text()

    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def build_tag_index(soup: BeautifulSoup) -> dict[tuple[str, str], Any]:
    """Build an index of all iXBRL tags keyed by (tag_name, context_id).

    This pre-indexes all ix:nonfraction and ix:nonnumeric elements to enable
    O(1) lookups instead of O(n) scans for each field extraction.

    Args:
        soup: BeautifulSoup object of the filing

    Returns:
        Dict mapping (tag_name, context_id) to BeautifulSoup element
    """
    tag_index = {}

    # Find all iXBRL tags once
    for element in soup.find_all(['ix:nonfraction', 'ix:nonnumeric']):
        tag_name = element.get('name')
        context_id = element.get('contextref')

        if tag_name and context_id:
            # Use first occurrence if multiple tags with same (name, contextref)
            key = (tag_name, context_id)
            if key not in tag_index:
                tag_index[key] = element

    return tag_index


def extract_tag_value(
    soup_or_index,
    tag_name: str,
    context_id: str,
    negate_to_positive: bool = False,
) -> Optional[Decimal | str]:
    """Extract and convert value for a given RR tag and context.

    Args:
        soup_or_index: BeautifulSoup object OR tag index dict (for performance)
        tag_name: Full tag name (e.g., "rr:ManagementFeesOverAssets")
        context_id: Context ID to match
        negate_to_positive: If True, negate negative numeric values to positive

    Returns:
        Decimal for numeric tags, str for text tags, or None if not found
    """
    # Support both BeautifulSoup (legacy) and dict index (optimized)
    if isinstance(soup_or_index, dict):
        # O(1) lookup from pre-built index
        element = soup_or_index.get((tag_name, context_id))
        if not element:
            return None
    else:
        # O(n) scan for backward compatibility
        soup = soup_or_index
        elements = soup.find_all(
            lambda tag: tag.name in ('ix:nonfraction', 'ix:nonnumeric')
            and tag.get('name') == tag_name
            and tag.get('contextref') == context_id
        )

        if not elements:
            return None

        # Use the first matching element
        element = elements[0]

    # Handle numeric tags (ix:nonFraction)
    if element.name == 'ix:nonfraction':
        scale = element.get('scale')
        format_attr = element.get('format')
        sign = element.get('sign')

        return convert_numeric_value(
            element,
            scale=scale,
            format_attr=format_attr,
            sign=sign,
            negate_to_positive=negate_to_positive,
        )

    # Handle text tags (ix:nonNumeric)
    elif element.name == 'ix:nonnumeric':
        # Check if it's a text block (contains HTML)
        escape_attr = element.get('escape')
        if escape_attr == 'true':
            # Extract inner HTML and strip tags
            inner_html = element.decode_contents()
            return strip_html_to_text(inner_html)
        else:
            # Simple text value
            return element.get_text().strip()

    return None


def parse_date_tag(
    soup_or_index,
    tag_name: str,
    context_id: str,
) -> Optional[date]:
    """Extract and parse a date from an iXBRL tag.

    Args:
        soup_or_index: BeautifulSoup object OR tag index dict (for performance)
        tag_name: Full tag name (e.g., "dei:DocumentPeriodEndDate")
        context_id: Context ID to match

    Returns:
        date object or None
    """
    value = extract_tag_value(soup_or_index, tag_name, context_id)
    if not value or not isinstance(value, str):
        return None

    # Try parsing various date formats
    for fmt in ['%Y-%m-%d', '%m/%d/%Y', '%m/%d/%y']:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue

    try:
        from dateutil.parser import parse as dateutil_parse
        return dateutil_parse(value).date()
    except (ValueError, TypeError):
        pass

    logger.warning(f"Failed to parse date: '{value}'")
    return None


FEE_VALUE_FIELDS = [
    'management_fee', 'distribution_12b1', 'other_expenses',
    'total_expense_gross', 'fee_waiver', 'total_expense_net', 'acquired_fund_fees',
]


def _apply_fee_sanity_check(fee: dict, cik: str) -> None:
    """Correct fee values that appear to be display percentages (> 0.50 without scale)."""
    for field in FEE_VALUE_FIELDS:
        val = fee.get(field)
        if val is not None and val > Decimal('0.50'):
            logger.warning(f"CIK {cik}: Fee field {field}={val} exceeds 0.50, applying correction (÷100)")
            fee[field] = val * Decimal('0.01')


def _apply_net_expense_fallback(fee: dict) -> None:
    """Calculate total_expense_net from gross and waiver if not already set."""
    if fee.get('total_expense_net') is None and fee.get('total_expense_gross') is not None:
        waiver = fee.get('fee_waiver')
        if waiver is None or waiver == 0:
            fee['total_expense_net'] = fee['total_expense_gross']
        else:
            fee['total_expense_net'] = fee['total_expense_gross'] - waiver


def _parse_html_fee_value(cell_text: str) -> Optional[Decimal]:
    """Parse a fee percentage value from an HTML table cell.

    Handles:
    - "0.70%" → Decimal('0.0070')
    - "(0.10)%" → Decimal('0.0010')  (parentheses = negative, absolute taken)
    - "None" / "—" / "-" → None
    - "0.00" or "0.00%" → Decimal('0.0000')

    Unlike parse_decimal(pct=True) which only divides by 100 when "%" is present,
    this function ALWAYS divides by 100 because HTML fee tables display human-readable
    percentages with or without the "%" suffix. Always takes abs() of negatives
    (fee waivers in parentheses are stored as positive).
    """
    text = cell_text.strip()

    if not text or text.lower() in ('none', '—', '–', '-', 'n/a'):
        return None

    # Handle parentheses for negative values: (0.10)
    negative = False
    if text.startswith('(') and ')' in text:
        negative = True
        text = text.replace('(', '').replace(')', '')

    # Strip % and whitespace
    text = text.replace('%', '').replace(',', '').strip()

    if not text or text in ('—', '–', '-'):
        return None

    try:
        value = Decimal(text)
    except (ValueError, InvalidOperation):
        return None

    if negative:
        value = abs(value)

    # Convert display percentage to decimal: 0.70 → 0.0070
    return value * Decimal('0.01')


def _match_fee_row_label(label: str) -> Optional[str]:
    """Match a table row label to a fee field name.

    Returns field name or None if not matched.
    """
    normalized = label.lower().strip()
    normalized = re.sub(r'\s+', ' ', normalized)

    # Total net (must check BEFORE gross to avoid false positive on gross)
    if ('total annual fund operating expenses after' in normalized
            or 'net expenses' == normalized
            or 'total annual fund operating expenses after fee waiver' in normalized
            or 'total annual fund operating expenses after expense' in normalized):
        return 'total_expense_net'

    # Fee waiver (check before total gross)
    if ('fee waiver' in normalized or 'expense reimbursement' in normalized
            or 'fee waiver or reimbursement' in normalized
            or 'waiver and/or reimbursement' in normalized):
        # Exclude the "after fee waiver" total row (already caught above)
        if 'total annual' not in normalized:
            return 'fee_waiver'

    # Total gross (no "after" qualifier)
    if 'total annual fund operating expenses' in normalized and 'after' not in normalized:
        return 'total_expense_gross'

    # Management fee
    if 'management fee' in normalized:
        return 'management_fee'

    # 12b-1 fees (handle "and/or" vs "and")
    if '12b-1' in normalized or '12b1' in normalized:
        return 'distribution_12b1'

    # Other expenses
    if 'other expenses' in normalized or 'other operating expenses' in normalized:
        return 'acquired_fund_fees' if 'acquired fund' in normalized else 'other_expenses'

    # Acquired fund fees
    if 'acquired fund fees' in normalized:
        return 'acquired_fund_fees'

    return None


def _find_etf_for_html_table(
    table,
    class_id_to_etf: dict,
    series_id_to_etfs: dict,
    cik: str,
) -> Optional[Any]:
    """Find the ETF associated with an HTML fee table.

    Search strategy:
    1. Look backwards from the table for headings containing class/series IDs
    2. Look in the table header row itself
    3. If only one ETF exists for this CIK, use it

    Returns ETF object or None.
    """
    # Collect all preceding siblings and parent siblings to search for headings
    candidates = []

    # Walk up the DOM looking for headings before this table
    node = table
    for _ in range(10):  # limit search depth
        prev = node.find_previous_sibling()
        if prev:
            candidates.append(prev)
            node = prev
        else:
            parent = node.parent
            if parent:
                node = parent
                prev = node.find_previous_sibling()
                if prev:
                    candidates.append(prev)
            else:
                break

    # Search candidates for class/series IDs
    for candidate in candidates:
        text = candidate.get_text()
        # Look for class ID pattern C000XXXXX
        match = re.search(r'\b(C\d{6,})\b', text, re.IGNORECASE)
        if match:
            class_id = match.group(1).upper()
            etf = class_id_to_etf.get(class_id)
            if etf:
                return etf

        # Look for series ID pattern S000XXXXX
        match = re.search(r'\b(S\d{6,})\b', text, re.IGNORECASE)
        if match:
            series_id = match.group(1).upper()
            etf_list = series_id_to_etfs.get(series_id, [])
            if len(etf_list) == 1:
                return etf_list[0]

    # Look in table header row
    header = table.find('tr')
    if header:
        text = header.get_text()
        match = re.search(r'\b(C\d{6,})\b', text, re.IGNORECASE)
        if match:
            class_id = match.group(1).upper()
            etf = class_id_to_etf.get(class_id)
            if etf:
                return etf

    # Last resort: if only one ETF for this CIK, use it
    all_etfs = list(class_id_to_etf.values())
    if len(all_etfs) == 1:
        return all_etfs[0]

    # Multiple ETFs but no identifier found
    logger.warning(f"CIK {cik}: Could not identify ETF for HTML fee table")
    return None


def _extract_fees_from_html_table(
    soup: BeautifulSoup,
    session,
    class_id_to_etf: dict,
    series_id_to_etfs: dict,
    effective_date,
    filing_date,
    cik: str,
) -> set[str]:
    """Extract fee data from plain HTML fee tables (fallback when no iXBRL tags found).

    Returns the set of class_ids for which fee data was extracted.
    """
    # Find all tables that contain a row mentioning "Management Fees"
    fee_tables = []
    for table in soup.find_all('table'):
        first_cells = table.find_all('td', limit=15)
        if any(re.search(r'management fees?', c.get_text(), re.IGNORECASE) for c in first_cells):
            fee_tables.append(table)

    if not fee_tables:
        logger.debug(f"CIK {cik}: No HTML fee tables found")
        return set()

    processed_class_ids = set()

    for table in fee_tables:
        etf = _find_etf_for_html_table(table, class_id_to_etf, series_id_to_etfs, cik)
        if etf is None:
            continue

        # Extract fee data from table rows
        fee_fields: dict[str, Optional[Decimal]] = {}

        for row in table.find_all('tr'):
            cells = row.find_all(['td', 'th'])
            if not cells:
                continue

            label = cells[0].get_text().strip()
            field = _match_fee_row_label(label)
            if field is None:
                continue

            # Find the first non-label cell with a parseable percentage value
            value = None
            for cell in cells[1:]:
                cell_text = cell.get_text().strip()
                parsed = _parse_html_fee_value(cell_text)
                if parsed is not None or cell_text.lower() in ('none', '—', '–', '-'):
                    value = parsed
                    break

            fee_fields[field] = value

        if not fee_fields:
            continue

        _apply_fee_sanity_check(fee_fields, cik)
        _apply_net_expense_fallback(fee_fields)

        # Use filing_date as effective_date fallback
        eff_date = effective_date if effective_date is not None else filing_date

        if any(v is not None for v in fee_fields.values()):
            upsert_record(
                session,
                FeeExpense,
                filter_kwargs={
                    'etf_id': etf.id,
                    'effective_date': eff_date,
                    'filing_date': filing_date,
                },
                data_kwargs={k: v for k, v in fee_fields.items()},
            )
            logger.debug(f"CIK {cik}: HTML fallback upserted fee data for {etf.ticker}")
            if etf.class_id:
                processed_class_ids.add(etf.class_id)

    return processed_class_ids


def _make_process_cik_prospectus(from_date: Optional[str] = None, to_date: Optional[str] = None):
    """Factory that returns a _process_cik_prospectus function with optional date range for backfill."""
    from etf_pipeline.parser_utils import build_filing_date_filter
    backfill_mode = from_date is not None or to_date is not None
    filing_date_filter = build_filing_date_filter(from_date, to_date)

    def _process_cik_prospectus(session, cik: str) -> bool:
        from edgar import Company
        from etf_pipeline.models import ETF, FeeExpense
        from etf_pipeline.parser_utils import ensure_date, update_processing_log, upsert_record
        from sqlalchemy import select

        try:
            stmt = select(ETF).where(ETF.cik == cik)
            etfs = session.execute(stmt).scalars().all()

            class_id_to_etf = {}
            series_id_to_etfs = {}
            for etf in etfs:
                if etf.class_id:
                    class_id_to_etf[etf.class_id] = etf
                if etf.series_id:
                    if etf.series_id not in series_id_to_etfs:
                        series_id_to_etfs[etf.series_id] = []
                    series_id_to_etfs[etf.series_id].append(etf)

            if not class_id_to_etf:
                logger.warning(f"CIK {cik}: No ETFs with class_id found in database")
                return True

            needed_class_ids = set(class_id_to_etf.keys())
            satisfied = set()
            latest_filing_date = None

            company = Company(cik)
            get_filings_kwargs = {'form': '485BPOS'}
            if filing_date_filter is not None:
                get_filings_kwargs['filing_date'] = filing_date_filter
            filings = company.get_filings(**get_filings_kwargs)

            if not filings or (hasattr(filings, 'empty') and filings.empty):
                logger.info(f"CIK {cik}: No 485BPOS filings found")
                return True

            if not backfill_mode:
                most_recent_filing = filings[0]
                most_recent_date = most_recent_filing.filing_date if hasattr(most_recent_filing, 'filing_date') else date.today()
                cutoff_date = most_recent_date - timedelta(days=LOOKBACK_DAYS)
            else:
                cutoff_date = None

            total_filings = len(filings)

            for filing_idx in range(total_filings):
                # In normal mode: stop if all class_ids satisfied
                if not backfill_mode and not (needed_class_ids - satisfied):
                    logger.debug(f"CIK {cik}: All class_ids satisfied after {filing_idx} filing(s)")
                    break

                filing = filings[filing_idx]
                filing_date = ensure_date(filing.filing_date)

                if latest_filing_date is None or filing_date > latest_filing_date:
                    latest_filing_date = filing_date

                # In normal mode: stop if filing is outside 18-month window
                if not backfill_mode and cutoff_date and filing_date < cutoff_date:
                    logger.debug(f"CIK {cik}: Filing {filing_idx} outside 18-month window, stopping")
                    break

                if backfill_mode:
                    logger.info(f"CIK {cik}: Processing filing {filing_idx + 1}/{total_filings}")

                filing_url = filing.document.url if hasattr(filing, 'document') else None

                # Get HTML content
                try:
                    old_handler = signal.signal(signal.SIGALRM, _html_timeout_handler)
                    signal.alarm(120)  # 120 second timeout
                    html = filing.html()
                    signal.alarm(0)  # Cancel alarm
                    signal.signal(signal.SIGALRM, old_handler)  # Restore handler
                    if not html:
                        logger.warning(f"CIK {cik}: Filing {filing_idx} returned empty HTML, skipping")
                        continue
                except (HtmlFetchTimeout, Exception) as e:
                    signal.alarm(0)  # Cancel alarm on error
                    signal.signal(signal.SIGALRM, old_handler)
                    logger.warning(f"CIK {cik}: Filing {filing_idx} HTML fetch failed: {e}, skipping")
                    continue

                # Parse iXBRL
                soup = BeautifulSoup(html, 'lxml')

                # Extract contexts
                context_map = parse_contexts(soup)

                # Detect which namespace prefix is in use (rr: or oef:)
                rr_tags = soup.find_all(lambda tag: tag.get('name', '').startswith('rr:'))
                oef_tags = soup.find_all(lambda tag: tag.get('name', '').startswith('oef:'))

                if rr_tags:
                    tag_prefix = 'rr'
                elif oef_tags:
                    tag_prefix = 'oef'
                else:
                    logger.info(f"CIK {cik}: Filing {filing_idx} has no iXBRL tags, trying HTML table fallback")
                    del rr_tags, oef_tags
                    html_matched = _extract_fees_from_html_table(
                        soup, session, class_id_to_etf, series_id_to_etfs,
                        None, filing_date, cik
                    )
                    if html_matched:
                        logger.info(f"CIK {cik}: HTML fallback extracted fees for {len(html_matched)} ETF(s)")
                        satisfied.update(html_matched)
                    del soup, html
                    gc.collect()
                    continue

                del rr_tags, oef_tags

                # Build tag index for O(1) lookups (performance optimization)
                tag_index = build_tag_index(soup)

                # Find the base context (no dimensions) for effective_date
                base_context_id = None
                for ctx_id, ctx_data in context_map.items():
                    if ctx_data['series_id'] is None and ctx_data['class_id'] is None:
                        base_context_id = ctx_id
                        break

                # If no base context, try to find one with just CIK
                if not base_context_id and context_map:
                    base_context_id = list(context_map.keys())[0]

                # Extract effective_date from DocumentPeriodEndDate
                effective_date = None
                if base_context_id:
                    effective_date = parse_date_tag(tag_index, 'dei:DocumentPeriodEndDate', base_context_id)

                if not effective_date:
                    logger.warning(f"CIK {cik}: Filing {filing_idx} has no effective_date, using filing date")
                    effective_date = filing_date

                # Track which ETFs had data extracted in this filing
                etfs_with_data_this_filing = set()

                # Process each context that has a class_id
                for context_id, context_data in context_map.items():
                    class_id = context_data.get('class_id')
                    if not class_id:
                        continue

                    # In normal mode: skip if already satisfied (avoid overwriting with older data)
                    if not backfill_mode and class_id in satisfied:
                        logger.debug(f"CIK {cik}: class_id {class_id} already satisfied, skipping")
                        continue

                    # Match class_id to ETF
                    etf = class_id_to_etf.get(class_id)
                    if not etf:
                        logger.debug(f"CIK {cik}: class_id {class_id} not found in database, skipping")
                        continue

                    # Extract fee data
                    fee_data = {
                        'etf_id': etf.id,
                        'effective_date': effective_date,
                        'filing_date': filing_date,
                        'management_fee': extract_tag_value(tag_index, f'{tag_prefix}:ManagementFeesOverAssets', context_id),
                        'distribution_12b1': extract_tag_value(tag_index, f'{tag_prefix}:DistributionAndService12b1FeesOverAssets', context_id),
                        'other_expenses': extract_tag_value(tag_index, f'{tag_prefix}:OtherExpensesOverAssets', context_id),
                        'total_expense_gross': extract_tag_value(tag_index, f'{tag_prefix}:ExpensesOverAssets', context_id),
                        'fee_waiver': extract_tag_value(tag_index, f'{tag_prefix}:FeeWaiverOrReimbursementOverAssets', context_id, negate_to_positive=True),
                        'total_expense_net': extract_tag_value(tag_index, f'{tag_prefix}:NetExpensesOverAssets', context_id),
                        'acquired_fund_fees': extract_tag_value(tag_index, f'{tag_prefix}:AcquiredFundFeesAndExpensesOverAssets', context_id),
                        'fee_waiver_expiration_date': parse_date_tag(tag_index, f'{tag_prefix}:FeeWaiverOrReimbursementOverAssetsDateOfTermination', context_id),
                    }

                    _apply_fee_sanity_check(fee_data, cik)
                    _apply_net_expense_fallback(fee_data)

                    # Upsert FeeExpense (if any data present)
                    if any(fee_data[k] is not None for k in fee_data if k not in ('etf_id', 'effective_date', 'filing_date')):
                        upsert_record(
                            session,
                            FeeExpense,
                            filter_kwargs={
                                'etf_id': etf.id,
                                'effective_date': effective_date,
                                'filing_date': filing_date,
                            },
                            data_kwargs={k: v for k, v in fee_data.items() if k not in ('etf_id', 'effective_date', 'filing_date')},
                        )
                        logger.debug(f"CIK {cik}: Upserted fee data for {etf.ticker}")

                        etfs_with_data_this_filing.add(etf.id)

                    # Mark this class_id as satisfied (used in normal mode for early exit)
                    satisfied.add(class_id)

                # Extract narrative text (series-level, not class-level)
                all_nonnumeric = soup.find_all('ix:nonnumeric')

                # Build series_id -> context_id mapping (plain series contexts only, no class dimension)
                series_context_map = {}
                for ctx_id, ctx_data in context_map.items():
                    sid = ctx_data.get('series_id')
                    cid = ctx_data.get('class_id')
                    if sid and not cid and sid not in series_context_map:
                        series_context_map[sid] = ctx_id

                # For series with no series-only context, use a class-level context
                for ctx_id, ctx_data in context_map.items():
                    sid = ctx_data.get('series_id')
                    if sid and sid not in series_context_map:
                        series_context_map[sid] = ctx_id

                # Build reverse mapping: context_id -> series_id (for all contexts with a series)
                context_to_series = {}
                for ctx_id, ctx_data in context_map.items():
                    sid = ctx_data.get('series_id')
                    if sid:
                        context_to_series[ctx_id] = sid

                # Iterate known series from the database to avoid redundant RiskAxis-dimensioned iterations
                for series_id, etf_list in series_id_to_etfs.items():
                    context_id = series_context_map.get(series_id)

                    objective_text = None
                    strategy_text = None
                    if context_id:
                        objective_text = extract_tag_value(tag_index, f'{tag_prefix}:ObjectivePrimaryTextBlock', context_id)
                        strategy_text = extract_tag_value(tag_index, f'{tag_prefix}:StrategyNarrativeTextBlock', context_id)

                    risk_blocks = []

                    for element in all_nonnumeric:
                        tag_name = element.get('name', '')
                        element_context_ref = element.get('contextref', '')

                        if ('risktextblock' in tag_name.lower() or 'risknarrativetextblock' in tag_name.lower()) and context_to_series.get(element_context_ref) == series_id:
                            escape_attr = element.get('escape')
                            if escape_attr == 'true':
                                inner_html = element.decode_contents()
                                risk_text = strip_html_to_text(inner_html)
                            else:
                                risk_text = element.get_text().strip()

                            if risk_text:
                                risk_blocks.append(risk_text)

                    principal_risks = '\n\n'.join(risk_blocks) if risk_blocks else None

                    if not etf_list:
                        logger.debug(f"CIK {cik}: series_id {series_id} not found in database, skipping narrative text")
                        continue

                    for etf in etf_list:
                        if objective_text:
                            etf.objective_text = objective_text
                            logger.debug(f"CIK {cik}: Updated objective_text for {etf.ticker}")

                        if strategy_text:
                            etf.strategy_text = strategy_text
                            logger.debug(f"CIK {cik}: Updated strategy_text for {etf.ticker}")

                        if principal_risks:
                            etf.principal_risks = principal_risks
                            logger.debug(f"CIK {cik}: Updated principal_risks for {etf.ticker} ({len(risk_blocks)} risk blocks)")

                # Update filing_url for ETFs processed in this filing
                if filing_url:
                    for etf_id in etfs_with_data_this_filing:
                        etf = session.get(ETF, etf_id)
                        if etf:
                            etf.filing_url = filing_url
                            logger.debug(f"CIK {cik}: Updated filing_url for {etf.ticker}")

                del all_nonnumeric, soup, html
                gc.collect()
                session.commit()
                session.expunge_all()
                class_id_to_etf = {
                    cid: session.merge(etf_obj)
                    for cid, etf_obj in class_id_to_etf.items()
                }
                series_id_to_etfs = {
                    sid: [session.merge(etf_obj) for etf_obj in etf_list]
                    for sid, etf_list in series_id_to_etfs.items()
                }
                logger.debug(f"CIK {cik}: Committed data for filing {filing_idx}")

            # Update processing log after successful processing
            if latest_filing_date is not None:
                latest_filing_date = ensure_date(latest_filing_date)
                update_processing_log(session, cik, "prospectus", latest_filing_date)

            session.commit()
            logger.info(f"CIK {cik}: Successfully processed 485BPOS filing")
            return True

        except Exception as e:
            logger.error(f"CIK {cik}: Error processing 485BPOS filing: {e}")
            session.rollback()
            return False

    return _process_cik_prospectus


# Default (normal mode) processor — used by run_parser_loop and existing tests
_process_cik_prospectus = _make_process_cik_prospectus()


def parse_prospectus(
    cik: Optional[str] = None,
    ciks: Optional[list[str]] = None,
    limit: Optional[int] = None,
    clear_cache: bool = True,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> None:
    """Parse 485BPOS filings for fee schedules and strategy."""
    from etf_pipeline.db import get_engine
    from etf_pipeline.parser_utils import clear_and_log_cache, resolve_cik_list, run_parser_loop
    from sqlalchemy.orm import sessionmaker

    engine = get_engine()
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        cik_list = resolve_cik_list(session, cik=cik, ciks=ciks, limit=limit)
        if not cik_list:
            return

    process_fn = _make_process_cik_prospectus(from_date=from_date, to_date=to_date)
    run_parser_loop(cik_list, session_factory, process_fn, "prospectus")

    if clear_cache:
        clear_and_log_cache()
