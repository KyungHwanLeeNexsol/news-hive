---
id: SPEC-NEWS-001
version: "1.0.0"
status: completed
created: "2026-03-26"
updated: "2026-03-26"
author: MoAI
priority: high
issue_number: 0
---

# SPEC-NEWS-001: 뉴스-가격 반응 추적 시스템

## HISTORY

| 버전  | 날짜       | 작성자 | 변경 내용           |
| ----- | ---------- | ------ | ------------------- |
| 1.0.0 | 2026-03-26 | MoAI   | 초기 SPEC 문서 작성 |

---

## 1. 개요

뉴스 발생 시점의 주가를 스냅샷으로 저장하고, T+1D / T+5D 후 가격 변화를 추적하여 "이 유형의 뉴스 이후 평균 X% 수익, 승률 Y%" 형태의 데이터 기반 통계를 축적하는 시스템.

### 1.1 배경

- 현재 뉴스 수집 및 AI 분류 파이프라인은 완료 상태 (Phase 5까지 구현)
- `FundSignal` 모델 + `signal_verifier.py`에 동일한 가격 추적 패턴이 이미 존재
- 뉴스와 주가 반응 간 상관관계 데이터가 없어 투자 판단의 근거가 부족

### 1.2 목표

- 뉴스 발생 시점 기준 주가 스냅샷 자동 캡처
- T+1D, T+5D 시점의 가격 변화율 자동 백필
- 종목별 뉴스 패턴 통계 (평균 수익률, 승률) 제공
- 데일리 브리핑 AI 프롬프트에 통계 데이터 통합

---

## 2. 환경 (Environment)

### 2.1 시스템 환경

- **Backend**: Python 3.11+ / FastAPI / SQLAlchemy 2.0 (async)
- **Database**: PostgreSQL 16 (docker-compose)
- **스케줄러**: APScheduler (기존 18:00 KST signal_verification job 존재)
- **가격 데이터 소스**: `naver_finance.fetch_stock_fundamentals_batch()` (50종목/요청, 5분 캐시)
- **AI 분류**: Anthropic Claude API (기존 뉴스 분류 파이프라인)

### 2.2 기존 참조 구현

- `backend/app/models/fund_signal.py` - 유사한 가격 추적 모델 패턴
- `backend/app/services/signal_verifier.py` - 가격 검증 스케줄러 로직
- `backend/app/services/news_crawler.py` - 뉴스 수집 파이프라인 (Phase 5 주입 지점)
- `backend/app/services/scheduler.py` - APScheduler cron 패턴

### 2.3 제약 조건

- 7일 뉴스 삭제 정책이 존재 → `news_price_impact` 테이블은 독립 보존 필요
- 가격 API 호출은 50종목/요청 제한, 5분 캐시 적용
- 시장 운영 시간(09:00-15:30 KST) 외에도 스냅샷 캡처 수행 (장외 가격 기준)

---

## 3. 가정 (Assumptions)

- A1: `naver_finance.fetch_stock_fundamentals_batch()` API는 장외 시간에도 마지막 체결가를 반환한다
- A2: 뉴스-종목 관계(`news_stock_relations`)에서 `stock_id`가 있는 레코드만 가격 추적 대상이다
- A3: 1D/5D 백필은 영업일 기준이 아닌 캘린더 기준으로 계산한다
- A4: 기존 `FundSignal` 가격 추적 패턴을 그대로 차용할 수 있다
- A5: 뉴스 기사 삭제 후에도 impact 레코드의 통계적 가치는 유지된다

---

## 4. 요구사항 (Requirements) - EARS 형식

### Module 1: 초기 가격 스냅샷 캡처

**REQ-NPI-001 [Ubiquitous]**
시스템은 **항상** 새 뉴스 기사가 DB에 저장되고 `news_stock_relations`가 생성된 후, 연관 종목의 현재가를 즉시 스냅샷으로 캡처해야 한다.

**REQ-NPI-002 [Event-Driven]**
**WHEN** 스케줄러 뉴스 크롤링 작업이 완료되어 1개 이상의 새 기사가 저장될 때, **THEN** 시스템은 해당 기사들의 연관 종목에 대해 `news_price_impact` 레코드를 생성하고 `price_at_news` 필드에 현재가를 기록해야 한다.

**REQ-NPI-003 [State-Driven]**
**IF** 시장 운영 시간(09:00-15:30 KST) 외의 시간이라도 **THEN** 시스템은 가격 스냅샷 캡처를 정상적으로 수행해야 한다 (마지막 체결가 기준).

**REQ-NPI-004 [Unwanted Behavior]**
**IF** 특정 종목의 가격 API 호출이 실패하면, **THEN** 시스템은 해당 종목의 스냅샷을 건너뛰고 나머지 종목의 캡처를 계속 처리해야 한다. 시스템은 단일 종목의 API 실패로 전체 캡처 프로세스를 중단**하지 않아야 한다**.

**REQ-NPI-005 [Conditional]**
**IF** `news_stock_relations` 레코드에 `stock_id`가 있는 경우에만 **THEN** 시스템은 가격 스냅샷을 생성해야 한다. `sector_id`만 있고 `stock_id`가 null인 관계에 대해서는 스냅샷을 생성하지 않아야 한다.

---

### Module 2: 가격 반응 백필 (1D/5D)

**REQ-NPI-006 [Event-Driven]**
**WHEN** 매일 18:30 KST에 스케줄러가 실행될 때, **THEN** 시스템은 미완료 상태의 `news_price_impact` 레코드에 대해 가격 반응 데이터를 업데이트해야 한다.

**REQ-NPI-007 [State-Driven]**
**IF** 스냅샷 생성일로부터 1일이 경과한 레코드의 `price_after_1d`가 null인 상태라면, **THEN** 시스템은 해당 종목의 현재가를 조회하여 `price_after_1d`와 `return_1d_pct`를 업데이트해야 한다.

**REQ-NPI-008 [State-Driven]**
**IF** 스냅샷 생성일로부터 5일이 경과한 레코드의 `price_after_5d`가 null인 상태라면, **THEN** 시스템은 해당 종목의 현재가를 조회하여 `price_after_5d`와 `return_5d_pct`를 업데이트해야 한다.

**REQ-NPI-009 [Unwanted Behavior]**
**IF** 백필 중 주가 API 호출이 실패하면, **THEN** 시스템은 최대 3회 재시도 후에도 실패 시 해당 필드를 null로 유지해야 한다. 시스템은 재시도 실패로 인해 다른 레코드의 백필을 중단**하지 않아야 한다**.

---

### Module 3: 뉴스 패턴 통계 API

**REQ-NPI-010 [Ubiquitous]**
시스템은 **항상** `GET /api/news/{id}/impact` 엔드포인트를 통해 해당 뉴스 기사의 가격 반응 데이터(스냅샷 가격, 1D/5D 변화율)를 반환해야 한다.

**REQ-NPI-011 [Ubiquitous]**
시스템은 **항상** `GET /api/stocks/{id}/news-impact-stats` 엔드포인트를 통해 해당 종목의 뉴스 패턴별 통계(평균 수익률, 승률, 표본 수)를 반환해야 한다.

**REQ-NPI-012 [Event-Driven]**
**WHEN** 클라이언트가 종목 상세 페이지를 조회할 때, **THEN** 프론트엔드는 자동으로 `news-impact-stats` API를 호출하여 최근 30일 뉴스 패턴 통계를 로드해야 한다.

**REQ-NPI-013 [State-Driven]**
**IF** 해당 종목에 대한 완료된 impact 레코드가 0건인 상태라면, **THEN** 통계 API는 빈 통계 객체를 반환하고 "데이터 부족" 상태를 표시해야 한다.

---

### Module 4: 데일리 브리핑 통계 강화

**REQ-NPI-014 [Event-Driven]**
**WHEN** 매일 08:30 KST 데일리 브리핑 생성 시, **THEN** 시스템은 각 추천 종목의 최근 30일 뉴스 패턴 통계를 AI 프롬프트에 포함하여 브리핑 품질을 향상해야 한다.

**REQ-NPI-015 [State-Driven]**
**IF** 특정 종목에 대한 뉴스 패턴 통계가 없는 상태라면, **THEN** 시스템은 해당 종목의 통계 섹션을 브리핑 프롬프트에서 생략해야 한다.

---

### Module 5: 데이터 보존 정책

**REQ-NPI-016 [Ubiquitous]**
시스템은 **항상** `news_price_impact` 레코드를 90일간 보존해야 한다. 90일 경과 후 자동 삭제한다.

**REQ-NPI-017 [Ubiquitous]**
시스템은 **항상** 뉴스 기사가 7일 후 삭제되더라도 `news_price_impact` 레코드를 유지해야 한다. FK 관계는 `SET NULL`로 설정하여 뉴스 삭제 시 `news_id`가 null이 되지만 레코드 자체는 보존된다.

---

## 5. 사양 (Specifications)

### 5.1 데이터 모델: `NewsPriceImpact`

| 컬럼명            | 타입          | 제약 조건                      | 설명                         |
| ----------------- | ------------- | ------------------------------ | ---------------------------- |
| id                | SERIAL        | PK                             | 고유 ID                      |
| news_id           | INTEGER       | FK → news_articles, SET NULL   | 뉴스 기사 ID (삭제 시 null)  |
| stock_id          | INTEGER       | FK → stocks, NOT NULL          | 종목 ID                      |
| relation_id       | INTEGER       | FK → news_stock_relations, SET NULL | 뉴스-종목 관계 ID       |
| price_at_news     | FLOAT         | NOT NULL                       | 뉴스 발생 시점 주가          |
| price_after_1d    | FLOAT         | NULLABLE                       | 1일 후 주가                  |
| price_after_5d    | FLOAT         | NULLABLE                       | 5일 후 주가                  |
| return_1d_pct     | FLOAT         | NULLABLE                       | 1일 수익률 (%)               |
| return_5d_pct     | FLOAT         | NULLABLE                       | 5일 수익률 (%)               |
| captured_at       | TIMESTAMP     | NOT NULL, DEFAULT now()        | 스냅샷 캡처 시각             |
| backfill_1d_at    | TIMESTAMP     | NULLABLE                       | 1D 백필 완료 시각            |
| backfill_5d_at    | TIMESTAMP     | NULLABLE                       | 5D 백필 완료 시각            |
| created_at        | TIMESTAMP     | NOT NULL, DEFAULT now()        | 레코드 생성 시각             |

### 5.2 인덱스 설계

- `ix_news_price_impact_stock_id` — 종목별 조회 성능
- `ix_news_price_impact_news_id` — 뉴스별 조회 성능
- `ix_news_price_impact_captured_at` — 기간별 조회 및 90일 삭제 정책
- `ix_news_price_impact_backfill` — 백필 대상 레코드 조회 (복합: `backfill_1d_at IS NULL AND captured_at`)

### 5.3 API 응답 스키마

**GET /api/news/{id}/impact**

```json
{
  "news_id": 123,
  "impacts": [
    {
      "stock_id": 45,
      "stock_name": "대창단조",
      "price_at_news": 15200,
      "price_after_1d": 15800,
      "price_after_5d": 16100,
      "return_1d_pct": 3.95,
      "return_5d_pct": 5.92,
      "captured_at": "2026-03-20T14:30:00+09:00"
    }
  ]
}
```

**GET /api/stocks/{id}/news-impact-stats**

```json
{
  "stock_id": 45,
  "stock_name": "대창단조",
  "period_days": 30,
  "total_news_count": 12,
  "completed_count": 8,
  "stats_1d": {
    "avg_return_pct": 1.23,
    "win_rate_pct": 62.5,
    "max_return_pct": 5.2,
    "min_return_pct": -2.1
  },
  "stats_5d": {
    "avg_return_pct": 2.45,
    "win_rate_pct": 75.0,
    "max_return_pct": 8.7,
    "min_return_pct": -3.4
  }
}
```

---

## 6. 구현 노트 (Implementation Notes)

> 구현 완료일: 2026-03-26 | 요구사항 17/17 완료

### 구현 완료 항목

| 파일 | 유형 | 설명 |
|------|------|------|
| `backend/app/models/news_price_impact.py` | 신규 | NewsPriceImpact ORM 모델 |
| `backend/alembic/versions/016_add_news_price_impact_table.py` | 신규 | DB 마이그레이션 (3개 인덱스) |
| `backend/app/services/news_price_impact_service.py` | 신규 | 스냅샷 캡처/백필/통계 서비스 (5개 async 함수) |
| `backend/app/schemas/news_price_impact.py` | 신규 | Pydantic 응답 스키마 |
| `backend/app/models/__init__.py` | 수정 | NewsPriceImpact import 추가 |
| `backend/app/services/news_crawler.py` | 수정 | 뉴스 저장 후 capture_price_snapshots() 주입 |
| `backend/app/services/scheduler.py` | 수정 | 2개 cron job 추가 (18:30 KST 백필, 03:00 KST 정리) |
| `backend/app/services/fund_manager.py` | 수정 | 브리핑 프롬프트에 뉴스 패턴 통계 통합 |
| `backend/app/routers/news.py` | 수정 | GET /api/news/{id}/impact 엔드포인트 추가 |
| `backend/app/routers/stocks.py` | 수정 | GET /api/stocks/{id}/news-impact-stats 엔드포인트 추가 |
| `frontend/src/lib/api.ts` | 수정 | fetchStockNewsImpactStats() 함수 추가 |
| `frontend/src/lib/types.ts` | 수정 | StockNewsImpactStats 인터페이스 추가 |
| `frontend/src/app/stocks/[id]/page.tsx` | 수정 | 뉴스 반응 통계 카드 UI 추가 |

### SPEC 대비 실제 구현 차이

- **relation_id 처리**: SPEC에서는 `news_stock_relations` 대량 삽입 후 ID를 역추적하여 `relation_id`를 채우는 방식을 계획했으나, 현재 구현에서는 `None`으로 전달함. 향후 개선 과제로 이전.
- **FK 전략**: `news_id`는 ON DELETE SET NULL (뉴스 7일 삭제 후에도 impact 레코드 유지), `stock_id`는 ON DELETE CASCADE (종목 삭제 시 관련 impact도 삭제)

---

## 7. 추적성 (Traceability)

| 요구사항 ID     | 모듈                | 구현 파일 (예상)                                |
| --------------- | ------------------- | ----------------------------------------------- |
| REQ-NPI-001~005 | 초기 가격 스냅샷    | `news_price_impact_service.py`, `news_crawler.py` |
| REQ-NPI-006~009 | 가격 반응 백필      | `news_price_impact_service.py`, `scheduler.py`  |
| REQ-NPI-010~013 | 뉴스 패턴 통계 API  | `routers/news.py`, `routers/stocks.py`          |
| REQ-NPI-014~015 | 브리핑 통계 강화    | `fund_manager.py`                               |
| REQ-NPI-016~017 | 데이터 보존 정책    | `news_price_impact.py` (모델), `scheduler.py`   |
