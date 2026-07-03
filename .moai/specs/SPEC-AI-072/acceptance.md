# SPEC-AI-072 Acceptance Criteria

Given-When-Then 시나리오와 엣지케이스. 모든 기준은 관찰 가능(생성된 `FundSignal`의 confidence/
reasoning/`surge_metadata`, 스킵 여부, mock 호출, 테스트 출력)해야 하며, 타 탐지기·앙상블·매수 로직·
DB 스키마 diff는 0이어야 한다. 테스트는 `fetch_stock_price_history_sync`를 OHLCV 픽스처로 mock 한다.

---

## AC-072-001 (REQ-001/003) — T-1 종가-대-종가로 change_rate 계산, 라이브 아님

**Given** 종목 A의 일봉 이력이 (최신순) `[오늘 partial, T-1 close=127, T-2 close=100, ...]` 이고,
`fetch_stock_price_history_sync`가 그 픽스처를 반환하도록 mock된 상태 (T-1-대-T-2 = (127-100)/100*100
= **+27.0%**)

**When** `detect_near_limit_up_carries(db, cfg)` 가 실행되면

**Then**:
- A에 대해 `change_rate = 27.0` 으로 판정되어 시그널이 생성된다(15.0~29.99 밴드 내).
- `confidence ≈ 27.0/30*0.5 = 0.45`.
- `surge_metadata["yesterday_change_pct"] == 27.0` (당일 partial 행 값이나 라이브 값이 **아님**).
- reasoning에 "전일 27.00% 상승"이 포함된다.
- `_fetch_price_change_sync`(라이브)는 change_rate 산출에 사용되지 않는다(제거되었거나
  price_at_signal 전용).

---

## AC-072-002 (REQ-002) — 날짜 매칭으로 T-1 선택, 인덱스 가정 아님

**Given** 종목 B의 이력에 당일 partial 행이 `records[0]`으로 **존재하는** 픽스처와, 당일 partial 행이
**없는**(즉 `records[0]`이 T-1) 픽스처 두 가지. 두 경우 모두 T-1 close·T-2 close는 동일

**When** 각각에 대해 `detect_near_limit_up_carries` 가 실행되면

**Then**:
- 두 경우 모두 **동일한 T-1 change_rate**가 계산된다(인덱스 위치가 바뀌어도 `date` 매칭으로 올바른
  T-1/T-2를 선택).
- 당일 partial 행은 T-1으로 오선택되지 않는다(예상 T-1 날짜와 불일치).

---

## AC-072-003 (REQ-002) — T-1 날짜 부재 종목은 스킵, 배치 미중단

**Given** 종목 C의 이력에 예상 T-1 KST 거래일에 해당하는 `date` 레코드가 **없고**(데이터 공백/휴장
불일치), 뒤이어 처리될 종목 D는 정상 이력(T-1 +27%)을 가진 상태

**When** `detect_near_limit_up_carries(db, cfg)` 가 실행되면

**Then**:
- C는 시그널 없이 조용히 스킵된다(예외 없음, 배치 중단 없음).
- D는 정상적으로 시그널이 생성된다(C의 스킵이 후속 종목 처리를 막지 않음).

---

## AC-072-004 (REQ-004) — 임계·공식·시그널 생성 회귀 없음

**Given** T-1 change_rate가 각각 30.0(경계 초과), 29.99(상단 경계), 15.0(하단 경계), 10.0(미달)이
되도록 종가 픽스처가 구성된 4개 종목

**When** `detect_near_limit_up_carries(db, cfg)` 가 실행되면

**Then**:
- 30.0 → 생성 안 함(상한가 도달, `> max` 배제), 29.99 → 생성, 15.0 → 생성, 10.0 → 생성 안 함
  (`< min`).
- 생성된 각 시그널의 `confidence == round(change_rate/30*0.5, 4)`.
- 모든 생성 시그널이 `signal_type=="surge_candidate"`, `paper_executed is True`,
  `surge_basis==["near_limit_up_carry"]`.
- 오늘 이미 시그널 있는 종목 중복 방지·`max_signals_per_day` 상한·시총 필터(NULL 허용)가
  기존대로 동작(별도 케이스로 확인).

---

## AC-072-005 (REQ-005) — price_at_signal 채워짐, 오라벨 없음

**Given** T-1 +27% 종목 E

**When** 시그널이 생성되면

**Then**:
- `price_at_signal` 이 NULL이 아니다(안 A: T-1 종가 = 127, 또는 안 B: 라이브 현재가 스냅샷).
- 당일 라이브 값이 `yesterday_change_pct`/"전일" reasoning에 오라벨되지 않는다(그 값은 T-1
  종가-대-종가 = 27.0 이어야 함).

---

## 엣지케이스

- **EC-1 close[T-2] <= 0**: T-2 종가가 0/음수인 비정상 픽스처면 0 나눗셈을 피해 그 종목을 스킵한다
  (`_get_peer_price_5d_trend`의 `oldest > 0` 가드와 동형). 예외 없이 다음 종목 진행.
- **EC-2 이력 조회 실패/빈 리스트**: `fetch_stock_price_history_sync`가 빈 리스트를 반환하거나 예외를
  던지면 그 종목만 스킵(기존 debug 로그 관례). 배치는 계속된다.
- **EC-3 pages 부족으로 T-2 없음**: 이력에 T-1은 있으나 그 이전(T-2) 레코드가 없으면 change_rate
  계산 불가 → 스킵. 정상 운영에서는 `pages`가 충분해야 하며 이 스킵이 광범위하면 `pages` 상향
  신호.
- **EC-4 함수 최상위 예외**: 내부에서 억제되지 않은 예외가 나면 기존 `try/except`(`:2729-2731`)가 빈
  리스트를 반환해 상위 파이프라인을 보호한다(무변경).
- **EC-5 enabled=False**: `config.enabled=False`면 즉시 빈 리스트 반환, 이력 조회 자체가 일어나지
  않는다(기존 `:2634-2635` 동작 무변경).

---

## Definition of Done

- [ ] 현행(라이브 기반, 버그) 동작 characterization test 존재(PRESERVE): 라이브 change_rate가
      임계/confidence/reasoning/`yesterday_change_pct`로 흘러가던 동작 스냅샷.
- [ ] change_rate가 `fetch_stock_price_history_sync` 일봉의 T-1 종가-대-종가로 계산됨(AC-072-001).
- [ ] T-1 레코드 선택이 `date` 매칭이며, 당일 partial 행 유무에 무관하게 동일 T-1 결과(AC-072-002).
- [ ] 예상 T-1 날짜 부재 종목이 배치 중단 없이 스킵되고 후속 종목은 정상 처리됨(AC-072-003).
- [ ] 임계(15.0~29.99)·`confidence=change_rate/30*0.5`·`paper_executed=True` surge_candidate 생성이
      change_rate 소스 외 무변경(AC-072-004).
- [ ] `price_at_signal` NULL 회귀 없음, 당일 값 오라벨 없음(AC-072-005).
- [ ] 모든 엣지케이스(EC-1~EC-5) 테스트 커버.
- [ ] `test_near_limit_up_carry.py`가 `fetch_stock_price_history_sync` mock 기반으로 갱신되고
      `yesterday_change_pct` 값 정확성을 단언.
- [ ] 테스트 커버리지 85%+, `ruff check` 무경고, 전체 급등 스위트 회귀 없음.
- [ ] 타 탐지기/앙상블 diff 0, 매수 로직 diff 0, DB 스키마 diff 0(신규 테이블/마이그레이션 없음).
- [ ] 과거 `FundSignal` 백필/재분류 없음(전진 전용, Exclusion 4 준수).
