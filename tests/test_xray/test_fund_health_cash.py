"""Tests for fund_health.cash_position_pct calculation in the xray route.

Covers:
  - STIV holdings only (cash_not_reported is None): cash_position_pct comes from holdings
  - Both STIV holdings and cash_not_reported present: values are summed
  - Neither STIV holdings nor cash_not_reported: cash_position_pct is None
  - cash_not_reported non-zero, no STIV holdings: cash_position_pct comes from cash_not_reported alone
"""
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from etf_pipeline.api.deps import get_db
from etf_pipeline.api.main import app
from etf_pipeline.models import Base, ETF, FundSnapshot, Holding


def _make_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def set_fk(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    return engine


def _make_client(engine):
    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _teardown(engine):
    app.dependency_overrides.pop(get_db, None)
    Base.metadata.drop_all(engine)
    engine.dispose()


# ---------------------------------------------------------------------------
# Fixture: STIV holdings only, cash_not_reported is None
# net_assets=10000, STIV value_usd=500 -> cash_position_pct = 500/10000*100 = 5.0
# ---------------------------------------------------------------------------

@pytest.fixture()
def stiv_only_client():
    """ETF with STIV holding and no cash_not_reported on snapshot."""
    engine = _make_engine()
    factory = sessionmaker(bind=engine)

    with factory() as sess:
        etf = ETF(
            ticker="STIVONLY",
            cik="0000000030",
            series_id="S000000030",
            issuer_name="Test Issuer",
            fund_name="STIV Only ETF",
        )
        sess.add(etf)
        sess.flush()

        sess.add(
            Holding(
                etf_id=etf.id,
                report_date=date(2024, 12, 31),
                filing_date=date(2025, 1, 15),
                name="T-Bill",
                cusip="912796AA0",
                asset_category="STIV",
                value_usd=Decimal("500"),
                pct_val=Decimal("5.0"),
                holding_key="912796AA0",
            )
        )

        sess.add(
            FundSnapshot(
                cik="0000000030",
                series_id="S000000030",
                report_date=date(2024, 12, 31),
                filing_date=date(2025, 1, 15),
                net_assets=Decimal("10000"),
                total_assets=Decimal("10500"),
                cash_not_reported=None,
            )
        )
        sess.commit()

    client = _make_client(engine)
    yield client
    _teardown(engine)


# ---------------------------------------------------------------------------
# Fixture: both STIV holdings and cash_not_reported present
# net_assets=10000, STIV value_usd=500, cash_not_reported=300
# total_cash = 800 -> cash_position_pct = 800/10000*100 = 8.0
# ---------------------------------------------------------------------------

@pytest.fixture()
def stiv_and_cash_client():
    """ETF with STIV holding and non-zero cash_not_reported on snapshot."""
    engine = _make_engine()
    factory = sessionmaker(bind=engine)

    with factory() as sess:
        etf = ETF(
            ticker="STIVANDCASH",
            cik="0000000031",
            series_id="S000000031",
            issuer_name="Test Issuer",
            fund_name="STIV And Cash ETF",
        )
        sess.add(etf)
        sess.flush()

        sess.add(
            Holding(
                etf_id=etf.id,
                report_date=date(2024, 12, 31),
                filing_date=date(2025, 1, 15),
                name="T-Bill",
                cusip="912796BB0",
                asset_category="STIV",
                value_usd=Decimal("500"),
                pct_val=Decimal("5.0"),
                holding_key="912796BB0",
            )
        )

        sess.add(
            FundSnapshot(
                cik="0000000031",
                series_id="S000000031",
                report_date=date(2024, 12, 31),
                filing_date=date(2025, 1, 15),
                net_assets=Decimal("10000"),
                total_assets=Decimal("10800"),
                cash_not_reported=Decimal("300"),
            )
        )
        sess.commit()

    client = _make_client(engine)
    yield client
    _teardown(engine)


# ---------------------------------------------------------------------------
# Fixture: no STIV holdings, cash_not_reported is None
# ---------------------------------------------------------------------------

@pytest.fixture()
def no_cash_client():
    """ETF with non-STIV holding and no cash_not_reported — cash_position_pct must be None."""
    engine = _make_engine()
    factory = sessionmaker(bind=engine)

    with factory() as sess:
        etf = ETF(
            ticker="NOCASH",
            cik="0000000032",
            series_id="S000000032",
            issuer_name="Test Issuer",
            fund_name="No Cash ETF",
        )
        sess.add(etf)
        sess.flush()

        sess.add(
            Holding(
                etf_id=etf.id,
                report_date=date(2024, 12, 31),
                filing_date=date(2025, 1, 15),
                name="Apple Inc",
                cusip="037833100",
                asset_category="EC",
                value_usd=Decimal("9000"),
                pct_val=Decimal("90.0"),
                holding_key="037833100",
            )
        )

        sess.add(
            FundSnapshot(
                cik="0000000032",
                series_id="S000000032",
                report_date=date(2024, 12, 31),
                filing_date=date(2025, 1, 15),
                net_assets=Decimal("10000"),
                total_assets=Decimal("10000"),
                cash_not_reported=None,
            )
        )
        sess.commit()

    client = _make_client(engine)
    yield client
    _teardown(engine)


# ---------------------------------------------------------------------------
# Tests: STIV only
# ---------------------------------------------------------------------------

def test_stiv_only_cash_position_pct_is_not_none(stiv_only_client):
    """cash_position_pct must be populated when STIV holdings exist even with no cash_not_reported."""
    data = stiv_only_client.get("/api/v1/xray/STIVONLY").json()
    assert data["fund_health"]["cash_position_pct"] is not None


def test_stiv_only_cash_position_pct_value(stiv_only_client):
    """cash_position_pct = STIV value_usd / net_assets * 100 = 500/10000*100 = 5.0."""
    data = stiv_only_client.get("/api/v1/xray/STIVONLY").json()
    assert data["fund_health"]["cash_position_pct"] == pytest.approx(5.0, abs=0.01)


# ---------------------------------------------------------------------------
# Tests: STIV + cash_not_reported
# ---------------------------------------------------------------------------

def test_stiv_and_cash_position_pct_is_not_none(stiv_and_cash_client):
    """cash_position_pct must be set when both STIV holdings and cash_not_reported are present."""
    data = stiv_and_cash_client.get("/api/v1/xray/STIVANDCASH").json()
    assert data["fund_health"]["cash_position_pct"] is not None


def test_stiv_and_cash_position_pct_sums_both(stiv_and_cash_client):
    """cash_position_pct = (STIV value_usd + cash_not_reported) / net_assets * 100 = 800/10000*100 = 8.0."""
    data = stiv_and_cash_client.get("/api/v1/xray/STIVANDCASH").json()
    assert data["fund_health"]["cash_position_pct"] == pytest.approx(8.0, abs=0.01)


# ---------------------------------------------------------------------------
# Tests: no cash at all
# ---------------------------------------------------------------------------

def test_no_cash_position_pct_is_none(no_cash_client):
    """cash_position_pct must be None when there are no STIV holdings and cash_not_reported is None."""
    data = no_cash_client.get("/api/v1/xray/NOCASH").json()
    assert data["fund_health"]["cash_position_pct"] is None


# ---------------------------------------------------------------------------
# Fixture: no STIV holdings, cash_not_reported is non-zero
# net_assets=100000, cash_not_reported=13400 -> cash_position_pct = 13400/100000*100 = 13.4
# Models the Franklin FTSE Hong Kong ETF case: bank cash present, no STIV holdings.
# ---------------------------------------------------------------------------

@pytest.fixture()
def cash_not_reported_no_stiv_client():
    """ETF with non-STIV equity holdings and non-zero cash_not_reported on snapshot."""
    engine = _make_engine()
    factory = sessionmaker(bind=engine)

    with factory() as sess:
        etf = ETF(
            ticker="CASHONLY",
            cik="0000000033",
            series_id="S000000033",
            issuer_name="Test Issuer",
            fund_name="Cash Not Reported No STIV ETF",
        )
        sess.add(etf)
        sess.flush()

        sess.add(
            Holding(
                etf_id=etf.id,
                report_date=date(2024, 12, 31),
                filing_date=date(2025, 1, 15),
                name="HSBC Holdings",
                cusip="404280406",
                asset_category="EC",
                value_usd=Decimal("86600"),
                pct_val=Decimal("86.6"),
                holding_key="404280406",
            )
        )

        sess.add(
            FundSnapshot(
                cik="0000000033",
                series_id="S000000033",
                report_date=date(2024, 12, 31),
                filing_date=date(2025, 1, 15),
                net_assets=Decimal("100000"),
                total_assets=Decimal("100000"),
                cash_not_reported=Decimal("13400"),
            )
        )
        sess.commit()

    client = _make_client(engine)
    yield client
    _teardown(engine)


# ---------------------------------------------------------------------------
# Tests: cash_not_reported only (no STIV holdings)
# ---------------------------------------------------------------------------

def test_cash_not_reported_no_stiv_is_not_none(cash_not_reported_no_stiv_client):
    """cash_position_pct must be populated when cash_not_reported is set even with no STIV holdings."""
    data = cash_not_reported_no_stiv_client.get("/api/v1/xray/CASHONLY").json()
    assert data["fund_health"]["cash_position_pct"] is not None


def test_cash_not_reported_no_stiv_value(cash_not_reported_no_stiv_client):
    """cash_position_pct = cash_not_reported / net_assets * 100 = 13400/100000*100 = 13.4."""
    data = cash_not_reported_no_stiv_client.get("/api/v1/xray/CASHONLY").json()
    assert data["fund_health"]["cash_position_pct"] == pytest.approx(13.4, abs=0.01)
