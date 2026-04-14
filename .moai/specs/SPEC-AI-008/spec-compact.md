# SPEC-AI-008 (Compact) — 네이버 종토방 크롤러 및 이상 활성화 탐지

**Status**: draft | **Priority**: Medium | **Created**: 2026-04-14

## Requirements (EARS)

- **REQ-FORUM-001**: System SHALL crawl Naver 종토방 posts for each tracked stock every 30 minutes during market hours (09:00-18:00 KST weekdays).
- **REQ-FORUM-002**: System SHALL store per-post data: `stock_code`, `content` (first 200 chars), `nickname`, `post_date`, `view_count`, `agree_count`, `disagree_count`.
- **REQ-FORUM-003**: System SHALL compute hourly aggregated metrics: `total_posts`, `bullish_count`, `bearish_count`, `neutral_count`, `bullish_ratio`, `comment_volume`, `avg_7d_volume`.
- **REQ-FORUM-004**: WHEN `bullish_ratio` exceeds 80% for 2 consecutive hours, THEN system SHALL flag `overheating_alert = True`.
- **REQ-FORUM-005**: WHEN `comment_volume` exceeds 3x the 7-day average, THEN system SHALL flag `volume_surge = True`.
- **REQ-FORUM-006**: IF 5 consecutive failures occur, THEN system SHALL call `circuit_breaker.record_failure("naver_forum")` and pause 120 seconds.
- **REQ-FORUM-007**: System SHALL NOT use browser automation (Playwright/Selenium). Use `httpx` + `BeautifulSoup` only.
- **REQ-FORUM-008**: System SHALL rate limit to 1 request per 3 seconds per stock.

## Acceptance Scenarios (Given-When-Then)

1. **정상 크롤링**: Given valid stock code `005930`, When `crawl_stock_forum("005930", pages=3)` runs, Then `StockForumPost` records are saved with non-null `content` (≤200 chars) and `post_date` within last 7 days.
2. **과열 경고**: Given 100 posts with 85 bullish + previous hour also >0.80, When `aggregate_hourly` runs, Then `overheating_alert = True` and `bullish_ratio ≈ 0.85`.
3. **댓글 급증**: Given `comment_volume = 500` and `avg_7d_volume = 100`, When `detect_anomalies` runs, Then `volume_surge = True` (500 > 3×100).
4. **Circuit Breaker**: Given Naver returns 403 five times consecutively, When crawler retries, Then `circuit_breaker.record_failure("naver_forum")` is called and crawling pauses 120s.
5. **장 시간 외 스킵**: Given current time = 20:00 KST, When scheduler triggers `forum_crawl_job`, Then crawl is skipped and "outside market hours" log is written.

## Files to Create

- `backend/app/models/stock_forum.py` — `StockForumPost` + `StockForumHourly` models
- `backend/app/services/forum_crawler.py` — httpx + BeautifulSoup based crawler
- `backend/alembic/versions/048_stock_forum.py` — migration (revision="048", down_revision="047")

## Files to Modify

- `backend/app/services/scheduler.py` — add `forum_crawl_job` (30min interval, market hours gate)
- `backend/app/services/fund_manager.py` — add `_gather_forum_sentiment()` with weight 0.2~0.3 (contrarian signal)

## Keyword Classification (Rule-based, no AI)

- **Bullish**: 매수, 올라, 상승, 돌파, 급등, 장대양봉, 목표가, 좋아, ✅, 🚀
- **Bearish**: 매도, 내려, 하락, 손절, 급락, 음봉, 별로, 😭, 📉
- **Neutral**: 위 키워드 미매칭

## Exclusions (What NOT to Build)

- 개별 게시글 AI 감성 분류 (배치 비용 부담)
- 실시간 WebSocket 스트리밍 (30분 배치로 충분)
- 네이버 로그인 기반 수집 (계정 차단 위험)
- 게시글 전문 저장 (200자 제한)
- 댓글/대댓글 수집 (비용 대비 가치 낮음)
- 타 커뮤니티 크롤링 (별도 SPEC 분리)

## MX Tag Targets

- `forum_crawler.crawl_stock_forum()` → @MX:NOTE (rate limit rules) + @MX:WARN (Naver 차단 위험, @MX:REASON 필수)
- `StockForumHourly` model → @MX:ANCHOR (fund_manager core dependency)
- `classify_sentiment()` → @MX:TODO (keyword 사전 확장 가능성)

## Success Criteria

- 100개 추적 종목에 대해 30분마다 안정적으로 수집
- 수집 실패율 < 5% (주간 평균)
- `fund_manager`에서 종토방 시그널을 low weight (0.2~0.3) contrarian indicator로 참조
- Naver IP 차단 없이 연속 7일 운영
