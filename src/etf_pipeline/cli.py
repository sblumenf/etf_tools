import click


@click.group()
def main():
    """SEC EDGAR ETF data pipeline."""
    pass


@main.command()
def discover():
    """Fetch SEC tickers JSON and filter to ETFs."""
    from etf_pipeline.discover import fetch

    click.echo("Fetching company_tickers_mf.json from SEC...")
    etfs = fetch()
    click.echo(f"Filtered to {len(etfs)} ETF tickers.")


@main.command("load-etfs")
@click.option("--cik", type=str, help="Process only this CIK")
@click.option("--limit", type=int, help="Process only the first N CIKs")
def load_etfs_cmd(cik, limit):
    """Load ETF tickers from etf_tickers.json into the database."""
    import logging

    from etf_pipeline.load_etfs import load_etfs

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    load_etfs(cik=cik, limit=limit)


@main.command()
@click.option("--cik", type=str, help="Process only this CIK")
@click.option("--limit", type=int, help="Process only the first N CIKs")
@click.option("--keep-cache", is_flag=True, default=False, help="Keep edgartools HTTP cache after processing (default: clear)")
def nport(cik, limit, keep_cache):
    """Parse NPORT-P filings for holdings and derivatives."""
    import logging

    from etf_pipeline.parsers.nport import parse_nport

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    parse_nport(cik=cik, limit=limit, clear_cache=not keep_cache)


@main.command()
@click.option("--cik", type=str, help="Process only this CIK")
@click.option("--limit", type=int, help="Process only the first N CIKs")
@click.option("--keep-cache", is_flag=True, default=False, help="Keep edgartools HTTP cache after processing (default: clear)")
def ncsr(cik, limit, keep_cache):
    """Parse N-CSR filings for performance data."""
    import logging

    from etf_pipeline.parsers.ncsr import parse_ncsr

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    parse_ncsr(cik=cik, limit=limit, clear_cache=not keep_cache)


@main.command()
@click.option("--cik", type=str, help="Process only this CIK")
@click.option("--limit", type=int, help="Process only the first N CIKs")
@click.option("--keep-cache", is_flag=True, default=False,
              help="Keep edgartools HTTP cache after processing (default: clear)")
def prospectus(cik, limit, keep_cache):
    """Parse 485BPOS filings for fee schedules, shareholder fees, and strategy."""
    import logging
    from etf_pipeline.parsers.prospectus import parse_prospectus
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    parse_prospectus(cik=cik, limit=limit, clear_cache=not keep_cache)


@main.command()
@click.option("--cik", type=str, help="Process only this CIK")
@click.option("--limit", type=int, help="Process only the first N CIKs")
@click.option("--keep-cache", is_flag=True, default=False, help="Keep edgartools HTTP cache after processing (default: clear)")
def flows(cik, limit, keep_cache):
    """Parse 24F-2NT filings for fund flow data."""
    import logging

    from etf_pipeline.parsers.flows import parse_flows

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    parse_flows(cik=cik, limit=limit, clear_cache=not keep_cache)


@main.command()
@click.option("--cik", type=str, help="Process only this CIK")
@click.option("--limit", type=int, help="Process only the first N CIKs")
@click.option("--keep-cache", is_flag=True, default=False, help="Keep edgartools HTTP cache after processing (default: clear)")
def finhigh(cik, limit, keep_cache):
    """Parse N-CSR filings for Financial Highlights data (per-share operating, distributions, ratios)."""
    import logging

    from etf_pipeline.parsers.finhigh import parse_finhigh

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    parse_finhigh(cik=cik, limit=limit, clear_cache=not keep_cache)


@main.command()
@click.option("--limit", type=int, help="Process only the first N CIKs")
def run_all(limit):
    """Run the full pipeline: discover + all parsers."""
    import logging

    from etf_pipeline.db import get_engine
    from etf_pipeline.models import Base
    from etf_pipeline.discover import fetch
    from etf_pipeline.load_etfs import load_etfs
    from etf_pipeline.parsers.nport import parse_nport
    from etf_pipeline.parsers.ncsr import parse_ncsr
    from etf_pipeline.parsers.prospectus import parse_prospectus
    from etf_pipeline.parsers.finhigh import parse_finhigh
    from etf_pipeline.parsers.flows import parse_flows

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    click.echo("--- Step 0/8: Ensuring database tables exist ---")
    engine = get_engine()
    Base.metadata.create_all(engine)

    click.echo("--- Step 1/8: Discovering ETF tickers ---")
    fetch()

    click.echo("--- Step 2/8: Loading ETFs into database ---")
    load_etfs(limit=limit)

    click.echo("--- Step 3/8: Parsing NPORT filings ---")
    parse_nport(limit=limit, clear_cache=False)

    click.echo("--- Step 4/8: Parsing N-CSR filings ---")
    parse_ncsr(limit=limit, clear_cache=False)

    click.echo("--- Step 5/8: Parsing prospectus filings ---")
    parse_prospectus(limit=limit, clear_cache=False)

    click.echo("--- Step 6/8: Parsing financial highlights ---")
    parse_finhigh(limit=limit, clear_cache=False)

    click.echo("--- Step 7/8: Parsing fund flows ---")
    parse_flows(limit=limit, clear_cache=True)

    click.echo("--- Step 8/8: Pipeline complete ---")
