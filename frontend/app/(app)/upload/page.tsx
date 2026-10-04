"use client";

import { useCallback, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { DocumentSummary, Sample } from "@/lib/types";
import { Button, Card, DocLink, ErrorNote, FlagBadge, Spinner, StatusBadge, cx } from "@/components/ui";

const KIND_STYLE: Record<string, { label: string; cls: string }> = {
  clean: { label: "Clean", cls: "bg-emerald-50 text-emerald-800" },
  scanned: { label: "Scan / photo", cls: "bg-sky-50 text-sky-800" },
  bad_totals: { label: "Bad totals", cls: "bg-amber-50 text-amber-800" },
  duplicate: { label: "Duplicate", cls: "bg-amber-50 text-amber-800" },
  price_jump: { label: "Price jump", cls: "bg-amber-50 text-amber-800" },
  poisoned: { label: "Prompt injection", cls: "bg-red-50 text-red-700" },
};
const ACCEPT = ".pdf,.png,.jpg,.jpeg,.webp,.tif,.tiff,application/pdf,image/*";
const INTAKE_EMAIL = process.env.NEXT_PUBLIC_INTAKE_EMAIL || "";

export default function UploadPage() {
  const samples = useApi<Sample[]>("/samples");
  const [uploaded, setUploaded] = useState<DocumentSummary[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [uploading, setUploading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const add = (doc: DocumentSummary) => setUploaded((u) => [doc, ...u.filter((d) => d.id !== doc.id)]);

  const uploadFiles = useCallback(async (files: FileList | File[]) => {
    setError(null);
    for (const file of Array.from(files)) {
      setUploading(file.name);
      try {
        const form = new FormData();
        form.append("file", file);
        add(await api<DocumentSummary>("/documents", { method: "POST", body: form }));
      } catch (e) {
        setError(`${file.name}: ${e instanceof Error ? e.message : e}`);
      }
    }
    setUploading(null);
  }, []);

  async function trySample(name: string) {
    setBusy(name);
    setError(null);
    try {
      add(await api<DocumentSummary>(`/samples/${encodeURIComponent(name)}`, { method: "POST" }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
    setBusy(null);
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Upload</h1>
        <p className="text-sm text-ink-muted">PDFs, scans and phone photos. Each file is checked for hidden instructions before the model reads it.</p>
      </div>

      <div className="grid gap-6 lg:grid-cols-5">
        <div className="space-y-6 lg:col-span-3">
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDrag(true);
            }}
            onDragLeave={() => setDrag(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDrag(false);
              if (e.dataTransfer.files.length) uploadFiles(e.dataTransfer.files);
            }}
            onClick={() => input.current?.click()}
            className={cx(
              "flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-14 text-center transition",
              drag ? "border-brand bg-brand-soft/50" : "border-stone-300 bg-white hover:border-stone-400",
            )}
          >
            <svg viewBox="0 0 24 24" className="h-10 w-10 text-stone-400" fill="none" stroke="currentColor" strokeWidth={1.5} aria-hidden>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 16V4m0 0-4 4m4-4 4 4M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" />
            </svg>
            <p className="mt-3 font-medium">{uploading ? <>Uploading {uploading}…</> : "Drop invoices here or click to choose"}</p>
            <p className="mt-1 text-sm text-ink-muted">PDF, PNG, JPG, WEBP or TIFF · up to 15 MB</p>
            <input
              ref={input}
              type="file"
              accept={ACCEPT}
              multiple
              className="hidden"
              onChange={(e) => {
                if (e.target.files?.length) uploadFiles(e.target.files);
                e.target.value = "";
              }}
            />
          </div>

          {error && <ErrorNote>{error}</ErrorNote>}

          <Card title="Just uploaded">
            {uploaded.length === 0 ? (
              <p className="py-4 text-center text-sm text-ink-muted">Files you upload here show up with live status.</p>
            ) : (
              <ul className="divide-y divide-paper-line">
                {uploaded.map((d) => (
                  <LiveRow key={d.id} initial={d} />
                ))}
              </ul>
            )}
          </Card>

          <Card title="Email intake">
            {INTAKE_EMAIL ? (
              <p className="text-sm text-ink-soft">
                Email a PDF or photo of an invoice, from any address, to{" "}
                <a href={`mailto:${INTAKE_EMAIL}`} className="font-mono font-medium text-brand hover:underline">
                  {INTAKE_EMAIL}
                </a>
                . n8n picks it up within about 20 seconds and it appears in Documents with an ✉ marker.
              </p>
            ) : (
              <p className="text-sm text-ink-soft">
                Invoices emailed to the intake inbox are picked up by n8n every 20 seconds and appear in Documents with an ✉ marker. Locally, send
                mail to the Mailpit SMTP server on port 1025 (any address).
              </p>
            )}
          </Card>
        </div>

        <Card title="Try a sample" className="lg:col-span-2">
          <p className="mb-3 text-sm text-ink-muted">Generated invoices from fake food suppliers, including some designed to fail.</p>
          {samples.error && <ErrorNote>{samples.error}</ErrorNote>}
          <ul className="space-y-2">
            {(samples.data ?? []).map((s) => {
              const k = KIND_STYLE[s.kind] ?? { label: s.kind, cls: "bg-stone-100" };
              return (
                <li key={s.name} className="flex items-start justify-between gap-3 rounded-lg border border-paper-line p-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-medium">{s.title}</span>
                      <span className={cx("rounded px-1.5 py-0.5 text-[11px] font-medium", k.cls)}>{k.label}</span>
                    </div>
                    <p className="mt-0.5 text-xs text-ink-muted">{s.description}</p>
                  </div>
                  <Button variant="secondary" className="shrink-0 px-3 py-1.5 text-xs" disabled={busy !== null} onClick={() => trySample(s.name)}>
                    {busy === s.name ? <Spinner className="h-3 w-3" /> : "Try"}
                  </Button>
                </li>
              );
            })}
          </ul>
        </Card>
      </div>
    </div>
  );
}

function LiveRow({ initial }: { initial: DocumentSummary }) {
  const { data } = useApi<DocumentSummary>(`/documents/${initial.id}`, {
    intervalMs: 1500,
    shouldPoll: (d) => d.status === "queued" || d.status === "processing",
  });
  const d = data ?? initial;
  return (
    <li className="flex items-center justify-between gap-3 py-2.5">
      <div className="min-w-0">
        <DocLink id={d.id} review={d.status === "needs_review"}>
          <span className="block truncate">{d.vendor_name || d.filename}</span>
        </DocLink>
        <span className="text-xs text-ink-muted">
          #{d.id} · {d.filename}
        </span>
      </div>
      <span className="flex items-center gap-1.5">
        {d.flagged && <FlagBadge />}
        <StatusBadge status={d.status} />
      </span>
    </li>
  );
}
