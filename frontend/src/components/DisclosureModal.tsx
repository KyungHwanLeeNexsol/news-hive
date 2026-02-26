'use client';

import { useEffect, useState, useCallback } from 'react';
import type { DisclosureItem } from '@/lib/types';
import { fetchDisclosureSummary } from '@/lib/api';

interface Props {
  disclosure: DisclosureItem;
  onClose: () => void;
}

export default function DisclosureModal({ disclosure, onClose }: Props) {
  const [summary, setSummary] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [iframeError, setIframeError] = useState(false);

  const formattedDate = disclosure.rcept_dt
    ? `${disclosure.rcept_dt.slice(0, 4)}.${disclosure.rcept_dt.slice(4, 6)}.${disclosure.rcept_dt.slice(6, 8)}`
    : '';

  // Fetch AI summary on mount
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(false);

    fetchDisclosureSummary(disclosure.id)
      .then((data) => {
        if (!cancelled) {
          setSummary(data.ai_summary);
          setLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setError(true);
          setLoading(false);
        }
      });

    return () => { cancelled = true; };
  }, [disclosure.id]);

  // ESC key to close
  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if (e.key === 'Escape') onClose();
  }, [onClose]);

  useEffect(() => {
    document.addEventListener('keydown', handleKeyDown);
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = '';
    };
  }, [handleKeyDown]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ backgroundColor: 'rgba(0,0,0,0.5)', backdropFilter: 'blur(2px)' }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div
        className="bg-white rounded-lg shadow-xl flex flex-col"
        style={{ width: '90vw', maxWidth: '1200px', height: '80vh' }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-[#e5e5e5]">
          <div className="flex items-center gap-3 min-w-0">
            <h2 className="text-[15px] font-semibold text-[#333] truncate">
              {disclosure.report_name}
            </h2>
            {disclosure.report_type && (
              <span className="badge badge-neutral shrink-0">{disclosure.report_type}</span>
            )}
            <span className="text-[12px] text-[#999] shrink-0">{formattedDate}</span>
          </div>
          <button
            onClick={onClose}
            className="text-[#999] hover:text-[#333] text-xl leading-none px-2 shrink-0"
          >
            ✕
          </button>
        </div>

        {/* Body — 50/50 split */}
        <div className="flex flex-1 min-h-0">
          {/* Left: DART iframe */}
          <div className="w-1/2 border-r border-[#e5e5e5] flex flex-col">
            {!iframeError ? (
              <iframe
                src={disclosure.url}
                className="flex-1 w-full"
                title="DART 원문"
                onError={() => setIframeError(true)}
                sandbox="allow-same-origin allow-scripts allow-popups"
              />
            ) : (
              <div className="flex-1 flex items-center justify-center text-[#999]">
                <div className="text-center">
                  <p className="mb-3 text-[14px]">DART 원문을 표시할 수 없습니다.</p>
                  <a
                    href={disclosure.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-[#1261c4] hover:underline text-[13px]"
                  >
                    새 탭에서 열기 →
                  </a>
                </div>
              </div>
            )}
          </div>

          {/* Right: AI Summary */}
          <div className="w-1/2 flex flex-col">
            <div className="px-5 py-3 border-b border-[#e5e5e5] bg-[#f8f9fa]">
              <h3 className="text-[13px] font-semibold text-[#333]">
                AI 공시 요약
              </h3>
              <p className="text-[11px] text-[#999] mt-0.5">
                AI가 분석한 공시 내용 요약입니다
              </p>
            </div>
            <div className="flex-1 px-5 py-4 overflow-y-auto">
              {loading ? (
                <div className="flex flex-col items-center justify-center h-full gap-3">
                  <div className="w-6 h-6 border-2 border-[#1261c4] border-t-transparent rounded-full animate-spin" />
                  <p className="text-[13px] text-[#999]">AI 요약을 생성하고 있습니다...</p>
                </div>
              ) : error ? (
                <div className="flex items-center justify-center h-full">
                  <p className="text-[13px] text-[#999]">요약 생성에 실패했습니다.</p>
                </div>
              ) : summary ? (
                <p className="text-[14px] text-[#333] leading-7 whitespace-pre-wrap">{summary}</p>
              ) : (
                <div className="flex items-center justify-center h-full">
                  <p className="text-[13px] text-[#999]">요약을 생성할 수 없습니다.</p>
                </div>
              )}
            </div>

            {/* Footer link */}
            <div className="px-5 py-3 border-t border-[#e5e5e5] text-center">
              <a
                href={disclosure.url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-[12px] text-[#1261c4] hover:underline"
              >
                DART 원문 새 탭에서 열기 →
              </a>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
