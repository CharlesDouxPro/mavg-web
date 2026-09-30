import { useCallback, useEffect, useRef, useState } from "react";

/** Une valeur qui ne suit `value` qu'après `ms` sans changement. */
export function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return debounced;
}

/** Charge `load`, et le recharge toutes les `interval(data)` ms tant que la page est visible. */
export function usePolling<T>(
  load: () => Promise<T>,
  deps: unknown[],
  interval: (data: T | null) => number | null,
) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);
  const loadRef = useRef(load);
  loadRef.current = load;
  const intervalRef = useRef(interval);
  intervalRef.current = interval;
  const [tick, setTick] = useState(0);

  const refresh = useCallback(() => setTick((value) => value + 1), []);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const run = async () => {
      try {
        const next = await loadRef.current();
        if (cancelled) return;
        setData(next);
        setError(null);
        schedule(next);
      } catch (err) {
        if (cancelled) return;
        setError(err as Error);
        schedule(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    const schedule = (next: T | null) => {
      const ms = intervalRef.current(next);
      if (ms !== null) timer = setTimeout(() => (document.hidden ? schedule(next) : run()), ms);
    };
    run();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  return { data, error, loading, refresh, setData };
}
