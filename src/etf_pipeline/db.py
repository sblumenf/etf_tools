from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine

from etf_pipeline.config import DATABASE_URL


def get_engine(url: str | None = None) -> Engine:
    resolved = url or DATABASE_URL
    kwargs = {"connect_args": {"timeout": 30}} if resolved.startswith("sqlite") else {}
    engine = create_engine(resolved, **kwargs)
    enable_sqlite_fks(engine)
    return engine


def enable_sqlite_fks(engine: Engine) -> None:
    """Enable foreign key enforcement for SQLite (used in tests)."""
    if engine.dialect.name != "sqlite":
        return

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()
