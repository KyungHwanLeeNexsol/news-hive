'use client';

import { useEffect, useState, useCallback } from 'react';
import Link from 'next/link';
import {
  fetchFundSignals,
  fetchDailyBriefing,
  generateDailyBriefing,
  analyzeStock,
  analyzePortfolio,
  fetchLatestPortfolioReport,
  fetchStocks,
  fetchAccuracyStats,
  verifySignals,
} from '@/lib/api';
import type { FundSignal, DailyBriefing, PortfolioReport, StockListItem, AccuracyStats } from '@/lib/types';
import { useWatchlist } from '@/lib/watchlist';
import { useAdmin } from '@/lib/useAdmin';

type Tab = 'briefing' | 'signals' | 'accuracy' | 'portfolio';

function formatDateTime(dateStr: string): string {
  const d = new Date(dateStr);
  return d.toLocaleDateString('ko-KR', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatNumber(n: number | null | undefined): string {
  if (n == null) return '-';
  return n.toLocaleString('ko-KR');
}

function SignalBadge({ signal, confidence }: { signal: string; confidence: number }) {
  const config = {
    buy: { label: '\uB9E4\uC218', bg: 'bg-[#ffebee]', text: 'text-[#e12343]', border: 'border-[#e12343]' },
    sell: { label: '\uB9E4\uB3C4', bg: 'bg-[#e3f2fd]', text: 'text-[#1261c4]', border: 'border-[#1261c4]' },
    hold: { label: '\uAD00\uB9DD', bg: 'bg-[#f5f5f5]', text: 'text-[#666]', border: 'border-[#999]' },
  }[signal] || { label: signal, bg: 'bg-[#f5f5f5]', text: 'text-[#666]', border: 'border-[#999]' };

  return (
    <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded border text-[13px] font-bold ${config.bg} ${config.text} ${config.border}`}>
      {config.label}
      <span className="text-[11px] font-normal opacity-70">
        {Math.round(confidence * 100)}%
      </span>
    </span>
  );
}

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color = pct >= 70 ? '#e12343' : pct >= 50 ? '#ffa723' : '#999';
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-[#eee] rounded-full overflow-hidden">
        <div className="h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: color }} />
      </div>
      <span className="text-[11px] text-[#999] w-8 text-right">{pct}%</span>
    </div>
  );
}

function VerificationBadge({ signal }: { signal: FundSignal }) {
  if (signal.verified_at && signal.is_correct !== null) {
    return (
      <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${
        signal.is_correct
          ? 'bg-[#e8f5e9] text-[#2e7d32]'
          : 'bg-[#fce4ec] text-[#c62828]'
      }`}>
        {signal.is_correct ? '\uC801\uC911' : '\uBD88\uC801\uC911'}
        {signal.return_pct != null && ` ${signal.return_pct > 0 ? '+' : ''}${signal.return_pct}%`}
      </span>
    );
  }
  if (signal.price_at_signal) {
    const days = signal.price_after_5d ? 5 : signal.price_after_3d ? 3 : signal.price_after_1d ? 1 : 0;
    return (
      <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-[#fff3e0] text-[#e65100] font-medium">
        \uAC80\uC99D\uC911 {days > 0 ? `(${days}\uC77C)` : ''}
      </span>
    );
  }
  return null;
}

// ── Login Gate ──
function AdminLogin({ onLogin }: { onLogin: (pw: string) => Promise<boolean> }) {
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setLoading(true);
    const ok = await onLogin(password);
    if (!ok) setError('\uBE44\uBC00\uBC88\uD638\uAC00 \uC77C\uCE58\uD558\uC9C0 \uC54A\uC2B5\uB2C8\uB2E4.');
    setLoading(false);
  }

  return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <div className="section-box p-8 w-full max-w-sm">
        <div className="text-center mb-6">
          <div className="text-[32px] mb-2">{'\u{1F512}'}</div>
          <h2 className="text-[16px] font-bold text-[#333]">AI Fund Manager</h2>
          <p className="text-[12px] text-[#999] mt-1">\uAD00\uB9AC\uC790 \uB85C\uADF8\uC778\uC774 \uD544\uC694\uD569\uB2C8\uB2E4</p>
        </div>
        <form onSubmit={handleSubmit}>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="\uBE44\uBC00\uBC88\uD638"
            className="w-full px-3 py-2.5 border border-[#ddd] rounded text-[13px] mb-3 focus:outline-none focus:border-[#1261c4]"
            autoFocus
          />
          {error && <p className="text-[12px] text-[#e12343] mb-2">{error}</p>}
          <button
            type="submit"
            disabled={loading || !password}
            className="w-full py-2.5 bg-[#1261c4] text-white text-[13px] font-medium rounded hover:bg-[#0d4e9e] disabled:bg-[#999]"
          >
            {loading ? '\uB85C\uADF8\uC778 \uC911...' : '\uB85C\uADF8\uC778'}
          </button>
        </form>
      </div>
    </div>
  );
}

// ── Briefing Tab ──
function BriefingTab() {
  const [briefing, setBriefing] = useState<DailyBriefing | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);

  useEffect(() => {
    fetchDailyBriefing().then(setBriefing).catch(() => {}).finally(() => setLoading(false));
  }, []);

  async function handleGenerate(regenerate = false) {
    setGenerating(true);
    try {
      const b = await generateDailyBriefing(regenerate);
      setBriefing(b);
    } catch {
      alert('\uBE0C\uB9AC\uD551 \uC0DD\uC131\uC5D0 \uC2E4\uD328\uD588\uC2B5\uB2C8\uB2E4. AI API \uD0A4\uB97C \uD655\uC778\uD558\uC138\uC694.');
    } finally {
      setGenerating(false);
    }
  }

  if (loading) {
    return (
      <div className="space-y-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="section-box p-4">
            <div className="skeleton skeleton-text mb-2" style={{ width: '30%' }} />
            <div className="skeleton skeleton-text mb-1" style={{ width: '90%' }} />
            <div className="skeleton skeleton-text mb-1" style={{ width: '80%' }} />
            <div className="skeleton skeleton-text" style={{ width: '70%' }} />
          </div>
        ))}
      </div>
    );
  }

  if (!briefing) {
    return (
      <div className="section-box p-8 text-center">
        <div className="text-[40px] mb-3">&#x1F4CA;</div>
        <p className="text-[15px] text-[#333] font-medium mb-1">\uC624\uB298\uC758 AI \uBE0C\uB9AC\uD551\uC774 \uC544\uC9C1 \uC5C6\uC2B5\uB2C8\uB2E4</p>
        <p className="text-[13px] text-[#999] mb-4">
          AI\uAC00 \uCD5C\uADFC \uB274\uC2A4, \uACF5\uC2DC, \uB9E4\uD06C\uB85C \uB370\uC774\uD130\uB97C \uC885\uD569 \uBD84\uC11D\uD558\uC5EC<br />
          \uC804\uBB38 \uD380\uB4DC\uB9E4\uB2C8\uC800 \uC218\uC900\uC758 \uC2DC\uC7A5 \uBE0C\uB9AC\uD551\uC744 \uC0DD\uC131\uD569\uB2C8\uB2E4.
        </p>
        <button
          onClick={() => handleGenerate()}
          disabled={generating}
          className="px-5 py-2 bg-[#1261c4] text-white text-[13px] font-medium rounded hover:bg-[#0d4e9e] disabled:bg-[#999]"
        >
          {generating ? 'AI \uBD84\uC11D \uC911...' : '\uC624\uB298\uC758 \uBE0C\uB9AC\uD551 \uC0DD\uC131'}
        </button>
      </div>
    );
  }

  interface SectorItem { sector: string; sentiment?: string; analysis: string }
  interface StockItem { stock: string; reason: string }

  function tryParseJson<T>(value: string | null | undefined): T[] | null {
    if (!value) return null;
    try {
      const parsed = JSON.parse(value);
      if (Array.isArray(parsed)) return parsed as T[];
    } catch {
      // not JSON
    }
    return null;
  }

  const sectorItems = tryParseJson<SectorItem>(briefing.sector_highlights);
  const stockItems = tryParseJson<StockItem>(briefing.stock_picks);

  const sentimentColor = (s: string) => {
    if (s === 'positive') return { bg: 'bg-[#e8f5e9]', text: 'text-[#2e7d32]', label: '\uAE0D\uC815' };
    if (s === 'negative') return { bg: 'bg-[#fce4ec]', text: 'text-[#c62828]', label: '\uBD80\uC815' };
    return { bg: 'bg-[#f5f5f5]', text: 'text-[#616161]', label: '\uC911\uB9BD' };
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <div>
          <span className="text-[13px] text-[#999]">
            {briefing.briefing_date} \uBE0C\uB9AC\uD551
          </span>
        </div>
        <button
          onClick={() => handleGenerate(true)}
          disabled={generating}
          className="text-[12px] text-[#1261c4] hover:underline disabled:text-[#999]"
        >
          {generating ? '\uC0DD\uC131 \uC911...' : '\uB2E4\uC2DC \uC0DD\uC131'}
        </button>
      </div>
      <div className="space-y-3">
        {briefing.market_overview && (
          <div className="section-box">
            <div className="section-title"><span>{'\u{1F30D}'} \uC2DC\uC7A5 \uC804\uB9DD</span></div>
            <div className="p-4 text-[13px] text-[#333] leading-[1.8]">
              {briefing.market_overview}
            </div>
          </div>
        )}
        {briefing.sector_highlights && (
          <div className="section-box">
            <div className="section-title"><span>{'\u{1F3AF}'} \uC8FC\uBAA9 \uC139\uD130</span></div>
            <div className="p-4">
              {sectorItems ? (
                <div className="space-y-2.5">
                  {sectorItems.map((item, i) => {
                    const sc = sentimentColor(item.sentiment || 'neutral');
                    return (
                      <div key={i} className="border border-[#eee] rounded-lg p-3">
                        <div className="flex items-center gap-2 mb-1.5">
                          <span className="text-[13px] font-semibold text-[#222]">{item.sector}</span>
                          <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${sc.bg} ${sc.text}`}>
                            {sc.label}
                          </span>
                        </div>
                        <p className="text-[12.5px] text-[#555] leading-[1.7]">{item.analysis}</p>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="text-[13px] text-[#333] leading-[1.8]">{briefing.sector_highlights}</div>
              )}
            </div>
          </div>
        )}
        {briefing.stock_picks && (
          <div className="section-box">
            <div className="section-title"><span>{'\u{2B50}'} \uC624\uB298\uC758 \uD53D</span></div>
            <div className="p-4">
              {stockItems ? (
                <div className="space-y-2.5">
                  {stockItems.map((item, i) => (
                    <div key={i} className="border border-[#eee] rounded-lg p-3">
                      <div className="flex items-center gap-2 mb-1.5">
                        <span className="text-[14px] font-semibold text-[#1261c4]">{item.stock}</span>
                      </div>
                      <p className="text-[12.5px] text-[#555] leading-[1.7]">{item.reason}</p>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-[13px] text-[#333] leading-[1.8]">{briefing.stock_picks}</div>
              )}
            </div>
          </div>
        )}
        {briefing.risk_assessment && (
          <div className="section-box">
            <div className="section-title"><span>{'\u{26A0}\u{FE0F}'} \uB9AC\uC2A4\uD06C \uD3C9\uAC00</span></div>
            <div className="p-4 text-[13px] text-[#333] leading-[1.8]">
              {briefing.risk_assessment}
            </div>
          </div>
        )}
        {briefing.strategy && (
          <div className="section-box">
            <div className="section-title"><span>{'\u{1F4DD}'} \uD22C\uC790 \uC804\uB7B5</span></div>
            <div className="p-4 text-[13px] text-[#333] leading-[1.8]">
              {briefing.strategy}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Signals Tab ──
function SignalsTab() {
  const [signals, setSignals] = useState<FundSignal[]>([]);
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState<number | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);
  const { watchlist } = useWatchlist();
  const [watchedStocks, setWatchedStocks] = useState<StockListItem[]>([]);

  useEffect(() => {
    fetchFundSignals().then(setSignals).catch(() => {}).finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (watchlist.length === 0) {
      setWatchedStocks([]);
      return;
    }
    fetchStocks({ ids: watchlist.join(','), limit: watchlist.length })
      .then((r) => setWatchedStocks(r.stocks))
      .catch(() => {});
  }, [watchlist]);

  async function handleAnalyze(stockId: number) {
    setAnalyzing(stockId);
    try {
      const signal = await analyzeStock(stockId);
      setSignals((prev) => {
        const filtered = prev.filter((s) => s.stock_id !== stockId);
        return [signal, ...filtered];
      });
    } catch {
      alert('\uBD84\uC11D\uC5D0 \uC2E4\uD328\uD588\uC2B5\uB2C8\uB2E4.');
    } finally {
      setAnalyzing(null);
    }
  }

  if (loading) {
    return (
      <div className="section-box">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="p-4 border-b border-[#f0f0f0]">
            <div className="flex items-center gap-3">
              <div className="skeleton skeleton-badge" style={{ width: 60 }} />
              <div className="skeleton skeleton-text flex-1" />
            </div>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div>
      {watchedStocks.length > 0 && (
        <div className="section-box mb-3">
          <div className="section-title">
            <span>\uAD00\uC2EC\uC885\uBAA9 \uBD84\uC11D</span>
          </div>
          <div className="p-3 flex flex-wrap gap-2">
            {watchedStocks.map((stock) => (
              <button
                key={stock.id}
                onClick={() => handleAnalyze(stock.id)}
                disabled={analyzing === stock.id}
                className="px-3 py-1.5 text-[12px] border border-[#ddd] rounded hover:border-[#1261c4] hover:text-[#1261c4] disabled:text-[#999] disabled:border-[#eee] transition-colors"
              >
                {analyzing === stock.id ? '\uBD84\uC11D \uC911...' : stock.name}
              </button>
            ))}
          </div>
        </div>
      )}

      {signals.length === 0 ? (
        <div className="section-box p-8 text-center">
          <p className="text-[15px] text-[#333] font-medium mb-1">\uC0DD\uC131\uB41C \uD22C\uC790 \uC2DC\uADF8\uB110\uC774 \uC5C6\uC2B5\uB2C8\uB2E4</p>
          <p className="text-[13px] text-[#999]">
            \uC704 \uAD00\uC2EC\uC885\uBAA9\uC744 \uD074\uB9AD\uD558\uAC70\uB098, \uC885\uBAA9 \uC0C1\uC138 \uD398\uC774\uC9C0\uC5D0\uC11C AI \uBD84\uC11D\uC744 \uC694\uCCAD\uD558\uC138\uC694.
          </p>
        </div>
      ) : (
        <div className="section-box">
          <div className="section-title">
            <span>AI \uD22C\uC790 \uC2DC\uADF8\uB110</span>
            <span className="text-[12px] font-normal text-[#999]">{signals.length}\uAC74</span>
          </div>
          {signals.map((signal) => (
            <div key={signal.id} className="border-b border-[#f0f0f0] last:border-b-0">
              <div
                className="p-4 cursor-pointer hover:bg-[#f7f8fa] transition-colors"
                onClick={() => setExpanded(expanded === signal.id ? null : signal.id)}
              >
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <SignalBadge signal={signal.signal} confidence={signal.confidence} />
                    <Link
                      href={`/stocks/${signal.stock_id}`}
                      className="text-[14px] font-medium text-[#333] hover:text-[#1261c4]"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {signal.stock_name || `\uC885\uBAA9#${signal.stock_id}`}
                    </Link>
                    {signal.sector_name && (
                      <span className="badge badge-sector">{signal.sector_name}</span>
                    )}
                    <VerificationBadge signal={signal} />
                  </div>
                  <div className="flex items-center gap-3 text-[12px] text-[#999]">
                    {signal.target_price && (
                      <span>\uBAA9\uD45C\uAC00 {formatNumber(signal.target_price)}</span>
                    )}
                    {signal.stop_loss && (
                      <span>\uC190\uC808\uAC00 {formatNumber(signal.stop_loss)}</span>
                    )}
                    <span>{formatDateTime(signal.created_at)}</span>
                  </div>
                </div>
                <div className="mb-2">
                  <ConfidenceBar value={signal.confidence} />
                </div>
                <p className="text-[13px] text-[#555] leading-relaxed">
                  {signal.reasoning}
                </p>
              </div>
              {expanded === signal.id && (
                <div className="px-4 pb-4 space-y-3">
                  {/* Price tracking */}
                  {signal.price_at_signal && (
                    <div className="p-3 bg-[#fafafa] rounded border border-[#eee]">
                      <div className="text-[12px] font-bold text-[#333] mb-2">\uC8FC\uAC00 \uCD94\uC801</div>
                      <div className="grid grid-cols-4 gap-2 text-[12px]">
                        <div>
                          <span className="text-[#999]">\uC2DC\uADF8\uB110 \uC2DC\uC810</span>
                          <div className="font-medium">{formatNumber(signal.price_at_signal)}\uC6D0</div>
                        </div>
                        <div>
                          <span className="text-[#999]">1\uC77C \uD6C4</span>
                          <div className="font-medium">{signal.price_after_1d ? `${formatNumber(signal.price_after_1d)}\uC6D0` : '-'}</div>
                        </div>
                        <div>
                          <span className="text-[#999]">3\uC77C \uD6C4</span>
                          <div className="font-medium">{signal.price_after_3d ? `${formatNumber(signal.price_after_3d)}\uC6D0` : '-'}</div>
                        </div>
                        <div>
                          <span className="text-[#999]">5\uC77C \uD6C4</span>
                          <div className="font-medium">{signal.price_after_5d ? `${formatNumber(signal.price_after_5d)}\uC6D0` : '-'}</div>
                        </div>
                      </div>
                    </div>
                  )}
                  {signal.news_summary && (
                    <div className="p-3 bg-[#f7f8fa] rounded">
                      <div className="text-[12px] font-bold text-[#1261c4] mb-1">\uB274\uC2A4 \uBD84\uC11D</div>
                      <p className="text-[12px] text-[#555] leading-relaxed">{signal.news_summary}</p>
                    </div>
                  )}
                  {signal.financial_summary && (
                    <div className="p-3 bg-[#f7f8fa] rounded">
                      <div className="text-[12px] font-bold text-[#2e7d32] mb-1">\uC7AC\uBB34 \uBD84\uC11D</div>
                      <p className="text-[12px] text-[#555] leading-relaxed">{signal.financial_summary}</p>
                    </div>
                  )}
                  {signal.market_summary && (
                    <div className="p-3 bg-[#f7f8fa] rounded">
                      <div className="text-[12px] font-bold text-[#e65100] mb-1">\uAE30\uC220\uC801 \uBD84\uC11D</div>
                      <p className="text-[12px] text-[#555] leading-relaxed">{signal.market_summary}</p>
                    </div>
                  )}
                  <div className="flex justify-end">
                    <button
                      onClick={(e) => { e.stopPropagation(); handleAnalyze(signal.stock_id); }}
                      disabled={analyzing === signal.stock_id}
                      className="text-[12px] text-[#1261c4] hover:underline disabled:text-[#999]"
                    >
                      {analyzing === signal.stock_id ? '\uC7AC\uBD84\uC11D \uC911...' : '\uC7AC\uBD84\uC11D'}
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Accuracy Tab ──
function AccuracyTab() {
  const [stats, setStats] = useState<AccuracyStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [verifying, setVerifying] = useState(false);
  const [days, setDays] = useState(30);

  const load = useCallback((d: number) => {
    setLoading(true);
    fetchAccuracyStats(d).then(setStats).catch(() => {}).finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(days); }, [days, load]);

  async function handleVerify() {
    setVerifying(true);
    try {
      const result = await verifySignals();
      alert(`\uAC80\uC99D \uC644\uB8CC: ${result.verified}\uAC74 \uAC80\uC99D, ${result.updated}\uAC74 \uC5C5\uB370\uC774\uD2B8`);
      load(days);
    } catch {
      alert('\uAC80\uC99D\uC5D0 \uC2E4\uD328\uD588\uC2B5\uB2C8\uB2E4.');
    } finally {
      setVerifying(false);
    }
  }

  if (loading) {
    return (
      <div className="space-y-4">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="section-box p-4">
            <div className="skeleton skeleton-text mb-2" style={{ width: '40%' }} />
            <div className="skeleton skeleton-text" style={{ width: '60%' }} />
          </div>
        ))}
      </div>
    );
  }

  if (!stats || stats.total === 0) {
    return (
      <div className="section-box p-8 text-center">
        <div className="text-[40px] mb-3">{'\u{1F4CA}'}</div>
        <p className="text-[15px] text-[#333] font-medium mb-1">\uAC80\uC99D\uB41C \uC2DC\uADF8\uB110\uC774 \uC5C6\uC2B5\uB2C8\uB2E4</p>
        <p className="text-[13px] text-[#999] mb-4">
          \uC2DC\uADF8\uB110 \uBC1C\uD589 \uD6C4 5\uC77C\uC774 \uC9C0\uB098\uBA74 \uC790\uB3D9\uC73C\uB85C \uC801\uC911 \uC5EC\uBD80\uAC00 \uAC80\uC99D\uB429\uB2C8\uB2E4.<br/>
          \uC218\uB3D9 \uAC80\uC99D\uC744 \uD558\uB824\uBA74 \uC544\uB798 \uBC84\uD2BC\uC744 \uD074\uB9AD\uD558\uC138\uC694.
        </p>
        <button
          onClick={handleVerify}
          disabled={verifying}
          className="px-5 py-2 bg-[#1261c4] text-white text-[13px] font-medium rounded hover:bg-[#0d4e9e] disabled:bg-[#999]"
        >
          {verifying ? '\uAC80\uC99D \uC911...' : '\uC218\uB3D9 \uAC80\uC99D \uC2E4\uD589'}
        </button>
      </div>
    );
  }

  const confidenceLevels = [
    { key: 'high', label: '\uACE0\uC2E0\uB8B0 (70%+)', color: '#e12343' },
    { key: 'medium', label: '\uC911\uAC04 (40-70%)', color: '#ffa723' },
    { key: 'low', label: '\uC800\uC2E0\uB8B0 (<40%)', color: '#999' },
  ];

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          {[7, 14, 30, 60, 90].map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={`px-2.5 py-1 text-[12px] rounded ${
                days === d ? 'bg-[#1261c4] text-white' : 'bg-[#f0f0f0] text-[#666] hover:bg-[#e0e0e0]'
              }`}
            >
              {d}\uC77C
            </button>
          ))}
        </div>
        <button
          onClick={handleVerify}
          disabled={verifying}
          className="text-[12px] text-[#1261c4] hover:underline disabled:text-[#999]"
        >
          {verifying ? '\uAC80\uC99D \uC911...' : '\uC218\uB3D9 \uAC80\uC99D'}
        </button>
      </div>

      {/* Overview cards */}
      <div className="grid grid-cols-4 gap-3 mb-3">
        <div className="section-box p-4 text-center">
          <div className="text-[24px] font-bold text-[#1261c4]">{stats.accuracy}%</div>
          <div className="text-[11px] text-[#999] mt-1">\uC804\uCCB4 \uC801\uC911\uB960</div>
          <div className="text-[11px] text-[#666]">{stats.correct}/{stats.total}\uAC74</div>
        </div>
        <div className="section-box p-4 text-center">
          <div className="text-[24px] font-bold text-[#e12343]">{stats.buy_accuracy}%</div>
          <div className="text-[11px] text-[#999] mt-1">\uB9E4\uC218 \uC801\uC911\uB960</div>
        </div>
        <div className="section-box p-4 text-center">
          <div className="text-[24px] font-bold text-[#1261c4]">{stats.sell_accuracy}%</div>
          <div className="text-[11px] text-[#999] mt-1">\uB9E4\uB3C4 \uC801\uC911\uB960</div>
        </div>
        <div className="section-box p-4 text-center">
          <div className={`text-[24px] font-bold ${stats.avg_return >= 0 ? 'text-[#e12343]' : 'text-[#1261c4]'}`}>
            {stats.avg_return > 0 ? '+' : ''}{stats.avg_return}%
          </div>
          <div className="text-[11px] text-[#999] mt-1">\uD3C9\uADE0 \uC218\uC775\uB960</div>
        </div>
      </div>

      {/* Accuracy bar */}
      <div className="section-box mb-3">
        <div className="section-title"><span>{'\u{1F3AF}'} \uC801\uC911\uB960 \uBC14</span></div>
        <div className="p-4">
          <div className="h-6 bg-[#eee] rounded-full overflow-hidden flex">
            <div
              className="h-full bg-[#2e7d32] flex items-center justify-center text-[11px] text-white font-medium"
              style={{ width: `${stats.accuracy}%` }}
            >
              {stats.accuracy > 10 ? `${stats.accuracy}%` : ''}
            </div>
            <div
              className="h-full bg-[#e0e0e0] flex items-center justify-center text-[11px] text-[#666] font-medium"
              style={{ width: `${100 - stats.accuracy}%` }}
            >
              {100 - stats.accuracy > 10 ? `${(100 - stats.accuracy).toFixed(1)}%` : ''}
            </div>
          </div>
        </div>
      </div>

      {/* Confidence breakdown */}
      {Object.keys(stats.by_confidence).length > 0 && (
        <div className="section-box">
          <div className="section-title"><span>{'\u{1F4CA}'} \uC2E0\uB8B0\uB3C4\uBCC4 \uC801\uC911\uB960</span></div>
          <div className="p-4 space-y-3">
            {confidenceLevels.map(({ key, label, color }) => {
              const bucket = stats.by_confidence[key];
              if (!bucket) return null;
              return (
                <div key={key}>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[12px] text-[#333] font-medium">{label}</span>
                    <span className="text-[12px] text-[#666]">
                      {bucket.accuracy}% ({bucket.total}\uAC74)
                    </span>
                  </div>
                  <div className="h-2 bg-[#eee] rounded-full overflow-hidden">
                    <div
                      className="h-full rounded-full"
                      style={{ width: `${bucket.accuracy}%`, backgroundColor: color }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Portfolio Tab ──
function PortfolioTab() {
  const [report, setReport] = useState<PortfolioReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const { watchlist } = useWatchlist();

  useEffect(() => {
    fetchLatestPortfolioReport().then(setReport).catch(() => {}).finally(() => setLoading(false));
  }, []);

  async function handleAnalyze() {
    if (watchlist.length === 0) {
      alert('\uAD00\uC2EC\uC885\uBAA9\uC744 \uBA3C\uC800 \uB4F1\uB85D\uD574\uC8FC\uC138\uC694.');
      return;
    }
    setAnalyzing(true);
    try {
      const r = await analyzePortfolio(watchlist);
      setReport(r);
    } catch {
      alert('\uD3EC\uD2B8\uD3F4\uB9AC\uC624 \uBD84\uC11D\uC5D0 \uC2E4\uD328\uD588\uC2B5\uB2C8\uB2E4.');
    } finally {
      setAnalyzing(false);
    }
  }

  if (loading) {
    return (
      <div className="space-y-4">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="section-box p-4">
            <div className="skeleton skeleton-text mb-2" style={{ width: '30%' }} />
            <div className="skeleton skeleton-text mb-1" style={{ width: '90%' }} />
            <div className="skeleton skeleton-text" style={{ width: '70%' }} />
          </div>
        ))}
      </div>
    );
  }

  if (!report) {
    return (
      <div className="section-box p-8 text-center">
        <div className="text-[40px] mb-3">&#x1F4BC;</div>
        <p className="text-[15px] text-[#333] font-medium mb-1">\uD3EC\uD2B8\uD3F4\uB9AC\uC624 \uBD84\uC11D \uB9AC\uD3EC\uD2B8\uAC00 \uC5C6\uC2B5\uB2C8\uB2E4</p>
        <p className="text-[13px] text-[#999] mb-4">
          \uAD00\uC2EC\uC885\uBAA9\uC744 \uAE30\uBC18\uC73C\uB85C AI\uAC00 \uD3EC\uD2B8\uD3F4\uB9AC\uC624\uB97C \uC885\uD569 \uBD84\uC11D\uD569\uB2C8\uB2E4.<br />
          \uC139\uD130 \uBD84\uC0B0\uB3C4, \uB9AC\uC2A4\uD06C, \uB9AC\uBC38\uB7F0\uC2F1 \uC804\uB7B5\uC744 \uC81C\uC548\uD569\uB2C8\uB2E4.
        </p>
        {watchlist.length > 0 ? (
          <button
            onClick={handleAnalyze}
            disabled={analyzing}
            className="px-5 py-2 bg-[#1261c4] text-white text-[13px] font-medium rounded hover:bg-[#0d4e9e] disabled:bg-[#999]"
          >
            {analyzing ? 'AI \uBD84\uC11D \uC911...' : `\uD3EC\uD2B8\uD3F4\uB9AC\uC624 \uBD84\uC11D (${watchlist.length}\uC885\uBAA9)`}
          </button>
        ) : (
          <p className="text-[13px] text-[#e12343]">
            \uAD00\uC2EC\uC885\uBAA9\uC744 \uBA3C\uC800 \uB4F1\uB85D\uD574\uC8FC\uC138\uC694.
          </p>
        )}
      </div>
    );
  }

  const sections = [
    { title: '\uC885\uD569 \uD3C9\uAC00', content: report.overall_assessment, icon: '\u{1F4CA}' },
    { title: '\uB9AC\uC2A4\uD06C \uBD84\uC11D', content: report.risk_analysis, icon: '\u{26A0}\u{FE0F}' },
    { title: '\uC139\uD130 \uBD84\uC0B0\uB3C4', content: report.sector_balance, icon: '\u{1F3AF}' },
    { title: '\uB9AC\uBC38\uB7F0\uC2F1 \uC81C\uC548', content: report.rebalancing, icon: '\u{1F504}' },
  ];

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <span className="text-[13px] text-[#999]">
          \uBD84\uC11D\uC77C: {formatDateTime(report.created_at)}
        </span>
        <button
          onClick={handleAnalyze}
          disabled={analyzing || watchlist.length === 0}
          className="text-[12px] text-[#1261c4] hover:underline disabled:text-[#999]"
        >
          {analyzing ? '\uBD84\uC11D \uC911...' : '\uB2E4\uC2DC \uBD84\uC11D'}
        </button>
      </div>
      <div className="space-y-3">
        {sections.map((section) =>
          section.content ? (
            <div key={section.title} className="section-box">
              <div className="section-title">
                <span>{section.icon} {section.title}</span>
              </div>
              <div className="p-4 text-[13px] text-[#333] leading-relaxed whitespace-pre-wrap">
                {section.content}
              </div>
            </div>
          ) : null
        )}
      </div>
    </div>
  );
}

// ── Main Page ──
export default function FundManagerPage() {
  const { isAdmin, checking, login, logout } = useAdmin();
  const [tab, setTab] = useState<Tab>('briefing');

  if (checking) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-[13px] text-[#999]">\uC778\uC99D \uD655\uC778 \uC911...</div>
      </div>
    );
  }

  if (!isAdmin) {
    return <AdminLogin onLogin={login} />;
  }

  const tabs: { key: Tab; label: string }[] = [
    { key: 'briefing', label: '\uB370\uC77C\uB9AC \uBE0C\uB9AC\uD551' },
    { key: 'signals', label: '\uD22C\uC790 \uC2DC\uADF8\uB110' },
    { key: 'accuracy', label: '\uC801\uC911\uB960' },
    { key: 'portfolio', label: '\uD3EC\uD2B8\uD3F4\uB9AC\uC624' },
  ];

  return (
    <div>
      <div className="section-box mb-3">
        <div className="flex items-center justify-between px-4 py-3">
          <div>
            <h1 className="text-[16px] font-bold text-[#333]">AI Fund Manager</h1>
            <p className="text-[12px] text-[#999] mt-0.5">
              \uB274\uC2A4 + \uACF5\uC2DC + \uC2DC\uC138 + \uC7AC\uBB34\uC81C\uD45C\uB97C \uC885\uD569 \uBD84\uC11D\uD558\uB294 AI \uD380\uB4DC\uB9E4\uB2C8\uC800
            </p>
          </div>
          <button
            onClick={logout}
            className="text-[12px] text-[#999] hover:text-[#e12343]"
          >
            \uB85C\uADF8\uC544\uC6C3
          </button>
        </div>
        <div className="flex border-t border-[#e5e5e5]">
          {tabs.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`flex-1 py-2.5 text-[13px] font-semibold text-center border-b-2 transition-colors ${
                tab === t.key
                  ? 'border-[#1261c4] text-[#1261c4] bg-[#f7f8fa]'
                  : 'border-transparent text-[#666] hover:text-[#333]'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {tab === 'briefing' && <BriefingTab />}
      {tab === 'signals' && <SignalsTab />}
      {tab === 'accuracy' && <AccuracyTab />}
      {tab === 'portfolio' && <PortfolioTab />}
    </div>
  );
}
