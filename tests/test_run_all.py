import queue
from datetime import date, datetime
from unittest.mock import MagicMock, call, patch

from click.testing import CliRunner

from etf_pipeline.cli import (
    PARSER_FORM_MAP,
    check_sec_filing_dates,
    get_all_ciks,
    get_processing_log,
    get_stale_parsers,
    main,
)
from etf_pipeline.models import ETF, ProcessingLog


def test_get_all_ciks_no_limit(session):
    """Test get_all_ciks returns all distinct CIKs in alphabetical order."""
    session.add(ETF(ticker="SPY", cik="0000001234", issuer_name="Test 1"))
    session.add(ETF(ticker="QQQ", cik="0000005678", issuer_name="Test 2"))
    session.add(ETF(ticker="VTI", cik="0000001234", issuer_name="Test 1"))  # Duplicate CIK
    session.commit()

    from etf_pipeline.cli import get_all_ciks

    ciks = get_all_ciks(session, limit=None)

    assert ciks == ["0000001234", "0000005678"]


def test_get_all_ciks_with_limit(session):
    """Test get_all_ciks respects limit parameter."""
    session.add(ETF(ticker="SPY", cik="0000001234", issuer_name="Test 1"))
    session.add(ETF(ticker="QQQ", cik="0000005678", issuer_name="Test 2"))
    session.add(ETF(ticker="VTI", cik="0000009999", issuer_name="Test 3"))
    session.commit()

    from etf_pipeline.cli import get_all_ciks

    ciks = get_all_ciks(session, limit=2)

    assert ciks == ["0000001234", "0000005678"]


def test_get_processing_log_exists(session):
    """Test get_processing_log returns existing log entry."""
    session.add(
        ProcessingLog(
            cik="0000001234",
            parser_type="nport",
            last_run_at=datetime(2026, 1, 1),
            latest_filing_date_seen=date(2025, 12, 31),
        )
    )
    session.commit()

    from etf_pipeline.cli import get_processing_log

    log = get_processing_log(session, "0000001234", "nport")

    assert log is not None
    assert log.cik == "0000001234"
    assert log.parser_type == "nport"
    assert log.latest_filing_date_seen == date(2025, 12, 31)


def test_get_processing_log_not_exists(session):
    """Test get_processing_log returns None when no log exists."""
    from etf_pipeline.cli import get_processing_log

    log = get_processing_log(session, "0000001234", "nport")

    assert log is None


def test_get_stale_parsers_never_processed(session):
    """Test get_stale_parsers returns all parsers with SEC filings when never processed."""
    latest_sec_filings = {
        "NPORT-P": date(2026, 1, 15),
        "N-CSR": date(2026, 1, 10),
        "485BPOS": date(2026, 1, 5),
        "24F-2NT": date(2026, 1, 1),
    }

    from etf_pipeline.cli import get_stale_parsers

    stale = get_stale_parsers(session, "0000001234", latest_sec_filings)

    assert set(stale) == {"nport", "ncsr", "prospectus", "finhigh", "flows"}


def test_get_stale_parsers_all_current(session):
    """Test get_stale_parsers returns empty list when all parsers are current."""
    session.add(
        ProcessingLog(
            cik="0000001234",
            parser_type="nport",
            last_run_at=datetime(2026, 1, 20),
            latest_filing_date_seen=date(2026, 1, 15),
        )
    )
    session.add(
        ProcessingLog(
            cik="0000001234",
            parser_type="ncsr",
            last_run_at=datetime(2026, 1, 20),
            latest_filing_date_seen=date(2026, 1, 10),
        )
    )
    session.add(
        ProcessingLog(
            cik="0000001234",
            parser_type="prospectus",
            last_run_at=datetime(2026, 1, 20),
            latest_filing_date_seen=date(2026, 1, 5),
        )
    )
    session.add(
        ProcessingLog(
            cik="0000001234",
            parser_type="finhigh",
            last_run_at=datetime(2026, 1, 20),
            latest_filing_date_seen=date(2026, 1, 10),
        )
    )
    session.add(
        ProcessingLog(
            cik="0000001234",
            parser_type="flows",
            last_run_at=datetime(2026, 1, 20),
            latest_filing_date_seen=date(2026, 1, 1),
        )
    )
    session.commit()

    latest_sec_filings = {
        "NPORT-P": date(2026, 1, 15),
        "N-CSR": date(2026, 1, 10),
        "485BPOS": date(2026, 1, 5),
        "24F-2NT": date(2026, 1, 1),
    }

    from etf_pipeline.cli import get_stale_parsers

    stale = get_stale_parsers(session, "0000001234", latest_sec_filings)

    assert stale == []


def test_get_stale_parsers_partial_stale(session):
    """Test get_stale_parsers returns only parsers with new filings."""
    session.add(
        ProcessingLog(
            cik="0000001234",
            parser_type="nport",
            last_run_at=datetime(2026, 1, 20),
            latest_filing_date_seen=date(2026, 1, 10),  # Older than SEC
        )
    )
    session.add(
        ProcessingLog(
            cik="0000001234",
            parser_type="ncsr",
            last_run_at=datetime(2026, 1, 20),
            latest_filing_date_seen=date(2026, 1, 15),  # Current with SEC
        )
    )
    session.commit()

    latest_sec_filings = {
        "NPORT-P": date(2026, 1, 15),  # Newer than log
        "N-CSR": date(2026, 1, 15),    # Same as log
        "485BPOS": date(2026, 1, 5),   # No log entry
        "24F-2NT": date(2026, 1, 1),   # No log entry
    }

    from etf_pipeline.cli import get_stale_parsers

    stale = get_stale_parsers(session, "0000001234", latest_sec_filings)

    assert set(stale) == {"nport", "prospectus", "finhigh", "flows"}


def test_get_stale_parsers_no_sec_filings(session):
    """Test get_stale_parsers returns empty list when SEC has no filings."""
    latest_sec_filings = {
        "NPORT-P": None,
        "N-CSR": None,
        "485BPOS": None,
        "24F-2NT": None,
    }

    from etf_pipeline.cli import get_stale_parsers

    stale = get_stale_parsers(session, "0000001234", latest_sec_filings)

    assert stale == []


def test_get_stale_parsers_ncsr_shared_form(session):
    """Test that ncsr and finhigh both check N-CSR form."""
    session.add(
        ProcessingLog(
            cik="0000001234",
            parser_type="ncsr",
            last_run_at=datetime(2026, 1, 20),
            latest_filing_date_seen=date(2026, 1, 10),
        )
    )
    session.commit()

    latest_sec_filings = {
        "NPORT-P": None,
        "N-CSR": date(2026, 1, 15),  # Newer than both ncsr and finhigh logs
        "485BPOS": None,
        "24F-2NT": None,
    }

    from etf_pipeline.cli import get_stale_parsers

    stale = get_stale_parsers(session, "0000001234", latest_sec_filings)

    assert set(stale) == {"ncsr", "finhigh"}


@patch("etf_pipeline.cli.process_single_cik")
@patch("etf_pipeline.cli.get_all_ciks")
@patch("etf_pipeline.load_etfs.load_etfs")
@patch("etf_pipeline.discover.fetch")
def test_run_all_skips_cik_with_no_new_filings(
    mock_fetch,
    mock_load_etfs,
    mock_get_all_ciks,
    mock_process_cik,
):
    """Test that run_all skips CIKs with no new filings."""
    runner = CliRunner()

    mock_get_all_ciks.return_value = ["0000001234", "0000005678"]
    mock_process_cik.side_effect = [
        {"status": "skipped", "failed_parsers": [], "warning": None},
        {"status": "processed", "failed_parsers": [], "warning": None},
    ]

    # Mock Process to execute synchronously instead of in subprocess
    with patch("multiprocessing.get_context") as mock_ctx:
        mock_queue_obj = MagicMock()
        results = []

        def queue_put(item):
            results.append(item)

        def queue_get(timeout=None):
            return results.pop(0) if results else None

        mock_queue_obj.put = queue_put
        mock_queue_obj.get = queue_get

        def mock_queue_factory():
            return mock_queue_obj

        mock_context = MagicMock()
        mock_context.Queue = mock_queue_factory

        def mock_process_factory(target, args):
            # Execute target synchronously
            proc = MagicMock()
            proc.exitcode = 0

            def start():
                target(*args)

            proc.start = start
            proc.join = MagicMock()
            proc.is_alive = MagicMock(return_value=False)
            return proc

        mock_context.Process = mock_process_factory
        mock_ctx.return_value = mock_context

        result = runner.invoke(main, ["run-all"])

    assert result.exit_code == 0
    assert "1 CIKs processed" in result.output
    assert "1 CIKs skipped" in result.output
    assert "0 CIKs failed" in result.output


@patch("etf_pipeline.cli.process_single_cik")
@patch("etf_pipeline.cli.get_all_ciks")
@patch("etf_pipeline.load_etfs.load_etfs")
@patch("etf_pipeline.discover.fetch")
def test_run_all_runs_parsers_in_order(
    mock_fetch,
    mock_load_etfs,
    mock_get_all_ciks,
    mock_process_cik,
):
    """Test that run_all processes CIKs and parsers are run in order (tested via process_single_cik)."""
    runner = CliRunner()

    mock_get_all_ciks.return_value = ["0000001234"]
    mock_process_cik.return_value = {"status": "processed", "failed_parsers": [], "warning": None}

    with patch("multiprocessing.get_context") as mock_ctx:
        mock_queue_obj = MagicMock()
        results = []
        mock_queue_obj.put = lambda item: results.append(item)
        mock_queue_obj.get = lambda timeout=None: results.pop(0) if results else None

        mock_context = MagicMock()
        mock_context.Queue = lambda: mock_queue_obj

        def mock_process_factory(target, args):
            proc = MagicMock()
            proc.exitcode = 0
            proc.start = lambda: target(*args)
            proc.join = MagicMock()
            proc.is_alive = MagicMock(return_value=False)
            return proc

        mock_context.Process = mock_process_factory
        mock_ctx.return_value = mock_context

        result = runner.invoke(main, ["run-all"])

    assert result.exit_code == 0
    mock_process_cik.assert_called_once()


@patch("etf_pipeline.cli.process_single_cik")
@patch("etf_pipeline.cli.get_all_ciks")
@patch("etf_pipeline.load_etfs.load_etfs")
@patch("etf_pipeline.discover.fetch")
def test_run_all_processes_multiple_ciks(
    mock_fetch,
    mock_load_etfs,
    mock_get_all_ciks,
    mock_process_cik,
):
    """Test that run_all processes multiple CIKs."""
    runner = CliRunner()

    mock_get_all_ciks.return_value = ["0000001234", "0000005678", "0000009999"]
    mock_process_cik.return_value = {"status": "processed", "failed_parsers": [], "warning": None}

    with patch("multiprocessing.get_context") as mock_ctx:
        mock_queue_obj = MagicMock()
        results = []
        mock_queue_obj.put = lambda item: results.append(item)
        mock_queue_obj.get = lambda timeout=None: results.pop(0) if results else None

        mock_context = MagicMock()
        mock_context.Queue = lambda: mock_queue_obj

        def mock_process_factory(target, args):
            proc = MagicMock()
            proc.exitcode = 0
            proc.start = lambda: target(*args)
            proc.join = MagicMock()
            proc.is_alive = MagicMock(return_value=False)
            return proc

        mock_context.Process = mock_process_factory
        mock_ctx.return_value = mock_context

        result = runner.invoke(main, ["run-all"])

    assert result.exit_code == 0
    assert mock_process_cik.call_count == 3


@patch("etf_pipeline.cli.process_single_cik")
@patch("etf_pipeline.cli.get_all_ciks")
@patch("etf_pipeline.load_etfs.load_etfs")
@patch("etf_pipeline.discover.fetch")
def test_run_all_continues_on_cik_failure(
    mock_fetch,
    mock_load_etfs,
    mock_get_all_ciks,
    mock_process_cik,
):
    """Test that run_all continues processing other CIKs after a parser failure."""
    runner = CliRunner()

    mock_get_all_ciks.return_value = ["0000001234", "0000005678", "0000009999"]
    mock_process_cik.side_effect = [
        {"status": "processed", "failed_parsers": [], "warning": None},
        {"status": "processed", "failed_parsers": ["nport(0000005678)"], "warning": None},
        {"status": "processed", "failed_parsers": [], "warning": None},
    ]

    with patch("multiprocessing.get_context") as mock_ctx:
        mock_queue_obj = MagicMock()
        results = []
        mock_queue_obj.put = lambda item: results.append(item)
        mock_queue_obj.get = lambda timeout=None: results.pop(0) if results else None

        mock_context = MagicMock()
        mock_context.Queue = lambda: mock_queue_obj

        def mock_process_factory(target, args):
            proc = MagicMock()
            proc.exitcode = 0
            proc.start = lambda: target(*args)
            proc.join = MagicMock()
            proc.is_alive = MagicMock(return_value=False)
            return proc

        mock_context.Process = mock_process_factory
        mock_ctx.return_value = mock_context

        result = runner.invoke(main, ["run-all"])

    assert result.exit_code == 0
    assert "3 CIKs processed" in result.output
    assert "0 CIKs failed" in result.output
    assert "Failed parsers: nport(0000005678)" in result.output
    assert mock_process_cik.call_count == 3


@patch("edgar.storage_management.clear_cache")
@patch("etf_pipeline.cli.run_parser_for_cik")
@patch("etf_pipeline.cli.get_stale_parsers")
@patch("etf_pipeline.cli.check_sec_filing_dates")
@patch("etf_pipeline.cli.get_all_ciks")
@patch("etf_pipeline.load_etfs.load_etfs")
@patch("etf_pipeline.discover.fetch")
def test_run_all_respects_limit(
    mock_fetch,
    mock_load_etfs,
    mock_get_all_ciks,
    mock_check_sec,
    mock_get_stale,
    mock_run_parser,
    mock_clear_cache,
):
    """Test that run_all respects --limit parameter."""
    runner = CliRunner()

    mock_get_all_ciks.return_value = ["0000001234", "0000005678"]
    mock_check_sec.return_value = ({}, False)
    mock_get_stale.return_value = ["nport"]

    result = runner.invoke(main, ["run-all", "--limit", "2"])

    assert result.exit_code == 0
    mock_load_etfs.assert_called_once_with(limit=2)
    mock_get_all_ciks.assert_called_once()
    # Verify limit was passed to get_all_ciks
    call_args = mock_get_all_ciks.call_args
    assert call_args[0][1] == 2  # Second positional arg is limit


@patch("edgar.Company")
def test_check_sec_filing_dates_success(mock_company_class):
    """Test check_sec_filing_dates returns filing dates from SEC."""
    mock_filing_nport = MagicMock(form="NPORT-P", filing_date=date(2026, 1, 15))
    mock_filing_ncsr = MagicMock(form="N-CSR", filing_date=date(2026, 1, 10))
    mock_filing_24f2nt = MagicMock(form="24F-2NT", filing_date=date(2026, 1, 1))
    mock_filing_other = MagicMock(form="OTHER", filing_date=date(2026, 1, 20))

    mock_filings = [
        mock_filing_nport,
        mock_filing_ncsr,
        mock_filing_24f2nt,
        mock_filing_other,
    ]

    mock_company = MagicMock()
    mock_company.get_filings.return_value = mock_filings
    mock_company_class.return_value = mock_company

    result, had_error = check_sec_filing_dates("0000001234")

    assert result == {
        "NPORT-P": date(2026, 1, 15),
        "N-CSR": date(2026, 1, 10),
        "485BPOS": None,
        "24F-2NT": date(2026, 1, 1),
    }
    assert had_error is False


@patch("edgar.Company")
def test_check_sec_filing_dates_handles_exception(mock_company_class):
    """Test check_sec_filing_dates handles exceptions gracefully."""
    mock_company = MagicMock()
    mock_company.get_filings.side_effect = Exception("SEC API error")
    mock_company_class.return_value = mock_company

    result, had_error = check_sec_filing_dates("0000001234")

    assert result == {
        "NPORT-P": None,
        "N-CSR": None,
        "485BPOS": None,
        "24F-2NT": None,
    }
    assert had_error is True


@patch("etf_pipeline.parsers.nport.parse_nport")
def test_run_parser_for_cik_nport(mock_parse_nport):
    """Test run_parser_for_cik dispatches to nport parser."""
    from etf_pipeline.cli import run_parser_for_cik

    run_parser_for_cik("0000001234", "nport")

    mock_parse_nport.assert_called_once_with(ciks=["0000001234"], clear_cache=True)


@patch("etf_pipeline.parsers.ncsr.parse_ncsr")
def test_run_parser_for_cik_ncsr(mock_parse_ncsr):
    """Test run_parser_for_cik dispatches to ncsr parser."""
    from etf_pipeline.cli import run_parser_for_cik

    run_parser_for_cik("0000001234", "ncsr")

    mock_parse_ncsr.assert_called_once_with(ciks=["0000001234"], clear_cache=True)


@patch("etf_pipeline.parsers.prospectus.parse_prospectus")
def test_run_parser_for_cik_prospectus(mock_parse_prospectus):
    """Test run_parser_for_cik dispatches to prospectus parser."""
    from etf_pipeline.cli import run_parser_for_cik

    run_parser_for_cik("0000001234", "prospectus")

    mock_parse_prospectus.assert_called_once_with(ciks=["0000001234"], clear_cache=True)


@patch("etf_pipeline.parsers.finhigh.parse_finhigh")
def test_run_parser_for_cik_finhigh(mock_parse_finhigh):
    """Test run_parser_for_cik dispatches to finhigh parser."""
    from etf_pipeline.cli import run_parser_for_cik

    run_parser_for_cik("0000001234", "finhigh")

    mock_parse_finhigh.assert_called_once_with(ciks=["0000001234"], clear_cache=True)


@patch("etf_pipeline.parsers.flows.parse_flows")
def test_run_parser_for_cik_flows(mock_parse_flows):
    """Test run_parser_for_cik dispatches to flows parser."""
    from etf_pipeline.cli import run_parser_for_cik

    run_parser_for_cik("0000001234", "flows")

    mock_parse_flows.assert_called_once_with(ciks=["0000001234"], clear_cache=True)


def test_parser_form_map_consistency():
    """Test PARSER_FORM_MAP has correct mappings."""
    assert PARSER_FORM_MAP == {
        "nport": "NPORT-P",
        "ncsr": "N-CSR",
        "prospectus": "485BPOS",
        "finhigh": "N-CSR",
        "flows": "24F-2NT",
    }


def test_parser_form_map_ncsr_finhigh_share_form():
    """Test that ncsr and finhigh both map to N-CSR."""
    assert PARSER_FORM_MAP["ncsr"] == "N-CSR"
    assert PARSER_FORM_MAP["finhigh"] == "N-CSR"


def test_get_stale_parsers_check_failed_never_processed(session):
    """Test check_failed=True includes parsers with no ProcessingLog when SEC dates are None."""
    latest_sec_filings = {
        "NPORT-P": None,
        "N-CSR": None,
        "485BPOS": None,
        "24F-2NT": None,
    }

    from etf_pipeline.cli import get_stale_parsers

    stale = get_stale_parsers(session, "0000001234", latest_sec_filings, check_failed=True)

    assert set(stale) == {"nport", "ncsr", "prospectus", "finhigh", "flows"}


def test_get_stale_parsers_check_failed_already_processed(session):
    """Test check_failed=True skips parsers that have ProcessingLog entries."""
    session.add(
        ProcessingLog(
            cik="0000001234",
            parser_type="nport",
            last_run_at=datetime(2026, 1, 20),
            latest_filing_date_seen=date(2026, 1, 15),
        )
    )
    session.add(
        ProcessingLog(
            cik="0000001234",
            parser_type="ncsr",
            last_run_at=datetime(2026, 1, 20),
            latest_filing_date_seen=date(2026, 1, 10),
        )
    )
    session.commit()

    latest_sec_filings = {
        "NPORT-P": None,
        "N-CSR": None,
        "485BPOS": None,
        "24F-2NT": None,
    }

    from etf_pipeline.cli import get_stale_parsers

    stale = get_stale_parsers(session, "0000001234", latest_sec_filings, check_failed=True)

    # Only parsers without ProcessingLog entries should be included
    assert set(stale) == {"prospectus", "finhigh", "flows"}


@patch("etf_pipeline.cli.process_single_cik")
@patch("etf_pipeline.cli.get_all_ciks")
@patch("etf_pipeline.load_etfs.load_etfs")
@patch("etf_pipeline.discover.fetch")
def test_run_all_when_sec_check_fails(
    mock_fetch,
    mock_load_etfs,
    mock_get_all_ciks,
    mock_process_cik,
):
    """Test that run_all handles SEC check failures and processes unprocessed parsers."""
    runner = CliRunner()

    mock_get_all_ciks.return_value = ["0000001234"]
    mock_process_cik.return_value = {
        "status": "processed",
        "failed_parsers": [],
        "warning": "SEC filing date check failed for CIK 0000001234, will attempt unprocessed parsers"
    }

    with patch("multiprocessing.get_context") as mock_ctx:
        mock_queue_obj = MagicMock()
        results = []
        mock_queue_obj.put = lambda item: results.append(item)
        mock_queue_obj.get = lambda timeout=None: results.pop(0) if results else None

        mock_context = MagicMock()
        mock_context.Queue = lambda: mock_queue_obj

        def mock_process_factory(target, args):
            proc = MagicMock()
            proc.exitcode = 0
            proc.start = lambda: target(*args)
            proc.join = MagicMock()
            proc.is_alive = MagicMock(return_value=False)
            return proc

        mock_context.Process = mock_process_factory
        mock_ctx.return_value = mock_context

        result = runner.invoke(main, ["run-all"])

    assert result.exit_code == 0
    assert "Warning: SEC filing date check failed for CIK 0000001234" in result.output
    assert "will attempt unprocessed parsers" in result.output
    assert "1 CIKs processed" in result.output
    assert "0 CIKs skipped" in result.output


@patch("etf_pipeline.cli.get_all_ciks")
@patch("etf_pipeline.load_etfs.load_etfs")
@patch("etf_pipeline.discover.fetch")
def test_run_all_handles_subprocess_timeout(
    mock_fetch,
    mock_load_etfs,
    mock_get_all_ciks,
):
    """Test that run_all handles subprocess timeout correctly."""
    runner = CliRunner()

    mock_get_all_ciks.return_value = ["0000001234"]

    with patch("multiprocessing.get_context") as mock_ctx:
        mock_queue_obj = MagicMock()

        mock_context = MagicMock()
        mock_context.Queue = lambda: mock_queue_obj

        def mock_process_factory(target, args):
            proc = MagicMock()
            proc.exitcode = None
            proc.start = MagicMock()
            proc.join = MagicMock()
            proc.is_alive = MagicMock(return_value=True)  # Simulates timeout
            proc.terminate = MagicMock()
            return proc

        mock_context.Process = mock_process_factory
        mock_ctx.return_value = mock_context

        result = runner.invoke(main, ["run-all"])

    assert result.exit_code == 0
    assert "Process timed out for CIK 0000001234" in result.output
    assert "0 CIKs processed" in result.output
    assert "0 CIKs skipped" in result.output
    assert "1 CIKs failed" in result.output


@patch("etf_pipeline.cli.get_all_ciks")
@patch("etf_pipeline.load_etfs.load_etfs")
@patch("etf_pipeline.discover.fetch")
def test_run_all_handles_subprocess_crash(
    mock_fetch,
    mock_load_etfs,
    mock_get_all_ciks,
):
    """Test that run_all handles subprocess crash correctly."""
    runner = CliRunner()

    mock_get_all_ciks.return_value = ["0000001234"]

    with patch("multiprocessing.get_context") as mock_ctx:
        mock_queue_obj = MagicMock()

        mock_context = MagicMock()
        mock_context.Queue = lambda: mock_queue_obj

        def mock_process_factory(target, args):
            proc = MagicMock()
            proc.exitcode = -9  # Simulates OOM kill
            proc.start = MagicMock()
            proc.join = MagicMock()
            proc.is_alive = MagicMock(return_value=False)
            return proc

        mock_context.Process = mock_process_factory
        mock_ctx.return_value = mock_context

        result = runner.invoke(main, ["run-all"])

    assert result.exit_code == 0
    assert "Process crashed for CIK 0000001234" in result.output
    assert "exit code: -9" in result.output
    assert "0 CIKs processed" in result.output
    assert "0 CIKs skipped" in result.output
    assert "1 CIKs failed" in result.output


@patch("etf_pipeline.cli.get_all_ciks")
@patch("etf_pipeline.load_etfs.load_etfs")
@patch("etf_pipeline.discover.fetch")
def test_run_all_handles_empty_queue(
    mock_fetch,
    mock_load_etfs,
    mock_get_all_ciks,
):
    """Test that run_all handles empty queue correctly."""
    runner = CliRunner()

    mock_get_all_ciks.return_value = ["0000001234"]

    with patch("multiprocessing.get_context") as mock_ctx:
        mock_queue_obj = MagicMock()
        mock_queue_obj.get = MagicMock(side_effect=queue.Empty)  # Simulates empty queue

        mock_context = MagicMock()
        mock_context.Queue = lambda: mock_queue_obj

        def mock_process_factory(target, args):
            proc = MagicMock()
            proc.exitcode = 0
            proc.start = MagicMock()
            proc.join = MagicMock()
            proc.is_alive = MagicMock(return_value=False)
            return proc

        mock_context.Process = mock_process_factory
        mock_ctx.return_value = mock_context

        result = runner.invoke(main, ["run-all"])

    assert result.exit_code == 0
    assert "No result received from subprocess for CIK 0000001234" in result.output
    assert "0 CIKs processed" in result.output
    assert "0 CIKs skipped" in result.output
    assert "1 CIKs failed" in result.output
