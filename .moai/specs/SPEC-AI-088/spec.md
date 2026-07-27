---
id: SPEC-AI-088
title: "same_day/near_limit_up_carry 시그널 사전 이동폭(pre_signal_change_pct) 계측"
version: "0.1.1"
status: completed
created: 2026-07-27
updated: 2026-07-27
author: Nexsol
priority: High
phase: "backend observability v0.1.0"
module: "backend/app/services"
lifecycle: spec-anchored
tags: "surge-detection, observability, circular-logic, same-day-horizon, near-limit-up-carry, measurement-only, backend"
issue_number: null
tier: S
---

# SPEC-AI-088: same_day/near_limit_up_carry 시그널 사전 이동폭(pre_signal_change_pct) 계측 (Pre-Signal Movement Measurement)

## HISTORY

| 버전 | 날짜 | 변경 내용 |
|------|------|-----------|
| 0.1.0 | 2026-07-27 | 최초 작성 — same_day/near_limit_up_carry 시그널의 순환논리 계측 필드 추가(측정 전용, Option A) |
| 0.1.1 | 2026-07-27 | plan-auditor iteration 1 지적사항 반영(defect-fix pass) — (D1) REQ-001~005의 구현 세부사항(함수명/파일경로/줄번호)을 "> 구현 참고:" 블록으로 분리하고 정본 문장을 행위 중립적으로 재작성, (D2) REQ-002의 "동일 동작" 주장을 완화하고 `fetch_current_price`/`fetch_current_price_with_change` 폴백 엔드포인트 델타(`/integration` 폐기 vs `/price`)를 사실 확인 섹션에 명시 |

## 선행 SPEC (전제 조건 / Assumptions)

- **SPEC-AI-080**: 동일-당일 고확신 공시 촉매 즉시 급등 시그널 발화(`_create_immediate_surge_signal`, `disclosure_impact_scorer.py:535`) 및 `horizon` 키(`same_day`/`next_day`, `_classify_disclosure_horizon`) 도입. 본 SPEC이 계측을 추가하는 1차 대상.
- **SPEC-AI-083**: 장중 고빈도 재스캔(09:10/09:35/10:00/10:30/10:55 KST, `scheduler.py:2508`) + `_gather_surge_candidates()`(`fund_manager.py:1270`) 내 `_intraday_horizon`(`fund_manager.py:1403-1405`) 계산 도입. same_day 귀속 시그널의 주 발생 경로(2차 대상).
- **SPEC-AI-072/075**: `detect_near_limit_up_carries()`(`surge_detector.py:2691`)가 `price_at_signal`을 **T-1 종가**(`t1_close`, `:2877`)로 설정하도록 확정. 본 SPEC은 이 불변식을 재확인만 하며 코드를 변경하지 않는다(3차 대상).
- **SPEC-AI-075**: `_is_near_limit_up_carry_signal()`/`_is_same_day_event_horizon_signal()`(`surge_evaluation_service.py:482-524`)가 이미 surge_metadata 내용(surge_basis 리스트 1차, 플랫 키 OR 폴백) 기반으로 두 시그널군을 표준 T-1→T predicted_set에서 배제하고 있음. 본 SPEC은 이 판별 함수가 이미 식별하는 두 시그널군에 계측 필드를 추가할 뿐, 판별 로직 자체는 변경하지 않는다.

**[HARD] 사실 확인**:
- `fetch_current_price_with_change_sync()`/`fetch_current_price_with_change()`(`naver_finance.py:899, 1287`)는 Naver 응답의 `fluctuationsRatio`를 그대로 반환하며, 이는 "전일 종가 대비 등락률"이다(`surge_actual_outcome_service.py`의 `change_rate >= 10.0` 당일 급등 판정과 동일 의미 필드). 즉 이 값은 **정확히 "T-1 종가 → 조회 시점 가격" 변화율**이며, `pre_signal_change_pct`가 필요로 하는 값과 수학적으로 동일하다.
- `_gather_surge_candidates()`(`fund_manager.py:1270`)와 `_create_immediate_surge_signal()`(`disclosure_impact_scorer.py:535`)는 **이미** `price_at_signal`을 위해 위 두 함수 중 하나를 호출하고 있으나, 반환 dict의 `change_rate` 키는 현재 버려지고 `current_price`만 사용된다(`fund_manager.py:1486-1489`, `disclosure_impact_scorer.py:558`는 `fetch_current_price`만 사용해 change_rate 자체가 없음). 따라서 REQ-001/002는 **신규 네트워크 호출 없이** 이미 도착한 응답에서 필드 하나를 추가로 추출하는 것만으로 충족된다.
- **[plan-auditor iteration 1 D2 지적 반영]** REQ-002가 교체하는 `fetch_current_price()`(`naver_finance.py:1252`, 구)의 모바일 API 폴백은 `/api/stock/{code}/integration` 엔드포인트를 호출한다(`:1268`) — 이 엔드포인트는 `fetch_current_price_with_change_sync()`의 docstring(`naver_finance.py:906`)에 "stockInfo: {} 빈 객체를 반환하여 폐기"로 명시된 **문서화된 폐기 엔드포인트**다. 반면 교체 대상 `fetch_current_price_with_change()`(`:1287`, 신)의 모바일 API 폴백은 이미 수정된 `/api/stock/{code}/price` 엔드포인트를 호출한다(`:1307`). 두 함수 모두 1차 조회(`fetch_naver_stock_list`, 시장당 `page_size=50`)는 시가총액 상위 50위 이내 종목만 커버하므로, 그 밖의 종목(다수)에서는 이 모바일 API 폴백이 사실상 주경로로 작동한다 — 즉 REQ-002의 함수 교체는 해당 종목군에서 `current_price` 조회 성공률 자체를 바꾸는 실질적 동작 델타를 수반하며, 이는 REQ-002 정본 문장이 명시하는 계측 정확도 개선의 의도된 부수 효과다(plan.md R-2, acceptance.md AC-088-003 참고).
- `detect_near_limit_up_carries()`(`surge_detector.py:2827-2880`)는 `price_at_signal=t1_close`(`:2877`)로 설정한다 — 즉 이 경로의 "시그널 시점 가격"은 정의상 T-1 종가 그 자체이므로, `pre_signal_change_pct`는 항상 `0.0`이며 별도 계산이나 fetch가 필요 없다.
- `detect_theme_news_carry()`(`surge_detector.py:3195-3353`, SPEC-AI-084, `horizon: "same_day"` 부여)는 전파 대상 멤버에게 **`price_at_signal`을 전혀 설정하지 않는다**(FundSignal 생성자 `:3323-3334`에 `price_at_signal=` 인자 없음). 이 경로는 신규 fetch 없이는 `pre_signal_change_pct`를 계산할 수 없다 — 본 SPEC의 명시적 제외 대상(§Out of Scope 참고). 또한 이 탐지기는 `ThemeNewsCarryConfig.enabled=False`가 기본값(SPEC-AI-084, 아직 미활성화)이므로 이 갭의 실제 영향은 현재 0건이다.

Related: 이번 세션 실측 데이터 — 2026-07-27 same_day 시그널 3건(현대무벡스/319400, 셀바스AI/108860, 티엑스알로보틱스/484810) 중 현대무벡스는 시그널 발화 시점에 이미 +19.93% 상승 후였고 발화 이후에는 -4.34%(이미 고점을 지난 뒤 뒤늦게 태깅된 순환논리 사례). `feedback_realtime_surge_verification.md`(2026-07-22 추가분)의 "same_day 시그널은 price_at_signal vs T-1종가 대조로 순환논리 배제 필수" 교훈을 시스템 자체의 계측 필드로 운영화한다.

## Overview

급등예측 시스템의 same_day 지평 시그널(SPEC-AI-080/083)과 near_limit_up_carry 시그널(SPEC-AI-072)은 신호 발생 시점에 이미 얼마나 움직인 종목인지를 기록하지 않는다. 그 결과 "이미 20% 상승한 뒤 뒤늦게 태깅된 종목"과 "지금 막 움직이기 시작한 종목"이 동일하게 라벨링되어, 개별 시그널 검토(이번 세션처럼 수작업으로 price_at_signal vs T-1종가를 대조)와 집계 평가지표(recall/precision) 양쪽에서 순환논리를 구조적으로 구분할 수 없다.

본 SPEC은 **측정 전용(Option A, 사용자 명시 승인)**으로 이 갭을 메운다: 시그널 억제/필터링/신뢰도 조정/탐지기 임계값 변경은 전혀 하지 않으며, 이미 확보된 데이터(`fetch_current_price_with_change*`의 기존 응답, `detect_near_limit_up_carries`의 기존 `t1_close`)에서 신규 fetch 비용 없이 파생 가능한 `pre_signal_change_pct` 필드 하나만 `surge_metadata`에 추가하고, 이를 기존 리뷰 API 2곳에 노출한다.

## 설계 원칙 (Design Principles)

- **측정만, 억제 없음(Option A)**: 사용자가 AskUserQuestion으로 명시 선택. 시그널 발화 여부, 신뢰도 스코어링, 탐지기 임계값은 이 SPEC에서 무변경. 순환논리를 관측했을 때 무엇을 할지(억제/가중치 조정)는 후속 SPEC의 범위이며, 이 필드가 축적하는 실측 분포가 그 후속 SPEC의 입력이 된다.
- **신규 fetch 비용 0**: REQ-001/002는 이미 발생 중인 네트워크 호출의 반환값에서 버려지던 필드를 추가로 읽을 뿐이다. REQ-003은 이미 메모리에 있는 `t1_close` 변수를 재사용한다. 이 원칙 때문에 `detect_theme_news_carry`(신규 fetch가 필요) 경로는 이번 SPEC에서 의도적으로 제외한다(§Out of Scope).
- **부가 전용(additive-only)**: 신규 DB 컬럼/마이그레이션 없음. `surge_metadata`(기존 Text/JSON 필드)에 키 하나만 추가. 필드 부재 시 소비자는 `None`/`null`로 처리(SPEC-AI-075/080의 fail-safe JSON 파싱 관례와 동일).
- **기존 판별 함수 무변경**: `_is_same_day_event_horizon_signal()`/`_is_near_limit_up_carry_signal()`(evaluation 배제 로직)은 이 SPEC에서 손대지 않는다 — 새 필드는 그 판별 결과에 부가되는 형제 데이터일 뿐, 판별 자체를 대체하지 않는다.

## EARS Requirements

### REQ-AI088-001 (Where/When, P0) — 장중 재스캔 same_day 경로 사전 이동폭 계측

**Where** 장중 재스캔이 산출하는 시그널의 지평 분류가 "same_day"인 경우, **when** 해당 경로가 급등후보 시그널을 신규 생성하거나 기존 행을 갱신하는 경우(단, 별도 즉시발화 마커로 이미 스킵 처리되는 행은 제외), the system **shall** 이미 시그널 시점 가격 산출을 위해 호출 중인 함수의 동일 응답에서 등락률 값을 추가로 추출해 `surge_metadata["pre_signal_change_pct"]`로 저장하며, 이를 위해 추가 네트워크 호출을 발생시키지 아니한다.
> 구현 참고: 대상 `_gather_surge_candidates()`(`fund_manager.py:1270`), 지평 분류 `_intraday_horizon`(`:1403-1405`). 신규 생성(`:1549-1566`) 및 기존 행 갱신(`:1504-1548`, `_existing_is_immediate=False`인 경우에 한함) 양쪽에 적용. 이미 `price_at_signal` 산출을 위해 호출 중인 `fetch_current_price_with_change_sync()`(`:1486-1489`)의 동일 응답 dict에서 `change_rate`를 추가 추출한다.

### REQ-AI088-002 (Where, P0) — 즉시발화 same_day 경로 사전 이동폭 계측

**Where** 즉시발화 경로가 부여하는 지평 분류가 "same_day"인 경우, the system **shall** 시그널 시점 현재가 조회에 사용하는 함수를 등락률까지 함께 반환하는 동등 함수로 교체하고, 반환된 현재가는 기존과 동일한 코드 경로로 `price_at_signal`에 사용하며 등락률은 신규로 `surge_metadata["pre_signal_change_pct"]`에 저장한다. 이 교체는 호출 횟수를 변경하지 아니한다(1콜 → 1콜, 응답 필드만 확장). **다만** 교체 대상 두 함수의 모바일 API 폴백 엔드포인트가 서로 다르므로(§선행 SPEC 사실 확인 및 plan.md R-2 참고), 1차 조회(시가총액 상위 50위)에 잡히지 않는 종목에서는 폴백 경로의 `current_price` 조회 성공률 자체가 달라질 수 있다 — 이는 호출 횟수·판정 로직과 무관한, 계측 정확도 측면의 의도된 부수 개선이다.
> 구현 참고: 대상 `_create_immediate_surge_signal()`(`disclosure_impact_scorer.py:535`), 지평 `horizon`(`_classify_disclosure_horizon` 반환값, `:466`). 기존 `fetch_current_price(disclosure.stock_code)`(`:558`) 호출을 `fetch_current_price_with_change(disclosure.stock_code)`로 교체한다.

### REQ-AI088-003 (When, P0) — near_limit_up_carry 경로 불변식 계측

**When** 근접상한가 이월 탐지기가 시그널 시점 가격을 T-1 종가로 설정하는 방식으로 `near_limit_up_carry` 시그널을 생성하는 경우, the system **shall** `surge_metadata["pre_signal_change_pct"]`를 `0.0`으로 설정한다 — 시그널 시점 가격이 정의상 T-1 종가 그 자체이므로 이 값은 항상 정확히 0이며, 추가 데이터 조회나 계산을 요구하지 아니한다.
> 구현 참고: 대상 `detect_near_limit_up_carries()`(`surge_detector.py:2691`), `near_limit_up_carry` FundSignal 생성부(`:2869-2878`, `price_at_signal=t1_close`).

### REQ-AI088-004 (Ubiquitous + When, P0) — 부가 전용 계약(하위 호환) [HARD]

The system **shall** `surge_metadata["pre_signal_change_pct"]`를 선택적(optional) 필드로 취급한다. **When** 이 SPEC 이전에 생성된 시그널, 또는 REQ-AI088-001~003이 다루지 않는 탐지기 경로가 생성한 시그널을 소비자가 읽는 경우, the system **shall** 해당 필드가 부재하거나 파싱 불가능해도 예외를 발생시키지 아니하며 기존 동작(필드 부재 시 `None`/무시)을 그대로 유지한다.
> 구현 참고: REQ-AI088-001~003이 다루지 않는 경로의 예 — `detect_theme_news_carry()`(SPEC-AI-084, `surge_detector.py:3195-3353`), 표준 T-1→T 앙상블 경로.

### REQ-AI088-005 (When, P1) — 리뷰 API 노출

**When** 평가 상세 조회 API 또는 예측 이력 조회 API가 `surge_candidate`/`preday_disclosure`/`disclosure_impact` 시그널의 상세 항목을 구성하는 경우, the system **shall** 공유 헬퍼로 `surge_metadata`에서 `pre_signal_change_pct`를 추출해 응답 item dict에 포함시키며, 필드가 부재하거나 파싱 불가능한 경우 `null`을 반환한다.
> 구현 참고: 대상 `GET /api/surge-trading/evaluation/{date_str}`(`surge_trading.py:280`, 내부적으로 `_get_signal_details_for_date()` `:242` 사용), `GET /api/surge-trading/prediction-history`(`:374`, 인라인 item dict 2곳 `:455-467`, `:499-511`).

## Implementation Scope

| 파일 | 변경 내용 | REQ |
|------|-----------|-----|
| `backend/app/services/fund_manager.py` | `_gather_surge_candidates()` 내 `_signal_current_price` 산출부(`:1483-1491`)에서 `change_rate`도 함께 추출, `_intraday_horizon=="same_day"`일 때 `metadata["pre_signal_change_pct"]`에 반영(`:1414-1419` 부근) | REQ-001 |
| `backend/app/services/disclosure_impact_scorer.py` | `_create_immediate_surge_signal()`의 `fetch_current_price` → `fetch_current_price_with_change` 교체(`:557-560`), `horizon=="same_day"`일 때 `metadata["pre_signal_change_pct"]`에 반영(`:573-582` 부근) | REQ-002 |
| `backend/app/services/surge_detector.py` | `detect_near_limit_up_carries()`의 `metadata` dict(`:2860-2865`)에 `"pre_signal_change_pct": 0.0` 추가 | REQ-003 |
| `backend/app/routers/surge_trading.py` | `pre_signal_change_pct` 추출 공유 헬퍼 추가 + `_get_signal_details_for_date()`(`:242-277`) 및 `/prediction-history` 인라인 item dict 2곳(`:455-467`, `:499-511`)에 배선 | REQ-005 |
| `backend/tests/test_spec_ai_088.py` | 신규 — 특성화 + 신규 동작 테스트 | 전체 |

**신규 DB 마이그레이션 없음.** `surge_metadata`(기존 Text/JSON 컬럼)에 키 하나 추가는 스키마 변경이 아니다.

## Acceptance Criteria

Acceptance Criteria(AC-088-001~009)와 Given/When/Then 테스트 시나리오는 별도 파일 `acceptance.md`에 정본으로 기술한다 (Tier S 관례상 spec.md 인라인도 허용되나, house style 정합 및 plan-auditor 검증 편의를 위해 3-file 구조를 유지한다).

## Out of Scope

### Out of Scope — 탐지기 판정 로직 변경

- 어떤 탐지기의 신뢰도(confidence) 스코어링, 앙상블 가중치, 임계값(`min_score_for_signal` 등)도 변경하지 아니한다.
- `_is_same_day_event_horizon_signal()`/`_is_near_limit_up_carry_signal()`(evaluation predicted_set 배제 로직)을 변경하지 아니한다 — `pre_signal_change_pct`는 이 판별 결과에 부가되는 형제 데이터일 뿐이다.
- `pre_signal_change_pct` 값을 근거로 시그널을 억제·필터링·재점수화하지 아니한다(Option A, 측정 전용). 이 값을 활용한 억제/가중치 조정은 후속 SPEC의 범위다.

### Out of Scope — 미커버 탐지기 경로

- `detect_theme_news_carry()`(SPEC-AI-084, `surge_detector.py:3195-3353`)가 전파하는 `horizon: "same_day"` 시그널은 이 SPEC에서 `pre_signal_change_pct`를 계산하지 아니한다 — 이 경로는 전파 대상 멤버에 대해 `price_at_signal` 자체를 설정하지 않으므로, 계측을 위해서는 신규 가격 조회 fetch가 필요하며 이는 "신규 fetch 비용 0" 설계 원칙에 위배된다. 이 탐지기는 현재 `enabled=False`가 기본값이라 실제 영향은 0건이다. 후속 SPEC 후보로 남긴다.
- 표준 T-1→T 앙상블 경로(`_gather_surge_candidates()`가 `_intraday_horizon != "same_day"`일 때 생성하는 시그널, 즉 08:00/09:05/15:20 KST 정기 스캔)는 이미 순환논리 문제가 구조적으로 존재하지 않는 지평(T-1 시점에 T당일 급등을 예측)이므로 `pre_signal_change_pct` 계측 대상이 아니다.

### Out of Scope — 스키마/집계 확장

- 신규 DB 마이그레이션·컬럼을 추가하지 아니한다.
- `GET /api/surge-trading/coverage`(`compute_coverage_dashboard`, `CoverageDashboardResponse` Pydantic 스키마)에 집계/롤업 지표(예: 오늘 same_day 시그널 평균 `pre_signal_change_pct`)를 추가하지 아니한다 — 이는 별도 캐시된 대시보드 스키마 변경을 요구하며, 이번 SPEC의 개별-시그널 계측 범위를 넘어선다. 후속 SPEC 후보로 남긴다.

### Out of Scope — 백필

- 이 SPEC 이전에 생성된 기존 `surge_metadata` 레코드에 `pre_signal_change_pct`를 소급 백필하지 아니한다(전진 적용만).
