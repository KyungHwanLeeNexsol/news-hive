# SPEC-AI-042 구현 계획 (Implementation Plan)

## 1. 개요

야간·장전 공시 기반 갭업 조기 포착 기능을 추가한다. 신규 서비스 1개(`preday_signal_service.py`), 기존 함수 1개 수정(`get_today_signals`), YAML 필드 1개 추가, 스케줄러 잡 3개 등록. **DB 마이그레이션 불요**(기존 `signal_type`/`disclosure_id`/`surge_metadata` 컬럼 재사용).

## 2. 기술 접근 (Technical Approach)

- **신규 signal_type 분리**: `preday_disclosure`를 기존 `surge_candidate`와 구분하여 평가·실행 경로 격리.
- **탐지기 재사용**: `detect_immediate_disclosure_signal` / `detect_disclosure_surge_pattern`을 메인 `gather_surge_candidates` 흐름 밖에서 독립 호출. 두 함수는 `(db, config)`만 받아 `SurgeCandidate` 리스트를 반환하므로 부작용 없이 독립 호출 가능(T-001에서 검증).
- **갭 대용 지표**: 시가 미제공 제약 때문에 `change_rate`(전일 종가 대비 등락률)를 갭 필터 입력으로 사용.
- **실행 재사용**: 신규 매수 로직 없이 `execute_buy_orders`를 그대로 호출. `get_today_signals`가 preday_disclosure를 반환하도록 확장하는 것이 통합 지점.
- **잡 격리**: 신규 잡 3개는 고유 id 사용. 09:05은 기존 `fund_morning_execute`와 동일 분이지만 별도 id로 충돌 회피.

## 3. 작업 분해 (Task Decomposition)

> 우선순위 라벨: P-High(차단 의존) / P-Med / P-Low. 시간 추정 없음.

| ID | 작업 | 산출물 | 우선순위 | 선행 |
|---|---|---|---|---|
| **T-001** | `detect_immediate_disclosure_signal()` + `detect_disclosure_surge_pattern()`의 독립 호출 가능성 확인 (read-only). 부작용·전역 상태 의존 여부, 반환 `SurgeCandidate` 필드(stock_id/stock_code/score) 확정 | 검증 노트 (코드 내 구현 불요) | P-High | — |
| **T-002** | `FundSignal.signal_type`/`disclosure_id`/`surge_metadata` 컬럼 존재 재확인 및 String(30) 길이 `preday_disclosure`(17자) 수용 확인. SurgeCandidate→FundSignal 매핑 필드 결정 | 매핑 표 | P-High | — |
| **T-003** | `preday_signal_service.py` 생성 — `post_market_scan(db, scan_from_dt) -> int` + `_save_preday_signal(db, candidate, disclosure_id) -> bool`(중복 시 False). REQ-042-001, 002 | 신규 파일 | P-High | T-001, T-002 |
| **T-004** | `preday_signal_service.py` — `preopen_watchlist_refresh(db) -> int`. 전날 17:00 이후 preday 시그널 + 당일 00:00 이후 신규 공시 재스캔. REQ-042-003, 004 | 함수 추가 | P-Med | T-003 |
| **T-005** | `preday_signal_service.py` — `early_entry_check(db) -> dict` + `_compute_gap_rate(stock_code) -> float|None`. 갭 계산 + 3분류 필터 + `execute_buy_orders` 호출. REQ-042-005, 006, 007, 012 | 함수 추가 | P-High | T-003 |
| **T-006** | `surge_detection.yaml`에 `gap_entry_threshold: 0.05` 추가 + 설정 모델(Pydantic)에 대응 속성 추가 + `get_surge_config()` 로드 확인. REQ-042-008 | YAML + 모델 수정 | P-High | — |
| **T-007** | `get_today_signals()` 수정 — signal_cutoff 분기에 `preday_disclosure`(당일 08:00 KST cutoff) 포함. surge_candidate 경로 보존. REQ-042-009 | 함수 수정 | P-High | T-002 |
| **T-008** | `scheduler.py` `start_scheduler()`에 3개 잡 등록 (`surge_preday_scan` 17:00, `surge_preopen_refresh` 08:00, `surge_preday_early_entry` 09:05) + 래퍼 함수 + 거래일 가드. REQ-042-010, 011, 013 | scheduler 수정 | P-Med | T-003, T-004, T-005 |
| **T-009** | `tests/test_preday_signal_service.py` 작성 (unit, 8+ cases): post_market_scan 저장/중복방지, preopen_refresh 합집합/중복방지, SurgeCandidate→FundSignal 매핑, disclosure_id fallback, 거래일 가드, 갭 조회 실패 격리 | 테스트 파일 | P-High | T-003, T-004 |
| **T-010** | `tests/test_early_entry_check.py` 작성: 갭 필터 로직 4분류(갭다운<0 skip / 0 경계 채택 / 소갭 채택 / 대갭≥5% skip), execute_buy_orders 호출 여부, gap_entry_threshold 설정 반영 | 테스트 파일 | P-High | T-005, T-006 |

## 4. 마일스톤 (Milestones, 우선순위 기반)

1. **M1 — 기반 검증 + 설정** (P-High): T-001, T-002, T-006 완료. 탐지기 독립 호출 가능성·모델 매핑·YAML 임계값 확정.
2. **M2 — 스캔·저장 코어** (P-High): T-003, T-009(스캔 부분). post_market_scan + 중복 방지 동작.
3. **M3 — 조기 진입 코어** (P-High): T-005, T-007, T-010. 갭 필터 + get_today_signals 통합 + execute_buy_orders 재사용.
4. **M4 — 워치리스트 + 스케줄링** (P-Med): T-004, T-008. preopen 재스캔 + 3개 잡 등록.
5. **M5 — 통합 검증** (P-High): 전체 테스트 통과 + SC-5 무결성 검증(기존 잡 동작 불변).

## 5. 검증 명령 (Verification)

```bash
# 백엔드 단위 테스트 (slow 제외)
cd backend && uv run pytest tests/test_preday_signal_service.py tests/test_early_entry_check.py --tb=short -q

# 임포트 무결성
cd backend && uv run python -c "from app.services.preday_signal_service import post_market_scan, preopen_watchlist_refresh, early_entry_check; print('OK')"

# 린트·타입
cd backend && uv run ruff check . && uv run mypy app/

# 기존 surge 테스트 회귀 (SC-5 무결성)
cd backend && uv run pytest tests/ -k "surge or signal" --tb=short -q -m "not slow"
```

## 6. MX Tag Plan

| 위치 | 태그 | 사유 |
|---|---|---|
| `preday_signal_service.py:early_entry_check()` | `# @MX:WARN` + `# @MX:REASON` | BUY_CUTOFF 이전 매수 가능 시간 내에서만 실행되어야 하며, gap 임계값은 반드시 `get_surge_config().gap_entry_threshold`에서 읽고 하드코딩 금지. 매수 주문을 유발하는 실행 경로 |
| `get_today_signals()` 수정 부분 (`surge_trading_service.py:169`) | `# @MX:NOTE` + `# @MX:SPEC: SPEC-AI-042` | preday_disclosure를 당일 08:00 cutoff로 포함하는 분기 로직 설명. surge_candidate 경로(직전 영업일 15:00)와 구분됨 |
| `_save_preday_signal()` | `# @MX:NOTE` | disclosure_id 기반 중복 방지 키 우선순위(컬럼 → surge_metadata fallback) 설명 |
| 3개 신규 스케줄러 잡 래퍼 (`scheduler.py`) | `# @MX:NOTE` | 잡 간 의존 관계: `surge_preday_scan`(17:00) → `surge_preopen_refresh`(08:00) → `surge_preday_early_entry`(09:05). 09:05은 기존 `fund_morning_execute`와 동일 분·별도 id |
| `early_entry_check()`가 fan_in 기준 충족 시 | `# @MX:ANCHOR` (구현 후 fan_in ≥ 3 확인 시) | 라우터/스케줄러/테스트에서 참조되면 ANCHOR로 승격 |

## 7. 가정 (Assumptions)

1. `detect_immediate_disclosure_signal`/`detect_disclosure_surge_pattern`은 부작용 없이 `(db, config)`만으로 독립 호출 가능 (T-001에서 검증, 미충족 시 wrapper 필요).
2. `SurgeCandidate`에 `disclosure_id` 또는 그에 매핑 가능한 식별자가 포함된다(미포함 시 공시 조회로 역추적 — T-001 확인 항목).
3. 09:05 시점 `fetch_current_price_with_change()`의 `change_rate`가 갭 대용으로 실용적이다(진짜 시가 갭과의 괴리는 RISK-2로 수용).
4. 기존 `execute_buy_orders`의 BEAR 레짐 중단·한도 게이트가 preday 진입에도 동일하게 적용되는 것이 의도된 동작이다.
