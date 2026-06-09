# SPEC-AI-042 인수 기준 (Acceptance Criteria)

Given-When-Then 형식. 모든 시나리오는 관찰 가능한 증거(저장된 시그널, 매수 실행 결과 dict, 스킵 카운트)로 검증한다.

---

## Scenario 1: 공시 기반 갭업 포착 happy path (15:30 공시 → 17:00 스캔 → 익일 9:05 소갭 진입)

- **Given** T일 15:35 KST에 종목 A(자사주 소각 공시)가 DART에 접수되고, `detect_immediate_disclosure_signal`이 종목 A를 후보로 반환하는 상태
- **And** 종목 A에 동일 disclosure_id 기반 preday_disclosure 시그널이 아직 없는 상태
- **When** T일 17:00 KST `surge_preday_scan` 잡이 실행되면
- **Then** 종목 A에 대해 `signal_type="preday_disclosure"`, `disclosure_id`=해당 공시 id, `surge_metadata.source="preday_scan"`인 FundSignal이 1건 저장된다
- **And** `post_market_scan` 반환값(신규 저장 수)이 1 이상이다
- **When** 익일(T+1) 09:05 KST `surge_preday_early_entry` 잡이 실행되고, 종목 A의 `change_rate`가 +3.0%(0 ≤ gap < 5%)인 상태에서
- **Then** 종목 A가 조기 매수 대상으로 채택되어 `execute_buy_orders` 경로로 진입한다
- **And** `early_entry_check` 반환 dict의 `entered >= 1`이고, `execute_result.executed >= 1`이다

## Scenario 2: 갭 ≥ 5% skip (이미 급등한 종목 걸러내기 → gap_pullback 위임)

- **Given** 종목 B에 유효한 preday_disclosure 시그널이 존재하는 상태
- **And** `gap_entry_threshold = 0.05`(surge_detection.yaml 기본값)
- **When** 09:05 KST `surge_preday_early_entry` 잡이 실행되고 종목 B의 `change_rate`가 +7.2%(≥ 5%)인 상태에서
- **Then** 종목 B는 조기 진입에서 제외된다(`execute_buy_orders`로 전달되지 않음)
- **And** `early_entry_check` 반환 dict의 `skipped_gapup`이 1 증가한다
- **And** 종목 B는 기존 `gap_pullback_check`(10:00~11:30) 처리에 위임된다(별도 차단 없음)

## Scenario 3: 갭다운 skip (공시 재료가 음성인 경우)

- **Given** 종목 C에 유효한 preday_disclosure 시그널이 존재하는 상태
- **When** 09:05 KST 잡이 실행되고 종목 C의 `change_rate`가 -2.1%(< 0%)인 상태에서
- **Then** 종목 C는 조기 진입에서 제외된다(패턴 파괴로 판단)
- **And** `early_entry_check` 반환 dict의 `skipped_gapdown`이 1 증가한다
- **And** `execute_buy_orders`는 종목 C에 대해 매수를 시도하지 않는다

## Scenario 4: 중복 시그널 방지 (동일 공시 기반 시그널 2번 생성 안 됨)

- **Given** 종목 D의 공시(disclosure_id=999)가 T일 17:00 스캔에서 이미 preday_disclosure 시그널로 저장된 상태
- **When** 익일 08:00 KST `surge_preopen_refresh` 잡이 동일 공시(disclosure_id=999)를 재스캔하면
- **Then** 종목 D에 대해 신규 FundSignal이 생성되지 않는다(`_save_preday_signal`이 False 반환)
- **And** 종목 D의 disclosure_id=999 기반 preday_disclosure 시그널은 DB에 정확히 1건만 존재한다
- **And** 중복 판정은 `FundSignal.disclosure_id` 컬럼 우선, 미설정 시 `surge_metadata` JSON의 disclosure_id로 fallback한다

## Scenario 5: 기존 10:00 인트라데이 플로우 무결성 (변경 없음 검증)

- **Given** 본 SPEC 적용 전 10:00 `surge_signal_generate_intraday`와 15:20 `surge_signal_generate` 잡이 생성하는 surge_candidate 시그널 집합
- **When** SPEC-AI-042 구현 후 동일 입력 데이터로 두 잡을 실행하면
- **Then** 생성되는 surge_candidate 시그널의 수·내용이 적용 전과 동일하다
- **And** `get_today_signals()`가 반환하는 surge_candidate 시그널의 signal_cutoff 동작(직전 영업일 15:00 KST)이 변경되지 않는다
- **And** preday_disclosure 시그널은 surge_candidate 평가·생성 흐름에 혼입되지 않는다

## Scenario 6: 장전 워치리스트 합집합 (REQ-042-004)

- **Given** `get_today_signals()`가 반환하는 활성 surge_candidate 시그널에 종목 E가 있고, preday_disclosure 시그널에 종목 F가 있는 상태(E ≠ F)
- **When** `preopen_watchlist_refresh` 후 watch_list가 산출되면
- **Then** watch_list는 {E, F}를 stock_id 기준 중복 제거하여 모두 포함한다
- **And** 동일 종목이 양쪽에 모두 존재하면 1건으로 처리된다

## Scenario 7: 거래일 가드 (REQ-042-011)

- **Given** 실행일이 토요일 또는 `KRX_EXTRA_HOLIDAYS`에 포함된 휴장일인 상태
- **When** `surge_preday_scan` / `surge_preopen_refresh` / `surge_preday_early_entry` 중 어느 잡이라도 트리거되면
- **Then** 해당 잡은 즉시 스킵되고 어떤 시그널 생성·매수도 발생하지 않는다

## Scenario 8: 갭 조회 실패 격리 (REQ-042-012)

- **Given** preday_disclosure 시그널 보유 종목 3개(G, H, I) 중 종목 H의 `fetch_current_price_with_change` 호출이 예외/None을 반환하는 상태
- **When** 09:05 `early_entry_check`가 실행되면
- **Then** 종목 H는 건너뛰고 종목 G, I의 갭 필터·진입 처리는 정상 수행된다
- **And** 잡 전체가 중단되지 않는다(전체 실패 금지)

## Scenario 9: 09:05 잡 id 충돌 회피 (REQ-042-010)

- **Given** 기존 `fund_morning_execute` 잡(id `fund_morning_execute`, 09:05 KST)이 등록된 상태
- **When** `start_scheduler()`가 `surge_preday_early_entry`(id `surge_preday_early_entry`, 09:05 KST)를 추가 등록하면
- **Then** 두 잡은 서로 다른 id로 독립 등록되며 `replace_existing`으로 서로를 덮어쓰지 않는다
- **And** 09:05에 두 잡이 모두 실행되어도 `execute_buy_orders`의 현금·`max_open_positions` 한도 게이트가 초과 매수를 방지한다

---

## Quality Gate Criteria

- 신규 단위 테스트(`test_preday_signal_service.py`, `test_early_entry_check.py`) 8건 이상 통과.
- `cd backend && uv run ruff check .` 경고 0건, `uv run mypy app/` 신규 코드 타입 오류 0건.
- 기존 surge 관련 테스트 회귀 0건(SC-5 무결성).
- `from app.services.preday_signal_service import ...` 임포트 성공.

## Definition of Done

- [ ] REQ-042-001~013 전 요구사항 구현 및 테스트로 커버.
- [ ] `preday_signal_service.py` 3개 공개 함수(post_market_scan / preopen_watchlist_refresh / early_entry_check) 구현.
- [ ] `get_today_signals()`가 preday_disclosure(당일 08:00 cutoff) 포함하도록 수정, surge_candidate 경로 보존.
- [ ] `surge_detection.yaml` `gap_entry_threshold: 0.05` 추가 + 설정 모델 속성 반영.
- [ ] scheduler.py 3개 잡(17:00/08:00/09:05) 등록, 고유 id, 거래일 가드.
- [ ] DB 마이그레이션 없음 확인(기존 컬럼 재사용).
- [ ] MX 태그(WARN/NOTE/ANCHOR) plan.md MX Tag Plan대로 부여.
- [ ] 기존 15:20/10:00/09:00/09:05 잡 무변경 확인.
- [ ] Scenario 1~9 전부 통과.
