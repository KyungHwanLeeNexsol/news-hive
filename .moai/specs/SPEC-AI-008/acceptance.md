# SPEC-AI-008: Acceptance Criteria

## Definition of Done (완료 기준)

- 모든 EARS 요구사항(REQ-FORUM-001 ~ 008)이 코드로 구현되고 테스트로 검증됨
- 아래 Given-When-Then 시나리오 5개 모두 자동화 테스트로 통과
- Alembic 마이그레이션(048) 이 up/down 양방향 정상 동작
- 추적 종목 100개에 대해 연속 24시간 운영 시 수집 실패율 < 5%
- `fund_manager`가 `StockForumHourly`를 참조하여 시그널 조합에 반영

---

## Test Scenarios (Given-When-Then)

### Scenario 1: 정상 크롤링 및 저장

**Given** 유효한 종목 코드 `005930` (삼성전자)이 추적 대상에 등록되어 있고,
**Given** 네이버 종토방 URL이 정상 응답(200 OK)을 반환할 때,

**When** `forum_crawler.crawl_stock_forum("005930", pages=3)` 이 호출되면,

**Then** `StockForumPost` 테이블에 게시글 레코드가 1개 이상 저장되어야 한다
**And** 각 레코드의 `content` 필드는 NULL이 아니며 최대 200자 이하여야 한다
**And** 각 레코드의 `post_date`는 최근 7일 이내여야 한다
**And** `sentiment` 필드는 `'bullish'`, `'bearish'`, `'neutral'` 중 하나여야 한다

### Scenario 2: 과열 경고 탐지 (Overheating Alert)

**Given** 특정 시간대에 `StockForumPost` 100건이 존재하고,
**Given** 그중 85건의 content가 bullish 키워드(매수/급등/돌파 등)를 포함하며,
**Given** 직전 1시간에도 `bullish_ratio > 0.80` 이었을 때,

**When** `aggregate_hourly(stock_id, current_hour)` 가 실행되면,

**Then** 생성된 `StockForumHourly` 레코드에서 `bullish_ratio`는 약 0.85 (±0.01) 여야 한다
**And** `overheating_alert` 는 `True` 여야 한다
**And** `total_posts == 100`, `bullish_count == 85` 여야 한다

### Scenario 3: 댓글량 급증 탐지 (Volume Surge)

**Given** 현재 시간대의 `comment_volume == 500` 이고,
**Given** 지난 7일간 같은 시간대의 `avg_7d_volume == 100` 일 때,

**When** `detect_anomalies(hourly)` 가 호출되면,

**Then** `volume_surge` 는 `True` 여야 한다 (500 > 3 × 100)
**And** `avg_7d_volume` 는 100.0으로 기록되어야 한다

### Scenario 4: Circuit Breaker 작동 (연속 실패 시 차단)

**Given** 네이버 종토방이 연속 5회 HTTP 403 Forbidden을 반환하는 상태일 때,

**When** `crawl_stock_forum("005930")` 이 재시도 로직에 따라 5회 연속 실패하면,

**Then** `circuit_breaker.record_failure("naver_forum")` 이 정확히 1회 호출되어야 한다
**And** 해당 provider_key에 대한 크롤링은 120초 동안 일시 중단되어야 한다
**And** 120초가 경과한 후에야 다음 크롤링 시도가 가능해야 한다

### Scenario 5: 장 시간 외 스케줄러 스킵

**Given** 현재 시각이 KST 20:00 (장 종료 후)이고,
**Given** `forum_crawl_job()` 이 스케줄러에 의해 트리거될 때,

**When** `forum_crawl_job()` 이 장 시간 체크 로직을 수행하면,

**Then** 실제 크롤링은 실행되지 않고 early return 되어야 한다
**And** 로그에 "Skipped: outside market hours" 메시지가 기록되어야 한다
**And** `StockForumPost` 테이블에 신규 레코드가 추가되지 않아야 한다

---

## Edge Cases (경계 조건)

### EC-1: 빈 게시판
- **상황**: 신규 상장 종목 등 게시글이 0건인 경우
- **기대 동작**: `total_posts = 0`, `bullish_ratio = 0.0`, 모든 alert 플래그 `False`
- **예외 발생 금지**: ZeroDivisionError 방지

### EC-2: 7일 이력 부족
- **상황**: 신규 등록 후 3일밖에 지나지 않아 `avg_7d_volume` 계산 불가
- **기대 동작**: 사용 가능한 데이터 평균으로 fallback, `volume_surge = False` 강제

### EC-3: HTML 구조 변경으로 파싱 실패
- **상황**: 네이버가 DOM 구조를 변경하여 BeautifulSoup selector가 매칭 실패
- **기대 동작**: 파싱 실패를 에러 로그 + alert, `circuit_breaker` 작동, 부분 수집분은 저장하지 않음

### EC-4: 주말/공휴일
- **상황**: 토요일/일요일 또는 한국 증시 휴장일
- **기대 동작**: 평일 여부 체크 로직에서 조기 종료 (Scenario 5와 동일 패턴)

### EC-5: 중복 게시글
- **상황**: 같은 종목의 같은 게시글이 여러 페이지 크롤링 과정에서 중복 수집
- **기대 동작**: UNIQUE 제약(`stock_code`, `post_date`, `nickname`)으로 DB 레벨 중복 차단

### EC-6: 200자 초과 content
- **상황**: 원본 게시글이 200자를 초과하는 경우
- **기대 동작**: 최초 200자까지만 저장, 말줄임 없이 단순 truncate

---

## Quality Gate Criteria

### 테스트 커버리지

- `forum_crawler.py`: 단위 테스트 커버리지 ≥ 85%
- `stock_forum.py` 모델: 기본 CRUD 테스트 포함
- 집계 함수(`aggregate_hourly`, `detect_anomalies`): 100% 커버리지

### 성능 기준

- 단일 종목 크롤링 완료 시간: ≤ 15초 (3페이지, rate limit 포함)
- 100개 종목 전체 크롤링: ≤ 10분 (3초 간격 직렬 기준)
- DB 삽입 쿼리: 배치 insert 사용, 단일 종목당 < 500ms

### 안정성 기준

- 연속 7일 운영 중 수집 실패율 < 5%
- Naver IP 차단 0회
- Circuit breaker 작동 후 자동 복구 100%

### 코드 품질 (TRUST 5)

- **Tested**: 5개 Given-When-Then 시나리오 자동화
- **Readable**: 함수명/변수명 영어, docstring 한글 허용
- **Unified**: `ruff` / `black` 포매팅 통과
- **Secured**: User-Agent 로테이션, IP 차단 방지 rate limit
- **Trackable**: Conventional commit 메시지, SPEC-AI-008 참조

---

## Manual Verification Steps (수동 검증 체크리스트)

배포 후 수동으로 확인할 항목:

- [ ] `alembic upgrade head` 후 `stock_forum_posts` / `stock_forum_hourly` 테이블 생성 확인
- [ ] `alembic downgrade -1` 으로 롤백 가능 확인
- [ ] 장 시간 중 30분 경과 후 `StockForumPost` 테이블에 신규 레코드 존재 확인
- [ ] 1시간 경과 후 `StockForumHourly` 테이블에 집계 레코드 존재 확인
- [ ] `fund_manager` 시그널 생성 API 호출 시 종토방 데이터 반영 확인
- [ ] 장 마감 후 스케줄러 로그에서 "Skipped: outside market hours" 메시지 확인
- [ ] 7일 연속 운영 후 `journalctl -u newshive`에서 에러 패턴 확인

---

## Rollback Plan (롤백 계획)

구현 후 문제 발생 시:

1. **긴급 중단**: `scheduler.py`에서 `forum_crawl_job` 비활성화 (즉시 반영)
2. **DB 롤백**: `alembic downgrade -1` 으로 048 → 047 복귀
3. **코드 롤백**: 해당 feature branch revert
4. **fund_manager 영향 최소화**: `_gather_forum_sentiment()` 가 없으면 해당 시그널은 0으로 처리되도록 defensive coding
