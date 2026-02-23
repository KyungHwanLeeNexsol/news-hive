const API_BASE = "/api";

export async function fetchSectors() {
  const res = await fetch(`${API_BASE}/sectors`);
  return res.json();
}

export async function fetchSector(id: number) {
  const res = await fetch(`${API_BASE}/sectors/${id}`);
  return res.json();
}

export async function fetchSectorNews(id: number) {
  const res = await fetch(`${API_BASE}/sectors/${id}/news`);
  return res.json();
}

export async function fetchStockNews(id: number) {
  const res = await fetch(`${API_BASE}/stocks/${id}/news`);
  return res.json();
}

export async function refreshNews() {
  const res = await fetch(`${API_BASE}/news/refresh`, { method: "POST" });
  return res.json();
}
