import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import {
  ComposableMap,
  Geographies,
  Geography,
  ZoomableGroup,
} from "react-simple-maps";
import { useState, useMemo } from "react";
import type { GeographicData } from "../../lib/api";

const GEO_URL =
  "https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json";

interface GeographicCardProps {
  data: GeographicData | null;
}

// Map ISO alpha-2 to ISO numeric used by world-atlas TopoJSON
const ISO2_TO_NUMERIC: Record<string, string> = {
  AF: "004", AX: "248", AL: "008", DZ: "012", AS: "016", AD: "020",
  AO: "024", AI: "660", AQ: "010", AG: "028", AR: "032", AM: "051",
  AW: "533", AU: "036", AT: "040", AZ: "031", BS: "044", BH: "048",
  BD: "050", BB: "052", BY: "112", BE: "056", BZ: "084", BJ: "204",
  BM: "060", BT: "064", BO: "068", BA: "070", BW: "072", BR: "076",
  VG: "092", BN: "096", BG: "100", BF: "854", BI: "108", KH: "116",
  CM: "120", CA: "124", CV: "132", KY: "136", CF: "140", TD: "148",
  CL: "152", CN: "156", CO: "170", KM: "174", CG: "178", CD: "180",
  CR: "188", CI: "384", HR: "191", CU: "192", CY: "196", CZ: "203",
  DK: "208", DJ: "262", DM: "212", DO: "214", EC: "218", EG: "818",
  SV: "222", GQ: "226", ER: "232", EE: "233", ET: "231", FK: "238",
  FO: "234", FJ: "242", FI: "246", FR: "250", PF: "258", GA: "266",
  GM: "270", GE: "268", DE: "276", GH: "288", GI: "292", GR: "300",
  GL: "304", GD: "308", GU: "316", GT: "320", GG: "831", GN: "324",
  GW: "624", GY: "328", HT: "332", HN: "340", HK: "344", HU: "348",
  IS: "352", IN: "356", ID: "360", IR: "364", IQ: "368", IE: "372",
  IM: "833", IL: "376", IT: "380", JM: "388", JP: "392", JE: "832",
  JO: "400", KZ: "398", KE: "404", KI: "296", KW: "414", KG: "417",
  LA: "418", LV: "428", LB: "422", LS: "426", LR: "430", LY: "434",
  LI: "438", LT: "440", LU: "442", MO: "446", MK: "807", MG: "450",
  MW: "454", MY: "458", MV: "462", ML: "466", MT: "470", MH: "584",
  MR: "478", MU: "480", MX: "484", FM: "583", MD: "498", MC: "492",
  MN: "496", ME: "499", MS: "500", MA: "504", MZ: "508", MM: "104",
  NA: "516", NR: "520", NP: "524", NL: "528", NC: "540", NZ: "554",
  NI: "558", NE: "562", NG: "566", NU: "570", NF: "574", KP: "408",
  NO: "578", OM: "512", PK: "586", PW: "585", PS: "275", PA: "591",
  PG: "598", PY: "600", PE: "604", PH: "608", PL: "616", PT: "620",
  PR: "630", QA: "634", RO: "642", RU: "643", RW: "646", SH: "654",
  KN: "659", LC: "662", PM: "666", VC: "670", WS: "882", SM: "674",
  ST: "678", SA: "682", SN: "686", RS: "688", SC: "690", SL: "694",
  SG: "702", SK: "703", SI: "705", SB: "090", SO: "706", ZA: "710",
  GS: "239", SS: "728", ES: "724", LK: "144", SD: "736", SR: "740",
  SZ: "748", SE: "752", CH: "756", SY: "760", TW: "158", TJ: "762",
  TZ: "834", TH: "764", TL: "626", TG: "768", TO: "776", TT: "780",
  TN: "788", TR: "792", TM: "795", TC: "796", TV: "798", UG: "800",
  UA: "804", AE: "784", GB: "826", US: "840", UY: "858", UZ: "860",
  VU: "548", VE: "862", VN: "704", VI: "850", WF: "876", EH: "732",
  YE: "887", ZM: "894", ZW: "716",
};

// Inverted map: ISO numeric -> ISO alpha-2, built once at module load
const NUMERIC_TO_ISO2: Record<string, string> = Object.fromEntries(
  Object.entries(ISO2_TO_NUMERIC).map(([iso2, numeric]) => [numeric, iso2])
);

function getColor(pct: number, maxPct: number): string {
  if (maxPct === 0) return "#e5e7eb";
  const intensity = Math.min(pct / maxPct, 1);
  // Scale from light blue (#bfdbfe) to dark blue (#1e40af)
  const r = Math.round(191 + (30 - 191) * intensity);
  const g = Math.round(219 + (64 - 219) * intensity);
  const b = Math.round(254 + (175 - 254) * intensity);
  return `rgb(${r},${g},${b})`;
}

export function GeographicCard({ data }: GeographicCardProps) {
  const [tooltip, setTooltip] = useState<{ name: string; pct: number } | null>(null);

  if (!data || !data.items || data.items.length === 0) {
    return (
      <div className="rounded-lg border bg-card text-card-foreground shadow-sm p-6">
        <h3 className="text-lg font-semibold mb-4">Geographic Diversification</h3>
        <div className="h-24 flex items-center justify-center">
          <p className="text-muted-foreground text-sm italic">No data available</p>
        </div>
      </div>
    );
  }

  const { top10, maxPct, pctByNumeric, nameByCode } = useMemo(() => {
    const sorted = [...data.items].sort((a, b) => b.pct - a.pct);
    const top10 = sorted.slice(0, 10);
    const maxPct = sorted[0]?.pct ?? 1;
    const pctByNumeric: Record<string, number> = {};
    const nameByCode: Record<string, string> = {};
    for (const item of data.items) {
      const numeric = ISO2_TO_NUMERIC[item.country_code.toUpperCase()];
      if (numeric) pctByNumeric[numeric] = item.pct;
      nameByCode[item.country_code.toUpperCase()] = item.country_name;
    }
    return { top10, maxPct, pctByNumeric, nameByCode };
  }, [data]);

  return (
    <div className="rounded-lg border bg-card text-card-foreground shadow-sm p-6 col-span-1 md:col-span-2">
      <h3 className="text-lg font-semibold mb-4">Geographic Diversification</h3>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Bar chart — top 10 countries */}
        <div>
          <p className="text-sm text-muted-foreground mb-2 font-medium">Top Countries by Allocation</p>
          <ResponsiveContainer width="100%" height={280}>
            <BarChart
              data={top10}
              layout="vertical"
              margin={{ top: 0, right: 16, left: 8, bottom: 0 }}
            >
              <XAxis
                type="number"
                tickFormatter={(v) => `${v.toFixed(0)}%`}
                domain={[0, Math.ceil(maxPct * 1.05)]}
                tick={{ fontSize: 11 }}
              />
              <YAxis
                type="category"
                dataKey="country_name"
                width={110}
                tick={{ fontSize: 11 }}
              />
              <Tooltip
                formatter={(value) => [
                  typeof value === "number" ? `${value.toFixed(2)}%` : String(value),
                  "Allocation",
                ]}
              />
              <Bar dataKey="pct" radius={[0, 3, 3, 0]}>
                {top10.map((entry, index) => (
                  <Cell
                    key={index}
                    fill={getColor(entry.pct, maxPct)}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Choropleth map */}
        <div className="relative">
          <p className="text-sm text-muted-foreground mb-2 font-medium">World Allocation Map</p>
          {tooltip && (
            <div className="absolute top-6 right-0 bg-popover border rounded px-2 py-1 text-xs z-10 shadow">
              <span className="font-medium">{tooltip.name}</span>: {tooltip.pct.toFixed(2)}%
            </div>
          )}
          <ComposableMap
            projectionConfig={{ scale: 120 }}
            style={{ width: "100%", height: "auto" }}
          >
            <ZoomableGroup>
              <Geographies geography={GEO_URL}>
                {({ geographies }) =>
                  geographies.map((geo) => {
                    const numericId = String(geo.id).padStart(3, "0");
                    const pct = pctByNumeric[numericId] ?? 0;
                    return (
                      <Geography
                        key={geo.rsmKey}
                        geography={geo}
                        fill={pct > 0 ? getColor(pct, maxPct) : "#e5e7eb"}
                        stroke="#fff"
                        strokeWidth={0.3}
                        onMouseEnter={() => {
                          if (pct > 0) {
                            const code = NUMERIC_TO_ISO2[numericId];
                            const name = code ? nameByCode[code] ?? code : numericId;
                            setTooltip({ name, pct });
                          }
                        }}
                        onMouseLeave={() => setTooltip(null)}
                        style={{
                          default: { outline: "none" },
                          hover: { fill: "#1d4ed8", outline: "none", cursor: "pointer" },
                          pressed: { outline: "none" },
                        }}
                      />
                    );
                  })
                }
              </Geographies>
            </ZoomableGroup>
          </ComposableMap>
        </div>
      </div>
    </div>
  );
}
