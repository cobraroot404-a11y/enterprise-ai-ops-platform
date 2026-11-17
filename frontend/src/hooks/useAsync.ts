import { useCallback, useEffect, useRef, useState } from "react";

export interface AsyncState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

interface Settled<T> {
  key: string;
  data: T | null;
  error: string | null;
}

/**
 * Run an async loader whenever `deps` (primitives) change or `reload()` is called. `loading` is derived from whether the
 * latest request key has settled, so no state is set synchronously inside the effect. Stale responses are ignored.
 */
export function useAsync<T>(load: () => Promise<T>, deps: unknown[]): AsyncState<T> {
  const [tick, setTick] = useState(0);
  const [settled, setSettled] = useState<Settled<T> | null>(null);
  const key = JSON.stringify([...deps, tick]);
  const loader = useRef(load);
  useEffect(() => { loader.current = load; });

  useEffect(() => {
    let cancelled = false;
    loader
      .current()
      .then((data) => { if (!cancelled) setSettled({ key, data, error: null }); })
      .catch((err: Error) => { if (!cancelled) setSettled((prev) => ({ key, data: prev?.data ?? null, error: err.message })); });
    return () => { cancelled = true; };
  }, [key]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  const current = settled?.key === key;
  return { data: settled?.data ?? null, error: current ? settled?.error ?? null : null, loading: !current, reload };
}
