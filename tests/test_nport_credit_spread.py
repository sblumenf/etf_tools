"""Tests for credit spread risk extraction in NPORT-P parser."""

from datetime import date
from decimal import Decimal
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import select

from etf_pipeline.models import CreditSpreadRisk, ETF
from etf_pipeline.parsers.nport import parse_nport


@pytest.fixture
def sample_etfs(session):
    """Create sample ETFs in the database."""
    etfs = [
        ETF(
            ticker="VOO",
            cik="0000036405",
            series_id="S000002839",
            issuer_name="Vanguard Group Inc",
            fund_name="Vanguard S&P 500 ETF",
        ),
    ]
    session.add_all(etfs)
    session.commit()
    return etfs


def _add_mock_fund_info(mock_report):
    """Helper to add fund_info to a mock FundReport."""
    fund_info = Mock()
    fund_info.total_assets = Decimal("10000000.00")
    fund_info.total_liabilities = Decimal("500000.00")
    fund_info.net_assets = Decimal("9500000.00")
    fund_info.cash_not_reported = Decimal("50000.00")
    fund_info.assets_invested = Decimal("9800000.00")
    fund_info.assets_misc_sec = Decimal("150000.00")
    fund_info.amt_pay_one_yr_banks_borr = Decimal("100000.00")
    fund_info.amt_pay_one_yr_ctrld_comp = Decimal("0.00")
    fund_info.amt_pay_one_yr_oth_affil = Decimal("0.00")
    fund_info.amt_pay_one_yr_other = Decimal("50000.00")
    fund_info.amt_pay_aft_one_yr_banks_borr = Decimal("250000.00")
    fund_info.amt_pay_aft_one_yr_ctrld_comp = Decimal("0.00")
    fund_info.amt_pay_aft_one_yr_oth_affil = Decimal("0.00")
    fund_info.amt_pay_aft_one_yr_other = Decimal("100000.00")
    fund_info.delay_deliv = Decimal("0.00")
    fund_info.stand_by_commit = Decimal("0.00")
    fund_info.liquidity_pref = Decimal("0.00")
    fund_info.is_non_cash_collateral = False
    mock_report.fund_info = fund_info


def test_parse_nport_extracts_credit_spread_risk(session, engine, sample_etfs, mock_nport_db):
    """Test that parse_nport extracts credit spread risk metrics from NPORT XML."""
    voo = sample_etfs[0]

    with patch("etf_pipeline.parsers.nport.Company") as mock_company:
        company = Mock()

        filing = Mock()
        filing.filing_date = date(2025, 1, 15)
        filing.accession_number = "0000000000-25-000000"
        filing.xml = Mock(return_value="""<?xml version="1.0"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/nport">
  <formData>
    <fundInfo>
      <creditSprdRiskInvstGrade period3Mon="1500.50" period1Yr="3000.75" period5Yr="6000.00" period10Yr="9000.25" period30Yr="12000.50"/>
      <creditSprdRiskNonInvstGrade period3Mon="2500.25" period1Yr="5000.50" period5Yr="10000.75" period10Yr="15000.00" period30Yr="20000.25"/>
    </fundInfo>
  </formData>
</edgarSubmission>""")
        filings = Mock()
        filings.empty = False
        filings.__len__ = Mock(return_value=1)
        filings.__getitem__ = Mock(side_effect=[filing])
        company.get_filings = Mock(return_value=filings)
        mock_company.return_value = company

        mock_report = Mock()
        mock_report.reporting_period = date(2024, 12, 31)
        mock_report.non_derivatives = []
        mock_report.derivatives = []

        general_info = Mock()
        general_info.series_id = voo.series_id
        mock_report.general_info = general_info

        _add_mock_fund_info(mock_report)

        with patch(
            "etf_pipeline.parsers.nport.FundReport.from_filing",
            return_value=mock_report,
        ):
            parse_nport(cik="36405")

    stmt = select(CreditSpreadRisk).where(CreditSpreadRisk.etf_id == voo.id)
    risk = session.execute(stmt).scalar_one()

    # Check investment grade metrics
    assert risk.invst_grade_3m == Decimal("1500.50")
    assert risk.invst_grade_1y == Decimal("3000.75")
    assert risk.invst_grade_5y == Decimal("6000.00")
    assert risk.invst_grade_10y == Decimal("9000.25")
    assert risk.invst_grade_30y == Decimal("12000.50")

    # Check non-investment grade metrics
    assert risk.non_invst_grade_3m == Decimal("2500.25")
    assert risk.non_invst_grade_1y == Decimal("5000.50")
    assert risk.non_invst_grade_5y == Decimal("10000.75")
    assert risk.non_invst_grade_10y == Decimal("15000.00")
    assert risk.non_invst_grade_30y == Decimal("20000.25")


def test_parse_nport_handles_missing_credit_spread_risk(session, engine, sample_etfs, mock_nport_db):
    """Test that parse_nport handles NPORT filings with no credit spread risk data."""
    voo = sample_etfs[0]

    with patch("etf_pipeline.parsers.nport.Company") as mock_company:
        company = Mock()

        filing = Mock()
        filing.filing_date = date(2025, 1, 15)
        filing.accession_number = "0000000000-25-000000"
        filing.xml = Mock(return_value="""<?xml version="1.0"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/nport">
  <formData>
    <fundInfo>
    </fundInfo>
  </formData>
</edgarSubmission>""")
        filings = Mock()
        filings.empty = False
        filings.__len__ = Mock(return_value=1)
        filings.__getitem__ = Mock(side_effect=[filing])
        company.get_filings = Mock(return_value=filings)
        mock_company.return_value = company

        mock_report = Mock()
        mock_report.reporting_period = date(2024, 12, 31)
        mock_report.non_derivatives = []
        mock_report.derivatives = []

        general_info = Mock()
        general_info.series_id = voo.series_id
        mock_report.general_info = general_info

        _add_mock_fund_info(mock_report)

        with patch(
            "etf_pipeline.parsers.nport.FundReport.from_filing",
            return_value=mock_report,
        ):
            parse_nport(cik="36405")

    stmt = select(CreditSpreadRisk).where(CreditSpreadRisk.etf_id == voo.id)
    risks = session.execute(stmt).scalars().all()

    assert len(risks) == 0
