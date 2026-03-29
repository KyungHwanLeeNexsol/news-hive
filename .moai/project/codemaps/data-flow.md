# NewsHive 데이터 흐름

> 마지막 업데이트: 2026-03-26

## 1. 뉴스 집계 파이프라인

가장 핵심적인 데이터 흐름으로, 10분마다 (또는 수동 트리거로) 실행된다.

```
APScheduler (interval: 10분)
    │
    ▼
_run_crawl_job()  [별도 스레드 + asyncio.run()]
    │
    ├── 1. _cleanup_old_articles(db)
    │       └── 7일 이상 된 news_articles + news_stock_relations 삭제
    │
    ├── 2. asyncio.run(crawl_all_news(db))
    │       │
    │       ├── DB에서 활성 섹터·종목 로드
    │       ├── KeywordIndex 구축 (종목명·키워드 → 종목ID 매핑)
    │       │
    │       ├── 병렬 크롤링 (asyncio.gather)
    │       │   ├── naver.search_naver_news()     → 네이버 검색 API
    │       │   ├── google.search_google_news()   → Google News RSS
    │       │   ├── yahoo.search_yahoo_finance_top() + search_yahoo_stock_news()
    │       │   └── korean_rss.fetch_korean_rss_feeds()  → 한국 언론사 RSS
    │       │
    │       ├── 1차 URL 기반 중복 제거
    │       │   └── 이미 DB에 있는 URL 필터링
    │       │
    │       ├── 퍼지 중복 제거 (Fuzzy Deduplication)
    │       │   ├── _normalize_title(): 소스 접미사 제거, 소문자 변환
    │       │   ├── _title_bigrams(): 문자 bigram 집합 추출
    │       │   └── Jaccard 유사도 ≥ 0.6이면 동일 기사로 판단 후 스킵
    │       │
    │       ├── content_scraper.scrape_articles_batch()
    │       │   └── 기사 원문 URL에서 본문 스크래핑 (BeautifulSoup)
    │       │
    │       ├── ai_classifier.translate_articles_batch()
    │       │   └── 영문 기사 → 한국어 번역 (ask_ai() 호출)
    │       │
    │       ├── ai_classifier.is_non_financial_article()
    │       │   └── 금융 무관 기사 필터링 (ask_ai() 호출)
    │       │
    │       ├── ai_classifier.classify_news()
    │       │   └── 키워드 인덱스로 1차 종목·섹터 매핑
    │       │
    │       ├── ai_classifier.classify_news_with_ai()
    │       │   └── AI로 정밀 분류 + 요약 생성 (ask_ai() 호출)
    │       │
    │       ├── ai_classifier.classify_sentiment()
    │       │   └── 제목 기반 긍정/부정/중립 감성 분류
    │       │
    │       └── DB 저장
    │           ├── news_articles (INSERT, URL UNIQUE 충돌 시 스킵)
    │           └── news_stock_relations (INSERT, match_type + relevance 포함)
    │
    ├── 3. macro_risk.detect_macro_risks(db)
    │       └── 뉴스 패턴 기반 거시경제 리스크 감지 → macro_alerts 생성
    │
    ├── 4. macro_risk.deactivate_old_alerts(db)
    │       └── 오래된 알림 비활성화
    │
    └── 5. 감성 백필 (sentiment NULL인 기사 일괄 처리)
            └── ai_classifier.classify_sentiment() → DB 업데이트
```

---

## 2. 투자 시그널 생성 파이프라인

매일 08:30 KST 또는 `/api/fund/signals` POST 요청으로 실행된다.

```
APScheduler cron (08:30 KST) 또는 수동 API 호출
    │
    ▼
fund_manager.generate_fund_signals(db)
    │
    ├── 1. DB에서 추적 중인 종목 목록 로드
    │
    ├── 2. 각 종목별 (병렬/순차):
    │   │
    │   ├── naver_finance.fetch_naver_stock_list()
    │   │   └── 실시간 주가·거래량·시가총액 수집
    │   │
    │   ├── technical_indicators.calculate_rsi(prices)
    │   │   └── RSI(14) 계산
    │   │
    │   ├── technical_indicators.calculate_macd(prices)
    │   │   └── MACD(12,26,9) 계산
    │   │
    │   ├── technical_indicators.calculate_bollinger_bands(prices)
    │   │   └── 볼린저 밴드(20,2) 계산
    │   │
    │   └── 최근 뉴스·공시 로드 (DB 쿼리)
    │
    ├── 3. ask_ai() — 종합 AI 분석
    │   └── 프롬프트: 주가·기술지표·뉴스·공시 → BUY/SELL/HOLD + 신뢰도 + 목표가 + 근거
    │
    ├── 4. fund_signals 테이블 저장
    │   └── signal, confidence, target_price, reason, ai_provider
    │
    └── 5. 기존 오늘 시그널 초기화 후 신규 저장 (멱등성 보장)
```

---

## 3. DART 공시 수집 파이프라인

30분마다 실행된다.

```
APScheduler (interval: 30분) — 시작 시 즉시 1회 실행
    │
    ▼
_run_dart_crawl()
    │
    ├── 1. _cleanup_old_disclosures(db)
    │       └── 7일 이상 된 공시 삭제 (rcept_dt 기준)
    │
    ├── 2. asyncio.run(dart_crawler.fetch_dart_disclosures(db))
    │       │
    │       ├── DART OpenAPI 호출
    │       │   └── 최신 공시 목록 수집 (최근 N건)
    │       │
    │       ├── URL 기반 중복 제거 (rcept_no UNIQUE)
    │       │
    │       ├── ask_ai() — 공시 AI 요약
    │       │   └── 공시 제목·내용 → 투자자 관점 핵심 요약
    │       │
    │       └── disclosures 테이블 저장
    │           └── corp_name, report_nm, rcept_dt, url, ai_summary
    │
    ├── 3. dart_crawler.backfill_disclosure_stock_ids(db)
    │       └── 기업명으로 stock_id 역매핑 (미매핑 공시 보완)
    │
    └── 4. dart_crawler.backfill_disclosure_report_types(db)
            └── 공시 유형 분류 (사업보고서/분기보고서 등)
```

---

## 4. 실시간 주가 데이터 흐름

프론트엔드에서 종목 상세 페이지 접근 시 발생하는 흐름이다.

```
브라우저 → GET /api/stocks/{id}/price
    │
    ▼
stocks.router → get_stock_price()
    │
    ├── naver_finance 모듈 호출
    │   ├── 네이버 모바일 API 시도 (1순위)
    │   └── 네이버 PC API 폴백 (2순위)
    │
    ├── 주가 이력 계산 (종가·시가·고가·저가·거래량)
    │
    └── PriceRecord[] 응답 반환
```

**시가총액 갱신 (6시간마다):**

```
APScheduler (interval: 6시간)
    │
    ▼
_update_market_caps()
    │
    ├── KOSPI 10페이지 × 50종목 = 500종목
    ├── KOSDAQ 10페이지 × 50종목 = 500종목
    │   └── naver_finance.fetch_naver_stock_list() 반복 호출
    │
    └── stocks 테이블 market_cap 배치 업데이트
```

---

## 5. 프론트엔드 ↔ 백엔드 요청 라이프사이클

```
사용자 브라우저
    │
    │  HTTP 요청 (예: GET /api/sectors)
    ▼
Next.js (Vercel)
    │
    ├── next.config.ts의 rewrites 규칙
    │   `/api/*` → `http://140.245.76.242:8000/api/*`
    │
    ▼
lib/api.ts의 fetchWithRetry()
    │
    ├── cache: "no-store" (실시간 데이터 캐시 방지)
    ├── 최대 1회 재시도 (5xx 응답 시 3초 대기 후 재시도)
    └── 성공 → Response.json() → TypeScript 타입으로 반환
    │
    ▼
FastAPI (Oracle Cloud VM)
    │
    ├── CORS 미들웨어 검증 (FRONTEND_URL 화이트리스트)
    ├── 라우터 디스패치
    ├── get_db() 의존성 → SQLAlchemy 세션 생성
    ├── ORM 쿼리 → PostgreSQL
    ├── Pydantic 스키마로 응답 직렬화
    └── JSON 응답 반환
    │
    ▼
브라우저 렌더링
    │
    └── React Server Component (RSC) 또는 Client Component에서 데이터 표시
```

**관리자 전용 API (`/api/fund/*`) 흐름:**

```
사용자 로그인 → POST /api/auth/login
    │
    ▼
auth.router → 비밀번호 검증 → JWT 토큰 발급
    │
    ▼ (이후 요청)
fund_manager.router → _require_admin() 의존성
    │
    ├── Authorization: Bearer {token} 헤더 검증
    ├── _verify_admin_token(token) → 유효성·만료 확인
    └── 통과 시 핸들러 실행 / 실패 시 401 반환
```

---

## 6. 데일리 브리핑 생성 흐름

```
APScheduler cron (08:30 KST 매일)
    │
    ▼
fund_manager.generate_daily_briefing(db)
    │
    ├── 1. 오늘의 fund_signals 조회 (전체 시그널 요약)
    ├── 2. 최근 뉴스 상위 N건 조회
    ├── 3. 활성 macro_alerts 조회
    ├── 4. 최근 disclosures 조회
    │
    ├── 5. ask_ai() 호출
    │   └── 프롬프트: 시그널 요약 + 뉴스 헤드라인 + 공시 + 거시경제 알림
    │       → 투자자 관점 데일리 마켓 브리핑 (한국어, 마크다운 형식)
    │
    └── 6. daily_briefings 테이블 저장
            └── briefing_date (오늘 날짜), content, ai_provider
```

---

## 7. 시그널 검증 흐름

매일 18:00 KST (한국 주식 시장 마감 후) 실행된다.

```
APScheduler cron (18:00 KST 매일)
    │
    ▼
signal_verifier.verify_signals(db)
    │
    ├── 검증 대상: 생성 후 1~30일 경과한 미검증 fund_signals
    │
    ├── 각 시그널별:
    │   ├── 시그널 생성 당시 가격과 현재 가격 비교
    │   ├── BUY 시그널: 현재가 > 목표가이면 적중 (hit)
    │   ├── SELL 시그널: 현재가 < 목표가이면 적중 (hit)
    │   └── 결과를 fund_signals.verified_result에 업데이트
    │
    └── 검증 통계 반환 (verified 수, updated 수)
```
