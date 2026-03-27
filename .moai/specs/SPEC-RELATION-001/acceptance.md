---
id: SPEC-RELATION-001
type: acceptance
version: "1.0.0"
created: "2026-03-27"
updated: "2026-03-27"
---

## HISTORY

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0.0 | 2026-03-27 | MoAI | Initial acceptance criteria creation |

---

# SPEC-RELATION-001: 수락 기준 및 테스트 시나리오

> TAG: SPEC-RELATION-001
> 검증 대상: stock_relations 테이블, 뉴스 전파 엔진, AI 추론 서비스, 프론트엔드 배지 시스템

---

## Given-When-Then 테스트 시나리오

### TC-01: 섹터 간 AI 추론 - 전체 섹터 DB 기반 관계 생성

**Feature**: Inter-sector AI inference (Phase A)

```gherkin
Scenario: DB의 전체 섹터 목록을 Gemini AI에 전송하여 섹터 간 관계를 추론한다
  Given DB에 "반도체" (id=1), "반도체장비" (id=2), "자동차" (id=3), "자동차부품" (id=4) 섹터가 있고
  And stock_relations 테이블이 비어있고
  And Gemini AI가 다음 JSON 응답을 반환할 때:
    [
      {"source_sector_id": 2, "target_sector_id": 1, "relation_type": "equipment", "confidence": 0.9, "reason": "반도체 생산설비 공급"},
      {"source_sector_id": 4, "target_sector_id": 3, "relation_type": "supplier", "confidence": 0.85, "reason": "자동차 부품 공급"}
    ]
  When infer_inter_sector_relations(db) 함수가 호출되면
  Then stock_relations에 source_sector_id=2, target_sector_id=1, type=equipment, confidence=0.9 행이 생성된다
  And stock_relations에 source_sector_id=4, target_sector_id=3, type=supplier, confidence=0.85 행이 생성된다
  And 총 2개의 섹터 간 관계가 생성된다
  And AI 프롬프트에 하드코딩된 관계 목록이 아닌 DB에서 조회한 섹터 목록이 포함되어 있다
```

### TC-02: 섹터 내 경쟁사 AI 추론 - DB 종목 기반

**Feature**: Intra-sector competitor inference (Phase B)

```gherkin
Scenario: 섹터 내 종목 목록을 Gemini AI에 전송하여 경쟁 관계를 추론한다
  Given DB에 "건설기계" 섹터가 있고
  And 해당 섹터에 대창단조(id=10), 진성이엔씨(id=11), 현대제철(id=12) 종목이 등록되어 있고
  And Gemini AI가 다음 JSON 응답을 반환할 때:
    [{"stock_a_id": 10, "stock_b_id": 11, "confidence": 0.85, "reason": "두 기업 모두 포크레인 하부 구조물 생산"}]
  When infer_competitor_relations(db) 함수가 호출되면
  Then stock_relations에 source=10, target=11, type=competitor, confidence=0.85 행이 생성된다
  And stock_relations에 source=11, target=10, type=competitor, confidence=0.85 행이 생성된다
  And 양방향 관계 총 2개가 생성된다
  And AI 프롬프트에 하드코딩된 경쟁사 목록이 아닌 DB에서 조회한 종목 목록이 포함되어 있다
```

### TC-03: 경쟁사 악재 -> 반사이익 전파 (감성 역전)

**Feature**: Competitor news propagation with sentiment inversion

```gherkin
Scenario: 경쟁사의 부정 뉴스가 내 종목에 호재로 전파된다
  Given DB에 대창단조(stock_id=10)와 진성이엔씨(stock_id=11)가 있고
  And stock_relations에 source=대창단조, target=진성이엔씨, type=competitor 관계가 있고
  And "진성이엔씨 굴삭기 부품 라인 가동 중단" 기사가 sentiment='negative'로 분류되어
  And news_stock_relations에 news_id=100, stock_id=11, match_type='keyword' 관계가 생성되었을 때
  When propagate_news_relations() 함수가 호출되면
  Then news_stock_relations에 news_id=100, stock_id=10, match_type='propagated',
       relation_sentiment='positive', propagation_type='competitor' 행이 생성된다
  And impact_reason은 "경쟁사 진성이엔씨" 문자열을 포함한다
```

### TC-04: 공급망 수혜 전파 (감성 유지)

**Feature**: Supply chain news propagation with same sentiment

```gherkin
Scenario: 반도체 호황 뉴스가 반도체장비 섹터에 동일 감성으로 전파된다
  Given DB에 반도체(sector_id=1)와 반도체장비(sector_id=2) 섹터가 있고
  And stock_relations에 source_sector_id=2(반도체장비), target_sector_id=1(반도체), type=equipment 관계가 있고
  And "삼성전자 HBM 생산 설비 대폭 확대" 기사가 sector_id=1(반도체)에 sentiment='positive'로 분류될 때
  When propagate_news_relations() 함수가 호출되면
  Then news_stock_relations에 sector_id=2(반도체장비), match_type='propagated',
       relation_sentiment='positive', propagation_type='equipment' 행이 생성된다
  And impact_reason에 "장비" 또는 "수주" 문자열이 포함된다
```

### TC-05: 중복 전파 방지 - 이미 직접 매핑된 종목

**Feature**: Skip propagation when target already directly mapped

```gherkin
Scenario: 이미 직접 매핑된 종목에는 propagated 관계가 생성되지 않는다
  Given stock_relations에 source=대창단조(10), target=진성이엔씨(11), type=competitor 관계가 있고
  And 기사 news_id=300이 stock_id=10(대창단조)와 stock_id=11(진성이엔씨) 모두에 직접 매핑되어 있을 때
  When propagate_news_relations() 함수가 호출되면
  Then news_id=300, stock_id=10, match_type='propagated' 행이 생성되지 않는다
  And DB에 news_id=300에 대한 propagated 행의 수는 0이다
```

### TC-06: 프론트엔드 배지 - 간접호재 표시

**Feature**: Frontend badge display for propagated positive news

```gherkin
Scenario: propagated 긍정 뉴스 카드에 "간접호재" 배지가 표시된다
  Given 뉴스 API가 다음 데이터를 반환할 때:
    { matchType: 'propagated', relationSentiment: 'positive', impactReason: '경쟁사 악재로 반사이익' }
  When 뉴스 카드 컴포넌트가 렌더링되면
  Then "간접호재" 텍스트가 포함된 배지 요소가 DOM에 존재한다
  And 배지의 배경색이 연초록 계열이다
  And 배지에 마우스를 올리면 impactReason 텍스트가 툴팁으로 표시된다
```

### TC-07: 프론트엔드 배지 - 간접악재 표시

**Feature**: Frontend badge display for propagated negative news

```gherkin
Scenario: propagated 부정 뉴스 카드에 "간접악재" 배지가 표시된다
  Given 뉴스 API가 다음 데이터를 반환할 때:
    { matchType: 'propagated', relationSentiment: 'negative' }
  When 뉴스 카드 컴포넌트가 렌더링되면
  Then "간접악재" 텍스트가 포함된 배지 요소가 DOM에 존재한다
  And 배지의 배경색이 연빨강 계열이다
```

### TC-08: AI 신뢰도 필터링 - 0.6 미만 제외

**Feature**: Confidence threshold filtering

```gherkin
Scenario: 신뢰도 0.6 미만인 AI 추론 결과는 저장되지 않는다
  Given Gemini AI가 다음 응답을 반환할 때:
    [
      {"stock_a_id": 10, "stock_b_id": 12, "confidence": 0.4, "reason": "약한 연관"},
      {"stock_a_id": 10, "stock_b_id": 11, "confidence": 0.85, "reason": "강한 경쟁관계"}
    ]
  When infer_competitor_relations() 함수가 호출되면
  Then stock_relations에 stock_a_id=10, stock_b_id=12 관계는 저장되지 않는다
  And stock_relations에 stock_a_id=10, stock_b_id=11 관계는 양방향으로 저장된다
```

### TC-09: 중립 감성 유지 (competitor 관계)

**Feature**: Neutral sentiment preserved for competitor relations

```gherkin
Scenario: competitor 관계에서 중립 감성은 역전되지 않는다
  Given 기사가 sentiment='neutral'로 분류되고
  And 경쟁사 관계 전파 대상이 있을 때
  When propagate_news_relations() 함수가 호출되면
  Then propagated 관계의 relation_sentiment는 'neutral'이다
```

### TC-10: 앱 시작 자동 추론 트리거

**Feature**: Auto-inference on app startup

```gherkin
Scenario: stock_relations가 비어있을 때 앱 시작 시 자동으로 추론이 실행된다
  Given stock_relations 테이블이 비어있을 때
  When FastAPI 앱이 시작되면
  Then run_full_inference()가 호출된다
  And 로그에 "초기 관계 추론 실행" 또는 유사한 메시지가 기록된다
  And stock_relations 테이블에 최소 1개의 행이 생성된다
```

### TC-11: 관계 API 조회

**Feature**: Stock relations API endpoint

```gherkin
Scenario: GET /api/stocks/relations 엔드포인트가 정상 응답한다
  Given stock_relations 테이블에 관계 데이터가 있을 때
  When GET /api/stocks/relations?stock_id=10 요청을 보내면
  Then HTTP 200 응답이 반환된다
  And 응답 JSON에 "relations" 배열이 있다
  And 배열의 각 항목에 id, relation_type, confidence 필드가 있다
```

### TC-12: 수동 추론 트리거 API

**Feature**: Manual inference trigger API

```gherkin
Scenario: POST /api/stocks/infer-relations가 추론을 실행하고 결과를 반환한다
  Given 유효한 AI API 키가 설정되어 있을 때
  When POST /api/stocks/infer-relations 요청을 보내면
  Then HTTP 200 응답이 반환된다
  And 응답에 "status": "completed", "relations_created" (int) 필드가 있다
```

### TC-13: 관계 삭제 API

**Feature**: Relation deletion API

```gherkin
Scenario: DELETE /api/stocks/relations/{id}가 관계를 삭제한다
  Given stock_relations에 id=42인 관계가 있을 때
  When DELETE /api/stocks/relations/42 요청을 보내면
  Then HTTP 200 응답이 반환된다
  And stock_relations에 id=42인 행이 더 이상 존재하지 않는다
```

### TC-14: 경쟁사 호재 -> 나의 악재 전파

**Feature**: Competitor positive news inverts to negative

```gherkin
Scenario: 경쟁사의 긍정 뉴스가 내 종목에 위협으로 전파된다
  Given stock_relations에 source=대창단조, target=진성이엔씨, type=competitor 관계가 있고
  And "진성이엔씨 신규 수주 1000억 달성" 기사가 sentiment='positive'로 분류될 때
  When propagate_news_relations() 함수가 호출되면
  Then news_stock_relations에 stock_id=대창단조, match_type='propagated',
       relation_sentiment='negative', propagation_type='competitor' 행이 생성된다
```

### TC-15: 중복 관계 저장 방지

**Feature**: Duplicate relation prevention

```gherkin
Scenario: 이미 존재하는 관계는 중복으로 저장되지 않는다
  Given stock_relations에 source=10, target=11, type=competitor 관계가 이미 있을 때
  When run_full_inference()가 재실행되면
  Then 동일한 관계가 중복으로 생성되지 않는다
  And stock_relations 테이블의 해당 관계 수는 기존과 동일하다
```

### TC-16: AI 추론 실패 시 graceful skip

**Feature**: AI inference failure handling

```gherkin
Scenario: AI 응답 파싱 실패 시 해당 섹터를 스킵하고 다음으로 진행한다
  Given "건설기계" 섹터에 대해 AI가 잘못된 JSON을 반환할 때
  And "반도체" 섹터에 대해 AI가 정상 JSON을 반환할 때
  When infer_competitor_relations() 함수가 호출되면
  Then "건설기계" 섹터에 대한 에러가 로그에 기록된다
  And "반도체" 섹터의 관계는 정상적으로 저장된다
  And 전체 추론 프로세스가 중단되지 않는다
```

---

## Edge Cases

### EC-01: 종목 1개만 있는 섹터
경쟁사 추론에서 종목 2개 미만 섹터는 스킵되어야 한다.

### EC-02: AI 응답이 빈 배열
AI가 관계 없음으로 판단하여 `[]`을 반환하면, 해당 섹터에 대해 관계가 생성되지 않고 에러 없이 처리되어야 한다.

### EC-03: 전파 대상 종목이 삭제된 경우
`stock_relations`의 source/target이 삭제된 종목을 참조하면 CASCADE로 관계도 삭제되고, 전파 시 해당 관계가 조회되지 않아야 한다.

### EC-04: 동일 기사에 대한 전파 반복 호출
같은 기사에 대해 propagate가 두 번 호출되어도 중복 propagated 행이 생성되지 않아야 한다.

### EC-05: AI 응답에 존재하지 않는 ID
AI가 DB에 없는 stock_id나 sector_id를 반환하면 해당 항목을 스킵하고 유효한 항목만 저장해야 한다.

### EC-06: 감성이 NULL인 기사의 전파
원본 기사의 sentiment가 NULL이면 전파된 관계의 relation_sentiment도 NULL이어야 한다.

---

## 성능 기준 (Performance Criteria)

| 항목 | 기준 |
|------|------|
| 전체 AI 추론 시간 (Phase A + B) | 60초 이내 (섹터 20개, 종목 100개 기준) |
| 뉴스 1건 전파 처리 시간 | 100ms 이내 (DB 쿼리 + 행 생성) |
| 전파 관계 상한선 | 뉴스 1건당 최대 20개 propagated 관계 |
| API 응답 시간 | GET /api/stocks/relations - 200ms 이내 |

---

## 품질 게이트 (Quality Gates)

### 백엔드

| 항목 | 기준 |
|------|------|
| 새 모델 파일 테스트 | pytest 단위 테스트 존재 |
| stock_relation_service.py | AI 호출 mock으로 단위 테스트 |
| relation_propagator.py | compute_propagated_sentiment() 함수 단위 테스트 |
| Alembic 마이그레이션 | `alembic upgrade head` 오류 없이 성공 |
| 타입 힌트 | mypy/pyright 오류 없음 |
| 린팅 | ruff 경고 없음 |

### 프론트엔드

| 항목 | 기준 |
|------|------|
| TypeScript 컴파일 | `tsc --noEmit` 오류 없음 |
| 배지 컴포넌트 | 렌더링 테스트 존재 |
| API 함수 | 타입 안전 (any 사용 금지) |

### 통합

| 항목 | 기준 |
|------|------|
| 뉴스 크롤링 파이프라인 | 기존 키워드/AI 분류가 깨지지 않음 |
| 전파 후 뉴스 수 | 전파 전보다 뉴스 관계 수가 증가 |
| 전파 중복 없음 | 동일 news_id + stock_id 쌍의 propagated 행이 1개 이하 |

---

## Definition of Done

- [ ] `stock_relations` 테이블 생성 및 Alembic 마이그레이션 적용됨
- [ ] `news_stock_relations`에 3개 신규 컬럼 추가됨
- [ ] `stock_relation_service.py` 구현 완료 (Phase A: 섹터 간 AI 추론 + Phase B: 경쟁사 AI 추론)
- [ ] AI 추론이 **하드코딩 없이** DB 데이터 기반으로만 동작함
- [ ] `relation_propagator.py` 구현 완료 (전파 + 감성 변환)
- [ ] 뉴스 크롤링 파이프라인에 전파 단계 연결됨
- [ ] 관계 API 3개 엔드포인트 구현됨
- [ ] 앱 시작 시 자동 추론 트리거 동작 확인됨
- [ ] 주간 갱신 스케줄러 등록됨
- [ ] 프론트엔드 뉴스 카드에 간접호재/간접악재 배지 표시됨
- [ ] impact_reason 툴팁 표시됨
- [ ] 직접/간접 필터 UI 동작 확인됨
- [ ] TC-01 ~ TC-16 모두 통과
- [ ] Edge Cases EC-01 ~ EC-06 검증됨
- [ ] ruff 린팅 오류 없음
- [ ] TypeScript 컴파일 오류 없음
- [ ] OCI 서버에 배포 후 기능 동작 확인

---

## 수동 검증 체크리스트 (Deployment Verification)

배포 후 OCI 서버에서 다음을 확인:

```bash
# 1. stock_relations 테이블 존재 및 데이터 확인
psql -c "SELECT COUNT(*) FROM stock_relations;"

# 2. AI 추론 관계 확인 (하드코딩이 아닌 AI 생성)
psql -c "SELECT s1.name as source, s2.name as target, relation_type, confidence
         FROM stock_relations sr
         LEFT JOIN sectors s1 ON sr.source_sector_id = s1.id
         LEFT JOIN sectors s2 ON sr.target_sector_id = s2.id
         WHERE source_sector_id IS NOT NULL LIMIT 10;"

# 3. propagated 관계 생성 확인 (뉴스 수집 후)
psql -c "SELECT COUNT(*) FROM news_stock_relations WHERE match_type = 'propagated';"

# 4. API 엔드포인트 동작 확인
curl http://140.245.76.242:8000/api/stocks/relations?limit=5
```
