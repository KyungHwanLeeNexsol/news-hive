---
id: SPEC-AI-117
title: "급등예측 파이프라인 신뢰성(Tier 0) — 진행 상황"
version: "0.1.0"
status: in-progress
created: 2026-08-21
updated: 2026-08-21
author: Nexsol
priority: High
phase: "backend surge-detection v0.1.0"
module: "backend/app/services"
lifecycle: spec-anchored
tags: "surge-detection, reliability, backend"
tier: M
related_specs: [SPEC-AI-082, SPEC-AI-096, SPEC-AI-063, SPEC-AI-074, SPEC-AI-092, SPEC-AI-109, SPEC-AI-115]
---

# SPEC-AI-117 progress.md

## §E.1 Plan-phase Audit-Ready Signal

plan_status: audit-ready
plan_complete_at: 2026-08-21

_plan-phase 산출물(spec.md/plan.md/acceptance.md/progress.md) 작성 완료. plan-auditor
검토 대기 중._

## §E.2 Run-phase Evidence

### M1 — gather-timeout diff 배포 (REQ-AI117-001 / AC-AI117-001)

- 커밋: `73f94e5` `fix(SPEC-AI-117): M1 gather-timeout 40분 완화 배포`
- diff 내용: `_GATHER_TIMEOUT_S` 1200→2400 + 성공/타임아웃/예외 3개 경로
  `time.monotonic()` 소요시간 로깅. 세션이 `git diff HEAD`로 확인한 그대로
  재작성 없이 커밋(REQ-AI117-001 필수 조건 충족).
- 부수 수정: `tests/test_surge_ai083_intraday_rescan.py::TestCommonInvariants::test_gather_timeout_constant_unchanged`
  불변성 가드를 1200→2400으로 갱신(SPEC-AI-082→SPEC-AI-117 값 소유권 이전
  명시). 이 갱신 없이는 REQ-AI117-006 전체 회귀가 실패한다.
- Push: `git push origin main` 결과는 §E.3에 기록(배포 확인은 커밋 직후
  진행 예정).

- Push: `git push origin main` → `70e56db..ec015d6 main -> main` (커밋
  `73f94e5`, `ec015d6` 모두 반영).
- CI/CD 자동배포(`.github/workflows/ci.yml` deploy job, backend 경로 변경 →
  backend-test + backend-lint 통과 후 `scripts/deploy.sh` 실행) 확인:
  - 서버 `git log -1 --format='%h'` → `ec015d6` (2026-08-21 02:44:22 UTC 확인,
    push 후 자동 배포 완료).
  - 서버 파일 `grep -n '_GATHER_TIMEOUT_S' app/services/fund_manager.py` →
    `66:_GATHER_TIMEOUT_S: float = 2400  # 40분 (...)` — 값 로드 확인.
  - `systemctl show newshive -p ActiveState -p SubState -p
    ExecMainStartTimestamp -p NRestarts` → `NRestarts=0`,
    `ExecMainStartTimestamp=Fri 2026-08-21 02:46:04 UTC`, `ActiveState=active`,
    `SubState=running` — 크래시루프 없이 단일 재기동 확인.

| AC | Status | Verification Command | Actual Output |
|----|--------|----------------------|----------------|
| AC-AI117-001 | PASS | `git log -1 --format='%h'` (서버) + `grep _GATHER_TIMEOUT_S` (서버) + `systemctl show newshive` | 서버 `ec015d6`, `_GATHER_TIMEOUT_S=2400`, `NRestarts=0`/`active`/`running` |

### M2 — Item 2 진단 (REQ-AI117-002 / AC-AI117-002a/002b)

**AC-AI117-002a — gate_drop_observation_enabled 서버 실측값 확인**

- 정적 파일 확인: 서버 `app/surge_config/surge_detection.yaml:321` → `gate_drop_observation_enabled: true`.
- 서버 `app/surge_config/surge_detection.auto.yaml`(자동개선 루프 전용,
  레포 미포함) 원본:
  ```
  # surge_detection.auto.yaml — SPEC-AI-069 REQ-002 리셋 완료 (auto_improve_enabled=false)
  # base surge_detection.yaml이 유일 authoritative 소스. 특정 키 오버라이드 없음.
  ```
  → `gate_drop_observation_enabled` 키 오버라이드 없음(drift 없음).
- 앱의 실제 `get_surge_config()` 로더로 실측(서버 `venv/bin/python`,
  `app.surge_config.surge_settings.get_surge_config()`):
  ```
  gate_drop_observation_enabled = True
  ```
- **결론: `true`로 확인됨. 정합화(재조정) 불필요 — REQ-AI117-002 필수 조건의
  "false 확인 시 정합화" 하위 조건은 발동하지 않는다.**

**AC-AI117-002b — surge_gate_drop_observations 원본 조회**

쿼리: `trading_date='2026-08-20' AND stock_code IN ('049470','462860')`
(서버 DB, `SurgeGateDropObservation` ORM 직접 조회, 서버 `venv/bin/python`)

- 참고: 2026-08-20 전체 `gate_drop_observations` 행 수 26,353건(계측
  자체는 활발히 동작 중). 그날 관측된 distinct `gate_name`: `below_regime_threshold`,
  `sector_contagion_gate`, `evaluation_excluded_near_limit_carry`,
  `evaluation_excluded_same_day`, `price_fetch_truncation`,
  `strong_bypass_failed`, `immediate_bypass_failed`.

| stock_code | 결과 | gate_name | score_before_drop | market_regime | detector_set_json | reason_metadata_json |
|---|---|---|---|---|---|---|
| 462860 (더즌) | **있음(1건)** | `price_fetch_truncation` | 0.095 | BEAR | `["theme_cluster"]` | `{"entry_pool": "existing", "max_price_fetch_candidates": 50, "original_count": 1416, "pool_member_exempt_count": 116, "pre_truncation_rank": 859}` |
| 049470 (비트플래닛) | **없음(0건)** | — | — | — | — | — |

- 049470 추가 확인: `stock_code LIKE '%049470%'`로 **전체 기간** 조회 —
  0건(포맷 불일치 가능성 배제, 이 종목은 이 테이블에 단 한 번도 기록된 적이
  없다).
- **462860 해석(원본 사실만, 가공 없음)**: `pre_truncation_rank=859`가
  `max_price_fetch_candidates=50`를 크게 초과 — 이 세션의 spec.md §Context
  Item 2 가설(가격조회 사전절단이 `entry_pool="existing"`인 순수 신호
  부족 후보를 bypass 게이트 도달 전에 제거한다)과 정확히 일치하는 드롭
  기록이 확인됐다. `original_count=1416`은 그날 `merged` 크기가
  `_MAX_PRICE_FETCH_CANDIDATES`(50)를 28배 초과했음을 의미한다.
- **049470 해석(원본 사실만)**: instrumented 게이트(위 7개) 중 어느 것으로도
  드롭이 기록되지 않았다 — 이는 (a) 애초에 `merged`에 진입하지 못했거나
  (`build_scan_universe()`/`detect_volume_breakout()` 자체 유니버스에서
  발견되지 않음), (b) instrumented되지 않은 다른 경로(예: `_pre_score`
  가중합 계산 이전 단계, 또는 콜백이 없는 게이트)에서 사라졌을 가능성을
  시사한다. 이 세션은 그 이상의 근본원인을 추가로 규명하지 않는다(REQ-AI117-002
  범위 밖 — spec.md §Non-Goals "알고리즘/임계값 튜닝" 경계 유지).

**REQ-AI117-003 게이트 판정**: AC-AI117-002b가 `gate_name='price_fetch_truncation'`
드롭을 1건(462860) 확인 → **분기 A, REQ-AI117-003 시행**(acceptance.md
시나리오 2).

### M3 — 조건부: 절단 면제 확장 (REQ-AI117-003 / AC-AI117-003)

M2 진단(462860 `price_fetch_truncation` 드롭 1건 확인)이 REQ-AI117-003
시행 조건을 충족해 시행했다.

- 변경 파일: `app/services/surge_detector.py`
  - `_apply_price_fetch_truncation()`에 키워드 전용 파라미터
    `volume_breakout_bypass_threshold: float | None = None` 추가(기본값
    `None`이면 신규 조건이 비활성화되어 SPEC-AI-096 기존 동작과 완전히
    동일 — 무회귀).
  - 면제 조건: `entry_pool != "existing" OR (volume_breakout_bypass_threshold
    is not None AND candidate.volume_breakout_score >=
    volume_breakout_bypass_threshold)`.
  - 호출부(`gather_surge_candidates()`)에서
    `volume_breakout_bypass_threshold=config.volume_breakout.volume_breakout_bypass_threshold`
    (SPEC-AI-063 기존 값 재사용, 새 임계값 도입 없음) 전달.
  - `_MAX_PRICE_FETCH_CANDIDATES`(50) 숫자, `_pre_score()` 가중합 산출식,
    `_POOL_MEMBER_WARNING_THRESHOLD`(200) 경고 로직, pool_a/b/c/d 소속
    면제 로직(SPEC-AI-096) 자체는 무변경(REQ-AI117-003 필수 조건 전항목
    충족).
- 신규 테스트: `tests/test_spec_ai_117.py`
  `TestPriceFetchTruncationVolumeBreakoutBypassExemption` 4건 — M2 실측치
  (462860, volume_breakout_score=0.50, bypass_threshold=0.30) 그대로 사용해
  (a) 미지정 시 절단(무회귀 기준선), (b) 임계값 충족 시 생존, (c) 임계값
  미달 시 여전히 절단, (d) pool 소속 면제 로직 무변경을 각각 검증.

| AC | Status | Verification Command | Actual Output |
|----|--------|----------------------|----------------|
| AC-AI117-003 | PASS | `uv run pytest tests/test_spec_ai_117.py tests/test_spec_ai_096.py tests/test_spec_ai_115.py -v` | 28 passed |

### M4 — 조건부: Pool B 실패 경보 승격 (REQ-AI117-004 / AC-AI117-004) — 시행하지 않음

로그 인코딩 발견: 서버 로그는 pythonjsonlogger `ensure_ascii` 이스케이프로
Korean 텍스트를 `\uXXXX`로 기록한다(예: `[스캔유니버스]` → `[스캔유니버스]`).
Korean 리터럴 문자열로 grep 시 항상 0건이 반환되므로(오탐), ASCII 하위
문자열("Pool B")로 검색해 원본 로그를 직접 육안 확인했다.

- 조회: `journalctl -u newshive --since '2026-08-20 00:00:00' --until
  '2026-08-20 12:00:00' | grep 'Pool B'` (UTC 00:00~12:00 = KST 09:00~21:00,
  실질 장중 09:00~16:11 KST까지 커버).
- **결과: 해당 구간에 `Pool B 조회 실패` 라인 0건.** Pool B 소싱은 그날
  09:26~16:11 KST(UTC 00:26~07:11)에 걸쳐 6회 관측되었고 매회 정상
  카운트를 반환했다(원본 로그 발췌, 시각순):
  - 00:26 `[스캔유니버스] Pool B stocks 미존재 종목 제외: 제외=59건`
  - 00:30 `[스캔유니버스] Pool B(거래량200%+): 22개`
  - 00:51 `... 26개`
  - 01:24 `... 30개`
  - 01:50 `... 29개`
  - 02:26 `... 30개`
  - 06:38 `... 49개`
  - 07:03 `... 50개`
  - 참고(부가 정보, 원본): 07:01~07:11 KST 구간
    `app.services.surge_evaluation_service` 로그
    `[급등평가] non_scannable 원인 진단 완료 — date=2026-08-20 truncated=2
    absent=43 (Pool B는 사후 재구성 불가로 재판정 대상 제외)` — M2의
    price_fetch_truncation 드롭 확인(462860 1건)과 정합적인 truncated=2
    관측이나, 이 카운트가 정확히 어느 2종목인지는 이 세션에서 추가로
    역추적하지 않는다(REQ-AI117-004 범위 밖).
- **판정: REQ-AI117-004는 시행하지 않는다.** acceptance.md §D Closure
  Gates + REQ-AI117-004 필수 조건("진단 결과 Pool B 실패가 실제로
  관측되지 않으면 이 REQ는 시행하지 않고 spec.md에 그 사실을 기록한다")에
  따라 조건부 AC는 "N/A — 조건 미충족"으로 PASS 간주한다.

| AC | Status | Verification Command | Actual Output |
|----|--------|----------------------|----------------|
| AC-AI117-004 | N/A — 조건 미충족(PASS 간주) | `journalctl -u newshive --since '2026-08-20 00:00:00' --until '2026-08-20 12:00:00' \| grep 'Pool B'` | Pool B 조회 실패 0건, 정상 카운트 6회 관측(22→50) |

### M5 — Item 3 서버측 진단 (REQ-AI117-005 / AC-AI117-005)

**서버 타임존 확정(중요 — 위임 프롬프트 전제 정정)**: `timedatectl` →
`Time zone: Etc/UTC (UTC, +0000)`. 즉 journalctl 타임스탬프는 **UTC이며
KST가 아니다** — 위임 프롬프트의 "2026-08-19 11:26:42(서버 로컬
타임스탬프, TZ 재확인 필요)"는 TZ 미확인 상태의 인용이었다. 이 세션이
직접 조회한 재시작 이벤트는 **UTC 11:26:06 = KST 20:26:06**이다(오전이
아닌 저녁 시각).

**19:15 KST 평가누락감시 잡 실행 로그 조회** (UTC 10:00~10:30 = KST
19:00~19:30):
```
$ journalctl -u newshive --since '2026-08-19 10:00:00' --until '2026-08-19 10:30:00'
-- No entries --
```
→ **이 30분 구간에 로그가 전혀 없다.** `surge_missing_evaluation_check`/
`[급등평가누락감시]` 관련 로그 라인 자체가 존재하지 않는다 — 잡이
실행되지 않았음을 강하게 시사한다.

**정지 시점 역추적**: 마지막 정상 로그 활동은 UTC 09:30:24(KST
18:30:24) — `google_genai.models` AFC 호출 완료 로그. 그 이후 UTC
11:26:06(KST 20:26:06)까지 **약 1시간 56분간 로그가 전혀 없다.** 19:15
KST(UTC 10:15)는 이 무로그 구간(18:30~20:26 KST) 내부에 위치한다 —
프로세스가 이미 응답 불능(메모리 스레싱 추정) 상태였을 가능성이 높다.

**재시작 근본원인 — OOM Kill 확정** (UTC 11:20:00~11:35:00 조회, 원본
발췌):
```
Aug 19 11:26:04 news-hive kernel: systemd-udevd invoked oom-killer: gfp_mask=0x140cca(GFP_HIGHUSER_MOVABLE|__GFP_COMP), order=0, oom_score_adj=-1000
Aug 19 11:26:09 news-hive kernel: oom-kill:constraint=CONSTRAINT_NONE,nodemask=(null),cpuset=systemd-udevd.service,mems_allowed=0,global_oom,task_memcg=/system.slice/newshive.service,task=uvicorn,pid=1306511,uid=1001
Aug 19 11:26:09 news-hive kernel: Out of memory: Killed process 1306511 (uvicorn) total-vm:3392864kB, anon-rss:595900kB, file-rss:392kB, shmem-rss:0kB, UID:1001 pgtables:5452kB oom_score_adj:0
Aug 19 11:26:09 news-hive kernel: oom_reaper: reaped process 1306511 (uvicorn), now anon-rss:168kB, file-rss:244kB, shmem-rss:0kB
Aug 19 11:26:06 news-hive systemd[1]: newshive.service: Main process exited, code=killed, status=9/KILL
Aug 19 11:26:06 news-hive systemd[1]: newshive.service: Failed with result 'signal'.
Aug 19 11:26:06 news-hive systemd[1]: newshive.service: Consumed 13h 39min 35.497s CPU time.
Aug 19 11:26:12 news-hive systemd[1]: newshive.service: Scheduled restart job, restart counter is at 2.
Aug 19 11:26:12 news-hive systemd[1]: Stopped NewsHive FastAPI Backend.
Aug 19 11:26:12 news-hive systemd[1]: Started NewsHive FastAPI Backend.
Aug 19 11:26:35 news-hive uvicorn[1347390]: INFO:     Started server process [1347390]
```
→ **근본원인 확정(추측 아님, 커널 로그 직접 확인): 커널 OOM killer가
uvicorn 프로세스(PID 1306511)를 SIGKILL로 종료.** `restart counter is at
2`로 보아 이 사건 전에도 최소 1회 재시작이 있었다(참고 정보, 추가
역추적 안 함). systemd가 자동 재기동(26초 이내)해 서비스는 즉시
복구됐다.

**DB 재확인(2026-08-21 기준, 이 세션 직접 조회)**: `surge_prediction_evaluation`
테이블 `evaluation_date='2026-08-19'` 행 수 — **0건.** 재시작 후 이틀이
지난 지금도 캐치업되지 않았다(spec.md §Context Item 3의 관측과 일치).

**진단 결론(REQ-AI117-005 필수 조건 (a)/(b) 분기 판정)**: 분기 (b)에
해당한다 — **19:15 KST 잡 자체가 그날 미실행으로 확인됐다**(19:00~19:30
KST 무로그 + 정지 구간 18:30~20:26 KST가 19:15를 포함). 근본원인은
배포/인프라(OOM)이나, "재시작 시 놓친 잡을 스윕하지 않는" 구조적 공백이
동시에 확인된다(스케줄러가 재기동 시 다음 실행시각을 그냥 익일
19:15로 계산할 뿐, 놓친 08-19를 캐치업하지 않음 — APScheduler cron
트리거의 기본 동작).

**이 SPEC 범위 내 조치 여부**: §Non-Goals("2026-08-19 프로세스 재시작의
근본원인 '수정'"은 범위 밖, "진단 완료, 조치 불필요"로 종결 가능)와
plan.md M5("추가 REQ로 확장할지는 진단 후 결정 — 강제하지 않음")에 따라,
**OOM 자체에 대한 코드 수정(메모리 상향 등)은 이 SPEC이 아닌 인프라
변경 절차를 따른다.** "누락 영업일 캐치업 스윕" 구조적 보강은 신규
로직 추가(단순 진단을 넘어선 기능 확장)이므로 이 세션은 이 SPEC 범위
안에서 구현하지 않는다 — Open Questions에 후속 SPEC 후보로 기록한다
(§E.3 참고).

| AC | Status | Verification Command | Actual Output |
|----|--------|----------------------|----------------|
| AC-AI117-005 | PASS(진단 완료) | `journalctl -u newshive --since ... \| grep ...` + `journalctl -k` + DB 재확인 | 19:15 KST 잡 미실행 확인(무로그), OOM 확정(kernel 로그), 08-19 평가 행 0건(08-21 기준) |

## §E.3 Run-phase Audit-Ready Signal

M1(REQ-AI117-001) 완료·배포 검증 완료. M2(REQ-AI117-002) 진단 완료 —
`gate_drop_observation_enabled=true`(drift 없음), 462860 드롭 1건 확인/
049470 드롭 0건. M3(REQ-AI117-003) 시행 완료 — 절단 면제 확장 +
characterization 테스트 4건 PASS, 전체 회귀 2534 passed/0 failed
(`cd backend && uv run pytest tests/ -m "not slow"`), ruff clean.
M4(REQ-AI117-004) 진단 완료 — Pool B 조회 실패 미관측, 시행하지 않음(N/A).
M5(REQ-AI117-005) 진단 완료 — 19:15 KST 잡 미실행 + OOM kill 근본원인
확정, 캐치업 스윕은 이 SPEC 범위 밖으로 판단(Open Questions 후속 SPEC
후보 기록). M6(무회귀 최종 검증 + CHANGELOG 준비)로 진행.

## §E.4 Sync-phase Audit-Ready Signal

_<pending sync-phase>_
