"""SPEC-AI-073 REQ-AI073-002: fund_signals.disclosure_id FK를 ON DELETE SET NULL로 개정.

fund_signals는 예측 기록/평가 모집단(SPEC-AI-041/043/071)이다. disclosure_id는 이 신호를
촉발한 공시의 출처 메타데이터일 뿐이므로, 출처 공시가 5일 보존 정책(_cleanup_old_disclosures)
을 벗어나 삭제되어도 신호 레코드 자체는 반드시 보존되어야 한다. 기존 FK는 ON DELETE 미지정
(PostgreSQL 기본 NO ACTION/RESTRICT)이라 참조된 공시를 지울 수 없어 정리 벌크 DELETE가
ForeignKeyViolation으로 실패하고, 이 실패가 같은 함수 내 공시 수집 실행 자체를 차단했다
(2026-06-30~ 데이터 아웃티지, SPEC-AI-073 참고).

ON DELETE CASCADE는 사용하지 않는다 — 신호 레코드를 삭제하면 평가/백테스트 모집단이
손상되기 때문이다. SET NULL만이 "출처 공시 노후화와 무관하게 신호는 보존"이라는 의미에 맞다.

Revision ID: 068_fund_signal_disclosure_set_null
Revises: 067_surge_detector_contribution
Create Date: 2026-07-08
"""

from __future__ import annotations

from alembic import op

revision = "068_fund_signal_disclosure_set_null"
down_revision = "067_surge_detector_contribution"
branch_labels = None
depends_on = None

_CONSTRAINT_NAME = "fund_signals_disclosure_id_fkey"


def upgrade() -> None:
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


def downgrade() -> None:
    # 원복: ON DELETE 거동 없음(PostgreSQL 기본 NO ACTION/RESTRICT).
    op.drop_constraint(_CONSTRAINT_NAME, "fund_signals", type_="foreignkey")
    op.create_foreign_key(
        _CONSTRAINT_NAME,
        "fund_signals",
        "disclosures",
        ["disclosure_id"],
        ["id"],
    )
