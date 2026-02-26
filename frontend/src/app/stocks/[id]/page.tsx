'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { fetchStockDetail, fetchStockNews, fetchStockPrices, fetchStockFinancials, fetchSentimentTrend, fetchStockDisclosures } from '@/lib/api';
import { formatSectorName } from '@/lib/format';
import type { StockDetail, NewsArticle, PriceRecord, FinancialPeriod, SentimentTrendItem, DisclosureItem } from '@/lib/types';
import Pagination from '@/components/Pagination';
import { useWatchlist } from '@/lib/watchlist';

const PAGE_SIZE = 30;

/* ─── Formatting helpers ─── */

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  return d.toLocaleDateString('ko-KR', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

function formatNumber(n: number | null | undefined): string {
  if (n == null) return '-';
  return n.toLocaleString('ko-KR');
}

function formatBillion(n: number | null | undefined): string {
  if (n == null) return '-';
  if (Math.abs(n) >= 10000) return `${(n / 10000).toFixed(1)}조`;
  return `${formatNumber(n)}억`;
}

function formatPercent(n: number | null | undefined): string {
  if (n == null) return '-';
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`;
}

function sentimentLabel(sentiment: string | null): { text: string; className: string } {
  switch (sentiment) {
    case 'positive': return { text: '호재', className: 'badge-positive' };
    case 'negative': return { text: '악재', className: 'badge-negative' };
    default: return { text: '중립', className: 'badge-neutral' };
  }
}

function sourceLabel(source: string): string {
  switch (source) {
    case 'naver': return '네이버';
    case 'google': return '구글';
    case 'yahoo': return 'Yahoo';
    case 'korean_rss': return '경제지';
    case 'us_news': return '미국';
    default: return source;
  }
}

/* ─── Candlestick Chart ─── */

function PriceChart({ prices }: { prices: PriceRecord[] }) {
  if (prices.length < 2) return <p className="text-[13px] text-[#999] py-8 text-center">차트 데이터가 부족합니다.</p>;

  const data = [...prices].reverse();
  const n = data.length;

  // Price range (use high/low for full range)
  const allHighs = data.map(p => p.high || p.close);
  const allLows = data.map(p => (p.low || p.close));
  const minP = Math.min(...allLows);
  const maxP = Math.max(...allHighs);
  const priceRange = maxP - minP || 1;

  // Volume range
  const volumes = data.map(p => p.volume);
  const maxVol = Math.max(...volumes, 1);

  // Layout constants
  const w = 800;
  const chartH = 240;       // candlestick area height
  const volH = 60;           // volume bar area height
  const gap = 8;             // gap between chart and volume
  const totalH = chartH + gap + volH;
  const padL = 60;           // left padding for price labels
  const padR = 10;
  const padT = 10;
  const padB = 25;           // bottom for date labels
  const chartAreaW = w - padL - padR;
  const candleW = Math.max(2, Math.min(8, (chartAreaW / n) * 0.7));
  const candleGap = chartAreaW / n;

  // Price → Y coordinate (in candlestick area)
  const priceY = (price: number) => padT + (1 - (price - minP) / priceRange) * (chartH - padT);

  // Volume → Y coordinate (in volume area)
  const volY = (vol: number) => chartH + gap + volH - (vol / maxVol) * volH;

  // Generate ~5 price ticks for the y-axis
  const priceTicks: number[] = [];
  const tickCount = 5;
  for (let i = 0; i <= tickCount; i++) {
    priceTicks.push(Math.round(minP + (priceRange * i) / tickCount));
  }

  return (
    <div className="px-4 py-3">
      <div className="flex items-center gap-3 mb-2">
        <span className="text-[12px] font-bold text-[#333]">주가 차트</span>
        <span className="flex items-center gap-1 text-[11px]">
          <span className="inline-block w-3 h-3 bg-[#e12343]" /> 상승
        </span>
        <span className="flex items-center gap-1 text-[11px]">
          <span className="inline-block w-3 h-3 bg-[#1261c4]" /> 하락
        </span>
      </div>
      <div className="overflow-x-auto">
        <svg viewBox={`0 0 ${w} ${totalH + padB}`} className="w-full" style={{ minWidth: 500, height: totalH + padB }}>
          {/* Price grid lines + labels */}
          {priceTicks.map((tick) => {
            const y = priceY(tick);
            return (
              <g key={`tick-${tick}`}>
                <line x1={padL} y1={y} x2={w - padR} y2={y} stroke="#eee" strokeWidth={1} />
                <text x={padL - 5} y={y + 3} textAnchor="end" fontSize={10} fill="#999">
                  {tick.toLocaleString()}
                </text>
              </g>
            );
          })}

          {/* Volume label */}
          <text x={padL - 5} y={chartH + gap + 10} textAnchor="end" fontSize={9} fill="#999">거래량</text>

          {/* Candlesticks + Volume bars */}
          {data.map((d, i) => {
            const cx = padL + i * candleGap + candleGap / 2;
            const isUp = d.close >= d.open;
            const color = isUp ? '#e12343' : '#1261c4';

            const bodyTop = priceY(Math.max(d.open, d.close));
            const bodyBot = priceY(Math.min(d.open, d.close));
            const bodyH = Math.max(1, bodyBot - bodyTop);

            const wickTop = priceY(d.high || Math.max(d.open, d.close));
            const wickBot = priceY(d.low || Math.min(d.open, d.close));

            const vTop = volY(d.volume);
            const vBot = chartH + gap + volH;

            // Date labels: show a few evenly spaced
            const showDate = i === 0 || i === n - 1 || (n > 10 && i % Math.ceil(n / 6) === 0);
            const dateLabel = d.date.replace(/\./g, '/').replace(/^20/, '');

            return (
              <g key={`c-${i}`}>
                {/* Wick (high-low line) */}
                <line x1={cx} y1={wickTop} x2={cx} y2={wickBot} stroke={color} strokeWidth={1} />
                {/* Candle body */}
                <rect
                  x={cx - candleW / 2}
                  y={bodyTop}
                  width={candleW}
                  height={bodyH}
                  fill={isUp ? color : color}
                  stroke={color}
                  strokeWidth={0.5}
                />
                {/* Volume bar */}
                <rect
                  x={cx - candleW / 2}
                  y={vTop}
                  width={candleW}
                  height={vBot - vTop}
                  fill={color}
                  opacity={0.35}
                />
                {/* Date label */}
                {showDate && (
                  <text
                    x={cx}
                    y={totalH + padB - 5}
                    textAnchor="middle"
                    fontSize={9}
                    fill="#999"
                  >
                    {dateLabel}
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      </div>
      <div className="flex justify-between text-[11px] text-[#999] mt-1">
        <span>최저 {formatNumber(minP)}원</span>
        <span>최고 {formatNumber(maxP)}원</span>
      </div>
    </div>
  );
}

/* ─── Sentiment Trend Chart ─── */

function SentimentChart({ data }: { data: SentimentTrendItem[] }) {
  if (data.length === 0) return <p className="text-[13px] text-[#999] py-8 text-center">감성 분석 데이터가 없습니다.</p>;

  const maxTotal = Math.max(...data.map(d => d.positive + d.negative + d.neutral), 1);
  const barW = Math.max(12, Math.min(32, 600 / data.length));
  const w = data.length * (barW + 4) + 40;
  const h = 150;

  return (
    <div className="px-4 py-3">
      <h3 className="text-[13px] font-bold text-[#333] mb-2">뉴스 감성 트렌드 (최근 30일)</h3>
      <div className="overflow-x-auto">
        <svg viewBox={`0 0 ${w} ${h + 30}`} className="w-full" style={{ minWidth: Math.min(w, 400), height: h + 30 }}>
          {data.map((d, i) => {
            const x = 20 + i * (barW + 4);
            const total = d.positive + d.negative + d.neutral;
            const scale = total > 0 ? h / maxTotal : 0;

            const negH = d.negative * scale;
            const neutralH = d.neutral * scale;
            const posH = d.positive * scale;

            return (
              <g key={d.date}>
                {/* Negative (bottom) */}
                <rect x={x} y={h - negH} width={barW} height={negH} fill="#1261c4" opacity={0.7} rx={1} />
                {/* Neutral (middle) */}
                <rect x={x} y={h - negH - neutralH} width={barW} height={neutralH} fill="#999" opacity={0.4} rx={1} />
                {/* Positive (top) */}
                <rect x={x} y={h - negH - neutralH - posH} width={barW} height={posH} fill="#e12343" opacity={0.7} rx={1} />
                {/* Date label (show every few) */}
                {(i === 0 || i === data.length - 1 || i % Math.ceil(data.length / 5) === 0) && (
                  <text x={x + barW / 2} y={h + 15} textAnchor="middle" fontSize={9} fill="#999">
                    {d.date.slice(5)}
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      </div>
      <div className="flex gap-4 justify-center mt-1 text-[11px]">
        <span className="flex items-center gap-1"><span className="inline-block w-3 h-3 rounded-sm bg-[#e12343] opacity-70" /> 호재</span>
        <span className="flex items-center gap-1"><span className="inline-block w-3 h-3 rounded-sm bg-[#999] opacity-40" /> 중립</span>
        <span className="flex items-center gap-1"><span className="inline-block w-3 h-3 rounded-sm bg-[#1261c4] opacity-70" /> 악재</span>
      </div>
    </div>
  );
}

/* ─── Financial table ─── */

function FinancialTable({ data, type }: { data: FinancialPeriod[]; type: 'annual' | 'quarter' }) {
  if (data.length === 0) return <p className="text-[13px] text-[#999] py-8 text-center">재무 데이터가 없습니다.</p>;

  const sumOrAvg = (
    items: FinancialPeriod[],
    key: keyof FinancialPeriod,
    mode: 'sum' | 'avg',
  ): string => {
    const vals = items.map(d => d[key]).filter((v): v is number => v != null);
    if (vals.length === 0) return '-';
    if (mode === 'avg') return (vals.reduce((a, b) => a + b, 0) / vals.length).toFixed(1);
    return formatNumber(vals.reduce((a, b) => a + b, 0));
  };

  return (
    <div className="overflow-x-auto">
      <table className="naver-table text-[12px]">
        <thead>
          <tr>
            <th className="text-left">{type === 'annual' ? '연도' : '분기'}</th>
            <th>매출액</th>
            <th>영업이익</th>
            <th>영업이익률</th>
            <th>순이익</th>
            <th>EPS</th>
            {type === 'annual' && <th>BPS</th>}
            {type === 'annual' && <th>ROE</th>}
          </tr>
        </thead>
        <tbody>
          {data.map((fp) => (
            <tr key={fp.period}>
              <td className="font-medium">{fp.period}</td>
              <td className="text-right">{fp.revenue != null ? formatBillion(fp.revenue) : '-'}</td>
              <td className={`text-right ${fp.operating_profit != null && fp.operating_profit < 0 ? 'text-[#1261c4]' : ''}`}>
                {fp.operating_profit != null ? formatBillion(fp.operating_profit) : '-'}
              </td>
              <td className="text-right">{fp.operating_margin != null ? `${fp.operating_margin.toFixed(1)}%` : '-'}</td>
              <td className={`text-right ${fp.net_income != null && fp.net_income < 0 ? 'text-[#1261c4]' : ''}`}>
                {fp.net_income != null ? formatBillion(fp.net_income) : '-'}
              </td>
              <td className="text-right">{fp.eps != null ? formatNumber(fp.eps) : '-'}</td>
              {type === 'annual' && <td className="text-right">{fp.bps != null ? formatNumber(fp.bps) : '-'}</td>}
              {type === 'annual' && <td className="text-right">{fp.roe != null ? `${fp.roe.toFixed(1)}%` : '-'}</td>}
            </tr>
          ))}
          <tr className="bg-[#f7f8fa] font-medium">
            <td>합계/평균</td>
            <td className="text-right">{sumOrAvg(data, 'revenue', 'sum')}</td>
            <td className="text-right">{sumOrAvg(data, 'operating_profit', 'sum')}</td>
            <td className="text-right">{sumOrAvg(data, 'operating_margin', 'avg')}%</td>
            <td className="text-right">{sumOrAvg(data, 'net_income', 'sum')}</td>
            <td className="text-right">-</td>
            {type === 'annual' && <td className="text-right">-</td>}
            {type === 'annual' && <td className="text-right">{sumOrAvg(data, 'roe', 'avg')}%</td>}
          </tr>
        </tbody>
      </table>
    </div>
  );
}

/* ─── Main Page ─── */

type Tab = 'indicators' | 'financials' | 'news' | 'disclosures';

export default function StockDetailPage() {
  const params = useParams();
  const stockId = Number(params.id);
  const { toggleStock, isWatched } = useWatchlist();

  const [detail, setDetail] = useState<StockDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(true);

  const [tab, setTab] = useState<Tab>('indicators');

  // Indicators tab
  const [prices, setPrices] = useState<PriceRecord[]>([]);
  const [pricesLoading, setPricesLoading] = useState(false);
  const [pricesLoaded, setPricesLoaded] = useState(false);
  const [sentimentTrend, setSentimentTrend] = useState<SentimentTrendItem[]>([]);
  const [sentimentLoaded, setSentimentLoaded] = useState(false);

  // Financials tab
  const [financials, setFinancials] = useState<{ annual: FinancialPeriod[]; quarter: FinancialPeriod[] } | null>(null);
  const [financialsLoading, setFinancialsLoading] = useState(false);
  const [financialsLoaded, setFinancialsLoaded] = useState(false);

  // News tab
  const [news, setNews] = useState<NewsArticle[]>([]);
  const [newsTotal, setNewsTotal] = useState(0);
  const [newsPage, setNewsPage] = useState(1);
  const [newsLoading, setNewsLoading] = useState(false);
  const [newsLoaded, setNewsLoaded] = useState(false);

  // Disclosures tab
  const [disclosures, setDisclosures] = useState<DisclosureItem[]>([]);
  const [disclosuresTotal, setDisclosuresTotal] = useState(0);
  const [disclosuresLoading, setDisclosuresLoading] = useState(false);
  const [disclosuresLoaded, setDisclosuresLoaded] = useState(false);

  // Load detail on mount
  useEffect(() => {
    if (!stockId) return;
    setDetailLoading(true);
    fetchStockDetail(stockId)
      .then(setDetail)
      .catch(() => {})
      .finally(() => setDetailLoading(false));
  }, [stockId]);

  // Lazy load tab data
  useEffect(() => {
    if (!stockId) return;

    if (tab === 'indicators' && !pricesLoaded) {
      setPricesLoading(true);
      fetchStockPrices(stockId, 3)
        .then((p) => { setPrices(p); setPricesLoaded(true); })
        .catch(() => {})
        .finally(() => setPricesLoading(false));
    }

    if (tab === 'indicators' && !sentimentLoaded) {
      fetchSentimentTrend(stockId)
        .then((d) => { setSentimentTrend(d); setSentimentLoaded(true); })
        .catch(() => {});
    }

    if (tab === 'financials' && !financialsLoaded) {
      setFinancialsLoading(true);
      fetchStockFinancials(stockId)
        .then((f) => { setFinancials(f); setFinancialsLoaded(true); })
        .catch(() => {})
        .finally(() => setFinancialsLoading(false));
    }

    if (tab === 'news' && !newsLoaded) {
      setNewsLoading(true);
      fetchStockNews(stockId, 0, PAGE_SIZE)
        .then((r) => { setNews(r.articles); setNewsTotal(r.total); setNewsLoaded(true); })
        .catch(() => {})
        .finally(() => setNewsLoading(false));
    }

    if (tab === 'disclosures' && !disclosuresLoaded) {
      setDisclosuresLoading(true);
      fetchStockDisclosures(stockId, 20)
        .then((r) => { setDisclosures(r.disclosures); setDisclosuresTotal(r.total); setDisclosuresLoaded(true); })
        .catch(() => {})
        .finally(() => setDisclosuresLoading(false));
    }
  }, [stockId, tab, pricesLoaded, sentimentLoaded, financialsLoaded, newsLoaded, disclosuresLoaded]);

  // News pagination
  useEffect(() => {
    if (!stockId || tab !== 'news' || newsPage === 1) return;
    setNewsLoading(true);
    window.scrollTo({ top: 0 });
    fetchStockNews(stockId, (newsPage - 1) * PAGE_SIZE, PAGE_SIZE)
      .then((r) => { setNews(r.articles); setNewsTotal(r.total); })
      .catch(() => {})
      .finally(() => setNewsLoading(false));
  }, [stockId, newsPage, tab]);

  const d = detail;
  const priceColor = d && d.change_rate != null ? (d.change_rate >= 0 ? 'text-[#e12343]' : 'text-[#1261c4]') : '';
  const newsTotalPages = Math.ceil(newsTotal / PAGE_SIZE);

  return (
    <div>
      {/* Breadcrumb */}
      <div className="flex items-center gap-1 text-[12px] text-[#999] mb-3">
        <Link href="/" className="hover:text-[#333] hover:underline">업종 현황</Link>
        <span>&rsaquo;</span>
        {d?.sector_id && (
          <>
            <Link href={`/sectors/${d.sector_id}`} className="hover:text-[#333] hover:underline">
              {d.sector_name ? formatSectorName(d.sector_name) : '섹터'}
            </Link>
            <span>&rsaquo;</span>
          </>
        )}
        <span className="text-[#333] font-medium">{d?.name || '종목 상세'}</span>
      </div>

      {/* Header: name + price */}
      <div className="section-box">
        {detailLoading ? (
          <div className="p-4">
            <div className="skeleton skeleton-text" style={{ width: '40%', height: 24 }} />
            <div className="skeleton skeleton-text mt-2" style={{ width: '25%', height: 18 }} />
          </div>
        ) : d ? (
          <div className="px-4 py-3 border-b border-[#e5e5e5]">
            <div className="flex items-baseline gap-3">
              <button
                onClick={() => toggleStock(d.id)}
                className={`text-[20px] leading-none transition-colors ${
                  isWatched(d.id) ? 'text-[#ffa723]' : 'text-[#ccc] hover:text-[#ffa723]'
                }`}
                title={isWatched(d.id) ? '관심종목 해제' : '관심종목 추가'}
              >
                {isWatched(d.id) ? '★' : '☆'}
              </button>
              <h1 className="text-[18px] font-bold text-[#333]">{d.name}</h1>
              <span className="text-[13px] text-[#999]">{d.stock_code}</span>
              {d.sector_name && (
                <Link
                  href={`/sectors/${d.sector_id}`}
                  className="badge badge-sector text-[11px]"
                >
                  {formatSectorName(d.sector_name)}
                </Link>
              )}
            </div>
            <div className="flex items-baseline gap-3 mt-1">
              <span className={`text-[22px] font-bold ${priceColor}`}>
                {d.current_price ? `${formatNumber(d.current_price)}원` : '-'}
              </span>
              {d.price_change != null && d.change_rate != null && (
                <span className={`text-[14px] ${priceColor}`}>
                  {d.price_change >= 0 ? '▲' : '▼'} {formatNumber(Math.abs(d.price_change))} ({formatPercent(d.change_rate)})
                </span>
              )}
            </div>
          </div>
        ) : (
          <div className="p-4 text-[#999]">종목 정보를 불러올 수 없습니다.</div>
        )}

        {/* Key metrics cards */}
        {d && !detailLoading && (
          <div className="grid grid-cols-3 sm:grid-cols-6 border-b border-[#e5e5e5]">
            {[
              { label: '시가총액', value: d.market_cap != null ? formatBillion(d.market_cap) : '-' },
              { label: 'PER', value: d.per != null && d.per > 0 ? d.per.toFixed(2) : '-' },
              { label: 'PBR', value: d.pbr != null && d.pbr > 0 ? d.pbr.toFixed(2) : '-' },
              { label: '배당수익률', value: d.dividend_yield != null && d.dividend_yield > 0 ? `${d.dividend_yield.toFixed(2)}%` : '-' },
              { label: '거래량', value: d.volume != null && d.volume > 0 ? formatNumber(d.volume) : '-' },
              { label: '외국인비율', value: d.foreign_ratio != null && d.foreign_ratio > 0 ? `${d.foreign_ratio.toFixed(1)}%` : '-' },
            ].map((m) => (
              <div key={m.label} className="px-3 py-2.5 text-center border-r border-[#e5e5e5] last:border-r-0">
                <div className="text-[11px] text-[#999]">{m.label}</div>
                <div className="text-[14px] font-semibold text-[#333] mt-0.5">{m.value}</div>
              </div>
            ))}
          </div>
        )}

        {/* Tabs */}
        <div className="flex border-b border-[#e5e5e5]">
          {([
            { key: 'indicators' as Tab, label: '투자지표' },
            { key: 'financials' as Tab, label: '재무실적' },
            { key: 'news' as Tab, label: '뉴스' },
            { key: 'disclosures' as Tab, label: '공시' },
          ]).map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`px-5 py-2.5 text-[13px] font-medium border-b-2 transition-colors ${
                tab === t.key
                  ? 'text-[#1261c4] border-[#1261c4]'
                  : 'text-[#999] border-transparent hover:text-[#333]'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* Tab content */}
        <div className="min-h-[300px]">
          {/* ─── Indicators Tab ─── */}
          {tab === 'indicators' && (
            <div>
              {d && (
                <div className="grid grid-cols-2 sm:grid-cols-4 border-b border-[#e5e5e5]">
                  {[
                    { label: 'EPS', value: d.eps != null && d.eps !== 0 ? `${formatNumber(d.eps)}원` : '-' },
                    { label: 'BPS', value: d.bps != null && d.bps !== 0 ? `${formatNumber(d.bps)}원` : '-' },
                    { label: '배당금', value: d.dividend != null && d.dividend > 0 ? `${formatNumber(d.dividend)}원` : '-' },
                    { label: '거래대금', value: d.trading_value != null && d.trading_value > 0 ? formatBillion(Math.round(d.trading_value / 1_0000_0000)) : '-' },
                  ].map((m) => (
                    <div key={m.label} className="px-3 py-2.5 text-center border-r border-[#e5e5e5] last:border-r-0">
                      <div className="text-[11px] text-[#999]">{m.label}</div>
                      <div className="text-[14px] font-semibold text-[#333] mt-0.5">{m.value}</div>
                    </div>
                  ))}
                </div>
              )}
              {pricesLoading ? (
                <div className="p-4">
                  <div className="skeleton" style={{ width: '100%', height: 200 }} />
                </div>
              ) : (
                <PriceChart prices={prices} />
              )}
              {sentimentLoaded && (
                <div className="border-t border-[#e5e5e5]">
                  <SentimentChart data={sentimentTrend} />
                </div>
              )}
            </div>
          )}

          {/* ─── Financials Tab ─── */}
          {tab === 'financials' && (
            <div className="p-4 space-y-6">
              {financialsLoading ? (
                <div>
                  <div className="skeleton skeleton-text mb-2" style={{ width: '20%' }} />
                  {Array.from({ length: 5 }).map((_, i) => (
                    <div key={i} className="skeleton skeleton-text mb-1" style={{ width: `${70 + Math.random() * 25}%` }} />
                  ))}
                </div>
              ) : financials ? (
                <>
                  <div>
                    <h3 className="text-[14px] font-bold text-[#333] mb-2">연간 실적</h3>
                    <FinancialTable data={financials.annual} type="annual" />
                  </div>
                  <div>
                    <h3 className="text-[14px] font-bold text-[#333] mb-2">분기별 실적</h3>
                    <FinancialTable data={financials.quarter} type="quarter" />
                  </div>
                </>
              ) : (
                <p className="text-[13px] text-[#999] py-8 text-center">재무 데이터를 불러올 수 없습니다.</p>
              )}
            </div>
          )}

          {/* ─── News Tab ─── */}
          {tab === 'news' && (
            <div>
              <table className="naver-table">
                <thead>
                  <tr>
                    <th className="text-left" style={{ width: '48%' }}>제목</th>
                    <th style={{ width: '8%' }}>구분</th>
                    <th style={{ width: '9%' }}>출처</th>
                    <th style={{ width: '15%' }}>관련</th>
                    <th style={{ width: '20%' }}>날짜</th>
                  </tr>
                </thead>
                <tbody>
                  {newsLoading ? (
                    Array.from({ length: 10 }).map((_, i) => (
                      <tr key={`sk-${i}`}>
                        <td><div className="skeleton skeleton-text" style={{ width: `${55 + Math.random() * 35}%` }} /></td>
                        <td className="text-center"><div className="skeleton skeleton-badge mx-auto" /></td>
                        <td className="text-center"><div className="skeleton skeleton-badge mx-auto" /></td>
                        <td className="text-center"><div className="skeleton skeleton-badge mx-auto" /></td>
                        <td className="text-center"><div className="skeleton skeleton-text-sm mx-auto" style={{ width: '80%' }} /></td>
                      </tr>
                    ))
                  ) : news.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="text-center py-8 text-[#999]">관련 뉴스가 없습니다.</td>
                    </tr>
                  ) : (
                    news.map((article) => {
                      const sentiment = sentimentLabel(article.sentiment);
                      return (
                        <tr key={article.id}>
                          <td>
                            <Link
                              href={`/news/${article.id}`}
                              className="text-[#333] hover:text-[#1261c4] hover:underline"
                            >
                              {article.title}
                            </Link>
                            {article.summary && (
                              <p className="text-[11px] text-[#999] mt-0.5 truncate max-w-[400px]">{article.summary}</p>
                            )}
                          </td>
                          <td className="text-center">
                            <span className={`badge ${sentiment.className}`}>{sentiment.text}</span>
                          </td>
                          <td className="text-center">
                            <span className="badge badge-source">{sourceLabel(article.source)}</span>
                          </td>
                          <td className="text-center">
                            {(() => {
                              const sectors = new Map<number, string>();
                              const stocks = new Map<number, string>();
                              for (const rel of article.relations) {
                                if (rel.sector_id && rel.sector_name) sectors.set(rel.sector_id, rel.sector_name);
                                if (rel.stock_id && rel.stock_name) stocks.set(rel.stock_id, rel.stock_name);
                              }
                              const tags: { key: string; label: string; cls: string }[] = [];
                              for (const [id, name] of sectors) tags.push({ key: `s${id}`, label: formatSectorName(name), cls: 'badge-sector' });
                              for (const [id, name] of stocks) tags.push({ key: `t${id}`, label: name, cls: 'badge-stock' });
                              return tags.slice(0, 3).map((t) => (
                                <span key={t.key} className={`badge ${t.cls} mr-1`}>{t.label}</span>
                              ));
                            })()}
                          </td>
                          <td className="text-center text-[12px] text-[#999]">{formatDate(article.published_at)}</td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
              {!newsLoading && news.length > 0 && (
                <Pagination currentPage={newsPage} totalPages={newsTotalPages} onPageChange={setNewsPage} />
              )}
            </div>
          )}

          {/* ─── Disclosures Tab ─── */}
          {tab === 'disclosures' && (
            <div>
              <table className="naver-table">
                <thead>
                  <tr>
                    <th className="text-left" style={{ width: '55%' }}>공시 제목</th>
                    <th style={{ width: '12%' }}>유형</th>
                    <th style={{ width: '15%' }}>날짜</th>
                    <th style={{ width: '18%' }}>원문</th>
                  </tr>
                </thead>
                <tbody>
                  {disclosuresLoading ? (
                    Array.from({ length: 8 }).map((_, i) => (
                      <tr key={`sk-${i}`}>
                        <td><div className="skeleton skeleton-text" style={{ width: `${55 + Math.random() * 35}%` }} /></td>
                        <td className="text-center"><div className="skeleton skeleton-badge mx-auto" /></td>
                        <td className="text-center"><div className="skeleton skeleton-text-sm mx-auto" style={{ width: '80%' }} /></td>
                        <td className="text-center"><div className="skeleton skeleton-badge mx-auto" /></td>
                      </tr>
                    ))
                  ) : disclosures.length === 0 ? (
                    <tr>
                      <td colSpan={4} className="text-center py-8 text-[#999]">
                        공시 내역이 없습니다.
                      </td>
                    </tr>
                  ) : (
                    disclosures.map((disc) => (
                      <tr key={disc.rcept_no}>
                        <td className="text-[13px]">{disc.report_name}</td>
                        <td className="text-center">
                          {disc.report_type && (
                            <span className="badge badge-neutral">{disc.report_type}</span>
                          )}
                        </td>
                        <td className="text-center text-[12px] text-[#999]">
                          {disc.rcept_dt ? `${disc.rcept_dt.slice(0, 4)}.${disc.rcept_dt.slice(4, 6)}.${disc.rcept_dt.slice(6, 8)}` : '-'}
                        </td>
                        <td className="text-center">
                          <a
                            href={disc.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-[12px] text-[#1261c4] hover:underline"
                          >
                            DART 원문
                          </a>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
