# SPEC-AI-073 Research — DART 공시 수집 차단 복구 + app.services 로거 가시성

조사 완료일: 2026-07-08. 본 문서는 프로덕션 서버 read-only DB/로그 조사로 이미 확정된 진단을
구조화한 것으로, 재탐색을 목적으로 하지 않는다. 라인 번호는 2026-07-08 기준 재확인 결과다.

---

## 1. 문제 요약 (두 개의 인과 연쇄된 버그)

2026-06-30 이후 DART 공시 수집(`_run_dart_crawl`)이 **매 스케줄 실행마다 100% 실패**하고 있으며,
그 실패가 **어떤 로그에도 나타나지 않아** 8일 넘게 무증상으로 방치되었다.

- **Bug 1 (데이터 아웃티지)**: 30분마다 도는 공시 정리(`_cleanup_old_disclosures`)가 `fund_signals`
  → `disclosures` 외래키 제약(`ON DELETE` 미지정 = NO ACTION/RESTRICT) 때문에 `ForeignKeyViolation`
  으로 실패한다. 이 정리 호출이 **실제 수집(`fetch_dart_disclosures`)보다 먼저** 같은 try 블록에서
  실행되므로, 정리 실패가 함수 전체를 중단시켜 **수집이 아예 실행되지 못한다.**
- **Bug 2 (관측 불가)**: `app.services.scheduler` / `app.services.dart_crawler` 로거의 출력이
  ERROR/CRITICAL을 포함해 **어떤 레벨에서도 `journalctl`/stdout에 도달하지 않는다.** 그 결과 Bug 1의
  `logger.error(...)`도, DART stale watchdog의 `logger.critical(...)` 경보도 운영 가시성에 전혀
  나타나지 않았다.

Bug 2가 Bug 1을 은폐했기 때문에 하나의 인시던트로 함께 다룬다.

---

## 2. Bug 1 — 코드 위치 / 인과 사슬

- **정리 함수**: `_cleanup_old_disclosures(db)` — `backend/app/services/scheduler.py:264-273`.
  `db.query(Disclosure).filter(Disclosure.rcept_dt < cutoff).delete(synchronize_session=False)`
  로 5일 초과 공시를 벌크 DELETE 후 commit.
- **호출 순서 (핵심 버그)**: `_run_dart_crawl()` (`:276-309`) 는 같은 try 블록에서
  - `:285` `_cleanup_old_disclosures(db)` ← **먼저 실행**
  - `:287` `count = asyncio.run(fetch_dart_disclosures(db, days=5))` ← 정리가 실패하면 **도달 못 함**
  - `:292-294` `except Exception as e: logger.error("DART crawl failed: %s", e); raise`
- **외래키 정의**: `backend/app/models/fund_signal.py:71-73`
  `disclosure_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("disclosures.id"), nullable=True)`
  — **`ondelete` 미지정** → PostgreSQL 기본 NO ACTION(RESTRICT). 제약명 `fund_signals_disclosure_id_fkey`.
- **트리거 조건**: `fund_signals` 중 하나라도 5일 컷오프보다 오래된 `disclosures` 행을 참조하면, 그
  행에 대한 DELETE가 `psycopg2.errors.ForeignKeyViolation` 발생 → 트랜잭션 abort → 함수 중단.
  이 참조가 2026-06-29/30경 처음 발생, 현재 프로덕션에 **161개**의 차단 유발 `fund_signals` 행 존재.
- **자가 회복 불가**: 차단을 유발하는 `fund_signals` 행은 스스로 늙어 사라지지 않으므로, 현재 로직
  하에서는 매 실행이 영구히 동일하게 실패한다.

### 실증 증거 (라이브 프로세스, 2026-07-08)

- Prometheus 카운터 `newshive_job_failures_total{job_id="_run_dart_crawl"}` = 28,
  `newshive_job_duration_seconds_count` = 84 = 28 × 3(`@retry_with_backoff(max_attempts=3)`,
  `:276`). 즉 모든 스케줄 호출이 3회 재시도 전부 실패.
- 격리된 롤백 테스트 호출에서 `fetch_dart_disclosures` 자체는 정상 동작 — 수집 대기 중인 신규
  공시 **1420건** 확인. 즉 수집 로직에는 결함이 없고, 오직 정리 선행-차단이 원인.

### 하류 영향 (조용한 저하)

- **Pool A(공시 기반 후보) = 0/일** (2026-06-30 이후): `build_scan_universe`(`surge_detector.py`)/
  `surge_universe_pool_service.py`가 당일 공시 종목으로 구성하는 Pool A가 공시 미유입으로 비어 있음.
- 공시 의존 탐지기 **`immediate_disclosure` / `disclosure_pattern` / `insider_purchase` /
  `news_delayed`** 전부 0 신호 → 앙상블 recall 저하가 원인 불명인 채 누적.
- **부수 차단 (SPEC-FOLLOW-001)**: `:294`의 `raise`가 함수를 빠져나가므로, try 블록 **밖**의
  `:309` `_run_keyword_matching()`(공시 크롤 후 키워드 매칭)도 **도달하지 못한다** → 키워드 매칭도
  06-30 이후 동반 정지.
- **watchdog 복구도 차단**: DART stale watchdog `_check_dart_health`(`:331-375`)가 stale을 감지하면
  `:370`에서 `threading.Thread(target=_run_dart_crawl, ...)`로 직접 재크롤을 시도하지만, 이 스레드도
  **같은 정리-선행 `_run_dart_crawl`을 호출**하므로 동일 FK 위반으로 실패 → 자동 복구 경로 무력화.

---

## 3. Bug 2 — 코드 위치 / 후보 원인

- **로거 정의**: `scheduler.py:14` `logger = logging.getLogger(__name__)` (= `app.services.scheduler`),
  `dart_crawler.py:18` `logger = logging.getLogger(__name__)` (= `app.services.dart_crawler`).
- **로깅 설정**: `backend/app/main.py:26-42`. `pythonjsonlogger.json.JsonFormatter` + `StreamHandler`를
  `logging.root.handlers`에 **덮어쓰기 할당**(`:35 logging.root.handlers = [_json_handler]`),
  `logging.root.setLevel(logging.INFO)`. ImportError 시 `logging.basicConfig(level=INFO)` fallback.
- **기존 인지 (프로젝트 메모리)**: "INFO 로그 미표시(미해결): pythonjsonlogger JSON + StreamHandler
  조합 원인 추정". 본 조사로 범위가 INFO보다 넓음이 확인됨 — 동일 두 로거의 **ERROR/CRITICAL도** 미출력.

### 후보 원인 가설 (Run 단계에서 근본 원인 확정 후 최소 수정)

본 SPEC은 원인을 특정해 처방하지 않는다(WHAT 규정). 다만 Run 단계 진단의 출발점으로 후보를 기록한다:

1. **uvicorn 로깅 재구성 + `disable_existing_loggers`** (최유력): uvicorn이 자체 `LOGGING_CONFIG`로
   로깅을 재구성할 때 기본값이 이미 생성된 로거를 비활성화하는 동작을 포함할 수 있음. `scheduler`/
   `dart_crawler` 로거는 **import 시점(`main.py:21`의 `from app.services.scheduler import ...`)**에
   생성되어 `main.py:26-42`의 root 핸들러 재구성 및 uvicorn 부팅보다 앞설 수 있음 → 사후 비활성화.
2. **핸들러/포매터 예외 삼킴**: `JsonFormatter`가 `%`-스타일 위치 인자(예: `_check_dart_health`의
   `logger.critical("...%.1f...", elapsed_hours)`) 포매팅에서 예외를 던지면 해당 레코드가 조용히 유실.
3. **`logging.root.handlers` 덮어쓰기 순서/중복 인스턴스화**: root 핸들러를 리스트 통째 교체하는
   과정과 uvicorn/gunicorn/systemd 스트림 캡처 사이의 순서 문제, 또는 basicConfig 이전 로거 생성.
4. **핸들러 레벨 필터 / propagate=False**: 특정 지점에서 로거 `propagate`가 꺼졌거나 핸들러 레벨이
   상향되어 하위 로거 레코드가 root 핸들러에 도달하지 못할 가능성.

가설 검증·확정과 수정 방식은 Run(DDD) 단계의 몫이다. SPEC이 규정하는 것은 **결과 계약**: 두 로거
(및 일반화하여 `app.services.*`)의 ERROR/CRITICAL이 `journalctl -u newshive`에 도달할 것.

---

## 4. 선택된 접근 (방어 심층 — 두 축 모두)

Bug 1은 **원인(FK 제약)**과 **증상 증폭(순서/결합)** 두 층위를 가지므로 둘 다 고친다(defense in depth):

1. **FK 관계 교정 — `ON DELETE SET NULL`**: `fund_signals.disclosure_id`에 `ondelete="SET NULL"`
   부여(Alembic 마이그레이션 068, `down_revision = "067_surge_detector_contribution"`, 제약
   drop→recreate). **CASCADE가 아닌 SET NULL을 택하는 이유**: `fund_signals`는 예측 기록(evaluation/
   backtest 모집단)이며 `disclosure_id`는 출처 메타데이터다. 출처 공시가 5일 보존 창을 벗어나면 신호
   레코드 자체는 **살아남아야** 하고(SPEC-AI-041/043/071이 이 모집단에 의존), 단지 매달린 참조만
   NULL로 끊는 것이 의미상 옳다. CASCADE는 신호 레코드를 삭제해 평가 모집단을 손상시킨다.
2. **정리/수집 격리** — `_cleanup_old_disclosures`와 `fetch_dart_disclosures`를 **독립 try/except**로
   분리(또는 순서 재배치)하여, 정리 실패가 어떤 이유로든 수집을 막지 못하게 한다. 이는 FK 교정과
   무관한 미래의 다른 정리 실패에도 수집을 보호하는 2차 방어선이다.

Bug 2는 **근본 원인 확정 후 최소 수정**으로, 두 로거(및 `app.services.*`)의 ERROR/CRITICAL이 기존
로깅/알림 파이프라인에 도달하게 한다. 새 중앙 로깅 시스템 도입은 범위 밖.

---

## 5. 범위 밖 (사용자 명시 결정)

- **Pool C의 구조적 후행성 한계**(커버리지 ~30% 상한) — 별도 미래 SPEC.
- **Pool B의 레버리지/인버스 ETF 오염**(Naver 거래량 순위 스크레이프) — 별도 미래 SPEC.
- **뉴스/테마 급등 미탐지**(대응 탐지기 부재) — 별도 SPEC/제품 결정, 버그 아님.
- 5일 보존 정책 자체 변경, 탐지기/앙상블/신호 생성 로직 변경, 매매/포트폴리오 로직 변경은 범위 밖.

---

## 6. 구현 방법론 (DDD: ANALYZE-PRESERVE-IMPROVE + Reproduction-First)

`quality.yaml` `development_mode: ddd` + CLAUDE.md Section 7 Rule 4(재현 우선):

1. **ANALYZE** — 현행 `_run_dart_crawl` 순서·FK 정의·로깅 설정 매핑(위 §2/§3 완료).
2. **PRESERVE / 재현 우선** — 수정 **전에** 실패 재현 테스트 작성:
   (a) 5일 초과 `disclosures`를 참조하는 `fund_signals` 행이 있을 때 `_cleanup_old_disclosures`가
   `IntegrityError`/`ForeignKeyViolation`을 유발하고 `_run_dart_crawl`이 `fetch_dart_disclosures`에
   도달하지 못함을 포착(현재 상태에서 실패/에러하는 테스트),
   (b) `caplog`로 `app.services.scheduler`/`dart_crawler` ERROR 레벨 로그가 캡처되지 않는(또는
   되는) 현행 동작 포착. 수정 전 (a)의 실패를 확인.
3. **IMPROVE** — FK SET NULL(마이그레이션) + 정리/수집 격리 + 로거 가시성 수정을 최소 변경으로 적용,
   (a)가 통과하고 수집이 진행됨을 확인. 배포 후 다음 크론에서 Pool A 비영·`journalctl` 가시성 검증.
