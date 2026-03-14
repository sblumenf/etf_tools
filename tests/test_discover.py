import json
from unittest.mock import patch, MagicMock, call

from etf_pipeline.discover import fetch

# MF data — SPY is NOT here; it's a UIT and comes from S-6 discovery
MOCK_MF_DATA = {
    "fields": ["cik", "seriesId", "classId", "symbol"],
    "data": [
        [1592900, "S000047440", "C000148278", "IJAN"],
        [2110, "S000009184", "C000024954", "LACAX"],
    ],
}

# EFTS S-6 search response
MOCK_EFTS_RESPONSE = {
    "hits": {
        "total": {"value": 1},
        "hits": [
            {
                "_source": {
                    "cik": "884394",
                    "entity_name": "SPDR S&P 500 ETF TRUST",
                }
            }
        ],
    }
}

# Submissions response for CIK 884394 (SPY)
MOCK_SUBMISSIONS_SPY = {
    "tickers": ["SPY"],
    "exchanges": ["NYSE Arca"],
}


def _make_resp(payload):
    resp = MagicMock()
    resp.read.return_value = json.dumps(payload).encode()
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def test_fetch_mf_tickers_filtered(tmp_path, monkeypatch):
    """MF tickers pass through with series_id/class_id intact; 5-char tickers excluded."""
    monkeypatch.setattr("etf_pipeline.discover.DATA_DIR", tmp_path)
    monkeypatch.setattr("etf_pipeline.discover.FILTERED_FILE", tmp_path / "filtered.json")

    def urlopen_side_effect(req):
        url = req.full_url
        if "company_tickers_mf" in url:
            return _make_resp(MOCK_MF_DATA)
        if "efts.sec.gov" in url:
            return _make_resp(MOCK_EFTS_RESPONSE)
        if "submissions" in url:
            return _make_resp(MOCK_SUBMISSIONS_SPY)
        raise ValueError(f"Unexpected URL: {url}")

    with patch("urllib.request.urlopen", side_effect=urlopen_side_effect):
        etfs = fetch()

    tickers = {e["ticker"] for e in etfs}
    assert "IJAN" in tickers
    assert "LACAX" not in tickers  # 5 chars, filtered out


def test_fetch_uit_etfs_discovered(tmp_path, monkeypatch):
    """UIT ETFs from S-6 filers are included with series_id=None and class_id=None."""
    monkeypatch.setattr("etf_pipeline.discover.DATA_DIR", tmp_path)
    monkeypatch.setattr("etf_pipeline.discover.FILTERED_FILE", tmp_path / "filtered.json")

    def urlopen_side_effect(req):
        url = req.full_url
        if "company_tickers_mf" in url:
            return _make_resp(MOCK_MF_DATA)
        if "efts.sec.gov" in url:
            return _make_resp(MOCK_EFTS_RESPONSE)
        if "submissions" in url:
            return _make_resp(MOCK_SUBMISSIONS_SPY)
        raise ValueError(f"Unexpected URL: {url}")

    with patch("urllib.request.urlopen", side_effect=urlopen_side_effect):
        etfs = fetch()

    spy = next((e for e in etfs if e["ticker"] == "SPY"), None)
    assert spy is not None
    assert spy["series_id"] is None
    assert spy["class_id"] is None
    assert spy["cik"] == 884394


def test_fetch_dedup_mf_takes_precedence(tmp_path, monkeypatch):
    """If a ticker appears in both MF and UIT sources, the MF entry wins."""
    monkeypatch.setattr("etf_pipeline.discover.DATA_DIR", tmp_path)
    monkeypatch.setattr("etf_pipeline.discover.FILTERED_FILE", tmp_path / "filtered.json")

    # MF data includes IJAN; EFTS returns a CIK whose submissions also list IJAN
    mf_data_with_ijan = {
        "fields": ["cik", "seriesId", "classId", "symbol"],
        "data": [
            [1592900, "S000047440", "C000148278", "IJAN"],
        ],
    }
    submissions_with_ijan = {
        "tickers": ["IJAN"],
        "exchanges": ["NYSE Arca"],
    }

    def urlopen_side_effect(req):
        url = req.full_url
        if "company_tickers_mf" in url:
            return _make_resp(mf_data_with_ijan)
        if "efts.sec.gov" in url:
            return _make_resp(MOCK_EFTS_RESPONSE)
        if "submissions" in url:
            return _make_resp(submissions_with_ijan)
        raise ValueError(f"Unexpected URL: {url}")

    with patch("urllib.request.urlopen", side_effect=urlopen_side_effect):
        etfs = fetch()

    ijan_entries = [e for e in etfs if e["ticker"] == "IJAN"]
    assert len(ijan_entries) == 1
    # MF entry has series_id set
    assert ijan_entries[0]["series_id"] == "S000047440"


def test_fetch_graceful_degradation_on_uit_failure(tmp_path, monkeypatch):
    """If UIT discovery raises, MF data is still returned."""
    monkeypatch.setattr("etf_pipeline.discover.DATA_DIR", tmp_path)
    monkeypatch.setattr("etf_pipeline.discover.FILTERED_FILE", tmp_path / "filtered.json")

    def urlopen_side_effect(req):
        url = req.full_url
        if "company_tickers_mf" in url:
            return _make_resp(MOCK_MF_DATA)
        # Any EFTS or submissions call raises a network error
        raise OSError("network error")

    with patch("urllib.request.urlopen", side_effect=urlopen_side_effect):
        etfs = fetch()

    tickers = {e["ticker"] for e in etfs}
    assert "IJAN" in tickers
    # SPY not present because UIT discovery failed
    assert "SPY" not in tickers


def test_fetch_uit_non_exchange_traded_excluded(tmp_path, monkeypatch):
    """UITs without a recognized exchange are excluded."""
    monkeypatch.setattr("etf_pipeline.discover.DATA_DIR", tmp_path)
    monkeypatch.setattr("etf_pipeline.discover.FILTERED_FILE", tmp_path / "filtered.json")

    submissions_no_exchange = {
        "tickers": ["XYZ"],
        "exchanges": [],
    }

    def urlopen_side_effect(req):
        url = req.full_url
        if "company_tickers_mf" in url:
            return _make_resp(MOCK_MF_DATA)
        if "efts.sec.gov" in url:
            return _make_resp(MOCK_EFTS_RESPONSE)
        if "submissions" in url:
            return _make_resp(submissions_no_exchange)
        raise ValueError(f"Unexpected URL: {url}")

    with patch("urllib.request.urlopen", side_effect=urlopen_side_effect):
        etfs = fetch()

    tickers = {e["ticker"] for e in etfs}
    assert "XYZ" not in tickers


def test_fetch_writes_json_file(tmp_path, monkeypatch):
    """Combined results are written to the output file."""
    monkeypatch.setattr("etf_pipeline.discover.DATA_DIR", tmp_path)
    out_file = tmp_path / "filtered.json"
    monkeypatch.setattr("etf_pipeline.discover.FILTERED_FILE", out_file)

    def urlopen_side_effect(req):
        url = req.full_url
        if "company_tickers_mf" in url:
            return _make_resp(MOCK_MF_DATA)
        if "efts.sec.gov" in url:
            return _make_resp(MOCK_EFTS_RESPONSE)
        if "submissions" in url:
            return _make_resp(MOCK_SUBMISSIONS_SPY)
        raise ValueError(f"Unexpected URL: {url}")

    with patch("urllib.request.urlopen", side_effect=urlopen_side_effect):
        etfs = fetch()

    written = json.loads(out_file.read_text())
    assert written == etfs
