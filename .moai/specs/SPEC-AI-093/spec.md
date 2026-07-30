---
id: SPEC-AI-093
title: "급등 결과 라벨 재정의: 장중 고가 기준 등락률(high_change_rate) 실측 수집"
version: "0.1.0"
status: completed
created: 2026-07-30
updated: 2026-07-30
author: Nexsol
priority: High
phase: "backend surge-detection v0.1.0"
module: "backend/app/services"
lifecycle: spec-anchored
tags: "surge-detection, outcome-label, high-change-rate, evaluation-metric, backend"
tier: M
related_specs: [SPEC-AI-041, SPEC-AI-050, SPEC-AI-071, SPEC-AI-072, SPEC-AI-090, SPEC-AI-092]
---

# SPEC-AI-093: 급등 결과 라벨 재정의

## HISTORY

- 2026-07-30 v0.1.0 (draft): 라이브 코드 검증 결과를 반영해 초안 작성. `high_change_rate` 컬럼이
  스키마·마이그레이션에는 존재하나 모든 insert 경로에서 무조건 `None`으로 하드코딩되어 있다는 사실과,
  그로 인해 급등 라벨이 종가 기준 단일 축으로만 측정되고 있다는 문제를 범위로 정의한다.

## 선행 SPEC

- **SPEC-AI-041**: `surge_actual_outcome` 테이블과 `high_change_rate` 컬럼을 최초 정의한 SPEC.
  본 SPEC은 그 SPEC이 명세했으나 구현되지 않은 항목을 뒤늦게 이행한다.
- **SPEC-AI-072**: 일봉 조회 시 **인덱스가 아닌 `date` 매칭**으로 T-1 종가를 구해야 한다는 교훈의
  출처. 본 SPEC의 T-1 종가 계산은 그 패턴을 그대로 재사용한다.
- **SPEC-AI-090**: 기존 `was_surge` 정의를 **변경하지 않고** 완화된 대안 기준을 병렬로 추가한 선례
  (REQ-AI090-004). 본 SPEC의 라벨 정책 결정은 이 선례를 따른다.
- **SPEC-AI-071**: 정답 모집단을 `stocks` 교집합으로 정제. 과거 데이터 백필 없이 전진 적용만 한 선례.
- **SPEC-AI-092**: 평가 기록 안정화. 본 SPEC은 그 평가 파이프라인이 소비하는 **라벨 자체의 정확도**를 다룬다.

## Context / Problem

### 문제 1 — 급등 결과 라벨이 서로 다른 두 질문을 하나로 뭉개고 있다

`backend/app/services/surge_actual_outcome_service.py:173-174` (`collect_daily_surge_outcomes` 내부):

```python
"change_rate": change_rate,
"was_surge": change_rate >= 10.0,
"high_change_rate": None,  # 고가 기준 등락률은 현재 API에서 미지원
```

세 가지 사실이 확인된다.

1. `change_rate`는 **종가 대 전일종가** 등락률이다. `fetch_current_price_with_change`
   (`backend/app/services/naver_finance.py:1287-1327`)가 Naver의 `fluctuationsRatio` 필드를 그대로
   반환하며, 장중 고가와는 무관하다.
2. `high_change_rate`는 실재하는 nullable 컬럼이다 —
   `backend/app/models/surge_actual_outcome.py:36`, 마이그레이션
   `backend/alembic/versions/058_surge_actual_outcome.py:30`. 그러나 코드베이스의 **어떤 writer도
   이 컬럼을 채우지 않는다.** 모든 insert 경로에서 무조건 `None`이 기록된다.
3. 원래 SPEC-AI-041 (`.moai/specs/SPEC-AI-041/spec.md:141`)은 `high_change_rate`를
   `(고가 − 전일종가) / 전일종가 × 100 (고가 미수집 시 change_rate로 대체)`로 명세했다. 즉 장중
   고가 기준이며 **명시적 fallback까지 규정**되어 있었다. 실제 구현은 그 fallback조차 이행하지 않고
   `None`을 하드코딩했다.

주석 "현재 API에서 미지원"은 **사실과 다르다.** `PriceRecord` 데이터클래스
(`naver_finance.py:655-663`)는 `high` 필드를 보유하며, `fetch_stock_price_history`
(`naver_finance.py:689-776`)와 `fetch_stock_price_history_sync` (`naver_finance.py:808-837`)는
Naver `sise_day.naver` 일봉 HTML에서 `open/high/low/close/volume`을 모두 파싱한다
(`naver_finance.py:724-737`). 고가는 이미 수집 가능한 데이터다.

### 문제 2 — 장중 급등 후 되밀린 종목이 체계적으로 비급등으로 오분류된다

종가 단일 기준의 직접적 귀결이다.

- 장중 +15%까지 급등했다가 종가 +7%로 되밀린 종목 → `was_surge=False`. 실제로는 예측 시스템이
  맞히려던 매매 기회가 분명히 발생했다.
- 반대로 장 후반에야 움직인 종목은 포착되지만, 두 경우가 **동일한 단일 boolean으로 뭉개져**
  구분되지 않는다.

이 라벨로 산출된 운영 지표(2026-07-01 이후 18거래일: 실제 급등 1,086건, 예측 205건, 적중 8건,
precision 3.90%, 시장 전체 recall 0.74%)는 **시스템이 예측하려는 실제 매매 기회를 대표하지 않을 수
있는 라벨** 위에서 측정된 값이다. 라벨의 정확도를 먼저 확보하지 않으면 그 위에 쌓는 모든 튜닝
판단이 잘못된 기준을 향하게 된다.

### 확인된 라벨 소비자 (재정의 시 영향 범위)

`was_surge`는 평가 전용 라벨이 아니다. 프로덕션 소비 지점은 다음과 같다.

| 소비 지점 | 성격 |
|-----------|------|
| `surge_evaluation_service.py:779` | recall/precision 분모 (정답 집합) |
| `surge_evaluation_service.py:556` | non_scannable 분류 |
| `surge_evaluation_service.py:941` | 탐지기별 기여도 집계 |
| `surge_universe_gap_service.py:121` | 유니버스 간극 측정 |
| `surge_auto_improver.py:499`, `:1156` | 자동개선 루프 입력 |
| **`surge_detector.py:3922`** | **탐지기 입력** — SPEC-AI-050 월요일 테마캐리가 최근 10거래일 `was_surge=True` 종목을 후보 소스로 사용 |
| `scheduler.py:952`, `:998` | 미탐 종목 텔레그램 알림 |

마지막에서 두 번째 항목이 핵심이다. `was_surge`를 재정의하면 **평가 지표만 바뀌는 것이 아니라
탐지기 하나의 후보 소싱 범위가 부수적으로 넓어진다.** 이는 예측 건수 급증으로 이어질 수 있으며,
SPEC-AI-092 plan.md §D가 명시한 롤백 트리거("일별 예측 수가 기존 14일 평균 대비 3배 이상 증가")에
정면으로 해당한다.

### 수집 잡 실행 시각

`_run_surge_collect_outcomes` (`backend/app/services/scheduler.py:787-788`)는 평일 16:10 KST에
실행된다. 장 마감(15:30 KST) 40분 후이므로 당일 일봉이 게시되어 있을 것으로 기대되나, 본 SPEC은
이를 단정하지 않고 fallback 경로와 그 발생률 계측을 필수 요구사항으로 둔다.

## Goals

1. `high_change_rate`를 실측값으로 채운다 — 일봉 고가와 T-1 종가로 계산한다.
2. T-1 종가는 인덱스가 아닌 `date` 매칭으로 구해 SPEC-AI-072 버그의 재발을 차단한다.
3. fallback 경로 진입을 구분 가능한 이벤트로 로깅해 운영자가 발생률을 관측할 수 있게 한다.
4. `was_surge`의 기존 정의를 동결하고, 고가 기준 지표는 **병렬 지표**로 노출한다.
5. 전진 적용만 한다 — 과거 `surge_actual_outcome` 행을 백필하지 않는다.
6. 부분 수집된 날의 고가 기반 지표가 오해를 부르지 않도록 coverage guard를 둔다.

## Non-Goals

### Out of Scope — 범위 제한

- **`was_surge` 재정의 및 과거 데이터 백필**: 본 SPEC은 `was_surge`를 종가 기준으로 **동결**한다.
  재정의 판단의 근거는 §Decision D2에 기록하며, 재정의가 필요하다는 결론이 나면 별도 SPEC으로 다룬다.
- **same_day vs next_day 예측 지평 분리**: 별도의 더 큰 문제이며 후속 SPEC 대상이다.
- **`build_scan_universe()` 재정렬, 150종목 cap, 50후보 사전 필터**: 후속 SPEC 대상이다.
- **ML 모델 도입 / `ml_feature_engineering.py` 변경**: 후속 SPEC 대상이다.
- **뉴스-종목 매칭 / 테마 탐지 변경**: 후속 SPEC 대상이다.
- **adaptive threshold와 예측 gate 배선**: 의도된 설계 분리로 이미 문서화되어 있으며 조치 불필요.
- **탐지기 로직 변경**: `surge_detector.py:3922`의 테마캐리 입력은 `was_surge` 동결에 의해
  자동으로 무영향이다. 탐지기 자체는 건드리지 않는다.

## Decisions

### D1 — 고가 데이터 획득 방식: 추가 조회 (기존 `change_rate` 경로 불변)

`fetch_stock_price_history(code, pages=1)`을 종목별로 **추가 호출**하고, 기존
`fetch_current_price_with_change` 호출은 그대로 둔다.

기각한 대안 — 일봉 한 번의 조회로 `change_rate`와 `high`를 모두 유도하기 (호출 수는 줄지만,
`change_rate`의 산출 근거가 Naver `fluctuationsRatio`에서 자체 계산 종가-대-종가로 **바뀐다**).
18거래일 누적 기준선이 이미 존재하는 지표의 의미를 조용히 이동시키는 것은 허용되지 않는다.

비용 영향: 종목당 최대 +1 네트워크 호출(대상 약 200종목, 동시성 10). 다만
`fetch_stock_price_history`는 `_price_cache`를 공유하며 당일 탐지기 실행이 이미 다수 종목의 일봉을
캐싱해 두므로 실제 증가분은 그보다 작을 것으로 예상된다. 잡은 하루 1회 장 마감 후 배치이므로
부하 시간대와 겹치지 않는다. **예상은 근거가 아니므로**, 실제 캐시 적중률과 호출 증가분은
REQ-AI093-003의 계측으로 관측한다.

### D2 — `was_surge`는 재정의하지 않는다 (동결)

세 가지 근거로 동결을 선택한다.

1. **부수효과 범위**: `was_surge`는 순수 평가 라벨이 아니라 `surge_detector.py:3922`의 탐지기
   입력이다. 재정의는 탐지기 후보 소싱 범위를 함께 넓히며, 이는 본 SPEC이 의도한 "라벨 정확도
   개선"과 무관한 예측 건수 변동을 유발한다.
2. **소급 비교 가능성**: 18거래일 누적 기준선(실제 급등 1,086건 / precision 3.90% /
   recall 0.74%)이 종가 기준 라벨 위에 축적되어 있다. 백필 없이 재정의하면 시계열 중간에 단절이
   생기고, 백필은 §D3의 이유로 수행하지 않는다.
3. **프로젝트 선례**: SPEC-AI-090이 REQ-AI090-004에서 "기존 `was_surge`/scannable 집계 정의 자체는
   변경하지 않는다"는 원칙으로 병렬 기준 추가 패턴을 이미 확립했다. 동일 패턴을 따른다.

대신 고가 기반 성공 여부는 **저장 컬럼이 아닌 파생 지표**로 노출한다
(`high_change_rate >= 10.0`). 새 컬럼과 마이그레이션이 불필요하며, `was_surge`와 병렬로 비교
가능하다.

### D3 — 전진 적용 (백필 없음)

배포 이전 `surge_actual_outcome` 행은 `high_change_rate=NULL`로 남는다.

트레이드오프를 명시한다. 백필하면 전 구간 비교가 가능해지지만, 과거 각 거래일의 일봉을 종목별로
재조회해야 하고(수백 종목 × 수십 거래일), 그 시점의 정답 모집단이 SPEC-AI-071/SPEC-AI-076 등으로
여러 차례 바뀌었기 때문에 재구성한 라벨이 당시 평가와 정합하지 않는다. SPEC-AI-071이 동일한 이유로
백필을 하지 않은 선례를 따른다. 대가로 고가 기반 지표는 배포일 이후부터만 유효하며, 이 사실을
§REQ-AI093-005의 coverage guard로 표면화한다.

### D4 — NULL의 의미와 fallback 위치

저장 컬럼은 정직하게 유지한다. 측정 실패 시 `high_change_rate`에 `change_rate`를 써 넣지 않고
**NULL로 남긴다** — 그래야 "실측된 고가"와 "대체값"이 구분된다.

SPEC-AI-041이 명세한 fallback(`고가 미수집 시 change_rate로 대체`)은 **읽기 시점**의 파생 지표
계층에서 `COALESCE(high_change_rate, change_rate)`로 이행한다. 저장은 정직하게, 소비는 fallback
적용 — 두 요구를 모두 만족하며 새 컬럼이 필요 없다.

## Requirements

### REQ-AI093-001: 장중 고가 기준 등락률 실측 수집

When `collect_daily_surge_outcomes()`가 종목 결과를 upsert하면, 시스템은 해당 종목의 당일 일봉
고가와 전일 종가로 계산한 `high_change_rate`를 저장해야 한다.

계산식:

```
high_change_rate = (T일 일봉 high − T-1일 일봉 close) / T-1일 일봉 close × 100
```

필수 조건:

- 데이터 출처는 `fetch_stock_price_history`가 반환하는 `PriceRecord.high` / `PriceRecord.close`다.
- 기존 `change_rate` 산출 경로(`fetch_current_price_with_change`)는 변경하지 않는다 (D1).
- `high_change_rate`는 `change_rate`보다 작을 수 없다(고가 ≥ 종가). 이 불변식이 깨지면 계산 오류로
  간주하고 NULL 처리 후 경고 로깅한다.

### REQ-AI093-002: T-1 종가는 date 매칭으로 구한다

When T-1 종가를 조회하면, 시스템은 일봉 리스트의 **인덱스 위치가 아니라 `PriceRecord.date` 값
매칭**으로 해당 거래일 레코드를 특정해야 한다.

필수 조건:

- `trading_date`와 직전 영업일을 각각 Naver 일봉 날짜 형식(`YYYY.MM.DD`)으로 변환해 매칭한다.
- 매칭되는 레코드가 없으면 계산을 포기하고 REQ-AI093-003의 fallback 경로로 진입한다 — 근접한 다른
  레코드로 추정하지 않는다.

근거: SPEC-AI-072에서 `near_limit_up_carry`가 인덱스 기반 조회로 T-1 등락률을 오라벨해 "이미 당일
급등한 종목을 뒤늦게 추격"하는 정반대 동작을 한 사례가 있다. 동일 실패를 반복하지 않는다.

### REQ-AI093-003: fallback 경로 구분 로깅 및 발생률 계측

When 고가 기반 계산이 불가능하면, 시스템은 `high_change_rate`를 NULL로 저장하고 그 사유를 구분
가능한 로그 이벤트로 남겨야 한다.

fallback 진입 조건 (각각 구분 가능해야 한다):

| 사유 코드 | 조건 |
|-----------|------|
| `no_candle_t` | T일 일봉 레코드 미발견 (미게시 또는 조회 실패) |
| `no_candle_t1` | T-1일 일봉 레코드 미발견 |
| `invalid_high` | `high <= 0` |
| `invalid_prev_close` | T-1 종가 `<= 0` |
| `invariant_violation` | 계산 결과가 `change_rate`보다 작음 (REQ-AI093-001 불변식 위반) |

필수 조건:

- 배치 종료 시 사유별 건수와 전체 대비 비율을 1건의 요약 로그로 집계한다.
- 개별 종목 실패는 배치 전체를 중단시키지 않는다 (기존 fail-open 정책 유지).
- 로그 문구는 `code_comments: ko` 설정에 따라 한국어로 작성하되, 사유 코드는 영문 식별자로 둔다.

### REQ-AI093-004: `was_surge` 정의 동결 및 소비자 무회귀

While 본 SPEC이 적용되는 동안, 시스템은 `was_surge`의 산출식(`change_rate >= 10.0`)과 그 값을
소비하는 7개 지점의 동작을 변경하지 않아야 한다.

필수 조건:

- `surge_evaluation_service.py`, `surge_universe_gap_service.py`, `surge_auto_improver.py`,
  `surge_detector.py`, `scheduler.py`의 `was_surge` 소비 코드는 무수정이다.
- 동일 fixture에서 본 SPEC 적용 전후의 `was_surge` 값과 기존 평가 지표가 완전히 동일해야 한다.

### REQ-AI093-005: 고가 기반 병렬 지표와 coverage guard

Where 고가 기반 성공 여부가 필요하면, 시스템은 저장 컬럼이 아닌 파생 판정
(`COALESCE(high_change_rate, change_rate) >= 10.0`)으로 이를 산출하고, 산출과 함께 해당 거래일의
`high_change_rate` 실측 커버리지를 반환해야 한다.

필수 조건:

- 커버리지 정의: `high_change_rate IS NOT NULL`인 행 수 ÷ 해당 거래일 전체 행 수.
- 커버리지가 임계값 미만인 거래일에 대해서는 고가 기반 지표에 "부분 수집" 표시를 부착한다 —
  부분 수집된 날의 낮은 고가 기반 recall이 실제 성능 저하로 오독되지 않게 한다.
- 임계값은 설정으로 노출하며 기본값을 명시한다.
- 이 파생 지표는 기존 `was_surge` 기반 지표를 **대체하지 않고 병렬로** 제공한다 (D2).

### REQ-AI093-006: 비용 증가 관측

When 배치가 완료되면, 시스템은 고가 조회로 인한 추가 외부 호출 수와 캐시 적중 수를 로깅해야 한다.

필수 조건:

- D1이 "캐시 덕분에 증가분이 작을 것"이라고 **예상**한 부분을 실측으로 대체한다.
- 배치 소요 시간을 기존 `_record_job_duration("surge_collect_outcomes", ...)` 경로로 계속 계측한다.

## Open Questions

정책 판단(고가 데이터 획득 방식 / `was_surge` 동결 / 백필 없음 / NULL 의미와 fallback 위치)은
§Decisions D1~D4에서 이미 확정했다. 아래는 그 결정을 **구현할 때 확정해야 하는 구체적 파라미터
값과 노출 범위**만 남긴 목록이다.

1. REQ-AI093-005의 coverage 임계값 기본값 — 0.90을 제안하나 확정 필요. (임계값을 설정으로 노출한다는
   것 자체는 REQ-AI093-005에서 이미 결정됨)
2. 고가 기반 파생 지표의 노출 표면 — 평가 로그까지인가, `/prediction-history` API 응답까지인가?
   API까지 노출한다면 하위 호환을 위해 신규 필드 추가 방식이어야 한다.
3. TASK-002의 `fetch_stock_price_history` `pages` 값 — `pages=1`이 T와 T-1을 모두 포함하는지는
   페이지당 행 수에 의존하므로 실측으로 확정해야 한다. 연휴 직후 T-1이 며칠 전인 경우를 포함해
   보수적으로 잡는다.
