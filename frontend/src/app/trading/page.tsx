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
  fetchPaperSnapshots,
  resetPaperTrading,
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
} from '@/lib/types';

type Tab = 'vip' | 'ks200' | 'paper';

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

  return (
    <div className="flex flex-col gap-6">
      {/* 요약 카드 */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        <StatCard label="초기 자본" value={`${fmt(stats.initial_capital)}원`} />
        <StatCard label="잔여 현금" value={`${fmt(stats.current_cash)}원`} />
        <StatCard label="투자 중" value={`${fmt(invested)}원`} />
        <StatCard label="총 평가액" value={`${fmt(stats.total_value)}원`} />
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex flex-col gap-1">
          <span className="text-[12px] text-gray-500 font-medium">총 손익</span>
          <span className={`text-[18px] font-bold ${pctColor(totalPnl)}`}>
            {totalPnl >= 0 ? '+' : ''}{fmt(totalPnl)}원
          </span>
          <span className={`text-[12px] font-semibold ${pctColor(stats.total_return_pct)}`}>
            {fmtPct(stats.total_return_pct)}
          </span>
        </div>
      </div>

      {/* 오픈 포지션 */}
      <div>
        <h2 className="text-[15px] font-bold text-gray-800 mb-3">
          오픈 포지션 <span className="text-[13px] text-gray-500 font-normal">({positions.length}종목)</span>
        </h2>
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
                  <th className="text-right px-4 py-3 font-semibold text-gray-600">비중</th>
                  <th className="text-right px-4 py-3 font-semibold text-gray-600">매수일</th>
                </tr>
              </thead>
              <tbody>
                {[...positions].sort((a, b) => b.invest_amount - a.invest_amount).map((p) => {
                  const weight = stats.total_value > 0
                    ? (p.invest_amount / stats.total_value * 100).toFixed(1)
                    : '0.0';
                  return (
                    <tr key={p.id} className="border-b border-gray-100 hover:bg-gray-50 transition-colors">
                      <td className="px-4 py-3 font-semibold text-gray-800">
                        {p.stock_name}
                        {p.stock_code && (
                          <span className="ml-1.5 text-gray-400 font-normal">{p.stock_code}</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right text-gray-700">{fmt(p.entry_price)}원</td>
                      <td className="px-4 py-3 text-right text-gray-700">{fmt(p.quantity)}주</td>
                      <td className="px-4 py-3 text-right font-semibold text-gray-800">{fmt(p.invest_amount)}원</td>
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
                  <td colSpan={7} className="text-center py-8 text-gray-400">거래 내역이 없습니다</td>
                </tr>
              ) : trades.map((t) => (
                <tr key={t.id} className="border-b border-gray-100 hover:bg-gray-50 transition-colors">
                  <td className="px-4 py-3 font-semibold text-gray-800">
                    {t.stock_name}
                    {t.stock_code && <span className="ml-1.5 text-gray-400 font-normal">{t.stock_code}</span>}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <span className={`inline-block px-2 py-0.5 rounded text-[11px] font-semibold ${
                      t.is_open
                        ? 'bg-green-50 text-green-700 border border-green-200'
                        : 'bg-gray-50 text-gray-500 border border-gray-200'
                    }`}>
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
              ))}
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
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        <StatCard label="초기 자본" value={`${fmt(stats.initial_capital)}원`} />
        <StatCard label="잔여 현금" value={`${fmt(stats.current_cash)}원`} />
        <StatCard label="투자 중" value={`${fmt(stats.position_value)}원`} />
        <StatCard label="총 평가액" value={`${fmt(stats.total_value)}원`} />
        <div className="bg-white rounded-xl border border-gray-200 p-4 flex flex-col gap-1">
          <span className="text-[12px] text-gray-500 font-medium">총 손익</span>
          <span className={`text-[18px] font-bold ${pctColor(stats.total_pnl)}`}>
            {stats.total_pnl >= 0 ? '+' : ''}{fmt(stats.total_pnl)}원
          </span>
          <span className={`text-[12px] font-semibold ${pctColor(stats.total_return_pct)}`}>
            {fmtPct(stats.total_return_pct)}
          </span>
        </div>
      </div>

      {/* 포지션 상태 */}
      <div className="flex items-center gap-2 text-[13px] text-gray-500">
        <span className="font-semibold text-gray-700">{positions.length}</span>개 포지션 운용 중
        <span className="text-gray-300">|</span>
        최대 <span className="font-semibold text-gray-700">{stats.max_positions}</span>개
      </div>

      {/* 오픈 포지션 */}
      <div>
        <h2 className="text-[15px] font-bold text-gray-800 mb-3">
          오픈 포지션 <span className="text-[13px] text-gray-500 font-normal">({positions.length}종목)</span>
        </h2>
        {positions.length === 0 ? (
          <div className="text-center py-8 text-gray-400 text-[13px]">
            보유 종목이 없습니다 — 평일 15:30 스캔 후 익일 09:05에 매수됩니다
          </div>
        ) : (
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200">
                  <th className="text-left px-4 py-3 font-semibold text-gray-600">종목코드</th>
                  <th className="text-right px-4 py-3 font-semibold text-gray-600">매수가</th>
                  <th className="text-right px-4 py-3 font-semibold text-gray-600">수량</th>
                  <th className="text-right px-4 py-3 font-semibold text-gray-600">평가금액</th>
                  <th className="text-right px-4 py-3 font-semibold text-gray-600">매수일</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((p) => (
                  <tr key={p.id} className="border-b border-gray-100 hover:bg-gray-50 transition-colors">
                    <td className="px-4 py-3 font-semibold text-gray-800">{p.stock_code}</td>
                    <td className="px-4 py-3 text-right text-gray-700">{fmt(p.entry_price)}원</td>
                    <td className="px-4 py-3 text-right text-gray-700">{fmt(p.quantity)}주</td>
                    <td className="px-4 py-3 text-right font-semibold text-gray-800">{fmt(p.current_value)}원</td>
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
                <th className="text-left px-4 py-3 font-semibold text-gray-600">종목코드</th>
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
                  <td colSpan={7} className="text-center py-8 text-gray-400">거래 내역이 없습니다</td>
                </tr>
              ) : trades.map((t) => (
                <tr key={t.id} className="border-b border-gray-100 hover:bg-gray-50 transition-colors">
                  <td className="px-4 py-3 font-semibold text-gray-800">{t.stock_code}</td>
                  <td className="px-4 py-3 text-right">
                    <span className={`inline-block px-2 py-0.5 rounded text-[11px] font-semibold ${
                      t.is_open
                        ? 'bg-green-50 text-green-700 border border-green-200'
                        : 'bg-gray-50 text-gray-500 border border-gray-200'
                    }`}>
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
              ))}
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
  const [snapshots, setSnapshots] = useState<PaperSnapshot[]>([]);
  const [loading, setLoading] = useState(true);
  const [resetting, setResetting] = useState(false);

  useEffect(() => {
    Promise.all([
      fetchPaperTradingStats(),
      fetchPaperPositions(),
      fetchPaperTrades(50),
      fetchPaperSnapshots(30),
    ])
      .then(([s, p, t, sn]) => {
        setStats(s);
        setPositions(p);
        setTrades(t);
        setSnapshots(sn);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  async function handleReset() {
    if (!confirm('포트폴리오를 초기화하시겠습니까?\n모든 포지션과 거래 기록이 삭제됩니다.')) return;
    setResetting(true);
    try {
      const ok = await resetPaperTrading();
      if (ok) {
        setStats(null);
        setPositions([]);
        setTrades([]);
        setSnapshots([]);
        const s = await fetchPaperTradingStats();
        setStats(s);
      } else {
        alert('초기화에 실패했습니다.');
      }
    } catch {
      alert('초기화에 실패했습니다.');
    } finally {
      setResetting(false);
    }
  }

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

  const totalValue = stats.initial_capital + stats.total_pnl;
  const returnPct = stats.initial_capital > 0
    ? ((totalValue - stats.initial_capital) / stats.initial_capital) * 100
    : 0;

  return (
    <div className="flex flex-col gap-6">
      {/* 요약 카드 */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="bg-white rounded-xl border border-gray-200 p-4 text-center">
          <span className="text-[12px] text-gray-500 font-medium">총 자산</span>
          <div className="text-[18px] font-bold text-gray-900 mt-1">{fmt(totalValue)}원</div>
          <div className={`text-[12px] font-semibold mt-0.5 ${pctColor(returnPct)}`}>
            {returnPct >= 0 ? '+' : ''}{returnPct.toFixed(2)}% 누적 수익률
          </div>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4 text-center">
          <span className="text-[12px] text-gray-500 font-medium">승률</span>
          <div className={`text-[18px] font-bold mt-1 ${stats.win_rate >= 50 ? 'text-[#e12343]' : 'text-[#1261c4]'}`}>
            {stats.win_rate.toFixed(1)}%
          </div>
          <div className="text-[12px] text-gray-400 mt-0.5">청산 {stats.closed_trades}건 중</div>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4 text-center">
          <span className="text-[12px] text-gray-500 font-medium">수익 안정성</span>
          <div className={`text-[18px] font-bold mt-1 ${stats.sharpe_warning ? 'text-orange-400' : 'text-green-700'}`}>
            {stats.sharpe_ratio.toFixed(2)}
          </div>
          <div className="text-[11px] text-gray-400 mt-0.5">
            {stats.sharpe_warning ? '⚠ 변동성 대비 수익 낮음' : '변동성 대비 수익 효율'}
          </div>
        </div>
        <div className="bg-white rounded-xl border border-gray-200 p-4 text-center">
          <span className="text-[12px] text-gray-500 font-medium">최대 낙폭</span>
          <div className="text-[18px] font-bold text-[#1261c4] mt-1">{stats.mdd.toFixed(2)}%</div>
          <div className="text-[12px] text-gray-400 mt-0.5">고점 대비 최대 하락폭</div>
        </div>
      </div>

      {/* 오픈 포지션 */}
      <div>
        <h2 className="text-[15px] font-bold text-gray-800 mb-3">
          오픈 포지션 <span className="text-[13px] text-gray-500 font-normal">({positions.length}건)</span>
        </h2>
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
                  <th className="text-right px-4 py-3 font-semibold text-gray-600">목표가</th>
                  <th className="text-right px-4 py-3 font-semibold text-gray-600">손절가</th>
                  <th className="text-right px-4 py-3 font-semibold text-gray-600">진입일</th>
                </tr>
              </thead>
              <tbody>
                {[...positions].sort((a, b) => b.invest_amount - a.invest_amount).map((pos, i) => (
                  <tr key={i} className="border-b border-gray-100 hover:bg-gray-50 transition-colors">
                    <td className="px-4 py-3 font-semibold text-gray-800">{pos.stock_name}</td>
                    <td className="px-4 py-3 text-right text-gray-700">{fmt(pos.entry_price)}원</td>
                    <td className="px-4 py-3 text-right text-gray-700">{fmt(pos.quantity)}</td>
                    <td className="px-4 py-3 text-right text-gray-700">{fmt(pos.invest_amount)}원</td>
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
                  <tr key={i} className="border-b border-gray-100 hover:bg-gray-50 transition-colors">
                    <td className="px-4 py-3 font-semibold text-gray-800">{trade.stock_name}</td>
                    <td className="px-4 py-3 text-right text-gray-700">{fmt(trade.entry_price)}원</td>
                    <td className="px-4 py-3 text-right text-gray-700">{fmt(trade.exit_price)}원</td>
                    <td className={`px-4 py-3 text-right font-semibold ${pctColor(trade.pnl)}`}>
                      {trade.pnl >= 0 ? '+' : ''}{fmt(trade.pnl)}원
                    </td>
                    <td className={`px-4 py-3 text-right font-semibold ${pctColor(trade.return_pct)}`}>
                      {trade.return_pct >= 0 ? '+' : ''}{trade.return_pct.toFixed(2)}%
                    </td>
                    <td className="px-4 py-3 text-center">
                      <span className={`inline-block px-2 py-0.5 rounded text-[11px] font-medium ${
                        trade.exit_reason === 'target_hit'
                          ? 'bg-green-50 text-green-700 border border-green-200'
                          : trade.exit_reason === 'stop_loss'
                            ? 'bg-red-50 text-red-700 border border-red-200'
                            : 'bg-gray-50 text-gray-500 border border-gray-200'
                      }`}>
                        {exitReasonLabel[trade.exit_reason] || trade.exit_reason}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right text-gray-400">{trade.entry_date.slice(0, 10)}</td>
                    <td className="px-4 py-3 text-right text-gray-400">{trade.exit_date.slice(0, 10)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* 일별 수익률 추이 */}
      {snapshots.length > 0 && (
        <div>
          <h2 className="text-[15px] font-bold text-gray-800 mb-3">
            일별 누적수익률 <span className="text-[13px] text-gray-500 font-normal">최근 {snapshots.length}일</span>
          </h2>
          <div className="bg-white rounded-xl border border-gray-200 p-4">
            <div className="space-y-1.5">
              {snapshots.map((snap) => {
                const maxAbs = Math.max(...snapshots.map((s) => Math.abs(s.cumulative_return_pct)), 1);
                const width = Math.abs(snap.cumulative_return_pct) / maxAbs * 50;
                const isPositive = snap.cumulative_return_pct >= 0;
                return (
                  <div key={snap.date} className="flex items-center gap-2 text-[11px]">
                    <span className="w-[60px] text-gray-400 shrink-0">{snap.date.slice(5)}</span>
                    <div className="flex-1 flex items-center">
                      <div className="w-1/2 flex justify-end">
                        {!isPositive && (
                          <div className="h-3 bg-[#1261c4] rounded-l" style={{ width: `${width}%` }} />
                        )}
                      </div>
                      <div className="w-px h-4 bg-gray-200 shrink-0" />
                      <div className="w-1/2">
                        {isPositive && (
                          <div className="h-3 bg-[#e12343] rounded-r" style={{ width: `${width}%` }} />
                        )}
                      </div>
                    </div>
                    <span className={`w-[55px] text-right shrink-0 font-medium ${isPositive ? 'text-[#e12343]' : 'text-[#1261c4]'}`}>
                      {isPositive ? '+' : ''}{snap.cumulative_return_pct.toFixed(2)}%
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* 초기화 버튼 */}
      <div className="text-center">
        <button
          type="button"
          onClick={handleReset}
          disabled={resetting}
          className="px-4 py-2 text-[12px] text-gray-400 border border-gray-300 rounded-md hover:text-red-500 hover:border-red-300 disabled:opacity-50 transition-colors"
        >
          {resetting ? '초기화 중...' : '포트폴리오 초기화'}
        </button>
      </div>
    </div>
  );
}

// ─── 메인 페이지 ───
export default function TradingPage() {
  const [tab, setTab] = useState<Tab>('vip');

  const tabs: { key: Tab; label: string; desc: string }[] = [
    { key: 'vip', label: 'VIP 추종', desc: '브이아이피자산운용 대량보유 공시 추종' },
    { key: 'ks200', label: 'KS200 스윙', desc: 'Stochastics Slow + 이격도 기반 스윙 트레이딩' },
    { key: 'paper', label: 'AI 페이퍼', desc: 'AI 펀드매니저 시그널 기반 페이퍼 트레이딩' },
  ];

  return (
    <div className="max-w-[1200px] mx-auto px-4 py-6">
      {/* 헤더 */}
      <div className="mb-6">
        <h1 className="text-[22px] font-bold text-gray-900">모의투자 포트폴리오</h1>
        <p className="text-[13px] text-gray-500 mt-1">AI 모델별 페이퍼 트레이딩 현황</p>
      </div>

      {/* 탭 */}
      <div className="flex gap-1 mb-6 bg-gray-100 p-1 rounded-xl w-fit">
        {tabs.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setTab(t.key)}
            className={`px-5 py-2 rounded-lg text-[13px] font-semibold transition-all ${
              tab === t.key
                ? 'bg-white text-[#1261c4] shadow-sm'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* 탭 설명 */}
      <p className="text-[12px] text-gray-400 mb-5">
        {tabs.find((t) => t.key === tab)?.desc}
      </p>

      {/* 콘텐츠 */}
      {tab === 'vip' && <VIPTab />}
      {tab === 'ks200' && <KS200Tab />}
      {tab === 'paper' && <PaperTradingTab />}
    </div>
  );
}
