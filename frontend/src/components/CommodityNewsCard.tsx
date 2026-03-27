"use client";

import Link from "next/link";
import type { CommodityNewsArticle, CommodityNewsRelation } from "@/lib/types";

const IMPACT_LABELS: Record<string, { text: string; className: string }> = {
  price_up: { text: "가격상승", className: "bg-[#e8f5e9] text-[#2e7d32]" },
  price_down: { text: "가격하락", className: "bg-[#ffebee] text-[#c62828]" },
  supply_disruption: { text: "공급차질", className: "bg-[#fff3e0] text-[#e65100]" },
  demand_change: { text: "수요변화", className: "bg-[#e3f2fd] text-[#1565c0]" },
  policy_change: { text: "정책변경", className: "bg-[#f3e5f5] text-[#7b1fa2]" },
};

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "";
  const d = new Date(dateStr);
  return d.toLocaleDateString("ko-KR", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function sentimentLabel(sentiment: string | null): { text: string; className: string } {
  switch (sentiment) {
    case "positive": return { text: "호재", className: "badge-positive" };
    case "negative": return { text: "악재", className: "badge-negative" };
    default: return { text: "중립", className: "badge-neutral" };
  }
}

function ImpactBadge({ rel }: { rel: CommodityNewsRelation }) {
  const impact = rel.impact_direction ? IMPACT_LABELS[rel.impact_direction] : null;
  const isPriceChange = rel.impact_direction === "price_up" || rel.impact_direction === "price_down";

  if (impact && isPriceChange) {
    // 가격상승/가격하락: 원자재명과 함께 하나의 뱃지로 표현
    return (
      <span className={`inline-flex items-center gap-0.5 px-1.5 py-0.5 text-[11px] font-medium rounded ${impact.className}`}>
        {rel.name_ko}
        <span className="mx-0.5 opacity-60">·</span>
        {impact.text}
      </span>
    );
  }

  return (
    <span className="inline-flex items-center gap-1">
      <span className="inline-block px-1.5 py-0.5 text-[11px] font-medium rounded bg-[#f0f0f0] text-[#555]">
        {rel.name_ko}
      </span>
      {impact && (
        <span className={`inline-block px-1.5 py-0.5 text-[10px] font-medium rounded ${impact.className}`}>
          {impact.text}
        </span>
      )}
    </span>
  );
}

interface CommodityNewsCardProps {
  article: CommodityNewsArticle;
}

export default function CommodityNewsCard({ article }: CommodityNewsCardProps) {
  const sentiment = sentimentLabel(article.sentiment);

  return (
    <tr>
      <td>
        <Link
          href={`/news/${article.id}`}
          className="text-[#333] hover:text-[#1261c4] hover:underline"
        >
          {article.title}
        </Link>
        {article.summary && (
          <p className="text-[11px] text-[#999] mt-0.5 truncate max-w-[500px]">
            {article.summary}
          </p>
        )}
      </td>
      <td className="text-center">
        <span className={`badge ${sentiment.className}`}>
          {sentiment.text}
        </span>
      </td>
      <td>
        <div className="flex flex-wrap gap-1 justify-center">
          {article.commodity_relations?.slice(0, 3).map((rel) => (
            <ImpactBadge key={rel.commodity_id} rel={rel} />
          ))}
        </div>
      </td>
      <td className="text-center text-[12px] text-[#999]">
        {formatDate(article.published_at)}
      </td>
    </tr>
  );
}
