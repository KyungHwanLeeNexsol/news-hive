---
id: SPEC-AI-109
title: "급등예측 평가 누락 자동복구 및 관리자 백필"
version: "0.1.0"
status: completed
created: 2026-08-07
updated: 2026-08-07
author: Nexsol
priority: Critical
phase: "backend surge-evaluation v0.1.0"
module: "backend/app/services"
lifecycle: spec-anchored
tags: "surge-evaluation, backfill, scheduler, admin-api, operations"
tier: S
related_specs: [SPEC-AI-041, SPEC-AI-061, SPEC-AI-086, SPEC-AI-092, SPEC-AI-095, SPEC-AI-101, SPEC-AI-108]
---

# SPEC-AI-109: 급등예측 평가 누락 자동복구 및 관리자 백필

## Context

2026-08-07 운영 점검에서 공식 급등예측 평가는 2026-08-03까지만 존재했고,
2026-08-04 이후 `/api/surge-trading/evaluation/{date}`가 404를 반환했다. 신호
생성은 계속 살아 있었으므로 문제는 예측기 자체보다 장마감 actual outcome 수집 또는
평가 row 생성 경로의 누락 복구 부재였다.

기존 SPEC-AI-092는 `detect_missing_evaluation_records()`와
`check_and_alert_missing_evaluation()`로 누락을 감지하고 알림을 보냈지만, 실제
복구는 수행하지 않았다. 기존 `POST /api/surge-trading/re-evaluate/{date}`도
`surge_actual_outcome`이 이미 존재한다는 전제가 있어, actual outcome 자체가 없는
날짜에는 충분하지 않았다.

## Goals

1. actual outcome과 evaluation row 누락을 하나의 멱등 복구 함수로 처리한다.
2. 19:15 KST 누락 감시 잡이 알림에서 끝나지 않고 당일 자동복구를 시도한다.
3. 운영자가 SSH 없이 관리자 API로 날짜 범위 백필을 실행할 수 있게 한다.
4. actual outcome 수집 후에도 row가 없으면 평가 row 생성을 건너뛰어 잘못된
   `actual_surge_count=0` 평가를 남기지 않는다.
5. 기존 actual 수집 함수가 현재 상위 상승 종목을 조회하는 한계 때문에, 과거 날짜
   actual outcome이 없을 때는 자동 수집을 기본 차단한다.

## Non-Goals

- 급등 예측 알고리즘, scan universe bridge 활성화, detector 가중치, threshold 값을
  변경하지 않는다.
- 신규 DB 테이블, 컬럼, alembic migration을 추가하지 않는다.
- 2026-08-04 이후 운영 DB 백필 실행 자체는 배포 후 운영 명령/API 호출 단계로 남긴다.
- 과거 날짜의 actual outcome을 전체 종목 히스토리로 재구성하는 대형 백필러는 만들지
  않는다. 과거 날짜는 actual row가 이미 있을 때 evaluation만 복구한다.

## Requirements

### REQ-AI109-001 (P0, Event-Driven) — actual+evaluation 복구 함수

**When** 지정 거래일의 `surge_actual_outcome` 또는 `surge_prediction_evaluation`
row가 누락된 동안, the system **shall** `repair_missing_surge_evaluation()`으로
actual outcome 수집과 평가 생성을 순서대로 시도해야 한다.

필수 조건:

- actual outcome이 없으면 `collect_daily_surge_outcomes()`를 먼저 실행한다.
- 단, 지정 거래일이 오늘(KST)이 아니면 과거 actual 자동수집은 기본 차단하고
  `skipped_historical_actual_collection_unavailable`을 반환한다.
- 수집 후에도 actual outcome row가 없으면 `evaluate_surge_predictions()`를 호출하지
  않는다.
- 평가 실행 시 T-1 pool_counts와 직전 scannable metrics를 fail-open으로 주입한다.
- 이미 두 row가 모두 있으면 외부 수집/평가를 호출하지 않고 no-op으로 종료한다.

### REQ-AI109-002 (P0, Event-Driven) — 감시 잡 자동복구

**When** `_run_surge_missing_evaluation_check()`가 actual 또는 evaluation 누락을
감지하면, the system **shall** `repair_missing_surge_evaluation()`을 1회 호출해야
한다. 복구 실패는 warning/error 로그로 격리하고 스케줄러 프로세스를 중단시키지
않아야 한다.

### REQ-AI109-003 (P0, Event-Driven) — 관리자 날짜 범위 백필 API

**When** 관리자가 `POST /api/surge-trading/evaluation-backfill`을 호출하면, the
system **shall** `start_date`부터 `end_date`까지의 거래일에 대해
`repair_missing_surge_evaluation()`을 실행하고 날짜별 결과를 반환해야 한다.

필수 조건:

- Authorization Bearer 관리자 토큰을 요구한다.
- 한 번에 최대 32 calendar days까지만 허용한다.
- 비거래일은 `skipped_non_trading_day`로 표시한다.
- 한 날짜 실패가 전체 범위 백필을 중단하지 않고 해당 날짜 결과에 `failed`로 남는다.

## Acceptance Criteria

- AC-109-001: actual/evaluation 둘 다 없는 날짜에서 actual 수집 성공 후 평가가 생성된다.
- AC-109-002: actual 수집 후에도 row가 없으면 평가 생성을 건너뛴다.
- AC-109-003: 과거 날짜 actual이 없으면 현재 데이터로 수집하지 않고 스킵한다.
- AC-109-004: 이미 두 row가 모두 있으면 수집/평가 함수가 호출되지 않는다.
- AC-109-005: 누락 감시 스케줄러는 누락 감지 시 복구 함수를 호출한다.
- AC-109-006: 백필 API는 관리자 인증 없이는 401을 반환한다.
- AC-109-007: 백필 API는 거래일 범위의 각 날짜에 복구 함수를 호출하고 결과를 반환한다.
