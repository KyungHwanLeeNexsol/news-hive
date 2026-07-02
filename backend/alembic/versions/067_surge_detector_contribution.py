"""SPEC-AI-070: surge_detector_contribution 테이블 생성 (탐지기별 기여도 스냅샷).

Revision ID: 067_surge_detector_contribution
Revises: 066_surge_backtest_result
Create Date: 2026-07-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "067_surge_detector_contribution"
down_revision = "066_surge_backtest_result"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "surge_detector_contribution",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_date", sa.Date(), nullable=False),
        sa.Column("detector", sa.String(length=40), nullable=False),
        sa.Column("emission_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("solo_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("solo_tp", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("coincident_hit_rate", sa.Float(), nullable=True),
        sa.Column("unique_catch", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "retire_candidate", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "run_date", "detector", name="uq_surge_detector_contribution_run_date_detector"
        ),
    )
    op.create_index(
        "ix_surge_detector_contribution_run_date",
        "surge_detector_contribution",
        ["run_date"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_surge_detector_contribution_run_date", table_name="surge_detector_contribution"
    )
    op.drop_table("surge_detector_contribution")
