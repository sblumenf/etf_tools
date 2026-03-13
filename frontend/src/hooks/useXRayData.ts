import { useState, useEffect } from "react";
import { getXRay } from "../lib/api";

export function useXRayData(ticker: string | undefined, n: number = 10) {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ticker) return;
    setLoading(true);
    setError(null);
    getXRay(ticker, n)
      .then(setData)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [ticker, n]);

  return { data, loading, error };
}
