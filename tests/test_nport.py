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

        # Track which series to return for each CIK
        cik_to_series = {
            "0000036405": ["S000002839", "S000002840"],  # VOO, VTV
            "0001064641": ["S000002753"],  # SPY
        }
        series_call_tracker = {}

        def company_factory(cik):
            company = Mock()

            # Create mock filings based on CIK
            series_list = cik_to_series.get(cik, [])
            num_filings = len(series_list)

            filings_list = []
            for _ in range(num_filings):
                filing = Mock()
                filing.filing_date = date(2025, 1, 15)
                filing.cik = cik  # Track which CIK this filing belongs to
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
            # Get the series list for this CIK
            cik = filing.cik
            series_list = cik_to_series.get(cik, [])

            # Track which series we're on for this CIK
            if cik not in series_call_tracker:
                series_call_tracker[cik] = 0

            series_id = series_list[series_call_tracker[cik] % len(series_list)]
            series_call_tracker[cik] += 1

            return mock_fund_report(series_id)

        with patch(
            "etf_pipeline.parsers.nport.FundReport.from_filing",
            side_effect=fund_report_side_effect,
        ):
            yield mock_class


def test_parse_nport_creates_holdings(session, engine, sample_etfs, mock_edgar_company):
    """Test that parse_nport creates holding records from FundReport."""
    with patch("etf_pipeline.parsers.nport.get_engine", return_value=engine):
        with patch("etf_pipeline.parsers.nport.get_session_factory") as mock_factory:
            from sqlalchemy.orm import sessionmaker

            mock_factory.return_value = sessionmaker(bind=engine)

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


def test_parse_nport_updates_last_fetched(session, engine, sample_etfs, mock_edgar_company):
    """Test that parse_nport updates ETF.last_fetched timestamp."""
    voo = session.execute(select(ETF).where(ETF.ticker == "VOO")).scalar_one()
    assert voo.last_fetched is None

    with patch("etf_pipeline.parsers.nport.get_engine", return_value=engine):
        with patch("etf_pipeline.parsers.nport.get_session_factory") as mock_factory:
            from sqlalchemy.orm import sessionmaker

            mock_factory.return_value = sessionmaker(bind=engine)

            parse_nport(cik="36405")

    session.expire_all()
    voo = session.execute(select(ETF).where(ETF.ticker == "VOO")).scalar_one()
    assert voo.last_fetched is not None
    assert isinstance(voo.last_fetched, datetime)


def test_parse_nport_skips_existing_holdings(session, engine, sample_etfs, mock_edgar_company, caplog):
    """Test that parse_nport skips ETF when holdings already exist for report_date."""
    import logging
    caplog.set_level(logging.INFO)

    voo = session.execute(select(ETF).where(ETF.ticker == "VOO")).scalar_one()

    existing_holding = Holding(
        etf_id=voo.id,
        report_date=date(2024, 12, 31),
        name="Existing Holding",
        cusip="123456789",
        value_usd=Decimal("1000"),
    )
    session.add(existing_holding)
    session.commit()

    with patch("etf_pipeline.parsers.nport.get_engine", return_value=engine):
        with patch("etf_pipeline.parsers.nport.get_session_factory") as mock_factory:
            from sqlalchemy.orm import sessionmaker

            mock_factory.return_value = sessionmaker(bind=engine)

            parse_nport(cik="36405")

    stmt = select(Holding).where(Holding.etf_id == voo.id)
    holdings = session.execute(stmt).scalars().all()

    assert len(holdings) == 1
    assert holdings[0].name == "Existing Holding"
    assert "already exist" in caplog.text


def test_parse_nport_no_nport_filing(session, engine, sample_etfs, caplog):
    """Test that parse_nport handles CIK with no NPORT-P filing."""
    with patch("etf_pipeline.parsers.nport.Company") as mock_company:
        company = Mock()
        filings = Mock()
        filings.empty = True
        filings.__len__ = Mock(return_value=0)
        company.get_filings = Mock(return_value=filings)
        mock_company.return_value = company

        with patch("etf_pipeline.parsers.nport.get_engine", return_value=engine):
            with patch("etf_pipeline.parsers.nport.get_session_factory") as mock_factory:
                from sqlalchemy.orm import sessionmaker

                mock_factory.return_value = sessionmaker(bind=engine)

                parse_nport(cik="36405")

    stmt = select(Holding)
    holdings = session.execute(stmt).scalars().all()
    assert len(holdings) == 0
    assert "No NPORT-P filings found" in caplog.text


def test_parse_nport_with_limit(session, engine, sample_etfs, mock_edgar_company):
    """Test that --limit flag works correctly."""
    with patch("etf_pipeline.parsers.nport.get_engine", return_value=engine):
        with patch("etf_pipeline.parsers.nport.get_session_factory") as mock_factory:
            from sqlalchemy.orm import sessionmaker

            mock_factory.return_value = sessionmaker(bind=engine)

            parse_nport(limit=1)

    stmt = select(Holding)
    holdings = session.execute(stmt).scalars().all()

    assert len(holdings) == 6


def test_parse_nport_with_cik_filter(session, engine, sample_etfs, mock_edgar_company):
    """Test that --cik flag works correctly."""
    with patch("etf_pipeline.parsers.nport.get_engine", return_value=engine):
        with patch("etf_pipeline.parsers.nport.get_session_factory") as mock_factory:
            from sqlalchemy.orm import sessionmaker

            mock_factory.return_value = sessionmaker(bind=engine)

            parse_nport(cik="1064641")

    stmt = select(Holding)
    holdings = session.execute(stmt).scalars().all()

    assert len(holdings) == 3

    spy = session.execute(select(ETF).where(ETF.ticker == "SPY")).scalar_one()
    assert all(h.etf_id == spy.id for h in holdings)


def test_parse_nport_invalid_cik(session, engine, sample_etfs, mock_edgar_company, capsys):
    """Test behavior when requested CIK is not in database."""
    with patch("etf_pipeline.parsers.nport.get_engine", return_value=engine):
        with patch("etf_pipeline.parsers.nport.get_session_factory") as mock_factory:
            from sqlalchemy.orm import sessionmaker

            mock_factory.return_value = sessionmaker(bind=engine)

            parse_nport(cik="99999")

    captured = capsys.readouterr()
    assert "not found in database" in captured.out

    stmt = select(Holding)
    holdings = session.execute(stmt).scalars().all()
    assert len(holdings) == 0


def test_parse_nport_no_etfs_in_db(session, engine, capsys):
    """Test behavior when no ETFs exist in database."""
    with patch("etf_pipeline.parsers.nport.get_engine", return_value=engine):
        with patch("etf_pipeline.parsers.nport.get_session_factory") as mock_factory:
            from sqlalchemy.orm import sessionmaker

            mock_factory.return_value = sessionmaker(bind=engine)

            parse_nport()

    captured = capsys.readouterr()
    assert "No ETFs found in database" in captured.out


def test_parse_nport_handles_na_values(session, engine, sample_etfs):
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
            with patch("etf_pipeline.parsers.nport.get_engine", return_value=engine):
                with patch("etf_pipeline.parsers.nport.get_session_factory") as mock_factory:
                    from sqlalchemy.orm import sessionmaker

                    mock_factory.return_value = sessionmaker(bind=engine)

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


def test_parse_nport_fundreport_parse_error(session, engine, sample_etfs, caplog):
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
            with patch("etf_pipeline.parsers.nport.get_engine", return_value=engine):
                with patch("etf_pipeline.parsers.nport.get_session_factory") as mock_factory:
                    from sqlalchemy.orm import sessionmaker

                    mock_factory.return_value = sessionmaker(bind=engine)

                    parse_nport(cik="36405")

    stmt = select(Holding)
    holdings = session.execute(stmt).scalars().all()
    assert len(holdings) == 0
    assert "Failed to parse filing" in caplog.text


def test_parse_nport_creates_derivatives(session, engine, sample_etfs):
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
            with patch("etf_pipeline.parsers.nport.get_engine", return_value=engine):
                with patch("etf_pipeline.parsers.nport.get_session_factory") as mock_factory:
                    from sqlalchemy.orm import sessionmaker

                    mock_factory.return_value = sessionmaker(bind=engine)

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


def test_parse_nport_etf_with_no_derivatives(session, engine, sample_etfs):
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
            with patch("etf_pipeline.parsers.nport.get_engine", return_value=engine):
                with patch("etf_pipeline.parsers.nport.get_session_factory") as mock_factory:
                    from sqlalchemy.orm import sessionmaker

                    mock_factory.return_value = sessionmaker(bind=engine)

                    parse_nport(cik="36405")

    stmt = select(Derivative)
    derivatives = session.execute(stmt).scalars().all()
    assert len(derivatives) == 0


def test_parse_nport_skips_derivatives_when_holdings_exist(session, engine, sample_etfs):
    """Test that parse_nport skips derivatives when holdings already exist for report_date."""
    voo = session.execute(select(ETF).where(ETF.ticker == "VOO")).scalar_one()

    existing_holding = Holding(
        etf_id=voo.id,
        report_date=date(2024, 12, 31),
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
            with patch("etf_pipeline.parsers.nport.get_engine", return_value=engine):
                with patch("etf_pipeline.parsers.nport.get_session_factory") as mock_factory:
                    from sqlalchemy.orm import sessionmaker

                    mock_factory.return_value = sessionmaker(bind=engine)

                    parse_nport(cik="36405")

    stmt = select(Derivative).where(Derivative.etf_id == voo.id)
    voo_derivatives = session.execute(stmt).scalars().all()
    assert len(voo_derivatives) == 0


def test_parse_nport_creates_forward_and_swaption_derivatives(session, engine, sample_etfs):
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
            with patch("etf_pipeline.parsers.nport.get_engine", return_value=engine):
                with patch("etf_pipeline.parsers.nport.get_session_factory") as mock_factory:
                    from sqlalchemy.orm import sessionmaker

                    mock_factory.return_value = sessionmaker(bind=engine)

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


def test_parse_nport_clears_cache_when_flag_set(session, engine, sample_etfs, mock_edgar_company):
    """Test that parse_nport calls clear_cache when clear_cache=True."""
    with patch("etf_pipeline.parsers.nport.get_engine", return_value=engine):
        with patch("etf_pipeline.parsers.nport.get_session_factory") as mock_factory:
            with patch("etf_pipeline.parsers.nport.edgar_clear_cache") as mock_clear_cache:
                from sqlalchemy.orm import sessionmaker

                mock_factory.return_value = sessionmaker(bind=engine)
                mock_clear_cache.return_value = {"files_deleted": 10, "bytes_freed": 1024000}

                parse_nport(cik="36405", clear_cache=True)

                mock_clear_cache.assert_called_once_with(dry_run=False)


def test_parse_nport_does_not_clear_cache_when_flag_disabled(session, engine, sample_etfs, mock_edgar_company):
    """Test that parse_nport does not call clear_cache when clear_cache=False."""
    with patch("etf_pipeline.parsers.nport.get_engine", return_value=engine):
        with patch("etf_pipeline.parsers.nport.get_session_factory") as mock_factory:
            with patch("etf_pipeline.parsers.nport.edgar_clear_cache") as mock_clear_cache:
                from sqlalchemy.orm import sessionmaker

                mock_factory.return_value = sessionmaker(bind=engine)

                parse_nport(cik="36405", clear_cache=False)

                mock_clear_cache.assert_not_called()


def test_parse_nport_clears_cache_by_default(session, engine, sample_etfs, mock_edgar_company):
    """Test that parse_nport clears cache by default (clear_cache defaults to True)."""
    with patch("etf_pipeline.parsers.nport.get_engine", return_value=engine):
        with patch("etf_pipeline.parsers.nport.get_session_factory") as mock_factory:
            with patch("etf_pipeline.parsers.nport.edgar_clear_cache") as mock_clear_cache:
                from sqlalchemy.orm import sessionmaker

                mock_factory.return_value = sessionmaker(bind=engine)
                mock_clear_cache.return_value = {"files_deleted": 10, "bytes_freed": 1024000}

                parse_nport(cik="36405")

                mock_clear_cache.assert_called_once_with(dry_run=False)
