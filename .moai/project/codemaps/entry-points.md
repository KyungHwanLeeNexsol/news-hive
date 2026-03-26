# NewsHive 진입점 목록

> 마지막 업데이트: 2026-03-26

## 애플리케이션 진입점

| 진입점 | 파일 | 설명 |
|--------|------|------|
| Backend 서버 | `backend/app/main.py` | `uvicorn app.main:app --reload --port 8000` |
| Frontend 서버 | `frontend/src/app/layout.tsx` | `npm run dev` → Next.js App Router 루트 레이아웃 |
| DB 마이그레이션 | `alembic/` | `alembic upgrade head` |
| 초기 데이터 | `app/seed/sectors.py`, `app/seed/stocks.py`, `app/seed/economic_events.py` | 앱 시작 시 `lifespan`에서 백그라운드 스레드로 자동 실행 |

---

## 스케줄러 작업 목록

`app/services/scheduler.py`의 `start_scheduler()` 에서 등록되는 7개 APScheduler 작업이다.

| 작업 ID | 트리거 | 실행 주기 | 호출 서비스 | 역할 |
|---------|--------|----------|-----------|------|
| `news_crawl` | interval | 10분 (기본값, 설정 가능) | `news_crawler.crawl_all_news()` + `ai_classifier.classify_sentiment()` + `macro_risk.detect_macro_risks()` | 뉴스 수집·분류·거시 리스크 감지·감성 백필 |
| `dart_crawl` | interval | 30분 | `dart_crawler.fetch_dart_disclosures()` + `backfill_disclosure_stock_ids()` | DART 공시 수집·종목 매핑 |
| `market_cap_update` | interval | 6시간 | `naver_finance.fetch_naver_stock_list()` | KOSPI/KOSDAQ 시가총액 DB 갱신 |
| `daily_briefing` | cron | 매일 08:30 KST | `fund_manager.generate_daily_briefing()` | AI 데일리 브리핑 자동 생성 |
| `signal_verification` | cron | 매일 18:00 KST | `signal_verifier.verify_signals()` | 투자 시그널 적중률 검증 (장 마감 후) |

> 참고: 스케줄러 시작 시 `news_crawl`, `dart_crawl`, `market_cap_update`는 `next_run_time=datetime.now()`로 즉시 1회 실행된다.

---

## API 라우트 목록

### 섹터 (`/api/sectors`)

| 메서드 | 경로 | 핸들러 | 역할 |
|--------|------|--------|------|
| GET | `/api/sectors` | `sectors.list_sectors` | 전체 섹터 목록 (종목 수·퍼포먼스 포함) |
| POST | `/api/sectors` | `sectors.create_sector` | 커스텀 섹터 생성 |
| GET | `/api/sectors/{id}` | `sectors.get_sector` | 섹터 상세 (종목 목록 포함) |
| DELETE | `/api/sectors/{id}` | `sectors.delete_sector` | 커스텀 섹터 삭제 |
| GET | `/api/sectors/{id}/news` | `sectors.get_sector_news` | 해당 섹터 관련 뉴스 |

### 종목 (`/api/stocks`)

| 메서드 | 경로 | 핸들러 | 역할 |
|--------|------|--------|------|
| GET | `/api/stocks` | `stocks.list_stocks` | 종목 목록 |
| POST | `/api/sectors/{id}/stocks` | `stocks.add_stock` | 섹터에 종목 추가 |
| DELETE | `/api/stocks/{id}` | `stocks.delete_stock` | 종목 삭제 |
| GET | `/api/stocks/{id}/news` | `stocks.get_stock_news` | 해당 종목 뉴스 |
| GET | `/api/stocks/{id}/price` | `stocks.get_stock_price` | 실시간 주가 데이터 |
| GET | `/api/stocks/{id}/financial` | `stocks.get_financial_data` | 재무 데이터 |

### 뉴스 (`/api/news`)

| 메서드 | 경로 | 핸들러 | 역할 |
|--------|------|--------|------|
| GET | `/api/news` | `news.list_news` | 전체 최신 뉴스 |
| GET | `/api/news/{id}` | `news.get_news` | 뉴스 상세 |
| POST | `/api/news/refresh` | `news.refresh_news` | 수동 뉴스 수집 트리거 |

### 공시 (`/api/disclosures`)

| 메서드 | 경로 | 핸들러 | 역할 |
|--------|------|--------|------|
| GET | `/api/disclosures` | `disclosures.list_disclosures` | DART 공시 목록 |
| GET | `/api/disclosures/{id}` | `disclosures.get_disclosure` | 공시 상세 |

### 알림 (`/api/alerts`)

| 메서드 | 경로 | 핸들러 | 역할 |
|--------|------|--------|------|
| GET | `/api/alerts` | `alerts.list_alerts` | 거시경제 리스크 알림 목록 |

### 이벤트 (`/api/events`)

| 메서드 | 경로 | 핸들러 | 역할 |
|--------|------|--------|------|
| GET | `/api/events` | `events.list_events` | 경제 캘린더 이벤트 목록 |

### AI 펀드매니저 (`/api/fund`) — 관리자 인증 필요

| 메서드 | 경로 | 핸들러 | 역할 |
|--------|------|--------|------|
| GET | `/api/fund/signals` | `fund_manager.get_signals` | 투자 시그널 목록 |
| POST | `/api/fund/signals` | `fund_manager.generate_signals` | 투자 시그널 수동 생성 |
| GET | `/api/fund/briefing` | `fund_manager.get_briefing` | 최신 데일리 브리핑 |
| POST | `/api/fund/briefing` | `fund_manager.generate_briefing` | 브리핑 수동 생성 |
| GET | `/api/fund/portfolio` | `fund_manager.get_portfolio` | 포트폴리오 리포트 |
| GET | `/api/fund/accuracy` | `fund_manager.get_accuracy` | 시그널 적중률 통계 |

### 인증 (`/api/auth`)

| 메서드 | 경로 | 핸들러 | 역할 |
|--------|------|--------|------|
| POST | `/api/auth/login` | `auth.login` | 관리자 로그인 → JWT 토큰 발급 |

### 시스템

| 메서드 | 경로 | 핸들러 | 역할 |
|--------|------|--------|------|
| GET/HEAD | `/api/health` | `main.health` | 서비스 헬스체크 |
| POST | `/api/deploy` | `main.deploy_webhook` | GitHub Webhook → 자동 배포 (HMAC-SHA256 검증) |
| GET | `/api/market-status` | `main.market_status` | 한국 주식 시장 개장 여부 조회 |

---

## 프론트엔드 페이지 라우트

Next.js App Router 파일 시스템 기반 라우팅이다.

| URL 경로 | 파일 위치 | 역할 |
|---------|---------|------|
| `/` | `app/page.tsx` | 대시보드 — 섹터 카드 그리드 + 거시경제 알림 배너 |
| `/sectors/[id]` | `app/sectors/[id]/page.tsx` | 섹터 상세 — 소속 종목 목록 + 섹터 뉴스 피드 |
| `/stocks` | `app/stocks/page.tsx` | 전체 종목 목록 (시가총액 정렬) |
| `/stocks/[id]` | `app/stocks/[id]/page.tsx` | 종목 상세 — 주가·재무·뉴스·공시 통합 뷰 |
| `/news` | `app/news/page.tsx` | 전체 뉴스 피드 (필터·페이지네이션) |
| `/news/[id]` | `app/news/[id]/page.tsx` | 뉴스 상세 |
| `/disclosures` | `app/disclosures/page.tsx` | DART 공시 목록 |
| `/fund` | `app/fund/page.tsx` | AI 펀드매니저 — 시그널·브리핑·포트폴리오 |
| `/calendar` | `app/calendar/page.tsx` | 경제 캘린더 이벤트 |
| `/watchlist` | `app/watchlist/page.tsx` | 관심 종목 목록 |
| `/manage` | `app/manage/page.tsx` | 관리 페이지 — 섹터·종목 CRUD |

---

## 앱 초기화 순서 (lifespan)

```
uvicorn 시작
    │
    ▼
lifespan() 실행 (app/main.py)
    │
    ├── 1. _run_migrations()  →  Alembic upgrade head (동기, 순차)
    │
    ├── 2. threading.Thread(_run_seed)  →  섹터·종목·경제이벤트 시드 (백그라운드)
    │
    └── 3. start_scheduler()  →  APScheduler 시작 (7개 작업 즉시 등록)
            │
            └── news_crawl, dart_crawl, market_cap_update 즉시 1회 실행
```
