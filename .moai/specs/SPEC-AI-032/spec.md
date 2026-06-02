---
id: SPEC-AI-032
version: 0.1.0
status: draft
created: 2026-06-02
updated: 2026-06-02
author: MoAI
priority: High
issue_number: null
---

# SPEC-AI-032: 뉴스 속도 탐지기 (News Velocity Detector)

## HISTORY

- 2026-06-02 (v0.1.0): 최초 작성. 2026-06-02 운영 분석에서 오후 신호의
  `theme_cluster_score`가 0.94~0.97로 매우 높았으나 **모두 약한 후보**(보조 탐지기
  동반 0건)였고 실제 급등으로 이어지지 않은 사실이 확인되었다. 근본 원인은
  `detect_theme_news_cluster`가 `cluster_window_hours`(24h) 내 테마 키워드 **총
  기사 수**만 카운트하므로, "24시간 내내 시간당 10건"(이미 가격에 반영된 stale
  테마)과 "어제 시간당 1건이었다가 지금 시간당 10건으로 급증"(돌파 직전, 미반영
  테마)을 **구분하지 못한다**는 데 있다. 실제 급등은 테마가 **안정적으로 활성**일
  때가 아니라 **가속(velocity spike)**할 때 발생하는 경향이 있다. 본 SPEC은 테마별
  기사 발생 **속도의 가속도**를 측정하는 신규 탐지기 `detect_news_velocity`를
  추가하여, 전체 테마 전파 이전에 조기 신호를 포착한다.

---

## 선행 SPEC (전제 조건 / Assumptions)

본 SPEC은 다음 기존 SPEC이 구축한 인프라 위에 동작하며, 새로운 매매 엔진을 만들지
않고 기존 자산을 재사용한다.

- **SPEC-AI-012 (급등 징후 탐지 시스템)**: `surge_detector.py`의 4개 탐지기
  (theme_cluster, volume_news_combo, immediate_disclosure, disclosure_pattern),
  앙상블 스코어링, `SurgeCandidate` 데이터클래스, `surge_settings.py`의
  `SurgeDetectionConfig`/`EnsembleConfig`/`EnsembleWeightsConfig`/`get_surge_config()`
  설정 인프라를 도입했다. 본 SPEC의 신규 탐지기는 **탐지기 5**로 이 파이프라인에
  편입된다.
  - **[HARD] 사실 확인 — `SurgeCandidate` 현재 필드**: `stock_code`, `stock_name`,
    `theme_cluster_score`, `combo_score`, `pattern_score`, `legacy_score`,
    `immediate_disclosure_score`, `active_detectors`, `price_5d_trend`, `per`,
    `pbr`, `disclosure_sentiment` (surge_detector.py 라인 58~79). `velocity_score`
    필드는 **존재하지 않으며** 본 SPEC이 신규 추가한다.
  - **[HARD] 사실 확인 — `gather_surge_candidates`는 종목 코드 기준 병합 구조**:
    각 탐지기 결과를 `merged: dict[str, SurgeCandidate]`로 병합한다(라인 1063~).
    본 SPEC의 `detect_news_velocity` 결과도 이 병합 경로에 합류하여, 동일 종목에
    대해 `theme_cluster_score`와 `velocity_score`가 같은 `SurgeCandidate` 객체에
    채워지도록 한다.
- **SPEC-AI-014 (테마 클러스터 종목 수준 개인화)**: `detect_theme_news_cluster`의
  점수 산식을 도입했다.
  - **[HARD] 사실 확인 — 현재 테마 클러스터는 "총량"만 본다**:
    `detect_theme_news_cluster`는 `cluster_window_hours`(24h) 내 뉴스를 DB에서 직접
    조회(`NewsArticle.published_at >= cutoff`, 최대 1000건, 라인 203~209)한 뒤,
    키워드별 기사 수 `keyword_counts[kw]`를 누적하고(라인 216~221),
    `theme_base = min(1.0, cnt / 10)`(라인 298)로 점수를 만든다. 이는 윈도 내
    **누적 총량**이며, 시간에 따른 **변화율(가속도)**을 전혀 반영하지 않는다. 본
    SPEC은 이 산식을 **변경하지 않고**, 가속도를 별도 차원으로 측정하는 신규
    탐지기를 병렬 추가한다.
  - **[HARD] 사실 확인 — 시간 기준 컬럼은 `NewsArticle.published_at`(naive UTC)**:
    테마 클러스터는 `cutoff_naive = cutoff.replace(tzinfo=None)`로 naive datetime
    비교를 사용한다(라인 199~205). 본 SPEC의 속도 계산도 동일한 `published_at`
    naive UTC 비교를 사용하여 시간대 불일치를 방지한다.
- **SPEC-AI-018 (임계값·앙상블 정밀화)**: `compute_ensemble_score()`를 탐지기
  그룹 단위(news / disclosure / technical)로 묶어 컨센서스 배율을 적용하도록
  재설계했다.
  - **[HARD] 사실 확인 — news 그룹은 현재 [theme_cluster, combo] 2개**:
    `compute_ensemble_score`의 `detector_groups["news"]`는
    `[candidate.theme_cluster_score, candidate.combo_score]`이다(라인 980).
    `active_groups`는 "그룹 내 하나라도 점수 > 0이면 1"로 카운트된다(라인 984~986).
    본 SPEC은 `news_velocity`를 **news 그룹에 합류**시켜, theme/combo/velocity가
    모두 동일 news 이벤트 축으로 묶이게 한다. 즉 velocity 단독 발동 또는 theme+
    velocity 동반 발동 모두 news 그룹 1개로만 카운트되어 **동일 뉴스 이벤트의
    이중 보상(double-counting)을 방지**한다.
  - **[HARD] 사실 확인 — 가중치 합산 1.0 불변식이 존재한다**:
    `SurgeDetectionConfig.validate_ensemble_weights`(라인 216~225)는
    `theme_cluster + volume_news_combo + disclosure_pattern + legacy_detectors`가
    1.0(±0.001)이어야 한다는 `@model_validator`를 강제한다. `EnsembleWeightsConfig`
    에 `news_velocity`를 단순 추가하면 **이 불변식 검증 방식과의 정합성**을 반드시
    결정해야 한다(REQ-AI032-005에서 명시).

---

## Overview

본 SPEC은 테마별 뉴스 기사의 **발생 속도 가속도(velocity acceleration)**를 측정하는
신규 탐지기 `detect_news_velocity`를 추가한다. 기존 `theme_cluster`가 윈도 내 누적
총량(stale 여부 무관)을 보는 반면, 본 탐지기는 "최근 2시간 발생량이 24시간 평균
대비 몇 배인가"를 보아 **테마가 막 가속하기 시작한 시점**을 조기에 포착한다.

이 SPEC은 **무엇을(WHAT)**과 **왜(WHY)**를 정의하며, 구체적 함수 시그니처·임계값
미세 보정·앙상블 가중치 최종 수치는 Run 단계 또는 후속 SPEC으로 이연한다.

### 핵심 속도 공식 (Velocity Formula)

```
baseline_per_2h = articles_last_24h / 12        # 24시간을 2시간 단위 12구간으로 나눈 기대값
velocity_ratio  = articles_in_last_2h / baseline_per_2h
```

- `velocity_ratio >= 2.0`: 후보 생성 임계(기준 대비 2배 가속)
- `velocity_ratio >= 3.0`: 뉴스가 baseline 대비 3배로 가속 중
- `velocity_ratio >= 5.0`: 대형 뉴스 급증(major spike)

`velocity_score`(0.0~1.0)는 `velocity_ratio`에서 단조 증가하는 함수로 도출한다
(구체적 변환식은 Run 단계 결정 — 예: `min(1.0, (velocity_ratio - 2.0) / k)` 또는
시그모이드. 본 SPEC은 단조성과 0.0~1.0 범위만 요구한다).

### 문제 맥락 — 2026-06-02 운영 증거 (Evidence)

| 신호 시점 | theme_cluster_score | 보조 탐지기 | 결과 | 비고 |
|---|---|---|---|---|
| 오후 신호군 | 0.94~0.97 (매우 높음) | 없음 (단독) | 약함 | stale 테마 — 이미 반영 |

높은 `theme_cluster_score`는 테마가 **여전히 활성**임을 뜻할 뿐, 테마가 **새롭다
(미반영)**는 것을 뜻하지 않는다. 누적 총량만으로는 stale 테마와 breaking 테마를
구분할 수 없다.

### 가속/비가속 시나리오

| 시나리오 | 최근 2h 기사 | 24h 기사 | baseline(24h/12) | velocity_ratio | 기대 동작 |
|---|---|---|---|---|---|
| stale 테마 (균일) | 20 | 240 | 20 | 1.0 | 후보 미생성 (가속 없음) |
| 가속 테마 (돌파) | 10 | 24 | 2 | 5.0 | major spike 후보 |
| 완만 가속 | 6 | 36 | 3 | 2.0 | 임계 통과 후보 |
| 저활성 신규 | 4 | 12 | 1 | 4.0 | 가속 후보 |

stale 테마는 `theme_cluster_score`는 높아도 `velocity_score`는 낮고, breaking
테마는 그 반대 — 두 차원이 상호 보완적으로 작동한다.

### 실용적 이점 (Practical Benefit)

- `theme_cluster_score = 0.50` + `velocity_score = 0.80`인 종목은 두 점수가
  앙상블에 함께 반영되어 단일 차원만으로는 도달하기 어려운 점수에 도달한다.
- 전체 테마 전파(stale 단계) **이전**의 조기 신호를 포착한다.

---

## Root Cause (근본 원인)

### Root Cause 1 — 누적 총량은 신선도(가속도)를 표현하지 못한다

`theme_base = min(1.0, cnt / 10)`는 윈도 내 **총 기사 수**의 단조 함수다. 시간당
10건이 24시간 지속된 테마(총 240건)와 어제는 조용하다가 지금 막 가속한 테마(총
24건)를 비교하면, 전자가 항상 더 높은 점수를 받는다. 그러나 후자가 미반영 상태일
가능성이 높다. 총량 지표는 **변화율 정보를 폐기**한다.

### Root Cause 2 — stale 신호의 거짓 확신

윈도가 24시간으로 길어 stale 테마가 만점에 가까운 점수를 유지한다(2026-06-02 오후
0.94~0.97). 높은 점수가 "강한 신호"로 오인되어 약한 후보가 통과되었다. 가속도
차원이 없으면 "여전히 활성"과 "막 시작"을 구분할 수 없다.

---

## 설계 원칙 (Design Principles)

1. **Additive, non-mutating (가산·비변경)**: `detect_news_velocity`는 신규 함수이며
   `detect_theme_news_cluster`의 산식(`theme_base = min(1.0, cnt/10)`)을 **변경하지
   않는다**. velocity는 별도 차원으로 추가된다.
2. **Reuse existing news query path (뉴스 조회 재사용)**: 테마 클러스터와 동일한
   `NewsArticle.published_at` naive UTC 비교, 동일 키워드/`sector_theme_map`을
   재사용한다. 신규 외부 API 호출을 추가하지 않는다.
3. **No double-counting (이중 보상 방지)**: `news_velocity`는 `compute_ensemble_score`
   의 **news 그룹**(theme_cluster, combo와 동일)에 합류한다. theme와 velocity가
   동시에 발동해도 news 그룹은 1개로만 카운트되어 컨센서스 배율을 인위적으로
   부풀리지 않는다.
4. **Backward compatible (하위 호환)**: velocity 설정이 부재하거나 비활성이면
   모든 `velocity_score`는 `0.0`으로 기본값 처리되어 기존 앙상블 동작이 그대로
   유지된다.
5. **Invariant-honest (불변식 정직성)**: 가중치 합산 1.0 불변식을 **명시적으로**
   다룬다(REQ-AI032-005). `news_velocity`를 기존 합산식에 포함시킬지, 별도 비합산
   가중치로 둘지를 SPEC에서 결정하여 `validate_ensemble_weights`가 깨지지 않도록
   한다.
6. **Scope-locked (범위 고정)**: 다른 4개 탐지기 로직, 매매 엔진, 포지션 사이징,
   체결 게이트는 변경하지 않는다.

---

## EARS Requirements

### REQ-AI032-001: 뉴스 속도 탐지기 신규 추가

The system **shall** provide a new detector function `detect_news_velocity(db, config)`
in `backend/app/services/surge_detector.py` that, for each active theme keyword,
computes a velocity ratio comparing recent article rate against the 24-hour baseline
rate.

**When** `detect_news_velocity` is invoked, the system **shall** query `NewsArticle`
records using the same `published_at` naive-UTC comparison and the same theme keyword
set + `sector_theme_map` as `detect_theme_news_cluster`, **shall not** introduce a
new external API call, and **shall not** modify the existing `detect_theme_news_cluster`
scoring formula.

### REQ-AI032-002: 속도 비율 계산

**When** `detect_news_velocity` evaluates a theme keyword, the system **shall** compute:

- `articles_in_last_2h` = count of matching articles with
  `published_at >= now - NewsVelocityConfig.window_hours` (default `2`)
- `articles_last_24h` = count of matching articles with
  `published_at >= now - NewsVelocityConfig.baseline_window_hours` (default `24`)
- `baseline_per_window = articles_last_24h / (baseline_window_hours / window_hours)`
  (default divisor `12`)
- `velocity_ratio = articles_in_last_2h / baseline_per_window`

**Where** `baseline_per_window` is `0` (no articles in the 24h baseline), the system
**shall** treat `velocity_ratio` as `0.0` (a theme with no baseline activity cannot be
"accelerating" in a measurable sense) **rather than** dividing by zero.

### REQ-AI032-003: velocity_score 도출 및 후보 생성 임계

**If** a theme's `velocity_ratio` is `>= NewsVelocityConfig.min_velocity_ratio`
(default `2.0`), **then** the system **shall** generate `SurgeCandidate` objects for
the stocks in that theme's mapped sectors (reusing the same sector/stock resolution
and market-cap filtering as `detect_theme_news_cluster`), with the candidate's
`velocity_score` field populated.

The `velocity_score` **shall** be a value in `[0.0, 1.0]` derived as a monotonically
non-decreasing function of `velocity_ratio` (the exact transform is deferred to the
Run phase; only monotonicity and the `[0.0, 1.0]` range are required here).

**When** a candidate is generated by this detector, the system **shall** append
`"news_velocity"` to that candidate's `active_detectors` list.

**If** `velocity_ratio < min_velocity_ratio`, **then** the system **shall not**
generate a candidate from this detector for that theme.

### REQ-AI032-004: SurgeCandidate velocity_score 필드 추가 (하위 호환)

The system **shall** add a new field `velocity_score: float = 0.0` to the
`SurgeCandidate` dataclass in `backend/app/services/surge_detector.py`.

**Where** no velocity detector runs or velocity configuration is absent, `velocity_score`
**shall** default to `0.0`, and every existing detector and the ensemble pipeline
**shall** continue to function unchanged (the new field is purely additive).

**When** `detect_news_velocity` results are merged into the candidate pool in
`gather_surge_candidates` (keyed by `stock_code`), the system **shall** populate
`velocity_score` on the existing merged `SurgeCandidate` for that stock so that
`theme_cluster_score` and `velocity_score` coexist on the same object.

### REQ-AI032-005: 앙상블 가중치 추가 및 합산 불변식 정합

The system **shall** add a `news_velocity` weight entry to `EnsembleWeightsConfig` in
`backend/app/surge_config/surge_settings.py` so that `compute_ensemble_score` can apply
a configurable weight to `velocity_score`.

**Because** `SurgeDetectionConfig.validate_ensemble_weights` enforces that
`theme_cluster + volume_news_combo + disclosure_pattern + legacy_detectors == 1.0`
(±0.001), the system **shall** reconcile the new `news_velocity` weight with this
invariant. The reconciliation **shall** follow one of these two approaches, decided in
the Run phase, and **shall not** leave the existing validator broken:

- **Option A (intra-news redistribution, recommended)**: `news_velocity` is **not**
  added to the sum-to-1.0 set. Instead, the `news` group's contribution to the ensemble
  is computed as a blend of `theme_cluster_score`, `combo_score`, and `velocity_score`
  **within** the existing `theme_cluster` + `volume_news_combo` weight envelope, so the
  four-weight sum-to-1.0 invariant is preserved unchanged. `news_velocity: 0.30` then
  acts as the velocity component's share **inside** the news group, not a fifth top-level
  weight.
- **Option B (extend the invariant)**: `news_velocity` becomes a fifth top-level weight
  and `validate_ensemble_weights` is updated to require all five weights to sum to 1.0,
  with the existing four weights re-normalized accordingly.

**Where** `news_velocity` is absent from configuration, the loader **shall** apply a
documented default such that velocity contributes nothing (effective weight `0.0`),
preserving exact backward compatibility.

### REQ-AI032-006: news 그룹 합류 및 이중 보상 방지

**When** `compute_ensemble_score` evaluates a candidate, the system **shall** include
`velocity_score` in the `detector_groups["news"]` group alongside `theme_cluster_score`
and `combo_score`, so that the news group fires (counts toward `active_groups`) when
**any** of theme, combo, or velocity is `> 0`.

**Where** both `theme_cluster_score > 0` and `velocity_score > 0` for the same candidate,
the system **shall** still count the news group as exactly **one** active group (no
double-counting of the same news event for the consensus multiplier), while the
individual weighted contributions of theme and velocity **shall** both be reflected in
the weighted sum.

### REQ-AI032-007: NewsVelocityConfig 설정 추가

The system **shall** add a `NewsVelocityConfig` Pydantic model in
`backend/app/surge_config/surge_settings.py`, attached to `SurgeDetectionConfig` via
`Field(default_factory=...)`, defining at minimum:

- `window_hours`: int. Recent-rate window. Default: `2`.
- `baseline_window_hours`: int. Baseline window. Default: `24`.
- `min_velocity_ratio`: float. Candidate-generation threshold (REQ-AI032-003).
  Default: `2.0`.

**When** the configuration is absent from the loaded YAML, the loader **shall** apply
these documented defaults (backward compatible), and the configuration **shall** be
adjustable without code changes.

---

## Implementation Scope

| 파일 | 변경 내용 | 관련 REQ |
|---|---|---|
| `backend/app/services/surge_detector.py` | `SurgeCandidate`에 `velocity_score: float = 0.0` 필드 추가; `detect_news_velocity(db, config)` 신규 탐지기 함수 추가(테마 클러스터의 뉴스 조회·키워드·섹터 해석 재사용, 속도 비율 계산, velocity_score 산출, active_detectors에 "news_velocity" 추가); `gather_surge_candidates`에서 velocity 결과를 stock_code 기준 병합; `compute_ensemble_score`에서 velocity_score를 news 그룹에 합류시키고 가중 합산에 반영 | REQ-AI032-001~006 |
| `backend/app/surge_config/surge_settings.py` | `NewsVelocityConfig` Pydantic 모델 신규 추가, `SurgeDetectionConfig`에 `Field(default_factory=...)`로 연결; `EnsembleWeightsConfig`에 `news_velocity` 가중치 추가 + `validate_ensemble_weights` 불변식 정합 처리(REQ-AI032-005 Option A 또는 B) | REQ-AI032-005, REQ-AI032-007 |
| `backend/tests/test_surge_ai032.py` (신규) | 속도 비율 계산(정상/가속/stale/zero-baseline/0÷0 방지), velocity_score 단조성·범위, 임계 미달 후보 미생성, active_detectors 반영, velocity_score 기본값 0.0 하위 호환, news 그룹 단일 카운트(이중 보상 방지), 가중치 합산 불변식 유지(Option A/B), 설정 부재 기본값 테스트 | 전체 |

---

## Non-Goals (What NOT to Build)

본 SPEC의 범위에서 **명시적으로 제외**되는 항목:

- **`detect_theme_news_cluster`의 기존 산식은 변경하지 않는다.** `theme_base =
  min(1.0, cnt / 10)`, 종목 수준 블렌딩(SPEC-AI-014), 거래량 보너스 등 기존 테마
  클러스터 로직을 일절 수정하지 않는다. velocity는 **병렬 추가** 차원이다.
- **분(minute) 단위 또는 실시간 스트림 속도는 구현하지 않는다.** 속도는 시간 단위
  윈도(`window_hours`/`baseline_window_hours`)로 측정한다. 장중 실시간 뉴스 스트림
  도입은 별도 후속 SPEC 후보이다.
- **velocity_score → surge_probability 변환식의 최종 보정은 포함하지 않는다.**
  본 SPEC은 단조성과 `[0.0, 1.0]` 범위만 요구하며, 구체적 변환 곡선(선형/시그모이드)
  과 계수는 Run 단계에서 결정한다.
- **news 그룹 외 다른 그룹 구조는 변경하지 않는다.** disclosure/technical 그룹,
  컨센서스 배율(`consensus_multiplier_*`), `min_score_for_signal`, SPEC-AI-029
  적응형 임계값, SPEC-AI-030 combo 게이트를 변경하지 않는다.
- **다른 탐지기는 건드리지 않는다.** `detect_volume_surge_news_combo`,
  `detect_disclosure_surge_pattern`, `detect_immediate_disclosure_signal` 및 기타
  보조 탐지기(group_cascade, near_limit_up, theme_propagation 등) 로직을 변경하지
  않는다.
- **매매 엔진·포지션 사이징·체결 게이트는 변경하지 않는다.** `max_open_positions`,
  `position_pct`, `BUY_CUTOFF`, `max_daily_entries`, `execute_buy_orders` 체결
  필터를 변경하지 않는다.
- **velocity 전용 별도 그룹은 만들지 않는다.** velocity는 news 그룹에 합류하며,
  네 번째 탐지기 그룹을 신설하지 않는다(이중 보상 방지 — REQ-AI032-006).
- **백테스팅 또는 A/B 테스트 하네스 구축은 포함하지 않는다.** velocity 탐지기 효과
  측정은 운영 로그를 활용하는 별도 후속 SPEC 후보이다.
- **GitHub 이슈 생성은 포함하지 않는다.** 본 SPEC은 로컬 전용이다.

---

## References

### 코드 위치 (수정/신규 대상)

- `backend/app/services/surge_detector.py`
  - `SurgeCandidate` (라인 58~79) — `velocity_score: float = 0.0` 필드 추가
    (REQ-AI032-004)
  - `detect_news_velocity()` (신규) — 속도 탐지기 진입점 (REQ-AI032-001~003)
  - `detect_theme_news_cluster()` (라인 177~) — 뉴스 조회·키워드·섹터 해석 패턴
    참조(재사용 대상이며 **변경 대상 아님**); `theme_base = min(1.0, cnt/10)`는
    라인 298
  - `gather_surge_candidates()` (라인 1034~) — velocity 결과 stock_code 병합
    (REQ-AI032-004)
  - `compute_ensemble_score()` (라인 947~1007) — `detector_groups["news"]`에
    velocity 합류 + 가중 합산 반영 (REQ-AI032-005/006)
- `backend/app/surge_config/surge_settings.py`
  - `NewsVelocityConfig` 신규 모델, `SurgeDetectionConfig` 연결 (REQ-AI032-007)
  - `EnsembleWeightsConfig` (라인 61~67) — `news_velocity` 가중치 추가
    (REQ-AI032-005)
  - `validate_ensemble_weights()` (라인 216~225) — 합산 1.0 불변식 정합
    (REQ-AI032-005)

### 데이터·동작 사실 확인

- `detect_theme_news_cluster`는 `NewsArticle.published_at >= cutoff_naive`(naive
  UTC) 비교로 윈도 내 뉴스를 DB 직접 조회(최대 1000건)하고, 키워드별 누적
  `keyword_counts[kw]`로 `theme_base = min(1.0, cnt/10)` 점수를 만든다 — **변화율
  미반영**(surge_detector.py 라인 199~298).
- `SurgeCandidate` 현재 필드에 `velocity_score` 없음(라인 58~79) — 본 SPEC 신규
  추가.
- `compute_ensemble_score`의 `detector_groups["news"] = [theme_cluster_score,
  combo_score]`, `active_groups`는 그룹 내 점수 > 0이면 1로 카운트(라인 979~986).
- `validate_ensemble_weights`는 4개 가중치 합산 1.0(±0.001) 강제
  (`@model_validator`, 라인 216~225) — `news_velocity` 추가 시 정합 필요.
- 설정 모델은 `Field(default_factory=...)` 패턴으로 `SurgeDetectionConfig`에 연결
  (예: `combo_chase_guard`, `adaptive_threshold`, `disclosure_type_filter`,
  라인 208~212).

### 선행 SPEC

- SPEC-AI-012: 급등 징후 탐지 시스템 (탐지기 인프라, SurgeCandidate, 앙상블, 설정)
- SPEC-AI-014: 테마 클러스터 종목 수준 개인화 (theme_cluster 점수 산식 상세)
- SPEC-AI-018: 임계값·앙상블 정밀화 (news/disclosure/technical 그룹 구조)
- SPEC-AI-029: 적응형 급등 확률 임계값 (본 SPEC과 독립, 임계값 영역 — 변경 안 함)
- SPEC-AI-030: combo 추격매수 방지 (본 SPEC과 독립, combo 게이트 영역 — 변경 안 함)
