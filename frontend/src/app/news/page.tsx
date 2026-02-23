"use client";

import { useEffect, useState } from "react";
import { fetchNews, refreshNews } from "@/lib/api";
import type { NewsArticle } from "@/lib/types";

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

function sourceLabel(source: string): string {
  switch (source) {
    case "naver": return "네이버";
    case "google": return "구글";
    case "newsapi": return "NewsAPI";
    default: return source;
  }
}

export default function NewsPage() {
  const [news, setNews] = useState<NewsArticle[]>([]);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    fetchNews().then(setNews).catch(() => {});
  }, []);

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

  return (
    <div className="section-box">
      <div className="section-title">
        <span>전체 뉴스</span>
        <button
          onClick={handleRefresh}
          disabled={refreshing}
          className="px-3 py-1 text-[12px] bg-[#03c75a] text-white rounded hover:bg-[#02b350] disabled:opacity-50"
        >
          {refreshing ? "수집 중..." : "뉴스 새로고침"}
        </button>
      </div>
      <table className="naver-table">
        <thead>
          <tr>
            <th className="text-left" style={{ width: "50%" }}>제목</th>
            <th style={{ width: "10%" }}>출처</th>
            <th style={{ width: "20%" }}>관련 종목</th>
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
            news.map((article) => (
              <tr key={article.id}>
                <td>
                  <a
                    href={article.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-[#333] hover:text-[#03c75a] hover:underline"
                  >
                    {article.title}
                  </a>
                  {article.summary && (
                    <p className="text-[11px] text-[#999] mt-0.5 truncate max-w-[500px]">
                      {article.summary}
                    </p>
                  )}
                </td>
                <td className="text-center">
                  <span className="badge badge-source">{sourceLabel(article.source)}</span>
                </td>
                <td className="text-center">
                  <div className="flex flex-wrap gap-1 justify-center">
                    {article.relations.slice(0, 3).map((rel, i) => (
                      <span
                        key={i}
                        className={`badge ${rel.relevance === "direct" ? "badge-direct" : "badge-indirect"}`}
                      >
                        {rel.stock_name || rel.sector_name}
                      </span>
                    ))}
                  </div>
                </td>
                <td className="text-center text-[#999] text-[12px]">
                  {formatDate(article.published_at)}
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
