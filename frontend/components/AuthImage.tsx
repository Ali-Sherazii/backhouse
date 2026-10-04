"use client";

import { useEffect, useState } from "react";
import { apiBlobUrl } from "@/lib/api";
import { Spinner } from "./ui";

/** <img> for endpoints that need the bearer token. */
export function AuthImage({ path, alt, className, onLoad }: { path: string; alt: string; className?: string; onLoad?: () => void }) {
  const [src, setSrc] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let url: string | null = null;
    let cancelled = false;
    apiBlobUrl(path)
      .then((u) => {
        if (cancelled) URL.revokeObjectURL(u);
        else {
          url = u;
          setSrc(u);
        }
      })
      .catch(() => setFailed(true));
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [path]);

  if (failed) return <div className="flex aspect-[8.5/11] items-center justify-center bg-stone-100 text-sm text-ink-muted">Page image unavailable</div>;
  if (!src)
    return (
      <div className="flex aspect-[8.5/11] items-center justify-center bg-stone-50 text-ink-muted">
        <Spinner />
      </div>
    );
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={src} alt={alt} className={className} onLoad={onLoad} draggable={false} />;
}
