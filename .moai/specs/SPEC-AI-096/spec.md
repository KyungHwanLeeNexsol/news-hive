---
id: SPEC-AI-096
title: "급등예측 스캔 유니버스 파이프라인 — 캡·절단·단계적 활성화 정책"
version: "0.1.0"
status: completed
created: 2026-08-03
updated: 2026-08-03
author: Nexsol
priority: High
phase: "backend surge-detection v0.1.0"
module: "backend/app/services"
lifecycle: spec-anchored
tags: "surge-detection, scan-universe, pool-d, bridge-candidates, price-fetch-truncation, observability, backend"
tier: M
related_specs: [SPEC-AI-038, SPEC-AI-063, SPEC-AI-065, SPEC-AI-068, SPEC-AI-076, SPEC-AI-086, SPEC-AI-089, SPEC-AI-092, SPEC-AI-094]
---

# SPEC-AI-096: 급등예측 스캔 유니버스 파이프라인 — 캡·절단·단계적 활성화 정책

## HISTORY

- 2026-08-03 v0.1.0 (draft): GPT 외부 구조진단 + 내부 코드검증이 공통으로 지목한 4개 항목
  (스캔 유니버스 상한, Pool D, bridge 후보, price-fetch 사전절단)을 하나의 SPEC으로
  묶는다. 조사 과정에서 위임 프롬프트에 없던 신규 관측 갭(§Context "Pool D count 미영속화")을
  발견해 REQ에 반영했고, "8개 종목이 150-cap에 절단됐다"(finding 7)는 주장이 실제로는
  `max_scan_universe` 상향만으로는 해소되지 않고 bridge 활성화와 결합되어야 함을 코드
  추적으로 확인해 §Decisions에 명시했다(research.md §C.1 참고).

## 선행 SPEC

- **SPEC-AI-065** (완료): `build_scan_universe()`, Pool A/B/C, `max_scan_universe` 상한의
  최초 소유 SPEC. 본 SPEC은 이 구조를 변경하지 않고 값·정책만 조정한다.
- **SPEC-AI-076** (완료): quota 배분(`pool_b_min_slots`/`pool_c_min_slots`), existing
  "우선순위 최하" 원칙. 무변경 승계.
- **SPEC-AI-086** (완료): Pool D 도입(기본 비활성), `max_scan_universe` 경계 clamp
  `[50, 600]`(`_clamp_scan_universe_cap`), 동적 시간대별 상한(선택 기능). 본 SPEC의
  캡 상향은 이 clamp를 그대로 사용하며 절대 초과하지 않는다.
- **SPEC-AI-089** (완료): `measure_universe_detection_gap()` — 순수 읽기 계측, 기본 비활성.
- **SPEC-AI-092** (완료): `generate_scan_universe_bridge_candidates()`, bridge 후보
  attribution(`active_detectors=["scan_universe_bridge", pool]`). 본 SPEC은 이 로직을
  재사용하며 코드를 변경하지 않는다 — 활성화 기준만 정의한다.
- **SPEC-AI-063** (완료): `volume_breakout_score` 단독 앙상블 우회(bypass) 패턴. REQ-AI096-005가
  이 패턴("이미 계산된 신호로 절단을 면제")을 재사용한다.
- **SPEC-AI-038**: `_MAX_PRICE_FETCH_CANDIDATES` 30→50 조정 이력. 이 상수를 올리는 것이
  과거 실제 300초 타임아웃 사고와 직결됐던 안전 제약의 근거다.
- **SPEC-AI-094** (완료): `existing_codes` 병합 필터 교정(`scan_universe_include_existing`
  플래그, 기본 비활성). 본 SPEC과 다른 항목이며 명시적으로 범위에서 제외한다(§Out of Scope).

## Context / Problem

### 급등예측 recall 저하의 구조적 원인 — 탐지망보다 하류에 있는 스캔 유니버스

외부(GPT) 분석과 내부 코드검증이 공통으로 확인한 사실: 스캔 유니버스 파이프라인이
**탐지기 출력의 하류**에 있어(순수 관측용), 탐지기가 애초에 놓친 종목을 스캔 유니버스가
사후에 구제하지 못한다. 또한 몇몇 안전망 기능이 코드에는 존재하지만 기본값이 비활성이다.

### 검증된 사실 (코드 직접 확인, research.md §B 상세)

1. `surge_detection.yaml:234`, `surge_settings.py:532` — `max_scan_universe: 150`(기본값,
   변경 없음).
2. `surge_detector.py:4798` `if config.pool_d_min_slots > 0:` — Pool D(뉴스 언급 기반)는
   구현되어 있으나 `pool_d_min_slots` 기본값 0(`surge_settings.py:557`)이라 소싱 쿼리
   자체가 실행되지 않는다.
3. `surge_detector.py:1937` `existing_codes = set(merged.keys())` → `:1941`
   `build_scan_universe(..., existing_codes=existing_codes)` — 개별 탐지기(theme_cluster,
   volume_news_combo, disclosure_pattern, news_delayed, volume_breakout,
   momentum_continuation, immediate_disclosure) 결과가 먼저 `merged`에 병합된 **후에**
   스캔 유니버스가 빌드된다.
4. `surge_detector.py:4977`(`generate_scan_universe_bridge_candidates`, 호출 `:2021`)는
   유니버스 소속이지만 `merged`에 없는 후보를 `qualified`로 승격할 수 있으나,
   `scan_universe_bridge_candidates_enabled` 기본값 `False`(`surge_settings.py:589`)라
   기본 설정에서는 유니버스 소속만으로 후보가 되지 않는다.
5. `surge_detector.py:1992-2015`(`measure_universe_detection_gap`)는 평가/로깅 전용
   계측으로 `universe_gap_measurement_enabled` 기본 `False`(`:581`).
6. `_MAX_PRICE_FETCH_CANDIDATES = 50`(`surge_detector.py:2118`) — `merged`가 50개를
   초과하면 `price_5d_trend`(HTTP 조회) 전에 앙상블 가중합 사전점수로 상위 50개만 남기고
   나머지는 폐기한다(`:2119-2138`). 2026-06-30 SPEC-AI-038이 30→50으로 확대했다.
7. **[미검증 인용]** 위임 프롬프트에 따르면 2026-07-28 실제 급등 23개 중 scannable은 4개뿐이었고
   (11개는 어떤 후보 소스에도 진입하지 못함, 8개는 150-cap에 절단됨) — 이 세션은 이 수치를
   DB로 재검증하지 않았다(research.md §B row 7, ⚠️ 미검증 표시).

### 신규 발견 — Pool D는 계산은 되지만 이력에 저장되지 않는다 (관측 갭)

`build_scan_universe()`가 `pool_counts["pool_d"]`를 계산함에도(`:4861`), 호출부
`persist_pool_counts()`(`:1961-1970`)는 `pool_a`/`pool_b`/`pool_c`/`scan_universe_size`
4키만 전달하고 **`pool_d`를 누락**한다. `SurgeUniversePoolHistory` 모델에는 애초에
`pool_d_count` 컬럼이 없다(`backend/app/models/surge_universe_pool_history.py:15-47`).
결과적으로 Pool D는 매 실행 로그 라인(`:4824`)에만 찍히고 여러 거래일에 걸친 추세를
볼 영속 데이터가 없다 — "활성화 전 관측"이 요구사항인데 관측 인프라 자체가 미완성이다.

### 신규 발견 — `max_scan_universe` 상향만으로는 finding 7의 "8개 절단"을 해소하지 못한다

`build_scan_universe()`가 반환하는 `_universe_codes`(및 그 절단 결과)의 소비처는
entry_pool 태깅(`:1944-1948`, `merged` 멤버십은 변경 안 함), `persist_pool_counts`/
`persist_universe_members`(순수 관측), `measure_universe_detection_gap`(기본 비활성),
`generate_scan_universe_bridge_candidates`(기본 비활성 — 즉시 빈 리스트) 4곳뿐이다.
즉 **bridge 후보가 비활성인 한, `max_scan_universe`를 아무리 올려도 실제 매매 후보
(`qualified`)에는 영향이 없다** — `scannable_recall`/`coverage`/`surge_type`(SPEC-AI-068)
평가지표의 분모만 개선된다. 캡 상향과 bridge 활성화는 함께 다뤄야 하는 하나의 인과 사슬이다.

### 신규 발견 — `entry_pool` 태깅은 이미 절단보다 먼저 실행된다

`SurgeCandidate.entry_pool`(기본값 `"existing"`, `:95`)은 `:1944-1948`에서 Pool A/B/C/D
소속 여부로 갱신되며, 이는 `_MAX_PRICE_FETCH_CANDIDATES` 절단 블록(`:2118-2138`)보다
**먼저** 실행된다. 즉 절단 시점에 이미 각 candidate가 "외부 독립 공급 신호"를 가졌는지
별도 조회 없이 판별할 수 있다.

## Goals

1. `max_scan_universe` 상한을 SPEC-AI-086 clamp(`[50, 600]`) 내에서 보수적으로 상향하고,
   그 상향이 평가지표(scannable_recall/coverage) 분모에 미치는 영향을 명시적으로 인지시킨다.
2. Pool D(`pool_d_min_slots`)의 실제 일자별 공급량을 여러 거래일에 걸쳐 관측할 수 있도록
   영속화 인프라를 완성하고, 안전한 canary→기본활성화 전환 기준을 정의한다.
3. bridge 후보(`scan_universe_bridge_candidates_enabled`)의 canary→기본활성화 전환 기준과
   기존 attribution(`surge_basis`) 재사용 관측 절차를 정의한다.
4. `_MAX_PRICE_FETCH_CANDIDATES` 사전절단 정책을, 외부 독립 공급 신호(Pool A/B/C/D 소속)를
   가진 후보는 면제하는 방향으로 재설계한다 — 단, HTTP 호출량이 늘어나는 숫자 자체의 재상향은
   과거 타임아웃 사고 이력(SPEC-AI-038)을 근거로 이 SPEC에서 다루지 않는다.
5. 위 4개 항목 모두 기존 회귀(탐지/매매 로직, `existing_codes` 처리, quota 배분)에 영향을
   주지 않아야 한다.

## Non-Goals

### Out of Scope — 배치 가격 데이터 HTTP 인프라

- 별도 SPEC("B: 배치 가격 데이터 조회 인프라")이 소유한다. `_MAX_PRICE_FETCH_CANDIDATES`의
  숫자 자체를 늘리는 것(HTTP 호출량 증가)은 그 SPEC의 배치/캐싱 인프라가 갖춰진 후에만
  안전하다 — 본 SPEC은 절단 **정책**(무엇을 면제할지)만 다룬다.

### Out of Scope — 뉴스-종목 매핑 고도화

- 별도 SPEC("C: 뉴스-종목 매핑 고도화")이 소유한다. Pool D가 사용하는
  `NewsStockRelation.relevance == "direct"` 매칭 정확도 개선은 본 SPEC의 범위가 아니다 —
  본 SPEC은 현재 매칭 결과를 있는 그대로 관측/활성화 대상으로 다룬다.

### Out of Scope — ML 피처 스냅샷 저장

- 별도 SPEC("D")이 소유한다. 본 SPEC은 어떤 ML 피처 스냅샷 테이블도 신설하지 않는다.

### Out of Scope — Horizon 분리 예측 아키텍처

- 별도 SPEC("E: Horizon 분리 예측 아키텍처")이 소유한다. same_day/next_day horizon 분리,
  앙상블 스코어링 구조, `combo_chase_guard` 변경은 이 SPEC 이후 별도로 계획한다(구조적으로
  선행 필요 — 이 SPEC의 완료를 기다린다).

### Out of Scope — `existing_codes` 병합 필터

- SPEC-AI-094(완료)가 이미 소유·해결했다. 재론하지 않는다.

### Out of Scope — ML 모델 학습

- 사용자 결정에 따라 이 Epic 전체에서 명시적으로 범위 밖이다.

### Out of Scope — Pool D / bridge 후보의 실제 프로덕션 활성화(flag flip)

- 본 SPEC은 **활성화 기준과 관측 인프라**까지만 다룬다. `pool_d_min_slots`를 0에서 양수로,
  `scan_universe_bridge_candidates_enabled`를 `False`에서 `True`로 실제로 뒤집는 것은
  본 SPEC의 배포 산출물이 관측 데이터를 축적한 뒤 별도 운영 판단(사용자 확인)으로
  결정한다(§Decisions D3/D4, Open Questions 참고) — SPEC-AI-084/085/086/092가 이미
  확립한 "배선 → 관측 → 활성화는 별도 결정" 관례를 그대로 따른다.

## Decisions

### D1 — `max_scan_universe` 기본값을 150→250으로 보수적 상향한다 (clamp 내)

기존 clamp(`_MAX_SCAN_UNIVERSE_FLOOR=50`, `_MAX_SCAN_UNIVERSE_CEILING=600`, SPEC-AI-086)를
그대로 사용하며 250은 그 범위 안이다. 250을 선택한 이유: (a) finding 7이 인용하는
2026-07-28 사례에서 8개 종목이 150-cap에 걸렸다는 사실은 그날 원시 후보 합계가 150을
분명히 초과했음을 시사하지만, 정확한 초과분을 확인할 영속 이력이 없다(§Context "신규
발견 — Pool D 미영속화"와 동일한 근본 문제 — Pool A/B/C도 시계열로 축적된 것은
`SurgeUniverseMember`/`SurgeUniversePoolHistory`뿐이며 raw 초과분 자체는 로그에만
남는다). (b) 극단적으로 크게(예: 600 상한 근접) 올리면 `persist_universe_members`가
매일 기록하는 행 수, `measure_universe_detection_gap`/bridge 활성화 시 조회 비용이
비례 증가한다 — 아직 데이터가 없는 상태에서 상한 근접값을 택하는 것은 과도한 선제
비용이다.

기각한 대안: (1) 150 유지 — finding 7이 사실이라면 recall 개선 효과가 전혀 없다.
(2) 즉시 600(상한)으로 설정 — 검증되지 않은 비용 증가를 감수할 근거가 없다.

**[HARD] 이 변경은 플래그가 아니다** — `max_scan_universe`는 SPEC-AI-065 이래 항상
활성인 단일 스칼라이며, Pool D/bridge처럼 "신규 코드 경로 On/Off"가 아니다. 그러나
research.md §C.1이 보인 대로 이 값의 변경은 **`scannable_recall`/`coverage`/`surge_type`
평가지표의 분모를 즉시 이동시킨다**(SPEC-AI-094가 `existing_codes`에 대해 겪은 것과
동일한 종류의 지표 불연속). 현재 프로젝트가 recall 0% 원인을 추적 중이므로, 이 변경은
sync-phase CHANGELOG에 "평가지표 분모 이동" 경고를 명시적으로 남겨야 한다
(REQ-AI096-006 필수 조건).

### D2 — `_MAX_PRICE_FETCH_CANDIDATES`(50)의 숫자는 그대로 두고, 절단을 pool 소속 후보에 면제한다

`entry_pool`이 `pool_a`/`pool_b`/`pool_c`/`pool_d` 중 하나인 `merged` candidate는
사전점수(`_pre_score`) 절단 대상에서 제외한다 — 이는 SPEC-AI-063이 `volume_breakout_score`
단독으로 앙상블 우회를 허용한 것과 동일한 논리다: 이미 외부 독립 신호(DART 공시/거래량
폭증/실제 등락률/뉴스 언급)를 가진 후보를 순수 내부 앙상블 사전점수만으로 버리는 것은
근거가 약하다. `entry_pool == "existing"`(순수 탐지기 전용, 외부 풀 소속 없음)인
candidate만 기존처럼 상위 50개로 절단한다.

기각한 대안: 숫자 자체를 50→80 등으로 재상향 — SPEC-AI-038의 코드 주석이 직접 증언하듯
이 숫자를 올리는 것은 순수 설정값 변경이 아니라 "HTTP 호출량 × 타임아웃 여유"의 함수다.
배치 HTTP 인프라(SPEC B) 없이 숫자를 올리면 2026-06-30 이전에 실제로 겪은 300초
타임아웃을 재현할 위험이 있다. **면제 정책은 신규 HTTP 호출을 추가하지 않는다** —
면제된 후보도 여전히 기존 `price_5d_trend` 조회 대상이 되므로, 면제되는 후보 수만큼
호출량이 늘어날 수 있다는 점은 인지하되(§리스크), 이는 "탐지기가 실제로 잡은 후보인데
버려지던" 손실을 없애는 것이지 무제한 확장이 아니다 — pool 소속 후보 수는
`max_scan_universe`(250)와 quota(`pool_b/c/d_min_slots`)로 이미 유계다.

### D3 — Pool D는 이 SPEC에서 활성화하지 않는다; 관측 인프라 완성 + 활성화 기준만 정의한다

`pool_d_min_slots` 기본값은 0으로 유지한다. 이 SPEC은 (a) `pool_d_count`를
`SurgeUniversePoolHistory`에 영속화하는 마이그레이션/코드를 추가하고(REQ-AI096-002),
(b) 활성화 기준을 다음과 같이 정의한다: `pool_d_min_slots`를 0보다 큰 값(제안:
`10`, 최종 스캔 유니버스 250 대비 4% — 관측 목적의 최소 침습)으로 canary 전환하기 전에
**최소 5거래일** 동안 `pool_d_count`가 0이 아닌 값으로 안정적으로 관측되어야 한다(DART/
거래량/등락률 어디에도 걸리지 않는 "absent형" 급등을 실제로 탐지 가능한 뉴스 매핑
데이터가 존재함을 확인). 5거래일 관측 후에도 매매 대상 편입은 이 SPEC의 범위가 아니다
(Pool D는 여전히 "측정 유니버스"일 뿐 — 실제 후보 승격은 bridge를 통해서만 가능하다,
research.md §C.1).

거래일 수(5일)는 이 프로젝트가 다른 관측 기간을 명시한 선례가 없어 임의 제안값이다 —
Open Questions에 최종 확정 필요 항목으로 남긴다.

### D4 — bridge 후보는 이 SPEC에서 활성화하지 않는다; 기존 attribution 재사용 관측 절차만 정의한다

`scan_universe_bridge_candidates_enabled` 기본값은 `False`로 유지한다. 활성화 절차:
(1) D1(캡 250)과 D3(Pool D 관측 인프라)가 먼저 배포되어야 한다 — bridge는 `_universe_codes`
(pool_a/pool_c 한정)에서 소싱하므로 캡이 작으면 후보 풀 자체가 작다. (2) 활성화 후
**최소 10거래일** 동안 기존 `_extract_combo_key()`/`surge_basis` 분석 도구로
`"scan_universe_bridge"`가 포함된 조합의 승률/수익률을 앙상블 평균과 비교 관측한다
(research.md §C.4 — 신규 계측 코드 불필요, 기존 도구 재사용). (3) 관측 기간 동안
precision이 앙상블 평균보다 유의하게 낮거나 `generate_scan_universe_bridge_candidates()`
예외율이 상승하면 flag를 즉시 `False`로 되돌린다(단일 값 변경, 데이터 손실 없음 —
`bridge_score`/`bypass_composite_score`는 이미 nullable-safe 런타임 필드).

10거래일 관측 기간 역시 Pool D의 5일과 마찬가지로 제안값이며 최종 확정은 운영 판단이다.

### D5 — Pool D 이력 확장은 기존 컬럼을 건드리지 않고 신규 nullable 컬럼만 추가한다

`SurgeUniversePoolHistory`에 `pool_d_count: Mapped[int]`를 추가한다(default=0,
nullable=False — 기존 3개 pool count 컬럼과 동일한 타입/제약으로 통일; SPEC-AI-068이
확립한 "관측용 컬럼은 nullable" 관례와 다르게, 이 값은 "관측되지 않음(NULL)"과
"0개(정상 관측, Pool D 소싱 자체가 비활성)"을 구분할 필요가 없다 — `pool_d_min_slots=0`
이면 항상 정확히 0이므로 `nullable=False, default=0`이 `pool_a/b/c_count`와 일관적이다).
기존 3개 컬럼 타입/제약/의미는 무변경.

## Requirements

### REQ-AI096-001: `max_scan_universe` 기본값 상향

Where `max_scan_universe`가 명시적으로 재정의되지 않으면, the system **shall**
`surge_settings.py`의 `SurgeDetectionConfig.max_scan_universe` 기본값과
`surge_detection.yaml`의 `max_scan_universe` 값을 `150`에서 `250`으로 변경해야 한다.

필수 조건:

- `_clamp_scan_universe_cap()`(`[50, 600]`, SPEC-AI-086) 로직 자체는 무수정이다 — 250은
  이미 그 범위 안이므로 clamp는 no-op으로 남는다.
- `pool_b_min_slots`(20)/`pool_c_min_slots`(30)/`pool_d_min_slots`(0, 미활성 유지) quota
  값 자체는 변경하지 않는다(SPEC-AI-076/086 소유, §Out of Scope).
- 배포 CHANGELOG(REQ-AI096-006)에 "`scannable_recall`/`coverage`/`surge_type` 평가지표
  분모가 이동한다"는 경고 문구를 반드시 포함해야 한다.

### REQ-AI096-002: Pool D 관측 영속화 확장

When `build_scan_universe()`가 `pool_counts`를 계산하고 이를 호출부가 영속화하면,
the system **shall** `pool_d` 수치를 `SurgeUniversePoolHistory.pool_d_count`(신규
컬럼)에 함께 저장해야 한다.

필수 조건:

- 신규 alembic 리비전 1건(`071_surge_universe_pool_history_pool_d.py` 제안,
  down_revision = 현재 head `"070_surge_pred_eval_high_based"`)으로
  `pool_d_count: Mapped[int]`(`Integer, nullable=False, default=0`)를 추가한다.
- `persist_pool_counts()`(`surge_universe_pool_service.py`) 호출 시그니처의 `pool_counts`
  dict 인자에 `"pool_d"` 키를 추가로 읽어 저장한다 — 키가 없으면 기존과 동일하게 `0`으로
  처리한다(하위 호환).
- 호출부(`surge_detector.py:1961-1970`)의 `persist_pool_counts()` 호출 딕셔너리에
  `"pool_d": _pool_counts.get("pool_d", 0)` 항목을 추가한다.
- `get_pool_counts_for_date()`(`surge_universe_pool_service.py:77-98`) 반환 dict에도
  대칭적으로 `"pool_d"` 키를 추가한다.
- `evaluate_surge_predictions()`(`surge_evaluation_service.py`)가 `pool_counts` 인자를
  소비하는 기존 로직은 **무수정**이다 — 이 REQ는 저장/조회 계층만 확장하며, 신규 pool_d
  값을 평가 지표 계산에 사용하도록 만드는 것은 이 SPEC의 범위가 아니다.
- 백필 없음 — 기존 행은 `pool_d_count=0`으로 남는다(SPEC-AI-093/095 전진 적용 원칙 승계).

### REQ-AI096-003: Pool D 단계적 활성화 기준 문서화

While `pool_d_min_slots`가 `0`(기본값)으로 유지되는 동안, the system **shall** 배포된
관측 인프라(REQ-AI096-002)만으로 canary 활성화 판단이 가능해야 한다 — 즉 코드 변경
없이 `pool_d_min_slots`를 양수로 바꾸는 것만으로 소싱 쿼리가 즉시 실행 가능한 상태여야
한다(이미 `if config.pool_d_min_slots > 0:` 게이트로 구조적으로 보장됨, 무수정 확인
필요).

필수 조건:

- 활성화 기준(§Decisions D3: canary 값 10, 최소 5거래일 `pool_d_count > 0` 관측)은
  코드가 아닌 plan.md/CHANGELOG 문서에 기록한다 — 이 REQ는 "기준이 문서화되어 있고
  기존 게이트가 그 기준을 코드 변경 없이 만족시킬 수 있음"을 검증 대상으로 한다.
- 이 SPEC의 배포로 `pool_d_min_slots` 값 자체는 변경하지 않는다(0 유지).

### REQ-AI096-004: bridge 후보 단계적 활성화 기준 문서화

While `scan_universe_bridge_candidates_enabled`가 `False`(기본값)로 유지되는 동안,
the system **shall** 기존 `_extract_combo_key()`/`surge_basis` attribution 파이프라인이
`"scan_universe_bridge"` 접두 조합을 코드 변경 없이 식별 가능한 상태를 유지해야 한다
(`generate_scan_universe_bridge_candidates()`의 `active_detectors=["scan_universe_bridge",
pool]` 태깅, `:5132`, 무수정 확인).

필수 조건:

- 활성화 기준(§Decisions D4: D1+D3 선행, 최소 10거래일 관측, precision 비교 기준)은
  plan.md/CHANGELOG 문서에 기록한다 — 신규 계측 코드를 추가하지 않는다.
- 이 SPEC의 배포로 `scan_universe_bridge_candidates_enabled` 값 자체는 변경하지 않는다
  (False 유지).

### REQ-AI096-005: price-fetch 사전절단 pool 소속 후보 면제

When `len(merged)`가 `_MAX_PRICE_FETCH_CANDIDATES`(50, 무변경)를 초과하면, the system
**shall** `candidate.entry_pool`이 `"pool_a"`/`"pool_b"`/`"pool_c"`/`"pool_d"` 중 하나인
candidate를 사전점수(`_pre_score`) 절단 대상에서 제외하고, `entry_pool == "existing"`인
candidate만 상위 `_MAX_PRICE_FETCH_CANDIDATES`개로 절단해야 한다.

필수 조건:

- `_MAX_PRICE_FETCH_CANDIDATES`의 숫자(50)와 `_pre_score()` 가중합 산출식 자체는
  무변경이다 — 절단 **대상 집합**만 재정의한다.
- 면제된 pool 소속 candidate 수가 원래 있었을 절단 폭을 초과해 `merged` 전체 크기가
  과도하게 커지는 경우(예: pool 소속만으로 이미 200개 초과) 로그 경고를 남겨야 한다
  (신규 HTTP 호출량 급증 조기 감지, §리스크).
- entry_pool 태깅(`:1944-1948`)이 이 절단 블록보다 먼저 실행되는 기존 순서는 무변경이다
  (이미 그러함 — 코드 재배치 없음).

### REQ-AI096-006: 배포 관측성 및 무회귀 보장

While 본 SPEC이 적용되는 동안, the system **shall not** Pool D 소싱 로직, bridge 후보
생성 로직, `existing_codes` 병합 필터(SPEC-AI-094), quota 배분(`pool_b/c_min_slots`),
7개 핵심 탐지기의 판정 로직을 변경해서는 안 된다.

필수 조건:

- `pool_d_min_slots=0`, `scan_universe_bridge_candidates_enabled=False`인 현재 프로덕션
  설정 조합에서, REQ-AI096-002(Pool D 영속화 확장)와 REQ-AI096-005(절단 면제)를 제외한
  나머지 관측 가능한 산출물(`qualified` 최종 후보 집합)은 REQ-AI096-001(캡 상향)이
  적용되기 전과 **정확히 동일**해야 한다 — 캡 상향 자체는 `scannable_recall`/`coverage`
  분모를 이동시키므로(D1) 이 무회귀 범위에서 명시적으로 제외한다.
- sync-phase CHANGELOG 항목에 다음 3가지를 반드시 명시한다: (a) `max_scan_universe`
  150→250 변경과 그로 인한 평가지표 분모 이동 경고, (b) Pool D 관측 인프라 추가(활성화
  아님), (c) price-fetch 절단 면제 정책 변경.

## Open Questions

정책 판단(캡 250 선택 근거, 절단 면제 vs 숫자 재상향, Pool D/bridge 이 SPEC에서 미활성화)은
§Decisions D1~D5에서 이미 확정했다. 아래는 구현·운영 시 확정할 항목만 남긴다.

1. `max_scan_universe`의 최종 목표값 — 250은 보수적 1차 상향 제안이다. REQ-AI096-002
   배포로 `pool_d_count` 포함 실측 이력이 축적된 뒤, 관측된 raw 합계(Pool A+B+C+D) 분포를
   근거로 재조정 여부를 판단한다.
2. Pool D canary 값(제안 10)과 관측 기간(제안 5거래일)의 최종 확정.
3. bridge 후보 활성화 관측 기간(제안 10거래일)과 "precision이 유의하게 낮다"의 정량적
   임계값(예: 앙상블 평균 대비 -N%p) — 이 SPEC은 절차만 정의하고 정확한 임계값은
   실측 데이터 확보 후 별도 결정한다.
4. finding 7(2026-07-28, 23개 중 4개만 scannable)의 DB 재검증 — 이 세션에서 수행하지
   않았다(research.md §B row 7). run-phase 착수 전 재확인을 권장하되, 이 SPEC의 정책
   결정 자체는 그 재검증 결과에 의존하지 않는다(캡 상향·면제 정책 모두 finding 7이
   부분적으로만 정확하더라도 여전히 타당한 독립적 개선이다).
