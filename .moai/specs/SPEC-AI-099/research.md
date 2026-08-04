# SPEC-AI-099 Research — 급등예측 피처 스냅샷 데이터 인프라

## 목적

이 문서는 spec.md 작성 전 라이브 코드를 직접 읽어 위임 프롬프트의 4개 "검증된 현황"
항목을 코드 대조로 재확인한 기록이다. 그중 1건은 **과대 서술되어 있어 정정**했다
(§2 참고). manager-spec은 검증 도구 없이 방어 주장을 하지 않는다는 원칙
(verification-claim-integrity)에 따라 정정 내용을 숨기지 않고 명시한다.

## 0. SPEC ID 배정 경위

위임 프롬프트는 "형제 SPEC(SPEC-AI-096/097/098)이 이번 배치에서 이미 생성되었으니
다음 자유 번호는 SPEC-AI-099일 가능성이 높다"고 예고했다. Write 이전에
`.moai/specs/` 목록을 직접 재확인한 결과 SPEC-AI-096/097/098이 모두 5개 파일
(research/spec/plan/acceptance/progress.md)로 완성되어 있었고, **SPEC-AI-099는
미점유**였다. `bash` 정규식 self-check(`^SPEC(-[A-Z][A-Z0-9]*)+-[0-9]{3}$`)도
PASS했다. 손상 없이 SPEC-AI-099로 배정한다.

## 1. 위임 프롬프트 "검증된 현황" 4개 항목 코드 대조

### 1-1. 수동 가중치 앙상블 (정확)

`backend/app/surge_config/surge_detection.yaml:67-74`:

```yaml
theme_cluster: 0.19
volume_news_combo: 0.25
disclosure_pattern: 0.14
legacy_detectors: 0.00
news_delayed: 0.11
weekend_gap_up: 0.08
volume_breakout: 0.11
momentum_continuation: 0.12
```

`regime_thresholds`(79-82행): `BULL: 0.38, SIDEWAYS: 0.45, BEAR: 0.42`. 이 값들은
주석(55-66행)에서 확인되듯 SPEC-AI-017/018/039/050/065를 거치며 사람이 손으로 재조정한
이력이 그대로 남아있다 — 학습된 가중치가 아니다. `surge_detector.py:1538-1608`
(`compute_ensemble_score`)는 이 가중치의 단순 곱셈-합산 + 컨센서스 배율(활성 그룹
수 기반, 1.00/1.30/1.55)만 수행한다. 위임 프롬프트의 서술이 정확하다.

### 1-2. `ml_feature_engineering.py`의 일 단위 집계 (정확)

`backend/app/services/ml_feature_engineering.py:24-94`(`capture_daily_features`)는
`MLFeatureSnapshot.date`에 `unique=True` 제약(모델 파일 21행)이 걸려 있어 **하루에
정확히 1행**만 생성된다. 컬럼은 당일 시그널 전체의 4-factor 평균(`avg_news_sentiment`
등), 추세 정렬 분포, `recent_5_accuracy` — 모두 당일 시그널 집합에 대한 **집계값**이며
종목별/시각별 원자 단위 피처가 아니다. 위임 프롬프트의 서술이 정확하다.

### 1-3. `check_ml_readiness`의 무소비 카운터 (정확)

`ml_feature_engineering.py:97-120`은 `MLFeatureSnapshot` 행 수를
`ML_READINESS_THRESHOLD_DAYS=90`과 비교해 로그 메시지("REQ-AI-011 활성화를
검토하세요")만 남긴다. `grep -rn "check_ml_readiness" backend/app` 결과 호출부는
`capture_daily_features` 내부(90행, 로그 목적) 1곳뿐 — 이 함수의 반환값을 실제로
소비해 분기하는 코드는 없다. 위임 프롬프트의 서술이 정확하다.

### 1-4. sklearn/lightgbm/xgboost 미의존 (정확)

`grep -rn "sklearn\|lightgbm\|xgboost" backend/app` → 유일한 매치는
`surge_contribution_service.py:763` 주석("순수 파이썬 배치 경사하강 로지스틱
회귀(numpy/sklearn 미사용, AI-065 오프라인...")과 `surge_calibrator.py` 모듈
docstring("numpy / scikit-learn 의존성 없이 순수 Python만 사용한다") — 둘 다 "이
라이브러리를 쓰지 않는다"는 명시적 진술이지 실제 의존이 아니다. `pyproject.toml`/
`requirements*.txt`에서도 매치 0건. 위임 프롬프트의 서술이 정확하다.

## 2. 정정 사항 — "개별 원시 피처가 이미 계산되어 재사용 가능하다"는 전제는 과대 서술이다

위임 프롬프트는 스냅샷에 담을 필드로 "거래량 증가율, 거래대금 증가율, 뉴스 기사 수,
최근 변동성, 시장 대비 상대수익률, 섹터 모멘텀, 시가총액/유동성 — 이미 코드베이스
어딘가에 계산되어 있으니 재사용하라"고 전제했다. 코드 대조 결과 이 전제는 **부분적으로만
사실**이다.

- `SurgeCandidate` 데이터클래스(`surge_detector.py:61-99`)에는 `theme_cluster_score`,
  `combo_score`, `pattern_score`, `immediate_disclosure_score`, `legacy_score`,
  `news_delayed_score`, `squeeze_score`, `volume_breakout_score`,
  `momentum_continuation_score`, `price_5d_trend`, `per`/`pbr`,
  `disclosure_sentiment`, `entry_pool`, `bridge_score` — 즉 **탐지기별로 이미 계산된
  스코어(derived score)**만 존재한다.
- 위임 프롬프트가 예로 든 "거래량 증가율" 자체(`volume_ratio`)는
  `surge_detector.py:2675`에서 `today_volume / avg_volume`으로 계산되지만, 이는
  `detect_volume_breakout()` 계열 함수 **내부 지역변수**다 — `confidence`/
  `volume_breakout_score`로 축약된 뒤 `SurgeCandidate`에는 그 축약값만 실린다.
  원시 `volume_ratio` 자체는 후속 소비처(예: 본 SPEC의 피처 스냅샷)에 노출되지 않는다.
  "거래대금 증가율", "뉴스 기사 수"(테마 클러스터 내부의 `stock_specific_count`는
  존재하나 반환값에 포함되지 않음), "시장 대비 상대수익률", "섹터 모멘텀"(별도 서비스
  `sector_momentum.py`에 있으나 `SurgeCandidate`와 조인되어 있지 않음)도 동일한 패턴 —
  계산은 되지만 후속 소비처로 스레딩되어 있지 않다.

**결론**: 본 SPEC이 "이미 계산된 값만 재사용"하려면, 탐지기 함수 내부를 수정해 원시
지역변수를 반환값/객체 필드로 노출시키는 작업이 선행되어야 한다 — 이는 위임 프롬프트가
명시적으로 배제한 "이 SPEC이 필요로 하지 않는 새 비싼 계산을 발명하지 말라"는 제약과
충돌하지 않으면서도 범위를 넓힌다. §Decisions D3에서 1단계 범위를 "`SurgeCandidate`에
이미 존재하는 필드 + `compute_ensemble_score`가 이미 계산하는 중간값(`best_disclosure_score`,
`active_groups`, `weighted_sum`) + 스캔 루프에서 이미 조회된 컨텍스트(시총, 현재가)"로
좁히고, 원시 미노출 피처(거래량/거래대금 비율, 뉴스 건수, 상대수익률, 섹터 모멘텀)는
탐지기 함수 시그니처 변경이 필요한 후속 SPEC으로 명시적으로 이월한다.

## 3. 기존 `FundSignal` 쓰기 경로 확인 — per-row flush, 배치 아님 + 행 자체가 가변적

`backend/app/services/fund_manager.py:1505-1585`(`qualified` 후보 순회 루프 내부):

- 5영업일 이내 중복이 있으면 **기존 행을 UPDATE**한다(1516-1560행) —
  `existing.confidence`, `existing.surge_metadata`, `existing.created_at`이 스캔
  사이클마다 덮어써진다(SPEC-AI-080 R-6/R-7 WARN 태그, 1522-1531행). 즉
  `FundSignal`은 **불변(immutable) 레코드가 아니다** — 같은 논리 키(stock_id +
  signal_type="surge_candidate")로 여러 스캔 사이클에 걸쳐 재사용된다.
- 신규인 경우에도 `db.add(signal)` 직후 **개별 `db.flush()`**를 호출한다
  (1580-1581행) — 루프 순회당 1회씩, 배치 삽입이 아니다.
- `grep -rn "bulk_save_objects\|bulk_insert_mappings\|db\.add_all" backend/app`
  결과 매치는 `surge_universe_pool_service.py` 1개 파일뿐 — `surge_detector.py`/
  `fund_manager.py`의 스코어링 핫루프에는 배치 삽입 선례가 없다.

**결론**: `FundSignal`은 (a) 스캔 사이클 간 가변(mutable)이라 "불변 피처 스냅샷"
요구사항과 충돌하고, (b) 이미 존재하는 쓰기 패턴 자체가 개별 flush(사용자가 명시적으로
피하라고 한 "per-row commit")다. 본 SPEC은 `FundSignal` 쓰기 경로를 재사용하지 않고
독립된 신규 쓰기 경로를 신설해야 하며, 그 신규 경로에서 배치 삽입을 도입하는 것은
기존 패턴을 답습하지 않는 **개선**이지 반복이 아니다.

## 4. `compute_ensemble_score` 호출 지점 3곳 확인 — 최적 캡처 지점

`grep -n "compute_ensemble_score(" backend/app/services/surge_detector.py` →
2193행, 2290행, 2360행 3곳. 2193행은 `for candidate in merged.values():`
(2192행 시작) 메인 루프 내부이며, 이 루프는 **그 사이클에 고려된 모든 후보**(테마·거래량·공시
등 탐지기 중 하나라도 반응한 후보 전체, `merged` 딕셔너리)에 대해 정확히 1회씩
`compute_ensemble_score`를 호출한다. 이후 3개의 우회(bypass) 루프(2204/2229/2263행)는
**동일한 `merged.values()`를 재순회**하며 이미 스코어링된 후보 중 임계값 미달분을
조건부로 `qualified`에 추가할 뿐 — `merged`에 없는 새 후보를 만들거나 새로
`compute_ensemble_score`를 호출하지 않는다.

**결론**: 2192-2199행의 메인 루프가 "그 사이클에 평가된 모든 후보의 점수를 정확히 1회
계산하는" 유일한 지점이다. 여기서 스냅샷을 캡처하면 최종적으로 시그널로 승격되는
후보(양성 예시)와 승격되지 않는 후보(음성 예시)를 모두 포함하게 되어, 향후 지도학습
모델(분류기/랭커)을 학습시킬 때 필요한 양쪽 클래스를 모두 확보한다 — `fund_manager.py`의
`FundSignal` 생성 지점(§3)에서 캡처하면 승격된 후보만 보이므로 음성 예시가 없다.

## 5. 조인 가능한 정답(outcome) 소스 확인

- `SurgeActualOutcome`(`models/surge_actual_outcome.py`, composite PK
  `(trading_date, stock_code)`): `change_rate`, `was_surge`(>=10%),
  `high_change_rate` 보유 — 종목-일자 단위 실제 결과. 본 SPEC의 스냅샷과 자연스럽게
  조인 가능한 **유일한 종목 단위(row-level) 정답 소스**다.
- `SurgePredictionEvaluation`(`models/surge_prediction_evaluation.py`, PK
  `evaluation_date` 단일)은 **일별 집계**(precision/recall/f1, TP/FP/FN 카운트)이며
  종목별 행이 아니므로 본 SPEC의 스냅샷 1행과 직접 조인할 수 없다 — 조인 대상은
  `SurgeActualOutcome`으로 한정한다.
- `SurgePredictionEvaluation.predicted_codes_json`(77-81행, SPEC-AI-092)이
  평가 시점의 공식 predicted set 스냅샷을 이미 남기고 있으나, 이는 평가 파이프라인
  전용 필드이며 본 SPEC의 스냅샷 테이블과는 별개 관심사다(중복 저장 아님 — 후자는
  피처+점수, 전자는 "그날 어떤 종목이 predicted set에 속했는가"라는 감사용 메타데이터).

## 6. 보존(retention) 정책 선례 부재 확인

`grep -rniE "cleanup_old|DELETE FROM fund_signals|delete.*FundSignal" backend/app`
결과 정리(cleanup) 잡은 3개뿐이다: `_cleanup_old_articles`, `_cleanup_old_disclosures`
(`scheduler.py:240,264,269,287,298,304` — 공시 5일 보존), `cleanup_old_impacts`
(`news_price_impact_service.py:350`). **`fund_signals`, `surge_actual_outcome`,
`surge_prediction_evaluation` 테이블을 대상으로 하는 정리 잡은 존재하지 않는다** —
이 테이블들은 현재 무기한 누적된다. 즉 project memory의 "데이터 보존 5일"은 공시
(disclosures)에 한정된 정책이며, 예측/결과 계열 테이블에는 적용되지 않는다. 본 SPEC이
신설하는 피처 스냅샷 테이블에 상속할 기존 보존 선례가 없으므로, 보존 정책은 §Decisions에서
명시적으로 결정해야 한다(신규 결정 사항, 선례 답습이 아님).

## 7. Non-Goals 경계 확인

- `build_scan_universe()`(Pool A/B/C/D 구성)와 배치 시세 조회는 이번 배치의 형제
  SPEC(SPEC-AI-096/097) 대상이다 — 본 조사에서 건드리지 않았다.
- 뉴스-종목 매칭 경계 가드(SPEC-AI-098)는 별개 관심사이며 본 SPEC의 스냅샷은 그 결과
  스코어(`theme_cluster_score`)를 소비만 할 뿐 매칭 로직 자체와 무관하다.
- `compute_ensemble_score`의 가중치 합산 공식 자체, 레짐별 임계값, 컨센서스 배율은
  무수정 대상이다 — 본 SPEC은 그 계산 결과를 **읽어서 저장**할 뿐이다.
- `surge_calibrator.py`(isotonic 캘리브레이션)는 `confidence`를 사후 보정하는 별개
  파이프라인이며, 본 SPEC의 스냅샷은 보정 전(raw) `surge_score`를 저장 대상으로 한다 —
  보정된 값과의 관계는 Open Question으로 남긴다.
