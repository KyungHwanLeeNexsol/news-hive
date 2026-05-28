---
id: SPEC-AI-019
type: acceptance
version: 0.1.0
status: draft
created: 2026-05-27
updated: 2026-05-27
author: Nexsol
---

# SPEC-AI-019 Acceptance Criteria

본 문서는 SPEC-AI-019 의 인수 기준을 Given-When-Then 시나리오와 검증 가능한
관측 지표로 정의한다.

---

## Quality Gates (Definition of Done)

전체 SPEC 이 완료되었다고 선언하려면 다음 항목이 **모두** 충족되어야 한다:

- [ ] **G1**: `pytest backend/tests/test_surge_ai019_path_b.py -v` 의 4 케이스
      전부 통과
- [ ] **G2**: `pytest backend/tests/test_surge_ai018.py -v` 의 모든 케이스가
      변경 없이 통과 (Phase 3 회귀 없음)
- [ ] **G3**: `pytest backend/tests/` 전체 슈트 통과 (기존 1147 테스트, 신규
      4 테스트 포함 1151 이상)
- [ ] **G4**: `SurgeCandidate` 모델에 `per: float | None` 과
      `pbr: float | None` 필드가 추가되어 있다 (`SurgeCandidate` 정의 grep
      으로 확인 가능)
- [ ] **G5**: `fund_manager.py:1700-1718` 의 valuation 필터 블록이 제거되어
      있다 (`fund_manager.py` 에서 `max_per` / `max_pbr` 직접 참조 없음)
- [ ] **G6**: `surge_detector.detect_surge_candidates()` 내부에 valuation
      필터 블록이 정확히 1개 존재한다
- [ ] **G7**: 신규 valuation 필터 블록에 `@MX:ANCHOR` 태그가 SPEC-AI-019 참조
      와 함께 부착되어 있다
- [ ] **G8**: 배포 후 첫 영업일 15:20 잡 결과에서 PER>500 또는 PBR>30 종목이
      `fund_signals.signal_type='surge_candidate'` 에 0건 존재 (사후 쿼리 검증)

---

## Given-When-Then 시나리오

### Scenario 1: Path B 에서 PER>500 종목 제외 (REQ-AI019-004, REQ-AI019-009a)

**Given** `run_surge_signal_generation` 잡이 호출하는 `_gather_surge_candidates`
경로(leading_candidates=[])가 사용된다
**And** 후보 종목 X 의 `SurgeCandidate.per = 750.0`
**And** 후보 종목 X 의 `SurgeCandidate.pbr = 5.0`
**When** `surge_detector.detect_surge_candidates()` 가 후보 셋을 처리한다
**Then** 종목 X 는 valuation_disqualifiers 필터에서 제외되어야 한다
**And** 종목 X 에 대한 `surge_candidate` 시그널이 생성되지 않아야 한다

### Scenario 2: Path B 에서 PBR>30 종목 제외 (REQ-AI019-004, REQ-AI019-009b)

**Given** `run_surge_signal_generation` 잡이 호출하는 `_gather_surge_candidates`
경로(leading_candidates=[])가 사용된다
**And** 후보 종목 Y 의 `SurgeCandidate.per = 20.0`
**And** 후보 종목 Y 의 `SurgeCandidate.pbr = 45.0`
**When** `surge_detector.detect_surge_candidates()` 가 후보 셋을 처리한다
**Then** 종목 Y 는 valuation_disqualifiers 필터에서 제외되어야 한다
**And** 종목 Y 에 대한 `surge_candidate` 시그널이 생성되지 않아야 한다

### Scenario 3: PER 결측치 통과 (REQ-AI019-005, REQ-AI019-009c)

**Given** 후보 종목 Z 의 `SurgeCandidate.per = None`
**And** 후보 종목 Z 의 `SurgeCandidate.pbr = 8.0`
**When** `surge_detector.detect_surge_candidates()` 가 후보 셋을 처리한다
**Then** 종목 Z 는 valuation 사유로 제외되지 않아야 한다
**And** 후속 앙상블 스코어 계산에 종목 Z 가 포함되어야 한다

### Scenario 4: 정상 밸류에이션 통과 (REQ-AI019-009d)

**Given** 후보 종목 W 의 `SurgeCandidate.per = 15.0`
**And** 후보 종목 W 의 `SurgeCandidate.pbr = 2.5`
**When** `surge_detector.detect_surge_candidates()` 가 후보 셋을 처리한다
**Then** 종목 W 는 valuation 필터를 통과해야 한다
**And** 후속 앙상블 스코어 계산에 종목 W 가 포함되어야 한다

### Scenario 5: Path A 와 Path B 행위 동등성 (REQ-AI019-007)

**Given** 동일한 입력 데이터셋 (동일한 후보 코드, 동일한 PER/PBR 값)
**When** Path A (`_gather_leading_candidates + _gather_surge_candidates`) 가
실행된다
**And** Path B (`_gather_surge_candidates(..., leading_candidates=[])`) 가
실행된다
**Then** valuation 사유로 제외되는 후보 코드 집합이 양 경로에서 동일해야 한다

### Scenario 6: PER=0 결측치 동치 처리 (REQ-AI019-005)

**Given** 후보 종목 V 의 `SurgeCandidate.per = 0`
**And** 후보 종목 V 의 `SurgeCandidate.pbr = 50.0`
**When** `surge_detector.detect_surge_candidates()` 가 후보 셋을 처리한다
**Then** PER=0 은 결측치로 간주되어 PER 필터는 통과
**But** PBR=50 > 30 이므로 PBR 필터에서 제외
**And** 종목 V 의 `surge_candidate` 시그널은 생성되지 않아야 한다

### Scenario 7: 탐지기 단계 per/pbr 수집 (REQ-AI019-002)

**Given** mock 시장 데이터가 PER=12, PBR=1.5 를 반환하도록 설정된다
**When** `detect_theme_cluster_candidates` (또는 다른 두 탐지기 중 하나) 가
해당 종목 후보를 생성한다
**Then** 반환된 `SurgeCandidate` 객체의 `per` 속성은 12 이어야 한다
**And** 반환된 `SurgeCandidate` 객체의 `pbr` 속성은 1.5 이어야 한다
**And** 동일 종목에 대한 추가 외부 API 호출 발생 횟수는 0 이어야 한다 (mock
호출 카운트 검증)

### Scenario 8: SPEC-AI-018 회귀 없음 (REQ-AI019-008)

**Given** SPEC-AI-018 acceptance 시나리오 전체가 정의되어 있다
**When** 본 SPEC 의 변경 적용 후 `pytest backend/tests/test_surge_ai018.py`
가 실행된다
**Then** 모든 케이스가 통과해야 한다
**And** `_gather_leading_candidates()` 경로(Path A) 의 PER>500/PBR>30 제외
행위가 보존되어야 한다

---

## Edge Cases

### Edge Case 1: 양쪽 모두 결측치

**Given** 후보 종목의 `per = None` 이고 `pbr = None`
**Then** 필터를 통과해야 한다 (REQ-AI018-008 호환)

### Edge Case 2: 경계값 (PER = 500 정확히)

**Given** 후보 종목의 `per = 500.0` (max_per 와 정확히 동일)
**Then** REQ-AI019-004 의 조건 `per > max_per` 에 의해 통과해야 한다
(strict greater-than)

### Edge Case 3: 경계값 (PBR = 30 정확히)

**Given** 후보 종목의 `pbr = 30.0` (max_pbr 와 정확히 동일)
**Then** REQ-AI019-004 의 조건 `pbr > max_pbr` 에 의해 통과해야 한다

### Edge Case 4: 음수 PER (적자 기업)

**Given** 후보 종목의 `per = -5.0` (적자 기업)
**Then** `per > 500` 조건에 해당하지 않으므로 PER 필터는 통과
**And** PBR 만 평가 대상이 된다

### Edge Case 5: 빈 후보 리스트

**Given** 탐지기가 후보를 한 건도 반환하지 않는다
**When** `detect_surge_candidates()` 가 호출된다
**Then** 필터 블록은 예외 없이 빈 리스트를 반환해야 한다

### Edge Case 6: config 로드 실패 (방어적 동작)

**Given** `ValuationDisqualifiersConfig` 로드가 실패한다 (가상 시나리오)
**Then** 필터는 안전한 기본값(skip_if_missing=true 와 동치) 으로 동작하여
모든 후보를 통과시켜야 하며, 시그널 생성 자체는 차단되지 않아야 한다

### Edge Case 7: 부분 실패 - 일부 종목만 per/pbr 결측

**Given** 후보 100건 중 30건은 per/pbr 가 채워져 있고, 70건은 모두 None
**Then** 결측 70건은 필터를 통과해야 한다
**And** 채워진 30건 중 부적격 종목만 제외되어야 한다

---

## Test Strategy

### 신규 테스트 파일: `backend/tests/test_surge_ai019_path_b.py`

다음 pytest 함수 (최소 4 케이스) 를 포함해야 한다:

- `test_path_b_excludes_per_above_500`: Scenario 1 검증
- `test_path_b_excludes_pbr_above_30`: Scenario 2 검증
- `test_path_b_passes_per_none`: Scenario 3 검증
- `test_path_b_passes_normal_valuation`: Scenario 4 검증

추가 권장 케이스:

- `test_path_a_path_b_parity`: Scenario 5 검증
- `test_per_zero_treated_as_missing`: Scenario 6 검증
- `test_detector_piggyback_no_extra_api_call`: Scenario 7 검증
- `test_boundary_per_exactly_500`: Edge Case 2 검증
- `test_boundary_pbr_exactly_30`: Edge Case 3 검증

### Fixture 패턴

- `SurgeCandidate` 객체를 직접 생성하여 per/pbr 다양한 값을 주입
- `surge_detector.detect_surge_candidates()` 를 직접 호출 (Path B mock:
  `leading_candidates=[]`)
- 외부 API 호출은 `unittest.mock.patch` 로 mock 처리
- mock 호출 카운트 검증으로 piggy-back 의도 검증

### 회귀 검증 명령

```
pytest backend/tests/test_surge_ai018.py -v
pytest backend/tests/test_surge_detector.py -v
pytest backend/tests/test_surge_scoring.py -v
pytest backend/tests/ -v
```

---

## Observable Evidence Requirements

다음 관측 가능한 증거가 본 SPEC 의 완료를 입증해야 한다:

1. **코드 수준**: `grep -n "per:" backend/app/services/surge_detector.py` 가
   `SurgeCandidate` 정의 영역에서 `per: float | None` 라인을 반환해야 한다.
2. **코드 수준**: `grep -n "max_per\|max_pbr" backend/app/services/fund_manager.py`
   가 0 라인을 반환해야 한다 (필터 제거 확인).
3. **코드 수준**: `grep -n "max_per\|max_pbr" backend/app/services/surge_detector.py`
   가 정확히 valuation 필터 블록 1곳에서만 매칭되어야 한다.
4. **테스트 수준**: pytest 실행 결과 신규 4 케이스 PASSED, 기존 1147 테스트
   PASSED.
5. **운영 수준** (배포 후): 첫 영업일 15:20 잡 종료 직후
   `SELECT COUNT(*) FROM fund_signals WHERE signal_type='surge_candidate' AND
   created_at::date = CURRENT_DATE` 결과에서, 각 종목 코드를 대상으로 외부
   PER/PBR 조회 결과가 per ≤ 500 AND pbr ≤ 30 임을 100% 만족.
6. **MX 태그 수준**: `grep -rn "@MX:ANCHOR.*AI-019" backend/app/services/`
   가 최소 1건 매칭.

---

## Rollback Criteria

다음 중 하나라도 발생하면 즉시 롤백한다:

- 배포 후 24시간 내 `surge_candidate` 시그널 일일 생성 건수가 직전 영업일 대비
  -50% 이하로 급감 (예: 96 → 48 미만)
- 운영 로그에서 `detect_surge_candidates` 가 처리하는 후보 셋의 per/pbr 결측률
  이 100% (piggy-back 실패)
- SPEC-AI-018 의 어떤 acceptance 시나리오에서도 회귀 발생

---

## Success Metrics

| 메트릭 | 측정 방법 | 목표값 |
|---|---|---|
| 부적격 종목 비율 | 배포 후 영업일별 `fund_signals.surge_candidate` 종목에 대한 PER/PBR 사후 조회 | 0% (per>500 또는 pbr>30 종목 0건) |
| 신규 테스트 통과율 | `pytest backend/tests/test_surge_ai019_path_b.py` | 100% (최소 4 케이스) |
| 회귀 테스트 통과율 | `pytest backend/tests/` 전체 | 100% (기존 + 신규 모두 통과) |
| API 호출 증가 | 탐지기별 외부 API 호출 카운트 비교 | 변화 없음 (piggy-back 보장) |
| Path A/B 동등성 | 동일 입력에 대한 시그널 종목 집합 일치 | 100% 일치 |
