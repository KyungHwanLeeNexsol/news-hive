'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { fetchStockNews } from '@/lib/api';
import { formatSectorName } from '@/lib/format';
import type { NewsArticle } from '@/lib/types';
import LoadingBar from '@/components/LoadingBar';

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
    case 'newsapi':
      return 'NewsAPI';
    case 'korean_rss':
      return '경제지';
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
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!stockId) return;
    fetchStockNews(stockId)
      .then(setNews)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [stockId]);

  return (
    <>
    <LoadingBar loading={loading} />
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
          <span className="text-[12px] font-normal text-[#999]">{news.length}건</span>
        </div>
        {news.length === 0 ? (
          <div className="py-8 text-center text-[13px] text-[#999]">관련 뉴스가 없습니다.</div>
        ) : (
          <table className="naver-table">
            <thead>
              <tr>
                <th className="text-left" style={{ width: '48%' }}>
                  제목
                </th>
                <th style={{ width: '8%' }}>구분</th>
                <th style={{ width: '9%' }}>출처</th>
                <th style={{ width: '15%' }}>관련</th>
                <th style={{ width: '20%' }}>날짜</th>
              </tr>
            </thead>
            <tbody>
              {news.map((article) => {
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
                      {article.relations.slice(0, 2).map((rel, i) => (
                        <span
                          key={i}
                          className={`badge ${rel.relevance === 'direct' ? 'badge-direct' : 'badge-indirect'} mr-1`}
                        >
                          {rel.stock_name || (rel.sector_name && formatSectorName(rel.sector_name))}
                        </span>
                      ))}
                    </td>
                    <td className="text-center text-[12px] text-[#999]">{formatDate(article.published_at)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
    </>
  );
}
