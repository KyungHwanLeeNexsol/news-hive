'use client';

import { useWebSocket } from '@/lib/useWebSocket';
import NotificationToast from '@/components/NotificationToast';
import { AuthProvider } from '@/components/AuthProvider';

/**
 * 클라이언트 프로바이더 래퍼
 * - AuthProvider: 사용자 인증 상태 전역 제공
 * - WebSocket 연결 초기화 (alerts, signals, news 토픽 구독)
 * - 알림 토스트 렌더링
 */
export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <ProvidersInner>{children}</ProvidersInner>
    </AuthProvider>
  );
}

/** WebSocket 등 인증 컨텍스트 안에서 동작해야 하는 내부 프로바이더 */
function ProvidersInner({ children }: { children: React.ReactNode }) {
  useWebSocket(['alerts', 'signals', 'news']);

  return (
    <>
      {children}
      <NotificationToast />
    </>
  );
}
