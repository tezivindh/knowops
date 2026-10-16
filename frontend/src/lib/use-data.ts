"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { errorMessage } from "@/lib/api";

interface State<T> {
  key: string | null;
  data: T | undefined;
  error: string | null;
}

/**
 * Load data for a screen.
 *
 * Re-fetches when `deps` change (they must be JSON-serialisable primitives),
 * ignores responses from superseded requests, and exposes `reload` for after
 * mutations. `loading` is true until the request for the current deps has
 * settled; `reload` refreshes quietly without flipping it.
 */
export function useData<T>(load: (() => Promise<T>) | null, deps: unknown[]) {
  const key = JSON.stringify(deps);
  const [state, setState] = useState<State<T>>({ key: null, data: undefined, error: null });
  const loadRef = useRef(load);
  const keyRef = useRef(key);
  const generation = useRef(0);

  useLayoutEffect(() => {
    loadRef.current = load;
    keyRef.current = key;
  });

  const fetchNow = useCallback(async () => {
    const fn = loadRef.current;
    if (!fn) return;
    const current = ++generation.current;
    const forKey = keyRef.current;
    try {
      const data = await fn();
      if (current === generation.current) setState({ key: forKey, data, error: null });
    } catch (e) {
      if (current === generation.current)
        setState((s) => ({ key: forKey, data: s.key === forKey ? s.data : undefined, error: errorMessage(e) }));
    }
  }, []);

  // Each fetch bumps the generation, so a response for superseded deps is dropped.
  useEffect(() => {
    void fetchNow();
  }, [key, fetchNow]);

  const setData = useCallback((update: (current: T | undefined) => T | undefined) => {
    setState((s) => ({ ...s, data: update(s.data) }));
  }, []);

  return {
    data: state.data,
    error: state.key === key ? state.error : null,
    loading: load !== null && state.key !== key,
    reload: fetchNow,
    setData,
  };
}

/** Run `callback` every `ms` while `active` is true. */
export function useInterval(callback: () => void | Promise<void>, ms: number, active: boolean) {
  const saved = useRef(callback);
  useLayoutEffect(() => {
    saved.current = callback;
  });
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => void saved.current(), ms);
    return () => clearInterval(id);
  }, [ms, active]);
}
