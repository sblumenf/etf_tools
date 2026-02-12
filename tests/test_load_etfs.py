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
        {"ticker": "VOO", "cik": 36405, "series_id": "S000002839", "class_id": "C000092055"},
        {"ticker": "VTV", "cik": 36405, "series_id": "S000002840", "class_id": "C000007778"},
        {"ticker": "SPY", "cik": 1064641, "series_id": "S000002753", "class_id": "C000007519"},
        {"ticker": "IVV", "cik": 1100663, "series_id": "S000002824", "class_id": "C000007793"},
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
            elif cik == "0001064641":
                company.name = "SPDR S&P 500 ETF Trust"
            elif cik == "0001100663":
                company.name = "iShares Trust"
            else:
                company.name = f"Unknown Company {cik}"
            return company

        mock.side_effect = company_factory
        yield mock


def test_load_etfs_all(session, engine, sample_tickers_file, mock_company):
    """Test loading all ETFs from the file."""
    with patch("etf_pipeline.load_etfs.TICKERS_FILE", sample_tickers_file):
        with patch("etf_pipeline.load_etfs.get_engine", return_value=engine):
            with patch("etf_pipeline.load_etfs.get_session_factory") as mock_factory:
                from sqlalchemy.orm import sessionmaker

                mock_factory.return_value = sessionmaker(bind=engine)

                load_etfs()

    stmt = select(ETF).order_by(ETF.ticker)
    etfs = session.execute(stmt).scalars().all()

    assert len(etfs) == 4
    assert etfs[0].ticker == "IVV"
    assert etfs[0].cik == "0001100663"
    assert etfs[0].issuer_name == "iShares Trust"
    assert etfs[1].ticker == "SPY"
    assert etfs[1].cik == "0001064641"
    assert etfs[2].ticker == "VOO"
    assert etfs[2].cik == "0000036405"
    assert etfs[2].issuer_name == "Vanguard Group Inc"
    assert etfs[3].ticker == "VTV"
    assert etfs[3].cik == "0000036405"


def test_load_etfs_with_limit(session, engine, sample_tickers_file, mock_company):
    """Test loading only the first N CIKs."""
    with patch("etf_pipeline.load_etfs.TICKERS_FILE", sample_tickers_file):
        with patch("etf_pipeline.load_etfs.get_engine", return_value=engine):
            with patch("etf_pipeline.load_etfs.get_session_factory") as mock_factory:
                from sqlalchemy.orm import sessionmaker

                mock_factory.return_value = sessionmaker(bind=engine)

                load_etfs(limit=2)

    stmt = select(ETF).order_by(ETF.ticker)
    etfs = session.execute(stmt).scalars().all()

    assert len(etfs) == 3
    assert {e.ticker for e in etfs} == {"VOO", "VTV", "SPY"}


def test_load_etfs_with_cik_filter(session, engine, sample_tickers_file, mock_company):
    """Test loading only a specific CIK."""
    with patch("etf_pipeline.load_etfs.TICKERS_FILE", sample_tickers_file):
        with patch("etf_pipeline.load_etfs.get_engine", return_value=engine):
            with patch("etf_pipeline.load_etfs.get_session_factory") as mock_factory:
                from sqlalchemy.orm import sessionmaker

                mock_factory.return_value = sessionmaker(bind=engine)

                load_etfs(cik="36405")

    stmt = select(ETF).order_by(ETF.ticker)
    etfs = session.execute(stmt).scalars().all()

    assert len(etfs) == 2
    assert etfs[0].ticker == "VOO"
    assert etfs[1].ticker == "VTV"
    assert all(e.cik == "0000036405" for e in etfs)


def test_load_etfs_upsert_existing(session, engine, sample_tickers_file, mock_company):
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
        with patch("etf_pipeline.load_etfs.get_engine", return_value=engine):
            with patch("etf_pipeline.load_etfs.get_session_factory") as mock_factory:
                from sqlalchemy.orm import sessionmaker

                mock_factory.return_value = sessionmaker(bind=engine)

                load_etfs(cik="36405")

    stmt = select(ETF).where(ETF.ticker == "VOO")
    voo = session.execute(stmt).scalar_one()

    assert voo.cik == "0000036405"
    assert voo.series_id == "S000002839"
    assert voo.issuer_name == "Vanguard Group Inc"

    stmt_all = select(ETF)
    all_etfs = session.execute(stmt_all).scalars().all()
    assert len(all_etfs) == 2


def test_load_etfs_file_not_found(session, engine, tmp_path, mock_company, capsys):
    """Test behavior when etf_tickers.json does not exist."""
    nonexistent_file = tmp_path / "nonexistent.json"

    with patch("etf_pipeline.load_etfs.TICKERS_FILE", nonexistent_file):
        with patch("etf_pipeline.load_etfs.get_engine", return_value=engine):
            with patch("etf_pipeline.load_etfs.get_session_factory") as mock_factory:
                from sqlalchemy.orm import sessionmaker

                mock_factory.return_value = sessionmaker(bind=engine)

                load_etfs()

    captured = capsys.readouterr()
    assert "does not exist" in captured.out


def test_load_etfs_invalid_cik(session, engine, sample_tickers_file, mock_company, capsys):
    """Test behavior when requested CIK is not in the file."""
    with patch("etf_pipeline.load_etfs.TICKERS_FILE", sample_tickers_file):
        with patch("etf_pipeline.load_etfs.get_engine", return_value=engine):
            with patch("etf_pipeline.load_etfs.get_session_factory") as mock_factory:
                from sqlalchemy.orm import sessionmaker

                mock_factory.return_value = sessionmaker(bind=engine)

                load_etfs(cik="99999")

    captured = capsys.readouterr()
    assert "not found" in captured.out

    stmt = select(ETF)
    etfs = session.execute(stmt).scalars().all()
    assert len(etfs) == 0


def test_load_etfs_company_error(session, engine, sample_tickers_file, capsys):
    """Test that CIK-level errors are caught and logged."""
    with patch("etf_pipeline.load_etfs.TICKERS_FILE", sample_tickers_file):
        with patch("etf_pipeline.load_etfs.get_engine", return_value=engine):
            with patch("etf_pipeline.load_etfs.get_session_factory") as mock_factory:
                from sqlalchemy.orm import sessionmaker

                mock_factory.return_value = sessionmaker(bind=engine)

                with patch("etf_pipeline.load_etfs.Company") as mock_company:
                    mock_company.side_effect = Exception("API error")

                    load_etfs()

    captured = capsys.readouterr()
    assert "failed" in captured.out.lower()

    stmt = select(ETF)
    etfs = session.execute(stmt).scalars().all()
    assert len(etfs) == 0
