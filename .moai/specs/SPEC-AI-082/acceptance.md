# Acceptance Criteria: SPEC-AI-082 — 급등 후보 수집 글로벌 타임아웃 오폐기 교정

검증은 모두 `_gather_surge_candidates()`의 **관찰 가능한 반환값**(빈 리스트 vs 실제 후보 리스트)과,
적용된 타임아웃 값(모듈 상수 또는 설정)의 **결정적 구동**으로 고정한다. 실제 12~15분 HTTP 지연은
재현하지 않으며, 소형 주입 타임아웃 + 블로킹 mock으로 래퍼의 타임아웃 경계 거동을 대리 검증한다
(spec.md §2 [E-1]/[E-5], plan.md §3). 매매/발신 부작용은 검증 대상이 아니다(예측 기록 모드).

모든 AC는 EARS(Easy Approach to Requirements Syntax) 문장 패턴(Ubiquitous/Event-Driven/State-Driven/
Unwanted/Optional)으로 서술한다. RED(수정 전 특성화)와 GREEN(수정 후 목표) 거동이 모두 존재하는 AC는
각각 별도의 EARS 문장으로 구분해 명시한다(REQ-005 재현-우선 원칙).

**중요 — 관련 위험 고지 (spec.md [R-3]/[X-2] 참조):** 타임아웃 후 고아 스레드가 공유 `db` 세션을
뒤늦게 건드리는 세션 수명 위험은 본 SPEC에서 **해결하지 않는다**. 본 AC는 값 상향과 오폐기 거동
교정만 검증하며, 고아 스레드 안전성은 후속 SPEC(§8 (c))으로 유예됨을 명시한다.

---

## AC-082-001 (REQ-001, 타임아웃 값이 정상 실행 시간을 여유 있게 상회) [HARD]

- **WHEN** 테스트가 `_gather_surge_candidates()`가 사용하는 적용 타임아웃 값(승격된 모듈 상수 또는
  설정 필드)을 조회하면, the system **SHALL** 그 값이 `>= 1200`초(20분)임을 만족한다 — 코드베이스가
  문서화한 정상 실행 시간 상단(15분/900s)을 여유 있게 상회함을 값 회귀 가드로 고정한다.
- 근거: 300s(현행)는 문서화된 정상 상단의 1/3에 불과하다(spec.md §1 표). 이 AC는 값이 다시 900s
  이하로 회귀하지 않도록 하한을 고정한다.

---

## AC-082-002 (REQ-005/002, 오폐기 재현 → 교정 — RED/GREEN) [HARD]

**핵심 재현 시나리오.** 2026-07-20 프로덕션 10:00 KST 잡의 "300s 초과 → 0개 후보" 오폐기를 대표한다.

- (RED, 특성화) 테스트 전제: 적용 타임아웃을 소형 값(예: 0.05초)으로 주입(monkeypatch)하고,
  `app.services.fund_manager.gather_surge_candidates`를 그보다 오래 블로킹하는 mock(예: 내부
  `time.sleep(0.2)` 후 비어있지 않은 후보 리스트 반환)으로 대체한다. **WHEN** 이 상태에서
  `_gather_surge_candidates()`가 호출되면, the system **SHALL** 빈 리스트 `[]`를 반환한다(실제 후보가
  있음에도 타임아웃으로 오폐기되는 거동의 특성화 — 실패 테스트가 이 오폐기를 포착한다).
- (GREEN, 목표) **WHEN** 적용 타임아웃을 감싼 mock의 소요보다 크게(예: 5초) 주입하고 동일 mock으로
  `_gather_surge_candidates()`가 호출되면, the system **SHALL** 그 실제 후보 리스트(비어있지 않음)를
  그대로 반환한다(적용 타임아웃 이내 완료 시 오폐기 없음, REQ-002).

---

## AC-082-003 (REQ-003/007, 병리적 초과 시 안전망 거동 보존) [HARD]

- **WHEN** 감싼 `gather_surge_candidates` 호출이 적용된(상향된) 타임아웃마저 초과하면(소형 주입
  타임아웃 + 그보다 오래 블로킹하는 mock으로 모사), the system **SHALL** 명확한 경고 로그를 남기고
  빈 리스트 `[]`를 반환한다 — 기존 안전망 거동을 그대로 보존한다.
- the system **SHALL NOT** 타임아웃 가드를 제거하거나 사실상 무한 대기로 만들어서는 안 된다 —
  상한(유계 폐기 경로)은 반드시 유지된다.

---

## AC-082-004 (REQ-004, 타임아웃 값의 테스트 주입 가능성) [HARD]

- **WHILE** 재현 테스트가 실행되는 동안, the system **SHALL** 적용 타임아웃 값을 실제 HTTP 지연 없이
  결정적으로 주입/조회할 수 있는 형태(모듈 상수 또는 설정 필드)로 노출한다 — 함수-로컬 리터럴로 인해
  monkeypatch가 불가능했던 상태(spec.md §2 [E-1])가 해소되어 있어야 한다.
- 근거: AC-082-002의 RED/GREEN 테스트 자체가 이 주입 가능성 없이는 작성 불가하므로, 이 AC는
  AC-082-002 성립의 전제로 함께 검증된다.

---

## AC-082-005 (REQ-006, 범위·불변식 diff 0) [HARD]

- **IF** 본 SPEC의 변경이 적용되면, **THEN** the system **SHALL NOT** `surge_detector.py::
  gather_surge_candidates`(탐지 본체)의 알고리즘·순차 HTTP fetch 구조, 앙상블 점수/가중치/임계값,
  스캔 유니버스 구성, 매수·매매 로직, 스케줄러 크론 시각·주기를 변경한다 — 코드 diff 0으로 확인한다.
- **WHILE** 기존 `test_surge_ai080_fund_manager.py`가 실행되는 동안(즉시 반환 mock이라 타임아웃
  분기에 도달하지 않음, spec.md §2 [E-5]), the system **SHALL** 전체 케이스를 코드 변경 없이 그대로
  통과시킨다.

---

## AC-082-006 (REQ-005, 특성화 테스트 선행 — DDD 재현 우선) [HARD]

- **IF** `_gather_surge_candidates()`의 타임아웃 가드 또는 그 값에 대한 변경이 이루어지면, **THEN**
  the system **SHALL** 그 변경 이전에 AC-082-002의 RED 시나리오(오폐기 `[]` 재현)를 포착하는 특성화
  테스트가 먼저 작성되고 실행되어 실패가 확인된 이후에만 IMPROVE 단계(값 승격·상향)로 진행한다
  (CLAUDE.md Rule 4, 재현 우선).
- the system **SHALL** 전체 백엔드 회귀 스위트를 무회귀로 통과한다: `cd backend && uv run pytest
  tests/ --tb=short -q -m "not slow"`(기본 실행) 및 `-n 4`(xdist 병렬) 양쪽.
- the system **SHALL** `cd backend && uv run ruff check .`를 무경고로 통과하고, `uv run mypy app/`을
  프로젝트 기존 상태 대비 회귀 없이 통과한다.

---

## AC-082-007 (REQ-008, 관측성 연속성 — P2 선택)

- **WHERE** 타임아웃이 실제로 발생한 경우, the system **SHALL** 경고 로그 메시지에 적용된 타임아웃
  초 값을 숫자로 포함한다(기존 `%ds` 포맷 유지) — journalctl 이력에서 ASCII 부분 문자열(예: `1200s`)
  검색이 계속 가능하도록 보장한다. 본 AC 전체는 REQ-008과 마찬가지로 P2/선택 요구사항이며, 선택성은
  라벨과 WHERE 트리거 조건으로 표현한다.
- 근거(검증 함정): 한국어 단어 `타임아웃`으로 grep 시 유니코드 정규화 불일치로 거짓 음성이
  발생하므로, 프로덕션 로그 검증은 ASCII 숫자 부분 문자열로 수행한다(plan.md 검증 명령 주석).

---

## Definition of Done

- [ ] AC-082-001/002/003/004/005/006 전부 통과(002/006은 RED→GREEN 재현 우선 순서 준수). 007(REQ-008)은
      P2(선택).
- [ ] `_GATHER_TIMEOUT_S`(또는 설정 필드)가 함수-로컬 리터럴에서 테스트 주입 가능한 형태로 승격되고,
      값이 `>= 1200s`(20분)로 상향되어 있다.
- [ ] 타임아웃 발생 시 경고 로그 + 빈 리스트 반환 안전망이 그대로 보존되어 있다(무한 대기/가드 제거
      아님).
- [ ] 탐지 본체(`gather_surge_candidates`)·앙상블·가중치·임계·스캔 유니버스·매매 로직·스케줄러 크론
      diff 0. 기존 `test_surge_ai080_fund_manager.py` 무회귀.
- [ ] 신규 테이블/마이그레이션 없음. 과거 데이터 백필 없음(전진 적용).
- [ ] 고아 스레드/세션 수명 위험([R-3]/[X-2])이 본 SPEC 미해결이며 후속 SPEC(§8 (c))으로 유예됨이
      spec.md에 명시되어 있고, 오케스트레이터/사용자에게 이 편차가 전달된다.
- [ ] 신규/변경 로직 커버리지 85%+, `ruff` 무경고, `mypy` 회귀 없음.
- [ ] 전체 백엔드 스위트 회귀 없음 — 로컬 기본 실행 + `-n 4`(xdist) 병렬 실행 양쪽 확인.
- [ ] `_gather_surge_candidates` 타임아웃 지점에 `@MX:NOTE`(+`@MX:SPEC: SPEC-AI-082`)로 정상 실행
      시간 근거(12~15분)와 유계 유지 원칙을 기록.
