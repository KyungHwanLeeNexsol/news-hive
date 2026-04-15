'use client';

import { useEffect, useState } from 'react';
import {
  fetchVIPPortfolio,
  fetchVIPPositions,
  fetchVIPTrades,
  fetchKS200Portfolio,
  fetchKS200Positions,
  fetchKS200Trades,
  fetchPaperTradingStats,
  fetchPaperPositions,
  fetchPaperTrades,
  fetchTradingOverview,
} from '@/lib/api';
import type {
  VIPPortfolioStats,
  VIPPosition,
  VIPTradeHistory,
  KS200PortfolioStats,
  KS200Position,
  KS200TradeHistory,
  PaperTradingStats,
  PaperPosition,
  PaperTrade,
  PaperSnapshot,
  TradingOverview,
  TradingModel,
} from '@/lib/types';

type Tab = 'vip' | 'ks200' | 'paper' | 'compare';

function fmt(n: number | null | undefined): string {
  if (n == null) return '-';
  return n.toLocaleString('ko-KR');
}

function fmtPct(n: number | null | undefined): string {
  if (n == null) return '-';
  const sign = n >= 0 ? '+' : '';
  return `${sign}${n.toFixed(2)}%`;
}

function pctColor(n: number | null | undefined): string {
  if (n == null) return 'text-gray-500';
  if (n > 0) return 'text-[#e12343]';
  if (n < 0) return 'text-[#1261c4]';
  return 'text-gray-500';
}

function formatDate(s: string | null | undefined): string {
  if (!s) return '-';
  const d = new Date(s);
  return d.toLocaleDateString('ko-KR', { year: 'numeric', month: '2-digit', day: '2-digit' });
}

// ─── 요약 카드 ───
function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 flex flex-col gap-1">
      <span className="text-[12px] text-gray-500 font-medium">{label}</span>
      <span className="text-[18px] font-bold text-gray-900">{value}</span>
      {sub && <span className="text-[12px] text-gray-400">{sub}</span>}
    </div>
  );
}

// ─── VIP 탭 ───
function VIPTab() {
  const [stats, setStats] = useState<VIPPortfolioStats | null>(null);
  const [positions, setPositions] = useState<VIPPosition[]>([]);
  const [trades, setTrades] = useState<VIPTradeHistory[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([fetchVIPPortfolio(), fetchVIPPositions(), fetchVIPTrades(20)])
      .then(([s, p, t]) => {
        setStats(s);
        setPositions(p);
        setTrades(t);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : '불러오기 실패'))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="text-center py-16 text-gray-400 text-[14px]">로딩 중...</div>;
  if (error) return <div className="text-center py-16 text-red-500 text-[14px]">{error}</div>;
  if (!stats) return null;

  const invested = stats.positions_value;
  const totalPnl = stats.total_value - stats.initial_capital;
  const isProfit = totalPnl >= 0;

  return (
    <div className="flex flex-col gap-6">
      {/* 요약 카드 */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        {/* 총 손익 - 강조 카드 */}
        <div
          className={`rounded-xl border p-4 flex flex-col gap-1 ${isProfit ? 'bg-red-50 border-red-200' : 'bg-blue-50 border-blue-200'}`}
        >
          <span
            className={`text-[11px] font-semibold uppercase tracking-wide ${isProfit ? 'text-red-400' : 'text-blue-400'}`}
          >
            총 손익
          </span>
          <span className={`text-[18px] font-bold ${pctColor(totalPnl)}`}>
            {isProfit ? '+' : ''}
            {fmt(totalPnl)}원
          </span>
          <span className={`text-[13px] font-bold ${pctColor(stats.total_return_pct)}`}>
            {fmtPct(stats.total_return_pct)}
          </span>
        </div>
        {/* 총 평가액 */}
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex flex-col gap-1">
          <span className="text-[11px] text-gray-400 font-medium">총 평가액</span>
          <span className="text-[17px] font-bold text-gray-800">{fmt(stats.total_value)}원</span>
          <span className="text-[11px] text-gray-400">초기자본 {fmt(stats.initial_capital)}원</span>
        </div>
        {/* 잔여 현금 */}
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex flex-col gap-1">
          <span className="text-[11px] text-gray-400 font-medium">잔여 현금</span>
          <span className="text-[17px] font-bold text-gray-700">{fmt(stats.current_cash)}원</span>
        </div>
        {/* 투자 중 */}
        <div className="bg-indigo-50 rounded-xl border border-indigo-200 p-4 flex flex-col gap-1">
          <span className="text-[11px] text-indigo-400 font-medium">투자 중</span>
          <span className="text-[17px] font-bold text-indigo-700">{fmt(invested)}원</span>
          <span className="text-[11px] text-indigo-400">{stats.open_positions}종목</span>
        </div>
        {/* 청산 손익 */}
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex flex-col gap-1">
          <span className="text-[11px] text-gray-400 font-medium">실현 손익</span>
          <span className={`text-[17px] font-bold ${pctColor(stats.realized_pnl)}`}>
            {stats.realized_pnl >= 0 ? '+' : ''}
            {fmt(stats.realized_pnl)}원
          </span>
          <span className="text-[11px] text-gray-400">청산 {stats.closed_trades}건</span>
        </div>
      </div>

      {/* 오픈 포지션 */}
      <div>
        {(() => {
          const totalCurrent = positions.reduce((s, p) => s + p.current_value, 0);
          const totalInvest = positions.reduce((s, p) => s + p.invest_amount, 0);
          const openRet = totalInvest > 0 ? ((totalCurrent - totalInvest) / totalInvest) * 100 : 0;
          return (
            <div className="flex items-baseline justify-between mb-3">
              <h2 className="text-[15px] font-bold text-gray-800">
                오픈 포지션 <span className="text-[13px] text-gray-500 font-normal">({positions.length}종목)</span>
              </h2>
              {positions.length > 0 && (
                <div className="flex items-center gap-3 text-[13px]">
                  <span className="text-gray-500">
                    평가금액 <span className="font-semibold text-gray-800">{fmt(totalCurrent)}원</span>
                  </span>
                  <span className={`font-bold ${openRet >= 0 ? 'text-[#e12343]' : 'text-[#1261c4]'}`}>
                    {openRet >= 0 ? '+' : ''}
                    {openRet.toFixed(2)}%
                  </span>
                </div>
              )}
            </div>
          );
        })()}
        {positions.length === 0 ? (
          <div className="text-center py-8 text-gray-400 text-[13px]">보유 종목이 없습니다</div>
        ) : (
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200">
                  <th className="text-left px-4 py-3 font-semibold text-gray-600">종목</th>
                  <th className="text-right px-4 py-3 font-semibold text-gray-600">매수가</th>
                  <th className="text-right px-4 py-3 font-semibold text-gray-600">수량</th>
                  <th className="text-right px-4 py-3 font-semibold text-gray-600">평가금액</th>
                  <th className="text-right px-4 py-3 font-semibold text-gray-600">수익률</th>
                  <th className="text-right px-4 py-3 font-semibold text-gray-600">비중</th>
                  <th className="text-right px-4 py-3 font-semibold text-gray-600">매수일</th>
                </tr>
              </thead>
              <tbody>
                {[...positions]
                  .sort((a, b) => b.invest_amount - a.invest_amount)
                  .map((p) => {
                    const weight =
                      stats.total_value > 0 ? ((p.invest_amount / stats.total_value) * 100).toFixed(1) : '0.0';
                    return (
                      <tr key={p.id} className="border-b border-gray-100 hover:bg-gray-50 transition-colors">
                        <td className="px-4 py-3 font-semibold text-gray-800">
                          {p.stock_name}
                          {p.stock_code && <span className="ml-1.5 text-gray-400 font-normal">{p.stock_code}</span>}
                        </td>
                        <td className="px-4 py-3 text-right text-gray-700">{fmt(p.entry_price)}원</td>
                        <td className="px-4 py-3 text-right text-gray-700">{fmt(p.quantity)}주</td>
                        <td className="px-4 py-3 text-right font-semibold text-gray-800">{fmt(p.current_value)}원</td>
                        <td className={`px-4 py-3 text-right font-semibold ${pctColor(p.unrealized_pct)}`}>
                          {p.unrealized_pct != null ? fmtPct(p.unrealized_pct) : '-'}
                        </td>
                        <td className="px-4 py-3 text-right text-gray-500">{weight}%</td>
                        <td className="px-4 py-3 text-right text-gray-400">{formatDate(p.entry_date)}</td>
                      </tr>
                    );
                  })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* 거래 내역 */}
      <div>
        <h2 className="text-[15px] font-bold text-gray-800 mb-3">최근 거래 내역</h2>
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="text-left px-4 py-3 font-semibold text-gray-600">종목</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-600">상태</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-600">매수가</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-600">매도가</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-600">손익</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-600">수익률</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-600">매수일</th>
              </tr>
            </thead>
            <tbody>
              {trades.length === 0 ? (
                <tr>
                  <td colSpan={7} className="text-center py-8 text-gray-400">
                    거래 내역이 없습니다
                  </td>
                </tr>
              ) : (
                trades.map((t) => (
                  <tr key={t.id} className="border-b border-gray-100 hover:bg-gray-50 transition-colors">
                    <td className="px-4 py-3 font-semibold text-gray-800">
                      {t.stock_name}
                      {t.stock_code && <span className="ml-1.5 text-gray-400 font-normal">{t.stock_code}</span>}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <span
                        className={`inline-block px-2 py-0.5 rounded text-[11px] font-semibold ${
                          t.is_open
                            ? 'bg-green-50 text-green-700 border border-green-200'
                            : 'bg-gray-50 text-gray-500 border border-gray-200'
                        }`}
                      >
                        {t.is_open ? '보유' : '청산'}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right text-gray-700">{fmt(t.entry_price)}</td>
                    <td className="px-4 py-3 text-right text-gray-700">{t.exit_price ? fmt(t.exit_price) : '-'}</td>
                    <td className={`px-4 py-3 text-right font-semibold ${pctColor(t.pnl)}`}>
                      {t.pnl != null ? `${t.pnl >= 0 ? '+' : ''}${fmt(t.pnl)}` : '-'}
                    </td>
                    <td className={`px-4 py-3 text-right font-semibold ${pctColor(t.return_pct)}`}>
                      {fmtPct(t.return_pct)}
                    </td>
                    <td className="px-4 py-3 text-right text-gray-400">{formatDate(t.entry_date)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ─── KS200 탭 ───
function KS200Tab() {
  const [stats, setStats] = useState<KS200PortfolioStats | null>(null);
  const [positions, setPositions] = useState<KS200Position[]>([]);
  const [trades, setTrades] = useState<KS200TradeHistory[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([fetchKS200Portfolio(), fetchKS200Positions(), fetchKS200Trades(20)])
      .then(([s, p, t]) => {
        setStats(s);
        setPositions(p);
        setTrades(t);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : '불러오기 실패'))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="text-center py-16 text-gray-400 text-[14px]">로딩 중...</div>;
  if (error) return <div className="text-center py-16 text-red-500 text-[14px]">{error}</div>;
  if (!stats) return null;

  return (
    <div className="flex flex-col gap-6">
      {/* 요약 카드 */}
      {(() => {
        const ks200Profit = stats.total_pnl >= 0;
        return (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
            <div
              className={`rounded-xl border p-4 flex flex-col gap-1 ${ks200Profit ? 'bg-red-50 border-red-200' : 'bg-blue-50 border-blue-200'}`}
            >
              <span
                className={`text-[11px] font-semibold uppercase tracking-wide ${ks200Profit ? 'text-red-400' : 'text-blue-400'}`}
              >
                총 손익
              </span>
              <span className={`text-[18px] font-bold ${pctColor(stats.total_pnl)}`}>
                {ks200Profit ? '+' : ''}
                {fmt(stats.total_pnl)}원
              </span>
              <span className={`text-[13px] font-bold ${pctColor(stats.total_return_pct)}`}>
                {fmtPct(stats.total_return_pct)}
              </span>
            </div>
            <div className="bg-white rounded-xl border border-gray-200 p-4 flex flex-col gap-1">
              <span className="text-[11px] text-gray-400 font-medium">총 평가액</span>
              <span className="text-[17px] font-bold text-gray-800">{fmt(stats.total_value)}원</span>
              <span className="text-[11px] text-gray-400">초기자본 {fmt(stats.initial_capital)}원</span>
            </div>
            <div className="bg-white rounded-xl border border-gray-200 p-4 flex flex-col gap-1">
              <span className="text-[11px] text-gray-400 font-medium">잔여 현금</span>
              <span className="text-[17px] font-bold text-gray-700">{fmt(stats.current_cash)}원</span>
            </div>
            <div className="bg-indigo-50 rounded-xl border border-indigo-200 p-4 flex flex-col gap-1">
              <span className="text-[11px] text-indigo-400 font-medium">투자 중</span>
              <span className="text-[17px] font-bold text-indigo-700">{fmt(stats.position_value)}원</span>
              <span className="text-[11px] text-indigo-400">{stats.open_positions}종목</span>
            </div>
            <div className="bg-white rounded-xl border border-gray-200 p-4 flex flex-col gap-1">
              <span className="text-[11px] text-gray-400 font-medium">최대 운용</span>
              <span className="text-[17px] font-bold text-gray-700">{stats.max_positions}종목</span>
              <span className="text-[11px] text-gray-400">실현손익 {fmt(stats.realized_pnl)}원</span>
            </div>
          </div>
        );
      })()}

      {/* 포지션 상태 */}
      <div className="flex items-center gap-2 text-[13px] text-gray-500">
        <span className="font-semibold text-gray-700">{positions.length}</span>개 포지션 운용 중
        <span className="text-gray-300">|</span>
        최대 <span className="font-semibold text-gray-700">{stats.max_positions}</span>개
      </div>

      {/* 오픈 포지션 */}
      <div>
        {(() => {
          const totalCurrent = positions.reduce((s, p) => s + p.current_value, 0);
          const totalInvest = positions.reduce((s, p) => s + p.entry_price * p.quantity, 0);
          const openRet = totalInvest > 0 ? ((totalCurrent - totalInvest) / totalInvest) * 100 : 0;
          return (
            <div className="flex items-baseline justify-between mb-3">
              <h2 className="text-[15px] font-bold text-gray-800">
                오픈 포지션 <span className="text-[13px] text-gray-500 font-normal">({positions.length}종목)</span>
              </h2>
              {positions.length > 0 && (
                <div className="flex items-center gap-3 text-[13px]">
                  <span className="text-gray-500">
                    평가금액 <span className="font-semibold text-gray-800">{fmt(totalCurrent)}원</span>
                  </span>
                  <span className={`font-bold ${openRet >= 0 ? 'text-[#e12343]' : 'text-[#1261c4]'}`}>
                    {openRet >= 0 ? '+' : ''}
                    {openRet.toFixed(2)}%
                  </span>
                </div>
              )}
            </div>
          );
        })()}
        {positions.length === 0 ? (
          <div className="text-center py-8 text-gray-400 text-[13px]">
            보유 종목이 없습니다 — 평일 15:30 스캔 후 익일 09:05에 매수됩니다
          </div>
        ) : (
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200">
                  <th className="text-left px-4 py-3 font-semibold text-gray-600">종목명</th>
                  <th className="text-right px-4 py-3 font-semibold text-gray-600">매수가</th>
                  <th className="text-right px-4 py-3 font-semibold text-gray-600">수량</th>
                  <th className="text-right px-4 py-3 font-semibold text-gray-600">평가금액</th>
                  <th className="text-right px-4 py-3 font-semibold text-gray-600">수익률</th>
                  <th className="text-right px-4 py-3 font-semibold text-gray-600">매수일</th>
                </tr>
              </thead>
              <tbody>
                {[...positions]
                  .sort((a, b) => b.current_value - a.current_value)
                  .map((p) => (
                    <tr key={p.id} className="border-b border-gray-100 hover:bg-gray-50 transition-colors">
                      <td className="px-4 py-3 font-semibold text-gray-800">{p.stock_name}</td>
                      <td className="px-4 py-3 text-right text-gray-700">{fmt(p.entry_price)}원</td>
                      <td className="px-4 py-3 text-right text-gray-700">{fmt(p.quantity)}주</td>
                      <td className="px-4 py-3 text-right font-semibold text-gray-800">{fmt(p.current_value)}원</td>
                      <td className={`px-4 py-3 text-right font-semibold ${pctColor(p.unrealized_pct)}`}>
                        {p.unrealized_pct != null ? fmtPct(p.unrealized_pct) : '-'}
                      </td>
                      <td className="px-4 py-3 text-right text-gray-400">{formatDate(p.entry_date)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* 거래 내역 */}
      <div>
        <h2 className="text-[15px] font-bold text-gray-800 mb-3">최근 거래 내역</h2>
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="text-left px-4 py-3 font-semibold text-gray-600">종목명</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-600">상태</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-600">매수가</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-600">매도가</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-600">손익</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-600">수익률</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-600">매수일</th>
              </tr>
            </thead>
            <tbody>
              {trades.length === 0 ? (
                <tr>
                  <td colSpan={7} className="text-center py-8 text-gray-400">
                    거래 내역이 없습니다
                  </td>
                </tr>
              ) : (
                trades.map((t) => (
                  <tr key={t.id} className="border-b border-gray-100 hover:bg-gray-50 transition-colors">
                    <td className="px-4 py-3 font-semibold text-gray-800">{t.stock_name}</td>
                    <td className="px-4 py-3 text-right">
                      <span
                        className={`inline-block px-2 py-0.5 rounded text-[11px] font-semibold ${
                          t.is_open
                            ? 'bg-green-50 text-green-700 border border-green-200'
                            : 'bg-gray-50 text-gray-500 border border-gray-200'
                        }`}
                      >
                        {t.is_open ? '보유' : '청산'}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right text-gray-700">{fmt(t.entry_price)}</td>
                    <td className="px-4 py-3 text-right text-gray-700">{t.exit_price ? fmt(t.exit_price) : '-'}</td>
                    <td className={`px-4 py-3 text-right font-semibold ${pctColor(t.pnl)}`}>
                      {t.pnl != null ? `${t.pnl >= 0 ? '+' : ''}${fmt(t.pnl)}` : '-'}
                    </td>
                    <td className={`px-4 py-3 text-right font-semibold ${pctColor(t.return_pct)}`}>
                      {fmtPct(t.return_pct)}
                    </td>
                    <td className="px-4 py-3 text-right text-gray-400">{formatDate(t.entry_date)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ─── AI 페이퍼 트레이딩 탭 ───
function PaperTradingTab() {
  const [stats, setStats] = useState<PaperTradingStats | null>(null);
  const [positions, setPositions] = useState<PaperPosition[]>([]);
  const [trades, setTrades] = useState<PaperTrade[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([fetchPaperTradingStats(), fetchPaperPositions(), fetchPaperTrades(50)])
      .then(([s, p, t]) => {
        setStats(s);
        setPositions(p);
        setTrades(t);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const exitReasonLabel: Record<string, string> = {
    target_hit: '목표가 도달',
    stop_loss: '손절',
    timeout: '기간만료',
    signal_sell: '매도시그널',
  };

  if (loading) return <div className="text-center py-16 text-gray-400 text-[14px]">로딩 중...</div>;

  if (!stats) {
    return (
      <div className="bg-white rounded-xl border border-gray-200 p-10 text-center">
        <p className="text-[15px] text-gray-700 font-medium mb-1">페이퍼 트레이딩 데이터가 없습니다</p>
        <p className="text-[13px] text-gray-400">
          AI 펀드매니저가 시그널을 기반으로 모의 매매를 실행하면 여기에 표시됩니다.
        </p>
      </div>
    );
  }

  // KS200과 동일하게 미실현 포지션 평가금액을 포함한 총 손익/수익률 사용
  const returnPct = stats.total_return_pct ?? 0;
  const totalValue = stats.initial_capital + stats.total_pnl;
  const paperProfit = stats.total_pnl >= 0;

  return (
    <div className="flex flex-col gap-6">
      {/* 요약 카드 */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        {/* 총 손익 */}
        <div
          className={`rounded-xl border p-4 flex flex-col gap-1 ${paperProfit ? 'bg-red-50 border-red-200' : 'bg-blue-50 border-blue-200'}`}
        >
          <span
            className={`text-[11px] font-semibold uppercase tracking-wide ${paperProfit ? 'text-red-400' : 'text-blue-400'}`}
          >
            총 손익
          </span>
          <span className={`text-[18px] font-bold ${pctColor(stats.total_pnl)}`}>
            {paperProfit ? '+' : ''}
            {fmt(stats.total_pnl)}원
          </span>
          <span className={`text-[13px] font-bold ${pctColor(returnPct)}`}>
            {returnPct >= 0 ? '+' : ''}
            {returnPct.toFixed(2)}%
          </span>
        </div>
        {/* 총 자산 */}
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex flex-col gap-1">
          <span className="text-[11px] text-gray-400 font-medium">총 자산</span>
          <span className="text-[17px] font-bold text-gray-800">{fmt(totalValue)}원</span>
          <span className="text-[11px] text-gray-400">초기자본 {fmt(stats.initial_capital)}원</span>
        </div>
        {/* 잔여 현금 */}
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex flex-col gap-1">
          <span className="text-[11px] text-gray-400 font-medium">잔여 현금</span>
          <span className="text-[17px] font-bold text-gray-700">{fmt(stats.current_cash)}원</span>
        </div>
        {/* 투자 중 */}
        <div className="bg-indigo-50 rounded-xl border border-indigo-200 p-4 flex flex-col gap-1">
          <span className="text-[11px] text-indigo-400 font-medium">투자 중</span>
          <span className="text-[17px] font-bold text-indigo-700">{stats.open_positions}종목</span>
          <span className="text-[11px] text-indigo-400">보유 포지션</span>
        </div>
        {/* 승률 */}
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex flex-col gap-1">
          <span className="text-[11px] text-gray-400 font-medium">승률</span>
          <span className={`text-[18px] font-bold ${stats.win_rate >= 50 ? 'text-[#e12343]' : 'text-[#1261c4]'}`}>
            {stats.win_rate.toFixed(1)}%
          </span>
          <span className="text-[11px] text-gray-400">청산 {stats.closed_trades}건 중</span>
        </div>
        {/* 코스피 대비 — 시장중립 알파 (2026-04 교정) */}
        <div
          className={`rounded-xl border p-4 flex flex-col gap-1 ${
            stats.alpha_warning
              ? 'bg-blue-50 border-blue-300'
              : 'bg-white border-gray-200'
          }`}
        >
          <span className="text-[11px] text-gray-500 font-medium flex items-center gap-1">
            코스피 대비
            {stats.alpha_warning && (
              <span className="inline-block px-1.5 py-0 rounded text-[10px] font-bold bg-blue-100 text-blue-700 border border-blue-200">
                시장 못이김
              </span>
            )}
          </span>
          <span className={`text-[18px] font-bold ${pctColor(stats.alpha_pct ?? null)}`}>
            {stats.alpha_pct == null
              ? '-'
              : `${stats.alpha_pct >= 0 ? '+' : ''}${stats.alpha_pct.toFixed(2)}%`}
          </span>
          <span className="text-[11px] text-gray-400">
            {stats.benchmark_cumulative_return_pct == null
              ? 'KOSPI 데이터 없음'
              : `KOSPI ${stats.benchmark_cumulative_return_pct >= 0 ? '+' : ''}${stats.benchmark_cumulative_return_pct.toFixed(2)}% / 내 ${stats.cumulative_return >= 0 ? '+' : ''}${stats.cumulative_return.toFixed(2)}%`}
            {stats.alpha_win_rate != null && stats.alpha_sample_size != null && stats.alpha_sample_size > 0 && (
              <>
                <br />
                시장초과 승률 {stats.alpha_win_rate.toFixed(1)}% ({stats.alpha_sample_size}건)
              </>
            )}
          </span>
        </div>
      </div>

      {/* 오픈 포지션 */}
      <div>
        {(() => {
          const totalCurrent = positions.reduce(
            (s, p) => s + (p.current_price != null ? p.current_price * p.quantity : p.invest_amount),
            0,
          );
          const totalInvest = positions.reduce((s, p) => s + p.invest_amount, 0);
          const openRet = totalInvest > 0 ? ((totalCurrent - totalInvest) / totalInvest) * 100 : 0;
          return (
            <div className="flex items-baseline justify-between mb-3">
              <h2 className="text-[15px] font-bold text-gray-800">
                오픈 포지션 <span className="text-[13px] text-gray-500 font-normal">({positions.length}건)</span>
              </h2>
              {positions.length > 0 && (
                <div className="flex items-center gap-3 text-[13px]">
                  <span className="text-gray-500">
                    평가금액 <span className="font-semibold text-gray-800">{fmt(totalCurrent)}원</span>
                  </span>
                  <span className={`font-bold ${openRet >= 0 ? 'text-[#e12343]' : 'text-[#1261c4]'}`}>
                    {openRet >= 0 ? '+' : ''}
                    {openRet.toFixed(2)}%
                  </span>
                </div>
              )}
            </div>
          );
        })()}
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          {positions.length === 0 ? (
            <div className="py-8 text-center text-[13px] text-gray-400">오픈 포지션이 없습니다</div>
          ) : (
            <table className="w-full text-[13px]">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200">
                  <th className="text-left px-4 py-3 font-semibold text-gray-600">종목명</th>
                  <th className="text-right px-4 py-3 font-semibold text-gray-600">진입가</th>
                  <th className="text-right px-4 py-3 font-semibold text-gray-600">수량</th>
                  <th className="text-right px-4 py-3 font-semibold text-gray-600">투자금액</th>
                  <th className="text-right px-4 py-3 font-semibold text-gray-600">평가금액</th>
                  <th className="text-right px-4 py-3 font-semibold text-gray-600">수익률</th>
                  <th className="text-right px-4 py-3 font-semibold text-gray-600">목표가</th>
                  <th className="text-right px-4 py-3 font-semibold text-gray-600">손절가</th>
                  <th className="text-right px-4 py-3 font-semibold text-gray-600">진입일</th>
                </tr>
              </thead>
              <tbody>
                {[...positions]
                  .sort((a, b) => b.invest_amount - a.invest_amount)
                  .map((pos, i) => (
                    <tr key={i} className="border-b border-gray-100 hover:bg-gray-50 transition-colors">
                      <td className="px-4 py-3 font-semibold text-gray-800">{pos.stock_name}</td>
                      <td className="px-4 py-3 text-right text-gray-700">{fmt(pos.entry_price)}원</td>
                      <td className="px-4 py-3 text-right text-gray-700">{fmt(pos.quantity)}</td>
                      <td className="px-4 py-3 text-right text-gray-700">{fmt(pos.invest_amount)}원</td>
                      <td className="px-4 py-3 text-right text-gray-700">
                        {pos.current_price != null ? `${fmt(pos.current_price * pos.quantity)}원` : '-'}
                      </td>
                      <td
                        className={`px-4 py-3 text-right font-semibold ${pos.unrealized_pct == null ? 'text-gray-400' : pos.unrealized_pct >= 0 ? 'text-[#e12343]' : 'text-[#1261c4]'}`}
                      >
                        {pos.unrealized_pct != null
                          ? `${pos.unrealized_pct >= 0 ? '+' : ''}${pos.unrealized_pct.toFixed(2)}%`
                          : '-'}
                      </td>
                      <td className="px-4 py-3 text-right text-[#e12343] font-semibold">{fmt(pos.target_price)}원</td>
                      <td className="px-4 py-3 text-right text-[#1261c4] font-semibold">{fmt(pos.stop_loss)}원</td>
                      <td className="px-4 py-3 text-right text-gray-400">{pos.entry_date.slice(0, 10)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* 거래 내역 */}
      <div>
        <h2 className="text-[15px] font-bold text-gray-800 mb-3">
          거래 내역 <span className="text-[13px] text-gray-500 font-normal">({trades.length}건)</span>
        </h2>
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          {trades.length === 0 ? (
            <div className="py-8 text-center text-[13px] text-gray-400">거래 내역이 없습니다</div>
          ) : (
            <table className="w-full text-[13px]">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200">
                  <th className="text-left px-4 py-3 font-semibold text-gray-600">종목명</th>
                  <th className="text-right px-4 py-3 font-semibold text-gray-600">진입가</th>
                  <th className="text-right px-4 py-3 font-semibold text-gray-600">청산가</th>
                  <th className="text-right px-4 py-3 font-semibold text-gray-600">손익</th>
                  <th className="text-right px-4 py-3 font-semibold text-gray-600">수익률</th>
                  <th className="text-center px-4 py-3 font-semibold text-gray-600">청산사유</th>
                  <th className="text-right px-4 py-3 font-semibold text-gray-600">진입일</th>
                  <th className="text-right px-4 py-3 font-semibold text-gray-600">청산일</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((trade, i) => (
                  <tr
                    key={i}
                    className={`border-b border-gray-100 hover:bg-gray-50 transition-colors ${trade.is_open ? 'bg-indigo-50/40' : ''}`}
                  >
                    <td className="px-4 py-3 font-semibold text-gray-800">{trade.stock_name}</td>
                    <td className="px-4 py-3 text-right text-gray-700">{fmt(trade.entry_price)}원</td>
                    <td className="px-4 py-3 text-right text-gray-700">
                      {trade.exit_price != null ? `${fmt(trade.exit_price)}원` : '-'}
                    </td>
                    <td className={`px-4 py-3 text-right font-semibold ${pctColor(trade.pnl)}`}>
                      {trade.pnl != null ? `${trade.pnl >= 0 ? '+' : ''}${fmt(trade.pnl)}원` : '-'}
                    </td>
                    <td className={`px-4 py-3 text-right font-semibold ${pctColor(trade.return_pct)}`}>
                      {trade.return_pct != null ? `${trade.return_pct >= 0 ? '+' : ''}${trade.return_pct.toFixed(2)}%` : '-'}
                    </td>
                    <td className="px-4 py-3 text-center">
                      {trade.is_open ? (
                        <span className="inline-block px-2 py-0.5 rounded text-[11px] font-medium bg-indigo-50 text-indigo-700 border border-indigo-200">
                          보유 중
                        </span>
                      ) : (
                        <span
                          className={`inline-block px-2 py-0.5 rounded text-[11px] font-medium ${
                            trade.exit_reason === 'target_hit'
                              ? 'bg-green-50 text-green-700 border border-green-200'
                              : trade.exit_reason === 'stop_loss'
                                ? 'bg-red-50 text-red-700 border border-red-200'
                                : 'bg-gray-50 text-gray-500 border border-gray-200'
                          }`}
                        >
                          {(trade.exit_reason && exitReasonLabel[trade.exit_reason]) || trade.exit_reason || '-'}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right text-gray-400">{trade.entry_date.slice(0, 10)}</td>
                    <td className="px-4 py-3 text-right text-gray-400">
                      {trade.exit_date ? trade.exit_date.slice(0, 10) : '-'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── 모델 뱃지 ───
const MODEL_BADGE: Record<TradingModel, { bg: string; text: string; label: string }> = {
  paper: { bg: 'bg-violet-100 border-violet-300', text: 'text-violet-700', label: 'AI펀드' },
  ks200: { bg: 'bg-amber-100 border-amber-300', text: 'text-amber-700', label: 'KS200' },
  vip: { bg: 'bg-emerald-100 border-emerald-300', text: 'text-emerald-700', label: 'VIP추종' },
};

function ModelBadge({ model }: { model: TradingModel }) {
  const b = MODEL_BADGE[model];
  return (
    <span className={`inline-block px-2 py-0.5 rounded border text-[11px] font-bold ${b.bg} ${b.text}`}>
      {b.label}
    </span>
  );
}

// ─── 전체 비교 탭 (경쟁 대시보드) ───
function ComparisonTab() {
  const [data, setData] = useState<TradingOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tradeFilter, setTradeFilter] = useState<TradingModel | 'all'>('all');

  useEffect(() => {
    fetchTradingOverview()
      .then(setData)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : '불러오기 실패'))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="text-center py-16 text-gray-400 text-[14px]">로딩 중...</div>;
  if (error) return <div className="text-center py-16 text-red-500 text-[14px]">{error}</div>;
  if (!data) return null;

  // 수익률 기준 내림차순 정렬 → 순위 결정
  const rankedModels = (['paper', 'ks200', 'vip'] as TradingModel[])
    .map((m) => ({ model: m, ...data.models[m] }))
    .sort((a, b) => b.total_return_pct - a.total_return_pct);

  const rankMedal = ['🥇', '🥈', '🥉'];
  const maxAbsReturn = Math.max(...rankedModels.map((m) => Math.abs(m.total_return_pct)), 1);

  // 칸반 포지션: 모델별 그룹화
  const positionsByModel = rankedModels.reduce<Record<string, typeof data.positions>>((acc, { model }) => {
    acc[model] = data.positions.filter((p) => p.model === model);
    return acc;
  }, {});

  // 포지션 카드 색상 (한국: 빨강=수익, 파랑=손실)
  function positionCardClass(pct: number | null): string {
    if (pct == null) return 'bg-gray-50 border-gray-200';
    if (pct > 10) return 'bg-red-200 border-red-300';
    if (pct > 5) return 'bg-red-100 border-red-200';
    if (pct > 0) return 'bg-red-50 border-red-100';
    if (pct > -5) return 'bg-blue-50 border-blue-100';
    return 'bg-blue-100 border-blue-200';
  }

  const filteredTrades =
    tradeFilter === 'all' ? data.trades : data.trades.filter((t) => t.model === tradeFilter);

  const exitReasonLabel: Record<string, string> = {
    target_hit: '목표가',
    stop_loss: '손절',
    timeout: '기간만료',
    signal_sell: '매도시그널',
  };

  return (
    <div className="flex flex-col gap-6">
      {/* ─── 섹션 1: 순위 비교 카드 ─── */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {rankedModels.map(({ model, label, total_return_pct, win_rate, open_positions, closed_trades, total_pnl }, idx) => {
          const isPos = total_return_pct >= 0;
          const barWidth = Math.round((Math.abs(total_return_pct) / maxAbsReturn) * 100);
          const cardBg = MODEL_BADGE[model as TradingModel].bg;
          return (
            <div
              key={model}
              className={`rounded-xl border p-5 flex flex-col gap-3 ${
                idx === 0 ? 'ring-2 ring-offset-2 ring-amber-400 shadow-lg' : 'shadow-sm'
              } ${cardBg}`}
            >
              {/* 순위 메달 + 모델명 */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-[22px] leading-none">{rankMedal[idx]}</span>
                  <span className="text-[13px] font-bold text-gray-700">{label}</span>
                </div>
                <ModelBadge model={model} />
              </div>
              {/* 수익률 대형 */}
              <div>
                <span className={`text-[34px] font-bold leading-none ${pctColor(total_return_pct)}`}>
                  {total_return_pct >= 0 ? '+' : ''}{total_return_pct.toFixed(2)}%
                </span>
              </div>
              {/* 상대적 수익률 바 */}
              <div className="h-2 bg-white/60 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all ${isPos ? 'bg-red-500' : 'bg-blue-500'}`}
                  style={{ width: `${barWidth}%` }}
                />
              </div>
              {/* 3분할 지표 */}
              <div className="grid grid-cols-3 gap-1 text-center pt-1">
                <div>
                  <div className={`text-[16px] font-bold ${win_rate >= 50 ? 'text-[#e12343]' : 'text-[#1261c4]'}`}>
                    {win_rate.toFixed(0)}%
                  </div>
                  <div className="text-[11px] text-gray-400">승률</div>
                </div>
                <div>
                  <div className="text-[16px] font-bold text-gray-700">{open_positions}</div>
                  <div className="text-[11px] text-gray-400">보유종목</div>
                </div>
                <div>
                  <div className="text-[16px] font-bold text-gray-700">{closed_trades}</div>
                  <div className="text-[11px] text-gray-400">청산건수</div>
                </div>
              </div>
              {/* 누적 손익 */}
              <div className="pt-2 border-t border-gray-200/60">
                <span className={`text-[13px] font-semibold ${pctColor(total_pnl)}`}>
                  {total_pnl >= 0 ? '+' : ''}{fmt(total_pnl)}원
                </span>
                <span className="text-[11px] text-gray-400 ml-1">누적 손익</span>
              </div>
            </div>
          );
        })}
      </div>

      {/* ─── 섹션 2: 포지션 칸반 (3열) ─── */}
      <div>
        <h2 className="text-[15px] font-bold text-gray-800 mb-3">
          오픈 포지션
          <span className="text-[13px] text-gray-500 font-normal ml-1">({data.positions.length}종목)</span>
        </h2>
        {data.positions.length === 0 ? (
          <div className="text-center py-8 text-gray-400 text-[13px]">보유 종목이 없습니다</div>
        ) : (
          <div className="grid grid-cols-3 gap-3">
            {rankedModels.map(({ model }, idx) => {
              const positions = positionsByModel[model] ?? [];
              const badge = MODEL_BADGE[model];
              return (
                <div key={model} className="flex flex-col gap-2">
                  {/* 열 헤더 */}
                  <div className={`flex items-center gap-1.5 px-3 py-2 rounded-lg border ${badge.bg}`}>
                    <span className="text-[14px] leading-none">{rankMedal[idx]}</span>
                    <span className={`text-[12px] font-bold ${badge.text}`}>{badge.label}</span>
                    <span className={`ml-auto text-[11px] font-medium ${badge.text} opacity-70`}>
                      {positions.length}종목
                    </span>
                  </div>
                  {/* 포지션 카드 */}
                  {positions.length === 0 ? (
                    <div className="text-center py-6 text-gray-400 text-[12px] bg-gray-50 rounded-lg border border-dashed border-gray-200">
                      보유 없음
                    </div>
                  ) : (
                    positions.map((p, i) => (
                      <div
                        key={i}
                        className={`rounded-lg border p-3 flex flex-col gap-1.5 ${positionCardClass(p.unrealized_pct)}`}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <span className="text-[13px] font-bold text-gray-800 leading-tight">{p.stock_name}</span>
                          <span className={`text-[15px] font-bold flex-shrink-0 ${pctColor(p.unrealized_pct)}`}>
                            {p.unrealized_pct != null
                              ? `${p.unrealized_pct >= 0 ? '+' : ''}${p.unrealized_pct.toFixed(1)}%`
                              : '-'}
                          </span>
                        </div>
                        <div className="flex items-center justify-between text-[11px] text-gray-500">
                          <span>{fmt(p.invest_amount)}원</span>
                          <span>{p.entry_date ? p.entry_date.slice(0, 10) : '-'}</span>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* ─── 섹션 3: 거래 피드 ─── */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-[15px] font-bold text-gray-800">
            최근 거래
            <span className="text-[13px] text-gray-500 font-normal ml-1">({filteredTrades.length}건)</span>
          </h2>
          <div className="flex gap-1 bg-gray-100 p-1 rounded-lg">
            {(['all', 'paper', 'ks200', 'vip'] as const).map((f) => (
              <button
                key={f}
                type="button"
                onClick={() => setTradeFilter(f)}
                className={`px-3 py-1 rounded text-[12px] font-semibold transition-all ${
                  tradeFilter === f ? 'bg-white text-[#1261c4] shadow-sm' : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                {f === 'all' ? '전체' : MODEL_BADGE[f].label}
              </button>
            ))}
          </div>
        </div>
        {filteredTrades.length === 0 ? (
          <div className="text-center py-8 text-gray-400 text-[13px]">거래 내역이 없습니다</div>
        ) : (
          <div className="flex flex-col gap-1.5">
            {filteredTrades.map((t, i) => {
              const isWin = t.return_pct != null && t.return_pct > 0;
              return (
                <div
                  key={i}
                  className={`flex items-center gap-3 px-4 py-2.5 rounded-lg border text-[13px] ${
                    isWin
                      ? 'bg-red-50/60 border-red-100'
                      : t.return_pct != null
                      ? 'bg-blue-50/60 border-blue-100'
                      : 'bg-white border-gray-100'
                  }`}
                >
                  <ModelBadge model={t.model} />
                  <span className="font-semibold text-gray-800 flex-1 min-w-0 truncate">{t.stock_name}</span>
                  {t.exit_reason && (
                    <span
                      className={`text-[11px] px-1.5 py-0.5 rounded font-medium flex-shrink-0 ${
                        t.exit_reason === 'target_hit'
                          ? 'bg-red-100 text-red-700'
                          : t.exit_reason === 'stop_loss'
                          ? 'bg-blue-100 text-blue-700'
                          : 'bg-gray-100 text-gray-600'
                      }`}
                    >
                      {exitReasonLabel[t.exit_reason] ?? t.exit_reason}
                    </span>
                  )}
                  <span className={`font-bold flex-shrink-0 ${pctColor(t.return_pct)}`}>
                    {t.return_pct != null ? `${t.return_pct >= 0 ? '+' : ''}${t.return_pct.toFixed(2)}%` : '-'}
                  </span>
                  <span className={`flex-shrink-0 text-[12px] ${pctColor(t.pnl)}`}>
                    {t.pnl != null ? `${t.pnl >= 0 ? '+' : ''}${fmt(t.pnl)}원` : ''}
                  </span>
                  <span className="text-gray-400 flex-shrink-0 text-[12px]">
                    {t.exit_date ? t.exit_date.slice(0, 10) : '-'}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── 메인 페이지 ───
export default function TradingPage() {
  const [tab, setTab] = useState<Tab>('compare');

  const tabs: { key: Tab; label: string; desc: string }[] = [
    { key: 'compare', label: '전체 비교', desc: '3개 모델 통합 포트폴리오 비교 — 종목별 매수/매도가, 손익률 한눈에' },
    { key: 'vip', label: 'VIP 추종', desc: '브이아이피자산운용 대량보유 공시 추종' },
    { key: 'ks200', label: 'KS200 스윙', desc: 'Stochastics Slow + 이격도 기반 스윙 트레이딩' },
    { key: 'paper', label: 'AI 펀드매니저', desc: 'AI 펀드매니저 시그널 기반 페이퍼 트레이딩' },
  ];

  return (
    <div className="max-w-[1200px] mx-auto px-4 py-6">
      {/* 헤더 */}
      <div className="mb-6">
        <h1 className="text-[22px] font-bold text-gray-900">모의투자 포트폴리오</h1>
        <p className="text-[13px] text-gray-500 mt-1">모델별 페이퍼 트레이딩 현황</p>
      </div>

      {/* 탭 */}
      <div className="flex gap-1 mb-6 bg-gray-100 p-1 rounded-xl w-fit">
        {tabs.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setTab(t.key)}
            className={`px-5 py-2 rounded-lg text-[13px] font-semibold transition-all ${
              tab === t.key ? 'bg-white text-[#1261c4] shadow-sm' : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* 탭 설명 */}
      <p className="text-[12px] text-gray-400 mb-5">{tabs.find((t) => t.key === tab)?.desc}</p>

      {/* 콘텐츠 */}
      {tab === 'compare' && <ComparisonTab />}
      {tab === 'vip' && <VIPTab />}
      {tab === 'ks200' && <KS200Tab />}
      {tab === 'paper' && <PaperTradingTab />}
    </div>
  );
}
