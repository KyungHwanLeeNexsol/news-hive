'use client';

import { useState, useEffect, useCallback } from 'react';

const STORAGE_KEY = 'newshive_watchlist';

function getStored(): number[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function setStored(ids: number[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(ids));
}

/**
 * Hook to manage watchlist (localStorage-backed).
 */
export function useWatchlist() {
  const [watchlist, setWatchlist] = useState<number[]>([]);

  useEffect(() => {
    setWatchlist(getStored());
  }, []);

  const addStock = useCallback((id: number) => {
    setWatchlist((prev) => {
      if (prev.includes(id)) return prev;
      const next = [...prev, id];
      setStored(next);
      return next;
    });
  }, []);

  const removeStock = useCallback((id: number) => {
    setWatchlist((prev) => {
      const next = prev.filter((x) => x !== id);
      setStored(next);
      return next;
    });
  }, []);

  const toggleStock = useCallback((id: number) => {
    setWatchlist((prev) => {
      const next = prev.includes(id)
        ? prev.filter((x) => x !== id)
        : [...prev, id];
      setStored(next);
      return next;
    });
  }, []);

  const isWatched = useCallback((id: number) => watchlist.includes(id), [watchlist]);

  return { watchlist, addStock, removeStock, toggleStock, isWatched };
}
