"""Shared utilities for ETF pipeline parsers."""
from datetime import date, datetime

from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from etf_pipeline.models import ProcessingLog


def ensure_date(value) -> date:
    """Convert a datetime or date value to a date."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise TypeError(f"ensure_date expected date or datetime, got {type(value)}")


def update_processing_log(session: Session, cik: str, parser_type: str, filing_date: date) -> None:
    """Upsert a processing_log entry for the given CIK and parser type."""
    stmt = insert(ProcessingLog).values(
        cik=cik,
        parser_type=parser_type,
        last_run_at=datetime.now(),
        latest_filing_date_seen=filing_date,
    ).on_conflict_do_update(
        index_elements=["cik", "parser_type"],
        set_={
            "last_run_at": datetime.now(),
            "latest_filing_date_seen": filing_date,
        },
    )
    session.execute(stmt)
