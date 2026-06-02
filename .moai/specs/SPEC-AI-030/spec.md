---
id: SPEC-AI-030
version: 0.1.0
status: implemented
created: 2026-06-02
updated: 2026-06-02
author: MoAI
priority: High
issue_number: null
---

# SPEC-AI-030: 거래량콤보 탐지기 추격매수 방지 (Volume-News Combo Chase-Buy Prevention)

## HISTORY

- 2026-06-02 (v0.1.0): 최초 작성. 2026-06-02 운영 분석에서 `volume_news_combo`
  탐지기가 생성한 6건 신호가 **100% 실패**(평균 -7.7%, 급등 0건, 급락 5건)한 사실이
  확인되었다(라온로보틱스 -8.9%, 나노팀 -10%, 삼화전자 -13.8%, 유니셈 -7.8%,
  에이팩트 -7.4%). 같은 날 유일한 성공(쎄노텍 +10.6%)은 `immediate_disclosure` +
  `theme_cluster` 조합이었고 `volume_news_combo`는 미관여였다. 근본 원인은 거래량
  z-score가 임계값을 넘을 때쯤이면 **거래량 급증이 이미 발생**해 스마트머니가 이미
  매수를 마친 상태이며, 우리는 천장에서 추격매수(chase-buy)하고 있다는 구조적 결함이다.
  본 SPEC은 신호 생성 시점(`detect_volume_surge_news_combo`)에 (1) 당일 과열 필터,
  (2) 거래량 급증 신선도 검증, (3) 분산(distribution) 패턴 거부, (4) 앙상블 단독
  교차 차단을 추가하여 추격매수를 차단한다.

---

## 선행 SPEC (전제 조건 / Assumptions)

본 SPEC은 다음 기존 SPEC이 구축한 인프라 위에 동작하며, 새로운 탐지기나 매매 엔진을
만들지 않고 기존 자산을 재사용한다.

- **SPEC-AI-012 (급등 징후 탐지 시스템)**: `surge_detector.py`의 4개 탐지기
  (theme_cluster, volume_news_combo, immediate_disclosure, disclosure_pattern),
  앙상블 스코어링, `SurgeCandidate` 데이터클래스
  (`theme_cluster_score`/`combo_score`/`immediate_disclosure_score`/`active_detectors`),
  `surge_settings.py`의 `SurgeDetectionConfig`/`VolumeNewsComboConfig`/`EnsembleConfig`/
  `get_surge_config()` 설정 인프라를 도입했다. `volume_news_combo`는 **탐지기 2**이다.
  - **전제**: `detect_volume_surge_news_combo(db, config, market_regime)`은
    `surge_detector.py` 라인 418~553에 존재하며, 거래량 z-score
    (`(current_vol - mean_vol) / std_vol`)가 `cfg.volume_zscore_threshold`를 초과하고
    `news_window_hours` 내 긍정 뉴스가 있는 종목을 후보로 만든다. 점수는
    `combo_score = sigmoid((z_score - threshold)/1.0) * sentiment_score`로 산출한다.
  - **전제**: 이 탐지기는 이미 후보별로 `_fetch_price_change_sync(stock_code)`를
    호출하여(라인 533~538) 당일 가격 데이터를 piggy-back 수집한다(SPEC-AI-020 PER/PBR
    수집 경로). 본 SPEC은 이 **이미 존재하는 호출 결과를 재사용**하여 신규 API 호출을
    추가하지 않는다.
  - **[HARD] 사실 확인 — 가용한 당일 등락 지표는 `change_rate`(전일대비)뿐**:
    `_fetch_price_change_sync`가 반환하는 dict는 `{"current_price": int,
    "change_rate": float}` 두 키만 가진다(`naver_finance.fetch_current_price_with_change_sync`,
    라인 830~833). **`open_price`(시가)는 이 동기 경로에서 제공되지 않는다.** 따라서
    "시가 대비 +5%" 또는 "current_price < open_price" 형태의 시가 기준 판정은 본
    탐지기 경로에서 직접 구현할 수 없다. 본 SPEC의 REQ는 **실제 가용한 `change_rate`
    (전일 종가 대비 % 등락)** 기준으로 작성되며, 시가 기준 판정은 Non-Goals로 이연한다.
- **SPEC-AI-013 (급등예측 페이퍼 트레이딩)**: `surge_trading_service.py`의
  `execute_buy_orders()` 매수 실행 로직을 도입했다.
  - **[HARD] 사실 확인 — 체결 시점 필터는 이미 존재하나 "너무 늦다"**:
    `execute_buy_orders()`는 체결 시점에 `change_rate < INTRADAY_CRASH_LIMIT(-3.0%)`
    급락 제외(라인 784), `change_rate > INTRADAY_OVERHEAT_LIMIT(+15.0%)` 과열 제외
    (라인 794), 시그널 기준가 대비 `ENTRY_GAPUP_LIMIT(0.05)` 갭업 제외(라인 807)를
    수행한다. 그러나 이 필터들은 **신호가 이미 생성·기록된 후 체결 시점**에만 동작하므로,
    신호 자체가 추격매수성으로 만들어지는 것을 막지 못한다. 본 SPEC은 동등한 게이트를
    **신호 생성 시점**(`detect_volume_surge_news_combo`)으로 전진 배치한다.
  - **전제**: 신호 가격 대비 체결가가 크게 벌어진 사례(삼화전자 3,905→2,810 -28%,
    나노팀 14,650→11,370 -22%, 라온로보틱스 21,600→17,780 -18%)는 신호 생성 후
    급락한 종목을 stale/peak 가격으로 기록했기 때문이며, 본 SPEC의 신선도·분산
    게이트가 이러한 후보를 신호 단계에서 제거한다.
- **SPEC-AI-015 (시장 레짐 탐지)**: `MarketRegimeEnum`(**BULL / BEAR / SIDEWAYS
  3개 값만 존재, VOLATILE 없음**)을 도입했다. 본 SPEC은 레짐 임계값을 변경하지 않는다.
- **SPEC-AI-018 (임계값·앙상블 정밀화)**: `min_score_for_signal`을 0.45로 상향하고
  `consensus_multiplier_two`/`consensus_multiplier_three_plus`/`strong_single_bypass_threshold`
  를 도입했다. `compute_ensemble_score()`는 탐지기를 news(theme+combo)/disclosure/
  technical 3개 그룹으로 묶어 컨센서스 배율을 적용한다(라인 940~947).
  - **전제**: `volume_news_combo`는 `theme_cluster`와 함께 **news 그룹**에 묶여 있어,
    combo 단독으로는 active_groups가 1로 카운트된다. 본 SPEC의 REQ-AI030-004는 이
    그룹 구조 위에 **combo 단독 신호의 buy-pool 진입을 차단**하는 게이트를 추가하며,
    가중치 합산(`validate_ensemble_weights`)이나 컨센서스 배율 자체는 변경하지 않는다.
- **SPEC-AI-029 (적응형 급등 확률 임계값)**: `AdaptiveThresholdConfig`,
  `SurgeThresholdHistory` 모델, 신호 생성 시점 적응 임계값을 도입했다(현재 구현 중).
  - **전제**: SPEC-AI-029의 `combo_zero_theme_floor`(combo_score=0일 때 theme >= 0.7
    요구)는 **combo가 0인 경우**를 다룬다. 본 SPEC의 REQ-AI030-004는 그 반대 방향,
    즉 **combo > 0이지만 단독으로만 발동된 경우**를 다루므로 상호 보완적이며 충돌하지
    않는다. 두 게이트는 독립적으로 평가된다.

---

## Overview

본 SPEC은 `volume_news_combo` 탐지기가 **거래량 급증이 이미 끝난 종목을 천장에서
추격매수**하는 구조적 결함을 신호 생성 시점에 차단한다. 네 가지 게이트를 정의한다.

1. **당일 과열 필터(REQ-AI030-001)** — combo 신호가 발동할 때 당일 등락
   (`change_rate`)이 이미 높으면(>= 임계) 거래량 급증을 이미 추격한 것이므로 후보에서
   제외한다.
2. **거래량 급증 신선도 검증(REQ-AI030-002)** — z-score가 높은 이유가 어제의 급증이
   오늘 baseline에 잔류하기 때문일 수 있다. 급증이 **최신 거래일**에 발생했는지
   (어제 대비 오늘 거래량 비율) 확인하여 stale 급증을 거른다.
3. **분산 패턴 거부(REQ-AI030-003)** — 거래량은 높은데 가격이 하락 중
   (`change_rate < 0`)이면 매집이 아니라 분산(스마트머니 매도)이므로 매수 신호를
   생성하지 않는다.
4. **앙상블 단독 교차 차단(REQ-AI030-004)** — `combo_score`만으로는 신호 임계값을
   넘지 못하게 하여, 최소 1개 다른 탐지기(theme_cluster 또는 immediate_disclosure)가
   동반될 때만 combo 후보를 buy-pool에 포함한다.

이 SPEC은 **무엇을(WHAT)**과 **왜(WHY)**를 정의하며, 구체적 함수 시그니처·임계값
미세 보정·앙상블 재설계 등은 Run 단계 또는 후속 SPEC으로 이연한다.

### 문제 맥락 — 2026-06-02 운영 증거 (Evidence)

| 종목 | 탐지기 | 결과 | 신호가 → 체결가 | 비고 |
|---|---|---|---|---|
| 라온로보틱스 | volume_news_combo | -8.9% | 21,600 → 17,780 (-18%) | 추격매수 후 급락 |
| 나노팀 | volume_news_combo | -10% | 14,650 → 11,370 (-22%) | 추격매수 후 급락 |
| 삼화전자 | volume_news_combo | -13.8% | 3,905 → 2,810 (-28%) | 추격매수 후 급락 |
| 유니셈 | volume_news_combo | -7.8% | — | 추격매수 후 손실 |
| 에이팩트 | volume_news_combo | -7.4% | — | 추격매수 후 손실 |
| 쎄노텍 | immediate_disclosure + theme_cluster | +10.6% | — | combo 미관여, 유일 성공 |

`volume_news_combo` 6건: **성공 0건 / 실패 5건 + 1건 손실**, 평균 -7.7%.
대조군 `theme_cluster`: 평균 -2.4%, 일부 성공. combo 단독·추격매수가 손실의
주요 원인임이 확인된다.

### 게이트 적용 시나리오

| 시나리오 | change_rate | 오늘/어제 거래량비 | 동반 탐지기 | 기대 동작 |
|---|---|---|---|---|
| 정상 매집 후보 | +2% | 2.0배 (신선) | theme_cluster | 통과 |
| 추격매수 (과열) | +9% | 1.5배 | theme_cluster | REQ-001로 제외 |
| stale 급증 | +1% | 0.6배 (어제 잔류) | theme_cluster | REQ-002로 제외 |
| 분산 (매도) | -2% | 3.0배 | theme_cluster | REQ-003로 제외 |
| combo 단독 | +2% | 2.0배 | (없음) | REQ-004로 buy-pool 미포함 |

---

## Root Cause (네 가지 근본 원인)

### Root Cause 1 — 임계값 통과 시점 = 급증 종료 시점

거래량 z-score가 `volume_zscore_threshold`를 넘을 만큼 높아졌다는 것은 거래량 급증이
이미 발생했다는 의미다. 스마트머니는 이미 매수를 마쳤고, 우리는 가격이 오른 뒤 천장에서
추격매수한다. 신호 생성 시점에 **당일 가격이 이미 얼마나 올랐는지**(`change_rate`)를
점검하지 않는다.

### Root Cause 2 — 거래량 급증 신선도 미검증

`current_vol`(`volumes[-1]`)의 z-score가 높아도, 그 급증이 **오늘** 발생한 것인지
**어제** 발생해 baseline에 잔류한 것인지 구분하지 않는다. 어제의 급증을 오늘 뒤늦게
포착하면 이미 한 박자 늦은 진입이 된다.

### Root Cause 3 — 거래량 방향성(매집 vs 분산) 무시

높은 거래량 + 가격 상승 = 매집(accumulation), 높은 거래량 + 가격 하락 =
분산(distribution). 현재는 두 경우를 동일하게 매수 신호로 처리한다. 분산 국면에서
매수하면 스마트머니의 매도 물량을 받는 셈이다.

### Root Cause 4 — combo 단독 신호의 무차별 진입

`volume_news_combo`는 거래량 + 뉴스라는 단일 이벤트 축에만 반응한다. 테마 동조나
공시 같은 독립적 근거 없이 combo만으로 신호가 생성되면, 거짓 양성률이 높다(2026-06-02
6건 전부 실패). combo는 **확인용 보조 신호**여야 하며 단독 트리거가 되어서는 안 된다.

---

## 설계 원칙 (Design Principles)

1. **Signal-generation-time gating (신호 생성 시점 게이트)**: 모든 게이트는
   `detect_volume_surge_news_combo` 내부 또는 `gather_surge_candidates` 병합 직후에서
   동작한다. 체결 시점(`execute_buy_orders`)의 기존 필터는 변경하지 않으며, 본 SPEC의
   게이트는 그보다 **앞단**에서 추격매수성 후보를 제거한다.
2. **Reuse existing price fetch (가격 조회 재사용)**: REQ-001/003은 탐지기가 이미
   호출하는 `_fetch_price_change_sync` 결과(`change_rate`)를 재사용한다. 신규 외부
   API 호출을 추가하지 않는다. 가격 조회 실패 시(`None`) 보수적으로 후보를 제외한다.
3. **Available-signal-honest (가용 신호 정직성)**: 시가(`open_price`)가 동기 경로에서
   가용하지 않으므로, REQ는 `change_rate`(전일대비)로 작성한다. 시가 기준 판정은
   존재하지 않는 데이터를 가정하지 않고 Non-Goals로 명시 이연한다.
4. **Config-driven thresholds (설정 기반 임계값)**: 모든 임계값(과열 한계, 신선도
   비율, 분산 판정 기준, combo 단독 차단 스위치)은 `surge_detection.yaml`의 신규
   `combo_chase_guard` 섹션에서 조정 가능해야 한다. 섹션 부재 시 문서화된 기본값으로
   동작한다(하위 호환).
5. **Backward compatible & disable-able (하위 호환·비활성 가능)**: `enabled = false`
   이면 본 SPEC의 모든 게이트가 비활성화되고 기존 combo 탐지 동작이 그대로 유지된다.
6. **Scope-locked (범위 고정)**: 다른 3개 탐지기(theme/disclosure/immediate)의 로직,
   앙상블 가중치, 컨센서스 배율, 임계값 보정(SPEC-AI-029 영역)은 변경하지 않는다.

---

## EARS Requirements

### REQ-AI030-001: 신호 생성 시점 당일 과열 필터

**When** `detect_volume_surge_news_combo` evaluates a candidate that has passed the
volume z-score and news-sentiment conditions, the system **shall** read that
candidate's current-day `change_rate` (previous-close percent change) from the
already-fetched `_fetch_price_change_sync` result.

**If** the candidate's `change_rate` is `>= combo_chase_guard.overheat_change_pct`
(default `+5.0`), **then** the system **shall not** include the candidate in the
combo detector output (the volume spike has already been chased — buying now means
buying at the top).

**Where** the price fetch returns `None` (price unavailable), the system **shall**
treat the candidate as ineligible for the overheat gate decision in a conservative
manner: it **shall** exclude the candidate (a candidate whose current price cannot
be confirmed must not be chase-bought). This conservative-exclude behavior **shall**
be controllable via `combo_chase_guard.exclude_on_price_unavailable` (default
`true`).

### REQ-AI030-002: 거래량 급증 신선도 검증

**When** `detect_volume_surge_news_combo` computes the volume z-score for a candidate,
the system **shall** additionally compute a freshness ratio defined as
`current_vol / previous_day_vol` where `current_vol = volumes[-1]` and
`previous_day_vol = volumes[-2]` (the two most recent daily volume bars from
`_get_volume_history`).

**If** the freshness ratio is `< combo_chase_guard.min_freshness_ratio`
(default `1.5`), **then** the system **shall not** include the candidate — a high
z-score driven by a stale spike (yesterday's surge still inflating the baseline
window) rather than a fresh today-spike is rejected.

**Where** fewer than 2 daily volume bars are available (`len(volumes) < 2`), the
system **shall** treat the freshness gate as failing (conservative exclude), because
freshness cannot be verified. **Where** `previous_day_vol` is `0`, the system
**shall** treat the freshness ratio as satisfied only if `current_vol > 0` (a spike
from zero baseline is fresh by definition).

### REQ-AI030-003: 분산(Distribution) 패턴 거부

**If** a combo candidate has a high volume z-score **but** its current-day
`change_rate` is `< combo_chase_guard.distribution_change_pct` (default `0.0`, i.e.
price is declining on the day), **then** the system **shall not** generate a buy
signal for that candidate — high volume with a falling price is a distribution
pattern (smart money selling), not accumulation.

**Where** `change_rate` is exactly `0.0`, the candidate **shall** be treated as
non-distribution (flat is not declining) and **shall** proceed to other gates.
**Where** the price fetch returns `None`, the distribution decision **shall** follow
the same conservative-exclude policy as REQ-AI030-001
(`combo_chase_guard.exclude_on_price_unavailable`).

### REQ-AI030-004: 앙상블 단독 교차 차단 (combo는 보조 신호)

**When** the merged candidate pool is assembled in `gather_surge_candidates`, the
system **shall** require that any candidate whose **only** active detector is
`volume_news_combo` (i.e. `combo_score > 0` while `theme_cluster_score == 0` AND
`immediate_disclosure_score == 0` AND `pattern_score == 0`) be excluded from the
buy-eligible pool — passing the ensemble signal threshold via `combo_score` alone
**shall not** be sufficient.

**Where** a candidate has `combo_score > 0` accompanied by at least one of
`theme_cluster_score > 0`, `immediate_disclosure_score > 0`, or `pattern_score > 0`,
this gate **shall not** apply (combo acts as a confirming signal alongside an
independent detector).

This gate **shall** be controllable via
`combo_chase_guard.require_companion_detector` (default `true`). **When** the master
switch `combo_chase_guard.enabled` is `false`, this gate and REQ-AI030-001 through
REQ-AI030-003 **shall** all be inactive and the legacy combo behavior **shall** be
restored.

### REQ-AI030-005: combo_chase_guard 설정 추가

The system **shall** add a `combo_chase_guard` section under `surge_detection:` in
`backend/app/surge_config/surge_detection.yaml`, parsed by a new Pydantic model
`ComboChaseGuardConfig` in `backend/app/surge_config/surge_settings.py`, attached to
`SurgeDetectionConfig` via `Field(default_factory=...)`. The section **shall** define
at minimum:

- `enabled`: bool master switch for all four gates. Default: `true`.
- `overheat_change_pct`: float. Candidate excluded when `change_rate >=` this value
  (REQ-AI030-001). Default: `5.0`.
- `min_freshness_ratio`: float. Minimum `current_vol / previous_day_vol`
  (REQ-AI030-002). Default: `1.5`.
- `distribution_change_pct`: float. Candidate rejected when `change_rate <` this
  value (REQ-AI030-003). Default: `0.0`.
- `require_companion_detector`: bool. When true, combo-only candidates are excluded
  (REQ-AI030-004). Default: `true`.
- `exclude_on_price_unavailable`: bool. Conservative-exclude when price fetch returns
  `None` (REQ-AI030-001/003). Default: `true`.

When the section is absent from the YAML, the loader **shall** apply the documented
defaults (backward compatible). The configuration **shall** be adjustable without
code changes.

---

## Implementation Scope

| 파일 | 변경 내용 | 관련 REQ |
|---|---|---|
| `backend/app/surge_config/surge_settings.py` | `ComboChaseGuardConfig` Pydantic 모델 신규 추가, `SurgeDetectionConfig`에 `Field(default_factory=...)`로 연결 | REQ-AI030-005 |
| `backend/app/surge_config/surge_detection.yaml` | `combo_chase_guard` 섹션 신규 추가 (enabled, overheat_change_pct, min_freshness_ratio, distribution_change_pct, require_companion_detector, exclude_on_price_unavailable) | REQ-AI030-005 |
| `backend/app/services/surge_detector.py` | `detect_volume_surge_news_combo`에 과열 필터·신선도 검증·분산 거부 게이트 추가 (이미 호출 중인 `_fetch_price_change_sync` 결과 및 `volumes[-1]`/`volumes[-2]` 재사용); `gather_surge_candidates` 병합 직후 combo-단독 후보 제외 게이트 추가 | REQ-AI030-001~004 |
| `backend/tests/test_surge_ai030.py` (신규) | 과열 필터·신선도(stale/fresh/zero-baseline)·분산·combo 단독 차단·가격 None 보수 제외·enabled=false 폴백·설정 부재 기본값 테스트 | 전체 |

---

## Non-Goals (What NOT to Build)

본 SPEC의 범위에서 **명시적으로 제외**되는 항목:

- **시가(open_price) 기준 판정은 구현하지 않는다.** `_fetch_price_change_sync`가
  시가를 반환하지 않으므로(`current_price`/`change_rate`만), "시가 대비 +5%" 또는
  "current_price < open_price" 형태의 판정은 본 탐지기 경로에서 가용하지 않다. 본
  SPEC은 전일대비 `change_rate`로 대체한다. 시가 데이터를 새 API로 조회하는 작업은
  별도 후속 SPEC 후보이다.
- **체결 시점 필터(`execute_buy_orders`의 INTRADAY_CRASH_LIMIT/INTRADAY_OVERHEAT_LIMIT/
  ENTRY_GAPUP_LIMIT)는 변경하지 않는다.** 본 SPEC은 신호 생성 시점 게이트만 추가하며,
  기존 체결 게이트는 이중 안전망으로 그대로 둔다.
- **임계값 미세 보정(calibration)은 포함하지 않는다.** `volume_zscore_threshold`,
  `min_score_for_signal`, 레짐별 임계값, SPEC-AI-029의 적응형 임계값 로직을 변경하지
  않는다. 본 SPEC의 게이트는 그 위에 추가되는 별도 필터다.
- **앙상블 재설계는 포함하지 않는다.** `compute_ensemble_score`의 가중치, 컨센서스
  배율(`consensus_multiplier_*`), news/disclosure/technical 그룹 구조,
  `validate_ensemble_weights`를 변경하지 않는다. REQ-AI030-004는 앙상블 점수 계산을
  바꾸지 않고 buy-pool 진입 단계에서 combo-단독 후보를 제외하는 게이트일 뿐이다.
- **다른 탐지기는 건드리지 않는다.** `detect_theme_news_cluster`,
  `detect_disclosure_surge_pattern`, `detect_immediate_disclosure_signal` 및 기타
  보조 탐지기(group_cascade, near_limit_up 등)의 로직을 변경하지 않는다.
- **신선도 검증을 분(minute) 단위로 정밀화하지 않는다.** `_get_volume_history`는
  일봉(daily) 거래량을 제공하므로 신선도는 일 단위 해상도(`volumes[-1]/volumes[-2]`)로
  판정한다. 장중 실시간 거래량 스트림 도입은 제외한다.
- **포지션 사이징·max_open_positions·BUY_CUTOFF·max_daily_entries 변경은 포함하지
  않는다.** 본 SPEC은 combo 탐지기 진입 게이트만 다룬다.
- **백테스팅 또는 A/B 테스트 하네스 구축은 포함하지 않는다.** 게이트 효과 측정은
  운영 로그를 활용하는 별도 후속 SPEC 후보이다.
- **GitHub 이슈 생성은 포함하지 않는다.** 본 SPEC은 로컬 전용이다.

---

## References

### 코드 위치 (수정/신규 대상)

- `backend/app/services/surge_detector.py`
  - `detect_volume_surge_news_combo()` (라인 418~553) — 과열·신선도·분산 게이트 추가
    진입점 (REQ-AI030-001~003)
  - `gather_surge_candidates()` (라인 995~) — 병합 후 combo-단독 제외 게이트
    (REQ-AI030-004)
  - `_fetch_price_change_sync()` (라인 393~407) — 재사용할 가격 조회 (신규 호출 없음)
  - `_get_volume_history()` (라인 556~) — `volumes[-1]`/`volumes[-2]` 신선도 비율 출처
- `backend/app/surge_config/surge_settings.py`
  - `ComboChaseGuardConfig` 신규 모델, `SurgeDetectionConfig` 연결 (REQ-AI030-005)
- `backend/app/surge_config/surge_detection.yaml` — `combo_chase_guard` 섹션
  (REQ-AI030-005)

### 데이터·동작 사실 확인

- `_fetch_price_change_sync(stock_code)` → `{"current_price": int, "change_rate":
  float}` 또는 `None`. **시가(open_price) 없음.** `change_rate`는 전일 종가 대비 %
  등락 (`naver_finance.fetch_current_price_with_change_sync` 라인 810~836).
- `SurgeCandidate` 필드: `theme_cluster_score`, `combo_score`, `pattern_score`,
  `immediate_disclosure_score`, `active_detectors` (surge_detector.py 라인 58~79).
- combo 탐지기는 이미 후보별로 `_fetch_price_change_sync`를 호출하여 PER/PBR을
  piggy-back 수집한다(라인 533~538). 본 SPEC은 동일 호출 결과의 `change_rate`/
  `current_price`를 재사용한다.
- 체결 시점 기존 상수(변경 대상 아님, 이중 안전망):
  `INTRADAY_CRASH_LIMIT = -3.0`, `INTRADAY_OVERHEAT_LIMIT = 15.0`,
  `ENTRY_GAPUP_LIMIT = 0.05` (`surge_trading_service.py` 라인 32~34).
- 앙상블 그룹: news(theme+combo)/disclosure/technical (`compute_ensemble_score`
  라인 940~947). combo는 theme와 동일 news 그룹.

### 선행 SPEC

- SPEC-AI-012: 급등 징후 탐지 시스템 (combo 탐지기, SurgeCandidate, 설정 인프라)
- SPEC-AI-013: 급등예측 페이퍼 트레이딩 (execute_buy_orders 체결 게이트)
- SPEC-AI-015: 시장 레짐 탐지 (MarketRegimeEnum — BULL/BEAR/SIDEWAYS)
- SPEC-AI-018: 임계값·앙상블 정밀화 (min_score_for_signal, 컨센서스 배율, 그룹 구조)
- SPEC-AI-029: 적응형 급등 확률 임계값 (combo_zero_theme_floor — 본 SPEC과 보완 관계)
