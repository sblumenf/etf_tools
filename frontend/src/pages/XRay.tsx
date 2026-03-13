import { useParams, Link } from "react-router-dom";
import { useXRayData } from "../hooks/useXRayData";
import { HoldingsCard } from "../components/cards/HoldingsCard";
import { AssetAllocationCard } from "../components/cards/AssetAllocationCard";
import { GeographicCard } from "../components/cards/GeographicCard";
import { LiquidityCard } from "../components/cards/LiquidityCard";
import { FeeCard } from "../components/cards/FeeCard";
import { PerformanceCard } from "../components/cards/PerformanceCard";
import { FundHealthCard } from "../components/cards/FundHealthCard";
import { ConcentrationCard } from "../components/cards/ConcentrationCard";

export function XRay() {
  const { ticker } = useParams<{ ticker: string }>();
  const { data, loading, error } = useXRayData(ticker);

  if (loading) {
    return (
      <div className="max-w-7xl mx-auto p-6">
        <div className="mb-8">
          <div className="h-4 w-24 bg-gray-200 animate-pulse rounded mb-4" />
          <div className="flex items-baseline gap-3">
            <div className="h-9 w-20 bg-gray-200 animate-pulse rounded" />
            <div className="h-6 w-64 bg-gray-200 animate-pulse rounded" />
          </div>
          <div className="h-4 w-40 bg-gray-200 animate-pulse rounded mt-2" />
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="rounded-xl border bg-card p-6 space-y-3">
              <div className="h-5 w-32 bg-gray-200 animate-pulse rounded" />
              <div className="h-4 w-full bg-gray-200 animate-pulse rounded" />
              <div className="h-4 w-5/6 bg-gray-200 animate-pulse rounded" />
              <div className="h-32 bg-gray-200 animate-pulse rounded mt-4" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen gap-4">
        <p className="text-destructive font-semibold text-lg">{error}</p>
        <Link to="/" className="text-sm text-muted-foreground underline">
          Back to search
        </Link>
      </div>
    );
  }

  if (!data) return null;

  const c = data.data_completeness || {};

  return (
    <div className="max-w-7xl mx-auto p-6">
      <div className="mb-8">
        <Link to="/" className="text-sm text-muted-foreground hover:underline mb-4 inline-block">
          &larr; Back to search
        </Link>
        <div className="flex items-baseline gap-3">
          <h1 className="text-3xl font-bold">{data.ticker}</h1>
          <span className="text-muted-foreground text-lg">{data.name}</span>
        </div>
        {data.filing_date && (
          <p className="text-sm text-muted-foreground mt-1">
            Data as of: {data.filing_date}
          </p>
        )}
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <HoldingsCard data={data.holdings} onNChange={() => {}} />
        <AssetAllocationCard data={data.asset_allocation} />
        <GeographicCard data={data.geographic} />
        <LiquidityCard data={data.liquidity} />
        <FeeCard data={data.fees} />
        <PerformanceCard data={data.performance} />
        <FundHealthCard data={data.fund_health} />
        <ConcentrationCard data={data.concentration} hasHoldings={!!c.holdings} />
      </div>
    </div>
  );
}
