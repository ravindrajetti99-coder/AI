"use client";

import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";

type Query = Record<string, string | number | boolean | undefined | null>;
type Result<T> = { key: string | null; data?: T; error: unknown };

/**
 * Fetch `path` on mount and whenever it (or `query`) changes; a `null` path skips the request.
 * `loading` is derived: true until a result for the current request has arrived.
 */
export function useApi<T>(path: string | null, query?: Query) {
  const queryKey = JSON.stringify(query ?? {});
  const requestKey = path ? `${path}?${queryKey}` : null;
  const [result, setResult] = useState<Result<T>>({ key: null, error: null });

  useEffect(() => {
    if (!path) return;
    let live = true;
    api<T>(path, { query: JSON.parse(queryKey) as Query }).then(
      (data) => live && setResult({ key: requestKey, data, error: null }),
      (error) => live && setResult({ key: requestKey, error }),
    );
    return () => {
      live = false;
    };
  }, [path, queryKey, requestKey]);

  /** Refetch in place (keeps showing the current data meanwhile). */
  const reload = useCallback(async () => {
    if (!path) return;
    try {
      const data = await api<T>(path, { query: JSON.parse(queryKey) as Query });
      setResult({ key: requestKey, data, error: null });
    } catch (error) {
      setResult((prev) => ({ key: requestKey, data: prev.key === requestKey ? prev.data : undefined, error }));
    }
  }, [path, queryKey, requestKey]);

  const setData = useCallback((data: T) => setResult({ key: requestKey, data, error: null }), [requestKey]);
  const current = result.key === requestKey;
  return { data: current ? result.data : undefined, error: current ? result.error : null, loading: path !== null && !current, reload, setData };
}
