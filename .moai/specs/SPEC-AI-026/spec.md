---
id: SPEC-AI-026
version: 0.2.0
status: implemented
created: 2026-05-29
updated: 2026-07-02
author: MoAI
priority: Medium
issue_number: 0
title: 종목 포럼 언급 급증 시그널 (Forum Mention Surge Detection)
---

# SPEC-AI-026: 종목 포럼 언급 급증 시그널

## HISTORY

- 2026-05-29 (v0.1.0): 초안 작성. 스케줄러가 이미 30분마다 `forum_crawler.crawl_and_aggregate`를 호출하여 `stock_forum_posts` 테이블에 게시글을 적재하고 있으나, 이 데이터가 surge_candidate 시그널 생성에는 연결되지 않은 사각지대를 해소한다. 포럼 언급 급증(직전 평소 대비 5배 이상)은 거래량 급등을 1 ~ 4시간 선행하는 패턴이 관찰되며, 본 SPEC은 이를 surge_candidate 시그널로 자동 발행한다. backend-only SPEC.
- 2026-07-02 (v0.2.0, DDD 버그픽스): `detect_forum_mention_surge()`의 `surge_metadata` 키명을 SPEC 요구(`mentions_recent`/`baseline_avg_daily`/`mention_ratio`)와 다르게 `recent_count`/`baseline_avg`/`ratio`로 구현했던 불일치를 수정. 다운스트림 소비자는 테스트 파일 외 없음을 grep으로 확인 후 전면 교체. 중복 방지 범위가 spec의 3개 signal_type이 아닌 "오늘 발행된 모든 signal_type"으로 넓게 구현된 것은 SPEC-AI-023과 동일한 근거(교차 탐지기 중복 방지에 더 안전)로 검토 후 유지(근거는 progress.md 참조). config 필드/기본값, confidence 공식, baseline=0 스킵 로직은 이미 SPEC과 일치하여 무변경. status: planned → implemented.

---

## Overview

뉴스/공시/거래량 기반 surge_candidate 탐지 파이프라인은 미디어 노출 전 단계의 **개인 투자자 관심 폭증**을 감지하지 못한다. 포럼(네이버 종목토론방) 언급 수는 다음의 선행 신호를 제공한다:

- 평소 일평균 1 ~ 3건이던 종목이 24시간 내 50건 이상 토론 → 매수 압력 증가 직전 단계
- 거래량 폭증보다 **1 ~ 4시간 선행**하는 통계적 패턴 관찰됨
- 뉴스/공시가 부재하더라도 (예: 풍문, 테마 연관성) 포럼 활성도 변화로 식별 가능

본 SPEC은 SPEC-AI-008에서 이미 적재 중인 `stock_forum_posts` 데이터를 활용하여, `_run_coverage_expansion()`에 **신규 try/except 블록 1개**를 추가하고, 비교 기준 대비 5배 이상 + 절대값 ≥ 10건 조건을 만족하는 종목에 `signal_type="surge_candidate"`, `surge_basis: ["forum_mention_surge"]` 시그널을 발행한다.

### Problem Background

| 시나리오 | 기존 파이프라인 처리 | 본 SPEC 처리 |
|---|---|---|
| 평소 일평균 1건 → 24시간 50건, 뉴스 부재 | 어떤 탐지기도 발동 안 함 | forum_mention_surge 시그널 생성 |
| 평소 일평균 5건 → 24시간 80건, 뉴스 1건 (저 sentiment) | volume_news_combo가 거래량 급등 시에만 발동 (선행성 부족) | 거래량 급등 1 ~ 4시간 전에 미리 발동 |
| 평소 0건 → 24시간 12건 (신규 종목) | 처리 불가 (baseline 부재) | division-by-zero 가드로 스킵 |

### Root Cause

- 기존 탐지기는 **뉴스/공시/거래량/가격**의 외부 시그널만 입력으로 사용
- 포럼 게시글 수는 `StockForumHourly.volume_surge` 컬럼(7일 평균의 3배)에 boolean으로만 기록되며, surge_candidate 시그널로 변환되지 않음
- `fund_manager._gather_forum_sentiment()`는 sentiment 비율(bullish_ratio)만 fund 시그널 입력으로 사용. 게시글 절대 수(`total_posts`) 변화율은 활용 안 됨

### 설계 원칙

- **가법적 확장 (Additive)**: 기존 `surge_candidate`, `theme_propagation`, `volume_anomaly`, `near_limit_up_carry` 생성 로직 변경 금지
- **try/except 격리**: `_run_coverage_expansion()` 내 신규 try 블록 (4번째)로 추가. 본 단계 실패가 상위 파이프라인에 영향 없음
- **paper_executed=True**: 사용자 요구사항. 본 SPEC 시그널은 익일 매수 큐에 자동 진입 (SPEC-AI-022 theme_propagation과 동일 정책)
- **신규 마이그레이션 없음**: `stock_forum_posts` 테이블은 SPEC-AI-008에서 생성 완료
- **신규 signal_type 도입 금지**: `signal_type='surge_candidate'`를 그대로 사용. 식별은 `surge_metadata.surge_basis=["forum_mention_surge"]`로 수행
- **WHAT/WHY only**: 시그널 생성 조건과 confidence 공식만 정의. 쿼리 최적화, 인덱스 활용은 RUN 단계에서 결정

### 전제 조건 (Assumptions)

- `stock_forum_posts` 테이블이 존재하며 `stock_id`, `stock_code`, `post_date` 컬럼을 보유한다 (SPEC-AI-008).
- `forum_crawler.crawl_and_aggregate`가 스케줄러에 의해 30분 주기로 호출되어 당일 게시글이 DB에 적재된다 (장 시간 KST 평일 09:00 ~ 18:00).
- `fund_signals` 테이블은 `signal_type`, `confidence`, `surge_metadata`, `paper_executed` 컬럼을 보유한다 (SPEC-AI-004, SPEC-AI-012).
- `_run_coverage_expansion`은 `run_surge_signal_generation` 내 surge_candidate persist 직후 호출된다 (SPEC-AI-022).
- `surge_trading_service.get_today_signals`는 `signal_type='surge_candidate'`만 필터링하므로, 본 SPEC의 신규 시그널도 동일 `signal_type='surge_candidate'`로 발행되어 자동으로 익일 매수 큐에 포함된다.
- 본 SPEC은 새 DB 컬럼/마이그레이션을 추가하지 않는다.

---

## EARS Requirements

### REQ-AI026-001: 포럼 언급량 급증 탐지 및 시그널 생성

**WHERE** 시스템이 `_run_coverage_expansion()` 내 surge_candidate / theme_propagation / volume_anomaly / near_limit_up_carry 처리 완료 후, the system SHALL `detect_forum_mention_surge(db, config) -> int` 신규 탐지기를 호출하여 포럼 언급량 급증 종목에 대한 surge_candidate 시그널을 생성한다.

**WHEN** 본 탐지기가 실행될 때, the system SHALL 각 종목별로 다음 두 값을 집계한다:
- (a) **`mentions_recent`**: `stock_forum_posts` 테이블에서 `post_date >= NOW() - INTERVAL '{mention_window_hours} hours'` 조건을 만족하는 row 수 (per `stock_id`, `stock_id IS NOT NULL` 가드)
- (b) **`baseline_avg_daily`**: `stock_forum_posts` 테이블에서 `post_date >= NOW() - INTERVAL '{baseline_days + 1} days'` AND `post_date < NOW() - INTERVAL '1 day'` 조건의 row 수를 `baseline_days`로 나눈 일평균값

**IF** `baseline_avg_daily <= 0` (신규 종목 또는 0건) 이면, **then** the system SHALL 해당 종목을 시그널 후보에서 제외한다 (division-by-zero 방지).

**WHEN** 종목의 `mentions_recent >= baseline_avg_daily * ForumMentionConfig.mention_multiplier` AND `mentions_recent >= ForumMentionConfig.min_absolute_mentions` 조건을 모두 만족할 때, AND 다음 중복 조건이 모두 부재할 때 (a, b, c 모두 부재), the system SHALL 신규 `FundSignal` 레코드를 생성한다:
- (a) 동일 종목에 오늘 (KST 00:00:00 이후) `signal_type='surge_candidate'` 시그널이 이미 존재 (기존 surge_candidate / carry_over / near_limit_up_carry가 처리한 케이스)
- (b) 동일 종목에 오늘 `signal_type='theme_propagation'` 시그널이 존재
- (c) 동일 종목에 오늘 `signal_type='volume_anomaly'` 시그널이 존재

**IF** 위 모든 조건을 만족하면, **then** the system SHALL 다음 값으로 `FundSignal` 레코드를 생성한다:
- `signal_type = "surge_candidate"`
- `signal = "buy"`
- `confidence = round(min(ratio / 20.0, ForumMentionConfig.max_confidence), 4)`, 여기서 `ratio = mentions_recent / baseline_avg_daily`
- `reasoning = f"[SPEC-AI-026 포럼언급급증] 최근 {mention_window_hours}h 게시글 {mentions_recent}건 (평소 {baseline_avg_daily:.1f}건/일 대비 {ratio:.1f}x)"`
- `paper_executed = True`
- `surge_metadata`(JSON 문자열): `{"surge_basis": ["forum_mention_surge"], "mentions_recent": mentions_recent, "baseline_avg_daily": round(baseline_avg_daily, 2), "mention_ratio": round(ratio, 2)}`
- 기타 필드 (`target_price`, `stop_loss`, `price_at_signal`, `news_summary`, `financial_summary`, `market_summary`, `disclosure_id`, `factor_scores`, `composite_score`, `ai_model`, `tp_sl_method`, `prompt_version`, `trend_alignment`, `volatility_level`): NULL 또는 기본값

**WHEN** 탐지기 실행이 완료될 때, the system SHALL 평가 종목 수, baseline 부재 스킵 수, 생성된 시그널 수를 로깅한다 (`logger.info("[포럼언급] 평가=%d baseline_skip=%d 생성=%d", ...)`).

**WHERE** 단일 종목 처리 중 예외가 발생하면, the system SHALL 해당 종목만 스킵하고 다음 종목 처리를 계속한다 (예외 전파 금지).

`[NEW]` `backend/app/services/surge_detector.py` — `detect_forum_mention_surge(db, config) -> int` 신규 함수 (생성된 시그널 수 반환)
`[MODIFY]` `backend/app/services/fund_manager.py` — `_run_coverage_expansion()` 내 near_limit_up_carry 호출 이후 `detect_forum_mention_surge()` 호출 추가 (별도 try/except 블록)
`[NEW]` `backend/app/surge_config/surge_settings.py` — `ForumMentionConfig(BaseModel)` 신규 Pydantic 클래스 추가

---

### REQ-AI026-002: ForumMentionConfig 설정 클래스

**WHERE** 본 SPEC의 파라미터를 런타임에 조정할 수 있도록, the system SHALL `app.surge_config.surge_settings`에 다음 Pydantic 모델을 추가한다:

```python
class ForumMentionConfig(BaseModel):
    """SPEC-AI-026: 포럼 언급 급증 시그널 설정."""
    enabled: bool = True
    mention_multiplier: float = 5.0          # baseline 대비 배수 임계값
    min_absolute_mentions: int = 10          # 최근 24h 절대값 최소치
    baseline_days: int = 7                   # 직전 평균 계산 기간
    mention_window_hours: int = 24           # 최근 게시글 집계 시간 창
    max_confidence: float = 0.35             # confidence 상한
```

**WHERE** `ForumMentionConfig` 인스턴스는, the system SHALL `_run_coverage_expansion()` 내부에서 직접 instantiate하여 `detect_forum_mention_surge(db, ForumMentionConfig())` 형태로 호출한다 (SPEC-AI-022 / SPEC-AI-023과 동일 패턴).

**WHERE** `SurgeDetectionConfig` 본체에는, the system SHALL `ForumMentionConfig` 필드를 추가하지 않는다 — 본 SPEC의 config는 독립적으로 instantiate된다.

**IF** `ForumMentionConfig.enabled == False`이면, **then** the system SHALL 탐지기를 호출하지 않고 즉시 0을 반환한다.

`[MODIFY]` `backend/app/surge_config/surge_settings.py` — `ForumMentionConfig` 클래스 정의 (REQ-AI026-001과 동일 파일)

---

### REQ-AI026-003: 통합 지점 격리

**WHERE** `fund_manager._run_coverage_expansion()` 헬퍼는, the system SHALL 본 SPEC의 탐지기 호출을 다음 위치(4번째 try 블록)에 추가한다:

```
_run_coverage_expansion(db, surge_results)
├── try 1: propagate_theme_group_signals       (기존, SPEC-AI-022)
├── try 2: detect_volume_anomaly_dormant_stocks (기존, SPEC-AI-022)
├── try 3: detect_near_limit_up_carries          (기존, SPEC-AI-023)
└── try 4: detect_forum_mention_surge            (신규, SPEC-AI-026)
```

**WHEN** 신규 try/except 블록이 실행될 때, the system SHALL:
- 실패 시 `logger.warning("[커버리지확장] 포럼언급 급증 탐지 실패 (다른 시그널 결과 보존됨): %s", e)` 로깅
- DB 세션 무결성을 위해 필요 시 `db.rollback()` 후에도 후속 코드(이 함수 종료) 진행
- 본 try 블록이 실패해도 이미 commit된 surge_candidate, theme_propagation, volume_anomaly, near_limit_up_carry 시그널은 보존된다

**WHERE** `detect_forum_mention_surge()` 내부에서 단일 종목 처리가 실패하면, the system SHALL 해당 종목만 스킵하고 다음 종목을 계속 처리한다. 단일 종목의 DB add 실패 시에는 해당 row만 `db.rollback()` 후 다음으로 진행하며, 모든 종목 처리 완료 후 일괄 commit 또는 함수 종료 시점에 commit한다.

`[NO NEW FILE]` REQ-AI026-001 / REQ-AI026-002의 파일 변경에 포함

---

## Acceptance Criteria

각 요구사항별 검증 가능한 인수 기준. 외부 의존성(DB)은 in-memory SQLite 또는 mock으로 격리.

### AC-001: 24시간 50건, 7일 평균 5건/일 → ratio=10x → confidence=0.35 (capped) (REQ-AI026-001)

**Given**:
- 종목 X가 `stocks` 테이블에 존재하고 `stock_forum_posts`에 다음 데이터 적재:
  - 최근 24시간 내 게시글 50건 (NOW() - 1h ~ NOW() 범위)
  - 직전 7일간 (8일 전 ~ 1일 전) 게시글 35건 → 일평균 5.0건
- 종목 X에 당일 어떤 signal_type의 FundSignal도 부재
- `ForumMentionConfig()` 기본값 사용 (`mention_multiplier=5.0`, `min_absolute_mentions=10`, `max_confidence=0.35`)

**When**: `detect_forum_mention_surge(db, ForumMentionConfig())` 호출

**Then**:
- 종목 X에 대해 시그널 1건 생성
- `signal_type == "surge_candidate"`, `signal == "buy"`
- ratio = 50 / 5.0 = 10.0 → `confidence = round(min(10.0/20.0, 0.35), 4) = 0.35` (cap 적용)
- `surge_metadata` JSON 파싱 시 `surge_basis == ["forum_mention_surge"]`, `mentions_recent == 50`, `baseline_avg_daily == 5.0`, `mention_ratio == 10.0`
- `paper_executed == True`
- 함수 반환값 `>= 1`

### AC-002: 24시간 3건 (절대값 미달) → 시그널 생성 안 함 (REQ-AI026-001)

**Given**:
- 종목 Y가 stocks 테이블에 존재
- 최근 24시간 내 게시글 3건, 직전 7일 평균 0.3건/일 (ratio 10x 충족)
- 당일 signal 부재

**When**: `detect_forum_mention_surge(db, ForumMentionConfig())` 호출

**Then**:
- 종목 Y에 대해 시그널 생성 안 함 (`mentions_recent < min_absolute_mentions=10`)

### AC-003: ratio < 5.0 → 시그널 생성 안 함 (REQ-AI026-001)

**Given**:
- 종목 Z가 stocks 테이블에 존재
- 최근 24시간 내 게시글 15건, 직전 7일 평균 5건/일 → ratio = 3.0x
- 당일 signal 부재

**When**: `detect_forum_mention_surge(db, ForumMentionConfig())` 호출

**Then**:
- 종목 Z에 대해 시그널 생성 안 함 (`ratio < mention_multiplier=5.0`)

### AC-004: 당일 surge_candidate 시그널이 이미 존재 → 중복 생성 안 함 (REQ-AI026-001)

**Given**:
- 종목 W가 24h=60건, baseline=4건/일 → ratio=15x, mentions=60 모두 통과
- 종목 W에 당일 `signal_type="surge_candidate"` 시그널이 이미 존재 (volume_anomaly 또는 일반 surge_candidate)

**When**: `detect_forum_mention_surge(db, ForumMentionConfig())` 호출

**Then**:
- 종목 W에 대해 시그널 생성 안 함 (중복 방지)
- 기존 시그널의 confidence/metadata 변경 없음

### AC-005: 탐지기 예외 발생 → 다른 시그널 파이프라인 미영향 (REQ-AI026-003)

**Given**:
- `_run_coverage_expansion()` 진입 시 surge_candidate, theme_propagation, volume_anomaly, near_limit_up_carry 시그널이 이미 DB에 commit됨
- `detect_forum_mention_surge()` 내부에서 예외 발생 (예: DB 연결 끊김 mock)

**When**: `_run_coverage_expansion(db, surge_results)` 호출

**Then**:
- 함수가 예외를 raise하지 않고 정상 반환
- 기존 surge_candidate / theme_propagation / volume_anomaly / near_limit_up_carry row가 DB에 그대로 보존됨
- `logger.warning` 호출 발생 (메시지에 "포럼언급" 또는 "forum" 포함)

### AC-006: baseline_avg_daily=0 (신규 종목) → 시그널 생성 안 함, 예외 없음 (REQ-AI026-001)

**Given**:
- 종목 N이 stocks 테이블에 존재 (예: 신규 상장)
- 최근 24시간 내 게시글 30건, 직전 7일간 게시글 0건 (baseline_avg_daily = 0.0)
- 당일 signal 부재

**When**: `detect_forum_mention_surge(db, ForumMentionConfig())` 호출

**Then**:
- 종목 N에 대해 시그널 생성 안 함 (division-by-zero 방지 가드)
- 예외 미발생
- 로그에 "baseline_skip" 카운트 1 이상

### AC-007: 당일 theme_propagation 시그널 존재 → 중복 생성 안 함 (REQ-AI026-001)

**Given**:
- 종목 V가 24h=40건, baseline=3건/일 → ratio=13x, 모든 조건 충족
- 종목 V에 당일 `signal_type="theme_propagation"` 시그널 존재

**When**: `detect_forum_mention_surge(db, ForumMentionConfig())` 호출

**Then**:
- 종목 V에 대해 신규 시그널 생성 안 함

### AC-008: enabled=False 시 탐지기 즉시 0 반환 (REQ-AI026-002)

**Given**: `ForumMentionConfig(enabled=False)` 인스턴스

**When**: `detect_forum_mention_surge(db, config)` 호출

**Then**:
- 즉시 0 반환
- DB 쿼리 0회 (mock assert)
- DB add 호출 0회

### AC-009: confidence 공식 정확성 (REQ-AI026-001)

**Given**: 다양한 (mentions_recent, baseline_avg_daily) 입력에 대한 confidence 계산

**When**: 수식 `round(min(ratio / 20.0, max_confidence), 4)` 적용

**Then** (`max_confidence=0.35` 기본값):
- mentions=10, baseline=2 → ratio=5.0 → `confidence = round(min(0.25, 0.35), 4) = 0.25`
- mentions=20, baseline=2 → ratio=10.0 → `confidence = round(min(0.5, 0.35), 4) = 0.35` (cap)
- mentions=14, baseline=2 → ratio=7.0 → `confidence = round(min(0.35, 0.35), 4) = 0.35` (cap 경계)
- mentions=12, baseline=2 → ratio=6.0 → `confidence = round(min(0.3, 0.35), 4) = 0.3`

### AC-010: stock_id IS NULL인 게시글은 평가 제외 (REQ-AI026-001)

**Given**:
- `stock_forum_posts`에 `stock_id=NULL`, `stock_code="999999"` 게시글 50건 존재 (FK 무결성 SET NULL 케이스)
- 다른 정상 stock_id를 가진 종목은 부재

**When**: `detect_forum_mention_surge(db, ForumMentionConfig())` 호출

**Then**:
- 시그널 생성 0건
- 평가 종목 수 0

---

## Implementation Notes

### 신규 함수 시그니처

```python
# backend/app/services/surge_detector.py
def detect_forum_mention_surge(
    db: Session,
    config: "ForumMentionConfig",  # noqa: F821 (지연 임포트)
) -> int:
    """SPEC-AI-026 REQ-001: 포럼 언급 급증 종목에 surge_candidate 시그널 생성.

    각 종목별로 (최근 mention_window_hours 게시글 수) vs (직전 baseline_days 일평균 게시글 수)
    비율을 계산하여 mention_multiplier 이상이고 절대값이 min_absolute_mentions 이상이면 시그널 발행.

    Returns: 생성된 시그널 수
    """
```

### Pydantic 설정 클래스 (surge_settings.py)

```python
class ForumMentionConfig(BaseModel):
    """SPEC-AI-026: 포럼 언급 급증 시그널 설정."""
    enabled: bool = True
    mention_multiplier: float = 5.0
    min_absolute_mentions: int = 10
    baseline_days: int = 7
    mention_window_hours: int = 24
    max_confidence: float = 0.35
```

### fund_manager._run_coverage_expansion 통합 지점

```python
def _run_coverage_expansion(db: Session, surge_results: list[dict]) -> None:
    # ... 기존 try 1: propagate_theme_group_signals
    # ... 기존 try 2: detect_volume_anomaly_dormant_stocks
    # ... 기존 try 3: detect_near_limit_up_carries

    try:
        from app.surge_config.surge_settings import ForumMentionConfig
        from app.services.surge_detector import detect_forum_mention_surge

        forum_config = ForumMentionConfig()
        forum_count = detect_forum_mention_surge(db, forum_config)
        logger.info("[커버리지확장] 포럼언급 급증 시그널 %d개 생성", forum_count)
    except Exception as e:
        logger.warning("[커버리지확장] 포럼언급 급증 탐지 실패 (다른 시그널 결과 보존됨): %s", e)
```

### 권장 SQL 쿼리 패턴 (RUN 단계 구현 참고)

```sql
-- 후보 종목 집계 (단일 쿼리)
WITH recent AS (
    SELECT stock_id, COUNT(*) AS mentions_recent
    FROM stock_forum_posts
    WHERE stock_id IS NOT NULL
      AND post_date >= NOW() - INTERVAL '24 hours'
    GROUP BY stock_id
    HAVING COUNT(*) >= 10  -- min_absolute_mentions
),
baseline AS (
    SELECT stock_id, COUNT(*) / 7.0 AS baseline_avg_daily
    FROM stock_forum_posts
    WHERE stock_id IS NOT NULL
      AND post_date >= NOW() - INTERVAL '8 days'
      AND post_date <  NOW() - INTERVAL '1 day'
    GROUP BY stock_id
)
SELECT r.stock_id, r.mentions_recent, b.baseline_avg_daily,
       (r.mentions_recent::float / b.baseline_avg_daily) AS ratio
FROM recent r
JOIN baseline b ON r.stock_id = b.stock_id
WHERE b.baseline_avg_daily > 0
  AND (r.mentions_recent::float / b.baseline_avg_daily) >= 5.0;
```

이후 Python에서 중복 시그널 체크 (당일 surge_candidate / theme_propagation / volume_anomaly 부재 검증) 후 FundSignal add.

### @MX Tag 계획

- `detect_forum_mention_surge()`: `@MX:NOTE` + `@MX:SPEC: SPEC-AI-026 REQ-001`. fan_in 예상 1 (`_run_coverage_expansion`에서만 호출).
- `ForumMentionConfig`: `@MX:NOTE` + `@MX:SPEC: SPEC-AI-026 REQ-002`.
- 두 SQL 쿼리가 stock_forum_posts 풀스캔에 가까우면 `@MX:WARN` + `@MX:REASON: post_date 인덱스 부재 시 풀스캔 위험` 권장 (RUN 단계에서 인덱스 확인 후 결정).

### 테스트 전략

- `backend/tests/test_forum_mention_surge.py` (신규) — REQ-AI026-001 (AC-001 ~ AC-004, AC-006 ~ AC-010)
- `backend/tests/test_coverage_expansion_integration.py` (확장) — REQ-AI026-003 (AC-005)
- 테스트 fixture: `stock_forum_posts`에 시간대별 게시글 직접 insert (forum_crawler mock 불필요)
- 목표 coverage: 신규 함수 90%+, 수정 파일 (`fund_manager.py`, `surge_settings.py`) 85%+

### 운영 고려사항

- **호출 시점**: `_run_coverage_expansion()`은 매 평일 15:20 KST 직후 호출. 본 SPEC 탐지기는 당일 09:00 ~ 15:20 게시글을 즉시 평가하여 익일 매수 큐에 진입.
- **DB 부담**: 일 평균 신규 시그널 5 ~ 20건 예상. 이슈 종목 (예: 테마주 폭발) 발생 시 50건 이상 가능. 향후 `max_signals_per_day` config 추가 검토.
- **인덱스 의존성**: `ix_forum_posts_stock_id`, `ix_forum_posts_collected_at`은 존재하나 `post_date` 단독 인덱스 부재. 쿼리 플랜 확인 후 `post_date` 인덱스 추가 필요 시 별도 마이그레이션 SPEC으로 분리.
- **paper_executed=True 정책**: 본 SPEC 시그널은 익일 매수 큐에 자동 진입한다 (SPEC-AI-013과 호환). 백테스트 검증 후 정책 조정은 별도 SPEC.

---

## Exclusions (What NOT to Build)

- **포럼 크롤러 변경**: `forum_crawler.crawl_and_aggregate` 로직 변경 금지. 본 SPEC은 이미 적재된 데이터를 소비만 한다.
- **`stock_forum_posts.post_date` 인덱스 추가**: 마이그레이션 변경 없음. RUN 단계에서 쿼리 플랜 확인 후 필요 시 별도 SPEC으로 분리.
- **새 DB 컬럼 추가**: `surge_metadata` JSON 내 표기로 충분. `fund_signals` 또는 `stock_forum_*` 테이블 스키마 변경 금지.
- **신규 마이그레이션 추가**: 본 SPEC은 DB 스키마 무변경.
- **자동봇/스팸 필터링**: nickname 패턴 분석, 동일 작성자 반복 게시 탐지는 본 SPEC 범위 외. 별도 SPEC.
- **sentiment 기반 가중**: bullish_ratio를 confidence에 반영하는 로직은 본 SPEC 범위 외 (단순히 게시글 수 변화율만 평가).
- **시간대별 가중 (예: 장 시작 후 1시간 가중)**: 균일 가중. 시간대별 분석은 별도 SPEC.
- **다중 baseline 비교 (예: 7일 + 30일)**: 7일 단일 baseline만 사용. 다중 baseline은 별도 SPEC.
- **신규 signal_type 도입**: `signal_type='surge_candidate'`를 그대로 사용. 새 enum 값 도입 금지.
- **target_price/stop_loss 자동 산정**: NULL로 발행. TP/SL은 매수 단계의 `surge_trading_service`에서 별도 산정.
- **`SurgeDetectionConfig`에 `forum_mention` 필드 추가**: `ForumMentionConfig`은 독립 instantiate. SurgeDetectionConfig 본체 변경 금지.
- **scheduler.py 호출 시간 변경**: 본 SPEC은 함수 시그니처와 로직만 정의.
- **프론트엔드 변경**: backend-only SPEC. 새 시그널의 UI 표시는 `surge_basis` 필드를 기존 UI가 처리.
- **외부 알림 (이메일/슬랙) 발송**: 본 SPEC은 시그널 생성만. 알림은 기존 briefing 시스템에 위임.
- **포럼 언급 급증 패턴의 ML 기반 적중률 학습**: 본 SPEC은 고정 confidence 공식. 동적 학습은 후속 SPEC.
- **시간당 윈도우 (예: 1시간, 3시간)**: 24시간 단일 윈도우만 사용. 단기 윈도우는 별도 SPEC.

---

## Delta Markers Summary

| Marker | File | Requirements |
|--------|------|--------------|
| `[NEW]` | `backend/app/services/surge_detector.py` (`detect_forum_mention_surge` 함수 추가) | REQ-AI026-001 |
| `[MODIFY]` | `backend/app/services/fund_manager.py` (`_run_coverage_expansion`에 호출 추가) | REQ-AI026-001, REQ-AI026-003 |
| `[MODIFY]` | `backend/app/surge_config/surge_settings.py` (`ForumMentionConfig` 클래스 추가) | REQ-AI026-002 |
| `[NEW]` | `backend/tests/test_forum_mention_surge.py` | AC-001 ~ AC-004, AC-006 ~ AC-010 |
| `[MODIFY]` | `backend/tests/test_coverage_expansion_integration.py` | AC-005 |

---

## Related SPECs

- **SPEC-AI-008** (선행, 필수): 종목토론방 크롤러 — `stock_forum_posts`, `stock_forum_hourly` 테이블 및 적재 파이프라인을 제공. 본 SPEC은 이 데이터의 소비자.
- **SPEC-AI-012** (선행): 급등 징후 탐지 — `surge_candidate` signal_type과 `surge_metadata.surge_basis` 패턴의 reference.
- **SPEC-AI-013** (선행): 급등예측 모의투자 포트폴리오 — `surge_trading_service.get_today_signals`의 signal_type 필터 (본 SPEC의 신규 시그널이 자동 통과).
- **SPEC-AI-022** (선행, 필수): 시그널 커버리지 확장 — `_run_coverage_expansion()` 통합 지점과 try/except 격리 패턴. 본 SPEC은 동일 패턴으로 4번째 탐지기를 추가.
- **SPEC-AI-023** (선행): 상한가 근접 carry-forward — 본 SPEC의 직전 try 블록(3번째). 동일 격리 패턴 적용.
- **SPEC-AI-018** (관련): 시장 레짐 분류 — 본 SPEC은 레짐 페널티 미적용 (단일 신호 + 절대값 필터로 충분히 보수적).

---

## Verification Checklist

- [ ] 모든 EARS 요구사항이 검증 가능한 인수 기준을 가진다 (AC-001 ~ AC-010)
- [ ] 신규 DB 마이그레이션 없음 확인 (스키마 무변경)
- [ ] 기존 `signal_type='surge_candidate'` 컬럼 의미 무변경 (필터 자동 통과)
- [ ] `surge_metadata` JSON 스키마에 `forum_mention_surge` surge_basis 키 추가만 (기존 키 변경 없음)
- [ ] `_run_coverage_expansion()` 내 4번째 try/except 격리로 다른 시그널 회귀 방지
- [ ] in-memory DB 또는 mock 기반 격리 테스트로 외부 의존성 차단
- [ ] target coverage 85%+ 명시, 신규 함수 90%+
- [ ] @MX 태그 계획 포함 (NOTE / SPEC, SQL 쿼리 인덱스 의존도에 따라 WARN 권고)
- [ ] `paper_executed=True` 기본값 (익일 매수 큐 진입 허용)
- [ ] confidence 공식 검증 가능 (`min(ratio/20, max_confidence)`, 기본 cap 0.35)
- [ ] division-by-zero 가드 검증 (`baseline_avg_daily > 0`)
- [ ] 중복 방지: 동일 종목에 당일 surge_candidate / theme_propagation / volume_anomaly 존재 시 스킵
- [ ] stock_id IS NULL row 평가 제외 보장
