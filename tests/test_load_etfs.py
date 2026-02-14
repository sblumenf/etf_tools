"""Tests for load_etfs module."""

import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import select

from etf_pipeline.load_etfs import load_etfs
from etf_pipeline.models import ETF


@pytest.fixture
def sample_tickers_file(tmp_path):
    """Create a sample etf_tickers.json file."""
    data = [
        {"ticker": "VOO", "cik": 36405, "series_id": "S000002839", "class_id": "C000007800"},
        {"ticker": "VTV", "cik": 36405, "series_id": "S000002840", "class_id": "C000007801"},
        {"ticker": "SPY", "cik": 1064641, "series_id": "S000002753", "class_id": "C000007739"},
        {"ticker": "IVV", "cik": 1100663, "series_id": "S000002824", "class_id": "C000007785"},
    ]
    tickers_file = tmp_path / "etf_tickers.json"
    tickers_file.write_text(json.dumps(data, indent=2))
    return tickers_file


@pytest.fixture
def mock_company():
    """Mock the edgar Company class."""
    with patch("etf_pipeline.load_etfs.Company") as mock:
        def company_factory(cik):
            company = Mock()
            if cik == "0000036405":
                company.name = "Vanguard Group Inc"
                # Mock get_filings to handle individual filing type requests
                def get_filings_vanguard(form):
                    filing = Mock()
                    # Return issuer-wide filing for 24F-2NT with both series
                    if form == "24F-2NT":
                        filing.header.text = """
<SERIES>
<SERIES-ID>S000002839
<SERIES-NAME>Vanguard 500 Index Fund
</SERIES>
<SERIES>
<SERIES-ID>S000002840
<SERIES-NAME>Vanguard Value Index Fund
</SERIES>
"""
                        return [filing]
                    return []
                company.get_filings.side_effect = get_filings_vanguard
            elif cik == "0001064641":
                company.name = "SPDR S&P 500 ETF Trust"
                # Mock get_filings to handle individual filing type requests
                def get_filings_spdr(form):
                    filing = Mock()
                    # Return filing for 24F-2NT
                    if form == "24F-2NT":
                        filing.header.text = """
<SERIES>
<SERIES-ID>S000002753
<SERIES-NAME>SPDR S&P 500 ETF Trust
</SERIES>
"""
                        return [filing]
                    return []
                company.get_filings.side_effect = get_filings_spdr
            elif cik == "0001100663":
                company.name = "iShares Trust"
                # Mock get_filings to handle individual filing type requests
                def get_filings_ishares(form):
                    filing = Mock()
                    # Return filing for 24F-2NT
                    if form == "24F-2NT":
                        filing.header.text = """
<SERIES>
<SERIES-ID>S000002824
<SERIES-NAME>iShares Core S&P 500 ETF
</SERIES>
"""
                        return [filing]
                    return []
                company.get_filings.side_effect = get_filings_ishares
            else:
                company.name = f"Unknown Company {cik}"
                company.get_filings.return_value = []
            return company

        mock.side_effect = company_factory
        yield mock


def test_load_etfs_all(session, engine, sample_tickers_file, mock_company, mock_load_etfs_db):
    """Test loading all ETFs from the file."""
    with patch("etf_pipeline.load_etfs.TICKERS_FILE", sample_tickers_file):
        load_etfs()

    stmt = select(ETF).order_by(ETF.ticker)
    etfs = session.execute(stmt).scalars().all()

    assert len(etfs) == 4
    assert etfs[0].ticker == "IVV"
    assert etfs[0].cik == "0001100663"
    assert etfs[0].issuer_name == "iShares Trust"
    assert etfs[0].fund_name == "iShares Core S&P 500 ETF"
    assert etfs[1].ticker == "SPY"
    assert etfs[1].cik == "0001064641"
    assert etfs[1].fund_name == "SPDR S&P 500 ETF Trust"
    assert etfs[2].ticker == "VOO"
    assert etfs[2].cik == "0000036405"
    assert etfs[2].issuer_name == "Vanguard Group Inc"
    assert etfs[2].fund_name == "Vanguard 500 Index Fund"
    assert etfs[3].ticker == "VTV"
    assert etfs[3].cik == "0000036405"
    assert etfs[3].fund_name == "Vanguard Value Index Fund"


def test_load_etfs_with_limit(session, engine, sample_tickers_file, mock_company, mock_load_etfs_db):
    """Test loading only the first N CIKs."""
    with patch("etf_pipeline.load_etfs.TICKERS_FILE", sample_tickers_file):
        load_etfs(limit=2)

    stmt = select(ETF).order_by(ETF.ticker)
    etfs = session.execute(stmt).scalars().all()

    assert len(etfs) == 3
    assert {e.ticker for e in etfs} == {"VOO", "VTV", "SPY"}


def test_load_etfs_with_cik_filter(session, engine, sample_tickers_file, mock_company, mock_load_etfs_db):
    """Test loading only a specific CIK."""
    with patch("etf_pipeline.load_etfs.TICKERS_FILE", sample_tickers_file):
        load_etfs(cik="36405")

    stmt = select(ETF).order_by(ETF.ticker)
    etfs = session.execute(stmt).scalars().all()

    assert len(etfs) == 2
    assert etfs[0].ticker == "VOO"
    assert etfs[1].ticker == "VTV"
    assert all(e.cik == "0000036405" for e in etfs)


def test_load_etfs_upsert_existing(session, engine, sample_tickers_file, mock_company, mock_load_etfs_db):
    """Test that existing ETFs are updated, not duplicated."""
    existing = ETF(
        ticker="VOO",
        cik="0000000000",
        series_id="OLD_SERIES",
        issuer_name="Old Issuer",
    )
    session.add(existing)
    session.commit()

    with patch("etf_pipeline.load_etfs.TICKERS_FILE", sample_tickers_file):
        load_etfs(cik="36405")

    stmt = select(ETF).where(ETF.ticker == "VOO")
    voo = session.execute(stmt).scalar_one()

    assert voo.cik == "0000036405"
    assert voo.series_id == "S000002839"
    assert voo.issuer_name == "Vanguard Group Inc"
    assert voo.fund_name == "Vanguard 500 Index Fund"

    stmt_all = select(ETF)
    all_etfs = session.execute(stmt_all).scalars().all()
    assert len(all_etfs) == 2


def test_load_etfs_file_not_found(session, engine, tmp_path, mock_company, mock_load_etfs_db, capsys):
    """Test behavior when etf_tickers.json does not exist."""
    nonexistent_file = tmp_path / "nonexistent.json"

    with patch("etf_pipeline.load_etfs.TICKERS_FILE", nonexistent_file):
        load_etfs()

    captured = capsys.readouterr()
    assert "does not exist" in captured.out


def test_load_etfs_invalid_cik(session, engine, sample_tickers_file, mock_company, mock_load_etfs_db, capsys):
    """Test behavior when requested CIK is not in the file."""
    with patch("etf_pipeline.load_etfs.TICKERS_FILE", sample_tickers_file):
        load_etfs(cik="99999")

    captured = capsys.readouterr()
    assert "not found" in captured.out

    stmt = select(ETF)
    etfs = session.execute(stmt).scalars().all()
    assert len(etfs) == 0


def test_load_etfs_company_error(session, engine, sample_tickers_file, mock_load_etfs_db, capsys):
    """Test that CIK-level errors are caught and logged."""
    with patch("etf_pipeline.load_etfs.TICKERS_FILE", sample_tickers_file):
        with patch("etf_pipeline.load_etfs.Company") as mock_company:
            mock_company.side_effect = Exception("API error")

            load_etfs()

    captured = capsys.readouterr()
    assert "failed" in captured.out.lower()

    stmt = select(ETF)
    etfs = session.execute(stmt).scalars().all()
    assert len(etfs) == 0


def test_load_etfs_filing_type_priority(session, engine, tmp_path, mock_load_etfs_db):
    """Test that filing types are tried in priority order and issuer-wide forms are preferred.

    This test validates the fix for the bug where NPORT-P (fund-specific) would only
    populate 1 series name for a multi-series CIK, while 24F-2NT (issuer-wide) has all series.
    """
    # Create a CIK with 2 series
    data = [
        {"ticker": "MULTI1", "cik": 12345, "series_id": "S000001", "class_id": "C000001"},
        {"ticker": "MULTI2", "cik": 12345, "series_id": "S000002", "class_id": "C000002"},
    ]
    tickers_file = tmp_path / "multi_series.json"
    tickers_file.write_text(json.dumps(data, indent=2))

    with patch("etf_pipeline.load_etfs.TICKERS_FILE", tickers_file):
        with patch("etf_pipeline.load_etfs.Company") as mock_company_cls:
            company = Mock()
            company.name = "Multi-Series Trust"

            def get_filings_priority(form):
                filing = Mock()
                # 24F-2NT has all series (issuer-wide)
                if form == "24F-2NT":
                    filing.header.text = """
<SERIES>
<SERIES-ID>S000001
<SERIES-NAME>Multi Fund One
</SERIES>
<SERIES>
<SERIES-ID>S000002
<SERIES-NAME>Multi Fund Two
</SERIES>
"""
                    return [filing]
                # NPORT-P only has 1 series (fund-specific)
                elif form == "NPORT-P":
                    filing.header.text = """
<SERIES>
<SERIES-ID>S000001
<SERIES-NAME>Multi Fund One
</SERIES>
"""
                    return [filing]
                return []

            company.get_filings.side_effect = get_filings_priority
            mock_company_cls.return_value = company

            load_etfs()

    stmt = select(ETF).order_by(ETF.ticker)
    etfs = session.execute(stmt).scalars().all()

    # Both series should have proper fund names (not issuer name fallback)
    assert len(etfs) == 2
    assert etfs[0].ticker == "MULTI1"
    assert etfs[0].fund_name == "Multi Fund One"
    assert etfs[1].ticker == "MULTI2"
    assert etfs[1].fund_name == "Multi Fund Two"  # This would fail with old code
