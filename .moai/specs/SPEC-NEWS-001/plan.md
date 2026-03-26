---
id: SPEC-NEWS-001
type: plan
version: "1.0.0"
---

# SPEC-NEWS-001: 구현 계획서

## 1. 구현 단계 분해

### Phase 1: 데이터 모델 및 마이그레이션 [Priority: High]

**목표**: `NewsPriceImpact` 모델 생성 및 DB 마이그레이션

- NEW: `backend/app/models/news_price_impact.py` — SQLAlchemy ORM 모델
- MODIFY: `backend/app/models/__init__.py` — 모델 등록
- NEW: Alembic 마이그레이션 파일 생성

**핵심 설계**:
- `news_id` FK는 `ondelete="SET NULL"` (7일 뉴스 삭제 정책 대응)
- `relation_id` FK도 `ondelete="SET NULL"` (뉴스 삭제 시 relation도 삭제될 수 있음)
- `stock_id` FK는 `ondelete="CASCADE"` (종목 삭제 시 impact도 삭제)
- 4개 인덱스 설계 (stock_id, news_id, captured_at, 백필용 복합)

**참조 구현**: `backend/app/models/fund_signal.py` 패턴 차용

---

### Phase 2: 핵심 서비스 구현 [Priority: High]

**목표**: 가격 스냅샷 캡처 및 백필 서비스 구현

- NEW: `backend/app/services/news_price_impact_service.py`

**함수 설계**:

| 함수명                       | 역할                                       |
| ---------------------------- | ------------------------------------------ |
| `capture_price_snapshots()`  | 새 뉴스의 연관 종목 가격 스냅샷 일괄 캡처  |
| `backfill_1d_prices()`       | 1일 경과 레코드의 가격 반응 업데이트        |
| `backfill_5d_prices()`       | 5일 경과 레코드의 가격 반응 업데이트        |
| `get_news_impact()`          | 뉴스별 가격 반응 데이터 조회                |
| `get_stock_impact_stats()`   | 종목별 뉴스 패턴 통계 계산 (30일)           |
| `cleanup_old_records()`      | 90일 경과 레코드 삭제                       |

**참조 구현**: `backend/app/services/signal_verifier.py` — 동일한 가격 조회 + 업데이트 패턴

---

### Phase 3: 뉴스 크롤러 통합 [Priority: High]

**목표**: 뉴스 수집 파이프라인에 가격 스냅샷 캡처 주입

- MODIFY: `backend/app/services/news_crawler.py`
  - Phase 5 완료 후 (article + relations 모두 DB 커밋 후) `capture_price_snapshots()` 호출
  - 실패 시 로그만 남기고 뉴스 수집 프로세스에 영향 없도록 try-except 처리

**주입 지점**: `news_crawler.py`의 `_process_batch()` 또는 `crawl_all()` 메서드 마지막 단계

---

### Phase 4: 스케줄러 등록 [Priority: High]

**목표**: 백필 및 정리 작업 스케줄러 등록

- MODIFY: `backend/app/services/scheduler.py`
  - 18:30 KST: `backfill_1d_prices()` + `backfill_5d_prices()` (기존 18:00 signal_verification 이후)
  - 03:00 KST: `cleanup_old_records()` (90일 경과 레코드 삭제)

**참조**: 기존 `signal_verification` job의 cron 패턴 활용

---

### Phase 5: API 엔드포인트 [Priority: Medium]

**목표**: 뉴스 impact 및 종목 통계 API 구현

- MODIFY: `backend/app/routers/news.py`
  - `GET /api/news/{id}/impact` — 뉴스별 가격 반응 데이터
- MODIFY: `backend/app/routers/stocks.py`
  - `GET /api/stocks/{id}/news-impact-stats` — 종목별 뉴스 패턴 통계

- NEW: `backend/app/schemas/news_price_impact.py` — Pydantic 응답 스키마

---

### Phase 6: 브리핑 통합 [Priority: Medium]

**목표**: 데일리 브리핑 AI 프롬프트에 통계 데이터 통합

- MODIFY: `backend/app/services/fund_manager.py`
  - 08:30 KST 브리핑 생성 시 `get_stock_impact_stats()` 호출
  - 통계 데이터를 AI 프롬프트에 삽입 (30일 기준 평균 수익률, 승률)
  - 통계 없는 종목은 해당 섹션 생략

---

### Phase 7: 프론트엔드 표시 [Priority: Low]

**목표**: 종목 상세 페이지에 뉴스 패턴 통계 표시

- MODIFY: `frontend/src/app/stocks/[id]/page.tsx` — 통계 카드 컴포넌트 추가
- MODIFY: `frontend/src/lib/api.ts` — API 호출 함수 추가

---

## 2. 기술 스택 및 의존성

### 신규 의존성

없음. 모든 필요 라이브러리는 이미 설치되어 있음:
- SQLAlchemy 2.0 (async) — 모델 정의
- APScheduler — 스케줄러 작업
- `naver_finance` 모듈 — 가격 데이터 조회

### 기존 활용 모듈

| 모듈                                      | 활용 방식                          |
| ----------------------------------------- | ---------------------------------- |
| `naver_finance.fetch_stock_fundamentals_batch()` | 50종목/요청 일괄 가격 조회   |
| `signal_verifier.py`                      | 가격 추적 패턴 참조                |
| `fund_signal.py`                          | 모델 구조 참조                     |
| `scheduler.py`                            | APScheduler cron 패턴 참조         |

---

## 3. DB 스키마 상세 설계

### NewsPriceImpact 테이블

```sql
CREATE TABLE news_price_impact (
    id SERIAL PRIMARY KEY,
    news_id INTEGER REFERENCES news_articles(id) ON DELETE SET NULL,
    stock_id INTEGER NOT NULL REFERENCES stocks(id) ON DELETE CASCADE,
    relation_id INTEGER REFERENCES news_stock_relations(id) ON DELETE SET NULL,
    price_at_news FLOAT NOT NULL,
    price_after_1d FLOAT,
    price_after_5d FLOAT,
    return_1d_pct FLOAT,
    return_5d_pct FLOAT,
    captured_at TIMESTAMP NOT NULL DEFAULT NOW(),
    backfill_1d_at TIMESTAMP,
    backfill_5d_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- 인덱스
CREATE INDEX ix_npi_stock_id ON news_price_impact(stock_id);
CREATE INDEX ix_npi_news_id ON news_price_impact(news_id);
CREATE INDEX ix_npi_captured_at ON news_price_impact(captured_at);
CREATE INDEX ix_npi_backfill_pending ON news_price_impact(captured_at)
    WHERE backfill_1d_at IS NULL OR backfill_5d_at IS NULL;
```

### FK 전략 요약

| FK 대상              | ON DELETE  | 이유                                    |
| -------------------- | ---------- | --------------------------------------- |
| news_articles        | SET NULL   | 7일 삭제 정책, impact 레코드는 90일 보존 |
| stocks               | CASCADE    | 종목 삭제 시 관련 impact도 삭제          |
| news_stock_relations | SET NULL   | relation 삭제 시에도 impact 보존         |

---

## 4. 리스크 분석 및 완화 전략

### R1: 가격 API 호출 실패 (가능성: 중간)

- **영향**: 스냅샷 누락 또는 백필 데이터 불완전
- **완화**: 개별 종목 실패 시 skip & 로그, 전체 프로세스 계속 진행
- **백필 재시도**: 3회 재시도 후 null 유지, 다음 스케줄 실행 시 재시도 대상에서 제외하지 않음

### R2: 뉴스 대량 발생 시 가격 API 부하 (가능성: 낮음)

- **영향**: API rate limit 초과
- **완화**: `fetch_stock_fundamentals_batch()` 활용 (50종목/요청), 5분 캐시로 중복 호출 방지
- **추가**: 동일 종목의 중복 스냅샷 방지 (같은 크롤링 배치 내 동일 stock_id는 1회만 캡처)

### R3: 7일 뉴스 삭제 후 데이터 연결 단절 (가능성: 확실)

- **영향**: news_id가 null이 되어 원본 뉴스 추적 불가
- **완화**: `news_price_impact`에 충분한 컨텍스트 저장 (stock_id, captured_at으로 독립 분석 가능)
- **설계 결정**: SET NULL FK로 레코드 보존, 통계 계산은 news_id 없이도 stock_id 기반으로 동작

### R4: 백필 타이밍 정확도 (가능성: 낮음)

- **영향**: 정확히 24시간/120시간이 아닌 캘린더 기준 1일/5일 후 18:30 시점 가격
- **완화**: 통계적으로 유의미한 수준이며, 정밀한 시점 가격보다 추세 파악이 목적
- **문서화**: 사용자에게 "영업일 기준이 아닌 캘린더 기준" 안내

---

## 5. 기존 참조 구현 위치

| 참조 대상                     | 파일 경로                                        | 참조 포인트                   |
| ----------------------------- | ------------------------------------------------ | ----------------------------- |
| 가격 추적 모델 패턴           | `backend/app/models/fund_signal.py`              | 컬럼 구조, FK 설계            |
| 가격 검증 스케줄러            | `backend/app/services/signal_verifier.py`        | 일괄 가격 조회 + 업데이트 로직 |
| 뉴스 수집 파이프라인          | `backend/app/services/news_crawler.py`           | Phase 5 완료 후 주입 지점     |
| 스케줄러 cron 패턴            | `backend/app/services/scheduler.py`              | APScheduler job 등록 방식     |
| 가격 데이터 API               | `backend/app/services/naver_finance.py`          | `fetch_stock_fundamentals_batch()` |
| 브리핑 생성 로직              | `backend/app/services/fund_manager.py`           | AI 프롬프트 구성 방식         |

---

## 6. MX 태그 전략

### 신규 MX 태그 대상

| 파일                              | 함수                          | 태그           | 이유                                       |
| --------------------------------- | ----------------------------- | -------------- | ------------------------------------------ |
| `news_price_impact_service.py`    | `capture_price_snapshots()`   | @MX:ANCHOR     | 뉴스 크롤러에서 호출 (fan_in >= 1, 핵심 로직) |
| `news_price_impact_service.py`    | `backfill_1d_prices()`        | @MX:NOTE       | 스케줄러에서 호출되는 배치 작업              |
| `news_price_impact_service.py`    | `backfill_5d_prices()`        | @MX:NOTE       | 스케줄러에서 호출되는 배치 작업              |
| `news_price_impact_service.py`    | `get_stock_impact_stats()`    | @MX:ANCHOR     | API + 브리핑에서 호출 (fan_in >= 2)          |
| `news_crawler.py`                 | 스냅샷 주입 지점              | @MX:WARN       | 파이프라인 핵심 분기점, 실패 격리 필수       |
| `scheduler.py`                    | 백필 job 등록                 | @MX:NOTE       | 신규 cron job 등록 컨텍스트                  |

---

## 7. 파일 변경 요약

| 파일                                          | 변경 유형 | 변경 범위     |
| --------------------------------------------- | --------- | ------------- |
| `backend/app/models/news_price_impact.py`     | NEW       | 전체 (모델)   |
| `backend/app/services/news_price_impact_service.py` | NEW  | 전체 (서비스) |
| `backend/app/schemas/news_price_impact.py`    | NEW       | 전체 (스키마) |
| `backend/app/services/news_crawler.py`        | MODIFY    | 소규모 (주입) |
| `backend/app/services/scheduler.py`           | MODIFY    | 소규모 (job)  |
| `backend/app/services/fund_manager.py`        | MODIFY    | 중규모 (프롬프트) |
| `backend/app/routers/news.py`                 | MODIFY    | 소규모 (엔드포인트) |
| `backend/app/routers/stocks.py`               | MODIFY    | 소규모 (엔드포인트) |
| `backend/app/models/__init__.py`              | MODIFY    | 소규모 (import) |
| Alembic 마이그레이션                          | NEW       | 전체          |
| `frontend/src/app/stocks/[id]/page.tsx`       | MODIFY    | 중규모 (UI)   |
| `frontend/src/lib/api.ts`                     | MODIFY    | 소규모 (함수) |
