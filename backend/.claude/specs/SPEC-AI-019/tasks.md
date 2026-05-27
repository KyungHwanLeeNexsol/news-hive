---
id: SPEC-AI-019
type: tasks
version: 0.1.0
status: planned
created: 2026-05-27
updated: 2026-05-27
author: Nexsol (manager-strategy)
---

# SPEC-AI-019 Task Decomposition

본 문서는 SPEC-AI-019 (급등 시그널 밸류에이션 필터 적용 범위 확장) 의
실행 계획을 원자적 태스크로 분해한다. 각 태스크는 단일 DDD ANALYZE-PRESERVE-IMPROVE
사이클에서 완결되도록 설계되었다.

## 실행 순서 원칙

- T-001 ~ T-002 는 데이터 수집 기반 (Milestone 1 의 토대).
- T-003 ~ T-005 는 3개 탐지기에 piggy-back 수집을 추가 (각 탐지기 독립 단위로 분할).
- T-006 은 단일 지점 필터 배치 (Milestone 2 의 핵심, T-001~T-005 모두 완료 후 수행).
- T-007 은 중복 코드 제거 (Milestone 3, T-006 완료 후 수행하여 회귀 위험 최소화).
- T-008 은 신규 회귀 방지 테스트.
- T-009 는 MX 태그 적용 및 전체 회귀 슈트 실행 (마지막 단계).

각 태스크의 `Planned Files` 열은 Drift Guard 의 비교 기준이 되므로, 실제 구현 시
이 목록에 명시된 파일만 수정해야 한다. 수정 범위 확대가 필요한 경우 SPEC 으로 돌아
가서 plan 을 갱신한 뒤 진행한다.

---

## Task Table

| Task ID | Description | Requirement | Dependencies | Planned Files | Status |
|---|---|---|---|---|---|
| T-001 | SurgeCandidate 모델에 per/pbr 필드 추가 (`float \| None = None` 기본값, `price_5d_trend` 필드 인접 위치). characterization test 로 기존 dataclass 직렬화 (`asdict`) 와 `__init__` 호환성 스냅샷 확보. | REQ-AI019-001 | (없음) | MODIFY: backend/app/services/surge_detector.py (SurgeCandidate dataclass 근처, line ~72) | ✓ completed |
| T-002 | `_extract_valuation(market_data) → (per, pbr)` 어댑터 헬퍼 함수 추가. 외부 시장 데이터 응답의 키 변형 (`per` vs `pe_ratio`, `pbr` vs `price_to_book` 등) 을 흡수. unit-tested 헬퍼 로 3개 탐지기가 공통 사용. | REQ-AI019-002 (Risk 1 mitigation) | T-001 | MODIFY: backend/app/services/surge_detector.py (helper 함수 추가) | ✓ completed |
| T-003 | `detect_theme_cluster_candidates` 탐지기에 per/pbr piggy-back 수집 추가. 기존 시장 데이터 fetch 결과를 `_extract_valuation` 으로 통과시켜 SurgeCandidate 에 채움. 추가 외부 API 호출 0건 보장. | REQ-AI019-002 | T-002 | MODIFY: backend/app/services/surge_detector.py (`detect_theme_cluster_candidates` 본문) | ✓ completed |
| T-004 | `detect_volume_news_combo_candidates` 탐지기에 per/pbr piggy-back 수집 추가. | REQ-AI019-002 | T-002 | MODIFY: backend/app/services/surge_detector.py (`detect_volume_news_combo_candidates` 본문) | ✓ completed |
| T-005 | `detect_disclosure_pattern_candidates` 탐지기에 per/pbr piggy-back 수집 추가. | REQ-AI019-002 | T-002 | MODIFY: backend/app/services/surge_detector.py (`detect_disclosure_pattern_candidates` 본문) | ✓ completed |
| T-006 | `surge_detector.detect_surge_candidates()` 의 앙상블 스코어 계산 직전 단계에 valuation_disqualifiers 필터 단일 지점 배치. `ValuationDisqualifiersConfig` 를 `surge_settings` 에서 로드. None/0 통과 규칙 보존. 경계값 strict greater-than 보존. | REQ-AI019-003, REQ-AI019-004, REQ-AI019-005 | T-003, T-004, T-005 | MODIFY: backend/app/services/surge_detector.py (`detect_surge_candidates`, line ~900-1050) | ✓ completed |
| T-007 | `fund_manager.py:1700-1718` 의 중복 valuation 필터 코드 제거. 제거 전 `_gather_leading_candidates` 후속 코드의 가정 (Risk 3) 검증을 위한 characterization test 확보. 커밋 메시지에 `@MX:LEGACY SPEC-AI-019` 명시. | REQ-AI019-006 | T-006 | MODIFY: backend/app/services/fund_manager.py (line 1700-1718 제거, `_gather_leading_candidates` 함수 범위) | ✓ completed |
| T-008 | 신규 단위 테스트 파일 `test_surge_ai019_path_b.py` 작성. 4 필수 케이스 (per>500 제외, pbr>30 제외, per=None 통과, 정상값 통과) + 권장 케이스 (Path A/B parity, per=0 결측 동치, piggy-back API 호출 카운트=0, 경계값). `unittest.mock.patch` 로 외부 의존성 차단. | REQ-AI019-009, REQ-AI019-007 검증 | T-006, T-007 | NEW: backend/tests/test_surge_ai019_path_b.py | ✓ completed |
| T-009 | MX 태그 적용 (`@MX:NOTE` for per/pbr fields, `@MX:ANCHOR SPEC-AI-019` for filter block) 및 전체 회귀 슈트 실행. `pytest backend/tests/` 1147+ 테스트 통과 확인. `pytest backend/tests/test_surge_ai018.py` 회귀 0건. ruff/black/mypy 통과. | REQ-AI019-010, REQ-AI019-008 | T-001 ~ T-008 | MODIFY: backend/app/services/surge_detector.py (MX 태그 주석만) | ✓ completed |

---

## Atomicity Verification

각 태스크가 DDD 단일 사이클에서 완결 가능함을 다음 기준으로 확인:

- **T-001**: dataclass 필드 2개 추가 (Low complexity, 단순 변경). characterization test 로 기존 직렬화 보존.
- **T-002**: 단일 헬퍼 함수, 입출력 명확, unit test 가능.
- **T-003 ~ T-005**: 동일 패턴의 탐지기 instrumentation, 각각 독립 함수 1개 수정.
- **T-006**: 기존 SPEC-AI-018 코드 위치 이동 + config accessor 호출 (Low complexity).
- **T-007**: 단순 코드 블록 삭제 + 후속 로직 검증.
- **T-008**: 신규 테스트 파일, 격리된 단위.
- **T-009**: 비기능적 작업 (태그 + 회귀 슈트).

각 태스크는 다른 태스크의 내부 구현에 의존하지 않으며, 명시된 `Dependencies` 만으로
순서가 결정된다.

---

## Drift Guard 비교 기준

Phase 2 (manager-ddd) 가 각 태스크를 실행할 때, 실제 수정 파일 집합을 위 `Planned
Files` 열과 비교한다. 다음 위반은 Drift 로 간주된다:

- Planned 에 없는 파일 수정 (예: 다른 모듈 손댐)
- Planned 에 있는 파일을 수정하지 않고 우회
- Planned 의 NEW 라벨 파일을 다른 경로로 생성

Drift 발견 시 Phase 2 에이전트는 작업을 일시 중단하고 사용자에게 plan 갱신을 요청한
다.

---

## Out-of-Scope Reminder

다음은 본 SPEC 의 어떤 태스크에도 포함되지 않는다 (spec.md `Exclusions` 참조):

- PER/PBR 의 `stocks` 테이블 영구 저장 (스키마 변경 금지)
- `valuation_disqualifiers` 임계값 변경 (max_per, max_pbr 기본값 유지)
- `_recent_surge_penalty` 또는 Phase 4 그룹 컨센서스 배율 수정
- `run_surge_signal_generation` 의 스케줄 시각 변경
- 새 valuation 지표 (EV/EBITDA, ROE 등) 도입
