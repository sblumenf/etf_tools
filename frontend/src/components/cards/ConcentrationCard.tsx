import { Treemap, ResponsiveContainer, Tooltip } from "recharts";

interface TreemapEntry {
  name: string;
  ticker: string | null;
  weight: number;
}

interface ConcentrationData {
  hhi: number | null;
  top5_weight: number | null;
  top10_weight: number | null;
  top20_weight: number | null;
  treemap_data: TreemapEntry[] | null;
}

interface ConcentrationCardProps {
  data: ConcentrationData | null;
  hasHoldings: boolean;
}

const BLUE_PALETTE = [
  "#1d4ed8",
  "#2563eb",
  "#3b82f6",
  "#4f94f8",
  "#60a5fa",
  "#72b3fb",
  "#84c0fc",
  "#93c5fd",
  "#a5d0fd",
  "#b3d9fe",
  "#bfe0fe",
  "#c7e5fe",
  "#cfe8fe",
  "#d6ecfe",
  "#ddefff",
  "#e3f2ff",
  "#e8f4ff",
  "#edf6ff",
  "#f1f8ff",
  "#f5faff",
];

function getHhiLabel(hhi: number): string {
  if (hhi < 100) return "Highly Diversified";
  if (hhi < 500) return "Diversified";
  if (hhi < 1500) return "Moderate Concentration";
  return "Concentrated";
}

function getHhiColor(hhi: number): string {
  if (hhi < 100) return "text-green-600";
  if (hhi < 500) return "text-blue-600";
  if (hhi < 1500) return "text-amber-600";
  return "text-red-600";
}

function fmtPct(val: number | null): string {
  if (val === null || val === undefined) return "—";
  return val.toFixed(1) + "%";
}

function fmtHhi(val: number | null): string {
  if (val === null || val === undefined) return "—";
  return Math.round(val).toLocaleString();
}

interface StatBlockProps {
  label: string;
  value: string;
  sub?: React.ReactNode;
}

function StatBlock({ label, value, sub }: StatBlockProps) {
  return (
    <div>
      <p className="text-xs text-muted-foreground uppercase tracking-wide">{label}</p>
      <p className="text-xl font-bold tabular-nums">{value}</p>
      {sub && <div className="mt-0.5">{sub}</div>}
    </div>
  );
}

interface TreemapCell {
  name: string;
  size: number;
  fill: string;
  ticker?: string | null;
  weight: number;
  [key: string]: unknown;
}

function buildTreemapData(entries: TreemapEntry[]): TreemapCell[] {
  return entries.map((entry, idx) => {
    const isOther = entry.name === "Other";
    const fill = isOther ? "#94a3b8" : (BLUE_PALETTE[idx] ?? "#93c5fd");
    return {
      name: entry.ticker && !isOther ? entry.ticker : entry.name,
      size: entry.weight,
      fill,
      ticker: entry.ticker,
      weight: entry.weight,
    };
  });
}

interface CustomTooltipProps {
  active?: boolean;
  payload?: Array<{ payload: TreemapCell }>;
}

function CustomTooltip({ active, payload }: CustomTooltipProps) {
  if (!active || !payload || !payload.length) return null;
  const d = payload[0].payload;
  return (
    <div className="rounded border bg-white shadow text-sm px-3 py-2">
      <p className="font-semibold">{d.name}</p>
      <p className="text-muted-foreground">{fmtPct(d.weight)}</p>
    </div>
  );
}

interface CustomContentProps {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  name?: string;
  fill?: string;
}

function CustomContent({ x = 0, y = 0, width = 0, height = 0, name = "", fill = "#3b82f6" }: CustomContentProps) {
  const showLabel = width > 40 && height > 24;
  return (
    <g>
      <rect x={x} y={y} width={width} height={height} fill={fill} stroke="#fff" strokeWidth={1} />
      {showLabel && (
        <text
          x={x + width / 2}
          y={y + height / 2}
          textAnchor="middle"
          dominantBaseline="middle"
          fontSize={Math.min(12, width / 5)}
          fill="#fff"
          fontWeight="600"
          style={{ pointerEvents: "none" }}
        >
          {name}
        </text>
      )}
    </g>
  );
}

export function ConcentrationCard({ data, hasHoldings }: ConcentrationCardProps) {
  if (!hasHoldings || !data) {
    return (
      <div className="rounded-lg border bg-card text-card-foreground shadow-sm p-6">
        <h3 className="text-lg font-semibold mb-4">Concentration Analysis</h3>
        <div className="h-24 flex items-center justify-center">
          <p className="text-muted-foreground text-sm italic">No data available</p>
        </div>
      </div>
    );
  }

  const treemapCells = data.treemap_data ? buildTreemapData(data.treemap_data) : null;

  return (
    <div className="rounded-lg border bg-card text-card-foreground shadow-sm p-6">
      <h3 className="text-lg font-semibold mb-4">Concentration Analysis</h3>

      <div className="flex flex-wrap gap-6 mb-5">
        <StatBlock
          label="HHI"
          value={fmtHhi(data.hhi)}
          sub={
            data.hhi !== null ? (
              <span className={`text-xs font-medium ${getHhiColor(data.hhi)}`}>
                {getHhiLabel(data.hhi)}
              </span>
            ) : null
          }
        />
        <StatBlock label="Top 5" value={fmtPct(data.top5_weight)} />
        <StatBlock label="Top 10" value={fmtPct(data.top10_weight)} />
        <StatBlock label="Top 20" value={fmtPct(data.top20_weight)} />
      </div>

      {treemapCells && treemapCells.length > 0 && (
        <div style={{ height: 220 }}>
          <ResponsiveContainer width="100%" height="100%">
            <Treemap
              data={treemapCells}
              dataKey="size"
              content={<CustomContent />}
            >
              <Tooltip content={<CustomTooltip />} />
            </Treemap>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
