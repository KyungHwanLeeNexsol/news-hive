# SPEC-AI-092 Research

## 1. 운영 DB 점검 요약

점검일: 2026-07-28
대상: 운영 PostgreSQL `surge_prediction_evaluation`, `surge_actual_outcome`, `fund_signals`,
`surge_universe_members`

### 7월 누적 평가

```text
eval_days: 18
predicted: 205
actual: 1086
tp: 8
fp: 197
fn: 1078
precision_micro: 0.0390
recall_market_micro: 0.0074
scannable_actual: 159
coverage_micro: 0.1464
scannable_recall_micro: 0.0503
```

해석:

- 시장 전체 recall은 1% 미만이다.
- 스캔 가능 종목 기준 recall도 5% 수준이다.
- coverage 자체가 14.64%라 전체 실제 급등주의 대부분이 전일 스캔 가능 범위 밖에 있다.

### 2026-07-28 평가 복구 후 결과

```text
predicted_count: 7
actual_surge_count: 23
true_positive: 0
false_positive: 7
false_negative: 23
precision: 0
recall: 0
scannable_actual_count: 4
coverage: 0.1739
scan_universe_size: 150
pool_a_count: 253
pool_b_count: 0
pool_c_count: 112
```

### 2026-07-28 non-scannable 진단

```text
non_scannable: 19
absent: 11
truncated: 8
```

absent는 T-1 소스 단계에서 스캔 유니버스 후보가 아니었던 종목이다. truncated는 후보 풀에는 있었지만
최종 150개 scan universe cap에서 탈락한 종목이다.

## 2. 코드 경로 확인

### 평가 경로

대상: `backend/app/services/surge_evaluation_service.py`

- `evaluate_surge_predictions()`는 평가일 T의 직전 영업일 T-1을 계산한다.
- 공식 predicted set은 `FundSignal.signal_type == "surge_candidate"`,
  `surge_metadata is not null`, `date(created_at) == T-1` 조건으로 조회한다.
- 이후 `near_limit_up_carry`와 `horizon=="same_day"`를 제외한다.
- actual set은 `SurgeActualOutcome.was_surge is true` 기준이다.
- scannable recall/coverage는 `surge_universe_members` T-1 기준으로 계산한다.

### 후보 생성 경로

대상: `backend/app/services/surge_detector.py`

- `gather_surge_candidates()`는 1차 탐지 결과를 `merged`에 먼저 모은다.
- 그 뒤 `build_scan_universe(db, config, existing_codes=set(merged.keys()))`를 호출한다.
- 반환된 universe는 pool count/member 영속화와 측정에 쓰인다.
- `merged`에 없는 universe member를 공식 후보로 승격하는 일반 경로는 없다.

### signal update 경로

대상: `backend/app/services/fund_manager.py`

- `_gather_surge_candidates()`는 5일 내 같은 stock/signal_type 행이 있으면 기존 `FundSignal`을 업데이트한다.
- 업데이트 경로에서 `created_at`을 현재 시각으로 이동한다.
- `originally_created_at`은 보존하지만, 기존 history API는 평가 완료 row에서도 현재 `created_at` 기준으로 재조회했다.

## 3. 2026-07-28 세부 관찰

공식 예측 7개는 실제 급등 23개와 겹치지 않았다.

실제 급등 중 scannable 4개:

```text
079950 인베니아: pool_a, gap_pullback_candidate만 존재
291810 핀텔: pool_c, surge_candidate 없음
363250 진시스템: pool_c, surge_candidate 없음
377480 마음AI: pool_c, surge_candidate 없음
```

해석:

- universe에 들어온 종목도 공식 `surge_candidate`로 승격되지 않는 간극이 실제로 있다.
- Pool C bridge 후보화는 scannable recall 개선에 직접 닿는 1차 후보가 될 수 있다.

## 4. adaptive threshold 관찰

`surge_threshold_history` 최근 row는 threshold 0.5, regime BEAR, reason `base=0.380, win_rate=None,
regime=BEAR` 패턴이었다.

`run_surge_signal_generation()`은 threshold를 계산/저장하지만, 후보 생성은 `surge_detector.py` 내부
regime threshold와 bypass 조건을 중심으로 동작한다. 즉 현재 threshold history가 예측 생성 수를
직접 통제한다고 단정할 수 없다.

## 5. 운영 복구 기록

2026-07-28 actual outcome은 처음에 비어 있었다. 수동 수집 시 mapper import 누락으로 untracked movers가
섞인 중간 상태가 있었고, 이후 `stocks` 마스터 교집합 기준으로 정리했다.

최종 상태:

```text
surge_actual_outcome 2026-07-28 rows: 121
was_surge rows: 23
unresolved stock_name rows: 0
surge_prediction_evaluation 2026-07-28 rows: 1
```

## 6. 결론

우선순위:

1. 평가 기록 불변성: 이미 P0/P1로 최소 수정 가능하며 위험이 낮다.
2. 평가 스냅샷: 과거 디버깅 재현성 확보에 필요하다.
3. Pool C 중심 bridge 후보화: scannable actual 미스에 직접 닿는 개선이다.
4. Pool A/D 확장: source absent 비중이 크므로 별도 소스 개선으로 이어진다.
5. adaptive threshold 연결: 현재 threshold가 실질 gate인지 정책 명확화가 먼저다.
