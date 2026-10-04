"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { api, apiBlobUrl, getUser } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { CHECK_LABEL, DETECTOR_LABEL, FIELD_LABEL, money, seconds, stamp } from "@/lib/format";
import type { AuditEntry, DocumentDetail } from "@/lib/types";
import { PageViewer } from "@/components/PageViewer";
import { Button, Card, ErrorNote, FlagBadge, Spinner, StatusBadge, cx } from "@/components/ui";

const ACTION_LABEL: Record<string, string> = {
  received: "Received",
  email_received: "Email received",
  processing_started: "Processing started",
  processed: "Processed",
  auto_approved: "Auto-approved",
  approved: "Approved",
  corrected: "Fields corrected",
  note: "Note",
  rejected: "Rejected",
  export_requested: "Sent to n8n for export",
  export_failed: "Export failed",
  export_retry_requested: "Export retry requested",
  exported: "Bill created in Odoo",
  failed: "Processing failed",
  reprocess_requested: "Reprocess requested",
};

const STEPS = ["Received", "Read & screened", "Extracted & checked", "Decision", "In Odoo"];

function stepIndex(d: DocumentDetail): number {
  switch (d.status) {
    case "queued":
      return 0;
    case "processing":
      return d.guard ? 2 : 1;
    case "needs_review":
    case "approved":
    case "rejected":
    case "failed":
      return 3;
    case "exported":
      return 4;
  }
}

export default function DocumentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data: doc, error, reload } = useApi<DocumentDetail>(`/documents/${id}`, {
    intervalMs: 1500,
    shouldPoll: (d) => ["queued", "processing"].includes(d.status) || (d.status === "approved" && !d.odoo_bill_id),
  });
  const [busy, setBusy] = useState(false);
  const isAdmin = getUser()?.role === "admin";

  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!doc) return <div className="h-96 animate-pulse rounded-xl bg-stone-100" />;

  const data = doc.extraction?.data;
  const step = stepIndex(doc);
  const pending = doc.status === "queued" || doc.status === "processing";

  async function openOriginal() {
    const url = await apiBlobUrl(doc!.file_url);
    window.open(url, "_blank", "noopener");
  }

  async function retryExport() {
    setBusy(true);
    try {
      await api(`/documents/${id}/export`, { method: "POST" });
      await reload();
    } finally {
      setBusy(false);
    }
  }

  async function reprocess() {
    setBusy(true);
    try {
      await api(`/documents/${id}/reprocess`, { method: "POST" });
      await reload();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="text-sm text-ink-muted">
            <Link href="/documents" className="hover:text-ink">Documents</Link> / #{doc.id}
          </div>
          <h1 className="mt-1 flex flex-wrap items-center gap-2 text-2xl font-semibold">
            {data?.vendor_name || doc.filename}
            <StatusBadge status={doc.status} />
            {doc.flagged && <FlagBadge />}
          </h1>
          <p className="mt-1 text-sm text-ink-muted">
            {data?.invoice_number && <span className="font-mono">{data.invoice_number} · </span>}
            {money(data?.total ?? null, data?.currency)} · {doc.filename}
            {doc.source === "email" && <> · emailed{doc.email_from ? ` by ${doc.email_from}` : ""}</>}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {doc.status === "needs_review" && (
            <Link href={`/documents/${id}/review`} className="rounded-lg bg-amber-500 px-3.5 py-2 text-sm font-medium text-white hover:bg-amber-600">
              Review now →
            </Link>
          )}
          {doc.odoo_url && (
            <a href={doc.odoo_url} target="_blank" rel="noreferrer" className="rounded-lg bg-emerald-700 px-3.5 py-2 text-sm font-medium text-white hover:bg-emerald-800">
              Open bill #{doc.odoo_bill_id} in Odoo ↗
            </a>
          )}
          {doc.extraction?.trace_url && (
            <a href={doc.extraction.trace_url} target="_blank" rel="noreferrer" className="rounded-lg bg-white px-3.5 py-2 text-sm font-medium ring-1 ring-inset ring-paper-line hover:bg-stone-50">
              Langfuse trace ↗
            </a>
          )}
          <Button variant="secondary" onClick={openOriginal}>Original file</Button>
          {isAdmin && doc.status === "approved" && !doc.odoo_bill_id && (
            <Button variant="ghost" onClick={retryExport} disabled={busy}>
              {busy && <Spinner />} Retry export
            </Button>
          )}
          {isAdmin && (doc.status === "failed" || doc.status === "needs_review") && (
            <Button variant="ghost" onClick={reprocess} disabled={busy}>
              {busy && <Spinner />} Reprocess
            </Button>
          )}
        </div>
      </div>

      {(doc.odoo_url || doc.extraction?.trace_url) && (
        <p className="-mt-3 text-xs text-ink-muted">
          Odoo and Langfuse open in a new tab. Sign in there with <span className="font-mono">reviewer@demo.backhouse</span> /{" "}
          <span className="font-mono">demo1234</span> (read-only).
        </p>
      )}

      {/* Pipeline progress */}
      <ol className="grid grid-cols-5 gap-2">
        {STEPS.map((s, i) => {
          const done = i < step || (i === step && !pending);
          const current = i === step && pending;
          const failed = i === 3 && (doc.status === "failed" || doc.status === "rejected");
          return (
            <li key={s} className={cx("rounded-lg border px-3 py-2 text-xs sm:text-sm", failed ? "border-red-200 bg-red-50 text-red-800" : done ? "border-emerald-200 bg-emerald-50 text-emerald-900" : current ? "border-sky-200 bg-sky-50 text-sky-900" : "border-paper-line bg-white text-ink-muted")}>
              <span className="flex items-center gap-1.5 font-medium">
                {current ? <Spinner className="h-3 w-3" /> : done ? "✓" : `${i + 1}.`} {i === 3 && step >= 3 ? decisionLabel(doc) : s}
              </span>
            </li>
          );
        })}
      </ol>

      {doc.error && <ErrorNote>{doc.error}</ErrorNote>}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="space-y-6">
          {data && (
            <Card title="Extracted data" action={<span className="text-xs text-ink-muted">{doc.extraction?.model} · {seconds(doc.extraction?.latency_ms)}</span>}>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
                {(["vendor_name", "vendor_tax_id", "invoice_number", "invoice_date", "due_date", "currency"] as const).map((k) => (
                  <div key={k}>
                    <dt className="text-xs text-ink-muted">{FIELD_LABEL[k]}</dt>
                    <dd className="font-medium">{data[k] ?? "—"}</dd>
                  </div>
                ))}
              </dl>
              <table className="mt-4 w-full text-sm">
                <thead>
                  <tr className="border-b border-paper-line text-left text-xs text-ink-muted">
                    <th className="py-1.5 font-medium">Item</th>
                    <th className="py-1.5 text-right font-medium">Qty</th>
                    <th className="py-1.5 text-right font-medium">Unit</th>
                    <th className="py-1.5 text-right font-medium">Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {data.line_items.map((l, i) => (
                    <tr key={i} className="border-b border-paper-line/60">
                      <td className="py-1.5">{l.description}</td>
                      <td className="py-1.5 text-right tabular-nums">{l.quantity ?? "—"}</td>
                      <td className="py-1.5 text-right tabular-nums">{money(l.unit_price, data.currency)}</td>
                      <td className="py-1.5 text-right tabular-nums">{money(l.amount, data.currency)}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot className="text-right tabular-nums">
                  <tr><td colSpan={3} className="pt-2 text-ink-muted">Subtotal</td><td className="pt-2">{money(data.subtotal, data.currency)}</td></tr>
                  {data.discount ? (
                    <tr><td colSpan={3} className="text-ink-muted">Discount</td><td>−{money(Math.abs(data.discount), data.currency)}</td></tr>
                  ) : null}
                  <tr><td colSpan={3} className="text-ink-muted">Tax</td><td>{money(data.tax, data.currency)}</td></tr>
                  <tr className="font-semibold"><td colSpan={3}>Total</td><td>{money(data.total, data.currency)}</td></tr>
                </tfoot>
              </table>
            </Card>
          )}

          <Card title="Checks">
            {doc.checks.length === 0 ? (
              <p className="text-sm text-ink-muted">{pending ? "Running…" : "No checks recorded."}</p>
            ) : (
              <ul className="space-y-1.5 text-sm">
                {doc.checks.map((c) => (
                  <li key={c.name} className="flex gap-2">
                    <span className={c.passed ? "text-emerald-600" : c.severity === "warning" ? "text-amber-600" : "text-red-600"}>{c.passed ? "✓" : c.severity === "warning" ? "!" : "✗"}</span>
                    <span>
                      <span className="font-medium">{CHECK_LABEL[c.name] ?? c.name}</span> <span className="text-ink-muted">· {c.detail}</span>
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card title={<span className="flex items-center gap-2">Injection guard {doc.guard?.flagged && <FlagBadge />}</span>}>
            {!doc.guard ? (
              <p className="text-sm text-ink-muted">{pending ? "Screening…" : "Not run."}</p>
            ) : doc.guard.signals.filter((s) => s.strength !== "info").length === 0 ? (
              <p className="text-sm text-emerald-800">Clean: no hidden text and no instruction-like phrases.</p>
            ) : (
              <ul className="space-y-2 text-sm">
                {doc.guard.signals
                  .filter((s) => s.strength !== "info")
                  .map((s, i) => (
                    <li key={i} className={cx("rounded-lg p-2.5", s.strength === "strong" ? "bg-red-50 text-red-900" : "bg-stone-50")}>
                      <span className="font-semibold">{DETECTOR_LABEL[s.detector]}</span> <span className="text-xs uppercase">({s.strength})</span> · {s.detail}
                      {s.text && <q className="mt-1 block break-words font-mono text-xs">{s.text}</q>}
                    </li>
                  ))}
              </ul>
            )}
            {doc.guard?.signals.some((s) => s.strength === "info") && (
              <p className="mt-2 text-xs text-ink-muted">{doc.guard.signals.filter((s) => s.strength === "info").map((s) => s.detail).join(" · ")}</p>
            )}
          </Card>

          <Card title="Timeline">
            <ol className="relative space-y-4 border-l border-paper-line pl-5">
              {doc.audit.map((a, i) => (
                <TimelineItem key={i} entry={a} />
              ))}
            </ol>
          </Card>
        </div>

        <div className="lg:sticky lg:top-20 lg:self-start">
          {doc.page_urls.length > 0 ? (
            <PageViewer pageUrls={doc.page_urls} overlays={[]} />
          ) : (
            <div className="flex aspect-[8.5/11] items-center justify-center rounded-lg border border-dashed border-paper-line text-sm text-ink-muted">
              {pending ? <Spinner /> : "No page preview"}
            </div>
          )}
          <p className="mt-2 text-xs text-ink-muted">
            {doc.page_count ?? "?"} page(s) · text from {doc.text_source ?? "—"} · processed in {seconds(doc.processing_ms)} · sha256 {doc.sha256.slice(0, 12)}…
          </p>
        </div>
      </div>
    </div>
  );
}

function decisionLabel(d: DocumentDetail): string {
  if (d.status === "failed") return "Failed";
  if (d.status === "rejected") return "Rejected";
  if (d.auto_approved) return "Auto-approved";
  if (d.status === "needs_review") return "Needs review";
  return "Approved by reviewer";
}

function TimelineItem({ entry }: { entry: AuditEntry }) {
  const tone =
    entry.action === "rejected" || entry.action === "failed" || entry.action === "export_failed"
      ? "bg-red-500"
      : entry.action === "exported" || entry.action.includes("approved")
        ? "bg-emerald-500"
        : entry.action === "corrected"
          ? "bg-amber-500"
          : "bg-stone-300";
  const after = entry.after ?? {};
  return (
    <li className="relative">
      <span className={cx("absolute -left-[26px] top-1 h-3 w-3 rounded-full ring-4 ring-white", tone)} />
      <p className="text-sm">
        <span className="font-medium">{ACTION_LABEL[entry.action] ?? entry.action}</span>
        <span className="text-ink-muted"> · {entry.user ?? "system"} · {stamp(entry.at)}</span>
      </p>
      {entry.action === "corrected" && entry.before && (
        <ul className="mt-1 space-y-0.5 text-xs">
          {Object.keys(after).map((k) => (
            <li key={k}>
              <span className="text-ink-muted">{FIELD_LABEL[k] ?? k}:</span>{" "}
              <span className="text-red-700 line-through">{short(entry.before?.[k])}</span> → <span className="text-emerald-800">{short(after[k])}</span>
            </li>
          ))}
        </ul>
      )}
      {entry.action === "processed" && Array.isArray(after.reasons) && after.reasons.length > 0 && (
        <ul className="mt-1 list-inside list-disc text-xs text-ink-muted">
          {(after.reasons as string[]).slice(0, 6).map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}
      {entry.action === "rejected" && typeof after.reason === "string" && after.reason && <p className="mt-0.5 text-xs text-ink-muted">“{after.reason}”</p>}
      {entry.action === "exported" && <p className="mt-0.5 text-xs text-ink-muted">Odoo bill #{String(after.odoo_bill_id)}</p>}
      {(entry.action === "failed" || entry.action === "export_failed") && <p className="mt-0.5 break-words text-xs text-red-700">{String(after.error)}</p>}
    </li>
  );
}

function short(v: unknown): string {
  if (v === null || v === undefined || v === "") return "empty";
  if (Array.isArray(v)) return `${v.length} line(s)`;
  return String(v);
}
