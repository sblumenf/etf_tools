const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export interface DataCompleteness {
  holdings: boolean;
  fees: boolean;
  performance: boolean;
  fund_health: boolean;
  geographic: boolean;
  concentration: boolean;
}

export interface HoldingItem {
  name: string;
  ticker: string | null;
  value_usd: number | null;
  pct_val: number | null;
}

export interface HoldingsData {
  total_count: number;
  items: HoldingItem[];
}

export interface AssetCategoryItem {
  code: string;
  display_name: string;
  pct: number;
  value_usd: number | null;
}

export interface AssetAllocationData {
  items: AssetCategoryItem[];
}

export interface CountryItem {
  country_code: string;
  country_name: string;
  pct: number;
}

export interface GeographicData {
  items: CountryItem[];
}

export interface FeeData {
  management_fee: number | null;
  distribution_12b1: number | null;
  other_expenses: number | null;
  acquired_fund_fees: number | null;
  gross_expense_ratio: number | null;
  net_expense_ratio: number | null;
  fee_waiver: number | null;
  waiver_expiration: string | null;
  waiver_expiring_soon: boolean;
}

export interface PerformanceInterval {
  label: string;
  fund_return: number | null;
  benchmark_return: number | null;
  alpha: number | null;
}

export interface PerformanceData {
  benchmark_name: string | null;
  turnover_rate: number | null;
  intervals: PerformanceInterval[];
}

export interface FundHealthData {
  total_net_assets: number | null;
  total_borrowings: number | null;
  leverage_ratio: number | null;
  cash_position_pct: number | null;
  latest_net_flow: number | null;
}

export interface ConcentrationData {
  hhi: number | null;
  top5_weight: number | null;
  top10_weight: number | null;
  top20_weight: number | null;
  treemap_data: HoldingItem[] | null;
}

export interface XRayResponse {
  ticker: string;
  name: string;
  filing_date: string | null;
  data_completeness: DataCompleteness;
  holdings: HoldingsData | null;
  asset_allocation: AssetAllocationData | null;
  geographic: GeographicData | null;
  fees: FeeData | null;
  performance: PerformanceData | null;
  fund_health: FundHealthData | null;
  concentration: ConcentrationData | null;
}

export async function searchETFs(q: string): Promise<Array<{ ticker: string; name: string; cik: string }>> {
  const res = await fetch(`${API_BASE}/api/v1/etfs/search?q=${encodeURIComponent(q)}`);
  if (!res.ok) throw new Error("Search failed");
  return res.json();
}

export async function getXRay(ticker: string): Promise<XRayResponse> {
  const res = await fetch(`${API_BASE}/api/v1/xray/${ticker}`);
  if (res.status === 404) throw new Error("ETF not found");
  if (!res.ok) throw new Error("Failed to load ETF data");
  return res.json();
}
