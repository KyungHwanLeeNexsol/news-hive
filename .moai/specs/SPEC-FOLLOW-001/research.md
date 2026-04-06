---
spec_id: SPEC-FOLLOW-001
type: research
created: 2026-04-06
---

# SPEC-FOLLOW-001: 리서치 결과

## 1. 기존 알림 시스템 분석

### Web Push (현재 유일한 알림 채널)

- **서비스**: `backend/app/services/push_service.py` — VAPID + pywebpush 기반
- **라우터**: `backend/app/routers/push.py` — 구독/해제/VAPID 키 조회
- **모델**: `PushSubscription` (user_id, endpoint, p256dh_key, auth_key)
- **특징**: 
  - VAPID 미설정 시 개발 모드 폴백 (알림 생략)
  - 다중 디바이스 지원 (사용자당 N개 구독)
  - 410 Gone 응답 시 구독 만료 처리

### 텔레그램 연동: 현재 없음

- `grep -r "telegram"` 결과 0건
- 텔레그램 관련 코드, 패키지, 설정 모두 없음
- **신규 구현 필요**: Bot API 연동 + 메시지 발송 서비스

## 2. 인증 시스템 분석

### JWT 사용자 인증 (SPEC-AUTH-001 구현 완료)

- **라우터**: `backend/app/routers/auth.py`
- **핵심 함수**: `get_current_user(token, db) -> User`
  - OAuth2PasswordBearer 스킴 사용
  - JWT 검증 → User 객체 반환
  - 모든 보호 엔드포인트에서 `Depends(get_current_user)` 패턴
- **모델**: User (id, email, password_hash, name, email_verified, created_at, last_login_at)
- **관련 모델**: EmailVerificationCode, RefreshToken, UserWatchlist, UserPreferences, PushSubscription

### User 모델 확장 포인트

- `telegram_chat_id` 필드 추가 필요 (nullable String)
- `followings` relationship 추가 필요

## 3. 뉴스/공시 시스템 분석

### 뉴스 (NewsArticle)

- **모델**: `backend/app/models/news.py`
  - 필드: id, title, summary, url, source, published_at, collected_at, sentiment, urgency, ai_summary, content
  - relations → NewsStockRelation (종목 연관)
- **크롤러**: `backend/app/services/news_crawler.py` — 스케줄러에서 interval 호출
- **수집 주기**: `NEWS_CRAWL_INTERVAL_MINUTES` 설정 기반

### 공시 (Disclosure)

- **모델**: `backend/app/models/disclosure.py`
  - 필드: id, corp_code, corp_name, stock_code, stock_id, report_name, report_type, rcept_no, rcept_dt, url, ai_summary
  - SPEC-AI-004 추가 필드: impact_score, baseline_price, reflected_pct, unreflected_gap, ripple_checked, disclosed_at
- **크롤러**: `backend/app/services/dart_crawler.py` — DART Open API (opendart.fss.or.kr)
- **수집 주기**: `DART_CRAWL_INTERVAL_MINUTES` 설정 기반

### 증권사 보고서: 현재 없음

- `grep -r "analyst|report|증권사|보고서"` 결과에서 증권사 보고서 전용 크롤러/모델 확인 불가
- 기존 DART 크롤러의 `report_name` / `report_type`은 DART 공시 분류용 (증권사 보고서 아님)
- **1차 구현에서 제외**: 뉴스 + 공시만 키워드 매칭 대상

## 4. AI 클라이언트 분석

### ask_ai() 인터페이스

- **파일**: `backend/app/services/ai_client.py`
- **함수**: `ask_ai(prompt, max_retries=3) -> str | None`
- **함수**: `ask_ai_with_model(prompt, max_retries=3) -> tuple[str | None, str]`
- **전략**: 
  1. Gemini 3키 라운드로빈 (GEMINI_API_KEY, _2, _3)
  2. 전부 rate limit 시 Z.AI(GLM) fallback
  3. Circuit breaker 패턴 적용
- **활용 방식**: 프롬프트 전달 → 텍스트 응답 수신 → JSON 파싱 (호출측 담당)

### AI 키워드 생성 시 고려사항

- JSON 응답 포맷 요청 → 파싱 실패 가능성 있음 (try/except 필수)
- Gemini rate limit: 무료 티어 20 req/day → 키워드 생성 횟수 제한 필요
- 기존 `stocks.keywords` 필드 (ARRAY(Text))는 정적 키워드 목록으로 참조 가능

## 5. 스케줄러 분석

### APScheduler 구조

- **파일**: `backend/app/services/scheduler.py`
- **타입**: `BackgroundScheduler` (별도 스레드 풀에서 실행)
- **패턴**: 
  - sync wrapper 함수 → `asyncio.run()` 으로 async 작업 실행
  - `@retry_with_backoff(max_attempts=3)` 데코레이터
  - `_record_job_duration()` Prometheus 메트릭 기록
  - `SessionLocal()` DB 세션 생성/해제 패턴

### 기존 작업 목록 (20+개)

- news_crawl (interval)
- dart_crawl (interval)
- market_cap_update (interval)
- daily_briefing (cron 08:30 KST)
- signal_verification (cron 18:00 KST)
- news_impact_backfill (cron 18:30 KST)
- commodity_price_fetch (10분 interval)
- commodity_news_crawl (30분 interval)
- fast_verify (1시간 interval)
- 등등...

### 키워드 매칭 작업 추가 전략

- **방법 1**: `_run_crawl_job()` / `_run_dart_crawl()` 끝에 연쇄 호출
  - 장점: 새 콘텐츠 수집 직후 매칭 → 빠른 알림
  - 단점: 크롤링 실패 시 매칭도 실행 안됨
- **방법 2**: 별도 interval 작업 (5~10분)
  - 장점: 독립적 실행, 크롤링 실패와 무관
  - 단점: 약간의 지연
- **권장**: 방법 1 + 방법 2 병행 (연쇄 + fallback interval)

## 6. 종목 모델 (Stock) 분석

- **모델**: `backend/app/models/stock.py`
- **필드**: id, sector_id, name, stock_code, market, market_cap, keywords, created_at
- **stock_code**: String(20) — 한국 주식 6자리 코드 (예: "298020")
- **keywords**: ARRAY(Text) — 기존 정적 키워드 배열 (AI 생성 키워드와 별개)
- **관계**: sector (Sector), news_relations (NewsStockRelation), disclosures (backref)

### 팔로잉 시 종목 검증

- stock_code로 Stock 테이블 조회 → 존재하지 않으면 404
- stocks 테이블은 seed 데이터 + market_cap_update로 유지됨

## 7. 프론트엔드 패턴 분석

### 기존 페이지 구조

```
frontend/src/app/
├── auth/          -- 로그인/회원가입
├── calendar/      -- 경제 캘린더
├── chat/          -- AI 채팅
├── commodities/   -- 원자재
├── disclosures/   -- 공시
├── fund/          -- AI 펀드매니저
├── maintenance/   -- 점검 페이지
├── manage/        -- 관리자
├── news/          -- 뉴스
├── sectors/       -- 섹터
├── stocks/        -- 종목 (상세: [id])
├── watchlist/     -- 관심종목
├── layout.tsx     -- 레이아웃
└── page.tsx       -- 홈
```

### 참조할 패턴

- **watchlist/page.tsx**: 관심종목 CRUD — 종목 검색 + 추가/삭제 UI (가장 유사한 패턴)
- **stocks/[id]/page.tsx**: 동적 라우팅 패턴
- **fund/page.tsx**: 리스트 + AI 관련 기능

## 8. UserWatchlist vs StockFollowing 차이점

| Feature | UserWatchlist (기존) | StockFollowing (신규) |
|---------|---------------------|----------------------|
| 목적 | 관심종목 저장 (UI 필터) | 키워드 기반 알림 구독 |
| 키워드 | 없음 | 종목별 키워드 관리 |
| AI 연동 | 없음 | AI 키워드 생성 |
| 알림 | 없음 | 텔레그램/Web Push 알림 |
| 테이블 | user_watchlists | stock_followings + stock_keywords |

두 기능은 독립적이며, 향후 통합 가능 (watchlist → following으로 마이그레이션).

## 9. 텔레그램 Bot API 기술 검토

### 메시지 발송

- HTTP POST `https://api.telegram.org/bot{TOKEN}/sendMessage`
- Body: `{"chat_id": "...", "text": "...", "parse_mode": "HTML"}`
- 별도 패키지 불필요: 기존 `httpx` 라이브러리로 충분

### Webhook 수신

- `setWebhook` API로 URL 등록
- HTTPS 필수 (self-signed 인증서 가능)
- OCI VM(140.245.76.242)은 HTTP:8000 — Vercel 프록시 또는 Cloudflare Tunnel 필요
- **대안**: 개발 단계에서는 polling 모드 (`getUpdates`) 사용

### Rate Limit

- 동일 채팅: 초당 1메시지
- 전체: 초당 30메시지
- 그룹: 분당 20메시지
- 현재 사용자 규모에서는 문제 없음

## 10. DART 사업보고서 활용 가능성

### 현재 DART 크롤러

- `fetch_dart_disclosures(db)`: 최근 공시 목록만 수집 (제목 + URL)
- 사업보고서 본문 텍스트 접근: DART API의 `document.xml` 다운로드 필요
- 추가 API 호출 + XML 파싱 필요 → 1차 구현에서는 AI 학습 데이터 기반 추론으로 대체

### 1차 구현 전략

- AI가 기업명만으로 키워드 추론 (Gemini의 학습 데이터 활용)
- 향후 DART 사업보고서 텍스트 분석 추가 시 키워드 품질 향상 가능
