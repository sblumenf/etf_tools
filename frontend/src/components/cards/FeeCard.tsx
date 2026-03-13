import { formatPct as fmtPct } from "../../lib/format";
import type { FeeData } from "../../lib/api";

interface FeeCardProps {
  data: FeeData | null;
}


interface FeeRowProps {
  label: string;
  value: string;
  bold?: boolean;
  divider?: boolean;
}

function FeeRow({ label, value, bold, divider }: FeeRowProps) {
  return (
    <>
      {divider && <tr><td colSpan={2} className="pt-2 pb-1"><div className="border-t" /></td></tr>}
      <tr className={bold ? "font-semibold" : ""}>
        <td className="py-1 text-sm text-muted-foreground pr-4">{label}</td>
        <td className="py-1 text-sm tabular-nums text-right">{value}</td>
      </tr>
    </>
  );
}

export function FeeCard({ data }: FeeCardProps) {
  if (!data) {
    return (
      <div className="rounded-lg border bg-card text-card-foreground shadow-sm p-6">
        <h3 className="text-lg font-semibold mb-4">Fee Structure</h3>
        <div className="h-24 flex items-center justify-center">
          <p className="text-muted-foreground text-sm italic">No data available</p>
        </div>
      </div>
    );
  }

  const hasBreakdown =
    data.management_fee !== null ||
    data.distribution_12b1 !== null ||
    data.other_expenses !== null ||
    data.acquired_fund_fees !== null;

  return (
    <div className="rounded-lg border bg-card text-card-foreground shadow-sm p-6">
      <h3 className="text-lg font-semibold mb-4">Fee Structure</h3>

      {/* Prominent expense ratio display */}
      <div className="flex gap-6 mb-5">
        <div>
          <p className="text-xs text-muted-foreground uppercase tracking-wide">Gross Expense Ratio</p>
          <p className="text-2xl font-bold tabular-nums">{fmtPct(data.gross_expense_ratio)}</p>
        </div>
        {data.net_expense_ratio !== null && data.net_expense_ratio !== data.gross_expense_ratio && (
          <div>
            <p className="text-xs text-muted-foreground uppercase tracking-wide">Net Expense Ratio</p>
            <p className="text-2xl font-bold tabular-nums">{fmtPct(data.net_expense_ratio)}</p>
          </div>
        )}
      </div>

      {/* Fee breakdown table */}
      {hasBreakdown && (
        <table className="w-full mb-4">
          <tbody>
            {data.management_fee !== null && (
              <FeeRow label="Management Fee" value={fmtPct(data.management_fee)} />
            )}
            {data.distribution_12b1 !== null && (
              <FeeRow label="12b-1 Distribution Fee" value={fmtPct(data.distribution_12b1)} />
            )}
            {data.other_expenses !== null && (
              <FeeRow label="Other Expenses" value={fmtPct(data.other_expenses)} />
            )}
            {data.acquired_fund_fees !== null && (
              <FeeRow label="Acquired Fund Fees" value={fmtPct(data.acquired_fund_fees)} />
            )}
            <FeeRow
              label="Gross Expense Ratio"
              value={fmtPct(data.gross_expense_ratio)}
              bold
              divider
            />
            {data.fee_waiver !== null && (
              <FeeRow label="Fee Waiver" value={`-${fmtPct(data.fee_waiver)}`} />
            )}
            {data.net_expense_ratio !== null && data.net_expense_ratio !== data.gross_expense_ratio && (
              <FeeRow label="Net Expense Ratio" value={fmtPct(data.net_expense_ratio)} bold />
            )}
          </tbody>
        </table>
      )}

      {/* Waiver expiration notice */}
      {data.fee_waiver !== null && data.waiver_expiration && (
        <div
          className={`text-sm rounded px-3 py-2 ${
            data.waiver_expiring_soon
              ? "bg-amber-50 border border-amber-300 text-amber-800"
              : "bg-muted text-muted-foreground"
          }`}
        >
          {data.waiver_expiring_soon && (
            <span className="font-semibold mr-1">Warning:</span>
          )}
          Fee waiver expires {data.waiver_expiration}
          {data.waiver_expiring_soon && " (within 6 months)"}
        </div>
      )}
    </div>
  );
}
