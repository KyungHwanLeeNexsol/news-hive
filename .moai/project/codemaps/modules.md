# NewsHive 모듈 목록

> 마지막 업데이트: 2026-03-26

## 백엔드 모듈 (Python / FastAPI)

### 진입점

| 파일 | 책임 | 주요 공개 인터페이스 |
|------|------|---------------------|
| `app/main.py` | FastAPI 앱 생성, 라이프사이클(lifespan) 관리, 미들웨어·라우터 등록 | `app` (FastAPI 인스턴스), `/api/health`, `/api/deploy`, `/api/market-status` |
| `app/config.py` | pydantic-settings 기반 환경변수 로드 | `settings` (전역 설정 싱글톤) |
| `app/database.py` | SQLAlchemy 엔진·세션 팩토리 | `engine`, `SessionLocal`, `get_db()` |

---

### 라우터 (app/routers/)

| 모듈 | 프리픽스 | 책임 |
|------|---------|------|
| `sectors.py` | `/api/sectors` | 섹터 CRUD, 섹터 뉴스 조회, 섹터 퍼포먼스 |
| `stocks.py` | `/api/stocks` | 종목 CRUD, 종목 뉴스·주가·재무 데이터 |
| `news.py` | `/api/news` | 전체 뉴스 조회, 수동 새로고침 트리거 |
| `disclosures.py` | `/api/disclosures` | DART 공시 목록·상세 조회 |
| `alerts.py` | `/api/alerts` | 거시경제 리스크 알림 조회 |
| `events.py` | `/api/events` | 경제 캘린더 이벤트 조회 |
| `fund_manager.py` | `/api/fund` | AI 투자 시그널, 데일리 브리핑, 포트폴리오 (관리자 인증 필요) |
| `auth.py` | `/api/auth` | 관리자 로그인·토큰 검증 |
| `utils.py` | - | 뉴스 응답 포매팅 공통 유틸 (`format_articles`) |

---

### 서비스 (app/services/)

#### 핵심 비즈니스 로직

| 모듈 | 책임 | 주요 공개 함수 |
|------|------|---------------|
| `news_crawler.py` | 4개 뉴스 소스 병렬 크롤링 오케스트레이터, 퍼지 중복 제거 | `crawl_all_news(db)` |
| `ai_classifier.py` | 키워드·AI 하이브리드 분류, 감성 분석, 번역 | `classify_news()`, `classify_news_with_ai()`, `classify_sentiment()`, `translate_articles_batch()` |
| `ai_client.py` | Groq→Gemini→OpenRouter 폴백 체인 | `ask_ai(prompt)` |
| `fund_manager.py` | 투자 시그널 생성, 데일리 브리핑 AI 작성 (52KB) | `generate_fund_signals(db)`, `generate_daily_briefing(db)` |
| `scheduler.py` | APScheduler 7개 백그라운드 작업 등록·관리 | `start_scheduler()`, `stop_scheduler()` |

#### 데이터 수집

| 모듈 | 책임 | 주요 공개 함수 |
|------|------|---------------|
| `dart_crawler.py` | DART 전자공시 API 수집·파싱·AI 요약 | `fetch_dart_disclosures(db)` |
| `naver_finance.py` | 네이버 금융 실시간 주가·섹터 퍼포먼스 | `fetch_naver_stock_list()`, `fetch_sector_performances()` |
| `technical_indicators.py` | RSI, MACD, 볼린저 밴드 계산 | `calculate_rsi()`, `calculate_macd()`, `calculate_bollinger_bands()` |
| `macro_risk.py` | 거시경제 리스크 감지·알림 생성 | `detect_macro_risks(db)`, `deactivate_old_alerts(db)` |
| `signal_verifier.py` | 과거 투자 시그널 적중 여부 검증 | `verify_signals(db)` |
| `financial_scraper.py` | 종목 재무 데이터 스크래핑 | - |
| `article_scraper.py` | 뉴스 기사 본문 스크래핑 | - |
| `kis_api.py` | 한국투자증권 API 연동 | - |

#### 크롤러 (app/services/crawlers/)

| 모듈 | 데이터 소스 | 방식 |
|------|-----------|------|
| `naver.py` | 네이버 뉴스 검색 API | REST API (JSON) |
| `google.py` | Google News RSS | RSS/XML 파싱 |
| `yahoo.py` | Yahoo Finance | REST API (JSON) |
| `korean_rss.py` | 한국 언론사 RSS 피드 | RSS/XML 파싱 |
| `content_scraper.py` | 기사 원문 URL | HTML 스크래핑 (BeautifulSoup) |
| `us_news.py` | 미국 금융 뉴스 | REST API |

---

### 모델 (app/models/)

| 모델 | 테이블 | 핵심 필드 |
|------|--------|----------|
| `Sector` | `sectors` | id, name, is_custom |
| `Stock` | `stocks` | id, sector_id, name, stock_code, keywords[], market_cap |
| `NewsArticle` | `news_articles` | id, title, summary, url(UNIQUE), source, sentiment, published_at |
| `NewsStockRelation` | `news_stock_relations` | news_id, stock_id, sector_id, match_type, relevance |
| `Disclosure` | `disclosures` | rcept_no, corp_name, report_nm, rcept_dt, stock_id |
| `MacroAlert` | `macro_alerts` | title, content, risk_level, is_active |
| `EconomicEvent` | `economic_events` | title, event_date, country, importance |
| `FundSignal` | `fund_signals` | stock_id, signal(BUY/SELL/HOLD), confidence, target_price |
| `DailyBriefing` | `daily_briefings` | briefing_date, content, ai_provider |
| `SectorInsight` | `sector_insights` | sector_id, insight_text, generated_at |
| `PortfolioReport` | `portfolio_reports` | report_date, content |

---

### 스키마 (app/schemas/)

| 모듈 | Pydantic 모델 |
|------|--------------|
| `sector.py` | SectorCreate, SectorResponse, SectorDetailResponse |
| `stock.py` | StockCreate, StockResponse, StockDetailResponse |
| `news.py` | NewsArticleResponse |
| `disclosure.py` | DisclosureItem, DisclosureDetail |
| `fund_manager.py` | FundSignalResponse, DailyBriefingResponse, PortfolioReportResponse, AccuracyStatsResponse |

---

## 프론트엔드 모듈 (Next.js / TypeScript)

### 페이지 (app/)

| 경로 | 파일 | 역할 |
|------|------|------|
| `/` | `page.tsx` | 대시보드 — 섹터 카드 목록 |
| `/sectors/[id]` | `sectors/[id]/page.tsx` | 섹터 상세 — 종목 목록 + 섹터 뉴스 피드 |
| `/stocks` | `stocks/page.tsx` | 종목 목록 |
| `/stocks/[id]` | (추정) | 종목 상세 — 주가·재무·뉴스 |
| `/news` | `news/page.tsx` | 전체 뉴스 피드 |
| `/news/[id]` | (추정) | 뉴스 상세 |
| `/disclosures` | `disclosures/page.tsx` | DART 공시 목록 |
| `/fund` | `fund/page.tsx` | AI 펀드매니저 대시보드 |
| `/calendar` | `calendar/page.tsx` | 경제 캘린더 |
| `/watchlist` | `watchlist/page.tsx` | 관심 종목 |
| `/manage` | `manage/page.tsx` | 관리 — 섹터/종목 CRUD |

### 공통 컴포넌트 (components/)

| 컴포넌트 | 역할 |
|---------|------|
| `Header.tsx` | 상단 네비게이션 바 |
| `SectorCard.tsx` | 섹터 카드 UI |
| `NewsCard.tsx` | 뉴스 아이템 카드 |
| `DisclosureModal.tsx` | 공시 상세 모달 |
| `MacroAlertBanner.tsx` | 거시경제 리스크 배너 |
| `ChangeRate.tsx` | 주가 등락률 표시 |
| `UpDownBar.tsx` | 상승/하락 시각화 바 |
| `LoadingBar.tsx` | 로딩 상태 표시 |
| `Pagination.tsx` | 페이지네이션 |

### 유틸리티 (lib/)

| 파일 | 역할 |
|------|------|
| `api.ts` | 모든 Backend API 호출 함수 (fetchWithRetry 포함) |
| `types.ts` | TypeScript 타입 정의 (Sector, Stock, NewsArticle 등) |
