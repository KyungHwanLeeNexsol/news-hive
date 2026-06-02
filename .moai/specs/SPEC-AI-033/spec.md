---
id: SPEC-AI-033
version: 0.1.0
status: draft
created: 2026-06-02
updated: 2026-06-02
author: MoAI
priority: High
issue_number: null
---

# SPEC-AI-033: 즉각 공시 가중치 독립화 (Immediate Disclosure Weight Independence)

## HISTORY

- 2026-06-02 (v0.1.0): 최초 작성. 2026-06-02 앙상블 스코어링 시스템 분석에서
  `immediate_disclosure` 탐지기가 **경험적으로 가장 강력한 예측자**(쎄노텍 +10.6%,
  오스템 +15%, 파미셀 +8%)임에도 불구하고, 앙상블 점수에 대한 기여가 구조적으로
  과소평가(under-weighted)되어 있는 사실이 확인되었다. 근본 원인은
  `compute_ensemble_score()`가 `best_disclosure_score = max(pattern_score,
  immediate_disclosure_score)` 형태로 두 공시 탐지기를 **동일한
  `disclosure_pattern` 가중치(0.20)에 공유**시키기 때문이다. 따라서
  `immediate_disclosure_score`가 아무리 높아도 0.20 비중을 넘는 기여를 할 수 없다.
  SPEC-AI-018에서 도입된 우회 메커니즘(`immediate_disclosure_bypass_threshold = 0.85`)은
  강한 즉각 공시가 임계값 게이트를 통과하도록 돕는 임시방편이었으나, 우회로
  살아남은 후보의 **저장된 확률값(`surge_probability_score`)은 여전히 0.20 비중만
  반영**한다. 그 결과 포지션 사이징/랭킹/임계값 비교에서 즉각 공시 후보가
  부당하게 낮게 평가된다.

  - **검증 데이터 (파미셀, 저장 점수 0.4843)**: 현재 공식에서
    `theme_cluster_score = 0.7448`, `immediate_disclosure_score = 0.82`,
    `pattern_score = 0`일 때
    `weighted_sum = 0.7448 × 0.28 + max(0, 0.82) × 0.20 = 0.2085 + 0.1640 = 0.3725`,
    컨센서스 배율(news + disclosure 2개 그룹 → 1.30) 적용 시
    `0.3725 × 1.30 = 0.4843`. 즉, 가장 강한 신호(0.82)가 0.20 비중에 갇혀 있다.
  - **개선 시 (immediate_disclosure 독립 가중치 0.35 가정)**:
    `weighted_sum = 0.7448 × 0.28 + 0.82 × 0.35 = 0.2085 + 0.2870 = 0.4955`,
    `0.4955 × 1.30 = 0.6442`. 동일 후보가 0.4843 → 0.6442로 상향되어 신호 강도가
    실제 예측력에 부합한다.

  본 SPEC은 `immediate_disclosure_score`를 `disclosure_pattern`에서 분리하여
  **독립 가중치**와 **독립 컨센서스 그룹**으로 승격한다.

---

## 선행 SPEC (전제 조건 / Assumptions)

본 SPEC은 다음 기존 SPEC이 구축한 앙상블 인프라 위에서 동작하며, 새로운 탐지기를
만들지 않는다. 가중치 배분과 그룹 카운트 로직만 재정의한다.

- **SPEC-AI-012 (급등 징후 탐지 시스템)**: `surge_detector.py`의 4개 탐지기
  (`theme_cluster`, `volume_news_combo`, `immediate_disclosure`, `disclosure_pattern`),
  `compute_ensemble_score()`, `surge_settings.py`의 `EnsembleWeightsConfig` /
  `EnsembleConfig` / `SurgeDetectionConfig` / `get_surge_config()` 설정 인프라를
  도입했다.
  - **[HARD] 사실 확인 — 현재 `EnsembleWeightsConfig` 필드**: `theme_cluster`,
    `volume_news_combo`, `disclosure_pattern`, `legacy_detectors` 4개 float 필드만
    존재한다. **`immediate_disclosure` 필드는 존재하지 않는다.**
  - **[HARD] 사실 확인 — 가중치 합산 검증자**: `SurgeDetectionConfig`에
    `@model_validator(mode="after") validate_ensemble_weights`가 존재하며,
    `theme_cluster + volume_news_combo + disclosure_pattern + legacy_detectors`의
    합이 `1.0 (±0.001)`이 아니면 `ValueError`를 발생시킨다. 새 필드를 추가하면
    이 검증자도 반드시 갱신해야 한다(REQ-AI033-005 참조).
  - **[HARD] 사실 확인 — `SurgeCandidate` 점수 필드**: `candidate.theme_cluster_score`,
    `candidate.combo_score`, `candidate.pattern_score`,
    `candidate.immediate_disclosure_score`, `candidate.legacy_score`가 이미
    개별적으로 존재한다. 본 SPEC은 새 점수 필드를 만들지 않고 기존
    `immediate_disclosure_score`를 독립 항으로 사용한다.
- **SPEC-AI-017 (컨센서스 배율 도입)**: `EnsembleConfig.consensus_multiplier_two`(1.30),
  `consensus_multiplier_three_plus`(1.55), `regime_thresholds`를 도입했다.
  - **[HARD] 사실 확인 — 현재 컨센서스 그룹**: `compute_ensemble_score()`의
    `detector_groups`는 `news`(theme + combo), `disclosure`(best_disclosure_score),
    `technical`(legacy) **3개 그룹**뿐이며, 배율은 `active_groups`가 1/2/3+개일 때
    `1.00 / consensus_multiplier_two / consensus_multiplier_three_plus`로 적용된다.
    **4개 그룹 배율은 존재하지 않는다.** 본 SPEC이 `immediate_disclosure`를 독립
    그룹으로 분리하면 그룹 수가 최대 4개가 되므로 4개 그룹 배율을 신설해야 한다
    (REQ-AI033-003 참조).
- **SPEC-AI-018 (앙상블 정밀화)**: `theme_cluster`를 0.28로, `legacy_detectors`를
  0.17로 조정하고 `immediate_disclosure_bypass_threshold`(0.85),
  `strong_single_bypass_threshold`(0.85)를 도입했다.
  - **전제**: 현재 YAML 가중치는 `theme_cluster=0.28`, `volume_news_combo=0.35`,
    `disclosure_pattern=0.20`, `legacy_detectors=0.17`(합 1.00)이다. 본 SPEC은 이
    값들을 의미적으로 유지하되, `disclosure_pattern`(0.20)을 `pattern_score`
    전용으로 좁히고 `immediate_disclosure`(0.35)를 신규 항으로 추가한다. 추가 후
    가중치 단순 합은 `0.28+0.35+0.20+0.35+0.17 = 1.35`로 1.0을 초과하므로,
    정규화 처리가 필수다(REQ-AI033-002, REQ-AI033-005 참조).
  - **전제**: 우회 임계값(`immediate_disclosure_bypass_threshold`)의 의미와 값은
    본 SPEC에서 변경하지 않는다. 본 SPEC은 우회 후 **저장되는 확률값**의 품질만
    개선한다.

---

## 환경 및 범위 (Environment & Scope)

- **언어/런타임**: Python 3.13+, Pydantic v2.
- **대상 파일** (총 2개 소스 + 1개 설정 + 1개 테스트):
  - `backend/app/surge_config/surge_settings.py` — `EnsembleWeightsConfig` 필드 추가,
    `validate_ensemble_weights` 갱신, `EnsembleConfig` 컨센서스 배율 필드 추가.
  - `backend/app/services/surge_detector.py` — `compute_ensemble_score()` 공식 및
    그룹 카운트 로직 수정.
  - `backend/app/surge_config/surge_detection.yaml` — `ensemble.weights`에
    `immediate_disclosure` 추가, `ensemble`에 4개 그룹 배율 추가.
  - `backend/tests/` — 가중치 정규화, 그룹 카운트, 하위 호환성 검증 테스트.
- **하위 호환성 [HARD]**: YAML에 `immediate_disclosure` 키가 없으면 시스템은
  반드시 정상 부팅해야 한다. 이 경우 폴백 정책은 REQ-AI033-004에서 정의한다.

---

## EARS 요구사항 (Requirements)

### REQ-AI033-001 — 즉각 공시 독립 가중치 필드 (Ubiquitous)

The system **shall** define an independent weight field `immediate_disclosure: float`
on `EnsembleWeightsConfig`, distinct from `disclosure_pattern`.

- `EnsembleWeightsConfig`는 `theme_cluster`, `volume_news_combo`,
  `disclosure_pattern`, `immediate_disclosure`, `legacy_detectors` 5개 float 필드를
  가져야 한다.
- `disclosure_pattern`은 더 이상 `immediate_disclosure_score`와 공유되지 않으며,
  `pattern_score`(공시 유형별 과거 급등 패턴) 기여 **전용**이다.
- 기본값: `immediate_disclosure = 0.35`. 단, 기본값은 YAML 값으로 오버라이드된다.

### REQ-AI033-002 — 앙상블 공식 분리 (Event-Driven)

**When** `compute_ensemble_score(candidate, config)` is invoked, the system
**shall** compute `weighted_sum` with `immediate_disclosure_score` and `pattern_score`
as separate weighted terms, **not** via `max(...)`.

- 신규 공식 (정규화 전 의미):
  ```
  weighted_sum =
        w.theme_cluster        * candidate.theme_cluster_score
      + w.volume_news_combo    * candidate.combo_score
      + w.disclosure_pattern   * candidate.pattern_score          # pattern 전용
      + w.immediate_disclosure * candidate.immediate_disclosure_score  # 신규 독립항
      + w.legacy_detectors     * candidate.legacy_score
  ```
- `best_disclosure_score = max(pattern_score, immediate_disclosure_score)`
  계산은 **제거**된다.
- 가중치 단순 합이 1.0을 초과(`0.28+0.35+0.20+0.35+0.17 = 1.35`)하므로, 실제
  적용되는 가중치는 REQ-AI033-005가 정의하는 정규화 규칙을 따른다.

### REQ-AI033-003 — 컨센서스 그룹 재산정 (State-Driven)

**While** counting active detector groups for the consensus multiplier, the system
**shall** treat `immediate_disclosure` as its own group, yielding up to 4 groups.

- 신규 그룹 정의:
  - `news`: `[theme_cluster_score, combo_score]`
  - `immediate_disclosure`: `[immediate_disclosure_score]` (신규 독립 그룹)
  - `disclosure`: `[pattern_score]` (pattern 전용)
  - `technical`: `[legacy_score]`
- `active_groups`(점수 > 0인 그룹 수)에 따른 배율:
  - `active_groups >= 4` → `consensus_multiplier_four_plus` (신규)
  - `active_groups == 3` → `consensus_multiplier_three_plus`
  - `active_groups == 2` → `consensus_multiplier_two`
  - `active_groups <= 1` → `1.00`
- `EnsembleConfig`는 신규 필드 `consensus_multiplier_four_plus: float`를 가져야 하며,
  기본값은 `consensus_multiplier_three_plus`와 일관되도록 설정한다(권장 `1.70`,
  최종값은 acceptance에서 검증).

### REQ-AI033-004 — 하위 호환성 폴백 (Unwanted Behavior)

**If** the `immediate_disclosure` key is absent from `ensemble.weights` in the YAML
configuration, **then** the system **shall** fall back to using the
`disclosure_pattern` weight value for `immediate_disclosure` and **shall not** raise
a configuration error.

- 구버전 YAML(`immediate_disclosure` 미지정)로 부팅 시 `immediate_disclosure`는
  `disclosure_pattern` 값으로 자동 설정되어야 한다.
- 이 폴백은 가중치 합산 검증(REQ-AI033-005)을 통과해야 한다.
- 마찬가지로 `consensus_multiplier_four_plus`가 YAML에 없으면 기본값을 사용하며
  오류를 내지 않아야 한다.

### REQ-AI033-005 — 가중치 정규화 및 검증 (Ubiquitous)

The system **shall** normalize the five ensemble weights so that the effective
weights applied in `compute_ensemble_score()` sum to 1.0, and the
`validate_ensemble_weights` validator **shall** be updated to include
`immediate_disclosure`.

- **검증자 갱신 [HARD]**: 현재 `validate_ensemble_weights`는 4개 필드 합이 1.0인지
  검사한다. 5개 필드를 검사하도록 갱신해야 한다. 단, 5개 필드의 단순 합은 1.0을
  초과하므로 다음 중 하나의 정규화 전략을 채택한다(택1, acceptance에서 확정):
  - (전략 A — 권장) **런타임 정규화**: `compute_ensemble_score()`가 5개 가중치를
    `sum`으로 나눈 정규화된 값을 사용한다. 이 경우 검증자는 5개 합이 0보다 큰지만
    확인한다(1.0 강제 폐기).
    - 검증 가능: 파미셀 재계산 시 정규화 가중치
      `imm = 0.35/1.35 = 0.2593`, `theme = 0.28/1.35 = 0.2074`,
      `weighted_sum = 0.7448×0.2074 + 0.82×0.2593 = 0.1545 + 0.2126 = 0.3671`,
      배율(2 그룹 1.30) → `0.4772`. (절대 비율은 0.20 단독보다 imm 비중이 상승)
  - (전략 B) **YAML 합산 1.0 강제 + 검증자 유지**: 운영자가 5개 가중치를 합 1.0이
    되도록 직접 재배분한다(예: `theme 0.21 / combo 0.26 / pattern 0.15 /
    imm 0.26 / legacy 0.12`). 검증자는 5개 합 == 1.0(±0.001)을 강제한다.
- 어떤 전략을 택하든, 최종 앙상블 점수는 `min(1.0, weighted_sum * multiplier)`로
  `[0.0, 1.0]` 범위에 유지되어야 한다.
- @MX:ANCHOR(가중치 합산 검증)는 새 필드를 반영하도록 갱신되어야 한다.

---

## 비목표 (Non-Goals)

본 SPEC은 다음을 **명시적으로 다루지 않는다**:

- **신규 탐지기 추가**: `immediate_disclosure` 탐지기는 이미 SPEC-AI-012에
  존재한다. 탐지 로직은 변경하지 않는다.
- **우회 임계값 변경**: `immediate_disclosure_bypass_threshold`(0.85),
  `strong_single_bypass_threshold`(0.85)의 값과 의미는 변경하지 않는다.
- **공시 역신호 필터 변경**: SPEC-AI-028의 `DisclosureTypeFilterConfig`(exclusion/
  penalty 패턴) 로직은 변경하지 않는다. `immediate_disclosure_score`는 필터 적용
  이후의 값을 그대로 사용한다.
- **적응형 임계값 변경**: SPEC-AI-029의 `AdaptiveThresholdConfig` 로직은 변경하지
  않는다. 본 SPEC이 개선하는 것은 적응형 임계값과 비교되는 **확률값의 품질**이다.
- **포지션 사이징/매매 엔진 변경**: `surge_trading_service.py`의 매수/매도 로직,
  `max_open_positions`, `position_pct` 등은 변경하지 않는다.
- **레짐 임계값 재조정**: SPEC-AI-017의 `regime_thresholds`(BULL/SIDEWAYS/BEAR) 값은
  변경하지 않는다.
- **새 API 엔드포인트 추가**: 본 SPEC은 내부 스코어링 로직만 변경하며 외부 인터페이스를
  추가하지 않는다.

---

## 구현 범위 (Implementation Scope)

| 파일 | 변경 내용 | 관련 REQ |
|------|-----------|----------|
| `backend/app/surge_config/surge_settings.py` | `EnsembleWeightsConfig`에 `immediate_disclosure: float` 추가; `EnsembleConfig`에 `consensus_multiplier_four_plus: float` 추가; `validate_ensemble_weights` 5개 필드 반영 + 정규화 전략 적용; 하위 호환 폴백(`immediate_disclosure` 미지정 시 `disclosure_pattern` 값 사용) | 001, 003, 004, 005 |
| `backend/app/services/surge_detector.py` | `compute_ensemble_score()`에서 `best_disclosure_score = max(...)` 제거; `immediate_disclosure`/`pattern` 분리 항 적용; `detector_groups` 4개 그룹화; 4개 그룹 배율 분기 추가 | 002, 003 |
| `backend/app/surge_config/surge_detection.yaml` | `ensemble.weights.immediate_disclosure: 0.35` 추가(전략 A 기준); `ensemble.consensus_multiplier_four_plus` 추가; 주석에 SPEC-AI-033 명시 | 001, 003 |
| `backend/tests/` | 가중치 정규화 검증, 4개 그룹 컨센서스 배율, 파미셀 재현 사례(0.4843→상향), 하위 호환 폴백(키 부재 시 무오류 부팅) 테스트 | 전체 |

### MX 태그 대상

- `compute_ensemble_score()`: 공식 분리로 @MX:NOTE 갱신(SPEC-AI-018 REQ-009 그룹화
  설명 → 4개 그룹 + immediate 독립화로 업데이트). 함수 fan_in >= 3이면 @MX:ANCHOR 유지.
- `validate_ensemble_weights`: @MX:ANCHOR + @MX:REASON 갱신(정규화 전략 반영, 5개
  필드 검증).

---

## 언어 정책

- **본문/주석**: 한국어 (`code_comments: ko`)
- **코드 식별자**: 영어 (`immediate_disclosure`, `consensus_multiplier_four_plus`,
  `compute_ensemble_score`, `EnsembleWeightsConfig` 등)
- **REQ ID**: `REQ-AI033-NNN`
