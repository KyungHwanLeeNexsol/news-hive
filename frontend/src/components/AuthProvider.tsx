'use client';

import { createContext, useContext } from 'react';
import { useUser } from '@/lib/useUser';

// @MX:ANCHOR: 앱 전체 인증 상태 컨텍스트 — 여러 컴포넌트에서 useAuth()로 참조
// @MX:REASON: Header, 보호된 페이지 등 다수 컴포넌트가 이 컨텍스트에 의존
export const UserContext = createContext<ReturnType<typeof useUser> | null>(null);

/**
 * 앱 최상위에 배치하는 인증 프로바이더.
 * useUser 훅의 상태를 Context로 하위 컴포넌트에 제공한다.
 */
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const auth = useUser();
  return <UserContext.Provider value={auth}>{children}</UserContext.Provider>;
}

/**
 * 인증 컨텍스트 접근 훅.
 * AuthProvider 외부에서 사용 시 에러를 던진다.
 */
export function useAuth(): ReturnType<typeof useUser> {
  const ctx = useContext(UserContext);
  if (!ctx) {
    throw new Error('useAuth는 AuthProvider 내부에서만 사용할 수 있습니다.');
  }
  return ctx;
}
