# SPEC-AI-042 (Compact): 야간·장전 공시 기반 갭업 조기 포착

id: SPEC-AI-042 | version: 1.0.0 | status: draft | priority: high

## 한 줄 요약

장 마감(15:30) ~ 장 시작(09:00) 사이 접수되는 야간·장전 공시를 포착하여, 신규 `signal_type="preday_disclosure"` 시그널로 저장하고 익일 09:05 갭업 초기(0% ≤ gap < 5%)에 기존 `execute_buy_orders`로 조기 진입한다. 기존 15:20/10:00 생성 잡과 09:00/09:05 실행 잡은 무변경. DB 마이그레이션 불요.

## 요구사항 (EARS)

### M1: 장 마감 후 공시 스캔
- **REQ-042-001**: When 17:00 KST 잡(`surge_preday_scan`) 트리거 시, 당일 15:30 이후 공시에 `detect_immediate_disclosure_signal` + `detect_disclosure_surge_pattern` 실행 → `signal_type="preday_disclosure"` FundSignal 저장(surge_metadata에 detector/disclosure_id/source, disclosure_id 컬럼에도 기록).
- **REQ-042-002**: If 동일 stock_id + 동일 disclosure_id 시그널 존재 시, then 스킵. 판정 우선순위: disclosure_id 컬럼 → surge_metadata JSON fallback.

### M2: 장전 워치리스트 갱신
- **REQ-042-003**: When 08:00 KST 잡(`surge_preopen_refresh`) 트리거 시, 전날 17:00 이후 preday 시그널 + 당일 00:00 이후 신규 공시 재스캔(REQ-042-002 중복 방지 동일 적용).
- **REQ-042-004**: watch_list = `get_today_signals()` 활성 시그널 ∪ 유효 preday_disclosure 시그널 (stock_id 기준 중복 제거).

### M3: 9:05 KST 조기 진입
- **REQ-042-005**: When 09:05 KST 잡(`surge_preday_early_entry`) 트리거 시, preday_disclosure 보유 종목별 gap_rate 조회. gap_rate = `fetch_current_price_with_change().change_rate`(전일 종가 대비, 시가 미제공으로 change_rate를 갭 대용 사용).
- **REQ-042-006**: 갭 필터 — gap_rate ≥ 5%(gap_entry_threshold) → skip(gap_pullback 위임); gap_rate < 0% → skip(갭다운); 0% ≤ gap_rate < 5% → 채택.
- **REQ-042-007**: 조기 매수 시 기존 `execute_buy_orders()`(max_open_positions=7, position_pct=0.14, 한도/섹터/BEAR 게이트) 그대로 재사용.

### M4: 설정 및 통합
- **REQ-042-008**: `surge_detection.yaml`의 `surge_detection:` 블록에 `gap_entry_threshold`(기본 0.05) 추가. 갭 필터는 설정값 읽음(하드코딩 금지).
- **REQ-042-009**: `get_today_signals()`가 preday_disclosure 시그널 중 당일 08:00 KST 이후 생성분을 signal_cutoff 예외로 포함. surge_candidate 경로(직전 영업일 15:00) 보존.
- **REQ-042-010**: 기존 15:20/10:00 생성 잡 + 09:00/09:05 실행 잡 무변경. 신규 잡은 고유 id(`surge_preday_scan`/`surge_preopen_refresh`/`surge_preday_early_entry`)로 충돌 회피.

### M5: 거래일 가드 및 안전
- **REQ-042-011**: If 주말 또는 KRX_EXTRA_HOLIDAYS 휴장일, then 3개 신규 잡 즉시 스킵.
- **REQ-042-012**: If 종목 갭 조회 실패, then 해당 종목 건너뛰고 계속(전체 실패 금지).
- **REQ-042-013**: While 09:05 잡 실행 중, 기존 BUY_CUTOFF/`is_buy_eligible_hours` 가드에 의존(우회 금지).

## Delta Markers
- [EXISTING] `execute_buy_orders()`, `detect_immediate_disclosure_signal()`, `detect_disclosure_surge_pattern()`, 15:20/10:00/09:00/09:05 잡 — 무변경.
- [MODIFY] `get_today_signals()`(surge_trading_service.py:169) — preday_disclosure 당일 08:00 cutoff 포함.
- [MODIFY] `surge_detection.yaml` + 설정 모델 — `gap_entry_threshold: 0.05` 추가.
- [NEW] `preday_signal_service.py` — post_market_scan / preopen_watchlist_refresh / early_entry_check.
- [NEW] scheduler 3개 잡 (17:00 / 08:00 / 09:05 KST).

## Exclusions
프리마켓 가격 수집(시가 미제공) · 야간 뉴스 감성 분석 · 기존 15:20/10:00 생성 잡 수정 · 기존 09:00/09:05 실행 잡 수정 · 해외 시장 연동 · DB 마이그레이션 · 신규 탐지기 · 매도/익절/손절.

## 인수 기준 (Acceptance, Given/When/Then 요약)
1. **Happy path**: 15:35 공시 → 17:00 스캔 시 preday_disclosure 1건 저장 → 익일 09:05 change_rate +3%(소갭) → 조기 진입(`entered ≥ 1`).
2. **갭 ≥ 5% skip**: change_rate +7.2% → 제외, `skipped_gapup` 증가, gap_pullback 위임.
3. **갭다운 skip**: change_rate -2.1% → 제외, `skipped_gapdown` 증가, 매수 미시도.
4. **중복 방지**: disclosure_id=999가 17:00 저장 후 08:00 재스캔 시 신규 생성 없음, DB에 정확히 1건.
5. **무결성**: 구현 후 10:00/15:20 surge_candidate 생성 수·내용 불변, signal_cutoff 동작 보존.
6. **워치리스트 합집합**: 활성 surge_candidate ∪ preday_disclosure (stock_id 중복 제거).
7. **거래일 가드**: 주말·휴장일에 3개 잡 모두 스킵.
8. **조회 실패 격리**: 1개 종목 갭 조회 실패 시 나머지 정상 처리, 잡 미중단.
9. **09:05 id 충돌 회피**: `fund_morning_execute`와 별도 id, 한도 게이트가 초과 매수 방지.

## Quality Gate
- 신규 단위 테스트 8건 이상 통과 (`test_preday_signal_service.py`, `test_early_entry_check.py`).
- `ruff check .` 경고 0, `mypy app/` 신규 코드 오류 0.
- 기존 surge 테스트 회귀 0건.
- REQ-042-001~013 전부 테스트 커버.

## 관련 SPEC
SPEC-AI-012(surge_metadata 의존) · SPEC-AI-004(gap_pullback 위임 대상) · SPEC-AI-031(장전 재확인 스캔 인접) · SPEC-AI-041(평가 루프 인접).
