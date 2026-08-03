# SPEC-AI-096 Acceptance Criteria

> GEARS 정규 문장 형식. 각 AC는 **볼드 WHEN/WHILE/WHERE 트리거 + 볼드 shall/shall not 절**로
> 구성한다.

## §A. AC 매트릭스 (REQ ↔ AC 매핑)

| AC ID | 대응 REQ | 심각도 |
|-------|----------|--------|
| AC-096-001 | REQ-AI096-002 | Must-Pass |
| AC-096-002 | REQ-AI096-002 | Must-Pass |
| AC-096-003 | REQ-AI096-001 | Must-Pass |
| AC-096-004 | REQ-AI096-001 | Must-Pass |
| AC-096-005 | REQ-AI096-005 | Must-Pass |
| AC-096-006 | REQ-AI096-005 | Must-Pass |
| AC-096-007 | REQ-AI096-005 | Should-Pass |
| AC-096-008 | REQ-AI096-003 | Must-Pass |
| AC-096-009 | REQ-AI096-004 | Must-Pass |
| AC-096-010 | REQ-AI096-006 | Must-Pass |

## §B. 인수 기준 (정규 문장)

### AC-096-001 — `pool_d_count` 신규 컬럼이 마이그레이션으로 존재하고 영속화된다

**When** `persist_pool_counts()`가 `{"pool_a": 3, "pool_b": 2, "pool_c": 1, "pool_d": 4,
"scan_universe_size": 10}`로 호출되면, the system **shall** `SurgeUniversePoolHistory`
행의 `pool_d_count`를 `4`로 저장해야 한다.

- 검증 방법: pytest — fixture DB에 upsert 후 재조회, `pool_d_count == 4` 확인. 신규
  행 직접 INSERT 시 `pool_d_count` 기본값이 `0`임도 함께 확인(SQLite
  `Base.metadata.create_all()` 경로 + `alembic heads`/`alembic history -r 070:071`
  정적 리비전 체인 검증).

### AC-096-002 — `pool_d` 키 누락 시 하위 호환(0으로 처리)

**When** `persist_pool_counts()`가 `pool_d` 키가 없는 기존 형태의 dict
(`{"pool_a": 3, "pool_b": 2, "pool_c": 1, "scan_universe_size": 6}`)로 호출되면, the
system **shall** `pool_d_count`를 `0`으로 저장해야 하며 예외를 발생시켜서는 **shall
not** 안 된다. 같은 방식으로 `get_pool_counts_for_date()`도 `"pool_d"` 키를 포함한
dict를 반환해야 한다.

- 검증 방법: pytest — 기존 SPEC-AI-065 호출부 형태(pool_d 키 없음)로 회귀 테스트 실행,
  예외 없이 통과 및 반환 dict에 `"pool_d": 0` 포함 확인.

### AC-096-003 — `max_scan_universe` 기본값이 250으로 반영된다

**When** `surge_settings.py`의 `SurgeDetectionConfig`를 기본 설정으로 인스턴스화하거나
`surge_detection.yaml`을 로드하면, the system **shall** `max_scan_universe == 250`을
반환해야 한다.

- 검증 방법: pytest — `SurgeDetectionConfig().max_scan_universe == 250` 및 yaml
  파싱 결과 동일 확인.

### AC-096-004 — clamp 로직은 무수정이며 250은 clamp 범위 내에서 그대로 유지된다

**When** `_resolve_scan_universe_cap(config)`가 기본 설정(동적 시간대 상한 미설정)으로
호출되면, the system **shall** `250`을 그대로 반환해야 한다(clamp 최소/최대 미적용,
no-op). **While** `max_scan_universe`가 `[50, 600]` 범위를 벗어나는 별도 설정으로
변경되면, the system **shall** 기존 `_clamp_scan_universe_cap()` 경고 로그 + clamp
동작(SPEC-AI-086)을 그대로 유지해야 한다.

- 검증 방법: pytest — `test_spec_ai_086.py`의 clamp 테스트 케이스 무수정 통과 + 신규
  케이스(입력 250 → 출력 250) 추가.

### AC-096-005 — pool 소속 후보는 사전절단에서 면제된다

**When** `merged`에 60개의 candidate가 있고 그중 40개는 `entry_pool`이
`pool_a`/`pool_b`/`pool_c`/`pool_d` 중 하나이며 20개는 `entry_pool == "existing"`이면,
the system **shall** 사전절단 후 40개 pool 소속 candidate 전원과 20개 existing
candidate 중 사전점수 상위 min(20, 50)개(즉 20개 전부, 50 미만이므로 절단 없음)를
`merged`에 남겨야 한다.

- 검증 방법: pytest — fixture candidate 60개(40 pool 소속 + 20 existing) 주입, 절단
  후 `len(merged) == 60`(면제 대상이 50 미만이라 이 케이스는 절단 자체가 발생하지
  않음 — 아래 AC-096-006이 실제 절단 발생 케이스를 검증).

### AC-096-006 — existing 후보만 실제로 절단된다 (절단 발생 케이스)

**When** `merged`에 40개의 pool 소속 candidate와 80개의 `entry_pool == "existing"`
candidate(합계 120개, `_MAX_PRICE_FETCH_CANDIDATES=50` 초과)가 있으면, the system
**shall** 절단 후 `merged`에 40개 pool 소속 candidate 전원과 existing 후보 중
`_pre_score()` 내림차순 상위 50개만 남겨야 하며(existing 30개는 폐기), 최종
`len(merged) == 90`이어야 한다. 같은 조건에서, the system **shall not** pool 소속
candidate를 사전점수 값과 무관하게 하나라도 폐기해서는 안 된다.

- 검증 방법: pytest — 40개 pool 소속(사전점수 낮게 설정) + 80개 existing(사전점수
  다양하게 설정) fixture 주입, `len(merged) == 90` 및 pool 소속 40개 전원 생존, existing
  상위 50개만 생존(사전점수 기준 정렬 검증) 확인.

### AC-096-007 — pool 소속 후보 과다 시 경고 로그가 남는다

**When** pool 소속 candidate 수가 `200`을 초과하면, the system **shall** HTTP 호출량
급증 경고 로그 1건을 남겨야 한다.

- 검증 방법: pytest — `caplog`로 pool 소속 candidate 201개 fixture 주입 시 경고 로그
  존재 확인.

### AC-096-008 — Pool D 활성화 기준이 코드 변경 없이 canary 값을 받아들인다

**When** `pool_d_min_slots`를 `0`에서 `10`(제안 canary 값)으로만 변경하고 그 외 어떤
코드도 수정하지 않으면, the system **shall** Pool D 소싱 쿼리가 정상 실행되어
`pool_d_codes`가 비어있지 않은 결과를 반환할 수 있는 상태여야 한다(기존
`if config.pool_d_min_slots > 0:` 게이트, 무수정 확인).

- 검증 방법: pytest — `test_spec_ai_086.py`의 기존 Pool D 활성 테스트 케이스를
  `pool_d_min_slots=10`으로 재실행해 무수정 통과 확인(회귀, 코드 diff 0).

### AC-096-009 — bridge 후보 활성화 기준이 코드 변경 없이 canary 값을 받아들이고 기존 attribution을 보존한다

**When** `scan_universe_bridge_candidates_enabled`를 `False`에서 `True`로만 변경하고
그 외 어떤 코드도 수정하지 않으면, the system **shall** `generate_scan_universe_bridge_candidates()`가
정상 실행되어 `active_detectors=["scan_universe_bridge", pool]` 태깅을 유지하는 후보를
반환할 수 있는 상태여야 한다.

- 검증 방법: pytest — `test_spec_ai_092.py`의 기존 bridge 활성 테스트 케이스 무수정
  통과 확인(회귀, 코드 diff 0) + `git diff --name-only` 결과에
  `surge_detector.py`의 `generate_scan_universe_bridge_candidates` 함수 본문 변경이
  없음을 grep으로 확인.

### AC-096-010 — 기본 설정 조합에서 최종 후보 집합 무회귀 (캡 변경 제외)

**While** `pool_d_min_slots=0`이고 `scan_universe_bridge_candidates_enabled=False`인
상태에서 `max_scan_universe`를 `150`으로 고정하면(REQ-AI096-001 적용 이전 기준값),
the system **shall** `gather_surge_candidates()`가 반환하는 `qualified` 최종 후보
집합과 각 후보의 `bypass_composite_score`/`entry_pool` 값이 본 SPEC 적용 이전과
완전히 동일해야 한다.

- 검증 방법: pytest — `test_spec_ai_065.py` + `test_spec_ai_086.py` +
  `test_spec_ai_089.py` + `test_spec_ai_092.py` 전체 무수정 통과(캡 파라미터를 테스트
  fixture에서 150으로 명시 오버라이드) + 전체 회귀 스위트
  `cd backend && uv run pytest tests/ -m "not slow"` 통과.

## §C. 기존 회귀 테스트 전체 통과

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests/ -q -m "not slow"
```
