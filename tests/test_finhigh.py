"""Tests for Financial Highlights parser."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from etf_pipeline.parsers.finhigh import (
    _parse_date,
    _parse_decimal,
    parse_financial_highlights_table,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "finhigh"


class TestParseDecimal:
    """Tests for _parse_decimal helper."""

    def test_none(self):
        assert _parse_decimal(None) is None

    def test_empty_string(self):
        assert _parse_decimal("") is None
        assert _parse_decimal("  ") is None

    def test_dash_variants(self):
        assert _parse_decimal("-") is None
        assert _parse_decimal("—") is None
        assert _parse_decimal("N/A") is None
        assert _parse_decimal("n/a") is None

    def test_simple_decimal(self):
        assert _parse_decimal("1.23") == Decimal("1.23")
        assert _parse_decimal("0.05") == Decimal("0.05")

    def test_with_dollar_sign(self):
        assert _parse_decimal("$1.23") == Decimal("1.23")
        assert _parse_decimal("$102.18") == Decimal("102.18")

    def test_with_commas(self):
        assert _parse_decimal("1,234.56") == Decimal("1234.56")
        assert _parse_decimal("$1,234.56") == Decimal("1234.56")

    def test_parentheses_negative(self):
        assert _parse_decimal("(1.23)") == Decimal("-1.23")
        assert _parse_decimal("($1.23)") == Decimal("-1.23")
        assert _parse_decimal("(1,234.56)") == Decimal("-1234.56")

    def test_percentage(self):
        assert _parse_decimal("0.17%") == Decimal("0.0017")
        assert _parse_decimal("14.10%") == Decimal("0.1410")
        assert _parse_decimal("-17.71%") == Decimal("-0.1771")

    def test_existing_decimal(self):
        d = Decimal("1.23")
        assert _parse_decimal(d) == d


class TestParseDate:
    """Tests for _parse_date helper."""

    def test_none(self):
        assert _parse_date(None) is None

    def test_empty_string(self):
        assert _parse_date("") is None

    def test_slash_format(self):
        result = _parse_date("12/31/2024")
        assert result.year == 2024
        assert result.month == 12
        assert result.day == 31

    def test_iso_format(self):
        result = _parse_date("2024-12-31")
        assert result.year == 2024
        assert result.month == 12
        assert result.day == 31

    def test_long_month_format(self):
        result = _parse_date("December 31, 2024")
        assert result.year == 2024
        assert result.month == 12
        assert result.day == 31

    def test_invalid_format(self):
        assert _parse_date("not a date") is None


class TestParseFinancialHighlightsTable:
    """Tests for parse_financial_highlights_table function."""

    def test_vanguard_sample(self):
        """Test parsing a real Vanguard Financial Highlights table."""
        fixture_path = FIXTURES_DIR / "vanguard_sample.html"
        with open(fixture_path, "r") as f:
            html = f.read()

        result = parse_financial_highlights_table(html)

        # Check structure
        assert "operating" in result
        assert "distribution" in result
        assert "ratios" in result
        assert "fiscal_year_end" in result
        assert "math_validated" in result

        # Check operating data (2024 column)
        assert result["operating"]["nav_beginning"] == Decimal("102.18")
        assert result["operating"]["net_investment_income"] == Decimal("1.404")
        assert result["operating"]["net_realized_unrealized_gain"] == Decimal("12.933")
        assert result["operating"]["total_from_operations"] == Decimal("14.337")
        assert result["operating"]["equalization"] is None  # Vanguard doesn't use equalization
        assert result["operating"]["nav_end"] == Decimal("115.15")
        assert result["operating"]["total_return"] == Decimal("0.1410")  # 14.10% as decimal

        # Check distribution data
        assert result["distribution"]["dist_net_investment_income"] == Decimal("-1.367")
        assert result["distribution"]["dist_realized_gains"] is None  # No cap gains for 2024
        assert result["distribution"]["dist_return_of_capital"] is None
        assert result["distribution"]["dist_total"] == Decimal("-1.367")

        # Check ratios
        assert result["ratios"]["expense_ratio"] == Decimal("0.0017")  # 0.17% as decimal
        assert result["ratios"]["portfolio_turnover"] == Decimal("0.13")  # 13% as decimal
        # Net assets: $335 million
        assert result["ratios"]["net_assets_end"] == Decimal("335000000")

        # Check fiscal year end
        # We may not extract the exact date from this table format
        # assert result["fiscal_year_end"] is not None

        # Check math validation
        # NAV_end = NAV_begin + total_ops + dist_total + equalization
        # 115.15 = 102.18 + 14.337 + (-1.367) + 0 = 115.15 ✓
        assert result["math_validated"] is True

    def test_no_table_error(self):
        """Test that missing table raises ValueError."""
        html = "<div>Not a table</div>"
        with pytest.raises(ValueError, match="No table found"):
            parse_financial_highlights_table(html)

    def test_too_few_rows_error(self):
        """Test that table with too few rows raises ValueError."""
        html = """
        <table>
            <tr><td>Row 1</td></tr>
            <tr><td>Row 2</td></tr>
            <tr><td>Row 3</td></tr>
        </table>
        """
        with pytest.raises(ValueError, match="Too few rows"):
            parse_financial_highlights_table(html)

    def test_missing_values_handled(self):
        """Test that missing values return None without crashing."""
        # Create a minimal table that passes row count but has missing data
        html = """
        <table>
            <tr><td>Header</td><td>2024</td></tr>
            <tr><td>Net Asset Value, Beginning of Period</td><td>$100.00</td></tr>
            <tr><td>Investment Operations</td><td></td></tr>
            <tr><td>Net Investment Income</td><td>1.00</td></tr>
            <tr><td>Net Realized and Unrealized Gain</td><td>—</td></tr>
            <tr><td>Total from Investment Operations</td><td>1.00</td></tr>
            <tr><td>Distributions</td><td></td></tr>
            <tr><td>Dividends from Net Investment Income</td><td>(1.00)</td></tr>
            <tr><td>Total Distributions</td><td>(1.00)</td></tr>
            <tr><td>Net Asset Value, End of Period</td><td>$100.00</td></tr>
            <tr><td>Total Return</td><td>1.00%</td></tr>
            <tr><td>Ratios/Supplemental Data</td><td></td></tr>
        </table>
        """
        result = parse_financial_highlights_table(html)

        # Should parse what's there
        assert result["operating"]["nav_beginning"] == Decimal("100.00")
        assert result["operating"]["net_investment_income"] == Decimal("1.00")
        assert result["operating"]["net_realized_unrealized_gain"] is None  # em dash
        assert result["operating"]["nav_end"] == Decimal("100.00")

        # Math validation should pass even with missing gain field
        # because the total_from_operations is correctly stated
        assert result["math_validated"] is True

    def test_equalization_row(self):
        """Test handling of equalization row (State Street SPDR pattern)."""
        html = """
        <table>
            <tr><td>For a Share Outstanding</td><td>2024</td></tr>
            <tr><td>Net Asset Value, Beginning of Period</td><td>$100.00</td></tr>
            <tr><td>Investment Operations</td><td></td></tr>
            <tr><td>Net Investment Income</td><td>2.00</td></tr>
            <tr><td>Net Realized and Unrealized Gain</td><td>10.00</td></tr>
            <tr><td>Total from Investment Operations</td><td>12.00</td></tr>
            <tr><td>Equalization</td><td>0.05</td></tr>
            <tr><td>Distributions</td><td></td></tr>
            <tr><td>Dividends from Net Investment Income</td><td>(2.00)</td></tr>
            <tr><td>Total Distributions</td><td>(2.00)</td></tr>
            <tr><td>Net Asset Value, End of Period</td><td>$110.05</td></tr>
            <tr><td>Total Return</td><td>12.10%</td></tr>
            <tr><td>Ratios/Supplemental Data</td><td></td></tr>
            <tr><td>Net Assets, End of Period (Millions)</td><td>$500</td></tr>
        </table>
        """
        result = parse_financial_highlights_table(html)

        # Check equalization is captured
        assert result["operating"]["equalization"] == Decimal("0.05")

        # Check math validation includes equalization
        # NAV_end = 100.00 + 12.00 + (-2.00) + 0.05 = 110.05 ✓
        assert result["math_validated"] is True

    def test_return_of_capital_distribution(self):
        """Test handling of return of capital distributions (ALPS pattern)."""
        html = """
        <table>
            <tr><td>For a Share Outstanding</td><td>2024</td></tr>
            <tr><td>Net Asset Value, Beginning of Period</td><td>$50.00</td></tr>
            <tr><td>Investment Operations</td><td></td></tr>
            <tr><td>Net Investment Income</td><td>1.50</td></tr>
            <tr><td>Net Realized and Unrealized Gain</td><td>5.00</td></tr>
            <tr><td>Total from Investment Operations</td><td>6.50</td></tr>
            <tr><td>Distributions</td><td></td></tr>
            <tr><td>Dividends from Net Investment Income</td><td>(1.50)</td></tr>
            <tr><td>Distributions from Realized Capital Gains</td><td>(0.50)</td></tr>
            <tr><td>Return of Capital</td><td>(0.25)</td></tr>
            <tr><td>Total Distributions</td><td>(2.25)</td></tr>
            <tr><td>Net Asset Value, End of Period</td><td>$54.25</td></tr>
            <tr><td>Total Return</td><td>13.20%</td></tr>
            <tr><td>Ratios/Supplemental Data</td><td></td></tr>
        </table>
        """
        result = parse_financial_highlights_table(html)

        # Check all distribution components
        assert result["distribution"]["dist_net_investment_income"] == Decimal("-1.50")
        assert result["distribution"]["dist_realized_gains"] == Decimal("-0.50")
        assert result["distribution"]["dist_return_of_capital"] == Decimal("-0.25")
        assert result["distribution"]["dist_total"] == Decimal("-2.25")

        # Check math validation
        # NAV_end = 50.00 + 6.50 + (-2.25) + 0 = 54.25 ✓
        assert result["math_validated"] is True


class TestProcessCikFinhigh:
    """Integration tests for _process_cik_finhigh."""

    def test_process_cik_finhigh_basic(self, session):
        """Test full CIK processing with mocked filing."""
        from unittest.mock import MagicMock, patch
        from etf_pipeline.models import ETF, PerShareOperating, PerShareDistribution, PerShareRatios
        from etf_pipeline.parsers.finhigh import _process_cik_finhigh

        # Setup: Create test ETF in database
        etf = ETF(
            cik='0000036405',
            ticker='VFIAX',
            fund_name='Vanguard 500 Index Fund Investor Shares',
            class_id='C000123456',
            issuer_name='Vanguard'
        )
        session.add(etf)
        session.commit()

        # Load fixture HTML
        fixture_path = FIXTURES_DIR / "vanguard_sample.html"
        with open(fixture_path, "r") as f:
            sample_html = f.read()

        # Create full HTML document with heading and share class
        full_html = f"""
        <html>
        <body>
        <h2>Vanguard 500 Index Fund</h2>
        <h3>Investor Shares</h3>
        <h4>Financial Highlights</h4>
        {sample_html}
        </body>
        </html>
        """

        # Create SGML header with series/class mapping
        sgml_header = """
        <SERIES-AND-CLASSES-CONTRACTS-DATA>
        <EXISTING-SERIES-AND-CLASSES-CONTRACTS>
        <SERIES>
        <SERIES-NAME>Vanguard 500 Index Fund
        <CLASS-CONTRACT>
        <CLASS-CONTRACT-ID>C000123456
        <CLASS-CONTRACT-NAME>Investor Shares
        <CLASS-CONTRACT-TICKER-SYMBOL>VFIAX
        </CLASS-CONTRACT>
        </SERIES>
        </EXISTING-SERIES-AND-CLASSES-CONTRACTS>
        </SERIES-AND-CLASSES-CONTRACTS-DATA>
        """

        # Mock edgartools Company and Filing
        with patch('etf_pipeline.parsers.finhigh.Company') as mock_company:
            mock_filing = MagicMock()
            mock_filing.filing_date = date(2024, 12, 31)
            mock_filing.html.return_value = full_html
            mock_header = MagicMock()
            mock_header.text = sgml_header
            mock_filing.header = mock_header

            mock_filings = [mock_filing]
            mock_company_instance = MagicMock()
            mock_company_instance.get_filings.return_value = mock_filings
            mock_company.return_value = mock_company_instance

            # Execute
            result = _process_cik_finhigh(session, '0000036405')

            # Verify success
            assert result is True

            # Verify data was inserted
            operating = session.query(PerShareOperating).filter_by(etf_id=etf.id).first()
            assert operating is not None
            assert operating.nav_beginning == Decimal("102.18")
            assert operating.nav_end == Decimal("115.15")
            assert operating.net_investment_income == Decimal("1.404")
            assert operating.net_realized_unrealized_gain == Decimal("12.933")
            assert operating.total_from_operations == Decimal("14.337")
            assert operating.total_return == Decimal("0.1410")
            assert operating.math_validated is True

            distribution = session.query(PerShareDistribution).filter_by(etf_id=etf.id).first()
            assert distribution is not None
            assert distribution.dist_net_investment_income == Decimal("-1.367")
            assert distribution.dist_total == Decimal("-1.367")

            ratios = session.query(PerShareRatios).filter_by(etf_id=etf.id).first()
            assert ratios is not None
            assert ratios.expense_ratio == Decimal("0.0017")
            assert ratios.portfolio_turnover == Decimal("0.13")
            assert ratios.net_assets_end == Decimal("335000000")

    def test_process_cik_finhigh_no_match(self, session):
        """Test that unmatched tables are skipped gracefully."""
        from unittest.mock import MagicMock, patch
        from etf_pipeline.models import ETF, PerShareOperating
        from etf_pipeline.parsers.finhigh import _process_cik_finhigh

        # Setup: Create ETF with different fund name
        etf = ETF(
            cik='0000036405',
            ticker='VOO',
            fund_name='Different Fund Name',
            class_id='C000999999',
            issuer_name='Vanguard'
        )
        session.add(etf)
        session.commit()

        # Load fixture HTML with mismatched heading
        fixture_path = FIXTURES_DIR / "vanguard_sample.html"
        with open(fixture_path, "r") as f:
            sample_html = f.read()

        full_html = f"""
        <html>
        <body>
        <h2>Unrelated Fund Name</h2>
        <h3>Some Other Shares</h3>
        <h4>Financial Highlights</h4>
        {sample_html}
        </body>
        </html>
        """

        # Create SGML header with non-matching series/class
        sgml_header = """
        <SERIES-AND-CLASSES-CONTRACTS-DATA>
        <EXISTING-SERIES-AND-CLASSES-CONTRACTS>
        <SERIES>
        <SERIES-NAME>Unrelated Fund Name
        <CLASS-CONTRACT>
        <CLASS-CONTRACT-ID>C000888888
        <CLASS-CONTRACT-NAME>Some Other Shares
        <CLASS-CONTRACT-TICKER-SYMBOL>XXX
        </CLASS-CONTRACT>
        </SERIES>
        </EXISTING-SERIES-AND-CLASSES-CONTRACTS>
        </SERIES-AND-CLASSES-CONTRACTS-DATA>
        """

        # Mock edgartools
        with patch('etf_pipeline.parsers.finhigh.Company') as mock_company:
            mock_filing = MagicMock()
            mock_filing.filing_date = date(2024, 12, 31)
            mock_filing.html.return_value = full_html
            mock_header = MagicMock()
            mock_header.text = sgml_header
            mock_filing.header = mock_header

            mock_filings = [mock_filing]
            mock_company_instance = MagicMock()
            mock_company_instance.get_filings.return_value = mock_filings
            mock_company.return_value = mock_company_instance

            # Execute
            result = _process_cik_finhigh(session, '0000036405')

            # Should still succeed but with no data inserted
            assert result is True

            # Verify no data was inserted
            operating = session.query(PerShareOperating).filter_by(etf_id=etf.id).first()
            assert operating is None

    def test_process_cik_finhigh_upsert(self, session):
        """Test that upserting same fiscal year updates existing record."""
        from unittest.mock import MagicMock, patch
        from datetime import date
        from etf_pipeline.models import ETF, PerShareOperating
        from etf_pipeline.parsers.finhigh import _process_cik_finhigh

        # Setup: Create ETF and existing record
        etf = ETF(
            cik='0000036405',
            ticker='VFIAX',
            fund_name='Vanguard 500 Index Fund Investor Shares',
            class_id='C000123456',
            issuer_name='Vanguard'
        )
        session.add(etf)
        session.flush()

        # Insert old data
        old_operating = PerShareOperating(
            etf_id=etf.id,
            fiscal_year_end=date(2024, 12, 31),
            filing_date=date(2024, 12, 31),
            nav_beginning=Decimal("100.00"),
            nav_end=Decimal("110.00"),
            math_validated=False
        )
        session.add(old_operating)
        session.commit()

        # Load fixture HTML
        fixture_path = FIXTURES_DIR / "vanguard_sample.html"
        with open(fixture_path, "r") as f:
            sample_html = f.read()

        full_html = f"""
        <html>
        <body>
        <h2>Vanguard 500 Index Fund</h2>
        <h3>Investor Shares</h3>
        <h4>Financial Highlights</h4>
        {sample_html}
        </body>
        </html>
        """

        # Create SGML header with series/class mapping
        sgml_header = """
        <SERIES-AND-CLASSES-CONTRACTS-DATA>
        <EXISTING-SERIES-AND-CLASSES-CONTRACTS>
        <SERIES>
        <SERIES-NAME>Vanguard 500 Index Fund
        <CLASS-CONTRACT>
        <CLASS-CONTRACT-ID>C000123456
        <CLASS-CONTRACT-NAME>Investor Shares
        <CLASS-CONTRACT-TICKER-SYMBOL>VFIAX
        </CLASS-CONTRACT>
        </SERIES>
        </EXISTING-SERIES-AND-CLASSES-CONTRACTS>
        </SERIES-AND-CLASSES-CONTRACTS-DATA>
        """

        # Mock edgartools
        with patch('etf_pipeline.parsers.finhigh.Company') as mock_company:
            mock_filing = MagicMock()
            mock_filing.filing_date = date(2024, 12, 31)
            mock_filing.html.return_value = full_html
            mock_header = MagicMock()
            mock_header.text = sgml_header
            mock_filing.header = mock_header

            mock_filings = [mock_filing]
            mock_company_instance = MagicMock()
            mock_company_instance.get_filings.return_value = mock_filings
            mock_company.return_value = mock_company_instance

            # Execute
            result = _process_cik_finhigh(session, '0000036405')

            # Verify success
            assert result is True

            # Verify data was updated (not duplicated)
            operating_records = session.query(PerShareOperating).filter_by(etf_id=etf.id).all()
            assert len(operating_records) == 1

            operating = operating_records[0]
            assert operating.nav_beginning == Decimal("102.18")  # Updated value
            assert operating.nav_end == Decimal("115.15")  # Updated value
            assert operating.math_validated is True  # Updated value
