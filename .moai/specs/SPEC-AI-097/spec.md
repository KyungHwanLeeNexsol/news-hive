---
id: SPEC-AI-097
title: "급등 후보 스코어링 가격이력 조회 배치·캐싱 성능개선"
version: "0.1.0"
status: draft
created: 2026-08-03
updated: 2026-08-03
author: Nexsol
priority: Medium
phase: "backend surge-detection v0.1.0"
module: "backend/app/services"
lifecycle: spec-anchored
tags: "surge-detection, price-history, caching, batching, performance, backend"
tier: M
related_specs: [SPEC-AI-016, SPEC-AI-038, SPEC-AI-062, SPEC-AI-066, SPEC-AI-072, SPEC-AI-076]
---

# SPEC-AI-097: 급등 후보 스코어링 가격이력 조회 배치·캐싱 성능개선

## HISTORY

- 2026-08-03 v0.1.0 (draft): GPT 급등예측 구조진단 보고서 핵심주장 #2("종목별 순차 HTTP 호출이
  top-50 사전필터의 근본원인")의 후속 조치로 작성. `project_gpt_surge_diagnosis_2026_07_30.md`
  (auto-memory)가 "HTTP 순차호출 → 배치 전환"을 미작성 SPEC 후보로 남긴 항목을 이행한다. 동일
  문제의 "정책" 측면(top-50 절단 자체를 완화할지 여부)은 별도 형제 SPEC이 다루며, 본 SPEC은
  "메커니즘"(HTTP 비용 자체를 낮추는 배치/캐싱)만 다룬다.

## 선행 SPEC

- **SPEC-AI-038**: `_MAX_PRICE_FETCH_CANDIDATES=50` 사전필터를 도입한 SPEC(성능 패치 3단계,
  `backend/app/services/surge_detector.py:2114-2138`). 본 SPEC은 이 사전필터가 존재하는 근본
  원인(HTTP 비용)을 다루되, 절단 값 자체나 절단 정책은 변경하지 않는다.
- **SPEC-AI-016**: `fetch_current_prices_batch()`(매수 주문 실행 경로, 현재가 배치 조회)의 소유
  SPEC. 본 SPEC은 이 함수와 그 호출부를 수정하지 않는다(§Non-Goals).
- **SPEC-AI-062/063/066**: `detect_volume_breakout()` 계열 — `fetch_stock_price_history_sync`
  순차 호출부 중 하나(`surge_detector.py:4335`).
- **SPEC-AI-072**: `detect_near_limit_up_carries()` — 순차 호출부 중 하나, T-1 종가 계산에
  가격이력을 사용한다.
- **SPEC-AI-076**: `build_scan_universe()` 및 Pool A/B/C/D 배분 — 본 SPEC이 개선하는 가격조회
  성능의 다운스트림(스캔 유니버스 크기)이지만, 유니버스 배분 로직 자체는 무관하다.
- **(형제 SPEC, ID 미확정)**: top-50 사전필터(`_MAX_PRICE_FETCH_CANDIDATES`) 절단값·정책 자체의
  완화 여부 — 본 SPEC과 동일 세션에서 별도로 작성 중. 본 SPEC은 그 정책 변경에 의존하지 않고
  독립적으로 완결된다(§Non-Goals). 형제 SPEC의 ID가 확정되면 `related_specs`에 후속 반영한다.

## Context / Problem

### 검증된 사실 — 로컬 OHLCV 저장소는 존재하지 않는다

`backend/app/models/` 전체를 검색한 결과, 가격 이력(OHLCV)을 저장하는 로컬 DB 테이블은 존재하지
않는다. 가격이력은 매번 Naver Finance의 `sise_day.naver` HTML 페이지를 파싱해서 얻는다
(`backend/app/services/naver_finance.py`).

### 검증된 사실 — 가격이력 조회는 8개 이상 지점에서 종목당 개별 순차 HTTP 호출로 이뤄진다

- `fetch_stock_price_history()`(naver_finance.py:689, `async def`) — 내부적으로 `asyncio.gather`
  로 **한 종목의 여러 페이지**를 병렬 요청하지만, 여러 종목을 병렬로 조회하는 용도가 아니다.
- `fetch_stock_price_history_sync()`(naver_finance.py:808, `def`) — 페이지를 **순차** for-loop로
  요청한다(`httpx.Client` 동기, 페이지 간 병렬 없음). `surge_detector.py`의 모든 호출부가 이
  동기 버전을 사용한다.

`surge_detector.py` 안의 모든 함수는 `def`(동기)이다 — `gather_surge_candidates`(:1835)를
포함해 파일 전체에 `async def`가 0건임을 grep으로 확인했다. 즉 `asyncio.gather` 기반 동시성을
도입하려면 이 파일의 함수들을 async로 전환해야 하며, 이는 스코프를 크게 벗어난다.

확인된 순차 호출 지점(종목 리스트를 순회하며 매 종목마다 `fetch_stock_price_history_sync`를
1회씩 호출):

| 위치(대략) | 함수 | 용도 |
|------------|------|------|
| `:2143-2156` | `gather_surge_candidates` 내부(top-50 사전필터 직후) | `price_5d_trend` 채움 |
| `:2652` | `detect_volume_anomaly_dormant_stocks` | 휴면 재활성 60거래일 이력(`config.history_pages`) |
| `:2776` 부근 | `detect_near_limit_up_carries` | T-1 종가 계산 |
| `:3792` 부근 | (그룹 캐스케이드/주간 갭업 계열) | 이력 조회 |
| `:4033` | `detect_bollinger_squeeze_signals` | 시총 상위 N종목 60일 볼린저 밴드(`config.price_pages`) |
| `:4335` | `detect_volume_breakout` | 거래량 리더 유니버스 30거래일 이력(`pages=3`) |
| `:4724` 부근 | (촉매 유니버스 확장 계열) | 이력 조회 |

이와 대조적으로 `fetch_current_prices_batch()`(naver_finance.py:1525, `async def`, 매수 주문
실행 전용, SPEC-AI-016)는 이미 배치당 10종목 동시 조회 + 배치 간 0.5초 대기 패턴을 구현하고
있다 — 그러나 이 함수는 **현재가**(1회성 스냅샷) 조회 전용이며, **가격이력**(OHLCV 시계열)
조회에는 전혀 재사용되지 않는다. "종목 배치 동시조회" 인프라는 이미 이 프로젝트에 존재하지만,
스코어링 경로의 가격이력 조회에는 배선되어 있지 않다는 것이 핵심 발견이다.

### 검증된 사실 — 캐시는 존재하나 `stock_code`로만 키가 잡히고 `pages` 값을 구분하지 않는다

`_price_cache`(naver_finance.py:686, `_PriceHistoryCache`)는 인메모리 dict
(`{stock_code: list[PriceRecord]}`) + Redis write-through(TTL=3600초, `PRICE_CACHE_TTL`)로
구성되며, TTL은 장중/장마감 인지형(`_cache_ttl()`)이다. 그러나 캐시 히트 판정
(`fetch_stock_price_history_sync:816-819`, `fetch_stock_price_history:696-698`)은
**`stock_code`만**을 키로 사용하고, 그 데이터가 몇 페이지 분량으로 채워졌는지(`pages` 인자)는
기록하지 않는다.

호출부마다 요청하는 `pages` 값이 서로 다르다(`pages=1`, `pages=3`, `config.history_pages`,
`config.price_pages` 등 — 위 표). 결과적으로 한 스캔 사이클 내에서 어떤 호출부가 먼저
`pages=1`로 어떤 종목을 캐싱하면, 그 직후 다른 호출부가 같은 종목을 `pages=3`(더 많은 이력
필요)으로 요청해도 캐시 히트로 처리되어 **부족한 이력이 조용히 재사용**된다. 이는
`len(records) < config.min_history_days` 같은 하류 검증을 오탐(과소 이력으로 실제로는 조건을
만족하는 종목을 탈락)시킬 수 있는 잠재 리스크다 — 이번 조사에서 새로 발견한 사실이며, 기존
SPEC 어디에서도 다뤄지지 않았다.

## Goals

1. Naver Finance(또는 이 코드베이스에 이미 존재하는 다른 조회 엔드포인트)가 여러 종목을 한
   요청으로 묶어 조회하는 진짜 벌크 API를 제공하는지 조사하고 결론을 근거와 함께 남긴다.
2. `surge_detector.py`의 스코어링 경로 가격이력 조회(종목당 개별 순차 호출)를, 매수 주문 실행
   경로(`fetch_current_prices_batch`, SPEC-AI-016)에 이미 배선된 것과 유사한 동시성 배치 조회로
   전환한다 — 단, 실행 경로 자체는 건드리지 않고 별도 함수로 구현한다(§Non-Goals).
3. 캐시 히트 판정에 `pages` 값을 반영해, 짧은 이력으로 캐시된 결과가 더 긴 이력을 요구하는
   후속 호출에 잘못 재사용되는 문제를 제거한다.
4. 변경 전/후로 스캔 사이클당 총 HTTP 호출 수와 소요 시간을 측정 가능하게 만들어, top-50
   사전필터 완화 여부를 판단하는 형제 SPEC이 근거로 쓸 수 있게 한다.

## Non-Goals

### Out of Scope — 절단 정책 및 스캔 유니버스

- **`_MAX_PRICE_FETCH_CANDIDATES=50` 값 변경 또는 제거**: 이 사전필터가 존재하는 이유(가격조회
  비용)를 본 SPEC이 낮추지만, 절단 자체를 완화할지는 별도 형제 SPEC의 정책 판단이다. 본 SPEC은
  그 판단에 필요한 측정치(Goal 4)만 제공한다.
- **`max_scan_universe`(150) 상한, Pool D 활성화, quota 배분 로직**: `build_scan_universe()`
  (SPEC-AI-065/076/086) 소유. 무관.

### Out of Scope — 인접 파이프라인 영역

- **뉴스-종목 매칭 고도화**: 별도 형제 SPEC("C") 소관.
- **피처 스냅샷 저장(`ml_feature` 계열)**: 별도 형제 SPEC("D") 소관.
- **horizon(예측 지평) 분리**: 별도 형제 SPEC("E") 소관.
- **ML 모델 도입**: GPT 진단 항목 #3 — 완전히 무관한 별개 축.

### Out of Scope — 매수 주문 실행 경로

- **`fetch_current_prices_batch()`(SPEC-AI-016) 또는 그 호출부(`surge_trading_service.py`)
  수정**: 공유 코드 추출이 명백히 필요한 경우가 아닌 한 건드리지 않는다. 건드릴 경우에도 그
  함수의 기존 동작은 characterization 테스트로 바이트 동등을 증명해야 한다.
- **`fetch_current_price_with_change()` 등 현재가(단발성 스냅샷) 조회 함수**: 가격이력(시계열)과
  무관.

### Out of Scope — 탐지 로직 자체

- **8개 탐지기의 스코어링 알고리즘·가중치·임계값 변경**: 본 SPEC은 가격이력을 "어떻게 더 빨리
  가져오는가"만 다루며, 가져온 데이터를 "어떻게 쓰는가"는 건드리지 않는다.
- **`compute_ensemble_score` 등 스코어 계산 로직**: 무관.

## Decisions

### D1 — 배치 동시조회는 새 함수로 별도 구현한다 (ThreadPoolExecutor, asyncio 미사용)

`surge_detector.py`의 모든 함수가 동기이므로, 8개 탐지기를 async로 전환하는 것은 스코프를 크게
벗어난다. 대신 `naver_finance.py`에 `fetch_current_prices_batch()`와 같은 배치/딜레이 패턴을
갖되 **동기 시그니처**를 유지하는 신규 함수를 추가한다. 내부 구현은
`concurrent.futures.ThreadPoolExecutor`로 배치당 N개 동시 실행한다 — 동기 함수 내부에서
`asyncio.run()`을 호출하는 방식은 호출 스택 어딘가가 이미 실행 중인 이벤트 루프 안(예: 비동기
컨텍스트에서 스레드 없이 직접 호출되는 경우)일 때
`RuntimeError: asyncio.run() cannot be called from a running event loop`를 유발할 수 있어
채택하지 않는다.

### D2 — 캐시 히트 판정에 `pages`를 반영한다 (기존 `_price_cache` 확장, 신규 캐시 구조체 아님)

`_PriceHistoryCache`에 `pages_fetched: dict[str, int]`(또는 동등한 필드)를 추가해, 캐시 히트는
`cached_pages >= requested_pages`일 때만 유효로 판정한다. 요청 페이지가 캐시된 페이지보다
많으면 재조회 후 캐시를 갱신한다 — 더 짧은 페이지 요청은 항상 캐시된 더 긴 결과의 선행
부분집합으로 충족된다(레코드가 date-descending 순서이므로 슬라이싱으로 자연히 해결된다).

### D3 — 로컬 영속 OHLCV 테이블 신설 여부는 plan.md에서 결정을 보류한다

가장 되돌리기 어려운 결정(신규 테이블은 마이그레이션 배포 후 롤백 비용이 큼)이므로 독단적으로
확정하지 않는다. 기존 인메모리+Redis 캐시가 "하루 여러 번 읽기" 요구를 실제로 충족하는지는
운영 스캔 사이클의 프로세스 생명주기(사이클마다 새 프로세스인지, 장기 실행 프로세스인지)에
따라 달라지므로, 이는 plan.md M1 사전조사로 확인한 뒤 Implementation Kickoff Approval 단계에서
사용자와 함께 확정한다(plan.md §Open Questions 참고).

### D4 — 측정은 기존 로그 라인 확장으로 (신규 대시보드/메트릭 인프라 없음)

Goal 4의 측정치는 기존 `[급등탐지] price_5d_trend 조회 전 상위 N개로...` 류 로그 패턴을
확장해 기록한다 — 신규 관측 인프라(Prometheus 등) 도입은 이 SPEC 범위 밖이다(YAGNI, Enforce
Simplicity 사다리).

## Requirements

### REQ-AI097-001: 벌크 조회 가능성 조사 결과 문서화

**When** M1 사전조사가 완료되면, the system(의 plan.md 및 구현 커밋 메시지)은 Naver Finance
또는 이 코드베이스에 이미 존재하는 다른 소스가 여러 종목을 한 HTTP 요청으로 묶어 조회하는 진짜
벌크 엔드포인트를 제공하는지 여부를 실측 근거(요청/응답 예시 또는 코드 인용)와 함께 기록해야
한다.

필수 조건:

- 조사 결과가 "벌크 엔드포인트 없음"이면, 그 사실이 D1의 동시성 배치 접근을 채택하는 근거로
  명시적으로 연결되어야 한다.
- 조사는 `fetch_current_prices_batch()`(기존 동시성-배치, 진짜 벌크 아님)와 벌크 엔드포인트를
  혼동하지 않고 구분해서 기록해야 한다.

### REQ-AI097-002: 가격이력 동시조회 배치 함수 신설

**When** 스코어링 경로가 N개(N≥2) 서로 다른 종목의 가격이력을 필요로 하면, the system **shall**
`naver_finance.py`에 신규 동기 함수(예: `fetch_stock_price_history_batch_sync`)를 통해 그
조회를 배치당 M개 동시 실행(기본값은 `fetch_current_prices_batch`와 동일한 스타일을 참고,
구현 시 확정) + 배치 간 지연으로 처리해야 하며, 기존 `fetch_current_prices_batch()`
(SPEC-AI-016) 자체는 **shall not** 호출·수정한다.

필수 조건:

- 신규 함수의 반환 타입은 `dict[str, list[PriceRecord]]`(호출부가 stock_code로 결과를 조회).
- 개별 종목 조회 실패는 예외를 전파하지 않고 빈 리스트로 격리한다(기존
  `fetch_stock_price_history_sync`의 실패 격리 관례를 승계).
- `concurrent.futures.ThreadPoolExecutor`로 여러 스레드가 동시에 `_price_cache`(공유 dict)에
  쓰기/축출(`evict_expired`)을 수행할 때 경합 조건이 발생하지 않아야 한다(예: `threading.Lock`
  으로 캐시 접근을 직렬화하거나, 각 스레드의 결과를 배치 함수 내부에서 수집한 뒤 메인 스레드에서
  일괄 캐시 갱신).
- `surge_detector.py`의 순차 for-loop 호출부(§Context 표) 중 최소 1개 이상을 이 신규 함수로
  전환해 실사용 경로에서 검증해야 한다 — 전환 대상은 plan.md에서 확정한다.

### REQ-AI097-003: 캐시 히트 판정의 pages 인지형 전환

**When** `fetch_stock_price_history_sync()`(또는 신규 배치 함수)가 캐시 히트를 검사하면, the
system **shall** 캐시에 기록된 `pages` 값이 요청된 `pages` 값 이상일 때만 캐시 히트로 판정해야
하며, **shall not** 더 적은 페이지로 채워진 캐시 항목을 더 많은 페이지가 필요한 요청에 그대로
반환한다.

필수 조건:

- 캐시 미스(페이지 부족) 시 재조회 후 캐시를 더 큰 페이지 수로 갱신한다.
- 기존 캐시 TTL(장중/장마감 인지형, `_cache_ttl()`) 동작은 변경하지 않는다 — 페이지 인지형
  판정은 TTL 판정에 **추가**되는 조건이지 대체가 아니다.
- Redis write-through 캐시(`stock:{code}:prices`)에 대해서도 동일한 pages 메타데이터 반영
  또는 "인메모리 미스 시에만 사용"(기존 `:701-710` 동작) 유지 중 하나를 택일하되, 어느 쪽이든
  REQ-AI097-004의 무회귀 조건을 만족해야 한다.

### REQ-AI097-004: 매수 주문 실행 경로 무영향

**While** 본 SPEC이 적용되는 동안, the system **shall not** `fetch_current_prices_batch()`,
`fetch_current_price_with_change()`, 또는 `surge_trading_service.py`의 매수 주문 실행 흐름을
변경한다 — 이 함수들을 호출하는 어떤 하류 로직도 동작이 달라져서는 안 된다.

필수 조건:

- `git diff --name-only`에 `surge_trading_service.py`가 포함되면, 그 변경이 순수 리팩터
  추출이며 기존 동작을 characterization 테스트로 바이트 동등 증명했는지 확인해야 한다.

### REQ-AI097-005: 성능 측정치 로깅

**When** 신규 배치 조회 경로가 실행되면, the system **shall** 해당 스캔 사이클에서 발생한
가격이력 HTTP 호출 수(캐시 히트 제외)와 그 조회 단계의 소요 시간(초)을 기존 로그 체계에 남겨야
한다.

필수 조건:

- 측정치는 변경 전 베이스라인과 비교 가능한 형태로 남긴다(같은 fixture/replay로 전/후 비교).
- 신규 DB 컬럼·마이그레이션은 이 요구사항만으로는 발생시키지 않는다(로그 라인 확장으로 충분).

## Open Questions

정책 판단(D1 동시성 방식 / D2 캐시 확장 방식 / D4 측정 방식)은 §Decisions에서 이미 확정했다.
유일하게 확정되지 않은 항목(§D3 — 로컬 영속 OHLCV 테이블 신설 여부)은 plan.md §Open Questions
에 `[NEEDS CLARIFICATION]` 마커로 기록하며, Implementation Kickoff Approval 이전에 사용자와
확정해야 한다.
