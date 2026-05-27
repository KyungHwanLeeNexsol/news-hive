---
spec_id: SPEC-AI-020
version: 0.1.0
created: 2026-05-28
updated: 2026-05-28
author: Nexsol
---

# SPEC-AI-020 Acceptance Criteria

## 개요

본 문서는 SPEC-AI-020 (PER/PBR 밸류에이션 필터 제거) 의 acceptance 기준을
Given-When-Then 형식으로 정의한다. SPEC-AI-018 Phase 3 및 SPEC-AI-019 의
필터 적용 acceptance 와 정반대 방향의 단언을 포함한다.

---

## Acceptance Scenarios

### Scenario 1: Path B 에서 PER 극단값 종목이 시그널 풀에 포함됨

**Given**: 15:20 KST 잡 (`run_surge_signal_generation` → Path B) 이
실행되고, 후보 중 하나가 `per = 10027` (레인보우로보틱스 사례, 적자 테마주
로 EPS 가 0 에 근접하여 PER 이 매우 큰 값으로 발산) 이며 ensemble 스코어와
qualification 임계값을 통과한다.

**When**: `surge_detector.detect_surge_candidates()` 가 호출되어
SurgeCandidate 리스트를 반환한다.

**Then**: 해당 후보가 `signal_type='surge_candidate'` 시그널 풀에 **포함
**되어야 한다. PER 값에 의한 어떠한 필터링도 적용되지 않아야 한다.

### Scenario 2: Path A 에서 PBR 극단값 종목이 시그널 풀에 포함됨

**Given**: 08:30 KST 데일리 브리핑 잡 (`generate_daily_briefing` → Path A)
이 실행되고, 후보 중 하나가 `pbr = 46.8` (알테오젠 사례, 바이오 성장주의
정상 산업 가치 프로파일) 이며 ensemble 스코어와 qualification 임계값을
통과한다.

**When**: `_gather_leading_candidates` 와 `_gather_surge_candidates` 가
연속 호출되어 SurgeCandidate 리스트를 생성한다.

**Then**: 해당 후보가 `signal_type='surge_candidate'` 시그널 풀에 **포함
**되어야 한다. PBR 값에 의한 어떠한 필터링도 적용되지 않아야 한다.

### Scenario 3: Path A 와 Path B 의 행위 동등성 (parity)

**Given**: 동일한 입력 데이터 (동일한 뉴스 풀, 동일한 시장 데이터, 동일한
disclosure 이벤트 셋) 가 양 경로에 주어진다.

**When**: Path A (`_gather_leading_candidates` + `_gather_surge_candidates`)
와 Path B (`_gather_surge_candidates` with `leading_candidates=[]`) 가
각각 실행된다.

**Then**: 두 경로가 생성하는 `surge_candidate` 시그널 집합은 PER/PBR
기반 제외/포함에 대해 동일한 결정을 내려야 한다 (양 경로 모두 필터가
없으므로 자동으로 성립). `legacy_score` 차이 등 SPEC-AI-019 가 명시한
경로별 메타데이터 차이는 허용된다.

### Scenario 4: 운영 환경 사후 검증

**Given**: 본 SPEC 이 main 에 머지되고 자동 배포되어, 다음 영업일
(2026-05-29 KST 금요일 또는 그 이후 첫 영업일) 15:20 KST 잡이 실행된다.

**When**: 운영 데이터베이스의 `fund_signals` 테이블을 조회한다 (해당
잡 실행 직후 약 30분 이내).

**Then**: 생성된 `signal_type='surge_candidate'` 시그널 중 `per > 500`
또는 `pbr > 30` 인 종목이 **정상 포함**되어야 한다. 시뮬레이션에서 제외
되었던 11 종목과 유사한 종목군이 confidence 임계값을 통과하는 경우 시그널
풀에 등장해야 한다.

### Scenario 5: SurgeCandidate per/pbr 필드가 data-only 로 유지됨

**Given**: 3개 탐지기 중 하나(`detect_theme_cluster_candidates`,
`detect_volume_news_combo_candidates`,
`detect_disclosure_pattern_candidates`) 가 호출되고 후보를 생성한다.

**When**: SurgeCandidate 객체가 구성된다.

**Then**:

- `SurgeCandidate.per` 필드와 `SurgeCandidate.pbr` 필드가 객체에 **존재
  **해야 한다.
- 시장 데이터 조회 경로에서 piggy-back 으로 값이 **populate** 되어야
  한다 (None 이거나 실제 값).
- 해당 필드 값이 어떠한 조건문에서도 후보의 시그널 포함 여부를 결정
  하는 데 사용되지 **않아야** 한다.

### Scenario 6: ValuationDisqualifiersConfig 스키마 유지, 미사용

**Given**: 본 SPEC 이 구현된 상태에서 `surge_detection.yaml` 을 로드한다.

**When**: `ValuationDisqualifiersConfig` Pydantic 모델이 인스턴스화된다.

**Then**:

- 모델 클래스와 YAML 섹션이 **존재**해야 한다 (스키마 유지).
- YAML 섹션에 `# DEPRECATED by SPEC-AI-020` 주석이 **포함**되어야 한다.
- `detect_surge_candidates()` 내부에서 해당 config 인스턴스가 **참조
  되지 않아야** 한다 (로더 호출 제거 확인).

### Scenario 7: 회귀 슈트 통과

**Given**: 본 SPEC 의 구현 PR 이 CI 에 푸시된다.

**When**: 전체 회귀 테스트 슈트가 실행된다.

**Then**:

- `test_surge_ai019_path_b.py` 의 모든 케이스가 인버트된 acceptance
  기준 하에 **통과**해야 한다.
- `test_surge_ai018.py` 의 Phase 1, 2, 4 케이스가 **변경 없이 통과**
  해야 한다.
- `test_surge_ai018.py` 의 Phase 3 케이스는 **retire 되었거나 인버트
  된 형태로 통과**해야 한다.
- 그 외 모든 기존 테스트는 **영향받지 않고 통과**해야 한다.

---

## Edge Cases

### Edge Case 1: per = None 인 후보

**Given**: 외부 API 가 PER 값을 반환하지 못한 후보 (`per = None`).

**When**: `detect_surge_candidates()` 가 호출된다.

**Then**: 해당 후보가 시그널 풀에 포함된다 (필터 부재로 자명한 통과).
SPEC-AI-018 REQ-AI018-008 "None 은 통과" 동작과 동일한 외부 관찰 결과.

### Edge Case 2: per = 500 (이전 임계값 경계)

**Given**: PER 이 정확히 500 인 후보.

**When**: `detect_surge_candidates()` 가 호출된다.

**Then**: 해당 후보가 시그널 풀에 포함된다 (이전에는 임계값 정확 일치
시 통과였으나, 본 SPEC 에서는 필터 자체가 없으므로 자명한 통과).

### Edge Case 3: pbr = 30 (이전 임계값 경계)

**Given**: PBR 이 정확히 30 인 후보.

**When**: `detect_surge_candidates()` 가 호출된다.

**Then**: 해당 후보가 시그널 풀에 포함된다 (위와 동일하게 자명한 통과).

### Edge Case 4: per = 0 또는 pbr = 0 인 후보

**Given**: PER 또는 PBR 이 정확히 0 인 후보 (데이터 누락 또는 EPS = 0
케이스).

**When**: `detect_surge_candidates()` 가 호출된다.

**Then**: 해당 후보가 시그널 풀에 포함된다. SPEC-AI-019 REQ-AI019-005
의 "0 은 통과" 호환성 동작도 본 SPEC 하에서 자명하게 만족된다 (필터 부재).

### Edge Case 5: per 와 pbr 둘 다 극단값

**Given**: 후보가 `per = 10000` 이고 `pbr = 50` 인 동시 극단값 (예:
적자 바이오 성장주).

**When**: `detect_surge_candidates()` 가 호출된다.

**Then**: 해당 후보가 시그널 풀에 포함된다. 두 지표 중 하나라도 극단
이면 제외하던 이전 동작은 본 SPEC 에서 무효화된다.

### Edge Case 6: 정상값 후보 (기존 통과 케이스)

**Given**: `per = 15`, `pbr = 2` 인 정상 가치 후보.

**When**: `detect_surge_candidates()` 가 호출된다.

**Then**: 해당 후보가 시그널 풀에 포함된다 (이전과 동일하게 통과 — 동작
변화 없음).

---

## Quality Gate Criteria

### LSP / Lint / Type Check

- 변경된 파일에 대해 zero error, zero type error, zero lint error 가 보장
  되어야 한다 (MoAI run phase 기준).
- 제거된 코드 블록이 import 되었던 모듈은 미사용 import 경고가 발생하지
  않도록 정리되어야 한다 (`_extract_valuation` 은 유지되므로 영향 없음).

### Test Coverage

- `surge_detector.py` 의 패키지 단위 테스트 커버리지가 기존 수준
  (85% 이상) 을 유지해야 한다.
- 인버트된 `test_surge_ai019_path_b.py` 의 모든 케이스가 통과해야 한다.

### MX Tag Compliance

- 제거된 필터 블록과 함께 `@MX:ANCHOR SPEC-AI-019 REQ-AI019-003,004,005`
  태그가 삭제되어 코드베이스에 잔존하지 않아야 한다.
- `SurgeCandidate.per/pbr` 필드의 `@MX:NOTE` 가
  "SPEC-AI-020: data-only observability, filtering removed" 로 업데이트
  되어야 한다.
- `ValuationDisqualifiersConfig` 정의부에 deprecated `@MX:NOTE` 가 추가
  되어야 한다.

### Configuration Validation

- `surge_detection.yaml` 가 정상 파싱되어야 한다 (deprecation 주석 추가
  후에도 YAML syntax error 없음).
- `ValuationDisqualifiersConfig` Pydantic 모델이 정상 인스턴스화되어야
  한다 (스키마 유지 확인).

---

## Definition of Done

본 SPEC 은 다음 모든 조건을 만족할 때 완료된 것으로 간주한다.

- [ ] 모든 EARS Requirements (REQ-AI020-001 ~ REQ-AI020-010) 이 코드에
      반영되었다.
- [ ] 본 문서의 모든 Acceptance Scenarios (Scenario 1 ~ 7) 가 통과한다.
- [ ] 모든 Edge Cases (Edge Case 1 ~ 6) 가 의도된 동작을 보인다.
- [ ] Quality Gate Criteria (LSP, Test Coverage, MX Tag, Config) 모두
      통과한다.
- [ ] 변경 사항이 단일 PR 로 묶여 main 에 머지된다.
- [ ] 다음 영업일 15:20 KST 잡 실행 후 Scenario 4 의 사후 검증이 완료
      된다 (선택적 — 머지 자체의 완료 조건은 아니지만 사후 모니터링
      체크포인트).
- [ ] SPEC-AI-018 Phase 3 및 SPEC-AI-019 의 필터 적용 acceptance 가 본
      SPEC 에 의해 supersede 되었음이 코드 주석 또는 본 SPEC 문서에 명시
      되어 있다.
- [ ] 데이터 수집 인프라(SurgeCandidate per/pbr 필드, `_extract_valuation`,
      3개 탐지기 piggy-back) 가 보존되어 향후 observability/사후 분석에
      활용 가능한 상태로 유지된다.
