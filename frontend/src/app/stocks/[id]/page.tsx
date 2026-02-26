'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { fetchStockDetail, fetchStockNews, fetchStockPrices, fetchStockFinancials } from '@/lib/api';
import { formatSectorName } from '@/lib/format';
import type { StockDetail, NewsArticle, PriceRecord, FinancialPeriod } from '@/lib/types';
import Pagination from '@/components/Pagination';

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

/* ─── Mini SVG line chart ─── */

function PriceChart({ prices }: { prices: PriceRecord[] }) {
  if (prices.length < 2) return <p className="text-[13px] text-[#999] py-8 text-center">차트 데이터가 부족합니다.</p>;

  const data = [...prices].reverse();
  const closes = data.map(p => p.close);
  const minP = Math.min(...closes);
  const maxP = Math.max(...closes);
  const range = maxP - minP || 1;

  const w = 700;
  const h = 200;
  const padX = 0;
  const padY = 10;

  const points = data.map((_, i) => {
    const x = padX + (i / (data.length - 1)) * (w - 2 * padX);
    const y = padY + (1 - (closes[i] - minP) / range) * (h - 2 * padY);
    return `${x},${y}`;
  });

  const first = closes[0];
  const last = closes[closes.length - 1];
  const color = last >= first ? '#e12343' : '#1261c4';

  const areaPath = `M${points[0]} ${points.join(' L')} L${w - padX},${h - padY} L${padX},${h - padY} Z`;

  return (
    <div className="px-4 py-3">
      <div className="flex justify-between text-[11px] text-[#999] mb-1">
        <span>{data[0].date}</span>
        <span>{data[data.length - 1].date}</span>
      </div>
      <svg viewBox={`0 0 ${w} ${h}`} className="w-full" style={{ height: 200 }}>
        <defs>
          <linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.15" />
            <stop offset="100%" stopColor={color} stopOpacity="0.01" />
          </linearGradient>
        </defs>
        <path d={areaPath} fill="url(#areaGrad)" />
        <polyline points={points.join(' ')} fill="none" stroke={color} strokeWidth="2" />
      </svg>
      <div className="flex justify-between text-[11px] text-[#999] mt-1">
        <span>최저 {formatNumber(minP)}원</span>
        <span>최고 {formatNumber(maxP)}원</span>
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

type Tab = 'indicators' | 'financials' | 'news';

export default function StockDetailPage() {
  const params = useParams();
  const stockId = Number(params.id);

  const [detail, setDetail] = useState<StockDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(true);

  const [tab, setTab] = useState<Tab>('indicators');

  // Indicators tab
  const [prices, setPrices] = useState<PriceRecord[]>([]);
  const [pricesLoading, setPricesLoading] = useState(false);
  const [pricesLoaded, setPricesLoaded] = useState(false);

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
  }, [stockId, tab, pricesLoaded, financialsLoaded, newsLoaded]);

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
              { label: '거래량', value: d.volume != null ? formatNumber(d.volume) : '-' },
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
                <div className="grid grid-cols-2 sm:grid-cols-5 border-b border-[#e5e5e5]">
                  {[
                    { label: 'EPS', value: d.eps != null ? `${formatNumber(d.eps)}원` : '-' },
                    { label: 'BPS', value: d.bps != null ? `${formatNumber(d.bps)}원` : '-' },
                    { label: '52주 최고', value: d.high_52w != null ? `${formatNumber(d.high_52w)}원` : '-' },
                    { label: '52주 최저', value: d.low_52w != null ? `${formatNumber(d.low_52w)}원` : '-' },
                    { label: '배당금', value: d.dividend != null && d.dividend > 0 ? `${formatNumber(d.dividend)}원` : '-' },
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
        </div>
      </div>
    </div>
  );
}
