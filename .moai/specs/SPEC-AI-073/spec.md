---
id: SPEC-AI-073
version: 0.1.0
status: draft
created: 2026-07-08
updated: 2026-07-08
author: MoAI
priority: High
issue_number: 0
---

# SPEC-AI-073: DART 공시 수집 차단 복구 + app.services 로거 가시성 (DART Ingestion Unblock + Logger Visibility)

## HISTORY

- 2026-07-08 (v0.1.0): 최초 작성. 프로덕션 서버 read-only DB/로그 조사로 확정된 두 개의 인과 연쇄된
  프로덕션 버그를 SPEC화.
  - **Bug 1 (데이터 아웃티지, 2026-06-30~)**: `_run_dart_crawl`(`scheduler.py:276-309`)이 같은 try
    블록에서 `_cleanup_old_disclosures(db)`(`:285`)를 `fetch_dart_disclosures(db, days=5)`(`:287`)
    **이전**에 호출한다. 정리 벌크 DELETE가 `fund_signals.disclosure_id` 외래키(`fund_signal.py:71-73`,
    `ON DELETE` 미지정 = RESTRICT) 때문에 5일 초과 참조 공시 삭제 시 `ForeignKeyViolation`으로 실패 →
    함수 전체 abort → **수집이 아예 실행되지 못함**. 현재 프로덕션에 차단 유발 `fund_signals` 161행,
    이 행들은 스스로 늙어 사라지지 않아 **자가 회복 불가**. Prometheus `newshive_job_failures_total
    {job_id="_run_dart_crawl"}` = 28(84 = 28×3 재시도) 전량 실패. 격리 테스트에서 수집 로직 자체는
    정상(대기 공시 1420건). 하류: Pool A = 0/일, 공시 의존 탐지기 4종(`immediate_disclosure`/
    `disclosure_pattern`/`insider_purchase`/`news_delayed`) 전부 0 신호. `:294`의 `raise`로 try 밖
    `:309` `_run_keyword_matching()`(SPEC-FOLLOW-001)도 동반 정지. watchdog 복구
    (`_check_dart_health:370` → 스레드 `_run_dart_crawl`)도 같은 FK 위반으로 무력화.
  - **Bug 2 (관측 불가, 8일+)**: `app.services.scheduler`/`app.services.dart_crawler` 로거 출력이
    ERROR/CRITICAL을 포함해 어떤 레벨에서도 `journalctl`/stdout에 도달하지 않는다. `main.py:26-42`
    로깅 설정(pythonjsonlogger JSON + StreamHandler, root 핸들러 덮어쓰기). 기존 메모 "INFO 미표시"
    보다 범위가 넓음 확인 — Bug 1의 `logger.error`도, watchdog의 `logger.critical` DART 경보도 전혀
    표면화되지 않아 8일간 무증상 방치. Bug 2가 Bug 1을 은폐했으므로 하나의 인시던트로 함께 다룬다.
  - **선택 접근 (방어 심층)**: Bug 1은 FK 교정(`ON DELETE SET NULL`, 마이그레이션 068)과 정리/수집
    try 격리 **둘 다**; Bug 2는 근본 원인 확정 후 최소 수정으로 `app.services.*` ERROR/CRITICAL을
    기존 로깅/알림 파이프라인에 도달시킴.

---

## 선행 SPEC / 관계 (Assumptions & Relationships)

각 항목은 2026-07-08 코드 재확인 결과다. 본 SPEC은 DART 수집 파이프라인의 **운영 신뢰성/가시성**만
복구하며, 탐지기·앙상블·신호 생성·매매 로직을 바꾸지 않는다.

- **SPEC-AI-004 (공시 기반 시그널) — FK 소유 SPEC (본 SPEC이 `ON DELETE` 거동만 개정)**:
  `fund_signals.disclosure_id` FK는 AI-004(`fund_signal.py:69` 주석)에서 도입됐다. 본 SPEC은 컬럼/
  관계 의미를 바꾸지 않고 오직 `ON DELETE` 거동을 `SET NULL`로 개정한다(신호 레코드는 보존, 매달린
  참조만 NULL).
- **SPEC-AI-041/043/071 (예측 기록·평가 모집단) — 보존이 FK 선택의 근거**: `fund_signals`는 예측
  기록/평가 모집단이다. FK를 CASCADE로 하면 출처 공시 노후화 시 신호 레코드가 삭제되어 이 모집단이
  손상된다. 따라서 **SET NULL**을 택해 평가 모집단을 보존한다. 예측 기록 모드(AI-043) 유지, 매수
  로직 diff 0.
- **SPEC-AI-065 (build_scan_universe / Pool A~C) — 입력 복구(로직 무변경)**: Pool A는 당일 공시
  종목으로 구성된다. 본 SPEC은 공시 유입을 복구해 Pool A 입력을 되살릴 뿐, `build_scan_universe`/
  `surge_universe_pool_service.py`의 구성 로직은 변경하지 않는다.
- **SPEC-FOLLOW-001 (공시 후 키워드 매칭) — 동반 복구**: `_run_keyword_matching()`(`:309`)은
  `_run_dart_crawl` try 밖에 있어 크롤 실패 시 함께 정지했다. 크롤 복구 시 자동 재개된다(로직 무변경).
- **DART watchdog / 크래시 알림 (AI-064-era) — CRITICAL 경보 가시성 회귀 가드**: `_check_dart_health`
  (`:331-375`)의 `logger.critical` DART stale 경보는 Bug 2 때문에 표면화되지 못했다. Bug 2 수정으로
  이 경보가 다시 보이는 것이 회귀 가드다. watchdog 로직 자체는 변경하지 않는다.

---

## Environment (환경/전제)

- Backend: Python 3.12+, FastAPI, SQLAlchemy 2.0, APScheduler(BackgroundScheduler, KST 직접 지정),
  PostgreSQL 16, Alembic. 배포: OCI VM 베어메탈 + systemd(`newshive`), 로그는 `journalctl -u newshive`.
- 대상 코드: `backend/app/services/scheduler.py`(`_run_dart_crawl`/`_cleanup_old_disclosures`/
  `_check_dart_health`), `backend/app/models/fund_signal.py`(FK 정의), `backend/app/main.py`(로깅 설정),
  필요 시 `backend/app/services/dart_crawler.py` 로거.
- **현재 Alembic head = `067_surge_detector_contribution`** — FK 개정 마이그레이션은 `068`,
  `down_revision = "067_surge_detector_contribution"`.
- 운영 모드: 예측 기록 전용(실매매 비활성). 자금 리스크 없음. 본 SPEC은 데이터 수집/가시성 복구.
- 데이터 사실: `SurgeActualOutcome`/평가 파이프라인은 `fund_signals` 존재에 의존(FK CASCADE 금지 근거).

---

## Requirements (EARS)

### REQ-AI073-001 (P0, Unwanted Behavior) — 정리 실패가 수집을 차단하지 않도록 격리

**IF** `_cleanup_old_disclosures`가 어떤 이유로든(외래키 위반 포함) 예외를 던지면, **THEN the system
SHALL NOT** 그로 인해 `fetch_dart_disclosures`(실제 공시 수집)의 실행을 건너뛰어서는 안 된다.

- 정리 단계와 수집 단계를 **독립 try/except**로 분리(또는 순서를 재배치)하여, 정리 실패가 수집을
  막지 못하게 한다. 정리 예외는 격리해 로그로 남기고, 수집은 계속 진행한다.
- **[HARD]** 이 요구는 FK 교정(REQ-002)과 **독립적인 2차 방어선**이다 — 미래의 다른 정리 실패
  원인에도 수집을 보호해야 하므로, REQ-002만으로 대체하지 않는다(방어 심층).
- 세션 상태 처리: 정리 실패로 트랜잭션이 abort된 경우 수집 진행 전 세션을 복구(rollback)한다
  (기존 `:299-306` finally rollback/close 관례와 일관).

### REQ-AI073-002 (P0, Event-Driven) — `fund_signals.disclosure_id` 외래키 `ON DELETE SET NULL`

**WHEN** 5일 보존 컷오프를 벗어난 `disclosures` 행이 삭제되고 그 행을 참조하는 `fund_signals` 행이
존재하면, **the system SHALL** 참조 `fund_signals` 행을 삭제하지 않고 그 `disclosure_id`를 NULL로
설정하여 삭제가 성공하도록 해야 한다.

- `fund_signals.disclosure_id` FK를 `ON DELETE SET NULL`로 개정한다. Alembic 마이그레이션 068
  (`down_revision = "067_surge_detector_contribution"`)에서 기존 제약 `fund_signals_disclosure_id_fkey`
  를 drop 후 `ondelete="SET NULL"`로 recreate. `fund_signal.py:71-73` 모델 정의도 일치시킨다.
- **[HARD]** `ON DELETE CASCADE`를 사용하지 않는다 — `fund_signals`는 예측 기록/평가 모집단
  (SPEC-AI-041/043/071 의존)이며 신호 레코드는 출처 공시 노후화와 무관하게 보존되어야 한다. CASCADE는
  평가 모집단을 손상시킨다.
- 마이그레이션은 멱등적·가역적(upgrade: SET NULL 재생성, downgrade: NO ACTION 원복)이어야 한다.

### REQ-AI073-003 (P0, Ubiquitous) — app.services 로거 ERROR/CRITICAL 운영 가시성

The system **SHALL** `app.services.scheduler` 및 `app.services.dart_crawler`(및 일반화하여 임의의
`app.services.*`) 로거가 발생시키는 **ERROR 및 CRITICAL** 레벨 레코드를 `journalctl -u newshive`
(=프로세스 stdout)에서 관측 가능하도록 한다.

- Run 단계에서 로거 침묵의 **근본 원인을 확정**한 뒤 최소 수정으로 해소한다(원인 후보는 research.md §3).
  본 요구는 결과 계약이며 특정 처방을 규정하지 않는다.
- 수정 후, watchdog `_check_dart_health`의 `logger.critical` DART stale 경보(`:363`)와 `_run_dart_crawl`
  실패 시 `logger.error`(`:293`)가 `journalctl`에 나타나야 한다(회귀 가드).
- **[HARD]** 새 중앙 로깅 시스템/외부 로깅 백엔드 도입은 하지 않는다 — 기존 로깅 설정
  (`main.py:26-42`) 안에서 ERROR/CRITICAL 도달을 보장한다.

### REQ-AI073-004 (P0, Event-Driven) — 수정 배포 후 수집 재개 + Pool A 비영 검증

**WHEN** 수정이 프로덕션에 배포되고 다음 스케줄된 `_run_dart_crawl`(또는 watchdog 복구)이 실행되면,
**the system SHALL** 공시 수집을 성공적으로 완료하고, 이후 급등 스캔 사이클에서 Pool A(공시 기반
후보)가 다시 비영(non-zero)이 되어야 한다.

- 본 요구는 단위 테스트만으로는 충족되지 않으며 **배포 후 검증 단계**를 포함한다: 배포 후 첫 크롤
  로그에서 (a) `fetch_dart_disclosures`가 신규 공시 count를 반환하는지, (b) `journalctl`에 크롤
  성공 로그가 나타나는지, (c) 다음 급등 스캔에서 Pool A count > 0 인지 확인.
- **[HARD]** 이 검증은 인수 기준(acceptance.md AC-073-004)에 명시되며, 마이그레이션 068이 프로덕션
  head까지 정상 적용됨을 포함한다.

### REQ-AI073-005 (P1, Event-Driven) — watchdog 자동 복구 경로 회귀 가드

**WHEN** DART stale watchdog `_check_dart_health`가 stale을 감지해 `_run_dart_crawl` 복구를 트리거하면,
**the system SHALL** REQ-001/002의 격리·FK 교정 혜택을 그 복구 경로에서도 동일하게 받아 복구 크롤이
정리 실패로 중단되지 않도록 해야 한다.

- watchdog는 `:370`에서 `_run_dart_crawl`을 직접 호출하므로 REQ-001/002 수정이 자동 적용된다. 본
  요구는 "복구 경로가 여전히 정리-선행 차단으로 무력화되지 않는다"는 회귀 가드다.
- **[HARD]** `_check_dart_health` 및 `_send_dart_stale_alert`의 감지 임계(2시간)·알림 로직은 변경하지
  않는다 — 오직 복구 대상 함수(`_run_dart_crawl`)의 견고성에 의존한다.

---

## Exclusions (What NOT to Build) [HARD]

1. **Pool C 구조적 후행성 한계 — 범위 밖.** 커버리지 ~30% 상한을 만드는 Pool C의 backward-looking
   설계는 별도 미래 SPEC에서 다룬다.
2. **Pool B 레버리지/인버스 ETF 오염 — 범위 밖.** Naver 거래량 순위 스크레이프의 지수 파생상품 오염은
   별도 미래 SPEC에서 다룬다.
3. **뉴스/테마 급등 미탐지 — 범위 밖.** 대응 탐지기가 없는 뉴스/테마 급등 누락은 별도 SPEC/제품
   결정 사안이며 버그가 아니다.
4. **5일 보존 정책 자체 변경 금지.** `_cleanup_old_disclosures`는 계속 5일 초과 공시를 삭제한다.
   본 SPEC은 그 삭제가 수집을 막지 못하게 할 뿐, 보존 기간을 바꾸지 않는다.
5. **아웃티지 기간 과거 데이터 소급 재계산 금지.** 2026-06-30~복구일 사이 미유입 공시의 소급
   백필/재평가는 하지 않는다(복구 후 `days=5` 정상 창이 최근 5일을 재수집하는 것은 정상 동작이며
   별도 백필 노력이 아니다). 과거 `surge_prediction_evaluation` 재계산 없음.
6. **탐지기/앙상블/신호 생성 로직 무변경.** `build_scan_universe`, `gather_surge_candidates`,
   `compute_ensemble_score`, 개별 탐지기, `surge_detection.yaml`은 불변.
7. **중앙 로깅/외부 로깅 백엔드 도입 금지.** 기존 `main.py` 로깅 설정 내에서 `app.services.*`
   ERROR/CRITICAL 도달만 보장한다(관측 계약).
8. **매매·포트폴리오 로직 변경 금지.** SPEC-AI-043 예측 기록 모드 유지(매수 로직 diff 0).
9. **watchdog 감지 임계/알림 로직 변경 금지.** `_check_dart_health`의 2시간 임계·Telegram 경보는
   불변(REQ-005는 회귀 가드일 뿐).

---

## Success Criteria

- 정리 실패가 수집을 차단하지 않는다 — 정리/수집이 독립 격리되어, 정리 예외가 있어도
  `fetch_dart_disclosures`가 실행된다(REQ-001).
- `fund_signals.disclosure_id` FK가 `ON DELETE SET NULL`로 개정되고(마이그레이션 068), 5일 초과 참조
  공시 삭제가 신호 레코드를 보존한 채 성공한다(REQ-002).
- `app.services.scheduler`/`dart_crawler`(및 `app.services.*`)의 ERROR/CRITICAL이 `journalctl`에서
  관측 가능하다 — watchdog CRITICAL 경보와 크롤 ERROR 포함(REQ-003).
- 배포 후 다음 크론에서 공시 수집이 성공하고 Pool A가 다시 비영이 됨이 배포 검증으로 확인된다(REQ-004).
- watchdog 복구 경로가 동일 혜택으로 정리 차단 없이 동작한다(REQ-005).
- **재현 우선**(CLAUDE.md Rule 4): FK 위반으로 수집이 차단되는 현행 상태를 재현하는 실패 테스트가
  수정 **전에** 작성·확인되고 수정 후 통과한다. `caplog`로 대상 로거 ERROR 캡처가 검증된다.
- 신규/변경 로직 테스트 커버리지 85%+, `ruff` 무경고, 전체 백엔드 스위트 회귀 없음(`-n 4` 병렬 포함).
- 신호 생성 경로 diff 0, 탐지기/앙상블 diff 0, 매수 로직 diff 0. DB 변경은 마이그레이션 068 한 건
  (FK `ON DELETE` 거동)뿐.

---

## MX Tag 대상 (Run 단계 식별)

- `_run_dart_crawl`(`scheduler.py:276`) — 다수 스케줄러 진입점 + watchdog에서 호출되는 고 fan_in
  경계. 정리/수집 격리 계약을 `@MX:ANCHOR`(+`@MX:REASON`)로 고정.
- `main.py:26-42` 로깅 설정 블록 — 운영 가시성 불변식. 원인 확정 후 `@MX:NOTE`로 의도/제약 기록.
