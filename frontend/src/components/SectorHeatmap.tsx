'use client';

import { useRouter } from 'next/navigation';
import type { Sector } from '@/lib/types';
import { formatSectorName } from '@/lib/format';

// @MX:NOTE: 섹터 변동률 기반 색상 매핑 (녹색: 상승, 적색: 하락, 회색: 없음)
function getHeatmapColor(changeRate: number | null | undefined): string {
  if (changeRate == null) return '#9ca3af';
  if (changeRate >= 2) return '#16a34a';
  if (changeRate >= 0.5) return '#22c55e';
  if (changeRate >= 0) return '#86efac';
  if (changeRate >= -0.5) return '#fca5a5';
  if (changeRate >= -2) return '#ef4444';
  return '#dc2626';
}

// 배경 색상에 따른 텍스트 색상 결정 (가독성 보장)
function getTextColor(changeRate: number | null | undefined): string {
  if (changeRate == null) return '#fff';
  if (changeRate >= 2 || changeRate < -2) return '#fff';
  if (changeRate >= 0.5 || changeRate < -0.5) return '#fff';
  return '#333';
}

interface SectorHeatmapProps {
  sectors: Sector[];
}

export default function SectorHeatmap({ sectors }: SectorHeatmapProps): React.ReactElement | null {
  const router = useRouter();

  if (sectors.length === 0) return null;

  // 종목 수 기반으로 셀 크기 결정 (최소 1, flex-grow로 비율 적용)
  const maxStockCount = Math.max(...sectors.map((s) => s.total_stocks ?? s.stock_count ?? 1), 1);

  return (
    <div className="w-full">
      <div className="flex flex-wrap gap-[2px]">
        {sectors.map((sector) => {
          const stockCount = sector.total_stocks ?? sector.stock_count ?? 1;
          const changeRate = sector.change_rate;
          const bgColor = getHeatmapColor(changeRate);
          const textColor = getTextColor(changeRate);

          // 셀 크기: 종목 수에 비례 (최소 너비 보장)
          const ratio = stockCount / maxStockCount;
          const minWidth = 90;
          const maxWidth = 220;
          const width = Math.round(minWidth + ratio * (maxWidth - minWidth));

          // 높이도 비율에 따라 조정
          const minHeight = 52;
          const maxHeight = 80;
          const height = Math.round(minHeight + ratio * (maxHeight - minHeight));

          return (
            <button
              key={sector.id}
              onClick={() => router.push(`/sectors/${sector.id}`)}
              className="flex flex-col items-center justify-center rounded-sm cursor-pointer transition-opacity hover:opacity-85 active:opacity-70"
              style={{
                backgroundColor: bgColor,
                color: textColor,
                width: `${width}px`,
                height: `${height}px`,
                flexGrow: stockCount,
                flexShrink: 1,
                flexBasis: `${width}px`,
              }}
              title={`${formatSectorName(sector.name)} | ${changeRate != null ? `${changeRate >= 0 ? '+' : ''}${changeRate.toFixed(2)}%` : '데이터 없음'} | ${stockCount}종목`}
            >
              <span
                className="font-medium truncate px-1 leading-tight"
                style={{ fontSize: height > 60 ? '12px' : '11px', maxWidth: `${width - 8}px` }}
              >
                {formatSectorName(sector.name)}
              </span>
              <span
                className="font-bold leading-tight"
                style={{ fontSize: height > 60 ? '13px' : '11px' }}
              >
                {changeRate != null
                  ? `${changeRate >= 0 ? '+' : ''}${changeRate.toFixed(2)}%`
                  : '-'}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
