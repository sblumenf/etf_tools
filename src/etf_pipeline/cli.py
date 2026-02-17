import logging
import multiprocessing
import queue
import time
from datetime import date

import click

logger = logging.getLogger(__name__)


def _configure_logging():
    """Configure logging with external library noise suppressed."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    # Suppress noisy HTTP/cache library loggers — only show warnings and errors
    for noisy_logger in (
        "httpx",
        "httpcore",
        "httpxthrottlecache",
        "httpxthrottlecache.controller",
        "httpxthrottlecache.filecache.transport",
        "httpxthrottlecache.ratelimiter",
    ):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)


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
    from etf_pipeline.load_etfs import load_etfs

    _configure_logging()

    load_etfs(cik=cik, limit=limit)


@main.command()
@click.option("--cik", type=str, help="Process only this CIK")
@click.option("--limit", type=int, help="Process only the first N CIKs")
@click.option("--keep-cache", is_flag=True, default=False, help="Keep edgartools HTTP cache after processing (default: clear)")
def nport(cik, limit, keep_cache):
    """Parse NPORT-P filings for holdings and derivatives."""
    from etf_pipeline.parsers.nport import parse_nport

    _configure_logging()

    parse_nport(cik=cik, limit=limit, clear_cache=not keep_cache)


@main.command()
@click.option("--cik", type=str, help="Process only this CIK")
@click.option("--limit", type=int, help="Process only the first N CIKs")
@click.option("--keep-cache", is_flag=True, default=False, help="Keep edgartools HTTP cache after processing (default: clear)")
def ncsr(cik, limit, keep_cache):
    """Parse N-CSR filings for performance data."""
    from etf_pipeline.parsers.ncsr import parse_ncsr

    _configure_logging()

    parse_ncsr(cik=cik, limit=limit, clear_cache=not keep_cache)


@main.command()
@click.option("--cik", type=str, help="Process only this CIK")
@click.option("--limit", type=int, help="Process only the first N CIKs")
@click.option("--keep-cache", is_flag=True, default=False,
              help="Keep edgartools HTTP cache after processing (default: clear)")
def prospectus(cik, limit, keep_cache):
    """Parse 485BPOS filings for fee schedules, shareholder fees, and strategy."""
    from etf_pipeline.parsers.prospectus import parse_prospectus
    _configure_logging()
    parse_prospectus(cik=cik, limit=limit, clear_cache=not keep_cache)


@main.command()
@click.option("--cik", type=str, help="Process only this CIK")
@click.option("--limit", type=int, help="Process only the first N CIKs")
@click.option("--keep-cache", is_flag=True, default=False, help="Keep edgartools HTTP cache after processing (default: clear)")
def flows(cik, limit, keep_cache):
    """Parse 24F-2NT filings for fund flow data."""
    from etf_pipeline.parsers.flows import parse_flows

    _configure_logging()

    parse_flows(cik=cik, limit=limit, clear_cache=not keep_cache)


@main.command()
@click.option("--cik", type=str, help="Process only this CIK")
@click.option("--limit", type=int, help="Process only the first N CIKs")
@click.option("--keep-cache", is_flag=True, default=False, help="Keep edgartools HTTP cache after processing (default: clear)")
def finhigh(cik, limit, keep_cache):
    """Parse N-CSR filings for Financial Highlights data (per-share operating, distributions, ratios)."""
    from etf_pipeline.parsers.finhigh import parse_finhigh

    _configure_logging()

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


def check_sec_filing_dates(cik: str) -> tuple[dict[str, date | None], bool]:
    """Check SEC for latest filing date per form type using a single API call.

    Returns (result_dict, had_error). If had_error is True, None values
    in result_dict mean "check failed", not "no filings found".
    """
    from edgar import Company
    from etf_pipeline.parser_utils import ensure_date

    form_types = {"NPORT-P", "N-CSR", "485BPOS", "24F-2NT"}
    result = {ft: None for ft in form_types}
    had_error = False

    try:
        company = Company(cik)
        filings = company.get_filings(form=list(form_types))

        for filing in filings:
            form = filing.form
            if form in form_types and result[form] is None:
                result[form] = ensure_date(filing.filing_date)
                if all(v is not None for v in result.values()):
                    break

        del filings
        del company

    except Exception as e:
        logger.warning("CIK %s: Failed to check SEC filing dates: %s", cik, e)
        had_error = True

    return result, had_error


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


def get_stale_parsers(session, cik, latest_sec_filings, check_failed=False):
    """Return list of parser_types that need to run for this CIK.

    A parser is needed if:
    - Never processed before (no processing_log entry)
    - New filing available (SEC latest date > log's latest_filing_date_seen)
    - Filing date check failed and parser was never processed (check_failed=True)
    """
    needed = []

    for parser_type, form_type in PARSER_FORM_MAP.items():
        sec_latest_date = latest_sec_filings.get(form_type)
        if sec_latest_date is None:
            if check_failed:
                log_entry = get_processing_log(session, cik, parser_type)
                if log_entry is None:
                    needed.append(parser_type)
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
    parser_func(ciks=[cik], clear_cache=True)


def process_single_cik(cik, parser_order, parser_form_map):
    """Subprocess entry point: process a single CIK with its own DB session.

    Returns dict with keys:
    - status: "processed", "skipped", or "failed"
    - failed_parsers: list of strings like "nport(CIK)"
    - warning: optional string if SEC check failed
    """
    _configure_logging()

    from sqlalchemy.orm import sessionmaker
    from etf_pipeline.db import get_engine

    result = {
        "status": "failed",
        "failed_parsers": [],
        "warning": None
    }

    engine = None
    session = None

    try:
        engine = get_engine()
        session_factory = sessionmaker(bind=engine)
        session = session_factory()

        latest_sec_filings, check_failed = check_sec_filing_dates(cik)
        if check_failed:
            result["warning"] = f"SEC filing date check failed for CIK {cik}, will attempt unprocessed parsers"

        stale_parsers = get_stale_parsers(session, cik, latest_sec_filings, check_failed=check_failed)

        if not stale_parsers:
            result["status"] = "skipped"
            session.close()
            engine.dispose()
            return result

        for parser_type in parser_order:
            if parser_type in stale_parsers:
                try:
                    run_parser_for_cik(cik, parser_type)
                except Exception as e:
                    logger.error(f"Failed {parser_type} for CIK {cik}: {e}")
                    result["failed_parsers"].append(f"{parser_type}({cik})")

        result["status"] = "processed"

    except Exception as e:
        logger.error(f"Failed to process CIK {cik}: {e}")
        result["status"] = "failed"

    finally:
        if session is not None:
            session.close()
        if engine is not None:
            engine.dispose()

    return result


def _worker_process_cik(result_queue, cik, parser_order, parser_form_map):
    """Worker function for multiprocessing: calls process_single_cik and puts result in queue."""
    result = process_single_cik(cik, parser_order, parser_form_map)
    result_queue.put(result)


@main.command()
@click.option("--limit", type=int, help="Process only the first N CIKs")
def run_all(limit):
    """Run the full pipeline with per-CIK orchestration and freshness detection."""
    from sqlalchemy.orm import sessionmaker

    from etf_pipeline.db import get_engine
    from etf_pipeline.models import Base
    from etf_pipeline.discover import fetch
    from etf_pipeline.load_etfs import load_etfs

    _configure_logging()

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
    failed_parsers = []

    ctx = multiprocessing.get_context('spawn')

    for cik in ciks:
        click.echo(f"\nChecking CIK {cik}...")
        start_time = time.time()

        result_queue = ctx.Queue()

        proc = ctx.Process(target=_worker_process_cik, args=(result_queue, cik, PARSER_ORDER, PARSER_FORM_MAP))
        proc.start()
        proc.join(timeout=600)

        if proc.is_alive():
            proc.terminate()
            proc.join()
            duration = time.time() - start_time
            click.echo(f"  Process timed out for CIK {cik} ({duration:.1f}s)")
            failed += 1
            continue

        if proc.exitcode != 0:
            duration = time.time() - start_time
            click.echo(f"  Process crashed for CIK {cik} (exit code: {proc.exitcode}, {duration:.1f}s)")
            failed += 1
            continue

        try:
            result = result_queue.get(timeout=5)
        except queue.Empty:
            duration = time.time() - start_time
            click.echo(f"  No result received from subprocess for CIK {cik} ({duration:.1f}s)")
            failed += 1
            continue

        duration = time.time() - start_time

        if result["warning"]:
            click.echo(f"  Warning: {result['warning']}")

        if result["status"] == "skipped":
            click.echo(f"  No new filings for CIK {cik}, skipping ({duration:.1f}s)")
            skipped += 1
        elif result["status"] == "processed":
            click.echo(f"  Completed processing for CIK {cik} in {duration:.1f}s")
            processed += 1
            if result["failed_parsers"]:
                for fp in result["failed_parsers"]:
                    click.echo(f"  Failed parser: {fp}")
                failed_parsers.extend(result["failed_parsers"])
        elif result["status"] == "failed":
            click.echo(f"  Failed to process CIK {cik} ({duration:.1f}s)")
            failed += 1
            if result["failed_parsers"]:
                failed_parsers.extend(result["failed_parsers"])

    click.echo("\n--- Step 4: Pipeline complete ---")
    click.echo(f"Summary: {processed} CIKs processed, {skipped} CIKs skipped (no new filings), {failed} CIKs failed")
    if failed_parsers:
        click.echo(f"Failed parsers: {', '.join(failed_parsers)}")
