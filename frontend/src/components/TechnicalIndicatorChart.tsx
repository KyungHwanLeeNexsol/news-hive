'use client';

import { useEffect, useRef, useState } from 'react';
import type { PriceRecord } from '@/lib/types';

// @MX:NOTE: RSI, MACD 보조지표를 프론트엔드에서 직접 계산
// @MX:REASON: 백엔드 API 추가 호출 없이 가격 데이터로 산출 가능

type IndicatorTab = 'rsi' | 'macd';

interface TechnicalIndicatorChartProps {
  prices: PriceRecord[];
}

// EMA 계산
function calculateEMA(data: number[], period: number): number[] {
  const result: number[] = [];
  const multiplier = 2 / (period + 1);

  // 첫 번째 EMA는 SMA로 시작
  let sum = 0;
  for (let i = 0; i < Math.min(period, data.length); i++) {
    sum += data[i];
  }
  result.push(sum / Math.min(period, data.length));

  for (let i = 1; i < data.length; i++) {
    if (i < period) {
      // 아직 period만큼 데이터가 없으면 SMA
      let s = 0;
      for (let j = 0; j <= i; j++) s += data[j];
      result.push(s / (i + 1));
    } else {
      result.push((data[i] - result[result.length - 1]) * multiplier + result[result.length - 1]);
    }
  }
  return result;
}

// RSI(14) 계산
function calculateRSI(prices: { close: number }[], period = 14): (number | null)[] {
  if (prices.length < period + 1) return prices.map(() => null);

  const changes: number[] = [];
  for (let i = 1; i < prices.length; i++) {
    changes.push(prices[i].close - prices[i - 1].close);
  }

  const result: (number | null)[] = [null]; // 첫 번째는 변화량 없음

  let avgGain = 0;
  let avgLoss = 0;

  // 초기 평균 계산
  for (let i = 0; i < period; i++) {
    if (changes[i] >= 0) avgGain += changes[i];
    else avgLoss += Math.abs(changes[i]);
    result.push(null);
  }
  avgGain /= period;
  avgLoss /= period;

  // 첫 번째 RSI
  const firstRS = avgLoss === 0 ? 100 : avgGain / avgLoss;
  result.push(100 - 100 / (1 + firstRS));

  // 이후 스무딩 RSI
  for (let i = period; i < changes.length; i++) {
    const gain = changes[i] >= 0 ? changes[i] : 0;
    const loss = changes[i] < 0 ? Math.abs(changes[i]) : 0;
    avgGain = (avgGain * (period - 1) + gain) / period;
    avgLoss = (avgLoss * (period - 1) + loss) / period;
    const rs = avgLoss === 0 ? 100 : avgGain / avgLoss;
    result.push(100 - 100 / (1 + rs));
  }

  return result;
}

// MACD 계산: EMA(12) - EMA(26), Signal = EMA(9) of MACD
function calculateMACD(prices: { close: number }[]): {
  macd: (number | null)[];
  signal: (number | null)[];
  histogram: (number | null)[];
} {
  const closes = prices.map((p) => p.close);
  if (closes.length < 26) {
    const empty = prices.map(() => null);
    return { macd: empty, signal: empty, histogram: empty };
  }

  const ema12 = calculateEMA(closes, 12);
  const ema26 = calculateEMA(closes, 26);

  const macdLine: (number | null)[] = [];
  for (let i = 0; i < closes.length; i++) {
    if (i < 25) {
      macdLine.push(null);
    } else {
      macdLine.push(ema12[i] - ema26[i]);
    }
  }

  // Signal line: EMA(9) of MACD values (null이 아닌 값만)
  const validMacd = macdLine.filter((v): v is number => v !== null);
  const signalEma = calculateEMA(validMacd, 9);

  const signal: (number | null)[] = [];
  const histogram: (number | null)[] = [];
  let validIdx = 0;

  for (let i = 0; i < closes.length; i++) {
    if (macdLine[i] == null) {
      signal.push(null);
      histogram.push(null);
    } else {
      if (validIdx < 8) {
        // Signal line은 9개 이상의 MACD 값이 있어야 유효
        signal.push(null);
        histogram.push(null);
      } else {
        const sigVal = signalEma[validIdx];
        signal.push(sigVal);
        histogram.push((macdLine[i] as number) - sigVal);
      }
      validIdx++;
    }
  }

  return { macd: macdLine, signal, histogram };
}

// 날짜 → lightweight-charts 시간 형식
function toChartTime(dateStr: string): string {
  return dateStr.replace(/\./g, '-');
}

export default function TechnicalIndicatorChart({
  prices,
}: TechnicalIndicatorChartProps): React.ReactElement | null {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartInstanceRef = useRef<ReturnType<typeof import('lightweight-charts').createChart> | null>(null);
  const [activeTab, setActiveTab] = useState<IndicatorTab>('rsi');

  useEffect(() => {
    if (!chartContainerRef.current || prices.length < 15) return;

    let cancelled = false;

    (async () => {
      const { createChart, LineSeries, HistogramSeries } = await import('lightweight-charts');

      if (cancelled || !chartContainerRef.current) return;

      // 기존 차트 정리
      if (chartInstanceRef.current) {
        chartInstanceRef.current.remove();
        chartInstanceRef.current = null;
      }

      const container = chartContainerRef.current;
      const chart = createChart(container, {
        width: container.clientWidth,
        height: 180,
        layout: {
          background: { color: '#ffffff' },
          textColor: '#333',
          fontSize: 10,
        },
        grid: {
          vertLines: { color: '#f5f5f5' },
          horzLines: { color: '#f0f0f0' },
        },
        rightPriceScale: {
          borderColor: '#e5e5e5',
        },
        timeScale: {
          borderColor: '#e5e5e5',
          timeVisible: false,
        },
        crosshair: { mode: 0 },
        localization: { locale: 'ko-KR' },
      });

      chartInstanceRef.current = chart;

      // 데이터를 시간순으로 정렬 (오래된 → 최신)
      const sorted = [...prices].reverse();

      if (activeTab === 'rsi') {
        // RSI 라인
        const rsiValues = calculateRSI(sorted);
        const rsiSeries = chart.addSeries(LineSeries, {
          color: '#8b5cf6',
          lineWidth: 2,
          priceLineVisible: false,
          lastValueVisible: true,
        });

        const rsiData = sorted
          .map((p, i) => {
            if (rsiValues[i] == null) return null;
            return { time: toChartTime(p.date), value: rsiValues[i] as number };
          })
          .filter(Boolean);

        rsiSeries.setData(rsiData as Parameters<typeof rsiSeries.setData>[0]);

        // 과매수(70) / 과매도(30) 기준선
        const overboughtSeries = chart.addSeries(LineSeries, {
          color: 'rgba(239, 68, 68, 0.4)',
          lineWidth: 1,
          lineStyle: 2,
          crosshairMarkerVisible: false,
          priceLineVisible: false,
          lastValueVisible: false,
        });

        const oversoldSeries = chart.addSeries(LineSeries, {
          color: 'rgba(34, 197, 94, 0.4)',
          lineWidth: 1,
          lineStyle: 2,
          crosshairMarkerVisible: false,
          priceLineVisible: false,
          lastValueVisible: false,
        });

        const timePoints = sorted.map((p) => toChartTime(p.date));
        overboughtSeries.setData(
          timePoints.map((t) => ({ time: t, value: 70 })) as Parameters<typeof overboughtSeries.setData>[0],
        );
        oversoldSeries.setData(
          timePoints.map((t) => ({ time: t, value: 30 })) as Parameters<typeof oversoldSeries.setData>[0],
        );

        // 스케일 고정 (0-100)
        chart.priceScale('right').applyOptions({
          autoScale: false,
          scaleMargins: { top: 0.05, bottom: 0.05 },
        });
      } else {
        // MACD
        const { macd, signal, histogram } = calculateMACD(sorted);

        // MACD 히스토그램
        const histSeries = chart.addSeries(HistogramSeries, {
          priceLineVisible: false,
          lastValueVisible: false,
        });

        const histData = sorted
          .map((p, i) => {
            if (histogram[i] == null) return null;
            return {
              time: toChartTime(p.date),
              value: histogram[i] as number,
              color: (histogram[i] as number) >= 0 ? 'rgba(225,35,67,0.5)' : 'rgba(18,97,196,0.5)',
            };
          })
          .filter(Boolean);

        histSeries.setData(histData as Parameters<typeof histSeries.setData>[0]);

        // MACD 라인
        const macdSeries = chart.addSeries(LineSeries, {
          color: '#3b82f6',
          lineWidth: 2,
          priceLineVisible: false,
          lastValueVisible: false,
        });

        const macdData = sorted
          .map((p, i) => {
            if (macd[i] == null) return null;
            return { time: toChartTime(p.date), value: macd[i] as number };
          })
          .filter(Boolean);

        macdSeries.setData(macdData as Parameters<typeof macdSeries.setData>[0]);

        // Signal 라인
        const signalSeries = chart.addSeries(LineSeries, {
          color: '#ef4444',
          lineWidth: 2,
          lineStyle: 2,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        });

        const signalData = sorted
          .map((p, i) => {
            if (signal[i] == null) return null;
            return { time: toChartTime(p.date), value: signal[i] as number };
          })
          .filter(Boolean);

        signalSeries.setData(signalData as Parameters<typeof signalSeries.setData>[0]);
      }

      chart.timeScale().fitContent();

      // 리사이즈 대응
      const resizeObserver = new ResizeObserver((entries) => {
        for (const entry of entries) {
          chart.applyOptions({ width: entry.contentRect.width });
        }
      });
      resizeObserver.observe(container);

      (container as unknown as Record<string, () => void>).__cleanup = () => {
        resizeObserver.disconnect();
      };
    })();

    return () => {
      cancelled = true;
      const container = chartContainerRef.current;
      if (container && (container as unknown as Record<string, () => void>).__cleanup) {
        (container as unknown as Record<string, () => void>).__cleanup();
      }
      if (chartInstanceRef.current) {
        chartInstanceRef.current.remove();
        chartInstanceRef.current = null;
      }
    };
  }, [prices, activeTab]);

  if (prices.length < 15) return null;

  return (
    <div className="px-4 py-3 border-t border-[#e5e5e5]">
      {/* 탭 전환 */}
      <div className="flex items-center gap-1 mb-3">
        <span className="text-[12px] font-bold text-[#333] mr-2">보조지표</span>
        <button
          onClick={() => setActiveTab('rsi')}
          className={`px-2.5 py-1 text-[11px] rounded transition-colors ${
            activeTab === 'rsi'
              ? 'bg-[#8b5cf6] text-white'
              : 'bg-[#f5f5f5] text-[#666] hover:bg-[#e5e5e5]'
          }`}
        >
          RSI
        </button>
        <button
          onClick={() => setActiveTab('macd')}
          className={`px-2.5 py-1 text-[11px] rounded transition-colors ${
            activeTab === 'macd'
              ? 'bg-[#3b82f6] text-white'
              : 'bg-[#f5f5f5] text-[#666] hover:bg-[#e5e5e5]'
          }`}
        >
          MACD
        </button>
      </div>

      {/* 차트 */}
      <div ref={chartContainerRef} className="w-full" />

      {/* 범례 */}
      <div className="flex items-center gap-4 mt-1 text-[10px] text-[#999]">
        {activeTab === 'rsi' ? (
          <>
            <span className="flex items-center gap-1">
              <span className="inline-block w-3 h-0.5 bg-[#8b5cf6]" /> RSI(14)
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block w-3 h-0.5 bg-[#ef4444] opacity-40" style={{ borderTop: '1px dashed' }} /> 과매수 70
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block w-3 h-0.5 bg-[#22c55e] opacity-40" style={{ borderTop: '1px dashed' }} /> 과매도 30
            </span>
          </>
        ) : (
          <>
            <span className="flex items-center gap-1">
              <span className="inline-block w-3 h-0.5 bg-[#3b82f6]" /> MACD
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block w-3 h-0.5 bg-[#ef4444]" style={{ borderTop: '1px dashed' }} /> Signal
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block w-3 h-3 bg-[#e12343] opacity-50" /> 히스토그램
            </span>
          </>
        )}
      </div>
    </div>
  );
}
