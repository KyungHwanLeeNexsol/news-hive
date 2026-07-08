# SPEC-AI-075 Acceptance Criteria

Given-When-Then 시나리오와 엣지케이스. 모든 기준은 관찰 가능(테스트 출력 / `predicted_set` 멤버십 /
`predicted_count` 값 / 로그 문자열)해야 하며, 탐지기/신호 생성/스케줄/앙상블/매수 로직 및 `actual_set`
diff는 0이어야 한다. 신규 테이블/마이그레이션은 없다.

**재현 우선(CLAUDE.md Rule 4)**: AC-075-001의 재현 테스트는 수정 **전**에 작성되어 실패
(near_limit_up_carry가 현행 predicted_set에 **포함**됨을 "제외됨" 기대치로 포착)함을 확인한 뒤, 수정 후
통과해야 한다.

---

## AC-075-001 (REQ-001/002/004) — near_limit_up_carry 오염 재현 → 수정 후 predicted_set에서 배제

**Given** trading_date=T, T-1 버킷에 다음 `surge_candidate` 시그널들이 세팅된 상태(`_setup` 헬퍼 확장,
`created_at=T-1`):
- near_limit_up_carry 시그널 N건 — `surge_metadata={"surge_basis": ["near_limit_up_carry"],
  "near_limit_up_carry": true, "yesterday_change_pct": 22.0, "surge_probability_score": 0.36}`
- 표준 지평 시그널 M건 — `surge_metadata={"surge_basis": ["theme_cluster"], "theme_cluster_score": 0.8}`

**When** `evaluate_surge_predictions(db, T)`가 실행되면

**Then**:
- (수정 전, 재현) 현행 코드에서는 `predicted_count == N + M`(near_limit_up_carry **포함**) — near_limit_up_carry를
  제외한 기대치(`== M`)로 단언한 이 테스트가 **수정 전 실패**함을 확인한다.
- (수정 후) near_limit_up_carry N건이 `predicted_set`에서 **배제**되어 `predicted_count == M`이 된다.
- 표준 지평(theme_cluster) 시그널 M건은 **그대로 포함**된다(오탐 배제 없음).

---

## AC-075-002 (REQ-002) — 식별은 `surge_metadata` 권위 필드(`surge_basis`) 기준

**Given** `signal_type=="surge_candidate"`를 공유하되 `surge_metadata`가 서로 다른 시그널들이 섞인 상태
(near_limit_up_carry / theme_cluster / volume_news_combo 등)

**When** predicted_set 조립이 실행되면

**Then**:
- 배제 판정은 `surge_metadata`의 **`surge_basis` 리스트 멤버십**(`"near_limit_up_carry" in surge_basis`)으로
  이뤄진다 — `signal_type`으로 식별하지 않는다(전부 "surge_candidate"라 식별 불가).
- 플랫 `near_limit_up_carry: true` 키만 있고 `surge_basis`가 없는(또는 그 반대) 변형 시그널도 OR 폴백으로
  배제된다(견고성).
- 두 키 중 어느 것도 near_limit_up_carry를 가리키지 않는 표준 탐지기 시그널은 배제되지 않는다(오탐 0).

---

## AC-075-003 (REQ-003) — 배제는 predicted 측에만, actual/표준 규칙 불변

**Given** near_limit_up_carry 종목 중 일부가 T에 실제 급등(`SurgeActualOutcome.was_surge==True`)한 상태

**When** `evaluate_surge_predictions(db, T)`가 실행되면

**Then**:
- 그 종목은 `actual_set`(시장전체 실제급등)에 **그대로 남는다** — actual 측은 signal_type과 무관한 시장
  진실이므로 정제되지 않는다.
- 배제는 `predicted_set` 한 곳(`:523-536`)에만 적용된다.
- TP/FP/FN/precision/legacy_recall(`:561-574`) 및 scannable_recall/coverage(`:581-628`) **계산식 자체는
  변경되지 않으며**, 정제된 predicted_set이 그대로 흘러 표준 지평만 반영한다.
- `actual_surge_count` diff 0(동일 픽스처에서 수정 전후 actual_set 크기 불변).

---

## AC-075-004 (REQ-004) — 07-06/07-07형 지배 시나리오 재현

**Given** predicted_set이 near_limit_up_carry로 **지배**되는 시나리오(예: T-1 버킷 7건 전부
near_limit_up_carry, 표준 지평 0건 — 2026-07-06형)

**When** `evaluate_surge_predictions(db, T)`가 실행되면

**Then**:
- (수정 전) 현행 predicted_count는 7(전부 계상)이며 TP=0/precision·recall이 잘못된 날 비교로 산출됨을
  재현한다.
- (수정 후) 7건 전부 배제되어 predicted_count=0 → precision/recall이 기존 zero-denominator 처리로 0.0
  반환(그 날 표준 지평 예측이 없었다는 정직한 반영).
- 검증은 predicted_count/predicted_set 멤버십으로 고정하며, FN 방향을 단정하지 않는다(research.md §6).

---

## AC-075-005 (REQ-004) — 기존 평가 테스트 무회귀

**Given** `TestEvaluateSurgePredictionsCharacterization`의 기존 특성화 테스트(표준 지평 predicted_count/
TP/FP/FN/precision/pool_counts/upsert/commit)와 SPEC-AI-068 Scannable Recall/Coverage 테스트

**When** 배제 로직 적용 후 전체 스위트가 실행되면

**Then**:
- 기존 테스트가 **전량 통과**한다(표준 지평 시그널만 쓰는 테스트라 배제 로직의 영향을 받지 않음).
- 탐지기 테스트(`test_near_limit_up_carry.py`)가 전량 통과한다(탐지기 diff 0).

---

## AC-075-006 (P1 관측) — 배제 관측 로깅

**Given** predicted_set 조립이 하나 이상의 near_limit_up_carry 시그널을 배제하는 상태

**When** predicted_set 조립이 실행되면

**Then**:
- 배제된 near_limit_up_carry 시그널 수(및 예시 일부)가 로그로 남는다(`[급등평가]` 로깅 관례 정합).
- 배제가 0건이면 불필요한 로그를 남기지 않는다(노이즈 억제).

---

## 엣지케이스

- **EC-1 배제 후 predicted_set 0**: 그 날 표준 지평 시그널이 전무하면 predicted_count=0으로 진행하고,
  precision/recall은 기존 zero-denominator 경로(`:566-573`)가 0.0 반환(정상, 현행에서도 가능한 상태).
- **EC-2 손상 JSON**: `surge_metadata` `json.loads` 실패 시 해당 시그널을 **표준 지평으로 보수적 포함**
  (fail-safe)하고 경고 로깅 — 표준 시그널을 잘못 버리지 않는다.
- **EC-3 플랫 플래그/surge_basis 편측 존재**: 두 키 중 하나만 near_limit_up_carry를 가리켜도 OR 폴백으로
  배제된다(견고성). 실측상 탐지기는 두 키를 모두 쓰나(`surge_detector.py:2751-2756`) 향후 변형 대비.
- **EC-4 near_limit_up_carry가 actual_set과 교집합**: T에 실제 급등한 near_limit_up_carry 종목은 actual_set에
  잔류(AC-075-003). predicted에서만 배제.
- **EC-5 preday_disclosure 공존**: preday_disclosure는 여전히 `signal_type` 필터로 자동 제외되며(기존
  동작 불변), near_limit_up_carry 배제 로직과 독립적으로 병존한다.
- **EC-6 병렬 테스트(`-n 4`)**: 신규 평가 테스트가 pytest-xdist 4워커 환경에서 결정적으로 통과한다(공유
  상태 오염 주의 — DB 픽스처 격리 확인).

---

## Definition of Done

- [ ] **재현 우선**: near_limit_up_carry가 현행 predicted_set/predicted_count에 포함되는 상태를 재현하는
      실패 characterization 테스트가 수정 **전** 작성·실패 확인됨(AC-075-001/004, Rule 4).
- [ ] `date(created_at)==T-1` 버킷의 near_limit_up_carry 시그널이 `surge_metadata`(`surge_basis` 멤버십,
      플랫 플래그 OR 폴백)로 `predicted_set`에서 배제됨(AC-075-001/002, REQ-001/002).
- [ ] 식별이 `signal_type`이 아닌 `surge_metadata` 내용으로 이뤄지고, 표준 탐지기 시그널은 오탐 배제되지
      않음(AC-075-002).
- [ ] 배제가 predicted 측 한 곳에만 적용되고 `actual_set`/`actual_surge_count` 및 TP/FP/FN·scannable·
      coverage 계산식은 불변(AC-075-003, REQ-003).
- [ ] 07-06/07-07형 지배 시나리오에서 수정 후 near_limit_up_carry가 predicted_count에서 제외됨
      (AC-075-004, REQ-004).
- [ ] 기존 `TestEvaluateSurgePredictionsCharacterization` + SPEC-AI-068 테스트 + 탐지기 테스트 전량 무회귀
      (AC-075-005).
- [ ] 배제 건수 로깅(AC-075-006, 배제 0건 시 노이즈 억제).
- [ ] 모든 엣지케이스(EC-1~EC-6) 테스트/확인 커버.
- [ ] 테스트 커버리지 85%+, `ruff check` 무경고, 전체 백엔드 스위트 회귀 없음(`-n 4` 병렬 포함).
- [ ] 탐지기/신호 생성/스케줄/앙상블/매수 로직 diff 0. `actual_set`/`SurgeActualOutcome` diff 0. 신규
      테이블/마이그레이션 없음.
- [ ] 과거 `surge_prediction_evaluation` 소급 재계산/백필 없음(Exclusion 6 준수). 전진 적용만.
- [ ] 동일-당일(T→T) 평가 경로 미구현(Exclusion 1 준수).
