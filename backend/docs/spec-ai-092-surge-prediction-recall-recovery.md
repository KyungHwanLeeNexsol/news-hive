# SPEC-AI-092: 급등 예측 재현율 회복 1차 개선안

작성일: 2026-07-28
범위: T-1 급등 예측(`FundSignal.signal_type="surge_candidate"`)의 평가 기록 안정화, 스캔 유니버스와 탐지 후보 간 배선 개선, 운영 평가 누락 방지

정본 SPEC 산출물: `.moai/specs/SPEC-AI-092/`

## 배경

2026-07-28 운영 DB 점검 결과, 급등 예측 실패의 주된 원인은 단일 탐지기 점수 튜닝보다 구조적 입력 손실에 가깝다.

- 2026-07-01 이후 평가일 18개 기준:
  - 예측 205개
  - 실제 급등 1086개
  - TP 8개
  - micro precision 3.90%
  - 시장 전체 recall 0.74%
  - 스캔 가능 종목 기준 recall 5.03%
  - coverage 14.64%
- 2026-07-28 평가:
  - 예측 7개
  - 실제 급등 23개
  - TP 0개
  - scannable actual 4개
  - coverage 17.39%
- 2026-07-28 non-scannable 19개 원인:
  - 소스 부재(absent) 11개
  - 후보 풀에는 있었지만 scan universe cap에서 탈락(truncated) 8개

`SPEC-AI-089`는 스캔 유니버스와 탐지망 간극을 측정하는 M1 스파이크다. 본 문서는 그 다음 단계로, 측정 결과를 실제 예측 후보 생성과 평가 안정성에 반영하기 위한 구현 요구사항을 정의한다.

## 현재 문제

### P0. 평가 기록 누락

2026-07-28 운영 서버에서 실적 수집/평가가 누락되어 `surge_prediction_evaluation` 레코드가 없었다. 서비스 재시작 시점과 수집 시간대가 겹친 것으로 보이며, 운영 DB에는 같은 날짜 실제 급등 결과도 비어 있었다.

P0 수동 복구는 완료했다.

- `surge_actual_outcome` 2026-07-28 수집 및 종목 마스터 기준 정리
- `surge_prediction_evaluation` 2026-07-28 생성
- 최종 actual rows 121개, was_surge 23개

### P1. 과거 예측 기록 드리프트

`GET /api/surge-trading/prediction-history`가 평가 테이블의 `predicted_count`를 사용하지 않고 현재 `FundSignal.created_at` 기준으로 시그널을 재조회해 카운트를 재계산했다.

`FundSignal.created_at`은 carry-over/update 경로에서 후일 날짜로 이동할 수 있으므로 과거 평가 당시의 공식 예측 수와 API 표시값이 달라진다.

### P1. 스캔 유니버스가 실제 탐지 입력으로 충분히 연결되지 않음

`gather_surge_candidates()`는 탐지기 결과를 먼저 `merged`에 합친 뒤 `build_scan_universe()`를 호출한다. 이때 스캔 유니버스는 pool count와 universe member 영속화 및 평가 지표에 쓰이지만, `merged`에 없는 universe member를 새 후보로 평가하는 경로가 제한적이다.

2026-07-28 기준 scannable actual 4개 중:

- 3개는 전일 Pool C에 있었지만 `surge_candidate` 신호가 없었다.
- 1개는 `gap_pullback_candidate`만 있었고 공식 `surge_candidate` 예측에는 들어가지 않았다.

즉, 유니버스에 들어온 종목도 공식 급등 예측 후보로 승격되지 않는 간극이 있다.

### P2. adaptive threshold가 후보 생성 컷에 직접 연결되지 않음

`run_surge_signal_generation()`은 adaptive threshold를 계산/저장하지만, 실제 후보 생성 자격 판정은 `surge_detector.py` 내부 regime threshold와 bypass 조건 중심으로 동작한다. 운영상 threshold history가 존재해도 예측 생성 품질에 직접 반영되지 않을 수 있다.

## 목표

1. 과거 평가 기록은 평가 당시의 공식 결과를 정본으로 유지한다.
2. 스캔 유니버스에 들어온 종목 중 탐지망 미커버 종목을 비용 제한 안에서 후보화할 수 있게 한다.
3. adaptive threshold가 실제 후보 생성 또는 후보 승격 판단에 쓰이는지 명확히 한다.
4. 실적 수집/평가 누락을 운영상 탐지하고 복구 가능하게 한다.
5. 모든 예측 로직 변경은 feature flag로 단계 배포한다.

## 비목표

- 당일 장중 급등 추격(`horizon="same_day"`)을 표준 T-1 -> T recall에 섞지 않는다.
- BEAR regime의 매수 실행 차단 정책을 본 문서에서 변경하지 않는다.
- LLM miss analysis 품질 개선은 본 문서 범위가 아니다.
- 모든 시장 급등주를 예측 대상으로 삼지 않는다. coverage와 scannable recall을 분리해서 관리한다.

## 요구사항

### REQ-AI092-001: 평가 완료 기록의 불변성

시스템은 평가 완료 행의 `predicted_count`, TP/FP/FN, precision/recall/f1을 API 응답에서 평가 테이블 값 기준으로 반환해야 한다.

- `FundSignal.created_at` 현재값으로 과거 `predicted_count`를 재계산하지 않는다.
- 상세 시그널 목록은 현재 DB에서 조회할 수 있으나, 조회 결과 길이를 공식 평가 카운트로 사용하지 않는다.
- 다음 단계에서는 평가 당시 `predicted_set` 코드 목록을 스냅샷으로 저장하는 방안을 검토한다.

### REQ-AI092-002: 평가 스냅샷 설계

시스템은 평가 당시 공식 예측 종목 집합을 재현 가능하게 저장해야 한다.

허용 구현안:

- `surge_prediction_evaluation.predicted_codes_json`
- 또는 `surge_prediction_signal_snapshot(evaluation_date, signal_date, stock_code, signal_id, metadata_json, confidence, basis_json)`

필수 조건:

- `created_at` 후일 변경과 무관하게 당시 predicted set을 복원할 수 있어야 한다.
- near-limit carry, same-day horizon 제외 규칙 적용 후의 공식 set이어야 한다.
- 기존 평가 테이블 조회 API는 하위 호환 필드를 유지해야 한다.

### REQ-AI092-003: 스캔 유니버스 bridge 후보화

시스템은 `build_scan_universe()` 결과 중 `merged`에 없는 종목을 제한된 비용 안에서 bridge 후보로 평가할 수 있어야 한다.

필수 조건:

- feature flag 기본값은 OFF다.
- flag OFF 상태에서 기존 `gather_surge_candidates()` 출력은 기존과 동일해야 한다.
- 신규 네트워크 호출은 기본적으로 금지한다. 이미 수집된 DB 데이터, universe entry pool, 직전 가격/등락률, 공시/뉴스 관계만 사용한다.
- bridge 후보에는 `surge_basis`에 `scan_universe_bridge`와 원 entry pool을 기록한다.
- bridge 후보는 기존 공식 평가 지평 규칙을 따른다. `same_day` 후보는 표준 T-1 -> T 평가에서 제외된다.

권장 1차 스코어링:

- Pool C: 전일 등락률 5% 이상, 거래량/뉴스 동반 여부, 섹터 동조 여부를 가산
- Pool A: 공시 impact score, unreflected gap, 공시 유형 whitelist를 가산
- Pool D: 뉴스 언급량 증가, 직접 매핑 뉴스 수, 중복 기사 제거 후 유효 기사 수를 가산
- bridge 전용 최대 후보 수를 둔다. 예: pool별 10개, 전체 30개

### REQ-AI092-004: adaptive threshold 연결성

시스템은 adaptive threshold가 후보 생성 또는 후보 저장 판단에 실제로 사용되는지 테스트로 보장해야 한다.

허용 구현안:

- `gather_surge_candidates()`에 effective threshold 인자를 주입한다.
- 또는 `compute_ensemble_score()` 이후 최종 저장 gate에서 `SurgeThresholdHistory`의 당일 threshold를 사용한다.

필수 조건:

- threshold history가 존재하는 날과 없는 날의 fallback 경로를 테스트한다.
- BEAR regime에서 threshold가 높아진다면 예측 생성 수 변화가 관찰 가능해야 한다.
- 매수 실행 threshold와 예측 생성 threshold가 다르면 명시적으로 분리 명명한다.

### REQ-AI092-005: 운영 평가 누락 감시

시스템은 영업일 기준 실적 수집과 평가 레코드 누락을 탐지해야 한다.

필수 조건:

- 장마감 이후 기대 시각까지 `surge_actual_outcome.trading_date = today` 행이 없으면 경고 로그 또는 알림을 남긴다.
- `surge_prediction_evaluation.evaluation_date = today` 행이 없으면 경고 로그 또는 알림을 남긴다.
- 수동 재실행은 idempotent해야 한다.
- untracked market movers가 `surge_actual_outcome`에 섞이지 않도록 `stocks.stock_code` 기준 정리 또는 수집 단계 필터를 보장한다.

## 수용 기준

### AC-092-001: prediction-history 카운트 불변

평가 완료 행이 있고 해당 날짜의 `FundSignal.created_at`이 후일로 이동해도 `/prediction-history`의 `predicted_count`는 `SurgePredictionEvaluation.predicted_count`와 같아야 한다.

### AC-092-002: bridge flag OFF 무회귀

`scan_universe_bridge_candidates_enabled=false` 상태에서 동일 fixture의 `gather_surge_candidates()` 결과는 기존 결과와 동일해야 한다.

### AC-092-003: bridge 후보 생성

flag ON 상태에서 `build_scan_universe()`에는 있으나 `merged`에는 없는 Pool C 종목이 bridge scoring 최소 조건을 만족하면 `surge_candidate` 후보로 생성되어야 한다.

### AC-092-004: 비용 예산

bridge 후보화는 universe member당 외부 API 호출을 추가하지 않아야 한다. 테스트는 Naver/DART fetch mock 호출 수가 기존 대비 증가하지 않음을 검증해야 한다.

### AC-092-005: 평가 스냅샷 복원

평가 후 동일 종목의 `FundSignal.created_at`이 변경되어도 평가 스냅샷에서 당시 predicted set을 복원할 수 있어야 한다.

### AC-092-006: adaptive threshold 실사용

threshold를 0.30과 0.70으로 고정한 테스트 fixture에서 저장되는 후보 수가 달라져야 한다. 후보 수가 동일하면 threshold가 실제 생성 gate에 연결되지 않은 것으로 본다.

### AC-092-007: 운영 누락 감시

평가 기준일의 actual/evaluation 레코드가 없을 때 감시 함수는 누락 상태를 반환하고, 레코드가 있으면 정상 상태를 반환해야 한다.

## 구현 순서

1. P0 기록 안정화
   - `/prediction-history` evaluated row는 stored metric을 사용한다.
   - 회귀 테스트로 `created_at` drift 케이스를 고정한다.

2. P1 평가 스냅샷
   - 스키마 변경 여부 결정.
   - 공식 predicted set 저장.
   - `/evaluation/{date}`와 `/prediction-history`의 상세 목록을 snapshot 우선으로 전환.

3. P1 bridge 후보화
   - config flag 추가.
   - `SPEC-AI-089` 측정 결과를 기반으로 pool별 bridge 후보 생성.
   - no extra network invariant 테스트.

4. P2 adaptive threshold 연결
   - 예측 생성 threshold와 매수 실행 threshold를 분리 명명.
   - 생성 gate 테스트 추가.

5. P2 운영 감시
   - daily health check 또는 scheduler 후속 검증 추가.
   - 누락 시 관리자 알림 또는 명시 로그.

## 검증 SQL

최근 평가 성능:

```sql
select
  count(*) as eval_days,
  sum(predicted_count) as predicted,
  sum(actual_surge_count) as actual,
  sum(true_positive) as tp,
  sum(false_positive) as fp,
  sum(false_negative) as fn,
  round((sum(true_positive)::numeric / nullif(sum(predicted_count), 0)), 4) as precision_micro,
  round((sum(true_positive)::numeric / nullif(sum(actual_surge_count), 0)), 4) as recall_market_micro,
  sum(scannable_actual_count) as scannable_actual,
  round((sum(scannable_actual_count)::numeric / nullif(sum(actual_surge_count), 0)), 4) as coverage_micro,
  round((sum(true_positive)::numeric / nullif(sum(scannable_actual_count), 0)), 4) as scannable_recall_micro
from surge_prediction_evaluation
where evaluation_date >= date '2026-07-01'
  and actual_surge_count > 0;
```

평가 누락 점검:

```sql
select current_date as today,
  exists (
    select 1 from surge_actual_outcome where trading_date = current_date
  ) as has_actuals,
  exists (
    select 1 from surge_prediction_evaluation where evaluation_date = current_date
  ) as has_evaluation;
```

유니버스 내부 actual 중 무신호 점검:

```sql
with actual as (
  select stock_code
  from surge_actual_outcome
  where trading_date = date '2026-07-28'
    and was_surge is true
),
prev_universe as (
  select stock_code, entry_pool
  from surge_universe_members
  where trading_date = date '2026-07-27'
),
signals as (
  select s.stock_code, fs.signal_type
  from fund_signals fs
  join stocks s on s.id = fs.stock_id
  where date(fs.created_at) = date '2026-07-27'
)
select
  a.stock_code,
  coalesce(u.entry_pool, 'absent') as entry_pool,
  array_agg(distinct signals.signal_type) filter (where signals.signal_type is not null) as signal_types
from actual a
left join prev_universe u on u.stock_code = a.stock_code
left join signals on signals.stock_code = a.stock_code
group by a.stock_code, coalesce(u.entry_pool, 'absent')
order by entry_pool, a.stock_code;
```

## 롤백 기준

bridge 후보화 flag ON 이후 다음 중 하나가 발생하면 즉시 OFF로 되돌린다.

- 일별 예측 수가 기존 14일 평균 대비 3배 이상 증가
- precision이 5거래일 연속 0%
- 외부 fetch 호출 수가 기존 대비 증가
- scheduler runtime이 기존 대비 30% 이상 증가
- same-day 후보가 표준 T-1 -> T predicted set에 섞임

## 열린 질문

1. bridge 후보의 1차 목표는 coverage 개선인가, scannable recall 개선인가?
2. Pool C는 30개 floor를 유지할지, truncated가 반복되는 날에 동적으로 늘릴지 결정이 필요하다.
3. 평가 스냅샷은 JSON 컬럼으로 충분한가, 별도 테이블이 필요한가?
4. actual outcome 수집 대상은 상위 movers 전체를 보존할지, `stocks` 마스터 종목만 저장할지 정책 결정이 필요하다.
