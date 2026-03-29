'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import type { PriceRecord } from '@/lib/types';

// @MX:NOTE: lightweight-charts는 클라이언트 전용 라이브러리 — dynamic import 사용
// @MX:REASON: SSR 환경에서 window/document 참조 오류 방지

type TimeRange = '1W' | '1M' | '3M' | '6M' | '1Y';

interface CandlestickChartProps {
  prices: PriceRecord[];
  onTimeRangeChange: (months: number) => void;
  loading?: boolean;
}

// SMA 계산 (단순이동평균)
function calculateSMA(data: { close: number }[], period: number): (number | null)[] {
  const result: (number | null)[] = [];
  for (let i = 0; i < data.length; i++) {
    if (i < period - 1) {
      result.push(null);
    } else {
      let sum = 0;
      for (let j = i - period + 1; j <= i; j++) {
        sum += data[j].close;
      }
      result.push(sum / period);
    }
  }
  return result;
}

// 볼린저 밴드 계산
function calculateBollingerBands(
  data: { close: number }[],
  period = 20,
  multiplier = 2,
): { upper: (number | null)[]; middle: (number | null)[]; lower: (number | null)[] } {
  const middle = calculateSMA(data, period);
  const upper: (number | null)[] = [];
  const lower: (number | null)[] = [];

  for (let i = 0; i < data.length; i++) {
    if (middle[i] == null) {
      upper.push(null);
      lower.push(null);
    } else {
      let sumSq = 0;
      for (let j = i - period + 1; j <= i; j++) {
        sumSq += (data[j].close - (middle[i] as number)) ** 2;
      }
      const std = Math.sqrt(sumSq / period);
      upper.push((middle[i] as number) + multiplier * std);
      lower.push((middle[i] as number) - multiplier * std);
    }
  }

  return { upper, middle, lower };
}

// 날짜 문자열을 lightweight-charts 형식으로 변환
function toChartTime(dateStr: string): string {
  // "2025-03-28" 또는 "2025.03.28" 형식 처리
  return dateStr.replace(/\./g, '-');
}

const TIME_RANGES: { key: TimeRange; label: string; months: number }[] = [
  { key: '1W', label: '1주', months: 1 },
  { key: '1M', label: '1개월', months: 1 },
  { key: '3M', label: '3개월', months: 3 },
  { key: '6M', label: '6개월', months: 6 },
  { key: '1Y', label: '1년', months: 12 },
];

export default function CandlestickChart({
  prices,
  onTimeRangeChange,
  loading = false,
}: CandlestickChartProps): React.ReactElement {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ReturnType<typeof import('lightweight-charts').createChart> | null>(null);

  const [timeRange, setTimeRange] = useState<TimeRange>('3M');
  const [showSMA5, setShowSMA5] = useState(true);
  const [showSMA20, setShowSMA20] = useState(true);
  const [showSMA60, setShowSMA60] = useState(false);
  const [showBollinger, setShowBollinger] = useState(false);

  const handleTimeRangeChange = useCallback(
    (range: TimeRange) => {
      setTimeRange(range);
      const found = TIME_RANGES.find((r) => r.key === range);
      if (found) onTimeRangeChange(found.months);
    },
    [onTimeRangeChange],
  );

  useEffect(() => {
    if (!chartContainerRef.current || prices.length < 2) return;

    // dynamic import: lightweight-charts는 브라우저 전용
    let cancelled = false;

    (async () => {
      const { createChart, CandlestickSeries, HistogramSeries, LineSeries } = await import(
        'lightweight-charts'
      );

      if (cancelled || !chartContainerRef.current) return;

      // 기존 차트 정리
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }

      const container = chartContainerRef.current;
      const chart = createChart(container, {
        width: container.clientWidth,
        height: 400,
        layout: {
          background: { color: '#ffffff' },
          textColor: '#333',
          fontSize: 11,
        },
        grid: {
          vertLines: { color: '#f0f0f0' },
          horzLines: { color: '#f0f0f0' },
        },
        crosshair: {
          mode: 0, // Normal
        },
        rightPriceScale: {
          borderColor: '#e5e5e5',
        },
        timeScale: {
          borderColor: '#e5e5e5',
          timeVisible: false,
        },
        localization: {
          locale: 'ko-KR',
        },
      });

      chartRef.current = chart;

      // 데이터를 시간순으로 정렬 (오래된 → 최신)
      const sorted = [...prices].reverse();

      // 캔들스틱 시리즈
      const candleSeries = chart.addSeries(CandlestickSeries, {
        upColor: '#e12343',
        downColor: '#1261c4',
        borderUpColor: '#e12343',
        borderDownColor: '#1261c4',
        wickUpColor: '#e12343',
        wickDownColor: '#1261c4',
      });

      const candleData = sorted.map((p) => ({
        time: toChartTime(p.date),
        open: p.open,
        high: p.high,
        low: p.low,
        close: p.close,
      }));

      candleSeries.setData(candleData as Parameters<typeof candleSeries.setData>[0]);

      // 거래량 히스토그램
      const volumeSeries = chart.addSeries(HistogramSeries, {
        priceFormat: { type: 'volume' },
        priceScaleId: 'volume',
      });

      chart.priceScale('volume').applyOptions({
        scaleMargins: { top: 0.85, bottom: 0 },
      });

      const volumeData = sorted.map((p) => ({
        time: toChartTime(p.date),
        value: p.volume,
        color: p.close >= p.open ? 'rgba(225,35,67,0.3)' : 'rgba(18,97,196,0.3)',
      }));

      volumeSeries.setData(volumeData as Parameters<typeof volumeSeries.setData>[0]);

      // SMA 오버레이
      const smaConfigs = [
        { enabled: showSMA5, period: 5, color: '#eab308', label: 'SMA5' },
        { enabled: showSMA20, period: 20, color: '#3b82f6', label: 'SMA20' },
        { enabled: showSMA60, period: 60, color: '#ef4444', label: 'SMA60' },
      ];

      for (const sma of smaConfigs) {
        if (!sma.enabled) continue;
        const values = calculateSMA(sorted, sma.period);
        const lineData = sorted
          .map((p, i) => {
            if (values[i] == null) return null;
            return { time: toChartTime(p.date), value: values[i] as number };
          })
          .filter(Boolean);

        if (lineData.length > 0) {
          const lineSeries = chart.addSeries(LineSeries, {
            color: sma.color,
            lineWidth: 1,
            crosshairMarkerVisible: false,
            priceLineVisible: false,
            lastValueVisible: false,
          });
          lineSeries.setData(lineData as Parameters<typeof lineSeries.setData>[0]);
        }
      }

      // 볼린저 밴드
      if (showBollinger) {
        const bb = calculateBollingerBands(sorted);
        const bbColors = [
          { data: bb.upper, color: 'rgba(156,163,175,0.5)' },
          { data: bb.lower, color: 'rgba(156,163,175,0.5)' },
        ];

        for (const band of bbColors) {
          const lineData = sorted
            .map((p, i) => {
              if (band.data[i] == null) return null;
              return { time: toChartTime(p.date), value: band.data[i] as number };
            })
            .filter(Boolean);

          if (lineData.length > 0) {
            const lineSeries = chart.addSeries(LineSeries, {
              color: band.color,
              lineWidth: 1,
              lineStyle: 2, // dashed
              crosshairMarkerVisible: false,
              priceLineVisible: false,
              lastValueVisible: false,
            });
            lineSeries.setData(lineData as Parameters<typeof lineSeries.setData>[0]);
          }
        }
      }

      // 차트 크기를 컨텐츠에 맞춤
      chart.timeScale().fitContent();

      // 리사이즈 대응
      const resizeObserver = new ResizeObserver((entries) => {
        for (const entry of entries) {
          const { width } = entry.contentRect;
          chart.applyOptions({ width });
        }
      });
      resizeObserver.observe(container);

      // 정리 함수에서 observer 해제
      const cleanup = () => {
        resizeObserver.disconnect();
      };

      // cleanup 저장 (useEffect return에서 사용)
      (container as unknown as Record<string, () => void>).__cleanup = cleanup;
    })();

    return () => {
      cancelled = true;
      const container = chartContainerRef.current;
      if (container && (container as unknown as Record<string, () => void>).__cleanup) {
        (container as unknown as Record<string, () => void>).__cleanup();
      }
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, [prices, showSMA5, showSMA20, showSMA60, showBollinger]);

  return (
    <div className="px-4 py-3">
      {/* 컨트롤 영역 */}
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <div className="flex items-center gap-2">
          <span className="text-[12px] font-bold text-[#333]">주가 차트</span>
          {/* 기간 버튼 */}
          <div className="flex gap-0.5 ml-2">
            {TIME_RANGES.map((r) => (
              <button
                key={r.key}
                onClick={() => handleTimeRangeChange(r.key)}
                className={`px-2.5 py-1 text-[11px] rounded transition-colors ${
                  timeRange === r.key
                    ? 'bg-[#1261c4] text-white'
                    : 'bg-[#f5f5f5] text-[#666] hover:bg-[#e5e5e5]'
                }`}
              >
                {r.label}
              </button>
            ))}
          </div>
        </div>
        {/* 오버레이 토글 */}
        <div className="flex items-center gap-3 text-[11px]">
          <label className="flex items-center gap-1 cursor-pointer">
            <input
              type="checkbox"
              checked={showSMA5}
              onChange={() => setShowSMA5(!showSMA5)}
              className="w-3 h-3"
            />
            <span className="text-[#eab308] font-medium">5일</span>
          </label>
          <label className="flex items-center gap-1 cursor-pointer">
            <input
              type="checkbox"
              checked={showSMA20}
              onChange={() => setShowSMA20(!showSMA20)}
              className="w-3 h-3"
            />
            <span className="text-[#3b82f6] font-medium">20일</span>
          </label>
          <label className="flex items-center gap-1 cursor-pointer">
            <input
              type="checkbox"
              checked={showSMA60}
              onChange={() => setShowSMA60(!showSMA60)}
              className="w-3 h-3"
            />
            <span className="text-[#ef4444] font-medium">60일</span>
          </label>
          <label className="flex items-center gap-1 cursor-pointer">
            <input
              type="checkbox"
              checked={showBollinger}
              onChange={() => setShowBollinger(!showBollinger)}
              className="w-3 h-3"
            />
            <span className="text-[#9ca3af] font-medium">BB</span>
          </label>
        </div>
      </div>

      {/* 차트 컨테이너 */}
      {loading ? (
        <div className="skeleton" style={{ width: '100%', height: 400 }} />
      ) : prices.length < 2 ? (
        <p className="text-[13px] text-[#999] py-8 text-center">차트 데이터가 부족합니다.</p>
      ) : (
        <div ref={chartContainerRef} className="w-full" />
      )}

      {/* 범례 */}
      <div className="flex items-center gap-3 mt-2 text-[11px] text-[#999]">
        <span className="flex items-center gap-1">
          <span className="inline-block w-3 h-3 bg-[#e12343]" /> 상승
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-3 h-3 bg-[#1261c4]" /> 하락
        </span>
      </div>
    </div>
  );
}
