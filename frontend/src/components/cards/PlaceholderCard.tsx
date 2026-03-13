interface PlaceholderCardProps {
  title: string;
  available: boolean;
}

export function PlaceholderCard({ title, available }: PlaceholderCardProps) {
  return (
    <div className="rounded-lg border bg-card text-card-foreground shadow-sm p-6">
      <h3 className="text-lg font-semibold mb-4">{title}</h3>
      {available ? (
        <div className="h-24 flex items-center justify-center">
          <p className="text-muted-foreground text-sm">Coming soon...</p>
        </div>
      ) : (
        <div className="h-24 flex items-center justify-center">
          <p className="text-muted-foreground text-sm italic">No data available</p>
        </div>
      )}
    </div>
  );
}
