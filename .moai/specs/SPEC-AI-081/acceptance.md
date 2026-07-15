# Acceptance Criteria: SPEC-AI-081 — 공시 충격 스코어링 flat-base 카테고리 콘텐츠 인식 정밀화

검증은 모두 `score_disclosure_impact()`의 **관찰 가능한 반환값**과, 하위 소비자(임계 게이팅 로직)의
**입력값 전달 정합성**으로 고정한다. 매매/발신 부작용은 검증 대상이 아니다(예측 기록 모드).

모든 AC는 EARS(Easy Approach to Requirements Syntax) 문장 패턴(Ubiquitous/Event-Driven/State-Driven/
Unwanted/Optional)으로 서술한다. RED(수정 전 특성화)와 GREEN(수정 후 목표) 거동이 모두 존재하는
AC는 각각 별도의 EARS 문장으로 구분해 명시한다(REQ-007 재현 우선 원칙).

**중요 — 범위 편차 고지 (spec.md [X-9]/[R-3] 참조):** 038880형(희석성 증권 발행결정 재분류) 사례는
"flat +20보다 더 높은 점수"를 기준으로 검증하지 **않는다**. 코드 재검증 결과, `report_name`만으로는
희석 신호의 방향성(호재/악재)을 판별할 근거가 없어(spec.md §2 [E-6]) 상향을 인위적으로 강제하면
오탐 위험이 커진다. 대신 "발행공시 스코어링 경로로 정확히 라우팅되는가(차등 처리)"를 기준으로
검증한다.

---

## AC-081-001 (REQ-001, 최대주주 지배권 변경 — 006340형 재현/교정) [HARD]

**핵심 재현 시나리오.** 2026-07-13 006340(대원전선) 사례를 대표한다.

- (RED, 특성화) 테스트 전제: 코드베이스가 본 SPEC 수정 전 상태이고 `disclosure_content_aware_scoring
  .enabled=true`이다. **WHEN** `score_disclosure_impact()`가 `report_type="지분공시"`,
  `report_name="최대주주등소유주식변동신고서"`인 공시로 호출되면, the system **SHALL** `score ==
  25.0`을 반환한다(Tier1 키워드 "최대주주 변경"의 리터럴 불일치로 flat 기본값이 적용되는 커버리지
  갭의 특성화 — 실패 테스트가 이 갭을 포착한다).
- (GREEN, 목표) **WHEN** 최대주주 지배권 변경 키워드 커버리지 확장이 구현된 이후 `score_disclosure_
  impact()`가 동일 입력(`disclosure_content_aware_scoring.enabled=true`, `report_type="지분공시"`,
  `report_name="최대주주등소유주식변동신고서"`)으로 호출되면, the system **SHALL** `score >= 30.0`을
  반환한다(Tier1 배수 ×2.0 적용 시 `25 * 2.0 = 50.0` — flat 기본값 25 대비 최소 +5점 이상, 기존
  섹터파급 트리거 임계 이상으로 유의미하게 상향됨을 확인).

---

## AC-081-002 (REQ-002, 희석성 증권 발행결정 — 038880형 재분류 차등 처리) [HARD]

**핵심 재현 시나리오.** 2026-07-13 038880(아이에이) 사례를 대표한다.

- (RED, 특성화) 테스트 전제: 코드베이스가 본 SPEC 수정 전 상태이고 `disclosure_content_aware_scoring
  .enabled=true`이다. **WHEN** `score_disclosure_impact()`가 `report_type="주요사항보고"`,
  `report_name="주요사항보고서(전환사채권발행결정)"`인 공시로 호출되면, the system **SHALL** `score
  == 20.0`을 반환한다(`base=20 * multiplier=1.0`, "전환사채" 키워드가 Tier1/2/3 목록에 없어 동일
  카테고리 무신호 공시(465770형, AC-081-003)와 구분되지 않는 값을 받는 커버리지 갭의 특성화 —
  실패 테스트가 이 갭을 포착한다).
- (GREEN, 목표) **WHEN** 희석성 증권 발행결정 로컬 재분류가 구현된 이후 `score_disclosure_impact()`가
  동일 입력으로 호출되면, the system **SHALL** 이 공시를 "발행공시" 스코어링 경로로 라우팅하고
  `score == -10.0`을 반환한다(`_BASE_IMPACT_BY_TYPE["발행공시"]`와 동일 — 동일 카테고리
  "주요사항보고"의 무신호 공시(플랫 +20, AC-081-003)와 명확히 다른 점수를 받아 차등 처리가 이루어짐을
  확인).
- (불변식) **IF** 위 재분류가 적용되어 `score_disclosure_impact()`가 실행되면, **THEN** the system
  **SHALL NOT** `disclosure.report_type`(저장 필드)의 값을 변경한다 — 저장값은 여전히
  `"주요사항보고"`로 남아있어야 한다(REQ-006 (c), 재분류는 스코어링 함수 내부 로컬 계산에만 적용).

**참고 (비검증 범위, 비-EARS 서술 — 통과 기준 아님):** 위 GREEN 기준(`score == -10.0`)은 "발행공시
스코어링 경로로 정확히 라우팅되는가(차등 처리)"만을 요구한다. `score > 20.0`(상향)은 본 AC의 통과
조건에 포함되지 않는다 — 위 [범위 편차 고지] 참조.

---

## AC-081-003 (REQ-005, 무신호 공시 인플레이션 금지 — 465770형 음성 대조군) [HARD]

- **WHEN** 수정 후 `score_disclosure_impact()`가 `disclosure_content_aware_scoring.enabled=true`,
  `report_type="주요사항보고"`, `report_name="투자판단관련주요경영사항"`(범용 캐치올, 신규 키워드
  어디에도 매칭되지 않음)인 공시로 호출되면, the system **SHALL** `score == 20.0`(주요사항보고 flat
  기본값과 정확히 동일)을 반환한다 — 신호가 없는 공시는 the system **SHALL NOT** 인위적으로
  상향한다.
- 이 케이스는 spec.md [X-1]에 따라 본 SPEC으로 해결 불가한 유형(DART 원문 본문 미보유)이며, 본 AC는
  오탐 방지 회귀 가드(음성 대조군)로 재사용한다.

---

## AC-081-004 (REQ-005, 루틴 지분공시 무회귀)

- **WHEN** 수정 후 `score_disclosure_impact()`가 `report_type="지분공시"`, `report_name="임원·주요
  주주특정증권등소유상황보고서"`(기존 루틴 거버넌스 캡 대상, "최대주주" 키워드 없음)인 공시로
  호출되면, the system **SHALL** `score == 5.0`(기존 루틴 캡, 무변경)을 반환한다.
- 근거: 신규 최대주주 정규화 매칭은 "최대주주" 어근이 없는 이 제목에 매칭되지 않으며, 애초에 루틴
  캡이 스코어링 함수 최상단에서 조기 반환하므로 신규 로직에 도달하지도 않는다(spec.md §2 [E-5]).

---

## AC-081-005 (REQ-004, 백워드 호환 — 토글 비활성 = 레거시 완전 동등) [HARD]

- **WHILE** `disclosure_content_aware_scoring.enabled=false`(기본값)인 동안,
  `score_disclosure_impact()`가 AC-081-001의 006340형 입력으로 호출될 때마다 the system **SHALL**
  `score == 25.0`을 반환한다(정렬 도입 이전 레거시 거동과 정확히 동일).
- **WHILE** `disclosure_content_aware_scoring.enabled=false`(기본값)인 동안,
  `score_disclosure_impact()`가 AC-081-002의 038880형 입력으로 호출될 때마다 the system **SHALL**
  `score == 20.0`을 반환한다(정렬 도입 이전 레거시 거동과 정확히 동일).
- **WHILE** `disclosure_content_aware_scoring.enabled=false`(기본값)인 동안, the system **SHALL**
  `test_disclosure_impact_scorer.py`의 기존 `TestScoreDisclosureImpact` 전체 케이스(기업지배구조
  루틴/M&A가산, 지분공시, 발행공시, 수주계약, 실적변동, 정기공시, 기타공시)를 코드 변경 없이 그대로
  통과시킨다.

---

## AC-081-006 (REQ-006, 인접 카테고리·소비자·저장값 불변식 diff 0) [HARD]

- **WHEN** `score_disclosure_impact()`가 실적변동/기업지배구조/발행공시/정기공시/기타공시 5개
  카테고리 중 임의의 공시 입력으로 호출되면, the system **SHALL** `disclosure_content_aware_scoring
  .enabled` 토글의 활성/비활성 여부와 무관하게 완전히 동일한 결과값을 반환한다(REQ-001/002는 오직
  주요사항보고/지분공시 flat-base 경로에만 개입).
- **IF** 본 SPEC의 변경이 적용되면, **THEN** the system **SHALL NOT** `process_disclosure_impact()`의
  임계 분기 조건식(`impact_score >= 20` 기준가 스냅샷 트리거, `is_after_market and impact_score >=
  25` gap_pullback 트리거, `detect_sector_ripple`의 `impact_score >= 30` 진입 조건,
  `immediate_surge.min_impact` 즉시발화 게이팅)을 변경한다 — 새 `impact_score` 값이 이 기존
  조건식에 입력으로 흘러들어갈 뿐임을 통합 테스트로 확인한다.
- **IF** 본 SPEC의 변경이 적용되면, **THEN** the system **SHALL NOT** `disclosure.report_type`
  (저장 필드), `dart_crawler._classify_report_type()`, `_REPORT_TYPE_PATTERNS`를 변경한다 —
  코드/데이터 양쪽에서 diff 0으로 확인한다.

---

## AC-081-007 (REQ-007, 특성화 테스트 선행 — DDD 재현 우선) [HARD]

- **IF** `score_disclosure_impact()` 또는 그 하위 소비자에 대한 변경이 이루어지면, **THEN** the
  system **SHALL** 그 변경 이전에 AC-081-001/002의 RED 시나리오(006340형/038880형)를 재현하는
  특성화 테스트가 먼저 작성되고 실행되어 확인된 이후에만 IMPROVE 단계(키워드 확장/재분류 구현)로
  진행한다(CLAUDE.md Rule 4, 재현 우선).
- the system **SHALL** 전체 백엔드 회귀 스위트를 무회귀로 통과한다: `cd backend && uv run pytest
  tests/ --tb=short -q -m "not slow"`(기본 실행) 및 `-n 4`(xdist 병렬) 양쪽.
- the system **SHALL** `cd backend && uv run ruff check .`를 무경고로 통과하고, `uv run mypy app/`을
  프로젝트 기존 상태 대비 회귀 없이 통과한다.

---

## AC-081-008 (REQ-008, 관측성 — P2 선택)

- **WHERE** 006340형/038880형처럼 신규 로직이 실제로 트리거된 스코어링 호출인 경우, the system
  **SHALL** flat 기본값 대비 점수가 변경되었음을 나타내는 로그를 방출한다(신규 DB 컬럼/마이그레이션
  없음, 종목별 INFO 스팸 없음. 본 AC 전체는 REQ-008과 마찬가지로 P2/선택 요구사항이며, 선택성은
  라벨과 WHERE 트리거 조건으로 표현한다).
- **WHERE** 신호가 없어 flat 기본값이 유지된 호출(465770형)인 경우, the system **SHALL NOT** 이
  로깅을 방출한다.

---

## AC-081-009 (REQ-003, ai_summary 비의존성 검증) [HARD]

- **WHEN** `score_disclosure_impact()`가 동일한 `report_name`(006340형 또는 038880형 입력)에 대해
  `ai_summary=None`으로 호출되는 경우와, 관련 없는 임의의 비어있지 않은 텍스트로 `ai_summary`가
  채워져 호출되는 경우를 각각 실행하면, the system **SHALL** 두 경우 모두 동일한 `score` 값을
  반환한다(1차 신호원은 report_name이며, ai_summary 필드의 존재 여부 자체가 스코어링 결과를
  좌우해서는 안 됨을 확인).
- the system **SHALL NOT** `ai_summary` 필드의 값 존재 자체를 REQ-001/002 신규 로직의 1차 또는
  필수 판정 조건으로 사용한다 — `ai_summary`가 채워진 경우 신규 키워드가 매칭되더라도, 그 매칭은
  텍스트 내용 자체(동일 키워드가 ai_summary에도 포함된 경우)에 기인해야 하며 필드의 None 여부
  자체가 분기 조건이 되어서는 안 된다.

---

## Definition of Done

- [ ] AC-081-001/002/003/005/006/007/009 전부 통과(001/002/007은 RED→GREEN 재현 우선 순서 준수).
      004는 함께 통과 확인. 008(REQ-008)은 P2(선택).
- [ ] 최대주주 정규화 매칭 + 희석성 발행결정 로컬 재분류만 신규 추가 — 다른 5개 카테고리/소비자
      게이팅 로직/`report_type` 저장값/`dart_crawler.py` diff 0.
- [ ] `disclosure_content_aware_scoring.enabled`(기본 `false`) 설정 필드 + `surge_detection.yaml`
      키 추가.
- [ ] 038880형 사례는 "차등 처리"로만 검증하며 "상향"으로 검증하지 않음이 acceptance.md와 spec.md
      [X-9] 양쪽에 일관되게 명시되어 있다.
- [ ] 465770형(범용 캐치올)은 오탐 방지 음성 대조군으로 재사용되며, DART 원문 미보유로 인한 근본
      해결 불가 사실이 spec.md [X-1]/§8에 명시되어 있다.
- [ ] AC-081-009(REQ-003)로 ai_summary가 1차/필수 신호원으로 의존되지 않음이 검증되어 있다.
- [ ] 신규/변경 로직 커버리지 85%+, `ruff` 무경고, `mypy` 통과.
- [ ] 전체 백엔드 스위트 회귀 없음 — 로컬 기본 실행 + `-n 4`(xdist) 병렬 실행 양쪽 확인.
- [ ] `score_disclosure_impact` 함수에 신규 로컬 재분류/키워드 확장 지점을 `@MX:NOTE`
      (+`@MX:SPEC: SPEC-AI-081`)로 기록, 필요 시 `effective_report_type`이 저장값과 다를 수 있음을
      `@MX:WARN`(+`@MX:REASON`)으로 표시.
- [ ] 신규 테이블/마이그레이션 없음. 과거 데이터 백필 없음(전진 적용).
