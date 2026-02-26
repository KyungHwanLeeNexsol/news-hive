export interface Sector {
  id: number;
  name: string;
  is_custom: boolean;
  created_at: string;
  stock_count?: number;
  stocks?: Stock[];
  naver_code?: string | null;
  change_rate?: number | null;
  total_stocks?: number | null;
  rising_stocks?: number | null;
  flat_stocks?: number | null;
  falling_stocks?: number | null;
}

export interface Stock {
  id: number;
  sector_id: number;
  name: string;
  stock_code: string;
  keywords: string[] | null;
  created_at: string;
  current_price?: number | null;
  price_change?: number | null;
  change_rate?: number | null;
  bid_price?: number | null;
  ask_price?: number | null;
  volume?: number | null;
  trading_value?: number | null;
  prev_volume?: number | null;
  news_count?: number;
}

export interface StockDetail {
  id: number;
  name: string;
  stock_code: string;
  sector_id: number;
  sector_name: string | null;
  // Realtime
  current_price: number | null;
  price_change: number | null;
  change_rate: number | null;
  eps: number | null;
  bps: number | null;
  dividend: number | null;
  high_52w: number | null;
  low_52w: number | null;
  volume: number | null;
  trading_value: number | null;
  // Valuation
  per: number | null;
  pbr: number | null;
  market_cap: number | null;       // 억원
  dividend_yield: number | null;   // %
  foreign_ratio: number | null;    // %
  industry_per: number | null;
}

export interface FinancialPeriod {
  period: string;
  period_type: "annual" | "quarter";
  revenue: number | null;           // 억원
  operating_profit: number | null;
  operating_margin: number | null;
  net_income: number | null;
  eps: number | null;
  bps: number | null;
  roe: number | null;
  dividend_payout: number | null;
}

export interface PriceRecord {
  date: string;
  close: number;
  open: number;
  high: number;
  low: number;
  volume: number;
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
  ai_summary: string | null;
  content: string | null;
  url: string;
  source: string;
  sentiment: string | null;
  published_at: string | null;
  collected_at: string;
  relations: NewsRelation[];
}
