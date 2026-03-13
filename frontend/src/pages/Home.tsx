import { SearchBar } from "../components/SearchBar";

export function Home() {
  return (
    <div className="flex flex-col items-center justify-center min-h-screen gap-8 p-8 bg-background">
      <div className="text-center">
        <h1 className="text-4xl font-bold tracking-tight mb-2">ETF X-Ray</h1>
        <p className="text-muted-foreground text-lg">
          Comprehensive fund analysis from SEC filings
        </p>
      </div>
      <SearchBar />
      <p className="text-xs text-muted-foreground">
        Data sourced from SEC N-PORT filings
      </p>
    </div>
  );
}
