from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from etf_pipeline.api.deps import get_db
from etf_pipeline.api.schemas.xray import (
    AssetAllocationData,
    AssetCategoryItem,
    ConcentrationData,
    CountryItem,
    DataCompleteness,
    FeeData,
    FundHealthData,
    GeographicData,
    HoldingItem,
    HoldingsData,
    LiquidityData,
    LiquidityItem,
    PerformanceData,
    PerformanceInterval,
    XRayResponse,
)
from etf_pipeline.xray import service
from etf_pipeline.xray.calculations import compute_hhi, compute_top_n_weight
from etf_pipeline.xray.service import ASSET_CATEGORY_MAP, LIQUIDITY_MAP

router = APIRouter(prefix="/api/v1/xray", tags=["xray"])


def _country_name(code: str) -> str:
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
    return COUNTRY_NAMES.get(code.upper(), code)


@router.get("/{ticker}", response_model=XRayResponse)
def get_xray(ticker: str, db: Session = Depends(get_db)):
    etf = service.get_etf(db, ticker)
    if not etf:
        raise HTTPException(status_code=404, detail="ETF not found")

    holdings = service.get_holdings(db, etf.id)
    fees = service.get_fees(db, etf.id)
    perf = service.get_performance(db, etf.id)
    snapshot = service.get_fund_snapshot(db, etf.cik)
    latest_flow = service.get_latest_flow(db, etf.id, etf.cik)

    holdings_data = None
    concentration_data = None
    asset_allocation_data = None
    geographic_data = None
    liquidity_data = None

    if holdings:
        sorted_holdings = sorted(holdings, key=lambda h: (h.pct_val or 0), reverse=True)
        total_count = len(sorted_holdings)
        n = 10
        top_n = sorted_holdings[:n]
        other_pct = sum((h.pct_val or 0) for h in sorted_holdings[n:]) if total_count > n else None

        holdings_data = HoldingsData(
            total_count=total_count,
            items=[
                HoldingItem(
                    name=h.name or "",
                    ticker=h.ticker,
                    value_usd=float(h.value_usd) if h.value_usd is not None else None,
                    pct_val=float(h.pct_val) if h.pct_val is not None else None,
                )
                for h in top_n
            ],
            other_pct=float(other_pct) if other_pct is not None else None,
        )

        # asset allocation
        asset_groups = defaultdict(lambda: {"pct": 0.0, "value_usd": 0.0})
        for h in holdings:
            code = h.asset_category or "OTHER"
            asset_groups[code]["pct"] += float(h.pct_val or 0)
            asset_groups[code]["value_usd"] += float(h.value_usd or 0)
        asset_allocation_data = AssetAllocationData(
            items=[
                AssetCategoryItem(
                    code=code,
                    display_name=ASSET_CATEGORY_MAP.get(code, code),
                    pct=round(data["pct"], 4),
                    value_usd=data["value_usd"] or None,
                )
                for code, data in sorted(asset_groups.items(), key=lambda x: -x[1]["pct"])
            ]
        )

        # geographic
        country_groups: dict[str, float] = defaultdict(float)
        for h in holdings:
            if h.country:
                country_groups[h.country] += float(h.pct_val or 0)
        if country_groups:
            country_items = [
                CountryItem(
                    country_code=code,
                    country_name=_country_name(code),
                    pct=round(pct, 4),
                )
                for code, pct in sorted(country_groups.items(), key=lambda x: -x[1])[:20]
            ]
            geographic_data = GeographicData(items=country_items)

        # liquidity
        liquidity_groups: dict[str, float] = defaultdict(float)
        for h in holdings:
            liq = h.liquidity_classification
            if liq:
                liquidity_groups[liq] += float(h.pct_val or 0)
        if liquidity_groups:
            liq_order = ["HLI", "MLI", "LLI", "ILI"]
            items = []
            for code in liq_order:
                if code in liquidity_groups:
                    display, color = LIQUIDITY_MAP.get(code, (code, "gray"))
                    items.append(
                        LiquidityItem(
                            code=code,
                            display_name=display,
                            color=color,
                            pct=round(liquidity_groups[code], 4),
                        )
                    )
            liquidity_data = LiquidityData(items=items)

        # concentration
        weights = [float(h.pct_val) for h in sorted_holdings if h.pct_val is not None]
        hhi = compute_hhi(weights) if weights else None
        top5 = compute_top_n_weight(weights, 5) if weights else None
        top10 = compute_top_n_weight(weights, 10) if weights else None
        top20 = compute_top_n_weight(weights, 20) if weights else None
        treemap_rows = sorted_holdings[:20]
        other_treemap_pct = sum(float(h.pct_val or 0) for h in sorted_holdings[20:]) if total_count > 20 else None
        treemap_items = [
            HoldingItem(
                name=h.name or "",
                ticker=h.ticker,
                value_usd=float(h.value_usd) if h.value_usd is not None else None,
                pct_val=float(h.pct_val) if h.pct_val is not None else None,
            )
            for h in treemap_rows
        ]
        if other_treemap_pct:
            treemap_items.append(
                HoldingItem(name="Other", ticker=None, value_usd=None, pct_val=other_treemap_pct)
            )
        concentration_data = ConcentrationData(
            hhi=hhi,
            top5_weight=top5,
            top10_weight=top10,
            top20_weight=top20,
            treemap_items=treemap_items,
        )

    # fees card
    # FeeExpense fields: total_expense_gross, total_expense_net, fee_waiver_expiration_date
    fees_data = None
    if fees:
        waiver_expiring_soon = False
        waiver_exp_str = None
        if fees.fee_waiver_expiration_date:
            waiver_exp_str = str(fees.fee_waiver_expiration_date)
            try:
                exp = (
                    fees.fee_waiver_expiration_date
                    if isinstance(fees.fee_waiver_expiration_date, date)
                    else date.fromisoformat(str(fees.fee_waiver_expiration_date))
                )
                if exp <= date.today() + timedelta(days=180):
                    waiver_expiring_soon = True
            except Exception:
                pass
        fees_data = FeeData(
            management_fee=float(fees.management_fee) if fees.management_fee is not None else None,
            distribution_12b1=float(fees.distribution_12b1) if fees.distribution_12b1 is not None else None,
            other_expenses=float(fees.other_expenses) if fees.other_expenses is not None else None,
            acquired_fund_fees=float(fees.acquired_fund_fees) if fees.acquired_fund_fees is not None else None,
            gross_expense_ratio=float(fees.total_expense_gross) if fees.total_expense_gross is not None else None,
            net_expense_ratio=float(fees.total_expense_net) if fees.total_expense_net is not None else None,
            fee_waiver=float(fees.fee_waiver) if fees.fee_waiver is not None else None,
            waiver_expiration=waiver_exp_str,
            waiver_expiring_soon=waiver_expiring_soon,
        )

    # performance card
    # Performance fields: return_1yr, return_5yr, return_10yr, return_since_inception,
    #   benchmark_return_1yr, benchmark_return_5yr, benchmark_return_10yr,
    #   benchmark_name, portfolio_turnover (no inception benchmark return)
    perf_data = None
    if perf:
        intervals = []
        for label, fund_r, bench_r in [
            ("1 Year", perf.return_1yr, perf.benchmark_return_1yr),
            ("5 Year", perf.return_5yr, perf.benchmark_return_5yr),
            ("10 Year", perf.return_10yr, perf.benchmark_return_10yr),
            ("Since Inception", perf.return_since_inception, None),
        ]:
            fund_r_f = float(fund_r) if fund_r is not None else None
            bench_r_f = float(bench_r) if bench_r is not None else None
            if fund_r_f is not None or bench_r_f is not None:
                alpha = (fund_r_f - bench_r_f) if (fund_r_f is not None and bench_r_f is not None) else None
                intervals.append(
                    PerformanceInterval(
                        label=label,
                        fund_return=fund_r_f,
                        benchmark_return=bench_r_f,
                        alpha=alpha,
                    )
                )
        perf_data = PerformanceData(
            benchmark_name=perf.benchmark_name,
            turnover_rate=float(perf.portfolio_turnover) if perf.portfolio_turnover is not None else None,
            intervals=intervals,
        )

    # fund health card
    # FundSnapshot uses cik (queried above), fields: net_assets, total_assets, total_liabilities,
    #   amt_pay_one_yr_banks_borr, amt_pay_aft_one_yr_banks_borr, etc. — no single total_borrowings field
    fund_health_data = None
    if snapshot:
        net_assets = snapshot.net_assets
        # Sum all borrowing-related payables as a proxy for total borrowings
        borrowing_fields = [
            snapshot.amt_pay_one_yr_banks_borr,
            snapshot.amt_pay_one_yr_ctrld_comp,
            snapshot.amt_pay_one_yr_oth_affil,
            snapshot.amt_pay_one_yr_other,
            snapshot.amt_pay_aft_one_yr_banks_borr,
            snapshot.amt_pay_aft_one_yr_ctrld_comp,
            snapshot.amt_pay_aft_one_yr_oth_affil,
            snapshot.amt_pay_aft_one_yr_other,
        ]
        total_borrowings_val = sum(float(f) for f in borrowing_fields if f is not None)
        total_borrowings = total_borrowings_val if total_borrowings_val > 0 else None

        net_assets_f = float(net_assets) if net_assets else None
        leverage = (
            (total_borrowings_val / float(net_assets))
            if (total_borrowings and net_assets and float(net_assets) != 0)
            else 0.0
        )

        # cash_not_reported is the closest field for uninvested cash
        cash_pct = None
        if snapshot.cash_not_reported is not None and net_assets and float(net_assets) != 0:
            cash_pct = float(snapshot.cash_not_reported) / float(net_assets) * 100

        fund_health_data = FundHealthData(
            total_net_assets=net_assets_f,
            total_borrowings=total_borrowings,
            leverage_ratio=leverage,
            cash_position_pct=cash_pct,
            latest_net_flow=latest_flow,
        )

    completeness = DataCompleteness(
        holdings=bool(holdings),
        fees=fees_data is not None,
        performance=perf_data is not None,
        fund_health=fund_health_data is not None,
        liquidity=liquidity_data is not None,
        geographic=geographic_data is not None,
        concentration=concentration_data is not None,
    )

    return XRayResponse(
        ticker=etf.ticker,
        name=etf.fund_name or "",
        filing_date=None,
        data_completeness=completeness,
        holdings=holdings_data,
        asset_allocation=asset_allocation_data,
        geographic=geographic_data,
        liquidity=liquidity_data,
        fees=fees_data,
        performance=perf_data,
        fund_health=fund_health_data,
        concentration=concentration_data,
    )
