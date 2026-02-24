"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { fetchSectors, fetchNews, refreshNews } from "@/lib/api";
import type { Sector, NewsArticle } from "@/lib/types";
import ChangeRate from "@/components/ChangeRate";
import UpDownBar from "@/components/UpDownBar";

const REFRESH_INTERVAL = 5 * 60 * 1000; // 5 minutes

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "";
  const d = new Date(dateStr);
  return d.toLocaleDateString("ko-KR", {
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

export default function Dashboard() {
  const [sectors, setSectors] = useState<Sector[]>([]);
  const [news, setNews] = useState<NewsArticle[]>([]);
  const [refreshing, setRefreshing] = useState(false);

  const loadSectors = useCallback(() => {
    fetchSectors().then(setSectors).catch(() => {});
  }, []);

  useEffect(() => {
    loadSectors();
    fetchNews().then(setNews).catch(() => {});

    // Auto-refresh sectors every 5 minutes
    const interval = setInterval(loadSectors, REFRESH_INTERVAL);
    return () => clearInterval(interval);
  }, [loadSectors]);

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

  // Filter: only show sectors that have stocks in our DB
  const visibleSectors = sectors.filter(
    (s) => (s.stock_count ?? 0) > 0
  );
  const totalStocks = visibleSectors.reduce((sum, s) => sum + (s.stock_count ?? 0), 0);

  return (
    <div className="flex gap-4">
      {/* Left: Sector table */}
      <div className="flex-1 min-w-0">
        <div className="section-box">
          <div className="section-title">
            <span>업종별 뉴스</span>
            <span className="text-[12px] font-normal text-[#999]">
              {visibleSectors.length}개 업종 / {totalStocks}개 종목
            </span>
          </div>
          <table className="naver-table">
            <thead>
              <tr>
                <th className="text-left" style={{ width: "22%" }}>업종명</th>
                <th style={{ width: "12%" }}>전일대비</th>
                <th style={{ width: "8%" }}>전체</th>
                <th style={{ width: "8%" }}>상승</th>
                <th style={{ width: "8%" }}>보합</th>
                <th style={{ width: "8%" }}>하락</th>
                <th style={{ width: "22%" }}>등락그래프</th>
                <th style={{ width: "12%" }}>뉴스</th>
              </tr>
            </thead>
            <tbody>
              {visibleSectors.length === 0 ? (
                <tr>
                  <td colSpan={8} className="text-center py-8 text-[#999]">
                    등록된 업종이 없습니다.
                  </td>
                </tr>
              ) : (
                visibleSectors.map((sector) => (
                  <tr key={sector.id}>
                    <td>
                      <Link
                        href={`/sectors/${sector.id}`}
                        className="text-[#333] hover:text-[#03c75a] hover:underline font-medium"
                      >
                        {sector.name}
                      </Link>
                      {sector.is_custom && (
                        <span className="badge badge-source ml-1">커스텀</span>
                      )}
                    </td>
                    <td className="text-center">
                      <ChangeRate value={sector.change_rate} />
                    </td>
                    <td className="text-center text-[#333]">
                      {sector.stock_count ?? 0}
                    </td>
                    <td className="text-center text-rise">
                      {sector.rising_stocks ?? "-"}
                    </td>
                    <td className="text-center text-[#333]">
                      {sector.flat_stocks ?? "-"}
                    </td>
                    <td className="text-center text-fall">
                      {sector.falling_stocks ?? "-"}
                    </td>
                    <td className="px-2">
                      <UpDownBar
                        rising={sector.rising_stocks ?? 0}
                        flat={sector.flat_stocks ?? 0}
                        falling={sector.falling_stocks ?? 0}
                      />
                    </td>
                    <td className="text-center">
                      <Link
                        href={`/sectors/${sector.id}`}
                        className="text-[#1261c4] hover:underline text-[12px]"
                      >
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
              {refreshing ? "수집 중..." : "새로고침"}
            </button>
          </div>
          <div>
            {news.length === 0 ? (
              <div className="py-8 text-center text-[13px] text-[#999]">
                수집된 뉴스가 없습니다.
              </div>
            ) : (
              news.slice(0, 20).map((article) => (
                <div key={article.id} className="news-item">
                  <div className="flex-1 min-w-0">
                    <a
                      href={article.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="news-title block truncate"
                    >
                      {article.title}
                    </a>
                    <div className="news-meta flex items-center gap-2">
                      <span className="badge badge-source">
                        {sourceLabel(article.source)}
                      </span>
                      {article.relations.slice(0, 2).map((rel, i) => (
                        <span key={i} className={`badge ${rel.relevance === "direct" ? "badge-direct" : "badge-indirect"}`}>
                          {rel.stock_name || rel.sector_name}
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
