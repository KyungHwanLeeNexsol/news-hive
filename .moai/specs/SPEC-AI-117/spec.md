---
id: SPEC-AI-117
title: "급등예측 파이프라인 신뢰성(Tier 0) — gather 타임아웃 배포·거래량폭발 절단누락 진단·평가누락감시 사각지대 규명"
version: "0.1.0"
status: in-progress
created: 2026-08-21
updated: 2026-08-21
author: Nexsol
priority: High
phase: "backend surge-detection v0.1.0"
module: "backend/app/services"
lifecycle: spec-anchored
tags: "surge-detection, reliability, gather-timeout, gate-drop-observation, volume-breakout, missing-evaluation-monitor, backend"
tier: M
related_specs: [SPEC-AI-082, SPEC-AI-096, SPEC-AI-063, SPEC-AI-074, SPEC-AI-092, SPEC-AI-097, SPEC-AI-102, SPEC-AI-109, SPEC-AI-115]
---

# SPEC-AI-117: 급등예측 파이프라인 신뢰성(Tier 0) — gather 타임아웃 배포·거래량폭발 절단누락 진단·평가누락감시 사각지대 규명

## HISTORY

- 2026-08-21 v0.1.0 (draft): 사용자가 승인한 4단계 개선전략 중 "Tier 0"(순수 신뢰성/인프라
  수정, 탐지 알고리즘 로직은 건드리지 않음)를 이 SPEC으로 작성한다. 위임 프롬프트가 제시한
  3개 항목을 조사하는 과정에서 위임 프롬프트의 전제 2가지가 사실과 다름을 코드로 확인해
  범위를 교정했다:
  - Item 2(거래량폭발 미탐)는 "새 진단 인프라가 필요하다"는 전제였으나, SPEC-AI-115가
    이미 `surge_gate_drop_observations` 테이블 + 게이트별 드롭 관측 콜백을 구현해
    두었고, `app/surge_config/surge_detection.yaml:321`에 `gate_drop_observation_enabled: true`로
    설정되어 있다(레포 기준). 따라서 신규 계측을 만드는 대신 기존 테이블을 조회하는 것이
    올바른 1차 조치다 — §Decisions D2/D3.
  - Item 3(평가누락 무경보)는 "현재 완전 수동 발견 방식"이라는 전제였으나, SPEC-AI-092
    REQ-AI092-006이 이미 평일 19:15 KST에 `surge_missing_evaluation_check` 잡으로
    누락 감지 + 자동복구(`repair_missing_surge_evaluation`) + 텔레그램 경보까지 구현해
    스케줄러에 등록해 두었다(`app/services/scheduler.py:2836-2846`). 실제로 규명해야
    할 질문은 "왜 기존 메커니즘이 2026-08-19에 작동하지 않았는가"이지 "왜 메커니즘이
    없는가"가 아니다 — §Decisions D4.
  - Item 2의 근본원인 가설(가격조회 사전절단이 volume_breakout 단독 발견 후보를
    bypass 게이트 도달 전에 제거한다)은 코드 추적으로 도출했으나 프로덕션 데이터로
    검증하지 못했다(이 세션은 서버 DB/SSH 접근 도구가 없음) — REQ-AI117-002/003을
    "진단 우선, 조건부 수정"으로 설계해 `verification-claim-integrity.md`의
    무근거-결함주장 금지 원칙을 지킨다.
- 2026-08-21 v0.1.0 (draft, iter1 FAIL 수정): plan-auditor 1차 감사(`.moai/reports/plan-audit/SPEC-AI-117-review-1.md`,
  score 0.62)가 MP-2(EARS/GEARS 형식) FAIL을 포함한 4개 결함(D1-D4)을 반환해 다음을
  수정했다:
  - D1(필수, MP-2 firewall): `acceptance.md` §A AC Matrix의 7개 AC 행 전부를 자유
    서술형에서 GEARS 패턴(When/While/Where + **shall**/**shall not**)으로 재작성했다
    — 인수 기준의 의미·조건부 게이팅 로직·§B 시나리오는 변경하지 않았다.
  - D2(citation): §Context Item 2의 `VolumeBreakoutConfig` 인용을 `surge_detector.py:124-149`에서
    실제 정의 위치인 `surge_settings.py:124-149`로 정정했다(파일명 오기, 스코어링
    공식 내용 자체는 이미 정확했음).
  - D3(citation drift): `fund_manager.py` 인용 2건을 작업트리 실측 기준으로 정정했다
    — `_GATHER_TIMEOUT_S`는 `:64`→`:66`, `time.monotonic()` 계측 라인 그룹의 초기화
    라인은 `:1313`→`:1315`(나머지 `1331-1336, 1339-1341, 1344-1345` 구간은 이 세션이
    `sed`/`Read`로 재확인한 결과 이미 정확했다 — plan-auditor가 제시한 대체값
    `1332-1334, 1340-1341`은 이 세션의 직접 확인과 불일치해 채택하지 않았다).
  - D4(lifecycle 정확도): "선행 SPEC" 라벨을 실제 frontmatter `status:` 기준으로
    정정했다 — SPEC-AI-102와 SPEC-AI-115는 `(완료)`가 아니라 실제로
    `status: implemented`이므로 "(구현완료, status: implemented)"로 표기했다.
    SPEC-AI-097/SPEC-AI-109/그 외는 `status: completed`가 실측으로 확인되어
    "(완료)" 표기를 그대로 유지했다 — plan-auditor는 SPEC-AI-109도 `implemented`라고
    주장했으나 이 세션이 `grep`으로 직접 재확인한 결과 SPEC-AI-109는
    `status: completed`가 맞아 그 부분은 정정하지 않았다
    (`verification-claim-integrity.md`의 실측-우선 원칙에 따름).

## 선행 SPEC

- **SPEC-AI-082** (완료): `_GATHER_TIMEOUT_S` 도입 및 20분 캘리브레이션. 본 SPEC의
  Item 1(40분 상향)은 이 SPEC이 확립한 모듈 상수/가드 구조를 그대로 재사용한다.
- **SPEC-AI-096** (완료): `max_scan_universe` 150→250 확대(D1) + `_apply_price_fetch_truncation()`의
  pool 소속 후보(entry_pool in pool_a/b/c/d) 절단 면제(D2, REQ-AI096-005). Item 2의
  Context/가설이 정확히 이 절단 로직을 재추적한 결과다. 본 SPEC은 REQ-AI096-005의 면제
  조건을 volume_breakout bypass-eligible 후보로 확장할지 여부를 진단 후 조건부로 결정한다
  (§Decisions D2, REQ-AI117-003) — SPEC-AI-096 자체의 로직은 변경하지 않는다.
- **SPEC-AI-063** (완료): `volume_breakout_score` 단독 앙상블 우회(bypass) 임계값 도입
  (`volume_breakout_bypass_threshold=0.30`). Item 2의 미탐 사례는 이 bypass 게이트에
  도달하기 **전에** 후보가 사라졌다는 것이 이 세션의 코드 추적 가설이다.
- **SPEC-AI-074** (완료): Pool B 소싱의 레버리지/인버스 ETF 크라우딩아웃 완화
  (`fetch_volume_leaders_sync(limit=140, max_pages=3)`, `tracked_codes` 교집합 필터).
  Item 2의 "poolB=0" 관측이 이 Pool B 소싱 블록(`surge_detector.py:5650-5731`)의
  실패인지 여부를 REQ-AI117-002가 진단한다.
- **SPEC-AI-097**(완료) **/ SPEC-AI-102**(구현완료, status: implemented): `detect_volume_breakout()`/Pool B
  개별 순차 HTTP 조회를 배치 동시조회(`fetch_stock_price_history_batch_sync`)로 전환. Item 2의
  미탐 원인이 아니다(순차 호출 자체의 성능 문제가 아니라 절단/스코어링 로직 문제라는 것이 이
  세션의 가설) — 명시적으로 재론하지 않는다.
- **SPEC-AI-115**(구현완료, status: implemented): `surge_gate_drop_observations` 테이블 + `build_gate_drop_observation()` +
  `_apply_price_fetch_truncation()`의 `on_drop` 콜백 계측. 본 SPEC Item 2 진단의 핵심
  도구다 — 재사용하며 코드를 변경하지 않는다.
- **SPEC-AI-109** (완료): `repair_missing_surge_evaluation()` — actual outcome 수집과
  평가 실행을 하나의 멱등 절차로 묶은 운영 백필 함수. Item 3 진단이 이 함수의 실제
  거동(같은 날짜 자동복구 시 historical guard가 걸리지 않음)을 전제로 한다.
- **SPEC-AI-092 REQ-AI092-006** (완료): `detect_missing_evaluation_records()` +
  `check_and_alert_missing_evaluation()` + 스케줄러 잡 `surge_missing_evaluation_check`
  (평일 19:15 KST). Item 3의 "신규 모니터링 추가" 요청은 이 기존 메커니즘과 중복이므로
  범위에서 제외한다(§Decisions D4) — 대신 왜 이 메커니즘이 2026-08-19에 실패했는지
  진단한다.

## Context / Problem

### Item 1 — gather_surge_candidates 타임아웃 완화 diff가 미배포 상태로 방치

`backend/app/services/fund_manager.py`에 커밋되지 않은 작업트리 diff가 존재한다(이 세션
`git diff HEAD -- backend/app/services/fund_manager.py`로 직접 확인, 2026-08-21). diff 내용:

1. `_GATHER_TIMEOUT_S`를 `1200`(20분)에서 `2400`(40분)으로 상향(`fund_manager.py:66`).
2. `_gather_surge_candidates()`의 성공/타임아웃/예외 3개 경로 모두에 `time.monotonic()` 기반
   실제 소요시간 로깅 추가(`fund_manager.py:1315, 1331-1336, 1339-1341, 1344-1345`).

diff 자체의 주석이 근본원인을 명시한다: 2026-08-03 SPEC-AI-096이 `max_scan_universe`를
150→250(+67%)로 확대하면서 종목당 순차 HTTP 조회 루프(`_MAX_PRICE_FETCH_CANDIDATES`=50개
한도 내에서 여전히 순차 — SPEC-AI-102 TASK-006 주석, `surge_detector.py:2897-2905`
참조)의 실제 소요 시간도 비례 증가했고, 2026-07-20 기준 20분 캘리브레이션이 무효화되어
2026-08-19~08-20 프로덕션에서 타임아웃이 재발했다(서버 journalctl로 2026-08-19 이후
15회 확인 — 위임 프롬프트 제공 수치, 이 세션은 로그 원본을 재조회하지 않았다
[미검증 인용]). 서버는 현재 커밋 `e2a533e`(2026-08-18)에 머물러 있어 이 diff가 한 번도
배포되지 않았다.

40분 상향은 diff 자체 주석이 명시하듯 **임시 완화**이며, 근본 해법(종목별 HTTP 호출
병렬화)은 diff 작성자가 이미 별도 SPEC으로 명시적으로 분리해 두었다 — 본 SPEC은 그
경계를 유지한다(§Non-Goals).

### Item 2 — volume_breakout 활성 상태에서 명백한 미탐 2건

프로덕션 서버 설정(위임 프롬프트가 이 세션 이전에 직접 확인)은
`volume_breakout.enabled=True`, `volume_breakout.relative_threshold_enabled=True`다.
`surge_prediction_evaluation.miss_analysis_json`(`evaluation_date='2026-08-20'`)의 LLM
분석은 다음 2건을 `root_cause="거래량"`으로 명시한다(위임 프롬프트 제공 — 이 세션은
DB를 재조회하지 않았다):

- 비트플래닛(049470): +29.82%, "18배 이상의 거래량 급증"
- 더즌(462860): +26.05%, "110.62배라는 압도적인 거래량 급증"

`detect_volume_breakout()`의 스코어링 공식(`surge_settings.py:124-149`,
`VolumeBreakoutConfig`)은 `volume_breakout_score = min(ratio / 8.0, 0.50)`이므로 18배/110배
비율 모두 상한 `0.50`으로 즉시 클램프된다 — `volume_breakout_bypass_threshold=0.30`
(`surge_detection.yaml:270`)을 큰 폭으로 초과한다. 즉 **스코어링 공식 자체가 미탐의
원인일 수 없다** — 스코어가 임계값에 도달했다면 SPEC-AI-063 bypass가 `composite_score`를
직접 대체해 통과시켰을 것이다.

이 세션이 코드 추적으로 확인한 사실(가설, 프로덕션 데이터로 미검증):

1. `detect_volume_breakout()`은 자체 유니버스(`fetch_volume_leaders_sync(limit=cfg.max_candidates//2, max_pages=1)`,
   즉 시장별 상위 ~50종목, 단일 페이지)를 사용하며, `build_scan_universe()`의 Pool B
   (별도 200%+ 비율 쿼리, `surge_detector.py:5648-5731`)와 **완전히 독립**이다
   (`surge_detector.py:5214-5240`).
2. `merged` dict에 병합된 후 실행되는 `entry_pool` 태깅(`surge_detector.py:2669-2681`)은
   `build_scan_universe()`가 만든 `_entry_pool_map`에서만 pool_a/b/c/d 값을 가져온다 —
   volume_breakout 자체 유니버스에서 발견됐다는 사실만으로는 pool 태깅이 되지 않는다.
   Pool B(별도 쿼리)에서 **동시에** 잡히지 않으면 `entry_pool`은 기본값 `"existing"`으로
   남는다.
3. `_apply_price_fetch_truncation()`(`surge_detector.py:2345-2420`, SPEC-AI-096
   REQ-AI096-005)은 `entry_pool != "existing"`인 후보만 절단 면제하고, `entry_pool ==
   "existing"`인 후보는 `_pre_score()`(theme 0.19 + combo 0.25 + pattern 0.14 +
   news_delayed 0.11 + **volume_breakout 0.11** + momentum 0.12 + immediate_disclosure 0.08)
   가중합 상위 50개(`_MAX_PRICE_FETCH_CANDIDATES`, 무변경)로만 절단된다. 이 truncation
   호출(`:2890`)은 SPEC-AI-063의 bypass 로직(`:3068-3086`)보다 **먼저** 실행된다.
4. 결론적 가설: 뉴스/공시/테마 신호가 전혀 없는(즉 다른 6개 탐지기 점수가 0에 가까운)
   순수 거래량폭발 단독 후보는 `_pre_score()`에서 `volume_breakout_score(≤0.50) * 0.11
   ≈ 0.055`에 불과해 `merged`가 50개를 초과하는 날 existing 상위 50위 안에 들지 못하고,
   SPEC-AI-063 bypass 게이트에 도달하기 **전에** 조용히 잘려나갈 수 있다 — 단, 이는
   `merged`가 50개를 초과했는지, 두 종목의 `entry_pool`이 실제로 `"existing"`이었는지를
   확인해야만 성립하는 가설이다.

이 가설을 검증할 도구는 이미 존재한다: `_apply_price_fetch_truncation()`은
`on_drop=_observe_gate_drop`(`gate_drop_observation_enabled` 플래그로 게이팅,
`surge_detector.py:2560-2589, 2890-2893`) 콜백으로 드롭 사유를
`surge_gate_drop_observations`(SPEC-AI-115, `app/models/surge_gate_drop_observation.py`)
테이블에 `gate_name="price_fetch_truncation"`으로 영속화한다. 레포 기준
`surge_detection.yaml:321`에 `gate_drop_observation_enabled: true`로 설정되어 있으나,
`surge_settings.py`의 `SurgeDetectionConfig.gate_drop_observation_enabled` 기본값은
`False`(`:738`)이고 `surge_detection.auto.yaml`(자동개선 루프가 패치, 레포 미포함,
서버 전용)이 deep-merge로 덮어쓸 수 있다(`surge_settings.py:1035-1046`) — 서버가 실제로
이 값을 `true`로 로드하고 있는지는 이 세션에서 미확인이다.

별도로, `build_scan_universe()`의 Pool B 소싱 블록(`:5648-5731`) 전체가 단일
`try/except Exception as e: logger.warning(...)`(`:5730-5731`)로 감싸져 있어, HTTP
요청 실패·파싱 실패 등 어떤 예외든 카운트 0으로 조용히 수렴하고 WARNING 로그 한 줄만
남긴다 — 위임 프롬프트가 언급한 "2026-08-20 poolB=0"이 이 실패 경로의 결과인지, 아니면
그날 실제로 200%+ 비율에 도달한 종목이 없었던 것인지 로그 확인 없이는 구분 불가능하다.

### Item 3 — 2026-08-19 평가 레코드 완전 누락, 그러나 기존 감시 메커니즘이 이미 존재

`surge_prediction_evaluation` 테이블에 `evaluation_date='2026-08-19'` 행이 0건이다
(위임 프롬프트가 이 세션 이전에 DB 직접 확인). 서버 journalctl은 2026-08-19 11:26:42
(서버 로컬 타임스탬프, TZ 재확인 필요)경, `_run_surge_verify_predictions` 잡이 1시간
48분 지연됐다는 APScheduler 경고 직후 `"Added job ... to job store"` 로그로 이어진다 —
프로세스 재시작/리로드로 그날 18:38 KST 슬롯이 소실됐음을 시사한다(위임 프롬프트 확인,
이 세션은 로그 원본을 재조회하지 않았다 [미검증 인용]). 재시작의 근본원인(배포/OOM/기타)은
이 세션에서 dmesg sudo/TTY 제약으로 미확정이다.

이 세션이 코드 조사로 확인한 사실 — **위임 프롬프트의 "완전 수동 발견" 전제는 부정확하다**:
`app/services/surge_evaluation_service.py`에 SPEC-AI-092 REQ-AI092-006이 이미 다음을
구현해 두었다:

- `detect_missing_evaluation_records(db, trading_date)`(`:1662-1688`): 당일
  `surge_actual_outcome`/`surge_prediction_evaluation` 레코드 존재 여부를 읽기 전용으로
  감지.
- `check_and_alert_missing_evaluation()`(`:1731-1763`): 감지 후 누락 시
  `_send_missing_evaluation_alert()`로 텔레그램 admin 채널(`TELEGRAM_ADMIN_CHAT_ID`)에
  경보를 발송한다(fail-open — 미설정 시 warning 로그만).
- `repair_missing_surge_evaluation()`(`:1833-1945`, SPEC-AI-109): actual outcome 수집 +
  평가 재실행을 하나의 멱등 절차로 묶는다. `trading_date == today_kst`(당일 실행)일 때는
  `allow_historical_actual_collection` 가드가 걸리지 않는다(`:1875` 조건은
  `trading_date != today_kst`에서만 발동).
- `scheduler.py:2836-2846`: 평일 19:15 KST에 `_run_surge_missing_evaluation_check` 잡으로
  위 3개 함수를 연쇄 호출하도록 이미 등록되어 있다(`verify_predictions` 18:38,
  `backtest_gate` 18:45, `auto_improve` 19:00, `detector_contribution` 19:05 이후
  실행되도록 순서 설계됨, 주석 확인).

즉 2026-08-19 19:15 KST에 이 잡이 정상 실행됐다면 `repair_missing_surge_evaluation()`이
당일 actual outcome을 재수집하고 평가를 생성했어야 한다 — 그런데 이틀 뒤(2026-08-21)에도
해당 날짜 평가 행이 0건이라는 것은 다음 중 하나를 의미한다: (a) 19:15 잡 자체가 그날
실행되지 않았다(11:26 재시작과 별개로 이후 재차 재시작됐거나, 스케줄 자체가 소실됐거나),
(b) 잡은 실행됐으나 `repair_missing_surge_evaluation()`이 actual outcome 수집에 실패해
"actual outcome 여전히 누락 — 평가 생성 스킵" 경로(`:1900-1911`)로 조용히 종료됐다,
(c) 잡·복구 모두 성공했으나 텔레그램 경보만 사용자에게 도달하지 못했다(가능성 낮음 —
행이 여전히 0건이므로 (c)는 배제됨). 이 세 갈래를 구분하려면 서버 journalctl에서 19:15
전후 `[급등평가누락감시]` 로그 라인을 조회해야 하며, 이 세션은 그 조회를 수행하지
않았다.

## Goals

1. 이미 검토를 마친 gather-timeout 완화 diff(fund_manager.py)를 재작성 없이 그대로
   배포한다.
2. SPEC-AI-115가 이미 구축한 게이트-드롭 관측 인프라를 활용해, 활성 상태인
   volume_breakout 탐지기가 명백한 후보를 놓친 근본원인을 **추측이 아닌 데이터로**
   규명하고, 확인된 경우에만 SPEC-AI-096의 절단 면제 범위를 조건부로 확장한다.
3. SPEC-AI-092가 이미 구축한 평가누락 감시·자동복구 메커니즘이 2026-08-19에 왜
   작동하지 않았는지 서버측 로그로 규명하고, 근본원인이 코드 결함으로 확인되는 경우에
   한해(예: 스케줄러 재시작 시 누락 영업일을 놓치는 구조적 공백) 최소한의 보강을 추가한다
   — 중복 메커니즘은 신설하지 않는다.
4. 위 3개 항목 모두 급등 탐지/매매 판정 로직(7개 핵심 탐지기, 앙상블 가중치, quota 배분,
   `existing_codes` 필터)에 영향을 주지 않아야 한다.

## Non-Goals

### Out of Scope — 급등 탐지 알고리즘/임계값 튜닝

- 2026-08-11 사용자 결정(`project_surge_2026_08_11_monitor_vs_fix_decision.md`)에 따라
  2026-08-24까지 알고리즘 비교분석·튜닝은 보류한다. 본 SPEC의 REQ-AI117-003(조건부)이
  변경하는 것은 **절단 로직의 면제 대상 집합**이지 임계값·가중치·탐지기 판정 자체가
  아니다 — 그러나 사용자가 "알고리즘 근접" 우려를 제기하면 이 REQ 자체도 2026-08-24
  이후로 미룰 수 있다(Open Questions 참고).

### Out of Scope — theme_news_carry / catalyst_conviction.comention_theme_enabled

- 위임 프롬프트가 명시적으로 제외한 Tier 1 항목이며, 본 SPEC은 이 플래그들을 건드리지
  않는다.

### Out of Scope — gather_surge_candidates HTTP 호출 병렬화 근본 해법

- diff 자체 주석이 명시한 대로 별도 SPEC이 소유한다. 본 SPEC의 REQ-AI117-001은 이미
  작성된 40분 임시완화 diff를 배포하는 것으로 한정한다.

### Out of Scope — 2026-08-19 프로세스 재시작의 근본원인 "수정"

- REQ-AI117-005는 원인을 **규명**하는 진단 REQ다. 진단 결과가 배포/인프라(예: OOM,
  1회성 배포 트리거)로 확인되면 코드 변경 없이 "진단 완료, 조치 불필요"로 종결한다 —
  인프라 원인에 대한 수정(예: 메모리 상향)은 이 SPEC이 아닌 인프라 변경 절차를 따른다.

### Out of Scope — 신규 알림/모니터링 인프라 신설

- Item 3은 SPEC-AI-092가 이미 구축한 감시·자동복구·텔레그램 경보 메커니즘을 재사용한다.
  별도의 신규 알림 채널이나 감시 테이블을 만들지 않는다.

## Decisions

### D1 — Item 1 diff는 재작성하지 않고 그대로 배포한다

이 세션이 `git diff`로 확인한 diff는 이미 근본원인(SPEC-AI-096의 스캔 유니버스 확대로
인한 캘리브레이션 무효화)을 정확히 주석에 기록하고 있고, 3개 실행 경로(성공/타임아웃/
예외) 모두에 계측을 추가해 향후 재발 시 즉시 진단 가능하도록 설계되어 있다. 새로운
타임아웃 값을 계산하거나 재작성할 근거가 없다 — 40분이라는 값 자체가 "20분 캘리브레이션
+67% 스캔 확대 여유"라는 명시적 근거를 가진다.

기각한 대안: 40분보다 더 큰 값(예: 60분)을 즉시 선택 — diff 작성자가 이미 "여전히 유계로
유지해야 한다(REQ-AI082-003)"는 원칙을 인용했으며, 새 계측 로그가 쌓이기 전에 더 큰 값을
고를 근거 데이터가 없다. 배포 후 관측(Open Questions)으로 판단한다.

### D2 — Item 2는 진단 우선, 조건부 수정 — 절단 면제 확장을 추측만으로 구현하지 않는다

`verification-claim-integrity.md` §1.1 surface 3(결함/부채 주장은 전용 도구로 검증되기
전까지는 가설일 뿐)에 따라, 이 세션이 코드 추적으로 도출한 "가격조회 사전절단이
volume_breakout 단독 후보를 bypass 전에 제거한다"는 가설은 SPEC-AI-115가 이미 구축한
`surge_gate_drop_observations` 테이블 조회로 검증되기 전까지는 결함 확정이 아니다.
REQ-AI117-002(진단)를 REQ-AI117-003(조건부 수정)의 게이트로 설계한다.

기각한 대안: 가설만으로 즉시 `_apply_price_fetch_truncation()`의 면제 조건을 확장 —
위임 프롬프트 자체가 "확인된 가설에만 근거해 수정하라"고 명시했고, 실제로는 merged가
그날 50개를 초과하지 않았거나 두 종목이 다른 게이트에서 사라졌을 가능성을 배제할 수
없다. 근거 없는 코드 변경은 새로운 회귀 위험만 추가한다.

### D3 — 신규 계측 인프라를 만들지 않는다 — SPEC-AI-115 재사용, 설정 drift만 확인

Item 2 진단에 필요한 인프라(게이트별 드롭 사유 영속화)는 이미 프로덕션 코드에 존재한다
(`surge_gate_drop_observations` + `on_drop` 콜백). 유일한 불확실 지점은
`gate_drop_observation_enabled`가 프로덕션에서 실제로 `true`로 로드되는지 여부다
(레포의 `surge_detection.yaml`은 `true`이나 `surge_detection.auto.yaml`이 서버에서
deep-merge로 덮어쓸 수 있음, 이 세션은 서버 파일을 확인하지 못함).

기각한 대안: SPEC-AI-115와 별개로 새로운 진단 로그/테이블을 추가 — 기존 인프라가
정확히 이 목적으로 설계되어 있으므로 중복이며, 유지보수 표면만 늘린다.

### D4 — Item 3은 기존 SPEC-AI-092 메커니즘의 실패 원인만 규명한다 — 신규 알림 인프라를 만들지 않는다

위임 프롬프트의 "현재 완전 수동 발견" 전제는 사실이 아니다(§Context Item 3). 이미
평일 19:15 KST에 감지+자동복구+텔레그램 경보가 동작하도록 배선되어 있다. 규명해야 할
질문은 좁혀진다: 이 메커니즘이 2026-08-19에 (a) 실행되지 않았는지, (b) 실행됐으나
`repair_missing_surge_evaluation()`의 actual-outcome 재수집이 실패해 조용히
`skipped_actual_outcome_missing` 상태로 종료됐는지, 확인이 필요하다.

기각한 대안: 위임 프롬프트가 요청한 대로 "신규 감시 job"이나 "완료 확인 assertion"을
새로 추가 — 이미 존재하는 메커니즘과 거의 동일한 기능을 중복 구현하는 것이며, 실패
원인을 규명하지 않은 채 두 번째 감시 레이어를 추가하는 것은 근본 문제(스케줄러 재시작
시 그날의 잡이 소실될 수 있다는 구조적 공백, 확인되지 않음)를 가리기만 한다.

### D5 — 08-19 재시작 근본원인 규명은 이 세션이 아닌 run-phase 서버 접근에서 수행한다

manager-spec(이 세션)은 SSH/서버 셸 접근 도구가 없다 — 위임 프롬프트가 제공한 사실은
이전 세션(팀 리드)이 직접 조회한 결과다. 정확한 조회 명령을 REQ-AI117-005에 명시하여
run-phase에서 서버 접근이 가능한 컨텍스트가 그대로 실행할 수 있도록 한다.

기각한 대안: 근본원인을 확정하지 않은 채 "재발 방지 조치"를 먼저 설계 — 원인이 배포
트리거(의도된 재시작)인지 OOM(비의도적 장애)인지에 따라 필요한 조치가 완전히 다르다
(전자는 조치 불필요, 후자는 메모리 상향 등 인프라 변경 필요).

## Requirements

### REQ-AI117-001: gather-timeout 완화 diff 배포

When manager-develop가 이 SPEC의 run-phase 첫 마일스톤을 시작하면, the system **shall**
`backend/app/services/fund_manager.py`의 기존 미커밋 diff(`_GATHER_TIMEOUT_S` 1200→2400
+ 성공/타임아웃/예외 3개 경로의 `time.monotonic()` 소요시간 로깅)를 내용 변경 없이
커밋하고 main에 push해야 한다.

필수 조건:

- diff 내용(주석 포함)을 재작성하지 않는다 — 이 세션 `git diff`로 확인한 그대로 커밋한다.
- 커밋 메시지는 `fix(SPEC-AI-117): M1 gather-timeout 40분 완화 배포` 형태의 Conventional
  Commit을 사용한다.
- 배포(서버 재기동) 확인 후, 이후 최소 1거래일 동안 `"gather_surge_candidates 타임아웃"`
  경고 로그 재발 여부를 관찰 대상으로 기록한다(관찰 자체는 이 REQ의 완료 조건이 아님).
- 근본 해법(HTTP 호출 병렬화)은 이 REQ의 범위가 아니다.

### REQ-AI117-002: gate_drop_observation 설정 확인 + volume_breakout 미탐 진단 쿼리

Where 프로덕션 서버의 `SurgeDetectionConfig.gate_drop_observation_enabled` 실제 로드값이
확인되지 않은 상태이면, the system **shall** 서버에서 이 값을 직접 확인하고(관리자
API 또는 `get_surge_config()` 직접 조회), `true`로 확인되는 즉시
`surge_gate_drop_observations` 테이블에서 `trading_date='2026-08-20'` AND
`stock_code IN ('049470','462860')` 조건으로 조회하여 `gate_name='price_fetch_truncation'`
드롭 기록이 존재하는지 확인해야 한다.

필수 조건:

- `gate_drop_observation_enabled`가 서버에서 `false`로 확인되면, 그 원인(auto.yaml
  오버라이드 또는 별도 배포본 drift)을 규명하고 레포 `surge_detection.yaml`의 `true`
  값과 정합화하는 것이 이 REQ의 완료 조건에 포함된다 — 정합화 이후 위 조회를 실행한다.
- 조회 결과(있음/없음/설정 자체가 false여서 데이터 없음)는 REQ-AI117-003의 조건부 시행
  여부를 결정하는 게이트로 사용한다.
- 이 REQ 자체는 진단이 목적이며, 진단 결과를 plan.md/CHANGELOG에 원본 그대로(가공 없이)
  기록해야 한다.

### REQ-AI117-003 (조건부): 가격조회 사전절단 면제 범위를 volume_breakout bypass-eligible 후보로 확장

Where REQ-AI117-002의 진단이 `gate_name='price_fetch_truncation'`으로 두 종목 중 1건
이상이 드롭됐음을 확인하면, the system **shall** `_apply_price_fetch_truncation()`의
절단 면제 조건을 `entry_pool != "existing"`에서 `entry_pool != "existing" OR
candidate.volume_breakout_score >= config.volume_breakout.volume_breakout_bypass_threshold`로
확장해야 한다.

필수 조건:

- REQ-AI117-002 진단이 드롭을 확인하지 못하면(다른 게이트에서 사라졌거나, 애초에
  `merged`에 없었거나, `gate_drop_observation_enabled`가 여전히 false로 데이터 자체가
  없으면) 이 REQ는 **시행하지 않는다** — 대신 새로 규명한 사실을 spec.md HISTORY와
  plan.md에 기록하고 후속 SPEC 필요 여부만 판단한다.
- SPEC-AI-096 REQ-AI096-005/D2("이미 외부 독립 신호를 가진 후보는 순수 앙상블 사전점수만으로
  버리지 않는다")와 동일한 논리를 volume_breakout bypass-eligible 후보에 적용하는 것 —
  새로운 임계값이나 새 탐지기를 추가하지 않는다.
- `_MAX_PRICE_FETCH_CANDIDATES`(50)의 숫자와 `_pre_score()` 가중합 산출식 자체는
  무변경.
- `_POOL_MEMBER_WARNING_THRESHOLD`(200) 경고 로직은 면제 대상 확장 후에도 그대로
  동작해야 한다(무수정 확인 — 면제 대상이 늘면 이 경고가 더 자주 발동할 수 있음을
  인지하되 대응은 관찰 후 판단).
- pool_a/b/c/d 소속 면제 로직(SPEC-AI-096) 자체는 변경하지 않는다 — OR 조건을 추가할
  뿐이다.

### REQ-AI117-004 (조건부): Pool B 소싱 실패 가시성 승격

Where REQ-AI117-002 진단 과정 또는 별도 로그 조회에서 `"[스캔유니버스] Pool B 조회
실패"` 경고가 2026-08-20(또는 근접 거래일)에 실제로 발생했음이 확인되면, the system
**shall** 해당 실패를 WARNING 로그에서 텔레그램 관리자 채널 경보로 승격해야 한다.

필수 조건:

- 기존 `app.services.telegram_service.send_telegram_message` 헬퍼와
  `TELEGRAM_ADMIN_CHAT_ID` fail-open 패턴을 재사용한다(§Decisions D4와 동일하게 신규
  알림 채널을 신설하지 않는다).
- Pool B 소싱 실패는 매매/탐지 로직에 영향 없이 계속 fail-open으로 동작해야 한다 —
  경보만 추가되며 동작(빈 리스트 반환, 스캔 유니버스 계속 진행)은 변경하지 않는다.
- 진단 결과 Pool B 실패가 실제로 관측되지 않으면(해당일에 정상적으로 0건이었을 뿐이면)
  이 REQ는 시행하지 않고 spec.md에 그 사실을 기록한다.

### REQ-AI117-005: 2026-08-19 평가누락 사고 서버측 진단

When run-phase가 서버 접근 가능한 컨텍스트에서 시작되면, the system **shall** 서버
journalctl에서 2026-08-19 19:15 KST(±15분) 구간의 `surge_missing_evaluation_check`/
`[급등평가누락감시]` 잡 실행 로그를 조회하여, SPEC-AI-092의 기존 감지+자동복구
메커니즘이 그날 실행되었는지, 실행되었다면 왜 `surge_prediction_evaluation` 행이
여전히 비어있는지 규명해야 한다.

필수 조건:

- 조회 명령(서버 TZ 재확인 후 UTC 변환 적용): `journalctl -u newshive --since
  '2026-08-19 19:00 KST' --until '2026-08-19 19:30 KST'`, 로그에서
  `"[급등평가누락감시]"` 라인의 존재/부재와 그 내용(`status` dict)을 확인한다.
- 별도로 2026-08-19 11:26:42 전후 프로세스 재시작의 근본원인을 조회한다:
  `journalctl -u newshive --since '2026-08-19 11:00 KST' --until '2026-08-19 12:00
  KST'`, 및 가능하면 `dmesg -T | grep -i 'killed process'`(이전 세션은 sudo/TTY 제약으로
  미완료 — 재시도하거나 대안(예: `journalctl -k`)을 확보한다).
- 진단 결과에 따라: (a) 재시작 근본원인이 배포/인프라이고 19:15 잡 자체는 정상 실행되어
  단지 `actual_outcome` 재수집이 실패했을 뿐이라면, `collect_daily_surge_outcomes()`의
  실패 경로를 추가로 조사해 원인을 기록한다(코드 수정 여부는 그 조사 결과에 따라
  결정 — 이 REQ 자체에서 강제하지 않는다). (b) 19:15 잡 자체가 그날 미실행으로
  확인되면, 스케줄러 재기동 시 "직전 영업일 이후 누락된 평가일자를 스윕하는" 보강을
  이 SPEC 범위 안에서 추가 REQ로 문서화할지 여부를 plan.md에서 결정한다.
- 진단 결과 "1회성 배포 재시작 + 잡 자체는 정상 재등록되어 다음날부터 정상 동작" 같은
  결론이면 "진단 완료, 조치 불필요"로 종결한다 — 강제로 코드 변경을 추가하지 않는다.

### REQ-AI117-006: 무회귀 보장

While 본 SPEC이 적용되는 동안, the system **shall not** 급등 탐지 7개 핵심 탐지기의
판정 로직, 앙상블 가중치, quota 배분(`pool_b/c_min_slots`), `existing_codes` 병합 필터
(SPEC-AI-094), Pool A/B/C/D 소싱 쿼리 조건 자체를 변경해서는 안 된다 — REQ-AI117-003이
조건부로 시행되는 경우에도 변경 대상은 절단 **면제 조건**뿐이며 탐지 판정 자체는
불변이다.

필수 조건:

- 전체 회귀: `cd backend && uv run pytest tests/ -m "not slow"` 통과.
- REQ-AI117-003이 시행되는 경우, `_apply_price_fetch_truncation()`을 직접 겨냥한
  characterization 테스트(면제 없이 절단되던 케이스가 여전히 절단되는지, 새 면제
  조건이 의도한 케이스만 추가로 살리는지)를 포함해야 한다.

## Open Questions

정책 판단(진단 우선 원칙, 신규 인프라 신설 금지, 조건부 REQ 설계)은 §Decisions D1~D5에서
이미 확정했다. 아래는 run-phase/운영 판단으로 남기는 항목만 기록한다.

1. REQ-AI117-001 배포 후 40분 타임아웃이 재발하는지 최소 1~3거래일 관측 — 재발 시
   근본 해법(HTTP 병렬화) SPEC의 우선순위를 재평가한다.
2. REQ-AI117-003(조건부)이 "알고리즘 튜닝"에 해당하는지에 대한 최종 판단 — 이 세션은
   SPEC-AI-096 D2의 기존 논리를 조건 확장하는 것으로 분류했으나(§Non-Goals 참고), 사용자가
   2026-08-24 이전 시행을 원치 않으면 진단(REQ-AI117-002)만 이번 SPEC에서 완료하고
   조건부 수정은 별도 후속 SPEC(2026-08-24 이후)으로 미룰 수 있다.
3. REQ-AI117-005 진단 결과에 따라 필요할 수 있는 "스케줄러 재기동 시 누락 영업일
   catch-up 스윕"의 구체 설계 — 진단이 그 필요성을 확인하기 전까지는 설계하지 않는다.
4. `surge_detection.auto.yaml`의 서버 실측 내용(REQ-AI117-002의 전제) — 이 세션은
   레포에 이 파일이 없어(서버 전용) 실측하지 못했다.
