"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

/** Fetch `path`, and keep refetching every `intervalMs` while `shouldPoll(data)` is true. */
export function useApi<T>(path: string | null, opts: { intervalMs?: number; shouldPoll?: (d: T) => boolean } = {}) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const optsRef = useRef(opts);
  optsRef.current = opts;

  const load = useCallback(async () => {
    if (!path) return;
    try {
      const d = await api<T>(path);
      setData(d);
      setError(null);
      return d;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    let cancelled = false;
    const tick = async () => {
      const d = await load();
      const { intervalMs, shouldPoll } = optsRef.current;
      if (cancelled || !intervalMs) return;
      if (!shouldPoll || (d !== undefined && shouldPoll(d))) {
        timer = setTimeout(tick, intervalMs);
      }
    };
    setLoading(true);
    tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [load]);

  return { data, error, loading, reload: load, setData };
}
