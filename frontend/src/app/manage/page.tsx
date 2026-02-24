"use client";

import { useEffect, useState } from "react";
import { formatSectorName } from "@/lib/format";
import {
  fetchSectors,
  fetchSector,
  createSector,
  deleteSector,
  createStock,
  deleteStock,
  syncStocks,
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
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState<string | null>(null);
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

  async function handleSyncStocks() {
    setSyncing(true);
    setSyncResult(null);
    try {
      const result = await syncStocks();
      setSyncResult(`전종목 동기화 완료: ${result.added}개 종목 추가됨`);
      await loadSectors();
      if (selectedSector) {
        await handleSelectSector(selectedSector.id);
      }
    } catch {
      setError("전종목 동기화 실패");
    } finally {
      setSyncing(false);
    }
  }

  return (
    <div>
      {/* Alerts */}
      {syncResult && (
        <div className="mb-3 p-3 bg-[#e8f5e9] text-[#2e7d32] text-[13px] flex items-center justify-between">
          {syncResult}
          <button onClick={() => setSyncResult(null)} className="text-[#2e7d32] hover:underline text-[12px]">
            닫기
          </button>
        </div>
      )}
      {error && (
        <div className="mb-3 p-3 bg-[#fde8eb] text-[#e12343] text-[13px] flex items-center justify-between">
          {error}
          <button onClick={() => setError(null)} className="text-[#e12343] hover:underline text-[12px]">
            닫기
          </button>
        </div>
      )}

      <div className="flex gap-4">
        {/* Left: Sector list */}
        <div className="w-[400px] shrink-0">
          <div className="section-box">
            <div className="section-title">
              <span>업종 목록</span>
              <button
                onClick={handleSyncStocks}
                disabled={syncing}
                className="px-3 py-1 text-[12px] bg-[#1261c4] text-white rounded hover:bg-[#0f54a8] disabled:opacity-50"
              >
                {syncing ? "동기화 중..." : "전종목 동기화"}
              </button>
            </div>

            {/* Add sector form */}
            <form onSubmit={handleCreateSector} className="flex gap-2 p-3 border-b border-[#f0f0f0]">
              <input
                type="text"
                value={newSectorName}
                onChange={(e) => setNewSectorName(e.target.value)}
                placeholder="새 업종명 입력"
                className="flex-1 px-2 py-1.5 border border-[#ddd] text-[13px] focus:outline-none focus:border-[#1261c4]"
              />
              <button
                type="submit"
                className="px-3 py-1.5 bg-[#333] text-white text-[12px] hover:bg-[#555]"
              >
                추가
              </button>
            </form>

            {/* Sector table */}
            <table className="naver-table">
              <thead>
                <tr>
                  <th className="text-left" style={{ width: "55%" }}>업종명</th>
                  <th style={{ width: "25%" }}>종목수</th>
                  <th style={{ width: "20%" }}></th>
                </tr>
              </thead>
              <tbody>
                {sectors.map((sector) => (
                  <tr
                    key={sector.id}
                    className={`cursor-pointer ${selectedSector?.id === sector.id ? "!bg-[#f0f7ff]" : ""}`}
                    onClick={() => handleSelectSector(sector.id)}
                  >
                    <td>
                      <span className="font-medium text-[#333]">{formatSectorName(sector.name)}</span>
                      {sector.is_custom && (
                        <span className="badge badge-source ml-1">커스텀</span>
                      )}
                    </td>
                    <td className="text-center">{sector.stock_count ?? 0}</td>
                    <td className="text-center">
                      {sector.is_custom && (
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            handleDeleteSector(sector.id);
                          }}
                          className="text-[11px] text-[#e12343] hover:underline"
                        >
                          삭제
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Right: Stock management */}
        <div className="flex-1 min-w-0">
          {selectedSector ? (
            <div className="section-box">
              <div className="section-title">
                <span>{selectedSector.name} - 종목 관리</span>
                <span className="text-[12px] font-normal text-[#999]">
                  {selectedSector.stocks?.length ?? 0}개 종목
                </span>
              </div>

              {/* Add stock form */}
              <form onSubmit={handleCreateStock} className="p-3 border-b border-[#f0f0f0]">
                <div className="flex gap-2 mb-2">
                  <input
                    type="text"
                    value={stockForm.name}
                    onChange={(e) => setStockForm({ ...stockForm, name: e.target.value })}
                    placeholder="종목명"
                    className="flex-1 px-2 py-1.5 border border-[#ddd] text-[13px] focus:outline-none focus:border-[#1261c4]"
                  />
                  <input
                    type="text"
                    value={stockForm.stock_code}
                    onChange={(e) => setStockForm({ ...stockForm, stock_code: e.target.value })}
                    placeholder="종목코드"
                    className="w-[120px] px-2 py-1.5 border border-[#ddd] text-[13px] focus:outline-none focus:border-[#1261c4]"
                  />
                </div>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={stockForm.keywords}
                    onChange={(e) => setStockForm({ ...stockForm, keywords: e.target.value })}
                    placeholder="키워드 (쉼표 구분)"
                    className="flex-1 px-2 py-1.5 border border-[#ddd] text-[13px] focus:outline-none focus:border-[#1261c4]"
                  />
                  <button
                    type="submit"
                    className="px-4 py-1.5 bg-[#1261c4] text-white text-[12px] hover:bg-[#0f54a8]"
                  >
                    종목 추가
                  </button>
                </div>
              </form>

              {/* Stock table */}
              <table className="naver-table">
                <thead>
                  <tr>
                    <th className="text-left" style={{ width: "35%" }}>종목명</th>
                    <th style={{ width: "20%" }}>종목코드</th>
                    <th style={{ width: "35%" }}>키워드</th>
                    <th style={{ width: "10%" }}></th>
                  </tr>
                </thead>
                <tbody>
                  {!selectedSector.stocks || selectedSector.stocks.length === 0 ? (
                    <tr>
                      <td colSpan={4} className="text-center py-6 text-[#999]">
                        등록된 종목이 없습니다.
                      </td>
                    </tr>
                  ) : (
                    selectedSector.stocks.map((stock: Stock) => (
                      <tr key={stock.id}>
                        <td className="font-medium">{stock.name}</td>
                        <td className="text-center text-[#666]">{stock.stock_code}</td>
                        <td className="text-center">
                          {stock.keywords && stock.keywords.length > 0 ? (
                            <div className="flex flex-wrap gap-1 justify-center">
                              {stock.keywords.map((kw, i) => (
                                <span key={i} className="badge badge-market">{kw}</span>
                              ))}
                            </div>
                          ) : (
                            <span className="text-[#ccc]">-</span>
                          )}
                        </td>
                        <td className="text-center">
                          <button
                            onClick={() => handleDeleteStock(stock.id)}
                            className="text-[11px] text-[#e12343] hover:underline"
                          >
                            삭제
                          </button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="section-box">
              <div className="flex items-center justify-center h-[300px] text-[#999] text-[14px]">
                왼쪽에서 업종을 선택하세요
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
