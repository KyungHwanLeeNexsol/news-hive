## Task Decomposition
SPEC: SPEC-AI-081

| Task ID | Description | Requirement | Dependencies | Planned Files | Status |
|---------|-------------|-------------|---------------|--------|--------|
| T1 | 특성화 테스트(ANALYZE-PRESERVE): 3개 실증 사례(465770/038880/006340) 스타일 입력의 수정 전 flat 거동(20/20/25) 재현. 하위 소비자 임계 분기 통합 테스트 | REQ-007 | - | test_disclosure_impact_scorer.py, test_disclosure_impact_scorer_immediate_surge.py | done |
| T2 | 설정 플래그 도입: `DisclosureContentAwareScoringConfig` 추가, 기본값 false | REQ-004 | T1 | surge_settings.py, surge_detection.yaml | done |
| T3 | 최대주주 지배권 변경 키워드 커버리지 확장(IMPROVE): 정규화 매칭 헬퍼, 006340형 재현 테스트 | REQ-001 | T2 | disclosure_impact_scorer.py | done |
| T4 | 희석성 증권 발행결정 로컬 재분류(IMPROVE): `effective_report_type` 분기, 038880형 차등처리 테스트 | REQ-002 | T2 | disclosure_impact_scorer.py | done |
| T5 | ai_summary 비의존성 검증: None vs 임의 텍스트 동일 반환값 테스트 | REQ-003 | T3, T4 | test_disclosure_impact_scorer.py | done |
| T6 | 오탐 방지 회귀 가드: 465770형(무신호) flat 유지 명시 테스트 | REQ-005 | T3, T4 | test_disclosure_impact_scorer.py | done |
| T7 | 불변식 회귀 가드: 다른 5개 report_type, 하위 소비자 게이팅, report_type 저장값 diff 0 검증, 전체 스위트 무회귀 | REQ-006 | T3, T4 | test_disclosure_impact_scorer.py, test_disclosure_impact_scorer_immediate_surge.py | done |
| T8 | 백워드 호환 검증: 토글 비활성 시 레거시 완전 동등 테스트 | REQ-004 | T7 | test_disclosure_impact_scorer.py | done |
| T9 | 관측성 로깅 + MX 태그(NOTE/ANCHOR) | REQ-008 | T3, T4 | disclosure_impact_scorer.py | partial (MX NOTE/WARN 태그는 완료; 런타임 로깅은 미구현 — 파일당 NOTE 태그 상한(10) 근접으로 리스크 최소화 판단, P2/선택 요구사항이라 스킵) |

This file is git-tracked. Update task status as implementation progresses.
The planned_files column is used by the Drift Guard (Phase 2A/2B) to detect scope drift.
