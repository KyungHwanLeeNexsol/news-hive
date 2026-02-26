'use client';

import { useEffect } from 'react';

/**
 * Silently pings the backend via /api/keep-alive on first page load.
 * This wakes up the Render free-tier backend so subsequent API calls
 * don't hit a cold start timeout.
 */
export default function BackendWakeUp() {
  useEffect(() => {
    fetch('/api/keep-alive').catch(() => {});
  }, []);

  return null;
}
