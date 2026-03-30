---
id: SPEC-NEWS-002
version: "1.0.0"
status: completed
created: "2026-03-29"
updated: "2026-03-29"
author: zuge3
priority: high
issue_number: 0
depends_on: ["SPEC-NEWS-001"]
---

# 뉴스 수집 및 분류 품질 고도화

## 개요

뉴스 수집 파이프라인의 품질을 전방위적으로 개선하여 AI 펀드 예측 시스템에 양질의 입력을 제공한다.
현재 시스템의 주요 약점(중복 제거 과민, 블로킹 API 호출, 키워드 인덱스 비효율, 감성 분석 피상성)을
해결하고, 뉴스 긴급도 감지, 소스 신뢰도, 토픽 클러스터링 등 고급 기능을 추가한다.

핵심 목표:
- 뉴스 관련도 점수(contextual relevance)로 노이즈 필터링 강화
- 중복 제거 알고리즘 개선 (bigram 0.55 임계값 조정)
- 뉴스 긴급도 감지 (속보 vs 정기 보도)
- 소스 신뢰도 가중치 반영
- 토픽 클러스터링으로 섹터 레벨 분석 지원
- Gemini 블로킹 호출 async 전환
- 키워드 인덱스 캐시 최적화
- 뉴스 커버리지 갭 감지
- 문맥 인식 감성 분석
- 글로벌 뉴스 한국 시장 영향 분석

## 환경 (Environment)

- Backend: Python 3.11+ / FastAPI / SQLAlchemy 2.0 / PostgreSQL 16
- AI Provider: Groq (primary) + Gemini x3 (fallback) via ai_client.py
- 뉴스 소스: Naver Search API, Google News RSS, Yahoo Finance, Korean RSS, DART
- 기존 파일:
  - ai_classifier.py (639 LOC): 키워드 매칭 + AI 분류
  - news_crawler.py: 크롤러 오케스트레이터 (bigram dedup 포함)
  - ai_client.py (119 LOC): Groq/Gemini 멀티 프로바이더
  - crawlers/naver.py, google.py, yahoo.py, korean_rss.py
- 기존 테이블: news_articles, news_stock_relations, sectors, stocks
- 스케줄러: 10분 간격 뉴스 크롤링

## 전제 (Assumptions)

- A1: 현재 bigram Jaccard 유사도 0.55 임계값이 일부 유효한 뉴스를 과잉 필터링하고 있다
- A2: ai_client.py의 _call_gemini_key()가 sync google.genai 라이브러리를 사용하여 이벤트 루프를 블로킹한다
- A3: KeywordIndex.build()가 매 크롤링마다 전체 재구축되어 불필요한 DB 조회가 발생한다
- A4: 현재 감성 분석은 뉴스 제목 기반이며, 본문 컨텍스트를 활용하지 않는다
- A5: 한국 증시에 영향을 주는 글로벌 뉴스(미국 금리, 반도체 규제 등)는 현재 부분적으로만 수집된다
- A6: 뉴스 기사는 7일 후 삭제되지만, 분류 결과(news_stock_relations)는 보존된다

---

## Module 1: 뉴스 관련도 점수 (Contextual Relevance Scoring)

### REQ-NEWS-001: 컨텍스트 기반 관련도 점수

**WHEN** 뉴스가 수집되어 분류될 때 **THEN** 시스템은 단순 키워드 매칭 외에 문맥 기반 관련도 점수(0~100)를 산출해야 한다.

관련도 점수 산출 기준:
- 제목 내 종목명/키워드 직접 언급: +40점
- 본문 내 종목명/키워드 언급: +20점
- 동일 섹터 키워드 언급: +15점
- 재무/실적 관련 용어 포함: +15점
- 비금융 패턴 포함 시: -30점 (기존 is_non_financial_article 로직 활용)

시스템은 **항상** 관련도 점수가 30 미만인 뉴스-종목 관계를 news_stock_relations에 저장하지 않아야 한다.

**가능하면** AI 분류 시에도 관련도 점수를 함께 반환하도록 프롬프트를 설계한다.

수용 기준:
- news_stock_relations 테이블에 relevance_score INTEGER 컬럼 추가
- 키워드 매칭 분류 시 관련도 점수 산출 로직 구현
- AI 분류 응답에서 relevance_score 파싱
- 관련도 30 미만 관계는 DB에 저장되지 않음

---

## Module 2: 중복 제거 알고리즘 개선 (Dedup Enhancement)

### REQ-NEWS-002: 적응형 유사도 임계값

**WHEN** 뉴스 중복 제거를 수행할 때 **THEN** 시스템은 고정 임계값(0.55) 대신 제목 길이와 소스 다양성을 고려한 적응형 임계값을 사용해야 한다.

적응형 임계값 규칙:
- 짧은 제목(bigram 10개 미만): 임계값 0.70 (짧은 제목은 우연히 유사할 수 있음)
- 중간 제목(10~20 bigram): 임계값 0.60
- 긴 제목(20+ bigram): 임계값 0.50
- 같은 소스(source)에서 온 기사: 현재 임계값 유지
- 다른 소스에서 온 기사: 임계값 +0.05 (다른 소스의 유사 기사는 더 허용)

시스템은 **항상** 중복 제거 시 필터링된 기사 수와 적용된 임계값을 로그에 기록해야 한다.

수용 기준:
- _is_similar_title() 함수에 적응형 임계값 로직 적용
- 제목 길이별 임계값이 문서화되고 설정으로 관리
- 중복 제거 후 유효 기사 수가 기존 대비 15~25% 증가 (과잉 필터링 해소)
- 실제 중복 기사가 통과하는 비율은 5% 미만 유지

### REQ-NEWS-003: 중복 제거 메트릭 대시보드

**가능하면** 시스템은 중복 제거 통계(exact/fuzzy/source별 필터링 수)를 API로 제공하여 프론트엔드에서 모니터링할 수 있도록 한다.

수용 기준:
- GET /api/news/dedup-stats 엔드포인트 구현
- 최근 7일간의 일별 중복 제거 통계 반환

---

## Module 3: 뉴스 긴급도 감지 (News Urgency Detection)

### REQ-NEWS-004: 속보 vs 정기 보도 분류

**WHEN** 뉴스가 수집될 때 **THEN** 시스템은 각 기사의 긴급도를 다음 3단계로 분류해야 한다:
- `breaking`: 속보 (제목에 "[속보]", "[긴급]", "[단독]" 등 포함, 또는 최근 1시간 내 동일 주제 5건 이상)
- `important`: 중요 보도 (실적, 인수합병, 규제 변경 등 재무 영향 키워드 포함)
- `routine`: 정기 보도 (위 두 범주에 해당하지 않는 기사)

**WHEN** breaking 등급 뉴스가 감지되면 **THEN** 시스템은 해당 뉴스의 시간 가중치를 1.5x로 상향 조정해야 한다 (REQ-AI-002 시간 가중 스코어링 연동).

시스템은 **항상** 긴급도 정보를 news_articles 테이블에 기록해야 한다.

수용 기준:
- news_articles 테이블에 urgency VARCHAR(20) 컬럼 추가 (breaking/important/routine)
- 속보 패턴 감지 로직 (정규식 + 동일 주제 빈도)
- 중요 보도 키워드 리스트 관리 (실적, M&A, 규제, 소송, 배당 등)
- breaking 뉴스의 시간 가중치 1.5x 적용
- AI 프롬프트에 긴급도별 뉴스 그룹핑

---

## Module 4: 소스 신뢰도 가중치 (Source Credibility Weighting)

### REQ-NEWS-005: 뉴스 소스별 신뢰도 점수

시스템은 **항상** 뉴스 소스별로 신뢰도 가중치를 적용하여 AI 분류 및 감성 분석 결과에 반영해야 한다.

신뢰도 등급:
- Tier 1 (1.0x): 주요 경제지 (한국경제, 매일경제, 서울경제, 이데일리, 머니투데이)
- Tier 2 (0.85x): 종합 일간지 (조선일보, 중앙일보, 동아일보, 한겨레, 경향신문)
- Tier 3 (0.7x): 통신사 및 방송 (연합뉴스, 뉴스1, 뉴시스, YTN, SBS)
- Tier 4 (0.5x): 전문지/온라인 매체 (더벨, 인포스탁데일리, 팍스넷)
- Tier 5 (0.3x): 미확인/기타 소스

**IF** 소스가 매핑되지 않은 경우 **THEN** 시스템은 기본 신뢰도 0.5를 적용해야 한다.

수용 기준:
- source_credibility 매핑 딕셔너리 구현 (설정 파일 또는 DB)
- news_stock_relations의 관련도 점수에 소스 신뢰도 가중치 반영
- AI 프롬프트에 소스 신뢰도 Tier 정보 포함

---

## Module 5: 토픽 클러스터링 (Topic Clustering)

### REQ-NEWS-006: 관련 뉴스 그룹핑

**WHEN** 특정 섹터에 관련된 뉴스가 3건 이상 수집될 때 **THEN** 시스템은 유사 주제의 뉴스를 클러스터로 그룹핑하여 섹터 레벨 분석에 활용해야 한다.

클러스터링 기준:
- 동일 종목/섹터 태그
- 제목 bigram 유사도 0.3 이상 (클러스터링 용도로는 느슨하게)
- 24시간 이내 발행

**WHEN** 클러스터 크기가 5건 이상인 "핫 토픽"이 감지될 때 **THEN** 시스템은 해당 토픽을 AI 프롬프트에 "[핫 토픽] 섹터명: N건의 관련 뉴스" 형태로 강조해야 한다.

수용 기준:
- 뉴스 클러스터링 로직 구현 (간단한 agglomerative 방식)
- 클러스터 정보가 AI 프롬프트에 포함
- 핫 토픽 감지 시 브리핑에 별도 섹션으로 강조

---

## Module 6: Gemini 블로킹 호출 수정 (Async Fix)

### REQ-NEWS-007: Gemini API 비동기 전환

시스템은 **항상** Gemini API 호출 시 asyncio 이벤트 루프를 블로킹하지 않아야 한다.

**현재 문제**: ai_client.py의 `_call_gemini_key()`에서 `google.genai.Client.generate_content()`가 sync 호출이므로 이벤트 루프를 블로킹한다.

**수정 방향**: `asyncio.to_thread()`로 sync 호출을 래핑하거나, google-genai 라이브러리의 async API가 있다면 활용한다.

수용 기준:
- _call_gemini_key() 내부에서 asyncio.to_thread() 사용
- 다른 async 작업(뉴스 크롤링 등)이 Gemini 호출 중에도 정상 동작
- 기존 fallback 체인(Groq -> Gemini x3) 동작 변경 없음

---

## Module 7: 키워드 인덱스 캐싱 (Keyword Index Caching)

### REQ-NEWS-008: 변경 감지 기반 인덱스 캐싱

**WHILE** stocks/sectors 테이블에 변경이 없을 때 **THEN** 시스템은 KeywordIndex를 캐시에서 재사용하고 매 크롤링마다 재구축하지 않아야 한다.

**WHEN** stocks 또는 sectors 테이블에 INSERT/UPDATE/DELETE가 발생할 때 **THEN** 시스템은 KeywordIndex 캐시를 무효화하고 다음 크롤링 시 재구축해야 한다.

캐시 무효화 전략:
- stocks/sectors 테이블의 MAX(updated_at) 또는 COUNT(*)를 체크포인트로 사용
- 체크포인트가 변경되면 캐시 무효화

수용 기준:
- KeywordIndex 싱글턴 캐시 구현 (모듈 레벨)
- 변경 감지 로직 (MAX(updated_at) 비교)
- 캐시 히트 시 DB 조회 스킵
- 크롤링 로그에 "KeywordIndex: cache hit" / "cache miss (rebuilt)" 기록

---

## Module 8: 뉴스 커버리지 갭 감지 (Coverage Gap Detection)

### REQ-NEWS-009: 뉴스 없는 종목 알림

**WHEN** 추적 중인 종목이 최근 72시간 동안 관련 뉴스가 0건일 때 **THEN** 시스템은 "뉴스 커버리지 갭(coverage_gap)" 알림을 생성해야 한다.

**WHEN** 커버리지 갭이 감지된 종목에 대해 시그널이 생성될 때 **THEN** 시스템은 AI 프롬프트에 "최근 72시간 뉴스 없음 - 정보 부족 주의" 경고를 포함해야 한다.

시스템은 **항상** 일간 브리핑에 "뉴스 커버리지 현황" 섹션을 포함하여 각 섹터별 뉴스 수를 표시해야 한다.

수용 기준:
- 종목별 최근 뉴스 수 집계 로직 구현
- 72시간 무뉴스 종목 리스트 생성
- 브리핑에 커버리지 현황 섹션 추가
- coverage_gap 종목의 시그널에 정보 부족 경고 포함

---

## Module 9: 문맥 인식 감성 분석 (Context-Aware Sentiment)

### REQ-NEWS-010: 본문 기반 감성 분석

**WHEN** 뉴스 기사의 본문(article_scraper.py로 수집)이 존재할 때 **THEN** 시스템은 제목만이 아닌 본문 내용을 함께 활용하여 감성을 분석해야 한다.

**IF** 제목이 부정적이나 본문에서 "다만 ... 긍정적 전망", "그러나 ... 반등 예상" 등의 반전 표현이 있을 때 **THEN** 시스템은 감성을 "mixed"로 판정하고 AI 프롬프트에 반전 컨텍스트를 포함해야 한다.

시스템은 감성 분석 시 **항상** 다음 카테고리를 사용해야 한다:
- `strong_positive`: 명확한 호재 (실적 상회, 대규모 수주, 배당 증가)
- `positive`: 일반 긍정
- `mixed`: 긍정/부정 혼재
- `neutral`: 중립
- `negative`: 일반 부정
- `strong_negative`: 명확한 악재 (적자 전환, 상장폐지 우려, 횡령)

수용 기준:
- 감성 분석 카테고리가 6단계로 확장
- 본문 기반 반전 표현 감지 로직
- AI 분류 시 6단계 감성을 반환하도록 프롬프트 수정
- news_stock_relations에 sentiment VARCHAR(20) 컬럼 추가

---

## Module 10: 글로벌 뉴스 영향 분석 (Global News Impact)

### REQ-NEWS-011: 한국 시장 영향 글로벌 뉴스 감지

**WHEN** 글로벌 뉴스(Yahoo Finance, Google News 영문)에서 한국 증시에 영향을 줄 수 있는 키워드가 감지될 때 **THEN** 시스템은 해당 뉴스를 한국 관련 섹터와 매핑해야 한다.

글로벌-한국 영향 매핑:
- "semiconductor", "chip", "TSMC", "Nvidia" -> 반도체 섹터
- "oil price", "crude", "OPEC" -> 정유/화학 섹터
- "Fed rate", "interest rate", "treasury" -> 금융 섹터, 전체 시장
- "EV", "battery", "lithium" -> 2차전지 섹터
- "steel", "iron ore" -> 철강 섹터
- "Samsung", "Hyundai", "LG", "SK" -> 해당 그룹 종목

**WHEN** 매핑된 글로벌 뉴스의 감성이 strong_negative이고 한국 장 개장 전(09:00 KST 이전)일 때 **THEN** 시스템은 "글로벌 리스크(global_risk)" 경고를 생성해야 한다.

수용 기준:
- 글로벌 키워드-한국 섹터 매핑 테이블 구현
- Yahoo/Google 영문 뉴스에서 한국 관련 키워드 감지
- 장 개장 전 글로벌 리스크 경고 생성
- AI 프롬프트에 "글로벌 뉴스 영향" 섹션 포함

---

## 추적 태그

| TAG | 설명 | 관련 파일 |
|-----|------|-----------|
| SPEC-NEWS-002 | 본 SPEC 전체 | - |
| REQ-NEWS-001 | 컨텍스트 관련도 점수 | ai_classifier.py |
| REQ-NEWS-002 | 적응형 유사도 임계값 | news_crawler.py |
| REQ-NEWS-003 | 중복 제거 메트릭 | news_crawler.py, routers/news.py |
| REQ-NEWS-004 | 긴급도 감지 | news_crawler.py, ai_classifier.py |
| REQ-NEWS-005 | 소스 신뢰도 가중치 | ai_classifier.py |
| REQ-NEWS-006 | 토픽 클러스터링 | topic_clustering.py (신규) |
| REQ-NEWS-007 | Gemini async 수정 | ai_client.py |
| REQ-NEWS-008 | 키워드 인덱스 캐싱 | ai_classifier.py |
| REQ-NEWS-009 | 커버리지 갭 감지 | news_crawler.py, fund_manager.py |
| REQ-NEWS-010 | 문맥 감성 분석 | ai_classifier.py |
| REQ-NEWS-011 | 글로벌 뉴스 영향 | ai_classifier.py, news_crawler.py |
