"""Integration tests for API endpoints."""
import pytest
from fastapi.testclient import TestClient
from etf_pipeline.api.main import app


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_search_empty_query(client):
    resp = client.get("/api/v1/etfs/search?q=")
    assert resp.status_code == 200
    assert resp.json() == []


def test_search_returns_list(client):
    resp = client.get("/api/v1/etfs/search?q=spy")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_xray_not_found(client):
    resp = client.get("/api/v1/xray/NOTEXIST99")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "ETF not found"


def test_xray_spy_if_exists(client):
    """SPY xray endpoint returns valid JSON structure."""
    resp = client.get("/api/v1/xray/SPY")
    if resp.status_code == 404:
        pytest.skip("SPY not in test database")
    assert resp.status_code == 200
    data = resp.json()
    assert "ticker" in data
    assert "data_completeness" in data
    assert "holdings" in data
    assert "fees" in data
    assert "performance" in data
    assert "fund_health" in data
