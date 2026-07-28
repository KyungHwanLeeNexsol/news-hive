# SPEC-AI-091 — Acceptance Criteria (인수 기준)

> GEARS 정규 문장(normative sentence) 형식으로 작성한다. 각 AC는 **볼드 WHEN/WHILE/WHERE
> 트리거 + 볼드 shall/shall not 절**로 구성한다 — Given-When-Then 시나리오는 §D "시나리오"
> 섹션에서 각 AC를 구체적 예시로 보강하는 용도로만 사용하며, AC 정의 자체는 아니다.

## §A. AC 매트릭스 (REQ ↔ AC 매핑)

| AC ID | 대응 REQ | 심각도 |
|-------|----------|--------|
| AC-AI091-001 | REQ-AI091-001 | Must-Pass |
| AC-AI091-002 | REQ-AI091-002 | Must-Pass |
| AC-AI091-003 | REQ-AI091-003 | Should-Pass |
| AC-AI091-004 | REQ-AI091-004 | Must-Pass |
| AC-AI091-005 | REQ-AI091-005 | Must-Pass |
| AC-AI091-006 | REQ-AI091-006 | Should-Pass |
| AC-AI091-007 | REQ-AI091-007 | Must-Pass |
| AC-AI091-008 | REQ-AI091-008 | Should-Pass |
| AC-AI091-009 | REQ-AI091-009 | Must-Pass |
| AC-AI091-010 | REQ-AI091-010 | Must-Pass |
| AC-AI091-011 | REQ-AI091-011 | Must-Pass |

---

## §B. 인수 기준 (정규 문장)

### AC-AI091-001 — direct-relevance 전용 텍스트 스코핑

**While** `_gather_stock_theme_texts()`가 종목의 테마 키워드 소스 텍스트를 조회하는 동안,
the function **shall** `NewsStockRelation.relevance == "direct"`인 행에서 나온 텍스트만
반환하고 `relevance == "indirect"`인 행의 텍스트는 반환 목록에서 제외해야 한다.

- 검증: `db.query(...).filter(NewsStockRelation.relevance == "direct")`가 SQL 쿼리에
  포함되는지 단위 테스트로 확인. indirect 관계만 있는 종목에 대해 빈 리스트 또는 direct
  텍스트만 반환하는지 확인.

### AC-AI091-002 — 다중 텍스트 출현 임계

The keyword extraction function **shall** 하나의 소스 텍스트 목록에서 어떤 테마 키워드가
정확히 1개의 텍스트에만 등장하는 경우 그 키워드를 매칭 결과에서 제외하고, 최소 2개의
서로 다른 텍스트에 등장하는 키워드만 결과에 포함해야 한다.

- 검증: 3개 텍스트 중 1개에만 "로봇"이 등장하는 픽스처 → 매칭 결과에 "로봇" 없음. 2개
  이상 텍스트에 등장 → 매칭 결과에 포함.

### AC-AI091-003 — 한글 선행문자 경계 가드

**While** 텍스트 내에서 키워드 매칭 위치를 탐색하는 동안, the keyword extraction function
**shall** 매칭 시작 위치 직전 문자가 한글 음절 범위(`가`-`힣`)인 경우 해당 매칭을
거부해야 한다.

- 검증: "하이닉스" 텍스트에서 테마 어휘에 "이닉스" 유사 문자열이 있다고 가정할 때(대표
  예시, 실제 10개 어휘 중 해당 케이스가 없으면 합성 픽스처로 검증) 오탐 매칭이 발생하지
  않음을 단위 테스트로 확인.

### AC-AI091-004 — 지속 태깅 트리거의 단일 relevance 게이트

**When** 뉴스 저장 훅이 이번 크롤 배치의 `_touched_stock_ids`(또는 그 재구현)를 구성할 때,
the news collection pipeline **shall** `relevance == "direct"`인 `NewsStockRelation` 행에서
비롯된 `stock_id`만 그 집합에 포함해야 한다.

- 검증: `relevance="indirect"` 관계만 생성된 종목의 `stock_id`가 `_touched_stock_ids`에
  포함되지 않음을 단위 테스트로 확인. `relevance="direct"` 관계가 하나라도 있으면 포함됨을
  확인(direct 관계가 하나, indirect 관계가 여럿인 혼합 케이스 포함).

### AC-AI091-005 — indirect 전용 관계로는 지속 태깅 호출 금지

**When** 어떤 종목이 해당 크롤 배치에서 오직 indirect 관계로만 터치된 경우, the system
**shall not** 그 종목의 `stock_id`에 대해 `refresh_stock_keywords()`를 호출해서는 안 된다.

- 검증: mock/spy로 `refresh_stock_keywords` 호출 인자를 캡처 — indirect-only 종목의
  `stock_id`가 호출 인자 리스트에 없음을 확인.

### AC-AI091-006 — 설명 기반 관계 경로의 동등 적용

**When** `_resolve_description_relations()`가 `relevance="indirect"` 관계를 생성하면, the
AC-AI091-004 게이트 **shall** 그 관계에서 비롯된 `stock_id`도 동일하게 배제해야 한다 — 쿼리
매칭이나 제목 매칭으로 생성된 indirect 관계와 차별 없이 동일 로직 경로를 통과해야 한다.

- 검증: `DescriptionRelationMatchingConfig.enabled=True` 상태에서 설명 전용 indirect 매칭이
  발생하는 픽스처를 구성해, 해당 종목이 `_touched_stock_ids`(또는 재구현)에서 배제됨을
  확인.

### AC-AI091-007 — 리셋 후 재백필 정화 스크립트

The remediation script **shall** (a) 자동 태깅 기원으로 판단된 종목의 `stocks.keywords`를
`NULL`로 리셋하고, (b) 수정된 알고리즘(AC-AI091-001~003)이 반영된 `backfill_stock_keywords()`를
호출해 재채움하며, (c) 기본적으로 dry-run(진단만) 모드로 실행되고 `--execute` 플래그가
명시되어야만 실제 DB를 변경해야 한다.

- 검증: `--execute` 없이 실행 시 DB 변경 없음(진단 로그만 출력)을 통합 테스트로 확인.
  `--execute` 포함 시 대상 종목의 `keywords`가 리셋 후 재채움됨을 확인(SQLite 테스트 DB).

### AC-AI091-008 — provenance 불명 종목의 기본 포함 + 진단 보고

**While** 어떤 종목의 `keywords` 기원(자동/수동)을 판별할 수 없는 상태인 동안, the
remediation script **shall** 그 종목을 기본적으로 리셋 대상에 포함하되, 리셋 실행 전에
그러한 종목의 개수를 진단 로그로 보고해야 한다.

- 검증: 진단 단계 로그 출력에 불명확 종목 카운트가 포함됨을 확인.

### AC-AI091-009 — 정화 후 키워드 개수 분포 상한

**When** 정화 스크립트(AC-AI091-007)의 실행이 완료되면, the tagged-stock keyword-length
distribution **shall** 다음을 만족해야 한다: (a) 태깅된 종목(`keywords`가 비어있지 않은
전체 종목) 중 `keywords` 배열 길이가 정확히 `max_keywords_per_stock`(10)인 종목의 비율이
**5% 이하**, (b) `keywords` 배열 길이의 중앙값이 **4 이하**.

- 검증: 정화 후 프로덕션 DB(또는 테스트 픽스처 DB)에 대한 SQL 집계 쿼리로 확인
  (`SELECT COUNT(*) FILTER (WHERE array_length(keywords,1) = 10) * 1.0 / COUNT(*) FROM
  stocks WHERE keywords IS NOT NULL`). 초기 수치(2026-07-28 기준 20%, 144/719)와 비교해
  개선 여부를 정량 보고한다.
- 참고: 이 수치 상한(5%/4)은 plan-phase 제안값이며, M3 재백필 실측 결과에 따라 DP-2
  임계값과 함께 조정될 수 있다(조정 시 이 AC 문서를 갱신).

### AC-AI091-010 — 확정 오탐 종목 스팟체크

**When** 정화 스크립트(AC-AI091-007)의 실행이 완료되면, 종목 `023790`(동일스틸럭스),
`105560`(KB금융), `192080`(더블유게임즈) 각각의 `keywords` 배열 길이는 **shall not** 3을
초과해서는 안 된다.

- 검증: 3개 종목 각각에 대한 개별 DB 조회 스팟체크 스크립트/테스트.

### AC-AI091-011 — 무관 시스템 회귀 금지

The system **shall not** 본 SPEC 구현으로 인해 `tests/test_services/test_news_crawler.py`,
`tests/test_keyword_tagging_service.py`를 포함한 기존 테스트 스위트에 새로운 실패를
발생시켜서는 안 되며, `ThemeNewsCarryConfig`/`theme_cluster`의 동작을 변경해서는 안 된다.

- 검증: `cd backend && uv run pytest tests/ --tb=short -q -m "not slow"` 전체 스위트 그린.
  `git diff`에 `theme_cluster` 관련 파일 변경이 없음을 확인.

---

## §C. 엣지 케이스

1. **모든 관계가 indirect인 신규 종목**: `keywords`가 채워지지 않은 채로 유지되어야 한다
   (AC-AI091-005). 이는 버그가 아니라 의도된 동작 — direct 관계가 생길 때까지 태깅을
   보류한다.
2. **direct 1개 + indirect 다수 혼합**: direct 관계가 하나라도 있으면 지속 태깅이
   트리거되어야 하며(AC-AI091-004), 텍스트 수집은 direct 텍스트만 사용해야 한다
   (AC-AI091-001) — indirect 텍스트가 혼입되지 않아야 한다.
3. **테마 키워드가 정확히 2개 텍스트에 등장하는 경계값**: AC-AI091-002의 "최소 2개" 임계는
   ≥2를 포함(초과가 아님) — 정확히 2개인 경우 매칭 결과에 포함되어야 한다.
4. **정화 스크립트 재실행(멱등성)**: `--execute`를 두 번 연속 실행해도 세 번째 실행과 동일한
   최종 상태에 수렴해야 한다(`backfill_stock_keywords()`의 기존 멱등 계약 상속,
   §2 [E-9] spec.md).
5. **`max_keywords_per_stock`을 초과하는 매칭 후보**: 재백필 시 AC-AI091-002 임계를 통과한
   키워드가 10개를 초과하면 기존 캡핑 로직(`[:max_keywords_per_stock]`)이 그대로 적용되어야
   한다 — 본 SPEC은 캡 값 자체를 변경하지 않는다.

## §D. 시나리오 (Given-When-Then — AC 보강용, AC 정의 아님)

### 시나리오 1 — 은행주가 로봇 테마로 오탐되지 않는다

- **Given** `105560`(KB금융)이 "로봇" 테마를 언급하는 기사 1건과만 `relevance="indirect"`로
  연결되어 있고, 그 종목 자체를 다루는 direct 기사는 없다.
- **When** `refresh_stock_keywords()`가 실행된다.
- **Then** AC-AI091-005에 의해 이 종목은 지속 태깅 대상에서 제외되고, `keywords`는 갱신되지
  않는다.

### 시나리오 2 — 정화 후 분포가 개선된다

- **Given** 정화 스크립트 실행 전 719개 종목 중 144개(20%)가 `keywords` 10개를 보유한다.
- **When** `scripts/remediate_keyword_tagging.py --execute`가 실행되고 수정된 알고리즘으로
  재백필된다.
- **Then** AC-AI091-009에 의해 10개 보유 종목 비율이 5% 이하로 감소한다.

## §E. Definition of Done

- [ ] AC-AI091-001~011 전부 PASS (Must-Pass 8건 필수, Should-Pass 3건 목표).
- [ ] 전체 백엔드 테스트 스위트 그린(`uv run pytest tests/ --tb=short -q -m "not slow"`).
- [ ] `ruff check .` / `mypy app/` clean(신규 오류 없음, 기존 baseline 별도 표기).
- [ ] 정화 스크립트가 dry-run 기본값으로 동작하며 `--execute` 명시 없이 DB를 변경하지
      않음을 확인.
- [ ] `git diff`에 `theme_cluster`/`ThemeNewsCarryConfig` 관련 변경이 없음을 확인
      (AC-AI091-011).
- [ ] progress.md §E.2/§E.3에 실측 정화 전/후 분포 수치(AC-AI091-009 근거)가 기록됨.
