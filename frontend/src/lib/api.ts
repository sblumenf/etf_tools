const API_BASE = (import.meta as any).env?.VITE_API_BASE_URL || "http://localhost:8000";

export async function searchETFs(q: string): Promise<Array<{ ticker: string; name: string; cik: string }>> {
  const res = await fetch(`${API_BASE}/api/v1/etfs/search?q=${encodeURIComponent(q)}`);
  if (!res.ok) throw new Error("Search failed");
  return res.json();
}

export async function getXRay(ticker: string): Promise<any> {
  const res = await fetch(`${API_BASE}/api/v1/xray/${ticker}`);
  if (res.status === 404) throw new Error("ETF not found");
  if (!res.ok) throw new Error("Failed to load ETF data");
  return res.json();
}
