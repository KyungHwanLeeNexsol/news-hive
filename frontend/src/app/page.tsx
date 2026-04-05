'use client';

import { useEffect, useState, useCallback } from 'react';
import Link from 'next/link';
import { fetchSectors, fetchNews, fetchStocks, fetchDisclosures, refreshNews } from '@/lib/api';
import type { Sector, NewsArticle, StockListItem, DisclosureItem } from '@/lib/types';
import { formatSectorName } from '@/lib/format';
import ChangeRate from '@/components/ChangeRate';
import CommodityTicker from '@/components/CommodityTicker';
import UpDownBar from '@/components/UpDownBar';
import { useWatchlist } from '@/lib/watchlist';
import { useMarketRefresh } from '@/lib/useMarketRefresh';

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  return d.toLocaleDateString('ko-KR', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function sourceLabel(source: string): string {
  switch (source) {
    case 'naver':
      return '네이버';
    case 'google':
      return '구글';
    case 'yahoo':
      return 'Yahoo';
    case 'korean_rss':
      return '경제지';
    case 'us_news':
      return '미국';
    default:
      return source;
  }
}

function formatNumber(n: number | null | undefined): string {
  if (n == null) return '-';
  return n.toLocaleString('ko-KR');
}

export default function Dashboard() {
  const [sectors, setSectors] = useState<Sector[]>([]);
  const [news, setNews] = useState<NewsArticle[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [watchedStocks, setWatchedStocks] = useState<StockListItem[]>([]);
  const [recentDisclosures, setRecentDisclosures] = useState<DisclosureItem[]>([]);
  const { watchlist, toggleStock, isWatched } = useWatchlist();

  const loadData = useCallback(() => {
    setLoading(true);
    Promise.all([
      fetchSectors().then(setSectors).catch(() => {}),
      fetchNews(0, 20).then((r) => setNews(r.articles)).catch(() => {}),
      fetchDisclosures({ limit: 10 }).then((r) => setRecentDisclosures(r.disclosures)).catch(() => {}),
    ]).finally(() => setLoading(false));
  }, []);

  // Load watchlist stocks whenever watchlist changes
  useEffect(() => {
    if (watchlist.length === 0) {
      setWatchedStocks([]);
      return;
    }
    fetchStocks({ ids: watchlist.join(','), limit: watchlist.length })
      .then((r) => setWatchedStocks(r.stocks))
      .catch(() => {});
  }, [watchlist]);

  useEffect(() => { loadData(); }, [loadData]);

  // Auto-refresh: 15s during market hours, 5min otherwise
  useMarketRefresh(loadData);

  async function handleRefresh() {
    setRefreshing(true);
    try {
      await refreshNews();
      const { articles } = await fetchNews(0, 20);
      setNews(articles);
    } catch {
      // ignore
    } finally {
      setRefreshing(false);
    }
  }

  // Show all sectors (backend already sorts by change_rate desc)
  const visibleSectors = sectors;
  const totalStocks = visibleSectors.reduce((sum, s) => sum + (s.total_stocks ?? s.stock_count ?? 0), 0);

  return (
    <div>
      {/* 원자재 시세 티커 */}
      <CommodityTicker />

      {/* Watchlist widget — only show when there are watched stocks */}
      {watchedStocks.length > 0 && (
        <div className="section-box mb-3">
          <div className="section-title">
            <span>관심종목</span>
            <Link href="/stocks" className="text-[12px] font-normal text-[#1261c4] hover:underline">
              전체 종목 &rsaquo;
            </Link>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
            {watchedStocks.map((stock) => {
              const rate = stock.change_rate ?? 0;
              const priceColor = rate > 0 ? 'text-[#e12343]' : rate < 0 ? 'text-[#1261c4]' : 'text-[#333]';
              return (
                <div key={stock.id} className="px-3 py-2.5 border-r border-b border-[#e5e5e5] last:border-r-0 hover:bg-[#f7f8fa] transition-colors">
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => toggleStock(stock.id)}
                      className="text-[14px] leading-none text-[#ffa723] hover:text-[#ccc] transition-colors"
                      title="관심종목 해제"
                    >
                      ★
                    </button>
                    <Link
                      href={`/stocks/${stock.id}`}
                      className="text-[13px] font-medium text-[#333] hover:text-[#1261c4] truncate"
                    >
                      {stock.name}
                    </Link>
                  </div>
                  <div className={`text-[15px] font-bold mt-0.5 ${priceColor}`}>
                    {stock.current_price ? `${formatNumber(stock.current_price)}` : '-'}
                  </div>
                  <div className={`text-[12px] ${priceColor}`}>
                    {rate !== 0 ? `${rate > 0 ? '+' : ''}${rate.toFixed(2)}%` : '0.00%'}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

    <div className="flex gap-4">
      {/* Left: Sector table */}
      <div className="flex-1 min-w-0">
        <div className="section-box">
          <div className="section-title">
            <span>업종 현황</span>
            {!loading && (
              <span className="text-[12px] font-normal text-[#999]">
                {visibleSectors.length}개 업종 / {totalStocks}개 종목
              </span>
            )}
          </div>
          <table className="naver-table">
            <thead>
              <tr>
                <th className="text-left" style={{ width: '35%' }}>업종명</th>
                <th style={{ width: '15%' }}>전일대비</th>
                <th style={{ width: '8%' }}>전체</th>
                <th style={{ width: '26%' }}>상승/보합/하락</th>
                <th style={{ width: '16%' }}>뉴스</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                Array.from({ length: 10 }).map((_, i) => (
                  <tr key={`sk-${i}`}>
                    <td><div className="skeleton skeleton-text" style={{ width: `${50 + Math.random() * 30}%` }} /></td>
                    <td className="text-center"><div className="skeleton skeleton-badge mx-auto" /></td>
                    <td className="text-center"><div className="skeleton skeleton-text-sm mx-auto" style={{ width: '40%' }} /></td>
                    <td><div className="skeleton" style={{ height: '14px', borderRadius: '4px' }} /></td>
                    <td className="text-center"><div className="skeleton skeleton-text-sm mx-auto" style={{ width: '60%' }} /></td>
                  </tr>
                ))
              ) : visibleSectors.length === 0 ? (
                <tr>
                  <td colSpan={5} className="text-center py-8 text-[#999]">
                    등록된 업종이 없습니다.
                  </td>
                </tr>
              ) : (
                visibleSectors.map((sector) => (
                  <tr key={sector.id}>
                    <td>
                      <Link
                        href={`/sectors/${sector.id}`}
                        className="text-[#333] hover:text-[#1261c4] hover:underline font-medium"
                      >
                        {formatSectorName(sector.name)}
                      </Link>
                      {sector.is_custom && <span className="badge badge-source ml-1">커스텀</span>}
                    </td>
                    <td className="text-center">
                      <ChangeRate value={sector.change_rate} />
                    </td>
                    <td className="text-center text-[#333]">{sector.total_stocks ?? sector.stock_count ?? 0}</td>
                    <td className="px-2">
                      <UpDownBar
                        rising={sector.rising_stocks ?? 0}
                        flat={sector.flat_stocks ?? 0}
                        falling={sector.falling_stocks ?? 0}
                      />
                    </td>
                    <td className="text-center">
                      <Link href={`/sectors/${sector.id}`} className="text-[#1261c4] hover:underline text-[12px]">
                        뉴스보기
                      </Link>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Right: News sidebar */}
      <div className="w-[380px] shrink-0 hidden lg:block">
        <div className="section-box">
          <div className="section-title">
            <span>최신 뉴스</span>
            <button
              onClick={handleRefresh}
              disabled={refreshing}
              className="text-[12px] font-normal text-[#1261c4] hover:underline disabled:text-[#999]"
            >
              {refreshing ? '수집 중...' : '새로고침'}
            </button>
          </div>
          <div>
            {loading ? (
              Array.from({ length: 8 }).map((_, i) => (
                <div key={`sk-news-${i}`} className="news-item">
                  <div className="flex-1 min-w-0">
                    <div className="skeleton skeleton-text" style={{ width: `${60 + Math.random() * 30}%` }} />
                    <div className="flex items-center gap-2 mt-1.5">
                      <div className="skeleton skeleton-badge" style={{ width: '36px' }} />
                      <div className="skeleton skeleton-badge" />
                      <div className="skeleton skeleton-text-sm" style={{ width: '60px' }} />
                    </div>
                  </div>
                </div>
              ))
            ) : news.length === 0 ? (
              <div className="py-8 text-center text-[13px] text-[#999]">
                수집된 뉴스가 없습니다.
              </div>
            ) : (
              news.slice(0, 20).map((article) => (
                <div key={article.id} className="news-item">
                  <div className="flex-1 min-w-0">
                    <Link
                      href={`/news/${article.id}`}
                      className="news-title block truncate"
                    >
                      {article.title}
                    </Link>
                    <div className="news-meta flex items-center gap-2">
                      {(() => {
                        const sectors = new Map<number, string>();
                        const stocks = new Map<number, string>();
                        for (const rel of article.relations) {
                          if (rel.sector_id && rel.sector_name) sectors.set(rel.sector_id, rel.sector_name);
                          if (rel.stock_id && rel.stock_name) stocks.set(rel.stock_id, rel.stock_name);
                        }
                        const tags: { key: string; label: string; cls: string }[] = [];
                        for (const [id, name] of sectors) tags.push({ key: `s${id}`, label: formatSectorName(name), cls: "badge-sector" });
                        for (const [id, name] of stocks) tags.push({ key: `t${id}`, label: name, cls: "badge-stock" });
                        return tags.slice(0, 2).map((t) => (
                          <span key={t.key} className={`badge ${t.cls}`}>{t.label}</span>
                        ));
                      })()}
                      <span>{formatDate(article.published_at)}</span>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
          {!loading && news.length > 0 && (
            <div className="p-3 text-center border-t border-[#f0f0f0]">
              <Link href="/news" className="text-[12px] text-[#1261c4] hover:underline">
                뉴스 더보기 &rsaquo;
              </Link>
            </div>
          )}
        </div>

        {/* Recent Disclosures widget */}
        {recentDisclosures.length > 0 && (
          <div className="section-box mt-3">
            <div className="section-title">
              <span>최근 공시</span>
            </div>
            <div>
              {recentDisclosures.map((disc) => (
                <div key={disc.rcept_no} className="news-item">
                  <div className="flex-1 min-w-0">
                    <a
                      href={disc.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="news-title block truncate"
                    >
                      {disc.report_name}
                    </a>
                    <div className="news-meta flex items-center gap-2">
                      {disc.stock_name && (
                        <span className="badge badge-stock">{disc.stock_name}</span>
                      )}
                      {disc.report_type && (
                        <span className="badge badge-neutral">{disc.report_type}</span>
                      )}
                      <span>
                        {disc.rcept_dt ? `${disc.rcept_dt.slice(0, 4)}.${disc.rcept_dt.slice(4, 6)}.${disc.rcept_dt.slice(6, 8)}` : ''}
                      </span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
    </div>
  );
}
