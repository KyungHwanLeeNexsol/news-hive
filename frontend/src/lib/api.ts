import type { Sector, Stock, StockListItem, NewsArticle, NewsRelation, StockDetail, FinancialPeriod, PriceRecord, SentimentTrendItem, SectorInsight, DisclosureItem, DisclosureDetail, MacroAlert, EconomicEvent, FundSignal, DailyBriefing, PortfolioReport, AccuracyStats, StockNewsImpactStats, Commodity, CommodityHistoryPoint, SectorCommodity, CommodityNewsArticle, PaperTradingStats, PaperPosition, PaperTrade, PaperSnapshot, ChatResponse, BacktestResult, NewsPriceCorrelation } from "./types";

const API_BASE = "/api";

/**
 * 502/503 응답 시 점검 페이지로 리디렉션 (배포 중 백엔드 재시작 감지)
 */
function _redirectToMaintenance(): void {
  if (
    typeof window !== "undefined" &&
    !window.location.pathname.startsWith("/maintenance")
  ) {
    window.location.href = "/maintenance";
  }
}

/**
 * Fetch with automatic retry — handles backend cold starts / restarts.
 * 502/503 after all retries → redirects to /maintenance (server down during deploy).
 */
async function fetchWithRetry(
  input: RequestInfo | URL,
  init?: RequestInit,
  retries = 1,
): Promise<Response> {
  // Prevent browser/Next.js fetch caching for real-time data
  const opts: RequestInit = { cache: "no-store", ...init };
  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      const res = await fetch(input, opts);
      if (res.ok || res.status < 500 || attempt === retries) {
        // 최종 재시도 후에도 502/503이면 점검 페이지로
        if (attempt === retries && (res.status === 502 || res.status === 503)) {
          _redirectToMaintenance();
        }
        return res;
      }
      // 5xx — wait and retry
      await new Promise((r) => setTimeout(r, 3000));
    } catch (e) {
      if (attempt === retries) {
        // 네트워크 오류(connection refused 등)도 점검 페이지로
        _redirectToMaintenance();
        throw e;
      }
      await new Promise((r) => setTimeout(r, 3000));
    }
  }
  // Unreachable, but TypeScript needs it
  return fetch(input, opts);
}

export async function fetchSectors(): Promise<Sector[]> {
  const res = await fetchWithRetry(`${API_BASE}/sectors`);
  if (!res.ok) throw new Error("Failed to fetch sectors");
  return res.json();
}

export async function fetchSector(id: number): Promise<Sector> {
  const res = await fetchWithRetry(`${API_BASE}/sectors/${id}`);
  if (!res.ok) throw new Error("Failed to fetch sector");
  return res.json();
}

export async function createSector(name: string): Promise<Sector> {
  const res = await fetch(`${API_BASE}/sectors`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!res.ok) throw new Error("Failed to create sector");
  return res.json();
}

export async function deleteSector(id: number): Promise<void> {
  const res = await fetch(`${API_BASE}/sectors/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error("Failed to delete sector");
}

export async function fetchSectorNews(
  id: number,
  offset = 0,
  limit = 30,
): Promise<{ articles: NewsArticle[]; total: number }> {
  const res = await fetchWithRetry(`${API_BASE}/sectors/${id}/news?limit=${limit}&offset=${offset}`);
  if (!res.ok) throw new Error("Failed to fetch sector news");
  const total = parseInt(res.headers.get("X-Total-Count") || "0", 10);
  const articles = await res.json();
  return { articles, total };
}

export async function createStock(
  sectorId: number,
  data: { name: string; stock_code: string; keywords?: string[] }
): Promise<Stock> {
  const res = await fetch(`${API_BASE}/sectors/${sectorId}/stocks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error("Failed to create stock");
  return res.json();
}

export async function deleteStock(id: number): Promise<void> {
  const res = await fetch(`${API_BASE}/stocks/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error("Failed to delete stock");
}

export async function fetchStockNews(
  id: number,
  offset = 0,
  limit = 30,
): Promise<{ articles: NewsArticle[]; total: number }> {
  const res = await fetchWithRetry(`${API_BASE}/stocks/${id}/news?limit=${limit}&offset=${offset}`);
  if (!res.ok) throw new Error("Failed to fetch stock news");
  const total = parseInt(res.headers.get("X-Total-Count") || "0", 10);
  const articles = await res.json();
  return { articles, total };
}

export async function fetchNewsById(id: number): Promise<NewsArticle> {
  const res = await fetchWithRetry(`${API_BASE}/news/${id}`);
  if (!res.ok) throw new Error("Failed to fetch news article");
  return res.json();
}

export async function generateAiSummary(id: number): Promise<NewsArticle> {
  const res = await fetch(`${API_BASE}/news/${id}/summary`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to generate AI summary");
  return res.json();
}

export async function scrapeArticleContent(id: number): Promise<NewsArticle> {
  const res = await fetch(`${API_BASE}/news/${id}/content`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to scrape article content");
  return res.json();
}

export async function fetchNews(
  offset = 0,
  limit = 30,
): Promise<{ articles: NewsArticle[]; total: number }> {
  const res = await fetchWithRetry(`${API_BASE}/news?limit=${limit}&offset=${offset}`);
  if (!res.ok) throw new Error("Failed to fetch news");
  const total = parseInt(res.headers.get("X-Total-Count") || "0", 10);
  const articles = await res.json();
  return { articles, total };
}

export async function searchNews(
  query: string,
  offset = 0,
  limit = 30,
): Promise<{ articles: NewsArticle[]; total: number }> {
  const params = new URLSearchParams({ q: query, limit: String(limit), offset: String(offset) });
  const res = await fetchWithRetry(`${API_BASE}/news?${params}`);
  if (!res.ok) throw new Error("Failed to search news");
  const total = parseInt(res.headers.get("X-Total-Count") || "0", 10);
  const articles = await res.json();
  return { articles, total };
}

export async function refreshNews(): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE}/news/refresh`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to refresh news");
  return res.json();
}

export async function syncStocks(): Promise<{ message: string; added: number }> {
  const res = await fetch(`${API_BASE}/stocks/sync`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to sync stocks");
  return res.json();
}

export async function fetchStocks(
  params: { q?: string; market?: string; sector_id?: number; ids?: string; limit?: number; offset?: number } = {},
): Promise<{ stocks: StockListItem[]; total: number }> {
  const sp = new URLSearchParams();
  if (params.q) sp.set("q", params.q);
  if (params.market) sp.set("market", params.market);
  if (params.sector_id) sp.set("sector_id", String(params.sector_id));
  if (params.ids) sp.set("ids", params.ids);
  sp.set("limit", String(params.limit ?? 50));
  sp.set("offset", String(params.offset ?? 0));
  const res = await fetchWithRetry(`${API_BASE}/stocks?${sp}`);
  if (!res.ok) throw new Error("Failed to fetch stocks");
  const total = parseInt(res.headers.get("X-Total-Count") || "0", 10);
  const stocks = await res.json();
  return { stocks, total };
}

export async function fetchStockDetail(id: number): Promise<StockDetail> {
  const res = await fetchWithRetry(`${API_BASE}/stocks/${id}`);
  if (!res.ok) throw new Error("Failed to fetch stock detail");
  return res.json();
}

export async function fetchStockFinancials(
  id: number,
): Promise<{ annual: FinancialPeriod[]; quarter: FinancialPeriod[] }> {
  const res = await fetchWithRetry(`${API_BASE}/stocks/${id}/financials`);
  if (!res.ok) throw new Error("Failed to fetch financials");
  return res.json();
}

export async function fetchStockPrices(id: number, months = 3): Promise<PriceRecord[]> {
  const res = await fetchWithRetry(`${API_BASE}/stocks/${id}/prices?months=${months}`);
  if (!res.ok) throw new Error("Failed to fetch prices");
  return res.json();
}

export async function fetchSentimentTrend(id: number, days = 30): Promise<SentimentTrendItem[]> {
  const res = await fetchWithRetry(`${API_BASE}/stocks/${id}/sentiment-trend?days=${days}`);
  if (!res.ok) throw new Error("Failed to fetch sentiment trend");
  return res.json();
}

export async function fetchStockNewsImpactStats(id: number, days = 30): Promise<StockNewsImpactStats> {
  const res = await fetchWithRetry(`${API_BASE}/stocks/${id}/news-impact-stats?days=${days}`);
  if (!res.ok) throw new Error("Failed to fetch news impact stats");
  return res.json();
}

export async function generateSectorInsight(id: number): Promise<SectorInsight> {
  const res = await fetch(`${API_BASE}/sectors/${id}/insight`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to generate sector insight");
  return res.json();
}

export async function fetchDisclosures(
  params: { stock_id?: number; report_type?: string; q?: string; limit?: number; offset?: number } = {},
): Promise<{ disclosures: DisclosureItem[]; total: number }> {
  const sp = new URLSearchParams();
  if (params.stock_id) sp.set("stock_id", String(params.stock_id));
  if (params.report_type) sp.set("report_type", params.report_type);
  if (params.q) sp.set("q", params.q);
  sp.set("limit", String(params.limit ?? 30));
  sp.set("offset", String(params.offset ?? 0));
  const res = await fetchWithRetry(`${API_BASE}/disclosures?${sp}`);
  if (!res.ok) throw new Error("Failed to fetch disclosures");
  const total = parseInt(res.headers.get("X-Total-Count") || "0", 10);
  const disclosures = await res.json();
  return { disclosures, total };
}

export async function fetchStockDisclosures(
  stockId: number,
  limit = 20,
  offset = 0,
): Promise<{ disclosures: DisclosureItem[]; total: number }> {
  const res = await fetchWithRetry(`${API_BASE}/stocks/${stockId}/disclosures?limit=${limit}&offset=${offset}`);
  if (!res.ok) throw new Error("Failed to fetch stock disclosures");
  const total = parseInt(res.headers.get("X-Total-Count") || "0", 10);
  const disclosures = await res.json();
  return { disclosures, total };
}

export async function refreshDisclosures(): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE}/disclosures/refresh`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to refresh disclosures");
  return res.json();
}

export async function fetchMarketStatus(): Promise<{ market_open: boolean; refresh_interval: number }> {
  const res = await fetch(`${API_BASE}/market-status`);
  if (!res.ok) return { market_open: false, refresh_interval: 300 };
  return res.json();
}

export async function fetchDisclosureSummary(disclosureId: number): Promise<DisclosureDetail> {
  const res = await fetchWithRetry(`${API_BASE}/disclosures/${disclosureId}/summary`, {
    method: "POST",
  });
  if (!res.ok) throw new Error("Failed to fetch disclosure summary");
  return res.json();
}

// ── Macro Alerts ──

export async function fetchAlerts(activeOnly = true): Promise<MacroAlert[]> {
  const res = await fetchWithRetry(`${API_BASE}/alerts?active_only=${activeOnly}`);
  if (!res.ok) return [];
  return res.json();
}

export async function dismissAlert(alertId: number): Promise<void> {
  await fetch(`${API_BASE}/alerts/${alertId}/dismiss`, { method: "POST" });
}

// ── Economic Events ──

export async function fetchEvents(
  params: { days?: number; past_days?: number; category?: string } = {},
): Promise<EconomicEvent[]> {
  const sp = new URLSearchParams();
  if (params.days) sp.set("days", String(params.days));
  if (params.past_days != null) sp.set("past_days", String(params.past_days));
  if (params.category) sp.set("category", params.category);
  const res = await fetchWithRetry(`${API_BASE}/events?${sp}`);
  if (!res.ok) return [];
  return res.json();
}

export async function createEvent(data: {
  title: string;
  event_date: string;
  category?: string;
  importance?: string;
  country?: string;
  description?: string;
}): Promise<EconomicEvent> {
  const res = await fetch(`${API_BASE}/events`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error("Failed to create event");
  return res.json();
}

export async function deleteEvent(eventId: number): Promise<void> {
  await fetch(`${API_BASE}/events/${eventId}`, { method: "DELETE" });
}

export async function seedEvents(): Promise<{ seeded: number }> {
  const res = await fetch(`${API_BASE}/events/seed`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to seed events");
  return res.json();
}

// ── AI Fund Manager (requires admin auth) ──

import { getAdminToken } from "./useAdmin";

function adminHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const token = getAdminToken();
  const headers: Record<string, string> = { ...extra };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  return headers;
}

export async function resetSignals(): Promise<{ deleted: number; message: string }> {
  const res = await fetch(`${API_BASE}/fund/signals/reset`, {
    method: "DELETE",
    headers: adminHeaders(),
  });
  if (!res.ok) throw new Error("Failed to reset signals");
  return res.json();
}

export async function fetchFundSignals(limit = 20): Promise<FundSignal[]> {
  const res = await fetchWithRetry(`${API_BASE}/fund/signals?limit=${limit}`, {
    headers: adminHeaders(),
  });
  if (!res.ok) return [];
  return res.json();
}

export async function fetchStockSignals(stockId: number, limit = 10): Promise<FundSignal[]> {
  const res = await fetchWithRetry(`${API_BASE}/fund/signals/${stockId}?limit=${limit}`, {
    headers: adminHeaders(),
  });
  if (!res.ok) return [];
  return res.json();
}

export async function fetchAccuracyStats(days = 30): Promise<AccuracyStats | null> {
  const res = await fetchWithRetry(`${API_BASE}/fund/accuracy?days=${days}`, {
    headers: adminHeaders(),
  });
  if (!res.ok) return null;
  return res.json();
}

export async function verifySignals(): Promise<{ verified: number; updated: number }> {
  const res = await fetch(`${API_BASE}/fund/verify`, {
    method: "POST",
    headers: adminHeaders(),
  });
  if (!res.ok) throw new Error("Failed to verify signals");
  return res.json();
}

export async function fetchDailyBriefing(date?: string): Promise<DailyBriefing | null> {
  const params = date ? `?target_date=${date}` : '';
  const res = await fetchWithRetry(`${API_BASE}/fund/briefing${params}`, {
    headers: adminHeaders(),
  });
  if (!res.ok) return null;
  const data = await res.json();
  return data || null;
}

export async function generateDailyBriefing(regenerate = false): Promise<DailyBriefing> {
  const url = regenerate
    ? `${API_BASE}/fund/briefing/generate?regenerate=true`
    : `${API_BASE}/fund/briefing/generate`;
  const res = await fetch(url, { method: "POST", headers: adminHeaders() });
  if (!res.ok) throw new Error("Failed to generate briefing");
  return res.json();
}

export async function fetchBriefingHistory(limit = 7): Promise<DailyBriefing[]> {
  const res = await fetchWithRetry(`${API_BASE}/fund/briefings?limit=${limit}`, {
    headers: adminHeaders(),
  });
  if (!res.ok) return [];
  return res.json();
}

export async function analyzePortfolio(stockIds: number[]): Promise<PortfolioReport> {
  const res = await fetch(`${API_BASE}/fund/portfolio/analyze`, {
    method: "POST",
    headers: adminHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ stock_ids: stockIds }),
  });
  if (!res.ok) throw new Error("Failed to analyze portfolio");
  return res.json();
}

export async function fetchLatestPortfolioReport(): Promise<PortfolioReport | null> {
  const res = await fetchWithRetry(`${API_BASE}/fund/portfolio/latest`, {
    headers: adminHeaders(),
  });
  if (!res.ok) return null;
  const data = await res.json();
  return data || null;
}

// ── 종목 관계 (Stock Relations) ──

export async function getStockRelations(stockId: number): Promise<NewsRelation[]> {
  const res = await fetchWithRetry(`${API_BASE}/stocks/relations?stock_id=${stockId}`);
  if (!res.ok) return [];
  return res.json();
}

export async function inferRelations(): Promise<void> {
  const res = await fetch(`${API_BASE}/stocks/infer-relations`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to infer relations");
}

export async function deleteRelation(relationId: number): Promise<void> {
  const res = await fetch(`${API_BASE}/stocks/relations/${relationId}`, { method: "DELETE" });
  if (!res.ok) throw new Error("Failed to delete relation");
}

// ── 원자재 (Commodities) ──

export async function fetchCommodities(): Promise<Commodity[]> {
  const res = await fetchWithRetry(`${API_BASE}/commodities`);
  if (!res.ok) return [];
  const data = await res.json();
  return Array.isArray(data) ? data : data.commodities ?? [];
}

export async function fetchCommodityHistory(
  id: number,
  period = "1mo",
): Promise<{ history: CommodityHistoryPoint[] }> {
  const res = await fetchWithRetry(`${API_BASE}/commodities/${id}/history?period=${period}`);
  if (!res.ok) return { history: [] };
  const data = await res.json();
  if (Array.isArray(data)) return { history: data };
  return { history: data.history ?? [] };
}

export async function fetchSectorCommodities(sectorId: number): Promise<SectorCommodity[]> {
  const res = await fetchWithRetry(`${API_BASE}/sectors/${sectorId}/commodities`);
  if (!res.ok) return [];
  const data = await res.json();
  return Array.isArray(data) ? data : data.commodities ?? [];
}

export async function refreshCommodityPrices(): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE}/commodities/refresh`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to refresh commodity prices");
  return res.json();
}

// ── 원자재 뉴스 (Commodity News) ──

export async function fetchCommodityNews(
  offset = 0,
  limit = 30,
): Promise<{ articles: CommodityNewsArticle[]; total: number }> {
  const res = await fetchWithRetry(`${API_BASE}/commodities/news?limit=${limit}&offset=${offset}`);
  if (!res.ok) return { articles: [], total: 0 };
  const data = await res.json();
  if (Array.isArray(data)) {
    const total = parseInt(res.headers.get("X-Total-Count") || "0", 10);
    return { articles: data, total };
  }
  return { articles: data.articles ?? [], total: data.total ?? 0 };
}

export async function fetchCommodityNewsById(
  commodityId: number,
  offset = 0,
  limit = 30,
): Promise<{ articles: NewsArticle[]; total: number }> {
  const res = await fetchWithRetry(`${API_BASE}/commodities/${commodityId}/news?limit=${limit}&offset=${offset}`);
  if (!res.ok) return { articles: [], total: 0 };
  const data = await res.json();
  if (Array.isArray(data)) {
    const total = parseInt(res.headers.get("X-Total-Count") || "0", 10);
    return { articles: data, total };
  }
  return { articles: data.articles ?? [], total: data.total ?? 0 };
}

// ── 페이퍼 트레이딩 ──

export async function fetchPaperTradingStats(): Promise<PaperTradingStats | null> {
  const res = await fetchWithRetry(`${API_BASE}/paper-trading/stats`);
  if (!res.ok) return null;
  return res.json();
}

export async function fetchPaperPositions(): Promise<PaperPosition[]> {
  const res = await fetchWithRetry(`${API_BASE}/paper-trading/positions`);
  if (!res.ok) return [];
  return res.json();
}

export async function fetchPaperTrades(limit = 50): Promise<PaperTrade[]> {
  const res = await fetchWithRetry(`${API_BASE}/paper-trading/trades?limit=${limit}`);
  if (!res.ok) return [];
  return res.json();
}

export async function fetchPaperSnapshots(days = 30): Promise<PaperSnapshot[]> {
  const res = await fetchWithRetry(`${API_BASE}/paper-trading/snapshots?days=${days}`);
  if (!res.ok) return [];
  return res.json();
}

export async function resetPaperTrading(): Promise<boolean> {
  const res = await fetch(`${API_BASE}/paper-trading/reset`, { method: 'POST' });
  return res.ok;
}

// ── AI 채팅 ──

export async function sendChatMessage(
  message: string,
  sessionId?: string,
  stockCode?: string,
): Promise<ChatResponse> {
  const res = await fetchWithRetry(`${API_BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id: sessionId, stock_code: stockCode }),
  });
  if (!res.ok) throw new Error('Failed to send chat message');
  return res.json();
}

// ── 백테스트 ──

export async function fetchBacktest(params: {
  days?: number;
  stock_id?: number;
  signal_type?: string;
  min_confidence?: number;
}): Promise<BacktestResult> {
  const sp = new URLSearchParams();
  if (params.days) sp.set('days', String(params.days));
  if (params.stock_id) sp.set('stock_id', String(params.stock_id));
  if (params.signal_type) sp.set('signal_type', params.signal_type);
  if (params.min_confidence != null) sp.set('min_confidence', String(params.min_confidence));
  const res = await fetchWithRetry(`${API_BASE}/fund/backtest?${sp}`, {
    headers: adminHeaders(),
  });
  if (!res.ok) throw new Error('Failed to fetch backtest');
  return res.json();
}

// ── 뉴스-주가 상관관계 ──

export async function fetchNewsPriceCorrelation(
  stockId: number,
  days = 90,
): Promise<NewsPriceCorrelation> {
  const res = await fetchWithRetry(`${API_BASE}/stocks/${stockId}/news-price-correlation?days=${days}`);
  if (!res.ok) throw new Error('Failed to fetch news-price correlation');
  return res.json();
}

export async function fetchSectorCommodityNews(
  sectorId: number,
  offset = 0,
  limit = 30,
): Promise<{ articles: NewsArticle[]; total: number }> {
  const res = await fetchWithRetry(`${API_BASE}/sectors/${sectorId}/commodity-news?limit=${limit}&offset=${offset}`);
  if (!res.ok) return { articles: [], total: 0 };
  const data = await res.json();
  if (Array.isArray(data)) {
    const total = parseInt(res.headers.get("X-Total-Count") || "0", 10);
    return { articles: data, total };
  }
  return { articles: data.articles ?? [], total: data.total ?? 0 };
}
