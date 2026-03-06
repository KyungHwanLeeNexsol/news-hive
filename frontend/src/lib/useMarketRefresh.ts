"use client";

import { useEffect, useRef, useState } from "react";
import { fetchMarketStatus } from "./api";

/**
 * Hook that calls `callback` at an interval that adapts to market hours.
 * - Market open (09:00~15:30 KST weekdays): every 15 seconds
 * - Market closed: no auto-refresh (interval = 0)
 *
 * Checks market status every 5 minutes to detect open/close transitions.
 */
export function useMarketRefresh(callback: () => void) {
  const [intervalMs, setIntervalMs] = useState(0); // 0 = disabled
  const callbackRef = useRef(callback);
  callbackRef.current = callback;

  // Check market status periodically and update interval
  useEffect(() => {
    let mounted = true;

    const checkStatus = () => {
      fetchMarketStatus()
        .then((s) => {
          if (mounted) {
            setIntervalMs(s.refresh_interval > 0 ? s.refresh_interval * 1000 : 0);
          }
        })
        .catch(() => {});
    };

    checkStatus();
    const statusTimer = setInterval(checkStatus, 5 * 60_000);
    return () => {
      mounted = false;
      clearInterval(statusTimer);
    };
  }, []);

  // Run callback at the adaptive interval (skip if 0 = market closed)
  useEffect(() => {
    if (intervalMs <= 0) return;
    const timer = setInterval(() => callbackRef.current(), intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs]);

  return intervalMs;
}
