"""Parse N-CSR filings for performance data."""

import logging
from datetime import date
from typing import Optional

from edgar import Company
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from etf_pipeline.benchmark_labels import resolve_benchmark_label
from etf_pipeline.db import get_engine
from etf_pipeline.models import ETF, Performance
from etf_pipeline.parser_utils import (
    build_filing_date_filter,
    clear_and_log_cache,
    ensure_date,
    map_return_period,
    parse_date,
    parse_decimal,
    resolve_cik_list,
    run_parser_loop,
    update_processing_log,
    upsert_record,
)

logger = logging.getLogger(__name__)

_parse_decimal = parse_decimal


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



def _make_process_cik_ncsr(from_date: Optional[str] = None, to_date: Optional[str] = None):
    """Return a per-CIK processor for the parser loop."""
    date_filter = build_filing_date_filter(from_date, to_date)
    backfill_mode = date_filter is not None

    def _process_cik_ncsr(session: Session, cik: str) -> bool:
        MAX_FILINGS = 50  # Limit scan to 50 most recent filings per CIK

        try:
            # Build class_id -> ETF mapping from database first
            stmt = select(ETF).where(ETF.cik == cik)
            etfs = session.execute(stmt).scalars().all()

            class_id_to_etf = {}
            for etf in etfs:
                if etf.class_id:
                    class_id_to_etf[etf.class_id] = etf

            uit_fallback_etf = None
            if not class_id_to_etf:
                null_class_id_etfs = [e for e in etfs if not e.class_id]
                if len(null_class_id_etfs) == 1:
                    uit_fallback_etf = null_class_id_etfs[0]
                    logger.info(f"CIK {cik}: No ETFs with class_id; using UIT fallback ETF {uit_fallback_etf.ticker}")
                elif len(null_class_id_etfs) > 1:
                    logger.warning(f"CIK {cik}: No ETFs with class_id and multiple NULL class_id ETFs found — ambiguous, skipping")
                    return True
                else:
                    logger.warning(f"CIK {cik}: No ETFs with class_id found in database")
                    return True

            needed_class_ids = set(class_id_to_etf.keys())
            # Track (class_id, fiscal_year_end) pairs already processed -- first match wins
            satisfied = set()

            company = Company(cik)
            kwargs = {"form": "N-CSR"}
            if date_filter is not None:
                kwargs["filing_date"] = date_filter
            filings = company.get_filings(**kwargs)

            if not filings or (hasattr(filings, 'empty') and filings.empty):
                logger.info(f"CIK {cik}: No N-CSR filings found")
                return True  # Not an error, just no data

            processed_etfs = 0
            skipped_etfs = 0
            latest_filing_date = None

            num_filings = len(filings) if backfill_mode else min(len(filings), MAX_FILINGS)
            for filing_idx in range(num_filings):
                # In normal mode, stop early if all class_ids have been satisfied.
                # Skip this check for UIT fallback (needed_class_ids is empty but we still want to process).
                if not backfill_mode and needed_class_ids and not (needed_class_ids - {cid for cid, _ in satisfied}):
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
                    if uit_fallback_etf is None:
                        logger.warning(f"CIK {cik}: Filing {filing_idx} has no ClassAxis dimension")
                        continue
                    # UIT fallback: no ClassAxis means single-fund filing — add synthetic NULL column
                    df_filtered['dim_oef_ClassAxis'] = None

                # Extract benchmark data BEFORE per-class loop (benchmarks never have ClassAxis)
                benchmark_name = None
                benchmark_returns = {}

                has_benchmark_axis = 'dim_oef_BroadBasedIndexAxis' in df_filtered.columns
                if has_benchmark_axis:
                    # Filter for benchmark facts: BroadBasedIndexAxis is not null AND ClassAxis is null
                    benchmark_facts = df_filtered[
                        (df_filtered['dim_oef_BroadBasedIndexAxis'].notna()) &
                        (df_filtered['dim_oef_ClassAxis'].isna())
                    ].copy()

                    if not benchmark_facts.empty:
                        # Deduplicate benchmark facts by (concept, period_start, period_end, numeric_value)
                        # Keep first occurrence when multiple benchmark member IDs have identical values
                        benchmark_facts_deduped = benchmark_facts.drop_duplicates(
                            subset=['concept', 'period_start', 'period_end', 'numeric_value'],
                            keep='first'
                        )

                        # Extract benchmark name from the first benchmark
                        benchmark_axis_values = benchmark_facts_deduped['dim_oef_BroadBasedIndexAxis'].dropna().unique()
                        if len(benchmark_axis_values) > 0:
                            benchmark_name = _extract_benchmark_name(benchmark_axis_values[0])
                            resolve_benchmark_label(session, benchmark_name, xbrl_obj=xbrl_obj, cik=cik, filing_date=filing_date)

                        # Extract benchmark returns
                        for _, row in benchmark_facts_deduped.iterrows():
                            concept = row['concept']
                            numeric_value = row.get('numeric_value')

                            if concept == 'oef:AvgAnnlRtrPct':
                                period_start = row.get('period_start')
                                period_end = row.get('period_end')

                                if period_start and period_end:
                                    period_start = parse_date(period_start)
                                    period_end = parse_date(period_end)

                                    field_name = map_return_period(period_start, period_end)
                                    if field_name:
                                        # Map to benchmark field name
                                        benchmark_field = field_name.replace('return_', 'benchmark_return_')
                                        if benchmark_field in ['benchmark_return_1yr', 'benchmark_return_5yr', 'benchmark_return_10yr']:
                                            benchmark_returns[benchmark_field] = parse_decimal(numeric_value)

                        logger.debug(f"CIK {cik}: Filing {filing_idx} extracted benchmark: {benchmark_name}, returns: {benchmark_returns}")

                # Fallback to AdditionalIndexAxis if no benchmark found from BroadBasedIndexAxis
                if benchmark_name is None and 'dim_oef_AdditionalIndexAxis' in df_filtered.columns:
                    additional_facts = df_filtered[
                        (df_filtered['dim_oef_AdditionalIndexAxis'].notna()) &
                        (df_filtered['dim_oef_ClassAxis'].isna())
                    ].copy()

                    if not additional_facts.empty:
                        additional_facts_deduped = additional_facts.drop_duplicates(
                            subset=['concept', 'period_start', 'period_end', 'numeric_value'],
                            keep='first'
                        )

                        additional_axis_values = additional_facts_deduped['dim_oef_AdditionalIndexAxis'].dropna().unique()
                        if len(additional_axis_values) > 0:
                            benchmark_name = _extract_benchmark_name(additional_axis_values[0])
                            resolve_benchmark_label(session, benchmark_name, xbrl_obj=xbrl_obj, cik=cik, filing_date=filing_date)

                        for _, row in additional_facts_deduped.iterrows():
                            concept = row['concept']
                            numeric_value = row.get('numeric_value')

                            if concept == 'oef:AvgAnnlRtrPct':
                                period_start = row.get('period_start')
                                period_end = row.get('period_end')

                                if period_start and period_end:
                                    period_start = parse_date(period_start)
                                    period_end = parse_date(period_end)

                                    field_name = map_return_period(period_start, period_end)
                                    if field_name:
                                        benchmark_field = field_name.replace('return_', 'benchmark_return_')
                                        if benchmark_field in ['benchmark_return_1yr', 'benchmark_return_5yr', 'benchmark_return_10yr']:
                                            benchmark_returns[benchmark_field] = parse_decimal(numeric_value)

                        logger.debug(f"CIK {cik}: Filing {filing_idx} extracted benchmark (AdditionalIndex fallback): {benchmark_name}, returns: {benchmark_returns}")

                # Process each unique class_id in this filing's XBRL data
                for class_axis_value in df_filtered['dim_oef_ClassAxis'].dropna().unique():
                    class_id = _extract_class_id(class_axis_value)
                    if not class_id:
                        continue

                    # Look up ETF by class_id, fall back to UIT ETF if available
                    etf = class_id_to_etf.get(class_id)
                    if not etf:
                        if uit_fallback_etf is not None:
                            etf = uit_fallback_etf
                            logger.debug(f"CIK {cik}: class_id {class_id} not in database, using UIT fallback ETF {etf.ticker}")
                        else:
                            logger.debug(f"CIK {cik}: class_id {class_id} not found in database, skipping")
                            skipped_etfs += 1
                            continue

                    # Get all facts for this class (fund facts only - no benchmark axis)
                    class_facts = df_filtered[df_filtered['dim_oef_ClassAxis'] == class_axis_value].copy()
                    fund_facts = class_facts[class_facts['dim_oef_BroadBasedIndexAxis'].isna()].copy() if has_benchmark_axis else class_facts

                    # Extract fiscal_year_end from period_end (use the first one we find)
                    fiscal_year_end = None
                    if 'period_end' in fund_facts.columns:
                        period_ends = fund_facts['period_end'].dropna()
                        if not period_ends.empty:
                            fiscal_year_end = parse_date(period_ends.iloc[0])

                    if not fiscal_year_end:
                        logger.warning(f"CIK {cik}: No fiscal_year_end found for class_id {class_id}")
                        skipped_etfs += 1
                        continue

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
                                period_start = parse_date(period_start)
                                period_end = parse_date(period_end)

                                field_name = map_return_period(period_start, period_end)
                                if field_name:
                                    returns_data[field_name] = parse_decimal(numeric_value)

                        elif concept == 'oef:ExpenseRatioPct':
                            expense_ratio = parse_decimal(numeric_value)

                        elif concept == 'us-gaap:InvestmentCompanyPortfolioTurnover':
                            portfolio_turnover = parse_decimal(numeric_value)

                    # Upsert Performance record
                    data_kwargs = {
                        **returns_data,
                        "expense_ratio_actual": expense_ratio,
                        "portfolio_turnover": portfolio_turnover,
                    }
                    # Only include benchmark data if we actually extracted some
                    if benchmark_name is not None:
                        data_kwargs["benchmark_name"] = benchmark_name
                        data_kwargs.update(benchmark_returns)
                    upsert_record(
                        session,
                        Performance,
                        filter_kwargs={
                            "etf_id": etf.id,
                            "fiscal_year_end": fiscal_year_end,
                            "filing_date": filing_date,
                        },
                        data_kwargs=data_kwargs,
                    )
                    logger.debug(f"CIK {cik}: Upserted performance for {etf.ticker} (fiscal_year_end={fiscal_year_end}, filing_date={filing_date})")

                    satisfied.add(key)
                    processed_etfs += 1

                # UIT fallback: if no ClassAxis rows were found but we have a fallback ETF,
                # treat all non-benchmark facts as belonging to that ETF
                if uit_fallback_etf is not None and df_filtered['dim_oef_ClassAxis'].isna().all():
                    etf = uit_fallback_etf
                    fund_facts = df_filtered[df_filtered['dim_oef_BroadBasedIndexAxis'].isna()].copy() if has_benchmark_axis else df_filtered.copy()

                    fiscal_year_end = None
                    if 'period_end' in fund_facts.columns:
                        period_ends = fund_facts['period_end'].dropna()
                        if not period_ends.empty:
                            fiscal_year_end = parse_date(period_ends.iloc[0])

                    if fiscal_year_end:
                        key = (etf.class_id or etf.ticker, fiscal_year_end)
                        if key not in satisfied:
                            returns_data = {}
                            expense_ratio = None
                            portfolio_turnover = None

                            for _, row in fund_facts.iterrows():
                                concept = row['concept']
                                numeric_value = row.get('numeric_value')

                                if concept == 'oef:AvgAnnlRtrPct':
                                    period_start = row.get('period_start')
                                    period_end = row.get('period_end')

                                    if period_start and period_end:
                                        period_start = parse_date(period_start)
                                        period_end = parse_date(period_end)

                                        field_name = map_return_period(period_start, period_end)
                                        if field_name:
                                            returns_data[field_name] = parse_decimal(numeric_value)

                                elif concept == 'oef:ExpenseRatioPct':
                                    expense_ratio = parse_decimal(numeric_value)

                                elif concept == 'us-gaap:InvestmentCompanyPortfolioTurnover':
                                    portfolio_turnover = parse_decimal(numeric_value)

                            data_kwargs = {
                                **returns_data,
                                "expense_ratio_actual": expense_ratio,
                                "portfolio_turnover": portfolio_turnover,
                            }
                            if benchmark_name is not None:
                                data_kwargs["benchmark_name"] = benchmark_name
                                data_kwargs.update(benchmark_returns)
                            upsert_record(
                                session,
                                Performance,
                                filter_kwargs={
                                    "etf_id": etf.id,
                                    "fiscal_year_end": fiscal_year_end,
                                    "filing_date": filing_date,
                                },
                                data_kwargs=data_kwargs,
                            )
                            logger.info(f"CIK {cik}: Upserted UIT performance for {etf.ticker} (fiscal_year_end={fiscal_year_end}, filing_date={filing_date})")

                            satisfied.add(key)
                            processed_etfs += 1

                # In backfill mode, commit after each filing
                if backfill_mode:
                    update_processing_log(session, cik, "ncsr", filing_date)
                    session.commit()
                    logger.info(f"CIK {cik}: Processed filing {filing_idx + 1}/{num_filings} (filing_date={filing_date})")

            # Update processing log after successful processing (normal mode)
            if not backfill_mode and latest_filing_date is not None:
                latest_filing_date = ensure_date(latest_filing_date)
                update_processing_log(session, cik, "ncsr", latest_filing_date)

            session.commit()
            logger.info(f"CIK {cik}: Processed {processed_etfs} ETF(s), skipped {skipped_etfs}")
            return True

        except Exception as e:
            logger.error(f"CIK {cik}: Error processing N-CSR filing: {e}")
            session.rollback()
            return False

    return _process_cik_ncsr


def parse_ncsr(
    cik: Optional[str] = None,
    ciks: Optional[list[str]] = None,
    limit: Optional[int] = None,
    clear_cache: bool = True,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> None:
    """Parse N-CSR filings for performance data.

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
        cik_list = resolve_cik_list(session, cik=cik, ciks=ciks, limit=limit)

    if not cik_list:
        return

    process_fn = _make_process_cik_ncsr(from_date, to_date)
    run_parser_loop(cik_list, session_factory, process_fn, "ncsr")

    if clear_cache:
        clear_and_log_cache()
