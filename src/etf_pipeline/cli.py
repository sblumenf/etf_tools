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


@main.command()
def nport():
    """Parse NPORT-P filings for holdings and derivatives."""
    click.echo("nport: not yet implemented")


@main.command()
def ncsr():
    """Parse N-CSR filings for performance data."""
    click.echo("ncsr: not yet implemented")


@main.command()
def prospectus():
    """Parse 485BPOS filings for fee schedules and strategy."""
    click.echo("prospectus: not yet implemented")


@main.command()
def flows():
    """Parse 24F-2NT filings for fund flow data."""
    click.echo("flows: not yet implemented")


@main.command()
def run_all():
    """Run the full pipeline: discover + all parsers."""
    click.echo("run-all: not yet implemented")
