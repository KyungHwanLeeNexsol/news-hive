---
spec_id: SPEC-FOLLOW-001
type: plan
created: 2026-04-06
---

# SPEC-FOLLOW-001: 구현 계획

## Implementation Strategy

DDD(Domain-Driven Design) 방식으로 구현하며, 기존 패턴(모델 → 스키마 → 서비스 → 라우터 → 마이그레이션 → 프론트엔드)을 따른다.

## Milestone 1: 데이터 모델 및 마이그레이션 (Priority: High)

### 파일 목록

| Action | File | Description |
|--------|------|-------------|
| CREATE | `backend/app/models/following.py` | StockFollowing, StockKeyword, KeywordNotification 모델 |
| EDIT | `backend/app/models/__init__.py` | 신규 모델 import 등록 |
| EDIT | `backend/app/models/user.py` | User 모델에 `telegram_chat_id` 필드 추가, followings 관계 추가 |
| CREATE | `backend/alembic/versions/037_spec_follow_001_following.py` | 마이그레이션: stock_followings, stock_keywords, keyword_notifications 테이블 생성 + users.telegram_chat_id 추가 |

### 구현 세부

- `StockFollowing`: user_id + stock_id 유니크 제약, CASCADE 삭제
- `StockKeyword`: following_id + keyword 유니크 제약, category enum (product/competitor/upstream/market/custom)
- `KeywordNotification`: user_id + content_type + content_id 유니크 제약 (중복 알림 방지)
- `User.telegram_chat_id`: nullable String(50)

### 관련 요구사항

REQ-FOLLOW-001, REQ-FOLLOW-002, REQ-FOLLOW-003, REQ-FOLLOW-013, REQ-FOLLOW-034, REQ-FOLLOW-036

---

## Milestone 2: 팔로잉 CRUD API (Priority: High)

### 파일 목록

| Action | File | Description |
|--------|------|-------------|
| CREATE | `backend/app/schemas/following.py` | Pydantic 요청/응답 스키마 |
| CREATE | `backend/app/routers/following.py` | 팔로잉 + 키워드 CRUD 엔드포인트 |
| EDIT | `backend/app/main.py` | following 라우터 등록 |

### 엔드포인트 구현

- `POST /api/following/stocks` — 종목코드 검증 → StockFollowing 생성
- `DELETE /api/following/stocks/{stock_code}` — CASCADE로 키워드도 삭제
- `GET /api/following/stocks` — 팔로잉 목록 + 키워드 수 + 최근 알림 시각 조인
- `GET /api/following/stocks/{stock_code}/keywords` — 카테고리별 그룹화
- `POST /api/following/stocks/{stock_code}/keywords` — 수동 키워드 추가
- `DELETE /api/following/stocks/{stock_code}/keywords/{keyword_id}` — 키워드 삭제

### 관련 요구사항

REQ-FOLLOW-001~005, REQ-FOLLOW-020~023

---

## Milestone 3: AI 키워드 생성 서비스 (Priority: High)

### 파일 목록

| Action | File | Description |
|--------|------|-------------|
| CREATE | `backend/app/services/keyword_generator.py` | AI 키워드 생성 로직 |

### 구현 세부

- `generate_keywords(stock_code, company_name) -> list[dict]`
- 기존 `ask_ai()` 호출하여 4카테고리 키워드 생성
- 프롬프트: 종목명/코드 입력 → JSON 형식 출력 요구
- 응답 파싱: JSON 파싱 실패 시 빈 리스트 반환
- 중복 키워드 필터링 (DB 기존 키워드와 비교)
- 1일 1회 rate limit (마지막 생성 시각 체크)

### AI 프롬프트 템플릿 (초안)

```
당신은 한국 주식 시장 전문가입니다.
다음 기업에 대해 투자자가 모니터링해야 할 핵심 키워드를 생성하세요.

기업명: {company_name}
종목코드: {stock_code}

다음 4가지 카테고리별로 각 3~5개의 키워드를 JSON 형식으로 반환하세요:
1. product: 기업의 주력 제품/서비스 관련 (가격, 수요, 공급 포함)
2. competitor: 주요 경쟁사 이름 및 동향
3. upstream: 원재료, 전방산업, 공급망 관련
4. market: 해당 산업의 트렌드, 규제, 글로벌 이슈

JSON 형식:
{"product": ["키워드1", ...], "competitor": [...], "upstream": [...], "market": [...]}
```

### 관련 요구사항

REQ-FOLLOW-010~014

---

## Milestone 4: 텔레그램 봇 연동 (Priority: High)

### 파일 목록

| Action | File | Description |
|--------|------|-------------|
| CREATE | `backend/app/services/telegram_service.py` | 텔레그램 Bot API 메시지 발송 |
| EDIT | `backend/app/routers/following.py` | 텔레그램 연동 엔드포인트 추가 |
| EDIT | `backend/app/config.py` | TELEGRAM_BOT_TOKEN 설정 추가 |
| EDIT | `backend/requirements.txt` 또는 `pyproject.toml` | httpx 이미 존재 (추가 의존성 없음) |

### 구현 세부

- `send_telegram_message(chat_id, text, parse_mode="HTML") -> bool`
- Telegram Bot API의 `sendMessage` 엔드포인트 직접 호출 (httpx)
- 별도 패키지 불필요: `https://api.telegram.org/bot{TOKEN}/sendMessage` HTTP 호출
- 연동 코드: 6자리 랜덤 코드 생성 → 인메모리 또는 DB 임시 저장 → 봇에서 코드 수신 시 chat_id 매핑
- Webhook 또는 Polling 방식으로 봇 메시지 수신

### 텔레그램 봇 메시지 수신 방식

**Webhook 방식 (권장)**:
- `/api/following/telegram/webhook` 엔드포인트 등록
- Telegram Bot API의 `setWebhook`으로 URL 등록
- 봇으로 들어오는 메시지에서 연동 코드 파싱

### 관련 요구사항

REQ-FOLLOW-040~042

---

## Milestone 5: 키워드 매칭 스케줄러 (Priority: High)

### 파일 목록

| Action | File | Description |
|--------|------|-------------|
| CREATE | `backend/app/services/keyword_matcher.py` | 키워드 매칭 + 알림 디스패치 로직 |
| EDIT | `backend/app/services/scheduler.py` | `_run_keyword_matching` 작업 등록 |

### 구현 세부

- `match_keywords_and_notify(db) -> dict`
- 마지막 실행 이후 새로운 뉴스/공시 조회 (created_at > last_run)
- 전체 활성 키워드를 메모리에 로드 (user_id → keyword 매핑)
- 각 콘텐츠의 title (+content/ai_summary)에서 키워드 검색
- 매칭 시 keyword_notifications 테이블에서 중복 체크
- 신규 매칭 → 텔레그램 또는 Web Push 발송

### 스케줄러 등록

- 뉴스 크롤링 완료 후 연쇄 실행 (`_run_crawl_job` 마지막에 호출)
- DART 크롤링 완료 후에도 연쇄 실행 (`_run_dart_crawl` 마지막에 호출)
- 별도 fallback: 10분 interval 독립 작업 (크롤링 실패 시에도 동작)

### 관련 요구사항

REQ-FOLLOW-030~037

---

## Milestone 6: 프론트엔드 (Priority: Medium)

### 파일 목록

| Action | File | Description |
|--------|------|-------------|
| CREATE | `frontend/src/app/following/page.tsx` | 팔로잉 목록 페이지 |
| CREATE | `frontend/src/app/following/[stock_code]/page.tsx` | 종목 키워드 관리 페이지 |
| EDIT | `frontend/src/app/layout.tsx` | 네비게이션에 "팔로잉" 메뉴 추가 |

### 구현 세부

- 팔로잉 목록: 카드 그리드 레이아웃, 종목 검색 바, 빈 상태 안내
- 키워드 관리: 카테고리 탭, 태그 형태 키워드 표시, AI 생성 버튼, 수동 추가 입력
- 텔레그램 연동: 설정 섹션에 연동 상태 + 연동/해제 버튼
- 알림 히스토리: 최근 알림 목록 (무한 스크롤)

### 관련 요구사항

전체 Frontend Requirements

---

## Milestone 7: 테스트 (Priority: Medium)

### 파일 목록

| Action | File | Description |
|--------|------|-------------|
| CREATE | `backend/tests/test_following.py` | 팔로잉 CRUD 테스트 |
| CREATE | `backend/tests/test_keyword_generator.py` | AI 키워드 생성 테스트 |
| CREATE | `backend/tests/test_keyword_matcher.py` | 키워드 매칭 로직 테스트 |
| CREATE | `backend/tests/test_telegram_service.py` | 텔레그램 발송 테스트 |

### 테스트 전략

- 단위 테스트: 키워드 매칭 로직, AI 응답 파싱, 중복 체크
- 통합 테스트: API 엔드포인트 (conftest.py 기존 TestClient 재사용)
- Mock: AI 클라이언트, 텔레그램 API 호출 모킹

---

## Technical Approach

### 기존 패턴 준수

- **모델**: SQLAlchemy 2.0 Mapped 스타일 (기존 `user.py`, `stock.py` 패턴)
- **라우터**: FastAPI APIRouter with prefix + tags (기존 `push.py` 패턴)
- **인증**: `Depends(get_current_user)` (기존 auth.py 패턴)
- **스케줄러**: BackgroundScheduler + `@retry_with_backoff` 데코레이터 (기존 scheduler.py 패턴)
- **AI 호출**: `ask_ai()` 사용 (기존 ai_client.py 패턴)
- **에러 처리**: HTTPException with 한국어 메시지 (기존 패턴)

### 텔레그램 봇 설정

1. @BotFather로 봇 생성 → BOT_TOKEN 획득
2. `.env`에 `TELEGRAM_BOT_TOKEN` 추가
3. Webhook URL 등록: `https://{backend_domain}/api/following/telegram/webhook`
4. 또는 개발 환경에서는 polling 모드 사용

---

## Architecture Diagram

```
[User] ──POST /following/stocks──→ [Following Router]
                                        │
                                   [StockFollowing DB]
                                        │
[User] ──POST /keywords/ai-generate──→ [Keyword Generator]
                                        │
                                   [ask_ai() → Gemini/Z.AI]
                                        │
                                   [StockKeyword DB]

[Scheduler] ──interval 10min──→ [Keyword Matcher]
                                    │
                            ┌───────┴───────┐
                       [NewsArticle]   [Disclosure]
                            │               │
                      keyword search   keyword search
                            │               │
                            └───────┬───────┘
                                    │
                            [KeywordNotification DB]
                                    │
                        ┌───────────┴───────────┐
                   [Telegram Bot]          [Web Push]
                        │                       │
                   [User Telegram]        [User Browser]
```

## Risks & Mitigation

| Risk | Mitigation |
|------|------------|
| 키워드 매칭 성능 (대량 키워드 x 대량 뉴스) | 배치 처리, SQL LIKE 대신 Python in-memory 매칭 |
| 텔레그램 봇 토큰 노출 | 환경 변수로 관리, .env에 저장 |
| AI 키워드 JSON 파싱 실패 | try/except + 빈 리스트 fallback |
| 텔레그램 webhook SSL 요구 | Vercel 프론트엔드 프록시 또는 ngrok(개발) |
