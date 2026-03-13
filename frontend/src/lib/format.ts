export function formatUSD(val: number | null): string {
  if (val === null || val === undefined) return "—";
  if (val >= 1_000_000_000) return `$${(val / 1_000_000_000).toFixed(2)}B`;
  if (val >= 1_000_000) return `$${(val / 1_000_000).toFixed(2)}M`;
  if (val >= 1_000) return `$${(val / 1_000).toFixed(1)}K`;
  return `$${val.toFixed(2)}`;
}

// Standard percentage with 2 decimal places (handles null)
export function formatPct(val: number | null): string {
  if (val === null || val === undefined) return "—";
  return `${val.toFixed(2)}%`;
}

// Percentage with 1 decimal place (handles null)
export function formatPct1(val: number | null): string {
  if (val === null || val === undefined) return "—";
  return val.toFixed(1) + "%";
}

// Percentage with sign prefix for positive values (handles null)
export function formatPctSigned(val: number | null): string {
  if (val === null || val === undefined) return "—";
  return (val >= 0 ? "+" : "") + val.toFixed(2) + "%";
}

// Plain return value — no sign prefix (handles null)
export function formatReturn(val: number | null): string {
  if (val === null || val === undefined) return "—";
  return val.toFixed(2) + "%";
}

// AUM / large dollar amounts with T/B/M/K suffixes (handles null)
export function formatAUM(val: number | null): string {
  if (val === null || val === undefined) return "—";
  const abs = Math.abs(val);
  if (abs >= 1e12) return `$${(val / 1e12).toFixed(1)}T`;
  if (abs >= 1e9) return `$${(val / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `$${(val / 1e6).toFixed(0)}M`;
  if (abs >= 1e3) return `$${(val / 1e3).toFixed(0)}K`;
  return `$${val.toFixed(0)}`;
}
