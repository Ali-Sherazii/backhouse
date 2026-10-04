"use client";

import { useEffect, useState } from "react";
import { useApi } from "@/lib/hooks";
import { STATUS_LABEL } from "@/lib/format";
import type { DocumentSummary, Status } from "@/lib/types";
import { Card, ErrorNote, cx } from "@/components/ui";
import { DocTable } from "@/components/DocTable";

const TABS: (Status | "all" | "flagged")[] = ["all", "needs_review", "approved", "exported", "processing", "queued", "failed", "rejected", "flagged"];

export default function DocumentsPage() {
  const [tab, setTab] = useState<(typeof TABS)[number]>("all");

  // Read ?status= on first render (avoids useSearchParams' Suspense requirement).
  useEffect(() => {
    const s = new URLSearchParams(window.location.search).get("status");
    if (s && (TABS as string[]).includes(s)) setTab(s as (typeof TABS)[number]);
  }, []);

  const query = tab === "all" ? "" : tab === "flagged" ? "?flagged=true" : `?status=${tab}`;
  const { data, error } = useApi<DocumentSummary[]>(`/documents${query}`, { intervalMs: 4000 });

  function select(t: (typeof TABS)[number]) {
    setTab(t);
    const url = t === "all" ? "/documents" : `/documents?status=${t}`;
    window.history.replaceState(null, "", url);
  }

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Documents</h1>
      <div className="flex flex-wrap gap-1.5">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => select(t)}
            className={cx(
              "rounded-full px-3 py-1 text-sm transition",
              tab === t ? "bg-ink text-white" : "bg-white text-ink-soft ring-1 ring-inset ring-paper-line hover:bg-stone-50",
            )}
          >
            {t === "all" ? "All" : t === "flagged" ? "Flagged by guard" : STATUS_LABEL[t]}
          </button>
        ))}
      </div>
      {error && <ErrorNote>{error}</ErrorNote>}
      <Card>{data ? <DocTable docs={data} /> : <div className="h-32 animate-pulse rounded bg-stone-100" />}</Card>
    </div>
  );
}
