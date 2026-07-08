# SPEC-AI-073 Acceptance Criteria

Given-When-Then 시나리오와 엣지케이스. 모든 기준은 관찰 가능(테스트 출력/DB 행 상태/로그 문자열/
`journalctl` 출력/마이그레이션 상태)해야 하며, 신호 생성 경로·매수 로직 diff는 0이어야 한다. DB 변경은
마이그레이션 068(FK `ON DELETE` 거동) 한 건뿐이다.

**재현 우선(CLAUDE.md Rule 4)**: AC-073-001의 재현 테스트는 수정 **전**에 작성되어 실패(FK 위반으로
수집 차단)함을 확인한 뒤, 수정 후 통과해야 한다.

---

## AC-073-001 (REQ-001/002) — 정리 실패가 수집을 차단하지 않고, FK 삭제가 성공

**Given** `disclosures`에 5일 컷오프를 초과한 공시 D가 있고, `fund_signals` 행 S가 `disclosure_id = D.id`
로 D를 참조하며, `fetch_dart_disclosures`는 mock으로 신규 공시 N건을 반환하도록 설정된 상태

**When** `_run_dart_crawl()`(또는 그 내부 정리+수집 시퀀스)가 실행되면

**Then**:
- (수정 전, 재현) 현행 코드에서는 `_cleanup_old_disclosures`의 DELETE가 `IntegrityError`/
  `ForeignKeyViolation`을 일으키고 `fetch_dart_disclosures`(mock)가 **호출되지 않는다** — 이 테스트가
  수정 전 실패/에러함을 확인한다.
- (수정 후) `fetch_dart_disclosures`(mock)가 **호출되어 N건 수집**이 진행된다(REQ-001 격리).
- FK 개정 후 공시 D 삭제가 성공하고, 참조 신호 S는 **삭제되지 않으며** `S.disclosure_id`가 **NULL**로
  설정된다(REQ-002 SET NULL, CASCADE 아님).
- 신호 생성 경로(`build_scan_universe`/`gather_surge_candidates`/`compute_ensemble_score`) diff 0.

---

## AC-073-002 (REQ-002) — 마이그레이션 068 멱등/가역 + 제약 거동

**Given** Alembic head가 `067_surge_detector_contribution`인 상태

**When** 마이그레이션 068을 upgrade 후 downgrade 후 재-upgrade 하면

**Then**:
- upgrade 후 `fund_signals_disclosure_id_fkey`의 `confdeltype`(PostgreSQL 카탈로그)이 `SET NULL`
  (`n`)로 조회된다.
- downgrade 후 제약이 `NO ACTION`(`a`)로 원복된다.
- 재-upgrade가 오류 없이 다시 `SET NULL`을 적용한다(멱등/가역).
- 마이그레이션은 어떤 `fund_signals`/`disclosures` **데이터 행도 삭제/이동하지 않는다**(제약 거동
  변경만).

---

## AC-073-003 (REQ-003) — app.services 로거 ERROR/CRITICAL 캡처

**Given** 로깅 설정이 적용된 앱 컨텍스트에서 `app.services.scheduler` 로거가 존재하는 상태

**When** 해당 로거로 ERROR 및 CRITICAL 레코드를 발생시키면(예: `_run_dart_crawl` 실패 경로의
`logger.error`, watchdog의 `logger.critical`)

**Then**:
- `caplog`(pytest)로 `app.services.scheduler` 및 `app.services.dart_crawler`의 ERROR/CRITICAL 레코드가
  **캡처된다**(수정 전 미캡처였다면 수정 후 캡처로 전환).
- 프로세스 stdout(=journald 캡처)에도 해당 레코드가 도달함이 확인된다 — 순수 `caplog`가 propagate에
  의존해 참 원인을 가릴 수 있으므로, 최소 1개 시나리오는 실제 핸들러 출력(예: `capsys`/StreamHandler
  캡처)으로 검증한다.
- 기존 억제(`yfinance` 로거 CRITICAL 레벨, `main.py:42`)는 되돌아가지 않는다(회귀 없음).

---

## AC-073-004 (REQ-004) — 배포 후 수집 재개 + Pool A 비영 (배포 검증)

**Given** 수정과 마이그레이션 068이 프로덕션에 배포된 상태

**When** 다음 스케줄된 `_run_dart_crawl`(또는 watchdog 복구 크롤)이 실행되면

**Then** (배포 후 수동/관찰 검증, 단위 테스트로 대체 불가):
- `alembic current`가 068을 head로 보고한다.
- `journalctl -u newshive`에 `DART crawl completed: <count> new disclosures` 성공 로그가 나타난다
  (count > 0, 공시 유입 거래일 기준).
- 이후 급등 스캔 사이클 로그/유니버스 풀 카운트에서 Pool A(공시 기반 후보) count > 0 이 관측된다.
- Prometheus `newshive_job_failures_total{job_id="_run_dart_crawl"}`가 더 이상 증가하지 않는다.

---

## AC-073-005 (REQ-005) — watchdog 복구 경로 회귀 가드

**Given** DART stale watchdog `_check_dart_health`가 stale(마지막 수집 > 2h)을 감지하는 상태

**When** watchdog가 `_run_dart_crawl` 복구 스레드를 트리거하면

**Then**:
- 복구 크롤이 REQ-001 격리·REQ-002 FK 혜택을 받아 정리 실패로 중단되지 않고 수집을 진행한다.
- watchdog의 `logger.critical` DART stale 경보가 `journalctl`에 나타난다(REQ-003 회귀 가드와 결합).
- `_check_dart_health`의 2시간 임계·Telegram 알림 로직 diff 0(무변경 확인).

---

## 엣지케이스

- **EC-1 정리 성공·수집 실패**: 정리는 성공했으나 `fetch_dart_disclosures`가 네트워크 오류로 실패하면,
  격리에 의해 수집 실패만 로그·재시도되고 정리 결과에는 영향이 없다. 함수가 stuck되지 않는다(finally
  rollback/close 관례 유지).
- **EC-2 참조 없는 오래된 공시**: `fund_signals`가 참조하지 않는 5일 초과 공시는 종전대로 정상 삭제된다
  (FK 개정이 참조 있는 경우에만 SET NULL로 작동, 참조 없는 삭제는 무영향).
- **EC-3 NULL disclosure_id 하류 소비**: `disclosure_id`가 NULL이 된 신호를 읽는 코드가 NULL을 안전히
  처리한다(이미 `nullable=True`). NULL로 인한 AttributeError/조인 실패가 없음을 확인.
- **EC-4 로거 수정 후 볼륨**: 로거 가시성 복구로 그동안 억눌린 ERROR 로그가 일시 대량 표출될 수 있으나,
  이는 회귀가 아니라 은폐 해소다. INFO/DEBUG 볼륨은 계약 대상 아님.
- **EC-5 마이그레이션 재적용**: 이미 068이 적용된 DB에 재-upgrade가 오류 없이 no-op/재적용 되어야 한다
  (부팅 시 `_run_migrations()` 반복 호출 안전).
- **EC-6 병렬 테스트(`-n 4`)**: FK/로거 테스트가 pytest-xdist 4워커 환경에서도 결정적으로 통과한다
  (공유 파일/전역 로깅 상태 오염 주의 — 로거 테스트는 워커 격리 또는 fixture로 상태 복원).

---

## Definition of Done

- [ ] **재현 우선**: FK 위반으로 수집이 차단되는 현행 상태를 재현하는 실패 테스트가 수정 **전** 작성·
      실패 확인됨(AC-073-001, Rule 4).
- [ ] 정리/수집이 독립 격리되어 정리 실패가 수집을 막지 않음(AC-073-001, REQ-001).
- [ ] `fund_signals.disclosure_id` FK가 `ON DELETE SET NULL`로 개정되고 참조 신호가 보존됨
      (AC-073-001/002, REQ-002, CASCADE 아님).
- [ ] 마이그레이션 068이 멱등·가역이며 데이터 무손상(AC-073-002, EC-5).
- [ ] `app.services.scheduler`/`dart_crawler`(및 `app.services.*`) ERROR/CRITICAL이 `caplog` 및 실제
      핸들러 출력으로 캡처됨(AC-073-003, REQ-003).
- [ ] watchdog 복구 경로가 격리·FK 혜택을 받고 CRITICAL 경보가 가시화됨(AC-073-005, REQ-005).
- [ ] 배포 검증: 다음 크론에서 수집 성공·Pool A 비영·`journalctl` 가시성·`alembic current`=068
      (AC-073-004, REQ-004).
- [ ] 모든 엣지케이스(EC-1~EC-6) 테스트/확인 커버.
- [ ] 테스트 커버리지 85%+, `ruff check` 무경고, 전체 백엔드 스위트 회귀 없음(`-n 4` 병렬 포함).
- [ ] 신호 생성 경로 diff 0, 탐지기/앙상블 diff 0, 매수 로직 diff 0. DB 변경은 마이그레이션 068 한 건뿐.
- [ ] 아웃티지 기간 과거 데이터 소급 재계산 없음(Exclusion 5 준수).
