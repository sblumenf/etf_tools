"""Verify that get_engine() enables SQLite foreign key enforcement."""
from sqlalchemy import text

from etf_pipeline.db import get_engine


def test_get_engine_enables_foreign_keys():
    """get_engine with an in-memory SQLite URL must return an engine where
    PRAGMA foreign_keys is ON (returns 1)."""
    engine = get_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA foreign_keys")).fetchone()
    assert result is not None
    assert result[0] == 1
