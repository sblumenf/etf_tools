"""Parse N-CSR filings for performance data."""

import logging
from datetime import date
from typing import Optional

import pandas as pd
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
    normalize_return_value,
    parse_date,
    parse_decimal,
    resolve_cik_list,
    run_parser_loop,
    update_processing_log,
    upsert_record,
)

logger = logging.getLogger(__name__)

_NON_BENCHMARK_MEMBERS = {
    "AfterTaxesOnDistributionsMember",
    "AfterTaxesOnDistributionsAndSalesMember",
}

_OEF_CONCEPTS = [
    "oef:AvgAnnlRtrPct",
    "oef:ExpenseRatioPct",
    "oef:PortfolioTurnoverRate",
    "us-gaap:InvestmentCompanyPortfolioTurnover",
]
_RR_CONCEPTS = [
    "rr:AverageAnnualReturnYear01",
    "rr:AverageAnnualReturnYear05",
    "rr:AverageAnnualReturnYear10",
    "rr:AverageAnnualReturnSinceInception",
    "rr:ExpensesOverAssets",
    "rr:PortfolioTurnoverRate",
]


def _detect_taxonomy(df: pd.DataFrame) -> Optional[str]:
    """Detect whether filing uses 'oef' or 'rr' XBRL taxonomy."""
    for concept in df['concept'].dropna().unique():
        if concept.startswith('oef:'):
            return 'oef'
        if concept.startswith('rr:'):
            return 'rr'
    return None


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


def _extract_benchmark_returns_from_facts(facts_df):
    extracted = {}
    for _, row in facts_df.iterrows():
        concept = row['concept']
        numeric_value = row.get('numeric_value')
        if concept == 'oef:AvgAnnlRtrPct':
            period_start = row.get('period_start')
            period_end = row.get('period_end')
            if period_start and period_end:
                ps = parse_date(period_start)
                pe = parse_date(period_end)
                field_name = map_return_period(ps, pe)
                if field_name:
                    bfield = field_name.replace('return_', 'benchmark_return_')
                    if bfield in ['benchmark_return_1yr', 'benchmark_return_5yr', 'benchmark_return_10yr']:
                        extracted[bfield] = normalize_return_value(parse_decimal(numeric_value))
        elif concept == 'rr:AverageAnnualReturnYear01':
            extracted['benchmark_return_1yr'] = normalize_return_value(parse_decimal(numeric_value))
        elif concept == 'rr:AverageAnnualReturnYear05':
            extracted['benchmark_return_5yr'] = normalize_return_value(parse_decimal(numeric_value))
        elif concept == 'rr:AverageAnnualReturnYear10':
            extracted['benchmark_return_10yr'] = normalize_return_value(parse_decimal(numeric_value))
    return extracted


def _extract_fund_data(fund_facts):
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
                    returns_data[field_name] = normalize_return_value(parse_decimal(numeric_value))

        elif concept == 'rr:AverageAnnualReturnYear01':
            returns_data['return_1yr'] = normalize_return_value(parse_decimal(numeric_value))
        elif concept == 'rr:AverageAnnualReturnYear05':
            returns_data['return_5yr'] = normalize_return_value(parse_decimal(numeric_value))
        elif concept == 'rr:AverageAnnualReturnYear10':
            returns_data['return_10yr'] = normalize_return_value(parse_decimal(numeric_value))
        elif concept == 'rr:AverageAnnualReturnSinceInception':
            returns_data['return_since_inception'] = normalize_return_value(parse_decimal(numeric_value))

        elif concept == 'oef:ExpenseRatioPct':
            expense_ratio = parse_decimal(numeric_value)
        elif concept == 'rr:ExpensesOverAssets':
            expense_ratio = parse_decimal(numeric_value)

        elif concept in ('us-gaap:InvestmentCompanyPortfolioTurnover', 'oef:PortfolioTurnoverRate', 'rr:PortfolioTurnoverRate'):
            portfolio_turnover = parse_decimal(numeric_value)

    return returns_data, expense_ratio, portfolio_turnover


def _build_class_benchmark_map(df_filtered, class_axis_col):
    """Build a mapping from class_id to (benchmark_name, benchmark_facts_df).

    Uses document ordering: in XBRL facts, a class's fund rows are immediately
    followed by that class's benchmark rows. We scan rows in order, tracking the
    current class_id from ClassAxis. When we hit a BroadBasedIndexAxis row
    (which has no ClassAxis), we assign it to the most recently seen class.
    """
    class_to_benchmark = {}
    current_class_id = None
    current_benchmark_name = None
    current_benchmark_source = None  # 'broad' or 'additional'
    benchmark_rows = []

    broad_col = 'dim_oef_BroadBasedIndexAxis'
    additional_col = 'dim_oef_AdditionalIndexAxis'
    has_broad = broad_col in df_filtered.columns
    has_additional = additional_col in df_filtered.columns

    def _flush_benchmark():
        nonlocal current_class_id, current_benchmark_name, current_benchmark_source, benchmark_rows
        if current_class_id and current_benchmark_name and benchmark_rows:
            if current_class_id not in class_to_benchmark:
                bm_df = pd.DataFrame(benchmark_rows)
                class_to_benchmark[current_class_id] = (current_benchmark_name, bm_df)
        current_benchmark_name = None
        current_benchmark_source = None
        benchmark_rows = []

    for idx, row in df_filtered.iterrows():
        class_val = row.get(class_axis_col)
        broad_val = row.get(broad_col) if has_broad else None
        additional_val = row.get(additional_col) if has_additional else None

        # Row has a ClassAxis value -> it's a fund fact
        if pd.notna(class_val):
            # If we were collecting benchmark rows for a previous class, flush them
            if current_benchmark_name:
                _flush_benchmark()
            current_class_id = _extract_class_id(class_val)

        # Row has a BroadBasedIndexAxis value -> it's a broad-based benchmark fact (highest priority)
        elif pd.notna(broad_val) if has_broad else False:
            bm_name = _extract_benchmark_name(broad_val)
            if bm_name:
                if current_benchmark_name is None:
                    current_benchmark_name = bm_name
                    current_benchmark_source = 'broad'
                # Only append if this row matches the chosen source axis
                if current_benchmark_source == 'broad':
                    benchmark_rows.append(row.to_dict())

        # Row has an AdditionalIndexAxis value -> fallback benchmark (only if no broad-based found)
        elif pd.notna(additional_val) if has_additional else False:
            bm_name = _extract_benchmark_name(additional_val)
            if bm_name:
                if current_benchmark_name is None:
                    current_benchmark_name = bm_name
                    current_benchmark_source = 'additional'
                # Only append if this row matches the chosen source axis
                if current_benchmark_source == 'additional':
                    benchmark_rows.append(row.to_dict())

    # Flush last class
    _flush_benchmark()

    # Warn about orphaned benchmark rows (benchmark facts before any class facts)
    if benchmark_rows and current_class_id is None:
        logger.warning("Benchmark rows found before any class rows in document order — no class to assign them to")

    return class_to_benchmark


def _extract_benchmark_from_axis(df, axis_col):
    """Extract benchmark name and facts from a DataFrame filtered by an axis column."""
    bm_facts = df[df[axis_col].notna()]
    if bm_facts.empty:
        return None, pd.DataFrame()
    bm_facts_deduped = bm_facts.drop_duplicates(
        subset=['concept', 'period_start', 'period_end', 'numeric_value'],
        keep='first'
    )
    axis_vals = bm_facts_deduped[axis_col].dropna().unique()
    bm_name = _extract_benchmark_name(axis_vals[0]) if len(axis_vals) > 0 else None
    return bm_name, bm_facts_deduped


def _upsert_performance_record(session, etf, fiscal_year_end, filing_date, returns_data, data_kwargs, cik, label=""):
    """Upsert a Performance record, guarding against overwriting existing returns with nulls."""
    if not returns_data:
        existing_with_returns = session.execute(
            select(Performance).where(
                Performance.etf_id == etf.id,
                Performance.fiscal_year_end == fiscal_year_end,
                (Performance.return_1yr.isnot(None))
                | (Performance.return_5yr.isnot(None))
                | (Performance.return_10yr.isnot(None))
                | (Performance.return_since_inception.isnot(None)),
            )
        ).scalar_one_or_none()
        if existing_with_returns is not None:
            if data_kwargs.get("expense_ratio_actual") is not None:
                existing_with_returns.expense_ratio_actual = data_kwargs["expense_ratio_actual"]
            if data_kwargs.get("portfolio_turnover") is not None:
                existing_with_returns.portfolio_turnover = data_kwargs["portfolio_turnover"]
            logger.debug(f"CIK {cik}: Skipped null-return upsert for {etf.ticker} {label}(fiscal_year_end={fiscal_year_end}); patched expense/turnover on existing row")
            return

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
    logger.debug(f"CIK {cik}: Upserted {label}performance for {etf.ticker} (fiscal_year_end={fiscal_year_end}, filing_date={filing_date})")


def _make_process_cik_ncsr(from_date: Optional[str] = None, to_date: Optional[str] = None):
    """Return a per-CIK processor for the parser loop."""
    date_filter = build_filing_date_filter(from_date, to_date)
    backfill_mode = date_filter is not None

    def _process_cik_ncsr(session: Session, cik: str) -> bool:
        MAX_FILINGS = 500  # Limit scan to 500 most recent filings per CIK

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

                # Detect taxonomy and build appropriate concept filter
                taxonomy = _detect_taxonomy(df)

                if taxonomy == 'oef':
                    target_concepts = _OEF_CONCEPTS
                elif taxonomy == 'rr':
                    target_concepts = _RR_CONCEPTS
                    logger.info(f"CIK {cik}: Filing {filing_idx} uses RR taxonomy")
                else:
                    target_concepts = _OEF_CONCEPTS + _RR_CONCEPTS

                df_filtered = df[df['concept'].isin(target_concepts)].copy()

                if df_filtered.empty:
                    logger.debug(f"CIK {cik}: Filing {filing_idx} has no performance concepts (taxonomy={taxonomy})")
                    continue

                # Determine which ClassAxis column to use
                if 'dim_oef_ClassAxis' in df_filtered.columns:
                    class_axis_col = 'dim_oef_ClassAxis'
                elif 'dim_rr_ProspectusShareClassAxis' in df_filtered.columns:
                    class_axis_col = 'dim_rr_ProspectusShareClassAxis'
                else:
                    if uit_fallback_etf is None:
                        logger.warning(f"CIK {cik}: Filing {filing_idx} has no ClassAxis dimension")
                        continue
                    # UIT fallback: no ClassAxis means single-fund filing — add synthetic NULL column
                    class_axis_col = 'dim_oef_ClassAxis'
                    df_filtered[class_axis_col] = None

                # Build per-class benchmark map using document ordering
                class_benchmark_map = _build_class_benchmark_map(df_filtered, class_axis_col)

                # Per-filing caches to avoid redundant resolve/extract calls
                resolved_benchmarks = set()
                benchmark_returns_cache = {}

                # Also check for RR PerformanceMeasure axis as fallback
                has_broad_based_axis = 'dim_oef_BroadBasedIndexAxis' in df_filtered.columns
                has_rr_perf_axis = 'dim_rr_PerformanceMeasureAxis' in df_filtered.columns
                rr_benchmark_name = None
                rr_benchmark_returns = {}
                if has_rr_perf_axis:
                    rr_benchmark_name, rr_benchmark_facts_deduped = _extract_benchmark_from_axis(
                        df_filtered, 'dim_rr_PerformanceMeasureAxis'
                    )
                    if rr_benchmark_name in _NON_BENCHMARK_MEMBERS:
                        rr_benchmark_name = None
                        rr_benchmark_facts_deduped = pd.DataFrame()
                    if rr_benchmark_name is not None:
                        rr_benchmark_returns = _extract_benchmark_returns_from_facts(rr_benchmark_facts_deduped)

                # Process each unique class_id in this filing's XBRL data
                for class_axis_value in df_filtered[class_axis_col].dropna().unique():
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
                    class_facts = df_filtered[df_filtered[class_axis_col] == class_axis_value]
                    if has_broad_based_axis:
                        fund_facts = class_facts[class_facts['dim_oef_BroadBasedIndexAxis'].isna()]
                    elif has_rr_perf_axis:
                        fund_facts = class_facts[class_facts['dim_rr_PerformanceMeasureAxis'].isna()]
                    else:
                        fund_facts = class_facts

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
                    returns_data, expense_ratio, portfolio_turnover = _extract_fund_data(fund_facts)

                    # Use per-class benchmark from document ordering, fall back to RR
                    benchmark_name = None
                    benchmark_returns = {}
                    if class_id in class_benchmark_map:
                        benchmark_name, bm_facts_df = class_benchmark_map[class_id]
                        if benchmark_name not in resolved_benchmarks:
                            resolve_benchmark_label(session, benchmark_name, xbrl_obj=xbrl_obj, cik=cik, filing_date=filing_date)
                            resolved_benchmarks.add(benchmark_name)
                        if benchmark_name not in benchmark_returns_cache:
                            benchmark_returns_cache[benchmark_name] = _extract_benchmark_returns_from_facts(bm_facts_df)
                        benchmark_returns = benchmark_returns_cache[benchmark_name]
                    elif rr_benchmark_name:
                        benchmark_name = rr_benchmark_name
                        if benchmark_name not in resolved_benchmarks:
                            resolve_benchmark_label(session, benchmark_name, xbrl_obj=xbrl_obj, cik=cik, filing_date=filing_date)
                            resolved_benchmarks.add(benchmark_name)
                        benchmark_returns = rr_benchmark_returns

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

                    _upsert_performance_record(
                        session, etf, fiscal_year_end, filing_date, returns_data, data_kwargs, cik
                    )

                    satisfied.add(key)
                    processed_etfs += 1

                # UIT fallback: if no ClassAxis rows were found but we have a fallback ETF,
                # treat all non-benchmark facts as belonging to that ETF
                if uit_fallback_etf is not None and df_filtered[class_axis_col].isna().all():
                    etf = uit_fallback_etf
                    if has_broad_based_axis:
                        fund_facts = df_filtered[df_filtered['dim_oef_BroadBasedIndexAxis'].isna()]
                    elif has_rr_perf_axis:
                        fund_facts = df_filtered[df_filtered['dim_rr_PerformanceMeasureAxis'].isna()]
                    else:
                        fund_facts = df_filtered

                    fiscal_year_end = None
                    if 'period_end' in fund_facts.columns:
                        period_ends = fund_facts['period_end'].dropna()
                        if not period_ends.empty:
                            fiscal_year_end = parse_date(period_ends.iloc[0])

                    if fiscal_year_end:
                        key = (etf.class_id or etf.ticker, fiscal_year_end)
                        if key not in satisfied:
                            returns_data, expense_ratio, portfolio_turnover = _extract_fund_data(fund_facts)

                            # Use first available benchmark from class map, fall back to direct
                            # BroadBased/Additional extraction, then RR
                            uit_benchmark_name = None
                            uit_benchmark_returns = {}
                            if class_benchmark_map:
                                first_class_id = next(iter(class_benchmark_map))
                                uit_benchmark_name, bm_facts_df = class_benchmark_map[first_class_id]
                                if uit_benchmark_name not in resolved_benchmarks:
                                    resolve_benchmark_label(session, uit_benchmark_name, xbrl_obj=xbrl_obj, cik=cik, filing_date=filing_date)
                                    resolved_benchmarks.add(uit_benchmark_name)
                                if uit_benchmark_name not in benchmark_returns_cache:
                                    benchmark_returns_cache[uit_benchmark_name] = _extract_benchmark_returns_from_facts(bm_facts_df)
                                uit_benchmark_returns = benchmark_returns_cache[uit_benchmark_name]
                            elif has_broad_based_axis:
                                uit_benchmark_name, bm_facts_deduped = _extract_benchmark_from_axis(
                                    df_filtered, 'dim_oef_BroadBasedIndexAxis'
                                )
                                if uit_benchmark_name is not None:
                                    if uit_benchmark_name not in resolved_benchmarks:
                                        resolve_benchmark_label(session, uit_benchmark_name, xbrl_obj=xbrl_obj, cik=cik, filing_date=filing_date)
                                        resolved_benchmarks.add(uit_benchmark_name)
                                    if uit_benchmark_name not in benchmark_returns_cache:
                                        benchmark_returns_cache[uit_benchmark_name] = _extract_benchmark_returns_from_facts(bm_facts_deduped)
                                    uit_benchmark_returns = benchmark_returns_cache[uit_benchmark_name]
                            elif 'dim_oef_AdditionalIndexAxis' in df_filtered.columns:
                                uit_benchmark_name, bm_facts_deduped = _extract_benchmark_from_axis(
                                    df_filtered, 'dim_oef_AdditionalIndexAxis'
                                )
                                if uit_benchmark_name is not None:
                                    if uit_benchmark_name not in resolved_benchmarks:
                                        resolve_benchmark_label(session, uit_benchmark_name, xbrl_obj=xbrl_obj, cik=cik, filing_date=filing_date)
                                        resolved_benchmarks.add(uit_benchmark_name)
                                    if uit_benchmark_name not in benchmark_returns_cache:
                                        benchmark_returns_cache[uit_benchmark_name] = _extract_benchmark_returns_from_facts(bm_facts_deduped)
                                    uit_benchmark_returns = benchmark_returns_cache[uit_benchmark_name]
                            elif rr_benchmark_name:
                                uit_benchmark_name = rr_benchmark_name
                                if uit_benchmark_name not in resolved_benchmarks:
                                    resolve_benchmark_label(session, uit_benchmark_name, xbrl_obj=xbrl_obj, cik=cik, filing_date=filing_date)
                                    resolved_benchmarks.add(uit_benchmark_name)
                                uit_benchmark_returns = rr_benchmark_returns

                            data_kwargs = {
                                **returns_data,
                                "expense_ratio_actual": expense_ratio,
                                "portfolio_turnover": portfolio_turnover,
                            }
                            if uit_benchmark_name is not None:
                                data_kwargs["benchmark_name"] = uit_benchmark_name
                                data_kwargs.update(uit_benchmark_returns)

                            _upsert_performance_record(
                                session, etf, fiscal_year_end, filing_date, returns_data, data_kwargs, cik, label="UIT "
                            )

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
