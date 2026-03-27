---
id: SPEC-RELATION-001
type: plan
version: "1.0.0"
created: "2026-03-27"
updated: "2026-03-27"
---

## HISTORY

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0.0 | 2026-03-27 | MoAI | Initial plan creation |

---

# SPEC-RELATION-001: 구현 계획

> TAG: SPEC-RELATION-001
> 관련 파일: backend/app/models/stock_relation.py, backend/app/services/stock_relation_service.py,
>            backend/app/services/relation_propagator.py, backend/app/routers/stocks.py,
>            frontend/src/components/ (뉴스 카드 관련 컴포넌트)

---

## 아키텍처 전략

기존 파이프라인을 최대한 보존하고 **후처리 단계**를 삽입하는 방식으로 구현:

```
[기존 파이프라인]
크롤러 -> URL 중복 제거 -> classify_news() -> DB 저장

[신규 파이프라인]
크롤러 -> URL 중복 제거 -> classify_news() -> propagate_news() -> DB 저장
```

`classify_news()`의 시그니처나 내부 로직을 변경하지 않고, 반환된 관계 목록을 `relation_propagator.py`에 전달하는 후처리 방식으로 기존 코드의 안정성을 유지한다.

## 주요 설계 결정

1. **단방향 그래프 탐색**: `stock_relations` 테이블의 방향은 "target이 뉴스를 받으면 source에 전파"로 고정. 탐색 쿼리는 단순 WHERE 조건으로 처리.
2. **AI 추론 배치 처리**: Phase A는 전체 섹터를 하나의 프롬프트에 묶어 단일 AI 호출. Phase B는 섹터별 1회 호출.
3. **Alembic 마이그레이션 분리**: `stock_relations` 신규 테이블과 `news_stock_relations` 컬럼 추가를 별도 마이그레이션으로 분리.
4. **동기 DB 세션 유지**: 기존 코드가 sync SQLAlchemy 세션을 사용하므로 신규 서비스도 동일 패턴 유지.
5. **하드코딩 금지**: 모든 관계를 AI가 DB 데이터 기반으로 추론. 시드 데이터 없음.

---

## Phase 1: DB 스키마 + 기본 전파 (Primary Goal)

### Task 1: StockRelation 모델 생성

**파일**: `backend/app/models/stock_relation.py` (신규)

StockRelation ORM 모델 생성:
- id, source_stock_id, source_sector_id, target_stock_id, target_sector_id
- relation_type, confidence, description, is_ai_inferred, created_at
- FK relationships to Stock, Sector
- CHECK constraints (source_not_all_null, target_not_all_null)

**파일**: `backend/app/models/__init__.py` - StockRelation import 추가

**의존성**: 없음

### Task 2: Alembic 마이그레이션

두 개의 마이그레이션 파일:

- **마이그레이션 1**: `stock_relations` 테이블 생성 + 인덱스 + UNIQUE constraint
- **마이그레이션 2**: `news_stock_relations`에 `relation_sentiment`, `propagation_type`, `impact_reason` 컬럼 추가

**의존성**: Task 1

### Task 3: NewsStockRelation 모델 업데이트

**파일**: `backend/app/models/news_relation.py`

추가 필드:
- `relation_sentiment: Mapped[str | None]` (positive/negative/neutral)
- `propagation_type: Mapped[str | None]` (competitor/supplier/equipment/material/customer)
- `impact_reason: Mapped[str | None]` (한국어 영향 설명)

`match_type` 허용 값 확장: 'keyword' | 'ai_classified' | 'propagated'

**의존성**: Task 2

### Task 4: StockRelationService 구현

**파일**: `backend/app/services/stock_relation_service.py` (신규)

핵심 함수:
- `infer_inter_sector_relations(db: Session) -> int`: Phase A - 전체 섹터 목록 AI 추론
- `infer_competitor_relations(db: Session) -> int`: Phase B - 섹터별 경쟁사 추론
- `run_full_inference(db: Session) -> dict`: 전체 관계 추론 실행 (Phase A + B)
- `should_run_inference(db: Session) -> bool`: stock_relations 테이블 비어있는지 확인

AI 프롬프트 설계:
- DB에서 동적으로 섹터/종목 목록 생성 (하드코딩 금지)
- 응답 파싱: `json.loads()` 후 confidence >= 0.6 필터링
- 실패 시 로그 출력 후 해당 섹터 스킵 (전체 중단 없음)

**의존성**: Task 1

### Task 5: RelationPropagator 구현

**파일**: `backend/app/services/relation_propagator.py` (신규)

핵심 함수:
- `propagate_news_relations(db, article, existing_relations) -> list[NewsStockRelation]`
- `compute_propagated_sentiment(original, relation_type) -> str | None`
- `generate_impact_reason(relation, article) -> str`

전파 알고리즘 최적화:
- 기사 1건 처리 시 관계 탐색은 최대 1번의 DB 쿼리 (WHERE IN 사용)
- 이미 직접 매핑된 stock/sector ID 집합을 먼저 수집 후 필터링
- 전파 관계 상한선: 뉴스 1건당 최대 20개

**의존성**: Task 1, Task 3

### Task 6: 파이프라인 연결

**파일**: `backend/app/services/news_crawler.py`

`classify_news()` 호출 이후 `propagate_news_relations()` 호출 추가:

```python
# 기존 코드 (변경 없음)
relations = classify_news(article, sectors, stocks, db)
db.add_all(relations)

# 신규 추가
propagated = propagate_news_relations(db, article, relations)
if propagated:
    db.add_all(propagated)

db.commit()
```

**의존성**: Task 5

---

## Phase 2: API + 스케줄러 (Secondary Goal)

### Task 7: 관계 API 엔드포인트

**파일**: `backend/app/routers/stocks.py`

추가할 엔드포인트:
- `GET /api/stocks/relations` - 관계 목록 조회 (stock_id, sector_id, relation_type 필터)
- `POST /api/stocks/infer-relations` - AI 추론 수동 트리거
- `DELETE /api/stocks/relations/{id}` - 관계 삭제

**파일**: `backend/app/schemas/stock_relation.py` (신규) - Pydantic 응답 스키마

**의존성**: Task 4

### Task 8: 앱 시작 자동 추론

**파일**: `backend/app/main.py`

lifespan 함수에 추가:
- `should_run_inference()` 확인
- 비어있으면 `run_full_inference()` 실행

**의존성**: Task 4

### Task 9: 주간 갱신 스케줄러

**파일**: `backend/app/services/scheduler.py`

APScheduler에 주간 작업 추가:
- CronTrigger(day_of_week="sun", hour=2)
- 신규 종목에 대해서만 증분 추론 실행

**의존성**: Task 4

---

## Phase 3: 프론트엔드 (Final Goal)

### Task 10: API 응답 스키마 업데이트

**파일**: `backend/app/schemas/news.py` - 신규 필드 추가
**파일**: `backend/app/routers/utils.py` - `format_articles()` 업데이트

**의존성**: Task 3

### Task 11: 뉴스 카드 배지

**파일**: `frontend/src/components/` (기존 뉴스 카드 컴포넌트)

배지 로직:
- match_type='propagated' AND sentiment='positive' -> "간접호재" (연초록)
- match_type='propagated' AND sentiment='negative' -> "간접악재" (연빨강)
- 직접 뉴스 배지는 기존 유지

**의존성**: Task 10

### Task 12: 직접/간접 필터 UI + API 함수

**파일**: `frontend/src/app/stocks/[id]/page.tsx` - 필터 상태 관리
**파일**: `frontend/src/lib/api.ts` - 관계 API 함수 추가

**의존성**: Task 11

---

## Phase 4: 관리 페이지 (Optional Goal)

### Task 13: AI 관계 뷰 + 삭제 기능

**파일**: `frontend/src/app/manage/page.tsx`

- AI 추론 관계 목록 테이블
- 관계 유형 필터
- "잘못된 관계" 삭제 버튼

**의존성**: Task 7, Task 12

---

## 리스크 및 대응 방안

| 리스크 | 가능성 | 대응 |
|--------|--------|------|
| Gemini free tier 속도 제한 | 높음 | 섹터별 순차 처리 + 1초 딜레이, 실패 시 해당 섹터 스킵 |
| AI 응답 JSON 파싱 실패 | 중간 | try/except로 포착, 로그 기록 후 스킵 |
| 전파 생성 시 성능 저하 | 낮음 | batch insert 사용, 뉴스 1건당 전파 관계 상한선 20개 |
| 잘못된 경쟁사 추론 | 중간 | confidence 임계값 0.6, 사용자 삭제 기능 제공 |
| AI가 하드코딩보다 부정확 | 중간 | confidence threshold로 저품질 결과 필터, 수동 트리거로 재추론 가능 |

---

## 파일 변경 요약

### 신규 파일

| 파일 | 설명 |
|------|------|
| `backend/app/models/stock_relation.py` | StockRelation ORM 모델 |
| `backend/app/services/stock_relation_service.py` | AI 추론 서비스 (Phase A + B) |
| `backend/app/services/relation_propagator.py` | 뉴스 전파 엔진 |
| `backend/app/schemas/stock_relation.py` | Pydantic 응답 스키마 |
| `backend/alembic/versions/xxx_add_stock_relations.py` | Alembic 마이그레이션 1 |
| `backend/alembic/versions/xxx_add_propagation_fields.py` | Alembic 마이그레이션 2 |

### 수정 파일

| 파일 | 변경 내용 |
|------|-----------|
| `backend/app/models/news_relation.py` | 3개 컬럼 추가 |
| `backend/app/models/__init__.py` | StockRelation import |
| `backend/app/services/news_crawler.py` | propagate_news_relations() 호출 추가 |
| `backend/app/services/scheduler.py` | 주간 갱신 작업 추가 |
| `backend/app/routers/stocks.py` | 관계 API 3개 엔드포인트 추가 |
| `backend/app/schemas/news.py` | 신규 필드 추가 |
| `backend/app/routers/utils.py` | format_articles() 업데이트 |
| `backend/app/main.py` | lifespan에 초기 추론 트리거 |
| `frontend/src/components/` (뉴스 카드) | 배지 시스템 추가 |
| `frontend/src/app/stocks/[id]/page.tsx` | 필터 UI 추가 |
| `frontend/src/lib/api.ts` | 관계 API 함수 추가 |
