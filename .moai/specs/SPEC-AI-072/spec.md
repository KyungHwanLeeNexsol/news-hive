---
id: SPEC-AI-072
version: 0.1.0
status: completed
created: 2026-07-03
updated: 2026-07-03
author: MoAI
priority: Medium
issue_number: 0
---

# SPEC-AI-072: near_limit_up carry-forward 데이터 소스 교정 (T-1 종가 기준)

## HISTORY

- 2026-07-03 (v0.1.0): 최초 작성. 상한가 근접 carry-forward 탐지기
  `detect_near_limit_up_carries`(`backend/app/services/surge_detector.py:2614`, SPEC-AI-023)가
  이름·docstring상 **전일(T-1) 등락률**로 상한가 근접 종목을 판별해야 함에도, 실제로는 잡 실행 시점의
  **라이브 현재 등락률**(`_fetch_price_change_sync`, `:2685`)을 읽어 `yesterday_change_pct` 필드
  (`:2704`)와 "전일 X% 상승" reasoning(`:2700`)에 오라벨로 저장하는 버그를 SPEC화. 핵심 목표:
  **change_rate 소스를 일봉 이력(`fetch_stock_price_history_sync`)에서 계산한 T-1 종가-대-종가 변화로
  교체**하여, 탐지기가 이름·docstring이 주장하는 값을 실제로 측정하게 한다.
  - **확정 진단 (2026-07-03 라이브)**: 탐지기는 장 시작(09:00 KST)이 아니라 **장중**(10:00 KST
    `surge_signal_generate_intraday` / 15:20 KST `surge_signal_generate`)에 실행된다. 따라서 라이브
    등락률로는 **이미 당일 상한가에 근접해 대부분 실현된 종목**을 "전일 급등"으로 오분류해 추격
    시그널을 낸다 — 목적(전일 모멘텀의 익일 이월 예측)과 정반대. 실측: `034940`(조아제약)이 09:58
    KST에 이미 +29.9% 라이브였고, 10:05 KST 잡이 그 값을 "전일 29.90% 상승"·`yesterday_change_pct=
    29.9`로 발행. 그 값은 당일 라이브지 T-1 종가-대-종가 변화가 아니다.
  - **사용자 확정 결정 (2026-07-03, 재논의 금지)**: 데이터 소스만 교정한다 — 라이브
    `_fetch_price_change_sync` 대신 `fetch_stock_price_history_sync`의 일봉으로 T-1 종가-대-종가
    change_rate를 계산. **T-1 레코드 선택은 배열 인덱스 가정이 아니라 `date` 매칭**으로 하고, 예상
    T-1 날짜가 이력에 없으면 그 종목만 조용히 스킵(배치 미중단).
  - **전진(forward-only) 버그 수정** — 과거 `FundSignal` 행 백필/재분류 없음. 다음 잡 실행부터 적용.

---

## 선행 SPEC / 관계 (Assumptions & Relationships)

본 SPEC은 단일 탐지기 함수의 **change_rate 데이터 소스**만 교정한다. 임계값·앙상블·스케줄·매매 로직·
평가 공식을 바꾸지 않는다. 각 항목은 2026-07-03 코드 재확인 결과다.

- **SPEC-AI-023 (near_limit_up carry-forward 탐지기) — 본체(교정 대상)**: 본 SPEC이 수정하는 함수의
  원 SPEC. `NearLimitUpConfig` 임계값(15.0/29.99), 밴드, market_cap NULL 허용, `max_stocks_to_check`
  등은 **불변**. 본 SPEC은 그 임계 비교에 넣는 **change_rate 값의 출처**만 바꾼다.
- **SPEC-AI-067 (장중 당일 거래량 실시간성) — 이력 규약의 근거(비충돌)**: 067 REQ-004/006이
  `history[0]=당일(partial)`, `history[1:]=완결 이전 거래일`이라는 규약과 "이전 행 정확성 미검증"
  가정을 확립. 본 SPEC은 그 규약을 소비(날짜 매칭의 근거)할 뿐 067의 거래량 스플라이스 로직은
  건드리지 않는다.
- **SPEC-AI-071 (급등 결과 수집 유니버스 필터링) — 무관(별개 함수)**: 071은
  `surge_actual_outcome_service.py`의 정답 수집기를 다뤘고, 본 SPEC은 신호 생성 측
  `surge_detector.py`의 탐지기를 다룬다. 두 함수는 겹치지 않으며 본 SPEC은
  `surge_actual_outcome_service.py`를 일절 건드리지 않는다.
- **SPEC-AI-041 (자동평가·자가개선 루프) — 하류(비충돌)**: 교정 후 near_limit_up_carry 시그널의
  precision이 개선되면 041 평가/가중치 루프의 입력 품질이 좋아지나, 041의 로직은 변경하지 않는다.
- **SPEC-AI-043 (예측기록 모드) — 불변**: 실매매 비활성·예측 기록 패러다임 유지. 매수 로직 diff 0.

---

## Environment (환경/전제)

- Backend: Python 3.12+, FastAPI, SQLAlchemy 2.0, APScheduler(KST 직접 지정).
- 대상 함수는 탐지기 `detect_near_limit_up_carries(db, config)` 단일 함수
  (`backend/app/services/surge_detector.py:2614`). 장중 10:00/15:20 KST 잡에서 실행.
- 재사용 인프라: `fetch_stock_price_history_sync(stock_code, pages=3)`(`naver_finance.py:808`, 동기/
  캐시), `PriceRecord`(`naver_finance.py:656-663`, `date="YYYY.MM.DD"`+OHLCV, **change_rate 필드
  없음**), `_get_prev_business_day(ref) -> date`(`surge_trading_service.py:161`).
- 이력 정렬은 최신순(newest-first). 장중 `records[0]`=당일 partial 가능성 있음 → 인덱스가 아닌 날짜
  매칭으로 T-1/T-2 선택(research §6/§7).
- **신규 테이블/마이그레이션 없음** — 기존 함수 내부의 데이터 소스 교체만. DB 스키마 diff 0.
- 운영 모드: 예측기록 전용(실매매 비활성). 자금 리스크 없음.

---

## Requirements (EARS)

### REQ-AI072-001 (P0, Event-Driven) — change_rate를 T-1 종가-대-종가로 계산

**WHEN** `detect_near_limit_up_carries`가 후보 종목의 상한가 근접 여부를 평가하면, **the system
SHALL** 그 종목의 `change_rate`를 라이브 `_fetch_price_change_sync`가 아니라
`fetch_stock_price_history_sync`가 반환한 일봉에서 계산한 **T-1 종가-대-종가 변화율**
`(close[T-1] - close[T-2]) / close[T-2] * 100` 으로 산출해야 한다.

- 이 T-1 change_rate가 상한가 근접 임계 비교, `confidence`, `reasoning`, `surge_metadata`의 단일
  입력이 되어야 한다.
- **[HARD]** `PriceRecord`에는 `change_rate` 필드가 없으므로 종가로 직접 계산한다. `close[T-2] <= 0`
  등 계산 불가 상황은 REQ-002의 per-stock 스킵으로 처리.

### REQ-AI072-002 (P0, State-Driven) — 날짜 매칭 기반 T-1 선택 + 종목별 조용한 스킵

**WHILE** 반환된 일봉 이력에서 T-1 레코드를 선택하는 동안, **the system SHALL** 배열 인덱스 위치
가정(`records[1]` 등)이 아니라 각 `PriceRecord.date`("YYYY.MM.DD")를 예상 T-1 KST 거래일과 **날짜
매칭**하여 T-1 레코드를 찾고, 그 바로 이전(더 오래된) 레코드를 T-2로 삼아 change_rate를 계산해야
한다.

- 예상 T-1 KST 거래일은 기존 `_get_prev_business_day`(`surge_trading_service.py:161`)로 산출한다
  (`surge_actual_outcome_service.py`·`surge_evaluation_service.py`의 확립된 패턴 재사용).
- **[HARD]** 예상 T-1 날짜가 이력에 없거나 T-2 레코드가 없으면(데이터 공백/휴장 불일치/`pages`
  부족/조회 실패) **그 종목만 조용히 스킵**하고 다음 후보로 진행해야 하며, 배치 전체를 중단해서는
  안 된다(코드베이스의 per-stock 실패 격리 관례 일관).

### REQ-AI072-003 (P0, Ubiquitous) — metadata·reasoning이 실제 T-1 값을 반영

**the system SHALL** `surge_metadata`의 `yesterday_change_pct` 필드와 reasoning 텍스트의
"전일 {change_rate}% 상승" 표현이 **T-1의 실제 종가-대-종가 변화**를 나타내도록 해야 한다(라이브/
현재 시점 값이 아님).

- 본 요구사항은 REQ-001을 관찰 가능한 산출물로 재진술한 것이다 — 필드명 `yesterday_change_pct`와
  "전일" 서술이 이제 값과 일치한다.
- `surge_basis=["near_limit_up_carry"]`, `surge_probability_score`(=confidence) 키 구성은 유지.

### REQ-AI072-004 (P0, State-Driven) — 임계·공식·시그널 생성 회귀 보호

**WHILE** change_rate 소스를 교체하는 동안, **the system SHALL** 그 외 판정·생성 로직을 변경 없이
유지해야 한다:

- 상한가 근접 임계 비교 `near_limit_up_min_pct(15.0) <= change_rate <= near_limit_up_max_pct(29.99)`.
- `confidence = round(change_rate / 30.0 * 0.5, 4)`.
- `signal_type="surge_candidate"`, `paper_executed=True`, `db.commit()`로의 `FundSignal` 생성.
- 오늘 이미 시그널 있는 종목 중복 방지, `max_signals_per_day` 상한, 후보 시총 필터(NULL 허용) 등
  기존 게이트.
- **[HARD]** 유일한 의도된 동작 변화는 "change_rate가 라이브 대신 T-1 종가-대-종가"라는 점과, 그로
  인해 T-1 이력이 없는 종목이 스킵된다는 점뿐이다.

### REQ-AI072-005 (P1, Unwanted Behavior) — price_at_signal의 오라벨/NULL 회귀 금지

**IF** 라이브 `_fetch_price_change_sync` 호출을 제거하여 `price_at_signal`(`:2717`)의 기존 소스가
사라지면, **THEN the system SHALL** `price_at_signal`을 계속 채우되(NULL 회귀 금지), 당일 라이브
값을 "전일/T-1" 의미로 오라벨해서는 안 된다.

- 허용안(ANALYZE에서 택1): (A) T-1 종가를 `price_at_signal`로 사용(완전 이력 기반, 라이브 호출
  제거) — 권장, 또는 (B) `price_at_signal` 전용으로만 라이브 현재가 스냅샷을 유지(change_rate/
  metadata/reasoning은 여전히 T-1 기반).
- **[HARD]** 어느 안이든 `yesterday_change_pct`·"전일 X% 상승"·임계·confidence는 T-1 종가-대-종가에서
  파생되어야 한다.

---

## Exclusions (What NOT to Build) [HARD]

1. **`NearLimitUpConfig` 임계값 변경 금지** — `near_limit_up_min_pct=15.0`,
   `near_limit_up_max_pct=29.99`(및 밴드/`max_stocks_to_check`/market_cap NULL 허용)는 불변. 본
   SPEC은 임계에 넣는 change_rate의 **출처**만 바꾼다.
2. **호출 스케줄 변경 금지** — 10:00 KST(`surge_signal_generate_intraday`)/15:20 KST
   (`surge_signal_generate`) 잡 등록을 바꾸지 않는다(예: 장전 이동 금지). 장중 실행을 유지한 채
   데이터만 교정한다.
3. **다른 탐지기 변경 금지** — `detect_near_limit_up_carries` 외 어떤 탐지기·앙상블
   (`compute_ensemble_score`)·유니버스(`build_scan_universe`)·가중치도 건드리지 않는다.
4. **과거 데이터 백필/재분류 금지** — 구(버그) 로직으로 생성된 과거 `FundSignal` 행을 재계산·
   재라벨하지 않는다. 필터는 다음 실행부터 전진 적용.
5. **`surge_actual_outcome_service.py` 무변경** — 이는 SPEC-AI-071에서 이미 다룬 정답 수집기이며 본
   버그와 무관하다. 일절 건드리지 않는다.
6. **매매·포트폴리오 로직 변경 금지** — SPEC-AI-043 예측기록 모드 유지(매수 로직 diff 0).

---

## Success Criteria

- `detect_near_limit_up_carries`가 후보의 상한가 근접 여부·confidence·reasoning·
  `yesterday_change_pct`를 모두 `fetch_stock_price_history_sync` 일봉의 **T-1 종가-대-종가**
  change_rate에서 계산하며, 라이브 `_fetch_price_change_sync` 값을 사용하지 않는다(REQ-001/003).
- T-1 레코드 선택이 배열 인덱스가 아니라 `date` 매칭으로 이뤄지고, 예상 T-1 날짜가 없는 종목은
  배치를 중단하지 않고 조용히 스킵됨이 테스트로 보장된다(REQ-002).
- 임계 비교(15.0~29.99), `confidence=change_rate/30*0.5`, `paper_executed=True`
  surge_candidate 생성이 change_rate 소스 외 무변경임이 회귀 테스트로 확인된다(REQ-004).
- `price_at_signal`이 NULL 회귀 없이 채워지고 당일 라이브 값이 "전일"로 오라벨되지 않는다(REQ-005).
- 현행(라이브 기반, 버그) 동작을 포착하는 characterization test가 존재하고(PRESERVE), 교체 후
  갱신되어 신규 동작을 확정한다(DDD ANALYZE-PRESERVE-IMPROVE).
- 신규/변경 로직 테스트 커버리지 85%+, `ruff` 무경고, 전체 급등 스위트(특히
  `test_near_limit_up_carry.py`) 회귀 없음.
- DB 스키마 diff 0(신규 테이블/마이그레이션 없음), 타 탐지기/앙상블 diff 0, 매수 로직 diff 0.

---

## Implementation Notes (2026-07-03)

manager-ddd가 DDD로 계획대로 구현. REQ-005는 오케스트레이터가 옵션 A(라이브 호출 완전 제거,
`price_at_signal`도 T-1 종가 사용)로 확정 후 진행. `_compute_t1_change_from_history()` 헬퍼로
date 매칭 기반 T-1/T-2 선정, `_fetch_price_change_sync` 호출 완전 제거. 계획 대비 범위 이탈 없음.

- 테스트: `test_near_limit_up_carry.py` 29 passed, surge 전체 618 passed, 전체 스위트
  1833 passed / 0 failed
- 커밋: `ca1ad10`
- 상태: completed

**후속 관측 필요**: 오늘(07-03) 이 버그로 생성된 과거 `034940`(조아제약) 시그널은 재분류되지 않음
(Exclusions 4 준수, 전진 적용만). `near_limit_up_carry` 탐지기의 실제 precision 개선 여부는
향후 며칠 `surge_prediction_evaluation`으로 확인 필요 — 별도 SPEC 없이 관찰 사항으로만 기록.
