# SPEC-AI-101 Research

## §1. 위임 프롬프트 핵심 주장 검증

팀 리드 위임 프롬프트는 두 가지 문제를 제시했다. 둘 다 실제 코드 대조로 재확인했다.

### 1-1. `was_surge` 라벨은 종가 기준이며 point-in-time 미래최대수익률이 아니다 (CONFIRMED)

`backend/app/models/surge_actual_outcome.py:32-34`:

```python
change_rate: Mapped[float]       # 당일 종가 기준 등락률(%)
was_surge: Mapped[bool]          # change_rate >= 10.0
```

`high_change_rate`(장중 고가 기준 등락률, SPEC-AI-093이 실측 수집)는
`surge_evaluation_service.py:858-908`에서 `high_based_recall/precision/coverage`라는
**병렬 보조지표**로만 쓰인다 — `was_surge`나 `predicted_set` 판정 자체에는 관여하지 않는다
(`evaluate_surge_predictions` 본류 로직, `:775-784`는 여전히 `was_surge.is_(True)`만 조회).

### 1-2. SPEC-AI-100 지평 인식 임계값 아키텍처는 완성됐으나 완전히 비활성이다 (CONFIRMED)

`backend/app/surge_config/surge_detection.yaml:93-95`:

```yaml
horizon_aware_thresholds:
  enabled: false
  shadow_mode_enabled: false
```

`compute_horizon_signature()`(`surge_detector.py:1650`), `select_effective_threshold()`(`:1697`),
`run_horizon_shadow_comparison()`(`:1731`)는 모두 구현되어 있고 `run_horizon_shadow_comparison`은
메인 루프(`:2561`)에 실제로 배선되어 있다 — 그러나 함수 진입부(`:1752-1755`)가
`enabled`와 `shadow_mode_enabled` 둘 다 확인해 **둘 다 false인 현재 상태에서는 조기 반환**한다.
즉 관측이 전혀 시작되지 않은 상태(완성된 기계가 스위치만 꺼진 상태)다.

SPEC-AI-100 plan.md §D가 이미 전환 게이트 3요건(≥10 거래일, 3개 레짐 전량 관측,
qualified 집합 변화폭 ±30% 이내)을 확정했고(REQ-AI100-009/AC-100-011), "확인 절차(로그
조회 방법, 판정 기준)는 구현 시 plan.md §D에 명문화되어야 한다"고 명시했다 — 이 SPEC의
과제는 그 확인 절차를 실제로 만들고 관측을 켜는 것이다.

## §2. 라벨 재정의 실행가능성 조사 (핵심 발견 — 위임 프롬프트가 명시하지 않은 제약)

위임 프롬프트는 "30분/60분/120분/장마감 지평별 forward max return + MAE(최대 역행폭) +
거래량 + 슬리피지 반영 체결가능가"를 제안했다. 이 제안의 실행가능성을 데이터 소스
관점에서 조사했다.

**분봉/장중 시계열 가격 데이터 수집 인프라가 존재하지 않는다.** 코드베이스 전체에서
가격 조회 함수는 두 종류뿐이다:

- `naver_finance.py:708/830` `fetch_stock_price_history[_sync]` — **일봉**(daily OHLC) 조회.
- `kis_api.py:134` `fetch_kis_stock_price` — **단일 시점 현재가** 스냅샷(비주기적, 매매
  체결 시점에만 호출).

30/60/120분 지평의 forward return을 만들려면 **신규 주기적 장중 가격 폴링 파이프라인**
(스케줄러 잡 + 신규 영속 테이블)이 필요하다 — 이는 "라벨 재정의"가 아니라 별도의 데이터
수집 인프라 SPEC 규모의 작업이며, 위임 프롬프트가 Non-Goal로 명시한 "학습 인프라"와
성격이 유사하게 무겁다(SPEC-AI-099가 피처 스냅샷 인프라를 위해 별도 SPEC 전체를
소요한 것과 동일 규모).

**이미 존재하는 데이터만으로 point-in-time 근사가 가능하다.** `FundSignal.price_at_signal`
(`fund_signal.py:33`, 시그널 발행 시점 주가, 이미 매 surge_candidate 시그널에 기록됨)과
`SurgeActualOutcome.high_change_rate`(이미 SPEC-AI-093으로 실측 수집됨, T-1 종가 대비
장중 고가 등락률)를 결합하면:

```
day_high_price ≈ prev_close_price × (1 + high_change_rate/100)
forward_max_return_pct ≈ (day_high_price − price_at_signal) / price_at_signal × 100
```

`prev_close_price`(T-1 종가 절대가)는 `fetch_stock_price_history_sync`로 조회 가능하다
(SPEC-AI-072가 동일 기법으로 T-1 종가를 이미 사용한 선례— `날짜 매칭(인덱스 아님)으로
T-1 종가` 원칙을 그대로 재사용). 이 근사는 **신규 데이터 수집 없이** 이미 수집된 두
컬럼 + 기존 조회 함수 1개만으로 계산 가능한 "장마감(EOD) 지평의 point-in-time
미래최대수익률"이다 — 시그널가 대비 그날 고점까지의 실현 가능 수익률을 근사한다. 정확히
GPT 비평이 지적한 두 반례(장중 +15%였다가 종가 +7%로 마감한 경우, 시그널가 +3%에서
장중 +12%까지 갔다가 +8% 마감한 경우) 모두 이 근사로 "실제로는 잡았다"고 올바르게
라벨링된다.

**30/60/120분 세분 지평은 이 SPEC의 범위에서 명시적으로 제외한다**(신규 인프라 필요,
§Non-Goals). EOD 지평 근사만 v1 범위로 채택한다.

## §3. 선행 SPEC 교차 확인

- **SPEC-AI-095**(완료): `high_change_rate` 병렬 평가지표 노출 — 이 SPEC이 재사용하는
  "additive/parallel 스키마" 선례. `was_surge`는 동결(REQ-AI095-002), 소비자 무수정.
- **SPEC-AI-100**(완료): 지평 인식 임계값 아키텍처 + 섀도우 로깅(비활성) + 전환 게이트
  구조(3요건). 본 SPEC이 "실행" 담당.
- **SPEC-AI-075/083**(완료): 평가 계층 지평 분리 선례(`horizon` 메타데이터 필드,
  `surge_metadata` 기반 predicted_set 배제 패턴) — 본 SPEC의 신규 라벨은 이 패턴과
  독립이며 재구현하지 않는다.
- **SPEC-AI-099**(완료): `SurgeFeatureSnapshot` 인프라, `check_feature_snapshot_readiness()`가
  고유 스캔일수 **90일** 기준으로 ML 준비도를 판정(`surge_feature_snapshot_service.py:82-87`).
  본 SPEC의 신규 라벨은 향후 이 피처 스냅샷과 결합해 모델 학습에 쓰일 수 있으나, 모델
  학습 자체는 본 SPEC의 Non-Goal이며 SPEC-AI-099의 90일 축적 요건과 독립적으로 별도
  판단 대상이다.

## §4. 결론 — 두 갈래 실행 계획

1. **라벨**: `SurgeActualOutcome`을 직접 재정의(파괴적 변경)하지 않고, 신규 addtive
   테이블(신호 단위 forward-return 근사)을 신설한다 — SPEC-AI-095/075/080의 프로젝트
   선례를 그대로 따른다.
2. **전환 게이트**: SPEC-AI-100의 `shadow_mode_enabled`를 켜고, 섀도우 비교 결과를
   경량 신규 테이블에 영속화해 3요건 판정을 로그 스크래핑이 아닌 SQL 쿼리로 만든다
   (SPEC-AI-100 Open Question 4가 이미 예견한 "정량 분석이 필요해지면 전용 비교 테이블
   신설을 재검토"의 실행).
