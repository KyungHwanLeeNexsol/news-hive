---
id: SPEC-AI-091
title: "stocks.keywords 오염 근본원인 수정 — 무경계 substring 매칭 + 자기강화 순환 고리 차단"
version: "0.1.2"
status: completed
created: 2026-07-28
updated: 2026-07-28
author: manager-spec
priority: High
phase: "backend data-integrity hotfix"
module: "backend/app/services"
lifecycle: spec-anchored
tags: "keyword-tagging, data-integrity, news-stock-relation, surge-detection, backend, bugfix"
tier: M
---

# SPEC-AI-091: `stocks.keywords` 오염 근본원인 수정 — 무경계 substring 매칭 + 자기강화 순환 고리 차단 (Root-Cause Fix for `stocks.keywords` Corruption — Unscoped Substring Matching + Self-Reinforcing Feedback Loop)

## HISTORY

- 2026-07-28 (v0.1.0): 최초 작성 (Plan 단계 — 구현 미포함). 완료된 read-only 근본원인 조사
  (2026-07-28, 동일 세션)를 계승하며, 본 SPEC 작성 중 코드 재검증으로 **1건의 중요 갱신**을
  발견했다: `DescriptionRelationMatchingConfig.enabled`(SPEC-AI-085)가 조사 완료 시점 이후
  `True`로 프로덕션 활성화된 상태이며(commit `3a0080c`, 2026-07-28), 같은 날 나중 커밋
  (`12b3521`)이 `ThemeNewsCarryConfig.enabled`만 `False`로 롤백했을 뿐
  `DescriptionRelationMatchingConfig.enabled`는 롤백 대상에 포함되지 않았다(§2 [E-7] 참조).
  즉 조사 지시가 열어둔 "`_resolve_description_relations`가 동일 오염 메커니즘에 독립적으로
  기여하는가?"라는 미해결 질문은 본 SPEC 작성 중 **YES로 확정**되었고(§2 [E-6]/[E-7]), 그
  경로는 현재 프로덕션에서 활성 상태다 — 조사 완료 시점보다 오염 메커니즘이 더 활발해진
  상태에서 본 SPEC이 작성되었다.
- 2026-07-28 (v0.1.1): plan-auditor iteration 1 FAIL(0.86, MP-2) 대응. 감사 보고서
  `.moai/reports/plan-audit/SPEC-AI-091-review-1.md`의 지적사항을 반영.
  - **(D1, critical — MP-2 Must-Pass Firewall)** AC-AI091-009/010(및 그 원천
    REQ-AI091-009/010)이 5대 GEARS/EARS 정규 트리거(Ubiquitous/When/While/Where/
    Unwanted-shall-not) 어디에도 속하지 않는 "After" 트리거를 사용하던 문제를 수정.
    REQ/AC-009는 Event-Driven(**When** 정화 스크립트 실행이 완료되면) 형식으로,
    REQ/AC-010은 Unwanted(**When** ... **shall not** ...) 형식으로 전환했다. 통계
    상한(5%/중앙값≤4) 및 확정 3종목 스팟체크(≤3개) 기준의 기계 검증 가능한 내용은
    그대로 보존했다.
  - **(D3, major)** plan.md가 "Tier M / plan-auditor PASS 임계 0.80"을 명시하나
    spec.md frontmatter에 `tier:` 필드가 없어 프론트매터 전용 도구가 기본값
    Tier L(0.85)로 오판정할 수 있던 간극을 수정 — frontmatter에 `tier: M`을
    추가했다.
  - **(D2, minor)** REQ-AI091-003/004가 함수명·변수명
    (`ai_classifier.py::_count_keyword_matches`, `news_crawler.py`의
    `_touched_stock_ids`)을 REQ 본문에 직접 노출해 본 SPEC 자신의 WHAT-레벨
    컨벤션(§3 서문)과 모순되던 문제를 수정 — 구체 식별자는 이미 plan.md M1/M2에
    정합되어 있으므로 REQ 본문은 행위 수준 서술로 재작성했다.
  - **(D4, minor)** AC-AI091-008/REQ-AI091-008의 "Where" 트리거가 capability-gate가
    아닌 종목별 데이터 상태 조건을 나타내던 taxonomic 오분류를 "While"(State-Driven)로
    정정했다.
- 2026-07-28 (v0.1.2): sync-phase 완료 및 SPEC 종료. run-phase 구현 완료(commit
  `bc360b0`, M1-M3 단일 통합 커밋) + `run_commit_sha` backfill(commit `cfe31d2`).
  plan-auditor iteration 2 PASS(0.92, Tier M 임계 0.80). 전체 백엔드 회귀 스위트
  **2202 passed, 4 skipped, 3 xpassed, 0 failed**(SPEC-AI-090 baseline 대비 회귀 없음).
  AC-AI091-001~011 전량 PASS(Must-Pass 8건 + Should-Pass 3건 — AC-009/010은 테스트
  픽스처 DB 검증 기준). **잔여 위험(의도된 범위 제외)**: 정화 스크립트
  (`scripts/remediate_keyword_tagging.py`)는 M3에서 구현·테스트(합성 데이터 dry-run/
  execute 시연)까지 완료되었으나, 프로덕션 DB `--execute` 실행은 본 SPEC의 자율 실행
  범위 밖이며 CI/CD 배포 확인 이후 사용자가 별도로 요청할 때까지 보류한다(사용자
  명시 결정, AskUserQuestion) — 프로덕션 719개 종목의 기존 오염된 `keywords`는 이번
  sync 시점까지 미정화 상태로 남는다. 이는 SPEC 완료의 차단 사유가 아니다(§4 Out of
  Scope 범위가 알고리즘 수정 + 정화 도구 제공이지, 프로덕션 실행 시점 강제가 아님).

---

## 1. Overview (개요)

### 문제 — 확정된 활성(active) 데이터 오염 버그

급등예측 시스템의 뉴스 기반 탐지기(`theme_news_carry` 등)가 소비하는 `stocks.keywords`
(ARRAY(Text))가 두 가지 결함이 결합된 자기강화 순환 고리로 인해 지속적으로 오염되고 있다.
이는 일회성 버그가 아니라 **현재도 매일 실행 중인** 스케줄 잡(`keyword_backfill`, 24시간
주기)과 크롤 훅(`refresh_stock_keywords`, 크롤 배치마다)이 매일 오염을 더 심화시키는 활성
결함이다.

### 결함 1 — 무경계(unscoped) substring 매칭

`keyword_tagging_service.py::extract_theme_keywords()`(§2 [E-1])는 10개 테마 어휘
(배터리/AI/바이오/항공/게임/반도체/조선/5G/전기차/로봇, `ThemeClusterConfig.keywords`)를
**최대 50개 연결 기사의 제목+본문을 하나로 이어붙인 블록**(`_gather_stock_theme_texts`,
§2 [E-2])에 대해 순수 Python `kw in combined` substring 포함 검사(§2 [E-3])로 매칭한다.
`_gather_stock_theme_texts`는 종목에 연결된 `NewsStockRelation`을 **relevance/match_type
구분 없이 전량 조회**한다(§2 [E-2]) — "direct"(종목이 실제 주제)든 "indirect"(같은
섹터/키워드를 공유할 뿐인 약한 신호)든 구분하지 않는다.

### 결함 2 — 확정된 활성 자기강화 순환 고리 (3개 관계 생성 경로가 동일 메커니즘으로 수렴)

1. `news_crawler.py::_build_search_queries()`(§2 [E-4])는 이미 `keywords`가 채워진 종목의
   각 키워드를 검색 쿼리로 재사용한다.
2. `ai_classifier.py::KeywordIndex.build()`(§2 [E-5])는 `stock.keywords`를 인덱싱해
   `keyword_lower -> [(stock_id, sector_id), ...]` 역인덱스를 만든다 — **같은 키워드를 가진
   모든 종목**이 대상이 된다(원 종목 한정 아님).
3. 이 역인덱스는 **3개의 독립된 호출부**에서 `relevance="indirect"` `NewsStockRelation`을
   생성하는 데 쓰인다: (a) `_resolve_query_relations()`(§2 [E-4], 검색 쿼리 매칭),
   (b) `classify_news()`(§2 [E-5], 기사 제목 매칭), (c) `_resolve_description_relations()`
   (§2 [E-6]/[E-7], 기사 설명 매칭 — SPEC-AI-085, **현재 프로덕션 활성**).
4. `news_crawler.py`의 뉴스 저장 훅(§2 [E-8])은 이번 배치에서 생성된 **모든**
   `NewsStockRelation`의 `stock_id`를 relevance 구분 없이 `_touched_stock_ids`에 모아
   `refresh_stock_keywords()`를 호출한다.
5. `refresh_stock_keywords()`(§2 [E-9])는 (결함 1과 동일한 무경계 substring 로직으로) 기존
   키워드에 **병합**(삭제 없음)하고 `max_keywords_per_stock`(10)으로 캡핑한다.

3개 경로 중 어느 하나로든 "indirect" 관계가 생기면 5번 단계가 트리거되어 무경계 매칭이
재실행되고, 그 결과가 다시 1번 단계의 검색 쿼리 우선순위를 강화한다 — 완전한 자기강화
순환이다.

### 확정된 프로덕션 영향 (2026-07-28 직접 DB 조회, 재조사 없이 인용)

- 719/2605 종목에 `keywords`가 채워져 있고, 그중 144개(20%)가 정확히 10개(상한)를 보유 —
  분포가 상단에 편중(9개 28건, 8개 22건, 7개 30건, 6개 31건, 5개 36건).
- 확정 오탐 예시: `023790`(동일스틸럭스, 철강사) — 10개 테마 전부 태깅. `105560`(KB금융,
  은행) — 로봇/전기차/배터리/조선/원전 포함 10개. `192080`(더블유게임즈, 게임사) —
  반도체/배터리/전기차/로봇/조선/원전/바이오 포함 10개.
- 2026-07-28, `theme_news_carry` 기반 `surge_candidate` 시그널 69건 중 53건(77%)이
  공유 키워드 바스켓으로 무관 종목이 묶인 결과로 추정.

### 현재 위험 상태 (재확인, 조사 이후 변동 없음)

- `ThemeNewsCarryConfig.enabled = False`(commit `12b3521`, 2026-07-28 당일 롤백) — 오염된
  `stocks.keywords`의 하류 소비자가 현재 없다(`theme_cluster`는 `stocks.keywords`를 전혀
  참조하지 않으며 독립적으로 뉴스에서 테마를 재도출한다 — §2 [E-10]).
- `surge_trades` 테이블은 비어 있다(이전 세션 확인, 실매매 없음) — **금융 리스크는 0**.
- 그러나 `keyword_backfill` 스케줄 잡(24시간 주기, §2 [E-11])과 크롤 훅(크롤 배치마다,
  §2 [E-8])은 **계속 실행 중**이며 오염 데이터셋은 매일 더 커진다.

---

## 2. Code Evidence (코드 근거, 2026-07-28 재검증 완료)

- **[E-1] 무경계 substring 매칭.**
  `keyword_tagging_service.py::extract_theme_keywords()`(88-107행)는 `combined = " ".join(texts)`
  (102행) 후 `if kw and kw in combined and kw not in matched`(105행)로 매칭한다 — 단어 경계
  가드 없음, 텍스트 출처 구분 없음.
- **[E-2] relevance 구분 없는 텍스트 수집.**
  `_gather_stock_theme_texts()`(62-85행)는 `NewsStockRelation.stock_id == stock_id` 조인만
  필터로 쓰고(69-70행) `relevance`/`match_type` 필터가 없다 — 최대 50개 기사(`_MAX_ARTICLES_PER_STOCK`)
  제목+본문 전량을 blob에 포함.
- **[E-3] `refresh_stock_keywords()`의 병합·캡 로직.**
  163-216행. 기존 키워드 + 신규 매칭 키워드를 병합(`existing + [kw for kw in matched if kw
  not in existing]`, 202행) 후 `max_keywords_per_stock`(기본 10)로 캡(203행) — 삭제 없음,
  무한 증식만 상한으로 제한.
- **[E-4] `_build_search_queries()`의 키워드 재사용 + `_resolve_query_relations()`의 indirect
  전파.**
  `news_crawler.py:217-248`. 230-234행에서 `keywords`가 채워진 종목마다 `stock.keywords`의
  각 키워드를 검색 쿼리 집합에 추가한다. `_resolve_query_relations()`(251-303행)는 매칭된
  쿼리가 `index.stock_keywords`에 있으면(273-282행) **같은 키워드를 가진 모든 종목**에
  `relevance="indirect"` 관계를 생성한다.
- **[E-5] `KeywordIndex.build()`의 역인덱스 + `classify_news()`의 제목 indirect 매칭.**
  `ai_classifier.py:34-54`(build), `332-395`(classify_news). `build()`는 46-47행에서
  `stock.keywords`의 각 키워드를 `keyword_lower -> [(stock_id, sector_id), ...]`로 인덱싱한다.
  `classify_news()`는 366-376행에서 제목에 해당 키워드가 포함되면 인덱스에 매핑된 **모든**
  (stock_id, sector_id)에 `relevance="indirect"` 관계를 생성한다.
- **[E-6] `_resolve_description_relations()`도 동일 indirect 매칭 메커니즘을 공유한다 —
  미해결 질문 확정.**
  `news_crawler.py:306-342`(SPEC-AI-085). 333행에서 `classify_news(description, index)`를
  그대로 재호출한다 — [E-5]의 동일한 `index.stock_keywords` 기반 indirect 매칭 로직이 기사
  **설명(description)** 텍스트에도 적용된다. 즉 이 함수는 결함 2의 순환 고리에 대해 **제3의
  독립 진입점**이다 — 작업 지시가 남긴 미해결 질문("`_resolve_description_relations`가 동일
  오염에 기여하는가?")은 코드로 **YES**로 확정된다.
- **[E-7] `DescriptionRelationMatchingConfig.enabled`는 현재 `True`(프로덕션 활성) — 조사
  완료 시점 이후 갱신된 사실.**
  `surge_settings.py:756-771`. `enabled: bool = True`(767행, 주석: "2026-07-28 프로덕션
  활성화"). `git log`로 확인: commit `3a0080c`(2026-07-28)가 SPEC-AI-084/085를 함께
  활성화했고, 같은 날 나중 커밋 `12b3521`은 `ThemeNewsCarryConfig.enabled`만 `True → False`로
  롤백했다(diff 확인: `# @MX:SPEC: SPEC-AI-084 REQ-AI084-015` 주석이 붙은 필드만 변경) —
  `DescriptionRelationMatchingConfig.enabled`는 롤백 대상이 아니었다. 따라서 결함 2의 순환
  고리는 조사 완료 시점보다 **현재 더 활성**이다(관계 생성 경로가 3개로 늘어난 채 운영 중).
- **[E-8] 뉴스 저장 훅의 relevance 무관 트리거.**
  `news_crawler.py:876-884`. `_touched_stock_ids`(806-827행에서 채워짐, 최소 점수 필터만
  적용 — direct 10점/propagated 25점, relevance 자체는 필터링하지 않음)가 비어있지 않으면
  예외 격리 하에 `refresh_stock_keywords(db, list(_touched_stock_ids))`를 호출한다.
- **[E-9] `refresh_stock_keywords()`는 결함 1과 동일 무경계 로직을 재사용한다.**
  `keyword_tagging_service.py:163-216`. 193행 `_gather_stock_theme_texts(db, stock_id)`,
  197행 `extract_theme_keywords(texts, vocab)` — [E-1]/[E-2]와 동일 함수 재사용.
- **[E-10] `theme_cluster`는 `stocks.keywords`를 소비하지 않는다(무영향 확인).**
  이전 세션 전체 함수 본문 읽기로 확인 — `theme_cluster`(다른/구 테마 탐지기)는
  `Stock.sector_id` 기반으로 매 실행마다 뉴스에서 독립적으로 테마를 재도출한다. 본 SPEC의
  범위 밖.
- **[E-11] `keyword_backfill` 스케줄 잡은 현재도 24시간 주기로 실행 중.**
  `scheduler.py:475-500`(`_run_keyword_backfill`), `2138-2145`(`scheduler.add_job(...,
  interval, hours=24, id="keyword_backfill", replace_existing=True)`).
- **[E-12] `routers/stocks.py`에 `keywords` 수동 갱신(PUT/PATCH) 엔드포인트가 없다.**
  `POST /sectors/{sector_id}/stocks`(87-98행, `StockCreate.keywords`)에서 **생성 시점에만**
  설정 가능 — 별도 갱신 API 부재. `stocks.keywords`의 비어있지 않은 값 대부분은 자동 태깅
  (`backfill_stock_keywords`/`refresh_stock_keywords`) 기원일 가능성이 높으나, 생성 시점
  수동 설정 가능성을 완전히 배제할 수는 없다(§5 잔여 위험 참조 — provenance 컬럼 부재).

---

## 3. Requirements (GEARS)

> 표기: WHAT/관찰가능 행위 수준으로 기술한다. 구체 구현(함수 시그니처, 임계값)은 plan.md에서
> 확정한다. 각 REQ는 acceptance.md의 AC-AI091-0NN에 매핑된다.

### 핵심 — 매칭 알고리즘 근본원인 수정

#### REQ-AI091-001 (State-Driven, P0) [HARD] — direct-relevance 전용 텍스트 스코핑

**While** 종목의 테마 키워드 추출을 위한 소스 텍스트를 수집하는 동안, the keyword tagging
service **shall** `NewsStockRelation.relevance`가 `"direct"`인 행만 포함하고 `"indirect"`
행은 제외해야 한다 — 관계 생성 시점에 이미 확립된 direct/indirect 신뢰도 구분(§2 [E-4],
direct 10점/propagated 25점 최소 점수 필터)을 텍스트 수집 단계에도 일관되게 적용한다.

#### REQ-AI091-002 (Ubiquitous, P0) [HARD] — 다중 텍스트 출현 임계

The keyword extraction function **shall** 하나의 연결된 blob이 아니라 개별 소스 텍스트
목록을 대상으로, 테마 키워드가 최소 2개의 **서로 다른** 소스 텍스트에 출현할 때만 그
키워드를 매칭 결과에 포함해야 한다 — 단일 시황/묶음 기사가 우연히 언급한 무관 테마 단어가
연결 종목 전체에 전파되는 것을 방지한다.

#### REQ-AI091-003 (Ubiquitous, P1) — 한글 선행문자 경계 가드

The keyword extraction function **shall** 매칭 위치 직전 문자가 한글 음절이면 해당 매칭을
거부해야 한다 — 기존 코드베이스에 이미 확립된 경계 가드 패턴을 재사용해야 하며 신규 로직을
발명해서는 안 된다(Enforce Simplicity; 재사용 대상의 구체 위치는 plan.md M2에서 확정).

### 핵심 — 자기강화 순환 고리 차단 (단일 개입점)

#### REQ-AI091-004 (Ubiquitous, P0) [HARD] — 지속 태깅 트리거의 단일 relevance 게이트

The persistent-tagging trigger's touched-stock set **shall** `relevance`가 `"direct"`인
`NewsStockRelation` 행에서 비롯된 `stock_id`만 포함해야 한다 — 이 게이트는 관계를 생성한
경로(검색 쿼리 매칭, 기사 제목 매칭, 기사 설명 매칭 중 어느 것이든)와 무관하게 **단일
개입점**에서 적용되어, 각 경로에 개별 수정을 가하는 대신 순환 고리를 한 곳에서 차단한다
(Enforce Simplicity — 단일 개입점 vs 다중 패치; 개입점의 구체 위치와 관계 생성 경로별
함수명은 plan.md M1에서 확정).

#### REQ-AI091-005 (Unwanted, P0) [HARD] — indirect 전용 관계로는 지속 태깅 금지

The system **shall not** 어떤 종목이 해당 크롤 배치에서 오직 `relevance="indirect"`
관계로만 포함된 경우 그 종목에 대해 `refresh_stock_keywords()`를 호출해서는 안 된다.

#### REQ-AI091-006 (Event-Driven, P1) — 설명 기반 관계 경로의 동등 적용 확인 (미해결 질문 해소)

**When** `_resolve_description_relations()`(SPEC-AI-085, 현재 프로덕션 활성 — §2 [E-6]/[E-7])가
`relevance="indirect"` 관계를 생성하면, REQ-AI091-004의 게이트가 다른 두 경로(쿼리/제목
매칭)에서 생성된 관계와 **동일하게** 적용되어야 한다 — 이로써 조사 지시가 남긴 미해결
질문("설명 기반 경로가 동일 오염에 독립적으로 기여하는가")을 코드 수준에서 닫는다.

### 기존 데이터 정화(remediation)

#### REQ-AI091-007 (Ubiquitous, P0) — 리셋 후 재백필 정화

A one-time remediation script **shall** 자동 태깅 서비스(`backfill_stock_keywords`/
`refresh_stock_keywords`)로 채워진 것으로 판단되는 종목의 `stocks.keywords`를 `NULL`로
리셋한 뒤, REQ-AI091-001~003이 반영된 수정 알고리즘으로 `backfill_stock_keywords()`를
재실행해 정화된 상태로 재채움해야 한다.

#### REQ-AI091-008 (State-Driven, P2) — provenance 불명 종목의 기본 처리

**While** 어떤 종목의 기존 `keywords`가 자동 태깅 기원인지 수동 설정 기원인지 확인할 수
없는 상태인 동안(§2 [E-12] — `stocks` 테이블에 provenance 컬럼이 없어 구조적으로 구분
불가), the remediation script **shall** 기본적으로 그 종목을 리셋 대상에 포함하되, 그러한
불명확 종목의 개수를 유계 로그로 남기고, 실제 리셋 실행 전에 운영자에게 진단 카운트를
명시적으로 보고해야 한다.

### 검증·관측성

#### REQ-AI091-009 (Event-Driven, P1) — 정화 후 키워드 개수 분포 상한

**When** 정화 스크립트(REQ-AI091-007)의 실행이 완료되면, the tagged-stock keyword-length
distribution **shall** 태깅된 종목 전체에 대해 acceptance.md에 정의된 비-편중
(non-top-heavy) 수치 상한을 만족해야 한다 — 기계 검증 가능한 쿼리/테스트로 확인한다.

#### REQ-AI091-010 (Unwanted, P1) — 확정 오탐 종목 스팟체크

**When** 정화 스크립트(REQ-AI091-007)의 실행이 완료되면, 확정된 3개 오탐 예시 종목
(`023790`, `105560`, `192080`)의 `stocks.keywords`는 **shall not** 각각 3개를 초과하는
테마 키워드를 보유해서는 안 된다 — 스팟체크 테스트/쿼리로 확인한다.

#### REQ-AI091-011 (Unwanted, P0) [HARD] — 무관 시스템 회귀 금지

The system **shall not** `theme_news_carry`/`theme_cluster` 관련 기존 테스트 스위트를
회귀시키거나, `ThemeNewsCarryConfig`/`theme_cluster`의 동작을 본 SPEC의 일부로 변경해서는
안 된다.

---

## 4. Out of Scope (범위 제외) [HARD]

본 SPEC은 다음 항목을 명시적으로 **out of scope**로 지정한다. 각 하위 항목은 별도의 후속
SPEC 또는 사용자 결정 대상이다.

### Out of Scope — ThemeNewsCarryConfig 재활성화

- 본 SPEC은 `ThemeNewsCarryConfig.enabled`를 `True`로 되돌리지 않는다. 재활성화는 본 SPEC의
  수정 + 정화 완료 + 신규 데이터 품질 재측정을 전제로 한 **별도의 향후 결정**이며, 본 SPEC의
  완료 기준에 포함되지 않는다.

### Out of Scope — theme_cluster / detect_theme_news_cluster

- `theme_cluster`(구/별도 테마 탐지기)는 `stocks.keywords`를 전혀 참조하지 않고 매 실행마다
  뉴스에서 독립적으로 테마를 재도출한다(§2 [E-10], 전체 함수 본문 확인 완료). 본 SPEC은 이
  탐지기의 로직을 건드리지 않는다.

### Out of Scope — 일반 뉴스 크롤 예산/API 쿼터 재설계

- `_build_search_queries()`의 쿼리 예산(`MAX_TOTAL_QUERIES`/`MAX_STOCK_QUERIES`), 크롤
  빈도, 외부 API 쿼터, 신규 소스 추가는 범위 밖이다. 본 SPEC은 키워드 추출 알고리즘과
  지속 태깅 트리거 게이트에만 집중한다(Enforce Simplicity).

### Out of Scope — 스케줄 잡/크롤 훅의 임시 비활성화

- 사용자가 명시적으로 확인함: 본 SPEC 계획 단계 동안 `keyword_backfill` 스케줄 잡과
  `refresh_stock_keywords` 크롤 훅의 진입점 자체를 비활성화하는 것을 임시 조치로 제안하지
  않는다 — 수정 자체가 산출물이다. (단, REQ-AI091-004/005는 그 훅의 **내부 게이팅 로직**을
  변경하는 것이며, 훅의 존재나 스케줄을 비활성화하는 것이 아니다 — 두 개념은 구분된다.)

### Out of Scope — `stocks.keywords` provenance 컬럼 신설

- 자동 태깅 기원과 수동 설정 기원을 구조적으로 구분하는 신규 컬럼/스키마 마이그레이션은
  범위 밖이다(§2 [E-12] 잔여 위험을 REQ-AI091-008의 보수적 기본 처리로 완화할 뿐, 근본
  해결은 후속 SPEC 후보).

### Out of Scope — following 시스템 / `StockKeyword` / `StockFollowing`

- following 시스템의 사용자 키워드 테이블은 본 SPEC의 어떤 변경도 참조·수정하지 않는다
  (SPEC-AI-084 원 설계 계승, `keyword_tagging_service.py` 모듈 docstring 16-17행).

---

## 5. 잔여 위험 (Residual Risk, 참고용 — 상세는 acceptance.md)

- REQ-AI091-008의 provenance 불명 종목 기본 리셋 처리는 극소수의 생성 시점 수동 설정
  키워드를 오삭제할 가능성을 완전히 배제하지 못한다(§2 [E-12]). 완화: 리셋 실행 전 진단
  카운트 보고 + 운영자 확인 단계.
- REQ-AI091-002의 "최소 2개 서로 다른 텍스트" 임계값은 plan-phase 제안이며 실측 캘리브레이션
  대상이다(724개 종목 재백필 결과 관찰 후 조정 가능).
