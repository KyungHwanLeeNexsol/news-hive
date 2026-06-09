---
id: SPEC-AI-042
version: "1.0.0"
status: completed
completed_at: "2026-06-09"
created: "2026-06-09"
updated: "2026-06-09"
author: Nexsol
priority: high
issue_number: 0
---

# SPEC-AI-042: 야간·장전 공시 기반 갭업 조기 포착 (Overnight Disclosure Gap-Up Early Capture)

## HISTORY

- 2026-06-09 (v1.0.0): 최초 작성. 장 마감(15:30) 이후 ~ 장 시작(09:00) 사이에 접수되는 야간·장전 공시를 포착하여 익일 갭업 초기에 조기 진입하는 폐루프 정의. 신규 `signal_type="preday_disclosure"` 도입. 선행 SPEC: SPEC-AI-012(급등 시그널 + surge_metadata), SPEC-AI-004(공시 임팩트 스코어러 + gap_pullback), SPEC-AI-031(장 시작 직전 재확인 스캔 — 18h gap problem). 본 SPEC은 기존 15:20/10:00 시그널 생성 잡을 일절 수정하지 않는다.

---

## 1. Overview (개요)

### 목적

현재 급등 시그널 파이프라인은 **장 마감 후 15:30 ~ 장 시작 08:30 사이에 접수되는 공시(야간·장전 공시)를 어떤 시그널 생성 잡도 포착하지 못한다.** 이 시간대 공시는 익일 09:00 동시호가 갭업의 주요 동인이며, 시스템은 현재 이 갭업 초기 구간을 전부 놓친다(부분 완화책 `gap_pullback_check`는 10:00~11:30에 풀백을 매수하므로 초기 갭 자체는 포착 못 함).

본 SPEC은 다음 3단계 폐루프를 추가한다.

1. **장 마감 후 공시 스캔 (17:00 KST)**: 당일 15:30 이후 접수 공시를 조회하여 공시 기반 탐지기(`detect_immediate_disclosure_signal`, `detect_disclosure_surge_pattern`)만으로 `signal_type="preday_disclosure"` FundSignal을 생성한다.
2. **장전 워치리스트 갱신 (08:00 KST)**: 전날 17:00 이후 생성된 preday_disclosure 시그널 + 당일 00:00 이후 신규 공시를 재스캔하여 watch_list를 확정한다.
3. **9:05 KST 조기 진입 결정**: preday_disclosure 보유 종목의 실제 갭(gap_rate)을 조회하여 갭 필터(`0% ≤ gap_rate < 5%`)를 통과한 종목만 기존 `execute_buy_orders` 로직으로 조기 매수한다.

### 배경 — 현행 시그널 생성 타임라인 (수정 금지)

| 시각 (KST) | 스케줄러 id | 동작 | 본 SPEC 관계 |
|---|---|---|---|
| 15:20 | `surge_signal_generate` | `run_surge_signal_generation()` — 익일 surge_candidate 생성 (당일 장중 거래량 데이터 사용) | [EXISTING] 무변경 |
| 10:00 | `surge_signal_generate_intraday` | 장중 모멘텀 재탐지 | [EXISTING] 무변경 |
| 09:00~15:30 (30분 간격) | `surge_execute_buys` | `execute_buy_orders()` — surge_candidate 시그널 체결 | [EXISTING] 무변경 |
| 09:05 | `fund_morning_execute` | 08:30 브리핑 FundSignal 시가 일괄 체결 | [EXISTING] 무변경 (별도 잡, id 충돌 금지) |
| 10:00~11:30 (15분 간격) | `gap_pullback_check_*` | 갭업 풀백 매수 (`disclosure_impact_scorer._run_gap_pullback_check_sync`) | [EXISTING] 본 SPEC이 위임 대상(갭 ≥ 5%) |

**핵심 공백**: 위 어떤 잡도 15:30~08:30 야간·장전 공시를 시그널로 전환하지 않는다. `BUY_CUTOFF = time(11, 0)`(`surge_trading_service.py:31`)는 11:00 이후 신규 매수를 차단하므로, 갭업 초기 구간(09:00~09:05)을 노리는 별도 잡이 필요하다.

### 선행 인프라 (재사용)

| 컴포넌트 | 위치 (검증 2026-06-09) | 용도 |
|---|---|---|
| `detect_immediate_disclosure_signal(db, config)` | `surge_detector.py:862` | 즉각 공시 이벤트(자사주 소각·수주·합병) 기반 후보. 과거 통계 불요. `SurgeCandidate` 반환 |
| `detect_disclosure_surge_pattern(db, config)` | `surge_detector.py:737` | 공시 유형별 과거 급등 패턴 기반 후보. `SurgeCandidate` 반환 |
| `get_today_signals(db, min_probability)` | `surge_trading_service.py:169` | surge_candidate 시그널 조회. **현재 `signal_type=="surge_candidate"`만 필터**(`:200`). preday_disclosure 미포함 |
| `execute_buy_orders(db, max_daily_entries=6, max_open_positions=7, position_pct=0.14, ...)` | `surge_trading_service.py:599` | 매수 실행 메인. `get_today_signals()` 호출 후 한도·중복·임계 필터링 |
| `BUY_CUTOFF=time(11,0)` / `ENTRY_GAPUP_LIMIT=0.05` | `surge_trading_service.py:31`, `:34` | 11:00 매수 마감 / 5% 갭업 진입 제외 (실행 단계 게이트) |
| `is_market_hours()` / `KRX_EXTRA_HOLIDAYS` / `_get_prev_business_day()` | `surge_trading_service.py:103`, `:38`, `:161` | 거래일·휴장일 가드 (KST) |
| `disclosure_impact_scorer` (`score_disclosure_impact`, `detect_unreflected_gap`, `activate_gap_pullback`) | `disclosure_impact_scorer.py` | 갭업 탐지·풀백 진입 (위임 대상) |
| `FundSignal` 모델 | `fund_signal.py` | `signal_type`(String(30), `:70`), `disclosure_id`(FK, `:71`), `surge_metadata`(Text JSON, `:87`) **모두 존재** |
| `Stock.stock_code` | `stock.py:15` | FundSignal에 stock_code 컬럼 없음 → stock_id로 조인 필요 |
| `get_surge_config()` | `surge_settings.py:411` | `surge_detection.yaml` 싱글턴 로더 |
| `scheduler.add_job(func,"cron",day_of_week="mon-fri",hour=H,minute=M,timezone="Asia/Seoul",id=...,max_instances=1,coalesce=True,replace_existing=True)` | `scheduler.py:1246` (`start_scheduler`) | 잡 등록 패턴. KST 시각 직접 지정(UTC 변환 불요) |

---

## 2. Requirements (요구사항 — EARS)

### Module 1: 장 마감 후 공시 스캔 (Post-Market Disclosure Scan)

- **REQ-042-001** (Event-Driven): When 거래일 17:00 KST 잡(`surge_preday_scan`)이 트리거되면, the 시스템 **shall** 당일 15:30 이후 접수된 공시를 대상으로 `detect_immediate_disclosure_signal(db, config)` 및 `detect_disclosure_surge_pattern(db, config)`을 실행하고, 그 결과 후보를 `signal_type="preday_disclosure"` FundSignal로 저장한다.
  - 저장 시 `surge_metadata` JSON에 `{"detector": <탐지기명>, "disclosure_id": <id>, "source": "preday_scan", "scan_from": "<당일 15:30 KST ISO>"}`를 포함한다.
  - FundSignal `disclosure_id` 컬럼에도 동일 공시 id를 기록한다(중복 판정 1차 키).
- **REQ-042-002** (Unwanted Behavior): If 동일 종목(stock_id)에 대해 동일 `disclosure_id` 기반 시그널이 이미 존재하면, **then** the 시스템 **shall** 신규 FundSignal을 생성하지 않고 스킵한다.
  - 중복 판정 우선순위: (1) `FundSignal.disclosure_id == disc_id` 존재 여부, (2) fallback으로 `surge_metadata` JSON의 `disclosure_id` 키 일치 여부.

### Module 2: 장전 워치리스트 갱신 (Pre-Open Watch List Refresh)

- **REQ-042-003** (Event-Driven): When 거래일 08:00 KST 잡(`surge_preopen_refresh`)이 트리거되면, the 시스템 **shall** (a) 전날 17:00 KST 이후 생성된 `preday_disclosure` 시그널과 (b) 당일 00:00 KST 이후 접수된 신규 공시를 재스캔하여 누락된 공시에 대해 REQ-042-001과 동일 방식으로 추가 preday_disclosure 시그널을 생성한다.
  - 재스캔 시에도 REQ-042-002 중복 방지를 동일하게 적용한다.
- **REQ-042-004** (Ubiquitous): The 시스템 **shall** watch_list를 `get_today_signals()`가 반환하는 현재 활성 시그널 집합과 유효한 `preday_disclosure` 시그널 집합의 **합집합(stock_id 기준 중복 제거)**으로 산출한다.

### Module 3: 9:05 KST 조기 진입 결정 (Early Entry at 9:05 KST)

- **REQ-042-005** (Event-Driven): When 거래일 09:05 KST 잡(`surge_preday_early_entry`)이 트리거되면, the 시스템 **shall** 유효한 `preday_disclosure` 시그널 보유 종목 각각에 대해 실제 시가 대비 갭(gap_rate)을 조회한다.
  - gap_rate 정의: 전일 종가 대비 현재가 등락률(`fetch_current_price_with_change()`의 `change_rate`). **주의: 시가(open_price)는 동기 가격 경로에서 제공되지 않으므로 change_rate를 갭 대용 지표로 사용한다.**
- **REQ-042-006** (State-Driven / Unwanted Behavior): The 시스템 **shall** 다음 갭 필터를 적용한다.
  - If `gap_rate >= gap_entry_threshold`(기본 5%), **then** the 시스템 **shall** 해당 종목을 조기 진입에서 제외한다(이미 늦음 → 기존 `gap_pullback_check`에 위임).
  - If `gap_rate < 0%`(갭다운), **then** the 시스템 **shall** 해당 종목을 조기 진입에서 제외한다(공시 재료 음성 판단, 패턴 파괴).
  - While `0% <= gap_rate < gap_entry_threshold`인 동안, the 시스템 **shall** 해당 종목을 조기 매수 대상으로 채택한다.
- **REQ-042-007** (Event-Driven): When 조기 매수가 결정되면, the 시스템 **shall** 기존 `execute_buy_orders()` 로직(`max_open_positions=7`, `position_pct=0.14`, `max_daily_entries`, 섹터 한도, BEAR 레짐 중단 등 전 게이트)을 그대로 재사용하여 매수를 실행한다. 신규 매수 수량·자본 배분 로직을 별도로 구현하지 않는다.

### Module 4: 설정 및 통합 (Config & Integration)

- **REQ-042-008** (Ubiquitous): The 시스템 **shall** `surge_detection.yaml`의 `surge_detection:` 블록에 `gap_entry_threshold`(기본값 `0.05` = 5%) 필드를 추가하고, `get_surge_config()`로 로드 가능하게 한다. 조기 진입 갭 필터(REQ-042-006)는 이 설정값을 읽으며 하드코딩하지 않는다.
- **REQ-042-009** (Event-Driven): When `get_today_signals()`가 호출되면, the 시스템 **shall** signal_cutoff(직전 영업일 15:00 KST) 조건의 예외로 `signal_type="preday_disclosure"` 시그널 중 당일 08:00 KST 이후 생성된 것을 유효 시그널에 포함한다.
  - 기존 `surge_candidate` 시그널의 signal_cutoff 동작(직전 영업일 15:00 이후)은 변경하지 않는다.
- **REQ-042-010** (Unwanted Behavior): The 시스템 **shall** 기존 15:20(`surge_signal_generate`)·10:00(`surge_signal_generate_intraday`) 시그널 생성 흐름과 09:05(`fund_morning_execute`)·09:00(`surge_execute_buys`) 실행 잡을 일절 수정하지 않는다. 신규 잡은 고유 id(`surge_preday_scan`/`surge_preopen_refresh`/`surge_preday_early_entry`)를 사용하여 기존 잡과 `replace_existing` 충돌을 일으키지 않는다.

### Module 5: 거래일 가드 및 안전 (공통)

- **REQ-042-011** (Unwanted Behavior): If 실행일이 주말이거나 `KRX_EXTRA_HOLIDAYS` 휴장일이면, **then** the 시스템 **shall** 3개 신규 잡(스캔·갱신·조기진입)을 즉시 스킵한다.
- **REQ-042-012** (Unwanted Behavior): If 특정 종목의 갭 조회가 실패하면, **then** the 시스템 **shall** 해당 종목을 건너뛰고 나머지 종목 처리를 계속한다(전체 실패 금지).
- **REQ-042-013** (State-Driven): While `surge_preday_early_entry` 잡이 실행되는 동안, the 시스템 **shall** `execute_buy_orders`의 기존 `BUY_CUTOFF`/시간 가드(`is_buy_eligible_hours`)에 의존하며, 09:05이 매수 가능 시간 내임을 별도로 우회하지 않는다.

---

## 3. Architecture (아키텍처)

### 3.1 데이터 흐름

```
[당일 17:00] surge_preday_scan
    → post_market_scan(db, scan_from_dt=당일 15:30 KST)
    → detect_immediate_disclosure_signal + detect_disclosure_surge_pattern
    → preday_disclosure FundSignal 저장 (중복 방지: disclosure_id)

[익일 08:00] surge_preopen_refresh
    → preopen_watchlist_refresh(db)
    → (전날 17:00 이후 preday 시그널) ∪ (당일 00:00 이후 신규 공시 재스캔)
    → watch_list 확정

[익일 09:05] surge_preday_early_entry
    → early_entry_check(db)
    → preday_disclosure 보유 종목별 gap_rate 조회 (fetch_current_price_with_change)
    → 갭 필터: gap<0 skip / gap>=5% skip(gap_pullback 위임) / 0<=gap<5% 채택
    → execute_buy_orders(db) 재사용  [get_today_signals가 preday 포함하도록 수정됨]
```

### 3.2 신규 파일 — `backend/app/services/preday_signal_service.py`

| 함수 | 시그니처 (제안) | 담당 REQ |
|---|---|---|
| `post_market_scan` | `def post_market_scan(db: Session, scan_from_dt: datetime) -> int` | REQ-042-001, 002 |
| `preopen_watchlist_refresh` | `def preopen_watchlist_refresh(db: Session) -> int` | REQ-042-003, 004 |
| `early_entry_check` | `def early_entry_check(db: Session) -> dict` | REQ-042-005, 006, 007, 012 |
| `_compute_gap_rate` | `def _compute_gap_rate(stock_code: str) -> float | None` | REQ-042-005 (change_rate 기반) |
| `_save_preday_signal` | `def _save_preday_signal(db, candidate, disclosure_id) -> bool` | REQ-042-001, 002 (중복 시 False) |

- `post_market_scan` 반환: 신규 저장한 preday_disclosure 시그널 수.
- `early_entry_check` 반환: `{"candidates": int, "entered": int, "skipped_gapup": int, "skipped_gapdown": int, "execute_result": <execute_buy_orders dict>}`.

### 3.3 수정 파일 — `backend/app/services/surge_trading_service.py`

`get_today_signals(db, min_probability)` (line 169) — [MODIFY]:
- 기존 `signal_type=="surge_candidate"` 필터(line 200)에 더해 `signal_type=="preday_disclosure"` AND 당일 08:00 KST 이후 생성된 시그널을 포함하도록 쿼리·필터 확장(REQ-042-009).
- preday_disclosure 시그널의 날짜 유효성은 직전 영업일 15:00 cutoff가 아닌 **당일 08:00 KST cutoff**를 적용(분기 처리).
- surge_candidate 경로의 기존 동작은 보존.

### 3.4 수정 파일 — `backend/app/surge_config/surge_detection.yaml`

`surge_detection:` 블록(`min_score_for_signal: 0.45`와 동일 4-space 들여쓰기 레벨)에 추가:

```yaml
    # SPEC-AI-042: 야간·장전 공시 갭업 조기 진입 갭 필터 임계값
    # change_rate(전일 종가 대비 등락률) 기준. 0 <= gap < gap_entry_threshold 구간만 조기 진입.
    gap_entry_threshold: 0.05
```

> 주의: 본 SPEC은 `surge_detection.yaml`에 **단일 필드(`gap_entry_threshold`)만 추가**한다. 앙상블 가중치·기존 임계값은 무변경. 설정 객체(`get_surge_config()` 반환 타입)에 대응 속성 추가 필요(구현 시 Pydantic 모델 확장).

### 3.5 수정 파일 — `backend/app/services/scheduler.py`

`start_scheduler()`(line 1246) 내부에 3개 잡 등록 추가. 기존 cron 패턴(KST 직접 지정)을 그대로 따른다.

| 래퍼 함수 | id | hour/minute (KST) | 호출 |
|---|---|---|---|
| `_run_surge_preday_scan` | `surge_preday_scan` | 17:00 | `post_market_scan(db, 당일 15:30)` |
| `_run_surge_preopen_refresh` | `surge_preopen_refresh` | 08:00 | `preopen_watchlist_refresh(db)` |
| `_run_surge_preday_early_entry` | `surge_preday_early_entry` | 09:05 | `early_entry_check(db)` |

- 각 래퍼: `SessionLocal()` 생성 → 거래일 가드(REQ-042-011) → 서비스 호출 → `db.close()`. 비동기 필요 시 `asyncio.run()`.
- **09:05 충돌 주의**: 기존 `fund_morning_execute`(id `fund_morning_execute`, 09:05)와 **별도 잡**으로 등록한다. id가 다르므로 `replace_existing`은 서로 영향 없음. 두 잡은 동일 분에 독립 실행되며 공유 자원(포트폴리오 현금)은 `execute_buy_orders` 내부 트랜잭션·한도 게이트가 처리한다.

### 3.6 마이그레이션

**불필요.** `FundSignal.signal_type`(String(30))·`disclosure_id`(FK)·`surge_metadata`(Text)가 이미 존재하므로 신규 컬럼·테이블·마이그레이션이 없다. `preday_disclosure`는 기존 `signal_type` 컬럼에 저장되는 신규 enum 값일 뿐이다.

---

## 4. Delta Markers (Brownfield)

| 마커 | 대상 | 변경 내용 |
|---|---|---|
| [EXISTING] | `execute_buy_orders()` (`surge_trading_service.py:599`) | 코드 무변경. 신규 09:05 잡에서 호출만 추가됨 |
| [EXISTING] | `detect_immediate_disclosure_signal()` (`surge_detector.py:862`) | 코드 무변경. preday 스캔에서 독립 호출 |
| [EXISTING] | `detect_disclosure_surge_pattern()` (`surge_detector.py:737`) | 코드 무변경. preday 스캔에서 독립 호출 |
| [EXISTING] | 15:20/10:00 시그널 생성 잡, 09:00/09:05 실행 잡 | 전부 무변경 |
| [MODIFY] | `get_today_signals()` (`surge_trading_service.py:169`) | signal_cutoff 분기에 preday_disclosure(당일 08:00 cutoff) 포함 |
| [MODIFY] | `surge_detection.yaml` + 대응 설정 모델 | `gap_entry_threshold: 0.05` 필드 1개 추가 |
| [NEW] | `preday_signal_service.py` | post_market_scan / preopen_watchlist_refresh / early_entry_check |
| [NEW] | scheduler.py 3개 잡 | `surge_preday_scan`(17:00) / `surge_preopen_refresh`(08:00) / `surge_preday_early_entry`(09:05) |

---

## 5. Risks (위험)

| ID | 위험 | 완화책 |
|---|---|---|
| RISK-1 | 09:05 `surge_preday_early_entry`와 기존 `fund_morning_execute`(09:05) 동시 실행 시 현금 경쟁 | id 분리 + `execute_buy_orders` 내부 트랜잭션·`max_open_positions`/현금 게이트가 단일 진실 원천. 두 잡 모두 동일 한도 게이트를 통과하므로 초과 매수 불가 |
| RISK-2 | 시가(open_price) 미제공으로 진짜 갭(시가-전일종가)이 아닌 change_rate(현재가-전일종가) 사용 | change_rate를 갭 대용 지표로 명시(REQ-042-005). 09:05 시점 현재가는 시가에 근접하므로 실용적 근사. 진짜 시가 갭이 필요하면 별도 데이터 경로 SPEC |
| RISK-3 | 동일 공시가 17:00 스캔·08:00 재스캔에서 2회 시그널화 | disclosure_id 기반 중복 방지(REQ-042-002). 재스캔도 동일 가드 적용 |
| RISK-4 | preday_disclosure 시그널이 기존 surge_candidate 검증·평가(SPEC-AI-041) 로직에 혼입 | SPEC-AI-041의 surge signal_type 필터에 preday_disclosure 포함 여부는 AI-041 소관. 본 SPEC은 신규 signal_type 발행만 담당하며 평가 로직 미변경 |
| RISK-5 | `detect_*` 탐지기가 SurgeCandidate를 반환하므로 FundSignal 변환 매핑 필요 | `_save_preday_signal`에서 SurgeCandidate→FundSignal 매핑(stock_id, confidence, surge_metadata) 명시. 기존 surge_detector의 FundSignal 생성부(`surge_candidate` 저장 패턴) 참고 |
| RISK-6 | 08:00 잡이 당일 공휴일에 실행(브리핑 08:30 전) | REQ-042-011 거래일 가드가 3개 잡 모두 스킵 |

---

## 6. Success Criteria (성공 기준)

- **SC-1**: 15:30 이후 접수된 공시가 17:00 스캔에서 `preday_disclosure` 시그널로 저장된다(저장 수 ≥ 0, 중복 0건).
- **SC-2**: 09:05 잡 실행 시 갭 필터가 정확히 3분류(갭다운 skip / 소갭 채택 / 대갭 위임)된다.
- **SC-3**: `0% <= gap_rate < 5%` 종목만 `execute_buy_orders` 경로로 진입한다.
- **SC-4**: 동일 disclosure_id 기반 시그널이 17:00 + 08:00 두 잡에서 단 1건만 생성된다.
- **SC-5**: 기존 10:00 인트라데이·15:20 생성 잡의 동작·시그널 수가 본 SPEC 적용 전후 동일하다(무결성).
- **SC-6**: 거래일 가드가 주말·휴장일에 3개 신규 잡을 모두 스킵한다.

---

## 7. Exclusions (What NOT to Build / 제외 범위)

- **프리마켓 가격 데이터 수집 없음**: 네이버 API가 장전 시간외·동시호가 체결 데이터를 제공하지 않으므로, 진짜 시가(open_price) 기반 갭 계산은 본 SPEC 범위 밖. change_rate 대용만 사용.
- **야간 뉴스 감성 분석 없음**: 공시 텍스트 기반 탐지기만 사용. 야간 뉴스 NLP 감성 점수는 별도 SPEC.
- **기존 15:20 / 10:00 시그널 생성 잡 수정 없음**: 신규 잡만 추가. 기존 surge_candidate 생성 흐름 완전 보존.
- **기존 09:00 / 09:05 실행 잡 수정 없음**: `surge_execute_buys`·`fund_morning_execute` 무변경.
- **해외 시장 연동 없음**: KOSPI/KOSDAQ 전용. 미국 야간 선물·해외 동조화 미반영.
- **신규 DB 마이그레이션 없음**: 기존 `signal_type`/`disclosure_id`/`surge_metadata` 컬럼 재사용. 새 테이블·컬럼 미도입.
- **신규 탐지기 없음**: 기존 공시 탐지기 2종만 재사용. 새 탐지기 알고리즘 미도입.
- **매도·익절·손절 로직 없음**: 조기 진입(매수)만 담당. 청산은 기존 `check_exit_conditions` 소관.

---

## 8. 관련 SPEC

- **SPEC-AI-012**: 급등 징후 탐지 + `surge_metadata` JSON 도입 (의존 — 동일 메타데이터 구조 재사용).
- **SPEC-AI-004**: 공시 임팩트 스코어러 + `activate_gap_pullback()` (병행 — 본 SPEC이 갭 ≥ 5% 종목을 gap_pullback에 위임).
- **SPEC-AI-031**: 장 시작 직전 재확인 스캔(18h gap problem) (인접 — 본 SPEC은 공시 기반 조기 진입에 특화, AI-031은 일반 재확인 스캔).
- **SPEC-AI-041**: 급등예측 자동평가·자가개선 루프 (인접 — preday_disclosure 시그널의 평가 편입 여부는 AI-041 소관).
- **데이터 제약 참고**: surge 동기 가격 경로는 `change_rate`만 제공하고 `open_price` 미제공 — REQ-042-005가 change_rate를 갭 대용으로 사용하는 근거(SPEC-AI-030이 동일 제약으로 open_price 비교를 change_rate로 대체한 전례).
