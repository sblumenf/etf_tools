"""Tests for NPORT-P parser."""

import json
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import select

from etf_pipeline.models import Derivative, ETF, Holding
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
        inv = Mock()
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
            for series_id in series_list:
                filing = Mock()
                filing.filing_date = date(2025, 1, 15)
                filing.series_id = series_id
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
        return inv

    def create_report_with_series(series_id):
        mock_report = Mock()
        mock_report.reporting_period = date(2024, 12, 31)
        mock_report.non_derivatives = [create_mock_investment_with_na()]
        mock_report.derivatives = []
        general_info = Mock()
        general_info.series_id = series_id
        mock_report.general_info = general_info
        return mock_report

    with patch("etf_pipeline.parsers.nport.Company") as mock_company:
        company = Mock()

        filing1 = Mock()
        filing1.filing_date = date(2025, 1, 15)
        filing2 = Mock()
        filing2.filing_date = date(2025, 1, 15)

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

        return mock_report

    with patch("etf_pipeline.parsers.nport.Company") as mock_company:
        company = Mock()

        filing1 = Mock()
        filing1.filing_date = date(2025, 1, 15)

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
    assert "Skipping duplicate CUSIP 037833100" in caplog.text

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

        return mock_report

    with patch("etf_pipeline.parsers.nport.Company") as mock_company:
        company = Mock()

        filing1 = Mock()
        filing1.filing_date = date(2025, 1, 15)

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

        return mock_report

    with patch("etf_pipeline.parsers.nport.Company") as mock_company:
        company = Mock()

        filing1 = Mock()
        filing1.filing_date = date(2025, 1, 15)

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
        filing2 = Mock()
        filing2.filing_date = date(2025, 1, 15)

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
        return mock_report

    with patch("etf_pipeline.parsers.nport.Company") as mock_company:
        company = Mock()

        filing1 = Mock()
        filing1.filing_date = date(2025, 1, 15)
        filing2 = Mock()
        filing2.filing_date = date(2025, 1, 15)

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
        return mock_report

    with patch("etf_pipeline.parsers.nport.Company") as mock_company:
        company = Mock()

        filing1 = Mock()
        filing1.filing_date = date(2025, 1, 15)
        filing2 = Mock()
        filing2.filing_date = date(2025, 1, 15)

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
        return mock_report

    with patch("etf_pipeline.parsers.nport.Company") as mock_company:
        company = Mock()

        filing1 = Mock()
        filing1.filing_date = date(2025, 1, 15)
        filing2 = Mock()
        filing2.filing_date = date(2025, 1, 15)

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
        return mock_report

    with patch("etf_pipeline.parsers.nport.Company") as mock_company:
        company = Mock()

        filing1 = Mock()
        filing1.filing_date = date(2025, 1, 15)
        filing2 = Mock()
        filing2.filing_date = date(2025, 1, 15)

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
        return mock_report

    with patch("etf_pipeline.parsers.nport.Company") as mock_company:
        company = Mock()

        filing1 = Mock()
        filing1.filing_date = date(2025, 1, 15)

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
        return mock_report

    with patch("etf_pipeline.parsers.nport.Company") as mock_company:
        company = Mock()
        filing1 = Mock()
        filing1.filing_date = date(2025, 1, 15)
        filing2 = Mock()
        filing2.filing_date = date(2025, 1, 15)

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
