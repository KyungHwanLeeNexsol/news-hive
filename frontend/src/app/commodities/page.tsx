"use client";

import { Suspense, useEffect, useState, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { fetchCommodities, fetchCommodityHistory, refreshCommodityPrices, fetchCommodityNews, fetchCommodityNewsById } from "@/lib/api";
import type { Commodity, CommodityHistoryPoint, CommodityNewsArticle, NewsArticle } from "@/lib/types";
import ChangeRate from "@/components/ChangeRate";
import CommodityNewsCard from "@/components/CommodityNewsCard";
import Pagination from "@/components/Pagination";
import { useMarketRefresh } from "@/lib/useMarketRefresh";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";

function getPrice(c: Commodity): number | null {
  if (c.latest_price == null) return null;
  if (typeof c.latest_price === "number") return c.latest_price;
  return c.latest_price.price ?? null;
}

function getChangePct(c: Commodity): number | null {
  if (c.change_pct != null) return c.change_pct;
  if (c.latest_price != null && typeof c.latest_price === "object") return c.latest_price.change_pct;
  return null;
}

const CATEGORY_LABELS: Record<string, string> = {
  all: "전체",
  energy: "에너지",
  metal: "금속",
  agriculture: "농산물",
};

const PERIODS = [
  { value: "1w", label: "1주" },
  { value: "1mo", label: "1개월" },
  { value: "3mo", label: "3개월" },
  { value: "6mo", label: "6개월" },
  { value: "1y", label: "1년" },
  { value: "2y", label: "2년" },
  { value: "5y", label: "5년" },
  { value: "10y", label: "10년" },
  { value: "max", label: "전체" },
];

const NEWS_PAGE_SIZE = 30;

function formatPrice(price: number, currency: string): string {
  if (currency === "USD") {
    return `$${price.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }
  if (currency === "KRW") {
    return `${price.toLocaleString("ko-KR")}원`;
  }
  return price.toLocaleString();
}

function formatChartDate(dateStr: string, period?: string): string {
  const d = new Date(dateStr);
  const longPeriods = new Set(["2y", "5y", "10y", "max"]);
  if (period && longPeriods.has(period)) {
    return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, "0")}`;
  }
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

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

export default function CommoditiesPage() {
  return (
    <Suspense fallback={<div className="py-8 text-center text-[13px] text-[#999]">로딩 중...</div>}>
      <CommoditiesContent />
    </Suspense>
  );
}

function CommoditiesContent() {
  const searchParams = useSearchParams();
  const preselectedId = searchParams.get("selected");
  const initialTab = searchParams.get("tab") === "news" ? "news" : "prices";

  // 메인 탭: 시세 / 뉴스룸
  const [mainTab, setMainTab] = useState<"prices" | "news">(initialTab as "prices" | "news");

  // ── 시세 탭 상태 ──
  const [commodities, setCommodities] = useState<Commodity[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [category, setCategory] = useState("all");
  const [selectedId, setSelectedId] = useState<number | null>(
    preselectedId ? Number(preselectedId) : null,
  );
  const [period, setPeriod] = useState("1mo");
  const [history, setHistory] = useState<CommodityHistoryPoint[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  // ── 뉴스룸 탭 상태 ──
  const [newsArticles, setNewsArticles] = useState<CommodityNewsArticle[]>([]);
  const [newsTotal, setNewsTotal] = useState(0);
  const [newsPage, setNewsPage] = useState(1);
  const [newsLoading, setNewsLoading] = useState(false);
  const [newsFilterCommodity, setNewsFilterCommodity] = useState<number | null>(null);

  const loadCommodities = useCallback(() => {
    fetchCommodities()
      .then((data) => {
        setCommodities(data);
        if (!preselectedId && data.length > 0 && selectedId === null) {
          setSelectedId(data[0].id);
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [preselectedId, selectedId]);

  useEffect(() => { loadCommodities(); }, [loadCommodities]);
  useMarketRefresh(loadCommodities);

  // 선택된 원자재 히스토리 로드
  useEffect(() => {
    if (!selectedId || mainTab !== "prices") return;
    setHistoryLoading(true);
    fetchCommodityHistory(selectedId, period)
      .then((data) => setHistory(data.history))
      .catch(() => setHistory([]))
      .finally(() => setHistoryLoading(false));
  }, [selectedId, period, mainTab]);

  // 뉴스룸 데이터 로드
  useEffect(() => {
    if (mainTab !== "news") return;
    let cancelled = false;
    setNewsLoading(true);
    const offset = (newsPage - 1) * NEWS_PAGE_SIZE;

    if (newsFilterCommodity) {
      // 특정 원자재 필터 -> fetchCommodityNewsById
      fetchCommodityNewsById(newsFilterCommodity, offset, NEWS_PAGE_SIZE)
        .then((r) => {
          if (cancelled) return;
          const filtered = commodities.find((c) => c.id === newsFilterCommodity);
          const mapped: CommodityNewsArticle[] = r.articles.map((a: NewsArticle) => ({
            ...a,
            commodity_relations: filtered ? [{
              commodity_id: filtered.id,
              name_ko: filtered.name_ko,
              symbol: filtered.symbol,
              relevance: "keyword",
              impact_direction: null,
            }] : [],
          }));
          setNewsArticles(mapped);
          setNewsTotal(r.total);
        })
        .catch(() => { if (!cancelled) { setNewsArticles([]); setNewsTotal(0); } })
        .finally(() => { if (!cancelled) setNewsLoading(false); });
    } else {
      // 전체 원자재 뉴스
      fetchCommodityNews(offset, NEWS_PAGE_SIZE)
        .then((r) => { if (!cancelled) { setNewsArticles(r.articles); setNewsTotal(r.total); } })
        .catch(() => { if (!cancelled) { setNewsArticles([]); setNewsTotal(0); } })
        .finally(() => { if (!cancelled) setNewsLoading(false); });
    }
    return () => { cancelled = true; };
  }, [mainTab, newsPage, newsFilterCommodity, commodities]);

  const filteredCommodities =
    category === "all"
      ? commodities
      : commodities.filter((c) => c.category === category);

  const selectedCommodity = commodities.find((c) => c.id === selectedId);
  const newsTotalPages = Math.ceil(newsTotal / NEWS_PAGE_SIZE);

  async function handleRefresh() {
    setRefreshing(true);
    try {
      await refreshCommodityPrices();
      loadCommodities();
    } catch {
      // ignore
    } finally {
      setRefreshing(false);
    }
  }

  return (
    <div>
      {/* 헤더 */}
      <div className="flex items-center justify-between mb-3">
        <h1 className="text-[16px] font-bold text-[#333]">원자재</h1>
        {mainTab === "prices" && (
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            className="text-[12px] text-[#1261c4] hover:underline disabled:text-[#999]"
          >
            {refreshing ? "갱신 중..." : "시세 갱신"}
          </button>
        )}
      </div>

      {/* 메인 탭: 시세 / 뉴스룸 */}
      <div className="tab-nav mb-0">
        <button
          className={`tab-item ${mainTab === "prices" ? "active" : ""}`}
          onClick={() => setMainTab("prices")}
        >
          시세
        </button>
        <button
          className={`tab-item ${mainTab === "news" ? "active" : ""}`}
          onClick={() => { setMainTab("news"); setNewsPage(1); }}
        >
          뉴스룸 {newsTotal > 0 && `(${newsTotal})`}
        </button>
      </div>

      {/* ── 시세 탭 ── */}
      {mainTab === "prices" && (
        <>
          {/* 카테고리 탭 */}
          <div className="section-box" style={{ borderTop: "none" }}>
            <div className="flex gap-1 px-4 py-2 border-b border-[#e5e5e5]">
              {Object.entries(CATEGORY_LABELS).map(([key, label]) => (
                <button
                  key={key}
                  className={`px-2.5 py-1 text-[11px] rounded ${
                    category === key
                      ? "bg-[#1261c4] text-white"
                      : "bg-[#f5f5f5] text-[#666] hover:bg-[#e5e5e5]"
                  }`}
                  onClick={() => setCategory(key)}
                >
                  {label}
                </button>
              ))}
            </div>

            {/* 원자재 카드 그리드 */}
            {loading ? (
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
                {Array.from({ length: 10 }).map((_, i) => (
                  <div key={i} className="px-4 py-3 border-r border-b border-[#e5e5e5]">
                    <div className="skeleton skeleton-text" style={{ width: "60%" }} />
                    <div className="skeleton skeleton-text mt-1" style={{ width: "80%" }} />
                    <div className="skeleton skeleton-text-sm mt-1" style={{ width: "40%" }} />
                  </div>
                ))}
              </div>
            ) : filteredCommodities.length === 0 ? (
              <div className="py-8 text-center text-[13px] text-[#999]">
                해당 카테고리에 원자재가 없습니다.
              </div>
            ) : (
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
                {filteredCommodities.map((c) => {
                  const isSelected = c.id === selectedId;
                  const changePct = getChangePct(c) ?? 0;
                  const priceColor =
                    changePct > 0 ? "text-rise" : changePct < 0 ? "text-fall" : "text-[#333]";
                  return (
                    <button
                      key={c.id}
                      onClick={() => setSelectedId(c.id)}
                      className={`text-left px-4 py-3 border-r border-b border-[#e5e5e5] hover:bg-[#f7f8fa] transition-colors ${
                        isSelected ? "bg-[#f0f6ff]" : ""
                      }`}
                    >
                      <div className="flex items-center gap-1.5">
                        <span className="text-[13px] font-medium text-[#333]">{c.name_ko}</span>
                        <span className="text-[10px] text-[#999]">{c.symbol}</span>
                      </div>
                      {getPrice(c) != null ? (
                        <>
                          <div className={`text-[15px] font-bold mt-0.5 ${priceColor}`}>
                            {formatPrice(getPrice(c)!, c.currency)}
                          </div>
                          <div className="text-[12px] mt-0.5">
                            <ChangeRate value={getChangePct(c)} />
                          </div>
                        </>
                      ) : (
                        <div className="text-[13px] text-[#999] mt-0.5">-</div>
                      )}
                      <div className="text-[10px] text-[#bbb] mt-0.5">
                        {CATEGORY_LABELS[c.category] ?? c.category} / {c.unit}
                      </div>
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          {/* 차트 영역 */}
          {selectedCommodity && (
            <div className="section-box mt-3">
              <div className="flex items-center justify-between px-4 py-2.5 border-b border-[#e5e5e5]">
                <div className="flex items-center gap-2">
                  <span className="text-[14px] font-bold text-[#333]">
                    {selectedCommodity.name_ko}
                  </span>
                  <span className="text-[12px] text-[#999]">
                    {selectedCommodity.symbol} ({selectedCommodity.unit})
                  </span>
                  {getPrice(selectedCommodity) != null && (
                    <span className="text-[13px] font-bold ml-2">
                      {formatPrice(getPrice(selectedCommodity)!, selectedCommodity.currency)}
                    </span>
                  )}
                  {getChangePct(selectedCommodity) != null && (
                    <ChangeRate value={getChangePct(selectedCommodity)} />
                  )}
                </div>
                <div className="flex gap-1">
                  {PERIODS.map((p) => (
                    <button
                      key={p.value}
                      onClick={() => setPeriod(p.value)}
                      className={`px-2.5 py-1 text-[11px] rounded ${
                        period === p.value
                          ? "bg-[#1261c4] text-white"
                          : "bg-[#f5f5f5] text-[#666] hover:bg-[#e5e5e5]"
                      }`}
                    >
                      {p.label}
                    </button>
                  ))}
                </div>
              </div>
              <div className="px-4 py-4">
                {historyLoading ? (
                  <div className="h-[300px] flex items-center justify-center">
                    <span className="text-[13px] text-[#999]">차트 로딩 중...</span>
                  </div>
                ) : history.length === 0 ? (
                  <div className="h-[300px] flex items-center justify-center">
                    <span className="text-[13px] text-[#999]">데이터가 없습니다.</span>
                  </div>
                ) : (
                  <ResponsiveContainer width="100%" height={300}>
                    <LineChart data={history}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                      <XAxis
                        dataKey="date"
                        tickFormatter={(d) => formatChartDate(d, period)}
                        tick={{ fontSize: 11, fill: "#999" }}
                        tickLine={false}
                        axisLine={{ stroke: "#e5e5e5" }}
                      />
                      <YAxis
                        domain={["auto", "auto"]}
                        tick={{ fontSize: 11, fill: "#999" }}
                        tickLine={false}
                        axisLine={false}
                        width={80}
                        tickFormatter={(v: number) => v.toLocaleString()}
                      />
                      <Tooltip
                        contentStyle={{
                          fontSize: 12,
                          border: "1px solid #e5e5e5",
                          borderRadius: 4,
                          boxShadow: "0 2px 8px rgba(0,0,0,0.08)",
                        }}
                        labelFormatter={(label) => {
                          const d = new Date(String(label));
                          return d.toLocaleDateString("ko-KR");
                        }}
                        formatter={(value) => [Number(value).toLocaleString(), "종가"]}
                      />
                      <Line
                        type="monotone"
                        dataKey="close"
                        stroke="#1261c4"
                        strokeWidth={2}
                        dot={false}
                        activeDot={{ r: 4, fill: "#1261c4" }}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                )}
              </div>
            </div>
          )}
        </>
      )}

      {/* ── 뉴스룸 탭 ── */}
      {mainTab === "news" && (
        <div className="section-box" style={{ borderTop: "none" }}>
          {/* 필터 영역 */}
          <div className="flex items-center gap-3 px-4 py-2.5 border-b border-[#e5e5e5]">
            <label className="text-[12px] text-[#666]">원자재:</label>
            <select
              value={newsFilterCommodity ?? ""}
              onChange={(e) => {
                setNewsLoading(true);
                setNewsArticles([]);
                setNewsFilterCommodity(e.target.value ? Number(e.target.value) : null);
                setNewsPage(1);
              }}
              className="px-2 py-1 border border-[#ddd] rounded text-[12px] focus:outline-none focus:border-[#1261c4]"
            >
              <option value="">전체</option>
              {commodities.map((c) => (
                <option key={c.id} value={c.id}>{c.name_ko} ({c.symbol})</option>
              ))}
            </select>
            <span className="text-[12px] text-[#999] ml-auto">
              총 {newsTotal}건
            </span>
          </div>

          {/* 뉴스 테이블 */}
          <table className="naver-table">
            <thead>
              <tr>
                <th className="text-left" style={{ width: "48%" }}>제목</th>
                <th style={{ width: "7%" }}>구분</th>
                <th style={{ width: "25%" }}>원자재</th>
                <th style={{ width: "20%" }}>날짜</th>
              </tr>
            </thead>
            <tbody>
              {newsLoading ? (
                Array.from({ length: 15 }).map((_, i) => (
                  <tr key={`sk-${i}`}>
                    <td>
                      <div className="skeleton skeleton-text" style={{ width: `${55 + Math.random() * 35}%` }} />
                    </td>
                    <td className="text-center">
                      <div className="skeleton skeleton-badge mx-auto" />
                    </td>
                    <td className="text-center">
                      <div className="flex gap-1 justify-center">
                        <div className="skeleton skeleton-badge" />
                        <div className="skeleton skeleton-badge" />
                      </div>
                    </td>
                    <td className="text-center">
                      <div className="skeleton skeleton-text-sm mx-auto" style={{ width: "80%" }} />
                    </td>
                  </tr>
                ))
              ) : newsArticles.length === 0 ? (
                <tr>
                  <td colSpan={4} className="text-center py-8 text-[#999]">
                    원자재 관련 뉴스가 없습니다.
                  </td>
                </tr>
              ) : (
                newsArticles.map((article) => (
                  <CommodityNewsCard key={article.id} article={article} />
                ))
              )}
            </tbody>
          </table>

          {!newsLoading && newsArticles.length > 0 && (
            <Pagination
              currentPage={newsPage}
              totalPages={newsTotalPages}
              onPageChange={(p) => { setNewsPage(p); window.scrollTo({ top: 0 }); }}
            />
          )}
        </div>
      )}
    </div>
  );
}
