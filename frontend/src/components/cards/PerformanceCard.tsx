interface PerformanceInterval {
  label: string;
  fund_return: number | null;
  benchmark_return: number | null;
  alpha: number | null;
}

interface PerformanceData {
  benchmark_name: string | null;
  turnover_rate: number | null;
  intervals: PerformanceInterval[];
}

interface PerformanceCardProps {
  data: PerformanceData | null;
}

function fmtPct(val: number | null): string {
  if (val === null || val === undefined) return "—";
  return (val >= 0 ? "+" : "") + val.toFixed(2) + "%";
}

function fmtReturn(val: number | null): string {
  if (val === null || val === undefined) return "—";
  return val.toFixed(2) + "%";
}

function AlphaCell({ alpha }: { alpha: number | null }) {
  if (alpha === null || alpha === undefined) {
    return <td className="py-2 text-sm tabular-nums text-right text-muted-foreground">—</td>;
  }
  const colorClass = alpha > 0 ? "text-green-600" : alpha < 0 ? "text-red-600" : "text-muted-foreground";
  return (
    <td className={`py-2 text-sm tabular-nums text-right font-medium ${colorClass}`}>
      {fmtPct(alpha)}
    </td>
  );
}

export function PerformanceCard({ data }: PerformanceCardProps) {
  if (!data || data.intervals.length === 0) {
    return (
      <div className="rounded-lg border bg-card text-card-foreground shadow-sm p-6">
        <h3 className="text-lg font-semibold mb-4">Performance vs. Benchmark</h3>
        <div className="h-24 flex items-center justify-center">
          <p className="text-muted-foreground text-sm italic">No data available</p>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-lg border bg-card text-card-foreground shadow-sm p-6">
      <h3 className="text-lg font-semibold mb-1">Performance vs. Benchmark</h3>
      {data.benchmark_name && (
        <p className="text-xs text-muted-foreground mb-4">Benchmark: {data.benchmark_name}</p>
      )}

      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b">
              <th className="pb-2 text-xs font-medium text-muted-foreground text-left">Period</th>
              <th className="pb-2 text-xs font-medium text-muted-foreground text-right">Fund Return</th>
              <th className="pb-2 text-xs font-medium text-muted-foreground text-right">Benchmark</th>
              <th className="pb-2 text-xs font-medium text-muted-foreground text-right">Alpha</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {data.intervals.map((interval) => (
              <tr key={interval.label}>
                <td className="py-2 text-sm font-medium">{interval.label}</td>
                <td className="py-2 text-sm tabular-nums text-right">{fmtReturn(interval.fund_return)}</td>
                <td className="py-2 text-sm tabular-nums text-right text-muted-foreground">{fmtReturn(interval.benchmark_return)}</td>
                <AlphaCell alpha={interval.alpha} />
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {data.turnover_rate !== null && data.turnover_rate !== undefined && (
        <div className="mt-4 pt-4 border-t flex items-center gap-2">
          <span className="text-xs text-muted-foreground uppercase tracking-wide">Portfolio Turnover</span>
          <span className="text-sm font-semibold tabular-nums">{data.turnover_rate.toFixed(0)}%</span>
        </div>
      )}
    </div>
  );
}
