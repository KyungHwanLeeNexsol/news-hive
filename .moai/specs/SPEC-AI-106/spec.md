---
id: SPEC-AI-106
title: "지평 인식 임계값 섀도우 전환 게이트 가시성 확립 — 일일 평가 잡 통합"
version: "0.1.0"
status: completed
created: 2026-08-06
updated: 2026-08-06
author: Nexsol
priority: Medium
phase: "backend surge-detection v0.1.0"
module: "backend/app/services"
lifecycle: spec-anchored
tags: "surge-detection, scoring-architecture, horizon-aware-threshold, shadow-mode, observability, activation-gate, backend"
tier: S
related_specs: [SPEC-AI-100, SPEC-AI-101, SPEC-AI-104, SPEC-AI-105]
---

# SPEC-AI-106: 지평 인식 임계값 섀도우 전환 게이트 가시성 확립 — 일일 평가 잡 통합

## HISTORY

- 2026-08-06 v0.1.0 (draft): 위임 프롬프트("`horizon_aware_thresholds.enabled`를
  `true`로 전환해야 하는가, 어떤 근거로?")에 대한 응답으로 작성됐다. 코드 직접 확인으로
  범위를 크게 재조정했다. 위임 프롬프트는 "섀도우 비교가 영속화되는지 먼저 확인하고,
  영속화가 없으면 영속화부터 추가하라"는 이분법을 제시했으나, 실제로는 **제3의
  상태**임을 확인했다: `run_horizon_shadow_comparison()`의 영속화와 3요건 판정 함수
  `check_horizon_transition_readiness()`는 SPEC-AI-101(완료, 2026-08-05 배포)이 이미
  구현했다 — 영속화를 추가하는 작업은 중복이며 불필요하다. 그러나 `check_horizon_transition_readiness()`는
  자신의 테스트 파일에서만 호출되며 프로덕션의 어떤 스케줄러 잡·API·리포트에서도 호출되지
  않는다는 것을 확인했다 — 즉 함수는 존재하나 아무도 주기적으로 확인하지 않는 "죽은 관측
  경로"다. 또한 배포일(2026-08-05)과 오늘(2026-08-06) 사이의 경과 시간만으로도
  REQ-AI100-009가 요구하는 최소 10거래일 관측 요건에 구조적으로 크게 못 미침이 명백하다
  (정확한 축적 거래일수는 프로덕션 DB 쿼리로만 확인 가능하며, 이 세션은 그 쿼리를
  실행하지 않았다 — §Open Questions 1). 따라서 "지금 활성화 여부를 결정한다"는 원 질문에
  대한 정직한 답은 "아직 데이터가 없어 결정할 수 없다"이며, 데이터 없이 결정을 강행하는
  것은 관찰되지 않은 근거로 검증 주장을 하는 것과 동일한 오류다. 본 SPEC은 대신
  SPEC-AI-104/105가 확립한 "wire → 관측 → 활성화는 별도 결정" 패턴을 재사용해, 이미
  존재하는 판정 함수를 관측 가능하게 만드는 배선 작업(로그 통합)과, 실제 전환 시점에
  사람이 따를 검토 절차 문서화까지만 다룬다.

## 선행 SPEC

- **SPEC-AI-100** (완료): 지평 인식 임계값 선택 아키텍처(`compute_horizon_signature`,
  `select_effective_threshold`), 섀도우 비교 로깅(`run_horizon_shadow_comparison`),
  섀도우→프로덕션 전환 게이트 3요건(REQ-AI100-009: 관측 거래일 ≥10일, 3개 레짐 전량
  관측, qualified 집합 변화폭 ±30% 이내)의 소유 SPEC. 본 SPEC은 이 판정 로직 자체를
  재구현하지 않는다.
- **SPEC-AI-101** (완료, 2026-08-05 배포): `shadow_mode_enabled`를 `true`로 전환하고,
  섀도우 비교 결과 영속화 테이블 `SurgeHorizonShadowObservation`과 3요건 집계 함수
  `check_horizon_transition_readiness()`를 구현한 실행 SPEC. `enabled`는 `false`로
  유지했으며 "`enabled=true` 전환은 본 SPEC의 완료 조건이 아니다"(REQ-AI101-006)를
  명시적으로 확정했다. 본 SPEC은 이 판정 함수를 재사용만 하며 재구현하지 않는다 — 이
  함수를 프로덕션에서 관측 가능한 위치에 배선하는 작업만 추가한다.
- **SPEC-AI-104/105**: Pool D canary 전환 / bridge 후보 shadow 정밀도 측정 게이트.
  두 SPEC 모두 "관측 인프라 배선 → 관측 기간 확보 → 실제 활성화는 별도 SPEC/운영 판단"
  패턴을 확립했다. 본 SPEC은 이 패턴을 그대로 재사용한다 — 다만 SPEC-AI-101이 이미
  영속화 + 판정 함수까지 구축해 두었으므로, 본 SPEC이 새로 만드는 것은 "관측 가능하게
  배선"뿐이다.

### amendment 여부

본 SPEC은 어떤 선행 SPEC의 amendment도 아니다. `amendment_of:` 없이 `related_specs`로만
참조하는 신규 SPEC이다.

## Context / Problem

### 문제 1 — 전환 게이트 판정 함수가 존재하지만 프로덕션 어디에서도 호출되지 않는다

`check_horizon_transition_readiness(db)`(`surge_horizon_readiness_service.py`)는
`SurgeHorizonShadowObservation`을 집계해 (관측 고유 거래일수, 관측 레짐 집합, 관측 기간
중 qualified 집합 최대 변화폭, 3요건 충족 여부)를 반환하도록 SPEC-AI-101이 이미
완성했다. 그러나 이 함수를 호출하는 코드는 `backend/tests/test_spec_ai_101.py` 단 한
곳뿐이다 — 어떤 스케줄러 잡, API 엔드포인트, 리포트 스크립트도 이 함수를 호출하지
않는다. 즉 "3요건이 충족됐는지" 확인하려면 사람이 수동으로 파이썬 REPL이나 임시 스크립트를
작성해 DB를 조회해야 한다. 이 프로젝트의 반복된 실패 패턴 — 측정 인프라는 만들어졌으나
아무도 소비하지 않는 "죽은 관측 경로"(SPEC-AI-070의 `surge_detector_contribution`
리포트 전무, SPEC-AI-076 이전의 `pool_counts` post-truncation 카운트 부재 등) — 를
반복할 위험이 있다.

### 문제 2 — 배포 후 경과 시간이 최소 관측 요건에 구조적으로 미달한다

`shadow_mode_enabled`는 2026-08-05(SPEC-AI-101 sync 커밋 `e9d685d`)에 `true`로
전환됐다. 오늘은 2026-08-06이다. REQ-AI100-009가 요구하는 3요건 중 첫 번째("최소 관측
거래일 수 10일 이상")는 배포 후 최대 1~2 거래일밖에 경과하지 않은 시점에서는 산술적으로
충족될 수 없다 — 정확한 축적된 관측 거래일수 자체는 프로덕션 DB 쿼리로만 확인 가능하며
(§Open Questions 1), 이 세션은 프로덕션 DB에 접근하지 않았으므로 그 수치를 단정하지
않는다. 그러나 배포일과 오늘 날짜 사이의 산술적 간격만으로도 10거래일 요건에 크게
못 미친다는 결론은 명백하다. 이 시점에 `enabled=true` 전환 여부를 "결정"하는 것은 관찰된
증거 없이 검증 주장을 하는 것과 같은 범주의 오류다.

### 문제 3 — per-horizon 임계값 수치가 여전히 미확정 placeholder다

`surge_detection.yaml`의 `ensemble.horizon_aware_thresholds.thresholds` 블록은 모든
지평 시그니처(same_day_dominant/next_day_dominant/multi_day_dominant/mixed)에 대해
기존 `regime_thresholds`와 정확히 동일한 값(BULL 0.38 / SIDEWAYS 0.45 / BEAR 0.42)으로
초기화되어 있다 — SPEC-AI-100 Open Question 2가 명시했듯 "플래그가 켜져도 당장은 동작
변화가 없도록" 의도된 안전 초기값이며, 실제 지평별 최적 임계값은 섀도우 관측 데이터를
기반으로 확정해야 하는 미해결 항목이다. 이 값 튜닝 역시 관측 데이터가 축적되기 전에는
수행할 수 없다.

## Goals

1. SPEC-AI-101이 완성한 3요건 판정 함수(`check_horizon_transition_readiness`)를
   프로덕션에서 매일 자동으로 호출되도록 배선한다 — 신규 스케줄러 잡을 만들지 않고
   기존 일일 평가 잡에 격리된 진단 블록으로 추가한다.
2. 판정 결과가 journalctl에서 검색 가능한 구조화 로그로 남도록 한다 — 별도 알림
   채널(Telegram/API)은 도입하지 않는다.
3. 이 배선이 기존 일일 평가 잡의 핵심 결과(precision/recall/f1 커밋)와
   `enabled`/`shadow_mode_enabled` 값에 어떤 영향도 주지 않음을 보장한다.
4. 실제 전환 결정 시 사람이 따를 검토 절차(관측 완료 확인 방법, per-horizon 임계값
   튜닝 여부 판단, 승인 절차)를 plan.md §C에 문서화한다 — 이는 REQ-AI100-009가
   "확인 절차는 구현 시 plan.md에 명문화되어야 한다"고 요구한 항목을 완결한다.
5. `horizon_aware_thresholds.enabled`를 `true`로 전환하는 실제 결정은 본 SPEC의
   범위에 포함하지 않는다 — 관측 데이터가 축적된 이후 별도 세션/SPEC에서 이루어진다.

## Non-Goals

### Out of Scope — `horizon_aware_thresholds.enabled` 전환 실행

- **실제 마스터 스위치를 `true`로 전환하는 작업**: 배포 후 경과 시간이 최소 관측
  요건(10거래일)에 구조적으로 못 미치므로, 이 시점에 전환을 실행하는 것은 근거 없는
  결정이다. 이 결정은 관측 데이터가 축적된 이후 별도 SPEC 또는 운영 판단으로 이월한다.

### Out of Scope — per-horizon 임계값 수치 튜닝

- **`ensemble.horizon_aware_thresholds.thresholds`의 실제 지평별 최적값 확정**:
  SPEC-AI-100 Open Question 2가 명시한 대로 섀도우 관측 데이터 축적 후에만 수행
  가능하다. 본 SPEC은 이 튜닝을 실행하지 않으며, 향후 검토 절차의 체크리스트
  항목으로만 명문화한다.

### Out of Scope — SPEC-AI-100/101 판정·영속화 로직 재구현

- **`compute_horizon_signature`, `select_effective_threshold`,
  `run_horizon_shadow_comparison`, `check_horizon_transition_readiness`의 내부 계산
  로직 수정 또는 복제**: 본 SPEC은 이 함수들 중 `check_horizon_transition_readiness`를
  호출만 하며, 판정 로직 자체는 SPEC-AI-100/101 소유로 무수정 유지한다.

### Out of Scope — 신규 알림 채널

- **Telegram 리포트, 신규 API 엔드포인트, 대시보드 추가**: 구조화 로그 1줄로
  충분하다고 판단한다(SPEC-AI-101 §Decisions D3의 "로그 스크래핑 대신 영속화 테이블,
  단 신규 비교 전용 테이블은 아직 불필요" 선례와 동일한 최소주의 원칙 — 이번에는
  테이블도 이미 있으므로 로그 노출만 추가한다).

### Out of Scope — 신규 DB 테이블/마이그레이션

- **`SurgeHorizonShadowObservation` 스키마 변경 또는 신규 테이블 도입**: 기존
  테이블과 기존 판정 함수를 그대로 재사용한다. 본 SPEC은 신규 마이그레이션을
  포함하지 않는다.

## Decisions

### D1 — 로그 통합 지점은 기존 일일 평가 잡(`_run_surge_verify_predictions`, 18:30
KST)의 격리된 진단 블록으로 결정한다, 신규 스케줄러 잡은 기각한다

`_run_surge_verify_predictions`는 이미 SPEC-AI-086의 `diagnose_non_scannable_causes`
호출을 핵심 평가 결과 커밋 이후 격리된 `try/except` 블록으로 배치하는 선례를 갖고
있다. 3요건 판정은 하루 1회 확인으로 충분하고(관측은 매 스코어링 사이클마다 이미
누적되고 있음, 판정 자체는 저비용 단일 집계 쿼리), 이 기존 잡의 사이클과 자연스럽게
일치한다.

기각한 대안 — 신규 전용 스케줄러 잡 신설. 하루 1회 저비용 집계 쿼리를 위해 별도 잡을
운영하는 것은 불필요한 인프라 추가이며, 기존 평가 잡의 컨텍스트(당일 레짐 정보 등)와
분리되어 오히려 관측 가치가 낮다.

### D2 — 실제 전환은 본 SPEC의 산출물이 아니다, 관측 기간 미달이 구조적으로 명백하다

§Context 문제 2의 근거로, 배포일(2026-08-05)과 오늘(2026-08-06) 사이의 경과가
최소 10거래일 요건에 크게 못 미친다. 이 시점에 전환을 실행하는 SPEC을 작성하는 것은
근거 없는 결정을 코드화하는 것과 같다.

기각한 대안 — 지금 즉시 전환을 실행하고 향후 문제가 발견되면 롤백. 2026-07-28
`theme_news_carry` 자기강화 피드백 루프 사고(오탐률 77% 도달 후에야 발견) 이후 이
프로젝트는 스코어링 아키텍처 변경의 근거 없는 조기 전환을 명시적으로 경계해왔다
(SPEC-AI-100 D6, SPEC-AI-101 D5) — 동일 원칙을 적용해 기각한다.

### D3 — 신규 알림 채널 도입은 기각한다, 구조화 로그로 충분하다

`journalctl -u newshive` 검색으로 이미 이 프로젝트 전역에서 관측 로그를 확인하는
관례가 확립되어 있다(예: `1200s` ASCII 검색 선례, SPEC-AI-082). 판정 결과 4개 필드를
1줄 INFO 로그로 남기면 사람이 주기적으로(또는 관측 창 종료 시점에) 확인하기에 충분하다.

기각한 대안 — Telegram 일일 리포트 확장. 매매와 무관한 순수 관측 정보를 위해 기존
Telegram 리포트 포맷을 확장하는 것은 이 SPEC의 최소 범위를 넘어서며, 로그로 이미
목적을 달성할 수 있어 기각한다.

### D4 — per-horizon 임계값 튜닝은 이 SPEC의 범위 밖이다, 검토 절차의 체크리스트
항목으로만 명문화한다

§Context 문제 3의 근거로, 임계값 튜닝은 관측 데이터가 축적된 이후에만 의미 있는 판단이
가능하다. 본 SPEC은 이 판단을 지금 내리지 않고, plan.md §C 검토 절차에 "전환 시 반드시
확인할 항목"으로만 기록한다.

## Requirements

### REQ-AI106-001 (P1, Event)

**When** 평일 18:30 KST 일일 평가 잡(`_run_surge_verify_predictions`)이 실행되고
핵심 평가 결과(precision/recall/f1)가 커밋되면, the system **shall**
`check_horizon_transition_readiness(db)`를 호출해 그 반환값(관측된 고유 거래일수,
관측된 시장 레짐 집합, 관측 기간 중 qualified 집합 최대 변화폭, 3요건 충족 여부)을
구조화된 INFO 로그 1줄로 기록해야 한다.

필수 조건:

- 로그 메시지는 4개 필드(`observed_trading_days`, `regimes_observed`,
  `max_change_pct`, `all_criteria_met`) 값을 모두 포함해야 한다.
- 이 호출은 하루 1회(18:30 KST 잡 사이클당 1회)만 발생해야 하며, 매 스코어링
  사이클(`run_horizon_shadow_comparison`)마다 반복 호출해서는 **shall not** 안 된다.

### REQ-AI106-002 (P0, Unwanted)

**While** 본 SPEC이 적용되는 동안, the system **shall not**
`ensemble.horizon_aware_thresholds.enabled` 또는 `.shadow_mode_enabled` 값을
변경해서는 안 된다. 두 값 모두 SPEC-AI-101이 남긴 상태(`enabled: false`,
`shadow_mode_enabled: true`)를 그대로 유지해야 한다.

### REQ-AI106-003 (P0, Unwanted)

**While** 본 SPEC이 적용되는 동안, the system **shall not**
`check_horizon_transition_readiness()`, `run_horizon_shadow_comparison()`,
`compute_horizon_signature()`, `select_effective_threshold()`의 내부 판정 로직을
변경하거나 복제해서는 안 된다. REQ-AI106-001의 구현은 기존 함수를 호출만 해야 한다.

### REQ-AI106-004 (P0, State)

**Where** REQ-AI106-001의 로그 통합 블록에서 `check_horizon_transition_readiness()`
호출이 예외를 발생시키면, the system **shall** 그 예외를 격리된 `try/except`로 잡아
경고 로그만 남기고 무시해야 하며, 일일 평가 잡의 핵심 결과(precision/recall/f1 커밋)
저장에 **shall not** 영향을 주어서는 안 된다.

### REQ-AI106-005 (P1, Ubiquitous)

the system's plan-phase 산출물 **shall** plan.md §C에 실제 `enabled=true` 전환 시
사람이 따를 검토 절차를 문서화해야 한다. 이 절차는 최소한 (1) 관측 완료 확인 방법(3요건
판정 로그 또는 직접 쿼리 조회), (2) per-horizon 임계값 수치 튜닝 필요 여부 판단 기준,
(3) 전환 승인 및 롤백 경로를 포함해야 한다.

### REQ-AI106-006 (P1, Unwanted)

**While** 본 SPEC이 적용되는 동안, the system **shall not** 신규 DB 테이블, 컬럼,
또는 마이그레이션을 도입해서는 안 된다. 기존 `SurgeHorizonShadowObservation` 테이블과
기존 판정 함수만 재사용한다.

## Open Questions

1. **프로덕션 DB의 실제 관측 거래일수/레짐 커버리지** — 이 세션은 프로덕션 DB에
   접근하지 않았으므로 `check_horizon_transition_readiness()`의 실제 반환값(현재
   시점 `observed_trading_days`, `regimes_observed`)을 확인하지 못했다. REQ-AI106-001
   배포 후 첫 로그 출력에서 실제 값을 확인할 수 있다 — 배포 자체가 이 질문에 대한
   관측 채널이다.
2. **일일 로그 통합 시점(18:30 KST 잡) vs 별도 저빈도 확인 잡의 장기적 적합성** —
   현재는 매일 확인이 저비용이라 기존 잡에 통합했으나, 향후 관측 항목이 늘어나면
   저빈도(예: 주 1회) 요약 잡으로 분리할지는 이 SPEC의 결정 대상이 아니다.
3. **per-horizon 임계값 최적값 확정 시점의 튜닝 방법론** — 규칙 기반 수동 조정인지
   SPEC-AI-065 선례(오프라인 로지스틱 회귀 1회성 시드)와 유사한 통계적 접근인지는
   실제 관측 데이터 분포를 본 후 결정한다(§Decisions D4).
