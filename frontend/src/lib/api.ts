import type { Sector, Stock, NewsArticle } from "./types";

const API_BASE = "/api";

export async function fetchSectors(): Promise<Sector[]> {
  const res = await fetch(`${API_BASE}/sectors`);
  if (!res.ok) throw new Error("Failed to fetch sectors");
  return res.json();
}

export async function fetchSector(id: number): Promise<Sector> {
  const res = await fetch(`${API_BASE}/sectors/${id}`);
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
  const res = await fetch(`${API_BASE}/sectors/${id}/news?limit=${limit}&offset=${offset}`);
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
  const res = await fetch(`${API_BASE}/stocks/${id}/news?limit=${limit}&offset=${offset}`);
  if (!res.ok) throw new Error("Failed to fetch stock news");
  const total = parseInt(res.headers.get("X-Total-Count") || "0", 10);
  const articles = await res.json();
  return { articles, total };
}

export async function fetchNewsById(id: number): Promise<NewsArticle> {
  const res = await fetch(`${API_BASE}/news/${id}`);
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
  const res = await fetch(`${API_BASE}/news?limit=${limit}&offset=${offset}`);
  if (!res.ok) throw new Error("Failed to fetch news");
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
