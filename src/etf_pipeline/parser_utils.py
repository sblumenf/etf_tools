"""Shared utilities for ETF pipeline parsers."""
import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from dateutil.parser import parse as _du_parse

from sqlalchemy import select
from sqlalchemy.orm import Session

from typing import Optional

from etf_pipeline.models import ETF, ProcessingLog, BenchmarkMapping

logger = logging.getLogger(__name__)


def clean_str(val):
    if val is None:
        return None
    val_str = str(val).strip()
    if val_str in ("N/A", "NA", ""):
        return None
    return val_str


def get_clean(obj, attr):
    return clean_str(getattr(obj, attr, None))


def parse_decimal(val, pct=False):
    if val is None:
        return None

    if isinstance(val, Decimal):
        return val

    s = str(val).strip()

    if not s or s in ("-", "—", "N/A", "NA", "n/a"):
        return None

    is_percentage = pct and "%" in s
    s = s.replace("%", "")

    is_negative = False
    if s.startswith("(") and s.endswith(")"):
        is_negative = True
        s = s[1:-1]

    s = s.replace("$", "").replace(",", "")

    try:
        decimal_value = Decimal(s)
        if is_negative:
            decimal_value = -decimal_value
        if is_percentage:
            decimal_value = decimal_value / 100
        return decimal_value
    except (ValueError, TypeError, InvalidOperation):
        logger.warning("Could not parse decimal: %s", val)
        return None


def normalize_return_value(value):
    if value is None:
        return None
    if abs(value) > 2:
        return value / 100
    return value


def parse_date(val):
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    s = str(val).strip()
    if not s:
        return None
    try:
        return _du_parse(s).date()
    except (ValueError, OverflowError):
        logger.warning("Could not parse date: %s", s)
        return None


def ensure_date(value) -> date:
    """Convert a datetime or date value to a date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise TypeError(f"ensure_date expected date or datetime, got {type(value)}")


def build_filing_date_filter(from_date: Optional[str], to_date: Optional[str]) -> Optional[str]:
    """Convert from_date/to_date to edgartools filing_date string.

    Returns None if no dates provided, or "YYYY-MM-DD:YYYY-MM-DD" string.
    Raises ValueError if only one date is provided.
    """
    if from_date is None and to_date is None:
        return None
    if from_date is None or to_date is None:
        raise ValueError("Both from_date and to_date must be provided together")
    return f"{from_date}:{to_date}"


def resolve_cik_list(session, cik=None, ciks=None, limit=None):
    if ciks is not None:
        cik_list = [f"{int(c):010d}" for c in ciks]
    elif cik is not None:
        cik_padded = f"{int(cik):010d}"
        cik_list = [cik_padded]
    else:
        stmt = select(ETF.cik).distinct().order_by(ETF.cik)
        cik_list = [row[0] for row in session.execute(stmt).all()]
        if not cik_list:
            logger.warning("No CIKs found in ETF table. Run 'load-etfs' first.")
            return []

    if limit is not None:
        cik_list = cik_list[:limit]

    return cik_list


def run_parser_loop(cik_list, session_factory, process_fn, parser_name):
    succeeded = 0
    failed = 0

    for cik_str in cik_list:
        with session_factory() as session:
            if process_fn(session, cik_str):
                succeeded += 1
            else:
                failed += 1

    logger.info(f"{parser_name} summary: {succeeded} CIKs succeeded, {failed} CIKs failed")


def clear_and_log_cache():
    from edgar import clear_cache as edgar_clear_cache
    result = edgar_clear_cache(dry_run=False)
    files_deleted = result.get('files_deleted', 0)
    bytes_freed = result.get('bytes_freed', 0)
    mb_freed = bytes_freed / (1024 * 1024)
    logger.info(f"Cache cleared: {files_deleted} files deleted, {mb_freed:.2f} MB freed")


def upsert_record(session, model_class, filter_kwargs, data_kwargs):
    stmt = select(model_class).where(
        *(getattr(model_class, k) == v for k, v in filter_kwargs.items())
    )
    record = session.execute(stmt).scalar_one_or_none()

    if record is not None:
        for k, v in data_kwargs.items():
            setattr(record, k, v)
    else:
        record = model_class(**filter_kwargs, **data_kwargs)
        session.add(record)

    return record


def update_processing_log(session: Session, cik: str, parser_type: str, filing_date: date) -> None:
    """Upsert a processing_log entry for the given CIK and parser type."""
    existing = session.query(ProcessingLog).filter_by(cik=cik, parser_type=parser_type).first()
    if existing:
        existing.last_run_at = datetime.now()
        existing.latest_filing_date_seen = max(existing.latest_filing_date_seen, filing_date)
    else:
        session.add(ProcessingLog(
            cik=cik,
            parser_type=parser_type,
            last_run_at=datetime.now(),
            latest_filing_date_seen=filing_date,
        ))


def map_return_period(period_start: date, period_end: date) -> Optional[str]:
    """Map a date range to a return period field name.

    Uses +/- 30 day tolerance for 1yr/5yr/10yr matching.
    Maps to since_inception for any period > 1yr that doesn't match 5yr or 10yr.
    Returns None for periods <= 1yr that don't match 1yr.
    """
    if not period_start or not period_end:
        return None
    days = (period_end - period_start).days
    years = days / 365.25
    tolerance = 30 / 365.25
    if abs(years - 1) <= tolerance:
        return "return_1yr"
    elif abs(years - 5) <= tolerance:
        return "return_5yr"
    elif abs(years - 10) <= tolerance:
        return "return_10yr"
    elif years > 1 + tolerance:
        return "return_since_inception"
    else:
        return None


def upsert_benchmark_mapping(
    session,
    member_id: str,
    label: str,
    source: str,
    cik: Optional[str] = None,
    filing_date=None,
) -> None:
    """Upsert a BenchmarkMapping record for the given member_id."""
    existing = session.query(BenchmarkMapping).filter_by(member_id=member_id).first()
    if existing:
        existing.readable_name = label
        existing.source = source
    else:
        session.add(BenchmarkMapping(
            member_id=member_id,
            readable_name=label,
            source=source,
            first_seen_cik=cik,
            first_seen_date=filing_date,
        ))
