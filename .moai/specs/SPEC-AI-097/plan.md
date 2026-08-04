# SPEC-AI-097 Plan

## A. 구현 전략

Tier M, cycle_type: ddd(ANALYZE-PRESERVE-IMPROVE — `.moai/config/sections/quality.yaml`
`constitution.development_mode: ddd`). 범위는 "가격이력 조회의 HTTP 비용을 낮추는 메커니즘"에
한정하며, top-50 절단 정책·스캔 유니버스 배분·매수 실행 경로는 건드리지 않는다.

핵심 판단(결정 가역성이 높은 순 — 되돌리기 어려운 결정을 먼저 확정):

1. **[NEEDS CLARIFICATION: 로컬 영속 OHLCV 테이블 신설 여부(spec.md §Decisions D3)]** — 가장
   되돌리기 어려운 결정이다(신규 테이블은 마이그레이션 배포 후 롤백 비용이 크다). TASK-001
   사전조사에서 "운영 스캔 사이클(10:00/11:00대/15:20 KST 등)이 동일 장기실행 프로세스인지,
   매번 새 invocation인지"를 확인한 뒤, Implementation Kickoff Approval 단계에서 사용자와 함께
   다음 중 하나를 확정한다:
   - **Option A (기본 권장)**: 신규 테이블 없음. 기존 `_price_cache`(인메모리+Redis)를 pages
     인지형으로 확장(spec.md D2)하는 것으로 충분하다고 가정한다. 리스크: 스캔 사이클마다
     프로세스가 새로 뜬다면 인메모리 캐시가 매번 콜드스타트되어 Redis TTL(3600초)에만
     의존하게 된다 — Redis 가용성이 낮으면 이득이 줄어든다.
   - **Option B**: 신규 `SurgeStockPriceHistory`(가칭) 테이블을 신설하고, 하루 1회 배치로
     채운 뒤 스코어링 경로는 그 테이블만 읽는다. 스키마·마이그레이션·쓰기 경로 3종이 추가되어
     Tier가 M→L로 상향될 수 있다.
   - 본 SPEC은 Option A를 기본값으로 구현을 시작하되, TASK-001에서 발견한 사실이 Option B를
     강하게 지지하면 재계획(Re-planning Gate, `.claude/rules/moai/workflow/spec-workflow.md`
     § Re-planning Gate)한다.
2. 캐시 데이터 구조(`pages_fetched` 필드 추가, spec.md D2) — Option A/B 어느 쪽을 택하든 필요한
   공유 결정이므로 다음 순위.
3. 신규 배치 함수의 내부 구현 세부(스레드 풀 크기, 락 전략)는 이후 조정 가능성이 높으므로 가장
   낮은 순위 — 결정 재검토 비용이 작다.

### A.5 PRESERVE 목록 (수정 금지)

| 대상 | 사유 |
|------|------|
| `fetch_current_prices_batch()`(naver_finance.py:1525) | SPEC-AI-016 소유, 매수 주문 실행 경로 — REQ-AI097-004 |
| `fetch_current_price_with_change()` | 현재가 스냅샷 전용, 가격이력과 무관 |
| `surge_trading_service.py` 전체 | 매수 주문 실행 — REQ-AI097-004 |
| `build_scan_universe()` 및 Pool A/B/C/D quota 로직(surge_detector.py:4580 부근) | SPEC-AI-065/076/086 소유 |
| `_MAX_PRICE_FETCH_CANDIDATES=50` 상수 및 사전필터 자체(surge_detector.py:2118) | 형제 SPEC 소관 — 본 SPEC은 값을 변경하지 않는다 |
| 8개 탐지기의 스코어링 알고리즘(가중치/임계값), `compute_ensemble_score` | 무관 — 데이터를 "가져오는 방법"만 변경 |

## B. 작업 분해

### TASK-001: 벌크 엔드포인트 존재 여부 + 프로세스 생명주기 사전조사 (코드 변경 없음)

- Naver `sise_day.naver` 및 이 코드베이스가 이미 사용 중인 다른 Naver 엔드포인트(현재가 API 등)
  중 다종목-한번에 조회를 지원하는 것이 있는지 실제 요청으로 확인한다.
- 운영 스캔 사이클(10:00/11:00대/15:20 KST 등, 크론/systemd 타이머 설정 확인)이 동일
  장기실행 프로세스인지, 매번 새 invocation인지 확인한다 — §A 항목 1(Option A/B 판단)의 핵심
  입력이다.
- 결과를 REQ-AI097-001 근거로 기록하고, §A 항목 1의 Option A/B 판단에 반영한다.

추적 REQ/AC: REQ-AI097-001 / AC-097-001

### TASK-002: `_PriceHistoryCache`에 pages 인지형 판정 추가

- 대상: `naver_finance.py`의 `_PriceHistoryCache`, `fetch_stock_price_history_sync`,
  `fetch_stock_price_history`(async 버전도 동일 `_price_cache` 전역을 공유하므로 함께 반영).
- `pages_fetched: dict[str, int]`(또는 동등 필드) 추가, 히트 판정 조건에
  `cached_pages >= requested_pages`를 추가한다.
- 기존 TTL 판정(`_cache_ttl()`)은 무수정 — 신규 조건은 기존 조건에 AND로 결합한다.

추적 REQ/AC: REQ-AI097-003 / AC-097-002, AC-097-003

### TASK-003: 가격이력 동시조회 배치 함수 신설

- 대상: `naver_finance.py` 신규 함수(예: `fetch_stock_price_history_batch_sync`).
- `concurrent.futures.ThreadPoolExecutor` 기반, `batch_size`/`delay_sec` 파라미터화(기본값은
  `fetch_current_prices_batch`와 동일 스타일 참고, 구현 시 확정).
- 개별 실패 격리(예외 전파 금지, 실패 종목은 빈 리스트로 결과에 포함).
- 여러 스레드가 동시에 `_price_cache`(공유 dict, TASK-002가 확장한 구조체)를 읽고/쓰고/축출할
  때의 경합 조건을 `threading.Lock` 또는 "스레드는 결과만 반환하고 캐시 갱신은 메인 스레드가
  일괄 수행" 중 하나로 제거한다 — `asyncio.gather` 기반 동시성(단일 스레드 협조적 스케줄링)과
  달리 `ThreadPoolExecutor`는 진짜 OS 스레드이므로 이 문제가 새로 발생한다는 점에 주의한다.

추적 REQ/AC: REQ-AI097-002 / AC-097-004, AC-097-007

### TASK-004: `surge_detector.py` 최소 1개 호출부 전환

- 대상: spec.md §Context 표의 호출부 중 1개 이상. 권장: `detect_volume_breakout`
  (surge_detector.py:4335 부근)의 유니버스 순회 — 이미 `fetch_volume_leaders_sync`로 유니버스가
  명확히 구획되어 배치 전환 이득이 크고 회귀 범위가 좁다.
- 전환 대상 함수는 여전히 `def`(동기) 시그니처를 유지한다 — 신규 배치 함수 자체가 동기이므로
  상위 호출자를 async로 바꿀 필요가 없다(spec.md D1).

추적 REQ/AC: REQ-AI097-002 / AC-097-004, AC-097-005

### TASK-005: 측정 로깅 추가

- 대상: 신규 배치 함수 및/또는 TASK-004 전환 지점.
- HTTP 호출 수(캐시 히트 제외) + 조회 단계 소요 시간(초)을 기존 로그 라인 패턴을 확장해
  기록한다(spec.md D4 — 신규 관측 인프라 도입 없음).

추적 REQ/AC: REQ-AI097-005 / AC-097-006

### TASK-006: 무회귀 검증

- 대상: `backend/tests/test_naver_finance.py`(신규 또는 기존 확장), TASK-004 전환 대상
  탐지기의 기존 테스트.
- `fetch_current_prices_batch()` / `surge_trading_service.py` diff 0 확인(REQ-AI097-004).
- 전체 회귀 스위트 무회귀 확인.

추적 REQ/AC: REQ-AI097-001~005 전체 / AC-097-001~008

## C. 검증 계획

타겟 테스트:

```powershell
cd backend; uv run pytest tests/test_naver_finance.py -q
cd backend; uv run pytest tests/test_spec_ai_062.py tests/test_spec_ai_066.py tests/test_spec_ai_072.py -q
```

전체 회귀(CLAUDE.local.md 권장 명령):

```bash
cd backend && uv run pytest tests/ --tb=short -q -m "not slow"
```

정적 검사:

```bash
cd backend && uv run ruff check . && uv run mypy app/
```

임포트 sanity:

```bash
cd backend && uv run python -c "from app.main import app; print('OK')"
```

## D. 배포/롤백

Option A(기본 경로) 채택 시 신규 DB 마이그레이션이 없으므로 배포 자체의 롤백 비용은 낮다 —
`naver_finance.py`의 신규 함수와 `_PriceHistoryCache` 확장, `surge_detector.py`의 1개 호출부
전환만 되돌리면 이전 동작으로 완전히 복귀한다.

롤백 트리거:

- TASK-004에서 전환한 탐지기(`detect_volume_breakout` 등)의 신호 생성 결과가 순차 방식 대비
  달라지는 사례 발견(REQ-AI097-002 위반 신호 — 즉시 조사).
- 신규 배치 함수 도입 후 Naver 측 레이트리밋(HTTP 429 등) 증가 관측(배치 크기/딜레이 파라미터
  재조정 또는 롤백).
- `_price_cache` 동시쓰기 경합으로 인한 예외(`RuntimeError: dictionary changed size during
  iteration` 등) 발견 시 즉시 TASK-003으로 롤백.

Option B(신규 테이블)를 선택하게 될 경우, 그 시점에 별도 마이그레이션 롤백 절차를 plan.md에
추가한다(본 SPEC은 그 절차를 지금 정의하지 않는다 — §A 항목 1 결정 보류).

## E. 리스크

- **`_price_cache` 동시쓰기 경합**: `ThreadPoolExecutor`는 진짜 OS 스레드를 사용하므로, 기존의
  "확인 후 쓰기"(check-then-act) 캐시 접근 패턴이 여러 스레드에서 동시에 실행되면 경합 조건이
  발생할 수 있다. TASK-003의 락/일괄갱신 설계가 유일한 방어선이다(AC-097-007).
- **Naver 레이트리밋**: 동시 조회 배치 크기를 과도하게 키우면 `fetch_current_prices_batch`가
  이미 겪었던 레이트리밋 문제(batch_size=10, delay=0.5초로 완화)를 가격이력 조회에서도 재현할
  수 있다. 신규 함수의 기본 파라미터는 `fetch_current_prices_batch`의 검증된 값을 참고한다.
- **pages 인지형 캐시가 여전히 프로세스 재시작을 넘어서지 못하는 위험**: TASK-002/003은
  인메모리 캐시를 개선할 뿐, 프로세스가 스캔 사이클마다 재시작된다면 그 개선의 체감 효과가
  작을 수 있다 — TASK-001의 프로세스 생명주기 조사 결과가 이 리스크의 실제 크기를 결정한다.
- **existing_codes 항목과 무관하지만 인접 파일을 공유**: `surge_detector.py`는 다른 형제 SPEC들
  (top-50 정책 SPEC 등)과 동일 파일을 대상으로 하므로, 병렬 세션 작업 시
  `.claude/rules/moai/core/agent-common-protocol.md` § Pre-Spawn Sync Check를 run-phase
  진입 전 반드시 수행해야 한다(파일 충돌 방지).
