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
    ticker: Optional[str] = None
    value_usd: Optional[float] = None
    pct_val: Optional[float] = None


class HoldingsData(BaseModel):
    total_count: int
    items: list[HoldingItem]


class AssetCategoryItem(BaseModel):
    code: str
    display_name: str
    pct: float
    value_usd: Optional[float] = None


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
    management_fee: Optional[float] = None
    distribution_12b1: Optional[float] = None
    other_expenses: Optional[float] = None
    acquired_fund_fees: Optional[float] = None
    gross_expense_ratio: Optional[float] = None
    net_expense_ratio: Optional[float] = None
    fee_waiver: Optional[float] = None
    waiver_expiration: Optional[str] = None
    waiver_expiring_soon: bool


class PerformanceInterval(BaseModel):
    label: str
    fund_return: Optional[float] = None
    benchmark_return: Optional[float] = None
    alpha: Optional[float] = None


class PerformanceData(BaseModel):
    benchmark_name: Optional[str] = None
    turnover_rate: Optional[float] = None
    intervals: list[PerformanceInterval]


class FundHealthData(BaseModel):
    total_net_assets: Optional[float] = None
    total_borrowings: Optional[float] = None
    leverage_ratio: Optional[float] = None
    cash_position_pct: Optional[float] = None
    latest_net_flow: Optional[float] = None


class ConcentrationData(BaseModel):
    hhi: Optional[float] = None
    top5_weight: Optional[float] = None
    top10_weight: Optional[float] = None
    top20_weight: Optional[float] = None
    treemap_data: list[HoldingItem]


class XRayResponse(BaseModel):
    ticker: str
    name: str
    filing_date: Optional[str] = None
    data_completeness: DataCompleteness
    holdings: HoldingsData | None
    asset_allocation: AssetAllocationData | None
    geographic: GeographicData | None
    liquidity: LiquidityData | None
    fees: FeeData | None
    performance: PerformanceData | None
    fund_health: FundHealthData | None
    concentration: ConcentrationData | None
