# SPEC-AI-104 Acceptance Criteria

> GEARS 정규 문장 형식. 각 AC는 **볼드 WHEN/WHILE/WHERE 트리거 + 볼드 shall/shall not 절**로
> 구성한다.

## §A. AC 매트릭스 (REQ ↔ AC 매핑)

| AC ID | 대응 REQ | 심각도 |
|-------|----------|--------|
| AC-104-001 | REQ-AI104-002 | Must-Pass |
| AC-104-002 | REQ-AI104-004 | Must-Pass |
| AC-104-003 | REQ-AI104-005 | Must-Pass |
| AC-104-004 | REQ-AI104-005 | Must-Pass |
| AC-104-005 | REQ-AI104-001, REQ-AI104-006 | Must-Pass |
| AC-104-006 | REQ-AI104-003 | Must-Pass |
| AC-104-007 | REQ-AI104-008 | Must-Pass |
| AC-104-008 | REQ-AI104-007 | Should-Pass |

## §B. 인수 기준 (정규 문장)

### AC-104-001 — `pool_d_min_slots`가 YAML만 canary 값으로 전환되고 Pydantic 기본값은 0으로 유지된다

**When** `surge_settings.py`의 `SurgeDetectionConfig`를 인자 없이 인스턴스화하면, the
system **shall** `pool_d_min_slots == 0`을 반환해야 한다(Pydantic 기본값 무변경,
§Decisions D1). **While** `surge_detection.yaml`이 배포 설정으로 로드되는 동안, the
deployed config **shall** `pool_d_min_slots == 10`을 반환해야 한다.

- 검증 방법: `grep "pool_d_min_slots" backend/app/surge_config/surge_detection.yaml
  backend/app/surge_config/surge_settings.py` — yaml에서 `10`, `surge_settings.py` 기본값
  선언에서 `0` 확인.

### AC-104-002 — `universe_gap_measurement_enabled`가 true로 전환된다

**When** `surge_detection.yaml`이 배포 설정으로 로드되면, the deployed config **shall**
`universe_gap_measurement_enabled == true`를 반환해야 한다.

- 검증 방법: `grep "universe_gap_measurement_enabled" backend/app/surge_config/surge_detection.yaml`

### AC-104-003 — `analyze_pool_precision_by_date()`가 4개 풀 각각의 `{total, surge_count, precision}`을 반환한다

**When** `analyze_pool_precision_by_date(db, trading_date)`가 고정 fixture(known
`SurgeUniverseMember` + `SurgeActualOutcome` 행)로 호출되면, the system **shall**
`pool_a`/`pool_b`/`pool_c`/`pool_d` 4개 키 각각에 대해 `{total: int, surge_count: int,
precision: float | None}` 딕셔너리를 반환해야 하며, 그 값은 수동 산출값과 일치해야 한다.

- 검증 방법: 단위 테스트 — 고정 fixture(known `SurgeUniverseMember` + `SurgeActualOutcome`
  행)에 대해 계산값이 수동 산출값과 일치하는지 검증.

### AC-104-004 — 특정 거래일 특정 풀의 `total==0`이면 `precision`이 `None`이다 (division-by-zero guard)

**When** 특정 거래일 특정 풀에 소속된 `SurgeUniverseMember` 행이 0건이면, the system
**shall** 해당 풀의 `precision`을 `None`으로 반환해야 한다. **While** 이 조건이 성립하는
동안, the system **shall not** 0으로 나누기 예외를 발생시켜서는 안 된다.

- 검증 방법: 단위 테스트 — 빈 풀 fixture 주입, 예외 없이 `precision is None` 확인.

### AC-104-005 — 리포트 거래일별 표에 `pool_d` 열이 존재하고 "표본 합산" 섹션과 합계가 일치한다

**When** `scripts/measure_universe_detection_gap_report.py`가 실행되어 마크다운 리포트를
생성하면, the report script **shall** 거래일별 표에 `pool_d` 열을 표시해야 하며, 그 열의
합계는 "표본 합산" 섹션의 `pool_d` 값과 일치해야 한다.

- 검증 방법: `scripts/measure_universe_detection_gap_report.py` 실행 후 생성된 마크다운을
  파싱해 `pool_d` 열 존재 + 합계 일치를 검증(테스트).

### AC-104-006 — Pool D 코드가 `_assemble_scan_universe()`를 거쳐도 1차 탐지 후보(`merged`)에 유입되지 않는다

**When** `pool_d_min_slots=10`인 상태로 `_assemble_scan_universe()`가 `pool_d_codes`를
조립하면, the system **shall not** 그 결과를 8개 1차 탐지기의 후보 딕셔너리 `merged`에
유입시켜서는 안 되며, 동일 `merged` 입력에 대해 canary 전환 전(`pool_d_min_slots=0`)과
전환 후의 `merged` 키 집합은 바이트 동등해야 한다.

- 검증 방법: 단위 테스트 — `pool_d_min_slots=10`으로 `_assemble_scan_universe()`를 직접
  호출해 `_universe_codes`/`entry_pool_map`에는 pool_d 코드가 반영되지만, 별도로 준비한
  `merged` 픽스처 딕셔너리는 호출 전후 키 집합이 변경되지 않음을 확인.

### AC-104-007 — 기존 회귀 테스트 스위트(5개 파일)가 canary 전환 후에도 전량 통과한다

**While** 본 SPEC의 canary 전환(REQ-AI104-002/004)이 적용되는 동안, the system **shall**
8개 탐지기 스코어링·앙상블 가중치·quota 배분·bridge·existing 병합 필터 관련 기존 테스트
스위트(`test_spec_ai_086.py`/`089`/`094`/`096`/`102`) 5개 파일 전량을 통과시켜야 한다.

- 검증 방법: `uv run pytest tests/test_spec_ai_086.py tests/test_spec_ai_089.py
  tests/test_spec_ai_094.py tests/test_spec_ai_096.py tests/test_spec_ai_102.py -q`

### AC-104-008 — plan.md §C 활성화 게이트 절차가 문서화되고 CHANGELOG.md에 canary 경고가 기록된다

**When** plan-phase 산출물이 완성되면, plan.md's §C section **shall** recall측 +
precision측 복합 게이트 절차(§Decisions D4)를 문서화해야 하며, CHANGELOG.md의
`[Unreleased]` 섹션 **shall** Pool D canary 전환 경고 항목을 포함해야 한다.

- 검증 방법: `grep -A 20 "^## C\. 활성화 게이트 절차" .moai/specs/SPEC-AI-104/plan.md`로
  §C 섹션 헤딩과 recall/precision 키워드 포함 여부를 기계적으로 확인 + `grep "pool_d"
  CHANGELOG.md`로 canary 경고 존재를 확인. 절차 서술의 논리적 완결성(문서화된 절차가
  §Decisions D4 복합 게이트와 실제로 일치하는지)은 육안 리뷰를 보조 수단으로만 사용한다.

## Scenarios (Given-When-Then, 최소 2)

### 시나리오 1 — canary 전환 후 정상 관측일

**Given** `pool_d_min_slots=10`, `universe_gap_measurement_enabled=true`로 배포되었고,
오늘 뉴스에서 `relevance=="direct"`로 매칭된 종목이 3개(`005930`, `000660`, `035420`)
있으며, 그중 `005930`만 오늘 실제로 급등(`SurgeActualOutcome.was_surge=True`)했다.

**When** `analyze_pool_precision_by_date(db, today)`를 호출한다.

**Then** 반환값의 `pool_d`가 `{total: 3, surge_count: 1, precision: 0.333...}`이다.
`merged`(탐지 후보)에는 이 3개 종목 중 다른 채널(예: theme_cluster)로 이미 시그널을 받은
종목만 나타나며, 순수 pool_d 소속이라는 이유만으로 후보에 추가된 종목은 없다(AC-104-006).

### 시나리오 2 — pool_d 소속 종목이 0건인 날 (division-by-zero guard)

**Given** `pool_d_min_slots=10`이지만 오늘 `relevance=="direct"` 뉴스 매칭 종목이 0건이다
(예: 뉴스 크롤러 장애 또는 단순 저활동일).

**When** `analyze_pool_precision_by_date(db, today)`를 호출한다.

**Then** 반환값의 `pool_d`가 `{total: 0, surge_count: 0, precision: None}`이다 — 0으로
나누기 예외가 발생하지 않는다(AC-104-004).

### 시나리오 3 — 리포트 스크립트가 recall측+precision측을 함께 표시

**Given** 최근 5거래일에 걸쳐 `SurgeUniverseMember.entry_pool="pool_d"` 행과
`SurgeActualOutcome` 행이 축적되어 있다.

**When** `uv run python scripts/measure_universe_detection_gap_report.py --days 5`를
실행한다.

**Then** 생성된 마크다운 리포트의 거래일별 표에 `pool_d` 열이 존재하며(AC-104-005), 그
아래 신규 "Pool별 정밀도" 섹션에 pool_d와 pool_a/b/c의 precision 값이 나란히 표시된다.

### 시나리오 4 — canary 전환이 기존 회귀 스위트에 영향을 주지 않음

**Given** SPEC-AI-104 배포 전 `test_spec_ai_096.py`가 전량 통과하고 있었다.

**When** `pool_d_min_slots`를 0에서 10으로 전환한 뒤 동일 테스트 스위트를 재실행한다.

**Then** `test_spec_ai_096.py`를 포함한 5개 기존 회귀 테스트 파일이 전량 통과한다
(AC-104-007) — quota 배분 산술은 `reserved_d = min(len(pool_d_codes), config.pool_d_min_slots)`
이므로 `pool_d_codes`가 실제로 채워지기 시작해도 clamp 로직 자체(SPEC-AI-076/086 소유)는
무변경이며 기존 테스트가 가정한 `pool_d_min_slots=0` 전제와 무관하게 통과해야 한다.

## Edge Cases

- **뉴스 크롤러 장애로 `NewsStockRelation`/`NewsArticle` 조인 대상 자체가 없는 날**: Pool D
  소싱 쿼리(`_source_scan_universe_pools`)가 fail-open으로 해당 풀만 스킵하는 기존 동작
  (SPEC-AI-086 REQ-AI086-005)은 무변경 — `analyze_pool_precision_by_date()`도 동일하게
  `total=0, precision=None`을 반환해야 한다(시나리오 2와 동일 처리).
- **pool_d 예약 슬롯(quota) 초과로 일부 pool_d 후보가 최종 유니버스에서 절단되는 날**:
  `SurgeUniverseMember`에는 최종 절단 후(`reserved_d_list`) 종목만 영속화되므로,
  precision 측정도 절단 이후 집합만 대상으로 한다 — 절단 전 raw pool_d_codes 전체를
  대상으로 하지 않는다(리포트에 이 구분을 명시).
- **`pool_d_min_slots` 오설정(quota 합계가 `max_scan_universe` 초과)**: 기존
  clamp 로직(`_assemble_scan_universe` 비례 축소)이 그대로 적용되며, 본 SPEC은 이
  로직을 변경하지 않는다 — canary 값 10은 `pool_b_min_slots(20)+pool_c_min_slots(30)+10=60`
  으로 `max_scan_universe`(150 또는 SPEC-AI-096 상향 값) 대비 여유가 충분함을 plan.md
  TASK-002에서 확인한다.

## Quality Gate Criteria

- `uv run pytest tests/ --tb=short -q -m "not slow"` 전체 통과(CLAUDE.local.md 검증 명령
  계승).
- `uv run ruff check . && uv run mypy app/` 신규 결함 0건(기존 baseline 결함은 예외).
- 신규 함수 `analyze_pool_precision_by_date()`에 대한 단위 테스트 커버리지 100%(division-by-zero
  guard 포함 모든 분기).
- `git diff --name-only`에 `surge_trading_service.py`, `fetch_current_prices_batch`,
  8개 탐지기 스코어링 함수, `compute_ensemble_score()`가 포함되지 않음.

## Definition of Done

- [ ] AC-104-001 ~ AC-104-008 전량 PASS
- [ ] 4개 시나리오 전량 재현 검증
- [ ] plan.md §C 활성화 게이트 절차 최종본 기록
- [ ] CHANGELOG.md `[Unreleased]`에 canary 전환 경고 항목 추가
- [ ] `git diff --name-only`가 plan.md §A.1 PRESERVE 목록과 배치되지 않음을 리뷰로 확인
