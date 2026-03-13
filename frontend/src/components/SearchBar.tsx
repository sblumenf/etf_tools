import { useState, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { searchETFs } from "../lib/api";

export function SearchBar() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Array<{ ticker: string; name: string }>>([]);
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    setQuery(val);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!val.trim()) {
      setResults([]);
      setOpen(false);
      return;
    }
    debounceRef.current = setTimeout(async () => {
      try {
        const res = await searchETFs(val);
        setResults(res);
        setOpen(res.length > 0);
      } catch {
        setResults([]);
        setOpen(false);
      }
    }, 200);
  }, []);

  const handleSelect = (ticker: string) => {
    setQuery("");
    setResults([]);
    setOpen(false);
    navigate(`/xray/${ticker}`);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && query.trim()) {
      handleSelect(query.trim().toUpperCase());
    }
    if (e.key === "Escape") {
      setOpen(false);
    }
  };

  return (
    <div className="relative w-full max-w-xl">
      <input
        type="text"
        value={query}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        placeholder="Search by ticker or fund name (e.g. SPY)"
        className="w-full rounded-lg border border-input bg-background px-4 py-3 text-sm ring-offset-background placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
      />
      {open && results.length > 0 && (
        <ul className="absolute z-50 mt-1 w-full rounded-lg border bg-card shadow-lg overflow-hidden">
          {results.map((r) => (
            <li
              key={r.ticker}
              className="flex items-center gap-3 px-4 py-2.5 cursor-pointer hover:bg-accent text-sm"
              onMouseDown={() => handleSelect(r.ticker)}
            >
              <span className="font-mono font-semibold w-16 shrink-0">{r.ticker}</span>
              <span className="text-muted-foreground truncate">{r.name}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
