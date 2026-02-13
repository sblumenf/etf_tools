from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine

from etf_pipeline.config import DATABASE_URL


def get_engine(url: str | None = None) -> Engine:
    return create_engine(url or DATABASE_URL)


def enable_sqlite_fks(engine: Engine) -> None:
    """Enable foreign key enforcement for SQLite (used in tests)."""

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
