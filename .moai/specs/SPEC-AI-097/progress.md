# SPEC-AI-097 Progress

## §E.1 Plan-phase Audit-Ready Signal

```yaml
plan_status: audit-ready
plan_complete_at: 2026-08-04
plan_audit_verdict: PASS
plan_audit_score: 0.94
plan_audit_iteration: 1
plan_audit_report: .moai/reports/plan-audit/SPEC-AI-097-review-1.md
```

plan-auditor 1차 심사 PASS(0.94, Tier M 임계값 0.80 이상). MP-1~MP-7 전원 PASS/N/A,
BLOCKING 결함 없음. Category Scores: Clarity 0.90 / Completeness 1.0 / Testability 0.95 /
Traceability 1.0. 사용자가 Implementation Kickoff Approval을 통해 run-phase 진입을
승인함(D3 Option A 기본값 채택 확인 포함).

## §E.2 Run-phase Evidence

### TASK-001 — 벌크 엔드포인트 조사 + 프로세스 생명주기 (REQ-AI097-001 / AC-097-001)

- **벌크 엔드포인트 결론**: 가격이력(`sise_day.naver?code={code}&page={page}`)은 종목당
  단일 코드 파라미터만 지원 — 진짜 벌크(다종목-1요청) 엔드포인트 없음
  (`backend/app/services/naver_finance.py:374` `SISE_DAY_URL`).
  대조: 현재가/펀더멘털(`polling.finance.naver.com/api/realtime?query=SERVICE_ITEM:{code},...`)
  은 콤마 조인으로 최대 50개/요청 진짜 벌크를 지원하며, 이미
  `fetch_stock_fundamentals_batch()`(`naver_finance.py:522`)가 사용 중 — 가격이력과는
  무관한 별도 엔드포인트임을 확인. `fetch_current_prices_batch()`(SPEC-AI-016)는
  동시성-배치(asyncio.gather)이지 진짜 벌크가 아님을 재확인.
- **프로세스 생명주기**: `backend/app/services/scheduler.py`는 `BackgroundScheduler`
  (APScheduler)를 FastAPI/uvicorn과 동일한 단일 장기 실행 프로세스 내에서 구동
  (`scheduler.py:8,28`). 급등 스캔 사이클(10:00/11:00대/15:20 KST)은 매번 새
  invocation이 아니라 동일 프로세스의 스레드 풀 잡으로 실행됨 — 인메모리 `_price_cache`는
  스캔 사이클 간에 지속되며 배포/재시작 시에만 콜드스타트.
- **결론**: 위 두 사실이 plan.md §A 항목1의 **Option A(신규 테이블 없음, 기존
  `_price_cache` pages 인지형 확장으로 충분)** 채택 근거를 뒷받침함.

### TASK-002~005 구현 요약

| TASK | 대상 | 요약 |
|------|------|------|
| TASK-002 | `naver_finance.py` `_PriceHistoryCache` | `pages_fetched: dict[str, int]` 필드 추가, `is_fresh_hit()` 헬퍼로 TTL AND pages 판정 통합. `fetch_stock_price_history_sync`/`fetch_stock_price_history`(async) 양쪽에 적용, Redis 복구 경로는 pages 미기록(안전한 미스 방향) |
| TASK-003 | `naver_finance.py` `fetch_stock_price_history_batch_sync` (신규) | `ThreadPoolExecutor` 기반, 배치당 `batch_size`개 동시 조회 + 배치 간 `delay_sec` 대기. 워커는 `fetch_stock_price_history_sync`를 그대로 호출(중복 구현 없음, 기존 mock 호환성 유지) — 입력 dedup으로 두 스레드가 동일 캐시 키를 동시에 쓰지 않도록 보장(락 불필요) |
| TASK-004 | `surge_detector.py` `detect_volume_breakout` | 유니버스 순회 내 개별 `fetch_stock_price_history_sync` 호출을 루프 진입 전 1회 `fetch_stock_price_history_batch_sync` 호출로 전환 |
| TASK-005 | `fetch_stock_price_history_batch_sync` 내부 | 캐시히트/HTTP조회 종목 수 + 소요시간(초)을 `logger.info("[가격이력배치] ...")`로 기록 |

## §E.3 Run-phase Audit-Ready Signal

```yaml
run_status: audit-ready
run_complete_at: 2026-08-04
ac_pass_count: 7
ac_should_pass_count: 1
preserve_list_diff: 0
new_test_files: 1
regression_suite: 2304 passed, 4 skipped, 3 xpassed, 0 failed
```

### AC PASS/FAIL 매트릭스

| AC ID | 상태 | 검증 명령 | 결과 |
|-------|------|-----------|------|
| AC-097-001 | PASS | 코드 리뷰(§E.2 TASK-001) | 벌크 엔드포인트 부재 결론 + fetch_current_prices_batch와 구분 기록 완료 |
| AC-097-002 | PASS | `uv run pytest tests/test_spec_ai_097.py::TestPagesAwareCacheHit::test_insufficient_pages_forces_refetch -q` | `PASS` |
| AC-097-003 | PASS | `uv run pytest tests/test_spec_ai_097.py::TestPagesAwareCacheHit::test_sufficient_pages_skips_refetch -q` | `PASS` |
| AC-097-004 | PASS | `uv run pytest tests/test_spec_ai_097.py::TestBatchFetchConcurrency -q` | `4 passed` |
| AC-097-005 | PASS | `uv run pytest tests/test_surge_ai066.py -q` (기존 characterization, 무수정) | `40 passed` |
| AC-097-006 | PASS | `uv run pytest tests/test_spec_ai_097.py::TestPerformanceLogging -q` | `PASS` |
| AC-097-007 | PASS | `uv run pytest tests/test_spec_ai_097.py::TestBatchFetchConcurrency::test_batch_stress_no_cache_corruption -q` (20회 반복 스트레스) | `PASS` |
| AC-097-008 | PASS | `git diff --name-only \| grep -E 'surge_trading_service\.py'` | 매치 0건(exit 1) |

### PRESERVE 목록 검증 (plan.md §A.5)

| 대상 | Before/After diff |
|------|--------------------|
| `fetch_current_prices_batch()` (naver_finance.py:1522+) | 0 — 파일 diff에 해당 함수 라인 미포함 확인 |
| `fetch_current_price_with_change()` | 0 — 미접촉 |
| `surge_trading_service.py` 전체 | 0 — `git diff --name-only` 미포함(grep exit 1) |
| `build_scan_universe()` / Pool A/B/C/D quota | 0 — 미접촉 |
| `_MAX_PRICE_FETCH_CANDIDATES=50` 상수 | 0 — 미접촉 |
| 8개 탐지기 스코어링 알고리즘 / `compute_ensemble_score` | 0 — `detect_volume_breakout`은 데이터 조회 방식만 변경, 스코어링 로직(ratio/breakout_score 계산) 불변 |

### 전체 회귀 스위트

```
$ uv run pytest tests/ --tb=short -q -m "not slow"
2304 passed, 4 skipped, 3 xpassed, 259 warnings in 195.46s
```

기존 `tests/test_surge_ai067.py::TestPriceHistoryCacheTTL::test_market_closed_uses_long_ttl`
1건이 최초 실행에서 실패 → 원인 진단: 해당 테스트가 `pages_fetched` 필드 없이 캐시를
직접 채우던 레거시 픽스처였고, acceptance.md §D Edge Case("pages_fetched 없는 레거시
상태는 항상 미스 처리")에 따라 의도된 동작. 테스트 픽스처에 `pages_fetched["TTLTEST"]=1`
1줄을 추가해 AC-8.2(TTL 판정 자체, SPEC-AI-097 무관 영역)의 검증 의도를 보존한 뒤
재실행 → 전량 통과.

### 정적 검사

```
$ uv run ruff check app/services/naver_finance.py app/services/surge_detector.py tests/test_spec_ai_097.py tests/test_surge_ai067.py
All checks passed!

$ uv run python -c "from app.main import app; print('OK')"
OK
```

**Gap**: `uv run mypy app/` — 이 환경에 mypy가 설치되어 있지 않음(`No module named mypy`).
mypy 검증은 이 세션에서 수행하지 못함(환경 제약, 코드 변경과 무관).

## §E.4 Sync-phase Audit-Ready Signal

```yaml
sync_status: audit-ready
sync_complete_at: 2026-08-04
sync_commit_sha: pending-backfill-sync
changelog_entry_position: after-header-before-SPEC-AI-100
frontmatter_status_transitions:
  spec_md: "in-progress -> completed"
```

- **CHANGELOG.md**: `[Unreleased]` 섹션에 SPEC-AI-097 항목 추가(REQ 5개, AC 8개
  전량 PASS 요약). 사전 중복 검사(`grep -c 'SPEC-AI-097' CHANGELOG.md`) 0건 확인 후
  삽입.
- **AC count 대조**: `acceptance.md`(SSOT) `### AC-097-` 헤딩 8개 ↔ progress.md
  §E.3 AC 매트릭스 8개 ↔ CHANGELOG 서술 8개 — 일치 확인.
- **파일 경로 검증**: CHANGELOG에 인용된 4개 파일(`naver_finance.py`,
  `surge_detector.py`, `test_spec_ai_097.py`, `test_surge_ai067.py`) 전부
  `ls` 존재 확인 완료.
- **README.md**: 이번 SPEC은 사용자 대면 기능/버전/배지 변경이 없어(내부 성능
  메커니즘 개선) 갱신 불필요로 판단.
- **spec.md frontmatter**: `status: in-progress` → `status: completed`,
  `updated: 2026-08-04` 갱신(이 sync 커밋에서 병합 3단계 종료).
- **PRESERVE-list 재확인**: §E.3에서 이미 검증된 6개 대상 diff 0(변경 없음) — sync
  단계에서 추가 접촉 없음.
- **B12 self-test 결과**: (1) pre-emission grep 0건 통과, (2) AC count 일치(8=8=8),
  (3) 파일 경로 4/4 검증 완료.
