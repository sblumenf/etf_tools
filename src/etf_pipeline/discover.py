"""Fetch SEC company tickers and filter to ETFs."""

import json
import logging
import os
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from etf_pipeline.config import EDGAR_IDENTITY

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers_mf.json"
EFTS_S6_URL = "https://efts.sec.gov/LATEST/search-index?forms=S-6&dateRange=custom&startdt=2020-01-01"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
FILTERED_FILE = DATA_DIR / "etf_tickers.json"

log = logging.getLogger(__name__)


def _fetch_with_retry(url, headers, max_retries=3):
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as resp:
                return resp.read()
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
            if attempt == max_retries - 1:
                raise
            wait = 2 ** attempt
            log.warning("Fetch %s failed (attempt %d/%d): %s, retrying in %ds", url, attempt + 1, max_retries, e, wait)
            time.sleep(wait)


EXCHANGE_NAMES = {"NYSE", "NASDAQ", "NYSE ARCA", "NYSEARCA", "BATS", "CBOE", "NYSE MKT", "NYSE American"}

_SEC_REQUEST_DELAY = 0.1  # seconds between SEC EDGAR requests (10 req/s limit)

# Exchange-traded UITs that filed under obsolete S-6EL24 (not indexed by EFTS)
UIT_ETF_ALLOWLIST = [
    {"ticker": "SPY", "cik": 884394, "series_id": None, "class_id": None},
    {"ticker": "DIA", "cik": 1041130, "series_id": None, "class_id": None},
    {"ticker": "MDY", "cik": 936958, "series_id": None, "class_id": None},
]


def _fetch_uit_etfs():
    """Discover UIT ETFs by finding S-6 filers on EDGAR and checking their exchange listings."""
    identity = EDGAR_IDENTITY
    headers = {"User-Agent": identity}

    ciks = set()
    start = 0
    page_size = 100

    while True:
        url = f"{EFTS_S6_URL}&from={start}&size={page_size}"
        try:
            data = json.loads(_fetch_with_retry(url, headers))
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
            log.warning("EFTS page fetch failed at offset %d: %s, stopping pagination", start, e)
            break

        hits = data.get("hits", {}).get("hits", [])
        total = data.get("hits", {}).get("total", {}).get("value", 0)
        log.debug("EFTS S-6 search: %d total hits, fetched %d (from=%d)", total, len(hits), start)

        for hit in hits:
            src = hit.get("_source", {})
            ciks_list = src.get("ciks") or []
            cik_str = str(ciks_list[0]) if ciks_list else ""
            if cik_str:
                try:
                    ciks.add(int(cik_str))
                except (ValueError, TypeError):
                    pass

        time.sleep(_SEC_REQUEST_DELAY)
        start += len(hits)
        if start >= total or not hits:
            break

    log.debug("Found %d unique CIKs from S-6 filings", len(ciks))

    uit_etfs = []
    for cik in ciks:
        cik_padded = str(cik).zfill(10)
        url = SUBMISSIONS_URL.format(cik=cik_padded)
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as resp:
                sub = json.loads(resp.read())
        except Exception as exc:
            log.warning("Failed to fetch submissions for CIK %s: %s", cik, exc)
            continue
        time.sleep(_SEC_REQUEST_DELAY)

        tickers = sub.get("tickers", [])
        exchanges = sub.get("exchanges", [])

        if not tickers:
            continue

        exchange_set = {e.upper() for e in exchanges}
        is_exchange_traded = bool(exchange_set & {e.upper() for e in EXCHANGE_NAMES})
        if not is_exchange_traded:
            continue

        for ticker in tickers:
            if ticker and len(ticker) in (2, 3, 4):
                uit_etfs.append({
                    "ticker": ticker,
                    "cik": cik,
                    "series_id": None,
                    "class_id": None,
                })

    log.info("Discovered %d UIT ETF ticker(s) from S-6 filers", len(uit_etfs))
    return uit_etfs


def fetch():
    """Download company_tickers_mf.json and filter to ETFs."""
    DATA_DIR.mkdir(exist_ok=True)

    identity = EDGAR_IDENTITY
    raw = json.loads(_fetch_with_retry(SEC_TICKERS_URL, {"User-Agent": identity}))

    fields = raw["fields"]
    ci, si, cli, syi = fields.index("cik"), fields.index("seriesId"), fields.index("classId"), fields.index("symbol")

    etfs = [
        {"ticker": r[syi], "cik": r[ci], "series_id": r[si], "class_id": r[cli]}
        for r in raw["data"]
        if r[syi] and len(r[syi]) in (2, 3, 4)
    ]

    try:
        uit_etfs = _fetch_uit_etfs()
    except Exception as exc:
        log.warning("UIT ETF discovery failed, continuing with MF data only: %s", exc)
        uit_etfs = []

    existing_tickers = {e["ticker"] for e in etfs}
    for entry in uit_etfs:
        if entry["ticker"] not in existing_tickers:
            etfs.append(entry)
            existing_tickers.add(entry["ticker"])

    # Always include known exchange-traded UITs regardless of EFTS discovery success
    for entry in UIT_ETF_ALLOWLIST:
        if entry["ticker"] not in existing_tickers:
            etfs.append(entry)
            existing_tickers.add(entry["ticker"])

    tmp_fd, tmp_path = tempfile.mkstemp(dir=str(DATA_DIR), suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w") as tmp_f:
            json.dump(etfs, tmp_f, indent=2)
        os.replace(tmp_path, str(FILTERED_FILE))
    except BaseException:
        os.unlink(tmp_path)
        raise
    return etfs
