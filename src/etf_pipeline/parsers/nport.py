"""Parse NPORT-P filings for holdings and derivatives data."""

import logging
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from edgar import Company
from edgar.funds.reports import FundReport
from edgar.storage_management import clear_cache as edgar_clear_cache
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, sessionmaker

from etf_pipeline.db import get_engine
from etf_pipeline.models import (
    CreditSpreadRisk,
    DebtSecurityDetail,
    Derivative,
    DerivativeForward,
    DerivativeOption,
    DerivativeSwap,
    DerivativeSwapLeg,
    ETF,
    FundSnapshot,
    Holding,
    InterestRateRisk,
    NPORTMonthlyFlow,
    NPORTMonthlyReturn,
    SecurityLending,
)
from etf_pipeline.parser_utils import ensure_date, update_processing_log
from etf_pipeline.parsers.nport_xml import parse_nport_investments_xml

logger = logging.getLogger(__name__)


def _clean_str(val):
    """Return None if val is None, 'N/A', or Mock object, else str(val)."""
    if val is None:
        return None
    # Check if it's a Mock object (check for _mock_name attribute)
    if hasattr(val, '_mock_name'):
        return None
    val_str = str(val).strip()
    if val_str == "N/A":
        return None
    return val_str if val_str else None


def _safe_numeric(val):
    """Return None if val is None or Mock object, otherwise return val as-is."""
    if val is None:
        return None
    # Check if it's a Mock object
    if hasattr(val, '_mock_name'):
        return None
    return val


def parse_nport(
    cik: Optional[str] = None,
    ciks: Optional[list[str]] = None,
    limit: Optional[int] = None,
    clear_cache: bool = True,
) -> None:
    """Parse NPORT-P filings for all ETFs and extract holdings and derivatives.

    Args:
        cik: Optional CIK to process (all others will be skipped)
        ciks: Optional list of CIKs to process (overrides cik parameter)
        limit: Optional limit on number of CIKs to process (alphabetical order)
        clear_cache: Whether to clear edgartools HTTP cache after processing
    """
    engine = get_engine()
    session_factory = sessionmaker(bind=engine)

    with session_factory() as session:
        stmt = select(ETF).order_by(ETF.cik)
        etfs = session.execute(stmt).scalars().all()

        if not etfs:
            logger.warning("No ETFs found in database. Run 'load-etfs' first.")
            return

        by_cik = defaultdict(list)
        for etf in etfs:
            by_cik[etf.cik].append(etf)

        ciks_to_process = sorted(by_cik.keys())

        # ciks parameter takes precedence over cik
        if ciks is not None:
            ciks_padded = [f"{int(c):010d}" for c in ciks]
            valid_ciks = [c for c in ciks_padded if c in ciks_to_process]
            if not valid_ciks:
                logger.warning(f"None of the provided CIKs found in database: {ciks}")
                return
            ciks_to_process = valid_ciks
            logger.info(f"Processing {len(valid_ciks)} CIK(s) from ciks parameter")
        elif cik is not None:
            cik_padded = f"{int(cik):010d}"
            if cik_padded in ciks_to_process:
                ciks_to_process = [cik_padded]
                logger.info(f"Processing single CIK: {cik}")
            else:
                logger.warning(f"CIK {cik} not found in database")
                return

        if limit is not None and ciks is None:
            ciks_to_process = ciks_to_process[:limit]
            logger.info(f"Limiting to first {limit} CIKs")

    succeeded = 0
    failed = 0

    for cik_str in ciks_to_process:
        try:
            _process_cik(session_factory, cik_str, len(by_cik[cik_str]))
            succeeded += 1
        except Exception as e:
            failed += 1
            logger.error(f"Failed to process CIK {cik_str}: {e}", exc_info=True)

    logger.info(f"Summary: {succeeded} CIKs succeeded, {failed} CIKs failed")

    if clear_cache:
        result = edgar_clear_cache(dry_run=False)
        files_deleted = result.get('files_deleted', 0)
        bytes_freed = result.get('bytes_freed', 0)
        mb_freed = bytes_freed / (1024 * 1024)
        logger.info(f"Cache cleared: {files_deleted} files deleted, {mb_freed:.2f} MB freed")


def _get_latest_filings_per_series(filings):
    """Get latest filings grouped by series_id.

    Args:
        filings: EntityFilings collection from edgartools

    Returns:
        dict: Mapping of series_id -> (filing, fund_report, report_date, filing_date)
    """
    if not filings or (hasattr(filings, 'empty') and filings.empty):
        return {}

    # Group filings by filing_date
    by_date = defaultdict(list)
    for filing in filings:
        by_date[filing.filing_date].append(filing)

    if not by_date:
        return {}

    # Get the most recent filing date
    latest_date = max(by_date.keys())
    latest_filings = sorted(by_date[latest_date], key=lambda f: f.accession_number)

    # Parse each filing and extract series_id
    series_map = {}
    for filing in latest_filings:
        try:
            fund_report = FundReport.from_filing(filing)
            series_id = fund_report.general_info.series_id

            if not series_id:
                logger.warning(f"Filing has no series_id, skipping (filing_date={filing.filing_date})")
                continue

            report_date = fund_report.reporting_period
            if isinstance(report_date, str):
                report_date = datetime.strptime(report_date, "%Y-%m-%d").date()

            filing_date = ensure_date(filing.filing_date)
            series_map[series_id] = (filing, fund_report, report_date, filing_date)

        except Exception as e:
            logger.warning(f"Failed to parse filing: {e} (filing_date={filing.filing_date})")
            continue

    return series_map


def _process_cik(session_factory: sessionmaker, cik: str, etf_count: int) -> None:
    """Process a single CIK: fetch NPORT-P filings and extract holdings and derivatives by series_id."""
    logger.info(f"Processing CIK {cik}: {etf_count} ETF(s)")

    company = Company(cik)
    filings = company.get_filings(form="NPORT-P")

    if not filings or (hasattr(filings, 'empty') and filings.empty):
        logger.warning(f"CIK {cik}: No NPORT-P filings found")
        return

    logger.info(f"CIK {cik}: Found {len(filings)} NPORT-P filing(s)")

    # Get latest filings grouped by series_id
    series_map = _get_latest_filings_per_series(filings)

    if not series_map:
        logger.warning(f"CIK {cik}: No valid series found in filings")
        return

    logger.info(f"CIK {cik}: Parsed {len(series_map)} series from latest filings")

    # Track the latest filing date seen across all filings processed
    latest_filing_date = max(filing_date for _, _, _, filing_date in series_map.values()) if series_map else None

    with session_factory() as session:
        stmt = select(ETF).where(ETF.cik == cik)
        etfs = session.execute(stmt).scalars().all()

        # Collect etf_ids and report_dates that need checking
        etf_report_pairs = []
        for etf in etfs:
            if etf.series_id in series_map:
                _, _, report_date, _ = series_map[etf.series_id]
                etf_report_pairs.append((etf.id, report_date))

        # Batch query: find ETFs that already have holdings for their report_date
        existing_etf_ids = set()
        if etf_report_pairs:
            conditions = [
                and_(Holding.etf_id == eid, Holding.report_date == rd)
                for eid, rd in etf_report_pairs
            ]
            stmt_existing = select(Holding.etf_id).where(or_(*conditions)).distinct()
            existing_etf_ids = set(session.execute(stmt_existing).scalars().all())

        processed = 0
        for etf in etfs:
            if etf.series_id not in series_map:
                logger.warning(f"ETF {etf.ticker} (series_id={etf.series_id}): No matching NPORT-P filing found")
                continue
            if etf.id in existing_etf_ids:
                logger.info(f"ETF {etf.ticker}: Holdings already exist, skipping")
                continue
            filing, fund_report, report_date, filing_date = series_map[etf.series_id]
            _process_etf(session, etf, filing, fund_report, report_date, filing_date)
            processed += 1

        # Update processing log after successful processing
        if latest_filing_date is not None:
            latest_filing_date = ensure_date(latest_filing_date)
            update_processing_log(session, cik, "nport", latest_filing_date)

        session.commit()

    logger.info(f"CIK {cik}: Processed {processed}/{etf_count} ETF(s)")


def _extract_fund_snapshot(
    session: Session, cik: str, fund_report: FundReport, report_date, filing_date
) -> None:
    """Extract and insert fund-level balance sheet snapshot from FundReport."""
    # Check if snapshot already exists
    stmt = select(FundSnapshot).where(
        FundSnapshot.cik == cik,
        FundSnapshot.report_date == report_date,
        FundSnapshot.filing_date == filing_date,
    )
    existing = session.execute(stmt).scalar_one_or_none()
    if existing:
        logger.debug(f"Fund snapshot already exists for CIK {cik} on {report_date}")
        return

    # Extract fund_info data
    try:
        fund_info = fund_report.fund_info
    except AttributeError:
        logger.warning(f"No fund_info found in FundReport for CIK {cik}")
        return

    total_assets = None
    total_liabilities = None
    net_assets = None
    cash_not_reported = None
    assets_invested = None
    assets_misc_sec = None
    amt_pay_one_yr_banks_borr = None
    amt_pay_one_yr_ctrld_comp = None
    amt_pay_one_yr_oth_affil = None
    amt_pay_one_yr_other = None
    amt_pay_aft_one_yr_banks_borr = None
    amt_pay_aft_one_yr_ctrld_comp = None
    amt_pay_aft_one_yr_oth_affil = None
    amt_pay_aft_one_yr_other = None
    delay_deliv = None
    stand_by_commit = None
    liquidity_pref = None
    is_non_cash_collateral = False

    try:
        total_assets = fund_info.total_assets
    except AttributeError:
        pass

    try:
        total_liabilities = fund_info.total_liabilities
    except AttributeError:
        pass

    try:
        net_assets = fund_info.net_assets
    except AttributeError:
        pass

    try:
        cash_not_reported = fund_info.cash_not_reported
    except AttributeError:
        pass

    try:
        assets_invested = fund_info.assets_invested
    except AttributeError:
        pass

    try:
        assets_misc_sec = fund_info.assets_misc_sec
    except AttributeError:
        pass

    try:
        amt_pay_one_yr_banks_borr = fund_info.amt_pay_one_yr_banks_borr
    except AttributeError:
        pass

    try:
        amt_pay_one_yr_ctrld_comp = fund_info.amt_pay_one_yr_ctrld_comp
    except AttributeError:
        pass

    try:
        amt_pay_one_yr_oth_affil = fund_info.amt_pay_one_yr_oth_affil
    except AttributeError:
        pass

    try:
        amt_pay_one_yr_other = fund_info.amt_pay_one_yr_other
    except AttributeError:
        pass

    try:
        amt_pay_aft_one_yr_banks_borr = fund_info.amt_pay_aft_one_yr_banks_borr
    except AttributeError:
        pass

    try:
        amt_pay_aft_one_yr_ctrld_comp = fund_info.amt_pay_aft_one_yr_ctrld_comp
    except AttributeError:
        pass

    try:
        amt_pay_aft_one_yr_oth_affil = fund_info.amt_pay_aft_one_yr_oth_affil
    except AttributeError:
        pass

    try:
        amt_pay_aft_one_yr_other = fund_info.amt_pay_aft_one_yr_other
    except AttributeError:
        pass

    try:
        delay_deliv = fund_info.delay_deliv
    except AttributeError:
        pass

    try:
        stand_by_commit = fund_info.stand_by_commit
    except AttributeError:
        pass

    try:
        liquidity_pref = fund_info.liquidity_pref
    except AttributeError:
        pass

    try:
        is_non_cash_collateral_val = fund_info.is_non_cash_collateral
        if is_non_cash_collateral_val is not None:
            is_non_cash_collateral = bool(is_non_cash_collateral_val)
    except AttributeError:
        pass

    snapshot = FundSnapshot(
        cik=cik,
        report_date=report_date,
        filing_date=filing_date,
        total_assets=total_assets,
        total_liabilities=total_liabilities,
        net_assets=net_assets,
        cash_not_reported=cash_not_reported,
        assets_invested=assets_invested,
        assets_misc_sec=assets_misc_sec,
        amt_pay_one_yr_banks_borr=amt_pay_one_yr_banks_borr,
        amt_pay_one_yr_ctrld_comp=amt_pay_one_yr_ctrld_comp,
        amt_pay_one_yr_oth_affil=amt_pay_one_yr_oth_affil,
        amt_pay_one_yr_other=amt_pay_one_yr_other,
        amt_pay_aft_one_yr_banks_borr=amt_pay_aft_one_yr_banks_borr,
        amt_pay_aft_one_yr_ctrld_comp=amt_pay_aft_one_yr_ctrld_comp,
        amt_pay_aft_one_yr_oth_affil=amt_pay_aft_one_yr_oth_affil,
        amt_pay_aft_one_yr_other=amt_pay_aft_one_yr_other,
        delay_deliv=delay_deliv,
        stand_by_commit=stand_by_commit,
        liquidity_pref=liquidity_pref,
        is_non_cash_collateral=is_non_cash_collateral,
    )
    session.add(snapshot)
    logger.info(f"Created fund snapshot for CIK {cik} on {report_date}")


def _extract_monthly_returns(filing, etf_id: int, report_date, filing_date) -> list[NPORTMonthlyReturn]:
    """Extract monthly return data from NPORT-P filing XML.

    Args:
        filing: Filing object from edgartools
        etf_id: ETF ID to associate returns with
        report_date: Report date for the filing
        filing_date: Filing date

    Returns:
        List of NPORTMonthlyReturn objects
    """
    monthly_returns = []

    try:
        # Get raw XML content from filing
        xml_content = filing.xml()
        if not xml_content:
            logger.debug(f"No XML content found in filing for etf_id={etf_id}")
            return monthly_returns

        # Parse XML
        root = ET.fromstring(xml_content)

        # Find monthlyTotReturns element
        # Path: /edgarSubmission/formData/fundInfo/returnInfo/monthlyTotReturns
        ns = {'nport': 'http://www.sec.gov/edgar/nport'}

        # Find with namespace
        monthly_tot_returns = root.find('.//nport:monthlyTotReturns', ns)

        if monthly_tot_returns is None:
            logger.debug(f"No monthlyTotReturns element found in NPORT XML for etf_id={etf_id}")
            return monthly_returns

        # Extract each monthlyTotReturn child element
        for monthly_return_elem in monthly_tot_returns.findall('nport:monthlyTotReturn', ns):
            # Extract attributes
            rtn1 = monthly_return_elem.get('rtn1')
            rtn2 = monthly_return_elem.get('rtn2')
            rtn3 = monthly_return_elem.get('rtn3')
            class_id = monthly_return_elem.get('classId')

            # Convert "N/A" to None, otherwise convert to Decimal
            def parse_return(val):
                if val is None or val.strip().upper() == "N/A":
                    return None
                try:
                    return Decimal(val)
                except (ValueError, Exception) as e:
                    logger.warning(f"Could not parse return value '{val}': {e}")
                    return None

            month_1 = parse_return(rtn1)
            month_2 = parse_return(rtn2)
            month_3 = parse_return(rtn3)

            # Create NPORTMonthlyReturn object
            monthly_return = NPORTMonthlyReturn(
                etf_id=etf_id,
                report_date=report_date,
                filing_date=filing_date,
                class_id=class_id if class_id else None,
                month_1_return=month_1,
                month_2_return=month_2,
                month_3_return=month_3,
            )
            monthly_returns.append(monthly_return)

        if monthly_returns:
            logger.info(f"Extracted {len(monthly_returns)} monthly return entries for etf_id={etf_id}")

    except Exception as e:
        logger.warning(f"Failed to extract monthly returns for etf_id={etf_id}: {e}")

    return monthly_returns


def _extract_monthly_flows(filing, etf_id: int, report_date, filing_date) -> list[NPORTMonthlyFlow]:
    """Extract monthly flow data from NPORT-P filing XML.

    Args:
        filing: Filing object from edgartools
        etf_id: ETF ID to associate flows with
        report_date: Report date for the filing
        filing_date: Filing date

    Returns:
        List of NPORTMonthlyFlow objects
    """
    monthly_flows = []

    try:
        # Get raw XML content from filing
        xml_content = filing.xml()
        if not xml_content:
            logger.debug(f"No XML content found in filing for etf_id={etf_id}")
            return monthly_flows

        # Parse XML
        root = ET.fromstring(xml_content)

        # Find fundInfo element which contains monthly flow data
        # Path: /edgarSubmission/formData/fundInfo
        ns = {'nport': 'http://www.sec.gov/edgar/nport'}

        # Find fundInfo element
        fund_info = root.find('.//nport:fundInfo', ns)

        if fund_info is None:
            logger.debug(f"No fundInfo element found in NPORT XML for etf_id={etf_id}")
            return monthly_flows

        # Extract flow data from three separate elements: mon1Flow, mon2Flow, mon3Flow
        mon1_flow = fund_info.find('nport:mon1Flow', ns)
        mon2_flow = fund_info.find('nport:mon2Flow', ns)
        mon3_flow = fund_info.find('nport:mon3Flow', ns)

        # If no flow elements found, return empty list
        if mon1_flow is None and mon2_flow is None and mon3_flow is None:
            logger.debug(f"No monthly flow elements found in NPORT XML for etf_id={etf_id}")
            return monthly_flows

        # Convert "N/A" to None, otherwise convert to Decimal
        def parse_flow(val):
            if val is None or val.strip().upper() == "N/A":
                return None
            try:
                return Decimal(val)
            except (ValueError, Exception) as e:
                logger.warning(f"Could not parse flow value '{val}': {e}")
                return None

        # Extract flow data from attributes
        month_1_sales = parse_flow(mon1_flow.get('sales')) if mon1_flow is not None else None
        month_1_redemptions = parse_flow(mon1_flow.get('redemption')) if mon1_flow is not None else None
        month_1_reinvestments = parse_flow(mon1_flow.get('reinvestment')) if mon1_flow is not None else None

        month_2_sales = parse_flow(mon2_flow.get('sales')) if mon2_flow is not None else None
        month_2_redemptions = parse_flow(mon2_flow.get('redemption')) if mon2_flow is not None else None
        month_2_reinvestments = parse_flow(mon2_flow.get('reinvestment')) if mon2_flow is not None else None

        month_3_sales = parse_flow(mon3_flow.get('sales')) if mon3_flow is not None else None
        month_3_redemptions = parse_flow(mon3_flow.get('redemption')) if mon3_flow is not None else None
        month_3_reinvestments = parse_flow(mon3_flow.get('reinvestment')) if mon3_flow is not None else None

        # Create single NPORTMonthlyFlow object with data from all three months
        # Monthly flows are fund-level per NPORT XSD (mon1Flow/mon2Flow/mon3Flow), not class-level
        monthly_flow = NPORTMonthlyFlow(
            etf_id=etf_id,
            report_date=report_date,
            filing_date=filing_date,
            class_id=None,
            month_1_sales=month_1_sales,
            month_1_redemptions=month_1_redemptions,
            month_1_reinvestments=month_1_reinvestments,
            month_2_sales=month_2_sales,
            month_2_redemptions=month_2_redemptions,
            month_2_reinvestments=month_2_reinvestments,
            month_3_sales=month_3_sales,
            month_3_redemptions=month_3_redemptions,
            month_3_reinvestments=month_3_reinvestments,
        )
        monthly_flows.append(monthly_flow)

        if monthly_flows:
            logger.info(f"Extracted {len(monthly_flows)} monthly flow entry for etf_id={etf_id}")

    except Exception as e:
        logger.warning(f"Failed to extract monthly flows for etf_id={etf_id}: {e}")

    return monthly_flows


def _extract_interest_rate_risk(filing, etf_id: int, report_date, filing_date) -> list[InterestRateRisk]:
    """Extract interest rate risk data from NPORT-P filing XML.

    Args:
        filing: Filing object from edgartools
        etf_id: ETF ID to associate interest rate risk data with
        report_date: Report date for the filing
        filing_date: Filing date

    Returns:
        List of InterestRateRisk objects
    """
    interest_rate_risks = []

    try:
        # Get raw XML content from filing
        xml_content = filing.xml()
        if not xml_content:
            logger.debug(f"No XML content found in filing for etf_id={etf_id}")
            return interest_rate_risks

        # Parse XML
        root = ET.fromstring(xml_content)

        # Find curMetrics element
        # Path: /edgarSubmission/formData/fundinfo/curMetrics
        ns = {'nport': 'http://www.sec.gov/edgar/nport'}

        cur_metrics = root.find('.//nport:curMetrics', ns)

        if cur_metrics is None:
            logger.debug(f"No curMetrics element found in NPORT XML for etf_id={etf_id}")
            return interest_rate_risks

        # Extract each curMetric child element
        for cur_metric_elem in cur_metrics.findall('nport:curMetric', ns):
            # Extract currency code
            cur_cd_elem = cur_metric_elem.find('nport:curCd', ns)
            if cur_cd_elem is None or not cur_cd_elem.text:
                logger.warning(f"curMetric missing currency code for etf_id={etf_id}, skipping")
                continue

            currency_code = cur_cd_elem.text.strip()

            # Extract DV01 risk metrics
            dv01_elem = cur_metric_elem.find('nport:intrstRtRiskdv01', ns)
            dv01_3m = None
            dv01_1y = None
            dv01_5y = None
            dv01_10y = None
            dv01_30y = None

            if dv01_elem is not None:
                dv01_3m = _parse_decimal(dv01_elem.get('period3Mon'))
                dv01_1y = _parse_decimal(dv01_elem.get('period1Yr'))
                dv01_5y = _parse_decimal(dv01_elem.get('period5Yr'))
                dv01_10y = _parse_decimal(dv01_elem.get('period10Yr'))
                dv01_30y = _parse_decimal(dv01_elem.get('period30Yr'))

            # Extract DV100 risk metrics
            dv100_elem = cur_metric_elem.find('nport:intrstRtRiskdv100', ns)
            dv100_3m = None
            dv100_1y = None
            dv100_5y = None
            dv100_10y = None
            dv100_30y = None

            if dv100_elem is not None:
                dv100_3m = _parse_decimal(dv100_elem.get('period3Mon'))
                dv100_1y = _parse_decimal(dv100_elem.get('period1Yr'))
                dv100_5y = _parse_decimal(dv100_elem.get('period5Yr'))
                dv100_10y = _parse_decimal(dv100_elem.get('period10Yr'))
                dv100_30y = _parse_decimal(dv100_elem.get('period30Yr'))

            # Create InterestRateRisk object
            interest_rate_risk = InterestRateRisk(
                etf_id=etf_id,
                report_date=report_date,
                filing_date=filing_date,
                currency_code=currency_code,
                dv01_3m=dv01_3m,
                dv01_1y=dv01_1y,
                dv01_5y=dv01_5y,
                dv01_10y=dv01_10y,
                dv01_30y=dv01_30y,
                dv100_3m=dv100_3m,
                dv100_1y=dv100_1y,
                dv100_5y=dv100_5y,
                dv100_10y=dv100_10y,
                dv100_30y=dv100_30y,
            )
            interest_rate_risks.append(interest_rate_risk)

        if interest_rate_risks:
            logger.info(f"Extracted {len(interest_rate_risks)} interest rate risk entries for etf_id={etf_id}")

    except Exception as e:
        logger.warning(f"Failed to extract interest rate risk for etf_id={etf_id}: {e}")

    return interest_rate_risks


def _extract_credit_spread_risk(filing, etf_id: int, report_date, filing_date) -> Optional[CreditSpreadRisk]:
    """Extract credit spread risk data from NPORT-P filing XML.

    Args:
        filing: Filing object from edgartools
        etf_id: ETF ID to associate credit spread risk data with
        report_date: Report date for the filing
        filing_date: Filing date

    Returns:
        CreditSpreadRisk object if data found, None otherwise
    """
    try:
        # Get raw XML content from filing
        xml_content = filing.xml()
        if not xml_content:
            logger.debug(f"No XML content found in filing for etf_id={etf_id}")
            return None

        # Parse XML
        root = ET.fromstring(xml_content)

        # Find credit spread risk elements
        # Path: /edgarSubmission/formData/fundInfo/creditSprdRiskInvstGrade and creditSprdRiskNonInvstGrade
        ns = {'nport': 'http://www.sec.gov/edgar/nport'}

        invst_grade_elem = root.find('.//nport:creditSprdRiskInvstGrade', ns)
        non_invst_grade_elem = root.find('.//nport:creditSprdRiskNonInvstGrade', ns)

        # If neither element is found, return None
        if invst_grade_elem is None and non_invst_grade_elem is None:
            logger.debug(f"No credit spread risk elements found in NPORT XML for etf_id={etf_id}")
            return None

        # Extract investment grade metrics
        invst_grade_3m = None
        invst_grade_1y = None
        invst_grade_5y = None
        invst_grade_10y = None
        invst_grade_30y = None

        if invst_grade_elem is not None:
            invst_grade_3m = _parse_decimal(invst_grade_elem.get('period3Mon'))
            invst_grade_1y = _parse_decimal(invst_grade_elem.get('period1Yr'))
            invst_grade_5y = _parse_decimal(invst_grade_elem.get('period5Yr'))
            invst_grade_10y = _parse_decimal(invst_grade_elem.get('period10Yr'))
            invst_grade_30y = _parse_decimal(invst_grade_elem.get('period30Yr'))

        # Extract non-investment grade metrics
        non_invst_grade_3m = None
        non_invst_grade_1y = None
        non_invst_grade_5y = None
        non_invst_grade_10y = None
        non_invst_grade_30y = None

        if non_invst_grade_elem is not None:
            non_invst_grade_3m = _parse_decimal(non_invst_grade_elem.get('period3Mon'))
            non_invst_grade_1y = _parse_decimal(non_invst_grade_elem.get('period1Yr'))
            non_invst_grade_5y = _parse_decimal(non_invst_grade_elem.get('period5Yr'))
            non_invst_grade_10y = _parse_decimal(non_invst_grade_elem.get('period10Yr'))
            non_invst_grade_30y = _parse_decimal(non_invst_grade_elem.get('period30Yr'))

        # Create CreditSpreadRisk object
        credit_spread_risk = CreditSpreadRisk(
            etf_id=etf_id,
            report_date=report_date,
            filing_date=filing_date,
            invst_grade_3m=invst_grade_3m,
            invst_grade_1y=invst_grade_1y,
            invst_grade_5y=invst_grade_5y,
            invst_grade_10y=invst_grade_10y,
            invst_grade_30y=invst_grade_30y,
            non_invst_grade_3m=non_invst_grade_3m,
            non_invst_grade_1y=non_invst_grade_1y,
            non_invst_grade_5y=non_invst_grade_5y,
            non_invst_grade_10y=non_invst_grade_10y,
            non_invst_grade_30y=non_invst_grade_30y,
        )

        logger.info(f"Extracted credit spread risk data for etf_id={etf_id}")
        return credit_spread_risk

    except Exception as e:
        logger.warning(f"Failed to extract credit spread risk for etf_id={etf_id}: {e}")
        return None


def _parse_decimal(val: Optional[str]) -> Optional[Decimal]:
    """Parse a string value to Decimal, handling N/A and None."""
    if val is None or val.strip().upper() == "N/A":
        return None
    try:
        return Decimal(val)
    except (ValueError, Exception) as e:
        logger.warning(f"Could not parse decimal value '{val}': {e}")
        return None


def _build_derivative_swap(swp, derivative_id: int) -> DerivativeSwap:
    """Build a DerivativeSwap instance from a SwapDerivative object.

    Args:
        swp: SwapDerivative object from edgartools
        derivative_id: Foreign key to parent Derivative row

    Returns:
        DerivativeSwap instance
    """
    upfront_payment = _safe_numeric(swp.upfront_payment) if hasattr(swp, 'upfront_payment') else None
    upfront_payment_currency = _clean_str(swp.payment_currency) if hasattr(swp, 'payment_currency') else None
    upfront_receipt = _safe_numeric(swp.upfront_receipt) if hasattr(swp, 'upfront_receipt') else None
    upfront_receipt_currency = _clean_str(swp.receipt_currency) if hasattr(swp, 'receipt_currency') else None
    swap_flag = _clean_str(swp.swap_flag) if hasattr(swp, 'swap_flag') else None

    return DerivativeSwap(
        derivative_id=derivative_id,
        upfront_payment=upfront_payment,
        upfront_payment_currency=upfront_payment_currency,
        upfront_receipt=upfront_receipt,
        upfront_receipt_currency=upfront_receipt_currency,
        swap_flag=swap_flag,
    )


def _build_swap_legs(swp, swap_id: int) -> list[DerivativeSwapLeg]:
    """Build pay and receive DerivativeSwapLeg instances from a SwapDerivative object.

    Args:
        swp: SwapDerivative object from edgartools
        swap_id: Foreign key to parent DerivativeSwap row

    Returns:
        List of two DerivativeSwapLeg instances (pay and receive)
    """
    legs = []

    # Build pay leg
    pay_leg_type = None
    if hasattr(swp, 'fixed_rate_pay') and swp.fixed_rate_pay is not None:
        pay_leg_type = "fixed"
    elif hasattr(swp, 'floating_index_pay') and swp.floating_index_pay:
        pay_leg_type = "floating"
    elif hasattr(swp, 'other_description_pay') and swp.other_description_pay:
        pay_leg_type = "other"

    pay_leg = DerivativeSwapLeg(
        swap_id=swap_id,
        direction="pay",
        leg_type=pay_leg_type,
        fixed_rate=_safe_numeric(swp.fixed_rate_pay) if hasattr(swp, 'fixed_rate_pay') else None,
        fixed_amount=_safe_numeric(swp.fixed_amount_pay) if hasattr(swp, 'fixed_amount_pay') else None,
        fixed_currency=_clean_str(swp.fixed_currency_pay) if hasattr(swp, 'fixed_currency_pay') else None,
        floating_index=_clean_str(swp.floating_index_pay) if hasattr(swp, 'floating_index_pay') else None,
        floating_spread=_safe_numeric(swp.floating_spread_pay) if hasattr(swp, 'floating_spread_pay') else None,
        floating_amount=_safe_numeric(swp.floating_amount_pay) if hasattr(swp, 'floating_amount_pay') else None,
        floating_currency=_clean_str(swp.floating_currency_pay) if hasattr(swp, 'floating_currency_pay') else None,
        tenor=_clean_str(swp.floating_tenor_pay) if hasattr(swp, 'floating_tenor_pay') else None,
        tenor_unit=_clean_str(swp.floating_tenor_unit_pay) if hasattr(swp, 'floating_tenor_unit_pay') else None,
        reset_date_tenor=_clean_str(swp.floating_reset_date_tenor_pay) if hasattr(swp, 'floating_reset_date_tenor_pay') else None,
        reset_date_unit=_clean_str(swp.floating_reset_date_unit_pay) if hasattr(swp, 'floating_reset_date_unit_pay') else None,
        other_description=_clean_str(swp.other_description_pay) if hasattr(swp, 'other_description_pay') else None,
    )
    legs.append(pay_leg)

    # Build receive leg
    receive_leg_type = None
    if hasattr(swp, 'fixed_rate_receive') and swp.fixed_rate_receive is not None:
        receive_leg_type = "fixed"
    elif hasattr(swp, 'floating_index_receive') and swp.floating_index_receive:
        receive_leg_type = "floating"
    elif hasattr(swp, 'other_description_receive') and swp.other_description_receive:
        receive_leg_type = "other"

    receive_leg = DerivativeSwapLeg(
        swap_id=swap_id,
        direction="receive",
        leg_type=receive_leg_type,
        fixed_rate=_safe_numeric(swp.fixed_rate_receive) if hasattr(swp, 'fixed_rate_receive') else None,
        fixed_amount=_safe_numeric(swp.fixed_amount_receive) if hasattr(swp, 'fixed_amount_receive') else None,
        fixed_currency=_clean_str(swp.fixed_currency_receive) if hasattr(swp, 'fixed_currency_receive') else None,
        floating_index=_clean_str(swp.floating_index_receive) if hasattr(swp, 'floating_index_receive') else None,
        floating_spread=_safe_numeric(swp.floating_spread_receive) if hasattr(swp, 'floating_spread_receive') else None,
        floating_amount=_safe_numeric(swp.floating_amount_receive) if hasattr(swp, 'floating_amount_receive') else None,
        floating_currency=_clean_str(swp.floating_currency_receive) if hasattr(swp, 'floating_currency_receive') else None,
        tenor=_clean_str(swp.floating_tenor_receive) if hasattr(swp, 'floating_tenor_receive') else None,
        tenor_unit=_clean_str(swp.floating_tenor_unit_receive) if hasattr(swp, 'floating_tenor_unit_receive') else None,
        reset_date_tenor=_clean_str(swp.floating_reset_date_tenor_receive) if hasattr(swp, 'floating_reset_date_tenor_receive') else None,
        reset_date_unit=_clean_str(swp.floating_reset_date_unit_receive) if hasattr(swp, 'floating_reset_date_unit_receive') else None,
        other_description=_clean_str(swp.other_description_receive) if hasattr(swp, 'other_description_receive') else None,
    )
    legs.append(receive_leg)

    return legs


def _build_derivative_option(opt, derivative_id: int) -> DerivativeOption:
    """Build a DerivativeOption instance from an OptionDerivative object.
    
    Handles regular options, swaptions, and warrants. Flattens any nested
    derivative info (swaption-on-swap) into the nested_deriv_* columns.

    Args:
        opt: OptionDerivative object from edgartools
        derivative_id: Foreign key to parent Derivative row

    Returns:
        DerivativeOption instance
    """
    put_or_call = _clean_str(opt.put_or_call) if hasattr(opt, 'put_or_call') else None
    written_or_purchased = _clean_str(opt.written_or_purchased) if hasattr(opt, 'written_or_purchased') else None
    share_number = _safe_numeric(opt.share_number) if hasattr(opt, 'share_number') else None
    exercise_price = _safe_numeric(opt.exercise_price) if hasattr(opt, 'exercise_price') else None
    exercise_price_currency = _clean_str(opt.exercise_price_currency) if hasattr(opt, 'exercise_price_currency') else None
    index_name = _clean_str(opt.index_name) if hasattr(opt, 'index_name') else None
    index_identifier = _clean_str(opt.index_identifier) if hasattr(opt, 'index_identifier') else None

    # Handle nested derivative info (e.g., swaption-on-swap)
    nested_deriv_type = None
    nested_deriv_notional = None
    nested_deriv_counterparty = None
    nested_deriv_currency = None

    # Check for nested swap (swaption case)
    if hasattr(opt, 'swap_derivative') and opt.swap_derivative:
        nested_swap = opt.swap_derivative
        nested_deriv_type = "SWP"
        nested_deriv_notional = _safe_numeric(nested_swap.notional_amount) if hasattr(nested_swap, 'notional_amount') else None
        nested_deriv_counterparty = _clean_str(nested_swap.counterparty) if hasattr(nested_swap, 'counterparty') else None
        nested_deriv_currency = _clean_str(nested_swap.currency) if hasattr(nested_swap, 'currency') else None
    # Check for nested forward
    elif hasattr(opt, 'forward_derivative') and opt.forward_derivative:
        nested_fwd = opt.forward_derivative
        nested_deriv_type = "FWD"
        nested_deriv_notional = _safe_numeric(nested_fwd.notional_amount) if hasattr(nested_fwd, 'notional_amount') else None
        nested_deriv_counterparty = _clean_str(nested_fwd.counterparty) if hasattr(nested_fwd, 'counterparty') else None
        nested_deriv_currency = _clean_str(nested_fwd.currency) if hasattr(nested_fwd, 'currency') else None
    # Check for nested future
    elif hasattr(opt, 'future_derivative') and opt.future_derivative:
        nested_fut = opt.future_derivative
        nested_deriv_type = "FUT"
        nested_deriv_notional = _safe_numeric(nested_fut.notional_amount) if hasattr(nested_fut, 'notional_amount') else None
        nested_deriv_counterparty = _clean_str(nested_fut.counterparty) if hasattr(nested_fut, 'counterparty') else None
        nested_deriv_currency = _clean_str(nested_fut.currency) if hasattr(nested_fut, 'currency') else None

    return DerivativeOption(
        derivative_id=derivative_id,
        put_or_call=put_or_call,
        written_or_purchased=written_or_purchased,
        share_number=share_number,
        exercise_price=exercise_price,
        exercise_price_currency=exercise_price_currency,
        index_name=index_name,
        index_identifier=index_identifier,
        nested_deriv_type=nested_deriv_type,
        nested_deriv_notional=nested_deriv_notional,
        nested_deriv_counterparty=nested_deriv_counterparty,
        nested_deriv_currency=nested_deriv_currency,
    )


def _build_derivative_forward(fwd, derivative_id: int) -> DerivativeForward:
    """Build a DerivativeForward instance from a ForwardDerivative object.

    Args:
        fwd: ForwardDerivative object from edgartools
        derivative_id: Foreign key to parent Derivative row

    Returns:
        DerivativeForward instance
    """
    currency_sold = _clean_str(fwd.currency_sold) if hasattr(fwd, 'currency_sold') else None
    amount_sold = _safe_numeric(fwd.amount_sold) if hasattr(fwd, 'amount_sold') else None
    currency_purchased = _clean_str(fwd.currency_purchased) if hasattr(fwd, 'currency_purchased') else None
    amount_purchased = _safe_numeric(fwd.amount_purchased) if hasattr(fwd, 'amount_purchased') else None
    settlement_date = _parse_date(fwd.settlement_date) if hasattr(fwd, 'settlement_date') and fwd.settlement_date else None

    return DerivativeForward(
        derivative_id=derivative_id,
        currency_sold=currency_sold,
        amount_sold=amount_sold,
        currency_purchased=currency_purchased,
        amount_purchased=amount_purchased,
        settlement_date=settlement_date,
    )


def _process_etf(
    session: Session, etf: ETF, filing, fund_report: FundReport, report_date, filing_date
) -> None:
    """Process a single ETF: extract and insert holdings and derivatives."""
    # Extract fund-level snapshot
    _extract_fund_snapshot(session, etf.cik, fund_report, report_date, filing_date)

    # Extract monthly returns
    monthly_returns = _extract_monthly_returns(filing, etf.id, report_date, filing_date)
    for monthly_return in monthly_returns:
        session.add(monthly_return)

    # Extract monthly flows
    monthly_flows = _extract_monthly_flows(filing, etf.id, report_date, filing_date)
    for monthly_flow in monthly_flows:
        session.add(monthly_flow)

    # Extract interest rate risk
    interest_rate_risks = _extract_interest_rate_risk(filing, etf.id, report_date, filing_date)
    for interest_rate_risk in interest_rate_risks:
        session.add(interest_rate_risk)

    # Extract credit spread risk
    credit_spread_risk = _extract_credit_spread_risk(filing, etf.id, report_date, filing_date)
    if credit_spread_risk:
        session.add(credit_spread_risk)

    # Parse XML for custom fields not exposed by edgartools
    xml_custom_fields = parse_nport_investments_xml(filing.xml())

    holdings_count = 0
    seen_holding_keys = set()
    dup_holdings_count = 0
    for investment in fund_report.non_derivatives:
        holding = _map_investment_to_holding(etf, investment, report_date, filing_date, xml_custom_fields)
        if holding.holding_key in seen_holding_keys:
            dup_holdings_count += 1
            continue
        seen_holding_keys.add(holding.holding_key)
        session.add(holding)

        # Check for debt security details and attach to holding
        debt_detail = _map_debt_security_detail(investment)
        if debt_detail:
            holding.debt_security_detail = debt_detail

        # Check for security lending details and attach to holding
        sec_lending = _map_security_lending(investment)
        if sec_lending:
            holding.security_lending = sec_lending

        holdings_count += 1

    derivatives_count = 0
    seen_derivative_keys = set()
    dup_derivatives_count = 0
    for investment in fund_report.derivatives:
        derivative = _map_investment_to_derivative(etf, investment, report_date, filing_date)
        if derivative:
            deriv_key = (derivative.derivative_type, derivative.underlying_name)
            if deriv_key != (None, None) and deriv_key in seen_derivative_keys:
                dup_derivatives_count += 1
                continue
            if deriv_key != (None, None):
                seen_derivative_keys.add(deriv_key)
            session.add(derivative)
            session.flush()  # Flush to get derivative.id

            # Check for swap derivative and create child tables
            if investment.derivative_info and investment.derivative_info.swap_derivative:
                swp = investment.derivative_info.swap_derivative
                derivative_swap = _build_derivative_swap(swp, derivative.id)
                session.add(derivative_swap)
                session.flush()  # Flush to get swap.id

                # Create swap legs
                swap_legs = _build_swap_legs(swp, derivative_swap.id)
                for leg in swap_legs:
                    session.add(leg)

            # Check for option derivative and create child table
            # Handles regular options, swaptions, and warrants
            if investment.derivative_info and investment.derivative_info.option_derivative:
                opt = investment.derivative_info.option_derivative
                derivative_option = _build_derivative_option(opt, derivative.id)
                session.add(derivative_option)

            # Check for swaption (option on swap) - also creates DerivativeOption
            if investment.derivative_info and investment.derivative_info.swaption_derivative:
                swaption = investment.derivative_info.swaption_derivative
                derivative_option = _build_derivative_option(swaption, derivative.id)
                session.add(derivative_option)

            # Check for forward derivative and create child table
            if investment.derivative_info and investment.derivative_info.forward_derivative:
                fwd = investment.derivative_info.forward_derivative
                derivative_forward = _build_derivative_forward(fwd, derivative.id)
                session.add(derivative_forward)

            derivatives_count += 1

    # Log summary of duplicate skips if any
    if dup_holdings_count > 0 or dup_derivatives_count > 0:
        logger.info(f"ETF {etf.ticker}: Skipped {dup_holdings_count} duplicate holdings, {dup_derivatives_count} duplicate derivatives")

    logger.info(
        f"ETF {etf.ticker}: Inserted {holdings_count} holdings, {derivatives_count} derivatives for {report_date}"
    )


def _map_investment_to_holding(
    etf: ETF, investment, report_date, filing_date, xml_custom_fields: dict
) -> Holding:
    """Map an InvestmentOrSecurity to a Holding model instance."""
    identifiers = investment.identifiers

    isin = None
    ticker = None
    currency = None

    if identifiers:
        isin = identifiers.isin

    ticker = investment.ticker

    if hasattr(investment, "currency_code") and investment.currency_code:
        currency = investment.currency_code
    elif identifiers and hasattr(identifiers, "other") and identifiers.other and isinstance(identifiers.other, dict):
        for desc, value in identifiers.other.items():
            if desc and "currency" in desc.lower():
                currency = value

    is_restricted = (
        investment.is_restricted_security
        if investment.is_restricted_security is not None
        else False
    )

    fair_value_level = None
    if investment.fair_value_level:
        try:
            fair_value_level = int(investment.fair_value_level)
        except (ValueError, TypeError):
            logger.debug(f"Could not parse fair_value_level: {investment.fair_value_level}")

    # Extract new fields
    title = _clean_str(investment.title) if hasattr(investment, "title") else None

    payoff_profile = None
    if hasattr(investment, "payoff_profile"):
        payoff_profile = _clean_str(investment.payoff_profile)

    exchange_rate = None
    if hasattr(investment, "exchange_rate") and investment.exchange_rate is not None:
        try:
            exchange_rate = Decimal(str(investment.exchange_rate))
        except (ValueError, TypeError, Exception):
            logger.debug(f"Could not parse exchange_rate: {investment.exchange_rate}")

    # Compute holding_key: COALESCE(cusip, isin, name)
    cusip_clean = _clean_str(investment.cusip)
    isin_clean = _clean_str(isin)
    name_clean = _clean_str(investment.name) or ""
    lei_clean = _clean_str(investment.lei)
    holding_key = cusip_clean or isin_clean or name_clean

    # Extract custom XML fields using holding key
    # Build XML holding key (name|cusip|lei as used in nport_xml.py)
    xml_key = f"{name_clean}|{cusip_clean or ''}|{lei_clean or ''}"
    custom_fields = xml_custom_fields.get(xml_key, {})
    liquidity_classification = custom_fields.get("liquidity_classification")
    borrower_name = custom_fields.get("borrower_name")

    return Holding(
        etf_id=etf.id,
        report_date=report_date,
        filing_date=filing_date,
        name=name_clean,
        cusip=cusip_clean,
        isin=isin_clean,
        ticker=_clean_str(ticker),
        lei=lei_clean,
        balance=investment.balance,
        units=investment.units,
        value_usd=investment.value_usd,
        pct_val=investment.pct_value,
        asset_category=_clean_str(investment.asset_category),
        issuer_category=_clean_str(investment.issuer_category),
        country=_clean_str(investment.investment_country),
        currency=currency,
        fair_value_level=fair_value_level,
        is_restricted=is_restricted,
        title=title,
        payoff_profile=payoff_profile,
        exchange_rate=exchange_rate,
        holding_key=holding_key,
        borrower_name=borrower_name,
        liquidity_classification=liquidity_classification,
    )


def _map_investment_to_derivative(
    etf: ETF, investment, report_date, filing_date
) -> Optional[Derivative]:
    """Map an InvestmentOrSecurity with derivative_info to a Derivative model instance."""
    if not investment.derivative_info:
        return None

    deriv_info = investment.derivative_info
    derivative_type = deriv_info.derivative_category

    if not derivative_type:
        logger.debug(f"Derivative missing category for ETF {etf.ticker}, skipping")
        return None

    underlying_name = None
    underlying_cusip = None
    notional_value = None
    counterparty = None
    counterparty_lei = None
    delta = None
    expiration_date = None
    currency_sold = None
    currency_amt_sold = None
    settlement_date = None
    written_notional_amt = None
    other_amt = None

    # New parent-level fields (US-1)
    unrealized_appreciation = None
    currency = None
    underlying_title = None
    underlying_isin = None
    underlying_ticker = None
    underlying_other_id = None
    underlying_other_id_type = None
    payoff_profile = None

    # Extract unrealized appreciation (all derivative types)
    if hasattr(deriv_info, 'unrealized_appr') and deriv_info.unrealized_appr is not None:
        try:
            unrealized_appreciation = Decimal(str(deriv_info.unrealized_appr))
        except (ValueError, TypeError, Exception):
            logger.debug(f"Could not parse unrealized_appr: {deriv_info.unrealized_appr}")

    if deriv_info.forward_derivative:
        fwd = deriv_info.forward_derivative
        counterparty = fwd.counterparty_name
        counterparty_lei = fwd.counterparty_lei
        underlying_name = fwd.deriv_addl_name
        underlying_cusip = fwd.deriv_addl_cusip
        if fwd.amount_sold:
            notional_value = fwd.amount_sold
        elif fwd.amount_purchased:
            notional_value = fwd.amount_purchased
        expiration_date = _parse_date(fwd.settlement_date)
        # New fields for forward derivatives
        currency_sold = _clean_str(fwd.currency_sold)
        currency_amt_sold = fwd.amount_sold
        settlement_date = _parse_date(fwd.settlement_date)

        # Parent-level fields for forwards (deriv_addl_*)
        currency = _clean_str(fwd.deriv_addl_currency) if hasattr(fwd, 'deriv_addl_currency') else None
        underlying_title = _clean_str(fwd.deriv_addl_title) if hasattr(fwd, 'deriv_addl_title') else None
        underlying_isin = _clean_str(fwd.deriv_addl_isin) if hasattr(fwd, 'deriv_addl_isin') else None
        underlying_ticker = _clean_str(fwd.deriv_addl_ticker) if hasattr(fwd, 'deriv_addl_ticker') else None
        underlying_other_id = _clean_str(fwd.deriv_addl_other_id) if hasattr(fwd, 'deriv_addl_other_id') else None
        underlying_other_id_type = _clean_str(fwd.deriv_addl_other_id_type) if hasattr(fwd, 'deriv_addl_other_id_type') else None

    elif deriv_info.future_derivative:
        fut = deriv_info.future_derivative
        counterparty = fut.counterparty_name
        counterparty_lei = fut.counterparty_lei
        underlying_name = fut.reference_entity_name
        underlying_cusip = fut.reference_entity_cusip
        notional_value = fut.notional_amount
        expiration_date = _parse_date(fut.expiration_date)

        # Parent-level fields for futures (reference_entity_* + payoff_profile)
        currency = _clean_str(fut.currency) if hasattr(fut, 'currency') else None
        payoff_profile = _clean_str(fut.payoff_profile) if hasattr(fut, 'payoff_profile') else None
        underlying_title = _clean_str(fut.reference_entity_title) if hasattr(fut, 'reference_entity_title') else None
        underlying_isin = _clean_str(fut.reference_entity_isin) if hasattr(fut, 'reference_entity_isin') else None
        underlying_ticker = _clean_str(fut.reference_entity_ticker) if hasattr(fut, 'reference_entity_ticker') else None
        underlying_other_id = _clean_str(fut.reference_entity_other_id) if hasattr(fut, 'reference_entity_other_id') else None
        underlying_other_id_type = _clean_str(fut.reference_entity_other_id_type) if hasattr(fut, 'reference_entity_other_id_type') else None

    elif deriv_info.option_derivative:
        opt = deriv_info.option_derivative
        counterparty = opt.counterparty_name
        counterparty_lei = opt.counterparty_lei
        underlying_name = opt.reference_entity_name or opt.index_name
        underlying_cusip = opt.reference_entity_cusip
        if opt.share_number:
            notional_value = opt.share_number
        delta = _parse_delta(opt.delta)
        expiration_date = _parse_date(opt.expiration_date)
        # New field for written options
        if opt.written_or_purchased == "W" and opt.share_number:
            written_notional_amt = opt.share_number

        # Parent-level fields for options (reference_entity_*)
        currency = _clean_str(opt.currency_code) if hasattr(opt, 'currency_code') else None
        underlying_title = _clean_str(opt.reference_entity_title) if hasattr(opt, 'reference_entity_title') else None
        underlying_isin = _clean_str(opt.reference_entity_isin) if hasattr(opt, 'reference_entity_isin') else None
        underlying_ticker = _clean_str(opt.reference_entity_ticker) if hasattr(opt, 'reference_entity_ticker') else None
        underlying_other_id = _clean_str(opt.reference_entity_other_id) if hasattr(opt, 'reference_entity_other_id') else None
        underlying_other_id_type = _clean_str(opt.reference_entity_other_id_type) if hasattr(opt, 'reference_entity_other_id_type') else None

    elif deriv_info.swap_derivative:
        swp = deriv_info.swap_derivative
        counterparty = swp.counterparty_name
        counterparty_lei = swp.counterparty_lei
        underlying_name = swp.deriv_addl_name or swp.reference_entity_name
        underlying_cusip = swp.deriv_addl_cusip or swp.reference_entity_cusip
        notional_value = swp.notional_amount
        expiration_date = _parse_date(swp.termination_date)

        # Parent-level fields for swaps (deriv_addl_* or reference_entity_*)
        currency = _clean_str(swp.currency_code) if hasattr(swp, 'currency_code') else None
        # Prefer deriv_addl_* fields, fallback to reference_entity_*
        underlying_title = _clean_str(swp.deriv_addl_title) if hasattr(swp, 'deriv_addl_title') and swp.deriv_addl_title else (_clean_str(swp.reference_entity_title) if hasattr(swp, 'reference_entity_title') else None)
        underlying_isin = _clean_str(swp.deriv_addl_isin) if hasattr(swp, 'deriv_addl_isin') and swp.deriv_addl_isin else (_clean_str(swp.reference_entity_isin) if hasattr(swp, 'reference_entity_isin') else None)
        underlying_ticker = _clean_str(swp.deriv_addl_ticker) if hasattr(swp, 'deriv_addl_ticker') and swp.deriv_addl_ticker else (_clean_str(swp.reference_entity_ticker) if hasattr(swp, 'reference_entity_ticker') else None)
        underlying_other_id = _clean_str(swp.deriv_addl_other_id) if hasattr(swp, 'deriv_addl_other_id') and swp.deriv_addl_other_id else (_clean_str(swp.reference_entity_other_id) if hasattr(swp, 'reference_entity_other_id') else None)
        underlying_other_id_type = _clean_str(swp.deriv_addl_other_id_type) if hasattr(swp, 'deriv_addl_other_id_type') and swp.deriv_addl_other_id_type else (_clean_str(swp.reference_entity_other_id_type) if hasattr(swp, 'reference_entity_other_id_type') else None)

    elif deriv_info.swaption_derivative:
        swo = deriv_info.swaption_derivative
        counterparty = swo.counterparty_name
        counterparty_lei = swo.counterparty_lei
        expiration_date = _parse_date(swo.expiration_date)
        # New field for written swaptions
        if swo.written_or_purchased == "W" and swo.share_number:
            written_notional_amt = swo.share_number

        # Parent-level fields for swaptions (reference_entity_*)
        underlying_title = _clean_str(swo.reference_entity_title) if hasattr(swo, 'reference_entity_title') else None
        underlying_isin = _clean_str(swo.reference_entity_isin) if hasattr(swo, 'reference_entity_isin') else None
        underlying_ticker = _clean_str(swo.reference_entity_ticker) if hasattr(swo, 'reference_entity_ticker') else None
        underlying_other_id = _clean_str(swo.reference_entity_other_id) if hasattr(swo, 'reference_entity_other_id') else None
        underlying_other_id_type = _clean_str(swo.reference_entity_other_id_type) if hasattr(swo, 'reference_entity_other_id_type') else None

    return Derivative(
        etf_id=etf.id,
        report_date=report_date,
        filing_date=filing_date,
        derivative_type=derivative_type,
        underlying_name=_clean_str(underlying_name),
        underlying_cusip=_clean_str(underlying_cusip),
        notional_value=notional_value,
        counterparty=_clean_str(counterparty),
        counterparty_lei=_clean_str(counterparty_lei),
        delta=delta,
        expiration_date=expiration_date,
        currency_sold=currency_sold,
        currency_amt_sold=currency_amt_sold,
        settlement_date=settlement_date,
        written_notional_amt=written_notional_amt,
        other_amt=other_amt,
        # New parent-level fields (US-1)
        unrealized_appreciation=unrealized_appreciation,
        currency=currency,
        underlying_title=underlying_title,
        underlying_isin=underlying_isin,
        underlying_ticker=underlying_ticker,
        underlying_other_id=underlying_other_id,
        underlying_other_id_type=underlying_other_id_type,
        payoff_profile=payoff_profile,
    )


def _parse_date(date_str: Optional[str]) -> Optional[date]:
    """Parse a date string in YYYY-MM-DD format to a date object."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _parse_delta(delta_value) -> Optional[Decimal]:
    """Parse delta value which can be Decimal, str, or None."""
    if delta_value is None:
        return None
    if isinstance(delta_value, Decimal):
        return delta_value
    try:
        return Decimal(str(delta_value))
    except (ValueError, TypeError, InvalidOperation):
        return None


def _map_debt_security_detail(investment) -> Optional[DebtSecurityDetail]:
    """Map debt_security data from investment to DebtSecurityDetail model instance."""
    try:
        debt_sec = investment.debt_security
        if debt_sec is None:
            return None
        # Check if it's a real debt_security object by verifying it has expected attributes
        if not hasattr(debt_sec, 'maturity_date'):
            return None
    except AttributeError:
        return None

    # Extract maturity_date
    maturity_date = None
    try:
        if hasattr(debt_sec, 'maturity_date') and debt_sec.maturity_date:
            mat_date_raw = debt_sec.maturity_date
            if isinstance(mat_date_raw, str):
                if mat_date_raw == "N/A":
                    maturity_date = None
                else:
                    maturity_date = _parse_date(mat_date_raw)
            elif isinstance(mat_date_raw, datetime):
                maturity_date = mat_date_raw.date()
            elif isinstance(mat_date_raw, date):
                maturity_date = mat_date_raw
    except (AttributeError, TypeError):
        pass

    # Extract coupon_kind
    coupon_kind = None
    try:
        if hasattr(debt_sec, 'coupon_kind') and debt_sec.coupon_kind:
            coupon_kind = _clean_str(debt_sec.coupon_kind)
    except (AttributeError, TypeError):
        pass

    # Extract annualized_rate
    annualized_rate = None
    try:
        if hasattr(debt_sec, 'annualized_rate') and debt_sec.annualized_rate is not None:
            annualized_rate = debt_sec.annualized_rate
    except (AttributeError, TypeError):
        pass

    # Extract boolean fields
    is_default = False
    try:
        if hasattr(debt_sec, 'is_default') and debt_sec.is_default is not None:
            is_default = bool(debt_sec.is_default)
    except (AttributeError, TypeError):
        pass

    is_in_arrears = False
    try:
        if hasattr(debt_sec, 'are_instrument_payents_in_arrears') and debt_sec.are_instrument_payents_in_arrears is not None:
            is_in_arrears = bool(debt_sec.are_instrument_payents_in_arrears)
    except (AttributeError, TypeError):
        pass

    is_paid_kind = False
    try:
        if hasattr(debt_sec, 'is_paid_kind') and debt_sec.is_paid_kind is not None:
            is_paid_kind = bool(debt_sec.is_paid_kind)
    except (AttributeError, TypeError):
        pass

    is_mandatory_convertible = False
    try:
        if hasattr(debt_sec, 'is_mandatory_convertible') and debt_sec.is_mandatory_convertible is not None:
            is_mandatory_convertible = bool(debt_sec.is_mandatory_convertible)
    except (AttributeError, TypeError):
        pass

    is_contingent_convertible = False
    try:
        if hasattr(debt_sec, 'is_continuing_convertible') and debt_sec.is_continuing_convertible is not None:
            is_contingent_convertible = bool(debt_sec.is_continuing_convertible)
    except (AttributeError, TypeError):
        pass

    return DebtSecurityDetail(
        maturity_date=maturity_date,
        coupon_kind=coupon_kind,
        annualized_rate=annualized_rate,
        is_default=is_default,
        is_in_arrears=is_in_arrears,
        is_paid_kind=is_paid_kind,
        is_mandatory_convertible=is_mandatory_convertible,
        is_contingent_convertible=is_contingent_convertible,
    )



def _map_security_lending(investment) -> Optional[SecurityLending]:
    """Map security_lending data from investment to SecurityLending model instance."""
    try:
        sec_lending = investment.security_lending
        if sec_lending is None:
            return None
        # Check if it's a real security_lending object by verifying it has expected attributes
        if not hasattr(sec_lending, 'is_cash_collateral'):
            return None
    except AttributeError:
        return None

    # Extract boolean fields
    is_cash_collateral = False
    try:
        if hasattr(sec_lending, 'is_cash_collateral') and sec_lending.is_cash_collateral is not None:
            is_cash_collateral = (sec_lending.is_cash_collateral == "Y")
    except (AttributeError, TypeError):
        pass

    is_non_cash_collateral = False
    try:
        if hasattr(sec_lending, 'is_non_cash_collateral') and sec_lending.is_non_cash_collateral is not None:
            is_non_cash_collateral = (sec_lending.is_non_cash_collateral == "Y")
    except (AttributeError, TypeError):
        pass

    is_loan_by_fund = False
    try:
        if hasattr(sec_lending, 'is_loan_by_fund') and sec_lending.is_loan_by_fund is not None:
            is_loan_by_fund = (sec_lending.is_loan_by_fund == "Y")
    except (AttributeError, TypeError):
        pass

    return SecurityLending(
        is_cash_collateral=is_cash_collateral,
        is_non_cash_collateral=is_non_cash_collateral,
        is_loan_by_fund=is_loan_by_fund,
    )
