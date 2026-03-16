"""Tests for the resolve-benchmarks CLI command and _heuristic_label helper."""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner
from sqlalchemy.orm import sessionmaker

from etf_pipeline.benchmark_labels import _heuristic_label
from etf_pipeline.cli import main
from etf_pipeline.models import BenchmarkMapping, ETF, Performance


# ---------------------------------------------------------------------------
# _heuristic_label unit tests
# ---------------------------------------------------------------------------


class TestHeuristicLabel:
    def test_strips_member_suffix(self):
        assert _heuristic_label("SP500IndexMember") is not None
        result = _heuristic_label("SP500IndexMember")
        assert "Member" not in result

    def test_sp500_expansion(self):
        result = _heuristic_label("SP500IndexMember")
        assert "S&P 500" in result

    def test_sp_expansion(self):
        result = _heuristic_label("SPCompositeIndexMember")
        assert "S&P" in result

    def test_camelcase_split(self):
        result = _heuristic_label("BloombergUSAggregateBondIndexMember")
        assert result is not None
        # Should contain spaces from CamelCase splitting
        assert " " in result
        assert "Bloomberg" in result

    def test_strips_broad_based_index_member_suffix(self):
        result = _heuristic_label("SP500BroadBasedIndexMember")
        assert "BroadBasedIndexMember" not in result
        assert "Member" not in result

    def test_msci_kept_uppercase(self):
        result = _heuristic_label("MSCIWorldIndexMember")
        assert result is not None
        assert "MSCI" in result

    def test_returns_none_for_empty_string(self):
        assert _heuristic_label("") is None

    def test_returns_none_for_none(self):
        assert _heuristic_label(None) is None

    def test_returns_none_for_just_member_suffix(self):
        # "Member" stripped -> empty -> None
        assert _heuristic_label("Member") is None

    def test_result_is_stripped(self):
        result = _heuristic_label("RussellMidCapIndexMember")
        assert result == result.strip()

    def test_no_double_spaces(self):
        result = _heuristic_label("NasdaqCompositeIndexMember")
        assert result is not None
        assert "  " not in result

    def test_sp_not_expanded_mid_word_espn(self):
        # "ESPN" should not have "SP" expanded to "S&P" mid-word
        result = _heuristic_label("ESPNMember")
        assert result is not None
        assert "S&P" not in result
        assert "ES" in result

    def test_sp_not_expanded_mid_word_spy(self):
        # "SPY" as a member ID (ticker-like) should not corrupt to "S&P Y"
        result = _heuristic_label("SPYMember")
        assert result is not None
        assert result != "S&P Y"
        assert "S&P Y" not in result


# ---------------------------------------------------------------------------
# resolve-benchmarks CLI command tests
# ---------------------------------------------------------------------------


@pytest.fixture
def db_with_benchmarks(engine):
    """Insert one ETF with two Performance rows that have benchmark_names."""
    factory = sessionmaker(bind=engine)
    with factory() as sess:
        etf = ETF(ticker="SPY", cik="0000001234", issuer_name="SPDR S&P 500")
        sess.add(etf)
        sess.flush()
        perf1 = Performance(
            etf_id=etf.id,
            fiscal_year_end=date(2024, 6, 30),
            filing_date=date(2024, 9, 1),
            benchmark_name="SP500IndexMember",
        )
        perf2 = Performance(
            etf_id=etf.id,
            fiscal_year_end=date(2023, 6, 30),
            filing_date=date(2023, 9, 1),
            benchmark_name="BloombergUSAggregateBondIndexMember",
        )
        sess.add_all([perf1, perf2])
        sess.commit()

    with patch("etf_pipeline.db.get_engine", return_value=engine):
        yield engine


def test_resolve_benchmarks_no_unresolved(engine):
    runner = CliRunner()
    with patch("etf_pipeline.db.get_engine", return_value=engine):
        result = runner.invoke(main, ["resolve-benchmarks"])
    assert result.exit_code == 0
    assert "No unresolved" in result.output


def test_resolve_benchmarks_heuristic_resolves_sp500(db_with_benchmarks):
    engine = db_with_benchmarks
    runner = CliRunner()
    result = runner.invoke(main, ["resolve-benchmarks"])
    assert result.exit_code == 0
    assert "Resolved" in result.output

    factory = sessionmaker(bind=engine)
    with factory() as sess:
        row = sess.query(BenchmarkMapping).filter_by(member_id="SP500IndexMember").first()
        assert row is not None
        assert row.readable_name is not None
        assert "S&P 500" in row.readable_name
        assert row.source == "heuristic"


def test_resolve_benchmarks_dry_run_does_not_write(db_with_benchmarks):
    engine = db_with_benchmarks
    runner = CliRunner()
    result = runner.invoke(main, ["resolve-benchmarks", "--dry-run"])
    assert result.exit_code == 0

    factory = sessionmaker(bind=engine)
    with factory() as sess:
        count = sess.query(BenchmarkMapping).count()
    assert count == 0


def test_resolve_benchmarks_limit_flag(db_with_benchmarks):
    engine = db_with_benchmarks
    runner = CliRunner()
    result = runner.invoke(main, ["resolve-benchmarks", "--limit", "1"])
    assert result.exit_code == 0

    factory = sessionmaker(bind=engine)
    with factory() as sess:
        count = sess.query(BenchmarkMapping).filter(
            BenchmarkMapping.readable_name.isnot(None)
        ).count()
    # Only 1 was processed
    assert count <= 1


def test_resolve_benchmarks_skips_already_mapped(db_with_benchmarks):
    engine = db_with_benchmarks
    factory = sessionmaker(bind=engine)
    with factory() as sess:
        sess.add(BenchmarkMapping(
            member_id="SP500IndexMember",
            readable_name="S&P 500 Index",
            source="manual",
        ))
        sess.commit()

    runner = CliRunner()
    result = runner.invoke(main, ["resolve-benchmarks"])
    assert result.exit_code == 0

    # SP500IndexMember already had a mapping — only BloombergUSAggregateBondIndexMember is new
    with factory() as sess:
        row = sess.query(BenchmarkMapping).filter_by(member_id="SP500IndexMember").first()
        # Source should still be "manual" (not overwritten)
        assert row.source == "manual"


def test_resolve_benchmarks_xbrl_fallback_on_failure(db_with_benchmarks):
    """When heuristic returns None and EDGAR fetch fails, the benchmark counts as failed."""
    engine = db_with_benchmarks
    factory = sessionmaker(bind=engine)

    # Insert a performance record with a member_id the heuristic cannot resolve
    # (just 'Member' stripped -> empty string)
    with factory() as sess:
        etf = sess.query(ETF).filter_by(cik="0000001234").first()
        sess.add(Performance(
            etf_id=etf.id,
            fiscal_year_end=date(2022, 6, 30),
            filing_date=date(2022, 9, 1),
            benchmark_name="XMember",
        ))
        sess.commit()

    runner = CliRunner()
    with patch("edgar.Company") as mock_company_cls:
        mock_company = MagicMock()
        mock_company.get_filings.return_value = []
        mock_company_cls.return_value = mock_company

        result = runner.invoke(main, ["resolve-benchmarks"])

    assert result.exit_code == 0
    assert "failed" in result.output.lower()


def test_resolve_benchmarks_output_counts(db_with_benchmarks):
    runner = CliRunner()
    result = runner.invoke(main, ["resolve-benchmarks"])
    assert result.exit_code == 0
    # Summary line must be present
    assert "Resolved" in result.output
    assert "of" in result.output
