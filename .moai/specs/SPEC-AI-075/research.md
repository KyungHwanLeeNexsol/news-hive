# SPEC-AI-075 Research — near_limit_up_carry 평가 시점 불일치(evaluation-timing) 버그

조사 완료일: 2026-07-08. 본 문서는 별도 디버깅 조사(read-only, 코드 검증 + 프로덕션 데이터 검증)로
확정된 진단을 구조화한 것이며, 라인 번호는 2026-07-08 기준 실측 재확인 결과다. 본 SPEC은 **평가
(evaluation) 측면만** 다루며 탐지기·신호 생성·스케줄·매매 로직을 바꾸지 않는다.

---

## 1. 문제 요약 (한 문장)

`evaluate_surge_predictions()`(`surge_evaluation_service.py:482`)는 모든 `signal_type=="surge_candidate"`
시그널을 **동일한 "T-1 데이터로 익일(T) 예측" 지평(horizon)** 으로 가정해 T-1 버킷 대 T 실제급등을
비교한다. 그러나 `near_limit_up_carry` 탐지기 한 종은 지평이 다르다 — 시그널을 **발행한 바로 그 날
(day D)** 의 연속성을 예측한다. 그 결과 D에 발행된 near_limit_up_carry 시그널이 evaluation_date=**D+1**
실행에서 D+1 실제급등과 비교되어 **체계적으로 하루 늦게, 잘못된 날과 대조**된다.

---

## 2. 표준 평가 규칙 — 코드 위치 / 실제 동작

- **진입점**: `evaluate_surge_predictions(db, trading_date, pool_counts)` — `surge_evaluation_service.py:482`
  (18:30 KST `_run_surge_verify_predictions` 경로에서 호출). docstring `:495-516`은 "T-1 시그널 vs T
  당일 실제급등 비교"라 명시.
- **T-1 산출**: `:518` `prev_business_day = _get_prev_business_day(trading_date)`.
- **predicted_set 조립 (핵심 지점)**: `:523-536`
  ```python
  # preday_disclosure는 제외: 공시 기반 단기 반응 예측이므로 was_surge(10%+) 기준과 불일치
  signal_rows = (
      db.query(FundSignal.stock_id, Stock.stock_code)
      .join(Stock, FundSignal.stock_id == Stock.id)
      .filter(
          FundSignal.signal_type == "surge_candidate",
          FundSignal.surge_metadata.isnot(None),
          sqlfunc.date(FundSignal.created_at) == prev_business_day,
      )
      .all()
  )
  predicted_set: set[str] = {row.stock_code for row in signal_rows}
  ```
  — `signal_type=="surge_candidate"` AND `surge_metadata IS NOT NULL` AND `date(created_at)==T-1`.
  **쿼리는 `stock_id, stock_code`만 SELECT하며 `surge_metadata` 내용은 읽지 않는다.**
- **actual_set**: `:547-559` — `SurgeActualOutcome.was_surge==True AND trading_date==T` (시장전체 top-mover
  기준, signal_type 무관).
- **TP/FP/FN/precision/legacy_recall**: `:561-574`. **scannable_recall/coverage**: `:581-628`
  (SPEC-AI-068, `predicted_set` 그대로 재사용).

near_limit_up_carry 오염이 `predicted_set` 한 곳에서 발생하므로, 그 하위의 predicted_count/TP/FP/
precision/legacy_recall/scannable_recall/coverage **전부**가 함께 오염된다.

---

## 3. [핵심 정정] preday_disclosure 제외는 `surge_metadata` 필터가 아니라 `signal_type` 필터다

작업 지시(2차 정보)는 "기존 `preday_disclosure` 제외 패턴을 **동일 코드 형태(same code shape)로**
그대로 미러링"하라고 했으나, **코드 실측 결과 그 전제는 부정확하다.**

- `:524`의 주석 "preday_disclosure는 제외 …"는 **왜** preday_disclosure가 이 버킷에 없는지를 설명하는
  주석일 뿐, 실제 제외는 **`signal_type` 값 자체**로 이뤄진다. `preday_disclosure` 시그널은
  `signal_type == "preday_disclosure"`(별개 값, `preday_signal_service.py:30`
  `PREDAY_SIGNAL_TYPE = "preday_disclosure"`)를 갖는다. 따라서 `:529`의 `signal_type=="surge_candidate"`
  필터에 **애초에 걸리지 않아** 자동 제외된다. **surge_metadata를 들여다보지 않는다.**
- 반면 `near_limit_up_carry` 시그널은 `signal_type == "surge_candidate"`(`surge_detector.py:2763`, 실측)
  로 생성된다 — 표준 지평 탐지기들과 **같은 signal_type을 공유**한다. 그러므로 `:529` 필터를 **통과**하며,
  signal_type 기반으로는 제외가 불가능하다.
- **결론**: near_limit_up_carry 제외는 preday_disclosure와 **근거 범주(rationale category)는 동일**
  (지평 불일치, horizon mismatch)하지만 **코드 형태는 반드시 다르다** — signal_type 필터가 아니라
  `surge_metadata` **내용 기반 필터**(신규 필터 형태)가 필요하다. 이 정정이 본 SPEC의 중심 설계 제약이다.

---

## 4. near_limit_up_carry의 `surge_metadata` 권위 필드 (실측)

`detect_near_limit_up_carries()`(`surge_detector.py:2649`, SPEC-AI-023/072 소유)가 시그널마다 쓰는
metadata dict (`:2751-2756`, `:2766`에서 `json.dumps(..., ensure_ascii=False)`로 문자열 저장):

```python
metadata = {
    "surge_basis": ["near_limit_up_carry"],       # (1) 리스트 — 정본 탐지기 귀속
    "yesterday_change_pct": round(change_rate, 2),
    "surge_probability_score": confidence,
    "near_limit_up_carry": True,                   # (2) 플랫 불리언 플래그 (중복 편의 키)
}
```

- **두 키가 모두 존재**한다(작업 지시의 관찰이 맞았다): `surge_basis` 리스트 멤버십과 플랫
  `near_limit_up_carry: true`.
- **권위 필드 판단**: `surge_basis` 리스트 멤버십(`"near_limit_up_carry" in surge_basis`)을 **1차(정본)**
  판별 기준으로 삼는다 — `surge_basis`는 코드베이스 전반에서 탐지기 귀속의 정본
  (memory: `surge_basis == candidate.active_detectors`)이고, 다른 표준 탐지기/평가/기여도 로직도 이
  리스트를 소비한다. 플랫 `near_limit_up_carry: true`는 **보강용 OR 폴백**으로만 활용해 견고성을 높인다
  (둘 중 하나라도 참이면 near_limit_up_carry로 식별). 단, 다른 표준 탐지기의 metadata에는 이 두 키가
  없으므로 오탐 위험은 없다.
- **주의(HOW, plan.md에서 확정)**: 현재 `:525-534` 쿼리는 `surge_metadata`를 SELECT하지 않으므로,
  내용 필터를 위해 `surge_metadata`를 함께 조회해 **Python 측에서 파싱·판별**해야 한다. 테스트는
  SQLite, 프로덕션은 PostgreSQL이므로 DB별 JSON 연산자에 의존하지 말고 Python `json.loads` 후 리스트
  멤버십 검사를 하는 것이 이식성 있다(문자열 LIKE 매칭은 취약 — `surge_basis` 순서/공백 변형 위험).

---

## 5. 왜 하루 늦는가 (인과)

- `near_limit_up_carry` docstring(`:2653-2658`): "전일(T-1) 상한가 근접 종목에 **익일** surge_candidate
  시그널 발행". 여기서 "익일"은 **T-1 기준의 다음 거래일 = 시그널이 실제로 발행되는 날(day D)**. 즉
  시그널은 D의 연속 모멘텀을 예측한다(SPEC-AI-072가 change_rate를 T-1 종가-대-종가로 교정한 것도
  "D에 대한 예측" 의미를 정확히 하기 위함이었다).
- 이 탐지기는 10:00 KST 장중 잡과 15:20 KST 메인 잡 **양쪽에서 동일 경로로 실행**된다(분기 없음):
  `scheduler.py`의 두 잡 → `_run_surge_signal_generate` → `run_surge_signal_generation`
  (`fund_manager.py:2982`) → `_gather_surge_candidates` + `_run_coverage_expansion`
  (`fund_manager.py:3855`, near_limit_up 호출부 `:3921`). 두 잡 모두 같은 함수를 부르므로 near_limit_up_carry
  시그널의 target-day 의미는 동일하게 D다.
- 표준 평가 규칙은 evaluation_date=D+1 실행에서 `predicted_set`을 **T-1=D** 버킷으로 조립한다. 그 버킷에
  D에 발행된 near_limit_up_carry 시그널이 포함되어 **D+1**의 실제급등과 비교된다 → target day(D)가 이미
  지난 시점에 잘못된 날(D+1)과 대조. 랜덤이 아니라 **체계적으로 1거래일 늦다.**

---

## 6. 정량적 영향 (라이브 프로덕션 쿼리, read-only, 2026-07-08)

| date | near_limit_up_carry_count | total_surge_candidate_count | 비중 |
|------|---------------------------:|----------------------------:|-----:|
| 2026-07-08 | 4  | 15 | 27% |
| 2026-07-07 | 9  | 12 | 75% |
| 2026-07-06 | 7  | 7  | 100% |
| 2026-07-03 | 4  | 17 | 24% |
| 2026-07-02 | 0  | 7  | 0% |
| 2026-07-01 | 0  | 29 | 0% |
| 2026-06-30 | 0  | 4  | 0% |

- **무시할 수 있는 엣지 케이스가 아니다.** 2026-07-06/07-07은 이 프로젝트의 최근 근본원인 조사가
  "recall crisis" 증거로 삼은 바로 그 이틀인데, near_limit_up_carry가 전체 surge_candidate 발신의
  **100%(7/7)와 75%(9/12)** 를 차지했다.
- **결정적 사례**: evaluation_date=2026-07-07 레코드(`predicted_count=7, TP=0, recall=0.0`)의
  predicted_set 7건 전부가 2026-07-06 발신분에서 왔고, 2026-07-06은 **100% near_limit_up_carry(7/7)**
  였다. 즉 그 0%-recall 데이터 포인트는 **전부 잘못된 날과 비교된 시그널**로 구성돼 있었다.

### 오염 메커니즘의 정확한 서술 (작업 지시의 "inflate FN" 표현 정정)

near_limit_up_carry 시그널이 `predicted_set`에 섞이면 **predicted 측**이 오염된다:
- `predicted_count` 인위적 팽창(잘못된 지평의 시그널을 T 예측으로 계상),
- 이들이 D+1 실제급등에 대체로 미매칭 → **FP 팽창 → precision 하락**,
- 결과적으로 predicted_count/TP/FP/precision/legacy_recall/scannable_recall/coverage **집계 전체**가
  표준 지평(Pool A/B/C) 탐지기 성능을 순수하게 반영하지 못하게 된다.

**정정**: 작업 지시의 "inflate FN"은 부정확하다. `FN = |actual − predicted|`이므로 predicted에서
near_limit_up_carry를 제거해도 FN이 줄어들지 않는다(오히려 미소 증가 가능). 본 SPEC이 겨냥하는 실제
왜곡은 **predicted 측 오염**(잘못된 지평 시그널이 표준 지평 예측인 척 계상됨)이며, characterization
테스트도 "near_limit_up_carry가 현재 predicted_set/predicted_count에 **포함**되었다가 수정 후 **제외**"
라는 **관찰 가능한 사실**로 고정한다(FN 방향을 단정하지 않는다).

---

## 7. Pool C 판단 오염 (본 버그가 지금 시급한 이유)

- `near_limit_up_carry`는 Pool A/B/C 스캔 유니버스를 **전혀 사용하지 않는다** — 시총 상위 stocks를 직접
  스캔하는 T-1-종가 기반 검사(`build_scan_universe`와 무관, `surge_detector.py:2705-2716`).
- 이 프로젝트는 SPEC-AI-073(DART/Pool A 복구), SPEC-AI-074(Pool B ETF 오염 제거)를 막 완료했고,
  **2026-07-09부터** `surge_prediction_evaluation`의 `coverage`가 역사적 상한(~0.28~0.30)을 넘어서는지
  관찰해 **Pool C의 구조적 필요성**을 판단할 예정이다.
- 그런데 near_limit_up_carry의 오라벨 시그널이 스키마 어디에도 per-detector 분해 없이 동일한 집계
  `predicted_count`/`coverage`/`recall`에 접혀 들어가므로, **그 판단에 쓰일 지표를 직접 교란**한다.
  2026-07-09 이전에 고치면 coverage가 Pool A/B/C의 실제 기여를 더 순수하게 반영해 Pool C 판단이
  깨끗해진다.

---

## 8. 기존 테스트 자산 (실측)

- **`backend/tests/test_surge_evaluation_service.py`** — `evaluate_surge_predictions`의 정본 테스트
  파일. `TestEvaluateSurgePredictionsCharacterization`(`:202`)에 `_setup()` 헬퍼(`:205`)가 있어
  `predicted_codes`/`actual_surge_codes`로 FundSignal(`signal_type="surge_candidate"`,
  `surge_metadata='{"surge_basis": ["theme_cluster"], ...}'`, `created_at=T-1 15:20`) +
  SurgeActualOutcome를 세팅한다. `test_characterize_predicted_count_from_t_minus_1_surge_candidate_signals`
  (`:267`)가 확장 지점 — 이 헬퍼에 near_limit_up_carry metadata 시그널 주입을 추가하면 재현 테스트를
  최소 변경으로 구성할 수 있다.
- **`backend/tests/test_surge_evaluation_service_ai060.py`** — SPEC-AI-060 관련 평가 테스트(참고).
- **`backend/tests/test_near_limit_up_carry.py`** — 탐지기(`detect_near_limit_up_carries`) 자체 테스트.
  **본 SPEC은 탐지기를 안 건드리므로 이 파일은 변경 대상 아님**(회귀만 확인).
- **정정**: 작업 지시가 언급한 `test_surge_ai041.py`는 **존재하지 않는다**. SPEC-AI-041 평가 로직 테스트는
  `test_surge_evaluation_service.py`에 통합돼 있다(`glob '*ai041*'` = 0건 실측).

---

## 9. 선택된 접근

- **평가 측 단일 지점 수정**: `evaluate_surge_predictions()`의 `predicted_set` 조립(`:523-536`)에서
  `surge_metadata` 내용으로 near_limit_up_carry 시그널을 배제. 근거 범주는 기존 preday_disclosure 주석과
  동일(지평 불일치)하되 코드 형태는 **metadata 내용 필터**(신규)로 한다(§3).
- **predicted 측에만 적용**: `actual_set`(시장전체 실제급등)과 표준 지평 버킷팅 규칙 자체는 불변(§2).
- **동일-당일(T→T) 평가 경로는 미구현** — near_limit_up_carry의 진짜 성능을 정확히 측정하는 별도 지평
  평가는 **별도 미래 SPEC로 유예**. 본 SPEC의 범위는 엄격히 "잘못된 날 비교가 집계 지표를 교란하는 것을
  멈추는 것"이지 "near_limit_up_carry 성능을 올바로 측정하는 것"이 아니다(실매매 미개입, AI-043
  예측기록 모드라 시급성 낮음).

---

## 10. 구현 방법론 (DDD: ANALYZE-PRESERVE-IMPROVE + Reproduction-First)

`quality.yaml` `development_mode: ddd` + CLAUDE.md Section 7 Rule 4(재현 우선):

1. **ANALYZE** — `predicted_set` 조립·preday_disclosure 제외 실제 메커니즘·near_limit_up_carry
   metadata 형태 매핑(위 §2/§3/§4 완료).
2. **PRESERVE / 재현 우선** — 수정 **전**에 실패 characterization 테스트 작성: T-1 버킷에 near_limit_up_carry
   metadata를 가진 surge_candidate 시그널이 있을 때 현재 `predicted_set`/`predicted_count`에 **포함**됨을
   포착(현행에서 "포함되지 않는다"를 기대하면 실패). 07-06/07-07형 시나리오(predicted_set이 near_limit_up_carry
   지배) 재현. 기존 `TestEvaluateSurgePredictionsCharacterization` 전량 GREEN 유지 확인.
3. **IMPROVE** — `predicted_set` 조립에 near_limit_up_carry 배제(metadata 파싱 필터)를 최소 변경으로 적용,
   재현 테스트가 통과(배제 후 predicted_count에서 제외)하고 표준 지평 케이스 무회귀임을 확인.
