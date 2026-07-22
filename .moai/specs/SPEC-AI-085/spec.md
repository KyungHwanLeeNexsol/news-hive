---
id: SPEC-AI-085
version: 0.1.0
status: in-progress
created: 2026-07-22
created_at: "2026-07-22"
updated: 2026-07-22
author: Nexsol
priority: High
issue_number: null
lifecycle_level: 1
tier: M
labels: [news-crawling, news-stock-relation, content-matching, keyword-tagging, coverage, chicken-and-egg, backend, surge-detection]
---

# SPEC-AI-085: 기사 설명(description) 기반 종목 관계 생성으로 무-관계 순환 고리 차단 (Description-Based NewsStockRelation Creation to Break the Zero-Coverage Chicken-and-Egg Cycle)

## HISTORY

- 2026-07-22 (v0.1.0): 최초 작성 (Plan 단계 — 구현 미포함). SPEC-AI-084(뉴스 기반 산업 테마
  전파, commit `6f5fd66`)의 기능 플래그 활성화 전 검증 중 발견된 **직접 구조적 후속**이다.
  SPEC-AI-084의 `backfill_stock_keywords()`를 라이브 DB에 실행한 뒤 2026-07-22 삼성 로봇
  전담조직 발표발 로봇 테마 랠리로 실제 급등한 14종목과 대조한 결과, "로봇" 키워드 바스켓에
  올바르게 태깅된 것은 8/14뿐이었다. 미탐 6종(아이로보틱스/066430, 코닉오토메이션/391710,
  씨메스/475400, 한라캐스트/125490, 앤로보틱스/138360, 로보스타/090360)을 `news_stock_relations`
  직접 조회로 진단하니 6종 모두 관계 행이 0개 또는 1개였다 — 같은 날 `news_articles`에 이들
  종목에 대한 실제 관련 기사가 이미 존재했음에도(예: "로보스타 주가 불기둥" DB 확인)였다.
  SPEC-AI-084의 키워드 추출(`_gather_stock_theme_texts`)이 `NewsStockRelation` 조인으로 텍스트를
  읽으므로, 관계가 없는 종목은 키워드도 못 얻어 검색 우선순위 승격도 못 받는 **자기강화 순환
  고리**가 근본원인으로 지목되었다.
  - **코드 근거 확정(read-only, 2026-07-22)**: 세 근본 사실 모두 실제 코드로 검증(§2 [E-1]~[E-6]).
  - **[중대 정정 — 작업 지시 2차 정보 오류] (§2 [E-2] 참조)**: 작업 지시가 단언한 "관계는
    오직 타깃 검색 쿼리(`_resolve_query_relations`)로만 생성되며 기사 본문/제목을 검사하지
    않는다"는 코드로 반증되었다. `crawl_all_news`는 **모든** 기사에 대해
    `classify_news(ad["title"], index)`(`news_crawler.py:542`)를 호출해 **제목** 기반 관계를 이미
    생성한다(`_query=None` RSS/애그리게이터 기사 포함). 따라서 진짜 결손은 작업 지시가 서술한
    "쿼리 전용"이 아니라 그보다 좁은 **"제목 너머 텍스트(기사 설명) 미검사"**이다.
  - **범위 명시(사용자 확인)**: 본 SPEC은 "전체 시스템의 모든 뉴스 커버리지 개선"이 **아니라**
    RELATION 생성의 특정 순환 고리를 차단하는 데 국한한다. 일반 뉴스 크롤 예산/API 쿼터 재설계는
    범위 밖이다(§4 [X-1]).

---

## 1. Overview (개요)

### 문제 — 무-관계 종목의 자기강화 순환 고리

급등예측 시스템의 뉴스 기반 탐지기(예: `immediate_disclosure`, `volume_news_combo`,
SPEC-AI-084의 `theme_news_carry`)는 종목↔뉴스 연결을 `NewsStockRelation` 조인으로 소비한다.
`NewsArticle`에는 `stock_code` 컬럼이 없으므로, 어떤 종목이 뉴스와 "연결"되었다고 인정되려면
반드시 `news_stock_relations` 행이 존재해야 한다.

2026-07-22 라이브 감사에서, 로봇 테마 랠리로 실제 급등한 6종목이 관련 기사가 DB에 이미
존재함에도 관계 행이 0~1개에 그쳤다. 관계가 없으면 SPEC-AI-084의 키워드 태깅
(`_gather_stock_theme_texts`가 `NewsStockRelation` 조인으로 텍스트를 읽음)도 그 종목에는
키워드를 못 채우고, 키워드가 없으면 뉴스 크롤 검색 우선순위(`_build_search_queries`)의 상위
계층으로 승격되지 못하며, 승격되지 못하면 타깃 검색 대상에서 계속 밀려나 관계를 얻을 다음
기회가 또 사라진다. 이것이 **관계 없음 → 키워드 없음 → 우선순위 승격 없음 → 타깃 검색 없음 →
관계 없음**의 자기강화 순환 고리다.

### 근본원인 (모두 2026-07-22 코드/DB 검증)

1. **제목 매칭은 이미 존재하나 제목 너머 텍스트는 검사되지 않는다.** `crawl_all_news`의 관계
   계산 지점(`news_crawler.py:531-543`)은 모든 기사에 대해 `classify_news(ad["title"], index)`
   (제목만)을 호출한다. 기사 **설명(description)**·**본문(content)**은 종목명 매칭에 전혀
   사용되지 않는다. 따라서 종목명이 제목에는 없고 설명/본문에만 등장하는 기사(테마 로테이션
   묶음 기사가 전형)는 그 종목에 대한 관계를 만들지 못한다.
2. **타깃 검색 우선순위가 키워드에 의존한다.** `_build_search_queries`(`news_crawler.py:217`)는
   (a) 섹터명 전부 → (b) `stocks.keywords`가 이미 채워진 종목의 이름·키워드 → (c) 나머지 종목의
   유계 라운드로빈 표본 순으로 쿼리를 배분한다. SPEC-AI-084 백필 전에는 `stocks.keywords`가 전
   종목 NULL이었으므로 사실상 모든 소형주 타깃 커버리지가 약한 (c) 라운드로빈에 의존했다.
3. **결손이 순환한다.** (1) 때문에 관계가 안 생기면 (SPEC-AI-084) 키워드가 안 채워지고,
   키워드가 없으면 (2)의 (c)에 갇혀 타깃 검색을 못 받으며, 이는 다시 (1)의 관계 결손으로
   돌아온다.

### [중대 정정] 작업 지시 2차 정보 대비 실측 차이

작업 지시는 "관계는 오직 `_query`(타깃 검색 쿼리)로만 생성되고 기사 자체 텍스트는 검사되지
않는다"고 서술했으나, 코드 검증 결과 이는 **부정확**하다. `classify_news(ad["title"], index)`
(`news_crawler.py:542`)가 모든 기사의 **제목**을 종목명·키워드·섹터에 매칭해 관계를 이미
만든다(§2 [E-2]). `calculate_relevance_score`(`ai_classifier.py:268`)는 제목에 종목명 포함 시
+40을 부여하고(naver 신뢰도 0.75 곱 ≈ 30) 최소 점수 필터(10)를 여유 있게 통과한다. 즉 제목에
종목명이 있으면 관계가 생성·영속화된다. 진짜 결손은 "쿼리 전용"이 아니라 **"제목 너머 텍스트
(설명) 미검사"**이며, 본 SPEC은 그 좁혀진 결손을 정확히 겨냥한다.

### 접근 (최소 변경 — 설명 기반 관계 생성)

관계 계산 시점(`news_crawler.py:531-543`)에서 **이미 메모리에 있는** 기사 설명
(`ad.get("description")`)을 종목명 매칭 대상으로 추가한다. 기존 `classify_news`/`KeywordIndex`
매칭 의미(최장일치 + 한글 선행문자 배제 가드)와 기존 `calculate_relevance_score`(설명에 종목명
포함 시 +20 이미 존재) + 기존 최소 점수 필터를 재사용한다. 이는:

- **비용 0**: 설명은 크롤 시점에 이미 수집되어 메모리에 있다(추가 네트워크·스크래핑 없음).
- **순서 정합**: 설명은 무-관계 기사가 폐기되는 필터(`:554-558`) 이전에 사용 가능하다(본문은
  스크래핑이 그 필터 이후라 부적합, §2 [E-4] 참조).
- **엄격히 additive**: 기존 제목/쿼리 관계 생성은 불변.
- **stocks.keywords 비의존**: 종목 **이름**으로 매칭하므로 키워드 선채움 없이도 동작 → 순환
  고리를 구조적으로 차단.

새로 생성된 설명 기반 관계는 기존 삽입 경로를 그대로 타고 `_touched_stock_ids`(`:747`) →
`refresh_stock_keywords` 훅(`:812`)으로 흘러 키워드를 채우고, 이는 다음 크롤에서 (2)의 (b)
계층으로의 승격을 유발한다 — 순환 고리 차단이 기존 배선으로 자동 완성된다.

### 목표

종목명이 기사 **제목에는 없지만 설명에는 등장**하는 경우에도 `NewsStockRelation`이 생성되게
하여, 관계 없음 → 키워드 없음 → 승격 없음 → 관계 없음의 순환 고리를, `stocks.keywords`에
의존하지 않고 구조적으로 차단한다. 기존 제목/쿼리 관계 경로·탐지기·앙상블·매매 로직은 불변으로
유지하고 예측 기록 모드(SPEC-AI-043)를 계승한다.

---

## 2. Environment & Assumptions (환경 및 가정)

- Backend: Python 3.12+, FastAPI, SQLAlchemy 2.0, PostgreSQL 16(프로덕션)/SQLite(테스트).
  개발 방법론: DDD(ANALYZE-PRESERVE-IMPROVE, `.moai/config/sections/quality.yaml`). 검증 명령:
  `cd backend && uv run pytest tests/ --tb=short -q -m "not slow"` (CLAUDE.local.md).
- 운영 모드: **예측 기록 모드**(SPEC-AI-043) — 실매수/포트폴리오 실행 비활성. 본 SPEC의 모든
  변경은 뉴스 관계 데이터 생성만 확장하며 매매를 트리거하지 않는다.

### 코드 검증 완료 (2026-07-22, read-only)

- **[E-1] 관계는 두 경로로 생성된다(쿼리 + 제목).** `crawl_all_news`의 관계 계산 루프
  (`news_crawler.py:531-543`)는 기사마다 (a) `ad.get("_query")`가 있으면
  `_resolve_query_relations(query, index, sectors)`(`:534-535`, 검색 **쿼리 문자열**을 index에
  매칭), (b) `_us_sector_id`가 있으면 섹터 관계(`:536-541`), 그리고 (c) **모든 기사에 대해**
  `classify_news(ad["title"], index)`(`:542`, 기사 **제목**을 index에 매칭)를 합쳐
  `ad["_relations"]`를 만든다.
- **[E-2] 제목 매칭이 이미 존재한다(작업 지시 정정).** `classify_news`(`ai_classifier.py:332`)는
  제목을 `index.stock_names`(최장일치 + 한글 선행문자 배제 가드, `:344-363`),
  `index.stock_keywords`(`:366-376`), `index.sector_keywords`(`:378-393`)에 매칭한다.
  `calculate_relevance_score`(`ai_classifier.py:268`)는 제목에 종목명 포함 시 +40(`:296-297`),
  설명에 종목명 포함 시 +20(`:300-301`)을 부여하고 소스 신뢰도(naver 0.75)를 곱한다 → 제목
  종목명 매칭은 ≈30점으로 최소 필터 10(`news_crawler.py:619`/`:741`)을 통과한다. **따라서
  RSS/애그리게이터(`_query=None`) 기사라도 제목에 종목명이 있으면 관계가 생성·영속화된다** —
  작업 지시의 "관계는 쿼리 전용" 서술은 부정확하다.
- **[E-3] 그러나 설명(description)·본문(content)은 종목명 매칭에 사용되지 않는다.** `classify_news`
  는 **제목만** 읽고, `_resolve_query_relations`는 **쿼리 문자열만** 읽는다. `calculate_relevance_score`
  의 설명 +20(`:300-301`)은 **이미 존재하는** 관계의 점수를 올릴 뿐, 설명에서 관계를 **생성**하지
  않는다(관계 생성 함수가 설명을 안 봄). 따라서 종목명이 제목에는 없고 **설명에만** 등장하는
  기사는 그 종목에 대한 관계를 만들지 못한다 — 이것이 실제 결손이다.
- **[E-4] 본문(content)은 무-관계 필터 이후에야 확보된다.** 관계 계산(`:531-543`) → AI 분류
  (`:545-552`) → **무-관계 기사 폐기 필터**(`:554-558`, `unique_articles = [a for a in
  unique_articles if a.get("_relations")]`) → 스크래핑(`:570-573`, `ad["_content"]` 할당) 순서다.
  즉 스크래핑된 본문은 무-관계 기사가 이미 폐기된 뒤에야 생기므로, 본문 기반 매칭은 폐기 이전
  단계에서 쓸 수 없다(스크래핑을 필터 앞으로 옮기면 정크 기사 전량 스크래핑 = 비용 폭발).
  반면 **설명은 관계 계산 시점(`:531`)에 이미 메모리에 있다** → 설명 기반 매칭이 올바른 순서.
- **[E-5] 검색 우선순위 3계층 + 키워드 의존.** `_build_search_queries`(`news_crawler.py:217`):
  (a) 재고 있는 섹터명 전부(`:225-228`), (b) `stocks.keywords`가 채워진 종목의 이름 + 각 키워드
  (`:230-236`), (c) 나머지 종목의 라운드로빈 표본(`_stock_rr_index` 커서, `MAX_STOCK_QUERIES`
   상한, `:238-246`). 어떤 종목이 (b)로 승격되려면 `stocks.keywords`가 채워져야 하고, 이는
  SPEC-AI-084 키워드 태깅에 의존하며, 그 태깅은 다시 `NewsStockRelation` 존재에 의존한다.
- **[E-6] 신규 관계는 기존 배선으로 키워드 태깅까지 자동 연결.** 관계 삽입 루프
  (`news_crawler.py:690-761`)는 삽입된 관계의 `stock_id`를 `_touched_stock_ids`(`:747`)에 모으고,
  크롤 종료 시 `refresh_stock_keywords(db, list(_touched_stock_ids))`(`:812-818`, SPEC-AI-084)를
  호출해 그 종목들의 `stocks.keywords`를 채운다. → 설명 기반 관계를 `ad["_relations"]`에 병합하면
  이 배선을 그대로 타고 키워드 승격이 자동 이어진다(별도 요구사항 불필요).

### 가정

- **[A-1]** 설명 기반 매칭은 종목 **이름**(`KeywordIndex.stock_names`)으로 이뤄지므로
  `stocks.keywords` 선채움에 의존하지 않는다 → 순환 고리를 구조적으로 차단한다(관계가 없어도
  이름 매칭만으로 첫 관계를 만들 수 있음).
- **[A-2]** 테마 로테이션 묶음 기사는 넓은 피드(RSS/naver/섹터 검색)로 이미 수집되며, 그 설명
  스니펫이 제목에는 없는 멤버 종목을 나열하는 경향이 있다. 설명 기반 매칭은 이미 수집된 그런
  기사를 멤버 종목의 관계로 전환한다.
- **[A-3]** 설명 스니펫은 본문보다 짧다. 따라서 설명 기반 매칭이 SPEC-AI-084의 특정 6종 미탐을
  **모두** 회수하는지는 그 기사들의 설명 풍부도에 달렸으며 이는 배포 후 관측 대상이다(플랜
  단계 보증 아님). 본 SPEC은 "설명에 종목명이 등장하면 관계가 생긴다"는 구조적 결손 해소를
  보증하며, 특정 6종 전수 회수는 관측 지표로 다룬다.
- **[A-4]** 설명 매칭 확장은 오탐(무관 종목 관계 남발) 위험을 동반한다 — 시장 시황/묶음 기사
  설명이 다수 종목을 언급할 수 있다. 따라서 이름 경계 가드 + 기사당 관계 상한 + 기존 점수
  필터를 인수 기준으로 고정한다(REQ-AI085-003/004).
- **[A-5]** 예측 기록 모드가 유지되므로 어떤 경로도 실매수를 트리거하지 않는다 — 자금 리스크 0,
  리스크는 관계 precision·데이터 품질에 국한.

---

## 3. Requirements (EARS)

> 표기: WHAT/관찰가능 행위 수준으로 기술하고, 구체적 함수·설정키·임계값·삽입 지점은
> plan.md/Run 단계에서 확정한다. 각 요구사항은 acceptance.md의 AC-085-0NN에 매핑된다.

### 핵심 — 설명 기반 관계 생성

#### REQ-AI085-001 (Event-Driven, P0) — 설명 기반 종목 관계 생성

**WHEN** 수집된 기사의 설명(description) 텍스트가 추적 종목(`stocks`)의 이름을 포함하면,
the system **SHALL** 그 기사의 제목이나 타깃 검색 쿼리가 해당 종목을 명명하지 않더라도 그
종목에 대한 `NewsStockRelation`을 생성해야 한다.

- 근거([E-1]/[E-3]): 현재 관계는 제목(`classify_news`)·쿼리(`_resolve_query_relations`)로만
  생성되고 설명은 관계를 **생성**하지 않는다. 본 REQ는 기존 `KeywordIndex` 종목명 매칭을
  설명 텍스트에도 적용해 그 결손을 닫는다. 구체 매칭 함수·삽입 지점은 plan.md에서 확정.

#### REQ-AI085-002 (Ubiquitous, P0) — 종목명 기반(키워드 비의존) 순환 차단

the system **SHALL** 설명 기반 관계를 `stocks.keywords`가 아닌 종목 **이름**
(`KeywordIndex.stock_names`)으로 도출해, 키워드 선채움 없이도 관계가 생성되도록 함으로써
무-관계 종목의 순환 고리(관계 없음 → 키워드 없음 → 승격 없음 → 타깃 검색 없음 → 관계 없음)를
구조적으로 차단해야 한다.

- 근거([A-1]/[E-5]/[E-6]): 이름 매칭은 키워드에 의존하지 않으므로 첫 관계를 만들 수 있고, 그
  관계는 기존 `refresh_stock_keywords` 훅으로 키워드 승격까지 자동 연결된다.

#### REQ-AI085-003 (State-Driven, P0) — 이름 경계 가드 + 기사당 관계 상한 [HARD]

**WHILE** 설명 텍스트에서 종목명을 매칭하는 동안, the system **SHALL** 기존 제목 매처와 동일한
이름 경계 가드(최장일치 우선, 한글 선행문자 배제)를 적용하고 기사당 설명 기반 관계 수를 유계로
제한해, 단일 시황/묶음 기사가 수십 종목에 관계를 남발하지 않도록 해야 한다.

- 근거([A-4]/[E-2]): `classify_news`의 최장일치 + 한글 선행문자 가드(`ai_classifier.py:344-363`)를
  재사용한다. 기사당 상한 값은 plan.md에서 확정.

#### REQ-AI085-004 (State-Driven, P0) — 기존 관련성 점수/필터 재사용

**WHILE** 설명 기반 관계의 관련성을 산정하는 동안, the system **SHALL** 그 관계를 기존
`calculate_relevance_score` + 최소 점수 필터 경로로 라우팅해, 임계를 통과한 매칭만 영속화하고
미달 매칭은 걸러야 한다.

- 근거([E-2]/[E-3]): 설명에 종목명 포함 시 +20은 이미 존재하므로 병렬 점수 게이트를 신설하지
  않는다. 설명 기반 매칭이 이 점수 경로로 흐르도록 배선하는 것이 본 REQ의 요지다(설명-only
  매칭의 점수 취급 세부는 plan.md 결정점).

#### REQ-AI085-005 (Unwanted, P0) — 기존 제목/쿼리 관계 경로 무변경 [HARD]

the system **SHALL NOT** 제목 매칭(`classify_news`)이나 타깃 쿼리 매칭
(`_resolve_query_relations`)에 의한 기존 관계 생성을 변경해서는 안 된다 — 설명 기반 매칭은
엄격히 additive이며 기존 관계는 불변이다.

### 롤아웃·안전·데이터 무결성

#### REQ-AI085-006 (State-Driven, P1) — 설정 게이팅 + 단계적 롤아웃

**WHILE** 설명 기반 매칭이 배포되는 동안, the system **SHALL** 이를 설정 플래그로 게이팅하고
(보수적 기본값) SPEC-AI-079의 단계적 롤아웃 관례를 따라야 한다 — 롤백 = 플래그 복귀로 완전
레거시(제목/쿼리 관계만).

#### REQ-AI085-007 (Unwanted, P0) — following/수동 키워드 데이터 무오염 [HARD]

the system **SHALL NOT** following 시스템의 사용자 키워드 데이터나 수동 설정된 `stocks.keywords`를
변경해서는 안 된다 — 설명 기반 매칭은 `news_stock_relations` 행만 기록한다(기존 관계와 동일
테이블/컬럼).

#### REQ-AI085-008 (State-Driven, P1) — DDD 재현 우선 회귀 안전

**WHILE** 공유 관계 계산 경로(`crawl_all_news`의 관계 루프)를 변경하는 동안, the system **SHALL**
변경 전 현재 거동을 캡처하는 특성화 테스트(characterization test)를 선행해(DDD
ANALYZE-PRESERVE-IMPROVE) 기존 제목/쿼리 관계 생성의 무회귀를 검증해야 한다.

#### REQ-AI085-009 (Optional, P2) — 관측성

**WHERE** 설명 기반 매칭이 실행되면, the system **SHALL** 크롤당 생성된 설명 기반 관계 수를
유계 로그로 요약해(스키마 없음), 순환 고리 차단 효과의 배포 후 관측을 가능하게 해야 한다.

---

## 4. Exclusions (What NOT to Build) [HARD]

본 SPEC은 다음을 **명시적으로 범위에서 제외**한다:

- **[X-1] 전체 시스템 뉴스 커버리지·크롤 예산·API 쿼터 재설계 금지 (사용자 확인 완료).** 본 SPEC은
  RELATION 생성의 특정 순환 고리(제목 너머 설명 텍스트 미검사) 차단에 국한하며, `_build_search_queries`
  의 쿼리 예산(`MAX_TOTAL_QUERIES`/`MAX_STOCK_QUERIES`)·크롤 빈도·외부 API 쿼터·소스 추가를
  건드리지 않는다.
- **[X-2] 스크래핑된 본문(content) 기반 매칭 지양 (본 SPEC 범위 밖, 후속 후보).** 본문은 무-관계
  필터(`news_crawler.py:554-558`) 이후에야 확보되므로([E-4]), 본문 매칭은 스크래핑을 필터 앞으로
  옮기는 파이프라인 재정렬 + 정크 기사 전량 스크래핑 비용 통제를 요구한다. 본 SPEC은 비용 0로
  올바른 순서인 **설명(description)** 매칭에 국한하고, 본문 매칭은 설명이 불충분할 때의 후속
  에스컬레이션(§8 (a))으로 남긴다.
- **[X-3] 라운드로빈 공정성/우선순위 개선(작업 지시 방향 b) 범위 밖.** `_build_search_queries`의
  (c) 계층 라운드로빈을 가격/거래량 활동성 기반으로 재정렬하는 것은 순환 고리를 **완화**할 뿐
  **제거**하지 않는다(사용자 평가). 본 SPEC은 순환 고리를 구조적으로 제거하는 설명 기반 관계
  생성 한 가지 메커니즘에 집중한다(Enforce Simplicity). 방향 b는 §8 (b) 후속 후보.
- **[X-4] 신규 테이블/스키마 마이그레이션 없음.** 설명 기반 관계는 기존 `news_stock_relations`
  테이블/컬럼에 기존 관계와 동일 형식으로 기록된다. `stocks.keywords`는 기존 컬럼(SPEC-AI-084)
  이며 채움은 기존 `refresh_stock_keywords` 훅이 담당한다 — 신규 마이그레이션 불필요.
- **[X-5] 탐지기·앙상블·발신·임계·매수 로직 무변경** (예측 기록 모드, SPEC-AI-043). 본 SPEC은
  관계 데이터 생성만 확장하며 `compute_ensemble_score`/`gather_surge_candidates`/`build_scan_universe`/
  발신 게이팅/매매를 건드리지 않는다.
- **[X-6] 과거 데이터 소급 재계산/관계 백필 금지** — 이후 크롤 실행에만 전진 적용(SPEC-AI-071/
  080/083/084 무백필 관례 계승). 이미 폐기된 과거 기사에 대한 소급 관계 생성은 하지 않는다.
- **[X-7] `classify_news`/`_resolve_query_relations`/`calculate_relevance_score`의 기존 매칭·점수
  로직 재작성 금지** — 설명 매칭은 기존 함수·인덱스·점수 경로를 **재사용**하며, 기존 제목/쿼리
  관계 생성 결과를 바꾸지 않는다(REQ-AI085-005).
- **[X-8] following 시스템(`keyword_matcher`/`following`)과의 통합/변경 금지** (REQ-AI085-007).
  본 SPEC은 `news_stock_relations`만 기록하며 사용자 관심 키워드 데이터와 별개다.
- **[X-9] AI/LLM 기반 개체명 인식(NER) 도입 금지.** 설명 매칭은 기존 규칙/사전 기반
  `KeywordIndex` 종목명 매칭을 재사용한다 — 신규 LLM 인프라·예산 소모를 도입하지 않는다.

---

## 5. Risks (리스크)

- **[R-1] 오탐/관계 precision 리스크 (핵심).** 설명 기반 매칭은 시황/묶음 기사 설명이 다수 종목을
  언급할 때 무관 관계를 남발해 관계 precision을 떨어뜨릴 수 있다. 완화: 이름 경계 가드
  (REQ-AI085-003), 기사당 관계 상한(REQ-AI085-003), 기존 최소 점수 필터 재사용(REQ-AI085-004),
  설정 게이팅 + 단계적 롤아웃(REQ-AI085-006). **자금 리스크 0**(예측 기록 모드).
- **[R-2] 설명 풍부도 한계 리스크.** 설명 스니펫이 본문보다 짧아 특정 미탐 종목을 회수하지 못할
  수 있다. 완화: 순환 고리의 구조적 차단(관계가 생기면 키워드 승격으로 다음 크롤 커버리지가
  누적 개선)을 목표로 삼고, 특정 6종 전수 회수는 배포 후 관측 지표로 다룬다([A-3]). 본문 매칭은
  §8 (a) 후속.
- **[R-3] 공유 코드 회귀 리스크.** 관계 계산 루프는 뉴스 파이프라인의 고fan-in 지점이다 — 결함 시
  기존 제목/쿼리 관계 생성을 조용히 회귀시킬 수 있다. 완화: 재현 우선 특성화 테스트
  (REQ-AI085-008), 설정 플래그 OFF = 완전 레거시(REQ-AI085-006).
- **[R-4] 삽입 볼륨 증가 리스크.** 관계가 늘면 `news_stock_relations` 삽입량과 후속
  `refresh_stock_keywords`/가격 스냅샷 캡처 부하가 증가할 수 있다. 완화: 기사당 관계 상한 +
  최소 점수 필터로 유계화, 관측 로그(REQ-AI085-009)로 배포 후 볼륨 모니터링.

---

## 6. Related SPECs (관련 SPEC)

- **SPEC-AI-084 (직접 상위·불변)**: 키워드 바스켓 테마 전파 + 키워드 태깅 인프라
  (`keyword_tagging_service`, `refresh_stock_keywords` 훅). 본 SPEC이 만드는 설명 기반 관계는 이
  훅으로 키워드 승격까지 자동 연결되며([E-6]), SPEC-AI-084의 로직·테이블·전파는 불변([X-5]).
- **SPEC-AI-079 (참고 패턴)**: 설정 플립 활성화 + 단계적 롤아웃 관례 — 설명 매칭 게이팅에 계승
  (REQ-AI085-006).
- **SPEC-AI-043 (계승)**: 예측 기록 모드(실매매 비활성) — 매매 무변경([X-5]).
- **SPEC-AI-004/030/066 등 (수혜자)**: `immediate_disclosure`·`volume_news_combo`·기타 뉴스
  관계 의존 탐지기 전반이 `NewsStockRelation` 조인을 공유하므로, 본 SPEC의 관계 커버리지 개선은
  이들 모두에 이롭다(SPEC-AI-084가 표면화한 선재·광범위 결손).

---

## 7. Open Questions (열린 질문 — Run/Annotation 단계 확정)

- **[OQ-1] 설명 매칭 삽입 지점·방식.** `classify_news`를 설명에도 재호출(`classify_news(ad.get(
  "description",""), index)`)할지, 제목+설명 결합 텍스트로 한 번에 매칭할지, 전용 헬퍼를 둘지.
  기존 제목 관계와의 중복 제거(dedup) 방식 포함. plan.md 권고 + annotation 확정.
- **[OQ-2] 설명-only 매칭의 점수 취급.** `calculate_relevance_score`의 설명 +20(`:300-301`)이
  이미 존재하나, 제목에 종목명이 없는 설명-only 매칭이 최소 필터 10을 통과하는지(소스별 신뢰도
  곱 후)를 검증하고, 필요 시 설명 기반 관계의 relevance/match_type 라벨(direct/indirect)을 확정.
- **[OQ-3] 기사당 설명 관계 상한 값.** 시황/묶음 기사 오탐 통제를 위한 상한(REQ-AI085-003)의
  구체 값. 라이브 07-22 로봇 랠리 묶음 기사를 replay 표본으로 캘리브레이션.
- **[OQ-4] 설정 플래그 위치·기본값.** SPEC-AI-084 그룹 B의 `NewsUrgencyRecalibrationConfig`
  (surge_settings.py) 선례를 따를지, `app.config.settings` 플래그를 둘지. 기본값(보수적) 확정.
- **[OQ-5] 관측 로그 산정 방식.** 설명 기반 관계 수를 기존 크롤 요약 로그에 합산할지 별도 1줄로
  둘지(REQ-AI085-009). 종목별 로그 금지(스키마/노이즈 억제).

---

## 8. Follow-up Candidates (후속 후보 — 본 SPEC 범위 밖)

- (a) **스크래핑된 본문(content) 기반 관계 매칭**([X-2]) — 설명 매칭이 커버리지에 불충분함이
  배포 후 관측되면, 스크래핑을 무-관계 필터 앞으로 옮기는 파이프라인 재정렬 + 정크 기사 전량
  스크래핑 비용 통제를 갖춘 본문 매칭을 별도 SPEC으로. 설명보다 완전하나 비용·순서 재설계 필요.
- (b) **라운드로빈 타깃 검색 공정성 개선**([X-3], 작업 지시 방향 b) — `_build_search_queries`의
  (c) 계층을 최근 가격/거래량 활동성 기반으로 재정렬해 임박 뉴스 종목의 타깃 커버리지를 높이는
  별도 SPEC. 순환 고리를 완화(제거 아님)하므로 본 SPEC의 구조적 차단과 상보.
- (c) **관계 커버리지 효과 라이브 계측** — 배포 후 설명 기반 관계 생성 수·순환 고리 차단 종목 수·
  탐지기 recall 변화를 사후 관측(관측 전용).
- (d) **키워드 태깅 품질 반복 개선** — SPEC-AI-084 그룹 C의 바스켓 형성 품질을 신규 관계 유입에
  맞춰 관측·개선.
