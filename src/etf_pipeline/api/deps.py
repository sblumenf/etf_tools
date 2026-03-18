from sqlalchemy.orm import Session
from etf_pipeline.db import get_engine

_engine = None


def get_db():
    global _engine
    if _engine is None:
        _engine = get_engine()
    with Session(_engine) as session:
        yield session
