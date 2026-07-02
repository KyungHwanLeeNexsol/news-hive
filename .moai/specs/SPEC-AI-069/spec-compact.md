# SPEC-AI-069 (compact)

- id: SPEC-AI-069 | status: draft | priority: High | created: 2026-07-02
- title: Backtest 운영 게이트 & 자동개선 거버넌스 & z-score 회귀 격리
- goal: 검증 없는 자동개선 루프가 깨진 recall을 좇아 자기 마비. backtest를 운영 게이트로 승격,
  자동개선 전면 중단·기본값 리셋 후 backtest 가드+Scannable Recall(068) 재설계, z-score flag 격리,
  calibrator 정리.
- root cause: backtest dead code(`surge_backtest.py:36` 호출처=수동 `fund_manager.py:560`뿐,
  scheduler.py 잡 0건); calibrator no-op(`surge_calibrator.py:18` pkl 부재→identity);
  auto-improve가 깨진 recall 추종(`surge_auto_improver.py:355`, min_score :539-570); z-score 회귀
  (`surge_baseline_service.py:82-89` sigmoid, AI-065 소유, 임계값 재도출 없음).

## 사용자 확정 결정 (2026-07-02)
- D1 068+069만 작성(070 후속) · D2 루트 `.moai/specs/` · D3 z-score flag 기본 false→절대채점 폴백
- D4 자동개선 전체 중단(스케줄러 잡 비활성 + auto.yaml 리셋: min_score=0.38, legacy 가중치 복원)

## REQ (5)
- REQ-AI069-001 (P0, Event): WHEN backtest 잡 실행, compute_surge_backtest pass/fail 판정 영속화(스케줄러 편입).
- REQ-AI069-002 (P0, Unwanted): IF 배포, THEN 자동개선 전면 중단 + auto.yaml base 기본값 리셋(min_score=0.38, legacy 복원). [D4]
- REQ-AI069-003 (P0, State): WHILE 재활성, backtest canary 통과분만 반영 + 목표를 Scannable Recall(068)로. (재활성 기본 off)
- REQ-AI069-004 (P0, Where): WHERE z-score 경로 존재, flag 기본 DISABLED→절대채점 폴백. 재활성=backtest 재보정 후. [D3]
- REQ-AI069-005 (P1, Unwanted): IF calibrator pkl 부재, THEN identity 무효를 표면화 + 학습연결 or 명시적 제거.

## Exclusions
- 개별 탐지기 파라미터 튜닝(backtest 선행) · Scannable Recall 지표 구현(068 소유) · 유니버스 구성(065)
- z-score 알고리즘 재작성(flag만) · 신규 탐지기 · 실매매 변경(043) · 탐지기 기여도 검증(070 후속, D1)

## Deps / Rollout
- [HARD] 068 선행(REQ-003이 Scannable Recall 소비). AI-041/061/065 거버넌스.
- Rollout: M1 즉시 중단/리셋+z-score off → M2 backtest 축적 → M3(068 후) 가드+재타게팅 재활성.
  각 REQ 독립 flag 롤백. Deploy Guard 15:15~15:45 KST 준수.
