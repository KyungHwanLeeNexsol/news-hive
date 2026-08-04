# SPEC-AI-100 Research — 급등예측 스코어링 아키텍처: 지평(horizon) 분리

## 목적

이 문서는 spec.md/design.md 작성 전 라이브 코드를 직접 읽어 위임 프롬프트의 "코드 대조로
검증된 현황" 6개 항목을 재확인하고, 그 과정에서 위임 프롬프트에 없던 **추가 발견 사항**을
기록한다. manager-spec은 검증 도구 없이 방어 주장을 하지 않는다는 원칙
(verification-claim-integrity)에 따라, 위임 프롬프트의 서술을 그대로 베끼지 않고 실제
코드 라인을 대조해 확정하거나 정정한다.

## 0. SPEC ID 배정 경위

위임 프롬프트는 "형제 SPEC(SPEC-AI-096/097/098/099)이 이번 배치에서 이미 생성되었으니
다음 자유 번호는 SPEC-AI-100일 가능성이 높다"고 예고했다. Write 이전에 `.moai/specs/`
목록을 직접 재확인한 결과 SPEC-AI-096~099가 모두 5개(또는 4개, SPEC-AI-097은
research.md 없이 4개) 파일로 이미 존재했고, **SPEC-AI-100은 미점유**였다. `bash` 정규식
self-check(`^SPEC(-[A-Z][A-Z0-9]*)+-[0-9]{3}$`)도 PASS했다. 손상 없이 SPEC-AI-100으로
배정한다.

## 1. 위임 프롬프트 "검증된 현황" 6개 항목 코드 대조

### 1-1. `compute_ensemble_score`가 이질적 지평의 탐지기 점수를 단일 가중합으로 결합 (정확)

`surge_detector.py:1538-1608`(`compute_ensemble_score`)는 `theme_cluster_score`,
`combo_score`, `best_disclosure_score`(`max(pattern_score, immediate_disclosure_score)`),
`legacy_score`, `news_delayed_score`, `volume_breakout_score`,
`momentum_continuation_score` 7개 항을 `config.ensemble.weights`의 가중치로 곱해 합산한
뒤(1559-1570행), `detector_groups`(news/disclosure/technical 3그룹, 1576-1584행) 활성
그룹 수 기반 컨센서스 배율(1.00/1.30/1.55, 1590-1595행)을 곱한다. 메인 루프
(2192-2199행)는 이 점수를 `effective_threshold`(레짐별 고정값, 2184-2186행)와 비교해
단일 게이트를 적용한다. 위임 프롬프트의 서술이 정확하다.

### 1-2. 탐지기별 상이한 예측 지평 (정확, 단 세분화 필요 — §2-4 참고)

theme_cluster(48h 뉴스 윈도우), disclosure_pattern(당일/즉시 공시), momentum_continuation
(전일 T-1 가격 행동), volume_breakout/near_limit_up_carry(당일/장중)는 실제로 상이한
지평을 갖는다. 이 서술 자체는 정확하나, "이 모든 상이한 지평이 동일 가중치·동일
임계값으로 게이팅된다"는 진단은 정확한 반면, **어떤 지평 개념이 코드에 이미 존재하는지는
위임 프롬프트가 서술한 것보다 좁다** — §2-4에서 정정한다.

### 1-3. `surge_evaluation_service.py`의 same-day 지평 평가 계층 분리 (정확)

`_is_same_day_event_horizon_signal()`(506-524행)은 `surge_metadata.horizon == "same_day"`를
검사해 표준 T-1→T `predicted_set`에서 제외하고 `excluded_same_day_event_codes`(738-762행)로
별도 집계한다. 이는 평가(측정) 계층의 사후 분리이며, 탐지기 점수 계산이나 임계값 게이팅
시점(예측 생성)에는 관여하지 않는다. 위임 프롬프트의 서술이 정확하다.

### 1-4. `surge_threshold_service.py`의 매수 실행 전용(execution-only) 분리 (정확)

모듈 docstring(1-17행)이 명시적으로 확인한다: `get_today_threshold()`의 유일한 호출부는
`surge_trading_service.execute_buy_orders()`(매수 실행)이며, `gather_surge_candidates()`
(예측 생성)는 이 모듈을 import하지 않는다. `surge_detector.py:2181-2183` 주석도 동일한
분리를 재확인한다: "이 예측 생성 게이트는 surge_threshold_service의 적응형 임계값(매수
실행 전용)과 무관하다." 위임 프롬프트의 서술이 정확하다.

### 1-5. `combo_chase_guard` Gate 4가 지평 무관 단일 게이트 (정확)

`surge_detector.py:2158-2174`, `combo_score > 0`이고 `theme_cluster_score`/
`immediate_disclosure_score`/`pattern_score`가 모두 0이면 `merged`에서 완전히 제거한다
(`del merged[_code]`). `config.combo_chase_guard.require_companion_detector`
(`surge_detection.yaml:175`, 기본값 `true`)로 제어된다. 위임 프롬프트의 서술이 정확하다.

### 1-6. `event_rescan`(SPEC-AI-083) 사전 완화책의 출처 — 정정 필요

위임 프롬프트는 "SPEC-AI-083(`event_rescan`)이 이미 부분 완화책으로 구현되어 있다"고
서술했다. 코드를 직접 확인한 결과 `scheduler.py:36-38`의 모듈 헤더 주석은
`_event_rescan_state`/`_maybe_trigger_event_rescan()`(37-151행)를 **SPEC-AI-066
REQ-AI066-007**(고임팩트 뉴스 이벤트 구동 재스캔) 소유로 명시한다. project memory
(`project_surge_architectural_root_cause_2026_07_21.md`)에 따르면 SPEC-AI-083은 이
기존 메커니즘을 "재스캔 4잡 + same-day 귀속 + `event_rescan` **활성화**"로 확장/활성화한
것이지, 최초 구현체는 아니다. 즉 **SPEC-AI-066이 메커니즘을 구축했고, SPEC-AI-083이
그것을 활성화·확장했다** — 두 SPEC 모두 관련이 있으나 "이미 구현되어 있다"의 원 저자는
SPEC-AI-066이다. spec.md에서는 이 정정된 귀속을 사용한다.

## 2. 위임 프롬프트에 없던 추가 발견 — 지평(horizon) 분리 설계에 직접 영향

### 2-1. `weekend_gap_up` 탐지기는 라이브 파이프라인에 전혀 배선되지 않았다

`surge_settings.py:155` 주석: "weekend_gap_up은 coverage-expansion 탐지기. 가중치
필드는 합산 검증용" — 즉 `config.ensemble.weights.weekend_gap_up`(0.08)은 8개 가중치
합계를 1.00으로 맞추기 위한 필드일 뿐, **`compute_ensemble_score`의 `weighted_sum`
계산(1559-1570행)에는 전혀 사용되지 않는다**(직접 확인 — `w.weekend_gap_up` 참조 없음).
`fund_manager.py:4104-4113`에서 `detect_weekend_gap_up_signals()`를 호출하지만, 주석이
명시한다: "weekend_gap_up 결과는 dict 목록으로 반환 (**FundSignal 미생성** — 앙상블
외부 커버리지 정보) / 향후 gather_surge_candidates와 통합 예정." 즉 이 탐지기는 후보를
계산하지만 **실제 매매 시그널로 전혀 이어지지 않는다** — 순수 관측/로그 전용이다.

### 2-2. `bollinger_squeeze`(squeeze_score) 탐지기도 완전히 분리된 별도 잡이다

`SurgeCandidate.squeeze_score`(`surge_detector.py:85`) 필드는 존재하나,
`compute_ensemble_score`의 `weighted_sum`(1559-1570행)에는 `squeeze_score` 항이 없다
(직접 확인 — `w.squeeze` 또는 동등 항 부재). `grep`으로 `fund_manager.py` 전체를
확인한 결과 `detect_bollinger_squeeze_signals`에 대한 호출이 **전혀 없다**(0 matches).
호출부는 `scheduler.py:1233-1241`뿐이며, 그 잡의 유일한 후속 동작은
`logger.info("볼린저 스퀴즈 탐지 완료: %d건", len(results))` — 결과를 그 자리에서
버린다(변수 `results`가 함수 스코프를 벗어나지 않음). 즉 이 탐지기도 급등 후보 풀,
FundSignal, 앙상블 스코어링 그 무엇에도 연결되지 않은 **완전한 고아(orphan) 탐지기**다.

### 2-3. 결론 — "8개 탐지기"는 실제로 3개 층위로 나뉜다

| 층위 | 탐지기 | compute_ensemble_score 소비? | FundSignal 생성? |
|------|--------|-------------------------------|-------------------|
| 라이브(weighted_sum) | theme_cluster, volume_news_combo, disclosure_pattern(best_disclosure_score), legacy_detectors(가중치 0), news_delayed, volume_breakout, momentum_continuation | 예 (7항) | 예 |
| 라이브(bypass 경로) | immediate_disclosure(강한 단독), theme/combo(강한 단일), volume_breakout(단독) | 아니오 — 3개 bypass 루프(2204/2229/2263행)가 weighted_sum 우회 | 예 |
| **고아(미배선)** | **weekend_gap_up, bollinger_squeeze** | **아니오 — 가중치는 존재하나 미사용, 또는 필드는 존재하나 미사용** | **아니오** |

이는 spec.md §Decisions에 새 결정 항목(고아 탐지기 처리 범위)이 필요함을 시사한다 —
지평 분리 아키텍처를 설계할 때 이 2개 탐지기를 새 체계에 편입시킬지, 아니면 명시적으로
범위 밖으로 남길지 결정해야 한다.

### 2-4. 기존 `horizon` 메타데이터 필드는 "탐지기 종류"가 아닌 "공시 시그널 발생 시각"만 구분한다

`disclosure_impact_scorer.py:466`(`horizon = _classify_disclosure_horizon(now_kst,
immediate_cfg)`)와 532행(`return "next_day"`)을 직접 확인한 결과, `horizon` 필드는
**즉각 공시(immediate_disclosure) 탐지기 단일 경로에서만** 설정되며, 그 값(`same_day`/
`next_day`)은 공시가 **접수된 시각**이 배치 컷오프 이전/이후인지로 결정된다
(`_classify_disclosure_horizon`). 이는 위임 프롬프트가 문제 6에서 인용한 것과 동일한
필드이지만, **theme_cluster, momentum_continuation, volume_breakout 등 다른 6개
라이브 탐지기는 이 필드를 전혀 설정하지 않는다** — `horizon`은 "탐지기 유형에 내재한
예측 지평"이라는 일반 개념이 아니라, "공시 한 종류의 접수 시각 분류"라는 좁은 개념으로
이미 존재하는 것이다.

**결론**: 위임 프롬프트의 문제 3("`surge_metadata`의 `horizon`/`surge_basis` 필드로
same-day 지평을 식별한다")은 정확하지만, 이것이 "일반적인 탐지기-지평 taxonomy가 이미
존재한다"는 뜻은 아니다 — 오직 1개 탐지기(즉각 공시)의 시각 분류일 뿐이다. 본 SPEC이
설계할 지평 아키텍처는 이 좁은 개념을 **일반화**하는 작업이지, 이미 존재하는 일반
개념을 재사용하는 작업이 아니다. (이 구분은 design.md §B 옵션 비교에 직접 반영한다 —
일반화 작업의 비용은 순수 재사용보다 크지만, 완전히 새로 발명하는 것보다는 작다.)

## 3. `SurgeCandidate` 필드 구성 재확인 (SPEC-AI-099 연구 결과와 일치)

`surge_detector.py:61-99`의 필드 목록은 SPEC-AI-099 research.md §2가 이미 확인한
내용과 일치한다 — 탐지기별 파생 스코어만 존재하고 원시 지역변수(거래량 비율 등)는
노출되지 않는다. 본 SPEC은 이 필드 구성을 그대로 소비 대상으로 삼으며, 필드 확장은
범위 밖이다(§Out of Scope).

## 4. `combo_chase_guard`와 지평의 상호작용

Gate 4(2158-2174행)의 companion 조건(`theme_cluster_score`/`immediate_disclosure_score`/
`pattern_score` 중 하나라도 0 초과)은 이미 **서로 다른 지평의 탐지기를 컴패니언으로
혼용**한다 — `theme_cluster_score`(48h 다일 지평)와 `immediate_disclosure_score`(당일
지평)를 동등하게 취급해 "어느 한쪽이라도 corroborate하면 통과"로 판정한다. 이는 게이트
자체가 "지평 무관 corroboration"이라는 설계 의도를 가진 것으로 읽히며, 지평 분리
아키텍처 도입이 이 게이트의 **판정 로직 자체**를 바꿔야 할 필연적 이유는 발견되지
않았다 — design.md §D에서 이 판단을 다룬다.

## 5. `surge_threshold_service` 소비처 재확인

`grep`으로 `surge_threshold_service|compute_adaptive_threshold|get_adaptive_threshold`를
`app/services` 전체에서 검색한 결과 4개 파일(`surge_detector.py`,
`surge_threshold_service.py`, `fund_manager.py`, `surge_trading_service.py`)에서만
매치되었다. `surge_detector.py` 내 매치는 모듈 docstring/주석 인용뿐(1-1 참고 주석
2181-2183행) — 실제 `import` 또는 함수 호출은 없다. 이는 모듈 docstring의
"gather_surge_candidates()는 이 모듈을 import하지 않는다"는 주장을 재확인한다.

## 6. Non-Goals 경계 확인

- 스캔 유니버스(Pool A/B/C/D) 구성 변경(SPEC-AI-096), 배치 시세 조회(SPEC-AI-097),
  뉴스-종목 매칭(SPEC-AI-098), 피처 스냅샷 인프라(SPEC-AI-099)는 이번 배치의 형제 SPEC
  대상이며 본 조사에서 건드리지 않았다.
- **SPEC-AI-099와의 연계 관찰**: SPEC-AI-099가 구축할 종목별·사이클별 불변 피처
  스냅샷(`SurgeFeatureSnapshot`, 승격/비승격 후보 모두 기록)은, 본 SPEC이 지평 인식
  임계값을 실제 배포 전에 **백테스트**하려 할 때 필요한 정확한 도구다 — 현재 코드베이스는
  과거 사이클의 원시 스코어링 결과를 저장하지 않으므로(그것이 정확히 SPEC-AI-099가
  메우려는 공백이다), 본 SPEC의 검증 계획(plan.md §D)은 SPEC-AI-099 완료 이전에는
  섀도우 모드 로그 비교로, 완료 이후에는 스냅샷 기반 백테스트로 단계적으로 강화될 수
  있음을 명시한다. 이는 두 SPEC이 서로의 구현을 요구하지 않는 독립적 병행 관계이나,
  검증 품질 측면에서 SPEC-AI-099 완료가 본 SPEC의 사후 검증을 강화하는 수혜 관계다.
- 학습된 모델 도입은 이 Epic 전체에서 사용자 결정으로 배제되었다(위임 프롬프트 명시) —
  본 SPEC은 규칙 기반/수동 튜닝 스코어링 아키텍처만 다룬다.
