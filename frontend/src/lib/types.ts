export interface Sector {
  id: number;
  name: string;
  is_custom: boolean;
  created_at: string;
  stock_count?: number;
  stocks?: Stock[];
}

export interface Stock {
  id: number;
  sector_id: number;
  name: string;
  stock_code: string;
  keywords: string[] | null;
  created_at: string;
}

export interface NewsRelation {
  stock_id: number | null;
  stock_name: string | null;
  sector_id: number | null;
  sector_name: string | null;
  match_type: string;
  relevance: string;
}

export interface NewsArticle {
  id: number;
  title: string;
  summary: string | null;
  url: string;
  source: string;
  published_at: string | null;
  collected_at: string;
  relations: NewsRelation[];
}
