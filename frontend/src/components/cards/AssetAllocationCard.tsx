import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import { formatUSD, formatPct } from "../../lib/format";
import type { AssetAllocationData } from "../../lib/api";

interface AssetAllocationCardProps {
  data: AssetAllocationData | null;
}

const COLORS = [
  "#3b82f6",
  "#10b981",
  "#f59e0b",
  "#ef4444",
  "#8b5cf6",
  "#06b6d4",
  "#f97316",
  "#84cc16",
  "#ec4899",
  "#6366f1",
];


export function AssetAllocationCard({ data }: AssetAllocationCardProps) {
  if (!data || !data.items || data.items.length === 0) {
    return (
      <div className="rounded-lg border bg-card text-card-foreground shadow-sm p-6">
        <h3 className="text-lg font-semibold mb-4">Asset Allocation</h3>
        <div className="h-24 flex items-center justify-center">
          <p className="text-muted-foreground text-sm italic">No data available</p>
        </div>
      </div>
    );
  }

  const chartData = data.items.map((item) => ({
    name: item.display_name,
    value: item.pct,
  }));

  return (
    <div className="rounded-lg border bg-card text-card-foreground shadow-sm p-6">
      <h3 className="text-lg font-semibold mb-4">Asset Allocation</h3>

      <ResponsiveContainer width="100%" height={220}>
        <PieChart>
          <Pie
            data={chartData}
            cx="50%"
            cy="50%"
            innerRadius={55}
            outerRadius={90}
            paddingAngle={2}
            dataKey="value"
          >
            {chartData.map((_, index) => (
              <Cell key={index} fill={COLORS[index % COLORS.length]} />
            ))}
          </Pie>
          <Tooltip
            formatter={(value) => [
              typeof value === "number" ? `${value.toFixed(2)}%` : String(value),
              "Allocation",
            ]}
          />
          <Legend
            formatter={(value) => (
              <span className="text-xs">{value}</span>
            )}
          />
        </PieChart>
      </ResponsiveContainer>

      <div className="mt-4 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-muted-foreground">
              <th className="text-left pb-2 pr-4 font-medium">Category</th>
              <th className="text-right pb-2 pr-4 font-medium">%</th>
              <th className="text-right pb-2 font-medium">Value (USD)</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((item, idx) => (
              <tr key={idx} className="border-b last:border-0 hover:bg-muted/30 transition-colors">
                <td className="py-2 pr-4 flex items-center gap-2">
                  <span
                    className="inline-block w-2.5 h-2.5 rounded-full flex-shrink-0"
                    style={{ backgroundColor: COLORS[idx % COLORS.length] }}
                  />
                  {item.display_name}
                </td>
                <td className="py-2 pr-4 text-right tabular-nums font-medium">
                  {formatPct(item.pct)}
                </td>
                <td className="py-2 text-right tabular-nums">
                  {formatUSD(item.value_usd)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
