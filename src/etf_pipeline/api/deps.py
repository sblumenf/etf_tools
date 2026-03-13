from sqlalchemy.orm import Session
from etf_pipeline.db import get_engine


def get_db():
    engine = get_engine()
    with Session(engine) as session:
        yield session
