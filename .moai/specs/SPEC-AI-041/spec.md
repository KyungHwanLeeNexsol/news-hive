---
id: SPEC-AI-041
version: 0.1.0
status: draft
created: 2026-06-09
updated: 2026-06-09
author: Nexsol
priority: high
issue_number: null
---

# SPEC-AI-041: 급등예측 자동평가·자가개선 루프

## HISTORY

- 2026-06-09 (v0.1.0): 최초 작성. 급등 시그널 적중률 일별 자동 평가 + 탐지기별 성과 기반 YAML 파라미터 자가조정 루프 정의. 선행 SPEC: SPEC-AI-012(급등 시그널), SPEC-AI-029(적응형 임계값), SPEC-AI-039(news_delayed 탐지기 가중치 체계).

---

## 1. Overview (개요)

### 목적

매 거래일 장 마감 후 다음 순환을 자동 실행한다.

1. **실제 결과 수집**: 당일 KOSPI/KOSDAQ 전 종목 중 종가 기준 +10% 이상 상승한 종목(실제 급등주)을 수집한다.
2. **예측 적중 평가**: 전 거래일(T-1)에 생성된 급등 시그널과 당일(T) 실제 급등주를 대조하여 정밀도(precision)·재현율(recall)·F1을 산출한다.
3. **놓친 종목 분석**: 시그널을 내지 못한 실제 급등주(false negative)에 대해 LLM이 원인을 분석한다.
4. **자가개선**: 탐지기별 5거래일 롤링 적중률을 계산하여 `surge_detection.yaml`의 앙상블 가중치와 `min_score_for_signal`을 자동 조정하고, 재시작 없이 반영한다.
5. **리포트 전달**: 17:05 KST에 텔레그램으로 일일 평가·개선 리포트를 전송한다.

### 배경

`volume_news_combo` 탐지기는 현재 앙상블 가중치 0.32로 **활성** 상태이나(2026-06-02 분석 기준 6/6 실패, 평균 -7.7%로 추격매수 패턴), 성과 데이터가 자동으로 가중치에 반영되지 않는다. 현재 가중치 조정은 SPEC-AI-039처럼 수동 커밋으로만 이루어진다. 본 SPEC은 실측 성과를 매일 정량화하고 가중치를 자동 보정하는 폐루프(closed loop)를 구축한다.

### 선행 인프라 (재사용)

| 컴포넌트 | 위치 | 용도 |
|---|---|---|
| `FundSignal` 모델 | `backend/app/models/fund_signal.py` | 시그널 저장 (stock_id FK, signal_type, surge_metadata JSON, is_correct, composite_score) |
| `surge_detection.yaml` | `backend/app/surge_config/surge_detection.yaml` | 조정 대상: ensemble.weights(5개), min_score_for_signal, final_clamp_min/max |
| `get_surge_config()` | `backend/app/surge_config/surge_settings.py:411` | `_config_singleton` 기반 싱글턴 |
| `fetch_top_movers_codes()` | `backend/app/services/naver_finance.py:1099` | 네이버 sise_rise 상승률 상위 코드 스크래핑 (코드만 반환) |
| `fetch_current_price_with_change()` | `backend/app/services/naver_finance.py:1168` | 종목별 현재가+등락률 dict 반환 |
| `is_market_hours()` / `KRX_EXTRA_HOLIDAYS` | `backend/app/services/surge_trading_service.py:103` | 평일·공휴일 거래일 가드 (KST) |
| `aggregate_failure_patterns()` / `ImprovementLog` | `backend/app/services/improvement_loop.py:31`, `app/models/improvement_log.py` | 실패 패턴 집계 패턴 참고 |
| `send_telegram_message()` | `backend/app/services/telegram_service.py:14` | 비동기 텔레그램 전송 |
| `scheduler.add_job(func, "cron", ...)` | `backend/app/services/scheduler.py:1115` (`start_scheduler`) | 잡 등록 패턴 (timezone="Asia/Seoul") |
| 급등 라우터 | `backend/app/routers/surge_trading.py:15` | `/api/surge-trading` prefix |

---

## 2. Requirements (요구사항 — EARS)

### R1: 장 마감 후 실제 급등주 수집 (Ubiquitous + Event-Driven)

- **R1.1** When 거래일 16:10 KST 잡이 트리거되면, the 시스템 **shall** `fetch_top_movers_codes()`로 KOSPI·KOSDAQ 상승률 상위 종목 코드를 각각 최대 100개 수집한다.
- **R1.2** 수집한 각 종목 코드에 대해, the 시스템 **shall** `fetch_current_price_with_change()`를 호출하여 종가 기준 등락률(`change_rate`)을 확정한다.
- **R1.3** The 시스템 **shall** 등락률이 +10.0% 이상인 종목을 `was_surge = True`로 분류하여 `SurgeActualOutcome`에 저장한다.
- **R1.4** The 시스템 **shall** `(trading_date, stock_code)` 복합 키 중복 시 upsert(갱신)한다.
- **R1.5** If 특정 종목의 등락률 조회가 실패하면, **then** the 시스템 **shall** 해당 종목을 건너뛰고 나머지 수집을 계속한다(전체 실패 금지).

### R2: 급등 시그널 적중 평가 (Event-Driven)

- **R2.1** When 거래일 16:30 KST 잡이 트리거되면, the 시스템 **shall** 전 거래일(T-1, 직전 영업일) 생성된 급등 시그널을 조회한다. 급등 시그널 식별 조건: `signal_type` 에 surge 마커(`surge`, `theme_cluster`, `volume_news_combo`, `disclosure_pattern`, `news_delayed` 중 하나) 포함.
- **R2.2** The 시스템 **shall** 시그널 종목(`Stock.stock_code` via stock_id 조인)을 당일(T) `SurgeActualOutcome(was_surge=True)` 집합과 대조하여 TP/FP/FN을 산출한다.
  - TP: 시그널 있고 실제 급등(was_surge=True)
  - FP: 시그널 있으나 실제 급등 아님
  - FN: 시그널 없으나 실제 급등(was_surge=True)
- **R2.3** The 시스템 **shall** precision = TP/(TP+FP), recall = TP/(TP+FN), F1 = 2·P·R/(P+R)를 계산하며, 분모 0인 경우 해당 지표를 0.0으로 처리한다.
- **R2.4** The 시스템 **shall** 평가 결과를 `SurgePredictionEvaluation`에 `evaluation_date = T`로 저장한다.

### R3: 놓친 종목 LLM 분석 (Event-Driven)

- **R3.1** When 평가가 완료되고 FN 종목이 1개 이상 존재하면, the 시스템 **shall** FN 종목 상위 5개(등락률 내림차순)에 대해 Gemini LLM으로 "왜 시그널을 내지 못했는가" 분석을 1회 호출한다.
- **R3.2** The 시스템 **shall** LLM 분석 결과를 `SurgePredictionEvaluation.miss_analysis_json`에 저장한다.
- **R3.3** If Gemini 호출이 실패하거나 일일 한도(20회)에 도달하면, **then** the 시스템 **shall** 규칙 기반 fallback 분석(탐지기별 미발화 사유 요약)을 대신 기록한다.

### R4: 탐지기별 롤링 적중률 산출 (State-Driven)

- **R4.1** The 시스템 **shall** 최근 5거래일 급등 시그널의 `surge_metadata` JSON을 파싱하여 탐지기별(theme_cluster, volume_news_combo, disclosure_pattern, legacy_detectors, news_delayed) 발화·적중 건수를 집계한다.
- **R4.2** The 시스템 **shall** 탐지기별 적중률 = (해당 탐지기 기여 시그널 중 was_surge=True) / (해당 탐지기 기여 전체 시그널)로 산출한다.
- **R4.3** If `surge_metadata` JSON에 특정 탐지기 키가 없으면, **then** the 시스템 **shall** 해당 키를 0 기여로 처리하고 계속 집계한다(KeyError 금지).

### R5: 앙상블 가중치 자동 조정 (Event-Driven)

- **R5.1** When 16:50 KST 자가개선 잡이 실행되고 누적 거래일이 5일 이상이면, the 시스템 **shall** 탐지기별 롤링 적중률에 비례하여 가중치를 보정한다.
- **R5.2** The 시스템 **shall** 보정 후 5개 가중치의 합이 1.0이 되도록 정규화한다.
- **R5.3** The 시스템 **shall** 각 가중치를 [0.05, 0.45] 범위로 클램프한 후 재정규화한다.
- **R5.4** The 시스템 **shall** 1일 단일 가중치 변화량을 ±0.05로 제한한다(급격한 변동 방지).

### R6: min_score_for_signal 자동 조정 (Event-Driven)

- **R6.1** When 자가개선 잡이 실행되면, the 시스템 **shall** 당일 recall 기반으로 `min_score_for_signal`을 조정한다. recall < 0.30 이면 −0.02(완화), recall > 0.60 또는 precision < 0.20 이면 +0.02(강화).
- **R6.2** The 시스템 **shall** `min_score_for_signal`을 [0.35, 0.65] 범위로 클램프한다.

### R7: 자가개선 로그 기록 (Ubiquitous)

- **R7.1** For 모든 파라미터 변경, the 시스템 **shall** `SurgeAutoImprovementLog`에 (parameter_path, old_value, new_value, rationale, rolling_window_days, evaluation_date)를 1건씩 기록한다.
- **R7.2** If 변경값이 기존값과 동일하면(변화 없음), **then** the 시스템 **shall** 로그를 기록하지 않는다.

### R8: 설정 무중단 반영 (Event-Driven)

- **R8.1** When YAML 파라미터가 변경되어 파일에 기록되면, the 시스템 **shall** `reload_surge_config()`를 호출하여 `_config_singleton` 캐시를 비우고 다음 `get_surge_config()` 호출 시 신규 설정이 로드되도록 한다.
- **R8.2** The 시스템 **shall** 서버 재시작 없이 변경을 반영한다.

### R9: 텔레그램 일일 리포트 (Event-Driven)

- **R9.1** When 17:05 KST 리포트 잡이 실행되면, the 시스템 **shall** `send_telegram_message()`로 일일 리포트를 전송한다.
- **R9.2** The 리포트 **shall** 다음을 포함한다: 평가일, precision/recall/F1, TP/FP/FN 건수, 실제 급등주 총수, 놓친 종목 상위 3개(종목명·등락률), 적용된 파라미터 변경 목록(파라미터·이전값→신규값).

### R10: 거래일 가드 (Unwanted Behavior)

- **R10.1** If 실행일이 주말이거나 `KRX_EXTRA_HOLIDAYS`에 포함된 휴장일이면, **then** the 시스템 **shall** 모든 4개 잡(수집·평가·개선·리포트)을 즉시 스킵한다.

### R11: 최소 데이터 요건 (State-Driven)

- **R11.1** While 누적 평가 거래일이 5일 미만인 동안, the 시스템 **shall** 수집·평가·LLM 분석·리포트는 수행하되 R5·R6 자동 파라미터 조정은 비활성화한다.
- **R11.2** When 5거래일 이상 누적되면, the 시스템 **shall** 자동 조정을 활성화한다.

### R12: 안전 롤백 (Unwanted Behavior)

- **R12.1** If 파라미터 조정 적용 다음 거래일의 recall이 직전 5거래일 평균 recall 대비 20% 이상(상대) 하락하면, **then** the 시스템 **shall** 직전 조정을 자동 되돌린다.
- **R12.2** When 롤백이 발생하면, the 시스템 **shall** `SurgeAutoImprovementLog`에 rationale="auto_rollback"로 역방향 변경을 기록하고 텔레그램 리포트에 명시한다.

---

## 3. Architecture (아키텍처)

### 3.1 신규 DB 모델

**`SurgeActualOutcome`** (`backend/app/models/surge_actual_outcome.py`)

| 컬럼 | 타입 | 비고 |
|---|---|---|
| trading_date | Date | 복합 PK |
| stock_code | String(10) | 복합 PK |
| stock_name | String(50) | |
| change_rate | Float | (종가 − 전일종가) / 전일종가 × 100 |
| was_surge | Boolean | change_rate ≥ 10.0 |
| high_change_rate | Float | (고가 − 전일종가) / 전일종가 × 100 (고가 미수집 시 change_rate로 대체) |
| market | String(10) | "KOSPI" / "KOSDAQ" |
| created_at | DateTime(tz) | server_default now() |

**`SurgePredictionEvaluation`** (`backend/app/models/surge_prediction_evaluation.py`)

| 컬럼 | 타입 | 비고 |
|---|---|---|
| evaluation_date | Date | PK |
| predicted_count | Integer | T-1 급등 시그널 수 |
| actual_surge_count | Integer | T 실제 ≥10% 종목 수 |
| true_positive | Integer | |
| false_positive | Integer | |
| false_negative | Integer | |
| precision | Float | |
| recall | Float | |
| f1_score | Float | |
| miss_analysis_json | Text | LLM/fallback 분석 결과 |
| improvements_applied_json | Text | 적용된 변경 요약 |
| created_at | DateTime(tz) | |

**`SurgeAutoImprovementLog`** (`backend/app/models/surge_auto_improvement_log.py`)

| 컬럼 | 타입 | 비고 |
|---|---|---|
| id | Integer | PK autoincrement |
| applied_at | DateTime(tz) | server_default now() |
| evaluation_date | Date | 인덱스 |
| parameter_path | String(100) | 예: "ensemble.weights.theme_cluster" |
| old_value | Float | |
| new_value | Float | |
| rationale | Text | 조정 근거 (또는 "auto_rollback") |
| rolling_window_days | Integer | 적중률 산출에 사용한 거래일 수 |

### 3.2 신규 서비스

**`backend/app/services/surge_actual_outcome_service.py`**

- `async def collect_daily_surge_outcomes(db: Session, trading_date: date) -> int`
  - `fetch_top_movers_codes("KOSPI", 100)` + `fetch_top_movers_codes("KOSDAQ", 100)`로 코드 수집
  - 각 코드에 `fetch_current_price_with_change()` 호출 → change_rate 확정
  - `was_surge = change_rate >= 10.0` 분류, `SurgeActualOutcome` upsert
  - 반환: 저장(또는 갱신)한 종목 수
  - **주의**: `fetch_top_movers_codes()`는 코드만 반환하므로 등락률은 종목별 호출로 별도 확정해야 함(R1.2)

**`backend/app/services/surge_evaluation_service.py`**

- `def evaluate_surge_predictions(db: Session, trading_date: date) -> SurgePredictionEvaluation`
  - T-1 영업일 계산(주말·KRX_EXTRA_HOLIDAYS 역산)
  - `FundSignal`을 `Stock`과 조인하여 stock_code 확보, surge signal_type 필터
  - `SurgeActualOutcome(trading_date=T, was_surge=True)` 집합과 대조 → TP/FP/FN
  - precision/recall/F1 산출(분모 0 가드), 결과 저장 후 반환
- `async def analyze_misses_with_llm(missed_stocks: list[dict], db: Session) -> str`
  - FN 상위 5개에 대해 Gemini 1회 호출, 실패/한도 초과 시 규칙 기반 fallback

**`backend/app/services/surge_auto_improver.py`**

- `def analyze_and_improve(db: Session, trading_date: date) -> list[SurgeAutoImprovementLog]`
  - 5거래일 롤링 `surge_metadata` 파싱 → 탐지기별 적중률
  - 가중치 비례 보정 → 정규화 → 클램프[0.05,0.45] → ±0.05 제한 → 재정규화
  - min_score_for_signal recall 기반 조정 → 클램프[0.35,0.65]
  - `surge_detection.yaml` 쓰기(yaml.safe_dump, 기존 주석은 보존 불가하므로 별도 로더 사용 시 주의 — 구현 시 ruamel.yaml 또는 부분 갱신 전략 결정) → `reload_surge_config()` 호출
  - R11(최소 5일) / R12(롤백) 게이트 적용
  - 변경 건별 `SurgeAutoImprovementLog` 반환
- `def format_telegram_report(evaluation, improvements, missed_top3) -> str`
  - R9.2 형식의 한국어 리포트 문자열 생성

### 3.3 수정 파일

**`backend/app/surge_config/surge_settings.py`** — `reload_surge_config()` 추가:

```python
def reload_surge_config() -> SurgeDetectionConfig:
    """싱글턴 캐시를 비우고 surge_detection.yaml을 재로드한다."""
    global _config_singleton
    _config_singleton = _load_config_from_yaml(_CONFIG_PATH)
    logger.info("SurgeDetectionConfig 재로드 완료: %s", _CONFIG_PATH)
    return _config_singleton
```

**`backend/app/services/scheduler.py`** — `start_scheduler()`(line 1115) 내부에 4개 잡 등록 추가. 기존 `scheduler.add_job(func, "cron", day_of_week="mon-fri", hour=H, minute=M, timezone="Asia/Seoul", id=..., max_instances=1, coalesce=True, replace_existing=True)` 패턴을 그대로 따른다. 각 잡 래퍼는 내부에서 `SessionLocal()` 생성 + `asyncio.run()` + 거래일 가드(R10) 후 서비스 호출:

| 래퍼 함수 | id | hour/minute (KST) |
|---|---|---|
| `_run_surge_collect_outcomes` | surge_collect_outcomes | 16:10 |
| `_run_surge_verify_predictions` | surge_verify_predictions | 16:30 |
| `_run_surge_auto_improve` | surge_auto_improve | 16:50 |
| `_run_surge_daily_report` | surge_daily_report | 17:05 |

> 참고: 기존 코드베이스 스케줄러는 KST 시각을 `timezone="Asia/Seoul"`로 직접 지정한다(UTC 변환 불필요). 따라서 16:10/16:30/16:50/17:05 KST를 그대로 hour/minute에 사용한다.

**`backend/app/routers/surge_trading.py`** — 3개 엔드포인트 추가:

- `GET /api/surge-trading/evaluation` — 최근 N일 평가 목록
- `GET /api/surge-trading/evaluation/{date}` — 특정일 평가 상세 (miss_analysis 포함)
- `GET /api/surge-trading/improvements` — 최근 자가개선 로그 목록

### 3.4 마이그레이션

| 파일 | revision | down_revision |
|---|---|---|
| `058_surge_actual_outcome.py` | 058_surge_actual_outcome | 057_surge_threshold_history |
| `059_surge_prediction_evaluation.py` | 059_surge_prediction_evaluation | 058_surge_actual_outcome |
| `060_surge_auto_improvement_log.py` | 060_surge_auto_improvement_log | 059_surge_prediction_evaluation |

리비전 문자열·헤더 형식은 `057_surge_threshold_history.py`를 그대로 따른다.

### 3.5 데이터 흐름

```
16:10 collect_daily_surge_outcomes  →  SurgeActualOutcome (T)
16:30 evaluate_surge_predictions    →  SurgePredictionEvaluation (T)  [FundSignal(T-1) × SurgeActualOutcome(T)]
        + analyze_misses_with_llm   →  miss_analysis_json
16:50 analyze_and_improve           →  surge_detection.yaml 갱신 + reload_surge_config()
                                       + SurgeAutoImprovementLog (N건)
17:05 format_telegram_report        →  send_telegram_message()
```

---

## 4. Risks (위험)

| ID | 위험 | 완화책 |
|---|---|---|
| RISK-1 | 네이버 sise_rise 스크래핑 불안정(HTML 구조 변경·차단) | KIS API top movers 엔드포인트로 fallback. `fetch_top_movers_codes` 실패 시 빈 리스트 반환되므로 수집 0건이면 리포트에 "데이터 수집 실패" 명시하고 자가개선 스킵 |
| RISK-2 | `surge_metadata` JSON 스키마 불일치(탐지기 키 누락) | 모든 키 접근을 `.get(key, 0)`로 처리(R4.3), JSON 파싱 실패 시 해당 시그널 제외하고 계속 |
| RISK-3 | Gemini 일일 한도(20회) — 브리핑·시그널 생성과 공유 | FN 분석은 1일 1회·상위 5개만 호출. 한도 초과 시 규칙 기반 fallback(R3.3) |
| RISK-4 | YAML 자동 쓰기 시 주석 손실 | 구현 시 부분 갱신 전략 확정 필요(ruamel.yaml 라운드트립 권장). 본 SPEC은 ensemble.weights·min_score_for_signal 값만 갱신 |
| RISK-5 | T-1 영업일 역산 오류(연휴) | `KRX_EXTRA_HOLIDAYS` + 주말 역산 로직 재사용, 단위 테스트로 연휴 케이스 검증 |
| RISK-6 | 자동 조정이 모델을 악화 | R11(최소 5일)·R12(20% recall 하락 시 롤백)·±0.05 일일 변화 제한 3중 안전장치 |

---

## 5. Success Criteria (성공 기준)

- **SC-1**: 10거래일 누적 후 recall ≥ 0.35 (실제 ≥10% 급등 종목의 35% 이상 탐지)
- **SC-2**: 17:05 KST 리포트가 기준 시각 5분 이내 텔레그램 전달
- **SC-3**: 모든 파라미터 변경이 `SurgeAutoImprovementLog`에 100% 기록
- **SC-4**: `reload_surge_config()` 호출 후 서버 재시작 없이 신규 가중치가 다음 시그널 생성에 반영
- **SC-5**: 거래일 가드(R10)가 주말·휴장일에 4개 잡 모두 스킵

---

## 6. Exclusions (What NOT to Build / 제외 범위)

- **매수 주문 실행 없음**: 본 SPEC은 평가·개선만 담당. 실제 매수/매도는 기존 `surge_trading_service`의 범위.
- **포트폴리오 관리 없음**: 보유 종목·익절·손절 로직 미포함.
- **UI 대시보드 없음**: 결과 전달은 텔레그램 + 조회용 REST 엔드포인트만. 프론트엔드 화면 미구현.
- **Python 로직 자동 변경 없음**: 자가개선은 **YAML 파라미터(가중치·임계값)만** 조정. 탐지기 알고리즘·코드 자동 수정 금지.
- **탐지기 신규 추가 없음**: 기존 5개 탐지기 가중치 조정만. 새 탐지기 도입은 별도 SPEC.
- **실시간 장중 평가 없음**: 평가는 장 마감 후 일 1회 배치만. 장중 인트라데이 평가 미포함.

---

## 7. 관련 SPEC

- **SPEC-AI-012**: 급등 징후 탐지 + `surge_metadata` JSON 도입 (의존)
- **SPEC-AI-029**: 적응형 surge 확률 임계값 + `SurgeThresholdHistory` (병행 — 본 SPEC은 탐지기 가중치, AI-029는 확률 임계값 담당으로 영역 분리)
- **SPEC-AI-030**: volume_news_combo 추격매수 방지 게이트 (본 SPEC이 동일 탐지기 가중치를 사후 평가로 보정)
- **SPEC-AI-039**: news_delayed 탐지기 가중치 체계 (수동 조정 → 본 SPEC이 자동화로 대체)
