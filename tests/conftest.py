import os
from unittest.mock import patch

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


@pytest.fixture
def mock_nport_db(engine):
    """Patch database access for nport parser tests."""
    with patch("etf_pipeline.parsers.nport.get_engine", return_value=engine):
        with patch("etf_pipeline.parsers.nport.sessionmaker") as mock_sm:
            mock_sm.return_value = sessionmaker(bind=engine)
            yield


@pytest.fixture
def mock_load_etfs_db(engine):
    """Patch database access for load_etfs tests."""
    with patch("etf_pipeline.load_etfs.get_engine", return_value=engine):
        with patch("etf_pipeline.load_etfs.sessionmaker") as mock_sm:
            mock_sm.return_value = sessionmaker(bind=engine)
            yield


@pytest.fixture
def mock_flows_db(engine):
    """Patch database access for flows parser tests."""
    with patch("etf_pipeline.parsers.flows.get_engine", return_value=engine):
        with patch("etf_pipeline.parsers.flows.sessionmaker") as mock_sm:
            mock_sm.return_value = sessionmaker(bind=engine)
            yield


@pytest.fixture
def mock_ncsr_db(engine):
    """Patch database access for ncsr parser tests."""
    with patch("etf_pipeline.parsers.ncsr.get_engine", return_value=engine):
        with patch("etf_pipeline.parsers.ncsr.sessionmaker") as mock_sm:
            mock_sm.return_value = sessionmaker(bind=engine)
            yield
