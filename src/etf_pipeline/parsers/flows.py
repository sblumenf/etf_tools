"""Parse 24F-2NT filings for trust-level flow data."""

import logging
import xml.etree.ElementTree as ET
from datetime import date
from typing import Optional

from edgar import Company
from sqlalchemy.orm import Session, sessionmaker

from etf_pipeline.db import get_engine
from etf_pipeline.models import FlowData
from etf_pipeline.parser_utils import (
    build_filing_date_filter,
    clear_and_log_cache,
    ensure_date,
    parse_date,
    parse_decimal,
    resolve_cik_list,
    run_parser_loop,
    update_processing_log,
    upsert_record,
)

logger = logging.getLogger(__name__)

# XML namespace for 24F-2NT filings
NS = {"f2": "http://www.sec.gov/edgar/twentyfourf2filer"}


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
    except (ET.ParseError, TypeError, ValueError) as e:
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

    fiscal_year_end = parse_date(fiscal_year_elem.text)
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

    sales_value = parse_decimal(sales_elem.text if sales_elem is not None else None)
    redemptions_value = parse_decimal(redemptions_elem.text if redemptions_elem is not None else None)
    net_sales = parse_decimal(net_sales_elem.text if net_sales_elem is not None else None)

    return {
        "fiscal_year_end": fiscal_year_end,
        "sales_value": sales_value,
        "redemptions_value": redemptions_value,
        "net_sales": net_sales,
    }


def _process_single_filing(session: Session, cik: str, filing) -> bool:
    """Process a single 24F-2NT filing for a CIK. Returns True on success."""
    filing_date = ensure_date(filing.filing_date)

    xml_content = filing.xml()
    if xml_content is None:
        logger.warning(f"CIK {cik}: Filing has no XML content")
        return False

    flow_data = _extract_flow_data_from_xml(xml_content, cik)
    if flow_data is None:
        return False

    upsert_record(
        session,
        FlowData,
        filter_kwargs={"cik": cik, "fiscal_year_end": flow_data["fiscal_year_end"], "filing_date": filing_date},
        data_kwargs={
            "sales_value": flow_data["sales_value"],
            "redemptions_value": flow_data["redemptions_value"],
            "net_sales": flow_data["net_sales"],
        },
    )
    logger.info(f"CIK {cik}: Upserted flow data for fiscal year {flow_data['fiscal_year_end']}, filing_date {filing_date}")
    update_processing_log(session, cik, "flows", filing_date)
    session.commit()
    return True


def _make_process_cik_flows(from_date: Optional[str] = None, to_date: Optional[str] = None):
    """Return a per-CIK processor for the parser loop."""
    date_filter = build_filing_date_filter(from_date, to_date)
    backfill_mode = date_filter is not None

    def _process_cik_flows(session: Session, cik: str) -> bool:
        try:
            company = Company(cik)
            kwargs = {"form": "24F-2NT"}
            if date_filter is not None:
                kwargs["filing_date"] = date_filter
            filings = company.get_filings(**kwargs)

            if not filings or (hasattr(filings, 'empty') and filings.empty):
                logger.info(f"CIK {cik}: No 24F-2NT filings found")
                return True

            if backfill_mode:
                total = len(filings)
                success = True
                for i, filing in enumerate(filings):
                    ok = _process_single_filing(session, cik, filing)
                    if not ok:
                        success = False
                    logger.info(f"CIK {cik}: Processed {i + 1}/{total} filings")
                return success
            else:
                return _process_single_filing(session, cik, filings[0])

        except Exception as e:
            logger.error(f"CIK {cik}: Error processing filing: {e}")
            session.rollback()
            return False

    return _process_cik_flows


def parse_flows(
    cik: Optional[str] = None,
    ciks: Optional[list[str]] = None,
    limit: Optional[int] = None,
    clear_cache: bool = True,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> None:
    """Parse 24F-2NT filings for trust-level flow data.

    Args:
        cik: Optional CIK to process (all others will be skipped)
        ciks: Optional list of CIKs to process (overrides cik param)
        limit: Optional limit on number of CIKs to process
        clear_cache: Whether to clear edgartools HTTP cache after processing
        from_date: Optional start date for backfill (YYYY-MM-DD). Requires to_date.
        to_date: Optional end date for backfill (YYYY-MM-DD). Requires from_date.
    """
    engine = get_engine()
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        cik_list = resolve_cik_list(session, cik, ciks, limit)

    if not cik_list:
        return

    process_fn = _make_process_cik_flows(from_date, to_date)
    run_parser_loop(cik_list, session_factory, process_fn, "flows")

    if clear_cache:
        clear_and_log_cache()
