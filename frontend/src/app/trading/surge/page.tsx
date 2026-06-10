'use client';

import { useEffect, useState } from 'react';
import { fetchSurgePredictionHistory } from '@/lib/api';
import type { SurgePredictionDay, SurgeSignalRecord } from '@/lib/types';
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  Cell,
  ResponsiveContainer,
} from 'recharts';

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

function fmtPrice(n: number | null | undefined): string {
  if (n == null) return '-';
  return n.toLocaleString('ko-KR') + '원';
}

const ERROR_LABELS: Record<string, string> = {
  macro_shock: '거시충격',
  supply_reversal: '공급역전',
  earnings_miss: '실적미스',
  sector_contagion: '섹터전염',
  technical_breakdown: '기술붕괴',
};

function StatCard({ label, value, sub, highlight }: { label: string; value: string; sub?: string; highlight?: boolean }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 flex flex-col gap-1">
      <span className="text-[12px] text-gray-500 font-medium">{label}</span>
      <span className={`text-[18px] font-bold ${highlight ? 'text-[#e12343]' : 'text-gray-900'}`}>{value}</span>
      {sub && <span className="text-[12px] text-gray-400">{sub}</span>}
    </div>
  );
}

function SignalRow({ s }: { s: SurgeSignalRecord }) {
  const typeLabel = s.signal_type === 'surge_candidate' ? '급등후보' : '공시선행';
  return (
    <tr className="border-b border-gray-100 hover:bg-gray-50 transition-colors">
      <td className="px-4 py-2">
        <div className="font-semibold text-gray-800 text-[12px]">{s.stock_name}</div>
        <div className="text-[10px] text-gray-400">{s.stock_code}</div>
      </td>
      <td className="px-3 py-2 text-[11px]">
        <span className="bg-blue-50 text-blue-600 px-2 py-0.5 rounded-full text-[10px]">{typeLabel}</span>
      </td>
      <td className="px-3 py-2 text-right text-[12px] text-gray-600">
        {(s.confidence * 100).toFixed(0)}%
      </td>
      <td className="px-3 py-2 text-right text-[12px] text-gray-600">{fmtPrice(s.price_at_signal)}</td>
      <td className="px-3 py-2 text-right text-[12px] text-gray-600">{fmtPrice(s.price_after_1d)}</td>
      <td className={`px-3 py-2 text-right text-[12px] font-semibold ${pctColor(s.return_pct)}`}>
        {fmtPct(s.return_pct)}
      </td>
      <td className={`px-3 py-2 text-right text-[12px] font-semibold ${pctColor(s.alpha_pct)}`}>
        {fmtPct(s.alpha_pct)}
      </td>
      <td className="px-3 py-2 text-center text-[12px]">
        {s.is_correct === null ? (
          <span className="text-gray-300">-</span>
        ) : s.is_correct ? (
          <span className="text-[#e12343] font-bold">적중</span>
        ) : (
          <span className="text-[#1261c4]">오류</span>
        )}
      </td>
      <td className="px-3 py-2 text-[11px] text-gray-500">
        {s.error_category ? (ERROR_LABELS[s.error_category] ?? s.error_category) : '-'}
      </td>
    </tr>
  );
}

function DayRow({ day }: { day: SurgePredictionDay }) {
  const [open, setOpen] = useState(false);

  const topError = Object.entries(day.error_breakdown).sort((a, b) => b[1] - a[1])[0];

  return (
    <>
      <tr
        className="border-b border-gray-100 hover:bg-gray-50 transition-colors cursor-pointer"
        onClick={() => setOpen((v) => !v)}
      >
        <td className="px-4 py-3 text-[13px] font-semibold text-gray-800">
          <span className="mr-2 text-gray-400 text-[11px]">{open ? '▲' : '▼'}</span>
          {day.trading_date}
        </td>
        <td className="px-4 py-3 text-[13px] text-gray-600">
          {day.target_date ?? <span className="text-gray-300">-</span>}
        </td>
        <td className="px-4 py-3 text-right text-[13px] text-gray-700">{day.predicted_count}</td>
        <td className="px-4 py-3 text-right text-[13px] text-gray-700">
          <span className="text-[#e12343] font-semibold">{day.true_positive ?? '-'}</span>
          <span className="text-gray-400 mx-1">/</span>
          <span className="text-[#1261c4]">{day.false_positive ?? '-'}</span>
        </td>
        <td className={`px-4 py-3 text-right text-[13px] font-semibold ${pctColor(day.precision != null ? day.precision * 100 - 20 : null)}`}>
          {day.precision != null ? `${(day.precision * 100).toFixed(1)}%` : '-'}
        </td>
        <td className={`px-4 py-3 text-right text-[13px] font-semibold ${pctColor(day.avg_alpha_pct)}`}>
          {fmtPct(day.avg_alpha_pct)}
        </td>
        <td className="px-4 py-3 text-right text-[12px] text-gray-500">
          {topError ? `${ERROR_LABELS[topError[0]] ?? topError[0]} (${topError[1]})` : '-'}
        </td>
      </tr>
      {open && (
        <tr>
          <td colSpan={7} className="bg-gray-50 px-4 py-3">
            {day.signals.length === 0 ? (
              <div className="text-[12px] text-gray-400 text-center py-3">시그널 없음</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-[12px]">
                  <thead>
                    <tr className="border-b border-gray-200">
                      <th className="text-left px-4 py-2 text-gray-500 font-semibold">종목</th>
                      <th className="text-left px-3 py-2 text-gray-500 font-semibold">유형</th>
                      <th className="text-right px-3 py-2 text-gray-500 font-semibold">확률</th>
                      <th className="text-right px-3 py-2 text-gray-500 font-semibold">예측가</th>
                      <th className="text-right px-3 py-2 text-gray-500 font-semibold">실제가(+1일)</th>
                      <th className="text-right px-3 py-2 text-gray-500 font-semibold">등락률</th>
                      <th className="text-right px-3 py-2 text-gray-500 font-semibold">초과수익률</th>
                      <th className="text-center px-3 py-2 text-gray-500 font-semibold">적중</th>
                      <th className="text-right px-3 py-2 text-gray-500 font-semibold">오류분류</th>
                    </tr>
                  </thead>
                  <tbody>
                    {day.signals.map((s, i) => (
                      <SignalRow key={i} s={s} />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </td>
        </tr>
      )}
    </>
  );
}

function SurgeContent() {
  const [data, setData] = useState<SurgePredictionDay[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchSurgePredictionHistory(30)
      .then(setData)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="text-center py-8 text-gray-400 text-[13px]">로딩 중...</div>;
  if (data.length === 0)
    return <div className="text-center py-8 text-gray-400 text-[13px]">예측 기록이 없습니다</div>;

  // 요약 계산
  const totalPredicted = data.reduce((s, d) => s + d.predicted_count, 0);
  const totalTP = data.reduce((s, d) => s + d.true_positive, 0);
  const totalFP = data.reduce((s, d) => s + d.false_positive, 0);
  const overallPrecision = totalTP + totalFP > 0 ? totalTP / (totalTP + totalFP) : null;
  const alphas = data.flatMap((d) => d.signals.map((s) => s.alpha_pct).filter((v): v is number => v != null));
  const avgAlpha = alphas.length > 0 ? alphas.reduce((a, b) => a + b, 0) / alphas.length : null;

  // 최근 7일 추세
  const recent7 = data.slice(0, 7);
  const prev7 = data.slice(7, 14);
  const recentPrec = recent7.filter((d) => d.precision != null);
  const prevPrec = prev7.filter((d) => d.precision != null);
  const recentAvg = recentPrec.length > 0 ? recentPrec.reduce((s, d) => s + (d.precision ?? 0), 0) / recentPrec.length : null;
  const prevAvg = prevPrec.length > 0 ? prevPrec.reduce((s, d) => s + (d.precision ?? 0), 0) / prevPrec.length : null;
  const trend =
    recentAvg == null || prevAvg == null
      ? '→ 데이터 부족'
      : recentAvg > prevAvg + 0.02
      ? '↑ 개선'
      : recentAvg < prevAvg - 0.02
      ? '↓ 하락'
      : '→ 보합';

  // 정확도 추이 차트 (날짜 오름차순)
  const chartData = [...data].reverse().map((d) => ({
    date: d.trading_date.slice(5),
    precision: d.precision != null ? +(d.precision * 100).toFixed(1) : null,
    recall: d.recall != null ? +(d.recall * 100).toFixed(1) : null,
    f1: d.f1_score != null ? +(d.f1_score * 100).toFixed(1) : null,
  }));

  // 오류 원인 집계
  const errorTotals: Record<string, number> = {};
  data.forEach((d) => {
    Object.entries(d.error_breakdown).forEach(([k, v]) => {
      errorTotals[k] = (errorTotals[k] ?? 0) + v;
    });
  });
  const errorChartData = Object.entries(errorTotals).map(([k, v]) => ({
    name: ERROR_LABELS[k] ?? k,
    count: v,
  }));

  return (
    <div className="flex flex-col gap-6">
      {/* 섹션 1: 요약 카드 */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard label="총 예측 건수" value={`${totalPredicted.toLocaleString()}건`} sub={`최근 ${data.length}거래일`} />
        <StatCard
          label="전체 정밀도"
          value={overallPrecision != null ? `${(overallPrecision * 100).toFixed(1)}%` : '-'}
          sub={`적중 ${totalTP} / 오보 ${totalFP}`}
          highlight={overallPrecision != null && overallPrecision >= 0.3}
        />
        <StatCard
          label="평균 초과수익률"
          value={avgAlpha != null ? fmtPct(avgAlpha) : '-'}
          sub="검증 완료 시그널"
        />
        <StatCard label="7일 추세" value={trend} />
      </div>

      {/* 섹션 2: 날짜별 예측 기록 테이블 */}
      <div>
        <h2 className="text-[15px] font-bold text-gray-800 mb-3">날짜별 예측 기록</h2>
        <div className="bg-white rounded-xl border border-gray-200 overflow-x-auto">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="text-left px-4 py-3 font-semibold text-gray-600">시그널 생성일</th>
                <th className="text-left px-4 py-3 font-semibold text-gray-600">예측 대상일</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-600">예측 수</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-600">적중 / 오보</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-600">정밀도</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-600">평균 초과수익률</th>
                <th className="text-right px-4 py-3 font-semibold text-gray-600">주요 오류</th>
              </tr>
            </thead>
            <tbody>
              {data.map((day) => (
                <DayRow key={day.trading_date} day={day} />
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* 섹션 3: 정확도 추이 차트 */}
      {chartData.length > 0 && (
        <div>
          <h2 className="text-[15px] font-bold text-gray-800 mb-3">정확도 추이</h2>
          <div className="bg-white rounded-xl border border-gray-200 p-4">
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={chartData} margin={{ top: 4, right: 8, left: 8, bottom: 4 }}>
                <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#999' }} interval="preserveStartEnd" />
                <YAxis
                  tick={{ fontSize: 10, fill: '#999' }}
                  tickFormatter={(v: number) => `${v}%`}
                  domain={[0, 100]}
                />
                <Tooltip formatter={(v) => [`${v}%`]} labelFormatter={(l) => String(l)} />
                <Legend wrapperStyle={{ fontSize: '11px' }} />
                <Line type="monotone" dataKey="precision" stroke="#e12343" name="정밀도" dot={false} strokeWidth={2} connectNulls />
                <Line type="monotone" dataKey="recall" stroke="#1261c4" name="재현율" dot={false} strokeWidth={1.5} connectNulls />
                <Line type="monotone" dataKey="f1" stroke="#f59e0b" name="F1" dot={false} strokeWidth={1.5} connectNulls />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* 섹션 4: 오류 원인 분류 차트 */}
      {errorChartData.length > 0 && (
        <div>
          <h2 className="text-[15px] font-bold text-gray-800 mb-3">오류 원인 분류 (전체 기간)</h2>
          <div className="bg-white rounded-xl border border-gray-200 p-4">
            <ResponsiveContainer width="100%" height={160}>
              <BarChart data={errorChartData} margin={{ top: 4, right: 8, left: 8, bottom: 4 }}>
                <XAxis dataKey="name" tick={{ fontSize: 10, fill: '#999' }} />
                <YAxis tick={{ fontSize: 10, fill: '#999' }} />
                <Tooltip />
                <Bar dataKey="count" name="건수" radius={[3, 3, 0, 0]}>
                  {errorChartData.map((_, i) => (
                    <Cell key={i} fill={['#e12343', '#1261c4', '#f59e0b', '#10b981', '#8b5cf6'][i % 5]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </div>
  );
}

export default function SurgePage() {
  return (
    <div className="max-w-[1200px] mx-auto px-4 py-6">
      <div className="mb-6">
        <h1 className="text-[22px] font-bold text-gray-900">급등 예측 기록</h1>
        <p className="text-[13px] text-gray-500 mt-1">
          매 거래일 전날 생성된 시그널의 실제 적중률 추적 — 자동 가중치 개선 포함
        </p>
      </div>
      <SurgeContent />
    </div>
  );
}
