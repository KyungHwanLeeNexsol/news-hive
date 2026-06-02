"""surge_threshold_history 테이블 추가 (SPEC-AI-029).

적응형 surge 확률 임계값의 일별 산출 이력을 저장한다.
date 컬럼에 UNIQUE 제약을 적용하여 날짜당 단일 레코드를 보장한다.

Revision ID: 057_surge_threshold_history
Revises: 056_surge_data_integrity
Create Date: 2026-06-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "057_surge_threshold_history"
down_revision = "056_surge_data_integrity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "surge_threshold_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("win_rate_5d", sa.Float(), nullable=True),
        sa.Column("regime", sa.String(20), nullable=True),
        sa.Column("reason", sa.String(200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("date", name="uq_surge_threshold_history_date"),
    )
    op.create_index(
        "ix_surge_threshold_history_date",
        "surge_threshold_history",
        ["date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_surge_threshold_history_date", table_name="surge_threshold_history")
    op.drop_table("surge_threshold_history")
