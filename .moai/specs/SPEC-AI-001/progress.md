## SPEC-AI-001 Progress

- Started: 2026-03-28

### Phase A (완료)
- [x] REQ-AI-001: 매수 필터링 임계값 완화 (commit 7e1f29b)
- [x] REQ-AI-002: 시간 가중 뉴스 스코어링 (commit 7e1f29b)
- [x] REQ-AI-003: 오류 패턴 분류 시스템 (commit 7e1f29b)
- [x] REQ-AI-004: Bayesian confidence 보정 (commit 7e1f29b)

### Phase B (완료)
- [x] REQ-AI-005: 빠른 검증 루프 6h/12h (fast_verify + scheduler job)
- [x] REQ-AI-006: 독립 팩터 점수 산출 (factor_scoring.py)
- [x] REQ-AI-007: 팩터 기여도 추적 (factor_scoring.py)
- [x] REQ-AI-008: A/B 테스트 프레임워크 (prompt_versioner.py)
- [x] REQ-AI-009: 뉴스 임팩트 통계 학습 (news_price_impact_service.py)
- [x] REQ-AI-010: 매크로 NLP 분류기 (macro_risk.py async 전환)

### Phase C (미착수)
- [ ] REQ-AI-011: ML 앙상블 모델
- [ ] REQ-AI-012: 섹터 전파 모델
- [ ] REQ-AI-013: 페이퍼 트레이딩 시뮬레이션

### 통합 작업 (미완료)
- [ ] fund_manager.py에 factor_scoring 통합 호출
- [ ] fund_manager.py에 prompt_version 할당 연동
- [ ] fund_manager.py 프롬프트에 오류 패턴 분포 주입
- [ ] fund_manager.py 프롬프트에 섹터별 뉴스 임팩트 통계 주입
- [ ] calibrate_confidence()를 시그널 생성 파이프라인에 연결
