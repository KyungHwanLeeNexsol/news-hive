---
spec_id: SPEC-FOLLOW-001
title: 기업 팔로잉 시스템 (Company Following System)
status: completed
priority: high
created: 2026-04-06
completed: 2026-04-06
commit: 14fcb86
dependencies: [SPEC-AUTH-001]
tier: 7
lifecycle: spec-anchored
---

# SPEC-FOLLOW-001: 기업 팔로잉 시스템

## Overview

사용자가 관심 종목을 "팔로잉"하면 AI가 해당 기업의 핵심 키워드를 자동 생성하고, 뉴스/공시/증권사 보고서 중 키워드에 매칭되는 콘텐츠가 발생할 때 텔레그램 알림을 전송하는 시스템.

## Problem Statement

현재 NewsHive는 전체 시장 대상의 뉴스 크롤링과 AI 시그널을 제공하지만, 개별 사용자가 특정 종목에 대한 맞춤형 알림을 받을 수 있는 방법이 없다. UserWatchlist(관심종목)은 존재하지만 키워드 기반 알림 기능은 없다. 투자자가 특정 종목의 핵심 뉴스를 놓치지 않으려면 수동으로 뉴스를 검색해야 하며, 이는 비효율적이다.

## Solution Design

### 핵심 컨셉

1. **종목 팔로잉**: 사용자가 종목 코드로 팔로잉 등록
2. **AI 키워드 생성**: Gemini/Z.AI를 활용하여 4가지 카테고리(제품, 경쟁사, 전방산업, 시장키워드)에서 핵심 키워드 자동 생성
3. **키워드 관리**: 사용자가 AI 생성 키워드를 수정/추가/삭제 가능
4. **키워드 매칭**: 스케줄러가 주기적으로 신규 뉴스/공시를 사용자 키워드와 매칭
5. **텔레그램 알림**: 매칭된 콘텐츠를 텔레그램으로 실시간 알림 발송

### 기존 시스템 활용

- **인증**: `get_current_user` (JWT, `app/routers/auth.py`) 재사용
- **종목 DB**: `Stock` 모델 (`app/models/stock.py`) 재사용
- **뉴스 크롤러**: `NewsArticle` 모델 + 기존 `news_crawler.py` 활용
- **공시 크롤러**: `Disclosure` 모델 + 기존 `dart_crawler.py` 활용
- **AI 클라이언트**: `ask_ai()` (`app/services/ai_client.py`) 재사용
- **스케줄러**: APScheduler (`app/services/scheduler.py`) 에 새 작업 등록
- **알림**: 현재 Web Push(`push_service.py`)만 존재 -- 텔레그램 봇 신규 추가 필요

## Requirements (EARS Format)

### 종목 팔로잉 (REQ-FOLLOW-001 ~ 005)

**REQ-FOLLOW-001** (Event-Driven):
WHEN 사용자가 유효한 6자리 종목 코드를 제출 THEN 시스템은 해당 종목을 사용자의 팔로잉 목록에 추가해야 한다.

**REQ-FOLLOW-002** (Event-Driven):
WHEN 사용자가 팔로잉 중인 종목의 삭제를 요청 THEN 시스템은 해당 종목과 연관된 모든 키워드를 함께 삭제해야 한다.

**REQ-FOLLOW-003** (State-Driven):
IF 사용자가 이미 팔로잉 중인 종목 코드를 재등록 THEN 시스템은 409 Conflict를 반환해야 한다.

**REQ-FOLLOW-004** (State-Driven):
IF 제출된 종목 코드가 stocks 테이블에 존재하지 않는 경우 THEN 시스템은 404 Not Found를 반환해야 한다.

**REQ-FOLLOW-005** (Event-Driven):
WHEN 사용자가 팔로잉 목록을 조회 THEN 시스템은 각 종목의 이름, 코드, 키워드 수, 최근 알림 시각을 반환해야 한다.

### AI 키워드 생성 (REQ-FOLLOW-010 ~ 014)

**REQ-FOLLOW-010** (Event-Driven):
WHEN 사용자가 팔로잉 종목에 대해 AI 키워드 생성을 요청 THEN 시스템은 4가지 카테고리(제품, 경쟁사, 전방산업, 시장키워드)에서 키워드를 생성해야 한다.

**REQ-FOLLOW-011** (Ubiquitous):
시스템은 AI 키워드 생성 시 항상 `ask_ai()` 다중 프로바이더(Gemini 라운드로빈 + Z.AI fallback)를 사용해야 한다.

**REQ-FOLLOW-012** (State-Driven):
IF AI 키워드 생성에 실패(모든 프로바이더 소진) THEN 시스템은 빈 키워드 목록과 함께 에러 메시지를 반환하고, 사용자는 수동으로 키워드를 추가할 수 있어야 한다.

**REQ-FOLLOW-013** (Unwanted):
시스템은 동일 종목에 대해 중복 키워드를 생성하지 않아야 한다.

**REQ-FOLLOW-014** (Event-Driven):
WHEN AI가 키워드를 생성 THEN 각 키워드에는 카테고리(product, competitor, upstream, market)가 태그되어야 한다.

### 키워드 관리 (REQ-FOLLOW-020 ~ 023)

**REQ-FOLLOW-020** (Event-Driven):
WHEN 사용자가 커스텀 키워드를 추가 THEN 시스템은 해당 키워드를 category="custom"으로 저장해야 한다.

**REQ-FOLLOW-021** (Event-Driven):
WHEN 사용자가 키워드 삭제를 요청 THEN 시스템은 AI 생성/수동 추가 구분 없이 해당 키워드를 삭제해야 한다.

**REQ-FOLLOW-022** (State-Driven):
IF 종목의 키워드가 0개인 상태 THEN 해당 종목에 대한 키워드 매칭 알림은 발송되지 않아야 한다.

**REQ-FOLLOW-023** (Ubiquitous):
시스템은 키워드 목록 조회 시 항상 카테고리별로 그룹화하여 반환해야 한다.

### 키워드 매칭 및 알림 (REQ-FOLLOW-030 ~ 037)

**REQ-FOLLOW-030** (Event-Driven):
WHEN 스케줄러가 키워드 매칭 작업을 실행 THEN 시스템은 마지막 실행 이후 수집된 뉴스/공시의 제목+본문에서 사용자 키워드와의 매칭을 수행해야 한다.

**REQ-FOLLOW-031** (Event-Driven):
WHEN 키워드 매칭이 발견 THEN 시스템은 해당 사용자의 텔레그램 채팅으로 알림을 발송해야 한다.

**REQ-FOLLOW-032** (Ubiquitous):
시스템은 알림 발송 시 항상 콘텐츠 유형([뉴스]/[공시]/[보고서])을 구분하여 표시해야 한다.

**REQ-FOLLOW-033** (Ubiquitous):
시스템은 알림 메시지에 항상 원본 소스의 클릭 가능한 링크를 포함해야 한다.

**REQ-FOLLOW-034** (Unwanted):
시스템은 동일 사용자에게 동일 콘텐츠에 대해 중복 알림을 발송하지 않아야 한다.

**REQ-FOLLOW-035** (State-Driven):
IF 사용자의 텔레그램 chat_id가 설정되지 않은 경우 THEN 해당 사용자에 대한 텔레그램 알림은 건너뛰고, Web Push 대체 발송을 시도해야 한다.

**REQ-FOLLOW-036** (Event-Driven):
WHEN 알림이 발송 THEN 시스템은 `keyword_notifications` 테이블에 발송 기록을 저장해야 한다.

**REQ-FOLLOW-037** (Optional):
가능하면 사용자별 알림 빈도 제한(rate limiting) 기능을 제공하여, 동일 종목에 대해 1시간 내 최대 5건으로 제한한다.

### 텔레그램 연동 (REQ-FOLLOW-040 ~ 042)

**REQ-FOLLOW-040** (Event-Driven):
WHEN 사용자가 텔레그램 연동을 요청 THEN 시스템은 일회용 연동 코드를 생성하고 사용자에게 표시해야 한다.

**REQ-FOLLOW-041** (Event-Driven):
WHEN 사용자가 텔레그램 봇에 연동 코드를 전송 THEN 시스템은 해당 사용자의 telegram_chat_id를 저장해야 한다.

**REQ-FOLLOW-042** (Ubiquitous):
시스템은 텔레그램 메시지 발송 시 항상 Bot API의 `sendMessage`를 `parse_mode=HTML`로 사용해야 한다.

## Database Schema

### 신규 테이블

```
stock_followings
├── id: Integer (PK)
├── user_id: Integer (FK → users.id, ON DELETE CASCADE)
├── stock_id: Integer (FK → stocks.id, ON DELETE CASCADE)
├── created_at: DateTime (server_default=now)
└── UNIQUE(user_id, stock_id)

stock_keywords
├── id: Integer (PK)
├── following_id: Integer (FK → stock_followings.id, ON DELETE CASCADE)
├── keyword: String(100)
├── category: String(20)  -- product | competitor | upstream | market | custom
├── source: String(10)    -- ai | manual
├── created_at: DateTime (server_default=now)
└── UNIQUE(following_id, keyword)

keyword_notifications
├── id: Integer (PK)
├── user_id: Integer (FK → users.id, ON DELETE CASCADE)
├── keyword_id: Integer (FK → stock_keywords.id, ON DELETE SET NULL)
├── content_type: String(20)  -- news | disclosure | report
├── content_id: Integer       -- 대상 콘텐츠의 ID
├── content_title: String(500)
├── content_url: String(1000)
├── sent_at: DateTime (server_default=now)
├── channel: String(20)       -- telegram | web_push
└── UNIQUE(user_id, content_type, content_id)
```

### 기존 테이블 변경

```
users (수정)
└── telegram_chat_id: String(50), nullable=True  -- 텔레그램 연동 시 저장
```

## API Design

### Following CRUD

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/following/stocks` | 종목 팔로잉 등록 |
| DELETE | `/api/following/stocks/{stock_code}` | 종목 팔로잉 해제 |
| GET | `/api/following/stocks` | 팔로잉 목록 조회 |

### Keyword Management

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/following/stocks/{stock_code}/keywords` | 키워드 목록 조회 |
| POST | `/api/following/stocks/{stock_code}/keywords` | 수동 키워드 추가 |
| DELETE | `/api/following/stocks/{stock_code}/keywords/{keyword_id}` | 키워드 삭제 |
| POST | `/api/following/stocks/{stock_code}/keywords/ai-generate` | AI 키워드 생성 |

### Telegram Integration

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/following/telegram/link` | 텔레그램 연동 코드 생성 |
| GET | `/api/following/telegram/status` | 텔레그램 연동 상태 조회 |
| DELETE | `/api/following/telegram/link` | 텔레그램 연동 해제 |

### Notification History

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/following/notifications` | 알림 히스토리 조회 |

## AI Keyword Generation Design

### 프롬프트 전략

AI에게 종목명 + 종목코드를 전달하고, 4가지 카테고리에서 핵심 키워드를 추출하도록 프롬프트를 설계한다.

**입력**: 종목코드 (예: 298020), 기업명 (예: 효성티앤씨)
**출력**: JSON 형식의 카테고리별 키워드 리스트

**프롬프트 카테고리**:
1. **product**: 기업의 주력 제품/서비스 관련 키워드 (예: 스판덱스 가격)
2. **competitor**: 주요 경쟁사 관련 키워드 (예: 중국 스판덱스 업체)
3. **upstream**: 전방/후방 산업, 원재료 관련 키워드 (예: 석탄 가격, 천연가스 가격)
4. **market**: 해당 기업이 속한 시장/트렌드 키워드 (예: 스포츠웨어 성장)

### 데이터 소스

- DART 사업보고서 텍스트에서 빈출 도메인 용어 추출 (기존 `dart_crawler.py` 활용)
- AI의 학습 데이터 기반 기업 메타데이터 추론
- 기존 `stocks.keywords` 필드 참조 (있는 경우)

### Rate Limiting

- AI 키워드 생성은 종목당 1일 1회로 제한
- 캐시: 생성된 키워드는 DB에 저장되므로 재호출 시 기존 키워드 반환

## Notification System Design

### 스케줄러 작업

- **작업명**: `keyword_matching`
- **실행 주기**: 뉴스 크롤링 직후 (기존 `_run_crawl_job` 완료 후 연쇄 실행)
- **대안**: 별도 5분 간격 interval 작업

### 매칭 알고리즘

1. 마지막 매칭 시각 이후 수집된 뉴스/공시를 조회
2. 각 콘텐츠의 제목 + 본문(있는 경우)에서 키워드 포함 여부 확인
3. 매칭된 (user_id, content_type, content_id) 조합이 `keyword_notifications`에 없으면 알림 발송

### 텔레그램 메시지 포맷

```
[뉴스] 스판덱스 가격 관련
효성티앤씨 스판덱스 가격 인상 전망...3Q 실적 개선 기대
https://news.example.com/article/12345
```

### 알림 채널 우선순위

1. 텔레그램 (telegram_chat_id 설정된 사용자)
2. Web Push (telegram 미설정 시 기존 push_service.py 활용)

## Frontend Design

### 페이지 구조

```
/following
├── 팔로잉 종목 목록 (카드 형태)
│   ├── 종목명 + 종목코드
│   ├── 키워드 수 배지
│   ├── 최근 알림 시각
│   └── 언팔로잉 버튼
├── 종목 추가 검색 바 (종목코드/종목명 검색)
├── 텔레그램 연동 상태 표시
└── 알림 히스토리 탭

/following/[stock_code]
├── 종목 상세 + 키워드 관리
│   ├── AI 키워드 생성 버튼
│   ├── 카테고리별 키워드 태그 목록
│   ├── 수동 키워드 추가 입력
│   └── 키워드별 삭제 버튼
└── 해당 종목 알림 히스토리
```

### 참고할 기존 패턴

- `/watchlist/page.tsx`: 관심종목 목록 UI 패턴 (유사한 CRUD)
- `/fund/page.tsx`: AI 시그널 목록 + 상세 패턴
- `/stocks/[id]/page.tsx`: 종목 상세 페이지 패턴

## Exclusions (What NOT to Build)

- Shall NOT support 실시간 WebSocket 기반 알림 (reason: 기존 인프라에서 스케줄러 기반 폴링이 충분하며, 실시간성은 텔레그램 봇이 담당)
- Shall NOT implement 증권사 보고서 크롤러 (reason: 현재 보고서 수집 인프라 없음. 1차 구현에서는 뉴스 + 공시만 대상으로 함. 향후 SPEC에서 추가)
- Shall NOT implement 키워드 자동 갱신 (reason: 사용자 수동 관리 + AI 일회 생성으로 충분. 자동 갱신은 AI 비용 과다)
- Shall NOT support 다국어 키워드 매칭 (reason: 한국어 뉴스/공시만 대상)
- Shall NOT implement 알림 일시정지/스케줄 기능 (reason: MVP 범위 초과)
- Will NOT be optimized for 대규모 사용자 (reason: 현재 단일 VM 배포 환경, 수백 명 수준에서 충분)

## Dependencies & Risks

### Dependencies

| Dependency | Status | Impact |
|------------|--------|--------|
| SPEC-AUTH-001 (JWT 인증) | 구현 완료 | `get_current_user` 의존성 -- 정상 동작 확인됨 |
| Stock 테이블 데이터 | 운영 중 | 종목 코드 조회에 필요 |
| 뉴스 크롤러 (scheduler) | 운영 중 | 키워드 매칭 대상 콘텐츠 공급 |
| DART 크롤러 | 운영 중 | 공시 매칭 대상 콘텐츠 공급 |
| Gemini/Z.AI API | 운영 중 | AI 키워드 생성에 필요 |
| 텔레그램 Bot API | 신규 추가 필요 | BOT_TOKEN 환경 변수 + python-telegram-bot 패키지 |

### Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| 텔레그램 Bot API rate limit | Medium | 메시지 큐잉 + 초당 30메시지 제한 준수 |
| AI 키워드 품질 불량 | Medium | 사용자 수동 편집 기능 제공 |
| 키워드 매칭 false positive | Medium | 제목 + 본문 동시 매칭, 최소 글자 수 제한 (2글자 이상) |
| Gemini rate limit 소진 | Low | 기존 Z.AI fallback 활용 |
| 대량 알림 시 성능 | Low | 배치 처리 + rate limiting |
| DART API 장애 | Low | 기존 circuit breaker 패턴 적용 |

## Traceability

- REQ-FOLLOW-001~005 → StockFollowing 모델 + following CRUD API
- REQ-FOLLOW-010~014 → AI keyword generation service
- REQ-FOLLOW-020~023 → Keyword management API
- REQ-FOLLOW-030~037 → Keyword matching scheduler + notification service
- REQ-FOLLOW-040~042 → Telegram bot integration
