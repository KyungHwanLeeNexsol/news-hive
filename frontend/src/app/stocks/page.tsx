'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import Link from 'next/link';
import { fetchStocks } from '@/lib/api';
import type { StockListItem } from '@/lib/types';
import Pagination from '@/components/Pagination';
import ChangeRate from '@/components/ChangeRate';
import { useWatchlist } from '@/lib/watchlist';

const PAGE_SIZE = 50;
const REFRESH_INTERVAL = 5 * 60 * 1000; // 5 minutes

type MarketTab = '' | 'KOSPI' | 'KOSDAQ';

export default function StocksPage() {
  const [stocks, setStocks] = useState<StockListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [market, setMarket] = useState<MarketTab>('');
  const [searchInput, setSearchInput] = useState('');
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [watchlistOnly, setWatchlistOnly] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const { watchlist, toggleStock, isWatched } = useWatchlist();

  const load = useCallback((silent = false) => {
    if (watchlistOnly && watchlist.length === 0) {
      setStocks([]);
      setTotal(0);
      setLoading(false);
      return;
    }
    if (!silent) setLoading(true);
    const params: Parameters<typeof fetchStocks>[0] = {
      q: query,
      market: market || undefined,
      limit: PAGE_SIZE,
      offset: (page - 1) * PAGE_SIZE,
    };
    if (watchlistOnly) {
      params.ids = watchlist.join(',');
    }
    fetchStocks(params)
      .then((r) => {
        setStocks(r.stocks);
        setTotal(r.total);
      })
      .catch(() => {})
      .finally(() => { if (!silent) setLoading(false); });
  }, [query, market, page, watchlistOnly, watchlist]);

  useEffect(() => { load(); }, [load]);

  // Auto-refresh every 5 minutes (silent — no loading spinner)
  useEffect(() => {
    const interval = setInterval(() => load(true), REFRESH_INTERVAL);
    return () => clearInterval(interval);
  }, [load]);

  // Reset page when filters change
  useEffect(() => { setPage(1); }, [query, market, watchlistOnly]);

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

            <button
              onClick={() => setWatchlistOnly(!watchlistOnly)}
              className={`px-3 py-1 text-[12px] font-medium rounded transition-colors flex items-center gap-1 ${
                watchlistOnly
                  ? 'bg-[#ffa723] text-white'
                  : 'bg-[#f5f5f5] text-[#666] hover:bg-[#e5e5e5]'
              }`}
            >
              <span className="text-[13px]">{watchlistOnly ? '★' : '☆'}</span>
              관심종목
            </button>
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
        <div style={{ overflowX: 'auto' }}>
        <table className="naver-table" style={{ minWidth: '900px' }}>
          <thead>
            <tr>
              <th style={{ width: '3%' }}></th>
              <th className="text-left" style={{ width: '16%' }}>종목명</th>
              <th style={{ width: '10%' }}>현재가</th>
              <th style={{ width: '10%' }}>전일비</th>
              <th style={{ width: '9%' }}>등락률</th>
              <th style={{ width: '13%' }}>시가총액</th>
              <th style={{ width: '12%' }}>거래량</th>
              <th style={{ width: '7%' }}>시장</th>
              <th style={{ width: '5%' }}>뉴스</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              Array.from({ length: 15 }).map((_, i) => (
                <tr key={`sk-${i}`}>
                  <td className="text-center text-[#ccc]">☆</td>
                  <td><div className="skeleton skeleton-text" style={{ width: `${50 + Math.random() * 30}%` }} /></td>
                  {Array.from({ length: 7 }).map((_, j) => (
                    <td key={j} className="text-right"><div className="skeleton skeleton-text-sm" style={{ width: '70%', marginLeft: 'auto' }} /></td>
                  ))}
                </tr>
              ))
            ) : stocks.length === 0 ? (
              <tr>
                <td colSpan={9} className="text-center py-8 text-[#999]">
                  {watchlistOnly ? '관심종목이 없습니다.' : query ? '검색 결과가 없습니다.' : '종목이 없습니다.'}
                </td>
              </tr>
            ) : (
              stocks.map((stock) => {
                const pc = stock.price_change ?? 0;
                const priceColor = pc > 0 ? 'text-rise' : pc < 0 ? 'text-fall' : 'text-[#333]';
                const arrow = pc > 0 ? '▲' : pc < 0 ? '▼' : '';
                const rate = stock.change_rate ?? 0;
                // Highlight ±5% or more
                const rowBg = rate >= 5 ? 'bg-[#fff5f5]' : rate <= -5 ? 'bg-[#f5f5ff]' : '';

                // Format market cap: 억원 → 조/억
                const formatMarketCap = (v: number | null) => {
                  if (v == null) return '-';
                  if (v >= 10000) return `${(v / 10000).toFixed(1)}조`;
                  return `${v.toLocaleString()}억`;
                };

                return (
                  <tr key={stock.id} className={`hover:bg-[#f7f8fa] ${rowBg}`}>
                    <td className="text-center">
                      <button
                        onClick={(e) => { e.stopPropagation(); toggleStock(stock.id); }}
                        className={`text-[16px] leading-none transition-colors ${
                          isWatched(stock.id) ? 'text-[#ffa723]' : 'text-[#ccc] hover:text-[#ffa723]'
                        }`}
                        title={isWatched(stock.id) ? '관심종목 해제' : '관심종목 추가'}
                      >
                        {isWatched(stock.id) ? '★' : '☆'}
                      </button>
                    </td>
                    <td>
                      <Link
                        href={`/stocks/${stock.id}`}
                        className="text-[#333] hover:text-[#1261c4] hover:underline font-medium"
                      >
                        {stock.name}
                      </Link>
                    </td>
                    <td className="text-right text-[#333]">
                      {stock.current_price != null ? stock.current_price.toLocaleString() : '-'}
                    </td>
                    <td className={`text-right ${priceColor}`}>
                      {stock.price_change != null
                        ? `${arrow} ${Math.abs(stock.price_change).toLocaleString()}`
                        : '-'}
                    </td>
                    <td className="text-right">
                      <ChangeRate value={stock.change_rate} />
                    </td>
                    <td className="text-right text-[#333]">
                      {formatMarketCap(stock.market_cap)}
                    </td>
                    <td className="text-right">
                      {stock.volume != null ? stock.volume.toLocaleString() : '-'}
                    </td>
                    <td className="text-center">
                      {stock.market ? (
                        <span className={`text-[11px] px-1.5 py-0.5 rounded ${
                          stock.market === 'KOSPI'
                            ? 'bg-[#e8f4fd] text-[#1261c4]'
                            : 'bg-[#fef3e2] text-[#c57a20]'
                        }`}>
                          {stock.market}
                        </span>
                      ) : '-'}
                    </td>
                    <td className="text-center">
                      {stock.news_count > 0 ? (
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

        {!loading && stocks.length > 0 && (
          <Pagination currentPage={page} totalPages={totalPages} onPageChange={setPage} />
        )}
      </div>
    </div>
  );
}
