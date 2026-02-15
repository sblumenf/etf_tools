"""Custom XML field extraction for NPORT-P filings.

This module handles extraction of NPORT fields that are not exposed by
edgartools' FundReport API, requiring direct XML parsing.
"""

import logging
import xml.etree.ElementTree as ET
from typing import Optional

logger = logging.getLogger(__name__)

# NPORT XML namespace
NPORT_NS = {"ns": "http://www.sec.gov/edgar/nport"}


def extract_liquidity_classification(invst_or_sec_element: ET.Element) -> Optional[str]:
    """Extract liquidity classification from an invstOrSec XML element.

    The liquidity classification can appear in two forms:
    1. Simple: <fundCat>N/A</fundCat> or <fundCat>HLI</fundCat> (deprecated, rarely used)
    2. Multiple: <fundCats><fundCat category="HLI" pct="70"/><fundCat category="MLI" pct="30"/></fundCats>

    For multiple classifications, we return the category with the highest percentage.

    Valid values per NPORT schema:
    - HLI: Highly Liquid Investments
    - MLI: Moderately Liquid Investments
    - LLI: Less Liquid Investments
    - ILI: Illiquid Investments
    - N/A: Not classified

    Args:
        invst_or_sec_element: XML element for a single investment/security

    Returns:
        Liquidity classification code (HLI/MLI/LLI/ILI) or None if N/A or not present
    """
    try:
        # Check for simple fundCat element
        fund_cat = invst_or_sec_element.find("ns:fundCat", NPORT_NS)
        if fund_cat is not None:
            value = fund_cat.text
            if value and value.strip() not in ("N/A", ""):
                return value.strip()

        # Check for multiple fundCats element
        fund_cats = invst_or_sec_element.find("ns:fundCats", NPORT_NS)
        if fund_cats is not None:
            # Find all fundCat children and get the one with highest percentage
            categories = []
            for cat in fund_cats.findall("ns:fundCat", NPORT_NS):
                category = cat.get("category")
                pct = cat.get("pct")
                if category and pct:
                    try:
                        categories.append((category, float(pct)))
                    except ValueError:
                        logger.warning(f"Invalid percentage value for liquidity category: {pct}")
                        continue

            if categories:
                # Return category with highest percentage
                categories.sort(key=lambda x: x[1], reverse=True)
                return categories[0][0]

        return None

    except Exception as e:
        logger.warning(f"Error extracting liquidity classification: {e}")
        return None


def extract_borrower_name(invst_or_sec_element: ET.Element) -> Optional[str]:
    """Extract borrower name for repurchase agreement holdings.

    Note: In the NPORT-P XML schema, borrower information is stored at the
    fund level (<fundInfo><borrowers><borrower name="..." lei="..."/></borrowers>),
    not at the individual holding level. This function is a placeholder for
    potential future enhancement or alternative schema versions.

    Per the official NPORT XML schema (version 1.7), there is no borrower field
    within the invstOrSec element structure. This will always return None unless
    the schema changes or we find an undocumented field.

    Args:
        invst_or_sec_element: XML element for a single investment/security

    Returns:
        None (borrower data not available at holding level in current schema)
    """
    # Borrower information is at fund level, not holding level in NPORT schema
    # This function exists for API consistency but will always return None
    return None


def parse_nport_investments_xml(xml_content: str) -> dict[str, dict]:
    """Parse NPORT XML and extract custom fields for all investments.

    This function parses the full NPORT XML document and extracts custom fields
    (liquidity classification, borrower name) for each investment, indexed by
    a holding key constructed from identifying information.

    Args:
        xml_content: Raw XML content from NPORT-P filing

    Returns:
        Dictionary mapping holding_key -> {liquidity_classification, borrower_name}
        where holding_key is constructed from name+cusip+lei for uniqueness
    """
    try:
        root = ET.fromstring(xml_content)

        # Find all invstOrSec elements
        invst_or_secs = root.findall(".//ns:invstOrSec", NPORT_NS)

        result = {}
        for inv_elem in invst_or_secs:
            # Extract identifying information to build holding key
            name_elem = inv_elem.find("ns:name", NPORT_NS)
            cusip_elem = inv_elem.find("ns:cusip", NPORT_NS)
            lei_elem = inv_elem.find("ns:lei", NPORT_NS)

            name = name_elem.text if name_elem is not None else ""
            cusip = cusip_elem.text if cusip_elem is not None else ""
            lei = lei_elem.text if lei_elem is not None else ""

            # Build holding key (same logic as in nport.py _map_investment_to_holding)
            holding_key = f"{name}|{cusip}|{lei}"

            # Extract custom fields
            liquidity = extract_liquidity_classification(inv_elem)
            borrower = extract_borrower_name(inv_elem)

            result[holding_key] = {
                "liquidity_classification": liquidity,
                "borrower_name": borrower,
            }

        return result

    except ET.ParseError as e:
        logger.error(f"Failed to parse NPORT XML: {e}")
        return {}
    except Exception as e:
        logger.error(f"Error parsing NPORT investments XML: {e}")
        return {}
