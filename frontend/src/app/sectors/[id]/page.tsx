"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { fetchSector, fetchSectorNews } from "@/lib/api";
import { formatSectorName } from "@/lib/format";
import type { Sector, NewsArticle } from "@/lib/types";
import LoadingBar from "@/components/LoadingBar";
import ChangeRate from "@/components/ChangeRate";

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
    case "korean_rss": return "경제지";
    case "us_news": return "미국";
    default: return source;
  }
}

function sentimentLabel(sentiment: string | null): { text: string; className: string } {
  switch (sentiment) {
    case "positive": return { text: "호재", className: "badge-positive" };
    case "negative": return { text: "악재", className: "badge-negative" };
    default: return { text: "중립", className: "badge-neutral" };
  }
}

export default function SectorDetail() {
  const params = useParams();
  const sectorId = Number(params.id);

  const [sector, setSector] = useState<Sector | null>(null);
  const [news, setNews] = useState<NewsArticle[]>([]);
  const [tab, setTab] = useState<"stocks" | "news">("news");

  useEffect(() => {
    if (!sectorId) return;
    fetchSector(sectorId).then(setSector).catch(() => {});
    fetchSectorNews(sectorId).then(setNews).catch(() => {});
  }, [sectorId]);

  if (!sector) {
    return <LoadingBar loading={true} />;
  }

  return (
    <div>
      {/* Breadcrumb */}
      <div className="flex items-center gap-1 text-[12px] text-[#999] mb-3">
        <Link href="/" className="hover:text-[#333] hover:underline">
          업종별 뉴스
        </Link>
        <span>&rsaquo;</span>
        <span className="text-[#333] font-medium">{formatSectorName(sector.name)}</span>
      </div>

      {/* Tab nav */}
      <div className="tab-nav">
        <button
          className={`tab-item ${tab === "news" ? "active" : ""}`}
          onClick={() => setTab("news")}
        >
          뉴스 ({news.length})
        </button>
        <button
          className={`tab-item ${tab === "stocks" ? "active" : ""}`}
          onClick={() => setTab("stocks")}
        >
          종목 ({sector.stocks?.length ?? 0})
        </button>
      </div>

      {/* Tab content */}
      {tab === "stocks" ? (
        <div className="section-box" style={{ borderTop: "none" }}>
          <table className="naver-table">
            <thead>
              <tr>
                <th className="text-left" style={{ width: "8%" }}>번호</th>
                <th className="text-left" style={{ width: "42%" }}>종목명</th>
                <th style={{ width: "20%" }}>등락률</th>
                <th style={{ width: "30%" }}>개별뉴스</th>
              </tr>
            </thead>
            <tbody>
              {!sector.stocks || sector.stocks.length === 0 ? (
                <tr>
                  <td colSpan={4} className="text-center py-8 text-[#999]">
                    등록된 종목이 없습니다.{" "}
                    <Link href="/manage" className="text-[#1261c4] hover:underline">
                      관리 페이지
                    </Link>
                    에서 추가하세요.
                  </td>
                </tr>
              ) : (
                sector.stocks.map((stock, i) => (
                  <tr key={stock.id}>
                    <td className="text-center text-[#999]">{i + 1}</td>
                    <td>
                      <Link
                        href={`/stocks/${stock.id}`}
                        className="text-[#333] hover:text-[#1261c4] hover:underline font-medium"
                      >
                        {stock.name}
                      </Link>
                    </td>
                    <td className="text-center">
                      <ChangeRate value={stock.change_rate} />
                    </td>
                    <td className="text-center">
                      {(stock.news_count ?? 0) > 0 ? (
                        <Link
                          href={`/stocks/${stock.id}`}
                          className="text-[#1261c4] hover:underline text-[12px]"
                        >
                          {stock.news_count}건
                        </Link>
                      ) : (
                        <span className="text-[#ccc] text-[12px]">-</span>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="section-box" style={{ borderTop: "none" }}>
          {news.length === 0 ? (
            <div className="py-8 text-center text-[13px] text-[#999]">
              관련 뉴스가 없습니다.
            </div>
          ) : (
            <table className="naver-table">
              <thead>
                <tr>
                  <th className="text-left" style={{ width: "48%" }}>제목</th>
                  <th style={{ width: "8%" }}>구분</th>
                  <th style={{ width: "9%" }}>출처</th>
                  <th style={{ width: "15%" }}>관련</th>
                  <th style={{ width: "20%" }}>날짜</th>
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
                      </td>
                      <td className="text-center">
                        <span className={`badge ${sentiment.className}`}>
                          {sentiment.text}
                        </span>
                      </td>
                      <td className="text-center">
                        <span className="badge badge-source">
                          {sourceLabel(article.source)}
                        </span>
                      </td>
                      <td className="text-center">
                        {article.relations.slice(0, 2).map((rel, i) => (
                          <span
                            key={i}
                            className={`badge ${rel.relevance === "direct" ? "badge-direct" : "badge-indirect"} mr-1`}
                          >
                            {rel.stock_name || (rel.sector_name && formatSectorName(rel.sector_name))}
                          </span>
                        ))}
                      </td>
                      <td className="text-center text-[12px] text-[#999]">
                        {formatDate(article.published_at)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
