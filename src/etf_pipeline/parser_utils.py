"""Shared utilities for ETF pipeline parsers."""
import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from dateutil.parser import parse as _du_parse

from sqlalchemy.orm import Session

from etf_pipeline.models import ProcessingLog

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


def update_processing_log(session: Session, cik: str, parser_type: str, filing_date: date) -> None:
    """Upsert a processing_log entry for the given CIK and parser type."""
    existing = session.query(ProcessingLog).filter_by(cik=cik, parser_type=parser_type).first()
    if existing:
        existing.last_run_at = datetime.now()
        existing.latest_filing_date_seen = filing_date
    else:
        session.add(ProcessingLog(
            cik=cik,
            parser_type=parser_type,
            last_run_at=datetime.now(),
            latest_filing_date_seen=filing_date,
        ))
