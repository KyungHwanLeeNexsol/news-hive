"""surge_auto_improvement_log 테이블 추가 (SPEC-AI-041).

평가 결과를 기반으로 자동 적용된 파라미터 변경 이력을 저장한다.
parameter_path는 dot notation 경로 (예: "ensemble.weights.theme_cluster").

Revision ID: 060_surge_auto_improvement_log
Revises: 059_surge_prediction_evaluation
Create Date: 2026-06-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "060_surge_auto_improvement_log"
down_revision = "059_surge_prediction_evaluation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "surge_auto_improvement_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "applied_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("evaluation_date", sa.Date(), nullable=False),
        sa.Column("parameter_path", sa.String(100), nullable=False),
        sa.Column("old_value", sa.Float(), nullable=False),
        sa.Column("new_value", sa.Float(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("rolling_window_days", sa.Integer(), nullable=False, server_default="5"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_surge_auto_improvement_log_evaluation_date",
        "surge_auto_improvement_log",
        ["evaluation_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_surge_auto_improvement_log_evaluation_date",
        table_name="surge_auto_improvement_log",
    )
    op.drop_table("surge_auto_improvement_log")
