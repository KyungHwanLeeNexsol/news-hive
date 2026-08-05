# SPEC-AI-102 Plan

## A. 구현 전략

Tier M, cycle_type: ddd(ANALYZE-PRESERVE-IMPROVE — `.moai/config/sections/quality.yaml`
`constitution.development_mode: ddd`). 범위는 spec.md §Context 검증된 사실 1-4에 근거한
4가지 개선(Pool 소싱/existing 병합 분리, pool_b bridge 확장, 절단 상한 재평가, 잔여 순차
호출 전환)에 한정하며, 탐지기 스코어링·outcome 라벨·bridge 마스터 스위치 기본값·매수 실행
경로는 건드리지 않는다.

핵심 판단(결정 가역성이 높은 순 — 되돌리기 어려운 결정을 먼저 확정):

1. **`_MAX_PRICE_FETCH_CANDIDATES` 상향 폭**(spec.md §Decisions D3, §Open Questions 1) —
   가장 되돌리기 어려운 결정이다. 이 값은 앙상블 전체의 recall/precision 특성에 직접
   영향을 주며, 잘못 상향하면 SPEC-AI-096 이전 300초 타임아웃을 재현할 위험이 있다(spec.md
   §Context 검증된 사실 3). **결정 방법은 확정되었다**: TASK-001 사전조사(N=80/100/150 각각
   배치 조회 시 스캔 사이클 소요시간 실측)로 안전 상한을 확인한 뒤, Implementation Kickoff
   Approval 단계에서 사용자와 함께 구체적 값을 확정한다. 본 SPEC은 **다음 중 하나**를
   기본 시나리오로 제시하되, TASK-001 실측 결과가 이를 뒤집으면 재계획(Re-planning Gate)한다:
   - **Option A(기본 권장)**: 80으로 상향(50→80, +60%). 배치 조회 인프라 하에서
     `existing`(순수 탐지기 전용) 후보 80개 규모의 가격이력 배치 조회가 안전 여유 안에
     드는지가 TASK-001의 1차 검증 목표.
   - **Option B**: 변경 없음(50 유지). TASK-001 실측이 80개 규모에서도 소요시간 여유가
     부족하다고 나오면 채택 — "변경 없음"도 유효한 결론(REQ-AI102-003).
2. `build_scan_universe()` 함수 분리 설계(spec.md D1) — Pool 소싱 함수와 existing 병합·
   최종조립 함수의 정확한 분리 경계·내부 함수명은 TASK-002에서 확정한다. 하위 호환
   시그니처(공개 인터페이스)는 spec.md D1에서 이미 확정했으므로 이 결정의 가역성은
   중간 정도 — 이후 코드가 신규 내부 함수명에 의존하기 전까지는 되돌리기 쉽다.
3. `scan_universe_bridge_pool_limits["pool_b"]` 기본값(spec.md §Open Questions 2) — **5로
   확정**. pool_a/c 각 10 대비 신규 HTTP 비용이 있어 더 보수적인 시작값을 채택한다.
   TASK-003에서 그대로 반영한다. 신규 하위 플래그가 기본 False라 즉시 되돌릴 수 있어
   가역성이 가장 높다.
4. Pool B 루프 배치 전환 세부(스레드풀 크기 등은 SPEC-AI-097이 이미 확정한 패턴을 그대로
   재사용 — 신규 결정 없음, TASK-005는 순수 적용).

### A.1 순서 안정성 주의

`generate_scan_universe_bridge_candidates()`에 pool_b 대상이 추가되면 bridge 후보 순서에
`pool_b` 코드가 새로 섞여 들어간다 — 기존 pool_a/c만 있던 순서 가정(있다면)에 의존하는
하류 코드가 있는지 TASK-003에서 확인한다(`surge_metadata.surge_basis` 등 하류 소비자 grep).

**TASK-003 확인 결과(run-phase 기록)**: 순서 의존 하류 소비자 **없음**.
`surge_backtest._extract_combo_key()`가 `"+".join(sorted(basis))`로 정렬해 조합 키를
만들므로 순서 무관이다(`sorted` 호출을 소스에서 직접 확인). bridge 후보의
`active_detectors=["scan_universe_bridge", pool]`에 `pool_b`가 추가되면 새로운 조합 키
`pool_b+scan_universe_bridge`가 생길 뿐, 기존 `pool_a+scan_universe_bridge` /
`pool_c+scan_universe_bridge` 키의 의미는 변하지 않는다. 다른 소비자
(`continuation_bar_measurement_service._parse_surge_basis`,
`signal_verifier`, `fund_manager`)는 전부 멤버십 검사(`in`)만 수행한다.

### A.2 PRESERVE 목록(수정 금지)

| 대상 | 사유 |
|------|------|
| `fetch_current_prices_batch()`(naver_finance.py:1525) | SPEC-AI-016 소유, 매수 주문 실행 경로 — REQ-AI102-005 |
| `surge_trading_service.py` 전체 | 매수 주문 실행 — REQ-AI102-005 |
| 8개 탐지기의 스코어링 알고리즘(가중치/임계값), `compute_ensemble_score()`(:1574) | 무관 — 데이터를 "가져오는 시점/범위"만 변경 |
| Pool A/B/C/D 소싱 쿼리 각각의 필터·정렬 로직(`pool_a_rank_by_impact`, `_min_ratio=2.0`, 등락률 5% 하한, 뉴스 조인 조건) | SPEC-AI-065/074/076/078/086 소유 — 본 SPEC은 "언제 호출 가능한가"만 변경 |
| quota 배분 산술(`reserved_b/c/d`, clamp 로직, :5242-5297) | SPEC-AI-076/086 소유 — existing 병합·조립 함수로 그대로 이관, 로직 변경 없음 |
| `scan_universe_bridge_candidates_enabled` 마스터 스위치 기본값/활성화 절차 | SPEC-AI-092/096 D4 소유 — 운영 판단 대상, 본 SPEC은 대상 범위만 확장 |
| `fetch_stock_price_history_batch_sync()`(naver_finance.py:863) | SPEC-AI-097 소유 — 그대로 재사용, 수정하지 않음 |
| `_apply_price_fetch_truncation()`의 pool 소속 면제 로직(:2054-2077) | SPEC-AI-096 D2 소유 — 숫자(REQ-AI102-003)만 조정, 면제 판정 로직은 무변경 |

## B. 작업 분해

### TASK-001: `_MAX_PRICE_FETCH_CANDIDATES` 안전 상한 사전조사(코드 변경 없음)

- 대상: `_apply_price_fetch_truncation()`이 절단하는 `existing` 전용 후보를 N=80/100/150
  각각으로 배치 조회(`fetch_stock_price_history_batch_sync`)했을 때 스캔 사이클 소요시간을
  실측 fixture 또는 스테이징 재현으로 측정한다.
- 실측 결과를 spec.md §Decisions D3 시나리오(Option A/B) 중 하나의 채택 근거로 문서화한다.
- 추적 REQ/AC: REQ-AI102-003 / AC-102-001

#### TASK-001 실측 결과 (run-phase 기록, AC-102-001)

측정 환경: Windows 개발기(논리 코어 12), Naver `sise_day.naver` 실 HTTP,
실제 유니버스(`fetch_volume_leaders_sync(limit=90, max_pages=2)` → 172종목),
`pages=1`(절단이 실제로 게이팅하는 호출부와 동일), 매 회차 캐시 초기화. 단위 = wall초.

| N | 12코어 순차 | 12코어 배치 | 2코어 순차 | 2코어 배치 | 1코어 순차 | 1코어 배치 |
|---|---|---|---|---|---|---|
| 50 | 29.14 | 6.62 | — | — | **17.10** | 17.20 |
| 80 | 41.37 / 27.47 | 10.21 / 9.81 | 31.00 | 30.25 | **33.52** | **45.15** |
| 100 | — | 12.81 | — | — | — | — |
| 150 | — | 19.32 | — | 44.66 | ~63(선형 외삽) | **82.82** |

1코어 동시성 스윕(N=80): `batch_size=10` 45.15s / `bs=5` 34.10s / `bs=3` 37.71s —
전부 순차(33.52s)보다 느리다. CPU 계측(12코어, N=80): 순차 = CPU 23.19s / wall 27.47s
(84% — 이미 HTML 파싱·TLS로 CPU 바운드), 배치 = CPU 46.09s / wall 9.81s. 즉 동시성은
총 CPU 작업량을 약 2배로 늘리는 대가로 wall을 줄인다 — **코어가 있어야 이득이 난다**.

**핵심 결과: SPEC-AI-097 배치 이득은 코어 수 의존적이며 1코어에서 역전된다**
(12코어 3~4.4배 빠름 → 2코어 동률 → 1코어 약 35% 느림). 프로덕션은
`VM.Standard.E2.1.Micro`(1 OCPU)다.

**채택: Option B (50 유지, 코드 변경 없음)** — 근거 3가지:

1. 절단이 실제로 게이팅하는 호출부(`surge_detector.py` `_fetch_ph` 루프, TASK-006 표 7번)는
   **여전히 순차**다. SPEC-AI-097 배치 인프라가 이 경로에 아직 적용되어 있지 않으므로,
   "배치 인프라가 생겼으니 50을 올려도 안전하다"는 재평가 트리거가 이 값에는 아직
   성립하지 않는다.
2. 상향 자체는 위험하지 않다 — 1코어 기준 50→80은 +16.4s(17.10→33.52)로
   `_GATHER_TIMEOUT_S`(1200s, SPEC-AI-082가 300s에서 상향) 예산의 약 1.4%다. spec.md
   §Context 검증된 사실 3이 인용한 "300초 타임아웃 재현 위험"은 이미 stale하다.
   그러나 비용은 확실한 반면 이득은 미검증이므로 근거 없는 상향은 하지 않는다.
3. Option A를 재검토하려면 (a) 위 순차 루프의 배치 전환과 (b) 프로덕션 코어 수 확인이
   선행되어야 한다. 4코어 이상이면 배치 N=150(19.3s)이 현행 순차 N=50(29.1s)보다도
   빠르므로 상한을 크게 올릴 여지가 있고, 1코어면 배치 N=150(82.8s)이 현행(17.1s)의
   4.8배라 명백히 손해다.

미검증 갭: 프로덕션 코어 수 확인 실패(SSH 키 부재로 read-only `nproc` 프로브 불가).
측정치는 개발기 절대값이므로 프로덕션에 그대로 전이되지 않는다 — 전이 가능한 신호는
"코어 수에 따른 배치/순차 역전" 추세다.

### TASK-002: `build_scan_universe()` Pool 소싱 / existing 병합 함수 분리

- 대상: `surge_detector.py:4958`-`5345`.
- Pool A/B/C/D 소싱(existing_codes 미참조 부분)을 별도 내부 함수로 추출하고, existing
  병합·quota 배분·최종 조립(existing_codes 참조 부분)을 별도 함수로 추출한다.
- `build_scan_universe(db, config, existing_codes, now)`는 두 함수를 순서대로 호출하는
  얇은 wrapper로 재구성 — 공개 시그니처·반환값 완전 동일 유지(REQ-AI102-001).
- 신규 유닛 테스트: `existing_codes=set()`으로 Pool 소싱 함수 단독 호출 시 Pool A/B/C/D
  리스트가 `build_scan_universe()` 전체 호출과 동일함을 검증.

추적 REQ/AC: REQ-AI102-001 / AC-102-002, AC-102-003

### TASK-003: bridge 후보화 pool_b 하위 플래그 추가

- 대상: `generate_scan_universe_bridge_candidates()`(`:5355`-`5418`),
  `surge_settings.py:648`-`656`(`scan_universe_bridge_*` 필드군).
- 신규 config 필드: `scan_universe_bridge_pool_b_enabled: bool = False`,
  `scan_universe_bridge_pool_limits`에 `"pool_b"` 키 추가(기본값 5, §Open Questions 2 확정).
- pool_b 소속 + `merged`에 없는 종목에 대해 `fetch_stock_price_history_batch_sync()`로
  가격이력을 조회하고, 기존 Pool B 소싱 로직(`build_scan_universe` Pool B 루프)과 동일한
  거래량 비율 계산식(`_baseline_days=20`, `_min_ratio=2.0`)을 재사용해 점수화한다 — 새
  계산식을 발명하지 않는다(Enforce Simplicity).
- 마스터 스위치 OFF 또는 pool_b 하위 플래그 OFF(기본) 시 완전 무회귀를 characterization
  테스트로 증명한다.

추적 REQ/AC: REQ-AI102-002 / AC-102-004, AC-102-005, AC-102-006

### TASK-004: `_MAX_PRICE_FETCH_CANDIDATES` 상향 적용(TASK-001 근거 반영)

- 대상: `surge_detector.py:2011`.
- TASK-001 실측 결과에 따라 값을 상향하거나 유지한다. 상향 시 커밋 메시지에 실측 근거를
  기록한다(REQ-AI102-003 필수 조건).
- `_apply_price_fetch_truncation()`의 pool 소속 면제 로직(entry_pool != "existing")은
  무변경.

추적 REQ/AC: REQ-AI102-003 / AC-102-001

### TASK-005: `build_scan_universe()` Pool B 루프 배치 전환(최우선 대상)

- 대상: `surge_detector.py:5098`-`5126`(Pool B 순차 `fetch_stock_price_history_sync` 루프).
- `detect_volume_breakout()`(SPEC-AI-097 전환분, `:4681`-`4704`)과 동일 패턴으로
  `fetch_stock_price_history_batch_sync(volume_leader_codes, pages=3)` 일괄 조회 후,
  기존 baseline 계산·필터링 로직(`_resolve_today_volume`, `_baseline_days`, `_min_ratio`
  판정)은 그대로 유지한다 — 조회 방식만 배치로 전환.
- characterization 테스트: 전환 전/후 동일 입력 fixture에 대해 `pool_b_codes` 산출 결과가
  완전히 동일함을 증명(diff 0).

추적 REQ/AC: REQ-AI102-004 / AC-102-007, AC-102-008

### TASK-006: 잔여 순차 호출 지점 검토(전환 또는 판단 근거 기록)

- 대상: `_detect_volume_anomaly_internal`(`:3023`), `detect_near_limit_up_carries`(`:3274`),
  `detect_bollinger_squeeze_signals`(`:4404`) — 각각 `all_stocks`/`candidates`/`top_stocks`
  순회 규모를 확인하고, 배치 전환 이득이 있으면 전환, 없으면(단발 조회 성격이거나 이미
  config 상한으로 규모가 작으면) plan.md에 판단 근거를 기록한다.
- `_get_volume_history`(`:1068`)/`_get_peer_price_5d_trend`(`:2756`)는 종목 1개짜리 단발
  조회(pages=1)이므로 배치 전환 대상에서 제외 — 판단 근거는 spec.md D4에 이미 기록됨,
  재확인만 수행.

추적 REQ/AC: REQ-AI102-004 / AC-102-009

#### TASK-006 검토 결과 (run-phase 기록, AC-102-009)

**행 번호 주의**: spec.md/plan.md의 인용 행 번호는 SPEC-AI-101 M1(commit `3ae28ae`)이
plan 작성 이후 반영되어 약 +310행 밀려 있다. 아래는 현행 행 번호이며, 후속 작업자는
행 번호가 아니라 **함수명**으로 탐색할 것.

**잔여 순차 호출 지점은 6곳이 아니라 7곳이다.** spec.md §Context 검증된 사실 4의 표는
`grep -n "fetch_stock_price_history_sync("`로 열거했는데, 7번 지점은 import 별칭
(`... as _fetch_ph`)을 쓰기 때문에 그 grep에 걸리지 않아 누락됐다.

| # | 지점(함수) | 현행 행 | 규모 | 판단 | 근거 |
|---|-----------|--------|------|------|------|
| 1 | `_get_volume_history` | `:1340` | 종목 1개, pages=1 | **미전환** | 단발 조회 — 배치 이득 없음(spec.md D4 기록 재확인) |
| 2 | `_get_peer_price_5d_trend` | `:3069` | 종목 1개, pages=1 | **미전환** | 동일 — 단발 조회 |
| 3 | `_detect_volume_anomaly_internal` | `:3336` | `all_stocks` 순회, pages=6 | **미전환** | fetch **이전에** in-memory 사전 필터 2개(`signal_counts >= threshold` / `today_surge_ids`)가 `continue`로 후보를 걸러낸다. 선행 배치 조회는 순차 방식이 아예 조회하지 않는 종목까지 fetch하므로 HTTP 호출량이 늘어난다 — 전환하려면 필터를 fetch 앞으로 재배치하는 구조 변경이 필요하다(본 SPEC 범위 밖) |
| 4 | `detect_near_limit_up_carries` | `:3587` | `candidates` 순회(`max_stocks_to_check=1200`), pages=3 | **미전환** | 루프에 **데이터 의존적 조기 종료**(`len(signals) >= config.max_signals_per_day` → `break`)가 있다. 선행 배치는 break 지점을 알 수 없어 순차가 결코 조회하지 않을 종목까지 fetch한다 — 단순 전환은 동작 동등성을 깬다 |
| 5 | `detect_bollinger_squeeze_signals` | `:4717` | `top_stocks` 순회(`max_stocks_to_check=200`), pages=6 | **미전환** | 사전 필터·조기 종료가 없어 **구조적으로는 전환 가능한 유일한 지점**이다. 다만 200종목×6페이지 = 1200 요청 규모이고, TASK-001 실측상 1코어에서 배치는 순차보다 느리다. 프로덕션 코어 수 미확인 상태에서 이 규모를 전환하는 것은 정당화되지 않는다 — 코어 수 확인 후 별도 SPEC에서 재검토 |
| 6 | `build_scan_universe` Pool B | `:5460` | `volume_leader_codes` 순회(최대 140종목), pages=3 | **전환 완료** | TASK-005. 사전 필터·조기 종료 없음 → 배치 조회 집합이 순차 조회 집합과 정확히 일치(AC-102-007) |
| 7 | `_fetch_ph` price_5d_trend 루프 (**spec.md 표 누락분**) | `:2800` | `merged` 순회(= `_MAX_PRICE_FETCH_CANDIDATES` 상한 대상), pages=1 | **미전환** | `_MAX_PRICE_FETCH_CANDIDATES`(50)가 실제로 게이팅하는 유일한 지점. Option B(50 유지) 채택으로 상한이 그대로이므로 이번 SPEC에서 전환 불필요. 향후 Option A 재검토 시 **선행 조건**이 되므로 소스에 `@MX:NOTE`(SPEC-AI-102 TASK-006)로 탐색 가능하게 표시했다 |

**공통 판단 근거**: TASK-001 실측이 배치 전환의 이득을 코어 수 의존적으로 확정했고
(1코어에서 역전), 프로덕션(`VM.Standard.E2.1.Micro`, 1 OCPU) 코어 수를 확인하지 못했다.
따라서 이미 사용자 지시로 확정된 TASK-005(≤140종목, 경계 명확) 외에 200~1200종목 규모
지점을 추가 전환하는 것은 근거가 부족하다. 3·4번은 그와 별개로 구조적 차단 요인
(사전 필터 / 조기 종료)이 있어 단순 전환 자체가 불가하다.

**이월 과제**: 프로덕션 코어 수 확인(`nproc`) → 4코어 이상이면 5번(bollinger)과 7번
(price_5d_trend)의 배치 전환 + `_MAX_PRICE_FETCH_CANDIDATES` 상향(Option A)을 묶어
별도 SPEC으로 재검토.

### TASK-007: 무회귀 검증

- 대상: `backend/tests/test_spec_ai_092.py`, `test_spec_ai_094.py`, `test_spec_ai_096.py`,
  `test_spec_ai_097.py`(기존), 신규 `test_spec_ai_102.py`.
- `fetch_current_prices_batch()` / `surge_trading_service.py` / 8개 탐지기 스코어링 diff 0
  확인(REQ-AI102-005).
- 전체 회귀 스위트 무회귀 확인: `cd backend && uv run pytest tests/ -m "not slow"`.

추적 REQ/AC: REQ-AI102-001~005 전체 / AC-102-001~010

## C. 검증 계획

- `uv run ruff check .` / `uv run mypy app/` — 정적 분석 무회귀.
- `uv run python -c "from app.main import app; print('OK')"` — import 안전성.
- TASK-002/003/005 각각 characterization 테스트(전환 전/후 동일 fixture 결과 비교).
- `cd backend && uv run pytest tests/ --tb=short -q -m "not slow"` — 전체 회귀(CLAUDE.local.md
  검증 명령).

## D. 배포/롤백

- 신규 flag 3종(`scan_universe_bridge_pool_b_enabled` 기본 False,
  `scan_universe_bridge_pool_limits["pool_b"]`, `_MAX_PRICE_FETCH_CANDIDATES` 신규 값)은
  모두 단일 값 변경으로 롤백 가능 — 데이터 손실 없음, 마이그레이션 없음.
- TASK-002(함수 분리)·TASK-005(Pool B 배치 전환)는 공개 인터페이스·산출값이 characterization
  테스트로 보증된 동등 리팩터이므로, 문제 발생 시 해당 커밋만 `git revert`하면 즉시 이전
  동작으로 복원된다.
- 롤백 트리거: TASK-003 배포 후 pool_b bridge 후보의 실제 정밀도(precision)가 앙상블
  평균보다 유의하게 낮게 관측되거나, `generate_scan_universe_bridge_candidates()` 예외율이
  상승하면 `scan_universe_bridge_pool_b_enabled`를 False로 되돌린다(SPEC-AI-092 D4가 이미
  확립한 관측 절차와 동일 패턴 — 신규 계측 인프라 불필요).

## E. 리스크

- **TASK-001 실측이 스테이징/프로덕션 환경 차이로 로컬 fixture와 다르게 나올 위험**: 로컬
  실측은 방향성 판단(안전권 vs 위험권)에만 쓰고, 최종 값 확정은 Implementation Kickoff
  Approval에서 사용자와 함께 보수적으로 결정한다.
- **pool_b bridge 신규 HTTP 호출이 스캔 사이클 소요시간을 늘릴 위험**: `scan_universe_bridge_max_candidates`
  전체 상한이 이미 존재하고(REQ-AI102-002 필수 조건), 이번 SPEC에서 추가하는 pool_b 대상도
  이 상한 안에서만 발생하므로 상한 없는 확장은 구조적으로 불가능.
- **TASK-002 함수 분리가 예기치 않게 호출 순서에 의존하는 숨은 부작용을 깰 위험**(예:
  로깅 순서, `persist_pool_counts`/`persist_universe_members` 호출 시점): 분리 후에도
  `build_scan_universe()` wrapper가 기존과 동일한 순서로 두 함수를 호출하도록 강제하고,
  로깅·영속화 호출 지점은 옮기지 않는다(순수 함수 추출, 호출 순서 재배열 아님).
