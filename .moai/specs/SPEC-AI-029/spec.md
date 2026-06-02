---
id: SPEC-AI-029
version: 0.1.0
status: implemented
created: 2026-06-02
updated: 2026-06-02
author: MoAI
priority: High
issue_number: null
---

# SPEC-AI-029: 적응형 급등 확률 임계값 (Adaptive Surge Probability Threshold)

## HISTORY

- 2026-06-02 (v0.1.0): 최초 작성. 2026-06-02 운영 분석에서 4개 보유 포지션이 전부
  손실 상태(한양이엔지 -5.85%, 아이빔테크놀로지 -5.41%, 올릭스 -5.33%, 파미셀 0%)이며,
  진입 시점 `surge_probability_score`가 각각 0.71 / 0.48 / 0.48 / 0.44로 낮은 확률의
  후보까지 매수된 사실이 확인되었다. 근본 원인은 (1) `surge_probability_score` 최소
  임계값이 **정적(static)**이어서 최근 승률에 반응하지 못하고, (2) SIDEWAYS/BEAR 레짐에서
  거짓 양성을 줄이도록 임계값을 높이지 않으며, (3) 거래량 확인(`combo_score`)이 부재한
  후보에 대한 별도 게이트가 없고, (4) 실패한 포지션이 다음 신호 생성에 피드백되지 않는
  것이다. 본 SPEC은 신호 생성 시점에 동작하는 적응형 임계값 시스템을 정의한다.

---

## 선행 SPEC (전제 조건 / Assumptions)

본 SPEC은 다음 기존 SPEC이 구축한 인프라 위에 동작하며, 새로운 탐지기나 매매 엔진을
만들지 않고 기존 자산을 재사용한다.

- **SPEC-AI-012 (급등 징후 탐지 시스템)**: `surge_detector.py`의 4개 탐지기
  (theme_cluster, volume_news_combo, immediate_disclosure, disclosure_pattern), 앙상블
  스코어링, `FundSignal.surge_metadata`(Text, JSON 문자열), `surge_settings.py`의
  `SurgeDetectionConfig`/`EnsembleConfig`/`get_surge_config()` 설정 인프라를 도입했다.
  - **전제**: `EnsembleConfig.min_score_for_signal`(float)과
    `EnsembleConfig.regime_thresholds`(dict[str, float])가 이미 존재한다. 본 SPEC은
    이 정적 임계값에 **런타임 적응 레이어**를 추가하는 것이며, 기존 설정 키의 의미를
    변경하지 않는다.
  - **전제**: `surge_metadata` JSON은 탐지기별 점수를 포함한다. 거래량 확인 점수는
    `volume_news_combo` 탐지기의 점수(이하 `combo_score`로 지칭)로 표현되고,
    테마 점수는 `theme_cluster` 탐지기 점수(이하 `theme_cluster_score`)로 표현된다.
- **SPEC-AI-013 (급등예측 페이퍼 트레이딩)**: `SurgeTrade` / `SurgePortfolio` 모델,
  `surge_trading_service.py`의 매수/매도 실행 로직을 도입했다.
  - **전제**: `SurgeTrade`에는 명시적 `profit` 또는 `return_pct` 컬럼이 **존재하지
    않는다**. 거래 손익은 `entry_price`, `exit_price`, `exit_reason`, `is_open`
    컬럼으로부터 파생한다. 종료된 거래(승/패)는 `is_open = False`이며,
    승리(win)는 `exit_price > entry_price`로 판정한다.
- **SPEC-AI-015 (시장 레짐 탐지)**: `market_regime_service.py`,
  `MarketRegime` 모델, `MarketRegimeEnum`을 도입했다.
  - **[HARD] 사실 확인 — 레짐 enum 범위**: `MarketRegimeEnum`은 **BULL / BEAR /
    SIDEWAYS** 3개 값만 정의한다. **`VOLATILE` 값은 존재하지 않는다.**
    `classify_market_regime()`은 BULL / BEAR / SIDEWAYS 만 반환한다. 본 SPEC의
    REQ-AI029-002는 이 사실에 맞추어 작성되었다(아래 REQ 본문 및 Non-Goals 참조).
  - **전제**: 오늘자 레짐은 `get_or_create_today_regime(db)`로 조회하며, KOSPI 지표
    수집 실패 시 인메모리 `SIDEWAYS` 기본값을 반환한다.
- **SPEC-AI-016/017/018 (임계값·앙상블 정밀화)**: `min_score_for_signal`을 0.45로
  상향하고 레짐별 임계값/컨센서스 배율/단일 신호 우회 임계값을 도입했다. 본 SPEC의
  적응형 조정은 이 정적 값들 **위에 곱셈 배율로 적용**되며, 기존 값을 덮어쓰지 않는다.

---

## Overview

본 SPEC은 신호 생성 시점(08:30 KST)에 단 한 번 계산되는 **적응형 최소 확률 임계값
(adaptive minimum threshold)**을 정의한다. 임계값은 세 가지 입력으로부터 파생된다.

1. **최근 승률(trailing 5-trade win rate)** — 최근 종료된 5건의 거래 승률이 낮으면
   임계값을 높여 더 보수적으로 진입한다.
2. **시장 레짐(market regime)** — BEAR/SIDEWAYS에서는 거짓 양성이 많으므로 배율로
   임계값을 높이고, BULL에서는 낮춘다.
3. **거래량 확인 게이트(volume confirmation gate)** — 거래량 확인(`combo_score`)이
   전무한 후보는 테마 점수만으로 진입하지 못하도록 별도 하한을 요구한다.

계산된 임계값과 그 근거는 신규 테이블 `surge_threshold_history`에 영속화되어 관측 가능성
(observability)을 제공하며, 신규 API 엔드포인트로 현재 상태를 노출한다.

이 SPEC은 **무엇을(WHAT)**과 **왜(WHY)**를 정의하며, 구체적 함수 시그니처·클래스 구조 등
구현 세부는 Run 단계로 이연한다.

### 문제 맥락 — 2026-06-02 운영 증거 (Evidence)

| 종목 | 진입 시 surge_probability_score | 현재 등락 | 비고 |
|---|---|---|---|
| 한양이엔지 | 0.71 | -5.85% | 최고 확률 후보도 손실 |
| 아이빔테크놀로지 | 0.48 | -5.41% | 0.45 임계값 직상단 진입 |
| 올릭스 | 0.48 | -5.33% | 0.45 임계값 직상단 진입 |
| 파미셀 | 0.44 | 0% | 임계값 미만으로 추정되는 경계 진입 |

포트폴리오: 초기 5,000만원 → 현재 5,130만원(누적 +2.61%), 보유 4종목 전부 손실 또는 무수익.
종료 거래 21건 / 총 거래 25건. 낮은 확률(0.44~0.48) 후보가 정적 임계값을 통과해 손실에
기여한 정황이 확인된다.

### 임계값 적응 시나리오

| 시나리오 | 최근 5거래 승률 | 레짐 | 기대 동작 |
|---|---|---|---|
| 정상 | >= 40% | BULL | base × 0.9 (완화), 승률 가산 없음 |
| 연패 | < 40% | SIDEWAYS | base + 0.05 후 × 1.0, 단 0.70 상한 적용 |
| 약세장 연패 | < 40% | BEAR | base + 0.05 후 × 1.2, 0.70 상한 적용 |
| 거래량 미확인 후보 | (무관) | (무관) | combo_score=0 → theme_cluster_score >= 0.7 추가 요구 |

---

## Root Cause (네 가지 근본 원인)

### Root Cause 1 — 정적 확률 임계값

`EnsembleConfig.min_score_for_signal`(현재 0.45)과 `regime_thresholds`는 설정 파일에
고정되어 있다. 최근 거래가 연패 중이어도 임계값이 자동으로 높아지지 않아, 시장 상태
악화에 반응하지 못한다.

### Root Cause 2 — 레짐에 둔감한 진입

레짐별 탐지기 파라미터(`regime_detector_params`)는 존재하지만, **최소 확률 임계값
자체**에 레짐 배율을 곱하는 메커니즘은 없다. SIDEWAYS/BEAR에서 거짓 양성이 누적된다.

### Root Cause 3 — 거래량 확인 부재 후보의 무차별 진입

`theme_cluster` 점수가 높아도 거래량 확인(`combo_score`)이 0이면 실제 매집 없이 뉴스
테마만으로 부풀려진 신호일 수 있다. 현재는 이러한 후보를 별도로 거르지 않는다.

### Root Cause 4 — 실패 피드백 루프 부재

종료된 손실 거래가 다음 날 신호 생성 임계값에 반영되지 않는다. 승률 정보는 사후
조회만 가능할 뿐, 진입 결정에 자동 반영되지 않는다.

---

## 설계 원칙 (Design Principles)

1. **Multiplicative overlay (곱셈 오버레이)**: 적응형 임계값은 기존
   `min_score_for_signal`(또는 `regime_thresholds`)를 **base**로 삼아 그 위에 가산
   (+0.05)과 배율(×1.2 등)을 적용한다. 기존 설정 키의 값·의미를 변경하지 않는다.
2. **Signal-generation-time only (신호 생성 시점 한정)**: 적응 계산은 08:30 KST 신호
   생성 1회만 수행한다(REQ-AI029-006). 거래 체결 시점(`execute_buy_orders`)에는
   재계산하지 않는다. 동일 일자 내 임계값은 불변(immutable)이다.
3. **Hard cap (절대 상한)**: 승률 기반 가산은 0.70을 초과할 수 없다. 레짐 배율
   적용 후에도 최종값은 합리적 상한(아래 REQ-AI029-002 본문)에서 제한한다.
4. **Observability-first (관측 우선)**: 매 계산은 그 입력(승률, 레짐)과 사유를
   `surge_threshold_history`에 기록한다. 임계값이 왜 그 값인지 사후 추적 가능해야 한다.
5. **Derived win rate (파생 승률)**: 승률은 `SurgeTrade`의 종료 거래
   (`is_open = False`)에서 `exit_price > entry_price`로 결정론적으로 산출한다.
   별도 `profit` 컬럼을 추가하지 않는다.
6. **Backward compatible (하위 호환)**: `surge_threshold_history`에 행이 없거나
   종료 거래가 5건 미만이면, 시스템은 기존 정적 base 임계값으로 동작한다(승률 가산 없음).

---

## EARS Requirements

### REQ-AI029-001: 최근 5거래 승률 기반 임계값 가산

**When** the system computes the adaptive surge probability threshold at signal
generation time (REQ-AI029-006), the system **shall** compute the trailing
5-trade win rate from the 5 most recently closed `SurgeTrade` rows
(`is_open = False`, ordered by `exit_date` descending), where a win is defined as
`exit_price > entry_price`.

**If** the trailing 5-trade win rate drops below `0.40` (40%), **then** the system
**shall** raise the minimum `surge_probability_score` threshold by `+0.05`, and the
resulting raised threshold **shall** be capped at `0.70` (the raised threshold
**shall not** exceed `0.70` regardless of how low the win rate is).

**Where** fewer than 5 closed trades exist, the system **shall** treat the win-rate
gate as inactive (no `+0.05` addition) and proceed with the base threshold.

### REQ-AI029-002: 시장 레짐별 임계값 배율

**When** the system computes the adaptive threshold, the system **shall** apply a
regime-based multiplier to the (win-rate-adjusted) minimum threshold, using the
current regime obtained from `get_or_create_today_regime(db)`:

- **While** the regime is `BEAR`, the system **shall** apply a `1.2×` multiplier.
- **While** the regime is `SIDEWAYS`, the system **shall** apply a `1.0×` multiplier
  (neutral — SIDEWAYS is the conservative baseline).
- **While** the regime is `BULL`, the system **shall** apply a `0.9×` multiplier.

**[HARD] VOLATILE 처리**: `MarketRegimeEnum`은 현재 BULL/BEAR/SIDEWAYS 3개 값만
정의하며 `VOLATILE` 값은 존재하지 않는다(선행 SPEC 사실 확인 참조). 따라서 본 SPEC은
VOLATILE 케이스를 구현 대상에서 제외한다. **Where** a regime value other than
BULL/BEAR/SIDEWAYS is ever encountered (defensive default), the system **shall**
apply a `1.0×` multiplier. 만약 향후 `MarketRegimeEnum`에 `VOLATILE`가 추가되면,
`1.1×` 배율 적용은 별도 후속 SPEC에서 다룬다(Non-Goals 참조).

The regime multiplier **shall** be sourced from configuration (see
REQ-AI029-007), not hardcoded. The final threshold after applying the multiplier
**shall** be clamped to the range `[0.45, 0.85]` to prevent pathological values.

### REQ-AI029-003: 거래량 확인 부재 후보의 테마 점수 게이트

**If** a surge candidate's `combo_score` (the `volume_news_combo` detector score,
read from `surge_metadata`) is `0.0`, **then** the system **shall** require that
candidate's `theme_cluster_score` be `>= 0.7` before the candidate is included in
the buy-eligible pool — passing the adaptive `surge_probability_score` threshold
alone **shall not** be sufficient.

**Where** `combo_score > 0.0`, this gate **shall not** apply (the candidate is
evaluated against the adaptive threshold only). **Where** `surge_metadata` lacks a
`combo_score` or `theme_cluster_score` key, the system **shall** treat the missing
score as `0.0` (most conservative: a missing `combo_score` triggers the gate, and a
missing `theme_cluster_score` fails the `>= 0.7` requirement).

### REQ-AI029-004: surge_threshold_history 테이블에 적응 임계값 영속화

The system **shall** persist each computed adaptive threshold into a new table
`surge_threshold_history` at signal generation time (REQ-AI029-006). Each row
**shall** record at minimum:

- `date` (the trading date the threshold applies to),
- `threshold` (the final adaptive `surge_probability_score` minimum, after win-rate
  addition, regime multiplier, and clamping),
- `win_rate_5d` (the trailing 5-trade win rate used; nullable when fewer than 5
  closed trades),
- `regime` (the `MarketRegimeEnum` value used: `BULL` / `BEAR` / `SIDEWAYS`),
- `reason` (a short human-readable string explaining the computation, e.g.
  `"win_rate 0.20 < 0.40 → +0.05; regime BEAR ×1.2; clamped to 0.66"`).

The persistence **shall** be idempotent per `date`: re-running signal generation on
the same date **shall** upsert (overwrite) that date's row rather than inserting a
duplicate.

### REQ-AI029-005: GET /api/surge-trading/threshold-status 엔드포인트

The system **shall** expose a `GET /api/surge-trading/threshold-status` endpoint in
`backend/app/routers/surge_trading.py` (router prefix `/api/surge-trading`). The
endpoint **shall** return the current adaptive threshold, the trailing 5-trade win
rate, and the current market regime.

**Where** no `surge_threshold_history` row exists for the current date, the endpoint
**shall** return the base (static) threshold with a flag indicating the adaptive
threshold has not yet been computed for today (e.g. `"computed_today": false`),
rather than returning an error.

### REQ-AI029-006: 적응 임계값 계산은 신호 생성 시점에 1회 수행

**When** the daily surge signal generation job runs (the pre-existing 08:30 KST cron
job, `run_surge_signal_generation` in `backend/app/services/fund_manager.py`,
scheduled via `backend/app/services/scheduler.py`), the system **shall** compute the
adaptive threshold (REQ-AI029-001, REQ-AI029-002), persist it (REQ-AI029-004), and
use it for that day's candidate filtering.

The system **shall not** recompute the adaptive threshold at trade execution time
(`execute_buy_orders()` in `backend/app/services/surge_trading_service.py`). The
threshold computed at 08:30 KST **shall** remain immutable for the rest of the
trading day; execution reads the persisted value.

### REQ-AI029-007: surge_detection.yaml에 adaptive_threshold 설정 추가

The system **shall** add an `adaptive_threshold` section under `surge_detection:` in
`backend/app/surge_config/surge_detection.yaml`, parsed by a new Pydantic model in
`backend/app/surge_config/surge_settings.py`. The section **shall** define at
minimum:

- `enabled`: bool master switch. Default: `true`.
- `win_rate_window`: int number of recently closed trades to evaluate. Default: `5`.
- `win_rate_floor`: float win-rate threshold below which the addition applies.
  Default: `0.40`.
- `win_rate_addition`: float added to base threshold when the floor is breached.
  Default: `0.05`.
- `win_rate_cap`: float cap for the win-rate-raised threshold. Default: `0.70`.
- `regime_multipliers`: mapping of regime name to float multiplier. Default:
  `{BEAR: 1.2, SIDEWAYS: 1.0, BULL: 0.9}`.
- `final_clamp_min` / `final_clamp_max`: float bounds for the final threshold.
  Defaults: `0.45` / `0.85`.
- `combo_zero_theme_floor`: float `theme_cluster_score` minimum required when
  `combo_score == 0.0` (REQ-AI029-003). Default: `0.7`.

The configuration **shall** be adjustable without code changes. When the section is
absent from the YAML, the loader **shall** apply the documented defaults (backward
compatible). When `enabled = false`, the system **shall** fall back to the existing
static `min_score_for_signal` / `regime_thresholds` behavior and **shall not** write
to `surge_threshold_history`.

---

## Migration Spec — surge_threshold_history 테이블

신규 Alembic 마이그레이션 1건이 발생한다. 현재 최신 리비전은 `036`
(`036_spec_ai_004_disclosure_impact.py`)이므로, 새 리비전의 `down_revision`은 현재
헤드 리비전을 가리켜야 한다(Run 단계에서 `alembic heads`로 실제 헤드를 확인하여 연결).

**테이블 `surge_threshold_history` 스키마:**

| 컬럼 | 타입 | 제약 | 설명 |
|---|---|---|---|
| `id` | Integer | PK, autoincrement | 대리 키 |
| `date` | Date | NOT NULL, UNIQUE, index | 임계값이 적용되는 거래일 (일자당 1행) |
| `threshold` | Numeric(5, 4) | NOT NULL | 최종 적응 임계값 (0.0000~1.0000) |
| `win_rate_5d` | Numeric(5, 4) | NULLABLE | 사용된 최근 5거래 승률 (종료 거래 < 5건이면 NULL) |
| `regime` | String(20) | NOT NULL | 사용된 레짐 (`BULL`/`BEAR`/`SIDEWAYS`) |
| `reason` | String(255) | NOT NULL | 계산 근거 설명 문자열 |
| `created_at` | DateTime(timezone=True) | server_default=now() | 생성 시각 |

마이그레이션 규칙:
- `date` 컬럼에 **UNIQUE 제약**을 둔다(REQ-AI029-004의 일자당 upsert 보장).
- `upgrade()`는 테이블 생성, `downgrade()`는 테이블 삭제만 수행한다.
- 기존 테이블/컬럼을 변경하지 않는다(신규 테이블 추가 only).

---

## Implementation Scope

| 파일 | 변경 내용 | 관련 REQ |
|---|---|---|
| `backend/app/surge_config/surge_detection.yaml` | `adaptive_threshold` 섹션 신규 추가 (enabled, win_rate_*, regime_multipliers, final_clamp_*, combo_zero_theme_floor) | REQ-AI029-007 |
| `backend/app/surge_config/surge_settings.py` | `AdaptiveThresholdConfig` Pydantic 모델 추가, `SurgeDetectionConfig`에 `default_factory`로 필드 연결 | REQ-AI029-007 |
| `backend/app/models/surge_threshold_history.py` (신규) | `SurgeThresholdHistory` SQLAlchemy 모델 | REQ-AI029-004 |
| `backend/migrations/versions/0XX_spec_ai_029_threshold_history.py` (신규) | `surge_threshold_history` 테이블 생성/삭제 마이그레이션 (down_revision=현재 헤드) | REQ-AI029-004 |
| `backend/app/services/surge_trading_service.py` 또는 신규 `surge_threshold.py` | 적응 임계값 계산 함수 (승률 산출 + 레짐 배율 + 클램프 + upsert), 후보 필터에 적응 임계값 및 combo/theme 게이트 적용 | REQ-AI029-001~003 |
| `backend/app/services/fund_manager.py` | `run_surge_signal_generation()`에서 신호 생성 전 적응 임계값 계산·영속화 호출 | REQ-AI029-006 |
| `backend/app/routers/surge_trading.py` | `GET /threshold-status` 엔드포인트 추가 | REQ-AI029-005 |
| `backend/tests/test_surge_ai029.py` (신규) | 승률 가산·상한, 레짐 배율·클램프, combo/theme 게이트, upsert 멱등성, 엔드포인트, 비활성화 폴백 테스트 | 전체 |

---

## Acceptance Criteria

| ID | 기준 | 검증 방법 (pytest) |
|---|---|---|
| AC-029-01 | 최근 5 종료거래 승률 < 0.40 → base 임계값에 +0.05 가산 | 승률 0.20 fixture(`exit_price>entry_price` 1/5) → 임계값 = base+0.05 |
| AC-029-02 | 승률 가산 결과는 0.70을 초과하지 않는다 | base=0.68, 승률 0.0 → 0.73이 아닌 0.70으로 캡 |
| AC-029-03 | 종료 거래 5건 미만이면 승률 가산 비활성 | 종료거래 3건 fixture → base 임계값 그대로(가산 없음) |
| AC-029-04 | 레짐 BEAR=×1.2, SIDEWAYS=×1.0, BULL=×0.9 적용 | 3개 레짐 fixture, base 0.50 → 0.60 / 0.50 / 0.45 (클램프 전) |
| AC-029-05 | 최종 임계값이 [0.45, 0.85]로 클램프된다 | BEAR ×1.2 + 높은 base → 0.85 상한 적용 확인 |
| AC-029-06 | combo_score=0.0이고 theme_cluster_score < 0.7인 후보는 적응 임계값을 통과해도 제외 | surge_metadata fixture(combo=0.0, theme=0.6, prob=0.80) → buy pool 미포함 |
| AC-029-07 | combo_score=0.0이고 theme_cluster_score >= 0.7이면 게이트 통과 | fixture(combo=0.0, theme=0.7) → 적응 임계값 충족 시 포함 |
| AC-029-08 | combo_score > 0.0인 후보에는 theme 게이트 미적용 | fixture(combo=0.3, theme=0.1, prob>=임계값) → 포함 |
| AC-029-09 | surge_metadata에 combo/theme 키 부재 시 0.0으로 간주(가장 보수적) | 키 없는 fixture → theme 게이트로 제외 |
| AC-029-10 | 적응 임계값과 입력(승률·레짐·사유)이 surge_threshold_history에 1행 기록된다 | 신호 생성 호출 후 해당 date 행 1건, 필드값 검증 |
| AC-029-11 | 동일 date 재실행 시 중복 행이 아닌 upsert(덮어쓰기) | 동일 date 2회 실행 → 행 수 1, threshold 갱신 |
| AC-029-12 | GET /api/surge-trading/threshold-status가 threshold·win_rate·regime 반환 | TestClient GET 200, 3개 필드 존재 |
| AC-029-13 | 당일 history 행이 없으면 base 임계값 + computed_today=false 반환(에러 아님) | history 비운 상태 GET → 200, computed_today=false |
| AC-029-14 | 임계값 계산은 신호 생성 시점에만 수행, execute_buy_orders는 영속값을 읽는다 | execute_buy_orders 호출 시 임계값 재계산(upsert) 미발생 확인(spy/mock) |
| AC-029-15 | enabled=false 시 정적 min_score_for_signal로 폴백, history 미기록 | config enabled=false → history 행 0, 기존 임계값 사용 |
| AC-029-16 | adaptive_threshold 섹션이 YAML에 없어도 문서화 기본값으로 로드, 앙상블 가중치 검증 불변 | 섹션 제거 config 로드 → 기본값 적용, `get_surge_config()` 정상 |
| AC-029-17 | 기존 회귀 테스트 전체 통과 | `cd backend && uv run pytest tests/ -m "not slow"` 100% 통과 |
| AC-029-18 | 신규 테이블 외 스키마 변경 없음(기존 테이블/컬럼 불변) | 마이그레이션 diff: `surge_threshold_history` 생성만, 타 테이블 alter 없음 |

---

## Non-Goals (What NOT to Build)

본 SPEC의 범위에서 **명시적으로 제외**되는 항목:

- **VOLATILE 레짐 배율(×1.1) 구현은 포함하지 않는다.** `MarketRegimeEnum`에 현재
  `VOLATILE` 값이 존재하지 않으므로(BULL/BEAR/SIDEWAYS만), 존재하지 않는 enum 멤버를
  참조하는 코드를 작성하지 않는다. `MarketRegimeEnum`에 `VOLATILE`를 추가하는 작업과
  ×1.1 배율 적용은 별도 후속 SPEC 후보이다.
- **거래 체결 시점의 동적 임계값 재계산은 포함하지 않는다.** 임계값은 08:30 KST에 1회
  계산되고 당일 불변이다(REQ-AI029-006). 장중 실시간 임계값 조정은 제외한다.
- **새 탐지기 추가 또는 앙상블 가중치 변경은 포함하지 않는다.** 본 SPEC은 기존 4개
  탐지기의 출력 점수(combo/theme)를 게이트로 활용할 뿐, 탐지 로직이나 가중치 합산
  검증(`validate_ensemble_weights`)을 변경하지 않는다.
- **SurgeTrade에 profit/return_pct 컬럼 추가는 포함하지 않는다.** 승률은 기존
  `entry_price`/`exit_price`로 파생한다. 손익 비정규화 컬럼 도입은 제외한다.
- **포지션 사이징·max_open_positions·BUY_CUTOFF·max_daily_entries 변경은 포함하지
  않는다.** 본 SPEC은 진입 임계값 게이트만 다루며, 자본 배분 상수
  (position_pct=0.14, max_open_positions=7 등)는 변경하지 않는다.
- **백테스팅 또는 A/B 테스트 하네스 구축은 포함하지 않는다.** 적응 임계값의 효과
  측정 인프라는 `surge_threshold_history` 관측 데이터를 활용하는 별도 후속 SPEC
  후보이다.
- **승률 외 추가 성과 지표(샤프 비율, 최대 낙폭 등) 기반 적응은 포함하지 않는다.**
  본 SPEC은 trailing 5-trade win rate 단일 지표만 사용한다.
- **GitHub 이슈 생성은 포함하지 않는다.** 본 SPEC은 로컬 전용이다.
- **스케줄러 실행 빈도·시각 변경은 포함하지 않는다.** 기존 08:30 KST cron을 그대로
  사용한다(REQ-AI029-006).

---

## References

### 코드 위치 (수정/신규 대상)

- `backend/app/services/fund_manager.py`
  - `run_surge_signal_generation()` — 적응 임계값 계산·영속화 진입점 (REQ-AI029-006)
- `backend/app/services/surge_trading_service.py`
  - 후보 필터 / `execute_buy_orders()` — 적응 임계값 및 combo/theme 게이트 적용,
    체결 시 영속값 read-only (REQ-AI029-001~003, 006)
- `backend/app/services/market_regime_service.py`
  - `get_or_create_today_regime()` — 레짐 조회 (REQ-AI029-002)
- `backend/app/surge_config/surge_settings.py`
  - `AdaptiveThresholdConfig` 신규 모델, `SurgeDetectionConfig` 연결 (REQ-AI029-007)
- `backend/app/surge_config/surge_detection.yaml` — `adaptive_threshold` 섹션 (REQ-AI029-007)
- `backend/app/routers/surge_trading.py`
  - `GET /threshold-status` 신규 엔드포인트 (REQ-AI029-005)
- `backend/app/models/surge_threshold_history.py` (신규) — `SurgeThresholdHistory` 모델 (REQ-AI029-004)
- `backend/migrations/versions/` — 신규 마이그레이션 (REQ-AI029-004)

### 데이터 모델 사실 확인

- `SurgeTrade` (`backend/app/models/surge_portfolio.py`): `entry_price`(Numeric 15,2),
  `exit_price`(Numeric 15,2, nullable), `exit_reason`(String 50, nullable),
  `is_open`(Boolean, index), `exit_date`(Date, nullable),
  `surge_probability_score`(Numeric 5,4, nullable). **profit/return_pct 컬럼 없음** —
  승률은 종료 거래(`is_open=False`)에서 `exit_price > entry_price`로 파생.
- `MarketRegimeEnum` (`backend/app/models/market_regime.py`): **BULL / BEAR /
  SIDEWAYS 3개 값만 존재. VOLATILE 없음.**
- `EnsembleConfig` (`backend/app/surge_config/surge_settings.py`):
  `min_score_for_signal`(현재 0.45), `regime_thresholds`(dict[str, float]) — base
  임계값 출처.
- 라우터 prefix: `/api/surge-trading` (`surge_trading.py` 라인 15).
- 신호 생성 cron: 08:30 KST, `_run_surge_signal_generate` → `run_surge_signal_generation`
  (`scheduler.py` 라인 1152 인근, `hour=8`).

### 선행 SPEC

- SPEC-AI-012: 급등 징후 탐지 시스템 (탐지기, surge_metadata, surge_settings 인프라)
- SPEC-AI-013: 급등예측 페이퍼 트레이딩 (SurgeTrade/SurgePortfolio, 매수/매도 실행)
- SPEC-AI-015: 시장 레짐 탐지 (MarketRegime, MarketRegimeEnum, 레짐 조회)
- SPEC-AI-016/017/018: 임계값·앙상블 정밀화 (min_score_for_signal, regime_thresholds)
