"""Parse NPORT-P filings for holdings and derivatives data."""

import logging
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
from etf_pipeline.models import Derivative, ETF, Holding
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
            logger.warning(f"Failed to process CIK {cik_str}: {e}")

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
        dict: Mapping of series_id -> (fund_report, report_date, filing_date)
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
    latest_filings = by_date[latest_date]

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
            series_map[series_id] = (fund_report, report_date, filing_date)

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
    latest_filing_date = max(filing_date for _, _, filing_date in series_map.values()) if series_map else None

    with session_factory() as session:
        stmt = select(ETF).where(ETF.cik == cik)
        etfs = session.execute(stmt).scalars().all()

        # Collect etf_ids and report_dates that need checking
        etf_report_pairs = []
        for etf in etfs:
            if etf.series_id in series_map:
                _, report_date, _ = series_map[etf.series_id]
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
            fund_report, report_date, filing_date = series_map[etf.series_id]
            _process_etf(session, etf, fund_report, report_date, filing_date)
            processed += 1

        # Update processing log after successful processing
        if latest_filing_date is not None:
            latest_filing_date = ensure_date(latest_filing_date)
            update_processing_log(session, cik, "nport", latest_filing_date)

        session.commit()

    logger.info(f"CIK {cik}: Processed {processed}/{etf_count} ETF(s)")


def _process_etf(
    session: Session, etf: ETF, fund_report: FundReport, report_date, filing_date
) -> None:
    """Process a single ETF: extract and insert holdings and derivatives."""
    holdings_count = 0
    for investment in fund_report.non_derivatives:
        holding = _map_investment_to_holding(etf, investment, report_date, filing_date)
        session.add(holding)
        holdings_count += 1

    derivatives_count = 0
    for investment in fund_report.derivatives:
        derivative = _map_investment_to_derivative(etf, investment, report_date, filing_date)
        if derivative:
            session.add(derivative)
            derivatives_count += 1

    etf.last_fetched = datetime.now()

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

    return Holding(
        etf_id=etf.id,
        report_date=report_date,
        filing_date=filing_date,
        name=_clean_str(investment.name) or "",
        cusip=_clean_str(investment.cusip),
        isin=_clean_str(isin),
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
