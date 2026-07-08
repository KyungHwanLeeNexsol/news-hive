"""SPEC-AI-073 후속 하드닝 — 마이그레이션 068 lock_timeout+재시도 로직 검증.

CLAUDE.md Rule 4(재현 우선): 로컬에는 프로덕션과 동일한 라이브 트래픽 하 PostgreSQL
데드락을 재현할 환경이 없다. 대신 alembic `op`와 커넥션을 MagicMock으로 대체해
"N번 lock_timeout/deadlock 실패 후 성공" 및 "재시도 모두 소진 후 예외 전파" 시나리오를
검증한다 — test_surge_universe_pool_bugfix.py::TestSurgeCollectOutcomesSSLRetry와 동일한
OperationalError 재시도 테스트 컨벤션(OperationalError(stmt, params, orig) 생성, monkeypatch
기반 mock 주입)을 따른다.

마이그레이션 파일명이 숫자로 시작해 일반 `import`가 불가능하므로 importlib으로 직접 로드한다.
"""

import importlib.util
import os

import pytest
from sqlalchemy.exc import OperationalError

_MIGRATION_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "alembic",
    "versions",
    "068_fund_signal_fk_set_null.py",
)


def _load_migration_068():
    """숫자로 시작하는 파일명은 표준 import 대상이 될 수 없으므로 파일 경로로 직접 로드한다."""
    spec = importlib.util.spec_from_file_location("migration_068_under_test", _MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _lock_timeout_error(message: str = "canceling statement due to lock timeout") -> OperationalError:
    return OperationalError("ALTER TABLE fund_signals ...", {}, Exception(message))


class MagicMockSavepoint:
    """connection.begin_nested()가 반환하는 SAVEPOINT 객체의 최소 가짜 구현."""

    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True


class MagicMockConnection:
    """op.get_bind()가 반환하는 커넥션의 최소 가짜 구현 — begin_nested() 호출마다 다음
    savepoint를 순서대로 반환한다."""

    def __init__(self, savepoints: list) -> None:
        self._savepoints = list(savepoints)
        self.begin_nested_call_count = 0

    def begin_nested(self) -> MagicMockSavepoint:
        savepoint = self._savepoints[self.begin_nested_call_count]
        self.begin_nested_call_count += 1
        return savepoint


class TestRunDdlWithLockTimeoutRetry:
    """마이그레이션 068의 _run_ddl_with_lock_timeout_retry 헬퍼 단위 검증."""

    def test_characterize_retries_and_succeeds_after_transient_lock_timeout_failures(
        self, monkeypatch,
    ) -> None:
        """2회 lock_timeout 실패 후 3번째 시도에서 성공하면, 실패한 시도만 rollback되고
        성공한 시도는 commit되며, 실패 횟수만큼만 backoff 대기가 발생해야 한다."""
        migration = _load_migration_068()

        savepoints = [MagicMockSavepoint() for _ in range(3)]
        connection = MagicMockConnection(savepoints)
        monkeypatch.setattr(migration.op, "get_bind", lambda: connection)
        monkeypatch.setattr(migration.op, "execute", lambda *a, **k: None)

        attempts = {"count": 0}

        def flaky_ddl() -> None:
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise _lock_timeout_error()

        sleep_calls = []
        migration._run_ddl_with_lock_timeout_retry(
            flaky_ddl, sleep_fn=sleep_calls.append,
        )

        assert attempts["count"] == 3, "2번 실패 후 3번째 시도에서 성공해야 한다"
        assert sleep_calls == [migration._RETRY_BACKOFF_SECONDS] * 2, (
            "실패한 시도(2회)마다만 backoff 대기가 있어야 하고, 성공 후에는 대기하지 않아야 한다"
        )
        assert savepoints[0].rolled_back is True
        assert savepoints[1].rolled_back is True
        assert savepoints[2].rolled_back is False
        assert savepoints[2].committed is True

    def test_raises_after_exhausting_all_retry_attempts(self, monkeypatch) -> None:
        """모든 재시도(_MAX_ATTEMPTS)가 lock_timeout으로 실패하면 마지막 예외를 그대로
        전파해야 하고, 마지막 실패 이후에는 추가 대기 없이 즉시 raise해야 한다."""
        migration = _load_migration_068()

        savepoints = [MagicMockSavepoint() for _ in range(migration._MAX_ATTEMPTS)]
        connection = MagicMockConnection(savepoints)
        monkeypatch.setattr(migration.op, "get_bind", lambda: connection)
        monkeypatch.setattr(migration.op, "execute", lambda *a, **k: None)

        def always_fails() -> None:
            raise _lock_timeout_error()

        sleep_calls = []
        with pytest.raises(OperationalError):
            migration._run_ddl_with_lock_timeout_retry(
                always_fails, sleep_fn=sleep_calls.append,
            )

        assert connection.begin_nested_call_count == migration._MAX_ATTEMPTS
        assert all(sp.rolled_back for sp in savepoints), "모든 시도가 rollback되어야 한다"
        assert len(sleep_calls) == migration._MAX_ATTEMPTS - 1, (
            "마지막 시도 실패 후에는 재시도하지 않으므로 대기 없이 즉시 raise해야 한다"
        )

    def test_non_operational_error_propagates_without_retry(self, monkeypatch) -> None:
        """lock_timeout/deadlock과 무관한 예외(OperationalError가 아님)는 재시도하지 않고
        즉시 전파해야 한다 — 무관한 오류를 무의미하게 재시도 예산으로 소모하지 않기 위함."""
        migration = _load_migration_068()

        savepoints = [MagicMockSavepoint()]
        connection = MagicMockConnection(savepoints)
        monkeypatch.setattr(migration.op, "get_bind", lambda: connection)
        monkeypatch.setattr(migration.op, "execute", lambda *a, **k: None)

        def raises_value_error() -> None:
            raise ValueError("무관한 프로그래밍 오류")

        sleep_calls = []
        with pytest.raises(ValueError):
            migration._run_ddl_with_lock_timeout_retry(
                raises_value_error, sleep_fn=sleep_calls.append,
            )

        assert connection.begin_nested_call_count == 1
        assert sleep_calls == []


class TestUpgradeDowngradeUseRetryHelper:
    """회귀 가드: upgrade()/downgrade()가 헬퍼를 우회해 직접 DDL을 호출하지 않는지 확인."""

    def test_upgrade_and_downgrade_delegate_to_retry_helper_with_same_semantics(
        self, monkeypatch,
    ) -> None:
        migration = _load_migration_068()

        delegated_calls = []

        def fake_retry_helper(ddl_fn, **kwargs):
            delegated_calls.append(ddl_fn)
            ddl_fn()

        monkeypatch.setattr(migration, "_run_ddl_with_lock_timeout_retry", fake_retry_helper)

        drop_calls = []
        create_calls = []
        monkeypatch.setattr(
            migration.op, "drop_constraint",
            lambda *a, **k: drop_calls.append((a, k)),
        )
        monkeypatch.setattr(
            migration.op, "create_foreign_key",
            lambda *a, **k: create_calls.append((a, k)),
        )

        migration.upgrade()
        migration.downgrade()

        assert len(delegated_calls) == 2, "upgrade/downgrade 각각 헬퍼를 통해 DDL을 실행해야 한다"
        assert len(drop_calls) == 2
        assert len(create_calls) == 2

        # 의미(ON DELETE 거동) 변경 없음 확인: upgrade=SET NULL, downgrade=미지정(원복)
        _, upgrade_kwargs = create_calls[0]
        _, downgrade_kwargs = create_calls[1]
        assert upgrade_kwargs.get("ondelete") == "SET NULL"
        assert "ondelete" not in downgrade_kwargs
