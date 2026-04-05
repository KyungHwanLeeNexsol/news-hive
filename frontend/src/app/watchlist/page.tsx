'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import Link from 'next/link';
import { fetchStocks, fetchUserWatchlist, addToUserWatchlist, removeFromUserWatchlist, syncWatchlist } from '@/lib/api';
import type { StockListItem } from '@/lib/types';
import ChangeRate from '@/components/ChangeRate';
import { useWatchlist } from '@/lib/watchlist';
import { useMarketRefresh } from '@/lib/useMarketRefresh';
import { useAuth } from '@/components/AuthProvider';

export default function WatchlistPage() {
  const [stocks, setStocks] = useState<StockListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const { watchlist, toggleStock, isWatched } = useWatchlist();
  // @MX:NOTE: 로그인 상태에 따라 서버 API 또는 localStorage 분기 처리
  const { user, accessToken } = useAuth();
  // 서버 관심종목 ID 목록 (로그인 시)
  const [serverWatchlist, setServerWatchlist] = useState<number[]>([]);
  // 최초 로그인 동기화 여부 추적 (중복 sync 방지)
  const syncedRef = useRef(false);

  // 서버에서 관심종목 ID 목록 로드 후 주식 데이터 조회
  const loadFromServer = useCallback(async (silent = false) => {
    if (!accessToken) return;
    if (!silent) setLoading(true);
    try {
      const items = await fetchUserWatchlist(accessToken);
      const ids = items.map((i) => i.stock_id);
      setServerWatchlist(ids);
      if (ids.length === 0) {
        setStocks([]);
      } else {
        const r = await fetchStocks({ ids: ids.join(','), limit: 200 });
        setStocks(r.stocks);
      }
    } catch {
      // 서버 오류 시 조용히 처리
    } finally {
      if (!silent) setLoading(false);
    }
  }, [accessToken]);

  // localStorage 기반 로드 (비로그인)
  const load = useCallback((silent = false) => {
    if (watchlist.length === 0) {
      setStocks([]);
      setLoading(false);
      return;
    }
    if (!silent) setLoading(true);
    fetchStocks({ ids: watchlist.join(','), limit: 200 })
      .then((r) => setStocks(r.stocks))
      .catch(() => {})
      .finally(() => { if (!silent) setLoading(false); });
  }, [watchlist]);

  // 로그인 상태에 따라 초기 로드 및 동기화 처리
  useEffect(() => {
    if (user && accessToken) {
      // 최초 로그인 시 localStorage 관심종목을 서버에 sync
      if (!syncedRef.current && watchlist.length > 0) {
        syncedRef.current = true;
        syncWatchlist(watchlist, accessToken)
          .catch(() => {}) // 동기화 실패해도 조용히 처리
          .finally(() => loadFromServer());
      } else {
        syncedRef.current = true;
        loadFromServer();
      }
    } else {
      // 비로그인: localStorage 기반
      load();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, accessToken]);

  // Auto-refresh: 15s during market hours, 5min otherwise
  // 로그인 여부에 따라 서버 또는 localStorage 기반 새로고침
  useMarketRefresh(() => {
    if (user && accessToken) {
      loadFromServer(true);
    } else {
      load(true);
    }
  });

  // 로그인 상태의 관심종목 토글 (서버 API 호출)
  const handleToggleStock = useCallback(async (stockId: number) => {
    if (user && accessToken) {
      const isInServer = serverWatchlist.includes(stockId);
      try {
        if (isInServer) {
          await removeFromUserWatchlist(stockId, accessToken);
          setServerWatchlist((prev) => prev.filter((id) => id !== stockId));
          setStocks((prev) => prev.filter((s) => s.id !== stockId));
        } else {
          await addToUserWatchlist(stockId, accessToken);
          setServerWatchlist((prev) => [...prev, stockId]);
          // 추가 후 목록 새로고침
          loadFromServer(true);
        }
      } catch {
        // API 오류 시 조용히 처리
      }
    } else {
      // 비로그인: localStorage 기반 토글
      toggleStock(stockId);
    }
  }, [user, accessToken, serverWatchlist, toggleStock, loadFromServer]);

  const formatMarketCap = (v: number | null) => {
    if (v == null) return '-';
    if (v >= 10000) return `${(v / 10000).toFixed(1)}조`;
    return `${v.toLocaleString()}억`;
  };

  return (
    <div>
      <div className="section-box mb-3">
        <div className="flex items-center gap-3 px-4 py-2.5 border-b border-[#e5e5e5]">
          <div className="flex items-center gap-2">
            <span className="text-[15px] font-semibold text-[#333]">
              <span className="text-[#ffa723] mr-1">★</span>관심종목
            </span>
            {/* 로그인 시 서버 목록 수, 비로그인 시 localStorage 목록 수 표시 */}
            <span className="text-[12px] text-[#999]">
              {user ? serverWatchlist.length : watchlist.length}개
            </span>
          </div>
          <div className="flex-1" />
          {/* 비로그인 사용자에게 기기 간 동기화 안내 배너 */}
          {!user && (
            <span className="text-[11px] text-[#999] bg-[#f5f5f5] px-2 py-0.5 rounded">
              로그인하면 기기 간 동기화됩니다
            </span>
          )}
          <Link
            href="/stocks"
            className="px-3 py-1 text-[12px] font-medium rounded bg-[#f5f5f5] text-[#666] hover:bg-[#e5e5e5] transition-colors"
          >
            전체 종목
          </Link>
        </div>

        {/* 현재 표시 중인 관심종목 수가 0이고 로딩 완료일 때 빈 상태 표시 */}
        {(user ? serverWatchlist.length === 0 : watchlist.length === 0) && !loading ? (
          <div className="px-4 py-16 text-center">
            <p className="text-[#999] text-[14px] mb-2">관심종목이 없습니다.</p>
            <p className="text-[#bbb] text-[12px] mb-4">종목 페이지에서 ☆를 눌러 관심종목을 추가하세요.</p>
            <Link
              href="/stocks"
              className="inline-block px-4 py-2 text-[13px] font-medium bg-[#1261c4] text-white rounded hover:bg-[#0e4f9e] transition-colors"
            >
              종목 보러가기
            </Link>
          </div>
        ) : (
          <>
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
                  Array.from({ length: 5 }).map((_, i) => (
                    <tr key={`sk-${i}`}>
                      <td className="text-center text-[#ffa723]">★</td>
                      <td><div className="skeleton skeleton-text" style={{ width: `${50 + Math.random() * 30}%` }} /></td>
                      {Array.from({ length: 7 }).map((_, j) => (
                        <td key={j} className="text-right"><div className="skeleton skeleton-text-sm" style={{ width: '70%', marginLeft: 'auto' }} /></td>
                      ))}
                    </tr>
                  ))
                ) : (
                  stocks.map((stock) => {
                    const pc = stock.price_change ?? 0;
                    const priceColor = pc > 0 ? 'text-rise' : pc < 0 ? 'text-fall' : 'text-[#333]';
                    const arrow = pc > 0 ? '▲' : pc < 0 ? '▼' : '';
                    const rate = stock.change_rate ?? 0;
                    const rowBg = rate >= 5 ? 'bg-[#fff5f5]' : rate <= -5 ? 'bg-[#f5f5ff]' : '';

                    return (
                      <tr key={stock.id} className={`hover:bg-[#f7f8fa] ${rowBg}`}>
                        <td className="text-center">
                          <button
                            onClick={() => handleToggleStock(stock.id)}
                            className="text-[16px] leading-none text-[#ffa723] transition-colors hover:text-[#cc8400]"
                            title="관심종목 해제"
                          >
                            ★
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
          </>
        )}
      </div>
    </div>
  );
}
