from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from etf_pipeline.models import (
    Derivative,
    ETF,
    FeeExpense,
    FlowData,
    Holding,
    Performance,
    PerShareDistribution,
    PerShareOperating,
    PerShareRatios,
    ProcessingLog,
)


def _make_etf(**overrides) -> ETF:
    defaults = dict(
        ticker="SPY",
        cik="0000884394",
        series_id="S000005325",
        issuer_name="State Street Global Advisors",
        is_active=True,
        incomplete_data=False,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    defaults.update(overrides)
    return ETF(**defaults)


class TestETF:
    def test_create_etf(self, session):
        etf = _make_etf()
        session.add(etf)
        session.commit()

        result = session.query(ETF).filter_by(ticker="SPY").one()
        assert result.cik == "0000884394"
        assert result.is_active is True

    def test_ticker_unique_constraint(self, session):
        session.add(_make_etf(ticker="SPY"))
        session.commit()

        session.add(_make_etf(ticker="SPY", cik="9999999999"))
        with pytest.raises(IntegrityError):
            session.commit()

    def test_issuer_name_required(self, session):
        etf = _make_etf(issuer_name=None)
        session.add(etf)
        with pytest.raises(IntegrityError):
            session.commit()


class TestHolding:
    def test_create_holding(self, session):
        etf = _make_etf()
        session.add(etf)
        session.flush()

        holding = Holding(
            etf_id=etf.id,
            report_date=date(2024, 3, 31),
            filing_date=date(2024, 5, 1),
            name="Apple Inc",
            cusip="037833100",
            value_usd=Decimal("150000000.00"),
            pct_val=Decimal("0.07500"),
            asset_category="EC",
            currency="USD",
        )
        session.add(holding)
        session.commit()

        result = session.query(Holding).one()
        assert result.name == "Apple Inc"
        assert result.value_usd == Decimal("150000000.00")

    def test_holding_fk_constraint(self, session):
        holding = Holding(
            etf_id=9999,
            report_date=date(2024, 3, 31),
            filing_date=date(2024, 5, 1),
            name="Orphan",
        )
        session.add(holding)
        with pytest.raises(IntegrityError):
            session.commit()

    def test_etf_holdings_relationship(self, session):
        etf = _make_etf()
        session.add(etf)
        session.flush()

        h1 = Holding(
            etf_id=etf.id,
            report_date=date(2024, 3, 31),
            filing_date=date(2024, 5, 1),
            name="AAPL",
        )
        h2 = Holding(
            etf_id=etf.id,
            report_date=date(2024, 3, 31),
            filing_date=date(2024, 5, 1),
            name="MSFT",
        )
        session.add_all([h1, h2])
        session.commit()

        session.refresh(etf)
        assert len(etf.holdings) == 2


class TestDerivative:
    def test_create_derivative(self, session):
        etf = _make_etf()
        session.add(etf)
        session.flush()

        deriv = Derivative(
            etf_id=etf.id,
            report_date=date(2024, 3, 31),
            filing_date=date(2024, 5, 1),
            derivative_type="future",
            underlying_name="S&P 500 Index",
            notional_value=Decimal("50000000.00"),
            expiration_date=date(2024, 6, 21),
        )
        session.add(deriv)
        session.commit()

        result = session.query(Derivative).one()
        assert result.derivative_type == "future"


class TestPerformance:
    def test_create_performance(self, session):
        etf = _make_etf()
        session.add(etf)
        session.flush()

        perf = Performance(
            etf_id=etf.id,
            fiscal_year_end=date(2024, 1, 31),
            filing_date=date(2024, 3, 1),
            return_1yr=Decimal("0.12340"),
            portfolio_turnover=Decimal("0.50000"),
            expense_ratio_actual=Decimal("0.00090"),
        )
        session.add(perf)
        session.commit()

        result = session.query(Performance).one()
        assert result.return_1yr == Decimal("0.12340")

    def test_performance_unique_constraint(self, session):
        etf = _make_etf()
        session.add(etf)
        session.flush()

        session.add(
            Performance(
                etf_id=etf.id,
                fiscal_year_end=date(2024, 1, 31),
                filing_date=date(2024, 3, 1),
            )
        )
        session.commit()

        session.add(
            Performance(
                etf_id=etf.id,
                fiscal_year_end=date(2024, 1, 31),
                filing_date=date(2024, 3, 1),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


class TestFeeExpense:
    def test_create_fee_expense(self, session):
        etf = _make_etf()
        session.add(etf)
        session.flush()

        fee = FeeExpense(
            etf_id=etf.id,
            effective_date=date(2024, 3, 1),
            filing_date=date(2024, 3, 1),
            management_fee=Decimal("0.00045"),
            total_expense_net=Decimal("0.00093"),
        )
        session.add(fee)
        session.commit()

        result = session.query(FeeExpense).one()
        assert result.management_fee == Decimal("0.00045")

    def test_fee_unique_constraint(self, session):
        etf = _make_etf()
        session.add(etf)
        session.flush()

        session.add(
            FeeExpense(
                etf_id=etf.id,
                effective_date=date(2024, 3, 1),
                filing_date=date(2024, 3, 1),
            )
        )
        session.commit()

        session.add(
            FeeExpense(
                etf_id=etf.id,
                effective_date=date(2024, 3, 1),
                filing_date=date(2024, 3, 1),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


class TestFlowData:
    def test_create_flow_data(self, session):
        flow = FlowData(
            cik="0001100663",
            fiscal_year_end=date(2024, 1, 31),
            filing_date=date(2024, 3, 1),
            sales_value=Decimal("5000000000.0000"),
            redemptions_value=Decimal("4500000000.0000"),
            net_sales=Decimal("500000000.0000"),
        )
        session.add(flow)
        session.commit()

        result = session.query(FlowData).one()
        assert result.net_sales == Decimal("500000000.0000")
        assert result.cik == "0001100663"

    def test_flow_unique_constraint(self, session):
        session.add(
            FlowData(
                cik="0001100663",
                fiscal_year_end=date(2024, 1, 31),
                filing_date=date(2024, 3, 1),
            )
        )
        session.commit()

        session.add(
            FlowData(
                cik="0001100663",
                fiscal_year_end=date(2024, 1, 31),
                filing_date=date(2024, 3, 1),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


class TestPerShareOperating:
    def test_create_per_share_operating(self, session):
        etf = _make_etf()
        session.add(etf)
        session.flush()

        pso = PerShareOperating(
            etf_id=etf.id,
            fiscal_year_end=date(2024, 1, 31),
            filing_date=date(2024, 3, 1),
            nav_beginning=Decimal("100.0000"),
            net_investment_income=Decimal("2.5000"),
            net_realized_unrealized_gain=Decimal("12.0000"),
            total_from_operations=Decimal("14.5000"),
            nav_end=Decimal("112.0000"),
            total_return=Decimal("0.12340"),
            math_validated=True,
        )
        session.add(pso)
        session.commit()

        result = session.query(PerShareOperating).one()
        assert result.nav_beginning == Decimal("100.0000")
        assert result.total_return == Decimal("0.12340")
        assert result.math_validated is True

    def test_per_share_operating_unique_constraint(self, session):
        etf = _make_etf()
        session.add(etf)
        session.flush()

        session.add(
            PerShareOperating(
                etf_id=etf.id,
                fiscal_year_end=date(2024, 1, 31),
                filing_date=date(2024, 3, 1),
                math_validated=True,
            )
        )
        session.commit()

        session.add(
            PerShareOperating(
                etf_id=etf.id,
                fiscal_year_end=date(2024, 1, 31),
                filing_date=date(2024, 3, 1),
                math_validated=False,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()

    def test_etf_per_share_operating_relationship(self, session):
        etf = _make_etf()
        session.add(etf)
        session.flush()

        pso = PerShareOperating(
            etf_id=etf.id,
            fiscal_year_end=date(2024, 1, 31),
            filing_date=date(2024, 3, 1),
            math_validated=True,
        )
        session.add(pso)
        session.commit()

        session.refresh(etf)
        assert len(etf.per_share_operating) == 1


class TestPerShareDistribution:
    def test_create_per_share_distribution(self, session):
        etf = _make_etf()
        session.add(etf)
        session.flush()

        psd = PerShareDistribution(
            etf_id=etf.id,
            fiscal_year_end=date(2024, 1, 31),
            filing_date=date(2024, 3, 1),
            dist_net_investment_income=Decimal("-2.5000"),
            dist_realized_gains=Decimal("-0.5000"),
            dist_return_of_capital=Decimal("-0.1000"),
            dist_total=Decimal("-3.1000"),
        )
        session.add(psd)
        session.commit()

        result = session.query(PerShareDistribution).one()
        assert result.dist_net_investment_income == Decimal("-2.5000")
        assert result.dist_total == Decimal("-3.1000")

    def test_per_share_distribution_unique_constraint(self, session):
        etf = _make_etf()
        session.add(etf)
        session.flush()

        session.add(
            PerShareDistribution(
                etf_id=etf.id,
                fiscal_year_end=date(2024, 1, 31),
                filing_date=date(2024, 3, 1),
            )
        )
        session.commit()

        session.add(
            PerShareDistribution(
                etf_id=etf.id,
                fiscal_year_end=date(2024, 1, 31),
                filing_date=date(2024, 3, 1),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()

    def test_etf_per_share_distributions_relationship(self, session):
        etf = _make_etf()
        session.add(etf)
        session.flush()

        psd = PerShareDistribution(
            etf_id=etf.id,
            fiscal_year_end=date(2024, 1, 31),
            filing_date=date(2024, 3, 1),
        )
        session.add(psd)
        session.commit()

        session.refresh(etf)
        assert len(etf.per_share_distributions) == 1


class TestPerShareRatios:
    def test_create_per_share_ratios(self, session):
        etf = _make_etf()
        session.add(etf)
        session.flush()

        psr = PerShareRatios(
            etf_id=etf.id,
            fiscal_year_end=date(2024, 1, 31),
            filing_date=date(2024, 3, 1),
            expense_ratio=Decimal("0.00090"),
            portfolio_turnover=Decimal("0.50000"),
            net_assets_end=Decimal("1000000000.00"),
        )
        session.add(psr)
        session.commit()

        result = session.query(PerShareRatios).one()
        assert result.expense_ratio == Decimal("0.00090")
        assert result.net_assets_end == Decimal("1000000000.00")

    def test_per_share_ratios_unique_constraint(self, session):
        etf = _make_etf()
        session.add(etf)
        session.flush()

        session.add(
            PerShareRatios(
                etf_id=etf.id,
                fiscal_year_end=date(2024, 1, 31),
                filing_date=date(2024, 3, 1),
            )
        )
        session.commit()

        session.add(
            PerShareRatios(
                etf_id=etf.id,
                fiscal_year_end=date(2024, 1, 31),
                filing_date=date(2024, 3, 1),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()

    def test_etf_per_share_ratios_relationship(self, session):
        etf = _make_etf()
        session.add(etf)
        session.flush()

        psr = PerShareRatios(
            etf_id=etf.id,
            fiscal_year_end=date(2024, 1, 31),
            filing_date=date(2024, 3, 1),
        )
        session.add(psr)
        session.commit()

        session.refresh(etf)
        assert len(etf.per_share_ratios) == 1


class TestProcessingLog:
    def test_create_processing_log(self, session):
        log = ProcessingLog(
            cik="0001100663",
            parser_type="nport",
            last_run_at=datetime(2024, 2, 14, 10, 30, 0),
            latest_filing_date_seen=date(2024, 1, 31),
        )
        session.add(log)
        session.commit()

        result = session.query(ProcessingLog).one()
        assert result.cik == "0001100663"
        assert result.parser_type == "nport"
        assert result.latest_filing_date_seen == date(2024, 1, 31)

    def test_processing_log_unique_constraint(self, session):
        session.add(
            ProcessingLog(
                cik="0001100663",
                parser_type="nport",
                last_run_at=datetime(2024, 2, 14, 10, 30, 0),
                latest_filing_date_seen=date(2024, 1, 31),
            )
        )
        session.commit()

        session.add(
            ProcessingLog(
                cik="0001100663",
                parser_type="nport",
                last_run_at=datetime(2024, 2, 14, 11, 0, 0),
                latest_filing_date_seen=date(2024, 2, 28),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()

    def test_processing_log_allows_different_parsers(self, session):
        session.add(
            ProcessingLog(
                cik="0001100663",
                parser_type="nport",
                last_run_at=datetime(2024, 2, 14, 10, 30, 0),
                latest_filing_date_seen=date(2024, 1, 31),
            )
        )
        session.add(
            ProcessingLog(
                cik="0001100663",
                parser_type="ncsr",
                last_run_at=datetime(2024, 2, 14, 10, 35, 0),
                latest_filing_date_seen=date(2024, 1, 31),
            )
        )
        session.commit()

        result = session.query(ProcessingLog).all()
        assert len(result) == 2
