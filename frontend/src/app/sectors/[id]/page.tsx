"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { fetchSector, fetchSectorNews } from "@/lib/api";
import { formatSectorName } from "@/lib/format";
import type { Sector, NewsArticle } from "@/lib/types";
import ChangeRate from "@/components/ChangeRate";
import Pagination from "@/components/Pagination";

const PAGE_SIZE = 30;

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
  const [newsTotal, setNewsTotal] = useState(0);
  const [newsPage, setNewsPage] = useState(1);
  const [tab, setTab] = useState<"stocks" | "news">("news");
  const [sectorLoading, setSectorLoading] = useState(true);
  const [newsLoading, setNewsLoading] = useState(true);

  useEffect(() => {
    if (!sectorId) return;
    setSectorLoading(true);
    fetchSector(sectorId).then(setSector).catch(() => {}).finally(() => setSectorLoading(false));
  }, [sectorId]);

  useEffect(() => {
    if (!sectorId) return;
    setNewsLoading(true);
    window.scrollTo({ top: 0 });
    fetchSectorNews(sectorId, (newsPage - 1) * PAGE_SIZE, PAGE_SIZE)
      .then((r) => { setNews(r.articles); setNewsTotal(r.total); })
      .catch(() => {})
      .finally(() => setNewsLoading(false));
  }, [sectorId, newsPage]);

  const newsTotalPages = Math.ceil(newsTotal / PAGE_SIZE);

  return (
    <div>
      {/* Breadcrumb */}
      <div className="flex items-center gap-1 text-[12px] text-[#999] mb-3">
        <Link href="/" className="hover:text-[#333] hover:underline">
          업종별 뉴스
        </Link>
        <span>&rsaquo;</span>
        {sectorLoading ? (
          <div className="skeleton skeleton-text" style={{ width: '80px', display: 'inline-block' }} />
        ) : (
          <span className="text-[#333] font-medium">{sector ? formatSectorName(sector.name) : ""}</span>
        )}
      </div>

      {/* Tab nav */}
      <div className="tab-nav">
        <button
          className={`tab-item ${tab === "news" ? "active" : ""}`}
          onClick={() => setTab("news")}
        >
          뉴스 {!newsLoading && `(${newsTotal})`}
        </button>
        <button
          className={`tab-item ${tab === "stocks" ? "active" : ""}`}
          onClick={() => setTab("stocks")}
        >
          종목 {!sectorLoading && `(${sector?.stocks?.length ?? 0})`}
        </button>
      </div>

      {/* Tab content */}
      {tab === "stocks" ? (
        <div className="section-box" style={{ borderTop: "none", overflowX: "auto" }}>
          <table className="naver-table" style={{ minWidth: "900px" }}>
            <thead>
              <tr>
                <th className="text-left" style={{ width: "14%" }}>종목명</th>
                <th style={{ width: "8%" }}>현재가</th>
                <th style={{ width: "9%" }}>전일비</th>
                <th style={{ width: "8%" }}>등락률</th>
                <th style={{ width: "8%" }}>매수호가</th>
                <th style={{ width: "8%" }}>매도호가</th>
                <th style={{ width: "11%" }}>거래량</th>
                <th style={{ width: "11%" }}>거래대금</th>
                <th style={{ width: "11%" }}>전일거래량</th>
                <th style={{ width: "7%" }}>뉴스</th>
              </tr>
            </thead>
            <tbody>
              {sectorLoading ? (
                Array.from({ length: 8 }).map((_, i) => (
                  <tr key={`sk-${i}`}>
                    <td><div className="skeleton skeleton-text" style={{ width: `${50 + Math.random() * 30}%` }} /></td>
                    {Array.from({ length: 9 }).map((_, j) => (
                      <td key={j} className="text-right"><div className="skeleton skeleton-text-sm" style={{ width: '70%', marginLeft: 'auto' }} /></td>
                    ))}
                  </tr>
                ))
              ) : !sector?.stocks || sector.stocks.length === 0 ? (
                <tr>
                  <td colSpan={10} className="text-center py-8 text-[#999]">
                    등록된 종목이 없습니다.{" "}
                    <Link href="/manage" className="text-[#1261c4] hover:underline">
                      관리 페이지
                    </Link>
                    에서 추가하세요.
                  </td>
                </tr>
              ) : (
                sector.stocks.map((stock) => {
                  const pc = stock.price_change ?? 0;
                  const priceColor = pc > 0 ? "text-rise" : pc < 0 ? "text-fall" : "text-[#333]";
                  const arrow = pc > 0 ? "▲" : pc < 0 ? "▼" : "";
                  return (
                    <tr key={stock.id}>
                      <td>
                        <Link
                          href={`/stocks/${stock.id}`}
                          className="text-[#333] hover:text-[#1261c4] hover:underline font-medium"
                        >
                          {stock.name}
                        </Link>
                      </td>
                      <td className="text-right text-[#333]">
                        {stock.current_price != null ? stock.current_price.toLocaleString() : "-"}
                      </td>
                      <td className={`text-right ${priceColor}`}>
                        {stock.price_change != null
                          ? `${arrow} ${Math.abs(stock.price_change).toLocaleString()}`
                          : "-"}
                      </td>
                      <td className="text-right">
                        <ChangeRate value={stock.change_rate} />
                      </td>
                      <td className="text-right">
                        {stock.bid_price != null ? stock.bid_price.toLocaleString() : "-"}
                      </td>
                      <td className="text-right">
                        {stock.ask_price != null ? stock.ask_price.toLocaleString() : "-"}
                      </td>
                      <td className="text-right">
                        {stock.volume != null ? stock.volume.toLocaleString() : "-"}
                      </td>
                      <td className="text-right">
                        {stock.trading_value != null ? stock.trading_value.toLocaleString() : "-"}
                      </td>
                      <td className="text-right">
                        {stock.prev_volume != null ? stock.prev_volume.toLocaleString() : "-"}
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
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="section-box" style={{ borderTop: "none" }}>
          <table className="naver-table">
            <thead>
              <tr>
                <th className="text-left" style={{ width: "52%" }}>제목</th>
                <th style={{ width: "8%" }}>구분</th>
                <th style={{ width: "18%" }}>관련</th>
                <th style={{ width: "22%" }}>날짜</th>
              </tr>
            </thead>
            <tbody>
              {newsLoading ? (
                Array.from({ length: 15 }).map((_, i) => (
                  <tr key={`sk-${i}`}>
                    <td><div className="skeleton skeleton-text" style={{ width: `${55 + Math.random() * 35}%` }} /></td>
                    <td className="text-center"><div className="skeleton skeleton-badge mx-auto" /></td>
                    <td className="text-center">
                      <div className="flex gap-1 justify-center">
                        <div className="skeleton skeleton-badge" />
                        <div className="skeleton skeleton-badge" />
                      </div>
                    </td>
                    <td className="text-center"><div className="skeleton skeleton-text-sm mx-auto" style={{ width: "80%" }} /></td>
                  </tr>
                ))
              ) : news.length === 0 ? (
                <tr>
                  <td colSpan={4} className="text-center py-8 text-[#999]">
                    관련 뉴스가 없습니다.
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
                      </td>
                      <td className="text-center">
                        <span className={`badge ${sentiment.className}`}>
                          {sentiment.text}
                        </span>
                      </td>
                      <td className="text-center">
                        {(() => {
                          const sectors = new Map<number, string>();
                          const stocks = new Map<number, string>();
                          for (const rel of article.relations) {
                            if (rel.sector_id && rel.sector_name) sectors.set(rel.sector_id, rel.sector_name);
                            if (rel.stock_id && rel.stock_name) stocks.set(rel.stock_id, rel.stock_name);
                          }
                          const tags: { key: string; label: string; cls: string }[] = [];
                          for (const [id, name] of sectors) tags.push({ key: `s${id}`, label: formatSectorName(name), cls: "badge-sector" });
                          for (const [id, name] of stocks) tags.push({ key: `t${id}`, label: name, cls: "badge-stock" });
                          return tags.slice(0, 3).map((t) => (
                            <span key={t.key} className={`badge ${t.cls} mr-1`}>{t.label}</span>
                          ));
                        })()}
                      </td>
                      <td className="text-center text-[12px] text-[#999]">
                        {formatDate(article.published_at)}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
          {!newsLoading && news.length > 0 && (
            <Pagination currentPage={newsPage} totalPages={newsTotalPages} onPageChange={setNewsPage} />
          )}
        </div>
      )}
    </div>
  );
}
