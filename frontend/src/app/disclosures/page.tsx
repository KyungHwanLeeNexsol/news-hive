"use client";

import { useEffect, useState } from "react";
import { fetchDisclosures, refreshDisclosures } from "@/lib/api";
import type { DisclosureItem } from "@/lib/types";
import Pagination from "@/components/Pagination";
import DisclosureModal from "@/components/DisclosureModal";

const PAGE_SIZE = 30;

const REPORT_TYPES = [
  { value: "", label: "전체" },
  { value: "정기공시", label: "정기공시" },
  { value: "주요사항보고", label: "주요사항보고" },
  { value: "실적변동", label: "실적변동" },
  { value: "발행공시", label: "발행공시" },
  { value: "지분공시", label: "지분공시" },
  { value: "기업지배구조", label: "기업지배구조" },
  { value: "기업집단공시", label: "기업집단공시" },
  { value: "기타공시", label: "기타공시" },
];

function formatDate(raw: string): string {
  if (!raw || raw.length < 8) return "-";
  return `${raw.slice(0, 4)}.${raw.slice(4, 6)}.${raw.slice(6, 8)}`;
}

export default function DisclosuresPage() {
  const [disclosures, setDisclosures] = useState<DisclosureItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [reportType, setReportType] = useState("");
  const [selectedDisclosure, setSelectedDisclosure] = useState<DisclosureItem | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  // Search state
  const [searchInput, setSearchInput] = useState("");
  const [query, setQuery] = useState("");

  function handleRefresh() {
    setRefreshing(true);
    refreshDisclosures()
      .then(() => {
        setPage(1);
        return fetchDisclosures({ report_type: reportType || undefined, q: query || undefined, limit: PAGE_SIZE, offset: 0 });
      })
      .then((r) => {
        setDisclosures(r.disclosures);
        setTotal(r.total);
      })
      .catch(() => {})
      .finally(() => setRefreshing(false));
  }

  useEffect(() => {
    setLoading(true);
    window.scrollTo({ top: 0 });
    fetchDisclosures({
      report_type: reportType || undefined,
      q: query || undefined,
      limit: PAGE_SIZE,
      offset: (page - 1) * PAGE_SIZE,
    })
      .then((r) => {
        setDisclosures(r.disclosures);
        setTotal(r.total);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [page, reportType, query]);

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = searchInput.trim();
    setQuery(trimmed);
    setPage(1);
  }

  function handleClearSearch() {
    setSearchInput("");
    setQuery("");
    setPage(1);
  }

  function handleTypeChange(value: string) {
    setReportType(value);
    setPage(1);
  }

  const totalPages = Math.ceil(total / PAGE_SIZE);

  return (
    <div className="section-box">
      <div className="section-title">
        <span>{query ? `"${query}" 검색 결과 (${total}건)` : `전체 공시 (${total}건)`}</span>
        <button
          onClick={handleRefresh}
          disabled={refreshing}
          className="px-3 py-1 text-[12px] bg-[#1261c4] text-white rounded hover:bg-[#0f54a8] disabled:opacity-50"
        >
          {refreshing ? "수집 중..." : "공시 새로고침"}
        </button>
      </div>

      {/* Search bar */}
      <form onSubmit={handleSearch} className="flex gap-2 px-4 py-3 border-b border-[#e5e5e5]">
        <input
          type="text"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          placeholder="공시 제목 또는 종목명 검색"
          className="flex-1 px-3 py-1.5 border border-[#ddd] rounded text-[13px] focus:outline-none focus:border-[#1261c4]"
        />
        <button
          type="submit"
          className="px-4 py-1.5 bg-[#1261c4] text-white text-[13px] rounded hover:bg-[#0f54a8]"
        >
          검색
        </button>
        {query && (
          <button
            type="button"
            onClick={handleClearSearch}
            className="px-3 py-1.5 border border-[#ddd] text-[13px] text-[#666] rounded hover:bg-[#f5f5f5]"
          >
            초기화
          </button>
        )}
      </form>

      {/* Report type filter */}
      <div className="flex gap-1.5 px-4 py-3 border-b border-[#e5e5e5]">
        {REPORT_TYPES.map((rt) => (
          <button
            key={rt.value}
            onClick={() => handleTypeChange(rt.value)}
            className={`px-3 py-1 text-[12px] rounded border transition-colors ${
              reportType === rt.value
                ? "bg-[#1261c4] text-white border-[#1261c4]"
                : "bg-white text-[#666] border-[#ddd] hover:border-[#999]"
            }`}
          >
            {rt.label}
          </button>
        ))}
      </div>

      {/* Table */}
      <table className="naver-table">
        <thead>
          <tr>
            <th className="text-left" style={{ width: "50%" }}>공시 제목</th>
            <th style={{ width: "15%" }}>종목</th>
            <th style={{ width: "15%" }}>유형</th>
            <th style={{ width: "20%" }}>날짜</th>
          </tr>
        </thead>
        <tbody>
          {loading ? (
            Array.from({ length: 15 }).map((_, i) => (
              <tr key={`skeleton-${i}`}>
                <td>
                  <div className="skeleton skeleton-text" style={{ width: `${55 + Math.random() * 35}%` }} />
                </td>
                <td className="text-center">
                  <div className="skeleton skeleton-badge mx-auto" />
                </td>
                <td className="text-center">
                  <div className="skeleton skeleton-badge mx-auto" />
                </td>
                <td className="text-center">
                  <div className="skeleton skeleton-text-sm mx-auto" style={{ width: "80%" }} />
                </td>
              </tr>
            ))
          ) : disclosures.length === 0 ? (
            <tr>
              <td colSpan={4} className="text-center py-8 text-[#999]">
                {query ? `"${query}"에 대한 검색 결과가 없습니다.` : "공시 내역이 없습니다."}
              </td>
            </tr>
          ) : (
            disclosures.map((disc) => (
              <tr
                key={disc.rcept_no}
                className="cursor-pointer"
                onClick={() => setSelectedDisclosure(disc)}
              >
                <td className="text-[13px] text-[#1261c4]">{disc.report_name}</td>
                <td className="text-center">
                  {(disc.stock_name || disc.corp_name) && (
                    <span className="badge badge-stock">{disc.stock_name || disc.corp_name}</span>
                  )}
                </td>
                <td className="text-center">
                  {disc.report_type && (
                    <span className="badge badge-neutral">{disc.report_type}</span>
                  )}
                </td>
                <td className="text-center text-[12px] text-[#999]">
                  {formatDate(disc.rcept_dt)}
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>

      <Pagination currentPage={page} totalPages={totalPages} onPageChange={setPage} />

      {selectedDisclosure && (
        <DisclosureModal
          disclosure={selectedDisclosure}
          onClose={() => setSelectedDisclosure(null)}
        />
      )}
    </div>
  );
}
