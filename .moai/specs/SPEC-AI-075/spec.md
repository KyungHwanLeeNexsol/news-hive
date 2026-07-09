---
id: SPEC-AI-075
version: 1.0.0
status: completed
created: 2026-07-08
updated: 2026-07-08
author: MoAI
priority: High
issue_number: 0
---

# SPEC-AI-075: near_limit_up_carry 평가 시점 불일치 교정 (Evaluation-Timing Horizon Mismatch Fix)

## HISTORY

- 2026-07-08 (v1.0.0): **구현 완료** — 급등예측 평가 시스템에서 near_limit_up_carry 지평 불일치 버그 수정.
  commit: `811b340`, 테스트: `test_surge_evaluation_service.py` 181 라인 확장, 전체 1905건 PASS.
  AC-075-001~003 전부 충족. 스캔 유니버스 절단 버그(SPEC-AI-076)의 전제 정화 완료.

- 2026-07-08 (v0.1.0): 최초 작성. 별도 디버깅 조사(read-only, 코드 검증 + 프로덕션 데이터 검증)로 확정된
  **평가(evaluation) 시점 불일치 버그**를 SPEC화.
  - **버그**: `evaluate_surge_predictions()`(`surge_evaluation_service.py:482`)는 모든
    `signal_type=="surge_candidate"` 시그널을 "T-1 데이터로 익일(T) 예측"이라는 **단일 지평**으로 가정해
    `date(created_at)==T-1` 버킷(predicted_set)을 T 실제급등과 비교한다(`:523-536`). 그러나
    `near_limit_up_carry` 탐지기(`detect_near_limit_up_carries`, `surge_detector.py:2649`, SPEC-AI-023/072
    소유)는 지평이 다르다 — 시그널을 **발행한 그 날(day D)** 의 연속성을 예측한다. 평가 규칙이 탐지기/
    시그널 출처를 구분하지 않으므로, D에 발행된 near_limit_up_carry 시그널이 evaluation_date=**D+1**
    실행에서 D+1 실제급등과 비교되어 **체계적으로 1거래일 늦게, 잘못된 날과 대조**된다.
  - **정량 근거(라이브, 2026-07-08)**: near_limit_up_carry가 전체 surge_candidate 발신에서 차지한 비중 —
    2026-07-06 **100%(7/7)**, 2026-07-07 **75%(9/12)**, 2026-07-08 27%(4/15), 2026-07-03 24%(4/17).
    evaluation_date=2026-07-07(`predicted_count=7, TP=0, recall=0.0`)의 predicted_set 7건 전부가
    2026-07-06(100% near_limit_up_carry) 발신분 → 그 0%-recall 데이터 포인트는 **전부 잘못된 날과 비교된
    시그널**로 구성돼 있었다.
  - **선택 접근**: 평가 측 단일 지점(`predicted_set` 조립)에서 near_limit_up_carry 시그널을
    `surge_metadata` 내용 기반으로 배제. 근거 범주는 기존 `preday_disclosure` 제외(`:524` 주석)와 동일한
    지평 불일치이나, **코드 형태는 다르다**(research.md §3 참조 — preday_disclosure는 signal_type-level
    제외, near_limit_up_carry는 signal_type을 공유하므로 metadata-content 필터 필요).

---

## 선행 SPEC / 관계 (Assumptions & Relationships)

각 항목은 2026-07-08 코드 재확인 결과다. 본 SPEC은 **평가 측면만** 복구하며 탐지기·신호 생성·스케줄·
매매 로직을 바꾸지 않는다.

- **SPEC-AI-023/072 (near_limit_up_carry 탐지기) — 탐지기 본체 불변**: `detect_near_limit_up_carries`
  (`surge_detector.py:2649`)의 시그널 생성 로직, SPEC-AI-072의 T-1 종가-대-종가 change_rate 교정, 스케줄
  (10:00/15:20 KST), `surge_metadata` 구조는 모두 **불변**. 본 SPEC은 이 탐지기가 이미 쓰고 있는
  `surge_metadata`(`surge_basis: ["near_limit_up_carry"]` + 플랫 `near_limit_up_carry: true`, `:2751-2756`)
  를 **읽어 식별**할 뿐이다.
- **SPEC-AI-041/043 (급등예측 평가·자가개선, 예측기록 모드) — 평가 지표 품질 개선(비충돌)**:
  `evaluate_surge_predictions`는 AI-041 소유 평가 함수다. 본 SPEC은 그 predicted_set 조립 규칙만 정제해
  near_limit_up_carry 오염을 제거한다. 실매매 미개입(AI-043 예측기록 모드) — 매수 로직 diff 0. 시급성이
  낮은 이유(자금 리스크 없음)이기도 하다.
- **SPEC-AI-068 (Scannable Recall/Coverage) — 동일 predicted_set 재사용이므로 함께 정제됨**:
  scannable_recall/coverage(`:581-628`)는 `predicted_set`을 그대로 재사용한다. predicted_set에서
  near_limit_up_carry를 제거하면 이 지표들도 함께 표준 지평만 반영하게 된다.
- **SPEC-AI-073/074 (Pool A/B 복구) 및 예정된 Pool C 판단 — 본 SPEC이 판단 지표를 정화**: 2026-07-09부터
  `surge_prediction_evaluation.coverage`가 역사적 상한(~0.28~0.30)을 넘는지로 Pool C의 구조적 필요성을
  판단할 예정인데, near_limit_up_carry(Pool A/B/C 스캔 유니버스 **미사용**, `surge_detector.py:2705-2716`)의
  오라벨 시그널이 per-detector 분해 없이 동일 집계에 접혀 들어가 그 판단을 교란한다. 본 SPEC을 07-09
  이전에 적용하면 coverage가 Pool A/B/C 실제 기여를 더 순수하게 반영한다.
- **preday_disclosure 제외 (`:524`) — 근거 범주는 재사용, 코드 형태는 상이**: 지평 불일치라는 근거는
  동일하나, preday_disclosure는 `signal_type=="preday_disclosure"`라 `:529` 필터에 애초에 안 걸려 자동
  제외된다(surge_metadata 미확인). near_limit_up_carry는 `signal_type=="surge_candidate"`
  (`surge_detector.py:2763`)를 공유하므로 **metadata 내용 필터**(신규 형태)가 필요하다.

---

## Environment (환경/전제)

- Backend: Python 3.12+, FastAPI, SQLAlchemy 2.0, PostgreSQL 16(프로덕션) / SQLite(테스트). 배포: OCI VM
  베어메탈 + systemd(`newshive`). 운영 모드: **예측 기록 전용(실매매 비활성)** — 자금 리스크 없음.
- 대상 코드: `backend/app/services/surge_evaluation_service.py`의 `evaluate_surge_predictions()`
  `predicted_set` 조립 지점(`:523-536`)만.
- 대상 테스트: `backend/tests/test_surge_evaluation_service.py`(정본 평가 테스트,
  `TestEvaluateSurgePredictionsCharacterization` 확장).
- 데이터 사실(실측 2026-07-08):
  - `predicted_set` 필터는 `signal_type=="surge_candidate"` AND `surge_metadata IS NOT NULL` AND
    `date(created_at)==T-1`(`:529-531`)이며 **`surge_metadata` 내용은 읽지 않는다**(`stock_id, stock_code`만
    SELECT).
  - near_limit_up_carry 시그널의 `surge_metadata`(JSON 문자열)에는 `surge_basis: ["near_limit_up_carry"]`
    (정본 귀속 리스트) + 플랫 `near_limit_up_carry: true`(중복 편의 키)가 **모두** 존재
    (`surge_detector.py:2751-2756`).
  - 프로덕션=PostgreSQL / 테스트=SQLite이므로 DB별 JSON 연산자에 의존하지 않는 방식(Python `json.loads`
    후 리스트 멤버십 검사)이 이식성 있다.
- **신규 테이블/마이그레이션 없음**(기존 함수의 필터 로직 변경만).

---

## Requirements (EARS)

### REQ-AI075-001 (P0, Unwanted Behavior) — near_limit_up_carry를 T-1→T predicted_set에서 배제

**IF** `date(created_at)==T-1`인 어떤 `surge_candidate` 시그널의 `surge_metadata`가 그 시그널을
`near_limit_up_carry` 탐지 결과로 식별하면, **THEN the system SHALL NOT** 그 시그널을
`evaluate_surge_predictions()`의 표준 T-1→T 평가 버킷(`predicted_set`, `:523-536`)에 포함해서는 안 된다.

- 근거 범주는 기존 `preday_disclosure` 제외(`:524` 주석)와 **동일**(지평 불일치 — near_limit_up_carry의
  target day는 시그널 발행일 D이며 표준 규칙이 검사하는 시점(D+1)에는 이미 지났다).
- **[HARD]** 코드 형태는 preday_disclosure와 **다르다**: preday_disclosure는 `signal_type` 값으로 제외되나
  near_limit_up_carry는 `signal_type=="surge_candidate"`를 공유하므로 `surge_metadata` **내용 기반** 필터로
  배제한다(research.md §3).
- 배제로 predicted_set이 비게 되는 것은 정상 동작이다(그 날 표준 지평 시그널이 없었다는 사실의 정직한 반영).

### REQ-AI075-002 (P0, Ubiquitous) — 식별은 `surge_metadata` 권위 필드(`surge_basis`) 기준

The system **SHALL** near_limit_up_carry 시그널을 `surge_metadata`의 **`surge_basis` 리스트 멤버십**
(`"near_limit_up_carry" in surge_basis`)으로 식별하며, `signal_type`(="surge_candidate", 표준 지평 탐지기
전부가 공유)으로는 식별하지 않는다.

- **1차(정본) 판별**: `surge_basis` 리스트 멤버십(코드베이스 전반의 탐지기 귀속 정본,
  `surge_basis == candidate.active_detectors`).
- **보강(견고성)**: 플랫 `near_limit_up_carry: true` 키를 OR 폴백으로 함께 인정할 수 있다(둘 중 하나라도
  참이면 near_limit_up_carry). 다른 표준 탐지기 metadata에는 두 키가 없어 오탐 위험이 없다.
- **[HARD]** 식별 필드는 실제 코드(`surge_detector.py:2751-2756`)에서 확인된 값에 근거한다 — 2차 정보
  추정으로 결정하지 않는다. 필터 파싱은 DB별 JSON 연산자가 아닌 이식 가능한 방식(Python `json.loads`
  후 멤버십 검사)을 사용한다.

### REQ-AI075-003 (P0, State-Driven) — 배제는 predicted 측에만, actual/표준 규칙은 불변

**WHILE** near_limit_up_carry를 `predicted_set`에서 배제하는 동안, the system **SHALL** `actual_set`
(시장전체 실제급등, `:547-559`)과 표준 지평 버킷팅 규칙(`signal_type=="surge_candidate"` AND
`surge_metadata IS NOT NULL` AND `date(created_at)==T-1`)의 그 밖의 동작을 변경하지 않아야 한다.

- 배제는 **predicted(예측) 측 한 곳**(`:523-536`)에만 적용한다 — preday_disclosure가 그 자리에서 배제되는
  것과 일관. `actual_set`은 signal_type과 무관한 시장 진실이므로 손대지 않는다(near_limit_up_carry 종목이
  T에 실제 급등했다면 그 사실은 actual_set에 그대로 남는다).
- TP/FP/FN/precision/legacy_recall(`:561-574`) 및 scannable_recall/coverage(`:581-628`) 계산식 자체는
  변경하지 않는다 — 정제된 `predicted_set`이 그대로 흘러들어 자연히 표준 지평만 반영한다.

### REQ-AI075-004 (P1, Event-Driven) — 재현 우선 characterization + 회귀 보호

**WHEN** 기존 평가 테스트 스위트가 실행되면, the system **SHALL** 그 테스트들이 계속 통과하도록 하고,
추가로 2026-07-06/07-07형 시나리오(predicted_set이 near_limit_up_carry로 지배됨)를 재현하는 신규
characterization 테스트가 **수정 전 실패 → 수정 후 통과**해야 한다.

- **[HARD] 재현 우선(CLAUDE.md Rule 4)**: 수정 **전에** 실패 테스트를 작성·확인한다 — T-1 버킷에
  near_limit_up_carry `surge_metadata`를 가진 `surge_candidate` 시그널이 있을 때 현재 `predicted_set`/
  `predicted_count`에 **포함**됨을 포착(수정 후 "제외됨"을 기대하면 현행에서 실패). 이후 배제 구현 →
  통과 확인.
- 검증은 **관찰 가능한 사실**(predicted_set 멤버십 / predicted_count 값 / 로그)로 고정하며 FN 방향을
  단정하지 않는다(research.md §6 — "inflate FN" 표현은 부정확; 실제 왜곡은 predicted 측 오염).
- `test_surge_evaluation_service.py`의 `TestEvaluateSurgePredictionsCharacterization`(`_setup` 헬퍼,
  `:205`)를 확장한다. 탐지기 테스트(`test_near_limit_up_carry.py`)는 변경하지 않고 회귀만 확인한다.
- 정정: 작업 지시가 언급한 `test_surge_ai041.py`는 **존재하지 않는다** — 평가 테스트는
  `test_surge_evaluation_service.py`에 있다.

---

## Exclusions (What NOT to Build) [HARD]

1. **동일-당일(T→T) 평가 경로 미구현.** near_limit_up_carry의 진짜 성능을 올바른 지평(발행일 D의 실제
   결과)으로 측정하는 별도 평가 경로는 **별도 미래 SPEC로 유예**한다. 본 SPEC의 범위는 엄격히 "잘못된 날
   비교가 집계 지표를 교란하는 것을 멈추는 것"이지 "near_limit_up_carry 성능을 올바로 측정하는 것"이
   아니다(실매매 미개입, AI-043 예측기록 모드라 시급하지 않음).
2. **탐지기 본체 무변경.** `detect_near_limit_up_carries()`의 시그널 생성 로직, 스케줄(10:00/15:20 KST),
   `surge_metadata` 구조, SPEC-AI-072의 T-1 종가-대-종가 교정은 모두 불변. 본 SPEC은 평가 측 전용이다.
3. **actual_set / 시장전체 모집단 무변경.** `SurgeActualOutcome`/`was_surge` 수집·기준(10%+)·
   `surge_actual_outcome_service.py`는 손대지 않는다(그건 SPEC-AI-071 영역).
4. **Pool A/B/C 스캔 유니버스 로직 무관·무변경.** near_limit_up_carry는 스캔 유니버스를 쓰지 않으므로
   `build_scan_universe`/Pool C의 구조적 후행성 한계는 완전히 별개 사안이다(별도 SPEC).
5. **다른 탐지기 지평 정렬 범위 밖.** 조사에서 `insider_purchase_signals`가 "개념상 preday_disclosure에
   가까워 재검토 가치 있음"으로 표시됐으나 **확정적으로 고장난 것은 아니다** — 추가 조사 없이 범위를
   넓히지 않는다. 가능한 향후 후속으로만 기록.
6. **과거 데이터 소급 재계산/백필 금지.** 과거 `surge_prediction_evaluation` 행의 재계산·백필은 하지
   않는다 — 본 SPEC은 이후 평가 실행에만 전진 적용된다(SPEC-AI-071이 세운 무백필 관례 계승).
7. **매매·포트폴리오 로직 변경 금지.** SPEC-AI-043 예측 기록 모드 유지(매수 로직 diff 0).
8. **신규 테이블/마이그레이션/스키마 변경 금지.** 기존 함수의 predicted_set 필터 로직 변경만 한다
   (per-detector 분해 컬럼 추가 등 스키마 확장은 범위 밖).

---

## Success Criteria

- `date(created_at)==T-1` 버킷의 near_limit_up_carry 시그널이 `surge_metadata`(`surge_basis` 멤버십, 플랫
  플래그 OR 폴백) 기반으로 `predicted_set`에서 배제된다(REQ-001/002).
- 배제는 predicted 측 한 곳(`:523-536`)에만 적용되고 `actual_set` 및 표준 버킷팅 규칙/계산식은 불변
  (REQ-003). 정제된 predicted_set이 그대로 흘러 TP/FP/precision/recall/coverage가 표준 지평만 반영한다.
- **재현 우선**(Rule 4): 2026-07-06/07-07형 시나리오(predicted_set이 near_limit_up_carry 지배)에서
  near_limit_up_carry가 현행 predicted_set/predicted_count에 **포함**됨을 재현하는 실패 테스트가 수정
  **전** 작성·확인되고, 수정 후 **배제**되어 통과한다(REQ-004).
- 기존 `TestEvaluateSurgePredictionsCharacterization` 전량 무회귀. 탐지기 테스트
  (`test_near_limit_up_carry.py`) 무회귀. 신규/변경 로직 커버리지 85%+, `ruff` 무경고, 전체 백엔드
  스위트 회귀 없음(`-n 4` 병렬 포함).
- 탐지기/신호 생성/스케줄/앙상블/매수 로직 diff 0. `actual_set`/`SurgeActualOutcome` diff 0. 신규
  테이블/마이그레이션 없음.

---

## MX Tag 대상 (Run 단계 식별)

- `evaluate_surge_predictions`(`surge_evaluation_service.py:482`) — 18:30 KST 평가 잡 + AI-060/068 확장이
  얽힌 고 fan_in 평가 경계. predicted_set 지평-순수성 계약(near_limit_up_carry 배제 근거)을 `@MX:NOTE`
  (+`@MX:SPEC: SPEC-AI-075`)로 배제 필터 지점에 기록. 기존 AI-041/068 `@MX` 주석 관례와 정합.
