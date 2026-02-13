"""Parse Financial Highlights tables from N-CSR filings.

Financial Highlights section in N-CSR filings contains per-share operating data,
distribution data, and fund ratios that are NOT available in XBRL. This parser
extracts that data using positional HTML table parsing.
"""

import logging
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from bs4 import BeautifulSoup
from edgar import Company
from edgar.storage_management import clear_cache as edgar_clear_cache
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from etf_pipeline.db import get_engine
from etf_pipeline.models import (
    ETF,
    PerShareDistribution,
    PerShareOperating,
    PerShareRatios,
)

logger = logging.getLogger(__name__)


def _parse_decimal(value) -> Optional[Decimal]:
    """Parse value to Decimal, handling None, strings with formatting, and various types.

    Handles:
    - None -> None
    - "$1.23" -> 1.23
    - "(1.23)" -> -1.23 (parentheses indicate negative)
    - "1,234.56" -> 1234.56
    - "0.05%" -> 0.0005 (percentage to decimal)

    Args:
        value: Value to parse

    Returns:
        Decimal or None
    """
    if value is None:
        return None

    if isinstance(value, Decimal):
        return value

    # Convert to string for parsing
    s = str(value).strip()

    if not s or s in ("-", "—", "N/A", "n/a"):
        return None

    # Handle percentage
    is_percentage = "%" in s
    s = s.replace("%", "")

    # Handle parentheses as negative
    is_negative = False
    if s.startswith("(") and s.endswith(")"):
        is_negative = True
        s = s[1:-1]

    # Remove currency symbols and commas
    s = s.replace("$", "").replace(",", "")

    try:
        decimal_value = Decimal(s)
        if is_negative:
            decimal_value = -decimal_value
        if is_percentage:
            decimal_value = decimal_value / 100
        return decimal_value
    except (ValueError, TypeError, InvalidOperation):
        return None


def _parse_date(value: str) -> Optional[date]:
    """Parse date string to date object.

    Handles various formats like:
    - "12/31/2023"
    - "December 31, 2023"
    - "2023-12-31"

    Args:
        value: Date string

    Returns:
        date object or None
    """
    if not value:
        return None

    s = str(value).strip()

    # Try various formats
    for fmt in [
        "%m/%d/%Y",
        "%Y-%m-%d",
        "%B %d, %Y",
        "%b %d, %Y",
    ]:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue

    return None


def parse_financial_highlights_table(html_table_str: str) -> dict:
    """Parse a Financial Highlights HTML table using positional extraction.

    The Financial Highlights table follows a regulated structure (Form N-1A Item 13).
    Regardless of label variations, the ROW ORDER is fixed:
    1. NAV, Beginning of Period
    2. Investment Operations (NII, Gains, Total)
    3. Equalization (optional, some issuers only)
    4. Distributions (from NII, Cap Gains, ROC, Total)
    5. NAV, End of Period
    6. Total Return
    7. Ratios/Supplemental Data (expense ratio, turnover, net assets)

    Args:
        html_table_str: HTML string containing a single Financial Highlights table

    Returns:
        dict with keys:
        - operating: dict with nav_beginning, net_investment_income, etc.
        - distribution: dict with dist_net_investment_income, etc.
        - ratios: dict with expense_ratio, portfolio_turnover, net_assets_end
        - fiscal_year_end: date object
        - math_validated: bool
    """
    soup = BeautifulSoup(html_table_str, "lxml")
    table = soup.find("table")

    if not table:
        raise ValueError("No table found in HTML")

    # Extract all rows
    rows = table.find_all("tr")

    if len(rows) < 10:
        raise ValueError(f"Too few rows ({len(rows)}) for a Financial Highlights table")

    # Result structure
    result = {
        "operating": {},
        "distribution": {},
        "ratios": {},
        "fiscal_year_end": None,
        "math_validated": False,
    }

    # TODO: Implement positional extraction
    # This is a placeholder - needs to be implemented with real logic

    return result


def _process_cik_finhigh(session: Session, cik: str) -> bool:
    """Process N-CSR filings for Financial Highlights data for a single CIK.

    Iterates through multiple recent filings to cover all fund series
    under this CIK.

    Args:
        session: SQLAlchemy session
        cik: CIK string (zero-padded to 10 digits)

    Returns:
        True if successful, False otherwise
    """
    MAX_FILINGS = 10

    try:
        # Build class_id -> ETF mapping from database first
        stmt = select(ETF).where(ETF.cik == cik)
        etfs = session.execute(stmt).scalars().all()

        class_id_to_etf = {}
        for etf in etfs:
            if etf.class_id:
                class_id_to_etf[etf.class_id] = etf

        if not class_id_to_etf:
            logger.warning(f"CIK {cik}: No ETFs with class_id found in database")
            return True

        needed_class_ids = set(class_id_to_etf.keys())
        # Track (class_id, fiscal_year_end) pairs already processed
        satisfied = set()

        company = Company(cik)
        filings = company.get_filings(form="N-CSR")

        if not filings or (hasattr(filings, "empty") and filings.empty):
            logger.info(f"CIK {cik}: No N-CSR filings found")
            return True

        processed_etfs = 0
        skipped_etfs = 0

        num_filings = min(len(filings), MAX_FILINGS)
        for filing_idx in range(num_filings):
            # Stop early if all class_ids have been satisfied
            if not (needed_class_ids - {cid for cid, _ in satisfied}):
                logger.debug(
                    f"CIK {cik}: All class_ids satisfied after {filing_idx} filing(s)"
                )
                break

            filing = filings[filing_idx]

            # Get HTML from filing
            try:
                html = filing.html()
                if not html:
                    logger.warning(
                        f"CIK {cik}: Filing {filing_idx} has no HTML, skipping"
                    )
                    continue
            except Exception as e:
                logger.warning(
                    f"CIK {cik}: Filing {filing_idx} HTML fetch failed: {e}"
                )
                continue

            # TODO: Parse HTML to find Financial Highlights sections
            # TODO: Match sections to ETFs via fund name or class_id
            # TODO: Extract data and upsert to database

            logger.debug(
                f"CIK {cik}: Filing {filing_idx} - HTML parsing not yet implemented"
            )

        session.commit()
        logger.info(f"CIK {cik}: Processed {processed_etfs} ETF(s), skipped {skipped_etfs}")
        return True

    except Exception as e:
        logger.error(f"CIK {cik}: Error processing Financial Highlights: {e}")
        session.rollback()
        return False


def parse_finhigh(
    cik: Optional[str] = None,
    ciks: Optional[list[str]] = None,
    limit: Optional[int] = None,
    clear_cache: bool = True,
) -> None:
    """Parse Financial Highlights from N-CSR filings.

    Args:
        cik: Optional CIK to process (all others will be skipped)
        ciks: Optional list of CIKs to process (overrides cik param)
        limit: Optional limit on number of CIKs to process
        clear_cache: Whether to clear edgartools HTTP cache after processing
    """
    engine = get_engine()
    session_factory = sessionmaker(bind=engine)

    # Determine which CIKs to process
    with session_factory() as session:
        if ciks is not None:
            cik_list = ciks
        elif cik is not None:
            cik_padded = f"{int(cik):010d}"
            cik_list = [cik_padded]
            logger.info(f"Processing single CIK: {cik_padded}")
        else:
            # Get all distinct CIKs from ETF table
            stmt = select(ETF.cik).distinct().order_by(ETF.cik)
            cik_list = [row[0] for row in session.execute(stmt).all()]

            if not cik_list:
                logger.warning("No CIKs found in ETF table. Run 'load-etfs' first.")
                print("No CIKs found in ETF table. Run 'load-etfs' first.")
                return

        if limit is not None:
            cik_list = cik_list[:limit]
            logger.info(f"Limiting to first {limit} CIKs")

    succeeded = 0
    failed = 0

    for cik_str in cik_list:
        with session_factory() as session:
            if _process_cik_finhigh(session, cik_str):
                succeeded += 1
            else:
                failed += 1

    print(f"\nSummary: {succeeded} CIKs succeeded, {failed} CIKs failed")
    logger.info(f"Summary: {succeeded} CIKs succeeded, {failed} CIKs failed")

    if clear_cache:
        result = edgar_clear_cache(dry_run=False)
        files_deleted = result.get("files_deleted", 0)
        bytes_freed = result.get("bytes_freed", 0)
        mb_freed = bytes_freed / (1024 * 1024)
        logger.info(f"Cache cleared: {files_deleted} files deleted, {mb_freed:.2f} MB freed")
        print(f"Cache cleared: {files_deleted} files deleted, {mb_freed:.2f} MB freed")
