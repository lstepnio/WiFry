import { useCallback, useEffect, useRef, useState } from 'react';

export type ApiFetcher<T> = (signal: AbortSignal) => Promise<T>;

interface UseApiResult<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export function useApi<T>(
  fetcher: ApiFetcher<T>,
  pollInterval?: number
): UseApiResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);

  const load = useCallback(async () => {
    // Abort any in-flight request
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;

    try {
      const result = await fetcher(controller.signal);
      if (!controller.signal.aborted) {
        setData(result);
        setError(null);
      }
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') {
        return; // Request was cancelled — don't update state
      }
      if (!controller.signal.aborted) {
        setError(e instanceof Error ? e.message : 'Unknown error');
      }
    } finally {
      if (!controller.signal.aborted) {
        setLoading(false);
      }
    }
  }, [fetcher]);

  useEffect(() => {
    load();
    let intervalId: ReturnType<typeof setInterval> | undefined;
    if (pollInterval) {
      intervalId = setInterval(load, pollInterval);
    }
    return () => {
      controllerRef.current?.abort();
      if (intervalId) clearInterval(intervalId);
    };
  }, [load, pollInterval]);

  return { data, loading, error, refresh: load };
}
