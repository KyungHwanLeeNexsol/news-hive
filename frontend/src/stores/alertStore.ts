import { create } from 'zustand';
import type { MacroAlert } from '@/lib/types';

// 매크로 알림 상태 관리 스토어
interface AlertState {
  alerts: MacroAlert[];
  /** 사용자가 닫은(dismiss) 알림 ID 목록 */
  dismissedIds: Set<number>;
  /** 읽지 않은 알림 수 (dismissed 제외) */
  unreadCount: number;

  setAlerts: (alerts: MacroAlert[]) => void;
  addAlert: (alert: MacroAlert) => void;
  dismissAlert: (id: number) => void;
  clearAll: () => void;
}

/** 읽지 않은 알림 수 계산 헬퍼 */
function calcUnread(alerts: MacroAlert[], dismissedIds: Set<number>): number {
  return alerts.filter((a) => a.is_active && !dismissedIds.has(a.id)).length;
}

export const useAlertStore = create<AlertState>((set, get) => ({
  alerts: [],
  dismissedIds: new Set(),
  unreadCount: 0,

  setAlerts: (alerts) =>
    set((state) => ({
      alerts,
      unreadCount: calcUnread(alerts, state.dismissedIds),
    })),

  addAlert: (alert) =>
    set((state) => {
      // 중복 방지
      const exists = state.alerts.some((a) => a.id === alert.id);
      if (exists) return state;

      const next = [alert, ...state.alerts];
      return {
        alerts: next,
        unreadCount: calcUnread(next, state.dismissedIds),
      };
    }),

  dismissAlert: (id) =>
    set((state) => {
      const next = new Set(state.dismissedIds);
      next.add(id);
      return {
        dismissedIds: next,
        unreadCount: calcUnread(state.alerts, next),
      };
    }),

  clearAll: () =>
    set({ alerts: [], dismissedIds: new Set(), unreadCount: 0 }),
}));
