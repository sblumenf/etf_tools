from sqlalchemy.orm import Session
from sqlalchemy import func, desc, case
from etf_pipeline.models import ETF, Holding, FeeExpense, Performance, FundSnapshot, NPORTMonthlyFlow, FlowData

ASSET_CATEGORY_MAP = {
    "EC": "Equity - Common",
    "EP": "Equity - Preferred",
    "DBT": "Debt",
    "FI": "Fixed Income",
    "STIV": "Cash Equivalent",
    "ABS": "Asset-Backed Security",
    "ABS-MBS": "Mortgage-Backed Securities",
    "ABS-O": "Other ABS",
    "ABS-CBDO": "CDO/CLO",
    "ABS-APCP": "Asset-Backed Commercial Paper",
    "MBS": "Mortgage-Backed Security",
    "UST": "US Treasury",
    "LON": "Loan",
    "RA": "Repurchase Agreement",
    "SN": "Structured Note",
    "RE": "Real Estate",
    "COMM": "Commodity",
    "OTHER": "Other",
}

LIQUIDITY_MAP = {
    "HLI": ("Highly Liquid", "green"),
    "MLI": ("Moderately Liquid", "yellow"),
    "LLI": ("Less Liquid", "orange"),
    "ILI": ("Illiquid", "red"),
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
        .order_by(desc(Performance.fiscal_year_end))
        .first()
    )


def get_fund_snapshot(db: Session, cik: str) -> FundSnapshot | None:
    return (
        db.query(FundSnapshot)
        .filter(FundSnapshot.cik == cik)
        .order_by(desc(FundSnapshot.report_date))
        .first()
    )


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
