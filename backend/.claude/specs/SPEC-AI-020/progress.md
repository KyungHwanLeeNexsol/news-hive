## SPEC-AI-020 Progress — 최종 완료

- Started: 2026-05-28T00:00:00Z (UTC)
- Phase 2 PRESERVE: CT-A/CT-B/CT-C 캡처 완료. 베이스라인: 84 passed
  - CT-A: SurgeCandidate 필드 셋 베이스라인 — per/pbr 없음 (SPEC-AI-019 미구현)
  - CT-B: Phase 3 config schema 4개 테스트 → retire 대상
  - CT-C: test_surge_ai018(30) + test_surge_detector(22) + test_surge_scoring(22) = 84 passed
  - test_surge_ai019_path_b.py: 존재하지 않음 (SPEC-AI-019 미구현)
  - fund_manager.py 필터 블록: 라인 1707-1724 확인

### ANALYZE 단계 결과

- 실제 함수명:
  - detect_theme_news_cluster (라인 99)
  - detect_volume_surge_news_combo (라인 330)
  - detect_disclosure_surge_pattern (라인 578)
  - gather_surge_candidates (라인 864, orchestrator)
- SPEC-AI-019 미구현 항목 (SPEC-AI-020에서 함께 구현):
  - SurgeCandidate.per / SurgeCandidate.pbr 필드
  - _extract_valuation 헬퍼
  - 3개 탐지기 piggy-back 수집
  - test_surge_ai019_path_b.py
- SPEC-AI-018 필터 블록: fund_manager.py 1707-1724 (try/except 포함)

### IMPROVE 단계 완료 (2026-05-28T UTC)

- T-001 complete: SurgeCandidate에 per/pbr 필드 추가 (data-only, @MX:NOTE)
- T-002 complete: _extract_valuation 헬퍼 추가 (piggy-back, no new API calls)
- T-003 complete: detect_theme_news_cluster piggy-back per/pbr 수집 추가
- T-004 complete: detect_volume_surge_news_combo piggy-back per/pbr 수집 추가
- T-005 complete: detect_disclosure_surge_pattern piggy-back per/pbr 수집 추가
- T-006 complete: fund_manager.py 라인 1707-1724 필터 블록 제거 (SPEC-AI-018 REQ-007)
- T-007 complete: gather_surge_candidates에 valuation filter 없음 확인 (grep 검증)
- T-008 complete: ValuationDisqualifiersConfig docstring deprecated 처리
- T-009 complete: surge_detection.yaml deprecated 주석 추가
- T-010 complete: test_surge_ai018.py Phase 3 클래스 4개 @pytest.mark.skip(retire)
- T-011 complete: test_surge_ai020_no_filter.py 17개 신규 테스트 생성 (전체 통과)
- T-012 complete: MX 태그 정리, 특성화 테스트 per/pbr 스냅샷 업데이트

- Phase 2 IMPROVE complete: 2026-05-28T UTC
- Tests: 104 passed (surge 관련), 4 skipped (Phase 3 retired), 17 new test cases (T-011)
- Files modified: 5 (surge_detector.py, fund_manager.py, surge_detection.yaml, surge_settings.py, test_surge_ai018.py)
- Files created: 3 (test_surge_ai020_characterization.py, test_surge_ai020_no_filter.py, progress.md)
- Tests retired: 4 (TestPhase3ValuationDisqualifier — schema 검증은 characterization test로 이관)
- Filter removal verified: no active valuation filter in surge_detector.py OR fund_manager.py
