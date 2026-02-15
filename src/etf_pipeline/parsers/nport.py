"""Parse NPORT-P filings for holdings and derivatives data."""

import logging
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from edgar import Company
from edgar.funds.reports import FundReport
from edgar.storage_management import clear_cache as edgar_clear_cache
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, sessionmaker

from etf_pipeline.db import get_engine
from etf_pipeline.models import (
    DebtSecurityDetail,
    Derivative,
    ETF,
    FundSnapshot,
    Holding,
    NPORTMonthlyFlow,
    NPORTMonthlyReturn,
    SecurityLending,
)
from etf_pipeline.parser_utils import ensure_date, update_processing_log

logger = logging.getLogger(__name__)


def _clean_str(val):
    """Return None if val is None or 'N/A', else str(val)."""
    if val is None or str(val).strip() == "N/A":
        return None
    return str(val).strip() if val else None


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
            print("No ETFs found in database. Run 'load-etfs' first.")
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
                print(f"None of the provided CIKs found in database: {ciks}")
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
                print(f"CIK {cik} not found in database")
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

    print(f"\nSummary: {succeeded} CIKs succeeded, {failed} CIKs failed")
    logger.info(f"Summary: {succeeded} CIKs succeeded, {failed} CIKs failed")

    if clear_cache:
        result = edgar_clear_cache(dry_run=False)
        files_deleted = result.get('files_deleted', 0)
        bytes_freed = result.get('bytes_freed', 0)
        mb_freed = bytes_freed / (1024 * 1024)
        logger.info(f"Cache cleared: {files_deleted} files deleted, {mb_freed:.2f} MB freed")
        print(f"Cache cleared: {files_deleted} files deleted, {mb_freed:.2f} MB freed")


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
        xml_content = filing.xml
        if not xml_content:
            logger.debug(f"No XML content found in filing for etf_id={etf_id}")
            return monthly_returns

        # Parse XML
        root = ET.fromstring(xml_content)

        # Find monthlyTotReturns element
        # Path: /edgarSubmission/formData/fundinfo/returnInfo/monthlyTotReturns
        ns = {'edgar': 'http://www.sec.gov/edgar/nport'}

        # Try without namespace first
        monthly_tot_returns = root.find('.//monthlyTotReturns')

        # If not found, try with namespace
        if monthly_tot_returns is None:
            monthly_tot_returns = root.find('.//edgar:monthlyTotReturns', ns)

        # If still not found, try different path variations
        if monthly_tot_returns is None:
            # Try full path
            for form_data in root.iter('formData'):
                for fund_info in form_data.iter('fundinfo'):
                    for return_info in fund_info.iter('returnInfo'):
                        monthly_tot_returns = return_info.find('monthlyTotReturns')
                        if monthly_tot_returns is not None:
                            break

        if monthly_tot_returns is None:
            logger.debug(f"No monthlyTotReturns element found in NPORT XML for etf_id={etf_id}")
            return monthly_returns

        # Extract each monthlyTotReturn child element
        for monthly_return_elem in monthly_tot_returns.findall('monthlyTotReturn'):
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
        xml_content = filing.xml
        if not xml_content:
            logger.debug(f"No XML content found in filing for etf_id={etf_id}")
            return monthly_flows

        # Parse XML
        root = ET.fromstring(xml_content)

        # Find monthlyTotReturns element (same location as returns)
        # Path: /edgarSubmission/formData/fundinfo/returnInfo/monthlyTotReturns
        ns = {'edgar': 'http://www.sec.gov/edgar/nport'}

        # Try without namespace first
        monthly_tot_returns = root.find('.//monthlyTotReturns')

        # If not found, try with namespace
        if monthly_tot_returns is None:
            monthly_tot_returns = root.find('.//edgar:monthlyTotReturns', ns)

        # If still not found, try different path variations
        if monthly_tot_returns is None:
            # Try full path
            for form_data in root.iter('formData'):
                for fund_info in form_data.iter('fundinfo'):
                    for return_info in fund_info.iter('returnInfo'):
                        monthly_tot_returns = return_info.find('monthlyTotReturns')
                        if monthly_tot_returns is not None:
                            break

        if monthly_tot_returns is None:
            logger.debug(f"No monthlyTotReturns element found in NPORT XML for etf_id={etf_id}")
            return monthly_flows

        # Extract each monthlyTotReturn child element
        for monthly_return_elem in monthly_tot_returns.findall('monthlyTotReturn'):
            # Extract flow attributes
            sales_amt_1 = monthly_return_elem.get('salesAmt1')
            redemption_amt_1 = monthly_return_elem.get('redemptionAmt1')
            reinvest_amt_1 = monthly_return_elem.get('reinvestAmt1')
            sales_amt_2 = monthly_return_elem.get('salesAmt2')
            redemption_amt_2 = monthly_return_elem.get('redemptionAmt2')
            reinvest_amt_2 = monthly_return_elem.get('reinvestAmt2')
            sales_amt_3 = monthly_return_elem.get('salesAmt3')
            redemption_amt_3 = monthly_return_elem.get('redemptionAmt3')
            reinvest_amt_3 = monthly_return_elem.get('reinvestAmt3')
            class_id = monthly_return_elem.get('classId')

            # Convert "N/A" to None, otherwise convert to Decimal
            def parse_flow(val):
                if val is None or val.strip().upper() == "N/A":
                    return None
                try:
                    return Decimal(val)
                except (ValueError, Exception) as e:
                    logger.warning(f"Could not parse flow value '{val}': {e}")
                    return None

            month_1_sales = parse_flow(sales_amt_1)
            month_1_redemptions = parse_flow(redemption_amt_1)
            month_1_reinvestments = parse_flow(reinvest_amt_1)
            month_2_sales = parse_flow(sales_amt_2)
            month_2_redemptions = parse_flow(redemption_amt_2)
            month_2_reinvestments = parse_flow(reinvest_amt_2)
            month_3_sales = parse_flow(sales_amt_3)
            month_3_redemptions = parse_flow(redemption_amt_3)
            month_3_reinvestments = parse_flow(reinvest_amt_3)

            # Create NPORTMonthlyFlow object
            monthly_flow = NPORTMonthlyFlow(
                etf_id=etf_id,
                report_date=report_date,
                filing_date=filing_date,
                class_id=class_id if class_id else None,
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
            logger.info(f"Extracted {len(monthly_flows)} monthly flow entries for etf_id={etf_id}")

    except Exception as e:
        logger.warning(f"Failed to extract monthly flows for etf_id={etf_id}: {e}")

    return monthly_flows


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

    holdings_count = 0
    seen_holding_keys = set()
    for investment in fund_report.non_derivatives:
        holding = _map_investment_to_holding(etf, investment, report_date, filing_date)
        if holding.holding_key in seen_holding_keys:
            logger.warning(f"ETF {etf.ticker}: Skipping duplicate holding_key {holding.holding_key} in NPORT filing")
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
    for investment in fund_report.derivatives:
        derivative = _map_investment_to_derivative(etf, investment, report_date, filing_date)
        if derivative:
            deriv_key = (derivative.derivative_type, derivative.underlying_name)
            if deriv_key != (None, None) and deriv_key in seen_derivative_keys:
                logger.warning(f"ETF {etf.ticker}: Skipping duplicate derivative {deriv_key} in NPORT filing")
                continue
            if deriv_key != (None, None):
                seen_derivative_keys.add(deriv_key)
            session.add(derivative)
            derivatives_count += 1

    logger.info(
        f"ETF {etf.ticker}: Inserted {holdings_count} holdings, {derivatives_count} derivatives for {report_date}"
    )


def _map_investment_to_holding(etf: ETF, investment, report_date, filing_date) -> Holding:
    """Map an InvestmentOrSecurity to a Holding model instance."""
    identifiers = investment.identifiers

    isin = None
    ticker = None
    currency = None

    if identifiers:
        isin = identifiers.isin
        if hasattr(identifiers, "other") and identifiers.other and isinstance(identifiers.other, dict):
            for desc, value in identifiers.other.items():
                if desc and "currency" in desc.lower():
                    currency = value

    ticker = investment.ticker

    if not currency and hasattr(investment, "currency_code") and investment.currency_code:
        currency = investment.currency_code

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
    holding_key = cusip_clean or isin_clean or name_clean

    return Holding(
        etf_id=etf.id,
        report_date=report_date,
        filing_date=filing_date,
        name=name_clean,
        cusip=cusip_clean,
        isin=isin_clean,
        ticker=_clean_str(ticker),
        lei=_clean_str(investment.lei),
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

    elif deriv_info.future_derivative:
        fut = deriv_info.future_derivative
        counterparty = fut.counterparty_name
        counterparty_lei = fut.counterparty_lei
        underlying_name = fut.reference_entity_name
        underlying_cusip = fut.reference_entity_cusip
        notional_value = fut.notional_amount
        expiration_date = _parse_date(fut.expiration_date)

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

    elif deriv_info.swap_derivative:
        swp = deriv_info.swap_derivative
        counterparty = swp.counterparty_name
        counterparty_lei = swp.counterparty_lei
        underlying_name = swp.deriv_addl_name or swp.reference_entity_name
        underlying_cusip = swp.deriv_addl_cusip or swp.reference_entity_cusip
        notional_value = swp.notional_amount
        expiration_date = _parse_date(swp.termination_date)

    elif deriv_info.swaption_derivative:
        swo = deriv_info.swaption_derivative
        counterparty = swo.counterparty_name
        counterparty_lei = swo.counterparty_lei
        expiration_date = _parse_date(swo.expiration_date)
        # New field for written swaptions
        if swo.written_or_purchased == "W" and swo.share_number:
            written_notional_amt = swo.share_number

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
    except (ValueError, TypeError):
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
            maturity_date = _parse_date(debt_sec.maturity_date)
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
            is_cash_collateral = bool(sec_lending.is_cash_collateral)
    except (AttributeError, TypeError):
        pass

    is_non_cash_collateral = False
    try:
        if hasattr(sec_lending, 'is_non_cash_collateral') and sec_lending.is_non_cash_collateral is not None:
            is_non_cash_collateral = bool(sec_lending.is_non_cash_collateral)
    except (AttributeError, TypeError):
        pass

    is_loan_by_fund = False
    try:
        if hasattr(sec_lending, 'is_loan_by_fund') and sec_lending.is_loan_by_fund is not None:
            is_loan_by_fund = bool(sec_lending.is_loan_by_fund)
    except (AttributeError, TypeError):
        pass

    return SecurityLending(
        is_cash_collateral=is_cash_collateral,
        is_non_cash_collateral=is_non_cash_collateral,
        is_loan_by_fund=is_loan_by_fund,
    )
