"""SPEC-AI-073 REQ-AI073-002: fund_signals.disclosure_id FK를 ON DELETE SET NULL로 개정.

fund_signals는 예측 기록/평가 모집단(SPEC-AI-041/043/071)이다. disclosure_id는 이 신호를
촉발한 공시의 출처 메타데이터일 뿐이므로, 출처 공시가 5일 보존 정책(_cleanup_old_disclosures)
을 벗어나 삭제되어도 신호 레코드 자체는 반드시 보존되어야 한다. 기존 FK는 ON DELETE 미지정
(PostgreSQL 기본 NO ACTION/RESTRICT)이라 참조된 공시를 지울 수 없어 정리 벌크 DELETE가
ForeignKeyViolation으로 실패하고, 이 실패가 같은 함수 내 공시 수집 실행 자체를 차단했다
(2026-06-30~ 데이터 아웃티지, SPEC-AI-073 참고).

ON DELETE CASCADE는 사용하지 않는다 — 신호 레코드를 삭제하면 평가/백테스트 모집단이
손상되기 때문이다. SET NULL만이 "출처 공시 노후화와 무관하게 신호는 보존"이라는 의미에 맞다.

배포 하드닝(2026-07-08, SPEC-AI-073 후속 — 신규 SPEC 아님): 이 마이그레이션을 라이브
프로덕션에 적용하는 과정에서 실제 DeadlockDetected가 발생했다 — ALTER TABLE이 요구하는
AccessExclusiveLock이 앱의 지속적인 RowShareLock 트랜잭션(fund_signals 조회/삽입)과
충돌해 교착이 형성되었고, scripts/deploy.sh가 set -e로 배포를 중단시켰다(서비스 자체는
이전 버전으로 무중단 유지, 단 마이그레이션 미적용 상태로 배포가 막힘). 이를 완화하기 위해
DDL 실행에 짧은 lock_timeout + 재시도를 추가한다 — 의미(ON DELETE 거동)는 변경하지 않는다.

리비전 ID 재명명(2026-07-08, 같은 배포 하드닝 작업 중): 최초 리비전 ID
"068_fund_signal_disclosure_set_null"(36자)이 `alembic_version.version_num` 컬럼의
VARCHAR(32) 한도를 초과해 `StringDataRightTruncation`으로 실패했다 — 직전 리비전
"067_surge_detector_contribution"이 정확히 32자로 한도에 걸쳐 있었던 것과 대비된다.
이 DDL 자체(FK 재생성)는 lock_timeout+재시도 덕분에 이미 성공했었고, 실패는 그 이후
Alembic 자체의 버전 기록 UPDATE 단계에서 발생했다(트랜잭션 전체 롤백되어 데이터 유실 없음).
이후 신규 마이그레이션 작성 시 revision 문자열이 32자를 넘지 않도록 주의할 것.

Revision ID: 068_fund_signal_fk_set_null
Revises: 067_surge_detector_contribution
Create Date: 2026-07-08
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from alembic import op
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

revision = "068_fund_signal_fk_set_null"
down_revision = "067_surge_detector_contribution"
branch_labels = None
depends_on = None

_CONSTRAINT_NAME = "fund_signals_disclosure_id_fkey"

logger = logging.getLogger(__name__)

# 배포 하드닝 파라미터 — 근거는 아래 _run_ddl_with_lock_timeout_retry 참고.
_LOCK_TIMEOUT = "5s"
_MAX_ATTEMPTS = 5
_RETRY_BACKOFF_SECONDS = 3.0


def _run_ddl_with_lock_timeout_retry(
    ddl_fn: Callable[[], None],
    *,
    lock_timeout: str = _LOCK_TIMEOUT,
    max_attempts: int = _MAX_ATTEMPTS,
    backoff_seconds: float = _RETRY_BACKOFF_SECONDS,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> None:
    """짧은 lock_timeout 하에서 DDL을 실행하고, 실패 시 재시도한다.

    이 마이그레이션의 ALTER TABLE(DROP/ADD CONSTRAINT)은 AccessExclusiveLock을 요구하므로,
    지속적으로 쿼리되는 라이브 프로덕션 테이블에 대해 실행하면 앱의 RowShareLock 트랜잭션과
    교착할 수 있다(실제 2026-07-08 배포에서 DeadlockDetected 발생). 무한정 대기/교착 대신
    SET LOCAL lock_timeout으로 짧게 fail-fast시키고 몇 차례 재시도한다 — 일회성 배포 시점
    마이그레이션이므로 총 재시도 예산 수십 초는 허용 가능하다(lock_timeout=5s x 최대 5회
    시도 + 시도 사이 backoff=3s, 최악의 경우 약 37초 지연 후 raise).

    각 시도는 SAVEPOINT(connection.begin_nested())로 감싼다 — Alembic은 이 마이그레이션
    전체를 하나의 트랜잭션으로 감싸므로("Will assume transactional DDL" 로그), 실패한
    ALTER TABLE 문은 Postgres 규칙상 해당 (서브)트랜잭션 전체를 오염시켜 ROLLBACK 전까지
    이후 모든 명령을 거부한다. SAVEPOINT 단위로 롤백해야 다음 재시도가 깨끗한 상태에서
    시작할 수 있고, 성공 시 SAVEPOINT만 커밋하면 Alembic의 외곽 트랜잭션은 그대로 유지된다.
    SET LOCAL은 매 시도(매 SAVEPOINT)마다 새로 실행한다 — Postgres는 서브트랜잭션 롤백 시
    그 서브트랜잭션 안에서 변경된 GUC(lock_timeout 등)도 함께 되돌리므로, 재적용 없이는
    다음 시도에 lock_timeout이 사라질 수 있다.

    OperationalError만 재시도 대상으로 잡는다 — psycopg2의 lock_timeout 취소
    (QueryCanceled)와 DeadlockDetected는 모두 SQLAlchemy에서 OperationalError로 래핑된다.
    """
    connection = op.get_bind()
    last_error: OperationalError | None = None

    for attempt in range(1, max_attempts + 1):
        savepoint = connection.begin_nested()
        try:
            op.execute(text(f"SET LOCAL lock_timeout = '{lock_timeout}'"))
            ddl_fn()
        except OperationalError as exc:
            last_error = exc
            savepoint.rollback()
            logger.warning(
                "DDL attempt %d/%d failed (lock_timeout or deadlock), %s",
                attempt,
                max_attempts,
                "retrying" if attempt < max_attempts else "giving up",
                exc_info=exc,
            )
            if attempt >= max_attempts:
                break
            sleep_fn(backoff_seconds)
            continue
        else:
            savepoint.commit()
            return

    assert last_error is not None  # pragma: no cover - defensive, loop always sets it on failure path
    raise last_error


def upgrade() -> None:
    # @MX:WARN: [AUTO] 이 DDL은 지속적으로 쿼리되는 라이브 프로덕션 fund_signals 테이블에
    # AccessExclusiveLock을 요구한다 — lock_timeout+재시도 없이 실행하면 앱의 RowShareLock
    # 트랜잭션과 교착(deadlock)할 수 있다. _run_ddl_with_lock_timeout_retry 래핑을 제거하지 말 것.
    # @MX:REASON: 2026-07-08 실제 프로덕션 배포에서 DeadlockDetected 발생 확인
    # (pg_stat_activity에서 AccessExclusiveLock 대 RowShareLock 상호 대기 확인),
    # scripts/deploy.sh가 set -e로 실패 시 배포 자체가 중단됨 — "불필요한 복잡성"이 아님.
    def _do_upgrade_ddl() -> None:
        # PostgreSQL은 FK의 ON DELETE 거동을 in-place 변경할 수 없으므로 drop -> recreate.
        op.drop_constraint(_CONSTRAINT_NAME, "fund_signals", type_="foreignkey")
        op.create_foreign_key(
            _CONSTRAINT_NAME,
            "fund_signals",
            "disclosures",
            ["disclosure_id"],
            ["id"],
            ondelete="SET NULL",
        )

    _run_ddl_with_lock_timeout_retry(_do_upgrade_ddl)


def downgrade() -> None:
    # @MX:WARN: [AUTO] upgrade()와 동일한 라이브 테이블 잠금 위험 — lock_timeout+재시도 필수.
    # @MX:REASON: upgrade()와 동일한 DROP/ADD CONSTRAINT 패턴을 역순으로 수행하므로 동일한
    # AccessExclusiveLock 교착 위험이 있다. _run_ddl_with_lock_timeout_retry 래핑 유지할 것.
    def _do_downgrade_ddl() -> None:
        # 원복: ON DELETE 거동 없음(PostgreSQL 기본 NO ACTION/RESTRICT).
        op.drop_constraint(_CONSTRAINT_NAME, "fund_signals", type_="foreignkey")
        op.create_foreign_key(
            _CONSTRAINT_NAME,
            "fund_signals",
            "disclosures",
            ["disclosure_id"],
            ["id"],
        )

    _run_ddl_with_lock_timeout_retry(_do_downgrade_ddl)
