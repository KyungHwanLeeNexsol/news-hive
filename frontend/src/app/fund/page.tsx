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
} from '@/lib/api';
import type { FundSignal, DailyBriefing, PortfolioReport, StockListItem } from '@/lib/types';
import { useWatchlist } from '@/lib/watchlist';

type Tab = 'briefing' | 'signals' | 'portfolio';

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

  if (!briefing) {
    return (
      <div className="section-box p-8 text-center">
        <div className="text-[40px] mb-3">&#x1F4CA;</div>
        <p className="text-[15px] text-[#333] font-medium mb-1">오늘의 AI 브리핑이 아직 없습니다</p>
        <p className="text-[13px] text-[#999] mb-4">
          AI가 최근 뉴스, 공시, 매크로 데이터를 종합 분석하여<br />
          전문 펀드매니저 수준의 시장 브리핑을 생성합니다.
        </p>
        <button
          onClick={handleGenerate}
          disabled={generating}
          className="px-5 py-2 bg-[#1261c4] text-white text-[13px] font-medium rounded hover:bg-[#0d4e9e] disabled:bg-[#999]"
        >
          {generating ? 'AI 분석 중...' : '오늘의 브리핑 생성'}
        </button>
      </div>
    );
  }

  const sections = [
    { title: '시장 전망', content: briefing.market_overview, icon: '\u{1F30D}' },
    { title: '주목 섹터', content: briefing.sector_highlights, icon: '\u{1F3AF}' },
    { title: '오늘의 픽', content: briefing.stock_picks, icon: '\u{2B50}' },
    { title: '리스크 평가', content: briefing.risk_assessment, icon: '\u{26A0}\u{FE0F}' },
    { title: '투자 전략', content: briefing.strategy, icon: '\u{1F4DD}' },
  ];

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <div>
          <span className="text-[13px] text-[#999]">
            {briefing.briefing_date} 브리핑
          </span>
        </div>
        <button
          onClick={() => handleGenerate(true)}
          disabled={generating}
          className="text-[12px] text-[#1261c4] hover:underline disabled:text-[#999]"
        >
          {generating ? '생성 중...' : '다시 생성'}
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
      alert('분석에 실패했습니다.');
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
      {/* Quick analyze buttons for watchlist */}
      {watchedStocks.length > 0 && (
        <div className="section-box mb-3">
          <div className="section-title">
            <span>관심종목 분석</span>
          </div>
          <div className="p-3 flex flex-wrap gap-2">
            {watchedStocks.map((stock) => (
              <button
                key={stock.id}
                onClick={() => handleAnalyze(stock.id)}
                disabled={analyzing === stock.id}
                className="px-3 py-1.5 text-[12px] border border-[#ddd] rounded hover:border-[#1261c4] hover:text-[#1261c4] disabled:text-[#999] disabled:border-[#eee] transition-colors"
              >
                {analyzing === stock.id ? '분석 중...' : stock.name}
              </button>
            ))}
          </div>
        </div>
      )}

      {signals.length === 0 ? (
        <div className="section-box p-8 text-center">
          <p className="text-[15px] text-[#333] font-medium mb-1">생성된 투자 시그널이 없습니다</p>
          <p className="text-[13px] text-[#999]">
            위 관심종목을 클릭하거나, 종목 상세 페이지에서 AI 분석을 요청하세요.
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
                  <div className="flex items-center gap-3">
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
                  <div className="flex justify-end">
                    <button
                      onClick={(e) => { e.stopPropagation(); handleAnalyze(signal.stock_id); }}
                      disabled={analyzing === signal.stock_id}
                      className="text-[12px] text-[#1261c4] hover:underline disabled:text-[#999]"
                    >
                      {analyzing === signal.stock_id ? '재분석 중...' : '재분석'}
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

  const sections = [
    { title: '종합 평가', content: report.overall_assessment, icon: '\u{1F4CA}' },
    { title: '리스크 분석', content: report.risk_analysis, icon: '\u{26A0}\u{FE0F}' },
    { title: '섹터 분산도', content: report.sector_balance, icon: '\u{1F3AF}' },
    { title: '리밸런싱 제안', content: report.rebalancing, icon: '\u{1F504}' },
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
  const [tab, setTab] = useState<Tab>('briefing');

  const tabs: { key: Tab; label: string }[] = [
    { key: 'briefing', label: '데일리 브리핑' },
    { key: 'signals', label: '투자 시그널' },
    { key: 'portfolio', label: '포트폴리오' },
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
      {tab === 'portfolio' && <PortfolioTab />}
    </div>
  );
}
