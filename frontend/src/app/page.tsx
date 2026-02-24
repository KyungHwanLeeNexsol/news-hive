'use client';

import { useEffect, useState, useCallback } from 'react';
import Link from 'next/link';
import { fetchSectors, fetchNews, refreshNews } from '@/lib/api';
import type { Sector, NewsArticle } from '@/lib/types';
import { formatSectorName } from '@/lib/format';
import ChangeRate from '@/components/ChangeRate';
import LoadingBar from '@/components/LoadingBar';

const REFRESH_INTERVAL = 5 * 60 * 1000; // 5 minutes

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

export default function Dashboard() {
  const [sectors, setSectors] = useState<Sector[]>([]);
  const [news, setNews] = useState<NewsArticle[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [loading, setLoading] = useState(true);

  const loadData = useCallback(() => {
    setLoading(true);
    Promise.all([
      fetchSectors().then(setSectors).catch(() => {}),
      fetchNews().then(setNews).catch(() => {}),
    ]).finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    loadData();

    // Auto-refresh both sectors and news every 5 minutes
    const interval = setInterval(loadData, REFRESH_INTERVAL);
    return () => clearInterval(interval);
  }, [loadData]);

  async function handleRefresh() {
    setRefreshing(true);
    try {
      await refreshNews();
      const updated = await fetchNews();
      setNews(updated);
    } catch {
      // ignore
    } finally {
      setRefreshing(false);
    }
  }

  // Show all sectors (backend already sorts by change_rate desc)
  const visibleSectors = sectors;
  const totalStocks = visibleSectors.reduce((sum, s) => sum + (s.total_stocks ?? s.stock_count ?? 0), 0);

  if (loading) {
    return <LoadingBar loading={true} />;
  }

  return (
    <div className="flex gap-4">
      {/* Left: Sector table */}
      <div className="flex-1 min-w-0">
        <div className="section-box">
          <div className="section-title">
            <span>업종 현황</span>
            <span className="text-[12px] font-normal text-[#999]">
              {visibleSectors.length}개 업종 / {totalStocks}개 종목
            </span>
          </div>
          <table className="naver-table">
            <thead>
              <tr>
                <th className="text-left" style={{ width: '30%' }}>
                  업종명
                </th>
                <th style={{ width: '14%' }}>전일대비</th>
                <th style={{ width: '10%' }}>전체</th>
                <th style={{ width: '10%' }}>상승</th>
                <th style={{ width: '10%' }}>보합</th>
                <th style={{ width: '10%' }}>하락</th>
                <th style={{ width: '16%' }}>뉴스</th>
              </tr>
            </thead>
            <tbody>
              {visibleSectors.length === 0 ? (
                <tr>
                  <td colSpan={7} className="text-center py-8 text-[#999]">
                    {loading ? '업종 데이터를 불러오는 중...' : '등록된 업종이 없습니다.'}
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
                    <td className="text-center text-rise">{sector.rising_stocks ?? '-'}</td>
                    <td className="text-center text-[#333]">{sector.flat_stocks ?? '-'}</td>
                    <td className="text-center text-fall">{sector.falling_stocks ?? '-'}</td>
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
            {news.length === 0 ? (
              <div className="py-8 text-center text-[13px] text-[#999]">
                {loading ? '뉴스를 불러오는 중...' : '수집된 뉴스가 없습니다.'}
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
                      <span className="badge badge-source">{sourceLabel(article.source)}</span>
                      {article.relations.slice(0, 2).map((rel, i) => (
                        <span
                          key={i}
                          className={`badge ${rel.relevance === 'direct' ? 'badge-direct' : 'badge-indirect'}`}
                        >
                          {rel.stock_name || (rel.sector_name && formatSectorName(rel.sector_name))}
                        </span>
                      ))}
                      <span>{formatDate(article.published_at)}</span>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
          {news.length > 0 && (
            <div className="p-3 text-center border-t border-[#f0f0f0]">
              <Link href="/news" className="text-[12px] text-[#1261c4] hover:underline">
                뉴스 더보기 &rsaquo;
              </Link>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
