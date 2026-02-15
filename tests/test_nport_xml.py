"""Tests for NPORT-P XML custom field extraction."""

import pytest

from etf_pipeline.parsers.nport_xml import (
    extract_borrower_name,
    extract_liquidity_classification,
    parse_nport_investments_xml,
)

# Sample XML snippets for testing
NPORT_XML_TEMPLATE = '''<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/nport">
  <formData>
    <invstOrSecs>
      {investments}
    </invstOrSecs>
  </formData>
</edgarSubmission>'''


def test_extract_liquidity_classification_single_category():
    """Test extraction of simple single liquidity classification."""
    from xml.etree import ElementTree as ET

    xml_str = '''
    <invstOrSec xmlns="http://www.sec.gov/edgar/nport">
        <name>Test Security</name>
        <cusip>123456789</cusip>
        <fundCat>HLI</fundCat>
    </invstOrSec>'''

    elem = ET.fromstring(xml_str)
    result = extract_liquidity_classification(elem)

    assert result == "HLI"


def test_extract_liquidity_classification_multiple_categories():
    """Test extraction of liquidity classification with multiple categories."""
    from xml.etree import ElementTree as ET

    xml_str = '''
    <invstOrSec xmlns="http://www.sec.gov/edgar/nport">
        <name>Test Security</name>
        <cusip>123456789</cusip>
        <fundCats>
            <fundCat category="HLI" pct="70"/>
            <fundCat category="MLI" pct="30"/>
        </fundCats>
    </invstOrSec>'''

    elem = ET.fromstring(xml_str)
    result = extract_liquidity_classification(elem)

    # Should return the category with highest percentage
    assert result == "HLI"


def test_extract_liquidity_classification_multiple_categories_highest_not_first():
    """Test that the highest percentage category is selected, not just the first."""
    from xml.etree import ElementTree as ET

    xml_str = '''
    <invstOrSec xmlns="http://www.sec.gov/edgar/nport">
        <name>Test Security</name>
        <cusip>123456789</cusip>
        <fundCats>
            <fundCat category="MLI" pct="40"/>
            <fundCat category="LLI" pct="60"/>
        </fundCats>
    </invstOrSec>'''

    elem = ET.fromstring(xml_str)
    result = extract_liquidity_classification(elem)

    assert result == "LLI"


def test_extract_liquidity_classification_na_value():
    """Test that N/A liquidity classification returns None."""
    from xml.etree import ElementTree as ET

    xml_str = '''
    <invstOrSec xmlns="http://www.sec.gov/edgar/nport">
        <name>Test Security</name>
        <cusip>123456789</cusip>
        <fundCat>N/A</fundCat>
    </invstOrSec>'''

    elem = ET.fromstring(xml_str)
    result = extract_liquidity_classification(elem)

    assert result is None


def test_extract_liquidity_classification_missing():
    """Test that missing liquidity classification returns None."""
    from xml.etree import ElementTree as ET

    xml_str = '''
    <invstOrSec xmlns="http://www.sec.gov/edgar/nport">
        <name>Test Security</name>
        <cusip>123456789</cusip>
    </invstOrSec>'''

    elem = ET.fromstring(xml_str)
    result = extract_liquidity_classification(elem)

    assert result is None


def test_extract_liquidity_classification_all_categories():
    """Test all valid liquidity classification values."""
    from xml.etree import ElementTree as ET

    categories = ["HLI", "MLI", "LLI", "ILI"]

    for cat in categories:
        xml_str = f'''
        <invstOrSec xmlns="http://www.sec.gov/edgar/nport">
            <name>Test Security</name>
            <fundCat>{cat}</fundCat>
        </invstOrSec>'''

        elem = ET.fromstring(xml_str)
        result = extract_liquidity_classification(elem)

        assert result == cat


def test_extract_borrower_name_always_none():
    """Test that borrower name extraction always returns None.

    Borrower information is at fund level, not holding level in NPORT schema.
    """
    from xml.etree import ElementTree as ET

    xml_str = '''
    <invstOrSec xmlns="http://www.sec.gov/edgar/nport">
        <name>Test Security</name>
        <cusip>123456789</cusip>
    </invstOrSec>'''

    elem = ET.fromstring(xml_str)
    result = extract_borrower_name(elem)

    assert result is None


def test_parse_nport_investments_xml_single_holding():
    """Test parsing complete NPORT XML with single investment."""
    xml_content = NPORT_XML_TEMPLATE.format(investments='''
      <invstOrSec>
        <name>Apple Inc</name>
        <cusip>037833100</cusip>
        <lei>HWUPKR0MPOU8FGXBT394</lei>
        <fundCat>HLI</fundCat>
      </invstOrSec>
    ''')

    result = parse_nport_investments_xml(xml_content)

    assert len(result) == 1
    holding_key = "Apple Inc|037833100|HWUPKR0MPOU8FGXBT394"
    assert holding_key in result
    assert result[holding_key]["liquidity_classification"] == "HLI"
    assert result[holding_key]["borrower_name"] is None


def test_parse_nport_investments_xml_multiple_holdings():
    """Test parsing NPORT XML with multiple investments."""
    xml_content = NPORT_XML_TEMPLATE.format(investments='''
      <invstOrSec>
        <name>Apple Inc</name>
        <cusip>037833100</cusip>
        <lei>HWUPKR0MPOU8FGXBT394</lei>
        <fundCats>
          <fundCat category="HLI" pct="100"/>
        </fundCats>
      </invstOrSec>
      <invstOrSec>
        <name>Microsoft Corp</name>
        <cusip>594918104</cusip>
        <lei>INR2EJN1ERAN0W5ZP974</lei>
        <fundCats>
          <fundCat category="MLI" pct="60"/>
          <fundCat category="LLI" pct="40"/>
        </fundCats>
      </invstOrSec>
      <invstOrSec>
        <name>Private Security</name>
        <cusip>999999999</cusip>
        <lei>N/A</lei>
        <fundCat>ILI</fundCat>
      </invstOrSec>
    ''')

    result = parse_nport_investments_xml(xml_content)

    assert len(result) == 3

    # Check Apple
    apple_key = "Apple Inc|037833100|HWUPKR0MPOU8FGXBT394"
    assert result[apple_key]["liquidity_classification"] == "HLI"

    # Check Microsoft - should get MLI (highest percentage)
    msft_key = "Microsoft Corp|594918104|INR2EJN1ERAN0W5ZP974"
    assert result[msft_key]["liquidity_classification"] == "MLI"

    # Check Private Security (LEI is "N/A" which gets cleaned to empty string)
    private_key = "Private Security|999999999|"
    assert result[private_key]["liquidity_classification"] == "ILI"


def test_parse_nport_investments_xml_missing_identifiers():
    """Test parsing investments with missing CUSIP or LEI."""
    xml_content = NPORT_XML_TEMPLATE.format(investments='''
      <invstOrSec>
        <name>Security Without CUSIP</name>
        <lei>TESTLEI123456789012</lei>
        <fundCat>MLI</fundCat>
      </invstOrSec>
      <invstOrSec>
        <name>Security Without LEI</name>
        <cusip>123456789</cusip>
        <fundCat>HLI</fundCat>
      </invstOrSec>
    ''')

    result = parse_nport_investments_xml(xml_content)

    assert len(result) == 2

    # Security without CUSIP
    key1 = "Security Without CUSIP||TESTLEI123456789012"
    assert key1 in result
    assert result[key1]["liquidity_classification"] == "MLI"

    # Security without LEI
    key2 = "Security Without LEI|123456789|"
    assert key2 in result
    assert result[key2]["liquidity_classification"] == "HLI"


def test_parse_nport_investments_xml_no_liquidity_classification():
    """Test parsing investments without liquidity classification."""
    xml_content = NPORT_XML_TEMPLATE.format(investments='''
      <invstOrSec>
        <name>Test Security</name>
        <cusip>123456789</cusip>
        <lei>TESTLEI123456789012</lei>
      </invstOrSec>
    ''')

    result = parse_nport_investments_xml(xml_content)

    assert len(result) == 1
    holding_key = "Test Security|123456789|TESTLEI123456789012"
    assert result[holding_key]["liquidity_classification"] is None
    assert result[holding_key]["borrower_name"] is None


def test_parse_nport_investments_xml_invalid_xml():
    """Test that invalid XML returns empty dict."""
    xml_content = "This is not valid XML"

    result = parse_nport_investments_xml(xml_content)

    assert result == {}


def test_parse_nport_investments_xml_empty_investments():
    """Test parsing NPORT XML with no investments."""
    xml_content = NPORT_XML_TEMPLATE.format(investments='')

    result = parse_nport_investments_xml(xml_content)

    assert result == {}
