---
id: SPEC-AI-034
version: 0.1.0
status: draft
created: 2026-06-02
updated: 2026-06-02
author: MoAI
priority: Medium
issue_number: null
---

# SPEC-AI-034: 실적 기반 가중치 보정 (Performance-Based Weight Calibration)

## HISTORY

- 2026-06-02 (v0.1.0): 최초 작성. 현재 앙상블 가중치(theme_cluster: 0.28,
  volume_news_combo: 0.35, disclosure_pattern: 0.20, legacy_detectors: 0.17)는 초기
  SPEC 설계 시 **실제 매매 성과 데이터 없이 주관적으로 설정**된 값이며, 누적된 실거래
  성과로 교정된 적이 없다. 2026-06-02 운영 분석에서 다음 정황이 확인되었다.
  - `volume_news_combo` 신호: 6/6 실패(평균 -7.7%) — 가중치가 가장 높음에도 성과 최악.
  - `immediate_disclosure` 신호: +10~+15%로 최고 성과 — 가중치가 부재하거나 낮음.
  - `theme_cluster` 단독: 중립/혼조.
  본 SPEC은 `surge_trades` 테이블의 종료 거래와 `FundSignal.surge_metadata`의
  `surge_basis`를 결합해 탐지기별 승률·평균 수익률을 산출하고, **권고 가중치만 보고**하는
  읽기 전용 분석 서비스를 정의한다. 가중치 자동 적용은 범위에서 제외한다(사람이 검토 후
  `surge_detection.yaml`을 수동 갱신).

---

## 선행 SPEC (전제 조건 / Assumptions)

본 SPEC은 다음 기존 SPEC이 구축한 데이터 자산과 인프라 위에서 동작하며, 새 탐지기나 매매
엔진을 만들지 않는다. 데이터를 읽어 통계를 계산할 뿐, 설정·모델 스키마를 변경하지 않는다.

- **SPEC-AI-012 (급등 징후 탐지 시스템)**: `surge_detector.py`의 4개 탐지기와 앙상블
  스코어링, `FundSignal.surge_metadata`(Text, JSON 문자열), `surge_settings.py`의
  `EnsembleWeightsConfig`/`get_surge_config()` 설정 인프라를 도입했다.
  - **[HARD] 사실 확인 — 가중치 필드명**: `EnsembleWeightsConfig`의 실제 필드는
    `theme_cluster`, `volume_news_combo`, `disclosure_pattern`, **`legacy_detectors`**
    4개다(`legacy`가 아니라 `legacy_detectors`). 본 SPEC의 권고 가중치 출력은 이 정식
    필드명을 사용한다.
  - **[HARD] 사실 확인 — surge_metadata 구조**: `surge_metadata` JSON은
    `surge_basis`(list[str], 발화한 탐지기 이름 목록)를 포함한다. 관측된 탐지기 이름:
    `theme_cluster`, `volume_news_combo`, `disclosure_pattern`, `immediate_disclosure`,
    `sector_momentum`, `carry_over`. 본 SPEC은 이 `surge_basis`를 탐지기 단위 집계의
    근거로 사용한다.
  - **[HARD] 사실 확인 — 기존 추출 헬퍼 재사용**: `backend/app/services/surge_backtest.py`에
    이미 `_extract_combo_key(signal)`가 존재하여 `surge_metadata`에서 정렬된 탐지기
    조합 키(`"+".join(sorted(basis))`)를 추출한다. 본 SPEC의 조합 단위 집계는 이 헬퍼의
    로직을 재사용한다(중복 구현 금지).
- **SPEC-AI-013 (급등예측 페이퍼 트레이딩)**: `SurgeTrade`/`SurgePortfolio` 모델,
  `surge_trading_service.py` 매수/매도 실행 로직을 도입했다.
  - **[HARD] 사실 확인 — 손익 파생**: `SurgeTrade`에는 `profit`/`return_pct` 컬럼이
    **존재하지 않는다**. 종료 거래는 `exit_date IS NOT NULL`(= `is_open = False`)이며,
    수익률은 `(exit_price - entry_price) / entry_price`로, 승리는
    `exit_reason == "take_profit"` 또는 `exit_price > entry_price`로 파생한다.
    `entry_price`/`exit_price`는 `Numeric(15, 2)`, `surge_probability_score`는
    `Numeric(5, 4)` 타입이다.
  - **[HARD] 사실 확인 — 신호 연결**: `SurgeTrade.signal_id`는
    `fund_signals.id`를 가리키는 nullable FK다. 탐지기 조합은
    `SurgeTrade → FundSignal.surge_metadata`를 조인하여 얻는다. `signal_id`가 NULL인
    거래는 탐지기 귀속이 불가하므로 분석에서 제외한다.
- **SPEC-AI-018 (임계값·앙상블 정밀화)**: `min_score_for_signal` 상향과 앙상블 정밀화
  설정을 도입했다. 본 SPEC은 그 가중치 값을 **읽어 비교 기준(현행 가중치)으로만 사용**하며
  변경하지 않는다.

---

## Overview

본 SPEC은 누적된 페이퍼 트레이딩 성과로부터 탐지기별 신뢰도를 **객관적으로 산출**하고,
그 결과를 바탕으로 **권고 가중치(suggested_weights)를 보고**하는 읽기 전용 분석 서비스를
정의한다. 핵심 목적은 초기 설계 시 주관적으로 정한 앙상블 가중치를 실거래 데이터에 근거해
교정할 수 있도록, 사람이 판단할 수 있는 근거 보고서를 제공하는 것이다.

이 SPEC은 **무엇을(WHAT)**과 **왜(WHY)**를 정의하며, 구체적 함수 시그니처·SQL·집계 알고리즘
세부는 Run 단계로 이연한다.

### 분석 흐름 (개념)

1. 종료된 `SurgeTrade`(`exit_date IS NOT NULL`)를 `signal_id`로 `FundSignal`과 조인한다.
2. 각 거래에 대해 `FundSignal.surge_metadata.surge_basis`로부터 탐지기(또는 탐지기 조합)를
   식별한다(기존 `_extract_combo_key` 재사용).
3. 탐지기 단위로 그룹핑하여 승률·평균 수익률·표본 수를 계산한다.
4. 승률·평균 수익률에 비례해 권고 가중치를 도출하되, 표본 수에 따른 신뢰도 라벨을 부여한다.
5. 결과를 `DetectorPerformanceReport`로 반환한다. **설정 파일에 쓰지 않는다.**

### 신뢰도(confidence) 등급

| 등급 | 조건(총 분석 표본 수, `data_points`) | 의미 |
|---|---|---|
| `low` | < 50 | 표본 부족 — 참고용. 가중치 변경 권장하지 않음 |
| `medium` | 50 ~ 100 | 방향성 참고 가능 — 신중한 조정 검토 |
| `high` | > 100 | 통계적 신뢰 — 조정 검토 가능 |

### 출력 예시 (개념 — 실제 수치는 데이터에 따름)

```json
{
  "by_detector": {
    "immediate_disclosure": {"win_rate": 0.80, "avg_return": 0.12, "count": 5},
    "volume_news_combo":    {"win_rate": 0.15, "avg_return": -0.07, "count": 13},
    "theme_cluster":        {"win_rate": 0.45, "avg_return": 0.02, "count": 20}
  },
  "suggested_weights": {
    "immediate_disclosure": 0.40,
    "volume_news_combo":    0.20,
    "theme_cluster":        0.28,
    "disclosure_pattern":   0.20,
    "legacy_detectors":     0.17
  },
  "data_points": 30,
  "analysis_date": "2026-06-02",
  "confidence": "low"
}
```

> 비고: `suggested_weights`의 키는 `EnsembleWeightsConfig`의 정식 필드명을 따른다
> (`legacy_detectors` 포함). 표본이 없는 탐지기는 현행 가중치를 그대로 유지한 채 보고한다.

---

## 설계 원칙 (Design Principles)

1. **Read-only (읽기 전용)**: 본 서비스는 어떤 설정 파일·모델 스키마도 쓰지 않는다.
   DB는 SELECT만 수행한다. `surge_detection.yaml` 갱신은 사람의 책임이다.
2. **Derived metrics (파생 지표)**: 승률·수익률은 `SurgeTrade`의 `entry_price`/
   `exit_price`/`exit_reason`으로부터 파생한다. 새 비정규화 컬럼을 추가하지 않는다.
3. **No auto-apply (자동 적용 없음)**: `suggested_weights`는 권고일 뿐이다. 코드가
   가중치를 적용·반영하는 경로를 만들지 않는다.
4. **Statistical humility (통계적 겸손)**: 표본 수에 비례한 `confidence` 라벨을 항상
   반환하고, 표본 미달 조합은 보고서에서 제외한다(최소 5건).
5. **Reuse over reinvent (재사용 우선)**: 탐지기 조합 추출은 기존
   `surge_backtest._extract_combo_key`의 로직을 재사용한다.
6. **No ML/regression (회귀·학습 없음)**: 단순 집계 통계만 사용한다. 회귀 분석,
   최적화 솔버, 학습 모델은 도입하지 않는다.

---

## EARS Requirements

### REQ-AI034-001: 종료 거래와 신호 조인 후 탐지기별 성과 집계

The system **shall** provide a `calculate_detector_performance(db)` analysis function
in `backend/app/services/surge_calibration_service.py` that joins closed `SurgeTrade`
rows (`exit_date IS NOT NULL`) with `FundSignal` via `SurgeTrade.signal_id`, and groups
them by the detector identity derived from `FundSignal.surge_metadata.surge_basis`
(reusing the `_extract_combo_key` extraction logic from
`backend/app/services/surge_backtest.py`).

For each detector group, the system **shall** compute:

- `win_rate`: the proportion of trades where `exit_reason == "take_profit"` **or**
  `exit_price > entry_price`.
- `avg_return`: the average of `(exit_price - entry_price) / entry_price` across the
  group's trades.
- `count`: the number of trades in the group.

**Where** a `SurgeTrade.signal_id` is `NULL`, or the joined `FundSignal.surge_metadata`
is absent or unparseable, the system **shall** exclude that trade from detector
attribution (it **shall not** be counted toward any detector group).

### REQ-AI034-002: 최소 표본 수 필터 (탐지기 조합당 5건)

**If** a detector group has fewer than `5` trades, **then** the system **shall**
exclude that group from the `by_detector` section of the report (groups below the
minimum sample size **shall not** appear as recommendation-bearing rows). Excluded
trades **shall** still be counted toward the report-level `data_points` total so that
the reported sample size reflects all analyzed trades.

### REQ-AI034-003: 권고 가중치 산출 및 신뢰도 라벨링

**When** the system produces a `DetectorPerformanceReport`, the system **shall**
populate `suggested_weights` keyed by the canonical `EnsembleWeightsConfig` field names
(`theme_cluster`, `volume_news_combo`, `disclosure_pattern`, `legacy_detectors`, and
any additional detector identities observed such as `immediate_disclosure`), where each
suggested weight is derived from the detector's win rate and average return relative to
the other detectors.

**Where** a detector has no qualifying trades (below the REQ-AI034-002 minimum), the
system **shall** carry forward that detector's current weight from `get_surge_config()`
unchanged rather than dropping or zeroing it.

The system **shall** set the report-level `confidence` field based on the total
`data_points`: `"low"` when `data_points < 50`, `"medium"` when
`50 <= data_points <= 100`, and `"high"` when `data_points > 100`.

### REQ-AI034-004: GET /api/surge-trading/detector-performance 엔드포인트

The system **shall** expose a `GET /api/surge-trading/detector-performance` endpoint in
`backend/app/routers/surge_trading.py` (router prefix `/api/surge-trading`) that returns
the `DetectorPerformanceReport`. The endpoint **shall** be read-only and **shall not**
apply, persist, or write any weight values.

**Where** the optional `min_date` query parameter is supplied (ISO date), the endpoint
**shall** restrict the analysis to trades whose `exit_date >= min_date`. **Where**
`min_date` is omitted, the endpoint **shall** analyze all closed trades.

**Where** there are no closed trades (or none after applying `min_date`), the endpoint
**shall** return a well-formed report with an empty `by_detector`, `data_points` of `0`,
`confidence` of `"low"`, and the current weights echoed in `suggested_weights`, rather
than returning an error.

### REQ-AI034-005: 읽기 전용 보장 — 설정·스키마 불변

The system **shall not** write to `surge_detection.yaml`, **shall not** mutate
`EnsembleWeightsConfig` or any configuration object in memory in a way that persists,
and **shall not** alter any database table schema. All weight changes implied by
`suggested_weights` **shall** require a human to manually edit `surge_detection.yaml`.

The `DetectorPerformanceReport` **shall** include `analysis_date` (the date the report
was generated) so that consumers can record when a recommendation was produced.

---

## 데이터 모델 (Pydantic 출력 모델)

신규 SQLAlchemy 모델이나 마이그레이션은 **발생하지 않는다**(읽기 전용). 출력 직렬화를 위한
Pydantic 모델만 추가한다.

`DetectorPerformanceReport` (Pydantic v2 `BaseModel`):

| 필드 | 타입 | 설명 |
|---|---|---|
| `by_detector` | `dict[str, DetectorStat]` | 탐지기(또는 조합)별 통계. 최소 5건 충족 그룹만 포함 |
| `suggested_weights` | `dict[str, float]` | 권고 가중치 (EnsembleWeightsConfig 정식 필드명) |
| `data_points` | `int` | 분석에 사용된 종료 거래 총 수(필터 제외 거래 포함 집계) |
| `analysis_date` | `str` (ISO date) | 보고서 생성일 |
| `confidence` | `Literal["low","medium","high"]` | 표본 기반 신뢰도 등급 |

`DetectorStat` (중첩 모델):

| 필드 | 타입 | 설명 |
|---|---|---|
| `win_rate` | `float` | 승률 (0.0~1.0) |
| `avg_return` | `float` | 평균 수익률 (소수, 예: 0.12 = +12%) |
| `count` | `int` | 그룹 거래 수 |

---

## Implementation Scope

| 파일 | 변경 내용 | 관련 REQ |
|---|---|---|
| `backend/app/services/surge_calibration_service.py` (신규) | `calculate_detector_performance(db, min_date=None)` 분석 함수, `DetectorPerformanceReport`/`DetectorStat` Pydantic 모델, `_extract_combo_key` 재사용한 탐지기 귀속, 승률·수익률·신뢰도 산출, 권고 가중치 도출 | REQ-AI034-001~003, 005 |
| `backend/app/routers/surge_trading.py` | `GET /detector-performance` 엔드포인트 추가(`min_date` query param), 읽기 전용 보고서 반환 | REQ-AI034-004, 005 |
| `backend/tests/test_surge_ai034.py` (신규) | 종료거래 조인·집계, 5건 미만 필터, 승률/수익률 파생(`exit_reason`/가격), signal_id NULL 제외, 신뢰도 등급 경계(49/50/100/101), min_date 필터, 빈 데이터 폴백, 설정 파일 미변경(읽기 전용) 검증 | 전체 |

---

## Acceptance Criteria

| ID | 기준 | 검증 방법 (pytest) |
|---|---|---|
| AC-034-01 | 종료 거래만 집계(`exit_date IS NOT NULL`), 미종료 거래 제외 | open 거래 fixture 섞어 호출 → open 건 제외 확인 |
| AC-034-02 | 승률 = `exit_reason=="take_profit"` 또는 `exit_price>entry_price` 비율 | 5건 fixture(승 3/패 2) → win_rate=0.6 |
| AC-034-03 | avg_return = `(exit_price-entry_price)/entry_price` 평균 | 알려진 가격 fixture → 기대 평균 일치(소수 비교) |
| AC-034-04 | 탐지기 그룹핑은 surge_metadata.surge_basis 기반(`_extract_combo_key` 재사용) | volume_news_combo/immediate_disclosure 혼합 fixture → 그룹 분리 확인 |
| AC-034-05 | 그룹 거래 5건 미만이면 by_detector에서 제외 | 4건 그룹 fixture → by_detector에 미포함 |
| AC-034-06 | 5건 미만 그룹 거래도 data_points 총합에는 포함 | 4건 그룹 + 6건 그룹 → data_points=10, by_detector 1개 |
| AC-034-07 | signal_id NULL 또는 surge_metadata 파싱 실패 거래는 탐지기 귀속 제외 | signal_id=None fixture → 어느 그룹에도 미집계 |
| AC-034-08 | confidence: <50 "low", 50~100 "medium", >100 "high" | data_points 49/50/100/101 fixture → low/medium/medium/high |
| AC-034-09 | suggested_weights 키는 EnsembleWeightsConfig 정식 필드명(legacy_detectors 포함) | 보고서 키 집합에 legacy_detectors 존재 확인 |
| AC-034-10 | 표본 없는 탐지기는 현행 가중치 유지(0/누락 아님) | disclosure_pattern 표본 0 fixture → 현행값 그대로 echo |
| AC-034-11 | GET /api/surge-trading/detector-performance가 보고서 반환(200) | TestClient GET 200, 5개 최상위 필드 존재 |
| AC-034-12 | min_date query param 적용 시 exit_date >= min_date만 분석 | 경계 일자 fixture → 이전 거래 제외 확인 |
| AC-034-13 | 종료 거래 0건(또는 min_date 후 0건)이면 빈 보고서(에러 아님) | 빈 DB GET → 200, data_points=0, by_detector={}, confidence="low" |
| AC-034-14 | 호출 전후 surge_detection.yaml 파일 내용 불변(읽기 전용) | 파일 해시 호출 전후 비교 동일 |
| AC-034-15 | 신규 모델/마이그레이션 없음(스키마 불변) | 마이그레이션 디렉터리 변경 없음, DB alter 없음 |
| AC-034-16 | 기존 회귀 테스트 전체 통과 | `cd backend && uv run pytest tests/ -m "not slow"` 100% 통과 |

---

## Non-Goals (What NOT to Build)

본 SPEC의 범위에서 **명시적으로 제외**되는 항목:

- **가중치 자동 적용(auto-apply)은 포함하지 않는다.** `suggested_weights`는 보고용
  권고일 뿐이며, 코드가 `surge_detection.yaml`을 수정하거나 `EnsembleWeightsConfig`를
  런타임에 영속 변경하는 경로를 만들지 않는다. 적용은 사람이 YAML을 직접 편집한다.
- **머신러닝·회귀 분석·최적화 솔버는 포함하지 않는다.** 단순 집계 통계(승률, 평균
  수익률, 표본 수)만 사용한다. 선형 회귀, 베이지안 추론, 가중치 최적화 알고리즘 등은
  제외한다.
- **신규 DB 테이블·컬럼·마이그레이션은 발생하지 않는다.** 본 SPEC은 읽기 전용이며
  `SurgeTrade`/`FundSignal` 스키마를 변경하지 않는다. 보고서 영속화(history 테이블)는
  별도 후속 SPEC 후보다.
- **`SurgeTrade`에 profit/return_pct 컬럼 추가는 포함하지 않는다.** 승률·수익률은 기존
  `entry_price`/`exit_price`/`exit_reason`으로 파생한다.
- **탐지기 로직·앙상블 합산 검증(`validate_ensemble_weights`) 변경은 포함하지 않는다.**
  본 SPEC은 기존 탐지기 출력의 성과를 사후 집계할 뿐, 탐지·스코어링 경로를 수정하지
  않는다.
- **백테스팅 하네스 재구축은 포함하지 않는다.** 기존 `surge_backtest.py`의 조합 추출
  로직(`_extract_combo_key`)을 재사용하되, 백테스트 엔진 자체를 변경·대체하지 않는다.
- **권고 가중치의 정규화(합=1.0) 강제는 본 SPEC의 필수 범위가 아니다.** 권고값은 검토
  근거이며, 실제 적용 시 사람이 `validate_ensemble_weights`(합산 1.0) 제약을 충족하도록
  조정한다. (Run 단계에서 정규화 표시를 부가 제공할 수 있으나 자동 적용은 금지.)
- **인증·권한 모델 변경은 포함하지 않는다.** 기존 라우터 인증 패턴(`_verify_admin_token`)을
  따르며 새 인증 체계를 만들지 않는다.
- **스케줄러 연동(주기적 자동 분석)은 포함하지 않는다.** 본 SPEC은 온디맨드 API 조회만
  제공한다. 정기 보고 자동화는 별도 후속 SPEC 후보다.
- **GitHub 이슈 생성은 포함하지 않는다.** 로컬 전용이다.

---

## References

### 코드 위치 (수정/신규 대상)

- `backend/app/services/surge_calibration_service.py` (신규) — 분석 서비스 + Pydantic 모델
  (REQ-AI034-001~003, 005)
- `backend/app/routers/surge_trading.py` — `GET /detector-performance` 엔드포인트
  (라우터 prefix `/api/surge-trading`, 라인 15) (REQ-AI034-004)
- `backend/app/services/surge_backtest.py` — `_extract_combo_key()` 재사용 대상
  (라인 133~148) (REQ-AI034-001)
- `backend/app/surge_config/surge_settings.py` — `EnsembleWeightsConfig`(라인 61~67,
  필드 `theme_cluster`/`volume_news_combo`/`disclosure_pattern`/`legacy_detectors`),
  `get_surge_config()` — 현행 가중치 echo 출처 (REQ-AI034-003)
- `backend/tests/test_surge_ai034.py` (신규) — 전체 검증

### 데이터 모델 사실 확인

- `SurgeTrade` (`backend/app/models/surge_portfolio.py`): `entry_price`(Numeric 15,2),
  `exit_price`(Numeric 15,2, nullable), `exit_reason`(String 50, nullable: `stop_loss`/
  `take_profit`/`max_holding_period`/`manual`), `exit_date`(Date, nullable),
  `is_open`(Boolean, index), `signal_id`(FK→fund_signals.id, nullable),
  `surge_probability_score`(Numeric 5,4, nullable). **profit/return_pct 컬럼 없음.**
- `FundSignal` (`backend/app/models/fund_signal.py`): `surge_metadata`(Text, JSON 문자열,
  `surge_basis` list 포함). 관측된 탐지기 이름: `theme_cluster`, `volume_news_combo`,
  `disclosure_pattern`, `immediate_disclosure`, `sector_momentum`, `carry_over`.
- `EnsembleWeightsConfig` (`backend/app/surge_config/surge_settings.py` 라인 61): 필드
  `theme_cluster`/`volume_news_combo`/`disclosure_pattern`/`legacy_detectors`. 현행값
  0.28 / 0.35 / 0.20 / 0.17. (참고: 사용자 배경의 `legacy`는 정식 `legacy_detectors`.)
- 라우터 prefix: `/api/surge-trading` (`surge_trading.py` 라인 15), 인증 헬퍼
  `_verify_admin_token`(`auth.py`).

### 선행 SPEC

- SPEC-AI-012: 급등 징후 탐지 시스템 (탐지기, surge_metadata/surge_basis, 가중치 설정 인프라)
- SPEC-AI-013: 급등예측 페이퍼 트레이딩 (SurgeTrade/SurgePortfolio, entry/exit 가격)
- SPEC-AI-018: 임계값·앙상블 정밀화 (현행 가중치 기준값 출처)
