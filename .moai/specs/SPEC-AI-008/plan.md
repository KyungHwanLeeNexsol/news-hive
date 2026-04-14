# SPEC-AI-008: Implementation Plan

## Technical Approach (기술적 접근)

### 전체 아키텍처

```
[APScheduler Job (30min)]
      │
      ▼
[forum_crawler.crawl_all_stocks()]
      │
      ▼ httpx GET (1 req / 3s)
[finance.naver.com/item/board.nhn]
      │
      ▼ BeautifulSoup parse
[StockForumPost (raw)]
      │
      ▼ hourly aggregation
[StockForumHourly (aggregated)] ──► fund_manager._gather_forum_sentiment()
```

### 크롤링 전략

- **URL 패턴**: `https://finance.naver.com/item/board.nhn?code={stock_code}&page={page}`
- **페이지 수**: 종목당 최대 3페이지 (약 60~90 posts) — 30분 간격이면 충분
- **User-Agent 로테이션**: 5개 UA 풀에서 랜덤 선택
- **Rate Limit**: `asyncio.sleep(3.0)` per stock (REQ-FORUM-008)
- **타임아웃**: `httpx.AsyncClient(timeout=10)` — 기존 패턴 준수

### 키워드 분류 (규칙 기반)

- **Bullish keywords**: `매수`, `올라`, `상승`, `돌파`, `급등`, `장대양봉`, `목표가`, `좋아`, `✅`, `🚀`
- **Bearish keywords**: `매도`, `내려`, `하락`, `손절`, `급락`, `음봉`, `별로`, `😭`, `📉`
- **중립(neutral)**: 위 어떤 키워드도 매칭되지 않는 경우
- **매칭 우선순위**: bullish 키워드가 하나라도 있으면 bullish (단순 우선 매칭)

### 집계 로직 (Hourly Aggregation)

- `bullish_ratio = bullish_count / total_posts` (total_posts == 0이면 0.0)
- `avg_7d_volume`: 지난 7일간 같은 시간대 `comment_volume`의 평균
- `volume_surge = comment_volume > 3 * avg_7d_volume` (REQ-FORUM-005)
- `overheating_alert`: 직전 1시간 + 현재 1시간 모두 `bullish_ratio > 0.80` (REQ-FORUM-004)

## Files to Create (신규 파일)

### 1. `backend/app/models/stock_forum.py`

두 개의 SQLAlchemy 2.0 모델 정의:

**StockForumPost** (원시 데이터):
```
id: int PK
stock_id: FK→stocks.id (indexed)
stock_code: str(6) (indexed)
content: str(200)     # 최초 200자만
nickname: str(50)
post_date: DateTime (indexed)
view_count: int
agree_count: int
disagree_count: int
sentiment: str(10)    # 'bullish' | 'bearish' | 'neutral'
created_at: DateTime
UNIQUE (stock_code, post_date, nickname)   # 중복 방지
```

**StockForumHourly** (집계 데이터) — @MX:ANCHOR 대상:
```
id: int PK
stock_id: FK→stocks.id (indexed)
aggregated_at: DateTime (indexed)
total_posts: int
bullish_count: int
bearish_count: int
neutral_count: int
bullish_ratio: float
comment_volume: int
avg_7d_volume: float
volume_surge: bool (default False)
overheating_alert: bool (default False)
created_at: DateTime
UNIQUE (stock_id, aggregated_at)
```

### 2. `backend/app/services/forum_crawler.py`

주요 함수 구조:

- `async def crawl_stock_forum(stock_code: str, pages: int = 3) -> list[dict]`
  - httpx로 N페이지 수집, BeautifulSoup으로 파싱
  - @MX:NOTE (rate limiting & UA rotation 규칙 명시)
  - @MX:WARN (Naver 차단 위험 — rate limit 준수 필수)

- `def classify_sentiment(content: str) -> str` — bullish/bearish/neutral 키워드 매칭

- `async def crawl_all_stocks() -> None` — 추적 대상 종목 전체 순회 (scheduler entry point)

- `def aggregate_hourly(stock_id: int, hour: datetime) -> StockForumHourly` — 시간 단위 집계

- `def detect_anomalies(hourly: StockForumHourly) -> StockForumHourly` — volume_surge / overheating_alert 플래그 설정

### 3. `backend/alembic/versions/048_stock_forum.py`

- `revision = "048"`
- `down_revision = "047"` (krx_short_selling 뒤)
- `stock_forum_posts` + `stock_forum_hourly` 두 테이블 생성
- 인덱스: `ix_forum_posts_stock_date`, `ix_forum_hourly_stock_aggregated`

## Files to Modify (수정 파일)

### 1. `backend/app/services/scheduler.py`

- `forum_crawl_job()` 함수 추가
  - `IntervalTrigger(minutes=30)`
  - 장 시간(09:00-18:00 KST, Mon-Fri) 체크 후 실행
  - 비장 시간에는 early return (REQ-FORUM-001)
- `BackgroundScheduler.add_job()` 에 등록

### 2. `backend/app/services/fund_manager.py`

- `async def _gather_forum_sentiment(stock_id: int) -> dict` 함수 추가
  - 최근 1시간 `StockForumHourly` 조회
  - 반환: `{bullish_ratio, volume_surge, overheating_alert, weight: 0.25}`
- 기존 시그널 조합 함수에서 이 dict를 **low weight (0.2~0.3)** 으로 합산
- `fund_manager` 종합 의사결정 로직에서 contrarian signal로 해석:
  - `overheating_alert=True` → 매수 강도 감소 (또는 매도 고려)
  - `bullish_ratio < 0.20 & volume_surge=True` → 반등 후보로 가점

## Milestones (Priority-Based, No Time Estimates)

### Milestone 1 (Priority: High) — 데이터 모델 & 마이그레이션
- `stock_forum.py` 모델 작성
- `048_stock_forum.py` alembic 마이그레이션
- 로컬 DB에서 마이그레이션 정상 동작 확인

### Milestone 2 (Priority: High) — 크롤러 구현
- `forum_crawler.py` 단일 종목 수집 함수 구현
- BeautifulSoup 파싱 안정성 검증 (HTML 구조 변경 대응)
- Rate limit 및 UA rotation 동작 확인

### Milestone 3 (Priority: Medium) — 집계 및 이상 탐지
- 시간 단위 aggregation 함수
- `volume_surge` / `overheating_alert` 플래그 로직
- 7일 평균 계산 시 데이터 부족 시 fallback 처리

### Milestone 4 (Priority: Medium) — 스케줄러 통합
- `scheduler.py`에 30분 주기 job 등록
- 장 시간 체크 로직
- Circuit breaker 연동 (REQ-FORUM-006)

### Milestone 5 (Priority: Low) — fund_manager 통합
- `_gather_forum_sentiment()` 구현
- 가중치 조정 및 contrarian signal 해석 로직
- 기존 fund_manager 테스트 회귀 검증

## Technical Risks (리스크 분석)

| 리스크 | 발생 가능성 | 영향도 | 완화 전략 |
|--------|-------------|--------|-----------|
| 네이버 HTML 구조 변경 | Medium | High | BeautifulSoup selector를 config 기반으로 분리, 파싱 실패 시 alert |
| IP 차단 | Medium | High | Rate limit 엄격 준수, UA rotation, circuit breaker |
| 키워드 매칭의 낮은 정확도 | High | Low | contrarian 용도이므로 정확도 요구사항 낮음 (가중치 0.2~0.3) |
| DB 부하 (추적 종목 * 60 posts/30min) | Low | Medium | 200자 제한, unique constraint로 중복 제거, 30일 retention policy (후속 SPEC) |
| 장시간 서비스 다운 시 누락 | Low | Low | 30분 주기이므로 과거 복구 불필요 |

## MX Tag Targets

- **`forum_crawler.crawl_stock_forum()`**: `@MX:NOTE` — Rate limiting rules, UA rotation rationale
- **`forum_crawler.crawl_stock_forum()`**: `@MX:WARN` — Naver 차단 위험, @MX:REASON 필수
- **`StockForumHourly` 모델**: `@MX:ANCHOR` — `fund_manager._gather_forum_sentiment()`의 핵심 의존 계약
- **`classify_sentiment()`**: `@MX:TODO` — 키워드 사전 확장 가능성 (후속 개선)

## Testing Strategy

- 단위 테스트: `classify_sentiment()`, `aggregate_hourly()`, `detect_anomalies()`
- 통합 테스트: 실제 Naver URL에 대한 smoke test (CI에서는 VCR/recorded response 사용)
- 회귀 테스트: `fund_manager` 기존 시그널 조합이 유지되는지 확인
