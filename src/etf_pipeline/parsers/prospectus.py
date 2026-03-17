"""Parse 485BPOS (prospectus) filings for fee/expense data using iXBRL.

This parser extracts data from the Risk/Return Summary section of prospectuses,
which uses the RR (Risk/Return) XBRL taxonomy. Data is embedded in HTML using
inline XBRL (iXBRL) tags.
"""

import concurrent.futures
import gc
import logging
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from bs4 import BeautifulSoup

from etf_pipeline.models import FeeExpense, Performance
from etf_pipeline.parser_utils import map_return_period, upsert_record

logger = logging.getLogger(__name__)

LOOKBACK_DAYS = 1095  # 3-year window for prospectus filings

# SEC tax-treatment axis members that are NOT benchmark indexes —
# these appear on the PerformanceMeasureAxis but describe return types, not benchmarks.
_NON_BENCHMARK_MEMBERS = {
    "AfterTaxesOnDistributionsMember",
    "AfterTaxesOnDistributionsAndSalesMember",
    "AftertaxondistributionsMember",
    "ReturnBeforeTaxesMember",
    "ReturnAfterTaxesonDistributionsMember",
    "BasedonNAVMember",
}



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

        # Extract series_id, class_id, and performance_measure from segment dimensions
        series_id = None
        class_id = None
        performance_measure = None

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
                elif 'prospectusshare' in dimension.lower() or ('classaxis' in dimension.lower() and 'performancemeasure' not in dimension.lower()):
                    # Format: "rr01:C000014542Member" or "C000014542Member"
                    match = re.search(r'(C\d+)Member', member_value, re.IGNORECASE)
                    if match:
                        class_id = match.group(1).upper()

                # Extract benchmark name from PerformanceMeasureAxis
                elif 'performancemeasureaxis' in dimension.lower():
                    # Strip namespace prefix, keep raw member name
                    if ':' in member_value:
                        performance_measure = member_value.split(':', 1)[1]
                    else:
                        performance_measure = member_value

        # Extract period start/end dates (needed for OEF period-based return mapping)
        period_start = None
        period_end = None
        period_el = context.find('xbrli:period')
        if period_el:
            start_el = period_el.find('xbrli:startdate')
            end_el = period_el.find('xbrli:enddate')
            instant_el = period_el.find('xbrli:instant')
            if start_el:
                period_start = start_el.get_text().strip() or None
            if end_el:
                period_end = end_el.get_text().strip() or None
            elif instant_el:
                period_end = instant_el.get_text().strip() or None

        context_map[context_id] = {
            'cik': cik,
            'series_id': series_id,
            'class_id': class_id,
            'performance_measure': performance_measure,
            'period_start': period_start,
            'period_end': period_end,
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


def build_tag_index(soup: BeautifulSoup) -> tuple[dict[tuple[str, str], Any], Optional[str]]:
    """Build an index of all iXBRL tags keyed by (tag_name, context_id).

    This pre-indexes all ix:nonfraction and ix:nonnumeric elements to enable
    O(1) lookups instead of O(n) scans for each field extraction.

    Also detects the namespace prefix ('rr' or 'oef') as a side effect of
    the iteration, avoiding two additional full-document scans.

    Args:
        soup: BeautifulSoup object of the filing

    Returns:
        Tuple of (tag_index, detected_prefix) where detected_prefix is 'rr',
        'oef', or None if neither prefix is found.
    """
    tag_index = {}
    detected_prefix = None

    # Find all iXBRL tags once
    for element in soup.find_all(['ix:nonfraction', 'ix:nonnumeric']):
        tag_name = element.get('name')
        context_id = element.get('contextref')

        if tag_name and context_id:
            # Use first occurrence if multiple tags with same (name, contextref)
            key = (tag_name, context_id)
            if key not in tag_index:
                tag_index[key] = element

        # Detect prefix as a side effect (first match wins)
        if detected_prefix is None and tag_name:
            if tag_name.startswith('rr:'):
                detected_prefix = 'rr'
            elif tag_name.startswith('oef:'):
                detected_prefix = 'oef'

    return tag_index, detected_prefix


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


_FEE_COMPONENT_FIELDS = {'management_fee', 'distribution_12b1', 'other_expenses', 'acquired_fund_fees', 'fee_waiver'}
_FEE_TOTAL_FIELDS = {'total_expense_gross', 'total_expense_net'}


def _apply_fee_sanity_check(fee: dict, cik: str) -> None:
    """Correct fee values that appear to be display percentages (> threshold without scale).

    Component fields use a 0.10 threshold; total fields use 0.50 to allow
    legitimate fund-of-funds totals (e.g. 12-14%) to pass through unchanged.
    """
    for field in FEE_VALUE_FIELDS:
        val = fee.get(field)
        if val is None:
            continue
        threshold = Decimal('0.10') if field in _FEE_COMPONENT_FIELDS else Decimal('0.50')
        if val > threshold:
            logger.warning(f"CIK {cik}: Fee field {field}={val} exceeds {threshold}, applying correction (÷100)")
            fee[field] = val * Decimal('0.01')


def _apply_net_expense_fallback(fee: dict) -> None:
    """Calculate total_expense_net from gross and waiver if not already set."""
    if fee.get('total_expense_net') is None and fee.get('total_expense_gross') is not None:
        waiver = fee.get('fee_waiver')
        if waiver is None or waiver == 0:
            fee['total_expense_net'] = fee['total_expense_gross']
        else:
            fee['total_expense_net'] = fee['total_expense_gross'] - waiver


def _parse_html_pct_value(cell_text: str, take_abs: bool = False) -> Optional[Decimal]:
    """Parse a percentage value from an HTML table cell.

    Always divides by 100 (display percentages with or without the "%" suffix).
    Handles parenthetical negatives, bare dashes, and N/A.

    If take_abs=True, returns the absolute value (used for fee waivers stored as positive).
    """
    text = cell_text.strip()

    if not text or text.lower() in ('none', '—', '–', '-', 'n/a'):
        return None

    negative = False
    if text.startswith('(') and ')' in text:
        negative = True
        text = text.replace('(', '').replace(')', '')

    text = text.replace('%', '').replace(',', '').strip()

    if not text or text in ('—', '–', '-'):
        return None

    try:
        value = Decimal(text)
    except (ValueError, InvalidOperation):
        return None

    if negative:
        value = -value

    if take_abs:
        value = abs(value)

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
                parsed = _parse_html_pct_value(cell_text, take_abs=True)
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



_RETURN_LABEL_PATTERNS = [
    (re.compile(r'since\s+inception', re.IGNORECASE), 'return_since_inception'),
    (re.compile(r'\b10[\s-]*year', re.IGNORECASE), 'return_10yr'),
    (re.compile(r'\b5[\s-]*year', re.IGNORECASE), 'return_5yr'),
    (re.compile(r'\b1[\s-]*year', re.IGNORECASE), 'return_1yr'),
]

_BENCHMARK_LABEL_PATTERNS = re.compile(
    r'index|benchmark|s&p|russell|msci|bloomberg|barclays|dow jones|nasdaq|djia',
    re.IGNORECASE,
)

# Known UIT fund labels to skip (not benchmark rows)
_UIT_FUND_LABEL_PATTERNS = re.compile(
    r'(spdr|spider|trust|the\s+fund|fund\s+return)',
    re.IGNORECASE,
)


def _extract_performance_from_html_table(
    soup: BeautifulSoup,
    filing_date,
) -> Optional[dict]:
    """Extract performance data from plain HTML average annual returns table.

    Scans all tables for an "Average Annual" header, then extracts return values
    from rows labelled "1 Year", "5 Year(s)", "10 Year(s)", "Since Inception".
    Also extracts the first benchmark row found.

    Returns a dict with keys from: return_1yr, return_5yr, return_10yr,
    return_since_inception, benchmark_name, benchmark_return_1yr,
    benchmark_return_5yr, benchmark_return_10yr.
    Returns None if no performance table is found.
    """
    # Detect performance tables by looking for:
    # 1. "Average Annual" in a heading immediately preceding the table, OR
    # 2. Period labels ("1 Year", "5 Year", "10 Year") inside the table itself
    _period_label_re = re.compile(r'\b(?:1|5|10)\s*[-–]?\s*year', re.IGNORECASE)

    perf_tables = []
    for table in soup.find_all('table'):
        table_text = table.get_text()

        # Check period labels inside the table
        if _period_label_re.search(table_text):
            perf_tables.append(table)
            continue

        # Check preceding elements (headings) for "Average Annual"
        prev = table.find_previous_sibling()
        if prev and re.search(r'average\s+annual', prev.get_text(), re.IGNORECASE):
            perf_tables.append(table)

    if not perf_tables:
        return None

    # Use the first matching table
    table = perf_tables[0]

    result: dict = {}
    benchmark_name: Optional[str] = None
    benchmark_returns: dict = {}

    # Two table layouts exist:
    # VERTICAL: first column = period label ("1 Year"), other columns = fund/benchmark values
    #   Header row may have column names ("Fund", "S&P 500 Index")
    # HORIZONTAL: first column = entity name (fund or benchmark), other columns = period values
    #   Header row has period names ("1 Year", "5 Years", "10 Years")

    # For vertical layout: detect column header → entity name mapping
    # col_idx → entity label (fund or benchmark name)
    vertical_col_headers: dict[int, str] = {}

    # For horizontal layout: detect column header → field name mapping
    col_to_field: dict[int, str] = {}  # column index → return field name

    header_parsed = False
    horizontal_fund_row_seen = False  # first data row in horizontal layout = fund

    rows = table.find_all('tr')
    for row in rows:
        cells = row.find_all(['td', 'th'])
        if not cells:
            continue

        label = cells[0].get_text().strip()
        label_lower = label.lower()

        # Bug 3c: if this row signals the Average Annual section, reset so we re-parse headers
        row_text = row.get_text()
        if re.search(r'average\s+annual', row_text, re.IGNORECASE):
            header_parsed = False
            horizontal_fund_row_seen = False

        # Try to detect a header row with period labels in non-first cells (horizontal layout)
        if not header_parsed:
            header_found = False
            col_pos = 0  # track actual column position accounting for colspan
            for cell in cells:
                colspan = int(cell.get('colspan', 1) or 1)
                cell_text = cell.get_text().strip()
                if col_pos > 0:  # skip first column (entity label column)
                    for pat, field in _RETURN_LABEL_PATTERNS:
                        if pat.search(cell_text):
                            col_to_field[col_pos] = field
                            header_found = True
                            break
                col_pos += colspan
            if header_found:
                header_parsed = True
                continue

        # Check if this is a vertical layout header row (non-period labels in columns)
        # e.g., <th>Period</th><th>Fund</th><th>S&P 500 Index</th>
        # Detect: first cell looks like a header label (not a period), and remaining cells
        # are entity/column names (not percentage values)
        if not header_parsed and not col_to_field and not vertical_col_headers:
            non_period_header = True
            for pat, _ in _RETURN_LABEL_PATTERNS:
                if pat.search(label):
                    non_period_header = False
                    break
            if non_period_header and not re.search(r'average\s+annual', label_lower, re.IGNORECASE):
                # Check that other cells contain text (not percentages) — column headers
                col_labels_found = False
                for i, cell in enumerate(cells[1:], start=1):
                    cell_text = cell.get_text().strip()
                    # If cell has text but not a parseable percentage, treat as column header
                    if cell_text and not re.search(r'^\s*[-–]?\s*\d+', cell_text):
                        vertical_col_headers[i] = cell_text
                        col_labels_found = True
                    elif cell_text and _parse_html_pct_value(cell_text) is None:
                        vertical_col_headers[i] = cell_text
                        col_labels_found = True
                if col_labels_found:
                    continue  # skip this header row

        # Check if this is a row with a period label in the first column (vertical layout)
        matched_field = None
        for pat, field in _RETURN_LABEL_PATTERNS:
            if pat.search(label):
                matched_field = field
                break

        if matched_field:
            if vertical_col_headers:
                # Extract values for each known column
                # First non-benchmark column → fund return; benchmark column → benchmark return
                fund_set = False
                for col_idx, col_label in vertical_col_headers.items():
                    if col_idx >= len(cells):
                        continue
                    val = _parse_html_pct_value(cells[col_idx].get_text())
                    is_bm = bool(_BENCHMARK_LABEL_PATTERNS.search(col_label))
                    if not is_bm:
                        if not fund_set and val is not None:
                            result[matched_field] = val
                            fund_set = True
                    else:
                        if benchmark_name is None:
                            benchmark_name = col_label
                        if col_label == benchmark_name and val is not None:
                            bfield = matched_field.replace('return_', 'benchmark_return_')
                            if 'since' not in bfield:
                                benchmark_returns[bfield] = val
            else:
                # No column headers detected — first non-empty value cell is the fund return
                for cell in cells[1:]:
                    val = _parse_html_pct_value(cell.get_text())
                    if val is not None:
                        result[matched_field] = val
                        break
            continue

        # If we have a column header map, this is a data row (horizontal layout)
        if col_to_field and label and not re.search(r'average\s+annual', label_lower, re.IGNORECASE):
            # First data row is always treated as the fund row (regardless of name)
            # Subsequent rows that look like benchmarks are captured as benchmark
            if not horizontal_fund_row_seen:
                fund_row_values_found = False
                for col_idx, field in col_to_field.items():
                    if col_idx < len(cells) and result.get(field) is None:
                        val = _parse_html_pct_value(cells[col_idx].get_text())
                        if val is not None:
                            result[field] = val
                            fund_row_values_found = True
                if fund_row_values_found:
                    horizontal_fund_row_seen = True
            elif benchmark_name is None and _BENCHMARK_LABEL_PATTERNS.search(label):
                benchmark_name = label
                for col_idx, field in col_to_field.items():
                    if col_idx < len(cells):
                        val = _parse_html_pct_value(cells[col_idx].get_text())
                        if val is not None:
                            bfield = field.replace('return_', 'benchmark_return_')
                            if bfield.startswith('benchmark_return_') and 'since' not in bfield:
                                benchmark_returns[bfield] = val

    if benchmark_name:
        result['benchmark_name'] = benchmark_name
        result.update(benchmark_returns)

    if not any(result.get(k) is not None for k in (
        'return_1yr', 'return_5yr', 'return_10yr', 'return_since_inception'
    )):
        return None

    return result


_UIT_PERF_FIELDS = (
    'return_1yr', 'return_5yr', 'return_10yr',
    'return_since_inception', 'benchmark_name',
    'benchmark_return_1yr', 'benchmark_return_5yr',
    'benchmark_return_10yr',
)


def _write_uit_html_performance(session, cik, etf, soup, filing_date, satisfied):
    """Extract HTML performance for a single UIT ETF and upsert to DB."""
    from etf_pipeline.benchmark_labels import resolve_benchmark_label
    perf_html = _extract_performance_from_html_table(soup, filing_date)
    if not perf_html:
        logger.warning(f"CIK {cik}: No HTML performance table found for UIT ETF(s)")
        return
    try:
        if perf_html.get('benchmark_name'):
            resolve_benchmark_label(
                session,
                perf_html['benchmark_name'],
                xbrl_obj=None,
                cik=cik,
                filing_date=filing_date,
            )
        upsert_record(
            session,
            Performance,
            filter_kwargs={
                'etf_id': etf.id,
                'fiscal_year_end': filing_date,
                'filing_date': filing_date,
            },
            data_kwargs={k: perf_html[k] for k in _UIT_PERF_FIELDS if k in perf_html},
        )
        logger.info(f"CIK {cik}: HTML performance fallback upserted for UIT {etf.ticker}")
        satisfied.add(f"__UIT__{etf.id}")
    except Exception as e:
        logger.warning(f"CIK {cik}: HTML performance fallback failed for UIT: {e}")



def _extract_performance_data(
    tag_index: dict,
    context_map: dict,
    class_id: str,
    context_id: str,
    tag_prefix: str,
) -> dict:
    """Extract performance data for a given class context.

    For RR taxonomy (older filings): looks up fixed-period AverageAnnualReturn tags
    directly on the fund context and benchmark contexts (same class_id + PerformanceMeasureAxis).

    For OEF taxonomy (newer filings): looks up oef:AvgAnnlRtrPct across all contexts
    for this class_id, using context period start/end dates (captured in context_map)
    to map each value to the correct return period field.

    Returns dict with any subset of: return_1yr, return_5yr, return_10yr,
    return_since_inception, benchmark_name, benchmark_return_1yr, benchmark_return_5yr,
    benchmark_return_10yr, portfolio_turnover.
    """
    from etf_pipeline.parser_utils import parse_date as _parse_date

    result: dict = {}

    if tag_prefix == 'rr':
        # Fund returns: use the class-level context (no PerformanceMeasureAxis)
        result['return_1yr'] = extract_tag_value(tag_index, 'rr:AverageAnnualReturnYear01', context_id)
        result['return_5yr'] = extract_tag_value(tag_index, 'rr:AverageAnnualReturnYear05', context_id)
        result['return_10yr'] = extract_tag_value(tag_index, 'rr:AverageAnnualReturnYear10', context_id)
        result['return_since_inception'] = extract_tag_value(tag_index, 'rr:AverageAnnualReturnSinceInception', context_id)
        result['portfolio_turnover'] = extract_tag_value(tag_index, 'rr:PortfolioTurnoverRate', context_id)

        # Benchmark returns: find contexts with same class_id AND PerformanceMeasureAxis
        benchmark_name = None
        benchmark_returns: dict = {}

        for ctx_id, ctx_data in context_map.items():
            if ctx_data.get('class_id') != class_id:
                continue
            pm = ctx_data.get('performance_measure')
            if not pm:
                continue

            if benchmark_name is None and pm not in _NON_BENCHMARK_MEMBERS:
                benchmark_name = pm

            # Only collect returns for the first benchmark encountered
            if pm == benchmark_name:
                val_1yr = extract_tag_value(tag_index, 'rr:AverageAnnualReturnYear01', ctx_id)
                val_5yr = extract_tag_value(tag_index, 'rr:AverageAnnualReturnYear05', ctx_id)
                val_10yr = extract_tag_value(tag_index, 'rr:AverageAnnualReturnYear10', ctx_id)

                if val_1yr is not None:
                    benchmark_returns['benchmark_return_1yr'] = val_1yr
                if val_5yr is not None:
                    benchmark_returns['benchmark_return_5yr'] = val_5yr
                if val_10yr is not None:
                    benchmark_returns['benchmark_return_10yr'] = val_10yr

        if benchmark_name is not None:
            result['benchmark_name'] = benchmark_name
            result.update(benchmark_returns)

    elif tag_prefix == 'oef':
        # OEF fund returns: oef:AvgAnnlRtrPct and oef:PortfolioTurnoverRate are duration-typed;
        # each distinct context carries a different period. Scan all fund contexts for this class.
        benchmark_name = None
        benchmark_returns: dict = {}

        for ctx_id, ctx_data in context_map.items():
            if ctx_data.get('class_id') != class_id:
                continue

            pm = ctx_data.get('performance_measure')
            period_start_str = ctx_data.get('period_start')
            period_end_str = ctx_data.get('period_end')

            # Check for PortfolioTurnoverRate on any fund context (no benchmark axis)
            if pm is None and result.get('portfolio_turnover') is None:
                turnover = extract_tag_value(tag_index, 'oef:PortfolioTurnoverRate', ctx_id)
                if turnover is not None:
                    result['portfolio_turnover'] = turnover

            # Check for AvgAnnlRtrPct
            val = extract_tag_value(tag_index, 'oef:AvgAnnlRtrPct', ctx_id)
            if val is None:
                continue

            if pm is None:
                # Fund return — map via period dates
                if period_start_str and period_end_str:
                    ps = _parse_date(period_start_str)
                    pe = _parse_date(period_end_str)
                    field = map_return_period(ps, pe)
                    if field:
                        result[field] = val
                    else:
                        logger.debug(f"OEF prospectus: could not map period {period_start_str}..{period_end_str} to return field, skipping")
                else:
                    logger.debug(f"OEF prospectus: oef:AvgAnnlRtrPct in context {ctx_id} has no period info, skipping")
            else:
                # Benchmark return — only use the first benchmark
                if benchmark_name is None and pm not in _NON_BENCHMARK_MEMBERS:
                    benchmark_name = pm
                if pm == benchmark_name:
                    if period_start_str and period_end_str:
                        ps = _parse_date(period_start_str)
                        pe = _parse_date(period_end_str)
                        field = map_return_period(ps, pe)
                        if field and field in ('return_1yr', 'return_5yr', 'return_10yr'):
                            bfield = field.replace('return_', 'benchmark_return_')
                            benchmark_returns[bfield] = val

        if benchmark_name is not None:
            result['benchmark_name'] = benchmark_name
            result.update(benchmark_returns)

    return result


def _make_process_cik_prospectus(from_date: Optional[str] = None, to_date: Optional[str] = None):
    """Factory that returns a _process_cik_prospectus function with optional date range for backfill."""
    from etf_pipeline.parser_utils import build_filing_date_filter
    backfill_mode = from_date is not None and to_date is not None
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

            if not class_id_to_etf and not etfs:
                logger.warning(f"CIK {cik}: No ETFs found in database")
                return True

            # UITs have class_id=None — collect them separately for HTML fallback
            uit_etfs = [e for e in etfs if not e.class_id]

            if not class_id_to_etf and not uit_etfs:
                logger.warning(f"CIK {cik}: No ETFs with class_id found in database")
                return True

            needed_class_ids = set(class_id_to_etf.keys())
            # Add sentinels for UIT ETFs so the early-exit check doesn't skip them
            uit_sentinel_ids = {f"__UIT__{e.id}" for e in uit_etfs}
            needed_class_ids.update(uit_sentinel_ids)
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
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                        future = executor.submit(filing.html)
                        html = future.result(timeout=120)
                    if not html:
                        logger.warning(f"CIK {cik}: Filing {filing_idx} returned empty HTML, skipping")
                        continue
                except Exception as e:
                    logger.warning(f"CIK {cik}: Filing {filing_idx} HTML fetch failed: {e}, skipping")
                    continue

                # Parse iXBRL
                soup = BeautifulSoup(html, 'lxml')

                # Extract contexts
                context_map = parse_contexts(soup)

                # Build tag index for O(1) lookups; prefix detection is a side effect
                tag_index, tag_prefix = build_tag_index(soup)

                if not tag_prefix:
                    logger.info(f"CIK {cik}: Filing {filing_idx} has no iXBRL tags, trying HTML table fallback")
                    html_matched = _extract_fees_from_html_table(
                        soup, session, class_id_to_etf, series_id_to_etfs,
                        None, filing_date, cik
                    )
                    if html_matched:
                        logger.info(f"CIK {cik}: HTML fallback extracted fees for {len(html_matched)} ETF(s)")
                        satisfied.update(html_matched)

                    # For UITs (no class_id), try HTML performance fallback
                    if uit_etfs:
                        target_etf = uit_etfs[0] if len(uit_etfs) == 1 else None
                        if target_etf is None:
                            logger.warning(f"CIK {cik}: Multiple UIT ETFs found, cannot assign HTML performance unambiguously")
                        else:
                            _write_uit_html_performance(session, cik, target_etf, soup, filing_date, satisfied)

                    del tag_index, soup, html
                    gc.collect()
                    continue

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

                # Process each context that has a class_id (fund-level only, not benchmark)
                for context_id, context_data in context_map.items():
                    class_id = context_data.get('class_id')
                    if not class_id:
                        continue

                    # Skip benchmark contexts (they have both class_id and performance_measure)
                    if context_data.get('performance_measure'):
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

                    # Extract and upsert Performance data
                    try:
                        from etf_pipeline.benchmark_labels import resolve_benchmark_label
                        perf_data = _extract_performance_data(
                            tag_index, context_map, class_id, context_id, tag_prefix
                        )
                        fiscal_year_end = effective_date

                        perf_fields = ('return_1yr', 'return_5yr', 'return_10yr',
                                       'return_since_inception', 'benchmark_name',
                                       'benchmark_return_1yr', 'benchmark_return_5yr',
                                       'benchmark_return_10yr', 'portfolio_turnover')

                        if any(perf_data.get(k) is not None for k in perf_fields):
                            if perf_data.get('benchmark_name'):
                                resolve_benchmark_label(
                                    session,
                                    perf_data['benchmark_name'],
                                    xbrl_obj=None,
                                    cik=cik,
                                    filing_date=filing_date,
                                )
                            upsert_record(
                                session,
                                Performance,
                                filter_kwargs={
                                    'etf_id': etf.id,
                                    'fiscal_year_end': fiscal_year_end,
                                    'filing_date': filing_date,
                                },
                                data_kwargs={k: perf_data[k] for k in perf_fields if k in perf_data},
                            )
                            logger.debug(f"CIK {cik}: Upserted performance data for {etf.ticker}")
                    except Exception as e:
                        logger.warning(f"CIK {cik}: Failed to extract/upsert performance data for {etf.ticker}: {e}")

                    # Mark this class_id as satisfied (used in normal mode for early exit)
                    satisfied.add(class_id)

                # For UIT ETFs (no class_id), try HTML performance fallback
                # They are not present in the XBRL context map, so the per-class loop misses them
                if uit_etfs:
                    target_etf = uit_etfs[0] if len(uit_etfs) == 1 else None
                    if target_etf is None:
                        logger.warning(f"CIK {cik}: Multiple UIT ETFs found, cannot assign HTML performance unambiguously")
                    elif f"__UIT__{target_etf.id}" not in satisfied:
                        _write_uit_html_performance(session, cik, target_etf, soup, filing_date, satisfied)

                # Extract narrative text (series-level, not class-level)

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

                # Pre-group risk text blocks by series_id (single pass outside the series loop)
                risk_blocks_by_series: dict = {}
                for element in soup.find_all('ix:nonnumeric'):
                    tag_name = element.get('name', '')
                    if 'risktextblock' not in tag_name.lower() and 'risknarrativetextblock' not in tag_name.lower():
                        continue
                    element_context_ref = element.get('contextref', '')
                    sid = context_to_series.get(element_context_ref)
                    if sid is None:
                        continue
                    escape_attr = element.get('escape')
                    if escape_attr == 'true':
                        risk_text = strip_html_to_text(element.decode_contents())
                    else:
                        risk_text = element.get_text().strip()
                    if risk_text:
                        risk_blocks_by_series.setdefault(sid, []).append(risk_text)

                # Iterate known series from the database to avoid redundant RiskAxis-dimensioned iterations
                for series_id, etf_list in series_id_to_etfs.items():
                    context_id = series_context_map.get(series_id)

                    objective_text = None
                    strategy_text = None
                    if context_id:
                        objective_text = extract_tag_value(tag_index, f'{tag_prefix}:ObjectivePrimaryTextBlock', context_id)
                        strategy_text = extract_tag_value(tag_index, f'{tag_prefix}:StrategyNarrativeTextBlock', context_id)

                    risk_blocks = risk_blocks_by_series.get(series_id, [])
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

                del soup, html
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
                uit_etfs = [session.merge(e) for e in uit_etfs]
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
