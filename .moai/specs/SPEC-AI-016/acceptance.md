---
id: SPEC-AI-016-acceptance
version: 1.0.0
status: draft
created: 2026-05-20
parent_spec: SPEC-AI-016
---

# SPEC-AI-016 수락 기준 체크리스트

> 본 문서는 SPEC-AI-016 "급등 탐지 정밀도 강화"의 모든 수락 기준을 Given-When-Then 형식으로 정리한 검증 체크리스트이다. 각 항목은 단위 테스트 또는 통합 테스트로 자동화되어야 한다.

---

## REQ-AI016-001: 앙상블 점수 임계값 상향 (0.20 → 0.45)

### AC-016-001-1: YAML 임계값 로드

- **Given** `backend/app/surge_config/surge_detection.yaml` 파일이 변경된 상태
- **When** `SurgeDetectionConfig.load()` 호출
- **Then** `config.ensemble.min_score_for_signal == 0.45`로 파싱됨
- **검증 수단**: `tests/test_surge_settings.py::test_min_score_threshold_045`

### AC-016-001-2: 임계값 미달 후보 제외

- **Given** weighted_sum = 0.40 (multiplier 적용 후 ensemble score = 0.40)인 합성 SurgeCandidate
- **When** `gather_surge_candidates()` 실행
- **Then** 결과 리스트에 해당 종목이 포함되지 않음
- **검증 수단**: `tests/test_surge_detector.py::test_gather_excludes_below_045`

### AC-016-001-3: 임계값 통과 후보 포함

- **Given** weighted_sum = 0.50인 합성 SurgeCandidate (active_detectors=2 → multiplier 1.15 적용 후 ≈ 0.575)
- **When** `gather_surge_candidates()` 실행
- **Then** 결과 리스트에 포함됨
- **검증 수단**: `tests/test_surge_detector.py::test_gather_includes_above_045`

### AC-016-001-4: 즉각 공시 이벤트 우회 회귀 보장

- **Given** `immediate_disclosure_score = 0.90`, `theme_cluster_score = 0.10`, `combo_score = 0.0`인 SurgeCandidate (앙상블 가중합 0.30 미만)
- **When** `gather_surge_candidates()` 실행
- **Then** `_IMMEDIATE_BYPASS_THRESHOLD = 0.70`에 의해 결과 리스트에 우회 포함됨
- **검증 수단**: `tests/test_surge_detector.py::test_immediate_bypass_regression`

### AC-016-001-5: 기존 하드코딩 임계값 0.20 갱신 회귀

- **Given** 기존 테스트들이 `min_probability=Decimal("0.20")` 등을 하드코딩한 케이스 존재
- **When** 전체 pytest 스위트 실행
- **Then** 모든 테스트가 새로운 0.45 임계값과 일관되게 통과 (또는 명시적으로 더 낮은 임계값 사용을 의도한 케이스는 그대로 유지)
- **검증 수단**: `cd backend && uv run pytest tests/ -m "not slow" --tb=short`

---

## REQ-AI016-002: 탐지기별 점수 분해 INFO 로그

### AC-016-002-1: 매수 완료 케이스 분해 로그

- **Given** SurgeCandidate(theme=0.30, volume=0.15, disclosure=0.05, immediate=0.0, legacy=0.0, 총점=0.52), 가격/한도 모두 정상
- **When** `execute_buy_orders()` 실행
- **Then** 정확히 1회 INFO 로그 출력: `[SURGE] 005930 executed score=0.520 | theme=0.300 volume=0.150 disclosure=0.050 immediate=0.000 legacy=0.000 | reason=ok`
- **검증 수단**: `tests/test_surge_trading_service.py::test_buy_log_breakdown_executed` (caplog)

### AC-016-002-2: 섹터 집중 스킵 분해 로그

- **Given** 동일 섹터 보유 카운트가 `max_same_sector=2`에 도달한 상태에서 동일 섹터 후보 추가 입력
- **When** `execute_buy_orders()` 실행
- **Then** INFO 로그: `[SURGE] {code} skipped score=... | theme=... | reason=sector_concentration`
- **검증 수단**: `tests/test_surge_trading_service.py::test_buy_log_breakdown_sector_concentration`

### AC-016-002-3: 가격 조회 실패 분해 로그

- **Given** 후보 종목의 `fetch_current_prices_batch` 결과가 None, 재시도도 실패
- **When** `execute_buy_orders()` 실행
- **Then** INFO 로그: `[SURGE] {code} failed score=... | theme=... | reason=price_unavailable`
- **검증 수단**: `tests/test_surge_trading_service.py::test_buy_log_breakdown_price_unavailable`

### AC-016-002-4: surge_metadata 결측 시그널 처리

- **Given** `signal.surge_metadata` is None인 시그널
- **When** 분해 로그 출력
- **Then** 모든 점수가 `0.000`으로 표기되고 예외 발생 없이 매수 평가 계속됨
- **검증 수단**: `tests/test_surge_trading_service.py::test_buy_log_metadata_missing`

### AC-016-002-5: 표시 정밀도 확인

- **Given** 임의의 SurgeCandidate
- **When** 분해 로그 출력
- **Then** 각 점수 컴포넌트가 소수점 3자리(`%.3f`)로 표시되며, 0.0 ≤ 값 ≤ 1.0 범위
- **검증 수단**: `tests/test_surge_trading_service.py::test_buy_log_precision`

---

## REQ-AI016-003: 포트폴리오 단위 섹터 비중 가드

### AC-016-003-1: 섹터 비중 초과 시 스킵

- **Given** 포트폴리오 상태:
  - 현금: 30,000,000원
  - 바이오 섹터 오픈 포지션 평가액 합계: 22,000,000원
  - 비바이오 섹터 오픈 포지션 평가액 합계: 0원
  - 총 평가액: 52,000,000원
  - 바이오 현재 비중: 22M / 52M ≈ 0.423
- **When** 새로운 바이오 종목 매수 시도 (예상 매수 금액 9,000,000원, 매수 후 비중 = 31M/52M ≈ 0.596)
- **Then** `skip_reason="sector_overweight"`로 스킵됨
- **검증 수단**: `tests/test_surge_trading_service.py::test_sector_overweight_blocks_buy`

### AC-016-003-2: 비보유 섹터는 정상 통과

- **Given** AC-016-003-1과 동일한 포트폴리오 상태
- **When** 광통신(보유 0) 섹터 종목 매수 시도
- **Then** 섹터 비중 가드를 정상 통과 (다른 가드는 별개 평가)
- **검증 수단**: `tests/test_surge_trading_service.py::test_sector_overweight_allows_new_sector`

### AC-016-003-3: 현재가 조회 실패 시 entry_price 폴백

- **Given** 바이오 보유 종목 3개 중 1개의 현재가 조회 실패
- **When** `_compute_sector_portfolio_pct("바이오")` 호출
- **Then** 실패 종목은 `entry_price × quantity`로 평가되어 계산 완료, 예외 발생 없음
- **검증 수단**: `tests/test_surge_trading_service.py::test_sector_pct_fallback_entry_price`

### AC-016-003-4: 섹터 비중 스킵 시 추가 로그 라인

- **Given** AC-016-003-1 시나리오
- **When** 스킵 발생
- **Then** INFO 로그 추가 라인: `[SURGE] {code} skipped reason=sector_overweight sector_pct=0.60 limit=0.40`
- **검증 수단**: `tests/test_surge_trading_service.py::test_sector_overweight_log_format`

### AC-016-003-5: 환경변수 오버라이드

- **Given** 환경변수 `SURGE_MAX_SECTOR_PORTFOLIO_PCT=0.50` 설정
- **When** `surge_settings.load()` 호출
- **Then** `MAX_SECTOR_PORTFOLIO_PCT == 0.50`로 적용됨
- **검증 수단**: `tests/test_surge_settings.py::test_max_sector_pct_env_override`

### AC-016-003-6: max_same_sector와 AND 결합

- **Given** 동일 섹터 보유 종목 1개 (max_same_sector=2 미달, 비중 0.50 초과)
- **When** 동일 섹터 신규 매수 시도
- **Then** 카운트 가드는 통과, 비중 가드가 발동하여 스킵 (어느 한 쪽이라도 발동하면 스킵)
- **검증 수단**: `tests/test_surge_trading_service.py::test_sector_guards_and_combined`

---

## REQ-AI016-004: 가격 조회 안정성 개선 (배치 + 지연)

### AC-016-004-1: 배치 분할 + 지연 호출

- **Given** 30개 종목 코드 입력, `batch_size=10`, `delay_sec=0.5`
- **When** `fetch_current_prices_batch(codes, 10, 0.5)` 실행
- **Then** 정확히 3개 배치로 분할되고 배치 간 `asyncio.sleep(0.5)`가 2회 호출됨 (마지막 배치 뒤 sleep 없음)
- **검증 수단**: `tests/test_naver_finance.py::test_batch_split_and_delay` (mock `asyncio.sleep`)

### AC-016-004-2: 부분 실패 격리

- **Given** 10개 종목 입력, 그 중 3개 종목이 API에서 None 반환
- **When** `fetch_current_prices_batch` 실행
- **Then** 결과 dict에 10개 키 모두 존재, 3개 None / 7개 정상 dict
- **검증 수단**: `tests/test_naver_finance.py::test_batch_partial_failure_isolation`

### AC-016-004-3: 재시도 후 최종 실패 스킵

- **Given** 후보 종목의 가격 조회가 1차/2차 모두 None
- **When** `execute_buy_orders` 평가 루프
- **Then** `skip_reason="price_unavailable"`로 스킵 + 분해 로그 출력 + 예외 없음
- **검증 수단**: `tests/test_surge_trading_service.py::test_price_retry_then_skip`

### AC-016-004-4: 50종목 50% 실패 시뮬레이션

- **Given** 50개 후보 종목, mock으로 25종목 가격 정상 / 25종목 None 반환
- **When** `execute_buy_orders` 전체 사이클 실행
- **Then** 결과 `executed + skipped + failed == 50` (다른 한도 가드 무시), `price_unavailable` 스킵 ≥ 25, 예외 0건
- **검증 수단**: `tests/test_surge_trading_service.py::test_50_stocks_half_price_failure`

### AC-016-004-5: 모든 가격 성공 시 회귀 보장

- **Given** 모든 후보의 가격 조회가 정상 (배치 도입 전과 동일 결과)
- **When** `execute_buy_orders` 실행
- **Then** 매수 결과(executed 종목 목록, 수량, 금액)가 기존 동작과 일치
- **검증 수단**: `tests/test_surge_trading_service.py::test_batch_query_regression_all_success`

### AC-016-004-6: 설정 키 노출 확인

- **Given** `surge_detection.yaml`에 `price_query.batch_size`, `price_query.batch_delay_sec`, `price_query.retry_count` 추가
- **When** `SurgeDetectionConfig.load()` 호출
- **Then** `config.price_query.batch_size == 10`, `batch_delay_sec == 0.5`, `retry_count == 1` 기본값 확인
- **검증 수단**: `tests/test_surge_settings.py::test_price_query_config_defaults`

---

## 통합 시나리오 (End-to-End)

### I-016-001: 80개 후보 + 가격 50% 실패

- **Given** 합성 80개 surge_candidate 후보, Naver mock 50% 실패율
- **When** 매수 사이클 1회 실행
- **Then**
  - `executed + skipped + failed == 80`
  - 예외 발생 0건
  - INFO 로그에 모든 80건의 분해 정보 출력
  - 가격 실패로 인한 스킵이 통계상 35~45건 범위 (재시도 효과 반영)
- **검증 수단**: `tests/test_surge_e2e.py::test_80_candidates_half_price_failure`

### I-016-002: 바이오 편중 포트폴리오

- **Given** 바이오 3종 보유(비중 0.45) + 신규 바이오 후보 5건 + 비바이오 후보 5건
- **When** 매수 사이클 실행
- **Then**
  - 바이오 후보 5건 전부 `sector_overweight` 스킵
  - 비바이오 후보 5건은 정상 평가 (다른 가드 별개)
- **검증 수단**: `tests/test_surge_e2e.py::test_biotech_concentration_e2e`

### I-016-003: 임계값 0.45 미달 후보 일괄 입력

- **Given** 50개 합성 후보, 모두 ensemble 점수 0.30 (즉각 공시 미발화)
- **When** `gather_surge_candidates` → `execute_buy_orders` 순서로 실행
- **Then** `gather_surge_candidates` 결과 0건, `execute_buy_orders` 실행 후보 0건
- **검증 수단**: `tests/test_surge_e2e.py::test_all_below_threshold_zero_candidates`

### I-016-004: 정상 분포 거래일 시뮬레이션

- **Given** 50개 후보, 점수 분포 0.20~0.70 (정규분포 mock)
- **When** 매수 사이클 실행
- **Then**
  - `gather_surge_candidates` 통과 ≤ 25건
  - 최종 매수 후보 ≤ 5건 (다른 한도 가드 반영)
  - INFO 로그에 통과 후보 전체 분해 출현
- **검증 수단**: `tests/test_surge_e2e.py::test_normal_distribution_day`

---

## 회귀 보장 체크리스트

| 항목 | 검증 |
|---|---|
| 기존 `tests/test_surge_detector.py` 모든 케이스 통과 | [ ] |
| 기존 `tests/test_surge_trading_service.py::check_exit_conditions` 케이스 통과 | [ ] |
| SPEC-AI-014 컨센서스 배율 테스트 통과 (1/2/3 detector → 1.00/1.15/1.30) | [ ] |
| `is_market_hours`, `is_buy_eligible_hours` 동작 미변경 | [ ] |
| `_IMMEDIATE_BYPASS_THRESHOLD = 0.70` 우회 동작 미변경 | [ ] |
| 손절/익절/만기 임계값 미변경 (-0.08 / 0.15 / 5일) | [ ] |
| DB 마이그레이션 없음 (FundSignal, SurgeTrade, SurgePortfolio 스키마 미변경) | [ ] |

---

## 품질 게이트 (TRUST 5)

| 게이트 | 기준 | 검증 명령 |
|---|---|---|
| **T**ested | 신규 코드 커버리지 ≥ 85% | `cd backend && uv run pytest tests/ --cov=app/services/surge_trading_service --cov=app/services/naver_finance --cov-report=term` |
| **R**eadable | 명명 규칙 + 함수 길이 | `cd backend && uv run ruff check .` |
| **U**nified | 포맷팅 일관 | `cd backend && uv run ruff format --check .` |
| **S**ecured | 신규 외부 호출 검증 (Naver API 응답) | mypy strict + 단위 테스트의 timeout/exception 케이스 |
| **T**rackable | 커밋 메시지 + SPEC 참조 | `feat(surge): SPEC-AI-016 ...` 형식 |

---

## Definition of Done (최종)

- [ ] 4개 REQ 전부 구현 완료
- [ ] 단위 테스트 16종 + 통합 테스트 4종 전부 통과
- [ ] `cd backend && uv run pytest tests/ --tb=short -q -m "not slow"` 100% 통과
- [ ] `cd backend && uv run ruff check . && uv run mypy app/` 오류 0
- [ ] 회귀 보장 체크리스트 7항 전부 통과
- [ ] TRUST 5 품질 게이트 통과
- [ ] 개발 환경 24시간 합성 데이터 관측 완료
- [ ] 운영 환경 정규장 마감 후(KST 15:30 이후) 배포 완료
- [ ] 다음 거래일 첫 1시간 (09:00~10:00) 실시간 모니터링 완료
- [ ] 운영 1주 관찰 결과 성공 기준 메트릭 달성:
  - 일별 매수 후보 5~25건
  - 가격 조회 성공률 ≥ 90%
  - 단일 섹터 최대 비중 ≤ 40%
  - 추정 정밀도 ≥ 25%
- [ ] CHANGELOG 업데이트 (SPEC-AI-016 항목 추가)
- [ ] @MX 태그 추가 (5.5 절 대상 함수)

---

**검증 자동화 우선순위**: T-016-001~004 (REQ-001, 1순위) → T-016-013~016 (REQ-004, 2순위) → T-016-005~008 (REQ-002, 3순위) → T-016-009~012 (REQ-003, 4순위) → I-016-001~004 (통합, 마지막)
