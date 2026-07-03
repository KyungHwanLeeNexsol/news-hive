---
id: SPEC-AI-071
version: 0.1.0
status: completed
created: 2026-07-03
updated: 2026-07-03
author: MoAI
priority: Medium
issue_number: 0
---

# SPEC-AI-071: 급등 결과 수집 유니버스 필터링 (Surge Outcome Collection Universe Filtering)

## HISTORY

- 2026-07-03 (v0.1.0): 최초 작성. 급등예측 정답 수집기
  `collect_daily_surge_outcomes`(`surge_actual_outcome_service.py:40`)가 Naver "상승률상위" 원본을
  종목 유형 필터 없이 긁어, 개별 종목 촉매 급등과 무관한 **레버리지/인버스 2X ETN(지수 파생상품)**
  을 정답 모집단에 함께 집계하는 버그를 SPEC화. 핵심 목표: **`SurgeActualOutcome` upsert 및
  `was_surge` 카운트를 앱 `stocks` 테이블에 존재하는 종목으로 한정**하여, 탐지기가 구조적으로 잡을
  수 없는 종목(ETN·미추적 기업)이 recall/precision 분모를 부풀리지 못하게 한다.
  - **확정 진단 (2026-07-03 라이브 쿼리)**:
    - top-mover 약 205개 중 약 74개가 `stocks` 부재. `change_rate >= 10%` 37개 중 **11개(약 30%)** 가
      코드 대역 500000-599999/700000-799999의 인버스-레버리지 2X ETN(예: `520099`=미래에셋 인버스
      2X 반도체 ETN, `700018`=하나 인버스 2X 코스닥150 선물 ETN). 이들은 KOSDAQ150 선물 지수 **하락**
      으로 급등 — 개별 종목 촉매와 인과 방향이 기계적으로 반대.
    - 이 ETN들은 `sector_id`/재무/공시/뉴스가 없어 `build_scan_universe`(오직 `stocks`에서 구성)의
      후보가 될 수 없음 → **영구 false negative**. 나머지 부재 코드 일부(`900300`/`153890`/`477850`)는
      정상이나 현재 미추적 기업 — 역시 후보였던 적이 없어 동일 논리로 제외 대상.
  - **사용자 확정 결정 (2026-07-03, 재논의 금지)**: 정규식/코드 대역 ETN 휴리스틱이 아니라 **`stocks`
    테이블 교집합**으로 필터. 이유: (a) 나머지 급등 파이프라인이 이미 의존하는 "추적 가능 주식" 권위
    신호 재사용(`stocks` = 탐지기 후보 유니버스), (b) 미추적 실제 기업까지 동일 논리로 자연 제외,
    (c) T-1 예측 보완(`:72-101`)은 이미 `stocks` JOIN 소싱이라 무영향.
  - **전진(forward-only) 데이터 품질 수정** — 과거 행 백필/재계산 없음, ETN을 `stocks`에 추가하지
    않음. 다음 `collect_daily_surge_outcomes` 실행부터 적용.

---

## 선행 SPEC / 관계 (Assumptions & Relationships)

본 SPEC은 정답 수집기 한 함수의 **입력 유니버스 필터링**만 다룬다. 신호 생성·탐지기·매매 로직·
평가 공식을 바꾸지 않는다. 각 항목은 2026-07-03 코드 재확인 결과다.

- **SPEC-AI-041 (자동평가·자가개선 루프) — 정답 품질 개선(비충돌)**: `collect_daily_surge_outcomes`가
  채우는 `SurgeActualOutcome`는 041 평가 루프의 정답 분모다. 본 SPEC은 그 분모에서 탐지 불가 종목을
  제거해 recall/precision의 의미를 바로잡을 뿐, 041의 가중치/임계값 자동조정 로직은 건드리지 않는다.
- **SPEC-AI-043 (예측기록 모드) — 불변**: 실매매 비활성·예측 기록 패러다임 유지. 본 SPEC은 정답
  수집 필터만 다루므로 자금·매수 로직과 무관(매수 로직 diff 0).
- **SPEC-AI-065 (유니버스 확장 + build_scan_universe) — 불변**: 탐지기 후보 유니버스는 `stocks`에서
  구성된다는 사실이 본 필터의 근거(교집합 기준). 065의 유니버스 구성 코드는 변경하지 않는다.
- **SPEC-AI-061 (surge_actual_outcome.stock_name 보정) — 인접(비충돌)**: 061이 다룬 종목명
  fallback 경고(`stock_name == stock_code`, `:172-179`)는 본 필터 이후 사실상 0으로 수렴한다(부수
  효과). 061의 backfill 도구/COALESCE upsert 로직은 변경하지 않는다.
- **SPEC-AI-068 (평가지표 재정의 — scannable/Coverage) — 상보(별개 계층)**: 068은 스캔 유니버스
  기준의 Scannable Recall/Coverage 지표를 신설하는 측정 계층이고, 본 SPEC은 그 이전 단계인 정답
  **원천 데이터**에서 탐지 불가 종목을 제거한다. 두 작업은 목적이 겹치지 않으며 상호 재작성하지 않는다.

---

## Environment (환경/전제)

- Backend: Python 3.12+, FastAPI, SQLAlchemy 2.0, APScheduler(KST 직접 지정).
- DB: PostgreSQL 16. `SurgeActualOutcome` 복합 PK `(trading_date, stock_code)`, PostgreSQL
  `on_conflict_do_update` upsert(`:181-206`). `stocks` 테이블은 `Stock.stock_code`(String) 보유.
- 대상 함수는 정답 수집기 `collect_daily_surge_outcomes(db, trading_date)` 단일 함수.
  `fetch_top_movers_codes`는 코드만 반환(등락률 없음)하므로 코드별 `fetch_current_price_with_change`
  2단계 조회 구조는 유지한다.
- **신규 테이블/마이그레이션 없음** — 기존 함수의 필터링 변경만. DB 스키마 diff 0.
- 운영 모드: 예측기록 전용(실매매 비활성). 자금 리스크 없음.

---

## Requirements (EARS)

### REQ-AI071-001 (P0, Event-Driven) — `stocks` 존재 종목으로 정답 upsert 필터링

**WHEN** `collect_daily_surge_outcomes`가 실행되어 top-movers 코드와 T-1 예측 보완 코드가 결합된
`code_to_market` 집합이 구성되면, **the system SHALL** 가격 조회/upsert 루프에 진입하기 이전에 그
코드 집합을 앱 `stocks` 테이블에 존재하는 `stock_code`와 교집합하고, `stocks`에 없는 코드는
`SurgeActualOutcome` upsert 대상과 `was_surge` 카운트에서 모두 제외해야 한다.

- 필터 지점: 결합 `code_to_market` 구성 완료 직후(`:101` 이후), 가격 조회(`:108`) 이전.
- 필터 기준: `SELECT stock_code FROM stocks WHERE stock_code IN (<결합 코드 집합>)` 결과와의 교집합.
  기존 `Stock.stock_code.in_(...)` 조회 패턴(`:152-157`) 재사용 가능.
- **[HARD]** 필터는 upsert 대상 집합만 축소한다 — 10% 급등 분류식(`was_surge = change_rate >= 10.0`,
  `:137`)·upsert 스키마·복합 PL 충돌 처리는 변경하지 않는다.

### REQ-AI071-002 (P0, State-Driven) — T-1 예측 보완 로직 회귀 보호

**WHILE** T-1 `surge_candidate` 예측 종목이 Naver top-100 밖에 있는 상태이더라도, **the system
SHALL** 그 종목을 계속 결과 수집에 포함해야 한다.

- T-1 예측 보완 로직(`:72-101`, `Stock`↔`FundSignal` JOIN)은 **변경 없이 유지**한다.
- 보완 종목은 이미 `stocks`와의 JOIN으로 소싱되므로 REQ-001의 교집합 필터가 이들을 제외하지 않아야
  한다(보완 종목 ⊆ `stocks`가 불변식).
- **[HARD]** 이 요구사항은 "필터 도입으로 인해 예측 종목이 정답 수집에서 누락되지 않는다"는 회귀
  가드다 — top-100 밖 예측 종목 누락 시 평가에서 TP 계산이 영구 왜곡되기 때문.

### REQ-AI071-003 (P0, Unwanted Behavior) — 탐지 불가 종목의 정답 유입 금지

**IF** 결합 코드 집합에 앱 `stocks` 테이블에 없는 코드(레버리지/인버스 ETN·ETF·미추적 기업 등)가
포함되면, **THEN the system SHALL NOT** 그 코드를 `SurgeActualOutcome`에 영속화하거나 `was_surge`
급등 카운트에 반영해서는 안 된다.

- 근거: 이런 코드는 `build_scan_universe`(오직 `stocks`에서 구성)의 후보가 될 수 없어 어떤 탐지기로도
  `surge_candidate`가 되지 못한다 → 정답 모집단에 남으면 구조적 false negative로 recall/precision을
  왜곡한다.
- **[HARD]** 종목 유형 판별은 코드 대역/정규식 휴리스틱이 아니라 오직 `stocks` 존재 여부로 한다.

### REQ-AI071-004 (P1, Event-Driven) — 제외 종목 수 관측 로깅

**WHEN** REQ-001의 교집합 필터가 코드를 제외하면, **the system SHALL** 제외된 코드 수(미추적
종목 수)를 로그로 남겨 운영자가 필터 영향 규모를 관측할 수 있게 해야 한다.

- 기존 수집 로그(`:103-106`, `:210-213`) 관례와 일관된 형식.
- 제외 수가 비정상적으로 크면(예: 대부분이 필터됨) 유니버스 커버리지 문제 신호일 수 있으므로 관측
  대상이 된다 — 단, 본 SPEC은 로깅까지만 하고 알림/자동 조치는 범위 밖.

---

## Exclusions (What NOT to Build) [HARD]

1. **과거 데이터 백필/재계산 금지** — 과거 날짜의 `SurgeActualOutcome`·`surge_prediction_evaluation`
   행을 재수집·재계산하지 않는다. 필터는 다음 실행부터 전진 적용.
2. **`stocks`에 ETN/ETF 추가 금지** — ETN의 가격 동인은 지수/선물 역학이지 기업 촉매가 아니므로 본
   시스템의 탐지기 아키텍처에 맞지 않는다. ETN을 예측 대상으로 만들지 않는다.
3. **코드 대역/정규식 ETN 휴리스틱 금지** — 종목 유형 판별은 오직 `stocks` 존재 여부로 한다(권위 신호
   재사용). 500000/700000 대역 하드코딩 등 취약한 휴리스틱을 도입하지 않는다.
4. **신호 생성/탐지기 경로 무변경** — `build_scan_universe`, `gather_surge_candidates`,
   `compute_ensemble_score`, 개별 탐지기 로직은 불변.
5. **T-1 예측 보완 JOIN 로직 무변경** — `:72-101`은 REQ-002의 회귀 가드로 **보존만** 하며 재작성하지
   않는다.
6. **급등 분류·평가 공식 무변경** — `was_surge = change_rate >= 10.0` 임계, precision/recall 계산식
   (`surge_evaluation_service.py`)은 변경하지 않는다. 본 SPEC은 그 계산의 **입력 모집단**만 정제한다.
7. **실매매·포트폴리오 로직 변경 금지** — SPEC-AI-043 예측기록 모드 유지(매수 로직 diff 0).

---

## Success Criteria

- `collect_daily_surge_outcomes`가 결합 코드 집합을 `stocks` 존재 종목으로 교집합한 뒤에만 가격 조회/
  upsert를 수행하며, `stocks` 부재 코드는 `SurgeActualOutcome`과 `was_surge` 카운트에서 제외된다(REQ-001/003).
- T-1 예측 보완 로직이 변경 없이 동작하고, top-100 밖 예측 종목이 정답 수집에 계속 포함됨이 테스트로
  보장된다(REQ-002).
- 제외된 미추적 종목 수가 로그로 관측 가능하다(REQ-004).
- 현행 동작을 포착하는 characterization test가 존재하고(PRESERVE), 필터 도입 후 갱신되어 신규 동작을
  확정한다(DDD ANALYZE-PRESERVE-IMPROVE).
- 신규/변경 로직 테스트 커버리지 85%+, `ruff` 무경고, 전체 급등 스위트 회귀 없음.
- DB 스키마 diff 0(신규 테이블/마이그레이션 없음), 신호 생성 경로 diff 0, 매수 로직 diff 0.

---

## Implementation Notes (2026-07-03)

manager-ddd가 DDD(ANALYZE-PRESERVE-IMPROVE)로 계획대로 구현. `collect_daily_surge_outcomes()`에
`_fetch_tracked_stock_codes()` 헬퍼 추가 후 `stocks` 교집합 필터를 가격 조회 이전에 삽입, 제외 종목
수 로깅(REQ-004) 포함. DB 조회 실패 시 fail-open(미필터 진행) 확인 완료. 계획 대비 범위 이탈 없음
(과거 백필 없음, ETN을 `stocks`에 추가하지 않음, 코드 대역 휴리스틱 미사용 — 모두 Exclusions 준수).

- 테스트: `test_surge_actual_outcome_service.py` 14 passed, surge 전체 618 passed, 전체 스위트
  1822 passed / 0 failed
- 커밋: `03ff8dd`
- 상태: completed
