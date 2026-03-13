import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useXRayData } from "../hooks/useXRayData";
import { HoldingsCard } from "../components/cards/HoldingsCard";
import { AssetAllocationCard } from "../components/cards/AssetAllocationCard";
import { GeographicCard } from "../components/cards/GeographicCard";
import { LiquidityCard } from "../components/cards/LiquidityCard";
import { FeeCard } from "../components/cards/FeeCard";
import { PlaceholderCard } from "../components/cards/PlaceholderCard";

export function XRay() {
  const { ticker } = useParams<{ ticker: string }>();
  const [holdingsN, setHoldingsN] = useState(10);
  const { data, loading, error } = useXRayData(ticker, holdingsN);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <p className="text-muted-foreground">Loading {ticker}...</p>
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
        <HoldingsCard data={data.holdings} onNChange={setHoldingsN} />
        <AssetAllocationCard data={data.asset_allocation} />
        <GeographicCard data={data.geographic} />
        <LiquidityCard data={data.liquidity} />
        <FeeCard data={data.fees} />
        <PlaceholderCard title="Performance vs. Benchmark" available={c.performance} />
        <PlaceholderCard title="Fund Health" available={c.fund_health} />
        <PlaceholderCard title="Concentration Analysis" available={c.concentration} />
      </div>
    </div>
  );
}
