'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import type { User, AuthTokens } from './types';

// @MX:NOTE: localStorage 키 상수 — 여러 곳에서 참조하므로 한 곳에서 관리
const ACCESS_TOKEN_KEY = 'nh_access_token';
const REFRESH_TOKEN_KEY = 'nh_refresh_token';
const USER_KEY = 'nh_user';

/**
 * JWT exp 클레임을 디코딩해 만료 시각(ms)을 반환한다.
 * 파싱 실패 시 null 반환.
 */
function decodeTokenExp(token: string): number | null {
  try {
    const payload = token.split('.')[1];
    if (!payload) return null;
    const decoded = JSON.parse(atob(payload.replace(/-/g, '+').replace(/_/g, '/')));
    if (typeof decoded.exp !== 'number') return null;
    return decoded.exp * 1000; // ms 단위
  } catch {
    return null;
  }
}

/**
 * 사용자 인증 상태 관리 훅.
 * - 마운트 시 localStorage 토큰 확인 및 서버 검증
 * - 401 응답 시 refresh_token 으로 자동 갱신
 * - 만료 1분 전 자동 갱신 타이머 설정
 */
export function useUser() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  // 자동 갱신 타이머 ref — 컴포넌트 언마운트 시 정리
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  /**
   * 자동 갱신 타이머를 설정한다.
   * 토큰 만료 1분 전에 갱신 시도.
   */
  const scheduleRefresh = useCallback((token: string) => {
    if (refreshTimerRef.current) {
      clearTimeout(refreshTimerRef.current);
    }
    const exp = decodeTokenExp(token);
    if (!exp) return;
    const now = Date.now();
    const delay = exp - now - 60_000; // 1분 전
    if (delay <= 0) return;
    refreshTimerRef.current = setTimeout(async () => {
      const storedRefresh = localStorage.getItem(REFRESH_TOKEN_KEY);
      if (!storedRefresh) return;
      try {
        const res = await fetch('/api/auth/user/refresh', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: storedRefresh }),
          cache: 'no-store',
        });
        if (!res.ok) {
          // 갱신 실패 시 로그아웃 처리
          _clearStorage();
          setUser(null);
          setAccessToken(null);
          return;
        }
        const data = await res.json();
        localStorage.setItem(ACCESS_TOKEN_KEY, data.access_token);
        setAccessToken(data.access_token);
        scheduleRefresh(data.access_token);
      } catch {
        // 네트워크 오류 시 조용히 무시
      }
    }, delay);
  }, []);

  /** localStorage 인증 데이터 삭제 */
  function _clearStorage() {
    localStorage.removeItem(ACCESS_TOKEN_KEY);
    localStorage.removeItem(REFRESH_TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  }

  // 마운트 시 토큰 확인 및 사용자 정보 로드
  useEffect(() => {
    const storedAccess = localStorage.getItem(ACCESS_TOKEN_KEY);
    const storedRefresh = localStorage.getItem(REFRESH_TOKEN_KEY);
    const storedUser = localStorage.getItem(USER_KEY);

    if (!storedAccess) {
      setLoading(false);
      return;
    }

    // 캐시된 유저 정보로 즉시 UI 렌더링
    if (storedUser) {
      try {
        setUser(JSON.parse(storedUser));
        setAccessToken(storedAccess);
      } catch {
        // JSON 파싱 실패 시 무시
      }
    }

    // 서버에서 현재 사용자 정보 검증
    fetch('/api/auth/user/me', {
      headers: { Authorization: `Bearer ${storedAccess}` },
      cache: 'no-store',
    })
      .then(async (res) => {
        if (res.ok) {
          const userData: User = await res.json();
          localStorage.setItem(USER_KEY, JSON.stringify(userData));
          setUser(userData);
          setAccessToken(storedAccess);
          scheduleRefresh(storedAccess);
          return;
        }
        // 401 — refresh_token 으로 갱신 시도
        if (res.status === 401 && storedRefresh) {
          const refreshRes = await fetch('/api/auth/user/refresh', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ refresh_token: storedRefresh }),
            cache: 'no-store',
          });
          if (refreshRes.ok) {
            const data = await refreshRes.json();
            localStorage.setItem(ACCESS_TOKEN_KEY, data.access_token);
            // 갱신 후 사용자 정보 재조회
            const meRes = await fetch('/api/auth/user/me', {
              headers: { Authorization: `Bearer ${data.access_token}` },
              cache: 'no-store',
            });
            if (meRes.ok) {
              const userData: User = await meRes.json();
              localStorage.setItem(USER_KEY, JSON.stringify(userData));
              setUser(userData);
              setAccessToken(data.access_token);
              scheduleRefresh(data.access_token);
              return;
            }
          }
        }
        // 갱신도 실패 — 로그아웃 처리
        _clearStorage();
        setUser(null);
        setAccessToken(null);
      })
      .catch(() => {
        // 네트워크 오류 시 캐시된 사용자 정보 유지 (오프라인 UX)
      })
      .finally(() => setLoading(false));

    return () => {
      if (refreshTimerRef.current) {
        clearTimeout(refreshTimerRef.current);
      }
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /**
   * 로그인: 이메일/비밀번호로 인증 후 토큰을 저장한다.
   */
  const login = useCallback(async (email: string, password: string): Promise<void> => {
    const res = await fetch('/api/auth/user/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
      cache: 'no-store',
    });
    if (!res.ok) {
      const errorData = await res.json().catch(() => ({}));
      throw new Error(errorData.detail ?? '로그인에 실패했습니다.');
    }
    const data: AuthTokens = await res.json();
    localStorage.setItem(ACCESS_TOKEN_KEY, data.access_token);
    localStorage.setItem(REFRESH_TOKEN_KEY, data.refresh_token);
    localStorage.setItem(USER_KEY, JSON.stringify(data.user));
    setUser(data.user);
    setAccessToken(data.access_token);
    scheduleRefresh(data.access_token);
  }, [scheduleRefresh]);

  /**
   * 로그아웃: 서버 세션 무효화 후 로컬 저장소 삭제.
   */
  const logout = useCallback(async (): Promise<void> => {
    const storedAccess = localStorage.getItem(ACCESS_TOKEN_KEY);
    const storedRefresh = localStorage.getItem(REFRESH_TOKEN_KEY);
    if (storedRefresh && storedAccess) {
      try {
        await fetch('/api/auth/user/logout', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${storedAccess}`,
          },
          body: JSON.stringify({ refresh_token: storedRefresh }),
          cache: 'no-store',
        });
      } catch {
        // 서버 오류여도 로컬 정리는 진행
      }
    }
    if (refreshTimerRef.current) {
      clearTimeout(refreshTimerRef.current);
    }
    _clearStorage();
    setUser(null);
    setAccessToken(null);
  }, []);

  return {
    user,
    loading,
    login,
    logout,
    isLoggedIn: !!user,
    accessToken,
  };
}

/**
 * API 호출에서 현재 액세스 토큰을 가져온다.
 * 서버 컴포넌트에서는 null 반환.
 */
export function getUserAccessToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem(ACCESS_TOKEN_KEY);
}
