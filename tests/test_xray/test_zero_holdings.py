"""Tests for X-Ray route behavior when an ETF has no holdings."""
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import pytest

from etf_pipeline.api.main import app
from etf_pipeline.api.deps import get_db
from etf_pipeline.models import Base, ETF


@pytest.fixture()
def zero_holdings_client():
    """TestClient backed by an in-memory DB containing an ETF with no holdings."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def set_fk(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)

    factory = sessionmaker(bind=engine)
    with factory() as seed_session:
        seed_session.add(
            ETF(
                ticker="EMPTY",
                cik="0000000001",
                series_id="S000000001",
                issuer_name="Test Issuer",
                fund_name="Empty Holdings ETF",
            )
        )
        seed_session.commit()

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    yield client
    app.dependency_overrides.pop(get_db, None)
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_xray_zero_holdings_returns_200(zero_holdings_client):
    resp = zero_holdings_client.get("/api/v1/xray/EMPTY")
    assert resp.status_code == 200


def test_xray_zero_holdings_holdings_derived_fields_are_none(zero_holdings_client):
    data = zero_holdings_client.get("/api/v1/xray/EMPTY").json()
    assert data["holdings"] is None
    assert data["concentration"] is None
    assert data["geographic"] is None
    assert data["asset_allocation"] is None


def test_xray_zero_holdings_data_completeness_holdings_false(zero_holdings_client):
    data = zero_holdings_client.get("/api/v1/xray/EMPTY").json()
    assert data["data_completeness"]["holdings"] is False


def test_xray_zero_holdings_ticker_and_name_present(zero_holdings_client):
    data = zero_holdings_client.get("/api/v1/xray/EMPTY").json()
    assert data["ticker"] == "EMPTY"
    assert data["name"] == "Empty Holdings ETF"
