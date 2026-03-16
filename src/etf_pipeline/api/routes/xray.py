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
    PerformanceData,
    PerformanceInterval,
    XRayResponse,
)
from etf_pipeline.xray import service
from etf_pipeline.xray.calculations import compute_hhi, compute_top_n_weight
from etf_pipeline.xray.service import ASSET_CATEGORY_MAP, resolve_country_name

router = APIRouter(prefix="/api/v1/xray", tags=["xray"])

_ALLOC_COMPLETENESS_THRESHOLD = 95.0  # percent; below this, add "Unallocated" row


def _cash_pct(cash_not_reported, net_assets):
    if cash_not_reported is None or net_assets is None:
        return None
    cash_val = float(cash_not_reported)
    net = float(net_assets)
    if net == 0 or cash_val == 0:
        return None
    return (cash_val / net) * 100


@router.get("/{ticker}", response_model=XRayResponse)
def get_xray(ticker: str, db: Session = Depends(get_db)):
    etf = service.get_etf(db, ticker)
    if not etf:
        raise HTTPException(status_code=404, detail="ETF not found")

    holdings = service.get_holdings(db, etf.id)
    fees = service.get_fees(db, etf.id)
    perf = service.get_performance(db, etf.id)
    holdings_report_date = holdings[0].report_date if holdings else None
    snapshot = service.get_fund_snapshot(db, etf.cik, etf.series_id or "", report_date=holdings_report_date)
    latest_flow = service.get_latest_flow(db, etf.id, etf.cik)

    holdings_data = None
    concentration_data = None
    asset_allocation_data = None
    geographic_data = None

    if holdings:
        total_count = len(holdings)

        holdings_data = HoldingsData(
            total_count=total_count,
            items=[
                HoldingItem(
                    name=h.name or "",
                    ticker=h.ticker,
                    value_usd=float(h.value_usd) if h.value_usd is not None else None,
                    pct_val=float(h.pct_val) if h.pct_val is not None else None,
                )
                for h in holdings
            ],
        )

        # asset allocation
        asset_groups = defaultdict(lambda: {"pct": 0.0, "value_usd": 0.0})
        for h in holdings:
            code = h.asset_category or "OTHER"
            asset_groups[code]["pct"] += float(h.pct_val or 0)
            asset_groups[code]["value_usd"] += float(h.value_usd or 0)

        # Merge snapshot cash into STIV bucket before building items
        if snapshot and snapshot.cash_not_reported is not None:
            computed_cash_pct = _cash_pct(snapshot.cash_not_reported, snapshot.net_assets)
            if computed_cash_pct is not None:
                cash_val = float(snapshot.cash_not_reported)
                asset_groups["STIV"]["pct"] += computed_cash_pct
                asset_groups["STIV"]["value_usd"] += cash_val

        # Build allocation items once
        allocation_items = [
            AssetCategoryItem(
                code=code,
                display_name=ASSET_CATEGORY_MAP.get(code, code),
                pct=round(data["pct"], 4),
                value_usd=data["value_usd"] or None,
            )
            for code, data in sorted(asset_groups.items(), key=lambda x: -x[1]["pct"])
        ]
        total_alloc_pct = sum(item.pct for item in allocation_items)
        if total_alloc_pct < _ALLOC_COMPLETENESS_THRESHOLD:
            allocation_items.append(
                AssetCategoryItem(
                    code="UNALLOC",
                    display_name="Unallocated / Other",
                    pct=round(100.0 - total_alloc_pct, 4),
                    value_usd=None,
                )
            )
        asset_allocation_data = AssetAllocationData(items=allocation_items)

        # geographic
        country_groups: dict[str, float] = defaultdict(float)
        for h in holdings:
            code = h.country or "XX"
            country_groups[code] += float(h.pct_val or 0)
        if country_groups:
            country_items = [
                CountryItem(
                    country_code=code,
                    country_name=resolve_country_name(code),
                    pct=round(pct, 4),
                )
                for code, pct in sorted(country_groups.items(), key=lambda x: -x[1])[:20]
            ]
            geographic_data = GeographicData(items=country_items)

        # concentration
        weights = [float(h.pct_val or 0) for h in holdings]
        hhi = compute_hhi(weights) if weights else None
        top5 = compute_top_n_weight(weights, 5) if weights else None
        top10 = compute_top_n_weight(weights, 10) if weights else None
        top20 = compute_top_n_weight(weights, 20) if weights else None
        treemap_rows = holdings[:20]
        other_treemap_pct = sum(float(h.pct_val or 0) for h in holdings[20:]) if total_count > 20 else None
        treemap_data = [
            HoldingItem(
                name=h.name or "",
                ticker=h.ticker,
                value_usd=float(h.value_usd) if h.value_usd is not None else None,
                pct_val=float(h.pct_val) if h.pct_val is not None else None,
            )
            for h in treemap_rows
        ]
        if other_treemap_pct:
            treemap_data.append(
                HoldingItem(name="Other", ticker=None, value_usd=None, pct_val=other_treemap_pct)
            )
        concentration_data = ConcentrationData(
            hhi=hhi,
            top5_weight=top5,
            top10_weight=top10,
            top20_weight=top20,
            treemap_data=treemap_data,
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
        # Resolve benchmark to readable name
        benchmark_display = perf.benchmark_name
        if perf.benchmark_name:
            from etf_pipeline.models import BenchmarkMapping
            mapping = db.query(BenchmarkMapping).filter_by(member_id=perf.benchmark_name).first()
            if mapping and mapping.readable_name:
                benchmark_display = mapping.readable_name

        perf_data = PerformanceData(
            benchmark_name=benchmark_display,
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
        has_borrowing_data = any(f is not None for f in borrowing_fields)
        total_borrowings_val = sum(float(f or 0) for f in borrowing_fields)
        total_borrowings = total_borrowings_val if total_borrowings_val > 0 else None

        net_assets_f = float(net_assets) if net_assets else None
        if has_borrowing_data and net_assets and float(net_assets) != 0:
            leverage = (total_borrowings_val / float(net_assets)) * 100
        else:
            leverage = None

        stiv_value = sum(float(h.value_usd or 0) for h in holdings if h.asset_category == "STIV")
        total_cash = stiv_value + (float(snapshot.cash_not_reported) if snapshot.cash_not_reported else 0)
        cash_pct = (total_cash / float(net_assets) * 100) if net_assets and float(net_assets) > 0 and total_cash > 0 else None

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
        geographic=geographic_data is not None,
        concentration=concentration_data is not None,
    )

    # Derive filing_date from the most recent data source available
    filing_date_val = None
    if holdings:
        h0 = holdings[0]
        filing_date_val = str(h0.filing_date or h0.report_date or "") or None
    if not filing_date_val and fees and fees.effective_date:
        filing_date_val = str(fees.effective_date)
    if not filing_date_val and snapshot and snapshot.report_date:
        filing_date_val = str(snapshot.report_date)

    return XRayResponse(
        ticker=etf.ticker,
        name=etf.fund_name or "",
        filing_date=filing_date_val,
        data_completeness=completeness,
        holdings=holdings_data,
        asset_allocation=asset_allocation_data,
        geographic=geographic_data,
        fees=fees_data,
        performance=perf_data,
        fund_health=fund_health_data,
        concentration=concentration_data,
    )
