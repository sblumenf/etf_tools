import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from etf_pipeline.db import enable_sqlite_fks
from etf_pipeline.models import Base

os.environ.setdefault("EDGAR_IDENTITY", "Test User test@example.com")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")


@pytest.fixture()
def engine():
    eng = create_engine("sqlite:///:memory:")
    enable_sqlite_fks(eng)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture()
def session(engine):
    factory = sessionmaker(bind=engine)
    sess = factory()
    yield sess
    sess.close()
