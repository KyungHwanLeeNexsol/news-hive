'use client';

import { useEffect, useState, useCallback } from 'react';
import Link from 'next/link';
import {
  fetchFundSignals,
  fetchDailyBriefing,
  generateDailyBriefing,
  analyzePortfolio,
  fetchLatestPortfolioReport,
  fetchAccuracyStats,
  verifySignals,
  fetchPaperTradingStats,
  fetchPaperPositions,
  fetchPaperTrades,
  fetchPaperSnapshots,
  resetPaperTrading,
} from '@/lib/api';
import type {
  FundSignal, DailyBriefing, PortfolioReport, AccuracyStats,
  PaperTradingStats, PaperPosition, PaperTrade, PaperSnapshot,
} from '@/lib/types';
import { useWatchlist } from '@/lib/watchlist';
import { useAdmin } from '@/lib/useAdmin';
import BacktestDashboard from '@/components/BacktestDashboard';

type Tab = 'briefing' | 'signals' | 'accuracy' | 'portfolio' | 'paper' | 'backtest';

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
    buy: { label: '매수', bg: 'bg-[#ffebee]', text: 'text-[#e12343]', border: 'border-[#e12343]' },
    sell: { label: '매도', bg: 'bg-[#e3f2fd]', text: 'text-[#1261c4]', border: 'border-[#1261c4]' },
    hold: { label: '관망', bg: 'bg-[#f5f5f5]', text: 'text-[#666]', border: 'border-[#999]' },
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

function AiModelBadge({ model }: { model: string | null | undefined }) {
  if (!model) return null;
  const isGlm = model.toLowerCase().includes('glm');
  return (
    <span
      className={`text-[10px] px-1.5 py-0.5 rounded font-mono border ${
        isGlm
          ? 'bg-[#fff8e1] text-[#f57f17] border-[#ffe082]'
          : 'bg-[#e8f5e9] text-[#2e7d32] border-[#a5d6a7]'
      }`}
      title={isGlm ? 'Gemini rate limit 초과로 GLM 모델 사용 — 분석 품질이 다소 낮을 수 있습니다' : `AI 모델: ${model}`}
    >
      {model}
    </span>
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
        {signal.is_correct ? '적중' : '불적중'}
        {signal.return_pct != null && ` ${signal.return_pct > 0 ? '+' : ''}${signal.return_pct}%`}
      </span>
    );
  }
  if (signal.price_at_signal) {
    const days = signal.price_after_5d ? 5 : signal.price_after_3d ? 3 : signal.price_after_1d ? 1 : 0;
    return (
      <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-[#fff3e0] text-[#e65100] font-medium">
        검증중 {days > 0 ? `(${days}일)` : ''}
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
    if (!ok) setError('비밀번호가 일치하지 않습니다.');
    setLoading(false);
  }

  return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <div className="section-box p-8 w-full max-w-sm">
        <div className="text-center mb-6">
          <div className="text-[32px] mb-2">&#x1F512;</div>
          <h2 className="text-[16px] font-bold text-[#333]">AI Fund Manager</h2>
          <p className="text-[12px] text-[#999] mt-1">관리자 로그인이 필요합니다</p>
        </div>
        <form onSubmit={handleSubmit}>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="비밀번호"
            className="w-full px-3 py-2.5 border border-[#ddd] rounded text-[13px] mb-3 focus:outline-none focus:border-[#1261c4]"
            autoFocus
          />
          {error && <p className="text-[12px] text-[#e12343] mb-2">{error}</p>}
          <button
            type="submit"
            disabled={loading || !password}
            className="w-full py-2.5 bg-[#1261c4] text-white text-[13px] font-medium rounded hover:bg-[#0d4e9e] disabled:bg-[#999]"
          >
            {loading ? '로그인 중...' : '로그인'}
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
      alert('브리핑 생성에 실패했습니다. AI API 키를 확인하세요.');
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

  if (!briefing && !generating) {
    return (
      <div className="section-box p-8 text-center">
        <div className="text-[40px] mb-3">&#x1F4CA;</div>
        <p className="text-[15px] text-[#333] font-medium mb-1">오늘의 AI 브리핑이 아직 없습니다</p>
        <p className="text-[13px] text-[#999] mb-4">
          AI가 최근 뉴스, 공시, 매크로 데이터를 종합 분석하여<br />
          전문 펀드매니저 수준의 시장 브리핑을 생성합니다.
        </p>
        <button
          onClick={() => handleGenerate()}
          className="px-5 py-2 bg-[#1261c4] text-white text-[13px] font-medium rounded hover:bg-[#0d4e9e]"
        >
          오늘의 브리핑 생성
        </button>
      </div>
    );
  }

  if (generating) {
    return (
      <div>
        <div className="flex items-center justify-between mb-3">
          <span className="text-[13px] text-[#999]">AI 브리핑 생성 중...</span>
        </div>
        <div className="space-y-3">
          {/* 시장 전망 스켈레톤 */}
          <div className="section-box">
            <div className="section-title"><span>&#x1F30D; 시장 전망</span></div>
            <div className="p-4 space-y-2">
              <div className="skeleton skeleton-text" style={{ width: '95%' }} />
              <div className="skeleton skeleton-text" style={{ width: '88%' }} />
              <div className="skeleton skeleton-text" style={{ width: '92%' }} />
              <div className="skeleton skeleton-text" style={{ width: '75%' }} />
            </div>
          </div>
          {/* 주목 섹터 스켈레톤 */}
          <div className="section-box">
            <div className="section-title"><span>&#x1F3AF; 주목 섹터</span></div>
            <div className="p-4 space-y-2.5">
              {Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="border border-[#eee] rounded-lg p-3">
                  <div className="flex items-center gap-2 mb-2">
                    <div className="skeleton skeleton-text" style={{ width: '80px' }} />
                    <div className="skeleton skeleton-badge" style={{ width: '40px' }} />
                  </div>
                  <div className="skeleton skeleton-text mb-1" style={{ width: '90%' }} />
                  <div className="skeleton skeleton-text" style={{ width: '70%' }} />
                </div>
              ))}
            </div>
          </div>
          {/* 매수 추천 스켈레톤 */}
          <div className="section-box">
            <div className="section-title"><span>&#x2B50; 오늘의 매수 추천</span></div>
            <div className="p-4 space-y-2.5">
              {Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="border border-[#eee] rounded-lg p-3">
                  <div className="flex items-center gap-2 mb-2">
                    <div className="skeleton skeleton-text" style={{ width: '100px' }} />
                    <div className="skeleton skeleton-badge" style={{ width: '50px' }} />
                  </div>
                  <div className="skeleton skeleton-text mb-1" style={{ width: '95%' }} />
                  <div className="skeleton skeleton-text mb-1" style={{ width: '85%' }} />
                  <div className="skeleton skeleton-text" style={{ width: '60%' }} />
                </div>
              ))}
            </div>
          </div>
          {/* 리스크 평가 스켈레톤 */}
          <div className="section-box">
            <div className="section-title"><span>&#x26A0;&#xFE0F; 리스크 평가</span></div>
            <div className="p-4 space-y-2">
              <div className="skeleton skeleton-text" style={{ width: '90%' }} />
              <div className="skeleton skeleton-text" style={{ width: '80%' }} />
              <div className="skeleton skeleton-text" style={{ width: '70%' }} />
            </div>
          </div>
          {/* 투자 전략 스켈레톤 */}
          <div className="section-box">
            <div className="section-title"><span>&#x1F4DD; 투자 전략</span></div>
            <div className="p-4 space-y-2">
              <div className="skeleton skeleton-text" style={{ width: '92%' }} />
              <div className="skeleton skeleton-text" style={{ width: '85%' }} />
              <div className="skeleton skeleton-text" style={{ width: '78%' }} />
            </div>
          </div>
        </div>
        <div className="mt-4 text-center">
          <div className="inline-flex items-center gap-2 px-4 py-2 bg-[#f7f8fa] rounded-lg">
            <div className="w-4 h-4 border-2 border-[#1261c4] border-t-transparent rounded-full animate-spin" />
            <span className="text-[13px] text-[#666]">AI가 뉴스, 공시, 시세, 수급 데이터를 분석하고 있습니다...</span>
          </div>
        </div>
      </div>
    );
  }

  interface SectorItem { sector: string; sentiment?: string; analysis: string }
  interface StockItem { stock: string; action?: string; reason: string; target_price?: number; stop_loss?: number }

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

  const b = briefing!;
  const sectorItems = tryParseJson<SectorItem>(b.sector_highlights);
  const stockItems = tryParseJson<StockItem>(b.stock_picks);

  const sentimentColor = (s: string) => {
    if (s === 'positive') return { bg: 'bg-[#e8f5e9]', text: 'text-[#2e7d32]', label: '긍정' };
    if (s === 'negative') return { bg: 'bg-[#fce4ec]', text: 'text-[#c62828]', label: '부정' };
    return { bg: 'bg-[#f5f5f5]', text: 'text-[#616161]', label: '중립' };
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-[13px] text-[#999]">
            {b.briefing_date} 브리핑
          </span>
          <AiModelBadge model={b.ai_model} />
        </div>
        <button
          onClick={() => handleGenerate(true)}
          disabled={generating}
          className="text-[12px] text-[#1261c4] hover:underline disabled:text-[#999]"
        >
          다시 생성
        </button>
      </div>
      <div className="space-y-3">
        {b.market_overview && (
          <div className="section-box">
            <div className="section-title"><span>&#x1F30D; 시장 전망</span></div>
            <div className="p-4 text-[13px] text-[#333] leading-[1.8]">
              {b.market_overview}
            </div>
          </div>
        )}
        {b.sector_highlights && (
          <div className="section-box">
            <div className="section-title"><span>&#x1F3AF; 주목 섹터</span></div>
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
                <div className="text-[13px] text-[#333] leading-[1.8]">{b.sector_highlights}</div>
              )}
            </div>
          </div>
        )}
        {b.stock_picks && (
          <div className="section-box">
            <div className="section-title"><span>&#x2B50; 오늘의 매수 추천</span></div>
            <div className="p-4">
              {stockItems ? (
                <div className="space-y-2.5">
                  {stockItems.map((item, i) => {
                    const actionStyle = (a?: string) => {
                      if (a === '적극매수') return { bg: 'bg-[#e12343]', text: 'text-white' };
                      if (a === '매수') return { bg: 'bg-[#1261c4]', text: 'text-white' };
                      if (a === '회피') return { bg: 'bg-[#666]', text: 'text-white' };
                      return { bg: 'bg-[#f5f5f5]', text: 'text-[#666]' };
                    };
                    const as = actionStyle(item.action);
                    return (
                      <div key={i} className="border border-[#eee] rounded-lg p-3">
                        <div className="flex items-center justify-between mb-1.5">
                          <div className="flex items-center gap-2">
                            <span className="text-[14px] font-semibold text-[#1261c4]">{item.stock}</span>
                            {item.action && (
                              <span className={`text-[10px] px-2 py-0.5 rounded-full font-bold ${as.bg} ${as.text}`}>
                                {item.action}
                              </span>
                            )}
                          </div>
                          <div className="flex items-center gap-3 text-[11px] text-[#999]">
                            {item.target_price != null && item.target_price > 0 && (
                              <span>목표 <span className="text-[#e12343] font-medium">{item.target_price.toLocaleString()}</span></span>
                            )}
                            {item.stop_loss != null && item.stop_loss > 0 && (
                              <span>손절 <span className="text-[#1261c4] font-medium">{item.stop_loss.toLocaleString()}</span></span>
                            )}
                          </div>
                        </div>
                        <p className="text-[12.5px] text-[#555] leading-[1.7]">{item.reason}</p>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="text-[13px] text-[#333] leading-[1.8]">{b.stock_picks}</div>
              )}
            </div>
          </div>
        )}
        {b.risk_assessment && (
          <div className="section-box">
            <div className="section-title"><span>&#x26A0;&#xFE0F; 리스크 평가</span></div>
            <div className="p-4 text-[13px] text-[#333] leading-[1.8]">
              {b.risk_assessment}
            </div>
          </div>
        )}
        {b.strategy && (
          <div className="section-box">
            <div className="section-title"><span>&#x1F4DD; 투자 전략</span></div>
            <div className="p-4 text-[13px] text-[#333] leading-[1.8]">
              {b.strategy}
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
  const [expanded, setExpanded] = useState<number | null>(null);

  useEffect(() => {
    fetchFundSignals().then(setSignals).catch(() => {}).finally(() => setLoading(false));
  }, []);

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
      {signals.length === 0 ? (
        <div className="section-box p-8 text-center">
          <p className="text-[15px] text-[#333] font-medium mb-1">생성된 투자 시그널이 없습니다</p>
          <p className="text-[13px] text-[#999]">
            데일리 브리핑 생성 시 추천 종목의 시그널이 자동 생성됩니다.
          </p>
        </div>
      ) : (
        <div className="section-box">
          <div className="section-title">
            <span>AI 투자 시그널</span>
            <span className="text-[12px] font-normal text-[#999]">{signals.length}건</span>
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
                      {signal.stock_name || `종목#${signal.stock_id}`}
                    </Link>
                    {signal.sector_name && (
                      <span className="badge badge-sector">{signal.sector_name}</span>
                    )}
                    <VerificationBadge signal={signal} />
                    <AiModelBadge model={signal.ai_model} />
                  </div>
                  <div className="flex items-center gap-3 text-[12px] text-[#999]">
                    {signal.target_price && (
                      <span>목표가 {formatNumber(signal.target_price)}</span>
                    )}
                    {signal.stop_loss && (
                      <span>손절가 {formatNumber(signal.stop_loss)}</span>
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
                  {signal.price_at_signal && (
                    <div className="p-3 bg-[#fafafa] rounded border border-[#eee]">
                      <div className="text-[12px] font-bold text-[#333] mb-2">주가 추적</div>
                      <div className="grid grid-cols-4 gap-2 text-[12px]">
                        <div>
                          <span className="text-[#999]">시그널 시점</span>
                          <div className="font-medium">{formatNumber(signal.price_at_signal)}원</div>
                        </div>
                        <div>
                          <span className="text-[#999]">1일 후</span>
                          <div className="font-medium">{signal.price_after_1d ? `${formatNumber(signal.price_after_1d)}원` : '-'}</div>
                        </div>
                        <div>
                          <span className="text-[#999]">3일 후</span>
                          <div className="font-medium">{signal.price_after_3d ? `${formatNumber(signal.price_after_3d)}원` : '-'}</div>
                        </div>
                        <div>
                          <span className="text-[#999]">5일 후</span>
                          <div className="font-medium">{signal.price_after_5d ? `${formatNumber(signal.price_after_5d)}원` : '-'}</div>
                        </div>
                      </div>
                    </div>
                  )}
                  {signal.news_summary && (
                    <div className="p-3 bg-[#f7f8fa] rounded">
                      <div className="text-[12px] font-bold text-[#1261c4] mb-1">뉴스 분석</div>
                      <p className="text-[12px] text-[#555] leading-relaxed">{signal.news_summary}</p>
                    </div>
                  )}
                  {signal.financial_summary && (
                    <div className="p-3 bg-[#f7f8fa] rounded">
                      <div className="text-[12px] font-bold text-[#2e7d32] mb-1">재무 분석</div>
                      <p className="text-[12px] text-[#555] leading-relaxed">{signal.financial_summary}</p>
                    </div>
                  )}
                  {signal.market_summary && (
                    <div className="p-3 bg-[#f7f8fa] rounded">
                      <div className="text-[12px] font-bold text-[#e65100] mb-1">기술적 분석</div>
                      <p className="text-[12px] text-[#555] leading-relaxed">{signal.market_summary}</p>
                    </div>
                  )}
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
      alert(`검증 완료: ${result.verified}건 검증, ${result.updated}건 업데이트`);
      load(days);
    } catch {
      alert('검증에 실패했습니다.');
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
        <div className="text-[40px] mb-3">&#x1F4CA;</div>
        <p className="text-[15px] text-[#333] font-medium mb-1">검증된 시그널이 없습니다</p>
        <p className="text-[13px] text-[#999] mb-4">
          시그널 발행 후 5일이 지나면 자동으로 적중 여부가 검증됩니다.<br/>
          수동 검증을 하려면 아래 버튼을 클릭하세요.
        </p>
        <button
          onClick={handleVerify}
          disabled={verifying}
          className="px-5 py-2 bg-[#1261c4] text-white text-[13px] font-medium rounded hover:bg-[#0d4e9e] disabled:bg-[#999]"
        >
          {verifying ? '검증 중...' : '수동 검증 실행'}
        </button>
      </div>
    );
  }

  const confidenceLevels = [
    { key: 'high', label: '고신뢰 (70%+)', color: '#e12343' },
    { key: 'medium', label: '중간 (40-70%)', color: '#ffa723' },
    { key: 'low', label: '저신뢰 (<40%)', color: '#999' },
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
              {d}일
            </button>
          ))}
        </div>
        <button
          onClick={handleVerify}
          disabled={verifying}
          className="text-[12px] text-[#1261c4] hover:underline disabled:text-[#999]"
        >
          {verifying ? '검증 중...' : '수동 검증'}
        </button>
      </div>

      {/* Overview cards */}
      <div className="grid grid-cols-4 gap-3 mb-3">
        <div className="section-box p-4 text-center">
          <div className="text-[24px] font-bold text-[#1261c4]">{stats.accuracy}%</div>
          <div className="text-[11px] text-[#999] mt-1">전체 적중률</div>
          <div className="text-[11px] text-[#666]">{stats.correct}/{stats.total}건</div>
        </div>
        <div className="section-box p-4 text-center">
          <div className="text-[24px] font-bold text-[#e12343]">{stats.buy_accuracy}%</div>
          <div className="text-[11px] text-[#999] mt-1">매수 적중률</div>
        </div>
        <div className="section-box p-4 text-center">
          <div className="text-[24px] font-bold text-[#1261c4]">{stats.sell_accuracy}%</div>
          <div className="text-[11px] text-[#999] mt-1">매도 적중률</div>
        </div>
        <div className="section-box p-4 text-center">
          <div className={`text-[24px] font-bold ${stats.avg_return >= 0 ? 'text-[#e12343]' : 'text-[#1261c4]'}`}>
            {stats.avg_return > 0 ? '+' : ''}{stats.avg_return}%
          </div>
          <div className="text-[11px] text-[#999] mt-1">평균 수익률</div>
        </div>
      </div>

      {/* Accuracy bar */}
      <div className="section-box mb-3">
        <div className="section-title"><span>&#x1F3AF; 적중률 바</span></div>
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
          <div className="section-title"><span>&#x1F4CA; 신뢰도별 적중률</span></div>
          <div className="p-4 space-y-3">
            {confidenceLevels.map(({ key, label, color }) => {
              const bucket = stats.by_confidence[key];
              if (!bucket) return null;
              return (
                <div key={key}>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[12px] text-[#333] font-medium">{label}</span>
                    <span className="text-[12px] text-[#666]">
                      {bucket.accuracy}% ({bucket.total}건)
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
/** Lightweight markdown-like renderer for AI report content. */
function RenderMarkdown({ text }: { text: string }) {
  const lines = text.split('\n');
  const elements: React.ReactNode[] = [];
  let key = 0;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();

    // Skip empty lines
    if (!trimmed) {
      elements.push(<div key={key++} className="h-2" />);
      continue;
    }

    // ## Heading
    if (trimmed.startsWith('## ')) {
      elements.push(
        <h3 key={key++} className="text-[13px] font-bold text-[#1261c4] mt-3 mb-1.5 pb-1 border-b border-[#e8e8e8]">
          {trimmed.slice(3)}
        </h3>
      );
      continue;
    }

    // Numbered list: 1. item
    if (/^\d+\.\s/.test(trimmed)) {
      const num = trimmed.match(/^(\d+)\./)?.[1] || '';
      const content = trimmed.replace(/^\d+\.\s*/, '');
      elements.push(
        <div key={key++} className="flex gap-2 text-[13px] text-[#333] leading-relaxed pl-1 py-0.5">
          <span className="text-[#1261c4] font-bold shrink-0">{num}.</span>
          <span dangerouslySetInnerHTML={{ __html: boldify(content) }} />
        </div>
      );
      continue;
    }

    // Bullet point: - item
    if (trimmed.startsWith('- ')) {
      const content = trimmed.slice(2);
      elements.push(
        <div key={key++} className="flex gap-2 text-[13px] text-[#333] leading-relaxed pl-1 py-0.5">
          <span className="text-[#1261c4] shrink-0 mt-[2px]">&#x2022;</span>
          <span dangerouslySetInnerHTML={{ __html: boldify(content) }} />
        </div>
      );
      continue;
    }

    // Regular text
    elements.push(
      <p key={key++} className="text-[13px] text-[#333] leading-relaxed py-0.5" dangerouslySetInnerHTML={{ __html: boldify(trimmed) }} />
    );
  }

  return <>{elements}</>;
}

/** Convert **bold** markers to <strong> tags. */
function boldify(text: string): string {
  return text.replace(/\*\*(.+?)\*\*/g, '<strong class="text-[#111] font-semibold">$1</strong>');
}

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
      alert('관심종목을 먼저 등록해주세요.');
      return;
    }
    setAnalyzing(true);
    try {
      const r = await analyzePortfolio(watchlist);
      setReport(r);
    } catch {
      alert('포트폴리오 분석에 실패했습니다.');
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
        <p className="text-[15px] text-[#333] font-medium mb-1">포트폴리오 분석 리포트가 없습니다</p>
        <p className="text-[13px] text-[#999] mb-4">
          관심종목을 기반으로 AI가 포트폴리오를 종합 분석합니다.<br />
          섹터 분산도, 리스크, 리밸런싱 전략을 제안합니다.
        </p>
        {watchlist.length > 0 ? (
          <button
            onClick={handleAnalyze}
            disabled={analyzing}
            className="px-5 py-2 bg-[#1261c4] text-white text-[13px] font-medium rounded hover:bg-[#0d4e9e] disabled:bg-[#999]"
          >
            {analyzing ? 'AI 분석 중...' : `포트폴리오 분석 (${watchlist.length}종목)`}
          </button>
        ) : (
          <p className="text-[13px] text-[#e12343]">
            관심종목을 먼저 등록해주세요.
          </p>
        )}
      </div>
    );
  }

  const sections: { title: string; content: string | null; icon: string; color: string }[] = [
    { title: '종합 평가', content: report.overall_assessment, icon: '\uD83D\uDCCA', color: '#1261c4' },
    { title: '리스크 분석', content: report.risk_analysis, icon: '\u26A0\uFE0F', color: '#e12343' },
    { title: '섹터 분산도', content: report.sector_balance, icon: '\uD83C\uDFAF', color: '#0d9488' },
    { title: '리밸런싱 제안', content: report.rebalancing, icon: '\uD83D\uDD04', color: '#7c3aed' },
  ];

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <span className="text-[13px] text-[#999]">
          분석일: {formatDateTime(report.created_at)}
        </span>
        <button
          onClick={handleAnalyze}
          disabled={analyzing || watchlist.length === 0}
          className="text-[12px] text-[#1261c4] hover:underline disabled:text-[#999]"
        >
          {analyzing ? '분석 중...' : '다시 분석'}
        </button>
      </div>
      <div className="space-y-3">
        {sections.map((section) =>
          section.content ? (
            <div key={section.title} className="section-box overflow-hidden">
              <div
                className="px-4 py-2.5 flex items-center gap-2 text-[14px] font-bold text-white"
                style={{ backgroundColor: section.color }}
              >
                <span>{section.icon}</span>
                <span>{section.title}</span>
              </div>
              <div className="p-4">
                <RenderMarkdown text={section.content} />
              </div>
            </div>
          ) : null
        )}
      </div>
    </div>
  );
}

// ── Paper Trading Tab ──
function PaperTradingTab() {
  const [stats, setStats] = useState<PaperTradingStats | null>(null);
  const [positions, setPositions] = useState<PaperPosition[]>([]);
  const [trades, setTrades] = useState<PaperTrade[]>([]);
  const [snapshots, setSnapshots] = useState<PaperSnapshot[]>([]);
  const [loading, setLoading] = useState(true);
  const [resetting, setResetting] = useState(false);

  useEffect(() => {
    Promise.all([
      fetchPaperTradingStats(),
      fetchPaperPositions(),
      fetchPaperTrades(50),
      fetchPaperSnapshots(30),
    ])
      .then(([s, p, t, sn]) => {
        setStats(s);
        setPositions(p);
        setTrades(t);
        setSnapshots(sn);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  async function handleReset() {
    if (!confirm('포트폴리오를 초기화하시겠습니까?\n모든 포지션과 거래 기록이 삭제됩니다.')) return;
    setResetting(true);
    try {
      const ok = await resetPaperTrading();
      if (ok) {
        setStats(null);
        setPositions([]);
        setTrades([]);
        setSnapshots([]);
        // 초기화 후 새로 불러오기
        const s = await fetchPaperTradingStats();
        setStats(s);
      } else {
        alert('초기화에 실패했습니다.');
      }
    } catch {
      alert('초기화에 실패했습니다.');
    } finally {
      setResetting(false);
    }
  }

  const exitReasonLabel: Record<string, string> = {
    target_hit: '목표가 도달',
    stop_loss: '손절',
    timeout: '기간만료',
    signal_sell: '매도시그널',
  };

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="grid grid-cols-4 gap-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="section-box p-4">
              <div className="skeleton skeleton-text mb-2" style={{ width: '60%' }} />
              <div className="skeleton skeleton-text" style={{ width: '40%' }} />
            </div>
          ))}
        </div>
        <div className="section-box p-4">
          <div className="skeleton skeleton-text mb-2" style={{ width: '30%' }} />
          <div className="skeleton skeleton-text mb-1" style={{ width: '90%' }} />
          <div className="skeleton skeleton-text" style={{ width: '70%' }} />
        </div>
      </div>
    );
  }

  if (!stats) {
    return (
      <div className="section-box p-8 text-center">
        <div className="text-[40px] mb-3">&#x1F4B9;</div>
        <p className="text-[15px] text-[#333] font-medium mb-1">페이퍼 트레이딩 데이터가 없습니다</p>
        <p className="text-[13px] text-[#999]">
          AI 펀드매니저가 시그널을 기반으로 모의 매매를 실행하면 여기에 표시됩니다.
        </p>
      </div>
    );
  }

  const totalValue = stats.initial_capital + stats.total_pnl;

  return (
    <div>
      {/* 상단 통계 카드 */}
      <div className="grid grid-cols-4 gap-3 mb-3">
        <div className="section-box p-4 text-center">
          <div className="text-[20px] font-bold text-[#333]">
            {formatNumber(totalValue)}
            <span className="text-[12px] font-normal text-[#999] ml-1">원</span>
          </div>
          <div className="text-[11px] text-[#999] mt-1">총 자산</div>
          <div className={`text-[12px] font-medium mt-0.5 ${stats.cumulative_return >= 0 ? 'text-[#e12343]' : 'text-[#1261c4]'}`}>
            {stats.cumulative_return >= 0 ? '+' : ''}{stats.cumulative_return.toFixed(2)}%
          </div>
        </div>
        <div className="section-box p-4 text-center">
          <div className={`text-[24px] font-bold ${stats.win_rate >= 50 ? 'text-[#e12343]' : 'text-[#1261c4]'}`}>
            {stats.win_rate.toFixed(1)}%
          </div>
          <div className="text-[11px] text-[#999] mt-1">승률</div>
          <div className="text-[11px] text-[#666]">{stats.closed_trades}건 중</div>
        </div>
        <div className="section-box p-4 text-center">
          <div className={`text-[24px] font-bold ${stats.sharpe_warning ? 'text-[#ffa723]' : 'text-[#2e7d32]'}`}>
            {stats.sharpe_ratio.toFixed(2)}
          </div>
          <div className="text-[11px] text-[#999] mt-1">Sharpe Ratio</div>
          {stats.sharpe_warning && (
            <div className="text-[10px] text-[#ffa723] font-medium mt-0.5">&#x26A0; 1.0 미만</div>
          )}
        </div>
        <div className="section-box p-4 text-center">
          <div className="text-[24px] font-bold text-[#1261c4]">
            {stats.mdd.toFixed(2)}%
          </div>
          <div className="text-[11px] text-[#999] mt-1">MDD</div>
          <div className="text-[11px] text-[#666]">최대낙폭</div>
        </div>
      </div>

      {/* 오픈 포지션 */}
      <div className="section-box mb-3">
        <div className="section-title">
          <span>오픈 포지션</span>
          <span className="text-[12px] font-normal text-[#999]">{positions.length}건</span>
        </div>
        {positions.length === 0 ? (
          <div className="p-6 text-center text-[13px] text-[#999]">
            오픈 포지션이 없습니다
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-[12px]">
              <thead>
                <tr className="border-b border-[#eee] bg-[#f7f8fa]">
                  <th className="text-left px-4 py-2.5 font-semibold text-[#666]">종목명</th>
                  <th className="text-right px-4 py-2.5 font-semibold text-[#666]">진입가</th>
                  <th className="text-right px-4 py-2.5 font-semibold text-[#666]">수량</th>
                  <th className="text-right px-4 py-2.5 font-semibold text-[#666]">투자금액</th>
                  <th className="text-right px-4 py-2.5 font-semibold text-[#666]">목표가</th>
                  <th className="text-right px-4 py-2.5 font-semibold text-[#666]">손절가</th>
                  <th className="text-right px-4 py-2.5 font-semibold text-[#666]">진입일</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((pos, i) => (
                  <tr key={i} className="border-b border-[#f0f0f0] hover:bg-[#f7f8fa]">
                    <td className="px-4 py-2.5 font-medium text-[#333]">{pos.stock_name}</td>
                    <td className="text-right px-4 py-2.5 text-[#333]">{formatNumber(pos.entry_price)}원</td>
                    <td className="text-right px-4 py-2.5 text-[#333]">{formatNumber(pos.quantity)}</td>
                    <td className="text-right px-4 py-2.5 text-[#333]">{formatNumber(pos.invest_amount)}원</td>
                    <td className="text-right px-4 py-2.5 text-[#e12343]">{formatNumber(pos.target_price)}원</td>
                    <td className="text-right px-4 py-2.5 text-[#1261c4]">{formatNumber(pos.stop_loss)}원</td>
                    <td className="text-right px-4 py-2.5 text-[#999]">{pos.entry_date.slice(0, 10)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* 거래 내역 */}
      <div className="section-box mb-3">
        <div className="section-title">
          <span>거래 내역</span>
          <span className="text-[12px] font-normal text-[#999]">{trades.length}건</span>
        </div>
        {trades.length === 0 ? (
          <div className="p-6 text-center text-[13px] text-[#999]">
            거래 내역이 없습니다
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-[12px]">
              <thead>
                <tr className="border-b border-[#eee] bg-[#f7f8fa]">
                  <th className="text-left px-4 py-2.5 font-semibold text-[#666]">종목명</th>
                  <th className="text-right px-4 py-2.5 font-semibold text-[#666]">진입가</th>
                  <th className="text-right px-4 py-2.5 font-semibold text-[#666]">청산가</th>
                  <th className="text-right px-4 py-2.5 font-semibold text-[#666]">손익</th>
                  <th className="text-right px-4 py-2.5 font-semibold text-[#666]">수익률</th>
                  <th className="text-center px-4 py-2.5 font-semibold text-[#666]">청산사유</th>
                  <th className="text-right px-4 py-2.5 font-semibold text-[#666]">진입일</th>
                  <th className="text-right px-4 py-2.5 font-semibold text-[#666]">청산일</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((trade, i) => (
                  <tr key={i} className="border-b border-[#f0f0f0] hover:bg-[#f7f8fa]">
                    <td className="px-4 py-2.5 font-medium text-[#333]">{trade.stock_name}</td>
                    <td className="text-right px-4 py-2.5 text-[#333]">{formatNumber(trade.entry_price)}원</td>
                    <td className="text-right px-4 py-2.5 text-[#333]">{formatNumber(trade.exit_price)}원</td>
                    <td className={`text-right px-4 py-2.5 font-medium ${trade.pnl >= 0 ? 'text-[#e12343]' : 'text-[#1261c4]'}`}>
                      {trade.pnl >= 0 ? '+' : ''}{formatNumber(trade.pnl)}원
                    </td>
                    <td className={`text-right px-4 py-2.5 font-medium ${trade.return_pct >= 0 ? 'text-[#e12343]' : 'text-[#1261c4]'}`}>
                      {trade.return_pct >= 0 ? '+' : ''}{trade.return_pct.toFixed(2)}%
                    </td>
                    <td className="text-center px-4 py-2.5">
                      <span className={`inline-block px-2 py-0.5 rounded text-[10px] font-medium ${
                        trade.exit_reason === 'target_hit'
                          ? 'bg-[#e8f5e9] text-[#2e7d32]'
                          : trade.exit_reason === 'stop_loss'
                            ? 'bg-[#fce4ec] text-[#c62828]'
                            : 'bg-[#f5f5f5] text-[#666]'
                      }`}>
                        {exitReasonLabel[trade.exit_reason] || trade.exit_reason}
                      </span>
                    </td>
                    <td className="text-right px-4 py-2.5 text-[#999]">{trade.entry_date.slice(0, 10)}</td>
                    <td className="text-right px-4 py-2.5 text-[#999]">{trade.exit_date.slice(0, 10)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* 일별 수익률 추이 */}
      <div className="section-box mb-3">
        <div className="section-title">
          <span>일별 수익률 추이</span>
          <span className="text-[12px] font-normal text-[#999]">최근 {snapshots.length}일</span>
        </div>
        {snapshots.length === 0 ? (
          <div className="p-6 text-center text-[13px] text-[#999]">
            스냅샷 데이터가 없습니다
          </div>
        ) : (
          <div className="p-4">
            {/* 누적 수익률 바 차트 */}
            <div className="space-y-1.5">
              {snapshots.map((snap) => {
                const maxAbs = Math.max(
                  ...snapshots.map((s) => Math.abs(s.cumulative_return_pct)),
                  1,
                );
                const width = Math.abs(snap.cumulative_return_pct) / maxAbs * 50;
                const isPositive = snap.cumulative_return_pct >= 0;
                return (
                  <div key={snap.date} className="flex items-center gap-2 text-[11px]">
                    <span className="w-[70px] text-[#999] shrink-0">{snap.date.slice(5)}</span>
                    <div className="flex-1 flex items-center">
                      <div className="w-1/2 flex justify-end">
                        {!isPositive && (
                          <div
                            className="h-3 bg-[#1261c4] rounded-l"
                            style={{ width: `${width}%` }}
                          />
                        )}
                      </div>
                      <div className="w-px h-4 bg-[#ddd] shrink-0" />
                      <div className="w-1/2">
                        {isPositive && (
                          <div
                            className="h-3 bg-[#e12343] rounded-r"
                            style={{ width: `${width}%` }}
                          />
                        )}
                      </div>
                    </div>
                    <span className={`w-[55px] text-right shrink-0 font-medium ${isPositive ? 'text-[#e12343]' : 'text-[#1261c4]'}`}>
                      {isPositive ? '+' : ''}{snap.cumulative_return_pct.toFixed(2)}%
                    </span>
                  </div>
                );
              })}
            </div>
            {/* 범례 */}
            <div className="flex items-center justify-center gap-4 mt-3 text-[10px] text-[#999]">
              <span className="flex items-center gap-1">
                <span className="inline-block w-2.5 h-2.5 bg-[#e12343] rounded-sm" /> 수익
              </span>
              <span className="flex items-center gap-1">
                <span className="inline-block w-2.5 h-2.5 bg-[#1261c4] rounded-sm" /> 손실
              </span>
            </div>
          </div>
        )}
      </div>

      {/* 초기화 버튼 */}
      <div className="text-center mt-4">
        <button
          onClick={handleReset}
          disabled={resetting}
          className="px-4 py-2 text-[12px] text-[#999] border border-[#ddd] rounded hover:text-[#e12343] hover:border-[#e12343] disabled:opacity-50 transition-colors"
        >
          {resetting ? '초기화 중...' : '포트폴리오 초기화'}
        </button>
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
        <div className="text-[13px] text-[#999]">인증 확인 중...</div>
      </div>
    );
  }

  if (!isAdmin) {
    return <AdminLogin onLogin={login} />;
  }

  const tabs: { key: Tab; label: string }[] = [
    { key: 'briefing', label: '데일리 브리핑' },
    { key: 'signals', label: '투자 시그널' },
    { key: 'accuracy', label: '적중률' },
    { key: 'portfolio', label: '포트폴리오' },
    { key: 'paper', label: '페이퍼 트레이딩' },
    { key: 'backtest', label: '백테스트' },
  ];

  return (
    <div>
      <div className="section-box mb-3">
        <div className="flex items-center justify-between px-4 py-3">
          <div>
            <h1 className="text-[16px] font-bold text-[#333]">AI Fund Manager</h1>
            <p className="text-[12px] text-[#999] mt-0.5">
              뉴스 + 공시 + 시세 + 재무제표를 종합 분석하는 AI 펀드매니저
            </p>
          </div>
          <button
            onClick={logout}
            className="text-[12px] text-[#999] hover:text-[#e12343]"
          >
            로그아웃
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
      {tab === 'paper' && <PaperTradingTab />}
      {tab === 'backtest' && <BacktestDashboard />}
    </div>
  );
}
