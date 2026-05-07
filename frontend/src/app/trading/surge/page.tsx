'use client';

import { useEffect, useState } from 'react';
import {
  fetchSurgePortfolio,
  fetchSurgePositions,
  fetchSurgeTrades,
  fetchSurgePerformance,
} from '@/lib/api';
import type {
  SurgePortfolioStats,
  SurgePosition,
  SurgeTrade,
  SurgePerformancePoint,
} from '@/lib/types';
import { BarChart, Bar, XAxis, YAxis, Tooltip, Cell, ResponsiveContainer } from 'recharts';

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

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 flex flex-col gap-1">
      <span className="text-[12px] text-gray-500 font-medium">{label}</span>
      <span className="text-[18px] font-bold text-gray-900">{value}</span>
      {sub && <span className="text-[12px] text-gray-400">{sub}</span>}
    </div>
  );
}

function SurgeContent() {
  const [portfolio, setPortfolio] = useState<SurgePortfolioStats | null>(null);
  const [positions, setPositions] = useState<SurgePosition[]>([]);
  const [trades, setTrades] = useState<SurgeTrade[]>([]);
  const [tradeTotal, setTradeTotal] = useState(0);
  const [performance, setPerformance] = useState<SurgePerformancePoint[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      fetchSurgePortfolio(),
      fetchSurgePositions(),
      fetchSurgeTrades(20, 0),
      fetchSurgePerformance(30),
    ])
      .then(([p, pos, t, perf]) => {
        setPortfolio(p);
        setPositions(pos);
        setTrades(t.items);
        setTradeTotal(t.total);
        setPerformance(perf);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="text-center py-8 text-gray-400 text-[13px]">로딩 중...</div>;

  return (
    <div className="flex flex-col gap-6">
      {/* 포트폴리오 요약 */}
      {portfolio && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <StatCard
            label="초기 자본"
            value={`${fmt(portfolio.initial_capital)}원`}
          />
          <StatCard
            label="현재 평가액"
            value={`${fmt(portfolio.current_value)}원`}
            sub={fmtPct(portfolio.return_pct)}
          />
          <StatCard
            label="가용 현금"
            value={`${fmt(portfolio.current_cash)}원`}
          />
          <StatCard
            label="보유 종목 / 총 거래"
            value={`${portfolio.open_positions_count}종목`}
            sub={`청산 ${portfolio.closed_trades_count}건`}
          />
        </div>
      )}

      {/* 보유 포지션 */}
      <div>
        <h2 className="text-[15px] font-bold text-gray-800 mb-3">
          보유 포지션{' '}
          <span className="text-[13px] text-gray-500 font-normal">({positions.length}종목)</span>
        </h2>
        <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="text-left px-4 py-3 font-semibold text-gray-600">종목</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-600">매입단가</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-600">현재가</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-600">수량</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-600">수익률</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-600">보유일</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-600">급등확률</th>
              </tr>
            </thead>
            <tbody>
              {positions.length === 0 ? (
                <tr>
                  <td colSpan={7} className="text-center py-8 text-gray-400">
                    보유 중인 종목이 없습니다
                  </td>
                </tr>
              ) : (
                positions.map((p) => (
                  <tr key={p.id} className="border-b border-gray-100 hover:bg-gray-50 transition-colors">
                    <td className="px-4 py-3">
                      <div className="font-semibold text-gray-800">{p.stock_name}</div>
                      <div className="text-[11px] text-gray-400">{p.stock_code}</div>
                    </td>
                    <td className="px-4 py-3 text-right text-gray-700">{fmt(p.entry_price)}원</td>
                    <td className="px-4 py-3 text-right text-gray-700">
                      {p.current_price != null ? `${fmt(p.current_price)}원` : '-'}
                    </td>
                    <td className="px-4 py-3 text-right text-gray-700">{p.quantity}주</td>
                    <td className={`px-4 py-3 text-right font-semibold ${pctColor(p.pnl_pct)}`}>
                      {fmtPct(p.pnl_pct)}
                    </td>
                    <td className="px-4 py-3 text-right text-gray-400">{p.days_held}일</td>
                    <td className="px-4 py-3 text-right text-gray-600">
                      {p.surge_probability_score != null
                        ? `${(p.surge_probability_score * 100).toFixed(0)}%`
                        : '-'}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* 누적 수익률 차트 */}
      {performance.length > 0 && (
        <div>
          <h2 className="text-[15px] font-bold text-gray-800 mb-3">누적 수익률 (최근 30일)</h2>
          <div className="bg-white rounded-xl border border-gray-200 p-4">
            <ResponsiveContainer width="100%" height={180}>
              <BarChart data={performance} margin={{ top: 4, right: 8, left: 8, bottom: 4 }}>
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 10, fill: '#999' }}
                  tickFormatter={(v: string) => v.slice(5)}
                  interval="preserveStartEnd"
                />
                <YAxis
                  tick={{ fontSize: 10, fill: '#999' }}
                  tickFormatter={(v: number) => `${v.toFixed(1)}%`}
                />
                <Tooltip
                  formatter={(v: number) => [`${v.toFixed(2)}%`, '누적수익률']}
                  labelFormatter={(l: string) => l}
                />
                <Bar dataKey="cumulative_return_pct" radius={[3, 3, 0, 0]}>
                  {performance.map((entry, index) => (
                    <Cell
                      key={index}
                      fill={entry.cumulative_return_pct >= 0 ? '#e12343' : '#1261c4'}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* 청산 거래 이력 */}
      <div>
        <h2 className="text-[15px] font-bold text-gray-800 mb-3">
          청산 이력{' '}
          <span className="text-[13px] text-gray-500 font-normal">({tradeTotal}건)</span>
        </h2>
        <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="text-left px-4 py-3 font-semibold text-gray-600">종목</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-600">매입단가</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-600">매도가</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-600">수량</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-600">매입일</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-600">매도일</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-600">청산사유</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-600">수익률</th>
              </tr>
            </thead>
            <tbody>
              {trades.length === 0 ? (
                <tr>
                  <td colSpan={8} className="text-center py-8 text-gray-400">
                    청산 기록이 없습니다
                  </td>
                </tr>
              ) : (
                trades.map((t) => (
                  <tr key={t.id} className="border-b border-gray-100 hover:bg-gray-50 transition-colors">
                    <td className="px-4 py-3">
                      <div className="font-semibold text-gray-800">{t.stock_name}</div>
                      <div className="text-[11px] text-gray-400">{t.stock_code}</div>
                    </td>
                    <td className="px-4 py-3 text-right text-gray-700">{fmt(t.entry_price)}원</td>
                    <td className="px-4 py-3 text-right text-gray-700">
                      {t.exit_price != null ? `${fmt(t.exit_price)}원` : '-'}
                    </td>
                    <td className="px-4 py-3 text-right text-gray-700">{t.quantity}주</td>
                    <td className="px-4 py-3 text-right text-gray-400">{formatDate(t.entry_date)}</td>
                    <td className="px-4 py-3 text-right text-gray-400">{formatDate(t.exit_date)}</td>
                    <td className="px-4 py-3 text-right text-gray-500">
                      {t.exit_reason === 'stop_loss'
                        ? '손절'
                        : t.exit_reason === 'take_profit'
                        ? '익절'
                        : t.exit_reason === 'max_holding_period'
                        ? '기간만료'
                        : (t.exit_reason ?? '-')}
                    </td>
                    <td className={`px-4 py-3 text-right font-semibold ${pctColor(t.return_pct)}`}>
                      {fmtPct(t.return_pct)}
                    </td>
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

export default function SurgePage() {
  return (
    <div className="max-w-[1200px] mx-auto px-4 py-6">
      <div className="mb-6">
        <h1 className="text-[22px] font-bold text-gray-900">급등 예측 모의투자</h1>
        <p className="text-[13px] text-gray-500 mt-1">AI 급등 예측 시그널 기반 — 손절 -8% / 익절 +15% / 최대 5거래일</p>
      </div>
      <SurgeContent />
    </div>
  );
}
