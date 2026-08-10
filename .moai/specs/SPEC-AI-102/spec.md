---
id: SPEC-AI-102
title: "급등예측 후보군 손실 구조 개선: 유니버스-탐지기 의존성 분리 + bridge 대상 확장 + 가격조회 배치 전환 완결"
version: "0.1.0"
status: implemented
created: 2026-08-04
updated: 2026-08-10
author: Nexsol
priority: High
phase: "backend surge-detection v0.1.0"
module: "backend/app/services"
lifecycle: spec-anchored
tags: "surge-detection, scan-universe, bridge-candidates, price-history, batching, backend"
tier: M
related_specs: [SPEC-AI-016, SPEC-AI-038, SPEC-AI-065, SPEC-AI-072, SPEC-AI-074, SPEC-AI-076, SPEC-AI-092, SPEC-AI-094, SPEC-AI-096, SPEC-AI-097, SPEC-AI-101]
---

# SPEC-AI-102: 급등예측 후보군 손실 구조 개선

## HISTORY

- 2026-08-04 v0.1.0 (draft): 2026-08-04자 외부(GPT) 급등예측 파이프라인 구조진단 비평의 후속
  조치로 작성. 비평은 "스캔 유니버스 생성이 탐지기 실행 이후에 일어나 탐지기가 못 잡은 종목이
  구조적으로 손실된다"(Problem 1), "가격조회 사전필터 50이 그대로 방치되어 있다"(Problem 2),
  "종목별 순차 HTTP 호출 지점이 SPEC-AI-097 이후에도 대부분 남아있다"(Problem 3) 세 가지를
  지적했다. **orchestrator가 실제 코드(`surge_detector.py`)를 직접 대조 검증한 결과, Problem 1의
  진단은 부분적으로 부정확함이 드러났다** — `build_scan_universe()`의 Pool A/B/C/D 소싱
  로직(`:5010`-`:5209`)은 `existing_codes`/`merged`(탐지기 결과)를 전혀 참조하지 않으며,
  `existing_codes`는 함수 말미(`:5222`, "기존 탐지기 결과 추가 — 우선순위 최하") existing 태깅
  단계에서만 쓰인다. 즉 "탐지기가 못 잡은 종목의 손실"은 순서 문제가 아니라, 그 손실을 메우는
  기존 메커니즘(`generate_scan_universe_bridge_candidates`, SPEC-AI-092)이 (a) 기본
  비활성이고 (b) `pool_a`/`pool_c`만 대상으로 설계되어 있으며 — 그 설계 근거가 "pool_b는
  신규 외부 fetch가 필요해서 제외"(`surge_detector.py:5387` 부근 docstring)였다는 사실에서
  비롯된다. SPEC-AI-097이 그 fetch 비용 자체를 낮췄으므로, 이 SPEC은 원 비평이 요구한 "재정렬"
  대신 **더 작고 근거가 명확한 두 가지 수정**(bridge 대상에 pool_b 추가 + 함수 분리로 불필요한
  구조적 의존성 제거)으로 재구성했다. 상세 근거는 §Context 참조.

## 선행 SPEC

- **SPEC-AI-092** (완료): `generate_scan_universe_bridge_candidates()`(`surge_detector.py:5355`)
  도입 — 스캔 유니버스에는 있으나 `merged`(1차 탐지기 결과)에 없는 종목을 신규 외부 fetch 없이
  bridge 후보로 승격. `pool_a`/`pool_c`만 대상(`scan_universe_bridge_pool_limits` 기본값
  `{"pool_a": 10, "pool_c": 10}`), 마스터 스위치 `scan_universe_bridge_candidates_enabled`
  기본 False. `surge_settings.py:630-648` 주석에 "pool_b는 가격이력 fetch가 필요해 대상에서
  제외"라는 설계 근거가 명시되어 있다 — 본 SPEC이 재평가하는 지점.
- **SPEC-AI-094** (완료): `build_scan_universe()`의 existing 병합 필터 판정 기준을
  `entry_pool_map` 미등재에서 `_pool_member_codes` 미소속으로 교정. `scan_universe_include_existing`
  플래그(기본 False)와 existing-tail 병합 루프(`:5210`-`:5229`) 소유.
- **SPEC-AI-096** (완료): 스캔 유니버스 quota 배분(Pool A/B/C/D 최소 슬롯 예약) + 절단 면제
  정책. §Decisions D2에서 `_MAX_PRICE_FETCH_CANDIDATES=50` 상향을 **명시적으로 보류**하며 근거로
  "배치 HTTP 인프라(SPEC B) 없이 숫자를 올리면 2026-06-30 이전에 겪은 300초 타임아웃을 재현할
  위험"을 들었다 — 그 "배치 HTTP 인프라"가 바로 SPEC-AI-097이며, 이제 존재한다.
- **SPEC-AI-097** (완료): `fetch_stock_price_history_batch_sync()`(`naver_finance.py:863`)
  신설 — `ThreadPoolExecutor` 기반 동시조회 + `pages` 인지형 캐시. `detect_volume_breakout()`
  (`surge_detector.py:4704`) 1곳만 전환 완료했고, spec.md에서 "top-50 절단 정책 완화 여부는
  별도 형제 SPEC 소관"이라고 명시적으로 위임했다 — 본 SPEC이 그 형제 SPEC이다.
- **SPEC-AI-072/074/076**: `build_scan_universe()` Pool B(거래량 200%+) 소싱 로직 및
  레버리지/인버스 ETF·ETN 배제 필터(`fetch_tracked_stock_codes`) 소유 — 무변경 유지.
- **SPEC-AI-101** (`status: draft`로 spec.md 작성 완료 — 이 SPEC 작성 시점에는 `research.md`만
  존재했으나 이후 spec.md가 작성됨): outcome 라벨 재정의 및 horizon(예측 지평) 임계값 활성화.
  형제 관계 — 범위 중복 없음(related_specs로만 연결).

## Context / Problem

### 검증된 사실 1 — `build_scan_universe()`의 Pool A/B/C/D 소싱은 `merged`(탐지기 결과)와 무관하게 이미 독립적이다

`surge_detector.py:4958`-`5345`(`build_scan_universe`) 전체를 대조 검증한 결과, Pool
A(DART 공시, `:5010`-`:5059`) / Pool B(거래량 200%+, `:5061`-`5131`) / Pool
C(등락률 5%+, `:5132`-`5167`) / Pool D(뉴스 언급, `:5169`-`5208`) 소싱 쿼리 4개 모두
`existing_codes` 매개변수를 전혀 참조하지 않는다 — 각각 DB(`Disclosure`, `SurgeActualOutcome`,
`NewsStockRelation`)와 외부 API(`fetch_volume_leaders_sync`)만 조회한다.
`existing_codes`는 함수 말미(`:5210`-`5229`, "기존 탐지기 결과 추가 — 우선순위 최하")에서
existing 태깅과 `_existing_only`/`_existing_tail` 계산에만 쓰인다. 호출부
(`gather_surge_candidates:2299`)가 8개 탐지기 병합(`merged`) **이후에** `build_scan_universe`를
호출하는 것은 사실이지만, 그 호출 순서가 Pool A/B/C/D의 산출 내용 자체를 바꾸지는 않는다 —
`existing_codes`를 빈 집합(`set()`)으로 호출해도 Pool A/B/C/D 4개 리스트와
`entry_pool_map`(existing 태깅 제외)은 완전히 동일하게 산출된다. 이는 GPT 비평의 Problem 1
("탐지기가 못 잡은 종목은 유니버스에 편입될 기회가 구조적으로 없다")이 문자 그대로는
부정확함을 뜻한다 — Pool 소싱 자체는 탐지기 완료를 기다릴 필요가 **없다**.

### 검증된 사실 2 — "탐지기가 못 잡은 종목을 편입"하는 메커니즘은 이미 존재하지만 pool_b가 제외되어 있고, 그 제외 사유가 이제 재평가 가능하다

`generate_scan_universe_bridge_candidates()`(`surge_detector.py:5355`-`5418`, SPEC-AI-092)가
정확히 이 문제("스캔 유니버스에는 있지만 `merged`에 없는 종목")를 다루는 기존 메커니즘이다.
`candidate_codes = [code for code in universe_codes if code not in merged and
entry_pool_map.get(code) in ("pool_a", "pool_c")]`(`:5390`-`5393`)로 **pool_a/pool_c만**
대상으로 하드코딩되어 있다. 함수 docstring(`:5362`-`5366`)이 그 이유를 명시한다: "1차 탐지기
결과(merged)에 없는 pool_a/pool_c 종목을 **이미 조회된 DB 자료**(Disclosure.impact_score,
SurgeActualOutcome.change_rate)만으로 점수화 — **신규 외부 fetch(Naver/DART) 호출 없음**".
pool_b(거래량 200%+)가 제외된 이유는 pool_b를 점수화하려면 가격이력(baseline 거래량 대비 당일
거래량 비율)이 필요한데, 그 조회가 종목당 순차 `fetch_stock_price_history_sync` 호출이라
비용이 부담스러웠기 때문이다 — SPEC-AI-097이 그 정확한 비용(순차 HTTP)을 낮추는 배치 함수를
신설했으므로, 이 제약은 이제 재검토 대상이다.

또한 `scan_universe_bridge_candidates_enabled`(`surge_settings.py:648`) 마스터 스위치는
SPEC-AI-096 §Decisions D4가 이미 "canary→기본활성화 전환 기준"(10 거래일 관측 등)을 문서화한
**운영 판단 대상**이다 — 본 SPEC은 그 마스터 스위치의 기본값이나 활성화 절차를 건드리지
않는다(§Non-Goals). 본 SPEC이 바꾸는 것은 마스터 스위치가 ON일 때 **대상 범위**뿐이다.

### 검증된 사실 3 — `_MAX_PRICE_FETCH_CANDIDATES=50`은 SPEC-AI-096이 "배치 인프라 부재"를 이유로 명시적으로 보류한 값이며, 그 인프라가 이제 존재한다

`surge_detector.py:2007`-`2011` 주석이 직접 인용한다: "이 숫자(50)는 SPEC-AI-096에서도
무수정이다(§Decisions D2 — 배치 HTTP 인프라 없이 숫자를 올리면 과거 300초 타임아웃 재현
위험)". SPEC-AI-096 spec.md §Decisions D2(`:197`-`203`)는 "배치 HTTP 인프라(SPEC B) 없이
숫자를 올리면 ... 300초 타임아웃을 재현할 위험이 있다"고 명시했다 — 이 "SPEC B"가 바로
완료된 SPEC-AI-097이다. `_apply_price_fetch_truncation()`(`:2027`-`2079`)은 이미
`entry_pool != "existing"`(즉 pool_a/b/c/d 소속) 후보를 절단 대상에서 면제하므로(SPEC-AI-096
D2), 50 상한의 실질 영향 범위는 순수 `entry_pool == "existing"` 후보로 이미 좁혀져 있다 —
그럼에도 그 좁혀진 범위 안에서도 배치 인프라가 생긴 지금, 50이라는 숫자 자체가 여전히
최적인지는 재평가할 근거가 갖춰졌다.

### 검증된 사실 4 — 순차 HTTP 호출 지점은 SPEC-AI-097 전환분(1곳) 제외 6곳이 남아있고, 그중 `build_scan_universe()` Pool B 루프가 단일 최대 규모다

`grep -n "fetch_stock_price_history_sync(" app/services/surge_detector.py`로 확인한
잔여 순차 호출 지점(전환 완료된 `detect_volume_breakout`의 `fetch_stock_price_history_batch_sync`
호출 제외) 6곳:

| 위치 | 함수 | 요청 규모 | 용도 |
|------|------|-----------|------|
| `:1068` | `_get_volume_history` | 종목 1개, `pages=1` | 거래량 이력(baseline_days) |
| `:2756` | `_get_peer_price_5d_trend` | 종목 1개, `pages=1` | 동종 그룹 5일 추세 |
| `:3023` | `_detect_volume_anomaly_internal` | `all_stocks` 순회, `pages=config.history_pages` | 휴면 재활성 탐지 |
| `:3274` | `detect_near_limit_up_carries` | `candidates` 순회, `pages=3`(기본) | T-1 종가 계산 |
| `:4404` | `detect_bollinger_squeeze_signals` | `top_stocks` 순회, `pages=config.price_pages` | 볼린저 밴드 |
| **`:5102`** | **`build_scan_universe`(Pool B)** | **`volume_leader_codes` 순회(최대 140종목×3페이지, `fetch_volume_leaders_sync(limit=140, max_pages=3)`)** | **거래량 200%+ 판정** |

`:1068`/`:2756`은 종목 1개짜리 단발 조회라 배치 전환의 이득이 낮다. `:5102`(Pool B 루프)는
단일 호출로 최대 140종목까지 순회할 수 있어 6곳 중 유일하게 100종목대 규모이며,
`detect_volume_breakout`(이미 전환 완료)과 동일한 패턴(전량 조회 → baseline 대비 비율 계산)을
사용해 구조적으로 가장 가까운 전환 대상이다.

## Goals

1. `build_scan_universe()`를 "Pool A/B/C/D 소싱"과 "existing 태깅·최종 조립"으로 내부 분리하되,
   기존 시그니처·반환값은 하위 호환 유지 — 검증된 사실 1의 불필요한 구조적 의존성을 제거하고,
   향후 가격조회 캐시 예열 등에 활용할 수 있는 지점을 만든다.
2. `generate_scan_universe_bridge_candidates()`의 대상 범위에 `pool_b`를 추가하되, 기존
   pool_a/pool_c 경로(신규 fetch 없음)와 리스크 프로필이 다르므로 별도 하위 플래그로 분리한다.
3. `_MAX_PRICE_FETCH_CANDIDATES=50`을 SPEC-AI-097 배치 인프라 기준으로 재평가하고, 상향하거나
   "변경 없음"의 근거를 남긴다.
4. 잔여 순차 HTTP 호출 지점을 가능한 범위에서 배치 함수로 전환하며, 최소한
   `build_scan_universe()` Pool B 루프(검증된 사실 4의 최대 규모 지점)는 반드시 전환한다.

## Non-Goals

### Out of Scope — 탐지기 스코어링 자체

- 8개 탐지기의 스코어링 알고리즘·가중치·임계값 변경.
- `compute_ensemble_score()`(`:1574`) 산출식 변경.

### Out of Scope — outcome 라벨/horizon/ML

- 정답 라벨(outcome) 재정의, horizon(예측 지평) 임계값 활성화 — SPEC-AI-101 소관.
- ML 모델 학습/도입 — 무관한 별개 축.

### Out of Scope — Pool D 활성화 및 bridge 마스터 스위치 기본값 전환

- `pool_d_min_slots`, `scan_universe_bridge_candidates_enabled`의 기본값을 True로 전환하는
  것은 이미 SPEC-AI-096 §Decisions D3/D4가 문서화한 별도의 관측-기반 운영 활성화 절차(각각
  최소 5/10 거래일 관측)이며, 코드 SPEC이 아니라 운영 판단 대상이다. 본 SPEC은 bridge
  "대상 범위"에 pool_b를 추가할 뿐 — 마스터 스위치 기본값이나 canary→기본활성화 전환 기준
  자체는 건드리지 않는다.

### Out of Scope — 매수 주문 실행 경로

- `fetch_current_prices_batch()`(SPEC-AI-016), `surge_trading_service.py` 매수 흐름 —
  SPEC-AI-097과 동일 경계 승계.

### Out of Scope — Pool A/B/C/D 소싱 쿼리 자체의 로직 변경

- Pool A(impact 정렬), Pool B(레버리지/인버스 배제, `_min_ratio`), Pool C(등락률 5% 하한),
  Pool D(뉴스 언급 조인) 각 소싱 쿼리의 필터·정렬 로직은 SPEC-AI-065/074/076/078/086
  소유이며 무변경 — 본 SPEC은 "언제 호출 가능한가"(§Goals 1)와 "그 결과를 bridge로 얼마나
  활용하는가"(§Goals 2)만 다룬다.

## Decisions

### D1 — `build_scan_universe()`를 "Pool 소싱" + "existing 병합·최종 조립"으로 내부 분리한다(하위 호환 wrapper 유지)

**채택**: 기존 `build_scan_universe(db, config, existing_codes, now)` 시그니처와 반환값
(`universe_codes, entry_pool_map, pool_counts`)은 그대로 유지한다. 내부적으로 Pool A/B/C/D
소싱(`existing_codes`를 참조하지 않는 부분, `:5010`-`5209`)과 existing 병합·quota 배분·최종
조립(`existing_codes`를 참조하는 부분, `:5210`-`5345`)을 각각 별도 함수로 추출하고,
`build_scan_universe()` 자체는 두 함수를 순서대로 호출하는 얇은 wrapper가 된다. 이렇게 하면
(a) 기존 호출부·테스트가 무수정으로 계속 동작하고(REQ-AI102-001 필수 조건), (b) Pool 소싱
결과가 `merged` 완성을 기다릴 필요가 없다는 사실이 코드 구조로도 드러나 향후 SPEC이 이를
활용하기 쉬워진다(예: Pool B 루프가 배치 전환된 뒤, 다른 탐지기가 같은 종목의 가격이력을
조회할 때 SPEC-AI-097의 pages 인지형 캐시를 통해 중복 HTTP 호출이 줄어드는 예열 효과).

**기각한 대안 1 — `gather_surge_candidates()`의 호출 순서 자체를 앞당겨 Pool 소싱을 8개
탐지기보다 먼저 실행**: 검증된 사실 1에 따르면 이 재정렬은 candidate 손실을 막는 효과가 없다
(existing 태깅은 어차피 `merged` 완성 후에만 가능하고, 그 태깅이 없어도 Pool A/B/C/D 자체
산출물은 동일하다). 재정렬은 순전히 코드 가독성 개선일 뿐 관측 가능한 동작 변화가 없어,
이 SPEC의 실질 목표(Goal 2/3/4)에 기여하지 않는 변경을 위해 리스크(호출 순서 변경에 따른
회귀 가능성)만 지는 셈이다 — 기각.

**기각한 대안 2 — Pool 소싱과 8개 탐지기를 스레드로 진짜 병렬 실행**: 8개 탐지기 함수는 전부
동기(`def`)이며 SQLAlchemy `db: Session`을 공유한다. SQLAlchemy Session은 스레드-안전하지
않으므로 진짜 동시 실행은 세션 관리 재설계(스레드별 세션 분리)가 필요해 스코프를 크게
벗어난다 — 기각(YAGNI, Enforce Simplicity 사다리).

### D2 — bridge 후보화에 pool_b를 하위 플래그로 추가한다(마스터 스위치와 별개, 신규 fetch 명시 허용)

**채택**: `generate_scan_universe_bridge_candidates()`가 pool_b 소속이면서 `merged`에 없는
종목에 대해서는, 기존 pool_a/c의 "DB 재조회만" 원칙과 달리 SPEC-AI-097의
`fetch_stock_price_history_batch_sync()`로 가격이력을 조회해 거래량 비율을 계산하고
점수화한다. `scan_universe_bridge_candidates_enabled`(마스터 스위치)와 신규 하위 플래그
(예: `scan_universe_bridge_pool_b_enabled`, 기본값 False)가 **모두** True일 때만 pool_b
bridge 경로가 활성화된다 — 마스터 스위치 OFF 시 완전 무회귀는 그대로 유지되고, 마스터
스위치가 이미 ON인 배포에서도 pool_b 하위 플래그가 별도로 OFF면 pool_a/c만 대상인 기존
동작과 동일하다. `scan_universe_bridge_pool_limits`에 `"pool_b"` 키를 추가로 허용해
상한을 독립적으로 제어한다.

**기각한 대안 — pool_b를 REQ-AI092-005("신규 외부 fetch 없음") 원칙 위반으로 보고 손대지
않는다**: SPEC-AI-097 배치 인프라가 이미 존재하는 상황에서 그 제약의 근거(비용)가 바뀌었는데도
정책을 그대로 두는 것은 근거 없는 보수성이다. 다만 pool_a/c와 리스크 프로필이 다르므로
(신규 HTTP 호출 발생) 완전히 같은 플래그로 묶지 않고 하위 플래그로 분리해 롤백 단위를
좁힌다 — 기각(단, 위험 분리 설계는 채택안에 반영).

### D3 — `_MAX_PRICE_FETCH_CANDIDATES` 구체적 상향 폭은 plan.md M1 실측으로 결정한다

**결정 자체는 이 SPEC 범위**(REQ-AI102-003), **구체적 숫자는 위임**: SPEC-AI-096 D2가 "배치
인프라 없이 올리면 위험"이라 명시했으므로 이제 인프라가 있다는 사실은 재평가 트리거이지만,
안전한 구체적 상향 폭(50→80? 100?)은 배치 조회 시 실제 스캔 사이클 소요시간을 측정해야 결정
가능하다. plan.md M1 사전조사에서 N=80/100/150 각각 실측 후 Implementation Kickoff Approval
이전 사용자와 확정한다(§Open Questions). "변경 없음"도 유효한 결론이다.

### D4 — Pool B 루프(`build_scan_universe:5098`-`5126`)를 잔여 배치 전환의 최우선 대상으로 지정한다

**채택**: 검증된 사실 4에서 확인했듯 Pool B 루프는 순차 호출 지점 중 유일하게 최대 140종목
규모(다른 지점들은 config 상위종목 N개 또는 단일 종목 수준)이며, 이미 SPEC-AI-097이 검증한
`detect_volume_breakout` 전환분과 거의 동형(전량 배치 조회 → baseline 대비 비율 계산)이라
전환 리스크가 가장 낮다. 단발 조회 지점(`_get_volume_history`, `_get_peer_price_5d_trend`,
각 pages=1 종목 1개)은 배치 이득이 없어 전환 대상에서 제외한다(plan.md에서 판단 근거 기록).

## Requirements

### REQ-AI102-001: Pool 소싱 / existing 병합 분리

**When** `gather_surge_candidates()`가 `build_scan_universe()`의 결과를 필요로 하면, the
system **shall** Pool A/B/C/D 소싱 로직과 existing 코드 병합·quota 배분·최종 조립 로직을
내부적으로 별도 호출 가능한 두 함수로 분리해야 한다.

필수 조건:

- 기존 `build_scan_universe(db, config, existing_codes, now)` 시그니처와 반환값
  (`universe_codes, entry_pool_map, pool_counts`)은 하위 호환 wrapper로 그대로 유지되어,
  기존 모든 호출부(테스트 포함, `test_spec_ai_094.py`/`test_spec_ai_096.py` 등)가 무수정으로
  계속 통과해야 한다.
- 신규 분리는 최소 1개의 독립 유닛 테스트로 "`existing_codes=set()`으로 Pool 소싱 함수를
  단독 호출해도 Pool A/B/C/D 리스트(existing 태깅 제외)가 `build_scan_universe()` 전체
  호출 시와 동일하게 산출됨"을 검증해야 한다.

### REQ-AI102-002: bridge 후보화에 pool_b 하위 플래그 추가

**Where** `scan_universe_bridge_candidates_enabled`와 신규 하위 플래그(pool_b 대상, 기본값
False)가 모두 True이면, the system **shall** `generate_scan_universe_bridge_candidates()`가
pool_b 소속이면서 `merged`에 없는 종목에 대해 `fetch_stock_price_history_batch_sync()`
(SPEC-AI-097)로 가격이력을 조회해 거래량 비율로 점수화하고 bridge 후보 목록에 포함해야 한다.

필수 조건:

- 신규 하위 플래그가 False(기본값)이면 pool_a/c만 대상인 기존 동작과 완전히 동일해야
  한다(무회귀) — 마스터 스위치가 이미 True인 배포에서도 동일하게 보장되어야 한다.
- pool_b bridge 후보 수는 `scan_universe_bridge_pool_limits["pool_b"]`(신규 키, 기본값 5)로
  상한을 둔다.
- pool_b bridge 스코어링으로 발생하는 신규 HTTP 호출은 `scan_universe_bridge_max_candidates`
  전체 상한 안에서만 발생해야 한다 — 무제한 확장 금지.

### REQ-AI102-003: `_MAX_PRICE_FETCH_CANDIDATES` 재평가

**When** plan.md M1 사전조사가 SPEC-AI-097 배치 인프라 기준 안전 상한을 실측하면, the
system(의 plan.md 및 구현 커밋 메시지)은 `_MAX_PRICE_FETCH_CANDIDATES` 값을 그 실측 근거와
함께 유지하거나 상향해야 한다.

필수 조건:

- 값을 변경하지 않기로 결정하더라도, 그 판단 근거(측정 결과)를 커밋 메시지 또는 plan.md에
  기록해야 한다 — "변경 없음"도 유효한 결론이다.
- 상향할 경우, `entry_pool != "existing"` 면제 정책(SPEC-AI-096 D2)의 의미(existing 전용
  후보에만 적용되는 절단)는 변경하지 않는다.

### REQ-AI102-004: 잔여 순차 HTTP 호출 지점의 배치 전환

**When** 스코어링 경로가 2개 이상 종목의 가격이력을 순차 for-loop로 조회하면, the system
**shall** 가능한 지점에 한해 `fetch_stock_price_history_batch_sync()`(SPEC-AI-097)로
전환해야 하며, 최소한 `build_scan_universe()` Pool B 루프(`surge_detector.py:5098`-`5126`,
검증된 사실 4의 최대 규모 지점)는 반드시 전환해야 한다.

필수 조건:

- 전환 대상 각각에 대해 기존 동작(baseline 계산, 필터링 로직, `_resolve_today_volume` 결과)이
  characterization 테스트로 무회귀 검증되어야 한다.
- 배치 이득이 없는 단발(종목 1개, pages=1) 조회 지점(`_get_volume_history`,
  `_get_peer_price_5d_trend`)은 전환하지 않기로 결정할 수 있으며, 그 판단 근거를 plan.md에
  남겨야 한다.

### REQ-AI102-005: 매수 주문 실행 경로 및 탐지 스코어링 무영향

**While** 본 SPEC이 적용되는 동안, the system **shall not** `fetch_current_prices_batch()`,
`surge_trading_service.py` 매수 흐름, 8개 탐지기의 스코어링 알고리즘·가중치,
`compute_ensemble_score()`를 변경한다.

필수 조건:

- `git diff --name-only`에 위 파일들이 포함되면 순수 추출/리팩터이며 characterization
  테스트로 바이트 동등을 증명해야 한다.

## Open Questions

1. **`_MAX_PRICE_FETCH_CANDIDATES` 상향 폭**: 결정 방법은 확정되었다 — M1(TASK-001)
   사전조사에서 N=80/100/150 각각에 대해 배치 조회(`fetch_stock_price_history_batch_sync`)
   시 스캔 사이클 소요시간을 실측하고, 그 결과를 최종 값 선택의 근거로 삼는다(§Decisions D3,
   REQ-AI102-003). 구체적 숫자는 M1 완료 시점에 progress.md에 실측 결과와 함께 기록하며,
   Implementation Kickoff Approval 이전 사용자와 확정한다 — "변경 없음(50 유지)"도 유효한
   결론이다.
2. **`scan_universe_bridge_pool_limits["pool_b"]` 기본값**: **5로 확정**. pool_a/c는 각
   10인데 pool_b는 신규 HTTP 호출 비용이 발생하므로(§Decisions D2) 더 보수적인 시작값을
   채택한다.
