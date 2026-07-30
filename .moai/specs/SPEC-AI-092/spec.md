---
id: SPEC-AI-092
title: "급등 예측 재현율 회복: 스캔 유니버스 bridge 후보화와 평가 기록 안정화"
version: "0.1.1"
status: completed
created: 2026-07-28
updated: 2026-07-30
author: Nexsol
priority: High
phase: "backend surge-detection v0.1.0"
module: "backend/app/services"
lifecycle: spec-anchored
tags: "surge-detection, scan-universe, recall, prediction-history, adaptive-threshold, backend"
tier: M
depends_on: [SPEC-AI-089]
related_specs: [SPEC-AI-041, SPEC-AI-065, SPEC-AI-068, SPEC-AI-076, SPEC-AI-086, SPEC-AI-088]
---

# SPEC-AI-092: 급등 예측 재현율 회복

## HISTORY

- 2026-07-29 v0.1.1 (draft): 이미 완료된 SPEC-AI-090과 번호가 충돌하지 않도록
  재현율 회복 초안을 SPEC-AI-092로 재번호화했다. 요구사항 범위와 운영 분석 내용은 v0.1.0과 같다.
- 2026-07-28 v0.1.0 (draft): 운영 DB 점검과 2026-07-28 수동 복구 결과를 반영해 초안 작성.
  SPEC-AI-089가 측정한 "스캔 유니버스와 탐지망 간극"의 다음 단계로, 실제 후보 생성 배선과
  평가 기록 안정화를 구현 범위로 정의한다.

## 선행 SPEC

- **SPEC-AI-041**: `surge_prediction_evaluation` 평가 테이블과 T-1 -> T precision/recall 평가.
- **SPEC-AI-068**: `surge_universe_members` 영속화와 scannable recall/coverage 분리.
- **SPEC-AI-086**: `build_scan_universe()`가 측정 전용 그림자 유니버스임을 명시하고 배선을 후속으로 위임.
- **SPEC-AI-089**: 스캔 유니버스와 탐지망 간극을 측정하는 M1 스파이크. 본 SPEC은 측정 이후의 조건부 구현 단계다.
- **SPEC-AI-088**: same-day 후보의 사전 이동폭 계측. 본 SPEC은 same-day 후보를 표준 T-1 -> T 평가에 섞지 않는다.

## Context / Problem

2026-07-28 운영 DB 기준 급등 예측 실패는 단순 threshold 튜닝보다 구조적 입력 손실에 가깝다.

- 2026-07-01 이후 평가일 18개 합산:
  - 예측 205개
  - 실제 급등 1086개
  - TP 8개
  - micro precision 3.90%
  - 시장 전체 recall 0.74%
  - scannable recall 5.03%
  - coverage 14.64%
- 2026-07-28 평가:
  - 예측 7개
  - 실제 급등 23개
  - TP 0개
  - scannable actual 4개
  - coverage 17.39%
- 2026-07-28 non-scannable 19개 원인:
  - source absent 11개
  - scan universe cap에서 truncated 8개

코드 경로상 `gather_surge_candidates()`는 1차 탐지 결과를 `merged`에 합친 뒤
`build_scan_universe()`를 호출한다. 이 universe는 pool count와 평가 지표에는 쓰이지만,
`merged`에 없는 universe member를 공식 `surge_candidate`로 승격하는 경로가 충분하지 않다.

또한 `/prediction-history`는 평가 완료 행에서도 현재 `FundSignal.created_at` 기준 상세 목록 길이로
`predicted_count`를 재계산해 과거 평가 기록이 흔들렸다. `created_at`은 carry-over/update 경로에서
후일로 이동할 수 있으므로, 평가 완료 row의 공식 metric은 평가 테이블 값을 정본으로 사용해야 한다.

## Goals

1. 평가 완료 기록은 평가 당시 공식 predicted set 결과로 고정한다.
2. 스캔 유니버스에 있었지만 기존 탐지망에 들어오지 않은 종목을 제한된 비용 안에서 bridge 후보화한다.
3. adaptive threshold가 예측 생성 gate 또는 매수 실행 gate 중 어디에 쓰이는지 명확히 하고 테스트한다.
4. actual/evaluation 누락을 운영상 감지하고 수동 재실행을 idempotent하게 유지한다.
5. 모든 예측 로직 변경은 feature flag 기본 OFF로 배포한다.

## Non-Goals

### Out of Scope — 예측 로직 및 범위 제한

- 같은 날 이미 오른 종목의 `horizon="same_day"` 후보를 표준 T-1 -> T predicted set에 포함하지 않는다.
- BEAR regime의 매수 실행 차단 정책은 바꾸지 않는다.
- LLM miss analysis 개선은 본 SPEC 범위가 아니다.
- 전체 시장 급등주를 모두 예측 대상으로 만들지 않는다. coverage와 scannable recall은 계속 분리해 본다.

## Requirements

### REQ-AI092-001: 평가 완료 기록 카운트 불변

When `/api/surge-trading/prediction-history`가 평가 완료 row를 반환하면, 시스템은
`SurgePredictionEvaluation.predicted_count`를 공식 `predicted_count`로 반환해야 한다.

구현 참고:

- 현재 `FundSignal` 재조회 결과는 상세 표시용으로만 사용한다.
- 상세 목록 길이와 평가 테이블 카운트가 다를 수 있음을 허용한다.

### REQ-AI092-002: 평가 predicted set 스냅샷

When `evaluate_surge_predictions()`가 평가를 저장하면, 시스템은 near-limit carry와 same-day horizon을
제외한 공식 predicted set을 후일 복원할 수 있도록 저장해야 한다.

허용 구현안:

- `surge_prediction_evaluation.predicted_codes_json`
- 또는 `surge_prediction_signal_snapshot` 별도 테이블

필수 조건:

- `FundSignal.created_at`이 후일 이동해도 평가 당시 predicted set을 복원할 수 있어야 한다.
- 기존 API 응답 필드는 하위 호환을 유지해야 한다.

### REQ-AI092-003: 스캔 유니버스 bridge 후보화

When `scan_universe_bridge_candidates_enabled=true`이면, 시스템은 `build_scan_universe()` 결과 중
`merged`에 없는 종목을 비용 제한 안에서 bridge 후보로 평가할 수 있어야 한다.

필수 조건:

- feature flag 기본값은 false다.
- flag OFF 상태에서 `gather_surge_candidates()` 출력은 기존과 동일해야 한다.
- 신규 네트워크 호출은 기본 금지한다.
- bridge 후보의 `surge_metadata.surge_basis`에는 `scan_universe_bridge`와 원 entry pool을 기록한다.
- bridge 후보는 표준 T-1 -> T 평가 지평을 따른다. `horizon="same_day"`는 기존처럼 표준 predicted set에서 제외한다.

### REQ-AI092-004: bridge scoring

When bridge 후보를 평가하면, 시스템은 이미 수집된 DB/인메모리 데이터만 사용해 pool별 점수를 계산해야 한다.

권장 1차 점수:

- Pool A: 공시 impact score, unreflected gap, 공시 유형 whitelist.
- Pool C: 전일 등락률, 거래량/뉴스 동반 여부, 섹터 동조 여부.
- Pool D: 뉴스 언급량 증가, 직접 매핑 뉴스 수, 중복 제거 후 유효 기사 수.

필수 조건:

- 전체 bridge 후보 수 상한을 둔다.
- pool별 상한을 둘 수 있어야 한다.
- 산출된 후보는 기존 `SurgeCandidate` 구조에 맞춰 downstream scoring을 통과해야 한다.

### REQ-AI092-005: adaptive threshold 연결성

When adaptive threshold가 계산/저장된 날이면, 시스템은 그 threshold가 예측 생성 gate 또는 매수 실행
gate 중 어디에 적용되는지 명시적으로 보장해야 한다.

필수 조건:

- 예측 생성 threshold와 매수 실행 threshold가 다르면 설정명과 로그명을 분리한다.
- threshold 0.30과 0.70 fixture에서 저장 후보 수 차이가 테스트로 관찰되어야 한다.
- threshold history가 없는 날의 fallback 경로를 테스트해야 한다.

### REQ-AI092-006: 운영 평가 누락 감시

When 장마감 이후 지정 시각이 지나면, 시스템은 당일 actual/evaluation 레코드 누락 여부를 감지해야 한다.

필수 조건:

- `surge_actual_outcome.trading_date=today` 부재를 감지한다.
- `surge_prediction_evaluation.evaluation_date=today` 부재를 감지한다.
- 수동 재실행은 idempotent해야 한다.
- `stocks` 마스터에 없는 untracked mover가 actual outcome에 섞이지 않도록 수집 단계 또는 정리 단계에서 방어한다.

## Open Questions

1. bridge 후보의 1차 목표 지표는 coverage 개선인가, scannable recall 개선인가?
2. 평가 스냅샷은 JSON 컬럼으로 충분한가, 별도 테이블이 필요한가?
3. Pool C floor는 유지할지, truncated 비율이 높을 때 동적으로 늘릴지 결정해야 한다.
4. actual outcome 수집 대상은 상위 movers 전체 보존인가, `stocks` 마스터 종목 한정인가?
