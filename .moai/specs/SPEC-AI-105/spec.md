---
id: SPEC-AI-105
title: "급등예측 스캔 유니버스 bridge 후보 활성화 검증 — Shadow 정밀도 측정 게이트"
version: "0.1.0"
status: in-progress
created: 2026-08-06
updated: 2026-08-06
author: Nexsol
priority: High
phase: "backend surge-detection v0.1.0"
module: "backend/app/services"
lifecycle: spec-anchored
tags: "surge-detection, scan-universe, bridge-candidates, activation-gate, precision-measurement, shadow-observation, backend"
tier: M
related_specs: [SPEC-AI-089, SPEC-AI-092, SPEC-AI-096, SPEC-AI-102, SPEC-AI-104]
---

# SPEC-AI-105: 급등예측 스캔 유니버스 bridge 후보 활성화 검증 — Shadow 정밀도 측정 게이트

## HISTORY

- 2026-08-06 v0.1.0 (draft): 위임 프롬프트("`scan_universe_bridge_candidates_enabled`를
  활성화해야 하는가, 활성화한다면 어떤 검증된 조건 아래에서인가")에 대한 응답으로 작성.
  코드 직접 확인으로 `generate_scan_universe_bridge_candidates()`의 `_target_pools`가
  `pool_d`를 절대 포함하지 않음을 확인해, SPEC-AI-096 §Decisions D4가 명시한 "Pool D
  관측 인프라 선행 배포" 전제가 bridge에는 실제로 무관함을 정정했다(§Context 핵심 정정
  참고). Pool C의 bridge scoring이 Pool C 자신의 유니버스 진입 기준보다 느슨해 사실상
  무필터에 가깝다는 정밀도 리스크를 코드 산술로 확인해 push-back으로 기록했다(§Decisions
  D2). SPEC-AI-104가 Pool D canary 전환에 사용한 "wire → 관측 → 활성화는 별도 결정"
  패턴을 그대로 재사용해, 이 SPEC은 shadow 계측(관측 전용, 무회귀)까지만 배포하고 실제
  마스터 스위치 반전은 이 SPEC의 산출물이 아니다.

## 선행 SPEC

- **SPEC-AI-089** (완료): `measure_universe_detection_gap()` / `analyze_no_signal_pool_attribution()`
  — 순수 읽기 계측 함수 패턴의 최초 소유 SPEC. 본 SPEC의 신규 분석 함수는 이 자매
  패턴을 그대로 계승한다.
- **SPEC-AI-092** (완료): `generate_scan_universe_bridge_candidates()` 최초 구현.
  `scan_universe_bridge_candidates_enabled` 기본값 `False`. 본 SPEC은 이 함수의
  스코어링 로직을 재사용만 하며 절대 수정하지 않는다.
- **SPEC-AI-096** (완료): `max_scan_universe` 150→250 상향(D1), bridge 단계적 활성화
  기준 문서화(D4 — canary 값·관측기간 "임의 제안값, Open Questions" 명시). 본 SPEC은
  D4가 위임한 "후속 SPEC이 세부 수치를 확정한다"는 과제를 이어받는다.
- **SPEC-AI-102** (진행중, `in-progress` — 완료 아님, 코드는 이미 존재): `scan_universe_bridge_pool_b_enabled`
  하위 플래그. pool_b bridge 경로는 신규 HTTP 호출(가격이력 배치 조회)을 동반해 pool_a/
  pool_c와 리스크 프로필이 다르다. 본 SPEC은 pool_b를 shadow 계측 범위에서 명시적으로
  제외한다(§Decisions D4).
- **SPEC-AI-104** (draft, 미배포): Pool D canary 전환(`pool_d_min_slots` 0→10) SPEC.
  본 SPEC과 병렬 관계다 — Pool D 배포 여부와 무관하게 bridge 활성화 게이트는 진행
  가능함을 §Context에서 정정한다(Pool D는 bridge의 `_target_pools`에 없음).

## Context / Problem

### `scan_universe_bridge_candidates_enabled`가 도입 후 단 한 번도 켜진 적이 없다

`generate_scan_universe_bridge_candidates()`(`surge_detector.py:5766-6012`, SPEC-AI-092
REQ-AI092-003/004, SPEC-AI-102 REQ-AI102-002)는 `build_scan_universe()`가 이미 산출한
`universe_codes`/`entry_pool_map`과 1차 탐지기 결과(`merged`)만 입력으로 받아, `merged`에
없는 pool_a/pool_c(하위 플래그 시 pool_b) 종목을 이미 조회된 DB 자료만으로 점수화해
`SurgeCandidate`로 승격한다. 이 함수는 신규 외부 fetch 없이(pool_a/pool_c 경로)
`qualified` 최종 후보 목록에 실제로 합류하는 유일한 "유니버스 소속 → 매매후보 승격"
경로다(`:2694` 호출, `:2981-2984` 합류). 그러나 마스터 스위치
`scan_universe_bridge_candidates_enabled`(`surge_settings.py:696`) 기본값이 `False`이고,
`surge_detection.yaml`에 이 키가 명시되지 않아(코드 직접 확인, grep 결과 매치 없음)
Pydantic 기본값이 곧 배포값이다 — 도입(SPEC-AI-092, 2026-07-28) 이후 프로덕션에서
단 한 번도 활성화된 적이 없다.

### 검증된 사실 (코드 직접 확인)

1. `_BRIDGE_MIN_SCORE = 0.3`(`surge_detector.py:5750`)는 config가 아니라 함수 내부
   모듈 상수다. pool_a 점수 = 오늘 공시 최대 `impact_score / 100.0`(`:5837-5861`),
   pool_c 점수 = 최신 거래일 등락률(`SurgeActualOutcome.change_rate`) `/ 15.0`
   (`:5863-5893`).
2. `_target_pools: tuple[str, ...] = ("pool_a", "pool_c")`(`:5811`)이며,
   `config.scan_universe_bridge_pool_b_enabled`가 `True`일 때만 `pool_b`가 추가된다
   (`:5812-5813`). **`pool_d`는 이 튜플에 절대 등장하지 않는다** — Pool D는 bridge의
   소싱 대상이 전혀 아니다(SPEC-AI-096 research.md §C.1 "Pool D는 여전히 측정 유니버스일
   뿐 — 실제 후보 승격은 bridge를 통해서만 가능" 서술과도 일치 — 단, 그 승격이 pool_a/c/b
   한정임은 SPEC-AI-096 본문에 명시되지 않았다).
3. `scan_universe_bridge_max_candidates: int = 20`, `scan_universe_bridge_pool_limits:
   {"pool_a": 10, "pool_b": 5, "pool_c": 10}`(`surge_settings.py:699, 718-720`) — 전체
   상한과 pool별 상한이 이미 config로 존재한다.
4. `max_scan_universe`는 SPEC-AI-096 D1에 의해 `150 → 250`으로 이미 배포되었다
   (`surge_detection.yaml:291`, 코드 직접 확인). bridge는 `universe_codes`(pool_a/pool_c
   소싱, 이 cap의 영향을 받음)에서 후보를 뽑으므로, 이 상향은 bridge 후보 풀 크기에
   실질적 영향을 준다.

### 핵심 정정 — SPEC-AI-096 D4의 "Pool D 선행 배포" 전제는 부정확하다

SPEC-AI-096 §Decisions D4는 bridge 활성화 절차의 첫 조건으로 "(1) D1(캡 250)과
D3(Pool D 관측 인프라)가 먼저 배포되어야 한다"고 명시한다. 그러나 검증된 사실 2번이
보이듯 `_target_pools`는 `pool_d`를 포함한 적이 없다 — bridge는 Pool D 소속 종목을
절대 대상으로 삼지 않는다. D4가 D3을 전제조건으로 든 근거("bridge는 pool_a/pool_c 한정
소싱 유니버스에서 후보를 뽑으므로 캡이 작으면 후보 풀 자체가 작다")는 사실 `max_scan_universe`
캡(D1) 하나만으로 완전히 설명되며, Pool D 관측 인프라(D3)의 배포 여부는 bridge 후보
풀 크기에 아무 영향을 주지 않는다. 따라서 D1(이미 배포됨)만으로 bridge 활성화의
캡 관련 전제조건은 이미 충족된 상태다 — SPEC-AI-104(Pool D canary)의 배포 여부는 본
SPEC의 진행을 막는 전제조건이 아니다(§Decisions D3에서 문서 정정으로 반영).

### Pool C bridge scoring의 정밀도 리스크 — 사실상 무필터에 가깝다

`_BRIDGE_MIN_SCORE(0.3)`를 pool_c 산식(`change_rate / 15.0`)에 대입하면 최소 통과
등락률은 `change_rate >= 4.5%`다. 그런데 Pool C 자신의 유니버스 진입 기준(SPEC-AI-065,
`_source_scan_universe_pools()`)은 이미 `change_rate >= 5%`(및 양거래량)를 요구한다 —
즉 어떤 종목이 애초에 pool_c에 진입했다면, bridge의 자체 점수 기준(4.5%)은 이미 그보다
엄격한 진입 기준(5%)에 항상 미달 없이 통과한다. **bridge scoring은 pool_c에 대해 사실상
2차 필터가 아니라 통과 의례에 가깝다.** 반면 pool_a는 `impact_score >= 30`이 실제
변별력을 가진다(SPEC-AI-081 조사 기록상 flat 카테고리 baseline 20~25는 이 문턱 아래).
이 비대칭은 pool_a/pool_c를 하나로 묶어 관측하면 강한 pool_a 정밀도가 약한 pool_c를
가릴 위험을 만든다(§Decisions D2, push-back).

### [미검증 인용] 원 위임 프롬프트의 "2026-07-28 Pool C 3종목 미승격" 주장

원 위임 프롬프트는 "2026-07-28 인시던트에서 Pool C에 3종목이 있었으나 어떤
`surge_candidate`도 생성되지 않았다"고 인용했다. 이 세션은 SPEC-AI-092 spec.md §Context를
직접 재확인했으나, 거기 기록된 non-scannable 19개 원인 분해는 "source absent 11개 /
scan universe cap에서 truncated 8개"뿐이며 pool_c 특정 3종목 breakdown은 등장하지 않는다.
이 세션은 라이브 DB 조회 권한이 없어 이 구체적 수치를 독립 재검증하지 못했다 — Open
Questions에 남긴다.

## Goals

1. `scan_universe_bridge_candidates_enabled`를 실제로 켜지 않고도, 켰을 때 생성될
   bridge 후보의 pool별(pool_a/pool_c) 정밀도(실제 급등 적중률)를 여러 거래일에 걸쳐
   측정할 수 있는 shadow 계측 인프라를 배포한다.
2. shadow 계측이 `qualified`/`merged`/`FundSignal`/매매 실행 경로에 어떤 영향도 주지
   않음을 보장한다(SPEC-AI-092 REQ-AI092-005 "신규 외부 fetch 없음" 불변식과 동일한
   급의 무영향 보장).
3. SPEC-AI-096 D4가 "임의 제안값, Open Questions"로 남긴 활성화 절차(관측 기간, 비교
   기준선, 좁은 범위 우선 활성화 메커니즘)를 구체화한다 — 정확한 숫자 확정은 관측
   데이터 확보 후로 미루되, 절차와 데이터 계약은 이 SPEC이 확정한다.
4. Pool D 선행 배포 전제(SPEC-AI-096 D4)를 정정해, bridge 활성화 게이트가 SPEC-AI-104의
   배포 상태와 독립적으로 진행 가능함을 문서화한다.
5. 위 4개 항목 모두 기존 탐지기 스코어링·앙상블·quota 배분·bridge 스코어링 함수 본체·
   매매 실행 경로에 회귀를 주지 않아야 한다.

## Non-Goals

### Out of Scope — bridge 마스터 스위치 실제 활성화

- `scan_universe_bridge_candidates_enabled`를 `False`에서 `True`로 실제로 뒤집는 것은
  이 SPEC의 배포 산출물이 아니다. shadow 계측이 관측 데이터를 축적한 뒤 별도 SPEC
  또는 운영 판단으로 결정한다(SPEC-AI-066/079/091/084/085/086/092/096/104가 이미
  확립한 "배선 → 관측 → 활성화는 별도 결정" 관례를 그대로 따른다).

### Out of Scope — Pool D 관측 인프라 자체

- Pool D의 `pool_d_min_slots` canary 전환·정밀도 측정은 SPEC-AI-104(별도, draft) 소유다.
  본 SPEC은 그 SPEC의 배포 여부와 무관하게 진행되며, Pool D 코드를 일절 건드리지 않는다.

### Out of Scope — pool_b bridge 하위 경로

- `scan_universe_bridge_pool_b_enabled`(SPEC-AI-102, `in-progress`) 하위 플래그와 그
  가격이력 배치 조회(HTTP 신규 호출) 경로는 shadow 계측 범위에서 명시적으로 제외한다
  (§Decisions D4). SPEC-AI-102가 `completed`로 전환된 이후의 pool_b shadow 확장은
  별도 후속 SPEC 후보다.

### Out of Scope — bridge scoring 산식·임계값 변경

- `_BRIDGE_MIN_SCORE(0.3)`, pool_a/pool_c 점수 산식, `scan_universe_bridge_max_candidates`,
  `scan_universe_bridge_pool_limits` 기본값은 이 SPEC에서 변경하지 않는다. Pool C
  정밀도 리스크(§Context)에 대한 대응은 산식 변경이 아니라 shadow 관측과 좁은 범위
  우선 활성화 절차(§Decisions)로 다룬다.

### Out of Scope — 탐지기/앙상블/매매 실행 로직

- 8개 1차 탐지기의 스코어링, `compute_ensemble_score()`, quota 배분(SPEC-AI-065/074/
  076/078/086), `surge_trading_service.py`의 매수 실행 경로는 전부 무변경이다.

## Decisions

### D1 — 기존 `generate_scan_universe_bridge_candidates()`를 config override로 재호출한다(재구현 금지)

shadow 계측은 별도의 "미리보기" 스코어링 함수를 새로 작성하지 않고, 마스터 스위치만
`True`로 override한 config 사본을 만들어 **동일 함수를 그대로 재호출**한다. 기각한
대안: 스코어링 로직을 복제한 별도 shadow 함수 — 향후 `_BRIDGE_MIN_SCORE`나 점수
산식이 바뀔 때 shadow 계측이 실제 경로와 조용히 어긋날 위험이 있어 기각한다(Simplicity
Ladder — 기존 함수 재사용을 신규 코드보다 우선).

### D2 — Pool C shadow 정밀도는 pool_a와 분리 집계해야 한다 (push-back)

§Context에서 확인한 대로 pool_c의 bridge 점수 기준(4.5%)은 pool_c 자신의 유니버스
진입 기준(5%)보다 느슨해 사실상 무필터다. 따라서 신규 분석 함수(REQ-AI105-003)와
리포트(REQ-AI105-005)는 pool_a/pool_c를 blended 단일 수치로 합치지 않고 **반드시
pool별로 분리**해 보고해야 한다 — 합쳐서 보고하면 강한 pool_a 정밀도가 약한 pool_c의
근본적 무필터 문제를 가릴 수 있다. 향후 활성화 절차(REQ-AI105-007)도 pool_a/pool_c를
개별적으로 판단하도록 설계한다(각각 clear 여부 독립 판정 — blended 평균으로 판단
금지).

### D3 — Pool D 선행 배포 전제를 문서로 정정하고, SPEC-AI-104 배포 여부와 독립적으로 진행한다

SPEC-AI-096 D4의 "D3(Pool D 관측 인프라) 선행 배포 필요" 서술은 §Context 핵심 정정에서
보인 대로 부정확하다(bridge는 pool_d를 소싱하지 않음). 이 SPEC은 코드가 아닌 문서
(plan.md/CHANGELOG)로 이 정정을 기록하며, SPEC-AI-104의 배포 상태(현재 draft, 미배포)와
무관하게 진행한다. SPEC-AI-096 spec.md 본문 자체는 개정하지 않는다 — SPEC-AI-096은
`completed` 상태이며 이 정정은 그 SPEC의 완료 판정을 무효화하지 않는 후속 발견이다
(SPEC-AI-104가 SPEC-AI-096을 개정하지 않은 것과 동일한 근거).

### D4 — shadow 계측은 pool_b를 하드코딩으로 배제한다(안전 우선, config 값과 무관)

shadow 호출용 config override는 마스터 스위치(`scan_universe_bridge_candidates_enabled`)만
`True`로 바꾸고 `scan_universe_bridge_pool_b_enabled`는 원본 config 값을 그대로
전달한다 — 그러나 그와 별개로, shadow 계측 자체의 대상 pool 집합은 항상 `("pool_a",
"pool_c")`로 하드코딩해 pool_b를 원천 배제한다. 이유: pool_b bridge 경로는 가격이력
배치 조회(신규 HTTP 호출)를 동반해 SPEC-AI-092의 "신규 외부 fetch 없음" 원칙
(REQ-AI092-005)을 벗어난다 — shadow 계측이라는 "관측 전용, 비용 최소" 목적에 맞지
않는다. pool_b shadow 확장은 SPEC-AI-102가 `completed`로 전환된 이후 별도 SPEC
후보로 남긴다(Open Questions 3).

### D5 — 비교 기준선은 기존에 이미 영속화되는 시스템 전체 일일 정밀도를 재사용한다

"precision이 유의하게 낮다"의 비교 기준선으로, 탐지기별로 분해된 정밀도(현재 미영속화 —
[[project-surge-detector-constraints]] "Ensemble scoring internals" 참조)를 새로
계측하지 않고, 이미 매일 저장되는 `SurgePredictionEvaluation.precision`(AI-041/043
평가 파이프라인 산출물)을 재사용한다. 기각한 대안: 탐지기별 정밀도를 신규 계측 —
범위가 이 SPEC의 활성화 게이트 목적을 넘어선다(신규 영속 컬럼·집계 로직 필요).

## Requirements

### REQ-AI105-001: shadow bridge 후보 계측(기존 스코어링 재사용, 무영향)

**While** `scan_universe_bridge_shadow_enabled`가 `true`이고 실제 마스터 스위치
`scan_universe_bridge_candidates_enabled`가 `false`(기본값)로 유지되는 동안, the
system **shall** 마스터 스위치만 `true`로 override한 config 사본으로
`generate_scan_universe_bridge_candidates()`를 그대로 재호출해 shadow 후보를
계산해야 한다.

필수 조건:

- 신규 스코어링 산식을 작성하지 않는다 — `_BRIDGE_MIN_SCORE`, pool_a/pool_c 점수
  산식은 재사용만 한다(§Decisions D1).
- shadow 호출은 대상 pool 집합을 항상 `("pool_a", "pool_c")`로 고정한다 — 원본
  config의 `scan_universe_bridge_pool_b_enabled` 값과 무관하게 pool_b는 절대 포함
  하지 않는다(§Decisions D4).
- shadow 후보는 `qualified`/`merged`에 절대 합류하지 않으며, `FundSignal`·텔레그램
  알림·매매 실행 경로 어디에도 도달하지 않는다.

### REQ-AI105-002: shadow 후보 영속화 (신규 테이블)

**When** 거래일별 shadow 후보 계산이 완료되면, the system **shall** 각 후보의
`stock_code`/`entry_pool`/`bridge_score`를 신규 `surge_bridge_shadow_candidates`
테이블에 저장해야 한다.

필수 조건:

- `SurgeUniverseMember`(SPEC-AI-068)와 동일한 일자당 replace(DELETE-then-insert)
  semantics를 재사용한다(`persist_universe_members()` 패턴 계승).
- composite PK `(trading_date, stock_code)`. 신규 alembic 리비전 1건 추가(현재 head
  확인: `074_surge_horizon_shadow_observation` — run-phase 착수 직전 `alembic heads`로
  재확인 필수, 다른 병렬 SPEC이 먼저 배포되면 head가 이동할 수 있다).
- 백필 없음 — 배포 시점 이후 관측만 축적한다(SPEC-AI-093/095/104 전진 적용 원칙 승계).

### REQ-AI105-003: pool별 shadow 정밀도 분석 함수

**When** `analyze_bridge_shadow_precision_by_date(db, trading_date)`가 호출되면, the
system **shall** `pool_a`/`pool_c` 각각에 대해 `{total: int, surge_count: int,
precision: float | None}`을 반환해야 하며, `pool_a`/`pool_c`를 **절대 blended
합산하지 않고 분리**해서 반환해야 한다(§Decisions D2).

필수 조건:

- `SurgeActualOutcome.trading_date == trading_date AND was_surge.is_(True)`와
  shadow 저장 코드의 교집합 비율로 계산한다.
- `total == 0`이면 `precision`은 `None`이다(0으로 나누기 예외 금지 — SPEC-AI-089/104의
  `*_gap_ratio`/`analyze_pool_precision_by_date()` None-guard 관례 계승).
- `backend/app/services/surge_universe_gap_service.py`에 `analyze_no_signal_pool_attribution()`의
  자매 함수로 추가한다.

### REQ-AI105-004: bridge 활성화 전제조건 정정 (문서 전용)

The plan.md와 CHANGELOG.md 문서 **shall** 다음 정정 내용을 기록해야 한다: bridge
활성화 준비도는 `max_scan_universe` 상한 크기(SPEC-AI-096 D1, 이미 배포됨)에만
의존하며, Pool D 관측 인프라 준비도(SPEC-AI-096 D4가 명시한 선행 조건)와는 무관하다
— `generate_scan_universe_bridge_candidates()`의 `_target_pools`가 `"pool_d"`를
포함한 적이 없기 때문이다(코드 직접 확인: `pool_a`, `pool_c`, 조건부 `pool_b`뿐).

필수 조건:

- 코드 변경을 수반하지 않는다 — 순수 문서 정정이다.
- SPEC-AI-096 spec.md 본문은 개정하지 않는다(§Decisions D3).

### REQ-AI105-005: 리포트에 pool별 shadow 정밀도 병기

**When** shadow 계측이 여러 거래일에 걸쳐 축적된 뒤 측정 리포트 스크립트가 실행되면,
the report script **shall** `pool_a`/`pool_c` shadow 정밀도를 분리된 행/열로 표시해야
하며(blended 합산 표시 금지, §Decisions D2), 기존 pool 커버리지 리포트(SPEC-AI-089/104
`measure_universe_detection_gap_report.py`)와 나란히 배치해야 한다.

### REQ-AI105-006: 무회귀 보장

**While** 이 SPEC이 배포되는 동안, the system **shall not** `qualified`/`merged`/
`FundSignal` 산출물, 실제 `scan_universe_bridge_candidates_enabled` 값(`false` 유지),
`_BRIDGE_MIN_SCORE`, pool_a/pool_c/pool_b 점수 산식, quota 배분(SPEC-AI-065/074/076/
078/086), 8개 탐지기 판정 로직, `compute_ensemble_score()`, 매매 실행 경로를 변경해서는
안 된다.

필수 조건:

- `scan_universe_bridge_shadow_enabled`의 값(`false`/`true` 무관)과 독립적으로 위
  불변식이 성립해야 한다.
- `git diff --name-only`에 `surge_trading_service.py`, 8개 탐지기 스코어링 함수,
  `compute_ensemble_score()`가 포함되지 않아야 한다.

### REQ-AI105-007: 활성화 게이트 절차 문서화(recall/precision 비교 + 좁은 범위 우선 활성화)

The plan.md §C 활성화 게이트 절차 **shall** 다음을 정의해야 한다: (a) 최소 10거래일
shadow 관측 기간(SPEC-AI-096 D4가 이미 제안한 값을 재사용 — 재도출하지 않음), (b)
pool별 shadow 정밀도를 이미 영속화된 시스템 전체 일일 정밀도(`SurgePredictionEvaluation.precision`)와
비교하는 기준선(§Decisions D5), (c) **기존 `scan_universe_bridge_pool_limits`의
0-값 메커니즘**(예: `{"pool_a": 0, "pool_c": 10}`)을 사용한 pool 단위 좁은 범위 우선
활성화 절차 — 신규 "대상 pool 부분집합" 플래그를 추가하지 않고 기존 config만으로
어느 pool을 먼저 실활성화할지 선택 가능함을 명시, (d) 관측 중 precision이 기준선 대비
유의하게 낮거나 `generate_scan_universe_bridge_candidates()` 예외율이 상승하면 즉시
`false`로 되돌리는 롤백 절차(SPEC-AI-096 D4와 동일).

필수 조건:

- 이 REQ의 산출물은 문서(plan.md §C + CHANGELOG.md)이며, 실제 활성화 실행은 이
  SPEC의 배포 범위가 아니다.
- pool_a와 pool_c는 절차상 독립적으로 판정한다 — 어느 한쪽만 기준을 충족해도 그
  pool만 좁은 범위로 먼저 활성화하는 경로를 문서에 명시한다(§Decisions D2).

## Open Questions

1. 관측 기간(10거래일)과 "유의하게 낮다"의 정량적 임계값(예: 기준선 대비 -N%p)의
   최종 확정 — 이 SPEC은 절차만 정의하고, 정확한 숫자는 shadow 관측 데이터 확보 후
   별도 결정한다(SPEC-AI-096 D4, SPEC-AI-104 §Open Questions와 동일한 유보 방식).
2. 원 위임 프롬프트가 인용한 "2026-07-28 Pool C 3종목 미승격" 주장의 DB 재검증 — 이
   세션은 라이브 DB 조회 권한이 없어 수행하지 못했다(§Context "[미검증 인용]" 참고).
   run-phase 착수 전 재확인을 권장하되, 이 SPEC의 shadow 계측 설계 자체는 그 재검증
   결과에 의존하지 않는다(정밀도 측정 인프라는 그 주장의 진위와 무관하게 유효하다).
3. pool_b shadow 계측 확장 여부 — SPEC-AI-102가 `completed`로 전환된 이후 판단 대상
   후속 SPEC 후보로 남긴다(§Decisions D4).
