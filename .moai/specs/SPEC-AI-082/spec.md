---
id: SPEC-AI-082
version: 1.0.0
status: completed
created: 2026-07-20
created_at: "2026-07-20"
updated: 2026-07-20
author: Nexsol
priority: High
issue_number: null
lifecycle_level: 1
labels: [surge-detection, timeout-guard, ops-reliability, backend]
---

# SPEC-AI-082: 급등 후보 수집 글로벌 타임아웃 오폐기 교정 (Surge-Candidate Gather Timeout — Spurious Empty-Result Discard Fix)

## HISTORY

- 2026-07-20 (v1.0.0): **완료** (commit `b2e6cbc`). DDD ANALYZE-PRESERVE-IMPROVE로 타임아웃 상수
  승격 완료. 신규 테스트 7개 파일 포함 전체 회귀 스위트 통과(2008 passed, 0 failed). 타임아웃 값
  300s→1200s 상향으로 정상 실행(12~15분)이 폐기되던 기존 버그 해결. **편차: [R-3](타임아웃 후
  고아 스레드의 세션 수명 안전성) 남은 미해결 위험으로, 근본 수정은 §8 후속 SPEC 후보(c)로 유예** —
  본 SPEC 범위는 최소 안전 수정(타임아웃 값 교정)에만 한정하되, 이 편차는 동의 문서에 명시적 기록됨.
  신규 파일: `backend/tests/test_surge_ai082_gather_timeout.py`(245L). 영향 파일:
  `backend/app/services/fund_manager.py` 전용. ruff clean.
- 2026-07-20 (v0.1.0): 최초 작성. 2026-07-20 프로덕션(ubuntu@140.245.76.242) SSH 라이브 로그 +
  DB 조회 + 코드 read-only 대조로 이미 근본원인이 확정된 버그를 SPEC화. `_gather_surge_candidates()`
  (`fund_manager.py:1259`)의 글로벌 타임아웃 상수 `_GATHER_TIMEOUT_S = 300`(5분, `:1295`)이,
  같은 파일이 스스로 문서화한 `gather_surge_candidates` 정상 실행 시간 "12~15분"(`:3106`, SPEC-AI-022
  주석) 및 "15분+ 실행 결과"(`:3097`)의 절반에도 못 미쳐, 후보 풀이 큰 날마다 `asyncio.TimeoutError`로
  실제 탐지 작업을 빈 리스트로 조용히 폐기하는 문제. 라이브 증거로 최근 ~11거래일 중 7일(07-09/10/13/
  14/15/16/20)에서 재현 확인. 근본 성능 문제(순차 per-stock HTTP)와 타임아웃 후 고아 스레드의 세션
  수명 위험은 별도 후속 SPEC 후보로 분리하고, 본 SPEC은 **최소 안전 수정(타임아웃 값 교정)**으로 범위를
  좁힌다.

---

## 1. Overview (개요)

### 문제

`_gather_surge_candidates()`(`backend/app/services/fund_manager.py:1259-1319`)는 동기(sync) 탐지
함수 `gather_surge_candidates()`(`surge_detector.py:1829`)를 스레드풀로 분리해 실행하고
`asyncio.wait_for(..., timeout=_GATHER_TIMEOUT_S)`로 감싼다. `gather_surge_candidates`는 후보 종목
**한 종목당 다중 동기 HTTP 호출**(Naver Finance 가격 이력 3페이지 + 실시간가 ≈ 4요청/종목)을 수행하는
순차 루프이므로, 후보 종목 수가 많은 날에는 전체 소요 시간이 수 분을 크게 초과한다.

**모순의 핵심 — 같은 파일 안에 서로 다른 실행 시간 근거가 공존한다:**

| 위치 | 서술 | 함의 |
|------|------|------|
| `fund_manager.py:1293-1295` | "성능 패치: sync HTTP 루프를 스레드로 분리 + **5분 글로벌 타임아웃**" → `_GATHER_TIMEOUT_S = 300` | 정상 상한이 5분이라는 전제 |
| `fund_manager.py:3106` (SPEC-AI-022 주석) | "gather_surge_candidates가 **12~15분** 실행되는 동안 기존 DB 연결이 idle→SSL 끊김" | 정상 실행이 12~15분 |
| `fund_manager.py:3097` (주석) | "surge_candidates 즉시 커밋 — **15분+ 실행** 결과를 즉시 보호" | 정상 실행이 15분 이상일 수 있음 |

즉 코드베이스 자신의 문서가 정상 실행을 **12~15분**으로 명시하는데, 가드는 그 정상 시간의 절반도 안
되는 **5분(300s)**으로 하드코딩되어 있다.

**효과 (오폐기 경로):** 후보 풀이 5분 이상 걸리는 날(라이브 관측상 예외가 아니라 일상적)에는
`asyncio.wait_for`가 `asyncio.TimeoutError`를 던지고, 예외 핸들러(`:1311-1316`)가
`"[급등탐지] gather_surge_candidates 타임아웃 %ds 초과 — 빈 리스트 반환"`을 로깅한 뒤 **빈 리스트
`[]`를 반환**한다. `_gather_surge_candidates()`는 (a) 평일 급등 시그널 전용 생성
경로 `run_surge_signal_generation()`(`:3095`, `_run_surge_signal_generate` 스케줄러 잡, 10:00/15:20 KST)와
(b) `generate_daily_briefing()`의 병렬 gather(`:3220`, `_gather_leading_candidates`/
`_gather_disclosure_candidates`와 나란히)에서 호출된다. `[]`가 반환되면 그날의 급등 후보 탐지 배치는
사실상 통째로 폐기된다 — 후보 0개, 유니버스 멤버 0개, 탐지기 기여도 0개가 저장된다.

**라이브 증거 (2026-07-20, 프로덕션 SSH):**

- 오늘(2026-07-20) 10:00 KST 잡: 01:07:57 UTC 로그에
  `[급등탐지] gather_surge_candidates 타임아웃 300s 초과 — 빈 리스트 반환` →
  `[급등시그널] 15:20 독립 생성 완료: 0개 후보 — 탐지 결과 없음` →
  `[커버리지확장] 테마 전파 시그널 0개 생성`. 직후 및 20분+ 뒤 DB 재조회로
  `surge_universe_members`/`surge_detector_contribution` 당일 0행 확정.
- 빈도 (journalctl 전체 이력, 2026-03월까지 소급): 동일 타임아웃 메시지가
  **2026-07-09/07-10/07-13/07-14/07-15/07-16/07-20** 발생 = 최근 ~11거래일 중 7일. 최초 발생(07-09)이
  SPEC-AI-080/081 "즉시발화" 배포(commit `52258d0`, 2026-07-16)보다 앞서므로 **선재(pre-existing)하고
  독립적인 버그** — SPEC-AI-080/081이 유발한 것이 아니다.

### 목표

`gather_surge_candidates`의 코드베이스-문서화 정상 실행 시간(12~15분)을 **여유롭게 상회**하도록
글로벌 타임아웃 값을 교정하여, 정상 소요 시간 안에 끝나는 실제 탐지 작업이 타임아웃으로 오폐기되지
않게 한다. 동시에 가드 자체는 제거하지 않아(무한 대기 회귀 방지) 병리적으로 오래 걸리는 날의
안전망은 유지한다.

---

## 2. Environment & Assumptions (환경 및 가정)

- Backend: Python 3.13+, FastAPI, SQLAlchemy 2.0, PostgreSQL(프로덕션)/SQLite(테스트).
  개발 방법론: DDD(ANALYZE-PRESERVE-IMPROVE, `.moai/config/sections/quality.yaml`
  `development_mode: ddd`). 검증 명령: `cd backend && uv run pytest tests/ --tb=short -q -m "not slow"`
  (CLAUDE.local.md).

### 코드 검증 완료 (2026-07-20, read-only)

- [E-1] **타임아웃 상수는 함수-로컬 리터럴이다.** `_GATHER_TIMEOUT_S = 300`은
  `_gather_surge_candidates()` 함수 본문 내부(`:1295`)에 리터럴로 선언되어 있으며 모듈 상수도
  설정(config) 필드도 아니다. → 현재 상태로는 테스트에서 monkeypatch/주입이 불가능하다. DDD
  재현-우선(Rule 4) 테스트를 실 HTTP 지연 없이 작성하려면 이 값을 **외부에서 관찰/주입 가능한
  형태(모듈 상수 또는 설정 필드)로 승격**해야 한다(REQ-004, 구체 방식은 plan.md에서 결정).
- [E-2] **폐기 경로 확정.** `asyncio.wait_for(_loop.run_in_executor(None, lambda:
  gather_surge_candidates(...)), timeout=_GATHER_TIMEOUT_S)`(`:1298-1310`) → `except
  asyncio.TimeoutError:`(`:1311`) → 경고 로그(`:1312-1315`) → `return []`(`:1316`). 반환된 `[]`는
  호출자에서 "탐지 결과 없음"으로 처리된다(`run_surge_signal_generation` `:3099-3101`은 `count==0`
  경고 후 `db.commit()`; `generate_daily_briefing` 병렬 gather는 빈 후보로 브리핑 진행).
- [E-3] **고아 스레드 위험(관련 위험, 본 SPEC 미해결).** `run_in_executor(None, ...)`은 기본
  `ThreadPoolExecutor`를 사용한다. `asyncio.wait_for`는 감싼 **future만 취소**하고 스레드풀 워커
  자체는 취소하지 못한다(파이썬 스레드는 강제 취소 불가). 따라서 타임아웃 후에도 `gather_surge_
  candidates`의 순차 HTTP 작업은 백그라운드에서 계속 진행되며, 그 워커는 호출부가 넘겨준 **동일
  `db` 세션**(SQLAlchemy Session, 스레드 안전 아님)을 12~15분 뒤 뒤늦게 건드릴 수 있다. 그 시점엔
  호출부가 이미 빈 결과를 로깅하고 진행(추가 `db.commit()`/신규 세션 오픈/함수 반환)했으므로, 뒤늦은
  쓰기는 유실되거나 stale/닫힌 세션과 경쟁(race)할 수 있다. → 리스크 [R-3], §4 [X-2], §8 후속 후보.
- [E-4] **`gather_surge_candidates`의 성능 특성.** `surge_detector.py:1829`의 동기 함수로, 후보 종목
  루프에서 종목당 다중 동기 HTTP 호출(Naver 가격 이력·실시간가)을 순차 수행한다. 종목당 ≈0.5~1s ×
  후보 200+종목이면 자연히 5분을 초과한다. **이 순차 구조 자체가 근본 성능 원인**이지만, 그 재구조화는
  본 SPEC 범위 밖이다(§4 [X-1], §8 후속 후보 (b)).
- [E-5] **기존 테스트와의 충돌 없음.** `tests/test_surge_ai080_fund_manager.py`는
  `app.services.fund_manager.gather_surge_candidates`를 `return_value=[mock_candidate]`로 즉시 반환
  mock 하여(예: `:181-185`) 타임아웃 분기(`:1311`)에 절대 도달하지 않는다 → 타임아웃 값을 어떻게
  바꾸어도 이 파일의 기존 케이스는 그대로 통과한다. 본 SPEC의 재현 테스트는 **주입 가능한 소형
  타임아웃 + 그보다 오래 걸리는(블로킹) mock**을 새로 구성해야 하며, 이 파일 또는 신규 전용 테스트
  파일에 추가한다(plan.md §5).

### 가정

- [A-1] 문서화된 "12~15분"(`:3106`) 및 "15분+"(`:3097`)를 정상 실행 시간의 권위 있는 상한 근거로
  채택한다. 실측 프로파일링으로 이 값을 재확인하는 것은 Run 단계 선택 사항이나 본 SPEC의 값
  교정 결정을 막지 않는다(블로커 아님).
- [A-2] 타임아웃은 여전히 **유계(bounded)**여야 하며, 하루 주기(다음 스케줄 잡까지 수 시간 간격)에
  비해 충분히 작은 상한으로 유지한다 — "가드 제거/무한 대기"는 명시적 회귀로 금지한다(REQ-003).
- [A-3] 값 교정은 `_gather_surge_candidates`의 **래퍼 로직만** 건드리며,
  `gather_surge_candidates`(탐지 본체)·앙상블·유니버스·매매 경로에는 diff 0이다(REQ-006).

---

## 3. Requirements (EARS)

### REQ-AI082-001 (Ubiquitous, P0) — 타임아웃이 문서화된 정상 실행 시간을 여유 있게 상회

the system **SHALL** `_gather_surge_candidates()`가 감싸는 `gather_surge_candidates` 실행에 대해,
코드베이스가 문서화한 정상 실행 시간(12~15분)을 **여유(headroom)를 두고 상회**하는 글로벌 타임아웃을
적용해야 한다. 즉 정상 소요 시간 범위 안에서 완료되는 스캔이 타임아웃으로 폐기되어서는 안 된다.

- 근거(§1 표, §2 [A-1]): 현행 300s(5분)는 문서화된 정상 상단(15분)의 1/3에 불과하다. "여유 있게
  상회"의 구체 수치(권장 `1200s`=20분, 15분 대비 ≈+33% 헤드룸)는 plan.md에서 확정하되, 최소
  수용 기준(acceptance 하한)은 AC-082-001에 고정한다.

### REQ-AI082-002 (Event-Driven, P0) — 정상 완료 시 실제 결과 반환(오폐기 금지)

**WHEN** 감싼 `gather_surge_candidates` 호출이 적용된 타임아웃 이내에 완료되면, the system **SHALL**
그 실제 후보 리스트를 반환해야 한다 — 정상 완료된 탐지 작업을 빈 리스트로 폐기해서는 안 된다.

- 근거(§2 [E-2]): 이것이 본 버그의 관찰 가능한 핵심 계약이다. 재현-우선 테스트(REQ-005)가 이
  계약(적용 타임아웃 이내 완료 → 결과 보존)을 실 HTTP 지연 없이 결정적으로 검증한다.

### REQ-AI082-003 (Unwanted, P0) — 무한 대기/가드 제거 금지 [HARD]

the system **SHALL NOT** 타임아웃 가드를 제거하거나 사실상 무한(unbounded)한 대기로 만들어서는 안
된다 — 병리적으로 오래 걸리는 날을 위한 유계 안전망(취소/폐기 경로)은 반드시 유지해야 한다.

- 근거(§2 [A-2]): 값을 올리는 수정이 "영원히 실행되며 상한이 없는" 반대 극단으로 회귀하지 않도록
  명시적으로 금지한다. 타임아웃 발생 시 기존 관찰 가능 거동(경고 로그 + 빈 리스트 반환)은 그대로
  보존한다(REQ-007).

### REQ-AI082-004 (State-Driven, P0) — 타임아웃 값의 테스트 가능성(외부 관찰/주입) [HARD]

**WHILE** 재현-우선 테스트가 래퍼의 타임아웃 거동을 검증하는 동안, the system **SHALL** 실제 HTTP
지연 없이 타임아웃 경계를 결정적으로 구동할 수 있도록 타임아웃 값을 외부에서 관찰/주입 가능한
형태로 노출해야 한다.

- 근거(§2 [E-1]): 현행 함수-로컬 리터럴은 monkeypatch 불가라 실 HTTP 지연 없이는 타임아웃 분기를
  단위 테스트로 재현할 수 없다. 값을 모듈 상수 또는 설정 필드로 승격하는 것이 최소 전제다(구체 방식
  선택은 plan.md §1). 이 요구는 "테스트 가능성"이라는 **결과**를 규정하며, 특정 승격 방식(모듈 상수
  vs 설정 필드)은 지정하지 않는다.

### REQ-AI082-005 (Unwanted, P0) — 변경 전 재현(특성화) 테스트 선행 [HARD]

**IF** 타임아웃 가드 또는 그 값에 대한 변경이 이루어지면, **THEN** 그 변경 이전에 오폐기 거동을
포착하는 실패 테스트가 작성·확인되어 있어야 SHALL 한다(DDD ANALYZE-PRESERVE, 재현-우선 —
CLAUDE.md Rule 4).

- (RED) 소형 주입 타임아웃보다 오래 걸리는(블로킹) mock으로 `_gather_surge_candidates` 호출 시 실제
  후보가 있음에도 `[]`가 반환됨(오폐기)을 재현한다.
- (GREEN) 적용 타임아웃을 감싼 호출의 소요보다 크게 두면 실제 후보 리스트가 그대로 반환됨(오폐기
  없음)을 확인한다.
- 근거(§2 [E-5]): 기존 `test_surge_ai080_fund_manager.py`는 즉시 반환 mock이라 타임아웃 분기를
  건드리지 않는다 — 재현 테스트는 신규 구성이며 기존 케이스와 상호 독립이다.

### REQ-AI082-006 (Ubiquitous, P0) — 범위 한정 (탐지/앙상블/유니버스/매매 불변) [HARD]

the system **SHALL NOT** 다음을 변경해서는 안 된다: `gather_surge_candidates`(탐지 본체)의 알고리즘·
순차 HTTP fetch 구조, 앙상블 점수/가중치/임계값, 스캔 유니버스 구성, 매수·매매 로직(예측 기록 모드,
SPEC-AI-043), 스케줄러 크론 시각·주기. 본 SPEC의 변경은 `_gather_surge_candidates` 래퍼의 타임아웃
값(및 그 승격에 필요한 최소 배선)으로 국한한다.

### REQ-AI082-007 (Event-Driven, P1) — 병리적 초과 시 안전망 거동 보존

**WHEN** 감싼 호출이 상향된 타임아웃마저 진짜로 초과하면, the system **SHALL** 기존 관찰 가능 거동을
보존해야 한다 — 즉 명확한 경고 로그를 남기고 빈 리스트를 반환한다. 본 SPEC은 오폐기의 **빈도를
좁힐 뿐** 안전망을 제거하지 않는다.

- 근거: 상향 후에도 안전망은 동일 형태로 유지되어야 운영자가 "진짜 초과"와 "후보 없음"을 로그로
  계속 구분할 수 있다.

### REQ-AI082-008 (Optional, P2) — 관측성 연속성 (선택)

**WHERE** 타임아웃이 실제로 발생한 경우, the system **SHALL** 로그 메시지에 적용된 타임아웃 초 값을
숫자로 포함해야 한다(기존 `%ds` 형식 유지). 이는 journalctl 이력 분석에서 ASCII 숫자 부분 문자열
(예: `900s`) 검색이 계속 가능하도록 보장한다(§ 검증 주석의 유니코드 정규화 함정 참조). 신규 테이블/
컬럼/마이그레이션 금지, 종목별 INFO 스팸 금지.

---

## 4. Exclusions (What NOT to Build) [HARD]

본 SPEC은 다음을 **명시적으로 범위에서 제외**한다:

- [X-1] **`gather_surge_candidates`의 성능 재구조화 금지** — 순차 per-stock 동기 HTTP 루프를
  동시/배치 fetch로 바꾸는 것은 진짜 근본 원인(§2 [E-4])이지만, 최소 안전 수정의 범위를 벗어난다.
  이는 별도 대형 SPEC 후보다(§8 (b)). 이유: 동시성 도입은 Naver 레이트리밋·세션 안전성·앙상블
  입력 순서 등 블라스트 반경이 크며, 잘못하면 상향된 900s에서도 여전히 느릴 수 있으나 그 판단·설계는
  별도 조사가 필요하다.
- [X-2] **타임아웃 후 고아 스레드 / `db` 세션 수명 안전성 근본 수정 금지** — §2 [E-3]의 위험(취소되지
  않는 스레드가 공유 세션을 뒤늦게 건드림)은 본 SPEC에서 **리스크로 고지([R-3])하되 해결은 유예**한다.
  값 상향은 고아 발생 **빈도**를 부수적으로 줄이지만(대부분 타임아웃 이내 완료) 위험 자체를 닫지는
  않는다. 근본 수정(전용 세션 격리 / 취소 가능 executor / thread-safe 핸드오프)은 별도 후속 SPEC(§8 (c)).
- [X-3] **탐지기·앙상블·가중치·임계·스캔 유니버스·매매(예측 기록 모드) 로직 무변경** (REQ-006).
- [X-4] **스케줄러 크론 시각/주기 변경 금지** — `_run_surge_signal_generate`(10:00/15:20 KST) 등.
- [X-5] **신규 테이블/스키마/마이그레이션/과거 데이터 백필 금지** (전진 적용만, SPEC-AI-071/079/080/081
  관례 계승).
- [X-6] **무한 타임아웃 또는 가드 완전 제거 금지** (REQ-003) — 상한은 반드시 유지.

---

## 5. Risks (리스크)

- [R-1] **브리핑 지연 증가 리스크.** `_gather_surge_candidates`는 `generate_daily_briefing()`의 병렬
  gather(`:3220`)에서도 await 된다. 타임아웃을 5분→20분으로 올리면 브리핑 생성이 급등 gather에 최대
  20분까지 블로킹될 수 있다(현재는 최대 5분). 완화: 브리핑 스케줄이 이 상한을 허용하는지 Run 단계에서
  확인(스케줄 여유가 수 시간이면 무해). 필요 시 두 호출 경로에 서로 다른 타임아웃을 부여하는 안을
  Run에서 검토(단, 최소 수정 원칙상 우선은 단일 값 상향).
- [R-2] **병리적 지연 미해소 리스크.** 값 상향은 순차 HTTP 구조 자체를 고치지 않으므로, 후보 풀이
  극단적으로 큰 날에는 20분마저 초과할 수 있다. 완화: 그날은 REQ-007 안전망으로 기존과 동일하게
  경고+빈 리스트 반환(회귀 아님). 근본 해소는 §8 (b) 후속 SPEC.
- [R-3] **[관련 위험 — 본 SPEC 미해결, 명시 고지] 타임아웃 후 고아 스레드의 세션 경쟁/유실.** §2
  [E-3] 참조. 값 상향으로 발생 빈도는 감소하나 위험 자체는 닫히지 않는다. 오케스트레이터/사용자에게
  이 편차를 명확히 전달하고, 해결은 §8 (c) 후속 SPEC으로 유예한다. **본 SPEC 최상위 편차.**
- [R-4] **테스트 가능성 승격의 부작용 리스크.** 함수-로컬 리터럴을 모듈 상수/설정으로 승격(REQ-004)할
  때 실수로 다른 거동을 건드릴 위험. 완화: 승격은 값의 **위치만** 이동하고 기본 거동은 동일해야 하며
  (기존 mock 테스트 무회귀, §2 [E-5]), 승격 전/후 diff를 코드 리뷰 체크리스트로 고정.

---

## 6. Related SPECs (관련 SPEC)

- **SPEC-AI-012 (선행)**: `_gather_surge_candidates`/`gather_surge_candidates` 원 소유(급등 후보 수집).
  본 SPEC은 그 async 래퍼의 타임아웃 값만 교정.
- **SPEC-AI-022 (근거 출처)**: `fund_manager.py:3106`의 "12~15분 실행" 주석이 이 SPEC의 정상 실행
  시간 근거다. SPEC-AI-022 커버리지 확장 로직 자체는 무변경.
- **SPEC-AI-043 (계승)**: 예측 기록 모드(실매매 비활성) 유지 — 매매 로직 무변경(REQ-006).
- **SPEC-AI-080/081 (인접, 무관)**: 07-09 최초 타임아웃 발생이 이들 배포(2026-07-16)보다 앞서므로
  본 버그는 선재·독립. 이들 로직 무변경.
- **SPEC-AI-079 (참고 패턴)**: 공유 코드의 거동 전환 시 설정 게이팅·기본값 롤아웃 관례 — REQ-004에서
  타임아웃 값을 설정 필드로 승격할 경우 이 패턴을 참고(단, 모듈 상수 승격도 허용).

---

## 7. Open Questions (열린 질문 — Run 단계 확정)

- [OQ-1] **타임아웃 값 승격 방식.** 모듈 상수(`fund_manager.py` 최상단)로 승격할지, `SurgeDetectionConfig`
  설정 필드로 승격할지. 최소 수정·단순성(CLAUDE.md Agent Core Behavior #4) 관점에서 plan.md는 모듈
  상수를 권장하되, 다른 surge 파라미터와의 일관성(설정 중앙화)을 이유로 설정 필드도 후보다. 어느
  쪽이든 REQ-004(테스트 주입 가능)를 충족해야 한다.
- [OQ-2] **정확한 상향 값.** AC 하한은 `>= 1200s`(20분)로 고정하되, 실측 프로파일이 가능하면 Run
  단계에서 정상 상단 대비 헤드룸을 재검토(블로커 아님).
- [OQ-3] **브리핑 경로 별도 타임아웃 여부([R-1]).** 단일 값 상향으로 충분한지, 두 호출 경로에 서로
  다른 타임아웃이 필요한지는 Run 단계에서 브리핑 스케줄 여유를 확인 후 판단(기본은 단일 값).

---

## Implementation Notes (Level 1)

### 실제 구현 요약 (2026-07-20, commit b2e6cbc)

#### 핵심 변경사항

**타임아웃 상수 승격** (`fund_manager.py`)
- `_GATHER_TIMEOUT_S = 300` (함수 내부 리터럴) → `_GATHER_TIMEOUT_S = 1200` (모듈 레벨 상수, 
  `:1295` 이동)
- 테스트 가능성(REQ-004): monkeypatch/주입 가능한 모듈 상수로 승격, 기존 동작 diff 0

**재현 테스트** (`test_surge_ai082_gather_timeout.py`)
- 신규 7개 테스트 (245줄): RED 재현(소형 주입 타임아웃 + 블로킹 mock) → 오폐기 확인, GREEN 
  (타임아웃 상향) → 결과 보존 확인
- DDD PRESERVE 기존 mock 테스트 무회귀 확인(`test_surge_ai080_fund_manager.py` 기존 케이스 
  동일 통과)

**폐기 경로 보존** (`fund_manager.py:1311-1316`)
- `asyncio.TimeoutError` 핸들러: 경고 로그 + `return []` 기존 거동 유지 (REQ-007)

#### 편차 및 선택사항

**[R-3] 타임아웃 후 고아 스레드 미해결**
- 미해결 위험으로 명시 고지(§5 [R-3]). 값 상향으로 발생 빈도는 감소하나 위험 자체는 닫히지 않음.
  근본 수정(세션 격리 / 취소 가능 executor / thread-safe 핸드오프)은 §8(c) 후속 SPEC 후보로 
  유예(SPEC 작성 단계에서 동의 문서에 명시적 기록).

#### 신규 테이블/마이그레이션

- 없음. 스키마 변경 없음. 과거 데이터 백필 없음(2026-07-20 이후 전진 적용).

#### 배포 상태

- 로컬 검증 완료(2026-07-20, commit b2e6cbc). main push 이후 프로덕션 배포 대기.

#### 영향 파일

- `backend/app/services/fund_manager.py` (diff: +1 모듈 상수, -2 함수 내부 로컬)
- `backend/tests/test_surge_ai082_gather_timeout.py` (신규, 7 tests)

---

## 8. Follow-up Candidates (후속 후보 — 본 SPEC 범위 밖)

- (a) **정상 실행 시간 실측 프로파일링** — 12~15분 문서 값을 라이브 계측으로 재확인하고 헤드룸을
  데이터로 재산정(경량, 관측 전용).
- (b) **`gather_surge_candidates` 동시/배치 HTTP 재구조화([X-1])** — 순차 per-stock fetch를
  동시성/배치로 전환하는 진짜 성능 근본 수정. Naver 레이트리밋·세션 안전성 리스크 있어 별도 대형
  조사 필요. 상향된 타임아웃에서도 병리적으로 느린 날(§[R-2])의 최종 해소책.
- (c) **타임아웃 후 고아 스레드 / 세션 수명 안전성([X-2], [R-3])** — 취소 불가 스레드가 공유 `db`
  세션을 뒤늦게 건드리는 경쟁을 닫는 수정(전용 세션 격리 / 취소 가능 executor / thread-safe 핸드오프).
