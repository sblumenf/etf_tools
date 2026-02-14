"""Parse N-CSR filings for performance data."""

import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

import pandas as pd
from edgar import Company
from edgar.storage_management import clear_cache as edgar_clear_cache
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from etf_pipeline.db import get_engine
from etf_pipeline.models import ETF, Performance
from etf_pipeline.parser_utils import ensure_date, update_processing_log

logger = logging.getLogger(__name__)


def _extract_class_id(member_value: str) -> Optional[str]:
    """Extract class_id from ClassAxis member value.

    Examples:
        "ist:C000131291Member" -> "C000131291"
        "C000131291Member" -> "C000131291"
        None -> None

    Args:
        member_value: Value from dim_oef_ClassAxis column

    Returns:
        Extracted class_id or None
    """
    if not member_value or not isinstance(member_value, str):
        return None

    # Strip namespace prefix (e.g., "ist:")
    if ":" in member_value:
        member_value = member_value.split(":", 1)[1]

    # Strip "Member" suffix
    if member_value.endswith("Member"):
        member_value = member_value[:-6]

    return member_value if member_value else None


def _extract_benchmark_name(member_value: str) -> Optional[str]:
    """Extract benchmark name from BroadBasedIndexAxis member value.

    Examples:
        "ist:BloombergUSUniversalIndexMember" -> "BloombergUSUniversalIndexMember"
        "BloombergUSUniversalIndexMember" -> "BloombergUSUniversalIndexMember"
        None -> None

    Args:
        member_value: Value from dim_oef_BroadBasedIndexAxis column

    Returns:
        Raw member name (without namespace prefix) or None
    """
    if not member_value or not isinstance(member_value, str):
        return None

    # Strip namespace prefix (e.g., "ist:")
    if ":" in member_value:
        member_value = member_value.split(":", 1)[1]

    return member_value if member_value else None


def _calculate_period_years(period_start: date, period_end: date) -> Optional[float]:
    """Calculate the number of years between two dates.

    Args:
        period_start: Start date
        period_end: End date

    Returns:
        Number of years as float, or None if calculation fails
    """
    if not period_start or not period_end:
        return None

    days = (period_end - period_start).days
    return days / 365.25


def _map_return_period(period_start: date, period_end: date) -> Optional[str]:
    """Map date range to return period field name.

    Uses +/- 30 day tolerance for period matching.

    Args:
        period_start: Period start date
        period_end: Period end date

    Returns:
        One of: "return_1yr", "return_5yr", "return_10yr", "return_since_inception"
        or None if dates are invalid
    """
    years = _calculate_period_years(period_start, period_end)
    if years is None:
        return None

    # Allow +/- 30 days when matching return periods (1yr, 5yr, 10yr)
    tolerance = 30 / 365.25

    if abs(years - 1) <= tolerance:
        return "return_1yr"
    elif abs(years - 5) <= tolerance:
        return "return_5yr"
    elif abs(years - 10) <= tolerance:
        return "return_10yr"
    else:
        return "return_since_inception"


def _parse_decimal(value) -> Optional[Decimal]:
    """Parse value to Decimal, handling None and various types.

    Args:
        value: Value to parse (can be Decimal, float, str, int, or None)

    Returns:
        Decimal or None
    """
    if value is None:
        return None

    if isinstance(value, Decimal):
        return value

    try:
        return Decimal(str(value))
    except (ValueError, TypeError, InvalidOperation):
        return None


def _process_cik_ncsr(session: Session, cik: str) -> bool:
    """Process N-CSR filings for a single CIK.

    Iterates through multiple recent filings to cover all fund series
    under this CIK (e.g., Vanguard files separate N-CSRs per fund series).

    Args:
        session: SQLAlchemy session
        cik: CIK string (zero-padded to 10 digits)

    Returns:
        True if successful, False otherwise
    """
    MAX_FILINGS = 10  # Limit scan to 10 most recent filings per CIK

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
        # Track (class_id, fiscal_year_end) pairs already processed -- first match wins
        satisfied = set()

        company = Company(cik)
        filings = company.get_filings(form="N-CSR")

        if not filings or (hasattr(filings, 'empty') and filings.empty):
            logger.info(f"CIK {cik}: No N-CSR filings found")
            return True  # Not an error, just no data

        processed_etfs = 0
        skipped_etfs = 0
        latest_filing_date = None

        num_filings = min(len(filings), MAX_FILINGS)
        for filing_idx in range(num_filings):
            # Stop early if all class_ids have been satisfied
            if not (needed_class_ids - {cid for cid, _ in satisfied}):
                logger.debug(f"CIK {cik}: All class_ids satisfied after {filing_idx} filing(s)")
                break

            filing = filings[filing_idx]
            filing_date = ensure_date(filing.filing_date)

            # Track the latest filing date
            if latest_filing_date is None or filing_date > latest_filing_date:
                latest_filing_date = filing_date

            # Check if it's inline XBRL
            if not filing.is_inline_xbrl:
                logger.warning(f"CIK {cik}: Filing {filing_idx} is not inline XBRL, skipping")
                continue

            # Get XBRL data
            try:
                xbrl_obj = filing.xbrl()
                if xbrl_obj is None:
                    logger.warning(f"CIK {cik}: Filing {filing_idx} failed to parse XBRL, skipping")
                    continue

                df = xbrl_obj.facts.to_dataframe()
            except Exception as e:
                logger.warning(f"CIK {cik}: Filing {filing_idx} XBRL extraction failed: {e}")
                continue

            if df.empty:
                logger.debug(f"CIK {cik}: Filing {filing_idx} XBRL DataFrame is empty")
                continue

            # Filter for OEF concepts we care about
            target_concepts = [
                "oef:AvgAnnlRtrPct",
                "oef:ExpenseRatioPct",
                "us-gaap:InvestmentCompanyPortfolioTurnover"
            ]

            df_filtered = df[df['concept'].isin(target_concepts)].copy()

            if df_filtered.empty:
                logger.debug(f"CIK {cik}: Filing {filing_idx} has no OEF performance concepts")
                continue

            if 'dim_oef_ClassAxis' not in df_filtered.columns:
                logger.warning(f"CIK {cik}: Filing {filing_idx} has no ClassAxis dimension")
                continue

            # Process each unique class_id in this filing's XBRL data
            for class_axis_value in df_filtered['dim_oef_ClassAxis'].dropna().unique():
                class_id = _extract_class_id(class_axis_value)
                if not class_id:
                    continue

                # Look up ETF by class_id
                etf = class_id_to_etf.get(class_id)
                if not etf:
                    logger.debug(f"CIK {cik}: class_id {class_id} not found in database, skipping")
                    skipped_etfs += 1
                    continue

                # Get all facts for this class
                class_facts = df_filtered[df_filtered['dim_oef_ClassAxis'] == class_axis_value].copy()

                # Separate fund facts from benchmark facts
                has_benchmark_axis = 'dim_oef_BroadBasedIndexAxis' in class_facts.columns
                if has_benchmark_axis:
                    fund_facts = class_facts[class_facts['dim_oef_BroadBasedIndexAxis'].isna()].copy()
                    benchmark_facts = class_facts[class_facts['dim_oef_BroadBasedIndexAxis'].notna()].copy()
                else:
                    fund_facts = class_facts
                    benchmark_facts = pd.DataFrame()

                # Extract fiscal_year_end from period_end (use the first one we find)
                fiscal_year_end = None
                if 'period_end' in fund_facts.columns:
                    period_ends = fund_facts['period_end'].dropna()
                    if not period_ends.empty:
                        first_period_end = period_ends.iloc[0]
                        if isinstance(first_period_end, str):
                            fiscal_year_end = datetime.strptime(first_period_end, "%Y-%m-%d").date()
                        elif isinstance(first_period_end, datetime):
                            fiscal_year_end = first_period_end.date()
                        elif hasattr(first_period_end, 'date'):
                            fiscal_year_end = first_period_end.date()
                        else:
                            fiscal_year_end = first_period_end

                if not fiscal_year_end:
                    logger.warning(f"CIK {cik}: No fiscal_year_end found for class_id {class_id}")
                    skipped_etfs += 1
                    continue

                # Final sanity check: ensure fiscal_year_end is a date object
                if isinstance(fiscal_year_end, datetime):
                    fiscal_year_end = fiscal_year_end.date()

                # Skip if this (class_id, fiscal_year_end) was already processed
                key = (class_id, fiscal_year_end)
                if key in satisfied:
                    logger.debug(f"CIK {cik}: class_id {class_id} fiscal_year_end {fiscal_year_end} already processed, skipping")
                    continue

                # Extract fund returns by period
                returns_data = {}
                expense_ratio = None
                portfolio_turnover = None

                for _, row in fund_facts.iterrows():
                    concept = row['concept']
                    numeric_value = row.get('numeric_value')

                    if concept == 'oef:AvgAnnlRtrPct':
                        # Map period to field name
                        period_start = row.get('period_start')
                        period_end = row.get('period_end')

                        if period_start and period_end:
                            # Convert to date objects if needed
                            if isinstance(period_start, str):
                                period_start = datetime.strptime(period_start, "%Y-%m-%d").date()
                            elif isinstance(period_start, datetime):
                                period_start = period_start.date()
                            elif hasattr(period_start, 'date'):
                                period_start = period_start.date()

                            if isinstance(period_end, str):
                                period_end = datetime.strptime(period_end, "%Y-%m-%d").date()
                            elif isinstance(period_end, datetime):
                                period_end = period_end.date()
                            elif hasattr(period_end, 'date'):
                                period_end = period_end.date()

                            field_name = _map_return_period(period_start, period_end)
                            if field_name:
                                returns_data[field_name] = _parse_decimal(numeric_value)

                    elif concept == 'oef:ExpenseRatioPct':
                        expense_ratio = _parse_decimal(numeric_value)

                    elif concept == 'us-gaap:InvestmentCompanyPortfolioTurnover':
                        portfolio_turnover = _parse_decimal(numeric_value)

                # Extract benchmark data (if any)
                benchmark_name = None
                benchmark_returns = {}

                if not benchmark_facts.empty:
                    # Extract benchmark name from the first benchmark
                    benchmark_axis_values = benchmark_facts['dim_oef_BroadBasedIndexAxis'].dropna().unique()
                    if len(benchmark_axis_values) > 0:
                        benchmark_name = _extract_benchmark_name(benchmark_axis_values[0])

                    # Extract benchmark returns
                    for _, row in benchmark_facts.iterrows():
                        concept = row['concept']
                        numeric_value = row.get('numeric_value')

                        if concept == 'oef:AvgAnnlRtrPct':
                            period_start = row.get('period_start')
                            period_end = row.get('period_end')

                            if period_start and period_end:
                                # Convert to date objects if needed
                                if isinstance(period_start, str):
                                    period_start = datetime.strptime(period_start, "%Y-%m-%d").date()
                                elif isinstance(period_start, datetime):
                                    period_start = period_start.date()
                                elif hasattr(period_start, 'date'):
                                    period_start = period_start.date()

                                if isinstance(period_end, str):
                                    period_end = datetime.strptime(period_end, "%Y-%m-%d").date()
                                elif isinstance(period_end, datetime):
                                    period_end = period_end.date()
                                elif hasattr(period_end, 'date'):
                                    period_end = period_end.date()

                                field_name = _map_return_period(period_start, period_end)
                                if field_name:
                                    # Map to benchmark field name
                                    benchmark_field = field_name.replace('return_', 'benchmark_return_')
                                    if benchmark_field in ['benchmark_return_1yr', 'benchmark_return_5yr', 'benchmark_return_10yr']:
                                        benchmark_returns[benchmark_field] = _parse_decimal(numeric_value)

                # Upsert Performance record
                stmt = select(Performance).where(
                    Performance.etf_id == etf.id,
                    Performance.fiscal_year_end == fiscal_year_end,
                    Performance.filing_date == filing_date
                )
                existing = session.execute(stmt).scalar_one_or_none()

                if existing:
                    # Update existing record
                    for field, value in returns_data.items():
                        setattr(existing, field, value)
                    existing.expense_ratio_actual = expense_ratio
                    existing.portfolio_turnover = portfolio_turnover
                    existing.benchmark_name = benchmark_name
                    for field, value in benchmark_returns.items():
                        setattr(existing, field, value)
                    logger.debug(f"CIK {cik}: Updated performance for {etf.ticker} (fiscal_year_end={fiscal_year_end}, filing_date={filing_date})")
                else:
                    # Insert new record
                    new_perf = Performance(
                        etf_id=etf.id,
                        fiscal_year_end=fiscal_year_end,
                        filing_date=filing_date,
                        return_1yr=returns_data.get('return_1yr'),
                        return_5yr=returns_data.get('return_5yr'),
                        return_10yr=returns_data.get('return_10yr'),
                        return_since_inception=returns_data.get('return_since_inception'),
                        expense_ratio_actual=expense_ratio,
                        portfolio_turnover=portfolio_turnover,
                        benchmark_name=benchmark_name,
                        benchmark_return_1yr=benchmark_returns.get('benchmark_return_1yr'),
                        benchmark_return_5yr=benchmark_returns.get('benchmark_return_5yr'),
                        benchmark_return_10yr=benchmark_returns.get('benchmark_return_10yr'),
                    )
                    session.add(new_perf)
                    logger.debug(f"CIK {cik}: Inserted performance for {etf.ticker} (fiscal_year_end={fiscal_year_end}, filing_date={filing_date})")

                satisfied.add(key)
                processed_etfs += 1

        # Update processing log after successful processing
        if latest_filing_date is not None:
            latest_filing_date = ensure_date(latest_filing_date)
            update_processing_log(session, cik, "ncsr", latest_filing_date)

        session.commit()
        logger.info(f"CIK {cik}: Processed {processed_etfs} ETF(s), skipped {skipped_etfs}")
        return True

    except Exception as e:
        logger.error(f"CIK {cik}: Error processing N-CSR filing: {e}")
        session.rollback()
        return False


def parse_ncsr(
    cik: Optional[str] = None,
    ciks: Optional[list[str]] = None,
    limit: Optional[int] = None,
    clear_cache: bool = True,
) -> None:
    """Parse N-CSR filings for performance data.

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
            if _process_cik_ncsr(session, cik_str):
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
