"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import { CHECK_LABEL, DETECTOR_LABEL, FIELD_LABEL, money } from "@/lib/format";
import type { DocumentDetail, InvoiceFields, LineItem } from "@/lib/types";
import { PageViewer, type Overlay } from "@/components/PageViewer";
import { Button, Confidence, ErrorNote, FlagBadge, Spinner, StatusBadge, cx } from "@/components/ui";

const TOL = 0.02;
const EMPTY: InvoiceFields = {
  vendor_name: null,
  vendor_tax_id: null,
  invoice_number: null,
  invoice_date: null,
  due_date: null,
  currency: null,
  line_items: [],
  subtotal: null,
  discount: null,
  tax: null,
  total: null,
};

type ScalarKey = Exclude<keyof InvoiceFields, "line_items">;
const HEADER_FIELDS: { key: ScalarKey; kind: "text" | "date" | "money"; wide?: boolean }[] = [
  { key: "vendor_name", kind: "text", wide: true },
  { key: "vendor_tax_id", kind: "text" },
  { key: "invoice_number", kind: "text" },
  { key: "invoice_date", kind: "date" },
  { key: "due_date", kind: "date" },
  { key: "currency", kind: "text" },
];
const TOTAL_FIELDS: ScalarKey[] = ["subtotal", "discount", "tax", "total"];

const near = (a: number, b: number) => Math.abs(a - b) <= TOL + 1e-9;

export default function ReviewPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { data: doc, error, setData } = useApi<DocumentDetail>(`/documents/${id}`, {
    intervalMs: 1500,
    shouldPoll: (d) => d.status === "queued" || d.status === "processing",
  });
  const [form, setForm] = useState<InvoiceFields>(EMPTY);
  const [active, setActive] = useState<string | null>(null);
  const [showText, setShowText] = useState(false);
  const [saving, setSaving] = useState<"approve" | "reject" | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const extraction = doc?.extraction;

  useEffect(() => {
    if (extraction) setForm({ ...EMPTY, ...extraction.data, line_items: (extraction.data.line_items ?? []).map((l) => ({ ...l })) });
  }, [extraction]);

  const overlays = useMemo<Overlay[]>(() => {
    if (!doc) return [];
    const out: Overlay[] = [];
    if (showText) doc.layout.spans.forEach((s) => out.push({ key: `span-${s.id}`, page: s.page, bbox: s.bbox, tone: "span", label: s.text }));
    Object.entries(extraction?.field_boxes ?? {}).forEach(([key, boxes]) => {
      const isActive = active !== null && (key === active || (active.startsWith("line_items.") && key.startsWith(active.split(".").slice(0, 2).join(".") + ".")));
      boxes.forEach((b) => out.push({ key, page: b.page, bbox: b.bbox, tone: isActive ? "active" : "field", label: FIELD_LABEL[key] ?? key }));
    });
    doc.layout.spans.filter((s) => s.excluded).forEach((s) => out.push({ key: `hidden-${s.id}`, page: s.page, bbox: s.bbox, tone: "danger", label: "removed by guard" }));
    return out;
  }, [doc, extraction, active, showText]);

  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!doc) return <div className="h-96 animate-pulse rounded-xl bg-stone-100" />;

  if (doc.status === "queued" || doc.status === "processing") {
    return (
      <div className="mx-auto max-w-lg space-y-4 py-16 text-center">
        <Spinner className="h-8 w-8 text-brand" />
        <h1 className="text-xl font-semibold">Processing {doc.filename}</h1>
        <p className="text-sm text-ink-muted">Reading text, screening for hidden instructions, extracting fields and running checks. This page updates by itself.</p>
      </div>
    );
  }

  const editable = doc.status === "needs_review";
  const conf = extraction?.field_confidence ?? {};
  const ungrounded = new Set(conf._ungrounded ?? []);
  const guard = doc.guard;
  const strong = guard?.signals.filter((s) => s.strength === "strong") ?? [];
  const weak = guard?.signals.filter((s) => s.strength === "weak") ?? [];
  const offPage = doc.layout.spans.filter((s) => s.excluded && (s.bbox[0] >= 1 || s.bbox[1] >= 1 || s.bbox[2] <= 0 || s.bbox[3] <= 0));
  const reasons = (doc.audit.filter((a) => a.action === "processed").pop()?.after?.reasons as string[] | undefined) ?? [];

  // Live arithmetic on the form as the reviewer edits it
  const linesSum = form.line_items.reduce((acc, l) => acc + (l.amount ?? 0), 0);
  const sumOk = form.subtotal !== null && near(linesSum, form.subtotal);
  const discount = Math.abs(form.discount ?? 0);
  const computedTotal = (form.subtotal ?? linesSum) - discount + (form.tax ?? 0);
  const totalOk = form.total !== null && near(computedTotal, form.total);

  const setField = (key: ScalarKey, value: string | number | null) => setForm((f) => ({ ...f, [key]: value }));
  const setLine = (i: number, patch: Partial<LineItem>) =>
    setForm((f) => ({ ...f, line_items: f.line_items.map((l, j) => (j === i ? { ...l, ...patch } : l)) }));

  async function approve() {
    if (guard?.flagged && !window.confirm("The injection guard flagged this document. Approve it anyway? The approval will trigger an alert.")) return;
    setSaving("approve");
    setActionError(null);
    try {
      const updated = await api<DocumentDetail>(`/documents/${id}/approve`, { method: "POST", body: JSON.stringify({ fields: form }) });
      setData(updated);
      router.push(`/documents/${id}`);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e));
      setSaving(null);
    }
  }

  async function reject() {
    const reason = window.prompt("Why are you rejecting this invoice?", guard?.flagged ? "Prompt-injection attempt" : "");
    if (reason === null) return;
    setSaving("reject");
    setActionError(null);
    try {
      await api(`/documents/${id}/reject`, { method: "POST", body: JSON.stringify({ reason }) });
      router.push(`/documents/${id}`);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e));
      setSaving(null);
    }
  }

  const focus = (key: string) => {
    setActive(key);
    const el = document.getElementById(`f-${key}`);
    if (el) {
      el.scrollIntoView({ block: "center", behavior: "smooth" });
      (el as HTMLInputElement).focus({ preventScroll: true });
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm text-ink-muted">
            <Link href="/documents" className="hover:text-ink">Documents</Link> / <Link href={`/documents/${id}`} className="hover:text-ink">#{id}</Link> / Review
          </div>
          <h1 className="flex flex-wrap items-center gap-2 text-xl font-semibold">
            <span className="truncate">{doc.filename}</span>
            <StatusBadge status={doc.status} />
            {guard?.flagged && <FlagBadge />}
          </h1>
        </div>
        <label className="flex items-center gap-2 text-sm text-ink-soft">
          <input type="checkbox" checked={showText} onChange={(e) => setShowText(e.target.checked)} className="accent-brand" />
          Show all text boxes
        </label>
      </div>

      {guard?.flagged && (
        <div className="rounded-xl border-2 border-red-300 bg-red-50 p-4 text-red-900">
          <div className="flex items-start gap-3">
            <svg viewBox="0 0 24 24" className="mt-0.5 h-6 w-6 shrink-0 text-red-600" fill="currentColor" aria-hidden>
              <path d="M12 2 1 21h22L12 2zm0 6 .01 0L13 15h-2l1-7zm-1 9h2v2h-2v-2z" />
            </svg>
            <div className="min-w-0 flex-1 space-y-2">
              <p className="font-semibold">Possible prompt injection. This document contains instructions aimed at an AI, or text a person can&apos;t see.</p>
              <p className="text-sm">
                The offending text was removed before extraction and the document was held for review. Check the invoice is genuine before approving;
                approving it will send an alert.
              </p>
              <ul className="space-y-2">
                {strong.map((s, i) => (
                  <li key={i} className="rounded-lg bg-white/80 p-2.5 text-sm ring-1 ring-red-200">
                    <span className="font-semibold">{DETECTOR_LABEL[s.detector] ?? s.detector}</span>
                    {s.page !== null && <span className="text-red-700"> · page {s.page + 1}</span>}
                    {s.detail && <span className="text-red-700"> · {s.detail}</span>}
                    {s.text && <q className="mt-1 block break-words font-mono text-xs text-red-950">{s.text}</q>}
                  </li>
                ))}
              </ul>
              {offPage.length > 0 && <p className="text-xs">{offPage.length} span(s) sit outside the visible page, so they can&apos;t be highlighted on the image.</p>}
            </div>
          </div>
        </div>
      )}

      {!editable && (
        <div className="rounded-lg border border-paper-line bg-white px-4 py-3 text-sm">
          This document is <StatusBadge status={doc.status} /> and can no longer be edited.{" "}
          <Link href={`/documents/${id}`} className="font-medium text-brand hover:underline">See its history →</Link>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        {/* Document */}
        <div className="lg:sticky lg:top-20 lg:max-h-[calc(100vh-6rem)] lg:overflow-y-auto lg:pr-1">
          <PageViewer pageUrls={doc.page_urls} overlays={overlays} onSelect={(k) => !k.startsWith("span-") && !k.startsWith("hidden-") && focus(k)} />
          <p className="mt-2 text-xs text-ink-muted">
            Text from {doc.text_source === "ocr" ? "OCR" : doc.text_source === "mixed" ? "text layer + OCR" : "the PDF text layer"} · click a highlight to jump to its field.
          </p>
        </div>

        {/* Fields */}
        <div className="space-y-5">
          {reasons.length > 0 && editable && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">
              <p className="font-semibold">Why this needs a human</p>
              <ul className="mt-1 list-inside list-disc space-y-0.5">
                {reasons.slice(0, 8).map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            </div>
          )}

          <fieldset disabled={!editable} className="space-y-5">
            <section className="rounded-xl border border-paper-line bg-white p-4 shadow-card">
              <h2 className="mb-3 text-sm font-semibold">Invoice</h2>
              <div className="grid grid-cols-2 gap-3">
                {HEADER_FIELDS.map(({ key, kind, wide }) => (
                  <Field key={key} name={key} active={active === key} conf={conf[key]} ungrounded={ungrounded.has(key)} wide={wide}>
                    <input
                      id={`f-${key}`}
                      className="field-input"
                      type={kind === "date" ? "date" : "text"}
                      value={(form[key] as string | null) ?? ""}
                      onFocus={() => setActive(key)}
                      onChange={(e) => setField(key, e.target.value || null)}
                    />
                  </Field>
                ))}
              </div>
            </section>

            <section className="rounded-xl border border-paper-line bg-white p-4 shadow-card">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="flex items-center gap-2 text-sm font-semibold">
                  Line items <Confidence value={conf.line_items} ungrounded={ungrounded.has("line_items")} />
                </h2>
                {editable && (
                  <Button
                    variant="ghost"
                    className="px-2 py-1 text-xs"
                    onClick={() => setForm((f) => ({ ...f, line_items: [...f.line_items, { description: "", quantity: 1, unit_price: null, amount: null }] }))}
                  >
                    + Add line
                  </Button>
                )}
              </div>
              <div className="-mx-1 overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-ink-muted">
                      <th className="px-1 pb-1 font-medium">Description</th>
                      <th className="w-16 px-1 pb-1 text-right font-medium">Qty</th>
                      <th className="w-24 px-1 pb-1 text-right font-medium">Unit</th>
                      <th className="w-24 px-1 pb-1 text-right font-medium">Amount</th>
                      <th className="w-6" />
                    </tr>
                  </thead>
                  <tbody>
                    {form.line_items.map((l, i) => {
                      const mathOk = l.quantity === null || l.unit_price === null || l.amount === null || near(l.quantity * l.unit_price, l.amount);
                      const rowActive = active?.startsWith(`line_items.${i}.`);
                      return (
                        <tr key={i} className={cx(rowActive && "bg-amber-50")}>
                          <td className="px-1 py-1">
                            <input id={`f-line_items.${i}.description`} className="field-input" value={l.description} onFocus={() => setActive(`line_items.${i}.description`)} onChange={(e) => setLine(i, { description: e.target.value })} />
                          </td>
                          {(["quantity", "unit_price", "amount"] as const).map((k) => (
                            <td key={k} className="px-1 py-1">
                              <NumberInput
                                id={`f-line_items.${i}.${k}`}
                                value={l[k]}
                                invalid={k === "amount" && !mathOk}
                                onFocus={() => setActive(`line_items.${i}.${k}`)}
                                onChange={(v) => setLine(i, { [k]: v })}
                              />
                            </td>
                          ))}
                          <td className="px-1 text-center">
                            {editable && (
                              <button type="button" className="text-stone-400 hover:text-red-600" title="Remove line" onClick={() => setForm((f) => ({ ...f, line_items: f.line_items.filter((_, j) => j !== i) }))}>
                                ×
                              </button>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              {form.line_items.some((l) => l.quantity !== null && l.unit_price !== null && l.amount !== null && !near(l.quantity * l.unit_price, l.amount)) && (
                <p className="mt-2 text-xs text-red-700">Highlighted amounts don&apos;t equal quantity × unit price.</p>
              )}
            </section>

            <section className="rounded-xl border border-paper-line bg-white p-4 shadow-card">
              <h2 className="mb-3 text-sm font-semibold">Totals</h2>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                {TOTAL_FIELDS.map((key) => (
                  <Field key={key} name={key} active={active === key} conf={conf[key]} ungrounded={ungrounded.has(key)}>
                    <NumberInput id={`f-${key}`} value={form[key] as number | null} onFocus={() => setActive(key)} onChange={(v) => setField(key, v)} />
                  </Field>
                ))}
              </div>
              <ul className="mt-3 space-y-1 text-sm">
                <LiveCheck ok={sumOk} label={`Lines add up to ${money(linesSum, form.currency)}`} hint={form.subtotal !== null ? `subtotal ${money(form.subtotal, form.currency)}` : "no subtotal"} />
                <LiveCheck ok={totalOk} label={discount ? "Subtotal − discount + tax = total" : "Subtotal + tax = total"} hint={form.total !== null ? money(computedTotal, form.currency) : "no total"} />
              </ul>
            </section>
          </fieldset>

          <section className="rounded-xl border border-paper-line bg-white p-4 shadow-card">
            <h2 className="mb-2 text-sm font-semibold">Checks from the last run</h2>
            <ul className="space-y-1.5">
              {doc.checks.map((c) => (
                <li key={c.name} className="flex gap-2 text-sm">
                  <span className={cx("mt-0.5 h-4 w-4 shrink-0 rounded-full text-center text-[10px] font-bold leading-4 text-white", c.passed ? "bg-emerald-500" : c.severity === "warning" ? "bg-amber-500" : "bg-red-500")}>
                    {c.passed ? "✓" : c.severity === "warning" ? "!" : "×"}
                  </span>
                  <span>
                    <span className="font-medium">{CHECK_LABEL[c.name] ?? c.name}</span>
                    <span className="block text-xs text-ink-muted">{c.detail}</span>
                  </span>
                </li>
              ))}
            </ul>
            {weak.length > 0 && (
              <details className="mt-3 text-sm">
                <summary className="cursor-pointer text-ink-muted">{weak.length} weak guard signal(s), recorded but not blocking</summary>
                <ul className="mt-1 space-y-1 text-xs">
                  {weak.map((s, i) => (
                    <li key={i}>
                      <span className="font-medium">{DETECTOR_LABEL[s.detector]}</span>: {s.detail} <q className="font-mono">{s.text.slice(0, 120)}</q>
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </section>

          {actionError && <ErrorNote>{actionError}</ErrorNote>}

          {editable && (
            <div className="sticky bottom-0 -mx-1 flex items-center justify-end gap-3 border-t border-paper-line bg-paper/95 px-1 py-3 backdrop-blur">
              <span className="mr-auto text-xs text-ink-muted">Your edits are saved with the approval and recorded in the audit log.</span>
              <Button variant="danger" onClick={reject} disabled={saving !== null}>
                {saving === "reject" && <Spinner />} Reject
              </Button>
              <Button variant="success" onClick={approve} disabled={saving !== null}>
                {saving === "approve" && <Spinner />} Approve &amp; send to Odoo
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Field({ name, active, conf, ungrounded, wide, children }: { name: string; active: boolean; conf?: number; ungrounded: boolean; wide?: boolean; children: React.ReactNode }) {
  return (
    <label className={cx("block space-y-1 rounded-lg p-1.5 transition", wide && "col-span-2", active && "bg-amber-50 ring-1 ring-amber-300")}>
      <span className="flex items-center justify-between gap-2 text-xs font-medium text-ink-soft">
        {FIELD_LABEL[name] ?? name}
        <Confidence value={conf} ungrounded={ungrounded} />
      </span>
      {children}
    </label>
  );
}

function NumberInput({ id, value, onChange, onFocus, invalid }: { id: string; value: number | null; onChange: (v: number | null) => void; onFocus?: () => void; invalid?: boolean }) {
  return (
    <input
      id={id}
      type="number"
      step="any"
      inputMode="decimal"
      className={cx("field-input text-right tabular-nums", invalid && "border-red-400 bg-red-50")}
      value={value ?? ""}
      onFocus={onFocus}
      onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
    />
  );
}

function LiveCheck({ ok, label, hint }: { ok: boolean; label: string; hint: string }) {
  return (
    <li className={cx("flex items-center gap-2", ok ? "text-emerald-800" : "text-red-700")}>
      <span className="font-bold">{ok ? "✓" : "✗"}</span> {label} <span className="text-xs text-ink-muted">({hint})</span>
    </li>
  );
}
