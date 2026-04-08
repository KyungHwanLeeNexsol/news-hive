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

export interface StockListItem {
  id: number;
  name: string;
  stock_code: string;
  sector_id: number;
  sector_name: string | null;
  market: string | null;
  current_price: number | null;
  price_change: number | null;
  change_rate: number | null;
  bid_price: number | null;
  ask_price: number | null;
  volume: number | null;
  trading_value: number | null;
  market_cap: number | null;       // 시가총액 (억원)
  prev_volume: number | null;
  news_count: number;
}

export interface Stock {
  id: number;
  sector_id: number;
  name: string;
  stock_code: string;
  market: string | null;
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
  is_estimate?: boolean;
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

export interface SentimentTrendItem {
  date: string;
  positive: number;
  negative: number;
  neutral: number;
}

export interface SectorInsight {
  content: string;
  created_at?: string;
  cached: boolean;
}

export interface DisclosureItem {
  id: number;
  corp_code: string;
  corp_name: string;
  stock_code: string | null;
  stock_id: number | null;
  stock_name?: string | null;
  report_name: string;
  report_type: string | null;
  rcept_no: string;
  rcept_dt: string;
  url: string;
  created_at: string;
}

export interface DisclosureDetail {
  id: number;
  corp_name: string;
  report_name: string;
  report_type: string | null;
  rcept_no: string;
  rcept_dt: string;
  url: string;
  ai_summary: string | null;
}

export interface MacroAlert {
  id: number;
  level: 'warning' | 'critical';
  keyword: string;
  title: string;
  description: string | null;
  article_count: number;
  is_active: boolean;
  created_at: string;
}

export interface EconomicEvent {
  id: number;
  title: string;
  description: string | null;
  event_date: string;
  category: string;
  importance: string;
  country: string;
}

export interface NewsRelation {
  stock_id: number | null;
  stock_name: string | null;
  sector_id: number | null;
  sector_name: string | null;
  match_type: string;
  relevance: string;
  relation_sentiment?: string | null;
  propagation_type?: string | null;
  impact_reason?: string | null;
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

// ── AI Fund Manager ──

export interface FundSignal {
  id: number;
  stock_id: number;
  stock_name: string | null;
  stock_code: string | null;
  sector_name: string | null;
  signal: 'buy' | 'sell' | 'hold';
  confidence: number;
  target_price: number | null;
  stop_loss: number | null;
  reasoning: string;
  news_summary: string | null;
  financial_summary: string | null;
  market_summary: string | null;
  created_at: string;
  price_at_signal: number | null;
  price_after_1d: number | null;
  price_after_3d: number | null;
  price_after_5d: number | null;
  is_correct: boolean | null;
  return_pct: number | null;
  verified_at: string | null;
  ai_model: string | null;
}

export interface ConfidenceBucket {
  total: number;
  accuracy: number;
}

export interface AccuracyStats {
  total: number;
  correct: number;
  accuracy: number;
  avg_return: number;
  buy_accuracy: number;
  sell_accuracy: number;
  by_confidence: Record<string, ConfidenceBucket>;
}

export interface DailyBriefing {
  id: number;
  briefing_date: string;
  market_overview: string;
  sector_highlights: string | null;
  stock_picks: string | null;
  risk_assessment: string | null;
  strategy: string | null;
  created_at: string;
  ai_model: string | null;
}

export interface StockNewsImpactStats {
  stock_id: number;
  status: "sufficient" | "insufficient";
  count: number;
  avg_1d: number | null;
  avg_5d: number | null;
  win_rate_1d: number | null;
  win_rate_5d: number | null;
  max_return_5d: number | null;
  min_return_5d: number | null;
}

export interface PortfolioReport {
  id: number;
  stock_ids: string;
  overall_assessment: string;
  risk_analysis: string | null;
  sector_balance: string | null;
  rebalancing: string | null;
  created_at: string;
}

// ── 원자재 (Commodity) ──

export interface CommodityPrice {
  price: number;
  change_pct: number | null;
  open_price: number | null;
  high_price: number | null;
  low_price: number | null;
  volume: number | null;
  recorded_at: string;
}

export interface Commodity {
  id: number;
  symbol: string;
  name_ko: string;
  name_en: string;
  category: string;
  unit: string;
  currency: string;
  latest_price: number | CommodityPrice | null;
  change_pct?: number | null;
}

export interface CommodityHistoryPoint {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface SectorCommodity {
  commodity: Commodity;
  correlation_type: string;
  description: string | null;
}

// ── 원자재 뉴스 (Commodity News) ──

export interface CommodityNewsRelation {
  commodity_id: number;
  name_ko: string;
  symbol: string;
  relevance: string;
  impact_direction: string | null;
}

// 원자재 뉴스 = 기존 NewsArticle + commodity_relations 필드
export interface CommodityNewsArticle extends NewsArticle {
  commodity_relations: CommodityNewsRelation[];
}

// 페이퍼 트레이딩
export interface PaperTradingStats {
  initial_capital: number;
  current_cash: number;
  total_trades: number;
  closed_trades: number;
  open_positions: number;
  win_rate: number;
  avg_return: number;
  total_pnl: number;
  cumulative_return: number;
  sharpe_ratio: number;
  mdd: number;
  sharpe_warning: boolean;
}

export interface PaperPosition {
  stock_name: string;
  entry_price: number;
  quantity: number;
  target_price: number;
  stop_loss: number;
  entry_date: string;
  invest_amount: number;
}

export interface PaperTrade {
  stock_name: string;
  entry_price: number;
  exit_price: number;
  pnl: number;
  return_pct: number;
  exit_reason: string;
  entry_date: string;
  exit_date: string;
}

export interface PaperSnapshot {
  date: string;
  total_value: number;
  cumulative_return_pct: number;
  daily_return_pct: number;
}

// ── AI 채팅 ──

export interface ChatResponse {
  reply: string;
  context_used: string[];
  session_id: string;
  ai_model: string | null;
}

// ── 백테스트 ──

export interface BacktestSummary {
  total_signals: number;
  win_rate: number;
  avg_return: number;
  max_drawdown: number;
  sharpe_ratio: number;
  kospi_return: number;
}

export interface BacktestTimeline {
  date: string;
  cumulative_return: number;
  signal_count: number;
}

export interface BacktestByStock {
  stock_name: string;
  signals: number;
  win_rate: number;
  avg_return: number;
}

export interface BacktestResult {
  summary: BacktestSummary;
  timeline: BacktestTimeline[];
  by_stock: BacktestByStock[];
}

// ── 사용자 인증 ──

export interface User {
  id: number;
  email: string;
  name: string;
  email_verified: boolean;
  created_at: string;
}

export interface AuthTokens {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user: User;
}

// ── 뉴스-주가 상관관계 ──

export interface CorrelationTimeline {
  date: string;
  sentiment_score: number;
  price_change_pct: number;
  correlation_7d: number | null;
}

export interface NewsPriceCorrelation {
  correlation_7d: number;
  timeline: CorrelationTimeline[];
}

// ── 모의투자 포트폴리오 ──

export interface VIPPortfolioStats {
  portfolio_id: number;
  name: string;
  initial_capital: number;
  current_cash: number;
  positions_value: number;
  total_value: number;
  total_return_pct: number;
  realized_pnl: number;
  open_positions: number;
  closed_trades: number;
}

export interface VIPPosition {
  id: number;
  stock_code: string | null;
  stock_name: string;
  split_sequence: number;
  entry_price: number;
  quantity: number;
  invest_amount: number;
  entry_date: string | null;
  partial_sold: boolean;
  disclosure_type: string | null;
  stake_pct: number | null;
}

export interface VIPTradeHistory {
  id: number;
  stock_code: string | null;
  stock_name: string;
  split_sequence: number;
  entry_price: number;
  quantity: number;
  entry_date: string | null;
  exit_price: number | null;
  exit_date: string | null;
  exit_reason: string | null;
  pnl: number | null;
  return_pct: number | null;
  partial_sold: boolean;
  is_open: boolean;
}

export interface KS200PortfolioStats {
  portfolio_id: number;
  name: string;
  initial_capital: number;
  current_cash: number;
  position_value: number;
  total_value: number;
  total_pnl: number;
  total_return_pct: number;
  realized_pnl: number;
  open_positions: number;
  max_positions: number;
}

export interface KS200Position {
  id: number;
  stock_code: string;
  entry_price: number;
  quantity: number;
  entry_date: string | null;
  current_value: number;
}

export interface KS200TradeHistory {
  id: number;
  stock_code: string;
  entry_price: number;
  quantity: number;
  entry_date: string | null;
  exit_price: number | null;
  exit_date: string | null;
  exit_reason: string | null;
  pnl: number | null;
  return_pct: number | null;
  is_open: boolean;
}
