interface FundHealthData {
  total_net_assets: number | null;
  total_borrowings: number | null;
  leverage_ratio: number | null;
  cash_position_pct: number | null;
  latest_net_flow: number | null;
}

interface FundHealthCardProps {
  data: FundHealthData | null;
}

function fmtAUM(val: number | null): string {
  if (val === null || val === undefined) return "—";
  const abs = Math.abs(val);
  if (abs >= 1e12) return `$${(val / 1e12).toFixed(1)}T`;
  if (abs >= 1e9) return `$${(val / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `$${(val / 1e6).toFixed(0)}M`;
  if (abs >= 1e3) return `$${(val / 1e3).toFixed(0)}K`;
  return `$${val.toFixed(0)}`;
}

function fmtPct(val: number | null): string {
  if (val === null || val === undefined) return "—";
  return val.toFixed(2) + "%";
}

function fmtLeverage(val: number | null): string {
  if (val === null || val === undefined) return "—";
  if (val === 0) return "None";
  return val.toFixed(2) + "%";
}

interface MetricRowProps {
  label: string;
  value: string;
  valueClass?: string;
}

function MetricRow({ label, value, valueClass }: MetricRowProps) {
  return (
    <div className="flex items-center justify-between py-2 border-b last:border-0">
      <span className="text-sm text-muted-foreground">{label}</span>
      <span className={`text-sm font-medium tabular-nums ${valueClass ?? ""}`}>{value}</span>
    </div>
  );
}

export function FundHealthCard({ data }: FundHealthCardProps) {
  if (!data) {
    return (
      <div className="rounded-lg border bg-card text-card-foreground shadow-sm p-6">
        <h3 className="text-lg font-semibold mb-4">Fund Health</h3>
        <div className="h-24 flex items-center justify-center">
          <p className="text-muted-foreground text-sm italic">No data available</p>
        </div>
      </div>
    );
  }

  const flowIsPositive = data.latest_net_flow !== null && data.latest_net_flow > 0;
  const flowIsNegative = data.latest_net_flow !== null && data.latest_net_flow < 0;
  const flowLabel =
    data.latest_net_flow === null
      ? "—"
      : `${data.latest_net_flow > 0 ? "+" : ""}${fmtAUM(data.latest_net_flow)}`;

  return (
    <div className="rounded-lg border bg-card text-card-foreground shadow-sm p-6">
      <h3 className="text-lg font-semibold mb-2">Fund Health</h3>

      {/* AUM hero metric */}
      <div className="mb-4">
        <p className="text-xs text-muted-foreground uppercase tracking-wide">Total Net Assets (AUM)</p>
        <p className="text-3xl font-bold tabular-nums">{fmtAUM(data.total_net_assets)}</p>
      </div>

      <div>
        <MetricRow label="Total Borrowings" value={fmtAUM(data.total_borrowings)} />
        <MetricRow label="Leverage Ratio" value={fmtLeverage(data.leverage_ratio)} />
        <MetricRow label="Cash Position" value={fmtPct(data.cash_position_pct)} />
        <MetricRow
          label="Latest Net Flow"
          value={flowLabel}
          valueClass={
            flowIsPositive ? "text-green-600" : flowIsNegative ? "text-red-600" : ""
          }
        />
      </div>
    </div>
  );
}
