'use client';

import { useEffect, useState } from 'react';
import { fetchAlerts, dismissAlert } from '@/lib/api';
import type { MacroAlert } from '@/lib/types';

export default function MacroAlertBanner() {
  const [alerts, setAlerts] = useState<MacroAlert[]>([]);
  const [dismissed, setDismissed] = useState<Set<number>>(new Set());

  useEffect(() => {
    fetchAlerts(true).then(setAlerts).catch(() => {});
    // 1분마다 새 알림 확인
    const interval = setInterval(() => {
      fetchAlerts(true).then(setAlerts).catch(() => {});
    }, 60_000);
    return () => clearInterval(interval);
  }, []);

  const visible = alerts.filter((a) => !dismissed.has(a.id));
  if (visible.length === 0) return null;

  function handleDismiss(id: number) {
    setDismissed((prev) => new Set(prev).add(id));
    dismissAlert(id).catch(() => {});
  }

  return (
    <div className="space-y-1 mb-3">
      {visible.map((alert) => (
        <div
          key={alert.id}
          className={`flex items-center gap-3 px-4 py-2.5 rounded-md text-[13px] ${
            alert.level === 'critical'
              ? 'bg-[#fde8e8] border border-[#e12343] text-[#c41a1a]'
              : 'bg-[#fff8e6] border border-[#f5a623] text-[#8a6d00]'
          }`}
        >
          <span className="font-bold text-[14px] shrink-0">
            {alert.level === 'critical' ? '긴급' : '주의'}
          </span>
          <span className="flex-1 min-w-0">
            <span className="font-semibold">{alert.title}</span>
            {alert.description && (
              <span className="text-[12px] ml-2 opacity-80">
                {alert.description.split('\n')[0]}
              </span>
            )}
          </span>
          <span className="text-[11px] opacity-60 shrink-0">
            {new Date(alert.created_at).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })}
          </span>
          <button
            onClick={() => handleDismiss(alert.id)}
            className="text-[16px] opacity-50 hover:opacity-100 shrink-0 leading-none"
            title="닫기"
          >
            &times;
          </button>
        </div>
      ))}
    </div>
  );
}
