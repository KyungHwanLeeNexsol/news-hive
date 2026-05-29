---
id: SPEC-AI-022
version: 0.1.0
status: implemented
created: 2026-05-29
updated: 2026-05-29
author: MoAI
priority: High
issue_number: 0
title: 시그널 커버리지 확장 — 테마 전파 및 비활성 종목 거래량 이상 탐지 (Signal Coverage Expansion)
---

# SPEC-AI-022: 시그널 커버리지 확장

## HISTORY

- 2026-05-29 (v0.1.0): 초안 작성. 2026-05-29 KST 라이브 급등 상위 30종목 분석에서 ① LG그룹 테마 cascade 시 LG씨엔에스(064400, +29.91%), 현대오토에버(307950, +24.80%), 솔루스첨단소재(336370, +25.70%)가 anchor 종목(LG전자/LG이노텍) 시그널이 발생했음에도 같은 영업일 시그널을 받지 못한 사건, ② 오브젠(417860, +29.93%), TS인베스트먼트(246690, +29.96%), 플리토(300080, +29.89%), 누리플랜(069140, +29.90%) 등 비활성 종목이 갑작스러운 +29%대 급등을 보였으나 거래량 이상 탐지 메커니즘 부재로 시그널이 전혀 발생하지 않은 사건을 기반으로 한 backend-only SPEC. 현재 68개/일 시그널(2,605종목 중 2.6% 커버리지)을 확장하기 위한 2종의 새 signal_type 도입과 관측용 coverage 엔드포인트를 정의한다.

---

## Overview

`surge_detector.py`의 현재 앙상블은 4개 탐지기(테마 클러스터, 거래량+뉴스 콤보, 공시 패턴, 즉각 공시)를 sector 기반으로 평가하나, 다음 두 가지 구조적 사각지대를 갖는다:

1. **재벌 그룹 cascade 미전파**: `detect_theme_news_cluster()`는 stock의 `sector_id`로만 propagation을 한다. LG그룹 cascade(IT 서비스 + 전기·전자 + 화학 + 2차전지 + 디스플레이 등 4~5개 sector를 가로지름)나 삼성그룹 cascade는 sector_id로 묶이지 않으므로 일부 sector에 속한 자회사·계열사는 anchor 종목이 강한 시그널을 받았음에도 propagation에서 누락된다.
2. **비활성 종목 거래량 이상 미감지**: 현재 4개 탐지기 모두 "뉴스+공시" 또는 "뉴스+거래량"의 결합 신호에 의존한다. 뉴스가 거의 없고 공시도 없으나 갑작스러운 거래량 폭증으로 급등하는 종목(오브젠, TS인베스트먼트, 플리토 등)은 어떤 탐지기도 발동시키지 못한다.

본 SPEC은 위 2가지 사각지대를 보완하는 4개 backend-only 요구사항을 정의한다. 핵심 설계 원칙은 **기존 surge_candidate 시그널 생성 로직을 변경하지 않는 가법적(additive) 확장**이다. 새 시그널은 별도의 `signal_type` 값으로 발행되며, 기본적으로 `paper_executed=False`로 시작해 자동 매수 큐에 진입하지 않는다(관측·검증 우선).

### Problem Background (2026-05-29 KST 실제 사례)

#### Group A — 테마 cascade 미전파 (LG그룹)

| 종목 | 코드 | 당일 등락 | 과거 시그널 이력 | 마지막 시그널 | 비고 |
|------|------|-----------|------------------|----------------|------|
| LG씨엔에스 | 064400 | +29.91% | 8건 | 2026-05-20 | LG그룹 IT 서비스 — 9일간 시그널 공백 |
| 현대오토에버 | 307950 | +24.80% | 3건 | 2026-05-28 | 현대차그룹 IT — 전일 신호 있었으나 당일 미전파 |
| 솔루스첨단소재 | 336370 | +25.70% | 2건 | 2026-05-20 | LG그룹 계열 화학 — 9일간 공백 |

같은 날 LG전자(066570)와 LG이노텍(011070)은 시그널을 받았으나 `min_probability=0.30` 필터에서 탈락(SPEC-AI-021로 부분 보정). 만약 anchor 종목인 LG전자가 `theme_cluster_score >= 0.80`을 받았다면, LG씨엔에스·솔루스첨단소재 등 LG그룹 계열사는 sector가 달라도 propagation 시그널을 받아야 한다.

#### Group B — 비활성 종목 거래량 이상 미감지

| 종목 | 코드 | 당일 등락 | 통산 시그널 수 | 마지막 시그널 |
|------|------|-----------|----------------|----------------|
| 오브젠 | 417860 | +29.93% | 0 | Never |
| TS인베스트먼트 | 246690 | +29.96% | 1 | 2026-04-02 |
| 플리토 | 300080 | +29.89% | 2 | 2026-04-03 |
| 누리플랜 | 069140 | +29.90% | 1 | 2026-04-06 |

이 4종목은 모두 거래량이 평소의 5~20배 폭증하며 상한가 또는 상한가 근처까지 급등했으나, 뉴스·공시가 거의 없어 기존 4개 탐지기가 침묵했다.

### Root Cause Analysis

1. **Sector 기반 propagation의 한계**: 현재 `cfg.sector_theme_map`은 `theme_keyword → sector_name` 매핑이며, 그룹 cascade를 표현할 수 없다. 그룹 단위 propagation은 별도 데이터 구조(`theme_groups` 테이블)와 anchor 기반 트리거가 필요하다.
2. **News+Volume 결합 가정**: `detect_volume_surge_news_combo`는 거래량 z-score AND 긍정 뉴스 두 조건을 모두 요구한다. 뉴스가 부재한 거래량 단독 폭증 종목은 영원히 탐지되지 않는다. 뉴스 없는 단독 거래량 폭증을 별도의 약한 신호(`volume_anomaly`)로 분리하여 관측 가능하게 만들어야 한다.
3. **관측 가시성 부재**: 현재 시스템은 "오늘 N개 시그널 발생"만 알 수 있고, "오늘 급등했으나 시그널을 받지 못한 종목"의 가시성이 없다. 커버리지 메트릭이 부재하므로 사각지대를 데이터로 식별할 수 없다.

본 SPEC은 위 3가지 근본 원인을 보정하는 4개 backend-only 요구사항을 정의한다. 1개의 신규 DB 마이그레이션(`theme_groups`, `stock_theme_groups` 테이블 추가)과 신규 `signal_type` 값 2개를 도입하나, 기존 `surge_candidate` 시그널 파이프라인은 변경하지 않는다.

### 전제 조건 (Assumptions)

- `fund_signals` 테이블은 `signal_type: str | None`, `confidence: float`, `surge_metadata: TEXT`(JSON), `paper_executed: bool` 컬럼을 이미 보유한다 (SPEC-AI-004, SPEC-AI-012).
- `stocks` 테이블은 `sector_id: int (FK)`, `stock_code: str`, `name: str`, `market_cap: int | None`을 보유한다.
- `surge_detector.gather_surge_candidates()`는 `list[SurgeCandidate]`를 반환하며 각 candidate는 `theme_cluster_score: float`, `stock_code: str`, `price_5d_trend: float | None` 필드를 갖는다 (SPEC-AI-012, SPEC-AI-018).
- `naver_finance.fetch_stock_price_history_sync(code, pages=N)`은 동기 호출 가능하며 `list[PriceRecord]`를 반환한다(최신순). 페이지당 약 10 거래일.
- `app/services/surge_trading_service.get_today_signals(db, min_probability)`는 `signal_type='surge_candidate'`로 필터링되므로 신규 `theme_propagation` / `volume_anomaly` 시그널은 매수 큐에서 자동 제외된다 (별도 코드 변경 불필요).
- 기존 API 계약(`POST /surge/execute`, `GET /surge/portfolio`, `GET /fund/signals`)의 응답 스키마는 변경하지 않는다.
- 신규 엔드포인트는 `/api/surge-trading` prefix 하에 추가되며 `_require_admin` 의존성 없이 read-only로 제공한다(기존 GET 엔드포인트와 동일 패턴).

---

## EARS Requirements

### REQ-AI022-001: 테마 전파 시그널 (Theme Propagation Signal)

**WHERE** `gather_surge_candidates()`가 반환한 후보군 중 anchor 종목이 `theme_cluster_score >= theme_propagation_trigger_threshold`(설정값, 기본 `0.80`)를 갖는 시그널이 당일 발행될 때, the system SHALL 해당 anchor 종목이 속한 모든 `ThemeGroup`을 조회하여 동일 그룹의 peer 종목들에 대해 propagation 후보 집합을 구성한다.

**WHEN** propagation 후보 집합을 평가할 때, the system SHALL 각 peer 종목에 대해 다음 조건을 모두 검사한다:
- (a) 오늘(`created_at >= today_kst_00:00:00`) peer 종목에 대한 `FundSignal`이 부재한다 (`signal_type` 무관 — surge_candidate, theme_propagation, volume_anomaly, disclosure_impact 등 모두 부재해야 함)
- (b) peer 종목의 자체 `price_5d_trend`가 `20.0` 미만이거나 알 수 없다 (이미 급등한 종목은 제외 — SPEC-AI-018 recent_surge_penalty 정책 준수)
- (c) anchor 종목과 peer 종목이 동일 `theme_group_id`에 함께 속한다

**IF** 세 조건 (a), (b), (c)가 모두 충족되면, **then** the system SHALL `signal_type="theme_propagation"`의 신규 `FundSignal` 레코드를 다음 값으로 생성한다:
- `confidence = theme_propagation_base_score` (설정값, 기본 `0.25`)
- `signal = "buy"` (기존 컬럼 NOT NULL 제약 준수)
- `reasoning` = `f"{anchor.name}({anchor.stock_code})의 theme_cluster_score={src_score:.3f} 신호를 {group.name} 그룹 내 propagation으로 전파"`
- `paper_executed = False` (매수 실행 큐에서 자동 제외)
- `surge_metadata` JSON: `{"surge_basis": ["theme_propagation"], "source_stock_code": anchor.stock_code, "source_theme_cluster_score": round(src_score, 4), "theme_group_id": group.id, "theme_group_name": group.name}`
- `signal_type = "theme_propagation"`
- 기타 필드(`target_price`, `stop_loss`, `price_at_signal`)는 NULL — propagation 신호는 가격 정보 없이 발행

**WHEN** 동일 peer 종목이 복수 (anchor, group) 쌍의 propagation 대상이 될 때, the system SHALL `source_theme_cluster_score`가 가장 높은 단일 row만 생성하고 나머지 후보는 폐기한다. 중복 row 생성은 금지된다.

**WHERE** anchor 종목 자체는, the system SHALL propagation 대상에서 제외한다(자기 자신에 대한 신호 중복 방지).

**WHERE** `ThemeGroup` 테이블에 anchor 종목이 속한 그룹이 없거나 그룹의 모든 peer가 조건 (a)~(c)를 충족하지 못하면, the system SHALL propagation 단계에서 정상적으로 0건의 신호를 생성하고 에러를 발생시키지 않는다.

**WHEN** propagation이 완료될 때, the system SHALL 생성된 propagation 시그널 수를 로깅한다 (`logger.info("[propagation] anchor=%s group=%s peers=%d propagated=%d", ...)`).

`[NEW]` `backend/app/services/surge_detector.py` — `propagate_theme_group_signals(db, qualified_candidates, config) -> list[FundSignal]` 신규 함수
`[MODIFY]` `backend/app/services/fund_manager.py` — `run_surge_signal_generation()` 내 surge_candidate 시그널 persist 직후 `propagate_theme_group_signals()` 호출 추가
`[NEW]` `backend/app/surge_config/surge_settings.py` — `ThemePropagationConfig(BaseModel)` Pydantic 클래스 신규 추가, `SurgeDetectionConfig`에 `theme_propagation: ThemePropagationConfig` 필드 추가

---

### REQ-AI022-002: 비활성 종목 거래량 이상 탐지 (Dormant Stock Volume Anomaly Detection)

**WHERE** 시스템이 일간 surge_candidate 시그널 생성을 완료한 직후, the system SHALL 다음 조건을 충족하는 종목군을 대상으로 별도의 거래량 이상 탐지를 수행한다:
- (a) 종목이 stocks 테이블에 존재하고 `market_cap >= dormant_min_market_cap_eok` (설정값, 기본 `300`억원 — 너무 작은 종목 제외)
- (b) 종목이 직전 `dormant_lookback_days`(설정값, 기본 `90`)일 동안 `signal_type='surge_candidate'`인 `FundSignal`을 `dormant_max_signals`(설정값, 기본 `3`)건 미만으로 받았다

**WHEN** 후보 종목군이 식별되면, the system SHALL 각 종목에 대해 `fetch_stock_price_history_sync(code, pages=volume_anomaly_pages)`(설정값, 기본 `pages=6`, 약 60 거래일)를 호출하여 거래량 히스토리를 조회한다. 히스토리가 `volume_baseline_min_days`(설정값, 기본 `40`)일 미만이면, the system SHALL 해당 종목을 스킵한다.

**WHEN** 거래량 데이터가 충분할 때, the system SHALL 다음을 계산한다:
- `today_volume = history[0].volume` (최신순 정렬 기준 첫 레코드)
- `baseline_volumes = [r.volume for r in history[1:61]]` (당일 제외, 직전 60일)
- `mean_baseline = mean(baseline_volumes)` — 0이면 종목 스킵
- `volume_ratio = today_volume / mean_baseline`

**IF** `volume_ratio >= volume_anomaly_threshold`(설정값, 기본 `5.0`), **then** the system SHALL `signal_type="volume_anomaly"`의 신규 `FundSignal` 레코드를 다음 값으로 생성한다:
- `confidence = min(volume_ratio / 10.0, volume_anomaly_max_confidence)` (설정값 max, 기본 `0.40`)
- `signal = "buy"` (NOT NULL 제약 준수)
- `reasoning` = `f"비활성 종목 거래량 이상 — 당일 거래량 {today_volume:,}주는 60일 평균 {int(mean_baseline):,}주의 {volume_ratio:.1f}배"`
- `paper_executed = False`
- `surge_metadata` JSON: `{"surge_basis": ["volume_anomaly"], "is_dormant_stock": True, "volume_ratio": round(volume_ratio, 2), "today_volume": today_volume, "baseline_mean_volume": int(mean_baseline), "baseline_days": len(baseline_volumes), "lookback_signal_count": signal_count_in_lookback}`
- `signal_type = "volume_anomaly"`

**WHERE** 거래량 폭증 종목이 같은 날 `signal_type='surge_candidate'` 시그널도 받았으면, the system SHALL `volume_anomaly` 시그널을 중복 생성하지 않는다 (surge_candidate가 이미 신호로 충분하므로 중복 회피).

**WHERE** 거래량 폭증 종목이 같은 날 `signal_type='theme_propagation'` 시그널을 받았으면, the system SHALL 양쪽 모두 유지한다(서로 다른 정보를 표현).

**WHEN** volume_anomaly 탐지가 완료될 때, the system SHALL 후보 종목 수, 평가 종목 수, 생성된 시그널 수를 로깅한다.

**WHERE** 본 단계는 외부 API(`naver_finance`) 호출이 많아 운영 환경 영향을 최소화하기 위해, the system SHALL 일간 surge_candidate 시그널 persist 완료 후, 별도의 `try/except` 블록 내에서 실행하며 예외 발생 시 로깅 후 surge_candidate 결과를 손상시키지 않고 정상 종료한다.

`[NEW]` `backend/app/services/surge_detector.py` — `detect_volume_anomaly_dormant_stocks(db, config) -> list[FundSignal]` 신규 함수
`[MODIFY]` `backend/app/services/fund_manager.py` — `run_surge_signal_generation()` 내 propagation 호출 이후 `detect_volume_anomaly_dormant_stocks()` 호출 추가
`[NEW]` `backend/app/surge_config/surge_settings.py` — `VolumeAnomalyConfig(BaseModel)` Pydantic 클래스 신규 추가, `SurgeDetectionConfig`에 `volume_anomaly: VolumeAnomalyConfig` 필드 추가

---

### REQ-AI022-003: 테마 그룹 데이터 모델 및 초기 시드 (Theme Group Schema and Seed Data)

**WHERE** 시스템이 그룹 단위 propagation을 지원해야 할 때, the system SHALL `theme_groups`와 `stock_theme_groups` 두 신규 테이블을 도입한다.

**WHEN** Alembic 마이그레이션 `037_spec_ai_022_theme_groups.py`이 적용될 때, the system SHALL `theme_groups` 테이블을 다음 스키마로 생성한다:
- `id: Integer PRIMARY KEY AUTOINCREMENT`
- `name: String(100) NOT NULL UNIQUE`
- `anchor_stock_id: Integer NULL FOREIGN KEY REFERENCES stocks.id ON DELETE SET NULL`
- `description: Text NULL`
- `created_at: TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()`

**WHEN** 같은 마이그레이션이 적용될 때, the system SHALL `stock_theme_groups` 조인 테이블을 다음 스키마로 생성한다:
- `id: Integer PRIMARY KEY AUTOINCREMENT`
- `stock_id: Integer NOT NULL FOREIGN KEY REFERENCES stocks.id ON DELETE CASCADE`
- `theme_group_id: Integer NOT NULL FOREIGN KEY REFERENCES theme_groups.id ON DELETE CASCADE`
- `weight: Float NOT NULL DEFAULT 1.0`
- `created_at: TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()`
- UNIQUE CONSTRAINT `(stock_id, theme_group_id)` — 동일 (stock, group) 중복 방지
- INDEX on `theme_group_id` — 그룹 → peer 조회 성능

**WHEN** 마이그레이션 적용 시, the system SHALL 다음 초기 그룹을 `theme_groups`에 INSERT 한다(SQL NOT EXISTS 조건부 INSERT로 idempotent 보장):

| name | anchor (stock_code by name lookup) | description |
|------|------------------------------------|-------------|
| LG그룹 | LG전자 (코드 066570) | LG 계열사 전반 |
| 삼성그룹 | 삼성전자 (코드 005930) | 삼성 계열사 전반 |
| 현대차그룹 | 현대차 (코드 005380) | 현대자동차 계열사 전반 |
| SK그룹 | SK하이닉스 (코드 000660) | SK 계열사 전반 |

**WHEN** 그룹 INSERT 후, the system SHALL 다음 종목들을 `stock_theme_groups`에 (stock_code 룩업 후) INSERT 한다. 룩업 실패(`stocks` 테이블에 stock_code 부재) 시 해당 row만 스킵하고 마이그레이션은 성공으로 완료된다:

- **LG그룹** (`weight=1.0`): 003550 (LG), 066570 (LG전자), 011070 (LG이노텍), 064400 (LG씨엔에스), 051910 (LG화학), 373220 (LG에너지솔루션), 034220 (LG디스플레이), 032640 (LG유플러스), 336370 (솔루스첨단소재)
- **삼성그룹** (`weight=1.0`): 005930 (삼성전자), 006400 (삼성SDI), 018260 (삼성에스디에스), 009150 (삼성전기), 207940 (삼성바이오로직스), 028260 (삼성물산), 032830 (삼성생명)
- **현대차그룹** (`weight=1.0`): 005380 (현대차), 000270 (기아), 012330 (현대모비스), 307950 (현대오토에버), 086280 (현대글로비스), 000720 (현대건설)
- **SK그룹** (`weight=1.0`): 000660 (SK하이닉스), 017670 (SK텔레콤), 096770 (SK이노베이션), 402340 (SK스퀘어), 034730 (SK), 011790 (SKC)

**WHERE** anchor_stock_id를 설정할 때, the system SHALL anchor 종목의 stock_code를 stocks 테이블에서 룩업하고, 존재하면 `theme_groups.anchor_stock_id`에 채우고, 부재하면 NULL을 유지한다(이후 수동 보정 가능).

**WHEN** `downgrade()`가 호출될 때, the system SHALL `stock_theme_groups` 테이블 DROP 후 `theme_groups` 테이블 DROP을 순서대로 수행한다.

**WHEN** `backend/app/models/theme_group.py` 신규 SQLAlchemy 모델이 정의될 때, the system SHALL `ThemeGroup` 클래스에 `stocks: relationship("Stock", secondary="stock_theme_groups", back_populates="theme_groups")` 및 `anchor_stock: relationship("Stock", foreign_keys=[anchor_stock_id])`를 정의하고, `Stock` 모델에 `theme_groups: relationship("ThemeGroup", secondary="stock_theme_groups", back_populates="stocks")`를 추가한다.

**WHERE** Stock 모델의 기존 컬럼·관계는, the system SHALL 변경하지 않는다(추가 only).

`[NEW]` `backend/app/models/theme_group.py` — `ThemeGroup`, `StockThemeGroup` SQLAlchemy 모델
`[MODIFY]` `backend/app/models/stock.py` — `theme_groups` 관계 추가 (기존 필드 변경 금지)
`[MODIFY]` `backend/app/models/__init__.py` — `ThemeGroup`, `StockThemeGroup` 임포트 추가
`[NEW]` `backend/alembic/versions/037_spec_ai_022_theme_groups.py` — 스키마 + 시드 마이그레이션 (down_revision=036)

---

### REQ-AI022-004: 시그널 커버리지 대시보드 API (Coverage Dashboard Endpoint)

**WHERE** 운영 관측 가시성을 위해 새 read-only 엔드포인트가 필요할 때, the system SHALL `GET /api/surge-trading/coverage` 엔드포인트를 `app/routers/surge_trading.py`에 추가한다.

**WHEN** 엔드포인트가 호출될 때, the system SHALL 다음 필드를 갖는 JSON 응답을 반환한다:

```json
{
  "as_of": "2026-05-29T15:30:00+09:00",
  "total_stocks_tracked": 2605,
  "signals_generated_today": 68,
  "coverage_pct": 2.61,
  "by_signal_type": {
    "surge_candidate": 68,
    "theme_propagation": 12,
    "volume_anomaly": 5,
    "disclosure_impact": 3
  },
  "theme_propagation_triggered": 12,
  "volume_anomaly_triggered": 5,
  "top_missed": [
    {
      "stock_code": "417860",
      "name": "오브젠",
      "change_pct": 29.93,
      "market_cap_eok": 350,
      "has_any_signal_today": false
    }
  ]
}
```

**WHEN** `as_of` 필드를 계산할 때, the system SHALL `datetime.now(ZoneInfo("Asia/Seoul"))`을 ISO 8601 형식으로 반환한다.

**WHEN** `total_stocks_tracked` 필드를 계산할 때, the system SHALL `SELECT COUNT(*) FROM stocks` 단일 쿼리로 산출한다.

**WHEN** `signals_generated_today` 필드를 계산할 때, the system SHALL 당일 KST 00:00:00 이후 생성된 `FundSignal` 중 `signal_type='surge_candidate'`인 행 수를 반환한다. `theme_propagation`이나 `volume_anomaly`는 포함하지 않는다(기존 정의 유지).

**WHEN** `coverage_pct` 필드를 계산할 때, the system SHALL `round(signals_generated_today / total_stocks_tracked * 100, 2)`를 반환하며, `total_stocks_tracked == 0`이면 `0.0`을 반환한다.

**WHEN** `by_signal_type` 필드를 계산할 때, the system SHALL 당일 생성된 모든 `FundSignal`을 `signal_type`별로 GROUP BY COUNT 하여 dict로 반환한다. NULL `signal_type`은 키 `"unspecified"`로 집계한다.

**WHEN** `theme_propagation_triggered`와 `volume_anomaly_triggered` 필드를 계산할 때, the system SHALL `by_signal_type.get("theme_propagation", 0)` 및 `by_signal_type.get("volume_anomaly", 0)`을 각각 반환한다.

**WHEN** `top_missed` 필드를 계산할 때, the system SHALL 다음 절차를 따른다:
1. `stocks` 테이블에서 `market_cap >= coverage_missed_min_market_cap_eok`(설정값, 기본 `1000`억원) 종목을 조회한다.
2. 각 종목에 대해 당일 `FundSignal`이 존재하는지 확인한다(모든 `signal_type` 포함). 존재하면 제외한다.
3. 제외 후 남은 종목에 대해 `fetch_current_price_with_change_sync(code)`를 호출하여 `change_rate`을 수집한다. 호출 실패 시 해당 종목 스킵.
4. `change_rate >= coverage_missed_change_threshold_pct`(설정값, 기본 `15.0`)인 종목만 유지한다.
5. `change_rate` 내림차순 정렬 후 상위 `coverage_missed_limit`(설정값, 기본 `10`)건만 반환한다.

**WHERE** `top_missed` 계산이 일정 시간(설정값 `coverage_top_missed_timeout_sec`, 기본 `15.0`초)을 초과할 때, the system SHALL 부분 결과(타임아웃 시점까지 수집된 종목)를 반환하며 `top_missed_partial: true` 플래그를 응답에 추가한다.

**WHERE** `_require_admin` 의존성은, the system SHALL 본 엔드포인트에 적용하지 않는다(read-only 관측용, 기존 `GET /api/surge-trading/portfolio`와 동일).

**WHEN** DB 쿼리 또는 가격 API 호출이 실패할 때, the system SHALL HTTP 500을 반환하지 않고 가능한 부분 결과로 응답을 구성한다. 단, `total_stocks_tracked` 쿼리 자체가 실패하면 HTTP 500을 반환한다.

**WHEN** 응답을 캐싱할 때, the system SHALL `coverage_cache_ttl_sec`(설정값, 기본 `60`초) 동안 in-memory 캐시를 사용하여 반복 호출 시 부담을 줄인다.

**WHERE** 외부 API 응답(`POST /surge/execute` 등 기존 엔드포인트)의 스키마는, the system SHALL 변경하지 않는다.

`[NEW]` `backend/app/routers/surge_trading.py` — `GET /coverage` 엔드포인트 추가
`[NEW]` `backend/app/schemas/surge_trading_coverage.py` — Pydantic 응답 모델 (`CoverageResponse`, `TopMissedStock`)
`[NEW]` `backend/app/services/surge_coverage_service.py` — `compute_coverage_snapshot(db, config) -> CoverageResponse` 비즈니스 로직
`[MODIFY]` `backend/app/surge_config/surge_settings.py` — `CoverageDashboardConfig(BaseModel)` Pydantic 클래스 추가

---

## Acceptance Criteria

각 요구사항별 검증 가능한 인수 기준. 모든 테스트는 신규 파일 또는 기존 테스트 파일에 추가한다. 외부 의존성(DB, 가격 API, 뉴스 API)은 mock으로 격리한다.

### AC-001: anchor 종목 강한 신호 시 동일 그룹 peer에 propagation 시그널 생성 (REQ-AI022-001)

**Given**:
- DB에 `ThemeGroup(id=1, name="LG그룹", anchor_stock_id=lg_elec.id)`이 존재
- LG전자(066570), LG씨엔에스(064400), 솔루스첨단소재(336370)가 모두 LG그룹 멤버로 `stock_theme_groups`에 등록
- `qualified_candidates`에 LG전자가 `theme_cluster_score=0.85`로 포함
- LG씨엔에스, 솔루스첨단소재에 대한 당일 FundSignal이 부재
- LG씨엔에스의 `price_5d_trend = 5.0` (페널티 미적용)

**When**: `propagate_theme_group_signals(db, qualified_candidates, config)` 호출

**Then**:
- LG씨엔에스에 대해 `signal_type="theme_propagation"`, `confidence=0.25`, `paper_executed=False` 시그널 1건 생성
- 솔루스첨단소재에 대해 동일한 시그널 1건 생성
- LG전자(anchor 자기 자신)에 대해서는 propagation 시그널 미생성
- 각 시그널의 `surge_metadata`에 `source_stock_code="066570"`, `source_theme_cluster_score=0.85`, `theme_group_name="LG그룹"` 포함
- 함수 반환값 `len(result) == 2`

### AC-002: peer 종목에 당일 시그널 이미 존재 시 propagation 미생성 (REQ-AI022-001)

**Given**:
- AC-001과 동일한 그룹 설정
- LG씨엔에스에 대한 `signal_type="surge_candidate"` 시그널이 당일 이미 존재
- 솔루스첨단소재에 대해서는 당일 시그널 부재

**When**: `propagate_theme_group_signals(db, qualified_candidates, config)` 호출

**Then**:
- LG씨엔에스에 대해서는 propagation 시그널 미생성 (이미 존재)
- 솔루스첨단소재에 대해서는 propagation 시그널 1건 생성
- 함수 반환값 `len(result) == 1`

### AC-003: peer 종목의 5일 수익률 > 20% 시 propagation 미생성 (REQ-AI022-001)

**Given**:
- AC-001과 동일한 그룹 설정
- LG씨엔에스의 `price_5d_trend = 25.0` (이미 급등)
- 솔루스첨단소재의 `price_5d_trend = 5.0`

**When**: `propagate_theme_group_signals(db, qualified_candidates, config)` 호출, peer의 price_5d_trend 조회는 mock 주입

**Then**:
- LG씨엔에스에 대해서는 propagation 시그널 미생성 (recent_surge_penalty 정책)
- 솔루스첨단소재에 대해서는 propagation 시그널 1건 생성

### AC-004: 동일 peer가 복수 그룹의 propagation 대상일 때 최고 점수 단일 row만 생성 (REQ-AI022-001)

**Given**:
- 삼성SDI(006400)가 "삼성그룹"과 "2차전지 밸류체인" 두 그룹에 모두 속함
- 삼성전자(005930) anchor가 `theme_cluster_score=0.82`로 qualified
- LG에너지솔루션(373220) anchor가 `theme_cluster_score=0.90`으로 qualified
- 삼성SDI에 대한 당일 시그널 부재

**When**: `propagate_theme_group_signals` 호출

**Then**:
- 삼성SDI에 대해 propagation 시그널 **1건만** 생성 (중복 방지)
- 생성된 시그널의 `source_theme_cluster_score = 0.90` (높은 점수)
- 생성된 시그널의 `source_stock_code = "373220"` (LG에너지솔루션)

### AC-005: anchor가 theme_cluster_score < threshold일 때 propagation 미발동 (REQ-AI022-001)

**Given**:
- `theme_propagation_trigger_threshold = 0.80`
- LG전자가 `theme_cluster_score=0.75`로 qualified (다른 detector 점수로 통과)

**When**: `propagate_theme_group_signals` 호출

**Then**:
- propagation 시그널 0건 생성
- 로그에 anchor 미충족 메시지

### AC-006: 5배 이상 거래량 폭증 + dormant 조건 충족 시 volume_anomaly 시그널 생성 (REQ-AI022-002)

**Given**:
- 오브젠(417860)이 stocks 테이블에 `market_cap=500`(억원)로 존재
- 직전 90일간 surge_candidate 시그널 0건
- `fetch_stock_price_history_sync("417860", pages=6)` mock이 60일 데이터 반환:
  - `history[0].volume = 5_000_000` (오늘)
  - `history[1..60]`의 평균 volume = 500_000 (10배 비율)

**When**: `detect_volume_anomaly_dormant_stocks(db, config)` 호출

**Then**:
- `signal_type="volume_anomaly"` 시그널 1건 생성
- `confidence = min(10.0 / 10.0, 0.40) = 0.40`
- `surge_metadata` JSON에 `volume_ratio=10.0`, `is_dormant_stock=True`, `today_volume=5000000`, `baseline_mean_volume=500000` 포함
- `paper_executed=False`

### AC-007: dormancy 조건 위배 시 volume_anomaly 시그널 미생성 (REQ-AI022-002)

**Given**:
- 종목 A가 직전 90일 동안 `signal_type='surge_candidate'` 시그널을 5건 받음 (`dormant_max_signals=3` 초과)
- 거래량은 5배 이상 폭증

**When**: `detect_volume_anomaly_dormant_stocks(db, config)` 호출

**Then**: 종목 A에 대해 volume_anomaly 시그널 미생성

### AC-008: 거래량 데이터 부족 시 종목 스킵 (REQ-AI022-002)

**Given**:
- 종목 B가 dormant 조건 충족
- `fetch_stock_price_history_sync("B", pages=6)` mock이 30일 데이터만 반환 (`< volume_baseline_min_days=40`)

**When**: `detect_volume_anomaly_dormant_stocks` 호출

**Then**:
- 종목 B에 대해 volume_anomaly 시그널 미생성
- 로그에 "데이터 부족" 메시지
- 예외 미발생

### AC-009: 거래량 폭증 + 당일 surge_candidate 시그널 존재 시 중복 회피 (REQ-AI022-002)

**Given**:
- 종목 C가 dormant 조건 충족하고 거래량 10배 폭증
- 종목 C에 당일 `signal_type='surge_candidate'` 시그널이 이미 존재

**When**: `detect_volume_anomaly_dormant_stocks` 호출

**Then**: 종목 C에 volume_anomaly 시그널 미생성 (surge_candidate가 우선)

### AC-010: 마이그레이션 upgrade 후 theme_groups에 4개 그룹 INSERT 완료 (REQ-AI022-003)

**Given**: SQLite in-memory DB에 migration 035 + 036 적용 완료

**When**: `alembic upgrade head` 실행 (037 적용)

**Then**:
- `SELECT COUNT(*) FROM theme_groups` == 4
- `SELECT name FROM theme_groups ORDER BY name` returns ["LG그룹", "SK그룹", "삼성그룹", "현대차그룹"]
- 사전에 005930 (삼성전자), 066570 (LG전자) 등 anchor 종목이 stocks에 INSERT 되어 있다면 `anchor_stock_id`가 NULL이 아니다
- anchor 종목이 stocks에 부재하면 anchor_stock_id는 NULL (마이그레이션은 성공)

### AC-011: stock_theme_groups에 멤버십 INSERT 시 stock_code 룩업 실패 row 스킵 (REQ-AI022-003)

**Given**:
- 마이그레이션 035, 036 적용 후
- stocks 테이블에 LG전자(066570), 삼성전자(005930)만 INSERT (다른 LG/삼성 계열사 부재)

**When**: `alembic upgrade head` 실행

**Then**:
- `theme_groups` 4건 INSERT 성공
- `stock_theme_groups`에 LG전자(LG그룹), 삼성전자(삼성그룹) 두 row만 INSERT
- 부재 종목(LG씨엔에스, 삼성SDI 등) row는 스킵
- 마이그레이션 exit code 0

### AC-012: downgrade 시 theme_groups, stock_theme_groups 모두 DROP (REQ-AI022-003)

**Given**: 037 마이그레이션 적용 완료 상태

**When**: `alembic downgrade -1` 실행

**Then**:
- `theme_groups`, `stock_theme_groups` 테이블 모두 부재
- stocks 테이블은 변경 없음
- `alembic upgrade head` 재실행 시 정상 적용 (idempotent)

### AC-013: GET /api/surge-trading/coverage 기본 응답 스키마 (REQ-AI022-004)

**Given**:
- stocks 테이블에 2605건
- 당일 surge_candidate 시그널 68건, theme_propagation 12건, volume_anomaly 5건 존재

**When**: `GET /api/surge-trading/coverage` 호출

**Then**: 응답이 다음 스키마를 만족
- HTTP 200
- `total_stocks_tracked == 2605`
- `signals_generated_today == 68` (surge_candidate만 카운트)
- `coverage_pct == 2.61`
- `by_signal_type == {"surge_candidate": 68, "theme_propagation": 12, "volume_anomaly": 5}`
- `theme_propagation_triggered == 12`
- `volume_anomaly_triggered == 5`
- `as_of` 필드가 ISO 8601 형식
- `top_missed` 필드가 list

### AC-014: top_missed가 change_pct 내림차순으로 정렬되고 상한 적용 (REQ-AI022-004)

**Given**:
- `market_cap >= 1000`억원 종목 20개가 stocks에 존재
- 그 중 8개가 당일 시그널 없고 change_pct >= 15.0
- 8개의 change_pct: [29.9, 28.5, 25.0, 22.0, 20.0, 18.5, 17.0, 15.5]
- `coverage_missed_limit = 10`

**When**: `GET /api/surge-trading/coverage` 호출

**Then**:
- `len(top_missed) == 8`
- `top_missed[0].change_pct == 29.9`
- `top_missed[-1].change_pct == 15.5`
- 내림차순 정렬 보장
- 각 항목에 `stock_code`, `name`, `change_pct`, `market_cap_eok`, `has_any_signal_today=false` 포함

### AC-015: top_missed 타임아웃 시 partial 플래그 (REQ-AI022-004)

**Given**:
- `coverage_top_missed_timeout_sec = 0.1` (테스트용 매우 짧은 값)
- 가격 API mock이 종목마다 50ms 지연

**When**: `GET /api/surge-trading/coverage` 호출

**Then**:
- HTTP 200 반환
- `top_missed_partial == true`
- `top_missed`는 비어있거나 일부 종목만 포함
- `total_stocks_tracked`, `signals_generated_today`는 정상 반환

### AC-016: 캐시 적용 시 60초 내 반복 호출 시 동일 응답 (REQ-AI022-004)

**Given**: `coverage_cache_ttl_sec = 60`

**When**: 동일 endpoint를 1초 간격으로 2회 호출

**Then**:
- 2회 응답이 byte-level identical (동일 `as_of` 포함)
- 2번째 호출은 DB 쿼리를 수행하지 않음 (mock assert)

### AC-017: 기존 surge_candidate 생성 파이프라인 회귀 없음 (Cross-cutting)

**Given**: 기존 `gather_surge_candidates()`가 4개 후보를 반환하는 시나리오

**When**: `run_surge_signal_generation()` 호출 (REQ-AI022-001, REQ-AI022-002 통합 후)

**Then**:
- 4개 `signal_type='surge_candidate'` 시그널이 기존과 동일하게 persist됨
- 추가로 propagation/volume_anomaly 시그널이 발행되더라도 기존 surge_candidate row 수·내용·persist 순서는 변경되지 않음
- propagation/volume_anomaly 단계에서 예외 발생 시에도 surge_candidate 시그널은 정상 commit (격리된 try/except)

### AC-018: get_today_signals는 신규 signal_type을 매수 큐에서 자동 제외 (Cross-cutting)

**Given**:
- DB에 당일 `signal_type='surge_candidate'` 1건, `signal_type='theme_propagation'` 5건, `signal_type='volume_anomaly'` 3건 존재

**When**: `get_today_signals(db, min_probability=Decimal("0.30"))` 호출

**Then**:
- 반환된 list에는 surge_candidate 종목만 포함 (확률 통과 시)
- propagation/volume_anomaly 종목은 자동 제외 (signal_type 필터로 인해)
- `get_today_signals` 함수 자체 코드는 변경 없음

---

## Implementation Notes

### 신규 함수 시그니처

```python
# surge_detector.py
def propagate_theme_group_signals(
    db: Session,
    qualified_candidates: list[SurgeCandidate],
    config: SurgeDetectionConfig,
) -> list[FundSignal]:
    """REQ-AI022-001"""

def detect_volume_anomaly_dormant_stocks(
    db: Session,
    config: SurgeDetectionConfig,
) -> list[FundSignal]:
    """REQ-AI022-002"""
```

```python
# surge_coverage_service.py
def compute_coverage_snapshot(
    db: Session,
    config: CoverageDashboardConfig,
) -> CoverageResponse:
    """REQ-AI022-004"""
```

### Pydantic 설정 클래스 추가 (surge_settings.py)

```python
class ThemePropagationConfig(BaseModel):
    enabled: bool = True
    trigger_threshold: float = 0.80         # anchor's theme_cluster_score floor
    base_score: float = 0.25                # propagated confidence
    suppress_if_5d_trend_above: float = 20.0

class VolumeAnomalyConfig(BaseModel):
    enabled: bool = True
    threshold: float = 5.0                  # volume_ratio threshold
    max_confidence: float = 0.40
    lookback_days: int = 90
    max_signals_in_lookback: int = 3
    min_market_cap_eok: int = 300
    pages: int = 6                          # naver_finance pages
    baseline_min_days: int = 40

class CoverageDashboardConfig(BaseModel):
    enabled: bool = True
    cache_ttl_sec: float = 60.0
    missed_min_market_cap_eok: int = 1000
    missed_change_threshold_pct: float = 15.0
    missed_limit: int = 10
    top_missed_timeout_sec: float = 15.0
```

### fund_manager.run_surge_signal_generation 통합 지점

```python
async def run_surge_signal_generation(...):
    # ... existing surge_candidate generation and persist ...
    db.commit()  # surge_candidate commit

    # REQ-AI022-001: theme propagation (isolated)
    try:
        from app.services.surge_detector import propagate_theme_group_signals
        if config.theme_propagation.enabled:
            propagation_signals = propagate_theme_group_signals(db, qualified, config)
            for sig in propagation_signals:
                db.add(sig)
            db.commit()
            logger.info("[propagation] %d signals generated", len(propagation_signals))
    except Exception as e:
        db.rollback()
        logger.error("[propagation] failed: %s", e, exc_info=True)

    # REQ-AI022-002: volume anomaly (isolated)
    try:
        from app.services.surge_detector import detect_volume_anomaly_dormant_stocks
        if config.volume_anomaly.enabled:
            anomaly_signals = detect_volume_anomaly_dormant_stocks(db, config)
            for sig in anomaly_signals:
                db.add(sig)
            db.commit()
            logger.info("[volume_anomaly] %d signals generated", len(anomaly_signals))
    except Exception as e:
        db.rollback()
        logger.error("[volume_anomaly] failed: %s", e, exc_info=True)
```

### @MX Tag 계획

- `propagate_theme_group_signals()`: `@MX:NOTE` + `@MX:SPEC: SPEC-AI-022 REQ-001`. fan_in 예상 1 (fund_manager에서만 호출).
- `detect_volume_anomaly_dormant_stocks()`: `@MX:NOTE` + `@MX:SPEC: SPEC-AI-022 REQ-002` + `@MX:WARN` (외부 API 호출 다수, 동기 컨텍스트). `@MX:REASON`: 60일 거래량 베이스라인 계산용 naver_finance 동기 호출, 후보 수 제한으로 latency 관리.
- `compute_coverage_snapshot()`: `@MX:NOTE` + `@MX:SPEC: SPEC-AI-022 REQ-004`. fan_in 예상 1 (router에서만 호출).
- `ThemeGroup`, `StockThemeGroup` 모델: `@MX:NOTE` + `@MX:SPEC: SPEC-AI-022 REQ-003`.

### 테스트 전략

- `backend/tests/test_theme_propagation.py` (신규) — REQ-AI022-001 (AC-001~AC-005)
- `backend/tests/test_volume_anomaly.py` (신규) — REQ-AI022-002 (AC-006~AC-009)
- `backend/tests/test_theme_groups_migration.py` (신규) — REQ-AI022-003 (AC-010~AC-012), SQLite in-memory Alembic 실행
- `backend/tests/test_coverage_endpoint.py` (신규) — REQ-AI022-004 (AC-013~AC-016), FastAPI TestClient
- `backend/tests/test_surge_signal_generation_integration.py` (확장) — Cross-cutting (AC-017, AC-018)
- 외부 의존성(naver_finance, DB price API) mock 주입 — 기존 `_price_change_provider`, `_volume_provider` 패턴 활용
- 목표 coverage: 신규 파일 90%+, 수정 파일(`surge_detector.py`, `fund_manager.py`, `surge_trading.py`, `stock.py`) 85%+

### 운영 고려사항

- propagation은 평균 추가 10~30 시그널/일 예상 (4개 그룹 × 평균 5 peer × 활성 확률 50%). DB 부담 미미.
- volume_anomaly는 후보 집합이 dormant 필터로 좁혀짐 (예상 100~300종목/일). naver_finance 호출 100~300회 × 평균 500ms = 50~150초. 09:05 batch 이후 별도 슬롯에서 실행하거나 비동기 background task로 분리.
- coverage 엔드포인트의 top_missed 계산은 캐시되므로 호출 빈도가 1분당 1회 미만이면 부담 무시 가능.

---

## Exclusions (What NOT to Build)

- **`surge_candidate` 시그널 생성 로직 변경**: 기존 4개 탐지기, 앙상블 가중치, 임계값, recent_surge_penalty 로직은 변경 금지. SPEC-AI-022는 가법적 확장만.
- **`get_today_signals` 함수 변경**: 신규 signal_type은 자동 제외되므로 코드 변경 불필요.
- **매수 큐(execute_buy_orders)에 propagation/volume_anomaly 통합**: 본 SPEC은 관측·검증 단계. paper_executed 자동 마킹·매수 실행은 별도 후속 SPEC.
- **min_probability 임계값 전역 변경**: SPEC-AI-021의 부스트 로직과 무관. 본 SPEC은 새 signal_type만 도입.
- **확장 가능한 그룹 cascade 분석(2단계 propagation)**: anchor → peer 한 단계만. peer → peer'의 추가 propagation 금지.
- **theme_groups 동적 학습/자동 생성**: 초기 4개 그룹은 수동 시드. ML 기반 자동 그룹 발견은 별도 SPEC.
- **volume_anomaly의 take_profit/stop_loss 설정**: `target_price`, `stop_loss` 모두 NULL. 매수 시 적용할 TP/SL은 별도 SPEC.
- **`detect_volume_surge_news_combo`의 거래량 z-score 임계값 완화**: 본 SPEC은 별도 탐지기를 추가. 기존 탐지기는 손대지 않는다.
- **프론트엔드 변경**: backend-only SPEC. 새 시그널의 UI 표시, coverage dashboard UI는 별도 작업.
- **fund_manager.py의 buy/sell/hold 레거시 시그널 변경**: SPEC-AI-022는 surge_* 계열만 다룬다.
- **신규 컬럼 `fund_signals.theme_group_id` 추가**: surge_metadata JSON 내 `theme_group_id`로 충분. ALTER TABLE 금지.
- **propagation/volume_anomaly의 price_at_signal/price_after_Nd 검증 로직 추가**: 본 SPEC은 시그널 생성만. 추후 적중률 검증은 후속 SPEC.
- **재벌 그룹 외 테마(2차전지 밸류체인, AI 반도체 등) 시드 데이터**: 초기 4개 재벌 그룹만. 추가 그룹은 수동 SQL INSERT 또는 후속 SPEC.
- **`POST /api/surge-trading/coverage/refresh` 캐시 무효화 엔드포인트**: 60초 TTL로 충분. 명시적 무효화는 후속 작업.

---

## Delta Markers Summary

| Marker | File | Requirements |
|--------|------|--------------|
| `[NEW]` | `backend/app/models/theme_group.py` | REQ-AI022-003 |
| `[MODIFY]` | `backend/app/models/stock.py` | REQ-AI022-003 (relationship 추가만) |
| `[MODIFY]` | `backend/app/models/__init__.py` | REQ-AI022-003 |
| `[NEW]` | `backend/alembic/versions/037_spec_ai_022_theme_groups.py` | REQ-AI022-003 |
| `[NEW]` | `backend/app/services/surge_detector.py` (추가 함수) | REQ-AI022-001, REQ-AI022-002 |
| `[MODIFY]` | `backend/app/services/fund_manager.py` | REQ-AI022-001, REQ-AI022-002 (호출 추가) |
| `[MODIFY]` | `backend/app/surge_config/surge_settings.py` | REQ-AI022-001, 002, 004 (Config 클래스 추가) |
| `[NEW]` | `backend/app/services/surge_coverage_service.py` | REQ-AI022-004 |
| `[NEW]` | `backend/app/schemas/surge_trading_coverage.py` | REQ-AI022-004 |
| `[MODIFY]` | `backend/app/routers/surge_trading.py` | REQ-AI022-004 (엔드포인트 추가) |
| `[NEW]` | `backend/tests/test_theme_propagation.py` | AC-001~AC-005 |
| `[NEW]` | `backend/tests/test_volume_anomaly.py` | AC-006~AC-009 |
| `[NEW]` | `backend/tests/test_theme_groups_migration.py` | AC-010~AC-012 |
| `[NEW]` | `backend/tests/test_coverage_endpoint.py` | AC-013~AC-016 |
| `[MODIFY/NEW]` | `backend/tests/test_surge_signal_generation_integration.py` | AC-017, AC-018 |

---

## Related SPECs

- **SPEC-AI-012** (선행, 필수): 급등 징후 탐지 — surge_detector 4개 탐지기와 SurgeCandidate dataclass, gather_surge_candidates 진입점. 본 SPEC은 이 위에 propagation 단계를 추가.
- **SPEC-AI-014** (선행): 종목 전용 기사 블렌딩과 가격 보너스 — theme_cluster_score 계산 로직. 본 SPEC의 trigger_threshold 기준점.
- **SPEC-AI-013** (선행): 급등예측 모의투자 포트폴리오 — surge_trading_service.get_today_signals의 signal_type 필터.
- **SPEC-AI-018** (선행): 시장 레짐 분류와 recent_surge_penalty — 본 SPEC의 propagation에서 5일 수익률 페널티 정책 준수.
- **SPEC-AI-021** (병행): 손절 후 회복 confidence_boost — surge_trading_service 단의 보정. 본 SPEC과 독립적으로 동작.
- **SPEC-AI-004** (관련): 공시 기반 시그널 — 다른 signal_type 도입 패턴(`disclosure_impact`)의 reference.

---

## Verification Checklist

- [ ] 모든 EARS 요구사항이 검증 가능한 인수 기준을 가진다 (AC-001 ~ AC-018)
- [ ] 신규 마이그레이션 037이 down_revision=036 정확히 연결
- [ ] 기존 `fund_signals.signal_type` 컬럼 schema 변경 없음 확인 (TEXT 활용)
- [ ] 기존 `get_today_signals` 코드 무변경 확인 (signal_type 필터로 자동 제외)
- [ ] 기존 API 응답 스키마 변경 없음 확인 (`GET /api/surge-trading/coverage`는 신규 추가)
- [ ] propagation/volume_anomaly 단계의 try/except 격리로 surge_candidate 시그널 회귀 방지
- [ ] mock 기반 격리 테스트로 외부 의존성(naver_finance, DB) 차단
- [ ] target coverage 85%+ 명시, 신규 파일 90%+
- [ ] @MX 태그 계획 포함 (NOTE/WARN/SPEC)
- [ ] paper_executed=False 기본값으로 자동 매수 큐 제외 보장
- [ ] 4개 재벌 그룹 시드 데이터의 stock_code 정확성 (LG전자 066570, 삼성전자 005930, 현대차 005380, SK하이닉스 000660)
