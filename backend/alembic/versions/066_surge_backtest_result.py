"""SPEC-AI-069: surge_backtest_result 테이블 생성 (backtest 게이트 판정 영속화).

Revision ID: 066_surge_backtest_result
Revises: 065_surge_universe_members
Create Date: 2026-07-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "066_surge_backtest_result"
down_revision = "065_surge_universe_members"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # REQ-001: backtest 운영 게이트 pass/fail/insufficient 판정 영속화 테이블
    op.create_table(
        "surge_backtest_result",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_date", sa.Date(), nullable=False),
        sa.Column(
            "total_signals", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "directional_accuracy",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "average_return_pct", sa.Float(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "verdict",
            sa.String(length=20),
            nullable=False,
            comment="SPEC-AI-069 REQ-001: pass/fail/insufficient",
        ),
        sa.Column("config_hash", sa.String(length=16), nullable=False),
        sa.Column("min_signals", sa.Integer(), nullable=False),
        sa.Column("min_directional_accuracy", sa.Float(), nullable=False),
        sa.Column("lookback_days", sa.Integer(), nullable=False),
        sa.Column("by_combination_json", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        comment="SPEC-AI-069 REQ-001: backtest 운영 게이트 판정 결과",
    )
    op.create_index(
        "ix_surge_backtest_result_run_date",
        "surge_backtest_result",
        ["run_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_surge_backtest_result_run_date",
        table_name="surge_backtest_result",
    )
    op.drop_table("surge_backtest_result")
