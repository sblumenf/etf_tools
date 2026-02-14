"""Load ETF tickers into the database from etf_tickers.json."""

import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Optional

from edgar import Company
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from etf_pipeline.db import get_engine
from etf_pipeline.models import ETF
from etf_pipeline.sgml import parse_series_class_info

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
TICKERS_FILE = DATA_DIR / "etf_tickers.json"


def load_etfs(cik: Optional[str] = None, limit: Optional[int] = None) -> None:
    """Load ETF records from etf_tickers.json into the database.

    Args:
        cik: Optional CIK to process (all others will be skipped)
        limit: Optional limit on number of CIKs to process (alphabetical order)
    """
    if not TICKERS_FILE.exists():
        logger.error(f"File not found: {TICKERS_FILE}")
        print(f"Error: {TICKERS_FILE} does not exist. Run 'discover' command first.")
        return

    with open(TICKERS_FILE) as f:
        tickers = json.load(f)

    by_cik = defaultdict(list)
    for entry in tickers:
        by_cik[entry["cik"]].append(entry)

    ciks = sorted(by_cik.keys())

    if cik is not None:
        cik_int = int(cik)
        if cik_int in ciks:
            ciks = [cik_int]
            logger.info(f"Processing single CIK: {cik}")
        else:
            logger.warning(f"CIK {cik} not found in etf_tickers.json")
            print(f"CIK {cik} not found in etf_tickers.json")
            return

    if limit is not None:
        ciks = ciks[:limit]
        logger.info(f"Limiting to first {limit} CIKs")

    engine = get_engine()
    session_factory = sessionmaker(bind=engine)

    succeeded = 0
    failed = 0

    for cik_int in ciks:
        try:
            _process_cik(session_factory, cik_int, by_cik[cik_int])
            succeeded += 1
        except Exception as e:
            failed += 1
            logger.warning(f"Failed to process CIK {cik_int:010d}: {e}")

    print(f"\nSummary: {succeeded} CIKs succeeded, {failed} CIKs failed")
    logger.info(f"Summary: {succeeded} CIKs succeeded, {failed} CIKs failed")


def _process_cik(session_factory, cik_int: int, entries: list[dict]) -> None:
    """Process a single CIK: fetch issuer name, extract series names, and upsert all ETFs."""
    cik_padded = f"{cik_int:010d}"

    logger.info(f"Processing CIK {cik_padded}: {len(entries)} ETF(s)")

    company = Company(cik_padded)
    issuer_name = company.name

    # Extract series_id -> series_name mapping from recent filings
    # Try filing types in priority order (issuer-wide forms first)
    needed_series_ids = {entry.get("series_id") for entry in entries if entry.get("series_id")}
    series_mapping = {}
    filing_types = ["24F-2NT", "485BPOS", "N-CSR", "NPORT-P"]

    for filing_type in filing_types:
        if needed_series_ids and needed_series_ids.issubset(series_mapping.keys()):
            logger.info(f"CIK {cik_padded}: All {len(needed_series_ids)} needed series covered, stopping early")
            break

        try:
            filings = company.get_filings(form=filing_type)
            if filings and len(filings) > 0:
                filing = filings[0]
                if hasattr(filing, 'header') and hasattr(filing.header, 'text'):
                    header_text = filing.header.text
                    new_series = parse_series_class_info(header_text)['series']
                    # Merge new series, don't overwrite existing entries
                    for series_id, series_name in new_series.items():
                        if series_id not in series_mapping:
                            series_mapping[series_id] = series_name
                    logger.info(f"CIK {cik_padded}: Extracted {len(new_series)} series from {filing_type} (total: {len(series_mapping)})")
        except Exception as e:
            logger.warning(f"CIK {cik_padded}: Failed to extract series mapping from {filing_type}: {e}")

    logger.info(f"CIK {cik_padded}: issuer_name = {issuer_name}")

    with session_factory() as session:
        for entry in entries:
            # Look up fund_name by series_id, fall back to issuer_name
            series_id = entry.get("series_id")
            fund_name = series_mapping.get(series_id, issuer_name) if series_id else issuer_name

            logger.debug(f"CIK {cik_padded}, {entry['ticker']}: series_id={series_id}, fund_name={fund_name}")

            _upsert_etf(session, entry, cik_padded, issuer_name, fund_name)
        session.commit()

    logger.info(f"CIK {cik_padded}: committed {len(entries)} ETF(s)")


def _upsert_etf(
    session: Session, entry: dict, cik_padded: str, issuer_name: str, fund_name: str
) -> None:
    """Upsert a single ETF record (match on ticker)."""
    ticker = entry["ticker"]

    stmt = select(ETF).where(ETF.ticker == ticker)
    existing = session.execute(stmt).scalar_one_or_none()

    if existing:
        existing.cik = cik_padded
        existing.series_id = entry["series_id"]
        existing.class_id = entry["class_id"]
        existing.issuer_name = issuer_name
        existing.fund_name = fund_name
        logger.info(f"Updated ETF: {ticker}")
    else:
        etf = ETF(
            ticker=ticker,
            cik=cik_padded,
            series_id=entry["series_id"],
            class_id=entry["class_id"],
            issuer_name=issuer_name,
            fund_name=fund_name,
        )
        session.add(etf)
        logger.info(f"Inserted ETF: {ticker}")
