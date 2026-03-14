"""Tests for _extract_fund_snapshot in nport.py — series_id-aware deduplication."""
from datetime import date
from decimal import Decimal
from unittest.mock import Mock

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from etf_pipeline.models import FundSnapshot
from etf_pipeline.parsers.nport import _extract_fund_snapshot


def _make_fund_report(total_assets="1000000.00"):
    """Return a minimal mock FundReport with fund_info."""
    fi = Mock()
    fi.total_assets = Decimal(total_assets)
    fi.total_liabilities = Decimal("50000.00")
    fi.net_assets = Decimal("950000.00")
    fi.cash_not_reported = Decimal("5000.00")
    fi.assets_invested = Decimal("980000.00")
    fi.assets_misc_sec = Decimal("15000.00")
    fi.amt_pay_one_yr_banks_borr = Decimal("10000.00")
    fi.amt_pay_one_yr_ctrld_comp = Decimal("0.00")
    fi.amt_pay_one_yr_oth_affil = Decimal("0.00")
    fi.amt_pay_one_yr_other = Decimal("5000.00")
    fi.amt_pay_aft_one_yr_banks_borr = Decimal("25000.00")
    fi.amt_pay_aft_one_yr_ctrld_comp = Decimal("0.00")
    fi.amt_pay_aft_one_yr_oth_affil = Decimal("0.00")
    fi.amt_pay_aft_one_yr_other = Decimal("10000.00")
    fi.delay_deliv = Decimal("0.00")
    fi.stand_by_commit = Decimal("0.00")
    fi.liquidity_pref = Decimal("0.00")
    fi.is_non_cash_collateral = False

    report = Mock()
    report.fund_info = fi
    return report


REPORT_DATE = date(2024, 12, 31)
FILING_DATE = date(2025, 1, 15)
CIK = "0000036405"


def test_extract_fund_snapshot_stores_series_id(session):
    """series_id is persisted on the FundSnapshot record."""
    report = _make_fund_report()
    _extract_fund_snapshot(session, CIK, "S000002839", report, REPORT_DATE, FILING_DATE)
    session.flush()

    stmt = select(FundSnapshot).where(FundSnapshot.cik == CIK)
    snapshots = session.execute(stmt).scalars().all()

    assert len(snapshots) == 1
    assert snapshots[0].series_id == "S000002839"


def test_extract_fund_snapshot_two_series_same_cik_both_stored(session):
    """Two series sharing one CIK each produce their own snapshot."""
    report_a = _make_fund_report("1000000.00")
    report_b = _make_fund_report("2000000.00")

    _extract_fund_snapshot(session, CIK, "S000002839", report_a, REPORT_DATE, FILING_DATE)
    _extract_fund_snapshot(session, CIK, "S000002840", report_b, REPORT_DATE, FILING_DATE)
    session.flush()

    stmt = select(FundSnapshot).where(FundSnapshot.cik == CIK).order_by(FundSnapshot.series_id)
    snapshots = session.execute(stmt).scalars().all()

    assert len(snapshots) == 2
    assert snapshots[0].series_id == "S000002839"
    assert snapshots[0].total_assets == Decimal("1000000.00")
    assert snapshots[1].series_id == "S000002840"
    assert snapshots[1].total_assets == Decimal("2000000.00")


def test_extract_fund_snapshot_skips_duplicate_same_series(session, caplog):
    """Re-running for the same (cik, series_id, report_date, filing_date) is a no-op."""
    import logging
    caplog.set_level(logging.DEBUG)

    report = _make_fund_report("1000000.00")
    _extract_fund_snapshot(session, CIK, "S000002839", report, REPORT_DATE, FILING_DATE)
    session.flush()

    report2 = _make_fund_report("9999999.00")
    _extract_fund_snapshot(session, CIK, "S000002839", report2, REPORT_DATE, FILING_DATE)
    session.flush()

    stmt = select(FundSnapshot).where(
        FundSnapshot.cik == CIK,
        FundSnapshot.series_id == "S000002839",
    )
    snapshots = session.execute(stmt).scalars().all()

    assert len(snapshots) == 1
    assert snapshots[0].total_assets == Decimal("1000000.00")
    assert "already exists" in caplog.text


def test_extract_fund_snapshot_none_series_id(session):
    """series_id=None is stored as NULL and treated as a distinct key."""
    report = _make_fund_report()
    _extract_fund_snapshot(session, CIK, None, report, REPORT_DATE, FILING_DATE)
    session.flush()

    stmt = select(FundSnapshot).where(FundSnapshot.cik == CIK)
    snapshots = session.execute(stmt).scalars().all()

    assert len(snapshots) == 1
    assert snapshots[0].series_id is None


def test_extract_fund_snapshot_missing_fund_info(session, caplog):
    """FundReport without fund_info attribute logs a warning and creates nothing."""
    import logging
    caplog.set_level(logging.WARNING)

    report = Mock(spec=["non_derivatives", "derivatives"])  # no fund_info attribute

    _extract_fund_snapshot(session, CIK, "S000002839", report, REPORT_DATE, FILING_DATE)
    session.flush()

    stmt = select(FundSnapshot).where(FundSnapshot.cik == CIK)
    snapshots = session.execute(stmt).scalars().all()

    assert len(snapshots) == 0
    assert "No fund_info" in caplog.text
