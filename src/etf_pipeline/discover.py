"""Fetch SEC company tickers and filter to ETFs."""

import json
import os
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers_mf.json"
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
FILTERED_FILE = DATA_DIR / "etf_tickers.json"


def fetch():
    """Download company_tickers_mf.json and filter to ETFs."""
    DATA_DIR.mkdir(exist_ok=True)

    identity = os.environ.get("EDGAR_IDENTITY", "etf-pipeline admin@example.com")
    req = urllib.request.Request(SEC_TICKERS_URL, headers={"User-Agent": identity})
    with urllib.request.urlopen(req) as resp:
        raw = json.loads(resp.read())

    fields = raw["fields"]
    ci, si, syi = fields.index("cik"), fields.index("seriesId"), fields.index("symbol")

    etfs = [
        {"ticker": r[syi], "cik": r[ci], "series_id": r[si]}
        for r in raw["data"]
        if r[syi] and len(r[syi]) in (3, 4)
    ]

    FILTERED_FILE.write_text(json.dumps(etfs, indent=2))
    return etfs
