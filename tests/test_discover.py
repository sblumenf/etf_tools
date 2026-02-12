import json
from unittest.mock import patch, MagicMock

from etf_pipeline.discover import fetch

MOCK_SEC_DATA = {
    "fields": ["cik", "seriesId", "classId", "symbol"],
    "data": [
        [884394, "S000005325", "C000013536", "SPY"],
        [1592900, "S000047440", "C000148278", "IJAN"],
        [2110, "S000009184", "C000024954", "LACAX"],
    ],
}


def test_fetch_and_filter(tmp_path, monkeypatch):
    monkeypatch.setattr("etf_pipeline.discover.DATA_DIR", tmp_path)
    monkeypatch.setattr("etf_pipeline.discover.FILTERED_FILE", tmp_path / "filtered.json")

    resp = MagicMock()
    resp.read.return_value = json.dumps(MOCK_SEC_DATA).encode()
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=resp):
        etfs = fetch()

    assert len(etfs) == 2
    tickers = {e["ticker"] for e in etfs}
    assert tickers == {"SPY", "IJAN"}
