'use client';

import { useState, useEffect, useCallback } from 'react';
import { fetchBacktest } from '@/lib/api';
import type { BacktestResult, BacktestByStock } from '@/lib/types';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';

// 정렬 기준 타입
type SortKey = 'stock_name' | 'signals' | 'win_rate' | 'avg_return';
type SortDir = 'asc' | 'desc';

export default function BacktestDashboard(): JSX.Element {
  // 필터 상태
  const [days, setDays] = useState(90);
  const [signalType, setSignalType] = useState('all');
  const [minConfidence, setMinConfidence] = useState(0.5);

  // 데이터 상태
  const [data, setData] = useState<BacktestResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 테이블 정렬
  const [sortKey, setSortKey] = useState<SortKey>('avg_return');
  const [sortDir, setSortDir] = useState<SortDir>('desc');

  // 데이터 로드
  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await fetchBacktest({
        days,
        signal_type: signalType === 'all' ? undefined : signalType,
        min_confidence: minConfidence,
      });
      setData(result);
    } catch {
      setError('백테스트 데이터를 불러오는데 실패했습니다.');
    } finally {
      setLoading(false);
    }
  }, [days, signalType, minConfidence]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // 종목별 정렬
  const sortedStocks = data?.by_stock
    ? [...data.by_stock].sort((a: BacktestByStock, b: BacktestByStock) => {
        const va = a[sortKey];
        const vb = b[sortKey];
        if (typeof va === 'string' && typeof vb === 'string') {
          return sortDir === 'asc' ? va.localeCompare(vb) : vb.localeCompare(va);
        }
        return sortDir === 'asc'
          ? (va as number) - (vb as number)
          : (vb as number) - (va as number);
      })
    : [];

  // 정렬 토글
  const handleSort = (key: SortKey): void => {
    if (sortKey === key) {
      setSortDir(sortDir === 'asc' ? 'desc' : 'asc');
    } else {
      setSortKey(key);
      setSortDir('desc');
    }
  };

  // 정렬 아이콘
  const sortIcon = (key: SortKey): string => {
    if (sortKey !== key) return '';
    return sortDir === 'asc' ? ' \u25B2' : ' \u25BC';
  };

  const summary = data?.summary;

  return (
    <div className="space-y-4">
      {/* 필터 바 */}
      <div className="section-box px-4 py-3">
        <div className="flex flex-wrap items-center gap-4">
          {/* 기간 선택 */}
          <div className="flex items-center gap-2">
            <span className="text-[12px] text-[#666] font-medium">기간</span>
            <div className="flex rounded-lg overflow-hidden border border-[#e5e5e5]">
              {[30, 60, 90, 180].map((d) => (
                <button
                  key={d}
                  onClick={() => setDays(d)}
                  className={`px-3 py-1.5 text-[12px] font-medium transition-colors ${
                    days === d
                      ? 'bg-[#1261c4] text-white'
                      : 'bg-white text-[#666] hover:bg-[#f7f8fa]'
                  }`}
                >
                  {d}일
                </button>
              ))}
            </div>
          </div>

          {/* 시그널 타입 */}
          <div className="flex items-center gap-2">
            <span className="text-[12px] text-[#666] font-medium">시그널</span>
            <select
              value={signalType}
              onChange={(e) => setSignalType(e.target.value)}
              className="px-2 py-1.5 border border-[#e5e5e5] rounded-lg text-[12px] text-[#333] bg-white"
            >
              <option value="all">전체</option>
              <option value="buy">매수</option>
              <option value="sell">매도</option>
            </select>
          </div>

          {/* 최소 신뢰도 */}
          <div className="flex items-center gap-2">
            <span className="text-[12px] text-[#666] font-medium">
              최소 신뢰도: {Math.round(minConfidence * 100)}%
            </span>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={minConfidence}
              onChange={(e) => setMinConfidence(parseFloat(e.target.value))}
              className="w-24 accent-[#1261c4]"
            />
          </div>
        </div>
      </div>

      {/* 에러 메시지 */}
      {error && (
        <div className="section-box px-4 py-3 text-[13px] text-[#e12343]">{error}</div>
      )}

      {/* 로딩 */}
      {loading && (
        <div className="section-box px-4 py-8 text-center">
          <div className="text-[13px] text-[#999]">백테스트 데이터 로딩 중...</div>
        </div>
      )}

      {/* 요약 카드 */}
      {!loading && summary && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          {[
            { label: '총 시그널', value: `${summary.total_signals}건`, color: '#333' },
            {
              label: '승률',
              value: `${summary.win_rate.toFixed(1)}%`,
              color: summary.win_rate >= 50 ? '#e12343' : '#1261c4',
            },
            {
              label: '평균 수익률',
              value: `${summary.avg_return >= 0 ? '+' : ''}${summary.avg_return.toFixed(2)}%`,
              color: summary.avg_return >= 0 ? '#e12343' : '#1261c4',
            },
            {
              label: '최대 낙폭',
              value: `${summary.max_drawdown.toFixed(2)}%`,
              color: '#1261c4',
            },
            {
              label: 'Sharpe Ratio',
              value: summary.sharpe_ratio.toFixed(2),
              color: summary.sharpe_ratio >= 1 ? '#e12343' : '#666',
            },
            {
              label: 'KOSPI 수익률',
              value: `${summary.kospi_return >= 0 ? '+' : ''}${summary.kospi_return.toFixed(2)}%`,
              color: summary.kospi_return >= 0 ? '#e12343' : '#1261c4',
            },
          ].map((card) => (
            <div key={card.label} className="section-box px-3 py-3 text-center">
              <div className="text-[11px] text-[#999] font-medium">{card.label}</div>
              <div className="text-[17px] font-bold mt-1" style={{ color: card.color }}>
                {card.value}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 누적 수익률 차트 */}
      {!loading && data?.timeline && data.timeline.length > 0 && (
        <div className="section-box px-4 py-4">
          <h3 className="text-[13px] font-bold text-[#333] mb-3">누적 수익률 추이</h3>
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={data.timeline}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis
                dataKey="date"
                tickFormatter={(v: string) => v.slice(5)}
                tick={{ fontSize: 11, fill: '#999' }}
              />
              <YAxis
                tickFormatter={(v: number) => `${v.toFixed(1)}%`}
                tick={{ fontSize: 11, fill: '#999' }}
                width={55}
              />
              <Tooltip
                formatter={(value: number | string) => [`${Number(value).toFixed(2)}%`, '누적 수익률']}
                labelFormatter={(label: string) => label}
                contentStyle={{ fontSize: 12, borderRadius: 8 }}
              />
              <Line
                type="monotone"
                dataKey="cumulative_return"
                stroke="#1261c4"
                strokeWidth={2}
                dot={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* 종목별 성과 테이블 */}
      {!loading && sortedStocks.length > 0 && (
        <div className="section-box">
          <h3 className="text-[13px] font-bold text-[#333] px-4 pt-3 pb-2">종목별 성과</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="border-t border-b border-[#e5e5e5] bg-[#f8f9fa]">
                  <th
                    className="px-4 py-2 text-left text-[12px] text-[#666] font-semibold cursor-pointer hover:text-[#333]"
                    onClick={() => handleSort('stock_name')}
                  >
                    종목명{sortIcon('stock_name')}
                  </th>
                  <th
                    className="px-4 py-2 text-right text-[12px] text-[#666] font-semibold cursor-pointer hover:text-[#333]"
                    onClick={() => handleSort('signals')}
                  >
                    시그널 수{sortIcon('signals')}
                  </th>
                  <th
                    className="px-4 py-2 text-right text-[12px] text-[#666] font-semibold cursor-pointer hover:text-[#333]"
                    onClick={() => handleSort('win_rate')}
                  >
                    승률{sortIcon('win_rate')}
                  </th>
                  <th
                    className="px-4 py-2 text-right text-[12px] text-[#666] font-semibold cursor-pointer hover:text-[#333]"
                    onClick={() => handleSort('avg_return')}
                  >
                    평균 수익률{sortIcon('avg_return')}
                  </th>
                </tr>
              </thead>
              <tbody>
                {sortedStocks.map((s) => (
                  <tr key={s.stock_name} className="border-b border-[#f0f0f0] hover:bg-[#f8f9fa]">
                    <td className="px-4 py-2 font-medium text-[#333]">{s.stock_name}</td>
                    <td className="px-4 py-2 text-right text-[#666]">{s.signals}건</td>
                    <td className="px-4 py-2 text-right">
                      <span className={s.win_rate >= 50 ? 'text-[#e12343]' : 'text-[#1261c4]'}>
                        {s.win_rate.toFixed(1)}%
                      </span>
                    </td>
                    <td className="px-4 py-2 text-right">
                      <span className={s.avg_return >= 0 ? 'text-[#e12343]' : 'text-[#1261c4]'}>
                        {s.avg_return >= 0 ? '+' : ''}{s.avg_return.toFixed(2)}%
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 데이터 없음 */}
      {!loading && !error && data && data.timeline.length === 0 && (
        <div className="section-box px-4 py-8 text-center">
          <p className="text-[13px] text-[#999]">해당 조건에 맞는 백테스트 데이터가 없습니다.</p>
        </div>
      )}
    </div>
  );
}
