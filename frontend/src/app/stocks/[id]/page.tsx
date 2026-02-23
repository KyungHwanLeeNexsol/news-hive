"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { fetchStockNews } from "@/lib/api";
import type { NewsArticle } from "@/lib/types";
import NewsCard from "@/components/NewsCard";

export default function StockDetail() {
  const params = useParams();
  const stockId = Number(params.id);

  const [news, setNews] = useState<NewsArticle[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!stockId) return;
    fetchStockNews(stockId).then(setNews).catch(() => setError("뉴스 로딩 실패"));
  }, [stockId]);

  if (error) {
    return (
      <div className="p-4 bg-red-50 text-red-700 rounded-lg">{error}</div>
    );
  }

  return (
    <div>
      <div className="mb-6">
        <Link
          href="/"
          className="text-sm text-blue-600 hover:text-blue-800 mb-2 inline-block"
        >
          &larr; 대시보드
        </Link>
        <h1 className="text-2xl font-bold text-gray-900">종목 뉴스</h1>
      </div>

      <section>
        {news.length === 0 ? (
          <p className="text-gray-500 text-sm">관련 뉴스가 없습니다.</p>
        ) : (
          <div className="space-y-3">
            {news.map((article) => (
              <NewsCard key={article.id} article={article} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
