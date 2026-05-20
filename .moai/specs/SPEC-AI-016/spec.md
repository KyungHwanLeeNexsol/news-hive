---
id: SPEC-AI-016
version: 1.0.0
status: completed
created: 2026-05-20
updated: 2026-05-20
author: MoAI
priority: High
issue_number: 0
title: 급등 탐지 정밀도 강화 (Surge Detection Precision Enhancement)
tags: [surge-detection, precision, sector-guard, observability, price-stability]
dependencies: [SPEC-AI-013, SPEC-AI-014]
---

# SPEC-AI-016: 급등 탐지 정밀도 강화

## HISTORY

- 2026-05-20 (v1.0.0): 초기 SPEC 작성 — 2026-05-20 운영 분석에서 발견된 거짓양성 95% 문제(80+ 후보 / 실제 상승 4종목) 해결을 위한 4대 정밀도 개선 요구사항 정의

---

## 0. 배경 및 목적 (Background)

### 0.1 배경 — 2026-05-20 운영 분석 결과

NewsHive 급등 탐지 시스템(`surge_detector.py` + `surge_trading_service.py`)은 SPEC-AI-014의 스코어링 개편 이후 **신호 발화 수**는 회복되었으나, **정밀도(precision)**가 현저히 낮은 상태로 운영되고 있다. 2026-05-20 분석 결과는 다음과 같다.

| 메트릭 | 측정치 |
|---|---|
| 당일 발화 surge_candidate 시그널 | 80+ 종목 |
| 실제 의미있게 상승한 종목 | ~4 종목 |
| 거짓양성 비율(False Positive Rate) | ~95% |
| 추정 정밀도(Precision) | ~5% |

세부 분석에서 확인된 **4가지 구조적 결함**:

1. **임계값 과도하게 낮음** — `surge_detection.yaml`의 `ensemble.min_score_for_signal: 0.20`은 사실상 모든 앙상블 결과를 통과시킨다. 운영 분석상 0.45 수준으로 상향해야 변별력이 확보된다.

2. **탐지기별 점수 분해 로그 부재** — `surge_execute_buys`가 시그널을 처리할 때 앙상블 총점만 로깅한다 (`surge_metadata`에는 저장되나 INFO 로그에는 없음). 어떤 탐지기가 얼마나 기여했는지 운영 화면(`journalctl`)에서 즉시 확인 불가 → 튜닝/디버깅 불가능.

3. **포트폴리오 단위 섹터 집중 미감지** — 2026-05-20 보유 포지션은 바이오 3종(SK바이오팜, ABL바이오, 녹십자)이었으나, 시장 주도 테마는 광통신·반도체장비였다. 현재 `max_same_sector: 2` 필터는 *동시 보유 종목 수*만 제한하고, *포트폴리오 총 평가액 대비 섹터 비중*은 검사하지 않는다. 결과적으로 한 섹터에 자본의 40% 이상이 집중되어도 진입을 허용한다.

4. **가격 조회 불안정** — 80+ 후보를 일괄 검증할 때 약 50%의 종목에서 Naver Finance 가격 조회가 실패한다 (`_get_price_with_change_sync` → naver_finance 레이트 리미트 추정). 실패 시 매수가 실행되지 않을 뿐 아니라, 무관한 "no data" 시그널이 후속 로직으로 전파된다.

### 0.2 목적

스코어링 구조(SPEC-AI-014에서 처리 완료)는 그대로 유지한 채, **신호 품질 게이트**와 **포트폴리오 안전 장치**, **운영 관측성**, **데이터 수집 안정성**을 강화하여 정밀도를 5% → 25% 이상으로 개선한다.

### 0.3 비즈니스 가치

- 거짓양성 95% → ≤ 75% 감소 (실제 매수 후보 80건 → 일별 5~10건)
- 포트폴리오 섹터 리스크 분산: 단일 섹터 손실이 자본의 40% 이하로 제한
- 운영 진단력 확보: INFO 로그만으로 시그널 발화 원인 파악 가능
- 가격 조회 실패율 50% → 10% 미만으로 감소

### 0.4 본 SPEC의 범위 (Scope Boundary)

본 SPEC은 **스코어링 구조를 변경하지 않는다**. SPEC-AI-014는 점수 산식·가중치·컨센서스 배율을 다루었고, 본 SPEC은 그 결과물(앙상블 점수)에 대한 **컷오프 강화**와 **포트폴리오/운영 보호 장치**만을 다룬다.

---

## 1. 영향 범위 (Affected Files)

| 파일 | 변경 성격 | 관련 REQ |
|---|---|---|
| `backend/app/surge_config/surge_detection.yaml` | `ensemble.min_score_for_signal: 0.20 → 0.45` 단순 값 변경 | REQ-001 |
| `backend/app/services/surge_trading_service.py` | `execute_buy_orders` 내 탐지기별 INFO 로그 추가, 섹터 비중 가드 함수 신설, 가격 배치 조회 구조 변경 | REQ-002, REQ-003, REQ-004 |
| `backend/app/services/naver_finance.py` | 배치 가격 조회 헬퍼 (`fetch_current_prices_batch`) 신설 — 배치 크기·간격 설정 가능 | REQ-004 |
| `backend/app/surge_config/surge_settings.py` | 신규 설정 키 노출 (`max_sector_portfolio_pct`, `price_batch_size`, `price_batch_delay_sec`) | REQ-003, REQ-004 |
| `backend/tests/test_surge_trading_service.py` | 4개 REQ에 대응하는 단위·통합 테스트 추가/수정 | 전체 |

---

## 2. 요구사항 (Requirements, EARS 형식)

### REQ-AI016-001 (P1, Critical): 앙상블 점수 임계값 상향

**WHEN** `surge_detector.gather_surge_candidates`가 앙상블 점수를 계산하여 `surge_candidate` 시그널을 생성할 때, 시스템은 SHALL 임계값 0.45 미만의 후보를 **반드시 제외**한다.

- **현재**: `surge_detection.yaml`의 `ensemble.min_score_for_signal: 0.20`
- **변경 후**: `ensemble.min_score_for_signal: 0.45`

**WHERE** YAML 변경은 `backend/app/surge_config/surge_detection.yaml`의 단일 값만 수정한다. 코드 로직 변경은 불필요하며 `compute_ensemble_score()` 출력 흐름은 그대로 유지된다.

**IF** 기존 테스트(`tests/test_surge_detector.py`, `tests/test_surge_trading_service.py`)에서 `min_score_for_signal` 또는 0.20을 하드코딩한 케이스가 존재하면, **THEN** 시스템은 SHALL 새로운 임계값 0.45로 일관되게 갱신한다.

**WHILE** `gather_surge_candidates` 내 즉각 공시 이벤트 우회(`_IMMEDIATE_BYPASS_THRESHOLD = 0.70`) 로직은 본 변경의 영향을 받지 않는다 (자사주 소각·합병 등 단일 이벤트는 별도 경로로 통과 유지).

**수락 기준**:
- AC-016-001-1: `surge_detection.yaml` 로드 시 `min_score_for_signal == 0.45`로 파싱됨 (단위 테스트)
- AC-016-001-2: 가중합 0.40 짜리 합성 후보 입력 시 `gather_surge_candidates` 결과 리스트에서 제외됨 (단위 테스트)
- AC-016-001-3: 가중합 0.50 짜리 합성 후보 입력 시 결과 리스트에 포함됨 (단위 테스트)
- AC-016-001-4: 즉각 공시 점수 0.90짜리 후보는 앙상블 점수가 0.45 미만이어도 우회 통과됨 (회귀 보장)

**배포 주의사항**: 본 변경은 시그널 발화 수를 즉시 크게 감소시키므로, **반드시 정규장 마감 후(KST 15:30 이후) 배포**한다. 장중 배포 시 진행 중인 매수 사이클이 중단될 수 있다.

---

### REQ-AI016-002 (P2, High): 탐지기별 점수 분해 INFO 로그

**WHEN** `surge_trading_service.execute_buy_orders`가 매수 후보 시그널을 순회하며 각 종목을 평가할 때, 시스템은 SHALL 매수 통과/스킵/실패 여부와 무관하게 **각 탐지기의 기여 점수**를 INFO 레벨로 로깅한다.

- **현재**: 매수 완료 시 `surge_execute_buys: %s(%s) 매수 완료 — 수량=%d, 단가=%s, 금액=%s, 확률=%.2f, 탐지기=%s` 형식으로 총점만 출력. 스킵/실패 케이스도 탐지기 분해 정보가 없다.
- **변경 후 로그 형식** (모든 평가 종목 대상):
  ```
  [SURGE] {ticker} {action} score={total:.3f} | theme={theme:.3f} volume={vol:.3f} disclosure={disc:.3f} immediate={imm:.3f} legacy={leg:.3f} | reason={reason}
  ```
  여기서 `action` ∈ `{executed, skipped, failed}`, `reason`은 스킵/실패 케이스의 사유(`daily_limit`, `intraday_crash`, `sector_overweight`, `price_unavailable` 등).

**WHERE** 탐지기별 점수는 `signal.surge_metadata` JSON 필드에 이미 저장되어 있으며 (`surge_candidate_to_signal_metadata()` 참고), `_parse_surge_metadata()` 헬퍼를 확장하여 6개 점수 컴포넌트(theme_cluster_score, combo_score, pattern_score, immediate_disclosure_score, legacy_score, 그리고 앙상블 총점)를 함께 반환하도록 수정한다.

**IF** `surge_metadata`가 결측 또는 파싱 실패인 시그널이 발견되면, **THEN** 시스템은 SHALL 결측 점수를 `0.000`으로 표기하고 정상 로그를 출력한다 (예외로 매수 흐름 중단 금지).

**WHILE** 본 로그는 INFO 레벨이므로 운영 환경(`journalctl -u newshive`)에서 기본 노출된다. DEBUG 로그(상세 breakdown)는 변경하지 않고 보존한다.

**수락 기준**:
- AC-016-002-1: 매수 완료 케이스 1건에 대해 `[SURGE] 005930 executed score=0.520 | theme=0.300 volume=0.150 ...` 패턴의 INFO 로그가 정확히 1회 출력됨 (단위 테스트, `caplog` 사용)
- AC-016-002-2: 섹터 집중으로 스킵된 케이스에 대해 `action=skipped reason=sector_concentration`이 포함된 분해 로그가 출력됨
- AC-016-002-3: 가격 조회 실패 케이스에 대해 `action=failed reason=price_unavailable` 분해 로그가 출력됨
- AC-016-002-4: 6개 점수 컴포넌트가 합계 0.0~1.0 범위 내에 있고, 표시 정밀도는 소수점 3자리

---

### REQ-AI016-003 (P2, High): 포트폴리오 단위 섹터 비중 가드

**WHEN** `surge_trading_service.execute_buy_orders`가 특정 종목에 대해 매수 실행 직전 단계에 도달했을 때, 시스템은 SHALL 해당 종목의 섹터가 **현재 포트폴리오 총 평가액의 `MAX_SECTOR_PORTFOLIO_PCT` (기본 0.40)을 초과**하는지 검사하고, 초과 시 매수를 스킵한다.

- **계산식**:
  ```
  sector_value      = Σ(open positions in sector) × 현재가 (현재가 조회 실패 시 entry_price 폴백)
  total_value       = portfolio.current_cash + Σ(all open positions value)
  sector_portfolio_pct = sector_value / total_value
  ```
- **판정**: `sector_portfolio_pct + (예상 매수 금액 / total_value) > MAX_SECTOR_PORTFOLIO_PCT`이면 **스킵**.

**WHERE** 신규 함수 `_compute_sector_portfolio_pct(db, sector_name) -> Decimal`을 `surge_trading_service.py`에 추가한다. 기존 `_get_open_sector_counts()`와 별도 함수로 두어 *카운트 기반* 필터(`max_same_sector`)와 *비중 기반* 필터(`MAX_SECTOR_PORTFOLIO_PCT`)를 모두 유지한다.

**IF** 현재 보유 포지션의 일부 종목에서 현재가 조회가 실패하면, **THEN** 시스템은 SHALL 해당 종목의 `entry_price × quantity`를 폴백 평가액으로 사용하여 비중 계산을 계속한다 (graceful fallback).

**WHILE** 본 가드는 `max_same_sector` 카운트 필터와 **AND 조건**으로 결합된다. 즉 어느 한 가드라도 발동하면 매수를 스킵한다. 스킵 사유는 `skip_reason="sector_overweight"`로 명시한다.

**수락 기준**:
- AC-016-003-1: 합성 포트폴리오(현금 30M, 바이오 섹터 보유 평가액 22M, 총 평가액 52M)에서 바이오 섹터 신규 매수 시도 시 (예상 매수 금액 9M, 매수 후 비중 = 31M/52M ≈ 0.596) → `skip_reason="sector_overweight"`로 스킵됨
- AC-016-003-2: 동일 포트폴리오에서 광통신(비보유) 섹터 매수 시도 시 → 정상 통과
- AC-016-003-3: 현재가 조회 실패 1종목 포함 케이스에서 폴백 평가액으로 계산 진행, 예외 발생 없음
- AC-016-003-4: 신규 로그 라인 `[SURGE] {ticker} skipped score=... reason=sector_overweight sector_pct=0.59 limit=0.40`이 INFO 출력됨
- AC-016-003-5: 기본값 `MAX_SECTOR_PORTFOLIO_PCT = 0.40`은 `surge_settings.py`에서 환경변수 또는 YAML로 오버라이드 가능

---

### REQ-AI016-004 (P3, Medium): 가격 조회 안정성 개선 (배치 + 지연)

**WHEN** `surge_trading_service` 또는 후속 검증 로직이 N개 (N ≥ 5) 종목의 현재가를 연속 조회할 때, 시스템은 SHALL 조회를 **`price_batch_size` (기본 10) 단위로 분할**하고, **각 배치 사이에 `price_batch_delay_sec` (기본 0.5초) 지연**을 삽입하여 Naver Finance 레이트 리미트를 회피한다.

- **현재**: `_get_price_with_change_sync(stock_code)`가 종목별로 동기 호출됨. 80+ 종목 일괄 검증 시 ~50% 실패율 관측.
- **변경 후 동작**:
  - `naver_finance.py`에 신규 헬퍼 `fetch_current_prices_batch(stock_codes: list[str], batch_size: int = 10, delay_sec: float = 0.5) -> dict[str, dict | None]` 추가
  - 각 배치는 비동기 `asyncio.gather()`로 동시 조회, 배치 종료 후 `await asyncio.sleep(delay_sec)`
  - 결과는 `{stock_code: {"current_price": int, "change_rate": float} | None}` 형식
- **`surge_trading_service` 통합**:
  - `execute_buy_orders` 시작 시 전체 후보의 가격을 1회 일괄 조회하여 내부 dict 캐시에 보관
  - 종목별 평가 시 캐시 조회 → 미존재/None인 경우 1회 재시도 → 최종 실패 시 `skip_reason="price_unavailable"`로 스킵

**WHERE** 설정 키는 `surge_config/surge_settings.py`에 다음과 같이 노출한다:
- `PriceQueryConfig.batch_size: int = 10`
- `PriceQueryConfig.batch_delay_sec: float = 0.5`
- `PriceQueryConfig.retry_count: int = 1`

`surge_detection.yaml`에는 다음 섹션을 추가한다:
```yaml
price_query:
  batch_size: 10
  batch_delay_sec: 0.5
  retry_count: 1
```

**IF** 재시도 후에도 가격이 조회되지 않으면, **THEN** 시스템은 SHALL 해당 종목을 매수 후보에서 제외(skip)하고, INFO 로그 `[SURGE] {ticker} failed score=... reason=price_unavailable batches={batch_idx}`를 출력한다. 예외 전파 금지.

**WHILE** 본 변경은 `check_exit_conditions()`(매도 사이클)와 `get_portfolio_stats()`(평가액 계산)에는 적용하지 않는다 (각각 후보 수가 작음). 본 SPEC 범위는 매수 사이클에 한정한다.

**수락 기준**:
- AC-016-004-1: 30개 종목 입력 시 정확히 3개 배치로 분할되고, 배치 간 `asyncio.sleep(0.5)`가 2회 호출됨 (mock 검증)
- AC-016-004-2: 배치 중 일부 종목이 None을 반환해도 다른 종목의 결과는 정상 dict로 반환됨
- AC-016-004-3: 가격 조회 1차 실패 시 재시도 1회 수행, 재시도도 실패 시 `skip_reason="price_unavailable"`로 스킵
- AC-016-004-4: 합성 테스트로 50종목 입력, 50% 실패 시뮬레이션 → 25개 통과 / 25개 `price_unavailable` 스킵 (예외 없음)
- AC-016-004-5: 모든 종목 가격 조회가 성공한 경우, 기존 동작과 동일한 매수 결과 (회귀 보장)

---

## 3. 비목표 (Non-Goals / Exclusions)

본 SPEC은 다음을 **변경하지 않는다**:

1. **신규 탐지기 추가** — 5번째 탐지기 도입(예: 외국인 매수, 기관 수급)은 본 SPEC 범위 외. 별도 SPEC 발급 필요.
2. **스코어링 산식 변경** — 가중치, 컨센서스 배율, 종목 단위 개인화는 SPEC-AI-014에서 다루었으며 본 SPEC에서는 손대지 않는다.
3. **DB 스키마 변경** — `FundSignal`, `SurgeTrade`, `SurgePortfolio` 테이블 구조 유지. 마이그레이션 없음.
4. **매도(check_exit_conditions) 로직 변경** — 손절/익절/만기 임계값(`stop_loss_pct=-0.08`, `take_profit_pct=0.15`, `max_holding_days=5`)은 그대로 유지. 가격 배치 조회는 매수 사이클에만 적용.
5. **알람/UI 변경** — 프론트엔드 시그널 표시, 알람 발송 정책은 별도 처리.
6. **장중 동작 모드 추가** — `is_buy_eligible_hours`(09:00~11:00 + 손절 복구) 및 `is_market_hours`(09:00~15:30) 가드는 변경하지 않는다.
7. **백테스트 인프라 변경** — `backtest.enabled: true`, `evaluation_horizon_days: 5` 등 백테스트 설정은 그대로 유지.

---

## 4. 성공 기준 (Success Criteria)

| 메트릭 | 현재 (2026-05-20 측정) | 목표 (구현 1주 후) |
|---|---|---|
| 일별 surge_candidate 발화 수 | 80+ | 10~25건 |
| 추정 정밀도 (실제 의미있게 상승한 비율) | ~5% | ≥ 25% |
| 가격 조회 성공률 | ~50% | ≥ 90% |
| 포트폴리오 단일 섹터 최대 비중 | 미감지 (실측 60%+ 사례 발생) | ≤ 40% |
| INFO 로그에서 탐지기별 점수 확인 가능 | 불가 | 모든 평가 종목에 대해 가능 |

---

## 5. 구현 가이드 (Implementation Notes)

### 5.1 단계별 구현 순서 (권장 우선순위)

1. **Phase A — YAML 임계값 변경** (REQ-001): 가장 단순. `surge_detection.yaml` 1줄 수정. 기존 테스트 회귀만 확인.
2. **Phase B — 가격 배치 조회 인프라** (REQ-004): `naver_finance.fetch_current_prices_batch()` 신규 함수 + `surge_trading_service` 통합. REQ-002의 `price_unavailable` 로그 사유 분리에도 필요.
3. **Phase C — 탐지기별 INFO 로그** (REQ-002): `_parse_surge_metadata` 확장, `execute_buy_orders` 내 모든 분기점에 로그 호출 삽입.
4. **Phase D — 섹터 비중 가드** (REQ-003): `_compute_sector_portfolio_pct()` 신규 함수, `execute_buy_orders` 내 `_get_open_sector_counts` 호출 직후 새 가드 추가.

### 5.2 데이터 흐름 (Data Flow)

```
[get_today_signals() — 임계값 0.45 이미 통과한 후보만]
        │
        ▼
[execute_buy_orders 시작]
   ├── 모든 후보 종목 코드 수집 (N개)
   ├── fetch_current_prices_batch(codes, batch_size=10, delay=0.5)  ← REQ-004
   └── 결과를 price_cache: dict[str, dict | None]로 보관
        │
        ▼
[각 종목 평가 루프]
   ├── 1. 일일 한도 / 동시 보유 한도 / 중복 체크 (기존)
   ├── 2. 섹터 카운트 필터 (max_same_sector, 기존)
   ├── 3. 섹터 비중 가드 (MAX_SECTOR_PORTFOLIO_PCT=0.40)  ← REQ-003 (신규)
   ├── 4. 가격 조회 from price_cache (없으면 1회 재시도)
   │      └── 재시도 실패 → skip reason="price_unavailable"   ← REQ-004
   ├── 5. 인트라데이 급락/과열 필터 (기존)
   ├── 6. 수량 계산 → 매수 트랜잭션 (기존)
   └── 7. [SURGE] INFO 로그 — 탐지기별 분해 + action + reason  ← REQ-002
```

### 5.3 호환성 및 폴백

- `min_score_for_signal: 0.45` 상향은 기존 시그널이 DB에 이미 저장되어 있는 경우 영향 없음(필터는 `gather_surge_candidates` 단계에서 적용). 다음 사이클부터 자연스럽게 반영.
- `fetch_current_prices_batch`는 신규 함수이며 기존 `_fetch_current_price_async`, `_fetch_price_with_change_async`는 변경하지 않는다 (병행 운영 가능).
- 섹터 비중 가드 도입 후에도 `max_same_sector` 카운트 가드는 유지된다 (두 가드는 AND 결합).

### 5.4 로깅 표준

본 SPEC으로 추가/변경되는 로그 라인:

| 레벨 | 패턴 | 발생 시점 |
|---|---|---|
| INFO | `[SURGE] {code} executed score={s} \| theme=... \| reason=ok` | 매수 완료 |
| INFO | `[SURGE] {code} skipped score={s} \| theme=... \| reason={r}` | 모든 스킵 케이스 (daily_limit, max_open_positions, duplicate_position, sector_concentration, sector_overweight, insufficient_cash, intraday_crash, intraday_overheat, quantity_zero) |
| INFO | `[SURGE] {code} failed score={s} \| theme=... \| reason=price_unavailable batches={n}` | 가격 조회 재시도 후 최종 실패 |
| INFO | `[SURGE] {code} skipped reason=sector_overweight sector_pct={p:.2f} limit=0.40` | 섹터 비중 가드 발동 (별도 라인) |

### 5.5 @MX 태그 추가 대상 (구현 단계 참고)

본 SPEC 구현 시 다음 함수들이 신규 ANCHOR/NOTE 후보가 된다 (Run 단계에서 처리):

- `naver_finance.fetch_current_prices_batch` → `# @MX:ANCHOR: 배치 가격 조회 — 매수 사이클 진입점` (fan_in ≥ 1, 향후 매도/평가 사이클 확장 시 fan_in 증가 예상)
- `surge_trading_service._compute_sector_portfolio_pct` → `# @MX:NOTE: 섹터 비중 가드 핵심 계산. 폴백: 현재가 조회 실패 시 entry_price 사용`
- `surge_trading_service.execute_buy_orders` 내 신규 로그 호출부 → `# @MX:NOTE: [AUTO] SPEC-AI-016 탐지기별 분해 로그`

### 5.6 배포 정책 (Deployment Policy)

[HARD] 본 SPEC의 모든 변경사항은 다음 순서로만 배포한다:

1. **개발/스테이징 환경 검증** — 합성 데이터 + 운영 DB 복제본으로 24시간 관측
2. **운영 배포 시점** — 반드시 KST 평일 **15:30 이후** (정규장 마감 후). 휴장일 배포 권장.
3. **배포 직후 모니터링** — 다음 거래일 09:00~10:30 사이 첫 1시간 동안 매수 사이클 로그를 실시간 관찰 (`journalctl -u newshive -f`)
4. **롤백 기준** — 배포 다음 거래일에 매수 후보가 0건이거나, 가격 조회 성공률이 70% 미만으로 떨어지면 즉시 `surge_detection.yaml`을 직전 커밋으로 되돌리고 재계획

---

## 6. 테스트 수락 기준 (Test Acceptance Criteria)

### 6.1 단위 테스트 (Unit Tests)

| 테스트 ID | 대상 REQ | 검증 항목 |
|---|---|---|
| T-016-001 | REQ-001 | YAML 로드 후 `config.ensemble.min_score_for_signal == 0.45` |
| T-016-002 | REQ-001 | 합성 후보(weighted_sum=0.40) → `gather_surge_candidates` 결과 미포함 |
| T-016-003 | REQ-001 | 합성 후보(weighted_sum=0.50) → 결과 포함 |
| T-016-004 | REQ-001 | 즉각 공시 점수 0.90 후보는 앙상블 0.30이어도 우회 통과 (회귀) |
| T-016-005 | REQ-002 | 매수 완료 시 `[SURGE] {code} executed score=... theme=...` 로그 1회 (caplog) |
| T-016-006 | REQ-002 | 섹터 집중 스킵 시 `reason=sector_concentration` 분해 로그 |
| T-016-007 | REQ-002 | 가격 실패 시 `action=failed reason=price_unavailable` 분해 로그 |
| T-016-008 | REQ-002 | `surge_metadata` 결측 시그널에 대해 모든 점수 `0.000`으로 표기, 예외 없음 |
| T-016-009 | REQ-003 | 합성 포트폴리오(바이오 비중 0.42) 신규 바이오 매수 시도 → `sector_overweight` 스킵 |
| T-016-010 | REQ-003 | 동일 포트폴리오에서 비보유 섹터(광통신) 매수 시도 → 통과 |
| T-016-011 | REQ-003 | 일부 종목 현재가 실패 → entry_price 폴백, 비중 계산 정상 완료 |
| T-016-012 | REQ-003 | `MAX_SECTOR_PORTFOLIO_PCT` 환경변수 오버라이드 동작 |
| T-016-013 | REQ-004 | 30종목 입력 시 3배치 분할, `asyncio.sleep(0.5)` 2회 호출 (mock) |
| T-016-014 | REQ-004 | 배치 내 일부 종목 None 반환 시 다른 종목 결과 정상 |
| T-016-015 | REQ-004 | 1차 실패 → 재시도 1회 → 재시도도 실패 시 `price_unavailable` 스킵 |
| T-016-016 | REQ-004 | 50종목 50% 실패 시뮬레이션 → 25개 통과 / 25개 스킵, 예외 없음 |

### 6.2 통합 테스트 (Integration Tests)

| 테스트 ID | 시나리오 |
|---|---|
| I-016-001 | 합성 80개 후보 + Naver mock(50% 실패) → 매수 사이클 종료 후 `executed + skipped + failed == 80`, 예외 0건 |
| I-016-002 | 바이오 3종 보유 포트폴리오(비중 0.45) + 신규 바이오 후보 5건 → 모두 `sector_overweight` 스킵, 비바이오 후보는 정상 평가 |
| I-016-003 | 정상 거래일 시뮬레이션(모든 후보 점수 0.30) → `gather_surge_candidates` 결과 0건 (임계값 0.45 동작 확인) |
| I-016-004 | 정상 거래일 시뮬레이션(후보 50건, 점수 분포 0.20~0.70) → 통과 후보 ≤ 5건, INFO 로그에 모든 평가 종목의 탐지기별 분해 출현 |

### 6.3 회귀 테스트 (Regression)

- 기존 `tests/test_surge_detector.py`의 모든 케이스 통과 (스코어링 로직 미변경)
- 기존 `tests/test_surge_trading_service.py`의 매도 사이클 테스트 통과 (`check_exit_conditions` 미변경)
- SPEC-AI-014의 컨센서스 배율 테스트 통과 (`active_count >= 2 → 1.15`, `active_count >= 3 → 1.30`)
- `is_market_hours`, `is_buy_eligible_hours` 동작 변화 없음

### 6.4 Done 정의 (Definition of Done)

- [ ] 4개 REQ 전부 구현 완료
- [ ] 단위 테스트 16종 + 통합 테스트 4종 전부 통과
- [ ] `cd backend && uv run pytest tests/ --tb=short -q -m "not slow"` 100% 통과
- [ ] `cd backend && uv run ruff check . && uv run mypy app/` 오류 0
- [ ] 개발 환경에서 24시간 합성 데이터 관측 완료
- [ ] 운영 환경 정규장 마감 후 배포 완료 + 다음 거래일 첫 1시간 실시간 모니터링 완료
- [ ] 운영 환경 1주 관찰: 일별 매수 후보 5~25건 / 가격 성공률 ≥ 90% / 단일 섹터 비중 ≤ 40% 확인
- [ ] CHANGELOG 업데이트
- [ ] `@MX:NOTE` / `@MX:ANCHOR` 태그 추가 (5.5 절 참조)

---

## 7. 위험 및 완화 (Risks & Mitigation)

| 위험 | 영향도 | 완화 방안 |
|---|---|---|
| 임계값 0.45 상향이 너무 빡빡하여 매수 후보 0건 발생 | 중 | 운영 첫 거래일 모니터링 → 0건 지속 시 0.40 또는 0.35로 단계적 완화 |
| 가격 배치 조회 자체가 Naver 레이트 리미트에 걸려 실패율 증가 | 중 | `batch_size=10`, `delay=0.5s`를 시작 값으로 운영 후 조정. 실패율 30% 초과 시 배치 크기를 5로 축소 |
| 섹터 비중 계산 시 모든 보유 종목의 현재가 조회로 지연 누적 | 낮 | 배치 조회 결과를 재사용 (단일 사이클 내 캐시) |
| `[SURGE]` INFO 로그가 너무 많아 journal disk 사용량 급증 | 낮 | 일별 평가 종목 수가 25건으로 감소(임계값 상향 효과) 후 부담 미미. 필요 시 log rotation 정책 점검 |
| 섹터 비중 가드가 시장 주도 섹터 진입을 과도 차단 | 중 | `MAX_SECTOR_PORTFOLIO_PCT` 환경변수로 운영 중 조정 가능 (기본 0.40 → 필요시 0.50) |
| 가격 배치 함수의 asyncio 사용이 기존 동기 컨텍스트와 충돌 | 중 | `asyncio.run()` 1회 호출로 캡슐화 + 기존 패턴(`_get_current_price_sync`)과 동일한 RuntimeError 가드 |

---

## 8. 참고 문서 (References)

- **SPEC-AI-012**: 급등예측 시그널 시스템 — 4개 탐지기 ensemble 인프라
- **SPEC-AI-013**: 급등예측 모의투자 포트폴리오 — 매수/매도 사이클 인프라 (본 SPEC 직접 의존)
- **SPEC-AI-014**: 급등 시그널 스코어링 고도화 — 컨센서스 배율, 종목 단위 개인화 (스코어링 구조 미변경)
- **SPEC-AI-015**: 시장 국면 적응 전략 (관련 컨텍스트)
- `backend/app/surge_config/surge_detection.yaml`: ensemble 가중치 및 임계값 설정
- `backend/app/services/surge_detector.py`: `gather_surge_candidates`, `compute_ensemble_score`
- `backend/app/services/surge_trading_service.py`: `execute_buy_orders`, `_get_open_sector_counts`, `_get_price_with_change_sync`
- `backend/app/services/naver_finance.py`: `fetch_current_price`, `fetch_current_price_with_change` (배치 헬퍼 신규 추가 대상)

---

**SPEC-AI-016 작성 완료** — Run 단계 진입 전 본 SPEC 검토 및 승인이 필요합니다. 배포는 반드시 정규장 마감 후 진행 (5.6 절 참조).
