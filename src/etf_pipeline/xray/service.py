from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from etf_pipeline.models import ETF, Holding, FeeExpense, Performance, FundSnapshot, NPORTMonthlyFlow, FlowData
from etf_pipeline.xray.calculations import compute_hhi, compute_top_n_weight

ASSET_CATEGORY_MAP = {
    "EC": "Equity - Common",
    "EP": "Equity - Preferred",
    "DBT": "Debt",
    "FI": "Fixed Income",
    "STIV": "Cash Equivalent",
    "ABS": "Asset-Backed Security",
    "MBS": "Mortgage-Backed Security",
    "UST": "US Treasury",
    "OTHER": "Other",
}

LIQUIDITY_MAP = {
    "HLI": ("Highly Liquid", "green"),
    "MLI": ("Moderately Liquid", "yellow"),
    "LLI": ("Less Liquid", "orange"),
    "ILI": ("Illiquid", "red"),
}


def get_etf(db: Session, ticker: str) -> ETF | None:
    return db.query(ETF).filter(func.upper(ETF.ticker) == ticker.upper()).first()


def search_etfs(db: Session, q: str, limit: int = 20) -> list[ETF]:
    """Search ETFs by ticker or name. Exact ticker match first."""
    if not q.strip():
        return []
    q_upper = q.upper()
    exact = db.query(ETF).filter(func.upper(ETF.ticker) == q_upper).all()
    partial = (
        db.query(ETF)
        .filter(
            func.upper(ETF.ticker).contains(q_upper) |
            func.upper(ETF.fund_name).contains(q_upper)
        )
        .filter(func.upper(ETF.ticker) != q_upper)
        .limit(limit - len(exact))
        .all()
    )
    return (exact + partial)[:limit]


def get_holdings(db: Session, etf_id: int) -> list[Holding]:
    return (
        db.query(Holding)
        .filter(Holding.etf_id == etf_id)
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
