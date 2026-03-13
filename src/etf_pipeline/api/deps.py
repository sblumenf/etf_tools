from sqlalchemy.orm import Session
from etf_pipeline.db import get_engine

_engine = get_engine()


def get_db():
    with Session(_engine) as session:
        yield session
