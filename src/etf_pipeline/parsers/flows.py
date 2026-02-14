"""Parse 24F-2NT filings for trust-level flow data."""

import logging
import xml.etree.ElementTree as ET
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from edgar import Company
from edgar.storage_management import clear_cache as edgar_clear_cache
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session, sessionmaker

from etf_pipeline.db import get_engine
from etf_pipeline.models import ETF, FlowData, ProcessingLog

logger = logging.getLogger(__name__)

# XML namespace for 24F-2NT filings
NS = {"f2": "http://www.sec.gov/edgar/twentyfourf2filer"}


def _parse_money(val: Optional[str]) -> Optional[Decimal]:
    """Parse money string handling commas and accounting negatives.

    Examples:
        "1,234.56" -> Decimal("1234.56")
        "(20.00)" -> Decimal("-20.00")
        None -> None

    Args:
        val: Money string from XML

    Returns:
        Decimal value or None if parsing fails
    """
    if not val:
        return None

    val = val.strip()
    if not val:
        return None

    # Handle accounting notation for negatives: (20.00) -> -20.00
    is_negative = val.startswith("(") and val.endswith(")")
    if is_negative:
        val = val[1:-1]  # Strip parens

    # Remove commas
    val = val.replace(",", "")

    try:
        result = Decimal(val)
        return -result if is_negative else result
    except (InvalidOperation, ValueError) as e:
        logger.warning(f"Failed to parse money value '{val}': {e}")
        return None


def _parse_date(date_str: Optional[str]) -> Optional[date]:
    """Parse MM/DD/YYYY date string.

    Args:
        date_str: Date string from XML (format: MM/DD/YYYY)

    Returns:
        date object or None if parsing fails
    """
    if not date_str:
        return None

    try:
        return datetime.strptime(date_str.strip(), "%m/%d/%Y").date()
    except ValueError as e:
        logger.warning(f"Failed to parse date '{date_str}': {e}")
        return None


def _extract_flow_data_from_xml(xml_content: str, cik: str) -> Optional[dict]:
    """Extract flow data from 24F-2NT XML.

    Args:
        xml_content: Raw XML string from filing
        cik: CIK of the filing entity (for logging)

    Returns:
        Dictionary with keys: fiscal_year_end, sales_value, redemptions_value, net_sales
        Returns None if extraction fails
    """
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as e:
        logger.warning(f"CIK {cik}: Failed to parse XML: {e}")
        return None

    # Navigate to annualFilingInfo (use first one if multiple exist)
    annual_filings = root.findall(".//f2:annualFilings/f2:annualFilingInfo", NS)
    if not annual_filings:
        logger.warning(f"CIK {cik}: No annualFilingInfo found in XML")
        return None

    # Use the first annualFilingInfo
    annual_filing = annual_filings[0]

    # Extract item4 (fiscal year end)
    item4 = annual_filing.find("f2:item4", NS)
    if item4 is None:
        logger.warning(f"CIK {cik}: item4 not found")
        return None

    fiscal_year_elem = item4.find("f2:lastDayOfFiscalYear", NS)
    if fiscal_year_elem is None or not fiscal_year_elem.text:
        logger.warning(f"CIK {cik}: lastDayOfFiscalYear not found")
        return None

    fiscal_year_end = _parse_date(fiscal_year_elem.text)
    if fiscal_year_end is None:
        return None

    # Extract item5 (flow data)
    item5 = annual_filing.find("f2:item5", NS)
    if item5 is None:
        logger.warning(f"CIK {cik}: item5 not found")
        return None

    sales_elem = item5.find("f2:aggregateSalePriceOfSecuritiesSold", NS)
    redemptions_elem = item5.find("f2:aggregatePriceOfSecuritiesRedeemedOrRepurchasedInFiscalYear", NS)
    net_sales_elem = item5.find("f2:netSales", NS)

    sales_value = _parse_money(sales_elem.text if sales_elem is not None else None)
    redemptions_value = _parse_money(redemptions_elem.text if redemptions_elem is not None else None)
    net_sales = _parse_money(net_sales_elem.text if net_sales_elem is not None else None)

    return {
        "fiscal_year_end": fiscal_year_end,
        "sales_value": sales_value,
        "redemptions_value": redemptions_value,
        "net_sales": net_sales,
    }


def _process_cik_flows(session: Session, cik: str) -> bool:
    """Process 24F-2NT filing for a single CIK.

    Args:
        session: SQLAlchemy session
        cik: CIK string (zero-padded to 10 digits)

    Returns:
        True if successful, False otherwise
    """
    try:
        company = Company(cik)
        filings = company.get_filings(form="24F-2NT")

        if not filings or (hasattr(filings, 'empty') and filings.empty):
            logger.info(f"CIK {cik}: No 24F-2NT filings found")
            return True  # Not an error, just no data

        # Get the latest filing
        filing = filings[0]
        raw_filing_date = filing.filing_date if hasattr(filing, 'filing_date') else date.today()
        # Convert to date if it's a datetime
        if isinstance(raw_filing_date, datetime):
            filing_date = raw_filing_date.date()
        elif isinstance(raw_filing_date, date):
            filing_date = raw_filing_date
        else:
            filing_date = date.today()

        # Get XML content
        xml_content = filing.xml()
        if xml_content is None:
            logger.warning(f"CIK {cik}: Filing has no XML content")
            return False

        # Extract flow data
        flow_data = _extract_flow_data_from_xml(xml_content, cik)
        if flow_data is None:
            return False

        # Upsert into database
        stmt = select(FlowData).where(
            FlowData.cik == cik,
            FlowData.fiscal_year_end == flow_data["fiscal_year_end"],
            FlowData.filing_date == filing_date
        )
        existing = session.execute(stmt).scalar_one_or_none()

        if existing:
            # Update existing record
            existing.sales_value = flow_data["sales_value"]
            existing.redemptions_value = flow_data["redemptions_value"]
            existing.net_sales = flow_data["net_sales"]
            logger.info(f"CIK {cik}: Updated flow data for fiscal year {flow_data['fiscal_year_end']}, filing_date {filing_date}")
        else:
            # Insert new record
            new_flow = FlowData(
                cik=cik,
                fiscal_year_end=flow_data["fiscal_year_end"],
                filing_date=filing_date,
                sales_value=flow_data["sales_value"],
                redemptions_value=flow_data["redemptions_value"],
                net_sales=flow_data["net_sales"],
            )
            session.add(new_flow)
            logger.info(f"CIK {cik}: Inserted flow data for fiscal year {flow_data['fiscal_year_end']}, filing_date {filing_date}")

        # Update processing log after successful processing
        stmt = insert(ProcessingLog).values(
            cik=cik,
            parser_type="flows",
            last_run_at=datetime.now(),
            latest_filing_date_seen=filing_date,
        ).on_conflict_do_update(
            index_elements=["cik", "parser_type"],
            set_={
                "last_run_at": datetime.now(),
                "latest_filing_date_seen": filing_date,
            },
        )
        session.execute(stmt)

        session.commit()
        return True

    except Exception as e:
        logger.error(f"CIK {cik}: Error processing filing: {e}")
        session.rollback()
        return False


def parse_flows(
    cik: Optional[str] = None,
    ciks: Optional[list[str]] = None,
    limit: Optional[int] = None,
    clear_cache: bool = True,
) -> None:
    """Parse 24F-2NT filings for trust-level flow data.

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
            # Use provided list of CIKs (already padded)
            cik_list = ciks
        elif cik is not None:
            # Single CIK provided
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
            if _process_cik_flows(session, cik_str):
                succeeded += 1
            else:
                failed += 1

    print(f"\nSummary: {succeeded} CIKs succeeded, {failed} CIKs failed")
    logger.info(f"Summary: {succeeded} CIKs succeeded, {failed} CIKs failed")

    if clear_cache:
        result = edgar_clear_cache(dry_run=False)
        files_deleted = result.get('files_deleted', 0)
        bytes_freed = result.get('bytes_freed', 0)
        mb_freed = bytes_freed / (1024 * 1024)
        logger.info(f"Cache cleared: {files_deleted} files deleted, {mb_freed:.2f} MB freed")
        print(f"Cache cleared: {files_deleted} files deleted, {mb_freed:.2f} MB freed")
