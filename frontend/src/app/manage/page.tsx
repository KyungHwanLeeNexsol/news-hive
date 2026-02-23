"use client";

import { useEffect, useState } from "react";
import {
  fetchSectors,
  fetchSector,
  createSector,
  deleteSector,
  createStock,
  deleteStock,
} from "@/lib/api";
import type { Sector, Stock } from "@/lib/types";

export default function ManagePage() {
  const [sectors, setSectors] = useState<Sector[]>([]);
  const [selectedSector, setSelectedSector] = useState<Sector | null>(null);
  const [newSectorName, setNewSectorName] = useState("");
  const [stockForm, setStockForm] = useState({
    name: "",
    stock_code: "",
    keywords: "",
  });
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadSectors();
  }, []);

  async function loadSectors() {
    try {
      const data = await fetchSectors();
      setSectors(data);
    } catch {
      setError("섹터 목록 로딩 실패");
    }
  }

  async function handleSelectSector(id: number) {
    try {
      const data = await fetchSector(id);
      setSelectedSector(data);
    } catch {
      setError("섹터 상세 로딩 실패");
    }
  }

  async function handleCreateSector(e: React.FormEvent) {
    e.preventDefault();
    if (!newSectorName.trim()) return;
    try {
      await createSector(newSectorName.trim());
      setNewSectorName("");
      await loadSectors();
    } catch {
      setError("섹터 생성 실패");
    }
  }

  async function handleDeleteSector(id: number) {
    if (!confirm("이 섹터를 삭제하시겠습니까?")) return;
    try {
      await deleteSector(id);
      if (selectedSector?.id === id) setSelectedSector(null);
      await loadSectors();
    } catch {
      setError("섹터 삭제 실패 (기본 섹터는 삭제 불가)");
    }
  }

  async function handleCreateStock(e: React.FormEvent) {
    e.preventDefault();
    if (!selectedSector || !stockForm.name.trim() || !stockForm.stock_code.trim())
      return;
    try {
      const keywords = stockForm.keywords
        .split(",")
        .map((k) => k.trim())
        .filter((k) => k);
      await createStock(selectedSector.id, {
        name: stockForm.name.trim(),
        stock_code: stockForm.stock_code.trim(),
        keywords: keywords.length > 0 ? keywords : undefined,
      });
      setStockForm({ name: "", stock_code: "", keywords: "" });
      await handleSelectSector(selectedSector.id);
      await loadSectors();
    } catch {
      setError("종목 추가 실패");
    }
  }

  async function handleDeleteStock(stockId: number) {
    if (!confirm("이 종목을 삭제하시겠습니까?")) return;
    try {
      await deleteStock(stockId);
      if (selectedSector) {
        await handleSelectSector(selectedSector.id);
      }
      await loadSectors();
    } catch {
      setError("종목 삭제 실패");
    }
  }

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-6">섹터/종목 관리</h1>

      {error && (
        <div className="mb-4 p-3 bg-red-50 text-red-700 rounded-lg text-sm">
          {error}
          <button
            onClick={() => setError(null)}
            className="ml-2 text-red-500 hover:text-red-700"
          >
            닫기
          </button>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Left: Sector list */}
        <div>
          <h2 className="text-lg font-semibold text-gray-800 mb-3">
            섹터 목록
          </h2>

          <form onSubmit={handleCreateSector} className="flex gap-2 mb-4">
            <input
              type="text"
              value={newSectorName}
              onChange={(e) => setNewSectorName(e.target.value)}
              placeholder="새 섹터명"
              className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <button
              type="submit"
              className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
            >
              추가
            </button>
          </form>

          <div className="space-y-2">
            {sectors.map((sector) => (
              <div
                key={sector.id}
                className={`flex items-center justify-between p-3 rounded-lg border cursor-pointer transition-all ${
                  selectedSector?.id === sector.id
                    ? "border-blue-500 bg-blue-50"
                    : "border-gray-200 bg-white hover:border-gray-300"
                }`}
                onClick={() => handleSelectSector(sector.id)}
              >
                <div>
                  <span className="font-medium text-gray-900">
                    {sector.name}
                  </span>
                  <span className="text-sm text-gray-500 ml-2">
                    ({sector.stock_count ?? 0}종목)
                  </span>
                </div>
                {sector.is_custom && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDeleteSector(sector.id);
                    }}
                    className="text-sm text-red-500 hover:text-red-700 px-2 py-1"
                  >
                    삭제
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Right: Stock management for selected sector */}
        <div>
          {selectedSector ? (
            <>
              <h2 className="text-lg font-semibold text-gray-800 mb-3">
                {selectedSector.name} - 종목 관리
              </h2>

              <form onSubmit={handleCreateStock} className="mb-4 space-y-2">
                <input
                  type="text"
                  value={stockForm.name}
                  onChange={(e) =>
                    setStockForm({ ...stockForm, name: e.target.value })
                  }
                  placeholder="종목명 (예: 대창단조)"
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                <input
                  type="text"
                  value={stockForm.stock_code}
                  onChange={(e) =>
                    setStockForm({ ...stockForm, stock_code: e.target.value })
                  }
                  placeholder="종목코드 (예: 015230)"
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                <input
                  type="text"
                  value={stockForm.keywords}
                  onChange={(e) =>
                    setStockForm({ ...stockForm, keywords: e.target.value })
                  }
                  placeholder="키워드 (쉼표 구분, 예: 포크레인,하부구조물)"
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                <button
                  type="submit"
                  className="w-full px-4 py-2 bg-green-600 text-white text-sm font-medium rounded-lg hover:bg-green-700 transition-colors"
                >
                  종목 추가
                </button>
              </form>

              <div className="space-y-2">
                {selectedSector.stocks?.map((stock: Stock) => (
                  <div
                    key={stock.id}
                    className="flex items-center justify-between p-3 bg-white rounded-lg border border-gray-200"
                  >
                    <div>
                      <span className="font-medium text-gray-900">
                        {stock.name}
                      </span>
                      <span className="text-sm text-gray-500 ml-2">
                        {stock.stock_code}
                      </span>
                      {stock.keywords && stock.keywords.length > 0 && (
                        <div className="flex flex-wrap gap-1 mt-1">
                          {stock.keywords.map((kw, i) => (
                            <span
                              key={i}
                              className="text-xs px-2 py-0.5 bg-gray-100 text-gray-600 rounded"
                            >
                              {kw}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                    <button
                      onClick={() => handleDeleteStock(stock.id)}
                      className="text-sm text-red-500 hover:text-red-700 px-2 py-1"
                    >
                      삭제
                    </button>
                  </div>
                ))}
                {(!selectedSector.stocks ||
                  selectedSector.stocks.length === 0) && (
                  <p className="text-gray-500 text-sm">
                    등록된 종목이 없습니다.
                  </p>
                )}
              </div>
            </>
          ) : (
            <div className="flex items-center justify-center h-full text-gray-400">
              <p>왼쪽에서 섹터를 선택하세요</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
