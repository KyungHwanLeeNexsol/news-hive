"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { fetchNews, refreshNews } from "@/lib/api";
import { formatSectorName } from "@/lib/format";
import type { NewsArticle } from "@/lib/types";
import LoadingBar from "@/components/LoadingBar";
import Pagination from "@/components/Pagination";

const PAGE_SIZE = 30;

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "";
  const d = new Date(dateStr);
  return d.toLocaleDateString("ko-KR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function sentimentLabel(sentiment: string | null): { text: string; className: string } {
  switch (sentiment) {
    case "positive": return { text: "호재", className: "badge-positive" };
    case "negative": return { text: "악재", className: "badge-negative" };
    default: return { text: "중립", className: "badge-neutral" };
  }
}

export default function NewsPage() {
  const [news, setNews] = useState<NewsArticle[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [refreshing, setRefreshing] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetchNews((page - 1) * PAGE_SIZE, PAGE_SIZE)
      .then((r) => { setNews(r.articles); setTotal(r.total); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [page]);

  async function handleRefresh() {
    setRefreshing(true);
    try {
      await refreshNews();
      const r = await fetchNews(0, PAGE_SIZE);
      setNews(r.articles);
      setTotal(r.total);
      setPage(1);
    } catch {
      // ignore
    } finally {
      setRefreshing(false);
    }
  }

  const totalPages = Math.ceil(total / PAGE_SIZE);

  if (loading && news.length === 0) {
    return <LoadingBar loading={true} />;
  }

  return (
    <div className="section-box">
      <div className="section-title">
        <span>전체 뉴스 ({total}건)</span>
        <button
          onClick={handleRefresh}
          disabled={refreshing}
          className="px-3 py-1 text-[12px] bg-[#1261c4] text-white rounded hover:bg-[#0f54a8] disabled:opacity-50"
        >
          {refreshing ? "수집 중..." : "뉴스 새로고침"}
        </button>
      </div>
      <table className="naver-table">
        <thead>
          <tr>
            <th className="text-left" style={{ width: "50%" }}>제목</th>
            <th style={{ width: "7%" }}>구분</th>
            <th style={{ width: "23%" }}>관련 종목</th>
            <th style={{ width: "20%" }}>날짜</th>
          </tr>
        </thead>
        <tbody>
          {news.length === 0 ? (
            <tr>
              <td colSpan={4} className="text-center py-8 text-[#999]">
                수집된 뉴스가 없습니다. 뉴스 새로고침을 눌러주세요.
              </td>
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
                      <p className="text-[11px] text-[#999] mt-0.5 truncate max-w-[500px]">
                        {article.summary}
                      </p>
                    )}
                  </td>
                  <td className="text-center">
                    <span className={`badge ${sentiment.className}`}>
                      {sentiment.text}
                    </span>
                  </td>
                  <td className="text-center">
                    <div className="flex flex-wrap gap-1 justify-center">
                      {article.relations.slice(0, 3).map((rel, i) => (
                        <span
                          key={i}
                          className={`badge ${rel.relevance === "direct" ? "badge-direct" : "badge-indirect"}`}
                        >
                          {rel.stock_name || (rel.sector_name && formatSectorName(rel.sector_name))}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="text-center text-[#999] text-[12px]">
                    {formatDate(article.published_at)}
                  </td>
                </tr>
              );
            })
          )}
        </tbody>
      </table>
      <Pagination currentPage={page} totalPages={totalPages} onPageChange={setPage} />
    </div>
  );
}
