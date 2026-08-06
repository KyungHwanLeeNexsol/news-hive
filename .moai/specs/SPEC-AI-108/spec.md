---
id: SPEC-AI-108
title: "급등예측 지평 시그니처별 정밀도 분리 측정 — SPEC-AI-100 임계값 아키텍처 실증 근거 확립"
version: "0.1.0"
status: in-progress
created: 2026-08-06
updated: 2026-08-06
author: Nexsol
priority: High
phase: "backend surge-detection v0.1.0"
module: "backend/app/services"
lifecycle: spec-anchored
tags: "surge-detection, horizon-signature, precision-diagnostic, evaluation-metric, shadow-observation, backend"
tier: M
related_specs: [SPEC-AI-070, SPEC-AI-075, SPEC-AI-080, SPEC-AI-083, SPEC-AI-093, SPEC-AI-095, SPEC-AI-100, SPEC-AI-101, SPEC-AI-106]
---

# SPEC-AI-108: 급등예측 지평 시그니처별 정밀도 분리 측정

## HISTORY

- 2026-08-06 v0.1.0 (draft): 외부 구조진단(GPT 비평)이 "익일예측(next-day)"과
  "장중 조기경보(intraday early-warning)"를 완전히 분리된 두 모델/파이프라인으로
  재설계해야 한다고 주장한 데 대한 응답으로 작성됐다. research 결과, 그 주장의
  핵심 전제 대부분이 **이미 5개 선행 SPEC(080/083/100/101/106)으로 해소되었음**을
  확인했다 — 특히 SPEC-AI-100 §Decisions D1이 "완전 분리형(옵션 a)"을 이미 검토·평가한
  뒤 **명시적으로 기각**하고 "지평 태깅형 단일 파이프라인(옵션 b)"을 채택했으며, 이
  결정의 근거(5개 SPEC의 수동 튜닝 이력 무효화, 병합/중복제거 복잡도, 섀도우 검증
  가중치)는 이 세션의 재검토로도 여전히 유효함을 확인했다. 남은 진짜 격차는
  "완전 분리가 필요한가"가 아니라 — **SPEC-AI-100이 도입한 지평 시그니처 taxonomy
  (`same_day_dominant`/`next_day_dominant`/`multi_day_dominant`/`mixed`)가 실제로
  서로 다른 예측 정밀도와 상관관계가 있는지 단 한 번도 측정된 적이 없다**는 것이다.
  본 SPEC은 신규 아키텍처나 완전 분리를 제안하지 않고, 이미 수집되고 있는 데이터
  (SPEC-AI-100의 `horizon_labels`, SPEC-AI-070의 surge_basis attribution 패턴,
  SPEC-AI-101의 신호 단위 EOD 최대수익률)만으로 이 taxonomy의 실증적 유효성을
  측정하는 순수 관측 증분을 제안한다 — SPEC-AI-100 Open Question 2(지평별 임계값
  수치 확정)와 향후 "완전 분리 재검토" 여부 판단에 필요한 첫 번째 증거를 만든다.
  **정직한 평가**: 사용자가 명시적으로 물었던 "GPT 권고 전부를 적용하면 도움이
  되는가"에 대한 이 영역의 답은 부분적으로 "아니오"에 가깝다 — 제안된 작업의
  대부분은 이미 완료되었고, 실제로 남은 작업은 GPT 비평이 제시한 규모보다 훨씬
  작다.
- 2026-08-06 v0.1.0 (draft, plan-auditor iteration-1 FAIL 대응): iteration-1
  독립 감사(score 0.625, MP-2 Must-Pass firewall FAIL)가 4건의 critical 결함을
  적발해 전량 수정했다 — (D1) `surge_basis`의 레거시 탐지기 병합 경로가
  `"legacy"`를 append하나 `compute_horizon_signature()`의 앙상블 키는
  `"legacy_detectors"`라는 2번째 라벨 불일치를 최초 발견(§Context [E-6] 신설);
  (D2) 과거 Open Question 1(`disclosure_pattern`/`immediate_disclosure` 라벨
  불일치)을 이 세션의 grep으로 즉시 해소해 REQ-AI108-001 확정 요구사항으로
  승격(Open Questions에서 제거); (D3) §Context [E-2]의 "컴포넌트 점수는
  전부 영속화되지 않는다"는 진술이 사실과 달랐음을 `surge_candidate_to_signal_metadata()`
  (`surge_detector.py:3052-3067`) 직접 확인으로 정정(실제로는 7개 중 5개가
  영속화됨) — §Decisions D1에 "왜 하이브리드가 아닌 전체 attribution인가"의
  재정당화 근거(기각한 대안 2)를 신설하고 REQ-AI108-002를 같은 근거로 재작성;
  (D4) REQ-AI108-007/AC-108-008의 GEARS 오용(이산 예외 이벤트에 While/Where
  사용)을 When(Event-Driven)으로 수정. 4건 모두 코드 직접 대조로 재검증했다.
- 2026-08-06 v0.1.0 (draft, plan-auditor iteration-2 FAIL 대응): iteration-2
  독립 감사가 3건의 결함을 적발했다 — (D1, critical) §Context [E-2]와
  REQ-AI108-002가 iteration-1 D3 수정 과정에서 "컴포넌트 점수는 7개 중
  5개만 영속화되고, 나머지 3개는 영속화되지 않는다"는 산술 자기모순
  (5+3=8≠7)을 도입했음을 발견 — §Decisions D1 "기각한 대안 2"(5개 원시
  점수 필드가 7개 앙상블 키 중 4개만 커버, `disclosure_pattern`은
  `pattern_score`/`immediate_disclosure_score` 2개 원시 필드의 `max()`이므로
  나머지 3개 앙상블 키만 원시 필드 부재)의 정확한 진술과 일치하도록 두
  passage를 재작성해 정정했다; (D2, major) acceptance.md §A AC 매트릭스에서
  AC-108-003(앙상블 7개 키 밖 `surge_basis` 멤버 무시 — §Decisions D2 스코프
  경계)이 REQ-AI108-002(attribution 원칙 계승)로 잘못 매핑되어 있던 것을
  실제 소유 요구사항인 REQ-AI108-001로 재매핑했다; (D3, minor) AC-108-003의
  "the system shall ... shall not ..." 이중 modal 오용을 단일 shall not
  절로 재작성해 GEARS 정규 문장으로 정정했다. (D4는 non-blocking으로
  auditor가 수정 불요를 확인 — 변경 없음.)

## 선행 SPEC

- **SPEC-AI-100** (완료, Tier L): 지평 인식 임계값 선택 아키텍처의 원 소유 SPEC.
  `compute_horizon_signature()`, `horizon_labels` 설정, `select_effective_threshold()`,
  섀도우 비교(`run_horizon_shadow_comparison`)를 도입했다. **§Decisions D1이 "완전
  분리형" 옵션을 이미 검토 후 기각**했다 — 본 SPEC은 이 결정을 재론하지 않는다.
  Open Question 2("지평별 임계값의 정확한 수치")는 여전히 미해결이며, 본 SPEC의
  산출물이 그 판단의 증거 입력이 된다.
- **SPEC-AI-101** (완료): `SurgeSignalForwardOutcome`(신호가 대비 EOD 최대수익률,
  `forward_max_return_pct`) 신규 테이블 + SPEC-AI-100 섀도우 관측 활성화
  (`shadow_mode_enabled: true`, `enabled: false` 유지) + 전환 게이트 3요건 판정
  함수(`check_horizon_transition_readiness`)의 소유 SPEC. 본 SPEC은 이 신호 단위
  outcome 테이블을 정밀도 분리 측정의 "실제(actual)" 입력으로 재사용한다 —
  테이블/컬럼 신규 추가 없음.
- **SPEC-AI-070** (draft, 미배포): 탐지기 기여도 검증 SPEC. "컴포넌트 점수는
  영속화되지 않으므로 정확한 재채점(re-score)은 불가능하다 — 기여도 분석은
  `surge_basis` 멤버십 귀속(attribution)이어야 한다"는 제약과 방법론을 최초로
  확립했다. 본 SPEC은 이 **attribution-not-re-score 원칙을 지평 시그니처 재구성에
  그대로 재사용**한다 — 컴포넌트 점수 재구성을 시도하지 않는다.
- **SPEC-AI-093/095**: `high_change_rate` 실측 수집 + `high_based_recall/precision`
  병렬 노출. T-1 종가 기준 병렬 지표를 확립한 선례이며, "동결 + 병렬 추가"
  설계 원칙(D2)을 본 SPEC도 계승한다 — 단, 본 SPEC이 다루는 것은 "T-1 종가 기준
  vs 고가 기준" 축이 아니라 "어떤 탐지기 부류(같은 T-1→T 지평 내에서)가 신호를
  발화했는가" 축이며, 두 축은 서로 직교한다(§Context에서 명시적으로 구분한다).
- **SPEC-AI-075/080/083**: 평가 계층의 지평 배제 패턴(`_is_near_limit_up_carry_signal`,
  `_is_same_day_event_horizon_signal`) 소유 SPEC. 이 패턴들은 `predicted_set`에서
  일부 신호를 **배제**해 별도 서브지표로 분리한다. 본 SPEC은 이 배제 로직을 소비만
  하며(무수정), `predicted_set`에 **남아 있는** 신호만을 대상으로 지평 시그니처
  분리 정밀도를 측정한다 — 즉 본 SPEC의 측정 대상은 이미 표준 T-1→T 지평으로
  확정된 신호 집합이다(§Context "핵심 정정" 참고).
- **SPEC-AI-106** (draft, 미배포): SPEC-AI-100/101 판정 함수(`check_horizon_transition_readiness`)를
  기존 일일 평가 잡에 로그로 배선하는 병렬 SPEC. 본 SPEC과 동일하게
  `evaluate_surge_predictions()`/`_run_surge_verify_predictions()`에 격리된 진단
  블록을 추가하는 패턴을 쓰지만, 다루는 데이터가 다르다(106=섀도우 qualified 집합
  변화폭, 108=실제 outcome 기반 정밀도). 두 SPEC은 서로 독립적으로 구현 가능하며
  어느 순서로 배포되어도 충돌하지 않는다(§Decisions D3).

### amendment 여부

본 SPEC은 어떤 선행 SPEC의 amendment도 아니다. `amendment_of:` 없이 `related_specs`로만
참조하는 신규 SPEC이다.

## Context / Problem

### 문제 1 — 외부 비평의 "완전 분리" 전제는 이미 검토·기각된 결정이다

원 위임 프롬프트가 인용한 외부 구조진단은 "익일 예측"과 "장중 조기경보"를
"완전히 별개의 모델/파이프라인"으로 재설계해야 한다고 주장했다. 이 주장을 코드로
직접 검증한 결과, 이 정확한 질문이 이미 SPEC-AI-100(2026-08-03~04, Tier L)에서
다뤄졌다:

- SPEC-AI-100 §Decisions D1은 두 옵션을 명시적으로 비교했다 — 옵션 (a) 완전
  분리형(지평별 독립 가중치 세트 + 독립 임계값 세트)과 옵션 (b) 지평 태깅형
  단일 파이프라인(가중합 수식은 무수정, 임계값 선택 단계만 지평 인식으로 확장).
- **옵션 (a)는 명시적으로 기각됐다** — 근거: "5개 SPEC(017/018/039/050/065)의
  수동 튜닝 이력을 무효화하고, 한 종목이 여러 지평의 시그널을 동시에 받을 때의
  병합/중복제거 로직을 새로 발명해야 하며, 섀도우 모드 검증이 구조적으로 더
  무겁다"(design.md §C 트레이드오프 표).
- 이 근거는 이 세션의 재검토로도 여전히 유효하다 — 재검토 시점(2026-08-06)까지
  탐지기 가중치 재조정 이력이 추가로 발생하지 않았고, 다중 지평 동시 발화 문제도
  해소되지 않았다.

따라서 "완전 분리해야 하는가"라는 질문 자체는 **이미 답변된 결정**이며, 본 SPEC이
재론하거나 뒤집지 않는다. 이 사실을 사용자에게 정직하게 보고하는 것 자체가 본
SPEC의 research 산출물 중 하나다.

### 문제 2 — 지평 taxonomy가 실제로 정밀도 차이를 만드는지 단 한 번도 측정된 적 없다

SPEC-AI-100이 도입한 지평 시그니처(`compute_horizon_signature()`, 4개 값:
`same_day_dominant`/`next_day_dominant`/`multi_day_dominant`/`mixed`)는 이미
가중치 선택 아키텍처의 핵심 축으로 배선되어 있으나, **그 taxonomy 자체가
실제로 서로 다른 예측 정밀도를 가지는지를 측정하는 코드는 어디에도 없다**:

- `run_horizon_shadow_comparison()`(SPEC-AI-100/101)은 "기존 임계값 경로와 신규
  지평 인식 경로의 qualified **집합**이 얼마나 다른가"만 측정한다 — 두 경로가
  실제로 얼마나 정확했는지(precision)는 다루지 않는다.
- `evaluate_high_based_outcomes()`/`high_based_recall`(SPEC-AI-093/095)은 T-1
  종가 대비 고가 기준의 병렬 지표이지만, 지평 시그니처로 세분화되지 않는다 —
  집계 전체(모든 signal_type=="surge_candidate")에 대한 단일 값이다.
  `SurgeSignalForwardOutcome`/`forward_max_return_pct`(SPEC-AI-101)도 마찬가지로
  신호 단위 값은 있으나 지평 시그니처별로 묶어 집계하는 로직이 없다.
- `check_horizon_transition_readiness()`(SPEC-AI-101)의 3요건(관측 거래일수/레짐
  커버리지/qualified 변화폭)은 "안전하게 전환할 수 있는가"를 판정할 뿐, "전환이
  실제로 예측을 더 정확하게 만드는가"는 판정하지 않는다 — SPEC-AI-106의 plan.md
  §C 3항이 이미 이 한계를 명시적으로 인정했다("구조 요건은 필요조건이지
  충분조건이 아니다").

즉 SPEC-AI-100의 전체 아키텍처는 "지평이 다르면 임계값도 달라야 한다"는 **가설**
위에 구축되었으나, 그 가설을 실증하는 측정은 아직 존재하지 않는다. SPEC-AI-100
Open Question 2("지평별 임계값의 정확한 수치")가 영구히 placeholder 값
(기존 `regime_thresholds`와 동일)에 머물러 있는 근본 원인이 바로 이 증거 부재다 —
사람이 판단할 근거 데이터 자체가 생산되고 있지 않다.

### 핵심 정정 — 본 SPEC이 측정하는 것은 "같은 지평 내 탐지기 부류 분리"이지 "같은-당일 vs 익일" 자체가 아니다

`predicted_set`(2단계, `evaluate_surge_predictions`)은 SPEC-AI-075/080이 확립한
배제 패턴에 의해 **이미** near_limit_up_carry(D 자신의 연속성 예측, T→T)와
same-day-event 즉시발화 신호(장중 접수, T→T)를 별도 서브지표로 분리·배제한다.
따라서 `predicted_set`에 남은 신호는 정의상 전부 **동일한 표준 T-1→T 지평**을
예측 대상으로 삼는다 — 예측 **대상일**의 축은 이미 균질하다.

본 SPEC이 세분화하는 축은 다르다: 그 T-1→T 예측 신호들 중 **어떤 탐지기 부류가
발화에 기여했는가**(SPEC-AI-100의 `horizon_labels` 분류 — `volume_breakout`/
`disclosure_pattern`/`volume_news_combo`처럼 "빠른 촉매형"으로 라벨링된 탐지기가
발화한 신호 vs `theme_cluster`/`news_delayed`처럼 "느린 다일형"으로 라벨링된
탐지기가 발화한 신호)로 신호를 분류해, 그 두 부류의 실제 정밀도가 다른지를
묻는다. 이것이 정확히 SPEC-AI-100의 임계값 선택 아키텍처가 전제하는 축이며,
지금까지 측정된 적 없는 그 축이다. 이 구분을 spec.md/acceptance.md 전체에서
일관되게 유지한다 — "same-day 예측 vs next-day 예측"(이미 해소됨, 080/083/075
소유)과 "same_day_dominant 지평 시그니처 vs next_day_dominant 지평 시그니처
탐지기 부류별 정밀도"(본 SPEC이 처음 측정)를 혼동하지 않는다.

### 검증된 사실 (코드 직접 확인, 2026-08-06)

- [E-1] `compute_horizon_signature(candidate, config)`(`surge_detector.py:1922`)는
  **살아있는 `SurgeCandidate` 객체의 컴포넌트 점수 필드**(`theme_cluster_score`,
  `combo_score`, `pattern_score`/`immediate_disclosure_score`의 max, `legacy_score`,
  `news_delayed_score`, `volume_breakout_score`, `momentum_continuation_score`)를
  입력으로 받는다 — 7개 앙상블 가중합 키에 한정된다. 점수>0인 키의 `horizon_labels`
  라벨 집합을 만들어, 집합이 비면 `multi_day_dominant`, 1개면
  `{label}_dominant`, 2개 이상이면 `mixed`를 반환한다(`:1961-1966`).
- [E-2] **5개의 원시 점수 필드가 영속화되지만, 이는 7개 앙상블 키 중 4개
  (`theme_cluster`/`volume_news_combo`/`disclosure_pattern`/`legacy_detectors`)만
  커버한다**(코드 직접 확인, 2026-08-06 — 이전 초안의 "전부 영속화되지 않는다"는
  진술은 부정확했다). `disclosure_pattern`은 `pattern_score`와
  `immediate_disclosure_score` 2개 원시 필드의 `max()`이기 때문이다. 나머지
  3개 앙상블 키(`news_delayed`/`volume_breakout`/`momentum_continuation`)는
  대응하는 원시 필드가 전혀 영속화되지 않는다. `surge_candidate_to_signal_metadata()`(`surge_detector.py:3052-3067`,
  `fund_manager.py:1414`에서 표준 신호 생성 경로로부터 호출됨)는
  `FundSignal.surge_metadata`에 최종 `surge_probability_score`/`surge_basis`
  외에도 `theme_cluster_score`/`combo_score`/`pattern_score`/
  `immediate_disclosure_score`/`legacy_score` **5개**를 함께 저장한다. 반면
  `news_delayed_score`/`volume_breakout_score`/`momentum_continuation_score`
  **3개**는 이 함수에 없다 — 어디에도 영속화되지 않는다. 그럼에도
  `compute_horizon_signature()`를 평가 시점에 **그대로 재호출하는 것은
  여전히 불가능**하다 — 그 함수는 7개 키 전부의 점수를 동시에 입력으로
  요구하는데(§Context [E-1]), 3개 키의 입력값이 원천적으로 존재하지 않기
  때문이다(부분 가용 ≠ 재호출 가능). §Decisions D1이 이 정정된 사실 위에서
  "5개는 직접 읽고 3개만 attribution하는 하이브리드" 대신 "7개 전부
  attribution"을 채택하는 이유를 별도로 설명한다.
- [E-3] `evaluate_surge_predictions()`의 2단계 쿼리(`surge_evaluation_service.py:873-888`)는
  이미 `FundSignal.surge_metadata`를 함께 select한다(`signal_rows`) — `surge_basis`를
  얻기 위한 추가 쿼리가 불필요하다.
- [E-4] `_persist_signal_forward_outcomes()`(SPEC-AI-101,
  `surge_evaluation_service.py:701`)는 동일한 `signal_rows`를 재사용해(재조회
  금지 원칙 준수) `SurgeSignalForwardOutcome`에 신호 단위
  `forward_max_return_pct`를 upsert한다 — 이 함수는 `(trading_date,
  fund_signal_id)` UNIQUE로 멱등이다.
- [E-5] `horizon_labels`/`thresholds` 설정(`surge_detection.yaml:96-129`)은
  `horizon_aware_thresholds.enabled`/`.shadow_mode_enabled` 값과 무관하게
  **항상 읽을 수 있다** — YAML에 무조건 존재하는 정적 설정이다. 따라서 본
  SPEC의 측정 로직은 `enabled`/`shadow_mode_enabled` 상태에 의존하지 않고
  항상 동작할 수 있다.
- [E-6] **`surge_basis` 문자열-앙상블 키 정규화 매핑을 코드 대조로 확정했다**
  (2026-08-06 — 과거 초안의 Open Question 1을 이 세션에서 해소). 신호 생성
  경로가 `active_detectors`(=`surge_basis`)에 append하는 문자열 중 2개가
  `compute_horizon_signature()`의 앙상블 키와 다르다: `immediate_disclosure`
  경로(`surge_detector.py:1827`)는 `"immediate_disclosure"`를 append하지만
  앙상블 키는 `"disclosure_pattern"` 1개뿐이다(`:1945`,
  `max(pattern_score, immediate_disclosure_score)`로 두 경로를 하나로 병합);
  레거시 탐지기 병합 경로(`:2729-2730`)는 `"legacy"`를 append하지만 앙상블
  키는 `"legacy_detectors"`다(`:1950`). 확정된 정규화 매핑은
  `{"immediate_disclosure": "disclosure_pattern", "legacy":
  "legacy_detectors"}`이며, `disclosure_pattern` 경로(`:1620`) 자신은 이미
  `"disclosure_pattern"`을 append하므로 매핑 불필요. 나머지 5개 앙상블 키
  (`theme_cluster`/`volume_news_combo`/`news_delayed`/`volume_breakout`/
  `momentum_continuation`)는 `surge_basis` 문자열과 1:1 동일하다
  (`surge_detector.py:762,963,1309,2235,2589-2590,2600-2601` 등에서 확인) —
  정규화 대상은 위 2건뿐이다.

## Goals

1. 지평 시그니처(`same_day_dominant`/`next_day_dominant`/`multi_day_dominant`/`mixed`)
   taxonomy가 실제로 서로 다른 예측 정밀도와 상관관계가 있는지 측정하는 순수
   관측 진단을 추가한다 — SPEC-AI-100의 임계값 선택 아키텍처가 전제하는 가설의
   첫 실증 데이터를 만든다.
2. 이 측정은 SPEC-AI-070이 확립한 "attribution over `surge_basis` membership,
   not re-score" 원칙을 그대로 재사용한다 — 컴포넌트 점수 재구성을 시도하지
   않는다.
3. 이 측정은 이미 존재하는 데이터(SPEC-AI-100의 `horizon_labels`, SPEC-AI-101의
   `SurgeSignalForwardOutcome.forward_max_return_pct`)만 재사용한다 — 신규
   테이블/컬럼/마이그레이션을 도입하지 않는다.
4. 측정 결과는 SPEC-AI-100 Open Question 2(지평별 임계값 수치 확정)와 향후
   "완전 분리 재검토" 여부 판단(SPEC-AI-100 D1) 두 결정의 증거 입력으로만
   문서화한다 — 이 SPEC 자신은 어느 결정도 내리지 않는다.
5. 사용자에게 "GPT 비평 대부분은 이미 5개 SPEC으로 해소되었다"는 사실을
   정직하게 보고한다 — 남은 작업의 실제 규모가 원 요청보다 훨씬 작음을 명시한다.

## Non-Goals

### Out of Scope — 완전 분리 모델/파이프라인 재도입

- SPEC-AI-100 §Decisions D1의 "완전 분리형(옵션 a) 기각" 결정을 재론하거나
  뒤집지 않는다. 본 SPEC의 측정 결과가 향후 그 재검토에 참고 자료가 될 수는
  있으나, 본 SPEC 자신은 그 판단을 내리지 않는다.
- 지평별 독립 탐지기 가중치 세트, 독립 후보 생성 경로, 독립 스코어링 함수를
  신설하지 않는다.

### Out of Scope — 지평별 임계값 수치 튜닝

- `ensemble.horizon_aware_thresholds.thresholds` 블록의 실제 수치(현재
  `regime_thresholds`와 동일한 placeholder)를 변경하지 않는다. SPEC-AI-100
  Open Question 2는 여전히 미해결로 남긴다 — 본 SPEC은 그 판단에 쓰일 증거만
  생산한다.

### Out of Scope — `horizon_aware_thresholds.enabled`/`.shadow_mode_enabled` 전환

- 두 값 모두 SPEC-AI-101이 남긴 상태(`enabled: false`, `shadow_mode_enabled:
  true`)를 그대로 유지한다. 본 SPEC의 측정 로직은 이 두 값과 무관하게 항상
  동작한다(§Context [E-5]) — 전환 여부와 결합하지 않는다.

### Out of Scope — 스캔 주기/탐지 타이밍 변경

- 장중 재스캔 빈도, 이벤트 구동 즉시발화 트리거는 SPEC-AI-083 소유이며 본
  SPEC은 무변경이다. "언제 후보를 생성하는가"는 본 SPEC의 관심사가 아니다 —
  "이미 생성된 후보가 어떤 탐지기 부류인지"만 다룬다.

### Out of Scope — 신규 DB 테이블/컬럼/마이그레이션

- `SurgeSignalForwardOutcome`, `FundSignal.surge_metadata`, `surge_detection.yaml`의
  `horizon_labels`/`thresholds` 설정을 있는 그대로 재사용한다. 신규 alembic
  리비전을 추가하지 않는다.

### Out of Scope — 신규 알림 채널

- Telegram, 신규 API 엔드포인트, 대시보드를 추가하지 않는다. SPEC-AI-106
  §Decisions D3("구조화 로그로 충분")의 최소주의 선례를 그대로 따른다 — 구조화
  로그 1줄로 노출한다.

### Out of Scope — SPEC-AI-100/101 판정·집계 로직 재구현

- `compute_horizon_signature()`, `select_effective_threshold()`,
  `run_horizon_shadow_comparison()`, `check_horizon_transition_readiness()`,
  `evaluate_high_based_outcomes()`, `_persist_signal_forward_outcomes()`의
  내부 로직을 수정하거나 복제하지 않는다. 본 SPEC은 이 함수들이 이미 생산한
  데이터를 **읽기만** 한다(단, `compute_horizon_signature()` 자체는 사후 재호출이
  불가능하므로 — §Context [E-2] — 그 알고리즘을 `surge_basis` 입력용으로
  재구성한 **별개의 신규 함수**를 추가한다. 이는 기존 함수의 수정이 아니다).

### Out of Scope — 분/시간 단위 세분 지평 라벨(30/60/120분)

- SPEC-AI-101 research.md §2가 이미 확인했듯 이 코드베이스에는 분봉/장중
  시계열 가격 수집 인프라가 없다. 본 SPEC도 이 인프라를 신설하지 않는다 —
  기존 4개 지평 시그니처 값만 사용한다.

## Decisions

### D1 — 지평 시그니처는 `surge_basis` 귀속으로 사후 재구성한다, `compute_horizon_signature()` 재호출은 불가능하다

§Context [E-2]가 확인했듯 컴포넌트 점수 7개 중 3개(`news_delayed_score`/
`volume_breakout_score`/`momentum_continuation_score`)는 영속화되지 않으므로
`compute_horizon_signature()`를 평가 시점에 그대로 재호출할 수 없다 — 7개
전부가 동시에 필요한데 3개의 입력값이 원천적으로 없다. 대신 SPEC-AI-070이
확립한 attribution 원칙을 재사용해, `surge_metadata.surge_basis` 리스트
멤버십을 "점수>0" 조건과 동치로 취급하는 **신규 별개 함수**
(`_reconstruct_horizon_signature_from_basis`)를 추가한다 — `compute_horizon_signature()`
자체는 무수정 유지한다.

기각한 대안 1 — 신호 생성 시점(살아있는 `SurgeCandidate` 존재 시점)에
`compute_horizon_signature()`를 즉시 호출해 그 결과값을 `surge_metadata`에
신규 필드로 기록. 이는 쓰기 경로(신호 생성 로직) 변경을 요구해 [X-2] 회귀
표면을 넓히고, 이미 배포된 과거 신호에는 소급 적용할 수 없어(백필 금지 관례,
SPEC-AI-071/076/093 계승) 즉시 관측을 시작할 수 없다. 사후 재구성(읽기 전용)이
쓰기 경로 무변경 + 즉시 관측 가능 두 이점을 모두 만족해 채택한다.

기각한 대안 2 — 영속화된 5개 원 점수 필드(`theme_cluster_score`/`combo_score`/
`pattern_score`/`immediate_disclosure_score`/`legacy_score`, 앙상블 키
기준으로는 `theme_cluster`/`volume_news_combo`/`disclosure_pattern`/
`legacy_detectors` 4개를 커버)는 `surge_metadata`에서 직접 읽어 `점수>0`으로
판정하고, 영속화되지 않은 나머지 앙상블 키 3개(`news_delayed`/
`volume_breakout`/`momentum_continuation`)만 `surge_basis` attribution으로
채우는 하이브리드 방식. 이 방식은 4개 앙상블 키에 한해 라이브 함수와
완전히 동일한 `점수>0` 게이트를 재현할 수 있어 이론상 더 정확해 보이지만
기각한다 — 근거: (a) `surge_metadata`에 점수가 기록되는 시점(신호 생성)과
`surge_basis`에 탐지기 이름이 append되는 조건은 탐지기별로 서로 다른 코드
경로에서 독립적으로 결정된다(예: legacy는 `num_triggered>=1`일 때만
`legacy_score_map`에 등재되어 append되지만, 다른 탐지기는 각기 다른 병합
블록에서 append 여부를 결정한다 — §Context [E-6]). 두 판정 기준이 우연히
일치하지 않는 예외 케이스가 발생하면, 하이브리드 경로는 4개 앙상블 키에서는
"점수 기준", 3개 앙상블 키에서는 "attribution 기준"이라는 서로 다른 정의의
"활성" 판정이 하나의 결과값에 섞여 무엇을 측정하는지 불명확해진다
(§Decisions D2가 이미 경계한 것과 동일한 문제 — "이 진단이 실제로 무엇을
측정하는가"). (b) 단일 attribution 경로 유지가 Simplicity
Ladder상 더 단순하고(하이브리드 이중 분기 구현/테스트 불필요), SPEC-AI-070
원칙을 예외 없이 일관 재사용해 감사 추적의 설계 계보를 깨끗하게 유지한다.
따라서 7개 키 전부에 대해 단일 attribution 경로를 적용한다 — REQ-AI108-002가
이 결정을 구속력 있는 요구사항으로 명시한다.

### D2 — 재구성 범위는 앙상블 가중합 7개 키로 한정한다, 독립/우회 탐지기는 무시한다

`compute_horizon_signature()`의 라이브 로직은 구조적으로 7개 앙상블 가중합
키(`theme_cluster`/`volume_news_combo`/`disclosure_pattern`/`legacy_detectors`/
`news_delayed`/`volume_breakout`/`momentum_continuation`)만 본다 — 독립/우회
탐지기(near_limit_up_carry, weekend_gap_up, insider_purchase, theme_group_carry,
forum_mention_surge, group_cascade, bollinger_squeeze, volume_anomaly 등)의
발화 여부는 라이브 함수 자체가 구조적으로 볼 수 없다. 사후 재구성 함수도
동일하게 이 7개 키에 없는 `surge_basis` 멤버는 무시해야 라이브 로직과
동등하다(동등성 보존, PRESERVE 정신 준수).

기각한 대안 — `surge_basis`의 모든 멤버를 지평 시그니처 계산에 포함(우회
탐지기 포함). 이는 라이브 `compute_horizon_signature()`가 실제로 계산했을
값과 사후 재구성 값이 달라지는 결과를 낳아, "이 진단이 실제로 무엇을
측정하는가"에 대한 정의가 모호해진다 — 기각한다.

### D3 — 신규 진단은 `evaluate_surge_predictions()` 내부에 읽기 전용 격리 블록으로 추가한다, SPEC-AI-106과 독립적으로 배포 가능하다

`SurgeSignalForwardOutcome`은 신호가 이미 upsert된 이후 값을 재조회(같은
`trading_date` + `signal_rows`의 `fund_signal_id` 집합으로 한정된 소규모
SELECT, 예측 건수가 일 3~9건이므로 비용 무시 가능)해 사용한다 — 기존
`_persist_signal_forward_outcomes()`의 시그니처나 반환값은 변경하지 않는다
(무터치 PRESERVE). 이 진단은 순수 읽기(신규 쓰기 없음)이므로 실패 격리가
단순하다. SPEC-AI-106(같은 잡에 다른 진단 블록을 추가)과는 데이터가
다르고(106=섀도우 qualified 집합 변화폭, 108=실제 outcome 기반 정밀도)
서로 참조하지 않으므로, 두 SPEC은 어느 순서로 배포되어도 충돌하지 않는다.

기각한 대안 — `_persist_signal_forward_outcomes()`의 반환값을 확장(집합 →
신호별 매핑)해 재조회를 피함. 반환 타입 변경은 기존 호출부(테스트 포함)의
계약을 바꾸므로, 작은 성능 이득(예측 건수가 적어 재조회 비용이 무시 가능한
상황에서) 대비 회귀 표면이 더 크다고 판단해 기각한다(Simplicity Ladder —
기존 함수 무터치가 더 단순).

### D4 — 정밀도만 산출한다, 지평 시그니처별 recall은 산출하지 않는다

`predicted_set`(신호)은 지평 시그니처로 자연 분류되지만, `actual_set`
(실제 급등주, `SurgeActualOutcome`)은 종목·날짜 단위일 뿐 어떤 탐지기가
그 종목을 잡았어야 했는지에 대한 정보가 없다 — "지평 시그니처별 recall"을
정의하려면 실제 급등주 각각에 대해 "어느 지평 시그니처였어야 했는가"라는
반사실적(counterfactual) 판단이 필요한데 이는 정의 불가능하다. 반면
정밀도(TP/predicted_count)는 "우리가 실제로 발화한 신호가 어느 지평
시그니처였고, 그 신호가 맞았는가"만 물으므로 잘 정의된다. 따라서 본 SPEC은
정밀도만 산출한다.

기각한 대안 — recall도 강제로 산출(예: 실제 급등주 중 아무 지평에도 안
잡힌 것은 제외). 이는 지평 시그니처별 recall이라는 이름의 다른 지표(실질은
"scannable 방식의 지평별 재해석")를 만들어내 혼동을 유발하므로 기각한다.

## Requirements

### REQ-AI108-001 (P0, Event-Driven) — `surge_basis` 기반 지평 시그니처 사후 재구성

**When** 일일 평가 잡(`evaluate_surge_predictions`)이 신호가 기준 EOD 최대수익률을
계산·저장한 직후, the system **shall** `predicted_set`의 각 신호에 대해
`surge_metadata.surge_basis` 리스트와 `ensemble.horizon_aware_thresholds.horizon_labels`
설정만을 입력으로 하는 신규 함수로 지평 시그니처(`same_day_dominant`/
`next_day_dominant`/`multi_day_dominant`/`mixed`)를 재구성해야 한다.

필수 조건:

- the system **shall not** `compute_horizon_signature()`(SPEC-AI-100)를 수정해야
  한다 — 재구성은 별개의 신규 함수로 구현한다(§Decisions D1).
- 재구성 대상은 앙상블 가중합 7개 키(`theme_cluster`/`volume_news_combo`/
  `disclosure_pattern`/`legacy_detectors`/`news_delayed`/`volume_breakout`/
  `momentum_continuation`)에 해당하는 `surge_basis` 멤버로 한정한다 — the
  system **shall not** 독립/우회 탐지기 이름을 이 재구성에 포함해서는 안
  된다(§Decisions D2).
- `surge_basis` 문자열을 앙상블 키로 정규화할 때 the system **shall**
  `{"immediate_disclosure": "disclosure_pattern", "legacy":
  "legacy_detectors"}` 매핑을 적용해야 한다(§Context [E-6]에서 코드 대조로
  확정) — 나머지 5개 앙상블 키(`theme_cluster`/`volume_news_combo`/
  `news_delayed`/`volume_breakout`/`momentum_continuation`)는 `surge_basis`
  문자열과 1:1 동일하므로 정규화가 불필요하다.
- 다중 라벨 발화 시 `mixed`, 라벨 없음 시 `multi_day_dominant`, 단일 라벨 시
  `{label}_dominant` 규칙은 `compute_horizon_signature()`와 동일해야 한다.

### REQ-AI108-002 (P0, Ubiquitous) — attribution 원칙 계승, 재채점 시도 금지

the system **shall** `surge_basis` 멤버십을 "해당 탐지기가 발화했다(점수>0)"는
증거로만 취급해야 한다(SPEC-AI-070이 확립한 attribution-not-re-score 원칙
재사용). the system **shall not** 원 컴포넌트 점수 값 자체를 재구성하거나
추정하려 시도해서는 안 된다 — 5개의 원시 점수 필드(`theme_cluster_score`/
`combo_score`/`pattern_score`/`immediate_disclosure_score`/`legacy_score`)가
`surge_metadata`에 실제로 영속화되어 있으나(§Context [E-2]), 이는 7개 앙상블
키 중 4개(`theme_cluster`/`volume_news_combo`/`disclosure_pattern`/
`legacy_detectors`)만 커버한다 — `disclosure_pattern`은 `pattern_score`와
`immediate_disclosure_score` 2개 원시 필드의 `max()`이기 때문이다. 나머지
3개 앙상블 키(`news_delayed`/`volume_breakout`/`momentum_continuation`)는
대응하는 원시 필드가 전혀 영속화되지 않아, `compute_horizon_signature()`가
요구하는 7개 키 전부를 동시에 필요로 하는 재호출은 여전히 불가능하다. 5개
원시 필드만 직접 읽고 나머지 3개 앙상블 키만 attribution하는 하이브리드
방식은 §Decisions D1 기각한 대안 2의 근거(서로 다른 코드 경로의
"활성" 판정 기준이 섞여 측정 정의가 불명확해지는 위험)로 채택하지 않는다 —
`surge_basis` 멤버십 하나만을 유일한 진실 소스로 취급하는 단일 attribution
경로를 7개 키 전부에 예외 없이 적용한다.

### REQ-AI108-003 (P0, Event-Driven) — 지평 시그니처별 정밀도 진단

**When** REQ-AI108-001의 지평 시그니처 재구성과 SPEC-AI-101의 신호가 기준
`forward_max_return_pct` 계산이 모두 완료되면, the system **shall**
`predicted_set` 신호를 재구성된 지평 시그니처 4개 버킷으로 그룹화하고, 각
버킷에 대해 `{signal_count, forward_positive_count, precision}`을 계산해야
한다. `forward_positive_count`는 해당 버킷 내 `forward_max_return_pct >= 10.0`
(SPEC-AI-101의 기존 임계값)인 신호 수이며, `precision = forward_positive_count
/ signal_count`다.

필수 조건:

- the system **shall** 2단계에서 이미 조회한 `signal_rows`를 재사용해야 한다
  — the system **shall not** `predicted_set`을 재조회해서는 안 된다
  (SPEC-AI-095/101이 확립한 원칙 재사용).
- the system **shall not** `_persist_signal_forward_outcomes()`의 함수
  시그니처나 반환값을 변경해서는 안 된다 — 신규 함수가 `SurgeSignalForwardOutcome`을
  독립적으로 재조회한다(§Decisions D3).

### REQ-AI108-004 (P0, State-Driven) — 0건 버킷의 None 가드

**While** 어느 지평 시그니처 버킷의 `signal_count`가 0인 동안, the system
**shall** 그 버킷의 `precision`을 `None`(NULL)으로 보고해야 하며, **shall not**
0으로 나누기 예외를 발생시키거나 `precision`을 `0.0`으로 대체해서는 안 된다
— "측정 불가"와 "0%"를 구분하는 기존 관례(SPEC-AI-093/095/104)를 재사용한다.

### REQ-AI108-005 (P0, Unwanted) — 게이팅·신규 테이블·기존 로직 변경 금지 [HARD]

the system **shall not**:

- 이 진단의 결과를 신호 생성 게이팅, `compute_ensemble_score()`,
  `select_effective_threshold()`, 어떤 bypass/gate 로직에도 사용해서는 안 된다;
- `ensemble.horizon_aware_thresholds.enabled` 또는 `.shadow_mode_enabled`
  값을 변경해서는 안 된다(SPEC-AI-101 REQ-AI101-006 불변식 계승);
- 신규 데이터베이스 테이블, 컬럼, 또는 alembic 마이그레이션을 도입해서는 안
  된다 — 모든 재구성은 이미 영속화된 `surge_metadata`/`SurgeSignalForwardOutcome`
  데이터 위에서만 동작해야 한다;
- `run_horizon_shadow_comparison()`, `check_horizon_transition_readiness()`,
  `evaluate_high_based_outcomes()`, `_persist_signal_forward_outcomes()`,
  `compute_horizon_signature()`, `select_effective_threshold()`의 내부 판정
  로직을 수정해서는 안 된다.

### REQ-AI108-006 (P1, Event-Driven) — 구조화 로그 노출

**When** 지평 시그니처별 정밀도 진단이 완료되면, the system **shall** 4개
버킷 전부의 `{bucket, signal_count, forward_positive_count, precision}`을
포함하는 구조화 INFO 로그 1줄을 SPEC-AI-101의 기존 신호가 기준 EOD 최대수익률
로그 인근에 기록해야 한다.

### REQ-AI108-007 (P0, Event-Driven) — 실패 격리 [HARD]

**When** 지평 시그니처 재구성 또는 정밀도 집계 계산 중 예외가 발생하면,
the system **shall** 그 예외를 격리된 `try/except`로 잡아 경고 로그만
남겨야 하며, **shall not** `evaluate_surge_predictions()`의 핵심 평가
결과 계산·커밋(precision/recall/f1/TP/FP/FN, `SurgePredictionEvaluation`
upsert) 또는 REQ-AI101-001/002의 신호가 기준 EOD 최대수익률 upsert에
영향을 주어서는 안 된다.

### REQ-AI108-008 (P1, Ubiquitous) — 증거 활용 절차 문서화 (결정 아님)

plan-phase 산출물 **shall** plan.md에 이 진단 결과가 두 개의 향후 결정 —
(a) SPEC-AI-100 Open Question 2(지평별 임계값 수치 확정), (b) SPEC-AI-100
§Decisions D1("완전 분리 기각")의 재검토 필요 여부 — 에 어떻게 증거로
활용되어야 하는지를 문서화해야 한다. 본 SPEC **shall not** 이 두 결정
중 어느 것도 스스로 내려서는 안 된다.

## Related SPECs

§ 선행 SPEC 섹션에서 이미 상세히 다룸(SPEC-AI-070/075/080/083/093/095/100/101/106).

## Open Questions

정책 판단(사후 재구성 방식 D1 / 재구성 범위 D2 / 배선 위치 D3 / recall 미산출
D4)은 §Decisions에서 이미 확정했다. `surge_basis` 문자열-앙상블 키 정규화
매핑(과거 Open Question 1 — `disclosure_pattern`/`immediate_disclosure` 및
`legacy`/`legacy_detectors` 2건)도 이 세션에서 코드 대조로 확정했다(§Context
[E-6], REQ-AI108-001 필수 조건에 반영). 남은 항목은 구현 시 확정할 사항이다.

1. **신규 함수의 정확한 배치 위치** — `surge_evaluation_service.py`의 사설
   (private, `_` 접두) 헬퍼로 둘지(§Decisions가 암묵 전제), 재사용 가능성을
   고려해 공개 함수로 둘지는 Run 단계에서 기존 파일 스타일(예:
   `_compute_forward_max_return`이 사설 순수 함수인 선례)을 참고해 확정한다.
2. **관측 표본 수 충분성** — 일 예측 건수가 3~9건 수준(project-surge-spec-status
   메모리)이라 4개 버킷으로 나누면 초기 관측 기간 동안 다수 버킷이 `signal_count`
   낮음/0에 머물 수 있다. 이는 REQ-AI108-004의 None 가드로 안전하게 처리되나,
   "언제부터 이 진단 결과를 SPEC-AI-100 Open Question 2 판단에 신뢰성 있게
   사용할 수 있는가"의 최소 표본 기준은 본 SPEC이 정하지 않는다 — 관측 데이터
   축적 후 별도 판단 대상이다.
