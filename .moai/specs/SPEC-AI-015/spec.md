---
id: SPEC-AI-015
version: 1.0.0
status: completed
created: 2026-05-07
updated: 2026-05-07
author: MoAI
priority: High
issue_number: 0
title: 시장 레짐 적응형 전략 (Market Regime Adaptive Strategy)
tags: [fund-manager, market-regime, adaptive-strategy, ai-trading, risk-management]
dependencies: [SPEC-AI-007, SPEC-AI-003]
---

# SPEC-AI-015: 시장 레짐 적응형 전략 (Market Regime Adaptive Strategy)

## HISTORY

- 2026-05-07 (v1.0.0 → completed): 구현 완료 — 15개 파일, 1562 LOC 추가, 56개 신규 테스트, 전체 1022개 통과
- 2026-05-07 (v1.0.0): 초기 SPEC 작성 — 즉시 적용 fix(168e4cb) 후속, AI 펀드매니저 시장 레짐 적응형 전략 정식화

---

## 0. 배경 및 목적 (Background)

### 0.1 문제 정의

NewsHive AI 펀드매니저는 현재 KOSPI200 대비 지속적인 underperform을 기록하고 있다. 백테스트 및 실전 운용 분석 결과 다음 3가지 구조적 문제가 식별되었다:

1. **Cash Drag (현금 보유 지연)**
   - `MIN_ACTION_CONFIDENCE=0.55` (직전 0.50으로 완화) 임계값으로 인해 hold 시그널이 과다 생성
   - 결과: 평균 30~50% 현금 비중 유지 → KS200 (100% 매수) 대비 알파 손실
   - 시장 상승 구간에서 기회비용 누적

2. **No Market Regime Awareness (시장 레짐 무시)**
   - 상승장/하락장/횡보장에서 동일한 전략 파라미터 사용
   - 보수적 전천후(all-weather) 디폴트로 설계되어, 어떤 단일 레짐에서도 최적이 아님
   - confidence 임계값, 포지션 사이즈, 목표가 범위, 손절폭이 모두 정적

3. **Missed Alpha in Bull Markets (상승장 기회 손실)**
   - 명확한 상승 추세에서도 conservative entry로 인해 시그널 발생 빈도 저하
   - 상승장 특유의 모멘텀 시그널을 충분히 활용하지 못함

### 0.2 직전 즉시 적용 변경 (commit 168e4cb)

다음 변경은 이미 main 브랜치에 적용되었다. 본 SPEC은 이를 **정식 시스템화**하는 후속 작업이다:

| 변경 항목 | 이전 | 이후 |
|---|---|---|
| `MIN_ACTION_CONFIDENCE` | 0.55 | **0.50** |
| 목표가 범위 (target_pct) | +5~+20% | **+5~+30%** |
| 포지션 사이즈 conf≥0.80 신규 티어 | 없음 | **20%** |
| 시장 레짐 텍스트 주입 (briefing prompt) | 없음 | **`_market_regime` 변수 주입** |
| 시장 레짐 텍스트 주입 (analyze_stock prompt) | 없음 | **`_signal_market_regime` 변수 주입** |

### 0.3 본 SPEC의 목적

위 즉시 적용 fix는 **하드코딩 텍스트 주입**에 그쳐 다음 한계가 있다:

- DB 영속화 부재: 일별 레짐 분류 이력을 추적할 수 없음
- 동적 파라미터 부재: confidence, position_pct, target/stop은 여전히 정적 상수
- 코드 가드와 프롬프트 지시 불일치: AI는 "상승장이니 적극적으로"라는 텍스트만 받고 실제 코드 임계값은 그대로
- API 노출 부재: 프런트/외부 분석 도구에서 현재 레짐 조회 불가

본 SPEC은 다음을 정식 시스템으로 구축한다:

- **A. 일별 시장 레짐 분류 및 DB 영속화**
- **B. 레짐별 동적 파라미터 적용 (confidence / position / target / stop / max_trades)**
- **C. fund_manager.py / paper_trading.py / Scheduler / API 통합**
- **D. 7일 레짐 이력 조회 API**

### 0.4 비즈니스 가치

- KS200 대비 알파 회복: 상승장에서 buy 시그널 빈도 20%+ 증가 기대
- 하락장 자본 보호: 보수 모드 자동 전환으로 drawdown 완화
- 운용 가시성 확보: 일별 레짐 이력 → 전략 성과를 레짐별로 사후 평가 가능
- 향후 ML 기반 레짐 검출(SPEC 후속)을 위한 데이터 인프라 마련

---

## 1. 범위 및 제약 (Scope and Constraints)

### 1.1 In-Scope

- 일별 1회 KOSPI 기반 레짐 분류 (BULL / BEAR / SIDEWAYS)
- `MarketRegime` SQLAlchemy 모델 + Alembic migration
- `market_regime_service.py` 서비스 모듈 신설
- `fund_manager.py`의 `analyze_stock()` 및 `generate_daily_briefing()` 통합
- `paper_trading.py`의 포지션 사이징 / 손절 / 목표가 / 일일 거래수 통합
- 스케줄러 일별 09:00 KST 레짐 갱신 잡 (briefing 이전)
- `GET /fund/market-regime` REST 엔드포인트 (당일 + 7일 이력)
- 데이터 부재 시 SIDEWAYS 디폴트 graceful fallback

### 1.2 Out-of-Scope (Exclusions)

본 SPEC은 다음을 **명시적으로 포함하지 않는다**:

- 실시간 인트라데이 레짐 갱신 (일별로 충분)
- ML 기반 레짐 검출 (룰 기반만 사용)
- 프런트엔드 UI 변경 (API 노출만)
- 별도 설정 파일을 통한 파라미터 외부화 (코드 상수 + DB persisted regime로 충분)
- VIX 등 외부 변동성 지수 통합 (KOSPI 자체 변동성 proxy만 사용)
- 종목별 레짐 (시장 전체 단일 레짐만 사용)
- 백테스트 시뮬레이션 (별도 SPEC으로 분리)

### 1.3 의존성

- **SPEC-AI-007**: `MIN_ACTION_CONFIDENCE` 단일 상수 통일 — 본 SPEC은 이를 레짐별로 동적 오버라이드
- **SPEC-AI-003**: 시장 데이터 파이프라인 (`SectorMomentum` 모델, `avg_return_5d` 계산) — 본 SPEC은 이를 레짐 분류 입력으로 사용

### 1.4 가정 (Assumptions)

- KOSPI 5일 수익률은 `SectorMomentum` 테이블에서 조회 가능 (이미 `_kospi_ret_5d` 변수로 fund_manager.py에서 사용 중)
- KOSPI 20일 이동평균선 계산을 위한 KOSPI 일별 종가 데이터가 가용 (또는 별도 조회 함수 신설 필요 — plan.md 참조)
- 일별 1회 분류로 충분한 시그널 안정성 확보 가능
- 룰 기반 분류가 ML 기반 대비 운영 단순성/감사가능성에서 우위

---

## 2. 요구사항 (Requirements)

### 2.1 기능 요구사항 — Market Regime Detection

#### REQ-AI-015-001: MarketRegime DB 모델 신설 [NEW]

**The system shall** persist daily market regime classifications in a `market_regimes` table with the following schema:

| 컬럼 | 타입 | 제약 | 의미 |
|---|---|---|---|
| `id` | Integer | PK, autoincrement | 레코드 ID |
| `date` | Date | UNIQUE, NOT NULL, indexed | 분류 기준일 (KST) |
| `regime` | Enum(`BULL`, `BEAR`, `SIDEWAYS`) | NOT NULL | 분류 결과 |
| `kospi_5d_return` | Float | NOT NULL | KOSPI 5거래일 수익률 (%) |
| `kospi_20d_ma_position` | Float | NOT NULL | KOSPI 종가 vs 20일 이동평균 (%, +면 상회) |
| `volatility_index` | Float | NULLABLE | KOSPI 5일 표준편차 기반 변동성 proxy (옵션) |
| `confidence_score` | Float | NOT NULL, 0.0~1.0 | 분류 신뢰도 |
| `created_at` | DateTime | NOT NULL, default=now | 레코드 생성 시각 |
| `updated_at` | DateTime | NOT NULL, default=now, onupdate=now | 갱신 시각 |

**File**: `backend/app/models/market_regime.py` [NEW]
**Migration**: `backend/alembic/versions/XXX_spec_ai_015_market_regime.py` [NEW]

#### REQ-AI-015-002: 레짐 분류 알고리즘 [NEW]

**The system shall** classify the daily market regime using the following rule-based algorithm:

```
INPUT:
  - kospi_5d_return: float (%)
  - kospi_20d_ma_position: float (%)

CLASSIFICATION:
  IF kospi_5d_return >= +1.5%
     AND kospi_20d_ma_position > 0%   (KOSPI above 20d MA)
  THEN regime = BULL

  ELIF kospi_5d_return <= -1.5%
       OR kospi_20d_ma_position < -2%   (KOSPI below 20d MA by >2%)
  THEN regime = BEAR

  ELSE
  THEN regime = SIDEWAYS
```

**Confidence Score 계산**:
- BULL: `min(1.0, kospi_5d_return / 3.0 * 0.5 + max(0, kospi_20d_ma_position) / 5.0 * 0.5)`
- BEAR: `min(1.0, abs(kospi_5d_return) / 3.0 * 0.5 + abs(min(0, kospi_20d_ma_position)) / 5.0 * 0.5)`
- SIDEWAYS: `0.6` (디폴트)

#### REQ-AI-015-003: 레짐별 파라미터 매핑 [NEW]

**The system shall** map each regime to a `RegimeParams` dataclass with the following fixed parameter sets:

| 파라미터 | BEAR | SIDEWAYS | BULL |
|---|---|---|---|
| `min_action_confidence` | **0.65** | **0.55** | **0.48** |
| `max_position_pct_high` (conf≥0.80) | 0.10 | 0.15 | **0.20** |
| `target_pct_max` | 0.15 | 0.25 | **0.30** |
| `stop_loss_pct_default` | **0.04** | 0.05 | 0.07 |
| `max_daily_trades` | **2** | 5 | **7** |

**Where** `RegimeParams` 데이터클래스는 `market_regime_service.py`에 정의되어야 한다.

#### REQ-AI-015-004: 서비스 모듈 신설 [NEW]

**The system shall** provide a `market_regime_service.py` module with the following public API:

```python
# backend/app/services/market_regime_service.py [NEW]

class MarketRegimeEnum(str, enum.Enum):
    BULL = "BULL"
    BEAR = "BEAR"
    SIDEWAYS = "SIDEWAYS"

@dataclass
class RegimeParams:
    min_action_confidence: float
    max_position_pct_high: float  # for conf >= 0.80
    target_pct_max: float
    stop_loss_pct_default: float
    max_daily_trades: int

def classify_market_regime(
    kospi_5d_return: float,
    kospi_20d_ma_position: float,
    vol_level: Optional[float] = None,
) -> tuple[MarketRegimeEnum, float]:
    """Returns (regime, confidence_score). Pure function."""

def get_or_create_today_regime(db: Session) -> MarketRegime:
    """일별 09:00 KST 이후 호출. 같은 날짜 레코드 있으면 반환, 없으면 분류 후 INSERT."""

def get_regime_params(regime: MarketRegimeEnum) -> RegimeParams:
    """레짐 → 파라미터 매핑. 정적 dict 조회."""

def get_recent_regimes(db: Session, days: int = 7) -> list[MarketRegime]:
    """최근 N일 레짐 이력 조회 (date desc)."""
```

#### REQ-AI-015-005: KOSPI 20일 MA 조회 함수 [NEW or EXTEND]

**The system shall** provide a function to compute the KOSPI 20-day moving average and current position relative to it.

**Approach** (plan.md에서 결정):
- (a) `naver_finance.py`에 `fetch_kospi_20d_ma() -> tuple[float, float]` 신설 → 외부 API 의존
- (b) `SectorMomentum`이나 별도 KOSPI 시계열 테이블에서 20일 종가 조회 후 평균 계산
- (c) 첫 구현은 (a) 우선, 캐시 레이어로 (b) 후속 SPEC 분리

**If** 20일 MA 데이터를 가져올 수 없으면, **the system shall** `kospi_20d_ma_position = 0.0` 으로 디폴트 처리하고 `confidence_score`를 0.4 이하로 낮춘다.

### 2.2 통합 요구사항 — fund_manager.py

#### REQ-AI-015-010: analyze_stock() 레짐 통합 [MODIFY]

**When** `analyze_stock()` 가 호출되면, **the system shall**:

1. `get_or_create_today_regime(db)` 로 오늘의 레짐 객체 조회
2. `get_regime_params(regime.regime)` 로 동적 파라미터 획득
3. AI 프롬프트에 다음을 주입:
   - `_signal_market_regime`: 레짐 한글 라벨 (상승장/하락장/횡보장)
   - `_signal_regime_bias`: 레짐별 지시 텍스트
   - `_signal_min_confidence`: `regime_params.min_action_confidence` 의 실제 수치
   - `_signal_target_max`: `regime_params.target_pct_max` 의 실제 수치
4. AI 응답 후 코드 가드에서 `regime_params.min_action_confidence` 를 사용하여 confidence floor 검증

**File**: `backend/app/services/fund_manager.py` [MODIFY]
- 기존 라인 40 `MIN_ACTION_CONFIDENCE: float = 0.50` 은 폴백 디폴트로 유지
- `analyze_stock()` 내부에서 레짐 기반 동적 임계값을 우선 적용
- 레짐 조회 실패 시 디폴트 상수로 graceful fallback

#### REQ-AI-015-011: generate_daily_briefing() 레짐 통합 [MODIFY]

**When** `generate_daily_briefing()` 가 호출되면, **the system shall**:

1. `get_or_create_today_regime(db)` 로 오늘의 레짐 조회
2. 기존 `_kospi_ret_5d` 외에 `_market_regime`, `_regime_bias`, `_kospi_20d_ma_pct` 변수를 프롬프트에 주입
3. 직전 즉시 적용된 텍스트 주입 코드를 본 서비스 호출로 **대체** (하드코딩 제거)

**File**: `backend/app/services/fund_manager.py` [MODIFY]

### 2.3 통합 요구사항 — paper_trading.py

#### REQ-AI-015-020: 포지션 사이징 레짐 통합 [MODIFY]

**When** `_position_pct_by_confidence(confidence, db)` 가 호출되면, **the system shall**:

1. `get_or_create_today_regime(db)` 로 레짐 조회
2. `get_regime_params(regime.regime)` 로 파라미터 획득
3. 다음 매핑을 적용:
   - `confidence >= 0.80` → `regime_params.max_position_pct_high`
   - `confidence >= 0.70` → `regime_params.max_position_pct_high * 0.75`
   - `confidence >= 0.60` → `regime_params.max_position_pct_high * 0.50`
   - else → `regime_params.max_position_pct_high * 0.25`
4. 결과는 0.05 ~ 0.20 범위 내로 clamp

**File**: `backend/app/services/paper_trading.py` [MODIFY]
- 기존 라인 21 `MAX_POSITION_PCT = 0.10` 은 절대 상한 cap으로 유지
- 함수 시그니처에 `db: Session` 파라미터 추가 필요 (기존 호출부 수정)

#### REQ-AI-015-021: 손절가 / 목표가 레짐 통합 [MODIFY]

**Where** AI 응답이 명시적인 stop_loss / target을 제공하지 않은 경우, **the system shall** `regime_params.stop_loss_pct_default` 및 `regime_params.target_pct_max` 를 디폴트로 사용한다.

**File**: `backend/app/services/paper_trading.py` [MODIFY]
- 기존 라인 37 `DEFAULT_TARGET_PCT = 0.15` 및 라인 38 `DEFAULT_STOP_LOSS_PCT = 0.05` 는 폴백 상수로 유지

#### REQ-AI-015-022: 일일 거래 한도 레짐 통합 [MODIFY]

**The system shall** enforce `regime_params.max_daily_trades` as the upper bound for `execute_signal_trade()` invocations per UTC date.

**File**: `backend/app/services/paper_trading.py` [MODIFY]
- 일일 카운터는 기존 trades 테이블에서 `created_at::date == today` 로 집계
- 한도 초과 시 매수 시그널은 무시되고 hold로 다운그레이드

### 2.4 스케줄링 / API 요구사항

#### REQ-AI-015-030: 일별 스케줄러 잡 [MODIFY]

**While** 평일 09:00 KST에, **the system shall**:

1. `get_or_create_today_regime(db)` 호출 (idempotent)
2. 결과를 로그에 기록
3. **이후** `generate_daily_briefing()` 가 동일 db 세션에서 즉시 동일 레짐을 참조하도록 보장

**File**: 기존 스케줄러 (`backend/app/services/scheduler.py` 또는 동등 위치) [MODIFY]
- 잡 등록 순서: market_regime_update → daily_briefing → ... (의존성 명시)

#### REQ-AI-015-031: REST API 엔드포인트 [NEW]

**When** `GET /fund/market-regime` 가 호출되면, **the system shall** 다음 JSON을 반환한다:

```json
{
  "today": {
    "date": "2026-05-07",
    "regime": "BULL",
    "kospi_5d_return": 2.13,
    "kospi_20d_ma_position": 1.45,
    "volatility_index": 0.87,
    "confidence_score": 0.78,
    "params": {
      "min_action_confidence": 0.48,
      "max_position_pct_high": 0.20,
      "target_pct_max": 0.30,
      "stop_loss_pct_default": 0.07,
      "max_daily_trades": 7
    }
  },
  "history": [
    { "date": "2026-05-06", "regime": "SIDEWAYS", "kospi_5d_return": 0.42, ... },
    { "date": "2026-05-05", "regime": "SIDEWAYS", "kospi_5d_return": 0.18, ... },
    ... (총 7일)
  ]
}
```

**File**: `backend/app/routers/fund.py` [MODIFY]

### 2.5 비기능 요구사항

#### REQ-AI-015-040: Graceful Fallback [HARD]

**If** `SectorMomentum` 데이터 조회 실패, KOSPI 20일 MA 조회 실패, 또는 `MarketRegime` INSERT 실패가 발생하면, **the system shall**:

- regime = `SIDEWAYS`, confidence = 0.5 의 in-memory 디폴트로 진행
- DB 저장 시도 없이 호출자에게 디폴트 RegimeParams 제공
- 에러 로그 기록 (WARN 레벨)
- AI 펀드매니저 동작은 절대 차단하지 않음 (fallback first)

#### REQ-AI-015-041: 멱등성 [HARD]

**The system shall** ensure that `get_or_create_today_regime(db)` is idempotent within a single calendar date:
- 같은 날짜 호출 시 항상 동일한 레코드 반환 (이미 존재 시 SELECT, 없으면 INSERT)
- UNIQUE constraint on `date` 컬럼이 race condition 방어

#### REQ-AI-015-042: 후방 호환 [HARD]

**The system shall** preserve all existing test cases. 본 SPEC 도입으로 인한 기존 `tests/services/test_fund_manager.py`, `tests/services/test_paper_trading.py` 의 회귀가 발생해서는 안 된다.

#### REQ-AI-015-043: 성능 [SHOULD]

**Where** `analyze_stock()` 또는 `_position_pct_by_confidence()` 가 호출되는 핫 패스에서, **the system shall** 레짐 조회 latency를 평균 < 5ms로 유지한다 (DB query + dict lookup).

권장 구현: 요청 단위 in-memory cache (`functools.lru_cache` 또는 컨텍스트 캐시).

---

## 3. 제외사항 (Exclusions / What NOT to Build)

본 SPEC은 다음을 **명시적으로 포함하지 않는다**:

1. **실시간 인트라데이 레짐 갱신** — 일별 09:00 KST 1회 갱신만 지원
2. **ML 기반 레짐 검출 (HMM, k-means, Random Forest 등)** — 룰 기반 임계값만 사용
3. **프런트엔드 UI 변경** — API만 노출, 화면 구현은 별도 SPEC
4. **별도 YAML/JSON 설정 파일을 통한 파라미터 외부화** — Python 모듈 내 dict 상수로 관리
5. **VIX 또는 KOSPI 옵션 변동성 지수 통합** — KOSPI 5일 표준편차 proxy만 (옵션, NULLABLE)
6. **종목별/섹터별 레짐 분기** — 시장 전체 단일 레짐
7. **백테스트 시뮬레이션 / 과거 레짐 시뮬레이션 데이터 백필** — 본 SPEC 도입일 이후 데이터만 누적
8. **레짐 전환 알림(notification)** — 단순 DB 영속 + API 노출까지
9. **자동 레짐 임계값 튜닝 / A/B 테스트 인프라** — 향후 별도 SPEC

---

## 4. 영향받는 파일 (Affected Files)

### 4.1 신규 파일 [NEW]

- `backend/app/models/market_regime.py` — `MarketRegime` SQLAlchemy 모델 + `MarketRegimeEnum`
- `backend/app/services/market_regime_service.py` — 분류/조회/파라미터 서비스
- `backend/alembic/versions/XXX_spec_ai_015_market_regime.py` — DB 마이그레이션
- `backend/tests/services/test_market_regime_service.py` — 단위 테스트
- `backend/tests/api/test_fund_market_regime.py` — API 테스트

### 4.2 수정 파일 [MODIFY]

- `backend/app/services/fund_manager.py`
  - `analyze_stock()` 레짐 동적 임계값 적용
  - `generate_daily_briefing()` 하드코딩 텍스트 주입 → 서비스 호출로 대체
- `backend/app/services/paper_trading.py`
  - `_position_pct_by_confidence()` 시그니처 확장 + 레짐 통합
  - `execute_signal_trade()` 일일 거래 한도 적용
  - 디폴트 stop/target 레짐 기반 오버라이드
- `backend/app/routers/fund.py`
  - `GET /fund/market-regime` 엔드포인트 추가
- `backend/app/services/scheduler.py` (또는 동등 위치)
  - 09:00 KST 잡 등록, briefing 잡과의 의존성 명시
- `backend/app/main.py` 또는 `models/__init__.py`
  - `MarketRegime` 모델 import 등록

### 4.3 영향 받지만 수정 없음 (검증만 수행)

- `backend/tests/services/test_fund_manager.py` — 회귀 없는지 검증
- `backend/tests/services/test_paper_trading.py` — 회귀 없는지 검증
- `backend/app/services/sector_momentum_service.py` — `avg_return_5d` 조회 인터페이스만 사용

---

## 5. 성공 기준 (Success Criteria)

상세 인수 기준은 `acceptance.md` 참조. 핵심 요약:

- 일별 09:00 KST 이후 `market_regimes` 테이블에 당일 레코드 1건 존재
- BULL 레짐 시 `analyze_stock()` 의 confidence floor가 0.48로 동작 (코드 + 프롬프트 일치)
- BEAR 레짐 시 confidence floor가 0.65, 일일 거래 한도 2건
- `GET /fund/market-regime` 200 OK, today + 7일 history 반환
- `SectorMomentum` 데이터 부재 시 SIDEWAYS 디폴트로 graceful fallback, 시스템 무중단
- 기존 테스트 100% 통과 (회귀 없음)
- 신규 단위/통합 테스트 커버리지 ≥ 85% on `market_regime_service.py`

---

## 6. 참고 (References)

- `backend/app/services/fund_manager.py` 라인 40, 2128~, 2623~, 2860~2872
- `backend/app/services/paper_trading.py` 라인 21, 32, 37, 38, 124, 133
- `backend/app/models/sector_momentum.py` (`SectorMomentum.avg_return_5d`)
- 직전 commit: 168e4cb (즉시 적용 fix)
- SPEC-AI-007: Confidence Threshold Unification
- SPEC-AI-003: Market Data Pipeline / Sector Momentum
