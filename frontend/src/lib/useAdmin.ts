'use client';

import { useState, useEffect, useCallback } from 'react';

const TOKEN_KEY = 'nh_admin_token';

export function useAdmin() {
  const [token, setToken] = useState<string | null>(null);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    const saved = localStorage.getItem(TOKEN_KEY);
    if (!saved) {
      setChecking(false);
      return;
    }
    // Verify token is still valid
    fetch('/api/auth/verify', {
      headers: { Authorization: `Bearer ${saved}` },
    })
      .then((res) => {
        if (res.ok) {
          setToken(saved);
        } else {
          localStorage.removeItem(TOKEN_KEY);
        }
      })
      .catch(() => {
        localStorage.removeItem(TOKEN_KEY);
      })
      .finally(() => setChecking(false));
  }, []);

  const login = useCallback(async (password: string): Promise<boolean> => {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password }),
    });
    if (!res.ok) return false;
    const data = await res.json();
    localStorage.setItem(TOKEN_KEY, data.token);
    setToken(data.token);
    return true;
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    setToken(null);
  }, []);

  return { isAdmin: !!token, token, checking, login, logout };
}

/** Get the stored admin token for API calls. */
export function getAdminToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem(TOKEN_KEY);
}
