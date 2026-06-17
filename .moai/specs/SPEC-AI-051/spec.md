---
id: SPEC-AI-051
version: 1.0.0
status: completed
created: 2026-06-17
updated: 2026-06-17
author: kyunghwan
priority: high
issue_number: 0
---

# SPEC-AI-051: 급등주 탐지 커버리지 확장 3종 — 볼린저 밴드 스퀴즈 + 공시 키워드 고도화 + 14:30 런너 파이프라인 (Surge Detection Coverage Expansion: Bollinger Squeeze + Disclosure Keyword Tiering + 14:30 Runner Pipeline)

## HISTORY

- 2026-06-17 (v1.0.0): 최초 작성. 현행 급등 탐지 파이프라인이 놓치는 3개 공백을 메우는 3개 독립 기능 정의.
  1. **볼린저 밴드 스퀴즈 탐지기**(`detect_bollinger_squeeze_signals`) — 뉴스·공시 트리거가 전혀 없는 기술적 에너지 압축 급등을 사전 포착.
  2. **공시 키워드 가중치 사전 강화**(`score_disclosure_impact` 수정) — FDA 승인·국가전략기술 등 고가치 공시의 과소평가 교정.
  3. **14:30 KST 갭상승 런너 파이프라인**(`detect_gap_up_runners`) — 당일 급등 리더 종목의 동일 섹터 2/3등 종목을 익일 갭상승 후보로 사전 등록.
  선행 SPEC: SPEC-AI-004(공시 임팩트 스코어러), SPEC-AI-013(15:20 시그널 전일 생성), SPEC-AI-023(near_limit_up carry-forward 패턴), SPEC-AI-042(preday early_entry 폐루프), SPEC-AI-043(예측 기록 모드 전환). 본 SPEC은 DB 마이그레이션을 추가하지 않으며, 기존 탐지기 가중치를 변경하지 않는다(스퀴즈는 가산만).

---

## 선행 SPEC (전제 조건 / Assumptions)

| 선행 SPEC | 본 SPEC이 의존하는 자산 |
|---|---|
| SPEC-AI-004 | `score_disclosure_impact()` 공시 충격 점수 계산 로직 (Feature 2가 수정) |
| SPEC-AI-013 | 15:20 KST `surge_signal_generate` 잡 — Feature 1의 15:10 잡이 그 직전에 실행 |
| SPEC-AI-023 | `detect_near_limit_up_carries()` FundSignal 생성·중복방지 패턴 (Feature 3의 참조 구현) |
| SPEC-AI-042 | `preday_signal_service.early_entry_check()` 09:05 조기 진입 메커니즘 (Feature 3의 익일 실행 소비자) |
| SPEC-AI-043 | 예측 기록 모드 — `surge_execute_buys` 잡 비활성화. Feature 3은 실거래가 아닌 시그널 예측 기록을 산출 |

### [HARD] 사실 확인 (코드 검증 2026-06-17)

- **`_bollinger_bands(prices, period=20, std_dev=2.0)` 존재** — `technical_indicators.py:139-151`. 반환값은 `(upper, middle, lower)` 튜플(셋 다 `float | None`, `len(prices) < period`이면 `(None, None, None)`). period가 첫 20개 가격만 사용하므로 **입력 리스트는 최신순 정렬을 가정**한다.
- **`fetch_stock_price_history_sync(stock_code, pages=3)` 존재** — `naver_finance.py:779-807`. `pages=3` ≈ 30 거래일. **60+ 거래일 확보에는 `pages=6` 이상 필요**. 반환 `list[PriceRecord]`. `PriceRecord`(`naver_finance.py:628-637`) 필드: `date`(str, "2026.02.26"), `close`(int), `open`(int), `high`(int), `low`(int), `volume`(int). **`close`는 `int` 타입이며 일봉은 최신순(내림차순)으로 반환**된다.
- **`SurgeCandidate` dataclass** — `surge_detector.py:58-81`. 현행 필드: `stock_code`, `stock_name`, `theme_cluster_score`, `combo_score`, `pattern_score`, `legacy_score`, `immediate_disclosure_score`, `active_detectors`, `price_5d_trend`, `per`, `pbr`, `disclosure_sentiment`, `news_delayed_score`. **`squeeze_score` 필드는 존재하지 않음 → 신규 추가 필요**.
- **`score_disclosure_impact(disclosure, market_cap_億)` 다중 조기 반환** — `disclosure_impact_scorer.py:138-182`. 반환 경로: (1) 루틴 거버넌스 → `5.0` 고정 반환(line 154), (2) 수주/계약 비율 기반(line 163), (3) 실적변동 % 추출(line 171), (4) `_BASE_IMPACT_BY_TYPE` 기본값(line 176-182). **Tier 배수는 (2)(3)(4) 경로의 최종 점수에 적용해야 하며, 루틴 거버넌스 캡(5.0)에는 적용하지 않는다**. 기존 키워드 상수: `_CONTRACT_KEYWORDS`(line 48), `_MNA_KEYWORDS`(line 70-80), `_MNA_BONUS=20`(line 81).
- **`FundSignal` 생성 패턴** — `detect_near_limit_up_carries()`(`surge_detector.py:1811-1918`). 핵심 필드: `stock_id`(FK→Stock.id, **stock_code 컬럼 없음**), `signal="buy"`, `signal_type`(String), `confidence`, `reasoning`, `surge_metadata`(JSON 문자열, `surge_basis` 리스트 포함), `price_at_signal`. 현재가 주입은 `_fetch_price_change_sync(stock_code)` → `{"current_price": int, "change_rate": float}`.
- **`Stock` 모델** — `stock.py:9-23`. `sector_id`(Integer FK→sectors.id, **non-nullable**), `market_cap`(BigInteger, **억원 단위**, nullable), `sector` relationship 존재.
- **중복 진입 방지 헬퍼 존재** — `get_open_position(db, stock_code)`(`surge_trading_service.py:432`)가 `SurgeTrade.is_open.is_(True)` + stock_code로 미체결 포지션을 조회. Feature 3의 "이미 오픈된 SurgeTrade에 없는 종목"을 이 헬퍼로 판정한다.
- **[HARD] 09:05 소비자 필터 제약** — `early_entry_check()`(`preday_signal_service.py:366`)는 `FundSignal.signal_type == "preday_disclosure"`로 **엄격 필터링**한다. 따라서 `gap_up_runners` 시그널은 **자동으로 픽업되지 않는다**. Feature 3 통합은 (a) `early_entry_check`의 signal_type 필터를 `gap_up_runners` 포함하도록 확장하거나, (b) `gap_up_runners` 전용 09:05 소비자를 추가해야 한다 — REQ-AI051-010에서 명시.
- **스케줄러 잡 등록 패턴** — `scheduler.py`. `scheduler.add_job(func, "cron", day_of_week="mon-fri", hour=H, minute=M, timezone="Asia/Seoul", id=..., max_instances=1, coalesce=True, replace_existing=True)`. KST 시각 직접 지정(UTC 변환 불요). 15:20 잡 id=`surge_signal_generate`(line 1772-1783), 10:00 잡 id=`surge_signal_generate_intraday`(line 1787-1798). **신규 잡 id는 충돌 회피 필수**.
- **BUY_CUTOFF** — `surge_trading_service.py:31` `BUY_CUTOFF = time(11, 0)`. Feature 3의 14:30 시그널은 **당일 체결 대상이 아님**(target_date=익일) → BUY_CUTOFF 충돌 없음.

---

## 배경 (Overview)

현행 급등 탐지 파이프라인은 다음 3개 유형의 급등을 구조적으로 놓친다.

### 공백 1 — 트리거 없는 기술적 압축 급등

현재 모든 탐지기는 외부 촉매(뉴스·공시·거래량 이상·테마 클러스터)에 의존한다. 그러나 실제 급등의 상당수는 **변동성이 극도로 수축된 횡보 구간 직후 발생하는 기술적 분출**이다. 볼린저 밴드 폭(BandWidth)이 일정 기간 최저로 수축한 "스퀴즈" 상태는 에너지 압축의 정량 지표이며 통상 1~2거래일의 선행 시간을 제공한다. `_bollinger_bands()` 헬퍼는 이미 존재하나, **60일 최저 밴드폭 비교 로직과 이를 호출하는 탐지기가 전무**하여 이 유형을 전혀 포착하지 못한다.

### 공백 2 — 고가치 공시의 과소평가

`score_disclosure_impact()`는 공시 유형(`report_type`)별 기본 충격 점수와 수주금액/시총 비율로 점수를 산정한다. 그러나 "FDA 승인", "세계 최초", "국가전략기술" 같은 **질적으로 폭발력이 큰 키워드가 점수에 반영되지 않아**, 동일 유형의 루틴 공시와 동일 점수를 받는다. 그 결과 `immediate_disclosure` 탐지기가 FDA급 이벤트를 일반 공시로 분류하여 시그널 강도를 과소 산정한다.

### 공백 3 — 테마 리더만 잡고 추종주를 놓침

당일 급등 리더(surge_candidate / immediate_disclosure 고신뢰 시그널)는 포착하나, **동일 섹터의 2/3등 추종 종목(런너)은 익일 갭상승 가능성이 높음에도 사전 후보로 등록되지 않는다**. 리더 급등은 동일 테마 종목의 익일 갭상승을 유발하는 선행 지표이지만, 이를 익일 예측에 활용하는 파이프라인이 없다.

## 목표 (Objectives)

1. **볼린저 밴드 스퀴즈 탐지기 신설**: 활성 종목의 60+ 거래일 일봉으로 BandWidth를 계산하여 당일 밴드폭이 60일 최저 이하인 종목을 스퀴즈 후보로 탐지하고, `SurgeCandidate.squeeze_score`를 채워 15:10 KST에 일일 산출한다.
2. **공시 키워드 Tier 배수 도입**: Tier 1(×2.0)/Tier 2(×1.5)/Tier 3(×1.2) 키워드 사전을 추가하여, 매칭되는 **최고 Tier 1개의 배수만** 공시 기본 점수에 곱하고 100점으로 캡한다.
3. **14:30 KST 갭상승 런너 파이프라인 신설**: 당일 고신뢰 리더 시그널의 섹터 2/3등 종목을 `gap_up_runners` 시그널로 생성하여 익일 09:05 조기 진입 소비자가 처리하도록 등록한다(당일 미체결).

## 가정 및 데이터 제약 (Assumptions & Data Constraints)

- **일봉 스크레이프 부하**: Feature 1은 활성 종목(수십~수백 종목) × `pages≥6`(60거래일) Naver 일봉 요청을 발생시킨다. `fetch_stock_price_history_sync`는 5초 타임아웃 + TTL 캐시를 사용하므로 캐시 히트율에 성능이 좌우된다. 후보 종목 수 상한(`max_stocks_to_check`)으로 부하를 제한한다.
- **밴드폭 데이터 충분성**: 60거래일 미만 데이터(신규 상장·거래 정지)인 종목은 스퀴즈 판정 대상에서 제외한다(`None` 반환 시 스킵).
- **정렬 가정**: `PriceRecord` 리스트는 최신순(내림차순)이며 `_bollinger_bands`는 입력 앞부분 `period`개를 사용하므로, 슬라이딩 윈도우 BandWidth 계산 시 각 영업일 기준 정렬을 명시적으로 관리한다.
- **Feature 3은 예측 기록 모드(SPEC-AI-043)에서 동작**: `surge_execute_buys`가 비활성이므로 `gap_up_runners` 시그널은 실거래가 아닌 익일 예측 기록으로 평가된다.
- **DB 마이그레이션 없음**: `gap_up_runners`는 기존 `FundSignal.signal_type`(String) 값으로 표현하며 신규 컬럼/테이블을 추가하지 않는다. `squeeze_score`는 런타임 dataclass 필드이며 DB 영속화하지 않는다.
- **섹터 피어 산정**: `Stock.sector_id`(non-nullable) 기준 동일 섹터 종목을 `market_cap` 내림차순 정렬한다. `market_cap`이 NULL인 종목은 순위 산정에서 제외한다.

---

## EARS Requirements (요구사항)

### Module 1 — 볼린저 밴드 스퀴즈 탐지기 (Feature 1)

- **REQ-AI051-001** (Ubiquitous): The 시스템 **shall** `SurgeCandidate` dataclass(`surge_detector.py`)에 `squeeze_score: float = 0.0` 필드를 추가하여, 스퀴즈 강도를 0.0~1.0 범위로 보관한다. 기존 필드와 기본값은 변경하지 않는다.

- **REQ-AI051-002** (Event-Driven): When `detect_bollinger_squeeze_signals(db, config)`가 호출되면, the 시스템 **shall** 각 활성 종목에 대해 `fetch_stock_price_history_sync(stock_code, pages≥6)`로 60+ 거래일 종가를 확보하고, 각 영업일 기준 BandWidth = (BB상단 − BB하단) / BB중심(period=20, `_bollinger_bands` 재사용)을 계산하여 **당일 BandWidth가 직전 60거래일 BandWidth 최저값 이하인 종목**을 스퀴즈 후보로 판정하고 `squeeze_score`를 채운 `SurgeCandidate`로 반환한다.
  - `squeeze_score`는 당일 밴드폭의 60일 최저 대비 압축 정도를 0.0~1.0으로 정규화한다(설정 가능한 산식, 하드코딩 금지).
  - 60거래일 미만 데이터 또는 `_bollinger_bands`가 `None`을 반환하는 종목은 결과에서 제외한다.

- **REQ-AI051-003** (Event-Driven): When 거래일 15:10 KST 신규 스케줄러 잡이 트리거되면, the 시스템 **shall** `detect_bollinger_squeeze_signals`를 실행한다. 이 잡은 15:20 KST `surge_signal_generate` 잡보다 **반드시 먼저** 완료되도록 일정을 배치하며, 신규 고유 잡 id를 사용하여 기존 잡과 충돌하지 않는다.

### Module 2 — 공시 키워드 가중치 사전 강화 (Feature 2)

- **REQ-AI051-004** (Ubiquitous): The 시스템 **shall** `disclosure_impact_scorer.py`에 3개 Tier 키워드 사전을 정의한다.
  - Tier 1 (×2.0): `FDA 승인`, `세계 최초`, `독점 공급`, `최대주주 변경`, `국가전략기술`, `국책사업 선정`
  - Tier 2 (×1.5): `공급계약 체결`, `지분 인수`, `합병`, `MOU 체결`, `수주`(단독 계약), `자사주 소각`(50억 이상)
  - Tier 3 (×1.2): `신제품 출시`, `신규 수주`, `매출 급증`, `계열사 지원`

- **REQ-AI051-005** (Event-Driven): When `score_disclosure_impact(disclosure, market_cap_億)`가 base 점수를 산정한 후, the 시스템 **shall** `report_name`(및 `ai_summary`)에서 매칭되는 키워드 중 **최고 Tier 1개의 배수만** 최종 점수에 곱한다. 배수는 누적되지 않으며(공시당 1개), 최종 점수는 100으로 캡한다(기존 동작 보존).

- **REQ-AI051-006** (Unwanted Behavior): If 공시가 루틴 거버넌스 캡(5.0 고정 반환, `disclosure_impact_scorer.py:154`) 경로에 해당하면, **then** the 시스템 **shall** Tier 배수를 적용하지 않고 5.0을 그대로 반환한다(루틴 공시 오발 방지).

### Module 3 — 14:30 KST 갭상승 런너 파이프라인 (Feature 3)

- **REQ-AI051-007** (Event-Driven): When `detect_gap_up_runners(db, config)`가 호출되면, the 시스템 **shall** 당일 생성된 FundSignal 중 `signal_type IN ('surge_candidate', 'immediate_disclosure')` AND `confidence >= 0.75`인 리더 종목을 조회하고, 각 리더의 동일 `sector_id` 종목을 `market_cap` 내림차순으로 정렬한 뒤 **2등·3등 피어(런너)**를 선정한다.

- **REQ-AI051-008** (State-Driven): While 런너 후보 선정 중, the 시스템 **shall** `get_open_position(db, stock_code)`로 이미 오픈된 `SurgeTrade`가 있는 종목을 후보에서 제외하고, 각 런너의 현재가를 `_fetch_price_change_sync(stock_code)`로 조회하여 주입한다.

- **REQ-AI051-009** (Event-Driven): When 런너 종목이 확정되면, the 시스템 **shall** `signal="buy"`, `signal_type="gap_up_runners"`, `confidence = leader.confidence * 0.7`, `reasoning = "오늘 [리더명] +X% 급등 테마 2/3등 종목, 익일 갭상승 저격"`, `surge_metadata.surge_basis = ["gap_up_runners"]`, `price_at_signal=<현재가>`로 `FundSignal`을 생성한다(`stock_id` 기준, stock_code 컬럼 없음). 신규 DB 마이그레이션은 추가하지 않는다.

- **REQ-AI051-010** (Event-Driven): When 거래일 14:30 KST 신규 스케줄러 잡(Mon-Fri)이 트리거되면, the 시스템 **shall** `detect_gap_up_runners`를 실행한다. 생성된 `gap_up_runners` 시그널이 익일 09:05 KST 조기 진입에서 처리되도록, the 시스템 **shall** `early_entry_check()`(`preday_signal_service.py`)의 signal_type 필터를 `gap_up_runners` 포함하도록 확장하거나 전용 09:05 소비자를 추가한다(자동 픽업 불가 — 현행 필터는 `preday_disclosure`만 허용). 14:30 시그널은 당일 체결 대상이 아니므로(target_date=익일) BUY_CUTOFF와 충돌하지 않는다.

---

## 영향 받는 파일 (Affected Files)

| 파일 | 변경 유형 | 내용 |
|---|---|---|
| `backend/app/services/surge_detector.py` | [MODIFY] | `SurgeCandidate`에 `squeeze_score` 필드 추가(REQ-001); `detect_bollinger_squeeze_signals()` 신규(REQ-002); `detect_gap_up_runners()` 신규(REQ-007~009) |
| `backend/app/services/technical_indicators.py` | [MODIFY] | `calculate_bollinger_bandwidth_squeeze()` 헬퍼 신규(60일 최저 밴드폭 비교). 기존 `_bollinger_bands()`는 무변경 재사용 |
| `backend/app/services/disclosure_impact_scorer.py` | [MODIFY] | Tier 1/2/3 키워드 사전 추가(REQ-004); `score_disclosure_impact()`에 최고 Tier 배수 적용 로직 추가(REQ-005, REQ-006) |
| `backend/app/services/scheduler.py` | [MODIFY] | 15:10 KST 스퀴즈 잡 추가(REQ-003); 14:30 KST 런너 잡 추가(REQ-010) |
| `backend/app/services/preday_signal_service.py` | [MODIFY] | `early_entry_check()` signal_type 필터 확장 또는 전용 소비자 추가(REQ-010) |
| `backend/tests/...` | [NEW] | 스퀴즈/키워드 Tier/런너 단위 테스트 |

---

## 제외 범위 (What NOT to Build)

- **실시간 틱 데이터 / WebSocket 피드 미도입**: KIS OpenAPI가 필요하며 본 SPEC 범위 밖. 스퀴즈·갭상승 판정은 일봉/장중 폴링 데이터로만 수행한다.
- **14:30 당일 체결 미구현**: BUY_CUTOFF(11:00)를 14:30 당일 매수용으로 변경하지 않는다. 14:30 시그널은 익일(target_date=tomorrow) 전용이다.
- **Tier 4/5 키워드 미추가**: 키워드 사전은 정확히 3개 Tier로 제한한다.
- **기존 탐지기 가중치 변경 금지**: `EnsembleWeightsConfig`의 `theme_cluster`/`volume_news_combo`/`disclosure_pattern`/`legacy_detectors` 가중치를 변경하지 않는다. 스퀴즈는 **가산(additive)**으로만 통합한다.
- **DB 마이그레이션 미추가**: `gap_up_runners`는 기존 `FundSignal.signal_type`(String) 값으로 표현. 신규 컬럼/테이블/migration 파일을 생성하지 않는다. `squeeze_score`는 DB 영속화하지 않는다.
- **denormalized P&L 컬럼 미추가**: `SurgeTrade`에 profit/return 컬럼을 추가하지 않는다(파생 계산 유지).

---

## 구현 노트 (Implementation Notes)

> 완료일: 2026-06-17 | 커밋: `0565474` | 브랜치: `feature/SPEC-AI-051`

### 실제 구현 vs. 계획 비교

| 항목 | 계획 | 실제 | 비고 |
|---|---|---|---|
| squeeze_score 필드 | dataclass 추가 | 완료 | 기본값 0.0, DB 비영속화 |
| calculate_bollinger_bandwidth_squeeze() | technical_indicators.py 신규 | 완료 | @MX:ANCHOR 태그 추가 |
| detect_bollinger_squeeze_signals() | surge_detector.py 신규 | 완료 | max_stocks_to_check=200 |
| 스케줄러 15:10 잡 | surge_bollinger_squeeze | 완료 | Mon-Fri, 15:20 잡보다 선행 |
| Tier 1/2/3 키워드 사전 | disclosure_impact_scorer.py | 완료 | _KEYWORD_TIER1~3 상수 |
| _get_keyword_tier_multiplier() | 신규 헬퍼 | 완료 | 루틴 거버넌스 면제 유지 |
| detect_gap_up_runners() | surge_detector.py 신규 | 완료 | confidence_decay=0.7 |
| 스케줄러 14:30 잡 | surge_gap_up_runners | 완료 | Mon-Fri, 당일 미체결 |
| early_entry_check() 필터 확장 | signal_type IN 확장 | 완료 | gap_up_runners 포함 |
| BollingerSqueezeConfig | surge_settings.py | 완료 | SPEC에 없던 설정 클래스 추가 (범위 내) |
| GapUpRunnersConfig | surge_settings.py | 완료 | SPEC에 없던 설정 클래스 추가 (범위 내) |
| 테스트 | test_spec_ai_051.py 신규 | 완료 | 15개 테스트 전체 통과 |

### 범위 확장 (SPEC 계획 대비 추가된 사항)

- `surge_settings.py`에 `BollingerSqueezeConfig`, `GapUpRunnersConfig` Pydantic 설정 클래스 추가 — 하드코딩 방지를 위한 자연스러운 확장
- `test_disclosure_impact_scorer.py` 기존 테스트 수정 — "합병" 키워드가 Tier 2에 포함됨에 따라 M&A 기대값 30.0 → 45.0 조정

### 미구현 항목

없음. REQ-AI051-001 ~ REQ-AI051-011 전체 구현 완료.

### TRUST 5 게이트

- **Tested**: 15/15 단위 테스트 통과, Ruff 린트 클린
- **Readable**: Python 코드 관례 준수, 한국어 코드 주석
- **Unified**: 기존 Pydantic BaseModel 패턴, 지연 임포트 패턴 일관 적용
- **Secured**: 외부 입력 없음, SQL 인젝션 없음, 기존 동작 영향 최소화
- **Trackable**: conventional commit `feat(surge)`, SPEC ID 참조
