"""Parse 485BPOS (prospectus) filings for fee/expense data using iXBRL.

This parser extracts data from the Risk/Return Summary section of prospectuses,
which uses the RR (Risk/Return) XBRL taxonomy. Data is embedded in HTML using
inline XBRL (iXBRL) tags.
"""

import logging
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


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

                # Extract class_id from ProspectusShareClassAxis
                elif 'prospectusshare' in dimension.lower():
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

    soup = BeautifulSoup(html_fragment, 'html.parser')
    text = soup.get_text()

    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def extract_tag_value(
    soup: BeautifulSoup,
    tag_name: str,
    context_id: str,
    negate_to_positive: bool = False,
) -> Optional[Decimal | str]:
    """Extract and convert value for a given RR tag and context.

    Args:
        soup: BeautifulSoup object of the filing
        tag_name: Full tag name (e.g., "rr:ManagementFeesOverAssets")
        context_id: Context ID to match
        negate_to_positive: If True, negate negative numeric values to positive

    Returns:
        Decimal for numeric tags, str for text tags, or None if not found
    """
    # Find all elements with this tag name and context (namespace-aware: ix:nonFraction, ix:nonNumeric)
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
    soup: BeautifulSoup,
    tag_name: str,
    context_id: str,
) -> Optional[date]:
    """Extract and parse a date from an iXBRL tag.

    Args:
        soup: BeautifulSoup object of the filing
        tag_name: Full tag name (e.g., "dei:DocumentPeriodEndDate")
        context_id: Context ID to match

    Returns:
        date object or None
    """
    value = extract_tag_value(soup, tag_name, context_id)
    if not value or not isinstance(value, str):
        return None

    # Try parsing various date formats
    for fmt in ['%Y-%m-%d', '%m/%d/%Y', '%m/%d/%y']:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue

    logger.warning(f"Failed to parse date: '{value}'")
    return None
