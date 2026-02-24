'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { fetchNewsById, generateAiSummary, scrapeArticleContent } from '@/lib/api';
import { formatSectorName } from '@/lib/format';
import type { NewsArticle } from '@/lib/types';
import LoadingBar from '@/components/LoadingBar';

function formatDate(dateStr: string | null): string {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  return d.toLocaleDateString('ko-KR', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
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

function sentimentLabel(sentiment: string | null): { text: string; className: string } {
  switch (sentiment) {
    case 'positive': return { text: '호재', className: 'badge-positive' };
    case 'negative': return { text: '악재', className: 'badge-negative' };
    default: return { text: '중립', className: 'badge-neutral' };
  }
}

/** Strip HTML tags and decode common entities */
function stripHtml(html: string): string {
  return html
    .replace(/<[^>]*>/g, '')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/\s+/g, ' ')
    .trim();
}

export default function NewsDetail() {
  const params = useParams();
  const newsId = Number(params.id);
  const [article, setArticle] = useState<NewsArticle | null>(null);
  const [aiSummary, setAiSummary] = useState<string | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [articleContent, setArticleContent] = useState<string | null>(null);
  const [contentLoading, setContentLoading] = useState(false);
  const [contentFailed, setContentFailed] = useState(false);
  const [bodyOpen, setBodyOpen] = useState(false);

  useEffect(() => {
    if (!newsId) return;
    fetchNewsById(newsId)
      .then((data) => {
        setArticle(data);

        // AI summary: use cached or generate
        if (data.ai_summary) {
          setAiSummary(data.ai_summary);
        } else {
          setSummaryLoading(true);
          generateAiSummary(newsId)
            .then((result) => setAiSummary(result.ai_summary))
            .catch(() => {})
            .finally(() => setSummaryLoading(false));
        }

        // Article content: use cached only (scraping deferred to when user opens body)
        if (data.content) {
          setArticleContent(data.content);
        }
      })
      .catch(() => {});
  }, [newsId]);

  if (!article) {
    return <LoadingBar loading={true} />;
  }

  const sentiment = sentimentLabel(article.sentiment);
  const cleanSummary = article.summary ? stripHtml(article.summary) : null;

  return (
    <div className="max-w-[860px]">
      {/* Breadcrumb */}
      <div className="flex items-center gap-1 text-[12px] text-[#999] mb-3">
        <Link href="/news" className="hover:text-[#333] hover:underline">
          전체 뉴스
        </Link>
        <span>&rsaquo;</span>
        <span className="text-[#333] font-medium truncate max-w-[500px]">
          {article.title}
        </span>
      </div>

      {/* Article card */}
      <div className="section-box">
        {/* Header area */}
        <div className="p-5 pb-4 border-b border-[#e5e5e5]">
          <h1 className="text-[18px] font-bold text-[#333] leading-snug mb-3">
            {article.title}
          </h1>
          <div className="flex flex-wrap items-center gap-2 text-[12px]">
            <span className={`badge ${sentiment.className}`}>{sentiment.text}</span>
            <span className="badge badge-source">{sourceLabel(article.source)}</span>
            <span className="text-[#999]">{formatDate(article.published_at)}</span>
          </div>
        </div>

        {/* Body area */}
        <div className="p-5">
          {/* Related stocks/sectors */}
          {article.relations.length > 0 && (() => {
            // Deduplicate: collect unique sectors and stocks
            const sectorMap = new Map<number, { name: string; relevance: string }>();
            const stockMap = new Map<number, { name: string; relevance: string; sectorId: number | null }>();
            for (const rel of article.relations) {
              if (rel.sector_id && rel.sector_name && !sectorMap.has(rel.sector_id)) {
                sectorMap.set(rel.sector_id, { name: rel.sector_name, relevance: rel.relevance });
              }
              if (rel.stock_id && rel.stock_name && !stockMap.has(rel.stock_id)) {
                stockMap.set(rel.stock_id, { name: rel.stock_name, relevance: rel.relevance, sectorId: rel.sector_id });
              }
            }
            const sectors = Array.from(sectorMap.entries());
            const stocks = Array.from(stockMap.entries());

            return (
              <div className="mb-5">
                <div className="text-[12px] font-semibold text-[#666] mb-2">관련 종목/섹터</div>
                <div className="flex flex-wrap gap-1.5">
                  {sectors.map(([id, s]) => (
                    <Link
                      key={`sector-${id}`}
                      href={`/sectors/${id}`}
                      className="badge badge-indirect hover:opacity-80 px-2 py-0.5"
                    >
                      {formatSectorName(s.name)}
                    </Link>
                  ))}
                  {stocks.map(([id, s]) => (
                    <Link
                      key={`stock-${id}`}
                      href={`/stocks/${id}`}
                      className={`badge ${s.relevance === 'direct' ? 'badge-direct' : 'badge-indirect'} hover:opacity-80 px-2 py-0.5`}
                    >
                      {s.name}
                    </Link>
                  ))}
                </div>
              </div>
            );
          })()}

          {/* AI Summary */}
          <div className="mb-5 p-4 bg-[#f0f7ff] rounded-md border border-[#d0e3f7]">
            <div className="flex items-center gap-1.5 mb-2.5">
              <span className="text-[13px] font-bold text-[#1261c4]">AI 분석 요약</span>
            </div>
            {summaryLoading ? (
              <div className="text-[13px] text-[#999] flex items-center gap-2">
                <span className="inline-block w-3.5 h-3.5 border-2 border-[#1261c4] border-t-transparent rounded-full animate-spin" />
                AI 요약을 생성하고 있습니다...
              </div>
            ) : aiSummary ? (
              <div className="text-[13px] text-[#333] leading-[1.9] whitespace-pre-line">
                {aiSummary}
              </div>
            ) : (
              <div className="text-[13px] text-[#999]">
                AI 요약을 생성할 수 없습니다.
              </div>
            )}
          </div>

          {/* Link to original article */}
          <div className="mb-5">
            <a
              href={article.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-[13px] text-[#1261c4] hover:underline"
            >
              기사 원문 보기 &rsaquo;
            </a>
          </div>

          {/* Article content (collapsible) */}
          <div className="mb-5">
            <button
              onClick={() => {
                const opening = !bodyOpen;
                setBodyOpen(opening);
                if (opening && !articleContent && !contentLoading && !contentFailed) {
                  setContentLoading(true);
                  scrapeArticleContent(newsId)
                    .then((result) => {
                      if (result.content) {
                        setArticleContent(result.content);
                      } else {
                        setContentFailed(true);
                      }
                    })
                    .catch(() => setContentFailed(true))
                    .finally(() => setContentLoading(false));
                }
              }}
              className="flex items-center gap-2 text-[13px] font-bold text-[#333] cursor-pointer hover:text-[#1261c4]"
            >
              <span
                className="inline-block transition-transform duration-200"
                style={{ transform: bodyOpen ? 'rotate(90deg)' : 'rotate(0deg)' }}
              >
                &#9654;
              </span>
              기사 본문
            </button>
            {bodyOpen && (
              <div className="mt-3">
                {contentLoading ? (
                  <div className="p-6 text-center text-[13px] text-[#999] bg-[#fafafa] rounded-md border border-[#eee]">
                    <span className="inline-block w-3.5 h-3.5 border-2 border-[#999] border-t-transparent rounded-full animate-spin mr-2 align-middle" />
                    기사 본문을 가져오고 있습니다...
                  </div>
                ) : articleContent ? (
                  <div className="p-4 bg-[#fafafa] rounded-md border border-[#eee] text-[13px] text-[#333] leading-[2] whitespace-pre-line max-h-[600px] overflow-y-auto">
                    {articleContent}
                  </div>
                ) : contentFailed ? (
                  <div className="p-6 text-center bg-[#fafafa] rounded-md border border-[#eee]">
                    <div className="text-[13px] text-[#999] mb-3">
                      해당 뉴스 사이트에서 본문을 가져올 수 없습니다.
                    </div>
                    <a
                      href={article.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 px-4 py-2 bg-[#1261c4] text-white text-[13px] rounded-md hover:bg-[#0e4fa0] transition-colors"
                    >
                      원문 사이트에서 보기 &rsaquo;
                    </a>
                  </div>
                ) : null}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
