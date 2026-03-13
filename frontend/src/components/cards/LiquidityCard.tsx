import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";

interface LiquidityItem {
  code: string;
  display_name: string;
  color: string;
  pct: number;
}

interface LiquidityData {
  items: LiquidityItem[];
}

interface LiquidityCardProps {
  data: LiquidityData | null;
}

// Color mapping from spec codes to tailwind-compatible hex values
const CODE_COLORS: Record<string, string> = {
  HLI: "#22c55e", // green
  MLI: "#eab308", // yellow
  LLI: "#f97316", // orange
  ILI: "#ef4444", // red
};

function getColor(item: LiquidityItem): string {
  return CODE_COLORS[item.code] || item.color || "#94a3b8";
}

export function LiquidityCard({ data }: LiquidityCardProps) {
  if (!data || !data.items || data.items.length === 0) {
    return (
      <div className="rounded-lg border bg-card text-card-foreground shadow-sm p-6">
        <h3 className="text-lg font-semibold mb-4">Liquidity Profile</h3>
        <div className="h-24 flex items-center justify-center">
          <p className="text-muted-foreground text-sm italic">No data available</p>
        </div>
      </div>
    );
  }

  // Build a single stacked bar: one entry, each item is a key
  // Recharts stacked bar needs the data as an object with keys for each bar segment
  const barEntry: Record<string, string | number> = { name: "Liquidity" };
  for (const item of data.items) {
    barEntry[item.code] = item.pct;
  }
  const barData = [barEntry];

  return (
    <div className="rounded-lg border bg-card text-card-foreground shadow-sm p-6">
      <h3 className="text-lg font-semibold mb-4">Liquidity Profile</h3>

      <div className="mb-4">
        <ResponsiveContainer width="100%" height={80}>
          <BarChart
            data={barData}
            layout="vertical"
            margin={{ top: 0, right: 0, bottom: 0, left: 0 }}
          >
            <XAxis
              type="number"
              domain={[0, 100]}
              hide
            />
            <YAxis type="category" dataKey="name" hide />
            <Tooltip
              formatter={(value, name) => {
                const item = data.items.find((i) => i.code === name);
                return [
                  `${typeof value === "number" ? value.toFixed(2) : value}%`,
                  item ? item.display_name : String(name),
                ];
              }}
            />
            {data.items.map((item) => (
              <Bar
                key={item.code}
                dataKey={item.code}
                stackId="liquidity"
                fill={getColor(item)}
                radius={0}
              >
                <Cell fill={getColor(item)} />
              </Bar>
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="space-y-2">
        {data.items.map((item) => (
          <div key={item.code} className="flex items-center justify-between text-sm">
            <div className="flex items-center gap-2">
              <span
                className="inline-block w-3 h-3 rounded-sm flex-shrink-0"
                style={{ backgroundColor: getColor(item) }}
              />
              <span>{item.display_name}</span>
            </div>
            <span className="tabular-nums font-medium">{item.pct.toFixed(2)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}
