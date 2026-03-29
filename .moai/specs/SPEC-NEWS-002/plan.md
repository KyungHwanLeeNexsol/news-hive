---
id: SPEC-NEWS-002
type: plan
version: "1.0.0"
created: "2026-03-29"
updated: "2026-03-29"
---

# SPEC-NEWS-002 구현 계획: 뉴스 수집 및 분류 품질 고도화

## 구현 전략

ai_classifier.py(639 LOC)와 news_crawler.py의 기존 로직을 점진적으로 개선하면서,
토픽 클러스터링 등 새로운 기능은 별도 모듈로 분리한다.
각 Phase는 독립적으로 배포 가능하며, 이전 Phase의 기능이 없어도 동작한다.

## Phase 1: 핵심 버그 수정 및 성능 (Primary Goal)

**범위**: REQ-NEWS-007, REQ-NEWS-008, REQ-NEWS-002

### 작업 분해

**Task 1.1: Gemini 블로킹 호출 수정 (REQ-NEWS-007)**
- 대상 파일: `backend/app/services/ai_client.py`
- 작업 내용:
  - _call_gemini_key() 내부의 `client.models.generate_content()` 호출을 `asyncio.to_thread()`로 래핑
  - google-genai 라이브러리의 async API 존재 여부 확인 (있으면 async 버전 사용)
  - 기존 fallback 체인 동작 보존
- 영향 범위: 전체 AI 호출 (분류, 감성 분석, 번역, 펀드매니저)
- 리스크: 낮음 (래핑만 변경)

**Task 1.2: 키워드 인덱스 캐싱 (REQ-NEWS-008)**
- 대상 파일: `backend/app/services/ai_classifier.py`
- 작업 내용:
  - 모듈 레벨 `_cached_index: KeywordIndex | None` 변수 추가
  - `_cache_checkpoint: tuple[int, datetime] | None` (종목 수, 최신 updated_at)
  - classify 호출 시 체크포인트 비교 -> 변경 없으면 캐시 재사용
  - 캐시 히트/미스 로깅
- 의존성: stocks, sectors 테이블의 updated_at 컬럼
- 리스크: 스레드 안전성 (단일 워커이므로 문제 없음, 주석 명시)

**Task 1.3: 적응형 중복 제거 임계값 (REQ-NEWS-002)**
- 대상 파일: `backend/app/services/news_crawler.py`
- 작업 내용:
  - _is_similar_title() 함수에 bigram 수 기반 동적 임계값 적용
  - 소스 다양성 고려 (다른 소스면 +0.05 허용)
  - 기존 고정 0.55 임계값을 adaptive로 교체
  - 필터링 통계 로깅 강화 (임계값별 카운트)
- 리스크: 중복 기사 증가 가능성 -> 모니터링 필요

### Alembic 마이그레이션
- 이 Phase에서는 DB 변경 없음

---

## Phase 2: 분류 품질 향상 (Secondary Goal)

**범위**: REQ-NEWS-001, REQ-NEWS-004, REQ-NEWS-005, REQ-NEWS-010

### 작업 분해

**Task 2.1: 컨텍스트 관련도 점수 (REQ-NEWS-001)**
- 대상 파일: `backend/app/services/ai_classifier.py`
- 작업 내용:
  - classify_news() 반환값에 relevance_score 추가
  - 점수 산출 로직: 제목 키워드(+40), 본문 키워드(+20), 섹터(+15), 재무 용어(+15), 비금융(-30)
  - classify_news_with_ai() 프롬프트에 relevance_score 반환 요청 추가
  - news_stock_relations 저장 시 30 미만 필터링
- DB 변경: news_stock_relations에 relevance_score INTEGER 추가

**Task 2.2: 뉴스 긴급도 감지 (REQ-NEWS-004)**
- 대상 파일: `backend/app/services/news_crawler.py`
- 작업 내용:
  - 속보 패턴 정규식: r"\[(속보|긴급|단독|breaking|exclusive)\]"
  - 중요 보도 키워드 리스트: ["실적", "인수", "합병", "M&A", "규제", "소송", "배당", "상장폐지", ...]
  - 동일 주제 빈도 감지 (1시간 내 5건 이상)
  - breaking 뉴스 시간 가중치 1.5x 적용
- DB 변경: news_articles에 urgency VARCHAR(20) 추가

**Task 2.3: 소스 신뢰도 가중치 (REQ-NEWS-005)**
- 대상 파일: `backend/app/services/ai_classifier.py`
- 작업 내용:
  - SOURCE_CREDIBILITY 딕셔너리 구현 (5 Tier)
  - 소스명 -> Tier 매핑 (정규식 기반 매칭)
  - 관련도 점수에 신뢰도 가중치 곱하기
  - 기본 신뢰도 0.5 (미매핑 소스)
- 설정: ai_classifier.py 상단 또는 별도 config 파일

**Task 2.4: 문맥 감성 분석 확장 (REQ-NEWS-010)**
- 대상 파일: `backend/app/services/ai_classifier.py`
- 작업 내용:
  - 감성 카테고리 6단계 확장 (strong_positive ~ strong_negative + mixed)
  - 본문 내 반전 표현 감지 ("다만", "그러나", "한편", "반면")
  - AI 분류 프롬프트에 6단계 감성 반환 요청
  - classify_sentiment() 및 classify_sentiment_with_ai() 업데이트
- DB 변경: news_stock_relations에 sentiment VARCHAR(20) 추가 (기존 match_type/relevance 외 별도)

### Alembic 마이그레이션
- news_stock_relations: relevance_score INTEGER, sentiment VARCHAR(20) 추가
- news_articles: urgency VARCHAR(20) 추가

---

## Phase 3: 고급 분석 기능 (Tertiary Goal)

**범위**: REQ-NEWS-006, REQ-NEWS-009, REQ-NEWS-011

### 작업 분해

**Task 3.1: 토픽 클러스터링 (REQ-NEWS-006)**
- 신규 파일: `backend/app/services/topic_clustering.py`
- 작업 내용:
  - 간단한 agglomerative clustering (bigram 유사도 0.3 기준)
  - 동일 섹터 태그 + 24시간 이내 조건
  - 클러스터 크기 5+ -> 핫 토픽 플래그
  - AI 프롬프트 주입 포맷: "[핫 토픽] 반도체: 7건의 관련 뉴스"

**Task 3.2: 뉴스 커버리지 갭 감지 (REQ-NEWS-009)**
- 대상 파일: `backend/app/services/news_crawler.py`
- 작업 내용:
  - 종목별 최근 72시간 뉴스 수 집계 쿼리
  - 0건 종목 리스트 생성 및 fund_manager.py에 전달
  - 브리핑에 "뉴스 커버리지 현황" 섹션 추가

**Task 3.3: 글로벌 뉴스 영향 분석 (REQ-NEWS-011)**
- 대상 파일: `backend/app/services/ai_classifier.py`, `backend/app/services/news_crawler.py`
- 작업 내용:
  - GLOBAL_KEYWORD_SECTOR_MAP 딕셔너리 구현
  - Yahoo/Google 영문 뉴스에서 한국 관련 키워드 매칭
  - 장 개장 전(09:00 KST) global_risk 경고 생성
  - AI 프롬프트에 "글로벌 뉴스 영향" 섹션

---

## Phase 4: 메트릭 및 모니터링 (Optional Goal)

**범위**: REQ-NEWS-003

### 작업 분해

**Task 4.1: 중복 제거 메트릭 API**
- 대상 파일: `backend/app/routers/news.py`
- 신규 모델: dedup 통계 Pydantic 스키마
- 작업 내용:
  - 크롤링 시 중복 제거 통계를 news_crawl_stats 테이블에 저장
  - GET /api/news/dedup-stats 엔드포인트
  - 최근 7일 일별 통계 반환

---

## 신규 파일 목록

| 파일 | 용도 |
|------|------|
| backend/app/services/topic_clustering.py | 뉴스 토픽 클러스터링 |

## 수정 파일 목록

| 파일 | 변경 내용 |
|------|-----------|
| backend/app/services/ai_client.py | Gemini async 전환 (asyncio.to_thread) |
| backend/app/services/ai_classifier.py | 관련도 점수, 소스 신뢰도, 감성 6단계, 키워드 캐싱, 글로벌 매핑 |
| backend/app/services/news_crawler.py | 적응형 dedup, 긴급도 감지, 커버리지 갭 |
| backend/app/routers/news.py | dedup stats 엔드포인트 |
| backend/app/models/news.py | urgency 컬럼 추가 |
| backend/app/models/news_relation.py | relevance_score, sentiment 컬럼 추가 |

## 리스크 및 대응

| 리스크 | 영향 | 대응 |
|--------|------|------|
| 적응형 임계값으로 중복 증가 | 사용자 경험 저하 | 1주일 모니터링 후 임계값 미세 조정 |
| Gemini async 전환 부작용 | AI 호출 실패 | 기존 fallback 체인 유지, to_thread 실패 시 sync fallback |
| 관련도 점수 30 기준 과도 필터링 | 유효 뉴스 누락 | 초기 20으로 시작, 1주일 후 30으로 상향 |
| 소스 신뢰도 매핑 불완전 | 주요 소스 누락 | Tier 5(0.3x) 기본값으로 안전, 로그 모니터링으로 미매핑 소스 발견 |
| ai_classifier.py 코드량 증가 | 유지보수 어려움 | 독립 함수로 분리, 600LOC 초과 시 모듈 분할 검토 |
| 클러스터링 O(n^2) 성능 | 대량 뉴스 시 느림 | 섹터별 분할 클러스터링으로 n 제한 |

## 기술적 접근 방향

1. **Phase 1 우선**: 버그 수정(Gemini async)과 성능 개선(캐싱, dedup)을 먼저 처리하여 기반 안정화
2. **하위 호환**: 모든 DB 변경은 nullable 컬럼 추가로 기존 데이터 영향 없음
3. **점진적 활성화**: 관련도 점수, 소스 신뢰도 등은 초기에 로깅만 하고 필터링은 나중에 활성화
4. **AI 프롬프트 통합**: 각 모듈의 결과는 fund_manager.py의 AI 프롬프트에 구조화된 섹션으로 주입
5. **설정 기반**: 임계값, 신뢰도 매핑, 키워드 리스트는 코드 내 상수로 관리 (개인 프로젝트 특성상 DB 설정 불필요)
