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
    _parse_html_fee_value,
    _match_fee_row_label,
    _extract_fees_from_html_table,
)


@pytest.fixture
def sample_filing():
    """Load sample 485BPOS fixture."""
    fixture_path = Path(__file__).parent / "fixtures" / "prospectus" / "sample_485bpos.html"
    with open(fixture_path, 'r', encoding='utf-8') as f:
        html = f.read()
    return BeautifulSoup(html, 'lxml')


@pytest.fixture
def sample_filing_path():
    """Return path to sample 485BPOS fixture."""
    return Path(__file__).parent / "fixtures" / "prospectus" / "sample_485bpos.html"


@pytest.fixture
def sample_filing_oef():
    """Load sample 485BPOS fixture with OEF namespace."""
    fixture_path = Path(__file__).parent / "fixtures" / "prospectus" / "sample_485bpos_oef.html"
    with open(fixture_path, 'r', encoding='utf-8') as f:
        html = f.read()
    return BeautifulSoup(html, 'lxml')


@pytest.fixture
def sample_filing_oef_path():
    """Return path to sample 485BPOS OEF fixture."""
    return Path(__file__).parent / "fixtures" / "prospectus" / "sample_485bpos_oef.html"


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
        element = BeautifulSoup(html, 'lxml').find('ix:ix:nonfraction')

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
            element = BeautifulSoup(html, 'lxml').find('ix:nonfraction')
            result = convert_numeric_value(element, scale="-2")
            assert result == expected, f"Failed for {displayed}"

    def test_format_numwordsen_none(self):
        """Test ixt-sec:numwordsen 'None' → NULL."""
        html = '<ix:nonFraction format="ixt-sec:numwordsen" scale="-2">None</ix:nonFraction>'
        element = BeautifulSoup(html, 'lxml').find('ix:nonfraction')

        result = convert_numeric_value(element, scale="-2", format_attr="ixt-sec:numwordsen")
        assert result is None

    def test_format_numwordsen_na(self):
        """Test ixt-sec:numwordsen 'N/A' → NULL."""
        html = '<ix:nonFraction format="ixt-sec:numwordsen" scale="-2">N/A</ix:nonFraction>'
        element = BeautifulSoup(html, 'lxml').find('ix:nonfraction')

        result = convert_numeric_value(element, scale="-2", format_attr="ixt-sec:numwordsen")
        assert result is None

    def test_format_zerodash(self):
        """Test ixt:zerodash '—' → Decimal('0')."""
        html = '<ix:nonFraction format="ixt:zerodash" scale="-2">—</ix:nonFraction>'
        element = BeautifulSoup(html, 'lxml').find('ix:nonfraction')

        result = convert_numeric_value(element, scale="-2", format_attr="ixt:zerodash")
        assert result == Decimal('0')

    def test_sign_negative(self):
        """Test sign="-" negates the value."""
        html = '<ix:nonFraction scale="-2" sign="-">0.10</ix:nonFraction>'
        element = BeautifulSoup(html, 'lxml').find('ix:nonfraction')

        result = convert_numeric_value(element, scale="-2", sign="-")
        # 0.10 * 10^-2 = 0.0010, then negate to -0.0010
        assert result == Decimal('-0.0010')

    def test_negate_to_positive_fee_waiver(self):
        """Test negate_to_positive=True converts negative to positive."""
        html = '<ix:nonFraction scale="-2" sign="-">0.10</ix:nonFraction>'
        element = BeautifulSoup(html, 'lxml').find('ix:nonfraction')

        result = convert_numeric_value(element, scale="-2", sign="-", negate_to_positive=True)
        # 0.10 * 10^-2 = 0.0010, then negate to -0.0010, then flip to +0.0010
        assert result == Decimal('0.0010')

    def test_negate_to_positive_redemption_fee(self):
        """Test negate_to_positive=True for redemption fee (displayed 2.00, sign=-)."""
        html = '<ix:nonFraction scale="-2" sign="-">2.00</ix:nonFraction>'
        element = BeautifulSoup(html, 'lxml').find('ix:nonfraction')

        result = convert_numeric_value(element, scale="-2", sign="-", negate_to_positive=True)
        # 2.00 * 10^-2 = 0.0200, then negate to -0.0200, then flip to +0.0200
        assert result == Decimal('0.0200')

    def test_no_scale(self):
        """Test numeric value without scale factor."""
        html = '<ix:nonFraction>695</ix:nonFraction>'
        element = BeautifulSoup(html, 'lxml').find('ix:nonfraction')

        result = convert_numeric_value(element)
        assert result == Decimal('695')

    def test_decimal_formatting(self):
        """Test value with comma formatting."""
        html = '<ix:nonFraction>1,223</ix:nonFraction>'
        element = BeautifulSoup(html, 'lxml').find('ix:nonfraction')

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
        value = extract_tag_value(sample_filing, "rr:RedemptionFeeOverRedemption", context_id, negate_to_positive=True)

        # Displayed: 2.00%, scale=-2, sign="-" → -0.0200, then negate_to_positive → 0.0200
        assert value == Decimal('0.0200')

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

    def test_extract_principal_risks_text_block(self, sample_filing):
        """Test extracting a single risk text block with risk dimension context."""
        # The fixture now has multiple RiskTextBlock elements with risk-dimensioned contexts
        # Test that we can extract individual risk blocks by their specific context
        context_id = "AsOf2022-11-03_custom_S000014796Member_custom_RiskLoseMoneyMember"
        value = extract_tag_value(sample_filing, "rr:RiskTextBlock", context_id)

        assert isinstance(value, str)
        assert "Risk of Loss" in value
        assert value == "Risk of Loss. It is important to understand that you can lose money by investing in the fund."

        # Test another risk dimension
        context_id = "AsOf2022-11-03_custom_S000014796Member_custom_PerformanceRiskMember"
        value = extract_tag_value(sample_filing, "rr:RiskTextBlock", context_id)

        assert isinstance(value, str)
        assert "Stock Market Volatility" in value

        # Test yet another risk dimension
        context_id = "AsOf2022-11-03_custom_S000014796Member_custom_ForeignExposureRiskMember"
        value = extract_tag_value(sample_filing, "rr:RiskTextBlock", context_id)

        assert isinstance(value, str)
        assert "Foreign Exposure" in value

    def test_extract_all_risk_blocks(self, sample_filing):
        """Test that all RiskTextBlock elements can be found for a series."""
        # This demonstrates how the parser collects multiple risk blocks
        # The actual parser uses soup.find_all to get all risk blocks for concatenation
        series_id = "S000014796"
        risk_blocks = []

        context_map = parse_contexts(sample_filing)
        context_to_series = {
            ctx_id: ctx_data['series_id']
            for ctx_id, ctx_data in context_map.items()
            if ctx_data.get('series_id')
        }

        for element in sample_filing.find_all('ix:nonnumeric'):
            tag_name = element.get('name', '')
            element_context_ref = element.get('contextref', '')

            if ('risktextblock' in tag_name.lower() or 'risknarrativetextblock' in tag_name.lower()) and context_to_series.get(element_context_ref) == series_id:
                risk_text = element.get_text().strip()
                if risk_text:
                    risk_blocks.append(risk_text)

        # Should find all 3 risk blocks from the fixture
        assert len(risk_blocks) == 3
        assert any("Risk of Loss" in block for block in risk_blocks)
        assert any("Stock Market Volatility" in block for block in risk_blocks)
        assert any("Foreign Exposure" in block for block in risk_blocks)

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

    def test_parse_fee_waiver_expiration_date(self, sample_filing):
        """Test parsing fee waiver expiration date."""
        context_id = "AsOf2022-11-03_custom_S000014796Member_custom_C000014542Member"
        date_value = parse_date_tag(sample_filing, "rr:FeeWaiverOrReimbursementOverAssetsDateOfTermination", context_id)

        from datetime import date
        assert date_value == date(2024, 12, 31)

    def test_parse_fee_waiver_expiration_date_missing(self, sample_filing):
        """Test parsing missing fee waiver expiration date returns None."""
        context_id = "AsOf2022-11-03_custom_S000014796Member_custom_C000014546Member"
        date_value = parse_date_tag(sample_filing, "rr:FeeWaiverOrReimbursementOverAssetsDateOfTermination", context_id)

        assert date_value is None


class TestParseDateTagFormats:
    """Test parse_date_tag() with various date format strings."""

    def _make_soup(self, date_text: str, context_id: str = "ctx1", tag_name: str = "dei:DocumentPeriodEndDate") -> BeautifulSoup:
        """Create a minimal BeautifulSoup with one ix:nonnumeric date tag."""
        html = (
            f'<html><body>'
            f'<ix:nonnumeric name="{tag_name}" contextref="{context_id}">{date_text}</ix:nonnumeric>'
            f'</body></html>'
        )
        return BeautifulSoup(html, 'lxml')

    def test_iso_format(self):
        """Test ISO format: 2024-12-31."""
        from datetime import date
        soup = self._make_soup("2024-12-31")
        result = parse_date_tag(soup, "dei:DocumentPeriodEndDate", "ctx1")
        assert result == date(2024, 12, 31)

    def test_us_slash_format(self):
        """Test US slash format: 12/31/2024."""
        from datetime import date
        soup = self._make_soup("12/31/2024")
        result = parse_date_tag(soup, "dei:DocumentPeriodEndDate", "ctx1")
        assert result == date(2024, 12, 31)

    def test_full_month_name(self):
        """Test full month name: February 6, 2026."""
        from datetime import date
        soup = self._make_soup("February 6, 2026")
        result = parse_date_tag(soup, "dei:DocumentPeriodEndDate", "ctx1")
        assert result == date(2026, 2, 6)

    def test_abbreviated_month_with_period(self):
        """Test abbreviated month with period: Dec. 31, 2024."""
        from datetime import date
        soup = self._make_soup("Dec. 31, 2024")
        result = parse_date_tag(soup, "dei:DocumentPeriodEndDate", "ctx1")
        assert result == date(2024, 12, 31)

    def test_full_month_name_variant(self):
        """Test full month name variant: August 20, 2025."""
        from datetime import date
        soup = self._make_soup("August 20, 2025")
        result = parse_date_tag(soup, "dei:DocumentPeriodEndDate", "ctx1")
        assert result == date(2025, 8, 20)


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_convert_numeric_value_none_element(self):
        """Test convert_numeric_value with None element."""
        result = convert_numeric_value(None)
        assert result is None

    def test_convert_numeric_value_empty_text(self):
        """Test convert_numeric_value with empty text."""
        html = '<ix:nonFraction scale="-2"></ix:nonFraction>'
        element = BeautifulSoup(html, 'lxml').find('ix:nonfraction')

        result = convert_numeric_value(element, scale="-2")
        assert result is None

    def test_convert_numeric_value_invalid_number(self):
        """Test convert_numeric_value with invalid number text."""
        html = '<ix:nonFraction scale="-2">ABC</ix:nonFraction>'
        element = BeautifulSoup(html, 'lxml').find('ix:nonfraction')

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
        soup = BeautifulSoup(html, 'lxml')
        context_map = parse_contexts(soup)

        # Context should be found even if CIK is missing
        assert "NoIdentifier" in context_map
        assert context_map["NoIdentifier"]["cik"] is None


class TestIntegrationProcessCikProspectus:
    """Integration tests for _process_cik_prospectus()."""

    def test_process_cik_full_flow(self, session, sample_filing_path):
        """Test full CIK processing flow with mocked filing."""
        from unittest.mock import Mock, patch
        from etf_pipeline.models import ETF, FeeExpense
        from etf_pipeline.parsers.prospectus import _process_cik_prospectus
        from datetime import date

        # Create ETF records matching the fixture
        etf_a = ETF(
            cik='0001314612',
            ticker='TESTA',
            fund_name='Test Fund - Class A', issuer_name='Test Issuer',
            series_id='S000014796',
            class_id='C000014542',
        )
        etf_i = ETF(
            cik='0001314612',
            ticker='TESTI',
            fund_name='Test Fund - Class I', issuer_name='Test Issuer',
            series_id='S000014796',
            class_id='C000014546',
        )
        session.add_all([etf_a, etf_i])
        session.commit()
        etf_a_id = etf_a.id
        etf_i_id = etf_i.id

        # Read fixture HTML
        with open(sample_filing_path) as f:
            html_content = f.read()

        # Mock edgartools objects
        mock_filing = Mock()
        mock_filing.html.return_value = html_content
        mock_filing.filing_date = date(2022, 11, 3)
        mock_filing.document.url = 'https://www.sec.gov/test/filing.htm'

        mock_filings = Mock()
        mock_filings.__getitem__ = Mock(return_value=mock_filing)
        mock_filings.__len__ = Mock(return_value=1)
        mock_filings.empty = False

        mock_company = Mock()
        mock_company.get_filings.return_value = mock_filings

        # Patch Company class
        with patch('edgar.Company', return_value=mock_company):
            result = _process_cik_prospectus(session, '0001314612')

        assert result is True

        # Verify FeeExpense data for Class A (values from fixture: 0.70 → 0.0070, etc.)
        fee_a = session.query(FeeExpense).filter_by(etf_id=etf_a_id).one()
        assert fee_a.management_fee == pytest.approx(Decimal('0.0070'))
        assert fee_a.distribution_12b1 == pytest.approx(Decimal('0.0025'))
        assert fee_a.other_expenses == pytest.approx(Decimal('0.0030'))
        assert fee_a.total_expense_gross == pytest.approx(Decimal('0.0125'))
        assert fee_a.fee_waiver == pytest.approx(Decimal('0.0010'))  # Negated from source -0.10
        assert fee_a.total_expense_net == pytest.approx(Decimal('0.0115'))
        assert fee_a.acquired_fund_fees is None  # Not in fixture
        assert fee_a.fee_waiver_expiration_date == date(2024, 12, 31)
        assert fee_a.effective_date == date(2022, 11, 3)

        # Verify FeeExpense data for Class I (values from fixture)
        fee_i = session.query(FeeExpense).filter_by(etf_id=etf_i_id).one()
        assert fee_i.management_fee == pytest.approx(Decimal('0.0070'))
        assert fee_i.distribution_12b1 == Decimal('0')  # zerodash "—"
        assert fee_i.other_expenses == pytest.approx(Decimal('0.0024'))  # 0.24 with scale -2
        assert fee_i.total_expense_gross == pytest.approx(Decimal('0.0094'))  # 0.94 with scale -2
        assert fee_i.fee_waiver_expiration_date is None  # Not in fixture for Class I

        # Verify ETF updates (narrative text from series-level context)
        from etf_pipeline.models import ETF as ETFModel
        etf_a_refreshed = session.get(ETFModel, etf_a_id)
        etf_i_refreshed = session.get(ETFModel, etf_i_id)
        assert etf_a_refreshed.objective_text == 'The fund seeks long-term capital growth.'
        assert etf_a_refreshed.strategy_text == 'The fund invests primarily in common stocks of large U.S. companies.'
        # Verify all three risk blocks are concatenated with double newlines
        expected_risks = (
            'Risk of Loss. It is important to understand that you can lose money by investing in the fund.\n\n'
            'Stock Market Volatility. Stock markets are volatile and can decline significantly in response to adverse issuer, political, regulatory, market, or economic developments.\n\n'
            'Foreign Exposure. Foreign markets can be more volatile than the U.S. market due to increased risks of adverse issuer, political, regulatory, market, or economic developments.'
        )
        assert etf_a_refreshed.principal_risks == expected_risks
        assert etf_a_refreshed.filing_url == 'https://www.sec.gov/test/filing.htm'
        # Both classes share the same series-level text (both have series_id S000014796)
        assert etf_i_refreshed.objective_text == 'The fund seeks long-term capital growth.'
        assert etf_i_refreshed.strategy_text == 'The fund invests primarily in common stocks of large U.S. companies.'
        assert etf_i_refreshed.principal_risks == expected_risks

    def test_process_cik_multi_filing(self, session, sample_filing_path):
        """Test processing multiple filings - verifies loop can handle multiple files."""
        from unittest.mock import Mock, patch
        from etf_pipeline.models import ETF, FeeExpense
        from etf_pipeline.parsers.prospectus import _process_cik_prospectus
        from datetime import date

        # Create ETF records matching the fixture
        etf_a = ETF(
            cik='0001314612',
            ticker='TESTA',
            fund_name='Test Fund - Class A', issuer_name='Test Issuer',
            series_id='S000014796',
            class_id='C000014542',
        )
        etf_i = ETF(
            cik='0001314612',
            ticker='TESTI',
            fund_name='Test Fund - Class I', issuer_name='Test Issuer',
            series_id='S000014796',
            class_id='C000014546',
        )
        session.add_all([etf_a, etf_i])
        session.commit()
        etf_a_id = etf_a.id
        etf_i_id = etf_i.id

        # Read fixture HTML (contains both classes)
        with open(sample_filing_path) as f:
            html_content = f.read()

        # Mock multiple filings available
        mock_filing_0 = Mock()
        mock_filing_0.html.return_value = html_content
        mock_filing_0.filing_date = date(2022, 11, 3)
        mock_filing_0.document.url = 'https://www.sec.gov/test/filing0.htm'

        mock_filing_1 = Mock()
        mock_filing_1.html.return_value = html_content
        mock_filing_1.filing_date = date(2022, 5, 3)
        mock_filing_1.document.url = 'https://www.sec.gov/test/filing1.htm'

        mock_filings = Mock()
        mock_filings.__getitem__ = Mock(side_effect=[mock_filing_0, mock_filing_1])
        mock_filings.__len__ = Mock(return_value=2)
        mock_filings.empty = False

        mock_company = Mock()
        mock_company.get_filings.return_value = mock_filings

        # Patch Company class
        with patch('edgar.Company', return_value=mock_company):
            result = _process_cik_prospectus(session, '0001314612')

        assert result is True

        # Both ETFs should have data
        fee_a = session.query(FeeExpense).filter_by(etf_id=etf_a_id).one()
        assert fee_a.management_fee == pytest.approx(Decimal('0.0070'))
        assert fee_a.effective_date == date(2022, 11, 3)

        fee_i = session.query(FeeExpense).filter_by(etf_id=etf_i_id).one()
        assert fee_i.management_fee == pytest.approx(Decimal('0.0070'))
        assert fee_i.effective_date == date(2022, 11, 3)

        # Verify both ETFs have filing URLs (from whichever filing processed them)
        from etf_pipeline.models import ETF as ETFModel
        etf_a_refreshed = session.get(ETFModel, etf_a_id)
        assert etf_a_refreshed.filing_url is not None

        etf_i_refreshed = session.get(ETFModel, etf_i_id)
        assert etf_i_refreshed.filing_url is not None

    def test_process_cik_no_filings(self, session):
        """Test CIK with no 485BPOS filings."""
        from unittest.mock import Mock, patch
        from etf_pipeline.models import ETF
        from etf_pipeline.parsers.prospectus import _process_cik_prospectus

        # Create ETF record
        etf = ETF(cik='0001314612', ticker='TEST', fund_name='Test', issuer_name='Test Issuer', class_id='C000014542')
        session.add(etf)
        session.commit()

        # Mock Company with empty filings
        mock_filings = Mock()
        mock_filings.empty = True

        mock_company = Mock()
        mock_company.get_filings.return_value = mock_filings

        with patch('edgar.Company', return_value=mock_company):
            result = _process_cik_prospectus(session, '0001314612')

        # Should succeed but do nothing
        assert result is True

    def test_process_cik_no_rr_tags(self, session):
        """Test filing with no RR tags."""
        from unittest.mock import Mock, patch
        from etf_pipeline.models import ETF
        from etf_pipeline.parsers.prospectus import _process_cik_prospectus
        from datetime import date

        # Create ETF record
        etf = ETF(cik='0001314612', ticker='TEST', fund_name='Test', issuer_name='Test Issuer', class_id='C000014542')
        session.add(etf)
        session.commit()

        # Mock filing with no RR tags
        html_no_rr = '<html><body>Plain HTML, no iXBRL</body></html>'

        mock_filing = Mock()
        mock_filing.html.return_value = html_no_rr
        mock_filing.filing_date = date(2022, 11, 3)

        mock_filings = Mock()
        mock_filings.__getitem__ = Mock(return_value=mock_filing)
        mock_filings.__len__ = Mock(return_value=1)
        mock_filings.empty = False

        mock_company = Mock()
        mock_company.get_filings.return_value = mock_filings

        with patch('edgar.Company', return_value=mock_company):
            result = _process_cik_prospectus(session, '0001314612')

        # Should succeed but do nothing
        assert result is True

    def test_process_cik_unmatched_class_ids(self, session, sample_filing_path):
        """Test filing with class_ids not in database."""
        from unittest.mock import Mock, patch
        from etf_pipeline.models import ETF, FeeExpense
        from etf_pipeline.parsers.prospectus import _process_cik_prospectus
        from datetime import date

        # Create ETF with different class_id than fixture
        etf = ETF(
            cik='0001314612',
            ticker='TEST',
            fund_name='Test', issuer_name='Test Issuer',
            class_id='C999999999',  # Not in fixture
        )
        session.add(etf)
        session.commit()

        # Read fixture HTML
        with open(sample_filing_path) as f:
            html_content = f.read()

        mock_filing = Mock()
        mock_filing.html.return_value = html_content
        mock_filing.filing_date = date(2022, 11, 3)
        mock_filing.document.url = 'https://www.sec.gov/test/filing.htm'

        mock_filings = Mock()
        mock_filings.__getitem__ = Mock(return_value=mock_filing)
        mock_filings.__len__ = Mock(return_value=1)
        mock_filings.empty = False

        mock_company = Mock()
        mock_company.get_filings.return_value = mock_filings

        with patch('edgar.Company', return_value=mock_company):
            result = _process_cik_prospectus(session, '0001314612')

        # Should succeed but not create any FeeExpense records
        assert result is True
        assert session.query(FeeExpense).count() == 0

    def test_process_cik_upsert_update_existing(self, session, sample_filing_path):
        """Test upsert updates existing records."""
        from unittest.mock import Mock, patch
        from etf_pipeline.models import ETF, FeeExpense
        from etf_pipeline.parsers.prospectus import _process_cik_prospectus
        from datetime import date

        # Create ETF record
        etf = ETF(
            cik='0001314612',
            ticker='TESTA',
            fund_name='Test', issuer_name='Test Issuer',
            class_id='C000014542',
        )
        session.add(etf)
        session.commit()

        # Create existing FeeExpense record with different values
        existing_fee = FeeExpense(
            etf_id=etf.id,
            effective_date=date(2022, 11, 3),
            filing_date=date(2022, 11, 3),
            management_fee=Decimal('0.0050'),  # Old value
            distribution_12b1=Decimal('0.0020'),  # Old value
        )
        session.add(existing_fee)
        session.commit()
        existing_id = existing_fee.id

        # Read fixture HTML
        with open(sample_filing_path) as f:
            html_content = f.read()

        mock_filing = Mock()
        mock_filing.html.return_value = html_content
        mock_filing.filing_date = date(2022, 11, 3)
        mock_filing.document.url = 'https://www.sec.gov/test/filing.htm'

        mock_filings = Mock()
        mock_filings.__getitem__ = Mock(return_value=mock_filing)
        mock_filings.__len__ = Mock(return_value=1)
        mock_filings.empty = False

        mock_company = Mock()
        mock_company.get_filings.return_value = mock_filings

        with patch('edgar.Company', return_value=mock_company):
            result = _process_cik_prospectus(session, '0001314612')

        assert result is True

        # Should update existing record, not create new one
        assert session.query(FeeExpense).count() == 1
        updated_fee = session.query(FeeExpense).filter_by(id=existing_id).one()
        assert updated_fee.management_fee == pytest.approx(Decimal('0.0070'))  # Updated
        assert updated_fee.distribution_12b1 == pytest.approx(Decimal('0.0025'))  # Updated


class TestIntegrationParseProspectus:
    """Integration tests for parse_prospectus() entry point."""

    def test_parse_prospectus_single_cik(self, session, sample_filing_path):
        """Test parse_prospectus with single CIK."""
        from unittest.mock import Mock, patch
        from etf_pipeline.models import ETF, FeeExpense
        from etf_pipeline.parsers.prospectus import parse_prospectus
        from datetime import date

        # Create ETF record
        etf = ETF(
            cik='0001314612',
            ticker='TESTA',
            fund_name='Test', issuer_name='Test Issuer',
            class_id='C000014542',
        )
        session.add(etf)
        session.commit()

        # Read fixture HTML
        with open(sample_filing_path) as f:
            html_content = f.read()

        mock_filing = Mock()
        mock_filing.html.return_value = html_content
        mock_filing.filing_date = date(2022, 11, 3)
        mock_filing.document.url = 'https://www.sec.gov/test/filing.htm'

        mock_filings = Mock()
        mock_filings.__getitem__ = Mock(return_value=mock_filing)
        mock_filings.__len__ = Mock(return_value=1)
        mock_filings.empty = False

        mock_company = Mock()
        mock_company.get_filings.return_value = mock_filings

        # Patch both Company and get_engine
        with patch('edgar.Company', return_value=mock_company):
            with patch('etf_pipeline.db.get_engine') as mock_get_engine:
                # Return the test session's engine
                mock_get_engine.return_value = session.bind

                # Mock clear_cache to avoid actual cache operations
                with patch('edgar.clear_cache') as mock_clear:
                    mock_clear.return_value = {'files_deleted': 0, 'bytes_freed': 0}

                    parse_prospectus(cik='1314612', limit=None, clear_cache=False)

        # Verify data was inserted
        fee = session.query(FeeExpense).filter_by(etf_id=etf.id).one()
        assert fee.management_fee == pytest.approx(Decimal('0.0070'))


class TestOEFNamespace:
    """Test OEF namespace support (oef: prefix instead of rr:)."""

    def test_parse_contexts_oef_class_axis(self, sample_filing_oef):
        """Test parsing contexts with OEF ClassAxis dimension."""
        context_map = parse_contexts(sample_filing_oef)

        # Class-level context should parse correctly with oef:ClassAxis
        context_id = "AsOf2022-11-03_custom_S000014796Member_custom_C000014542Member"
        assert context_id in context_map
        assert context_map[context_id]["cik"] == "0001314612"
        assert context_map[context_id]["series_id"] == "S000014796"
        assert context_map[context_id]["class_id"] == "C000014542"

    def test_extract_oef_management_fee(self, sample_filing_oef):
        """Test extracting management fee with oef: prefix."""
        context_id = "AsOf2022-11-03_custom_S000014796Member_custom_C000014542Member"
        value = extract_tag_value(sample_filing_oef, "oef:ManagementFeesOverAssets", context_id)

        assert value == Decimal('0.0070')

    def test_extract_oef_objective_text(self, sample_filing_oef):
        """Test extracting objective text with oef: prefix."""
        context_id = "AsOf2022-11-03_custom_S000014796Member"
        value = extract_tag_value(sample_filing_oef, "oef:ObjectivePrimaryTextBlock", context_id)

        assert isinstance(value, str)
        assert value == "The fund seeks long-term capital growth."

    def test_extract_oef_principal_risks_text(self, sample_filing_oef):
        """Test extracting principal risks text with oef: prefix and risk dimensions."""
        # Test individual risk blocks with risk-dimensioned contexts
        context_id = "AsOf2022-11-03_custom_S000014796Member_custom_RiskLoseMoneyMember"
        value = extract_tag_value(sample_filing_oef, "oef:RiskTextBlock", context_id)

        assert isinstance(value, str)
        assert "Risk of Loss" in value

        # Test another risk dimension
        context_id = "AsOf2022-11-03_custom_S000014796Member_custom_PerformanceRiskMember"
        value = extract_tag_value(sample_filing_oef, "oef:RiskTextBlock", context_id)

        assert isinstance(value, str)
        assert "Stock Market Volatility" in value

    def test_process_cik_oef_full_flow(self, session, sample_filing_oef_path):
        """Test full CIK processing flow with OEF namespace."""
        from unittest.mock import Mock, patch
        from etf_pipeline.models import ETF, FeeExpense
        from etf_pipeline.parsers.prospectus import _process_cik_prospectus
        from datetime import date

        # Create ETF records matching the fixture
        etf_a = ETF(
            cik='0001314612',
            ticker='TESTA',
            fund_name='Test Fund - Class A', issuer_name='Test Issuer',
            series_id='S000014796',
            class_id='C000014542',
        )
        etf_i = ETF(
            cik='0001314612',
            ticker='TESTI',
            fund_name='Test Fund - Class I', issuer_name='Test Issuer',
            series_id='S000014796',
            class_id='C000014546',
        )
        session.add_all([etf_a, etf_i])
        session.commit()
        etf_a_id = etf_a.id
        etf_i_id = etf_i.id

        # Read fixture HTML
        with open(sample_filing_oef_path) as f:
            html_content = f.read()

        # Mock edgartools objects
        mock_filing = Mock()
        mock_filing.html.return_value = html_content
        mock_filing.filing_date = date(2022, 11, 3)
        mock_filing.document.url = 'https://www.sec.gov/test/filing.htm'

        mock_filings = Mock()
        mock_filings.__getitem__ = Mock(return_value=mock_filing)
        mock_filings.__len__ = Mock(return_value=1)
        mock_filings.empty = False

        mock_company = Mock()
        mock_company.get_filings.return_value = mock_filings

        # Patch Company class
        with patch('edgar.Company', return_value=mock_company):
            result = _process_cik_prospectus(session, '0001314612')

        assert result is True

        # Verify FeeExpense data for Class A (should work identically to RR namespace)
        fee_a = session.query(FeeExpense).filter_by(etf_id=etf_a_id).one()
        assert fee_a.management_fee == pytest.approx(Decimal('0.0070'))
        assert fee_a.distribution_12b1 == pytest.approx(Decimal('0.0025'))
        assert fee_a.other_expenses == pytest.approx(Decimal('0.0030'))
        assert fee_a.total_expense_gross == pytest.approx(Decimal('0.0125'))
        assert fee_a.fee_waiver == pytest.approx(Decimal('0.0010'))
        assert fee_a.total_expense_net == pytest.approx(Decimal('0.0115'))
        assert fee_a.fee_waiver_expiration_date == date(2024, 12, 31)
        assert fee_a.effective_date == date(2022, 11, 3)

        # Verify FeeExpense data for Class I
        fee_i = session.query(FeeExpense).filter_by(etf_id=etf_i_id).one()
        assert fee_i.management_fee == pytest.approx(Decimal('0.0070'))
        assert fee_i.distribution_12b1 == Decimal('0')  # zerodash

        # Verify narrative text
        from etf_pipeline.models import ETF as ETFModel
        etf_a_refreshed = session.get(ETFModel, etf_a_id)
        etf_i_refreshed = session.get(ETFModel, etf_i_id)
        assert etf_a_refreshed.objective_text == 'The fund seeks long-term capital growth.'
        assert etf_a_refreshed.strategy_text == 'The fund invests primarily in common stocks of large U.S. companies.'
        # Verify all three risk blocks are concatenated with double newlines
        expected_risks = (
            'Risk of Loss. It is important to understand that you can lose money by investing in the fund.\n\n'
            'Stock Market Volatility. Stock markets are volatile and can decline significantly in response to adverse issuer, political, regulatory, market, or economic developments.\n\n'
            'Foreign Exposure. Foreign markets can be more volatile than the U.S. market due to increased risks of adverse issuer, political, regulatory, market, or economic developments.'
        )
        assert etf_a_refreshed.principal_risks == expected_risks
        assert etf_i_refreshed.objective_text == 'The fund seeks long-term capital growth.'
        assert etf_i_refreshed.strategy_text == 'The fund invests primarily in common stocks of large U.S. companies.'
        assert etf_i_refreshed.principal_risks == expected_risks


class TestProspectusProcessingLog:
    """Tests for ProcessingLog and filing_date in prospectus parser."""

    def test_parse_prospectus_writes_processing_log(self, session, sample_filing_path):
        """Test that prospectus parser writes ProcessingLog row."""
        from unittest.mock import Mock, patch
        from etf_pipeline.models import ETF, ProcessingLog
        from etf_pipeline.parsers.prospectus import _process_cik_prospectus
        from datetime import date

        # Create ETF record
        etf = ETF(
            cik='0001314612',
            ticker='TESTA',
            fund_name='Test Fund - Class A', issuer_name='Test Issuer',
            series_id='S000014796',
            class_id='C000014542',
        )
        session.add(etf)
        session.commit()

        # Read fixture HTML
        with open(sample_filing_path) as f:
            html_content = f.read()

        # Mock edgartools objects
        mock_filing = Mock()
        mock_filing.html.return_value = html_content
        mock_filing.filing_date = date(2022, 11, 3)
        mock_filing.document.url = 'https://www.sec.gov/test/filing.htm'

        mock_filings = Mock()
        mock_filings.__getitem__ = Mock(return_value=mock_filing)
        mock_filings.__len__ = Mock(return_value=1)
        mock_filings.empty = False

        mock_company = Mock()
        mock_company.get_filings.return_value = mock_filings

        with patch('edgar.Company', return_value=mock_company):
            result = _process_cik_prospectus(session, '0001314612')

        assert result is True

        # Verify ProcessingLog was created
        from sqlalchemy import select
        stmt = select(ProcessingLog).where(
            ProcessingLog.cik == "0001314612",
            ProcessingLog.parser_type == "prospectus"
        )
        log = session.execute(stmt).scalar_one_or_none()

        assert log is not None
        assert log.cik == "0001314612"
        assert log.parser_type == "prospectus"
        assert log.latest_filing_date_seen == date(2022, 11, 3)
        assert log.last_run_at is not None

    def test_parse_prospectus_sets_filing_date(self, session, sample_filing_path):
        """Test that prospectus parser sets filing_date on inserted rows."""
        from unittest.mock import Mock, patch
        from etf_pipeline.models import ETF, FeeExpense
        from etf_pipeline.parsers.prospectus import _process_cik_prospectus
        from datetime import date
        from sqlalchemy import select

        # Create ETF record
        etf = ETF(
            cik='0001314612',
            ticker='TESTA',
            fund_name='Test Fund - Class A', issuer_name='Test Issuer',
            series_id='S000014796',
            class_id='C000014542',
        )
        session.add(etf)
        session.commit()
        etf_id = etf.id

        # Read fixture HTML
        with open(sample_filing_path) as f:
            html_content = f.read()

        # Mock edgartools objects
        mock_filing = Mock()
        mock_filing.html.return_value = html_content
        mock_filing.filing_date = date(2022, 11, 3)
        mock_filing.document.url = 'https://www.sec.gov/test/filing.htm'

        mock_filings = Mock()
        mock_filings.__getitem__ = Mock(return_value=mock_filing)
        mock_filings.__len__ = Mock(return_value=1)
        mock_filings.empty = False

        mock_company = Mock()
        mock_company.get_filings.return_value = mock_filings

        with patch('edgar.Company', return_value=mock_company):
            result = _process_cik_prospectus(session, '0001314612')

        assert result is True

        # Verify FeeExpense has filing_date
        stmt = select(FeeExpense).where(FeeExpense.etf_id == etf_id)
        fee_expense = session.execute(stmt).scalar_one()
        assert fee_expense.filing_date == date(2022, 11, 3)


class TestFeeExpenseNetFallback:
    """Tests for total_expense_net fallback logic."""

    def test_net_expense_fallback_no_waiver(self, session):
        """Test that total_expense_net = total_expense_gross when NetExpensesOverAssets tag is missing and no fee_waiver."""
        from unittest.mock import Mock, patch
        from etf_pipeline.models import ETF, FeeExpense
        from etf_pipeline.parsers.prospectus import _process_cik_prospectus
        from datetime import date

        # Create ETF record
        etf = ETF(
            cik='0001314612',
            ticker='TESTFALLBACK',
            fund_name='Test Fallback Fund',
            issuer_name='Test Issuer',
            series_id='S000099999',
            class_id='C000099999',
        )
        session.add(etf)
        session.commit()
        etf_id = etf.id

        # HTML with ExpensesOverAssets but NO NetExpensesOverAssets tag and no fee waiver
        html_no_net = """
        <html>
        <ix:resources>
            <xbrli:context id="AsOf2022-11-03">
                <xbrli:entity>
                    <xbrli:identifier>0001314612</xbrli:identifier>
                </xbrli:entity>
            </xbrli:context>
            <xbrli:context id="AsOf2022-11-03_custom_S000099999Member_custom_C000099999Member">
                <xbrli:entity>
                    <xbrli:identifier>0001314612</xbrli:identifier>
                    <xbrli:segment>
                        <xbrldi:explicitmember dimension="dei:LegalEntityAxis">rr:S000099999Member</xbrldi:explicitmember>
                        <xbrldi:explicitmember dimension="rr:ProspectusShareClassAxis">rr:C000099999Member</xbrldi:explicitmember>
                    </xbrli:segment>
                </xbrli:entity>
            </xbrli:context>
        </ix:resources>
        <body>
            <ix:nonfraction name="dei:DocumentPeriodEndDate" contextref="AsOf2022-11-03">2022-11-03</ix:nonfraction>
            <ix:nonfraction name="rr:ManagementFeesOverAssets" contextref="AsOf2022-11-03_custom_S000099999Member_custom_C000099999Member" scale="-2">0.50</ix:nonfraction>
            <ix:nonfraction name="rr:ExpensesOverAssets" contextref="AsOf2022-11-03_custom_S000099999Member_custom_C000099999Member" scale="-2">0.75</ix:nonfraction>
        </body>
        </html>
        """

        mock_filing = Mock()
        mock_filing.html.return_value = html_no_net
        mock_filing.filing_date = date(2022, 11, 3)
        mock_filing.document.url = 'https://www.sec.gov/test/filing.htm'

        mock_filings = Mock()
        mock_filings.__getitem__ = Mock(return_value=mock_filing)
        mock_filings.__len__ = Mock(return_value=1)
        mock_filings.empty = False

        mock_company = Mock()
        mock_company.get_filings.return_value = mock_filings

        with patch('edgar.Company', return_value=mock_company):
            result = _process_cik_prospectus(session, '0001314612')

        assert result is True

        # Verify total_expense_net was set to total_expense_gross (0.0075)
        fee = session.query(FeeExpense).filter_by(etf_id=etf_id).one()
        assert fee.total_expense_gross == pytest.approx(Decimal('0.0075'))
        assert fee.total_expense_net == pytest.approx(Decimal('0.0075'))  # Fallback: net = gross
        assert fee.fee_waiver is None

    def test_net_expense_fallback_with_waiver(self, session):
        """Test that total_expense_net = total_expense_gross - fee_waiver when NetExpensesOverAssets tag is missing."""
        from unittest.mock import Mock, patch
        from etf_pipeline.models import ETF, FeeExpense
        from etf_pipeline.parsers.prospectus import _process_cik_prospectus
        from datetime import date

        # Create ETF record
        etf = ETF(
            cik='0001314612',
            ticker='TESTWAIVER',
            fund_name='Test Waiver Fund',
            issuer_name='Test Issuer',
            series_id='S000099998',
            class_id='C000099998',
        )
        session.add(etf)
        session.commit()
        etf_id = etf.id

        # HTML with ExpensesOverAssets, FeeWaiverOrReimbursementOverAssets, but NO NetExpensesOverAssets tag
        html_with_waiver = """
        <html>
        <ix:resources>
            <xbrli:context id="AsOf2022-11-03">
                <xbrli:entity>
                    <xbrli:identifier>0001314612</xbrli:identifier>
                </xbrli:entity>
            </xbrli:context>
            <xbrli:context id="AsOf2022-11-03_custom_S000099998Member_custom_C000099998Member">
                <xbrli:entity>
                    <xbrli:identifier>0001314612</xbrli:identifier>
                    <xbrli:segment>
                        <xbrldi:explicitmember dimension="dei:LegalEntityAxis">rr:S000099998Member</xbrldi:explicitmember>
                        <xbrldi:explicitmember dimension="rr:ProspectusShareClassAxis">rr:C000099998Member</xbrldi:explicitmember>
                    </xbrli:segment>
                </xbrli:entity>
            </xbrli:context>
        </ix:resources>
        <body>
            <ix:nonfraction name="dei:DocumentPeriodEndDate" contextref="AsOf2022-11-03">2022-11-03</ix:nonfraction>
            <ix:nonfraction name="rr:ManagementFeesOverAssets" contextref="AsOf2022-11-03_custom_S000099998Member_custom_C000099998Member" scale="-2">0.60</ix:nonfraction>
            <ix:nonfraction name="rr:ExpensesOverAssets" contextref="AsOf2022-11-03_custom_S000099998Member_custom_C000099998Member" scale="-2">0.80</ix:nonfraction>
            <ix:nonfraction name="rr:FeeWaiverOrReimbursementOverAssets" contextref="AsOf2022-11-03_custom_S000099998Member_custom_C000099998Member" scale="-2" sign="-">0.10</ix:nonfraction>
        </body>
        </html>
        """

        mock_filing = Mock()
        mock_filing.html.return_value = html_with_waiver
        mock_filing.filing_date = date(2022, 11, 3)
        mock_filing.document.url = 'https://www.sec.gov/test/filing.htm'

        mock_filings = Mock()
        mock_filings.__getitem__ = Mock(return_value=mock_filing)
        mock_filings.__len__ = Mock(return_value=1)
        mock_filings.empty = False

        mock_company = Mock()
        mock_company.get_filings.return_value = mock_filings

        with patch('edgar.Company', return_value=mock_company):
            result = _process_cik_prospectus(session, '0001314612')

        assert result is True

        # Verify total_expense_net = gross - waiver (0.0080 - 0.0010 = 0.0070)
        fee = session.query(FeeExpense).filter_by(etf_id=etf_id).one()
        assert fee.total_expense_gross == pytest.approx(Decimal('0.0080'))
        assert fee.fee_waiver == pytest.approx(Decimal('0.0010'))
        assert fee.total_expense_net == pytest.approx(Decimal('0.0070'))  # Fallback: net = gross - waiver

    def test_net_expense_preserved_when_present(self, session, sample_filing_path):
        """Test that total_expense_net is preserved when NetExpensesOverAssets tag exists."""
        from unittest.mock import Mock, patch
        from etf_pipeline.models import ETF, FeeExpense
        from etf_pipeline.parsers.prospectus import _process_cik_prospectus
        from datetime import date

        # Create ETF record matching the fixture (which has NetExpensesOverAssets)
        etf = ETF(
            cik='0001314612',
            ticker='TESTA',
            fund_name='Test Fund - Class A',
            issuer_name='Test Issuer',
            series_id='S000014796',
            class_id='C000014542',
        )
        session.add(etf)
        session.commit()
        etf_id = etf.id

        # Read fixture HTML (contains NetExpensesOverAssets tag)
        with open(sample_filing_path) as f:
            html_content = f.read()

        mock_filing = Mock()
        mock_filing.html.return_value = html_content
        mock_filing.filing_date = date(2022, 11, 3)
        mock_filing.document.url = 'https://www.sec.gov/test/filing.htm'

        mock_filings = Mock()
        mock_filings.__getitem__ = Mock(return_value=mock_filing)
        mock_filings.__len__ = Mock(return_value=1)
        mock_filings.empty = False

        mock_company = Mock()
        mock_company.get_filings.return_value = mock_filings

        with patch('edgar.Company', return_value=mock_company):
            result = _process_cik_prospectus(session, '0001314612')

        assert result is True

        # Verify total_expense_net preserved from tag (not recalculated)
        fee = session.query(FeeExpense).filter_by(etf_id=etf_id).one()
        assert fee.total_expense_gross == pytest.approx(Decimal('0.0125'))
        assert fee.fee_waiver == pytest.approx(Decimal('0.0010'))
        assert fee.total_expense_net == pytest.approx(Decimal('0.0115'))  # From tag, not gross - waiver

    def test_net_expense_fallback_zero_waiver(self, session):
        """Test that total_expense_net = total_expense_gross when fee_waiver is zero."""
        from unittest.mock import Mock, patch
        from etf_pipeline.models import ETF, FeeExpense
        from etf_pipeline.parsers.prospectus import _process_cik_prospectus
        from datetime import date

        # Create ETF record
        etf = ETF(
            cik='0001314612',
            ticker='TESTZERO',
            fund_name='Test Zero Waiver Fund',
            issuer_name='Test Issuer',
            series_id='S000099997',
            class_id='C000099997',
        )
        session.add(etf)
        session.commit()
        etf_id = etf.id

        # HTML with ExpensesOverAssets and zero fee_waiver (zerodash)
        html_zero_waiver = """
        <html>
        <ix:resources>
            <xbrli:context id="AsOf2022-11-03">
                <xbrli:entity>
                    <xbrli:identifier>0001314612</xbrli:identifier>
                </xbrli:entity>
            </xbrli:context>
            <xbrli:context id="AsOf2022-11-03_custom_S000099997Member_custom_C000099997Member">
                <xbrli:entity>
                    <xbrli:identifier>0001314612</xbrli:identifier>
                    <xbrli:segment>
                        <xbrldi:explicitmember dimension="dei:LegalEntityAxis">rr:S000099997Member</xbrldi:explicitmember>
                        <xbrldi:explicitmember dimension="rr:ProspectusShareClassAxis">rr:C000099997Member</xbrldi:explicitmember>
                    </xbrli:segment>
                </xbrli:entity>
            </xbrli:context>
        </ix:resources>
        <body>
            <ix:nonfraction name="dei:DocumentPeriodEndDate" contextref="AsOf2022-11-03">2022-11-03</ix:nonfraction>
            <ix:nonfraction name="rr:ManagementFeesOverAssets" contextref="AsOf2022-11-03_custom_S000099997Member_custom_C000099997Member" scale="-2">0.65</ix:nonfraction>
            <ix:nonfraction name="rr:ExpensesOverAssets" contextref="AsOf2022-11-03_custom_S000099997Member_custom_C000099997Member" scale="-2">0.85</ix:nonfraction>
            <ix:nonfraction name="rr:FeeWaiverOrReimbursementOverAssets" contextref="AsOf2022-11-03_custom_S000099997Member_custom_C000099997Member" format="ixt:zerodash" scale="-2">—</ix:nonfraction>
        </body>
        </html>
        """

        mock_filing = Mock()
        mock_filing.html.return_value = html_zero_waiver
        mock_filing.filing_date = date(2022, 11, 3)
        mock_filing.document.url = 'https://www.sec.gov/test/filing.htm'

        mock_filings = Mock()
        mock_filings.__getitem__ = Mock(return_value=mock_filing)
        mock_filings.__len__ = Mock(return_value=1)
        mock_filings.empty = False

        mock_company = Mock()
        mock_company.get_filings.return_value = mock_filings

        with patch('edgar.Company', return_value=mock_company):
            result = _process_cik_prospectus(session, '0001314612')

        assert result is True

        # Verify total_expense_net = gross when waiver is zero
        fee = session.query(FeeExpense).filter_by(etf_id=etf_id).one()
        assert fee.total_expense_gross == pytest.approx(Decimal('0.0085'))
        assert fee.fee_waiver == Decimal('0')  # zerodash
        assert fee.total_expense_net == pytest.approx(Decimal('0.0085'))  # Fallback: net = gross (waiver is 0)


class TestParseHtmlFeeValue:
    """Unit tests for _parse_html_fee_value()."""

    def test_basic_percentage(self):
        assert _parse_html_fee_value('0.70%') == Decimal('0.0070')

    def test_no_percent_sign(self):
        assert _parse_html_fee_value('0.70') == Decimal('0.0070')

    def test_zero_value(self):
        assert _parse_html_fee_value('0.00%') == Decimal('0.0000')

    def test_parentheses_negative(self):
        # Parentheses = negative in financial tables, absolute taken
        assert _parse_html_fee_value('(0.10)%') == Decimal('0.0010')

    def test_dash_returns_none(self):
        assert _parse_html_fee_value('—') is None
        assert _parse_html_fee_value('-') is None

    def test_none_text_returns_none(self):
        assert _parse_html_fee_value('None') is None
        assert _parse_html_fee_value('none') is None

    def test_empty_string_returns_none(self):
        assert _parse_html_fee_value('') is None
        assert _parse_html_fee_value('   ') is None

    def test_whitespace_stripped(self):
        assert _parse_html_fee_value('  0.25%  ') == Decimal('0.0025')

    def test_large_percentage(self):
        assert _parse_html_fee_value('1.30%') == Decimal('0.0130')


class TestMatchFeeRowLabel:
    """Unit tests for _match_fee_row_label()."""

    def test_management_fees(self):
        assert _match_fee_row_label('Management Fees') == 'management_fee'
        assert _match_fee_row_label('management fees') == 'management_fee'

    def test_distribution_12b1(self):
        assert _match_fee_row_label('Distribution and/or Service (12b-1) Fees') == 'distribution_12b1'
        assert _match_fee_row_label('Distribution and Service (12b-1) Fees') == 'distribution_12b1'

    def test_other_expenses(self):
        assert _match_fee_row_label('Other Expenses') == 'other_expenses'

    def test_acquired_fund_fees(self):
        assert _match_fee_row_label('Acquired Fund Fees and Expenses') == 'acquired_fund_fees'

    def test_total_expense_gross(self):
        assert _match_fee_row_label('Total Annual Fund Operating Expenses') == 'total_expense_gross'

    def test_total_expense_net(self):
        assert _match_fee_row_label('Total Annual Fund Operating Expenses After Fee Waiver') == 'total_expense_net'
        assert _match_fee_row_label('Net Expenses') == 'total_expense_net'

    def test_fee_waiver(self):
        assert _match_fee_row_label('Fee Waiver or Reimbursement') == 'fee_waiver'
        assert _match_fee_row_label('Fee Waiver') == 'fee_waiver'
        assert _match_fee_row_label('Expense Reimbursement') == 'fee_waiver'

    def test_unmatched_label(self):
        assert _match_fee_row_label('Some Unrelated Row') is None
        assert _match_fee_row_label('') is None


class TestExtractFeesFromHtmlTable:
    """Tests for _extract_fees_from_html_table()."""

    HTML_ONE_CLASS = """
    <html><body>
    <h3>Class A (C000014542)</h3>
    <table>
      <tr><td>Management Fees</td><td>0.70%</td></tr>
      <tr><td>Distribution and/or Service (12b-1) Fees</td><td>0.25%</td></tr>
      <tr><td>Other Expenses</td><td>0.30%</td></tr>
      <tr><td>Total Annual Fund Operating Expenses</td><td>1.30%</td></tr>
      <tr><td>Fee Waiver or Reimbursement</td><td>(0.10)%</td></tr>
      <tr><td>Total Annual Fund Operating Expenses After Fee Waiver</td><td>1.20%</td></tr>
    </table>
    </body></html>
    """

    HTML_NO_MANAGEMENT_FEES = """
    <html><body>
    <table>
      <tr><td>Some Random Row</td><td>1.00%</td></tr>
    </table>
    </body></html>
    """

    HTML_NO_CLASS_ID = """
    <html><body>
    <h3>Annual Fund Operating Expenses</h3>
    <table>
      <tr><td>Management Fees</td><td>0.50%</td></tr>
      <tr><td>Total Annual Fund Operating Expenses</td><td>0.50%</td></tr>
    </table>
    </body></html>
    """

    def _make_session_with_etf(self, session, class_id='C000014542', series_id='S000014796', ticker='TESTA'):
        from etf_pipeline.models import ETF
        etf = ETF(
            cik='0001314612', ticker=ticker,
            fund_name='Test Fund', issuer_name='Test Issuer',
            series_id=series_id, class_id=class_id,
        )
        session.add(etf)
        session.commit()
        return etf

    def test_extracts_fees_single_class(self, session):
        from datetime import date
        from etf_pipeline.models import FeeExpense
        etf = self._make_session_with_etf(session)
        soup = BeautifulSoup(self.HTML_ONE_CLASS, 'lxml')
        class_id_to_etf = {etf.class_id: etf}
        series_id_to_etfs = {etf.series_id: [etf]}
        filing_date = date(2022, 11, 3)

        matched = _extract_fees_from_html_table(
            soup, session, class_id_to_etf, series_id_to_etfs, None, filing_date, '0001314612'
        )

        assert len(matched) == 1
        fee = session.query(FeeExpense).filter_by(etf_id=etf.id).one()
        assert fee.management_fee == pytest.approx(Decimal('0.0070'))
        assert fee.distribution_12b1 == pytest.approx(Decimal('0.0025'))
        assert fee.other_expenses == pytest.approx(Decimal('0.0030'))
        assert fee.total_expense_gross == pytest.approx(Decimal('0.0130'))
        assert fee.fee_waiver == pytest.approx(Decimal('0.0010'))
        assert fee.total_expense_net == pytest.approx(Decimal('0.0120'))

    def test_uses_filing_date_when_no_effective_date(self, session):
        from datetime import date
        from etf_pipeline.models import FeeExpense
        etf = self._make_session_with_etf(session)
        soup = BeautifulSoup(self.HTML_ONE_CLASS, 'lxml')
        class_id_to_etf = {etf.class_id: etf}
        series_id_to_etfs = {etf.series_id: [etf]}
        filing_date = date(2023, 5, 10)

        _extract_fees_from_html_table(
            soup, session, class_id_to_etf, series_id_to_etfs, None, filing_date, '0001314612'
        )

        fee = session.query(FeeExpense).filter_by(etf_id=etf.id).one()
        assert fee.effective_date == filing_date
        assert fee.filing_date == filing_date

    def test_uses_provided_effective_date(self, session):
        from datetime import date
        from etf_pipeline.models import FeeExpense
        etf = self._make_session_with_etf(session)
        soup = BeautifulSoup(self.HTML_ONE_CLASS, 'lxml')
        class_id_to_etf = {etf.class_id: etf}
        series_id_to_etfs = {etf.series_id: [etf]}
        effective_date = date(2022, 10, 31)
        filing_date = date(2022, 11, 3)

        _extract_fees_from_html_table(
            soup, session, class_id_to_etf, series_id_to_etfs, effective_date, filing_date, '0001314612'
        )

        fee = session.query(FeeExpense).filter_by(etf_id=etf.id).one()
        assert fee.effective_date == effective_date

    def test_no_fee_table_returns_zero(self, session):
        from datetime import date
        etf = self._make_session_with_etf(session)
        soup = BeautifulSoup(self.HTML_NO_MANAGEMENT_FEES, 'lxml')
        class_id_to_etf = {etf.class_id: etf}
        series_id_to_etfs = {etf.series_id: [etf]}

        matched = _extract_fees_from_html_table(
            soup, session, class_id_to_etf, series_id_to_etfs, None, date(2022, 11, 3), '0001314612'
        )
        assert len(matched) == 0

    def test_single_etf_used_when_no_class_id_in_html(self, session):
        from datetime import date
        from etf_pipeline.models import FeeExpense
        etf = self._make_session_with_etf(session, class_id='C000099001', series_id='S000099001', ticker='SINGLE')
        soup = BeautifulSoup(self.HTML_NO_CLASS_ID, 'lxml')
        class_id_to_etf = {etf.class_id: etf}
        series_id_to_etfs = {etf.series_id: [etf]}

        matched = _extract_fees_from_html_table(
            soup, session, class_id_to_etf, series_id_to_etfs, None, date(2022, 11, 3), '0001314612'
        )
        assert len(matched) == 1
        fee = session.query(FeeExpense).filter_by(etf_id=etf.id).one()
        assert fee.management_fee == pytest.approx(Decimal('0.0050'))

    def test_net_expense_fallback_no_waiver(self, session):
        from datetime import date
        from etf_pipeline.models import FeeExpense
        html = """
        <html><body>
        <h3>Fund (C000099002)</h3>
        <table>
          <tr><td>Management Fees</td><td>0.40%</td></tr>
          <tr><td>Total Annual Fund Operating Expenses</td><td>0.40%</td></tr>
        </table>
        </body></html>
        """
        etf = self._make_session_with_etf(session, class_id='C000099002', series_id='S000099002', ticker='NETNOW')
        soup = BeautifulSoup(html, 'lxml')
        class_id_to_etf = {etf.class_id: etf}
        series_id_to_etfs = {etf.series_id: [etf]}

        _extract_fees_from_html_table(
            soup, session, class_id_to_etf, series_id_to_etfs, None, date(2022, 11, 3), '0001314612'
        )

        fee = session.query(FeeExpense).filter_by(etf_id=etf.id).one()
        assert fee.total_expense_gross == pytest.approx(Decimal('0.0040'))
        assert fee.total_expense_net == pytest.approx(Decimal('0.0040'))  # fallback: net = gross


class TestFeeValueSanityCheck:
    """Tests for the fee value sanity check (> 0.50 correction)."""

    def test_sanity_check_corrects_unscaled_ixbrl_value(self, session):
        from unittest.mock import Mock, patch
        from etf_pipeline.models import ETF, FeeExpense
        from etf_pipeline.parsers.prospectus import _process_cik_prospectus
        from datetime import date

        etf = ETF(
            cik='0001314612', ticker='SANITY',
            fund_name='Sanity Fund', issuer_name='Test Issuer',
            series_id='S000088001', class_id='C000088001',
        )
        session.add(etf)
        session.commit()
        etf_id = etf.id

        # Filer wrote "0.99" meaning 0.99% but omitted scale="-2"
        # Without the sanity check this would be stored as 0.99 (= 99%)
        html_missing_scale = """
        <html>
        <ix:resources>
            <xbrli:context id="AsOf2022-11-03">
                <xbrli:entity><xbrli:identifier>0001314612</xbrli:identifier></xbrli:entity>
            </xbrli:context>
            <xbrli:context id="AsOf2022-11-03_custom_S000088001Member_custom_C000088001Member">
                <xbrli:entity>
                    <xbrli:identifier>0001314612</xbrli:identifier>
                    <xbrli:segment>
                        <xbrldi:explicitmember dimension="dei:LegalEntityAxis">rr:S000088001Member</xbrldi:explicitmember>
                        <xbrldi:explicitmember dimension="rr:ProspectusShareClassAxis">rr:C000088001Member</xbrldi:explicitmember>
                    </xbrli:segment>
                </xbrli:entity>
            </xbrli:context>
        </ix:resources>
        <body>
            <ix:nonfraction name="dei:DocumentPeriodEndDate" contextref="AsOf2022-11-03">2022-11-03</ix:nonfraction>
            <ix:nonfraction name="rr:ManagementFeesOverAssets" contextref="AsOf2022-11-03_custom_S000088001Member_custom_C000088001Member">0.99</ix:nonfraction>
        </body>
        </html>
        """

        mock_filing = Mock()
        mock_filing.html.return_value = html_missing_scale
        mock_filing.filing_date = date(2022, 11, 3)
        mock_filing.document.url = 'https://www.sec.gov/test/filing.htm'

        mock_filings = Mock()
        mock_filings.__getitem__ = Mock(return_value=mock_filing)
        mock_filings.__len__ = Mock(return_value=1)
        mock_filings.empty = False

        mock_company = Mock()
        mock_company.get_filings.return_value = mock_filings

        with patch('edgar.Company', return_value=mock_company):
            result = _process_cik_prospectus(session, '0001314612')

        assert result is True
        fee = session.query(FeeExpense).filter_by(etf_id=etf_id).one()
        # 0.99 > 0.50 so sanity check applies ÷100 → 0.0099
        assert fee.management_fee == pytest.approx(Decimal('0.0099'))

    def test_sanity_check_does_not_affect_normal_scaled_values(self, session, sample_filing_path):
        from unittest.mock import Mock, patch
        from etf_pipeline.models import ETF, FeeExpense
        from etf_pipeline.parsers.prospectus import _process_cik_prospectus
        from datetime import date

        etf = ETF(
            cik='0001314612', ticker='NORMAL',
            fund_name='Normal Fund', issuer_name='Test Issuer',
            series_id='S000014796', class_id='C000014542',
        )
        session.add(etf)
        session.commit()
        etf_id = etf.id

        with open(sample_filing_path) as f:
            html_content = f.read()

        mock_filing = Mock()
        mock_filing.html.return_value = html_content
        mock_filing.filing_date = date(2022, 11, 3)
        mock_filing.document.url = 'https://www.sec.gov/test/filing.htm'

        mock_filings = Mock()
        mock_filings.__getitem__ = Mock(return_value=mock_filing)
        mock_filings.__len__ = Mock(return_value=1)
        mock_filings.empty = False

        mock_company = Mock()
        mock_company.get_filings.return_value = mock_filings

        with patch('edgar.Company', return_value=mock_company):
            result = _process_cik_prospectus(session, '0001314612')

        assert result is True
        fee = session.query(FeeExpense).filter_by(etf_id=etf_id).one()
        # Values from fixture are correctly scaled (all < 0.50) — sanity check must not alter them
        assert fee.management_fee == pytest.approx(Decimal('0.0070'))
        assert fee.total_expense_gross == pytest.approx(Decimal('0.0125'))
        assert fee.total_expense_net == pytest.approx(Decimal('0.0115'))

    def test_html_fallback_sanity_check(self, session):
        from datetime import date
        from etf_pipeline.models import FeeExpense
        # If a value parsed from HTML somehow exceeds 0.50 (shouldn't happen with _parse_html_fee_value
        # but the sanity check still protects against edge cases)
        etf_class_id = 'C000088002'
        from etf_pipeline.models import ETF
        etf = ETF(
            cik='0001314612', ticker='HTMLSANITY',
            fund_name='HTML Sanity Fund', issuer_name='Test Issuer',
            series_id='S000088002', class_id=etf_class_id,
        )
        session.add(etf)
        session.commit()

        # Build a soup that calls _extract_fees_from_html_table directly with a
        # value just above 0.50 to trigger the sanity check path
        # (Simulating a table cell that has "51%" which _parse_html_fee_value returns as 0.51)
        html = f"""
        <html><body>
        <h3>Fund ({etf_class_id})</h3>
        <table>
          <tr><td>Management Fees</td><td>51%</td></tr>
          <tr><td>Total Annual Fund Operating Expenses</td><td>51%</td></tr>
        </table>
        </body></html>
        """
        soup = BeautifulSoup(html, 'lxml')
        class_id_to_etf = {etf.class_id: etf}
        series_id_to_etfs = {etf.series_id: [etf]}

        matched = _extract_fees_from_html_table(
            soup, session, class_id_to_etf, series_id_to_etfs, None, date(2022, 11, 3), '0001314612'
        )
        assert len(matched) == 1
        fee = session.query(FeeExpense).filter_by(etf_id=etf.id).one()
        # 51% → _parse_html_fee_value returns 0.51 → sanity check corrects to 0.0051
        assert fee.management_fee == pytest.approx(Decimal('0.0051'))


class TestHtmlFallbackIntegration:
    """Integration tests for HTML fallback path through _process_cik_prospectus."""

    def test_html_fallback_fires_when_no_ixbrl_tags(self, session):
        from unittest.mock import Mock, patch
        from etf_pipeline.models import ETF, FeeExpense
        from etf_pipeline.parsers.prospectus import _process_cik_prospectus
        from datetime import date

        etf = ETF(
            cik='0001314612', ticker='HTMLFALL',
            fund_name='HTML Fallback Fund', issuer_name='Test Issuer',
            series_id='S000099010', class_id='C000099010',
        )
        session.add(etf)
        session.commit()
        etf_id = etf.id

        # Plain HTML with no ix: tags but with a fee table
        html_plain = """
        <html><body>
        <h3>Fund (C000099010)</h3>
        <table>
          <tr><td>Management Fees</td><td>0.45%</td></tr>
          <tr><td>Other Expenses</td><td>0.10%</td></tr>
          <tr><td>Total Annual Fund Operating Expenses</td><td>0.55%</td></tr>
        </table>
        </body></html>
        """

        mock_filing = Mock()
        mock_filing.html.return_value = html_plain
        mock_filing.filing_date = date(2022, 11, 3)
        mock_filing.document.url = 'https://www.sec.gov/test/filing.htm'

        mock_filings = Mock()
        mock_filings.__getitem__ = Mock(return_value=mock_filing)
        mock_filings.__len__ = Mock(return_value=1)
        mock_filings.empty = False

        mock_company = Mock()
        mock_company.get_filings.return_value = mock_filings

        with patch('edgar.Company', return_value=mock_company):
            result = _process_cik_prospectus(session, '0001314612')

        assert result is True
        fee = session.query(FeeExpense).filter_by(etf_id=etf_id).one()
        assert fee.management_fee == pytest.approx(Decimal('0.0045'))
        assert fee.other_expenses == pytest.approx(Decimal('0.0010'))
        assert fee.total_expense_gross == pytest.approx(Decimal('0.0055'))
        assert fee.total_expense_net == pytest.approx(Decimal('0.0055'))  # fallback: net=gross
        assert fee.effective_date == date(2022, 11, 3)  # uses filing_date as fallback
        assert fee.filing_date == date(2022, 11, 3)


class TestParseContextsPerformanceMeasure:
    """Test that parse_contexts captures PerformanceMeasureAxis and period dates."""

    def test_performance_measure_extracted(self):
        """Test that PerformanceMeasureAxis member is extracted from context segment."""
        html = """
        <html>
        <ix:resources>
          <xbrli:context id="ctx_fund_benchmark">
            <xbrli:entity>
              <xbrli:identifier scheme="http://www.sec.gov/CIK">0001314612</xbrli:identifier>
              <xbrli:segment>
                <xbrldi:explicitMember dimension="dei:LegalEntityAxis">rr01:S000014796Member</xbrldi:explicitMember>
                <xbrldi:explicitMember dimension="rr:ProspectusShareClassAxis">rr01:C000014542Member</xbrldi:explicitMember>
                <xbrldi:explicitMember dimension="rr:PerformanceMeasureAxis">rr01:SP500IndexMember</xbrldi:explicitMember>
              </xbrli:segment>
            </xbrli:entity>
            <xbrli:period>
              <xbrli:startDate>2021-11-03</xbrli:startDate>
              <xbrli:endDate>2022-11-03</xbrli:endDate>
            </xbrli:period>
          </xbrli:context>
        </ix:resources>
        </html>
        """
        soup = BeautifulSoup(html, 'lxml')
        context_map = parse_contexts(soup)

        assert "ctx_fund_benchmark" in context_map
        ctx = context_map["ctx_fund_benchmark"]
        assert ctx["class_id"] == "C000014542"
        assert ctx["performance_measure"] == "SP500IndexMember"
        assert ctx["period_start"] == "2021-11-03"
        assert ctx["period_end"] == "2022-11-03"

    def test_fund_context_has_no_performance_measure(self):
        """Test that a plain fund context has performance_measure=None."""
        html = """
        <html>
        <ix:resources>
          <xbrli:context id="ctx_fund">
            <xbrli:entity>
              <xbrli:identifier scheme="http://www.sec.gov/CIK">0001314612</xbrli:identifier>
              <xbrli:segment>
                <xbrldi:explicitMember dimension="dei:LegalEntityAxis">rr01:S000014796Member</xbrldi:explicitMember>
                <xbrldi:explicitMember dimension="rr:ProspectusShareClassAxis">rr01:C000014542Member</xbrldi:explicitMember>
              </xbrli:segment>
            </xbrli:entity>
            <xbrli:period>
              <xbrli:startDate>2021-11-03</xbrli:startDate>
              <xbrli:endDate>2022-11-03</xbrli:endDate>
            </xbrli:period>
          </xbrli:context>
        </ix:resources>
        </html>
        """
        soup = BeautifulSoup(html, 'lxml')
        context_map = parse_contexts(soup)

        assert "ctx_fund" in context_map
        ctx = context_map["ctx_fund"]
        assert ctx["class_id"] == "C000014542"
        assert ctx["performance_measure"] is None
        assert ctx["period_start"] == "2021-11-03"
        assert ctx["period_end"] == "2022-11-03"

    def test_performance_measure_strips_namespace_prefix(self):
        """Test that namespace prefix is stripped from PerformanceMeasureAxis member."""
        html = """
        <html>
        <ix:resources>
          <xbrli:context id="ctx_bm">
            <xbrli:entity>
              <xbrli:identifier scheme="http://www.sec.gov/CIK">0001314612</xbrli:identifier>
              <xbrli:segment>
                <xbrldi:explicitMember dimension="rr:ProspectusShareClassAxis">rr01:C000014542Member</xbrldi:explicitMember>
                <xbrldi:explicitMember dimension="rr:PerformanceMeasureAxis">ns:BloombergAggMember</xbrldi:explicitMember>
              </xbrli:segment>
            </xbrli:entity>
            <xbrli:period>
              <xbrli:startDate>2021-11-03</xbrli:startDate>
              <xbrli:endDate>2022-11-03</xbrli:endDate>
            </xbrli:period>
          </xbrli:context>
        </ix:resources>
        </html>
        """
        soup = BeautifulSoup(html, 'lxml')
        context_map = parse_contexts(soup)
        ctx = context_map["ctx_bm"]
        assert ctx["performance_measure"] == "BloombergAggMember"


class TestExtractPerformanceData:
    """Unit tests for _extract_performance_data() helper."""

    def _make_rr_filing(self, include_benchmark=True):
        """Build minimal RR iXBRL with fund and benchmark performance tags."""
        benchmark_context = ""
        benchmark_tags = ""
        if include_benchmark:
            benchmark_context = """
            <xbrli:context id="ctx_bm">
              <xbrli:entity>
                <xbrli:identifier>0001314612</xbrli:identifier>
                <xbrli:segment>
                  <xbrldi:explicitMember dimension="rr:ProspectusShareClassAxis">rr01:C000014542Member</xbrldi:explicitMember>
                  <xbrldi:explicitMember dimension="rr:PerformanceMeasureAxis">rr01:SP500IndexMember</xbrldi:explicitMember>
                </xbrli:segment>
              </xbrli:entity>
              <xbrli:period>
                <xbrli:startDate>2021-11-03</xbrli:startDate>
                <xbrli:endDate>2022-11-03</xbrli:endDate>
              </xbrli:period>
            </xbrli:context>"""
            benchmark_tags = """
            <ix:nonfraction name="rr:AverageAnnualReturnYear01" contextRef="ctx_bm" scale="-2" unitRef="Ratio">9.10</ix:nonfraction>
            <ix:nonfraction name="rr:AverageAnnualReturnYear05" contextRef="ctx_bm" scale="-2" unitRef="Ratio">13.50</ix:nonfraction>
            <ix:nonfraction name="rr:AverageAnnualReturnYear10" contextRef="ctx_bm" scale="-2" unitRef="Ratio">15.20</ix:nonfraction>"""
        return f"""
        <html>
        <ix:resources>
          <xbrli:context id="ctx_fund">
            <xbrli:entity>
              <xbrli:identifier>0001314612</xbrli:identifier>
              <xbrli:segment>
                <xbrldi:explicitMember dimension="rr:ProspectusShareClassAxis">rr01:C000014542Member</xbrldi:explicitMember>
              </xbrli:segment>
            </xbrli:entity>
            <xbrli:period>
              <xbrli:startDate>2012-11-03</xbrli:startDate>
              <xbrli:endDate>2022-11-03</xbrli:endDate>
            </xbrli:period>
          </xbrli:context>
          {benchmark_context}
          <xbrli:unit id="Ratio"><xbrli:measure>xbrli:pure</xbrli:measure></xbrli:unit>
        </ix:resources>
        <ix:nonfraction name="rr:AverageAnnualReturnYear01" contextRef="ctx_fund" scale="-2" unitRef="Ratio">8.50</ix:nonfraction>
        <ix:nonfraction name="rr:AverageAnnualReturnYear05" contextRef="ctx_fund" scale="-2" unitRef="Ratio">12.30</ix:nonfraction>
        <ix:nonfraction name="rr:AverageAnnualReturnYear10" contextRef="ctx_fund" scale="-2" unitRef="Ratio">14.75</ix:nonfraction>
        <ix:nonfraction name="rr:AverageAnnualReturnSinceInception" contextRef="ctx_fund" scale="-2" unitRef="Ratio">11.20</ix:nonfraction>
        <ix:nonfraction name="rr:PortfolioTurnoverRate" contextRef="ctx_fund" scale="-2" unitRef="Ratio">45.00</ix:nonfraction>
        {benchmark_tags}
        </html>"""

    def test_rr_fund_returns(self):
        from etf_pipeline.parsers.prospectus import _extract_performance_data, build_tag_index, parse_contexts
        soup = BeautifulSoup(self._make_rr_filing(include_benchmark=False), 'lxml')
        context_map = parse_contexts(soup)
        tag_index = build_tag_index(soup)

        result = _extract_performance_data(tag_index, context_map, 'C000014542', 'ctx_fund', 'rr')

        assert result['return_1yr'] == Decimal('0.0850')
        assert result['return_5yr'] == Decimal('0.1230')
        assert result['return_10yr'] == Decimal('0.1475')
        assert result['return_since_inception'] == Decimal('0.1120')
        assert result['portfolio_turnover'] == Decimal('0.4500')
        assert result.get('benchmark_name') is None

    def test_rr_benchmark_returns(self):
        from etf_pipeline.parsers.prospectus import _extract_performance_data, build_tag_index, parse_contexts
        soup = BeautifulSoup(self._make_rr_filing(include_benchmark=True), 'lxml')
        context_map = parse_contexts(soup)
        tag_index = build_tag_index(soup)

        result = _extract_performance_data(tag_index, context_map, 'C000014542', 'ctx_fund', 'rr')

        assert result['return_1yr'] == Decimal('0.0850')
        assert result['benchmark_name'] == 'SP500IndexMember'
        assert result['benchmark_return_1yr'] == Decimal('0.0910')
        assert result['benchmark_return_5yr'] == Decimal('0.1350')
        assert result['benchmark_return_10yr'] == Decimal('0.1520')

    def test_rr_no_performance_tags_returns_empty(self):
        from etf_pipeline.parsers.prospectus import _extract_performance_data, build_tag_index, parse_contexts
        html = """
        <html>
        <ix:resources>
          <xbrli:context id="ctx_fund">
            <xbrli:entity><xbrli:identifier>0001314612</xbrli:identifier>
              <xbrli:segment>
                <xbrldi:explicitMember dimension="rr:ProspectusShareClassAxis">rr01:C000014542Member</xbrldi:explicitMember>
              </xbrli:segment>
            </xbrli:entity>
            <xbrli:period><xbrli:startDate>2021-11-03</xbrli:startDate><xbrli:endDate>2022-11-03</xbrli:endDate></xbrli:period>
          </xbrli:context>
        </ix:resources>
        <ix:nonfraction name="rr:ManagementFeesOverAssets" contextRef="ctx_fund" scale="-2">0.70</ix:nonfraction>
        </html>"""
        soup = BeautifulSoup(html, 'lxml')
        context_map = parse_contexts(soup)
        tag_index = build_tag_index(soup)

        result = _extract_performance_data(tag_index, context_map, 'C000014542', 'ctx_fund', 'rr')

        assert result.get('return_1yr') is None
        assert result.get('benchmark_name') is None

    def test_oef_fund_returns_with_period_mapping(self):
        from etf_pipeline.parsers.prospectus import _extract_performance_data, build_tag_index, parse_contexts
        html = """
        <html xmlns:oef="http://xbrl.sec.gov/oef-rr/2025" xmlns:oef01="http://oef01/20221103">
        <ix:resources>
          <xbrli:context id="ctx_1yr">
            <xbrli:entity><xbrli:identifier>0001314612</xbrli:identifier>
              <xbrli:segment>
                <xbrldi:explicitMember dimension="oef:ClassAxis">oef01:C000014542Member</xbrldi:explicitMember>
              </xbrli:segment>
            </xbrli:entity>
            <xbrli:period><xbrli:startDate>2021-11-03</xbrli:startDate><xbrli:endDate>2022-11-03</xbrli:endDate></xbrli:period>
          </xbrli:context>
          <xbrli:context id="ctx_5yr">
            <xbrli:entity><xbrli:identifier>0001314612</xbrli:identifier>
              <xbrli:segment>
                <xbrldi:explicitMember dimension="oef:ClassAxis">oef01:C000014542Member</xbrldi:explicitMember>
              </xbrli:segment>
            </xbrli:entity>
            <xbrli:period><xbrli:startDate>2017-11-03</xbrli:startDate><xbrli:endDate>2022-11-03</xbrli:endDate></xbrli:period>
          </xbrli:context>
          <xbrli:unit id="Ratio"><xbrli:measure>xbrli:pure</xbrli:measure></xbrli:unit>
        </ix:resources>
        <ix:nonfraction name="oef:AvgAnnlRtrPct" contextRef="ctx_1yr" scale="-2" unitRef="Ratio">8.50</ix:nonfraction>
        <ix:nonfraction name="oef:AvgAnnlRtrPct" contextRef="ctx_5yr" scale="-2" unitRef="Ratio">12.30</ix:nonfraction>
        </html>"""
        soup = BeautifulSoup(html, 'lxml')
        context_map = parse_contexts(soup)
        tag_index = build_tag_index(soup)

        result = _extract_performance_data(tag_index, context_map, 'C000014542', 'ctx_1yr', 'oef')

        assert result['return_1yr'] == Decimal('0.0850')
        assert result['return_5yr'] == Decimal('0.1230')
        assert result.get('benchmark_name') is None

    def test_oef_benchmark_return(self):
        from etf_pipeline.parsers.prospectus import _extract_performance_data, build_tag_index, parse_contexts
        html = """
        <html xmlns:oef="http://xbrl.sec.gov/oef-rr/2025" xmlns:oef01="http://oef01/20221103">
        <ix:resources>
          <xbrli:context id="ctx_1yr">
            <xbrli:entity><xbrli:identifier>0001314612</xbrli:identifier>
              <xbrli:segment>
                <xbrldi:explicitMember dimension="oef:ClassAxis">oef01:C000014542Member</xbrldi:explicitMember>
              </xbrli:segment>
            </xbrli:entity>
            <xbrli:period><xbrli:startDate>2021-11-03</xbrli:startDate><xbrli:endDate>2022-11-03</xbrli:endDate></xbrli:period>
          </xbrli:context>
          <xbrli:context id="ctx_bm_1yr">
            <xbrli:entity><xbrli:identifier>0001314612</xbrli:identifier>
              <xbrli:segment>
                <xbrldi:explicitMember dimension="oef:ClassAxis">oef01:C000014542Member</xbrldi:explicitMember>
                <xbrldi:explicitMember dimension="oef:PerformanceMeasureAxis">oef01:SP500IndexMember</xbrldi:explicitMember>
              </xbrli:segment>
            </xbrli:entity>
            <xbrli:period><xbrli:startDate>2021-11-03</xbrli:startDate><xbrli:endDate>2022-11-03</xbrli:endDate></xbrli:period>
          </xbrli:context>
          <xbrli:unit id="Ratio"><xbrli:measure>xbrli:pure</xbrli:measure></xbrli:unit>
        </ix:resources>
        <ix:nonfraction name="oef:AvgAnnlRtrPct" contextRef="ctx_1yr" scale="-2" unitRef="Ratio">8.50</ix:nonfraction>
        <ix:nonfraction name="oef:AvgAnnlRtrPct" contextRef="ctx_bm_1yr" scale="-2" unitRef="Ratio">9.10</ix:nonfraction>
        </html>"""
        soup = BeautifulSoup(html, 'lxml')
        context_map = parse_contexts(soup)
        tag_index = build_tag_index(soup)

        result = _extract_performance_data(tag_index, context_map, 'C000014542', 'ctx_1yr', 'oef')

        assert result['return_1yr'] == Decimal('0.0850')
        assert result['benchmark_name'] == 'SP500IndexMember'
        assert result['benchmark_return_1yr'] == Decimal('0.0910')


class TestIntegrationPerformanceRR:
    """Integration tests for performance extraction in _process_cik_prospectus (RR namespace)."""

    def test_performance_extracted_rr_namespace(self, session):
        """Test that Performance record is written for RR namespace filing with perf data."""
        from datetime import date
        from unittest.mock import Mock, patch
        from etf_pipeline.models import ETF, Performance
        from etf_pipeline.parsers.prospectus import _process_cik_prospectus
        from pathlib import Path

        fixture_path = Path(__file__).parent / "fixtures" / "prospectus" / "sample_485bpos_perf.html"

        etf = ETF(
            cik='0001314612',
            ticker='TESTA',
            fund_name='Test Fund - Class A',
            issuer_name='Test Issuer',
            series_id='S000014796',
            class_id='C000014542',
        )
        session.add(etf)
        session.commit()
        etf_id = etf.id

        with open(fixture_path) as f:
            html_content = f.read()

        mock_filing = Mock()
        mock_filing.html.return_value = html_content
        mock_filing.filing_date = date(2022, 11, 3)
        mock_filing.document.url = 'https://www.sec.gov/test/filing.htm'

        mock_filings = Mock()
        mock_filings.__getitem__ = Mock(return_value=mock_filing)
        mock_filings.__len__ = Mock(return_value=1)
        mock_filings.empty = False

        mock_company = Mock()
        mock_company.get_filings.return_value = mock_filings

        with patch('edgar.Company', return_value=mock_company):
            result = _process_cik_prospectus(session, '0001314612')

        assert result is True

        perf = session.query(Performance).filter_by(etf_id=etf_id).one()
        assert perf.return_1yr == pytest.approx(Decimal('0.0850'))
        assert perf.return_5yr == pytest.approx(Decimal('0.1230'))
        assert perf.return_10yr == pytest.approx(Decimal('0.1475'))
        assert perf.return_since_inception == pytest.approx(Decimal('0.1120'))
        assert perf.portfolio_turnover == pytest.approx(Decimal('0.4500'))
        assert perf.benchmark_name == 'SP500IndexMember'
        assert perf.benchmark_return_1yr == pytest.approx(Decimal('0.0910'))
        assert perf.benchmark_return_5yr == pytest.approx(Decimal('0.1350'))
        assert perf.benchmark_return_10yr == pytest.approx(Decimal('0.1520'))
        assert perf.fiscal_year_end == date(2022, 11, 3)
        assert perf.filing_date == date(2022, 11, 3)

    def test_benchmark_context_skipped_for_fees(self, session):
        """Test that benchmark contexts (class_id + PerformanceMeasureAxis) do not create FeeExpense."""
        from datetime import date
        from unittest.mock import Mock, patch
        from etf_pipeline.models import ETF, FeeExpense
        from etf_pipeline.parsers.prospectus import _process_cik_prospectus
        from pathlib import Path

        fixture_path = Path(__file__).parent / "fixtures" / "prospectus" / "sample_485bpos_perf.html"

        etf = ETF(
            cik='0001314612',
            ticker='TESTA',
            fund_name='Test Fund - Class A',
            issuer_name='Test Issuer',
            series_id='S000014796',
            class_id='C000014542',
        )
        session.add(etf)
        session.commit()
        etf_id = etf.id

        with open(fixture_path) as f:
            html_content = f.read()

        mock_filing = Mock()
        mock_filing.html.return_value = html_content
        mock_filing.filing_date = date(2022, 11, 3)
        mock_filing.document.url = 'https://www.sec.gov/test/filing.htm'

        mock_filings = Mock()
        mock_filings.__getitem__ = Mock(return_value=mock_filing)
        mock_filings.__len__ = Mock(return_value=1)
        mock_filings.empty = False

        mock_company = Mock()
        mock_company.get_filings.return_value = mock_filings

        with patch('edgar.Company', return_value=mock_company):
            result = _process_cik_prospectus(session, '0001314612')

        assert result is True
        # Only one FeeExpense record (from the fund context, not the benchmark context)
        assert session.query(FeeExpense).filter_by(etf_id=etf_id).count() == 1


class TestIntegrationPerformanceOEF:
    """Integration tests for performance extraction with OEF namespace."""

    def test_performance_extracted_oef_namespace(self, session):
        """Test that Performance record is written for OEF namespace filing with perf data."""
        from datetime import date
        from unittest.mock import Mock, patch
        from etf_pipeline.models import ETF, Performance
        from etf_pipeline.parsers.prospectus import _process_cik_prospectus
        from pathlib import Path

        fixture_path = Path(__file__).parent / "fixtures" / "prospectus" / "sample_485bpos_oef_perf.html"

        etf = ETF(
            cik='0001314612',
            ticker='TESTA',
            fund_name='Test Fund - Class A',
            issuer_name='Test Issuer',
            series_id='S000014796',
            class_id='C000014542',
        )
        session.add(etf)
        session.commit()
        etf_id = etf.id

        with open(fixture_path) as f:
            html_content = f.read()

        mock_filing = Mock()
        mock_filing.html.return_value = html_content
        mock_filing.filing_date = date(2022, 11, 3)
        mock_filing.document.url = 'https://www.sec.gov/test/filing.htm'

        mock_filings = Mock()
        mock_filings.__getitem__ = Mock(return_value=mock_filing)
        mock_filings.__len__ = Mock(return_value=1)
        mock_filings.empty = False

        mock_company = Mock()
        mock_company.get_filings.return_value = mock_filings

        with patch('edgar.Company', return_value=mock_company):
            result = _process_cik_prospectus(session, '0001314612')

        assert result is True

        perf = session.query(Performance).filter_by(etf_id=etf_id).one()
        assert perf.return_1yr == pytest.approx(Decimal('0.0850'))
        assert perf.return_5yr == pytest.approx(Decimal('0.1230'))
        assert perf.return_10yr == pytest.approx(Decimal('0.1475'))
        assert perf.portfolio_turnover == pytest.approx(Decimal('0.4500'))
        assert perf.benchmark_name == 'SP500IndexMember'
        assert perf.benchmark_return_1yr == pytest.approx(Decimal('0.0910'))
        assert perf.fiscal_year_end == date(2022, 11, 3)
        assert perf.filing_date == date(2022, 11, 3)

    def test_no_performance_data_no_record(self, session):
        """Test that no Performance record is written when filing has no performance tags."""
        from datetime import date
        from unittest.mock import Mock, patch
        from etf_pipeline.models import ETF, Performance
        from etf_pipeline.parsers.prospectus import _process_cik_prospectus
        from pathlib import Path

        # Use the original RR fixture which has no performance tags
        fixture_path = Path(__file__).parent / "fixtures" / "prospectus" / "sample_485bpos.html"

        etf = ETF(
            cik='0001314612',
            ticker='TESTA',
            fund_name='Test Fund - Class A',
            issuer_name='Test Issuer',
            series_id='S000014796',
            class_id='C000014542',
        )
        session.add(etf)
        session.commit()
        etf_id = etf.id

        with open(fixture_path) as f:
            html_content = f.read()

        mock_filing = Mock()
        mock_filing.html.return_value = html_content
        mock_filing.filing_date = date(2022, 11, 3)
        mock_filing.document.url = 'https://www.sec.gov/test/filing.htm'

        mock_filings = Mock()
        mock_filings.__getitem__ = Mock(return_value=mock_filing)
        mock_filings.__len__ = Mock(return_value=1)
        mock_filings.empty = False

        mock_company = Mock()
        mock_company.get_filings.return_value = mock_filings

        with patch('edgar.Company', return_value=mock_company):
            result = _process_cik_prospectus(session, '0001314612')

        assert result is True
        # No performance data in fixture → no Performance record
        assert session.query(Performance).filter_by(etf_id=etf_id).count() == 0


class TestExtractPerformanceFromHtmlTable:
    """Unit tests for _extract_performance_from_html_table()."""

    from etf_pipeline.parsers.prospectus import _extract_performance_from_html_table

    VERTICAL_LAYOUT = """
    <html><body>
    <h3>Average Annual Total Returns</h3>
    <table>
      <tr><th>Period</th><th>Fund</th><th>S&amp;P 500 Index</th></tr>
      <tr><td>1 Year</td><td>8.50%</td><td>9.10%</td></tr>
      <tr><td>5 Years</td><td>12.30%</td><td>13.50%</td></tr>
      <tr><td>10 Years</td><td>14.75%</td><td>15.20%</td></tr>
      <tr><td>Since Inception</td><td>11.20%</td><td></td></tr>
    </table>
    </body></html>
    """

    HORIZONTAL_LAYOUT = """
    <html><body>
    <h3>Average Annual Total Returns as of December 31</h3>
    <table>
      <thead>
        <tr><th></th><th>1 Year</th><th>5 Years</th><th>10 Years</th></tr>
      </thead>
      <tbody>
        <tr><td>SPDR S&amp;P 500 ETF Trust</td><td>8.50%</td><td>12.30%</td><td>14.75%</td></tr>
        <tr><td>S&amp;P 500 Index</td><td>9.10%</td><td>13.50%</td><td>15.20%</td></tr>
      </tbody>
    </table>
    </body></html>
    """

    NO_PERFORMANCE_TABLE = """
    <html><body>
    <table>
      <tr><td>Management Fees</td><td>0.0945%</td></tr>
      <tr><td>Total Annual Fund Operating Expenses</td><td>0.0945%</td></tr>
    </table>
    </body></html>
    """

    def test_vertical_layout_fund_returns(self):
        from datetime import date
        from etf_pipeline.parsers.prospectus import _extract_performance_from_html_table
        soup = BeautifulSoup(self.VERTICAL_LAYOUT, 'lxml')
        result = _extract_performance_from_html_table(soup, date(2022, 12, 31))

        assert result is not None
        assert result['return_1yr'] == Decimal('0.0850')
        assert result['return_5yr'] == Decimal('0.1230')
        assert result['return_10yr'] == Decimal('0.1475')
        assert result['return_since_inception'] == Decimal('0.1120')

    def test_vertical_layout_benchmark(self):
        from datetime import date
        from etf_pipeline.parsers.prospectus import _extract_performance_from_html_table
        soup = BeautifulSoup(self.VERTICAL_LAYOUT, 'lxml')
        result = _extract_performance_from_html_table(soup, date(2022, 12, 31))

        assert result is not None
        assert result.get('benchmark_name') == 'S&P 500 Index'
        assert result['benchmark_return_1yr'] == Decimal('0.0910')
        assert result['benchmark_return_5yr'] == Decimal('0.1350')
        assert result['benchmark_return_10yr'] == Decimal('0.1520')

    def test_horizontal_layout_fund_returns(self):
        from datetime import date
        from etf_pipeline.parsers.prospectus import _extract_performance_from_html_table
        soup = BeautifulSoup(self.HORIZONTAL_LAYOUT, 'lxml')
        result = _extract_performance_from_html_table(soup, date(2022, 12, 31))

        assert result is not None
        assert result['return_1yr'] == Decimal('0.0850')
        assert result['return_5yr'] == Decimal('0.1230')
        assert result['return_10yr'] == Decimal('0.1475')

    def test_horizontal_layout_benchmark(self):
        from datetime import date
        from etf_pipeline.parsers.prospectus import _extract_performance_from_html_table
        soup = BeautifulSoup(self.HORIZONTAL_LAYOUT, 'lxml')
        result = _extract_performance_from_html_table(soup, date(2022, 12, 31))

        assert result is not None
        assert result.get('benchmark_name') == 'S&P 500 Index'
        assert result['benchmark_return_1yr'] == Decimal('0.0910')
        assert result['benchmark_return_5yr'] == Decimal('0.1350')
        assert result['benchmark_return_10yr'] == Decimal('0.1520')

    def test_no_performance_table_returns_none(self):
        from datetime import date
        from etf_pipeline.parsers.prospectus import _extract_performance_from_html_table
        soup = BeautifulSoup(self.NO_PERFORMANCE_TABLE, 'lxml')
        result = _extract_performance_from_html_table(soup, date(2022, 12, 31))
        assert result is None

    def test_negative_return_value(self):
        from datetime import date
        from etf_pipeline.parsers.prospectus import _extract_performance_from_html_table
        html = """
        <html><body>
        <h3>Average Annual Total Returns</h3>
        <table>
          <tr><td>1 Year</td><td>(2.50)%</td></tr>
          <tr><td>5 Years</td><td>8.00%</td></tr>
          <tr><td>10 Years</td><td>11.00%</td></tr>
        </table>
        </body></html>
        """
        soup = BeautifulSoup(html, 'lxml')
        result = _extract_performance_from_html_table(soup, date(2022, 12, 31))
        assert result is not None
        assert result['return_1yr'] == Decimal('-0.0250')
        assert result['return_5yr'] == Decimal('0.0800')


class TestUitHtmlPerformanceFallback:
    """Integration tests for UIT HTML performance fallback in _process_cik_prospectus."""

    UIT_PERF_HTML = """
    <html><body>
    <h3>Average Annual Total Returns</h3>
    <table>
      <tr><th>Period</th><th>SPY</th><th>S&amp;P 500 Index</th></tr>
      <tr><td>1 Year</td><td>25.02%</td><td>25.02%</td></tr>
      <tr><td>5 Years</td><td>15.68%</td><td>15.69%</td></tr>
      <tr><td>10 Years</td><td>13.07%</td><td>13.09%</td></tr>
    </table>
    </body></html>
    """

    def test_uit_html_performance_extracted_no_ixbrl(self, session):
        """UIT (no class_id) gets Performance record via HTML fallback when no iXBRL present."""
        from datetime import date
        from unittest.mock import Mock, patch
        from etf_pipeline.models import ETF, Performance
        from etf_pipeline.parsers.prospectus import _process_cik_prospectus

        etf = ETF(
            cik='0000884394',
            ticker='SPY',
            fund_name='SPDR S&P 500 ETF Trust',
            issuer_name='State Street',
            series_id=None,
            class_id=None,
        )
        session.add(etf)
        session.commit()
        etf_id = etf.id

        mock_filing = Mock()
        mock_filing.html.return_value = self.UIT_PERF_HTML
        mock_filing.filing_date = date(2024, 3, 1)
        mock_filing.document.url = 'https://www.sec.gov/test/spy.htm'

        mock_filings = Mock()
        mock_filings.__getitem__ = Mock(return_value=mock_filing)
        mock_filings.__len__ = Mock(return_value=1)
        mock_filings.empty = False

        mock_company = Mock()
        mock_company.get_filings.return_value = mock_filings

        with patch('edgar.Company', return_value=mock_company):
            result = _process_cik_prospectus(session, '0000884394')

        assert result is True
        perf = session.query(Performance).filter_by(etf_id=etf_id).one()
        assert perf.return_1yr == pytest.approx(Decimal('0.2502'))
        assert perf.return_5yr == pytest.approx(Decimal('0.1568'))
        assert perf.return_10yr == pytest.approx(Decimal('0.1307'))
        assert perf.filing_date == date(2024, 3, 1)

    def test_uit_no_performance_table_no_record(self, session):
        """UIT with plain HTML but no performance table writes no Performance record."""
        from datetime import date
        from unittest.mock import Mock, patch
        from etf_pipeline.models import ETF, Performance
        from etf_pipeline.parsers.prospectus import _process_cik_prospectus

        etf = ETF(
            cik='0000884394',
            ticker='SPY',
            fund_name='SPDR S&P 500 ETF Trust',
            issuer_name='State Street',
            series_id=None,
            class_id=None,
        )
        session.add(etf)
        session.commit()
        etf_id = etf.id

        html_no_perf = """
        <html><body>
        <table>
          <tr><td>Management Fees</td><td>0.0945%</td></tr>
        </table>
        </body></html>
        """

        mock_filing = Mock()
        mock_filing.html.return_value = html_no_perf
        mock_filing.filing_date = date(2024, 3, 1)
        mock_filing.document.url = 'https://www.sec.gov/test/spy.htm'

        mock_filings = Mock()
        mock_filings.__getitem__ = Mock(return_value=mock_filing)
        mock_filings.__len__ = Mock(return_value=1)
        mock_filings.empty = False

        mock_company = Mock()
        mock_company.get_filings.return_value = mock_filings

        with patch('edgar.Company', return_value=mock_company):
            result = _process_cik_prospectus(session, '0000884394')

        assert result is True
        assert session.query(Performance).filter_by(etf_id=etf_id).count() == 0
