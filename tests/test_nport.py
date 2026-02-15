"""Tests for NPORT-P parser."""

import json
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import select

from etf_pipeline.models import (
    DebtSecurityDetail,
    Derivative,
    ETF,
    FundSnapshot,
    Holding,
    SecurityLending,
)
from etf_pipeline.parsers.nport import parse_nport


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
        ETF(
            ticker="VTV",
            cik="0000036405",
            series_id="S000002840",
            issuer_name="Vanguard Group Inc",
            fund_name="Vanguard Value ETF",
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


@pytest.fixture
def mock_fund_report():
    """Create a mock FundReport with sample holdings."""

    def create_mock_investment(name, cusip, value_usd, pct_value):
        """Create a mock InvestmentOrSecurity object."""
        inv = Mock(spec=['name', 'lei', 'title', 'cusip', 'balance', 'units', 'currency_code',
                         'value_usd', 'pct_value', 'asset_category', 'issuer_category',
                         'investment_country', 'is_restricted_security', 'fair_value_level',
                         'ticker', 'debt_security', 'identifiers'])
        inv.name = name
        inv.lei = "N/A"
        inv.title = "N/A"
        inv.cusip = cusip
        inv.balance = Decimal("100.0")
        inv.units = "NS"
        inv.currency_code = "USD"
        inv.value_usd = Decimal(str(value_usd))
        inv.pct_value = Decimal(str(pct_value))
        inv.asset_category = "EC"
        inv.issuer_category = "CORP"
        inv.investment_country = "US"
        inv.is_restricted_security = False
        inv.fair_value_level = "1"
        inv.ticker = name[:4]
        inv.debt_security = None

        identifiers = Mock()
        identifiers.isin = f"{cusip}XX"
        identifiers.ticker = name[:4]
        inv.identifiers = identifiers

        return inv

    def create_report_with_series_id(series_id):
        mock_report = Mock()
        mock_report.reporting_period = date(2024, 12, 31)
        mock_report.non_derivatives = [
            create_mock_investment("Apple Inc", "037833100", "1000000", "10.0"),
            create_mock_investment("Microsoft Corp", "594918104", "800000", "8.0"),
            create_mock_investment("Amazon.com Inc", "023135106", "600000", "6.0"),
        ]
        mock_report.derivatives = []

        # Add general_info with series_id
        general_info = Mock()
        general_info.series_id = series_id
        mock_report.general_info = general_info

        # Add fund_info with balance sheet data
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

        return mock_report

    return create_report_with_series_id


@pytest.fixture
def mock_edgar_company(mock_fund_report):
    """Mock the edgar Company class to return filings and FundReport."""
    with patch("etf_pipeline.parsers.nport.Company") as mock_class:

        # Map CIK to series IDs
        cik_to_series = {
            "0000036405": ["S000002839", "S000002840"],  # VOO, VTV
            "0001064641": ["S000002753"],  # SPY
        }

        def company_factory(cik):
            company = Mock()

            # Create mock filings with series_id attached
            series_list = cik_to_series.get(cik, [])
            filings_list = []
            for idx, series_id in enumerate(series_list):
                filing = Mock()
                filing.filing_date = date(2025, 1, 15)
                filing.series_id = series_id
                filing.accession_number = f"0000000000-25-{idx:06d}"
                filings_list.append(filing)

            # Mock filings collection
            filings_obj = Mock()
            filings_obj.empty = False
            filings_obj.__len__ = Mock(return_value=len(filings_list))
            filings_obj.__getitem__ = Mock(side_effect=lambda i: filings_list[i])

            company.get_filings = Mock(return_value=filings_obj)

            return company

        mock_class.side_effect = company_factory

        def fund_report_side_effect(filing):
            return mock_fund_report(filing.series_id)

        with patch(
            "etf_pipeline.parsers.nport.FundReport.from_filing",
            side_effect=fund_report_side_effect,
        ):
            yield mock_class


def test_parse_nport_creates_holdings(session, engine, sample_etfs, mock_edgar_company, mock_nport_db):
    """Test that parse_nport creates holding records from FundReport."""
    parse_nport(cik="36405")

    stmt = select(Holding).order_by(Holding.name)
    holdings = session.execute(stmt).scalars().all()

    assert len(holdings) == 6
    assert holdings[0].name == "Amazon.com Inc"
    assert holdings[0].cusip == "023135106"
    assert holdings[0].value_usd == Decimal("600000")
    assert holdings[0].pct_val == Decimal("6.0")
    assert holdings[0].asset_category == "EC"
    assert holdings[0].issuer_category == "CORP"
    assert holdings[0].country == "US"
    assert holdings[0].currency == "USD"
    assert holdings[0].fair_value_level == 1
    assert holdings[0].is_restricted is False
    assert holdings[0].report_date == date(2024, 12, 31)


def test_parse_nport_skips_existing_holdings(session, engine, sample_etfs, mock_edgar_company, mock_nport_db, caplog):
    """Test that parse_nport skips ETF when holdings already exist for report_date."""
    import logging
    caplog.set_level(logging.INFO)

    voo = session.execute(select(ETF).where(ETF.ticker == "VOO")).scalar_one()

    existing_holding = Holding(
        etf_id=voo.id,
        report_date=date(2024, 12, 31),
        filing_date=date(2024, 12, 31),
        name="Existing Holding",
        cusip="123456789",
        value_usd=Decimal("1000"),
        holding_key="123456789",
    )
    session.add(existing_holding)
    session.commit()

    parse_nport(cik="36405")

    stmt = select(Holding).where(Holding.etf_id == voo.id)
    holdings = session.execute(stmt).scalars().all()

    assert len(holdings) == 1
    assert holdings[0].name == "Existing Holding"
    assert "already exist" in caplog.text


def test_parse_nport_no_nport_filing(session, engine, sample_etfs, mock_nport_db, caplog):
    """Test that parse_nport handles CIK with no NPORT-P filing."""
    with patch("etf_pipeline.parsers.nport.Company") as mock_company:
        company = Mock()
        filings = Mock()
        filings.empty = True
        filings.__len__ = Mock(return_value=0)
        company.get_filings = Mock(return_value=filings)
        mock_company.return_value = company

        parse_nport(cik="36405")

    stmt = select(Holding)
    holdings = session.execute(stmt).scalars().all()
    assert len(holdings) == 0
    assert "No NPORT-P filings found" in caplog.text


def test_parse_nport_with_limit(session, engine, sample_etfs, mock_edgar_company, mock_nport_db):
    """Test that --limit flag works correctly."""
    parse_nport(limit=1)

    stmt = select(Holding)
    holdings = session.execute(stmt).scalars().all()

    assert len(holdings) == 6


def test_parse_nport_with_cik_filter(session, engine, sample_etfs, mock_edgar_company, mock_nport_db):
    """Test that --cik flag works correctly."""
    parse_nport(cik="1064641")

    stmt = select(Holding)
    holdings = session.execute(stmt).scalars().all()

    assert len(holdings) == 3

    spy = session.execute(select(ETF).where(ETF.ticker == "SPY")).scalar_one()
    assert all(h.etf_id == spy.id for h in holdings)


def test_parse_nport_invalid_cik(session, engine, sample_etfs, mock_edgar_company, mock_nport_db, capsys):
    """Test behavior when requested CIK is not in database."""
    parse_nport(cik="99999")

    captured = capsys.readouterr()
    assert "not found in database" in captured.out

    stmt = select(Holding)
    holdings = session.execute(stmt).scalars().all()
    assert len(holdings) == 0


def test_parse_nport_no_etfs_in_db(session, engine, mock_nport_db, capsys):
    """Test behavior when no ETFs exist in database."""
    parse_nport()

    captured = capsys.readouterr()
    assert "No ETFs found in database" in captured.out


def test_parse_nport_handles_na_values(session, engine, sample_etfs, mock_nport_db):
    """Test that N/A values are converted to NULL."""

    def create_mock_investment_with_na():
        inv = Mock()
        inv.name = "Test Security"
        inv.lei = "N/A"
        inv.title = "N/A"
        inv.cusip = "N/A"
        inv.balance = None
        inv.units = "NS"
        inv.currency_code = None
        inv.value_usd = Decimal("1000")
        inv.pct_value = Decimal("1.0")
        inv.asset_category = "EC"
        inv.issuer_category = "CORP"
        inv.investment_country = "US"
        inv.is_restricted_security = None
        inv.fair_value_level = None
        inv.ticker = None
        inv.identifiers = None
        inv.debt_security = None
        return inv

    def create_report_with_series(series_id):
        mock_report = Mock()
        mock_report.reporting_period = date(2024, 12, 31)
        mock_report.non_derivatives = [create_mock_investment_with_na()]
        mock_report.derivatives = []
        general_info = Mock()
        general_info.series_id = series_id
        mock_report.general_info = general_info
        # Add fund_info
        fund_info = Mock(spec=['total_assets', 'total_liabilities', 'net_assets'])
        fund_info.total_assets = Decimal("1000000.00")
        fund_info.total_liabilities = Decimal("50000.00")
        fund_info.net_assets = Decimal("950000.00")
        mock_report.fund_info = fund_info
        return mock_report

    with patch("etf_pipeline.parsers.nport.Company") as mock_company:
        company = Mock()

        filing1 = Mock()
        filing1.filing_date = date(2025, 1, 15)
        filing1.accession_number = "0000000000-25-000000"
        filing2 = Mock()
        filing2.filing_date = date(2025, 1, 15)
        filing2.accession_number = "0000000000-25-000001"

        filings = Mock()
        filings.empty = False
        filings.__len__ = Mock(return_value=2)
        filings.__getitem__ = Mock(side_effect=[filing1, filing2])
        company.get_filings = Mock(return_value=filings)
        mock_company.return_value = company

        call_count = [0]
        def fund_report_side_effect(filing):
            series_ids = ["S000002839", "S000002840"]
            series_id = series_ids[call_count[0]]
            call_count[0] += 1
            return create_report_with_series(series_id)

        with patch(
            "etf_pipeline.parsers.nport.FundReport.from_filing", side_effect=fund_report_side_effect
        ):
            parse_nport(cik="36405")

    stmt = select(Holding)
    holdings = session.execute(stmt).scalars().all()

    assert len(holdings) == 2
    holding = holdings[0]
    assert holding.cusip is None
    assert holding.lei is None
    assert holding.isin is None
    assert holding.ticker is None
    assert holding.fair_value_level is None
    assert holding.is_restricted is False


def test_parse_nport_deduplicates_holdings_with_same_cusip(session, engine, sample_etfs, mock_nport_db, caplog):
    """Test that parse_nport deduplicates holdings with duplicate CUSIPs and logs a warning."""
    import logging
    caplog.set_level(logging.WARNING)

    def create_mock_investment_with_cusip(name, cusip, value_usd):
        inv = Mock()
        inv.name = name
        inv.lei = "N/A"
        inv.title = "N/A"
        inv.cusip = cusip
        inv.balance = Decimal("100.0")
        inv.units = "NS"
        inv.currency_code = "USD"
        inv.value_usd = Decimal(str(value_usd))
        inv.pct_value = Decimal("5.0")
        inv.asset_category = "EC"
        inv.issuer_category = "CORP"
        inv.investment_country = "US"
        inv.is_restricted_security = False
        inv.fair_value_level = "1"
        inv.ticker = name[:4]
        inv.debt_security = None

        identifiers = Mock()
        identifiers.isin = f"{cusip}XX"
        identifiers.ticker = name[:4]
        inv.identifiers = identifiers

        return inv

    def create_report_with_duplicates(series_id):
        mock_report = Mock()
        mock_report.reporting_period = date(2024, 12, 31)
        # Create two holdings with the same CUSIP
        mock_report.non_derivatives = [
            create_mock_investment_with_cusip("Apple Inc", "037833100", "1000000"),
            create_mock_investment_with_cusip("Apple Inc Duplicate", "037833100", "500000"),
            create_mock_investment_with_cusip("Microsoft Corp", "594918104", "800000"),
        ]
        mock_report.derivatives = []

        general_info = Mock()
        general_info.series_id = series_id
        mock_report.general_info = general_info

        _add_mock_fund_info(mock_report)
        return mock_report

    with patch("etf_pipeline.parsers.nport.Company") as mock_company:
        company = Mock()

        filing1 = Mock()
        filing1.filing_date = date(2025, 1, 15)
        filing1.accession_number = "0000000000-25-000000"

        filings = Mock()
        filings.empty = False
        filings.__len__ = Mock(return_value=1)
        filings.__getitem__ = Mock(side_effect=[filing1])
        company.get_filings = Mock(return_value=filings)
        mock_company.return_value = company

        with patch(
            "etf_pipeline.parsers.nport.FundReport.from_filing",
            return_value=create_report_with_duplicates("S000002839"),
        ):
            parse_nport(cik="36405")

    # Verify only 2 holdings were inserted (duplicate was skipped)
    stmt = select(Holding)
    holdings = session.execute(stmt).scalars().all()
    assert len(holdings) == 2

    # Verify the non-duplicate holdings were inserted
    cusips = [h.cusip for h in holdings]
    assert "037833100" in cusips
    assert "594918104" in cusips
    assert cusips.count("037833100") == 1  # Only one instance of the duplicate CUSIP

    # Verify warning was logged about the duplicate
    assert "Skipping duplicate holding_key 037833100" in caplog.text

    # Verify processing_log was still updated (no constraint violation crash)
    from etf_pipeline.models import ProcessingLog
    stmt = select(ProcessingLog).where(
        ProcessingLog.cik == "0000036405",
        ProcessingLog.parser_type == "nport"
    )
    log = session.execute(stmt).scalar_one_or_none()
    assert log is not None
    assert log.latest_filing_date_seen == date(2025, 1, 15)


def test_parse_nport_does_not_deduplicate_none_cusip_holdings(session, engine, sample_etfs, mock_nport_db, caplog):
    """Test that parse_nport does not deduplicate holdings with cusip = None."""
    import logging
    caplog.set_level(logging.WARNING)

    def create_mock_investment_without_cusip(name):
        inv = Mock()
        inv.name = name
        inv.lei = "N/A"
        inv.title = "N/A"
        inv.cusip = None
        inv.balance = Decimal("100.0")
        inv.units = "NS"
        inv.currency_code = "USD"
        inv.value_usd = Decimal("1000000")
        inv.pct_value = Decimal("5.0")
        inv.asset_category = "EC"
        inv.issuer_category = "CORP"
        inv.investment_country = "US"
        inv.is_restricted_security = False
        inv.fair_value_level = "1"
        inv.ticker = name[:4]
        inv.debt_security = None

        identifiers = Mock()
        identifiers.isin = None
        identifiers.ticker = name[:4]
        inv.identifiers = identifiers

        return inv

    def create_report_with_none_cusips(series_id):
        mock_report = Mock()
        mock_report.reporting_period = date(2024, 12, 31)
        # Create two holdings with cusip = None (different names)
        mock_report.non_derivatives = [
            create_mock_investment_without_cusip("Security A"),
            create_mock_investment_without_cusip("Security B"),
        ]
        mock_report.derivatives = []

        general_info = Mock()
        general_info.series_id = series_id
        mock_report.general_info = general_info

        _add_mock_fund_info(mock_report)
        return mock_report

    with patch("etf_pipeline.parsers.nport.Company") as mock_company:
        company = Mock()

        filing1 = Mock()
        filing1.filing_date = date(2025, 1, 15)
        filing1.accession_number = "0000000000-25-000000"

        filings = Mock()
        filings.empty = False
        filings.__len__ = Mock(return_value=1)
        filings.__getitem__ = Mock(side_effect=[filing1])
        company.get_filings = Mock(return_value=filings)
        mock_company.return_value = company

        with patch(
            "etf_pipeline.parsers.nport.FundReport.from_filing",
            return_value=create_report_with_none_cusips("S000002839"),
        ):
            parse_nport(cik="36405")

    # Verify both holdings were inserted (not deduplicated)
    stmt = select(Holding)
    holdings = session.execute(stmt).scalars().all()
    assert len(holdings) == 2

    # Verify the holdings have different names
    names = sorted([h.name for h in holdings])
    assert names == ["Security A", "Security B"]

    # Verify both have cusip = None
    assert all(h.cusip is None for h in holdings)

    # Verify no warning was logged about duplicates
    assert "Skipping duplicate CUSIP" not in caplog.text


def test_parse_nport_deduplicates_derivatives_with_same_key(session, engine, sample_etfs, mock_nport_db, caplog):
    """Test that parse_nport deduplicates derivatives with same derivative_type and underlying_name."""
    import logging
    caplog.set_level(logging.WARNING)

    def create_mock_derivative(deriv_type, underlying_name, underlying_cusip, counterparty):
        """Create a mock InvestmentOrSecurity object with derivative_info."""
        inv = Mock()
        inv.name = "Derivative Investment"
        inv.derivative_info = Mock()
        inv.derivative_info.derivative_category = deriv_type

        fut = Mock()
        fut.counterparty_name = counterparty
        fut.counterparty_lei = "123456789012345678AA"
        fut.reference_entity_name = underlying_name
        fut.reference_entity_cusip = underlying_cusip
        fut.notional_amount = Decimal("100000.00")
        fut.expiration_date = "2025-06-30"
        inv.derivative_info.future_derivative = fut
        inv.derivative_info.forward_derivative = None
        inv.derivative_info.option_derivative = None
        inv.derivative_info.swap_derivative = None
        inv.derivative_info.swaption_derivative = None

        return inv

    def create_report_with_duplicate_derivatives(series_id):
        mock_report = Mock()
        mock_report.reporting_period = date(2024, 12, 31)
        mock_report.non_derivatives = []
        # Create two derivatives with same type and underlying_name but different underlying_cusip
        mock_report.derivatives = [
            create_mock_derivative("FUT", "S&P 500 Index", "12345678X", "Goldman Sachs"),
            create_mock_derivative("FUT", "S&P 500 Index", "87654321X", "Morgan Stanley"),
            create_mock_derivative("FUT", "NASDAQ Index", "11111111X", "JP Morgan"),
        ]

        general_info = Mock()
        general_info.series_id = series_id
        mock_report.general_info = general_info

        _add_mock_fund_info(mock_report)
        return mock_report

    with patch("etf_pipeline.parsers.nport.Company") as mock_company:
        company = Mock()

        filing1 = Mock()
        filing1.filing_date = date(2025, 1, 15)
        filing1.accession_number = "0000000000-25-000000"

        filings = Mock()
        filings.empty = False
        filings.__len__ = Mock(return_value=1)
        filings.__getitem__ = Mock(side_effect=[filing1])
        company.get_filings = Mock(return_value=filings)
        mock_company.return_value = company

        with patch(
            "etf_pipeline.parsers.nport.FundReport.from_filing",
            return_value=create_report_with_duplicate_derivatives("S000002839"),
        ):
            parse_nport(cik="36405")

    # Verify only 2 derivatives were inserted (duplicate was skipped)
    stmt = select(Derivative)
    derivatives = session.execute(stmt).scalars().all()
    assert len(derivatives) == 2

    # Verify the non-duplicate derivatives were inserted
    underlying_names = sorted([d.underlying_name for d in derivatives])
    assert underlying_names == ["NASDAQ Index", "S&P 500 Index"]

    # Verify warning was logged about the duplicate
    assert "Skipping duplicate derivative ('FUT', 'S&P 500 Index')" in caplog.text


def test_parse_nport_fundreport_parse_error(session, engine, sample_etfs, mock_nport_db, caplog):
    """Test that parser handles FundReport.from_filing() errors gracefully."""
    with patch("etf_pipeline.parsers.nport.Company") as mock_company:
        company = Mock()

        filing1 = Mock()
        filing1.filing_date = date(2025, 1, 15)
        filing1.accession_number = "0000000000-25-000000"
        filing2 = Mock()
        filing2.filing_date = date(2025, 1, 15)
        filing2.accession_number = "0000000000-25-000001"

        filings = Mock()
        filings.empty = False
        filings.__len__ = Mock(return_value=2)
        filings.__getitem__ = Mock(side_effect=[filing1, filing2])
        company.get_filings = Mock(return_value=filings)
        mock_company.return_value = company

        with patch(
            "etf_pipeline.parsers.nport.FundReport.from_filing",
            side_effect=Exception("Parse error"),
        ):
            parse_nport(cik="36405")

    stmt = select(Holding)
    holdings = session.execute(stmt).scalars().all()
    assert len(holdings) == 0
    assert "Failed to parse filing" in caplog.text


def test_parse_nport_creates_derivatives(session, engine, sample_etfs, mock_nport_db):
    """Test that parse_nport creates derivative records from FundReport."""

    def create_mock_derivative(deriv_type, underlying_name, counterparty):
        """Create a mock InvestmentOrSecurity object with derivative_info."""
        inv = Mock()
        inv.name = "Derivative Investment"
        inv.derivative_info = Mock()
        inv.derivative_info.derivative_category = deriv_type

        if deriv_type == "FUT":
            fut = Mock()
            fut.counterparty_name = counterparty
            fut.counterparty_lei = "123456789012345678AA"
            fut.reference_entity_name = underlying_name
            fut.reference_entity_cusip = "12345678X"
            fut.notional_amount = Decimal("100000.00")
            fut.expiration_date = "2025-06-30"
            inv.derivative_info.future_derivative = fut
            inv.derivative_info.forward_derivative = None
            inv.derivative_info.option_derivative = None
            inv.derivative_info.swap_derivative = None
            inv.derivative_info.swaption_derivative = None

        elif deriv_type == "OPT":
            opt = Mock()
            opt.counterparty_name = counterparty
            opt.counterparty_lei = "123456789012345678BB"
            opt.reference_entity_name = underlying_name
            opt.reference_entity_cusip = "87654321X"
            opt.share_number = Decimal("1000")
            opt.delta = Decimal("0.5")
            opt.expiration_date = "2025-03-15"
            inv.derivative_info.option_derivative = opt
            inv.derivative_info.forward_derivative = None
            inv.derivative_info.future_derivative = None
            inv.derivative_info.swap_derivative = None
            inv.derivative_info.swaption_derivative = None

        elif deriv_type == "SWP":
            swp = Mock()
            swp.counterparty_name = counterparty
            swp.counterparty_lei = "123456789012345678CC"
            swp.deriv_addl_name = underlying_name
            swp.deriv_addl_cusip = "11111111X"
            swp.reference_entity_name = None
            swp.reference_entity_cusip = None
            swp.notional_amount = Decimal("5000000.00")
            swp.termination_date = "2030-12-31"
            inv.derivative_info.swap_derivative = swp
            inv.derivative_info.forward_derivative = None
            inv.derivative_info.future_derivative = None
            inv.derivative_info.option_derivative = None
            inv.derivative_info.swaption_derivative = None

        return inv

    def create_report_with_series(series_id):
        mock_report = Mock()
        mock_report.reporting_period = date(2024, 12, 31)
        mock_report.non_derivatives = []
        mock_report.derivatives = [
            create_mock_derivative("FUT", "S&P 500 Index", "Goldman Sachs"),
            create_mock_derivative("OPT", "Apple Inc", "Morgan Stanley"),
            create_mock_derivative("SWP", "LIBOR", "JP Morgan"),
        ]
        general_info = Mock()
        general_info.series_id = series_id
        mock_report.general_info = general_info
        _add_mock_fund_info(mock_report)
        return mock_report

    with patch("etf_pipeline.parsers.nport.Company") as mock_company:
        company = Mock()

        filing1 = Mock()
        filing1.filing_date = date(2025, 1, 15)
        filing1.accession_number = "0000000000-25-000000"
        filing2 = Mock()
        filing2.filing_date = date(2025, 1, 15)
        filing2.accession_number = "0000000000-25-000001"

        filings = Mock()
        filings.empty = False
        filings.__len__ = Mock(return_value=2)
        filings.__getitem__ = Mock(side_effect=[filing1, filing2])
        company.get_filings = Mock(return_value=filings)
        mock_company.return_value = company

        call_count = [0]
        def fund_report_side_effect(filing):
            series_ids = ["S000002839", "S000002840"]
            series_id = series_ids[call_count[0]]
            call_count[0] += 1
            return create_report_with_series(series_id)

        with patch(
            "etf_pipeline.parsers.nport.FundReport.from_filing", side_effect=fund_report_side_effect
        ):
            parse_nport(cik="36405")

    stmt = select(Derivative).order_by(Derivative.derivative_type)
    derivatives = session.execute(stmt).scalars().all()

    assert len(derivatives) == 6

    future_derivs = [d for d in derivatives if d.derivative_type == "FUT"]
    assert len(future_derivs) == 2
    fut = future_derivs[0]
    assert fut.underlying_name == "S&P 500 Index"
    assert fut.underlying_cusip == "12345678X"
    assert fut.notional_value == Decimal("100000.00")
    assert fut.counterparty == "Goldman Sachs"
    assert fut.counterparty_lei == "123456789012345678AA"
    assert fut.expiration_date == date(2025, 6, 30)
    assert fut.delta is None
    assert fut.report_date == date(2024, 12, 31)

    option_derivs = [d for d in derivatives if d.derivative_type == "OPT"]
    assert len(option_derivs) == 2
    opt = option_derivs[0]
    assert opt.underlying_name == "Apple Inc"
    assert opt.underlying_cusip == "87654321X"
    assert opt.notional_value == Decimal("1000")
    assert opt.counterparty == "Morgan Stanley"
    assert opt.counterparty_lei == "123456789012345678BB"
    assert opt.delta == Decimal("0.5")
    assert opt.expiration_date == date(2025, 3, 15)
    assert opt.report_date == date(2024, 12, 31)

    swap_derivs = [d for d in derivatives if d.derivative_type == "SWP"]
    assert len(swap_derivs) == 2
    swp = swap_derivs[0]
    assert swp.underlying_name == "LIBOR"
    assert swp.underlying_cusip == "11111111X"
    assert swp.notional_value == Decimal("5000000.00")
    assert swp.counterparty == "JP Morgan"
    assert swp.counterparty_lei == "123456789012345678CC"
    assert swp.expiration_date == date(2030, 12, 31)
    assert swp.delta is None
    assert swp.report_date == date(2024, 12, 31)


def test_parse_nport_etf_with_no_derivatives(session, engine, sample_etfs, mock_nport_db):
    """Test that parse_nport handles ETF with no derivatives without error."""
    def create_report_with_series(series_id):
        mock_report = Mock()
        mock_report.reporting_period = date(2024, 12, 31)
        mock_report.non_derivatives = []
        mock_report.derivatives = []
        general_info = Mock()
        general_info.series_id = series_id
        mock_report.general_info = general_info
        _add_mock_fund_info(mock_report)
        return mock_report

    with patch("etf_pipeline.parsers.nport.Company") as mock_company:
        company = Mock()

        filing1 = Mock()
        filing1.filing_date = date(2025, 1, 15)
        filing1.accession_number = "0000000000-25-000000"
        filing2 = Mock()
        filing2.filing_date = date(2025, 1, 15)
        filing2.accession_number = "0000000000-25-000001"

        filings = Mock()
        filings.empty = False
        filings.__len__ = Mock(return_value=2)
        filings.__getitem__ = Mock(side_effect=[filing1, filing2])
        company.get_filings = Mock(return_value=filings)
        mock_company.return_value = company

        call_count = [0]
        def fund_report_side_effect(filing):
            series_ids = ["S000002839", "S000002840"]
            series_id = series_ids[call_count[0]]
            call_count[0] += 1
            return create_report_with_series(series_id)

        with patch(
            "etf_pipeline.parsers.nport.FundReport.from_filing", side_effect=fund_report_side_effect
        ):
            parse_nport(cik="36405")

    stmt = select(Derivative)
    derivatives = session.execute(stmt).scalars().all()
    assert len(derivatives) == 0


def test_parse_nport_skips_derivatives_when_holdings_exist(session, engine, sample_etfs, mock_nport_db):
    """Test that parse_nport skips derivatives when holdings already exist for report_date."""
    voo = session.execute(select(ETF).where(ETF.ticker == "VOO")).scalar_one()

    existing_holding = Holding(
        etf_id=voo.id,
        report_date=date(2024, 12, 31),
        filing_date=date(2024, 12, 31),
        name="Existing Holding",
        cusip="123456789",
        value_usd=Decimal("1000"),
        holding_key="123456789",
    )
    session.add(existing_holding)
    session.commit()

    def create_mock_derivative(deriv_type):
        inv = Mock()
        inv.name = "Derivative"
        inv.derivative_info = Mock()
        inv.derivative_info.derivative_category = deriv_type
        fut = Mock()
        fut.counterparty_name = "Test"
        fut.counterparty_lei = "123456789012345678AA"
        fut.reference_entity_name = "Test Index"
        fut.reference_entity_cusip = "12345678X"
        fut.notional_amount = Decimal("100000.00")
        fut.expiration_date = "2025-06-30"
        inv.derivative_info.future_derivative = fut
        inv.derivative_info.forward_derivative = None
        inv.derivative_info.option_derivative = None
        inv.derivative_info.swap_derivative = None
        inv.derivative_info.swaption_derivative = None
        return inv

    def create_report_with_series(series_id):
        mock_report = Mock()
        mock_report.reporting_period = date(2024, 12, 31)
        mock_report.non_derivatives = []
        mock_report.derivatives = [create_mock_derivative("FUT")]
        general_info = Mock()
        general_info.series_id = series_id
        mock_report.general_info = general_info
        _add_mock_fund_info(mock_report)
        return mock_report

    with patch("etf_pipeline.parsers.nport.Company") as mock_company:
        company = Mock()

        filing1 = Mock()
        filing1.filing_date = date(2025, 1, 15)
        filing1.accession_number = "0000000000-25-000000"
        filing2 = Mock()
        filing2.filing_date = date(2025, 1, 15)
        filing2.accession_number = "0000000000-25-000001"

        filings = Mock()
        filings.empty = False
        filings.__len__ = Mock(return_value=2)
        filings.__getitem__ = Mock(side_effect=[filing1, filing2])
        company.get_filings = Mock(return_value=filings)
        mock_company.return_value = company

        call_count = [0]
        def fund_report_side_effect(filing):
            series_ids = ["S000002839", "S000002840"]
            series_id = series_ids[call_count[0]]
            call_count[0] += 1
            return create_report_with_series(series_id)

        with patch(
            "etf_pipeline.parsers.nport.FundReport.from_filing", side_effect=fund_report_side_effect
        ):
            parse_nport(cik="36405")

    stmt = select(Derivative).where(Derivative.etf_id == voo.id)
    voo_derivatives = session.execute(stmt).scalars().all()
    assert len(voo_derivatives) == 0


def test_parse_nport_creates_forward_and_swaption_derivatives(session, engine, sample_etfs, mock_nport_db):
    """Test that parse_nport creates forward and swaption derivative records from FundReport."""

    def create_mock_derivative(deriv_type, underlying_name, counterparty):
        """Create a mock InvestmentOrSecurity object with derivative_info."""
        inv = Mock()
        inv.name = "Derivative Investment"
        inv.derivative_info = Mock()
        inv.derivative_info.derivative_category = deriv_type

        if deriv_type == "FWD":
            fwd = Mock()
            fwd.counterparty_name = counterparty
            fwd.counterparty_lei = "123456789012345678DD"
            fwd.deriv_addl_name = underlying_name
            fwd.deriv_addl_cusip = "22222222X"
            fwd.amount_sold = Decimal("2500000.00")
            fwd.amount_purchased = None
            fwd.settlement_date = "2025-09-30"
            inv.derivative_info.forward_derivative = fwd
            inv.derivative_info.future_derivative = None
            inv.derivative_info.option_derivative = None
            inv.derivative_info.swap_derivative = None
            inv.derivative_info.swaption_derivative = None

        elif deriv_type == "SWAPTION":
            swo = Mock()
            swo.counterparty_name = counterparty
            swo.counterparty_lei = "123456789012345678EE"
            swo.expiration_date = "2026-12-31"
            swap_nested = Mock()
            swap_nested.notional_amount = Decimal("10000000.00")
            swo.swap_derivative = swap_nested
            inv.derivative_info.swaption_derivative = swo
            inv.derivative_info.forward_derivative = None
            inv.derivative_info.future_derivative = None
            inv.derivative_info.option_derivative = None
            inv.derivative_info.swap_derivative = None

        return inv

    def create_report_with_series(series_id):
        mock_report = Mock()
        mock_report.reporting_period = date(2024, 12, 31)
        mock_report.non_derivatives = []
        mock_report.derivatives = [
            create_mock_derivative("FWD", "EUR/USD Forward", "Citibank"),
            create_mock_derivative("SWAPTION", None, "Bank of America"),
        ]
        general_info = Mock()
        general_info.series_id = series_id
        mock_report.general_info = general_info
        _add_mock_fund_info(mock_report)
        return mock_report

    with patch("etf_pipeline.parsers.nport.Company") as mock_company:
        company = Mock()

        filing1 = Mock()
        filing1.filing_date = date(2025, 1, 15)
        filing1.accession_number = "0000000000-25-000000"
        filing2 = Mock()
        filing2.filing_date = date(2025, 1, 15)
        filing2.accession_number = "0000000000-25-000001"

        filings = Mock()
        filings.empty = False
        filings.__len__ = Mock(return_value=2)
        filings.__getitem__ = Mock(side_effect=[filing1, filing2])
        company.get_filings = Mock(return_value=filings)
        mock_company.return_value = company

        call_count = [0]
        def fund_report_side_effect(filing):
            series_ids = ["S000002839", "S000002840"]
            series_id = series_ids[call_count[0]]
            call_count[0] += 1
            return create_report_with_series(series_id)

        with patch(
            "etf_pipeline.parsers.nport.FundReport.from_filing", side_effect=fund_report_side_effect
        ):
            parse_nport(cik="36405")

    stmt = select(Derivative).order_by(Derivative.derivative_type)
    derivatives = session.execute(stmt).scalars().all()

    assert len(derivatives) == 4

    forward_derivs = [d for d in derivatives if d.derivative_type == "FWD"]
    assert len(forward_derivs) == 2
    fwd = forward_derivs[0]
    assert fwd.underlying_name == "EUR/USD Forward"
    assert fwd.underlying_cusip == "22222222X"
    assert fwd.notional_value == Decimal("2500000.00")
    assert fwd.counterparty == "Citibank"
    assert fwd.counterparty_lei == "123456789012345678DD"
    assert fwd.expiration_date == date(2025, 9, 30)
    assert fwd.delta is None
    assert fwd.report_date == date(2024, 12, 31)

    swaption_derivs = [d for d in derivatives if d.derivative_type == "SWAPTION"]
    assert len(swaption_derivs) == 2
    swo = swaption_derivs[0]
    assert swo.underlying_name is None
    assert swo.underlying_cusip is None
    assert swo.notional_value is None
    assert swo.counterparty == "Bank of America"
    assert swo.counterparty_lei == "123456789012345678EE"
    assert swo.expiration_date == date(2026, 12, 31)
    assert swo.delta is None
    assert swo.report_date == date(2024, 12, 31)


def test_parse_nport_option_derivative_index_name_fallback(session, engine, sample_etfs, mock_nport_db):
    """Test that option derivatives use index_name when reference_entity_name is None."""

    def create_mock_option_with_index():
        """Create a mock InvestmentOrSecurity with option using index_name."""
        inv = Mock()
        inv.name = "Index Option Derivative"
        inv.derivative_info = Mock()
        inv.derivative_info.derivative_category = "OPT"

        opt = Mock()
        opt.counterparty_name = "Morgan Stanley"
        opt.counterparty_lei = "123456789012345678BB"
        opt.reference_entity_name = None
        opt.index_name = "S&P 500 Index"
        opt.reference_entity_cusip = "87654321X"
        opt.share_number = Decimal("1000")
        opt.delta = Decimal("0.5")
        opt.expiration_date = "2025-03-15"
        inv.derivative_info.option_derivative = opt
        inv.derivative_info.forward_derivative = None
        inv.derivative_info.future_derivative = None
        inv.derivative_info.swap_derivative = None
        inv.derivative_info.swaption_derivative = None

        return inv

    def create_report_with_series(series_id):
        mock_report = Mock()
        mock_report.reporting_period = date(2024, 12, 31)
        mock_report.non_derivatives = []
        mock_report.derivatives = [create_mock_option_with_index()]
        general_info = Mock()
        general_info.series_id = series_id
        mock_report.general_info = general_info
        _add_mock_fund_info(mock_report)
        return mock_report

    with patch("etf_pipeline.parsers.nport.Company") as mock_company:
        company = Mock()

        filing1 = Mock()
        filing1.filing_date = date(2025, 1, 15)
        filing1.accession_number = "0000000000-25-000000"

        filings = Mock()
        filings.empty = False
        filings.__len__ = Mock(return_value=1)
        filings.__getitem__ = Mock(side_effect=[filing1])
        company.get_filings = Mock(return_value=filings)
        mock_company.return_value = company

        with patch(
            "etf_pipeline.parsers.nport.FundReport.from_filing",
            return_value=create_report_with_series("S000002839"),
        ):
            parse_nport(cik="36405")

    stmt = select(Derivative).where(Derivative.derivative_type == "OPT")
    derivatives = session.execute(stmt).scalars().all()

    assert len(derivatives) == 1
    opt = derivatives[0]
    assert opt.underlying_name == "S&P 500 Index"
    assert opt.underlying_cusip == "87654321X"
    assert opt.notional_value == Decimal("1000")
    assert opt.counterparty == "Morgan Stanley"
    assert opt.delta == Decimal("0.5")
    assert opt.expiration_date == date(2025, 3, 15)


def test_parse_nport_clears_cache_when_flag_set(session, engine, sample_etfs, mock_edgar_company, mock_nport_db):
    """Test that parse_nport calls clear_cache when clear_cache=True."""
    with patch("etf_pipeline.parsers.nport.edgar_clear_cache") as mock_clear_cache:
        mock_clear_cache.return_value = {"files_deleted": 10, "bytes_freed": 1024000}

        parse_nport(cik="36405", clear_cache=True)

        mock_clear_cache.assert_called_once_with(dry_run=False)


def test_parse_nport_does_not_clear_cache_when_flag_disabled(session, engine, sample_etfs, mock_edgar_company, mock_nport_db):
    """Test that parse_nport does not call clear_cache when clear_cache=False."""
    with patch("etf_pipeline.parsers.nport.edgar_clear_cache") as mock_clear_cache:
        parse_nport(cik="36405", clear_cache=False)

        mock_clear_cache.assert_not_called()


def test_parse_nport_clears_cache_by_default(session, engine, sample_etfs, mock_edgar_company, mock_nport_db):
    """Test that parse_nport clears cache by default (clear_cache defaults to True)."""
    with patch("etf_pipeline.parsers.nport.edgar_clear_cache") as mock_clear_cache:
        mock_clear_cache.return_value = {"files_deleted": 10, "bytes_freed": 1024000}

        parse_nport(cik="36405")

        mock_clear_cache.assert_called_once_with(dry_run=False)


def test_parse_nport_with_ciks_parameter(session, engine, sample_etfs, mock_edgar_company, mock_nport_db):
    """Test that --ciks parameter overrides cik and processes multiple CIKs."""
    parse_nport(ciks=["36405", "1064641"])

    stmt = select(Holding)
    holdings = session.execute(stmt).scalars().all()

    # Should have holdings from both CIKs: VOO (3) + VTV (3) + SPY (3) = 9 total
    assert len(holdings) == 9

    # Verify both CIKs were processed
    etf_ids = set(h.etf_id for h in holdings)
    assert len(etf_ids) == 3  # VOO, VTV, SPY


def test_parse_nport_ciks_overrides_cik(session, engine, sample_etfs, mock_edgar_company, mock_nport_db):
    """Test that ciks parameter takes precedence over cik parameter."""
    parse_nport(cik="36405", ciks=["1064641"])

    stmt = select(Holding)
    holdings = session.execute(stmt).scalars().all()

    # Should only process SPY (CIK 1064641), not VOO/VTV (CIK 36405)
    assert len(holdings) == 3

    spy = session.execute(select(ETF).where(ETF.ticker == "SPY")).scalar_one()
    assert all(h.etf_id == spy.id for h in holdings)


def test_parse_nport_ciks_invalid_ciks(session, engine, sample_etfs, mock_edgar_company, mock_nport_db, capsys):
    """Test behavior when all provided CIKs are invalid."""
    parse_nport(ciks=["99999", "88888"])

    captured = capsys.readouterr()
    assert "None of the provided CIKs found in database" in captured.out

    stmt = select(Holding)
    holdings = session.execute(stmt).scalars().all()
    assert len(holdings) == 0


def test_parse_nport_writes_processing_log(session, engine, sample_etfs, mock_edgar_company, mock_nport_db):
    """Test that parse_nport writes ProcessingLog row with correct data."""
    from etf_pipeline.models import ProcessingLog

    parse_nport(cik="36405")

    # Verify ProcessingLog was created
    stmt = select(ProcessingLog).where(
        ProcessingLog.cik == "0000036405",
        ProcessingLog.parser_type == "nport"
    )
    log = session.execute(stmt).scalar_one_or_none()

    assert log is not None
    assert log.cik == "0000036405"
    assert log.parser_type == "nport"
    assert log.latest_filing_date_seen == date(2025, 1, 15)
    assert log.last_run_at is not None


def test_parse_nport_sets_filing_date(session, engine, sample_etfs, mock_edgar_company, mock_nport_db):
    """Test that parse_nport sets filing_date on inserted holdings and derivatives."""
    parse_nport(cik="36405")

    # Verify Holdings have filing_date
    stmt = select(Holding).order_by(Holding.name).limit(1)
    holding = session.execute(stmt).scalar_one()
    assert holding.filing_date == date(2025, 1, 15)

    # Add derivative to mock to test derivatives
    def create_mock_derivative():
        inv = Mock()
        inv.name = "Test Derivative"
        inv.derivative_info = Mock()
        inv.derivative_info.derivative_category = "FUT"

        fut = Mock()
        fut.counterparty_name = "Test Counter"
        fut.counterparty_lei = "123456789012345678AA"
        fut.reference_entity_name = "Test Entity"
        fut.reference_entity_cusip = "12345678X"
        fut.notional_amount = Decimal("100000.00")
        fut.expiration_date = "2025-06-30"
        inv.derivative_info.future_derivative = fut
        inv.derivative_info.forward_derivative = None
        inv.derivative_info.option_derivative = None
        inv.derivative_info.swap_derivative = None
        inv.derivative_info.swaption_derivative = None
        return inv

    # Run again with derivatives
    from sqlalchemy import delete
    session.execute(delete(Holding))
    session.commit()

    def create_report_with_derivatives(series_id):
        mock_report = Mock()
        mock_report.reporting_period = date(2024, 12, 31)
        mock_report.non_derivatives = []
        mock_report.derivatives = [create_mock_derivative()]
        general_info = Mock()
        general_info.series_id = series_id
        mock_report.general_info = general_info
        _add_mock_fund_info(mock_report)
        return mock_report

    with patch("etf_pipeline.parsers.nport.Company") as mock_company:
        company = Mock()
        filing1 = Mock()
        filing1.filing_date = date(2025, 1, 15)
        filing1.accession_number = "0000000000-25-000000"
        filing2 = Mock()
        filing2.filing_date = date(2025, 1, 15)
        filing2.accession_number = "0000000000-25-000001"

        filings = Mock()
        filings.empty = False
        filings.__len__ = Mock(return_value=2)
        filings.__getitem__ = Mock(side_effect=[filing1, filing2])
        company.get_filings = Mock(return_value=filings)
        mock_company.return_value = company

        call_count = [0]
        def fund_report_side_effect(filing):
            series_ids = ["S000002839", "S000002840"]
            series_id = series_ids[call_count[0]]
            call_count[0] += 1
            return create_report_with_derivatives(series_id)

        with patch("etf_pipeline.parsers.nport.FundReport.from_filing", side_effect=fund_report_side_effect):
            parse_nport(cik="36405")

    # Verify Derivative has filing_date
    stmt = select(Derivative).limit(1)
    derivative = session.execute(stmt).scalar_one()
    assert derivative.filing_date == date(2025, 1, 15)


def test_parse_nport_creates_fund_snapshot(session, engine, sample_etfs, mock_edgar_company, mock_nport_db):
    """Test that parse_nport creates fund snapshot records with balance sheet data."""
    parse_nport(cik="36405")

    # Verify fund snapshots were created
    stmt = select(FundSnapshot).where(FundSnapshot.cik == "0000036405")
    snapshots = session.execute(stmt).scalars().all()

    # Should have one snapshot (both ETFs share same CIK and filing date)
    assert len(snapshots) == 1

    snapshot = snapshots[0]
    assert snapshot.cik == "0000036405"
    assert snapshot.report_date == date(2024, 12, 31)
    assert snapshot.filing_date == date(2025, 1, 15)
    assert snapshot.total_assets == Decimal("10000000.00")
    assert snapshot.total_liabilities == Decimal("500000.00")
    assert snapshot.net_assets == Decimal("9500000.00")
    assert snapshot.cash_not_reported == Decimal("50000.00")
    assert snapshot.assets_invested == Decimal("9800000.00")
    assert snapshot.assets_misc_sec == Decimal("150000.00")
    assert snapshot.amt_pay_one_yr_banks_borr == Decimal("100000.00")
    assert snapshot.amt_pay_one_yr_ctrld_comp == Decimal("0.00")
    assert snapshot.amt_pay_one_yr_oth_affil == Decimal("0.00")
    assert snapshot.amt_pay_one_yr_other == Decimal("50000.00")
    assert snapshot.amt_pay_aft_one_yr_banks_borr == Decimal("250000.00")
    assert snapshot.amt_pay_aft_one_yr_ctrld_comp == Decimal("0.00")
    assert snapshot.amt_pay_aft_one_yr_oth_affil == Decimal("0.00")
    assert snapshot.amt_pay_aft_one_yr_other == Decimal("100000.00")
    assert snapshot.delay_deliv == Decimal("0.00")
    assert snapshot.stand_by_commit == Decimal("0.00")
    assert snapshot.liquidity_pref == Decimal("0.00")
    assert snapshot.is_non_cash_collateral is False


def test_parse_nport_skips_duplicate_fund_snapshot(session, engine, sample_etfs, mock_edgar_company, mock_nport_db, caplog):
    """Test that parse_nport skips creating fund snapshot if one already exists."""
    import logging
    caplog.set_level(logging.DEBUG)

    # Create initial snapshot
    existing_snapshot = FundSnapshot(
        cik="0000036405",
        report_date=date(2024, 12, 31),
        filing_date=date(2025, 1, 15),
        total_assets=Decimal("5000000.00"),
        total_liabilities=Decimal("200000.00"),
        net_assets=Decimal("4800000.00"),
    )
    session.add(existing_snapshot)
    session.commit()

    # Run parser
    parse_nport(cik="36405")

    # Verify only one snapshot exists (original was not overwritten)
    stmt = select(FundSnapshot).where(FundSnapshot.cik == "0000036405")
    snapshots = session.execute(stmt).scalars().all()
    assert len(snapshots) == 1
    assert snapshots[0].total_assets == Decimal("5000000.00")  # Original value
    assert "Fund snapshot already exists" in caplog.text


def test_parse_nport_handles_missing_fund_info(session, engine, sample_etfs, mock_nport_db, caplog):
    """Test that parse_nport handles FundReport without fund_info gracefully."""
    import logging
    caplog.set_level(logging.WARNING)

    def create_report_without_fund_info(series_id):
        mock_report = Mock(spec=['reporting_period', 'non_derivatives', 'derivatives', 'general_info'])
        mock_report.reporting_period = date(2024, 12, 31)
        mock_report.non_derivatives = []
        mock_report.derivatives = []
        general_info = Mock()
        general_info.series_id = series_id
        mock_report.general_info = general_info
        # No fund_info attribute - will raise AttributeError when accessed
        return mock_report

    with patch("etf_pipeline.parsers.nport.Company") as mock_company:
        company = Mock()

        filing1 = Mock()
        filing1.filing_date = date(2025, 1, 15)
        filing1.accession_number = "0000000000-25-000000"

        filings = Mock()
        filings.empty = False
        filings.__len__ = Mock(return_value=1)
        filings.__getitem__ = Mock(side_effect=[filing1])
        company.get_filings = Mock(return_value=filings)
        mock_company.return_value = company

        with patch(
            "etf_pipeline.parsers.nport.FundReport.from_filing",
            return_value=create_report_without_fund_info("S000002839"),
        ):
            parse_nport(cik="36405")

    # No snapshots should be created
    stmt = select(FundSnapshot)
    snapshots = session.execute(stmt).scalars().all()
    assert len(snapshots) == 0
    assert "No fund_info found" in caplog.text


def test_parse_nport_creates_debt_security_detail(session, engine, sample_etfs, mock_nport_db):
    """Test that parse_nport creates DebtSecurityDetail for debt holdings."""
    def create_mock_bond(name, cusip, maturity_date_str, coupon_rate):
        """Create a mock InvestmentOrSecurity with debt_security data."""
        inv = Mock()
        inv.name = name
        inv.lei = None
        inv.title = "Corporate Bond"
        inv.cusip = cusip
        inv.balance = Decimal("100000.0")
        inv.units = "PA"
        inv.currency_code = "USD"
        inv.value_usd = Decimal("105000.00")
        inv.pct_value = Decimal("10.5")
        inv.asset_category = "DBT"
        inv.issuer_category = "CORP"
        inv.investment_country = "US"
        inv.is_restricted_security = False
        inv.fair_value_level = "2"
        inv.ticker = None

        identifiers = Mock()
        identifiers.isin = f"{cusip}XX"
        inv.identifiers = identifiers

        # Add debt_security data
        debt_sec = Mock()
        debt_sec.maturity_date = maturity_date_str
        debt_sec.coupon_kind = "Fixed"
        debt_sec.annualized_rate = Decimal(str(coupon_rate))
        debt_sec.is_default = False
        debt_sec.are_instrument_payents_in_arrears = False
        debt_sec.is_paid_kind = False
        debt_sec.is_mandatory_convertible = False
        debt_sec.is_continuing_convertible = False
        inv.debt_security = debt_sec

        return inv

    def create_report_with_bonds(series_id):
        mock_report = Mock()
        mock_report.reporting_period = date(2024, 12, 31)
        mock_report.non_derivatives = [
            create_mock_bond("Apple Inc Bond", "037833AG3", "2030-05-15", "3.75"),
            create_mock_bond("Microsoft Corp Bond", "594918BG6", "2035-08-08", "4.25"),
        ]
        mock_report.derivatives = []
        general_info = Mock()
        general_info.series_id = series_id
        mock_report.general_info = general_info
        _add_mock_fund_info(mock_report)
        return mock_report

    with patch("etf_pipeline.parsers.nport.Company") as mock_company:
        company = Mock()
        filing1 = Mock()
        filing1.filing_date = date(2025, 1, 15)
        filing1.accession_number = "0000000000-25-000000"

        filings = Mock()
        filings.empty = False
        filings.__len__ = Mock(return_value=1)
        filings.__getitem__ = Mock(side_effect=[filing1])
        company.get_filings = Mock(return_value=filings)
        mock_company.return_value = company

        with patch(
            "etf_pipeline.parsers.nport.FundReport.from_filing",
            return_value=create_report_with_bonds("S000002839"),
        ):
            parse_nport(cik="36405")

    # Verify holdings were created
    stmt = select(Holding).order_by(Holding.name)
    holdings = session.execute(stmt).scalars().all()
    assert len(holdings) == 2

    # Verify debt security details were created
    stmt = select(DebtSecurityDetail).join(Holding).order_by(Holding.name)
    debt_details = session.execute(stmt).scalars().all()
    assert len(debt_details) == 2

    # Check first bond details
    assert debt_details[0].maturity_date == date(2030, 5, 15)
    assert debt_details[0].coupon_kind == "Fixed"
    assert debt_details[0].annualized_rate == Decimal("3.75")
    assert debt_details[0].is_default is False
    assert debt_details[0].is_in_arrears is False
    assert debt_details[0].is_paid_kind is False
    assert debt_details[0].is_mandatory_convertible is False
    assert debt_details[0].is_contingent_convertible is False

    # Check second bond details
    assert debt_details[1].maturity_date == date(2035, 8, 8)
    assert debt_details[1].coupon_kind == "Fixed"
    assert debt_details[1].annualized_rate == Decimal("4.25")


def test_parse_nport_equity_holding_has_no_debt_detail(session, engine, sample_etfs, mock_edgar_company, mock_nport_db):
    """Test that equity holdings do not create DebtSecurityDetail rows."""
    parse_nport(cik="36405")

    # Verify holdings exist
    stmt = select(Holding)
    holdings = session.execute(stmt).scalars().all()
    assert len(holdings) > 0

    # Verify NO debt security details exist (mock investments are equities)
    stmt = select(DebtSecurityDetail)
    debt_details = session.execute(stmt).scalars().all()
    assert len(debt_details) == 0


def test_parse_nport_debt_detail_with_null_coupon(session, engine, sample_etfs, mock_nport_db):
    """Test that debt holdings with NULL coupon rate are handled correctly."""
    def create_mock_zero_coupon_bond(name, cusip, maturity_date_str):
        """Create a mock InvestmentOrSecurity with debt_security but no coupon."""
        inv = Mock()
        inv.name = name
        inv.lei = None
        inv.title = "Zero Coupon Bond"
        inv.cusip = cusip
        inv.balance = Decimal("100000.0")
        inv.units = "PA"
        inv.currency_code = "USD"
        inv.value_usd = Decimal("80000.00")
        inv.pct_value = Decimal("8.0")
        inv.asset_category = "DBT"
        inv.issuer_category = "CORP"
        inv.investment_country = "US"
        inv.is_restricted_security = False
        inv.fair_value_level = "2"
        inv.ticker = None

        identifiers = Mock()
        identifiers.isin = f"{cusip}XX"
        inv.identifiers = identifiers

        # Add debt_security data with no coupon
        debt_sec = Mock()
        debt_sec.maturity_date = maturity_date_str
        debt_sec.coupon_kind = "Zero"
        debt_sec.annualized_rate = None  # NULL coupon
        debt_sec.is_default = False
        debt_sec.are_instrument_payents_in_arrears = False
        debt_sec.is_paid_kind = False
        debt_sec.is_mandatory_convertible = False
        debt_sec.is_continuing_convertible = False
        inv.debt_security = debt_sec

        return inv

    def create_report_with_zero_coupon(series_id):
        mock_report = Mock()
        mock_report.reporting_period = date(2024, 12, 31)
        mock_report.non_derivatives = [
            create_mock_zero_coupon_bond("Zero Coupon Treasury", "912828XY1", "2040-02-15"),
        ]
        mock_report.derivatives = []
        general_info = Mock()
        general_info.series_id = series_id
        mock_report.general_info = general_info
        _add_mock_fund_info(mock_report)
        return mock_report

    with patch("etf_pipeline.parsers.nport.Company") as mock_company:
        company = Mock()
        filing1 = Mock()
        filing1.filing_date = date(2025, 1, 15)
        filing1.accession_number = "0000000000-25-000000"

        filings = Mock()
        filings.empty = False
        filings.__len__ = Mock(return_value=1)
        filings.__getitem__ = Mock(side_effect=[filing1])
        company.get_filings = Mock(return_value=filings)
        mock_company.return_value = company

        with patch(
            "etf_pipeline.parsers.nport.FundReport.from_filing",
            return_value=create_report_with_zero_coupon("S000002839"),
        ):
            parse_nport(cik="36405")

    # Verify debt security detail was created with NULL coupon rate
    stmt = select(DebtSecurityDetail)


def test_parse_nport_creates_security_lending(session, engine, sample_etfs, mock_nport_db):
    """Test that parse_nport creates SecurityLending for holdings with lending data."""
    def create_mock_lending_security(name, cusip, is_cash, is_non_cash, is_loan):
        """Create a mock InvestmentOrSecurity with security_lending data."""
        inv = Mock()
        inv.name = name
        inv.lei = None
        inv.title = "Lent Security"
        inv.cusip = cusip
        inv.balance = Decimal("1000.0")
        inv.units = "NS"
        inv.currency_code = "USD"
        inv.value_usd = Decimal("50000.00")
        inv.pct_value = Decimal("5.0")
        inv.asset_category = "EC"
        inv.issuer_category = "CORP"
        inv.investment_country = "US"
        inv.is_restricted_security = False
        inv.fair_value_level = "1"
        inv.ticker = "TEST"
        inv.debt_security = None  # No debt_security for equity

        identifiers = Mock()
        identifiers.isin = f"{cusip}XX"
        inv.identifiers = identifiers

        # Add security_lending data
        sec_lending = Mock()
        sec_lending.is_cash_collateral = is_cash
        sec_lending.is_non_cash_collateral = is_non_cash
        sec_lending.is_loan_by_fund = is_loan
        inv.security_lending = sec_lending

        return inv

    def create_report_with_lending(series_id):
        mock_report = Mock()
        mock_report.reporting_period = date(2024, 12, 31)
        mock_report.non_derivatives = [
            create_mock_lending_security("Security A", "111111111", True, False, True),
            create_mock_lending_security("Security B", "222222222", False, True, False),
        ]
        mock_report.derivatives = []
        general_info = Mock()
        general_info.series_id = series_id
        mock_report.general_info = general_info
        _add_mock_fund_info(mock_report)
        return mock_report

    with patch("etf_pipeline.parsers.nport.Company") as mock_company:
        company = Mock()
        filing1 = Mock()
        filing1.filing_date = date(2025, 1, 15)
        filing1.accession_number = "0000000000-25-000000"

        filings = Mock()
        filings.empty = False
        filings.__len__ = Mock(return_value=1)
        filings.__getitem__ = Mock(side_effect=[filing1])
        company.get_filings = Mock(return_value=filings)
        mock_company.return_value = company

        with patch(
            "etf_pipeline.parsers.nport.FundReport.from_filing",
            return_value=create_report_with_lending("S000002839"),
        ):
            parse_nport(cik="36405")

    # Verify holdings were created
    stmt = select(Holding).order_by(Holding.name)
    holdings = session.execute(stmt).scalars().all()
    assert len(holdings) == 2

    # Verify security lending details were created
    stmt = select(SecurityLending).join(Holding).order_by(Holding.name)
    lending_details = session.execute(stmt).scalars().all()
    assert len(lending_details) == 2

    # Check first security lending details
    assert lending_details[0].is_cash_collateral is True
    assert lending_details[0].is_non_cash_collateral is False
    assert lending_details[0].is_loan_by_fund is True

    # Check second security lending details
    assert lending_details[1].is_cash_collateral is False
    assert lending_details[1].is_non_cash_collateral is True
    assert lending_details[1].is_loan_by_fund is False


def test_parse_nport_holding_without_lending_data(session, engine, sample_etfs, mock_edgar_company, mock_nport_db):
    """Test that holdings without security_lending data do not create SecurityLending rows."""
    def create_report_without_lending(series_id):
        mock_report = Mock()
        mock_report.reporting_period = date(2024, 12, 31)

        inv = Mock()
        inv.name = "Regular Security"
        inv.lei = None
        inv.title = None
        inv.cusip = "333333333"
        inv.balance = Decimal("100.0")
        inv.units = "NS"
        inv.currency_code = "USD"
        inv.value_usd = Decimal("10000.00")
        inv.pct_value = Decimal("5.0")
        inv.asset_category = "EC"
        inv.issuer_category = "CORP"
        inv.investment_country = "US"
        inv.is_restricted_security = False
        inv.fair_value_level = "1"
        inv.ticker = "REG"
        inv.debt_security = None  # No debt_security
        inv.security_lending = None  # No security_lending data

        identifiers = Mock()
        identifiers.isin = "US3333333333"
        inv.identifiers = identifiers

        mock_report.non_derivatives = [inv]
        mock_report.derivatives = []
        general_info = Mock()
        general_info.series_id = series_id
        mock_report.general_info = general_info
        _add_mock_fund_info(mock_report)
        return mock_report

    with patch("etf_pipeline.parsers.nport.FundReport.from_filing", return_value=create_report_without_lending("S000002839")):
        parse_nport(cik="36405")

    # Verify holding was created
    stmt = select(Holding)
    holdings = session.execute(stmt).scalars().all()
    assert len(holdings) == 1

    # Verify NO security lending detail was created
    stmt = select(SecurityLending)
    lending_details = session.execute(stmt).scalars().all()
    assert len(lending_details) == 0


def test_parse_nport_holding_key_with_cusip(session, engine, sample_etfs, mock_nport_db):
    """Test that holding_key is set to CUSIP when CUSIP is available."""
    def create_mock_investment_with_cusip():
        inv = Mock()
        inv.name = "Apple Inc"
        inv.lei = None
        inv.title = "Common Stock"
        inv.cusip = "037833100"
        inv.balance = Decimal("100.0")
        inv.units = "NS"
        inv.currency_code = "USD"
        inv.value_usd = Decimal("1000000.00")
        inv.pct_value = Decimal("10.0")
        inv.asset_category = "EC"
        inv.issuer_category = "CORP"
        inv.investment_country = "US"
        inv.is_restricted_security = False
        inv.fair_value_level = "1"
        inv.ticker = "AAPL"
        inv.debt_security = None

        identifiers = Mock()
        identifiers.isin = "US0378331005"
        inv.identifiers = identifiers

        return inv

    def create_report_with_cusip(series_id):
        mock_report = Mock()
        mock_report.reporting_period = date(2024, 12, 31)
        mock_report.non_derivatives = [create_mock_investment_with_cusip()]
        mock_report.derivatives = []
        general_info = Mock()
        general_info.series_id = series_id
        mock_report.general_info = general_info
        _add_mock_fund_info(mock_report)
        return mock_report

    with patch("etf_pipeline.parsers.nport.Company") as mock_company:
        company = Mock()
        filing1 = Mock()
        filing1.filing_date = date(2025, 1, 15)
        filing1.accession_number = "0000000000-25-000000"

        filings = Mock()
        filings.empty = False
        filings.__len__ = Mock(return_value=1)
        filings.__getitem__ = Mock(side_effect=[filing1])
        company.get_filings = Mock(return_value=filings)
        mock_company.return_value = company

        with patch(
            "etf_pipeline.parsers.nport.FundReport.from_filing",
            return_value=create_report_with_cusip("S000002839"),
        ):
            parse_nport(cik="36405")

    stmt = select(Holding)
    holdings = session.execute(stmt).scalars().all()
    assert len(holdings) == 1
    assert holdings[0].holding_key == "037833100"
    assert holdings[0].cusip == "037833100"
    assert holdings[0].isin == "US0378331005"
    assert holdings[0].name == "Apple Inc"


def test_parse_nport_holding_key_with_only_isin(session, engine, sample_etfs, mock_nport_db):
    """Test that holding_key is set to ISIN when CUSIP is NULL but ISIN is available."""
    def create_mock_investment_with_only_isin():
        inv = Mock()
        inv.name = "Foreign Security"
        inv.lei = None
        inv.title = "ADR"
        inv.cusip = None  # No CUSIP
        inv.balance = Decimal("50.0")
        inv.units = "NS"
        inv.currency_code = "USD"
        inv.value_usd = Decimal("500000.00")
        inv.pct_value = Decimal("5.0")
        inv.asset_category = "EC"
        inv.issuer_category = "CORP"
        inv.investment_country = "GB"
        inv.is_restricted_security = False
        inv.fair_value_level = "1"
        inv.ticker = "BP"
        inv.debt_security = None

        identifiers = Mock()
        identifiers.isin = "GB0007980591"
        inv.identifiers = identifiers

        return inv

    def create_report_with_only_isin(series_id):
        mock_report = Mock()
        mock_report.reporting_period = date(2024, 12, 31)
        mock_report.non_derivatives = [create_mock_investment_with_only_isin()]
        mock_report.derivatives = []
        general_info = Mock()
        general_info.series_id = series_id
        mock_report.general_info = general_info
        _add_mock_fund_info(mock_report)
        return mock_report

    with patch("etf_pipeline.parsers.nport.Company") as mock_company:
        company = Mock()
        filing1 = Mock()
        filing1.filing_date = date(2025, 1, 15)
        filing1.accession_number = "0000000000-25-000000"

        filings = Mock()
        filings.empty = False
        filings.__len__ = Mock(return_value=1)
        filings.__getitem__ = Mock(side_effect=[filing1])
        company.get_filings = Mock(return_value=filings)
        mock_company.return_value = company

        with patch(
            "etf_pipeline.parsers.nport.FundReport.from_filing",
            return_value=create_report_with_only_isin("S000002839"),
        ):
            parse_nport(cik="36405")

    stmt = select(Holding)
    holdings = session.execute(stmt).scalars().all()
    assert len(holdings) == 1
    assert holdings[0].holding_key == "GB0007980591"
    assert holdings[0].cusip is None
    assert holdings[0].isin == "GB0007980591"
    assert holdings[0].name == "Foreign Security"


def test_parse_nport_holding_key_with_only_name(session, engine, sample_etfs, mock_nport_db):
    """Test that holding_key is set to name when both CUSIP and ISIN are NULL."""
    def create_mock_investment_with_only_name():
        inv = Mock()
        inv.name = "Private Equity Investment"
        inv.lei = None
        inv.title = "Limited Partnership Interest"
        inv.cusip = None  # No CUSIP
        inv.balance = Decimal("1000.0")
        inv.units = "PA"
        inv.currency_code = "USD"
        inv.value_usd = Decimal("250000.00")
        inv.pct_value = Decimal("2.5")
        inv.asset_category = "EC"
        inv.issuer_category = "CORP"
        inv.investment_country = "US"
        inv.is_restricted_security = True
        inv.fair_value_level = "3"
        inv.ticker = None
        inv.debt_security = None

        identifiers = Mock()
        identifiers.isin = None  # No ISIN
        inv.identifiers = identifiers

        return inv

    def create_report_with_only_name(series_id):
        mock_report = Mock()
        mock_report.reporting_period = date(2024, 12, 31)
        mock_report.non_derivatives = [create_mock_investment_with_only_name()]
        mock_report.derivatives = []
        general_info = Mock()
        general_info.series_id = series_id
        mock_report.general_info = general_info
        _add_mock_fund_info(mock_report)
        return mock_report

    with patch("etf_pipeline.parsers.nport.Company") as mock_company:
        company = Mock()
        filing1 = Mock()
        filing1.filing_date = date(2025, 1, 15)
        filing1.accession_number = "0000000000-25-000000"

        filings = Mock()
        filings.empty = False
        filings.__len__ = Mock(return_value=1)
        filings.__getitem__ = Mock(side_effect=[filing1])
        company.get_filings = Mock(return_value=filings)
        mock_company.return_value = company

        with patch(
            "etf_pipeline.parsers.nport.FundReport.from_filing",
            return_value=create_report_with_only_name("S000002839"),
        ):
            parse_nport(cik="36405")

    stmt = select(Holding)
    holdings = session.execute(stmt).scalars().all()
    assert len(holdings) == 1
    assert holdings[0].holding_key == "Private Equity Investment"
    assert holdings[0].cusip is None
    assert holdings[0].isin is None
    assert holdings[0].name == "Private Equity Investment"


def test_parse_nport_holding_constraint_prevents_duplicate_holding_key(session, engine, sample_etfs, mock_nport_db):
    """Test that unique constraint prevents duplicate holdings with same holding_key."""
    from sqlalchemy.exc import IntegrityError

    def create_mock_investment_duplicate(name):
        inv = Mock()
        inv.name = name
        inv.lei = None
        inv.title = "Foreign Bond"
        inv.cusip = None  # No CUSIP
        inv.balance = Decimal("100.0")
        inv.units = "PA"
        inv.currency_code = "EUR"
        inv.value_usd = Decimal("100000.00")
        inv.pct_value = Decimal("1.0")
        inv.asset_category = "DBT"
        inv.issuer_category = "CORP"
        inv.investment_country = "DE"
        inv.is_restricted_security = False
        inv.fair_value_level = "2"
        inv.ticker = None
        inv.debt_security = None

        identifiers = Mock()
        identifiers.isin = "DE0001234567"  # Same ISIN for both
        inv.identifiers = identifiers

        return inv

    def create_report_with_duplicates(series_id):
        mock_report = Mock()
        mock_report.reporting_period = date(2024, 12, 31)
        # Two holdings with same ISIN (which becomes holding_key)
        mock_report.non_derivatives = [
            create_mock_investment_duplicate("German Bond A"),
            create_mock_investment_duplicate("German Bond B"),
        ]
        mock_report.derivatives = []
        general_info = Mock()
        general_info.series_id = series_id
        mock_report.general_info = general_info
        _add_mock_fund_info(mock_report)
        return mock_report

    with patch("etf_pipeline.parsers.nport.Company") as mock_company:
        company = Mock()
        filing1 = Mock()
        filing1.filing_date = date(2025, 1, 15)
        filing1.accession_number = "0000000000-25-000000"

        filings = Mock()
        filings.empty = False
        filings.__len__ = Mock(return_value=1)
        filings.__getitem__ = Mock(side_effect=[filing1])
        company.get_filings = Mock(return_value=filings)
        mock_company.return_value = company

        with patch(
            "etf_pipeline.parsers.nport.FundReport.from_filing",
            return_value=create_report_with_duplicates("S000002839"),
        ):
            parse_nport(cik="36405")

    # Verify only one holding was inserted (duplicate was skipped by deduplication)
    stmt = select(Holding)
    holdings = session.execute(stmt).scalars().all()
    assert len(holdings) == 1
    assert holdings[0].holding_key == "DE0001234567"


def test_parse_nport_extracts_title_payoff_exchange_rate(session, engine, sample_etfs, mock_nport_db):
    """Test that title, payoff_profile, and exchange_rate are extracted correctly."""
    def create_mock_investment_with_new_fields():
        inv = Mock()
        inv.name = "Foreign Currency Bond"
        inv.lei = "123456789012345678XX"
        inv.title = "Senior Unsecured Note"
        inv.cusip = "888888888"
        inv.balance = Decimal("1000.0")
        inv.units = "PA"
        inv.currency_code = "EUR"
        inv.value_usd = Decimal("110000.00")
        inv.pct_value = Decimal("1.1")
        inv.asset_category = "DBT"
        inv.issuer_category = "CORP"
        inv.investment_country = "FR"
        inv.is_restricted_security = False
        inv.fair_value_level = "2"
        inv.ticker = None
        inv.debt_security = None
        inv.payoff_profile = "Long"
        inv.exchange_rate = Decimal("1.095432")

        identifiers = Mock()
        identifiers.isin = "FR0001234567"
        inv.identifiers = identifiers

        return inv

    def create_report_with_new_fields(series_id):
        mock_report = Mock()
        mock_report.reporting_period = date(2024, 12, 31)
        mock_report.non_derivatives = [create_mock_investment_with_new_fields()]
        mock_report.derivatives = []
        general_info = Mock()
        general_info.series_id = series_id
        mock_report.general_info = general_info
        _add_mock_fund_info(mock_report)
        return mock_report

    with patch("etf_pipeline.parsers.nport.Company") as mock_company:
        company = Mock()
        filing1 = Mock()
        filing1.filing_date = date(2025, 1, 15)
        filing1.accession_number = "0000000000-25-000000"

        filings = Mock()
        filings.empty = False
        filings.__len__ = Mock(return_value=1)
        filings.__getitem__ = Mock(side_effect=[filing1])
        company.get_filings = Mock(return_value=filings)
        mock_company.return_value = company

        with patch(
            "etf_pipeline.parsers.nport.FundReport.from_filing",
            return_value=create_report_with_new_fields("S000002839"),
        ):
            parse_nport(cik="36405")

    stmt = select(Holding)
    holdings = session.execute(stmt).scalars().all()
    assert len(holdings) == 1
    holding = holdings[0]
    assert holding.title == "Senior Unsecured Note"
    assert holding.payoff_profile == "Long"
    assert holding.exchange_rate == Decimal("1.095432")
    assert holding.holding_key == "888888888"
