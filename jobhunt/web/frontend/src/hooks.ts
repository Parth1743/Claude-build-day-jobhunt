import { useCallback, useEffect, useRef, useState } from "react";
import { waitForTask } from "./api";
import type { Task } from "./types";

/** Load data with loading/error state and a manual refresh. */
export function useLoad<T>(loader: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      setData(await loaderRef.current());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    reload();
  }, deps);

  return { data, error, loading, reload, setData };
}

/** Run a background AI task: start it, poll it, expose progress. */
export function useTask<T>() {
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const timer = useRef<number | null>(null);

  const run = useCallback(async (start: () => Promise<Task>): Promise<T | null> => {
    setRunning(true);
    setError(null);
    setElapsed(0);
    const began = Date.now();
    timer.current = window.setInterval(() => setElapsed(Math.round((Date.now() - began) / 1000)), 1000);
    try {
      const task = await start();
      return await waitForTask<T>(task.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return null;
    } finally {
      setRunning(false);
      if (timer.current) window.clearInterval(timer.current);
    }
  }, []);

  return { run, running, error, elapsed, clearError: () => setError(null) };
}

/** Copy text to the clipboard and report success briefly. */
export function useCopy() {
  const [copied, setCopied] = useState<string | null>(null);
  const copy = useCallback(async (key: string, text: string) => {
    await navigator.clipboard.writeText(text);
    setCopied(key);
    setTimeout(() => setCopied(null), 1500);
  }, []);
  return { copy, copied };
}
