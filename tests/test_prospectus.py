"""Tests for prospectus (485BPOS) iXBRL parser."""

from decimal import Decimal
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from etf_pipeline.parsers.prospectus import (
    convert_numeric_value,
    extract_tag_value,
    parse_contexts,
    parse_date_tag,
    strip_html_to_text,
)


@pytest.fixture
def sample_filing():
    """Load sample 485BPOS fixture."""
    fixture_path = Path(__file__).parent / "fixtures" / "prospectus" / "sample_485bpos.html"
    with open(fixture_path, 'r', encoding='utf-8') as f:
        html = f.read()
    return BeautifulSoup(html, 'html.parser')


class TestParseContexts:
    """Test context parsing (CIK, series_id, class_id extraction)."""

    def test_parse_contexts_base_context(self, sample_filing):
        """Test parsing base context (CIK only)."""
        context_map = parse_contexts(sample_filing)

        assert "AsOf2022-11-03" in context_map
        assert context_map["AsOf2022-11-03"]["cik"] == "0001314612"
        assert context_map["AsOf2022-11-03"]["series_id"] is None
        assert context_map["AsOf2022-11-03"]["class_id"] is None

    def test_parse_contexts_series_level(self, sample_filing):
        """Test parsing series-level context (CIK + series_id)."""
        context_map = parse_contexts(sample_filing)

        context_id = "AsOf2022-11-03_custom_S000014796Member"
        assert context_id in context_map
        assert context_map[context_id]["cik"] == "0001314612"
        assert context_map[context_id]["series_id"] == "S000014796"
        assert context_map[context_id]["class_id"] is None

    def test_parse_contexts_class_level(self, sample_filing):
        """Test parsing class-level context (CIK + series_id + class_id)."""
        context_map = parse_contexts(sample_filing)

        context_id = "AsOf2022-11-03_custom_S000014796Member_custom_C000014542Member"
        assert context_id in context_map
        assert context_map[context_id]["cik"] == "0001314612"
        assert context_map[context_id]["series_id"] == "S000014796"
        assert context_map[context_id]["class_id"] == "C000014542"

    def test_parse_contexts_multiple_classes(self, sample_filing):
        """Test parsing multiple class contexts."""
        context_map = parse_contexts(sample_filing)

        # Class A
        context_a = "AsOf2022-11-03_custom_S000014796Member_custom_C000014542Member"
        assert context_map[context_a]["class_id"] == "C000014542"

        # Class I
        context_i = "AsOf2022-11-03_custom_S000014796Member_custom_C000014546Member"
        assert context_map[context_i]["class_id"] == "C000014546"


class TestConvertNumericValue:
    """Test numeric value conversion rules."""

    def test_scale_factor_negative_two(self):
        """Test scale factor -2: displayed 0.70 → Decimal('0.0070')."""
        html = '<ix:ix:nonfraction scale="-2">0.70</ix:ix:nonfraction>'
        element = BeautifulSoup(html, 'html.parser').find('ix:ix:nonfraction')

        result = convert_numeric_value(element, scale="-2")
        assert result == Decimal('0.0070')

    def test_scale_factor_negative_two_various_values(self):
        """Test scale factor -2 with various displayed values."""
        test_cases = [
            ("5.75", Decimal('0.0575')),
            ("1.00", Decimal('0.0100')),
            ("0.25", Decimal('0.0025')),
            ("0.10", Decimal('0.0010')),
        ]

        for displayed, expected in test_cases:
            html = f'<ix:nonFraction scale="-2">{displayed}</ix:nonFraction>'
            element = BeautifulSoup(html, 'html.parser').find('ix:nonfraction')
            result = convert_numeric_value(element, scale="-2")
            assert result == expected, f"Failed for {displayed}"

    def test_format_numwordsen_none(self):
        """Test ixt-sec:numwordsen 'None' → NULL."""
        html = '<ix:nonFraction format="ixt-sec:numwordsen" scale="-2">None</ix:nonFraction>'
        element = BeautifulSoup(html, 'html.parser').find('ix:nonfraction')

        result = convert_numeric_value(element, scale="-2", format_attr="ixt-sec:numwordsen")
        assert result is None

    def test_format_numwordsen_na(self):
        """Test ixt-sec:numwordsen 'N/A' → NULL."""
        html = '<ix:nonFraction format="ixt-sec:numwordsen" scale="-2">N/A</ix:nonFraction>'
        element = BeautifulSoup(html, 'html.parser').find('ix:nonfraction')

        result = convert_numeric_value(element, scale="-2", format_attr="ixt-sec:numwordsen")
        assert result is None

    def test_format_zerodash(self):
        """Test ixt:zerodash '—' → Decimal('0')."""
        html = '<ix:nonFraction format="ixt:zerodash" scale="-2">—</ix:nonFraction>'
        element = BeautifulSoup(html, 'html.parser').find('ix:nonfraction')

        result = convert_numeric_value(element, scale="-2", format_attr="ixt:zerodash")
        assert result == Decimal('0')

    def test_sign_negative(self):
        """Test sign="-" negates the value."""
        html = '<ix:nonFraction scale="-2" sign="-">0.10</ix:nonFraction>'
        element = BeautifulSoup(html, 'html.parser').find('ix:nonfraction')

        result = convert_numeric_value(element, scale="-2", sign="-")
        # 0.10 * 10^-2 = 0.0010, then negate to -0.0010
        assert result == Decimal('-0.0010')

    def test_negate_to_positive_fee_waiver(self):
        """Test negate_to_positive=True converts negative to positive."""
        html = '<ix:nonFraction scale="-2" sign="-">0.10</ix:nonFraction>'
        element = BeautifulSoup(html, 'html.parser').find('ix:nonfraction')

        result = convert_numeric_value(element, scale="-2", sign="-", negate_to_positive=True)
        # 0.10 * 10^-2 = 0.0010, then negate to -0.0010, then flip to +0.0010
        assert result == Decimal('0.0010')

    def test_negate_to_positive_redemption_fee(self):
        """Test negate_to_positive=True for redemption fee (displayed 2.00, sign=-)."""
        html = '<ix:nonFraction scale="-2" sign="-">2.00</ix:nonFraction>'
        element = BeautifulSoup(html, 'html.parser').find('ix:nonfraction')

        result = convert_numeric_value(element, scale="-2", sign="-", negate_to_positive=True)
        # 2.00 * 10^-2 = 0.0200, then negate to -0.0200, then flip to +0.0200
        assert result == Decimal('0.0200')

    def test_no_scale(self):
        """Test numeric value without scale factor."""
        html = '<ix:nonFraction>695</ix:nonFraction>'
        element = BeautifulSoup(html, 'html.parser').find('ix:nonfraction')

        result = convert_numeric_value(element)
        assert result == Decimal('695')

    def test_decimal_formatting(self):
        """Test value with comma formatting."""
        html = '<ix:nonFraction>1,223</ix:nonFraction>'
        element = BeautifulSoup(html, 'html.parser').find('ix:nonfraction')

        result = convert_numeric_value(element)
        assert result == Decimal('1223')


class TestStripHtmlToText:
    """Test HTML stripping for text blocks."""

    def test_strip_simple_html(self):
        """Test stripping simple HTML tags."""
        html = "<p>The fund seeks long-term capital growth.</p>"
        result = strip_html_to_text(html)
        assert result == "The fund seeks long-term capital growth."

    def test_strip_nested_html(self):
        """Test stripping nested HTML tags."""
        html = "<p>The fund invests primarily in <b>common stocks</b> of large U.S. companies.</p>"
        result = strip_html_to_text(html)
        assert result == "The fund invests primarily in common stocks of large U.S. companies."

    def test_strip_multiple_paragraphs(self):
        """Test stripping multiple paragraphs."""
        html = "<p>First paragraph.</p><p>Second paragraph.</p>"
        result = strip_html_to_text(html)
        # Multiple whitespace normalized to single space
        assert "First paragraph" in result
        assert "Second paragraph" in result

    def test_normalize_whitespace(self):
        """Test whitespace normalization."""
        html = "<p>Text with   multiple    spaces.</p>"
        result = strip_html_to_text(html)
        assert result == "Text with multiple spaces."

    def test_empty_html(self):
        """Test empty HTML."""
        assert strip_html_to_text("") == ""
        assert strip_html_to_text("<p></p>") == ""


class TestExtractTagValue:
    """Test tag extraction from iXBRL filing."""

    def test_extract_management_fee_class_a(self, sample_filing):
        """Test extracting management fee for Class A."""
        context_id = "AsOf2022-11-03_custom_S000014796Member_custom_C000014542Member"
        value = extract_tag_value(sample_filing, "rr:ManagementFeesOverAssets", context_id)

        assert value == Decimal('0.0070')  # 0.70% with scale -2

    def test_extract_distribution_12b1_class_a(self, sample_filing):
        """Test extracting 12b-1 fee for Class A."""
        context_id = "AsOf2022-11-03_custom_S000014796Member_custom_C000014542Member"
        value = extract_tag_value(sample_filing, "rr:DistributionAndService12b1FeesOverAssets", context_id)

        assert value == Decimal('0.0025')  # 0.25% with scale -2

    def test_extract_other_expenses_class_a(self, sample_filing):
        """Test extracting other expenses for Class A."""
        context_id = "AsOf2022-11-03_custom_S000014796Member_custom_C000014542Member"
        value = extract_tag_value(sample_filing, "rr:OtherExpensesOverAssets", context_id)

        assert value == Decimal('0.0030')  # 0.30% with scale -2

    def test_extract_total_expense_gross_class_a(self, sample_filing):
        """Test extracting total gross expense for Class A."""
        context_id = "AsOf2022-11-03_custom_S000014796Member_custom_C000014542Member"
        value = extract_tag_value(sample_filing, "rr:ExpensesOverAssets", context_id)

        assert value == Decimal('0.0125')  # 1.25% with scale -2

    def test_extract_fee_waiver_class_a(self, sample_filing):
        """Test extracting fee waiver for Class A (with sign=- and negate_to_positive)."""
        context_id = "AsOf2022-11-03_custom_S000014796Member_custom_C000014542Member"
        value = extract_tag_value(
            sample_filing,
            "rr:FeeWaiverOrReimbursementOverAssets",
            context_id,
            negate_to_positive=True
        )

        # Displayed: 0.10%, scale=-2, sign="-" → -0.0010, then negate_to_positive → 0.0010
        assert value == Decimal('0.0010')

    def test_extract_total_expense_net_class_a(self, sample_filing):
        """Test extracting total net expense for Class A."""
        context_id = "AsOf2022-11-03_custom_S000014796Member_custom_C000014542Member"
        value = extract_tag_value(sample_filing, "rr:NetExpensesOverAssets", context_id)

        assert value == Decimal('0.0115')  # 1.15% with scale -2

    def test_extract_zerodash_value_class_i(self, sample_filing):
        """Test extracting zerodash value for Class I 12b-1 fee."""
        context_id = "AsOf2022-11-03_custom_S000014796Member_custom_C000014546Member"
        value = extract_tag_value(sample_filing, "rr:DistributionAndService12b1FeesOverAssets", context_id)

        assert value == Decimal('0')  # zerodash "—" → 0

    def test_extract_numwordsen_none_class_i(self, sample_filing):
        """Test extracting 'None' value for Class I front load."""
        context_id = "AsOf2022-11-03_custom_S000014796Member_custom_C000014546Member"
        value = extract_tag_value(
            sample_filing,
            "rr:MaximumSalesChargeImposedOnPurchasesOverOfferingPrice",
            context_id
        )

        assert value is None  # "None" with numwordsen → NULL

    def test_extract_front_load_class_a(self, sample_filing):
        """Test extracting front load for Class A."""
        context_id = "AsOf2022-11-03_custom_S000014796Member_custom_C000014542Member"
        value = extract_tag_value(
            sample_filing,
            "rr:MaximumSalesChargeImposedOnPurchasesOverOfferingPrice",
            context_id
        )

        assert value == Decimal('0.0575')  # 5.75% with scale -2

    def test_extract_deferred_load_class_a(self, sample_filing):
        """Test extracting deferred load for Class A."""
        context_id = "AsOf2022-11-03_custom_S000014796Member_custom_C000014542Member"
        value = extract_tag_value(sample_filing, "rr:MaximumDeferredSalesChargeOverOther", context_id)

        assert value == Decimal('0.0100')  # 1.00% with scale -2

    def test_extract_redemption_fee_class_a(self, sample_filing):
        """Test extracting redemption fee for Class A (with sign=- and negate_to_positive)."""
        context_id = "AsOf2022-11-03_custom_S000014796Member_custom_C000014542Member"
        value = extract_tag_value(sample_filing, "rr:RedemptionFee", context_id, negate_to_positive=True)

        # Displayed: 2.00%, scale=-2, sign="-" → -0.0200, then negate_to_positive → 0.0200
        assert value == Decimal('0.0200')

    def test_extract_expense_example_year_01(self, sample_filing):
        """Test extracting expense example 1 year."""
        context_id = "AsOf2022-11-03_custom_S000014796Member_custom_C000014542Member"
        value = extract_tag_value(sample_filing, "rr:ExpenseExampleYear01", context_id)

        assert value == Decimal('695')

    def test_extract_expense_example_year_03(self, sample_filing):
        """Test extracting expense example 3 years."""
        context_id = "AsOf2022-11-03_custom_S000014796Member_custom_C000014542Member"
        value = extract_tag_value(sample_filing, "rr:ExpenseExampleYear03", context_id)

        assert value == Decimal('949')

    def test_extract_expense_example_year_05(self, sample_filing):
        """Test extracting expense example 5 years."""
        context_id = "AsOf2022-11-03_custom_S000014796Member_custom_C000014542Member"
        value = extract_tag_value(sample_filing, "rr:ExpenseExampleYear05", context_id)

        assert value == Decimal('1223')

    def test_extract_expense_example_year_10(self, sample_filing):
        """Test extracting expense example 10 years."""
        context_id = "AsOf2022-11-03_custom_S000014796Member_custom_C000014542Member"
        value = extract_tag_value(sample_filing, "rr:ExpenseExampleYear10", context_id)

        assert value == Decimal('2019')

    def test_extract_objective_text_block(self, sample_filing):
        """Test extracting objective text block (HTML stripped)."""
        context_id = "AsOf2022-11-03_custom_S000014796Member"
        value = extract_tag_value(sample_filing, "rr:ObjectivePrimaryTextBlock", context_id)

        assert isinstance(value, str)
        assert value == "The fund seeks long-term capital growth."

    def test_extract_strategy_text_block(self, sample_filing):
        """Test extracting strategy text block (HTML stripped, preserves bold)."""
        context_id = "AsOf2022-11-03_custom_S000014796Member"
        value = extract_tag_value(sample_filing, "rr:StrategyNarrativeTextBlock", context_id)

        assert isinstance(value, str)
        # HTML <b> tags should be stripped
        assert value == "The fund invests primarily in common stocks of large U.S. companies."

    def test_extract_missing_tag(self, sample_filing):
        """Test extracting non-existent tag returns None."""
        context_id = "AsOf2022-11-03_custom_S000014796Member_custom_C000014542Member"
        value = extract_tag_value(sample_filing, "rr:NonExistentTag", context_id)

        assert value is None

    def test_extract_wrong_context(self, sample_filing):
        """Test extracting tag with wrong context returns None."""
        # Try to extract Class A data using Class I context
        context_id = "AsOf2022-11-03_custom_S000014796Member_custom_C000014546Member"
        value = extract_tag_value(sample_filing, "rr:FeeWaiverOrReimbursementOverAssets", context_id)

        # Class I doesn't have a fee waiver in the fixture
        assert value is None


class TestParseDateTag:
    """Test date parsing from iXBRL tags."""

    def test_parse_date_iso_format(self, sample_filing):
        """Test parsing date in ISO format (YYYY-MM-DD)."""
        context_id = "AsOf2022-11-03"
        date_value = parse_date_tag(sample_filing, "dei:DocumentPeriodEndDate", context_id)

        from datetime import date
        assert date_value == date(2022, 11, 3)

    def test_parse_date_missing_tag(self, sample_filing):
        """Test parsing missing date tag returns None."""
        context_id = "AsOf2022-11-03"
        date_value = parse_date_tag(sample_filing, "dei:NonExistentDate", context_id)

        assert date_value is None


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_convert_numeric_value_none_element(self):
        """Test convert_numeric_value with None element."""
        result = convert_numeric_value(None)
        assert result is None

    def test_convert_numeric_value_empty_text(self):
        """Test convert_numeric_value with empty text."""
        html = '<ix:nonFraction scale="-2"></ix:nonFraction>'
        element = BeautifulSoup(html, 'html.parser').find('ix:nonfraction')

        result = convert_numeric_value(element, scale="-2")
        assert result is None

    def test_convert_numeric_value_invalid_number(self):
        """Test convert_numeric_value with invalid number text."""
        html = '<ix:nonFraction scale="-2">ABC</ix:nonFraction>'
        element = BeautifulSoup(html, 'html.parser').find('ix:nonfraction')

        result = convert_numeric_value(element, scale="-2")
        assert result is None

    def test_parse_contexts_missing_identifier(self):
        """Test parse_contexts with missing identifier."""
        html = """
        <xbrli:context id="NoIdentifier">
          <xbrli:entity>
          </xbrli:entity>
        </xbrli:context>
        """
        soup = BeautifulSoup(html, 'html.parser')
        context_map = parse_contexts(soup)

        # Context should be found even if CIK is missing
        assert "NoIdentifier" in context_map
        assert context_map["NoIdentifier"]["cik"] is None
