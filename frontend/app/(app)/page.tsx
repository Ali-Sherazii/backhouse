"use client";

import Link from "next/link";
import { useApi } from "@/lib/hooks";
import { money, seconds, STATUS_LABEL, when } from "@/lib/format";
import type { Stats, Status } from "@/lib/types";
import { Card, DocLink, Empty, ErrorNote, FlagBadge, StatusBadge } from "@/components/ui";
import { DocTable } from "@/components/DocTable";

const BAR_ORDER: Status[] = ["exported", "approved", "needs_review", "processing", "queued", "failed", "rejected"];
const BAR_COLOR: Record<Status, string> = {
  exported: "bg-emerald-600",
  approved: "bg-emerald-300",
  needs_review: "bg-amber-400",
  processing: "bg-sky-400",
  queued: "bg-stone-300",
  failed: "bg-red-500",
  rejected: "bg-stone-400",
};

export default function Dashboard() {
  const { data, error } = useApi<Stats>("/stats", { intervalMs: 5000 });

  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!data) return <div className="h-40 animate-pulse rounded-xl bg-stone-100" />;

  const review = data.counts.needs_review;
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Dashboard</h1>
          <p className="text-sm text-ink-muted">Demo Bistro · supplier invoices</p>
        </div>
        <div className="flex gap-2">
          {review > 0 && (
            <Link href="/documents?status=needs_review" className="rounded-lg bg-amber-100 px-3.5 py-2 text-sm font-medium text-amber-900 hover:bg-amber-200">
              {review} waiting for review →
            </Link>
          )}
          <Link href="/upload" className="rounded-lg bg-ink px-3.5 py-2 text-sm font-medium text-white hover:bg-ink-soft">
            Upload invoice
          </Link>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        <Stat label="Invoices" value={data.total} />
        <Stat label="Needs review" value={review} tone={review ? "amber" : undefined} />
        <Stat
          label="Auto-approved"
          value={data.auto_approve_rate === null ? "—" : `${Math.round(data.auto_approve_rate * 100)}%`}
          hint={`${data.auto_approved} of ${data.processed} processed`}
        />
        <Stat label="Flagged by guard" value={data.flagged} tone={data.flagged ? "red" : undefined} />
        <Stat label="Avg. processing" value={seconds(data.avg_processing_ms)} hint="upload → decision" />
      </div>

      <Card title="By status">
        <div className="flex h-3 overflow-hidden rounded-full bg-stone-100">
          {BAR_ORDER.map((s) =>
            data.counts[s] ? (
              <div key={s} className={BAR_COLOR[s]} style={{ width: `${(data.counts[s] / Math.max(1, data.total)) * 100}%` }} title={`${STATUS_LABEL[s]}: ${data.counts[s]}`} />
            ) : null,
          )}
        </div>
        <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-sm">
          {BAR_ORDER.map((s) => (
            <Link key={s} href={`/documents?status=${s}`} className="flex items-center gap-1.5 text-ink-soft hover:text-ink">
              <span className={`h-2.5 w-2.5 rounded-full ${BAR_COLOR[s]}`} />
              {STATUS_LABEL[s]} <span className="font-semibold tabular-nums text-ink">{data.counts[s]}</span>
            </Link>
          ))}
        </div>
      </Card>

      <div className="grid gap-6 xl:grid-cols-3">
        <Card title="Recent documents" className="xl:col-span-2" action={<Link href="/documents" className="text-sm text-brand hover:underline">All →</Link>}>
          <DocTable docs={data.recent} compact />
        </Card>

        <div className="space-y-6">
          <Card title={<span className="flex items-center gap-2">Flagged documents {data.flagged > 0 && <FlagBadge />}</span>}>
            {data.flagged_documents.length === 0 ? (
              <Empty>No prompt-injection attempts caught yet. Try a poisoned sample on the Upload page.</Empty>
            ) : (
              <ul className="divide-y divide-paper-line">
                {data.flagged_documents.map((d) => (
                  <li key={d.id} className="flex items-center justify-between gap-3 py-2.5">
                    <div className="min-w-0">
                      <DocLink id={d.id} review={d.status === "needs_review"}>
                        <span className="block truncate">{d.vendor_name || d.filename}</span>
                      </DocLink>
                      <span className="text-xs text-ink-muted">{d.invoice_number || d.filename} · {when(d.created_at)}</span>
                    </div>
                    <StatusBadge status={d.status} />
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card title="Price-change alerts">
            {data.price_alerts.length === 0 ? (
              <Empty>No unit price moved more than 10% against the vendor&apos;s last invoice.</Empty>
            ) : (
              <ul className="space-y-3">
                {data.price_alerts.map((a) => (
                  <li key={a.document_id} className="rounded-lg border border-amber-200 bg-amber-50/60 p-3">
                    <div className="flex items-center justify-between gap-2">
                      <DocLink id={a.document_id}>{a.vendor_name || `Document #${a.document_id}`}</DocLink>
                      <StatusBadge status={a.status} />
                    </div>
                    <ul className="mt-1.5 space-y-0.5 text-sm">
                      {a.changes.map((c) => (
                        <li key={c.item} className="flex justify-between gap-3">
                          <span className="truncate text-ink-soft">{c.item}</span>
                          <span className={`whitespace-nowrap font-mono text-xs ${c.change_pct > 0 ? "text-red-700" : "text-emerald-700"}`}>
                            {money(c.old)} → {money(c.new)} ({c.change_pct > 0 ? "+" : ""}
                            {c.change_pct}%)
                          </span>
                        </li>
                      ))}
                    </ul>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value, hint, tone }: { label: string; value: React.ReactNode; hint?: string; tone?: "amber" | "red" }) {
  const toneCls = tone === "amber" ? "text-amber-700" : tone === "red" ? "text-red-700" : "text-ink";
  return (
    <div className="rounded-xl border border-paper-line bg-white p-4 shadow-card">
      <p className="text-xs font-medium uppercase tracking-wide text-ink-muted">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${toneCls}`}>{value}</p>
      {hint && <p className="mt-0.5 text-xs text-ink-muted">{hint}</p>}
    </div>
  );
}
