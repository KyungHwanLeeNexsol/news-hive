---
spec_id: SPEC-AI-020
version: 0.1.0
created: 2026-05-28
updated: 2026-05-28
author: Nexsol
---

# SPEC-AI-020 Implementation Plan

## 개요

본 Plan 문서는 SPEC-AI-018 Phase 3 및 SPEC-AI-019 가 도입한 PER/PBR 밸류에이션
필터를 급등 시그널 파이프라인에서 제거하기 위한 구현 계획을 정의한다.
구현 범위는 좁고 회귀 위험이 낮으며, 데이터 수집 인프라(SurgeCandidate
per/pbr 필드, 3개 탐지기 piggy-back 수집, `_extract_valuation` 헬퍼)는
유지된다.

본 Plan 은 **어떻게(HOW)** 를 정의한다. **무엇을(WHAT)** 과 **왜(WHY)**
는 spec.md 를 참조한다.

---

## Technical Approach

### 핵심 전략

단일 파일(`surge_detector.py`)의 한 함수(`detect_surge_candidates()`) 내부
에서 필터 블록만 제거한다. 데이터 수집 코드(SurgeCandidate 필드, 헬퍼,
piggy-back) 는 모두 보존하므로 차분 범위가 좁다.

### 구현 순서

1. **데이터 수집 인프라 확인**: `SurgeCandidate.per/pbr`, `_extract_valuation`,
   3개 탐지기 piggy-back 수집이 정상 동작하는지 기존 테스트로 확인.
2. **필터 블록 제거**: `detect_surge_candidates()` 에서 SPEC-AI-019 가
   추가한 valuation 필터 블록을 삭제. `ValuationDisqualifiersConfig` 로더
   호출도 함께 제거.
3. **주석 및 태그 업데이트**:
   - `SurgeCandidate.per/pbr` 필드 주석을 "data-only" 로 명시
   - `@MX:ANCHOR SPEC-AI-019 REQ-AI019-003` 제거
   - `@MX:NOTE` 업데이트
4. **설정 deprecation 주석 추가**: `surge_detection.yaml` 의
   `valuation_disqualifiers` 섹션에 `# DEPRECATED by SPEC-AI-020` 추가.
   `ValuationDisqualifiersConfig` Pydantic 모델 docstring 에도 명시.
5. **테스트 인버트**:
   - `test_surge_ai019_path_b.py`: 필터 제외 단언을 통과 단언으로 변경
   - `test_surge_ai018.py` Phase 3 케이스: retire 또는 invert
6. **회귀 슈트 실행**: 전체 테스트가 변경된 acceptance 기준 하에 통과하는
   지 확인.

### 변경 파일 목록

| 파일 | 변경 유형 | 설명 |
|---|---|---|
| `backend/app/services/surge_detector.py` | 수정 | 필터 블록 제거, 주석/태그 업데이트 |
| `backend/app/surge_config/surge_settings.py` | 수정 | `ValuationDisqualifiersConfig` docstring 에 deprecation 명시 |
| `backend/app/surge_config/surge_detection.yaml` | 수정 | YAML 주석 추가 |
| `backend/tests/test_surge_ai019_path_b.py` | 수정 | 필터 단언 인버트 |
| `backend/tests/test_surge_ai018.py` | 수정 | Phase 3 케이스 retire/invert |

신규 파일 없음. 삭제 파일 없음.

---

## Milestones (Priority-Based)

본 SPEC 은 변경 범위가 좁아 단일 마일스톤으로 충분하다. 모든 작업은 단일
PR 로 묶어 롤백 안전성을 확보한다.

### Milestone 1 — Priority: High (단일 마일스톤)

**목표**: 필터 제거 + 테스트 인버트 + 전체 회귀 통과

**구성 작업**:

- M1-T1 (필수): `detect_surge_candidates()` 의 valuation 필터 블록 제거
  (REQ-AI020-001)
- M1-T2 (필수): SurgeCandidate per/pbr 필드 주석 업데이트 (REQ-AI020-002)
- M1-T3 (필수): `_extract_valuation` 및 piggy-back 수집 보존 확인
  (REQ-AI020-003, REQ-AI020-004)
- M1-T4 (필수): `ValuationDisqualifiersConfig` deprecation 주석 추가,
  YAML deprecation 주석 추가, 로더 호출 제거 (REQ-AI020-005)
- M1-T5 (필수): MX 태그 정리 — `@MX:ANCHOR` 제거, `@MX:NOTE` 업데이트,
  deprecated `@MX:NOTE` 신규 추가 (REQ-AI020-010)
- M1-T6 (필수): `test_surge_ai019_path_b.py` 인버트 (REQ-AI020-007)
- M1-T7 (필수): `test_surge_ai018.py` Phase 3 케이스 retire/invert
  (REQ-AI020-008)
- M1-T8 (필수): 전체 회귀 슈트 통과 확인 (REQ-AI020-009)
- M1-T9 (Low): SPEC-AI-018 deprecation 명시 — spec.md HISTORY 및 선행 SPEC
  섹션에 supersession 관계 기록 (REQ-AI020-006, 이미 본 SPEC 문서에 포함됨)

**완료 기준**:

- 위 모든 작업의 코드 변경이 단일 PR 로 묶임
- CI 의 전체 회귀 통과
- 코드 리뷰 승인 후 main 머지

---

## Dependencies

### 선행 조건

- 사용자가 SPEC-AI-019 PR 처리 방식을 결정해야 한다 (Rollout Plan Step 0
  참조). 두 옵션 모두 본 Plan 의 구현에는 영향을 주지 않는다.
- SPEC-AI-019 의 데이터 수집 인프라(REQ-001 ~ 002, 004)가 코드베이스에
  존재해야 한다. PR (a) 를 선택한 경우 본 SPEC 의 구현 PR 이 해당 인프라
  를 함께 포함해야 한다.

### 외부 의존성

- 없음. 외부 라이브러리 변경 없음. 데이터베이스 스키마 변경 없음.
  외부 API 변경 없음.

---

## Risk Analysis

### Risk 1: 회귀 위험 — Low

**기술적 위험**: 필터 제거는 추가가 아닌 삭제 작업이므로 새로운 코드 경로
가 생기지 않는다. 데이터 수집 인프라는 그대로 유지되므로 SurgeCandidate
객체의 모양도 변하지 않는다.

**완화**:

- 단일 PR 로 묶어 회귀 발견 시 즉시 revert 가능
- 전체 회귀 슈트가 새 acceptance 기준 하에 통과해야 머지
- 다음 영업일 15:20 KST 잡 결과 사후 모니터링

### Risk 2: SPEC-AI-018/019 acceptance 부분 회귀 — Acknowledged

**의도된 회귀**: SPEC-AI-018 Phase 3 의 acceptance 가 본 SPEC 에 의해
무효화되며, 이는 명시적 의도이다. SPEC-AI-018 Phase 1/2/4 의 acceptance
는 영향받지 않는다.

**완화**:

- spec.md 의 HISTORY 와 선행 SPEC 섹션에서 supersession 관계를 명시
- 인버트되는 테스트 케이스에 SPEC-AI-020 참조 주석 추가
- SPEC-AI-018 문서는 FROZEN 으로 유지 (역사적 기록 보존)

### Risk 3: 운영 영향 — Low

**행위 변경**: 매 영업일 15:20 잡이 생성하는 시그널 중 PER>500 또는
PBR>30 종목이 다시 포함된다 (시뮬레이션 기준 약 11 종목).

**완화**:

- 시뮬레이션 결과에 따르면 제외되었던 11 종목 중 0 종목이 실제 위험 종목
  이고, 7 종목이 정상적인 바이오/제약 성장주
- 다음 영업일 09:00 의 `surge_execute_buys` 가 실행하는 모의 매매는
  추가적인 리스크 관리 로직(SPEC-AI-018 Phase 1/2/4 의 ensemble 가중치,
  recent surge penalty, group consensus multiplier) 을 거치므로 최종 매수
  결정에 다중 안전판이 작동

### Risk 4: 향후 가치 기반 안전판 부재 — Acknowledged, Deferred

**잔여 위험**: 가치 지표 기반 안전판이 사라지므로, 향후 진짜 pump-and-dump
종목이 나타날 경우 1차 차단 메커니즘이 없다.

**완화**:

- Future Work (SPEC-AI-021 후보) 로 별도 안전판 설계 이연
- 시간 지평이 일치하는 대체 안전판(관리종목·거래정지, 변동성 캡, 유동성)
  은 모멘텀 전략에 더 적합

---

## Testing Strategy

### 단위 테스트

- **인버트**: `test_surge_ai019_path_b.py`
  - `per > 500` 케이스 → 통과 단언
  - `pbr > 30` 케이스 → 통과 단언
  - `per is None` 케이스 → 통과 단언 (변경 없음, 자명한 통과)
  - 경계 케이스 (`per == 500`, `pbr == 30`) → 통과 단언 (변경 없음)
  - 정상값 케이스 → 통과 단언 (변경 없음)
- **유지**: Path A/B parity 케이스 — 양 경로 모두 필터 없음이므로 parity
  성립

### 회귀 테스트

- `test_surge_ai018.py` Phase 1 (ensemble 가중치) — 영향 없음, 통과 유지
- `test_surge_ai018.py` Phase 2 (recent surge penalty) — 영향 없음, 통과 유지
- `test_surge_ai018.py` Phase 4 (group consensus multiplier) — 영향 없음,
  통과 유지
- `test_surge_ai018.py` Phase 3 (PER/PBR 필터) — retire 또는 invert
- 그 외 전체 회귀 슈트 — 영향 없음, 통과 유지

### 통합 테스트 (선택)

- 3개 탐지기 piggy-back 수집이 정상 동작하는지 확인 (SurgeCandidate per/pbr
  필드가 None 이 아닌 값으로 populate 되는 케이스가 최소 하나)

### 사후 운영 모니터링

- 다음 영업일 15:20 KST 잡 실행 후 `fund_signals` 테이블 쿼리
- 시뮬레이션에서 제외되었던 11 종목 중 confidence 임계값을 통과하는
  종목이 다시 시그널 풀에 등장하는지 확인

---

## Rollback Plan

본 SPEC 의 변경은 단일 PR 로 구성되므로 git revert 한 번으로 롤백 가능
하다. 데이터 수집 인프라는 보존되므로 필터를 재도입하려면 SPEC-AI-019 의
필터 블록을 다시 추가하면 된다 (코드 차이 최소).

### 롤백 트리거 조건

- 인버트된 테스트가 실제로는 실패하는 경우
- 다음 영업일 15:20 잡이 비정상 종료되거나 시그널 생성이 실패하는 경우
- 사후 모니터링에서 데이터 수집 인프라가 깨진 것이 발견되는 경우 (별개
  버그이지만 안전을 위해 함께 롤백 가능)

### 롤백 절차

1. `git revert <merge-commit-hash>` 로 단일 revert PR 생성
2. CI 통과 확인 후 즉시 머지
3. 자동 배포 후 다음 영업일 15:20 잡 정상 동작 확인
