'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { useAlertStore } from '@/stores/alertStore';
import { useNotificationStore } from '@/stores/notificationStore';
import type { MacroAlert, FundSignal } from '@/lib/types';

// WebSocket 메시지 타입 정의
interface WsMessage {
  type: 'macro_alert' | 'fund_signal' | 'new_articles';
  data: unknown;
}

interface UseWebSocketReturn {
  isConnected: boolean;
  lastMessage: WsMessage | null;
}

/**
 * WebSocket 연결 관리 훅
 * - 자동 재연결 (exponential backoff: 1s, 2s, 4s, 8s, max 30s)
 * - 토픽 구독: alerts, signals, news
 * - 수신 메시지를 Zustand 스토어에 반영
 * - WebSocket 불가 시 기존 폴링으로 폴백 (REQ-RT-006)
 */
export function useWebSocket(
  topics: string[] = ['alerts', 'signals', 'news'],
): UseWebSocketReturn {
  const [isConnected, setIsConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<WsMessage | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const retryCountRef = useRef(0);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);

  // Zustand 스토어 액션
  const addAlert = useAlertStore((s) => s.addAlert);
  const addNotification = useNotificationStore((s) => s.addNotification);

  /** WebSocket URL 구성 */
  const buildWsUrl = useCallback((): string => {
    // 개발 환경에서 직접 백엔드 연결 (Next.js rewrite는 WS 미지원)
    const envWsUrl = process.env.NEXT_PUBLIC_WS_URL;
    if (envWsUrl) {
      const base = envWsUrl.replace(/\/$/, '');
      return `${base}/ws?topics=${topics.join(',')}`;
    }

    // 개발 환경에서만 window.location 기반 자동 구성 (프로덕션은 NEXT_PUBLIC_WS_URL 필수)
    if (typeof window === 'undefined') return '';
    const host = window.location.hostname;
    if (host !== 'localhost' && host !== '127.0.0.1') return '';
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${proto}//${window.location.host}/ws?topics=${topics.join(',')}`;
  }, [topics]);

  /** 수신 메시지 처리 */
  const handleMessage = useCallback(
    (event: MessageEvent) => {
      try {
        const msg = JSON.parse(event.data as string) as WsMessage;
        setLastMessage(msg);

        switch (msg.type) {
          case 'macro_alert': {
            const alert = msg.data as MacroAlert;
            addAlert(alert);
            addNotification({
              type: 'alert',
              title: alert.level === 'critical' ? '[긴급] ' + alert.title : '[주의] ' + alert.title,
              message: alert.description?.split('\n')[0] ?? '',
            });
            break;
          }
          case 'fund_signal': {
            const signal = msg.data as FundSignal;
            const label =
              signal.signal === 'buy' ? '매수' : signal.signal === 'sell' ? '매도' : '홀드';
            addNotification({
              type: 'signal',
              title: `${signal.stock_name ?? '종목'} ${label} 시그널`,
              message: `신뢰도 ${Math.round(signal.confidence * 100)}%`,
            });
            break;
          }
          case 'new_articles': {
            const articles = msg.data as { count?: number };
            addNotification({
              type: 'news',
              title: '새 뉴스 도착',
              message: `${articles.count ?? 0}건의 새 기사가 수집되었습니다.`,
            });
            break;
          }
        }
      } catch {
        // JSON 파싱 실패 시 무시
      }
    },
    [addAlert, addNotification],
  );

  /** WebSocket 연결 시도 */
  const connect = useCallback(() => {
    if (!mountedRef.current) return;
    const url = buildWsUrl();
    if (!url) return;

    try {
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        if (!mountedRef.current) {
          ws.close();
          return;
        }
        setIsConnected(true);
        retryCountRef.current = 0; // 재연결 카운터 초기화
      };

      ws.onmessage = handleMessage;

      ws.onclose = () => {
        if (!mountedRef.current) return;
        setIsConnected(false);
        wsRef.current = null;
        scheduleReconnect();
      };

      ws.onerror = () => {
        // onclose가 자동 호출되므로 별도 처리 불필요
      };
    } catch {
      // WebSocket 생성자 에러 (브라우저 미지원 등)
      setIsConnected(false);
      scheduleReconnect();
    }
  }, [buildWsUrl, handleMessage]);

  /** Exponential backoff 재연결 스케줄링 */
  const scheduleReconnect = useCallback(() => {
    if (!mountedRef.current) return;

    // 1s, 2s, 4s, 8s, 16s, 30s (max)
    const delay = Math.min(1000 * Math.pow(2, retryCountRef.current), 30_000);
    retryCountRef.current += 1;

    retryTimerRef.current = setTimeout(() => {
      if (mountedRef.current) {
        connect();
      }
    }, delay);
  }, [connect]);

  useEffect(() => {
    mountedRef.current = true;
    connect();

    return () => {
      mountedRef.current = false;
      if (retryTimerRef.current) {
        clearTimeout(retryTimerRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [connect]);

  return { isConnected, lastMessage };
}
