import type { Sector, Stock, StockListItem, NewsArticle, StockDetail, FinancialPeriod, PriceRecord, SentimentTrendItem, SectorInsight, DisclosureItem, DisclosureDetail } from "./types";

const API_BASE = "/api";

/**
 * Fetch with automatic retry — handles Render free-tier cold starts
 * where the first request may time out (502/504) while the backend wakes up.
 */
async function fetchWithRetry(
  input: RequestInfo | URL,
  init?: RequestInit,
  retries = 1,
): Promise<Response> {
  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      const res = await fetch(input, init);
      if (res.ok || res.status < 500 || attempt === retries) return res;
      // 5xx — backend might be waking up, wait and retry
      await new Promise((r) => setTimeout(r, 3000));
    } catch (e) {
      if (attempt === retries) throw e;
      await new Promise((r) => setTimeout(r, 3000));
    }
  }
  // Unreachable, but TypeScript needs it
  return fetch(input, init);
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

export async function generateSectorInsight(id: number): Promise<SectorInsight> {
  const res = await fetch(`${API_BASE}/sectors/${id}/insight`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to generate sector insight");
  return res.json();
}

export async function fetchDisclosures(
  params: { stock_id?: number; report_type?: string; limit?: number; offset?: number } = {},
): Promise<{ disclosures: DisclosureItem[]; total: number }> {
  const sp = new URLSearchParams();
  if (params.stock_id) sp.set("stock_id", String(params.stock_id));
  if (params.report_type) sp.set("report_type", params.report_type);
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

export async function fetchDisclosureSummary(disclosureId: number): Promise<DisclosureDetail> {
  const res = await fetchWithRetry(`${API_BASE}/disclosures/${disclosureId}/summary`, {
    method: "POST",
  });
  if (!res.ok) throw new Error("Failed to fetch disclosure summary");
  return res.json();
}
