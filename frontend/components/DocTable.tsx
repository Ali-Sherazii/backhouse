import { money, seconds, when } from "@/lib/format";
import type { DocumentSummary } from "@/lib/types";
import { DocLink, Empty, FlagBadge, StatusBadge } from "./ui";

export function DocTable({ docs, compact }: { docs: DocumentSummary[]; compact?: boolean }) {
  if (docs.length === 0) return <Empty>No documents here.</Empty>;
  return (
    <div className={compact ? "-mx-4 -my-4 overflow-x-auto" : "overflow-x-auto"}>
      <table className="table-base">
        <thead>
          <tr>
            {!compact && <th>#</th>}
            <th>Vendor</th>
            <th>Invoice</th>
            <th className="text-right">Total</th>
            <th>Status</th>
            {!compact && <th>Checks</th>}
            {!compact && <th>Time</th>}
            <th>Received</th>
          </tr>
        </thead>
        <tbody>
          {docs.map((d) => (
            <tr key={d.id}>
              {!compact && <td className="font-mono text-xs text-ink-muted">{d.id}</td>}
              <td className="max-w-[18rem]">
                <DocLink id={d.id} review={d.status === "needs_review"}>
                  <span className="block truncate">{d.vendor_name || d.filename}</span>
                </DocLink>
                {!compact && d.vendor_name && <span className="block truncate text-xs text-ink-muted">{d.filename}</span>}
              </td>
              <td className="font-mono text-xs text-ink-soft">{d.invoice_number || "—"}</td>
              <td className="text-right tabular-nums">{money(d.total, d.currency)}</td>
              <td>
                <span className="flex items-center gap-1.5">
                  <StatusBadge status={d.status} />
                  {d.flagged && <FlagBadge />}
                  {d.auto_approved && <span className="text-xs text-emerald-700" title="Approved without a human">auto</span>}
                </span>
              </td>
              {!compact && (
                <td className="whitespace-nowrap text-xs">
                  {d.failed_checks > 0 && <span className="mr-2 text-red-700">{d.failed_checks} failed</span>}
                  {d.warnings > 0 && <span className="text-amber-700">▲ price</span>}
                  {d.failed_checks === 0 && d.warnings === 0 && d.processed_at && <span className="text-emerald-700">all pass</span>}
                </td>
              )}
              {!compact && <td className="whitespace-nowrap text-xs tabular-nums text-ink-muted">{seconds(d.processing_ms)}</td>}
              <td className="whitespace-nowrap text-ink-muted">
                {when(d.created_at)} {d.source === "email" && <span title="Received by email">✉</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
