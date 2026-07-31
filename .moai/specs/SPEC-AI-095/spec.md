---
id: SPEC-AI-095
title: "고가 기준(high_change_rate) 평가지표의 공식 평가 리포트 노출"
version: "0.1.0"
status: completed
created: 2026-07-31
updated: 2026-07-31
author: Nexsol
priority: Medium
phase: "backend surge-detection v0.1.0"
module: "backend/app/services"
lifecycle: spec-anchored
tags: "surge-detection, evaluation-metric, high-change-rate, observability, backend"
tier: M
related_specs: [SPEC-AI-041, SPEC-AI-068, SPEC-AI-092, SPEC-AI-093, SPEC-AI-094]
---

# SPEC-AI-095: 고가 기준(high_change_rate) 평가지표의 공식 평가 리포트 노출

## HISTORY

- 2026-07-31 v0.1.0 (draft): 이 세션에서 두 항목(existing_codes 병합 필터 교정 + high_change_rate
  평가 노출)을 하나의 SPEC으로 요청받았으나, 조사 결과 첫 번째 항목이 이미 `SPEC-AI-094`(draft,
  2026-07-30 작성, 동일 버그·거의 동일한 코드 라인)와 실질적으로 상충하는 설계(플래그 게이팅
  기본 비활성 vs. 이번 요청의 무조건 즉시 수정)를 갖는 것을 확인했다. 근거 없이 어느 설계를 택할지
  임의로 결정하지 않기 위해 그 항목은 본 SPEC 범위에서 제외하고(§Out of Scope 참고), 독립적으로
  충돌 없는 두 번째 항목(고가 기반 평가지표 노출)만 SPEC화한다. 두 번째 항목도 조사 중 위임
  프롬프트의 함수 위치 인용(`surge_evaluation_service.py:459-523`)이 실제와 달라 정정했다 —
  `evaluate_high_based_outcomes()`는 `surge_actual_outcome_service.py:459-523`(SPEC-AI-093
  REQ-AI093-005)에 이미 존재하며, `surge_evaluation_service.py`의 공식 평가 함수
  `evaluate_surge_predictions()`(:658)는 이를 전혀 참조하지 않음을 코드로 직접 확인했다(§Context).

## 선행 SPEC

- **SPEC-AI-093** (완료, 2026-07-30): `high_change_rate` 실측 수집 + 파생 판정 함수
  `evaluate_high_based_outcomes()`를 도입했다(REQ-AI093-005). 그 SPEC의 Open Question 2
  ("고가 기반 파생 지표의 노출 표면 — 평가 로그까지인가, `/prediction-history` API 응답까지인가?")가
  본 SPEC이 이행하는 유보 사항이다.
- **SPEC-AI-068**: `SurgePredictionEvaluation`에 `scannable_recall`/`coverage`/
  `scannable_actual_count` 3개 nullable 컬럼을 추가한 선례(migration 065). 본 SPEC의
  컬럼 추가·병렬 지표 설계가 그 패턴을 그대로 재사용한다.
- **SPEC-AI-092**: `predicted_count`/`predicted_codes_json` 스냅샷 고정. 본 SPEC이 재사용하는
  `predicted_set`이 그 스냅샷과 동일 시점 값임을 보장한다(무관 병행, 충돌 없음).
- **SPEC-AI-041**: `evaluate_surge_predictions()`와 `SurgePredictionEvaluation` 모델의 원 소유 SPEC.
- **SPEC-AI-094** (draft, 2026-07-30): 본 SPEC의 원 요청에 포함되어 있던 `existing_codes` 병합
  필터 버그를 이미 선점하고 있다. §Out of Scope 참고 — 본 SPEC은 그 항목을 다루지 않는다.

## Context / Problem

### `evaluate_high_based_outcomes()`는 존재하지만 공식 평가 경로에서 참조되지 않는다

`backend/app/services/surge_actual_outcome_service.py:459-523`에 다음 함수가 이미 구현되어
있다(SPEC-AI-093 REQ-AI093-005, TASK-004):

```python
def evaluate_high_based_outcomes(
    db: Session,
    trading_date: date,
    surge_threshold: float = 10.0,
    coverage_threshold: float | None = None,
) -> dict:
    ...
```

이 함수는 `COALESCE(high_change_rate, change_rate) >= surge_threshold`로 산출한 파생 판정을
기존 `was_surge_count`와 **병렬로** 반환한다(D2 동결 원칙 준수). 그러나 이는 거래일 단위 **집계
카운트**(총 행 수 대비 고가 기준 급등 행 수)일 뿐, `predicted_set`과 교차한 recall/precision을
산출하지 않는다 — 즉 "고가 기준으로 다시 채점하면 우리 예측이 얼마나 맞았는가"라는 질문에는
아직 답하지 못한다.

`backend/app/services/surge_evaluation_service.py:658`의 `evaluate_surge_predictions()`가
공식 일일 평가 함수다 — `SurgePredictionEvaluation` 테이블에 upsert되고,
`/api/surge-trading/evaluation`, `/evaluation/{date}`, `/prediction-history` 세 엔드포인트
(`backend/app/routers/surge_trading.py:204,307,405`)가 그 테이블을 조회해 응답한다. 이 함수
전체를 grep한 결과 `high_change_rate`/`high_based` 문자열이 **0건** 나타난다(직접 확인) — 즉
고가 기반 지표는 어디에도 공식 리포트로 노출되지 않는다.

### `evaluate_surge_predictions()`는 이미 동일한 패턴(병렬 파생 지표)을 두 번 적용해 왔다

이 함수의 5단계(:809-856)가 이미 정확히 이런 구조를 갖는다 — 기존 `actual_set`(시장 전체
`was_surge` 기준)과 별개로 `universe_set`과의 교집합으로 `scannable_recall`/`coverage`를
**추가로** 계산하고, 실패 시 격리된 try/except로 두 값을 NULL 처리하며 주 지표는 보존한다
(SPEC-AI-068). 본 SPEC은 동일한 구조를 "고가 기준 actual_set"에도 적용하는 것으로, 새로운
패턴이 아니라 기존 패턴의 재사용이다.

### 8단계(:955-979)는 동일한 "런타임 전용, 비영속" 필드 선례도 이미 갖고 있다

`scannable_denominator_expanded`(SPEC-AI-086)는 신규 DB 컬럼 없이 호출 결과 객체에만
존재하는 런타임 속성이다. 본 SPEC은 이와 달리 **영속 컬럼**을 선택한다(§Decisions D1) —
`/prediction-history`가 DB에서 직접 조회하는 과거 레코드에도 값이 남아야 "공식 리포트에
노출"이라는 요구를 만족하기 때문이다.

## Goals

1. `evaluate_surge_predictions()`가 고가 기준 recall/precision을 `predicted_set`과 실제
   교차하여 산출하도록 확장한다.
2. 기존 `precision`/`recall`/`f1_score`/`true_positive`/`false_positive`/`false_negative`
   산출식과 `was_surge` 판정 자체는 완전히 불변으로 유지한다.
3. 새 지표를 `SurgePredictionEvaluation`에 영속화해 `/prediction-history` 등 기존 응답
   경로가 향후 이를 노출할 수 있는 기반을 만든다.
4. 계산 실패가 주 평가 결과의 upsert/commit을 방해하지 않도록 격리한다(기존 Scannable Recall
   블록과 동일 패턴).

## Non-Goals

### Out of Scope — 범위 제한

- **`existing_codes` 스캔 유니버스 병합 필터 무효화 교정**: 이 세션에서 함께 요청되었으나
  `.moai/specs/SPEC-AI-094/`가 동일 버그(`build_scan_universe()`의 `entry_pool_map` 병합
  필터가 구조적으로 항상 빈 리스트를 반환하는 문제, 거의 동일한 코드 라인 인용)를 이미 상세
  분석해 플래그 게이팅(기본 비활성) 설계로 draft 상태에 있다. 이번 요청은 무조건 즉시 수정
  (플래그 없음)을 전제로 하여 두 설계가 상충한다 — 배포 즉시 `scannable_recall`/`coverage`/
  `surge_type` 라벨이 이동하는지(SPEC-AI-094는 기본 비활성으로 이동을 유예, 이번 요청은 즉시
  이동을 함의) 여부가 핵심 쟁점이다. 오케스트레이터/사용자가 (a) SPEC-AI-094를 그대로 실행,
  (b) SPEC-AI-094를 이번 요청 설계로 개정, (c) 두 설계를 병기해 사용자가 최종 결정 중 하나를
  택해야 하며, 본 SPEC은 그 결정 없이 진행하지 않는다.
- **`was_surge` 재정의**: SPEC-AI-093 D2 동결 결정을 승계한다. 본 SPEC이 추가하는 지표는
  병렬(parallel)이며 주 지표를 대체하지 않는다.
- **`/api/surge-trading/evaluation` · `/evaluation/{date}` · `/prediction-history` 라우터
  응답 필드 추가**: 세 엔드포인트 모두 ORM 인스턴스를 직접 직렬화하지 않고 명시적 dict
  키 목록을 반환한다(`surge_trading.py:223-236`, `:341-358`, `/prediction-history` 본문 —
  직접 확인). 신규 컬럼이 이 dict들에 자동으로 나타나지 않으므로, 라우터 응답 필드 추가는
  별도의 작고 독립적인 후속 작업이다(본 SPEC은 영속화까지만).
- **`evaluate_high_based_outcomes()`(SPEC-AI-093) 자체 수정**: 그 함수는 무수정으로 유지한다
  — 본 SPEC은 `evaluate_surge_predictions()`에 그와 유사하되 `predicted_set` 교차가 추가된
  새 계산을 인접 배치한다.
- **텔레그램/Slack 등 알림 채널로의 노출**: 본 SPEC 범위 밖. 로깅과 DB 영속화까지만 다룬다.
- **`surge_threshold`(10.0) 값 자체의 변경**: 기존 `was_surge`와 동일 기준을 유지해
  "동일 조건에서 라벨만 다르게 재채점"이라는 비교 가능성을 보존한다.

## Decisions

### D1 — 런타임 전용 속성이 아닌 영속 컬럼을 선택한다

`scannable_denominator_expanded`(SPEC-AI-086)처럼 비영속 런타임 속성으로 둘 수도 있으나,
`/prediction-history`가 과거 레코드를 DB에서 직접 조회하므로 비영속 속성은 그 경로에 절대
나타나지 않는다. "공식 평가 리포트의 일부로 노출"이라는 요구를 만족하려면 영속화가 필수다.
대가: 작은 마이그레이션(3개 nullable 컬럼) 1건이 필요하다 — SPEC-AI-068이 동일한 이유로
동일 크기의 마이그레이션(`scannable_recall`/`coverage`/`scannable_actual_count`)을 이미
선례로 남겼다.

### D2 — 3개 컬럼으로 최소화한다 (recall / precision / coverage)

FP_high는 `predicted_count - high_based_true_positive`로 유도 가능하므로 별도 컬럼이
필요 없다. `partial_collection` 불리언도 별도 컬럼 없이 `high_based_coverage <
0.90`(운영 임계값, `SURGE_HIGH_COVERAGE_THRESHOLD` env var로 노출된 기존 상수 재사용)로
소비 측에서 판정 가능하다 — 신규 컬럼을 최소화해 Tier S 범위(<300 LOC, <5 파일)를 지킨다.

### D3 — 계산 위치는 5단계(Scannable Recall) 직후, 6단계(upsert) 직전

기존 함수의 5단계(:809-856)가 이미 "주 actual_set과 별개로 파생 actual_set을 계산해 실패
시 격리하는" 동일한 구조를 갖는다. 새 계산을 그 직후에 인접 배치하면 6단계의 upsert
(갱신/생성 두 분기)에 3개 필드만 추가하면 되고, 별도의 트랜잭션 경계나 새로운 실패 격리
패턴을 발명할 필요가 없다.

## Requirements

### REQ-AI095-001: 고가 기준 recall/precision 산출

**When** `evaluate_surge_predictions()`가 4단계(주 TP/FP/FN 계산) 이후에 도달하면, the
system **shall** `COALESCE(high_change_rate, change_rate) >= surge_threshold`(기본
10.0, 기존 `was_surge`와 동일 기준)를 만족하는 종목 집합(`high_actual_set`)을
`SurgeActualOutcome`에서 별도로 조회하고, 이미 계산된 `predicted_set`과의 교집합으로
`high_based_true_positive`/`high_based_false_negative`를 산출한 뒤
`high_based_recall = TP_high / (TP_high + FN_high)`,
`high_based_precision = TP_high / predicted_count`(predicted_count > 0일 때;
FP_high = predicted_count − TP_high)를 계산해야 한다.

필수 조건:

- `predicted_set`은 기존 2단계에서 이미 확정된 값(near_limit_up_carry/same-day 배제 적용
  완료)을 그대로 재사용한다 — 별도 재조회 금지.
- `predicted_count == 0`이면 `high_based_precision`은 NULL로 남긴다(0으로 나누기 회피 —
  "측정 불가"와 "0%"를 구분해 소비자 오독을 방지한다).
- `TP_high + FN_high == 0`(해당 거래일에 고가 기준 급등 실제 종목이 0건)이면
  `high_based_recall`은 `ZeroDivisionError`를 발생시키지 말고 NULL로 남겨야 한다 —
  `predicted_count == 0` 시 `high_based_precision`을 NULL로 처리하는 것과 동일한 이유
  (0으로 나누기 회피, "측정 불가"와 "0%" 구분). 기존 `scannable_recall` 지표가 동일한
  분모-0 가드를 이미 구현하고 있다(`backend/app/services/surge_evaluation_service.py:832-834`
  — 참조 구현 형태).

### REQ-AI095-002: 기존 주 지표 완전 불변

**While** 본 SPEC이 적용되는 동안, the system **shall not** 기존 `precision`/`recall`/
`f1_score`/`true_positive`/`false_positive`/`false_negative` 컬럼의 산출식,
`SurgeActualOutcome.was_surge`의 판정 기준(`change_rate >= 10.0`), 또는
`scannable_recall`/`coverage`(SPEC-AI-068)의 산출식을 변경해서는 안 된다.

검증 방법: 동일 fixture에 대해 본 SPEC 적용 전후 AC-095-007에 명시된 필드 집합의 값이 완전히
동일해야 한다.

### REQ-AI095-003: `SurgePredictionEvaluation` 영속화

**When** `evaluate_surge_predictions()`가 6단계에서 `SurgePredictionEvaluation` 행을
upsert(기존 행 갱신 또는 신규 생성 — 두 분기 모두)하면, the system **shall**
`high_based_recall`(`float | None`), `high_based_precision`(`float | None`),
`high_based_coverage`(`float | None` — `evaluate_high_based_outcomes()`와 동일한 정의:
`high_change_rate IS NOT NULL`인 행 비율)를 같은 트랜잭션(같은 `db.commit()`)으로 함께
저장해야 한다.

필수 조건:

- 신규 alembic 리비전 1건(down_revision = 현재 head `069_surge_pred_eval_snapshot`)으로
  3개 nullable 컬럼을 추가한다. 기존 행은 모두 NULL로 남는다(백필 없음 — SPEC-AI-093 D3
  전진 적용 원칙 승계).
- 기존 갱신 분기(`existing.xxx = ...`)와 신규 생성 분기(`SurgePredictionEvaluation(...)`)
  양쪽 모두에 3개 필드를 추가해야 한다 — 한쪽만 추가하면 재실행(idempotent upsert) 시
  값이 소실된다.

### REQ-AI095-004: 계산 실패 격리 (fail-open)

**When** 고가 기준 지표 계산 중 예외가 발생하면, the system **shall** `high_based_recall`/
`high_based_precision`/`high_based_coverage` 세 값을 모두 `None`으로 처리하고 기존
5-6단계(주 평가 결과의 계산·upsert·commit)를 방해해서는 **shall not** 한다 — 기존
Scannable Recall 블록(:820-851, `try/except` + `db.rollback()`)과 동일한 격리 패턴을
재사용한다.

### REQ-AI095-005: 로그 노출

**When** `evaluate_surge_predictions()`의 고가 기준 지표 계산이 완료되면, the system
**shall** 기존 "평가 결과: TP=%d, FP=%d, FN=%d, precision=%.3f, legacy_recall=%.3f,
f1=%.3f" 로그 라인(:804-807)에 인접한 위치에 `high_based_recall`/`high_based_precision`/
`high_based_coverage` 값을 별도 로그 라인 1건으로 남겨야 한다(계산 불가/실패 시 값은
`None`으로 그대로 로깅 — 은폐 금지).

## Open Questions

정책 판단(영속 컬럼 선택 D1 / 3컬럼 최소화 D2 / 계산 위치 D3 / existing_codes 항목 제외)은
§Decisions와 §Out of Scope에서 이미 확정했다. `predicted_count == 0`일 때 `high_based_precision`을
NULL로 처리하는 정책 역시 REQ-AI095-001과 acceptance.md AC-095-008 양쪽에서 이미 확정했으므로
(0.0이 아닌 NULL — "측정 불가"와 "0%"를 구분) 아래 목록에서 제외한다. 아래는 구현 시 확정할
파라미터만 남긴 목록이다.

1. 신규 alembic 리비전 파일명 — `070_surge_pred_eval_high_based.py` 제안, 구현 시 프로젝트
   명명 관례(`0XX_설명적_이름.py`) 재확인 후 확정.
2. `existing_codes` 항목(§Out of Scope 첫 항목)의 최종 처리 방향 — 본 SPEC의 범위가 아니며,
   오케스트레이터/사용자가 SPEC-AI-094 관련 결정을 내린 뒤 별도 SPEC 또는 SPEC-AI-094 개정
   으로 다뤄야 한다.
