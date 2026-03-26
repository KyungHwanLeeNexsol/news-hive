"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { fetchCommodities } from "@/lib/api";
import type { Commodity } from "@/lib/types";
import ChangeRate from "@/components/ChangeRate";
import { useMarketRefresh } from "@/lib/useMarketRefresh";

const CATEGORY_LABELS: Record<string, string> = {
  energy: "에너지",
  metal: "금속",
  agriculture: "농산물",
};

function formatPrice(price: number, currency: string): string {
  if (currency === "USD") {
    return `$${price.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }
  if (currency === "KRW") {
    return `${price.toLocaleString("ko-KR")}원`;
  }
  return price.toLocaleString();
}

export default function CommodityTicker() {
  const [commodities, setCommodities] = useState<Commodity[]>([]);
  const [loading, setLoading] = useState(true);

  const loadData = () => {
    fetchCommodities()
      .then(setCommodities)
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => { loadData(); }, []);
  useMarketRefresh(loadData);

  if (loading) {
    return (
      <div className="section-box mb-3">
        <div className="flex items-center gap-4 px-4 py-2.5 overflow-hidden">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="flex items-center gap-2 shrink-0">
              <div className="skeleton skeleton-text" style={{ width: "60px" }} />
              <div className="skeleton skeleton-text" style={{ width: "80px" }} />
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (commodities.length === 0) return null;

  // 카테고리별 그룹핑
  const grouped = new Map<string, Commodity[]>();
  for (const c of commodities) {
    const list = grouped.get(c.category) ?? [];
    list.push(c);
    grouped.set(c.category, list);
  }

  return (
    <div className="section-box mb-3">
      <div className="flex items-center justify-between px-4 py-1.5 border-b border-[#e5e5e5]">
        <span className="text-[12px] font-bold text-[#333]">원자재 시세</span>
        <Link href="/commodities" className="text-[11px] text-[#1261c4] hover:underline">
          전체보기 &rsaquo;
        </Link>
      </div>
      <div className="flex overflow-x-auto scrollbar-hide">
        {["energy", "metal", "agriculture"].map((cat) => {
          const items = grouped.get(cat);
          if (!items || items.length === 0) return null;
          return (
            <div key={cat} className="flex items-center shrink-0">
              <span className="text-[10px] text-[#999] font-medium px-3 py-2 whitespace-nowrap">
                {CATEGORY_LABELS[cat] ?? cat}
              </span>
              {items.map((c) => (
                <Link
                  key={c.id}
                  href={`/commodities?selected=${c.id}`}
                  className="flex items-center gap-1.5 px-3 py-2 border-r border-[#f0f0f0] hover:bg-[#f7f8fa] transition-colors whitespace-nowrap"
                >
                  <span className="text-[12px] font-medium text-[#333]">{c.name_ko}</span>
                  {c.latest_price ? (
                    <>
                      <span className="text-[12px] text-[#333]">
                        {formatPrice(c.latest_price.price, c.currency)}
                      </span>
                      <ChangeRate value={c.latest_price.change_pct} />
                    </>
                  ) : (
                    <span className="text-[11px] text-[#999]">-</span>
                  )}
                </Link>
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}
