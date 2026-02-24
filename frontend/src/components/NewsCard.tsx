"use client";

import type { NewsArticle } from "@/lib/types";
import { formatSectorName } from "@/lib/format";

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "";
  const d = new Date(dateStr);
  return d.toLocaleDateString("ko-KR", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function sourceLabel(source: string): string {
  switch (source) {
    case "naver":
      return "네이버";
    case "google":
      return "구글";
    case "newsapi":
      return "NewsAPI";
    default:
      return source;
  }
}

function relevanceBadge(relevance: string) {
  if (relevance === "direct") {
    return (
      <span className="inline-block px-2 py-0.5 text-xs font-medium rounded bg-red-100 text-red-700">
        직접
      </span>
    );
  }
  return (
    <span className="inline-block px-2 py-0.5 text-xs font-medium rounded bg-yellow-100 text-yellow-700">
      간접
    </span>
  );
}

export default function NewsCard({ article }: { article: NewsArticle }) {
  return (
    <div className="bg-white rounded-lg border border-gray-200 p-4 hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between gap-2 mb-2">
        <a
          href={article.url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-base font-semibold text-gray-900 hover:text-blue-600 leading-snug"
        >
          {article.title}
        </a>
        <span className="shrink-0 text-xs px-2 py-0.5 rounded bg-gray-100 text-gray-500">
          {sourceLabel(article.source)}
        </span>
      </div>

      {article.summary && (
        <p className="text-sm text-gray-600 mb-3 line-clamp-2">
          {article.summary}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2 mb-2">
        {article.relations.map((rel, i) => (
          <span key={i} className="flex items-center gap-1">
            {relevanceBadge(rel.relevance)}
            <span className="text-xs text-gray-500">
              {rel.stock_name || (rel.sector_name && formatSectorName(rel.sector_name))}
            </span>
          </span>
        ))}
      </div>

      <p className="text-xs text-gray-400">
        {formatDate(article.published_at)}
      </p>
    </div>
  );
}
