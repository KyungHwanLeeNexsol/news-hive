# SPEC-AI-068 (compact)

- id: SPEC-AI-068 | status: draft | priority: High | created: 2026-07-02
- title: 급등예측 평가지표 재정의 & 스캔 유니버스 진단 인프라
- goal: recall을 Scannable Recall(알고리즘 품질) + Coverage(유니버스 설계 품질)로 분리 측정.
  근본진단: 최근 17일 중 15일 TP=0은 파라미터가 아닌 **평가지표 구조** 문제.
- root cause: `surge_evaluation_service.py:531-535` 주석 "actual_outcome==스캔 유니버스"는 거짓.
  actual은 `surge_actual_outcome_service.py:44-47` 시장 top-100 무버 → recall 구조적 상한 ~22%
  (2026-07-01 실제급등 123 중 78%가 전일 유니버스 밖). 유니버스 코드 미영속화
  (`surge_universe_pool_history.py` 개수만).

## REQ (5)
- REQ-AI068-001 (P0, Event): WHEN 유니버스 구성 시, 종목코드+풀태그를 거래일별 영속화(구성 로직 불변).
- REQ-AI068-002 (P0, Event): WHEN 평가 시, Scannable Recall=|유니버스∩실제∩발신|/|유니버스∩실제| 산출.
- REQ-AI068-003 (P0, Event): WHEN 평가 시, Coverage=|유니버스∩실제|/|전체실제| 분리 저장.
- REQ-AI068-004 (P0, Unwanted): IF 유니버스 영속화 존재, THEN 시장 top-movers를 recall 분모로 쓰지 않음(:531-535 제거).
- REQ-AI068-005 (P1, Ubiquitous): 실제급등주 scannable/non-scannable 라벨링, 공식목표=scannable만.
  non-scannable 실시간 트랙은 경계 정의만.

## Exclusions
- 당일 촉매형(~78%) 실시간 조기탐지 파이프라인 구현 제외(별도 후속 SPEC)
- 유니버스 구성 로직(build_scan_universe/우선순위/상한) 변경 제외(AI-065 소유)
- 탐지기 파라미터/가중치/임계값 변경 제외
- 자동개선 루프·backtest·calibrator 변경 제외(AI-069 소유)

## Deps
- extends AI-065(유니버스)/AI-041(평가루프)/AI-043(예측기록). 순서 068→069(069 REQ-003이 Scannable Recall 소비).
