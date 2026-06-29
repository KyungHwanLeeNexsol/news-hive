---
id: SPEC-AI-065
version: 1.0.0
status: completed
created: 2026-06-29
updated: 2026-06-29
author: Nexsol
priority: high
issue_number: null
---

# SPEC-AI-065: 상대적 이상치 탐지 + 스캔 유니버스 확장으로 급등 리콜 개선

## HISTORY

- 2026-06-29 (v0.1.0): 최초 작성. 2026년 6월 데이터 분석 결과 — 실제 급등(+10% 이상) 855건 중 시스템이 적중한 것은 5건(recall 0.6%) — 의 근본 원인이 탐지기 알고리즘이 아니라 **입력 종목 유니버스(스캔 대상)**에 있다는 진단에 기반. (1) 종목별 z-score 정규화로 절대 점수의 대형주 편향 제거, (2) 자동 스캔 유니버스 확장 3개 풀(공시/거래량/모멘텀), (3) 모멘텀 연속 탐지기 신설, (4) 과거 데이터 기반 앙상블 가중치 오프라인 재보정, (5) 풀별 평가 지표 추가. 선행 SPEC: SPEC-AI-041(자동평가·자가개선 루프 — 온라인 가중치 보정 소유), SPEC-AI-029(적응형 임계값 소유), SPEC-AI-062(volume_breakout 7번째 탐지기), SPEC-AI-012(앙상블·surge_metadata).

---

## 1. Executive Summary (요약)

이 SPEC은 한국 주식 급등(익일 +10% 이상) 예측 시스템의 **리콜(recall)을 0.6%에서 3% 이상으로(약 5배)** 끌어올리는 것을 목표로 한다.

2026년 6월 데이터 분석은 핵심 진단을 내렸다: **문제는 탐지기 알고리즘이 아니라 탐지기에 들어가는 입력 종목 집합이다.** 현재 시스템은 뉴스·테마·거래량 신호에 걸린 하루 20~30개 종목만 스캔하며, 이 입력 집합은 구조적으로 뉴스 기사량이 많은 대형주(현대차, 삼성전자 등)에 편향된다. 대형주는 +10% 임계에 도달하기 어려우므로, 알고리즘을 아무리 튜닝해도 적중률이 오르지 않는다. 실제 급등의 대부분은 애초에 스캔조차 되지 않은 중소형주(+20~30%)였다(미스 유형 B).

본 SPEC은 두 가지 축으로 이를 해결한다.

1. **상대적 이상치 탐지(REQ-1)** — 절대 앙상블 점수를 종목별 z-score 정규화로 대체하여, "그 종목 기준으로 비정상적인" 신호를 포착한다. 평소 뉴스 3건인 대형주의 뉴스 3건은 정상이지만, 평소 뉴스 0건인 소형주의 뉴스 3건은 이상치다.
2. **스캔 유니버스 자동 확장(REQ-2)** — 공시·거래량·모멘텀 기반 3개 풀을 익일 후보군에 자동 추가하여 스캔 대상을 하루 80~150개로 넓힌다.

여기에 모멘텀 연속 탐지기(REQ-3), 과거 데이터 기반 가중치 재보정(REQ-4), 풀별 정밀도/리콜 추적(REQ-5)을 더한다.

> **핵심 설계 원칙**: 유니버스 확장은 **입력(후보 평가 대상)**을 넓히는 것이지 **출력(발신 시그널)**을 늘리는 것이 아니다. 시그널 발신은 여전히 `min_score_for_signal` + 적응형 임계값 + 상위 랭킹으로 게이팅된다. 즉 80~150개를 **평가**하되 월 30~40개만 **발신**한다. 이 분리가 리콜(더 많은 후보 검토)과 정밀도(엄선 발신)를 동시에 달성하는 메커니즘이다.

---

## 2. Background and Problem Statement (배경 및 문제 정의)

### 2.1 시스템 현황

- `surge_detector.py`: 앙상블 탐지기로 급등 후보 생성
- `fund_manager.py`: 시그널 생성 오케스트레이션, 품질 게이트
- `scheduler.py`: 일별 잡(시그널 생성 + 자가개선) 실행
- `surge_auto_improver.py`: 파라미터 자동 튜닝 (SPEC-AI-041 소유)
- `surge_detection.yaml` (base) / `surge_detection.auto.yaml` (자동개선 오버레이)
- 현행 앙상블 탐지기(7종): `theme_cluster`, `volume_news_combo`, `disclosure_pattern`, `legacy_detectors`, `news_delayed`, `weekend_gap_up`, `volume_breakout`

### 2.2 데이터 분석 결과 (2026년 6월)

| 항목 | 측정값 |
|---|---|
| 실제 발생 급등(+10% 이상) | 855건 |
| 시스템 적중(TP) | 5건 (recall 0.6%) |
| 일일 스캔 유니버스 | 20~30 종목 |
| 적중 예측 confidence 분포 | 0.237 ~ 0.350 |
| 대형주 미적중 예측 confidence | 0.173 ~ 0.187 |

### 2.3 두 가지 미스 유형

- **유형 A (신호 존재, 점수 미달)**: HL만도 +9.2%, HD건설기계 +9.1% 등 — 신호는 잡혔으나 +10% 임계 직전에서 탈락. 상대적 점수 보정으로 일부 구제 가능.
- **유형 B (애초에 미스캔)**: 850건 미스의 대부분 — +20~30% 급등한 중소형주가 스캔 대상에 들어오지도 못함. **유니버스 확장으로만 해결 가능.**

### 2.4 성공 패턴 (6/12 → 6/13 TP 사례)

한국앤컴퍼니-아시아나 M&A 뉴스 → 섹터 테마 형성 → 4개 종목 10~14% 급등. 이 사례에서 `fired: []`(단일 탐지기가 개별 임계를 넘지 못함)였으나 **앙상블 합산이 통과**했다. 즉 단일 탐지기 강한 신호가 아니라 **다수 약한 신호의 누적**이 익일 급등을 선행한다는 증거 — REQ-3(모멘텀 연속)과 REQ-1(z-score 누적)의 근거.

### 2.5 근본 원인

탐지기 자체가 아니라 **입력 종목 유니버스**가 문제다. 현재는 테마 클러스터·거래량 이상·공시 스캔에 걸린 종목만 시그널 생성 대상이 되며, 이는 뉴스량 기반 대형주 편향 후보를 만들어 구조적으로 +10% 임계에 도달할 수 없다.

### 2.6 선행 인프라 (재사용) 및 실제 데이터 제약 [HARD]

| 컴포넌트 | 위치 | 용도 / 제약 |
|---|---|---|
| `_fetch_price_change_sync()` | `surge_detector.py` | `{current_price, change_rate}`만 반환. **`open_price`(시가) 없음.** `change_rate`는 **전일 종가 대비**(%)이며 인트라데이 시가 대비 아님 |
| `_get_volume_history()` | `surge_detector.py` | **일봉(daily) 거래량**만 반환. 20일 평균 대비 배수는 일봉 해상도로만 계산 가능 |
| `PriceRecord` | `naver_finance.py:629` | 전체 OHLCV(date/close/open/high/low/volume) 보유 → 전일 등락률은 일봉 이력에서 계산 가능. pages=1 ≈ 10거래일 |
| `fetch_top_movers_codes(market, limit)` | `naver_finance.py:1099` | **종목코드만** 반환(등락률 없음). 등락률은 코드별 `fetch_current_price_with_change()` 2단계 호출 필요 |
| `FundSignal` | `app/models/fund_signal.py` | **`stock_code` 컬럼 없음** — `stock_id`(FK)→`Stock.stock_code` 조인 필수. `surge_metadata`(JSON)에 탐지기별 점수 저장 |
| `Disclosure` | `app/models/disclosure.py` | `stock_code`(String, nullable), `rcept_dt`(YYYYMMDD **문자열**), `report_name`, `disclosed_at`. 날짜 비교 시 문자열 변환 필요 |
| `compute_ensemble_score()` | `surge_detector.py` | 0~1 정규화 surge prob 산출. `validate_ensemble_weights`가 모든 가중치 합=1.0 강제 |
| `reload_surge_config()` | `surge_settings.py` | 설정 캐시 초기화(존재 확인됨, auto_improver 사용) |
| `surge_prediction_evaluation` | `app/models/surge_prediction_evaluation.py` | 일별 평가 지표 저장. [MODIFY] 풀별 카운트 컬럼 추가 대상 |
| migration head | `alembic/versions/062_crash_risk_alerts.py` | 신규 migration 063의 `down_revision=062` |

> **라이브러리 제약 [HARD]**: 백엔드에 **numpy / scipy / sklearn 미설치**(`pyproject.toml`). 따라서 REQ-1 z-score는 순수 파이썬 롤링 평균/표준편차로, REQ-4 로지스틱 회귀는 순수 파이썬 경사하강 또는 오프라인 분석 스크립트로 구현해야 한다(선례: SPEC-AI-036의 hand-rolled PAV isotonic).

### 2.7 운영 모드 제약 [HARD]

본 시스템은 **예측 기록 모드**(SPEC-AI-043)로 동작한다. 실제 매수는 비활성(의도적). 본 SPEC의 모든 변경은 **예측·평가에만** 영향을 주며, 매수 로직(`execute_buy_orders`, `max_open_positions`, `max_daily_entries`)은 변경하지 않는다.

---

## 3. Requirements (요구사항 — EARS)

### REQ-1: 상대적 이상치 탐지 (Z-Score 정규화)

목적: 절대 앙상블 점수의 대형주 편향을 제거하고, 종목 자기 기준 대비 비정상 신호를 포착한다.

- **REQ-1.1 (State-Driven)** — While 각 종목·각 탐지기에 대해 30거래일 롤링 통계(`rolling_mean`, `rolling_std`, `sample_count`)가 유지되는 동안, the system **shall** 신규 신호값을 `z = (current_signal - rolling_mean) / rolling_std`로 정규화한다.
- **REQ-1.2 (Ubiquitous)** — The system **shall** 앙상블 점수 계산 시 절대 신호값 대신 REQ-1.1의 z-score를 입력으로 사용한다.
- **REQ-1.3 (If/then)** — If 특정 종목·탐지기의 `sample_count < min_baseline_samples`(설정값, 기본 10)이거나 `rolling_std == 0`이면, **then** the system **shall** z-score 정규화를 건너뛰고 절대값 기반 fallback 경로를 사용한다(콜드스타트 안전장치).
- **REQ-1.4 (Event-Driven)** — When 일별 시그널 평가가 완료되면, the system **shall** 각 종목·탐지기의 롤링 통계를 당일 관측값으로 갱신한다(30거래일 윈도우 유지).
- **REQ-1.5 (Ubiquitous)** — The system **shall** 롤링 통계를 신규 테이블 `stock_signal_baselines`에 영속화하고, 발신 시그널의 z-score 산출 근거를 `FundSignal.surge_metadata`(JSON)에 기록한다.
- **REQ-1.6 (Ubiquitous, 라이브러리 제약)** — The system **shall** z-score 통계를 순수 파이썬으로 계산한다(numpy/scipy 미사용).

근거: 평소 뉴스 3건인 대형주의 뉴스 3건(z≈0)보다, 평소 뉴스 0건인 소형주의 뉴스 3건(z≫0)이 높게 채점되어야 한다.

### REQ-2: 스캔 유니버스 자동 확장

목적: 익일 후보군에 3개 풀을 자동 추가하여 스캔 대상을 20~30 → 80~150 종목으로 확장한다.

- **REQ-2.1 (Event-Driven, Pool A)** — When 당일 장 마감 후 유니버스 빌드가 실행되면, the system **shall** 당일 신규 공시가 있는 모든 종목(`Disclosure.rcept_dt`가 당일과 일치)을 익일 후보 풀에 추가한다.
- **REQ-2.2 (Event-Driven, Pool B)** — When 유니버스 빌드가 실행되면, the system **shall** 당일 거래량이 20일 평균 대비 200% 이상인 종목을 후보 풀에 추가한다(일봉 거래량 기준).
- **REQ-2.3 (Event-Driven, Pool C)** — When 유니버스 빌드가 실행되면, the system **shall** 당일 `change_rate`가 5~15% 범위이고 거래량이 양(+)인 종목(모멘텀 연속 후보)을 후보 풀에 추가한다.
- **REQ-2.4 (Ubiquitous)** — The system **shall** 각 후보의 진입 사유를 풀 태그(`pool_a` / `pool_b` / `pool_c` / `existing`)로 기록하여 `surge_metadata.entry_pool`에 저장한다.
- **REQ-2.5 (Ubiquitous)** — The system **shall** 3개 풀의 종목을 기존 탐지 후보와 합집합(중복 제거)하여 익일 아침 앙상블 계산 대상에 포함한다.
- **REQ-2.6 (If/then, 데이터 제약)** — If Pool C 후보의 `change_rate`가 이력(`PriceRecord`)으로 확보되지 않으면, **then** the system **shall** `fetch_top_movers_codes()` + 코드별 `fetch_current_price_with_change()` 2단계 조회로 보완한다.
- **REQ-2.7 (Ubiquitous, 상한)** — The system **shall** 유니버스 크기에 상한(`max_scan_universe`, 기본 150)을 적용하여 폭주를 방지하고, 상한 초과 시 풀 우선순위(A > B > C)와 z-score로 절단한다.

> 설계 주의: 풀 추가는 **유니버스 포함**(평가 대상)이지 **탐지기 발화**가 아니다. Pool A ≠ `disclosure_pattern` 탐지기, Pool B ≠ `volume_breakout` 탐지기. 풀로 들어온 종목은 전체 앙상블(z-score 포함)로 재채점된다.

### REQ-3: 모멘텀 연속 탐지기 (`momentum_continuation`)

목적: 전일 5~15% 상승한 종목이 익일 연속 급등하는 패턴을 포착하는 신규(8번째) 탐지기.

- **REQ-3.1 (Event-Driven)** — When 한 종목이 전일(T-1) `change_rate` 5~15% 상승을 기록했으면, the system **shall** `momentum_continuation` 탐지기를 발화시킨다.
- **REQ-3.2 (Ubiquitous)** — The system **shall** 컨텍스트 팩터(섹터 추세, 시장 레짐, 거래량 일관성)로 발화 점수를 가중한다.
- **REQ-3.3 (Ubiquitous)** — The system **shall** `momentum_continuation`을 앙상블에 초기 가중치 0.12로 통합하되, `EnsembleWeightsConfig`에 필드를 추가하고 `validate_ensemble_weights`의 합=1.0 검증을 갱신하며 나머지 가중치를 비례 재조정한다.
- **REQ-3.4 (Unwanted, If/then)** — If 전일 상승이 과열 구간(예: `change_rate > 15%`)이면, **then** the system **shall** `momentum_continuation`을 발화시키지 않는다(추격매수성 차단).
- **REQ-3.5 (Ubiquitous, 중복 방지)** — The system **shall** `momentum_continuation`을 기존 `volume_breakout`(당일 거래량 돌파) 및 `technical_momentum`(SPEC-AI-044, 뉴스 무촉매 기술 돌파)과 구분되는 **전일 실현 상승 연속성** 신호로만 정의한다.

근거: 6/13 급등 사례는 전일 섹터 테마 활동이 선행했다. 전일 실현 상승은 익일 연속 급등의 약한 선행지표다.

### REQ-4: 앙상블 가중치 오프라인 재보정

목적: 과거 데이터의 증거로 초기 가중치를 재설정한다.

- **REQ-4.1 (Event-Driven)** — When 재보정 분석이 실행되면, the system **shall** 과거 데이터에 대해 오프라인 로지스틱 회귀 `(T-1 탐지기별 점수) → (T일 was_surge)`를 적합한다.
- **REQ-4.2 (Ubiquitous)** — The system **shall** 적합 결과로 `surge_detection.auto.yaml`의 가중치를 갱신하되, 합=1.0 및 기존 클램프 경계(`[0.05, 0.45]`)를 준수한다.
- **REQ-4.3 (Ubiquitous)** — The system **shall** 5개 TP와 850개 FN을 차별화한 팩터를 분석 산출물로 기록한다(어떤 탐지기 조합이 적중을 구분했는가).
- **REQ-4.4 (Ubiquitous, 라이브러리 제약)** — The system **shall** 로지스틱 회귀를 순수 파이썬(경사하강) 또는 오프라인 분석 스크립트로 구현한다(sklearn 미사용).
- **REQ-4.5 (Ubiquitous, 영역 분리)** — The system **shall** REQ-4를 **1회성 오프라인 초기 시드**로 한정하고, 이후 온라인 가중치 튜닝은 SPEC-AI-041 자가개선 루프가 시드값에서 이어받도록 한다(동시 보정 금지).

### REQ-5: 평가 지표 갱신

목적: 풀별 정밀도/리콜 분석을 가능케 한다.

- **REQ-5.1 (Ubiquitous)** — The system **shall** `surge_prediction_evaluation`에 `scan_universe_size`, `pool_a_count`, `pool_b_count`, `pool_c_count` 컬럼을 추가한다.
- **REQ-5.2 (Event-Driven)** — When 일별 평가가 실행되면, the system **shall** 당일 유니버스 크기와 풀별 후보 수를 기록한다.
- **REQ-5.3 (Ubiquitous)** — The system **shall** 각 적중/미적중을 진입 풀 태그(`surge_metadata.entry_pool`, `FundSignal`→`Stock` 조인)로 귀속시켜 풀별 정밀도/리콜 산출을 가능케 한다.

---

## 4. Acceptance Criteria (수용 기준 — 측정 가능)

> 상세 Given-When-Then 시나리오는 `acceptance.md` 참조.

| ID | 기준 | 목표값 |
|---|---|---|
| AC-1 | 리콜 개선 | 0.6% → **≥ 3%** (5배, 월 25건+ 적중) |
| AC-2 | 정밀도 유지 | **≥ 15%** (월 30~40 발신 중 5건+ 적중) |
| AC-3 | 스캔 유니버스 확장 | 일 20~30 → **80~150 종목** |
| AC-4 | z-score 정규화 | 구현 및 콜드스타트 fallback 테스트 통과 |
| AC-5 | 모멘텀 연속 탐지기 | 앙상블 통합, `validate_ensemble_weights` 합=1.0 통과 |
| AC-6 | 풀별 지표 | `surge_prediction_evaluation`에 4개 컬럼 기록, 풀별 정밀도/리콜 조회 가능 |
| AC-7 | 회귀 없음 | 기존 7탐지기 시그널 생성 경로 무손상(예측 기록 모드 유지) |

---

## 5. Implementation Notes (구현 메모)

### 5.1 수정/신규 파일

| 파일 | 변경 | 내용 |
|---|---|---|
| `app/services/surge_baseline_service.py` | [NEW] | z-score 롤링 통계 산출/영속화 (순수 파이썬) |
| `app/models/stock_signal_baseline.py` | [NEW] | `stock_signal_baselines` 모델 |
| `app/services/surge_detector.py` | [MODIFY] | 유니버스 빌더(3 풀), `momentum_continuation` 탐지기, z-score 적용 |
| `app/services/surge_settings.py` | [MODIFY] | `EnsembleWeightsConfig` 8번째 필드 + `validate_ensemble_weights` 합 갱신, 신규 설정 섹션 |
| `surge_detection.yaml` / `surge_detection.auto.yaml` | [MODIFY] | 가중치 재조정, `momentum_continuation`/`scan_universe`/`baseline` 섹션 |
| `app/services/surge_evaluation_service.py` | [MODIFY] | 풀별 카운트·정밀도/리콜 집계 |
| `app/scheduler.py` | [MODIFY] | Pool C 장마감 수집 잡, 유니버스 빌드 연결 (`timezone="Asia/Seoul"`, KST 직접) |
| `alembic/versions/063_*.py` | [NEW] | `down_revision=062` — 테이블 생성 + 컬럼 추가 |
| `scripts/recalibrate_ensemble_weights.py` | [NEW] | REQ-4 오프라인 로지스틱 회귀(순수 파이썬) |

### 5.2 DB 마이그레이션 (063, down_revision=062)

1. `CREATE TABLE stock_signal_baselines`: `id`, `stock_id`(FK→stocks.id), `detector_name`, `rolling_mean`, `rolling_std`, `sample_count`, `window_values`(JSON, 선택), `updated_at`. 유니크: `(stock_id, detector_name)`.
2. `ALTER TABLE surge_prediction_evaluation ADD COLUMN`: `scan_universe_size INT`, `pool_a_count INT`, `pool_b_count INT`, `pool_c_count INT` (모두 nullable, 기본 0).

### 5.3 앙상블 가중치 재조정 (8탐지기)

`momentum_continuation` 초기 0.12 추가 → 기존 7개 가중치를 비례 축소하여 합=1.0 유지. `EnsembleWeightsConfig` 필드 추가와 `validate_ensemble_weights` 합산 라인 갱신을 **동시에** 해야 검증 통과(선례: SPEC-AI-044/062 6→7 재조정). 최종값은 REQ-4 재보정으로 확정.

### 5.4 영역 분리 (충돌 방지)

- **본 SPEC**: 유니버스 입력 집합, z-score 상대 채점, `momentum_continuation` 탐지기, 풀별 지표, 가중치 **오프라인 시드**.
- **SPEC-AI-041**: 가중치 **온라인** 자동보정(5일 롤링) — REQ-4 시드 이후 이어받음.
- **SPEC-AI-029/038**: 확률 **임계값** / 레짐.
- **SPEC-AI-062**: `volume_breakout` 탐지기 정의·가중치.

---

## 6. Out of Scope / Exclusions (제외 항목 — What NOT to Build) [HARD]

- 실제 매수 실행/포트폴리오 로직 변경 — 예측 기록 모드(SPEC-AI-043) 유지. `execute_buy_orders`, `max_open_positions`, `max_daily_entries` 무변경.
- 인트라데이(분봉) 데이터·시가(`open_price`) 기반 신호 — 현 데이터 경로에서 미가용. 모든 등락률 판정은 전일 종가 대비 `change_rate`(일봉) 기준.
- numpy/scipy/sklearn 등 신규 수치 라이브러리 도입 — 순수 파이썬으로만 구현.
- SPEC-AI-041의 온라인 가중치 자동보정 알고리즘 재작성 — REQ-4는 1회성 오프라인 시드만 제공.
- SPEC-AI-029/038의 적응형 임계값·레짐 로직 변경.
- 신규 탐지기는 `momentum_continuation` 1개로 한정 — 추가 탐지기 신설 금지.
- 전체 시장(2000+ 종목) 무차별 스캔 — 유니버스는 3개 풀 + 기존 탐지로 한정하고 `max_scan_universe`(150)로 상한.
- 프론트엔드 UI/대시보드 변경 — 본 SPEC은 백엔드 예측·평가 파이프라인에 한정.

---

## 7. Risks (위험)

| 위험 | 영향 | 완화 |
|---|---|---|
| 유니버스 확장으로 FP 증가 → 정밀도 하락 | 정밀도 < 15% | 발신 게이팅(min_score+적응형 임계+상위 랭킹) 유지, z-score로 랭킹 품질 개선 |
| z-score 콜드스타트(신규/희소 종목 통계 부족) | 잘못된 정규화 | `min_baseline_samples` 미만 시 절대값 fallback(REQ-1.3) |
| 8탐지기 가중치 합 검증 누락 | 시그널 생성 전체 실패 | 모델 필드+검증 라인 동시 수정, 테스트로 합=1.0 강제(AC-5) |
| Pool C 2단계 조회 부하 | 스캔 지연 | `max_scan_universe` 상한 + 이력 우선·top_movers 보완(REQ-2.6) |
| 일봉 거래량 해상도 한계 | Pool B 신선도 판정 오차 | 일봉 기준 명시, 인트라데이 요구는 별도 SPEC |
