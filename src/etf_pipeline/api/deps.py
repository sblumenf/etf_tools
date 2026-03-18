from functools import lru_cache

from sqlalchemy.orm import Session
from etf_pipeline.db import get_engine


@lru_cache(maxsize=1)
def _get_engine():
    return get_engine()


def get_db():
    with Session(_get_engine()) as session:
        yield session
