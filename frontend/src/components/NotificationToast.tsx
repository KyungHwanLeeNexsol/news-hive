'use client';

import { useEffect, useRef } from 'react';
import { useNotificationStore, type Notification } from '@/stores/notificationStore';

/** 알림 타입별 스타일 매핑 */
const STYLE_MAP: Record<Notification['type'], { bg: string; border: string; icon: string }> = {
  alert: {
    bg: 'bg-[#fde8e8]',
    border: 'border-[#e12343]',
    icon: '\u26A0', // 경고 아이콘
  },
  signal: {
    bg: 'bg-[#e8f0fe]',
    border: 'border-[#4285f4]',
    icon: '\u26A1', // 번개 아이콘
  },
  news: {
    bg: 'bg-[#e6f7ed]',
    border: 'border-[#34a853]',
    icon: '\u{1F4F0}', // 신문 아이콘
  },
};

/** 개별 토스트 아이템 (5초 후 자동 제거) */
function ToastItem({ notification }: { notification: Notification }) {
  const removeNotification = useNotificationStore((s) => s.removeNotification);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    timerRef.current = setTimeout(() => {
      removeNotification(notification.id);
    }, 5_000);

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [notification.id, removeNotification]);

  const style = STYLE_MAP[notification.type];

  return (
    <div
      className={`
        ${style.bg} border ${style.border}
        rounded-lg shadow-lg px-4 py-3 min-w-[300px] max-w-[380px]
        animate-[slideIn_0.3s_ease-out]
      `}
      role="alert"
    >
      <div className="flex items-start gap-2">
        <span className="text-[16px] shrink-0 mt-0.5" aria-hidden="true">
          {style.icon}
        </span>
        <div className="flex-1 min-w-0">
          <p className="text-[13px] font-semibold truncate">{notification.title}</p>
          {notification.message && (
            <p className="text-[12px] opacity-70 mt-0.5 line-clamp-2">
              {notification.message}
            </p>
          )}
        </div>
        <button
          onClick={() => removeNotification(notification.id)}
          className="text-[14px] opacity-40 hover:opacity-100 shrink-0 leading-none"
          aria-label="닫기"
        >
          &times;
        </button>
      </div>
    </div>
  );
}

/** 알림 토스트 컨테이너 - 화면 우하단 고정 */
export default function NotificationToast() {
  const notifications = useNotificationStore((s) => s.notifications);

  // 최대 3개만 화면에 표시
  const visible = notifications.slice(0, 3);

  if (visible.length === 0) return null;

  return (
    <div
      className="fixed bottom-4 right-4 z-50 flex flex-col-reverse gap-2"
      aria-live="polite"
      aria-label="알림 영역"
    >
      {visible.map((n) => (
        <ToastItem key={n.id} notification={n} />
      ))}
    </div>
  );
}
