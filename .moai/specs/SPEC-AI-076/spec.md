---
id: SPEC-AI-076
version: 0.1.0
status: draft
created: 2026-07-09
updated: 2026-07-09
author: MoAI
priority: High
issue_number: 0
---

# SPEC-AI-076: 스캔 유니버스 풀 절단 크라우딩아웃 교정 (Scan-Universe Pool Truncation Starvation Fix)

## HISTORY

- 2026-07-09 (v0.1.0): 최초 작성. 별도 조사(read-only 코드 검증 + 2026-07-08 라이브 DB 실측)로 확정된
  **스캔 유니버스 최종 배분 절단 버그**를 SPEC화.
  - **버그**: `build_scan_universe()`(`surge_detector.py:4113-4314`, SPEC-AI-065 소유)의 최종 병합
    (`:4288-4303`)이 `pool_a + pool_b + pool_c + existing`를 단순 concat한 뒤 `[:max_scan_universe]`(150)로
    슬라이스한다. 우선순위가 엄격한 A>B>C>existing이고 **어떤 풀에도 슬롯 보장(floor)이 없으므로**,
    상위 풀 하나가 150 슬롯을 다 소진하면 하위 풀 후보는 실제 스캔에서 전량 조용히 탈락한다.
  - **정량 근거(라이브, 2026-07-08 15:20 KST 스캔, DB 직접 조회)**: Pool A raw **232**(SPEC-AI-073 DART
    복구로 0→232 급증), Pool B raw 0, Pool C raw **52**, 최종 `scan_universe_size` 150. Pool A(232)만으로
    이미 150 상한을 초과 → 그날 `final_universe`는 사실상 `pool_a_codes[:150]`이고 **Pool C 52건이 100%
    실제 스캔에서 배제**됐다. 한 풀의 일일 공급 급증(Pool A는 당일 공시량에 전적으로 의존, 시스템 통제 밖)이
    나머지 풀을 조용히 0으로 만드는 이전에 알려지지 않은 구조적 버그.
  - **관측 불가능성**: 영속되는 `pool_a/b/c_count`(`SurgeUniversePoolHistory`)는 **절단 전 raw 수**라
    스캔이 100% Pool A였어도 `pool_a=232, pool_c=52`처럼 정상으로 보인다.
  - **선택 접근(불변 슈퍼시드 결정)**: 배분 메커니즘만 슈퍼시드 — 엄격 concat-then-slice를 **풀별 최소
    슬롯 예약(quota) 방식**으로 교체. `max_scan_universe`(150) 상향 없음, `_min_ratio`(2.0) 불변. 상세는
    아래 "불변 슈퍼시드 결정" 절.

---

## 불변 슈퍼시드 결정 (Invariant-Supersession Decision) [HARD]

이전 SPEC들이 이 코드 영역에 남긴 "불변" 주석 2건을 **명시적으로** 다룬다:
- `:4183`(SPEC-AI-074): "`_min_ratio(2.0)·max_scan_universe(150)는 불변`"
- `:4217`(SPEC-AI-067): "`Pool A/B/C 우선순위·max_scan_universe·_min_ratio=2.0은 불변(SPEC-AI-065 소유)`"

**결정: 부분 슈퍼시드(배분 메커니즘만).** 이 불변은 (1)비용 상한(`max_scan_universe=150`)과 (2)슬롯 배분
정책(엄격 A>B>C concat-then-slice)을 한 덩어리로 묶었으나 **둘은 분리 가능**하며 버그는 전적으로 (2)에 있다.

- **보존**: `max_scan_universe`(150) — 그 실제 목적은 **스캔 비용 상한**이다(Pool B 후보마다
  `fetch_stock_price_history_sync(pages=3)` 네트워크 호출 + 스캔 후보마다 탐지기/LLM 예산 소모). 상향하지
  않는다. `_min_ratio`(2.0, SPEC-AI-074 소유)도 불변. 총 유니버스 크기 <= 150 유지 → **스캔 비용 동일**.
- **슈퍼시드**: (2) 엄격 concat-then-slice **배분 메커니즘만** → 풀별 최소 슬롯 예약(quota) + 우선순위
  잔여 채움으로 교체. 이 부분에 한해 SPEC-AI-076이 소유권을 가지며, `:4183`/`:4217` 주석을 "배분
  메커니즘은 이제 quota 기반(SPEC-AI-076 소유), `max_scan_universe`/`_min_ratio`는 여전히 불변"으로 갱신한다.

**지금 슈퍼시드가 정당한 이유(이전 저자들이 갖지 못한 새 사실)**: `:4183`/`:4217` 주석은 **2026-07-01~07-08,
Pool A가 DART 크롤러 장애로 구조적 0이던 기간**(SPEC-AI-073가 07-08 복구)에 작성됐다. Pool A=0이면 A+B+C 합이
150을 넘는 일이 드물어 **절단의 크라우딩아웃 실패 모드가 발현할 수 없었고 검증된 적도 없다** — 불변은 그 결함이
보이지 않는 조건에서 확인됐다. SPEC-AI-073의 DART 복구로 Pool A가 232까지 오르는 것은 이전 저자들이 예상할 수
없던 진짜 새로운 입력 분포다. 따라서 이는 잘 검토된 불변을 가볍게 뒤집는 것이 아니라, **한 번도 그 입력에
대해 검증되지 않은 메커니즘을 교정**하는 것이다.

**기각한 대안**: (a) `max_scan_universe` 상향 — Pool A 공급에 따라 스캔 비용이 무한정 증가하고, 상향해도
비굶주림을 **보장하지 못한다**(Pool A=400이면 상한 300이어도 C 굶주림). (b) 라운드로빈/인터리브 — 잔여 슬롯
배분에서 의도된 A>B>C 우선순위 신호를 완전히 폐기. quota(최소 floor + 우선순위 잔여)는 **비용 상한·우선순위
선호·비굶주림 보장을 모두** 유지하는 하이브리드다.

---

## 선행 SPEC / 관계 (Assumptions & Relationships)

각 항목은 2026-07-08~09 코드 재확인 결과다. 본 SPEC은 **스캔 유니버스 최종 배분만** 바꾸며 탐지기·후보
소싱·신호 발신·임계·매매 로직을 바꾸지 않는다.

- **SPEC-AI-065 (build_scan_universe / Pool 조합 / 상한 상위 SPEC) — 배분 메커니즘 부분 슈퍼시드**: 본
  SPEC이 `:4288-4303` 배분 로직의 소유권을 quota 방식으로 인수한다. Pool A/B/C 정의·`max_scan_universe`
  상한값·"유니버스는 출력(발신)이 아닌 입력(평가대상) 확장"이라는 설계원칙은 계승·보존한다.
- **SPEC-AI-074 (Pool B 후보 소스 stocks 교집합) — 후보 소싱 불변**: Pool B의 ETF·ETN 크라우딩아웃 제거는
  **후보 소스 단계**(`fetch_volume_leaders_sync` + `fetch_tracked_stock_codes`)에서 이미 처리됨. 본 SPEC은
  그 뒤 **최종 배분 단계**의 서로 다른 크라우딩아웃(풀-간 슬롯 굶주림)을 다룬다. `_min_ratio=2.0` 불변.
- **SPEC-AI-073 (DART 복구) — 이 버그를 처음 발현시킨 새 사실**: Pool A가 0→232로 회복되면서 절단 실패
  모드가 최초로 표면화. 본 SPEC은 그 복구가 만든 새 입력 분포에 대한 배분 로직 교정이다.
- **SPEC-AI-068 (SurgeUniverseMember, entry_pool 영속) — 관측성 자산 재사용**: 최종 유니버스 종목코드가
  entry_pool 태그와 함께 이미 영속되므로 **절단 후 풀별 실제 스캔 수는 신규 컬럼 없이 복원 가능**하다
  (`COUNT(entry_pool) GROUP BY entry_pool`). 본 SPEC의 관측성 요구(REQ-005)는 이 자산을 근거로 신규
  마이그레이션을 피한다.
- **SPEC-AI-065 REQ-5 (SurgeUniversePoolHistory raw 카운트) 및 `evaluate_surge_predictions` 소비 —
  raw 의미 보존**: `persist_pool_counts`/`get_pool_counts_for_date`/`evaluate_surge_predictions`
  (`surge_evaluation_service.py:678-728`)가 `pool_a/b/c_count`를 raw 공급 값으로 읽는다. 이 컬럼 의미를
  바꾸면 회귀 → **의미 불변(raw 유지), post-truncation은 별도 신규 dict 키/로그로만 노출**.
- **SPEC-AI-043 (예측 기록 모드) — 매매 무개입**: 실매매 비활성. 매수 로직 diff 0. 자금 리스크 없음.
- **관측 예정 Pool C 판단(2026-07-11~07-14) — 본 SPEC이 그 판단의 전제**: "Pool C가 구조적으로 필요한가"를
  coverage로 판정할 예정인데, Pool C가 실제 스캔에서 100% 절단되면 그 근거 자체가 오염된다(스캔되지 않은 풀의
  가치는 측정 불가). 본 SPEC을 관찰 창 이전에 적용해야 판단이 유효하다. (Pool C 신호 품질 자체는 별개 사안 —
  Exclusions 참조.)

---

## Environment (환경/전제)

- Backend: Python 3.12+, FastAPI, SQLAlchemy 2.0, PostgreSQL 16(프로덕션) / SQLite(테스트). 배포: OCI VM
  베어메탈 + systemd(`newshive`). 운영 모드: **예측 기록 전용(실매매 비활성)** — 자금 리스크 없음.
- 대상 코드: `backend/app/services/surge_detector.py`의 `build_scan_universe()` 최종 배분/병합 지점
  (`:4288-4303`) + 반환 `pool_counts` 구성(`:4282-4286`). 설정 필드는 `app/surge_config/surge_settings.py`
  `SurgeDetectionConfig` + `surge_detection.yaml`.
- 대상 테스트: `backend/tests/test_spec_ai_065.py`(build_scan_universe 배분 정본 테스트) 확장. 회귀 확인:
  `test_spec_ai_074.py`(Pool B 소싱), `test_surge_universe_members.py`, `test_surge_universe_pool_bugfix.py`.
- 데이터/코드 사실(실측 2026-07-08~09):
  - 최종 병합은 `pool_a_codes + pool_b_codes + pool_c_codes + existing` concat 후 `[:max_universe]`
    (`:4289-4303`)이며 풀별 슬롯 보장이 없다.
  - `pool_counts`(`:4282-4286`)는 각 풀 리스트의 **raw pre-truncation 길이**만 담는다.
  - `build_scan_universe` fan_in=3: `surge_detector.py:1933`(gather_surge_candidates, 직후
    `persist_pool_counts`/`persist_universe_members`), `scheduler.py:1226`, `:1243`.
  - `max_scan_universe`(150)와 `_min_ratio`(2.0, Pool B 블록 `:4207` 하드코딩)는 상수. 스캔 비용 상한.
  - `SurgeUniverseMember.entry_pool`(SPEC-AI-068)에 최종 유니버스 풀 태그가 이미 영속됨.
- **신규 테이블/마이그레이션/스키마 변경 없음**(기존 함수의 배분 로직 변경 + 설정 필드 추가만).

---

## Requirements (EARS)

### REQ-AI076-001 (P0, Unwanted Behavior) — 풀 굶주림(starvation) 금지

**IF** `(len(pool_a_codes) + len(pool_b_codes) + len(pool_c_codes) + len(existing))`가 `max_scan_universe`를
초과하여 절단이 발생하면, **THEN the system SHALL NOT** 후보가 있는 어떤 풀(Pool B, Pool C)을 `final_universe`
에서 **0으로 만들어서는 안 된다** — 각 풀 P는 `final_universe`에 최소 `min(R_p, F_p)` 멤버를 보유해야 한다
(R_p = 풀 P의 raw 후보 수, F_p = 설정된 풀 P의 최소 슬롯 floor).

- 구체 보장(테스트 가능): 상위 우선순위 풀 크기와 무관하게, `sum(floors) <= max_scan_universe`인 한 각 풀은
  `min(R_p, F_p)` 슬롯을 확보한다. 예: Pool A raw=232, Pool C raw=52, cap=150, `pool_c_min_slots=30`이면
  `final_universe`의 `entry_pool=="pool_c"` 개수 >= 30 (현행 0에서 교정).
- **[HARD]** 이는 배분 메커니즘 교체다 — 후보 소싱(Pool A/B/C 쿼리)은 건드리지 않는다.

### REQ-AI076-002 (P0, Ubiquitous) — 비용 상한 보존 (슈퍼시드 범위 한정)

The system **SHALL** `max_scan_universe`(150)를 상향하지 않고 `_min_ratio`(2.0)를 변경하지 않으며,
`len(final_universe) <= max_scan_universe`를 항상 유지해야 한다.

- 슈퍼시드는 **배분 메커니즘에 한정**된다(불변 슈퍼시드 결정 절). 총 스캔 비용은 변경 전과 동일하게 상한 이내로
  유지된다.
- **[HARD]** `max_scan_universe`/`_min_ratio` 상수 자체는 이 SPEC이 소유하지 않는다(각각 SPEC-AI-065/074).
  본 SPEC은 그 값을 읽어 배분에만 사용한다.

### REQ-AI076-003 (P0, State-Driven) — 예약 후 잔여는 기존 우선순위로 채움

**WHILE** 풀별 최소 슬롯 예약을 채운 뒤 남은 용량을 배분하는 동안, the system **SHALL** 잔여 슬롯을 기존
우선순위 순서(A > B(잔여) > C(잔여) > existing)로 채우고 중복(dedup, 순서 보존)을 제거해야 한다.

- 배분 알고리즘(권장 구현): (1) `reserved_p = min(len(pool_p), F_p)` for p in {B, C}; (2) 예약 슬롯을 각
  풀 앞쪽에서 확보; (3) `remaining = max_universe - sum(reserved)`; (4) 잔여를 A>B(나머지)>C(나머지)>existing
  순으로 채움; (5) 최종 dedup. Pool A는 우선순위 1이라 별도 floor가 필요 없다(잔여에서 최우선 충당).
- 의도된 A>B>C 우선순위 **선호는 잔여 배분에서 보존**된다(라운드로빈처럼 폐기하지 않음).

### REQ-AI076-004 (P0, Event-Driven) — 절단 압력이 없을 때 레거시 동등성(회귀 가드)

**WHEN** `(pool_a + pool_b + pool_c + existing)`의 총 후보 수가 `max_scan_universe` 이하이면, the system
**SHALL** 모든 후보를 `final_universe`에 포함해야 하고(어떤 풀도 탈락 없음), 결과 종목코드 **집합(set)** 및
`entry_pool_map`은 기존 거동과 동일해야 한다.

- quota 방식은 절단이 없을 때 후보를 하나도 떨어뜨리지 않는다(모두 포함). 순서는 예약분이 앞당겨져 달라질 수
  있으나, 유니버스는 스캔 대상 **집합**이고 `entry_pool_map`은 코드-키 딕셔너리라 순서에 무관하다 —
  다운스트림 의미는 불변.
- **[HARD] 백워드 호환 탈출구**: `pool_b_min_slots == 0` 그리고 `pool_c_min_slots == 0`이면 quota 방식은
  기존 엄격 concat-then-slice와 **정확히 동일한** 결과를 내야 한다(회귀 검증 속성).

### REQ-AI076-005 (P1, Ubiquitous) — 절단 후(post-truncation) 풀별 카운트 관측성

The system **SHALL** 절단 후 `final_universe`에 실제로 살아남은 풀별 종목 수(post-truncation)를 계산하여
로그로 남기고 호출부가 로깅할 수 있도록 노출해야 하며(예: 반환 `pool_counts`에 `pool_a_scanned`/
`pool_b_scanned`/`pool_c_scanned` 신규 키), 기존 `pool_a`/`pool_b`/`pool_c`(raw pre-truncation) 및
`SurgeUniversePoolHistory.pool_a/b/c_count` 컬럼의 의미는 **변경하지 않아야 한다**.

- raw 카운트는 "각 풀이 절단 전 몇 건을 찾았나"라는 정당한 공급 지표이므로 보존한다(다만 코드/모델 주석에서
  pre-truncation 의미를 명확히 한다). `evaluate_surge_predictions`/`get_pool_counts_for_date`가 raw에
  의존하므로 의미 변경은 회귀다.
- **[HARD]** 절단 후 풀별 영속 진단은 이미 `SurgeUniverseMember.entry_pool`(SPEC-AI-068)로 가능하므로
  **신규 DB 컬럼/마이그레이션을 추가하지 않는다**. 본 REQ는 in-memory 계산·반환·로깅에 한정(스키마 0).

### REQ-AI076-006 (P1, Event-Driven) — 재현 우선 characterization + 회귀 보호

**WHEN** 2026-07-08형 시나리오(Pool A raw > `max_scan_universe`, Pool C raw > 0)가 재현되면, the system
**SHALL** 수정 **전**에 "현행 배분에서 Pool C의 `final_universe` 대표 수가 0"임을 포착하는 실패 테스트가
작성·확인되고, 수정 **후** 그 수가 `min(pool_c_raw, pool_c_min_slots)` 이상이 되어 통과해야 한다.

- **[HARD] 재현 우선(CLAUDE.md Rule 4)**: 수정 전 실패 테스트 먼저. 검증은 **관찰 가능한 사실**
  (`final_universe`의 entry_pool별 카운트 / `len(final_universe)` / 로그)로 고정한다.
- 신규 characterization은 `test_spec_ai_065.py`(build_scan_universe 배분 정본)에 추가한다. 기존
  `test_spec_ai_065.py`/`test_spec_ai_074.py`/`test_surge_universe_members.py`/
  `test_surge_universe_pool_bugfix.py` 전량 무회귀.

### REQ-AI076-007 (P1, State-Driven) — floor는 설정 기반 + 안전 검증

**WHILE** 풀별 최소 슬롯을 결정하는 동안, the system **SHALL** floor 값을 설정(`SurgeDetectionConfig`
`pool_b_min_slots`/`pool_c_min_slots`, `surge_detection.yaml`)에서 읽고, `sum(floors) > max_scan_universe`인
경우(오설정) 안전하게 축소(clamp)하고 경고 로그를 남겨야 한다.

- 기본값(Run 단계 튜닝 시작점, 하드 불변 아님): `pool_c_min_slots ≈ 30`(당일 실현급등 후행 풀 — 무거운 DART
  일에 가장 굶주리기 쉬움 → 더 큰 floor), `pool_b_min_slots ≈ 20`(거래량 풀). 최종 값은 Run 단계에서 라이브
  분포로 조정한다.
- floor가 커 Pool A가 과도하게 눌리지 않도록 `sum(floors)`는 `max_scan_universe`에 비해 충분히 작게 유지
  (검증 로직 + 로그). floors=0이면 레거시 거동(REQ-004 탈출구).

---

## Exclusions (What NOT to Build) [HARD]

1. **`max_scan_universe`(150) 상향 금지.** 비용 상한은 보존한다. 총 유니버스 크기 <= 150 유지(REQ-002).
   상한 상수의 소유권은 SPEC-AI-065에 남는다.
2. **`_min_ratio`(2.0) 변경 금지.** Pool B 비율 임계는 SPEC-AI-074 소유, 불변.
3. **신규 DB 테이블/컬럼/마이그레이션 금지.** post-truncation 영속 진단은 `SurgeUniverseMember.entry_pool`
   (SPEC-AI-068)로 이미 가능. `SurgeUniversePoolHistory.pool_a/b/c_count`는 raw 의미 유지(신규 scanned_count
   컬럼 추가는 범위 밖 — 필요 시 별도 후속 SPEC). 071~075가 세운 무마이그레이션 관례 계승.
4. **Pool C 신호 품질(후행성, 근본원인 #2) 미해결.** Pool C가 "당일 이미 급등한 종목" 소스라 신호원으로
   부적절한가는 **별개 사안**이며 2026-07-11~07-14 관찰 후 별도 SPEC로 판단한다. 본 SPEC은 절단/크라우딩아웃
   메커니즘만 다루며 Pool C 신호 품질과 독립이다.
5. **Pool A/B/C 후보 소싱 로직 무변경.** Pool A DART 쿼리, Pool B 거래량+stocks 교집합 필터(=SPEC-AI-074),
   Pool C `SurgeActualOutcome` 쿼리 — 전부 불변. 오직 최종 배분/병합(`:4288-4303`)만 바꾼다.
6. **탐지기/앙상블/신호 발신/임계/가중치 무변경.** 유니버스는 입력(평가대상) 확장이지 출력(발신) 증가가
   아니다(SPEC-AI-065 설계원칙). 발신은 여전히 min_score+적응형 임계+상위 랭킹으로 게이팅된다. 배분 방식
   변경이 발신량을 늘리지 않는다.
7. **매매·포트폴리오 로직 변경 금지.** SPEC-AI-043 예측 기록 모드 유지(매수 로직 diff 0).
8. **과거 데이터 소급 재계산/백필 금지.** 과거 `SurgeUniversePoolHistory`/`SurgeUniverseMember`/
   `surge_prediction_evaluation` 행 재계산·백필 없음. 이후 스캔 실행에만 전진 적용.
9. **평가 함수(`evaluate_surge_predictions`) 및 pool_counts 소비 무변경.** `get_pool_counts_for_date`는
   계속 raw 카운트를 T-1로 조회한다(의미 보존).
10. **`existing_codes` 누락 버그 미수정 [Human 결정, 2026-07-09].** manager-strategy Phase 1 분석 중 발견 —
    `:4278-4293`의 existing 병합 필터가 항상 빈 리스트를 반환해 `existing_codes`가 실제로는 `final_universe`에
    포함된 적이 없다. 본 SPEC의 스캔 범위(A/B/C 배분) 밖의 별개 기존 버그이므로 **현행 동작을 그대로
    보존**하고 AC-076-004를 그에 맞춰 정정했다(existing 제외, A+B+C 합집합만 검증). 이 버그 자체를 고치는
    것은 별도 후속 SPEC 후보다.

---

## Success Criteria

- **비굶주림**: 절단 압력 하(Pool A raw > cap)에서 Pool B/C가 후보를 가지면 각각 `final_universe`에
  `min(R_p, F_p)` 이상 대표된다. 07-08형 replay(A=232, B=0, C=52, cap=150, `pool_c_min_slots=30`)에서
  `entry_pool=="pool_c"` 개수 >= 30(현행 0), `len(final_universe)==150`, `entry_pool=="pool_a"` <= 120
  (REQ-001/003).
- **비용 상한 보존**: `len(final_universe) <= 150` 항상. `max_scan_universe`/`_min_ratio` 상수 값 diff 0
  (REQ-002).
- **레거시 동등성**: 절단 압력이 없을 때 모든 후보 포함, 결과 집합·`entry_pool_map` 기존과 동일. floors=0이면
  레거시 엄격 슬라이스와 정확히 동일(REQ-004).
- **관측성**: post-truncation 풀별 카운트가 계산·로깅되고 반환에 노출됨. `SurgeUniversePoolHistory` raw 컬럼
  의미·`evaluate_surge_predictions` 소비 diff 0(REQ-005).
- **재현 우선**(Rule 4): 07-08형 시나리오에서 "현행 Pool C 대표=0"을 재현하는 실패 테스트가 수정 전 작성·확인,
  수정 후 통과. 기존 065/074/유니버스 테스트 전량 무회귀. 신규/변경 로직 커버리지 85%+, `ruff` 무경고, 전체
  백엔드 스위트 회귀 없음(`-n 4` 병렬 포함)(REQ-006).
- **설정 안전성**: floor는 설정에서 읽히고 `sum(floors) > cap` 시 안전 축소+경고(REQ-007).
- 탐지기/후보 소싱/신호 발신/앙상블/매수 로직 diff 0. 신규 테이블/마이그레이션 없음.

---

## MX Tag 대상 (Run 단계 식별)

- `build_scan_universe`(`surge_detector.py:4113`) — fan_in=3(`:1933`, `scheduler.py:1226`/`:1243`) →
  `@MX:ANCHOR`(invariant contract) 후보. 배분 계약(quota가 엄격 슬라이스를 슈퍼시드; 비용 상한 보존) 명시.
- 최종 배분 지점(`:4288-4303`) — quota 배분 메커니즘 + 비굶주림 보장을 `@MX:NOTE`(+`@MX:SPEC: SPEC-AI-076`)로
  기록.
- 기존 "불변" 주석 갱신: `:4183`(SPEC-AI-074), `:4217`(SPEC-AI-067) — "배분 메커니즘은 이제 quota 기반
  (SPEC-AI-076 소유), `max_scan_universe`/`_min_ratio`는 여전히 불변"으로 정정(기존 065/067/074 주석 관례와
  정합).
