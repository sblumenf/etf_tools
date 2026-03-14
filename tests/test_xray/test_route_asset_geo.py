"""Tests for xray route — cash merging and geographic Unknown grouping."""
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


# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------

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
# Cash merging test
# ---------------------------------------------------------------------------

@pytest.fixture()
def cash_merge_client():
    """ETF with one STIV holding AND a snapshot.cash_not_reported value.
    The route must merge both into a single 'Cash & Equivalents' bucket."""
    engine = _make_engine()
    factory = sessionmaker(bind=engine)

    with factory() as sess:
        etf = ETF(
            ticker="CASHTEST",
            cik="0000000010",
            series_id="S000000010",
            issuer_name="Test Issuer",
            fund_name="Cash Merge ETF",
        )
        sess.add(etf)
        sess.flush()

        # One STIV holding: pct_val=5.0, value_usd=500
        sess.add(
            Holding(
                etf_id=etf.id,
                report_date=date(2024, 12, 31),
                filing_date=date(2025, 1, 15),
                name="Treasury Bill",
                cusip="912796RQ0",
                asset_category="STIV",
                value_usd=Decimal("500"),
                pct_val=Decimal("5.0"),
                holding_key="912796RQ0",
            )
        )

        # snapshot with cash_not_reported: value=100, net_assets=2000 -> 5.0%
        sess.add(
            FundSnapshot(
                cik="0000000010",
                series_id="S000000010",
                report_date=date(2024, 12, 31),
                filing_date=date(2025, 1, 15),
                net_assets=Decimal("2000"),
                total_assets=Decimal("2100"),
                cash_not_reported=Decimal("100"),
            )
        )
        sess.commit()

    client = _make_client(engine)
    yield client
    _teardown(engine)


def test_cash_merge_produces_single_cash_bucket(cash_merge_client):
    """STIV holding + snapshot.cash_not_reported must appear as one bucket, not two."""
    data = cash_merge_client.get("/api/v1/xray/CASHTEST").json()
    assert data["asset_allocation"] is not None

    items = data["asset_allocation"]["items"]
    cash_items = [i for i in items if i["code"] == "STIV"]

    assert len(cash_items) == 1, (
        f"Expected exactly one STIV bucket, got {len(cash_items)}: {items}"
    )


def test_cash_merge_stiv_pct_includes_both_sources(cash_merge_client):
    """The single STIV bucket pct must include both the holding pct and cash_not_reported pct."""
    data = cash_merge_client.get("/api/v1/xray/CASHTEST").json()
    items = data["asset_allocation"]["items"]
    stiv = next(i for i in items if i["code"] == "STIV")

    # holding contributes 5.0%, cash_not_reported = 100/2000 * 100 = 5.0%
    # combined should be approximately 10.0%
    assert stiv["pct"] == pytest.approx(10.0, abs=0.01)


def test_cash_merge_display_name_is_cash_equivalents(cash_merge_client):
    """The merged STIV bucket must display as 'Cash & Equivalents'."""
    data = cash_merge_client.get("/api/v1/xray/CASHTEST").json()
    items = data["asset_allocation"]["items"]
    stiv = next(i for i in items if i["code"] == "STIV")

    assert stiv["display_name"] == "Cash & Equivalents"


# ---------------------------------------------------------------------------
# Geographic Unknown grouping test
# ---------------------------------------------------------------------------

@pytest.fixture()
def geo_unknown_client():
    """ETF with holdings having country=None — must appear under 'XX' / 'Unknown'."""
    engine = _make_engine()
    factory = sessionmaker(bind=engine)

    with factory() as sess:
        etf = ETF(
            ticker="GEOTEST",
            cik="0000000020",
            series_id="S000000020",
            issuer_name="Test Issuer",
            fund_name="Geo Unknown ETF",
        )
        sess.add(etf)
        sess.flush()

        # Holding with country=None (unknown origin)
        sess.add(
            Holding(
                etf_id=etf.id,
                report_date=date(2024, 12, 31),
                filing_date=date(2025, 1, 15),
                name="Mystery Security",
                cusip="999999990",
                asset_category="EC",
                country=None,
                value_usd=Decimal("3000"),
                pct_val=Decimal("30.0"),
                holding_key="999999990",
            )
        )
        # Holding with known country for contrast
        sess.add(
            Holding(
                etf_id=etf.id,
                report_date=date(2024, 12, 31),
                filing_date=date(2025, 1, 15),
                name="US Corp",
                cusip="111111110",
                asset_category="EC",
                country="US",
                value_usd=Decimal("7000"),
                pct_val=Decimal("70.0"),
                holding_key="111111110",
            )
        )
        sess.commit()

    client = _make_client(engine)
    yield client
    _teardown(engine)


def test_geo_none_country_appears_as_xx(geo_unknown_client):
    """Holdings with country=None must be grouped under country_code='XX', not dropped."""
    data = geo_unknown_client.get("/api/v1/xray/GEOTEST").json()
    assert data["geographic"] is not None

    items = data["geographic"]["items"]
    codes = [i["country_code"] for i in items]
    assert "XX" in codes, f"Expected 'XX' in geographic items, got: {codes}"


def test_geo_none_country_display_name_is_unknown(geo_unknown_client):
    """The 'XX' geographic bucket must display as 'Unknown'."""
    data = geo_unknown_client.get("/api/v1/xray/GEOTEST").json()
    items = data["geographic"]["items"]
    xx = next(i for i in items if i["country_code"] == "XX")

    assert xx["country_name"] == "Unknown"


def test_geo_none_country_not_dropped(geo_unknown_client):
    """Holdings with country=None must contribute their pct to the 'XX' bucket."""
    data = geo_unknown_client.get("/api/v1/xray/GEOTEST").json()
    items = data["geographic"]["items"]
    xx = next(i for i in items if i["country_code"] == "XX")

    assert xx["pct"] == pytest.approx(30.0, abs=0.01)


def test_geo_known_country_still_present(geo_unknown_client):
    """Known-country holdings must still appear alongside the 'XX' bucket."""
    data = geo_unknown_client.get("/api/v1/xray/GEOTEST").json()
    items = data["geographic"]["items"]
    codes = [i["country_code"] for i in items]
    assert "US" in codes
