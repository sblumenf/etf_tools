"""Integration tests for xray service layer — uses real DB."""
import pytest
from sqlalchemy.orm import Session
from etf_pipeline.db import get_engine
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
