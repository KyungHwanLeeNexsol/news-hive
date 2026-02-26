'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import Link from 'next/link';
import { fetchStocks } from '@/lib/api';
import { formatSectorName } from '@/lib/format';
import type { StockListItem } from '@/lib/types';
import Pagination from '@/components/Pagination';

const PAGE_SIZE = 50;

type MarketTab = '' | 'KOSPI' | 'KOSDAQ';

export default function StocksPage() {
  const [stocks, setStocks] = useState<StockListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [market, setMarket] = useState<MarketTab>('');
  const [searchInput, setSearchInput] = useState('');
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    fetchStocks({
      q: query,
      market: market || undefined,
      limit: PAGE_SIZE,
      offset: (page - 1) * PAGE_SIZE,
    })
      .then((r) => {
        setStocks(r.stocks);
        setTotal(r.total);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [query, market, page]);

  useEffect(() => { load(); }, [load]);

  // Reset page when filters change
  useEffect(() => { setPage(1); }, [query, market]);

  // Debounced search
  const handleSearchChange = (value: string) => {
    setSearchInput(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => setQuery(value), 300);
  };

  const totalPages = Math.ceil(total / PAGE_SIZE);

  return (
    <div>
      {/* Search + market tabs */}
      <div className="section-box mb-3">
        <div className="flex items-center gap-3 px-4 py-2.5 border-b border-[#e5e5e5]">
          <div className="flex gap-1">
            {([
              { key: '' as MarketTab, label: '전체' },
              { key: 'KOSPI' as MarketTab, label: 'KOSPI' },
              { key: 'KOSDAQ' as MarketTab, label: 'KOSDAQ' },
            ]).map((t) => (
              <button
                key={t.key}
                onClick={() => setMarket(t.key)}
                className={`px-3 py-1 text-[12px] font-medium rounded transition-colors ${
                  market === t.key
                    ? 'bg-[#1261c4] text-white'
                    : 'bg-[#f5f5f5] text-[#666] hover:bg-[#e5e5e5]'
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>

          <div className="flex-1" />

          <div className="relative">
            <input
              type="text"
              placeholder="종목명 또는 코드 검색"
              value={searchInput}
              onChange={(e) => handleSearchChange(e.target.value)}
              className="w-[220px] px-3 py-1.5 text-[12px] border border-[#ddd] rounded outline-none focus:border-[#1261c4] transition-colors"
            />
            {searchInput && (
              <button
                onClick={() => { setSearchInput(''); setQuery(''); }}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-[#999] hover:text-[#333] text-[14px]"
              >
                &times;
              </button>
            )}
          </div>
        </div>

        <div className="px-4 py-1.5 text-[11px] text-[#999] border-b border-[#e5e5e5]">
          {loading ? '로딩 중...' : `총 ${total.toLocaleString()}개 종목`}
        </div>

        {/* Stock table */}
        <table className="naver-table">
          <thead>
            <tr>
              <th className="text-left" style={{ width: '30%' }}>종목명</th>
              <th style={{ width: '12%' }}>종목코드</th>
              <th style={{ width: '10%' }}>시장</th>
              <th className="text-left" style={{ width: '48%' }}>업종</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              Array.from({ length: 15 }).map((_, i) => (
                <tr key={`sk-${i}`}>
                  <td><div className="skeleton skeleton-text" style={{ width: `${40 + Math.random() * 30}%` }} /></td>
                  <td className="text-center"><div className="skeleton skeleton-text-sm mx-auto" style={{ width: '60%' }} /></td>
                  <td className="text-center"><div className="skeleton skeleton-badge mx-auto" /></td>
                  <td><div className="skeleton skeleton-text" style={{ width: `${30 + Math.random() * 40}%` }} /></td>
                </tr>
              ))
            ) : stocks.length === 0 ? (
              <tr>
                <td colSpan={4} className="text-center py-8 text-[#999]">
                  {query ? '검색 결과가 없습니다.' : '종목이 없습니다.'}
                </td>
              </tr>
            ) : (
              stocks.map((stock) => (
                <tr key={stock.id} className="cursor-pointer hover:bg-[#f7f8fa]">
                  <td>
                    <Link
                      href={`/stocks/${stock.id}`}
                      className="text-[#333] hover:text-[#1261c4] hover:underline font-medium"
                    >
                      {stock.name}
                    </Link>
                  </td>
                  <td className="text-center text-[12px] text-[#666]">{stock.stock_code}</td>
                  <td className="text-center">
                    <span className={`badge ${stock.market === 'KOSPI' ? 'badge-positive' : 'badge-neutral'}`}>
                      {stock.market || '-'}
                    </span>
                  </td>
                  <td>
                    {stock.sector_name && (
                      <Link
                        href={`/sectors/${stock.sector_id}`}
                        className="text-[12px] text-[#666] hover:text-[#1261c4] hover:underline"
                      >
                        {formatSectorName(stock.sector_name)}
                      </Link>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>

        {!loading && stocks.length > 0 && (
          <Pagination currentPage={page} totalPages={totalPages} onPageChange={setPage} />
        )}
      </div>
    </div>
  );
}
