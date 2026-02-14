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


PARSER_FORM_MAP = {
    "nport": "NPORT-P",
    "ncsr": "N-CSR",
    "prospectus": "485BPOS",
    "finhigh": "N-CSR",
    "flows": "24F-2NT",
}

PARSER_ORDER = ["nport", "ncsr", "prospectus", "finhigh", "flows"]


def get_all_ciks(session, limit):
    """Get list of CIKs from database, alphabetically sorted, with optional limit."""
    from sqlalchemy import select
    from etf_pipeline.models import ETF

    stmt = select(ETF.cik).distinct().order_by(ETF.cik)
    ciks = session.execute(stmt).scalars().all()

    if limit is not None:
        ciks = ciks[:limit]

    return ciks


def check_sec_filing_dates(cik):
    """Check SEC for latest filing date per form type.

    Returns dict: {form_type: date | None}
    """
    from edgar import Company

    result = {}
    form_types = set(PARSER_FORM_MAP.values())

    for form_type in form_types:
        try:
            company = Company(cik)
            filings = company.get_filings(form=form_type)
            if len(filings) > 0:
                result[form_type] = filings[0].filing_date
            else:
                result[form_type] = None
        except Exception:
            result[form_type] = None

    return result


def get_processing_log(session, cik, parser_type):
    """Query processing_log for a specific CIK and parser_type.

    Returns ProcessingLog instance or None.
    """
    from sqlalchemy import select
    from etf_pipeline.models import ProcessingLog

    stmt = select(ProcessingLog).where(
        ProcessingLog.cik == cik,
        ProcessingLog.parser_type == parser_type
    )
    return session.execute(stmt).scalar_one_or_none()


def get_stale_parsers(session, cik, latest_sec_filings):
    """Return list of parser_types that need to run for this CIK.

    A parser is needed if:
    - Never processed before (no processing_log entry)
    - New filing available (SEC latest date > log's latest_filing_date_seen)
    """
    needed = []

    for parser_type, form_type in PARSER_FORM_MAP.items():
        sec_latest_date = latest_sec_filings.get(form_type)
        if sec_latest_date is None:
            continue

        log_entry = get_processing_log(session, cik, parser_type)
        if log_entry is None:
            needed.append(parser_type)
        elif sec_latest_date > log_entry.latest_filing_date_seen:
            needed.append(parser_type)

    return needed


def run_parser_for_cik(cik, parser_type):
    """Dispatch to the correct parser function for a single CIK."""
    from etf_pipeline.parsers.nport import parse_nport
    from etf_pipeline.parsers.ncsr import parse_ncsr
    from etf_pipeline.parsers.prospectus import parse_prospectus
    from etf_pipeline.parsers.finhigh import parse_finhigh
    from etf_pipeline.parsers.flows import parse_flows

    parser_map = {
        "nport": parse_nport,
        "ncsr": parse_ncsr,
        "prospectus": parse_prospectus,
        "finhigh": parse_finhigh,
        "flows": parse_flows,
    }

    parser_func = parser_map[parser_type]
    parser_func(ciks=[cik], clear_cache=False)


@main.command()
@click.option("--limit", type=int, help="Process only the first N CIKs")
def run_all(limit):
    """Run the full pipeline with per-CIK orchestration and freshness detection."""
    import logging
    from edgar.storage_management import clear_cache as edgar_clear_cache
    from sqlalchemy.orm import sessionmaker

    from etf_pipeline.db import get_engine
    from etf_pipeline.models import Base
    from etf_pipeline.discover import fetch
    from etf_pipeline.load_etfs import load_etfs

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    click.echo("--- Step 0: Ensuring database tables exist ---")
    engine = get_engine()
    Base.metadata.create_all(engine)

    click.echo("--- Step 1: Discovering ETF tickers ---")
    fetch()

    click.echo("--- Step 2: Loading ETFs into database ---")
    load_etfs(limit=limit)

    click.echo("--- Step 3: Per-CIK processing with freshness detection ---")

    session_factory = sessionmaker(bind=engine)
    with session_factory() as session:
        ciks = get_all_ciks(session, limit)

        if not ciks:
            click.echo("No ETFs found in database.")
            return

        click.echo(f"Found {len(ciks)} CIKs to check")

    processed = 0
    skipped = 0
    failed = 0

    for cik in ciks:
        try:
            with session_factory() as session:
                click.echo(f"\nChecking CIK {cik}...")

                latest_sec_filings = check_sec_filing_dates(cik)
                stale_parsers = get_stale_parsers(session, cik, latest_sec_filings)

                if not stale_parsers:
                    click.echo(f"  No new filings for CIK {cik}, skipping")
                    skipped += 1
                    continue

                click.echo(f"  Running parsers for CIK {cik}: {', '.join(stale_parsers)}")

                for parser_type in PARSER_ORDER:
                    if parser_type in stale_parsers:
                        try:
                            run_parser_for_cik(cik, parser_type)
                        except Exception as e:
                            click.echo(f"  Failed {parser_type} for CIK {cik}: {e}")
                            raise

                edgar_clear_cache(dry_run=False)
                processed += 1

        except Exception as e:
            click.echo(f"  Failed to process CIK {cik}: {e}")
            failed += 1

    click.echo("\n--- Step 4: Pipeline complete ---")
    click.echo(f"Summary: {processed} CIKs processed, {skipped} CIKs skipped (no new filings), {failed} CIKs failed")
