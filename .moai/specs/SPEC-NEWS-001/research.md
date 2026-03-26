# SPEC-NEWS-001 Research
# 뉴스-가격 반응 추적 시스템

**Date**: 2026-03-26
**Author**: MoAI Explore Agent
**SPEC**: SPEC-NEWS-001

---

## 1. Architecture Analysis

### 뉴스 수집 파이프라인 (`news_crawler.py` - 497 lines)

파이프라인은 5단계로 동작:
- **Phase 1**: Async RSS + Yahoo 뉴스 병렬 수집
- **Phase 2**: Naver/Google/Yahoo 키워드 검색 (60 쿼리 budget, semaphore 동시성)
- **Phase 3**: Fuzzy 제목 매칭으로 중복 제거 + 비금융 필터링
- **Phase 4**: 키워드 인덱스 + AI fallback 분류로 종목/섹터 관계 해결
- **Phase 5**: 콘텐츠 스크래핑 + `ON CONFLICT` 처리를 포함한 bulk SQL insert

**핵심 주입 지점**: `news_crawler.py:493` — `news_stock_relations` 삽입 직후.
이 시점에 article_id, stock_id 모두 확정된 상태.

### 스케줄러 (`scheduler.py`)

| Job ID | 트리거 | 주기 | 서비스 |
|--------|--------|------|--------|
| news_crawl | interval | 10분 | `news_crawler.crawl_all_news()` |
| dart_crawl | interval | 30분 | `dart_crawler.crawl_dart_disclosures()` |
| market_cap | interval | 6시간 | `naver_finance.update_market_caps()` |
| daily_briefing | cron | 08:30 KST | `fund_manager.generate_daily_briefing()` |
| signal_verification | cron | 18:00 KST | `signal_verifier.verify_signals()` |

**시그널 검증 Job (18:00 KST)**이 우리에게 필요한 패턴 그 자체:
- 1D/3D/5D 전 시그널 역방향 조회
- batch fetch로 현재가 수집
- 수익률 역산 및 검증 컬럼 업데이트

---

## 2. 데이터 가용성

### 주가 데이터 (`naver_finance.py`)

| 함수 | 반환 데이터 | 특이사항 |
|------|------------|---------|
| `fetch_stock_fundamentals(code)` | current_price, price_change, change_rate, volume, trading_value | 단일 종목 |
| `fetch_stock_fundamentals_batch(codes)` | `dict[stock_code, StockFundamentals]` | **권장** — 50종목/요청, 5분 캐시 |

캐시 TTL:
- 장 중 (09:00-15:30 KST): 10초
- 장 외: 5분

스냅샷 캡처 시 `force=True` 옵션으로 캐시 무시 필요.

### 뉴스-종목 관계 (`news_relation.py`)

```
news_stock_relations:
  - news_id (FK → news_articles.id)
  - stock_id (FK → stocks.id) — nullable
  - sector_id (FK → sectors.id) — nullable
  - match_type: 'keyword' | 'ai_classified'
  - relevance: 'direct' | 'indirect'
```

sector_id만 있고 stock_id가 없는 경우(섹터 전용 뉴스)는 Phase 1에서 제외.

### 뉴스 감성 (`news.py`)

`sentiment` 컬럼: `'positive'` | `'negative'` | `'neutral'` — AI 분류기가 설정.

---

## 3. 참조 구현: FundSignal 패턴

**`fund_signal.py` 모델 — 완전히 동일한 패턴:**

```python
class FundSignal(Base):
    price_at_signal: int          # 시그널 시점 가격 스냅샷
    price_after_1d: int | None    # 1일 후 (나중에 채움)
    price_after_3d: int | None    # 3일 후
    price_after_5d: int | None    # 5일 후
    is_correct: bool | None       # 정확도
    return_pct: float | None      # 수익률
    verified_at: datetime | None  # 검증 완료 시각
```

**`signal_verifier.py` 서비스 패턴:**
1. 18:00 KST 스케줄 Job
2. N일 전 시그널 역방향 쿼리
3. `fetch_stock_fundamentals_batch()`로 일괄 가격 수집
4. 수익률 계산 후 검증 컬럼 업데이트
5. 재시도 로직 3회 + 로깅

→ **이 패턴을 그대로 복제.**

---

## 4. 주입 지점 및 의존성

### 최적 주입 지점

```
news_crawler.py:crawl_all_news()
  → Phase 5: bulk insert articles
    → insert news_stock_relations  ← 여기서 article_ids, stock_ids 확정
    → [NEW] capture_price_snapshots(db, article_ids, stock_relations)  ← 삽입 지점
```

- 이 함수 호출 시점에 DB 내 article과 relation이 모두 커밋된 상태
- `stock_code` 목록을 구성해 `fetch_stock_fundamentals_batch()` 1회 호출로 일괄 캡처
- Bulk insert로 `news_price_impact` 레코드 생성

### 데일리 브리핑 주입

`fund_manager.py:generate_daily_briefing()`의 종목 분석 섹션에서:
- 각 종목의 최근 30일 뉴스 패턴별 평균 수익률 통계 조회
- AI 프롬프트에 추가: `"이 유형의 뉴스 이후 평균 수익률: +X.X%, 승률: Y%"`

---

## 5. 기술적 제약 및 리스크

| 제약사항 | 영향 | 해결책 |
|---------|------|--------|
| **7일 뉴스 보존 정책** | 5일 추적 전 삭제 가능 | `news_price_impact` 테이블에 독립 보존 기간 (30일+) |
| **주가 데이터 15분 지연** | 스냅샷 정확도 저하 | `market_status_at_collection` 컬럼으로 추적 |
| **섹터 전용 뉴스** | stock_id 없음 | Phase 1에서 stock_id 있는 관계만 처리 |
| **크롤러 동시 실행** | 중복 스냅샷 가능 | `UNIQUE(news_id, stock_id)`로 DB 레벨 보호 |
| **장 외 뉴스** | 다음날 시가 반응이 실제 반응** | `market_status_at_collection` 트래킹으로 분석 시 구분 |

---

## 6. 신규 DB 테이블 설계 (권장)

```python
class NewsPriceImpact(Base):
    __tablename__ = "news_price_impact"

    id: Mapped[int] = mapped_column(primary_key=True)
    news_id: Mapped[int] = mapped_column(ForeignKey("news_articles.id", ondelete="SET NULL"), nullable=True, index=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id"), nullable=False, index=True)

    # 초기 스냅샷
    price_at_collection: Mapped[int] = mapped_column(nullable=True)
    collection_timestamp: Mapped[datetime]
    market_status_at_collection: Mapped[str] = mapped_column(String(20))  # 'open'|'closed'

    # 백필 (나중에 채움)
    price_after_1h: Mapped[int | None]
    price_after_1d: Mapped[int | None]
    price_after_5d: Mapped[int | None]

    # 계산값
    return_1h_pct: Mapped[float | None]
    return_1d_pct: Mapped[float | None]
    return_5d_pct: Mapped[float | None]

    verified_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("news_id", "stock_id"),
    )
```

---

## 7. 구현 권장사항

### 우선순위 접근법

1. **새 모델 `NewsPriceImpact`** 생성 — FundSignal 패턴 복제
2. **`news_price_impact_service.py`** 신규 서비스 파일:
   - `capture_initial_snapshots(db, article_stock_pairs)` — 크롤러 호출용
   - `update_impact_prices(db, hours_ago)` — 스케줄러 호출용
   - `compute_news_pattern_statistics(db, stock_id, days=30)` — 분석 API용
3. **`news_crawler.py`** 수정 — Phase 5 뒤 스냅샷 캡처 호출 추가
4. **`scheduler.py`** 수정 — 1D/5D 업데이트 Job 추가 (18:30 KST)
5. **`fund_manager.py`** 수정 — 브리핑 AI 프롬프트에 통계 주입
6. **`routers/news.py`** 수정 — 뉴스별 가격 반응 조회 엔드포인트 추가
7. **Alembic 마이그레이션** 생성

### 파일별 수정 범위

| 파일 | 수정 유형 | 예상 변경량 |
|------|----------|------------|
| `models/news_price_impact.py` | 신규 | ~40 lines |
| `services/news_price_impact_service.py` | 신규 | ~150 lines |
| `services/news_crawler.py` | 수정 (삽입) | +10 lines |
| `services/scheduler.py` | 수정 (Job 추가) | +20 lines |
| `services/fund_manager.py` | 수정 (프롬프트 강화) | +30 lines |
| `routers/news.py` | 수정 (엔드포인트 추가) | +30 lines |
| `alembic/versions/` | 신규 마이그레이션 | ~30 lines |

**총 신규/수정 코드: ~310 lines — 적정 범위**

---

## 결론

NewsHive 코드베이스는 이 기능을 위한 강력한 참조 패턴이 이미 존재:
- **FundSignal + SignalVerifier** = 동일 아키텍처의 검증된 구현
- **Bulk Insert 패턴** = news_crawler.py에 프로덕션 적용 가능
- **스케줄러 패턴** = 백필 Job 추가 용이

가장 큰 리스크: **7일 뉴스 삭제 정책** — `news_price_impact` 테이블에서 `SET NULL` FK로 해결 (뉴스가 삭제돼도 impact 레코드는 보존).
