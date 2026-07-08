"""SPEC-AI-073 재현 우선 테스트 — DART 공시 수집 차단 복구 + app.services 로거 가시성.

CLAUDE.md Rule 4(재현 우선): 아래 재현 테스트들은 수정 **전**에 작성되어 현재 코드에서
실패/에러함을 먼저 확인했고(RED), 이후 최소 수정을 적용해 통과함을 확인한다(GREEN).

- REQ-AI073-002: fund_signals.disclosure_id FK ON DELETE SET NULL (TestCleanupDisclosuresForeignKey)
- REQ-AI073-003: app.services.* 로거 ERROR/CRITICAL 가시성 (TestLoggerVisibility)

REQ-AI073-001(정리/수집 격리)의 재현 테스트는 기존 컨벤션(MagicMock 기반)과 일관되게
backend/tests/test_services/test_scheduler.py::TestRunDartCrawl 에 추가한다.
"""

import logging
import os

from sqlalchemy import text

from app.models.disclosure import Disclosure
from app.services.scheduler import _cleanup_old_disclosures


def _enable_sqlite_fk(db) -> None:
    """SQLite는 기본적으로 FK 제약을 강제하지 않으므로 테스트에서 명시적으로 켠다.

    프로덕션(PostgreSQL)은 항상 FK를 강제하므로 이 헬퍼는 테스트 인프라(SQLite)에서만 필요하다.
    """
    db.execute(text("PRAGMA foreign_keys=ON"))


class TestCleanupDisclosuresForeignKey:
    """REQ-AI073-002 — fund_signals.disclosure_id FK ON DELETE 거동."""

    def test_characterize_cleanup_deletes_stale_disclosure_and_nulls_referencing_signal(
        self, db, make_stock, make_disclosure, make_fund_signal,
    ) -> None:
        """AC-073-001/002: 5일 초과 공시를 참조하는 fund_signal이 있어도 정리가 성공하고,
        참조 신호는 삭제되지 않으며 disclosure_id가 NULL로 설정된다(SET NULL, CASCADE 아님).

        재현(Rule 4): 마이그레이션 068(ON DELETE SET NULL) 적용 전에는 이 테스트가
        IntegrityError로 에러났음을 확인했다(수정 전 RED) — FK 개정 후 통과한다(GREEN).
        """
        _enable_sqlite_fk(db)
        stock = make_stock()
        old_disclosure = make_disclosure(stock_id=stock.id, rcept_dt="20200101")
        signal = make_fund_signal(stock_id=stock.id, disclosure_id=old_disclosure.id)
        db.commit()
        old_disclosure_id = old_disclosure.id  # commit() 후 만료되므로 미리 캡처
        signal_id = signal.id

        _cleanup_old_disclosures(db)

        remaining = db.query(Disclosure).filter(Disclosure.id == old_disclosure_id).first()
        assert remaining is None, "5일 초과 공시는 삭제되어야 한다"

        refreshed_signal = db.query(type(signal)).filter(type(signal).id == signal_id).first()
        assert refreshed_signal is not None, "참조 신호는 삭제되지 않아야 한다"
        assert refreshed_signal.disclosure_id is None, (
            "참조 신호는 삭제되지 않고 disclosure_id만 NULL로 설정되어야 한다(SET NULL)"
        )

    def test_unreferenced_old_disclosure_still_deleted_normally(
        self, db, make_disclosure,
    ) -> None:
        """EC-2: fund_signals가 참조하지 않는 5일 초과 공시는 FK 개정과 무관하게 정상 삭제된다."""
        _enable_sqlite_fk(db)
        old_disclosure = make_disclosure(rcept_dt="20200101")
        db.commit()
        old_disclosure_id = old_disclosure.id  # commit() 후 만료되므로 미리 캡처

        _cleanup_old_disclosures(db)

        remaining = db.query(Disclosure).filter(Disclosure.id == old_disclosure_id).first()
        assert remaining is None


class TestLoggerVisibility:
    """REQ-AI073-003 — app.services.scheduler/dart_crawler ERROR/CRITICAL 가시성.

    근본 원인: backend/alembic/env.py의 `fileConfig(config.config_file_name)` 호출이
    `disable_existing_loggers` 기본값(True)으로 실행되어, alembic.ini의 [loggers]
    (root/sqlalchemy/alembic만 나열)에 없는 기존 로거(app.services.scheduler,
    app.services.dart_crawler 등)를 `.disabled = True`로 영구 비활성화시킨다.
    `Logger.isEnabledFor()`는 `self.disabled`를 최우선으로 검사하므로, 레벨 필터와
    무관하게 ERROR/CRITICAL 포함 모든 로그 호출이 완전한 no-op이 된다.
    `_run_migrations()`가 앱 시작 시 1회 실행되며, 이후 프로세스 수명 내내 복구되지 않는다.
    """

    ALEMBIC_INI_PATH = os.path.join(
        os.path.dirname(__file__), "..", "alembic.ini"
    )

    def _fresh_logger(self, name: str) -> logging.Logger:
        """테스트 간 격리를 위해 매번 새 이름의 로거를 만들고 정리한다."""
        logger = logging.getLogger(name)
        logger.disabled = False
        logger.handlers = []
        logger.propagate = True
        return logger

    def test_characterize_fileconfig_default_disables_preexisting_app_loggers(self) -> None:
        """재현(Rule 4): alembic.ini의 fileConfig를 기본값(disable_existing_loggers=True)으로
        호출하면, 이미 존재하는 app.services.* 로거가 비활성화되어 ERROR/CRITICAL도
        caplog에 잡히지 않는다 — 수정 전 실제 프로덕션 동작 재현.
        """
        logger = self._fresh_logger("app.services.scheduler.__repro_pre_fix__")
        assert logger.disabled is False

        from logging.config import fileConfig

        # env.py 수정 전 코드와 동일한 호출: disable_existing_loggers 인자 없음(기본값 True)
        fileConfig(self.ALEMBIC_INI_PATH)

        assert logger.disabled is True, (
            "fileConfig 기본값(disable_existing_loggers=True)은 alembic.ini에 나열되지 않은 "
            "기존 로거를 비활성화한다 — 이것이 8일간 로그 침묵의 근본 원인이다"
        )

        # disabled=True인 로거는 레벨과 무관하게 완전한 no-op이 된다(Logger.isEnabledFor 최우선 검사)
        assert logger.isEnabledFor(logging.CRITICAL) is False

    def test_env_py_fileconfig_call_preserves_existing_app_loggers(self) -> None:
        """수정 후: env.py는 `fileConfig(config.config_file_name, disable_existing_loggers=False)`
        를 호출해야 한다 — 기존 app.services.* 로거가 비활성화되지 않고 ERROR/CRITICAL이
        정상적으로 caplog/핸들러에 도달한다(회귀 가드 + 근본 수정 검증).
        """
        logger = self._fresh_logger("app.services.dart_crawler.__repro_post_fix__")
        assert logger.disabled is False

        from logging.config import fileConfig

        # env.py 수정 후 코드와 동일한 호출
        fileConfig(self.ALEMBIC_INI_PATH, disable_existing_loggers=False)

        assert logger.disabled is False, (
            "disable_existing_loggers=False이면 기존 로거가 비활성화되지 않아야 한다"
        )
        assert logger.isEnabledFor(logging.CRITICAL) is True

    def test_env_py_source_uses_disable_existing_loggers_false(self) -> None:
        """회귀 가드: backend/alembic/env.py 소스가 fileConfig 호출 시
        disable_existing_loggers=False를 명시하는지 확인한다(실수로 되돌아가는 것 방지).
        """
        env_py_path = os.path.join(
            os.path.dirname(__file__), "..", "alembic", "env.py"
        )
        with open(env_py_path, encoding="utf-8") as f:
            source = f.read()

        assert "disable_existing_loggers=False" in source, (
            "env.py의 fileConfig 호출은 disable_existing_loggers=False를 명시해야 "
            "app.services.* 로거가 마이그레이션 실행 후에도 비활성화되지 않는다"
        )

    def test_main_configure_json_logging_restores_root_handler_after_disabling(
        self, capsys,
    ) -> None:
        """방어선 2: main.py의 로깅 설정이 함수화되어 있고, 마이그레이션 직후 재적용하면
        alembic.ini의 [logger_root] 재구성(핸들러 교체) 이후에도 JSON 로깅이 복원된다.

        _run_migrations() 실행 후 root handler가 alembic.ini의 plain 콘솔 핸들러로
        교체되더라도, main.py가 마이그레이션 직후 로깅 설정을 재적용해 root를 되돌린다.

        AC-073-003: "최소 1개 시나리오는 실제 핸들러 출력으로 검증" — caplog는 자체 핸들러를
        root에 부착하는데 `_configure_json_logging()`이 `logging.root.handlers`를 통째로
        교체하면 caplog 핸들러도 함께 사라지므로, 여기서는 실제 StreamHandler 출력(stderr)을
        capsys로 직접 검증한다(실제 journalctl이 캡처하는 대상과 동일한 경로).
        """
        from app.main import _configure_json_logging

        logger = self._fresh_logger("app.services.scheduler.__repro_restore__")

        _configure_json_logging()
        assert logging.root.level == logging.INFO

        from logging.config import fileConfig
        fileConfig(self.ALEMBIC_INI_PATH, disable_existing_loggers=False)
        # alembic.ini [logger_root]는 level=WARNING, handlers=console로 root를 덮어쓴다
        assert logging.root.level == logging.WARNING

        # main.py가 마이그레이션 직후 재적용하는 것과 동일한 호출
        _configure_json_logging()

        assert logging.root.level == logging.INFO, "root 레벨이 INFO로 복원되어야 한다"
        assert logger.disabled is False

        capsys.readouterr()  # 이전 캡처 버퍼 비우기
        logger.error("post-restore error test")
        captured = capsys.readouterr()
        assert "post-restore error test" in captured.err
        assert '"level": "ERROR"' in captured.err, "JSON 포맷(main.py 설정)으로 출력되어야 한다"
