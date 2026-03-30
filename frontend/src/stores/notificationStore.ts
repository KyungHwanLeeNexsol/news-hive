import { create } from 'zustand';

// 실시간 알림 토스트 관리 스토어
export interface Notification {
  id: string;
  type: 'alert' | 'signal' | 'news';
  title: string;
  message: string;
  timestamp: number;
}

interface NotificationState {
  notifications: Notification[];
  addNotification: (n: Omit<Notification, 'id' | 'timestamp'>) => void;
  removeNotification: (id: string) => void;
}

/** 고유 ID 생성 */
function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

/** 동시에 보여줄 수 있는 최대 알림 수 */
const MAX_VISIBLE = 5;

export const useNotificationStore = create<NotificationState>((set) => ({
  notifications: [],

  addNotification: (n) =>
    set((state) => {
      const notification: Notification = {
        ...n,
        id: generateId(),
        timestamp: Date.now(),
      };
      // 최대 개수 초과 시 가장 오래된 것부터 제거
      const next = [notification, ...state.notifications].slice(0, MAX_VISIBLE);
      return { notifications: next };
    }),

  removeNotification: (id) =>
    set((state) => ({
      notifications: state.notifications.filter((n) => n.id !== id),
    })),
}));
