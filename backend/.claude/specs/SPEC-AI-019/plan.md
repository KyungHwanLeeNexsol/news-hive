---
id: SPEC-AI-019
type: plan
version: 0.1.0
status: draft
created: 2026-05-27
updated: 2026-05-27
author: Nexsol
---

# SPEC-AI-019 Implementation Plan

밸류에이션 부적격 필터(SPEC-AI-018 Phase 3)를 단일 지점으로 이전하여 모든 급등
시그널 생성 경로에 일관 적용한다. 본 plan 은 마일스톤과 기술 접근을 정의한다.
함수 시그니처와 상세 구현 결정은 Run 단계로 이연한다.

---

## Technical Approach

### 핵심 설계 결정

1. **데이터 수집 책임 이전 (Detection-time Enrichment)**
   - PER/PBR 수집 책임을 `fund_manager._gather_leading_candidates()` 에서
     `surge_detector` 의 3개 탐지기로 이전한다.
   - 모든 탐지기는 시장 데이터를 조회하는 기존 경로가 있으므로, 동일 호출 결과
     에서 per/pbr 를 추출하여 `SurgeCandidate` 에 함께 채운다.
   - 추가 외부 API 호출은 발생하지 않는다 (piggy-back).

2. **필터 위치 단일화 (Single Filter Point)**
   - `surge_detector.detect_surge_candidates()` 의 앙상블 스코어 계산 직전
     단계에 필터 블록을 1개 배치한다.
   - 후보 dict 가 아니라 `SurgeCandidate` 객체 속성을 참조하므로,
     데이터 누락 시 None 으로 안전하게 디폴트된다.

3. **중복 코드 제거 (DRY)**
   - `fund_manager.py:1700-1718` 의 필터 코드를 제거한다.
   - 단일 source of truth 는 `surge_detector` 에 위치한다.

### 변경 대상 모듈

| 파일 | 변경 유형 | 책임 |
|---|---|---|
| `backend/app/services/surge_detector.py` | 수정 (모델 + 탐지기 + 오케스트레이터) | per/pbr 필드 추가, 3개 탐지기에 수집 로직 추가, 필터 단일 지점 배치 |
| `backend/app/services/fund_manager.py` | 수정 (제거) | `_gather_leading_candidates` 내 중복 필터 코드 제거 |
| `backend/tests/test_surge_ai019_path_b.py` | 신규 추가 | Path B 시나리오의 회귀 방지 테스트 |
| `backend/tests/test_surge_ai018.py` | 회귀 검증 | 변경 없이 통과 확인 |
| `backend/tests/test_surge_detector.py` | 회귀 검증 | 변경 없이 통과 확인 |
| `backend/tests/test_surge_scoring.py` | 회귀 검증 | 변경 없이 통과 확인 |

### 의존성 그래프

```
[3 detectors] --(populates per/pbr on SurgeCandidate)--> [detect_surge_candidates]
                                                              |
                                                              v
                                  [valuation_disqualifiers filter (NEW location)]
                                                              |
                                                              v
                                              [ensemble scoring + qualification]
```

Path A (`_gather_leading_candidates → _gather_surge_candidates`) 와
Path B (`run_surge_signal_generation → _gather_surge_candidates(..., leading_candidates=[])`)
모두 동일한 `surge_detector.detect_surge_candidates()` 를 통과하므로 단일 필터
지점이 자동으로 양 경로에 적용된다.

---

## Milestones (Priority-Based)

### Milestone 1 (Priority: High) — 모델 확장 + 탐지기 수집

- REQ-AI019-001 구현: `SurgeCandidate` 에 `per`, `pbr` 필드 추가
- REQ-AI019-002 구현: 3개 탐지기
  (`detect_theme_cluster_candidates`, `detect_volume_news_combo_candidates`,
  `detect_disclosure_pattern_candidates`) 에 per/pbr 수집 로직 piggy-back
- 완료 조건: 기존 `test_surge_detector.py` 회귀 없음, 신규 필드가 후보 객체에
  채워지는지 단위 검증

### Milestone 2 (Priority: High) — 필터 단일 지점 이전

- REQ-AI019-003 구현: `detect_surge_candidates()` 에 valuation filter 블록 배치
- REQ-AI019-004 구현: per > max_per 또는 pbr > max_pbr 후보 제외
- REQ-AI019-005 구현: None/0 통과 규칙 (REQ-AI018-008 호환)
- 완료 조건: `test_surge_ai018.py` 전부 통과 (Phase 3 행위 보존)

### Milestone 3 (Priority: High) — 중복 제거 + Path B 검증

- REQ-AI019-006 구현: `fund_manager.py:1700-1718` 필터 제거
- REQ-AI019-007 검증: Path A / Path B 행위 동등성 확인 (동일 입력 → 동일 시그널 집합)
- REQ-AI019-009 구현: `test_surge_ai019_path_b.py` 4 케이스 추가
- 완료 조건: 신규 테스트 4건 통과, 기존 1147 테스트 회귀 없음

### Milestone 4 (Priority: Medium) — MX 태그 + 운영 검증

- REQ-AI019-010 구현: `@MX:ANCHOR`, `@MX:NOTE`, `@MX:LEGACY` 태그 적용
- REQ-AI019-008 검증: 전체 테스트 슈트 실행
- 운영 배포 후 첫 영업일 15:20 잡 결과 사후 쿼리 검증

---

## Risks

### Risk 1: 탐지기별 API 응답 스키마 불일치

각 탐지기가 호출하는 시장 데이터 소스가 동일 종목에 대해 per/pbr 를 동일 키 이름
으로 반환하지 않을 가능성. 일부 소스는 `per` 가 `pe_ratio` 또는 `price_earnings`
로 명명되어 있을 수 있다.

- **완화책**: 탐지기별로 응답 스키마를 사전 점검하고, 필요 시 어댑터 함수
  (`_extract_valuation(market_data) → (per, pbr)`) 를 도입한다.
- **검증**: 각 탐지기 단위 테스트에서 mock market data 에 두 키 변형을 모두 주입
  하여 정상 추출 확인.

### Risk 2: piggy-back 시점에 per/pbr 데이터가 누락된 종목 대량 발생

탐지기 호출 경로의 시장 데이터 응답이 일부 종목에 대해 per/pbr 를 포함하지 않을
경우, 필터가 사실상 비활성화되어 본 SPEC 의 목적이 달성되지 않을 위험.

- **완화책**: 운영 배포 전 staging 또는 dry-run 로그로 per/pbr 결측률을 측정.
  결측률이 임계치(예: 50%) 를 초과하면 Run 단계에서 보조 조회 경로를 검토한다.
- **검증**: 첫 영업일 배포 후 `fund_signals` 의 surge_metadata 에 per/pbr 값
  분포를 사후 분석.

### Risk 3: 기존 `_gather_leading_candidates` 의 후처리 로직이 필터에 의존

`fund_manager.py:1711` 의 필터 제거 후, 같은 함수의 후속 코드가 "필터링된 후보
리스트" 를 가정하고 동작할 가능성. 예: 후속 정렬, 슬라이싱.

- **완화책**: 제거 전 `_gather_leading_candidates` 의 전체 함수 흐름을 검토하여
  필터 직후 코드의 가정을 확인한다. 필요 시 `surge_detector` 로 책임을 옮긴 후
  `_gather_leading_candidates` 가 반환하는 후보 셋이 이미 필터링된 상태인지
  보장한다.
- **검증**: Path A 의 통합 시나리오 테스트(`test_surge_ai018.py` 의 Phase 3
  테스트) 가 변경 없이 통과해야 한다.

### Risk 4: SurgeCandidate dataclass 직렬화 변경의 부작용

per/pbr 필드 추가는 dataclass 의 `__init__`, `asdict` 등 직렬화 결과를 변경한다.
DB 저장 또는 외부 export 경로에서 영향이 발생할 가능성.

- **완화책**: 기본값을 `None` 으로 설정하여 backward-compatible 한 초기화를
  보장한다. 직렬화 경로(`asdict`, JSON dump) 의 단위 테스트를 추가 검토.
- **검증**: `test_surge_detector.py` 의 dataclass 관련 케이스 회귀 없음 확인.

---

## Validation Strategy

### Pre-merge (개발 단계)

1. `pytest backend/tests/test_surge_ai019_path_b.py -v` — 신규 4 케이스 통과
2. `pytest backend/tests/test_surge_ai018.py -v` — Phase 3 회귀 없음
3. `pytest backend/tests/` 전체 슈트 — 1147 테스트 통과
4. `ruff check backend/` 와 `black --check backend/` — 린팅/포맷 통과
5. `mypy backend/app/services/surge_detector.py` — 타입 오류 없음

### Post-merge (배포 후)

1. 첫 영업일 15:20 KST 잡 실행 직후 `fund_signals` 테이블에서 신규
   `surge_candidate` 레코드 추출
2. 각 종목 코드에 대해 별도 PER/PBR 조회를 수행하여 모든 시그널 종목이
   per ≤ 500 그리고 pbr ≤ 30 임을 확인
3. 다음 날 09:00 KST `surge_execute_buys` 의 매수 대상 종목에서도 동일 검증
4. 운영 로그에서 valuation 필터 적용 카운트를 측정 (선택)

---

## Configuration Touchpoints

- `backend/app/surge_config/surge_settings.py:112-115`:
  `ValuationDisqualifiersConfig` (변경 없음, 기존 max_per=500.0, max_pbr=30.0,
  skip_if_missing=true 그대로 사용).
- `backend/app/surge_config/surge_detection.yaml` 의 `valuation_disqualifiers`
  섹션 (변경 없음).

---

## Out of Scope

- PER/PBR 의 영구 저장(stocks 테이블 스키마 변경)은 본 SPEC 에서 다루지 않는다.
- 임계값 조정 (max_per, max_pbr) 은 본 SPEC 의 범위 밖이다.
- 새로운 valuation 지표(EV/EBITDA, ROE 등) 도입은 본 SPEC 범위 밖이다.

---

## Estimated Complexity

| 작업 | 복잡도 | 비고 |
|---|---|---|
| SurgeCandidate 필드 추가 | Low | 단순 dataclass 필드 2개 |
| 3개 탐지기 piggy-back 수집 | Medium | 각 탐지기의 시장 데이터 응답 스키마 확인 필요 |
| 필터 블록 단일 지점 배치 | Low | 기존 SPEC-AI-018 코드를 위치만 이동 |
| 중복 코드 제거 | Low | 단순 삭제 + 후속 로직 검증 |
| 신규 테스트 4 케이스 | Medium | Path B mock 시나리오 구성 |
| 회귀 검증 | Low | 전체 슈트 실행 |
