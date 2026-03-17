from datetime import date
from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, case
from etf_pipeline.models import ETF, Holding, FeeExpense, Performance, FundSnapshot, NPORTMonthlyFlow, FlowData, NPORTMonthlyReturn

ASSET_CATEGORY_MAP = {
    # Equity
    "EC": "Equity - Common",
    "EP": "Equity - Preferred",
    # Debt
    "DBT": "Debt",
    "SN": "Structured Note",
    "LON": "Loan",
    # Asset-Backed
    "ABS-MBS": "Mortgage-Backed Securities",
    "ABS-O": "Other ABS",
    "ABS-CBDO": "CDO/CLO",
    "ABS-APCP": "Asset-Backed Commercial Paper",
    # Derivatives
    "DCO": "Derivative - Commodity",
    "DCR": "Derivative - Credit",
    "DE": "Derivative - Equity",
    "DFE": "Derivative - Foreign Exchange",
    "DIR": "Derivative - Interest Rate",
    "DO": "Derivative - Other",
    # Other
    "STIV": "Cash & Equivalents",
    "RA": "Repurchase Agreement",
    "RE": "Real Estate",
    "COMM": "Commodity",
    "OTHER": "Other",
}

COUNTRY_NAMES = {
    "US": "United States", "USA": "United States",
    "GB": "United Kingdom", "GBR": "United Kingdom",
    "JP": "Japan", "JPN": "Japan",
    "DE": "Germany", "DEU": "Germany",
    "FR": "France", "FRA": "France",
    "CA": "Canada", "CAN": "Canada",
    "AU": "Australia", "AUS": "Australia",
    "CN": "China", "CHN": "China",
    "KR": "South Korea", "KOR": "South Korea",
    "CH": "Switzerland", "CHE": "Switzerland",
    "NL": "Netherlands", "NLD": "Netherlands",
    "SE": "Sweden", "SWE": "Sweden",
    "DK": "Denmark", "DNK": "Denmark",
    "HK": "Hong Kong", "HKG": "Hong Kong",
    "TW": "Taiwan", "TWN": "Taiwan",
    "IN": "India", "IND": "India",
    "BR": "Brazil", "BRA": "Brazil",
    "SG": "Singapore", "SGP": "Singapore",
    "IT": "Italy", "ITA": "Italy",
    "ES": "Spain", "ESP": "Spain",
    "XX": "Unknown",
}


def resolve_country_name(code: str) -> str:
    return COUNTRY_NAMES.get(code.upper(), code)


def get_etf(db: Session, ticker: str) -> ETF | None:
    return db.query(ETF).filter(ETF.ticker == ticker.upper()).first()


def search_etfs(db: Session, q: str, limit: int = 20) -> list[ETF]:
    if not q.strip():
        return []
    q_upper = q.upper()
    return (
        db.query(ETF)
        .filter(
            func.upper(ETF.ticker).contains(q_upper) |
            func.upper(ETF.fund_name).contains(q_upper)
        )
        .order_by(
            case((func.upper(ETF.ticker) == q_upper, 0), else_=1)
        )
        .limit(limit)
        .all()
    )


def get_holdings(db: Session, etf_id: int) -> list[Holding]:
    max_date_subq = (
        db.query(func.max(Holding.report_date))
        .filter(Holding.etf_id == etf_id)
        .scalar_subquery()
    )
    return (
        db.query(Holding)
        .filter(Holding.etf_id == etf_id)
        .filter(Holding.report_date == max_date_subq)
        .order_by(desc(Holding.pct_val))
        .all()
    )


def get_fees(db: Session, etf_id: int) -> FeeExpense | None:
    return (
        db.query(FeeExpense)
        .filter(FeeExpense.etf_id == etf_id)
        .order_by(desc(FeeExpense.effective_date))
        .first()
    )


def get_performance(db: Session, etf_id: int) -> Performance | None:
    return (
        db.query(Performance)
        .filter(Performance.etf_id == etf_id)
        .order_by(
            desc(Performance.fiscal_year_end),
            case((Performance.return_1yr.isnot(None), 0), else_=1),
            desc(Performance.filing_date),
        )
        .first()
    )


def get_fund_snapshot(db: Session, cik: str, series_id: str = "", report_date=None) -> FundSnapshot | None:
    q = db.query(FundSnapshot).filter(FundSnapshot.cik == cik)
    q = q.filter(FundSnapshot.series_id == series_id)
    if report_date:
        q = q.filter(FundSnapshot.report_date == report_date)
    return q.order_by(desc(FundSnapshot.report_date)).first()


def get_latest_flow(db: Session, etf_id: int, cik: str) -> float | None:
    """Get latest net flow from nport_monthly_flow or flow_data."""
    nport_flow = (
        db.query(NPORTMonthlyFlow)
        .filter(NPORTMonthlyFlow.etf_id == etf_id)
        .order_by(desc(NPORTMonthlyFlow.report_date))
        .first()
    )
    if nport_flow:
        sales = nport_flow.month_1_sales or 0
        redemptions = nport_flow.month_1_redemptions or 0
        if nport_flow.month_1_sales is not None or nport_flow.month_1_redemptions is not None:
            return float(sales) - float(redemptions)

    flow = (
        db.query(FlowData)
        .filter(FlowData.cik == cik)
        .order_by(desc(FlowData.fiscal_year_end))
        .first()
    )
    if flow and flow.net_sales is not None:
        return float(flow.net_sales)
    return None


def compute_performance_from_monthly(db: Session, etf_id: int) -> dict | None:
    rows = (
        db.query(NPORTMonthlyReturn)
        .filter(NPORTMonthlyReturn.etf_id == etf_id)
        .order_by(desc(NPORTMonthlyReturn.report_date))
        .all()
    )
    if not rows:
        return None

    # Build a dict of month_key (year, month) -> return value (float percent)
    # Each filing's report_date is the end of the 3-month period.
    # month_1 = report_date month, month_2 = 1 month prior, month_3 = 2 months prior.
    # Process filings newest-first; skip months already seen to avoid double-counting.
    monthly_returns: dict[tuple[int, int], float] = {}
    for row in rows:
        rd = row.report_date
        for offset, val in [(0, row.month_1_return), (1, row.month_2_return), (2, row.month_3_return)]:
            if val is None:
                continue
            month_date = rd - relativedelta(months=offset)
            key = (month_date.year, month_date.month)
            if key not in monthly_returns:
                monthly_returns[key] = float(val)

    if not monthly_returns:
        return None

    # Sort months descending (newest first)
    sorted_months = sorted(monthly_returns.keys(), reverse=True)

    def compound(keys: list[tuple[int, int]]) -> float:
        result = 1.0
        for k in keys:
            result *= 1.0 + monthly_returns[k] / 100.0
        return result - 1.0

    result = {}

    # 1yr: need at least 12 months
    if len(sorted_months) >= 12:
        keys_1yr = sorted_months[:12]
        result["return_1yr"] = compound(keys_1yr) * 100.0

    # 5yr: need at least 60 months
    if len(sorted_months) >= 60:
        keys_5yr = sorted_months[:60]
        cum = compound(keys_5yr)
        annualized = ((1.0 + cum) ** (1.0 / 5.0) - 1.0) * 100.0
        result["return_5yr"] = annualized

    if not result:
        return None

    return result
