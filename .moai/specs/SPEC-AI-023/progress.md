# SPEC-AI-023 진행 기록 — DDD 버그픽스 (2026-07-02)

## 배경

`detect_near_limit_up_carries()`는 이미 구현되어 파이프라인에 연결되어 있었으나, spec.md
요구사항과 실제 코드 사이에 정밀 대조 결과 불일치가 발견되어 DDD(ANALYZE-PRESERVE-IMPROVE)
사이클로 수정했다.

## 수정 항목

### 1. `min_market_cap_eok` 필드 및 시총 하한 필터 누락 (REQ-AI023-001 a)

- **재현 테스트**: `test_bugfix_ai023_min_market_cap_eok_field_exists_with_default_300`,
  `test_bugfix_ai023_min_market_cap_eok_filters_small_cap_stock`
  (`backend/tests/test_near_limit_up_carry.py`)
- **수정 전**: `NearLimitUpConfig`에 시총 하한 필드가 없고, 후보 쿼리도 시총 조건 없이
  `nullslast(Stock.market_cap.desc())` 정렬 + `limit(max_stocks_to_check)`만 적용.
- **수정 후**: `NearLimitUpConfig.min_market_cap_eok: int = 300` 필드 추가. 쿼리에
  `or_(Stock.market_cap.is_(None), Stock.market_cap >= config.min_market_cap_eok)` 필터 추가
  (NULL 시총 종목은 기존 정책대로 계속 허용).
- 파일: `backend/app/surge_config/surge_settings.py`, `backend/app/services/surge_detector.py`

### 2. `surge_metadata`에 `near_limit_up_carry: true` 키 누락

- **재현 테스트**: `test_bugfix_ai023_surge_metadata_has_near_limit_up_carry_true_key`
- **수정 전**: `{"surge_basis": [...], "yesterday_change_pct": ..., "surge_probability_score": ...}`
- **수정 후**: 위 필드 유지 + `"near_limit_up_carry": True` 키 추가.

## 판단이 필요했던 애매한 항목 (수정하지 않음)

### near_limit_up_min_pct 기본값: 코드 15.0 vs spec.md 25.0

**판단: 유지 (코드 값 15.0이 맞음, spec.md 값을 따르지 않음)**

`surge_settings.py`의 필드 주석에 "15~24% 모멘텀 이월 종목 누락 방지로 25.0→15.0 완화"라는
명시적 이력이 남아있고, 기존 테스트(`test_ac011_boundary_15_0_creates_signal`,
`test_ac013_18pct_now_qualifies_after_band_widening`)가 이 완화된 값을 characterize하고
있다. 이는 SPEC 작성 이후 발생한 의도적 정책 튜닝(운영 데이터 기반 커버리지 확장)으로
판단하여 되돌리지 않았다. spec.md 값(25.0)이 실수가 아니라 SPEC 작성 시점의 초기값이며,
이후 실전 운영을 통해 완화된 것으로 해석.

### max_stocks_to_check(코드, 1200) vs max_candidates_per_day(spec, 500)

**판단: 유지 (이름·값 모두 코드 기준 유지, spec.md 기준으로 되돌리지 않음)**

`surge_settings.py` 주석: "시총 상위 N 종목만 평가 — NULL 시총 종목도 후보 풀에 포함되도록
500→1200 확대". 단순 오타/실수가 아니라 NULL 시총 종목을 후보 풀에 포함시키기 위한 의도적
확장이며, 필드명 변경(`max_candidates_per_day` → `max_stocks_to_check`) 또한 의미가 "일일
최대 후보 수"에서 "평가 대상 최대 종목 수"로 정교화된 것으로 판단. 두 값 다 실수로 보이지
않아 변경하지 않았다.

### 중복 방지 범위: spec(3개 signal_type) vs 코드(오늘 존재하는 모든 signal_type)

**판단: 유지 (코드의 넓은 범위가 더 안전한 설계)**

spec.md는 surge_candidate/theme_propagation/volume_anomaly 3종만 중복 방지 대상으로
명시했으나, 실제 구현은 `FundSignal.stock_id` 전체(signal_type 무관)를 오늘자 existing_ids로
수집한다. SPEC-AI-023 작성 이후 `_run_coverage_expansion()`에 5개 탐지기가 추가로 연결되었고
(SPEC-AI-024 임원매수, SPEC-AI-025 테마그룹, SPEC-AI-026 포럼언급, SPEC-AI-027 그룹cascade,
SPEC-AI-050 주말갭업), 이들 신규 signal_type과의 교차 중복 방지가 없으면 동일 종목에 중복
매수 신호가 발행될 위험이 있다. 3종으로 좁히면 오히려 회귀(regression) 위험이 있다고 판단해
넓은 범위를 유지했다. SPEC-AI-026에도 동일 판단을 적용.

## 테스트 결과

- `backend/tests/test_near_limit_up_carry.py`: 18 passed (기존 15 + 신규 3)
- 전체 회귀: 1791 passed, 4 skipped, 3 xpassed (0 failed)
- `ruff check .`: All checks passed
