'use client';

import { useWebSocket } from '@/lib/useWebSocket';
import NotificationToast from '@/components/NotificationToast';

/**
 * 클라이언트 프로바이더 래퍼
 * - WebSocket 연결 초기화 (alerts, signals, news 토픽 구독)
 * - 알림 토스트 렌더링
 */
export function Providers({ children }: { children: React.ReactNode }) {
  useWebSocket(['alerts', 'signals', 'news']);

  return (
    <>
      {children}
      <NotificationToast />
    </>
  );
}
