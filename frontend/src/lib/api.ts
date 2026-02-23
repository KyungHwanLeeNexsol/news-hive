import type { Sector, Stock, NewsArticle } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL
  ? `${process.env.NEXT_PUBLIC_API_URL}/api`
  : "/api";

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

export async function fetchSectorNews(id: number): Promise<NewsArticle[]> {
  const res = await fetch(`${API_BASE}/sectors/${id}/news`);
  if (!res.ok) throw new Error("Failed to fetch sector news");
  return res.json();
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

export async function fetchStockNews(id: number): Promise<NewsArticle[]> {
  const res = await fetch(`${API_BASE}/stocks/${id}/news`);
  if (!res.ok) throw new Error("Failed to fetch stock news");
  return res.json();
}

export async function fetchNews(): Promise<NewsArticle[]> {
  const res = await fetch(`${API_BASE}/news`);
  if (!res.ok) throw new Error("Failed to fetch news");
  return res.json();
}

export async function refreshNews(): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE}/news/refresh`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to refresh news");
  return res.json();
}
