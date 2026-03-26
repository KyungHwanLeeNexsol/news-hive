# NewsHive 의존성 지도

> 마지막 업데이트: 2026-03-26

## 백엔드 외부 패키지

### 핵심 프레임워크

| 패키지 | 버전 | 목적 |
|--------|------|------|
| `fastapi` | 0.115.6 | 비동기 REST API 프레임워크 |
| `uvicorn[standard]` | 0.34.0 | ASGI 서버 (uvloop, httptools 포함) |
| `python-multipart` | 0.0.20 | 멀티파트 폼 데이터 파싱 |

### 데이터베이스

| 패키지 | 버전 | 목적 |
|--------|------|------|
| `sqlalchemy` | 2.0.36 | ORM 및 DB 추상화 레이어 |
| `psycopg2-binary` | 2.9.10 | PostgreSQL 드라이버 |
| `alembic` | 1.14.1 | DB 스키마 마이그레이션 |

### 스케줄러

| 패키지 | 버전 | 목적 |
|--------|------|------|
| `apscheduler` | 3.10.4 | 백그라운드 작업 스케줄러 (cron/interval 지원) |

### 뉴스 크롤링

| 패키지 | 버전 | 목적 |
|--------|------|------|
| `httpx` | 0.28.1 | 비동기 HTTP 클라이언트 (크롤러 + AI API 호출) |
| `feedparser` | 6.0.11 | RSS/Atom 피드 파싱 |
| `beautifulsoup4` | 4.12.3 | HTML 파싱 및 기사 본문 스크래핑 |

### AI 분류

| 패키지 | 버전 | 목적 |
|--------|------|------|
| `google-genai` | 1.14.0 | Google Gemini API 클라이언트 |

### 유틸리티

| 패키지 | 버전 | 목적 |
|--------|------|------|
| `python-dotenv` | 1.0.1 | `.env` 파일 로드 |
| `pydantic-settings` | 2.7.1 | 환경변수 타입 안전 로드 |

---

## 프론트엔드 외부 패키지

### 핵심 프레임워크

| 패키지 | 목적 |
|--------|------|
| `next` (15.x) | React 풀스택 프레임워크 (App Router) |
| `react` / `react-dom` (19.x) | UI 라이브러리 |
| `typescript` | 타입 안전 JavaScript |

### 스타일링

| 패키지 | 목적 |
|--------|------|
| `tailwindcss` v4 | 유틸리티 퍼스트 CSS 프레임워크 |

---

## 내부 모듈 의존 관계

```
app/main.py
  ├── app/config.py          (settings 전역 설정)
  ├── app/database.py        (SessionLocal, engine)
  ├── app/models/            (ORM 모델 — 테이블 생성용 import)
  ├── app/seed/              (초기 데이터 시드)
  ├── app/services/scheduler.py  (백그라운드 작업 시작/종료)
  └── app/routers/           (API 라우터 등록)

app/services/scheduler.py
  ├── app/services/news_crawler.py     (뉴스 크롤링)
  ├── app/services/dart_crawler.py     (DART 공시)
  ├── app/services/naver_finance.py    (시가총액 업데이트)
  ├── app/services/fund_manager.py     (데일리 브리핑)
  ├── app/services/signal_verifier.py  (시그널 검증)
  ├── app/services/ai_classifier.py    (감성 백필)
  └── app/services/macro_risk.py       (거시 리스크 감지)

app/services/news_crawler.py
  ├── app/services/crawlers/naver.py
  ├── app/services/crawlers/google.py
  ├── app/services/crawlers/yahoo.py
  ├── app/services/crawlers/korean_rss.py
  ├── app/services/crawlers/content_scraper.py
  └── app/services/ai_classifier.py   (분류 + 감성 + 번역)

app/services/ai_classifier.py
  └── app/services/ai_client.py       (ask_ai 폴백 체인)

app/services/fund_manager.py
  ├── app/services/ai_client.py
  ├── app/services/technical_indicators.py
  └── app/services/naver_finance.py

app/routers/*.py
  ├── app/database.py        (get_db 의존성)
  ├── app/models/            (ORM 쿼리)
  └── app/schemas/           (요청/응답 직렬화)
```

---

## AI 프로바이더 의존 체인

```
ask_ai(prompt)  ← app/services/ai_client.py
    │
    ▼ 1순위
  Groq API  (https://api.groq.com)
  모델: GROQ_MODEL (설정값)
  특징: 무료 티어, 고속, 할당량 제한 있음
    │
    ▼ 실패 시 (HTTP 4xx/5xx 또는 키 미설정)
  Gemini API  (google-genai SDK)
  모델: GEMINI_MODEL (설정값)
  특징: Google 무료 티어 (20 req/day)
    │
    ▼ 실패 시
  OpenRouter API  (https://openrouter.ai)
  모델: openrouter/free
  특징: 최종 폴백, 다양한 모델 지원
    │
    ▼ 모두 실패 시
  RuntimeError 반환 → 호출부에서 로깅 후 스킵
```

**사용 지점:**

| 서비스 | ask_ai 호출 목적 |
|--------|----------------|
| `ai_classifier.py` | 뉴스 종목·섹터 분류, 감성 분석, 한→영 번역 |
| `fund_manager.py` | 투자 시그널 생성, 데일리 브리핑 작성 |
| `dart_crawler.py` | 공시 AI 요약 |
| `macro_risk.py` | 거시경제 리스크 평가 |

---

## DB 의존 구조

```
PostgreSQL 16
    │
    ├── sectors  ←────────── stocks (sector_id FK)
    │                          │
    │                          └── news_stock_relations (stock_id FK)
    │                          │
    │                          └── fund_signals (stock_id FK)
    │
    ├── news_articles ←────── news_stock_relations (news_id FK)
    │
    ├── disclosures (stock_id FK → stocks, nullable)
    │
    ├── macro_alerts (독립)
    │
    ├── economic_events (독립)
    │
    ├── daily_briefings (독립)
    │
    ├── sector_insights (sector_id FK → sectors)
    │
    └── portfolio_reports (독립)
```

**참조 무결성 패턴:**

- `news_stock_relations`: `stock_id` 또는 `sector_id` 중 하나만 설정 (뉴스가 종목 또는 섹터에 귀속)
- `disclosures.stock_id`: nullable — 종목 미매핑 공시도 저장
- 7일 이상 된 `news_articles`, `disclosures`는 스케줄러가 자동 정리

---

## 외부 API 의존성

| 외부 서비스 | 인증 방식 | 용도 | 장애 시 영향 |
|-----------|---------|------|------------|
| 네이버 검색 API | Client ID/Secret | 뉴스 검색 | 뉴스 수집 부분 감소 |
| Google News | RSS (인증 불필요) | 뉴스 피드 | 뉴스 수집 부분 감소 |
| Yahoo Finance | 공개 API | 해외 뉴스 | 뉴스 수집 부분 감소 |
| DART API | API Key | 공시 수집 | 공시 기능 중단 |
| Groq | Bearer Token | AI 분류 (1순위) | Gemini로 폴백 |
| Gemini | SDK Key | AI 분류 (2순위) | OpenRouter로 폴백 |
| OpenRouter | Bearer Token | AI 분류 (3순위) | AI 분류 실패 |
| Naver Finance | 공개 API | 실시간 주가 | 주가 데이터 없음 |
