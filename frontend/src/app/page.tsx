"use client";

import { useEffect, useState } from "react";
import { fetchSectors, fetchNews, refreshNews } from "@/lib/api";
import type { Sector, NewsArticle } from "@/lib/types";
import SectorCard from "@/components/SectorCard";
import NewsCard from "@/components/NewsCard";

export default function Dashboard() {
  const [sectors, setSectors] = useState<Sector[]>([]);
  const [news, setNews] = useState<NewsArticle[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchSectors().then(setSectors).catch(() => setError("섹터 로딩 실패"));
    fetchNews().then(setNews).catch(() => {});
  }, []);

  async function handleRefresh() {
    setRefreshing(true);
    try {
      await refreshNews();
      const updated = await fetchNews();
      setNews(updated);
    } catch {
      setError("뉴스 새로고침 실패");
    } finally {
      setRefreshing(false);
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-gray-900">대시보드</h1>
        <button
          onClick={handleRefresh}
          disabled={refreshing}
          className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {refreshing ? "수집 중..." : "뉴스 새로고침"}
        </button>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 text-red-700 rounded-lg text-sm">
          {error}
        </div>
      )}

      <section className="mb-8">
        <h2 className="text-lg font-semibold text-gray-800 mb-3">섹터 목록</h2>
        {sectors.length === 0 ? (
          <p className="text-gray-500 text-sm">등록된 섹터가 없습니다.</p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {sectors.map((sector) => (
              <SectorCard key={sector.id} sector={sector} />
            ))}
          </div>
        )}
      </section>

      <section>
        <h2 className="text-lg font-semibold text-gray-800 mb-3">
          최신 뉴스
        </h2>
        {news.length === 0 ? (
          <p className="text-gray-500 text-sm">
            수집된 뉴스가 없습니다. 종목을 추가하고 뉴스를 새로고침하세요.
          </p>
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
