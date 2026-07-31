---
id: SPEC-AI-094
title: "스캔 유니버스 existing_codes 병합 필터 무효화 교정"
version: "0.1.0"
status: completed
created: 2026-07-30
updated: 2026-07-31
author: Nexsol
priority: Medium
phase: "backend surge-detection v0.1.0"
module: "backend/app/services"
lifecycle: spec-anchored
tags: "surge-detection, scan-universe, existing-codes, evaluation-metric, backend"
tier: S
related_specs: [SPEC-AI-065, SPEC-AI-068, SPEC-AI-076, SPEC-AI-086, SPEC-AI-089, SPEC-AI-092]
---

# SPEC-AI-094: 스캔 유니버스 existing_codes 병합 필터 무효화 교정

## HISTORY

- 2026-07-30 v0.1.0 (draft): SPEC-AI-076 Exclusion 10이 명시적으로 후속 SPEC 대상으로 남긴
  `existing_codes` 병합 필터 무효화 버그를 범위로 정의한다. 라이브 코드 검증 결과 이 버그가
  **후보 생성에는 전혀 영향이 없으나**, `scannable_recall` / `coverage` / `surge_type` 라벨의
  분모를 이동시키는 평가지표 영향이 있음을 확인하여 그 사실을 §Context에 기록한다.

## 선행 SPEC

- **SPEC-AI-076**: 본 버그를 최초로 발견하고 **의도적으로 보존**한 SPEC. Exclusion 10
  (`.moai/specs/SPEC-AI-076/spec.md:225-229`, Human 결정 2026-07-09)이 "본 SPEC의 스캔
  범위(A/B/C 배분) 밖의 별개 기존 버그이므로 현행 동작을 그대로 보존하고, **이 버그 자체를
  고치는 것은 별도 후속 SPEC 후보다**"라고 명시했고, AC-076-004를 그 보존 동작에 맞춰 정정했다
  (`acceptance.md:44-54`). 본 SPEC은 그 유보 사항을 이행하는 후속 SPEC이다.
- **SPEC-AI-065**: `build_scan_universe()`와 Pool A/B/C 구조, `max_scan_universe` 상한의 소유 SPEC.
- **SPEC-AI-068**: `SurgeUniverseMember` 영속화와 `scannable_recall` / `coverage` 지표를 도입한 SPEC.
  본 SPEC이 건드리는 `final_universe`가 그 지표의 **분모 원천**이다.
- **SPEC-AI-086**: Pool D 추가 + `pool_*_scanned` 관측 키. 유니버스 구성 로직의 최근 변경 이력.
- **SPEC-AI-089**: `measure_universe_detection_gap()` — `final_universe`의 또 다른 소비자.
- **SPEC-AI-092**: bridge 후보 생성 — `final_universe`의 소비자이나, 본 버그와 **무관함**을 §Context에서 논증한다.

### amendment 여부

본 SPEC은 SPEC-AI-076의 **amendment가 아니다**. SPEC-AI-076의 본문(Exclusion 10, AC-076-004)은
그 시점의 결정 기록으로서 여전히 정확하며 수정 대상이 아니다. `spec-frontmatter-schema.md`의
Status Transition Ownership Matrix상 `completed → in-progress (amendment)` 전이는 "선행 SPEC 자체를
제자리 수정"하는 경우에 해당하므로, 여기서는 `amendment_of:` 없이 `related_specs`로만 참조하는
통상적 신규 SPEC이 맞다.

## Context / Problem

### 버그 — existing 병합 필터가 구조적으로 항상 빈 리스트를 반환한다

`backend/app/services/surge_detector.py:4838-4840` (`build_scan_universe` 내부):

```python
for code in existing_codes:
    if code not in entry_pool_map:
        entry_pool_map[code] = "existing"
```

그리고 69줄 뒤 `:4907` (최종 유니버스 조립):

```python
universe_ordered = (
    reserved_b_list + reserved_c_list + reserved_d_list
    + pool_a_codes + b_remaining + c_remaining + d_remaining
    + [c for c in existing_codes if c not in entry_pool_map]   # ← 항상 []
)
```

위 루프가 `existing_codes`의 **모든** 원소를 `entry_pool_map`에 등록한 뒤이므로, 아래 리스트
컴프리헨션의 `c not in entry_pool_map` 조건은 어떤 원소에 대해서도 참이 될 수 없다. 결과적으로
`universe_ordered`의 마지막 항은 **구조적으로 항상 빈 리스트**다.

귀결: A/B/C/D 어느 풀에도 속하지 않는 종목(이하 **순수 existing**)은 `entry_pool_map`에는
`"existing"`으로 등재되지만 `final_universe`에는 **한 번도 포함된 적이 없다**.

이 사실은 코드 주석(`:4833-4837`)에 이미 기록되어 있으며 SPEC-AI-076이 의도적으로 보존한 것이다.
본 SPEC은 새로운 발견이 아니라 **유보된 결정의 이행**이다.

### `existing_codes`의 실제 의미

`gather_surge_candidates()`의 유일한 호출부(`surge_detector.py:1937`):

```python
existing_codes = set(merged.keys())
```

`merged`는 8개 탐지기 결과를 병합한 딕셔너리다. 즉 `existing_codes`는 **"이번 실행에서 이미 어떤
탐지기가 후보로 잡아낸 종목"**이지, 별도의 영속 추적 목록이 아니다. 이 의미 확정이 이후 영향
분석의 전제다.

### 영향 분석 — 후보 생성에는 영향 없음 (검증됨)

`build_scan_universe()` 반환값 3종의 하류 소비 지점을 전수 확인했다.

| 소비 지점 | 사용하는 반환값 | 본 버그의 영향 |
|-----------|-----------------|----------------|
| `surge_detector.py:1946` entry_pool 태깅 | `_entry_pool_map` | **없음** — 순수 existing도 map에는 `"existing"`으로 등재되어 있어 태깅이 정상 동작 |
| `surge_detector.py:2021` bridge 후보 생성 (SPEC-AI-092) | `_universe_codes` + `_entry_pool_map` | **없음** — 필터가 `code not in merged and entry_pool_map.get(code) in ("pool_a","pool_c")`(`:4998`)인데, 순수 existing은 정의상 `merged` 안에 있고 태그도 `"existing"`이라 **이중으로 배제**됨 |
| `surge_detector.py:1961` `persist_pool_counts` | `len(_universe_codes)` | 있음 — `scan_universe_size` 축소 |
| `surge_detector.py:1978` `persist_universe_members` | `_universe_codes` | 있음 — 유니버스 멤버 누락 |
| `surge_detector.py:1999` `measure_universe_detection_gap` | `_universe_codes` | 있음 — 관측 전용(기본 비활성) |

**결론 1 — 후보/시그널 생성 경로는 완전히 무영향이다.** 순수 existing 종목은 이미 `merged`에
들어 있는 탐지 후보이므로, `final_universe` 포함 여부와 무관하게 후보 자격을 유지한다.
bridge 경로도 `merged` 소속 종목을 원천 배제하므로 영향이 없다.

### 영향 분석 — 그러나 "관측 전용"이라고 말할 수는 없다

`persist_universe_members`가 기록한 멤버는 다음 경로로 **운영 평가지표에 직결**된다.

```
persist_universe_members(_universe_codes, ...)        surge_detector.py:1978
  → SurgeUniverseMember 테이블 (일자당 replace)
  → get_universe_members_for_date(db, prev_business_day)   surge_evaluation_service.py:823
  → universe_set
      ├─ scannable_actual = actual_set & universe_set        (:829)
      ├─ scannable_recall = |scannable_actual ∩ predicted| / |scannable_actual|   (:834)
      ├─ coverage = scannable_actual_count / total_actual_count                    (:838)
      └─ surge_type = "scannable" if code in universe_set else "non_scannable"     (:946)
```

즉 버그를 고치면 `universe_set`이 커지고, 그에 따라 **`scannable_recall` / `coverage` /
`surge_type` 라벨이 모두 이동한다.**

**결론 2 — 이 SPEC은 "무해한 정합성 수정"이 아니라 "지표 분모 이동"이다.** 특히 다음 비대칭에
주의해야 한다.

- 순수 existing = `merged` 후보 전체이며, 그중 상당수는 `min_score_for_signal` 게이트를 통과하지
  못해 `predicted_set`에는 들어가지 않는다.
- 따라서 순수 existing 종목이 실제로 급등하면 `scannable_actual` 분모는 +1 되지만 분자는 +0일 수
  있다 → **`scannable_recall`이 오히려 하락**할 수 있다.
- `coverage`(= scannable_actual / total_actual)는 반대로 상승한다.

두 지표가 반대 방향으로 움직이며, 그 변화는 "탐지 성능 변화"가 아니라 "정의 변경"이다. 현재
프로젝트가 recall 0% 지속 원인을 추적 중인 상황에서, 근거 없는 지표 단절은 진단을 오염시킨다.

### 영향 분석 — 절단(truncation)과의 상호작용

수정 시 순수 existing은 `universe_ordered`의 **맨 뒤**에 붙는다(우선순위 최하, 기존 설계 의도
유지). 이어지는 `final_universe = universe_dedup[:max_universe]`(`:4917`)가 상한 150을 적용한다.

- Pool A/B/C/D만으로 이미 150을 채우는 날 → 순수 existing은 전량 절단 → **동작 변화 없음**
- 유니버스가 150 미만인 날 → 잔여 슬롯만큼 포함 → 지표 이동 발생

즉 수정의 효과는 **날짜마다 다르다.** SPEC-AI-076이 도입한 quota 예약(`pool_b_min_slots` /
`pool_c_min_slots`)은 A/B/C 사이의 배분만 다루므로, existing에 별도 quota를 주지 않는 한 이
비균질성은 그대로 남는다. 본 SPEC은 existing에 quota를 **부여하지 않는다**(§Decisions D2).

### 기존 테스트가 현행 버그 동작을 명시적으로 고정하고 있다

`backend/tests/test_spec_ai_065.py:687-726` (AC-076-004 characterization):

```python
# (existing_codes 미포함은 SPEC-AI-076 스캔 범위 밖의 기존 버그 — 그대로 보존, Exclusion 10)
...
assert not (final_set & existing_codes), (...)
```

이 단언은 **버그 동작 자체를 계약으로 고정**한 것이다. 본 SPEC은 이 단언을 반전시켜야 하므로,
테스트 수정이 스코프에 포함되며 그 사실을 명시적으로 기록한다(무단 테스트 수정 아님).

## Goals

1. `existing_codes` 병합 필터가 실제로 동작하도록 교정한다 — 순수 existing 종목이 유니버스
   잔여 슬롯에 포함될 수 있게 한다.
2. 교정을 **설정 플래그 뒤에 두고 기본값을 비활성**으로 두어, 지표 단절이 사용자 결정 없이
   발생하지 않게 한다.
3. 후보/시그널 생성 경로 diff 0을 보장한다.
4. 지표 이동 폭을 관측 가능하게 로깅한다 — 플래그 활성화 판단의 근거를 만든다.
5. AC-076-004 characterization 테스트의 반전을 명시적·추적 가능하게 수행한다.

## Non-Goals

### Out of Scope — 범위 제한

- **existing 전용 quota(`existing_min_slots`) 도입**: 절단 비균질성을 없애려면 필요하나, 이는
  SPEC-AI-076이 정의한 배분 계약의 확장이며 별도 판단이 필요하다. 후속 SPEC 대상.
- **`scannable_recall` / `coverage` 정의 변경**: 본 SPEC은 분모 **원천**만 다루며 지표 산식은
  건드리지 않는다(`surge_evaluation_service.py` 무수정).
- **과거 `SurgeUniverseMember` / `surge_prediction_evaluation` 백필**: 하지 않는다.
  SPEC-AI-071 / SPEC-AI-076 Exclusion 8의 전진 적용 선례를 따른다.
- **`max_scan_universe`(150) 상한 및 quota 배분 로직 변경**: SPEC-AI-065 / SPEC-AI-076 소유.
- **bridge 후보 생성 로직(SPEC-AI-092) 변경**: 본 버그와 무관함이 §Context에서 확인됨.
- **탐지기 로직 · 매매 로직 변경**: 무관.
- **`entry_pool_map` 태깅 의미 변경**: `"existing"` 태그 자체는 이미 정상 동작 중이다.

## Decisions

### D1 — 설정 플래그 뒤에 두고 기본값 비활성 (`scan_universe_include_existing`, 기본 `False`)

수정 자체는 리스트 컴프리헨션 하나를 고치는 일이나, §Context가 보인 대로 그 귀결은 운영
평가지표의 정의 이동이다. 이 프로젝트는 유사 위험을 다룰 때 일관되게 **기본 비활성 플래그 →
관측 → 사용자 판단으로 활성화** 패턴을 사용해 왔다(SPEC-AI-084 / 085 / 086 Pool D /
092 bridge 모두 `enabled=False` 기본값으로 배포).

기각한 대안 — 무조건 수정. 배포 즉시 `scannable_recall` / `coverage` / `surge_type`이 이동하며,
그 이동이 "탐지 성능 변화"로 오독될 위험이 크다. 현재 recall 0% 원인 추적이 진행 중이라 지표
연속성의 가치가 특히 높다.

플래그 OFF 시 현행과 **바이트 동등**이어야 한다 — 이것이 D1의 검증 가능한 계약이다.

### D2 — existing에 quota를 부여하지 않는다 (우선순위 최하 유지)

`existing`은 원래 설계에서 "우선순위 최하"(`:4832` 주석 "기존 탐지기 결과 추가 (우선순위 최하)")
였다. quota를 주면 A/B/C의 슬롯을 빼앗게 되고, 이는 SPEC-AI-076이 해결한 크라우딩아웃 문제를
반대 방향으로 재도입한다. 순수 existing은 **이미 탐지된 후보**이므로 추가 탐지 도달범위를 넓히지
않는다 — 슬롯 경쟁에서 A/B/C보다 우선할 근거가 없다.

대가: 절단 압력이 높은 날은 수정의 효과가 0이 되어 날짜 간 비균질성이 남는다. 이 사실을 §D3의
로깅으로 표면화한다.

### D3 — 지표 이동 폭을 로깅으로 관측한다

플래그 ON/OFF와 무관하게, "포함 가능했던 순수 existing 수"와 "실제로 포함된 수"를 기존
`[스캔유니버스] 최종 유니버스: ...` 로그 라인(`:4934-4948`)에 추가 필드로 기록한다. OFF 상태에서도
이 값이 남으므로, **활성화 전에 영향 규모를 미리 알 수 있다.**

### D4 — AC-076-004 characterization 테스트는 플래그 조건부로 분기한다

기존 단언 `assert not (final_set & existing_codes)`는 **플래그 OFF 조건에서 그대로 유지**한다
(D1의 바이트 동등 계약을 지키는 회귀 가드가 된다). 플래그 ON 동작은 별도 테스트로 추가한다.
기존 단언을 삭제하지 않는다 — SPEC-AI-076의 계약은 OFF 경로에서 계속 유효하다.

## Requirements

### REQ-AI094-001: existing 병합 필터 교정

Where `scan_universe_include_existing`가 활성이면, `build_scan_universe()`는 A/B/C/D 어느 풀에도
속하지 않는 `existing_codes` 원소를 `universe_ordered`의 **최후순위**로 실제 병합해야 한다.

필수 조건:

- 병합 판정은 `entry_pool_map` 등재 여부가 아니라 **A/B/C/D 풀 소속 여부**를 기준으로 한다
  (현행 필터가 무효화된 근본 원인이 판정 기준의 오류이므로).
- 삽입 위치는 `universe_ordered`의 마지막 — 기존 우선순위 순서를 변경해서는 안 된다.
- `max_scan_universe` 상한(`final_universe = universe_dedup[:max_universe]`)은 그대로 적용된다.

### REQ-AI094-002: 플래그 비활성 시 바이트 동등

While `scan_universe_include_existing`가 비활성(기본값)이면, `build_scan_universe()`의 반환값
3종(`final_universe`, `entry_pool_map`, `pool_counts`)은 본 SPEC 적용 이전과 **완전히 동일**해야
한다.

필수 조건:

- `final_universe`의 **순서까지** 동일해야 한다(집합 동등이 아닌 리스트 동등).
- `entry_pool_map`의 `"existing"` 태깅 동작은 플래그와 무관하게 현행 유지된다 — 등재 루프
  (`:4838-4840`)가 본 SPEC에서 무수정이므로 **구조적으로** 보장되며, 별도 골든 테스트로
  직접 검증하지 않는다.
- 검증 방법 범위: AC-094-002가 실제로 커버하는 것은 `final_universe`의 순서
  (`test_golden_order_and_pool_counts_default_config`)와 `pool_counts`(`test_spec_ai_086.py`)
  2종뿐이다. `entry_pool_map` 동등성은 위 구조적 보장(등재 루프 무수정)에 근거하며 별도
  assert로 커버되지 않는다.

### REQ-AI094-003: 후보 생성 경로 무영향

While 본 SPEC이 적용되는 동안(플래그 ON/OFF 무관), 시스템은 `gather_surge_candidates()`가
생성하는 후보 집합과 시그널 집합을 변경해서는 안 된다.

필수 조건:

- `merged` 딕셔너리의 키 집합이 변하지 않는다.
- bridge 후보(`generate_scan_universe_bridge_candidates`) 결과가 변하지 않는다.
- `surge_detector.py:1946`의 entry_pool 태깅 결과가 변하지 않는다.
- `surge_evaluation_service.py` / `surge_universe_gap_service.py` / `surge_auto_improver.py` /
  `scheduler.py`는 무수정이다.

### REQ-AI094-004: 지표 이동 폭 관측

When `build_scan_universe()`가 완료되면, 시스템은 "A/B/C/D 미소속 existing 종목 수"와 "그중
실제로 `final_universe`에 포함된 수"를 기존 최종 유니버스 로그 라인에 기록해야 한다.

필수 조건:

- 플래그 비활성 시에도 "포함 가능했던 수"는 기록된다(활성화 판단 근거 확보).
- 플래그 비활성 시 "실제 포함 수"는 항상 0이다.
- 신규 DB 컬럼·마이그레이션 없음 — 로그 라인 확장에 한정한다.

### REQ-AI094-005: SPEC-AI-076 characterization 계약 보존

While `scan_universe_include_existing`가 비활성이면, `test_spec_ai_065.py`의 AC-076-004
characterization 단언(`assert not (final_set & existing_codes)`)이 무수정으로 통과해야 한다.

필수 조건:

- 기존 단언을 삭제하거나 완화해서는 안 된다 — 플래그 OFF 경로의 회귀 가드로 존치한다.
- 플래그 ON 동작 검증은 신규 테스트 케이스로 추가한다.
- 주석의 "Exclusion 10 / 보존" 문구는 "SPEC-AI-094에서 플래그 뒤로 교정, OFF 경로는 계속 보존"
  취지로 갱신한다.

## Acceptance Criteria (Tier S — 인라인)

> GEARS 정규 문장 형식. **볼드 트리거 + 볼드 shall/shall not 절**로 구성한다.

| AC ID | 대응 REQ | 심각도 |
|-------|----------|--------|
| AC-094-001 | REQ-AI094-001 | Must-Pass |
| AC-094-002 | REQ-AI094-002 | Must-Pass |
| AC-094-003 | REQ-AI094-003 | Must-Pass |
| AC-094-004 | REQ-AI094-001 (절단 상호작용) | Must-Pass |
| AC-094-005 | REQ-AI094-004 | Should-Pass |
| AC-094-006 | REQ-AI094-005 | Must-Pass |

### AC-094-001 — 플래그 활성 시 순수 existing이 유니버스에 포함된다

**When** `scan_universe_include_existing=True`이고 Pool A raw = 10, Pool B raw = 8, Pool C raw = 12,
`existing_codes` = 5개(A/B/C와 전부 서로소), `max_scan_universe=150`이면, the system **shall**
`len(final_universe) == 35`를 만족하고 5개 existing 코드가 전부 `final_universe`에 포함되며 각
코드의 `entry_pool_map` 값이 `"existing"`이어야 한다.

- 검증 방법: pytest — `test_spec_ai_065.py` 기존 fixture 재사용, 플래그만 반전

### AC-094-002 — 플래그 비활성 시 리스트 동등(순서 포함)

**While** `scan_universe_include_existing=False`(기본값)이면, the system **shall** 동일 입력에
대해 본 SPEC 적용 이전과 멤버십과 순서가 모두 동일한 `final_universe` 리스트를 반환해야 한다.

- 검증 방법: pytest — AC-076-004 골든 순서 테스트(`test_golden_order_and_pool_counts_default_config`)
  및 `test_spec_ai_086.py` 골든 유니버스 바이트 고정 테스트 무수정 통과. 이 검증은 리스트 순서까지
  비교하므로, 집합 동등(set equality)만으로는 본 AC 충족으로 판정하지 않는다.

### AC-094-003 — 후보 생성 경로 diff 0

**While** 본 SPEC이 적용된 상태에서(플래그 ON/OFF 무관), the system **shall not** `merged` 키
집합과 bridge 후보 결과를 변경해서는 안 된다.

- 검증 방법: pytest — `test_spec_ai_092.py` / `test_spec_ai_089.py` / `test_spec_ai_070.py` 무수정
  통과, 그리고 다음 grep이 0 매치여야 한다:

```bash
git diff --name-only | grep -E 'surge_evaluation_service|surge_universe_gap_service|surge_auto_improver|scheduler'
```

### AC-094-004 — 절단 압력 하에서 existing은 우선순위 최하로 탈락한다

**When** `scan_universe_include_existing=True`이고 Pool A/B/C만으로 이미 `max_scan_universe`를
채우는 입력(예: A raw = 232, B raw = 0, C raw = 52, cap = 150)이면, the system **shall**
`len(final_universe) == 150`을 유지하고 `entry_pool == "existing"`인 코드 수가 0이어야 한다.
같은 조건에서, the system **shall not** A/B/C의 quota 대표성(SPEC-AI-076 AC-076-001)을 변경한다.

- 검증 방법: pytest — SPEC-AI-076 07-08형 replay fixture에 existing 5개를 추가 주입

### AC-094-005 — 지표 이동 폭이 로깅된다

**When** `build_scan_universe()`가 완료되면, the system **shall** 최종 유니버스 로그 라인에
"A/B/C/D 미소속 existing 수"와 "실제 포함 수"를 기록해야 한다. **While**
`scan_universe_include_existing`가 비활성이면, the system **shall** 그 "실제 포함 수" 값을 항상
`0`으로 기록해야 한다.

- 검증 방법: pytest — `caplog`로 로그 라인 검사(플래그 ON/OFF 2 케이스)

### AC-094-006 — SPEC-AI-076 characterization 단언 존치

**While** 본 SPEC 적용 후에도, the system **shall** `test_spec_ai_065.py`의
`assert not (final_set & existing_codes)` 단언을 플래그 OFF 조건에서 그대로 보유해야 한다.
같은 조건에서, the system **shall not** 이 단언을 삭제하거나 완화한다.

- 검증 방법: grep — 해당 단언 문자열이 테스트 파일에 존재함을 확인

```bash
grep -c "assert not (final_set & existing_codes)" backend/tests/test_spec_ai_065.py
# 기대: 1 이상
```

## Open Questions

정책 판단(플래그 기본 비활성 / existing quota 미부여 / 백필 없음 / characterization 존치)은
§Decisions D1~D4에서 확정했다. 남은 항목은 구현 시 확정할 사항이다.

1. 플래그 이름 — `scan_universe_include_existing`을 제안하나, `surge_settings.py`의 기존 명명
   관례(`pool_d_min_slots`, `universe_gap_measurement_enabled`, `pool_a_rank_by_impact`)와의
   정합성 확인 후 확정한다.
2. 플래그 활성화 시점 — 본 SPEC은 배선까지만 하고 활성화는 하지 않는다. 활성화 판단은
   REQ-AI094-004 로깅으로 며칠간 "포함 가능했던 수"를 관측한 뒤 별도 결정한다. 관측 기간과
   판단 기준은 미정.
3. `scan_universe_size`(=`len(final_universe)`) 변동이 `SurgeUniversePoolHistory`에 기록될 때
   과거 시계열과의 단절을 어떻게 표시할지 — 플래그 활성화 시점에 판단한다. 본 SPEC 범위 밖.
