# SPEC-AI-026 Research: 종목 포럼 언급 급증 시그널

생성일: 2026-05-29
작성자: MoAI (manager-spec)
SPEC: SPEC-AI-026
범위: Backend-only

---

## 1. 코드베이스 조사 결과

### 1.1 발견된 포럼 데이터 모델 — `app/models/stock_forum.py`

기존 SPEC-AI-008 (역발상 지표용 종목토론방 크롤러)에서 이미 두 개의 모델이 정의되어 있다.

#### StockForumPost — 개별 게시글 레코드

```python
class StockForumPost(Base):
    __tablename__ = "stock_forum_posts"

    id: Mapped[int]                       # PK
    stock_id: Mapped[int | None]          # FK stocks.id (ondelete=SET NULL)
    stock_code: Mapped[str]               # 종목 코드, indexed
    content: Mapped[str | None]           # 게시글 제목 (max 200자)
    nickname: Mapped[str | None]          # 작성자 (max 100자)
    post_date: Mapped[datetime | None]    # 게시 시각 (KST tz-aware)
    view_count: Mapped[int]               # 조회수
    agree_count: Mapped[int]              # 찬성
    disagree_count: Mapped[int]           # 반대
    sentiment: Mapped[str]                # bullish | bearish | neutral
    collected_at: Mapped[datetime]        # 수집 시각 (server_default=NOW())

    # UniqueConstraint(stock_code, post_date, nickname) — 중복 방지
    # Index(stock_id), Index(collected_at), Index(stock_code)
```

#### StockForumHourly — 시간별 집계 메트릭

```python
class StockForumHourly(Base):
    __tablename__ = "stock_forum_hourly"

    id: Mapped[int]                       # PK
    stock_id: Mapped[int | None]          # FK stocks.id
    aggregated_at: Mapped[datetime]       # 집계 시각 (시간 단위 truncate)
    total_posts: Mapped[int]              # 시간당 게시글 수
    bullish_count: Mapped[int]
    bearish_count: Mapped[int]
    neutral_count: Mapped[int]
    bullish_ratio: Mapped[float]          # 0.0 ~ 1.0
    comment_volume: Mapped[int]           # = total_posts (별칭)
    avg_7d_volume: Mapped[float]          # 7일 평균 시간당 게시글 수
    volume_surge: Mapped[bool]            # 7일 평균의 3배 초과 시 True
    overheating_alert: Mapped[bool]       # 최근 2시간 bullish_ratio > 0.8 시 True

    # UniqueConstraint(stock_id, aggregated_at)
```

**Note**: StockForum 모델은 `app/models/__init__.py`에는 export되지 않으나, `app.models.stock_forum`에서 직접 import되어 `forum_crawler.py`와 `fund_manager._gather_forum_sentiment()`에서 사용 중이다.

### 1.2 크롤러 — `app/services/forum_crawler.py`

- `crawl_and_aggregate(db, stock_id, stock_code) -> dict`: 스케줄러 진입점.
  - 장 시간(KST 평일 09:00 ~ 18:00) 외에는 건너뜀.
  - 3페이지(약 60건) 크롤링 → `StockForumPost`에 upsert (UniqueConstraint 활용 ON CONFLICT DO NOTHING).
  - `aggregate_forum_hourly(db, stock_id)` 호출 → `StockForumHourly` upsert.
- 크롤러는 **시간 단위 집계**(`StockForumHourly`)를 이미 만들고 있다. 따라서 본 SPEC은 `StockForumHourly`를 그대로 사용하면 일별·다일 평균 집계를 SQL로 간단히 계산 가능.

### 1.3 통합 지점 — `_run_coverage_expansion(db, surge_results)`

`backend/app/services/fund_manager.py` 라인 3654 ~ 3719에 정의됨. 현재 **3개의 try/except 블록**으로 구성:

```
_run_coverage_expansion(db, surge_results)
├── try 1: propagate_theme_group_signals          (SPEC-AI-022 테마 전파)
├── try 2: detect_volume_anomaly_dormant_stocks   (SPEC-AI-022 거래량 이상)
└── try 3: detect_near_limit_up_carries            (SPEC-AI-023 상한가 근접)
```

> **사용자 요청 문장은 "6번째 try/except"라고 기술하나, 실측은 3개다.**
> 본 SPEC은 **4번째 try/except 블록**(논리적으로 "신규 탐지기 추가")으로 해석한다.
> 향후 SPEC-AI-024 / SPEC-AI-025가 별도 try 블록을 추가하면 자연스럽게 6번째로 정렬될 것.

### 1.4 설정 패턴 — `app/surge_config/surge_settings.py`

- `ThemePropagationConfig`, `VolumeAnomalyConfig`, `NearLimitUpConfig`, `CoverageDashboardConfig` 모두 동일 패턴: `BaseModel` 상속, 기본값 포함, `_run_coverage_expansion()`에서 직접 instantiate.
- 본 SPEC의 `ForumMentionConfig`도 동일 패턴 적용 (SurgeDetectionConfig 본체 변경 금지, 독립 instantiate).

### 1.5 FundSignal 모델 — `app/models/fund_signal.py`

- `signal_type: str | None` — surge_candidate, theme_propagation, volume_anomaly, near_limit_up_carry(SPEC-AI-023은 surge_candidate로 통합) 등이 이미 사용됨.
- `surge_metadata: str | None` — JSON 문자열로 `surge_basis: list[str]`, `surge_probability_score`, 탐지기별 점수를 담는다.
- `paper_executed: bool` — surge_candidate는 `True`(SPEC-AI-013에서 익일 매수 큐 진입). theme_propagation / volume_anomaly는 `True`. **본 SPEC도 `True`로 설정**하여 매수 큐 진입 허용 (사용자 요청 명시).

### 1.6 기존 surge_basis 키 목록 (관찰)

| surge_basis 키 | 출처 SPEC |
|---|---|
| `theme_cluster` | SPEC-AI-012 |
| `volume_news_combo` | SPEC-AI-012 |
| `disclosure_pattern` | SPEC-AI-012 |
| `disclosure_impact` | SPEC-AI-004 |
| `theme_propagation` | SPEC-AI-022 |
| `volume_anomaly` | SPEC-AI-022 |
| `near_limit_up_carry` | SPEC-AI-023 |
| **`forum_mention_surge`** | **SPEC-AI-026 (신규)** |

---

## 2. 사용자 요구사항 vs 실제 데이터 모델 정합성 분석

### 2.1 사용자 요구사항 요약

> 종목 X의 **최근 24시간 게시글 수**가 **7일 평균 일간 게시물 수의 5배 이상**이고, 절대값 ≥ 10건이면 surge_candidate 시그널 생성.

### 2.2 실제 데이터 모델과의 매핑

`StockForumHourly.total_posts`는 **시간당** 게시글 수이지 일간 누적값이 아니다.

**조정안**:
- "최근 24시간 게시글 수" = 최근 24개 `StockForumHourly` 레코드의 `total_posts` 합산
  - 또는: `StockForumPost`에서 `post_date >= now - 24h`인 row count 직접 조회
- "7일 평균 일간 게시물 수" = 최근 7일간(8일 전 ~ 어제) 일별 게시글 수 평균
  - 계산: `StockForumPost.post_date` 기준 일자별 GROUP BY → 7일 평균
  - 또는: `StockForumHourly.total_posts`를 24시간 단위로 합산 후 평균

### 2.3 구현 방식 선택 — 단순화 권장

`StockForumPost` 테이블에서 직접 집계하는 방식이 가장 단순하고 정확하다:

```sql
-- 최근 24시간 게시글 수 (per stock_code)
SELECT stock_code, COUNT(*) as posts_24h
FROM stock_forum_posts
WHERE post_date >= NOW() - INTERVAL '24 hours'
GROUP BY stock_code
HAVING COUNT(*) >= 10;  -- min_absolute_mentions filter

-- 직전 7일 평균 일간 게시글 수 (per stock_code)
SELECT stock_code,
       COUNT(*) / 7.0 as avg_daily_posts_7d
FROM stock_forum_posts
WHERE post_date >= NOW() - INTERVAL '8 days'
  AND post_date <  NOW() - INTERVAL '1 day'
GROUP BY stock_code;
```

후보 검증 후 ratio 계산: `posts_24h / avg_daily_posts_7d`.

### 2.4 가설 검증 (Sanity Check)

- **데이터 신선도**: `forum_crawler.crawl_and_aggregate`는 장 시간(평일 09:00 ~ 18:00 KST)에만 실행. 본 SPEC은 매일 15:20 KST 직후 `_run_coverage_expansion`이 호출되므로, 당일 09:00 ~ 15:20 게시글이 이미 DB에 적재되어 있다.
- **휴장일 영향**: 7일 평균 계산 시 주말·휴일은 자연스럽게 0건으로 잡혀 baseline을 낮추는 효과. 절대값 필터(≥ 10건)가 false positive를 방지한다.
- **신규 종목 처리**: 7일 이내 첫 등장한 종목은 `avg_daily_posts_7d ≈ 0`이 되어 ratio가 무한대가 될 수 있음. **요구사항: `avg_daily_posts_7d > 0` 가드 추가** 필요.

---

## 3. 잠재적 위험 및 완화

| 위험 | 완화 방안 |
|---|---|
| 7일 baseline이 0인 신규 종목에서 division-by-zero | `avg_daily_posts_7d > 0` 가드 + AC-006 추가 |
| 중복 시그널 생성 (당일 이미 surge_candidate 존재) | SPEC-AI-023 동일 패턴: `EXISTS` 서브쿼리로 중복 체크 |
| 포럼 크롤러 휴면 (장 시간 외) → stale data | 본 SPEC은 시그널만 발행. 데이터 신선도 보장은 크롤러 책임 |
| 자동봇/스팸이 게시글 수를 인위적으로 부풀림 | 본 SPEC 범위 외. 향후 별도 SPEC으로 스팸 필터 도입 가능 |
| 시그널 폭주 (이슈 종목 다수) | `max_signals_per_day`(기본 20) 적용 권장 |
| 외부 의존성 (StockForumPost 테이블 존재) | SPEC-AI-008에서 이미 마이그레이션 완료 — 별도 마이그레이션 불필요 |

---

## 4. 비기능적 요구사항

- **성능**: 일 1회 호출. SQL aggregation 2회 (`posts_24h`, `avg_daily_posts_7d`). 인덱스 `ix_forum_posts_stock_code`와 `post_date` 활용 가능. 예상 1초 이내.
- **DB 부담**: 신규 시그널 일 평균 5 ~ 20건 추정 (이슈 종목 다수일 때 폭증 가능).
- **격리**: 본 try/except 블록 실패해도 SPEC-AI-022 / SPEC-AI-023 결과는 보존 (이미 commit됨).
- **신규 마이그레이션 없음**: `stock_forum_posts`, `stock_forum_hourly` 테이블 모두 SPEC-AI-008에서 생성 완료.

---

## 5. 참조 SPEC 비교 (SPEC-AI-022, SPEC-AI-023과의 유사성)

| 항목 | SPEC-AI-022 (volume_anomaly) | SPEC-AI-023 (near_limit_up) | **SPEC-AI-026 (forum_mention)** |
|---|---|---|---|
| signal_type | `surge_candidate` | `surge_candidate` | `surge_candidate` |
| surge_basis | `["volume_anomaly"]` | `["near_limit_up_carry"]` | `["forum_mention_surge"]` |
| paper_executed | True | True | True |
| confidence 공식 | `min(ratio/10, 0.40)` | `change/30 * 0.5` (≈ 0.42 ~ 0.50) | `min(ratio/20, 0.35)` |
| Config 클래스 | `VolumeAnomalyConfig` | `NearLimitUpConfig` | `ForumMentionConfig` |
| Detector 함수 | `detect_volume_anomaly_dormant_stocks()` | `detect_near_limit_up_carries()` | `detect_forum_mention_surge()` |
| 통합 위치 | `_run_coverage_expansion` try 2 | `_run_coverage_expansion` try 3 | `_run_coverage_expansion` try 4 |

---

## 6. 발견 사항 요약

- **포럼 데이터 모델은 SPEC-AI-008에서 이미 완비됨** (`StockForumPost`, `StockForumHourly`). 신규 테이블·마이그레이션 불필요.
- **사용자 요구사항(24시간 vs 7일 일평균)은 `StockForumPost` 직접 집계가 가장 단순·정확**.
- **`_run_coverage_expansion` 내 try/except 블록은 현재 3개**이며, 본 SPEC은 4번째 블록으로 추가됨 (사용자 표현 "6번째"는 향후 SPEC 추가 후 정합 예상).
- **`surge_candidate` signal_type 재사용**하여 `surge_trading_service.get_today_signals` 필터를 자동 통과시키는 패턴은 SPEC-AI-022/023과 동일.
- **자기 종목 ID 기반 stocks 테이블 조인 필요** — `StockForumPost.stock_id`가 nullable이므로 `WHERE stock_id IS NOT NULL` 가드 필요.
