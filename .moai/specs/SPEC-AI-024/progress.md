# SPEC-AI-024 진행 기록 — DDD 버그픽스 (2026-07-02)

## 배경

`detect_insider_purchase_signals()`는 이미 구현되어 파이프라인에 연결되어 있었으나, spec.md
요구사항과 실제 코드 사이에 정밀 대조 결과 6건의 불일치가 발견되어 DDD
(ANALYZE-PRESERVE-IMPROVE) 사이클로 수정했다.

## 수정 항목

### 1. `disclosure_id` 추적성 필드 미설정 (가장 중요)

- **재현 테스트**: `test_bugfix_ai024_disclosure_id_is_set`
- **수정 전**: `FundSignal(...)` 생성 시 `disclosure_id` 필드가 전혀 설정되지 않음(항상 NULL).
- **수정 후**: `disclosure_id=disc.id` 추가.

### 2. `reasoning` 접두사 누락

- **재현 테스트**: `test_bugfix_ai024_reasoning_has_spec_prefix`
- **수정 전**: `f"임원 자사주 매수 공시 — {rname}"`
- **수정 후**: `f"[SPEC-AI-024 임원자사주매수] {rname}"`

### 3. 음성(제외) 키워드 누락 — "매각", "감소"

- **재현 테스트**: `test_bugfix_ai024_negative_keyword_maegak_blocked`,
  `test_bugfix_ai024_negative_keyword_gamso_blocked`
- **수정 전**: `_NEGATIVE_KEYWORDS = ["처분", "매도", "양도"]` (함수 내부 로컬 변수)
- **수정 후**: 모듈 상수 `_INSIDER_PURCHASE_NEGATIVE_KEYWORDS = ["처분", "매도", "매각", "양도", "감소"]`

### 4. report_type의 ㆍ/· 변형(c-2) 매칭 로직 부재

- **재현 테스트**: `test_bugfix_ai024_report_type_dot_variant_without_officer_in_name`
- **수정 전**: `report_type` 컬럼을 전혀 조회/필터링하지 않음. `report_name`에 "임원"이 없으면
  아예 후보에 오르지 못함.
- **수정 후**: DB 쿼리에 `report_type`/`report_name`이 `_INSIDER_PURCHASE_REPORT_TITLES`
  (ㆍ U+318D, 중간점 · 양쪽 변형)를 포함하는 경우도 후보에 포함하도록 `or_()` 확장. Python
  단에서 `is_title_variant` 조건으로 c-2를 판정.

### 5. 양성 매칭 순서 고정 문제

- **재현 테스트**: `test_bugfix_ai024_positive_match_is_order_independent`
- **수정 전**: `Disclosure.report_name.ilike("%임원%취득%")` — "임원"이 반드시 "취득"보다 앞에
  와야 매칭됨.
- **수정 후**: DB 쿼리는 폭넓게 후보를 가져오고, Python 단에서 `"임원" in rname` (순서 무관)
  AND `any(kw in rname for kw in _INSIDER_PURCHASE_ACTION_KEYWORDS)` 조합으로 판정.

### 6. 종목당 1건 dedup 시 "가장 최근 공시" 기준 미적용

- **재현 테스트**: `test_bugfix_ai024_dedup_uses_most_recent_disclosure`
- **수정 전**: `db.query(Disclosure).filter(...).all()` — 정렬 없이 DB 반환 순서에 의존.
- **수정 후**: `.order_by(Disclosure.created_at.desc())` 추가. `emitted` set으로 stock_id별
  최초 등장(=가장 최근 공시)만 채택하는 기존 로직과 결합하여 "최근 공시 우선" 보장.

## 변경하지 않은 항목 (명시적 지시)

- **함수명**: spec.md는 `detect_insider_purchase_signal`(단수)로 표기하지만 실제 코드는
  `detect_insider_purchase_signals`(복수형)이다. 호출부(`fund_manager._run_coverage_expansion`)가
  이미 이 이름을 참조 중이므로 breaking change 방지를 위해 함수명은 변경하지 않았다.
  spec.md 쪽 표기 오차로 간주.
- **`surge_metadata.rcept_no` 키**: spec.md는 `rcept_no`도 metadata에 포함하도록 요구하지만,
  이는 사용자가 제시한 버그 목록에 없어 스코프 밖으로 판단하여 추가하지 않았다(스코프
  디시플린 원칙).

## 테스트 결과

- `backend/tests/test_insider_purchase_signal.py`: 12 passed (기존 5 + 신규 7)
- 전체 회귀: 1791 passed, 4 skipped, 3 xpassed (0 failed)
- `ruff check .`: All checks passed
