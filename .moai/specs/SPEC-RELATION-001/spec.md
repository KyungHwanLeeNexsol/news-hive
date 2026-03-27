---
id: SPEC-RELATION-001
version: "1.0.0"
status: draft
created: "2026-03-27"
updated: "2026-03-27"
author: MoAI
priority: high
issue_number: 0
---

## HISTORY

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0.0 | 2026-03-27 | MoAI | Initial SPEC creation |

---

## 1. 개요 (Overview)

### 문제 정의

현재 NewsHive의 뉴스-종목 매핑 시스템(`news_stock_relations`)은 직접 언급 기반(keyword/ai_classified)만 지원한다. 투자자에게 진짜 중요한 뉴스는 **간접 영향**에 있다:

- **경쟁 대체 효과**: 경쟁사 B가 생산 중단 -> A에게는 호재 (시장 점유율 확대 기회)
- **공급망 수혜**: 반도체 호황 -> 반도체장비, 반도체부품/소재 기업도 수혜

현재 시스템은 이 두 가지 간접 전파 메커니즘이 없어 투자자가 중요한 뉴스를 놓친다.

### 목표

1. AI(Gemini)가 종목 간 관계(경쟁사, 공급망, 고객사, 장비/소재 공급사)를 **DB 데이터 기반으로 자동 추론**하는 시스템 구축 (하드코딩 없음)
2. 뉴스 분류 이후 관계 그래프를 탐색하여 간접 영향 종목에 뉴스를 전파
3. 전파된 뉴스에 맥락에 맞는 감성(호재/악재)을 역전 또는 유지하는 로직 구현
4. 프론트엔드에서 "왜 이 뉴스가 여기에?" 이유를 사용자에게 명확히 표시

### 범위

- Backend: 신규 테이블, AI 추론 서비스, 전파 엔진, API 엔드포인트
- Frontend: 뉴스 카드 배지, 필터 UI, impact_reason 툴팁
- Scheduler: 주간 관계 갱신 작업

---

## 2. 사용자 시나리오 (User Scenarios)

### 시나리오 1: 경쟁사 악재로 반사이익 포착

대창단조에 투자 중인 투자자가 종목 상세 페이지를 확인한다. 경쟁사인 진성이엔씨의 "굴삭기 부품 라인 가동 중단" 뉴스가 대창단조 피드에 "간접호재" 배지와 함께 나타난다. 배지에 마우스를 올리면 "경쟁사 진성이엔씨의 생산 중단으로 대창단조의 시장 점유율 확대 기대"라는 설명이 표시된다. 투자자는 반사이익 기회를 놓치지 않고 즉시 대응할 수 있다.

### 시나리오 2: 산업 호황으로 공급망 전체 수혜 발견

"삼성전자 HBM 생산 설비 대폭 확대" 뉴스가 반도체 섹터에 분류된다. AI가 추론한 섹터 간 관계(반도체 -> 반도체장비: equipment)를 통해, 반도체장비 섹터의 종목 피드에도 동일 뉴스가 "간접호재"로 전파된다. 반도체장비 종목에 투자 중인 투자자는 수혜 뉴스를 별도 검색 없이 자동으로 받아볼 수 있다.

---

## 3. 기술 스택 및 가정 (Tech Stack & Assumptions)

### 기술 환경

- **Backend**: Python 3.11+, FastAPI, SQLAlchemy 2.0 (sync session), Alembic
- **AI**: `ask_ai(prompt)` 함수 사용 (`backend/app/services/ai_client.py` - Groq primary -> Gemini-1/2/3 fallback)
- **DB**: PostgreSQL 16 (docker-compose), OCI VM 배포
- **Scheduler**: APScheduler (기존 `scheduler.py`에 주간 작업 추가)
- **Frontend**: Next.js (App Router), TypeScript, Tailwind CSS v4

### 가정 (Assumptions)

- `ask_ai()` 함수는 `backend/app/services/ai_client.py`에 이미 구현되어 있음
- 기존 `ai_classifier.py`의 `classify_news()` 함수 출력을 수정하지 않고 **후처리 단계를 추가**
- 섹터 간, 섹터 내 **모든 관계를 Gemini AI가 DB 섹터 목록 기반으로 자동 추론** (하드코딩된 관계 목록 없음)
- free tier AI 사용으로 배치 크기와 호출 횟수 최소화 필요
- 기존 뉴스 크롤링 파이프라인의 동작을 변경하지 않음

### 제약 사항

- AI 추론은 앱 시작 시 `stock_relations` 테이블이 비어있을 때만 전체 실행 (비용 절감)
- 주간 갱신은 신규 종목만 증분 처리
- 관계 신뢰도 0.6 미만은 저장하지 않음
- 전파된 뉴스는 원본 관계의 중복을 피해야 함 (동일 종목이 이미 직접 매핑된 경우 전파 스킵)

---

## 4. 기술 요구사항 (Technical Requirements, EARS Format)

### R-DM: 데이터 모델 요구사항

**R-DM-01 (Ubiquitous)**
시스템은 종목/섹터 간 방향성 관계를 저장하는 `stock_relations` 테이블을 항상 유지해야 한다.
> The system shall always maintain the `stock_relations` table storing directed relationships between stocks and sectors.

**R-DM-02 (Event-Driven)**
WHEN 새 종목이 등록되면 THEN 시스템은 해당 종목이 속한 섹터의 관계 추론 작업을 스케줄에 등록해야 한다.

**R-DM-03 (State-Driven)**
IF `stock_relations` 테이블이 비어있으면 THEN 앱 시작 시 초기 관계 추론을 전체 실행해야 한다.

**R-DM-04 (Unwanted)**
시스템은 신뢰도(confidence) 0.6 미만인 AI 추론 관계를 저장하지 않아야 한다.

**R-DM-05 (Unwanted)**
시스템은 source_stock_id, source_sector_id, target_stock_id, target_sector_id가 모두 NULL인 관계를 허용하지 않아야 한다.

### R-AI: AI 추론 서비스 요구사항

**R-AI-01 (Event-Driven)**
WHEN `stock_relations` 테이블이 비어있거나 `POST /api/stocks/infer-relations` 요청이 오면 THEN 시스템은 **DB에서 전체 섹터 목록을 조회**하여 Gemini AI에게 **한 번의 배치 프롬프트로 전송**하고, 섹터 간 공급망/설비/소재/고객사 관계를 자동 추론해야 한다. (하드코딩된 관계 목록 사용 금지)

**R-AI-02 (Event-Driven)**
WHEN 섹터에 2개 이상의 종목이 있으면 THEN 시스템은 **해당 섹터의 종목 목록을 Gemini AI에게 전송**하여 섹터 내 경쟁 관계를 추론해야 한다. (하드코딩된 경쟁사 목록 사용 금지)

**R-AI-03 (Event-Driven)**
WHEN AI 경쟁사 추론 응답을 파싱하면 THEN 시스템은 bidirectional 경쟁 관계(A->B, B->A)를 모두 저장해야 한다.

**R-AI-04 (Unwanted)**
시스템은 이미 존재하는 관계(source_id + target_id + relation_type 조합)를 중복으로 저장하지 않아야 한다.

**R-AI-05 (Ubiquitous)**
시스템은 AI 추론 실패 시 해당 섹터를 스킵하고 다음 섹터로 진행해야 한다. 전체 추론 프로세스가 단일 섹터 실패로 중단되지 않아야 한다.

### R-NC: 뉴스 분류 및 전파 요구사항

**R-NC-01 (Ubiquitous)**
시스템은 `news_stock_relations`의 모든 행에 대해 `relation_sentiment` 필드를 지원해야 한다.

**R-NC-02 (Event-Driven)**
WHEN `classify_news()`가 뉴스 기사의 관계를 생성하면 THEN 시스템은 `stock_relations` 그래프를 탐색하여 간접 영향 종목/섹터에 뉴스를 전파해야 한다.

**R-NC-03 (State-Driven)**
IF 전파 대상 종목이 이미 동일 뉴스에 대한 직접 매핑(match_type='keyword' 또는 'ai_classified')을 가지고 있으면 THEN 전파를 스킵해야 한다.

**R-NC-04 (State-Driven)**
IF 관계 유형이 'competitor'이면 THEN 전파된 감성은 원본 기사 감성의 반대여야 한다 (positive<->negative, neutral은 유지).

**R-NC-05 (State-Driven)**
IF 관계 유형이 'supplier', 'customer', 'equipment', 'material' 중 하나이면 THEN 전파된 감성은 원본 기사 감성과 동일해야 한다.

**R-NC-06 (Optional)**
가능하면 전파된 각 관계에 AI 생성 또는 템플릿 기반 `impact_reason` 텍스트를 제공해야 한다.

### R-API: API 요구사항

**R-API-01 (Ubiquitous)**
시스템은 종목/섹터별 관계 목록을 조회할 수 있는 `GET /api/stocks/relations` 엔드포인트를 제공해야 한다.

**R-API-02 (Event-Driven)**
WHEN `POST /api/stocks/infer-relations` 요청을 받으면 THEN 시스템은 AI 관계 추론 작업을 즉시 실행해야 한다.

**R-API-03 (Event-Driven)**
WHEN `DELETE /api/stocks/relations/{id}` 요청을 받으면 THEN 시스템은 해당 관계를 삭제해야 한다.

### R-FE: 프론트엔드 요구사항

**R-FE-01 (Ubiquitous)**
시스템은 뉴스 카드에서 `relation_sentiment` 값을 기준으로 감성 배지를 항상 표시해야 한다 (없으면 기사 원본 감성 fallback).

**R-FE-02 (State-Driven)**
IF 뉴스 관계의 `match_type`이 'propagated'이면 THEN "간접호재" 또는 "간접악재" 배지를 표시해야 한다.

**R-FE-03 (Optional)**
가능하면 간접 뉴스 관계에 `impact_reason` 툴팁을 제공해야 한다.

**R-FE-04 (Optional)**
가능하면 종목 상세 페이지에서 "직접뉴스만"/"간접뉴스포함" 필터를 제공해야 한다.

---

## 5. DB 스키마 변경

### 5.1 신규 테이블: `stock_relations`

```sql
CREATE TABLE stock_relations (
    id              SERIAL PRIMARY KEY,
    source_stock_id  INTEGER REFERENCES stocks(id) ON DELETE CASCADE,
    source_sector_id INTEGER REFERENCES sectors(id) ON DELETE CASCADE,
    target_stock_id  INTEGER REFERENCES stocks(id) ON DELETE CASCADE,
    target_sector_id INTEGER REFERENCES sectors(id) ON DELETE CASCADE,
    relation_type    VARCHAR(20) NOT NULL,  -- 'competitor' | 'supplier' | 'customer' | 'equipment' | 'material'
    confidence       FLOAT NOT NULL DEFAULT 1.0,  -- 0.0 ~ 1.0
    description      TEXT,  -- AI 생성 설명
    is_ai_inferred   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    CONSTRAINT source_not_all_null CHECK (
        source_stock_id IS NOT NULL OR source_sector_id IS NOT NULL
    ),
    CONSTRAINT target_not_all_null CHECK (
        target_stock_id IS NOT NULL OR target_sector_id IS NOT NULL
    )
);

CREATE INDEX idx_stock_relations_target_stock ON stock_relations(target_stock_id);
CREATE INDEX idx_stock_relations_target_sector ON stock_relations(target_sector_id);
CREATE INDEX idx_stock_relations_source_stock ON stock_relations(source_stock_id);
CREATE UNIQUE INDEX idx_stock_relations_unique ON stock_relations(
    COALESCE(source_stock_id, -1),
    COALESCE(source_sector_id, -1),
    COALESCE(target_stock_id, -1),
    COALESCE(target_sector_id, -1),
    relation_type
);
```

**관계 방향성 의미**: `target`이 뉴스를 받은 종목/섹터, `source`가 전파 수혜 종목/섹터.
"target에 뉴스가 생기면 source에게 전파한다"는 의미.

**예시**:
- 경쟁사 관계: target=진성이엔씨, source=대창단조, type=competitor
  -> 진성이엔씨 뉴스 발생 시, 대창단조에게 반전 감성으로 전파
- 공급망 관계: target=반도체(섹터), source=반도체장비(섹터), type=equipment
  -> 반도체 섹터 뉴스 발생 시, 반도체장비 섹터에게 동일 감성으로 전파

### 5.2 기존 테이블 변경: `news_stock_relations`

추가 컬럼:

```sql
ALTER TABLE news_stock_relations
    ADD COLUMN relation_sentiment  VARCHAR(10),  -- 'positive' | 'negative' | 'neutral' | NULL
    ADD COLUMN propagation_type    VARCHAR(20),  -- NULL | 'competitor' | 'supplier' | 'customer' | 'equipment' | 'material'
    ADD COLUMN impact_reason       TEXT;         -- 전파 이유 설명 (한국어)
```

`match_type` 값 확장: 기존 'keyword' | 'ai_classified' 외에 **'propagated'** 추가

### 5.3 SQLAlchemy 모델 변경

| 파일 | 변경 유형 |
|------|-----------|
| `backend/app/models/news_relation.py` | 3개 컬럼 추가 (relation_sentiment, propagation_type, impact_reason) |
| `backend/app/models/stock_relation.py` | 신규 모델 생성 (StockRelation) |
| `backend/app/models/__init__.py` | StockRelation import 추가 |

---

## 6. AI 추론 사양 (AI Inference Specification)

### 6.1 Phase A: 섹터 간 관계 추론 (Inter-Sector Inference)

DB에 등록된 **전체 섹터 목록**을 한 번에 Gemini AI에 전송하여 섹터 간 공급망/설비/소재/고객사 관계를 자동 추론한다. **하드코딩된 관계 목록을 사용하지 않는다.**

**INTER_SECTOR_INFERENCE_PROMPT 설계**:

```
당신은 한국 주식 시장 전문가입니다.
아래 섹터 목록을 보고, 섹터 간 공급망/설비/소재/고객사 관계가 있는 쌍을 찾아주세요.

섹터 목록:
{sector_list}  -- DB에서 동적으로 생성: "- 반도체 (id=1)\n- 반도체장비 (id=2)\n..."

관계 유형:
- equipment: target 섹터가 source 섹터의 생산설비를 공급
- material: target 섹터가 source 섹터의 원자재/부품을 공급
- supplier: target 섹터가 source 섹터의 중간재를 공급
- customer: target 섹터가 source 섹터의 주요 고객

신뢰도 0.6 미만이거나 확실하지 않은 쌍은 포함하지 마세요.

응답 형식 (JSON 배열):
[{"source_sector_id": <int>, "target_sector_id": <int>,
  "relation_type": "equipment|material|supplier|customer",
  "confidence": 0.9, "reason": "설명"}]
```

**실행 조건**: 앱 시작 시 `stock_relations`에 섹터 간 관계가 없을 때 1회 실행. 이후 주간 갱신 시 신규 섹터만 증분 처리.

### 6.2 Phase B: 섹터 내 경쟁사 추론 (Intra-Sector Competitor Inference)

각 섹터별로 종목 목록을 AI에 전송하여 경쟁 관계를 추론한다. **하드코딩된 경쟁사 목록을 사용하지 않는다.**

**COMPETITOR_INFERENCE_PROMPT 설계**:

```
당신은 한국 주식 시장 전문가입니다.
아래 섹터에 속한 기업들 중 직접 경쟁 관계인 쌍을 찾아주세요.

섹터: {sector_name}
기업 목록:
{stock_list}  -- DB에서 동적으로 생성: "- 대창단조 (015230)\n- 진성이엔씨 (036890)\n..."

응답 형식 (JSON 배열):
[{"stock_a_id": <int>, "stock_b_id": <int>,
  "confidence": 0.85, "reason": "두 기업 모두 포크레인 하부 구조물을 생산하는 직접 경쟁사"}]
```

**실행 조건**: 종목 2개 미만 섹터는 스킵. 섹터별 순차 처리.

### 6.3 추론 실행 흐름

```
앱 시작 / POST /api/stocks/infer-relations
  |
  v
1. stock_relations 테이블 비어있는지 확인 (앱 시작 시만)
  |
  v
2. Phase A: 섹터 간 AI 추론
   - sectors 테이블 전체 조회 -> sector_list 구성
   - ask_ai(INTER_SECTOR_INFERENCE_PROMPT) 호출 (1회)
   - JSON 파싱, confidence >= 0.6 필터링
   - sector_id 기반 INSERT (ON CONFLICT DO NOTHING)
  |
  v
3. Phase B: 섹터 내 경쟁사 추론 (섹터별 순차)
   - 종목 2개 미만 섹터 스킵
   - ask_ai(COMPETITOR_INFERENCE_PROMPT) 호출 (섹터당 1회)
   - JSON 파싱, confidence >= 0.6 필터링
   - A->B, B->A 양방향 INSERT
  |
  v
4. 완료 로그 출력 (섹터 간 N건, 섹터 내 M건 저장)
```

---

## 7. 전파 로직 사양 (Propagation Logic Specification)

### 7.1 전파 엔진 위치

신규 파일: `backend/app/services/relation_propagator.py`

기존 `classify_news()` 반환 후 호출되는 후처리 함수로 구현.

### 7.2 전파 알고리즘

```
입력: 방금 생성된 NewsStockRelation 리스트 (뉴스 1건에 대한 직접 매핑)
출력: 추가로 생성된 NewsStockRelation 리스트 (propagated)

For each relation in direct_relations:
    target = relation.stock_id OR relation.sector_id

    # stock_relations WHERE target_* = target 조회
    propagation_targets = query(
        stock_relations
        WHERE (target_stock_id = target OR target_sector_id = target)
    )

    For each prop_target in propagation_targets:
        source = prop_target.source_stock_id OR prop_target.source_sector_id

        # 이미 해당 뉴스에 직접 매핑되어 있으면 스킵
        IF source already in direct_relations:
            CONTINUE

        # 감성 계산
        propagated_sentiment = compute_sentiment(
            original=article_sentiment,
            relation_type=prop_target.relation_type
        )

        # 새 관계 생성
        new_relation = NewsStockRelation(
            news_id=article.id,
            stock_id=source if is_stock else None,
            sector_id=source if is_sector else None,
            match_type='propagated',
            relevance='indirect',
            relation_sentiment=propagated_sentiment,
            propagation_type=prop_target.relation_type,
            impact_reason=generate_impact_reason(...)
        )
```

### 7.3 감성 변환 규칙

| relation_type | 원본 감성 | 전파 감성 | 이유 |
|---------------|-----------|-----------|------|
| competitor | positive | negative | 경쟁사가 잘 되면 나는 위협 |
| competitor | negative | positive | 경쟁사가 어려우면 나는 반사이익 |
| competitor | neutral | neutral | 중립은 유지 |
| supplier | positive | positive | 고객사 호황 = 공급사도 수혜 |
| supplier | negative | negative | 고객사 부진 = 공급사도 타격 |
| customer | positive | positive | 고객 증가 = 수요 증가 |
| customer | negative | negative | 고객 감소 = 수요 감소 |
| equipment | positive | positive | 산업 호황 = 장비 수요 증가 |
| equipment | negative | negative | 산업 침체 = 장비 수요 감소 |
| material | positive | positive | 생산 증가 = 소재 수요 증가 |
| material | negative | negative | 생산 감소 = 소재 수요 감소 |

### 7.4 impact_reason 템플릿

```python
IMPACT_REASON_TEMPLATES = {
    "competitor_positive": "{target_name}의 호재로 인해 경쟁사 {source_name}에게 위협 요인",
    "competitor_negative": "{target_name}의 악재로 경쟁사 {source_name}에게 반사이익 기대",
    "supplier_positive": "{target_name} 관련 호재로 공급사 {source_name}의 수요 증가 예상",
    "supplier_negative": "{target_name}의 부진으로 공급사 {source_name}의 수요 감소 우려",
    "equipment_positive": "{target_name} 섹터 호황으로 장비업체 {source_name}의 수주 증가 기대",
    "equipment_negative": "{target_name} 섹터 침체로 장비업체 {source_name}의 수주 감소 우려",
    "material_positive": "{target_name} 생산 확대로 소재/부품 업체 {source_name}의 수혜 예상",
    "material_negative": "{target_name} 생산 축소로 소재/부품 업체 {source_name}의 타격 우려",
    "customer_positive": "{target_name} 고객사 호조로 {source_name}의 매출 증가 기대",
    "customer_negative": "{target_name} 고객사 부진으로 {source_name}의 매출 감소 우려",
}
```
