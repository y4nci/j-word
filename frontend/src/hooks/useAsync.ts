import { useCallback, useEffect, useState } from "react";

/**
 * Runs one async action at a time (LLM calls can take a minute) and keeps
 * its loading / error state. `busy` holds the label of the running action.
 */
export function useAsync() {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async <T,>(label: string, fn: () => Promise<T>): Promise<T | undefined> => {
    setBusy(label);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return undefined;
    } finally {
      setBusy(null);
    }
  }, []);

  return { busy, error, setError, run };
}

/**
 * Fetches data whenever `fetcher` changes (memoize it with useCallback) or
 * `reload()` is called. Responses that arrive after a newer request are ignored.
 */
export function useResource<T>(fetcher: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let stale = false;
    fetcher().then(
      (d) => { if (!stale) { setData(d); setError(null); } },
      (e: unknown) => { if (!stale) setError(e instanceof Error ? e.message : String(e)); }
    );
    return () => { stale = true; };
  }, [fetcher, version]);

  const reload = useCallback(() => setVersion((v) => v + 1), []);
  return { data, error, reload };
}
