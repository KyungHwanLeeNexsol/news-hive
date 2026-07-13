---
id: SPEC-AI-078
version: 1.0.0
status: completed
created: 2026-07-13
updated: 2026-07-13
author: MoAI
priority: High
issue_number: 0
lifecycle_level: 1
---

# SPEC-AI-078: Pool A 공시 후보 impact_score 기반 우선순위 절단 교정 (Impact-Ranked Pool A Truncation Fix)

## HISTORY

- 2026-07-13 (v1.0.0): **완료 + 배포 검증** (commit `1624fa3`). DDD ANALYZE-PRESERVE-IMPROVE로 구현 완료.
  모든 AC 충족. 프로덕션 배포(140.245.76.242) 확인 2026-07-13 01:50 UTC. 상세는 아래 "Implementation
  Notes" 섹션 참조.
- 2026-07-13 (v0.1.0): 최초 작성. 별도 심층 조사(SSH 프로덕션 DB 직접 조회 + read-only 코드 대조,
  `research.md`)로 확정된 **Pool A 무순위(unranked) 절단 버그**를 SPEC화.
  - **버그**: `build_scan_universe()`(`surge_detector.py:4188-4455`)의 Pool A 조회 쿼리
    (`:4230-4238`)에 `ORDER BY`가 없어 `pool_a_codes`가 DB 반환 순서(사실상 공시 접수 순서)
    그대로 사용된다. Pool A raw 후보가 `max_scan_universe`(150)에서 SPEC-AI-076 Pool B/C
    예약분을 뺀 실질 슬롯(~100~130)을 초과하는 날, 최종 병합의 단순 리스트 슬라이스
    (`:4427` `universe_dedup[:max_universe]`)로 **`impact_score`(신호 품질)와 무관하게** 절단될
    공시가 결정된다 — 즉 "무엇이 스캔되는가"가 사실상 임의적이다.
  - **정량 근거(라이브, 2026-07-08 15:20 KST 스캔, DB 직접 조회)**: Pool A raw **232건**, 그중
    `impact_score >= 20`(baseline 스냅샷 문턱)만 **155건**으로 이미 실질 슬롯 초과. 그날 미탐지(FN)
    표본 5종목 중 4종목(058730/263800/189330/214330)이 스캔 유니버스 자체에 부재.
  - **결정적 반례 058730(다스코)**: 07-08 당일 `report_type="주요사항보고"`,
    `report_name="단일판매ㆍ공급계약체결"`, `impact_score=20`(baseline 문턱 정확히 통과)으로
    **정상 스코어링까지 됐음에도** 무순위 절단으로 최종 유니버스에서 잘림 — 실제 상한가를 유발한
    계약 공시가 신호 품질과 무관하게 탈락한 사례. 정렬 없는 절단이 원인임을 직접 증명한다.
  - **선택 접근**: Pool A 후보 리스트 생성 시점에 `Disclosure.impact_score` 내림차순(NULLS LAST
    동급) 정렬을 도입 → 절단이 불가피할 때 **고impact 공시가 우선 잔존**. `max_scan_universe`
    상한값·SPEC-AI-076 quota 메커니즘·`pool_a` raw 카운트 의미는 **전부 불변**(아래 소유권 경계).

---

## 선행 SPEC / 소유권 경계 (Assumptions & Ownership Boundaries) [HARD]

본 SPEC은 **Pool A 후보 리스트의 정렬(intra-pool ordering)만** 바꾼다. 아래 인접 SPEC들의 소유
불변식은 읽어 사용만 하며 **변경하지 않는다**. (2026-07-13 코드 재확인 결과)

- **SPEC-AI-065 (build_scan_universe / Pool 조합 / 상한 상위 SPEC) — 상한값 불변**: `max_scan_universe`
  (150, `surge_settings.py:488`)의 소유권은 SPEC-AI-065에 남는다. 본 SPEC은 상한을 **읽어 절단에만
  사용**하며 상향/하향하지 않는다. Pool A/B/C 정의, "유니버스는 출력(발신)이 아닌 입력(평가대상)
  확장"이라는 설계원칙도 계승·보존한다.
- **SPEC-AI-076 (풀별 최소 슬롯 예약 quota) — quota 메커니즘 불변**: `pool_b_min_slots`(20)/
  `pool_c_min_slots`(30) 예약 로직(`:4387-4427`)과 백워드 호환 계약(`floors==0`이면 레거시
  concat-then-slice와 정확히 동일)은 **그대로 유지**한다. 본 SPEC은 SPEC-AI-076이 고친 **풀-간
  (cross-pool) 굶주림**과 별개인 **Pool A 풀-내부(intra-pool) 무순위 절단**을 다룬다 — SPEC-AI-076이
  다루지 않은 영역. 본 SPEC의 정렬은 예약 로직 **이전**의 `pool_a_codes` 생성 시점에 적용되므로
  quota 배분 구조(reserved_b/c, 잔여 채움)는 변경 불필요(낮은 침습도).
- **SPEC-AI-065 REQ-5 (raw pool_a_count) — raw 의미 불변**: `pool_counts["pool_a"]`(`:4373-4377`)와
  `SurgeUniversePoolHistory.pool_a_count`는 **절단 전 raw 공급 수**다(`evaluate_surge_predictions`/
  `get_pool_counts_for_date`가 이 의미로 소비, MX:REASON `:4371-4372`). 정렬은 리스트 **순서만**
  바꾸고 **길이(카운트)를 바꾸지 않으므로** raw 카운트 의미는 자동 보존된다.
- **SPEC-AI-073 (DART 복구) — 이 버그를 처음 발현시킨 새 사실**: Pool A가 0→232로 회복되며 절단
  압력이 최초 발생. SPEC-AI-076이 풀-간 굶주림을 고쳤으나, Pool A 풀-내부에서 **어떤 공시가**
  잘리는지는 여전히 무순위였다 — 본 SPEC이 그 잔여 결함을 교정한다.
- **SPEC-AI-043 (예측 기록 모드) — 매매 무개입**: 실매매 비활성. 매수 로직 diff 0. 자금 리스크 없음.

---

## Environment (환경/전제)

- Backend: Python 3.12+, FastAPI, SQLAlchemy 2.0, PostgreSQL 16(프로덕션) / SQLite(테스트). 배포:
  OCI VM 베어메탈 + systemd(`newshive`). 운영 모드: **예측 기록 전용(실매매 비활성)** — 자금 리스크 없음.
- 대상 코드: `backend/app/services/surge_detector.py`의 `build_scan_universe()` Pool A 후보 조회 지점
  (`:4229-4245`). 설정 필드는 `app/surge_config/surge_settings.py` `SurgeDetectionConfig` +
  `surge_detection.yaml`.
- 대상 모델: `backend/app/models/disclosure.py` — `impact_score: Mapped[float | None]`
  (`:28`, **nullable**). NULL 정렬 처리 필수(아래 REQ-AI078-002).
- 대상 테스트: `backend/tests/test_spec_ai_065.py`(build_scan_universe 배분 정본) 확장. 회귀 확인:
  `test_spec_ai_076.py`(quota 배분), `test_surge_universe_members.py`,
  `test_surge_universe_pool_bugfix.py`.
- 데이터/코드 사실(실측 2026-07-13):
  - Pool A 쿼리(`:4230-4238`)는 `db.query(Disclosure.stock_code).filter(...).distinct().all()` — **정렬
    없음**. `pool_a_codes`는 DB 반환 순서.
  - 한 종목이 같은 날 **복수 공시**를 낼 수 있으므로 정렬 기준은 종목별 **최고(MAX) impact_score**여야
    한다(단순 DISTINCT+ORDER BY는 Postgres에서 부적합 — 상세는 plan.md).
  - `impact_score`는 `disclosure_impact_scorer.score_disclosure_impact()` 산출, 미스코어링 공시는 NULL.
  - `build_scan_universe` fan_in=3: `surge_detector.py:1933`, `scheduler.py:1226`, `:1243`.
- **신규 테이블/마이그레이션/스키마 변경 없음**(기존 함수의 Pool A 조회 정렬 변경 + 설정 토글 필드
  추가만). 과거 데이터 백필 없음(전진 적용만).

---

## Requirements (EARS)

### REQ-AI078-001 (P0, State-Driven) — Pool A 절단 시 impact_score 우선순위 잔존

**WHILE** Pool A raw 후보 수가 실질 가용 슬롯을 초과하여 최종 유니버스 절단이 발생하는 동안,
the system **SHALL** Pool A 후보를 종목별 `impact_score` 내림차순으로 정렬한 뒤 절단하여, **고impact
공시가 저impact/무impact 공시보다 우선적으로 `final_universe`에 잔존**하도록 해야 한다.

- 구체 보장(테스트 가능): 두 Pool A 후보 X(impact=20), Y(impact=5)가 있고 실질 슬롯이 한 자리만
  남았다면, `final_universe`는 Y가 아니라 X를 포함해야 한다(현행: DB 순서에 따라 임의).
- **[HARD]** 이는 **Pool A 후보 리스트 정렬 변경**이다 — 후보 소싱(어떤 종목이 Pool A인가), 절단 상한값,
  quota 예약 메커니즘은 건드리지 않는다.

### REQ-AI078-002 (P0, Unwanted Behavior) — 미스코어링(NULL) 공시 처리

**IF** Pool A 후보에 `impact_score`가 아직 산출되지 않은(NULL) 공시가 포함되면, **THEN the system
SHALL NOT** NULL 공시를 스코어링된 공시보다 상위에 정렬해서도, `final_universe`에서 완전히 배제해서도
안 된다 — NULL 공시는 **모든 스코어링 공시보다 낮은 우선순위(NULLS LAST 동급)**로 뒤에 배치하되
후보로는 유지해야 한다.

- **[HARD] 근거**: `Disclosure.impact_score`는 nullable(`disclosure.py:28`)이며, PostgreSQL의
  `ORDER BY <col> DESC`는 기본적으로 `NULLS FIRST`다. 이를 방치하면 스코어링 안 된 공시가 오히려
  최우선 잔존하는 **역효과**가 발생한다. `NULLS LAST` 명시(또는 NULL-우선 판별 정렬키)로 방지한다.
- 스케줄러 타이밍상 유니버스 빌드 시점엔 그날 공시 대부분이 이미 스코어링돼 있으나(research.md 제약 #1,
  저위험 확인), 같은 스캔 사이클 내 방금 수집된 공시의 NULL 가능성은 완전히 배제되지 않으므로 본 REQ가
  안전망이다.

### REQ-AI078-003 (P0, Ubiquitous) — 종목별 최고 impact 기준 정렬

The system **SHALL** 같은 날 복수 공시를 낸 종목을 그 종목의 **최고(MAX) `impact_score`** 기준으로
정렬해야 한다(한 종목은 자신의 최상위 공시로 대표된다).

- **[HARD] 근거**: Pool A는 종목코드 단위(`.distinct()`)이나 한 종목이 하루에 여러 공시를 낼 수 있다.
  종목을 그 최상위 공시로 대표하지 않으면 고impact 공시를 가진 종목이 같은 종목의 저impact 공시 순서에
  밀려 오정렬될 수 있다. 종목별 `MAX(impact_score)` 집계로 대표값을 정한다.

### REQ-AI078-004 (P0, Unwanted Behavior) — 인접 SPEC 불변식 무변경 (소유권 경계)

The system **SHALL NOT** 다음을 변경해서는 안 된다:
1. `max_scan_universe`(150) 값 — SPEC-AI-065 소유, 읽어 사용만.
2. SPEC-AI-076 quota/예약 메커니즘(`pool_b_min_slots`/`pool_c_min_slots` 및 예약→잔여 배분 구조).
3. `pool_counts["pool_a"]` 및 `SurgeUniversePoolHistory.pool_a_count`의 **raw pre-truncation 의미**
   (SPEC-AI-065 REQ-5, `evaluate_surge_predictions` 소비 계약).

- **[HARD]** 정렬은 `pool_a_codes` 리스트의 **순서만** 바꾸고 길이·구성원 집합(절단 전)·quota 로직·
  카운트 의미에 영향을 주지 않는다. 세 불변식의 diff는 0이어야 한다.

### REQ-AI078-005 (P0, Event-Driven) — 백워드 호환 (토글 + 무절단 동등성)

**WHEN** (a) impact 정렬 기능이 설정 토글로 비활성화되거나, 또는 (b) 총 후보 수가
`max_scan_universe` 이하여서 절단 압력이 없으면, the system **SHALL** 레거시 거동을 보존해야 한다 —
결과 종목코드 **집합(set)** 및 `entry_pool_map`이 변경 전과 동일해야 한다.

- **[HARD] 백워드 호환 탈출구(SPEC-AI-076 패턴 계승)**: 정렬 활성 여부를 제어하는 설정 필드
  (예: `pool_a_rank_by_impact`)를 두고, 비활성 시 기존 DB-순서 거동과 **정확히 동일**한 결과를 낸다.
- 절단 압력이 없을 때는 모든 Pool A 후보가 포함되므로 정렬은 최종 **집합**에 영향을 주지 않는다
  (유니버스는 스캔 대상 집합, `entry_pool_map`은 코드-키 딕셔너리라 순서 무관). 절단이 **있을 때만**
  집합이 의도적으로 달라진다(그것이 이 SPEC의 교정 목표).

### REQ-AI078-006 (P1, Event-Driven) — 재현 우선 characterization + 회귀 보호

**WHEN** 2026-07-08형 시나리오(Pool A raw > 실질 슬롯 + 고impact 공시가 저impact/무순위 공시들 뒤에
위치)가 재현되면, the system **SHALL** 수정 **전**에 "현행 무순위 절단에서 고impact 종목(058730형)이
`final_universe`에 부재"임을 포착하는 실패 테스트가 작성·확인되고, 수정 **후** 그 종목이 잔존하여
통과해야 한다.

- **[HARD] 재현 우선(CLAUDE.md Rule 4)**: 수정 전 실패 테스트 먼저. 검증은 **관찰 가능한 사실**
  (`final_universe` 멤버십, entry_pool별 카운트)로 고정한다.
- 신규 characterization은 `test_spec_ai_065.py`(build_scan_universe 정본)에 추가한다. 기존
  `test_spec_ai_065.py`/`test_spec_ai_076.py`/`test_surge_universe_members.py`/
  `test_surge_universe_pool_bugfix.py` 전량 무회귀.

### REQ-AI078-007 (P2, Optional) — 절단 impact 컷오프 관측성

**WHERE** 진단 가시성이 필요한 경우, the system **SHALL** Pool A 절단이 발생한 스캔에서 잔존한 최저
impact 후보의 점수(컷오프 impact) 및 절단으로 탈락한 최고 impact 점수를 로그로 남길 수 있다 — 정렬
교정이 실제로 작동했는지(고impact가 저impact보다 우선 잔존) 운영 로그로 확인 가능하도록.

- **[HARD]** in-memory 계산·로깅에 한정(신규 DB 컬럼/마이그레이션 없음). 절단이 없는 스캔에서는
  로깅 생략 가능(무의미). 관측성 자산은 기존 `[스캔유니버스]` 로그 라인 확장으로 충분.

---

## Exclusions (What NOT to Build) [HARD]

### 인접 SPEC 소유 불변식 (변경 금지)

1. **`max_scan_universe`(150) 상향/하향 금지.** 비용 상한 소유권은 SPEC-AI-065. 읽어 사용만.
2. **SPEC-AI-076 quota 메커니즘 무변경.** `pool_b_min_slots`/`pool_c_min_slots` 예약·잔여 배분 구조,
   `floors==0` 레거시 동등성 계약 모두 그대로 유지. 본 SPEC의 정렬은 예약 로직 **이전**에 적용.
3. **`pool_a` raw 카운트 의미 변경 금지.** `pool_counts["pool_a"]`/`SurgeUniversePoolHistory.pool_a_count`는
   절단 전 raw 공급 수 유지(SPEC-AI-065 REQ-5, MX:REASON `:4371-4372`).
4. **Pool A/B/C 후보 소싱 로직 무변경.** 어떤 종목이 각 풀에 들어가는가(필터 조건)는 불변. Pool A는
   여전히 `rcept_dt == today AND stock_code IS NOT NULL`. 오직 Pool A 리스트의 **정렬**만 바꾼다.
5. **탐지기/앙상블/신호 발신/임계/가중치/매매 로직 무변경.** 유니버스는 입력(평가대상) 확장이지
   출력(발신) 증가가 아니다(SPEC-AI-065 설계원칙). 발신은 여전히 min_score+적응형 임계+상위 랭킹으로
   게이팅. SPEC-AI-043 예측 기록 모드 유지(매수 diff 0).
6. **과거 데이터 소급 재계산/백필 금지.** 이후 스캔 실행에만 전진 적용.

### 이번 세션 동반 발견 — 별도 백로그 (본 SPEC 범위 밖, 후속 SPEC 후보)

research.md와 함께 발견했으나 본 SPEC에 **포함하지 않는** 별개 관심사(스코프 규율 유지):

7. **`OPENAI_API_KEY` 프로덕션 미설정.** 코드가 아닌 시크릿/운영 이슈 — SPEC으로 해결 불가. 별도 운영
   작업으로 분리.
8. **LLM 미스분석 5종목 고정 샘플링 캡.** 미탐지 원인 LLM 분석의 표본 상한 이슈 — 별개 개선 과제.
9. **263800/189330 LLM 미스분석 그라운딩 의심(환각 가능성 미확정).** LLM 미스분석 출력의 데이터
   그라운딩 신뢰성 문제 — 별도 조사 필요, 본 정렬 교정과 무관.

---

## Success Criteria

- **impact 우선 잔존**: 절단 압력 하(Pool A raw > 실질 슬롯)에서 고impact 공시가 저impact/무순위 공시보다
  우선 잔존. 07-08형 replay에서 058730형 고impact 종목(impact=20)이 `final_universe`에 포함(현행 부재)
  (REQ-001).
- **NULL 안전**: 무impact(NULL) 공시가 스코어링 공시 뒤에 배치되고 완전 배제되지 않음. NULLS FIRST
  역효과 없음(REQ-002).
- **종목별 대표**: 복수 공시 종목이 자신의 MAX impact로 대표됨(REQ-003).
- **불변식 보존**: `max_scan_universe`/SPEC-AI-076 quota 로직/`pool_a` raw 카운트 의미 diff 0(REQ-004).
- **백워드 호환**: 토글 비활성 시 레거시 DB-순서와 정확히 동일. 무절단 시 결과 집합·`entry_pool_map`
  기존과 동일(REQ-005).
- **재현 우선**(Rule 4): 07-08형 시나리오에서 "현행 고impact 종목 부재"를 재현하는 실패 테스트가 수정
  전 작성·확인, 수정 후 통과. 기존 065/076/유니버스 테스트 전량 무회귀. 신규/변경 로직 커버리지 85%+,
  `ruff` 무경고, 전체 백엔드 스위트 회귀 없음(`-n 4` 병렬 포함)(REQ-006).
- 탐지기/후보 소싱/신호 발신/앙상블/매수 로직 diff 0. 신규 테이블/마이그레이션 없음.

---

## Implementation Notes (Level 1)

### 실제 구현 요약 (2026-07-13, commit 1624fa3)

#### 핵심 변경사항

**Pool A 조회 정렬 도입** (`backend/app/services/surge_detector.py:4229-4245`)
- 기존 `db.query(Disclosure.stock_code).filter(...).distinct()` → 정렬 없음
- 신규: 종목별 `MAX(impact_score)` 집계 + NULL-안전 내림차순 정렬 추가
- SQLAlchemy 패턴: `order_by(max_impact.is_(None).asc(), max_impact.desc())`
  - NULL 공시를 명시적으로 후순위(NULLS LAST 동급) 처리
  - Postgres/SQLite 양쪽에서 결정적 거동 보장 (이식성 우선)

**설정 토글** (`backend/app/surge_config/surge_settings.py`, `surge_detection.yaml`)
- `pool_a_rank_by_impact: bool = True` 필드 추가 (기본값: True)
- False 시 레거시 DB-순서 경로로 복귀 (백워드 호환, REQ-AI078-005 보증)

**테스트** (`backend/tests/test_spec_ai_065.py`)
- 신규 7개 테스트: `TestImpactRankedPoolATruncation` 클래스
- AC-078-001~006 전부 충족 (재현 우선 RED→GREEN 순서 준수)
- 기존 테스트 전량 무회귀: `test_spec_ai_076.py`, `test_surge_universe_members.py`,
  `test_surge_universe_pool_bugfix.py`
- 백엔드 전체 스위트: **1912 passed, 4 skipped, 3 xpassed, 0 regressions**
- 린트/타입체크: ruff 무경고, mypy 무신규 오류 (35개 baseline 불변)

**배포 상태**
- 프로덕션 배포: 2026-07-13 01:50 UTC (140.245.76.242)
- 배포 확인: git hash 일치, `pool_a_rank_by_impact: true` 적용 확인

#### 편차 및 선택사항

**Plan.md에 없던 추가 구현: stock_code 3차 정렬 키**
- Pool A 정렬: `impact DESC → NULLS LAST → stock_code ASC` (3단계)
- 용도: 동률 impact 종목 간의 순서 안정성 보장 (테스트 정확 순서 검증용)
- 신호 품질상 영향: 0 (동률 종목은 무차별)
- 필요 이유: `TestLegacyEquivalenceWhenFloorsZero` 정확 순서 assertion 유지

**REQ-AI078-007 (P2, 선택) 미구현**
- 절단 impact 컷오프 관측성 로깅
- 상태: **의도적 미구현** (optional, low priority)
- 후속 SPEC 기회에 추가 가능

#### 소유권 경계 무변경 (diff 0 검증)

아래 4개 불변식은 수정 후에도 의도한 대로 유지됨 (코드 재확인):

1. **`max_scan_universe`(150)**: 읽어 사용만, 값 불변 ✓
2. **SPEC-AI-076 quota 메커니즘**: 예약/잔여 배분 구조 무변경 ✓
3. **`pool_a` raw 카운트**: 절단 전 raw 공급 수 의미 불변 ✓
4. **탐지기/발신/매매 로직**: 신호 발신 및 매수 로직 diff 0 ✓

#### 신규 테이블/마이그레이션

- 없음 (설정 필드 추가만)
- 과거 데이터 백필: 없음 (2026-07-13 이후 전진 적용)

---

## MX Tag 대상 (Run 단계 식별)

- `build_scan_universe`(`surge_detector.py:4188`) — fan_in=3(`:1933`, `scheduler.py:1226`/`:1243`) →
  기존 `@MX:ANCHOR`(SPEC-AI-076) 유지·보강. Pool A 정렬 계약(impact DESC NULLS LAST) 명시 추가.
- Pool A 조회 지점(`:4229-4245`) — impact 우선순위 정렬 + NULL 처리를 `@MX:NOTE`
  (+`@MX:SPEC: SPEC-AI-078`)로 기록. NULLS LAST 근거를 `@MX:REASON`으로 명시(Postgres 기본
  NULLS FIRST 역효과 방지).
