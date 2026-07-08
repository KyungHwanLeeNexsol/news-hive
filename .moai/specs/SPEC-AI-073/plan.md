# SPEC-AI-073 Implementation Plan

## 설계 근거 (두 축의 방어 심층 + 관측 계약)

### 축 1 — Bug 1: 정리-선행 차단 제거 (원인 + 증상 이중 방어)

**원인 층 (REQ-002, FK `ON DELETE SET NULL`)**: `_cleanup_old_disclosures`의 벌크 DELETE가 실패하는
직접 원인은 `fund_signals.disclosure_id` FK가 `RESTRICT`(기본)라, 참조되는 오래된 공시를 지울 수 없기
때문이다. FK를 `SET NULL`로 바꾸면 공시 삭제 시 참조 신호의 `disclosure_id`만 NULL이 되고 삭제가
성공한다.

- **왜 SET NULL인가 (CASCADE 아님)**: `fund_signals`는 예측 기록/평가 모집단이다(SPEC-AI-041/043/071).
  `disclosure_id`는 "이 신호를 촉발한 공시" 출처 메타데이터일 뿐이다. 출처 공시가 5일 보존을 벗어나
  삭제될 때 **신호 레코드 자체는 반드시 살아남아야** 평가/백테스트 모집단이 온전하다. CASCADE는 신호를
  삭제해 모집단을 손상시킨다. 따라서 SET NULL이 유일하게 의미상 맞는 선택.
- **마이그레이션 068**: `down_revision = "067_surge_detector_contribution"`. PostgreSQL은 FK의
  `ON DELETE` 거동을 in-place 변경할 수 없으므로 제약 drop→recreate:
  `op.drop_constraint("fund_signals_disclosure_id_fkey", "fund_signals", type_="foreignkey")` →
  `op.create_foreign_key("fund_signals_disclosure_id_fkey", "fund_signals", "disclosures",
  ["disclosure_id"], ["id"], ondelete="SET NULL")`. downgrade는 `ondelete` 없이 원복.
  모델(`fund_signal.py:71-73`)의 `ForeignKey("disclosures.id", ondelete="SET NULL")`도 일치시킨다.

**증상 층 (REQ-001, 정리/수집 격리)**: FK를 고쳐도, 미래에 정리 단계가 **다른 이유로** 실패하면 같은
구조적 결함(정리 선행 → 수집 차단)이 재현될 수 있다. 그러므로 정리와 수집을 **독립 try/except**로
분리한다. 정리 예외는 잡아 로그로 남기고, 세션을 rollback으로 복구한 뒤 수집을 계속 진행한다. 이는
FK 교정과 무관한 영구 2차 방어선이다.

- 순서는 유지하되 격리하거나(정리 try/except → 수집 try/except), 수집을 먼저 두고 정리를 후행 격리해도
  된다. 핵심 계약은 "정리 실패 ⇏ 수집 스킵"(REQ-001). Run 단계에서 최소 변경 형태 선택.

### 축 2 — Bug 2: app.services 로거 가시성 (관측 계약)

`main.py:26-42`의 로깅 설정에서 두 로거(및 `app.services.*`)의 ERROR/CRITICAL이 stdout/journald에
도달하지 못하는 근본 원인을 확정한 뒤 최소 수정한다. research.md §3의 후보 가설(uvicorn
`disable_existing_loggers`, JsonFormatter 예외 삼킴, root 핸들러 덮어쓰기 순서, propagate/레벨 필터)을
순차 검증한다. SPEC 계약은 결과(ERROR/CRITICAL이 `journalctl`에 보임)이지 특정 처방이 아니다.

## 진입점 / 재사용 (신규 자산 최소화)

**변경 대상 파일 (핵심):**
- `backend/app/services/scheduler.py` — `_run_dart_crawl`(`:276-309`) 정리/수집 격리. `_check_dart_health`
  (`:331-375`)는 무변경(복구 대상 함수 견고성에 의존).
- `backend/app/models/fund_signal.py` — `disclosure_id` FK에 `ondelete="SET NULL"`(`:71-73`).
- `backend/alembic/versions/068_*.py` — FK 제약 drop→recreate(신규 마이그레이션 1건).
- `backend/app/main.py` — 로깅 설정(`:26-42`) 근본 원인 수정(최소 변경). 필요 시
  `dart_crawler.py` 로거.

**재사용:** 기존 `_record_job_duration`/finally rollback·close 관례(`:295-306`), `retry_with_backoff`
데코레이터(`:276`), `_run_keyword_matching`(`:309`) 호출부, watchdog 로직 전체.

**신규 자산:** 마이그레이션 068 한 건 외 신규 테이블/모델/스케줄러 잡 없음.

## 마일스톤 (우선순위 기반, 재현 우선)

1. **(ANALYZE)** 현행 `_run_dart_crawl` 순서·FK 정의·로깅 설정 확정(research.md 완료).
2. **(재현 우선 · RED)** 수정 **전** 실패 재현 테스트 작성 후 실패 확인(CLAUDE.md Rule 4):
   - (a) 5일 초과 `disclosures`를 참조하는 `fund_signals`가 있을 때 `_cleanup_old_disclosures` DELETE가
     `IntegrityError`를 유발하고 `_run_dart_crawl`이 `fetch_dart_disclosures`(mock)에 도달하지 못함을
     포착하는 테스트 — 현재 상태에서 실패/에러.
   - (b) `caplog`로 `app.services.scheduler` ERROR 로그 캡처 현행 동작 포착(수정 후 검증용 기준선).
3. **(P0)** 정리/수집 격리(REQ-001) — 정리 예외가 수집을 막지 않도록 try 분리 + 세션 rollback 복구.
4. **(P0)** FK `ON DELETE SET NULL`(REQ-002) — 모델 수정 + 마이그레이션 068(drop→recreate) + 멱등/가역.
5. **(P0)** 로거 가시성 근본 원인 수정(REQ-003) — 원인 확정 후 최소 수정. `caplog` 테스트로 ERROR
   캡처 확정.
6. **(P1)** watchdog 복구 경로 회귀 가드(REQ-005) — 복구 스레드가 격리·FK 혜택을 받음을 테스트로 확정.
7. **(GREEN/IMPROVE 검증)** 재현 테스트 (a) 통과, 수집 진행 확인. 전체 스위트 회귀 없음(`-n 4` 포함).
8. **(배포 검증, REQ-004)** 배포 후 다음 크론에서 수집 성공·Pool A 비영·`journalctl` 가시성 확인.

## 마이그레이션 계획 (068)

- **head 확인**: 현재 head `067_surge_detector_contribution`. `down_revision = "067_surge_detector_contribution"`.
- **upgrade**: `fund_signals_disclosure_id_fkey` drop → `ondelete="SET NULL"`로 recreate.
- **downgrade**: 동 제약 drop → `ondelete` 없이(RESTRICT) recreate.
- **적용 안전성**: `main.py`의 `_run_migrations()`(`:45-57`)가 부팅 시 `command.upgrade(head)` 실행 —
  배포 시 자동 적용. 제약 재생성은 `fund_signals` 전체 스캔이 아니라 카탈로그 변경이라 경량.
- **[HARD]** 마이그레이션은 데이터 삭제/이동을 하지 않는다(제약 거동 변경만). 기존 행 무손상.

## 실패/엣지 처리 설계

- **정리 예외 후 세션 상태**: 벌크 DELETE 실패 시 트랜잭션 abort 상태이므로, 수집 진행 전 `db.rollback()`
  으로 세션을 복구한다(기존 `:299-306` finally 관례와 일관). 복구 없이 수집 쿼리를 실행하면
  `PendingRollbackError` 위험.
- **정리 성공·수집 실패**: 격리했으므로 수집 실패는 그 단계에서 잡아 로그·재시도(기존 `retry_with_backoff`)
  로 처리하고 정리 성공에는 영향 없음.
- **FK SET NULL 이후 NULL disclosure_id 소비처**: `disclosure_id`를 읽는 하류 코드가 NULL을 안전히
  처리하는지 확인(이미 `nullable=True`라 대부분 NULL-safe로 가정하나, ANALYZE에서 참조부 점검).
- **로거 수정 부작용**: 로거 가시성 복구로 그동안 억눌렸던 로그가 대량 표출될 수 있음(특히 반복 실패
  로그). ERROR/CRITICAL만 계약 대상이며 INFO/DEBUG 볼륨 급증은 별도 관찰(범위 밖이나 회귀 아님).
- **yfinance 로거 억제 유지**: `main.py:42` `logging.getLogger("yfinance").setLevel(CRITICAL)`는
  의도된 스팸 억제 — 로거 수정이 이를 되돌리지 않도록 보존.

## 롤아웃 전략

1. **재현 테스트 선행** — 수정 전 실패 확인(Rule 4). 이후 최소 수정.
2. **Deploy Guard 준수** — 15:15~16:10 KST 자동 대기 창(기존 배포 파이프라인 관례).
3. **배포 후 검증(REQ-004)** — (a) `journalctl -u newshive`에 크롤 성공/실패 로그가 나타나는지,
   (b) `fetch_dart_disclosures` count > 0, (c) 다음 급등 스캔 로그에서 Pool A count > 0,
   (d) 마이그레이션 068이 head까지 적용됐는지(`alembic current`) 확인.
4. **watchdog 자연 복구 관찰** — 배포 후 stale이 남아 있으면 watchdog가 2h 내 복구 크롤을 트리거하고,
   그 CRITICAL/성공 로그가 이제 `journalctl`에 보여야 한다.

## 리스크

- **로거 근본 원인 미확정 위험** — uvicorn `disable_existing_loggers`가 원인이면 로거 생성 시점/uvicorn
  설정 순서 조정이 필요할 수 있음. 원인이 다중이면(예: 순서 + 포매터) 순차 검증 필요. 완화: research.md
  §3 가설을 우선순위대로 검증, `caplog` + 실제 stdout 캡처(subprocess/systemd 시뮬)로 이중 확인.
- **FK 개정의 하류 NULL 처리** — `disclosure_id`가 NULL이 되는 신호를 읽는 코드가 NULL 비대응이면
  회귀 가능. 완화: ANALYZE에서 `disclosure_id` 참조부 grep, 이미 `nullable=True`이므로 대부분 안전.
- **격리 형태의 과설계 위험** — 격리를 위해 함수를 과도하게 재구조화하지 않는다(TRUST Readable). 정리
  블록만 별도 try/except로 감싸고 세션 복구하는 최소 변경을 우선.
- **배포 검증의 비결정성** — Pool A 비영은 당일 공시 유무에 의존. 완화: 공시가 실제 유입되는 거래일에
  검증하거나, 최소한 `fetch_dart_disclosures` count > 0 + 크롤 성공 로그로 1차 확인 후 Pool A는 후속
  관찰.
