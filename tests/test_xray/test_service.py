"""Integration tests for xray service layer — uses real DB."""
import calendar
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from etf_pipeline.db import get_engine
from etf_pipeline.models import Base, ETF, NPORTMonthlyReturn
from etf_pipeline.xray import service


@pytest.fixture(scope="module")
def db():
    engine = get_engine()
    with Session(engine) as session:
        yield session


def test_search_etfs_empty_query(db):
    results = service.search_etfs(db, "")
    assert results == []


def test_search_etfs_partial_match(db):
    results = service.search_etfs(db, "SP")
    assert isinstance(results, list)
    assert len(results) <= 20


def test_get_etf_not_found(db):
    result = service.get_etf(db, "NOTEXIST99")
    assert result is None


def test_get_etf_spy_if_exists(db):
    result = service.get_etf(db, "SPY")
    if result:
        assert result.ticker == "SPY"


def test_get_holdings_returns_list(db):
    etf = service.get_etf(db, "SPY")
    if etf:
        holdings = service.get_holdings(db, etf.id)
        assert isinstance(holdings, list)


# ---------------------------------------------------------------------------
# Unit tests for compute_performance_from_monthly (in-memory SQLite)
# ---------------------------------------------------------------------------

def _make_mem_engine():
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


@pytest.fixture()
def mem_session():
    engine = _make_mem_engine()
    factory = sessionmaker(bind=engine)
    sess = factory()
    yield sess
    sess.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


def _add_etf(sess):
    etf = ETF(ticker="TESTUIT", cik="0000099999", issuer_name="Test Issuer")
    sess.add(etf)
    sess.flush()
    return etf


def _add_quarterly_returns(sess, etf_id, quarter_ends, monthly_return_pct):
    for quarter_end in quarter_ends:
        last_day = calendar.monthrange(quarter_end.year, quarter_end.month)[1]
        sess.add(NPORTMonthlyReturn(
            etf_id=etf_id,
            report_date=date(quarter_end.year, quarter_end.month, last_day),
            filing_date=date(quarter_end.year, quarter_end.month, last_day),
            month_1_return=Decimal(str(monthly_return_pct)),
            month_2_return=Decimal(str(monthly_return_pct)),
            month_3_return=Decimal(str(monthly_return_pct)),
        ))


def test_compute_perf_returns_none_when_no_rows(mem_session):
    etf = _add_etf(mem_session)
    mem_session.commit()
    result = service.compute_performance_from_monthly(mem_session, etf.id)
    assert result is None


def test_compute_perf_returns_none_when_insufficient_data(mem_session):
    etf = _add_etf(mem_session)
    _add_quarterly_returns(mem_session, etf.id, [date(2024, 9, 30)], 1.0)
    mem_session.commit()
    result = service.compute_performance_from_monthly(mem_session, etf.id)
    assert result is None


def test_compute_perf_1yr_with_four_quarterly_filings(mem_session):
    etf = _add_etf(mem_session)
    quarter_ends = [
        date(2024, 12, 31),
        date(2024, 9, 30),
        date(2024, 6, 30),
        date(2024, 3, 31),
    ]
    _add_quarterly_returns(mem_session, etf.id, quarter_ends, 1.0)
    mem_session.commit()

    result = service.compute_performance_from_monthly(mem_session, etf.id)
    assert result is not None
    assert "return_1yr" in result
    expected = ((1.01 ** 12) - 1) * 100
    assert result["return_1yr"] == pytest.approx(expected, rel=1e-6)


def test_compute_perf_no_5yr_when_fewer_than_60_months(mem_session):
    etf = _add_etf(mem_session)
    quarter_ends = [
        date(2024, 12, 31),
        date(2024, 9, 30),
        date(2024, 6, 30),
        date(2024, 3, 31),
    ]
    _add_quarterly_returns(mem_session, etf.id, quarter_ends, 1.0)
    mem_session.commit()

    result = service.compute_performance_from_monthly(mem_session, etf.id)
    assert result is not None
    assert "return_5yr" not in result


def test_compute_perf_5yr_annualized_with_20_quarterly_filings(mem_session):
    etf = _add_etf(mem_session)
    # Build 20 quarters ending Dec 2024 going back
    year, month = 2024, 12
    quarter_ends = []
    for _ in range(20):
        last_day = calendar.monthrange(year, month)[1]
        quarter_ends.append(date(year, month, last_day))
        total = year * 12 + month - 1 - 3
        year, month = total // 12, total % 12 + 1
    _add_quarterly_returns(mem_session, etf.id, quarter_ends, 1.0)
    mem_session.commit()

    result = service.compute_performance_from_monthly(mem_session, etf.id)
    assert result is not None
    assert "return_5yr" in result
    cum = (1.01 ** 60) - 1
    expected = ((1 + cum) ** (1 / 5) - 1) * 100
    assert result["return_5yr"] == pytest.approx(expected, rel=1e-6)


def test_compute_perf_no_double_counting_overlapping_months(mem_session):
    etf = _add_etf(mem_session)
    # Two rows with same report_date but different filing_date — same calendar months.
    # The later filing_date (amended) should win; months must be counted only once.
    mem_session.add(NPORTMonthlyReturn(
        etf_id=etf.id,
        report_date=date(2024, 12, 31),
        filing_date=date(2025, 1, 15),  # original
        month_1_return=Decimal("1.0"),
        month_2_return=Decimal("1.0"),
        month_3_return=Decimal("1.0"),
    ))
    mem_session.add(NPORTMonthlyReturn(
        etf_id=etf.id,
        report_date=date(2024, 12, 31),
        filing_date=date(2025, 2, 1),   # amendment
        month_1_return=Decimal("2.0"),
        month_2_return=Decimal("2.0"),
        month_3_return=Decimal("2.0"),
    ))
    for quarter_end in [date(2024, 9, 30), date(2024, 6, 30), date(2024, 3, 31)]:
        _add_quarterly_returns(mem_session, etf.id, [quarter_end], 2.0)
    mem_session.commit()

    result = service.compute_performance_from_monthly(mem_session, etf.id)
    assert result is not None
    # Latest filing for Dec-2024 quarter used 2%; all other months also 2%
    expected = ((1.02 ** 12) - 1) * 100
    assert result["return_1yr"] == pytest.approx(expected, rel=1e-3)


def test_compute_perf_skips_none_return_values(mem_session):
    etf = _add_etf(mem_session)
    for quarter_end in [
        date(2024, 12, 31),
        date(2024, 9, 30),
        date(2024, 6, 30),
        date(2024, 3, 31),
    ]:
        last_day = calendar.monthrange(quarter_end.year, quarter_end.month)[1]
        mem_session.add(NPORTMonthlyReturn(
            etf_id=etf.id,
            report_date=date(quarter_end.year, quarter_end.month, last_day),
            filing_date=date(quarter_end.year, quarter_end.month, last_day),
            month_1_return=Decimal("1.0"),
            month_2_return=None,
            month_3_return=Decimal("1.0"),
        ))
    mem_session.commit()

    # Only 8 months of data (4 filings x 2 months each) — not enough for 1yr
    result = service.compute_performance_from_monthly(mem_session, etf.id)
    assert result is None
