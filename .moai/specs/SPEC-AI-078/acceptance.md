# Acceptance Criteria: SPEC-AI-078 — Pool A impact_score 우선순위 절단 교정

검증은 모두 **관찰 가능한 사실**(`final_universe` 멤버십, `entry_pool_map`, `pool_counts` 카운트,
정렬 순서, 로그)로 고정한다. 매매/발신 부작용은 검증 대상이 아니다(예측 기록 모드).

---

## AC-078-001 (REQ-006, 재현 우선 — 058730형 고impact 종목 절단 재현/교정) [HARD]

**핵심 재현 시나리오.** 2026-07-08 058730(다스코, impact=20) 사례를 대표한다.

- **Given** Pool A raw 후보가 실질 가용 슬롯을 초과하는 상황(예: `max_scan_universe=10`,
  `pool_b_min_slots=0`, `pool_c_min_slots=0`, Pool A에 12개 종목: 고impact 종목 `HIGH`(impact=20)를
  DB 반환 순서상 **뒤쪽**(11번째)에 배치하고, 앞쪽 10개는 저impact(impact=1~5))
- **When (수정 전 / RED)** 현행 무순위 `build_scan_universe()`를 실행하면
- **Then** `HIGH`가 DB 순서상 뒤쪽이라 절단되어 `"HIGH" not in final_universe` — **실패 테스트가 이
  부재를 포착**한다.
- **When (수정 후 / GREEN)** impact 정렬(`pool_a_rank_by_impact=True`)을 적용해 재실행하면
- **Then** `HIGH`(impact=20)가 저impact 종목보다 우선 정렬되어 `"HIGH" in final_universe`,
  `entry_pool_map["HIGH"] == "pool_a"`, `len(final_universe) == max_scan_universe`(상한 준수).

---

## AC-078-002 (REQ-001/003, impact 내림차순 + 종목별 MAX 대표)

- **Given** Pool A에 종목 X(당일 공시 2건: impact 5, 20 → MAX=20), Y(공시 1건: impact 12),
  Z(공시 1건: impact 3), 실질 슬롯 2개(`max_scan_universe=2`, floors=0)
- **When** impact 정렬 `build_scan_universe()`를 실행하면
- **Then** 잔존은 MAX impact 상위 2종목 = {X(20), Y(12)}. `"Z" not in final_universe`. X는 저impact
  공시(5)가 아닌 **최고 공시(20)**로 대표되어 Y보다 상위 — 종목별 MAX 집계가 올바르게 작동함.

---

## AC-078-003 (REQ-002, NULL impact 후순위 유지 — NULLS FIRST 역효과 방지) [HARD]

- **Given** Pool A에 종목 S(impact=15), 종목 N(공시는 있으나 `impact_score` 미산출 = NULL), 실질
  슬롯 1개(`max_scan_universe=1`, floors=0)
- **When** impact 정렬 `build_scan_universe()`를 실행하면
- **Then** `"S" in final_universe` 이고 `"N" not in final_universe` — NULL 공시가 스코어링 공시보다
  **뒤로** 정렬됨(Postgres 기본 NULLS FIRST 역효과 없음).
- **And** 슬롯이 충분한 경우(`max_scan_universe=2`)엔 `"N" in final_universe`도 성립 — NULL은
  **완전 배제가 아니라 후순위 유지**(REQ-002 두 조건 모두 검증).

---

## AC-078-004 (REQ-005, 백워드 호환 — 토글 비활성 = 레거시 동등) [HARD]

- **Given** 동일한 Pool A 후보 집합과 절단 압력(Pool A raw > 슬롯)
- **When** `pool_a_rank_by_impact=False`(토글 비활성)로 `build_scan_universe()`를 실행하면
- **Then** 결과 `final_universe`(종목코드 순서 포함)와 `entry_pool_map`이 **정렬 도입 이전 레거시
  DB-순서 거동과 정확히 동일**하다(레거시 경로 = 기존 `.distinct()` 쿼리).

---

## AC-078-005 (REQ-005, 무절단 시 결과 집합 동등)

- **Given** 총 후보 수(Pool A+B+C+existing)가 `max_scan_universe` 이하 = 절단 압력 없음
- **When** impact 정렬 활성(`pool_a_rank_by_impact=True`)으로 실행하면
- **Then** 모든 Pool A 후보가 포함되어 `set(final_universe)` 및 `entry_pool_map`이 정렬 미적용 대비
  동일하다(정렬은 순서만 바꾸고 무절단 시 집합 불변). `len(final_universe) == 총 후보 수`.

---

## AC-078-006 (REQ-004, 인접 SPEC 불변식 diff 0) [HARD]

- **Given** 임의의 Pool A/B/C 후보 분포(절단 있음/없음 각각)
- **When** impact 정렬 `build_scan_universe()`를 실행하면
- **Then** 다음이 모두 성립한다:
  - `len(final_universe) <= max_scan_universe`(150) — 상한 준수, `max_scan_universe` 값 diff 0.
  - `pool_counts["pool_a"] == len(pool_a_codes)`(절단 전 raw) — raw 카운트 의미 diff 0.
  - `pool_b_min_slots`/`pool_c_min_slots` 예약 로직 결과(Pool B/C `min(R_p, F_p)` 보장)가 SPEC-AI-076
    거동과 동일 — quota 메커니즘 diff 0.
- **And** `test_spec_ai_076.py`/`test_surge_universe_members.py`/`test_surge_universe_pool_bugfix.py`
  전량 무회귀.

---

## AC-078-007 (REQ-007, 절단 컷오프 관측성 — P2 선택)

- **Given** Pool A 절단이 발생한 스캔(잔존 컷오프 impact가 존재)
- **When** `build_scan_universe()`를 실행하면
- **Then** `[스캔유니버스]` 로그에 잔존 최저 impact(컷오프) 및 탈락 최고 impact가 기록되어, 고impact가
  저impact보다 우선 잔존했음을 로그로 확인 가능하다.
- **And** 절단이 없는 스캔에서는 해당 로깅이 생략된다(무의미). 신규 DB 컬럼/마이그레이션 없음.

---

## Definition of Done

- [ ] AC-078-001~006 전부 통과(001은 RED→GREEN 재현 우선 순서 준수). 007은 P2(선택).
- [ ] Pool A 조회 정렬만 변경 — 후보 소싱/절단 상한/quota/매매/발신 로직 diff 0.
- [ ] `pool_a_rank_by_impact` 설정 필드(기본 True) + `surge_detection.yaml` 키 추가.
- [ ] NULL 정렬 이식성 방식(`is_(None).asc()`) 채택 — SQLite/Postgres 양쪽 결정적.
- [ ] 신규/변경 로직 커버리지 85%+, `ruff` 무경고, `mypy` 통과.
- [ ] 전체 백엔드 스위트 회귀 없음 — 로컬 기본 실행 + `-n 4`(xdist) 병렬 실행 양쪽 확인.
- [ ] `build_scan_universe` @MX:ANCHOR에 Pool A 정렬 계약 반영, Pool A 조회 지점 @MX:NOTE +
      NULLS LAST @MX:REASON 추가.
- [ ] 신규 테이블/마이그레이션 없음. 과거 데이터 백필 없음(전진 적용).
