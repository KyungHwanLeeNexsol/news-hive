---
id: SPEC-NEWS-002
type: acceptance
version: "1.0.0"
created: "2026-03-29"
updated: "2026-03-29"
---

# SPEC-NEWS-002 수용 기준: 뉴스 수집 및 분류 품질 고도화

## Module 1: 관련도 점수

### AC-NEWS-001-1: 키워드 매칭 관련도 산출

```gherkin
Given 뉴스 제목 "대창단조, 3분기 실적 서프라이즈" 수집
And 종목 "대창단조"가 stocks 테이블에 등록
When classify_news()가 호출되면
Then relevance_score >= 55 (제목 직접 언급 40 + 재무 용어 15)
And news_stock_relations에 해당 점수가 저장된다
```

### AC-NEWS-001-2: 저관련도 필터링

```gherkin
Given 뉴스 제목 "건설업계 전반적 전망" 수집
And 종목 "대창단조"가 건설기계 섹터에 등록
When classify_news()가 호출되면
Then relevance_score = 15 (섹터 키워드 15만 해당)
And score < 30이므로 news_stock_relations에 저장되지 않는다
```

### AC-NEWS-001-3: AI 분류 관련도

```gherkin
Given AI 분류가 관련도 점수와 함께 응답
When classify_news_with_ai() 결과가 파싱되면
Then AI가 반환한 relevance_score가 news_stock_relations에 기록된다
```

---

## Module 2: 중복 제거

### AC-NEWS-002-1: 짧은 제목 보호

```gherkin
Given 제목 A "삼성전자 실적 발표" (bigram 7개)
And 제목 B "삼성전자 실적 전망" (bigram 7개)
When 중복 제거가 실행되면
Then 임계값 0.70이 적용된다 (짧은 제목이므로 더 엄격)
And Jaccard 유사도가 0.70 미만이면 두 기사 모두 보존
```

### AC-NEWS-002-2: 다른 소스 허용

```gherkin
Given 한국경제에서 "현대차 2분기 영업이익 사상 최대" 수집
And 매일경제에서 "현대차 2분기 영업이익 역대 최고" 수집
When 중복 제거가 실행되면
Then 다른 소스이므로 임계값이 +0.05 상향 조정
And 두 소스 모두 보존될 가능성이 높아진다
```

### AC-NEWS-002-3: 중복 기사 필터링 유지

```gherkin
Given 같은 소스에서 동일한 기사가 2번 수집
When 중복 제거가 실행되면
Then URL 기반 exact dedup으로 1건만 보존
And 중복 제거 통계 로그에 기록
```

---

## Module 3: 긴급도 감지

### AC-NEWS-004-1: 속보 감지

```gherkin
Given 뉴스 제목 "[속보] 삼성전자 반도체 대규모 투자 발표"
When 긴급도 분류가 실행되면
Then urgency = "breaking"이 news_articles에 기록
And 시간 가중치가 1.5x로 상향 조정
```

### AC-NEWS-004-2: 중요 보도 감지

```gherkin
Given 뉴스 제목 "SK하이닉스 3분기 실적, 시장 전망치 상회"
And 제목에 "실적" 키워드 포함
When 긴급도 분류가 실행되면
Then urgency = "important"이 기록
```

### AC-NEWS-004-3: 동일 주제 빈도 기반 속보

```gherkin
Given 최근 1시간 내 "삼성전자" 관련 뉴스가 7건 수집
When 긴급도 분류가 실행되면
Then 해당 뉴스들이 "breaking"으로 상향 조정
```

---

## Module 4: 소스 신뢰도

### AC-NEWS-005-1: Tier 1 소스 적용

```gherkin
Given 한국경제 소스의 뉴스
When 관련도 점수에 소스 신뢰도를 적용하면
Then 신뢰도 가중치 1.0x가 적용 (점수 변동 없음)
```

### AC-NEWS-005-2: 미매핑 소스 기본값

```gherkin
Given 소스가 "알 수 없는 블로그"인 뉴스
When 신뢰도 매핑을 조회하면
Then 기본 신뢰도 0.5가 적용
And 로그에 "Unmapped source: 알 수 없는 블로그" 기록
```

---

## Module 5: 토픽 클러스터링

### AC-NEWS-006-1: 핫 토픽 감지

```gherkin
Given 반도체 섹터 관련 뉴스 7건이 24시간 내 수집
And 뉴스들의 bigram 유사도가 0.3 이상인 그룹 존재
When 토픽 클러스터링이 실행되면
Then 해당 그룹이 "핫 토픽"으로 플래그
And AI 프롬프트에 "[핫 토픽] 반도체: 7건의 관련 뉴스" 포함
```

### AC-NEWS-006-2: 소규모 클러스터

```gherkin
Given 철강 섹터 관련 뉴스 2건 수집
When 토픽 클러스터링이 실행되면
Then 클러스터 크기 < 3이므로 핫 토픽으로 표시되지 않는다
```

---

## Module 6: Gemini Async

### AC-NEWS-007-1: 비동기 동작 확인

```gherkin
Given Groq API가 실패하여 Gemini fallback 발생
When _call_gemini_key()가 호출되면
Then asyncio.to_thread()를 통해 실행
And 다른 비동기 작업이 블로킹되지 않는다
```

### AC-NEWS-007-2: Fallback 체인 보존

```gherkin
Given Groq와 Gemini-1이 모두 rate limited
When ask_ai()가 호출되면
Then Gemini-2로 fallback
And 최종 응답이 정상 반환
```

---

## Module 7: 키워드 캐싱

### AC-NEWS-008-1: 캐시 히트

```gherkin
Given KeywordIndex가 이전 크롤링에서 빌드됨
And stocks/sectors 테이블에 변경 없음
When 다음 크롤링에서 classify_news()가 호출되면
Then 캐시된 KeywordIndex가 재사용
And 로그에 "KeywordIndex: cache hit" 기록
And DB 조회(stocks/sectors SELECT)가 발생하지 않는다
```

### AC-NEWS-008-2: 캐시 무효화

```gherkin
Given 사용자가 새로운 종목을 추가
When 다음 크롤링이 실행되면
Then MAX(updated_at) 변경으로 캐시가 무효화
And KeywordIndex가 재구축
And 로그에 "KeywordIndex: cache miss (rebuilt)" 기록
```

---

## Module 8: 커버리지 갭

### AC-NEWS-009-1: 무뉴스 종목 감지

```gherkin
Given 종목 "진성이엔씨"가 최근 72시간 동안 관련 뉴스 0건
When 커버리지 갭 분석이 실행되면
Then "진성이엔씨"가 coverage_gap 목록에 포함
And 해당 종목 시그널 생성 시 "정보 부족 주의" 경고 포함
```

### AC-NEWS-009-2: 브리핑 커버리지 현황

```gherkin
Given 5개 섹터, 15개 종목이 추적 중
When 일간 브리핑이 생성되면
Then "뉴스 커버리지 현황" 섹션에 섹터별 뉴스 수 표시
And coverage_gap 종목이 빨간색(또는 경고)으로 표시
```

---

## Module 9: 감성 분석

### AC-NEWS-010-1: 6단계 감성 분류

```gherkin
Given 뉴스 "삼성전자 3분기 영업이익 20조 돌파, 역대 최고"
When 감성 분석이 실행되면
Then sentiment = "strong_positive"
```

### AC-NEWS-010-2: 반전 표현 감지

```gherkin
Given 뉴스 제목 "현대차 판매량 감소"
And 본문에 "다만 전기차 부문은 전년 대비 30% 성장하며 긍정적 전망"
When 문맥 감성 분석이 실행되면
Then sentiment = "mixed"
And AI 프롬프트에 반전 컨텍스트 포함
```

---

## Module 10: 글로벌 뉴스

### AC-NEWS-011-1: 글로벌 키워드 매핑

```gherkin
Given Yahoo Finance에서 "Nvidia reports record revenue, AI chip demand surges" 수집
When 글로벌-한국 매핑이 실행되면
Then 반도체 섹터와 연결
And AI 프롬프트 "글로벌 뉴스 영향" 섹션에 포함
```

### AC-NEWS-011-2: 장 개장 전 리스크 경고

```gherkin
Given 08:30 KST에 "Fed raises interest rates by 50bp" 뉴스 수집
And 감성 = strong_negative
When 글로벌 리스크 분석이 실행되면
Then global_risk 경고 생성
And 금융 섹터 + 전체 시장 관련 경고 표시
```

---

## Edge Cases

### EC-1: 모든 AI 프로바이더 실패 시

```gherkin
Given Groq + Gemini x3 모두 실패
When 뉴스 분류가 실행되면
Then 키워드 매칭 기반 분류만 적용 (graceful degradation)
And 관련도 점수는 키워드 기반으로만 산출
And 감성 분석은 "neutral" 기본값 적용
```

### EC-2: 뉴스 본문 없는 경우

```gherkin
Given article_scraper가 본문 수집에 실패
When 문맥 감성 분석이 실행되면
Then 제목 기반 감성 분석으로 fallback
And 6단계 중 strong_positive/strong_negative는 부여하지 않음
```

### EC-3: 캐시와 동시 크롤링

```gherkin
Given 수동 새로고침과 스케줄러 크롤링이 동시 실행
When KeywordIndex 캐시를 접근하면
Then 단일 프로세스이므로 경합 없음 (uvicorn 단일 워커)
And 둘 다 같은 캐시된 인덱스를 사용
```

---

## Quality Gates

### 성능 기준
- 키워드 인덱스 캐시 히트 시 크롤링 시간: 기존 대비 -2초 이상
- Gemini async 전환 후 동시 HTTP 요청 처리: 블로킹 없음 확인
- 토픽 클러스터링: 100건 뉴스 기준 1초 이내

### 품질 기준
- 적응형 dedup 후 유효 기사 수: 기존 대비 15~25% 증가
- 실제 중복 통과율: 5% 미만
- 관련도 30 미만 필터링 시 오탈락율: 10% 미만 (수동 검증)
- 감성 분석 6단계 정확도: 수동 검증 시 65% 이상

### Definition of Done
- [ ] Gemini 호출이 이벤트 루프를 블로킹하지 않음 (async 검증)
- [ ] 키워드 인덱스 캐시 히트/미스 로깅 확인
- [ ] 적응형 임계값 적용 후 중복 제거 통계 개선
- [ ] 관련도 점수가 news_stock_relations에 정상 기록
- [ ] 긴급도가 news_articles에 정상 기록
- [ ] 감성 6단계 분류 정상 동작
- [ ] 소스 신뢰도 Tier 매핑 완료 (주요 한국 언론 30개+)
- [ ] 커버리지 갭 감지 및 브리핑 통합
- [ ] 기존 뉴스 크롤링 파이프라인 regression 없음
- [ ] 글로벌 키워드-섹터 매핑 최소 20개 키워드
