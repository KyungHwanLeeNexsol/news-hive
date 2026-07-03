# SPEC-AI-071 Research — 급등 결과 수집 유니버스 필터링

조사 완료일: 2026-07-03. 본 문서는 이미 확정된 진단을 구조화한 것으로, 재탐색을 목적으로 하지 않는다.
라인 번호는 2026-07-03 기준 `backend/app/services/surge_actual_outcome_service.py` 재확인 결과다.

---

## 1. 문제 요약

급등예측 평가 시스템(SPEC-AI-041)의 **정답(ground truth) 수집기**가 Naver Finance "상승률상위"
원본 페이지를 필터 없이 긁어, 개별 종목 촉매(뉴스/공시/거래량/테마)로 급등한 종목과 **성격이
전혀 다른 지수 파생상품(레버리지/인버스 2X ETN)** 을 정답 모집단에 함께 집계한다. 이 ETN들은
탐지기 유니버스에 들어올 수 없는 **구조적·영구적 false negative** 이므로, `actual_surge_count`를
인위적으로 부풀리고 보고 recall/precision을 왜곡한다.

---

## 2. 코드 위치 / 함수 / 라인

- **대상 함수**: `collect_daily_surge_outcomes(db, trading_date)` —
  `backend/app/services/surge_actual_outcome_service.py:40`.
- **1단계, top-movers 스크레이프 (필터 없음)**: KOSPI/KOSDAQ 각 상위 100개 코드를
  `fetch_top_movers_codes()`(`naver_finance.py`, 코드만 반환)로 수집 → `code_to_market` 구성
  (`:57-70`). **여기에 종목 유형(instrument-type) 필터가 전혀 없다.**
- **2단계, T-1 예측 보완**: T-1 `surge_candidate` 예측 종목을 보완 (`:72-101`). 이 로직은
  코드를 항상 앱의 `stocks` 테이블에서 JOIN으로 소싱하므로(`Stock`↔`FundSignal` 조인 `:81-91`)
  **추적 불가 종목을 새로 유입시키지 않는다.**
- **3단계, 가격 조회**: 결합 코드 집합 전체에 대해 `fetch_current_price_with_change()`로
  `change_rate` 조회 (`:108-117`).
- **4단계, 급등 분류 & upsert**: `was_surge = change_rate >= 10.0` (`:137`) →
  `SurgeActualOutcome`(`backend/app/models/surge_actual_outcome.py`, 복합 PK
  `(trading_date, stock_code)`)에 upsert (`:181-206`), `surge_count` 집계 (`:209`).
- **하류 소비처**: `SurgeActualOutcome`는 `surge_evaluation_service.py`의 precision/recall 분모가
  되고, `GET /api/surge-trading/prediction-history`로 노출된다.

---

## 3. 실증 발견 (2026-07-03 라이브 쿼리)

- top-mover 코드 약 **205개** 중 약 **74개**가 앱 `stocks` 테이블에 부재.
- Naver `m.stock.naver.com/api/stock/{code}/basic`의 `stockName`으로 확인 결과, 코드 대역
  **500000-599999** 및 **700000-799999** 에 몰린 부재 코드는 2배 레버리지/인버스 ETN:
  예) `520099` = "미래에셋 인버스 2X 반도체 ETN", `700018` = "하나 인버스 2X 코스닥150 선물 ETN".
- 당일 스냅샷에서 `change_rate >= 10%` 인 37개 종목 중 **11개(약 30%)** 가 이런 인버스-레버리지
  ETN — 이들은 KOSDAQ150 선물 지수가 **하락**해서 급등한 것으로, 개별 종목 촉매 급등과는
  **인과 방향이 기계적으로 반대**다.
- 이 ETN 코드들은 `sector_id`/재무/공시/뉴스가 전혀 없어 어떤 탐지기로도 `surge_candidate`가 될
  수 없다(탐지기 유니버스는 `build_scan_universe`가 오직 `stocks`에서 구성). → **영구 false
  negative**: 잡을 수 없도록 설계된 시장 지수 파생 이동으로 시스템을 채점하고 있는 셈.
- 나머지 부재 코드 일부(`900300`, `153890`, `477850` 등)는 정상 기업이나 별개의 유니버스 커버리지
  사유로 현재 미추적 상태 — 이들 역시 후보였던 적이 없으므로 동일한 "TP가 될 수 없음" 논리로 정답
  모집단에서 제외되어야 한다.

---

## 4. 선택된 접근 (사용자 승인, 재논의 금지)

**결합 코드 집합(top-movers ∪ T-1-예측-보완)을 구성한 직후, 가격 조회/upsert 루프 이전에**
그 코드 집합을 `stocks` 테이블에 존재하는 코드와 교집합한다. 구체적으로 결합 `code_to_market`
구성 완료 지점(`:101` 직후, `:103` 로그·`:108` 가격 조회 이전)에서
`SELECT stock_code FROM stocks WHERE stock_code IN (...)` 결과와 교집합하여, `stocks`에 없는 코드는
`SurgeActualOutcome` upsert 및 `was_surge` 카운트에서 제외한다.

이미 존재하는 `Stock.stock_code.in_(...)` 조회 패턴(`:152-157`, 현재는 종목명 보완용)을 재사용해
동일한 권위 신호로 필터를 구성할 수 있다.

**정규식/코드 대역 ETN 휴리스틱보다 우수한 이유:**
1. 나머지 급등 파이프라인이 이미 의존하는 권위 있는 "추적 가능 주식인가" 신호를 재사용한다
   (`stocks` 테이블 = 탐지기 후보 유니버스와 정확히 동일).
2. 미추적-이지만-실제 기업까지 동일한 "후보였던 적 없음 → TP 불가능" 논리로 자연 제외 —
   특수 케이스 분기 불필요.
3. T-1 예측 보완(`:72-101`)은 이미 `stocks` JOIN으로 소싱되므로 새 필터의 영향을 받지 않는다.

**부수 효과(요구사항 아님)**: 필터 후 upsert되는 모든 코드가 `stocks`에 존재하므로, 종목명 fallback
경고(`stock_name == stock_code`, `:172-179`)가 사실상 0으로 수렴한다.

---

## 5. 범위 밖 (사용자 명시 결정)

- 과거 날짜의 `SurgeActualOutcome`/`surge_prediction_evaluation` 행 백필·재계산 **없음**.
- ETN/ETF를 `stocks`에 추가하거나 예측 시도 **없음** — ETN의 가격 동인은 지수/선물 역학이지 기업
  촉매가 아니므로 본 시스템의 탐지기 아키텍처에 맞지 않는다.
- 본 SPEC은 **다음 `collect_daily_surge_outcomes` 실행부터 적용되는 전진(forward-only) 데이터
  품질 수정**이다.

---

## 6. 구현 방법론 (DDD: ANALYZE-PRESERVE-IMPROVE)

`quality.yaml` `development_mode: ddd` 이므로:
1. **ANALYZE** — 현행 `collect_daily_surge_outcomes` 동작·의존성 매핑(위 §2 완료).
2. **PRESERVE** — 필터 도입 전 현행 동작을 포착하는 **characterization test** 작성(top-movers
   전체가 upsert되고 `stocks` 부재 코드도 포함되던 현재 동작 스냅샷).
3. **IMPROVE** — 결합 코드 집합에 `stocks` 교집합 필터를 최소 변경으로 삽입, characterization
   test 갱신으로 신규 필터 동작 확정. T-1 보완·10% 분류·upsert 스키마는 불변.
