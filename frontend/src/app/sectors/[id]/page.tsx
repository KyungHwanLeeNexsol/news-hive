"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { fetchSector, fetchSectorNews } from "@/lib/api";
import type { Sector, NewsArticle } from "@/lib/types";
import NewsCard from "@/components/NewsCard";

export default function SectorDetail() {
  const params = useParams();
  const sectorId = Number(params.id);

  const [sector, setSector] = useState<Sector | null>(null);
  const [news, setNews] = useState<NewsArticle[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!sectorId) return;
    fetchSector(sectorId).then(setSector).catch(() => setError("섹터 로딩 실패"));
    fetchSectorNews(sectorId).then(setNews).catch(() => {});
  }, [sectorId]);

  if (error) {
    return (
      <div className="p-4 bg-red-50 text-red-700 rounded-lg">{error}</div>
    );
  }

  if (!sector) {
    return <p className="text-gray-500">로딩 중...</p>;
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
        <h1 className="text-2xl font-bold text-gray-900">{sector.name}</h1>
      </div>

      <section className="mb-8">
        <h2 className="text-lg font-semibold text-gray-800 mb-3">
          종목 ({sector.stocks?.length ?? 0})
        </h2>
        {sector.stocks && sector.stocks.length > 0 ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {sector.stocks.map((stock) => (
              <Link
                key={stock.id}
                href={`/stocks/${stock.id}`}
                className="bg-white rounded-lg border border-gray-200 p-4 hover:shadow-md hover:border-blue-300 transition-all"
              >
                <h3 className="font-semibold text-gray-900">{stock.name}</h3>
                <p className="text-sm text-gray-500">{stock.stock_code}</p>
                {stock.keywords && stock.keywords.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-2">
                    {stock.keywords.map((kw, i) => (
                      <span
                        key={i}
                        className="text-xs px-2 py-0.5 bg-gray-100 text-gray-600 rounded"
                      >
                        {kw}
                      </span>
                    ))}
                  </div>
                )}
              </Link>
            ))}
          </div>
        ) : (
          <p className="text-gray-500 text-sm">
            등록된 종목이 없습니다.{" "}
            <Link href="/manage" className="text-blue-600 hover:underline">
              관리 페이지
            </Link>
            에서 추가하세요.
          </p>
        )}
      </section>

      <section>
        <h2 className="text-lg font-semibold text-gray-800 mb-3">
          섹터 뉴스
        </h2>
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
