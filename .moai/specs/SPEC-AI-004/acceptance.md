# SPEC-AI-004 수용 기준 체크리스트

## 공시 충격 스코어링 (P1)
- [ ] AC-001: `score_disclosure_impact()` 수주 10% → impact_score=50
- [ ] AC-004: 이미 반영된 공시에서 FundSignal 미생성

## 미반영 갭 탐지 (P1)
- [ ] AC-002: 30분 후 `reflected_pct` DB 저장
- [ ] AC-003: 갭 >= 15 → FundSignal 생성

## 동종업계 파급 (P2)
- [ ] AC-005: 섹터 파급 후보 탐지

## 갭업 풀백 전략 (P3)
- [ ] AC-006: 장마감 후 공시 → `gap_pullback_candidate` 생성

## 페이퍼트레이딩 연동 (P3)
- [ ] AC-007: FundSignal 생성 → `execute_paper_trade()` 자동 호출
- [ ] AC-009: 방어 모드 시 매수 차단

## 백테스팅 API (P3)
- [ ] AC-008: `/api/v1/portfolio/backtest-stats` 응답 검증

## 품질 게이트
- [ ] AC-010: 테스트 커버리지 >= 85%
