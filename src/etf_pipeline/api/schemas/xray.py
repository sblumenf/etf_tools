from pydantic import BaseModel
from typing import Optional


class DataCompleteness(BaseModel):
    holdings: bool
    fees: bool
    performance: bool
    fund_health: bool
    liquidity: bool
    geographic: bool
    concentration: bool


class HoldingItem(BaseModel):
    name: str
    ticker: Optional[str]
    value_usd: Optional[float]
    pct_val: Optional[float]
    weight: Optional[float] = None


class HoldingsData(BaseModel):
    total_count: int
    items: list[HoldingItem]
    other_pct: Optional[float]


class AssetCategoryItem(BaseModel):
    code: str
    display_name: str
    pct: float
    value_usd: Optional[float]


class AssetAllocationData(BaseModel):
    items: list[AssetCategoryItem]


class CountryItem(BaseModel):
    country_code: str
    country_name: str
    pct: float


class GeographicData(BaseModel):
    items: list[CountryItem]


class LiquidityItem(BaseModel):
    code: str
    display_name: str
    color: str
    pct: float


class LiquidityData(BaseModel):
    items: list[LiquidityItem]


class FeeData(BaseModel):
    management_fee: Optional[float]
    distribution_12b1: Optional[float]
    other_expenses: Optional[float]
    acquired_fund_fees: Optional[float]
    gross_expense_ratio: Optional[float]
    net_expense_ratio: Optional[float]
    fee_waiver: Optional[float]
    waiver_expiration: Optional[str]
    waiver_expiring_soon: bool


class PerformanceInterval(BaseModel):
    label: str
    fund_return: Optional[float]
    benchmark_return: Optional[float]
    alpha: Optional[float]


class PerformanceData(BaseModel):
    benchmark_name: Optional[str]
    turnover_rate: Optional[float]
    intervals: list[PerformanceInterval]


class FundHealthData(BaseModel):
    total_net_assets: Optional[float]
    total_borrowings: Optional[float]
    leverage_ratio: Optional[float]
    cash_position_pct: Optional[float]
    latest_net_flow: Optional[float]


class ConcentrationData(BaseModel):
    hhi: Optional[float]
    top5_weight: Optional[float]
    top10_weight: Optional[float]
    top20_weight: Optional[float]
    treemap_data: list[HoldingItem]


class XRayResponse(BaseModel):
    ticker: str
    name: str
    filing_date: Optional[str]
    data_completeness: DataCompleteness
    holdings: HoldingsData | None
    asset_allocation: AssetAllocationData | None
    geographic: GeographicData | None
    liquidity: LiquidityData | None
    fees: FeeData | None
    performance: PerformanceData | None
    fund_health: FundHealthData | None
    concentration: ConcentrationData | None
