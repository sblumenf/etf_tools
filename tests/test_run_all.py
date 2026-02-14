from unittest.mock import patch, call, MagicMock

from click.testing import CliRunner

from etf_pipeline.cli import main


def test_run_all_calls_all_steps_in_order():
    """Test that run_all invokes all 7 steps in the correct order."""
    runner = CliRunner()

    with (
        patch("etf_pipeline.discover.fetch") as mock_fetch,
        patch("etf_pipeline.load_etfs.load_etfs") as mock_load_etfs,
        patch("etf_pipeline.parsers.nport.parse_nport") as mock_parse_nport,
        patch("etf_pipeline.parsers.ncsr.parse_ncsr") as mock_parse_ncsr,
        patch("etf_pipeline.parsers.prospectus.parse_prospectus") as mock_parse_prospectus,
        patch("etf_pipeline.parsers.finhigh.parse_finhigh") as mock_parse_finhigh,
        patch("etf_pipeline.parsers.flows.parse_flows") as mock_parse_flows,
    ):
        # Create a manager to track call order
        manager = MagicMock()
        manager.attach_mock(mock_fetch, "fetch")
        manager.attach_mock(mock_load_etfs, "load_etfs")
        manager.attach_mock(mock_parse_nport, "parse_nport")
        manager.attach_mock(mock_parse_ncsr, "parse_ncsr")
        manager.attach_mock(mock_parse_prospectus, "parse_prospectus")
        manager.attach_mock(mock_parse_finhigh, "parse_finhigh")
        manager.attach_mock(mock_parse_flows, "parse_flows")

        result = runner.invoke(main, ["run-all"])

        assert result.exit_code == 0

        # Assert the expected call order
        expected_calls = [
            call.fetch(),
            call.load_etfs(limit=None),
            call.parse_nport(limit=None, clear_cache=False),
            call.parse_ncsr(limit=None, clear_cache=False),
            call.parse_prospectus(limit=None, clear_cache=False),
            call.parse_finhigh(limit=None, clear_cache=False),
            call.parse_flows(limit=None, clear_cache=True),
        ]
        assert manager.mock_calls == expected_calls


def test_run_all_passes_limit():
    """Test that run_all passes limit=5 to load_etfs and all parsers."""
    runner = CliRunner()

    with (
        patch("etf_pipeline.discover.fetch") as mock_fetch,
        patch("etf_pipeline.load_etfs.load_etfs") as mock_load_etfs,
        patch("etf_pipeline.parsers.nport.parse_nport") as mock_parse_nport,
        patch("etf_pipeline.parsers.ncsr.parse_ncsr") as mock_parse_ncsr,
        patch("etf_pipeline.parsers.prospectus.parse_prospectus") as mock_parse_prospectus,
        patch("etf_pipeline.parsers.finhigh.parse_finhigh") as mock_parse_finhigh,
        patch("etf_pipeline.parsers.flows.parse_flows") as mock_parse_flows,
    ):
        result = runner.invoke(main, ["run-all", "--limit", "5"])

        assert result.exit_code == 0

        # Assert load_etfs received limit=5
        mock_load_etfs.assert_called_once_with(limit=5)

        # Assert each parser received limit=5 with appropriate clear_cache
        mock_parse_nport.assert_called_once_with(limit=5, clear_cache=False)
        mock_parse_ncsr.assert_called_once_with(limit=5, clear_cache=False)
        mock_parse_prospectus.assert_called_once_with(limit=5, clear_cache=False)
        mock_parse_finhigh.assert_called_once_with(limit=5, clear_cache=False)
        mock_parse_flows.assert_called_once_with(limit=5, clear_cache=True)


def test_run_all_no_limit_passes_none():
    """Test that run_all without --limit passes limit=None to all functions."""
    runner = CliRunner()

    with (
        patch("etf_pipeline.discover.fetch") as mock_fetch,
        patch("etf_pipeline.load_etfs.load_etfs") as mock_load_etfs,
        patch("etf_pipeline.parsers.nport.parse_nport") as mock_parse_nport,
        patch("etf_pipeline.parsers.ncsr.parse_ncsr") as mock_parse_ncsr,
        patch("etf_pipeline.parsers.prospectus.parse_prospectus") as mock_parse_prospectus,
        patch("etf_pipeline.parsers.finhigh.parse_finhigh") as mock_parse_finhigh,
        patch("etf_pipeline.parsers.flows.parse_flows") as mock_parse_flows,
    ):
        result = runner.invoke(main, ["run-all"])

        assert result.exit_code == 0

        # Assert load_etfs received limit=None
        mock_load_etfs.assert_called_once_with(limit=None)

        # Assert each parser received limit=None with appropriate clear_cache
        mock_parse_nport.assert_called_once_with(limit=None, clear_cache=False)
        mock_parse_ncsr.assert_called_once_with(limit=None, clear_cache=False)
        mock_parse_prospectus.assert_called_once_with(limit=None, clear_cache=False)
        mock_parse_finhigh.assert_called_once_with(limit=None, clear_cache=False)
        mock_parse_flows.assert_called_once_with(limit=None, clear_cache=True)
