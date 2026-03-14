"""Tests for get_fund_snapshot series_id filtering and ASSET_CATEGORY_MAP entries."""
from datetime import date
from decimal import Decimal

import pytest

from etf_pipeline.models import FundSnapshot
from etf_pipeline.xray import service
from etf_pipeline.xray.service import ASSET_CATEGORY_MAP


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CIK = "0000036405"
REPORT_DATE = date(2024, 12, 31)
FILING_DATE = date(2025, 1, 15)


def _snapshot(cik, series_id, total_assets, report_date=REPORT_DATE, filing_date=FILING_DATE):
    return FundSnapshot(
        cik=cik,
        series_id=series_id,
        report_date=report_date,
        filing_date=filing_date,
        total_assets=Decimal(str(total_assets)),
        net_assets=Decimal(str(total_assets)),
    )


# ---------------------------------------------------------------------------
# get_fund_snapshot — series_id filtering
# ---------------------------------------------------------------------------

def test_get_fund_snapshot_without_series_id_returns_latest(session):
    """Without series_id, returns the most recent snapshot for the CIK."""
    session.add(_snapshot(CIK, "S000002839", "1000000", date(2024, 9, 30), date(2024, 10, 15)))
    session.add(_snapshot(CIK, "S000002839", "2000000", date(2024, 12, 31), date(2025, 1, 15)))
    session.commit()

    result = service.get_fund_snapshot(session, CIK)

    assert result is not None
    assert result.total_assets == Decimal("2000000")


def test_get_fund_snapshot_with_series_id_filters_correctly(session):
    """With series_id, returns the snapshot matching that specific series."""
    session.add(_snapshot(CIK, "S000002839", "1000000"))
    session.add(_snapshot(CIK, "S000002840", "2000000"))
    session.commit()

    result_a = service.get_fund_snapshot(session, CIK, series_id="S000002839")
    result_b = service.get_fund_snapshot(session, CIK, series_id="S000002840")

    assert result_a is not None
    assert result_a.series_id == "S000002839"
    assert result_a.total_assets == Decimal("1000000")

    assert result_b is not None
    assert result_b.series_id == "S000002840"
    assert result_b.total_assets == Decimal("2000000")


def test_get_fund_snapshot_series_id_does_not_return_other_series(session):
    """Querying for one series_id never returns a snapshot from a different series."""
    session.add(_snapshot(CIK, "S000002839", "1000000"))
    session.commit()

    result = service.get_fund_snapshot(session, CIK, series_id="S000002840")

    assert result is None


def test_get_fund_snapshot_backward_compatible_cik_only(session):
    """Calling with only cik (no series_id) works as before the change."""
    session.add(_snapshot(CIK, None, "500000"))
    session.commit()

    result = service.get_fund_snapshot(session, CIK)

    assert result is not None
    assert result.cik == CIK


def test_get_fund_snapshot_returns_none_when_no_data(session):
    """Returns None when no snapshot exists for the given cik."""
    result = service.get_fund_snapshot(session, "9999999999")
    assert result is None


def test_get_fund_snapshot_series_id_picks_latest_by_report_date(session):
    """When multiple snapshots share cik+series_id, the most recent report_date wins."""
    session.add(_snapshot(CIK, "S000002839", "1000000", date(2024, 6, 30), date(2024, 7, 15)))
    session.add(_snapshot(CIK, "S000002839", "3000000", date(2024, 12, 31), date(2025, 1, 15)))
    session.commit()

    result = service.get_fund_snapshot(session, CIK, series_id="S000002839")

    assert result is not None
    assert result.total_assets == Decimal("3000000")
    assert result.report_date == date(2024, 12, 31)


# ---------------------------------------------------------------------------
# ASSET_CATEGORY_MAP — new entries added in the data-completeness fix
# ---------------------------------------------------------------------------

NEW_ENTRIES = {
    "ABS-MBS": "Mortgage-Backed Securities",
    "ABS-O": "Other ABS",
    "ABS-CBDO": "CDO/CLO",
    "ABS-APCP": "Asset-Backed Commercial Paper",
    "LON": "Loan",
    "RA": "Repurchase Agreement",
    "SN": "Structured Note",
    "RE": "Real Estate",
    "COMM": "Commodity",
}


@pytest.mark.parametrize("code,label", NEW_ENTRIES.items())
def test_asset_category_map_new_entries(code, label):
    """Each newly added asset category code resolves to the correct label."""
    assert code in ASSET_CATEGORY_MAP, f"Code '{code}' missing from ASSET_CATEGORY_MAP"
    assert ASSET_CATEGORY_MAP[code] == label


def test_asset_category_map_original_entries_unchanged():
    """Pre-existing entries in ASSET_CATEGORY_MAP were not altered by the fix."""
    original = {
        "EC": "Equity - Common",
        "EP": "Equity - Preferred",
        "OTHER": "Other",
    }
    for code, label in original.items():
        assert ASSET_CATEGORY_MAP.get(code) == label, (
            f"Original entry '{code}' changed: expected '{label}', got '{ASSET_CATEGORY_MAP.get(code)}'"
        )


def test_asset_category_map_total_count():
    """ASSET_CATEGORY_MAP has exactly 20 entries matching the NPORT XSD enum plus OTHER."""
    assert len(ASSET_CATEGORY_MAP) == 20


# All codes that appear in the NPORT-P XSD assetCatType enum
XSD_VALID_CODES = {
    "STIV",
    "RA",
    "EC",
    "EP",
    "DBT",
    "DCO",
    "DCR",
    "DE",
    "DFE",
    "DIR",
    "DO",
    "SN",
    "LON",
    "ABS-MBS",
    "ABS-APCP",
    "ABS-CBDO",
    "ABS-O",
    "COMM",
    "RE",
}

# Legacy / non-XSD codes that must NOT be present in the map
DEPRECATED_CODES = {"FI", "ABS", "MBS", "UST"}


@pytest.mark.parametrize("code", sorted(XSD_VALID_CODES))
def test_asset_category_map_contains_all_xsd_codes(code):
    """Every code from the NPORT-P XSD assetCatType enum is present in ASSET_CATEGORY_MAP."""
    assert code in ASSET_CATEGORY_MAP, f"XSD code '{code}' is missing from ASSET_CATEGORY_MAP"


@pytest.mark.parametrize("code", sorted(DEPRECATED_CODES))
def test_asset_category_map_excludes_deprecated_codes(code):
    """Codes that are NOT part of the XSD enum must not appear in ASSET_CATEGORY_MAP."""
    assert code not in ASSET_CATEGORY_MAP, (
        f"Deprecated/non-XSD code '{code}' should not be in ASSET_CATEGORY_MAP"
    )
