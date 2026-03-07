from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from etf_pipeline.cli import main
from etf_pipeline.models import ETF


@pytest.fixture
def db_with_etfs(engine):
    """Insert two ETFs into the test DB and patch all parser engines."""
    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(bind=engine)
    with factory() as sess:
        sess.add(ETF(ticker="SPY", cik="0000001234", issuer_name="Test ETF 1"))
        sess.add(ETF(ticker="QQQ", cik="0000005678", issuer_name="Test ETF 2"))
        sess.commit()

    with patch("etf_pipeline.db.get_engine", return_value=engine):
        yield engine


def _noop(**kwargs):
    pass


def test_backfill_requires_from_date():
    runner = CliRunner()
    result = runner.invoke(main, ["backfill", "--to-date", "2024-12-31"])
    assert result.exit_code != 0
    assert "from-date" in result.output.lower() or "Missing option" in result.output


def test_backfill_requires_to_date():
    runner = CliRunner()
    result = runner.invoke(main, ["backfill", "--from-date", "2024-01-01"])
    assert result.exit_code != 0
    assert "to-date" in result.output.lower() or "Missing option" in result.output


def test_backfill_empty_db_shows_helpful_error(engine):
    runner = CliRunner()
    with patch("etf_pipeline.db.get_engine", return_value=engine):
        result = runner.invoke(
            main, ["backfill", "--from-date", "2024-01-01", "--to-date", "2024-12-31"]
        )
    assert result.exit_code == 0
    assert "discover" in result.output or "load-etfs" in result.output


def test_backfill_calls_all_parsers_with_date_range(db_with_etfs):
    runner = CliRunner()

    import etf_pipeline.cli as cli_module

    mock_fns = {name: MagicMock(return_value=None) for name in cli_module.PARSERS}
    original = dict(cli_module.PARSERS)
    for name, fn in mock_fns.items():
        cli_module.PARSERS[name] = (fn, original[name][1])

    try:
        result = runner.invoke(
            main,
            ["backfill", "--from-date", "2024-01-01", "--to-date", "2024-12-31"],
        )
    finally:
        cli_module.PARSERS.update(original)

    assert result.exit_code == 0
    for name, fn in mock_fns.items():
        fn.assert_called_once()
        _, kwargs = fn.call_args
        assert kwargs.get("from_date") == "2024-01-01", f"{name}: from_date not passed"
        assert kwargs.get("to_date") == "2024-12-31", f"{name}: to_date not passed"


def test_backfill_parser_flag_selects_specific_parsers(db_with_etfs):
    runner = CliRunner()

    import etf_pipeline.cli as cli_module

    mock_fns = {name: MagicMock(return_value=None) for name in cli_module.PARSERS}
    original = dict(cli_module.PARSERS)
    for name, fn in mock_fns.items():
        cli_module.PARSERS[name] = (fn, original[name][1])

    try:
        result = runner.invoke(
            main,
            [
                "backfill",
                "--from-date", "2024-01-01",
                "--to-date", "2024-12-31",
                "--parser", "flows",
                "--parser", "ncsr",
            ],
        )
    finally:
        cli_module.PARSERS.update(original)

    assert result.exit_code == 0
    mock_fns["flows"].assert_called_once()
    mock_fns["ncsr"].assert_called_once()
    mock_fns["nport"].assert_not_called()
    mock_fns["prospectus"].assert_not_called()
    mock_fns["finhigh"].assert_not_called()


def test_backfill_cik_flag_limits_to_one_cik(db_with_etfs):
    runner = CliRunner()

    import etf_pipeline.cli as cli_module

    captured = []

    def fake_parse(**kwargs):
        captured.append(kwargs.get("ciks", []))

    original = dict(cli_module.PARSERS)
    for name in cli_module.PARSERS:
        cli_module.PARSERS[name] = (fake_parse, original[name][1])

    try:
        result = runner.invoke(
            main,
            [
                "backfill",
                "--from-date", "2024-01-01",
                "--to-date", "2024-12-31",
                "--cik", "1234",
                "--parser", "flows",
            ],
        )
    finally:
        cli_module.PARSERS.update(original)

    assert result.exit_code == 0
    assert len(captured) == 1
    assert len(captured[0]) == 1
    assert captured[0][0] == "0000001234"


def test_backfill_limit_flag(db_with_etfs):
    runner = CliRunner()

    import etf_pipeline.cli as cli_module

    captured = []

    def fake_parse(**kwargs):
        captured.append(kwargs.get("ciks", []))

    original = dict(cli_module.PARSERS)
    for name in cli_module.PARSERS:
        cli_module.PARSERS[name] = (fake_parse, original[name][1])

    try:
        result = runner.invoke(
            main,
            [
                "backfill",
                "--from-date", "2024-01-01",
                "--to-date", "2024-12-31",
                "--limit", "1",
                "--parser", "flows",
            ],
        )
    finally:
        cli_module.PARSERS.update(original)

    assert result.exit_code == 0
    assert len(captured) == 1
    assert len(captured[0]) == 1


def test_backfill_parser_failure_is_collected_and_reported(db_with_etfs):
    runner = CliRunner()

    import etf_pipeline.cli as cli_module

    original = dict(cli_module.PARSERS)

    def failing_parse(**kwargs):
        raise RuntimeError("simulated parser crash")

    cli_module.PARSERS["flows"] = (failing_parse, original["flows"][1])

    try:
        result = runner.invoke(
            main,
            [
                "backfill",
                "--from-date", "2024-01-01",
                "--to-date", "2024-12-31",
                "--parser", "flows",
            ],
        )
    finally:
        cli_module.PARSERS.update(original)

    assert result.exit_code == 0
    assert "failed" in result.output.lower()
    assert "flows" in result.output


def test_backfill_summary_always_printed(db_with_etfs):
    runner = CliRunner()

    import etf_pipeline.cli as cli_module

    original = dict(cli_module.PARSERS)
    for name in cli_module.PARSERS:
        cli_module.PARSERS[name] = (MagicMock(return_value=None), original[name][1])

    try:
        result = runner.invoke(
            main,
            ["backfill", "--from-date", "2024-01-01", "--to-date", "2024-12-31"],
        )
    finally:
        cli_module.PARSERS.update(original)

    assert result.exit_code == 0
    assert "Backfill complete" in result.output
    assert "Parsers run:" in result.output
