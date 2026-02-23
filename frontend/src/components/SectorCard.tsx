"use client";

import Link from "next/link";
import type { Sector } from "@/lib/types";

export default function SectorCard({ sector }: { sector: Sector }) {
  return (
    <Link href={`/sectors/${sector.id}`}>
      <div className="bg-white rounded-lg border border-gray-200 p-5 hover:shadow-md hover:border-blue-300 transition-all cursor-pointer">
        <h3 className="text-lg font-semibold text-gray-900 mb-1">
          {sector.name}
        </h3>
        <div className="flex items-center gap-2">
          <span className="text-sm text-gray-500">
            종목 {sector.stock_count ?? 0}개
          </span>
          {sector.is_custom && (
            <span className="text-xs px-2 py-0.5 rounded bg-blue-50 text-blue-600">
              커스텀
            </span>
          )}
        </div>
      </div>
    </Link>
  );
}
