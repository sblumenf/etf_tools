"""Parse NPORT-P filings for holdings and derivatives data."""

import hashlib
import logging
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from edgar import Company
from edgar.funds.reports import FundReport
from sqlalchemy import and_, func, or_, select
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
from etf_pipeline.parser_utils import (
    build_filing_date_filter,
    clean_str,
    clear_and_log_cache,
    ensure_date,
    get_clean,
    parse_date,
    parse_decimal,
    update_processing_log,
)
from etf_pipeline.parsers.nport_xml import parse_nport_investments_xml

logger = logging.getLogger(__name__)

NPORT_NS = {'nport': 'http://www.sec.gov/edgar/nport'}
# Note: "N/A" is already converted to None by clean_str() before this check runs
PLACEHOLDER_CUSIPS = {"000000000", "999999999"}

# Sentinel values for NOT NULL constraint columns where data is missing
EMPTY_SENTINEL = ""
NO_EXPIRATION_SENTINEL = date(9999, 12, 31)


def parse_nport(
    cik: Optional[str] = None,
    ciks: Optional[list[str]] = None,
    limit: Optional[int] = None,
    clear_cache: bool = True,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> None:
    """Parse NPORT-P filings for all ETFs and extract holdings and derivatives.

    Args:
        cik: Optional CIK to process (all others will be skipped)
        ciks: Optional list of CIKs to process (overrides cik parameter)
        limit: Optional limit on number of CIKs to process (alphabetical order)
        clear_cache: Whether to clear edgartools HTTP cache after processing
        from_date: Optional start date for backfill (YYYY-MM-DD)
        to_date: Optional end date for backfill (YYYY-MM-DD)
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
    process_cik = _make_process_cik(from_date, to_date)

    for cik_str in ciks_to_process:
        try:
            process_cik(session_factory, cik_str, len(by_cik[cik_str]))
            succeeded += 1
        except Exception as e:
            failed += 1
            logger.error(f"Failed to process CIK {cik_str}: {e}", exc_info=True)

    logger.info(f"Summary: {succeeded} CIKs succeeded, {failed} CIKs failed")

    if clear_cache:
        clear_and_log_cache()


def _get_all_filings_per_series(filings):
    """Get all filings per series_id for backfill mode.

    Args:
        filings: EntityFilings collection from edgartools

    Returns:
        dict: Mapping of series_id -> list of (filing, fund_report, report_date, filing_date)
    """
    if not filings or (hasattr(filings, 'empty') and filings.empty):
        return {}

    series_map = {}
    for filing in filings:
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
            series_map.setdefault(series_id, []).append((filing, fund_report, report_date, filing_date))

        except Exception as e:
            logger.warning(f"Failed to parse filing: {e} (filing_date={filing.filing_date})")
            continue

    return series_map


def _get_latest_filings_per_series(filings, needed_series_ids=None):
    """Get the most recent filing per series_id across all filing dates.

    Args:
        filings: EntityFilings collection from edgartools
        needed_series_ids: optional set of series_ids to find; when all are found, stops early

    Returns:
        dict: Mapping of series_id -> (filing, fund_report, report_date, filing_date)
    """
    if not filings or (hasattr(filings, 'empty') and filings.empty):
        return {}

    # Sort all filings by filing_date descending so first match wins (most recent)
    all_filings = sorted(filings, key=lambda f: f.filing_date, reverse=True)

    if not all_filings:
        return {}

    # Parse each filing; first time we see a series_id is the most recent
    series_map = {}
    for filing in all_filings:
        try:
            fund_report = FundReport.from_filing(filing)
            series_id = fund_report.general_info.series_id

            if not series_id:
                logger.warning(f"Filing has no series_id, skipping (filing_date={filing.filing_date})")
                continue

            if series_id in series_map:
                continue

            report_date = fund_report.reporting_period
            if isinstance(report_date, str):
                report_date = datetime.strptime(report_date, "%Y-%m-%d").date()

            filing_date = ensure_date(filing.filing_date)
            series_map[series_id] = (filing, fund_report, report_date, filing_date)

            if needed_series_ids and needed_series_ids.issubset(series_map.keys()):
                logger.info(f"All {len(needed_series_ids)} needed series found after scanning — stopping early")
                break

        except Exception as e:
            logger.warning(f"Failed to parse filing: {e} (filing_date={filing.filing_date})")
            continue

    return series_map


def _make_process_cik(from_date: Optional[str] = None, to_date: Optional[str] = None):
    """Factory: return a _process_cik function with optional backfill date range."""
    backfill_mode = from_date is not None and to_date is not None
    date_filter = build_filing_date_filter(from_date, to_date)

    def _process_cik(session_factory: sessionmaker, cik: str, etf_count: int) -> None:
        """Process a single CIK: fetch NPORT-P filings and extract holdings and derivatives by series_id."""
        logger.info(f"Processing CIK {cik}: {etf_count} ETF(s)")

        company = Company(cik)
        kwargs = {"form": "NPORT-P"}
        if date_filter is not None:
            kwargs["filing_date"] = date_filter
        filings = company.get_filings(**kwargs)

        if not filings or (hasattr(filings, 'empty') and filings.empty):
            logger.warning(f"CIK {cik}: No NPORT-P filings found")
            return

        logger.info(f"CIK {cik}: Found {len(filings)} NPORT-P filing(s)")

        if backfill_mode:
            # Backfill: process all filings per series
            series_all = _get_all_filings_per_series(filings)
            if not series_all:
                logger.warning(f"CIK {cik}: No valid series found in filings")
                return

            with session_factory() as session:
                stmt = select(ETF).where(ETF.cik == cik)
                etfs = session.execute(stmt).scalars().all()

                latest_filing_date = None
                processed = 0
                total = sum(len(v) for v in series_all.values())

                for etf in etfs:
                    if etf.series_id not in series_all:
                        logger.warning(f"ETF {etf.ticker} (series_id={etf.series_id}): No matching NPORT-P filing found")
                        continue
                    filings_for_series = series_all[etf.series_id]
                    for i, (filing, fund_report, report_date, filing_date) in enumerate(filings_for_series):
                        # Per-filing dedup check
                        stmt_existing = select(Holding.etf_id).where(
                            Holding.etf_id == etf.id,
                            Holding.report_date == report_date,
                        ).limit(1)
                        already_exists = session.execute(stmt_existing).scalar_one_or_none()
                        if already_exists is not None:
                            logger.info(f"ETF {etf.ticker}: Holdings already exist for {report_date}, skipping")
                            continue
                        _process_etf(session, etf, filing, fund_report, report_date, filing_date)
                        session.commit()
                        processed += 1
                        logger.info(f"CIK {cik}: Processed {processed}/{total} filings (ETF {etf.ticker}, {report_date})")
                        if latest_filing_date is None or filing_date > latest_filing_date:
                            latest_filing_date = filing_date

                if latest_filing_date is not None:
                    update_processing_log(session, cik, "nport", latest_filing_date)
                    session.commit()

            logger.info(f"CIK {cik}: Backfill complete — {processed} filing(s) processed")
        else:
            # Normal mode: latest filing per series only
            # Query ETFs first so we know which series_ids we need
            with session_factory() as session:
                stmt = select(ETF).where(ETF.cik == cik)
                etfs = session.execute(stmt).scalars().all()
                needed_series_ids = {etf.series_id for etf in etfs if etf.series_id}

            series_map = _get_latest_filings_per_series(filings, needed_series_ids) if needed_series_ids else {}

            if not series_map and needed_series_ids:
                logger.warning(f"CIK {cik}: No valid series found in filings")
                return

            logger.info(f"CIK {cik}: Parsed {len(series_map)} series from filings")

            latest_filing_date = None

            with session_factory() as session:
                stmt = select(ETF).where(ETF.cik == cik)
                etfs = session.execute(stmt).scalars().all()

                # Collect etf_ids and report_dates that need checking
                etf_report_pairs = []
                for etf in etfs:
                    if etf.series_id in series_map:
                        _, _, report_date, _ = series_map[etf.series_id]
                        etf_report_pairs.append((etf.id, report_date))

                # Batch query: find ETFs that already have holdings for their report_date,
                # and the max filing_date stored for each, so amendments can overwrite older data.
                existing_filing_dates = {}
                if etf_report_pairs:
                    conditions = [
                        and_(Holding.etf_id == eid, Holding.report_date == rd)
                        for eid, rd in etf_report_pairs
                    ]
                    stmt_existing = (
                        select(Holding.etf_id, func.max(Holding.filing_date))
                        .where(or_(*conditions))
                        .group_by(Holding.etf_id)
                    )
                    for row_etf_id, row_filing_date in session.execute(stmt_existing).all():
                        existing_filing_dates[row_etf_id] = ensure_date(row_filing_date)

                processed = 0
                processed_series = set()
                for etf in etfs:
                    if etf.series_id not in series_map:
                        logger.warning(f"ETF {etf.ticker} (series_id={etf.series_id}): No matching NPORT-P filing found")
                        continue
                    if etf.series_id and etf.series_id in processed_series:
                        logger.debug("%s: series %s already processed for this CIK, skipping", etf.ticker, etf.series_id)
                        continue
                    if etf.id in existing_filing_dates:
                        _, _, report_date_check, filing_date_check = series_map[etf.series_id]
                        if not _check_amendment_and_clear(session, etf, report_date_check, filing_date_check, existing_filing_dates[etf.id]):
                            continue
                    filing, fund_report, report_date, filing_date = series_map[etf.series_id]
                    try:
                        _process_etf(session, etf, filing, fund_report, report_date, filing_date)
                        session.commit()
                        processed += 1
                        if filing_date and (latest_filing_date is None or ensure_date(filing_date) > latest_filing_date):
                            latest_filing_date = ensure_date(filing_date)
                        if etf.series_id:
                            processed_series.add(etf.series_id)
                    except Exception as e:
                        session.rollback()
                        logger.error("%s: failed to process: %s", etf.ticker, e)
                        if etf.series_id:
                            processed_series.add(etf.series_id)

                # Handle UITs (ETFs with no series_id) — process by CIK alone
                uit_etfs = [etf for etf in etfs if not etf.series_id]
                if uit_etfs and filings:
                    # Only use this path when ALL ETFs under this CIK lack series_id
                    # (prevents accidentally using this for multi-series issuers)
                    series_etfs = [etf for etf in etfs if etf.series_id]
                    if not series_etfs:
                        uit_filing = None
                        uit_fund_report = None
                        uit_report_date = None
                        uit_filing_date_val = None
                        for f in filings:
                            try:
                                fr = FundReport.from_filing(f)
                                uit_report_date = ensure_date(fr.general_info.report_date)
                                uit_filing_date_val = f.filing_date
                                uit_filing = f
                                uit_fund_report = fr
                                break
                            except Exception as e:
                                logger.debug("CIK %s: filing %s failed to parse: %s", cik, f.accession_number, e)
                                continue
                        if uit_filing is None:
                            logger.warning("CIK %s: no valid NPORT-P filings found for UIT ETFs", cik)
                            return

                        for etf in uit_etfs:
                            if not _check_amendment_and_clear(session, etf, uit_report_date, uit_filing_date_val):
                                continue
                            logger.info("Processing UIT ETF %s (CIK %s) from filing dated %s", etf.ticker, cik, uit_filing_date_val)
                            try:
                                _process_etf(session, etf, uit_filing, uit_fund_report, uit_report_date, uit_filing_date_val)
                                session.commit()
                                processed += 1
                                if uit_filing_date_val and (latest_filing_date is None or ensure_date(uit_filing_date_val) > latest_filing_date):
                                    latest_filing_date = ensure_date(uit_filing_date_val)
                            except Exception as e:
                                session.rollback()
                                logger.error("%s: failed to process: %s", etf.ticker, e)

                # Update processing log after successful processing
                if latest_filing_date is not None:
                    latest_filing_date = ensure_date(latest_filing_date)
                    update_processing_log(session, cik, "nport", latest_filing_date)
                    session.commit()

            logger.info(f"CIK {cik}: Processed {processed}/{etf_count} ETF(s)")

    return _process_cik


# Default (normal mode) process_cik for backward compatibility
_process_cik = _make_process_cik()


def _extract_fund_snapshot(
    session: Session, cik: str, series_id: str | None, fund_report: FundReport, report_date, filing_date
) -> None:
    """Extract and insert fund-level balance sheet snapshot from FundReport."""
    # Check if snapshot already exists
    stmt = select(FundSnapshot).where(
        FundSnapshot.cik == cik,
        FundSnapshot.series_id == (series_id or ""),
        FundSnapshot.report_date == report_date,
        FundSnapshot.filing_date == filing_date,
    )
    existing = session.execute(stmt).scalar_one_or_none()
    if existing:
        logger.debug(f"Fund snapshot already exists for CIK {cik} on {report_date}")
        return

    try:
        fi = fund_report.fund_info
    except AttributeError:
        logger.warning(f"No fund_info found in FundReport for CIK {cik}")
        return

    is_non_cash_collateral_val = getattr(fi, 'is_non_cash_collateral', None)
    is_non_cash_collateral = bool(is_non_cash_collateral_val) if is_non_cash_collateral_val is not None else False

    snapshot = FundSnapshot(
        cik=cik,
        series_id=series_id or "",
        report_date=report_date,
        filing_date=filing_date,
        total_assets=getattr(fi, 'total_assets', None),
        total_liabilities=getattr(fi, 'total_liabilities', None),
        net_assets=getattr(fi, 'net_assets', None),
        cash_not_reported=getattr(fi, 'cash_not_reported', None),
        assets_invested=getattr(fi, 'assets_invested', None),
        assets_misc_sec=getattr(fi, 'assets_misc_sec', None),
        amt_pay_one_yr_banks_borr=getattr(fi, 'amt_pay_one_yr_banks_borr', None),
        amt_pay_one_yr_ctrld_comp=getattr(fi, 'amt_pay_one_yr_ctrld_comp', None),
        amt_pay_one_yr_oth_affil=getattr(fi, 'amt_pay_one_yr_oth_affil', None),
        amt_pay_one_yr_other=getattr(fi, 'amt_pay_one_yr_other', None),
        amt_pay_aft_one_yr_banks_borr=getattr(fi, 'amt_pay_aft_one_yr_banks_borr', None),
        amt_pay_aft_one_yr_ctrld_comp=getattr(fi, 'amt_pay_aft_one_yr_ctrld_comp', None),
        amt_pay_aft_one_yr_oth_affil=getattr(fi, 'amt_pay_aft_one_yr_oth_affil', None),
        amt_pay_aft_one_yr_other=getattr(fi, 'amt_pay_aft_one_yr_other', None),
        delay_deliv=getattr(fi, 'delay_deliv', None),
        stand_by_commit=getattr(fi, 'stand_by_commit', None),
        liquidity_pref=getattr(fi, 'liquidity_pref', None),
        is_non_cash_collateral=is_non_cash_collateral,
    )
    session.add(snapshot)
    logger.info(f"Created fund snapshot for CIK {cik} on {report_date}")


def _extract_monthly_returns(root, etf_id: int, report_date, filing_date) -> list[NPORTMonthlyReturn]:
    """Extract monthly return data from NPORT-P filing XML.

    Args:
        root: Parsed XML root Element
        etf_id: ETF ID to associate returns with
        report_date: Report date for the filing
        filing_date: Filing date

    Returns:
        List of NPORTMonthlyReturn objects
    """
    monthly_returns = []

    try:
        # Find monthlyTotReturns element
        # Path: /edgarSubmission/formData/fundInfo/returnInfo/monthlyTotReturns
        monthly_tot_returns = root.find('.//nport:monthlyTotReturns', NPORT_NS)

        if monthly_tot_returns is None:
            logger.debug(f"No monthlyTotReturns element found in NPORT XML for etf_id={etf_id}")
            return monthly_returns

        # Extract each monthlyTotReturn child element
        for monthly_return_elem in monthly_tot_returns.findall('nport:monthlyTotReturn', NPORT_NS):
            # Extract attributes
            rtn1 = monthly_return_elem.get('rtn1')
            rtn2 = monthly_return_elem.get('rtn2')
            rtn3 = monthly_return_elem.get('rtn3')
            class_id = monthly_return_elem.get('classId')

            month_1 = parse_decimal(rtn1)
            month_2 = parse_decimal(rtn2)
            month_3 = parse_decimal(rtn3)

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


def _extract_monthly_flows(root, etf_id: int, report_date, filing_date) -> list[NPORTMonthlyFlow]:
    """Extract monthly flow data from NPORT-P filing XML.

    Args:
        root: Parsed XML root Element
        etf_id: ETF ID to associate flows with
        report_date: Report date for the filing
        filing_date: Filing date

    Returns:
        List of NPORTMonthlyFlow objects
    """
    monthly_flows = []

    try:
        # Find fundInfo element which contains monthly flow data
        # Path: /edgarSubmission/formData/fundInfo
        fund_info = root.find('.//nport:fundInfo', NPORT_NS)

        if fund_info is None:
            logger.debug(f"No fundInfo element found in NPORT XML for etf_id={etf_id}")
            return monthly_flows

        # Extract flow data from three separate elements: mon1Flow, mon2Flow, mon3Flow
        mon1_flow = fund_info.find('nport:mon1Flow', NPORT_NS)
        mon2_flow = fund_info.find('nport:mon2Flow', NPORT_NS)
        mon3_flow = fund_info.find('nport:mon3Flow', NPORT_NS)

        # If no flow elements found, return empty list
        if mon1_flow is None and mon2_flow is None and mon3_flow is None:
            logger.debug(f"No monthly flow elements found in NPORT XML for etf_id={etf_id}")
            return monthly_flows

        # Extract flow data from attributes
        month_1_sales = parse_decimal(mon1_flow.get('sales')) if mon1_flow is not None else None
        month_1_redemptions = parse_decimal(mon1_flow.get('redemption')) if mon1_flow is not None else None
        month_1_reinvestments = parse_decimal(mon1_flow.get('reinvestment')) if mon1_flow is not None else None

        month_2_sales = parse_decimal(mon2_flow.get('sales')) if mon2_flow is not None else None
        month_2_redemptions = parse_decimal(mon2_flow.get('redemption')) if mon2_flow is not None else None
        month_2_reinvestments = parse_decimal(mon2_flow.get('reinvestment')) if mon2_flow is not None else None

        month_3_sales = parse_decimal(mon3_flow.get('sales')) if mon3_flow is not None else None
        month_3_redemptions = parse_decimal(mon3_flow.get('redemption')) if mon3_flow is not None else None
        month_3_reinvestments = parse_decimal(mon3_flow.get('reinvestment')) if mon3_flow is not None else None

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


def _parse_risk_metrics(elem):
    """Extract 5 period metrics from a risk element using attributes, or return 5 Nones."""
    if elem is None:
        return None, None, None, None, None
    return (
        parse_decimal(elem.get('period3Mon')),
        parse_decimal(elem.get('period1Yr')),
        parse_decimal(elem.get('period5Yr')),
        parse_decimal(elem.get('period10Yr')),
        parse_decimal(elem.get('period30Yr')),
    )


def _extract_interest_rate_risk(root, etf_id: int, report_date, filing_date) -> list[InterestRateRisk]:
    """Extract interest rate risk data from NPORT-P filing XML.

    Args:
        root: Parsed XML root Element
        etf_id: ETF ID to associate interest rate risk data with
        report_date: Report date for the filing
        filing_date: Filing date

    Returns:
        List of InterestRateRisk objects
    """
    interest_rate_risks = []

    try:
        # Find curMetrics element
        # Path: /edgarSubmission/formData/fundinfo/curMetrics
        cur_metrics = root.find('.//nport:curMetrics', NPORT_NS)

        if cur_metrics is None:
            logger.debug(f"No curMetrics element found in NPORT XML for etf_id={etf_id}")
            return interest_rate_risks

        # Extract each curMetric child element
        for cur_metric_elem in cur_metrics.findall('nport:curMetric', NPORT_NS):
            # Extract currency code
            cur_cd_elem = cur_metric_elem.find('nport:curCd', NPORT_NS)
            if cur_cd_elem is None or not cur_cd_elem.text:
                logger.warning(f"curMetric missing currency code for etf_id={etf_id}, skipping")
                continue

            currency_code = cur_cd_elem.text.strip()

            # Extract DV01 and DV100 risk metrics
            dv01_elem = cur_metric_elem.find('nport:intrstRtRiskdv01', NPORT_NS)
            dv01_3m, dv01_1y, dv01_5y, dv01_10y, dv01_30y = _parse_risk_metrics(dv01_elem)

            dv100_elem = cur_metric_elem.find('nport:intrstRtRiskdv100', NPORT_NS)
            dv100_3m, dv100_1y, dv100_5y, dv100_10y, dv100_30y = _parse_risk_metrics(dv100_elem)

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


def _extract_credit_spread_risk(root, etf_id: int, report_date, filing_date) -> Optional[CreditSpreadRisk]:
    """Extract credit spread risk data from NPORT-P filing XML.

    Args:
        root: Parsed XML root Element
        etf_id: ETF ID to associate credit spread risk data with
        report_date: Report date for the filing
        filing_date: Filing date

    Returns:
        CreditSpreadRisk object if data found, None otherwise
    """
    try:
        # Find credit spread risk elements
        # Path: /edgarSubmission/formData/fundInfo/creditSprdRiskInvstGrade and creditSprdRiskNonInvstGrade
        invst_grade_elem = root.find('.//nport:creditSprdRiskInvstGrade', NPORT_NS)
        non_invst_grade_elem = root.find('.//nport:creditSprdRiskNonInvstGrade', NPORT_NS)

        # If neither element is found, return None
        if invst_grade_elem is None and non_invst_grade_elem is None:
            logger.debug(f"No credit spread risk elements found in NPORT XML for etf_id={etf_id}")
            return None

        # Extract investment grade and non-investment grade metrics
        invst_grade_3m, invst_grade_1y, invst_grade_5y, invst_grade_10y, invst_grade_30y = _parse_risk_metrics(invst_grade_elem)
        non_invst_grade_3m, non_invst_grade_1y, non_invst_grade_5y, non_invst_grade_10y, non_invst_grade_30y = _parse_risk_metrics(non_invst_grade_elem)

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



def _build_derivative_swap(swp, derivative_id: int) -> DerivativeSwap:
    """Build a DerivativeSwap instance from a SwapDerivative object.

    Args:
        swp: SwapDerivative object from edgartools
        derivative_id: Foreign key to parent Derivative row

    Returns:
        DerivativeSwap instance
    """
    upfront_payment = getattr(swp, 'upfront_payment', None)
    upfront_payment_currency = get_clean(swp, 'payment_currency')
    upfront_receipt = getattr(swp, 'upfront_receipt', None)
    upfront_receipt_currency = get_clean(swp, 'receipt_currency')
    swap_flag = get_clean(swp, 'swap_flag')

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

    for direction in ("pay", "receive"):
        leg_type = None
        if hasattr(swp, f'fixed_rate_{direction}') and getattr(swp, f'fixed_rate_{direction}') is not None:
            leg_type = "fixed"
        elif hasattr(swp, f'floating_index_{direction}') and getattr(swp, f'floating_index_{direction}'):
            leg_type = "floating"
        elif hasattr(swp, f'other_description_{direction}') and getattr(swp, f'other_description_{direction}'):
            leg_type = "other"

        leg = DerivativeSwapLeg(
            swap_id=swap_id,
            direction=direction,
            leg_type=leg_type,
            fixed_rate=getattr(swp, f'fixed_rate_{direction}', None),
            fixed_amount=getattr(swp, f'fixed_amount_{direction}', None),
            fixed_currency=get_clean(swp, f'fixed_currency_{direction}'),
            floating_index=get_clean(swp, f'floating_index_{direction}'),
            floating_spread=getattr(swp, f'floating_spread_{direction}', None),
            floating_amount=getattr(swp, f'floating_amount_{direction}', None),
            floating_currency=get_clean(swp, f'floating_currency_{direction}'),
            tenor=get_clean(swp, f'floating_tenor_{direction}'),
            tenor_unit=get_clean(swp, f'floating_tenor_unit_{direction}'),
            reset_date_tenor=get_clean(swp, f'floating_reset_date_tenor_{direction}'),
            reset_date_unit=get_clean(swp, f'floating_reset_date_unit_{direction}'),
            other_description=get_clean(swp, f'other_description_{direction}'),
        )
        legs.append(leg)

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
    put_or_call = get_clean(opt, 'put_or_call')
    written_or_purchased = get_clean(opt, 'written_or_purchased')
    share_number = getattr(opt, 'share_number', None)
    exercise_price = getattr(opt, 'exercise_price', None)
    exercise_price_currency = get_clean(opt, 'exercise_price_currency')
    index_name = get_clean(opt, 'index_name')
    index_identifier = get_clean(opt, 'index_identifier')

    # Handle nested derivative info (e.g., swaption-on-swap)
    nested_deriv_type = None
    nested_deriv_notional = None
    nested_deriv_counterparty = None
    nested_deriv_currency = None

    # Check for nested swap (swaption case)
    if hasattr(opt, 'swap_derivative') and opt.swap_derivative:
        nested_swap = opt.swap_derivative
        nested_deriv_type = "SWP"
        nested_deriv_notional = getattr(nested_swap, 'notional_amount', None)
        nested_deriv_counterparty = get_clean(nested_swap, 'counterparty')
        nested_deriv_currency = get_clean(nested_swap, 'currency')
    # Check for nested forward
    elif hasattr(opt, 'forward_derivative') and opt.forward_derivative:
        nested_fwd = opt.forward_derivative
        nested_deriv_type = "FWD"
        nested_deriv_notional = getattr(nested_fwd, 'notional_amount', None)
        nested_deriv_counterparty = get_clean(nested_fwd, 'counterparty')
        nested_deriv_currency = get_clean(nested_fwd, 'currency')
    # Check for nested future
    elif hasattr(opt, 'future_derivative') and opt.future_derivative:
        nested_fut = opt.future_derivative
        nested_deriv_type = "FUT"
        nested_deriv_notional = getattr(nested_fut, 'notional_amount', None)
        nested_deriv_counterparty = get_clean(nested_fut, 'counterparty')
        nested_deriv_currency = get_clean(nested_fut, 'currency')

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
    currency_sold = get_clean(fwd, 'currency_sold')
    amount_sold = getattr(fwd, 'amount_sold', None)
    currency_purchased = get_clean(fwd, 'currency_purchased')
    amount_purchased = getattr(fwd, 'amount_purchased', None)
    settlement_date = parse_date(fwd.settlement_date) if hasattr(fwd, 'settlement_date') and fwd.settlement_date else None

    return DerivativeForward(
        derivative_id=derivative_id,
        currency_sold=currency_sold,
        amount_sold=amount_sold,
        currency_purchased=currency_purchased,
        amount_purchased=amount_purchased,
        settlement_date=settlement_date,
    )


def _check_amendment_and_clear(session, etf, report_date, new_filing_date, existing_max_date=None):
    """Check if new filing supersedes existing data. Delete old data if so.

    Returns True if caller should proceed with processing, False to skip.
    """
    if existing_max_date is None:
        existing_max_date = (
            session.query(func.max(Holding.filing_date))
            .filter(Holding.etf_id == etf.id, Holding.report_date == report_date)
            .scalar()
        )

    if existing_max_date is None:
        return True  # No existing data, proceed

    old_date = ensure_date(existing_max_date)
    new_date = ensure_date(new_filing_date)

    if new_date > old_date:
        logger.info("%s: replacing holdings from filing %s with amendment from %s", etf.ticker, old_date, new_date)
        session.query(Holding).filter(Holding.etf_id == etf.id, Holding.report_date == report_date).delete()
        session.query(Derivative).filter(Derivative.etf_id == etf.id, Derivative.report_date == report_date).delete()
        return True

    logger.info("%s: holdings already up to date (filing %s), skipping", etf.ticker, old_date)
    return False


def _process_etf(
    session: Session, etf: ETF, filing, fund_report: FundReport, report_date, filing_date
) -> None:
    """Process a single ETF: extract and insert holdings and derivatives."""
    # Extract fund-level snapshot
    _extract_fund_snapshot(session, etf.cik, etf.series_id, fund_report, report_date, filing_date)

    xml_text = filing.xml()

    # Parse XML once and reuse root for all extraction functions
    root = None
    if xml_text:
        try:
            root = ET.fromstring(xml_text)
        except (ET.ParseError, TypeError) as e:
            logger.warning(f"ETF {etf.ticker}: Failed to parse XML: {e}")

    # Extract monthly returns
    monthly_returns = _extract_monthly_returns(root, etf.id, report_date, filing_date) if root is not None else []
    for monthly_return in monthly_returns:
        session.add(monthly_return)

    # Extract monthly flows
    monthly_flows = _extract_monthly_flows(root, etf.id, report_date, filing_date) if root is not None else []
    for monthly_flow in monthly_flows:
        session.add(monthly_flow)

    # Extract interest rate risk
    interest_rate_risks = _extract_interest_rate_risk(root, etf.id, report_date, filing_date) if root is not None else []
    for interest_rate_risk in interest_rate_risks:
        session.add(interest_rate_risk)

    # Extract credit spread risk
    credit_spread_risk = _extract_credit_spread_risk(root, etf.id, report_date, filing_date) if root is not None else None
    if credit_spread_risk:
        session.add(credit_spread_risk)

    # Parse XML for custom fields not exposed by edgartools
    xml_custom_fields = parse_nport_investments_xml(xml_text)

    holdings_count = 0
    seen_holding_keys = set()
    dup_holdings_count = 0
    for investment in (fund_report.non_derivatives or []):
        try:
            holding = _map_investment_to_holding(etf, investment, report_date, filing_date, xml_custom_fields)
            # Note: filing_date and etf_id are constant per _process_etf call;
            # DB constraint (etf_id, report_date, holding_key, filing_date) covers them at insert time.
            dedup_key = holding.holding_key
            if dedup_key in seen_holding_keys:
                dup_holdings_count += 1
                continue
            seen_holding_keys.add(dedup_key)
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
        except Exception as e:
            logger.warning("%s: skipping holding due to error: %s", etf.ticker, e, exc_info=True)
            continue

    derivatives_count = 0
    seen_derivative_keys = set()
    dup_derivatives_count = 0
    for investment in (fund_report.derivatives or []):
        try:
            derivative = _map_investment_to_derivative(etf, investment, report_date, filing_date)
            if derivative:
                deriv_key = (derivative.derivative_type, derivative.underlying_name, derivative.expiration_date, derivative.counterparty)
                if deriv_key in seen_derivative_keys:
                    dup_derivatives_count += 1
                    continue
                seen_derivative_keys.add(deriv_key)

                savepoint = session.begin_nested()
                try:
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

                    savepoint.commit()
                    derivatives_count += 1
                except Exception as e:
                    savepoint.rollback()
                    logger.warning("%s: skipping derivative (child build failed): %s", etf.ticker, e, exc_info=True)
                    continue
        except Exception as e:
            logger.warning("%s: skipping derivative (mapping failed): %s", etf.ticker, e, exc_info=True)
            continue

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
    title = get_clean(investment, "title")

    payoff_profile = None
    if hasattr(investment, "payoff_profile"):
        payoff_profile = clean_str(investment.payoff_profile)

    exchange_rate = None
    if hasattr(investment, "exchange_rate") and investment.exchange_rate is not None:
        try:
            exchange_rate = Decimal(str(investment.exchange_rate))
        except (ValueError, TypeError, Exception):
            logger.debug(f"Could not parse exchange_rate: {investment.exchange_rate}")

    # Compute holding_key: COALESCE(cusip, isin, name)
    cusip_clean = clean_str(investment.cusip)
    isin_clean = clean_str(isin)
    name_clean = clean_str(investment.name) or ""
    lei_clean = clean_str(investment.lei)
    cusip_for_xml = cusip_clean  # preserve original for xml_key lookup
    if cusip_clean in PLACEHOLDER_CUSIPS:
        cusip_clean = None
    holding_key = cusip_clean or isin_clean or name_clean
    if not holding_key:
        raw = f"{getattr(investment, 'balance', '')}|{getattr(investment, 'value_usd', '')}|{getattr(investment, 'units', '')}|{getattr(investment, 'asset_cat', '')}|{getattr(investment, 'country', '')}|{getattr(investment, 'title', '')}|{getattr(investment, 'payoff_profile', '')}"
        holding_key = f"__unknown_{hashlib.md5(raw.encode()).hexdigest()[:12]}__"
        logger.debug("Generated fallback holding_key for unnamed security in %s", etf.ticker)

    # Extract custom XML fields using holding key
    # Build XML holding key (name|cusip|lei as used in nport_xml.py)
    xml_key = f"{name_clean}|{cusip_for_xml or ''}|{lei_clean or ''}"
    custom_fields = xml_custom_fields.get(xml_key, {})
    liquidity_classification = custom_fields.get("liquidity_classification")

    # Warn if value may not be in USD
    if currency and currency.upper() != 'USD':
        logger.debug(
            "%s: holding '%s' reports currency %s but value stored as USD (value=%s, exchange_rate=%s)",
            etf.ticker, name_clean, currency,
            getattr(investment, 'value_usd', None),
            getattr(investment, 'exchange_rate', None),
        )

    return Holding(
        etf_id=etf.id,
        report_date=report_date,
        filing_date=filing_date,
        name=name_clean,
        cusip=cusip_clean,
        isin=isin_clean,
        ticker=clean_str(ticker),
        lei=lei_clean,
        balance=investment.balance,
        units=investment.units,
        value_usd=investment.value_usd,
        pct_val=investment.pct_value,
        asset_category=clean_str(investment.asset_category),
        issuer_category=clean_str(investment.issuer_category),
        country=clean_str(investment.investment_country),
        currency=currency,
        fair_value_level=fair_value_level,
        is_restricted=is_restricted,
        title=title,
        payoff_profile=payoff_profile,
        exchange_rate=exchange_rate,
        holding_key=holding_key,
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
        expiration_date = parse_date(fwd.settlement_date)
        # New fields for forward derivatives
        currency_sold = clean_str(fwd.currency_sold)
        currency_amt_sold = fwd.amount_sold
        settlement_date = parse_date(fwd.settlement_date)

        # Parent-level fields for forwards (deriv_addl_*)
        currency = get_clean(fwd, 'deriv_addl_currency')
        underlying_title = get_clean(fwd, 'deriv_addl_title')
        underlying_isin = get_clean(fwd, 'deriv_addl_isin')
        underlying_ticker = get_clean(fwd, 'deriv_addl_ticker')
        underlying_other_id = get_clean(fwd, 'deriv_addl_other_id')
        underlying_other_id_type = get_clean(fwd, 'deriv_addl_other_id_type')

    elif deriv_info.future_derivative:
        fut = deriv_info.future_derivative
        counterparty = fut.counterparty_name
        counterparty_lei = fut.counterparty_lei
        underlying_name = fut.reference_entity_name
        underlying_cusip = fut.reference_entity_cusip
        notional_value = fut.notional_amount
        expiration_date = parse_date(fut.expiration_date)

        # Parent-level fields for futures (reference_entity_* + payoff_profile)
        currency = get_clean(fut, 'currency')
        payoff_profile = get_clean(fut, 'payoff_profile')
        underlying_title = get_clean(fut, 'reference_entity_title')
        underlying_isin = get_clean(fut, 'reference_entity_isin')
        underlying_ticker = get_clean(fut, 'reference_entity_ticker')
        underlying_other_id = get_clean(fut, 'reference_entity_other_id')
        underlying_other_id_type = get_clean(fut, 'reference_entity_other_id_type')

    elif deriv_info.option_derivative:
        opt = deriv_info.option_derivative
        counterparty = opt.counterparty_name
        counterparty_lei = opt.counterparty_lei
        underlying_name = opt.reference_entity_name or opt.index_name
        underlying_cusip = opt.reference_entity_cusip
        if opt.share_number:
            notional_value = opt.share_number
        delta = parse_decimal(opt.delta)
        expiration_date = parse_date(opt.expiration_date)
        # New field for written options
        if opt.written_or_purchased == "W" and opt.share_number:
            written_notional_amt = opt.share_number

        # Parent-level fields for options (reference_entity_*)
        currency = get_clean(opt, 'currency_code')
        underlying_title = get_clean(opt, 'reference_entity_title')
        underlying_isin = get_clean(opt, 'reference_entity_isin')
        underlying_ticker = get_clean(opt, 'reference_entity_ticker')
        underlying_other_id = get_clean(opt, 'reference_entity_other_id')
        underlying_other_id_type = get_clean(opt, 'reference_entity_other_id_type')

    elif deriv_info.swap_derivative:
        swp = deriv_info.swap_derivative
        counterparty = swp.counterparty_name
        counterparty_lei = swp.counterparty_lei
        underlying_name = swp.deriv_addl_name or swp.reference_entity_name
        underlying_cusip = swp.deriv_addl_cusip or swp.reference_entity_cusip
        notional_value = swp.notional_amount
        expiration_date = parse_date(swp.termination_date)

        # Parent-level fields for swaps (deriv_addl_* or reference_entity_*)
        currency = get_clean(swp, 'currency_code')
        # Prefer deriv_addl_* fields, fallback to reference_entity_*
        underlying_title = clean_str(swp.deriv_addl_title) if hasattr(swp, 'deriv_addl_title') and swp.deriv_addl_title else (clean_str(swp.reference_entity_title) if hasattr(swp, 'reference_entity_title') else None)
        underlying_isin = clean_str(swp.deriv_addl_isin) if hasattr(swp, 'deriv_addl_isin') and swp.deriv_addl_isin else (clean_str(swp.reference_entity_isin) if hasattr(swp, 'reference_entity_isin') else None)
        underlying_ticker = clean_str(swp.deriv_addl_ticker) if hasattr(swp, 'deriv_addl_ticker') and swp.deriv_addl_ticker else (clean_str(swp.reference_entity_ticker) if hasattr(swp, 'reference_entity_ticker') else None)
        underlying_other_id = clean_str(swp.deriv_addl_other_id) if hasattr(swp, 'deriv_addl_other_id') and swp.deriv_addl_other_id else (clean_str(swp.reference_entity_other_id) if hasattr(swp, 'reference_entity_other_id') else None)
        underlying_other_id_type = clean_str(swp.deriv_addl_other_id_type) if hasattr(swp, 'deriv_addl_other_id_type') and swp.deriv_addl_other_id_type else (clean_str(swp.reference_entity_other_id_type) if hasattr(swp, 'reference_entity_other_id_type') else None)

    elif deriv_info.swaption_derivative:
        swo = deriv_info.swaption_derivative
        counterparty = swo.counterparty_name
        counterparty_lei = swo.counterparty_lei
        expiration_date = parse_date(swo.expiration_date)
        # New field for written swaptions
        if swo.written_or_purchased == "W" and swo.share_number:
            written_notional_amt = swo.share_number

        # Parent-level fields for swaptions (reference_entity_*)
        underlying_title = get_clean(swo, 'reference_entity_title')
        underlying_isin = get_clean(swo, 'reference_entity_isin')
        underlying_ticker = get_clean(swo, 'reference_entity_ticker')
        underlying_other_id = get_clean(swo, 'reference_entity_other_id')
        underlying_other_id_type = get_clean(swo, 'reference_entity_other_id_type')

    if expiration_date is None:
        expiration_date = NO_EXPIRATION_SENTINEL

    return Derivative(
        etf_id=etf.id,
        report_date=report_date,
        filing_date=filing_date,
        derivative_type=derivative_type,
        underlying_name=clean_str(underlying_name) or EMPTY_SENTINEL,
        underlying_cusip=clean_str(underlying_cusip),
        notional_value=notional_value,
        counterparty=clean_str(counterparty) or EMPTY_SENTINEL,
        counterparty_lei=clean_str(counterparty_lei),
        delta=delta,
        expiration_date=expiration_date,
        currency_sold=currency_sold,
        currency_amt_sold=currency_amt_sold,
        settlement_date=settlement_date,
        written_notional_amt=written_notional_amt,
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
    mat_date_raw = getattr(debt_sec, 'maturity_date', None)
    if mat_date_raw:
        if isinstance(mat_date_raw, str):
            if mat_date_raw != "N/A":
                maturity_date = parse_date(mat_date_raw)
        elif isinstance(mat_date_raw, datetime):
            maturity_date = mat_date_raw.date()
        elif isinstance(mat_date_raw, date):
            maturity_date = mat_date_raw

    # Extract coupon_kind
    raw_coupon_kind = getattr(debt_sec, 'coupon_kind', None)
    coupon_kind = clean_str(raw_coupon_kind) if raw_coupon_kind else None

    # Extract annualized_rate
    annualized_rate = getattr(debt_sec, 'annualized_rate', None)

    # Extract boolean fields
    raw_is_default = getattr(debt_sec, 'is_default', None)
    is_default = bool(raw_is_default) if raw_is_default is not None else False

    raw_in_arrears = getattr(debt_sec, 'are_instrument_payents_in_arrears', None)
    is_in_arrears = bool(raw_in_arrears) if raw_in_arrears is not None else False

    raw_paid_kind = getattr(debt_sec, 'is_paid_kind', None)
    is_paid_kind = bool(raw_paid_kind) if raw_paid_kind is not None else False

    raw_mandatory_conv = getattr(debt_sec, 'is_mandatory_convertible', None)
    is_mandatory_convertible = bool(raw_mandatory_conv) if raw_mandatory_conv is not None else False

    raw_contingent_conv = getattr(debt_sec, 'is_continuing_convertible', None)
    is_contingent_convertible = bool(raw_contingent_conv) if raw_contingent_conv is not None else False

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
    raw_cash_collateral = getattr(sec_lending, 'is_cash_collateral', None)
    is_cash_collateral = (raw_cash_collateral == "Y") if raw_cash_collateral is not None else False

    raw_non_cash_collateral = getattr(sec_lending, 'is_non_cash_collateral', None)
    is_non_cash_collateral = (raw_non_cash_collateral == "Y") if raw_non_cash_collateral is not None else False

    raw_loan_by_fund = getattr(sec_lending, 'is_loan_by_fund', None)
    is_loan_by_fund = (raw_loan_by_fund == "Y") if raw_loan_by_fund is not None else False

    return SecurityLending(
        is_cash_collateral=is_cash_collateral,
        is_non_cash_collateral=is_non_cash_collateral,
        is_loan_by_fund=is_loan_by_fund,
    )
