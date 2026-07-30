# SPEC-AI-094 Plan

## A. 구현 전략

본 SPEC은 Tier S로 진행한다. 실제 코드 변경은 `build_scan_universe()` 내부 3~4곳(설정 필드 1개,
병합 필터 1줄, 로그 라인 확장 1곳)이며, 나머지 작업은 테스트와 검증이다.

핵심 판단:

- 이 SPEC의 위험은 코드 복잡도가 아니라 **평가지표 정의의 조용한 이동**에 있다(spec.md §Context).
  따라서 최우선 제약은 "플래그 OFF에서 바이트 동등"이며, 그것을 지키면 나머지 위험은 활성화 시점의
  별도 판단으로 이연된다.
- 근본 원인은 판정 기준의 오류다. 현행 필터는 `c not in entry_pool_map`으로 판정하는데, 바로 위
  루프가 `entry_pool_map`을 오염시킨다. 올바른 판정 기준은 **A/B/C/D 풀 소속 여부**다.
- 신규 DB 컬럼·마이그레이션 없음. SPEC-AI-073이 겪은 프로덕션 전용 마이그레이션 위험(락 데드락,
  `alembic_version` 길이 초과)에 해당하지 않는다.

### A.1 수정 지점 (정확한 위치)

| 위치 | 현행 | 변경 |
|------|------|------|
| `surge_config/surge_settings.py` | — | `scan_universe_include_existing: bool = False` 신규 필드 |
| `surge_detector.py:4832-4840` | existing 전량 `entry_pool_map` 등재 | 등재는 유지, **풀 소속 집합을 별도 변수로 캡처** |
| `surge_detector.py:4907` | `[c for c in existing_codes if c not in entry_pool_map]` (항상 `[]`) | 플래그 조건 + 풀 소속 집합 기준 판정 |
| `surge_detector.py:4934-4948` | 최종 유니버스 로그 | existing 후보 수 / 실제 포함 수 필드 추가 |

판정 기준 교체의 구체 형태(구현 시 확정):

```python
# 풀 소속 코드 집합을 명시적으로 캡처 (existing 등재 루프 이전 시점 기준)
_pool_member_codes = set(pool_a_codes) | set(pool_b_codes) | set(pool_c_codes) | set(pool_d_codes)

# ... (기존 existing 등재 루프는 그대로) ...

_existing_only = [c for c in existing_codes if c not in _pool_member_codes]
_existing_tail = _existing_only if config.scan_universe_include_existing else []
```

`_existing_only`는 플래그와 무관하게 계산되어야 한다 — REQ-AI094-004의 "포함 가능했던 수"가
OFF 상태에서도 로깅되어야 하기 때문이다.

> 순서 안정성 주의: `existing_codes`는 `set[str]`이므로 반복 순서가 비결정적이다. 플래그 ON에서
> `final_universe` 순서를 결정론적으로 만들려면 `sorted(_existing_only)`가 필요하다. 플래그 OFF
> 경로는 빈 리스트라 영향이 없으므로 REQ-AI094-002(바이트 동등)와 충돌하지 않는다.

### A.5 PRESERVE 목록 (수정 금지)

| 대상 | 사유 |
|------|------|
| `surge_detector.py:4838-4840` existing 등재 루프 | `entry_pool_map`의 `"existing"` 태깅은 정상 동작 중 — 태깅 자체는 무수정 |
| `surge_detector.py:4864-4917` quota 배분 + dedup + 절단 | SPEC-AI-076/086 소유. existing에 quota 미부여(D2) |
| `surge_detector.py:4846-4851` `pool_counts` raw 키 | SPEC-AI-065 REQ-5 의미 고정 |
| `surge_detector.py:1937-2036` `gather_surge_candidates` 호출부 | 반환값 소비 로직 무수정 |
| `surge_detector.py:4998` bridge 필터 | SPEC-AI-092 소유. 본 버그와 무관 |
| `surge_evaluation_service.py` 전체 | 지표 산식 무수정 (REQ-AI094-003) |
| `surge_universe_gap_service.py` / `surge_auto_improver.py` / `scheduler.py` | 무수정 |
| `surge_universe_pool_service.py` `persist_universe_members` / `get_universe_members_for_date` | 영속화·조회 로직 무수정 |
| `test_spec_ai_065.py:716` `assert not (final_set & existing_codes)` | REQ-AI094-005 — 플래그 OFF 회귀 가드로 존치 |
| `test_spec_ai_086.py` 골든 유니버스 바이트 고정 테스트 | 플래그 OFF 동등성의 1차 가드 |

## B. 작업 분해

### TASK-001: 설정 필드 추가

- 대상: `backend/app/surge_config/surge_settings.py`
- `scan_universe_include_existing: bool = False` 추가. 기존 명명 관례(`pool_a_rank_by_impact`,
  `universe_gap_measurement_enabled`) 확인 후 최종명 확정(spec.md Open Question 1).
- 필드 주석에 "기본 비활성 — 활성화 시 scannable_recall/coverage 분모가 이동함" 경고를 남긴다.

추적: REQ-AI094-001, REQ-AI094-002 / AC-094-002

### TASK-002: 풀 소속 집합 캡처 + 병합 필터 교정

- 대상: `backend/app/services/surge_detector.py` — `build_scan_universe()`
- A.1의 `_pool_member_codes` / `_existing_only` / `_existing_tail` 도입.
- `:4907`의 마지막 항을 `_existing_tail`로 교체.
- `:4833-4837`의 Exclusion 10 주석을 갱신 — "SPEC-AI-094에서 플래그 뒤로 교정. 플래그 OFF
  경로는 SPEC-AI-076 AC-076-004 계약을 계속 보존한다"는 취지로 다시 쓴다. 주석 삭제 금지.
- `@MX:SPEC` 서브라인에 `SPEC-AI-094 REQ-AI094-001` 추가.

추적: REQ-AI094-001, REQ-AI094-002 / AC-094-001, AC-094-002, AC-094-004

### TASK-003: 로그 라인 확장

- 대상: `backend/app/services/surge_detector.py:4934-4948`
- 기존 `[스캔유니버스] 최종 유니버스: ...` 라인에 `existing_only=%d existing_included=%d` 필드 추가.
- `existing_included`는 `final_universe` 내 `entry_pool_map.get(c) == "existing"` 개수로 산출한다
  (`scanned_tally`가 이미 `"existing"` 키를 집계하므로 재사용 가능).
- 로그 문구는 한국어(`code_comments: ko`), 필드 키는 영문 식별자.

추적: REQ-AI094-004 / AC-094-005

### TASK-004: 테스트 — 플래그 ON 동작

- 대상: `backend/tests/test_spec_ai_065.py` (SPEC-AI-076 섹션 인접) 또는 신규
  `backend/tests/test_spec_ai_094.py` — 구현 시 결정. 신규 파일이 기존 테스트 오염 위험이 낮다.
- 케이스 3종:
  1. 절단 압력 없음 + 플래그 ON → existing 5개 전부 포함, `len == 35` (AC-094-001)
  2. 절단 압력 있음(A=232/B=0/C=52/cap=150) + 플래그 ON → `existing` 태그 0개, `len == 150`,
     Pool C 대표성 유지 (AC-094-004)
  3. 로그 필드 검사 — 플래그 ON/OFF 2 케이스 (AC-094-005)

추적: REQ-AI094-001, REQ-AI094-004 / AC-094-001, AC-094-004, AC-094-005

### TASK-005: 테스트 — 플래그 OFF 무회귀

- 대상: 기존 테스트 무수정 통과 확인 (신규 코드 없음, 실행 + 확인만)
- `test_spec_ai_065.py` — AC-076-004 characterization 포함 전량
- `test_spec_ai_086.py` — 골든 유니버스 바이트 고정
- `test_spec_ai_074.py` / `test_spec_ai_089.py` / `test_spec_ai_092.py` / `test_spec_ai_070.py`
- 어느 하나라도 수정이 필요하면 **그 자체가 REQ-AI094-002 위반 신호**다 — 테스트를 고치지 말고
  구현을 고친다.

추적: REQ-AI094-002, REQ-AI094-003, REQ-AI094-005 / AC-094-002, AC-094-003, AC-094-006

## C. 검증 계획

타겟 테스트:

```powershell
.\backend\.venv\Scripts\python.exe -m pytest .\backend\tests\test_spec_ai_065.py -q
.\backend\.venv\Scripts\python.exe -m pytest .\backend\tests\test_spec_ai_086.py -q
.\backend\.venv\Scripts\python.exe -m pytest .\backend\tests\test_spec_ai_074.py -q
.\backend\.venv\Scripts\python.exe -m pytest .\backend\tests\test_spec_ai_089.py -q
.\backend\.venv\Scripts\python.exe -m pytest .\backend\tests\test_spec_ai_092.py -q
.\backend\.venv\Scripts\python.exe -m pytest .\backend\tests\test_spec_ai_070.py -q
```

전체 회귀:

```powershell
.\backend\.venv\Scripts\python.exe -m pytest .\backend\tests -q -m "not slow"
```

정적 검사:

```powershell
.\backend\.venv\Scripts\ruff.exe check .\backend
.\backend\.venv\Scripts\python.exe -m mypy .\backend\app
```

범위 규율 grep (AC-094-003):

```bash
git diff --name-only | grep -E 'surge_evaluation_service|surge_universe_gap_service|surge_auto_improver|scheduler'
# 기대: 0 매치
```

characterization 존치 grep (AC-094-006):

```bash
grep -c "assert not (final_set & existing_codes)" backend/tests/test_spec_ai_065.py
# 기대: 1 이상
```

> CI 주의: `pytest-xdist -n 4` 환경에서만 재현되는 레이스 사례가 과거에 있었다(2026-07-03).
> 본 SPEC은 모듈 전역 상태를 추가하지 않으므로 해당 위험에 노출되지 않으나, 전체 회귀는
> `-n 4`로도 1회 확인한다.

## D. 배포/롤백

플래그 기본값이 `False`이므로 배포 자체는 **런타임 동작 diff 0**이다. 이것이 D1의 핵심 가치다.

롤백 트리거:

- `test_spec_ai_086.py` 골든 유니버스 테스트가 깨짐 → 즉시 되돌림(REQ-AI094-002 위반)
- 배포 후 `scan_universe_size`가 배포 전후로 변동 → 플래그 OFF인데 동작이 바뀐 것이므로 심각.
  즉시 되돌림
- `[스캔유니버스] 최종 유니버스` 로그가 사라지거나 기존 필드가 유실 → 관측성 회귀

롤백 단위: TASK-002의 `_existing_tail` 사용을 원래 리스트 컴프리헨션으로 되돌리면 완전 복구된다.
설정 필드와 로그 필드는 잔존해도 무해하다.

**활성화는 별도 결정이다.** 본 SPEC의 완료 조건에 플래그 활성화는 포함되지 않는다(spec.md
Open Question 2). 활성화 시에는 다음이 추가로 필요하다.

- `scannable_recall` / `coverage` / `scan_universe_size` 시계열의 단절 지점 기록
- 단절 이후 지표를 이전 구간과 직접 비교하지 않도록 하는 운영 합의

## E. 리스크

- **지표 단절(활성화 시)**: 최대 리스크이나 플래그 기본 비활성으로 이연했다. 활성화 판단 전에
  REQ-AI094-004 로깅으로 영향 규모를 먼저 관측한다.
- **`set` 반복 순서 비결정성**: 플래그 ON에서 `existing_codes`(set) 반복 순서가 실행마다 달라져
  `final_universe` 꼬리 순서가 흔들릴 수 있다. `sorted()` 적용으로 완화하나, 절단 경계에 걸린
  날에는 어떤 existing이 살아남는지가 정렬 기준(종목코드)에 의존한다 — impact 기반이 아니다.
  Pool A의 impact 정렬(SPEC-AI-078)과 달리 existing에는 순위 근거가 없으므로 이는 수용한 한계다.
- **날짜별 비균질 효과**: 절단 압력이 높은 날은 수정 효과가 0, 낮은 날은 큰 효과. quota 미부여
  결정(D2)의 직접적 대가이며, 지표 해석 시 혼란 요인이 된다. §D의 활성화 시 운영 합의 항목에서
  다룬다.
- **주석 갱신 누락**: `:4833-4837`의 "Exclusion 10 보존" 주석을 갱신하지 않으면, 이후 읽는
  사람이 코드와 주석의 불일치를 만나게 된다. TASK-002에 명시적으로 포함했다.
- **테스트 파일 선택**: TASK-004를 `test_spec_ai_065.py`에 추가하면 그 파일이 이미 065/074/076/078/
  086 다중 SPEC을 담고 있어 더 비대해진다. 신규 `test_spec_ai_094.py`가 낫다고 판단하나 구현 시
  최종 결정한다.
