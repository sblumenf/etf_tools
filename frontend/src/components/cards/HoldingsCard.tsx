import { formatUSD, formatPct } from "../../lib/format";

interface HoldingItem {
  name: string;
  ticker: string | null;
  value_usd: number | null;
  pct_val: number | null;
}

interface HoldingsData {
  total_count: number;
  items: HoldingItem[];
  other_pct: number | null;
}

interface HoldingsCardProps {
  data: HoldingsData | null;
  onNChange?: (n: number) => void;
}

const N_OPTIONS = [
  { label: "Top 10", value: 10 },
  { label: "Top 25", value: 25 },
  { label: "Top 50", value: 50 },
  { label: "All", value: 0 },
];

export function HoldingsCard({ data, onNChange }: HoldingsCardProps) {
  if (!data) {
    return (
      <div className="rounded-lg border bg-card text-card-foreground shadow-sm p-6">
        <h3 className="text-lg font-semibold mb-4">Holdings Composition</h3>
        <div className="h-24 flex items-center justify-center">
          <p className="text-muted-foreground text-sm italic">No data available</p>
        </div>
      </div>
    );
  }

  const { total_count, items, other_pct } = data;

  const handleNChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const val = Number(e.target.value);
    onNChange?.(val);
  };

  return (
    <div className="rounded-lg border bg-card text-card-foreground shadow-sm p-6">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-lg font-semibold">Holdings Composition</h3>
          <p className="text-xs text-muted-foreground mt-0.5">{total_count} total holdings</p>
        </div>
        <select
          className="text-sm border rounded px-2 py-1 bg-background text-foreground"
          defaultValue={10}
          onChange={handleNChange}
        >
          {N_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-muted-foreground">
              <th className="text-left pb-2 pr-4 font-medium">#</th>
              <th className="text-left pb-2 pr-4 font-medium">Name</th>
              <th className="text-left pb-2 pr-4 font-medium w-16">Ticker</th>
              <th className="text-right pb-2 pr-4 font-medium">Value (USD)</th>
              <th className="text-right pb-2 font-medium">% of Net Assets</th>
            </tr>
          </thead>
          <tbody>
            {items.map((holding, idx) => (
              <tr key={idx} className="border-b last:border-0 hover:bg-muted/30 transition-colors">
                <td className="py-2 pr-4 text-muted-foreground">{idx + 1}</td>
                <td className="py-2 pr-4 font-medium truncate max-w-[200px]" title={holding.name}>
                  {holding.name || "—"}
                </td>
                <td className="py-2 pr-4 font-mono text-xs text-muted-foreground">
                  {holding.ticker || "—"}
                </td>
                <td className="py-2 pr-4 text-right tabular-nums">
                  {formatUSD(holding.value_usd)}
                </td>
                <td className="py-2 text-right tabular-nums font-medium">
                  {formatPct(holding.pct_val)}
                </td>
              </tr>
            ))}
            {other_pct !== null && other_pct !== undefined && other_pct > 0 && (
              <tr className="text-muted-foreground bg-muted/20">
                <td className="py-2 pr-4">—</td>
                <td className="py-2 pr-4 italic" colSpan={2}>
                  Other ({total_count - items.length} holdings)
                </td>
                <td className="py-2 pr-4 text-right">—</td>
                <td className="py-2 text-right tabular-nums">{formatPct(other_pct)}</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
