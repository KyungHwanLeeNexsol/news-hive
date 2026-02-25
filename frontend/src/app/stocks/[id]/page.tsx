'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { fetchStockNews } from '@/lib/api';
import { formatSectorName } from '@/lib/format';
import type { NewsArticle } from '@/lib/types';
import Pagination from '@/components/Pagination';

const PAGE_SIZE = 30;

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

function sentimentLabel(sentiment: string | null): { text: string; className: string } {
  switch (sentiment) {
    case 'positive':
      return { text: '호재', className: 'badge-positive' };
    case 'negative':
      return { text: '악재', className: 'badge-negative' };
    default:
      return { text: '중립', className: 'badge-neutral' };
  }
}

export default function StockDetail() {
  const params = useParams();
  const stockId = Number(params.id);

  const [news, setNews] = useState<NewsArticle[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!stockId) return;
    setLoading(true);
    window.scrollTo({ top: 0 });
    fetchStockNews(stockId, (page - 1) * PAGE_SIZE, PAGE_SIZE)
      .then((r) => { setNews(r.articles); setTotal(r.total); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [stockId, page]);

  const totalPages = Math.ceil(total / PAGE_SIZE);

  return (
    <div>
      {/* Breadcrumb */}
      <div className="flex items-center gap-1 text-[12px] text-[#999] mb-3">
        <Link href="/" className="hover:text-[#333] hover:underline">
          업종 현황
        </Link>
        <span>&rsaquo;</span>
        <span className="text-[#333] font-medium">종목 뉴스</span>
      </div>

      <div className="section-box">
        <div className="section-title">
          <span>종목 관련 뉴스</span>
          {!loading && <span className="text-[12px] font-normal text-[#999]">{total}건</span>}
        </div>
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
            {loading ? (
              Array.from({ length: 15 }).map((_, i) => (
                <tr key={`sk-${i}`}>
                  <td>
                    <div className="skeleton skeleton-text" style={{ width: `${55 + Math.random() * 35}%` }} />
                    <div className="skeleton skeleton-text-sm" style={{ width: `${35 + Math.random() * 20}%` }} />
                  </td>
                  <td className="text-center"><div className="skeleton skeleton-badge mx-auto" /></td>
                  <td className="text-center"><div className="skeleton skeleton-badge mx-auto" /></td>
                  <td className="text-center">
                    <div className="flex gap-1 justify-center">
                      <div className="skeleton skeleton-badge" />
                    </div>
                  </td>
                  <td className="text-center"><div className="skeleton skeleton-text-sm mx-auto" style={{ width: "80%" }} /></td>
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
                        for (const [id, name] of sectors) tags.push({ key: `s${id}`, label: formatSectorName(name), cls: "badge-sector" });
                        for (const [id, name] of stocks) tags.push({ key: `t${id}`, label: name, cls: "badge-stock" });
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
        {!loading && news.length > 0 && (
          <Pagination currentPage={page} totalPages={totalPages} onPageChange={setPage} />
        )}
      </div>
    </div>
  );
}
