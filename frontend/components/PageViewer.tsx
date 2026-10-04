"use client";

import { AuthImage } from "./AuthImage";
import { cx } from "./ui";

export type Overlay = {
  key: string;
  page: number;
  bbox: [number, number, number, number];
  tone: "active" | "field" | "danger" | "span";
  label?: string;
};

const TONE: Record<Overlay["tone"], string> = {
  active: "border-2 border-brand bg-amber-300/30 shadow-[0_0_0_4px_rgba(180,83,9,0.15)] z-20",
  field: "border border-amber-500/60 bg-amber-200/15 hover:bg-amber-300/30 z-10",
  danger: "border-2 border-dashed border-red-600 bg-red-500/15 z-30",
  span: "border border-sky-400/40 bg-sky-200/10 z-0",
};

function onPage(b: [number, number, number, number]) {
  return b[2] > 0 && b[3] > 0 && b[0] < 1 && b[1] < 1;
}

export function PageViewer({
  pageUrls,
  overlays,
  onSelect,
}: {
  pageUrls: string[];
  overlays: Overlay[];
  onSelect?: (key: string) => void;
}) {
  return (
    <div className="space-y-4">
      {pageUrls.map((url, page) => (
        <div key={url} className="relative overflow-hidden rounded-lg border border-paper-line bg-white shadow-card">
          <AuthImage path={url} alt={`Page ${page + 1}`} className="block w-full select-none" />
          {overlays
            .filter((o) => o.page === page && onPage(o.bbox))
            .map((o, i) => {
              const [x0, y0, x1, y1] = o.bbox.map((v) => Math.min(1, Math.max(0, v)));
              const pad = 0.003;
              return (
                <button
                  type="button"
                  key={`${o.key}-${i}`}
                  title={o.label}
                  onClick={() => onSelect?.(o.key)}
                  className={cx("absolute rounded-[3px] transition", TONE[o.tone], !onSelect && "pointer-events-none")}
                  style={{
                    left: `${(x0 - pad) * 100}%`,
                    top: `${(y0 - pad) * 100}%`,
                    width: `${(x1 - x0 + 2 * pad) * 100}%`,
                    height: `${(y1 - y0 + 2 * pad) * 100}%`,
                  }}
                >
                  {o.tone === "danger" && o.label && (
                    <span className="absolute -top-5 left-0 whitespace-nowrap rounded bg-red-600 px-1.5 py-0.5 text-[10px] font-semibold text-white">
                      {o.label}
                    </span>
                  )}
                </button>
              );
            })}
          {pageUrls.length > 1 && (
            <span className="absolute bottom-2 right-2 rounded bg-ink/70 px-2 py-0.5 text-xs text-white">
              {page + 1} / {pageUrls.length}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}
