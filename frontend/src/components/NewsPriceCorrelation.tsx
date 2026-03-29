'use client';

import { useState, useEffect } from 'react';
import { fetchNewsPriceCorrelation } from '@/lib/api';
import type { NewsPriceCorrelation as CorrelationData } from '@/lib/types';
import {
  ComposedChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts';

interface Props {
  stockId: number;
}

// 상관계수에 따른 색상과 라벨
function correlationBadge(value: number): { label: string; color: string; bg: string } {
  const abs = Math.abs(value);
  if (abs >= 0.7) {
    return value > 0
      ? { label: '강한 양의 상관', color: '#e12343', bg: '#ffebee' }
      : { label: '강한 음의 상관', color: '#1261c4', bg: '#e3f2fd' };
  }
  if (abs >= 0.4) {
    return value > 0
      ? { label: '중간 양의 상관', color: '#ff8f00', bg: '#fff8e1' }
      : { label: '중간 음의 상관', color: '#5c6bc0', bg: '#e8eaf6' };
  }
  return { label: '약한 상관', color: '#999', bg: '#f5f5f5' };
}

export default function NewsPriceCorrelation({ stockId }: Props): JSX.Element {
  const [data, setData] = useState<CorrelationData | null>(null);
  const [loading, setLoading] = useState(false);
  const [days, setDays] = useState(90);

  useEffect(() => {
    let cancelled = false;
    const load = async (): Promise<void> => {
      setLoading(true);
      try {
        const result = await fetchNewsPriceCorrelation(stockId, days);
        if (!cancelled) setData(result);
      } catch {
        if (!cancelled) setData(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
  }, [stockId, days]);

  if (loading) {
    return (
      <div className="px-4 py-6 text-center">
        <div className="text-[13px] text-[#999]">뉴스-주가 상관관계 로딩 중...</div>
      </div>
    );
  }

  if (!data || data.timeline.length === 0) {
    return (
      <div className="px-4 py-6 text-center">
        <div className="text-[13px] text-[#999]">뉴스-주가 상관관계 데이터가 부족합니다.</div>
      </div>
    );
  }

  const badge = correlationBadge(data.correlation_7d);

  return (
    <div className="px-4 py-4">
      {/* 헤더 */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <h3 className="text-[13px] font-bold text-[#333]">뉴스 감성 vs 주가 변동</h3>
          <span
            className="text-[12px] font-semibold px-2.5 py-1 rounded-full"
            style={{ color: badge.color, backgroundColor: badge.bg }}
          >
            7일 상관계수: {data.correlation_7d.toFixed(3)} ({badge.label})
          </span>
        </div>
        {/* 기간 선택 */}
        <div className="flex rounded-lg overflow-hidden border border-[#e5e5e5]">
          {[30, 60, 90].map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={`px-2.5 py-1 text-[11px] font-medium transition-colors ${
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

      {/* 듀얼 축 차트 */}
      <ResponsiveContainer width="100%" height={260}>
        <ComposedChart data={data.timeline}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis
            dataKey="date"
            tickFormatter={(v: string) => v.slice(5)}
            tick={{ fontSize: 11, fill: '#999' }}
          />
          {/* 왼쪽 Y축: 감성 점수 */}
          <YAxis
            yAxisId="left"
            domain={[-1, 1]}
            tickFormatter={(v: number) => v.toFixed(1)}
            tick={{ fontSize: 11, fill: '#ff8f00' }}
            width={40}
            label={{
              value: '감성',
              angle: -90,
              position: 'insideLeft',
              style: { fontSize: 11, fill: '#ff8f00' },
            }}
          />
          {/* 오른쪽 Y축: 주가 변동률 */}
          <YAxis
            yAxisId="right"
            orientation="right"
            tickFormatter={(v: number) => `${v.toFixed(1)}%`}
            tick={{ fontSize: 11, fill: '#1261c4' }}
            width={50}
            label={{
              value: '주가',
              angle: 90,
              position: 'insideRight',
              style: { fontSize: 11, fill: '#1261c4' },
            }}
          />
          <Tooltip
            formatter={(value: number | string, name: string) => {
              const v = Number(value);
              if (name === 'sentiment_score') return [v.toFixed(3), '감성 점수'];
              if (name === 'price_change_pct') return [`${v.toFixed(2)}%`, '주가 변동률'];
              return [value, name];
            }}
            labelFormatter={(label: string) => label}
            contentStyle={{ fontSize: 12, borderRadius: 8 }}
          />
          <Legend
            formatter={(value: string) => {
              if (value === 'sentiment_score') return '감성 점수';
              if (value === 'price_change_pct') return '주가 변동률';
              return value;
            }}
            wrapperStyle={{ fontSize: 12 }}
          />
          <Line
            yAxisId="left"
            type="monotone"
            dataKey="sentiment_score"
            stroke="#ff8f00"
            strokeWidth={2}
            dot={false}
            name="sentiment_score"
          />
          <Line
            yAxisId="right"
            type="monotone"
            dataKey="price_change_pct"
            stroke="#1261c4"
            strokeWidth={2}
            dot={false}
            name="price_change_pct"
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
