import os
from decimal import Decimal
from unittest.mock import Mock, patch

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


def _add_mock_fund_info(mock_report):
    """Helper to add fund_info to a mock FundReport."""
    fund_info = Mock()
    fund_info.total_assets = Decimal("10000000.00")
    fund_info.total_liabilities = Decimal("500000.00")
    fund_info.net_assets = Decimal("9500000.00")
    fund_info.cash_not_report_in_cor_d = Decimal("50000.00")
    fund_info.assets_invested = Decimal("9800000.00")
    fund_info.assets_misc_sec = Decimal("150000.00")
    fund_info.amt_pay_one_yr_banks_borr = Decimal("100000.00")
    fund_info.amt_pay_one_yr_ctrld_comp = Decimal("0.00")
    fund_info.amt_pay_one_yr_oth_affil = Decimal("0.00")
    fund_info.amt_pay_one_yr_other = Decimal("50000.00")
    fund_info.amt_pay_aft_one_yr_banks_borr = Decimal("250000.00")
    fund_info.amt_pay_aft_one_yr_ctrld_comp = Decimal("0.00")
    fund_info.amt_pay_aft_one_yr_oth_affil = Decimal("0.00")
    fund_info.amt_pay_aft_one_yr_other = Decimal("100000.00")
    fund_info.delay_deliv = Decimal("0.00")
    fund_info.stand_by_commit = Decimal("0.00")

    fund_info.is_non_cash_collateral = False
    mock_report.fund_info = fund_info
