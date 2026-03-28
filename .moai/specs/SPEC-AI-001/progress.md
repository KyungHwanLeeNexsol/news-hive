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

### Phase C (진행 중)
- [ ] REQ-AI-011: ML 앙상블 모델 (90일+ 데이터 축적 필요)
- [ ] REQ-AI-012: 섹터 전파 모델 (90일+ 데이터 축적 필요)
- [x] REQ-AI-013: 페이퍼 트레이딩 시뮬레이션 (commit 2f7b16f)
  - 백엔드: 모델 3개, 서비스, API 5개, 마이그레이션
  - 프론트엔드: fund 페이지 페이퍼트레이딩 탭
  - 자동 매매: 시그널 생성 시 자동 가상 매매 연동
  - 스케줄러: 장중 청산 체크(1h) + 일일 스냅샷(16:00 KST)

### 통합 작업 (완료)
- [x] fund_manager.py에 factor_scoring 통합 호출 (commit b56b509)
- [x] fund_manager.py에 prompt_version 할당 연동 (commit b56b509)
- [x] fund_manager.py 프롬프트에 오류 패턴 분포 주입 (commit b56b509)
- [x] fund_manager.py 프롬프트에 섹터별 뉴스 임팩트 통계 주입 (commit b56b509)
- [x] calibrate_confidence()를 시그널 생성 파이프라인에 연결 (commit b56b509)
