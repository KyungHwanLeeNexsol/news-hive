---
id: SPEC-AI-008
version: 1.0.0
status: completed
created: 2026-04-14
updated: 2026-04-14
author: Nexsol
priority: Medium
issue_number: 0
---

# SPEC-AI-008: 네이버 종토방 크롤러 및 이상 활성화 탐지

## HISTORY

| Date       | Version | Author | Change                        |
| ---------- | ------- | ------ | ----------------------------- |
| 2026-04-14 | 1.0.0   | Nexsol | 초안 작성 (Initial draft)     |

## Overview (개요)

네이버 금융 종목토론방(종토방)에서 각 종목별 게시글을 수집하고, 감성 키워드 기반 규칙으로 집계하여 **이상 활성화(Abnormal Activity)** 를 탐지하는 시스템을 구축한다. 종토방 데이터는 직접적인 매수 시그널이 아닌 **역지표/이상 징후(contrarian/anomaly indicator)** 로 활용한다.

### 설계 원칙 (Design Rationale)

- 종토방은 개인 투자자 심리의 reflection이지 독립적 정보원천이 아니다
- 과열(극단적 낙관)은 매도 경계 신호, 극단적 비관은 반등 후보 신호로 해석
- AI 분류는 비용 부담이 크므로 **규칙 기반 키워드 매칭**으로 대체
- `fund_manager`에서의 가중치는 낮게 유지 (0.2~0.3 vs 뉴스 1.0)

## Requirements (EARS Format)

### Ubiquitous Requirements (항시 동작)

- **REQ-FORUM-001**: The system **shall** crawl Naver 종토방 posts for each tracked stock every 30 minutes during market hours (09:00-18:00 KST weekdays).

- **REQ-FORUM-002**: The system **shall** store per-post data with the following fields: `stock_code`, `content` (first 200 chars), `nickname`, `post_date`, `view_count`, `agree_count`, `disagree_count`.

- **REQ-FORUM-003**: The system **shall** compute hourly aggregated metrics including: `total_posts`, `bullish_count`, `bearish_count`, `neutral_count`, `bullish_ratio`, `comment_volume`, `avg_7d_volume`.

### Event-Driven Requirements (이벤트 기반)

- **REQ-FORUM-004**: **When** `bullish_ratio` exceeds 80% for 2 consecutive hours, **the system shall** flag `overheating_alert = True`.

- **REQ-FORUM-005**: **When** `comment_volume` exceeds 3x the 7-day average, **the system shall** flag `volume_surge = True`.

### Unwanted Behavior Requirements (금지 동작)

- **REQ-FORUM-006**: **If** 5 consecutive fetch failures occur for the same stock, **then the system shall** invoke `circuit_breaker.record_failure("naver_forum")` and pause crawling for that stock for 120 seconds before retrying.

- **REQ-FORUM-007**: The system **shall not** use browser automation tools (Playwright, Selenium, Puppeteer). Crawling **shall** use only `httpx` + `BeautifulSoup`.

### State-Driven Requirements (상태 기반)

- **REQ-FORUM-008**: **While** crawling is active, **the system shall** rate-limit requests to **1 request per 3 seconds per stock** to avoid Naver IP blocking.

## Exclusions (What NOT to Build)

명시적으로 본 SPEC 범위에서 제외되는 항목:

1. **개별 게시글 AI 감성 분류**
   - 이유: OpenAI/Gemini API 호출 비용(배치당 수백~수천 건) 대비 ROI 부족
   - 대체: 규칙 기반 키워드 매칭(bullish/bearish keyword list)

2. **실시간 WebSocket 스트리밍**
   - 이유: 30분 주기 배치로 충분 (종토방 데이터는 노이즈가 많아 실시간성 가치 낮음)
   - 대체: APScheduler interval job (30min)

3. **네이버 로그인/인증 기반 수집**
   - 이유: 계정 차단 위험 및 ToS 위반 가능성
   - 대체: 비로그인 공개 페이지만 수집

4. **게시글 전문(full content) 저장**
   - 이유: DB 용량 부담 및 저작권 이슈
   - 대체: 최초 200자만 저장 (키워드 탐지에 충분)

5. **댓글/대댓글 수집**
   - 이유: 크롤링 비용 대비 정보 가치 낮음
   - 대체: 원글 단위 집계

6. **타 커뮤니티 크롤링 (디시, 팍스넷, 증권플러스 등)**
   - 이유: 본 SPEC은 네이버 종토방 한정 (타 소스는 별도 SPEC으로 분리)

## Constitution Alignment

- **Tech Stack**: Python 3.12+, SQLAlchemy 2.0, httpx, BeautifulSoup4, APScheduler — 기존 스택 준수
- **Forbidden Libraries**: Playwright/Selenium 사용 금지 (REQ-FORUM-007)
- **Architectural Pattern**: 기존 crawler 패턴 준수 (`backend/app/services/crawlers/`)
- **Error Handling**: `circuit_breaker.record_failure()` 통합 (기존 패턴)

## Related SPECs

- **SPEC-AI-003**: `fund_manager.py` 선행 기술 탐지기 — 종토방 시그널을 입력으로 추가
- **SPEC-AI-004**: 공시 기반 선제적 시그널 — 유사한 contrarian signal 패턴 참고
- **SPEC-NEWS-001/002**: 뉴스 크롤러 — httpx + BeautifulSoup 패턴 재사용

## Success Criteria

- 100개 추적 종목에 대해 30분마다 안정적으로 수집
- 수집 실패율 < 5% (주간 평균)
- `overheating_alert` 및 `volume_surge` 플래그가 `fund_manager`에서 참조 가능
- Naver IP 차단 없이 연속 7일 운영
