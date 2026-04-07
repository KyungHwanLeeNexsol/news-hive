'use client';

import { useEffect, useRef, useState } from 'react';

interface ExchangeRate {
  pair: string;
  label: string;
  rate: number;
  change_pct: number | null;
}

interface InterestRate {
  country: string;
  code: string;
  central_bank: string;
  rate: number;
  rate_label: string;
  next_meeting: string | null;
  dday: number | null;
}

interface MacroRatesData {
  exchange_rates: ExchangeRate[];
  interest_rates: InterestRate[];
  updated_at: string;
}

const FLAG: Record<string, string> = {
  US: '🇺🇸',
  JP: '🇯🇵',
  KR: '🇰🇷',
};

function DdayBadge({ dday }: { dday: number | null }) {
  if (dday === null) return null;
  if (dday === 0) {
    return (
      <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-[#e12343] text-white">
        D-Day
      </span>
    );
  }
  const urgent = dday <= 7;
  return (
    <span
      className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
        urgent ? 'bg-[#fff3e0] text-[#e65100]' : 'bg-[#f0f0f0] text-[#666]'
      }`}
    >
      D-{dday}
    </span>
  );
}

function formatMeetingDate(dateStr: string | null): string {
  if (!dateStr) return '-';
  const d = new Date(dateStr);
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

function ChangePct({ value }: { value: number | null }) {
  if (value === null) return <span className="text-[#aaa]">-</span>;
  const color = value > 0 ? '#e12343' : value < 0 ? '#1261c4' : '#888';
  const sign = value > 0 ? '+' : '';
  return (
    <span style={{ color }} className="text-[11px] font-medium">
      {sign}{value.toFixed(2)}%
    </span>
  );
}

export default function GlobalMacroWidget() {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<MacroRatesData | null>(null);
  const [loading, setLoading] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);

  const fetchData = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/macro/rates');
      if (res.ok) {
        const json: MacroRatesData = await res.json();
        setData(json);
      }
    } catch {
      // 조용히 처리
    } finally {
      setLoading(false);
    }
  };

  // 패널 열 때 데이터 로드
  useEffect(() => {
    if (open && !data) {
      fetchData();
    }
  }, [open, data]);

  // 10분마다 자동 갱신 (패널 열려있을 때만)
  useEffect(() => {
    if (!open) return;
    const interval = setInterval(fetchData, 600_000);
    return () => clearInterval(interval);
  }, [open]);

  // 패널 외부 클릭 시 닫기
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  return (
    <div ref={panelRef} className="fixed bottom-5 right-5 z-50 flex flex-col items-end gap-2">
      {/* 팝업 패널 */}
      {open && (
        <div className="w-[300px] bg-white rounded-xl shadow-2xl border border-[#e5e5e5] overflow-hidden">
          {/* 헤더 */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-[#f0f0f0] bg-[#fafafa]">
            <span className="text-[13px] font-bold text-[#333]">글로벌 매크로</span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={fetchData}
                disabled={loading}
                className="text-[11px] text-[#1261c4] hover:underline disabled:opacity-40"
              >
                {loading ? '로딩...' : '새로고침'}
              </button>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="text-[#aaa] hover:text-[#333] text-[18px] leading-none"
              >
                ×
              </button>
            </div>
          </div>

          {loading && !data ? (
            <div className="px-4 py-6 text-center text-[12px] text-[#aaa]">데이터 로딩 중...</div>
          ) : data ? (
            <div className="divide-y divide-[#f5f5f5]">
              {/* 환율 섹션 */}
              <div className="px-4 py-3">
                <p className="text-[11px] font-semibold text-[#888] uppercase tracking-wide mb-2">환율</p>
                {data.exchange_rates.length === 0 ? (
                  <p className="text-[12px] text-[#bbb]">데이터 없음</p>
                ) : (
                  <div className="space-y-2">
                    {data.exchange_rates.map((r) => (
                      <div key={r.pair} className="flex items-center justify-between">
                        <span className="text-[12px] text-[#555]">
                          <span className="font-medium text-[#333]">{r.label}</span>
                          <span className="text-[#aaa] ml-1 text-[10px]">{r.pair}</span>
                        </span>
                        <div className="flex items-center gap-2">
                          <span className="text-[13px] font-semibold text-[#222]">
                            {r.rate.toLocaleString('ko-KR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}원
                          </span>
                          <ChangePct value={r.change_pct} />
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* 기준금리 섹션 */}
              <div className="px-4 py-3">
                <p className="text-[11px] font-semibold text-[#888] uppercase tracking-wide mb-2">기준금리</p>
                <div className="space-y-2.5">
                  {data.interest_rates.map((r) => (
                    <div key={r.code} className="flex items-center justify-between">
                      <div className="flex items-center gap-1.5">
                        <span className="text-[14px]">{FLAG[r.code] ?? ''}</span>
                        <div>
                          <p className="text-[12px] font-medium text-[#333] leading-tight">{r.country}</p>
                          <p className="text-[10px] text-[#aaa] leading-tight">{r.central_bank}</p>
                        </div>
                      </div>
                      <div className="flex items-center gap-2 text-right">
                        <span className="text-[13px] font-bold text-[#222]">{r.rate_label}</span>
                        <div className="flex flex-col items-end gap-0.5">
                          <DdayBadge dday={r.dday} />
                          {r.next_meeting && (
                            <span className="text-[10px] text-[#bbb]">{formatMeetingDate(r.next_meeting)}</span>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* 업데이트 시각 */}
              <div className="px-4 py-2 bg-[#fafafa]">
                <p className="text-[10px] text-[#bbb] text-right">
                  환율 {new Date(data.updated_at).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })} 기준
                </p>
              </div>
            </div>
          ) : (
            <div className="px-4 py-6 text-center text-[12px] text-[#aaa]">데이터를 불러올 수 없습니다.</div>
          )}
        </div>
      )}

      {/* 플로팅 버튼 */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        title="글로벌 매크로 지표"
        className={`w-12 h-12 rounded-full shadow-lg flex items-center justify-center text-white text-[18px] transition-all ${
          open ? 'bg-[#333] rotate-45' : 'bg-[#1261c4] hover:bg-[#0e4f9e]'
        }`}
      >
        {open ? (
          // X 아이콘 (회전 효과)
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <path d="M2 2L14 14M14 2L2 14" stroke="white" strokeWidth="2" strokeLinecap="round"/>
          </svg>
        ) : (
          // 달러/지구 아이콘
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <circle cx="12" cy="12" r="9" stroke="white" strokeWidth="1.8"/>
            <path d="M12 3C12 3 8 7 8 12C8 17 12 21 12 21" stroke="white" strokeWidth="1.5" strokeLinecap="round"/>
            <path d="M12 3C12 3 16 7 16 12C16 17 12 21 12 21" stroke="white" strokeWidth="1.5" strokeLinecap="round"/>
            <path d="M3 12H21" stroke="white" strokeWidth="1.5" strokeLinecap="round"/>
            <path d="M4 8H20M4 16H20" stroke="white" strokeWidth="1.2" strokeLinecap="round"/>
          </svg>
        )}
      </button>
    </div>
  );
}
