"""Tests for 24F-2NT flows parser."""

from datetime import date
from decimal import Decimal
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import select

from etf_pipeline.models import ETF, FlowData
from etf_pipeline.parsers.flows import parse_flows


@pytest.fixture
def sample_etfs(session):
    """Create sample ETFs in the database."""
    etfs = [
        ETF(
            ticker="IVV",
            cik="0001100663",
            series_id="S000002823",
            issuer_name="iShares Trust",
            fund_name="iShares Core S&P 500 ETF",
        ),
        ETF(
            ticker="IJH",
            cik="0001100663",
            series_id="S000002824",
            issuer_name="iShares Trust",
            fund_name="iShares Core S&P Mid-Cap ETF",
        ),
        ETF(
            ticker="SPY",
            cik="0001064641",
            series_id="S000002753",
            issuer_name="SPDR S&P 500 ETF Trust",
            fund_name="SPDR S&P 500 ETF Trust",
        ),
    ]
    for etf in etfs:
        session.add(etf)
    session.commit()
    return etfs


# Sample XML content for testing
SAMPLE_XML_VALID = """<?xml version="1.0" ?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/twentyfourf2filer">
  <headerData>
    <filerInfo>
      <filer>
        <issuerCredentials>
          <cik>0001100663</cik>
        </issuerCredentials>
      </filer>
    </filerInfo>
  </headerData>
  <formData>
    <annualFilings>
      <annualFilingInfo>
        <item4>
          <lastDayOfFiscalYear>10/28/2024</lastDayOfFiscalYear>
        </item4>
        <item5>
          <aggregateSalePriceOfSecuritiesSold>86116742248.00</aggregateSalePriceOfSecuritiesSold>
          <aggregatePriceOfSecuritiesRedeemedOrRepurchasedInFiscalYear>60338350561.00</aggregatePriceOfSecuritiesRedeemedOrRepurchasedInFiscalYear>
          <netSales>25778391687.00</netSales>
        </item5>
      </annualFilingInfo>
    </annualFilings>
  </formData>
</edgarSubmission>
"""

SAMPLE_XML_WITH_COMMAS = """<?xml version="1.0" ?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/twentyfourf2filer">
  <formData>
    <annualFilings>
      <annualFilingInfo>
        <item4>
          <lastDayOfFiscalYear>12/31/2023</lastDayOfFiscalYear>
        </item4>
        <item5>
          <aggregateSalePriceOfSecuritiesSold>1,234,567.89</aggregateSalePriceOfSecuritiesSold>
          <aggregatePriceOfSecuritiesRedeemedOrRepurchasedInFiscalYear>987,654.32</aggregatePriceOfSecuritiesRedeemedOrRepurchasedInFiscalYear>
          <netSales>246,913.57</netSales>
        </item5>
      </annualFilingInfo>
    </annualFilings>
  </formData>
</edgarSubmission>
"""

SAMPLE_XML_WITH_NEGATIVES = """<?xml version="1.0" ?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/twentyfourf2filer">
  <formData>
    <annualFilings>
      <annualFilingInfo>
        <item4>
          <lastDayOfFiscalYear>06/30/2024</lastDayOfFiscalYear>
        </item4>
        <item5>
          <aggregateSalePriceOfSecuritiesSold>5000000.00</aggregateSalePriceOfSecuritiesSold>
          <aggregatePriceOfSecuritiesRedeemedOrRepurchasedInFiscalYear>8000000.00</aggregatePriceOfSecuritiesRedeemedOrRepurchasedInFiscalYear>
          <netSales>(3000000.00)</netSales>
        </item5>
      </annualFilingInfo>
    </annualFilings>
  </formData>
</edgarSubmission>
"""

SAMPLE_XML_MISSING_ITEM5 = """<?xml version="1.0" ?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/twentyfourf2filer">
  <formData>
    <annualFilings>
      <annualFilingInfo>
        <item4>
          <lastDayOfFiscalYear>12/31/2023</lastDayOfFiscalYear>
        </item4>
      </annualFilingInfo>
    </annualFilings>
  </formData>
</edgarSubmission>
"""

SAMPLE_XML_PARTIAL_ITEM5 = """<?xml version="1.0" ?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/twentyfourf2filer">
  <formData>
    <annualFilings>
      <annualFilingInfo>
        <item4>
          <lastDayOfFiscalYear>12/31/2023</lastDayOfFiscalYear>
        </item4>
        <item5>
          <aggregateSalePriceOfSecuritiesSold>1000000.00</aggregateSalePriceOfSecuritiesSold>
        </item5>
      </annualFilingInfo>
    </annualFilings>
  </formData>
</edgarSubmission>
"""


def create_mock_filing(xml_content):
    """Create a mock Filing object that returns the given XML."""
    mock_filing = Mock()
    mock_filing.xml.return_value = xml_content if xml_content else None
    return mock_filing


def test_parse_flows_happy_path(session, sample_etfs, mock_flows_db):
    """Test parsing valid 24F-2NT XML creates FlowData row."""
    with patch("etf_pipeline.parsers.flows.Company") as mock_company_class:
        mock_company = Mock()
        mock_filings = [create_mock_filing(SAMPLE_XML_VALID)]
        mock_company.get_filings.return_value = mock_filings
        mock_company_class.return_value = mock_company

        parse_flows(cik="1100663", clear_cache=False)

        # Verify FlowData was created
        stmt = select(FlowData).where(FlowData.cik == "0001100663")
        flow = session.execute(stmt).scalar_one()

        assert flow.cik == "0001100663"
        assert flow.fiscal_year_end == date(2024, 10, 28)
        assert flow.sales_value == Decimal("86116742248.00")
        assert flow.redemptions_value == Decimal("60338350561.00")
        assert flow.net_sales == Decimal("25778391687.00")


def test_parse_flows_money_with_commas(session, sample_etfs, mock_flows_db):
    """Test parsing money values with commas."""
    with patch("etf_pipeline.parsers.flows.Company") as mock_company_class:
        mock_company = Mock()
        mock_filings = [create_mock_filing(SAMPLE_XML_WITH_COMMAS)]
        mock_company.get_filings.return_value = mock_filings
        mock_company_class.return_value = mock_company

        parse_flows(cik="1100663", clear_cache=False)

        stmt = select(FlowData).where(FlowData.cik == "0001100663")
        flow = session.execute(stmt).scalar_one()

        assert flow.sales_value == Decimal("1234567.89")
        assert flow.redemptions_value == Decimal("987654.32")
        assert flow.net_sales == Decimal("246913.57")


def test_parse_flows_accounting_negatives(session, sample_etfs, mock_flows_db):
    """Test parsing accounting-notation negative values (parentheses)."""
    with patch("etf_pipeline.parsers.flows.Company") as mock_company_class:
        mock_company = Mock()
        mock_filings = [create_mock_filing(SAMPLE_XML_WITH_NEGATIVES)]
        mock_company.get_filings.return_value = mock_filings
        mock_company_class.return_value = mock_company

        parse_flows(cik="1100663", clear_cache=False)

        stmt = select(FlowData).where(FlowData.cik == "0001100663")
        flow = session.execute(stmt).scalar_one()

        assert flow.net_sales == Decimal("-3000000.00")


def test_parse_flows_upsert(session, sample_etfs, mock_flows_db):
    """Test running parser twice produces same result (upsert)."""
    # First run
    with patch("etf_pipeline.parsers.flows.Company") as mock_company_class:
        mock_company = Mock()
        mock_filings = [create_mock_filing(SAMPLE_XML_VALID)]
        mock_company.get_filings.return_value = mock_filings
        mock_company_class.return_value = mock_company

        parse_flows(cik="1100663", clear_cache=False)

    stmt = select(FlowData).where(FlowData.cik == "0001100663")
    flow1 = session.execute(stmt).scalar_one()
    flow1_id = flow1.id
    assert flow1.net_sales == Decimal("25778391687.00")

    # Second run with different values
    UPDATED_XML = SAMPLE_XML_VALID.replace(
        "25778391687.00", "30000000000.00"
    )
    with patch("etf_pipeline.parsers.flows.Company") as mock_company_class:
        mock_company = Mock()
        mock_filings = [create_mock_filing(UPDATED_XML)]
        mock_company.get_filings.return_value = mock_filings
        mock_company_class.return_value = mock_company

        parse_flows(cik="1100663", clear_cache=False)

    # Should update existing row, not create new one
    # Refresh the session to see the updates from parse_flows
    session.expire_all()
    stmt = select(FlowData).where(FlowData.cik == "0001100663")
    all_flows = session.execute(stmt).scalars().all()
    assert len(all_flows) == 1

    flow2 = all_flows[0]
    assert flow2.id == flow1_id  # Same record
    assert flow2.net_sales == Decimal("30000000000.00")  # Updated value


def test_parse_flows_no_filings(session, sample_etfs, caplog, mock_flows_db):
    """Test handling CIK with no 24F-2NT filings."""
    import logging
    caplog.set_level(logging.INFO)

    with patch("etf_pipeline.parsers.flows.Company") as mock_company_class:
        mock_company = Mock()
        # Empty list should evaluate to falsy
        mock_filings = []
        mock_company.get_filings.return_value = mock_filings
        mock_company_class.return_value = mock_company

        parse_flows(cik="1100663", clear_cache=False)

        # Should log info message, not create any records
        assert "No 24F-2NT filings found" in caplog.text
        stmt = select(FlowData).where(FlowData.cik == "0001100663")
        result = session.execute(stmt).scalar_one_or_none()
        assert result is None


def test_parse_flows_no_xml_content(session, sample_etfs, caplog, mock_flows_db):
    """Test handling filing with no XML content."""
    with patch("etf_pipeline.parsers.flows.Company") as mock_company_class:
        mock_company = Mock()
        mock_filings = [create_mock_filing(None)]
        mock_company.get_filings.return_value = mock_filings
        mock_company_class.return_value = mock_company

        parse_flows(cik="1100663", clear_cache=False)

        assert "has no XML content" in caplog.text
        stmt = select(FlowData).where(FlowData.cik == "0001100663")
        result = session.execute(stmt).scalar_one_or_none()
        assert result is None


def test_parse_flows_missing_item5(session, sample_etfs, caplog, mock_flows_db):
    """Test handling XML with missing item5 section."""
    with patch("etf_pipeline.parsers.flows.Company") as mock_company_class:
        mock_company = Mock()
        mock_filings = [create_mock_filing(SAMPLE_XML_MISSING_ITEM5)]
        mock_company.get_filings.return_value = mock_filings
        mock_company_class.return_value = mock_company

        parse_flows(cik="1100663", clear_cache=False)

        assert "item5 not found" in caplog.text
        stmt = select(FlowData).where(FlowData.cik == "0001100663")
        result = session.execute(stmt).scalar_one_or_none()
        assert result is None


def test_parse_flows_partial_item5(session, sample_etfs, mock_flows_db):
    """Test handling XML with partial item5 fields."""
    with patch("etf_pipeline.parsers.flows.Company") as mock_company_class:
        mock_company = Mock()
        mock_filings = [create_mock_filing(SAMPLE_XML_PARTIAL_ITEM5)]
        mock_company.get_filings.return_value = mock_filings
        mock_company_class.return_value = mock_company

        parse_flows(cik="1100663", clear_cache=False)

        # Should create record with available data
        stmt = select(FlowData).where(FlowData.cik == "0001100663")
        flow = session.execute(stmt).scalar_one()

        assert flow.sales_value == Decimal("1000000.00")
        assert flow.redemptions_value is None
        assert flow.net_sales is None


def test_parse_flows_with_cik_filter(session, sample_etfs, mock_flows_db):
    """Test processing only specified CIK."""
    with patch("etf_pipeline.parsers.flows.Company") as mock_company_class:
        mock_company = Mock()
        mock_filings = [create_mock_filing(SAMPLE_XML_VALID)]
        mock_company.get_filings.return_value = mock_filings
        mock_company_class.return_value = mock_company

        parse_flows(cik="1100663", clear_cache=False)

        # Should only call Company once with the filtered CIK
        mock_company_class.assert_called_once_with("0001100663")


def test_parse_flows_with_limit(session, sample_etfs, mock_flows_db):
    """Test limiting number of CIKs processed."""
    with patch("etf_pipeline.parsers.flows.Company") as mock_company_class:
        mock_company = Mock()
        mock_filings = [create_mock_filing(SAMPLE_XML_VALID)]
        mock_company.get_filings.return_value = mock_filings
        mock_company_class.return_value = mock_company

        parse_flows(limit=1, clear_cache=False)

        # Should only process first CIK (1064641)
        mock_company_class.assert_called_once_with("0001064641")


def test_parse_flows_with_ciks_param(session, sample_etfs, mock_flows_db):
    """Test passing explicit ciks list."""
    with patch("etf_pipeline.parsers.flows.Company") as mock_company_class:
        mock_company = Mock()
        mock_filings = [create_mock_filing(SAMPLE_XML_VALID)]
        mock_company.get_filings.return_value = mock_filings
        mock_company_class.return_value = mock_company

        parse_flows(ciks=["0001100663"], clear_cache=False)

        mock_company_class.assert_called_once_with("0001100663")


def test_parse_flows_no_etfs_in_db(session, capsys, mock_flows_db):
    """Test handling empty ETF table."""
    parse_flows(clear_cache=False)

    captured = capsys.readouterr()
    assert "No CIKs found in ETF table" in captured.out


def test_parse_flows_date_parsing(session, sample_etfs, mock_flows_db):
    """Test MM/DD/YYYY date format parsing."""
    with patch("etf_pipeline.parsers.flows.Company") as mock_company_class:
        mock_company = Mock()
        mock_filings = [create_mock_filing(SAMPLE_XML_VALID)]
        mock_company.get_filings.return_value = mock_filings
        mock_company_class.return_value = mock_company

        parse_flows(cik="1100663", clear_cache=False)

        stmt = select(FlowData).where(FlowData.cik == "0001100663")
        flow = session.execute(stmt).scalar_one()

        assert flow.fiscal_year_end == date(2024, 10, 28)


def test_parse_flows_clears_cache_by_default(session, sample_etfs, mock_flows_db):
    """Test that cache is cleared by default."""
    with patch("etf_pipeline.parsers.flows.Company") as mock_company_class:
        with patch("etf_pipeline.parsers.flows.edgar_clear_cache") as mock_clear:
            mock_company = Mock()
            mock_filings = [create_mock_filing(SAMPLE_XML_VALID)]
            mock_company.get_filings.return_value = mock_filings
            mock_company_class.return_value = mock_company
            mock_clear.return_value = {"files_deleted": 10, "bytes_freed": 1024 * 1024}

            parse_flows(cik="1100663", clear_cache=True)

            mock_clear.assert_called_once_with(dry_run=False)


def test_parse_flows_keeps_cache_when_flag_set(session, sample_etfs, mock_flows_db):
    """Test that cache is not cleared when keep_cache=True."""
    with patch("etf_pipeline.parsers.flows.Company") as mock_company_class:
        with patch("etf_pipeline.parsers.flows.edgar_clear_cache") as mock_clear:
            mock_company = Mock()
            mock_filings = [create_mock_filing(SAMPLE_XML_VALID)]
            mock_company.get_filings.return_value = mock_filings
            mock_company_class.return_value = mock_company

            parse_flows(cik="1100663", clear_cache=False)

            mock_clear.assert_not_called()


def test_parse_flows_writes_processing_log(session, sample_etfs, mock_flows_db):
    """Test that parse_flows writes ProcessingLog row with correct data."""
    from etf_pipeline.models import ProcessingLog

    with patch("etf_pipeline.parsers.flows.Company") as mock_company_class:
        mock_company = Mock()
        mock_filings = [create_mock_filing(SAMPLE_XML_VALID)]
        mock_company.get_filings.return_value = mock_filings
        mock_company_class.return_value = mock_company

        parse_flows(cik="1100663", clear_cache=False)

        # Verify ProcessingLog was created
        stmt = select(ProcessingLog).where(
            ProcessingLog.cik == "0001100663",
            ProcessingLog.parser_type == "flows"
        )
        log = session.execute(stmt).scalar_one_or_none()

        assert log is not None
        assert log.cik == "0001100663"
        assert log.parser_type == "flows"
        # The fixture has no explicit filing_date in XML, should use latest from filings
        assert log.latest_filing_date_seen is not None
        assert log.last_run_at is not None


def test_parse_flows_sets_filing_date(session, sample_etfs, mock_flows_db):
    """Test that parse_flows sets filing_date on inserted FlowData row."""
    # Create a mock filing with an explicit filing_date
    mock_filing = Mock()
    mock_filing.filing_date = date(2024, 10, 28)
    mock_filing.xml.return_value = SAMPLE_XML_VALID

    with patch("etf_pipeline.parsers.flows.Company") as mock_company_class:
        mock_company = Mock()
        mock_filings = [mock_filing]
        mock_company.get_filings.return_value = mock_filings
        mock_company_class.return_value = mock_company

        parse_flows(cik="1100663", clear_cache=False)

        # Verify FlowData has filing_date
        stmt = select(FlowData).where(FlowData.cik == "0001100663")
        flow = session.execute(stmt).scalar_one()
        assert flow.filing_date == date(2024, 10, 28)
