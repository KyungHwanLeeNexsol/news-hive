# SPEC-AI-075 Implementation Plan

## 설계 근거 (평가 측 단일 지점 정제, 탐지기·발신 로직 무변경)

near_limit_up_carry의 평가 오염은 **한 지점**에서 발생한다: `evaluate_surge_predictions()`의
`predicted_set` 조립(`surge_evaluation_service.py:523-536`). 이 predicted_set이 하위의 TP/FP/FN/
precision/legacy_recall(`:561-574`)과 scannable_recall/coverage(`:581-628`) **전부**로 흘러가므로,
predicted_set 조립 단계에서 near_limit_up_carry를 배제하면 집계 전체가 표준 지평(Pool A/B/C)만 반영하게
된다. 탐지기·신호 생성·스케줄·매매는 손대지 않는다(평가 측 전용).

### [핵심] preday_disclosure "동일 코드 형태 미러링" 지시의 정정

작업 지시는 preday_disclosure 제외를 "동일 코드 형태로" 미러링하라 했으나, 코드 실측(research.md §3)
결과 그 전제는 부정확하다:

- **preday_disclosure**: `signal_type == "preday_disclosure"`(`preday_signal_service.py:30`)라서 `:529`의
  `signal_type=="surge_candidate"` 필터에 애초에 안 걸려 **자동 제외**된다. `:524` 주석은 그 이유를 적은
  설명일 뿐, surge_metadata를 보지 않는다.
- **near_limit_up_carry**: `signal_type == "surge_candidate"`(`surge_detector.py:2763`)를 **공유**하므로
  `:529` 필터를 통과한다 → signal_type로는 제외 불가.

따라서 **근거 범주(지평 불일치)는 재사용하되 코드 형태는 신규**(surge_metadata 내용 필터)로 한다. 이
정정 자체가 본 SPEC 설계의 중심이다.

## 진입점 / 변경 대상 (신규 자산 0)

**변경 대상 파일 (1개):**
- `backend/app/services/surge_evaluation_service.py` — `evaluate_surge_predictions()`의 predicted_set
  조립(`:523-536`)에 near_limit_up_carry 배제 로직 삽입. TP/FP/FN·scannable·pool_counts·upsert 로직은
  불변(정제된 predicted_set이 그대로 흐른다).

**변경 대상 테스트 파일 (1개):**
- `backend/tests/test_surge_evaluation_service.py` — `TestEvaluateSurgePredictionsCharacterization`
  (`:202`)에 재현/회귀 테스트 추가. `_setup()` 헬퍼(`:205`)를 near_limit_up_carry metadata 시그널을
  주입할 수 있도록 최소 확장(또는 전용 헬퍼 추가).

**재사용:** 기존 `_setup` 헬퍼 패턴(FundSignal `surge_metadata='{"surge_basis": [...], ...}'` +
SurgeActualOutcome), 기존 `_get_prev_business_day`, 기존 `[급등평가]`/`logger.info` 관례.

**신규 자산:** 신규 테이블/모델/스케줄러 잡/마이그레이션 **없음**. 신규 파일 없음.

## 배제 필터 구현 방식 (HOW — DB 이식성 고려)

현재 predicted_set 쿼리(`:525-534`)는 `stock_id, stock_code`만 SELECT하고 `surge_metadata`를 읽지 않는다.
내용 필터를 위해 두 가지 경로가 있으며 **경로 A(Python 파싱)를 권장**한다:

- **경로 A (권장) — surge_metadata 함께 조회 후 Python 파싱 배제**: 쿼리에 `FundSignal.surge_metadata`를
  추가 SELECT하고, 행 순회 시 `json.loads(surge_metadata)`로 파싱해 `"near_limit_up_carry" in
  surge_basis`(1차) 또는 `metadata.get("near_limit_up_carry") is True`(OR 폴백)면 predicted_set에서
  제외. **이유**: 테스트=SQLite / 프로덕션=PostgreSQL이므로 DB별 JSON 연산자(`->>`, `json_extract`)에
  의존하면 이식성이 깨진다. 파싱 예외(손상 JSON)는 **fail-safe로 포함**(보수적 — 표준 지평으로 취급)하되
  로깅(REQ-004 관측). near_limit_up_carry metadata는 탐지기가 항상 유효 JSON으로 쓰므로 예외는 드물다.
- **경로 B (비권장) — SQL LIKE 필터**: `surge_metadata NOT LIKE '%near_limit_up_carry%'`. 취약함
  (`surge_basis` 순서/공백/유사 문자열 오탐 위험) + 두 키 동시 처리 애매 → 권장하지 않음.

**설계 원칙(TRUST Readable)**: 배제는 predicted_set 조립부에 **최소 삽입**한다. 별도 클래스/추상화를
만들지 않는다("staff engineer가 왜 그냥 필터 한 줄 안 넣었지?" 회피).

## 마일스톤 (우선순위 기반, 재현 우선)

1. **(ANALYZE)** predicted_set 조립·preday_disclosure 실제 제외 메커니즘·near_limit_up_carry metadata
   형태 확정(research.md 완료).
2. **(재현 우선 · RED)** 수정 **전** 실패 characterization 테스트 작성 후 실패 확인(CLAUDE.md Rule 4):
   - (a) T-1 버킷에 near_limit_up_carry `surge_metadata`(`surge_basis: ["near_limit_up_carry"]` + 플랫
     `near_limit_up_carry: true`)를 가진 `surge_candidate` 시그널 N건 + 표준 지평(theme_cluster 등)
     시그널 M건을 세팅한 픽스처에서, 현행 `predicted_count == N+M`(near_limit_up_carry **포함**)임을
     포착 — 수정 후 기대치(`N`만 = near_limit_up_carry 제외)로 쓰면 현행에서 실패.
   - (b) 07-06/07-07형: predicted_set이 near_limit_up_carry로 **지배**되는(예: 7/7) 시나리오에서 현행
     predicted_count가 그 7건을 모두 계상함을 포착.
3. **(P0, REQ-001/002)** predicted_set 조립에 near_limit_up_carry 배제(경로 A) 구현 — `surge_metadata`
   함께 조회 + Python 파싱 멤버십 배제. 기존 표준 지평 필터(`signal_type`/`surge_metadata IS NOT NULL`/
   `date==T-1`)는 유지.
4. **(P0, REQ-003)** predicted 측에만 적용 확인 — `actual_set`(`:547-559`) 및 TP/FP/FN·scannable·
   coverage 계산식 무변경. 정제된 predicted_set이 그대로 흐름을 확인.
5. **(P0, REQ-004 GREEN)** 재현 테스트 통과(배제 후 predicted_count에서 near_limit_up_carry 제외) +
   기존 `TestEvaluateSurgePredictionsCharacterization` 전량 무회귀 확인.
6. **(P1 관측)** 배제 건수/예시 로깅(`[급등평가]` 관례 정합) — near_limit_up_carry 배제가 0건이면
   불필요한 로그 억제.
7. **(IMPROVE 검증)** 전체 백엔드 스위트 회귀 없음(`-n 4` 포함), 탐지기 테스트 무회귀, `ruff` 무경고.

## 실패/엣지 처리 설계

- **손상 JSON / 파싱 예외**: `json.loads` 실패 시 해당 시그널을 **표준 지평으로 보수적 포함**(fail-safe)하고
  경고 로깅. near_limit_up_carry를 놓쳐 오염이 남을지언정 표준 시그널을 잘못 버리지 않는다.
- **배제 후 predicted_set 0**: 그 날 표준 지평 시그널이 없었다는 정직한 반영 — precision/recall은
  기존 zero-denominator 처리(`:566-573`)가 그대로 0.0 반환. 정상.
- **near_limit_up_carry가 T에 실제 급등**: 그 종목은 `actual_set`에 그대로 남는다(시장 진실). predicted에서만
  빠지므로, 표준 지평이 그 종목을 T용으로 예측하지 않았다는 사실이 정직하게 반영된다(의도된 동작; FN
  방향은 단정하지 않음).
- **플랫 플래그만 있고 surge_basis 누락(또는 그 반대)**: OR 폴백으로 둘 중 하나라도 near_limit_up_carry를
  가리키면 배제(견고성). 실측상 탐지기는 두 키를 모두 쓰나(`:2751-2756`), 향후 변형에도 안전.
- **다른 탐지기 metadata 오탐**: 표준 탐지기 metadata에는 `near_limit_up_carry` 키/surge_basis 멤버가
  없으므로 오탐 위험 없음(테스트로 확인 — theme_cluster 시그널은 배제되지 않아야 함).

## 롤아웃 전략

1. **재현 테스트 선행**(Rule 4) — 수정 전 실패 확인 후 최소 수정.
2. **Deploy Guard 준수** — 15:15~16:10 KST 자동 대기 창(기존 배포 파이프라인 관례).
3. **2026-07-09 이전 적용 권장** — Pool C 판단 지표(coverage) 정화를 위해(spec.md 선행 SPEC 관계).
   배포는 전진 적용만(과거 행 백필 없음, Exclusion 6).
4. **배포 후 관측** — 배포 후 첫 18:30 평가 실행 로그에서 (a) predicted_count가 near_limit_up_carry 제외분만큼
   감소, (b) 배제 건수 로깅, (c) 이후 coverage 추이가 표준 지평만 반영하는지 전진 관찰.

## 리스크

- **near_limit_up_carry의 진짜 성능 미측정** — 본 SPEC은 오염 제거만 하고 T→T 올바른 평가는 유예(Exclusion 1).
  완화: 이는 의도된 범위 한정 — near_limit_up_carry 성능 측정은 별도 SPEC로 명시 유예(실매매 미개입이라
  시급성 낮음).
- **필터 이식성(SQLite vs PostgreSQL)** — DB별 JSON 연산자 의존 시 테스트/프로덕션 불일치. 완화: 경로 A
  (Python 파싱)로 이식성 확보.
- **과설계 위험** — 배제를 위해 함수를 과도 재구조화하면 TRUST Readable 위배. 완화: predicted_set 조립부에
  최소 삽입(필터 한 지점), 신규 추상화 금지.
- **다른 지평 불일치 탐지기 누락** — `insider_purchase_signals` 등이 개념상 유사할 수 있으나 미확정.
  완화: 범위 밖으로 명시(Exclusion 5), 향후 후속 조사 사안으로만 기록.
